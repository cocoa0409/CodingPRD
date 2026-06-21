"""Corner: invalid state transitions, initial state, and terminal lockdown."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, create_catalog, create_unit, create_customer, create_reservation,
    confirm, create_settled_reservation, make_customer_headers,
)
from test_helpers import api_client
from test_helpers import TEST_USERS
from test_helpers.factories import create_alteration_payload, create_party_order_payload

CLERK = TEST_USERS["clerk_headers"]

CAT = {
    "daily_rate_cents": 5000, "deposit_cents": 20000, "replacement_value_cents": 80000,
    "waiver_daily_rate_cents": 1200, "cleaning_buffer_days": 2, "late_fee_daily_rate_cents": 2000,
}


def test_confirm_from_already_confirmed_returns_invalid_state(api):
    """PRD §3.4: "The reservation must currently be `PENDING`, or the transition is undefined and rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_from_already_confirmed_returns_invalid_state
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux X"})
    create_unit(catalog["id"], "M")
    customer = create_customer()
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M")
    validate_success(confirm(resv["id"]), 200)

    res = api_client.confirm_reservation(resv["id"], {}, CLERK)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api_client.get_reservation(resv["id"], CLERK), 200)
    assert after["status"] == "CONFIRMED"


def test_pickup_from_pending_returns_invalid_state(api):
    """PRD §3.6: "The reservation must be `CONFIRMED`, or the transition is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pickup_from_pending_returns_invalid_state
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux W"})
    customer = create_customer()
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M")

    res = api_client.pickup_reservation(resv["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api_client.get_reservation(resv["id"], CLERK), 200)
    assert after["status"] == "PENDING"


def test_cancel_from_settled_terminal_returns_invalid_state(api):
    """PRD §2.6: "sixth, whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`)."
    PRD §3.3: "The reservation lifecycle proceeds through `PENDING`, `CONFIRMED`, `PICKED_UP`, then either `RETURNED` or `OVERDUE`, and finally the terminal `SETTLED`; an unfulfilled reservation may instead reach the terminal `CANCELLED`."

    Design: Corner/state_machines/cancel_from_settled_terminal_returns_invalid_state
    """
    _, _, _, resv, _ = create_settled_reservation(
        catalog_overrides={**CAT, "style_name": "Tux V"},
        reservation_overrides={
            "event_date_iso": "2026-09-04T00:00:00Z",
            "pickup_window_start_iso": "2026-09-01T09:00:00Z",
            "return_window_end_iso": "2026-09-03T17:00:00Z"},
        returned_at_iso="2026-09-03T12:00:00Z", disposition="CLEAN")
    assert resv["status"] == "SETTLED"

    res = api_client.cancel_reservation(resv["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_new_reservation_starts_in_pending(api):
    """PRD §3.3: "A new reservation starts `PENDING`, with no unit yet allocated — its `garment_unit_id` remains null until confirmation."

    Design: Corner/state_machines/new_reservation_starts_in_pending
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux U"})
    customer = create_customer()
    res = api_client.create_reservation(
        {"customer_id": customer["id"], "catalog_id": catalog["id"],
         "requested_size_code": "M", "event_date_iso": "2026-09-06T00:00:00Z",
         "pickup_window_start_iso": "2026-09-01T09:00:00Z",
         "return_window_end_iso": "2026-09-05T09:00:00Z", "damage_waiver_opted": False},
        CLERK)
    resv = validate_success(res, 201)
    assert resv["status"] == "PENDING"
    assert resv["garment_unit_id"] is None


def test_alteration_complete_from_cancelled_returns_invalid_state(api):
    """PRD §3.5: "A clerk completes it, moving it from `REQUESTED` to `COMPLETED".
    PRD §3.5: "An alteration may instead be cancelled from `REQUESTED` to `CANCELLED`, by a clerk or the customer, in which case no fee is charged."

    Design: Corner/state_machines/alteration_complete_from_cancelled_returns_invalid_state
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux T"})
    create_unit(catalog["id"], "M")
    customer = create_customer()
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M")
    validate_success(confirm(resv["id"]), 200)
    alt = validate_success(api_client.create_alteration(
        create_alteration_payload(resv["id"], kind="HEM", fee_cents=4000), CLERK), 201)
    validate_success(api_client.cancel_alteration(alt["id"], CLERK), 200)

    res = api_client.complete_alteration(alt["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    cust = validate_success(api_client.get_customer(customer["id"], CLERK), 200)
    assert cust["balance_owed_cents"] == 0, "no fee charged for the cancelled alteration"


def test_party_lock_from_forming_returns_invalid_state(api):
    """PRD §3.9: "Locking is a `Customer` action permitted when the `posture` is `READY` and the acting customer is the `coordinator_customer_id".

    Design: Corner/errors/party_lock_from_forming_returns_invalid_state
    """
    set_clock()
    coordinator = create_customer()
    coord_headers = make_customer_headers(coordinator["id"])
    party = validate_success(api_client.create_party_order(
        create_party_order_payload(coordinator["id"], event_date_iso="2026-09-06T00:00:00Z",
                                   required_member_count=2),
        coord_headers), 201)
    assert party["posture"] == "FORMING"

    res = api_client.lock_party_order(
        party["id"], {"expected_party_order_version": party["version"]}, coord_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api_client.get_party_order(party["id"], coord_headers), 200)
    assert after["posture"] == "FORMING"
