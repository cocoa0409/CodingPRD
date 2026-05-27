"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Every helper builds its preconditions from scratch using only PRD-declared
endpoints — the test harness restarts the server before every pytest test
so the database is empty at the start of each fixture call.

For Claimant-owned operations (entity_backed role), each helper threads the
Claimant.id of the created claimant into make_claimant_headers(id) — never
falling back to the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_claimant_payload,
    create_work_credit_payload,
    create_application_payload,
    create_evidence_payload,
    medical_decision_payload,
    schedule_hearing_payload,
    hearing_decision_payload,
    create_child_auxiliary_payload,
    complete_cdr_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_claimant_headers


# -------------------------------------------------------------------------
# Tier 0: clock control (PRD §2.10)
# -------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> None:
    """Set the server's logical clock to the given ISO-8601 instant."""
    res = api_client.set_clock(set_clock_payload(to_iso8601), TEST_USERS["ssa_admin_headers"])
    get_success_data(res)


def advance_clock(to_iso8601: str) -> None:
    """Advance the clock; also re-evaluates child-auxiliary age terminations."""
    res = api_client.advance_clock(set_clock_payload(to_iso8601), TEST_USERS["ssa_admin_headers"])
    get_success_data(res)


# -------------------------------------------------------------------------
# Tier 1: Claimant + WorkCredit ledger
# -------------------------------------------------------------------------

def create_claimant(**overrides) -> dict:
    """Create a Claimant via SSAAdmin (PRD §3.1)."""
    payload = create_claimant_payload(**overrides)
    res = api_client.create_claimant(payload, TEST_USERS["ssa_admin_headers"])
    return get_success_data(res)


def post_work_credit(claimant_id: str, year: int, credits_earned: int = 4,
                     earnings_cents: int = 4_800_000) -> dict:
    """Post a single year of work credits (PRD §3.1)."""
    payload = create_work_credit_payload(claimant_id, year, credits_earned, earnings_cents)
    res = api_client.create_work_credit(payload, TEST_USERS["ssa_admin_headers"])
    return get_success_data(res)


def post_work_credits_for_years(claimant_id: str, years, credits_earned: int = 4,
                                earnings_cents: int = 4_800_000) -> None:
    """Bulk-post credits across an iterable of calendar years."""
    for year in years:
        post_work_credit(claimant_id, year, credits_earned, earnings_cents)


# Convenience: the 12-year "insured" baseline used by most fixtures
# (12 years of 4 credits each between 2014 and 2025 inclusive).
INSURED_BASELINE_YEARS = list(range(2014, 2026))


def setup_insured_baseline_claimant(
    earnings_cents: int = 4_800_000,
    ssn_last4: str = "1234",
    full_name: str = "Insured Baseline",
    date_of_birth: str = "1980-01-01T00:00:00Z",
    filing_state: str = "TX",
    **claimant_overrides,
) -> dict:
    """Create a claimant and post 12 years of full credits — produces an
    'insured' claimant whose QC totals comfortably pass §3.2 thresholds."""
    claimant = create_claimant(
        ssn_last4=ssn_last4,
        full_name=full_name,
        date_of_birth=date_of_birth,
        filing_state=filing_state,
        **claimant_overrides,
    )
    post_work_credits_for_years(claimant["id"], INSURED_BASELINE_YEARS,
                                credits_earned=4, earnings_cents=earnings_cents)
    return claimant


# -------------------------------------------------------------------------
# Tier 2: Application creation, submit, evidence
# -------------------------------------------------------------------------

def create_application_for_claimant(claimant_id: str, **overrides) -> dict:
    """Create a DRAFT application (PRD §3.2). Posted via SSAAdmin to avoid
    coupling test ordering to the ownership check on /applications."""
    payload = create_application_payload(claimant_id, **overrides)
    res = api_client.create_application(payload, TEST_USERS["ssa_admin_headers"])
    return get_success_data(res)


def submit_application(app_id: str, claimant_id: str) -> dict:
    """Submit a draft application for QC review (PRD §3.2)."""
    res = api_client.submit_application(app_id, make_claimant_headers(claimant_id))
    return get_success_data(res)


def attach_evidence(app_id: str, claimant_id: str = None,
                    source_type: str = "TREATING_PHYSICIAN",
                    report_date: str = "2024-02-01T00:00:00Z",
                    diagnosis_code: str = "M54.5",
                    severity_score: int = 80) -> dict:
    """Attach a single MedicalEvidence row (PRD §3.3). If claimant_id is
    provided, attaches as the claimant; otherwise as DDSExaminer."""
    payload = create_evidence_payload(
        source_type=source_type,
        report_date=report_date,
        diagnosis_code=diagnosis_code,
        severity_score=severity_score,
    )
    if claimant_id is not None:
        headers = make_claimant_headers(claimant_id)
    else:
        headers = TEST_USERS["dds_examiner_headers"]
    res = api_client.create_evidence(app_id, payload, headers)
    return get_success_data(res)


