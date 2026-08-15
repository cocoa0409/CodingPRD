"""Payload factories — one per writable endpoint, input fields only (PRD §3/§4)."""
from .constants import PERFORMANCE_END, PERFORMANCE_START, RETRO_WINDOW_END, RETRO_WINDOW_START

_period_seq = [0]


def _next_tax_id() -> str:
    _period_seq[0] += 1
    return f"ACO-T{_period_seq[0]:04d}"


def create_agreement_period_payload(**overrides) -> dict:
    defaults = {
        "aco_tax_id": _next_tax_id(),
        "aco_name": "Test ACO",
        "performance_start_date": PERFORMANCE_START,
        "performance_end_date": PERFORMANCE_END,
        "track": "ONE_SIDED",
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(agreement_period_id: str, **overrides) -> dict:
    defaults = {
        "agreement_period_id": agreement_period_id,
        "tin": "100000001",
        "legal_name": "Participant PA",
        "share_weight_bp": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_beneficiary_payload(**overrides) -> dict:
    defaults = {
        "medicare_id": "MBI-0001",
        "birth_year": 1980,
    }
    defaults.update(overrides)
    return defaults


def create_election_payload(**overrides) -> dict:
    defaults = {
        "direction": "OPT_OUT",
        "effective_date": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(agreement_period_id: str, beneficiary_id: str, **overrides) -> dict:
    defaults = {
        "agreement_period_id": agreement_period_id,
        "beneficiary_id": beneficiary_id,
        "service_date": "2026-03-01",
        "allowed_amount_cents": 1000,
        "claim_type": "PART_A",
    }
    defaults.update(overrides)
    return defaults


def create_alignment_run_payload(expected_agreement_period_version: int, **overrides) -> dict:
    defaults = {
        "methodology": "RETROSPECTIVE",
        "window_start_date": RETRO_WINDOW_START,
        "window_end_date": RETRO_WINDOW_END,
        "expected_agreement_period_version": expected_agreement_period_version,
    }
    defaults.update(overrides)
    return defaults


def create_benchmark_payload(expected_agreement_period_version: int, **overrides) -> dict:
    defaults = {
        "variant": "FINAL",
        "expected_agreement_period_version": expected_agreement_period_version,
    }
    defaults.update(overrides)
    return defaults


def create_quality_score_payload(agreement_period_id: str, **overrides) -> dict:
    defaults = {
        "agreement_period_id": agreement_period_id,
        "measure_code": "M1",
        "numerator": 3,
        "denominator": 4,
        "max_points": 10,
    }
    defaults.update(overrides)
    return defaults


def review_score_payload(outcome="VALIDATED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def resubmit_score_payload(numerator=4, denominator=5) -> dict:
    return {"numerator": numerator, "denominator": denominator}


def create_settlement_payload(expected_agreement_period_version: int) -> dict:
    return {"expected_agreement_period_version": expected_agreement_period_version}


def create_appeal_payload(agreement_period_id: str, subject_type: str, subject_id: str,
                          **overrides) -> dict:
    defaults = {
        "agreement_period_id": agreement_period_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "grounds": "dispute",
    }
    defaults.update(overrides)
    return defaults


def rebuttal_payload(memo="additional context") -> dict:
    return {"memo": memo}


def decide_payload(outcome="UPHELD", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def determine_review_payload(outcome="DISMISSED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(**overrides) -> dict:
    defaults = {
        "direction": "CREDIT",
        "amount_cents": 1000,
        "reason_code": "OPERATOR",
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
