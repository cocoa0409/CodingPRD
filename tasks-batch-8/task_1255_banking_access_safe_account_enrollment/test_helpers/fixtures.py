"""Composite setup helpers (PRD §3 workflows).

Each helper builds preconditions from scratch using only PRD-declared
endpoints; every test runs against a fresh server (per-test-server isolation),
so fixtures always start from an empty database and the startup logical clock
(2026-05-01T00:00:00Z). Setup calls use the lenient get_success_data()
validator so failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .factories import (
    create_account_standard_payload, create_partner_institution_payload,
    create_certification_review_payload, score_payload, make_criteria_ratings,
    create_participant_payload, documents_payload, create_referral_payload,
    create_event_payload, create_application_payload, decision_payload,
    propose_payload, create_education_pairing_payload,
    create_funding_grant_payload, create_partner_report_payload,
    create_campaign_payload, VERIFIED_MATRICULA_DOCS,
)
from .test_users import (
    TEST_USERS, make_coalition_admin_headers, make_agency_navigator_headers,
    make_financial_coach_headers, make_institution_officer_headers,
    make_participant_headers,
)

ADMIN = TEST_USERS["coalition_admin_headers"]
NAV = TEST_USERS["agency_navigator_headers"]
COACH = TEST_USERS["financial_coach_headers"]
SCORER = make_coalition_admin_headers("admin-scorer")
FINALIZER = make_coalition_admin_headers("admin-finalizer")


def _fail(step, resp):
    raise AssertionError(f"Setup failed at {step}: {resp.status_code} {resp.text}")


def _ok(resp, step):
    data = get_success_data(resp)
    if not isinstance(data, dict) or "id" not in data:
        _fail(step, resp)
    return data


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators and clock/epoch drivers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    resp = _api.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


def run_ops_epoch():
    resp = _api.ops_evaluate_due(ADMIN)
    return get_success_data(resp)


def create_standard(**overrides):
    """Create an AccountStandard in DRAFT."""
    resp = _api.create_account_standard(create_account_standard_payload(**overrides), ADMIN)
    return _ok(resp, "create_account_standard")


def activate_standard(standard_id):
    resp = _api.activate_account_standard(standard_id, ADMIN)
    return _ok(resp, "activate_account_standard")


def setup_effective_standard(**overrides):
    """Create + activate a standard. Returns the EFFECTIVE standard."""
    std = create_standard(**overrides)
    return activate_standard(std["id"])


def create_institution(**overrides):
    """Register a PartnerInstitution (lands APPLIED)."""
    resp = _api.create_partner_institution(create_partner_institution_payload(**overrides), ADMIN)
    return _ok(resp, "create_partner_institution")


def get_institution(institution_id):
    return get_success_data(_api.get_partner_institution(institution_id, ADMIN))


def suspend_institution(institution_id):
    return _ok(_api.suspend_partner_institution(institution_id, ADMIN), "suspend_institution")


def reinstate_institution(institution_id):
    return _ok(_api.reinstate_partner_institution(institution_id, ADMIN), "reinstate_institution")


def open_review(institution, standard_id, period_start="2026-02-01",
                period_end="2026-02-28", expected_institution_version=None):
    """Open a CertificationReview against an institution (OCC on its version)."""
    inst_id = institution["id"] if isinstance(institution, dict) else institution
    if expected_institution_version is None:
        expected_institution_version = get_institution(inst_id)["version"]
    payload = create_certification_review_payload(
        inst_id, standard_id, expected_institution_version,
        period_start=period_start, period_end=period_end,
    )
    resp = _api.create_certification_review(payload, ADMIN)
    return _ok(resp, "create_certification_review")


def score_review(review_id, ratings=None, scorer=SCORER):
    resp = _api.score_certification_review(review_id, score_payload(ratings), scorer)
    return _ok(resp, "score_certification_review")


def finalize_review(review_id, finalizer=FINALIZER):
    resp = _api.finalize_certification_review(review_id, finalizer)
    return _ok(resp, "finalize_certification_review")


def setup_certified_institution(rubric_mode="STANDARD_RUBRIC",
                                requires_financial_education=False,
                                accepted_alt_id_types=("MATRICULA_CONSULAR",),
                                ratings=None, legal_name="Harbor CU",
                                charter_type="CREDIT_UNION",
                                standard_code="BO-2026",
                                standard_name="Bank On 2026",
                                period_start="2026-02-01",
                                period_end="2026-02-28"):
    """EFFECTIVE standard + institution certified under it through a full
    review lifecycle (open -> score -> finalize). Returns a dict with the
    standard, institution (CERTIFIED), and review."""
    std = setup_effective_standard(
        code=standard_code, name=standard_name, rubric_mode=rubric_mode,
        requires_financial_education=requires_financial_education,
        accepted_alt_id_types=list(accepted_alt_id_types),
    )
    inst = create_institution(legal_name=legal_name, charter_type=charter_type)
    rev = open_review(inst, std["id"], period_start, period_end,
                      expected_institution_version=inst["version"])
    score_review(rev["id"], ratings)
    finalize_review(rev["id"])
    return {
        "standard": std,
        "institution": get_institution(inst["id"]),
        "review": rev,
    }


def create_participant(navigator=NAV, **overrides):
    resp = _api.create_participant(create_participant_payload(**overrides), navigator)
    return _ok(resp, "create_participant")


def setup_documented_participant(id_doc_type="MATRICULA_CONSULAR", navigator=NAV, **overrides):
    """Participant whose docs_complete is true at creation: one VERIFIED
    identity doc plus a VERIFIED PROOF_OF_ADDRESS (PRD §3.3)."""
    docs = [
        {"doc_type": id_doc_type, "status": "VERIFIED"},
        {"doc_type": "PROOF_OF_ADDRESS", "status": "VERIFIED"},
    ]
    overrides.setdefault("id_documents", docs)
    return create_participant(navigator=navigator, **overrides)


def update_documents(participant_id, id_documents, navigator=NAV):
    resp = _api.update_participant_documents(
        participant_id, documents_payload(id_documents), navigator
    )
    return _ok(resp, "update_participant_documents")


def create_referral(participant_id, navigator=NAV, **overrides):
    resp = _api.create_referral(create_referral_payload(participant_id, **overrides), navigator)
    return _ok(resp, "create_referral")


def referral_docs_complete(referral_id, navigator=NAV):
    return _ok(_api.referral_docs_complete(referral_id, navigator), "referral_docs_complete")


def setup_referral_docs_complete(navigator=NAV, **participant_overrides):
    """Documented participant + referral advanced to DOCS_COMPLETE."""
    p = setup_documented_participant(navigator=navigator, **participant_overrides)
    ref = create_referral(p["id"], navigator=navigator)
    ref = referral_docs_complete(ref["id"], navigator=navigator)
    return {"participant": p, "referral": ref}


def create_event(institution_id, officer=None, **overrides):
    officer = officer or make_institution_officer_headers(institution_id)
    resp = _api.create_account_opening_event(
        create_event_payload(institution_id, **overrides), officer
    )
    return _ok(resp, "create_account_opening_event")


def get_event(event_id, headers=ADMIN):
    return get_success_data(_api.get_account_opening_event(event_id, headers))


def book_referral(referral_id, event_id, navigator=NAV):
    return _ok(_api.book_referral(referral_id, {"event_id": event_id}, navigator), "book_referral")


def create_application(institution_id, participant_id, officer=None, **overrides):
    officer = officer or make_institution_officer_headers(institution_id)
    resp = _api.create_account_application(
        create_application_payload(participant_id, institution_id, **overrides), officer
    )
    return _ok(resp, "create_account_application")


def decide_application(application_id, institution_id, outcome, officer=None, **overrides):
    officer = officer or make_institution_officer_headers(institution_id)
    resp = _api.decide_account_application(
        application_id, decision_payload(outcome, **overrides), officer
    )
    return _ok(resp, "decide_account_application")


def setup_submitted_application(prior_banking_record="CLEAN",
                                requires_financial_education=False,
                                id_doc_type="MATRICULA_CONSULAR",
                                navigator=NAV, **cert_kwargs):
    """Certified institution + documented participant + DOCS_COMPLETE referral
    + SUBMITTED application referencing the referral."""
    cert = setup_certified_institution(
        requires_financial_education=requires_financial_education, **cert_kwargs
    )
    inst = cert["institution"]
    pr = setup_referral_docs_complete(
        navigator=navigator, prior_banking_record=prior_banking_record,
        id_doc_type=id_doc_type,
    )
    app = create_application(inst["id"], pr["participant"]["id"],
                             referral_id=pr["referral"]["id"],
                             id_type_presented=id_doc_type)
    return {**cert, "participant": pr["participant"], "referral": pr["referral"],
            "application": app}


def setup_opened_account(navigator=NAV, **kwargs):
    """A SUBMITTED application approved to OPENED at the current clock."""
    ctx = setup_submitted_application(navigator=navigator, **kwargs)
    inst = ctx["institution"]
    app = decide_application(ctx["application"]["id"], inst["id"], "APPROVE")
    ctx["application"] = app
    return ctx


def find_barrier_case_for_application(application_id, headers=ADMIN):
    data = get_success_data(
        _api.list_barrier_cases(headers, params={"application_id": application_id})
    )
    rows = data if isinstance(data, list) else data.get("data", [])
    assert len(rows) >= 1, f"Setup failed: no barrier case for application {application_id}"
    return rows[0]


def setup_declined_chex_case(navigator=NAV, **kwargs):
    """FLAGGED participant; application DECLINE/CHEX; returns the spawned
    BarrierCase (status OPEN)."""
    kwargs.setdefault("prior_banking_record", "FLAGGED")
    ctx = setup_submitted_application(navigator=navigator, **kwargs)
    inst = ctx["institution"]
    decide_application(ctx["application"]["id"], inst["id"], "DECLINE",
                       decline_reason="CHEX")
    case = find_barrier_case_for_application(ctx["application"]["id"])
    ctx["case"] = case
    return ctx


def propose_case(case_id, institution_id, amount, officer=None):
    officer = officer or make_institution_officer_headers(institution_id)
    return _ok(_api.propose_barrier_case(case_id, propose_payload(amount), officer),
               "propose_barrier_case")


def counter_case(case_id, navigator=NAV):
    return _ok(_api.counter_barrier_case(case_id, {}, navigator), "counter_barrier_case")


def accept_case(case_id, participant_id):
    return _ok(_api.accept_barrier_case(case_id, {}, make_participant_headers(participant_id)),
               "accept_barrier_case")


def escalate_case(case_id, institution_id, officer=None):
    officer = officer or make_institution_officer_headers(institution_id)
    return _ok(_api.escalate_barrier_case(case_id, {}, officer), "escalate_barrier_case")


def create_pairing(participant_id, coach_id="coach-1", course_code="FOUNDATIONS", headers=None):
    headers = headers or make_financial_coach_headers(coach_id)
    resp = _api.create_education_pairing(
        create_education_pairing_payload(participant_id, coach_id, course_code=course_code),
        headers,
    )
    return _ok(resp, "create_education_pairing")


def complete_pairing(pairing_id, coach_id="coach-1"):
    return _ok(_api.complete_education_pairing(
        pairing_id, make_financial_coach_headers(coach_id)
    ), "complete_education_pairing")


def create_grant(**overrides):
    resp = _api.create_funding_grant(create_funding_grant_payload(**overrides), ADMIN)
    return _ok(resp, "create_funding_grant")


def activate_grant(grant_id):
    return _ok(_api.activate_funding_grant(grant_id, ADMIN), "activate_funding_grant")


def setup_active_grant(total_cents=500000, per_report_cap_cents=200000, **overrides):
    """A grant created and activated; the returned dict is the ACTIVE grant
    (its version is the post-activation one used for OCC on report create)."""
    g = create_grant(total_cents=total_cents, per_report_cap_cents=per_report_cap_cents,
                     **overrides)
    return activate_grant(g["id"])


def get_grant(grant_id, headers=ADMIN):
    return get_success_data(_api.get_funding_grant(grant_id, headers))


def create_report(institution_id, grant, period_start="2026-01-01",
                  period_end="2026-05-31", evaluation_mode="FINAL",
                  expected_grant_version=None, officer=None):
    """Create a DRAFT PartnerReport with its computed claim snapshot."""
    if expected_grant_version is None:
        expected_grant_version = get_grant(grant["id"])["version"]
    officer = officer or make_institution_officer_headers(institution_id)
    payload = create_partner_report_payload(
        institution_id, grant["id"], expected_grant_version,
        period_start=period_start, period_end=period_end,
        evaluation_mode=evaluation_mode,
    )
    resp = _api.create_partner_report(payload, officer)
    return _ok(resp, "create_partner_report")


def submit_report(report_id, institution_id, officer=None):
    officer = officer or make_institution_officer_headers(institution_id)
    return _ok(_api.submit_partner_report(report_id, officer), "submit_partner_report")


def setup_report_ready(num_accounts=1, grant_total=500000, grant_cap=200000,
                       requires_financial_education=False,
                       with_completed_pairing=False, navigator=NAV):
    """Certified institution with num_accounts OPENED accounts (approved at the
    startup clock 2026-05-01) and an ACTIVE grant. Returns a dict with the
    institution, standard, grant, and the opened applications/participants."""
    ctx = setup_certified_institution(
        requires_financial_education=requires_financial_education
    )
    inst = ctx["institution"]
    applications = []
    participants = []
    for i in range(num_accounts):
        pr = setup_referral_docs_complete(
            navigator=navigator,
            full_name=f"Participant {i}",
            date_of_birth=f"1990-01-{10 + i:02d}",
        )
        if with_completed_pairing:
            pairing = create_pairing(pr["participant"]["id"])
            complete_pairing(pairing["id"])
        app = create_application(inst["id"], pr["participant"]["id"],
                                 referral_id=pr["referral"]["id"])
        app = decide_application(app["id"], inst["id"], "APPROVE")
        applications.append(app)
        participants.append(pr["participant"])
    grant = setup_active_grant(total_cents=grant_total, per_report_cap_cents=grant_cap)
    return {"institution": inst, "standard": ctx["standard"], "grant": grant,
            "applications": applications, "participants": participants}


def create_campaign(**overrides):
    resp = _api.create_outreach_campaign(create_campaign_payload(**overrides), ADMIN)
    return _ok(resp, "create_outreach_campaign")


# ---------------------------------------------------------------------------
# Tier 4: retention scenario — two accounts opened on different dates, then
# epoch-evaluated so exactly one M6 checkpoint is EVALUATED_RETAINED
# ---------------------------------------------------------------------------

def setup_two_account_retention_scenario(navigator=NAV):
    """Certified institution; A1 OPENED at the startup clock 2026-05-01 (M6 due
    2026-10-31), A2 OPENED at 2026-05-15 (M6 due 2026-11-14); clock advanced to
    2026-11-10 and the ops epoch run (A1.M6 -> EVALUATED_RETAINED, A2.M6 stays
    PENDING); two ACTIVE grants ready for PROVISIONAL / FINAL reports."""
    ctx = setup_certified_institution()
    inst = ctx["institution"]

    def _open_one(name):
        pr = setup_referral_docs_complete(navigator=navigator, full_name=name)
        app = create_application(inst["id"], pr["participant"]["id"],
                                 referral_id=pr["referral"]["id"])
        return decide_application(app["id"], inst["id"], "APPROVE")

    app1 = _open_one("Ana Ruiz")            # opened at 2026-05-01 (startup clock)
    set_clock("2026-05-15T00:00:00Z")
    app2 = _open_one("Ben Okafor")          # opened at 2026-05-15
    set_clock("2026-11-10T00:00:00Z")
    run_ops_epoch()
    grant_p = setup_active_grant(funder_name="City Foundation")
    grant_f = setup_active_grant(funder_name="United Fund")
    return {**ctx, "app1": app1, "app2": app2,
            "grant_provisional": grant_p, "grant_final": grant_f}


# ---------------------------------------------------------------------------
# Tier 3: review-lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_scored_review(ratings=None, scorer=SCORER, standard_overrides=None,
                        legal_name="Harbor CU"):
    """EFFECTIVE standard + institution UNDER_REVIEW with a SCORED review
    (not yet finalized). Returns dict(standard, institution, review)."""
    std = setup_effective_standard(**(standard_overrides or {}))
    inst = create_institution(legal_name=legal_name)
    rev = open_review(inst, std["id"],
                      expected_institution_version=inst["version"])
    rev = score_review(rev["id"], ratings, scorer=scorer)
    return {"standard": std, "institution": get_institution(inst["id"]), "review": rev}


def setup_rubric_divergence(ratings=None):
    """Standard S (STANDARD_RUBRIC) EFFECTIVE; I1 reviewed and finalized under
    S; then standard R (REMEDIATION_RUBRIC) activated (S auto-SUPERSEDED) and
    I2 reviewed under R with identical ratings, left SCORED. Returns dict."""
    ratings = ratings if ratings is not None else make_criteria_ratings(edu=1)
    s1 = setup_scored_review(ratings, legal_name="Harbor CU",
                             standard_overrides={"code": "BO-2026-S",
                                                 "name": "Bank On Standard",
                                                 "rubric_mode": "STANDARD_RUBRIC"})
    rev1 = finalize_review(s1["review"]["id"])
    std_r = setup_effective_standard(code="BO-2026-R", name="Bank On Remediation",
                                     rubric_mode="REMEDIATION_RUBRIC")
    inst2 = create_institution(legal_name="Metro Bank", charter_type="BANK")
    rev2 = open_review(inst2, std_r["id"],
                       expected_institution_version=inst2["version"])
    rev2 = score_review(rev2["id"], ratings)
    return {"standard_s": get_success_data(_api.get_account_standard(s1["standard"]["id"], ADMIN)),
            "standard_r": std_r,
            "institution1": s1["institution"], "review1": rev1,
            "institution2": get_institution(inst2["id"]), "review2": rev2}


def setup_two_institutions_scored(ratings1, ratings2):
    """One EFFECTIVE standard; two institutions each with a SCORED review
    carrying the given ratings. Returns dict(standard, review1, review2)."""
    std = setup_effective_standard()
    inst1 = create_institution(legal_name="Harbor CU", charter_type="CREDIT_UNION")
    rev1 = open_review(inst1, std["id"], expected_institution_version=inst1["version"])
    rev1 = score_review(rev1["id"], ratings1)
    inst2 = create_institution(legal_name="Metro Bank", charter_type="BANK")
    rev2 = open_review(inst2, std["id"], expected_institution_version=inst2["version"])
    rev2 = score_review(rev2["id"], ratings2)
    return {"standard": std, "review1": rev1, "review2": rev2}


def setup_decertification_pending(navigator=NAV):
    """CERTIFIED institution; documented participant booked onto a SCHEDULED
    event; a second review (gap-compliant period) SCORED with FEE_COMPLIANCE
    rating 0 so finalization computes FAIL. Returns dict with all ids."""
    ctx = setup_certified_institution()
    inst = ctx["institution"]
    pr = setup_referral_docs_complete(navigator=navigator)
    event = create_event(inst["id"])
    book_referral(pr["referral"]["id"], event["id"], navigator=navigator)
    rev2 = open_review(inst, ctx["standard"]["id"],
                       period_start="2026-04-01", period_end="2026-04-30")
    ratings = make_criteria_ratings(fee=0)
    rev2 = score_review(rev2["id"], ratings)
    return {**ctx, "participant": pr["participant"], "referral": pr["referral"],
            "event": event, "review2": rev2}


def setup_event_with_referrals(num_participants=2, capacity=2, navigator=NAV,
                               **event_overrides):
    """Certified institution + SCHEDULED event + N DOCS_COMPLETE referrals
    (not yet booked). Returns dict(institution, event, referrals, participants)."""
    ctx = setup_certified_institution()
    inst = ctx["institution"]
    event = create_event(inst["id"], capacity=capacity, **event_overrides)
    referrals, participants = [], []
    for i in range(num_participants):
        pr = setup_referral_docs_complete(
            navigator=navigator, full_name=f"Participant {i}",
            date_of_birth=f"1990-01-{10 + i:02d}",
        )
        referrals.append(pr["referral"])
        participants.append(pr["participant"])
    return {**ctx, "event": event, "referrals": referrals,
            "participants": participants}
