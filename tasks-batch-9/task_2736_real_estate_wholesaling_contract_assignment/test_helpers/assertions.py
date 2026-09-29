"""
Entity-shape assertions, arithmetic helpers and domain invariant checkers.

The arithmetic helpers reproduce the two rounding operations the PRD defines —
rounding half up to a whole cent, and flooring toward negative infinity — so
that invariant checkers can recompute a derived figure rather than restating a
literal.
"""

from decimal import ROUND_HALF_UP, Decimal
from math import floor
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import (
    AGGRESSIVE_ARV_MULTIPLIER,
    CLOSING_COST_GROSS_UP_RATE,
    COMPLIANCE_HOLD_THRESHOLD,
    CONSERVATIVE_ARV_MULTIPLIER,
    CONTINGENCY_MULTIPLIER,
    DISTANCE_MAX_MILES,
    EQUITY_FLOOR_PCT,
    FEE_CAP_PCT_BY_TIER,
    GLA_BAND_MULTIPLIER,
    GLA_BAND_NUMERATOR,
    HIGH_EQUITY_PCT,
    LIVE_OFFER_STATUSES,
    MARKETING_RECOVERY_RATE,
    MIN_ASSIGNMENT_MARGIN_CENTS,
    PRIORITY_TIER_MIN_AVAILABLE_CENTS,
    RECENCY_MAX_DAYS,
    RECENCY_WEIGHT_BASE,
    SELLER_CLOSING_COST_PCT,
    STATE_TRANSFER_SURCHARGE_RATE,
    TIER_1_CEILING_CENTS,
    TIER_1_MIN_FEE_CENTS,
    TIER_1_RATE,
    TIER_2_CEILING_CENTS,
    TIER_2_MIN_FEE_CENTS,
    TIER_2_RATE,
    TIER_3_MIN_FEE_CENTS,
    TIER_3_RATE,
    TITLE_HOLDBACK_RATE,
)
from .types import DISCLOSURE_ACKNOWLEDGEMENT_FIELDS

Record = Dict[str, Any]


# ---------------------------------------------------------------------------
# Rounding discipline
# ---------------------------------------------------------------------------


def round_half_up(value) -> int:
    """
    Quantize to a whole unit such that a value exactly halfway between two
    units goes to the larger magnitude away from zero.
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_places(value, places: int) -> Decimal:
    """Round half up to a fixed number of decimal places, in full precision."""
    exponent = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(exponent, rounding=ROUND_HALF_UP)


def floor_to_int(value) -> int:
    """Mathematical floor toward negative infinity."""
    return floor(Decimal(str(value)))


def apply_rate(amount: int, rate: float) -> int:
    """Apply a rate to an integer amount and quantize to cents, half up."""
    return round_half_up(Decimal(str(amount)) * Decimal(str(rate)))


# ---------------------------------------------------------------------------
# Envelope-level field assertions
# ---------------------------------------------------------------------------


def assert_identity(record: Record, label: str = "record") -> None:
    """Every record's id is a server-minted UUID and carries a created_at."""
    assert is_valid_uuid(record.get("id")), f"{label}.id must be a UUID, got {record.get('id')!r}"
    assert is_iso8601_timestamp(record.get("created_at")), (
        f"{label}.created_at must be an ISO 8601 instant, got {record.get('created_at')!r}"
    )


def assert_versioned(record: Record, label: str = "record", version: Optional[int] = None) -> None:
    """
    Almost every record carries updated_at and an integer version that starts
    at 1 and increments by one on every mutation.
    """
    assert_identity(record, label)
    assert is_iso8601_timestamp(record.get("updated_at")), (
        f"{label}.updated_at must be an ISO 8601 instant, got {record.get('updated_at')!r}"
    )
    assert isinstance(record.get("version"), int), f"{label}.version must be an integer"
    assert record["version"] >= 1, f"{label}.version must start at 1"
    if version is not None:
        assert record["version"] == version, (
            f"{label}.version expected {version}, got {record['version']}"
        )


def assert_instant(actual: Optional[str], expected: Optional[str], label: str) -> None:
    """Compare two ISO 8601 UTC instants irrespective of sub-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label} expected {expected!r}, got {actual!r}"
    )


def assert_fields(record: Record, label: str = "record", **expected: Any) -> None:
    """Assert a subset of a record's fields equal the given values."""
    for key, want in expected.items():
        assert key in record, f"{label} is missing field {key!r}"
        got = record[key]
        if isinstance(want, str) and isinstance(got, str) and canonical_instant(want) != want:
            assert canonical_instant(got) == canonical_instant(want), (
                f"{label}.{key} expected {want!r}, got {got!r}"
            )
        else:
            assert got == want, f"{label}.{key} expected {want!r}, got {got!r}"


