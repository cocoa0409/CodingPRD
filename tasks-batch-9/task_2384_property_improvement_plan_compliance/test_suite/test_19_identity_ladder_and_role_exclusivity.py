"""The four identity gates in order, and the three roles refusing each other's exclusive acts."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_field_equals,
    assert_plan_dimensions,
    bootstrap_portfolio,
    capital_budget_payload,
    current_plan_version,
    headers_with_empty_user_id,
    headers_with_oversized_user_id,
    headers_with_role,
    headers_without_role,
    headers_without_user_id,
    issued_plan,
    list_rows,
    plan_payload,
    read_inspection,
    read_plan,
    schedule_inspection,
    scope_plan,
    validate_error,
    validate_success,
)


@pytest.fixture
def draft_plan_behind_the_identity_ladder(api):
    """A draft plan carrying one item, so every identity probe reaches the ladder, not a 404."""
    portfolio = bootstrap_portfolio(
        api,
        "Lyndhurst Hotels LLC",
        "ops@lyndhursth.example",
        name="Lyndhurst Abbey Gate",
    )
    return scope_plan(
        api,
        portfolio,
        [
            {
                "key": "casegoods",
                "category": "GUEST_FACING",
                "standards_reference": "GF-35.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
    )


class TestIdentityHeadersAreCheckedFirst:
    def test_a_request_without_a_role_header_is_rejected(
        self, api, draft_plan_behind_the_identity_ladder
    ):
        """"Every request to the API must carry two headers: `X-User-ID`, identifying the acting user,
        and `X-User-Role`, declaring the capacity in which that user acts. If `X-User-Role` is absent
        the request is rejected with `ERR_MISSING_ROLE`." "All three are 401-class failures and are
        evaluated before anything else about the request is inspected."

        Design: Corner/rbac/missing_and_invalid_auth_headers_are_rejected
        """
        scenario = draft_plan_behind_the_identity_ladder

        response = api.get_plan(scenario.plan_id, headers_without_role("bm-001"))

        validate_error(response, ApiErrorId.ERR_MISSING_ROLE, 401)

    def test_a_role_outside_the_closed_set_is_rejected(
        self, api, draft_plan_behind_the_identity_ladder
    ):
        """"If it is present but carries a value outside the three recognised roles the rejection is
        `ERR_INVALID_ROLE`." "The system recognises exactly three roles, spelled precisely as follows:
        `FranchiseeOwner`, `BrandManager`, and `BrandInspector`."

        Design: Corner/rbac/missing_and_invalid_auth_headers_are_rejected
        """
        scenario = draft_plan_behind_the_identity_ladder

        response = api.get_plan(scenario.plan_id, headers_with_role("bm-001", "Auditor"))

        validate_error(response, ApiErrorId.ERR_INVALID_ROLE, 401)

    def test_a_recognised_role_alone_is_not_enough_without_a_usable_user_id(
        self, api, draft_plan_behind_the_identity_ladder
    ):
        """"If `X-User-ID` is absent, empty, or longer than 64 characters the rejection is
        `ERR_MISSING_USER_ID`." "then `X-User-ID` present and between 1 and 64 characters
        (`ERR_MISSING_USER_ID`)".

        Design: Corner/rbac/missing_and_invalid_auth_headers_are_rejected
        """
        scenario = draft_plan_behind_the_identity_ladder

        validate_error(
            api.get_plan(scenario.plan_id, headers_without_user_id("BrandManager")),
            ApiErrorId.ERR_MISSING_USER_ID,
            401,
        )
        validate_error(
            api.get_plan(scenario.plan_id, headers_with_empty_user_id("BrandManager")),
            ApiErrorId.ERR_MISSING_USER_ID,
            401,
        )
        validate_error(
            api.get_plan(scenario.plan_id, headers_with_oversized_user_id("BrandManager")),
            ApiErrorId.ERR_MISSING_USER_ID,
            401,
        )

    def test_a_well_identified_caller_off_the_endpoint_list_is_a_403_instead(
        self, api, draft_plan_behind_the_identity_ladder
    ):
        """"When a caller presents a role that is not listed for the endpoint it is invoking, the
        request fails with `ERR_UNAUTHORIZED` (403)." "Issuing the plan is the brand's act of freezing
        the scope and starting the clock".

        Design: Corner/rbac/missing_and_invalid_auth_headers_are_rejected
        """
        scenario = draft_plan_behind_the_identity_ladder

        response = api.issue_plan(scenario.plan_id, scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
        plan = read_plan(api, scenario.plan_id)
        assert_plan_dimensions(plan, status="DRAFT")
        assert plan["issued_at"] is None, f"a refused issuance stamps no date, got {plan!r}"


@pytest.fixture
def issued_plan_with_a_visit_on_the_books(api):
    """An issued plan and a completion visit assigned to bi-007, still only scheduled."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "corridors",
                "category": "GUEST_FACING",
                "standards_reference": "GF-36.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Mereworth Hotels LLC",
        contact_email="ops@mereworthh.example",
        property_overrides={"name": "Mereworth Signal Yard"},
    )
    inspection = schedule_inspection(api, scenario, scheduled_date="2026-08-01")
    return scenario, inspection, current_plan_version(api, scenario.plan_id)


