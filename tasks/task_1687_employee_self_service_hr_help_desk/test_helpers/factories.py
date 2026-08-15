"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


# ---- Employees ----

def create_employee_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "employee_number": f"E{n:05d}",
        "full_name": f"Test Employee {n}",
        "email": f"employee{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


# ---- Teams ----

def create_team_payload(**overrides) -> dict:
    n = _seq()
    defaults = {"name": f"Team {n}", "description": f"Team {n} purpose"}
    defaults.update(overrides)
    return defaults


# ---- Agents ----

def create_agent_payload(team_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "display_name": f"Agent {n}",
        "email": f"agent{n}@example.com",
        "tier": "T1",
        "team_id": team_id,
    }
    defaults.update(overrides)
    return defaults


# ---- Ticket categories ----

def create_category_payload(specialist_team_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "code": f"CAT-{n:04d}",
        "name": f"Category {n}",
        "specialist_team_id": specialist_team_id,
    }
    defaults.update(overrides)
    return defaults


# ---- SLA policies ----

def create_sla_policy_payload(category_id, **overrides) -> dict:
    defaults = {
        "category_id": category_id,
        "priority": "P3",
        "first_response_minutes": 480,
        "resolution_minutes": 480,
    }
    defaults.update(overrides)
    return defaults


# ---- KB articles ----

def create_kb_article_payload(category_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "title": f"Article {n}",
        "body": f"Body of article {n}",
        "category_id": category_id,
    }
    defaults.update(overrides)
    return defaults


# ---- Article views ----

def create_article_view_payload(article_id, **overrides) -> dict:
    defaults = {"article_id": article_id}
    defaults.update(overrides)
    return defaults


# ---- Tickets ----

def create_ticket_payload(employee_id, category_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "employee_id": employee_id,
        "category_id": category_id,
        "subject": f"Ticket subject {n}",
        "description": f"Ticket description {n}",
    }
    defaults.update(overrides)
    return defaults


# ---- Data change requests ----

ADDRESS_NEW_VALUES = {
    "address_line1": "100 Main St",
    "city": "Denver",
    "region": "CO",
    "postal_code": "80202",
}

DIRECT_DEPOSIT_NEW_VALUES = {
    "bank_routing_number": "021000021",
    "bank_account_number": "123456789",
    "bank_account_type": "CHECKING",
}


def create_dcr_payload(employee_id, change_type, expected_employee_version, **overrides) -> dict:
    if change_type == "ADDRESS":
        new_values = dict(ADDRESS_NEW_VALUES)
    else:
        new_values = dict(DIRECT_DEPOSIT_NEW_VALUES)
    defaults = {
        "employee_id": employee_id,
        "change_type": change_type,
        "new_values": new_values,
        "expected_employee_version": expected_employee_version,
    }
    defaults.update(overrides)
    return defaults


# ---- Staffing windows ----

def create_staffing_window_payload(team_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "team_id": team_id,
        "name": f"Window {n}",
        "window_start": "2026-08-03T00:00:00Z",
        "window_end": "2026-08-08T00:00:00Z",
        "required_t1_hours": 10,
        "required_t2_hours": 0,
    }
    defaults.update(overrides)
    return defaults


# ---- Agent shifts ----

def create_agent_shift_payload(agent_id, staffing_window_id, **overrides) -> dict:
    defaults = {
        "agent_id": agent_id,
        "staffing_window_id": staffing_window_id,
        "shift_start": "2026-08-03T09:00:00Z",
        "shift_end": "2026-08-03T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults
