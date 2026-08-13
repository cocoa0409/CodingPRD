"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_agreement_period(data: dict):
    _assert_common(data)
    assert isinstance(data["aco_tax_id"], str) and data["aco_tax_id"]
    assert isinstance(data["aco_name"], str) and data["aco_name"]
    assert isinstance(data["performance_start_date"], str)
    assert isinstance(data["performance_end_date"], str)
    assert data["track"] in ("ONE_SIDED", "TWO_SIDED")
    assert data["status"] in ("SETUP", "OPEN", "ASSIGNMENT_LOCKED", "SETTLED")


def assert_participant(data: dict):
    _assert_common(data)
    assert isinstance(data["agreement_period_id"], str)
    assert isinstance(data["tin"], str) and data["tin"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["share_weight_bp"], int) and data["share_weight_bp"] > 0


def assert_beneficiary(data: dict):
    _assert_common(data)
    assert isinstance(data["medicare_id"], str) and data["medicare_id"]
    assert isinstance(data["birth_year"], int)
    assert isinstance(data["dual_eligible"], bool)
    assert isinstance(data["disabled"], bool)
    assert isinstance(data["esrd"], bool)


def assert_data_sharing_election(data: dict):
    """Append-only election entry: id + created_at only, no updated_at/version (PRD §2.4)."""
    _assert_common(data, with_version=False)
    assert "updated_at" not in data, "DataSharingElection must not carry updated_at"
    assert "version" not in data, "DataSharingElection must not carry version"
    assert data["direction"] in ("OPT_OUT", "OPT_IN")
    assert isinstance(data["effective_date"], str)


def assert_alignment_run(data: dict):
    _assert_common(data)
    assert data["methodology"] in ("PROSPECTIVE", "RETROSPECTIVE")
    assert isinstance(data["window_start_date"], str)
    assert isinstance(data["window_end_date"], str)
    assert isinstance(data["records_created_count"], int) and data["records_created_count"] >= 0
    assert data["status"] in ("COMPLETED", "SUPERSEDED", "LOCKED")


def assert_attribution_record(data: dict):
    _assert_common(data)
    assert isinstance(data["agreement_period_id"], str)
    assert isinstance(data["beneficiary_id"], str)
    assert isinstance(data["alignment_run_id"], str)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["plurality_cost_cents"], int)
    assert data["methodology"] in ("PROSPECTIVE", "RETROSPECTIVE")
    assert data["status"] in (
        "PROVISIONAL", "FINAL", "UNDER_APPEAL", "OVERTURNED", "EXCLUDED_OPT_OUT", "SUPERSEDED",
    )


def assert_claim_line(data: dict):
    _assert_common(data)
    assert isinstance(data["agreement_period_id"], str)
    assert isinstance(data["beneficiary_id"], str)
    assert isinstance(data["service_date"], str)
    assert isinstance(data["allowed_amount_cents"], int) and data["allowed_amount_cents"] > 0
    assert data["claim_type"] in ("PART_A", "PART_B")
    assert isinstance(data["review_excluded"], bool)
    assert data["status"] in ("RECEIVED", "ADJUDICATED", "VOIDED")


def assert_benchmark(data: dict):
    _assert_common(data)
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["beneficiary_months"], int) and data["beneficiary_months"] >= 0
    assert isinstance(data["risk_score_sum"], (int, float))
    assert isinstance(data["update_factor_used"], (int, float))
    assert isinstance(data["total_benchmark_cents"], int) and data["total_benchmark_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "LOCKED")


def assert_quality_score(data: dict):
    _assert_common(data)
    assert isinstance(data["agreement_period_id"], str)
    assert isinstance(data["measure_code"], str) and data["measure_code"]
    assert isinstance(data["numerator"], int) and data["numerator"] >= 0
    assert isinstance(data["denominator"], int) and data["denominator"] > 0
    assert isinstance(data["max_points"], int) and data["max_points"] > 0
    assert isinstance(data["performance_rate"], (int, float))
    assert isinstance(data["earned_points"], (int, float))
    assert isinstance(data["reported_by_user_id"], str) and data["reported_by_user_id"]
    assert data["status"] in ("REPORTED", "VALIDATED", "REJECTED")


def assert_settlement(data: dict):
    _assert_common(data)
    assert isinstance(data["agreement_period_id"], str)
    assert isinstance(data["benchmark_id"], str)
    for field in (
        "expenditure_total_cents", "gross_savings_cents", "msr_threshold_cents",
        "shared_savings_pre_sequestration_cents", "sequestration_levy_cents",
        "net_shared_savings_cents", "shared_loss_cents", "distributable_pool_cents",
        "reconciliation_balance_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["quality_score_snapshot"], (int, float))
    assert isinstance(data["quality_multiplier_snapshot"], (int, float))
    assert data["status"] in ("PROPOSED", "STALE", "SUPERSEDED", "FINAL", "SETTLED", "REOPENED")


def assert_distribution_line(data: dict):
    _assert_common(data)
    assert isinstance(data["settlement_id"], str)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PENDING", "APPROVED", "PAID", "VOIDED")


def assert_high_cost_review(data: dict):
    _assert_common(data)
    assert isinstance(data["agreement_period_id"], str)
    assert isinstance(data["beneficiary_id"], str)
    assert isinstance(data["flagged_expenditure_cents"], int)
    assert data["status"] in ("FLAGGED", "CONFIRMED_EXCLUSION", "DISMISSED")
    assert data.get("dismissal_reason") in (None, "MANUAL", "THRESHOLD_FALLEN")


def assert_appeal(data: dict):
    _assert_common(data)
    assert isinstance(data["agreement_period_id"], str)
    assert data["subject_type"] in ("ATTRIBUTION", "SETTLEMENT")
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["filed_by_participant_id"], str)
    assert isinstance(data["grounds"], str)
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    assert data.get("decided_outcome") in (None, "UPHELD", "DENIED")
    assert data["status"] in ("UNDER_REVIEW", "REBUTTAL", "UPHELD", "DENIED")


def assert_reconciliation_adjustment(data: dict):
    _assert_common(data)
    assert isinstance(data["settlement_id"], str)
    assert data["direction"] in ("CREDIT", "DEBIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["reason_code"], str) and data["reason_code"]
    assert data["status"] in ("POSTED", "REVERSED")


def assert_distribution_pool_conservation(lines: list, pool_cents: int):
    """PRD §3.7 invariant: created lines sum to the pool exactly."""
    assert sum(line["amount_cents"] for line in lines) == pool_cents, (
        "Distribution lines must sum to the distributable pool exactly"
    )
