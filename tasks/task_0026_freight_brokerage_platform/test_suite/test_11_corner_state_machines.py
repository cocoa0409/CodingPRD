"""Corner-design section: state_machines.

Initial-state, invalid-transition, precondition-enforcement, and
auto-transition claims on the entity state machines — each rooted in a
single PRD sentence.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    award_quote_payload,
    clock_advance,
    create_carrier,
    create_qualified_carrier,
    create_quote,
    create_shipper,
    deliver_payload,
    get_success_data,
    pickup_payload,
    set_clock,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_carrier_payload,
    reject_carrier_payload,
)
from test_helpers import make_carrier_headers


def test_new_carrier_starts_at_pending(api):
    """PRD §3.1: "The new row starts with `qualification_status` `PENDING`
    and a null `rejection_reason_code`."

    Design: Corner/state_machines/carrier_initial_state_pending
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_carrier(
        create_carrier_payload(
            legal_name="Uniform Carrier",
            mc_number="2525251",
            usdot_number="25252525",
            smartway_tier="GOLD",
            insurance_expiry_utc="2027-01-01T00:00:00Z",
            safety_score=30.0,
        ),
        TEST_USERS["broker_ops_headers"],
    )
    body = get_success_data(res)
    assert body["qualification_status"] == "PENDING"


def test_qualify_a_rejected_carrier_returns_invalid_state(api):
    """PRD §3.1: "A rejected carrier is terminal — there is no path out of
    `REJECTED`."
    PRD §2.7: "state-machine admissibility of the requested transition
    (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/carrier_qualify_from_rejected_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    carrier = create_carrier(
        smartway_tier="NONE",
        insurance_expiry_utc="2027-01-01T00:00:00Z",
        safety_score=30.0,
    )
    get_success_data(api.reject_carrier(
        carrier["id"], reject_carrier_payload(reason_code="BAD_MC"),
        TEST_USERS["broker_ops_headers"],
    ))
    # Attempt to qualify the rejected carrier.
    res = api.qualify_carrier(carrier["id"], TEST_USERS["broker_ops_headers"])
    validate_error(res, "ERR_INVALID_STATE")

    after = get_success_data(api_client.get_carrier(
        carrier["id"], TEST_USERS["broker_ops_headers"],
    ))
    assert after["qualification_status"] == "REJECTED"


def test_deliver_before_pickup_rejected(api):
    """PRD §3.5: "Delivery is reported by the carrier supplying
    `actual_delivery_at_utc`, which must be strictly later than the
    previously recorded `actual_pickup_at_utc`; otherwise the request is
    rejected with `ERR_DELIVERY_BEFORE_PICKUP`."

    Design: Corner/state_machines/load_deliver_before_pickup_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    shipper = create_shipper(credit_limit_cents=100_000_000)
    carrier = create_qualified_carrier(
        smartway_tier="NONE",
        insurance_expiry_utc="2027-01-01T00:00:00Z",
        safety_score=30.0,
    )
    quote = create_quote(
        shipper["id"], lane_origin="10001", lane_destination="30303",
        distance_miles=400,
        pickup_window_start_utc="2026-06-10T08:00:00Z",
        pickup_window_end_utc="2026-06-10T18:00:00Z",
        requested_equipment="DRY_VAN",
    )
    load = get_success_data(api.award_quote(
        quote["id"], award_quote_payload(carrier["id"], quote["version"]),
        TEST_USERS["broker_ops_headers"],
    ))
    carrier_headers = make_carrier_headers(carrier["id"])
    get_success_data(api.pickup_load(
        load["id"], pickup_payload("2026-06-10T11:00:00Z"), carrier_headers,
    ))
    # actual_delivery_at_utc is earlier than the recorded pickup time.
    res = api.deliver_load(
        load["id"], deliver_payload("2026-06-10T10:00:00Z"), carrier_headers,
    )
    validate_error(res, "ERR_DELIVERY_BEFORE_PICKUP")

    after = get_success_data(api_client.get_load(
        load["id"], TEST_USERS["broker_ops_headers"],
    ))
    assert after["status"] == "IN_TRANSIT"


def test_open_quote_auto_expires_on_clock_advance_past_expiry(api):
    """PRD §3.3: "The platform separately advances any `OPEN` quote to
    `EXPIRED` once the current server time reaches or passes
    `expires_at_utc`; this transition is performed by the test-driving
    clock-advance endpoint (§3.9) when invoked."
    PRD §3.9: "Invoking the sweep returns two arrays — the `id` of every
    `QuoteRequest` that just transitioned from `OPEN` to `EXPIRED`, and
    the `id` of every `ContractRate` that just transitioned from `ACTIVE`
    to `EXPIRED`."

    Design: Corner/state_machines/quote_request_expired_after_clock_advance
    """
    set_clock("2026-06-01T00:00:00Z")
    shipper = create_shipper(credit_limit_cents=100_000_000)
    quote = create_quote(
        shipper["id"], lane_origin="10001", lane_destination="30303",
        distance_miles=400,
        pickup_window_start_utc="2026-06-05T08:00:00Z",
        pickup_window_end_utc="2026-06-05T18:00:00Z",
        requested_equipment="DRY_VAN",
    )
    set_clock("2026-06-10T00:00:00Z")
    clock_advance()
    after = get_success_data(api_client.get_quote_request(
        quote["id"], TEST_USERS["broker_ops_headers"],
    ))
    assert after["status"] == "EXPIRED"
