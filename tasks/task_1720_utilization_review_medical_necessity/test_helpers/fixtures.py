"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via PRD-declared
endpoints (the server is restarted before each test, so nothing carries
over). Setup calls use get_success_data() so failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading (PRD §2.1): AttendingPhysician and PhysicianAdvisor are
entity-backed roles, so peer-to-peer calls use
make_attending_headers(<Physician.id>) and advisor-side calls use
make_advisor_headers(<Physician.id>) — never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ADMIT_AT,
    DENIAL_DECIDED_AT,
    EXPECTED_DISCHARGE_AT,
    LONG_CLINICAL_SUMMARY,
)
from .factories import (
    appeal_decision_payload,
    apply_credit_payload,
    auth_payer_decision_payload,
    cc44_committee_payload,
    cc44_concurrence_payload,
    cc44_rescind_payload,
    create_admission_review_payload,
    create_authorization_request_payload,
    create_avoidable_day_payload,
    create_cc44_payload,
    create_concurrent_review_payload,
    create_p2p_payload,
    create_payer_payload,
    create_physician_payload,
    create_utilization_case_payload,
    discharge_payload,
    file_appeal_payload,
    reschedule_p2p_payload,
    resolve_escalation_payload,
    resubmit_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_advisor_headers,
    make_attending_headers,
)

DIRECTOR = TEST_USERS["ur_director_headers"]
NURSE = TEST_USERS["ur_nurse_headers"]
PAYER_REVIEWER = TEST_USERS["payer_reviewer_headers"]
CASE_MANAGER = TEST_USERS["case_manager_headers"]
APPEALS = TEST_USERS["appeals_coordinator_headers"]
ANY_READ = TEST_USERS["ur_nurse_headers"]  # GET endpoints allow any role (PRD §4)


# ---------------------------------------------------------------------------
# Tier 0: single-call wrappers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Drive the server logical clock (PRD §2.11)."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), DIRECTOR))


def make_payer(**overrides) -> dict:
    return get_success_data(
        api_client.create_payer(create_payer_payload(**overrides), DIRECTOR))


def make_physician(is_advisor: bool = False, **overrides) -> dict:
    return get_success_data(api_client.create_physician(
        create_physician_payload(is_advisor=is_advisor, **overrides), DIRECTOR))


def make_advisor(**overrides) -> dict:
    overrides.setdefault("full_name", "Dr. Advisor")
    overrides.setdefault("specialty", "Utilization Medicine")
    return make_physician(is_advisor=True, **overrides)


def make_case(payer_id: str, attending_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_utilization_case(
        create_utilization_case_payload(payer_id, attending_id, **overrides),
        NURSE))


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_utilization_case(case_id, ANY_READ))


def case_version(case_id: str) -> int:
    return get_case(case_id)["version"]


def discharge_case(case_id: str, discharge_at: str) -> dict:
    return get_success_data(api_client.discharge_case(
        case_id, discharge_payload(discharge_at), NURSE))


def make_review(case_id: str, **overrides) -> dict:
    """Create a DRAFT admission review (PRD §3.2)."""
    return get_success_data(api_client.create_admission_review(
        case_id, create_admission_review_payload(**overrides), NURSE))


def submit_review(review_id: str) -> dict:
    return get_success_data(
        api_client.submit_admission_review(review_id, {}, NURSE))


def get_review(review_id: str) -> dict:
    return get_success_data(api_client.get_admission_review(review_id, ANY_READ))


def make_auth(case_id: str, expected_case_version=None, **overrides) -> dict:
    """Create an authorization request; the OCC field expected_case_version
    (PRD §2.10) is re-read from the live case when not supplied."""
    if expected_case_version is None:
        expected_case_version = case_version(case_id)
    return get_success_data(api_client.create_authorization_request(
        case_id,
        create_authorization_request_payload(expected_case_version, **overrides),
        NURSE))


def get_auth(auth_id: str) -> dict:
    return get_success_data(api_client.get_authorization_request(auth_id, ANY_READ))


def list_auths(case_id: str) -> list:
    return get_success_data(api_client.list_authorization_requests(case_id, ANY_READ))


def approve_auth(auth_id: str, certified_day_start: int = 1,
                 certified_day_count: int = 3) -> dict:
    return get_success_data(api_client.auth_payer_decision(
        auth_id,
        auth_payer_decision_payload(
            "APPROVE", certified_day_start=certified_day_start,
            certified_day_count=certified_day_count),
        PAYER_REVIEWER))


