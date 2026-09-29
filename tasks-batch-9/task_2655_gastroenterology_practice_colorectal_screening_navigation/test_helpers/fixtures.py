"""Composite setup helpers.

Every test starts against an empty database, so all preconditions are built from
scratch through the endpoints the PRD declares. These helpers encapsulate the
multi-step chains the suite needs repeatedly: standing up reference data, laying
out a room block, staffing it with anesthesia, navigating a patient through
bowel preparation, performing the exam, and routing pathology.

Ownership-gated calls thread the real entity id into the header builders for the
two entity-backed roles (`Endoscopist` carries the acting `Clinician.id`,
`Patient` carries the acting `Patient.id`).
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULTS,
    abort_procedure_payload,
    amend_pathology_report_payload,
    attest_quality_period_payload,
    cancel_booking_payload,
    close_episode_payload,
    complete_procedure_payload,
    create_anesthesia_clinician_payload,
    create_anesthesia_coverage_payload,
    create_clinician_payload,
    create_endoscopy_session_payload,
    create_insurance_plan_payload,
    create_noninvasive_test_payload,
    create_pathology_report_payload,
    create_patient_payload,
    create_procedure_booking_payload,
    create_quality_period_payload,
    create_referral_payload,
    create_screening_episode_payload,
    create_surveillance_recommendation_payload,
    dispute_claim_payload,
    noninvasive_test_result_payload,
    outreach_payload,
    prep_attestation_payload,
    session_status_action_payload,
    specimen,
    triage_action_payload,
)
from .test_users import (
    BILLING_SPECIALIST,
    PATHOLOGIST,
    PATIENT_NAVIGATOR,
    PRACTICE_ADMIN,
    QUALITY_OFFICER,
    REFERRAL_COORDINATOR,
    make_endoscopist_headers,
    make_patient_headers,
)

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


# ─── Single-step primitives ───────────────────────────

def move_clock(to_iso8601: str) -> None:
    """Move the server's logical clock, which is the sole source of 'now'."""
    get_success_data(api_client.set_clock(to_iso8601, PRACTICE_ADMIN))


def register_plan(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_insurance_plan(
            create_insurance_plan_payload(**overrides), PRACTICE_ADMIN
        )
    )


def register_endoscopist(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_clinician(create_clinician_payload(**overrides), PRACTICE_ADMIN)
    )


def register_anesthesia_clinician(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_clinician(
            create_anesthesia_clinician_payload(**overrides), PRACTICE_ADMIN
        )
    )


def register_patient(insurance_plan_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_patient(
            create_patient_payload(insurance_plan_id, **overrides), PRACTICE_ADMIN
        )
    )


def open_episode(patient_id: str, indication: str = "SCREENING_AVERAGE_RISK",
                 **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_screening_episode(
            create_screening_episode_payload(patient_id, indication, **overrides),
            REFERRAL_COORDINATOR,
        )
    )


def create_block(lead_endoscopist_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_endoscopy_session(
            create_endoscopy_session_payload(lead_endoscopist_id, **overrides),
            PRACTICE_ADMIN,
        )
    )


def apply_block_action(session_id: str, action: str,
                       reason: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.session_status_action(
            session_id, session_status_action_payload(action, reason), PRACTICE_ADMIN
        )
    )


def staff_block(session_id: str, anesthesia_clinician_id: str,
                coverage_start_utc: str = DEFAULTS["WINDOW_START_UTC"],
                coverage_end_utc: str = DEFAULTS["WINDOW_END_UTC"]) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_anesthesia_coverage(
            session_id,
            create_anesthesia_coverage_payload(
                anesthesia_clinician_id, coverage_start_utc, coverage_end_utc
            ),
            PRACTICE_ADMIN,
        )
    )


def read_block(session_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_endoscopy_session(session_id, PRACTICE_ADMIN))


def read_episode(episode_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_screening_episode(episode_id, PRACTICE_ADMIN))


def read_patient(patient_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_patient(patient_id, PRACTICE_ADMIN))


def read_booking(booking_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_procedure_booking(booking_id, PRACTICE_ADMIN))


def read_report(report_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_pathology_report(report_id, PATHOLOGIST))


def book_slot(session_id: str, episode_id: str, performing_endoscopist_id: str,
              expected_session_version: Optional[int] = None,
              slot_start_utc: str = DEFAULTS["SLOT_START_UTC"],
              duration_minutes: int = 45, **overrides) -> Dict[str, Any]:
    """Book a slot, reading the block's current `version` when none is pinned."""
    if expected_session_version is None:
        expected_session_version = read_block(session_id)["version"]
    return get_success_data(
        api_client.create_procedure_booking(
            session_id,
            create_procedure_booking_payload(
                episode_id, performing_endoscopist_id, expected_session_version,
                slot_start_utc, duration_minutes, **overrides
            ),
            REFERRAL_COORDINATOR,
        )
    )


def record_outreach(episode_id: str, channel: str = "PHONE",
                    acknowledged: bool = True) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_outreach(
            episode_id, outreach_payload(channel, acknowledged), PATIENT_NAVIGATOR
        )
    )


