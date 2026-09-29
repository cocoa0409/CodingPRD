"""Request-payload builders.

Every builder carries only *input* fields — never a computed, system or
derived field — and every one accepts ``**overrides`` so a test can pin the one
value it cares about while the rest stay valid. Optional fields that the server
defaults are omitted unless a caller passes them, so the default behaviour is
exercised rather than masked.

Visit payloads get one builder per legal site/channel pairing because the
pairing rules are strict: the identifier that does not belong must be absent,
not merely null.
"""

from typing import Any, Dict, List, Optional

# ─── Distributors ────────────────────────────────────────────────────────────


def create_distributor_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": "Cascade Bottling LLC",
        "state_code": "OR",
        "permit_number": "PERMIT-1001",
    }
    payload.update(overrides)
    return payload


def deposit_initiation_payload(
    product_id: str, container_count: int, period_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "container_count": container_count,
        "period_id": period_id,
    }
    payload.update(overrides)
    return payload


# ─── Beverage products (labels) ──────────────────────────────────────────────


def create_beverage_product_payload(
    distributor_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "distributor_id": distributor_id,
        "brand_name": "Cascade Spring Water",
        "beverage_type": "WATER",
        "container_material": "PET_PLASTIC",
        "fill_volume_ml": 500,
        "upc": "011110000001",
        "label_state_code": "OR",
    }
    payload.update(overrides)
    return payload


def registration_action_payload(
    action: str, reason: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ─── Redemption centres and machines ────────────────────────────────────────


def create_redemption_center_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_name": "Cascade Redemption Center",
        "x_miles": 0.0,
        "y_miles": 0.0,
        "accepted_materials": ["ALUMINUM", "GLASS", "PET_PLASTIC", "HDPE_PLASTIC"],
    }
    payload.update(overrides)
    return payload


def center_status_change_payload(
    action: str, reason: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


def create_machine_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "asset_tag": "RVM-1001",
        "accepted_material": "PET_PLASTIC",
    }
    payload.update(overrides)
    return payload


def machine_event_payload(
    event_type: str,
    visit_id: Optional[str] = None,
    note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event_type": event_type}
    if visit_id is not None:
        payload["visit_id"] = visit_id
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


# ─── Redeemer accounts ──────────────────────────────────────────────────────


def create_redeemer_account_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "holder_name": "Dana Reyes",
        "account_code": "ACCT-1001",
    }
    payload.update(overrides)
    return payload


def credit_action_payload(
    action: str,
    amount_cents: int,
    expected_account_version: int,
    memo: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": action,
        "amount_cents": amount_cents,
        "expected_account_version": expected_account_version,
    }
    if memo is not None:
        payload["memo"] = memo
    payload.update(overrides)
    return payload


def account_status_change_payload(
    action: str, reason: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ─── Redemption visits ──────────────────────────────────────────────────────


def center_machine_visit_payload(
    center_id: str,
    machine_id: str,
    account_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A machine-counted visit at a redemption centre."""
    payload: Dict[str, Any] = {
        "site_type": "CENTER",
        "channel": "MACHINE_COUNT",
        "center_id": center_id,
        "machine_id": machine_id,
    }
    if account_id is not None:
        payload["account_id"] = account_id
    payload.update(overrides)
    return payload


def center_hand_visit_payload(
    center_id: str, account_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """A hand-counted visit at a redemption centre."""
    payload: Dict[str, Any] = {
        "site_type": "CENTER",
        "channel": "HAND_COUNT",
        "center_id": center_id,
    }
    if account_id is not None:
        payload["account_id"] = account_id
    payload.update(overrides)
    return payload


def retailer_visit_payload(
    retailer_id: str, account_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """A visit at an obligated retail store; always hand-counted."""
    payload: Dict[str, Any] = {
        "site_type": "RETAILER",
        "channel": "HAND_COUNT",
        "retailer_id": retailer_id,
    }
    if account_id is not None:
        payload["account_id"] = account_id
    payload.update(overrides)
    return payload


def create_lot_payload(
    product_id: str,
    presented_quantity: int,
    expected_visit_version: int,
    out_of_state_marked_quantity: Optional[int] = None,
    contaminated_quantity: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "presented_quantity": presented_quantity,
        "expected_visit_version": expected_visit_version,
    }
    if out_of_state_marked_quantity is not None:
        payload["out_of_state_marked_quantity"] = out_of_state_marked_quantity
    if contaminated_quantity is not None:
        payload["contaminated_quantity"] = contaminated_quantity
    payload.update(overrides)
    return payload


def payout_action_payload(
    action: str, reason: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ─── Bag drops ──────────────────────────────────────────────────────────────


def create_bag_drop_payload(
    account_id: str, center_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "center_id": center_id,
        "tag_code": "TAG-1001",
        "declared_count": 100,
    }
    payload.update(overrides)
    return payload


def bag_drop_count_payload(
    counted_quantities: List[int], expected_bag_drop_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "counted_quantities": counted_quantities,
        "expected_bag_drop_version": expected_bag_drop_version,
    }
    payload.update(overrides)
    return payload


def bag_drop_settlement_payload(
    action: str, reason: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ─── Commodity batches ──────────────────────────────────────────────────────


def create_commodity_batch_payload(
    center_id: str, container_count: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "center_id": center_id,
        "material": "PET_PLASTIC",
        "batch_code": "BATCH-1001",
        "container_count": container_count,
    }
    payload.update(overrides)
    return payload


def sort_action_payload(contamination_pct: float, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": "SORT",
        "contamination_pct": contamination_pct,
    }
    payload.update(overrides)
    return payload


def bale_action_payload(
    bale_weights_kg: List[float], **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": "BALE",
        "bale_weights_kg": bale_weights_kg,
    }
    payload.update(overrides)
    return payload


def batch_sale_payload(
    pricing_mode: str,
    quoted_price_cents_per_tonne: int,
    period_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "pricing_mode": pricing_mode,
        "quoted_price_cents_per_tonne": quoted_price_cents_per_tonne,
        "period_id": period_id,
    }
    payload.update(overrides)
    return payload


# ─── Retailers ──────────────────────────────────────────────────────────────


def create_retailer_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "store_name": "Corner Market",
        "x_miles": 1.0,
        "y_miles": 0.0,
        "store_area_sqft": 3000,
    }
    payload.update(overrides)
    return payload


def exemption_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# ─── Program periods ────────────────────────────────────────────────────────


def create_program_period_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "quarter_code": "2026Q3",
        "start_date": "2026-07-01",
        "end_date": "2026-09-30",
    }
    payload.update(overrides)
    return payload


def period_action_payload(
    action: str, reason: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload
