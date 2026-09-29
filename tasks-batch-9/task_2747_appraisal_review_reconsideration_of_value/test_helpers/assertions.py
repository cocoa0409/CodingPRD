"""
Entity-shape and domain-invariant assertions for the Lender Appraisal Review Desk.

Two families live here. The ``assert_<entity>`` helpers check that a response body
carries the field set the PRD declares for that entity, including the presence or
absence of the concurrency quartet. The invariant helpers re-derive a PRD formula
from its inputs and compare it against what the API returned, so an arithmetic
regression is reported as a formula mismatch rather than as an opaque number.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    COMP_SKEW_DIVISOR,
    LTV_CONDITION_BPS,
    LTV_NO_IMPACT_BPS,
    LTV_PRICING_BPS,
    MIN_CLOSED_COMPS,
    MIN_EXHIBITS,
    NARRATIVE_TERM_WEIGHT,
    P_BIAS_SUBSTANTIATED_APPRAISER,
    P_SLA_MISS,
    REQUIRED_SECTIONS,
    REVISION_WEIGHT,
    RULE_CHECK_SEQUENCE,
    W_COMP,
    W_EXHIBIT,
    W_SECTION,
)


# ---------------------------------------------------------------------------
# Rounding and time helpers
# ---------------------------------------------------------------------------
def round_half_up(value) -> int:
    """Round to a whole number with halves rounding away from zero."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def canonical_instant(value: str) -> str:
    """
    Reduce an ISO 8601 UTC instant to a comparable canonical form.

    Timestamps are emitted with exactly three fractional digits and a trailing Z,
    while the instants a test supplies as input are usually written without a
    fractional part. Both spellings denote the same instant, so comparisons go
    through this normaliser rather than through raw string equality.
    """
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"instant must be UTC with a trailing Z: {value!r}"
    core = text[:-1]
    if "." in core:
        head, frac = core.split(".", 1)
        frac = (frac + "000")[:3].rstrip("0")
    else:
        head, frac = core, ""
    return f"{head}.{frac}Z" if frac else f"{head}Z"


