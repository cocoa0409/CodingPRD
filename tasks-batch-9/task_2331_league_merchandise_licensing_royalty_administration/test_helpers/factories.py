"""Request-payload factories.

Each factory returns only the fields a client is allowed to send. Server-computed and
server-managed fields are never included: the PRD says a request body carrying such a
field has it silently ignored, so tests that probe that behaviour add it explicitly.
Every factory accepts ``**overrides`` to reshape one field without rebuilding the body.
"""

from typing import Any, Dict, List, Optional

from .constants import DEFAULT_CLOCK_INSTANT


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def clock_payload(instant: str = DEFAULT_CLOCK_INSTANT, **overrides) -> Dict[str, Any]:
    return _merge({"current_utc": instant}, overrides)


# ---------------------------------------------------------------------------
# Product categories
# ---------------------------------------------------------------------------

#: The three-band jersey schedule used across the suite: 12% up to 20 000 cents of a
#: hundred, 10% in the middle band and 8% above.
JERSEY_TIER_SCHEDULE: List[Dict[str, Any]] = [
    {"from_cents": 0, "to_cents": 2000000, "rate_bps": 1200},
    {"from_cents": 2000000, "to_cents": 5000000, "rate_bps": 1000},
    {"from_cents": 5000000, "to_cents": None, "rate_bps": 800},
]


def jersey_category_payload(**overrides) -> Dict[str, Any]:
    """A fully specified jersey category: tiered schedule, caps and hard limits."""
    return _merge(
        {
            "category_code": "JERSEY",
            "display_name": "Authentic Jerseys",
            "base_royalty_rate_bps": 1200,
            "tier_schedule": [dict(band) for band in JERSEY_TIER_SCHEDULE],
            "closeout_rate_bps": 500,
            "exclusivity_allowed": True,
            "minimum_guarantee_floor_cents": 1000000,
            "mark_usage_class": "LEAGUE_CLUB_AND_PLAYER",
            "closeout_cap_pct_bps": 1500,
            "closeout_hard_limit_bps": 4000,
            "deduction_cap_pct_bps": 500,
            "deduction_hard_limit_bps": 2000,
            "advance_floor_bps_of_mg": 2500,
            "central_licensing_default": True,
        },
        overrides,
    )


def minimal_category_payload(
    category_code: str = "NOVELTY",
    display_name: str = "Novelty Goods",
    **overrides,
) -> Dict[str, Any]:
    """A category that omits every optional cap so the declared defaults apply."""
    return _merge(
        {
            "category_code": category_code,
            "display_name": display_name,
            "base_royalty_rate_bps": 1000,
            "tier_schedule": [{"from_cents": 0, "to_cents": None, "rate_bps": 1000}],
            "closeout_rate_bps": 400,
            "exclusivity_allowed": False,
            "minimum_guarantee_floor_cents": 500000,
            "mark_usage_class": "LEAGUE_AND_CLUB",
        },
        overrides,
    )


def headwear_category_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "category_code": "HEADWEAR",
            "display_name": "Caps and hats",
            "base_royalty_rate_bps": 1000,
            "tier_schedule": [{"from_cents": 0, "to_cents": None, "rate_bps": 1000}],
            "closeout_rate_bps": 400,
            "exclusivity_allowed": False,
            "minimum_guarantee_floor_cents": 500000,
            "mark_usage_class": "LEAGUE_AND_CLUB",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Clubs and players
# ---------------------------------------------------------------------------


def club_payload(
    club_code: str = "ATL",
    market_name: str = "Atlanta",
    revenue_share_units: int = 5,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "club_code": club_code,
            "market_name": market_name,
            "revenue_share_units": revenue_share_units,
        },
        overrides,
    )


def player_payload(full_name: str = "Marcus Vale", **overrides) -> Dict[str, Any]:
    return _merge({"full_name": full_name}, overrides)


def group_licensing_payload(opt_in: bool, **overrides) -> Dict[str, Any]:
    return _merge({"opt_in": opt_in}, overrides)


def individual_grant_payload(category_id: str, granted: bool = True, **overrides) -> Dict[str, Any]:
    return _merge({"category_id": category_id, "granted": granted}, overrides)


# ---------------------------------------------------------------------------
# Mark rights
# ---------------------------------------------------------------------------


