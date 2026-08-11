"""Non-linear state machines: the Booking CONFIRMED<->WEATHER_HOLD cycle and
the Permit DENIED->SUBMITTED re-application loop (PRD §3.5, §3.7).
"""
from test_helpers import (
    validate_success,
    sum_of_type,
    fixtures as fx,
)


# =====================================================================
# Difficulty/non_linear_state_machine/booking_weather_hold_cycle
# =====================================================================
def test_weather_hold_release_cycle_traverseable_repeatedly(api):
    """PRD §3.7: "The hold moves the booking to `WEATHER_HOLD` and increments
    its `version`. Releasing the hold needs no justification at all: a
    coordinator may return a `WEATHER_HOLD` booking to `CONFIRMED`
    unconditionally, again incrementing the version. The two transitions form
    a cycle a booking can traverse repeatedly as forecasts evolve."

    Design: Difficulty/non_linear_state_machine/booking_weather_hold_cycle
    """
    ctx = fx.setup_confirmed_sheep_booking()
    booking_id = ctx["booking"]["id"]
    fx.set_clock("2026-06-16T10:00:00Z")

    wa1 = fx.create_assessment(booking_id, "2026-06-16T09:30:00Z")
    held = validate_success(api.weather_hold(booking_id, wa1["id"], fx.COORD))
    assert held["status"] == "WEATHER_HOLD", held["status"]

    released = validate_success(api.release_weather_hold(booking_id, fx.COORD))
    assert released["status"] == "CONFIRMED", released["status"]

    wa2 = fx.create_assessment(
        booking_id, "2026-06-16T09:45:00Z",
        forecast_temp_f=36, forecast_precip_pct=95, wind_mph=40,
    )
    held_again = validate_success(api.weather_hold(booking_id, wa2["id"], fx.COORD))
    # CONFIRMED -> WEATHER_HOLD -> CONFIRMED -> WEATHER_HOLD: the cycle twice
    assert held_again["status"] == "WEATHER_HOLD", held_again["status"]


def test_weather_hold_cycle_preserves_payment_status(api):
    """PRD §3.7: "The hold moves the booking to `WEATHER_HOLD` and increments
    its `version`. Releasing the hold needs no justification at all: a
    coordinator may return a `WEATHER_HOLD` booking to `CONFIRMED`
    unconditionally, again incrementing the version."
    PRD §3.6: "Each accepted payment appends a `PAYMENT` ledger entry,
    recomputes `total_paid_cents`, and advances `payment_status`"

    Design: Difficulty/non_linear_state_machine/booking_weather_hold_cycle
    """
    ctx = fx.setup_confirmed_sheep_booking()
    booking_id = ctx["booking"]["id"]
    assert ctx["confirmed"]["payment_status"] == "DEPOSIT_PAID"

    fx.set_clock("2026-06-16T10:00:00Z")
    wa1 = fx.create_assessment(booking_id, "2026-06-16T09:30:00Z")
    held = validate_success(api.weather_hold(booking_id, wa1["id"], fx.COORD))
    assert held["payment_status"] == "DEPOSIT_PAID", held["payment_status"]

    released = validate_success(api.release_weather_hold(booking_id, fx.COORD))
    assert released["payment_status"] == "DEPOSIT_PAID", released["payment_status"]
    # The only money that ever moved is the 5181 deposit.
    assert sum_of_type(fx.list_ledger(booking_id), "PAYMENT") == 5181


# =====================================================================
# Difficulty/non_linear_state_machine/permit_denial_resubmission_cycle
# =====================================================================
def _setup_booking_with_draft_permit():
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer()
    venue = fx.create_venue(
        customer["id"], name="County Fairground", address="4 Fair Rd",
        distance_miles=15, max_guest_capacity=300, requires_animal_permit=True,
    )
    booking = fx.create_booking(
        customer["id"], venue["id"],
        start_time="2026-06-06T14:00:00Z", end_time="2026-06-06T16:00:00Z",
        guest_count=10, child_guest_count=0, planned_handwash_stations=1,
    )
    permit = fx.create_permit(booking["id"])
    return customer, booking, permit


def test_permit_denial_records_reason_and_resubmission_clears_it(api):
    """PRD §3.5: "Denial records a `denial_reason` and feeds a re-application
    loop: a `DENIED` permit may be submitted again (subject to the same
    336-hour lead time), which clears its `denial_reason` back to null and
    refreshes `submitted_by_user_id`, cycling `DENIED` back to `SUBMITTED` and
    onward to a fresh decision."

    Design: Difficulty/non_linear_state_machine/permit_denial_resubmission_cycle
    """
    _, _, permit = _setup_booking_with_draft_permit()

    submitted = fx.submit_permit(permit["id"], "coord-1")
    assert submitted["status"] == "SUBMITTED", submitted["status"]

    denied = fx.decide_permit(permit["id"], "DENIED", "officer-1",
                              denial_reason="incomplete application")
    assert denied["status"] == "DENIED", denied["status"]
    assert denied["denial_reason"] == "incomplete application"

    resubmitted = fx.submit_permit(permit["id"], "coord-1")
    assert resubmitted["status"] == "SUBMITTED", resubmitted["status"]
    assert resubmitted["denial_reason"] is None, resubmitted["denial_reason"]


def test_permit_cycle_completes_to_issued_with_operator_ids_recorded(api):
    """PRD §3.5: "Submitting a permit moves it from `DRAFT` to `SUBMITTED` and
    records the submitter's `X-User-ID` as `submitted_by_user_id`."
    PRD §3.5: "A `ComplianceOfficer` decides a `SUBMITTED` permit with a
    `decision` of `ISSUED` or `DENIED`, and the server records the decider's
    `X-User-ID` as `decided_by_user_id`."

    Design: Difficulty/non_linear_state_machine/permit_denial_resubmission_cycle
    """
    _, _, permit = _setup_booking_with_draft_permit()

    fx.submit_permit(permit["id"], "coord-1")
    fx.decide_permit(permit["id"], "DENIED", "officer-1",
                     denial_reason="incomplete application")
    resubmitted = fx.submit_permit(permit["id"], "coord-1")
    assert resubmitted["submitted_by_user_id"] == "coord-1"

    issued = fx.decide_permit(permit["id"], "ISSUED", "officer-1")
    # Full cycle: DRAFT -> SUBMITTED -> DENIED -> SUBMITTED -> ISSUED
    assert issued["status"] == "ISSUED", issued["status"]
    assert issued["submitted_by_user_id"] == "coord-1"
    assert issued["decided_by_user_id"] == "officer-1"
