"""Domain assertion helpers.

These wrap the framework's generic assertions with the field sets this API
declares, so a test can state an expectation once instead of spelling out a
dozen dictionary lookups.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from . import constants
from .types import (
    AddressStatus,
    DataStatus,
    MortalityStatus,
)


# ---------------------------------------------------------------------------
# Generic shape helpers
# ---------------------------------------------------------------------------

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_common_fields(entity: Dict[str, Any]) -> None:
    """Assert the four fields every versioned resource carries."""
    for field in COMMON_FIELDS:
        assert field in entity, "missing common field {!r}".format(field)
    assert is_valid_uuid(entity["id"]), "id is not a UUID: {!r}".format(entity["id"])
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int) and entity["version"] >= 1, entity["version"]


def assert_ledger_entry_common_fields(entry: Dict[str, Any]) -> None:
    """A settlement entry is append-only: it carries `id` and `created_at` only."""
    assert is_valid_uuid(entry["id"]), entry["id"]
    assert is_iso8601_timestamp(entry["created_at"]), entry["created_at"]
    assert "updated_at" not in entry, "settlement entries must not expose updated_at"
    assert "version" not in entry, "settlement entries must not expose version"


def assert_fields(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert an exact value for each named field."""
    for field, value in expected.items():
        assert field in entity, "missing field {!r}".format(field)
        assert entity[field] == value, "{}: expected {!r}, got {!r}".format(
            field, value, entity[field]
        )


def assert_null_fields(entity: Dict[str, Any], *fields: str) -> None:
    """Assert each named field is present and null."""
    for field in fields:
        assert field in entity, "missing field {!r}".format(field)
        assert entity[field] is None, "{}: expected null, got {!r}".format(field, entity[field])


def assert_has_fields(entity: Dict[str, Any], fields: Iterable[str]) -> None:
    """Assert every named field is present, whatever its value."""
    missing = [field for field in fields if field not in entity]
    assert not missing, "missing fields: {}".format(", ".join(sorted(missing)))


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    assert after["version"] == before["version"], (
        "version moved from {} to {} when it should not have".format(
            before["version"], after["version"]
        )
    )


