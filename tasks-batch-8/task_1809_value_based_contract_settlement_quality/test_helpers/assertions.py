"""Entity assertions and domain invariant checkers (PRD §2.5 common fields)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AnalysisStatus, ClaimStatus, ContractStatus, DisputeStatus, GroupStatus,
    MemberStatus, PracticeStatus, ProgramStatus, RecordStatus, RemittanceStatus,
    ReportStatus, ResultStatus, RunStatus, ScoreStatus, SettlementStatus,
    SpanStatus, YearStatus,
)


def _assert_common_fields(data: dict, entity: str):
    """PRD §2.5: id, created_at, updated_at, version on every resource."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def _assert_status(data: dict, field: str, enum, entity: str):
    assert data.get(field) in {e.value for e in enum}, (
        f"{entity}.{field} must be one of {[e.value for e in enum]}, got {data.get(field)!r}"
    )


def assert_program(data: dict):
    _assert_common_fields(data, "Program")
    assert isinstance(data.get("program_name"), str) and data["program_name"]
    _assert_status(data, "program_status", ProgramStatus, "Program")


def assert_practice_group(data: dict):
    _assert_common_fields(data, "PracticeGroup")
    assert isinstance(data.get("group_name"), str) and data["group_name"]
    assert isinstance(data.get("tin"), str) and data["tin"]
    _assert_status(data, "group_status", GroupStatus, "PracticeGroup")


def assert_practice(data: dict):
    _assert_common_fields(data, "Practice")
    assert isinstance(data.get("practice_group_id"), str)
    assert isinstance(data.get("npi"), str) and data["npi"]
    _assert_status(data, "practice_status", PracticeStatus, "Practice")


def assert_member(data: dict):
    _assert_common_fields(data, "Member")
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("member_ref"), str) and data["member_ref"]
    assert isinstance(data.get("birth_year"), int)
    _assert_status(data, "member_status", MemberStatus, "Member")


def assert_eligibility_span(data: dict):
    _assert_common_fields(data, "EligibilitySpan")
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("start_date"), str)
    assert isinstance(data.get("end_date"), str)
    _assert_status(data, "span_status", SpanStatus, "EligibilitySpan")


def assert_contract(data: dict):
    _assert_common_fields(data, "Contract")
    assert isinstance(data.get("program_id"), str)
    assert isinstance(data.get("practice_group_id"), str)
    assert isinstance(data.get("contract_ref"), str) and data["contract_ref"]
    assert isinstance(data.get("benchmark_pmpm_cents"), int)
    assert isinstance(data.get("withhold_rate_bp"), int)
    _assert_status(data, "contract_status", ContractStatus, "Contract")


def assert_performance_year(data: dict):
    _assert_common_fields(data, "PerformanceYear")
    assert isinstance(data.get("contract_id"), str)
    assert isinstance(data.get("year_label"), int)
    _assert_status(data, "year_status", YearStatus, "PerformanceYear")
    assert isinstance(data.get("total_member_months"), int)
    assert isinstance(data.get("actual_cost_cents"), int)
    assert isinstance(data.get("benchmark_cost_cents"), int)
    assert isinstance(data.get("withhold_pool_cents"), int)
    assert isinstance(data.get("accrued_reserve_cents"), int)


def assert_attribution_run(data: dict):
    _assert_common_fields(data, "AttributionRun")
    assert isinstance(data.get("performance_year_id"), str)
    assert isinstance(data.get("run_seq"), int) and data["run_seq"] >= 1
    _assert_status(data, "run_status", RunStatus, "AttributionRun")
    assert isinstance(data.get("attributed_member_count"), int)


def assert_attribution_record(data: dict):
    _assert_common_fields(data, "AttributionRecord")
    assert isinstance(data.get("attribution_run_id"), str)
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("practice_id"), str)
    assert isinstance(data.get("member_months"), int)
    _assert_status(data, "record_status", RecordStatus, "AttributionRecord")


def assert_risk_score(data: dict):
    _assert_common_fields(data, "RiskScore")
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("performance_year_id"), str)
    assert data.get("model_used") in ("PROSPECTIVE", "CONCURRENT")
    assert isinstance(data.get("score_milli"), int)
    _assert_status(data, "score_status", ScoreStatus, "RiskScore")


def assert_claim(data: dict):
    _assert_common_fields(data, "ClaimRecord")
    assert isinstance(data.get("performance_year_id"), str)
    assert isinstance(data.get("member_id"), str)
    assert isinstance(data.get("claim_ref"), str) and data["claim_ref"]
    assert isinstance(data.get("paid_amount_cents"), int)
    _assert_status(data, "claim_status", ClaimStatus, "ClaimRecord")