def assert_nulls(record: Record, *fields: str, label: str = "record") -> None:
    """Assert each named field is present and null."""
    for field in fields:
        assert field in record, f"{label} is missing field {field!r}"
        assert record[field] is None, (
            f"{label}.{field} expected null, got {record[field]!r}"
        )


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """The meta block of every list response echoes the window it applied."""
    if limit is not None:
        assert meta["limit"] == limit, f"meta.limit expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, (
            f"meta.offset expected {offset}, got {meta['offset']}"
        )
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"meta.total_count expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"meta.has_more expected {has_more}, got {meta['has_more']}"
        )


def assert_created_at_ascending(records: Sequence[Record]) -> None:
    """Results are ordered by created_at ascending."""
    stamps = [canonical_instant(r["created_at"]) for r in records]
    assert stamps == sorted(stamps), f"records are not ordered by created_at: {stamps}"


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------

_WHOLESALER_FIELDS = (
    "legal_name",
    "state_code",
    "disclosure_template_version",
    "licensure_status",
    "funding_window_capacity",
    "adverse_finding_count",
    "compliance_hold",
    "executed_assignment_count",
)


def assert_wholesaler(record: Record, **expected: Any) -> None:
    assert_versioned(record, "wholesaler")
    for field in _WHOLESALER_FIELDS:
        assert field in record, f"wholesaler is missing field {field!r}"
    assert isinstance(record["compliance_hold"], bool)
    assert record["funding_window_capacity"] >= 1
    assert record["adverse_finding_count"] >= 0
    assert record["executed_assignment_count"] >= 0
    assert_fields(record, "wholesaler", **expected)


_CAMPAIGN_FIELDS = (
    "wholesaler_id",
    "channel",
    "headline",
    "target_state_code",
    "discloses_intent_to_assign",
    "discloses_unlicensed_status",
    "dnc_scrubbed",
    "status",
    "published_at",
    "suspension_count",
)


def assert_marketing_campaign(record: Record, **expected: Any) -> None:
    assert_versioned(record, "marketing_campaign")
    for field in _CAMPAIGN_FIELDS:
        assert field in record, f"marketing_campaign is missing field {field!r}"
    assert record["status"] in ("DRAFT", "PUBLISHED", "SUSPENDED", "ARCHIVED")
    assert record["suspension_count"] >= 0
    assert_fields(record, "marketing_campaign", **expected)


_SELLER_LEAD_FIELDS = (
    "wholesaler_id",
    "marketing_campaign_id",
    "owner_name",
    "property_address",
    "state_code",
    "estimated_market_value_cents",
    "recorded_senior_lien_cents",
    "junior_lien_cents",
    "delinquent_property_tax_cents",
    "distress_flags",
    "status",
    "screening_variant",
    "net_equity_cents",
    "equity_pct",
    "protection_tier",
    "screened_at",
    "lead_gen_blocked",
)


def assert_seller_lead(record: Record, **expected: Any) -> None:
    assert_versioned(record, "seller_lead")
    for field in _SELLER_LEAD_FIELDS:
        assert field in record, f"seller_lead is missing field {field!r}"
    assert record["status"] in ("PROSPECT", "SCREENED", "UNDER_CONTRACT", "CLOSED")
    assert isinstance(record["distress_flags"], list)
    assert isinstance(record["lead_gen_blocked"], bool)
    assert_fields(record, "seller_lead", **expected)


_DEAL_ANALYSIS_FIELDS = (
    "seller_lead_id",
    "subject_gla_sqft",
    "comparables",
    "repair_scope_items",
    "valuation_variant",
    "qualifying_comp_count",
    "arv_cents",
    "repair_estimate_cents",
    "max_allowable_offer_cents",
    "status",
    "finalized_at",
)


def assert_deal_analysis(record: Record, **expected: Any) -> None:
    assert_versioned(record, "deal_analysis")
    for field in _DEAL_ANALYSIS_FIELDS:
        assert field in record, f"deal_analysis is missing field {field!r}"
    assert record["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")
    assert isinstance(record["qualifying_comp_count"], int)
    assert_fields(record, "deal_analysis", **expected)