def setup_application_in_medical_review(
    claimant_overrides: dict = None,
    application_overrides: dict = None,
    earnings_cents: int = 4_800_000,
    attach_evidence_after: bool = True,
) -> tuple:
    """Insured claimant + DRAFT application + submit (→ MEDICAL_REVIEW) +
    optional one TREATING_PHYSICIAN evidence row attached.

    Returns (claimant, app_after_submit). The post-submit application's
    `version` field is the token a subsequent /medical-decision must echo
    via `expected_application_version`."""
    c_over = claimant_overrides or {}
    a_over = application_overrides or {}
    claimant = setup_insured_baseline_claimant(earnings_cents=earnings_cents, **c_over)
    app = create_application_for_claimant(claimant["id"], **a_over)
    app_submitted = submit_application(app["id"], claimant["id"])
    if attach_evidence_after:
        attach_evidence(app["id"], claimant_id=claimant["id"])
    return claimant, app_submitted


# -------------------------------------------------------------------------
# Tier 3: Medical decision (approval / denial), reconsideration, hearing
# -------------------------------------------------------------------------

def submit_medical_decision(
    app_id: str,
    expected_application_version: int,
    decision_type: str = "RFC_DISABLED",
    established_onset_date: str = "2024-01-15T00:00:00Z",
    listing_reference: str = None,
    rfc_score: int = None,
    examiner_headers: dict = None,
) -> dict:
    """Record a MedicalDeterminationDecision (PRD §3.4)."""
    if rfc_score is None and decision_type in {"RFC_DISABLED", "NOT_DISABLED"}:
        rfc_score = 30 if decision_type == "RFC_DISABLED" else 90
    payload = medical_decision_payload(
        decision_type=decision_type,
        established_onset_date=established_onset_date,
        expected_application_version=expected_application_version,
        listing_reference=listing_reference,
        rfc_score=rfc_score,
    )
    headers = examiner_headers or TEST_USERS["dds_examiner_headers"]
    res = api_client.medical_decision(app_id, payload, headers)
    return get_success_data(res)


def setup_application_awarded(
    claimant_overrides: dict = None,
    application_overrides: dict = None,
    earnings_cents: int = 4_800_000,
    medical_clock_override: str = None,
    decision_type: str = "RFC_DISABLED",
    established_onset_date: str = "2024-01-15T00:00:00Z",
) -> dict:
    """End-to-end: insured claimant + MEDICAL_REVIEW + APPROVED_INITIAL +
    BenefitAward (status ACTIVE, status AWARDED on application).

    `medical_clock_override` (optional) re-sets the clock just before the
    medical-decision so that decision.created_at is at a known instant
    (this controls the INITIAL_APPROVAL back-pay window).

    Returns dict with keys: claimant, application, decision, award."""
    claimant, app = setup_application_in_medical_review(
        claimant_overrides=claimant_overrides,
        application_overrides=application_overrides,
        earnings_cents=earnings_cents,
        attach_evidence_after=True,
    )
    if medical_clock_override is not None:
        set_clock(medical_clock_override)
    decision = submit_medical_decision(
        app["id"],
        expected_application_version=app["version"],
        decision_type=decision_type,
        established_onset_date=established_onset_date,
    )
    # Fetch the freshly-created BenefitAward via the list endpoint.
    res = api_client.list_awards(TEST_USERS["benefits_admin_headers"],
                                 params={"application_id": app["id"]})
    awards_payload = get_success_data(res)
    awards = awards_payload["items"] if isinstance(awards_payload, dict) and "items" in awards_payload else awards_payload
    assert len(awards) >= 1, f"Expected at least one award for {app['id']}, got {awards!r}"
    award = awards[0]
    return {
        "claimant": claimant,
        "application": app,
        "decision": decision,
        "award": award,
    }


def deny_medical_setup(
    claimant_overrides: dict = None,
    application_overrides: dict = None,
    earnings_cents: int = 4_800_000,
    medical_clock_override: str = None,
) -> dict:
    """Insured claimant → MEDICAL_REVIEW → DENIED_MEDICAL.
    Returns {claimant, application, decision}."""
    claimant, app = setup_application_in_medical_review(
        claimant_overrides=claimant_overrides,
        application_overrides=application_overrides,
        earnings_cents=earnings_cents,
        attach_evidence_after=True,
    )
    if medical_clock_override is not None:
        set_clock(medical_clock_override)
    decision = submit_medical_decision(
        app["id"],
        expected_application_version=app["version"],
        decision_type="NOT_DISABLED",
        established_onset_date="2024-01-15T00:00:00Z",
    )
    return {"claimant": claimant, "application": app, "decision": decision}


def request_reconsideration(app_id: str, claimant_id: str) -> dict:
    res = api_client.request_reconsideration(app_id, make_claimant_headers(claimant_id))
    return get_success_data(res)


def request_hearing(app_id: str, claimant_id: str) -> dict:
    """Returns the newly-created HearingRequest."""
    res = api_client.request_hearing(app_id, make_claimant_headers(claimant_id))
    return get_success_data(res)


