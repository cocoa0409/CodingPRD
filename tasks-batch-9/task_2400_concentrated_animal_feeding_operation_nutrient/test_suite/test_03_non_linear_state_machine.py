"""Lifecycles that are not a straight line: the permit's two independent
dimensions and the plan's revision loop.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_null,
    assert_posture,
    assert_quantity,
    assert_state,
)
from test_helpers.factories import inspection_response_payload, plan_patch_payload
from test_helpers.fixtures import (
    approve_plan,
    certify_plan,
    conduct_inspection,
    cover_permit,
    register_operation,
    schedule_inspection,
    set_clock,
    setup_scenario,
    submit_plan,
)
from test_helpers.test_users import (
    PLANNER_2_HEADERS,
    REVIEWER_HEADERS,
    make_operator_headers,
)


def _operation_under_inspection():
    """A covered operation whose routine inspection has been conducted with two
    deficiencies recorded."""
    operation = register_operation()
    operation_id = operation["id"]
    operator_headers = make_operator_headers(operation_id)
    permit = cover_permit(operation_id, operator_headers, REVIEWER_HEADERS)
    inspection = schedule_inspection(
        operation_id, permit["id"], REVIEWER_HEADERS, scheduled_on="2026-07-15T00:00:00Z"
    )
    inspection = conduct_inspection(
        inspection["id"],
        2,
        REVIEWER_HEADERS,
        deficiency_categories=["RECORDKEEPING", "FREEBOARD"],
    )
    return {
        "operation": operation,
        "operator_headers": operator_headers,
        "permit": permit,
        "inspection": inspection,
    }


def test_permit_compliance_cycle_never_disturbs_the_coverage_dimension():
    """A notice of violation and the corrective-action response walk the
    compliance dimension while the coverage dimension stays COVERED, and a later
    renewal walks coverage while compliance stays where it was.

    PRD: "These two dimensions live on the same permit record but advance entirely independently: a coverage transition never writes `compliance_status`, and a compliance transition never writes `coverage_status`."
    PRD: "Issuing the notice transitions the inspection's own permit on its compliance dimension, `IN_GOOD_STANDING → NOTICE_ISSUED`, leaving that permit's `coverage_status` entirely untouched."
    PRD: "The response also advances the permit's compliance dimension `NOTICE_ISSUED → CORRECTIVE_ACTION`; the operation's posture stays `RESTRICTED`, because `CORRECTIVE_ACTION` is itself a restricting `compliance_status`."

    Design: Difficulty/non_linear_state_machine/permit_parallel_dimensions_advance_independently
    """
    ctx = _operation_under_inspection()
    permit_id = ctx["permit"]["id"]
    operator_headers = ctx["operator_headers"]

    assert_state(ctx["permit"], "coverage_status", "COVERED")
    assert_state(ctx["permit"], "compliance_status", "IN_GOOD_STANDING")

    validate_success(
        api_client.issue_nov(ctx["inspection"]["id"], REVIEWER_HEADERS), 200
    )
    permit = validate_success(api_client.get_permit(permit_id, operator_headers), 200)
    assert_state(permit, "compliance_status", "NOTICE_ISSUED")
    assert_state(permit, "coverage_status", "COVERED")

    validate_success(
        api_client.submit_inspection_response(
            ctx["inspection"]["id"],
            inspection_response_payload(
                corrective_action_summary="Berm repaired and records reconstructed"
            ),
            operator_headers,
        ),
        200,
    )
    permit = validate_success(api_client.get_permit(permit_id, operator_headers), 200)
    assert_state(permit, "compliance_status", "CORRECTIVE_ACTION")
    assert_state(permit, "coverage_status", "COVERED")

    set_clock("2030-08-01T00:00:00Z")
    permit = validate_success(
        api_client.initiate_permit_renewal(permit_id, operator_headers), 200
    )
    assert_state(permit, "coverage_status", "RENEWAL_PENDING")
    assert_state(permit, "compliance_status", "CORRECTIVE_ACTION")


def test_renewal_inside_the_window_carries_no_surcharge_while_the_operation_is_restricted():
    """A renewal filed before the due date is not late, and the outstanding
    corrective action keeps the operation restricted even though coverage has
    moved on to RENEWAL_PENDING.

    PRD: "Initiation stamps `renewal_submitted_at` from the logical clock and sets `is_late_renewal` to true exactly when `renewal_submitted_at` is strictly later than `renewal_due_on`."
    PRD: "Otherwise `RESTRICTED` when `open_finding_count` is at least 1, **or** any storage structure of the operation has `storage_status` equal to `FREEBOARD_ALERT`, **or** any permit of the operation has `compliance_status` equal to `NOTICE_ISSUED` or `CORRECTIVE_ACTION`."

    Design: Difficulty/non_linear_state_machine/permit_parallel_dimensions_advance_independently
    """
    ctx = _operation_under_inspection()
    operation_id = ctx["operation"]["id"]
    operator_headers = ctx["operator_headers"]

    validate_success(
        api_client.issue_nov(ctx["inspection"]["id"], REVIEWER_HEADERS), 200
    )
    inspection = validate_success(
        api_client.submit_inspection_response(
            ctx["inspection"]["id"],
            inspection_response_payload(
                corrective_action_summary="Berm repaired and records reconstructed"
            ),
            operator_headers,
        ),
        200,
    )
    assert_state(inspection, "inspection_status", "RESPONSE_SUBMITTED")

    set_clock("2030-08-01T00:00:00Z")
    permit = validate_success(
        api_client.initiate_permit_renewal(ctx["permit"]["id"], operator_headers), 200
    )

    assert permit["is_late_renewal"] is False, (
        "1 August 2030 is before the 3 October 2030 due date"
    )
    assert_quantity(permit["late_surcharge_amount"], 0.00, "late_surcharge_amount")
    assert_quantity(permit["gross_fee"], 589.00, "gross_fee")
    assert_quantity(permit["net_fee"], 559.55, "net_fee")
    assert_quantity(permit["total_due"], 559.55, "total_due")

    operation = validate_success(
        api_client.get_operation(operation_id, operator_headers), 200
    )
    assert_posture(operation, "RESTRICTED", findings=1)


def test_plan_returns_to_draft_and_must_be_certified_afresh():
    """Requiring revision counts the revision, the edit drops the plan back to
    DRAFT and clears the certification, and a second planner may then certify it.

    PRD: "Requiring revision advances `SUBMITTED → REVISION_REQUIRED` and increments `revision_count` by 1, leaving budgets as they were."
    PRD: "Revision is admissible while the plan is in `DRAFT` or `REVISION_REQUIRED`, sets `plan_status` to `DRAFT`, and clears both `certifying_planner_user_id` and `certified_at` — a revised plan must be certified afresh."
    PRD: "Certification stamps `certifying_planner_user_id` with the acting planner's `X-User-ID` and `certified_at` with the logical clock."

    Design: Difficulty/non_linear_state_machine/plan_revision_cycle_returns_to_draft_and_recertifies
    """
    ctx = setup_scenario("SUBMITTED")
    plan_id = ctx["plan"]["id"]

    assert ctx["plan"]["certifying_planner_user_id"] == "planner-1", (
        "the first certification is attributed to the planner who performed it"
    )

    plan = validate_success(
        api_client.require_plan_revision(plan_id, REVIEWER_HEADERS), 200
    )
    assert_state(plan, "plan_status", "REVISION_REQUIRED")
    assert plan["revision_count"] == 1, (
        f"revision_count: expected 1, got {plan['revision_count']}"
    )

    plan = validate_success(
        api_client.update_nutrient_plan(
            plan_id,
            plan_patch_payload(
                allowed_application_methods=["INJECTION"],
                winter_application_allowed=False,
            ),
            PLANNER_2_HEADERS,
        ),
        200,
    )
    assert_state(plan, "plan_status", "DRAFT")
    assert_null(plan, "certifying_planner_user_id", "certified_at")

    plan = certify_plan(plan_id, PLANNER_2_HEADERS)
    assert_state(plan, "plan_status", "CERTIFIED")
    assert plan["certifying_planner_user_id"] == "planner-2", (
        "re-certification is attributed to the planner who signed it the second time"
    )


def test_reapproved_plan_keeps_its_single_revision_and_reactivates_its_budgets():
    """Coming back round the loop does not re-count the revision, and approval
    activates the budgets again with their ledger intact.

    PRD: "This closes the plan cycle `DRAFT → CERTIFIED → SUBMITTED → APPROVED → REVISION_REQUIRED → DRAFT`."
    PRD: "Approval advances `SUBMITTED → APPROVED`, requires the operation's posture to be exactly `OPEN`, stamps `approved_at` from the logical clock, sets `budget_status` to `ACTIVE` on every field nutrient budget of the plan, and — when the plan names a `supersedes_plan_id` — transitions that referenced predecessor `APPROVED → SUPERSEDED`, which in turn sets `budget_status` to `LOCKED` on every budget of the predecessor."

    Design: Difficulty/non_linear_state_machine/plan_revision_cycle_returns_to_draft_and_recertifies
    """
    ctx = setup_scenario("SUBMITTED")
    plan_id = ctx["plan"]["id"]
    operation_id = ctx["operation"]["id"]

    validate_success(api_client.require_plan_revision(plan_id, REVIEWER_HEADERS), 200)
    validate_success(
        api_client.update_nutrient_plan(
            plan_id,
            plan_patch_payload(
                allowed_application_methods=["INJECTION"],
                winter_application_allowed=False,
            ),
            PLANNER_2_HEADERS,
        ),
        200,
    )
    certify_plan(plan_id, PLANNER_2_HEADERS)
    submit_plan(operation_id, plan_id, ctx["operator_headers"])
    plan = approve_plan(plan_id, REVIEWER_HEADERS)

    assert_state(plan, "plan_status", "APPROVED")
    assert plan["revision_count"] == 1, (
        f"revision_count: expected to stay at 1, got {plan['revision_count']}"
    )
    assert plan["allowed_application_methods"] == ["INJECTION"], (
        f"allowed_application_methods: expected ['INJECTION'], "
        f"got {plan['allowed_application_methods']}"
    )

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], ctx["operator_headers"]), 200
    )
    assert_state(budget, "budget_status", "ACTIVE")
    assert_budget_ledger(budget, applied=0.00, remaining=414396, total=414396)

    operation = validate_success(
        api_client.get_operation(operation_id, ctx["operator_headers"]), 200
    )
    assert_posture(operation, "OPEN", findings=0, discharges=0)
