"""Payload factories — one per entity, input fields only."""
from .constants import DEFAULT_LOSS_DATE, DEFAULT_STATUTE_DEADLINE


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Mutual",
        "naic_code": "12345",
        "commission_rate_bps": 2500,
        "commission_basis": "NET",
    }
    defaults.update(overrides)
    return defaults


def create_adverse_party_payload(**overrides) -> dict:
    defaults = {
        "name": "Adverse Party",
        "adverse_carrier_name": "Rival Insurance",
        "is_arbitration_eligible": True,
        "policy_limit_cents": 5_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(carrier_id, adverse_party_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "adverse_party_id": adverse_party_id,
        "claim_reference": "CLM-1",
        "loss_date": DEFAULT_LOSS_DATE,
        "paid_loss_cents": 2_500_000,
        "deductible_cents": 500_000,
        "total_damages_cents": 4_000_000,
        "statute_deadline": DEFAULT_STATUTE_DEADLINE,
    }
    defaults.update(overrides)
    return defaults


def assess_liability_payload(liability_pct=80, **overrides) -> dict:
    defaults = {"liability_pct": liability_pct}
    defaults.update(overrides)
    return defaults


def create_demand_payload(amount_demanded_cents=3_000_000, **overrides) -> dict:
    defaults = {"amount_demanded_cents": amount_demanded_cents}
    defaults.update(overrides)
    return defaults


def record_response_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_arbitration_payload(forum="AF", **overrides) -> dict:
    defaults = {"forum": forum}
    defaults.update(overrides)
    return defaults


def schedule_hearing_payload(hearing_start, hearing_end, **overrides) -> dict:
    defaults = {"hearing_start": hearing_start, "hearing_end": hearing_end}
    defaults.update(overrides)
    return defaults


def file_round_payload(note="round note", **overrides) -> dict:
    defaults = {"note": note}
    defaults.update(overrides)
    return defaults


def decide_arbitration_payload(award_amount_cents=2_000_000, **overrides) -> dict:
    defaults = {"award_amount_cents": award_amount_cents}
    defaults.update(overrides)
    return defaults


def propose_settlement_payload(settled_amount_cents, expected_claim_version, **overrides) -> dict:
    defaults = {
        "settled_amount_cents": settled_amount_cents,
        "expected_claim_version": expected_claim_version,
    }
    defaults.update(overrides)
    return defaults


def create_recovery_payment_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    defaults = {
        "doc_type": "POLICE_REPORT",
        "title": "Report 1",
        "uri": "s3://evidence/1",
    }
    defaults.update(overrides)
    return defaults


def create_commission_statement_payload(period_label="2026-Q3", **overrides) -> dict:
    defaults = {"period_label": period_label}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
