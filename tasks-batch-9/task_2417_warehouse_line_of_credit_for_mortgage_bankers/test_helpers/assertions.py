"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    PRINCIPAL_MOVING_ENTRY_TYPES,
    AdvanceCustodyStatus,
    AdvanceFundingStatus,
    BaileeLetterStatus,
    CommitmentStatus,
    CovenantPosture,
    CovenantTestStatus,
    CustodianStatus,
    FacilityStatus,
    InvestorStatus,
    MarginCallStatus,
    ReceiptStatus,
    RepurchaseDemandStatus,
    WireInstructionStatus,
)


def _members(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_mutable_common_fields(data: dict) -> None:
    """`id`, `created_at`, `updated_at` and `version` on a mutable resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_append_only_common_fields(data: dict) -> None:
    """An append-only record carries only `id` and `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "an append-only record has no updated_at"
    assert "version" not in data, "an append-only record has no version"


# ─── Per-entity assertions ────────────────────────────────────────────────────

def assert_facility(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert isinstance(data["borrower_legal_name"], str) and data["borrower_legal_name"]
    assert data["status"] in _members(FacilityStatus)
    assert data["last_covenant_status"] in _members(CovenantPosture)
    for field in (
        "committed_amount_cents",
        "wet_sublimit_cents",
        "aged_sublimit_cents",
        "scratch_and_dent_sublimit_cents",
        "min_tangible_net_worth_cents",
        "min_liquidity_cents",
        "min_ttm_net_income_cents",
        "outstanding_principal_cents",
        "availability_cents",
        "accrued_fee_balance_cents",
        "wet_outstanding_cents",
        "aged_outstanding_cents",
        "scratch_and_dent_outstanding_cents",
        "open_margin_call_count",
        "consecutive_breach_count",
        "escalated_demand_count",
        "bailee_period_days",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["availability_cents"] >= 0, "availability_cents is never negative"
    assert len(data["settlement_account_last4"]) == 4
    assert 0 < data["max_investor_concentration_pct"] < 1
    assert data["unused_line_fee_rate"] >= 0


def assert_product_advance_rate(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["product_code"] in (
        "CONFORMING",
        "JUMBO",
        "FHA_VA",
        "NON_QM",
        "SCRATCH_AND_DENT",
    )
    assert 0 < data["advance_rate"] <= 1
    assert isinstance(data["wet_funding_allowed"], bool)
    assert 0 <= data["wet_haircut"] < data["advance_rate"]
    assert 1 <= data["dwell_limit_days"] <= 365
    assert data["aging_step_days"] >= 1
    assert 0 <= data["curtailment_step_rate"] < 1


def assert_custodian(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["custodian_name"], str) and data["custodian_name"]
    assert 1 <= data["wet_receipt_deadline_hours"] <= 240
    assert data["status"] in _members(CustodianStatus)


def assert_investor(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["investor_name"], str) and data["investor_name"]
    assert data["counterparty_rating"] in ("A", "B", "C")
    assert 0 < data["concentration_limit_pct"] <= 1
    assert data["status"] in _members(InvestorStatus)
    assert isinstance(data["exposure_cents"], int) and data["exposure_cents"] >= 0


def assert_commitment(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["investor_id"])
    assert data["status"] in _members(CommitmentStatus)
    assert data["committed_amount_cents"] > 0
    assert 0.5 < data["price_pct"] <= 1.2
    for field in (
        "allocated_amount_cents",
        "settled_amount_cents",
        "remaining_amount_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} >= 0"
    assert_commitment_capacity_conserved(data)


def assert_advance(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["custodian_id"])
    assert data["funding_status"] in _members(AdvanceFundingStatus)
    assert data["custody_status"] in _members(AdvanceCustodyStatus)
    assert data["funding_type"] in ("WET", "DRY")
    assert data["loan_amount_cents"] > 0
    assert 0 < data["note_rate"] < 0.5
    assert isinstance(data["concentration_capped"], bool)
    assert isinstance(data["is_aged"], bool)
    assert isinstance(data["dwell_days"], int) and data["dwell_days"] >= 0
    for field in (
        "market_value_cents",
        "advance_amount_cents",
        "provisional_advance_amount_cents",
        "eligible_collateral_value_cents",
        "required_paydown_cents",
        "outstanding_balance_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer count of cents"
        assert data[field] >= 0, f"{field} must not be negative"
    assert len(data["payee_account_last4"]) == 4
    assert len(data["payee_routing_last4"]) == 4


def assert_wire_instruction(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["advance_id"])
    assert data["status"] in _members(WireInstructionStatus)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert len(data["payee_account_last4"]) == 4
    assert len(data["payee_routing_last4"]) == 4


def assert_receipt(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["advance_id"])
    assert is_valid_uuid(data["custodian_id"])
    assert data["status"] in _members(ReceiptStatus)
    assert isinstance(data["document_types"], list) and data["document_types"]
    assert isinstance(data["exception_codes"], list)
    assert isinstance(data["cured_exception_codes"], list)
    assert is_iso8601_timestamp(data["received_at"])


def assert_bailee_letter(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["advance_id"])
    assert is_valid_uuid(data["investor_id"])
    assert data["status"] in _members(BaileeLetterStatus)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert 1 <= data["bailee_period_days"] <= 90


def assert_margin_call(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["status"] in _members(MarginCallStatus)
    assert data["trigger_reason"] in (
        "VALUATION_DECLINE",
        "COMMITMENT_WITHDRAWN",
        "DWELL_EXCEEDED",
        "CUSTODY_EXCEPTION",
        "COVENANT_BREACH",
    )
    assert data["call_amount_cents"] > 0, "a call whose amount works out to zero is never created"
    assert isinstance(data["cured_amount_cents"], int) and data["cured_amount_cents"] >= 0
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["cure_deadline_at"])


def assert_covenant_test(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["status"] in _members(CovenantTestStatus)
    assert data["profitability_variant"] in ("TTM_ROLLING", "ANNUALIZED_QUARTER")
    assert isinstance(data["profitability_metric_cents"], int)
    assert isinstance(data["breach_codes"], list)
    assert data["breach_codes"] == sorted(
        data["breach_codes"]
    ), "breach_codes is stored sorted"
    assert (data["status"] == "PASS") == (
        not data["breach_codes"]
    ), "status is PASS exactly when breach_codes is empty"


def assert_repurchase_demand(data: dict) -> None:
    assert_mutable_common_fields(data)
    assert is_valid_uuid(data["advance_id"])
    assert data["status"] in _members(RepurchaseDemandStatus)
    assert data["reason"] in (
        "DWELL_EXCEEDED",
        "CUSTODY_EXCEPTION_UNCURED",
        "BAILEE_EXPIRED",
        "INVESTOR_SUSPENDED",
        "INELIGIBLE_PRODUCT",
    )
    assert is_iso8601_timestamp(data["raised_at"])
    assert is_iso8601_timestamp(data["deadline_at"])


def assert_cure_payment(data: dict) -> None:
    """A cure payment is an immutable record and carries no `version`."""
    assert_append_only_common_fields(data)
    assert is_valid_uuid(data["margin_call_id"])
    assert data["amount_cents"] > 0
    assert data["applied_to_fees_cents"] >= 0
    assert data["applied_to_principal_cents"] >= 0
    assert (
        data["applied_to_fees_cents"] + data["applied_to_principal_cents"]
        == data["amount_cents"]
    ), "the two waterfall buckets exhaust the payment"
    assert isinstance(data["principal_allocation"], list)
    for row in data["principal_allocation"]:
        assert is_valid_uuid(row["advance_id"])
        assert isinstance(row["amount_cents"], int)
    assert is_iso8601_timestamp(data["applied_at"])


def assert_ledger_entry(data: dict) -> None:
    """A ledger entry is an immutable record and carries no `version`."""
    assert_append_only_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["entry_type"] in (
        "ADVANCE_FUNDED",
        "CURE_PRINCIPAL",
        "INVESTOR_PROCEEDS",
        "REPURCHASE",
        "FEE_ACCRUAL",
        "FEE_PAYMENT",
        "MARGIN_CALL_WAIVED",
    )
    assert data["direction"] in ("DEBIT", "CREDIT")
    assert (
        isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    ), "amount_cents is a magnitude that is never negative"
    assert is_iso8601_timestamp(data["posted_at"])
    assert isinstance(data["memo"], str)


def assert_aging_run_summary(data: dict) -> None:
    """The aging run returns a job summary rather than a stored entity."""
    assert is_valid_uuid(data["facility_id"])
    assert is_iso8601_timestamp(data["run_at"])
    for field in (
        "advances_evaluated",
        "margin_calls_issued",
        "bailee_letters_expired",
        "receipts_overdue",
        "repurchase_demands_raised",
        "fee_accrual_cents",
        "accrual_days",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["curtailed_advance_ids"], list)


# ─── Domain invariant checkers ────────────────────────────────────────────────

def assert_ledger_conservation(summary: dict) -> None:
    """`outstanding_principal_cents` equals debits less credits."""
    assert (
        summary["outstanding_principal_cents"]
        == summary["ledger_debit_total_cents"] - summary["ledger_credit_total_cents"]
    ), (
        "ledger invariant broken: outstanding "
        f"{summary['outstanding_principal_cents']} != "
        f"{summary['ledger_debit_total_cents']} - {summary['ledger_credit_total_cents']}"
    )


def assert_aggregation_conservation(summary: dict) -> None:
    """`outstanding_principal_cents` equals `advance_outstanding_sum_cents`."""
    assert (
        summary["outstanding_principal_cents"] == summary["advance_outstanding_sum_cents"]
    ), (
        "aggregation invariant broken: outstanding "
        f"{summary['outstanding_principal_cents']} != advance sum "
        f"{summary['advance_outstanding_sum_cents']}"
    )


def assert_both_conservation_invariants(summary: dict) -> None:
    """Both invariants the reconciliation view exposes in one call."""
    assert_ledger_conservation(summary)
    assert_aggregation_conservation(summary)


def assert_availability_projection(summary_or_facility: dict) -> None:
    """`availability_cents` is the committed line less the outstanding principal."""
    expected = max(
        0,
        summary_or_facility["committed_amount_cents"]
        - summary_or_facility["outstanding_principal_cents"],
    )
    assert summary_or_facility["availability_cents"] == expected, (
        f"availability_cents should be {expected}, got "
        f"{summary_or_facility['availability_cents']}"
    )


def assert_commitment_capacity_conserved(commitment: dict) -> None:
    """Allocated plus settled plus remaining equals the committed face amount.

    PRD 3.2 derives `remaining_amount_cents` as "the committed face amount less
    both of those", so the three buckets reconcile — except on withdrawal, where
    PRD 3.2 says "the status becomes `WITHDRAWN` and `remaining_amount_cents`
    drops to zero", deliberately breaking the identity. A `WITHDRAWN` commitment
    is therefore exempt.
    """
    if commitment["status"] == "WITHDRAWN":
        assert commitment["remaining_amount_cents"] == 0, (
            "a WITHDRAWN commitment must carry zero remaining capacity, got "
            f"{commitment['remaining_amount_cents']}"
        )
        return
    total = (
        commitment["allocated_amount_cents"]
        + commitment["settled_amount_cents"]
        + commitment["remaining_amount_cents"]
    )
    assert total == commitment["committed_amount_cents"], (
        "commitment capacity not conserved: "
        f"{commitment['allocated_amount_cents']} + "
        f"{commitment['settled_amount_cents']} + "
        f"{commitment['remaining_amount_cents']} != "
        f"{commitment['committed_amount_cents']}"
    )


def ledger_totals(entries: list) -> tuple:
    """(debit_total, credit_total) over the principal-moving entries."""
    debit = sum(
        entry["amount_cents"]
        for entry in entries
        if entry["entry_type"] in PRINCIPAL_MOVING_ENTRY_TYPES
        and entry["direction"] == "DEBIT"
    )
    credit = sum(
        entry["amount_cents"]
        for entry in entries
        if entry["entry_type"] in PRINCIPAL_MOVING_ENTRY_TYPES
        and entry["direction"] == "CREDIT"
    )
    return debit, credit


def normalize_instant(value: str) -> str:
    """An ISO 8601 UTC instant reduced to whole seconds so two forms compare."""
    assert isinstance(value, str) and value.endswith(
        "Z"
    ), f"expected a UTC instant ending in Z, got {value!r}"
    body = value[:-1]
    if "." in body:
        body = body.split(".", 1)[0]
    return body + "Z"


def assert_instant(actual: str, expected_utc: str) -> None:
    """Assert a written datetime equals the expected logical-clock instant."""
    assert normalize_instant(actual) == normalize_instant(expected_utc), (
        f"expected the instant {expected_utc}, got {actual}"
    )


def assert_ordered_by(rows: list, *fields) -> None:
    """Assert a list response is ordered ascending by the given fields."""
    keys = [tuple(row[field] for field in fields) for row in rows]
    assert keys == sorted(keys), f"rows are not ordered ascending by {fields}: {keys}"


def assert_entry_types_in_order(entries: list, expected: list) -> None:
    """Assert the ledger holds exactly these (entry_type, direction) pairs in order."""
    actual = [(entry["entry_type"], entry["direction"]) for entry in entries]
    assert actual == expected, f"expected ledger sequence {expected}, got {actual}"
