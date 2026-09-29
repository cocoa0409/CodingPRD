"""Shape and invariant assertions for the eleven resource types.

Every resource carries an opaque `id` and a `created_at` timestamp. All of them
except a lifecycle reserve transaction also carry `updated_at` and an integer
`version`; a reserve transaction is append-only and is never updated, so it
carries neither.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(entity: dict) -> None:
    """Assert the identifier and audit-timestamp block every resource carries."""
    assert "id" in entity, "resource is missing its id"
    assert is_valid_uuid(entity["id"]), f"id is not an opaque UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not an ISO 8601 UTC timestamp: {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not an ISO 8601 UTC timestamp: {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"


def assert_append_only_fields(entity: dict) -> None:
    """Assert the reduced field block of a resource that is never updated."""
    assert "id" in entity, "resource is missing its id"
    assert is_valid_uuid(entity["id"]), f"id is not an opaque UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not an ISO 8601 UTC timestamp: {entity['created_at']!r}"
    )
    assert "updated_at" not in entity, "an append-only row carries no updated_at"
    assert "version" not in entity, "an append-only row carries no version"


def _require(entity: dict, fields) -> None:
    missing = [f for f in fields if f not in entity]
    assert not missing, f"response is missing fields {missing}"


def assert_concessionaire(entity: dict) -> None:
    assert_common_fields(entity)
    _require(
        entity,
        [
            "legal_name",
            "sponsor_equity_commitment_cents",
            "status",
            "concessions_count",
        ],
    )
    assert entity["status"] in ("ACTIVE", "STEPPED_IN", "WOUND_UP")
    assert isinstance(entity["sponsor_equity_commitment_cents"], int)
    assert isinstance(entity["concessions_count"], int)


def assert_concession(entity: dict) -> None:
    assert_common_fields(entity)
    _require(
        entity,
        [
            "project_name",
            "concessionaire_id",
            "status",
            "masp_cents",
            "indexation_pct",
            "deduction_cap_pct",
            "total_project_cost_cents",
            "senior_debt_committed_cents",
            "equity_committed_cents",
            "base_case_equity_irr_bps",
            "scheduled_service_commencement",
            "ld_daily_rate_cents",
            "ld_cap_cents",
            "lifecycle_reserve_target_cents",
            "senior_debt_drawn_cents",
            "equity_drawn_cents",
            "cumulative_drawn_pct",
            "ld_accrued_cents",
            "lifecycle_reserve_balance_cents",
            "availability_deduction_ytd_cents",
            "deduction_points_ytd",
            "persistent_breach_flag",
            "handback_status",
        ],
    )
    assert entity["status"] in (
        "DRAFTED",
        "FINANCIAL_CLOSE",
        "CONSTRUCTION",
        "OPERATIONS",
        "STEP_IN",
        "TERMINATED",
    )
    assert entity["handback_status"] in ("NOT_SURVEYED", "CERTIFIED", "FAILED")
    assert isinstance(entity["persistent_breach_flag"], bool)


def assert_drawdown_milestone(entity: dict) -> None:
    assert_common_fields(entity)
    _require(
        entity,
        [
            "concession_id",
            "sequence_no",
            "milestone_name",
            "requested_amount_cents",
            "status",
        ],
    )
    assert entity["status"] in ("REQUESTED", "APPROVED", "REJECTED", "DISBURSED")
    assert isinstance(entity["sequence_no"], int)
    assert entity["sequence_no"] >= 1


def assert_service_period(entity: dict) -> None:
    assert_common_fields(entity)
    _require(
        entity,
        [
            "concession_id",
            "period_index",
            "period_start",
            "period_end",
            "days_in_period",
            "reporting_status",
            "payment_status",
            "gross_unitary_charge_cents",
            "deduction_cap_cents",
            "deduction_points_total",
            "total_deduction_cents",
            "relief_credit_cents",
            "net_payment_cents",
        ],
    )
    assert entity["reporting_status"] in ("PENDING", "SELF_REPORTED", "VERIFIED")
    assert entity["payment_status"] in ("UNBILLED", "INVOICED", "PAID", "ADJUSTED")


def assert_performance_report(entity: dict) -> None:
    assert_common_fields(entity)
    _require(
        entity,
        [
            "service_period_id",
            "unavailable_minutes",
            "category_a_failures",
            "category_b_failures",
            "reported_points",
            "status",
            "submitted_at",
        ],
    )
    assert entity["status"] in ("SUBMITTED", "VERIFIED", "REJECTED", "SUPERSEDED")


def assert_deduction_event(entity: dict) -> None:
    assert_common_fields(entity)
    _require(
        entity,
        [
            "service_period_id",
            "sequence_no",
            "deduction_type",
            "points",
            "raw_amount_cents",
            "allowed_amount_cents",
            "pro_rata_amount_cents",
            "status",
            "issued_by_user_id",
            "issued_at",
        ],
    )
    assert entity["deduction_type"] in (
        "UNAVAILABILITY",
        "PERFORMANCE_FAILURE",
        "SELF_REPORT_UNDERSTATEMENT",
        "HANDBACK_SHORTFALL",
    )
    assert entity["status"] in ("ISSUED", "DISPUTED", "OVERTURNED", "WITHDRAWN")


def assert_deduction_dispute(entity: dict) -> None:
    assert_common_fields(entity)
    _require(
        entity,
        ["deduction_event_id", "raised_by_user_id", "grounds", "round_no", "status"],
    )
    assert entity["status"] in (
        "RAISED",
        "REFERRED_BACK",
        "RESUBMITTED",
        "UPHELD",
        "REJECTED",
    )
    assert 1 <= entity["round_no"] <= 3


def assert_relief_claim(entity: dict) -> None:
    assert_common_fields(entity)
    _require(
        entity,
        [
            "concession_id",
            "claim_type",
            "event_start",
            "event_end",
            "notified_at",
            "claimed_relief_days",
            "claimed_cost_cents",
            "status",
        ],
    )
    assert entity["claim_type"] in (
        "RELIEF_EVENT",
        "COMPENSATION_EVENT",
        "CHANGE_IN_LAW",
    )
    assert entity["status"] in (
        "NOTIFIED",
        "GRANTED",
        "PARTIALLY_GRANTED",
        "REJECTED",
    )


def assert_reserve_transaction(entity: dict) -> None:
    """A reserve transaction is append-only: no updated_at and no version."""
    assert_append_only_fields(entity)
    _require(
        entity,
        [
            "concession_id",
            "sequence_no",
            "txn_type",
            "amount_cents",
            "signed_amount_cents",
            "reason",
            "resulting_balance_cents",
            "created_by_role",
        ],
    )
    assert entity["txn_type"] in (
        "CONTRIBUTION",
        "WITHDRAWAL",
        "HANDBACK_TOPUP",
        "REVERSAL",
    )
    assert entity["amount_cents"] > 0, "a ledger row records a positive magnitude"


def assert_refinancing_event(entity: dict) -> None:
    assert_common_fields(entity)
    _require(
        entity,
        [
            "concession_id",
            "refinancing_date",
            "new_senior_debt_cents",
            "outstanding_senior_debt_cents",
            "refinancing_cost_cents",
            "gross_gain_cents",
            "tier_pct_applied",
            "authority_share_cents",
            "concessionaire_share_cents",
            "reserve_sweep_cents",
            "proposed_by_user_id",
            "status",
        ],
    )
    assert entity["status"] in ("PROPOSED", "CONSENTED", "REJECTED")


def assert_enforcement_action(entity: dict) -> None:
    assert_common_fields(entity)
    _require(
        entity,
        [
            "concession_id",
            "action_type",
            "trigger_reason",
            "initiated_by_role",
            "effective_date",
            "status",
        ],
    )
    assert entity["action_type"] in ("STEP_IN", "TERMINATION")
    assert entity["trigger_reason"] in (
        "PERSISTENT_BREACH",
        "LENDER_DEFAULT_CURE",
        "AUTHORITY_VOLUNTARY",
        "CONCESSIONAIRE_DEFAULT",
        "AUTHORITY_DEFAULT",
        "FORCE_MAJEURE",
    )
    assert entity["status"] in (
        "NOTIFIED",
        "STEP_IN_ACTIVE",
        "CURED",
        "LAPSED",
        "COMPENSATION_CALCULATED",
        "SETTLED",
    )


# --- Domain invariants -------------------------------------------------------


def assert_net_payment_identity(period: dict) -> None:
    """Net payable is the gross charge less deductions plus the relief credit."""
    expected = (
        period["gross_unitary_charge_cents"]
        - period["total_deduction_cents"]
        + period["relief_credit_cents"]
    )
    assert period["net_payment_cents"] == expected, (
        "net_payment_cents must equal gross - total deduction + relief credit: "
        f"{period['net_payment_cents']} != {expected}"
    )


def assert_deduction_within_cap(period: dict) -> None:
    """Deductions charged to one period never exceed that period's own cap."""
    assert period["total_deduction_cents"] <= period["deduction_cap_cents"], (
        f"total_deduction_cents {period['total_deduction_cents']} exceeds the "
        f"period cap {period['deduction_cap_cents']}"
    )