def league_mark_payload(
    mark_code: str = "LEAGUE_SHIELD",
    royalty_share_bps: int = 0,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "mark_code": mark_code,
            "owner_type": "LEAGUE",
            "usage_class": "PRIMARY",
            "royalty_share_bps": royalty_share_bps,
        },
        overrides,
    )


def club_mark_payload(
    club_id: str,
    mark_code: str = "ATL_PRIMARY",
    royalty_share_bps: int = 0,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "mark_code": mark_code,
            "owner_type": "CLUB",
            "club_id": club_id,
            "usage_class": "PRIMARY",
            "royalty_share_bps": royalty_share_bps,
        },
        overrides,
    )


def player_group_mark_payload(
    player_id: str,
    mark_code: str = "PLAYER_GROUP_POOL",
    royalty_share_bps: int = 0,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "mark_code": mark_code,
            "owner_type": "PLAYER_GROUP",
            "player_id": player_id,
            "usage_class": "SECONDARY",
            "royalty_share_bps": royalty_share_bps,
        },
        overrides,
    )


def player_individual_mark_payload(
    player_id: str,
    mark_code: str = "PLAYER_VALE",
    royalty_share_bps: int = 0,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "mark_code": mark_code,
            "owner_type": "PLAYER_INDIVIDUAL",
            "player_id": player_id,
            "usage_class": "SECONDARY",
            "royalty_share_bps": royalty_share_bps,
        },
        overrides,
    )


def mark_status_payload(action: str, **overrides) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ---------------------------------------------------------------------------
# Licensees
# ---------------------------------------------------------------------------


def licensee_payload(
    legal_name: str = "Summit Apparel Ltd",
    contact_email: str = "contracts@summitapparel.example",
    home_country_code: str = "US",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": legal_name,
            "contact_email": contact_email,
            "home_country_code": home_country_code,
        },
        overrides,
    )


def licensee_status_payload(action: str, **overrides) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


def activate_licensee_payload(vendor_compliance_certified: bool = True, **overrides) -> Dict[str, Any]:
    return _merge(
        {"action": "ACTIVATE", "vendor_compliance_certified": vendor_compliance_certified},
        overrides,
    )


# ---------------------------------------------------------------------------
# Agreements
# ---------------------------------------------------------------------------


def agreement_payload(
    licensee_id: str,
    category_id: str,
    minimum_guarantee_cents: int = 1000000,
    required_advance_cents: int = 250000,
    term_start_date: str = "2026-01-01",
    term_end_date: str = "2027-12-31",
    exclusivity_mode: str = "NON_EXCLUSIVE",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "licensee_id": licensee_id,
            "category_id": category_id,
            "exclusivity_mode": exclusivity_mode,
            "minimum_guarantee_cents": minimum_guarantee_cents,
            "required_advance_cents": required_advance_cents,
            "term_start_date": term_start_date,
            "term_end_date": term_end_date,
        },
        overrides,
    )


def contract_status_payload(action: str, **overrides) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


def advance_payment_payload(amount_cents: int, **overrides) -> Dict[str, Any]:
    return _merge({"amount_cents": amount_cents}, overrides)


def annual_true_up_payload(contract_year: int = 1, **overrides) -> Dict[str, Any]:
    return _merge({"contract_year": contract_year}, overrides)


def territory_grant_payload(
    territory_code: str = "US",
    channel_class: str = "ALL",
    effective_from: str = "2026-01-01",
    effective_to: str = "2028-01-01",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "territory_code": territory_code,
            "channel_class": channel_class,
            "effective_from": effective_from,
            "effective_to": effective_to,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Product submissions and sample reviews
# ---------------------------------------------------------------------------


def product_submission_payload(
    mark_ids: List[str],
    sku_class: str = "JERSEY",
    product_name: str = "Home Replica Jersey",
    retail_price_cents: int = 11999,
    sample_required: bool = False,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "sku_class": sku_class,
            "product_name": product_name,
            "mark_ids": list(mark_ids),
            "retail_price_cents": retail_price_cents,
            "sample_required": sample_required,
        },
        overrides,
    )


def submission_review_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def sample_review_payload(
    verdict: str,
    defect_codes: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"verdict": verdict}
    if defect_codes is not None:
        payload["defect_codes"] = list(defect_codes)
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Retailer authorizations
# ---------------------------------------------------------------------------


