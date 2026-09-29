"""Payload factories - one per resource, input fields only."""
import itertools

from .constants import REQUIRED_TRAINING_MODULES, TEST_DEFAULTS

_case_number_counter = itertools.count(1)
_classification_code_counter = itertools.count(1)


def unique_case_number(prefix: str = "07-RC") -> str:
    """A docket number that has not been used in this test process."""
    return f"{prefix}-{330000 + next(_case_number_counter)}"


def unique_classification_code(stem: str = "CLS") -> str:
    return f"{stem}{next(_classification_code_counter):03d}"


def create_petition_payload(**overrides) -> dict:
    payload = {
        "case_number": unique_case_number(),
        "petition_type": "RC",
        "union_name": TEST_DEFAULTS["UNION_NAME"],
        "filed_date": TEST_DEFAULTS["FILED_DATE"],
        "proposed_unit_description": TEST_DEFAULTS["UNIT_DESCRIPTION"],
        "claimed_employee_count": 120,
        "payroll_period_end": TEST_DEFAULTS["PAYROLL_PERIOD_END"],
    }
    payload.update(overrides)
    return payload


def create_classification_payload(petition_id: str, **overrides) -> dict:
    payload = {
        "petition_id": petition_id,
        "code": unique_classification_code(),
        "title": "Production Operator",
        "headcount": 60,
        "avg_hourly_wage_cents": 2400,
        "shift_code": "A",
        "work_location": "PLANT_1",
        "supervisory_authority_count": 0,
        "employer_position": "INCLUDE",
        "union_position": "INCLUDE",
        "supervision_overlap": 88,
        "skills_overlap": 90,
        "functional_integration": 92,
        "interchange_rate": 74,
        "work_conditions_overlap": 95,
    }
    payload.update(overrides)
    return payload


def verify_showing_payload(**overrides) -> dict:
    payload = {
        "submitted_card_count": 40,
        "duplicate_card_count": 3,
        "undated_card_count": 2,
        "stale_card_count": 2,
        "nonunit_card_count": 3,
    }
    payload.update(overrides)
    return payload


def create_election_agreement_payload(petition_id: str, **overrides) -> dict:
    payload = {
        "petition_id": petition_id,
        "agreement_type": "STIPULATED",
        "proposed_election_date": TEST_DEFAULTS["ELECTION_DATE"],
        "proposed_voting_method": "MANUAL",
    }
    payload.update(overrides)
    return payload


def stipulate_payload(**overrides) -> dict:
    payload = {
        "approved_election_date": TEST_DEFAULTS["ELECTION_DATE"],
        "voting_method": "MANUAL",
        "polls_open_at": TEST_DEFAULTS["POLLS_OPEN_AT"],
        "polls_close_at": TEST_DEFAULTS["POLLS_CLOSE_AT"],
    }
    payload.update(overrides)
    return payload


def direct_election_payload(**overrides) -> dict:
    payload = {
        "decision_date": "2026-08-25",
        "approved_election_date": TEST_DEFAULTS["ELECTION_DATE"],
        "voting_method": "MANUAL",
        "polls_open_at": TEST_DEFAULTS["POLLS_OPEN_AT"],
        "polls_close_at": TEST_DEFAULTS["POLLS_CLOSE_AT"],
    }
    payload.update(overrides)
    return payload


def create_voter_list_payload(petition_id: str, election_agreement_id: str,
                              expected_petition_version: int, **overrides) -> dict:
    payload = {
        "petition_id": petition_id,
        "election_agreement_id": election_agreement_id,
        "expected_petition_version": expected_petition_version,
    }
    payload.update(overrides)
    return payload


def create_voter_list_entry_payload(voter_list_id: str, classification_id: str, **overrides) -> dict:
    """A complete entry: all five statutory content fields present."""
    payload = {
        "voter_list_id": voter_list_id,
        "classification_id": classification_id,
        "full_name": "Dana Ruiz",
        "hire_date": "2024-03-11",
        "home_address": "144 Foundry Street, Springfield",
        "personal_email": "dana.ruiz@example.com",
        "personal_phone": "+1-555-0142",
        "shift_code": "A",
        "work_location": "PLANT_1",
    }
    payload.update(overrides)
    return payload


