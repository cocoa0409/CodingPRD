"""Optimistic concurrency on the slot line and the strict soft-ceiling boundary.

Covers the slot line version counter that advances on every capacity-changing
write — booking, release and consumption alike — and the auto-suspension that a
single cent past ninety percent of the hard ceiling triggers inside the very
request that crosses it.
"""

from test_helpers import (
    assert_clock_stamp,
    ChangeOrderStatus,
    ErrorCode,
    ProgramStatus,
    ReservationStatus,
    SuspensionReason,
    approve_change_order,
    assert_program_ledger,
    assert_slot_occupancy,
    assert_unit_money,
    award_unit,
    build_line_item,
    build_reservation_payload,
    create_active_program,
    create_plant_bay,
    create_released_specification,
    create_slot_line,
    hold_trip,
    raise_change_order,
    read_program,
    read_reservation,
    read_slot_line,
    read_unit,
    reserve_slot,
    schedule_trip,
    soft_ceiling,
    submit_change_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_booking_a_retry_and_a_release_each_advance_the_slot_line_version(api,
                                                                           admin_headers):
    """Two stale bookings are refused 412; each fresh read admits the next one.

    PRD 2.7: "If that value does not equal the slot line's current `version`, the
    request is rejected with `ERR_STALE_SLOT_LINE_VERSION` and HTTP 412, and
    nothing is persisted. Long-lead holds are booked against an observed
    free-slot picture; once another reservation, release or expiry has changed
    that picture, the booking decision rests on capacity the client never
    observed, and the hold is refused."
    PRD 3.6: "A successful booking lands the reservation in `RESERVED` with
    `confirmed_at` at null, rebuilds the line's `reserved_slot_count` and
    `available_slot_count`, and increments the line's `version`."
    PRD 3.6: "The first hop rebuilds the line's `reserved_slot_count` and
    `available_slot_count` and increments the line's `version` — the slot is
    genuinely back on the market."

    Design: Corner/complexity_layers/slot_line_optimistic_concurrency_rejects_stale_capacity_reads
    """
    program = create_active_program(api, name="Concurrency program")
    line = create_slot_line(api, supplier_name="Freightline Custom Chassis",
                            component_type="CHASSIS", total_slot_count=3)
    assert line["version"] == 1, line
    assert_slot_occupancy(line, reserved=0, available=3, total=3)

    first = reserve_slot(api, program["id"], line["id"],
                         expected_slot_line_version=1)
    assert first["status"] == ReservationStatus.RESERVED.value, first

    october = {"slot_start_date": "2026-10-01T00:00:00Z",
               "slot_end_date": "2026-10-15T00:00:00Z"}
    validate_error(
        api.create_chassis_reservation(
            build_reservation_payload(program["id"], line["id"], 1, **october),
            admin_headers,
        ),
        ErrorCode.ERR_STALE_SLOT_LINE_VERSION,
        412,
    )
    after_first = read_slot_line(api, line["id"])
    assert after_first["version"] == 2, after_first
    assert_slot_occupancy(after_first, reserved=1, available=2, total=3)

    second = reserve_slot(api, program["id"], line["id"],
                          expected_slot_line_version=2, **october)
    assert second["status"] == ReservationStatus.RESERVED.value, second
    after_second = read_slot_line(api, line["id"])
    assert after_second["version"] == 3, after_second

    validate_success(api.release_chassis_reservation(first["id"], admin_headers))

    november = {"slot_start_date": "2026-11-01T00:00:00Z",
                "slot_end_date": "2026-11-15T00:00:00Z"}
    validate_error(
        api.create_chassis_reservation(
            build_reservation_payload(program["id"], line["id"], 2, **november),
            admin_headers,
        ),
        ErrorCode.ERR_STALE_SLOT_LINE_VERSION,
        412,
    )
    after_release = read_slot_line(api, line["id"])
    assert after_release["version"] == 4, after_release
    assert_slot_occupancy(after_release, reserved=1, available=2, total=3)

    third = reserve_slot(api, program["id"], line["id"],
                         expected_slot_line_version=4, **november)
    assert third["status"] == ReservationStatus.RESERVED.value, third

    final_line = read_slot_line(api, line["id"])
    assert final_line["version"] == 5, final_line
    assert_slot_occupancy(final_line, reserved=2, available=1, total=3)
    assert read_reservation(api, first["id"])["status"] == \
        ReservationStatus.RELEASED.value

    rows, meta = validate_paginated(
        api.list_chassis_reservations(admin_headers, {"slot_line_id": line["id"]})
    )
    assert meta["total_count"] == 3, meta
    assert {row["id"] for row in rows} == {first["id"], second["id"], third["id"]}


def test_committed_money_exactly_on_the_soft_ceiling_survives_but_one_cent_does_not(
        api, admin_headers):
    """The soft-ceiling comparison is strict, and the crossing write still succeeds.

    PRD 2.10: "The **soft ceiling** is ninety percent of the hard ceiling, computed
    by taking the hard ceiling, multiplying by 90, dividing by 100 and quantising
    the result to whole cents with round-half-up. A write whose resulting
    `committed_cents` strictly exceeds the soft ceiling while remaining at or
    below the hard ceiling *succeeds*, and the program is automatically moved
    from `ACTIVE` to `SUSPENDED` inside that very same request with
    `suspension_reason` set to `SOFT_CEILING_BREACH`. Committed money landing
    exactly on the soft ceiling is not a breach; the comparison is strict."
    PRD 3.8: "On success the change order moves `SUBMITTED` to `APPROVED`,
    records `approved_by_user_id` as the approving officer's `X-User-ID` and
    stamps `applied_at` with the current logical clock."

    Design: Corner/complexity_layers/soft_ceiling_auto_suspension_is_strict_at_the_exact_boundary
    """
    program = create_active_program(api, name="Boundary program",
                                    contract_ceiling_cents=75_862_222)
    assert soft_ceiling(75_862_222) == 68_276_000
    spec = create_released_specification(api, program["id"], title="Boundary spec")
    bay = create_plant_bay(api, name="Bay A", max_concurrent_visitors=10)

    unit = award_unit(api, program["id"], spec["specification_id"])
    assert_unit_money(unit, price_cents=68_276_000)
    at_boundary = read_program(api, program["id"])
    assert_program_ledger(at_boundary, 68_276_000, ProgramStatus.ACTIVE.value, None)

    trip = schedule_trip(api, unit["id"], bay["id"], trip_type="PRE_CONSTRUCTION",
                         scheduled_start="2026-08-10T08:00:00Z",
                         scheduled_end="2026-08-10T16:00:00Z", committee_size=4)
    hold_trip(api, trip["id"])

    change_order = raise_change_order(
        api, unit["id"], trip["id"], program["id"],
        line_items=[build_line_item(description="One cent documentation fee",
                                    quantity=1, unit_cost_cents=1, markup_pct=0.0,
                                    is_taxable=False)],
    )
    assert change_order["price_delta_cents"] == 1, change_order
    submit_change_order(api, change_order["id"], program["id"])

    approved = approve_change_order(api, change_order["id"], officer="po-releaser")
    assert approved["status"] == ChangeOrderStatus.APPROVED.value, approved
    assert approved["approved_by_user_id"] == "po-releaser", approved
    assert_clock_stamp(approved["applied_at"], "2026-08-01T00:00:00Z")

    assert_unit_money(read_unit(api, unit["id"]), price_cents=68_276_000,
                      change_order_total_cents=1, open_change_order_count=0)
    assert_program_ledger(read_program(api, program["id"]), 68_276_001,
                          ProgramStatus.SUSPENDED.value,
                          SuspensionReason.SOFT_CEILING_BREACH.value)