def assert_instant(actual: Optional[str], expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants denote the same moment."""
    assert actual is not None, f"{label} must not be null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_millisecond_timestamp(value: str, label: str = "timestamp") -> None:
    """Assert a stamp is ISO 8601 UTC with exactly three fractional digits and a Z."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert value.endswith("Z"), f"{label} must end with Z: {value!r}"
    assert "." in value, f"{label} must carry a fractional part: {value!r}"
    fractional = value[:-1].split(".", 1)[1]
    assert len(fractional) == 3, (
        f"{label} must carry exactly 3 fractional digits, got {value!r}"
    )
    assert is_iso8601_timestamp(value), f"{label} is not a valid ISO 8601 stamp: {value!r}"


# ---------------------------------------------------------------------------
# Common field families
# ---------------------------------------------------------------------------
def assert_common_fields(entity: Dict[str, Any], label: str = "entity") -> None:
    """Assert the four fields every versioned resource carries."""
    assert is_valid_uuid(entity.get("id")), f"{label}.id must be a UUID: {entity.get('id')!r}"
    assert_millisecond_timestamp(entity.get("created_at"), f"{label}.created_at")
    assert_millisecond_timestamp(entity.get("updated_at"), f"{label}.updated_at")
    assert isinstance(entity.get("version"), int), f"{label}.version must be an integer"
    assert entity["version"] >= 1, f"{label}.version must start at 1 or above"


def assert_event_fields(entity: Dict[str, Any], label: str = "row") -> None:
    """
    Assert the field family of an append-only row.

    Rule-check results, appraiser communications and value revisions are never
    updated after they are written, so they expose an id and a creation stamp and
    carry neither an update stamp nor a concurrency version.
    """
    assert is_valid_uuid(entity.get("id")), f"{label}.id must be a UUID: {entity.get('id')!r}"
    assert_millisecond_timestamp(entity.get("created_at"), f"{label}.created_at")
    assert "version" not in entity, f"{label} must not expose a version field"
    assert "updated_at" not in entity, f"{label} must not expose an updated_at field"


def assert_fields_present(entity: Dict[str, Any], names: Iterable[str],
                          label: str = "entity") -> None:
    missing = [n for n in names if n not in entity]
    assert not missing, f"{label} is missing fields {missing}"


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------
LOAN_FILE_FIELDS = [
    "loan_number", "loan_purpose", "market_type", "risk_tier", "loan_amount_cents",
    "contract_price_cents", "borrower_display_name", "underwriting_status",
    "collateral_status", "value_of_record_appraisal_id",
    "current_appraised_value_cents", "effective_value_cents", "ltv_bps",
    "decision_impact", "rov_request_count",
]


def assert_loan_file(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "loan_file")
    assert_fields_present(data, LOAN_FILE_FIELDS, "loan_file")
    assert data["loan_purpose"] in ("PURCHASE", "REFINANCE")
    assert data["market_type"] in ("URBAN", "SUBURBAN", "RURAL")
    assert data["risk_tier"] in ("LOW", "STANDARD", "ELEVATED", "HIGH")
    assert data["loan_amount_cents"] > 0
    if data["loan_purpose"] == "REFINANCE":
        assert data["contract_price_cents"] is None, (
            "contract_price_cents must be null on a REFINANCE loan file"
        )
    else:
        assert data["contract_price_cents"] > 0


APPRAISER_FIELDS = [
    "full_name", "license_number", "license_state", "panel_status",
    "probation_started_at", "removal_reason", "performance_score_bps",
    "lifetime_performance_score_bps", "revision_rate_bps", "total_appraisal_count",
    "substantiated_bias_count", "sla_miss_count", "open_assignment_count",
    "completed_assignment_count", "panel_membership_count",
]


def assert_appraiser(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "appraiser")
    assert_fields_present(data, APPRAISER_FIELDS, "appraiser")
    assert data["panel_status"] in ("ACTIVE", "PROBATION", "SUSPENDED", "REMOVED")
    assert len(data["license_state"]) == 2 and data["license_state"].isupper()
    for field in ("performance_score_bps", "lifetime_performance_score_bps"):
        assert 0 <= data[field] <= 10000, f"appraiser.{field} must be clamped to 0..10000"


AMC_FIELDS = [
    "name", "sla_response_hours", "concurrent_dispute_capacity",
    "escalation_budget_cents", "panel_status", "ytd_escalation_spend_cents",
    "sla_breach_count", "open_dispute_count",
]


def assert_amc(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "amc")
    assert_fields_present(data, AMC_FIELDS, "amc")
    assert data["sla_response_hours"] >= 1
    assert data["concurrent_dispute_capacity"] >= 1
    assert data["escalation_budget_cents"] >= 0
    assert data["panel_status"] in ("ACTIVE", "PROBATION", "SUSPENDED")


def assert_panel_membership(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "panel_membership")
    assert_fields_present(
        data, ["appraiser_id", "amc_id", "coverage_state", "tier", "status"],
        "panel_membership",
    )
    assert data["tier"] in ("GENERAL", "COMPLEX", "REVIEW_SPECIALIST")
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


APPRAISAL_FIELDS = [
    "loan_file_id", "appraiser_id", "amc_id", "supersedes_appraisal_id",
    "report_form_type", "effective_date", "reported_value_cents", "sections_present",
    "exhibit_count", "narrative_text", "subject_census_tract_band", "review_status",
    "bias_screen_status", "quarantine_return_status", "completeness_score_bps",
    "eligible_comp_count", "closed_comp_count", "max_gross_adjustment_bps",
    "max_net_adjustment_bps", "indicated_value_cents", "variance_vs_reported_bps",
    "bias_risk_index", "current_value_cents", "rule_check_fail_count",
    "rule_check_warn_count",
]


def assert_appraisal(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "appraisal")
    assert_fields_present(data, APPRAISAL_FIELDS, "appraisal")
    assert data["report_form_type"] in ("FORM_1004", "FORM_1073", "FORM_2055")
    assert data["reported_value_cents"] > 0
    assert isinstance(data["sections_present"], list)
    assert len(set(data["sections_present"])) == len(data["sections_present"]), (
        "sections_present must not contain duplicates"
    )
    assert data["exhibit_count"] >= 0
    assert data["subject_census_tract_band"] in ("A", "B", "C", "D")


COMPARABLE_FIELDS = [
    "appraisal_id", "street_address", "sale_price_cents", "gross_adjustment_cents",
    "net_adjustment_cents", "distance_miles", "sale_date", "sale_status",
    "dwelling_type", "census_tract_band", "included_in_grid", "adjusted_price_cents",
    "gross_adjustment_bps", "net_adjustment_bps",
]


def assert_comparable(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "comparable")
    assert_fields_present(data, COMPARABLE_FIELDS, "comparable")
    assert data["sale_price_cents"] > 0
    assert data["distance_miles"] >= 0
    assert data["sale_status"] in ("CLOSED", "PENDING", "ACTIVE_LISTING")
    assert data["dwelling_type"] in ("SFR", "CONDO", "TOWNHOUSE", "MULTI_2_4")
    assert data["census_tract_band"] in ("A", "B", "C", "D")
    assert isinstance(data["included_in_grid"], bool)
    assert_comparable_metrics(data)


def assert_rule_check_row(data: Dict[str, Any]) -> None:
    assert_event_fields(data, "rule_check")
    assert_fields_present(
        data, ["appraisal_id", "sequence_no", "check_code", "outcome",
               "observed_value", "detail"],
        "rule_check",
    )
    assert 1 <= data["sequence_no"] <= 8
    assert data["check_code"] in RULE_CHECK_SEQUENCE
    assert data["outcome"] in ("PASS", "WARN", "FAIL")


def assert_bias_flag(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "bias_flag")
    assert_fields_present(
        data, ["appraisal_id", "source", "indicator_code", "matched_text",
               "severity_weight", "status", "adjudicated_by_user_id", "rationale"],
        "bias_flag",
    )
    assert data["source"] in ("NARRATIVE", "COMP_SELECTION")
    assert data["status"] in ("OPEN", "CLEARED", "SUBSTANTIATED")
    assert data["severity_weight"] >= 0


def assert_communication(data: Dict[str, Any]) -> None:
    assert_event_fields(data, "communication")
    assert_fields_present(
        data, ["appraisal_id", "sender_role", "sender_user_id", "recipient",
               "intent", "body", "sent_at"],
        "communication",
    )
    assert data["recipient"] in ("APPRAISER", "AMC", "LENDER_DESK")
    assert_millisecond_timestamp(data["sent_at"], "communication.sent_at")


DESK_REVIEW_FIELDS = [
    "appraisal_id", "status", "created_by_user_id", "submitted_by_user_id",
    "decided_by_user_id", "risk_tier_at_review", "preliminary_quality_score_bps",
    "final_quality_score_bps", "required_escalation", "decision_action",
    "reviewer_note", "findings_note", "decision_note",
]


def assert_desk_review(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "desk_review")
    assert_fields_present(data, DESK_REVIEW_FIELDS, "desk_review")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "ACCEPTED", "ESCALATED", "RETURNED", "CLOSED",
    )
    assert data["risk_tier_at_review"] in ("LOW", "STANDARD", "ELEVATED", "HIGH")
    assert 0 <= data["preliminary_quality_score_bps"]


