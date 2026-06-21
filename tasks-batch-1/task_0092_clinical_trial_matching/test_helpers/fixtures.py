"""Composite setup helpers for multi-step test prerequisites (PRD §3).

The harness restarts the API process before every individual test, so the
database is empty at the start of every test — each fixture rebuilds its
preconditions from scratch using only PRD-declared endpoints.

Uses ``get_success_data()`` (lenient validator) internally so setup failures
surface as clear "Setup failed" errors rather than confusing assertion
failures inside the test body.

Identity threading (PRD §2.1, §3.2, §3.5): all roles are opaque, but the
recorded operator ids are segregation-of-duties anchors. The fixtures stamp a
distinct operator id per role — Sponsor=sponsor-1, IRBReviewer=irb-1,
Investigator=inv-1, SafetyOfficer=so-1 — so the default flows never trip a
segregation check (reviewer != sponsor; adjudicator != reporter).

The canonical preamble used across the difficulty/corner indices is the
"OPEN trial + ELIGIBLE screening" sequence: create a Sponsor trial with arms +
a DRAFT consent; APPROVE the protocol IRB review; APPROVE the consent IRB
review; activate the consent (posture -> OPEN); register a participant; screen
(ELIGIBLE); create an enrollment (SCREENED). OCC versions are always captured
fresh from GET /trials/{id} immediately before each guarded call.
"""
from typing import Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    set_clock_payload,
    create_trial_payload,
    create_criterion_payload,
    create_arm_payload,
    create_consent_document_payload,
    activate_consent_payload,
    create_irb_review_payload,
    decide_irb_review_payload,
    create_participant_payload,
    screen_participant_payload,
    create_enrollment_payload,
    transition_payload,
    create_visit_payload,
    complete_visit_payload,
    create_adverse_event_payload,
    review_adverse_event_payload,
)
from .test_users import (
    TEST_USERS,
    make_sponsor_headers,
    make_irb_reviewer_headers,
    make_investigator_headers,
    make_safety_officer_headers,
    SPONSOR_USER_ID,
    IRB_REVIEWER_USER_ID,
    INVESTIGATOR_USER_ID,
    SAFETY_OFFICER_USER_ID,
)


# ─── Clock primitive (PRD §3.8) ─────────────────────────


def set_clock(to_iso8601: str) -> None:
    get_success_data(api_client.set_clock(
        set_clock_payload(to_iso8601), TEST_USERS["sponsor_headers"],
    ))


# ─── Primitive entity builders ──────────────────────────


def create_trial(sponsor_user_id: str = SPONSOR_USER_ID, **overrides) -> dict:
    return get_success_data(api_client.create_trial(
        create_trial_payload(**overrides), make_sponsor_headers(sponsor_user_id),
    ))


def add_criterion(trial_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_criterion(
        trial_id, create_criterion_payload(**overrides), TEST_USERS["sponsor_headers"],
    ))


def add_arm(trial_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_arm(
        trial_id, create_arm_payload(**overrides), TEST_USERS["sponsor_headers"],
    ))


def create_consent_document(trial_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_consent_document(
        trial_id, create_consent_document_payload(**overrides), TEST_USERS["sponsor_headers"],
    ))


def open_irb_review(trial_id: str, scope: str = "PROTOCOL", **overrides) -> dict:
    return get_success_data(api_client.create_irb_review(
        trial_id, create_irb_review_payload(scope=scope, **overrides), TEST_USERS["sponsor_headers"],
    ))


def decide_irb_review(trial_id: str, review_id: str, action: str,
                      reviewer_user_id: str = IRB_REVIEWER_USER_ID) -> dict:
    return get_success_data(api_client.decide_irb_review(
        trial_id, review_id, decide_irb_review_payload(action),
        make_irb_reviewer_headers(reviewer_user_id),
    ))


def create_participant(**overrides) -> dict:
    return get_success_data(api_client.create_participant(
        create_participant_payload(**overrides), TEST_USERS["coordinator_headers"],
    ))


def screen_participant(trial_id: str, participant_id: str) -> dict:
    return get_success_data(api_client.screen_participant(
        trial_id, screen_participant_payload(participant_id), TEST_USERS["coordinator_headers"],
    ))


def create_enrollment(screening_id: str) -> dict:
    return get_success_data(api_client.create_enrollment(
        create_enrollment_payload(screening_id), TEST_USERS["coordinator_headers"],
    ))


def get_trial_version(trial_id: str) -> int:
    return get_success_data(api_client.get_trial(
        trial_id, TEST_USERS["sponsor_headers"],
    ))["version"]


# ─── IRB approval helpers ───────────────────────────────


def approve_protocol(trial_id: str, reviewer_user_id: str = IRB_REVIEWER_USER_ID) -> dict:
    """Open a PROTOCOL review and APPROVE it (Trial.irb_status -> APPROVED)."""
    review = open_irb_review(trial_id, scope="PROTOCOL")
    decide_irb_review(trial_id, review["id"], "APPROVE", reviewer_user_id=reviewer_user_id)
    return review


