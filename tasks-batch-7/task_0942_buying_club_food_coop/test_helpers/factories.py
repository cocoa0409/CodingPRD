"""Payload factories — input fields only, one per creatable resource."""

from .constants import (
    CYCLE_CUTOFF_AT,
    CYCLE_OPENS_AT,
    PRICE_EPOCH,
)

# --------------------------------------------------------------------------
# Catalog blueprints used by the composite fixtures.  Each entry carries the
# item's declared input fields plus the case price published for it at the
# price epoch.
# --------------------------------------------------------------------------
ITEM_BLUEPRINTS = {
    "oat": {
        "sku": "OAT-25",
        "name": "Rolled Oats 25lb",
        "temp_class": "DRY",
        "case_pack_units": 4,
        "unit_weight_grams": 1000,
        "unit_cube_cm3": 3000,
        "split_allowed": True,
        "remainder_policy": "SHORT_FILL",
    },
    "berry": {
        "sku": "BERRY-10",
        "name": "Frozen Berries 10lb",
        "temp_class": "FROZEN",
        "case_pack_units": 6,
        "unit_weight_grams": 500,
        "unit_cube_cm3": 1200,
        "split_allowed": True,
        "remainder_policy": "ROUND_UP",
    },
    "cheese": {
        "sku": "CHEESE-2",
        "name": "Raw Cheddar 2lb",
        "temp_class": "CHILLED",
        "case_pack_units": 3,
        "unit_weight_grams": 900,
        "unit_cube_cm3": 1500,
        "split_allowed": True,
        "remainder_policy": "DROP",
    },
    "cheddar_sub": {
        "sku": "CHEDDAR-SUB",
        "name": "Substitute Cheddar 2lb",
        "temp_class": "CHILLED",
        "case_pack_units": 3,
        "unit_weight_grams": 900,
        "unit_cube_cm3": 1500,
        "split_allowed": True,
        "remainder_policy": "SHORT_FILL",
    },
    "salt": {
        "sku": "SALT-1",
        "name": "Sea Salt 1kg",
        "temp_class": "DRY",
        "case_pack_units": 5,
        "unit_weight_grams": 1000,
        "unit_cube_cm3": 1000,
        "split_allowed": True,
        "remainder_policy": "SHORT_FILL",
    },
    "pepper": {
        "sku": "PEPPER-1",
        "name": "Black Pepper 1kg",
        "temp_class": "DRY",
        "case_pack_units": 5,
        "unit_weight_grams": 1000,
        "unit_cube_cm3": 1000,
        "split_allowed": True,
        "remainder_policy": "SHORT_FILL",
    },
    "rice": {
        "sku": "RICE-50",
        "name": "Brown Rice 50lb",
        "temp_class": "DRY",
        "case_pack_units": 2,
        "unit_weight_grams": 22700,
        "unit_cube_cm3": 30000,
        "split_allowed": False,
        "remainder_policy": "SHORT_FILL",
    },
    "late": {
        "sku": "LATE-1",
        "name": "Late Priced Goods",
        "temp_class": "DRY",
        "case_pack_units": 4,
        "unit_weight_grams": 1000,
        "unit_cube_cm3": 3000,
    },
}

# case_price_cents published at the price epoch for each blueprint
ITEM_CASE_PRICE_CENTS = {
    "oat": 12000,
    "berry": 9000,
    "cheese": 10000,
    "cheddar_sub": 11000,
    "salt": 5250,
    "pepper": 5250,
    "rice": 40000,
    "late": 8000,
}


def create_route_payload(**overrides) -> dict:
    payload = {
        "code": "R-NORTH",
        "name": "North Route",
        "reefer_slots": 2,
        "route_minimum_cents": 1000,
        "max_pallets": 12,
    }
    payload.update(overrides)
    return payload


def create_drop_point_payload(route_id: str, **overrides) -> dict:
    payload = {"route_id": route_id, "name": "Depot A", "drop_minimum_cents": 1000}
    payload.update(overrides)
    return payload