class TestTheThreeRolesAreExclusivePeers:
    def test_the_owner_cannot_scope_and_the_brand_cannot_acknowledge(
        self, api, brand_manager, issued_plan_with_a_visit_on_the_books
    ):
        """"A `BrandManager` is the brand's compliance and franchising operator; it registers
        franchisees, properties and contractors, scopes and issues plans". "A `FranchiseeOwner` is the
        hotel owner holding the franchise agreement; it executes plans — acknowledging issuance,
        authorising and locking capital".

        Design: Corner/rbac/brand_and_owner_exclusive_operations_are_forbidden_to_the_other_side
        """
        scenario, _inspection, _version = issued_plan_with_a_visit_on_the_books

        validate_error(
            api.create_plan(
                plan_payload(scenario.property_id, "RELICENSING", "2026.1"),
                scenario.owner_headers,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.acknowledge_plan(scenario.plan_id, brand_manager),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="ISSUED")

    def test_the_inspector_cannot_fund_and_the_owner_cannot_inspect(
        self, api, brand_inspector, issued_plan_with_a_visit_on_the_books
    ):
        """"An inspector can neither scope nor issue a plan, nor decide extensions, budgets, draws,
        disputes or notices." "A `BrandInspector` is the brand's field inspector; it performs scheduled
        visits, raises punch-list defects, verifies, reopens or waives them, and certifies completion."

        Design: Corner/rbac/brand_and_owner_exclusive_operations_are_forbidden_to_the_other_side
        """
        scenario, inspection, version = issued_plan_with_a_visit_on_the_books

        validate_error(
            api.create_capital_budget(
                capital_budget_payload(scenario.plan_id, 1182500, version),
                brand_inspector,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.perform_inspection(inspection["id"], scenario.owner_headers),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        _rows, meta = list_rows(api, "list_capital_budgets", plan_id=scenario.plan_id)
        assert meta["total_count"] == 0, (
            f"the inspector's refused authorisation must leave no budget, got {meta}"
        )
        read_back = read_inspection(api, inspection["id"])
        assert_field_equals(read_back, "status", "SCHEDULED", "inspection")
        assert read_back["performed_at"] is None, (
            f"the owner's refused visit stamps nothing, got {read_back!r}"
        )

    def test_the_plan_read_is_shared_by_all_three_roles(
        self, api, brand_manager, brand_inspector, issued_plan_with_a_visit_on_the_books
    ):
        """"When a caller presents a role that is not listed for the endpoint it is invoking, the
        request fails with `ERR_UNAUTHORIZED` (403)." The read is listed for every role: "| GET |
        `/pip/plans/{id}` | Read one plan, including both state dimensions, the three category
        deadlines, cost aggregates and version | Any |".

        Design: Corner/rbac/brand_and_owner_exclusive_operations_are_forbidden_to_the_other_side
        """
        scenario, _inspection, _version = issued_plan_with_a_visit_on_the_books

        as_brand = validate_success(api.get_plan(scenario.plan_id, brand_manager))
        as_inspector = validate_success(api.get_plan(scenario.plan_id, brand_inspector))
        as_owner = validate_success(api.get_plan(scenario.plan_id, scenario.owner_headers))

        assert as_brand["id"] == as_inspector["id"] == as_owner["id"] == scenario.plan_id, (
            "the shared read must answer identically to all three capacities, got "
            f"{as_brand['id']!r}, {as_inspector['id']!r} and {as_owner['id']!r}"
        )
        assert_field_equals(as_inspector, "status", "ISSUED", "plan read as inspector")
