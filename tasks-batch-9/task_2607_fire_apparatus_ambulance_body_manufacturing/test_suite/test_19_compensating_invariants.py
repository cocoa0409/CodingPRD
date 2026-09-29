"""Two exact reversals, and the deliberate residue each one leaves behind.

Rescinding an approved change order returns the money and the kilograms with
zero drift while leaving the torn-up certificate and the reverted build exactly
where the approval left them; releasing a reservation returns the supplier
line's occupied slot count and, one hop further on, the bay's visitor pool.
"""

from test_helpers import (
    BuildStatus,
    CertificationStatus,
    CertificationTestStatus,
    ChangeOrderStatus,
    ErrorCode,
    InvalidatedReason,
    LongLeadStatus,
    ProgramStatus,
    ReservationStatus,
    TripStatus,
    WeightStatus,
    approve_change_order,
    assert_axle_loads,
    assert_program_ledger,
    assert_slot_occupancy,
    assert_unit_dimensions,
    assert_unit_money,
    build_line_item,
    confirm_reservation,
    create_plant_bay,
    create_slot_line,
    make_purchasing_officer_headers,
    raise_change_order,
    read_certification_test,
    read_change_order,
    read_program,
    read_reservation,
    read_slot_line,
    read_trip,
    read_unit,
    release_reservation,
    rescind_change_order,
    reserve_slot,
    schedule_trip,
    setup_awarded_unit,
    setup_unit_at_stage,
    submit_change_order,
    validate_error,
    validate_success,
)


PUMP_CLAUSE = [
    {"clause_code": "C1", "category": "PUMP",
     "requirement_text": "1500 gpm single stage pump",
     "mandatory": True, "is_restrictive": False},
]


def _approved_one_kilogram_amendment(api):
    """Cascade A run to completion: money up 500,000, rear axle up one kilogram.

    The pumper's rear load sits exactly on its 10,110 kg rating before the
    approval, so the single approved kilogram is what makes it ``OVER_REAR`` and
    drags the certificate, the build dimension and the FINAL trip down with it.
    """
    ctx = setup_unit_at_stage(
        api, "FINAL_INSPECTED",
        program_overrides={"name": "Compensation program",
                           "agency_name": "Ashland Fire",
                           "max_option_units": 1},
        clauses=PUMP_CLAUSE,
        bay_overrides={"name": "Bay A", "max_concurrent_visitors": 12},
        pre_trip_overrides={"scheduled_start": "2026-08-10T08:00:00Z",
                            "scheduled_end": "2026-08-10T16:00:00Z"},
        slot_line_overrides={"supplier_name": "Freightline Custom Chassis",
                             "total_slot_count": 2},
    )
    final_trip = schedule_trip(api, ctx["unit_id"], ctx["bay_id"],
                               trip_type="FINAL",
                               scheduled_start="2026-10-05T08:00:00Z",
                               scheduled_end="2026-10-05T16:00:00Z",
                               committee_size=4)
    ctx["final_trip_id"] = final_trip["id"]
    change_order = raise_change_order(
        api, ctx["unit_id"], ctx["mid_trip_id"], ctx["program_id"],
        line_items=[build_line_item(description="Rear ladder rack", quantity=1,
                                    unit_cost_cents=500_000, markup_pct=0.0,
                                    is_taxable=False)],
        weight_delta_front_kg=0, weight_delta_rear_kg=1,
    )
    submit_change_order(api, change_order["id"], ctx["program_id"])
    ctx["change_order_id"] = change_order["id"]
    ctx["approved"] = approve_change_order(api, change_order["id"],
                                          officer="po-releaser")
    return ctx


def _confirmed_single_slot_and_a_full_bay(api):
    """One slot on a one-slot line, and a bay with eight of ten seats taken."""
    ctx = setup_awarded_unit(
        api,
        program_overrides={"name": "Conservation program",
                           "agency_name": "Millbrook Fire",
                           "max_option_units": 1},
        clauses=PUMP_CLAUSE,
    )
    line = create_slot_line(api, supplier_name="Freightline Custom Chassis",
                            component_type="CHASSIS", total_slot_count=1)
    reservation = reserve_slot(api, ctx["program_id"], line["id"],
                              unit_order_id=ctx["unit_id"])
    confirm_reservation(api, reservation["id"])
    bay = create_plant_bay(api, name="Bay D", max_concurrent_visitors=10)
    pre_trip = schedule_trip(api, ctx["unit_id"], bay["id"],
                             trip_type="PRE_CONSTRUCTION",
                             scheduled_start="2026-08-10T08:00:00Z",
                             scheduled_end="2026-08-10T16:00:00Z",
                             committee_size=8)
    ctx["slot_line_id"] = line["id"]
    ctx["reservation_id"] = reservation["id"]
    ctx["bay_id"] = bay["id"]
    ctx["pre_trip_id"] = pre_trip["id"]
    return ctx


