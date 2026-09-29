"""Shape validators and domain invariant checkers.

The shape validators assert the common audit fields of PRD 2.4 plus the fields
the PRD names for each resource.  The invariant checkers encode the four
conserved quantities of PRD 2.9 and the arithmetic ladders of PRD 3.5, 3.7 and
3.9 so a single call can prove a whole money identity rather than a field.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as C


# --------------------------------------------------------------------------- #
# Arithmetic helpers mirroring PRD 2.6
# --------------------------------------------------------------------------- #
def floor_div(numerator: int, denominator: int) -> int:
    """Truncating division toward zero for non-negative operands (PRD 2.6)."""
    return numerator // denominator


def round_half_up(numerator: int, denominator: int) -> int:
    """Round half away from zero: a raw 25000.5 becomes 25001, not 25000."""
    if numerator < 0:
        return -((-numerator * 2 + denominator) // (2 * denominator))
    return (numerator * 2 + denominator) // (2 * denominator)


def bps_of(amount_cents: int, bps: int) -> int:
    """Floored basis-point share of an amount."""
    return (amount_cents * bps) // 10000


# --------------------------------------------------------------------------- #
# Common audit fields (PRD 2.4)
# --------------------------------------------------------------------------- #
def assert_common_fields(entity: Dict[str, Any], *, versioned: bool = True) -> None:
    assert "id" in entity, "resource must expose an id"
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(
        entity["created_at"]
    ), f"created_at must be ISO-8601 UTC, got {entity.get('created_at')!r}"
    if versioned:
        assert is_iso8601_timestamp(
            entity["updated_at"]
        ), f"updated_at must be ISO-8601 UTC, got {entity.get('updated_at')!r}"
        assert isinstance(entity["version"], int), "version must be an integer"
        assert entity["version"] >= 1, "version starts at 1"
    else:
        assert "updated_at" not in entity, "append-only resources carry no updated_at"
        assert "version" not in entity, "append-only resources carry no version"


def assert_fields_present(entity: Dict[str, Any], field_names: List[str]) -> None:
    missing = [name for name in field_names if name not in entity]
    assert not missing, f"missing declared fields: {missing}"


# --------------------------------------------------------------------------- #
# Per-resource shape validators
# --------------------------------------------------------------------------- #
def assert_retailer(retailer: Dict[str, Any]) -> None:
    assert_common_fields(retailer)
    assert_fields_present(
        retailer,
        [
            "name",
            "chain_code",
            "total_store_count",
            "void_rate_basis_default",
            "at_risk_void_rate_bps",
            "deduction_dispute_window_days",
            "demo_changeover_buffer_minutes",
            "max_concurrent_demos",
            "review_blackout_days",
        ],
    )


def assert_principal(principal: Dict[str, Any]) -> None:
    assert_common_fields(principal)
    assert_fields_present(
        principal,
        [
            "name",
            "code",
            "status",
            "slotting_budget_cents",
            "slotting_committed_cents",
            "open_slotting_liability_cents",
            "open_deduction_cents",
            "at_risk_authorization_count",
            "liability_ratio_bps",
            "credit_posture",
        ],
    )
    assert 0 <= principal["liability_ratio_bps"] <= 10000, "basis points live in 0..10000"


def assert_agreement(agreement: Dict[str, Any]) -> None:
    assert_common_fields(agreement)
    assert_fields_present(
        agreement,
        [
            "principal_id",
            "retailer_id",
            "category_code",
            "effective_start_date",
            "effective_end_date",
            "base_commission_bps",
            "tier_threshold_cents",
            "tier_commission_bps",
            "exclusive_in_category",
            "status",
        ],
    )


def assert_conflict_rule(rule: Dict[str, Any]) -> None:
    assert_common_fields(rule)
    assert_fields_present(
        rule,
        ["category_code", "principal_a_id", "principal_b_id", "scope", "status"],
    )


def assert_item(item: Dict[str, Any]) -> None:
    assert_common_fields(item)
    assert_fields_present(
        item,
        [
            "principal_id",
            "upc",
            "description",
            "case_pack_units",
            "list_price_cents",
            "unit_cost_cents",
            "catalog_state",
            "catalog_submission_round",
        ],
    )


def assert_review(review: Dict[str, Any]) -> None:
    assert_common_fields(review)
    assert_fields_present(
        review,
        [
            "retailer_id",
            "category_code",
            "review_window_start",
            "review_window_end",
            "submission_deadline",
            "new_item_slots",
            "status",
            "slots_awarded",
            "slots_remaining",
            "reopen_count",
        ],
    )
    assert (
        review["slots_awarded"] + review["slots_remaining"] == review["new_item_slots"]
    ), "awarded plus remaining slots must equal the slot capacity"


def assert_presentation(presentation: Dict[str, Any]) -> None:
    assert_common_fields(presentation)
    assert_fields_present(
        presentation,
        [
            "review_id",
            "principal_id",
            "item_ids",
            "status",
            "authorized_item_count",
            "prep_completeness_bps",
        ],
    )
    assert 0 <= presentation["prep_completeness_bps"] <= 10000


def assert_deal(deal: Dict[str, Any]) -> None:
    assert_common_fields(deal)
    assert_fields_present(
        deal,
        [
            "presentation_id",
            "requested_fee_per_store_cents",
            "current_fee_per_store_cents",
            "store_count_in_scope",
            "item_count_in_scope",
            "forecast_annual_units",
            "amortization_periods",
            "amortization_method",
            "state",
            "round_index",
            "gross_fee_cents",
            "volume_credit_cents",
            "net_before_admin_cents",
            "admin_fee_cents",
            "quoted_fee_cents",
            "recovered_cents",
            "unamortized_balance_cents",
            "written_off_cents",
            "periods_posted",
        ],
    )


def assert_authorization(authorization: Dict[str, Any]) -> None:
    assert_common_fields(authorization)
    assert_fields_present(
        authorization,
        [
            "review_id",
            "item_id",
            "retailer_id",
            "authorization_state",
            "settlement_state",
            "void_rate_basis",
            "authorized_store_count",
            "distributed_store_count",
            "void_store_count",
            "pending_store_count",
            "void_rate_bps",
            "periods_reported",
            "slotting_share_cents",
            "promo_settled_funding_cents",
            "trade_spend_total_cents",
        ],
    )


def assert_snapshot(snapshot: Dict[str, Any]) -> None:
    """A ledger entry is append-only: no updated_at, no version (PRD 2.4)."""
    assert_common_fields(snapshot, versioned=False)
    assert_fields_present(
        snapshot,
        [
            "authorization_id",
            "period_index",
            "reported_store_count",
            "distributed_store_count",
            "reported_case_volume",
            "amortized_amount_cents",
            "entry_kind",
            "is_reversed",
            "posted_at",
        ],
    )


def assert_promotion(promotion: Dict[str, Any]) -> None:
    assert_common_fields(promotion)
    assert_fields_present(
        promotion,
        [
            "authorization_id",
            "event_type",
            "window_start",
            "window_end",
            "planned_funding_cents",
            "actual_funding_cents",
            "settled_funding_cents",
            "state",
        ],
    )


def assert_deduction(deduction: Dict[str, Any]) -> None:
    assert_common_fields(deduction)
    assert_fields_present(
        deduction,
        [
            "retailer_id",
            "principal_id",
            "reason_code",
            "amount_cents",
            "deduction_date",
            "settlement_state",
            "dispute_state",
            "claim_amount_cents",
            "recovered_cents",
            "conceded_cents",
            "open_cents",
            "substantiation_doc_count",
            "refile_count",
        ],
    )


def assert_commission_statement(statement: Dict[str, Any]) -> None:
    assert_fields_present(
        statement,
        [
            "principal_id",
            "retailer_id",
            "category_code",
            "agreement_id",
            "base_commission_bps",
            "tier_threshold_cents",
            "tier_commission_bps",
            "lines",
            "total_shipped_cents",
            "total_commission_cents",
        ],
    )


def assert_voids_report(report: Dict[str, Any]) -> None:
    assert_fields_present(
        report,
        [
            "authorization_id",
            "item_id",
            "upc",
            "retailer_id",
            "void_rate_basis",
            "authorized_store_count",
            "reported_store_count",
            "distributed_store_count",
            "void_store_count",
            "pending_store_count",
            "void_rate_bps",
            "at_risk_void_rate_bps",
            "is_at_risk",
            "counterfactual_basis",
            "counterfactual_void_rate_bps",
        ],
    )


# --------------------------------------------------------------------------- #
# Conserved quantity 1: store counts (PRD 2.9)
# --------------------------------------------------------------------------- #
def assert_store_counts_conserved(authorization: Dict[str, Any]) -> None:
    """authorized == distributed + void + pending, for every authorization."""
    total = (
        authorization["distributed_store_count"]
        + authorization["void_store_count"]
        + authorization["pending_store_count"]
    )
    assert authorization["authorized_store_count"] == total, (
        "authorized_store_count must equal distributed + void + pending, got "
        f"{authorization['authorized_store_count']} != {total}"
    )


# --------------------------------------------------------------------------- #
# Conserved quantity 2: slotting money (PRD 2.9)
# --------------------------------------------------------------------------- #
def assert_slotting_money_conserved(deal: Dict[str, Any]) -> None:
    """accepted == recovered + written_off + unamortized once a fee is accepted."""
    accepted = deal.get("accepted_fee_cents")
    if accepted is None:
        return
    total = (
        deal["recovered_cents"] + deal["written_off_cents"] + deal["unamortized_balance_cents"]
    )
    assert accepted == total, (
        "accepted_fee_cents must equal recovered + written_off + unamortized, got "
        f"{accepted} != {total}"
    )


# --------------------------------------------------------------------------- #
# Conserved quantity 3: deduction money (PRD 2.9)
# --------------------------------------------------------------------------- #
def assert_deduction_money_conserved(deduction: Dict[str, Any]) -> None:
    """amount == recovered + conceded + open, at every step of the dispute."""
    total = deduction["recovered_cents"] + deduction["conceded_cents"] + deduction["open_cents"]
    assert deduction["amount_cents"] == total, (
        "amount_cents must equal recovered + conceded + open, got "
        f"{deduction['amount_cents']} != {total}"
    )


# --------------------------------------------------------------------------- #
# Conserved quantity 4: review slots (PRD 2.9)
# --------------------------------------------------------------------------- #
def assert_review_slots_conserved(review: Dict[str, Any]) -> None:
    total = review["slots_awarded"] + review["slots_remaining"]
    assert review["new_item_slots"] == total, (
        f"new_item_slots must equal awarded + remaining, got {review['new_item_slots']} != {total}"
    )


# --------------------------------------------------------------------------- #
# Ledger identity: signed amortization sum equals recovered_cents (PRD 2.9)
# --------------------------------------------------------------------------- #
def signed_amortization_total(snapshots: List[Dict[str, Any]]) -> int:
    return sum(entry["amortized_amount_cents"] for entry in snapshots)


def assert_ledger_matches_recovered(deal: Dict[str, Any], snapshots: List[Dict[str, Any]]) -> None:
    total = signed_amortization_total(snapshots)
    assert deal["recovered_cents"] == total, (
        "recovered_cents must equal the signed sum of ledger amortization, got "
        f"{deal['recovered_cents']} != {total}"
    )


# --------------------------------------------------------------------------- #
# Quote ladder (PRD 3.5)
# --------------------------------------------------------------------------- #
def expected_gross_fee(fee_per_store_cents: int, store_count: int, item_count: int) -> int:
    return fee_per_store_cents * store_count * item_count


def expected_volume_credit(gross_fee_cents: int, forecast_annual_units: int) -> int:
    raw_credit = forecast_annual_units * C.CREDIT_PER_FORECAST_UNIT_CENTS
    cap = bps_of(gross_fee_cents, C.VOLUME_CREDIT_CAP_BPS)
    return min(raw_credit, cap)


def admin_rate_bps(net_before_admin_cents: int) -> int:
    """Tier is keyed on the post-credit net, never on the quoted fee (PRD 3.5)."""
    if net_before_admin_cents <= C.ADMIN_TIER_1_MAX_CENTS:
        return C.ADMIN_BPS_TIER_1
    return C.ADMIN_BPS_TIER_2


def expected_admin_fee(net_before_admin_cents: int) -> int:
    """Net times the tiered rate over 10,000, rounded half up (PRD 3.5 step 5)."""
    return round_half_up(net_before_admin_cents * admin_rate_bps(net_before_admin_cents), 10000)


def expected_quote(
    fee_per_store_cents: int,
    store_count: int,
    item_count: int,
    forecast_annual_units: int,
) -> Dict[str, int]:
    gross = expected_gross_fee(fee_per_store_cents, store_count, item_count)
    credit = expected_volume_credit(gross, forecast_annual_units)
    net = gross - credit
    admin = expected_admin_fee(net)
    return {
        "gross_fee_cents": gross,
        "volume_credit_cents": credit,
        "net_before_admin_cents": net,
        "admin_fee_cents": admin,
        "quoted_fee_cents": net + admin,
    }


def assert_quote_ladder(
    deal: Dict[str, Any],
    fee_per_store_cents: int,
    store_count: int,
    item_count: int,
    forecast_annual_units: int,
) -> None:
    expected = expected_quote(
        fee_per_store_cents, store_count, item_count, forecast_annual_units
    )
    for field, value in expected.items():
        assert deal[field] == value, f"{field}: expected {value}, got {deal[field]}"


# --------------------------------------------------------------------------- #
# Amortization (PRD 3.7)
# --------------------------------------------------------------------------- #
def expected_straight_amortization(
    accepted_fee_cents: int,
    periods: int,
    periods_already_posted: int = 0,
    remaining_balance_cents: Optional[int] = None,
) -> int:
    """Base share every period, with the final period truing up the flooring."""
    base = floor_div(accepted_fee_cents, periods)
    if periods_already_posted + 1 == periods:
        amount = accepted_fee_cents - base * (periods - 1)
    else:
        amount = base
    if remaining_balance_cents is not None:
        amount = min(amount, remaining_balance_cents)
    return amount


def volume_ratio_bps(forecast_annual_units: int, periods: int, reported_case_volume: int) -> int:
    """Period target is rounded up; the achieved ratio is floored then capped at 10,000."""
    target = -(-forecast_annual_units // periods)
    if target == 0:
        return 0
    return min(10000, floor_div(reported_case_volume * 10000, target))


def expected_volume_weighted_amortization(
    accepted_fee_cents: int,
    forecast_annual_units: int,
    periods: int,
    reported_case_volume: int,
    remaining_balance_cents: Optional[int] = None,
) -> int:
    ratio = volume_ratio_bps(forecast_annual_units, periods, reported_case_volume)
    amount = round_half_up(accepted_fee_cents * ratio, 10000 * periods)
    if remaining_balance_cents is not None:
        amount = min(amount, remaining_balance_cents)
    return amount


# --------------------------------------------------------------------------- #
# Void rate (PRD 3.7)
# --------------------------------------------------------------------------- #
def expected_void_rate_bps(void_store_count: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return floor_div(void_store_count * 10000, denominator)


def assert_at_risk_threshold(
    authorization: Dict[str, Any], at_risk_void_rate_bps: int
) -> None:
    """The threshold comparison is inclusive: at the threshold the item is AT_RISK."""
    is_at_risk = authorization["void_rate_bps"] >= at_risk_void_rate_bps
    expected_state = "AT_RISK" if is_at_risk else "AUTHORIZED"
    assert authorization["authorization_state"] == expected_state, (
        f"void_rate_bps {authorization['void_rate_bps']} against threshold "
        f"{at_risk_void_rate_bps} should yield {expected_state}, got "
        f"{authorization['authorization_state']}"
    )


# --------------------------------------------------------------------------- #
# Commission statement (PRD 3.2)
# --------------------------------------------------------------------------- #
def expected_line_commission(
    line_shipped_cents: int,
    tier_threshold_cents: int,
    base_bps: int,
    tier_bps: int,
    cumulative_shipped_cents: int = 0,
) -> Dict[str, int]:
    """One step of the running tier walk, rounded half up once for the whole line."""
    remaining_tier1_room = max(0, tier_threshold_cents - cumulative_shipped_cents)
    tier1_part = min(line_shipped_cents, remaining_tier1_room)
    tier2_part = line_shipped_cents - tier1_part
    commission = round_half_up(tier1_part * base_bps + tier2_part * tier_bps, 10000)
    return {
        "tier1_part_cents": tier1_part,
        "tier2_part_cents": tier2_part,
        "line_commission_cents": commission,
    }


def expected_statement_walk(
    shipped_by_line: List[int], tier_threshold_cents: int, base_bps: int, tier_bps: int
) -> Dict[str, Any]:
    """Walk lines in the given (ascending upc) order, rounding each line then summing."""
    cumulative = 0
    lines: List[Dict[str, int]] = []
    for shipped in shipped_by_line:
        line = expected_line_commission(
            shipped, tier_threshold_cents, base_bps, tier_bps, cumulative
        )
        line["line_shipped_cents"] = shipped
        lines.append(line)
        cumulative += shipped
    return {
        "lines": lines,
        "total_shipped_cents": sum(shipped_by_line),
        "total_commission_cents": sum(line["line_commission_cents"] for line in lines),
    }


def assert_statement_walk(
    statement: Dict[str, Any], tier_threshold_cents: int, base_bps: int, tier_bps: int
) -> None:
    """Re-walk the statement's own shipped figures and match every derived field."""
    assert_lines_ordered_by_upc(statement["lines"])
    expected = expected_statement_walk(
        [line["line_shipped_cents"] for line in statement["lines"]],
        tier_threshold_cents,
        base_bps,
        tier_bps,
    )
    for index, (actual, wanted) in enumerate(zip(statement["lines"], expected["lines"])):
        for field in ("tier1_part_cents", "tier2_part_cents", "line_commission_cents"):
            assert actual[field] == wanted[field], (
                f"line {index} {field}: expected {wanted[field]}, got {actual[field]}"
            )
    assert statement["total_shipped_cents"] == expected["total_shipped_cents"]
    assert statement["total_commission_cents"] == expected["total_commission_cents"]


