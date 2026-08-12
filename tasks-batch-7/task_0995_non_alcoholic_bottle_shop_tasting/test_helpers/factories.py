"""Payload factories — one per entity, input fields only (PRD §4)."""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


# --- Catalogue ---

def create_category_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "code": f"cat-{i:04d}",
        "display_name": f"Category {i}",
        "compliance_class": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_sku_payload(category_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "category_id": category_id,
        "sku_code": f"sku-{i:04d}",
        "title": f"SKU {i}",
        "base_price_cents": 1000,
        "abv_basis_points": 0,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "lot_code": f"LOT-{i:04d}",
        "qty_received": 50,
        "unit_cost_cents": 100,
        "expires_on": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


# --- Members ---

def create_member_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "email": f"member{i:04d}@example.com",
        "full_name": f"Member {i}",
        "date_of_birth": "1990-01-01",
        "home_state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_attestation_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "attested_by_user_id": f"staff-attester-{i:04d}",
        "outcome": "APPROVED",
        "attested_on": "2026-05-01",
        "document_reference": f"doc-{i:04d}",
    }
    defaults.update(overrides)
    return defaults


def wallet_adjustment_payload(**overrides) -> dict:
    defaults = {"delta_cents": 0, "reason": "adjustment"}
    defaults.update(overrides)
    return defaults


# --- Club ---

def create_club_plan_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "code": f"PLAN-{i:04d}",
        "cadence": "MONTHLY",
        "bottles_per_shipment": 2,
        "price_cents_per_cycle": 3000,
        "allowed_category_ids": [],
        "discount_bps_on_retail": 1000,
        "max_active_subscriptions": 10,
    }
    defaults.update(overrides)
    return defaults


def create_club_subscription_payload(plan_id, member_id, expected_plan_version,
                                     **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "member_id": member_id,
        "started_on": "2026-04-01",
        "expected_plan_version": expected_plan_version,
        "trial_days": 0,
    }
    defaults.update(overrides)
    return defaults


# --- Tasting ---

def create_tasting_event_payload(host_member_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "title": f"Tasting {i}",
        "host_member_id": host_member_id,
        "starts_at": "2026-05-10T10:00:00Z",
        "ends_at": "2026-05-10T12:00:00Z",
        "capacity": 5,
        "flight_price_cents": 1000,
        "min_attendee_age_years": 0,
    }
    defaults.update(overrides)
    return defaults


def create_flight_item_payload(sku_id, **overrides) -> dict:
    defaults = {
        "sku_id": sku_id,
        "pour_size_ml": 30,
        "sequence_no": 1,
    }
    defaults.update(overrides)
    return defaults


def book_seat_payload(member_id, expected_event_version, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "expected_event_version": expected_event_version,
    }
    defaults.update(overrides)
    return defaults


# --- Special orders ---

def create_special_order_payload(member_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "member_id": member_id,
        "requested_sku_code": f"wanted-{i:04d}",
        "quantity": 1,
        "deposit_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def approve_special_order_payload(resolved_sku_id, approved_by_user_id,
                                  **overrides) -> dict:
    defaults = {
        "resolved_sku_id": resolved_sku_id,
        "approved_by_user_id": approved_by_user_id,
    }
    defaults.update(overrides)
    return defaults


def receive_special_order_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "lot_code": f"SO-LOT-{i:04d}",
        "qty_received": 10,
        "unit_cost_cents": 100,
        "expires_on": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


# --- Orders ---

def create_order_payload(member_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "channel": "RETAIL",
    }
    defaults.update(overrides)
    return defaults


def add_order_line_payload(sku_id, **overrides) -> dict:
    defaults = {"sku_id": sku_id, "qty": 1}
    defaults.update(overrides)
    return defaults


def submit_order_payload(expected_order_version, **overrides) -> dict:
    defaults = {"expected_order_version": expected_order_version}
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "carrier": "UPS",
        "tracking_no": f"TRK-{i:04d}",
        "shipped_on": "2026-05-02",
    }
    defaults.update(overrides)
    return defaults


# --- Shipping rules ---

def create_shipping_state_rule_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "allows_dtc": True,
        "min_age_years": 0,
        "abv_cap_basis_points": 500,
        "surcharge_cents_per_order": 0,
        "tax_rate_bps": 0,
    }
    defaults.update(overrides)
    return defaults