def assert_timestamps_present(entity: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert entity.get(field) is not None, "{} should be set".format(field)
        assert is_iso8601_timestamp(entity[field]), entity[field]


# ---------------------------------------------------------------------------
# Pension plan
# ---------------------------------------------------------------------------

PLAN_FIELDS = (
    "id",
    "sponsor_name",
    "plan_name",
    "plan_ein",
    "plan_status",
    "total_liability_cents",
    "plan_assets_cents",
    "service_cost_cents",
    "interest_cost_cents",
    "unrecognized_actuarial_loss_cents",
    "discount_rate_bps",
    "accounting_funded_status_bp",
    "participant_liability_total_cents",
    "amendment_scope",
    "amendment_adopted_at",
    "amendment_effective_date",
    "cumulative_settlement_charge_cents",
    "deferred_settlement_charge_cents",
    "filing_reference",
    "filing_submitted_at",
    "filing_deficiency_reason",
    "residual_effective_at",
    "terminated_at",
    "created_at",
    "updated_at",
    "version",
)


def assert_plan_shape(plan: Dict[str, Any]) -> None:
    assert_common_fields(plan)
    assert_has_fields(plan, PLAN_FIELDS)


def assert_funded_status_consistent(plan: Dict[str, Any]) -> None:
    """The plan's reported funded status must equal assets over liability in bp."""
    expected = constants.funded_status_bp(
        plan["plan_assets_cents"], plan["total_liability_cents"]
    )
    assert plan["accounting_funded_status_bp"] == expected, (
        "accounting_funded_status_bp {} does not match {} derived from "
        "assets {} over liability {}".format(
            plan["accounting_funded_status_bp"],
            expected,
            plan["plan_assets_cents"],
            plan["total_liability_cents"],
        )
    )


FUNDED_STATUS_FIELDS = (
    "accounting_funded_status_bp",
    "settlement_basis_liability_cents",
    "settlement_funded_status_bp",
    "participant_liability_total_cents",
    "unfunded_settlement_gap_cents",
    "cumulative_settlement_charge_cents",
    "deferred_settlement_charge_cents",
)


def assert_funded_status_shape(view: Dict[str, Any]) -> None:
    assert_has_fields(view, FUNDED_STATUS_FIELDS)


# ---------------------------------------------------------------------------
# De-risking strategy
# ---------------------------------------------------------------------------

STRATEGY_FIELDS = (
    "id",
    "plan_id",
    "strategy_type",
    "strategy_label",
    "ldi_hedge_ratio_bp",
    "strategy_status",
    "projected_accounting_cost_cents",
    "projected_settlement_cost_cents",
    "projected_basis_gap_cents",
    "in_scope_participant_count",
    "submitted_by_user_id",
    "decided_by_user_id",
    "revision_count",
    "decision_rationale",
    "created_at",
    "updated_at",
    "version",
)


def assert_strategy_shape(strategy: Dict[str, Any]) -> None:
    assert_common_fields(strategy)
    assert_has_fields(strategy, STRATEGY_FIELDS)


def assert_projections_cleared(strategy: Dict[str, Any]) -> None:
    assert_null_fields(
        strategy,
        "projected_accounting_cost_cents",
        "projected_settlement_cost_cents",
        "projected_basis_gap_cents",
    )
    assert strategy["in_scope_participant_count"] == 0, strategy["in_scope_participant_count"]


def assert_basis_gap_consistent(strategy: Dict[str, Any]) -> None:
    """The basis gap is the settlement projection less the accounting projection."""
    assert (
        strategy["projected_basis_gap_cents"]
        == strategy["projected_settlement_cost_cents"]
        - strategy["projected_accounting_cost_cents"]
    ), strategy


# ---------------------------------------------------------------------------
# Participant record
# ---------------------------------------------------------------------------

PARTICIPANT_FIELDS = (
    "id",
    "plan_id",
    "tranche_id",
    "participant_reference",
    "cohort",
    "date_of_birth",
    "stated_monthly_benefit_cents",
    "final_average_monthly_earnings_cents",
    "credited_service_months",
    "audited_monthly_benefit_cents",
    "participant_status",
    "mortality_status",
    "address_status",
    "address_search_tier",
    "address_search_attempts",
    "confirmed_address_line1",
    "confirmed_postal_code",
    "date_of_death",
    "benefit_audit_status",
    "data_confidence_score",
    "data_status",
    "accounting_liability_cents",
    "settlement_liability_cents",
    "created_at",
    "updated_at",
    "version",
)


def assert_participant_shape(participant: Dict[str, Any]) -> None:
    assert_common_fields(participant)
    assert_has_fields(participant, PARTICIPANT_FIELDS)


def effective_monthly_benefit(participant: Dict[str, Any]) -> int:
    """The audited benefit when one exists, otherwise the stated benefit."""
    audited = participant.get("audited_monthly_benefit_cents")
    if audited is None:
        return participant["stated_monthly_benefit_cents"]
    return audited


def assert_participant_liabilities_consistent(participant: Dict[str, Any]) -> None:
    """Both liabilities must equal the cohort factor applied to the effective benefit.

    A confirmed death zeroes both figures with no further arithmetic.
    """
    if participant["mortality_status"] == MortalityStatus.DECEASED_CONFIRMED.value:
        assert_fields(
            participant, accounting_liability_cents=0, settlement_liability_cents=0
        )
        return
    benefit = effective_monthly_benefit(participant)
    cohort = participant["cohort"]
    assert participant["accounting_liability_cents"] == constants.accounting_liability(
        benefit, cohort
    ), participant
    assert participant["settlement_liability_cents"] == constants.settlement_liability(
        benefit, cohort
    ), participant


def assert_data_confidence_consistent(participant: Dict[str, Any]) -> None:
    """The score must equal 100 less each applicable deduction, and gate `data_status`."""
    expected = constants.data_confidence_for(
        participant["address_status"],
        participant["mortality_status"],
        participant["benefit_audit_status"],
    )
    assert participant["data_confidence_score"] == expected, (
        "data_confidence_score {} does not match {} derived from address {}, "
        "mortality {}, audit {}".format(
            participant["data_confidence_score"],
            expected,
            participant["address_status"],
            participant["mortality_status"],
            participant["benefit_audit_status"],
        )
    )
    expected_status = constants.data_status_for(expected)
    assert participant["data_status"] == expected_status, participant["data_status"]


def assert_participant_is_clean(participant: Dict[str, Any]) -> None:
    assert_fields(
        participant,
        data_status=DataStatus.CLEAN.value,
        address_status=AddressStatus.CONFIRMED.value,
    )
    assert participant["mortality_status"] != MortalityStatus.UNVERIFIED.value, participant
    assert (
        participant["data_confidence_score"] >= constants.DATA_CONFIDENCE_CLEAN_MIN
    ), participant["data_confidence_score"]


# ---------------------------------------------------------------------------
# Benefit audit
# ---------------------------------------------------------------------------

AUDIT_FIELDS = (
    "id",
    "participant_id",
    "audit_basis",
    "audit_sequence",
    "stated_monthly_benefit_cents",
    "recomputed_monthly_benefit_cents",
    "variance_cents",
    "audit_status",
    "resolution",
    "override_rationale",
    "reopened_by_complaint_id",
    "created_at",
    "updated_at",
    "version",
)


def assert_audit_shape(audit: Dict[str, Any]) -> None:
    assert_common_fields(audit)
    assert_has_fields(audit, AUDIT_FIELDS)


def assert_audit_arithmetic(audit: Dict[str, Any], fame_cents: int, months: int) -> None:
    """The recomputation and the variance must both be independently reproducible."""
    expected_recomputed = constants.recomputed_monthly_benefit(fame_cents, months)
    assert audit["recomputed_monthly_benefit_cents"] == expected_recomputed, audit
    assert (
        audit["variance_cents"]
        == audit["stated_monthly_benefit_cents"] - audit["recomputed_monthly_benefit_cents"]
    ), audit


# ---------------------------------------------------------------------------
# Lump sum window and elections
# ---------------------------------------------------------------------------

WINDOW_FIELDS = (
    "id",
    "plan_id",
    "window_label",
    "opens_at",
    "closes_at",
    "eligibility_max_lump_sum_cents",
    "lump_sum_cap_cents",
    "window_status",
    "notice_count",
    "approved_lump_sum_total_cents",
    "paid_lump_sum_total_cents",
    "opened_at",
    "closed_at",
    "settled_at",
    "created_at",
    "updated_at",
    "version",
)

ELECTION_FIELDS = (
    "id",
    "window_id",
    "participant_id",
    "election_status",
    "notice_sent_at",
    "notice_estimated_lump_sum_cents",
    "election_choice",
    "elected_at",
    "raw_pv_cents",
    "admin_fee_bp",
    "admin_fee_cents",
    "net_lump_sum_cents",
    "revocation_count",
    "paid_at",
    "paid_amount_cents",
    "created_at",
    "updated_at",
    "version",
)


def assert_window_shape(window: Dict[str, Any]) -> None:
    assert_common_fields(window)
    assert_has_fields(window, WINDOW_FIELDS)


def assert_election_shape(election: Dict[str, Any]) -> None:
    assert_common_fields(election)
    assert_has_fields(election, ELECTION_FIELDS)


def assert_election_pricing(election: Dict[str, Any], expected_raw_pv_cents: int) -> None:
    """Pin the whole fee chain: raw present value, tier, fee and net amount."""
    assert election["raw_pv_cents"] == expected_raw_pv_cents, election
    assert election["admin_fee_bp"] == constants.admin_fee_bp_for(expected_raw_pv_cents), election
    assert election["admin_fee_cents"] == constants.admin_fee_cents_for(
        expected_raw_pv_cents
    ), election
    assert election["net_lump_sum_cents"] == constants.net_lump_sum_cents_for(
        expected_raw_pv_cents
    ), election
    assert (
        election["net_lump_sum_cents"]
        == election["raw_pv_cents"] - election["admin_fee_cents"]
    ), election


def assert_election_pricing_cleared(election: Dict[str, Any]) -> None:
    assert_null_fields(
        election,
        "election_choice",
        "elected_at",
        "raw_pv_cents",
        "admin_fee_bp",
        "admin_fee_cents",
        "net_lump_sum_cents",
    )


# ---------------------------------------------------------------------------
# Buyout tranche
# ---------------------------------------------------------------------------

TRANCHE_FIELDS = (
    "id",
    "plan_id",
    "tranche_label",
    "target_cohort",
    "tranche_status",
    "assigned_participant_count",
    "accounting_liability_cents",
    "settlement_liability_cents",
    "data_readiness_flag",
    "selection_basis",
    "selected_quote_id",
    "selected_insurer_id",
    "selection_score_bp",
    "locked_premium_cents",
    "lock_start_at",
    "lock_expires_at",
    "transfer_expense_cents",
    "settlement_gain_loss_cents",
    "settled_at",
    "abandoned_at",
    "abandonment_reason",
    "created_at",
    "updated_at",
    "version",
)

TRANCHE_SELECTION_FIELDS = (
    "selection_basis",
    "selected_quote_id",
    "selected_insurer_id",
    "selection_score_bp",
)

TRANCHE_LOCK_FIELDS = ("locked_premium_cents", "lock_start_at", "lock_expires_at")


def assert_tranche_shape(tranche: Dict[str, Any]) -> None:
    assert_common_fields(tranche)
    assert_has_fields(tranche, TRANCHE_FIELDS)


def assert_tranche_selection_cleared(tranche: Dict[str, Any]) -> None:
    assert_null_fields(tranche, *TRANCHE_SELECTION_FIELDS)


def assert_tranche_lock_cleared(tranche: Dict[str, Any]) -> None:
    assert_null_fields(tranche, *TRANCHE_LOCK_FIELDS)


# ---------------------------------------------------------------------------
# Insurer and quotes
# ---------------------------------------------------------------------------

INSURER_FIELDS = (
    "id",
    "insurer_name",
    "rating_grade",
    "capital_ratio_bp",
    "state_guaranty_coverage_cents",
    "capacity_cents",
    "committed_capacity_cents",
    "available_capacity_cents",
    "insurer_status",
    "rating_changed_at",
    "created_at",
    "updated_at",
    "version",
)

QUOTE_FIELDS = (
    "id",
    "tranche_id",
    "insurer_id",
    "quote_status",
    "requested_at",
    "premium_cents",
    "lock_days",
    "quote_valid_days",
    "submitted_at",
    "expires_at",
    "rating_at_submission",
    "composite_score_bp",
    "decline_reason",
    "created_at",
    "updated_at",
    "version",
)


def assert_insurer_shape(insurer: Dict[str, Any]) -> None:
    assert_common_fields(insurer)
    assert_has_fields(insurer, INSURER_FIELDS)


def assert_quote_shape(quote: Dict[str, Any]) -> None:
    assert_common_fields(quote)
    assert_has_fields(quote, QUOTE_FIELDS)


def assert_capacity_conserved(insurer: Dict[str, Any]) -> None:
    """Committed plus available capacity must always equal total capacity."""
    assert (
        insurer["committed_capacity_cents"] + insurer["available_capacity_cents"]
        == insurer["capacity_cents"]
    ), (
        "committed {} + available {} != capacity {}".format(
            insurer["committed_capacity_cents"],
            insurer["available_capacity_cents"],
            insurer["capacity_cents"],
        )
    )


def assert_capacity(
    insurer: Dict[str, Any], committed_cents: int, available_cents: int
) -> None:
    assert_fields(
        insurer,
        committed_capacity_cents=committed_cents,
        available_capacity_cents=available_cents,
    )
    assert_capacity_conserved(insurer)


def assert_composite_score(
    quote: Dict[str, Any],
    selection_basis: str,
    rating_grade: str,
    capital_ratio_bp: int,
    lowest_premium_cents: int,
) -> None:
    """The composite score must equal the weighted sum of the three point terms."""
    expected = constants.composite_score_bp(
        selection_basis,
        rating_grade,
        capital_ratio_bp,
        lowest_premium_cents,
        quote["premium_cents"],
    )
    assert quote["composite_score_bp"] == expected, (
        "composite_score_bp {} does not match {} derived under {}".format(
            quote["composite_score_bp"], expected, selection_basis
        )
    )


# ---------------------------------------------------------------------------
# Independent expert
# ---------------------------------------------------------------------------

EXPERT_FIELDS = (
    "id",
    "plan_id",
    "expert_firm_name",
    "conflict_disclosed",
    "expert_status",
    "proposed_by_user_id",
    "reviewed_by_user_id",
    "safest_available_opinion",
    "opinion_issued_at",
    "created_at",
    "updated_at",
    "version",
)


def assert_expert_shape(expert: Dict[str, Any]) -> None:
    assert_common_fields(expert)
    assert_has_fields(expert, EXPERT_FIELDS)


# ---------------------------------------------------------------------------
# Asset transfer
# ---------------------------------------------------------------------------

TRANSFER_FIELDS = (
    "id",
    "tranche_id",
    "transfer_mode",
    "in_kind_market_value_cents",
    "in_kind_lot_count",
    "cash_amount_cents",
    "gross_value_cents",
    "credited_value_cents",
    "transfer_expense_cents",
    "shortfall_cents",
    "transfer_status",
    "insurer_decision",
    "rejection_reason",
    "settled_at",
    "created_at",
    "updated_at",
    "version",
)


def assert_transfer_shape(transfer: Dict[str, Any]) -> None:
    assert_common_fields(transfer)
    assert_has_fields(transfer, TRANSFER_FIELDS)


def assert_in_kind_crediting(transfer: Dict[str, Any]) -> None:
    """In-kind expense is the haircut plus per-lot custody fees."""
    expected_expense = constants.in_kind_transfer_expense(
        transfer["gross_value_cents"], transfer["in_kind_lot_count"]
    )
    assert transfer["transfer_expense_cents"] == expected_expense, transfer
    assert (
        transfer["credited_value_cents"]
        == transfer["gross_value_cents"] - expected_expense
    ), transfer


def assert_cash_crediting(transfer: Dict[str, Any]) -> None:
    """Cash expense is the wire fee alone."""
    expected_expense = constants.cash_transfer_expense(transfer["gross_value_cents"])
    assert transfer["transfer_expense_cents"] == expected_expense, transfer
    assert (
        transfer["credited_value_cents"]
        == transfer["gross_value_cents"] - expected_expense
    ), transfer


# ---------------------------------------------------------------------------
# Settlement entries
# ---------------------------------------------------------------------------

SETTLEMENT_ENTRY_FIELDS = (
    "id",
    "plan_id",
    "tranche_id",
    "window_id",
    "entry_type",
    "amount_cents",
    "deferred_amount_cents",
    "gain_loss_cents",
    "pbo_settled_cents",
    "source_reference",
    "posted_at",
    "created_at",
)


def assert_settlement_entry_shape(entry: Dict[str, Any]) -> None:
    assert_ledger_entry_common_fields(entry)
    assert_has_fields(entry, SETTLEMENT_ENTRY_FIELDS)
    assert is_iso8601_timestamp(entry["posted_at"]), entry["posted_at"]


def entries_of_type(entries: Sequence[Dict[str, Any]], entry_type: str) -> List[Dict[str, Any]]:
    return [entry for entry in entries if entry["entry_type"] == entry_type]


def assert_single_entry_of_type(
    entries: Sequence[Dict[str, Any]], entry_type: str
) -> Dict[str, Any]:
    matches = entries_of_type(entries, entry_type)
    assert len(matches) == 1, "expected exactly one {} entry, found {}".format(
        entry_type, len(matches)
    )
    return matches[0]


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------

COMPLAINT_FIELDS = (
    "id",
    "participant_id",
    "tranche_id",
    "complaint_reference",
    "complaint_category",
    "complaint_detail",
    "complaint_status",
    "responsibility_determination",
    "determination_rationale",
    "remediation_amount_cents",
    "reversed_amount_cents",
    "triage_count",
    "resolved_at",
    "created_at",
    "updated_at",
    "version",
)


def assert_complaint_shape(complaint: Dict[str, Any]) -> None:
    assert_common_fields(complaint)
    assert_has_fields(complaint, COMPLAINT_FIELDS)


# ---------------------------------------------------------------------------
# Listing helpers
# ---------------------------------------------------------------------------


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def find_by_id(rows: Iterable[Dict[str, Any]], row_id: str) -> Optional[Dict[str, Any]]:
    for row in rows:
        if row["id"] == row_id:
            return row
    return None


def require_by_id(rows: Iterable[Dict[str, Any]], row_id: str) -> Dict[str, Any]:
    row = find_by_id(rows, row_id)
    assert row is not None, "row {} not present in listing".format(row_id)
    return row
