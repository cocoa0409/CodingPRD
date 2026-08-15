"""Foundations: response envelope, pagination, authentication/RBAC, state
rules and association onboarding."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_association,
    create_association_payload,
    create_expenditure,
    create_state_rule_payload,
    is_iso8601_timestamp,
    onboard_association,
    seed_state_rule,
    setup_adopted_study,
    setup_submitted_study,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEnvelopeAndPagination:
    def test_response_envelope_meta_shape(self, api, platform_admin_headers,
                                          reserve_specialist_headers,
                                          board_member_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." and "The
        `response_type` is either "object" for a single resource or "array"
        for a list of resources."

        Design: Corner/endpoints/response_envelope_meta_shape
        """
        seed_state_rule("CA")
        association = validate_success(
            api.create_association(create_association_payload(),
                                   reserve_specialist_headers), 201)
        res = api.get_association(association["id"], board_member_headers)
        assert res.status_code == 200
        body = res.json()
        request_id = body["meta"]["api_request_id"]
        assert isinstance(request_id, str) and request_id.startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"] == association["id"]

    def test_list_pagination_limit_has_more(self, api, platform_admin_headers,
                                            reserve_specialist_headers):
        """PRD §2.3: "List responses carry four pagination fields in the
        `meta` object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`." and "Unless otherwise specified, every list endpoint
        returns its resources sorted by creation timestamp (`created_at`) in
        ascending order."

        Design: Corner/endpoints/list_pagination_limit_has_more
        """
        seed_state_rule("CA")
        association = validate_success(
            api.create_association(
                create_association_payload(name="Pages HOA"),
                reserve_specialist_headers), 201)
        s1 = validate_success(api.create_study(
            {"association_id": association["id"], "fiscal_year": 2026,
             "study_type": "FULL", "inflation_rate": 0.03,
             "interest_rate": 0.02}, reserve_specialist_headers), 201)
        validate_success(api.withdraw_study(s1["id"], reserve_specialist_headers))
        s2 = validate_success(api.create_study(
            {"association_id": association["id"], "fiscal_year": 2027,
             "study_type": "UPDATE_NO_VISIT", "inflation_rate": 0.03,
             "interest_rate": 0.02}, reserve_specialist_headers), 201)

        page1, meta1 = validate_paginated(
            api.list_association_studies(association["id"],
                                         reserve_specialist_headers,
                                         params={"limit": 1}))
        assert len(page1) == 1, f"limit=1 must return one row, got {len(page1)}"
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert page1[0]["id"] == s1["id"], "created_at ASC puts S1 first"

        page2, meta2 = validate_paginated(
            api.list_association_studies(association["id"],
                                         reserve_specialist_headers,
                                         params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert page2[0]["id"] == s2["id"]
        assert meta2["has_more"] is False


class TestAccessControl:
    def test_missing_auth_header_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or does
        not name one of the four declared roles is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_unauthenticated
        """
        res = api.create_association(
            create_association_payload(name="Anon HOA",
                                       reserve_cash_balance_cents=1),
            headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_board_member_cannot_create_component(
            self, api, platform_admin_headers, reserve_specialist_headers,
            board_member_headers):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the addressed endpoint is rejected with `ERR_FORBIDDEN` (HTTP
        403)." PRD §4 restricts POST /components to ReserveSpecialist.

        Design: Corner/rbac/board_member_cannot_create_component
        """
        ctx_association = onboard_association("CA", name="RBAC HOA")
        study = validate_success(api.create_study(
            {"association_id": ctx_association["id"], "fiscal_year": 2026,
             "study_type": "FULL", "inflation_rate": 0.03,
             "interest_rate": 0.02}, reserve_specialist_headers), 201)
        res = api.create_component(
            {"study_id": study["id"], "name": "Roof", "category": "ROOFING",
             "useful_life_years": 5, "remaining_useful_life_years": 2,
             "current_replacement_cost_cents": 100000},
            board_member_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_association_manager_cannot_adopt_study(
            self, api, reserve_specialist_headers,
            association_manager_headers):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the addressed endpoint is rejected with `ERR_FORBIDDEN` (HTTP
        403)." PRD §4 restricts POST /reserve-studies/{id}/adopt to
        BoardMember.

        Design: Corner/rbac/association_manager_cannot_adopt_study
        """
        ctx = setup_submitted_study(association_name="RBAC2 HOA")
        res = api.adopt_study(ctx["study"]["id"], association_manager_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_reserve_specialist_cannot_approve_expenditure(
            self, api, reserve_specialist_headers,
            association_manager_headers):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the addressed endpoint is rejected with `ERR_FORBIDDEN` (HTTP
        403)." PRD §4 restricts POST /expenditures/{id}/approve to
        BoardMember.

        Design: Corner/rbac/reserve_specialist_cannot_approve_expenditure
        """
        ctx = setup_adopted_study(state_code="NV", cash=2000000,
                                  association_name="RBAC3 HOA",
                                  components=[{
                                      "name": "Roof", "category": "ROOFING",
                                      "useful_life_years": 5,
                                      "remaining_useful_life_years": 2,
                                      "current_replacement_cost_cents": 100000,
                                      "is_included_in_funding": True,
                                  }])
        expenditure = create_expenditure(ctx["association"]["id"],
                                         ctx["components"][0]["id"],
                                         amount_cents=5000)
        res = api.approve_expenditure(expenditure["id"],
                                      reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestStateRulesAndOnboarding:
    def test_state_rule_duplicate_state_code_rejected(
            self, api, platform_admin_headers):
        """PRD §3.1: "One rule exists per state: attempting to file a second
        rule for a `state_code` already on record is rejected with
        `ERR_STATE_RULE_EXISTS`."

        Design: Corner/entities/state_rule_duplicate_state_code_rejected
        """
        seed_state_rule("CA")
        res = api.create_state_rule(
            create_state_rule_payload(
                state_code="CA", min_percent_funded_pct=10,
                allowed_plan_types=["BASELINE"], site_visit_interval_years=5,
                disclosure_deadline_days=60, annual_update_required=False),
            platform_admin_headers)
        validate_error(res, ApiErrorId.ERR_STATE_RULE_EXISTS)

    def test_association_create_applies_defaults(
            self, api, platform_admin_headers, reserve_specialist_headers):
        """PRD §3.1: "optionally the `current_annual_contribution_cents` it
        presently funds each year, which defaults to 0 when omitted." and "A
        new association's `statutory_compliance_status` starts at
        `COMPLIANCE_UNKNOWN`, its `next_site_visit_due_date` starts null, and
        its `last_annual_update_fiscal_year` stays null until the first annual
        update runs."

        Design: Corner/entities/association_create_applies_defaults
        """
        seed_state_rule("CA")
        payload = create_association_payload(name="Defaults HOA")
        assert "current_annual_contribution_cents" not in payload
        association = validate_success(
            api.create_association(payload, reserve_specialist_headers), 201)
        assert_association(association)
        assert association["current_annual_contribution_cents"] == 0
        assert association["statutory_compliance_status"] == "COMPLIANCE_UNKNOWN"
        assert association["last_annual_update_fiscal_year"] is None
        assert association["next_site_visit_due_date"] is None

    def test_association_missing_required_state_code(
            self, api, reserve_specialist_headers):
        """PRD §2.8: "Required fields are present, no unknown fields are
        supplied, enum values are members of their declared sets, and numeric
        ranges hold — `useful_life_years` at least 1,
        `remaining_useful_life_years` at least 0 and no greater than the
        useful life, monetary amounts strictly positive, rates non-negative,
        `fiscal_year_end_month` between 1 and 12, `min_percent_funded_pct`
        between 0 and 100, `allowed_plan_types` a non-empty subset of the
        three plan types. Failures surface `ERR_INVALID_REQUEST`."

        Design: Corner/entities/association_missing_required_state_code
        """
        payload = {"name": "No State HOA", "fiscal_year_end_month": 12,
                   "reserve_cash_balance_cents": 500000}
        res = api.create_association(payload, reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_association_get_not_found(self, api, reserve_specialist_headers):
        """PRD §2.8: "Path identifiers and body foreign keys
        (`association_id`, `study_id`, `component_id`) resolve to existing
        resources; failures surface `ERR_NOT_FOUND`."

        Design: Corner/entities/association_get_not_found
        """
        res = api.get_association(NON_EXISTENT_UUID, reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_association_create_without_state_rule_rejected(
            self, api, reserve_specialist_headers):
        """PRD §3.1: "a rule for that state must already exist, and creation
        fails with `ERR_STATE_RULE_MISSING` when none does".

        Design: Corner/validations/association_create_without_state_rule_rejected
        """
        res = api.create_association(
            create_association_payload(name="No Rule HOA", state_code="ZZ",
                                       reserve_cash_balance_cents=1000),
            reserve_specialist_headers)
        validate_error(res, ApiErrorId.ERR_STATE_RULE_MISSING)
