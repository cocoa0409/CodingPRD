"""Resource CRUD, fee-plan completeness, listing/pagination/filtering, webhook idempotency,
ledger immutability, and role-based access control.

Covers corner queue Entities, Validations, Endpoints, Errors, RBAC, and Cross-Cutting
(ledger filter/pagination) instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    set_clock,
    create_flat_plan, create_approved_merchant, create_captured_charge,
    open_and_settle_batch, register_merchant,
    make_merchant_user_headers,
    TEST_USERS,
)

OPERATOR = TEST_USERS["platform_operator_headers"]
OFFICER = TEST_USERS["underwriting_officer_headers"]

NON_EXISTENT = "00000000-0000-0000-0000-000000000000"


# --- Entities: fee plan ---

def test_create_flat_fee_plan_echoes_fields(api):
    """PRD §3.1: "A `FLAT` plan prices every capture with a single percentage component plus a
    fixed component, and therefore must provide both `flat_pct_bps` (the percentage in basis
    points, where 290 means 2.90%) and `flat_fixed_cents` (the per-transaction fixed amount in
    cents)."

    Design: Corner/Entities/corner_fee_plan_creation_returns_envelope_and_all_fields
    """
    resp = api.create_fee_plan(
        {"name": "Standard Flat", "pricing_model": "FLAT", "flat_pct_bps": 290,
         "flat_fixed_cents": 30, "chargeback_fee_cents": 1500}
    )
    data = validate_success(resp, expected_status=201)
    assert data["pricing_model"] == "FLAT"
    assert data["flat_pct_bps"] == 290
    assert data["flat_fixed_cents"] == 30
    assert data["chargeback_fee_cents"] == 1500
    assert isinstance(data["id"], str) and len(data["id"]) > 0


def test_fee_plan_default_chargeback_fee_is_1500(api):
    """PRD §3.1: "a `chargeback_fee_cents` — the non-refundable fee debited from a merchant
    when a dispute opens, defaulting to 1500 cents when not supplied."

    Design: Corner/Entities/corner_fee_plan_default_chargeback_fee_applied
    """
    resp = api.create_fee_plan({"name": "No CB Fee", "pricing_model": "FLAT",
                                "flat_pct_bps": 200, "flat_fixed_cents": 25})
    data = validate_success(resp, expected_status=201)
    assert data["chargeback_fee_cents"] == 1500


# --- Entities: merchant ---

def test_merchant_registration_defaults_and_initial_status(api):
    """PRD §3.2: "Registration creates the merchant with `onboarding_status` set to
    `PENDING_REVIEW`".
    PRD §3.2: "The registrant may also choose a `payout_method`, either `BANK_ACCOUNT` (the
    default) or `DEBIT_CARD`."
    PRD §3.2: "its `reserve_rate_bps` and `available_balance_cents` and `reserved_balance_cents`
    are 0".

    Design: Corner/Entities/corner_merchant_registration_defaults_and_initial_status
    """
    plan = create_flat_plan()
    resp = api.create_merchant({"legal_name": "New Co", "mcc": "5812",
                                "fee_plan_id": plan["id"], "requested_monthly_volume_cents": 50000})
    data = validate_success(resp, expected_status=201)
    assert data["onboarding_status"] == "PENDING_REVIEW"
    assert data["payout_method"] == "BANK_ACCOUNT"
    assert data["available_balance_cents"] == 0
    assert data["reserved_balance_cents"] == 0


def test_get_merchant_returns_stored_entity(api):
    """PRD §3.2: "A prospective merchant registers by supplying its `legal_name`, its `mcc` (a
    Merchant Category Code that must be exactly four ASCII digits), the `fee_plan_id` of the
    plan it will price under".

    Design: Corner/Entities/corner_merchant_retrieval_returns_stored_entity
    """
    plan = create_flat_plan()
    merchant = register_merchant(plan["id"], legal_name="Lookup Co", mcc="5812")
    data = validate_success(api.get_merchant(merchant["id"], OPERATOR))
    assert data["id"] == merchant["id"]
    assert data["legal_name"] == "Lookup Co"
    assert data["mcc"] == "5812"


def test_get_nonexistent_merchant_returns_not_found(api):
    """PRD §2.7: "the server validates each path identifier left to right and rejects the first
    one that does not resolve to an existing resource with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/Entities/corner_merchant_not_found_returns_404
    """
    resp = api.get_merchant(NON_EXISTENT, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_list_merchants_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned".
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope."

    Design: Corner/Entities/corner_merchant_listing_pagination_envelope
    """
    plan = create_flat_plan()
    for name in ("A Co", "B Co", "C Co"):
        register_merchant(plan["id"], legal_name=name, requested_monthly_volume_cents=10000)
    data, meta = validate_paginated(api.list_merchants(OPERATOR, params={"limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_list_merchants_filter_by_fee_plan(api):
    """PRD §4 (endpoint): "List merchants, filterable by fee plan and onboarding status".

    Design: Corner/Entities/corner_merchant_list_filter_by_fee_plan
    """
    plan_a = create_flat_plan(name="Plan A", flat_pct_bps=290, flat_fixed_cents=30)
    plan_b = create_flat_plan(name="Plan B", flat_pct_bps=100, flat_fixed_cents=10)
    m_a = register_merchant(plan_a["id"], legal_name="On A", requested_monthly_volume_cents=10000)
    m_b = register_merchant(plan_b["id"], legal_name="On B", requested_monthly_volume_cents=10000)
    data, _ = validate_paginated(api.list_merchants(OPERATOR, params={"fee_plan_id": plan_a["id"]}))
    ids = [m["id"] for m in data]
    assert m_a["id"] in ids
    assert m_b["id"] not in ids
    for m in data:
        assert m["fee_plan_id"] == plan_a["id"]


def test_merchant_missing_required_legal_name_rejected(api):
    """PRD §2.8: "A request whose body is malformed, missing a required field, or carries a
    value of the wrong scalar type is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/Entities/corner_merchant_missing_required_legal_name
    """
    plan = create_flat_plan()
    resp = api.create_merchant({"mcc": "5812", "fee_plan_id": plan["id"],
                                "requested_monthly_volume_cents": 10000})
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_merchant_dangling_fee_plan_fk_rejected(api):
    """PRD §2.7: "any foreign-key field carried in a request body — such as `fee_plan_id` at
    merchant registration, or the `charge_id` and `merchant_id` linkages on creation endpoints
    — must reference an existing resource; a dangling body foreign key is rejected with
    `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/Entities/corner_merchant_fk_fee_plan_not_found
    """
    resp = api.create_merchant({"legal_name": "Dangling", "mcc": "5812",
                                "fee_plan_id": NON_EXISTENT, "requested_monthly_volume_cents": 10000})
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)


def test_ledger_entries_are_immutable_audit_records(api):
    """PRD §2.4: "Two entities are append-only audit records and deliberately carry **only**
    `id` and `created_at` — they have no `updated_at` and no `version`: the `LedgerEntry` and
    the `WebhookEvent`."

    Design: Corner/Entities/corner_ledger_entry_immutable_no_update_endpoint
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="MEDIUM")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=10000)
    open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    data, _ = validate_paginated(api.list_ledger_entries(merchant["id"], OPERATOR))
    assert any(e["entry_type"] == "RESERVE_HOLD" for e in data)
    for e in data:
        assert "version" not in e, "LedgerEntry is append-only; must not carry version"
        assert "updated_at" not in e, "LedgerEntry is append-only; must not carry updated_at"


# --- Validations: fee plan completeness, no eligible charges ---

def test_flat_plan_missing_required_fields_rejected(api):
    """PRD §3.1: "The pricing model determines which fields the plan must carry, and a plan
    that omits the fields its model requires is rejected with `ERR_FEE_PLAN_INCOMPLETE`
    (HTTP 422)."

    Design: Corner/Validations/corner_fee_plan_incomplete_flat_missing_fields
    """
    resp = api.create_fee_plan({"name": "Bad Flat", "pricing_model": "FLAT"})
    validate_error(resp, ApiErrorId.ERR_FEE_PLAN_INCOMPLETE)


def test_interchange_plus_plan_missing_markup_rejected(api):
    """PRD §3.1: "An `INTERCHANGE_PLUS` plan passes the network interchange cost straight
    through and adds a platform markup on top, and therefore must provide its markup fields:
    `markup_pct_bps` (the platform markup in basis points applied to the captured amount) and
    `markup_fixed_cents` (the platform per-transaction fixed markup in cents)."

    Design: Corner/Validations/corner_fee_plan_incomplete_interchange_missing_markup
    """
    resp = api.create_fee_plan({"name": "Bad IcPlus", "pricing_model": "INTERCHANGE_PLUS"})
    validate_error(resp, ApiErrorId.ERR_FEE_PLAN_INCOMPLETE)


def test_open_batch_with_no_eligible_charges_rejected(api):
    """PRD §3.7: "Opening a batch is permitted only when the merchant's `onboarding_status` is
    `APPROVED` or `SUSPENDED`, and only when at least one charge with `auth_status` `CAPTURED`
    and `settlement_status` `PENDING` exists for that merchant; if no such eligible charge
    exists, the open is rejected with `ERR_NO_ELIGIBLE_CHARGES` (HTTP 409)."

    Design: Corner/Validations/corner_settlement_batch_no_eligible_charges
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    resp = api.create_settlement_batch(merchant["id"], {"business_date": "2026-01-01"}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CHARGES)


# --- Endpoints: webhook idempotency ---

def test_webhook_emit_is_idempotent_on_key(api):
    """PRD §3.11: "Emission is idempotent on the key: a repeated emit carrying an
    `idempotency_key` that has already been used returns the existing event rather than
    creating a new one."

    Design: Corner/Endpoints/corner_webhook_idempotent_emit_returns_existing
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    payload = {"event_type": "DISPUTE_OPENED", "source_id": "abc", "idempotency_key": "key-123"}
    first = validate_success(api.emit_webhook_event(merchant["id"], payload, OPERATOR), expected_status=201)
    second = validate_success(api.emit_webhook_event(merchant["id"], payload, OPERATOR))
    assert second["id"] == first["id"], "repeated emit must return the existing event"


# --- Errors ---

def test_register_with_invalid_payout_method_enum_rejected(api):
    """PRD §2.8: "A request that supplies an enumerated field with a value outside its
    permitted set is rejected with `ERR_INVALID_ENUM` (HTTP 422)."
    PRD §2.8: "a merchant's `payout_method` is either `BANK_ACCOUNT` or `DEBIT_CARD`".

    Design: Corner/Errors/corner_err_invalid_enum_on_merchant_register
    """
    plan = create_flat_plan()
    resp = api.create_merchant({"legal_name": "Enum Co", "mcc": "5812", "fee_plan_id": plan["id"],
                                "requested_monthly_volume_cents": 10000, "payout_method": "CRYPTO"})
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


def test_refund_on_nonexistent_charge_returns_not_found(api):
    """PRD §2.7: "the server validates each path identifier left to right and rejects the first
    one that does not resolve to an existing resource with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/Errors/corner_err_fk_not_found_refund_on_missing_charge
    """
    headers = make_merchant_user_headers("00000000-0000-0000-0000-000000000001")
    resp = api.create_refund(NON_EXISTENT, {"amount_cents": 1000}, headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# --- RBAC ---

def test_merchant_user_cannot_settle_batch(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/RBAC/corner_merchant_user_cannot_settle_batch
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=10000)
    batch = validate_success(api.create_settlement_batch(merchant["id"], {"business_date": "2026-01-01"}, OPERATOR), expected_status=201)
    headers = make_merchant_user_headers(merchant["id"])
    resp = api.settle_batch(batch["id"], {"expected_merchant_version": version}, headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_underwriting_officer_cannot_create_charge(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/RBAC/corner_underwriting_officer_cannot_create_charge
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    resp = api.create_charge(merchant["id"], {"auth_amount_cents": 5000, "card_last4": "4242"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_merchant_user_cannot_access_other_merchants_charge(api):
    """PRD §2.1: "A `MerchantUser` reaching a resource owned by another merchant is rejected
    with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/RBAC/corner_merchant_user_cannot_access_other_merchants_charge
    """
    plan = create_flat_plan()
    m_a, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW",
                                      merchant_overrides={"legal_name": "A Co"})
    m_b, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW",
                                      merchant_overrides={"legal_name": "B Co"})
    from test_helpers import create_authorized_charge
    charge_b = create_authorized_charge(m_b["id"], auth_amount_cents=5000)
    headers_a = make_merchant_user_headers(m_a["id"])
    resp = api.get_charge(charge_b["id"], headers_a)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_protected_read_without_headers_unauthenticated(api):
    """PRD §2.1: "When either header is missing or malformed on a protected endpoint, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/RBAC/corner_unauthenticated_missing_headers_rejected
    """
    plan = create_flat_plan()
    merchant = register_merchant(plan["id"], legal_name="Auth Co")
    # No X-User-ID / X-User-Role headers at all.
    resp = api.get_merchant(merchant["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# --- Cross-Cutting: ledger filter + pagination ---

def test_ledger_filter_by_entry_type_pagination(api):
    """PRD §3.11: "Every merchant's ledger is readable as a list filterable by `account`,
    `entry_type`, and `source_type`".
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope."

    Design: Corner/Cross-Cutting Complexity Layers/corner_ledger_filter_by_entry_type_pagination
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="MEDIUM")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=10000)
    open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    data, meta = validate_paginated(
        api.list_ledger_entries(merchant["id"], OPERATOR, params={"entry_type": "RESERVE_HOLD", "limit": 10})
    )
    for e in data:
        assert e["entry_type"] == "RESERVE_HOLD"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
