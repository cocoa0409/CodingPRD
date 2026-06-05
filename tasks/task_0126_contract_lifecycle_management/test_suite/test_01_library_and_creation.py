"""Library configuration and contract creation — creation, defaults, system fields,
required/typed inputs, reference validation, listing, and computed deviation_count.

All tests here translate queue B (Corner) instances under section `entities`.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    factories as F, fixtures as FX,
    assert_organization, assert_clause_template, assert_contract,
    assert_contract_version,
    ApiErrorId, NON_EXISTENT_UUID,
)

ADMIN = FX.ADMIN
LIBRARIAN = FX.LIBRARIAN
MGR = FX.MGR


@pytest.fixture
def api():
    return api_client


def test_create_organization_applies_defaults(api):
    """PRD §3.1: "each with a display name, the risk_appetite_threshold discussed
    in §2.8 (default 60, valid range 0 through 100), and an auto_renew_lead_days
    value (default 30, which must be greater than 0)".
    PRD §2.4: "The version field is an integer that starts at its initial value".

    Design: Corner/entities/create_organization_returns_201_with_defaults
    """
    resp = api.create_organization({"name": "DefOrg"}, ADMIN)
    data = validate_success(resp, 201)
    assert_organization(data)
    assert data["risk_appetite_threshold"] == 60, "threshold must default to 60"
    assert data["auto_renew_lead_days"] == 30, "lead-days must default to 30"
    assert data["version"] == 1, "version must start at 1"


def test_get_contract_unknown_id_returns_contract_not_found(api):
    """PRD §2.6: "if no contract with that id exists, the request fails immediately
    with ERR_CONTRACT_NOT_FOUND before the child is even consulted."

    Design: Corner/entities/get_contract_not_found_returns_404
    """
    resp = api.get_contract("00000000-0000-4000-8000-000000000000", MGR)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND.value, 404)


def test_create_clause_template_missing_risk_weight_rejected(api):
    """PRD §2.6: "all required input fields must be present and well-typed... A
    missing required field, a value of the wrong type, or an enum value that is not
    a declared member is rejected with ERR_INVALID_REQUEST."

    Design: Corner/entities/create_clause_template_missing_required_field_returns_invalid_request
    """
    org = FX.create_organization(api)
    resp = api.create_clause_template(
        {"organization_id": org["id"], "clause_key": "X", "category": "OTHER",
         "standard_text": "s"},  # risk_weight omitted
        LIBRARIAN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_clause_template_invalid_category_rejected(api):
    """PRD §2.6: "any field declared as an enumeration must hold one of its declared
    members. A missing required field, a value of the wrong type, or an enum value
    that is not a declared member is rejected with ERR_INVALID_REQUEST."

    Design: Corner/entities/create_clause_template_invalid_enum_category_returns_invalid_request
    """
    org = FX.create_organization(api)
    resp = api.create_clause_template(
        {"organization_id": org["id"], "clause_key": "X", "category": "BOGUS",
         "standard_text": "s", "risk_weight": 5},
        LIBRARIAN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_contract_defaults_term_and_autorenew_from_template(api):
    """PRD §3.2: "The manager may supply term_months and auto_renew; when either is
    omitted it is filled from the template's default_term_months and
    auto_renew_default respectively."

    Design: Corner/entities/create_contract_defaults_term_and_autorenew_from_template
    """
    org = FX.create_organization(api)
    clause = FX.create_clause(api, org["id"], clause_key="K")
    template = FX.create_contract_template(
        api, org["id"], [clause["id"]], default_term_months=24, auto_renew_default=True
    )
    resp = api.create_contract(
        {"organization_id": org["id"], "contract_template_id": template["id"],
         "counterparty_name": "CP", "title": "C"},  # term_months / auto_renew omitted
        MGR,
    )
    data = validate_success(resp, 201)
    assert_contract(data)
    assert data["term_months"] == 24, "term_months must default from template (24)"
    assert data["auto_renew"] is True, "auto_renew must default from template (true)"


def test_create_contract_sets_system_fields(api):
    """PRD §3.2: "On creation the caller's X-User-ID is recorded as the contract's
    drafter_user_id... the contract's current_version_id, effective_date, and
    expiry_date all begin null while risk_score begins at 0 and renewal_cycle_index
    at 0."
    PRD §2.4: "The version field is an integer that starts at its initial value".

    Design: Corner/entities/contract_system_fields_generated_input_ignored
    """
    org = FX.create_organization(api)
    clause = FX.create_clause(api, org["id"], clause_key="K")
    template = FX.create_contract_template(api, org["id"], [clause["id"]])
    resp = api.create_contract(
        {"organization_id": org["id"], "contract_template_id": template["id"],
         "counterparty_name": "CP", "title": "C", "term_months": 12, "auto_renew": False},
        FX._mgr("drafter-7"),
    )
    data = validate_success(resp, 201)
    assert_contract(data)
    assert data["status"] == "DRAFT", "new contract must start DRAFT"
    assert data["risk_score"] == 0, "new contract risk_score must be 0"
    assert data["drafter_user_id"] == "drafter-7", "drafter_user_id must be the caller's X-User-ID"
    assert data["version"] == 1, "version must start at 1"


def test_create_contract_unknown_template_returns_reference_not_found(api):
    """PRD §2.6: "On any create endpoint that carries a foreign key in its body, the
    referenced resource must exist, be of the correct type, and belong to the same
    organization as the resource being created; otherwise the request fails with
    ERR_REFERENCE_NOT_FOUND."

    Design: Corner/entities/create_contract_unknown_template_returns_reference_not_found
    """
    org = FX.create_organization(api)
    resp = api.create_contract(
        {"organization_id": org["id"],
         "contract_template_id": "11111111-1111-4111-8111-111111111111",
         "counterparty_name": "CP", "title": "C", "term_months": 12, "auto_renew": False},
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, 404)


def test_list_clause_templates_pagination_envelope(api):
    """PRD §2.3: "Every list response carries limit, offset, total_count, and
    has_more in the meta object of the envelope."

    Design: Corner/entities/list_clause_templates_pagination_envelope
    """
    org = FX.create_organization(api)
    FX.create_clause(api, org["id"], clause_key="K1")
    FX.create_clause(api, org["id"], clause_key="K2")
    resp = api.list_clause_templates(LIBRARIAN, params={"organization_id": org["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true with limit 1 over 2 rows"
    assert len(data) == 1, "limit 1 must return exactly one row"


def test_contract_version_computes_deviation_count(api):
    """PRD §3.2: "The server computes deviation_count as the number of clause entries
    whose is_deviation is true".

    Design: Corner/entities/contract_version_computed_deviation_count
    """
    setup = FX.setup_draft_contract_with_version(
        api,
        clauses_spec=[
            {"clause_index": 0, "is_deviation": True, "text": "d"},
            {"clause_index": 1, "is_deviation": True, "text": "d"},
            {"clause_index": 2, "is_deviation": True, "text": "d"},
            {"clause_index": 3, "is_deviation": False, "text": "s"},
        ],
        clause_defs=[
            {"clause_key": "A", "risk_weight": 1},
            {"clause_key": "B", "risk_weight": 1},
            {"clause_key": "C", "risk_weight": 1},
            {"clause_key": "D", "risk_weight": 1},
        ],
    )
    version = setup["version"]
    assert_contract_version(version)
    assert version["deviation_count"] == 3, \
        f"deviation_count must count is_deviation=true entries (3), got {version['deviation_count']}"


def test_clause_template_risk_weight_out_of_range_rejected(api):
    """PRD §3.1: "The risk_weight must lie between 0 and 40 inclusive; a value
    outside that range is rejected with ERR_VALIDATION_RANGE."

    Design: Corner/entities/clause_template_create_out_of_range_risk_weight
    """
    org = FX.create_organization(api)
    resp = api.create_clause_template(
        {"organization_id": org["id"], "clause_key": "K", "category": "OTHER",
         "standard_text": "s", "risk_weight": 99},
        LIBRARIAN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION_RANGE.value, 422)
