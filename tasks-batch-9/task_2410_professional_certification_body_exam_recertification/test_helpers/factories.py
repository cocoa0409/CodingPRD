"""Payload factories — one per write operation, input fields only.

Every factory accepts ``**overrides`` so a test can control exactly the field
under assertion and inherit sane values for everything else. Optional inputs
are omitted from the defaults unless a test's claim depends on them, so that a
factory call never accidentally pins a value the PRD leaves to the server.
"""

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Shared literals used across the pipeline fixtures
# ---------------------------------------------------------------------------

DEFAULTS: Dict[str, Any] = {
    "PROGRAM_NAME": "Certified Practitioner X",
    "CREDENTIAL_CODE": "CPX",
    "JTA_VERSION": "JTA-2026.1",
    "DOMAIN_CODE": "D1",
    "ITEM_STEM": "CPX operational item",
    "FORM_CODE": "CPX-F1",
    "CANDIDATE_EMAIL": "cand.a@example.com",
    "CANDIDATE_NAME": "Cand A",
    "CENTER_CODE": "C1",
    "ROOM_CODE": "R1",
    "PROCTOR_POOL_CODE": "P1",
    "PROVIDER": "State Chapter Seminar",
}


def single_domain_blueprint(domain_code: str = "D1", min_operational_items: int = 1
                            ) -> List[Dict[str, Any]]:
    """A one-row blueprint whose ``weight_pct`` values sum to exactly 100."""
    return [{"domain_code": domain_code, "weight_pct": 100,
             "min_operational_items": min_operational_items}]


# ---------------------------------------------------------------------------
# CertificationProgram (PRD §3.1)
# ---------------------------------------------------------------------------


def create_program_payload(**overrides) -> Dict[str, Any]:
    """A minimal single-domain, single-position program.

    The tuning knobs named here are the ones the delivery pipeline needs pinned
    to keep every downstream expectation deterministic: a one-item form, a
    one-panellist quorum with no trimming, a sampling interval that never
    selects the first application for audit, a twelve-month cycle and a
    twelve-credit requirement.
    """
    payload: Dict[str, Any] = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "credential_code": DEFAULTS["CREDENTIAL_CODE"],
        "jta_version": DEFAULTS["JTA_VERSION"],
        "domain_specs": single_domain_blueprint(),
        "form_length": 1,
        "accepted_education_credentials": ["BACHELOR"],
        "psychometric_stat_basis": "POOLED",
        "min_panelists": 1,
        "panel_trim_count": 0,
        "audit_every_nth": 7,
        "cycle_length_months": 12,
        "required_ceu_credits": 12,
    }
    payload.update(overrides)
    return payload


def activate_program_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"activation_note": "CPX live"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Item (PRD §3.2 – §3.4)
# ---------------------------------------------------------------------------


def create_item_payload(program_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "domain_code": DEFAULTS["DOMAIN_CODE"],
        "cognitive_level": "APPLICATION",
        "stem": DEFAULTS["ITEM_STEM"],
    }
    payload.update(overrides)
    return payload


def submit_item_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"revision_note": "first submission"}
    payload.update(overrides)
    return payload