def approve_consent(trial_id: str, doc_id: str,
                    reviewer_user_id: str = IRB_REVIEWER_USER_ID) -> dict:
    """Open a CONSENT-scope review for doc_id and APPROVE it (doc DRAFT ->
    IRB_APPROVED)."""
    review = open_irb_review(trial_id, scope="CONSENT", consent_document_id=doc_id)
    decide_irb_review(trial_id, review["id"], "APPROVE", reviewer_user_id=reviewer_user_id)
    return review


def activate_consent(trial_id: str, doc_id: str) -> dict:
    """Activate an IRB_APPROVED consent, capturing the live trial version
    immediately before the OCC-guarded call (PRD §2.6)."""
    tv = get_trial_version(trial_id)
    return get_success_data(api_client.activate_consent_document(
        trial_id, doc_id, activate_consent_payload(tv), TEST_USERS["sponsor_headers"],
    ))


# ─── Composite: an OPEN trial ready for enrollment ──────


def setup_open_trial(
    num_arms: int = 2,
    target_enrollment: int = 5,
    randomization_method: str = "SIMPLE",
    criteria: Optional[List[dict]] = None,
    body_hash: str = "h1",
) -> dict:
    """Build a trial all the way to ``posture == OPEN``: arms added in SETUP,
    optional criteria, a DRAFT consent, an APPROVED protocol review, an
    APPROVED consent review, then consent activation (PRD §3.1, §3.2).

    Returns a dict with keys: trial_id, arm_ids, doc_id, trial.
    """
    trial = create_trial(target_enrollment=target_enrollment,
                         randomization_method=randomization_method)
    trial_id = trial["id"]

    for c in (criteria or []):
        add_criterion(trial_id, **c)

    arm_ids = []
    arm_names = ["TREATMENT", "PLACEBO", "ARM_C", "ARM_D"]
    for i in range(num_arms):
        arm = add_arm(trial_id, name=arm_names[i] if i < len(arm_names) else f"ARM_{i}")
        arm_ids.append(arm["id"])

    doc = create_consent_document(trial_id, body_hash=body_hash)
    approve_protocol(trial_id)
    approve_consent(trial_id, doc["id"])
    activate_consent(trial_id, doc["id"])

    return {
        "trial_id": trial_id,
        "arm_ids": arm_ids,
        "doc_id": doc["id"],
        "trial": trial,
    }


def create_eligible_screened_enrollment(trial_id: str, participant_overrides: Optional[dict] = None) -> dict:
    """Register an eligible participant, screen ELIGIBLE, and create a
    SCREENED enrollment. Returns dict: participant_id, screening_id,
    enrollment_id, enrollment."""
    participant = create_participant(**(participant_overrides or {}))
    screening = screen_participant(trial_id, participant["id"])
    enrollment = create_enrollment(screening["id"])
    return {
        "participant_id": participant["id"],
        "screening_id": screening["id"],
        "enrollment_id": enrollment["id"],
        "enrollment": enrollment,
    }


def consent_enrollment(enrollment_id: str, doc_id: str) -> dict:
    """SCREENED -> CONSENTED (PRD §3.4)."""
    return get_success_data(api_client.transition_enrollment(
        enrollment_id, transition_payload("CONSENT", consent_document_id=doc_id),
        TEST_USERS["coordinator_headers"],
    ))


def randomize_enrollment(trial_id: str, enrollment_id: str) -> dict:
    """CONSENTED -> RANDOMIZED, capturing the fresh trial version for the
    OCC check (PRD §2.6, §3.4)."""
    tv = get_trial_version(trial_id)
    return get_success_data(api_client.transition_enrollment(
        enrollment_id, transition_payload("RANDOMIZE", expected_trial_version=tv),
        TEST_USERS["coordinator_headers"],
    ))


def activate_enrollment(enrollment_id: str) -> dict:
    """RANDOMIZED -> ACTIVE (PRD §3.4)."""
    return get_success_data(api_client.transition_enrollment(
        enrollment_id, transition_payload("ACTIVATE"), TEST_USERS["coordinator_headers"],
    ))


def withdraw_enrollment(enrollment_id: str) -> dict:
    """-> WITHDRAWN (PRD §3.4)."""
    return get_success_data(api_client.transition_enrollment(
        enrollment_id, transition_payload("WITHDRAW"), TEST_USERS["coordinator_headers"],
    ))


# ─── Composite: enrollment at a chosen lifecycle stage ──


def setup_consented_enrollment(open_trial: Optional[dict] = None,
                               participant_overrides: Optional[dict] = None) -> dict:
    """An OPEN trial + one CONSENTED enrollment. Returns the merged dict from
    setup_open_trial and create_eligible_screened_enrollment."""
    ot = open_trial or setup_open_trial()
    enr = create_eligible_screened_enrollment(ot["trial_id"], participant_overrides)
    consent_enrollment(enr["enrollment_id"], ot["doc_id"])
    return {**ot, **enr}