def _crowding_trip(ctx):
    return {"unit_order_id": ctx["unit_id"], "plant_bay_id": ctx["bay_id"],
            "trip_type": "MID_CONSTRUCTION",
            "scheduled_start": "2026-08-10T09:00:00Z",
            "scheduled_end": "2026-08-10T11:00:00Z",
            "committee_size": 5}


def test_rescission_returns_the_money_and_the_kilograms_with_no_drift(api,
                                                                     admin_headers):
    """Both conserved quantities land back on their exact pre-approval values.

    PRD 3.8: "Rescission is designed to be an exact reversal of the fiscal and
    physical effects of the approval. The unit's `change_order_total_cents` is
    rebuilt over the *remaining* approved change orders and the axle loads are
    re-run over the *remaining* approved weight deltas, so both the money and the
    axle loads return precisely to their pre-approval values — the rescinded change
    order simply leaves the input set of both aggregations. The unit's frozen
    `price_cents` is untouched, because the award price is fixed for the life of the
    unit and was never part of what the change order moved. `approved_by_user_id` is
    cleared to null and `applied_at` is cleared to null. The program's
    `committed_cents` is recomputed back to exactly its pre-approval value."
    PRD 3.5: "Change orders that are `DRAFT`, `SUBMITTED`, `IN_NEGOTIATION`,
    `REJECTED` or `RESCINDED` contribute nothing, which is exactly what makes
    rescission an exact reversal."

    Design: Difficulty/compensating_invariant/rescind_restores_money_and_axle_loads_without_undoing_state_hops
    """
    ctx = _approved_one_kilogram_amendment(api)
    assert_unit_money(read_unit(api, ctx["unit_id"]),
                      change_order_total_cents=500_000)
    assert_program_ledger(read_program(api, ctx["program_id"]), 68_776_000,
                          ProgramStatus.ACTIVE.value, None)

    rescinded = rescind_change_order(api, ctx["change_order_id"],
                                     officer="po-releaser")
    assert rescinded["status"] == ChangeOrderStatus.RESCINDED.value, rescinded
    assert rescinded["approved_by_user_id"] is None, rescinded
    assert rescinded["applied_at"] is None, rescinded

    unit = read_unit(api, ctx["unit_id"])
    assert_unit_money(unit, price_cents=68_276_000, change_order_total_cents=0,
                      open_change_order_count=0)
    assert_axle_loads(unit, front_kg=5_810, rear_kg=10_110, gross_kg=15_920,
                      weight_status=WeightStatus.WITHIN_LIMITS.value)
    assert_program_ledger(read_program(api, ctx["program_id"]), 68_276_000,
                          ProgramStatus.ACTIVE.value, None)


def test_the_torn_up_certificate_and_the_reverted_build_are_not_given_back(
        api, admin_headers):
    """Certification has to be re-earned, and the compensation is single-shot.

    PRD 2.8: "What is *not* compensated is certification: a certificate torn up by
    Cascade A stays torn up when the change order that tore it up is rescinded, and
    the build dimension is not pushed forward again either. Certification has to be
    re-earned."
    PRD 2.9 rung 19: "The change order is in the state its transition allows —
    `DRAFT` to submit, `SUBMITTED` to negotiate, `IN_NEGOTIATION` to revise,
    `SUBMITTED` to approve, `SUBMITTED` to reject and `APPROVED` to rescind —
    otherwise `ERR_INVALID_CHANGE_ORDER_STATE`, 409."

    Design: Difficulty/compensating_invariant/rescind_restores_money_and_axle_loads_without_undoing_state_hops
    """
    ctx = _approved_one_kilogram_amendment(api)
    rescind_change_order(api, ctx["change_order_id"], officer="po-releaser")

    assert_unit_dimensions(
        read_unit(api, ctx["unit_id"]),
        build_status=BuildStatus.IN_PRODUCTION.value,
        certification_status=CertificationStatus.NOT_SUBMITTED.value)
    torn_up = read_certification_test(api, ctx["certification_test_id"])
    assert torn_up["status"] == CertificationTestStatus.INVALIDATED.value, torn_up
    assert torn_up["invalidated_reason"] == \
        InvalidatedReason.WEIGHT_STATUS_CHANGE.value, torn_up
    assert read_trip(api, ctx["final_trip_id"])["status"] == \
        TripStatus.CANCELLED.value

    validate_error(
        api.rescind_change_order(ctx["change_order_id"],
                                 make_purchasing_officer_headers("po-releaser")),
        ErrorCode.ERR_INVALID_CHANGE_ORDER_STATE,
        409,
    )
    assert read_change_order(api, ctx["change_order_id"])["status"] == \
        ChangeOrderStatus.RESCINDED.value
    assert_program_ledger(read_program(api, ctx["program_id"]), 68_276_000,
                          ProgramStatus.ACTIVE.value, None)


