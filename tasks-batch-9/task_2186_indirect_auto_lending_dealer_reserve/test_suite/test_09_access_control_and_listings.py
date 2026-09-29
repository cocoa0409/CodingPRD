"""Authentication, role and scope gating, entity-specific 404s, and listings."""
from test_helpers import (
    ADMIN, ANALYST, COMPLIANCE, FUNDER, ApiErrorId, api_client, book_contract,
    build_user_headers, dealer_status_action, make_dealer_principal_headers,
    onboard_dealer, read_application, read_dealer, setup_funded_contract,
    setup_program, submit_and_approve, submit_application, validate_error,
    validate_paginated, validate_success,
)

UNKNOWN_IDS = {
    "agreement": "11111111-1111-4111-8111-111111111111",
    "rate_sheet": "22222222-2222-4222-8222-222222222222",
    "application": "33333333-3333-4333-8333-333333333333",
    "contract": "44444444-4444-4444-8444-444444444444",
    "document": "55555555-5555-4555-8555-555555555555",
    "buyback": "66666666-6666-4666-8666-666666666666",
    "scorecard": "77777777-7777-4777-8777-777777777777",
    "review": "88888888-8888-4888-8888-888888888888",
    "reserve_entry": "99999999-9999-4999-8999-999999999999",
}