ESCALATION_FIELDS = [
    "desk_review_id", "amc_id", "assigned_appraiser_id", "escalation_type", "status",
    "due_at", "inspection_window_start", "inspection_window_end", "base_fee_cents",
    "rush_surcharge_cents", "discount_pct_bps", "total_cost_cents",
    "resulting_value_cents", "documentation_note", "cancel_reason",
]


def assert_escalation_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "escalation_order")
    assert_fields_present(data, ESCALATION_FIELDS, "escalation_order")
    assert data["escalation_type"] in ("FIELD_REVIEW", "SECOND_APPRAISAL")
    assert data["status"] in (
        "PENDING_ASSIGNMENT", "ASSIGNED", "REASSIGNMENT_REQUIRED", "COMPLETED",
        "CANCELLED",
    )


ROV_FIELDS = [
    "loan_file_id", "appraisal_id", "borrower_statement", "requested_value_cents",
    "round_number", "status", "admissible_evidence_count", "response_deadline_at",
    "appraiser_responded_at", "responded_late", "outcome", "revised_value_cents",
    "intake_note", "response_note", "next_round_reason", "closure_note",
]


def assert_rov_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "rov_request")
    assert_fields_present(data, ROV_FIELDS, "rov_request")
    assert data["status"] in (
        "INTAKE", "AWAITING_APPRAISER", "RESPONDED", "CLOSED_AFFIRMED",
        "CLOSED_REVISED",
    )
    assert 1 <= data["round_number"] <= 2
    assert isinstance(data["responded_late"], bool)


