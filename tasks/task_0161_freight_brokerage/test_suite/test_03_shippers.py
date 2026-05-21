"""Shipper onboarding, suspension, and credit posture — PRD §3.2."""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_shipper,
    create_brokerage,
    create_quote_request_payload,
    create_shipper,
    create_shipper_payload,
    make_shipper_headers,
    setup_brokerage_with_shipper,
    suspend_shipper,
    validate_error,
    validate_success,
)


def test_create_shipper_defaults(api, broker_ops_headers):
    """PRD §3.2: "On creation `status` is set to `ACTIVE` and
    `outstanding_invoiced_cents` to 0."

    Claim: a brand-new Shipper is ACTIVE with 0 outstanding.
    """
    brokerage = create_brokerage()
    res = api.create_shipper(
        brokerage["id"],
        create_shipper_payload(company_name="Brand New Shipper"),
        broker_ops_headers,
    )
    shipper = validate_success(res, 201)
    assert_shipper(shipper)
    assert shipper["status"] == "ACTIVE"
    assert shipper["outstanding_invoiced_cents"] == 0
    assert shipper["smartway_required"] is False


def test_create_shipper_requires_company_name(api, broker_ops_headers):
    """PRD §3.2: "A `BrokerOps` operator creates a shipper by supplying
    `company_name`, the boolean `smartway_required` ..., and a
    `credit_limit_cents` integer cap on outstanding invoiced amount."

    Claim: missing company_name -> ERR_INVALID_REQUEST.
    """
    brokerage = create_brokerage()
    payload = create_shipper_payload()
    del payload["company_name"]
    res = api.create_shipper(brokerage["id"], payload, broker_ops_headers)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_suspend_shipper_transitions_to_suspended(api, broker_ops_headers):
    """PRD §3.2: "A shipper can be moved to `SUSPENDED` by a `BrokerOps`
    operator."

    Claim: /suspend on an ACTIVE shipper -> status == SUSPENDED.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    res = api.suspend_shipper(brokerage["id"], shipper["id"],
                              broker_ops_headers)
    after = validate_success(res, 200)
    assert after["status"] == "SUSPENDED"


def test_suspended_shipper_blocks_new_quote_request(api):
    """PRD §3.2: "while `SUSPENDED`, attempts to file a new `QuoteRequest`
    against that shipper are rejected with `ERR_SHIPPER_SUSPENDED`."

    Claim: POST /quote-requests on a SUSPENDED shipper -> ERR_SHIPPER_SUSPENDED.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    suspend_shipper(brokerage["id"], shipper["id"])

    # ShipperUser ownership-gated call: mint headers from the actual
    # shipper id (PRD §2.1).
    res = api.create_quote_request(
        brokerage["id"], shipper["id"],
        create_quote_request_payload(),
        make_shipper_headers(shipper["id"]),
    )
    validate_error(res, "ERR_SHIPPER_SUSPENDED")


def test_shipper_user_cannot_read_other_shippers_resource(
    api, broker_ops_headers,
):
    """PRD §2.1: "A `ShipperUser` accessing another shipper's resource is
    rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Claim: ShipperUser headers minted from Shipper A's id attempting to
    GET Shipper B receive ERR_INSUFFICIENT_PERMISSIONS.
    """
    brokerage, shipper_a = setup_brokerage_with_shipper()
    shipper_b = create_shipper(brokerage["id"], company_name="Second")
    res = api.get_shipper(brokerage["id"], shipper_b["id"],
                          make_shipper_headers(shipper_a["id"]))
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")
