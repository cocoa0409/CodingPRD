"""Permit lead-time and segregation-of-duties rejections, weather-hold
justification and freshness rejections, and the two optimistic-concurrency
rules on Booking.version (PRD §2.6, §3.5, §3.7).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    fixtures as fx,
)
from test_helpers.test_users import (
    make_customer_headers, make_coordinator_headers,
    make_compliance_officer_headers,
)


def _setup_booking_with_permit():
    """Customer + permit-requiring venue + booking 2026-06-06 14:00-16:00 +
    ANIMAL_EXHIBITION permit in DRAFT (clock 2026-05-10)."""
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


# =====================================================================
# Corner/validations/permit_submit_lead_time_rejected
# =====================================================================
def test_permit_submit_lead_time_rejected(api):
    """PRD §3.5: "The filing system demands lead time: submission is allowed
    only when the event's `start_time` is at least 336 hours — fourteen full
    days — after now; filing later is rejected with `ERR_PERMIT_LEAD_TIME`."

    Design: Corner/validations/permit_submit_lead_time_rejected
    """
    _, _, permit = _setup_booking_with_permit()
    fx.set_clock("2026-06-01T00:00:00Z")  # 134h remain < 336h required
    resp = api.submit_permit(permit["id"], fx.COORD)
    validate_error(resp, ApiErrorId.ERR_PERMIT_LEAD_TIME)


# =====================================================================
# Corner/validations/permit_decide_same_operator_rejected
# =====================================================================
def test_permit_decide_same_operator_rejected(api):
    """PRD §3.5: "Segregation of duties is enforced mechanically: the
    decider's `X-User-ID` must differ from the permit's
    `submitted_by_user_id`, and a match is rejected with
    `ERR_SEGREGATION_OF_DUTY` (HTTP 403)."

    Design: Corner/validations/permit_decide_same_operator_rejected
    """
    _, booking, permit = _setup_booking_with_permit()
    # Submitted under operator id ops-9.
    validate_success(api.submit_permit(permit["id"],
                                       make_coordinator_headers("ops-9")))
    # The same operator id cannot decide it, even with the decider role.
    resp = api.decide_permit(permit["id"], {"decision": "ISSUED"},
                             make_compliance_officer_headers("ops-9"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTY, expected_status=403)

    permits = get_success_data(api.list_permits(booking["id"], fx.COORD))
    assert permits[0]["status"] == "SUBMITTED", permits[0]["status"]


# =====================================================================
# Corner/validations/weather_hold_without_mandatory_verdict_rejected
# =====================================================================
def test_weather_hold_without_mandatory_verdict_rejected(api):
    """PRD §3.7: "Two checks justify the hold: the assessment's `assessed_at`
    must be no older than 24 hours before now (`ERR_ASSESSMENT_STALE`), and
    its `verdict` must be `MANDATORY_HOLD` — a mere recommendation is not
    enough (`ERR_WEATHER_HOLD_NOT_JUSTIFIED`)."

    Design: Corner/validations/weather_hold_without_mandatory_verdict_rejected
    """
    ctx = fx.setup_confirmed_goat_booking()
    booking_id = ctx["booking"]["id"]
    fx.set_clock("2026-06-16T10:00:00Z")
    # Fresh (30 minutes old) but the verdict is a clear-weather PROCEED.
    wa = fx.create_assessment(booking_id, "2026-06-16T09:30:00Z",
                              verdict="PROCEED", forecast_temp_f=72,
                              forecast_precip_pct=10, wind_mph=5)
    resp = api.weather_hold(booking_id, wa["id"], fx.COORD)
    validate_error(resp, ApiErrorId.ERR_WEATHER_HOLD_NOT_JUSTIFIED)
    assert fx.get_booking(booking_id)["status"] == "CONFIRMED"


# =====================================================================
# Corner/validations/weather_hold_with_stale_assessment_rejected
# =====================================================================
def test_weather_hold_with_stale_assessment_rejected(api):
    """PRD §3.7: "Two checks justify the hold: the assessment's `assessed_at`
    must be no older than 24 hours before now (`ERR_ASSESSMENT_STALE`), and
    its `verdict` must be `MANDATORY_HOLD` — a mere recommendation is not
    enough (`ERR_WEATHER_HOLD_NOT_JUSTIFIED`)."

    Design: Corner/validations/weather_hold_with_stale_assessment_rejected
    """
    ctx = fx.setup_confirmed_goat_booking()
    booking_id = ctx["booking"]["id"]
    fx.set_clock("2026-06-16T10:00:00Z")
    # MANDATORY_HOLD but taken 31h before the hold attempt: stale.
    wa = fx.create_assessment(booking_id, "2026-06-15T03:00:00Z")
    resp = api.weather_hold(booking_id, wa["id"], fx.COORD)
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_STALE)
    assert fx.get_booking(booking_id)["status"] == "CONFIRMED"


# =====================================================================
# Corner/cross_cutting_layers/reschedule_with_stale_expected_version_rejected
# =====================================================================
def test_reschedule_with_stale_expected_version_rejected(api):
    """PRD §2.6: "The request must carry `expected_booking_version` equal to
    the booking's current `version`. If another writer has advanced the
    booking's version since the client last read it — by rescheduling,
    re-quoting, or any other mutation — the client's schedule view is stale,
    and the reschedule is rejected with `ERR_STALE_BOOKING_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_layers/reschedule_with_stale_expected_version_rejected
    """
    ctx = fx.setup_draft_booking(with_insurance=True)
    goat = fx.create_certified_animal("Gogo", "GOAT", "SMALL", 3, 8000,
                                      valid_until="2026-08-01T00:00:00Z")
    ba = fx.attach_animal(ctx["booking"]["id"], goat["id"])
    fx.confirm_booking_animal(ctx["booking"]["id"], ba["id"])
    fx.quote(ctx["booking"]["id"])
    fx.pay(ctx["booking"]["id"], ctx["customer"]["id"], 4872)
    fx.confirm_booking(ctx["booking"]["id"], ctx["customer"]["id"])
    # Re-read so the captured version reflects every mutation so far.
    captured_version = fx.get_booking(ctx["booking"]["id"])["version"]

    moved = validate_success(api.reschedule_booking(
        ctx["booking"]["id"],
        {"new_start_time": "2026-06-24T14:00:00Z",
         "new_end_time": "2026-06-24T16:00:00Z",
         "expected_booking_version": captured_version},
        make_customer_headers(ctx["customer"]["id"])))
    assert moved["status"] == "CONFIRMED", moved["status"]
    assert moved["version"] == captured_version + 1

    # Replaying the pre-reschedule version is now stale.
    resp = api.reschedule_booking(
        ctx["booking"]["id"],
        {"new_start_time": "2026-07-01T14:00:00Z",
         "new_end_time": "2026-07-01T16:00:00Z",
         "expected_booking_version": captured_version},
        make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_BOOKING_VERSION, expected_status=412)
    # The rejected replay left the first reschedule's window in place.
    assert fx.get_booking(ctx["booking"]["id"])["start_time"].startswith("2026-06-24")


# =====================================================================
# Corner/cross_cutting_layers/addon_attach_with_stale_expected_version_rejected
# =====================================================================
def test_addon_attach_with_stale_expected_version_rejected(api):
    """PRD §2.6: "Attaching an add-on supersedes the booking's current quote,
    so the request must likewise carry `expected_booking_version` matching the
    booking's current `version`. A mismatch means the client is pricing
    against a roster it has not observed, and the attach is rejected with
    `ERR_STALE_BOOKING_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/addon_attach_with_stale_expected_version_rejected
    """
    ctx = fx.setup_draft_booking()
    booking_id = ctx["booking"]["id"]
    stale_version = ctx["booking"]["version"]  # captured at creation
    fx.quote(booking_id)  # the quote advances Booking.version
    resp = api.create_addon(
        booking_id,
        {"addon_type": "PONY_RIDE", "duration_minutes": 30,
         "expected_booking_version": stale_version},
        make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_BOOKING_VERSION, expected_status=412)
