"""Payload factories — one per creatable resource, input fields only.

Every factory accepts **overrides so tests control exactly the fields the
claim under test depends on; sensible defaults cover the rest.
"""

_seq_counters: dict = {}


def _next(prefix: str) -> int:
    _seq_counters[prefix] = _seq_counters.get(prefix, 0) + 1
    return _seq_counters[prefix]


def unique_account_number() -> str:
    return f"ACCT-{_next('acct'):04d}"


def unique_serial_number() -> str:
    return f"SN-{_next('sn'):04d}"


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_field_technician_payload(**overrides) -> dict:
    defaults = {"display_name": f"Tech {_next('tech')}"}
    defaults.update(overrides)
    return defaults


def create_service_account_payload(**overrides) -> dict:
    defaults = {
        "account_number": unique_account_number(),
        "service_address": "1 Test Way",
        "billing_cycle_code": "C01",
    }
    defaults.update(overrides)
    return defaults


def create_meter_payload(**overrides) -> dict:
    defaults = {
        "serial_number": unique_serial_number(),
        "meter_type": "HANDHELD",
    }
    defaults.update(overrides)
    return defaults


def install_meter_payload(service_account_id: str, **overrides) -> dict:
    defaults = {"service_account_id": service_account_id}
    defaults.update(overrides)
    return defaults


def ami_read_payload(read_value: int, read_at: str, **overrides) -> dict:
    defaults = {"read_value": read_value, "read_at": read_at}
    defaults.update(overrides)
    return defaults


def create_billing_period_payload(**overrides) -> dict:
    defaults = {
        "cycle_code": f"C{_next('cycle'):02d}",
        "period_start_date": "2026-08-01",
        "period_end_date": "2026-08-31",
        "read_window_open_date": "2026-08-03",
        "read_window_close_date": "2026-08-07",
        "bill_run_date": "2026-08-31",
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(billing_cycle_period_id: str, **overrides) -> dict:
    defaults = {
        "billing_cycle_period_id": billing_cycle_period_id,
        "scheduled_date": "2026-08-03",
        "route_shift": "AM",
    }
    defaults.update(overrides)
    return defaults


def assign_route_payload(technician_id: str, **overrides) -> dict:
    defaults = {"technician_id": technician_id}
    defaults.update(overrides)
    return defaults


def reassign_route_payload(technician_id: str, expected_route_version: int, **overrides) -> dict:
    defaults = {
        "technician_id": technician_id,
        "expected_route_version": expected_route_version,
    }
    defaults.update(overrides)
    return defaults


def capture_read_payload(
    meter_id: str,
    read_value: int,
    read_at: str,
    expected_route_stop_version: int,
    **overrides,
) -> dict:
    defaults = {
        "meter_id": meter_id,
        "read_value": read_value,
        "read_at": read_at,
        "expected_route_stop_version": expected_route_stop_version,
    }
    defaults.update(overrides)
    return defaults


def mark_no_read_payload(no_read_reason: str = "NO_ACCESS", **overrides) -> dict:
    defaults = {"no_read_reason": no_read_reason}
    defaults.update(overrides)
    return defaults


def skip_hazard_payload(hazard_flag_id: str, **overrides) -> dict:
    defaults = {"hazard_flag_id": hazard_flag_id}
    defaults.update(overrides)
    return defaults


def reject_read_payload(rejection_reason: str = "IMPLAUSIBLE_SPIKE", **overrides) -> dict:
    defaults = {"rejection_reason": rejection_reason}
    defaults.update(overrides)
    return defaults


def create_hazard_flag_payload(service_account_id: str, **overrides) -> dict:
    defaults = {
        "service_account_id": service_account_id,
        "hazard_type": "DOG",
        "severity": "HIGH",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(
    work_order_type: str,
    service_account_id: str,
    **overrides,
) -> dict:
    defaults = {
        "work_order_type": work_order_type,
        "service_account_id": service_account_id,
        "scheduled_date": "2026-08-10",
        "work_shift": "AM",
    }
    defaults.update(overrides)
    return defaults


def dispatch_work_order_payload(technician_id: str, **overrides) -> dict:
    defaults = {"technician_id": technician_id}
    defaults.update(overrides)
    return defaults


def reschedule_work_order_payload(
    scheduled_date: str,
    work_shift: str,
    expected_work_order_version: int,
    **overrides,
) -> dict:
    defaults = {
        "scheduled_date": scheduled_date,
        "work_shift": work_shift,
        "expected_work_order_version": expected_work_order_version,
    }
    defaults.update(overrides)
    return defaults


def rework_payload(rework_reason: str = "RECHECK", **overrides) -> dict:
    defaults = {"rework_reason": rework_reason}
    defaults.update(overrides)
    return defaults


def create_investigation_payload(
    service_account_id: str,
    meter_id: str,
    **overrides,
) -> dict:
    defaults = {
        "service_account_id": service_account_id,
        "meter_id": meter_id,
        "indication_type": "TAMPER_FLAG",
    }
    defaults.update(overrides)
    return defaults


def confirm_theft_payload(theft_window_months: int, monthly_estimated_kwh: list, **overrides) -> dict:
    defaults = {
        "theft_window_months": theft_window_months,
        "monthly_estimated_kwh": monthly_estimated_kwh,
    }
    defaults.update(overrides)
    return defaults


def create_replacement_campaign_payload(**overrides) -> dict:
    defaults = {
        "campaign_name": f"Campaign {_next('camp')}",
        "quota": 5,
    }
    defaults.update(overrides)
    return defaults


def enroll_payload(meter_ids: list, **overrides) -> dict:
    defaults = {"meter_ids": meter_ids}
    defaults.update(overrides)
    return defaults


def create_ops_snapshot_payload(snapshot_at: str, **overrides) -> dict:
    defaults = {"snapshot_at": snapshot_at}
    defaults.update(overrides)
    return defaults