def assert_evidence_item(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "evidence_item")
    assert_fields_present(
        data, ["rov_request_id", "evidence_type", "street_address", "sale_price_cents",
               "sale_date", "distance_miles", "citation_note", "admissible",
               "inadmissible_reason", "round_number"],
        "evidence_item",
    )
    assert data["evidence_type"] in (
        "CLOSED_SALE", "ACTIVE_LISTING_WITH_CONTRACT", "DATA_ERROR_CITATION",
        "OPINION_STATEMENT",
    )
    assert isinstance(data["admissible"], bool)
    if data["admissible"]:
        assert data["inadmissible_reason"] is None
    else:
        assert data["inadmissible_reason"] in (
            "TYPE_NOT_ADMISSIBLE", "MISSING_REQUIRED_ATTRIBUTE", "STALE_SALE_DATE",
            "DISTANCE_EXCEEDED", "DUPLICATE_OF_GRID_COMP",
        )


DISPUTE_FIELDS = [
    "appraisal_id", "amc_id", "appraiser_id", "dispute_basis", "review_slot_start",
    "review_slot_end", "response_deadline_at", "appraiser_position",
    "response_summary", "appraiser_responded_at", "responded_late", "status",
    "resolution", "resolved_value_cents", "resolution_note",
]


def assert_dispute_case(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "dispute_case")
    assert_fields_present(data, DISPUTE_FIELDS, "dispute_case")
    assert data["dispute_basis"] in (
        "COMP_SELECTION", "ADJUSTMENT_SUPPORT", "VALUE_OPINION", "USPAP_COMPLIANCE",
    )
    assert data["status"] in (
        "OPEN", "APPRAISER_RESPONDED", "RESOLVED_UPHELD", "RESOLVED_OVERTURNED",
        "RESOLVED_BY_DEFAULT",
    )


REVISION_FIELDS = [
    "appraisal_id", "source_type", "source_ref_id", "prior_value_cents",
    "new_value_cents", "delta_cents", "delta_bps", "is_compensating",
    "ltv_bps_before", "ltv_bps_after", "decision_impact_before",
    "decision_impact_after", "documentation_note",
]


def assert_value_revision(data: Dict[str, Any]) -> None:
    assert_event_fields(data, "value_revision")
    assert_fields_present(data, REVISION_FIELDS, "value_revision")
    assert data["source_type"] in ("ROV", "FIELD_REVIEW", "SECOND_APPRAISAL", "DISPUTE")
    assert isinstance(data["is_compensating"], bool)
    assert data["delta_cents"] == data["new_value_cents"] - data["prior_value_cents"], (
        "delta_cents must be new_value_cents minus prior_value_cents"
    )
    expected_bps = round_half_up(
        10000 * abs(data["delta_cents"]) / data["prior_value_cents"]
    )
    assert data["delta_bps"] == expected_bps, (
        f"delta_bps should be {expected_bps}, got {data['delta_bps']}"
    )
    assert data["delta_bps"] >= 0, "delta_bps is an absolute magnitude"


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_comparable_metrics(row: Dict[str, Any]) -> None:
    """
    Re-derive the three per-row comparable figures from the row's own inputs.

    The adjusted price is the sale price plus the signed net adjustment. Both ratio
    fields are basis-point shares of the sale price, and the net share is taken from
    the absolute value of the net adjustment, so an equal downward adjustment
    reports the same ratio as an upward one.
    """
    expected_adjusted = row["sale_price_cents"] + row["net_adjustment_cents"]
    assert row["adjusted_price_cents"] == expected_adjusted, (
        f"adjusted_price_cents should be {expected_adjusted}, got {row['adjusted_price_cents']}"
    )
    expected_gross = round_half_up(
        10000 * row["gross_adjustment_cents"] / row["sale_price_cents"]
    )
    assert row["gross_adjustment_bps"] == expected_gross, (
        f"gross_adjustment_bps should be {expected_gross}, got {row['gross_adjustment_bps']}"
    )
    expected_net = round_half_up(
        10000 * abs(row["net_adjustment_cents"]) / row["sale_price_cents"]
    )
    assert row["net_adjustment_bps"] == expected_net, (
        f"net_adjustment_bps should be {expected_net}, got {row['net_adjustment_bps']}"
    )


