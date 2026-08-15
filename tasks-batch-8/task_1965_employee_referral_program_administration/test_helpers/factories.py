"""Payload factories — one per entity, input fields only."""

_COUNTER = {"n": 0}


def _next() -> int:
    _COUNTER["n"] += 1
    return _COUNTER["n"]


def create_employee_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "employee_number": f"E{n:04d}",
        "full_name": f"Employee {n}",
        "email": f"emp{n}@corp.com",
        "department": "ENGINEERING",
        "job_level": "IC",
        "hire_date": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_candidate_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"Candidate {n}",
        "email": f"cand{n}@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_requisition_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "req_number": f"REQ-{n:04d}",
        "title": f"Role {n}",
        "department": "ENGINEERING",
        "level": "IC",
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "effective_from": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Campaign {n}",
        "multiplier_bps": 15000,
        "flat_addon_cents": 50000,
        "window_start": "2026-07-01T00:00:00Z",
        "window_end": "2026-09-30T00:00:00Z",
        "budget_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "candidate_email": f"cand{n}@x.com",
        "candidate_full_name": f"Candidate {n}",
    }
    defaults.update(overrides)
    return defaults


def create_payroll_batch_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "period_label": f"2026-08{chr(ord('A') + (n % 26))}",
    }
    defaults.update(overrides)
    return defaults


def create_abuse_case_payload(**overrides) -> dict:
    defaults = {
        "case_type": "MANUAL",
    }
    defaults.update(overrides)
    return defaults


def create_tax_profile_payload(**overrides) -> dict:
    defaults = {
        "filing_status": "SINGLE",
        "withholding_method": "FLAT",
    }
    defaults.update(overrides)
    return defaults
