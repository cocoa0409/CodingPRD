"""Request-payload builders.

Each builder returns a complete, valid payload for one write endpoint and
accepts keyword overrides, so a test that cares about a single field can name
only that field.  Defaults are chosen so the canonical happy path holds: a FRAME
owner-occupied property in a HURRICANE zone, a BASIC_FIRE_EO package, an
appointed STANDARD-tier producer and three verified declinations.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    BASIS_MARKET_SHARE,
    CLOCK_BASE,
    CLOCK_BASE_DATE,
    COMMISSION_TIER_STANDARD,
    CONSTRUCTION_FRAME,
    DECISION_APPROVE,
    ELECTION_ACCEPT,
    ELIGIBILITY_DECISION_ADVANCE,
    INSPECTION_RESULT_PASS,
    MEMBER_STATUS_RUNOFF,
    OCCUPANCY_OWNER,
    PACKAGE_BASIC_FIRE_EO,
    PERIL_HURRICANE,
    PRODUCER_ACTION_SUSPEND,
    REASON_APPETITE,
    REASON_CAT_EXPOSURE,
    REASON_CONDITION,
    REQUIREMENT_CODE_ROOF,
    SEVERITY_MAJOR,
)


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; an override set to ``None`` drops the key entirely."""
    result = dict(payload)
    for key, value in overrides.items():
        if value is _OMIT:
            result.pop(key, None)
        else:
            result[key] = value
    return result