def test_releasing_the_slot_hands_the_committee_seats_back_to_the_bay(api,
                                                                     admin_headers):
    """A trip refused for capacity is admitted once hop three cancels its rival.

    PRD 3.6: "The second hop is caused by that freed slot: if the reservation named
    a `unit_order_id` and that unit's `build_status` is either `SPEC_LOCKED` or
    `PRE_CON_HELD`, the unit's `chassis_reservation_id` is cleared to null and its
    `long_lead_status` becomes `AT_RISK`. The third hop is caused by the unit going
    at risk: every inspection trip for that unit whose `trip_type` is
    `PRE_CONSTRUCTION` and whose `status` is `SCHEDULED` moves `SCHEDULED` to
    `CANCELLED`, processed in ascending `created_at` order, releasing each trip's
    `committee_size` from its bay's aggregate occupancy."
    PRD 3.7: "`CANCELLED` trips are excluded from the sum, which is precisely why
    cancelling a trip frees capacity for a later booking."

    Design: Difficulty/compensating_invariant/reservation_release_conserves_slot_count_and_frees_bay_capacity
    """
    ctx = _confirmed_single_slot_and_a_full_bay(api)

    validate_error(
        api.create_inspection_trip(_crowding_trip(ctx), admin_headers),
        ErrorCode.ERR_BAY_CAPACITY_EXCEEDED,
        409,
    )

    released = release_reservation(api, ctx["reservation_id"])
    assert released["status"] == ReservationStatus.RELEASED.value, released

    unit = read_unit(api, ctx["unit_id"])
    assert_unit_dimensions(unit, build_status=BuildStatus.SPEC_LOCKED.value,
                           long_lead_status=LongLeadStatus.AT_RISK.value)
    assert unit["chassis_reservation_id"] is None, unit
    assert read_trip(api, ctx["pre_trip_id"])["status"] == \
        TripStatus.CANCELLED.value

    admitted = validate_success(
        api.create_inspection_trip(_crowding_trip(ctx), admin_headers), 201
    )
    assert admitted["status"] == TripStatus.SCHEDULED.value, admitted
    assert admitted["committee_size"] == 5, admitted


def test_release_returns_the_slot_count_and_leaves_the_window_free_of_buffer(
        api, admin_headers):
    """Reserve then release restores the line, and the same window rebooks at once.

    PRD 3.6: "The first hop rebuilds the line's `reserved_slot_count` and
    `available_slot_count` and increments the line's `version` — the slot is
    genuinely back on the market."
    PRD 3.6: "A `RELEASED` or `EXPIRED` reservation leaves the occupied set
    entirely, which is what makes release and expiry exactly compensating against a
    booking."
    PRD 3.6: "`RELEASED` and `EXPIRED` reservations impose no buffer at all."
    PRD 3.6: "When the booking named a `unit_order_id`, that unit's
    `chassis_reservation_id` is set to point at the new reservation and its
    `long_lead_status` moves from `NOT_RESERVED` to `RESERVED`."
    PRD 3.9: "A unit whose slot was released or expired out from under it — and
    which therefore sits at `long_lead_status` of `AT_RISK` with a null
    `chassis_reservation_id` — cannot start production until a fresh reservation has
    been booked and confirmed for it."

    Design: Difficulty/compensating_invariant/reservation_release_conserves_slot_count_and_frees_bay_capacity
    """
    ctx = _confirmed_single_slot_and_a_full_bay(api)
    assert_slot_occupancy(read_slot_line(api, ctx["slot_line_id"]), reserved=1,
                          available=0, total=1)

    release_reservation(api, ctx["reservation_id"])
    freed = read_slot_line(api, ctx["slot_line_id"])
    assert_slot_occupancy(freed, reserved=0, available=1, total=1)

    rebooked = reserve_slot(api, ctx["program_id"], ctx["slot_line_id"],
                            unit_order_id=ctx["unit_id"],
                            slot_start_date="2026-09-01T00:00:00Z",
                            slot_end_date="2026-09-15T00:00:00Z")
    assert rebooked["status"] == ReservationStatus.RESERVED.value, rebooked
    assert rebooked["id"] != ctx["reservation_id"], rebooked
    assert read_reservation(api, ctx["reservation_id"])["status"] == \
        ReservationStatus.RELEASED.value

    assert_slot_occupancy(read_slot_line(api, ctx["slot_line_id"]), reserved=1,
                          available=0, total=1)
    unit = read_unit(api, ctx["unit_id"])
    assert_unit_dimensions(unit, long_lead_status=LongLeadStatus.RESERVED.value)
    assert unit["chassis_reservation_id"] == rebooked["id"], unit
    assert_program_ledger(read_program(api, ctx["program_id"]), 68_276_000,
                          ProgramStatus.ACTIVE.value, None)
