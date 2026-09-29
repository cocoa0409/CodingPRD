"""Request payload factories.

Each factory returns only the fields a client is allowed to send, with defaults
for the optional ones, and accepts **overrides so a test can pin any single
field. Server-derived fields never appear in a payload.
"""
from typing import Any, Dict, List, Optional

from .constants import AUG_01, CLOCK_DEFAULT


def _payload(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------

def clock_payload(current_utc: str = CLOCK_DEFAULT, **overrides: Any) -> Dict[str, Any]:
    return _payload({"current_utc": current_utc}, overrides)


# --------------------------------------------------------------------------
# Owners and stores
# --------------------------------------------------------------------------

def owner_payload(
    legal_name: str = "Rio Retail LLC",
    ownership_type: str = "LLC",
    tax_id_last4: str = "4417",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "legal_name": legal_name,
            "ownership_type": ownership_type,
            "tax_id_last4": tax_id_last4,
        },
        overrides,
    )


def store_payload(
    owner_id: str,
    store_name: str = "Rio Convenience",
    state_code: str = "TX",
    store_type: str = "CONVENIENCE",
    checkout_lane_count: int = 2,
    staple_shelf_linear_feet: int = 30,
    annual_gross_sales_cents: int = 36000000,
    annual_staple_sales_cents: int = 20000000,
    max_terminal_slots: int = 2,
    tax_rate_bps: Optional[int] = 825,
    hardship_designated: Optional[bool] = True,
    predecessor_store_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """The convenience store profile the suite anchors on: 5,555 staple basis
    points, a two-lane footprint, 30 feet of staple shelving and a hardship
    designation."""
    return _payload(
        {
            "owner_id": owner_id,
            "store_name": store_name,
            "state_code": state_code,
            "store_type": store_type,
            "checkout_lane_count": checkout_lane_count,
            "staple_shelf_linear_feet": staple_shelf_linear_feet,
            "annual_gross_sales_cents": annual_gross_sales_cents,
            "annual_staple_sales_cents": annual_staple_sales_cents,
            "max_terminal_slots": max_terminal_slots,
            "tax_rate_bps": tax_rate_bps,
            "hardship_designated": hardship_designated,
            "predecessor_store_id": predecessor_store_id,
        },
        overrides,
    )


def store_patch_payload(expected_store_version: int, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_store_version": expected_store_version}
    payload.update(fields)
    return payload


# --------------------------------------------------------------------------
# Staple inventory lines
# --------------------------------------------------------------------------

CATEGORIES = ("BREAD_CEREAL", "DAIRY", "FRUIT_VEG", "MEAT_POULTRY_FISH")
PERISHABLE_CATEGORIES = ("DAIRY", "FRUIT_VEG", "MEAT_POULTRY_FISH")


def inventory_line(
    category: str,
    variety_key: str,
    unit_count: int,
    is_perishable: bool,
) -> Dict[str, Any]:
    return {
        "category": category,
        "variety_key": variety_key,
        "unit_count": unit_count,
        "is_perishable": is_perishable,
    }


def category_lines(
    category: str,
    variety_count: int,
    unit_count: int,
    is_perishable: bool = False,
    prefix: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """`variety_count` distinct varieties of one category, each holding
    `unit_count` stocking units."""
    stem = prefix or category.lower()
    return [
        inventory_line(category, f"{stem}-{i + 1}", unit_count, is_perishable)
        for i in range(variety_count)
    ]


def passing_inventory_lines() -> List[Dict[str, Any]]:
    """Four categories, three varieties each, four units per variety: twelve
    distinct varieties, every one of them deep enough for the on-site variant,
    with perishables in three categories."""
    lines: List[Dict[str, Any]] = []
    for category in CATEGORIES:
        lines.extend(
            category_lines(
                category,
                variety_count=3,
                unit_count=4,
                is_perishable=category in PERISHABLE_CATEGORIES,
            )
        )
    return lines


def desk_failing_inventory_lines() -> List[Dict[str, Any]]:
    """Only three of the four categories reach three varieties -- meat and fish
    holds two -- so the desk assessment cannot reach four qualifying
    categories."""
    lines: List[Dict[str, Any]] = []
    for category in CATEGORIES[:3]:
        lines.extend(
            category_lines(
                category,
                variety_count=3,
                unit_count=4,
                is_perishable=category in PERISHABLE_CATEGORIES,
            )
        )
    lines.extend(
        category_lines(
            "MEAT_POULTRY_FISH", variety_count=2, unit_count=4, is_perishable=True
        )
    )
    return lines


def broad_but_shallow_inventory_lines() -> List[Dict[str, Any]]:
    """Five varieties of two units in every category: the desk variant counts
    breadth first and depth only in aggregate, so ten units across five
    varieties qualifies each category, while the on-site variant counts only
    varieties holding at least three units and finds none."""
    lines: List[Dict[str, Any]] = []
    for category in CATEGORIES:
        lines.extend(
            category_lines(
                category,
                variety_count=5,
                unit_count=2,
                is_perishable=category in PERISHABLE_CATEGORIES,
            )
        )
    return lines


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------

def application_payload(
    store_id: str,
    expected_store_version: int,
    application_type: str = "INITIAL",
    claimed_criterion: str = "CRITERION_A",
    reported_inventory_lines: Optional[List[Dict[str, Any]]] = None,
    reported_staple_sales_pct: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "store_id": store_id,
            "expected_store_version": expected_store_version,
            "application_type": application_type,
            "claimed_criterion": claimed_criterion,
            "reported_inventory_lines": (
                passing_inventory_lines()
                if reported_inventory_lines is None
                else reported_inventory_lines
            ),
            "reported_staple_sales_pct": reported_staple_sales_pct,
        },
        overrides,
    )


def documents_payload(
    reported_inventory_lines: Optional[List[Dict[str, Any]]] = None,
    reported_staple_sales_pct: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "reported_inventory_lines": (
                passing_inventory_lines()
                if reported_inventory_lines is None
                else reported_inventory_lines
            ),
            "reported_staple_sales_pct": reported_staple_sales_pct,
        },
        overrides,
    )


def decision_payload(
    outcome: str = "APPROVED", reason_code: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    return _payload({"outcome": outcome, "reason_code": reason_code}, overrides)


# --------------------------------------------------------------------------
# Inspectors and visits
# --------------------------------------------------------------------------

def inspector_payload(
    full_name: str = "Dana Ruiz",
    state_code: str = "TX",
    max_daily_minutes: int = 480,
    status: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "full_name": full_name,
            "state_code": state_code,
            "max_daily_minutes": max_daily_minutes,
            "status": status,
        },
        overrides,
    )


def store_visit_payload(
    application_id: str,
    inspector_id: str,
    visit_type: str = "PRE_AUTHORIZATION",
    window_start: str = "2026-08-01T00:00:00Z",
    window_end: str = "2026-08-01T02:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "application_id": application_id,
            "inspector_id": inspector_id,
            "visit_type": visit_type,
            "window_start": window_start,
            "window_end": window_end,
        },
        overrides,
    )


