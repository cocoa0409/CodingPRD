"""Surveillance exams: recording, finalization, recheck window. Translates difficulty queue
(resource_temporal_overlap / surveillance_recheck_buffer_blocks_early_reexam) plus corner
surveillance lifecycle instances.
"""
from test_helpers import (
    validate_error, get_success_data,
    TEST_USERS, ApiErrorId, panel,
    setup_employer_with_active_protocol, create_worker, setup_surveillance_exam,
    complete_surveillance_encounter_for_employer, set_clock,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
CLIN = TEST_USERS["clinician_headers"]


# ─── Recheck window (resource_temporal_overlap) ───────

def test_surveillance_recheck_buffer_blocks_early_reexam(api):
    """PRD §3.3: "For a `SURVEILLANCE` encounter, the system enforces a recheck window: if a prior
    `FINALIZED` surveillance exam of the same `exam_kind` exists for the same worker, and the
    number of days between that prior exam and the employer's `current_date` has not yet reached
    the panel's `recheck_interval_days`, the new encounter is rejected with
    `ERR_SURVEILLANCE_TOO_EARLY` as scheduled too early."

    Design: Difficulty/resource_temporal_overlap/surveillance_recheck_buffer_blocks_early_reexam
    """
    emp, _ = setup_employer_with_active_protocol(
        panels=[panel("AUDIOMETRIC", "MACHINIST", 5000, 365)],
        current_date="2026-06-01", mro_user_id="mro-1")
    wkr = create_worker(emp["id"], job_category="MACHINIST")
    # First audiometric exam FINALIZED + encounter completed on 2026-06-01.
    complete_surveillance_encounter_for_employer(
        emp["id"], wkr["id"], panel_code="AUDIOMETRIC",
        exam_overrides={"baseline_threshold_db": 20, "current_threshold_db": 22})
    # Advance only 90 days (< 365); a new audiometric encounter is too early.
    set_clock(emp["id"], "2026-09-01")
    resp = api.create_encounter(
        {"employer_id": emp["id"], "worker_id": wkr["id"],
         "encounter_type": "SURVEILLANCE", "panel_code": "AUDIOMETRIC"}, CLIN)
    validate_error(resp, ApiErrorId.ERR_SURVEILLANCE_TOO_EARLY.value)


def test_surveillance_recheck_buffer_blocks_at_partial_interval(api):
    """PRD §3.3: "if a prior `FINALIZED` surveillance exam of the same `exam_kind` exists for the
    same worker, and the number of days between that prior exam and the employer's `current_date`
    has not yet reached the panel's `recheck_interval_days`, the new encounter is rejected with
    `ERR_SURVEILLANCE_TOO_EARLY` as scheduled too early."

    Design: Difficulty/resource_temporal_overlap/surveillance_recheck_buffer_blocks_early_reexam
    """
    # Second translation: no clock advance at all (same current_date 2026-06-01, 0 days elapsed).
    emp, _ = setup_employer_with_active_protocol(
        panels=[panel("AUDIOMETRIC", "MACHINIST", 5000, 365)],
        current_date="2026-06-01", mro_user_id="mro-1")
    wkr = create_worker(emp["id"], job_category="MACHINIST")
    complete_surveillance_encounter_for_employer(
        emp["id"], wkr["id"], panel_code="AUDIOMETRIC",
        exam_overrides={"baseline_threshold_db": 20, "current_threshold_db": 21})
    resp = api.create_encounter(
        {"employer_id": emp["id"], "worker_id": wkr["id"],
         "encounter_type": "SURVEILLANCE", "panel_code": "AUDIOMETRIC"}, CLIN)
    validate_error(resp, ApiErrorId.ERR_SURVEILLANCE_TOO_EARLY.value)


# ─── Surveillance lifecycle (corner) ──────────────────

def test_surveillance_record_missing_measurements_rejected(api):
    """PRD §3.8: "Recording requires the exam to be `SCHEDULED` (otherwise
    `ERR_EXAM_NOT_SCHEDULED`) and requires the measurements for the exam kind to be present: an
    `AUDIOMETRIC` exam needs both `baseline_threshold_db` and `current_threshold_db` ... absent
    measurements yield `ERR_EXAM_MISSING_MEASUREMENTS`."

    Design: Corner/state_machines/surveillance_record_missing_measurements_rejected
    """
    emp, wkr, enc, ex = setup_surveillance_exam(
        panel_code="AUDIOMETRIC", job_category="MACHINIST", exam_overrides={})
    resp = api.record_surveillance_exam(ex["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_EXAM_MISSING_MEASUREMENTS.value)


def test_surveillance_finalize_when_not_recorded_rejected(api):
    """PRD §3.8: "A recorded exam is finalized by a `Clinician`, moving it from `RECORDED` to
    `FINALIZED` and requiring the exam to be `RECORDED` (otherwise `ERR_EXAM_NOT_RECORDED`)."

    Design: Corner/state_machines/surveillance_finalize_when_not_recorded_rejected
    """
    emp, wkr, enc, ex = setup_surveillance_exam(
        panel_code="AUDIOMETRIC", job_category="MACHINIST",
        exam_overrides={"baseline_threshold_db": 20, "current_threshold_db": 22})
    resp = api.finalize_surveillance_exam(ex["id"], CLIN)
    validate_error(resp, ApiErrorId.ERR_EXAM_NOT_RECORDED.value)


def test_surveillance_respirator_fit_pass_outcome_recorded(api):
    """PRD §3.12: "a `HALF_MASK` requires a fit factor of at least 100 ... if the measured
    `fit_factor` meets or exceeds the required minimum the outcome is `PASS`".
    PRD §3.8: "The exam's `exam_kind` is derived from the encounter's `panel_code` — `AUDIOMETRIC`
    or `RESPIRATOR_FIT`."

    Design: Corner/state_machines/surveillance_respirator_fit_pass_outcome_recorded
    """
    emp, wkr, enc, ex = setup_surveillance_exam(
        panel_code="RESPIRATOR_FIT", job_category="WELDER", price_cents=4000,
        exam_overrides={"fit_factor": 120, "respirator_class": "HALF_MASK"})
    out = get_success_data(api.record_surveillance_exam(ex["id"], CLIN))
    assert out["outcome"] == "PASS"
    assert out["exam_kind"] == "RESPIRATOR_FIT"