def create_item_payload(blueprint: str = "oat", **overrides) -> dict:
    payload = dict(ITEM_BLUEPRINTS[blueprint])
    payload.update(overrides)
    return payload


def create_price_version_payload(item_id: str, case_price_cents: int, **overrides) -> dict:
    payload = {
        "item_id": item_id,
        "effective_from": PRICE_EPOCH,
        "case_price_cents": case_price_cents,
    }
    payload.update(overrides)
    return payload


def create_member_payload(home_drop_point_id: str, **overrides) -> dict:
    payload = {
        "email": "member@coop.test",
        "full_name": "Test Member",
        "home_drop_point_id": home_drop_point_id,
    }
    payload.update(overrides)
    return payload


def dues_payment_payload(amount_cents: int, expected_member_version: int, term_years: int = 1) -> dict:
    return {
        "amount_cents": amount_cents,
        "term_years": term_years,
        "expected_member_version": expected_member_version,
    }


def tier_change_payload(new_tier: str, prorated_amount_cents: int, expected_member_version: int) -> dict:
    return {
        "new_tier": new_tier,
        "prorated_amount_cents": prorated_amount_cents,
        "expected_member_version": expected_member_version,
    }


def create_cycle_payload(**overrides) -> dict:
    payload = {
        "code": "CY-MAY",
        "opens_at": CYCLE_OPENS_AT,
        "cutoff_at": CYCLE_CUTOFF_AT,
    }
    payload.update(overrides)
    return payload


def create_drop_run_payload(cycle_id: str, drop_point_id: str) -> dict:
    return {"cycle_id": cycle_id, "drop_point_id": drop_point_id}


def create_member_order_payload(member_id: str, drop_run_id: str) -> dict:
    return {"member_id": member_id, "drop_run_id": drop_run_id}


def create_order_line_payload(
    member_order_id: str, item_id: str, qty_units: int, expected_member_order_version: int, **overrides
) -> dict:
    payload = {
        "member_order_id": member_order_id,
        "item_id": item_id,
        "qty_units": qty_units,
        "expected_member_order_version": expected_member_order_version,
    }
    payload.update(overrides)
    return payload


def patch_order_line_payload(expected_member_order_version: int, **overrides) -> dict:
    payload = {"expected_member_order_version": expected_member_order_version}
    payload.update(overrides)
    return payload


def create_receipt_line_payload(
    route_run_id: str,
    case_aggregate_id: str,
    cases_received: int,
    expected_route_run_version: int,
    **overrides,
) -> dict:
    payload = {
        "route_run_id": route_run_id,
        "case_aggregate_id": case_aggregate_id,
        "cases_received": cases_received,
        "expected_route_run_version": expected_route_run_version,
    }
    payload.update(overrides)
    return payload


def supplier_invoice_payload(supplier_invoice_cents: int, freight_cents: int) -> dict:
    return {
        "supplier_invoice_cents": supplier_invoice_cents,
        "freight_cents": freight_cents,
    }


def create_drop_reconciliation_payload(drop_run_id: str, expected_drop_run_version: int) -> dict:
    return {
        "drop_run_id": drop_run_id,
        "expected_drop_run_version": expected_drop_run_version,
    }


def create_volunteer_shift_payload(drop_run_id: str, member_id: str, hours: float) -> dict:
    return {"drop_run_id": drop_run_id, "member_id": member_id, "hours": hours}


def create_credit_grant_payload(
    member_id: str, amount_cents: int, expires_at: str, expected_member_version: int
) -> dict:
    return {
        "member_id": member_id,
        "amount_cents": amount_cents,
        "expires_at": expires_at,
        "expected_member_version": expected_member_version,
    }


def refund_payload(amount_cents: int, destination: str = "CARD") -> dict:
    return {"amount_cents": amount_cents, "destination": destination}


def payout_payload(payout_mode: str) -> dict:
    return {"payout_mode": payout_mode}
