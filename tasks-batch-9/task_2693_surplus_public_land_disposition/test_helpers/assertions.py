"""Per-entity shape assertions and domain invariant checkers."""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    AFFORDABLE_HOUSING_WRITE_DOWN,
    APPRAISAL_VALIDITY_DAYS,
    BID_DEPOSIT_FLOOR_CENTS,
    BID_DEPOSIT_FRACTION,
    CHALLENGE_DEPOSIT_CEILING_CENTS,
    CHALLENGE_DEPOSIT_FLOOR_CENTS,
    CHALLENGE_DEPOSIT_FRACTION,
    CURATIVE_RECOVERY_CAP_FRACTION,
    REOFFER_DISCOUNT_CAP,
    REOFFER_DISCOUNT_PER_CYCLE,
    SECONDS_PER_DAY,
)

# ---------------------------------------------------------------------------
# Money and time arithmetic
# ---------------------------------------------------------------------------


def round_half_up(value: Any) -> int:
    """Round to a whole cent, halves away from zero, exactly as the spec requires."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_instant(instant: str) -> datetime:
    """Parse an ISO 8601 UTC instant."""
    return datetime.fromisoformat(instant.replace("Z", "+00:00"))


def format_instant(moment: datetime) -> str:
    """Render an instant the way the API writes them.

    PRD 2.4 fixes the wire format for every instant the server writes: "an ISO
    8601 UTC instant, with three fractional digits".  The trailing milliseconds
    are therefore part of the value, not optional decoration.
    """
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def add_days(instant: str, days: int) -> str:
    """Add whole days of 86400 seconds each to an instant."""
    return format_instant(
        parse_instant(instant) + timedelta(seconds=days * SECONDS_PER_DAY)
    )


def whole_days_between(earlier: str, later: str) -> int:
    """Whole 86400-second days elapsed between two instants."""
    delta = parse_instant(later) - parse_instant(earlier)
    return int(delta.total_seconds() // SECONDS_PER_DAY)


def expected_expires_on(effective_date: str) -> str:
    """An accepted report lapses this many days after its effective date."""
    return add_days(effective_date, APPRAISAL_VALIDITY_DAYS)


# ---------------------------------------------------------------------------
# Derived money figures
# ---------------------------------------------------------------------------


def expected_challenge_deposit(appraised_value_cents: int) -> int:
    """One hundredth of the appraised value, rounded half up, then clamped."""
    raw = round_half_up(Decimal(appraised_value_cents) * Decimal(str(CHALLENGE_DEPOSIT_FRACTION)))
    if raw < CHALLENGE_DEPOSIT_FLOOR_CENTS:
        return CHALLENGE_DEPOSIT_FLOOR_CENTS
    if raw > CHALLENGE_DEPOSIT_CEILING_CENTS:
        return CHALLENGE_DEPOSIT_CEILING_CENTS
    return raw


def expected_required_bid_deposit(minimum_price_cents: int) -> int:
    """A twentieth of the frozen minimum price, rounded half up, floored."""
    raw = round_half_up(
        Decimal(minimum_price_cents) * Decimal(str(BID_DEPOSIT_FRACTION))
    )
    return max(raw, BID_DEPOSIT_FLOOR_CENTS)


def expected_minimum_price(
    appraised_value_cents: int,
    cure_deduction_cents: int = 0,
    reoffer_count: int = 0,
    book_value_cents: int = 0,
    affordable_housing: bool = False,
) -> int:
    """The statutory minimum price under the variant the caller names.

    The gross figure is the appraised value reduced by the write-down and by the
    re-offer discount, rounded half up exactly once. The curative deduction is
    subtracted from that gross figure. The market-floor variant then takes the
    larger of that raw figure and the parcel's carrying value; the affordable
    housing variant takes the larger of the raw figure and zero.
    """
    write_down = Decimal(str(AFFORDABLE_HOUSING_WRITE_DOWN)) if affordable_housing else Decimal(0)
    discount = min(
        Decimal(str(REOFFER_DISCOUNT_PER_CYCLE)) * reoffer_count,
        Decimal(str(REOFFER_DISCOUNT_CAP)),
    )
    gross = round_half_up(
        Decimal(appraised_value_cents) * (Decimal(1) - write_down) * (Decimal(1) - discount)
    )
    raw = gross - cure_deduction_cents
    if affordable_housing:
        return max(raw, 0)
    return max(raw, book_value_cents)


def expected_curative_recovery_cap(provisional_net_cents: int) -> int:
    """Curative recovery may not exceed this share of the provisional net proceeds."""
    return round_half_up(
        Decimal(provisional_net_cents) * Decimal(str(CURATIVE_RECOVERY_CAP_FRACTION))
    )


# ---------------------------------------------------------------------------
# Common system field assertions
# ---------------------------------------------------------------------------


def assert_versioned_system_fields(entity: Dict[str, Any], label: str = "entity") -> None:
    """Every versioned entity carries a server-minted id and the three audit fields."""
    assert is_valid_uuid(entity.get("id", "")), (
        f"{label}.id must be a server-minted UUID, got {entity.get('id')!r}"
    )
    assert "-" in str(entity.get("id", "")), f"{label}.id must not carry a prefix"
    for field in ("created_at", "updated_at"):
        assert is_iso8601_timestamp(entity.get(field, "")), (
            f"{label}.{field} must be an ISO 8601 timestamp, got {entity.get(field)!r}"
        )
    assert isinstance(entity.get("version"), int) and entity["version"] >= 1, (
        f"{label}.version must be a positive integer, got {entity.get('version')!r}"
    )


def assert_append_only_system_fields(
    entity: Dict[str, Any], label: str = "entity"
) -> None:
    """Append-only rows carry only an id and a creation stamp — no version, no update."""
    assert is_valid_uuid(entity.get("id", "")), (
        f"{label}.id must be a server-minted UUID, got {entity.get('id')!r}"
    )
    assert is_iso8601_timestamp(entity.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert "updated_at" not in entity, (
        f"{label} must not expose updated_at, it is not amendable"
    )
    assert "version" not in entity, (
        f"{label} must not expose version, it is not amendable"
    )


def assert_no_pagination_fields(meta: Dict[str, Any]) -> None:
    """A single-resource response omits every pagination field."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, (
            f"single-resource meta must omit {field}, got {meta.get(field)!r}"
        )


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------


