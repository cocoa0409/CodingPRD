"""Composite setup helpers for the USCIS case-management benchmark.

Every fixture builds its preconditions from scratch through PRD-declared endpoints
(see PRD §3.x). The runner restarts the API server before every individual pytest
test, so each test starts from an empty database — no entities, no clock state.

Fixtures use `get_success_data()` (lenient validator) so a setup failure surfaces
as a clear "Setup failed" trace rather than a cryptic assertion deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_applicant_payload,
    create_attorney_payload,
    create_case_payload,
    create_biometrics_payload,
    issue_rfe_payload,
    rfe_respond_payload,
    schedule_interview_payload,
    complete_interview_payload,
    decide_case_payload,
    visa_bulletin_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_attorney_headers,
    make_officer_headers,
)


_ADMIN_HEADERS = TEST_USERS["field_office_admin_headers"]
_ANON_HEADERS: dict = {}


# ─── Tier 0: clock & visa bulletin ──────────────────────────────


def set_clock(iso8601: str) -> None:
    """Mutate ClockState.current_utc to the given ISO 8601 string (PRD §2.5)."""
    res = api_client.set_clock(set_clock_payload(iso8601), _ADMIN_HEADERS)
    get_success_data(res)


def publish_visa_bulletin(bulletin_month: str, preference_category: str, country: str,
                          chart_type: str, cutoff_date: str) -> dict:
    """Publish a VisaBulletinEntry as the FieldOfficeAdmin (PRD §3.4)."""
    res = api_client.publish_visa_bulletin(
        visa_bulletin_payload(bulletin_month, preference_category, country,
                              chart_type, cutoff_date),
        _ADMIN_HEADERS,
    )
    return get_success_data(res)


# ─── Tier 1: registration helpers ───────────────────────────────


def register_applicant(**overrides) -> dict:
    """Self-register a new applicant (PRD §3.1). No auth required."""
    res = api_client.register_applicant(create_applicant_payload(**overrides),
                                        _ANON_HEADERS)
    return get_success_data(res)


def register_attorney(**overrides) -> dict:
    """Self-register a new attorney (PRD §3.1)."""
    res = api_client.register_attorney(create_attorney_payload(**overrides),
                                       _ANON_HEADERS)
    return get_success_data(res)


# ─── Tier 2: case creation in DRAFT ─────────────────────────────


def create_draft_case(applicant: dict, case_type: str = "I-130",
                      preference_category=None, attorney_id=None) -> dict:
    """Create a DRAFT case owned by `applicant` (PRD §3.1).

    The Applicant role is entity-backed, so we use make_applicant_headers(applicant.id)
    for the ownership-gated POST /uscis/cases.
    """
    headers = make_applicant_headers(applicant["id"])
    res = api_client.create_case(
        create_case_payload(applicant["id"], case_type=case_type,
                            preference_category=preference_category,
                            attorney_id=attorney_id),
        headers,
    )
    return get_success_data(res)


# ─── Tier 3: walking the case state machine ─────────────────────


def file_case(case: dict, applicant: dict) -> dict:
    """Transition DRAFT → FILED (PRD §3.2). Returns the post-file Case."""
    headers = make_applicant_headers(applicant["id"])
    res = api_client.file_case(case["id"], headers)
    return get_success_data(res)


def setup_filed_case(case_type: str = "I-130", preference_category=None,
                     file_date_iso: str = "2026-06-15T00:00:00Z",
                     date_of_birth: str = "1990-01-01",
                     country: str = "WORLDWIDE") -> tuple:
    """Register an applicant + create a case + file it. Returns (applicant, case_filed).

    Clock is set to `file_date_iso` before filing so file_date stamps deterministically.
    """
    set_clock(file_date_iso)
    applicant = register_applicant(
        date_of_birth=date_of_birth,
        country_of_chargeability=country,
    )
    case = create_draft_case(applicant, case_type=case_type,
                             preference_category=preference_category)
    filed = file_case(case, applicant)
    return applicant, filed


def setup_under_review_i130(file_date_iso: str = "2026-06-15T00:00:00Z") -> tuple:
    """I-130 case advanced straight from FILED → UNDER_REVIEW (no biometrics path).

    Returns (applicant, case_under_review, officer_headers).
    """
    applicant, filed = setup_filed_case(case_type="I-130", preference_category="IR",
                                        file_date_iso=file_date_iso)
    officer_id = filed["assigned_officer_id"]
    officer_headers = make_officer_headers(officer_id)
    res = api_client.advance_review(filed["id"], officer_headers)
    case_ur = get_success_data(res)
    return applicant, case_ur, officer_headers


def schedule_biometrics_for(case_id: str, officer_headers: dict,
                            scheduled_at: str = "2026-06-25T15:00:00Z",
                            asc_location_code: str = "ASC-SF-01") -> dict:
    """POST /uscis/cases/{id}/biometrics as Officer (PRD §3.3)."""
    res = api_client.schedule_biometrics(
        case_id,
        create_biometrics_payload(scheduled_at, asc_location_code),
        officer_headers,
    )
    return get_success_data(res)


def setup_biometrics_scheduled_i485(file_date_iso: str = "2026-06-15T00:00:00Z",
                                    biom_at: str = "2026-06-25T15:00:00Z",
                                    asc_location_code: str = "ASC-SF-01",
                                    date_of_birth: str = "1990-01-01",
                                    country: str = "WORLDWIDE",
                                    preference_category=None) -> tuple:
    """I-485 case filed and immediately scheduled for biometrics.

    Returns (applicant, case, biom_appt, officer_headers).
    """
    applicant, filed = setup_filed_case(case_type="I-485",
                                        preference_category=preference_category,
                                        file_date_iso=file_date_iso,
                                        date_of_birth=date_of_birth,
                                        country=country)
    officer_id = filed["assigned_officer_id"]
    officer_headers = make_officer_headers(officer_id)
    biom = schedule_biometrics_for(filed["id"], officer_headers,
                                   scheduled_at=biom_at,
                                   asc_location_code=asc_location_code)
    # Re-read the case to capture the new BIOMETRICS_SCHEDULED status & bumped version.
    case_after = get_success_data(api_client.get_case(filed["id"], officer_headers))
    return applicant, case_after, biom, officer_headers


def setup_under_review_i485(file_date_iso: str = "2026-06-15T00:00:00Z",
                            biom_at: str = "2026-06-25T15:00:00Z",
                            after_biom_at: str = "2026-06-26T00:00:00Z",
                            asc_location_code: str = "ASC-SF-01",
                            preference_category=None,
                            country: str = "WORLDWIDE",
                            date_of_birth: str = "1990-01-01") -> tuple:
    """I-485 case walked through biometrics to UNDER_REVIEW.

    Returns (applicant, case_under_review, biom_appt, officer_headers).
    """
    applicant, case, biom, officer_headers = setup_biometrics_scheduled_i485(
        file_date_iso=file_date_iso,
        biom_at=biom_at,
        asc_location_code=asc_location_code,
        date_of_birth=date_of_birth,
        country=country,
        preference_category=preference_category,
    )
    # Advance the clock past the biometrics appointment, complete it, advance to review.
    set_clock(after_biom_at)
    get_success_data(api_client.complete_biometrics(biom["id"], officer_headers))
    get_success_data(api_client.advance_review(case["id"], officer_headers))
    case_ur = get_success_data(api_client.get_case(case["id"], officer_headers))
    return applicant, case_ur, biom, officer_headers


# ─── Tier 4: RFE lifecycle ──────────────────────────────────────


def issue_rfe_on(case_id: str, officer_headers: dict,
                 evidence_items=None) -> dict:
    """POST /uscis/cases/{id}/rfes (PRD §3.5). Returns the new RFE."""
    res = api_client.issue_rfe(
        case_id, issue_rfe_payload(evidence_items_requested=evidence_items),
        officer_headers,
    )
    return get_success_data(res)


def setup_rfe_pending_i130(file_date_iso: str = "2026-06-15T00:00:00Z",
                           evidence_items=None) -> tuple:
    """I-130 case sitting in RFE_PENDING with one ISSUED RFE.

    Returns (applicant, case, rfe, officer_headers).
    """
    applicant, case_ur, officer_headers = setup_under_review_i130(file_date_iso)
    rfe = issue_rfe_on(case_ur["id"], officer_headers,
                       evidence_items=evidence_items or ["doc_a"])
    case_rfe = get_success_data(api_client.get_case(case_ur["id"], officer_headers))
    return applicant, case_rfe, rfe, officer_headers


def respond_to_rfe(rfe_id: str, applicant: dict, expected_case_version: int,
                   response_summary: str = "Submitted documents.") -> dict:
    """POST /uscis/rfes/{id}/respond as the case's applicant (PRD §3.6)."""
    headers = make_applicant_headers(applicant["id"])
    res = api_client.respond_to_rfe(
        rfe_id,
        rfe_respond_payload(expected_case_version, response_summary),
        headers,
    )
    return get_success_data(res)


