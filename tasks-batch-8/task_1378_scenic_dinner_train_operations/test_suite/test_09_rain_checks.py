"""Rain-check issuance, redemption money conservation, email matching, and clock-sweep
expiry (PRD §2.5, §3.5, §3.6)."""
import pytest

from test_helpers import (
    cancel_excursion,
    confirm_booking,
    create_confirmed_booking,
    create_held_booking,
    list_rain_checks_for_booking,
    set_clock,
    setup_issued_rain_check_and_second_excursion,
    setup_published_excursion,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


class TestRainCheckMoneyConservation:
    """Cents are conserved across issue + redeem: the source booking's paid_cents is
    carried losslessly into value_cents, and redemption floors the new paid at zero."""

    def test_raincheck_issuance_conserves_paid_cents(self, api, station_agent_headers):
        """PRD §3.6: "When an excursion is cancelled from `PUBLISHED` or `BOARDING`,
        every `CONFIRMED` or `CHECKED_IN` booking becomes `RAIN_CHECKED`, and the system
        issues one rain-check per such booking: its `booking_id` points at the source
        booking, its `customer_email` is copied across, its `value_cents` equals the
        source booking's `paid_cents`, its `reason` — one of `WEATHER`, `EVENT`, or
        `TRACK_RIGHTS_LOST` — is copied from the excursion's `cancel_reason`, its
        `issued_on` is the logical clock's date, and its `expires_on` is 365 days later,
        redeemable through that date inclusive as §2.5 states."

        Design: Difficulty/compensating_invariant/raincheck_money_conservation
        """
        scenario = setup_issued_rain_check_and_second_excursion(source_party_size=2)
        source = scenario["source_booking"]
        rc = scenario["rain_check"]
        assert source["paid_cents"] == 12000, "COACH party of 2 at base fare"
        assert rc["value_cents"] == 12000, "issuance leg conserves cents exactly"
        assert rc["customer_email"] == source["customer_email"], "email copied across"
        assert rc["booking_id"] == source["id"]
        assert rc["status"] == "ISSUED"

    def test_raincheck_redemption_floors_paid_at_zero(self, api, station_agent_headers):
        """PRD §3.5: "With a valid rain-check, `paid_cents` is the total minus the
        rain-check's `value_cents`, floored at zero — and the rain-check is consumed in
        full even when its value exceeds the new booking's total; no change is given. The
        redeemed rain-check flips `ISSUED → REDEEMED` with its `redeemed_booking_id`
        pointing at the booking that consumed it."

        Design: Difficulty/compensating_invariant/raincheck_money_conservation
        """
        scenario = setup_issued_rain_check_and_second_excursion(source_party_size=2)
        rc = scenario["rain_check"]
        excursion_b = scenario["pair"]["b"]["excursion"]

        held = create_held_booking(excursion_b["id"], "sam@x.com", "COACH", 1)
        confirmed = confirm_booking(held["id"], redeemed_rain_check_id=rc["id"])
        assert confirmed["total_price_cents"] == 6000
        assert confirmed["paid_cents"] == 0, "max(0, 6000 - 12000): no change given"

        after = validate_success(api.get_rain_check(rc["id"], station_agent_headers), 200)
        assert after["status"] == "REDEEMED", "rain-check fully consumed"
        assert after["redeemed_booking_id"] == confirmed["id"]


def test_rain_check_email_mismatch_rejected(api, station_agent_headers):
    """PRD §3.5: "The payload may carry a `redeemed_rain_check_id`; when present, the
    rain-check must be `ISSUED`, its `customer_email` must match the booking's, and the
    clock date must be on or before its `expires_on`, with any failure rejected as
    `ERR_RAIN_CHECK_INVALID`."

    Design: Corner/validations/rain_check_email_mismatch_rejected
    """
    scenario = setup_issued_rain_check_and_second_excursion(customer_email="sam@x.com")
    rc = scenario["rain_check"]
    excursion_b = scenario["pair"]["b"]["excursion"]

    held = create_held_booking(excursion_b["id"], "other@x.com", "COACH", 1)
    res = api.booking_event(held["id"],
                            {"event_type": "CONFIRM", "redeemed_rain_check_id": rc["id"]},
                            station_agent_headers)
    validate_error(res, ApiErrorId.ERR_RAIN_CHECK_INVALID.value, expected_status=422)

    after = validate_success(api.get_rain_check(rc["id"], station_agent_headers), 200)
    assert after["status"] == "ISSUED", "a failed redemption leaves the rain-check intact"


def test_clock_sweep_expires_rain_check(api, station_agent_headers, operations_manager_headers):
    """PRD §2.5: "A rain-check lives for 365 days: its `expires_on` is its `issued_on`
    plus 365 days, and it remains redeemable through that date inclusive — only a clock
    date strictly later than `expires_on` expires it."
    PRD §2.5: "Second, rain-checks still `ISSUED` whose `expires_on` is earlier than the
    new clock date flip to `EXPIRED`, processed earliest `expires_on` first."

    Design: Corner/state_machines/clock_sweep_expires_rain_check
    """
    # Cancel happens while the logical clock is at the 2026-08-01 default, so
    # issued_on = 2026-08-01 and expires_on = 2027-08-01.
    scenario = setup_published_excursion()
    booking = create_confirmed_booking(scenario["excursion"]["id"], "rc@x.com", "COACH", 1)
    cancel_excursion(scenario["excursion"]["id"], "WEATHER")
    rc = list_rain_checks_for_booking(booking["id"])[0]
    assert rc["issued_on"] == "2026-08-01"
    assert rc["expires_on"] == "2027-08-01", "issued_on + 365 days"

    set_clock("2027-08-01T12:00:00Z")  # on the expiry date itself
    on_day = validate_success(api.get_rain_check(rc["id"], station_agent_headers), 200)
    assert on_day["status"] == "ISSUED", "redeemable through expires_on inclusive"

    set_clock("2027-08-02T00:00:00Z")  # one day past
    after = validate_success(api.get_rain_check(rc["id"], station_agent_headers), 200)
    assert after["status"] == "EXPIRED", "a strictly later clock date expires it"
