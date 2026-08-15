"""PermitFiling rejection cycle and review-cycle counting."""
from test_helpers import (
    TEST_USERS,
    assert_permit_filing,
    get_success_data,
    setup_project_with_approved_layout,
    validate_success,
)

PC = TEST_USERS["permit_coordinator_headers"]


def test_permit_filing_rejection_cycle(api):
    """PRD §3.5: "A `REJECTED` filing can be resubmitted, cycling back to
    `SUBMITTED`" and "Each successful resubmission again increments
    `review_cycle_no` and restamps `submitted_at`."

    Design: Difficulty/non_linear_state_machine/permit_filing_rejection_cycle
    """
    _, project, layout, _ = setup_project_with_approved_layout(
        item_overrides_list=[
            {"model_no": "DISH", "quantity": 1, "unit_price_cents": 200_000,
             "lead_time_days": 3}
        ]
    )
    filing = get_success_data(
        api.create_permit_filing(project["id"], layout["id"], "HEALTH_DEPT", PC)
    )
    submitted = get_success_data(
        api.submit_permit_filing(project["id"], filing["id"], PC)
    )
    assert submitted["review_cycle_no"] == 1

    rejected = validate_success(
        api.record_permit_decision(project["id"], filing["id"], "REJECTED", PC), 200
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["review_cycle_no"] == 1

    resubmitted = validate_success(
        api.resubmit_permit_filing(project["id"], filing["id"], PC), 200
    )
    assert_permit_filing(resubmitted)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["review_cycle_no"] == 2


def test_permit_filing_submit_increments_cycle_and_stamps(api):
    """PRD §3.5: "Submission increments `review_cycle_no` by 1 and stamps
    `submitted_at` from the logical clock." and "The filing starts in `DRAFT`
    with `review_cycle_no` 0."

    Design: Difficulty/non_linear_state_machine/permit_filing_rejection_cycle
    """
    _, project, layout, _ = setup_project_with_approved_layout()
    filing = validate_success(
        api.create_permit_filing(project["id"], layout["id"], "BUILDING_DEPT", PC),
        201,
    )
    assert filing["status"] == "DRAFT"
    assert filing["review_cycle_no"] == 0

    submitted = validate_success(
        api.submit_permit_filing(project["id"], filing["id"], PC), 200
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["review_cycle_no"] == 1
    assert submitted["submitted_at"] is not None


def test_permit_filing_approval_is_terminal(api):
    """PRD §3.5: "recording `APPROVED` moves a `SUBMITTED` filing to
    `APPROVED`, recording `REJECTED` moves it to `REJECTED`, and either call
    against a filing not in `SUBMITTED` fails with `ERR_FILING_NOT_SUBMITTED`.
    `APPROVED` is terminal."

    Design: Difficulty/non_linear_state_machine/permit_filing_rejection_cycle
    """
    from test_helpers import validate_error

    _, project, layout, _ = setup_project_with_approved_layout()
    filing = get_success_data(
        api.create_permit_filing(project["id"], layout["id"], "HEALTH_DEPT", PC)
    )
    get_success_data(api.submit_permit_filing(project["id"], filing["id"], PC))
    approved = validate_success(
        api.record_permit_decision(project["id"], filing["id"], "APPROVED", PC), 200
    )
    assert approved["status"] == "APPROVED"

    # APPROVED is terminal: resubmit is rejected (requires REJECTED).
    res = api.resubmit_permit_filing(project["id"], filing["id"], PC)
    validate_error(res, "ERR_FILING_NOT_REJECTED", expected_status=409)
