"""CRUD, RBAC, and immutability tests — corner-queue (B) entity and rbac claims."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    is_valid_uuid, is_iso8601_timestamp,
    create_agency, create_case, create_logged_expense,
    create_agency_payload, create_case_payload, create_family_payload,
    create_birth_parent_payload, create_escrow_payload, create_expense_payload,
    create_home_study_payload,
    TEST_USERS, build_user_headers, make_caseworker_headers,
    make_finance_officer_headers,
)

ADMIN = TEST_USERS["agency_admin_headers"]
SUP = TEST_USERS["supervisor_headers"]
CW = TEST_USERS["caseworker_headers"]
FO = TEST_USERS["finance_officer_headers"]
CA = TEST_USERS["compact_admin_headers"]


# ─── Corner (B): entities / create_case_returns_201_with_computed_defaults ──
def test_create_case_returns_201_with_computed_defaults():
    """PRD §3.1: "At creation the case's phase is INTAKE, its escrow_balance_cents and
    reimbursable_expense_cents are both 0, and its interstate flag is computed: the case
    is interstate exactly when child_state and family_state differ."

    Design: Corner/entities/create_case_returns_201_with_computed_defaults
    """
    agency = create_agency()
    res = api_client.create_case(
        create_case_payload(agency["id"], child_state="NV", family_state="CA"), SUP)
    case = validate_success(res, 201)
    assert case["phase"] == "INTAKE"
    assert case["escrow_balance_cents"] == 0
    assert case["reimbursable_expense_cents"] == 0
    assert case["interstate"] is True


# ─── Corner (B): entities / get_case_returns_stored_entity ────────────────
def test_get_case_returns_stored_entity():
    """PRD §3.1: "Reading a case always returns its freshly reconciled phase,
    escrow_balance_cents, and reimbursable_expense_cents."

    Design: Corner/entities/get_case_returns_stored_entity
    """
    agency = create_agency()
    case = validate_success(api_client.create_case(
        create_case_payload(agency["id"], case_label="C-ret",
                            child_state="CA", family_state="CA"), SUP), 201)
    got = validate_success(api_client.get_case(case["id"], SUP), 200)
    assert got["case_label"] == "C-ret"
    assert got["interstate"] is False


# ─── Corner (B): entities / list_cases_pagination_envelope ────────────────
def test_list_cases_pagination_envelope():
    """PRD §2.3: "Paginated list responses always include limit, offset, total_count, and
    has_more in the meta object of the response envelope."

    Design: Corner/entities/list_cases_pagination_envelope
    """
    agency = create_agency()
    api_client.create_case(create_case_payload(agency["id"], case_label="C-a",
                                              child_state="CA", family_state="CA"), SUP)
    api_client.create_case(create_case_payload(agency["id"], case_label="C-b",
                                              child_state="CA", family_state="CA"), SUP)
    res = api_client.list_cases(SUP, params={"agency_id": agency["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ─── Corner (B): entities / get_case_not_found ────────────────────────────
def test_get_case_not_found():
    """PRD §2.7: "if the addressed resource does not exist, the request is rejected with
    ERR_NOT_FOUND."

    Design: Corner/entities/get_case_not_found
    """
    create_agency()
    res = api_client.get_case("00000000-0000-0000-0000-000000000000", SUP)
    validate_error(res, "ERR_NOT_FOUND")


# ─── Corner (B): entities / create_family_missing_required_field ──────────
def test_create_family_missing_required_field():
    """PRD §2.7: "Required fields must be present and of the declared type ... violations
    are rejected with ERR_INVALID_REQUEST."
    PRD §3.2: "supplying the case_id it belongs to, the primary_applicant_name, the
    family's residence_state, the household_size ..., and the combined annual_income_cents".

    Design: Corner/entities/create_family_missing_required_field
    """
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    payload = create_family_payload(case["id"])
    del payload["annual_income_cents"]
    res = api_client.create_family(payload, CW)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── Corner (B): entities / create_birth_parent_illegal_enum ──────────────
def test_create_birth_parent_illegal_enum():
    """PRD §2.7: "any field constrained to an enumerated set must carry a legal value;
    violations are rejected with ERR_INVALID_REQUEST."
    PRD §3.3: "the parent_role, which is one of BIRTH_MOTHER, BIRTH_FATHER, or
    LEGAL_GUARDIAN."

    Design: Corner/entities/create_birth_parent_illegal_enum
    """
    agency = create_agency()
    res = api_client.create_birth_parent(
        create_birth_parent_payload(agency["id"], parent_role="UNCLE"), CW)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── Corner (B): entities / system_fields_generated_on_create_case ────────
def test_system_fields_generated_on_create_case():
    """PRD §2.4: "The version is a system-managed integer that begins at its initial value
    and increments by one with every modification".

    Design: Corner/entities/system_fields_generated_on_create_case
    """
    agency = create_agency()
    case = validate_success(api_client.create_case(
        create_case_payload(agency["id"], case_label="C-sys",
                            child_state="CA", family_state="CA"), SUP), 201)
    assert case["version"] == 1
    assert is_iso8601_timestamp(case["created_at"])


# ─── Corner (B): entities / escrow_transaction_immutable_no_version ───────
def test_escrow_transaction_immutable_no_version():
    """PRD §2.4: "The escrow transaction is an immutable ledger record: it carries only id
    and created_at. It has no updated_at and no version, because it is never modified after
    it is written."

    Design: Corner/entities/escrow_transaction_immutable_no_version
    """
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    txn = validate_success(api_client.create_escrow_transaction(
        create_escrow_payload(case["id"], case["version"],
                              txn_type="DEPOSIT", amount_cents=500_000), FO), 201)
    got = validate_success(api_client.get_escrow_transaction(txn["id"], FO), 200)
    assert got["txn_type"] == "DEPOSIT"
    assert "version" not in got


# ─── Corner (B): entities / create_family_wrong_parent_case_not_found ─────
def test_create_family_wrong_parent_case_not_found():
    """PRD §2.7: "on create operations, every foreign-key reference supplied in the request
    body — a case_id, a family_id ... — must reference an existing resource; a dangling
    body reference is rejected with ERR_REFERENCED_RESOURCE_NOT_FOUND."

    Design: Corner/entities/create_family_wrong_parent_case_not_found
    """
    create_agency()
    res = api_client.create_family(
        create_family_payload("00000000-0000-0000-0000-000000000000",
                              annual_income_cents=8_000_000), CW)
    validate_error(res, "ERR_REFERENCED_RESOURCE_NOT_FOUND")


# ─── Corner (B): entities / fk_reverse_reachability_expenses_by_case ──────
def test_fk_reverse_reachability_expenses_by_case():
    """PRD §3.7: "Expenses may be retrieved and listed, optionally filtered by case_id."

    Design: Corner/entities/fk_reverse_reachability_expenses_by_case
    """
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    create_logged_expense(case["id"], amount_cents=100_000, category="MEDICAL")
    create_logged_expense(case["id"], amount_cents=200_000, category="LEGAL")
    res = api_client.list_expenses(FO, params={"case_id": case["id"]})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2


# ─── Corner (B): rbac / caseworker_cannot_approve_home_study ──────────────
def test_caseworker_cannot_approve_home_study():
    """PRD §2.1: "If the headers are well-formed but the declared role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED."
    PRD §2.1: "A Supervisor is a senior caseworker who opens cases, approves and returns
    home studies".

    Design: Corner/rbac/caseworker_cannot_approve_home_study
    """
    from test_helpers import create_family, create_under_review_home_study
    agency = create_agency()
    case = create_case(agency["id"], child_state="CA", family_state="CA")
    family = create_family(case["id"], annual_income_cents=8_000_000)
    hs = create_under_review_home_study(case["id"], family["id"])
    res = api_client.approve_home_study(hs["id"], make_caseworker_headers("cw-2"))
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner (B): rbac / compact_admin_cannot_open_case ────────────────────
def test_compact_admin_cannot_open_case():
    """PRD §2.1: "If the headers are well-formed but the declared role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED."
    PRD §2.1: "A Supervisor is a senior caseworker who opens cases".

    Design: Corner/rbac/compact_admin_cannot_open_case
    """
    agency = create_agency()
    res = api_client.create_case(
        create_case_payload(agency["id"], case_label="C-x",
                            child_state="CA", family_state="CA"), CA)
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner (B): rbac / missing_user_context_header ───────────────────────
def test_missing_user_context_header():
    """PRD §2.1: "Every request to the API must be authenticated by two mandatory HTTP
    headers ... If either header is missing or malformed, the request is rejected with
    ERR_MISSING_USER_CONTEXT."

    Design: Corner/rbac/missing_user_context_header
    """
    agency = create_agency()
    # No X-User-Role header (Content-Type only) -> missing user context.
    res = api_client.create_case(
        create_case_payload(agency["id"], case_label="C-x",
                            child_state="CA", family_state="CA"),
        {"Content-Type": "application/json"})
    validate_error(res, "ERR_MISSING_USER_CONTEXT")
