"""Composite setup helpers for multi-step test prerequisites.

Most testable claims require the system to be in a state that takes 5-15 API
calls to reach (e.g. a fulfilled CPAP device whose modem reports a compliance
window). These helpers encapsulate those preambles so tests focus on assertions.

All helpers use get_success_data() (lenient 2xx validator) so a setup failure
surfaces as a clear "Setup failed" error rather than a confusing assertion.
Each individual pytest test runs against a freshly restarted, empty server, so
every helper builds its preconditions from scratch using only PRD endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_patient_payload,
    create_referral_payload,
    approve_auth_payload,
    create_bed_payload,
    create_study_order_payload,
    schedule_study_payload,
    score_study_payload,
    interpret_payload,
    create_dme_order_payload,
    create_compliance_record_payload,
    create_follow_up_payload,
)
from .test_users import TEST_USERS

COORD = TEST_USERS["scheduling_coordinator_headers"]
TECH = TEST_USERS["sleep_technologist_headers"]
PHYS = TEST_USERS["physician_headers"]
DME = TEST_USERS["dme_coordinator_headers"]


# ─── Tier 0: Single-entity creators ───────────────────────────────────────

def create_patient(**overrides):
    """Create one patient. Returns the patient dict."""
    res = api_client.create_patient(create_patient_payload(**overrides), COORD)
    return get_success_data(res)


def create_bed(**overrides):
    """Create one sleep bed. Returns the bed dict."""
    res = api_client.create_bed(create_bed_payload(**overrides), COORD)
    return get_success_data(res)


# ─── Tier 1: Referral state progression ───────────────────────────────────

def create_submitted_referral(modality="HSAT", prior_auth_required=False,
                              patient_overrides=None, **referral_overrides):
    """Create a patient and a SUBMITTED referral under it.
    Returns (patient, referral)."""
    patient = create_patient(**(patient_overrides or {}))
    res = api_client.create_referral(
        create_referral_payload(
            patient["id"],
            requested_modality=modality,
            prior_auth_required=prior_auth_required,
            **referral_overrides,
        ),
        COORD,
    )
    return patient, get_success_data(res)


def create_authorized_referral(modality="HSAT", patient_overrides=None,
                               prior_auth_expires_on="2026-12-31",
                               prior_auth_number="PA-FIX", **referral_overrides):
    """Create a patient and a referral driven to AUTHORIZED via the no-auth fast
    path. Returns (patient, referral) where referral is the AUTHORIZED snapshot."""
    patient, referral = create_submitted_referral(
        modality=modality,
        prior_auth_required=False,
        patient_overrides=patient_overrides,
        **referral_overrides,
    )
    res = api_client.approve_auth(
        referral["id"],
        approve_auth_payload(
            prior_auth_number=prior_auth_number,
            prior_auth_expires_on=prior_auth_expires_on,
        ),
        COORD,
    )
    return patient, get_success_data(res)


def create_pending_auth_referral(modality="HSAT", patient_overrides=None,
                                 **referral_overrides):
    """Create a referral requiring prior auth and move it to PENDING_AUTH.
    Returns (patient, referral) where referral is the PENDING_AUTH snapshot."""
    patient, referral = create_submitted_referral(
        modality=modality,
        prior_auth_required=True,
        patient_overrides=patient_overrides,
        **referral_overrides,
    )
    res = api_client.request_auth(referral["id"], COORD)
    return patient, get_success_data(res)


# ─── Tier 2: StudyOrder lifecycle ─────────────────────────────────────────

def create_ordered_study(modality="HSAT", patient_overrides=None,
                         prior_auth_expires_on="2026-12-31", **referral_overrides):
    """Authorized referral + one ORDERED study of the given modality.
    Returns (patient, referral, study)."""
    patient, referral = create_authorized_referral(
        modality=("HSAT" if modality == "HSAT" else "IN_LAB_PSG"),
        patient_overrides=patient_overrides,
        prior_auth_expires_on=prior_auth_expires_on,
        **referral_overrides,
    )
    res = api_client.create_study_order(
        create_study_order_payload(
            referral["id"], referral["version"], modality=modality
        ),
        COORD,
    )
    return patient, referral, get_success_data(res)


def create_scheduled_study(modality="HSAT", bed=None,
                           night_start_utc="2026-07-01T22:00:00Z",
                           night_end_utc="2026-07-02T06:00:00Z",
                           patient_overrides=None,
                           prior_auth_expires_on="2026-12-31"):
    """Authorized referral + a study SCHEDULED for the given night.
    For in-lab modalities a bed is created (or supplied) and booked.
    Returns (patient, referral, study, bed_or_none)."""
    is_in_lab = modality in ("IN_LAB_PSG", "IN_LAB_TITRATION")
    if is_in_lab and bed is None:
        bed = create_bed()
    patient, referral, study = create_ordered_study(
        modality=modality,
        patient_overrides=patient_overrides,
        prior_auth_expires_on=prior_auth_expires_on,
    )
    sched_kwargs = dict(night_start_utc=night_start_utc, night_end_utc=night_end_utc)
    if is_in_lab:
        sched_kwargs["bed_id"] = bed["id"]
    res = api_client.schedule_study(
        study["id"], schedule_study_payload(**sched_kwargs), COORD
    )
    return patient, referral, get_success_data(res), bed


def create_in_progress_study(modality="HSAT", patient_overrides=None):
    """A study driven to IN_PROGRESS (scheduled then started).
    Returns (patient, referral, study, bed_or_none)."""
    patient, referral, study, bed = create_scheduled_study(
        modality=modality, patient_overrides=patient_overrides
    )
    res = api_client.start_study(study["id"], TECH)
    return patient, referral, get_success_data(res), bed


def create_scored_study(modality="HSAT", total_recording_minutes=480,
                        respiratory_event_count=120, patient_overrides=None,
                        **score_overrides):
    """A study driven to SCORED with a DRAFT scoring report.
    Returns (patient, referral, study, scoring_report, bed_or_none)."""
    patient, referral, study, bed = create_in_progress_study(
        modality=modality, patient_overrides=patient_overrides
    )
    score_res = api_client.score_study(
        study["id"],
        score_study_payload(
            total_recording_minutes,
            respiratory_event_count,
            study["version"],
            **score_overrides,
        ),
        TECH,
    )
    scored = get_success_data(score_res)
    reports, _ = _list_scoring_reports(study["id"])
    report = reports[0]
    return patient, referral, scored, report, bed


def create_interpreted_study(modality="HSAT", physician_recommends_cpap=True,
                             total_recording_minutes=480,
                             respiratory_event_count=240,
                             interpretation_text="Severe OSA",
                             patient_overrides=None):
    """A study driven to INTERPRETED (report FINALIZED, referral COMPLETED).
    Returns (patient, referral, study, scoring_report, bed_or_none)."""
    patient, referral, study, report, bed = create_scored_study(
        modality=modality,
        total_recording_minutes=total_recording_minutes,
        respiratory_event_count=respiratory_event_count,
        patient_overrides=patient_overrides,
    )
    res = api_client.interpret_scoring_report(
        report["id"],
        interpret_payload(
            interpretation_text=interpretation_text,
            physician_recommends_cpap=physician_recommends_cpap,
        ),
        PHYS,
    )
    finalized_report = get_success_data(res)
    return patient, referral, study, finalized_report, bed


# ─── Tier 3: DMEOrder lifecycle ───────────────────────────────────────────

def create_draft_dme(modality="HSAT", physician_recommends_cpap=True,
                     device_type="CPAP", prescribed_pressure_cmh2o=9.0):
    """Interpreted study + a DRAFT DMEOrder linked to it.
    Returns (study, scoring_report, dme_order)."""
    _, _, study, report, _ = create_interpreted_study(
        modality=modality, physician_recommends_cpap=physician_recommends_cpap
    )
    res = api_client.create_dme_order(
        create_dme_order_payload(
            study["id"],
            device_type=device_type,
            prescribed_pressure_cmh2o=prescribed_pressure_cmh2o,
        ),
        DME,
    )
    return study, report, get_success_data(res)


def create_submitted_dme(modality="HSAT", physician_recommends_cpap=True):
    """Interpreted study + a SUBMITTED DMEOrder. Returns (study, report, dme_order)."""
    study, report, dme = create_draft_dme(
        modality=modality, physician_recommends_cpap=physician_recommends_cpap
    )
    res = api_client.submit_dme_order(dme["id"], DME)
    return study, report, get_success_data(res)


def create_fulfilled_dme(modality="HSAT"):
    """Interpreted CPAP-recommended study + a FULFILLED DMEOrder.
    Returns (study, report, dme_order)."""
    study, report, dme = create_submitted_dme(modality=modality)
    res = api_client.fulfill_dme_order(dme["id"], DME)
    return study, report, get_success_data(res)


def create_fulfilled_dme_with_window(window_start_utc, window_end_utc,
                                     nights_used_4h_plus, total_usage_minutes):
    """Fulfilled DMEOrder plus one already-uploaded compliance window.
    Returns (study, dme_order, compliance_record)."""
    study, _, dme = create_fulfilled_dme()
    res = api_client.create_compliance_record(
        create_compliance_record_payload(
            dme["id"], window_start_utc, window_end_utc,
            nights_used_4h_plus, total_usage_minutes,
        ),
        DME,
    )
    return study, dme, get_success_data(res)


# ─── Tier 4: FollowUp lifecycle ───────────────────────────────────────────

def create_scheduled_follow_up(baseline_epworth_score=14,
                               scheduled_for_utc="2026-09-01T15:00:00Z"):
    """Interpreted study (patient with the given baseline) + a SCHEDULED follow-up.
    Returns (patient, study, follow_up)."""
    patient, _, study, _, _ = create_interpreted_study(
        patient_overrides={"baseline_epworth_score": baseline_epworth_score}
    )
    res = api_client.create_follow_up(
        create_follow_up_payload(study["id"], scheduled_for_utc=scheduled_for_utc),
        COORD,
    )
    return patient, study, get_success_data(res)


# ─── Helpers ──────────────────────────────────────────────────────────────

def _list_scoring_reports(study_order_id):
    """Return (list_of_reports, meta) for a study order's scoring reports."""
    res = api_client.list_scoring_reports_for_study(study_order_id, PHYS)
    data = get_success_data(res)
    return data, res


def first_scoring_report(study_order_id):
    """Return the first (DRAFT) scoring report for a study order."""
    reports, _ = _list_scoring_reports(study_order_id)
    return reports[0]