# ─── Tier 5: interview lifecycle ────────────────────────────────


def setup_interview_completed_i485(file_date_iso: str = "2026-06-15T00:00:00Z",
                                   biom_at: str = "2026-06-25T15:00:00Z",
                                   after_biom_at: str = "2026-06-26T00:00:00Z",
                                   interview_at: str = "2026-07-10T16:00:00Z",
                                   after_interview_at: str = "2026-07-11T00:00:00Z",
                                   preference_category: str = "F2A",
                                   country: str = "WORLDWIDE",
                                   field_office_code: str = "FO-SFR",
                                   bulletin_month: str = "2026-06",
                                   final_action_cutoff: str = "CURRENT",
                                   interview_decision: str = "NEEDS_REVIEW") -> tuple:
    """Full I-485 walk: filed → biometrics → completed → under review →
    interview scheduled → interview completed (with `interview_decision`).

    Publishes the matching FINAL_ACTION visa bulletin entry so the
    INTERVIEW_SCHEDULED gate (PRD §3.5) passes.

    Returns (applicant, case, interview, officer_headers).
    """
    # Set the clock first; bulletin row needs publishing before we file.
    set_clock(file_date_iso)
    # Publish the FINAL_ACTION cutoff so the visa-availability gate is CURRENT.
    publish_visa_bulletin(bulletin_month, preference_category, country,
                          "FINAL_ACTION", final_action_cutoff)
    applicant = register_applicant(country_of_chargeability=country)
    case = create_draft_case(applicant, case_type="I-485",
                             preference_category=preference_category)
    filed = file_case(case, applicant)
    officer_id = filed["assigned_officer_id"]
    officer_headers = make_officer_headers(officer_id)
    biom = schedule_biometrics_for(filed["id"], officer_headers,
                                   scheduled_at=biom_at,
                                   asc_location_code="ASC-SF-01")
    set_clock(after_biom_at)
    get_success_data(api_client.complete_biometrics(biom["id"], officer_headers))
    get_success_data(api_client.advance_review(filed["id"], officer_headers))
    interview = get_success_data(api_client.schedule_interview(
        filed["id"],
        schedule_interview_payload(interview_at, field_office_code),
        officer_headers,
    ))
    set_clock(after_interview_at)
    completed = get_success_data(api_client.complete_interview(
        interview["id"],
        complete_interview_payload(interview_decision),
        officer_headers,
    ))
    case_ic = get_success_data(api_client.get_case(filed["id"], officer_headers))
    return applicant, case_ic, completed, officer_headers