def assert_disclosure_acknowledgement(record: Record, **expected: Any) -> None:
    """
    A DisclosureAcknowledgement is an immutable legal artefact: it carries only
    id and created_at, and both updated_at and version are absent from it
    entirely.
    """
    assert_identity(record, "disclosure_acknowledgement")
    assert "version" not in record, (
        "disclosure_acknowledgement must not expose a version field"
    )
    assert "updated_at" not in record, (
        "disclosure_acknowledgement must not expose an updated_at field"
    )
    assert set(record.keys()) == set(DISCLOSURE_ACKNOWLEDGEMENT_FIELDS), (
        "disclosure_acknowledgement exposes an unexpected field set: "
        f"{sorted(record.keys())}"
    )
    assert_fields(record, "disclosure_acknowledgement", **expected)


_CONTRACT_FIELDS = (
    "seller_lead_id",
    "deal_analysis_id",
    "purchase_price_cents",
    "earnest_money_cents",
    "inspection_period_days",
    "assignment_rights_granted",
    "option_start_at",
    "closing_window_start_at",
    "closing_window_end_at",
    "contract_status",
    "assignment_status",
    "structure_election",
    "signed_at",
    "inspection_deadline_at",
    "assignment_deadline_at",
    "funding_base_cents",
    "transactional_lender_fee_cents",
    "total_funding_required_cents",
    "double_close_spread_cents",
    "cancellation_reason",
    "cancelled_at",
)


def assert_purchase_contract(record: Record, **expected: Any) -> None:
    assert_versioned(record, "purchase_contract")
    for field in _CONTRACT_FIELDS:
        assert field in record, f"purchase_contract is missing field {field!r}"
    assert record["contract_status"] in (
        "DRAFT",
        "SIGNED",
        "PENDING_CLOSE",
        "CLOSED",
        "CANCELLED",
    )
    assert record["assignment_status"] in ("NOT_MARKETED", "MARKETED", "ASSIGNED")
    assert record["structure_election"] in (
        "UNDECIDED",
        "ASSIGNMENT_ELECTED",
        "DOUBLE_CLOSE_ELECTED",
    )
    assert_fields(record, "purchase_contract", **expected)


_DEPOSIT_FIELDS = (
    "purchase_contract_id",
    "amount_cents",
    "status",
    "held_cents",
    "refunded_to_wholesaler_cents",
    "forfeited_to_seller_cents",
    "applied_at_closing_cents",
    "disposition_event_count",
)


def assert_earnest_money_deposit(record: Record, **expected: Any) -> None:
    assert_versioned(record, "earnest_money_deposit")
    for field in _DEPOSIT_FIELDS:
        assert field in record, f"earnest_money_deposit is missing field {field!r}"
    assert_escrow_conserved(record)
    assert_fields(record, "earnest_money_deposit", **expected)


_CASH_BUYER_FIELDS = (
    "wholesaler_id",
    "legal_name",
    "contact_email",
    "verified_funds_cents",
    "committed_deposit_cents",
    "available_funds_cents",
    "buyer_tier",
    "active_offer_count",
)


def assert_cash_buyer(record: Record, **expected: Any) -> None:
    assert_versioned(record, "cash_buyer")
    for field in _CASH_BUYER_FIELDS:
        assert field in record, f"cash_buyer is missing field {field!r}"
    assert_buyer_capital_coherent(record)
    assert_fields(record, "cash_buyer", **expected)


_POF_FIELDS = (
    "cash_buyer_id",
    "stated_funds_cents",
    "document_ref",
    "expires_at",
    "verification_status",
    "verified_funds_cents",
    "verified_at",
    "verified_by_user_id",
)


def assert_proof_of_funds(record: Record, **expected: Any) -> None:
    assert_versioned(record, "proof_of_funds")
    for field in _POF_FIELDS:
        assert field in record, f"proof_of_funds is missing field {field!r}"
    assert record["verification_status"] in ("SUBMITTED", "VERIFIED", "REJECTED")
    assert_fields(record, "proof_of_funds", **expected)


_OFFER_FIELDS = (
    "purchase_contract_id",
    "cash_buyer_id",
    "supersedes_offer_id",
    "buyer_price_cents",
    "buyer_deposit_cents",
    "status",
    "negotiation_round",
    "countered_price_cents",
    "accepted_at",
    "assignment_fee_cents",
)


