"""Payload factories — one per entity, input fields only.

Each factory provides sensible required-field defaults and accepts **overrides.
Only `source: input` fields appear; server-managed and computed fields are never
sent. Optional input fields (notify_channel, rush_eligible, priority,
assigned_technician_id, condition_notes, adjusted_price_cents, quantity,
supersedes_estimate_id) are omitted by default and added only when supplied.
"""
import itertools

_email_counter = itertools.count(1)
_code_counter = itertools.count(1)


def unique_email(prefix: str = "cust") -> str:
    return f"{prefix}{next(_email_counter)}@example.com"


def unique_code(prefix: str = "SVC") -> str:
    return f"{prefix}_{next(_code_counter)}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": unique_email(),
        "phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


def create_service_type_payload(**overrides) -> dict:
    defaults = {
        "code": unique_code(),
        "name": "Sole Replacement",
        "item_category": "SHOE",
        "base_price_cents": 4000,
        "standard_turnaround_days": 3,
        "warranty_days": 90,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Test Technician",
        "skills": ["SHOE", "LEATHER", "WATCH"],
    }
    defaults.update(overrides)
    return defaults


def create_repair_ticket_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
    }
    defaults.update(overrides)
    return defaults


def create_ticket_item_payload(ticket_id: str, **overrides) -> dict:
    defaults = {
        "ticket_id": ticket_id,
        "item_category": "SHOE",
        "description": "test item",
        "condition_grade": "GOOD",
    }
    defaults.update(overrides)
    return defaults


def create_service_line_payload(ticket_id: str, ticket_item_id: str,
                                service_type_id: str, **overrides) -> dict:
    defaults = {
        "ticket_id": ticket_id,
        "ticket_item_id": ticket_item_id,
        "service_type_id": service_type_id,
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(ticket_id: str, authored_by_technician_id: str,
                            **overrides) -> dict:
    defaults = {
        "ticket_id": ticket_id,
        "authored_by_technician_id": authored_by_technician_id,
    }
    defaults.update(overrides)
    return defaults


def present_estimate_payload(expected_ticket_version: int, **overrides) -> dict:
    defaults = {
        "expected_ticket_version": expected_ticket_version,
    }
    defaults.update(overrides)
    return defaults


def create_parts_order_payload(ticket_id: str, service_line_id: str,
                               supplier_cost_cents: int, lead_time_days: int,
                               **overrides) -> dict:
    defaults = {
        "ticket_id": ticket_id,
        "service_line_id": service_line_id,
        "part_name": "test part",
        "supplier_cost_cents": supplier_cost_cents,
        "lead_time_days": lead_time_days,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(ticket_id: str, amount_cents: int,
                           expected_ticket_version: int, **overrides) -> dict:
    defaults = {
        "ticket_id": ticket_id,
        "amount_cents": amount_cents,
        "method": "CASH",
        "expected_ticket_version": expected_ticket_version,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(ticket_id: str, service_line_id: str,
                                  reported_by_customer_id: str, **overrides) -> dict:
    defaults = {
        "ticket_id": ticket_id,
        "service_line_id": service_line_id,
        "reported_by_customer_id": reported_by_customer_id,
        "defect_description": "alleged repair failure",
    }
    defaults.update(overrides)
    return defaults


def rule_warranty_claim_payload(ruled_by_technician_id: str, **overrides) -> dict:
    defaults = {
        "ruled_by_technician_id": ruled_by_technician_id,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
