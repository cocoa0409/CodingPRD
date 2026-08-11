"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "PLAN_TIER": "CUSTOM",
    "PLAN_MONTHLY_FEE_CENTS": 100,
    "PLAN_INCLUDED_RETURNS": 100,
    "PLAN_OVERAGE_FEE_CENTS": 10,
    "PLAN_OVERSIZE_SURCHARGE_CENTS": 0,
    "PLAN_PICKUP_FEE_CENTS": 0,
    "MERCHANT_LEGAL_NAME": "Test Merchant",
    "SHOPPER_EMAIL": "shopper@x.com",
    "SHOPPER_FULL_NAME": "Test Shopper",
    "SHOPPER_POSTAL_CODE": "10001",
    "LOCATION_NAME": "Test Location",
    "LOCATION_KIND": "COUNTER",
    "LOCATION_POSTAL_CODE": "20001",
    "SLOT_SIZE_CLASS": "XL",
    "ZONE_CODE": "Z-TEST",
    "ZONE_WINDOW_CAPACITY": 10,
    "ROUTE_DESTINATION": "FAC-1",
    "ROUTE_WEIGHT_CAPACITY_GRAMS": 100000,
    # A billing window that covers the default logical clock
    # 2026-05-01T00:00:00Z (PRD §2.5).
    "CYCLE_PERIOD_START": "2026-04-01T00:00:00Z",
    "CYCLE_PERIOD_END": "2026-07-01T00:00:00Z",
    # A future pickup window relative to the default logical clock.
    "PICKUP_WINDOW_START": "2026-05-01T00:30:00Z",
    "PICKUP_WINDOW_END": "2026-05-01T02:30:00Z",
}


def create_subscription_plan_payload(**overrides) -> dict:
    defaults = {
        "tier": DEFAULTS["PLAN_TIER"],
        "monthly_fee_cents": DEFAULTS["PLAN_MONTHLY_FEE_CENTS"],
        "included_returns": DEFAULTS["PLAN_INCLUDED_RETURNS"],
        "overage_fee_cents": DEFAULTS["PLAN_OVERAGE_FEE_CENTS"],
        "pickup_enabled": True,
        "boxless_enabled": True,
        "oversize_enabled": True,
        "free_returns": False,
        "oversize_surcharge_cents": DEFAULTS["PLAN_OVERSIZE_SURCHARGE_CENTS"],
        "pickup_fee_cents": DEFAULTS["PLAN_PICKUP_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_merchant_account_payload(plan_id, **overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["MERCHANT_LEGAL_NAME"],
        "plan_id": plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_billing_cycle_payload(**overrides) -> dict:
    defaults = {
        "period_start": DEFAULTS["CYCLE_PERIOD_START"],
        "period_end": DEFAULTS["CYCLE_PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_shopper_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["SHOPPER_EMAIL"],
        "full_name": DEFAULTS["SHOPPER_FULL_NAME"],
        "postal_code": DEFAULTS["SHOPPER_POSTAL_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_return_item_line(
    sku="SKU-1",
    quantity=1,
    unit_price_cents=100,
    declared_condition="NEW",
    longest_side_cm=10,
    weight_grams=50,
    **overrides,
) -> dict:
    line = {
        "sku": sku,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "declared_condition": declared_condition,
        "longest_side_cm": longest_side_cm,
        "weight_grams": weight_grams,
    }
    line.update(overrides)
    return line


def create_return_order_payload(shopper_id, merchant_id, method="COUNTER_DROP",
                                items=None, **overrides) -> dict:
    defaults = {
        "shopper_id": shopper_id,
        "merchant_id": merchant_id,
        "method": method,
        "items": items if items is not None else [create_return_item_line()],
    }
    defaults.update(overrides)
    return defaults


def create_dropoff_location_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LOCATION_NAME"],
        "kind": DEFAULTS["LOCATION_KIND"],
        "postal_code": DEFAULTS["LOCATION_POSTAL_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_locker_slot_payload(**overrides) -> dict:
    defaults = {"size_class": DEFAULTS["SLOT_SIZE_CLASS"]}
    defaults.update(overrides)
    return defaults


def create_slot_reservation_payload(return_order_id, slot_id, **overrides) -> dict:
    defaults = {"return_order_id": return_order_id, "slot_id": slot_id}
    defaults.update(overrides)
    return defaults


def issue_label_payload(label_type, expected_return_order_version, **overrides) -> dict:
    defaults = {
        "label_type": label_type,
        "expected_return_order_version": expected_return_order_version,
    }
    defaults.update(overrides)
    return defaults


def change_method_payload(method, expected_return_order_version, **overrides) -> dict:
    defaults = {
        "method": method,
        "expected_return_order_version": expected_return_order_version,
    }
    defaults.update(overrides)
    return defaults


def confirm_dropoff_payload(location_id, **overrides) -> dict:
    defaults = {"location_id": location_id}
    defaults.update(overrides)
    return defaults


def inspect_item_payload(condition, **overrides) -> dict:
    defaults = {"condition": condition}
    defaults.update(overrides)
    return defaults


def create_courier_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": DEFAULTS["ZONE_CODE"],
        "window_capacity": DEFAULTS["ZONE_WINDOW_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_pickup_appointment_payload(return_order_id, zone_id, **overrides) -> dict:
    defaults = {
        "return_order_id": return_order_id,
        "zone_id": zone_id,
        "window_start": DEFAULTS["PICKUP_WINDOW_START"],
        "window_end": DEFAULTS["PICKUP_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def reschedule_pickup_payload(**overrides) -> dict:
    defaults = {
        "window_start": DEFAULTS["PICKUP_WINDOW_START"],
        "window_end": DEFAULTS["PICKUP_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_carrier_route_payload(origin_location_id, **overrides) -> dict:
    defaults = {
        "origin_location_id": origin_location_id,
        "destination_facility": DEFAULTS["ROUTE_DESTINATION"],
        "weight_capacity_grams": DEFAULTS["ROUTE_WEIGHT_CAPACITY_GRAMS"],
    }
    defaults.update(overrides)
    return defaults


def create_consolidation_tote_payload(route_id, location_id, **overrides) -> dict:
    defaults = {"route_id": route_id, "location_id": location_id}
    defaults.update(overrides)
    return defaults


def tote_membership_payload(return_order_id, expected_tote_version, **overrides) -> dict:
    defaults = {
        "return_order_id": return_order_id,
        "expected_tote_version": expected_tote_version,
    }
    defaults.update(overrides)
    return defaults


def append_ledger_entry_payload(kind, amount_cents, note, **overrides) -> dict:
    defaults = {"kind": kind, "amount_cents": amount_cents, "note": note}
    defaults.update(overrides)
    return defaults


def create_exception_case_payload(return_order_id, kind, note, **overrides) -> dict:
    defaults = {"return_order_id": return_order_id, "kind": kind, "note": note}
    defaults.update(overrides)
    return defaults


def resolve_exception_payload(resolution, expected_exception_case_version,
                              **overrides) -> dict:
    defaults = {
        "resolution": resolution,
        "expected_exception_case_version": expected_exception_case_version,
    }
    defaults.update(overrides)
    return defaults


def appeal_payload(appeal_note="please recheck", **overrides) -> dict:
    defaults = {"appeal_note": appeal_note}
    defaults.update(overrides)
    return defaults


def provide_shopper_info_payload(response_note="details", **overrides) -> dict:
    defaults = {"response_note": response_note}
    defaults.update(overrides)
    return defaults


def flag_discrepancy_payload(note="unit count mismatch", **overrides) -> dict:
    defaults = {"note": note}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