def pend_auth(auth_id: str, pend_reason: str = "Need updated clinical notes") -> dict:
    return get_success_data(api_client.auth_payer_decision(
        auth_id, auth_payer_decision_payload("PEND", pend_reason=pend_reason),
        PAYER_REVIEWER))


def deny_auth(auth_id: str, denial_reason_code: str = "CRITERIA_NOT_MET") -> dict:
    return get_success_data(api_client.auth_payer_decision(
        auth_id,
        auth_payer_decision_payload("DENY", denial_reason_code=denial_reason_code),
        PAYER_REVIEWER))


def resubmit_auth(auth_id: str, clinical_summary: str = LONG_CLINICAL_SUMMARY) -> dict:
    return get_success_data(api_client.resubmit_authorization_request(
        auth_id, resubmit_payload(clinical_summary), NURSE))


def list_denials_of_case(case_id: str) -> list:
    return get_success_data(api_client.list_denial_cases(case_id, ANY_READ))


def denial_of_case(case_id: str) -> dict:
    denials = list_denials_of_case(case_id)
    assert denials, "Setup failed: expected a denial case on the case"
    return denials[0]


def get_denial(denial_id: str) -> dict:
    return get_success_data(api_client.get_denial_case(denial_id, ANY_READ))


def make_concurrent_review(auth_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_concurrent_review(
        auth_id, create_concurrent_review_payload(**overrides), NURSE))


def list_concurrent_reviews(auth_id: str) -> list:
    return get_success_data(api_client.list_concurrent_reviews(auth_id, ANY_READ))


def get_concurrent_review(auth_id: str, review_id: str) -> dict:
    for review in list_concurrent_reviews(auth_id):
        if review["id"] == review_id:
            return review
    raise AssertionError(f"Setup failed: concurrent review {review_id} not listed")


def make_conference(auth_id: str, advisor_id: str, attending_id: str,
                    scheduled_start_at: str = "2026-08-03T10:00:00Z",
                    scheduled_end_at: str = "2026-08-03T10:30:00Z") -> dict:
    """Schedule a peer-to-peer conference as the case attending (PRD §3.5)."""
    return get_success_data(api_client.create_p2p_conference(
        auth_id,
        create_p2p_payload(advisor_id, scheduled_start_at, scheduled_end_at),
        make_attending_headers(attending_id)))


def get_conference(conference_id: str) -> dict:
    return get_success_data(api_client.get_p2p_conference(conference_id, ANY_READ))


def list_conferences_of_auth(auth_id: str) -> list:
    return get_success_data(api_client.list_p2p_conferences(auth_id, ANY_READ))


def make_cc44(case_id: str, expected_case_version=None, **overrides) -> dict:
    """Initiate a CC44 request; the OCC field expected_case_version
    (PRD §2.10) is re-read from the live case when not supplied."""
    if expected_case_version is None:
        expected_case_version = case_version(case_id)
    return get_success_data(api_client.create_cc44_request(
        case_id, create_cc44_payload(expected_case_version, **overrides), NURSE))


def list_cc44(case_id: str) -> list:
    return get_success_data(api_client.list_cc44_requests(case_id, ANY_READ))


def get_cc44(case_id: str, cc44_id: str) -> dict:
    for request in list_cc44(case_id):
        if request["id"] == cc44_id:
            return request
    raise AssertionError(f"Setup failed: CC44 request {cc44_id} not listed")


def concur_cc44(cc44_id: str, attending_id: str, decision: str = "CONCUR") -> dict:
    return get_success_data(api_client.cc44_concurrence(
        cc44_id, cc44_concurrence_payload(decision),
        make_attending_headers(attending_id)))


def committee_cc44(cc44_id: str, advisor_id: str, decision: str = "APPROVE") -> dict:
    return get_success_data(api_client.cc44_committee_review(
        cc44_id, cc44_committee_payload(decision), make_advisor_headers(advisor_id)))


def add_avoidable_day(case_id: str, day_date: str, barrier_code: str,
                      barrier_weight: int) -> dict:
    return get_success_data(api_client.create_avoidable_day(
        case_id,
        create_avoidable_day_payload(day_date, barrier_code, barrier_weight),
        CASE_MANAGER))


def list_avoidable_days(case_id: str) -> list:
    return get_success_data(api_client.list_avoidable_days(case_id, ANY_READ))