def assert_agency(agency: Dict[str, Any]) -> None:
    assert_versioned_system_fields(agency, "Agency")
    for field in (
        "name",
        "agency_type",
        "contact_email",
        "is_preference_entity",
        "preference_category",
        "notice_registry_status",
    ):
        assert field in agency, f"Agency must expose {field}"
    assert isinstance(agency["is_preference_entity"], bool), (
        "Agency.is_preference_entity must be a boolean"
    )


def assert_parcel(parcel: Dict[str, Any]) -> None:
    assert_versioned_system_fields(parcel, "Parcel")
    for field in (
        "apn",
        "address",
        "acreage",
        "zoning_code",
        "book_value_cents",
        "custodian_agency_id",
        "ownership_status",
        "valuation_status",
        "open_title_item_count",
        "disposition_ready",
    ):
        assert field in parcel, f"Parcel must expose {field}"
    assert parcel["acreage"] > 0, "Parcel.acreage must be strictly positive"
    assert parcel["book_value_cents"] >= 0, "Parcel.book_value_cents may not be negative"
    assert isinstance(parcel["disposition_ready"], bool), (
        "Parcel.disposition_ready must be a boolean"
    )


def assert_title_item(item: Dict[str, Any]) -> None:
    assert_versioned_system_fields(item, "TitleCurativeItem")
    for field in ("parcel_id", "item_type", "description", "cure_cost_estimate_cents", "status"):
        assert field in item, f"TitleCurativeItem must expose {field}"
    assert item["cure_cost_estimate_cents"] >= 0, (
        "TitleCurativeItem.cure_cost_estimate_cents may not be negative"
    )