def setup_randomized_enrollment(open_trial: Optional[dict] = None,
                                participant_overrides: Optional[dict] = None) -> dict:
    """An OPEN trial + one RANDOMIZED enrollment (safety_status CLEAR)."""
    ctx = setup_consented_enrollment(open_trial, participant_overrides)
    randomize_enrollment(ctx["trial_id"], ctx["enrollment_id"])
    return ctx


def setup_active_enrollment(open_trial: Optional[dict] = None,
                            participant_overrides: Optional[dict] = None) -> dict:
    """An OPEN trial + one ACTIVE enrollment ready to receive visits."""
    ctx = setup_randomized_enrollment(open_trial, participant_overrides)
    activate_enrollment(ctx["enrollment_id"])
    return ctx


# ─── Visits (PRD §3.6) ──────────────────────────────────


def schedule_visit(enrollment_id: str, sequence_index: int, scheduled_at: str,
                   draw_window_minutes: int) -> dict:
    return get_success_data(api_client.create_visit(
        enrollment_id,
        create_visit_payload(sequence_index, scheduled_at, draw_window_minutes),
        TEST_USERS["coordinator_headers"],
    ))


def complete_visit(visit_id: str, drawn_at: str) -> dict:
    return get_success_data(api_client.complete_visit(
        visit_id, complete_visit_payload(drawn_at), TEST_USERS["coordinator_headers"],
    ))


def setup_active_enrollment_with_completed_visits(
    visits: List[dict],
    open_trial: Optional[dict] = None,
    participant_overrides: Optional[dict] = None,
) -> dict:
    """An ACTIVE enrollment with a set of COMPLETED visits.

    ``visits`` is a list of dicts each with keys: sequence_index, scheduled_at,
    draw_window_minutes, drawn_at. Each visit is scheduled then completed
    in-window. Returns the lifecycle ctx plus ``visit_ids`` (in input order).
    """
    ctx = setup_active_enrollment(open_trial, participant_overrides)
    visit_ids = []
    for v in visits:
        visit = schedule_visit(
            ctx["enrollment_id"], v["sequence_index"], v["scheduled_at"], v["draw_window_minutes"],
        )
        complete_visit(visit["id"], v["drawn_at"])
        visit_ids.append(visit["id"])
    ctx["visit_ids"] = visit_ids
    return ctx


# ─── Adverse events (PRD §3.5) ──────────────────────────


def report_adverse_event(enrollment_id: str, severity: str = "MODERATE",
                         occurred_at: str = "2026-06-01T09:00:00Z",
                         is_serious: Optional[bool] = None,
                         reporter_user_id: str = INVESTIGATOR_USER_ID) -> dict:
    extra = {} if is_serious is None else {"is_serious": is_serious}
    return get_success_data(api_client.create_adverse_event(
        enrollment_id, create_adverse_event_payload(severity, occurred_at, **extra),
        make_investigator_headers(reporter_user_id),
    ))


def triage_adverse_event(ae_id: str, officer_user_id: str = SAFETY_OFFICER_USER_ID) -> dict:
    return get_success_data(api_client.review_adverse_event(
        ae_id, review_adverse_event_payload("TRIAGE"),
        make_safety_officer_headers(officer_user_id),
    ))


def adjudicate_adverse_event(ae_id: str, relation: str,
                             officer_user_id: str = SAFETY_OFFICER_USER_ID) -> dict:
    return get_success_data(api_client.review_adverse_event(
        ae_id, review_adverse_event_payload("ADJUDICATE", relation=relation),
        make_safety_officer_headers(officer_user_id),
    ))


def setup_enrollment_on_hold(open_trial: Optional[dict] = None,
                             participant_overrides: Optional[dict] = None,
                             severity: str = "SEVERE") -> dict:
    """A RANDOMIZED enrollment driven to safety_status == HOLD via a SEVERE
    adverse event triaged then adjudicated RELATED (PRD §3.5). Freezes the
    parent trial. Returns ctx plus ``ae_id``."""
    ctx = setup_randomized_enrollment(open_trial, participant_overrides)
    ae = report_adverse_event(ctx["enrollment_id"], severity=severity, is_serious=True)
    triage_adverse_event(ae["id"])
    adjudicate_adverse_event(ae["id"], "RELATED")
    ctx["ae_id"] = ae["id"]
    return ctx


# ─── Payments (PRD §3.7) ────────────────────────────────


def sweep_payment(enrollment_id: str) -> dict:
    return get_success_data(api_client.create_payment(
        enrollment_id, TEST_USERS["sponsor_headers"],
    ))


def pay_payment(payment_id: str) -> dict:
    return get_success_data(api_client.pay_payment(
        payment_id, TEST_USERS["sponsor_headers"],
    ))