def list_escalations(case_id: str) -> list:
    return get_success_data(api_client.list_escalation_cases(case_id, ANY_READ))


def escalation_of_case(case_id: str) -> dict:
    escalations = list_escalations(case_id)
    assert escalations, "Setup failed: expected an escalation case"
    return escalations[0]


def file_appeal(denial_id: str, appeal_level: int = 1, **overrides) -> dict:
    return get_success_data(api_client.file_appeal(
        denial_id, file_appeal_payload(appeal_level, **overrides), APPEALS))


def list_appeals(denial_id: str) -> list:
    return get_success_data(api_client.list_appeals(denial_id, ANY_READ))


def get_appeal(denial_id: str, appeal_id: str) -> dict:
    for appeal in list_appeals(denial_id):
        if appeal["id"] == appeal_id:
            return appeal
    raise AssertionError(f"Setup failed: appeal {appeal_id} not listed")


def decide_appeal(appeal_id: str, decision: str, **overrides) -> dict:
    return get_success_data(api_client.appeal_decision(
        appeal_id, appeal_decision_payload(decision, **overrides), PAYER_REVIEWER))


def list_audit_events(case_id: str) -> list:
    return get_success_data(api_client.list_audit_events(case_id, ANY_READ))


def stagger_clock(minute: int):
    """Advance the logical clock to a distinct minute so that sequentially
    created records carry strictly increasing creation timestamps under any
    clock implementation."""
    set_clock(f"2026-08-04T00:{minute:02d}:00Z")


# ---------------------------------------------------------------------------
# Tier 1/2: base scenario builders
# ---------------------------------------------------------------------------

def setup_case(plan_class: str = "MEDICARE",
               avoidable_attribution_method: str = "FIRST_CAUSE",
               patient_mrn: str = "MRN-BASE", with_advisor: bool = False,
               **payer_overrides) -> dict:
    """Payer + attending physician (+ optional advisor) + one open case.

    Returns {"payer", "attending", "advisor"?, "case"}."""
    payer = make_payer(plan_class=plan_class,
                       avoidable_attribution_method=avoidable_attribution_method,
                       **payer_overrides)
    attending = make_physician()
    ctx = {
        "payer": payer,
        "attending": attending,
        "case": make_case(payer["id"], attending["id"], patient_mrn=patient_mrn),
    }
    if with_advisor:
        ctx["advisor"] = make_advisor()
    return ctx


def setup_case_with_submitted_review(severity: int = 2, intensity: int = 2,
                                     comorbidity: int = 0,
                                     attestation: bool = False,
                                     plan_class: str = "MEDICARE",
                                     criteria_set: str = "INTERQUAL",
                                     with_advisor: bool = False,
                                     patient_mrn: str = "MRN-REV") -> dict:
    """Case plus one SUBMITTED admission review with pinned point inputs.

    Default inputs (2/2/0) score 20 < 60, so the default review lands
    CRITERIA_NOT_MET (PRD §3.2)."""
    ctx = setup_case(plan_class=plan_class, with_advisor=with_advisor,
                     patient_mrn=patient_mrn)
    review = make_review(
        ctx["case"]["id"], criteria_set=criteria_set,
        severity_of_illness_points=severity,
        intensity_of_service_points=intensity,
        comorbidity_count=comorbidity,
        two_midnight_attestation=attestation)
    ctx["review"] = submit_review(review["id"])
    return ctx


def setup_submitted_auth(patient_mrn: str = "MRN-AUTH", **case_kwargs) -> dict:
    """Case with one authorization request sitting SUBMITTED."""
    ctx = setup_case(patient_mrn=patient_mrn, **case_kwargs)
    ctx["auth"] = make_auth(ctx["case"]["id"])
    return ctx


def setup_approved_auth(clock: str = DENIAL_DECIDED_AT, certified_day_start: int = 1,
                        certified_day_count: int = 3,
                        requested_day_count: int = 3,
                        patient_mrn: str = "MRN-APP", **case_kwargs) -> dict:
    """Case with one APPROVED authorization carrying the certified interval
    [certified_day_start, certified_day_start + certified_day_count)."""
    if clock is not None:
        set_clock(clock)
    ctx = setup_case(patient_mrn=patient_mrn, **case_kwargs)
    ctx["auth"] = make_auth(ctx["case"]["id"],
                            requested_day_count=requested_day_count)
    ctx["auth"] = approve_auth(ctx["auth"]["id"], certified_day_start,
                               certified_day_count)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: denial / peer-to-peer / appeal lifecycle