def attest_prep(episode_id: str, patient_id: str,
                regimen_completed: bool = True) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_prep_attestation(
            episode_id,
            prep_attestation_payload(regimen_completed),
            make_patient_headers(patient_id),
        )
    )


def confirm_prep(episode_id: str, patient_id: str) -> Dict[str, Any]:
    """Drive navigation to `PREP_CONFIRMED`: one acknowledged PHONE touchpoint
    scores 3.00 and the completed attestation adds the 2.50 bonus for 5.50."""
    record_outreach(episode_id, "PHONE", True)
    return attest_prep(episode_id, patient_id, True)


def check_in(booking_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.check_in_booking(booking_id, PATIENT_NAVIGATOR))


def start_exam(booking_id: str, endoscopist_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.start_procedure(booking_id, make_endoscopist_headers(endoscopist_id))
    )


def complete_exam(booking_id: str, endoscopist_id: str, prep_quality_bbps: int = 8,
                  polyps_removed_count: int = 1, largest_polyp_mm: int = 7,
                  specimen_count: int = 1) -> Dict[str, Any]:
    return get_success_data(
        api_client.complete_procedure(
            booking_id,
            complete_procedure_payload(
                prep_quality_bbps, polyps_removed_count, largest_polyp_mm, specimen_count
            ),
            make_endoscopist_headers(endoscopist_id),
        )
    )


def abort_exam(booking_id: str, endoscopist_id: str, prep_quality_bbps: int = 3,
               cancellation_reason: str = "INADEQUATE_PREP") -> Dict[str, Any]:
    return get_success_data(
        api_client.abort_procedure(
            booking_id,
            abort_procedure_payload(prep_quality_bbps, cancellation_reason),
            make_endoscopist_headers(endoscopist_id),
        )
    )


def cancel_slot(booking_id: str,
                cancellation_reason: str = "PATIENT_RESCHEDULED") -> Dict[str, Any]:
    return get_success_data(
        api_client.cancel_booking(
            booking_id, cancel_booking_payload(cancellation_reason), REFERRAL_COORDINATOR
        )
    )


def receive_report(booking_id: str, specimens: List[Dict[str, Any]],
                   accession_number: str = DEFAULTS["ACCESSION_NUMBER"],
                   **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_pathology_report(
            booking_id,
            create_pathology_report_payload(specimens, accession_number, **overrides),
            PATHOLOGIST,
        )
    )


def finalize_report(report_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.finalize_pathology_report(report_id, PATHOLOGIST))


def amend_report(report_id: str, specimens: List[Dict[str, Any]],
                 amendment_reason: str = "SECOND_OPINION", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.amend_pathology_report(
            report_id,
            amend_pathology_report_payload(specimens, amendment_reason, **overrides),
            PATHOLOGIST,
        )
    )


def claim_for_booking(booking_id: str) -> Dict[str, Any]:
    """A claim is created when a booking is created; it is reachable only by listing."""
    body = api_client.list_billing_claims(BILLING_SPECIALIST, {"booking_id": booking_id})
    rows = body.json()["data"]
    assert len(rows) == 1, f"Expected exactly one claim for booking {booking_id}, got {len(rows)}"
    return rows[0]


def read_claim(claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_billing_claim(claim_id, BILLING_SPECIALIST))


def finalize_claim(claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.finalize_billing_claim(claim_id, BILLING_SPECIALIST))


def dispute_claim(claim_id: str, dispute_reason: str = "PATIENT_APPEAL") -> Dict[str, Any]:
    return get_success_data(
        api_client.dispute_billing_claim(
            claim_id, dispute_claim_payload(dispute_reason), BILLING_SPECIALIST
        )
    )


def reprice_claim(claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.reprice_billing_claim(claim_id, BILLING_SPECIALIST))


def open_quality_period(endoscopist_id: str, period_start_date: str,
                        period_end_date: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_quality_period(
            create_quality_period_payload(
                endoscopist_id, period_start_date, period_end_date, **overrides
            ),
            QUALITY_OFFICER,
        )
    )


def lock_quality_period(period_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.lock_quality_period(period_id, QUALITY_OFFICER))


def attest_quality_period(period_id: str, remediation_plan: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.attest_quality_period(
            period_id, attest_quality_period_payload(remediation_plan), QUALITY_OFFICER
        )
    )


def order_noninvasive_test(episode_id: str, test_type: str = "FIT",
                           collected_date: str = "2026-09-01") -> Dict[str, Any]:
    return get_success_data(
        api_client.create_noninvasive_test(
            episode_id,
            create_noninvasive_test_payload(test_type, collected_date),
            REFERRAL_COORDINATOR,
        )
    )


def post_test_result(test_id: str, result: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.post_noninvasive_test_result(
            test_id, noninvasive_test_result_payload(result), PATHOLOGIST
        )
    )


def submit_referral(patient_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_referral(
            create_referral_payload(patient_id, **overrides), REFERRAL_COORDINATOR
        )
    )


