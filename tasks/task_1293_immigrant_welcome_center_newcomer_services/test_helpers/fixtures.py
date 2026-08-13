"""Composite setup helpers.

The harness restarts the API server before every test, so every test builds its
preconditions from scratch via these helpers. All helpers use the lenient
get_success_data() validator so a broken precondition surfaces as a clear
"Setup failed" error rather than a confusing assertion failure.

Identity threading: staff-backed roles always act through headers built from the
created StaffMember's id (staff_headers()), never through a shared constant, so
ownership / authorship / segregation-of-duties checks see real entity ids.
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers

from .api_client import api_client
from .factories import (
    create_client_payload, create_staff_payload, create_organization_payload,
    create_room_payload, create_case_payload, create_assessment_payload,
    create_plan_payload, create_consent_payload, create_referral_payload,
    create_appointment_payload, create_program_payload,
    create_program_enrollment_payload, create_workshop_session_payload,
    create_workshop_enrollment_payload, create_benefit_screening_payload,
    create_funder_report_payload,
)
from .test_users import TEST_USERS

ADMIN_HEADERS = TEST_USERS["center_admin_headers"]

ROLE_BY_LEVEL = {"ADMIN": "CenterAdmin", "CASE_MANAGER": "CaseManager", "INTAKE": "IntakeSpecialist"}


def staff_headers(staff: dict) -> dict:
    """Auth headers for a persisted StaffMember, mapped from its role_level."""
    return build_user_headers(staff["id"], ROLE_BY_LEVEL[staff["role_level"]])


def partner_headers(organization: dict) -> dict:
    return build_user_headers(organization["id"], "PartnerOrg")


def client_headers(client: dict) -> dict:
    return build_user_headers(client["id"], "Client")


# --- Tier 0: atomic creators -------------------------------------------------

def create_staff_member(role_level="CASE_MANAGER", clearance_level=2,
                        full_name="Staff Member", weekly_appointment_capacity=10) -> dict:
    resp = api_client.create_staff(create_staff_payload(
        full_name=full_name, role_level=role_level, clearance_level=clearance_level,
        weekly_appointment_capacity=weekly_appointment_capacity,
    ), ADMIN_HEADERS)
    return get_success_data(resp)


def register_client(**overrides) -> dict:
    resp = api_client.create_client(create_client_payload(**overrides), ADMIN_HEADERS)
    return get_success_data(resp)


def create_partner_org(name="Partner Org", categories=("HOUSING",), capacity=5,
                       email="contact@org.test") -> dict:
    resp = api_client.create_organization(create_organization_payload(
        name=name, service_categories=list(categories), referral_capacity=capacity,
        contact_email=email,
    ), ADMIN_HEADERS)
    return get_success_data(resp)


def create_room(name="Room 1", capacity=20) -> dict:
    resp = api_client.create_room(create_room_payload(name=name, capacity=capacity), ADMIN_HEADERS)
    return get_success_data(resp)


def open_case(client, manager, **overrides) -> dict:
    resp = api_client.create_case(
        create_case_payload(client["id"], manager["id"], **overrides), staff_headers(manager))
    return get_success_data(resp)


def grant_consent(client, scope, **overrides) -> dict:
    resp = api_client.create_consent(
        create_consent_payload(client["id"], scope, **overrides), ADMIN_HEADERS)
    return get_success_data(resp)


def create_program(name="Program", kind="ESOL", capacity=5, base_fee_cents=0,
                   cost_per_completion_cents=12000) -> dict:
    resp = api_client.create_program(create_program_payload(
        name=name, kind=kind, capacity=capacity, base_fee_cents=base_fee_cents,
        cost_per_completion_cents=cost_per_completion_cents,
    ), ADMIN_HEADERS)
    return get_success_data(resp)


# --- Tier 1: state progression -----------------------------------------------

def create_draft_assessment(case, creator, score=1, **overrides) -> dict:
    resp = api_client.create_assessment(
        create_assessment_payload(case["id"], score=score, **overrides), staff_headers(creator))
    return get_success_data(resp)


def submit_assessment(assessment, actor) -> dict:
    return get_success_data(api_client.submit_assessment(assessment["id"], staff_headers(actor)))


def verify_assessment(assessment, verifier) -> dict:
    return get_success_data(api_client.verify_assessment(assessment["id"], staff_headers(verifier)))


def create_verified_assessment(case, creator, verifier, score=1, **overrides) -> dict:
    """Create -> submit -> verify (verifier != creator, per the segregation rule)."""
    asmt = create_draft_assessment(case, creator, score=score, **overrides)
    submit_assessment(asmt, creator)
    return verify_assessment(asmt, verifier)


def transition_case(case_id, to_status, actor, **extra) -> dict:
    payload = {"to_status": to_status}
    payload.update(extra)
    return get_success_data(api_client.transition_case(case_id, payload, staff_headers(actor)))


def transition_plan(plan_id, to_status, actor) -> dict:
    return get_success_data(api_client.transition_plan(plan_id, {"to_status": to_status}, staff_headers(actor)))


def get_case(case_id, actor) -> dict:
    return get_success_data(api_client.get_case(case_id, staff_headers(actor)))


def create_plan_for_case(case_id, actor, title="Service Plan", budgeted_hours=5) -> dict:
    """OCC-guarded creation: re-read the case to obtain its current version."""
    case_now = get_case(case_id, actor)
    resp = api_client.create_plan(case_id, create_plan_payload(
        title=title, budgeted_hours=budgeted_hours,
        expected_case_version=case_now["version"],
    ), staff_headers(actor))
    return get_success_data(resp)


def drive_case_to_planning(client=None, manager=None, verifier=None, score=1) -> dict:
    """Client + case + VERIFIED assessment + INTAKE->ASSESSED->PLANNING.

    Returns a context dict with all artifacts and the acting staff.
    """
    manager = manager or create_staff_member(full_name="Mgr One")
    verifier = verifier or create_staff_member(full_name="Mgr Two")
    client = client or register_client()
    case = open_case(client, manager)
    asmt = create_verified_assessment(case, manager, verifier, score=score)
    transition_case(case["id"], "ASSESSED", manager)
    case = transition_case(case["id"], "PLANNING", manager)
    return {"client": client, "case": case, "assessment": asmt,
            "manager": manager, "verifier": verifier}


def drive_case_to_active(client=None, manager=None, verifier=None, score=1,
                         plan_title="Service Plan", plan_hours=5) -> dict:
    """Full chain: verified assessment -> ASSESSED -> PLANNING -> plan -> plan ACTIVE
    -> case ACTIVE. Returns a context dict including the ACTIVE plan."""
    ctx = drive_case_to_planning(client=client, manager=manager, verifier=verifier, score=score)
    manager = ctx["manager"]
    plan = create_plan_for_case(ctx["case"]["id"], manager, title=plan_title, budgeted_hours=plan_hours)
    plan = transition_plan(plan["id"], "ACTIVE", manager)
    case = transition_case(ctx["case"]["id"], "ACTIVE", manager)
    ctx.update({"case": case, "plan": plan})
    return ctx


def suspend_case(case_id, actor) -> dict:
    return transition_case(case_id, "SUSPENDED", actor)


# --- Tier 2: referrals --------------------------------------------------------

def create_draft_referral(case, org, category, manager, **overrides) -> dict:
    resp = api_client.create_referral(
        create_referral_payload(case["id"], org["id"], category, **overrides),
        staff_headers(manager))
    return get_success_data(resp)


def send_referral(referral_id, manager) -> dict:
    return get_success_data(api_client.send_referral(referral_id, staff_headers(manager)))


def create_sent_referral(case, org, category, manager, **overrides) -> dict:
    """DRAFT -> SENT (requires the client to already hold REFERRAL_SHARE consent)."""
    ref = create_draft_referral(case, org, category, manager, **overrides)
    return send_referral(ref["id"], manager)


def create_accepted_referral(case, org, category, manager, warm_handoff=True, **overrides) -> dict:
    ref = create_sent_referral(case, org, category, manager, **overrides)
    payload = {"decision": "ACCEPTED"}
    if warm_handoff:
        payload["warm_handoff_offered"] = True
    return get_success_data(api_client.respond_referral(ref["id"], payload, partner_headers(org)))


def create_completed_referral(case, org, category, manager, **overrides) -> dict:
    ref = create_accepted_referral(case, org, category, manager, **overrides)
    get_success_data(api_client.confirm_handoff(ref["id"], staff_headers(manager)))
    return get_success_data(api_client.complete_referral(ref["id"], staff_headers(manager)))


def setup_case_with_sent_referral(categories=("HOUSING",), category="HOUSING",
                                  org_capacity=5, accompaniment_consent=False) -> dict:
    """Client (REFERRAL_SHARE consent) + case + ACTIVE org + SENT referral."""
    manager = create_staff_member(full_name="Mgr One")
    client = register_client()
    grant_consent(client, "REFERRAL_SHARE")
    if accompaniment_consent:
        grant_consent(client, "ACCOMPANIMENT")
    case = open_case(client, manager)
    org = create_partner_org(categories=categories, capacity=org_capacity)
    referral = create_sent_referral(case, org, category, manager)
    return {"client": client, "case": case, "org": org, "referral": referral,
            "manager": manager}


# --- Tier 3: appointments ------------------------------------------------------

def create_appointment(case, advocate, kind="DOCUMENT_ID",
                       starts_at="2026-08-10T10:00:00Z", ends_at="2026-08-10T11:00:00Z",
                       actor=None, **overrides) -> dict:
    actor = actor or advocate
    resp = api_client.create_appointment(create_appointment_payload(
        case["id"], advocate["id"], kind=kind, starts_at=starts_at, ends_at=ends_at,
        **overrides), staff_headers(actor))
    return get_success_data(resp)


def confirm_appointment(appointment_id, actor) -> dict:
    return get_success_data(api_client.confirm_appointment(appointment_id, staff_headers(actor)))


# --- Tier 4: benefits / programs ------------------------------------------------

def create_screening(case, actor, stated_income=1000000) -> dict:
    resp = api_client.create_benefit_screening(
        create_benefit_screening_payload(case["id"], stated_income), staff_headers(actor))
    return get_success_data(resp)


def run_screening(screening, actor) -> dict:
    return get_success_data(api_client.run_benefit_screening(screening["id"], staff_headers(actor)))


def verify_screening(screening, actor, documented_income) -> dict:
    return get_success_data(api_client.verify_benefit_screening(
        screening["id"], {"documented_annual_income_cents": documented_income}, staff_headers(actor)))


def create_verified_screening(case, actor, income) -> dict:
    scr = create_screening(case, actor, stated_income=income)
    run_screening(scr, actor)
    return verify_screening(scr, actor, income)


def apply_to_program(case, program, actor) -> dict:
    resp = api_client.create_program_enrollment(
        create_program_enrollment_payload(case["id"], program["id"]), staff_headers(actor))
    return get_success_data(resp)


def transition_enrollment(enrollment_id, to_status, actor, **extra) -> dict:
    payload = {"to_status": to_status}
    payload.update(extra)
    return get_success_data(api_client.transition_program_enrollment(
        enrollment_id, payload, staff_headers(actor)))


# --- Tier 5: workshops -----------------------------------------------------------

def create_session(room, manager, capacity=5, starts_at="2026-08-20T10:00:00Z",
                   ends_at="2026-08-20T11:00:00Z", title="Orientation") -> dict:
    resp = api_client.create_workshop_session(create_workshop_session_payload(
        room["id"], title=title, capacity=capacity, starts_at=starts_at, ends_at=ends_at,
    ), staff_headers(manager))
    return get_success_data(resp)


def enroll_in_session(session, case, actor) -> dict:
    resp = api_client.create_workshop_enrollment(
        create_workshop_enrollment_payload(session["id"], case["id"]), staff_headers(actor))
    return get_success_data(resp)


def get_session(session_id, actor) -> dict:
    return get_success_data(api_client.get_workshop_session(session_id, staff_headers(actor)))


def get_enrollment(enrollment_id, actor) -> dict:
    return get_success_data(api_client.get_workshop_enrollment(enrollment_id, staff_headers(actor)))


def setup_session_with_cases(num_cases=3, capacity=2, starts_at="2026-08-20T10:00:00Z",
                             ends_at="2026-08-20T11:00:00Z", room_name="Room W") -> dict:
    """Room + session + N (client, case) pairs ready for enrollment."""
    manager = create_staff_member(full_name="Mgr One")
    room = create_room(name=room_name)
    session = create_session(room, manager, capacity=capacity,
                             starts_at=starts_at, ends_at=ends_at)
    cases = []
    for _ in range(num_cases):
        client = register_client()
        cases.append(open_case(client, manager))
    return {"manager": manager, "room": room, "session": session, "cases": cases}


# --- Tier 6: clock / sweeps ------------------------------------------------------

def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN_HEADERS))


def run_sweeps() -> dict:
    return get_success_data(api_client.run_sweeps(ADMIN_HEADERS))


# --- Tier 7: funder reports -------------------------------------------------------

def create_funder_report(period_start="2026-08-01T00:00:00Z", period_end="2026-09-01T00:00:00Z",
                         funding_streams=None) -> dict:
    streams = funding_streams or [{"stream_name": "City", "share_pct": 100}]
    resp = api_client.create_funder_report(create_funder_report_payload(
        period_start=period_start, period_end=period_end, funding_streams=streams,
    ), ADMIN_HEADERS)
    return get_success_data(resp)


def setup_report_outcome_mix() -> dict:
    """Outcome mix inside window [2026-08-01, 2026-09-01): one COMPLETED program
    enrollment, two COMPLETED referrals, one ATTENDED workshop enrollment.

    Client 1 (program + workshop outcomes) holds DATA_REPORTING consent;
    client 2 (the two referral outcomes) does not.
    """
    manager = create_staff_member(full_name="Mgr One")
    verifier = create_staff_member(full_name="Mgr Two")
    client1 = register_client(full_name="Client One", household_size=3)
    client2 = register_client(full_name="Client Two", household_size=4)
    grant_consent(client1, "DATA_REPORTING")
    grant_consent(client2, "REFERRAL_SHARE")

    # Program enrollment completion for client 1 (free program, case ACTIVE).
    ctx = drive_case_to_active(client=client1, manager=manager, verifier=verifier, score=1)
    program = create_program(name="Workforce Bootcamp", kind="WORKFORCE", capacity=5,
                             base_fee_cents=0, cost_per_completion_cents=12000)
    enrollment = apply_to_program(ctx["case"], program, manager)
    transition_enrollment(enrollment["id"], "ELIGIBLE", manager)
    transition_enrollment(enrollment["id"], "ENROLLED", manager)
    transition_enrollment(enrollment["id"], "COMPLETED", manager)

    # Two completed referrals for client 2.
    case2 = open_case(client2, manager)
    org_x = create_partner_org(name="Org X", categories=("EMPLOYMENT",), capacity=5, email="x@org.test")
    org_y = create_partner_org(name="Org Y", categories=("EMPLOYMENT",), capacity=5, email="y@org.test")
    ref1 = create_completed_referral(case2, org_x, "EMPLOYMENT", manager)
    ref2 = create_completed_referral(case2, org_y, "EMPLOYMENT", manager)

    # One attended workshop enrollment for client 1.
    room = create_room(name="Room A", capacity=30)
    session = create_session(room, manager, capacity=10,
                             starts_at="2026-08-05T10:00:00Z", ends_at="2026-08-05T11:00:00Z")
    wke = enroll_in_session(session, ctx["case"], manager)
    set_clock("2026-08-06T00:00:00Z")
    run_sweeps()
    get_success_data(api_client.mark_attendance(wke["id"], {"attended": True}, staff_headers(manager)))

    return {"manager": manager, "verifier": verifier, "client1": client1, "client2": client2,
            "case1": ctx["case"], "case2": case2, "program": program, "enrollment": enrollment,
            "org_x": org_x, "org_y": org_y, "ref1": ref1, "ref2": ref2,
            "room": room, "session": session, "workshop_enrollment": wke}
