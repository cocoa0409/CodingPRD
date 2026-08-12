"""Composite setup helpers for multi-step preconditions.

Every helper builds preconditions from scratch using only PRD-declared endpoints
(the runner restarts the server before each test, so no state carries over).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CANONICAL_PROFILE_PAYLOAD,
    CANONICAL_START_DATE,
    DEFAULT_CLOCK_ISO,
)
from .factories import (
    create_role_profile_payload,
    create_employee_payload,
    create_new_hire_payload,
    create_onboarding_case_payload,
    create_orientation_session_payload,
    create_payroll_handoff_payload,
)
from .test_users import (
    TEST_USERS,
    make_hiring_manager_headers,
    make_buddy_headers,
    make_new_hire_headers,
    make_hr_admin_headers,
    make_adjudicator_headers,
)

HR = TEST_USERS["hr_admin_headers"]
IT = TEST_USERS["it_provisioner_headers"]
PAYROLL = TEST_USERS["payroll_ops_headers"]


# ---------------------------------------------------------------------------
# Tier 1 — Atomic entity creation
# ---------------------------------------------------------------------------

def create_published_profile(**profile_overrides):
    """Create a role profile and publish it once. Returns the profile dict."""
    payload = create_role_profile_payload(**profile_overrides)
    p = get_success_data(api_client.create_role_profile(payload, HR))
    p = get_success_data(api_client.publish_role_profile(p["id"], HR))
    return p


def create_employee(**overrides):
    return get_success_data(api_client.create_employee(create_employee_payload(**overrides), HR))


def create_new_hire(**overrides):
    return get_success_data(api_client.create_new_hire(create_new_hire_payload(**overrides), HR))


def create_manager_and_buddy():
    """Return (manager, buddy) with buddy reporting to manager."""
    mgr = create_employee()
    bud = create_employee(manager_id=mgr["id"])
    return mgr, bud


def create_case(manager, buddy, new_hire, profile, **case_overrides):
    """Create an onboarding case. Returns the case dict (PRE_BOARDING)."""
    payload = create_onboarding_case_payload(
        new_hire_id=new_hire["id"],
        role_profile_id=profile["id"],
        manager_id=manager["id"],
        buddy_id=buddy["id"],
        **case_overrides,
    )
    return get_success_data(api_client.create_onboarding_case(payload, HR))


# ---------------------------------------------------------------------------
# Tier 2 — Canonical case scaffold (profile + people + case)
# ---------------------------------------------------------------------------

def setup_basic_case(start_date=CANONICAL_START_DATE, **case_overrides):
    """Canonical scaffold: published profile + manager/buddy + new hire + case.

    Returns dict with keys: profile, manager, buddy, new_hire, case.
    The case is in PRE_BOARDING with all generated children.
    """
    profile = create_published_profile()
    mgr, bud = create_manager_and_buddy()
    nh = create_new_hire(start_date=start_date)
    case = create_case(mgr, bud, nh, profile, start_date=start_date, **case_overrides)
    return {
        "profile": profile,
        "manager": mgr,
        "buddy": bud,
        "new_hire": nh,
        "case": case,
    }


def get_case_tasks(case_id):
    return get_success_data(api_client.list_case_tasks(case_id, HR))


def get_case_trainings(case_id):
    return get_success_data(api_client.list_case_training_assignments(case_id, HR))


def get_case_checkins(case_id):
    return get_success_data(api_client.list_case_check_ins(case_id, HR))


def get_case_cycles(case_id):
    return get_success_data(api_client.list_case_probation_cycles(case_id, HR))


def get_case_clearances(case_id):
    return get_success_data(api_client.list_case_clearance_cases(case_id, HR))


def get_case_orders(case_id):
    return get_success_data(api_client.list_case_provisioning_orders(case_id, HR))


def get_case_handoffs(case_id):
    return get_success_data(api_client.list_case_payroll_handoffs(case_id, HR))


def get_case_surveys(case_id):
    return get_success_data(api_client.list_case_surveys(case_id, HR))


def get_summary(case_id):
    return get_success_data(api_client.get_case_summary(case_id, HR))


# ---------------------------------------------------------------------------
# Tier 3 — Lifecycle progression
# ---------------------------------------------------------------------------

def approve_required_tasks(case_id, new_hire):
    """Submit + APPROVE both required tasks (t1 DOCUMENT_UPLOAD, t2 FORM_ACK)."""
    nh_headers = make_new_hire_headers(new_hire["id"])
    tasks = get_case_tasks(case_id)
    t1 = next(t for t in tasks if t["task_kind"] == "DOCUMENT_UPLOAD")
    t2 = next(t for t in tasks if t["task_kind"] == "FORM_ACK")
    get_success_data(api_client.submit_task(t1["id"], {"document_ref": "doc://id-1"}, nh_headers))
    get_success_data(api_client.review_task(t1["id"], {"decision": "APPROVE"}, HR))
    get_success_data(api_client.submit_task(t2["id"], {"note": "signed"}, nh_headers))
    get_success_data(api_client.review_task(t2["id"], {"decision": "APPROVE"}, HR))
    return t1, t2


def submit_for_clearance(case_id, initiator_user_id="hr-1"):
    """PRE_BOARDING -> CLEARANCE_IN_PROGRESS; returns the clearance case."""
    hdrs = make_hr_admin_headers(initiator_user_id)
    get_success_data(api_client.submit_for_clearance(case_id, hdrs))
    return get_case_clearances(case_id)[0]


def pass_clearance(case_id, initiator_user_id="hr-1"):
    """Record BACKGROUND+REFERENCE PASSED so the case advances to PROVISIONING."""
    clearance = get_case_clearances(case_id)[0]
    get_success_data(api_client.record_clearance_result(
        clearance["id"], {"component": "BACKGROUND", "result": "PASSED"}, HR))
    get_success_data(api_client.record_clearance_result(
        clearance["id"], {"component": "REFERENCE", "result": "PASSED"}, HR))
    return get_success_data(api_client.list_case_clearance_cases(case_id, HR))[0]


def escalate_clearance(case_id, initiator_user_id="hr-1"):
    """Submit for clearance then record BACKGROUND FAILED to force ESCALATED."""
    submit_for_clearance(case_id, initiator_user_id=initiator_user_id)
    clearance = get_case_clearances(case_id)[0]
    get_success_data(api_client.record_clearance_result(
        clearance["id"], {"component": "BACKGROUND", "result": "FAILED"}, HR))
    return get_success_data(api_client.list_case_clearance_cases(case_id, HR))[0]


def setup_case_in_provisioning(start_date=CANONICAL_START_DATE, **case_overrides):
    """Case fully through CLEARANCE_IN_PROGRESS into PROVISIONING with a DRAFT order.

    Returns dict with keys of setup_basic_case plus: clearance, order, items.
    """
    ctx = setup_basic_case(start_date=start_date, **case_overrides)
    case_id = ctx["case"]["id"]
    approve_required_tasks(case_id, ctx["new_hire"])
    clearance = submit_for_clearance(case_id)
    pass_clearance(case_id)
    order = get_case_orders(case_id)[0]
    items = get_success_data(api_client.list_provisioning_items(order["id"], HR))
    ctx.update({"clearance": clearance, "order": order, "items": items})
    return ctx


def fulfill_order(order_id):
    """Submit the order, then drive every item PENDING -> IN_FULFILLMENT -> DONE."""
    get_success_data(api_client.submit_provisioning_order(order_id, HR))
    items = get_success_data(api_client.list_provisioning_items(order_id, HR))
    for it in items:
        get_success_data(api_client.transition_provisioning_item(it["id"], {"to": "IN_FULFILLMENT"}, IT))
        get_success_data(api_client.transition_provisioning_item(it["id"], {"to": "DONE"}, IT))
    return get_success_data(api_client.get_provisioning_order(order_id, HR))


def setup_day_one_ready(start_date=CANONICAL_START_DATE, session=None, **case_overrides):
    """Case in DAY_ONE_READY: order FULFILLED and orientation BOOKED.

    Returns ctx dict with keys: profile, manager, buddy, new_hire, case,
    clearance, order, items, session.
    """
    ctx = setup_case_in_provisioning(start_date=start_date, **case_overrides)
    fulfill_order(ctx["order"]["id"])
    if session is None:
        session = get_success_data(api_client.create_orientation_session(
            create_orientation_session_payload(
                room="R1",
                starts_at=f"{start_date}T09:00:00Z",
                ends_at=f"{start_date}T12:00:00Z",
                capacity=10,
            ), HR))
    get_success_data(api_client.book_orientation(ctx["case"]["id"], {"session_id": session["id"]}, HR))
    ctx["session"] = session
    ctx["case"] = get_success_data(api_client.get_onboarding_case(ctx["case"]["id"], HR))
    return ctx


def setup_in_progress(start_date=CANONICAL_START_DATE, **case_overrides):
    """Case in IN_PROGRESS: DAY_ONE_READY then clock advanced to start_dateT00:00:00Z.

    Returns ctx dict; ctx['case'] reflects the IN_PROGRESS case after the sweep.
    """
    ctx = setup_day_one_ready(start_date=start_date, **case_overrides)
    get_success_data(api_client.set_current_utc({"to_iso8601": f"{start_date}T00:00:00Z"}, HR))
    ctx["case"] = get_success_data(api_client.get_onboarding_case(ctx["case"]["id"], HR))
    return ctx


def setup_probation(start_date=CANONICAL_START_DATE, clock_after="2026-08-03T00:00:00Z", **case_overrides):
    """Case in PROBATION: all trainings + at least one MANAGER check-in completed.

    Returns ctx dict; ctx includes trainings/checkins/cycles lists.
    """
    ctx = setup_in_progress(start_date=start_date, **case_overrides)
    case_id = ctx["case"]["id"]
    nh_headers = make_new_hire_headers(ctx["new_hire"]["id"])
    mgr_headers = make_hiring_manager_headers(ctx["manager"]["id"])
    trainings = get_case_trainings(case_id)
    checkins = get_case_checkins(case_id)
    mgr_checkin = next(c for c in checkins if c["kind"] == "MANAGER")
    get_success_data(api_client.complete_check_in(mgr_checkin["id"], {"productivity_rating": 4}, mgr_headers))
    for tr in trainings:
        get_success_data(api_client.complete_training(tr["id"], {"score": 90}, nh_headers))
    if clock_after is not None:
        get_success_data(api_client.set_current_utc({"to_iso8601": clock_after}, HR))
    ctx["case"] = get_success_data(api_client.get_onboarding_case(case_id, HR))
    ctx["trainings"] = trainings
    ctx["checkins"] = get_case_checkins(case_id)
    ctx["cycles"] = get_case_cycles(case_id)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — Targeted composite fixtures
# ---------------------------------------------------------------------------

def setup_case_with_booked_session(start_date=CANONICAL_START_DATE, room="R1", capacity=1):
    """Case in PROVISIONING plus a session already booked by a second case.

    Returns dict with case_a (in PROVISIONING, not yet booked), case_b (booked), session.
    Used for FULL-session and capacity-boundary tests.
    """
    profile = create_published_profile()
    mgr, bud = create_manager_and_buddy()
    nh_a = create_new_hire(start_date=start_date)
    case_a = create_case(mgr, bud, nh_a, profile, start_date=start_date)
    approve_required_tasks(case_a["id"], nh_a)
    submit_for_clearance(case_a["id"])
    pass_clearance(case_a["id"])

    nh_b = create_new_hire(start_date=start_date)
    case_b = create_case(mgr, bud, nh_b, profile, start_date=start_date)
    approve_required_tasks(case_b["id"], nh_b)
    submit_for_clearance(case_b["id"])
    pass_clearance(case_b["id"])

    session = get_success_data(api_client.create_orientation_session(
        create_orientation_session_payload(
            room=room,
            starts_at=f"{start_date}T13:00:00Z",
            ends_at=f"{start_date}T15:00:00Z",
            capacity=capacity,
        ), HR))
    get_success_data(api_client.book_orientation(case_b["id"], {"session_id": session["id"]}, HR))
    return {
        "profile": profile, "manager": mgr, "buddy": bud,
        "nh_a": nh_a, "case_a": case_a, "nh_b": nh_b, "case_b": case_b,
        "session": get_success_data(api_client.list_orientation_sessions(HR, params={"room": room}))[0],
    }


def setup_handoff_ready(start_date=CANONICAL_START_DATE, **case_overrides):
    """Case in IN_PROGRESS with a fresh logical clock at start_date and case version captured.

    Returns ctx dict plus key 'case_version' (int) for the OCC expected_case_version field.
    """
    ctx = setup_in_progress(start_date=start_date, **case_overrides)
    case = get_success_data(api_client.get_onboarding_case(ctx["case"]["id"], HR))
    ctx["case"] = case
    ctx["case_version"] = case["version"]
    return ctx


def create_handoff_for_case(case_id, expected_case_version, **payload_overrides):
    payload = create_payroll_handoff_payload(
        expected_case_version=expected_case_version,
        **payload_overrides,
    )
    return get_success_data(api_client.create_payroll_handoff(case_id, payload, HR))


def setup_probation_with_handoff(start_date=CANONICAL_START_DATE, clock_after="2026-08-03T00:00:00Z"):
    """Case in PROBATION with a DRAFT payroll handoff in place (created at day one)."""
    ctx = setup_in_progress(start_date=start_date)
    case_id = ctx["case"]["id"]
    case = get_success_data(api_client.get_onboarding_case(case_id, HR))
    handoff = create_handoff_for_case(case_id, case["version"])
    nh_headers = make_new_hire_headers(ctx["new_hire"]["id"])
    mgr_headers = make_hiring_manager_headers(ctx["manager"]["id"])
    trainings = get_case_trainings(case_id)
    checkins = get_case_checkins(case_id)
    mgr_checkin = next(c for c in checkins if c["kind"] == "MANAGER")
    get_success_data(api_client.complete_check_in(mgr_checkin["id"], {"productivity_rating": 4}, mgr_headers))
    for tr in trainings:
        get_success_data(api_client.complete_training(tr["id"], {"score": 90}, nh_headers))
    get_success_data(api_client.set_current_utc({"to_iso8601": clock_after}, HR))
    ctx["case"] = get_success_data(api_client.get_onboarding_case(case_id, HR))
    ctx["trainings"] = trainings
    ctx["checkins"] = get_case_checkins(case_id)
    ctx["cycles"] = get_case_cycles(case_id)
    ctx["handoff"] = get_success_data(api_client.get_payroll_handoff(handoff["id"], HR))
    return ctx
