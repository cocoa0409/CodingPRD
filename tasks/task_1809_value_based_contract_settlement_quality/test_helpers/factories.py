"""Payload factories — one per entity, input fields only (PRD §3)."""

# Canonical decile catalog shared by the test contracts: 9 strictly ascending
# thresholds per measure (PRD §3.3).
DECILE_THRESHOLDS = [1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000]

DUAL_MEASURE_CATALOG = [
    {"measure_code": "HBA1C", "weight_bp": 9000, "decile_thresholds_bp": DECILE_THRESHOLDS},
    {"measure_code": "MAMMO", "weight_bp": 1000, "decile_thresholds_bp": DECILE_THRESHOLDS},
]

SINGLE_MEASURE_CATALOG = [
    {"measure_code": "HBA1C", "weight_bp": 10000, "decile_thresholds_bp": DECILE_THRESHOLDS},
]


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_program_payload(**overrides) -> dict:
    defaults = {"program_name": "MA Value", "line_of_business": "MEDICARE_ADVANTAGE"}
    defaults.update(overrides)
    return defaults


def create_practice_group_payload(**overrides) -> dict:
    defaults = {"group_name": "G1", "tin": "100000001"}
    defaults.update(overrides)
    return defaults


def create_practice_payload(practice_group_id: str, **overrides) -> dict:
    defaults = {
        "practice_group_id": practice_group_id,
        "practice_name": "PR1",
        "npi": "2000000001",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(program_id: str, **overrides) -> dict:
    defaults = {"program_id": program_id, "member_ref": "M-001", "birth_year": 1980}
    defaults.update(overrides)
    return defaults


def create_span_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(program_id: str, practice_group_id: str, **overrides) -> dict:
    """Canonical TWO_SIDED contract terms (PRD §3.3)."""
    defaults = {
        "program_id": program_id,
        "practice_group_id": practice_group_id,
        "contract_ref": "C-1",
        "effective_start": "2026-01-01",
        "effective_end": "2027-01-01",
        "risk_track": "TWO_SIDED",
        "risk_model": "PROSPECTIVE",
        "benchmark_pmpm_cents": 100000,
        "shared_savings_rate_bp": 5000,
        "shared_loss_rate_bp": 4000,
        "min_savings_rate_bp": 200,
        "min_loss_rate_bp": 200,
        "savings_cap_bp": 1000,
        "loss_cap_bp": 800,
        "stop_loss_cents": 2000000,
        "withhold_rate_bp": 500,
        "quality_gate_floor_points": 30,
        "quality_gate_excellence_points": 80,
        "estimate_method": "ANNUALIZATION",
        "quality_measures": DUAL_MEASURE_CATALOG,
    }
    defaults.update(overrides)
    return defaults


def create_year_payload(contract_id: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "year_label": 2026,
        "period_start": "2026-01-01",
        "period_end": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_attribution_run_payload(expected_performance_year_version: int, **overrides) -> dict:
    defaults = {
        "run_label": "R-1",
        "expected_performance_year_version": expected_performance_year_version,
    }
    defaults.update(overrides)
    return defaults


def create_attribution_record_payload(member_id: str, practice_id: str, **overrides) -> dict:
    defaults = {"member_id": member_id, "practice_id": practice_id}
    defaults.update(overrides)
    return defaults


def create_risk_score_payload(member_id: str, performance_year_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "performance_year_id": performance_year_id,
        "model_used": "PROSPECTIVE",
        "score_milli": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(performance_year_id: str, member_id: str, **overrides) -> dict:
    defaults = {
        "performance_year_id": performance_year_id,
        "member_id": member_id,
        "claim_ref": "CL-1",
        "service_date": "2026-03-10",
        "paid_amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_quality_result_payload(performance_year_id: str, **overrides) -> dict:
    defaults = {
        "performance_year_id": performance_year_id,
        "measure_code": "HBA1C",
        "numerator_count": 350,
        "denominator_count": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_interim_report_payload(performance_year_id: str, expected_performance_year_version: int, **overrides) -> dict:
    defaults = {
        "performance_year_id": performance_year_id,
        "months_elapsed": 6,
        "expected_performance_year_version": expected_performance_year_version,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(performance_year_id: str, **overrides) -> dict:
    defaults = {"performance_year_id": performance_year_id}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {
        "dispute_ref": "D-1",
        "reason_code": "CLAIMS_MISSING",
        "claimed_adjustment_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(outcome: str) -> dict:
    return {"outcome": outcome}


def suspend_group_payload(reason: str = "audit hold") -> dict:
    return {"reason": reason}


def create_renewal_analysis_payload(expected_contract_version: int) -> dict:
    return {"expected_contract_version": expected_contract_version}
