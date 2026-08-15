"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Air"),
        "country_code": "US",
        "credit_limit_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    defaults = {
        "part_number": _uniq("PN"),
        "description": "Test part",
        "rotable": False,
        "list_price_cents": 10_000,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_unit_payload(part_id: str, **overrides) -> dict:
    defaults = {
        "part_id": part_id,
        "serial_number": _uniq("SN"),
        "condition": "NEW",
        "trace_doc_level": "FAA_8130",
        "warehouse_code": "WH-1",
    }
    defaults.update(overrides)
    return defaults


def create_aog_request_payload(customer_id: str, part_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "aircraft_tail": _uniq("N"),
        "airport_code": "LAX",
        "part_id": part_id,
        "quantity": 1,
        "condition_acceptable": ["NEW"],
        "min_trace_doc": "FAA_8130",
        "needed_by_utc": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def make_quote_line(part_id: str, **overrides) -> dict:
    defaults = {
        "part_id": part_id,
        "quantity": 1,
        "sale_type": "OUTRIGHT",
        "unit_price_cents": 10_000,
        "discount_pct": 0,
        "condition_required": "NEW",
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(aog_request_id: str, customer_id: str, lines: list,
                         **overrides) -> dict:
    defaults = {
        "aog_request_id": aog_request_id,
        "customer_id": customer_id,
        "lines": lines,
        "validity_hours": 24,
        "freight_mode": "STANDARD",
        "distance_km": 800,
        "chargeable_weight_kg": 4,
        "destination_country": "US",
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(order_id: str, **overrides) -> dict:
    defaults = {"order_id": order_id}
    defaults.update(overrides)
    return defaults


def create_charter_slot_payload(**overrides) -> dict:
    defaults = {
        "tail_number": _uniq("N"),
        "home_base": "CLT",
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(customer_id: str, unit_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "unit_id": unit_id,
        "loan_type": "LOAN",
        "daily_rate_cents": 10_000,
        "start_at": "2026-05-10T00:00:00Z",
        "due_at": "2026-06-09T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(customer_id: str, order_line_id: str,
                                  **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "order_line_id": order_line_id,
        "fault_category": "DOA",
        "description": "fault reported",
    }
    defaults.update(overrides)
    return defaults


def create_return_authorization_payload(customer_id: str, order_line_id: str,
                                        **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "order_line_id": order_line_id,
        "reason": "not needed",
    }
    defaults.update(overrides)
    return defaults


def credit_adjustment_payload(entry_type: str, amount_cents: int,
                              expected_customer_version: int, **overrides) -> dict:
    defaults = {
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "expected_customer_version": expected_customer_version,
    }
    defaults.update(overrides)
    return defaults
