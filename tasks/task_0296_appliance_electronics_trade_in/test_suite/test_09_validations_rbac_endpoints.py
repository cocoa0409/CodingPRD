"""Remaining business validations (promo scope/status, declared-defect membership),
list/pagination reads, RBAC denials, and immediate-consistency data-wipe-then-payout.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_catalog_model_customer,
    create_catalog,
    create_device_model,
    create_customer,
    create_draft_trade_in,
    create_received_trade_in,
    create_promotion,
    inspect,
    record_data_wipe,
    set_clock,
    api_client,
    make_customer_headers,
    make_unauthenticated_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
AGENT = TEST_USERS["grading_agent_headers"]
FINANCE = TEST_USERS["finance_operator_headers"]


# ─── validations ──────────────────────────────────────

def test_promo_out_of_category_scope_returns_409(api):
    """PRD §3.3: "The resolution must find an `ACTIVE` campaign whose scope matches the
    device's category or is `ALL`; a missing, non-active, or out-of-scope code is
    rejected with `ERR_PROMO_INVALID` (HTTP 409)."

    A promo scoped to LAPTOP supplied for a SMARTPHONE trade-in returns ERR_PROMO_INVALID.

    Design: Corner/validations/promo_out_of_category_scope_returns_409
    """
    cat, model, customer = setup_catalog_model_customer()
    create_promotion(
        cat["id"], code="LAPONLY", category_scope="LAPTOP",
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
        bonus_pct=0.10, bonus_flat_cents=0, bonus_cap_cents=6000,
    )
    set_clock("2026-06-01T00:00:00Z")
    resp = api.create_trade_in(
        {"customer_id": customer["id"], "device_model_id": model["id"], "declared_grade": "GOOD", "promo_code": "LAPONLY"},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, "ERR_PROMO_INVALID")


def test_quote_declared_unknown_defect_returns_422(api):
    """PRD §3.4: "every entry in `declared_defects` must be a key that exists in the
    model's `defect_deductions`, otherwise `ERR_UNKNOWN_DEFECT` (HTTP 422)."

    POST /quote where declared_defects contains a key absent from the model's
    defect_deductions returns ERR_UNKNOWN_DEFECT; trade-in stays DRAFT.

    Design: Corner/validations/quote_declared_unknown_defect_returns_422
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_draft_trade_in(customer, model, declared_grade="GOOD", declared_defects=["BENT_HINGE"])
    resp = api.quote_trade_in(ti["id"], make_customer_headers(customer["id"]))
    validate_error(resp, "ERR_UNKNOWN_DEFECT")
    assert validate_success(api.get_trade_in(ti["id"], ADMIN))["status"] == "DRAFT"


def test_expired_promo_campaign_returns_409(api):
    """PRD §3.3: "The resolution must find an `ACTIVE` campaign whose scope matches the
    device's category or is `ALL`; a missing, non-active, or out-of-scope code is
    rejected with `ERR_PROMO_INVALID` (HTTP 409)."

    An EXPIRED promo campaign supplied at trade-in creation returns ERR_PROMO_INVALID.

    Design: Corner/validations/expired_promo_campaign_returns_409
    """
    cat, model, customer = setup_catalog_model_customer()
    promo = create_promotion(
        cat["id"], code="OLD", category_scope="ALL",
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
        bonus_pct=0.10, bonus_flat_cents=0, bonus_cap_cents=6000,
    )
    validate_success(api.expire_promotion_campaign(promo["id"], ADMIN))
    set_clock("2026-06-01T00:00:00Z")
    resp = api.create_trade_in(
        {"customer_id": customer["id"], "device_model_id": model["id"], "declared_grade": "GOOD", "promo_code": "OLD"},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, "ERR_PROMO_INVALID")


# ─── endpoints ────────────────────────────────────────