def triage(referral_id: str, action: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.referral_triage_action(
            referral_id, triage_action_payload(action, **overrides), REFERRAL_COORDINATOR
        )
    )


def accept_referral_for_open_access(patient_id: str, **referral_overrides) -> Dict[str, Any]:
    """Submit a referral and drive it to `ACCEPTED_OPEN_ACCESS`."""
    referral = submit_referral(patient_id, **referral_overrides)
    triage(referral["id"], "BEGIN_TRIAGE")
    return triage(referral["id"], "ACCEPT_OPEN_ACCESS")


def accept_referral_for_office_visit(patient_id: str, note: Optional[str] = None,
                                     **referral_overrides) -> Dict[str, Any]:
    """Submit a referral and drive it to `ACCEPTED_OFFICE_VISIT`, the clearance an
    ASA 4 or 5 patient needs before a slot may be booked."""
    referral = submit_referral(patient_id, **referral_overrides)
    triage(referral["id"], "BEGIN_TRIAGE")
    extras = {"note": note} if note is not None else {}
    return triage(referral["id"], "ACCEPT_OFFICE_VISIT", **extras)


def record_recommendation(episode_id: str, acting_endoscopist_id: str,
                          expected_episode_version: Optional[int] = None,
                          **overrides) -> Dict[str, Any]:
    if expected_episode_version is None:
        expected_episode_version = read_episode(episode_id)["version"]
    return get_success_data(
        api_client.create_surveillance_recommendation(
            episode_id,
            create_surveillance_recommendation_payload(
                expected_episode_version, **overrides
            ),
            make_endoscopist_headers(acting_endoscopist_id),
        )
    )


def close_episode(episode_id: str, reason: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_screening_episode(
            episode_id, close_episode_payload(reason), PATIENT_NAVIGATOR
        )
    )


# ─── Collection readers ───────────────────────────────
# Every collection endpoint returns the standard paginated envelope, so these
# return the `(rows, meta)` pair the framework validator produces.

def _paginated(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)


def list_patients(params: Optional[Dict[str, Any]] = None):
    return _paginated(api_client.list_patients(PRACTICE_ADMIN, params))


def list_blocks(params: Optional[Dict[str, Any]] = None):
    return _paginated(api_client.list_endoscopy_sessions(PRACTICE_ADMIN, params))


def list_coverage(params: Optional[Dict[str, Any]] = None):
    return _paginated(api_client.list_anesthesia_coverage(PRACTICE_ADMIN, params))


def list_referrals(params: Optional[Dict[str, Any]] = None):
    return _paginated(api_client.list_referrals(REFERRAL_COORDINATOR, params))


def list_episodes(params: Optional[Dict[str, Any]] = None):
    return _paginated(api_client.list_screening_episodes(PRACTICE_ADMIN, params))


def list_noninvasive_tests(params: Optional[Dict[str, Any]] = None):
    return _paginated(api_client.list_noninvasive_tests(PRACTICE_ADMIN, params))


def list_bookings(params: Optional[Dict[str, Any]] = None):
    return _paginated(api_client.list_procedure_bookings(PRACTICE_ADMIN, params))


def list_reports(params: Optional[Dict[str, Any]] = None):
    return _paginated(api_client.list_pathology_reports(PATHOLOGIST, params))


def list_recommendations(params: Optional[Dict[str, Any]] = None):
    return _paginated(api_client.list_surveillance_recommendations(PRACTICE_ADMIN, params))


def list_claims(params: Optional[Dict[str, Any]] = None):
    return _paginated(api_client.list_billing_claims(BILLING_SPECIALIST, params))


def list_quality_periods(params: Optional[Dict[str, Any]] = None):
    return _paginated(api_client.list_quality_periods(QUALITY_OFFICER, params))


def active_recommendation(episode_id: str) -> Dict[str, Any]:
    """The single `ACTIVE` recommendation on an episode: only one recommendation per
    episode may be `ACTIVE` at a time."""
    rows, _ = list_recommendations({"episode_id": episode_id, "status": "ACTIVE"})
    assert len(rows) == 1, f"Expected one ACTIVE recommendation, got {len(rows)}"
    return rows[0]


# ─── Remaining single-resource readers ────────────────

def read_plan(plan_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_insurance_plan(plan_id, PRACTICE_ADMIN))


def read_clinician(clinician_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_clinician(clinician_id, PRACTICE_ADMIN))


def read_coverage(coverage_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_anesthesia_coverage(coverage_id, PRACTICE_ADMIN))


def read_referral(referral_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_referral(referral_id, REFERRAL_COORDINATOR))


def read_noninvasive_test(test_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_noninvasive_test(test_id, PRACTICE_ADMIN))


def read_recommendation(recommendation_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_surveillance_recommendation(recommendation_id, PRACTICE_ADMIN)
    )


def read_quality_period(period_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_quality_period(period_id, QUALITY_OFFICER))


def release_coverage(coverage_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.release_anesthesia_coverage(coverage_id, PRACTICE_ADMIN)
    )
