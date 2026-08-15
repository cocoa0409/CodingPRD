"""Payload factories — one per entity, input fields only (PRD endpoint table)."""

DEFAULT_OCCURRED_AT = "2026-07-15T22:00:00Z"
DEFAULT_HEARING_SLOT = "2026-09-01T10:00:00Z"


def create_party_profile_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Person",
        "university_id": "U-T-1",
        "role_type": "STUDENT",
        "email": "person@example.edu",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(complainant_id, respondent_id, coordinator_id, **overrides) -> dict:
    defaults = {
        "complainant_id": complainant_id,
        "respondent_id": respondent_id,
        "coordinator_id": coordinator_id,
        "categories": ["STALKING"],
        "occurred_at": DEFAULT_OCCURRED_AT,
        "occurred_in_program_activity": True,
        "occurred_in_united_states": True,
        "received_via": "ONLINE_FORM",
    }
    defaults.update(overrides)
    return defaults


def dismiss_case_payload(**overrides) -> dict:
    defaults = {
        "dismissal_reason": "DISCRETIONARY_COMPLAINANT_WITHDRAWN",
        "refer_to_conduct": False,
    }
    defaults.update(overrides)
    return defaults


def supportive_measure_payload(**overrides) -> dict:
    defaults = {
        "measure_type": "COUNSELING",
        "party_side": "COMPLAINANT",
        "description": "Supportive measure",
        "effective_from": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def no_contact_directive_payload(expected_case_version, **overrides) -> dict:
    defaults = {
        "party_side": "MUTUAL",
        "restrictions": ["IN_PERSON"],
        "effective_from": "2026-08-01T00:00:00Z",
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def violation_report_payload(**overrides) -> dict:
    defaults = {
        "reported_by_side": "COMPLAINANT",
        "occurred_at": "2026-08-03T15:00:00Z",
        "description": "Alleged directive violation",
    }
    defaults.update(overrides)
    return defaults


def investigator_assignment_payload(investigator_id, **overrides) -> dict:
    defaults = {"investigator_id": investigator_id}
    defaults.update(overrides)
    return defaults


def evidence_item_payload(**overrides) -> dict:
    defaults = {
        "submitted_by_side": "COMPLAINANT",
        "evidence_type": "DOCUMENT",
        "description": "Evidence item",
    }
    defaults.update(overrides)
    return defaults


def evidence_packet_payload(expected_case_version, **overrides) -> dict:
    defaults = {"expected_case_version": expected_case_version}
    defaults.update(overrides)
    return defaults


def attach_report_payload(**overrides) -> dict:
    defaults = {"investigative_report_summary": "Investigative findings narrative"}
    defaults.update(overrides)
    return defaults


def review_response_payload(party_side, **overrides) -> dict:
    defaults = {"party_side": party_side, "response_text": "Reviewed"}
    defaults.update(overrides)
    return defaults


def notice_payload(**overrides) -> dict:
    defaults = {
        "notice_type": "ALLEGATIONS",
        "recipient_side": "BOTH",
        "body": "Notice body",
    }
    defaults.update(overrides)
    return defaults


def advisor_appointment_payload(party_side, advisor_id, **overrides) -> dict:
    defaults = {"party_side": party_side, "advisor_id": advisor_id}
    defaults.update(overrides)
    return defaults


def university_appointment_payload(party_side, **overrides) -> dict:
    defaults = {"party_side": party_side}
    defaults.update(overrides)
    return defaults


def hearing_payload(decision_maker_id, **overrides) -> dict:
    defaults = {
        "decision_maker_id": decision_maker_id,
        "scheduled_at": DEFAULT_HEARING_SLOT,
        "estimated_duration_minutes": 60,
        "modality": "VIRTUAL",
    }
    defaults.update(overrides)
    return defaults


def cross_exam_question_payload(asked_by_advisor_id, target_side, **overrides) -> dict:
    defaults = {
        "asked_by_advisor_id": asked_by_advisor_id,
        "target_side": target_side,
        "question_text": "Cross-examination question",
    }
    defaults.update(overrides)
    return defaults


def determination_payload(expected_case_version, **overrides) -> dict:
    defaults = {
        "responsibility_finding": "RESPONSIBLE",
        "standard_of_evidence": "PREPONDERANCE",
        "rationale": "The evidence supports the finding",
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def issue_payload(sanction_selections, **overrides) -> dict:
    defaults = {"sanction_selections": sanction_selections}
    defaults.update(overrides)
    return defaults


def appeal_payload(filed_by_side, appeal_target, grounds, **overrides) -> dict:
    defaults = {
        "filed_by_side": filed_by_side,
        "appeal_target": appeal_target,
        "grounds": grounds,
        "statement": "Appeal statement on the record",
    }
    defaults.update(overrides)
    return defaults


def begin_appeal_review_payload(appeal_officer_id, **overrides) -> dict:
    defaults = {"appeal_officer_id": appeal_officer_id}
    defaults.update(overrides)
    return defaults


def decide_appeal_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def informal_resolution_payload(facilitator_id, **overrides) -> dict:
    defaults = {"facilitator_id": facilitator_id}
    defaults.update(overrides)
    return defaults


def informal_consent_payload(party_side, consent, **overrides) -> dict:
    defaults = {"party_side": party_side, "consent": consent}
    defaults.update(overrides)
    return defaults


def resolve_informal_payload(**overrides) -> dict:
    defaults = {"agreed_terms": "Agreed resolution terms"}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
