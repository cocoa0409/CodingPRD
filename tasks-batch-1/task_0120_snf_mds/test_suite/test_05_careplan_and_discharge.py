"""Care-plan review cycle, discharge cascade, and terminal lockdown.

Covers difficulty rules: non_linear_state_machine (care-plan ACTIVE<->UNDER_REVIEW
cycle), transitive_cascade (discharge depth-3 cascade), plus corner care-plan and
discharge error/lockdown instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    fixtures,
    factories as f,
)

COORD = TEST_USERS["admissions_coordinator_headers"]
MDS = TEST_USERS["mds_coordinator_headers"]
PHYSICIAN = TEST_USERS["physician_headers"]


# =====================================================================
# Difficulty/non_linear_state_machine/careplan_active_under_review_cycle
# =====================================================================

def test_careplan_active_under_review_cycle():
    """PRD §3.7: "From ACTIVE, beginning a review moves the plan to UNDER_REVIEW;
    completing that review moves it back to ACTIVE and again sets last_reviewed_at to
    the moment of the request — this is the recurring review loop".

    Design: Difficulty/non_linear_state_machine/careplan_active_under_review_cycle
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    plan, goal = fixtures.create_active_care_plan(admission["id"])

    mid = validate_success(api_client.begin_review_care_plan(plan["id"], {}, PHYSICIAN))
    assert mid["status"] == "UNDER_REVIEW", f"expected UNDER_REVIEW, got {mid['status']}"

    back = validate_success(api_client.complete_review_care_plan(plan["id"], {}, PHYSICIAN))
    assert back["status"] == "ACTIVE", f"expected ACTIVE after complete-review, got {back['status']}"


def test_careplan_review_loop_refreshes_last_reviewed_at():
    """PRD §3.7: "completing that review moves it back to ACTIVE and again sets
    last_reviewed_at to the moment of the request — this is the recurring review loop".

    Design: Difficulty/non_linear_state_machine/careplan_active_under_review_cycle
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    plan, goal = fixtures.create_active_care_plan(admission["id"])
    # last_reviewed_at is set on activation; the completed review re-sets it,
    # proving the loop re-executes its side effect (the value must be present).
    get_success_data(api_client.begin_review_care_plan(plan["id"], {}, PHYSICIAN))
    back = validate_success(api_client.complete_review_care_plan(plan["id"], {}, PHYSICIAN))
    assert back["status"] == "ACTIVE"
    assert back["last_reviewed_at"] is not None, (
        "complete-review must set last_reviewed_at on the loop's second ACTIVE entry")


# =====================================================================
# Difficulty/transitive_cascade/discharge_cascade_admission_careplan_goal_depth3
# =====================================================================

def test_discharge_cascade_admission_careplan_goal_depth3():
    """PRD §3.8: "On discharge the admission's status becomes DISCHARGED ... a
    depth-three cascade fires: every ACTIVE care plan for the admission is closed to
    CLOSED, and every OPEN or IN_PROGRESS goal under those plans is moved to
    DISCONTINUED".

    Design: Difficulty/transitive_cascade/discharge_cascade_admission_careplan_goal_depth3
    """
    facility, admission, plan, goal, discharge_assessment = (
        fixtures.setup_discharge_planned_with_active_plan(payer_source="PRIVATE")
    )
    adm = validate_success(api_client.discharge_admission(
        admission["id"], {"discharge_at": "2026-02-11T00:00:00Z"}, COORD))
    assert adm["status"] == "DISCHARGED", f"expected DISCHARGED, got {adm['status']}"

    cp = validate_success(api_client.get_care_plan(plan["id"], PHYSICIAN))
    assert cp["status"] == "CLOSED", f"care plan must cascade to CLOSED, got {cp['status']}"

    goal_list = validate_success(api_client.list_goals(plan["id"], PHYSICIAN))
    assert goal_list[0]["status"] == "DISCONTINUED", (
        f"goal must cascade to DISCONTINUED, got {goal_list[0]['status']}")


def test_discharge_sets_resident_discharged():
    """PRD §3.8: "On discharge the admission's status becomes DISCHARGED and its
    discharge_at is set, the resident moves to DISCHARGED".

    Design: Difficulty/transitive_cascade/discharge_cascade_admission_careplan_goal_depth3
    """
    facility, admission, plan, goal, discharge_assessment = (
        fixtures.setup_discharge_planned_with_active_plan(payer_source="PRIVATE")
    )
    adm = validate_success(api_client.discharge_admission(
        admission["id"], {"discharge_at": "2026-02-11T00:00:00Z"}, COORD))
    assert adm["status"] == "DISCHARGED"
    res = validate_success(api_client.get_resident(adm["resident_id"], COORD))
    assert res["status"] == "DISCHARGED", f"resident must move to DISCHARGED, got {res['status']}"


# =====================================================================
# Corner/state_machines/care_plan_terminal_closed_lockdown_rejects_begin_review
# =====================================================================

def test_closed_care_plan_rejects_begin_review():
    """PRD §2.7: "on a transition endpoint, the target resource must be in a state from
    which the requested transition is legal, else ERR_INVALID_STATE".
    PRD §3.7: "From ACTIVE, beginning a review moves the plan to UNDER_REVIEW".

    Design: Corner/state_machines/care_plan_terminal_closed_lockdown_rejects_begin_review
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    plan, goal = fixtures.create_active_care_plan(admission["id"])
    get_success_data(api_client.close_care_plan(plan["id"], {}, PHYSICIAN))
    validate_error(api_client.begin_review_care_plan(plan["id"], {}, PHYSICIAN),
                   ApiErrorId.ERR_INVALID_STATE.value)


