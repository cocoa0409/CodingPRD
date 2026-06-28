"""State-machine corner cases: invalid transitions, terminal lockdown, and
refinement-grant side effects (PRD §3.4, §3.10, §3.9, §3.8)."""
from test_helpers import (
    validate_success, validate_error,
    setup_submitted_plan, setup_active_retainer,
    setup_refinement_requested, setup_one_refinement_granted_resumed,
    setup_case_active_step1_manufactured,
    create_clinician, create_patient, create_case, add_usable_intake,
    create_plan_payload,
    api_client, TEST_USERS, make_patient_headers, make_clinician_headers,
)

BILLING = TEST_USERS["billing_headers"]
MFG = TEST_USERS["manufacturing_headers"]


def test_approve_draft_plan_returns_invalid_state(api):
    """PRD §3.5: "Approving a submitted plan is the pivotal event of the case
    lifecycle. It is permitted only when the plan is `SUBMITTED`, the plan's case
    is `UNDER_REVIEW`, and the acting clinician's `id` equals the case's
    `assigned_clinician_id`."
    PRD §2.10: "then whether the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)".

    Approving a plan still in DRAFT (never SUBMITTED) is not a defined transition
    and returns ERR_INVALID_STATE (409); the case stays UNDER_REVIEW.

    Design: Corner/state_machines/approve_from_draft_plan_returns_invalid_state
    """
    # Build a case UNDER_REVIEW with a DRAFT (un-submitted) plan.
    create_clinician(license_state_codes=["CA"])
    from test_helpers import setup_case_under_review
    ctx = setup_case_under_review(state_code="CA", list_price_cents=300000)
    plan = validate_success(
        api.create_plan(
            create_plan_payload(ctx["case"]["id"], ctx["clinician"]["id"],
                                proposed_step_count=10, weeks_per_step=2),
            ctx["clin_headers"],
        ),
        201,
    )
    assert plan["status"] == "DRAFT"
    res = api.approve_plan(plan["id"], ctx["clin_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    assert case["status"] == "UNDER_REVIEW", case["status"]


def test_cancel_cancelled_retainer_returns_invalid_state(api):
    """PRD §3.10: "or cancel it (from `ACTIVE` or `PAUSED` to the terminal
    `CANCELLED`)."
    PRD §2.10: "then whether the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)".

    CANCELLED is terminal for a RetainerSubscription; a second cancel returns
    ERR_INVALID_STATE (409).

    Design: Corner/state_machines/cancel_retainer_twice_terminal_lockdown
    """
    ctx = setup_active_retainer(cadence="QUARTERLY", per_shipment_fee_cents=5000)
    ret_id = ctx["retainer"]["id"]
    validate_success(api.cancel_retainer(ret_id, ctx["pat_headers"]), 200)
    res = api.cancel_retainer(ret_id, ctx["pat_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    fetched = validate_success(api.get_retainer(ret_id, BILLING), 200)
    assert fetched["status"] == "CANCELLED", fetched["status"]


def test_first_refinement_grant_is_free(api):
    """PRD §3.9 Refinement fee: "When the pre-increment `refinement_count` is
    below 1, the refinement is free, `is_billable` stays false, and no fee is
    added. In effect, the first granted refinement is free and the second
    granted refinement is the first billable one."
    PRD §3.9: "the case's `refinement_count` is incremented".

    The first granted refinement (pre-increment count 0 < 1) is free:
    is_billable false, refinement_count becomes 1, total unchanged at 300000.
    (list 375000, 10 steps LIGHT 0.80 -> 300000 contracted.)

    Design: Corner/state_machines/refinement_first_grant_free_count_one
    """
    ctx = setup_refinement_requested(assessment="OFF_TRACK", proposed_step_count=10,
                                     additional_step_count=2, list_price_cents=375000)
    granted = validate_success(api.grant_refinement(ctx["refinement"]["id"], ctx["clin_headers"]), 200)
    assert granted["is_billable"] is False
    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    assert case["refinement_count"] == 1, case["refinement_count"]
    assert case["total_contracted_cents"] == 300000, case["total_contracted_cents"]


def test_second_refinement_grant_is_billable_and_raises_total(api):
    """PRD §3.9 Refinement fee: "when the pre-increment `refinement_count` is at
    least 1 (the included allotment of 1 having already been consumed), the
    refinement's `is_billable` is set true and a refinement fee of 30000 cents is
    appended to the case ledger, raising the case's `total_contracted_cents` by
    that fee".

    After one refinement already granted (count=1), the second grant is billable:
    is_billable true, count becomes 2, total rises 300000 -> 330000.
    (list 375000, 10 steps LIGHT 0.80 -> 300000 contracted base.)

    Design: Corner/state_machines/refinement_grant_increments_count_and_billable_on_second
    """
    ctx = setup_one_refinement_granted_resumed(proposed_step_count=10, list_price_cents=375000)
    granted = validate_success(
        api.grant_refinement(ctx["second_refinement"]["id"], ctx["clin_headers"]), 200
    )
    assert granted["is_billable"] is True
    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    assert case["refinement_count"] == 2, case["refinement_count"]
    assert case["total_contracted_cents"] == 330000, case["total_contracted_cents"]


def test_start_production_out_of_order_rejected(api):
    """PRD §3.8: "Starting production on a step moves it from `PLANNED` to
    `IN_PRODUCTION` and is allowed only when the case is `ACTIVE` or `REFINEMENT`
    and the immediately-prior `step_index` step (if there is one) is already
    `SHIPPED`; starting a step while its predecessor has not shipped is rejected
    with `ERR_STEP_ORDER_VIOLATION` (HTTP 422)."

    Starting production on step 2 while step 1 is only MANUFACTURED (not SHIPPED)
    is rejected with ERR_STEP_ORDER_VIOLATION (422).

    Design: Corner/state_machines/start_production_out_of_order_rejected
    """
    ctx = setup_case_active_step1_manufactured(proposed_step_count=10)
    s2 = ctx["steps"][1]
    res = api.start_production(s2["id"], MFG)
    validate_error(res, "ERR_STEP_ORDER_VIOLATION", expected_status=422)