def assert_lines_ordered_by_upc(lines: List[Dict[str, Any]]) -> None:
    upcs = [line["upc"] for line in lines]
    assert upcs == sorted(upcs), f"statement lines must be ordered by upc ascending, got {upcs}"


# --------------------------------------------------------------------------- #
# Deduction recovery (PRD 3.9)
# --------------------------------------------------------------------------- #
def expected_shortage_recovery(claim_amount_cents: int, amount_cents: int) -> int:
    """Capped by a 5,000 basis point contractual allowance (PRD 3.9)."""
    return min(claim_amount_cents, bps_of(amount_cents, C.SHORTAGE_ALLOWANCE_BPS))


def expected_promo_billback_recovery(
    claim_amount_cents: int, amount_cents: int, substantiated_funding_cents: int
) -> int:
    """Substantiated funding is conceded; only the excess is recoverable (PRD 3.9)."""
    return min(claim_amount_cents, max(0, amount_cents - substantiated_funding_cents))


def expected_duplicate_billback_recovery(claim_amount_cents: int) -> int:
    return claim_amount_cents


def expected_compliance_fine_recovery() -> int:
    return 0


# --------------------------------------------------------------------------- #
# Principal aggregates (PRD 2.9)
# --------------------------------------------------------------------------- #
def expected_liability_ratio_bps(
    open_slotting_liability_cents: int,
    open_deduction_cents: int,
    slotting_budget_cents: int,
) -> int:
    """Ratio is 0 on a zero budget; otherwise liability plus deductions over budget."""
    if slotting_budget_cents == 0:
        return 0
    numerator = (open_slotting_liability_cents + open_deduction_cents) * 10000
    return floor_div(numerator, slotting_budget_cents)


