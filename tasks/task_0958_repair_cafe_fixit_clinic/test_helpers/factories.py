"""Payload factories — one per entity, input fields only (PRD §3 narratives)."""
import uuid

from .constants import (
    EVENT_START, EVENT_END, SHIFT_START, SHIFT_END, DEFAULT_INDUCTION,
)


def _uniq_email() -> str:
    return f"{uuid.uuid4().hex[:8]}@x.com"


def create_repair_event_payload(**overrides) -> dict:
    defaults = {
        "name": "Repair Cafe",
        "starts_at": EVENT_START,
        "ends_at": EVENT_END,
        "intake_item_cap": 5,
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(event_id: str, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "category": "ELECTRONICS",
        "label": "Electronics bench 1",
        "capacity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_fixer_profile_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Fixer A",
        "email": _uniq_email(),
        "safety_induction_completed_at": DEFAULT_INDUCTION,
    }
    defaults.update(overrides)
    return defaults


def create_fixer_skill_payload(fixer_id: str, **overrides) -> dict:
    defaults = {
        "fixer_id": fixer_id,
        "category": "ELECTRONICS",
        "level": 4,
    }
    defaults.update(overrides)
    return defaults


def create_fixer_shift_payload(fixer_id: str, station_id: str, event_id: str,
                               **overrides) -> dict:
    defaults = {
        "fixer_id": fixer_id,
        "station_id": station_id,
        "event_id": event_id,
        "start_time": SHIFT_START,
        "end_time": SHIFT_END,
    }
    defaults.update(overrides)
    return defaults


def create_visitor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Visitor One",
        "email": _uniq_email(),
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(visitor_id: str, **overrides) -> dict:
    defaults = {
        "visitor_id": visitor_id,
        "safety_clause_accepted": True,
    }
    defaults.update(overrides)
    return defaults


def create_repair_item_payload(event_id: str, visitor_id: str, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "visitor_id": visitor_id,
        "category": "ELECTRONICS",
        "description": "Broken device",
        "weight_kg_estimated": 3.0,
    }
    defaults.update(overrides)
    return defaults


def create_triage_record_payload(expected_item_version: int, **overrides) -> dict:
    defaults = {
        "severity": 3,
        "estimated_difficulty": 2,
        "diagnosis": "diagnosis",
        "expected_item_version": expected_item_version,
    }
    defaults.update(overrides)
    return defaults


def create_part_stock_payload(**overrides) -> dict:
    defaults = {
        "sku": f"SKU-{uuid.uuid4().hex[:8]}",
        "name": "Spare part",
        "category": "ELECTRONICS",
        "unit_cost_cents": 400,
        "quantity_on_hand": 10,
    }
    defaults.update(overrides)
    return defaults


def create_part_reservation_payload(part_stock_id: str, repair_item_id: str,
                                    **overrides) -> dict:
    defaults = {
        "part_stock_id": part_stock_id,
        "repair_item_id": repair_item_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_safety_incident_payload(event_id: str, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "severity": "LOW",
        "description": "incident description",
    }
    defaults.update(overrides)
    return defaults


def create_monetary_donation_payload(**overrides) -> dict:
    defaults = {
        "donation_type": "MONETARY",
        "amount_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_in_kind_donation_payload(lines, **overrides) -> dict:
    defaults = {
        "donation_type": "IN_KIND",
        "in_kind_lines": lines,
    }
    defaults.update(overrides)
    return defaults


def in_kind_line(description="item", category="ELECTRONICS",
                 declared_value_cents=1000, age_years=1) -> dict:
    return {
        "description": description,
        "category": category,
        "declared_value_cents": declared_value_cents,
        "age_years": age_years,
    }


def record_outcome_payload(outcome="FIXED", weight_kg_actual=None) -> dict:
    payload = {"outcome": outcome}
    if weight_kg_actual is not None:
        payload["weight_kg_actual"] = weight_kg_actual
    return payload
