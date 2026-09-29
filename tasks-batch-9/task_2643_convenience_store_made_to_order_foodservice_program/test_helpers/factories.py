"""Request-payload factories.

Each factory returns a plain dict holding only client-supplied input fields —
never server-owned fields such as ``id``, ``created_at``, ``updated_at`` or
``version``. Every factory accepts ``**overrides`` so a test can vary exactly
the field under examination and leave the rest at a known-good baseline.
"""

from typing import Any, Dict, List, Optional

from . import constants as C


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of ``None`` removes the key entirely."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ─── Clock ────────────────────────────────────────────────────────────
def clock_payload(to_iso8601: str = C.DEFAULT_CLOCK, **overrides: Any) -> Dict[str, Any]:
    return _merge({"to_iso8601": to_iso8601}, overrides)


# ─── Store ────────────────────────────────────────────────────────────
def store_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "store_code": C.STORE_CODE,
            "name": C.STORE_NAME,
            "hot_case_slot_capacity": 4,
            "pickup_slot_capacity": 2,
            "is_fuel_site": True,
        },
        overrides,
    )


def daypart_transition_payload(to_daypart: str = "BREAKFAST", **overrides: Any) -> Dict[str, Any]:
    return _merge({"to_daypart": to_daypart}, overrides)


# ─── Holding unit ─────────────────────────────────────────────────────
def holding_unit_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "unit_code": "BC-1",
            "unit_type": "BAKERY_CASE",
            "min_temp_f": 135,
            "max_temp_f": 185,
            "slot_count": 3,
        },
        overrides,
    )


# ─── Menu items ───────────────────────────────────────────────────────
def menu_item_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "sku": "HOAGIE-ITAL",
            "name": "Italian Hoagie",
            "station": "SANDWICH",
            "fulfillment_mode": "MADE_TO_ORDER",
            "base_price_cents": 899,
            "unit_food_cost_cents": 300,
            "prep_seconds": 180,
            "valid_dayparts": ["BREAKFAST", "LUNCH", "DINNER", "OVERNIGHT"],
        },
        overrides,
    )


def _menu_item_variant(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """A named menu-item preset whose own fields stay overridable by a test."""
    fields = dict(defaults)
    fields.update(overrides)
    return menu_item_payload(**fields)


def hoagie_payload(**overrides: Any) -> Dict[str, Any]:
    """Made-to-order sandwich, one premium modifier included in the base price."""
    return _menu_item_variant(
        {
            "sku": "HOAGIE-ITAL",
            "name": "Italian Hoagie",
            "station": "SANDWICH",
            "base_price_cents": 899,
            "unit_food_cost_cents": 300,
            "prep_seconds": 180,
            "included_premium_count": 1,
            "is_catering_eligible": True,
        },
        overrides,
    )


def coffee_payload(**overrides: Any) -> Dict[str, Any]:
    return _menu_item_variant(
        {
            "sku": "COFFEE-LG",
            "name": "Large Coffee",
            "station": "BEVERAGE",
            "base_price_cents": 249,
            "unit_food_cost_cents": 40,
            "prep_seconds": 45,
        },
        overrides,
    )


def wrap_payload(**overrides: Any) -> Dict[str, Any]:
    return _menu_item_variant(
        {
            "sku": "WRAP-CHKN",
            "name": "Chicken Wrap",
            "station": "SANDWICH",
            "base_price_cents": 505,
            "unit_food_cost_cents": 180,
            "prep_seconds": 120,
        },
        overrides,
    )


def pretzel_payload(**overrides: Any) -> Dict[str, Any]:
    """Par-baked bakery item: stock is reserved from a holding batch."""
    return _menu_item_variant(
        {
            "sku": "PRETZEL-SOFT",
            "name": "Soft Pretzel",
            "station": "BAKERY",
            "fulfillment_mode": "PAR_BAKED_CASE",
            "base_price_cents": 199,
            "unit_food_cost_cents": 40,
            "prep_seconds": 0,
            "bake_minutes": 25,
            "hold_minutes": 240,
            "valid_dayparts": ["BREAKFAST", "LUNCH"],
            "is_catering_eligible": True,
        },
        overrides,
    )


def modifier_option_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "code": "EXTRA-PROV",
            "modifier_class": "CHEESE",
            "price_delta_cents": 0,
            "is_premium": False,
            "max_qty": 1,
        },
        overrides,
    )


