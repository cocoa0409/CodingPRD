"""Payload factories — one per creatable resource, input fields only."""
import itertools

_counter = itertools.count(1)

DEFAULTS = {
    "FIRM_NAME": "Acme Law",
    "FISCAL_YEAR_START_MONTH": 1,
    "STANDARD_RATE_CENTS": 50000,
    "FLAT_FEE_CENTS": 100000,
    "FISCAL_YEAR_INDEX": 2026,
    "ORIGINAL_BUDGET_CENTS": 100000,
    "TASK_CODE": "L110",
    "LITIGATION_STAGE": "DISCOVERY",
    "ENTRY_DATE": "2026-08-05",
    "REASON_CODE": "CLIENT_RELATIONS",
}


def _n() -> int:
    return next(_counter)


def create_firm_payload(**overrides) -> dict:
    defaults = {
        "name": f"{DEFAULTS['FIRM_NAME']} {_n()}",
        "fiscal_year_start_month": DEFAULTS["FISCAL_YEAR_START_MONTH"],
    }
    defaults.update(overrides)
    return defaults


def create_timekeeper_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"Timekeeper {n}",
        "bar_number": f"B{n:03d}",
        "role_title": "PARTNER",
        "standard_rate_cents": DEFAULTS["STANDARD_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "display_name": f"Client {n}",
        "client_number": f"CL{n:03d}",
    }
    defaults.update(overrides)
    return defaults


def create_matter_payload(responsible_partner_id: str, **overrides) -> dict:
    n = _n()
    defaults = {
        "matter_number": f"M{n:03d}",
        "title": f"Matter {n}",
        "litigation_stage": DEFAULTS["LITIGATION_STAGE"],
        "responsible_partner_id": responsible_partner_id,
    }
    defaults.update(overrides)
    return defaults


def create_fee_arrangement_payload(**overrides) -> dict:
    defaults = {
        "arrangement_type": "FLAT_FEE",
        "flat_fee_cents": DEFAULTS["FLAT_FEE_CENTS"],
        "fiscal_year_index": DEFAULTS["FISCAL_YEAR_INDEX"],
    }
    defaults.update(overrides)
    return defaults


def create_phase_budget_payload(**overrides) -> dict:
    defaults = {
        "litigation_stage": DEFAULTS["LITIGATION_STAGE"],
        "task_code": DEFAULTS["TASK_CODE"],
        "original_budget_cents": DEFAULTS["ORIGINAL_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_time_entry_payload(timekeeper_id: str, **overrides) -> dict:
    defaults = {
        "timekeeper_id": timekeeper_id,
        "task_code": DEFAULTS["TASK_CODE"],
        "litigation_stage": DEFAULTS["LITIGATION_STAGE"],
        "hours_worked_milli": 1000,
        "hourly_rate_cents": DEFAULTS["STANDARD_RATE_CENTS"],
        "entry_date": DEFAULTS["ENTRY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_write_down_request_payload(time_entry_ids, requested_amount_cents,
                                      **overrides) -> dict:
    defaults = {
        "time_entry_ids": list(time_entry_ids),
        "requested_amount_cents": requested_amount_cents,
        "reason_code": DEFAULTS["REASON_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_budget_amendment_payload(phase_budget_id: str, delta_cents: int,
                                    **overrides) -> dict:
    defaults = {
        "phase_budget_id": phase_budget_id,
        "delta_cents": delta_cents,
        "scope_change_reason": "scope change",
    }
    defaults.update(overrides)
    return defaults
