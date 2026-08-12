"""Composite setup helpers for multi-step PRD workflows.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Helpers use get_success_data() so a setup
failure surfaces as a clear "Setup failed" error rather than a confusing
assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import make_specialist_headers
from .factories import (
    create_physician_payload,
    create_case_payload,
    create_offer_payload,
    create_credential_item_payload,
    create_schedule_template_payload,
    create_mentorship_payload,
    create_check_in_payload,
)
from .test_users import TEST_USERS, make_physician_headers, make_mentor_headers

RECRUITER = TEST_USERS["recruiter_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
PRACTICE_MANAGER = TEST_USERS["practice_manager_headers"]
FINANCE_ANALYST = TEST_USERS["finance_analyst_headers"]
DIRECTOR = TEST_USERS["onboarding_director_headers"]
OPERATOR = TEST_USERS["system_operator_headers"]


def _setup_fail(step: str, response):
    raise AssertionError(
        f"Setup failed at step {step!r}: HTTP {response.status_code} body={response.text}"
    )


def _ok(response, step: str, expected_status=None):
    if expected_status is not None and response.status_code != expected_status:
        _setup_fail(step, response)
    try:
        return get_success_data(response)
    except Exception:
        _setup_fail(step, response)


# --- Tier 1: basic creation -------------------------------------------------

def create_physician(**overrides):
    """Register a physician prospect. Returns the physician dict."""
    resp = api_client.create_physician(create_physician_payload(**overrides), RECRUITER)
    return _ok(resp, "create_physician", 201)


def create_case(physician_id: str, target_start_date: str = "2027-06-01"):
    """Open an onboarding case for the physician. Returns the case dict."""
    resp = api_client.create_onboarding_case(
        create_case_payload(physician_id, target_start_date=target_start_date), RECRUITER
    )
    return _ok(resp, "create_case", 201)


def create_offer(case: dict, **term_overrides):
    """Draft an offer against the case at its current version. Returns the offer dict."""
    fresh = _ok(api_client.get_onboarding_case(case["id"], RECRUITER), "re-read case")
    resp = api_client.create_offer(
        create_offer_payload(case["id"], fresh["version"], **term_overrides), RECRUITER
    )
    return _ok(resp, "create_offer", 201)


def extend_offer(offer_id: str, **term_overrides):
    resp = api_client.extend_offer(offer_id, term_overrides, RECRUITER)
    return _ok(resp, "extend_offer")


def accept_offer(offer_id: str, physician_id: str):
    resp = api_client.accept_offer(offer_id, make_physician_headers(physician_id))
    return _ok(resp, "accept_offer")


def execute_offer(offer_id: str):
    resp = api_client.execute_offer(offer_id, CONTRACT_ADMIN)
    return _ok(resp, "execute_offer")


def set_clock(to_iso8601: str):
    resp = api_client.set_clock(to_iso8601, OPERATOR)
    return _ok(resp, "set_clock")


def run_epoch():
    resp = api_client.run_epoch(OPERATOR)
    return _ok(resp, "run_epoch")


# --- Tier 2: single-entity fetch helpers ------------------------------------

def get_case(case_id: str):
    return _ok(api_client.get_onboarding_case(case_id, DIRECTOR), "get_case")


def get_offer(offer_id: str):
    return _ok(api_client.get_offer(offer_id, RECRUITER), "get_offer")


def get_credential_item(item_id: str):
    return _ok(api_client.get_credential_item(item_id, DIRECTOR), "get_credential_item")


def get_training_plan_for_case(case_id: str):
    data = _ok(
        api_client.list_training_plans(PRACTICE_MANAGER, params={"onboarding_case_id": case_id}),
        "list training plans",
    )
    assert data, f"Setup failed: no training plan found for case {case_id}"
    return data[0]


def get_module_by_code(plan_id: str, module_code: str):
    data = _ok(
        api_client.list_training_modules(
            PRACTICE_MANAGER, params={"training_plan_id": plan_id, "module_code": module_code}
        ),
        "list modules",
    )
    assert data, f"Setup failed: no {module_code} module found in plan {plan_id}"
    return data[0]


def get_panel_for_case(case_id: str):
    data = _ok(
        api_client.list_panels(PRACTICE_MANAGER, params={"onboarding_case_id": case_id}),
        "list panels",
    )
    assert data, f"Setup failed: no panel found for case {case_id}"
    return data[0]


def get_guarantee_for_case(case_id: str):
    data = _ok(
        api_client.list_income_guarantees(FINANCE_ANALYST, params={"onboarding_case_id": case_id}),
        "list guarantees",
    )
    assert data, f"Setup failed: no income guarantee found for case {case_id}"
    return data[0]


def get_milestone_for_month(case_id: str, month_offset: int):
    data = _ok(
        api_client.list_ramp_milestones(
            PRACTICE_MANAGER,
            params={"onboarding_case_id": case_id, "month_offset": month_offset},
        ),
        "list milestones",
    )
    assert data, f"Setup failed: no milestone month_offset={month_offset} for case {case_id}"
    return data[0]


# --- Tier 3: executed-offer pipeline -----------------------------------------

def setup_executed_offer(specialty="FAMILY_MEDICINE", hire_type="EXPERIENCED",
                         full_name="Dr. Pipeline", **term_overrides):
    """Physician + case + offer walked DRAFT -> EXTENDED -> ACCEPTED -> EXECUTED.

    Returns dict(physician, case, offer, plan, panel, guarantee). The case is
    re-read after execution so its version/posture are current.
    """
    physician = create_physician(specialty=specialty, hire_type=hire_type, full_name=full_name)
    case = create_case(physician["id"])
    offer = create_offer(case, **term_overrides)
    offer = extend_offer(offer["id"])
    offer = accept_offer(offer["id"], physician["id"])
    offer = execute_offer(offer["id"])
    case = get_case(case["id"])
    return {
        "physician": physician,
        "case": case,
        "offer": offer,
        "plan": get_training_plan_for_case(case["id"]),
        "panel": get_panel_for_case(case["id"]),
        "guarantee": get_guarantee_for_case(case["id"]),
    }


# --- Tier 3: credential pipeline ----------------------------------------------

def create_credential_item(case_id: str, item_type: str, **overrides):
    resp = api_client.create_credential_item(
        create_credential_item_payload(case_id, item_type, **overrides),
        TEST_USERS["credentialing_specialist_headers"],
    )
    return _ok(resp, "create_credential_item", 201)


def approve_credential_item(item_id: str, submitter_id: str = "cs-1", verifier_id: str = "cs-2"):
    """Drive an item PENDING -> APPROVED honouring segregation of duties."""
    submit_headers = make_specialist_headers(submitter_id)
    verify_headers = make_specialist_headers(verifier_id)
    _ok(api_client.submit_credential_docs(item_id, {}, submit_headers), "submit-docs")
    _ok(api_client.verify_credential_item(item_id, {}, verify_headers), "verify")
    _ok(api_client.file_credential_item(item_id, {}, submit_headers), "file")
    return _ok(api_client.approve_credential_item(item_id, DIRECTOR), "approve")


def setup_credentials_complete(case_id: str, submitter_id: str = "cs-1", verifier_id: str = "cs-2"):
    """Register and approve the three required credential types; returns their dicts."""
    items = {}
    for item_type in ("STATE_LICENSE", "DEA_REGISTRATION", "PAYER_ENROLLMENT_MEDICARE"):
        item = create_credential_item(case_id, item_type)
        items[item_type] = approve_credential_item(
            item["id"], submitter_id=submitter_id, verifier_id=verifier_id
        )
    return items


# --- Tier 3: training pipeline -------------------------------------------------

def schedule_module(module_id: str, scheduled_on: str = None):
    payload = {}
    if scheduled_on is not None:
        payload["scheduled_on"] = scheduled_on
    return _ok(api_client.schedule_training_module(module_id, payload, PRACTICE_MANAGER), "schedule module")


def complete_module(module_id: str, physician_id: str, score: int, templates_built_count=None):
    payload = {"score": score}
    if templates_built_count is not None:
        payload["templates_built_count"] = templates_built_count
    return _ok(
        api_client.complete_training_module(module_id, payload, make_physician_headers(physician_id)),
        "complete module",
    )


def complete_training(case_id: str, physician_id: str, hire_type: str = "EXPERIENCED"):
    """Schedule + complete every required module and sign the plan off.

    Returns the COMPLETE training plan. For NEW_GRAD the BILLING module is
    included and NOTE_TEMPLATES is completed with 5 templates built.
    """
    plan = get_training_plan_for_case(case_id)
    templates_required = plan["templates_required"]
    codes = ["EHR_FUNDAMENTALS", "NOTE_TEMPLATES", "ORDER_ENTRY"]
    if hire_type == "NEW_GRAD":
        codes.append("BILLING")
    for code in codes:
        module = get_module_by_code(plan["id"], code)
        if module["status"] == "COMPLETED":
            continue
        schedule_module(module["id"])
        kwargs = {"score": 90}
        if code == "NOTE_TEMPLATES":
            kwargs["templates_built_count"] = templates_required
        complete_module(module["id"], physician_id, **kwargs)
    plan = get_training_plan_for_case(case_id)
    if plan["status"] == "AWAITING_SIGNOFF":
        return _ok(api_client.signoff_training_plan(plan["id"], PRACTICE_MANAGER), "signoff plan")
    return plan


# --- Tier 3: schedule / practice pipeline ---------------------------------------

def create_active_template(case_id: str, weekday: int, start_minute: int, end_minute: int,
                           block_type: str = "CLINIC"):
    template = _ok(
        api_client.create_schedule_template(
            create_schedule_template_payload(
                case_id, weekday=weekday, start_minute=start_minute,
                end_minute=end_minute, block_type=block_type,
            ),
            PRACTICE_MANAGER,
        ),
        "create template",
        201,
    )
    return _ok(api_client.activate_schedule_template(template["id"], PRACTICE_MANAGER), "activate template")


def setup_ready_schedule(case_id: str, blocks=None):
    """Create + activate CLINIC blocks; default totals exactly 1200 weekly minutes
    (480 on weekday 1, 480 on weekday 2, 240 on weekday 3). Returns template dicts."""
    if blocks is None:
        blocks = [(1, 480, 960), (2, 480, 960), (3, 480, 720)]
    templates = []
    for weekday, start_minute, end_minute in blocks:
        templates.append(create_active_template(case_id, weekday, start_minute, end_minute))
    return templates


# --- Tier 4: full go-live --------------------------------------------------------

def setup_go_live(specialty="FAMILY_MEDICINE", hire_type="EXPERIENCED",
                  clock_after_ready="2027-06-01T09:00:00Z", full_name="Dr. Live",
                  **term_overrides):
    """Full pipeline: executed offer, credentials APPROVED, training COMPLETE,
    exactly 1200 weekly CLINIC minutes ACTIVE (or the specialty's requirement
    met by default blocks), clock advanced to the start date, panel OPEN.

    Returns dict with physician, case, offer, plan, panel, guarantee, templates.
    """
    ctx = setup_executed_offer(
        specialty=specialty, hire_type=hire_type, full_name=full_name, **term_overrides
    )
    case_id = ctx["case"]["id"]
    ctx["credentials"] = setup_credentials_complete(case_id)
    ctx["plan"] = complete_training(case_id, ctx["physician"]["id"], hire_type=hire_type)
    ctx["templates"] = setup_ready_schedule(case_id)
    set_clock(clock_after_ready)
    ctx["panel"] = _ok(api_client.open_panel(ctx["panel"]["id"], PRACTICE_MANAGER), "open panel")
    ctx["case"] = get_case(case_id)
    return ctx


# --- Tier 4: guarantee / milestone helpers -------------------------------------

def setup_active_guarantee(clock="2027-06-05T00:00:00Z", full_name="Dr. Finance",
                           **term_overrides):
    """Executed offer pipeline with the logical clock advanced and the income
    guarantee activated. Returns the pipeline context dict."""
    ctx = setup_executed_offer(full_name=full_name, **term_overrides)
    set_clock(clock)
    ctx["guarantee"] = _ok(
        api_client.activate_income_guarantee(ctx["guarantee"]["id"], FINANCE_ANALYST),
        "activate guarantee",
    )
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def report_milestone(case_id: str, month_offset: int, actual_wrvu: int, collections_cents: int):
    milestone = get_milestone_for_month(case_id, month_offset)
    return _ok(
        api_client.report_ramp_milestone(
            milestone["id"],
            {"actual_wrvu": actual_wrvu, "collections_cents": collections_cents},
            PRACTICE_MANAGER,
        ),
        "report milestone",
    )


def attest_milestone(case_id: str, month_offset: int):
    milestone = get_milestone_for_month(case_id, month_offset)
    return _ok(api_client.attest_ramp_milestone(milestone["id"], FINANCE_ANALYST), "attest milestone")


def report_and_attest(case_id: str, month_offset: int, actual_wrvu: int, collections_cents: int):
    report_milestone(case_id, month_offset, actual_wrvu, collections_cents)
    return attest_milestone(case_id, month_offset)


# --- Tier 3: mentorship helpers ---------------------------------------------------

def create_active_mentor(specialty="FAMILY_MEDICINE", full_name="Dr. Mentor", email=None):
    """Register a staff physician and mark it ACTIVE so it can serve as mentor."""
    overrides = {"specialty": specialty, "hire_type": "LEADERSHIP", "full_name": full_name}
    if email is not None:
        overrides["email"] = email
    mentor = create_physician(**overrides)
    _ok(api_client.mark_physician_active(mentor["id"], DIRECTOR), "mark-active mentor")
    return _ok(api_client.get_physician(mentor["id"], DIRECTOR), "re-read mentor")


def create_mentorship(case_id: str, mentor_id: str):
    """Create a mentorship assignment at the case's current version."""
    fresh = get_case(case_id)
    return _ok(
        api_client.create_mentorship_assignment(
            create_mentorship_payload(case_id, mentor_id, fresh["version"]), DIRECTOR
        ),
        "create mentorship",
        201,
    )


def record_check_in(assignment_id: str, mentor_id: str, day_marker: str, sentiment: str):
    return _ok(
        api_client.record_check_in(
            assignment_id,
            create_check_in_payload(day_marker, sentiment),
            make_mentor_headers(mentor_id),
        ),
        "record check-in",
        201,
    )


def setup_mentorship(specialty="FAMILY_MEDICINE", mentee_name="Dr. Mentee"):
    """Physician + case + ACTIVE mentor + ACTIVE mentorship assignment.

    Returns dict(physician, case, mentor, assignment).
    """
    physician = create_physician(specialty=specialty, full_name=mentee_name)
    case = create_case(physician["id"])
    mentor = create_active_mentor(specialty=specialty)
    assignment = create_mentorship(case["id"], mentor["id"])
    return {
        "physician": physician,
        "case": get_case(case["id"]),
        "mentor": mentor,
        "assignment": assignment,
    }
