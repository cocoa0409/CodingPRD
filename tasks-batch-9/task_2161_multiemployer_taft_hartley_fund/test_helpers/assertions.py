"""Resource assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_identity(data: dict, label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 UTC timestamp"


def _assert_common_fields(data: dict, label: str) -> None:
    """id, created_at, updated_at and version, for every resource that carries them."""
    _assert_identity(data, label)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def assert_immutable_ledger_row(data: dict, label: str) -> None:
    """A contribution line or a motion vote carries only id and created_at."""
    _assert_identity(data, label)
    assert "updated_at" not in data, f"{label} must not serialise updated_at"
    assert "version" not in data, f"{label} must not serialise version"


def assert_fund(data: dict) -> None:
    _assert_common_fields(data, "Fund")
    assert data["fund_role"] in ("HOME", "SISTER")
    assert data["governance_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert data["reciprocity_agreement_status"] in ("NONE", "EXECUTED")
    assert data["accrual_method"] in ("HOURS_BASED", "ELAPSED_TIME")
    assert isinstance(data["plan_year_start_month"], int)
    assert 1 <= data["plan_year_start_month"] <= 12
    assert isinstance(data["total_uvb_cents"], int)
    assert isinstance(data["allocated_uvb_cents"], int)
    assert isinstance(data["unallocated_uvb_cents"], int)
    assert isinstance(data["active_union_trustees"], int)
    assert isinstance(data["active_employer_trustees"], int)
    assert isinstance(data["suspended_employer_count"], int)
    assert isinstance(data["reciprocal_receipts_cents"], int)
    assert isinstance(data["collections_run_index"], int)
    assert len(data["pool_prior_year_contributions_cents"]) == 5


def assert_fund_pool_split(data: dict) -> None:
    """unallocated_uvb_cents is always total_uvb_cents less allocated_uvb_cents."""
    assert (
        data["unallocated_uvb_cents"]
        == data["total_uvb_cents"] - data["allocated_uvb_cents"]
    ), (
        "unallocated_uvb_cents must equal total_uvb_cents less allocated_uvb_cents, "
        f"got {data['unallocated_uvb_cents']} for "
        f"{data['total_uvb_cents']} - {data['allocated_uvb_cents']}"
    )


def assert_employer(data: dict) -> None:
    _assert_common_fields(data, "Employer")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "WITHDRAWN")
    assert isinstance(data["contribution_rate_millicents_per_hour"], int)
    assert isinstance(data["delinquency_strikes"], int)
    assert isinstance(data["cumulative_delinquent_cents"], int)
    assert len(data["prior_year_contributions_cents"]) == 5
    assert len(data["prior_year_base_units"]) == 5


def assert_participant(data: dict) -> None:
    _assert_common_fields(data, "Participant")
    assert data["status"] in ("ACTIVE", "BROKEN_SERVICE")
    assert data["eligibility_status"] in ("ELIGIBLE", "NOT_ELIGIBLE")
    assert isinstance(data["vesting_service_years"], int)
    assert isinstance(data["vested"], bool)
    assert isinstance(data["consecutive_break_years"], int)
    for field in (
        "credited_hours_total",
        "reciprocal_hours_total",
        "hour_bank_hours",
        "forfeited_hours_total",
        "total_pension_credits",
    ):
        assert isinstance(data[field], (int, float)), f"Participant.{field} is numeric"


def assert_contribution_report(data: dict) -> None:
    _assert_common_fields(data, "ContributionReport")
    assert data["filing_status"] in ("SUBMITTED", "POSTED", "SUPERSEDED")
    assert data["payment_status"] in ("UNPAID", "PARTIAL", "PAID_IN_FULL", "DELINQUENT")
    assert data["origin"] in ("EMPLOYER", "AUDIT")
    assert isinstance(data["total_contributions_due_cents"], int)
    assert isinstance(data["amount_remitted_cents"], int)
    assert isinstance(data["due_date"], str) and len(data["due_date"]) == 10


def assert_contribution_line(data: dict) -> None:
    assert_immutable_ledger_row(data, "ContributionLine")
    assert data["work_classification"] in ("JOURNEYMAN", "APPRENTICE", "FOREMAN")
    assert isinstance(data["contribution_cents"], int)
    assert isinstance(data["gross_wages_cents"], int)


def assert_delinquency_assessment(data: dict) -> None:
    _assert_common_fields(data, "DelinquencyAssessment")
    assert data["basis"] in ("STATUTORY", "PLAN_SCHEDULE")
    assert data["status"] in ("ASSESSED", "SETTLED", "WAIVED")
    for field in (
        "days_late",
        "principal_cents",
        "interest_cents",
        "liquidated_damages_cents",
        "total_cents",
    ):
        assert isinstance(data[field], int), f"DelinquencyAssessment.{field} is integer"
    assert (
        data["total_cents"]
        == data["principal_cents"]
        + data["interest_cents"]
        + data["liquidated_damages_cents"]
    ), "total_cents is principal plus interest plus liquidated damages"


def assert_payroll_audit(data: dict) -> None:
    _assert_common_fields(data, "PayrollAudit")
    assert data["status"] in (
        "IN_FIELDWORK",
        "FINDINGS_ISSUED",
        "EMPLOYER_ACCEPTED",
        "CLOSED",
        "ABANDONED",
    )
    assert isinstance(data["round_count"], int)
    assert isinstance(data["underpayment_principal_cents"], int)
    assert isinstance(data["findings"], list)


def assert_coverage_month(data: dict) -> None:
    _assert_common_fields(data, "CoverageMonth")
    assert data["status"] in ("GRANTED", "REVOKED")
    assert data["source"] in ("CURRENT_HOURS", "BANK_DRAW", "RECIPROCAL")
    assert isinstance(data["coverage_month"], str) and len(data["coverage_month"]) == 7


def assert_pension_accrual(data: dict) -> None:
    _assert_common_fields(data, "PensionAccrual")
    assert data["accrual_status"] in ("OPEN", "FINALIZED")
    assert isinstance(data["plan_year"], int)
    assert isinstance(data["vesting_year_earned"], bool)
    assert isinstance(data["break_in_service"], bool)
    assert 0.0 <= float(data["pension_credit"]) <= 1.0


def assert_withdrawal_assessment(data: dict) -> None:
    _assert_common_fields(data, "WithdrawalAssessment")
    assert data["method"] in ("PRESUMPTIVE", "ROLLING_FIVE")
    assert data["status"] in (
        "DRAFT",
        "CERTIFIED",
        "DEMANDED",
        "REVIEW_REQUESTED",
        "PAYMENT_ACTIVE",
        "ACCELERATED",
        "SATISFIED",
    )
    assert isinstance(data["twenty_year_cap_applied"], bool)
    for field in (
        "raw_allocation_cents",
        "de_minimis_reduction_cents",
        "net_liability_cents",
        "annual_payment_cents",
        "schedule_years",
        "capped_liability_cents",
    ):
        assert isinstance(data[field], int), f"WithdrawalAssessment.{field} is integer"
    assert (
        data["net_liability_cents"]
        == data["raw_allocation_cents"] - data["de_minimis_reduction_cents"]
    ), "net_liability_cents is the raw allocation less the de-minimis reduction"


def assert_payment_installment(data: dict) -> None:
    _assert_common_fields(data, "PaymentInstallment")
    assert data["status"] in ("SCHEDULED", "PAID", "MISSED", "DEFAULTED")
    assert isinstance(data["installment_number"], int)
    assert isinstance(data["amount_cents"], int)


def assert_trustee(data: dict) -> None:
    _assert_common_fields(data, "Trustee")
    assert data["appointing_party"] in ("UNION", "EMPLOYER")
    assert data["seat_status"] in ("ACTIVE", "RESIGNED")


def assert_board_motion(data: dict) -> None:
    _assert_common_fields(data, "BoardMotion")
    assert data["subject_type"] in (
        "LD_WAIVER",
        "AUDIT_SETTLEMENT",
        "RECIPROCITY_AGREEMENT",
    )
    assert data["status"] in (
        "OPEN",
        "CARRIED",
        "FAILED",
        "DEADLOCKED",
        "ARBITRATION_CARRIED",
        "ARBITRATION_FAILED",
    )


def assert_motion_vote(data: dict) -> None:
    assert_immutable_ledger_row(data, "MotionVote")
    assert data["position"] in ("FOR", "AGAINST", "ABSTAIN")


def assert_reciprocity_transfer(data: dict) -> None:
    _assert_common_fields(data, "ReciprocityTransfer")
    assert data["transfer_type"] in ("MONEY_FOLLOWS_MAN", "PRO_RATA")
    assert data["status"] in ("PENDING", "ACCEPTED", "REJECTED")
    assert isinstance(data["applied_coverage_months"], int)


def assert_employer_ledger_identity(
    employer: dict, live_reports: list, assessed_totals: list
) -> None:
    """cumulative_delinquent_cents is unpaid contributions plus ASSESSED totals.

    ``live_reports`` are the employer's reports whose filing state is not
    SUPERSEDED and whose payment state is UNPAID, PARTIAL or DELINQUENT;
    ``assessed_totals`` are the total_cents of its assessments still ASSESSED.
    """
    unpaid = sum(
        r["total_contributions_due_cents"] - r["amount_remitted_cents"]
        for r in live_reports
    )
    expected = unpaid + sum(assessed_totals)
    assert employer["cumulative_delinquent_cents"] == expected, (
        "cumulative_delinquent_cents must equal unpaid contributions plus open "
        f"assessments: expected {expected}, got "
        f"{employer['cumulative_delinquent_cents']}"
    )
