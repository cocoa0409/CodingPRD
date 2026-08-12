"""Payload factories — one per entity, input fields only (PRD §3.1-§3.7)."""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


# --- Reference data ---

def create_policyholder_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"Test Holder {n}",
        "email": f"holder{n}@example.com",
        "phone": f"555-{1000 + (n % 9000)}",
        "state_code": "FL",
    }
    defaults.update(overrides)
    return defaults


def create_state_regulation_payload(**overrides) -> dict:
    defaults = {
        "state_code": "FL",
        "zero_deductible_windshield": False,
        "glass_sales_tax_rate_bp": 0,
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(policyholder_id: str, **overrides) -> dict:
    n = _n()
    defaults = {
        "policyholder_id": policyholder_id,
        "policy_number": f"PN-{n:05d}",
        "state_code": "FL",
        "coverage_type": "COMPREHENSIVE",
        "deductible_cents": 50000,
        "effective_start_date": "2026-01-01",
        "effective_end_date": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_glass_shop_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "shop_name": f"Glass Shop {n}",
        "state_code": "FL",
        "service_zip_prefixes": ["336"],
        "mobile_capable": False,
        "adas_certified": False,
        "oem_certified": False,
        "agreement_tier": "STANDARD",
        "bay_count": 1,
        "mobile_unit_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_part_catalog_entry_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "part_number": f"PN-PART-{n:05d}",
        "part_description": f"Catalog part {n}",
        "part_category": "WINDSHIELD",
        "part_origin": "AFTERMARKET",
        "nags_list_price_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


# --- Claims / disclosures ---

def create_claim_payload(policy_id: str, **overrides) -> dict:
    n = _n()
    defaults = {
        "policy_id": policy_id,
        "incident_state_code": "FL",
        "service_zip_code": "33601",
        "part_category": "WINDSHIELD",
        "loss_date": "2026-04-15",
        "description": f"claim {n}",
        "requires_adas_calibration": False,
        "estimated_repair_cost_cents": 90000,
    }
    defaults.update(overrides)
    return defaults


def create_choice_disclosure_payload(**overrides) -> dict:
    defaults = {
        "disclosure_channel": "PHONE",
        "shop_solicited": False,
        "informed_of_network_options": True,
    }
    defaults.update(overrides)
    return defaults


# --- Work-order scheduling ---

def schedule_payload(expected_work_order_version: int, **overrides) -> dict:
    defaults = {
        "service_mode": "IN_SHOP",
        "scheduled_start": "2026-05-02T10:00:00Z",
        "scheduled_end": "2026-05-02T11:00:00Z",
        "expected_work_order_version": expected_work_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_calibration_event_payload(**overrides) -> dict:
    defaults = {
        "calibration_type": "STATIC",
        "scheduled_start": "2026-05-02T12:30:00Z",
        "scheduled_end": "2026-05-02T13:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# --- Invoicing ---

def part_line(part_catalog_entry_id: str, unit_price_cents: int, quantity: int = 1,
              origin_claimed: str = "AFTERMARKET") -> dict:
    return {
        "part_catalog_entry_id": part_catalog_entry_id,
        "line_type": "PART",
        "quantity": quantity,
        "origin_claimed": origin_claimed,
        "unit_price_cents": unit_price_cents,
    }


def simple_line(line_type: str, unit_price_cents: int, quantity: int = 1) -> dict:
    return {
        "line_type": line_type,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
    }


def create_invoice_payload(line_items: list, **overrides) -> dict:
    payload = {"line_items": line_items}
    payload.update(overrides)
    return payload


def audit_decision_payload(action: str, adjustment_lines=None, **overrides) -> dict:
    payload = {"action": action}
    if adjustment_lines is not None:
        payload["adjustment_lines"] = adjustment_lines
    payload.update(overrides)
    return payload


def approve_all_lines(line_amounts: list) -> list:
    """adjustment_lines approving amounts by line_index (one entry per line)."""
    return [
        {"line_index": i, "approved_amount_cents": amt}
        for i, amt in enumerate(line_amounts)
    ]


# --- Warranty / fraud ---

def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {"issue_description": "leak after install"}
    defaults.update(overrides)
    return defaults


def decide_warranty_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def resolve_alert_payload(resolution: str, **overrides) -> dict:
    payload = {"resolution": resolution}
    payload.update(overrides)
    return payload
