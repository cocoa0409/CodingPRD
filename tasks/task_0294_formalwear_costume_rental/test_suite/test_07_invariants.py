"""Compensating-invariant tests: deposit conservation over a reservation's
lifecycle, and unit-pool conservation across a confirm+cancel round trip."""
from test_helpers import (
    validate_success,
    set_clock, create_catalog, create_unit, create_customer, create_reservation,
    confirm, create_picked_up_reservation, return_reservation,
    ledger_for_reservation, assert_deposit_conserved, available_unit_count,
)
from test_helpers import api_client
from test_helpers import TEST_USERS

CLERK = TEST_USERS["clerk_headers"]

CAT = {
    "daily_rate_cents": 5000, "deposit_cents": 20000, "replacement_value_cents": 80000,
    "waiver_daily_rate_cents": 1200, "cleaning_buffer_days": 2, "late_fee_daily_rate_cents": 2000,
}
ONTIME_RESV = {
    "event_date_iso": "2026-09-04T00:00:00Z",
    "pickup_window_start_iso": "2026-09-01T09:00:00Z",
    "return_window_end_iso": "2026-09-03T17:00:00Z",
}


def test_deposit_hold_equals_release_plus_capture_on_damage(api):
    """PRD §2.9: "Over the full pickup-to-settle lifecycle of a single reservation the deposit is conserved: the amount held at pickup equals the refunded portion plus the captured portion, so the `DEPOSIT_HOLD` magnitude always equals the sum of the matching `DEPOSIT_RELEASE` magnitude and `DEPOSIT_CAPTURE` magnitude."

    Design: Difficulty/compensating_invariant/deposit_conservation_hold_equals_release_plus_capture
    """
    _, _, _, resv = create_picked_up_reservation(
        catalog_overrides={**CAT, "style_name": "Tux P"}, reservation_overrides=ONTIME_RESV)
    # Return DAMAGED (no waiver): damage 48000, deposit 20000 fully captured.
    return_reservation(resv["id"], "2026-09-03T12:00:00Z", "DAMAGED")

    entries = ledger_for_reservation(resv["id"])
    hold, release, capture = assert_deposit_conserved(entries)
    assert hold == 20000, f"DEPOSIT_HOLD must equal the catalog deposit; got {hold}"
    assert release == 0, "no un-applied deposit to release on a full-capture damage close"
    assert capture == 20000, "full deposit consumed by the 48000 gross fees"


def test_unit_pool_conserved_confirm_then_cancel(api):
    """PRD §3.4: "that unit transitions from `AVAILABLE` to `RESERVED`."
    PRD §3.9: "on success the allocated unit is released from `RESERVED` back to `AVAILABLE".

    Design: Difficulty/compensating_invariant/unit_pool_conservation_confirm_then_cancel
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux Q"})
    unit = create_unit(catalog["id"], "M")
    customer = create_customer()
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M")

    before = available_unit_count(catalog["id"], "M")
    assert before == 1, f"one AVAILABLE size-M unit before confirm; got {before}"

    validate_success(confirm(resv["id"]), 200)
    validate_success(api_client.cancel_reservation(resv["id"], CLERK), 200)

    after = available_unit_count(catalog["id"], "M")
    assert after == 1, f"pool conserved across confirm+cancel; got {after}"
    unit_after = validate_success(api_client.get_garment_unit(unit["id"], CLERK), 200)
    assert unit_after["status"] == "AVAILABLE"
