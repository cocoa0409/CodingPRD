"""Payload factories — one per entity, input fields only."""
import itertools

_seq = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}{next(_seq)}"


def create_customer_payload(**overrides) -> dict:
    n = next(_seq)
    payload = {"full_name": f"Customer {n}", "email": f"cust{n}@x.com", "phone": "555-0100"}
    payload.update(overrides)
    return payload


def create_device_payload(customer_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "category": "PHONE",
        "brand": "Acme",
        "model": "Z1",
        "serial_number": _uniq("SN"),
        "market_value_cents": 60000,
    }
    payload.update(overrides)
    return payload


def create_technician_payload(**overrides) -> dict:
    payload = {"full_name": f"Tech {next(_seq)}", "certification_level": "STANDARD"}
    payload.update(overrides)
    return payload


def create_repair_bay_payload(**overrides) -> dict:
    payload = {"bay_name": _uniq("Bay-")}
    payload.update(overrides)
    return payload


def create_part_payload(**overrides) -> dict:
    payload = {"sku": _uniq("SKU-"), "name": "Screen", "unit_price_cents": 6000, "on_hand_qty": 10}
    payload.update(overrides)
    return payload


def create_repair_ticket_payload(device_id, customer_id, **overrides) -> dict:
    payload = {
        "device_id": device_id,
        "customer_id": customer_id,
        "intake_channel": "WALK_IN",
        "reported_issue": "cracked screen",
        "spend_cap_cents": 100000,
    }
    payload.update(overrides)
    return payload


def diagnose_payload(technician_id, bay_id,
                     start="2026-05-02T10:00:00Z", end="2026-05-02T11:00:00Z",
                     **overrides) -> dict:
    payload = {
        "assigned_technician_id": technician_id,
        "assigned_bay_id": bay_id,
        "scheduled_start_at": start,
        "scheduled_end_at": end,
    }
    payload.update(overrides)
    return payload


def create_estimate_payload(labor_hours, expected_repair_ticket_version, **overrides) -> dict:
    payload = {"labor_hours": labor_hours,
               "expected_repair_ticket_version": expected_repair_ticket_version}
    payload.update(overrides)
    return payload


def create_part_order_payload(part_id, quantity=1, **overrides) -> dict:
    payload = {"part_id": part_id, "quantity": quantity}
    payload.update(overrides)
    return payload


def create_trade_in_payload(customer_id, device_id, declared_grade="A", **overrides) -> dict:
    payload = {"customer_id": customer_id, "device_id": device_id, "declared_grade": declared_grade}
    payload.update(overrides)
    return payload


def offer_trade_in_payload(assessed_grade, has_accessories=False,
                           assessed_cosmetic_defect_count=0, **overrides) -> dict:
    payload = {
        "assessed_grade": assessed_grade,
        "has_accessories": has_accessories,
        "assessed_cosmetic_defect_count": assessed_cosmetic_defect_count,
    }
    payload.update(overrides)
    return payload


def create_data_wipe_certificate_payload(device_id, method="CRYPTO_ERASE",
                                         wipe_result="SUCCESS", **overrides) -> dict:
    payload = {"device_id": device_id, "method": method, "wipe_result": wipe_result}
    payload.update(overrides)
    return payload


def create_claim_payload(repair_ticket_id, customer_id, plan_type="ADH", **overrides) -> dict:
    payload = {"repair_ticket_id": repair_ticket_id, "customer_id": customer_id,
               "plan_type": plan_type}
    payload.update(overrides)
    return payload
