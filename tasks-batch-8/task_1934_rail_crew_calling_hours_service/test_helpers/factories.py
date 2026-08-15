"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_employee_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "employee_number": f"E{n:04d}",
        "full_name": f"Test Employee {n}",
        "craft": "CONDUCTOR",
        "seniority_date": "2010-01-01T00:00:00Z",
        "home_terminal": "CHI",
    }
    defaults.update(overrides)
    return defaults


def create_extra_board_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "board_code": f"CHI-CONDR-EB-{n:03d}",
        "craft": "CONDUCTOR",
        "terminal": "CHI",
        "guaranteed_slots": 1,
    }
    defaults.update(overrides)
    return defaults


def create_slot_payload(employee_id: str, **overrides) -> dict:
    defaults = {"employee_id": employee_id}
    defaults.update(overrides)
    return defaults


def create_job_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "job_symbol": f"M-CHI-{n:03d}",
        "craft": "CONDUCTOR",
        "origin_terminal": "CHI",
        "report_time": "2026-08-03T08:00:00Z",
        "crew_required": 1,
    }
    defaults.update(overrides)
    return defaults


def create_leave_bid_payload(employee_id: str, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "leave_type": "VACATION",
        "start_date": "2026-08-10T00:00:00Z",
        "end_date": "2026-08-12T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_pay_record_payload(employee_id: str, assignment_id: str, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "assignment_id": assignment_id,
        "claimed_minutes": 240,
        "claimed_deadhead_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


def resolve_shortage_payload(assignment_id: str, relieving_employee_id: str,
                             **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "relieving_employee_id": relieving_employee_id,
    }
    defaults.update(overrides)
    return defaults
