"""Two writes refused by a state that lives on an entirely different row.

Production start is blocked by the parent program's ledger rather than by
anything about the unit, and certification submission — a payload that names no
trip at all — is blocked by the state of one particular inspection trip.
"""

from test_helpers import (
    BuildStatus,
    CertificationStatus,
    CertificationTestStatus,
    ErrorCode,
    LongLeadStatus,
    ProgramStatus,
    ReservationStatus,
    SuspensionReason,
    TripStatus,
    assert_list_meta,
    assert_program_ledger,
    assert_slot_occupancy,
    assert_unit_dimensions,
    award_unit,
    confirm_reservation,
    create_slot_line,
    make_program_admin_headers,
    make_third_party_tester_headers,
    read_program,
    read_reservation,
    read_slot_line,
    read_trip,
    read_unit,
    reserve_slot,
    schedule_trip,
    setup_unit_at_stage,
    validate_error,
    validate_paginated,
    validate_success,
)


PUMP_CLAUSE = [
    {"clause_code": "C1", "category": "PUMP",
     "requirement_text": "1500 gpm single stage pump",
     "mandatory": True, "is_restrictive": False},
]


def _confirmed_slot_for(api, ctx):
    """Book and confirm one chassis slot for the context's unit."""
    line = create_slot_line(api, supplier_name="Freightline Custom Chassis",
                            component_type="CHASSIS", total_slot_count=2)
    reservation = reserve_slot(api, ctx["program_id"], line["id"],
                              unit_order_id=ctx["unit_id"])
    ctx["reservation_id"] = reservation["id"]
    ctx["reservation"] = confirm_reservation(api, reservation["id"])
    ctx["slot_line_id"] = line["id"]
    return line


def _ready_unit_under_a_tight_ceiling(api):
    """Unit A is PRE_CON_HELD with a CONFIRMED chassis slot; the ceiling is tight.

    A hard ceiling of 150,000,000 puts the soft ceiling at 135,000,000, so a
    second award of 68,276,000 cents breaches it.
    """
    ctx = setup_unit_at_stage(
        api, "PRE_CON_HELD",
        program_overrides={"name": "Soft ceiling program",
                           "agency_name": "Brookfield Fire",
                           "max_option_units": 1,
                           "contract_ceiling_cents": 150_000_000},
        clauses=PUMP_CLAUSE,
        bay_overrides={"name": "Bay A", "max_concurrent_visitors": 10},
        pre_trip_overrides={"scheduled_start": "2026-08-10T08:00:00Z",
                            "scheduled_end": "2026-08-10T16:00:00Z"},
    )
    _confirmed_slot_for(api, ctx)
    sibling = award_unit(api, ctx["program_id"], ctx["specification_id"])
    ctx["sibling_id"] = sibling["id"]
    ctx["sibling"] = sibling
    return ctx


def _in_production_unit_with_a_scheduled_mid_trip(api):
    """The pre-construction trip is HELD; the mid-construction trip is SCHEDULED."""
    ctx = setup_unit_at_stage(
        api, "IN_PRODUCTION",
        program_overrides={"name": "Gate program",
                           "agency_name": "Fairhaven Fire",
                           "max_option_units": 1},
        clauses=PUMP_CLAUSE,
        bay_overrides={"name": "Bay A", "max_concurrent_visitors": 10},
        pre_trip_overrides={"scheduled_start": "2026-08-10T08:00:00Z",
                            "scheduled_end": "2026-08-10T16:00:00Z"},
        slot_line_overrides={"supplier_name": "Freightline Custom Chassis",
                             "total_slot_count": 2},
    )
    mid_trip = schedule_trip(api, ctx["unit_id"], ctx["bay_id"],
                             trip_type="MID_CONSTRUCTION",
                             scheduled_start="2026-09-20T08:00:00Z",
                             scheduled_end="2026-09-20T16:00:00Z",
                             committee_size=4)
    ctx["mid_trip_id"] = mid_trip["id"]
    ctx["mid_trip"] = mid_trip
    return ctx