def create_supervisor_payload(petition_id: str, **overrides) -> dict:
    payload = {
        "petition_id": petition_id,
        "full_name": "Morgan Alvarez",
        "job_title": "Production Supervisor",
        "span_of_control": 18,
        "has_hire_fire_authority": False,
    }
    payload.update(overrides)
    return payload


def train_payload(**overrides) -> dict:
    payload = {
        "modules_completed": list(REQUIRED_TRAINING_MODULES),
        "quiz_score": 88,
    }
    payload.update(overrides)
    return payload


def record_violation_payload(**overrides) -> dict:
    payload = {"violation_code": "THREAT", "substantiated": True}
    payload.update(overrides)
    return payload


def create_campaign_communication_payload(petition_id: str, **overrides) -> dict:
    payload = {
        "petition_id": petition_id,
        "channel": "EMAIL",
        "audience_scope": "CLASSIFICATION",
        "planned_delivery_at": "2026-08-26T14:00:00Z",
        "message_summary": "Explains the employer position on the pending representation petition.",
    }
    payload.update(overrides)
    return payload


def accuracy_review_payload(**overrides) -> dict:
    payload = {"material_claim_count": 2, "unsupported_material_claim_count": 0}
    payload.update(overrides)
    return payload


def review_communication_payload(**overrides) -> dict:
    payload = {"disposition": "APPROVE"}
    payload.update(overrides)
    return payload


def create_poll_session_payload(election_round_id: str, expected_election_round_version: int,
                                **overrides) -> dict:
    payload = {
        "election_round_id": election_round_id,
        "location_code": "GATE_A",
        "session_start_at": "2026-09-01T08:00:00Z",
        "session_end_at": "2026-09-01T12:00:00Z",
        "method": "MANUAL",
        "expected_election_round_version": expected_election_round_version,
    }
    payload.update(overrides)
    return payload


def designate_observer_payload(**overrides) -> dict:
    payload = {"party": "EMPLOYER", "observer_name": "Riley Chen"}
    payload.update(overrides)
    return payload


def close_session_payload(**overrides) -> dict:
    payload = {"votes_for_count": 30, "votes_against_count": 25, "void_count": 1}
    payload.update(overrides)
    return payload


def create_challenged_ballot_payload(poll_session_id: str, **overrides) -> dict:
    payload = {
        "poll_session_id": poll_session_id,
        "challenger_party": "EMPLOYER",
        "basis": "SUPERVISOR",
    }
    payload.update(overrides)
    return payload


def resolve_ballot_payload(**overrides) -> dict:
    payload = {"resolution": "COUNTED_FOR"}
    payload.update(overrides)
    return payload


def create_objection_payload(election_round_id: str, **overrides) -> dict:
    payload = {
        "election_round_id": election_round_id,
        "filed_by_party": "EMPLOYER",
        "ground_code": "POLLING_IRREGULARITY",
        "conduct_occurred_at": "2026-09-01T10:00:00Z",
        "alleged_affected_voter_count": 10,
        "description": "Ballots were handed out away from the designated polling table.",
    }
    payload.update(overrides)
    return payload


def rule_objection_payload(**overrides) -> dict:
    payload = {
        "disposition": "OVERRULE",
        "disposition_rationale": "The conduct alleged could not have affected the results.",
    }
    payload.update(overrides)
    return payload


def create_ulp_charge_payload(petition_id: str, **overrides) -> dict:
    payload = {
        "petition_id": petition_id,
        "charging_party": "UNION",
        "charged_party": "EMPLOYER",
        "section_code": "8A1",
        "allegation_summary": "Supervisor threatened plant closure during a shift meeting.",
        "conduct_occurred_at": "2026-08-20T15:00:00Z",
        "blocking_requested": False,
    }
    payload.update(overrides)
    return payload


def determine_charge_payload(**overrides) -> dict:
    payload = {"determination": "DISMISS"}
    payload.update(overrides)
    return payload


def settle_charge_payload(**overrides) -> dict:
    payload = {"settlement_type": "NON_BOARD"}
    payload.update(overrides)
    return payload