def review_item_payload(decision: str = "APPROVE", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def response_batch_payload(is_pretest: bool = True, response_count: int = 40,
                           correct_count: int = 24, upper_n: int = 10,
                           upper_correct: int = 9, lower_n: int = 10,
                           lower_correct: int = 3, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "is_pretest": is_pretest,
        "response_count": response_count,
        "correct_count": correct_count,
        "upper_n": upper_n,
        "upper_correct": upper_correct,
        "lower_n": lower_n,
        "lower_correct": lower_correct,
    }
    payload.update(overrides)
    return payload


def retire_item_payload(retirement_reason: str = "EXPOSED", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"retirement_reason": retirement_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ExamForm (PRD §3.5)
# ---------------------------------------------------------------------------


def create_form_payload(program_id: str, item_ids: List[str],
                        panelist_user_ids: Optional[List[str]] = None,
                        **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "form_code": DEFAULTS["FORM_CODE"],
        "item_ids": list(item_ids),
        "panelist_user_ids": list(panelist_user_ids or ["pan-1"]),
        "panel_method": "MODIFIED_ANGOFF",
    }
    payload.update(overrides)
    return payload


def panel_rating_payload(panelist_user_id: str, mean_expected_pass_rate: float,
                         **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "panelist_user_id": panelist_user_id,
        "mean_expected_pass_rate": mean_expected_pass_rate,
    }
    payload.update(overrides)
    return payload


def adopt_cut_score_payload(expected_form_version: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_form_version": expected_form_version,
        "adoption_note": "single-panelist adoption",
    }
    payload.update(overrides)
    return payload


def publish_form_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"publication_note": "CPX form live"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Candidate and eligibility (PRD §3.6)
# ---------------------------------------------------------------------------


def create_candidate_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "email": DEFAULTS["CANDIDATE_EMAIL"],
        "full_name": DEFAULTS["CANDIDATE_NAME"],
    }
    payload.update(overrides)
    return payload


def create_application_payload(candidate_id: str, program_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "program_id": program_id,
        "education_credential": "BACHELOR",
        "education_completion_year": 2020,
        "experience_months": 36,
        "attestation_signed": True,
    }
    payload.update(overrides)
    return payload


def verify_dimension_payload(dimension: str, outcome: str = "PASS", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"dimension": dimension, "outcome": outcome}
    payload.update(overrides)
    return payload


def audit_decision_payload(outcome: str = "PASS", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ExamSession and ExamRegistration (PRD §3.7 – §3.8)
# ---------------------------------------------------------------------------


def create_test_center_session_payload(starts_at: str = "2026-08-10T00:00:00Z",
                                       ends_at: str = "2026-08-10T04:00:00Z",
                                       seat_capacity: int = 5,
                                       center_code: str = "C1",
                                       room_code: str = "R1",
                                       **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "modality": "TEST_CENTER",
        "starts_at": starts_at,
        "ends_at": ends_at,
        "seat_capacity": seat_capacity,
        "center_code": center_code,
        "room_code": room_code,
    }
    payload.update(overrides)
    return payload


def create_online_session_payload(starts_at: str = "2026-08-10T00:00:00Z",
                                  ends_at: str = "2026-08-10T04:00:00Z",
                                  seat_capacity: int = 50,
                                  proctor_pool_code: str = "P1",
                                  **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "modality": "ONLINE_PROCTORED",
        "starts_at": starts_at,
        "ends_at": ends_at,
        "seat_capacity": seat_capacity,
        "proctor_pool_code": proctor_pool_code,
    }
    payload.update(overrides)
    return payload


def create_registration_payload(application_id: str, form_id: str,
                                fee_paid_cents: int = 45000, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "form_id": form_id,
        "fee_paid_cents": fee_paid_cents,
    }
    payload.update(overrides)
    return payload


def schedule_seat_payload(session_id: str, expected_session_version: int,
                          **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return payload


def check_in_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"checkin_note": "seated"}
    payload.update(overrides)
    return payload


def submit_responses_payload(raw_score: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"raw_score": raw_score}
    payload.update(overrides)
    return payload


def report_score_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"report_note": "release result"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SecurityIncident (PRD §3.9)
# ---------------------------------------------------------------------------


def create_incident_payload(incident_type: str = "CONTENT_DISCLOSURE",
                            severity: str = "CRITICAL",
                            description: str = "Proctor observed the candidate "
                                               "photographing the screen.",
                            **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "incident_type": incident_type,
        "severity": severity,
        "description": description,
    }
    payload.update(overrides)
    return payload


def adjudicate_incident_payload(outcome: str = "SUBSTANTIATE", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Recertification (PRD §3.11)
# ---------------------------------------------------------------------------


def claim_ceu_payload(activity_date: str = "2026-09-15T00:00:00Z",
                      category: str = "LIVE_INSTRUCTION",
                      provider: str = "State Chapter Seminar",
                      contact_hours: float = 12.0, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "activity_date": activity_date,
        "category": category,
        "provider": provider,
        "contact_hours": contact_hours,
    }
    payload.update(overrides)
    return payload


def review_ceu_payload(outcome: str = "APPROVE", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


def audit_verify_ceu_payload(outcome: str = "VERIFY", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


def close_cycle_payload(expected_certificant_version: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_certificant_version": expected_certificant_version}
    payload.update(overrides)
    return payload


def elect_reexam_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"election_note": "electing re-examination"}
    payload.update(overrides)
    return payload


def reinstate_payload(payment_cents: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"payment_cents": payment_cents}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Discipline (PRD §3.12)
# ---------------------------------------------------------------------------


def open_case_payload(certificant_id: str, allegation_type: str = "CREDENTIAL_MISUSE",
                      description: str = "Holder advertised an unearned specialty.",
                      **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "certificant_id": certificant_id,
        "allegation_type": allegation_type,
        "description": description,
    }
    payload.update(overrides)
    return payload


def request_response_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"request_note": "please respond within 30 days"}
    payload.update(overrides)
    return payload


def respond_to_case_payload(response_text: str = "I dispute the allegation.",
                            **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"response_text": response_text}
    payload.update(overrides)
    return payload


def decide_case_payload(outcome: str, sanction_months: Optional[int] = None,
                        **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if sanction_months is not None:
        payload["sanction_months"] = sanction_months
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-driving capabilities (PRD §2.4, §3.13)
# ---------------------------------------------------------------------------


def set_clock_payload(current_utc: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


def maintenance_run_payload(dry_run: bool = False, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"dry_run": dry_run}
    payload.update(overrides)
    return payload
