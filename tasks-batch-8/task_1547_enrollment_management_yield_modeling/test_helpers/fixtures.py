"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Applicant calls are entity-backed (X-User-ID is the
Applicant record's id) and ApplicationReader submission is pinned to the
review's reader_id. Ownership-gated and reader-pinned calls always use the
make_* builders with the real ids, never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    APP_DEADLINE,
    CLOCK_START,
    DEPOSIT_TIME,
    REVIEW_WINDOW_END,
    REVIEW_WINDOW_START,
)
from .factories import (
    create_applicant_payload,
    create_application_payload,
    create_cycle_payload,
    create_deposit_payload,
    create_intervention_payload,
    create_program_payload,
    create_review_payload,
    submit_review_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_reader_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
MANAGER = TEST_USERS["enrollment_manager_headers"]
OFFICER = TEST_USERS["admissions_officer_headers"]
AID_OFFICER = TEST_USERS["financial_aid_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> None:
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: cycle + program setup
# ---------------------------------------------------------------------------

def create_cycle(**overrides) -> dict:
    """Create an admission cycle (born SETUP). Returns the cycle."""
    return get_success_data(api_client.create_cycle(
        create_cycle_payload(**overrides), MANAGER))


def create_program(cycle_id, **overrides) -> dict:
    """Create a program inside a cycle. Returns the program."""
    return get_success_data(api_client.create_program(
        create_program_payload(cycle_id, **overrides), MANAGER))


def advance_cycle(cycle_id, to_status) -> dict:
    """Advance a cycle one step. Returns the updated cycle."""
    return get_success_data(api_client.advance_cycle(cycle_id, to_status,
                                                     MANAGER))


def setup_open_cycle_with_program(**program_overrides) -> dict:
    """Clock pinned to the canonical start; cycle created and advanced to
    OPEN; one program created. Returns {"cycle": ..., "program": ...}."""
    set_clock(CLOCK_START)
    cycle = create_cycle()
    program = create_program(cycle["id"], **program_overrides)
    advance_cycle(cycle["id"], "OPEN")
    return {"cycle": cycle, "program": program}


def advance_cycle_to_decisions_released(cycle_id) -> None:
    """Clock to the application deadline, then OPEN -> REVIEW_CLOSED ->
    DECISIONS_RELEASED."""
    set_clock(APP_DEADLINE)
    advance_cycle(cycle_id, "REVIEW_CLOSED")
    advance_cycle(cycle_id, "DECISIONS_RELEASED")


# ---------------------------------------------------------------------------
# Tier 2: applicants and applications
# ---------------------------------------------------------------------------

def create_applicant(cycle_id, **overrides) -> dict:
    """Capture an inquiry. Returns the applicant (INQUIRY)."""
    return get_success_data(api_client.create_applicant(
        create_applicant_payload(cycle_id, **overrides), OFFICER))


def submit_application(cycle_id, program_id, applicant_id, **overrides) -> dict:
    """File an application. Returns the application (SUBMITTED)."""
    return get_success_data(api_client.create_application(
        create_application_payload(applicant_id, program_id, cycle_id,
                                   **overrides), OFFICER))


def create_application_for_new_applicant(cycle_id, program_id, **overrides
                                         ) -> dict:
    """Applicant + application in one call. Applicant fields can be overridden
    via applicant_overrides. Returns {"applicant": ..., "application": ...}."""
    applicant_overrides = overrides.pop("applicant_overrides", {})
    applicant = create_applicant(cycle_id, **applicant_overrides)
    application = submit_application(cycle_id, program_id, applicant["id"],
                                     **overrides)
    return {"applicant": applicant, "application": application}


# ---------------------------------------------------------------------------
# Tier 3: committee review workflow
# ---------------------------------------------------------------------------

def assign_review(application_id, reader_id,
                  window_start_at=REVIEW_WINDOW_START,
                  window_end_at=REVIEW_WINDOW_END) -> dict:
    """Assign a committee read. Returns the review (ASSIGNED)."""
    return get_success_data(api_client.create_review(
        create_review_payload(application_id, reader_id,
                              window_start_at=window_start_at,
                              window_end_at=window_end_at), OFFICER))


def submit_review(review_id, reader_id, score=80, recommendation="ADMIT"
                  ) -> dict:
    """Submit a read as its pinned reader. Returns the review (SUBMITTED)."""
    return get_success_data(api_client.submit_review(
        review_id,
        submit_review_payload(score_academic=score, score_fit=score,
                              recommendation=recommendation),
        make_reader_headers(reader_id)))


def assign_and_submit_review(application_id, reader_id, score=80,
                             recommendation="ADMIT",
                             window_start_at=REVIEW_WINDOW_START,
                             window_end_at=REVIEW_WINDOW_END) -> dict:
    """Assign then immediately submit a read. Returns the SUBMITTED review."""
    review = assign_review(application_id, reader_id,
                           window_start_at=window_start_at,
                           window_end_at=window_end_at)
    return submit_review(review["id"], reader_id, score=score,
                         recommendation=recommendation)


def transition_application(application_id, to_status, headers=None) -> dict:
    return get_success_data(api_client.transition_application(
        application_id, to_status, headers or OFFICER))


def drive_application_to_admitted(application_id, score=80) -> dict:
    """SUBMITTED -> IN_REVIEW -> COMMITTEE_REVIEW (auto) -> two submitted
    reads -> DECISION_PENDING -> ADMITTED. Returns the ADMITTED application
    (its version is the current OCC token)."""
    transition_application(application_id, "IN_REVIEW")
    assign_and_submit_review(application_id, "reader-1", score=score)
    assign_and_submit_review(application_id, "reader-2", score=score)
    transition_application(application_id, "DECISION_PENDING")
    return transition_application(application_id, "ADMITTED")


def create_admitted_application(cycle_id, program_id,
                                academic_score=80, efc_cents=5_000_000,
                                distance_band="LOCAL",
                                inquiry_source="WEB_FORM") -> dict:
    """Applicant + application driven all the way to ADMITTED.
    Returns {"applicant": ..., "application": ...}."""
    pair = create_application_for_new_applicant(
        cycle_id, program_id,
        academic_score=academic_score, efc_cents=efc_cents,
        applicant_overrides={"distance_band": distance_band,
                             "inquiry_source": inquiry_source})
    pair["application"] = drive_application_to_admitted(
        pair["application"]["id"], score=int(academic_score))
    return pair


def create_waitlisted_application(cycle_id, program_id, academic_score=80,
                                  recommendations=("ADMIT", "ADMIT")) -> dict:
    """Applicant + application driven to WAITLISTED; the waitlist decision
    births exactly one ACTIVE waitlist entry.
    Returns {"applicant": ..., "application": ..., "entry": ...}."""
    pair = create_application_for_new_applicant(
        cycle_id, program_id, academic_score=academic_score)
    app_id = pair["application"]["id"]
    transition_application(app_id, "IN_REVIEW")
    for idx, recommendation in enumerate(recommendations, start=1):
        assign_and_submit_review(app_id, f"reader-{idx}",
                                 score=int(academic_score),
                                 recommendation=recommendation)
    transition_application(app_id, "DECISION_PENDING")
    pair["application"] = transition_application(app_id, "WAITLISTED")
    pair["entry"] = get_waitlist_entry_for_application(app_id)
    return pair


def get_waitlist_entry_for_application(application_id) -> dict:
    """Fetch the single waitlist entry of an application via the filterable
    listing."""
    entries, meta = validate_paginated(api_client.list_waitlist_entries(
        MANAGER, params={"application_id": application_id}))
    assert meta["total_count"] == 1, (
        f"Expected exactly one waitlist entry for {application_id}, "
        f"got {meta['total_count']}")
    return entries[0]


# ---------------------------------------------------------------------------
# Tier 4: aid offers
# ---------------------------------------------------------------------------

def create_aid_offer(application, fund_type="MERIT") -> dict:
    """Create a computed aid offer against the application's current version
    (the dict must carry an up-to-date `version`). Returns the OFFERED offer."""
    return get_success_data(api_client.create_aid_offer(
        {"application_id": application["id"], "fund_type": fund_type,
         "expected_application_version": application["version"]},
        AID_OFFICER))


def refresh_application(application_id) -> dict:
    return get_success_data(api_client.get_application(application_id, OFFICER))


def refresh_program(program_id) -> dict:
    return get_success_data(api_client.get_program(program_id, MANAGER))


def accept_aid_offer(offer_id, applicant_id) -> dict:
    """Applicant-owner accepts an OFFERED offer."""
    return get_success_data(api_client.transition_aid_offer(
        offer_id, "ACCEPTED", make_applicant_headers(applicant_id)))


# ---------------------------------------------------------------------------
# Tier 5: deposits and enrollment
# ---------------------------------------------------------------------------

def pay_deposit(application, applicant, amount_cents=50_000) -> dict:
    """Pay a deposit as the owning applicant. Returns the PAID deposit;
    the application automatically moves ADMITTED -> DEPOSITED."""
    return get_success_data(api_client.create_deposit(
        create_deposit_payload(application["id"], amount_cents),
        make_applicant_headers(applicant["id"])))


def create_deposited_application(cycle_id, program_id, deposit_amount=50_000,
                                 deposit_time=DEPOSIT_TIME, **app_kwargs
                                 ) -> dict:
    """Full chain: applicant -> ADMITTED -> cycle advanced to
    DECISIONS_RELEASED -> clock moved to deposit_time -> deposit paid.
    Returns {"applicant": ..., "application": ..., "deposit": ...}."""
    pair = create_admitted_application(cycle_id, program_id, **app_kwargs)
    advance_cycle_to_decisions_released(cycle_id)
    set_clock(deposit_time)
    deposit = pay_deposit(pair["application"], pair["applicant"],
                          amount_cents=deposit_amount)
    pair["deposit"] = deposit
    pair["application"] = refresh_application(pair["application"]["id"])
    return pair


def schedule_intervention(application_id, advisor_id="advisor-1",
                          intervention_type="OUTREACH_CALL",
                          window_start_at="2027-04-10T09:00:00Z",
                          window_end_at="2027-04-10T09:30:00Z") -> dict:
    """Manually schedule a melt intervention. Returns the SCHEDULED row."""
    return get_success_data(api_client.create_intervention(
        create_intervention_payload(application_id, advisor_id,
                                    intervention_type, window_start_at,
                                    window_end_at), MANAGER))


def list_interventions_for(application_id) -> list:
    rows, _meta = validate_paginated(api_client.list_interventions(
        MANAGER, params={"application_id": application_id}))
    return rows
