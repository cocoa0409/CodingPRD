"""Domain assertions: resource-shape checks and the PRD's standing invariants.

The framework already supplies envelope, uuid, timestamp and race assertions. What is
added here is knowledge of *this* API: which fields each resource must expose, and the
arithmetic identities the PRD says must hold at every moment.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import THRESHOLDS


# ---------------------------------------------------------------------------
# Rounding helper mirroring PRD section 2.5
# ---------------------------------------------------------------------------


def round_half_up(value: Decimal, places: int = 0) -> int:
    """Round half up, the only rounding method PRD section 2.5 permits."""
    quantum = Decimal(1).scaleb(-places)
    rounded = Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(rounded) if places == 0 else rounded


def bps_of(amount: int, bps: int) -> int:
    """Apply a basis-point rate to an integer cent amount, rounded half up."""
    return round_half_up(Decimal(amount) * Decimal(bps) / Decimal(10000))


# ---------------------------------------------------------------------------
# Generic field helpers
# ---------------------------------------------------------------------------


def assert_has_fields(record: Mapping[str, Any], fields: Iterable[str], label: str = "record") -> None:
    missing = [field for field in fields if field not in record]
    assert not missing, f"{label} is missing expected fields {missing}; got keys {sorted(record.keys())}"


def assert_fields(record: Mapping[str, Any], expected: Mapping[str, Any], label: str = "record") -> None:
    """Assert every expected field equals its expected value, reporting all mismatches."""
    problems = []
    for field, want in expected.items():
        if field not in record:
            problems.append(f"{field}: absent (expected {want!r})")
        elif record[field] != want:
            problems.append(f"{field}: got {record[field]!r}, expected {want!r}")
    assert not problems, f"{label} mismatch -> " + "; ".join(problems)


def assert_fields_match(
    write_body: Mapping[str, Any], read_body: Mapping[str, Any], fields: Sequence[str], label: str = "resource"
) -> None:
    """Assert a write response and a later read agree field for field."""
    problems = []
    for field in fields:
        if write_body.get(field) != read_body.get(field):
            problems.append(f"{field}: write {write_body.get(field)!r} vs read {read_body.get(field)!r}")
    assert not problems, f"{label} is not immediately consistent -> " + "; ".join(problems)


def assert_pairwise_distinct(values: Sequence[Any], label: str = "values") -> None:
    assert len(set(values)) == len(values), f"{label} are not pairwise distinct: {values}"


def assert_common_fields(record: Mapping[str, Any], expected_version: Optional[int] = None, label: str = "resource") -> None:
    """Every resource carries id, created_at, updated_at and version (PRD section 2.4)."""
    assert_has_fields(record, ("id", "created_at", "updated_at", "version"), label)
    assert is_valid_uuid(record["id"]), f"{label}.id is not a UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), f"{label}.created_at is not ISO 8601: {record['created_at']!r}"
    assert is_iso8601_timestamp(record["updated_at"]), f"{label}.updated_at is not ISO 8601: {record['updated_at']!r}"
    assert isinstance(record["version"], int), f"{label}.version is not an integer: {record['version']!r}"
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"{label}.version is {record['version']}, expected {expected_version}"
        )


# ---------------------------------------------------------------------------
# Per-resource shape assertions
# ---------------------------------------------------------------------------

_PORTFOLIO_FIELDS = (
    "name",
    "program_code",
    "total_capital_cents",
    "committed_capital_cents",
    "deployed_capital_cents",
    "available_capital_cents",
    "utilization_bps",
    "capital_posture",
    "active_deal_count",
)

_FACILITY_FIELDS = (
    "portfolio_id",
    "facility_name",
    "advance_rate_bps",
    "valuation_basis",
    "carrier_concentration_limit_bps",
    "pledged_eligible_total_cents",
    "concentration_excess_cents",
    "borrowing_base_cents",
    "advances_outstanding_cents",
    "pledged_stream_count",
    "compliance_state",
)

_LEASE_STREAM_FIELDS = (
    "tower_site_id",
    "landowner_id",
    "current_annual_rent_cents",
    "escalator_type",
    "escalator_pct_bps",
    "remaining_term_months",
    "tenancy_quality_score",
    "anchor_carrier_name",
    "acquisition_status",
    "servicing_status",
    "rent_redirection_status",
    "active_tenancy_count",
    "cumulative_revenue_share_landowner_cents",
    "cumulative_revenue_share_acquirer_cents",
)

_VALUATION_FIELDS = (
    "lease_stream_id",
    "method",
    "tenancy_quality_score_snapshot",
    "discount_rate_bps",
    "growth_rate_bps",
    "horizon_years",
    "value_cents",
    "max_bid_cents",
    "status",
)

_DEAL_FIELDS = (
    "portfolio_id",
    "lease_stream_id",
    "valuation_id",
    "easement_type",
    "easement_term_years",
    "revenue_share_bps",
    "stage",
    "capital_state",
    "rofr_state",
    "negotiation_rounds",
    "easement_status",
    "escrow_funded_cents",
    "escrow_disbursed_cents",
    "escrow_holdback_cents",
    "escrow_refunded_cents",
)

_OFFER_FIELDS = ("deal_id", "offer_type", "amount_cents", "expires_at", "status", "round_number")

_TITLE_REPORT_FIELDS = (
    "deal_id",
    "snda_required",
    "review_status",
    "consent_status",
    "mortgage_present",
    "exception_count",
    "open_exception_count",
)

_ROFR_NOTICE_FIELDS = ("deal_id", "status", "window_days_snapshot", "served_at", "window_start", "window_end")

_DISPUTE_FIELDS = ("lease_stream_id", "dispute_type", "description", "status", "raised_by_role", "cure_attempts")

_PLEDGE_FIELDS = (
    "lease_stream_id",
    "pledge_start_date",
    "pledge_end_date",
    "status",
    "valuation_basis_snapshot",
    "basis_value_cents",
    "haircut_bps",
    "eligible_value_cents",
)

_AMENDMENT_FIELDS = (
    "lease_stream_id",
    "event_type",
    "gross_amount_cents",
    "effective_date",
    "effective_pass_through_cents",
    "net_amount_cents",
    "share_bps_applied",
    "landowner_share_cents",
    "acquirer_share_cents",
    "status",
)


def assert_portfolio(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="Portfolio")
    assert_has_fields(record, _PORTFOLIO_FIELDS, "Portfolio")
    assert_portfolio_ledger_balances(record)


def assert_facility(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="FinancingFacility")
    assert_has_fields(record, _FACILITY_FIELDS, "FinancingFacility")


def assert_tower_company(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="TowerCompany")
    assert_has_fields(record, ("legal_name", "notice_email", "rofr_required", "rofr_window_days", "site_count"), "TowerCompany")


def assert_tower_site(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="TowerSite")
    assert_has_fields(
        record,
        ("tower_company_id", "site_code", "state_code", "ground_area_sqft", "structure_type", "lease_stream_count"),
        "TowerSite",
    )


def assert_landowner(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="Landowner")
    assert_has_fields(record, ("legal_name", "entity_type", "contact_email", "outreach_status", "open_dispute_count"), "Landowner")


def assert_lease_stream(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="LeaseStream")
    assert_has_fields(record, _LEASE_STREAM_FIELDS, "LeaseStream")


def assert_tenancy(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="CarrierTenancy")
    assert_has_fields(
        record,
        ("carrier_name", "carrier_credit_tier", "tenancy_type", "monthly_rent_share_cents", "term_end_date", "status", "quality_points"),
        "CarrierTenancy",
    )


def assert_valuation(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="StreamValuation")
    assert_has_fields(record, _VALUATION_FIELDS, "StreamValuation")
    assert_max_bid_ceiling(record)


def assert_deal(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="Deal")
    assert_has_fields(record, _DEAL_FIELDS, "Deal")


def assert_offer(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="Offer")
    assert_has_fields(record, _OFFER_FIELDS, "Offer")


def assert_title_report(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="TitleReport")
    assert_has_fields(record, _TITLE_REPORT_FIELDS, "TitleReport")


def assert_rofr_notice(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="RofrNotice")
    assert_has_fields(record, _ROFR_NOTICE_FIELDS, "RofrNotice")


def assert_dispute(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="DisputeCase")
    assert_has_fields(record, _DISPUTE_FIELDS, "DisputeCase")


def assert_pledge(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="CollateralPledge")
    assert_has_fields(record, _PLEDGE_FIELDS, "CollateralPledge")


def assert_amendment_event(record: Mapping[str, Any]) -> None:
    assert_common_fields(record, label="AmendmentEvent")
    assert_has_fields(record, _AMENDMENT_FIELDS, "AmendmentEvent")
    assert_amendment_split_exhausts_net(record)


# ---------------------------------------------------------------------------
# Standing invariants stated by the PRD
# ---------------------------------------------------------------------------


def assert_portfolio_ledger_balances(portfolio: Mapping[str, Any]) -> None:
    """PRD 3.1: available plus committed plus deployed equals the whole pool."""
    total = portfolio["total_capital_cents"]
    parts = (
        portfolio["available_capital_cents"],
        portfolio["committed_capital_cents"],
        portfolio["deployed_capital_cents"],
    )
    assert sum(parts) == total, (
        f"portfolio ledger does not add back to the pool: available+committed+deployed={sum(parts)} vs total={total}"
    )


def assert_utilization_and_posture(portfolio: Mapping[str, Any]) -> None:
    """PRD 3.1: utilization is used/total in bps, and posture follows the two-rung ladder."""
    total = portfolio["total_capital_cents"]
    used = portfolio["committed_capital_cents"] + portfolio["deployed_capital_cents"]
    expected_bps = 0 if total == 0 else round_half_up(Decimal(used) * Decimal(10000) / Decimal(total))
    assert portfolio["utilization_bps"] == expected_bps, (
        f"utilization_bps is {portfolio['utilization_bps']}, expected {expected_bps} from used={used} total={total}"
    )
    if expected_bps >= THRESHOLDS["POSTURE_FROZEN_UTILIZATION_BPS"]:
        expected_posture = "FROZEN"
    elif expected_bps >= THRESHOLDS["POSTURE_CONSTRAINED_UTILIZATION_BPS"]:
        expected_posture = "CONSTRAINED"
    else:
        expected_posture = "OPEN"
    assert portfolio["capital_posture"] == expected_posture, (
        f"capital_posture is {portfolio['capital_posture']}, expected {expected_posture} at {expected_bps} bps"
    )


def assert_max_bid_ceiling(valuation: Mapping[str, Any]) -> None:
    """PRD 3.4: max_bid_cents is value_cents times 10500 bps, rounded half up."""
    expected = bps_of(valuation["value_cents"], THRESHOLDS["MAX_BID_MULTIPLIER_BPS"])
    assert valuation["max_bid_cents"] == expected, (
        f"max_bid_cents is {valuation['max_bid_cents']}, expected {expected} from value_cents {valuation['value_cents']}"
    )


def assert_settlement_arithmetic(
    settlement: Mapping[str, Any], expected_open_dispute_count: int = 0
) -> None:
    """PRD 3.7: broker tier keyed on gross, then fee, then holdback, then net."""
    gross = settlement["agreed_consideration_cents"]
    if gross >= THRESHOLDS["BROKER_TIER_HIGH_GROSS_CENTS"]:
        expected_bps = THRESHOLDS["BROKER_FEE_BPS_HIGH"]
    elif gross >= THRESHOLDS["BROKER_TIER_MID_GROSS_CENTS"]:
        expected_bps = THRESHOLDS["BROKER_FEE_BPS_MID"]
    else:
        expected_bps = THRESHOLDS["BROKER_FEE_BPS_LOW"]
    assert settlement["broker_fee_bps"] == expected_bps, (
        f"broker_fee_bps is {settlement['broker_fee_bps']}, expected {expected_bps} on gross {gross}"
    )
    expected_fee = bps_of(gross, expected_bps)
    assert settlement["broker_fee_cents"] == expected_fee, (
        f"broker_fee_cents is {settlement['broker_fee_cents']}, expected {expected_fee}"
    )
    holdback_bps = min(
        expected_open_dispute_count * THRESHOLDS["HOLDBACK_BPS_PER_DISPUTE"], THRESHOLDS["HOLDBACK_BPS_CAP"]
    )
    expected_holdback = bps_of(gross, holdback_bps)
    assert settlement["holdback_cents"] == expected_holdback, (
        f"holdback_cents is {settlement['holdback_cents']}, expected {expected_holdback} at {holdback_bps} bps"
    )
    assert settlement["net_landowner_proceeds_cents"] == gross - expected_holdback, (
        "net_landowner_proceeds_cents is not gross less holdback"
    )
    assert settlement["total_commitment_cents"] == gross + expected_fee, (
        "total_commitment_cents is not gross plus the broker fee"
    )


def assert_escrow_accounts_for_funding(deal_or_settlement: Mapping[str, Any]) -> None:
    """PRD 3.7: the disbursement and the retained holdback together account for the funding."""
    funded = deal_or_settlement["escrow_funded_cents"]
    disbursed = deal_or_settlement["escrow_disbursed_cents"]
    holdback = deal_or_settlement["escrow_holdback_cents"]
    assert disbursed + holdback == funded, (
        f"escrow does not reconcile: disbursed {disbursed} plus holdback {holdback} != funded {funded}"
    )


def assert_amendment_split_exhausts_net(event: Mapping[str, Any]) -> None:
    """PRD 3.8: the two shares always exhaust the net exactly."""
    assert event["net_amount_cents"] == event["gross_amount_cents"] - event["effective_pass_through_cents"], (
        "net_amount_cents is not gross less the effective pass-through"
    )
    expected_landowner = bps_of(event["net_amount_cents"], event["share_bps_applied"])
    assert event["landowner_share_cents"] == expected_landowner, (
        f"landowner_share_cents is {event['landowner_share_cents']}, expected {expected_landowner}"
    )
    assert event["landowner_share_cents"] + event["acquirer_share_cents"] == event["net_amount_cents"], (
        "the landowner and acquirer shares do not exhaust the net"
    )


def assert_pledge_eligible_value(pledge: Mapping[str, Any]) -> None:
    """PRD 3.9: eligible value is zero when ineligible or released, else basis less haircut."""
    if pledge["status"] in ("INELIGIBLE", "RELEASED"):
        assert pledge["eligible_value_cents"] == 0, (
            f"a {pledge['status']} pledge must carry eligible_value_cents 0, got {pledge['eligible_value_cents']}"
        )
        return
    expected = bps_of(pledge["basis_value_cents"], 10000 - pledge["haircut_bps"])
    assert pledge["eligible_value_cents"] == expected, (
        f"eligible_value_cents is {pledge['eligible_value_cents']}, expected {expected} "
        f"from basis {pledge['basis_value_cents']} at haircut {pledge['haircut_bps']} bps"
    )


def assert_borrowing_base(facility: Mapping[str, Any]) -> None:
    """PRD 3.9: the base is the concentration-adjusted pool times the advance rate."""
    adjusted = facility["pledged_eligible_total_cents"] - facility["concentration_excess_cents"]
    expected = bps_of(adjusted, facility["advance_rate_bps"])
    assert facility["borrowing_base_cents"] == expected, (
        f"borrowing_base_cents is {facility['borrowing_base_cents']}, expected {expected} "
        f"from adjusted pool {adjusted} at {facility['advance_rate_bps']} bps"
    )
    expected_state = (
        "BORROWING_BASE_DEFICIT" if facility["advances_outstanding_cents"] > facility["borrowing_base_cents"] else "COMPLIANT"
    )
    assert facility["compliance_state"] == expected_state, (
        f"compliance_state is {facility['compliance_state']}, expected {expected_state}"
    )


def assert_collection_page(meta: Mapping[str, Any], total_count: int, item_count: int, has_more: bool) -> None:
    """PRD 2.3: total_count counts pre-window rows and has_more reports the remainder."""
    assert meta["total_count"] == total_count, f"meta.total_count is {meta['total_count']}, expected {total_count}"
    assert meta["has_more"] is has_more, f"meta.has_more is {meta['has_more']}, expected {has_more}"
    assert item_count <= meta["limit"], f"page returned {item_count} items, above meta.limit {meta['limit']}"


def ids_of(items: Iterable[Dict[str, Any]]) -> list:
    return [item["id"] for item in items]


__all__ = [
    "round_half_up",
    "bps_of",
    "assert_has_fields",
    "assert_fields",
    "assert_fields_match",
    "assert_pairwise_distinct",
    "assert_common_fields",
    "assert_portfolio",
    "assert_facility",
    "assert_tower_company",
    "assert_tower_site",
    "assert_landowner",
    "assert_lease_stream",
    "assert_tenancy",
    "assert_valuation",
    "assert_deal",
    "assert_offer",
    "assert_title_report",
    "assert_rofr_notice",
    "assert_dispute",
    "assert_pledge",
    "assert_amendment_event",
    "assert_portfolio_ledger_balances",
    "assert_utilization_and_posture",
    "assert_max_bid_ceiling",
    "assert_settlement_arithmetic",
    "assert_escrow_accounts_for_funding",
    "assert_amendment_split_exhausts_net",
    "assert_pledge_eligible_value",
    "assert_borrowing_base",
    "assert_collection_page",
    "ids_of",
]
