"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

# Unique suffix counters so that two entities of the same kind created in one
# test (or across tests in one session scope) do not collide on uniqueness keys.
_CC_CODE_COUNTER = itertools.count(1)
_ROLE_NAME_COUNTER = itertools.count(1)
_SKU_COUNTER = itertools.count(1)
_EMP_CODE_COUNTER = itertools.count(1)
_LOCATION_COUNTER = itertools.count(1)
_SERIAL_COUNTER = itertools.count(1)
_SLOT_CODE_COUNTER = itertools.count(1)
_IDEMPOTENCY_COUNTER = itertools.count(1)


def create_cost_center_payload(**overrides) -> dict:
    payload = {
        "cost_center_code": "CC-%04d" % next(_CC_CODE_COUNTER),
        "name": "Ops",
    }
    payload.update(overrides)
    return payload


def create_job_role_payload(**overrides) -> dict:
    payload = {
        "role_name": "ROLE-%d" % next(_ROLE_NAME_COUNTER),
    }
    payload.update(overrides)
    return payload


def create_item_payload(**overrides) -> dict:
    payload = {
        "sku": "SKU-%d" % next(_SKU_COUNTER),
        "name": "PPE Item",
        "category": "GENERAL",
        "base_list_price_cents": 100,
    }
    payload.update(overrides)
    return payload


def create_contract_price_payload(**overrides) -> dict:
    payload = {
        "min_period_qty": 0,
        "unit_price_cents": 100,
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
    }
    payload.update(overrides)
    return payload


def create_issuance_policy_payload(**overrides) -> dict:
    payload = {
        "period_limit_qty": 10,
        "period_window_days": 30,
    }
    payload.update(overrides)
    return payload


def create_employee_payload(**overrides) -> dict:
    payload = {
        "employee_code": "E-%04d" % next(_EMP_CODE_COUNTER),
        "full_name": "Tech One",
    }
    payload.update(overrides)
    return payload


def create_machine_payload(**overrides) -> dict:
    payload = {
        "location_code": "LOC-%04d" % next(_LOCATION_COUNTER),
        "site_name": "Plant 1",
        "model": "VM-500",
    }
    payload.update(overrides)
    return payload


def create_slot_payload(**overrides) -> dict:
    payload = {
        "slot_code": "A%d" % next(_SLOT_CODE_COUNTER),
        "capacity": 20,
        "par_level": 0,
    }
    payload.update(overrides)
    return payload


def create_serialized_unit_payload(**overrides) -> dict:
    payload = {
        "serial_number": "SN-%05d" % next(_SERIAL_COUNTER),
    }
    payload.update(overrides)
    return payload


def create_manager_override_payload(**overrides) -> dict:
    payload = {
        "approved_qty": 2,
        "valid_from": "2026-05-01",
        "valid_until": "2026-05-31",
        "reason_code": "PROJECT",
    }
    payload.update(overrides)
    return payload


def create_issuance_payload(**overrides) -> dict:
    payload = {
        "qty": 1,
        "idempotency_key": "ik-%d" % next(_IDEMPOTENCY_COUNTER),
    }
    payload.update(overrides)
    return payload


def create_restock_order_payload(**overrides) -> dict:
    payload = {
        "qty": 5,
    }
    payload.update(overrides)
    return payload


def create_service_ticket_payload(**overrides) -> dict:
    payload = {
        "issue_code": "PREVENTIVE",
        "window_start": "2026-05-01T00:00:00Z",
        "window_end": "2026-05-02T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_chargeback_batch_payload(**overrides) -> dict:
    payload = {
        "period_start": "2026-05-01",
        "period_end": "2026-06-01",
    }
    payload.update(overrides)
    return payload


def create_compliance_audit_payload(**overrides) -> dict:
    payload = {
        "scope": "OVERRIDE_USAGE",
        "period_start": "2026-05-01",
        "period_end": "2026-05-31",
    }
    payload.update(overrides)
    return payload