def test_list_device_models_paginated_envelope(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping in the `meta`
    object of the envelope, namely `limit`, `offset`, `total_count`, and `has_more`."

    GET /catalogs/{id}/device-models returns an array envelope with total_count 2 and
    has_more false for a catalog holding two models.

    Design: Corner/endpoints/list_device_models_paginated_envelope
    """
    cat = create_catalog()
    create_device_model(cat["id"], model_code="PHN-1", category="SMARTPHONE")
    create_device_model(cat["id"], manufacturer="Globex", model_code="TAB-1", category="TABLET", base_value_cents=40000)

    data, meta = validate_paginated(api.list_device_models(cat["id"], ADMIN))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_filter_trade_ins_by_customer(api):
    """PRD §3.3: "A customer also carries two computed running totals that begin at 0:
    `wallet_balance_cents`, the store-credit balance, and `lifetime_payout_cents`, the
    conserved sum of payouts ever settled to them."
    PRD §3.3: "A customer record can be fetched to read back its wallet and lifetime
    totals, and a customer's own trade-ins can be listed."

    GET /trade-ins?customer_id={id} returns only that customer's trade-ins.

    Design: Corner/endpoints/filter_trade_ins_by_customer
    """
    cat = create_catalog()
    model = create_device_model(cat["id"])
    cust_a = create_customer()
    cust_b = create_customer()
    create_draft_trade_in(cust_a, model, declared_grade="GOOD")

    data, meta = validate_paginated(api.list_trade_ins(ADMIN, params={"customer_id": cust_a["id"]}))
    assert meta["total_count"] == 1
    assert all(t["customer_id"] == cust_a["id"] for t in data)


# ─── rbac ─────────────────────────────────────────────

def test_grading_agent_cannot_create_payout(api):
    """PRD §2.1: "When the headers are present and valid but the role is not permitted
    to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    A GradingAgent calling POST /trade-ins/{id}/payouts (reserved to FinanceOperator)
    is denied with ERR_FORBIDDEN; the trade-in stays ACCEPTED.

    Design: Corner/rbac/grading_agent_cannot_create_payout
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_received_trade_in(customer, model, declared_grade="FLAWLESS")
    inspect(ti["id"], "FLAWLESS", verified_defects=[])

    resp = api.create_payout(ti["id"], {"method": "ACH"}, AGENT)
    validate_error(resp, "ERR_FORBIDDEN")
    assert validate_success(api.get_trade_in(ti["id"], ADMIN))["status"] == "ACCEPTED"


def test_customer_cannot_act_on_other_customers_trade_in(api):
    """PRD §2.1: "for trade-in actions reserved to the owner, the acting `Customer`'s
    `X-User-ID` must equal the target `TradeIn.customer_id`, and a mismatch is rejected
    with `ERR_NOT_OWNER` (HTTP 403)."

    Customer B calling /quote on Customer A's trade-in is denied with ERR_NOT_OWNER;
    the trade-in stays DRAFT.

    Design: Corner/rbac/customer_cannot_act_on_other_customers_trade_in
    """
    cat = create_catalog()
    model = create_device_model(cat["id"])
    cust_a = create_customer()
    cust_b = create_customer()
    ti = create_draft_trade_in(cust_a, model, declared_grade="GOOD")

    resp = api.quote_trade_in(ti["id"], make_customer_headers(cust_b["id"]))
    validate_error(resp, "ERR_NOT_OWNER")
    assert validate_success(api.get_trade_in(ti["id"], ADMIN))["status"] == "DRAFT"


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a header the server
    cannot validate, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    A request with no auth headers returns ERR_UNAUTHENTICATED before any other check.

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    resp = api.get_trade_in("00000000-0000-4000-8000-000000000000", make_unauthenticated_headers())
    validate_error(resp, "ERR_UNAUTHENTICATED")


# ─── consistency_model ────────────────────────────────

def test_data_wipe_then_payout_succeeds_immediately(api):
    """PRD §3.7: "if the device model's `category` is among the catalog's
    `data_wipe_required_categories`, a `DataWipeCertificate` with `result` of `PASS`
    must already exist for this trade-in".
    PRD §3.7: "Issuing the payout creates a `Payout` whose `status` is `PAID` and whose
    `amount_cents` equals the trade-in's `final_value_cents` at that moment".

    After recording a PASS data-wipe cert, the very next payout on the same
    wipe-required ACCEPTED trade-in succeeds: trade-in PAID, payout amount 60000.

    Design: Corner/consistency_model/data_wipe_then_payout_succeeds_immediate
    """
    _cat, model, customer = setup_catalog_model_customer(
        catalog_overrides={"data_wipe_required_categories": ["SMARTPHONE"]}
    )
    ti = create_received_trade_in(customer, model, declared_grade="FLAWLESS")
    inspect(ti["id"], "FLAWLESS", verified_defects=[])
    record_data_wipe(ti["id"], method="NIST_PURGE", result="PASS")

    payout = validate_success(api.create_payout(ti["id"], {"method": "ACH"}, FINANCE), expected_status=201)
    assert payout["amount_cents"] == 60000
    assert payout["status"] == "PAID"
    assert validate_success(api.get_trade_in(ti["id"], ADMIN))["status"] == "PAID"