def findings_payload(
    observed_staple_shelf_linear_feet: int = 30,
    observed_inventory_lines: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "observed_inventory_lines": (
                passing_inventory_lines()
                if observed_inventory_lines is None
                else observed_inventory_lines
            ),
            "observed_staple_shelf_linear_feet": observed_staple_shelf_linear_feet,
        },
        overrides,
    )


def note_payload(note: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    return _payload({"note": note}, overrides)


# --------------------------------------------------------------------------
# Point-of-sale transactions
# --------------------------------------------------------------------------

def line_item(
    sku: str, item_class: str, unit_price_cents: int, qty: int
) -> Dict[str, Any]:
    return {
        "sku": sku,
        "item_class": item_class,
        "unit_price_cents": unit_price_cents,
        "qty": qty,
    }


def pos_transaction_payload(
    store_id: str,
    terminal_deployment_id: str,
    line_items: Optional[List[Dict[str, Any]]] = None,
    snap_benefit_available_cents: int = 1000,
    other_tender_offered_cents: int = 0,
    household_ebt_card_last4: str = "6120",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "store_id": store_id,
            "terminal_deployment_id": terminal_deployment_id,
            "household_ebt_card_last4": household_ebt_card_last4,
            "line_items": (
                [line_item("RICE-5LB", "STAPLE_FOOD", 1000, 1)]
                if line_items is None
                else line_items
            ),
            "snap_benefit_available_cents": snap_benefit_available_cents,
            "other_tender_offered_cents": other_tender_offered_cents,
        },
        overrides,
    )


def void_payload(void_reason_code: str = "CLERK_ERROR", **overrides: Any) -> Dict[str, Any]:
    return _payload({"void_reason_code": void_reason_code}, overrides)


# --------------------------------------------------------------------------
# Monitoring periods
# --------------------------------------------------------------------------

