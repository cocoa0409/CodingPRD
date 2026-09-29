"""Payload factories — one per write endpoint, input fields only.

A module-level counter keeps globally unique codes (`room_code`, `sku`,
`contract_code`, `route_code`) distinct within a single test, so a test that
creates several rooms or items never trips a uniqueness rule by accident.
"""

import itertools

_SEQ = itertools.count(1)


def next_suffix() -> str:
    """Monotonic suffix for globally unique codes."""
    return f"{next(_SEQ):04d}"


# ─── SupplyRoom ───────────────────────────────────────────────────────────

def create_supply_room_payload(**overrides) -> dict:
    defaults = {
        "facility_code": "FAC-TEST",
        "room_code": f"ROOM-{next_suffix()}",
        "gpo_member_class": "ACUTE",
        "room_type": "GENERAL_STORE",
    }
    defaults.update(overrides)
    return defaults


# ─── Item ─────────────────────────────────────────────────────────────────

def create_item_payload(**overrides) -> dict:
    defaults = {
        "sku": f"SKU-{next_suffix()}",
        "description": "Test item-master record",
        "manufacturer_code": "MFR-ACME",
        "uom": "CS",
        "wac_cents": 8000,
        "handling_class": "AMBIENT",
        "units_per_parent": 10,
    }
    defaults.update(overrides)
    return defaults


# ─── GpoContract ──────────────────────────────────────────────────────────

def create_contract_payload(**overrides) -> dict:
    defaults = {
        "manufacturer_code": "MFR-ACME",
        "contract_code": f"CTR-{next_suffix()}",
        "tier": "TIER_1",
        "member_class_scope": "ACUTE",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2026-12-31T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults


def contract_transition_payload(to_status: str) -> dict:
    return {"to_status": to_status}


# ─── ContractLine ─────────────────────────────────────────────────────────

def create_contract_line_payload(item_id: str, **overrides) -> dict:
    defaults = {
        "item_id": item_id,
        "tier_price_cents": 3000,
        "floor_price_cents": 2000,
    }
    defaults.update(overrides)
    return defaults


# ─── FormularyItem ────────────────────────────────────────────────────────

def create_formulary_item_payload(item_id: str, **overrides) -> dict:
    defaults = {
        "item_id": item_id,
        "facility_item_code": f"FAC-ITEM-{next_suffix()}",
        "par_qty": 50,
        "reorder_point": 10,
    }
    defaults.update(overrides)
    return defaults


def formulary_decision_payload(decision: str) -> dict:
    return {"decision": decision}


def adjust_on_hand_payload(delta_qty: int, expected_formulary_item_version: int) -> dict:
    return {
        "delta_qty": delta_qty,
        "expected_formulary_item_version": expected_formulary_item_version,
    }


# ─── Lot ──────────────────────────────────────────────────────────────────

def create_lot_payload(item_id: str, **overrides) -> dict:
    defaults = {
        "item_id": item_id,
        "lot_code": f"LOT-{next_suffix()}",
        "expiry_date": "2027-06-30T00:00:00Z",
        "received_quantity": 100,
    }
    defaults.update(overrides)
    return defaults


def lot_excursion_payload(action: str, note: str = None) -> dict:
    payload = {"action": action}
    if note is not None:
        payload["note"] = note
    return payload


# ─── ReplenishmentOrder ───────────────────────────────────────────────────

def create_order_payload(supply_room_id: str, **overrides) -> dict:
    defaults = {"supply_room_id": supply_room_id}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(
    item_id: str, requested_qty: int, expected_order_version: int, **overrides
) -> dict:
    defaults = {
        "item_id": item_id,
        "requested_qty": requested_qty,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


# ─── SubstitutionRequest ──────────────────────────────────────────────────

def create_substitution_request_payload(proposed_item_id: str, **overrides) -> dict:
    defaults = {
        "proposed_item_id": proposed_item_id,
        "justification": "Primary item on national backorder",
    }
    defaults.update(overrides)
    return defaults


def clinician_action_payload(action: str, note: str = None) -> dict:
    payload = {"action": action}
    if note is not None:
        payload["note"] = note
    return payload


def substitution_respond_payload(action: str, response_note: str = None) -> dict:
    payload = {"action": action}
    if response_note is not None:
        payload["response_note"] = response_note
    return payload


# ─── RecallNotice ─────────────────────────────────────────────────────────

def create_recall_notice_payload(item_id: str, **overrides) -> dict:
    defaults = {
        "item_id": item_id,
        "recall_class": "CLASS_I",
        "reason": "Sterile barrier breach detected in lot",
    }
    defaults.update(overrides)
    return defaults


def recall_cascade_payload(action: str) -> dict:
    return {"action": action}


# ─── DeliveryRoute ────────────────────────────────────────────────────────

def create_delivery_route_payload(**overrides) -> dict:
    defaults = {
        "route_code": f"RT-{next_suffix()}",
        "service_date": "2026-08-01",
        "vehicle_class": "AMBIENT_VAN",
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(
    order_id: str, arrival_min: int, service_minutes: int
) -> dict:
    return {
        "order_id": order_id,
        "arrival_min": arrival_min,
        "service_minutes": service_minutes,
    }


# ─── ChargebackClaim ──────────────────────────────────────────────────────

def create_chargeback_claim_payload(order_id: str, contract_id: str) -> dict:
    return {"order_id": order_id, "contract_id": contract_id}


def claim_response_payload(outcome: str, dispute_reason: str = None) -> dict:
    payload = {"outcome": outcome}
    if dispute_reason is not None:
        payload["dispute_reason"] = dispute_reason
    return payload


def claim_settle_payload(action: str) -> dict:
    return {"action": action}


# ─── Logical clock ────────────────────────────────────────────────────────

def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
