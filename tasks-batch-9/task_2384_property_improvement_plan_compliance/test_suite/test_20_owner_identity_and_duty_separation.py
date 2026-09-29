"""A neighbouring owner turned away, and the issuer barred from certifying its own plan."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledge_plan,
    assert_field_equals,
    assert_item_state,
    assert_plan_dimensions,
    bootstrap_portfolio,
    complete_item_work,
    extension_request_payload,
    issued_plan,
    list_rows,
    locked_budget,
    make_brand_manager_headers,
    make_franchisee_owner_headers,
    read_budget,
    read_franchisee,
    read_inspection,
    read_item,
    read_plan,
    perform_inspection,
    register_franchisee,
    schedule_inspection,
    scope_plan,
    start_item,
    validate_error,
    validate_success,
)


@pytest.fixture
def one_owners_plan_and_a_second_legitimate_owner(api):
    """An issued plan belonging to the first franchisee, and a second account with no property."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "corridors",
                "category": "GUEST_FACING",
                "standards_reference": "GF-37.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Norbury Hotels LLC",
        contact_email="ops@norburyh.example",
        property_overrides={"name": "Norbury Steelworks"},
    )
    stranger = register_franchisee(
        api, "Oakhampton Lodging LLC", "ops@oakhamptonl.example"
    )
    return scenario, stranger, make_franchisee_owner_headers(stranger["id"])


class TestOwnerIdentityIsCheckedAgainstTheProperty:
    def test_a_stranger_owner_cannot_acknowledge_the_plan(
        self, api, one_owners_plan_and_a_second_legitimate_owner
    ):
        """"every owner-side action resolves the governing `Property` and requires that its
        `franchisee_id` equal the presented `X-User-ID`, failing with `ERR_NOT_PROPERTY_FRANCHISEE`
        (403) otherwise. One owner can therefore never act on another owner's property." "It is refused
        from any other state with `ERR_PLAN_NOT_ACKNOWLEDGEABLE`, and refused to any `X-User-ID` other
        than the governing property's `franchisee_id` with `ERR_NOT_PROPERTY_FRANCHISEE`."

        Design: Corner/rbac/second_franchisee_cannot_acknowledge_another_owners_plan
        """
        scenario, stranger, stranger_headers = one_owners_plan_and_a_second_legitimate_owner

        response = api.acknowledge_plan(scenario.plan_id, stranger_headers)

        validate_error(response, ApiErrorId.ERR_NOT_PROPERTY_FRANCHISEE, 403)
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="ISSUED")
        assert_field_equals(
            read_franchisee(api, stranger["id"]), "portfolio_property_count", 0, "second franchisee"
        )

    def test_a_stranger_owner_cannot_file_relief_against_the_item(
        self, api, one_owners_plan_and_a_second_legitimate_owner
    ):
        """"When `X-User-Role` is `FranchiseeOwner`, `X-User-ID` is the `id` of the acting
        `FranchiseeAccount`." "unless the acting `X-User-ID` is the property's `franchisee_id`
        (`ERR_NOT_PROPERTY_FRANCHISEE`)".

        Design: Corner/rbac/second_franchisee_cannot_acknowledge_another_owners_plan
        """
        scenario, _stranger, stranger_headers = one_owners_plan_and_a_second_legitimate_owner

        response = api.create_extension_request(
            extension_request_payload(
                scenario.item_id("corridors"),
                30,
                business_justification=(
                    "A neighbouring franchisee attempts to file relief against scope that is not on "
                    "its own property."
                ),
            ),
            stranger_headers,
        )

        validate_error(response, ApiErrorId.ERR_NOT_PROPERTY_FRANCHISEE, 403)
        _rows, meta = list_rows(
            api, "list_extension_requests", item_id=scenario.item_id("corridors")
        )
        assert meta["total_count"] == 0, f"the stranger's request must leave no row, got {meta}"
        item = read_item(api, scenario.item_id("corridors"))
        assert_item_state(item, status="SCOPED")
        assert_field_equals(item, "extension_days_granted", 0, "item")

    def test_the_rightful_owner_is_admitted_to_the_same_act(
        self, api, one_owners_plan_and_a_second_legitimate_owner
    ):
        """"The owner's contractual receipt moves the plan `ISSUED → OWNER_ACKNOWLEDGED` and opens the
        execution window." "Acknowledgement recomputes nothing — no cost figure and no deadline moves —
        and simply increments the plan's `version` by one."

        Design: Corner/rbac/second_franchisee_cannot_acknowledge_another_owners_plan
        """
        scenario, _stranger, _stranger_headers = one_owners_plan_and_a_second_legitimate_owner

        acknowledged = validate_success(
            api.acknowledge_plan(scenario.plan_id, scenario.owner_headers)
        )

        assert_plan_dimensions(acknowledged, status="OWNER_ACKNOWLEDGED")
        assert_field_equals(
            read_plan(api, scenario.plan_id), "status", "OWNER_ACKNOWLEDGED", "plan"
        )