def redemption_period_payload(
    store_id: str,
    period_index: int = 8,
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-08-02T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "store_id": store_id,
            "period_index": period_index,
            "period_start": period_start,
            "period_end": period_end,
        },
        overrides,
    )


def settlement_payload(
    imported_total_cents: int = 1000000,
    imported_transaction_count: int = 100,
    imported_large_transaction_cents: int = 0,
    imported_even_dollar_transaction_count: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "imported_total_cents": imported_total_cents,
            "imported_transaction_count": imported_transaction_count,
            "imported_large_transaction_cents": imported_large_transaction_cents,
            "imported_even_dollar_transaction_count": (
                imported_even_dollar_transaction_count
            ),
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Investigations
# --------------------------------------------------------------------------

def investigation_payload(
    store_id: str,
    opened_reason: str = "TIP",
    trigger_period_id: Optional[str] = None,
    evidence_items: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "store_id": store_id,
            "opened_reason": opened_reason,
            "trigger_period_id": trigger_period_id,
            "evidence_items": evidence_items,
        },
        overrides,
    )


def evidence_payload(
    evidence_type: str = "HOUSEHOLD_INTERVIEW",
    observed_at: str = "2026-07-30T00:00:00Z",
    note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {"evidence_type": evidence_type, "observed_at": observed_at, "note": note},
        overrides,
    )


def conclude_payload(
    substantiated_violation: str = "NONE", **overrides: Any
) -> Dict[str, Any]:
    return _payload({"substantiated_violation": substantiated_violation}, overrides)


# --------------------------------------------------------------------------
# Sanction cases
# --------------------------------------------------------------------------

def sanction_case_payload(
    investigation_id: str,
    violation_type: str = "INELIGIBLE_ITEMS_HARDSHIP",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {"investigation_id": investigation_id, "violation_type": violation_type},
        overrides,
    )


def charge_letter_payload(
    charge_summary: str = "Ineligible item sales observed during the review period.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload({"charge_summary": charge_summary}, overrides)


def reply_payload(
    reply_text: str = "We dispute the findings and have retrained our staff.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload({"reply_text": reply_text}, overrides)


def cmp_election_payload(
    expected_sanction_case_version: int,
    hardship_ownership_change_pending: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "expected_sanction_case_version": expected_sanction_case_version,
            "hardship_ownership_change_pending": hardship_ownership_change_pending,
        },
        overrides,
    )


def determination_payload(
    sanction_type: str = "CMP_IN_LIEU", **overrides: Any
) -> Dict[str, Any]:
    return _payload({"sanction_type": sanction_type}, overrides)


def administrative_review_payload(
    grounds_text: str = "The determination misreads the redemption history.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload({"grounds_text": grounds_text}, overrides)


def review_decision_payload(
    outcome: str = "SUSTAINED", reason_code: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    return _payload({"outcome": outcome, "reason_code": reason_code}, overrides)


def cmp_payment_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _payload({"amount_cents": amount_cents}, overrides)


# --------------------------------------------------------------------------
# Equipment
# --------------------------------------------------------------------------

def depot_payload(
    state_code: str = "TX", total_units_owned: int = 5, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {"state_code": state_code, "total_units_owned": total_units_owned}, overrides
    )


def terminal_payload(
    depot_id: str,
    serial_number: str = "EBT-0001",
    model: str = "EBT_ONLY_WIRELESS",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {"depot_id": depot_id, "serial_number": serial_number, "model": model},
        overrides,
    )


def deployment_payload(
    store_id: str,
    terminal_id: str,
    deploy_start: str = AUG_01,
    deploy_end: str = "2026-09-30T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "store_id": store_id,
            "terminal_id": terminal_id,
            "deploy_start": deploy_start,
            "deploy_end": deploy_end,
        },
        overrides,
    )


def close_deployment_payload(
    close_reason_code: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    return _payload({"close_reason_code": close_reason_code}, overrides)


def order_line(item_code: str, qty: int) -> Dict[str, Any]:
    return {"item_code": item_code, "qty": qty}


def equipment_order_payload(
    store_id: str, lines: Optional[List[Dict[str, Any]]] = None, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {
            "store_id": store_id,
            "lines": [order_line("SIGNAGE_PACK", 1)] if lines is None else lines,
        },
        overrides,
    )


def cancel_order_payload(
    cancel_reason_code: str = "RETAILER_REQUEST", **overrides: Any
) -> Dict[str, Any]:
    return _payload({"cancel_reason_code": cancel_reason_code}, overrides)