def schedule_hearing(hearing_id: str, scheduled_date: str,
                    alj_headers: dict = None) -> dict:
    headers = alj_headers or TEST_USERS["alj_headers"]
    payload = schedule_hearing_payload(scheduled_date)
    res = api_client.schedule_hearing(hearing_id, payload, headers)
    return get_success_data(res)


def record_hearing_held(hearing_id: str, alj_headers: dict = None) -> dict:
    headers = alj_headers or TEST_USERS["alj_headers"]
    res = api_client.record_held_hearing(hearing_id, headers)
    return get_success_data(res)


def decide_hearing(hearing_id: str, outcome: str,
                   alj_headers: dict = None) -> dict:
    headers = alj_headers or TEST_USERS["alj_headers"]
    payload = hearing_decision_payload(outcome)
    res = api_client.hearing_decision(hearing_id, payload, headers)
    return get_success_data(res)


def setup_hearing_in_requested(
    claimant_overrides: dict = None,
    earnings_cents: int = 4_800_000,
    medical_clock_override: str = None,
) -> dict:
    """Walk to RECONSIDERATION → ALJ_PENDING with HearingRequest in
    REQUESTED. Returns {claimant, application, decision, hearing}."""
    ctx = deny_medical_setup(
        claimant_overrides=claimant_overrides,
        earnings_cents=earnings_cents,
        medical_clock_override=medical_clock_override,
    )
    request_reconsideration(ctx["application"]["id"], ctx["claimant"]["id"])
    hearing = request_hearing(ctx["application"]["id"], ctx["claimant"]["id"])
    ctx["hearing"] = hearing
    return ctx


# -------------------------------------------------------------------------
# Tier 4: Award children, suspend / reinstate
# -------------------------------------------------------------------------

def get_current_award(award_id: str) -> dict:
    res = api_client.get_award(award_id, TEST_USERS["benefits_admin_headers"])
    return get_success_data(res)


def create_child_auxiliary(award_id: str, expected_benefit_award_version: int,
                            child_full_name: str = "Test Child",
                            child_date_of_birth: str = "2015-01-01T00:00:00Z",
                            relationship: str = "BIOLOGICAL",
                            benefits_admin_headers: dict = None) -> dict:
    payload = create_child_auxiliary_payload(
        child_full_name=child_full_name,
        child_date_of_birth=child_date_of_birth,
        relationship=relationship,
        expected_benefit_award_version=expected_benefit_award_version,
    )
    headers = benefits_admin_headers or TEST_USERS["benefits_admin_headers"]
    res = api_client.create_child_auxiliary(award_id, payload, headers)
    return get_success_data(res)


def suspend_award(award_id: str, benefits_admin_headers: dict = None) -> dict:
    headers = benefits_admin_headers or TEST_USERS["benefits_admin_headers"]
    res = api_client.suspend_award(award_id, headers)
    return get_success_data(res)


def reinstate_award(award_id: str, benefits_admin_headers: dict = None) -> dict:
    headers = benefits_admin_headers or TEST_USERS["benefits_admin_headers"]
    res = api_client.reinstate_award(award_id, headers)
    return get_success_data(res)


# -------------------------------------------------------------------------
# Tier 5: CDR lifecycle
# -------------------------------------------------------------------------

def fetch_cdr_for_award(award_id: str) -> dict:
    res = api_client.list_cdr_reviews(TEST_USERS["ssa_admin_headers"],
                                       params={"benefit_award_id": award_id})
    payload = get_success_data(res)
    items = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
    assert len(items) >= 1, f"Expected CDR for award {award_id}, got {items!r}"
    return items[0]


def start_cdr(cdr_id: str) -> dict:
    res = api_client.start_cdr(cdr_id, TEST_USERS["ssa_admin_headers"])
    return get_success_data(res)


def complete_cdr(cdr_id: str, outcome: str) -> dict:
    payload = complete_cdr_payload(outcome)
    res = api_client.complete_cdr(cdr_id, payload, TEST_USERS["ssa_admin_headers"])
    return get_success_data(res)


def setup_awarded_with_active_child(
    claimant_overrides: dict = None,
    application_overrides: dict = None,
    earnings_cents: int = 4_800_000,
    child_full_name: str = "Test Child",
    child_date_of_birth: str = "2015-01-01T00:00:00Z",
    relationship: str = "BIOLOGICAL",
) -> dict:
    """AWARDED + one ACTIVE ChildAuxiliaryBenefit. Returns
    {claimant, application, decision, award, child}."""
    ctx = setup_application_awarded(
        claimant_overrides=claimant_overrides,
        application_overrides=application_overrides,
        earnings_cents=earnings_cents,
    )
    award_id = ctx["award"]["id"]
    award_v = ctx["award"]["version"]
    child = create_child_auxiliary(
        award_id,
        expected_benefit_award_version=award_v,
        child_full_name=child_full_name,
        child_date_of_birth=child_date_of_birth,
        relationship=relationship,
    )
    ctx["child"] = child
    return ctx
