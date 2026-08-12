"""Payload factories — one per entity, input fields only.

Defaults mirror the canonical event used across the PRD's worked examples.
"""
from . import constants


def create_event_payload(**overrides) -> dict:
    defaults = {
        "name": "Cedar Creek 2026",
        "site_name": "Cedar Creek Field",
        "event_starts_at": constants.EVENT_STARTS_AT,
        "event_ends_at": constants.EVENT_ENDS_AT,
        "adult_day_price_cents": 2599,
        "child_day_price_cents": 1200,
        "adult_weekend_price_cents": 6000,
        "child_weekend_price_cents": 2800,
        "early_bird_pct": 0.2,
        "early_bird_cutoff_at": constants.EARLY_BIRD_CUTOFF_AT,
        "service_fee_cents": 350,
        "refund_retain_pct": 0.15,
        "required_liability_cents": 1000000,
        "max_minor_per_adult": 4,
        "vendor_frontage_rate_cents": 900,
        "vendor_multi_day_discount_pct": 0.1,
        "vendor_min_fee_cents": 5000,
        "vendor_late_insurance_surcharge_cents": 2500,
        "vendor_insurance_deadline_at": constants.VENDOR_INSURANCE_DEADLINE_AT,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "agreement_type": "LANDOWNER_USE",
        "document_ref": "DOC-LAND-1",
        "effective_from": constants.AGREEMENT_EFFECTIVE_FROM,
        "effective_until": constants.AGREEMENT_EFFECTIVE_UNTIL,
    }
    defaults.update(overrides)
    return defaults


def sign_agreement_payload(**overrides) -> dict:
    defaults = {"signer_name": "Landowner Lee"}
    defaults.update(overrides)
    return defaults


def create_unit_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "name": "6th Ohio",
        "unit_type": "MILITARY",
        "portrayal_name": "6th Ohio Volunteer Infantry",
        "headcount_estimate": 12,
    }
    defaults.update(overrides)
    return defaults


def vet_unit_payload(**overrides) -> dict:
    defaults = {"decision": "APPROVE", "notes": "ok"}
    defaults.update(overrides)
    return defaults


def create_participant_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "full_name": "Ada Adams",
        "age_at_event": 34,
        "impression_class": "COMBATANT",
        "persona_description": "Federal private, 1864",
    }
    defaults.update(overrides)
    return defaults


def vet_participant_payload(**overrides) -> dict:
    defaults = {"decision": "APPROVE", "notes": "ok"}
    defaults.update(overrides)
    return defaults


def create_equipment_item_payload(participant_id, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "item_type": "FIREARM",
        "description": "1861 Springfield rifled musket",
    }
    defaults.update(overrides)
    return defaults


def schedule_inspection_payload(**overrides) -> dict:
    defaults = {
        "scheduled_for": "2026-07-10T09:00:00Z",
        "inspection_kind": "SAFETY",
    }
    defaults.update(overrides)
    return defaults


def record_inspection_payload(**overrides) -> dict:
    defaults = {"outcome": "PASS"}
    defaults.update(overrides)
    return defaults


def waive_inspection_payload(**overrides) -> dict:
    defaults = {"waiver_reason": "corrected on re-check"}
    defaults.update(overrides)
    return defaults


def create_site_area_payload(**overrides) -> dict:
    defaults = {
        "area_name": "Demo Field",
        "area_kind": "DEMO",
        "capacity_units": 4,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(**overrides) -> dict:
    defaults = {
        "starts_at": "2026-07-09T12:00:00Z",
        "ends_at": "2026-07-12T12:00:00Z",
        "units": 2,
    }
    defaults.update(overrides)
    return defaults


def create_program_slot_payload(site_area_id, **overrides) -> dict:
    defaults = {
        "title": "Artillery demonstration",
        "site_area_id": site_area_id,
        "starts_at": "2026-07-11T10:00:00Z",
        "ends_at": "2026-07-11T11:00:00Z",
        "open_flame": True,
        "required_combatants": 0,
    }
    defaults.update(overrides)
    return defaults


def ticket_line(line_type, quantity) -> dict:
    return {"line_type": line_type, "quantity": quantity}


def create_ticket_order_payload(**overrides) -> dict:
    defaults = {
        "buyer_name": "Pat Poe",
        "lines": [ticket_line("ADULT_DAY", 3), ticket_line("CHILD_DAY", 2)],
    }
    defaults.update(overrides)
    return defaults


def pay_ticket_order_payload(**overrides) -> dict:
    defaults = {"payment_method": "CARD", "payment_reference": "payref-1"}
    defaults.update(overrides)
    return defaults


def refund_ticket_order_payload(**overrides) -> dict:
    defaults = {"reason": "PATRON_CHOICE"}
    defaults.update(overrides)
    return defaults


def issue_parking_pass_payload(**overrides) -> dict:
    defaults = {"vehicle_plate": "OH-1234", "vehicle_class": "STANDARD"}
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "business_name": "Sutler Sam",
        "wares_description": "Period dry goods",
        "frontage_feet": 20,
        "requested_days": 3,
    }
    defaults.update(overrides)
    return defaults


def contract_vendor_payload(**overrides) -> dict:
    defaults = {"insurance_cert_ref": "CERT-77", "fee_payment_cents": 48600}
    defaults.update(overrides)
    return defaults


def create_contingency_alert_payload(**overrides) -> dict:
    defaults = {
        "alert_kind": "FIRE",
        "severity": "RED_FLAG",
        "message": "red flag warning issued",
    }
    defaults.update(overrides)
    return defaults
