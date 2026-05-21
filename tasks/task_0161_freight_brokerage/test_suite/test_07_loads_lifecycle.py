"""Load tender, carrier-accept, depart, deliver, cancel — PRD §3.6.

Covers the carrier-gate checks (qualification, insurance, SmartWay)
and the cancellability boundary.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    add_minutes,
    assert_load,
    carrier_accept_load,
    create_carrier,
    create_load_payload,
    depart_load,
    iso_utc,
    make_carrier_headers,
    make_shipper_headers,
    parse_iso,
    setup_accepted_load,
    setup_accepted_quote,
    setup_brokerage_shipper_qualified_carrier,
    setup_in_transit_load,
    setup_tendered_load,
    suspend_carrier,
    tender_load,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.6 — Tender on an ACCEPTED quote
# ===========================================================================
def test_tender_load_succeeds_and_is_tendered(api, broker_ops_headers):
    """PRD §3.6: "The load lands in `TENDERED`."

    Claim: tendering a load on an ACCEPTED quote with a QUALIFIED
    carrier returns a Load whose status == TENDERED.
    """
    brokerage, shipper, carrier, _quote, load = setup_tendered_load()
    assert_load(load)
    assert load["status"] == "TENDERED"
    assert load["carrier_id"] == carrier["id"]


def test_tender_copies_linehaul_and_rate_source_from_quote(api):
    """PRD §3.6: "As side effects, the load's `rate_source` and
    `linehaul_cents` are copied from the source quote."

    Claim: load.linehaul_cents and load.rate_source equal the quote's
    quoted_linehaul_cents and rate_source.
    """
    brokerage, shipper, carrier, quote, load = setup_tendered_load()
    assert load["linehaul_cents"] == quote["quoted_linehaul_cents"]
    assert load["rate_source"] == quote["rate_source"]


def test_tender_quote_not_accepted_rejected(api, broker_ops_headers):
    """PRD §3.6: "A `BrokerOps` operator tenders a load by supplying
    `quote_request_id` (which must refer to a `QuoteRequest` in `ACCEPTED` —
    otherwise `ERR_QUOTE_NOT_ACCEPTED`)."

    Claim: tender on a QUOTED (not ACCEPTED) quote -> ERR_QUOTE_NOT_ACCEPTED.
    """
    brokerage, shipper, carrier = (
        setup_brokerage_shipper_qualified_carrier()
    )
    # Make a quote in QUOTED but NOT accepted.
    from test_helpers import create_quote_request, quote_quote_request
    quote = create_quote_request(brokerage["id"], shipper["id"])
    quoted = quote_quote_request(brokerage["id"], shipper["id"], quote["id"])
    res = api.create_load(
        brokerage["id"], shipper["id"],
        create_load_payload(quoted["id"], carrier["id"]),
        broker_ops_headers,
    )
    validate_error(res, "ERR_QUOTE_NOT_ACCEPTED")


def test_tender_non_qualified_carrier_rejected(api, broker_ops_headers):
    """PRD §3.6: "The carrier-gate checks require the carrier to be in
    `QUALIFIED` (otherwise `ERR_CARRIER_NOT_QUALIFIED`)."

    Claim: tendering to a PENDING_QUALIFICATION carrier ->
    ERR_CARRIER_NOT_QUALIFIED.
    """
    brokerage, shipper, accepted = setup_accepted_quote()
    pending_carrier = create_carrier(brokerage["id"])  # PENDING_QUALIFICATION
    res = api.create_load(
        brokerage["id"], shipper["id"],
        create_load_payload(accepted["id"], pending_carrier["id"]),
        broker_ops_headers,
    )
    validate_error(res, "ERR_CARRIER_NOT_QUALIFIED")


def test_tender_smartway_violation_rejected(api, broker_ops_headers):
    """PRD §3.6: "if the owning shipper has `smartway_required` set to
    true — the carrier's `smartway_certified` to be true (otherwise
    `ERR_SMARTWAY_REQUIRED`)."

    Claim: tender on a SmartWay-required shipper with a non-certified
    carrier -> ERR_SMARTWAY_REQUIRED.
    """
    brokerage, shipper, carrier = (
        setup_brokerage_shipper_qualified_carrier(
            smartway_required=True, smartway_certified=False,
        )
    )
    # Build an accepted quote for this SmartWay-required shipper.
    from test_helpers import (create_quote_request, quote_quote_request,
                              accept_quote_request)
    quote = create_quote_request(brokerage["id"], shipper["id"])
    quoted = quote_quote_request(brokerage["id"], shipper["id"], quote["id"])
    accepted = accept_quote_request(brokerage["id"], shipper["id"],
                                    quoted["id"])
    res = api.create_load(
        brokerage["id"], shipper["id"],
        create_load_payload(accepted["id"], carrier["id"]),
        broker_ops_headers,
    )
    validate_error(res, "ERR_SMARTWAY_REQUIRED")


# ===========================================================================
# §3.6 — Carrier accepts the tender.
# ===========================================================================
def test_carrier_accept_transitions_to_accepted(api):
    """PRD §3.6: "A `CarrierUser` accepts the tender, advancing `TENDERED → ACCEPTED`."

    Claim: carrier-accept moves the load into status == ACCEPTED.
    """
    brokerage, shipper, carrier, _quote, load = setup_tendered_load()
    res = api.carrier_accept_load(
        brokerage["id"], shipper["id"], load["id"],
        make_carrier_headers(carrier["id"]),
    )
    after = validate_success(res, 200)
    assert after["status"] == "ACCEPTED"


def test_carrier_accept_by_other_carrier_rejected(api):
    """PRD §3.6: "This operation is restricted to the carrier whose `id`
    matches `X-User-ID`; any other carrier sees `ERR_INSUFFICIENT_PERMISSIONS`."

    Claim: a different carrier's id in X-User-ID -> ERR_INSUFFICIENT_PERMISSIONS.
    """
    brokerage, shipper, carrier, _quote, load = setup_tendered_load()
    other_carrier = create_carrier(brokerage["id"])
    res = api.carrier_accept_load(
        brokerage["id"], shipper["id"], load["id"],
        make_carrier_headers(other_carrier["id"]),
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_carrier_accept_a_non_tendered_load_rejected(api):
    """PRD §3.6: "Accepting a load not in `TENDERED` yields `ERR_LOAD_NOT_TENDERED`."

    Claim: carrier-accept on an ACCEPTED load -> ERR_LOAD_NOT_TENDERED.
    """
    brokerage, shipper, carrier, _quote, load = setup_accepted_load()
    res = api.carrier_accept_load(
        brokerage["id"], shipper["id"], load["id"],
        make_carrier_headers(carrier["id"]),
    )
    validate_error(res, "ERR_LOAD_NOT_TENDERED")


# ===========================================================================
# §3.6 — Depart, deliver, delivery-time guard.
# ===========================================================================
def test_depart_transitions_to_in_transit(api):
    """PRD §3.6: "The carrier then departs the pickup, moving the load
    from `ACCEPTED` to `IN_TRANSIT`."

    Claim: depart on an ACCEPTED load -> status == IN_TRANSIT.
    """
    brokerage, shipper, carrier, _quote, load = setup_accepted_load()
    res = api.depart_load(brokerage["id"], shipper["id"], load["id"],
                          make_carrier_headers(carrier["id"]))
    after = validate_success(res, 200)
    assert after["status"] == "IN_TRANSIT"


def test_depart_on_tendered_load_rejected(api):
    """PRD §3.6: "Attempting to depart a load not in `ACCEPTED` yields
    `ERR_LOAD_NOT_ACCEPTED`."

    Claim: /depart on a TENDERED load -> ERR_LOAD_NOT_ACCEPTED.
    """
    brokerage, shipper, carrier, _quote, load = setup_tendered_load()
    res = api.depart_load(brokerage["id"], shipper["id"], load["id"],
                          make_carrier_headers(carrier["id"]))
    validate_error(res, "ERR_LOAD_NOT_ACCEPTED")


def test_deliver_with_depart_before_arrive_rejected(api):
    """PRD §3.6: "The latter must be no earlier than the former;
    otherwise the request is rejected with `ERR_INVALID_DELIVERY_TIMES`."

    Claim: actual_depart_at < actual_arrive_at -> ERR_INVALID_DELIVERY_TIMES
    with HTTP 422.
    """
    brokerage, shipper, carrier, _quote, load = setup_in_transit_load()
    arrive = parse_iso(brokerage["clock_now_iso"])
    res = api.deliver_load(
        brokerage["id"], shipper["id"], load["id"],
        {
            "actual_arrive_at": iso_utc(arrive),
            "actual_depart_at": iso_utc(add_minutes(arrive, -10)),
        },
        make_carrier_headers(carrier["id"]),
    )
    validate_error(res, "ERR_INVALID_DELIVERY_TIMES")


def test_deliver_with_equal_arrive_depart_succeeds(api):
    """PRD §3.6: "The latter must be no earlier than the former" — equal
    is allowed.

    Claim: actual_depart_at == actual_arrive_at succeeds; detention is 0.
    """
    brokerage, shipper, carrier, _quote, load = setup_in_transit_load()
    arrive = parse_iso(brokerage["clock_now_iso"])
    res = api.deliver_load(
        brokerage["id"], shipper["id"], load["id"],
        {
            "actual_arrive_at": iso_utc(arrive),
            "actual_depart_at": iso_utc(arrive),
        },
        make_carrier_headers(carrier["id"]),
    )
    delivered = validate_success(res, 200)
    assert delivered["status"] == "DELIVERED"
    assert delivered["provisional_detention_cents"] == 0


# ===========================================================================
# §3.6 — Cancellation.
# ===========================================================================
def test_cancel_tendered_load_succeeds(api, broker_ops_headers):
    """PRD §3.6: "Cancellation moves a load from either `TENDERED` or
    `ACCEPTED` into the terminal `CANCELLED` state."

    Claim: cancel a TENDERED load -> status == CANCELLED.
    """
    brokerage, shipper, _carrier, _quote, load = setup_tendered_load()
    res = api.cancel_load(brokerage["id"], shipper["id"], load["id"],
                          broker_ops_headers)
    after = validate_success(res, 200)
    assert after["status"] == "CANCELLED"


def test_cancel_in_transit_load_rejected(api, broker_ops_headers):
    """PRD §3.6: "Cancellation from any later state is rejected with
    `ERR_LOAD_NOT_CANCELLABLE`."

    Claim: cancel on an IN_TRANSIT load -> ERR_LOAD_NOT_CANCELLABLE.
    """
    brokerage, shipper, _carrier, _quote, load = setup_in_transit_load()
    res = api.cancel_load(brokerage["id"], shipper["id"], load["id"],
                          broker_ops_headers)
    validate_error(res, "ERR_LOAD_NOT_CANCELLABLE")