def assert_appraiser(appraiser: Dict[str, Any]) -> None:
    assert_versioned_system_fields(appraiser, "Appraiser")
    for field in (
        "name",
        "license_number",
        "license_expires_on",
        "license_status",
        "active_engagement_count",
    ):
        assert field in appraiser, f"Appraiser must expose {field}"


def assert_appraisal(appraisal: Dict[str, Any]) -> None:
    assert_versioned_system_fields(appraisal, "Appraisal")
    for field in (
        "parcel_id",
        "appraiser_id",
        "method",
        "engagement_start_on",
        "engagement_end_on",
        "status",
        "revaluation_required",
        "challenge_count",
    ):
        assert field in appraisal, f"Appraisal must expose {field}"


def assert_challenge(challenge: Dict[str, Any]) -> None:
    assert_versioned_system_fields(challenge, "AppraisalChallenge")
    for field in (
        "appraisal_id",
        "challenger_agency_id",
        "asserted_value_cents",
        "status",
        "required_deposit_cents",
        "deposit_paid_cents",
        "deposit_refunded_cents",
        "deposit_forfeited_cents",
    ):
        assert field in challenge, f"AppraisalChallenge must expose {field}"


def assert_declaration(declaration: Dict[str, Any]) -> None:
    assert_versioned_system_fields(declaration, "SurplusDeclaration")
    for field in (
        "parcel_id",
        "justification",
        "status",
        "reoffer_count",
        "preference_offer_count",
        "unresolved_preference_count",
    ):
        assert field in declaration, f"SurplusDeclaration must expose {field}"


def assert_notice(notice: Dict[str, Any]) -> None:
    assert_versioned_system_fields(notice, "StatutoryNotice")
    for field in (
        "declaration_id",
        "recipient_agency_id",
        "notice_round",
        "status",
        "issued_at",
        "response_window_days",
        "response_deadline_at",
    ):
        assert field in notice, f"StatutoryNotice must expose {field}"


def assert_preference_offer(offer: Dict[str, Any]) -> None:
    assert_versioned_system_fields(offer, "PreferenceOffer")
    for field in (
        "declaration_id",
        "notice_id",
        "offeror_agency_id",
        "negotiation_status",
        "good_faith_status",
        "negotiation_opened_at",
        "negotiation_deadline_at",
        "ah_minimum_price_cents",
        "officer_round_count",
        "entity_round_count",
        "timely_response_count",
    ):
        assert field in offer, f"PreferenceOffer must expose {field}"


def assert_negotiation_round(round_row: Dict[str, Any]) -> None:
    assert_append_only_system_fields(round_row, "NegotiationRound")
    for field in (
        "offer_id",
        "round_number",
        "party",
        "price_offered_cents",
        "terms_summary",
        "is_timely",
    ):
        assert field in round_row, f"NegotiationRound must expose {field}"
    assert isinstance(round_row["is_timely"], bool), (
        "NegotiationRound.is_timely must be a boolean"
    )


def assert_environmental_review(review: Dict[str, Any]) -> None:
    assert_versioned_system_fields(review, "EnvironmentalReview")
    for field in ("declaration_id", "determination_class", "circulation_round", "status"):
        assert field in review, f"EnvironmentalReview must expose {field}"


def assert_offering(offering: Dict[str, Any]) -> None:
    assert_versioned_system_fields(offering, "DispositionOffering")
    for field in (
        "declaration_id",
        "offering_type",
        "bid_open_at",
        "bid_close_at",
        "status",
        "minimum_price_cents",
        "minimum_price_variant",
        "required_deposit_cents",
        "qualified_bid_count",
        "rescind_count",
    ):
        assert field in offering, f"DispositionOffering must expose {field}"


def assert_bidder(bidder: Dict[str, Any]) -> None:
    assert_versioned_system_fields(bidder, "Bidder")
    for field in (
        "legal_name",
        "entity_type",
        "contact_email",
        "debarment_status",
        "available_funds_cents",
        "escrow_held_cents",
        "lifetime_deposits_cents",
    ):
        assert field in bidder, f"Bidder must expose {field}"