def expected_completeness_bps(sections_present: List[str], closed_comp_count: int,
                              exhibit_count: int) -> int:
    """
    Re-derive the completeness score with the rounding order the PRD pins.

    Each of the three components is rounded to whole basis points before it is
    weighted; the weighted sum is then rounded once more. Weighting the unrounded
    components produces a different answer and is forbidden.
    """
    section_hits = len([s for s in REQUIRED_SECTIONS if s in sections_present])
    section_bps = round_half_up(10000 * section_hits / len(REQUIRED_SECTIONS))
    comp_bps = round_half_up(
        10000 * min(closed_comp_count, MIN_CLOSED_COMPS) / MIN_CLOSED_COMPS
    )
    exhibit_bps = round_half_up(10000 * min(exhibit_count, MIN_EXHIBITS) / MIN_EXHIBITS)
    return round_half_up(
        W_SECTION * section_bps + W_COMP * comp_bps + W_EXHIBIT * exhibit_bps
    )


def assert_completeness_score(appraisal: Dict[str, Any], closed_comp_count: int) -> None:
    expected = expected_completeness_bps(
        appraisal["sections_present"], closed_comp_count, appraisal["exhibit_count"]
    )
    assert appraisal["completeness_score_bps"] == expected, (
        f"completeness_score_bps should be {expected}, "
        f"got {appraisal['completeness_score_bps']}"
    )


def expected_indicated_value(adjusted_prices: List[int]) -> Optional[int]:
    """
    Re-derive the reconciled indicated value with the pinned rounding order.

    Each in-grid comparable's adjusted price is divided by the comparable count and
    that quotient is rounded to whole cents first; only then are the rounded
    quotients summed. Summing first and dividing once is forbidden and gives a
    different answer whenever the remainders do not cancel.
    """
    n = len(adjusted_prices)
    if n == 0:
        return None
    return sum(round_half_up(Decimal(p) / Decimal(n)) for p in adjusted_prices)


def expected_variance_bps(indicated: Optional[int], reported: int) -> Optional[int]:
    if indicated is None:
        return None
    return round_half_up(10000 * abs(indicated - reported) / reported)


def assert_rule_check_battery(rows: List[Dict[str, Any]]) -> None:
    """
    Assert a rule-check run wrote exactly eight rows in the pinned sequence.

    The battery always emits eight rows and the listing returns them in ascending
    sequence number, which is the emission order of the producing run.
    """
    assert len(rows) == len(RULE_CHECK_SEQUENCE), (
        f"a rule-check run writes exactly {len(RULE_CHECK_SEQUENCE)} rows, got {len(rows)}"
    )
    assert [r["sequence_no"] for r in rows] == list(range(1, len(RULE_CHECK_SEQUENCE) + 1))
    assert [r["check_code"] for r in rows] == RULE_CHECK_SEQUENCE
    for row in rows:
        assert_rule_check_row(row)


def outcome_of(rows: List[Dict[str, Any]], check_code: str) -> str:
    for row in rows:
        if row["check_code"] == check_code:
            return row["outcome"]
    raise AssertionError(f"no rule-check row for {check_code}")


def row_of(rows: List[Dict[str, Any]], check_code: str) -> Dict[str, Any]:
    for row in rows:
        if row["check_code"] == check_code:
            return row
    raise AssertionError(f"no rule-check row for {check_code}")


def expected_bias_risk_index(narrative_hits: int, comp_skew_bps: int) -> int:
    """Twelve points per matched term plus the rounded skew share, capped at 100."""
    return min(
        100,
        NARRATIVE_TERM_WEIGHT * narrative_hits
        + round_half_up(Decimal(comp_skew_bps) / Decimal(COMP_SKEW_DIVISOR)),
    )