def assert_assignment_offer(record: Record, **expected: Any) -> None:
    assert_versioned(record, "assignment_offer")
    for field in _OFFER_FIELDS:
        assert field in record, f"assignment_offer is missing field {field!r}"
    assert record["status"] in (
        "SUBMITTED",
        "COUNTERED_BY_WHOLESALER",
        "REVISED_BY_BUYER",
        "ACCEPTED",
        "CONSUMED",
        "WITHDRAWN",
        "LAPSED",
    )
    assert 1 <= record["negotiation_round"] <= 4, (
        f"negotiation_round out of range: {record['negotiation_round']}"
    )
    assert_fields(record, "assignment_offer", **expected)


_AGREEMENT_FIELDS = (
    "assignment_offer_id",
    "structure",
    "assignment_fee_cents",
    "title_holdback_cents",
    "state_transfer_surcharge_cents",
    "marketing_cost_recovery_cents",
    "wholesaler_net_cents",
    "settlement_status",
    "settlement_reference",
    "settled_at",
    "executed_at",
)


def assert_assignment_agreement(record: Record, **expected: Any) -> None:
    assert_versioned(record, "assignment_agreement")
    for field in _AGREEMENT_FIELDS:
        assert field in record, f"assignment_agreement is missing field {field!r}"
    assert record["structure"] in ("ASSIGNMENT", "DOUBLE_CLOSE")
    assert record["settlement_status"] in (
        "PENDING_SETTLEMENT",
        "SETTLED",
        "TERMINATED_UPSTREAM",
    )
    assert_fields(record, "assignment_agreement", **expected)


_TITLE_ORDER_FIELDS = (
    "purchase_contract_id",
    "title_company_name",
    "escrow_officer_ref",
    "funding_window_start_at",
    "funding_window_end_at",
    "status",
    "structure",
    "cleared_by_user_id",
    "funded_by_user_id",
    "buffered_window_end_at",
)


def assert_title_order(record: Record, **expected: Any) -> None:
    assert_versioned(record, "title_order")
    for field in _TITLE_ORDER_FIELDS:
        assert field in record, f"title_order is missing field {field!r}"
    assert record["status"] in (
        "OPENED",
        "CLEARED_TO_FUND",
        "FUNDED_AND_CLOSED",
        "CANCELLED",
    )
    assert_fields(record, "title_order", **expected)


_REVIEW_FIELDS = (
    "wholesaler_id",
    "subject_seller_lead_id",
    "review_type",
    "allegation_note",
    "status",
    "finding",
    "opened_by_user_id",
    "adjudicated_by_user_id",
    "adjudicated_at",
)


def assert_compliance_review(record: Record, **expected: Any) -> None:
    assert_versioned(record, "compliance_review")
    for field in _REVIEW_FIELDS:
        assert field in record, f"compliance_review is missing field {field!r}"
    assert record["status"] in (
        "OPENED",
        "ADJUDICATED_CLEARED",
        "ADJUDICATED_ADVERSE",
    )
    assert_fields(record, "compliance_review", **expected)


_DISPUTE_FIELDS = (
    "purchase_contract_id",
    "dispute_basis",
    "claimed_amount_cents",
    "status",
    "seller_evidence_ref",
    "wholesaler_evidence_ref",
    "award",
    "award_seller_cents",
    "award_wholesaler_cents",
    "adjudicated_by_user_id",
)


def assert_dispute_case(record: Record, **expected: Any) -> None:
    assert_versioned(record, "dispute_case")
    for field in _DISPUTE_FIELDS:
        assert field in record, f"dispute_case is missing field {field!r}"
    assert record["status"] in (
        "OPENED",
        "EVIDENCE_PARTIAL",
        "EVIDENCE_COMPLETE",
        "ADJUDICATED",
    )
    assert_fields(record, "dispute_case", **expected)


# ---------------------------------------------------------------------------
# Valuation derivations (PRD 3.4)
# ---------------------------------------------------------------------------


