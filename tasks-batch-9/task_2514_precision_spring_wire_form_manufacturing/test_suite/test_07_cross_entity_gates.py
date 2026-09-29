"""
Gates that read the state of an entity the request never names.

Whether a packed lot may ship depends on the standing of the tooling asset
behind its run's design; whether a lot may be allocated at all depends on the
live verdict carried by the program's newest qualification package; and whether
a production run may open depends on the incoming tensile verdict of the heat it
draws from. Each concern is proved from both sides: once with the far entity in
the state that refuses the request, and once with the identical request going
through after that entity has been put right.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_INTERIM_PIECE_CAP_EXCEEDED,
    ERR_PPAP_NOT_APPROVED,
    ERR_PROGRAM_POSTURE_BLOCKED,
    ERR_TOOLING_NOT_AMORTIZING,
    ERR_WIRE_LOT_NOT_CERTIFIED,
)
from test_helpers.test_users import (
    ENGINEERING_MANAGER_HEADERS,
    PROCESS_TECHNICIAN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
)


def _amortizing_safety_world(api: ApiClient) -> X.World:
    """A fully approved AUTOMOTIVE_SAFETY program on an AMORTIZING 4 800 000-cent tool.

    The chain runs program, grade, design D1, characteristic plan, prototype
    release, tooling, coiler, setup, certified heat, 26 000-piece run, first
    article, in-process subgroup, completion at 25 500 + 500, stress relief,
    quote at 26 000, PPAP package and the customer's full APPROVE.
    """
    return X.build_world(
        api,
        "approved",
        program={
            "program_code": "PGM-AUTO-5",
            "customer_name": "Northwind Drivetrain",
            "application_class": C.CLASS_AUTOMOTIVE_SAFETY,
            "ppap_level": 3,
            "required_ppk": 1.33,
        },
        submission={"ppap_level": 3},
    )


def test_packed_lot_ships_while_the_design_tooling_is_still_amortizing(api):
    """PRD §3.11: "The design's newest tooling asset must have an `amortization_status`
    of `AMORTIZING` or `FULLY_AMORTIZED`, otherwise `ERR_TOOLING_NOT_AMORTIZING` (HTTP
    409) — this is the gate that holds interim-approved lots in the warehouse."

    PRD §3.11: "Shipping then posts the tooling recovery computed under the program's
    `amortization_method` as described in section 3.4, writes it to the lot's
    `tooling_recovery_cents`, adds it to the tool's `recovered_cents` and subtracts it
    from `unamortized_cents`, and takes the tool `AMORTIZING → FULLY_AMORTIZED` if that
    leaves `unamortized_cents` at zero."

    PRD §3.4: "Under `FORECAST_BASIS` — a straight-line forecast recovery — the amount
    is the lot's `piece_count` multiplied by the tool's frozen `amort_per_piece_cents`,
    capped at the tool's live `unamortized_cents`; whichever of the two is smaller is
    posted."

    PRD §3.11: "On the program, `allocated_pieces` decreases by `piece_count` and
    `shipped_pieces` increases by it — `open_commitment_pieces` is untouched, because
    the commitment was consumed at allocation."

    Design: Difficulty/cross_entity_state_dependency/lot_ship_blocked_by_written_off_tooling_after_design_obsolescence
    """
    world = _amortizing_safety_world(api)
    lot_a = X.allocate_lot(api, world.run_id, world.program_id, 1_000)
    X.allocate_lot(api, world.run_id, world.program_id, 1_000)
    X.pack_lot(api, lot_a["id"], C.PACK_TANGLE_FREE_TRAY)

    tool_before = X.refresh_tooling(api, world.tooling_id)
    assert tool_before["amortization_status"] == C.AMORT_AMORTIZING, (
        "the full approval promoted the design to PRODUCTION_RELEASED, which arms the "
        f"tool for amortization, got {tool_before['amortization_status']}"
    )
    assert tool_before["amort_per_piece_cents"] == A.expected_amort_per_piece_cents(
        4_800_000, 500_000
    ) == 10, (
        "4 800 000 cents over a 500 000-piece basis rounds up to 10 cents per piece, "
        f"got {tool_before['amort_per_piece_cents']}"
    )

    shipped = validate_success(api.ship_lot(lot_a["id"], PROGRAM_MANAGER_HEADERS))
    assert shipped["lot_status"] == C.LOT_SHIPPED, (
        f"a packed lot behind an AMORTIZING tool ships, got {shipped['lot_status']}"
    )
    expected_recovery = A.expected_forecast_recovery_cents(1_000, 10, 4_800_000)
    assert expected_recovery == 10_000
    assert shipped["tooling_recovery_cents"] == 10_000, (
        "1 000 pieces at the frozen 10 cents per piece posts 10 000 cents, got "
        f"{shipped['tooling_recovery_cents']}"
    )

    tool = X.refresh_tooling(api, world.tooling_id)
    assert tool["recovered_cents"] == 10_000, (
        f"the posting lands in recovered_cents, got {tool['recovered_cents']}"
    )
    assert tool["unamortized_cents"] == 4_790_000, (
        "4 800 000 less the 10 000-cent posting leaves 4 790 000, got "
        f"{tool['unamortized_cents']}"
    )
    assert tool["amortization_status"] == C.AMORT_AMORTIZING, (
        "the balance is still positive, so the tool stays AMORTIZING, got "
        f"{tool['amortization_status']}"
    )
    A.assert_tooling_ledger_conserved(tool)

    program = X.refresh_program(api, world.program_id)
    assert program["shipped_pieces"] == 1_000, (
        f"shipped_pieces takes the lot's pieces, got {program['shipped_pieces']}"
    )
    assert program["allocated_pieces"] == 1_000, (
        "the second lot is still allocated, got "
        f"{program['allocated_pieces']}"
    )
    assert program["open_commitment_pieces"] == 498_000, (
        "shipping does not touch open_commitment_pieces, got "
        f"{program['open_commitment_pieces']}"
    )
    A.assert_commitment_conserved(program)


def test_packed_lot_refused_once_design_obsolescence_writes_the_tooling_off(api):
    """PRD §3.3: "On success the design moves to `OBSOLETE`; every tooling asset of the
    design whose `amortization_status` is `PENDING` or `AMORTIZING` transitions to
    `WRITTEN_OFF`, with `unamortized_cents` and `recovered_cents` left exactly as they
    stood — a write-off records the loss, it does not zero the ledger; every machine
    setup of the design still in `SCHEDULED` transitions to `ABORTED`; and the owning
    program's `delivery_posture` is re-derived, which lands on `BLOCKED`."

    PRD §3.11: "The design's newest tooling asset must have an `amortization_status`
    of `AMORTIZING` or `FULLY_AMORTIZED`, otherwise `ERR_TOOLING_NOT_AMORTIZING` (HTTP
    409) — this is the gate that holds interim-approved lots in the warehouse."

    PRD §3.11: "`tooling_recovery_cents` starts at 0 and `shipped_at` and
    `quarantine_reason` start null."

    Design: Difficulty/cross_entity_state_dependency/lot_ship_blocked_by_written_off_tooling_after_design_obsolescence
    """
    world = _amortizing_safety_world(api)
    lot_a = X.allocate_lot(api, world.run_id, world.program_id, 1_000)
    lot_b = X.allocate_lot(api, world.run_id, world.program_id, 1_000)

    X.pack_lot(api, lot_a["id"], C.PACK_TANGLE_FREE_TRAY)
    X.ship_lot(api, lot_a["id"])
    X.pack_lot(api, lot_b["id"], C.PACK_TANGLE_FREE_TRAY)

    packed_b = X.refresh_lot(api, lot_b["id"])
    assert packed_b["lot_status"] == C.LOT_PACKED, (
        f"lot B is packed and identical to lot A, got {packed_b['lot_status']}"
    )
    assert packed_b["tooling_recovery_cents"] == 0, (
        "an unshipped lot carries a zero recovery, got "
        f"{packed_b['tooling_recovery_cents']}"
    )

    retired = validate_success(
        api.obsolete_design(world.design_id, ENGINEERING_MANAGER_HEADERS)
    )
    assert retired["release_status"] == C.RELEASE_OBSOLETE, (
        f"retirement moves the design to OBSOLETE, got {retired['release_status']}"
    )

    tool = X.refresh_tooling(api, world.tooling_id)
    assert tool["amortization_status"] == C.AMORT_WRITTEN_OFF, (
        "an AMORTIZING tool of the retired design is written off, got "
        f"{tool['amortization_status']}"
    )
    assert tool["recovered_cents"] == 10_000, (
        "the write-off leaves recovered_cents exactly as it stood, got "
        f"{tool['recovered_cents']}"
    )
    assert tool["unamortized_cents"] == 4_790_000, (
        "the write-off records the loss without zeroing the ledger, got "
        f"{tool['unamortized_cents']}"
    )
    A.assert_tooling_ledger_conserved(tool)

    refused = api.ship_lot(lot_b["id"], PROGRAM_MANAGER_HEADERS)
    validate_error_is_one_of(
        refused, [ERR_TOOLING_NOT_AMORTIZING, ERR_PROGRAM_POSTURE_BLOCKED]
    )

    after = X.refresh_lot(api, lot_b["id"])
    assert after["lot_status"] == C.LOT_PACKED, (
        f"the refused lot stays on the dock as PACKED, got {after['lot_status']}"
    )
    assert after["tooling_recovery_cents"] == 0, (
        "no recovery is posted for a refused shipment, got "
        f"{after['tooling_recovery_cents']}"
    )
    assert after["shipped_at"] is None, (
        f"shipped_at stays null on a refused shipment, got {after['shipped_at']}"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["shipped_pieces"] == 1_000, (
        "only lot A ever shipped, got " f"{program['shipped_pieces']}"
    )
    assert program["allocated_pieces"] == 1_000, (
        f"lot B is still on allocation, got {program['allocated_pieces']}"
    )
    assert program["open_commitment_pieces"] == 498_000, (
        "both allocations already left the commitment, got "
        f"{program['open_commitment_pieces']}"
    )
    A.assert_commitment_conserved(program)


def _interim_capped_world(api: ApiClient, cap: int = 2_500) -> X.World:
    """An AUTOMOTIVE_NON_SAFETY program whose round-1 package is INTERIM_APPROVED."""
    return X.interim_approved_world(
        api,
        cap,
        program={
            "program_code": "PGM-AUTO-6",
            "customer_name": "Kestrel Actuation",
            "application_class": C.CLASS_AUTOMOTIVE_NON_SAFETY,
            "ppap_level": 2,
            "required_ppk": 1.33,
        },
        submission={"ppap_level": 2},
    )


def test_lot_allocation_stops_at_the_interim_verdicts_piece_ceiling(api):
    """PRD §3.11: "And if the newest submission is `INTERIM_APPROVED`, the program's
    `allocated_pieces` plus `shipped_pieces` plus this `piece_count` must not exceed
    that submission's `interim_piece_cap`, otherwise `ERR_INTERIM_PIECE_CAP_EXCEEDED`
    (HTTP 422)."

    PRD §3.10: "What it deliberately does **not** do is promote anything: the design
    stays `PROTOTYPE_RELEASED` and every tooling asset stays `PENDING`, because only a
    full `APPROVE` arms amortization."

    PRD §3.11: "On the program, `open_commitment_pieces` decreases by `piece_count` and
    `allocated_pieces` increases by it, conserving `committed_pieces`, and
    `delivery_posture` is re-derived."

    Design: Difficulty/cross_entity_state_dependency/lot_creation_capped_by_interim_approved_submission_then_reopened_by_resubmit
    """
    world = _interim_capped_world(api, 2_500)
    assert world.submission["submission_status"] == C.SUBMISSION_INTERIM_APPROVED, (
        "the customer's conditional verdict is on file, got "
        f"{world.submission['submission_status']}"
    )
    assert world.submission["interim_piece_cap"] == 2_500, (
        f"the verdict carries its ceiling, got {world.submission['interim_piece_cap']}"
    )

    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_PROTOTYPE, (
        "an interim verdict never promotes the design, got "
        f"{design['release_status']}"
    )
    tool = X.refresh_tooling(api, world.tooling_id)
    assert tool["amortization_status"] == C.AMORT_PENDING, (
        f"nothing is armed for amortization, got {tool['amortization_status']}"
    )

    first = validate_success(
        api.create_lot(
            F.lot_payload(world.run_id, world.program_id, 1_000),
            PROGRAM_MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    assert first["lot_status"] == C.LOT_ALLOCATED, (
        "1 000 pieces sits inside the 2 500-piece ceiling, got "
        f"{first['lot_status']}"
    )
    second = validate_success(
        api.create_lot(
            F.lot_payload(world.run_id, world.program_id, 1_000),
            PROGRAM_MANAGER_HEADERS,
        ),
        expected_status=201,
    )
    assert second["lot_status"] == C.LOT_ALLOCATED, (
        "a cumulative 2 000 pieces still sits inside the ceiling, got "
        f"{second['lot_status']}"
    )

    after_two = X.refresh_program(api, world.program_id)
    assert after_two["allocated_pieces"] == 2_000, (
        f"two 1 000-piece lots are allocated, got {after_two['allocated_pieces']}"
    )
    assert after_two["shipped_pieces"] == 0, (
        f"nothing has shipped yet, got {after_two['shipped_pieces']}"
    )

    refused = api.create_lot(
        F.lot_payload(world.run_id, world.program_id, 1_000), PROGRAM_MANAGER_HEADERS
    )
    validate_error(refused, ERR_INTERIM_PIECE_CAP_EXCEEDED)

    program = X.refresh_program(api, world.program_id)
    assert program["allocated_pieces"] == 2_000, (
        "2 000 + 1 000 exceeds 2 500, so the third lot never opened, got "
        f"{program['allocated_pieces']}"
    )
    assert program["shipped_pieces"] == 0, (
        f"nothing has shipped, got {program['shipped_pieces']}"
    )
    assert program["open_commitment_pieces"] == 498_000, (
        "only the two admitted allocations left the commitment, got "
        f"{program['open_commitment_pieces']}"
    )
    A.assert_commitment_conserved(program)


def test_lot_allocation_reopens_on_the_missing_verdict_after_a_resubmit(api):
    """PRD §3.10: "A successful resubmit increments `round_no` by 1, returns
    `submission_status` to `SUBMITTED`, clears `interim_piece_cap` back to null, clears
    `reviewed_by_program_id` and `decided_at` back to null, and re-stamps
    `submitted_by_user_id` from the acting header."

    PRD §3.10: "Resubmitting from `INTERIM_APPROVED` therefore withdraws the cap that
    was letting the program allocate pieces, and the re-derived `delivery_posture`
    returns to `BLOCKED` while no verdict is in force — lots already allocated stay
    allocated, but no new one can be created until the next verdict lands."

    PRD §3.11: "The PPAP standing gate requires both that the design's `release_status`
    is `PROTOTYPE_RELEASED` or `PRODUCTION_RELEASED` **and** that the newest
    qualification submission by `created_at` for the program and the run's design has a
    `submission_status` of `APPROVED` or `INTERIM_APPROVED`; a failure answers
    `ERR_PPAP_NOT_APPROVED` (HTTP 422)."

    PRD §3.11: "The program's `delivery_posture` must not be `BLOCKED`, which answers
    `ERR_PROGRAM_POSTURE_BLOCKED` (HTTP 409); as section 2.8 explains, on this endpoint
    that row is structurally shadowed by the PPAP gate."

    Design: Difficulty/cross_entity_state_dependency/lot_creation_capped_by_interim_approved_submission_then_reopened_by_resubmit
    """
    world = _interim_capped_world(api, 2_500)
    round_before = world.submission["round_no"]

    X.allocate_lot(api, world.run_id, world.program_id, 1_000)
    X.allocate_lot(api, world.run_id, world.program_id, 1_000)

    reopened = validate_success(
        api.resubmit_submission(world.submission_id, PROGRAM_MANAGER_HEADERS)
    )
    assert reopened["submission_status"] == C.SUBMISSION_SUBMITTED, (
        "the resubmit returns the package to SUBMITTED, got "
        f"{reopened['submission_status']}"
    )
    assert reopened["round_no"] == round_before + 1 == 2, (
        f"round_no rises by one from {round_before}, got {reopened['round_no']}"
    )
    assert reopened["interim_piece_cap"] is None, (
        "the resubmit withdraws the ceiling, got "
        f"{reopened['interim_piece_cap']}"
    )
    assert reopened["reviewed_by_program_id"] is None, (
        "the resubmit clears the reviewer, got "
        f"{reopened['reviewed_by_program_id']}"
    )
    assert reopened["decided_at"] is None, (
        f"the resubmit clears the verdict instant, got {reopened['decided_at']}"
    )

    blocked = X.refresh_program(api, world.program_id)
    assert blocked["delivery_posture"] == C.POSTURE_BLOCKED, (
        "no verdict is in force, so the posture returns to BLOCKED, got "
        f"{blocked['delivery_posture']}"
    )

    refused = api.create_lot(
        F.lot_payload(world.run_id, world.program_id, 1_000), PROGRAM_MANAGER_HEADERS
    )
    validate_error(refused, ERR_PPAP_NOT_APPROVED)

    program = X.refresh_program(api, world.program_id)
    assert program["allocated_pieces"] == 2_000, (
        "lots already allocated stay allocated, got "
        f"{program['allocated_pieces']}"
    )
    assert program["shipped_pieces"] == 0, (
        f"nothing has shipped, got {program['shipped_pieces']}"
    )
    assert program["open_commitment_pieces"] == 498_000, (
        "the refused request moved no pieces, got "
        f"{program['open_commitment_pieces']}"
    )
    A.assert_commitment_conserved(program)

    tool = X.refresh_tooling(api, world.tooling_id)
    assert tool["amortization_status"] == C.AMORT_PENDING, (
        "no full approval ever happened, so nothing was armed, got "
        f"{tool['amortization_status']}"
    )


def _mounted_industrial_world(api: ApiClient) -> X.World:
    """An INDUSTRIAL program with design D1 mounted and ACTIVE on COIL-9.

    The clock sits at 08:30Z, inside the booked [08:00Z, 12:00Z) window, so the
    activation is legal and no heat has been received yet.
    """
    return X.build_world(
        api,
        "active_setup",
        program={
            "program_code": "PGM-IND-8",
            "customer_name": "Bramble Industrial Supply",
            "committed_pieces": 100_000,
        },
        machine={"machine_code": "COIL-9"},
        activation_clock=C.CLOCK_INSIDE_SETUP_WINDOW,
    )


def test_run_refused_against_a_rejected_or_an_untested_heat(api):
    """PRD §3.7: "The heat's `certification_status` must be `CERTIFIED`; an
    `UNCERTIFIED` or `REJECTED` heat answers `ERR_WIRE_LOT_NOT_CERTIFIED` (HTTP 422)."

    PRD §3.5: "The outcomes differ only in the comparison against the grade: when the
    measured value is at least the linked material specification's `tensile_grade_mpa`,
    the lot moves `UNCERTIFIED → CERTIFIED`; when the measured value falls below that
    grade, the lot moves `UNCERTIFIED → REJECTED` and no run may ever draw from it."

    PRD §3.5: "At receipt the three buckets are opened with all mass free: `on_hand_kg`
    equals `received_kg`, while `reserved_kg` and `consumed_kg` both start at 0.000."

    PRD §2.9: "Every reservation, release and consumption posting moves mass between
    these three and never creates or destroys any."

    PRD §3.6: "On success the coiler transitions `IDLE → SETUP`, its `active_setup_id`
    is set to this setup's id, and its `version` increases by 1."

    Design: Difficulty/cross_entity_state_dependency/run_creation_blocked_by_rejected_and_untested_wire_heats
    """
    world = _mounted_industrial_world(api)

    bad = X.receive_wire(
        api, world.material_id, QUALITY_INSPECTOR_HEADERS, heat_number="HT-BAD",
        received_kg=500.0,
    )
    bad = X.certify_wire(api, bad["id"], QUALITY_INSPECTOR_HEADERS, tensile_test_mpa=1899)
    assert bad["certification_status"] == C.CERT_REJECTED, (
        "1899 MPa falls below the 1900 MPa grade, got "
        f"{bad['certification_status']}"
    )

    raw = X.receive_wire(
        api, world.material_id, QUALITY_INSPECTOR_HEADERS, heat_number="HT-RAW",
        received_kg=500.0,
    )
    assert raw["certification_status"] == C.CERT_UNCERTIFIED, (
        "an untested heat opens UNCERTIFIED, got "
        f"{raw['certification_status']}"
    )

    against_rejected = api.create_run(
        F.run_payload(world.setup_id, bad["id"], world.design_id, planned_pieces=1_000),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(against_rejected, ERR_WIRE_LOT_NOT_CERTIFIED)

    against_untested = api.create_run(
        F.run_payload(world.setup_id, raw["id"], world.design_id, planned_pieces=1_000),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(against_untested, ERR_WIRE_LOT_NOT_CERTIFIED)

    for label, heat_id in (("HT-BAD", bad["id"]), ("HT-RAW", raw["id"])):
        heat = X.refresh_wire_lot(api, heat_id)
        assert heat["on_hand_kg"] == 500.000, (
            f"{label} keeps all 500.000 kg free, got {heat['on_hand_kg']}"
        )
        assert heat["reserved_kg"] == 0.000, (
            f"{label} holds no reservation, got {heat['reserved_kg']}"
        )
        assert heat["consumed_kg"] == 0.000, (
            f"{label} has burned nothing, got {heat['consumed_kg']}"
        )
        A.assert_wire_ledger_conserved(heat)

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_SETUP, (
        "a refused run never occupies the coiler, so it stays in SETUP, got "
        f"{machine['machine_state']}"
    )
    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_ACTIVE, (
        f"the mounted setup is still ACTIVE, got {setup['setup_status']}"
    )


def test_run_admitted_once_the_heat_clears_its_incoming_tensile_test(api):
    """PRD §3.7: "The heat's `certification_status` must be `CERTIFIED`; an
    `UNCERTIFIED` or `REJECTED` heat answers `ERR_WIRE_LOT_NOT_CERTIFIED` (HTTP 422)."

    PRD §3.5: "The outcomes differ only in the comparison against the grade: when the
    measured value is at least the linked material specification's `tensile_grade_mpa`,
    the lot moves `UNCERTIFIED → CERTIFIED`; when the measured value falls below that
    grade, the lot moves `UNCERTIFIED → REJECTED` and no run may ever draw from it."

    PRD §3.7: "That figure is written to the run's `wire_reserved_kg` and is the value
    compared against the heat's `on_hand_kg` for the sufficiency gate; the heat's ledger
    is never fed into the computation, only compared against its result."

    PRD §3.7: "On success the reservation moves mass without creating any:
    `wire_reserved_kg` is subtracted from the heat's `on_hand_kg` and added to its
    `reserved_kg`, leaving `received_kg` untouched."

    PRD §3.7: "Its coiler transitions `SETUP → PRODUCTION` and the machine's `version`
    increases by 1."

    Design: Difficulty/cross_entity_state_dependency/run_creation_blocked_by_rejected_and_untested_wire_heats
    """
    world = _mounted_industrial_world(api)
    heat = X.receive_wire(
        api, world.material_id, QUALITY_INSPECTOR_HEADERS, heat_number="HT-OK",
        received_kg=500.0,
    )

    payload = F.run_payload(
        world.setup_id, heat["id"], world.design_id, planned_pieces=1_000
    )
    validate_error(
        api.create_run(payload, PROCESS_TECHNICIAN_HEADERS), ERR_WIRE_LOT_NOT_CERTIFIED
    )

    certified = X.certify_wire(
        api, heat["id"], QUALITY_INSPECTOR_HEADERS, tensile_test_mpa=1930
    )
    assert certified["certification_status"] == C.CERT_CERTIFIED, (
        "1930 MPa clears the 1900 MPa grade, got "
        f"{certified['certification_status']}"
    )

    run = validate_success(
        api.create_run(payload, PROCESS_TECHNICIAN_HEADERS), expected_status=201
    )
    expected_reserved = A.expected_wire_reserved_kg(C.D1_WIRE_MASS_PER_PIECE_KG, 1_000)
    assert expected_reserved == 21.821
    assert run["wire_reserved_kg"] == 21.821, (
        "0.021185 kg per piece over 1 000 pieces inflated three percent rounds to "
        f"21.821 kg, got {run['wire_reserved_kg']}"
    )
    assert run["process_status"] == C.PROCESS_FAI_PENDING, (
        f"a new run opens FAI_PENDING, got {run['process_status']}"
    )

    after = X.refresh_wire_lot(api, heat["id"])
    assert after["on_hand_kg"] == 478.179, (
        f"500.000 less the 21.821 kg reservation leaves 478.179, got {after['on_hand_kg']}"
    )
    assert after["reserved_kg"] == 21.821, (
        f"the same mass lands in reserved_kg, got {after['reserved_kg']}"
    )
    assert after["received_kg"] == 500.000, (
        f"received_kg is untouched by a reservation, got {after['received_kg']}"
    )
    A.assert_wire_ledger_conserved(after)

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_PRODUCTION, (
        "opening the run takes the coiler SETUP to PRODUCTION, got "
        f"{machine['machine_state']}"
    )
    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_ACTIVE, (
        f"the setup remains ACTIVE while the run coils, got {setup['setup_status']}"
    )