def expected_decision_impact(ltv_bps: int) -> str:
    """
    Map a loan-to-value ratio onto its decision impact band.

    The band boundaries are inclusive upper bounds, so a loan at exactly 8000 basis
    points is NO_IMPACT rather than PRICING_ADJUSTMENT.
    """
    if ltv_bps <= LTV_NO_IMPACT_BPS:
        return "NO_IMPACT"
    if ltv_bps <= LTV_PRICING_BPS:
        return "PRICING_ADJUSTMENT"
    if ltv_bps <= LTV_CONDITION_BPS:
        return "CONDITION_REQUIRED"
    return "DENIAL_RECOMMENDED"


def expected_ltv_bps(loan_amount_cents: int, effective_value_cents: int) -> int:
    return round_half_up(10000 * loan_amount_cents / effective_value_cents)


def assert_loan_value_chain(loan: Dict[str, Any]) -> None:
    """
    Assert a loan file's derived value fields agree with each other.

    The effective value is the lesser of the current appraised value and the
    contract price on a purchase and the current appraised value itself on a
    refinance; the ratio and the impact band follow from that effective value.
    """
    if loan["current_appraised_value_cents"] is None:
        assert loan["effective_value_cents"] is None
        assert loan["ltv_bps"] is None
        assert loan["decision_impact"] is None
        return
    current = loan["current_appraised_value_cents"]
    if loan["loan_purpose"] == "PURCHASE":
        expected_effective = min(current, loan["contract_price_cents"])
    else:
        expected_effective = current
    assert loan["effective_value_cents"] == expected_effective, (
        f"effective_value_cents should be {expected_effective}, "
        f"got {loan['effective_value_cents']}"
    )
    expected_ratio = expected_ltv_bps(loan["loan_amount_cents"], expected_effective)
    assert loan["ltv_bps"] == expected_ratio, (
        f"ltv_bps should be {expected_ratio}, got {loan['ltv_bps']}"
    )
    expected_band = expected_decision_impact(expected_ratio)
    assert loan["decision_impact"] == expected_band, (
        f"decision_impact should be {expected_band}, got {loan['decision_impact']}"
    )


def expected_performance_score(revision_rate_bps: int, substantiated_bias_count: int,
                               sla_miss_count: int) -> int:
    """A perfect 10000 less the revision, bias and service-level penalties, clamped."""
    score = (
        10000
        - round_half_up(Decimal(str(REVISION_WEIGHT)) * Decimal(revision_rate_bps))
        - P_BIAS_SUBSTANTIATED_APPRAISER * substantiated_bias_count
        - P_SLA_MISS * sla_miss_count
    )
    return max(0, min(10000, score))


def assert_escalation_cost_breakdown(order: Dict[str, Any]) -> None:
    """Assert the four cost fields of a priced order agree with one another."""
    subtotal = order["base_fee_cents"] + order["rush_surcharge_cents"]
    expected_discount = round_half_up(
        Decimal(subtotal) * Decimal(order["discount_pct_bps"]) / Decimal(10000)
    )
    expected_total = subtotal - expected_discount
    assert order["total_cost_cents"] == expected_total, (
        f"total_cost_cents should be {expected_total} "
        f"(subtotal {subtotal} less discount {expected_discount}), "
        f"got {order['total_cost_cents']}"
    )


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """Assert a listing came back oldest first, which is the only sanctioned order."""
    stamps = [canonical_instant(r["created_at"]) for r in rows]
    assert stamps == sorted(stamps), f"rows are not in ascending created_at order: {stamps}"


def assert_pagination_meta(meta: Dict[str, Any], total_count: int, limit: int,
                           offset: int, has_more: bool) -> None:
    assert meta["total_count"] == total_count, (
        f"total_count should be {total_count}, got {meta['total_count']}"
    )
    assert meta["limit"] == limit, f"limit should be {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"offset should be {offset}, got {meta['offset']}"
    assert meta["has_more"] is has_more, (
        f"has_more should be {has_more}, got {meta['has_more']}"
    )