@pytest.fixture
def plan_issued_by_the_inspector_who_would_certify_it(api):
    """A plan issued under the id bi-007, ready for the completion visit that same id performed."""
    portfolio = bootstrap_portfolio(
        api, "Pentlow Hotels LLC", "ops@pentlowh.example", name="Pentlow Waterworks"
    )
    scenario = scope_plan(
        api,
        portfolio,
        [
            {
                "key": "corridors",
                "category": "GUEST_FACING",
                "standards_reference": "GF-38.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
    )
    validate_success(api.issue_plan(scenario.plan_id, make_brand_manager_headers("bi-007")))
    acknowledge_plan(api, scenario)
    budget = locked_budget(api, scenario, 1182500)
    start_item(api, scenario, scenario.item_id("corridors"))
    complete_item_work(api, scenario, scenario.item_id("corridors"))
    inspection = schedule_inspection(api, scenario, scheduled_date="2026-08-01")
    inspection = perform_inspection(api, inspection["id"])
    return scenario, budget, inspection


class TestSignOffStacksTwoIdentityChecks:
    def test_an_unassigned_inspector_is_stopped_before_the_segregation_rule(
        self, api, other_brand_inspector, plan_issued_by_the_inspector_who_would_certify_it
    ):
        """"The acting `X-User-ID` must equal the inspection's `inspector_user_id`, or
        `ERR_NOT_ASSIGNED_INSPECTOR`. The acting `X-User-ID` must differ from the plan's
        `issued_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES` (403)". "`ERR_NOT_ASSIGNED_INSPECTOR`,
        `ERR_SEGREGATION_OF_DUTIES` ... in that order."

        Design: Corner/rbac/plan_issuer_cannot_certify_its_own_completion_inspection
        """
        scenario, _budget, inspection = plan_issued_by_the_inspector_who_would_certify_it

        response = api.sign_off_inspection(inspection["id"], other_brand_inspector)

        validate_error(response, ApiErrorId.ERR_NOT_ASSIGNED_INSPECTOR, 403)
        plan = read_plan(api, scenario.plan_id)
        assert_field_equals(plan, "issued_by_user_id", "bi-007", "plan")
        assert_plan_dimensions(plan, status="READY_FOR_COMPLETION_INSPECTION")

    def test_the_assigned_inspector_who_issued_the_plan_is_barred_from_certifying_it(
        self, api, brand_inspector, plan_issued_by_the_inspector_who_would_certify_it
    ):
        """"It stamps `issued_by_user_id` with the acting operator's `X-User-ID` — the id thereby
        barred from certifying this plan's completion". "The acting `X-User-ID` must differ from the
        plan's `issued_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES` (403): the operator who issued a
        plan can never certify its completion."

        Design: Corner/rbac/plan_issuer_cannot_certify_its_own_completion_inspection
        """
        scenario, budget, inspection = plan_issued_by_the_inspector_who_would_certify_it

        response = api.sign_off_inspection(inspection["id"], brand_inspector)

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        read_back = read_inspection(api, inspection["id"])
        assert_field_equals(read_back, "status", "PERFORMED", "inspection")
        assert read_back["signed_off_at"] is None, (
            f"a refused certification stamps no signature, got {read_back!r}"
        )
        assert read_back["signed_off_by_user_id"] is None, (
            f"a refused certification records no signer, got {read_back!r}"
        )
        assert_item_state(read_item(api, scenario.item_id("corridors")), status="WORK_COMPLETE")
        assert_field_equals(read_budget(api, budget["id"]), "status", "LOCKED", "budget")