def retailer_authorization_payload(
    expected_licensee_version: int,
    retailer_name: str = "Metro Sports",
    channel_class: str = "DEPARTMENT",
    sku_classes: Optional[List[str]] = None,
    authorized_from: str = "2026-01-01",
    authorized_to: str = "2028-12-31",
    closeout_allowed: bool = False,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "retailer_name": retailer_name,
            "channel_class": channel_class,
            "sku_classes": list(sku_classes) if sku_classes is not None else ["JERSEY"],
            "authorized_from": authorized_from,
            "authorized_to": authorized_to,
            "closeout_allowed": closeout_allowed,
            "expected_licensee_version": expected_licensee_version,
        },
        overrides,
    )


def authorization_status_payload(action: str, **overrides) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ---------------------------------------------------------------------------
# Royalty reports
# ---------------------------------------------------------------------------


def channel_line(
    retailer_authorization_id: str,
    gross_sales_cents: int,
    units: int = 1000,
    channel_class: str = "DEPARTMENT",
    closeout_sales_cents: int = 0,
    deductions_cents: int = 0,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "channel_class": channel_class,
            "retailer_authorization_id": retailer_authorization_id,
            "gross_sales_cents": gross_sales_cents,
            "units": units,
            "closeout_sales_cents": closeout_sales_cents,
            "deductions_cents": deductions_cents,
        },
        overrides,
    )


def royalty_report_payload(
    agreement_id: str,
    period_quarter: str,
    channel_lines: List[Dict[str, Any]],
    expected_agreement_version: int,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "agreement_id": agreement_id,
            "period_quarter": period_quarter,
            "channel_lines": [dict(line) for line in channel_lines],
            "expected_agreement_version": expected_agreement_version,
        },
        overrides,
    )


def report_review_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Audit engagements
# ---------------------------------------------------------------------------


def audit_engagement_payload(
    agreement_id: str, scope_quarters: List[str], **overrides
) -> Dict[str, Any]:
    return _merge(
        {"agreement_id": agreement_id, "scope_quarters": list(scope_quarters)}, overrides
    )


def audited_quarter(
    period_quarter: str,
    audited_gross_sales_cents: int,
    audited_closeout_cents: int = 0,
    audited_deductions_cents: int = 0,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "period_quarter": period_quarter,
            "audited_gross_sales_cents": audited_gross_sales_cents,
            "audited_closeout_cents": audited_closeout_cents,
            "audited_deductions_cents": audited_deductions_cents,
        },
        overrides,
    )


def issue_findings_payload(audited_quarters: List[Dict[str, Any]], **overrides) -> Dict[str, Any]:
    return _merge({"audited_quarters": [dict(q) for q in audited_quarters]}, overrides)


def dispute_payload(dispute_note: str = "Restated units disputed", **overrides) -> Dict[str, Any]:
    return _merge({"dispute_note": dispute_note}, overrides)


def settle_payload(
    settlement_basis: str = "FINDINGS",
    negotiated_cents: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"settlement_basis": settlement_basis}
    if negotiated_cents is not None:
        payload["negotiated_cents"] = negotiated_cents
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Enforcement actions
# ---------------------------------------------------------------------------


def enforcement_action_payload(
    venue_type: str = "ONLINE",
    venue_reference: str = "marketplace-listing-4102",
    target_name: str = "BargainShield",
    estimated_units: int = 120,
    estimated_retail_cents: int = 360000,
    suspected_licensee_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "venue_type": venue_type,
        "venue_reference": venue_reference,
        "target_name": target_name,
        "estimated_units": estimated_units,
        "estimated_retail_cents": estimated_retail_cents,
    }
    if suspected_licensee_id is not None:
        payload["suspected_licensee_id"] = suspected_licensee_id
    return _merge(payload, overrides)


def enforcement_status_payload(action: str, **overrides) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ---------------------------------------------------------------------------
# Distribution runs and quarter close
# ---------------------------------------------------------------------------


def distribution_run_payload(
    period_quarter: str, league_admin_rate_bps: int = 800, **overrides
) -> Dict[str, Any]:
    return _merge(
        {"period_quarter": period_quarter, "league_admin_rate_bps": league_admin_rate_bps},
        overrides,
    )


def run_version_payload(expected_run_version: int, **overrides) -> Dict[str, Any]:
    return _merge({"expected_run_version": expected_run_version}, overrides)


def quarter_close_payload(as_of_quarter: str, **overrides) -> Dict[str, Any]:
    return _merge({"as_of_quarter": as_of_quarter}, overrides)
