"""Validation-priority conflict tests: when two checks could both fail one request,
the PRD pins which error is returned."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, create_catalog, create_unit, create_customer, create_reservation,
    confirm, create_measurement_profile, make_customer_headers,
)
from test_helpers import api_client
from test_helpers import TEST_USERS
from test_helpers.factories import (
    create_alteration_payload, create_fit_check_payload, return_payload,
    create_reservation_payload,
)

CLERK = TEST_USERS["clerk_headers"]

CAT = {
    "daily_rate_cents": 5000, "deposit_cents": 20000, "replacement_value_cents": 80000,
    "waiver_daily_rate_cents": 1200, "cleaning_buffer_days": 2, "late_fee_daily_rate_cents": 2000,
}


def test_pickup_alteration_pending_beats_balance_outstanding(api):
    """PRD §3.6: "Next, no alteration on the reservation may still be outstanding: every alteration must be `COMPLETED` or `CANCELLED`, and any remaining `REQUESTED` alteration blocks pickup with `ERR_ALTERATION_PENDING`."
    PRD §3.6: "Finally, the customer must owe nothing: if the customer's `balance_owed_cents` is greater than 0, pickup is blocked with `ERR_BALANCE_OUTSTANDING` until the outstanding fees are cleared."

    Design: Difficulty/priority_pair_validation_conflict/pickup_alteration_pending_beats_balance_outstanding
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux I"})
    create_unit(catalog["id"], "M")
    create_unit(catalog["id"], "M")
    customer = create_customer()
    mp = create_measurement_profile(customer["id"], chest_cm=100)

    # Prior reservation: confirm, request + complete an alteration (fee 4000) so the
    # customer carries an outstanding balance.
    pre = create_reservation(customer["id"], catalog["id"], requested_size_code="M",
                             event_date_iso="2026-09-20T00:00:00Z",
                             pickup_window_start_iso="2026-09-15T09:00:00Z",
                             return_window_end_iso="2026-09-19T09:00:00Z")
    validate_success(confirm(pre["id"]), 200)
    alt_pre = validate_success(api_client.create_alteration(
        create_alteration_payload(pre["id"], kind="HEM", fee_cents=4000), CLERK), 201)
    validate_success(api_client.complete_alteration(alt_pre["id"], CLERK), 200)

    # Reservation under test: confirm, PASS fit-check, leave a REQUESTED alteration.
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M",
                              event_date_iso="2026-09-06T00:00:00Z",
                              pickup_window_start_iso="2026-09-01T09:00:00Z",
                              return_window_end_iso="2026-09-05T09:00:00Z")
    validate_success(confirm(resv["id"]), 200)
    validate_success(api_client.create_fit_check(
        create_fit_check_payload(resv["id"], mp["id"]), CLERK), 201)
    validate_success(api_client.create_alteration(
        create_alteration_payload(resv["id"], kind="TAKE_IN", fee_cents=3000), CLERK), 201)

    cust = validate_success(api_client.get_customer(customer["id"], CLERK), 200)
    assert cust["balance_owed_cents"] == 4000, "balance from the completed prior alteration"

    res = api_client.pickup_reservation(resv["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_ALTERATION_PENDING)
    after = validate_success(api_client.get_reservation(resv["id"], CLERK), 200)
    assert after["status"] == "CONFIRMED", "pickup rejected; no transition"


def test_cancel_invalid_state_beats_party_locked(api):
    """PRD §2.6: "sixth, whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Business rules that are specific to a single transition are evaluated after these foundational checks".
    PRD §3.9: "This freeze is enforced at cancellation time: a `CONFIRMED` member reservation whose party is `LOCKED` cannot be cancelled, and the attempt is rejected with `ERR_PARTY_LOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/cancel_invalid_state_beats_party_locked
    """
    # Build a READY party (required 1) with one confirmed member, fit-check it, pick up,
    # return CLEAN, finalize -> the member reservation is SETTLED. Then lock the party.
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux J"})
    create_unit(catalog["id"], "M")
    coordinator = create_customer()
    coord_headers = make_customer_headers(coordinator["id"])
    mp = create_measurement_profile(coordinator["id"], chest_cm=100)

    party = validate_success(api_client.create_party_order(
        {"coordinator_customer_id": coordinator["id"],
         "event_date_iso": "2026-09-04T00:00:00Z", "required_member_count": 1},
        coord_headers), 201)
    resv = validate_success(api_client.create_reservation(
        create_reservation_payload(coordinator["id"], catalog["id"], requested_size_code="M",
                                   event_date_iso="2026-09-04T00:00:00Z",
                                   pickup_window_start_iso="2026-09-01T09:00:00Z",
                                   return_window_end_iso="2026-09-03T17:00:00Z",
                                   party_order_id=party["id"]),
        coord_headers), 201)
    validate_success(confirm(resv["id"], expected_party_order_version=party["version"]), 200)
    party_v1 = validate_success(api_client.get_party_order(party["id"], coord_headers), 200)["version"]
    validate_success(api_client.create_fit_check(
        create_fit_check_payload(resv["id"], mp["id"]), CLERK), 201)
    validate_success(api_client.pickup_reservation(resv["id"], CLERK), 200)
    settlement = validate_success(api_client.return_reservation(
        resv["id"], return_payload("2026-09-03T12:00:00Z", "CLEAN"), CLERK), 200)
    validate_success(api_client.finalize_settlement(settlement["id"], CLERK), 200)
    # Lock the now-READY party (member is SETTLED, still counts as confirmed_member).
    validate_success(api_client.lock_party_order(
        party["id"], {"expected_party_order_version": party_v1}, coord_headers), 200)

    settled = validate_success(api_client.get_reservation(resv["id"], CLERK), 200)
    assert settled["status"] == "SETTLED", "member already terminal before the cancel"

    res = api_client.cancel_reservation(resv["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    party_after = validate_success(api_client.get_party_order(party["id"], coord_headers), 200)
    assert party_after["posture"] == "LOCKED"