class _Omit:
    """Sentinel meaning "leave this key out of the payload"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def member_insurer_payload(
    name: str = "Carrier One",
    naic_code: str = "10001",
    market_share_pct: Any = 30.0,
    written_premium_share_pct: Any = 10.0,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "name": name,
            "naic_code": naic_code,
            "market_share_pct": market_share_pct,
            "written_premium_share_pct": written_premium_share_pct,
        },
        overrides,
    )


def member_status_payload(status: str = MEMBER_STATUS_RUNOFF, **overrides: Any) -> Dict[str, Any]:
    return _merge({"status": status}, overrides)


def cat_zone_payload(
    code: str = "HUR-01",
    peril: str = PERIL_HURRICANE,
    exposure_cap_cents: int = 100_000_000,
    restricted_min_condition_score: int = 70,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "code": code,
            "peril": peril,
            "exposure_cap_cents": exposure_cap_cents,
            "restricted_min_condition_score": restricted_min_condition_score,
        },
        overrides,
    )


def producer_payload(
    full_name: str = "Pat Agent",
    license_number: str = "P-1001",
    commission_tier: str = COMMISSION_TIER_STANDARD,
    e_and_o_expiry_date: str = "2027-06-30",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": full_name,
            "license_number": license_number,
            "commission_tier": commission_tier,
            "e_and_o_expiry_date": e_and_o_expiry_date,
        },
        overrides,
    )


def agreement_execution_payload(
    agreement_effective_date: str = "2026-08-01", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"agreement_effective_date": agreement_effective_date}, overrides)


def producer_status_action_payload(
    action: str = PRODUCER_ACTION_SUSPEND,
    reason: Optional[str] = "E&O lapse under review",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Rate filings
# ---------------------------------------------------------------------------


def rate_filing_payload(
    cat_zone_id: str,
    expected_zone_version: int,
    peril_package: str = PACKAGE_BASIC_FIRE_EO,
    filed_rate_per_1000_cents: int = 900,
    voluntary_market_avg_rate_per_1000_cents: int = 800,
    effective_date: str = "2026-08-01",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "cat_zone_id": cat_zone_id,
            "peril_package": peril_package,
            "filed_rate_per_1000_cents": filed_rate_per_1000_cents,
            "voluntary_market_avg_rate_per_1000_cents": voluntary_market_avg_rate_per_1000_cents,
            "effective_date": effective_date,
            "expected_zone_version": expected_zone_version,
        },
        overrides,
    )


def filing_review_payload(
    decision: str = DECISION_APPROVE,
    review_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Applicants, properties, applications
# ---------------------------------------------------------------------------


def applicant_payload(
    full_name: str = "Ann Owner",
    email: str = "ann@example.com",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"full_name": full_name, "email": email}, overrides)


def property_payload(
    cat_zone_id: str,
    address_line: str = "1 Shore Rd",
    zip_code: str = "33101",
    construction_type: str = CONSTRUCTION_FRAME,
    roof_age_years: int = 12,
    replacement_cost_cents: int = 100_000_000,
    condition_score: int = 88,
    occupancy: str = OCCUPANCY_OWNER,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "cat_zone_id": cat_zone_id,
            "address_line": address_line,
            "zip_code": zip_code,
            "construction_type": construction_type,
            "roof_age_years": roof_age_years,
            "replacement_cost_cents": replacement_cost_cents,
            "condition_score": condition_score,
            "occupancy": occupancy,
        },
        overrides,
    )


def application_payload(
    property_id: str,
    applicant_id: str,
    requested_dwelling_limit_cents: int = 54_000_000,
    requested_peril_package: str = PACKAGE_BASIC_FIRE_EO,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "property_id": property_id,
            "applicant_id": applicant_id,
            "requested_dwelling_limit_cents": requested_dwelling_limit_cents,
            "requested_peril_package": requested_peril_package,
        },
        overrides,
    )


def declination_payload(
    member_insurer_id: str,
    declined_on: str = "2026-07-03",
    reason_code: str = REASON_CAT_EXPOSURE,
    evidence_reference: str = "DEC-1",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "member_insurer_id": member_insurer_id,
            "declined_on": declined_on,
            "reason_code": reason_code,
            "evidence_reference": evidence_reference,
        },
        overrides,
    )


def three_declination_payloads(
    member_insurer_ids: List[str], declined_on: str = "2026-07-03"
) -> List[Dict[str, Any]]:
    """One declination per distinct carrier, which is what sufficiency counts."""
    reasons = [REASON_CAT_EXPOSURE, REASON_APPETITE, REASON_CONDITION]
    return [
        declination_payload(
            member_insurer_id=member_id,
            declined_on=declined_on,
            reason_code=reasons[index % len(reasons)],
            evidence_reference=f"DEC-{index + 1}",
        )
        for index, member_id in enumerate(member_insurer_ids)
    ]


def eligibility_review_payload(
    decision: str = ELIGIBILITY_DECISION_ADVANCE, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Inspections and requirements
# ---------------------------------------------------------------------------


def inspection_completion_payload(
    observed_condition_score: int = 72,
    result: str = INSPECTION_RESULT_PASS,
    requirements: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "observed_condition_score": observed_condition_score,
        "result": result,
    }
    if requirements is not None:
        payload["requirements"] = requirements
    return _merge(payload, overrides)


def requirement_spec(
    code: str = REQUIREMENT_CODE_ROOF, severity: str = SEVERITY_MAJOR
) -> Dict[str, Any]:
    return {"code": code, "severity": severity}


def requirement_evidence_payload(
    evidence_reference: str = "ROOF-1", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"evidence_reference": evidence_reference}, overrides)


def requirement_clearance_payload(
    note: Optional[str] = "new roof verified", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if note is not None:
        payload["note"] = note
    return _merge(payload, overrides)


def requirement_waiver_payload(
    waiver_reason: str = "documented mitigation accepted", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"waiver_reason": waiver_reason}, overrides)


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


def bind_payload(
    application_id: str, effective_date: str = CLOCK_BASE_DATE, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"application_id": application_id, "effective_date": effective_date}, overrides
    )


def cancellation_payload(
    cancel_reason: str,
    cancel_date: str = CLOCK_BASE_DATE,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"cancel_reason": cancel_reason, "cancel_date": cancel_date}, overrides)


def renewal_payload(effective_date: str = "2027-09-01", **overrides: Any) -> Dict[str, Any]:
    return _merge({"effective_date": effective_date}, overrides)


# ---------------------------------------------------------------------------
# Take-out offers
# ---------------------------------------------------------------------------


def takeout_offer_payload(
    member_insurer_id: str,
    offered_premium_cents: int = 600_000,
    comparable_coverage_flag: bool = True,
    election_deadline_at: str = "2026-10-31T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "member_insurer_id": member_insurer_id,
            "offered_premium_cents": offered_premium_cents,
            "comparable_coverage_flag": comparable_coverage_flag,
            "election_deadline_at": election_deadline_at,
        },
        overrides,
    )


def election_payload(election: str = ELECTION_ACCEPT, **overrides: Any) -> Dict[str, Any]:
    return _merge({"election": election}, overrides)


def withdrawal_payload(reason: str = "capacity pulled", **overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------


def assessment_event_payload(
    cat_zone_id: str,
    trigger_loss_cents: int = 110_000_000,
    reserve_balance_cents_at_trigger: int = 100_000_000,
    allocation_basis: str = BASIS_MARKET_SHARE,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "cat_zone_id": cat_zone_id,
            "trigger_loss_cents": trigger_loss_cents,
            "reserve_balance_cents_at_trigger": reserve_balance_cents_at_trigger,
            "allocation_basis": allocation_basis,
        },
        overrides,
    )


def allocation_run_payload(
    expected_assessment_event_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"expected_assessment_event_version": expected_assessment_event_version},
        overrides,
    )


def assessment_cancellation_payload(
    reason: str = "loss estimate revised below reserves", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


def payment_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"amount_cents": amount_cents}, overrides)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def clock_payload(to_iso8601: str = CLOCK_BASE, **overrides: Any) -> Dict[str, Any]:
    return _merge({"to_iso8601": to_iso8601}, overrides)
