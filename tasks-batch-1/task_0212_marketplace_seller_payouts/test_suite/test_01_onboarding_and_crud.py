"""Seller onboarding, CRUD, computed-field, and ledger-immutability claims.

Translates queue B (Corner) instances from the entities, state_machines,
endpoints, rbac, and consistency_model sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_seller, assert_order, assert_ledger_entry,
    create_seller_payload, create_order_payload, create_payout_method_payload,
    NON_EXISTENT_UUID,
    make_seller_headers,
    create_fee_schedule, create_seller, create_order, onboard_active_seller,
    seller_with_verified_method,
)
from test_helpers import api_client


# ─────────────────────────────────────────────────────────────────────────────
# Entities
# ─────────────────────────────────────────────────────────────────────────────

def test_create_seller_returns_201_with_onboarding_defaults(api, reviewer_headers):
    """PRD §3.1: "A newly registered seller starts with `kyc_status` of `PENDING`,
    `w9_status` of `NOT_SUBMITTED`, and an `account_status` of `ONBOARDING`."
    PRD §3.1: "Its computed standing fields — `risk_tier` (`STANDARD`),
    `seller_risk_score` (0) ... all begin at their defaults."
    PRD §2.4: "an integer `version` that begins at 1".

    Design: Corner/entities/create_seller_returns_201_with_onboarding_defaults
    """
    res = api.create_seller(create_seller_payload(legal_name="Aardvark LLC"), reviewer_headers)
    seller = validate_success(res, 201)
    assert_seller(seller)
    assert seller["kyc_status"] == "PENDING"
    assert seller["w9_status"] == "NOT_SUBMITTED"
    assert seller["account_status"] == "ONBOARDING"
    assert seller["risk_tier"] == "STANDARD"
    assert seller["version"] == 1


def test_get_seller_not_found_returns_404(api, reviewer_headers):
    """PRD §2.8: "a reference to a non-existent resource anywhere in the path or
    body yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_seller_not_found_returns_404
    """
    res = api.get_seller(NON_EXISTENT_UUID, reviewer_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_seller_missing_required_field_returns_invalid_request(api, reviewer_headers):
    """PRD §3.1: "A `PlatformReviewer` registers a seller by supplying the seller's
    `legal_name`, `email`, `country_code`, `tax_classification`, and `tin_last4`."
    PRD §2.11: "Body well-formedness — required fields present, enums in range,
    amounts at least 1 (`ERR_INVALID_REQUEST`) — is the lowest-priority catch-all."

    Design: Corner/entities/create_seller_missing_required_field_returns_invalid_request
    """
    payload = create_seller_payload()
    del payload["legal_name"]
    res = api.create_seller(payload, reviewer_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_seller_invalid_country_enum_returns_invalid_request(api, reviewer_headers):
    """PRD §3.1: "The `country_code` is one of `US`, `CA`, `GB`, `DE`, or `AU`".
    PRD §2.11: "Body well-formedness — required fields present, enums in range,
    amounts at least 1 (`ERR_INVALID_REQUEST`) — is the lowest-priority catch-all."

    Design: Corner/entities/create_seller_invalid_country_enum_returns_invalid_request
    """
    res = api.create_seller(create_seller_payload(country_code="FR"), reviewer_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_order_computed_fees_ignore_client_supplied_values(api, finance_headers):
    """PRD §3.4: "The commission, stored in `commission_cents`, is the gross
    multiplied by the schedule's commission basis points divided by ten thousand,
    rounded half-up to whole cents."
    PRD §3.4: "The provisional `net_earnings_cents` is then the gross minus the
    commission, minus the platform fee, minus the processing fee — with no refund
    yet considered."

    Design: Corner/entities/order_computed_fees_ignore_client_supplied_values
    """
    create_fee_schedule()
    seller = create_seller()
    # Client attempts to dictate commission/net; server must price authoritatively.
    payload = create_order_payload(seller["id"], gross_amount_cents=10000)
    payload["commission_cents"] = 1
    payload["net_earnings_cents"] = 99999
    res = api.create_order(payload, finance_headers)
    order = validate_success(res, 201)
    assert_order(order)
    assert order["commission_cents"] == 1500
    assert order["net_earnings_cents"] == 8130
    assert order["settlement_status"] == "PENDING"


def test_ledger_entry_immutable_no_version_field(api, finance_headers):
    """PRD §2.4: "Two resource types are append-only records of fact and therefore
    carry only `id` and `created_at`, with no `updated_at` and no `version`: a
    ledger entry and a balance statement."
    PRD §3.4: "Order creation posts an `ORDER_PROCEEDS` ledger entry for that net
    amount in `PENDING` hold state".

    Design: Corner/entities/ledger_entry_immutable_no_version_field
    """
    create_fee_schedule()
    seller = create_seller()
    create_order(seller["id"], gross_amount_cents=10000)
    res = api.list_seller_ledger_entries(seller["id"], finance_headers)
    data, _meta = validate_paginated(res)
    proceeds = [e for e in data if e["source_type"] == "ORDER_PROCEEDS"]
    assert len(proceeds) == 1, f"expected exactly one ORDER_PROCEEDS entry, got {len(proceeds)}"
    entry = proceeds[0]
    assert_ledger_entry(entry)
    assert entry["amount_cents"] == 8130
    assert entry["hold_state"] == "PENDING"
    assert "version" not in entry
    assert "updated_at" not in entry


# ─────────────────────────────────────────────────────────────────────────────
# State machines (simple corners)
# ─────────────────────────────────────────────────────────────────────────────

def test_kyc_decision_from_pending_without_in_review_returns_invalid_state(api, reviewer_headers):
    """PRD §3.1: "Approval requires that the seller's `kyc_status` is currently
    `IN_REVIEW`."
    PRD §2.11: "Then whether the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/kyc_decision_from_pending_without_in_review_returns_invalid_state
    """
    seller = create_seller()
    res = api.decide_kyc(seller["id"], {"decision": "APPROVE"}, reviewer_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    refetched = validate_success(api.get_seller(seller["id"], reviewer_headers), 200)
    assert refetched["kyc_status"] == "PENDING"


def test_closed_seller_terminal_lockdown_reinstate_rejected(api, reviewer_headers):
    """PRD §3.2: "Closing a seller is terminal".
    PRD §3.2: "All four posture transitions are driven by a `PlatformReviewer`;
    requesting any of them from a state where the transition is undefined yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/closed_seller_terminal_lockdown_reinstate_rejected
    """
    seller, _pm = onboard_active_seller()
    # No orders → close is permitted.
    closed = validate_success(api.close_seller(seller["id"], reviewer_headers), 200)
    assert closed["account_status"] == "CLOSED"
    res = api.reinstate_seller(seller["id"], reviewer_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    refetched = validate_success(api.get_seller(seller["id"], reviewer_headers), 200)
    assert refetched["account_status"] == "CLOSED"


def test_payout_method_verify_third_wrong_code_moves_to_failed(api):
    """PRD §3.3: "Only when a submitted `micro_deposit_code` does not match and the
    method already has two prior failed attempts does the third wrong attempt move
    `verification_status` to `FAILED`, which is terminal."
    PRD §3.3: "Any non-matching submission is rejected with
    `ERR_BAD_MICRO_DEPOSIT_CODE` (HTTP 422); the transition to `FAILED` occurs on
    that third failure."

    Design: Corner/state_machines/payout_method_verify_third_wrong_code_moves_to_failed
    """
    seller, pm = seller_with_verified_method()
    sid = seller["id"]
    seller_hdr = make_seller_headers(sid)
    # Re-create a fresh UNVERIFIED method to exercise the failure path cleanly.
    fresh = validate_success(
        api.create_payout_method(create_payout_method_payload(sid, account_last4="4321"), seller_hdr), 201
    )
    pmid = fresh["id"]
    # Two wrong codes: still UNVERIFIED, each returns ERR_BAD_MICRO_DEPOSIT_CODE.
    validate_error(api.verify_payout_method(pmid, {"micro_deposit_code": "WRONG1"}, seller_hdr),
                   "ERR_BAD_MICRO_DEPOSIT_CODE", expected_status=422)
    validate_error(api.verify_payout_method(pmid, {"micro_deposit_code": "WRONG2"}, seller_hdr),
                   "ERR_BAD_MICRO_DEPOSIT_CODE", expected_status=422)
    # Third wrong attempt flips to FAILED.
    api.verify_payout_method(pmid, {"micro_deposit_code": "WRONG3"}, seller_hdr)
    refetched = validate_success(api.get_payout_method(pmid, seller_hdr), 200)
    assert refetched["verification_status"] == "FAILED"


def test_bad_micro_deposit_code_returns_422(api):
    """PRD §3.3: "Any non-matching submission is rejected with
    `ERR_BAD_MICRO_DEPOSIT_CODE` (HTTP 422)".

    Design: Corner/state_machines/payout_method_verify_third_wrong_code_moves_to_failed
    """
    seller = create_seller()
    sid = seller["id"]
    seller_hdr = make_seller_headers(sid)
    pm = validate_success(
        api.create_payout_method(create_payout_method_payload(sid), seller_hdr), 201
    )
    res = api.verify_payout_method(pm["id"], {"micro_deposit_code": "DEFINITELY_WRONG"}, seller_hdr)
    validate_error(res, "ERR_BAD_MICRO_DEPOSIT_CODE", expected_status=422)
    refetched = validate_success(api.get_payout_method(pm["id"], seller_hdr), 200)
    assert refetched["verification_status"] == "UNVERIFIED"


# ─────────────────────────────────────────────────────────────────────────────
# RBAC
# ─────────────────────────────────────────────────────────────────────────────

def test_seller_cannot_create_order_returns_unauthorized(api):
    """PRD §4 endpoint table: `POST /orders` authorized role is PlatformFinance.
    PRD §2.1: "When the headers are present but the named role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/seller_cannot_create_order_returns_unauthorized
    """
    seller = create_seller()
    res = api.create_order(
        create_order_payload(seller["id"], gross_amount_cents=10000),
        make_seller_headers(seller["id"]),
    )
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID` ...
    and `X-User-Role` .... If either header is missing or empty, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_sellers(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_seller_acting_on_other_sellers_payout_method_returns_not_owner(api):
    """PRD §2.1: "a seller attempting to read or act on a resource whose `seller_id`
    differs from their own `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403). This ownership rule governs the seller-scoped endpoints — a seller's
    own payout methods ...".

    Design: Corner/rbac/seller_acting_on_other_sellers_payout_method_returns_not_owner
    """
    seller_a, pm = seller_with_verified_method()
    seller_b = create_seller()
    code = pm.get("micro_deposit_code")
    # Seller B attempts to verify Seller A's method.
    res = api.verify_payout_method(
        pm["id"], {"micro_deposit_code": code}, make_seller_headers(seller_b["id"])
    )
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints (pagination)
# ─────────────────────────────────────────────────────────────────────────────

def test_list_orders_paginated_envelope_fields(api, finance_headers):
    """PRD §2.3: "The `meta` block of a list response carries the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the
    number of records matching the filter before pagination and `has_more`
    indicates whether records remain beyond the current page."

    Design: Corner/endpoints/list_orders_paginated_envelope_fields
    """
    create_fee_schedule()
    seller = create_seller()
    create_order(seller["id"], gross_amount_cents=5000)
    create_order(seller["id"], gross_amount_cents=6000)
    res = api.list_orders(finance_headers, params={"seller_id": seller["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_list_orders_invalid_limit_returns_pagination_error(api, finance_headers):
    """PRD §2.3: "A request whose `limit` falls outside the range 1 through 100, or
    whose `offset` is below 0, is rejected with `ERR_VALIDATION_PAGINATION`
    (HTTP 400)."

    Design: Corner/endpoints/list_orders_invalid_limit_returns_pagination_error
    """
    res = api.list_orders(finance_headers, params={"limit": 500})
    validate_error(res, "ERR_VALIDATION_PAGINATION", expected_status=400)


# ─────────────────────────────────────────────────────────────────────────────
# Consistency model
# ─────────────────────────────────────────────────────────────────────────────

def test_immediate_consistency_balance_visible_in_create_order_chain(api, finance_headers):
    """PRD §3.4: "The provisional `net_earnings_cents` is then the gross minus the
    commission, minus the platform fee, minus the processing fee — with no refund
    yet considered. Order creation posts an `ORDER_PROCEEDS` ledger entry for that
    net amount in `PENDING` hold state ... and reconciles the seller's balances".
    PRD §2.6: "The `pending_balance_cents` is the sum of ledger-entry amounts whose
    `hold_state` is `PENDING`".

    Design: Corner/consistency_model/immediate_consistency_balance_visible_in_create_order_chain
    """
    create_fee_schedule()
    seller = create_seller()
    create_order(seller["id"], gross_amount_cents=10000)
    refetched = validate_success(api.get_seller(seller["id"], finance_headers), 200)
    assert refetched["pending_balance_cents"] == 8130
    assert refetched["available_balance_cents"] == 0