def test_a_sibling_award_suspends_the_program_and_freezes_a_faultless_unit(
        api, admin_headers):
    """Unit A satisfies every gate about itself and is still refused.

    PRD 3.9: "Two cross-entity guards apply on two different partners: the owning
    program's `status` must be `ACTIVE`, or the call is refused with
    `ERR_PROGRAM_NOT_ACTIVE`; and the unit's `chassis_reservation_id` must be
    non-null with that reservation's `status` reading `CONFIRMED`, or the call is
    refused with `ERR_CHASSIS_NOT_CONFIRMED`."
    PRD 2.10: "A write whose resulting `committed_cents` strictly exceeds the soft
    ceiling while remaining at or below the hard ceiling *succeeds*, and the
    program is automatically moved from `ACTIVE` to `SUSPENDED` inside that very
    same request with `suspension_reason` set to `SOFT_CEILING_BREACH`."
    PRD 2.10: "reactivation is itself refused with
    `ERR_SOFT_CEILING_STILL_BREACHED` while committed money still exceeds the soft
    ceiling, whatever the original reason for the suspension was."

    Design: Difficulty/cross_entity_state_dependency/production_start_blocked_by_program_auto_suspension_from_sibling_award
    """
    ctx = _ready_unit_under_a_tight_ceiling(api)

    breached = read_program(api, ctx["program_id"])
    assert_program_ledger(breached, 136_552_000, ProgramStatus.SUSPENDED.value,
                          SuspensionReason.SOFT_CEILING_BREACH.value)

    unit = read_unit(api, ctx["unit_id"])
    assert_unit_dimensions(unit, build_status=BuildStatus.PRE_CON_HELD.value,
                           long_lead_status=LongLeadStatus.CONFIRMED.value)
    assert read_reservation(api, ctx["reservation_id"])["status"] == \
        ReservationStatus.CONFIRMED.value

    validate_error(
        api.start_production(ctx["unit_id"], admin_headers),
        ErrorCode.ERR_PROGRAM_NOT_ACTIVE,
        409,
    )
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.PRE_CON_HELD.value)

    validate_error(
        api.reactivate_program(ctx["program_id"], admin_headers),
        ErrorCode.ERR_SOFT_CEILING_STILL_BREACHED,
        409,
    )
    assert_program_ledger(read_program(api, ctx["program_id"]), 136_552_000,
                          ProgramStatus.SUSPENDED.value,
                          SuspensionReason.SOFT_CEILING_BREACH.value)


def test_the_block_clears_only_after_a_cancellation_and_an_explicit_reactivation(
        api, admin_headers):
    """Decommitting the sibling is not enough; a human has to reactivate.

    PRD 2.10: "Recovery from a soft-ceiling suspension is never automatic.
    Cancelling a unit or rescinding a change order may pull `committed_cents` back
    under the soft ceiling, but the program stays `SUSPENDED` until a
    `ProgramAdmin` explicitly reactivates it".
    PRD 3.9: "Starting production consumes the reservation, moving it `CONFIRMED`
    to `CONSUMED`, recomputes the supplier line's `reserved_slot_count` and
    `available_slot_count` (which come out unchanged, since a consumed slot is
    still an occupied slot) and increments the line's `version`, the reservation's
    `version` and the unit's `version`."

    Design: Difficulty/cross_entity_state_dependency/production_start_blocked_by_program_auto_suspension_from_sibling_award
    """
    ctx = _ready_unit_under_a_tight_ceiling(api)

    cancelled = validate_success(
        api.cancel_unit_order(ctx["sibling_id"], admin_headers)
    )
    assert cancelled["build_status"] == BuildStatus.CANCELLED.value, cancelled
    assert_program_ledger(read_program(api, ctx["program_id"]), 68_276_000,
                          ProgramStatus.SUSPENDED.value,
                          SuspensionReason.SOFT_CEILING_BREACH.value)

    reactivated = validate_success(
        api.reactivate_program(ctx["program_id"], admin_headers)
    )
    assert_program_ledger(reactivated, 68_276_000, ProgramStatus.ACTIVE.value, None)

    started = validate_success(api.start_production(ctx["unit_id"], admin_headers))
    assert started["build_status"] == BuildStatus.IN_PRODUCTION.value, started
    assert read_reservation(api, ctx["reservation_id"])["status"] == \
        ReservationStatus.CONSUMED.value
    assert_slot_occupancy(read_slot_line(api, ctx["slot_line_id"]), reserved=1,
                          available=1, total=2)


