"""A field action carries two independent state dimensions on one row.

PRD §3.5: "The two dimensions genuinely are independent — the execution dimension
advances while `approval_state` remains `APPROVED` throughout, and a progress call
never moves the approval dimension."
"""

from test_helpers import (
    ENGINEER_HEADERS,
    ERR_EXECUTION_BEFORE_APPROVAL,
    create_family,
    create_field_action,
    create_period,
    create_remedy_option,
    decide_field_action,
    read_family,
    read_field_action,
    read_period,
    select_remedy,
    submit_field_action,
    success_data,
    validate_error,
)


def _build_world(api):
    """FAM-P with a DRAFT campaign already priced at 26000000 cents."""
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    family = create_family(
        api,
        family_code="FAM-P",
        name="Front Load Washer Platform",
        launch_date="2024-02-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=22000,
        reserve_cap_cents=400000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-P-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-02-01",
        affected_build_end_date="2025-04-30",
        affected_unit_count=4000,
        regulatory_notice_filed=False,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-P-PERM",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=3000,
        labor_hours_centi=100,
        admin_cost_cents=500,
        expected_take_rate_bps=5000,
        is_engineering_approved=True,
    )
    selected = select_remedy(
        api, action["id"], remedy_option_id=option["id"], expected_field_action_version=1
    )
    assert selected["specific_accrual_cents"] == 26000000
    return {"period": period, "family": family, "action": selected, "option": option}


def test_execution_cannot_leave_not_started_before_the_approval_dimension_reads_approved(api):
    """A DRAFT action refuses execution progress and accumulates no cost.

    PRD §3.5: "Leaving `NOT_STARTED` requires the approval dimension to already
    read `APPROVED`; attempting it on an action still in `DRAFT`, `SUBMITTED` or
    `REJECTED` answers `ERR_EXECUTION_BEFORE_APPROVAL`." PRD §3.5 also says "each
    progress call adds the supplied `incurred_cost_cents` to the action's running
    `executed_cost_cents`", so a refused call must leave that running total at its
    initial 0.

    Design: Difficulty/non_linear_state_machine/field_action_execution_dimension_advances_independently_of_approval
    """
    world = _build_world(api)

    response = api.execution_progress(
        ENGINEER_HEADERS,
        world["action"]["id"],
        to_execution_state="IN_PROGRESS",
        incurred_cost_cents=500000,
    )
    validate_error(response, ERR_EXECUTION_BEFORE_APPROVAL, expected_status=409)

    action = read_field_action(api, world["action"]["id"])
    assert action["executed_cost_cents"] == 0
    assert action["execution_state"] == "NOT_STARTED"
    assert action["approval_state"] == "DRAFT"


def test_approval_books_the_campaign_accrual_and_leaves_execution_at_not_started(api):
    """Advancing the approval dimension does not touch the execution dimension.

    PRD §3.5: "A new action starts with `approval_state` of `DRAFT`,
    `execution_state` of `NOT_STARTED`". PRD §3.5: "**Hop one** records the
    controller's identifier as `decided_by_user_id`, writes the period chosen by the
    booking-period selector into `approved_period_id`, and recomputes
    `specific_accrual_cents` from the currently selected remedy option." The single
    OPEN period is the only booking candidate, and the execution axis stays where it
    started.

    Design: Difficulty/non_linear_state_machine/field_action_execution_dimension_advances_independently_of_approval
    """
    world = _build_world(api)
    submit_field_action(api, world["action"]["id"])

    approved = decide_field_action(api, world["action"]["id"], "APPROVED")

    assert approved["approval_state"] == "APPROVED"
    assert approved["execution_state"] == "NOT_STARTED"
    assert approved["specific_accrual_cents"] == 26000000
    assert approved["approved_period_id"] == world["period"]["id"]


def test_execution_walks_to_completed_while_approval_stays_pinned_at_approved(api):
    """The execution axis advances twice and the ledger absorbs the incurred cost.

    PRD §3.5: "`execution_state` starts at `NOT_STARTED` and advances through
    `IN_PROGRESS` to `COMPLETED`". PRD §2.10 subtracts "the **completed execution
    total** — the sum of `executed_cost_cents` over every field action of this
    family whose `execution_state` is `COMPLETED`", so 26000000 less 1200000 leaves
    24800000 cents. PRD §3.1: "`significant_exposure_count` is the number of field
    actions whose `approved_period_id` is this period, whose `approval_state` is
    `APPROVED`, and whose `specific_accrual_cents` is at least 50,000,000 cents",
    which this 26000000-cent campaign does not reach.

    Design: Difficulty/non_linear_state_machine/field_action_execution_dimension_advances_independently_of_approval
    """
    world = _build_world(api)
    submit_field_action(api, world["action"]["id"])
    decide_field_action(api, world["action"]["id"], "APPROVED")

    in_progress = success_data(
        api.execution_progress(
            ENGINEER_HEADERS,
            world["action"]["id"],
            to_execution_state="IN_PROGRESS",
            incurred_cost_cents=500000,
        )
    )
    assert in_progress["execution_state"] == "IN_PROGRESS"
    assert in_progress["approval_state"] == "APPROVED"
    assert in_progress["executed_cost_cents"] == 500000

    completed = success_data(
        api.execution_progress(
            ENGINEER_HEADERS,
            world["action"]["id"],
            to_execution_state="COMPLETED",
            incurred_cost_cents=700000,
        )
    )
    assert completed["execution_state"] == "COMPLETED"
    assert completed["approval_state"] == "APPROVED"
    assert completed["executed_cost_cents"] == 1200000

    family = read_family(api, world["family"]["id"])
    assert family["warranty_reserve_balance_cents"] == 24800000
    assert family["reserve_posture"] == "NORMAL"

    period = read_period(api, world["period"]["id"])
    assert period["significant_exposure_count"] == 0
    assert period["requires_significant_exposure_disclosure"] is False