def assert_bid(bid: Dict[str, Any]) -> None:
    assert_versioned_system_fields(bid, "Bid")
    for field in (
        "offering_id",
        "bidder_id",
        "amount_cents",
        "deposit_amount_cents",
        "qualification_status",
        "deposit_status",
        "submitted_at",
    ):
        assert field in bid, f"Bid must expose {field}"


def assert_conveyance(conveyance: Dict[str, Any]) -> None:
    assert_versioned_system_fields(conveyance, "Conveyance")
    for field in (
        "offering_id",
        "parcel_id",
        "grantee_kind",
        "sale_price_cents",
        "closing_costs_cents",
        "broker_fee_cents",
        "deed_restrictions",
        "reverter_condition",
        "reverter_cure_period_days",
        "recording_status",
        "compliance_status",
        "recoverable_curative_cost_cents",
        "net_proceeds_cents",
        "allocated_proceeds_cents",
    ):
        assert field in conveyance, f"Conveyance must expose {field}"
    populated = [
        key
        for key in ("grantee_bidder_id", "grantee_agency_id")
        if conveyance.get(key)
    ]
    assert len(populated) == 1, (
        "exactly one grantee reference must be populated, got "
        f"{populated} on conveyance {conveyance.get('id')}"
    )


def assert_fund(fund: Dict[str, Any]) -> None:
    assert_versioned_system_fields(fund, "Fund")
    for field in (
        "name",
        "fund_code",
        "priority_rank",
        "allocation_pct",
        "fixed_reserve_cents",
        "balance_cents",
        "lifetime_credits_cents",
        "lifetime_debits_cents",
    ):
        assert field in fund, f"Fund must expose {field}"
    assert fund["priority_rank"] >= 1, "Fund.priority_rank must be at least 1"
    assert 0 <= float(fund["allocation_pct"]) <= 1, (
        "Fund.allocation_pct must lie between 0 and 1"
    )


def assert_proceeds_allocation(row: Dict[str, Any]) -> None:
    assert_append_only_system_fields(row, "ProceedsAllocation")
    for field in (
        "fund_id",
        "amount_cents",
        "allocation_basis",
        "residual_included_cents",
        "status",
    ):
        assert field in row, f"ProceedsAllocation must expose {field}"


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_bidder_cash_conserved(bidder: Dict[str, Any]) -> None:
    """While no deposit has been applied the bidder's cash position is conserved."""
    total = bidder["available_funds_cents"] + bidder["escrow_held_cents"]
    assert total == bidder["lifetime_deposits_cents"], (
        "available funds plus escrow must equal lifetime deposits: "
        f"{bidder['available_funds_cents']} + {bidder['escrow_held_cents']} "
        f"!= {bidder['lifetime_deposits_cents']}"
    )


def assert_fund_ledger_identity(fund: Dict[str, Any]) -> None:
    """A fund's balance is exactly its lifetime credits less its lifetime debits."""
    expected = fund["lifetime_credits_cents"] - fund["lifetime_debits_cents"]
    assert fund["balance_cents"] == expected, (
        f"fund {fund.get('fund_code')} balance {fund['balance_cents']} must equal "
        f"credits {fund['lifetime_credits_cents']} less debits "
        f"{fund['lifetime_debits_cents']} = {expected}"
    )


def assert_waterfall_reconciles(rows: list, net_proceeds_cents: int) -> None:
    """The allocation rows must add up to the net proceeds to the cent."""
    total = sum(row["amount_cents"] for row in rows)
    assert total == net_proceeds_cents, (
        f"allocation rows total {total} must equal net proceeds {net_proceeds_cents}"
    )


def assert_money_is_whole_cents(value: Any, label: str) -> None:
    """Money fields are whole integer counts of cents."""
    assert isinstance(value, int), f"{label} must be an integer count of cents, got {value!r}"
    assert value >= 0, f"{label} may not be negative, got {value}"


def find_row(rows: list, **criteria: Any) -> Optional[Dict[str, Any]]:
    """The first row matching every named field, or None."""
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            return row
    return None
