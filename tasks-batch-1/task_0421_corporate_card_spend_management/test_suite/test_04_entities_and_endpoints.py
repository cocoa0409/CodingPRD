"""Entity creation, defaults, system-field minting, immutability, not-found,
listing/pagination, and FK-filtered reads.

Corner queue: entities, endpoints.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiClient, ApiErrorId, NON_EXISTENT_UUID,
    create_company, create_employee, create_spend_policy, create_card,
    setup_company_with_card, capture_transaction,
)
from test_helpers import factories as F
from test_helpers.test_users import make_finance_admin_headers, make_cardholder_headers

ADMIN = make_finance_admin_headers()


# ===========================================================================
# Corner: entities / create_company_returns_201_with_defaults_and_cascades
# ===========================================================================
def test_create_company_defaults_and_cascades(api: ApiClient):
    """PRD §3.1: "A newly created company starts in status ACTIVE, with
    available_credit_cents equal to its credit_limit_cents and clock_utc null. Two
    cascades fire at creation: a RewardAccount is created for the company with all
    balances at zero, and the company's first statement is opened with cycle_index 1"
    PRD §3.1: "Optionally the request may set currency (defaulting to USD ...)"

    POST /companies mints USD/ACTIVE/available==limit and auto-creates the
    RewardAccount and a cycle-1 OPEN statement.

    Design: Corner/entities/create_company_returns_201_with_defaults_and_cascades
    """
    company = validate_success(api.create_company(
        F.create_company_payload(legal_name="Boot Co", credit_limit_cents=500000,
                                 billing_model="CREDIT"), ADMIN), expected_status=201)
    assert company["currency"] == "USD", f"currency defaults USD, got {company['currency']}"
    assert company["status"] == "ACTIVE"
    assert company["available_credit_cents"] == 500000
    ra_list, _ = validate_paginated(api.list_reward_accounts(ADMIN, params={"company_id": company["id"]}))
    assert len(ra_list) == 1, "exactly one RewardAccount auto-created"
    stmts, _ = validate_paginated(api.list_statements(ADMIN, params={"company_id": company["id"]}))
    assert len(stmts) == 1, "exactly one OPEN statement auto-created"
    assert stmts[0]["cycle_index"] == 1, f"first cycle_index 1, got {stmts[0]['cycle_index']}"
    assert stmts[0]["status"] == "OPEN", f"first statement OPEN, got {stmts[0]['status']}"


# ===========================================================================
# Corner: entities / create_company_missing_billing_model_returns_validation
# ===========================================================================
def test_create_company_missing_billing_model_rejected(api: ApiClient):
    """PRD §3.1: "A FinanceAdmin brings a company into existence by supplying its
    legal_name, its credit_limit_cents ..., and its billing_model, which is one of
    CHARGE ... or CREDIT"
    PRD §2.10: "(4) body well-formedness — required fields present and enum values
    valid — ERR_VALIDATION"

    Omitting the required billing_model is rejected with ERR_VALIDATION.

    Design: Corner/entities/create_company_missing_billing_model_returns_validation
    """
    resp = api.create_company({"legal_name": "No Model", "credit_limit_cents": 500000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Corner: entities / get_card_nonexistent_returns_not_found
# ===========================================================================
def test_get_card_nonexistent_returns_not_found(api: ApiClient):
    """PRD §2.4: "A reference to a non-existent company or child resource yields
    ERR_NOT_FOUND."
    PRD §2.10: "(3) existence of all referenced resources, ERR_NOT_FOUND"

    GET /cards/{id} with a random UUID returns ERR_NOT_FOUND.

    Design: Corner/entities/get_card_nonexistent_returns_not_found
    """
    resp = api.get_card(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Corner: entities / system_fields_ignored_on_create_company
# ===========================================================================
def test_system_fields_minted_on_create_company(api: ApiClient):
    """PRD §3.1: "A newly created company starts in status ACTIVE, with
    available_credit_cents equal to its credit_limit_cents and clock_utc null."

    The server mints status=ACTIVE and available_credit_cents=credit_limit_cents
    regardless of the request body.

    Design: Corner/entities/system_fields_ignored_on_create_company
    """
    company = validate_success(api.create_company(
        F.create_company_payload(legal_name="Sys Co", credit_limit_cents=700000,
                                 billing_model="CHARGE"), ADMIN), expected_status=201)
    assert company["status"] == "ACTIVE", f"status minted ACTIVE, got {company['status']}"
    assert company["available_credit_cents"] == 700000, (
        f"available_credit minted == limit, got {company['available_credit_cents']}")


# ===========================================================================
# Corner: entities / duplicate_employee_email_among_active_rejected
# ===========================================================================
def test_duplicate_employee_email_rejected(api: ApiClient):
    """PRD §3.1: "an employee's email must be unique among the company's ACTIVE
    employees, and a reused email is rejected with ERR_DUPLICATE_EMAIL."

    A second ACTIVE employee with the same email in the same company is rejected.

    Design: Corner/entities/duplicate_employee_email_among_active_rejected
    """
    company = create_company(billing_model="CHARGE", credit_limit_cents=500000)
    create_employee(company["id"], "dup@acme.com", "First", "CARDHOLDER")
    resp = api.create_employee(
        F.create_employee_payload(company["id"], email="dup@acme.com",
                                  full_name="Second", employee_role="CARDHOLDER"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


# ===========================================================================
# Corner: entities / receipt_immutable_no_version_field
# ===========================================================================
def test_receipt_immutable_carries_no_version(api: ApiClient):
    """PRD §2.4: "One entity is the exception: a Receipt is immutable once created and
    therefore carries only id and created_at. A Receipt has no updated_at field and no
    version field."

    A fetched Receipt exposes id/created_at and its computed match_result, but no
    version field.

    Design: Corner/entities/receipt_immutable_no_version_field
    """
    base = setup_company_with_card()
    ch = base["cardholder_headers"]
    tx = capture_transaction(base["card"]["id"], headers=ch, amount_cents=10000)
    rcpt = validate_success(api.upload_receipt(
        tx["id"], F.receipt_payload(10000, "Merchant"), ch), expected_status=201)
    fetched = validate_success(api.get_receipt(rcpt["id"], ADMIN))
    assert fetched["match_result"] == "MATCH", f"match_result MATCH, got {fetched['match_result']}"
    assert "version" not in fetched, "Receipt must not carry a version field"
    assert "updated_at" not in fetched, "Receipt must not carry an updated_at field"


# ===========================================================================
# Corner: entities / list_companies_pagination_envelope
# ===========================================================================
def test_list_companies_pagination_envelope(api: ApiClient):
    """PRD §2.3: "Every list response includes these four fields in the meta object of
    the envelope: limit, offset, total_count, and has_more."

    GET /companies returns a paginated array envelope with total_count >= 2 and a
    boolean has_more.

    Design: Corner/entities/list_companies_pagination_envelope
    """
    create_company(legal_name="L1", credit_limit_cents=100000, billing_model="CHARGE")
    create_company(legal_name="L2", credit_limit_cents=100000, billing_model="CHARGE")
    data, meta = validate_paginated(api.list_companies(ADMIN))
    assert isinstance(data, list)
    assert meta["total_count"] >= 2, f"total_count >= 2, got {meta['total_count']}"
    assert isinstance(meta["has_more"], bool), "has_more must be boolean"


# ===========================================================================
# Corner: endpoints / list_cards_filtered_by_employee_id
# ===========================================================================
def test_list_cards_filtered_by_employee_id(api: ApiClient):
    """PRD §4: "employee_id (cards, reimbursement claims, spend authorizations)"
    PRD §2.3: "Every list response includes these four fields in the meta object of
    the envelope: limit, offset, total_count, and has_more."

    GET /cards?employee_id=<emp> returns only the card whose employee_id matches.

    Design: Corner/endpoints/list_cards_filtered_by_employee_id
    """
    company = create_company(billing_model="CHARGE", credit_limit_cents=5_000_000)
    e_a = create_employee(company["id"], "ea@acme.com", "EA", "CARDHOLDER")
    e_b = create_employee(company["id"], "eb@acme.com", "EB", "CARDHOLDER")
    pol = create_spend_policy(company["id"])
    create_card(company["id"], e_a["id"], pol["id"])
    create_card(company["id"], e_b["id"], pol["id"])
    data, meta = validate_paginated(api.list_cards(ADMIN, params={"employee_id": e_a["id"]}))
    assert meta["total_count"] == 1, f"exactly one card for e_a, got {meta['total_count']}"
    assert all(c["employee_id"] == e_a["id"] for c in data), (
        "every returned card has employee_id == e_a")
