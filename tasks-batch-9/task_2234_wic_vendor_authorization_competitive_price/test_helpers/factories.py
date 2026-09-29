"""
Request payload factories.

Each factory builds only the *input* fields the PRD declares for its endpoint;
server-managed and computed fields are never sent. Defaults reproduce the ordinary
happy-path shape and every field can be overridden by keyword. Passing ``None``
explicitly for an optional field omits it from the payload, which is how a test
exercises a documented default.
"""

from typing import Any, Dict, List, Optional

from .constants import DEFAULT_MIN_SUBMISSIONS_FOR_CEILING
from .types import (
    AdjustmentReasonCode,
    FormulaRestrictionLevel,
    MarMethod,
    ReviewDecision,
    StoreType,
    TrainingType,
    ViolationCode,
    VisitType,
)

_OMIT = object()


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the private omit sentinel."""
    return {k: v for k, v in payload.items() if v is not _OMIT}


# ---------------------------------------------------------------------------
# Peer groups
# ---------------------------------------------------------------------------


def peer_group_payload(
    code: str = "PG-SUPER-A",
    store_type: str = StoreType.SUPERMARKET.value,
    min_monthly_redemption_cents: int = 5_000_000,
    max_monthly_redemption_cents: Optional[int] = 20_000_000,
    mar_method: str = MarMethod.PEER_MEDIAN.value,
    competitive_allowance_pct: float = 0.05,
    min_submissions_for_ceiling: Any = DEFAULT_MIN_SUBMISSIONS_FOR_CEILING,
    min_stock_multiplier: float = 1.5,
    **overrides: Any,
) -> Dict[str, Any]:
    """A peer group create body. Pass ``min_submissions_for_ceiling=None`` to omit it."""
    payload: Dict[str, Any] = {
        "code": code,
        "store_type": store_type,
        "min_monthly_redemption_cents": min_monthly_redemption_cents,
        "max_monthly_redemption_cents": max_monthly_redemption_cents,
        "mar_method": mar_method,
        "competitive_allowance_pct": competitive_allowance_pct,
        "min_stock_multiplier": min_stock_multiplier,
    }
    if min_submissions_for_ceiling is not None:
        payload["min_submissions_for_ceiling"] = min_submissions_for_ceiling
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Food categories and authorized food items
# ---------------------------------------------------------------------------


def food_category_payload(
    code: str = "MILK",
    name: str = "Fluid Milk",
    is_formula: bool = False,
    formula_restriction_level: str = FormulaRestrictionLevel.NONE.value,
    min_stock_units: Any = 4,
    min_variety_count: int = 2,
    max_units_per_transaction: int = 6,
    stock_required: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """A food category create body."""
    payload: Dict[str, Any] = {
        "code": code,
        "name": name,
        "is_formula": is_formula,
        "formula_restriction_level": formula_restriction_level,
        "min_stock_units": min_stock_units,
        "min_variety_count": min_variety_count,
        "max_units_per_transaction": max_units_per_transaction,
        "stock_required": stock_required,
    }
    payload.update(overrides)
    return _prune(payload)


def authorized_food_item_payload(
    food_category_id: str,
    upc: str = "00011122233",
    brand: str = "Statewide Dairy",
    container_size_oz: float = 128,
    contract_brand: bool = False,
    required_for_authorization: Any = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """An authorized food list item create body."""
    payload: Dict[str, Any] = {
        "food_category_id": food_category_id,
        "upc": upc,
        "brand": brand,
        "container_size_oz": container_size_oz,
        "contract_brand": contract_brand,
    }
    if required_for_authorization is not None:
        payload["required_for_authorization"] = required_for_authorization
    payload.update(overrides)
    return _prune(payload)


def delist_payload(
    delist_reason: str = "brand withdrawn from the authorized food list",
    **overrides: Any,
) -> Dict[str, Any]:
    """The free-text reason a supervisor supplies when delisting a UPC."""
    payload: Dict[str, Any] = {"delist_reason": delist_reason}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------


def vendor_payload(
    store_name: str = "Alpha Market",
    store_type: str = StoreType.SUPERMARKET.value,
    reported_monthly_redemption_cents: int = 6_000_000,
    **overrides: Any,
) -> Dict[str, Any]:
    """A vendor application create body."""
    payload: Dict[str, Any] = {
        "store_name": store_name,
        "store_type": store_type,
        "reported_monthly_redemption_cents": reported_monthly_redemption_cents,
    }
    payload.update(overrides)
    return _prune(payload)


def training_payload(
    training_type: str = TrainingType.INITIAL.value,
    completed_at: str = "2026-07-15T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A record-training body."""
    payload: Dict[str, Any] = {
        "training_type": training_type,
        "completed_at": completed_at,
    }
    payload.update(overrides)
    return _prune(payload)


def denial_payload(
    denial_reason: str = "store failed the authorization review",
    **overrides: Any,
) -> Dict[str, Any]:
    """A deny body."""
    payload: Dict[str, Any] = {"denial_reason": denial_reason}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Price cycles and submissions
# ---------------------------------------------------------------------------