# ---------------------------------------------------------------------------

def setup_denied_auth(clock: str = DENIAL_DECIDED_AT,
                      denial_reason_code: str = "CRITERIA_NOT_MET",
                      requested_day_count: int = 3,
                      with_advisor: bool = True,
                      patient_mrn: str = "MRN-DEN", **case_kwargs) -> dict:
    """Case whose authorization request was DENIED at `clock`, with the
    linked DenialCase born OPEN.

    Returns {"payer", "attending", "advisor", "case", "auth", "denial"}.
    """
    if clock is not None:
        set_clock(clock)
    ctx = setup_case(with_advisor=with_advisor, patient_mrn=patient_mrn,
                     **case_kwargs)
    ctx["auth"] = make_auth(ctx["case"]["id"],
                            requested_day_count=requested_day_count)
    ctx["auth"] = deny_auth(ctx["auth"]["id"], denial_reason_code)
    ctx["denial"] = denial_of_case(ctx["case"]["id"])
    return ctx


def setup_p2p_scheduled(clock: str = DENIAL_DECIDED_AT,
                        scheduled_start_at: str = "2026-08-03T10:00:00Z",
                        scheduled_end_at: str = "2026-08-03T10:30:00Z",
                        denial_reason_code: str = "CRITERIA_NOT_MET",
                        patient_mrn: str = "MRN-P2P") -> dict:
    """Denied authorization with a SCHEDULED peer-to-peer conference."""
    ctx = setup_denied_auth(clock=clock, denial_reason_code=denial_reason_code,
                            patient_mrn=patient_mrn)
    ctx["conference"] = make_conference(
        ctx["auth"]["id"], ctx["advisor"]["id"], ctx["attending"]["id"],
        scheduled_start_at, scheduled_end_at)
    return ctx


def setup_appeal_filed(clock: str = DENIAL_DECIDED_AT,
                       denial_reason_code: str = "LEVEL_OF_CARE",
                       appeal_level: int = 1,
                       patient_mrn: str = "MRN-APL") -> dict:
    """Final denial (no conference) with one FILED appeal."""
    ctx = setup_denied_auth(clock=clock, denial_reason_code=denial_reason_code,
                            patient_mrn=patient_mrn)
    ctx["appeal"] = file_appeal(ctx["denial"]["id"], appeal_level)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: CC44 and escalation assembly
# ---------------------------------------------------------------------------

def setup_cc44_open(plan_class: str = "MEDICARE", with_advisor: bool = True,
                    patient_mrn: str = "MRN-CC44", **cc44_overrides) -> dict:
    """Medicare-family case whose latest submitted review is CRITERIA_NOT_MET,
    with one CC44 request sitting CONCURRENCE_PENDING (PRD §3.6)."""
    ctx = setup_case_with_submitted_review(
        plan_class=plan_class, with_advisor=with_advisor, patient_mrn=patient_mrn)
    ctx["cc44"] = make_cc44(ctx["case"]["id"], **cc44_overrides)
    return ctx


def setup_cc44_committee_pending(patient_mrn: str = "MRN-CC44C") -> dict:
    """CC44 request advanced to COMMITTEE_PENDING via attending CONCUR."""
    ctx = setup_cc44_open(patient_mrn=patient_mrn)
    ctx["cc44"] = concur_cc44(ctx["cc44"]["id"], ctx["attending"]["id"], "CONCUR")
    return ctx


def setup_avoidable_days(num_days: int, plan_class: str = "COMMERCIAL",
                         patient_mrn: str = "MRN-DAYS") -> dict:
    """Case with num_days OPEN avoidable-day records on distinct calendar
    days (2026-08-02 onward), cycling through barrier codes. The logical
    clock is staggered between creates so creation timestamps are strictly
    increasing under any clock implementation."""
    ctx = setup_case(plan_class=plan_class, patient_mrn=patient_mrn)
    codes = ["PLACEMENT_DELAY", "PAYER_AUTH_DELAY", "TRANSPORT_DELAY",
             "FAMILY_DECISION", "PHYSICIAN_DELAY"]
    days = []
    for i in range(num_days):
        stagger_clock(i)
        days.append(add_avoidable_day(
            ctx["case"]["id"], f"2026-08-{2 + i:02d}", codes[i % len(codes)],
            barrier_weight=2 + (i % 3)))
    ctx["days"] = days
    return ctx