def expected_credit_posture(liability_ratio_bps: int, at_risk_authorization_count: int) -> str:
    if (
        liability_ratio_bps >= C.RESTRICTED_RATIO_BPS
        or at_risk_authorization_count >= C.RESTRICTED_AT_RISK_COUNT
    ):
        return "RESTRICTED"
    if (
        liability_ratio_bps >= C.WATCH_RATIO_BPS
        or at_risk_authorization_count >= C.WATCH_AT_RISK_COUNT
    ):
        return "WATCH"
    return "NORMAL"


def assert_principal_aggregates(principal: Dict[str, Any]) -> None:
    """Ratio and posture are derived, never stored independently (PRD 2.9)."""
    expected_ratio = expected_liability_ratio_bps(
        principal["open_slotting_liability_cents"],
        principal["open_deduction_cents"],
        principal["slotting_budget_cents"],
    )
    assert principal["liability_ratio_bps"] == expected_ratio, (
        f"liability_ratio_bps: expected {expected_ratio}, got {principal['liability_ratio_bps']}"
    )
    expected_posture = expected_credit_posture(
        principal["liability_ratio_bps"], principal["at_risk_authorization_count"]
    )
    assert principal["credit_posture"] == expected_posture, (
        f"credit_posture: expected {expected_posture}, got {principal['credit_posture']}"
    )


# --------------------------------------------------------------------------- #
# Pagination envelope (PRD 2.3)
# --------------------------------------------------------------------------- #
def assert_pagination_meta(
    body: Dict[str, Any],
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_total: Optional[int] = None,
) -> None:
    meta = body["meta"]
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"pagination meta must carry {key}"
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    if expected_total is not None:
        assert meta["total_count"] == expected_total
    assert meta["has_more"] == (
        meta["offset"] + len(body["data"]) < meta["total_count"]
    ), "has_more must reflect whether further rows remain"


def assert_ordered_by_created_at(rows: List[Dict[str, Any]]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows must be ordered by created_at ascending, got {stamps}"


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    assert before["version"] == after["version"], (
        f"version must not move: was {before['version']}, now {after['version']}"
    )


def assert_version_bumped_by(before: Dict[str, Any], after: Dict[str, Any], delta: int = 1) -> None:
    assert after["version"] == before["version"] + delta, (
        f"version must advance by {delta}: was {before['version']}, now {after['version']}"
    )
