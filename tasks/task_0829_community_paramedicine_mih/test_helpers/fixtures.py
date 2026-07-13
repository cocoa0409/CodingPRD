"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared endpoints,
because the server database is empty at the start of each test. Helpers use the lenient
get_success_data() validator internally so setup failures surface as clear errors.

Identity threading: entity_backed roles (CareCoordinator, Paramedic, Clinician,
BillingSpecialist -> Provider; PayerReviewer -> Payer) always act under headers built
from the real entity id via the make_*_headers builders.
"""
from prd_bench_local_runner.testing import get_success_data
from . import factories as f
from .test_users import (
    make_program_admin_headers,
    make_care_coordinator_headers,
    make_paramedic_headers,
    make_clinician_headers,
    make_billing_specialist_headers,
    make_payer_reviewer_headers,
)

_NPI_SEQ = [0]


def _next_npi() -> str:
    _NPI_SEQ[0] += 1
    return f"90000{_NPI_SEQ[0]:05d}"


def _d(resp) -> dict:
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1/2 — organizational bootstrap (payer + program + full provider bench)
# ---------------------------------------------------------------------------
def bootstrap(api, program_overrides=None) -> dict:
    """Create a payer, a program, and one provider of each type.

    Returns an org context dict with ids and pre-threaded role headers.
    """
    admin = make_program_admin_headers()
    payer = _d(api.create_payer(f.create_payer_payload(), admin))
    program = _d(api.create_program(
        f.create_program_payload(payer["id"], **(program_overrides or {})), admin))
    coord = _d(api.create_provider(
        f.create_provider_payload("COORDINATOR", "Coord", _next_npi()), admin))
    clin = _d(api.create_provider(
        f.create_provider_payload("CLINICIAN", "Clin", _next_npi()), admin))
    para = _d(api.create_provider(
        f.create_provider_payload("PARAMEDIC", "Para", _next_npi()), admin))
    biller = _d(api.create_provider(
        f.create_provider_payload("BILLER", "Bill", _next_npi()), admin))
    return {
        "admin_headers": admin,
        "payer": payer,
        "payer_id": payer["id"],
        "program": program,
        "program_id": program["id"],
        "coord": coord,
        "coord_id": coord["id"],
        "coord_headers": make_care_coordinator_headers(coord["id"]),
        "clin": clin,
        "clin_id": clin["id"],
        "clin_headers": make_clinician_headers(clin["id"]),
        "para": para,
        "para_id": para["id"],
        "para_headers": make_paramedic_headers(para["id"]),
        "biller": biller,
        "biller_id": biller["id"],
        "biller_headers": make_billing_specialist_headers(biller["id"]),
        "payer_reviewer_headers": make_payer_reviewer_headers(payer["id"]),
    }


def add_provider(api, org, provider_type, **overrides) -> dict:
    return _d(api.create_provider(
        f.create_provider_payload(provider_type, npi=_next_npi(), **overrides),
        org["admin_headers"]))


# ---------------------------------------------------------------------------
# Referral / enrollment steps
# ---------------------------------------------------------------------------
def create_patient(api, org, **overrides) -> dict:
    return _d(api.create_patient(f.create_patient_payload(**overrides), org["coord_headers"]))


def create_referral(api, org, patient_id, referring_source="ED") -> dict:
    return _d(api.create_referral(
        f.create_referral_payload(patient_id, org["program_id"], referring_source),
        org["coord_headers"]))


def screen_referral(api, org, referral_id) -> dict:
    return _d(api.screen_referral(referral_id, org["coord_headers"]))


def accept_referral(api, org, referral_id) -> dict:
    return _d(api.accept_referral(referral_id, org["coord_headers"]))


def create_screened_referral(api, org, patient_overrides=None, referring_source="ED") -> dict:
    """Patient + referral advanced to SCREENED (not yet accepted)."""
    patient = create_patient(api, org, **(patient_overrides or {}))
    referral = create_referral(api, org, patient["id"], referring_source)
    screen_referral(api, org, referral["id"])
    return {"patient": patient, "patient_id": patient["id"], "referral_id": referral["id"]}


def enroll_patient(api, org, patient_overrides=None, referring_source="ED") -> dict:
    """Patient -> referral -> screen -> accept. Returns enrollment context."""
    sr = create_screened_referral(api, org, patient_overrides, referring_source)
    enrollment = accept_referral(api, org, sr["referral_id"])
    return {
        "patient": sr["patient"],
        "patient_id": sr["patient_id"],
        "referral_id": sr["referral_id"],
        "enrollment": enrollment,
        "enrollment_id": enrollment["id"],
        "enrollment_version": enrollment["version"],
    }


# ---------------------------------------------------------------------------
# Care-plan steps
# ---------------------------------------------------------------------------
def create_care_plan(api, org, enrollment_id, enrollment_version,
                     risk_level="MODERATE", cosigner_clinician_id=None, goals="reduce ED") -> dict:
    extra = {}
    if cosigner_clinician_id is not None:
        extra["cosigner_clinician_id"] = cosigner_clinician_id
    payload = f.create_care_plan_payload(
        org["clin_id"], enrollment_version, risk_level=risk_level, goals=goals, **extra)
    return _d(api.create_care_plan(enrollment_id, payload, org["clin_headers"]))


def activate_care_plan(api, org, care_plan_id) -> dict:
    return _d(api.activate_care_plan(care_plan_id, org["clin_headers"]))


def create_active_care_plan(api, org, enrollment_id, enrollment_version,
                            risk_level="MODERATE", cosigner_clinician_id=None) -> dict:
    cp = create_care_plan(api, org, enrollment_id, enrollment_version,
                          risk_level=risk_level, cosigner_clinician_id=cosigner_clinician_id)
    activate_care_plan(api, org, cp["id"])
    return cp


# ---------------------------------------------------------------------------
# Encounter steps
# ---------------------------------------------------------------------------
def schedule_home_visit(api, org, enrollment_id, care_plan_id, start, end, provider_id=None) -> dict:
    payload = f.create_home_visit_payload(
        enrollment_id, care_plan_id, provider_id or org["para_id"], start, end)
    return _d(api.create_home_visit(payload, org["coord_headers"]))


def complete_home_visit(api, org, home_visit_id, vitals=None) -> dict:
    return _d(api.complete_home_visit(
        home_visit_id, vitals or f.vitals_payload(), org["para_headers"]))


def add_completed_home_visit(api, org, enrollment_id, care_plan_id, start, end, vitals=None) -> dict:
    hv = schedule_home_visit(api, org, enrollment_id, care_plan_id, start, end)
    complete_home_visit(api, org, hv["id"], vitals)
    return hv


def schedule_telehealth(api, org, enrollment_id, patient_id, start, end, provider_id=None) -> dict:
    payload = f.create_telehealth_payload(
        enrollment_id, patient_id, provider_id or org["clin_id"], start, end)
    return _d(api.create_telehealth_session(payload, org["coord_headers"]))


def add_completed_telehealth(api, org, enrollment_id, patient_id, start, end, vitals=None) -> dict:
    ts = schedule_telehealth(api, org, enrollment_id, patient_id, start, end)
    _d(api.complete_telehealth_session(ts["id"], vitals or f.vitals_payload(), org["clin_headers"]))
    return ts


# ---------------------------------------------------------------------------
# Billing steps
# ---------------------------------------------------------------------------
def create_draft_claim(api, org, enrollment_id, period_start="2026-03-01T00:00:00Z",
                       period_end="2026-04-01T00:00:00Z") -> dict:
    payload = f.create_billing_claim_payload(
        enrollment_id, org["program_id"], org["payer_id"], period_start, period_end)
    return _d(api.create_billing_claim(payload, org["biller_headers"]))


def submit_claim(api, org, claim_id) -> dict:
    return _d(api.submit_billing_claim(claim_id, org["biller_headers"]))


# ---------------------------------------------------------------------------
# High-level composite scenarios
# ---------------------------------------------------------------------------
def setup_enrollment_with_active_plan(api, program_overrides=None, patient_overrides=None,
                                      risk_level="MODERATE") -> dict:
    """Org + active enrollment + one ACTIVE care plan. The workhorse context."""
    org = bootstrap(api, program_overrides)
    enr = enroll_patient(api, org, patient_overrides)
    cp = create_active_care_plan(api, org, enr["enrollment_id"], enr["enrollment_version"],
                                 risk_level=risk_level)
    ctx = dict(org=org, **enr)
    ctx["care_plan"] = cp
    ctx["care_plan_id"] = cp["id"]
    return ctx


def setup_enrollment_with_draft_plan(api, program_overrides=None, patient_overrides=None,
                                     risk_level="MODERATE", cosigner_clinician_id=None) -> dict:
    """Org + active enrollment + one DRAFT (unactivated) care plan."""
    org = bootstrap(api, program_overrides)
    enr = enroll_patient(api, org, patient_overrides)
    cp = create_care_plan(api, org, enr["enrollment_id"], enr["enrollment_version"],
                          risk_level=risk_level, cosigner_clinician_id=cosigner_clinician_id)
    ctx = dict(org=org, **enr)
    ctx["care_plan"] = cp
    ctx["care_plan_id"] = cp["id"]
    return ctx


def setup_dual_variant_claim(api) -> dict:
    """Enrollment with 2 COMPLETED home visits + 1 SCHEDULED home visit + 1 COMPLETED
    telehealth, then a DRAFT claim created and submitted over [2026-03-01, 2026-04-01).

    Program rates: per_visit 15000, per_telehealth 8000, diversion_bonus 50000,
    diversion_target_max_ed_visits 1 (0 ED events => diversion achieved).

    Returns claim_created (provisional) and claim_submitted (final).
    """
    ctx = setup_enrollment_with_active_plan(api)
    org, enr_id, cp_id = ctx["org"], ctx["enrollment_id"], ctx["care_plan_id"]
    pat_id = ctx["patient_id"]
    add_completed_home_visit(api, org, enr_id, cp_id,
                             "2026-03-02T10:00:00Z", "2026-03-02T11:00:00Z")
    add_completed_home_visit(api, org, enr_id, cp_id,
                             "2026-03-03T10:00:00Z", "2026-03-03T11:00:00Z")
    schedule_home_visit(api, org, enr_id, cp_id,
                        "2026-03-04T10:00:00Z", "2026-03-04T11:00:00Z")  # left SCHEDULED
    add_completed_telehealth(api, org, enr_id, pat_id,
                             "2026-03-05T09:00:00Z", "2026-03-05T09:30:00Z")
    claim_created = create_draft_claim(api, org, enr_id)
    claim_submitted = submit_claim(api, org, claim_created["id"])
    ctx["claim_created"] = claim_created
    ctx["claim_submitted"] = claim_submitted
    ctx["claim_id"] = claim_created["id"]
    return ctx


def setup_single_visit_claim(api, program_overrides=None) -> dict:
    """Enrollment with exactly one COMPLETED home visit and a DRAFT claim.

    Final amount = 1*per_visit_rate + diversion_bonus (0 ED events, target 1)
                 = 15000 + 50000 = 65000 with default rates.
    """
    ctx = setup_enrollment_with_active_plan(api, program_overrides=program_overrides)
    org, enr_id, cp_id = ctx["org"], ctx["enrollment_id"], ctx["care_plan_id"]
    hv = add_completed_home_visit(api, org, enr_id, cp_id,
                                  "2026-03-02T10:00:00Z", "2026-03-02T11:00:00Z")
    claim = create_draft_claim(api, org, enr_id)
    ctx["home_visit"] = hv
    ctx["claim"] = claim
    ctx["claim_id"] = claim["id"]
    return ctx


def setup_submitted_claim(api, program_overrides=None) -> dict:
    """Single-visit enrollment with the claim already SUBMITTED (commits 65000)."""
    ctx = setup_single_visit_claim(api, program_overrides=program_overrides)
    submit_claim(api, ctx["org"], ctx["claim_id"])
    return ctx


def setup_cost_outcome(api, baseline_ed_visits_12mo=8, actual_ed_visit_dates=None) -> dict:
    """Enrollment accepted at the default clock (2026-03-01), clock advanced to 2027-03-01
    (365 enrollment_days), with the given actual ED_VISIT events recorded in the period.

    Returns the enrollment context plus the cost-outcome report `data`.
    """
    org = bootstrap(api)
    enr = enroll_patient(api, org, {"baseline_ed_visits_12mo": baseline_ed_visits_12mo})
    # Advance the logical clock a full year after enrolment.
    _d(api.set_clock({"to_iso8601": "2027-03-01T00:00:00Z"}, org["admin_headers"]))
    dates = actual_ed_visit_dates if actual_ed_visit_dates is not None else [
        "2026-06-01T00:00:00Z", "2026-09-01T00:00:00Z"]
    for dt in dates:
        _d(api.create_ed_event(
            f.create_ed_event_payload(enr["patient_id"], "ED_VISIT", dt), org["coord_headers"]))
    report = _d(api.get_cost_outcome(enr["enrollment_id"], org["coord_headers"]))
    ctx = dict(org=org, **enr)
    ctx["cost_outcome"] = report
    return ctx


def setup_med_rec_pending(api) -> dict:
    """Enrollment + ACTIVE plan + one COMPLETED home visit + a MedReconciliation in
    PENDING_REVIEW (drafted then submitted)."""
    ctx = setup_enrollment_with_active_plan(api)
    org, enr_id, cp_id = ctx["org"], ctx["enrollment_id"], ctx["care_plan_id"]
    hv = add_completed_home_visit(api, org, enr_id, cp_id,
                                  "2026-03-06T10:00:00Z", "2026-03-06T11:00:00Z",
                                  vitals=f.vitals_payload(150, 95, 90))
    mr = _d(api.create_med_reconciliation(
        f.create_med_reconciliation_payload(enr_id, hv["id"], ["lisinopril", "metformin"],
                                            discrepancy_count=2),
        org["para_headers"]))
    _d(api.submit_med_reconciliation(mr["id"], org["para_headers"]))
    ctx["home_visit"] = hv
    ctx["med_reconciliation"] = mr
    ctx["med_reconciliation_id"] = mr["id"]
    return ctx


def setup_med_rec_drafted(api) -> dict:
    """Enrollment + ACTIVE plan + one COMPLETED home visit + a MedReconciliation still
    DRAFTED (never submitted)."""
    ctx = setup_enrollment_with_active_plan(api)
    org, enr_id, cp_id = ctx["org"], ctx["enrollment_id"], ctx["care_plan_id"]
    hv = add_completed_home_visit(api, org, enr_id, cp_id,
                                  "2026-03-23T10:00:00Z", "2026-03-23T11:00:00Z")
    mr = _d(api.create_med_reconciliation(
        f.create_med_reconciliation_payload(enr_id, hv["id"], ["aspirin"]),
        org["para_headers"]))
    ctx["home_visit"] = hv
    ctx["med_reconciliation"] = mr
    ctx["med_reconciliation_id"] = mr["id"]
    return ctx


def refetch_program(api, org) -> dict:
    return _d(api.get_program(org["program_id"], org["admin_headers"]))


def refetch_enrollment(api, org, enrollment_id) -> dict:
    return _d(api.get_enrollment(enrollment_id, org["coord_headers"]))


def refetch_care_plan(api, org, care_plan_id) -> dict:
    return _d(api.get_care_plan(care_plan_id, org["clin_headers"]))


def refetch_home_visit(api, org, home_visit_id) -> dict:
    return _d(api.get_home_visit(home_visit_id, org["coord_headers"]))


def refetch_claim(api, org, claim_id) -> dict:
    return _d(api.get_billing_claim(claim_id, org["biller_headers"]))