# ─── Tier 6: officer workload setup (two-case pool) ─────────────


def setup_officer_two_case_pool(initial_clock: str = "2026-06-01T00:00:00Z",
                                final_clock: str = "2026-06-15T00:00:00Z",
                                biom_at: str = "2026-07-01T15:00:00Z",
                                asc_location_code: str = "ASC-SF-01") -> tuple:
    """Create two cases assigned to the same officer at the same file_date.

    Case A: I-485 filed → biometrics scheduled (status=BIOMETRICS_SCHEDULED).
    Case B: I-130 filed → advance-review (status=UNDER_REVIEW).

    Both cases age `final_clock - initial_clock` days.

    PRD §3.2 says cases are assigned to officers "in round-robin order" from a
    server-managed pool of opaque officer ids — but PRD does not pin the pool
    SIZE. To deterministically land case_a and case_b on the SAME officer we
    file case_a, then file dummy throw-away cases until the next file would
    yield the same `assigned_officer_id` as case_a — at which point we file
    case_b. Dummy cases get assigned to OTHER officers and are not in
    `officer_id`'s pool, so they don't pollute the workload query.

    The pool-size loop bound is conservative (32) to handle any reasonable
    pool size; it raises if the assignment never repeats (which would itself
    be a PRD violation of "round-robin order").

    Returns (officer_id, officer_headers, case_a, case_b).
    """
    set_clock(initial_clock)
    applicant_a = register_applicant()
    case_a = create_draft_case(applicant_a, case_type="I-485")
    filed_a = file_case(case_a, applicant_a)
    officer_id = filed_a["assigned_officer_id"]
    officer_headers = make_officer_headers(officer_id)
    schedule_biometrics_for(filed_a["id"], officer_headers,
                            scheduled_at=biom_at,
                            asc_location_code=asc_location_code)

    # File dummy throw-away cases until the next file would be assigned to
    # `officer_id` again — meaning the round-robin has cycled back. We need
    # case_b to be the call that lands on `officer_id`, so we file dummies
    # and inspect each: when a dummy lands on `officer_id`, the NEXT file
    # will land on the officer right after `officer_id` in the rotation, not
    # back on `officer_id`. Instead, after seeing a dummy land on
    # `officer_id`, we must continue filing dummies until JUST BEFORE the
    # next cycle. Cleanest: after each dummy file, if the assigned officer
    # equals `officer_id`, that dummy IS effectively another case for this
    # officer — but it's I-131 and might affect the score. To keep the pool
    # clean, mark each dummy that lands on officer_id as DENIED (terminal,
    # excluded from pool) and keep going. Eventually we stop one dummy
    # before the desired cycle position.
    #
    # Simpler equivalent: file dummies, and EVERY time a dummy lands on
    # officer_id, abandon that dummy via no-show after grace by transitioning
    # it manually. But the simplest PRD-faithful approach: file dummy cases
    # (I-131) until the next call WOULD be officer_id. We don't know the
    # pool size, so we file one dummy, check its officer, repeat until we
    # see officer_id assigned to a dummy. At that point we've consumed one
    # full cycle's worth of officers; the NEXT file lands on officer_id +1.
    # That doesn't help either.
    #
    # Cleanest deterministic approach: file dummies and check `assigned_officer_id`.
    # When a dummy gets `officer_id`, we have just placed a SECOND case onto
    # the officer. Repurpose that dummy as case_b: it's the case we want on
    # officer_id. We just need to ensure it's of the right type/status for the
    # test. Make all dummies I-130 with preference_category=IR; when one lands
    # on officer_id, run advance-review on it (FILED→UNDER_REVIEW for I-130).
    # All earlier dummies (assigned to OTHER officers) remain in FILED — they
    # don't appear in officer_id's pool.

    filed_b = None
    for _ in range(32):
        applicant_d = register_applicant()
        case_d = create_draft_case(applicant_d, case_type="I-130",
                                   preference_category="IR")
        filed_d = file_case(case_d, applicant_d)
        if filed_d["assigned_officer_id"] == officer_id:
            filed_b = filed_d
            break
    if filed_b is None:
        raise RuntimeError(
            "round-robin officer assignment did not cycle back within 32 files"
        )

    get_success_data(api_client.advance_review(filed_b["id"], officer_headers))
    set_clock(final_clock)
    return officer_id, officer_headers, filed_a, filed_b