def price_cycle_payload(
    cycle_code: str = "2026Q3",
    submission_open_at: str = "2026-08-01T00:00:00Z",
    submission_due_at: str = "2026-09-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A price cycle create body over a half-open collection window."""
    payload: Dict[str, Any] = {
        "cycle_code": cycle_code,
        "submission_open_at": submission_open_at,
        "submission_due_at": submission_due_at,
    }
    payload.update(overrides)
    return _prune(payload)


def price_submission_payload(
    vendor_id: str,
    food_item_id: str,
    price_cycle_id: str,
    shelf_price_cents: int = 320,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    A shelf price submission create body.

    The key order matches the order the PRD declares the inputs in, which is the
    order body foreign keys are resolved in.
    """
    payload: Dict[str, Any] = {
        "vendor_id": vendor_id,
        "food_item_id": food_item_id,
        "price_cycle_id": price_cycle_id,
        "shelf_price_cents": shelf_price_cents,
    }
    payload.update(overrides)
    return _prune(payload)


def review_payload(
    decision: str = ReviewDecision.ACCEPT.value,
    review_reason: Any = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A review body; ``review_reason`` is required only for a rejection."""
    payload: Dict[str, Any] = {"decision": decision}
    if review_reason is not None:
        payload["review_reason"] = review_reason
    payload.update(overrides)
    return _prune(payload)


def revise_payload(shelf_price_cents: int, **overrides: Any) -> Dict[str, Any]:
    """A revise body carrying the replacement shelf price."""
    payload: Dict[str, Any] = {"shelf_price_cents": shelf_price_cents}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Monitoring visits
# ---------------------------------------------------------------------------


def monitoring_visit_payload(
    vendor_id: str,
    visit_type: str = VisitType.ROUTINE.value,
    scheduled_for: str = "2026-08-05T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A monitoring visit create body."""
    payload: Dict[str, Any] = {
        "vendor_id": vendor_id,
        "visit_type": visit_type,
        "scheduled_for": scheduled_for,
    }
    payload.update(overrides)
    return _prune(payload)


def observation_payload(
    food_category_id: str,
    observed_units: int,
    observed_variety_count: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """One minimum stock observation for a food category."""
    payload: Dict[str, Any] = {
        "food_category_id": food_category_id,
        "observed_units": observed_units,
        "observed_variety_count": observed_variety_count,
    }
    payload.update(overrides)
    return _prune(payload)


def buy_item(upc: str, quantity: int, charged_unit_price_cents: int) -> Dict[str, Any]:
    """One entry of the compliance-buy basket."""
    return {
        "upc": upc,
        "quantity": quantity,
        "charged_unit_price_cents": charged_unit_price_cents,
    }


def conduct_payload(
    buy_items: Optional[List[Dict[str, Any]]] = None, **overrides: Any
) -> Dict[str, Any]:
    """A conduct body; the basket is omitted entirely when there is none."""
    payload: Dict[str, Any] = {}
    if buy_items is not None:
        payload["buy_items"] = buy_items
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Redemption claims
# ---------------------------------------------------------------------------


def claim_line_payload(
    line_number: int,
    upc: str,
    quantity: int,
    charged_unit_price_cents: int,
    medical_doc_on_file: Any = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """One scanned line of a redemption claim."""
    payload: Dict[str, Any] = {
        "line_number": line_number,
        "upc": upc,
        "quantity": quantity,
        "charged_unit_price_cents": charged_unit_price_cents,
    }
    if medical_doc_on_file is not None:
        payload["medical_doc_on_file"] = medical_doc_on_file
    payload.update(overrides)
    return _prune(payload)


def redemption_claim_payload(
    vendor_id: str,
    claim_month: str = "2026-07",
    lines: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A redemption claim create body with a non-empty list of lines."""
    payload: Dict[str, Any] = {
        "vendor_id": vendor_id,
        "claim_month": claim_month,
        "lines": lines if lines is not None else [],
    }
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Reimbursement adjustments
# ---------------------------------------------------------------------------


def reimbursement_adjustment_payload(
    redemption_claim_id: str,
    expected_claim_version: int,
    reason_code: str = AdjustmentReasonCode.EDIT_ERROR.value,
    recoupment_rate: float = 0.10,
    **overrides: Any,
) -> Dict[str, Any]:
    """A reimbursement adjustment create body carrying its version guard."""
    payload: Dict[str, Any] = {
        "redemption_claim_id": redemption_claim_id,
        "reason_code": reason_code,
        "recoupment_rate": recoupment_rate,
        "expected_claim_version": expected_claim_version,
    }
    payload.update(overrides)
    return _prune(payload)


def reversal_payload(
    reversal_reason: str = "adjustment raised against the wrong claim month",
    **overrides: Any,
) -> Dict[str, Any]:
    """A reverse body."""
    payload: Dict[str, Any] = {"reversal_reason": reversal_reason}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------------------
# Sanction cases
# ---------------------------------------------------------------------------


def sanction_case_payload(
    vendor_id: str,
    expected_vendor_version: int,
    violation_code: str = ViolationCode.CLASS_C.value,
    source_visit_id: Any = None,
    narrative: str = "recorded during a routine compliance review",
    **overrides: Any,
) -> Dict[str, Any]:
    """A sanction case create body carrying its version guard."""
    payload: Dict[str, Any] = {
        "vendor_id": vendor_id,
        "violation_code": violation_code,
        "narrative": narrative,
        "expected_vendor_version": expected_vendor_version,
    }
    if source_visit_id is not None:
        payload["source_visit_id"] = source_visit_id
    payload.update(overrides)
    return _prune(payload)


def dismissal_payload(
    dismissal_reason: str = "the finding was withdrawn on review",
    **overrides: Any,
) -> Dict[str, Any]:
    """A dismiss body."""
    payload: Dict[str, Any] = {"dismissal_reason": dismissal_reason}
    payload.update(overrides)
    return _prune(payload)


def cmp_close_payload(cmp_payment_cents: int, **overrides: Any) -> Dict[str, Any]:
    """A close body carrying the civil money penalty payment."""
    payload: Dict[str, Any] = {"cmp_payment_cents": cmp_payment_cents}
    payload.update(overrides)
    return _prune(payload)
