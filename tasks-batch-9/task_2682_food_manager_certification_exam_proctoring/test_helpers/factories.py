"""Payload factories - one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_seq = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix so unique fields never collide inside one test."""
    return str(next(_seq))


def create_jurisdiction_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["JURISDICTION_NAME"],
        "jurisdiction_code": TEST_DEFAULTS["JURISDICTION_CODE"],
        "accepted_accreditation_bodies": ["ANAB_CFP"],
        "accepted_languages": ["EN", "ES"],
        "accepts_remote_proctoring": True,
        "min_passing_score_override": None,
        "requires_local_registration": True,
        "posting_deadline_days": 30,
        "recert_cycle_months": 60,
        "exam_fee_surcharge_pct": TEST_DEFAULTS["SURCHARGE_PCT"],
    }
    payload.update(overrides)
    return payload


def create_training_provider_payload(jurisdiction_id: str, **overrides) -> dict:
    payload = {
        "legal_name": TEST_DEFAULTS["PROVIDER_LEGAL_NAME"],
        "jurisdiction_id": jurisdiction_id,
        "contact_email": TEST_DEFAULTS["PROVIDER_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_credit_adjustment_payload(**overrides) -> dict:
    payload = {
        "amount_cents": TEST_DEFAULTS["PREPAY_CENTS"],
        "memo": "Initial prepayment",
    }
    payload.update(overrides)
    return payload


def create_exam_form_payload(**overrides) -> dict:
    payload = {
        "form_code": TEST_DEFAULTS["FORM_CODE"],
        "version_label": TEST_DEFAULTS["VERSION_LABEL"],
        "language": "EN",
        "accreditation_body": "ANAB_CFP",
        "scored_item_count": TEST_DEFAULTS["SCORED_ITEM_COUNT"],
        "pretest_item_count": TEST_DEFAULTS["PRETEST_ITEM_COUNT"],
        "national_cut_score": TEST_DEFAULTS["NATIONAL_CUT_SCORE"],
        "base_minutes": TEST_DEFAULTS["BASE_MINUTES"],
        "translated_extra_minutes": 0,
    }
    payload.update(overrides)
    return payload


def create_testing_site_payload(jurisdiction_id: str, **overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["SITE_NAME"],
        "jurisdiction_id": jurisdiction_id,
        "seat_count": TEST_DEFAULTS["SEAT_COUNT"],
        "address_line": TEST_DEFAULTS["SITE_ADDRESS"],
        "languages_supported": ["EN", "ES"],
    }
    payload.update(overrides)
    return payload


def create_candidate_payload(training_provider_id: str, jurisdiction_id: str, **overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "full_name": f"Candidate {suffix}",
        "email": f"candidate{suffix}@example.com",
        "preferred_language": "EN",
        "training_provider_id": training_provider_id,
        "jurisdiction_id": jurisdiction_id,
    }
    payload.update(overrides)
    return payload


def create_proctor_payload(training_provider_id: str, **overrides) -> dict:
    suffix = unique_suffix()
    payload = {
        "full_name": f"Proctor {suffix}",
        "email": f"proctor{suffix}@example.com",
        "training_provider_id": training_provider_id,
        "roles_held": ["PROCTOR", "INSTRUCTOR"],
        "languages_certified": ["EN", "ES"],
        "remote_certified": True,
    }
    payload.update(overrides)
    return payload


def create_registration_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision, "decision_note": "Credentials verified"}
    payload.update(overrides)
    return payload


def create_access_code_batch_payload(
    training_provider_id: str,
    exam_form_id: str,
    line_items=None,
    expires_at: str = "2027-01-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "training_provider_id": training_provider_id,
        "exam_form_id": exam_form_id,
        "expires_at": expires_at,
        "line_items": line_items or [{"bundle_type": "EXAM_ONLY", "quantity": 1}],
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(candidate_id: str, expected_batch_version: int,
                              bundle_type: str = "EXAM_ONLY", **overrides) -> dict:
    payload = {
        "candidate_id": candidate_id,
        "bundle_type": bundle_type,
        "expected_batch_version": expected_batch_version,
    }
    payload.update(overrides)
    return payload


def create_void_payload(expected_batch_version: int, reason: str = "Overbought inventory",
                        **overrides) -> dict:
    payload = {"reason": reason, "expected_batch_version": expected_batch_version}
    payload.update(overrides)
    return payload


def create_course_completion_payload(course_instructor_proctor_id: str, **overrides) -> dict:
    payload = {"course_instructor_proctor_id": course_instructor_proctor_id}
    payload.update(overrides)
    return payload


def create_accommodation_request_payload(candidate_id: str, **overrides) -> dict:
    payload = {
        "candidate_id": candidate_id,
        "accommodation_type": "EXTRA_TIME",
        "requested_multiplier": 1.5,
        "documentation_ref": "DOC-ACC-1",
        "requested_language": None,
    }
    payload.update(overrides)
    return payload


def create_accommodation_review_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_exam_session_payload(candidate_id: str, exam_form_id: str, access_code_id: str,
                                scheduled_start_at: str, delivery_mode: str = "IN_PERSON",
                                **overrides) -> dict:
    payload = {
        "candidate_id": candidate_id,
        "exam_form_id": exam_form_id,
        "access_code_id": access_code_id,
        "delivery_mode": delivery_mode,
        "scheduled_start_at": scheduled_start_at,
    }
    payload.update(overrides)
    return payload


def create_reschedule_payload(scheduled_start_at: str, expected_session_version: int,
                              **overrides) -> dict:
    payload = {
        "scheduled_start_at": scheduled_start_at,
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return payload


def create_check_in_payload(id_document_type: str = "GOVT_PHOTO_ID",
                            id_document_expires_on: str = "2030-01-01",
                            **overrides) -> dict:
    payload = {
        "id_document_type": id_document_type,
        "id_document_expires_on": id_document_expires_on,
        "proctor_attestation": True,
    }
    payload.update(overrides)
    return payload


def create_submission_payload(scored_correct_count: int, proctor_attestation: bool = True,
                              **overrides) -> dict:
    payload = {
        "scored_correct_count": scored_correct_count,
        "proctor_attestation": proctor_attestation,
        "pretest_correct_count": 0,
    }
    payload.update(overrides)
    return payload


def create_finalization_payload(**overrides) -> dict:
    payload = {"voided_item_count": 0, "voided_correct_count": 0}
    payload.update(overrides)
    return payload


def create_certificate_payload(score_report_id: str, **overrides) -> dict:
    payload = {"score_report_id": score_report_id}
    payload.update(overrides)
    return payload


def create_local_registration_payload(certificate_id: str, **overrides) -> dict:
    payload = {
        "certificate_id": certificate_id,
        "establishment_name": "Barton Springs Diner",
        "establishment_address": "1200 Barton Springs Rd, Austin TX",
    }
    payload.update(overrides)
    return payload


def create_posting_confirmation_payload(**overrides) -> dict:
    payload = {"posting_location": "Front counter, behind the register"}
    payload.update(overrides)
    return payload


def create_verification_payload(decision: str = "VERIFY", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_security_incident_payload(exam_session_id: str, reported_by_proctor_id: str,
                                     severity: str = "MAJOR", **overrides) -> dict:
    payload = {
        "exam_session_id": exam_session_id,
        "reported_by_proctor_id": reported_by_proctor_id,
        "category": "PROHIBITED_MATERIAL",
        "severity": severity,
        "narrative": "Candidate consulted printed notes concealed under the desk.",
    }
    payload.update(overrides)
    return payload


def create_incident_resolution_payload(outcome: str = "SUBSTANTIATE", **overrides) -> dict:
    payload = {"outcome": outcome, "resolution_note": "Reviewed room-scan footage."}
    payload.update(overrides)
    return payload


def create_cancellation_payload(reason: str = "Candidate withdrew", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def create_audit_open_payload(**overrides) -> dict:
    payload = {"audit_reason": "Routine conduct review"}
    payload.update(overrides)
    return payload


def create_audit_close_payload(outcome: str = "PASS", **overrides) -> dict:
    payload = {"outcome": outcome, "audit_note": "Review complete"}
    payload.update(overrides)
    return payload


def create_reinstatement_payload(**overrides) -> dict:
    payload = {"remediation_ref": "REMEDIATION-1"}
    payload.update(overrides)
    return payload
