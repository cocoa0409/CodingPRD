"""Which of two simultaneous defects the rejection ladder answers.

Three requests here each break two rules at once on three different endpoints —
lot allocation, run creation and setup booking — and the ladder of section 2.8
decides which single error the client is told about. Every instance is driven
twice: once with both defects live, to pin the winning error, and once with the
higher-ranked defect repaired, to prove the lower-ranked rule was genuinely
armed and not merely unreachable.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_COMMITMENT_EXCEEDED,
    ERR_PPAP_NOT_APPROVED,
    ERR_RUN_NOT_COMPLETE,
    ERR_SETUP_DESIGN_MISMATCH,
    ERR_SETUP_WINDOW_CONFLICT,
    ERR_WIRE_DIAMETER_EXCEEDS_MACHINE,
)
from test_helpers.test_users import (
    PROCESS_TECHNICIAN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
)

# A safety-critical program whose 24 000-piece commitment is deliberately smaller
# than the 25 000-piece draw the allocation tests make, and whose 20 000-piece
# minimum order quantity leaves that draw comfortably above the MOQ floor.
_COMMITMENT_PROGRAM = {
    "program_code": "PGM-AUTO-3",
    "customer_name": "Northwind Drivetrain",
    "application_class": C.CLASS_AUTOMOTIVE_SAFETY,
    "ppap_level": 3,
    "committed_pieces": 24_000,
    "minimum_order_quantity": 20_000,
    "required_salt_spray_hours": 96,
    "biocompatibility_required": False,
    "min_fatigue_margin": 1.2,
    "required_ppk": 1.33,
    "amortization_method": C.FORECAST_BASIS,
}

# 25 000 pieces: above the 20 000 MOQ, inside the 25 500 the run produces, and
# 1 000 pieces beyond the program's 24 000 open commitment.
_OVERDRAW_PIECES = 25_000

# 20 000 pieces: the same draw with the commitment defect removed.
_FITTING_PIECES = 20_000

# The stress-relief window this scenario books, which sits after the 08:30
# activation instant and before the 12:00 close of the setup window.
_BATCH_WINDOW_START = "2026-08-05T09:00:00Z"
_BATCH_WINDOW_END = "2026-08-05T11:00:00Z"


def _conflicted_allocation_world(api: ApiClient) -> X.World:
    """A fully qualified package whose run is still RUNNING.

    Every allocation gate other than the run-state gate and the commitment gate
    is satisfied: two in-control safety-critical subgroups put `min_ppk_observed`
    at 3.333 against a 1.33 floor, a discharged peened batch closes heat
    treatment, a quote is on file, and the customer has granted full approval.
    """
    world = X.build_world(
        api,
        "spc",
        program=_COMMITMENT_PROGRAM,
        activation_clock=C.CLOCK_INSIDE_SETUP_WINDOW,
    )

    # A second in-process subgroup, so the pooled figure has more than one
    # record to draw on while the run's lowest stamped Ppk stays 3.333.
    world.spc_records.append(
        X.record_spc_subgroup(api, world.run_id, world.characteristics[0])
    )

    world.oven = X.commission_oven(api)
    world.batch = X.schedule_batch(
        api,
        world.oven_id,
        world.run_id,
        window_start=_BATCH_WINDOW_START,
        window_end=_BATCH_WINDOW_END,
    )
    X.pin_clock(api, _BATCH_WINDOW_START)
    X.start_batch(api, world.batch_id)
    X.discharge_batch(api, world.batch_id, peening_performed=True)

    world.program = X.price_program(api, world.program, world.design_id)
    world.submission = X.file_submission(
        api, world.program_id, world.design_id, ppap_level=3
    )
    X.customer_verdict(
        api, world.submission_id, world.program_id, decision=C.DECISION_APPROVE
    )

    world.program = X.refresh_program(api, world.program_id)
    world.run = X.refresh_run(api, world.run_id)
    return world


def test_running_run_answers_run_not_complete_over_the_commitment_overrun(api):
    """A 25 000-piece draw on a RUNNING run breaks rank 22 and rank 74 at once.

    PRD §3.11: "Creating a shipment lot is the densest gate in the API: a `ProgramManager`
    names a `run_id`, a `program_id` and a `piece_count` greater than zero, and eleven
    substantive conditions apply in the priority order of section 2.8."
    PRD §2.8: "When a single request violates more than one rule, exactly one error is
    returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "22. `ERR_RUN_NOT_COMPLETE` — on `POST /shipment-lots`."
    PRD §2.8: "74. `ERR_COMMITMENT_EXCEEDED` — on `POST /shipment-lots`, `POST /shipment-lots/{id}/release-from-quarantine`."
    PRD §3.11: "The run's `process_status` must be `COMPLETE`, otherwise `ERR_RUN_NOT_COMPLETE` (HTTP 409); its `quality_status` must be `OPEN` or `DISPOSITIONED_ACCEPT`, and a held or scrapped run answers `ERR_RUN_ON_SPC_HOLD` (HTTP 409)."
    PRD §3.11: "`piece_count` must not exceed the program's `open_commitment_pieces`, otherwise `ERR_COMMITMENT_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/run_not_complete_state_outranks_commitment_exceeded_fiscal_on_lot_creation
    """
    world = _conflicted_allocation_world(api)

    # Both defects have to be live, or the pair is not being tested.
    assert world.run["process_status"] == C.PROCESS_RUNNING, (
        f"the run must still be RUNNING for rank 22 to bite, got {world.run['process_status']}"
    )
    assert world.program["open_commitment_pieces"] == 24_000, (
        "the whole 24 000-piece commitment must still be open, got "
        f"{world.program['open_commitment_pieces']}"
    )
    assert _OVERDRAW_PIECES > world.program["open_commitment_pieces"], (
        "the draw must exceed the open commitment for rank 74 to bite as well"
    )
    assert _OVERDRAW_PIECES >= world.program["minimum_order_quantity"], (
        "the draw must clear the MOQ floor so no higher-ranked quantity gate answers"
    )

    response = api.create_lot(
        F.lot_payload(world.run_id, world.program_id, _OVERDRAW_PIECES),
        PROGRAM_MANAGER_HEADERS,
    )
    validate_error(response, ERR_RUN_NOT_COMPLETE, 409)

    # A rejected allocation moves no piece counter at all.
    program = X.refresh_program(api, world.program_id)
    assert program["open_commitment_pieces"] == 24_000, (
        f"a rejected allocation leaves the commitment alone, got {program['open_commitment_pieces']}"
    )
    assert program["allocated_pieces"] == 0, (
        f"a rejected allocation allocates nothing, got {program['allocated_pieces']}"
    )
    assert program["shipped_pieces"] == 0, "a rejected allocation ships nothing"
    A.assert_commitment_conserved(program)

    lots, meta = validate_paginated(
        api.list_lots(PROGRAM_MANAGER_HEADERS, {"run_id": world.run_id})
    )
    assert meta["total_count"] == 0, (
        f"the rejected call must not have created a lot row, got {meta['total_count']}"
    )
    assert lots == [], "no lot exists for a run whose allocation was refused"


def test_completing_the_run_lets_the_commitment_overrun_surface(api):
    """Repairing the rank-22 defect hands the same body to rank 74.

    PRD §2.8: "When a single request violates more than one rule, exactly one error is
    returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "22. `ERR_RUN_NOT_COMPLETE` — on `POST /shipment-lots`."
    PRD §2.8: "74. `ERR_COMMITMENT_EXCEEDED` — on `POST /shipment-lots`, `POST /shipment-lots/{id}/release-from-quarantine`."
    PRD §3.11: "`piece_count` must not exceed the program's `open_commitment_pieces`, otherwise `ERR_COMMITMENT_EXCEEDED` (HTTP 422)."
    PRD §3.7: "Consumption is then computed as the design's stored six-decimal `wire_mass_per_piece_kg` multiplied by the sum of `produced_pieces` and `scrapped_pieces` — scrap burns wire exactly like good product does — rounded half up to three decimal places, and written to `wire_consumed_kg`."
    PRD §3.7: "At the run level, `min_cpk_observed` is refreshed to the lowest `cpk_value` across all of the run's inspection records, while `min_ppk_observed` is refreshed to the lowest `ppk_value` across only those of the run's records whose `record_kind` is `SPC` and whose characteristic has `is_safety_critical` true."

    Design: Difficulty/priority_pair_validation_conflict/run_not_complete_state_outranks_commitment_exceeded_fiscal_on_lot_creation
    """
    world = _conflicted_allocation_world(api)
    body = F.lot_payload(world.run_id, world.program_id, _OVERDRAW_PIECES)

    first = api.create_lot(body, PROGRAM_MANAGER_HEADERS)
    validate_error(first, ERR_RUN_NOT_COMPLETE, 409)

    X.complete_run(api, world.run_id, produced_pieces=25_500, scrapped_pieces=500)

    run = X.refresh_run(api, world.run_id)
    assert run["process_status"] == C.PROCESS_COMPLETE, (
        f"the run-state defect is now repaired, got {run['process_status']}"
    )
    assert run["wire_consumed_kg"] == A.expected_wire_consumed_kg(0.021185, 25_500, 500), (
        f"26 000 pieces at 0.021185 kg burn 550.810 kg, got {run['wire_consumed_kg']}"
    )
    assert run["wire_consumed_kg"] == 550.81, (
        f"the stored consumption figure is 550.810 kg, got {run['wire_consumed_kg']}"
    )
    assert run["min_ppk_observed"] == 3.333, (
        "the lowest safety-critical SPC Ppk on the run is 3.333, got "
        f"{run['min_ppk_observed']}"
    )

    # The identical body, replayed against a COMPLETE run.
    second = api.create_lot(body, PROGRAM_MANAGER_HEADERS)
    validate_error(second, ERR_COMMITMENT_EXCEEDED, 422)

    program = X.refresh_program(api, world.program_id)
    assert program["open_commitment_pieces"] == 24_000, (
        f"neither rejected call touched the commitment, got {program['open_commitment_pieces']}"
    )
    assert program["allocated_pieces"] == 0, (
        f"neither rejected call allocated a piece, got {program['allocated_pieces']}"
    )
    assert program["shipped_pieces"] == 0, "neither rejected call shipped a piece"
    A.assert_commitment_conserved(program)

    _, meta = validate_paginated(
        api.list_lots(PROGRAM_MANAGER_HEADERS, {"run_id": world.run_id})
    )
    assert meta["total_count"] == 0, (
        f"two rejections must leave the run with no lot rows, got {meta['total_count']}"
    )


def test_a_draw_inside_the_commitment_is_answered_only_by_the_run_state_gate(api):
    """With rank 74 satisfied the state gate answers alone, then lets the lot through.

    PRD §2.8: "22. `ERR_RUN_NOT_COMPLETE` — on `POST /shipment-lots`."
    PRD §3.11: "The run's `process_status` must be `COMPLETE`, otherwise `ERR_RUN_NOT_COMPLETE` (HTTP 409); its `quality_status` must be `OPEN` or `DISPOSITIONED_ACCEPT`, and a held or scrapped run answers `ERR_RUN_ON_SPC_HOLD` (HTTP 409)."
    PRD §3.11: "`piece_count` must not exceed the program's `open_commitment_pieces`, otherwise `ERR_COMMITMENT_EXCEEDED` (HTTP 422)."
    PRD §3.11: "Then the quantity gates: `piece_count` must be at least the program's `minimum_order_quantity`, inclusive at the boundary, otherwise `ERR_BELOW_MINIMUM_ORDER_QUANTITY` (HTTP 422); `piece_count` must not exceed the run's `produced_pieces` minus the pieces already carried by lots of this run whose `lot_status` is `ALLOCATED`, `PACKED` or `SHIPPED` — quarantined and returned lots do not consume run availability — otherwise `ERR_RUN_PIECES_EXHAUSTED` (HTTP 422)."
    PRD §3.11: "On the program, `open_commitment_pieces` decreases by `piece_count` and `allocated_pieces` increases by it, conserving `committed_pieces`, and `delivery_posture` is re-derived."

    Design: Difficulty/priority_pair_validation_conflict/run_not_complete_state_outranks_commitment_exceeded_fiscal_on_lot_creation
    """
    world = _conflicted_allocation_world(api)
    body = F.lot_payload(world.run_id, world.program_id, _FITTING_PIECES)

    assert _FITTING_PIECES == world.program["minimum_order_quantity"], (
        "this draw sits exactly on the MOQ, which the PRD admits inclusively"
    )
    assert _FITTING_PIECES <= world.program["open_commitment_pieces"], (
        "the fiscal defect is removed, so only the run-state defect is left"
    )

    refused = api.create_lot(body, PROGRAM_MANAGER_HEADERS)
    validate_error(refused, ERR_RUN_NOT_COMPLETE, 409)

    X.complete_run(api, world.run_id, produced_pieces=25_500, scrapped_pieces=500)

    allowed = api.create_lot(body, PROGRAM_MANAGER_HEADERS)
    lot = validate_success(allowed, 201)
    assert lot["lot_status"] == C.LOT_ALLOCATED, (
        f"with both defects gone the lot opens ALLOCATED, got {lot['lot_status']}"
    )
    assert lot["piece_count"] == _FITTING_PIECES, (
        f"the lot carries the requested 20 000 pieces, got {lot['piece_count']}"
    )
    assert lot["unit_price_cents"] == 24, (
        f"the lot snapshots the program's 24-cent quoted unit price, got {lot['unit_price_cents']}"
    )
    assert lot["extended_price_cents"] == _FITTING_PIECES * 24, (
        "extended_price_cents is piece_count times unit_price_cents, got "
        f"{lot['extended_price_cents']}"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["allocated_pieces"] == _FITTING_PIECES, (
        f"allocation moves 20 000 pieces into allocated, got {program['allocated_pieces']}"
    )
    assert program["open_commitment_pieces"] == 24_000 - _FITTING_PIECES, (
        "the commitment falls by the same 20 000 pieces, got "
        f"{program['open_commitment_pieces']}"
    )
    A.assert_commitment_conserved(program)

    _, meta = validate_paginated(
        api.list_lots(PROGRAM_MANAGER_HEADERS, {"run_id": world.run_id})
    )
    assert meta["total_count"] == 1, (
        f"exactly one lot survived the three calls, got {meta['total_count']}"
    )


# An industrial program, so release status alone governs run admissibility: no
# safety-critical Ppk floor and no approval package stand in the way.
_RUN_GATE_PROGRAM = {
    "program_code": "PGM-IND-3",
    "customer_name": "Bramble Industrial Supply",
    "application_class": C.CLASS_INDUSTRIAL,
    "ppap_level": 1,
    "committed_pieces": 100_000,
    "minimum_order_quantity": 1_000,
    "required_salt_spray_hours": 96,
    "biocompatibility_required": False,
    "min_fatigue_margin": 1.2,
    "required_ppk": 1.0,
    "amortization_method": C.FORECAST_BASIS,
}

# 1 000 pieces of the canonical 0.021185 kg design reserve 21.821 kg once the
# three-percent scrap allowance is applied and the product is rounded once.
_RUN_PIECES = 1_000
_RUN_RESERVED_KG = 21.821
_HEAT_RECEIVED_KG = 500.0


def _two_spare_designs_world(api: ApiClient) -> X.World:
    """An ACTIVE setup for one design, plus two designs it was never tooled for.

    `world.design` owns the setup. `world.extra["draft"]` never left `DRAFT`, so
    naming it in a run body breaks the release-status gate and the setup-to-design
    gate together. `world.extra["released"]` reached `PROTOTYPE_RELEASED`, so it
    breaks only the setup-to-design gate.
    """
    world = X.build_world(
        api,
        "certified_wire",
        program=_RUN_GATE_PROGRAM,
        design={"part_number": "D1-IND"},
        tooling={"tool_code": "TL-D1-IND", "original_cost_cents": 1_200_000},
        machine={"machine_code": "COIL-2"},
        wire_lot={"heat_number": "HT-500", "received_kg": _HEAT_RECEIVED_KG},
        activation_clock=C.CLOCK_INSIDE_SETUP_WINDOW,
    )

    world.extra["draft"] = X.draft_design(
        api, world.program_id, world.material_id, part_number="DX-DRAFT"
    )

    released = X.draft_design(
        api, world.program_id, world.material_id, part_number="DY-REL"
    )
    X.add_characteristic(api, released["id"])
    world.extra["released"] = X.release_prototype(api, released["id"])

    world.machine = X.refresh_machine(api, world.machine_id)
    world.wire_lot = X.refresh_wire_lot(api, world.wire_lot_id)
    return world


def test_draft_body_design_answers_ppap_not_approved_over_the_setup_mismatch(api):
    """A DRAFT design that is also not the setup's design breaks rank 41 and rank 47.

    PRD §2.8: "When a single request violates more than one rule, exactly one error is
    returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "41. `ERR_PPAP_NOT_APPROVED` — on `POST /machine-setups`, `POST /production-runs`, `POST /shipment-lots`."
    PRD §2.8: "47. `ERR_SETUP_DESIGN_MISMATCH` — on `POST /production-runs`."
    PRD §3.7: "The gates run in this order."
    PRD §3.7: "The design's `release_status` must be `PROTOTYPE_RELEASED` or `PRODUCTION_RELEASED`, otherwise `ERR_PPAP_NOT_APPROVED` (HTTP 422) — note that a merely `PROTOTYPE_RELEASED` design may be run for first articles and prototype quantities long before any approval package exists, which is exactly how the shop generates the evidence the package needs."
    PRD §3.7: "The `design_id` in the body must equal the design the setup was tooled for, or the answer is `ERR_SETUP_DESIGN_MISMATCH` (HTTP 422)."
    PRD §3.7: "On success the reservation moves mass without creating any: `wire_reserved_kg` is subtracted from the heat's `on_hand_kg` and added to its `reserved_kg`, leaving `received_kg` untouched."

    Design: Difficulty/priority_pair_validation_conflict/ppap_not_approved_safety_outranks_setup_design_mismatch_referential_on_run_creation
    """
    world = _two_spare_designs_world(api)
    draft = world.extra["draft"]

    # Both defects have to be live, or the pair is not being tested.
    assert draft["release_status"] == C.RELEASE_DRAFT, (
        f"the body design must still be DRAFT for rank 41 to bite, got {draft['release_status']}"
    )
    assert draft["id"] != world.setup["design_id"], (
        "the body design must differ from the setup's design for rank 47 to bite as well"
    )
    assert world.setup["setup_status"] == C.SETUP_ACTIVE, (
        f"the setup must be ACTIVE so no higher-ranked state gate answers, got {world.setup['setup_status']}"
    )

    response = api.create_run(
        F.run_payload(
            world.setup_id, world.wire_lot_id, draft["id"], planned_pieces=_RUN_PIECES
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(response, ERR_PPAP_NOT_APPROVED, 422)

    # A rejected run never reserves a kilogram and never occupies the coiler.
    wire_lot = X.refresh_wire_lot(api, world.wire_lot_id)
    assert wire_lot["on_hand_kg"] == _HEAT_RECEIVED_KG, (
        f"the whole heat is still on hand, got {wire_lot['on_hand_kg']}"
    )
    assert wire_lot["reserved_kg"] == 0.0, (
        f"a rejected run reserves nothing, got {wire_lot['reserved_kg']}"
    )
    A.assert_wire_ledger_conserved(wire_lot)

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_SETUP, (
        f"no run was created, so the coiler never reached PRODUCTION, got {machine['machine_state']}"
    )

    _, meta = validate_paginated(
        api.list_runs(PROCESS_TECHNICIAN_HEADERS, {"setup_id": world.setup_id})
    )
    assert meta["total_count"] == 0, (
        f"the rejected call must not have created a run row, got {meta['total_count']}"
    )


def test_releasing_the_body_design_lets_the_setup_design_mismatch_surface(api):
    """Repairing the rank-41 defect hands the same shape of body to rank 47.

    PRD §2.8: "When a single request violates more than one rule, exactly one error is
    returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "41. `ERR_PPAP_NOT_APPROVED` — on `POST /machine-setups`, `POST /production-runs`, `POST /shipment-lots`."
    PRD §2.8: "47. `ERR_SETUP_DESIGN_MISMATCH` — on `POST /production-runs`."
    PRD §3.7: "The design's `release_status` must be `PROTOTYPE_RELEASED` or `PRODUCTION_RELEASED`, otherwise `ERR_PPAP_NOT_APPROVED` (HTTP 422) — note that a merely `PROTOTYPE_RELEASED` design may be run for first articles and prototype quantities long before any approval package exists, which is exactly how the shop generates the evidence the package needs."
    PRD §3.7: "The `design_id` in the body must equal the design the setup was tooled for, or the answer is `ERR_SETUP_DESIGN_MISMATCH` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/ppap_not_approved_safety_outranks_setup_design_mismatch_referential_on_run_creation
    """
    world = _two_spare_designs_world(api)
    draft = world.extra["draft"]
    released = world.extra["released"]

    first = api.create_run(
        F.run_payload(
            world.setup_id, world.wire_lot_id, draft["id"], planned_pieces=_RUN_PIECES
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(first, ERR_PPAP_NOT_APPROVED, 422)

    assert released["release_status"] == C.RELEASE_PROTOTYPE, (
        f"the second body design clears the release gate, got {released['release_status']}"
    )
    assert released["id"] != world.setup["design_id"], (
        "the second body design is still not the design the setup was tooled for"
    )
    assert released["material_spec_id"] == world.wire_lot["material_spec_id"], (
        "both designs share the heat's material grade, so no lower-ranked material gate answers"
    )

    second = api.create_run(
        F.run_payload(
            world.setup_id, world.wire_lot_id, released["id"], planned_pieces=_RUN_PIECES
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(second, ERR_SETUP_DESIGN_MISMATCH, 422)

    wire_lot = X.refresh_wire_lot(api, world.wire_lot_id)
    assert wire_lot["on_hand_kg"] == _HEAT_RECEIVED_KG, (
        f"two rejections leave the whole heat on hand, got {wire_lot['on_hand_kg']}"
    )
    assert wire_lot["reserved_kg"] == 0.0, (
        f"two rejections reserve nothing, got {wire_lot['reserved_kg']}"
    )
    A.assert_wire_ledger_conserved(wire_lot)

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_SETUP, (
        f"the coiler is still merely set up, got {machine['machine_state']}"
    )

    _, meta = validate_paginated(
        api.list_runs(PROCESS_TECHNICIAN_HEADERS, {"setup_id": world.setup_id})
    )
    assert meta["total_count"] == 0, (
        f"two rejections must leave the setup with no run rows, got {meta['total_count']}"
    )


def test_the_setups_own_released_design_clears_both_run_gates(api):
    """With both defects gone the run opens and takes its reservation.

    PRD §2.8: "41. `ERR_PPAP_NOT_APPROVED` — on `POST /machine-setups`, `POST /production-runs`, `POST /shipment-lots`."
    PRD §2.8: "47. `ERR_SETUP_DESIGN_MISMATCH` — on `POST /production-runs`."
    PRD §3.7: "The `design_id` in the body must equal the design the setup was tooled for, or the answer is `ERR_SETUP_DESIGN_MISMATCH` (HTTP 422)."
    PRD §3.7: "On success the reservation moves mass without creating any: `wire_reserved_kg` is subtracted from the heat's `on_hand_kg` and added to its `reserved_kg`, leaving `received_kg` untouched."
    PRD §3.7: "Its coiler transitions `SETUP → PRODUCTION` and the machine's `version` increases by 1."

    Design: Difficulty/priority_pair_validation_conflict/ppap_not_approved_safety_outranks_setup_design_mismatch_referential_on_run_creation
    """
    world = _two_spare_designs_world(api)
    machine_version_before = world.machine["version"]

    response = api.create_run(
        F.run_payload(
            world.setup_id,
            world.wire_lot_id,
            world.design_id,
            planned_pieces=_RUN_PIECES,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    run = validate_success(response, 201)

    assert run["process_status"] == C.PROCESS_FAI_PENDING, (
        f"a new run opens at rest on the process axis, got {run['process_status']}"
    )
    assert run["wire_reserved_kg"] == A.expected_wire_reserved_kg(0.021185, _RUN_PIECES), (
        f"1 000 pieces plus three percent scrap reserve 21.821 kg, got {run['wire_reserved_kg']}"
    )
    assert run["wire_reserved_kg"] == _RUN_RESERVED_KG, (
        f"the stored reservation is 21.821 kg, got {run['wire_reserved_kg']}"
    )

    wire_lot = X.refresh_wire_lot(api, world.wire_lot_id)
    assert wire_lot["reserved_kg"] == _RUN_RESERVED_KG, (
        f"the reservation lands in the heat's reserved bucket, got {wire_lot['reserved_kg']}"
    )
    assert wire_lot["on_hand_kg"] == _HEAT_RECEIVED_KG - _RUN_RESERVED_KG, (
        f"the same mass leaves the on-hand bucket, got {wire_lot['on_hand_kg']}"
    )
    assert wire_lot["received_kg"] == _HEAT_RECEIVED_KG, (
        f"received_kg is untouched by a reservation, got {wire_lot['received_kg']}"
    )
    A.assert_wire_ledger_conserved(wire_lot)

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_PRODUCTION, (
        f"opening a run takes the coiler SETUP to PRODUCTION, got {machine['machine_state']}"
    )
    assert machine["version"] == machine_version_before + 1, (
        f"an occupancy-changing operation bumps the coiler's version once, got {machine['version']}"
    )


# The same industrial posture on a third program, so nothing but the coiler's
# ceiling and its changeover buffer governs a booking.
_BUFFER_PROGRAM = dict(_RUN_GATE_PROGRAM, program_code="PGM-IND-4")

# A thin stainless extension spring: 1.2 mm wire clears a 2.0 mm coiler, where
# the canonical 2.5 mm compression design does not.
_THIN_DESIGN = {
    "form_type": C.FORM_EXTENSION,
    "end_type": C.END_HOOK_EXTENSION,
    "wire_diameter_mm": 1.2,
    "outer_diameter_mm": 10.0,
    "free_length_mm": 24.0,
    "active_coils": 6,
    "max_working_load_n": 25,
    "min_working_load_n": 8,
    "cycle_seconds_per_piece": 2.4,
    "shot_peening_required": False,
}

# A hook-position print for the thin designs, non-safety-critical so no pooled
# capability floor is ever in play here.
_HOOK_POSITION_PLAN = {
    "char_code": C.CHAR_HOOK_POSITION,
    "nominal_value": 24.0,
    "lsl": 23.7,
    "usl": 24.3,
    "is_safety_critical": False,
    "cpk_floor": 1.0,
}

# The coiler this scenario commissions: a 2.0 mm ceiling and a 45-minute buffer.
_NARROW_CEILING_MM = 2.0
_BUFFER_MINUTES = 45

# The occupied window is [08:00Z, 12:00Z), so the buffer runs it out to 12:45Z.
# A booking that starts at 12:30Z clashes; one that starts at 12:45Z does not.
_INSIDE_BUFFER_START = "2026-08-05T12:30:00Z"
_ON_BUFFER_START = "2026-08-05T12:45:00Z"
_LATE_WINDOW_END = "2026-08-05T16:00:00Z"


def _release_thin_design(
    api: ApiClient, program_id: str, material_spec_id: str, part_number: str
) -> X.Json:
    """One thin stainless extension design, taken to PROTOTYPE_RELEASED."""
    design = X.draft_design(
        api, program_id, material_spec_id, part_number=part_number, **_THIN_DESIGN
    )
    X.add_characteristic(api, design["id"], **_HOOK_POSITION_PLAN)
    return X.release_prototype(api, design["id"])


def _buffered_coiler_world(api: ApiClient) -> X.World:
    """A 2.0 mm coiler already occupied from 08:00Z to 12:00Z.

    `world.design` is the thick 2.5 mm design the coiler cannot form.
    `world.extra["first_thin"]` owns the SCHEDULED setup, and
    `world.extra["second_thin"]` is a second thin design free to be booked.
    """
    world = X.World()
    world.program = X.open_program(api, **_BUFFER_PROGRAM)
    world.material = X.register_material(api)
    stainless = X.register_biocompatible_material(api)

    thick = X.draft_design(
        api, world.program_id, world.material_id, part_number="DT-THICK"
    )
    X.add_characteristic(api, thick["id"])
    world.design = X.release_prototype(api, thick["id"])
    world.tooling = X.capitalise_tooling(
        api, world.design_id, tool_code="TL-DT", original_cost_cents=1_200_000
    )

    first_thin = _release_thin_design(
        api, world.program_id, stainless["id"], "DN1-THIN"
    )
    second_thin = _release_thin_design(
        api, world.program_id, stainless["id"], "DN2-THIN"
    )
    world.extra["first_thin"] = first_thin
    world.extra["second_thin"] = second_thin
    world.extra["first_thin_tool"] = X.capitalise_tooling(
        api, first_thin["id"], tool_code="TL-DN1", original_cost_cents=900_000
    )
    world.extra["second_thin_tool"] = X.capitalise_tooling(
        api, second_thin["id"], tool_code="TL-DN2", original_cost_cents=900_000
    )

    world.machine = X.commission_machine(
        api,
        machine_code="COIL-3",
        max_wire_diameter_mm=_NARROW_CEILING_MM,
        changeover_buffer_minutes=_BUFFER_MINUTES,
    )
    world.setup = X.book_setup(
        api, world.machine, first_thin["id"], world.extra["first_thin_tool"]["id"]
    )
    world.machine = X.refresh_machine(api, world.machine_id)
    return world


def test_thick_wire_answers_the_diameter_ceiling_over_the_buffered_conflict(api):
    """A 2.5 mm design booked inside the changeover buffer breaks rank 53 and rank 67.

    PRD §2.8: "When a single request violates more than one rule, exactly one error is
    returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "53. `ERR_WIRE_DIAMETER_EXCEEDS_MACHINE` — on `POST /machine-setups`."
    PRD §2.8: "67. `ERR_SETUP_WINDOW_CONFLICT` — on `POST /machine-setups`."
    PRD §3.6: "The design's `wire_diameter_mm` must not exceed the coiler's `max_wire_diameter_mm`, or the booking answers `ERR_WIRE_DIAMETER_EXCEEDS_MACHINE` (HTTP 422) — and this ceiling is checked **before** the window arithmetic, so a too-heavy wire on a busy machine reports the diameter problem rather than a clash."
    PRD §3.6: "Two windows conflict when the new window's start is strictly earlier than the existing window's end plus the buffer **and** the existing window's start is strictly earlier than the new window's end plus the buffer."
    PRD §3.6: "If any such conflicting setup exists, the booking is rejected with `ERR_SETUP_WINDOW_CONFLICT` (HTTP 409)."
    PRD §3.6: "A successful booking stamps `set_by_user_id` from the technician's `X-User-ID`, opens the setup in `setup_status` `SCHEDULED`, and increases the coiler's `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/wire_diameter_constraint_outranks_setup_window_conflict_temporal_on_setup_creation
    """
    world = _buffered_coiler_world(api)
    machine_version_before = world.machine["version"]

    # Both defects have to be live, or the pair is not being tested.
    assert world.machine["max_wire_diameter_mm"] == _NARROW_CEILING_MM, (
        f"the coiler tops out at 2.0 mm, got {world.machine['max_wire_diameter_mm']}"
    )
    assert world.design["wire_diameter_mm"] > _NARROW_CEILING_MM, (
        f"the booked design's 2.5 mm wire must exceed that ceiling for rank 53 to bite, "
        f"got {world.design['wire_diameter_mm']}"
    )
    assert world.setup["setup_status"] == C.SETUP_SCHEDULED, (
        f"the occupying setup must be SCHEDULED to be considered, got {world.setup['setup_status']}"
    )
    assert world.setup["window_end"] == C.CLOCK_SETUP_WINDOW_END, (
        "the occupied window closes at 12:00Z, so the 45-minute buffer runs to 12:45Z, "
        f"got {world.setup['window_end']}"
    )

    response = api.create_setup(
        F.setup_payload(
            world.machine_id,
            world.design_id,
            world.tooling_id,
            machine_version_before,
            window_start=_INSIDE_BUFFER_START,
            window_end=_LATE_WINDOW_END,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(response, ERR_WIRE_DIAMETER_EXCEEDS_MACHINE, 422)

    # A rejected booking neither occupies the coiler nor supersedes a schedule.
    machine = X.refresh_machine(api, world.machine_id)
    assert machine["version"] == machine_version_before, (
        f"a rejected booking never bumps the coiler's version, got {machine['version']}"
    )

    occupying = X.refresh_setup(api, world.setup_id)
    assert occupying["setup_status"] == C.SETUP_SCHEDULED, (
        f"the occupying setup is untouched, got {occupying['setup_status']}"
    )
    assert occupying["superseded_by_setup_id"] is None, (
        "no supersession sweep runs for a booking that was refused, got "
        f"{occupying['superseded_by_setup_id']}"
    )

    _, meta = validate_paginated(
        api.list_setups(PROCESS_TECHNICIAN_HEADERS, {"machine_id": world.machine_id})
    )
    assert meta["total_count"] == 1, (
        f"the coiler still carries only its original setup, got {meta['total_count']}"
    )


def test_thin_wire_in_the_same_window_answers_the_buffered_conflict(api):
    """Repairing the rank-53 defect hands the same window to rank 67.

    PRD §2.8: "When a single request violates more than one rule, exactly one error is
    returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "53. `ERR_WIRE_DIAMETER_EXCEEDS_MACHINE` — on `POST /machine-setups`."
    PRD §2.8: "67. `ERR_SETUP_WINDOW_CONFLICT` — on `POST /machine-setups`."
    PRD §3.6: "The design's `wire_diameter_mm` must not exceed the coiler's `max_wire_diameter_mm`, or the booking answers `ERR_WIRE_DIAMETER_EXCEEDS_MACHINE` (HTTP 422) — and this ceiling is checked **before** the window arithmetic, so a too-heavy wire on a busy machine reports the diameter problem rather than a clash."
    PRD §3.6: "Two windows conflict when the new window's start is strictly earlier than the existing window's end plus the buffer **and** the existing window's start is strictly earlier than the new window's end plus the buffer."
    PRD §3.6: "Only setups on the same machine whose `setup_status` is `SCHEDULED` or `ACTIVE` are considered; `RELEASED`, `SUPERSEDED` and `ABORTED` setups never conflict, however their windows fall."
    PRD §3.6: "If any such conflicting setup exists, the booking is rejected with `ERR_SETUP_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/wire_diameter_constraint_outranks_setup_window_conflict_temporal_on_setup_creation
    """
    world = _buffered_coiler_world(api)
    machine_version_before = world.machine["version"]
    thin = world.extra["second_thin"]

    thick_attempt = api.create_setup(
        F.setup_payload(
            world.machine_id,
            world.design_id,
            world.tooling_id,
            machine_version_before,
            window_start=_INSIDE_BUFFER_START,
            window_end=_LATE_WINDOW_END,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(thick_attempt, ERR_WIRE_DIAMETER_EXCEEDS_MACHINE, 422)

    assert thin["wire_diameter_mm"] <= _NARROW_CEILING_MM, (
        f"the replacement design's 1.2 mm wire clears the 2.0 mm ceiling, got {thin['wire_diameter_mm']}"
    )

    thin_attempt = api.create_setup(
        F.setup_payload(
            world.machine_id,
            thin["id"],
            world.extra["second_thin_tool"]["id"],
            machine_version_before,
            window_start=_INSIDE_BUFFER_START,
            window_end=_LATE_WINDOW_END,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(thin_attempt, ERR_SETUP_WINDOW_CONFLICT, 409)

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["version"] == machine_version_before, (
        f"neither rejected booking bumps the coiler's version, got {machine['version']}"
    )

    occupying = X.refresh_setup(api, world.setup_id)
    assert occupying["setup_status"] == C.SETUP_SCHEDULED, (
        f"the occupying setup is untouched, got {occupying['setup_status']}"
    )
    assert occupying["superseded_by_setup_id"] is None, (
        f"nothing superseded it, got {occupying['superseded_by_setup_id']}"
    )

    _, meta = validate_paginated(
        api.list_setups(PROCESS_TECHNICIAN_HEADERS, {"machine_id": world.machine_id})
    )
    assert meta["total_count"] == 1, (
        f"two rejections leave the coiler with one setup, got {meta['total_count']}"
    )


def test_thick_wire_on_the_buffer_boundary_still_answers_the_diameter_ceiling(api):
    """At a buffer-legal 12:45Z start only rank 53 is left to answer.

    PRD §2.8: "53. `ERR_WIRE_DIAMETER_EXCEEDS_MACHINE` — on `POST /machine-setups`."
    PRD §2.8: "67. `ERR_SETUP_WINDOW_CONFLICT` — on `POST /machine-setups`."
    PRD §3.6: "The design's `wire_diameter_mm` must not exceed the coiler's `max_wire_diameter_mm`, or the booking answers `ERR_WIRE_DIAMETER_EXCEEDS_MACHINE` (HTTP 422) — and this ceiling is checked **before** the window arithmetic, so a too-heavy wire on a busy machine reports the diameter problem rather than a clash."
    PRD §3.6: "A gap exactly equal to `changeover_buffer_minutes` between two windows is permitted — the comparison is strict on both sides, so touching the buffer boundary is legal."
    PRD §3.6: "A successful booking stamps `set_by_user_id` from the technician's `X-User-ID`, opens the setup in `setup_status` `SCHEDULED`, and increases the coiler's `version` by 1."
    PRD §3.6: "It also performs a supersession sweep: every **other** setup on the same machine for the same design whose `setup_status` is `SCHEDULED` transitions `SCHEDULED → SUPERSEDED`, and each superseded row's `superseded_by_setup_id` is set to the id of the setup that has just been created."

    Design: Difficulty/priority_pair_validation_conflict/wire_diameter_constraint_outranks_setup_window_conflict_temporal_on_setup_creation
    """
    world = _buffered_coiler_world(api)
    machine_version_before = world.machine["version"]

    refused = api.create_setup(
        F.setup_payload(
            world.machine_id,
            world.design_id,
            world.tooling_id,
            machine_version_before,
            window_start=_ON_BUFFER_START,
            window_end=_LATE_WINDOW_END,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(refused, ERR_WIRE_DIAMETER_EXCEEDS_MACHINE, 422)

    # The same 12:45Z start is genuinely buffer-legal: a thin design takes it.
    allowed = api.create_setup(
        F.setup_payload(
            world.machine_id,
            world.extra["second_thin"]["id"],
            world.extra["second_thin_tool"]["id"],
            machine_version_before,
            window_start=_ON_BUFFER_START,
            window_end=_LATE_WINDOW_END,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    booked = validate_success(allowed, 201)
    assert booked["setup_status"] == C.SETUP_SCHEDULED, (
        f"a booking on the buffer boundary opens SCHEDULED, got {booked['setup_status']}"
    )
    assert booked["window_start"] == _ON_BUFFER_START, (
        f"the accepted window starts exactly 45 minutes after 12:00Z, got {booked['window_start']}"
    )

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["version"] == machine_version_before + 1, (
        "only the accepted booking bumps the coiler's version, and only once, got "
        f"{machine['version']}"
    )

    occupying = X.refresh_setup(api, world.setup_id)
    assert occupying["setup_status"] == C.SETUP_SCHEDULED, (
        "the earlier setup is for a different design, so the sweep leaves it alone, got "
        f"{occupying['setup_status']}"
    )
    assert occupying["superseded_by_setup_id"] is None, (
        f"and nothing superseded it, got {occupying['superseded_by_setup_id']}"
    )

    _, meta = validate_paginated(
        api.list_setups(PROCESS_TECHNICIAN_HEADERS, {"machine_id": world.machine_id})
    )
    assert meta["total_count"] == 2, (
        f"one refusal and one booking leave the coiler with two setups, got {meta['total_count']}"
    )
