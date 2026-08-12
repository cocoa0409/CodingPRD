"""Salvage plans: revision loop, segregation of duties, referential gates."""
from test_helpers import (
    ApiErrorId,
    draft_plan,
    make_operations_director_headers,
    report_casualty,
    setup_assessed_casualty,
    submit_assessment,
    submit_plan,
    validate_error,
    validate_success,
)


def test_plan_revision_loop_reject_returns_to_draft(
    api, salvage_master_headers, operations_director_headers
):
    """PRD 3.2: "Rejection by an `OperationsDirector` does not kill the plan:
    it returns the plan from `SUBMITTED` to `DRAFT` and increments the plan's
    `version`, and this draft–submit–reject revision loop may repeat without
    bound."

    Design: Corner/state_machines/plan_revision_loop_reject_returns_to_draft
    """
    ctx = setup_assessed_casualty(casualty_overrides={"vessel_name": "MV Pax"})
    plan = draft_plan(ctx["casualty"]["id"])
    plan = submit_plan(plan["id"])
    assert plan["status"] == "SUBMITTED"
    version_at_submit = plan["version"]

    rejected = validate_success(
        api.reject_plan(plan["id"], operations_director_headers), 200
    )
    assert rejected["status"] == "DRAFT", "reject loops back to DRAFT, not terminal"
    assert rejected["version"] == version_at_submit + 1

    resubmitted = validate_success(api.submit_plan(plan["id"], salvage_master_headers), 200)
    assert resubmitted["status"] == "SUBMITTED", "the plan is reusable after rejection"


def test_sod_plan_self_approve_rejected(api, salvage_master_headers):
    """PRD 3.2: "Approval by an `OperationsDirector` enforces two preconditions,
    in the pipeline order of §2.7: first the segregation-of-duties rule that the
    approver's identity must differ from the plan's `drafter_id`
    (`ERR_SOD_VIOLATION`)"

    Design: Corner/validations/sod_plan_self_approve_rejected
    """
    ctx = setup_assessed_casualty(casualty_overrides={"vessel_name": "MV Pax"})
    plan = draft_plan(ctx["casualty"]["id"])
    plan = submit_plan(plan["id"])
    assert plan["drafter_id"] == "sm-01"
    # The plan's author, acting in the director capacity, attempts approval.
    res = api.approve_plan(plan["id"], make_operations_director_headers("sm-01"))
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
    after = validate_success(api.get_plan(plan["id"], salvage_master_headers), 200)
    assert after["status"] == "SUBMITTED"


def test_assessment_not_approved_blocks_plan_approval(
    api, salvage_master_headers, operations_director_headers, marine_surveyor_headers
):
    """PRD 3.2: "Approval by an `OperationsDirector` enforces two preconditions,
    in the pipeline order of §2.7: first the segregation-of-duties rule ...,
    and then the referential gate that an assessment of the same casualty in
    status `APPROVED` must exist (`ERR_ASSESSMENT_NOT_APPROVED`)."

    Design: Corner/validations/assessment_not_approved_blocks_plan_approval
    """
    casualty = report_casualty(vessel_name="MV Pax")
    # Assessment filed but never approved.
    submit_assessment(casualty["id"], headers=marine_surveyor_headers)
    plan = draft_plan(casualty["id"])
    plan = submit_plan(plan["id"])
    res = api.approve_plan(plan["id"], operations_director_headers)
    validate_error(res, ApiErrorId.ERR_ASSESSMENT_NOT_APPROVED, expected_status=422)
    after = validate_success(api.get_plan(plan["id"], salvage_master_headers), 200)
    assert after["status"] == "SUBMITTED"
