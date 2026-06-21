"""Payload factories — one per entity, input fields only.

All monetary values are integer cents.
"""

DEFAULTS = {
    "CUSTOMER_NAME": "Test Customer",
    "SERVICE_STATE": "CA",
    "PACKAGE_FEE_CENTS": 6000,
    "PREMIUM_FEE_CENTS": 1500,
    "EQUIPMENT_LEASE_CENTS": 1000,
    "EQUIPMENT_REPLACEMENT_CENTS": 30000,
}


# ─── Catalog entities ─────────────────────────────────────────────────────
def create_channel_package_payload(**overrides) -> dict:
    defaults = {
        "tier_code": "PLUS",
        "name": "Plus",
        "monthly_fee_cents": DEFAULTS["PACKAGE_FEE_CENTS"],
        "channel_count": 120,
        "rank": 2,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_premium_channel_payload(**overrides) -> dict:
    defaults = {
        "code": "HBOX",
        "name": "HBox",
        "kind": "PREMIUM",
        "monthly_fee_cents": DEFAULTS["PREMIUM_FEE_CENTS"],
        "min_package_rank": 2,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": "DVR-4K",
        "kind": "DVR",
        "monthly_lease_cents": DEFAULTS["EQUIPMENT_LEASE_CENTS"],
        "replacement_cost_cents": DEFAULTS["EQUIPMENT_REPLACEMENT_CENTS"],
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_promotion_offer_payload(**overrides) -> dict:
    defaults = {
        "code": "SAVE20",
        "discount_kind": "PERCENT_OFF_PACKAGE",
        "percent_off": 0.2,
        "flat_off_cents": 0,
        "promo_months": 6,
        "requires_min_rank": 2,
        "rollback_protected": False,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_regional_sports_fee_rule_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "base_fee_cents": 800,
        "premier_surcharge_cents": 500,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "name": "Tech One",
        "home_state_code": "CA",
        "active": True,
    }
    defaults.update(overrides)
    return defaults


# ─── Account + children ───────────────────────────────────────────────────
def create_account_payload(**overrides) -> dict:
    defaults = {
        "customer_name": DEFAULTS["CUSTOMER_NAME"],
        "service_state_code": DEFAULTS["SERVICE_STATE"],
        "contract_term_months": 0,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(package_id: str, **overrides) -> dict:
    defaults = {"package_id": package_id}
    defaults.update(overrides)
    return defaults


def tier_change_payload(package_id: str, expected_account_version: int, **overrides) -> dict:
    defaults = {
        "package_id": package_id,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def attach_add_on_payload(premium_channel_id: str, **overrides) -> dict:
    defaults = {"premium_channel_id": premium_channel_id}
    defaults.update(overrides)
    return defaults


def assign_equipment_payload(equipment_model_id: str, quantity: int = 1, **overrides) -> dict:
    defaults = {"equipment_model_id": equipment_model_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def schedule_visit_payload(visit_type, window_start, window_end, technician_id, **overrides) -> dict:
    defaults = {
        "visit_type": visit_type,
        "window_start": window_start,
        "window_end": window_end,
        "technician_id": technician_id,
    }
    defaults.update(overrides)
    return defaults


def complete_visit_payload(outcome_note: str = "completed", **overrides) -> dict:
    defaults = {"outcome_note": outcome_note}
    defaults.update(overrides)
    return defaults


def apply_promotion_payload(promotion_offer_id: str, expected_account_version: int, **overrides) -> dict:
    defaults = {
        "promotion_offer_id": promotion_offer_id,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def issue_statement_payload(cycle_index: int, proration_mode: str, **overrides) -> dict:
    defaults = {
        "cycle_index": cycle_index,
        "proration_mode": proration_mode,
        "days_in_cycle": 30,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