def test_a_held_pre_construction_trip_does_not_open_the_certification_endpoint(
        api, admin_headers):
    """The gate names one trip type and one trip state, and neither is satisfied.

    PRD 3.9: "An inspection trip of that unit with `trip_type`
    `MID_CONSTRUCTION` and `status` `HELD` must exist, or the submission is refused
    with `ERR_MID_CON_INSPECTION_NOT_HELD` — the standards house does not test a
    body the committee has not yet walked."
    PRD 2.9: "The first rule that fails determines the response, nothing is
    persisted, and no lower rung is consulted."

    Design: Difficulty/cross_entity_state_dependency/certification_test_gated_on_mid_construction_trip_state
    """
    ctx = _in_production_unit_with_a_scheduled_mid_trip(api)
    assert read_trip(api, ctx["pre_trip_id"])["status"] == TripStatus.HELD.value
    assert read_trip(api, ctx["mid_trip_id"])["status"] == TripStatus.SCHEDULED.value

    validate_error(
        api.create_certification_test(
            {"unit_order_id": ctx["unit_id"], "test_standard": "NFPA_1901"},
            make_third_party_tester_headers(),
        ),
        ErrorCode.ERR_MID_CON_INSPECTION_NOT_HELD,
        409,
    )

    rows, meta = validate_paginated(
        api.list_certification_tests(admin_headers,
                                     {"unit_order_id": ctx["unit_id"]})
    )
    assert rows == [], rows
    assert_list_meta(meta, total_count=0, has_more=False)
    assert_unit_dimensions(
        read_unit(api, ctx["unit_id"]),
        build_status=BuildStatus.IN_PRODUCTION.value,
        certification_status=CertificationStatus.NOT_SUBMITTED.value)


def test_holding_the_mid_construction_trip_opens_it_and_the_standard_must_match(
        api, admin_headers):
    """The same submission is admitted once the committee has walked the body.

    PRD 3.9: "the standard must match the vehicle family: a `PUMPER` is tested
    against `NFPA_1901`, an `AERIAL` against `NFPA_1911`, and an `AMBULANCE`
    against either `NFPA_1917` or `AMD_STD_003`; any other pairing is refused with
    `ERR_TEST_STANDARD_MISMATCH`."
    PRD 3.7: "A `MID_CONSTRUCTION` trip held against a unit whose `build_status`
    is `IN_PRODUCTION` moves that unit `IN_PRODUCTION` to `MID_CON_HELD` and
    increments the unit's `version`."
    PRD 3.9: "The unit's `certification_status` must be `NOT_SUBMITTED` or
    `REJECTED_TESTING`, the two states from which a fresh test is meaningful".

    Design: Difficulty/cross_entity_state_dependency/certification_test_gated_on_mid_construction_trip_state
    """
    ctx = _in_production_unit_with_a_scheduled_mid_trip(api)
    admin = make_program_admin_headers()

    held = validate_success(api.hold_inspection_trip(ctx["mid_trip_id"], admin))
    assert held["status"] == TripStatus.HELD.value, held
    assert_unit_dimensions(read_unit(api, ctx["unit_id"]),
                           build_status=BuildStatus.MID_CON_HELD.value)

    validate_error(
        api.create_certification_test(
            {"unit_order_id": ctx["unit_id"], "test_standard": "NFPA_1917"},
            make_third_party_tester_headers(),
        ),
        ErrorCode.ERR_TEST_STANDARD_MISMATCH,
        422,
    )

    submitted = validate_success(
        api.create_certification_test(
            {"unit_order_id": ctx["unit_id"], "test_standard": "NFPA_1901"},
            make_third_party_tester_headers(),
        ),
        201,
    )
    assert submitted["status"] == CertificationTestStatus.SUBMITTED.value, submitted
    assert submitted["test_standard"] == "NFPA_1901", submitted
    assert_unit_dimensions(
        read_unit(api, ctx["unit_id"]),
        certification_status=CertificationStatus.IN_TESTING.value)
    assert_program_ledger(read_program(api, ctx["program_id"]), 68_276_000,
                          ProgramStatus.ACTIVE.value, None)