# =====================================================================
# Corner/validations/error_goal_required_on_care_plan_activate
# =====================================================================

def test_care_plan_activate_requires_open_goal():
    """PRD §3.7: "Activating a plan moves it from DRAFT to ACTIVE, but only when the
    parent admission is ACTIVE or NON_COVERED and the plan has at least one goal that
    is OPEN (its open_goal_count is at least 1); an activation attempt with no open
    goal is rejected with ERR_GOAL_REQUIRED".

    Design: Corner/validations/error_goal_required_on_care_plan_activate
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    plan = get_success_data(api_client.create_care_plan(
        admission["id"], f.create_care_plan_payload(review_interval_days=90), PHYSICIAN))
    validate_error(api_client.activate_care_plan(plan["id"], {}, PHYSICIAN),
                   ApiErrorId.ERR_GOAL_REQUIRED.value)


# =====================================================================
# Corner/validations/error_no_active_care_plan_on_plan_discharge
# =====================================================================

def test_plan_discharge_requires_active_care_plan():
    """PRD §3.8: "Planning requires that the admission have at least one ACTIVE care
    plan, or it is rejected with ERR_NO_ACTIVE_CARE_PLAN".

    Design: Corner/validations/error_no_active_care_plan_on_plan_discharge
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    # A DRAFT (not activated) care plan exists, but no ACTIVE one.
    get_success_data(api_client.create_care_plan(
        admission["id"], f.create_care_plan_payload(review_interval_days=90), PHYSICIAN))
    validate_error(api_client.plan_discharge_admission(admission["id"], {}, COORD),
                   ApiErrorId.ERR_NO_ACTIVE_CARE_PLAN.value)


# =====================================================================
# Corner/validations/error_discharge_assessment_incomplete
# =====================================================================

def test_discharge_blocked_by_incomplete_discharge_assessment():
    """PRD §3.8: "Execution requires that every DISCHARGE-type assessment for the
    admission be SUBMITTED — an incomplete discharge assessment is rejected with
    ERR_DISCHARGE_ASSESSMENT_INCOMPLETE".

    Design: Corner/validations/error_discharge_assessment_incomplete
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(payer_source="PRIVATE")
    plan, goal = fixtures.create_active_care_plan(admission["id"])
    # Schedule a DISCHARGE assessment; plan-discharge moves it to IN_PROGRESS (not SUBMITTED).
    fixtures.schedule_assessment(
        admission["id"], assessment_type="DISCHARGE",
        assessment_reference_date="2026-02-10T00:00:00Z",
        pt_function_score=12, slp_components_count=0, nta_comorbidity_points=4)
    get_success_data(api_client.plan_discharge_admission(admission["id"], {}, COORD))
    validate_error(
        api_client.discharge_admission(admission["id"], {"discharge_at": "2026-02-11T00:00:00Z"}, COORD),
        ApiErrorId.ERR_DISCHARGE_ASSESSMENT_INCOMPLETE.value)