def comparable_qualifies(subject_gla_sqft: int, comp: Dict[str, Any]) -> bool:
    """
    A comparable qualifies only when all three filters pass: distance at most
    0.50 miles inclusive, recency at most 180 days inclusive, and a size band
    evaluated in exact integer arithmetic.
    """
    if Decimal(str(comp["distance_miles"])) > Decimal(str(DISTANCE_MAX_MILES)):
        return False
    if comp["closed_days_ago"] > RECENCY_MAX_DAYS:
        return False
    spread = abs(comp["gla_sqft"] - subject_gla_sqft) * GLA_BAND_NUMERATOR
    return spread <= subject_gla_sqft * GLA_BAND_MULTIPLIER


def qualifying_comparables(
    subject_gla_sqft: int, comparables: Iterable[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """The subset of comparables passing the distance, recency and size filters."""
    return [c for c in comparables if comparable_qualifies(subject_gla_sqft, c)]


def adjusted_price(comp: Dict[str, Any]) -> int:
    """A comparable's adjusted price is its sale price plus its adjustment."""
    return comp["sale_price_cents"] + comp["adjustment_cents"]


def conservative_arv(qualifying: Sequence[Dict[str, Any]]) -> int:
    """
    The median of the qualifying adjusted prices, ordered by adjusted price
    ascending, then by smaller closed_days_ago, then by submitted position.
    An even count takes the sum of the two middle prices divided by two,
    floored.
    """
    indexed = list(enumerate(qualifying))
    ordered = sorted(
        indexed, key=lambda pair: (adjusted_price(pair[1]), pair[1]["closed_days_ago"], pair[0])
    )
    prices = [adjusted_price(c) for _, c in ordered]
    count = len(prices)
    if count % 2 == 1:
        return prices[count // 2]
    lo = prices[count // 2 - 1]
    hi = prices[count // 2]
    return floor_to_int(Decimal(lo + hi) / Decimal(2))


def aggressive_arv(qualifying: Sequence[Dict[str, Any]]) -> int:
    """
    A recency-weighted mean: each weight is 181 minus closed_days_ago, the
    numerator and denominator accumulate in full precision, and the single
    division is rounded half up once.
    """
    numerator = Decimal(0)
    denominator = Decimal(0)
    for comp in qualifying:
        weight = Decimal(RECENCY_WEIGHT_BASE - comp["closed_days_ago"])
        numerator += Decimal(adjusted_price(comp)) * weight
        denominator += weight
    return round_half_up(numerator / denominator)


def conservative_repair_estimate(items: Iterable[Dict[str, Any]]) -> int:
    """Sum of every high_cents, multiplied once by the contingency factor."""
    total = sum(Decimal(item["high_cents"]) for item in items) or Decimal(0)
    return round_half_up(Decimal(total) * Decimal(str(CONTINGENCY_MULTIPLIER)))


def aggressive_repair_estimate(items: Iterable[Dict[str, Any]]) -> int:
    """Sum of every low_cents, with no contingency at all."""
    return int(sum(item["low_cents"] for item in items))


def max_allowable_offer(arv_cents: int, variant: str, repair_estimate_cents: int) -> int:
    """
    The after-repair value times the variant's multiplier, floored, then
    reduced by the repair estimate and by the minimum assignment margin. The
    result is not clamped at zero.
    """
    multiplier = (
        CONSERVATIVE_ARV_MULTIPLIER if variant == "CONSERVATIVE" else AGGRESSIVE_ARV_MULTIPLIER
    )
    ceiling = floor_to_int(Decimal(arv_cents) * Decimal(str(multiplier)))
    return ceiling - repair_estimate_cents - MIN_ASSIGNMENT_MARGIN_CENTS


# ---------------------------------------------------------------------------
# Protection screen derivations (PRD 3.3)
# ---------------------------------------------------------------------------


def statutory_net_equity(estimated_market_value_cents: int, recorded_senior_lien_cents: int) -> int:
    """Estimated market value less the recorded senior lien and nothing else."""
    return estimated_market_value_cents - recorded_senior_lien_cents


def effective_net_equity(
    estimated_market_value_cents: int,
    recorded_senior_lien_cents: int,
    junior_lien_cents: int,
    delinquent_property_tax_cents: int,
) -> int:
    """
    Estimated market value less senior lien, junior lien, delinquent tax and a
    closing-cost allowance of eight percent of market value, that allowance
    rounded half up before it is subtracted.
    """
    allowance = round_half_up(
        Decimal(estimated_market_value_cents) * Decimal(str(SELLER_CLOSING_COST_PCT))
    )
    return (
        estimated_market_value_cents
        - recorded_senior_lien_cents
        - junior_lien_cents
        - delinquent_property_tax_cents
        - allowance
    )


def equity_pct(net_equity_cents: int, estimated_market_value_cents: int) -> Decimal:
    """Net equity over market value, quantized to exactly four places, half up."""
    return round_half_up_places(
        Decimal(net_equity_cents) / Decimal(estimated_market_value_cents), 4
    )


def protection_tier(pct, distress_flag_count: int) -> str:
    """
    PROTECTED at or above 0.35 with at least two flags; ELEVATED either at or
    above 0.35 with exactly one flag or below 0.35 with at least two flags;
    STANDARD in every other case.
    """
    high = Decimal(str(pct)) >= Decimal(str(HIGH_EQUITY_PCT))
    if high and distress_flag_count >= 2:
        return "PROTECTED"
    if (high and distress_flag_count == 1) or ((not high) and distress_flag_count >= 2):
        return "ELEVATED"
    return "STANDARD"


def statutory_equity_floor(
    estimated_market_value_cents: int, recorded_senior_lien_cents: int
) -> int:
    """
    Sixty percent of statutory equity, floored, with the senior lien added
    back. A purchase price strictly below this figure skims equity.
    """
    statutory = estimated_market_value_cents - recorded_senior_lien_cents
    return (
        floor_to_int(Decimal(statutory) * Decimal(str(EQUITY_FLOOR_PCT)))
        + recorded_senior_lien_cents
    )


# ---------------------------------------------------------------------------
# Fee cap, settlement and funding derivations (PRD 3.7, 3.8)
# ---------------------------------------------------------------------------


def assignment_fee_cap(purchase_price_cents: int, tier: str) -> int:
    """The contract price times the tier's share, floored."""
    share = FEE_CAP_PCT_BY_TIER[tier]
    return floor_to_int(Decimal(purchase_price_cents) * Decimal(str(share)))


def settlement_components(assignment_fee_cents: int) -> Dict[str, int]:
    """
    Each of the three rate-driven components is rounded to a whole cent on its
    own before any of them is subtracted; the net is the fee less all three.
    """
    holdback = apply_rate(assignment_fee_cents, TITLE_HOLDBACK_RATE)
    surcharge = apply_rate(assignment_fee_cents, STATE_TRANSFER_SURCHARGE_RATE)
    marketing = apply_rate(assignment_fee_cents, MARKETING_RECOVERY_RATE)
    return {
        "title_holdback_cents": holdback,
        "state_transfer_surcharge_cents": surcharge,
        "marketing_cost_recovery_cents": marketing,
        "wholesaler_net_cents": assignment_fee_cents - holdback - surcharge - marketing,
    }


def funding_base(purchase_price_cents: int) -> int:
    """Purchase price plus 2.1 percent of it, that product rounded half up."""
    return purchase_price_cents + apply_rate(
        purchase_price_cents, CLOSING_COST_GROSS_UP_RATE
    )


def lender_fee_tier(funding_base_cents: int) -> Dict[str, Any]:
    """
    The tier is selected from the grossed-up base, with half-open edges: a base
    exactly on fifteen million cents is in the second tier and one exactly on
    thirty million cents is in the third.
    """
    if funding_base_cents < TIER_1_CEILING_CENTS:
        return {"rate": TIER_1_RATE, "min_fee": TIER_1_MIN_FEE_CENTS, "tier": 1}
    if funding_base_cents < TIER_2_CEILING_CENTS:
        return {"rate": TIER_2_RATE, "min_fee": TIER_2_MIN_FEE_CENTS, "tier": 2}
    return {"rate": TIER_3_RATE, "min_fee": TIER_3_MIN_FEE_CENTS, "tier": 3}


def transactional_lender_fee(funding_base_cents: int) -> int:
    """The greater of the tier minimum and the rate product rounded half up."""
    tier = lender_fee_tier(funding_base_cents)
    return max(tier["min_fee"], apply_rate(funding_base_cents, tier["rate"]))


def double_close_schedule(purchase_price_cents: int) -> Dict[str, int]:
    """The three non-null figures the double-close election writes."""
    base = funding_base(purchase_price_cents)
    fee = transactional_lender_fee(base)
    return {
        "funding_base_cents": base,
        "transactional_lender_fee_cents": fee,
        "total_funding_required_cents": base + fee,
    }


# ---------------------------------------------------------------------------
# Domain invariants (PRD 2.11)
# ---------------------------------------------------------------------------


def assert_escrow_conserved(deposit: Record) -> None:
    """
    The four buckets always sum to exactly amount_cents, and no bucket is ever
    negative.
    """
    buckets = (
        "held_cents",
        "refunded_to_wholesaler_cents",
        "forfeited_to_seller_cents",
        "applied_at_closing_cents",
    )
    for bucket in buckets:
        assert deposit[bucket] >= 0, f"deposit.{bucket} must never be negative"
    total = sum(deposit[bucket] for bucket in buckets)
    assert total == deposit["amount_cents"], (
        "escrow conservation violated: buckets "
        f"{[deposit[b] for b in buckets]} sum to {total}, "
        f"amount_cents is {deposit['amount_cents']}"
    )
    assert deposit["disposition_event_count"] >= 0


def assert_buyer_capital_coherent(buyer: Record) -> None:
    """
    available_funds_cents is verified_funds_cents less committed_deposit_cents,
    and buyer_tier follows from those two figures.
    """
    assert (
        buyer["available_funds_cents"]
        == buyer["verified_funds_cents"] - buyer["committed_deposit_cents"]
    ), (
        "buyer capital reconciliation violated: available "
        f"{buyer['available_funds_cents']} != verified "
        f"{buyer['verified_funds_cents']} - committed "
        f"{buyer['committed_deposit_cents']}"
    )
    assert buyer["active_offer_count"] >= 0
    assert buyer["buyer_tier"] == expected_buyer_tier(
        buyer["verified_funds_cents"], buyer["available_funds_cents"]
    ), (
        f"buyer_tier {buyer['buyer_tier']} does not follow from verified "
        f"{buyer['verified_funds_cents']} and available "
        f"{buyer['available_funds_cents']}"
    )


def expected_buyer_tier(verified_funds_cents: int, available_funds_cents: int) -> str:
    """SUSPENDED on zero verified funds, PRIORITY at or above the threshold."""
    if verified_funds_cents == 0:
        return "SUSPENDED"
    if available_funds_cents >= PRIORITY_TIER_MIN_AVAILABLE_CENTS:
        return "PRIORITY"
    return "STANDARD"


def assert_buyer_capital_reconciled(buyer: Record, offers: Sequence[Record]) -> None:
    """
    committed_deposit_cents equals the sum of buyer_deposit_cents across that
    buyer's offers in a live negotiation status, and active_offer_count equals
    the count of those same offers.
    """
    live = [
        offer
        for offer in offers
        if offer["cash_buyer_id"] == buyer["id"] and offer["status"] in LIVE_OFFER_STATUSES
    ]
    expected_committed = sum(offer["buyer_deposit_cents"] for offer in live)
    assert buyer["committed_deposit_cents"] == expected_committed, (
        f"committed_deposit_cents {buyer['committed_deposit_cents']} does not "
        f"equal the live offer deposit sum {expected_committed}"
    )
    assert buyer["active_offer_count"] == len(live), (
        f"active_offer_count {buyer['active_offer_count']} does not equal the "
        f"live offer count {len(live)}"
    )
    assert_buyer_capital_coherent(buyer)


def assert_compliance_posture(wholesaler: Record) -> None:
    """compliance_hold becomes true once adverse_finding_count reaches two."""
    expected_hold = wholesaler["adverse_finding_count"] >= COMPLIANCE_HOLD_THRESHOLD
    assert wholesaler["compliance_hold"] is expected_hold, (
        f"compliance_hold {wholesaler['compliance_hold']} does not follow from "
        f"adverse_finding_count {wholesaler['adverse_finding_count']}"
    )


def assert_settlement_arithmetic(agreement: Record) -> None:
    """
    The three deduction components and the residual net must match a
    per-component rounding of the copied assignment fee.
    """
    expected = settlement_components(agreement["assignment_fee_cents"])
    for field, want in expected.items():
        assert agreement[field] == want, (
            f"agreement.{field} expected {want}, got {agreement[field]}"
        )


def assert_equity_pct_four_places(value) -> None:
    """equity_pct is carried to exactly four decimal places."""
    assert value is not None, "equity_pct must be populated once screened"
    quantized = Decimal(str(value)).quantize(Decimal("0.0001"))
    assert Decimal(str(value)) == quantized, (
        f"equity_pct {value!r} carries more than four decimal places"
    )
