"""Multi-hop cascades on the quality, qualification and first-article paths.

Three single requests in this API each fan out several hops deep: an in-process
subgroup that comes out out-of-control on a safety-critical characteristic, a
customer's full approval of a production-part approval package, and a
first-article rejection that unwinds the shop resources the run had taken. Every
test here drives exactly one of those requests and pins each hop the same
request must have applied, together with the negative control that shows the
later hops stay put when the trigger is absent.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    PROGRAM_MANAGER_HEADERS,
    QUALITY_INSPECTOR_ALT_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
)

# The free-length print limits the canonical safety-critical characteristic carries.
_LSL = 59.5
_USL = 60.5
_CPK_FLOOR = 1.333

# Three readings a tenth of the binding distance apart: Cpk 3.333, comfortably
# above the 1.333 floor.
_TIGHT_SUBGROUP = [59.95, 60.0, 60.05]

# Three readings four tenths of the binding distance apart: Cpk 0.833, below the
# floor, with every reading still inside the specification band.
_WIDE_SUBGROUP = [59.8, 60.0, 60.2]

_AUTO_SAFETY_PROGRAM = {
    "program_code": "PGM-AUTO-1",
    "customer_name": "Kestrel Restraint Systems",
    "application_class": C.CLASS_AUTOMOTIVE_SAFETY,
    "ppap_level": 3,
    "committed_pieces": 500_000,
    "minimum_order_quantity": 25_000,
    "required_salt_spray_hours": 96,
    "min_fatigue_margin": 1.2,
    "required_ppk": 1.33,
    "amortization_method": C.FORECAST_BASIS,
}

_HOOK_POSITION_PLAN = {
    "char_code": C.CHAR_HOOK_POSITION,
    "nominal_value": 24.0,
    "lsl": 23.7,
    "usl": 24.3,
    "is_safety_critical": False,
    "cpk_floor": 1.0,
}


def _quarantine_cascade_world(api: ApiClient, characteristics=None) -> X.World:
    """An allocated 25 000-piece lot on a complete, stress-relieved, approved run.

    Two in-control in-process subgroups per characteristic are recorded while the
    run is still coiling, so a third subgroup pools nine measurements.
    """
    world = X.build_world(
        api,
        "spc",
        program=_AUTO_SAFETY_PROGRAM,
        design={"part_number": "D1-AUTO"},
        characteristics=characteristics,
        tooling={"tool_code": "TL-D1"},
        activation_clock=C.CLOCK_INSIDE_SETUP_WINDOW,
    )
    for characteristic in world.characteristics:
        world.spc_records.append(X.record_spc_subgroup(api, world.run_id, characteristic))

    world.run = X.complete_run(api, world.run_id, 25_500, 500)
    world.oven = X.commission_oven(api)
    world.batch = X.schedule_batch(
        api, world.oven_id, world.run_id, peening_requested=True
    )
    X.pin_clock(api, C.CLOCK_BATCH_WINDOW_START)
    X.start_batch(api, world.batch_id)
    world.batch = X.discharge_batch(api, world.batch_id, True)

    world.program = X.price_program(api, world.program, world.design_id)
    world.submission = X.file_submission(
        api, world.program_id, world.design_id, ppap_level=3
    )
    world.submission = X.customer_verdict(
        api, world.submission_id, world.program_id, C.DECISION_APPROVE
    )
    world.lot = X.allocate_lot(api, world.run_id, world.program_id, 25_000)
    world.program = X.refresh_program(api, world.program_id)
    world.design = X.refresh_design(api, world.design_id)
    world.tooling = X.refresh_tooling(api, world.tooling_id)
    return world


def test_out_of_control_safety_subgroup_cascades_to_lot_quarantine_and_posture(
    api: ApiClient,
) -> None:
    """PRD §3.8: "An in-process record whose `control_state` comes out `OUT_OF_CONTROL`
    on a characteristic whose `is_safety_critical` is true escalates the whole run, and
    the escalation is a five-hop cascade that a naive implementation will only get half
    right."
    PRD §3.8: "Hop two: the run's `quality_status` transitions `OPEN → SPC_HOLD`."
    PRD §3.8: "Hop three: every shipment lot of this run whose `lot_status` is
    `ALLOCATED` or `PACKED` transitions to `QUARANTINED` with `quarantine_reason` set to
    `SPC_HOLD_CASCADE`."
    PRD §3.8: "Hop four: for each lot so quarantined, the lot's owning program has the
    lot's `piece_count` added back to `open_commitment_pieces`, has
    `quarantined_lot_count` increased by 1, and has `allocated_pieces` decreased by that
    same `piece_count`."
    PRD §3.8: "Hop five: because `quarantined_lot_count` has risen above zero, each
    affected program's `delivery_posture` is re-derived, which drops an `ON_TRACK`
    program to `AT_RISK`."
    PRD §2.10: "When they do, all effects are applied within the same request —
    consistency is immediate, never eventual — and each mutated row has its own
    `updated_at` refreshed and its own `version` advanced under the rules of section
    2.4."

    Design: Difficulty/transitive_cascade/spc_violation_quarantine_posture_chain_five_hops
    """
    world = _quarantine_cascade_world(api)

    assert world.lot["lot_status"] == C.LOT_ALLOCATED, (
        "the lot must be allocated before the cascade, or hop three has nothing to quarantine"
    )
    assert world.program["delivery_posture"] == C.POSTURE_ON_TRACK, (
        "an approved package with no quarantine and no held run is ON_TRACK before the cascade"
    )

    response = api.record_inspection(
        world.run_id,
        F.measurement_payload(world.characteristic_id, _WIDE_SUBGROUP),
        QUALITY_INSPECTOR_HEADERS,
    )
    record = validate_success(response, 201)

    # Hop one — the record itself.
    assert record["record_kind"] == C.RECORD_KIND_SPC, (
        "the inspections endpoint stamps record_kind SPC from the endpoint itself"
    )
    assert record["cpk_value"] == 0.833, (
        f"a 0.2 mm sigma against a 0.5 mm binding distance gives Cpk 0.833, got {record['cpk_value']}"
    )
    assert record["control_state"] == C.CONTROL_OUT_OF_CONTROL, (
        "Cpk 0.833 is below the characteristic's 1.333 floor, so the record is OUT_OF_CONTROL"
    )
    assert record["ppk_value"] == 1.571, (
        "nine pooled measurements — two tight subgroups plus this wide one — give Ppk 1.571, "
        f"got {record['ppk_value']}"
    )

    # Hop two — the run's quality axis moves while its process axis does not.
    run = X.refresh_run(api, world.run_id)
    assert run["quality_status"] == C.QUALITY_SPC_HOLD, (
        "hop two takes the run's quality_status from OPEN to SPC_HOLD"
    )
    assert run["process_status"] == C.PROCESS_COMPLETE, (
        "the two status axes are independent: a COMPLETE run may sit on SPC_HOLD"
    )
    assert run["min_cpk_observed"] == 0.833, (
        f"min_cpk_observed drops to the lowest Cpk on the run, got {run['min_cpk_observed']}"
    )
    assert run["min_ppk_observed"] == 1.571, (
        f"min_ppk_observed drops to the lowest safety-critical SPC Ppk, got {run['min_ppk_observed']}"
    )

    # Hop three — the allocated lot is quarantined by the cascade, not by an inspector.
    lot = X.refresh_lot(api, world.lot_id)
    assert lot["lot_status"] == C.LOT_QUARANTINED, (
        f"hop three quarantines the ALLOCATED lot, got {lot['lot_status']}"
    )
    assert lot["quarantine_reason"] == C.QUARANTINE_SPC_HOLD_CASCADE, (
        f"an automatic quarantine stamps SPC_HOLD_CASCADE, got {lot['quarantine_reason']}"
    )

    # Hop four — the program's piece commitment moves back, conserving the total.
    program = X.refresh_program(api, world.program_id)
    assert program["quarantined_lot_count"] == 1, (
        f"hop four raises quarantined_lot_count to 1, got {program['quarantined_lot_count']}"
    )
    assert program["allocated_pieces"] == 0, (
        f"hop four returns all 25 000 allocated pieces, got {program['allocated_pieces']}"
    )
    assert program["open_commitment_pieces"] == 500_000, (
        f"hop four puts the pieces back on the commitment, got {program['open_commitment_pieces']}"
    )
    assert program["shipped_pieces"] == 0, "a quarantine never ships anything"
    A.assert_commitment_conserved(program)

    # Hop five — the posture is re-derived from the risen quarantine count.
    assert program["delivery_posture"] == C.POSTURE_AT_RISK, (
        "an approved program with one quarantined lot is re-derived to AT_RISK, "
        f"got {program['delivery_posture']}"
    )


def test_out_of_control_safety_subgroup_leaves_price_snapshot_and_tooling_ledger_alone(
    api: ApiClient,
) -> None:
    """PRD §3.8: "The server stamps `record_kind` as `SPC` — again from the endpoint,
    never from the body — stamps `inspected_by_user_id`, and computes the full statistic
    set of section 3.7 including the pooled `ppk_value`."
    PRD §3.7: "On an in-process record it is computed by pooling every measurement of
    every inspection record whose `record_kind` is `SPC` and which shares both this
    record's `run_id` and its `characteristic_id`, including the record being created,
    into one single sample; records belonging to other runs never pool in, and the order
    in which records are pooled does not change the result."
    PRD §3.11: "Snapshotting matters: a later re-quote cannot move the price of a lot
    already allocated."
    PRD §2.4: "`CustomerProgram.version` is incremented **only** by the program quoting
    operation, `POST /customer-programs/{id}/quote`, and by nothing else."

    Design: Difficulty/transitive_cascade/spc_violation_quarantine_posture_chain_five_hops
    """
    world = _quarantine_cascade_world(api)

    version_before = world.program["version"]
    assert world.lot["unit_price_cents"] == 24, (
        f"the lot snapshots the quoted 24-cent unit price, got {world.lot['unit_price_cents']}"
    )
    assert world.lot["tooling_amort_per_piece_cents"] == 4, (
        "the lot snapshots the quote-time 4-cent amortization, not the tool's frozen 10, "
        f"got {world.lot['tooling_amort_per_piece_cents']}"
    )
    assert world.lot["extended_price_cents"] == 600_000, (
        f"25 000 pieces at 24 cents is 600 000 cents, got {world.lot['extended_price_cents']}"
    )

    response = api.record_inspection(
        world.run_id,
        F.measurement_payload(world.characteristic_id, _WIDE_SUBGROUP),
        QUALITY_INSPECTOR_HEADERS,
    )
    record = validate_success(response, 201)

    expected_cpk = A.expected_cpk_value(_WIDE_SUBGROUP, _LSL, _USL)
    assert expected_cpk == 0.833, "the short-run index of the wide subgroup is 0.833"
    assert record["cpk_value"] == expected_cpk, (
        f"the record carries the short-run index of its own subgroup, got {record['cpk_value']}"
    )
    pooled = _TIGHT_SUBGROUP + _TIGHT_SUBGROUP + _WIDE_SUBGROUP
    expected_ppk = A.expected_ppk_value(pooled, _LSL, _USL)
    assert expected_ppk == 1.571, "the nine pooled measurements give a long-run index of 1.571"
    assert record["ppk_value"] == expected_ppk, (
        f"the record pools every SPC subgroup of this run and characteristic, got {record['ppk_value']}"
    )
    assert record["control_state"] == A.expected_control_state(
        _WIDE_SUBGROUP, _LSL, _USL, _CPK_FLOOR
    ), "the rounded index below the floor decides the control state"

    lot = X.refresh_lot(api, world.lot_id)
    assert lot["unit_price_cents"] == 24, (
        "the quarantine cascade never re-prices the lot it quarantines"
    )
    assert lot["tooling_amort_per_piece_cents"] == 4, (
        "the snapshotted per-piece amortization survives the quarantine"
    )
    assert lot["extended_price_cents"] == 600_000, (
        "the snapshotted extended price survives the quarantine"
    )

    tooling = X.refresh_tooling(api, world.tooling_id)
    assert tooling["recovered_cents"] == 0, (
        f"nothing shipped, so the tooling ledger has recovered nothing, got {tooling['recovered_cents']}"
    )
    assert tooling["unamortized_cents"] == 4_800_000, (
        "a quarantine posts no recovery, so the whole capitalised cost is still outstanding"
    )
    A.assert_tooling_ledger_conserved(tooling)

    program = X.refresh_program(api, world.program_id)
    assert program["version"] == version_before, (
        "the five-hop cascade moves piece counters and posture but never the program's version, "
        f"got {program['version']} against {version_before}"
    )


def test_out_of_control_non_safety_subgroup_stops_after_the_record(
    api: ApiClient,
) -> None:
    """PRD §3.8: "An out-of-control record on a characteristic whose `is_safety_critical`
    is false records its control state and nothing more — the quality axis is untouched,
    no lot is quarantined, and no counter moves."
    PRD §3.7: "At the run level, `min_cpk_observed` is refreshed to the lowest
    `cpk_value` across all of the run's inspection records, while `min_ppk_observed` is
    refreshed to the lowest `ppk_value` across only those of the run's records whose
    `record_kind` is `SPC` and whose characteristic has `is_safety_critical` true."
    PRD §3.1: "Otherwise, if `quarantined_lot_count` is at least 1 **or** such a held run
    exists, the posture is `AT_RISK`."

    Design: Difficulty/transitive_cascade/spc_violation_quarantine_posture_chain_five_hops
    """
    world = _quarantine_cascade_world(api, characteristics=[{}, _HOOK_POSITION_PLAN])
    hook = world.characteristics[1]
    assert hook["is_safety_critical"] is False, (
        "the negative control needs a characteristic the escalation rule ignores"
    )

    off_print = X.out_of_control_subgroup(hook)
    response = api.record_inspection(
        world.run_id,
        F.measurement_payload(hook["id"], off_print),
        QUALITY_INSPECTOR_HEADERS,
    )
    record = validate_success(response, 201)

    assert record["record_kind"] == C.RECORD_KIND_SPC, (
        "the record is an in-process record like any other"
    )
    assert record["control_state"] == C.CONTROL_OUT_OF_CONTROL, (
        "a reading above the upper specification limit is out of control whatever the weighting"
    )

    run = X.refresh_run(api, world.run_id)
    assert run["quality_status"] == C.QUALITY_OPEN, (
        f"hop two does not fire for a non-safety-critical characteristic, got {run['quality_status']}"
    )
    assert run["process_status"] == C.PROCESS_COMPLETE, "the process axis is untouched"
    assert run["min_ppk_observed"] == 3.333, (
        "min_ppk_observed reads only safety-critical SPC records, so the hook subgroup leaves it "
        f"at the free-length figure, got {run['min_ppk_observed']}"
    )

    lot = X.refresh_lot(api, world.lot_id)
    assert lot["lot_status"] == C.LOT_ALLOCATED, (
        f"hop three does not fire, so the lot stays allocated, got {lot['lot_status']}"
    )
    assert lot["quarantine_reason"] is None, (
        "no quarantine happened, so no reason is stamped"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["quarantined_lot_count"] == 0, (
        f"hop four does not fire, so no counter moves, got {program['quarantined_lot_count']}"
    )
    assert program["allocated_pieces"] == 25_000, (
        f"the allocated pieces stay allocated, got {program['allocated_pieces']}"
    )
    assert program["open_commitment_pieces"] == 475_000, (
        f"the commitment stays consumed, got {program['open_commitment_pieces']}"
    )
    assert program["delivery_posture"] == C.POSTURE_ON_TRACK, (
        "with no quarantined lot and no held run the posture stays ON_TRACK, "
        f"got {program['delivery_posture']}"
    )
    A.assert_commitment_conserved(program)


def _submitted_package_world(api: ApiClient) -> X.World:
    """A SUBMITTED level-3 package over a priced program and an accepted first article.

    The run is left `RUNNING` — the package only needs one run whose first-article
    verdict was `ACCEPTED` — and the design is still `PROTOTYPE_RELEASED`, so the
    approval cascade has somewhere to go.
    """
    world = X.build_world(
        api,
        "running",
        program=_AUTO_SAFETY_PROGRAM,
        design={"part_number": "D1-AUTO"},
        tooling={"tool_code": "TL-D1"},
        activation_clock=C.CLOCK_INSIDE_SETUP_WINDOW,
    )
    world.program = X.price_program(api, world.program, world.design_id)
    world.submission = X.file_submission(
        api, world.program_id, world.design_id, ppap_level=3
    )
    world.program = X.refresh_program(api, world.program_id)
    return world


def test_full_customer_approval_cascades_design_tooling_and_quote_freeze(
    api: ApiClient,
) -> None:
    """PRD §3.10: "`APPROVE` is full release and drives the deepest cascade in the
    system, four hops long."
    PRD §3.10: "Hop one sets `submission_status` to `APPROVED`, a terminal status."
    PRD §3.10: "Hop two promotes the design `PROTOTYPE_RELEASED → PRODUCTION_RELEASED`."
    PRD §3.10: "Hop three, fired by that promotion, takes every `PENDING` tooling asset
    of the design to `AMORTIZING`, freezing `amortization_basis_pieces` from the
    program's `committed_pieces` and `amort_per_piece_cents` as the cost divided by that
    basis rounded up."
    PRD §3.10: "Hop four sets the program's `quote_frozen` to true — the commercial terms
    are now contractual and no further quote may be run — and re-derives
    `delivery_posture`, which reaches `ON_TRACK` on a program with no quarantined lots
    and no held run."
    PRD §3.10: "Every verdict stamps `reviewed_by_program_id` from the header and
    `decided_at` from the logical clock, and every verdict re-derives the program's
    `delivery_posture`."

    Design: Difficulty/transitive_cascade/ppap_approval_production_release_amortization_chain_four_hops
    """
    world = _submitted_package_world(api)
    assert world.design["release_status"] == C.RELEASE_PROTOTYPE, (
        "hop two needs a PROTOTYPE_RELEASED design to promote"
    )
    assert world.tooling["amortization_status"] == C.AMORT_PENDING, (
        "hop three needs a PENDING tooling asset to arm"
    )
    assert world.program["quote_frozen"] is False, "hop four needs an unfrozen quote"

    response = api.review_submission(
        world.submission_id,
        {"decision": C.DECISION_APPROVE},
        world.customer,
    )
    submission = validate_success(response)

    # Hop one.
    assert submission["submission_status"] == C.SUBMISSION_APPROVED, (
        f"hop one takes the package to APPROVED, got {submission['submission_status']}"
    )
    assert submission["round_no"] == 1, (
        f"the package was decided on its first round, got {submission['round_no']}"
    )
    assert submission["reviewed_by_program_id"] == world.program_id, (
        "the verdict stamps the deciding program from the header"
    )
    assert is_iso8601_timestamp(submission["decided_at"]), (
        f"decided_at must be an ISO 8601 instant, got {submission['decided_at']!r}"
    )
    assert submission["decided_at"].startswith("2026-08-05T08:30:00"), (
        "decided_at is stamped from the logical clock, which reads 2026-08-05T08:30:00Z, "
        f"got {submission['decided_at']!r}"
    )

    # Hop two.
    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_PRODUCTION, (
        f"hop two promotes the design to PRODUCTION_RELEASED, got {design['release_status']}"
    )

    # Hop three.
    tooling = X.refresh_tooling(api, world.tooling_id)
    assert tooling["amortization_status"] == C.AMORT_AMORTIZING, (
        f"hop three arms the tool, got {tooling['amortization_status']}"
    )
    assert tooling["amortization_basis_pieces"] == 500_000, (
        "the basis freezes from the program's committed_pieces, got "
        f"{tooling['amortization_basis_pieces']}"
    )
    assert tooling["amort_per_piece_cents"] == 10, (
        "4 800 000 cents over a 500 000-piece basis rounds up to 10 cents a piece, got "
        f"{tooling['amort_per_piece_cents']}"
    )
    assert tooling["recovered_cents"] == 0, (
        "arming the tool is not a recovery posting, got "
        f"{tooling['recovered_cents']}"
    )
    assert tooling["unamortized_cents"] == 4_800_000, (
        f"the whole capitalised cost is still outstanding, got {tooling['unamortized_cents']}"
    )
    A.assert_tooling_ledger_conserved(tooling)

    # Hop four.
    program = X.refresh_program(api, world.program_id)
    assert program["quote_frozen"] is True, (
        "hop four freezes the quote, got quote_frozen "
        f"{program['quote_frozen']}"
    )
    assert program["delivery_posture"] == C.POSTURE_ON_TRACK, (
        "an approved package with no quarantine and no held run re-derives to ON_TRACK, "
        f"got {program['delivery_posture']}"
    )


def test_interim_approval_stops_before_the_promotion_and_amortization_hops(
    api: ApiClient,
) -> None:
    """PRD §3.10: "The submission moves to `INTERIM_APPROVED` with the cap recorded, and
    `delivery_posture` is re-derived — an interim verdict counts as an approval for
    posture purposes, so a blocked program becomes `ON_TRACK` or `AT_RISK`."
    PRD §3.10: "What it deliberately does **not** do is promote anything: the design
    stays `PROTOTYPE_RELEASED` and every tooling asset stays `PENDING`, because only a
    full `APPROVE` arms amortization."
    PRD §3.4: "Both `amortization_basis_pieces` and `amort_per_piece_cents` stay null:
    until the customer has granted full approval, nobody knows over how many pieces the
    tool will be recovered."

    Design: Difficulty/transitive_cascade/ppap_approval_production_release_amortization_chain_four_hops
    """
    world = _submitted_package_world(api)

    response = api.review_submission(
        world.submission_id,
        {"decision": C.DECISION_INTERIM_APPROVE, "interim_piece_cap": 5_000},
        world.customer,
    )
    submission = validate_success(response)
    assert submission["submission_status"] == C.SUBMISSION_INTERIM_APPROVED, (
        f"the interim verdict lands on INTERIM_APPROVED, got {submission['submission_status']}"
    )
    assert submission["interim_piece_cap"] == 5_000, (
        f"the cap is recorded on the submission, got {submission['interim_piece_cap']}"
    )

    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_PROTOTYPE, (
        f"an interim verdict promotes nothing, got {design['release_status']}"
    )

    tooling = X.refresh_tooling(api, world.tooling_id)
    assert tooling["amortization_status"] == C.AMORT_PENDING, (
        f"only a full approval arms amortization, got {tooling['amortization_status']}"
    )
    assert tooling["amortization_basis_pieces"] is None, (
        "the basis stays null until full approval, got "
        f"{tooling['amortization_basis_pieces']}"
    )
    assert tooling["amort_per_piece_cents"] is None, (
        f"the per-piece rate stays null until full approval, got {tooling['amort_per_piece_cents']}"
    )
    assert tooling["unamortized_cents"] == 4_800_000, (
        "the ledger opens with the whole cost outstanding and an interim verdict does not move it"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["quote_frozen"] is False, (
        f"the quote freeze belongs to the full approval alone, got {program['quote_frozen']}"
    )
    assert program["delivery_posture"] == C.POSTURE_ON_TRACK, (
        "an interim verdict counts as an approval for posture, so the program leaves BLOCKED, "
        f"got {program['delivery_posture']}"
    )


def test_full_approval_freezes_the_basis_the_computed_recovery_read_uses(
    api: ApiClient,
) -> None:
    """PRD §3.4: "The `PENDING → AMORTIZING` promotion fires as a system event when the
    tool's design reaches `PRODUCTION_RELEASED`, and it is the moment the amortization
    basis is frozen: `amortization_basis_pieces` takes the owning program's
    `committed_pieces`, and `amort_per_piece_cents` becomes `original_cost_cents` divided
    by that basis, rounded **up** to the next whole cent."
    PRD §3.4: "Under `FORECAST_BASIS` — a straight-line forecast recovery — the amount is
    the lot's `piece_count` multiplied by the tool's frozen `amort_per_piece_cents`,
    capped at the tool's live `unamortized_cents`; whichever of the two is smaller is
    posted."
    PRD §3.4: "This variant recovers one and a half times the pro-rata share of the
    *remaining* balance against the *remaining* commitment, front-loading recovery
    heavily in the early lots."
    PRD §3.4: "A computed read on the program exposes them side by side for a
    hypothetical lot of a stated `piece_count`, returning the program's own
    `amortization_method`, the `tooling_asset_id` of the newest tooling asset by
    `created_at` for the program's most recently quoted design, that tool's
    `original_cost_cents`, `recovered_cents` and `unamortized_cents`, the program's live
    `open_commitment_pieces`, and then both hypothetical figures:
    `forecast_basis_recovery_cents` and `actual_basis_recovery_cents`."

    Design: Difficulty/transitive_cascade/ppap_approval_production_release_amortization_chain_four_hops
    """
    world = _submitted_package_world(api)
    X.customer_verdict(
        api, world.submission_id, world.program_id, C.DECISION_APPROVE
    )

    tooling = X.refresh_tooling(api, world.tooling_id)
    expected_rate = A.expected_amort_per_piece_cents(4_800_000, 500_000)
    assert expected_rate == 10, "4 800 000 over 500 000 rounds up to 10 cents a piece"
    assert tooling["amort_per_piece_cents"] == expected_rate, (
        f"the frozen rate is the cost over the basis rounded up, got {tooling['amort_per_piece_cents']}"
    )
    assert tooling["amortization_basis_pieces"] == 500_000, (
        f"the basis is the program's committed_pieces, got {tooling['amortization_basis_pieces']}"
    )

    response = api.get_tooling_amortization(
        world.program_id, PROGRAM_MANAGER_HEADERS, {"piece_count": 25_000}
    )
    amortization = validate_success(response)

    assert amortization["amortization_method"] == C.FORECAST_BASIS, (
        f"the read reports the program's own method, got {amortization['amortization_method']}"
    )
    assert amortization["tooling_asset_id"] == world.tooling_id, (
        "the read consults the newest tooling asset of the most recently quoted design"
    )
    assert amortization["original_cost_cents"] == 4_800_000, (
        f"the capitalised cost is reported verbatim, got {amortization['original_cost_cents']}"
    )
    assert amortization["recovered_cents"] == 0, (
        f"nothing has shipped, so nothing is recovered, got {amortization['recovered_cents']}"
    )
    assert amortization["unamortized_cents"] == 4_800_000, (
        f"the whole balance is outstanding, got {amortization['unamortized_cents']}"
    )
    assert amortization["open_commitment_pieces"] == 500_000, (
        "no lot is allocated yet, so the live commitment is untouched, got "
        f"{amortization['open_commitment_pieces']}"
    )

    expected_forecast = A.expected_forecast_recovery_cents(25_000, 10, 4_800_000)
    assert expected_forecast == 250_000, "25 000 pieces at the frozen 10 cents is 250 000 cents"
    assert amortization["forecast_basis_recovery_cents"] == expected_forecast, (
        "the straight-line figure is pieces times the frozen rate, capped at the balance, got "
        f"{amortization['forecast_basis_recovery_cents']}"
    )
    expected_actual = A.expected_actual_recovery_cents(4_800_000, 25_000, 500_000)
    assert expected_actual == 360_000, (
        "1.5 times the pro-rata share of 4 800 000 over 500 000 pieces is 360 000 cents"
    )
    assert amortization["actual_basis_recovery_cents"] == expected_actual, (
        "the accelerated figure front-loads recovery against the remaining commitment, got "
        f"{amortization['actual_basis_recovery_cents']}"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["quoted_unit_price_cents"] == 24, (
        f"the frozen quote priced the piece at 24 cents, got {program['quoted_unit_price_cents']}"
    )
    assert program["quoted_tooling_amort_per_piece_cents"] == 4, (
        "the quote's per-piece amortization is the capped 4 cents, a different number from the "
        f"tool's frozen 10, got {program['quoted_tooling_amort_per_piece_cents']}"
    )


_INDUSTRIAL_PROGRAM = {
    "program_code": "PGM-IND-2",
    "customer_name": "Bramble Industrial Supply",
    "application_class": C.CLASS_INDUSTRIAL,
    "ppap_level": 1,
    "committed_pieces": 100_000,
    "minimum_order_quantity": 1_000,
    "required_ppk": 1.0,
}


def _measured_first_article_world(api: ApiClient) -> X.World:
    """A 1 000-piece run on a certified 500 kg heat with one wide first-article subgroup.

    The run is still `FAI_PENDING`, its reservation is held, its setup is `ACTIVE` and
    the coiler is in `PRODUCTION`, so a rejection has four hops to unwind.
    """
    world = X.build_world(
        api,
        "run",
        program=_INDUSTRIAL_PROGRAM,
        design={"part_number": "D1-IND"},
        tooling={"tool_code": "TL-D1-IND", "original_cost_cents": 1_200_000},
        machine={"machine_code": "COIL-2"},
        wire_lot={"heat_number": "HT-500", "received_kg": 500.0},
        run={"planned_pieces": 1_000},
        activation_clock=C.CLOCK_INSIDE_SETUP_WINDOW,
    )
    world.fai_records.append(
        X.record_fai_subgroup(
            api, world.run_id, world.characteristics[0], _WIDE_SUBGROUP
        )
    )
    world.run = X.refresh_run(api, world.run_id)
    world.wire_lot = X.refresh_wire_lot(api, world.wire_lot_id)
    world.machine = X.refresh_machine(api, world.machine_id)
    return world


def test_first_article_rejection_unwinds_reservation_setup_and_coiler(
    api: ApiClient,
) -> None:
    """PRD §3.7: "`REJECT` sets `fai_disposition` to `REJECTED` and drives a four-hop
    cascade: the run's `process_status` becomes `CANCELLED`; the wire reservation is
    released using the run's stored `wire_reserved_kg` verbatim, subtracting it from the
    heat's `reserved_kg` and adding it back to the heat's `on_hand_kg`; the run's machine
    setup transitions `ACTIVE → ABORTED`; and that abort in turn returns the coiler to
    `machine_state` `IDLE` with `active_setup_id` null and its `version` increased by 1."
    PRD §2.10: "`CoilingMachine.active_setup_id` is a denormalised pointer resolved as
    the single machine setup row on that machine whose `setup_status` is `ACTIVE`, and is
    null when no such row exists; it is never accepted as an input."

    Design: Difficulty/transitive_cascade/fai_rejection_wire_release_setup_abort_chain_four_hops
    """
    world = _measured_first_article_world(api)
    machine_version_before = world.machine["version"]
    assert world.run["wire_reserved_kg"] == 21.821, (
        "a 1 000-piece run of the canonical design reserves 21.821 kg, got "
        f"{world.run['wire_reserved_kg']}"
    )
    assert world.wire_lot["reserved_kg"] == 21.821, "the heat is holding that reservation"

    response = api.dispose_fai(
        world.run_id, {"decision": C.DECISION_REJECT}, QUALITY_INSPECTOR_ALT_HEADERS
    )
    run = validate_success(response)

    # Hop one.
    assert run["fai_disposition"] == C.FAI_REJECTED, (
        f"the verdict is recorded as REJECTED, got {run['fai_disposition']}"
    )
    assert run["process_status"] == C.PROCESS_CANCELLED, (
        f"the rejection cancels the run's process axis, got {run['process_status']}"
    )
    assert run["produced_pieces"] == 0, (
        f"a cancelled first article produced nothing, got {run['produced_pieces']}"
    )

    # Hop two — the whole reservation goes back to the rack, none of it burned.
    wire_lot = X.refresh_wire_lot(api, world.wire_lot_id)
    assert wire_lot["reserved_kg"] == 0.0, (
        f"the reservation is released in full, got {wire_lot['reserved_kg']}"
    )
    assert wire_lot["on_hand_kg"] == 500.0, (
        f"the released kilograms return to the rack, got {wire_lot['on_hand_kg']}"
    )
    assert wire_lot["consumed_kg"] == 0.0, (
        f"a cancelled run burns nothing, got {wire_lot['consumed_kg']}"
    )
    A.assert_wire_ledger_conserved(wire_lot)

    # Hop three.
    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_ABORTED, (
        f"the run's ACTIVE setup is aborted by the cascade, got {setup['setup_status']}"
    )

    # Hop four.
    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_IDLE, (
        f"the abort frees the coiler back to IDLE, got {machine['machine_state']}"
    )
    assert machine["active_setup_id"] is None, (
        "with no ACTIVE setup on the machine the derived pointer resolves to null, got "
        f"{machine['active_setup_id']}"
    )
    assert machine["version"] == machine_version_before + 1, (
        "rejecting a first article changes the coiler's occupancy, so its version rises by "
        f"exactly 1, got {machine['version']} against {machine_version_before}"
    )


def test_first_article_acceptance_moves_nothing_but_the_two_run_fields(
    api: ApiClient,
) -> None:
    """PRD §3.7: "`ACCEPT` sets `fai_disposition` to `ACCEPTED` and advances the run
    `FAI_PENDING → RUNNING`, and nothing else moves."
    PRD §2.4: "`CoilingMachine.version` is incremented by every operation that changes the
    coiler's occupancy: scheduling a machine setup, activating a setup, aborting a setup
    that was `ACTIVE`, opening a production run, completing a run, cancelling a run, and
    rejecting a first article (which cancels the run)."

    Design: Difficulty/transitive_cascade/fai_rejection_wire_release_setup_abort_chain_four_hops
    """
    world = _measured_first_article_world(api)
    machine_version_before = world.machine["version"]

    response = api.dispose_fai(
        world.run_id, {"decision": C.DECISION_ACCEPT}, QUALITY_INSPECTOR_ALT_HEADERS
    )
    run = validate_success(response)

    assert run["fai_disposition"] == C.FAI_ACCEPTED, (
        f"the verdict is recorded as ACCEPTED, got {run['fai_disposition']}"
    )
    assert run["process_status"] == C.PROCESS_RUNNING, (
        f"acceptance advances the run to RUNNING, got {run['process_status']}"
    )

    wire_lot = X.refresh_wire_lot(api, world.wire_lot_id)
    assert wire_lot["reserved_kg"] == 21.821, (
        f"the reservation is not released, got {wire_lot['reserved_kg']}"
    )
    assert wire_lot["on_hand_kg"] == 478.179, (
        f"500.000 less the 21.821 kg reservation is still on hand, got {wire_lot['on_hand_kg']}"
    )
    assert wire_lot["consumed_kg"] == 0.0, "nothing is consumed until the run completes"
    A.assert_wire_ledger_conserved(wire_lot)

    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_ACTIVE, (
        f"the setup keeps running the job, got {setup['setup_status']}"
    )

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_PRODUCTION, (
        f"the coiler stays in PRODUCTION, got {machine['machine_state']}"
    )
    assert machine["active_setup_id"] == world.setup_id, (
        "the ACTIVE setup is still the machine's derived pointer, got "
        f"{machine['active_setup_id']}"
    )
    assert machine["version"] == machine_version_before, (
        "accepting a first article is not one of the occupancy-changing operations, so the "
        f"coiler's version does not move, got {machine['version']}"
    )


def test_rejected_first_article_releases_the_stored_reservation_verbatim(
    api: ApiClient,
) -> None:
    """PRD §3.7: "`ppk_value` is the pooled long-run capability and is **null on every
    first-article record**."
    PRD §3.7: "A first-article record with an `OUT_OF_CONTROL` control state records that
    fact and nothing more: the quality axis stays `OPEN`, because only in-process
    subgroups can drive a run onto a hold."
    PRD §3.7: "First-article records therefore move `min_cpk_observed` but leave
    `min_ppk_observed` untouched."
    PRD §2.9: "When a reservation is released, the release uses the `wire_reserved_kg`
    value stored on the run verbatim; it is never recomputed from the design, because the
    design may have been revised in the meantime."
    PRD §3.4: "The `PENDING → AMORTIZING` promotion fires as a system event when the
    tool's design reaches `PRODUCTION_RELEASED`, and it is the moment the amortization
    basis is frozen: `amortization_basis_pieces` takes the owning program's
    `committed_pieces`, and `amort_per_piece_cents` becomes `original_cost_cents` divided
    by that basis, rounded **up** to the next whole cent."

    Design: Difficulty/transitive_cascade/fai_rejection_wire_release_setup_abort_chain_four_hops
    """
    world = _measured_first_article_world(api)
    record = world.fai_records[0]

    assert record["record_kind"] == C.RECORD_KIND_FAI, (
        f"the first-article endpoint stamps record_kind FAI, got {record['record_kind']}"
    )
    expected_cpk = A.expected_cpk_value(_WIDE_SUBGROUP, _LSL, _USL)
    assert expected_cpk == 0.833, "the wide subgroup's short-run index is 0.833"
    assert record["cpk_value"] == expected_cpk, (
        f"the first-article record carries its own short-run index, got {record['cpk_value']}"
    )
    assert record["ppk_value"] is None, (
        f"a first-article record never carries a pooled index, got {record['ppk_value']}"
    )
    assert record["control_state"] == C.CONTROL_OUT_OF_CONTROL, (
        "0.833 is below the 1.333 floor, so the first article is out of control"
    )
    assert world.run["quality_status"] == C.QUALITY_OPEN, (
        "an out-of-control first article never puts a run on hold, got "
        f"{world.run['quality_status']}"
    )
    assert world.run["min_cpk_observed"] == expected_cpk, (
        f"the first-article record moves min_cpk_observed, got {world.run['min_cpk_observed']}"
    )
    assert world.run["min_ppk_observed"] is None, (
        "no in-process subgroup has been taken, so min_ppk_observed is still null, got "
        f"{world.run['min_ppk_observed']}"
    )

    stored_reservation = world.run["wire_reserved_kg"]
    assert stored_reservation == A.expected_wire_reserved_kg(
        world.design["wire_mass_per_piece_kg"], 1_000
    ), "the stored reservation is the stored per-piece mass scaled and inflated once"

    api.dispose_fai(
        world.run_id, {"decision": C.DECISION_REJECT}, QUALITY_INSPECTOR_ALT_HEADERS
    )

    run = X.refresh_run(api, world.run_id)
    assert run["wire_reserved_kg"] == stored_reservation, (
        "the run keeps the reservation figure as history after the release, got "
        f"{run['wire_reserved_kg']}"
    )
    wire_lot = X.refresh_wire_lot(api, world.wire_lot_id)
    assert wire_lot["on_hand_kg"] == wire_lot["received_kg"], (
        "releasing the stored figure verbatim restores the rack exactly, got "
        f"{wire_lot['on_hand_kg']} against {wire_lot['received_kg']}"
    )
    A.assert_wire_ledger_conserved(wire_lot)

    tooling = X.refresh_tooling(api, world.tooling_id)
    assert tooling["amortization_status"] == C.AMORT_PENDING, (
        "the tool arms only when its design reaches PRODUCTION_RELEASED, which a rejected "
        f"first article never does, got {tooling['amortization_status']}"
    )
    assert tooling["amortization_basis_pieces"] is None, (
        f"no basis is frozen, got {tooling['amortization_basis_pieces']}"
    )
    assert tooling["unamortized_cents"] == 1_200_000, (
        f"the capitalised cost is untouched, got {tooling['unamortized_cents']}"
    )
    A.assert_tooling_ledger_conserved(tooling)

    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_PROTOTYPE, (
        f"the design keeps its prototype release, got {design['release_status']}"
    )
