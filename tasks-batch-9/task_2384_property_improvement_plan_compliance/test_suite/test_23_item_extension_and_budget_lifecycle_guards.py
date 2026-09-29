"""Four already-consumed transitions asked for a second time on rows that are legally alive."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledged_plan,
    approve_budget,
    assert_field_equals,
    assert_item_state,
    authorize_budget,
    decide_extension,
    extension_decision_payload,
    extension_resubmit_payload,
    read_budget,
    read_extension,
    read_item,
    read_plan,
    request_extension,
    validate_error,
)

_JUSTIFICATION = (
    "The millwork subcontractor lost its lead installer and the replacement crew starts in "
    "October."
)
_STRONGER_JUSTIFICATION = (
    "The replacement installation crew has now confirmed an October mobilisation date in writing."
)


@pytest.fixture
def acknowledged_plan_with_one_untouched_item(api):
    """One guest-facing line on an acknowledged plan: nothing started, nothing funded yet."""
    return acknowledged_plan(
        api,
        [
            {
                "key": "casegoods",
                "category": "GUEST_FACING",
                "standards_reference": "GF-28.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Elverton Hotels LLC",
        contact_email="ops@elvertonh.example",
        property_overrides={"name": "Elverton Chapelgate"},
    )


def _deny_a_relief_request(api, scenario):
    request = request_extension(
        api,
        scenario,
        scenario.item_id("casegoods"),
        20,
        business_justification=_JUSTIFICATION,
    )
    decide_extension(api, request["id"], "DENY")
    return request


class TestConsumedTransitionsAreRefusedASecondTime:
    def test_work_cannot_be_reported_finished_on_an_item_never_started(
        self, api, acknowledged_plan_with_one_untouched_item
    ):
        """"Reporting the work finished moves the item `IN_PROGRESS → WORK_COMPLETE`; it is refused
        unless the item is `IN_PROGRESS` (`ERR_ITEM_NOT_IN_PROGRESS`) and unless the acting `X-User-ID`
        is the property's `franchisee_id`."

        Design: Corner/errors/item_extension_and_budget_lifecycle_guards_are_triggerable
        """
        scenario = acknowledged_plan_with_one_untouched_item

        response = api.complete_item_work(
            scenario.item_id("casegoods"), scenario.owner_headers
        )

        validate_error(response, ApiErrorId.ERR_ITEM_NOT_IN_PROGRESS, 409)
        assert_item_state(read_item(api, scenario.item_id("casegoods")), status="SCOPED")

    def test_filing_relief_defers_the_item_without_moving_its_date(
        self, api, acknowledged_plan_with_one_untouched_item
    ):
        """"A new request is created in `SUBMITTED` with `round_number` 1, `granted_days` 0,
        `pressure_ratio_at_decision` null, `decided_by_user_id` null and `decision_note` null. Creating
        it also moves the charged item `SCOPED → DEFERRED_PENDING_EXTENSION` and increments the item's
        `version`; crucially, the item's `deadline_date` does **not** change while the request is
        pending."

        Design: Corner/errors/item_extension_and_budget_lifecycle_guards_are_triggerable
        """
        scenario = acknowledged_plan_with_one_untouched_item

        request = request_extension(
            api,
            scenario,
            scenario.item_id("casegoods"),
            20,
            business_justification=_JUSTIFICATION,
        )

        assert_field_equals(request, "status", "SUBMITTED", "request")
        assert_field_equals(request, "round_number", 1, "request")
        assert_field_equals(request, "granted_days", 0, "request")
        assert request["pressure_ratio_at_decision"] is None, (
            f"a pending request has measured no pressure yet, got {request!r}"
        )
        assert_item_state(
            read_item(api, scenario.item_id("casegoods")),
            status="DEFERRED_PENDING_EXTENSION",
            deadline_date="2027-04-28",
        )

    def test_a_denied_request_cannot_be_decided_again(
        self, api, brand_manager, acknowledged_plan_with_one_untouched_item
    ):
        """"the decision is refused unless the request is in `SUBMITTED`
        (`ERR_EXTENSION_NOT_DECIDABLE`)." "`APPROVED`, `APPROVED_PARTIAL` and `DENIED` are the terminal
        request states".

        Design: Corner/errors/item_extension_and_budget_lifecycle_guards_are_triggerable
        """
        scenario = acknowledged_plan_with_one_untouched_item
        request = _deny_a_relief_request(api, scenario)

        response = api.decide_extension_request(
            request["id"], extension_decision_payload("APPROVE"), brand_manager
        )

        validate_error(response, ApiErrorId.ERR_EXTENSION_NOT_DECIDABLE, 409)
        stored = read_extension(api, request["id"])
        assert_field_equals(stored, "status", "DENIED", "request")
        assert_field_equals(stored, "granted_days", 0, "request")

    def test_a_denied_request_cannot_be_strengthened_either(
        self, api, acknowledged_plan_with_one_untouched_item
    ):
        """"the resubmission is refused unless the request is in `NEEDS_MORE_JUSTIFICATION`
        (`ERR_EXTENSION_NOT_RESUBMITTABLE`)". "A `DENY` moves the request `SUBMITTED → DENIED`, sets
        `granted_days` to 0, stores `pressure_ratio_at_decision`, `decided_by_user_id` and
        `decision_note`, and returns the item `DEFERRED_PENDING_EXTENSION → SCOPED` with
        `extension_days_granted` and `deadline_date` unchanged."

        Design: Corner/errors/item_extension_and_budget_lifecycle_guards_are_triggerable
        """
        scenario = acknowledged_plan_with_one_untouched_item
        request = _deny_a_relief_request(api, scenario)

        response = api.resubmit_extension_request(
            request["id"],
            extension_resubmit_payload(
                requested_days=20, business_justification=_STRONGER_JUSTIFICATION
            ),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_EXTENSION_NOT_RESUBMITTABLE, 409)
        assert_field_equals(
            read_extension(api, request["id"]), "status", "DENIED", "request"
        )
        item = read_item(api, scenario.item_id("casegoods"))
        assert_item_state(item, status="SCOPED", deadline_date="2027-04-28")
        assert_field_equals(item, "extension_days_granted", 0, "item")

    def test_an_approved_budget_cannot_be_approved_a_second_time(
        self, api, brand_manager, acknowledged_plan_with_one_untouched_item
    ):
        """"the consent is refused unless the budget is in `DRAFT` (`ERR_BUDGET_NOT_APPROVABLE`) and
        unless the governing plan's `status` is `ISSUED`, `OWNER_ACKNOWLEDGED` or `IN_EXECUTION`
        (`ERR_PLAN_NOT_IN_EXECUTION_WINDOW`), and increments the budget's `version` by one."

        Design: Corner/errors/item_extension_and_budget_lifecycle_guards_are_triggerable
        """
        scenario = acknowledged_plan_with_one_untouched_item
        budget = authorize_budget(api, scenario, 1182500)
        approve_budget(api, budget["id"])

        response = api.approve_capital_budget(budget["id"], brand_manager)

        validate_error(response, ApiErrorId.ERR_BUDGET_NOT_APPROVABLE, 409)
        stored = read_budget(api, budget["id"])
        assert_field_equals(stored, "status", "APPROVED", "budget")
        assert_field_equals(stored, "approved_by_user_id", "bm-001", "budget")

    def test_the_refusals_leave_the_plan_fully_funded_and_undisturbed(
        self, api, brand_manager, acknowledged_plan_with_one_untouched_item
    ):
        """"The gap follows immediately. When the plan has no active budget, `funding_gap_cents` is 0.
        Otherwise it is the funding requirement minus the active budget's `total_authorized_cents`,
        floored at 0 — a requirement below the authorisation leaves no gap rather than a negative one."

        Design: Corner/errors/item_extension_and_budget_lifecycle_guards_are_triggerable
        """
        scenario = acknowledged_plan_with_one_untouched_item
        _deny_a_relief_request(api, scenario)
        budget = authorize_budget(api, scenario, 1182500)
        approve_budget(api, budget["id"])
        validate_error(
            api.approve_capital_budget(budget["id"], brand_manager),
            ApiErrorId.ERR_BUDGET_NOT_APPROVABLE,
            409,
        )

        plan = read_plan(api, scenario.plan_id)

        assert_field_equals(plan, "funding_requirement_cents", 1182500, "plan")
        assert_field_equals(plan, "funding_gap_cents", 0, "plan")
        assert_field_equals(plan, "status", "OWNER_ACKNOWLEDGED", "plan")
