"""Payload factories — one per entity, input fields only.

Each factory uses a counter to mint unique human-meaningful keys (plan code,
equipment serial) so independent tests never collide on the uniqueness
constraints of PRD §2.10.
"""
import itertools

_plan_code_seq = itertools.count(1)
_serial_seq = itertools.count(1)
_postal_seq = itertools.count(1)


def unique_plan_code(prefix="PLAN"):
    return f"{prefix}-{next(_plan_code_seq)}"


def unique_serial(prefix="SN"):
    return f"{prefix}-{next(_serial_seq)}"


def unique_postal():
    return f"{20000 + next(_postal_seq)}"


def create_service_address_payload(**overrides) -> dict:
    defaults = {
        "line1": "1 Test Lane",
        "postal_code": unique_postal(),
        "coverage_status": "SERVICEABLE",
        "technology": "FIBER",
        "max_serviceable_mbps": 1000,
        "self_install_eligible": True,
    }
    defaults.update(overrides)
    return defaults


def create_service_plan_payload(**overrides) -> dict:
    defaults = {
        "code": unique_plan_code(),
        "tier": "PLUS",
        "download_mbps": 500,
        "throttled_mbps": 50,
        "monthly_fee_cents": 8999,
        "included_gb": 1000,
        "overage_policy": "BILL",
        "contract_term_months": 0,
        "etf_full_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_unit_payload(**overrides) -> dict:
    defaults = {
        "kind": "MODEM",
        "serial": unique_serial(),
        "lease_fee_cents_per_cycle": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Tech",
        "travel_buffer_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_install_slot_payload(technician_id, **overrides) -> dict:
    defaults = {
        "technician_id": technician_id,
        "window_start_iso": "2026-06-02T09:00:00Z",
        "window_end_iso": "2026-06-02T17:00:00Z",
        "capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(service_address_id, plan_id,
                           customer_user_id="cust-test", **overrides) -> dict:
    defaults = {
        "service_address_id": service_address_id,
        "plan_id": plan_id,
        "customer_user_id": customer_user_id,
    }
    defaults.update(overrides)
    return defaults


def create_service_order_payload(account_id, requested_plan_id,
                                 order_type="NEW_INSTALL",
                                 install_mode="SELF_INSTALL", **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "order_type": order_type,
        "install_mode": install_mode,
        "requested_plan_id": requested_plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_install_appointment_payload(service_order_id, install_slot_id,
                                       expected_account_version,
                                       start_iso="2026-06-02T09:00:00Z",
                                       end_iso="2026-06-02T10:00:00Z", **overrides) -> dict:
    defaults = {
        "service_order_id": service_order_id,
        "install_slot_id": install_slot_id,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_billing_cycle_payload(account_id, cycle_start_iso, cycle_end_iso,
                                 **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "cycle_start_iso": cycle_start_iso,
        "cycle_end_iso": cycle_end_iso,
    }
    defaults.update(overrides)
    return defaults


def create_usage_record_payload(account_id, billing_cycle_id, gb,
                                posted_at_iso="2026-06-10T00:00:00Z", **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "billing_cycle_id": billing_cycle_id,
        "posted_at_iso": posted_at_iso,
        "gb": gb,
    }
    defaults.update(overrides)
    return defaults


def create_outage_event_payload(account_id, billing_cycle_id,
                                started_at_iso="2026-06-05T00:00:00Z", **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "billing_cycle_id": billing_cycle_id,
        "started_at_iso": started_at_iso,
    }
    defaults.update(overrides)
    return defaults


def create_goodwill_credit_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_transfer_request_payload(account_id, to_service_address_id, to_plan_id,
                                    **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "to_service_address_id": to_service_address_id,
        "to_plan_id": to_plan_id,
    }
    defaults.update(overrides)
    return defaults