def test_a_dealer_principal_may_not_decision_an_application(api):
    """PRD 2.1: "A `CreditAnalyst` is the underwriter; decisioning an application is
    theirs alone."
    PRD 2.1: "When a request's role is not listed for the endpoint it addresses, the
    response is `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/dealer_principal_cannot_decision_an_application
    """
    program = setup_program()
    application = submit_application(
        program["dealer_id"], applicant_reference="APP-rb",
        monthly_debt_cents=180000, amount_financed_cents=1000000,
        collateral_value_cents=1000000,
    )

    response = api.decision_application(
        application["id"], {"outcome": "APPROVE"}, program["dealer_headers"]
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    unchanged = read_application(application["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["decisioned_by_user_id"] is None


def test_a_dealer_principal_may_not_act_for_another_dealership(api):
    """PRD 2.1: "`DealerPrincipal` is the only entity-backed role: when
    `X-User-Role` is `DealerPrincipal`, `X-User-ID` is the `id` of the acting
    `Dealer`, and ownership checks on any resource that references a dealership
    compare that resource's dealer foreign key to `X-User-ID`."
    PRD 2.1: "A `DealerPrincipal` who addresses or names a dealership other than
    their own is rejected with `ERR_DEALER_SCOPE_VIOLATION` (HTTP 403)"

    Design: Corner/rbac/dealer_principal_cannot_submit_for_another_dealer
    """
    program = setup_program()
    intruder = onboard_dealer(legal_name="Second Street Motors", state_code="NV")

    response = api.create_application(
        {
            "dealer_id": program["dealer_id"],
            "applicant_reference": "APP-SCOPE",
            "monitoring_cohort": "CONTROL",
            "credit_score": 725,
            "monthly_income_cents": 600000,
            "monthly_debt_cents": 180000,
            "amount_financed_cents": 1000000,
            "collateral_value_cents": 1000000,
            "term_months": 60,
            "vehicle_model_year": 2023,
            "requested_apr_bps": 749,
        },
        make_dealer_principal_headers(intruder["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DEALER_SCOPE_VIOLATION.value, 403)

    _, meta = validate_paginated(
        api.list_applications(ADMIN, params={"dealer_id": program["dealer_id"]})
    )
    assert meta["total_count"] == 0


def test_missing_or_undeclared_auth_headers_are_unauthenticated(api):
    """PRD 2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the role that
    principal is acting in. If either header is absent, empty, or if `X-User-Role`
    does not name one of the five roles defined below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.1: "The five roles are `PortfolioAdmin`, `CreditAnalyst`,
    `FundingSpecialist`, `DealerPrincipal`, and `ComplianceOfficer`."

    Design: Corner/rbac/dealer_get_missing_auth_headers_returns_unauthenticated
    """
    program = setup_program()

    anonymous = api.get_dealer(program["dealer_id"], {})
    validate_error(anonymous, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert anonymous.json()["response_type"] == "error"

    undeclared = api.get_dealer(
        program["dealer_id"], build_user_headers("auditor-1", "Auditor")
    )
    validate_error(undeclared, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_action_level_role_gates_split_the_dealer_status_endpoint(api):
    """PRD 2.1: "On the dealer status endpoint, the actions `SUSPEND`, `REINSTATE`,
    and `TERMINATE` require `PortfolioAdmin`, while `COMPLIANCE_HOLD` and
    `RELEASE_HOLD` require `ComplianceOfficer`; a `ComplianceOfficer` attempting
    `TERMINATE`, or a `PortfolioAdmin` attempting `RELEASE_HOLD`, receives
    `ERR_FORBIDDEN_ROLE`."
    PRD 3.9: "`SUSPEND` is permitted only from `ACTIVE`. The dealership advances
    `ACTIVE → SUSPENDED`"

    Design: Corner/rbac/portfolio_admin_cannot_place_compliance_hold
    """
    program = setup_program()

    response = api.dealer_status_action(
        program["dealer_id"],
        {"action": "COMPLIANCE_HOLD", "reason": "ADMIN_TRIES"}, ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    assert read_dealer(program["dealer_id"])["compliance_hold"] is False

    suspended = validate_success(
        api.dealer_status_action(
            program["dealer_id"], {"action": "SUSPEND", "reason": "AUDIT"}, ADMIN
        ),
        200,
    )
    assert suspended["status"] == "SUSPENDED"


def test_every_role_may_read_a_shared_get_endpoint(api):
    """PRD 2.1: "Every role may read through every `GET` endpoint."
    PRD 3.5: "Two ledger entries are posted, **in this order**: first a
    `PARTICIPATION_ACCRUAL` entry crediting `reserve_accrued_cents`, then an
    `INCENTIVE_ACCRUAL` entry crediting `incentive_accrued_cents`."

    Design: Corner/rbac/every_role_may_read_shared_get_endpoints
    """
    program = setup_program()
    funded = setup_funded_contract(program, doc_prefix="IMG-sh")
    contract_id = funded["contract"]["id"]

    for headers in (ADMIN, ANALYST, FUNDER, COMPLIANCE, program["dealer_headers"]):
        contract = validate_success(api.get_contract(contract_id, headers), 200)
        assert contract["id"] == contract_id
        assert contract["reserve_accrued_cents"] == 154055


def test_each_resource_family_answers_with_its_own_not_found_code(api):
    """PRD 2.7: "Each entity type has its own not-found code:
    `ERR_DEALER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_RATE_SHEET_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
    `ERR_BUYBACK_NOT_FOUND`, `ERR_SCORECARD_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, and
    `ERR_RESERVE_ENTRY_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/unknown_ids_return_entity_specific_not_found_codes
    """
    setup_program()

    probes = [
        (api.get_agreement(UNKNOWN_IDS["agreement"], ADMIN),
         ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value),
        (api.get_rate_sheet(UNKNOWN_IDS["rate_sheet"], ADMIN),
         ApiErrorId.ERR_RATE_SHEET_NOT_FOUND.value),
        (api.get_application(UNKNOWN_IDS["application"], ADMIN),
         ApiErrorId.ERR_APPLICATION_NOT_FOUND.value),
        (api.get_contract(UNKNOWN_IDS["contract"], ADMIN),
         ApiErrorId.ERR_CONTRACT_NOT_FOUND.value),
        (api.verify_document(UNKNOWN_IDS["document"], {"outcome": "VERIFY"}, FUNDER),
         ApiErrorId.ERR_DOCUMENT_NOT_FOUND.value),
        (api.get_buyback_demand(UNKNOWN_IDS["buyback"], ADMIN),
         ApiErrorId.ERR_BUYBACK_NOT_FOUND.value),
        (api.finalize_scorecard(UNKNOWN_IDS["scorecard"], ADMIN),
         ApiErrorId.ERR_SCORECARD_NOT_FOUND.value),
        (api.get_fair_lending_review(UNKNOWN_IDS["review"], COMPLIANCE),
         ApiErrorId.ERR_REVIEW_NOT_FOUND.value),
        (api.get_reserve_entry(UNKNOWN_IDS["reserve_entry"], ADMIN),
         ApiErrorId.ERR_RESERVE_ENTRY_NOT_FOUND.value),
    ]
    for response, expected_error_id in probes:
        validate_error(response, expected_error_id, 404)
        assert response.json()["response_type"] == "error"


def test_contract_listing_reports_the_pagination_envelope(api):
    """PRD 2.3: "Every list endpoint accepts two optional query parameters, `limit`
    and `offset`. `limit` defaults to 10 when omitted, has a minimum accepted value of
    1 and a maximum accepted value of 100."
    PRD 2.3: "List responses populate four pagination fields inside `meta`: `limit`
    and `offset` echo the effective values used for the query, `total_count` reports
    how many records match the filter before pagination is applied, and `has_more` is
    true when records remain beyond the current page."

    Design: Corner/entities/contracts_list_pagination_envelope_fields
    """
    program = setup_program()
    setup_funded_contract(
        program,
        application_overrides={
            "applicant_reference": "APP-p1", "monthly_debt_cents": 180000,
            "amount_financed_cents": 1000000, "collateral_value_cents": 1000000,
        },
        doc_prefix="IMG-p1",
    )
    setup_funded_contract(
        program, application_overrides={"applicant_reference": "APP-p2"},
        doc_prefix="IMG-p2",
    )

    response = api.list_contracts(
        ADMIN, params={"dealer_id": program["dealer_id"], "limit": 1, "offset": 1}
    )
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert len(rows) == 1
    assert meta["total_count"] == 2
    assert meta["limit"] == 1
    assert meta["offset"] == 1
    assert meta["has_more"] is False

    _, first_page_meta = validate_paginated(
        api.list_contracts(
            ADMIN, params={"dealer_id": program["dealer_id"], "limit": 1, "offset": 0}
        )
    )
    assert first_page_meta["has_more"] is True


def test_contracts_can_be_narrowed_by_funding_status(api):
    """PRD 3.4: "Contracts can be listed and narrowed by `dealer_id`, by originating
    `application_id`, by pinned `agreement_id`, and by either dimension —
    `funding_status` or `reserve_status`."

    Design: Corner/endpoints/contracts_filtered_list_by_funding_status
    """
    program = setup_program()
    funded = setup_funded_contract(
        program, application_overrides={"applicant_reference": "APP-fa"},
        doc_prefix="IMG-fa",
    )
    pending_application = submit_and_approve(
        program["dealer_id"], applicant_reference="APP-fb",
        monthly_debt_cents=180000, amount_financed_cents=1000000,
        collateral_value_cents=1000000,
    )
    pending = book_contract(pending_application["id"], program["dealer_id"])

    rows, meta = validate_paginated(
        api.list_contracts(
            ADMIN,
            params={"dealer_id": program["dealer_id"], "funding_status": "FUNDED"},
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == funded["contract"]["id"]

    rows, meta = validate_paginated(
        api.list_contracts(
            ADMIN,
            params={"dealer_id": program["dealer_id"], "funding_status": "PENDING_DOCS"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == pending["id"]