# ─── Promotion rules ──────────────────────────────────────────────────
def promotion_rule_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "code": "LUNCH10",
            "kind": "DAYPART_BUNDLE",
            "discount_kind": "PCT_PER_LINE",
            "discount_bp": 1000,
            "max_discount_cents": 100000,
            "valid_dayparts": ["LUNCH"],
            "stacking_rank": 1,
        },
        overrides,
    )


def cents_off_promotion_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "code": "TRAY2000",
            "kind": "DAYPART_BUNDLE",
            "discount_kind": "CENTS_OFF",
            "discount_cents": 2000,
            "max_discount_cents": 2000,
            "valid_dayparts": ["LUNCH"],
            "stacking_rank": 5,
        },
        overrides,
    )


def fuel_combo_promotion_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "code": "FUELFOOD900",
            "kind": "FUEL_FOOD_COMBO",
            "discount_kind": "CENTS_OFF",
            "discount_cents": 900,
            "max_discount_cents": 900,
            "min_food_subtotal_cents": 3000,
            "requires_fuel_gallons": 8,
            "valid_dayparts": ["LUNCH"],
            "stacking_rank": 10,
        },
        overrides,
    )


# ─── Loyalty ──────────────────────────────────────────────────────────
def loyalty_account_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"member_code": "MBR-0001", "email": "member@example.com"}, overrides)


def points_adjustment_payload(delta_points: int, reason: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"delta_points": delta_points, "reason": reason}, overrides)


def fuel_transaction_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "gallons": 12.5,
            "price_per_gallon_cents": 329,
            "occurred_at": "2026-07-25T08:00:00Z",
        },
        overrides,
    )


# ─── Staffing plans ───────────────────────────────────────────────────
def staffing_plan_payload(expected_store_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "service_date": C.SERVICE_DATE,
            "daypart": "LUNCH",
            "forecast_txn_count": 300,
            "mto_share_bp": 5000,
            "expected_store_version": expected_store_version,
        },
        overrides,
    )


# ─── Production batches ───────────────────────────────────────────────
def production_batch_payload(
    store_id: str, menu_item_id: str, holding_unit_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "store_id": store_id,
            "menu_item_id": menu_item_id,
            "holding_unit_id": holding_unit_id,
            "slot_index": 1,
            "planned_qty": 40,
            "bake_start_at": "2026-08-01T08:00:00Z",
        },
        overrides,
    )


def bake_payload(additional_qty: Optional[int] = None, **overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {}
    if additional_qty is not None:
        base["additional_qty"] = additional_qty
    return _merge(base, overrides)


def discard_payload(
    qty: int, reason: str, expected_batch_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"qty": qty, "reason": reason, "expected_batch_version": expected_batch_version},
        overrides,
    )


# ─── Food safety ──────────────────────────────────────────────────────
def temperature_log_payload(reading_f: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"reading_f": reading_f}, overrides)


def corrective_action_payload(
    temperature_log_id: str, action_taken: str = "Reset thermostat and re-probed", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"temperature_log_id": temperature_log_id, "action_taken": action_taken}, overrides
    )


# ─── Orders ───────────────────────────────────────────────────────────
def order_payload(store_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"store_id": store_id, "channel": "TOUCHSCREEN"}, overrides)


def preorder_payload(
    store_id: str,
    pickup_window_start: str,
    pickup_window_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "store_id": store_id,
            "channel": "MOBILE_PREORDER",
            "pickup_window_start": pickup_window_start,
            "pickup_window_end": pickup_window_end,
        },
        overrides,
    )


def catering_order_payload(
    store_id: str,
    pickup_window_start: str,
    pickup_window_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "store_id": store_id,
            "channel": "CATERING",
            "pickup_window_start": pickup_window_start,
            "pickup_window_end": pickup_window_end,
        },
        overrides,
    )


def order_line_payload(
    menu_item_id: str,
    qty: int = 1,
    modifiers: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"menu_item_id": menu_item_id, "qty": qty}
    if modifiers is not None:
        base["modifiers"] = modifiers
    return _merge(base, overrides)


def modifier_selection(modifier_option_id: str, qty: int = 1) -> Dict[str, Any]:
    """One element of an order line's ``modifiers`` array."""
    return {"modifier_option_id": modifier_option_id, "qty": qty}


def authorize_payload(tender_type: str = "CARD", **overrides: Any) -> Dict[str, Any]:
    return _merge({"tender_type": tender_type}, overrides)


def refund_payload(reason: str = "Customer complaint", **overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


def void_payload(reason: str = "Customer walked away", **overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


# ─── Kitchen tickets ──────────────────────────────────────────────────
def reopen_payload(reason: str = "Wrong bread used", **overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)
