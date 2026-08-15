"""Trip execution: dispatch idempotency, check-call rank discipline, the
DELIVERED completion cascade, detention measurement, driver pay variants, and
ETA projection (PRD §3.3, §3.5)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    api_client,
    complete_trip,
    dispatch_trip,
    get_load,
    get_tractor,
    get_trip,
    make_dispatcher_headers,
    post_check_call,
    set_clock,
    setup_delivered_trip,
    setup_delivered_trip_no_detention,
    setup_dispatched_trip,
    setup_planned_trip,
    validate_error,
    validate_paginated,
    validate_success,
)

DISPATCHER = make_dispatcher_headers()


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(
        timezone.utc)


def test_second_dispatch_rejected(api):
    """PRD §3.3: "A `Dispatcher` may dispatch only a `PLANNED` trip (otherwise
    `ERR_TRIP_NOT_PLANNED`) whose load still stands at `ASSIGNED` (otherwise
    `ERR_LOAD_NOT_ASSIGNABLE`) and whose driver is `ACTIVE` (otherwise
    `ERR_DRIVER_NOT_ACTIVE`). At dispatch, the tractor's current
    `odometer_miles` is frozen into the trip's `start_odometer_miles` — the
    baseline every later odometer report is measured against — the trip
    advances from `PLANNED` to `DISPATCHED`, and the load moves from
    `ASSIGNED` to `DISPATCHED` with it."

    Design: Corner/state_machines/trip_redispatch_rejected
    """
    ctx = setup_planned_trip(cdl_number="CDL-C15", unit_number="T-C15")
    dispatched = dispatch_trip(ctx["trip"]["id"])
    assert dispatched["status"] == "DISPATCHED"
    assert get_load(ctx["load"]["id"])["status"] == "DISPATCHED"
    resp = api_client.dispatch_trip(ctx["trip"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_PLANNED)


def test_cancel_completed_trip_rejected(api):
    """PRD §3.3: "A `Dispatcher` may cancel a trip in `PLANNED`, `DISPATCHED`,
    or `AT_PICKUP`; from `IN_TRANSIT`, `AT_DELIVERY`, or any terminal state the
    attempt is rejected with `ERR_TRIP_NOT_CANCELLABLE`."

    Design: Corner/state_machines/trip_cancel_completed_rejected
    """
    ctx = setup_delivered_trip_no_detention(cdl_number="CDL-C16",
                                            unit_number="T-C16")
    assert ctx["trip"]["status"] == "COMPLETED"
    resp = api_client.cancel_trip(ctx["trip"]["id"], {}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_CANCELLABLE)


def test_check_call_rank_regression_rejected_en_route_legal(api):
    """PRD §3.5: "`EN_ROUTE` reports carry no rank and may be interleaved while
    the trip is `DISPATCHED` or `IN_TRANSIT` without disturbing the sequence".
    PRD §3.5: "The same 422 rejection meets a kind that regresses the milestone
    rank, an `odometer_miles` below the previous report's reading, a first
    report whose odometer reads below the trip's `start_odometer_miles`, and
    any check call at all against a `PLANNED` or terminal trip."

    Design: Corner/state_machines/check_call_rank_regression_and_en_route_legality
    """
    ctx = setup_dispatched_trip(cdl_number="CDL-C24", unit_number="T-C24")
    set_clock("2026-08-02T12:00:00Z")
    en_route = post_check_call(ctx["trip"]["id"], ctx["driver"]["id"],
                               kind="EN_ROUTE",
                               occurred_at="2026-08-02T09:00:00Z",
                               state_code="TX", odometer_miles=100050)
    assert en_route["kind"] == "EN_ROUTE"
    post_check_call(ctx["trip"]["id"], ctx["driver"]["id"],
                    kind="ARRIVED_PICKUP", occurred_at="2026-08-02T10:00:00Z",
                    state_code="TX", odometer_miles=100120)
    resp = api_client.create_trip_check_call(
        ctx["trip"]["id"],
        {"kind": "ARRIVED_PICKUP", "occurred_at": "2026-08-02T10:30:00Z",
         "state_code": "TX", "odometer_miles": 100120},
        {"X-User-ID": ctx["driver"]["id"], "X-User-Role": "Driver"})
    validate_error(resp, ApiErrorId.ERR_CHECK_CALL_OUT_OF_ORDER)


def test_detention_early_arrival_anchors_at_appointment(api):
    """PRD §3.5: "Each leg anchors at the later of its arrival report and its
    appointment: the pickup leg anchors at the later of the `ARRIVED_PICKUP`
    report's `occurred_at` and the load's `pickup_appt_at`, and the delivery
    leg anchors at the later of the `ARRIVED_DELIVERY` report and the
    `delivery_appt_at`."
    PRD §3.5: "the charge is the billable minutes divided into 15-minute
    increments, rounded up, at 1500 cents per increment."
    (Pickup: arrive 07:30 vs appointment 08:00 -> 130 elapsed from the
    appointment -> 10 billable -> 1500; an arrival-anchored reading would
    bill 40 -> 4500. Delivery: 30 elapsed from the 18:00 anchor -> 0.)

    Design: Corner/calculations/detention_early_arrival_anchors_at_appointment
    """
    ctx = setup_dispatched_trip(cdl_number="CDL-C28", unit_number="T-C28")
    complete_trip(ctx["trip"]["id"], ctx["driver"]["id"],
                  clock_to="2026-08-03T18:30:00Z",
                  arrive_pickup_at="2026-08-02T07:30:00Z",
                  depart_pickup_at="2026-08-02T10:10:00Z",
                  arrive_delivery_at="2026-08-03T17:30:00Z",
                  delivered_at="2026-08-03T18:30:00Z")
    rows, _ = validate_paginated(
        api_client.list_load_accessorials(ctx["load"]["id"], DISPATCHER))
    assert len(rows) == 1, "delivery leg inside free minutes creates nothing"
    charge = rows[0]
    assert charge["type"] == "DETENTION_PICKUP"
    assert charge["quantity"] == 10
    assert charge["amount_cents"] == 1500
    assert charge["source"] == "AUTO_DETENTION"


def test_eta_projection_adds_breaks_and_rests(api):
    """PRD §3.5: "Break time adds 30 minutes for every additional 480-minute
    driving block beyond the first — 30 multiplied by the rounded-down quotient
    of the driving minutes minus one, divided by 480 — so no break time accrues
    at or under 480 minutes of driving."
    PRD §3.5: "With check calls present, the projection base is the later of
    the logical now and the latest report's `occurred_at`. The projected
    `eta_at` is that base plus driving, break, and rest minutes, and the `late`
    flag is set only when `eta_at` falls strictly after the load's
    `delivery_appt_at` — arriving exactly at the appointment is not late."

    Design: Corner/calculations/eta_projection_adds_breaks_and_rests
    """
    ctx = setup_dispatched_trip(cdl_number="CDL-C32", unit_number="T-C32")
    set_clock("2026-08-02T20:00:00Z")
    post_check_call(ctx["trip"]["id"], ctx["driver"]["id"], kind="EN_ROUTE",
                    occurred_at="2026-08-02T18:00:00Z", state_code="LA",
                    odometer_miles=100500)
    eta = validate_success(
        api_client.get_trip_eta(ctx["trip"]["id"], DISPATCHER))
    assert eta["remaining_miles"] == 520
    assert eta["drive_minutes"] == 624
    assert eta["break_minutes"] == 30
    assert eta["rest_minutes"] == 0
    assert _parse(eta["eta_at"]) == _parse("2026-08-03T06:54:00Z")
    assert eta["late"] is False


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / delivered_check_call_four_hop_cascade
# ---------------------------------------------------------------------------

def test_delivered_check_call_completes_trip_and_load(api):
    """PRD §3.5: "The report's `occurred_at` becomes the trip's `completed_at`;
    `actual_miles` is the report's odometer minus the `start_odometer_miles`
    snapshot taken at dispatch; `pay_miles` is the greater of `actual_miles`
    and the planned total of lane `loaded_miles` plus
    `planned_deadhead_miles`."
    PRD §3.5: "Finally, the load moves from `IN_TRANSIT` to `DELIVERED`, which
    triggers detention evaluation."

    Design: Difficulty/transitive_cascade/delivered_check_call_four_hop_cascade
    """
    ctx = setup_delivered_trip(cdl_number="CDL-7", unit_number="T-7")
    trip = ctx["trip"]
    assert trip["status"] == "COMPLETED"
    assert trip["actual_miles"] == 1050
    assert trip["pay_miles"] == 1050, "max(1050, 900 + 120)"
    assert trip["final_pay_cents"] == 65100, "1050 * 62"
    assert trip["completed_at"].startswith("2026-08-03T21:00")
    assert ctx["load"]["status"] == "DELIVERED"


def test_delivered_check_call_creates_detention_and_releases_tractor(api):
    """PRD §3.5: "For each leg whose billable minutes exceed zero, an
    AccessorialCharge is created in `PENDING` status with `type`
    `DETENTION_PICKUP` or `DETENTION_DELIVERY` as the leg dictates, `quantity`
    set to the billable minutes, `amount_cents` per the increment formula,
    `source` `AUTO_DETENTION`, and `trip_id` bound to the completing trip."
    PRD §3.5: "The tractor is released from `ASSIGNED` back to `AVAILABLE`, its
    `odometer_miles` reset to the `DELIVERED` report's reading, its
    `current_state_code` reset to the report's `state_code`, and its
    `current_fuel_gallons` reduced by the trip's fuel burn — the `actual_miles`
    divided by 6.5 miles per gallon, rounded up to the next whole gallon — but
    never below zero."

    Design: Difficulty/transitive_cascade/delivered_check_call_four_hop_cascade
    """
    ctx = setup_delivered_trip(cdl_number="CDL-7", unit_number="T-7")
    rows, _ = validate_paginated(
        api_client.list_load_accessorials(ctx["load"]["id"], DISPATCHER))
    assert len(rows) == 1
    charge = rows[0]
    assert charge["type"] == "DETENTION_DELIVERY"
    assert charge["quantity"] == 60
    assert charge["amount_cents"] == 6000, "ceil(60/15) * 1500"
    assert charge["source"] == "AUTO_DETENTION"
    assert charge["status"] == "PENDING"
    assert charge["trip_id"] == ctx["trip"]["id"]

    tractor = get_tractor(ctx["tractor"]["id"])
    assert tractor["status"] == "AVAILABLE"
    assert tractor["odometer_miles"] == 101050
    assert tractor["current_state_code"] == "GA"
    assert tractor["current_fuel_gallons"] == 0, (
        "max(0, 150 - ceil(1050/6.5)) = max(0, -12)")


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / driver_pay_provisional_vs_final_percentage
# ---------------------------------------------------------------------------

def test_percentage_provisional_pay_linehaul_only(api):
    """PRD §3.3: "For a `PERCENTAGE` driver, it is the load's `rate_cents`
    multiplied by the driver's `pay_percentage_bp` and divided by 10000,
    rounded half up to whole cents — a linehaul-only base, since surcharges are
    not yet in it."
    (round_half_up(250001 * 2750 / 10000) = round_half_up(68750.275) = 68750.)

    Design: Difficulty/dual_variant_calc/driver_pay_provisional_vs_final_percentage
    """
    ctx = setup_planned_trip(rate_cents=250001, pay_model="PERCENTAGE",
                             pay_percentage_bp=2750, cdl_number="CDL-2",
                             unit_number="T-2")
    assert ctx["trip"]["provisional_pay_cents"] == 68750


def test_percentage_final_pay_adds_fsc_to_base(api):
    """PRD §3.5: "for a `PERCENTAGE` driver, the sum of the load's `rate_cents`
    and `fuel_surcharge_cents` multiplied by `pay_percentage_bp` and divided by
    10000, rounded half up to whole cents — so the final figure differs from
    the provisional one whenever actual miles exceed the plan or a surcharge
    exists."
    (round_half_up((250001 + 20769) * 2750 / 10000) = round_half_up(74461.75)
    = 74462.)

    Design: Difficulty/dual_variant_calc/driver_pay_provisional_vs_final_percentage
    """
    ctx = setup_dispatched_trip(rate_cents=250001, pay_model="PERCENTAGE",
                                pay_percentage_bp=2750, cdl_number="CDL-2",
                                unit_number="T-2")
    provisional = ctx["trip"]["provisional_pay_cents"]
    complete_trip(ctx["trip"]["id"], ctx["driver"]["id"],
                  clock_to="2026-08-03T19:00:00Z",
                  arrive_pickup_at="2026-08-02T08:00:00Z",
                  depart_pickup_at="2026-08-02T09:00:00Z",
                  arrive_delivery_at="2026-08-03T17:00:00Z",
                  delivered_at="2026-08-03T19:00:00Z",
                  odometer_delivery=101000)
    trip = get_trip(ctx["trip"]["id"])
    assert trip["final_pay_cents"] == 74462
    assert trip["final_pay_cents"] != provisional == 68750


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / detention_free_minutes_exact_boundary
# ---------------------------------------------------------------------------

def _boundary_chain():
    """Pickup dwell exactly 120 free minutes; delivery dwell 181 elapsed."""
    ctx = setup_dispatched_trip(cdl_number="CDL-11", unit_number="T-12")
    # Delivery anchor 18:00 (= appointment); DELIVERED 21:01 -> 181 elapsed ->
    # 61 billable minutes. Clock at 21:01 keeps the DELIVERED call at-or-before
    # the logical now (PRD §3.4/§3.5 timestamp rule).
    complete_trip(ctx["trip"]["id"], ctx["driver"]["id"],
                  clock_to="2026-08-03T21:01:00Z",
                  arrive_pickup_at="2026-08-02T08:00:00Z",
                  depart_pickup_at="2026-08-02T10:00:00Z",
                  arrive_delivery_at="2026-08-03T18:00:00Z",
                  delivered_at="2026-08-03T21:01:00Z")
    return ctx


def test_detention_exactly_120_minutes_bills_nothing(api):
    """PRD §3.5: "Exactly 120 elapsed minutes produces nothing, while a single
    minute beyond the allowance produces one billable minute".
    (Pickup leg dwell is exactly 120 from the appointment anchor -> no
    DETENTION_PICKUP charge is created.)

    Design: Difficulty/boundary_precision_check/detention_free_minutes_exact_boundary
    """
    ctx = _boundary_chain()
    rows, _ = validate_paginated(
        api_client.list_load_accessorials(ctx["load"]["id"], DISPATCHER))
    types = [r["type"] for r in rows]
    assert "DETENTION_PICKUP" not in types, (
        "exactly 120 elapsed minutes must produce no pickup charge")
    assert len(rows) == 1


def test_detention_one_minute_past_free_allowance_bills(api):
    """PRD §3.5: "Exactly 120 elapsed minutes produces nothing, while a single
    minute beyond the allowance produces one billable minute, and the charge is
    the billable minutes divided into 15-minute increments, rounded up, at 1500
    cents per increment."
    (Delivery dwell 181 elapsed from the 18:00 anchor -> 61 billable ->
    ceil(61/15) * 1500 = 7500.)

    Design: Difficulty/boundary_precision_check/detention_free_minutes_exact_boundary
    """
    ctx = _boundary_chain()
    rows, _ = validate_paginated(
        api_client.list_load_accessorials(ctx["load"]["id"], DISPATCHER))
    assert len(rows) == 1
    charge = rows[0]
    assert charge["type"] == "DETENTION_DELIVERY"
    assert charge["quantity"] == 61
    assert charge["amount_cents"] == 7500