def assert_quality_result(data: dict):
    _assert_common_fields(data, "QualityMeasureResult")
    assert isinstance(data.get("performance_year_id"), str)
    assert isinstance(data.get("measure_code"), str) and data["measure_code"]
    assert isinstance(data.get("numerator_count"), int)
    assert isinstance(data.get("denominator_count"), int)
    _assert_status(data, "result_status", ResultStatus, "QualityMeasureResult")


def assert_interim_report(data: dict):
    _assert_common_fields(data, "InterimReport")
    assert isinstance(data.get("performance_year_id"), str)
    assert isinstance(data.get("months_elapsed"), int)
    assert isinstance(data.get("report_seq"), int) and data["report_seq"] >= 1
    _assert_status(data, "report_status", ReportStatus, "InterimReport")


def assert_settlement(data: dict):
    _assert_common_fields(data, "Settlement")
    assert isinstance(data.get("performance_year_id"), str)
    assert isinstance(data.get("settlement_seq"), int) and data["settlement_seq"] >= 1
    _assert_status(data, "settlement_status", SettlementStatus, "Settlement")
    assert isinstance(data.get("needs_recompute"), bool)


def assert_dispute(data: dict):
    _assert_common_fields(data, "SettlementDispute")
    assert isinstance(data.get("settlement_id"), str)
    assert isinstance(data.get("dispute_ref"), str) and data["dispute_ref"]
    assert isinstance(data.get("claimed_adjustment_cents"), int)
    _assert_status(data, "dispute_status", DisputeStatus, "SettlementDispute")


def assert_remittance(data: dict):
    _assert_common_fields(data, "DistributionRemittance")
    assert isinstance(data.get("settlement_id"), str)
    assert isinstance(data.get("practice_id"), str)
    assert isinstance(data.get("practice_member_months"), int)
    assert isinstance(data.get("amount_cents"), int)
    _assert_status(data, "remittance_status", RemittanceStatus, "DistributionRemittance")


def assert_renewal_analysis(data: dict):
    _assert_common_fields(data, "RenewalAnalysis")
    assert isinstance(data.get("contract_id"), str)
    assert isinstance(data.get("analysis_seq"), int) and data["analysis_seq"] >= 1
    _assert_status(data, "analysis_status", AnalysisStatus, "RenewalAnalysis")


def assert_year_rollups(data: dict, *, total_member_months=None, benchmark_cost_cents=None,
                        actual_cost_cents=None, withhold_pool_cents=None):
    """Domain invariants on a PerformanceYear's rollup fields."""
    if total_member_months is not None:
        assert data["total_member_months"] == total_member_months, (
            f"total_member_months: expected {total_member_months}, got {data['total_member_months']}"
        )
    if benchmark_cost_cents is not None:
        assert data["benchmark_cost_cents"] == benchmark_cost_cents, (
            f"benchmark_cost_cents: expected {benchmark_cost_cents}, got {data['benchmark_cost_cents']}"
        )
    if actual_cost_cents is not None:
        assert data["actual_cost_cents"] == actual_cost_cents, (
            f"actual_cost_cents: expected {actual_cost_cents}, got {data['actual_cost_cents']}"
        )
    if withhold_pool_cents is not None:
        assert data["withhold_pool_cents"] == withhold_pool_cents, (
            f"withhold_pool_cents: expected {withhold_pool_cents}, got {data['withhold_pool_cents']}"
        )


def assert_settlement_chain(data: dict, *, gross_savings_cents=None, savings_rate_bp=None,
                            shared_savings_cents=None, shared_losses_cents=None,
                            quality_composite_points=None, quality_multiplier_bp=None,
                            quality_adjusted_savings_cents=None, withhold_released_cents=None,
                            withhold_forfeited_cents=None, net_payable_cents=None):
    """Pinned eight-step settlement chain values (PRD §3.10)."""
    checks = {
        "gross_savings_cents": gross_savings_cents,
        "savings_rate_bp": savings_rate_bp,
        "shared_savings_cents": shared_savings_cents,
        "shared_losses_cents": shared_losses_cents,
        "quality_composite_points": quality_composite_points,
        "quality_multiplier_bp": quality_multiplier_bp,
        "quality_adjusted_savings_cents": quality_adjusted_savings_cents,
        "withhold_released_cents": withhold_released_cents,
        "withhold_forfeited_cents": withhold_forfeited_cents,
        "net_payable_cents": net_payable_cents,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert data.get(field) == expected, (
                f"Settlement.{field}: expected {expected}, got {data.get(field)}"
            )