def assert_ledger_running_balance(rows: list) -> None:
    """Each ledger row's resulting balance is the signed running total to that row."""
    running = 0
    for index, row in enumerate(rows):
        assert row["sequence_no"] == index + 1, (
            f"ledger sequence_no is not contiguous from 1: {row['sequence_no']} "
            f"at position {index + 1}"
        )
        running += row["signed_amount_cents"]
        assert row["resulting_balance_cents"] == running, (
            f"resulting_balance_cents {row['resulting_balance_cents']} is not the "
            f"running total {running} at sequence_no {row['sequence_no']}"
        )


def assert_signed_amount_direction(row: dict) -> None:
    """Withdrawals reduce the balance; contributions and top-ups increase it."""
    if row["txn_type"] == "WITHDRAWAL":
        assert row["signed_amount_cents"] == -row["amount_cents"], (
            "a withdrawal must carry a negative signed amount"
        )
    elif row["txn_type"] in ("CONTRIBUTION", "HANDBACK_TOPUP"):
        assert row["signed_amount_cents"] == row["amount_cents"], (
            "a contribution or top-up must carry a positive signed amount"
        )


def assert_drawdown_split_sums(milestone: dict) -> None:
    """A milestone's equity and debt portions add up to its certified cost."""
    assert (
        milestone["equity_portion_cents"] + milestone["debt_portion_cents"]
        == milestone["certified_cost_cents"]
    ), "equity_portion + debt_portion must equal certified_cost"


def assert_gain_share_sums(event: dict) -> None:
    """The authority and concessionaire shares partition the gross gain."""
    assert (
        event["authority_share_cents"] + event["concessionaire_share_cents"]
        == event["gross_gain_cents"]
    ), "authority_share + concessionaire_share must equal gross_gain"


def assert_pagination_meta(meta: dict, expected_total: int) -> None:
    """Collection metadata reports the total matching rows before pagination."""
    assert meta["total_count"] == expected_total, (
        f"total_count {meta['total_count']} != expected {expected_total}"
    )
    assert isinstance(meta["has_more"], bool)
    assert meta["has_more"] == (
        meta["offset"] + meta["limit"] < meta["total_count"]
    ), "has_more must say whether further rows follow this window"
