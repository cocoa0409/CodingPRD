"""Payload factories — one per entity, input fields only (PRD §3).

Identifiers that carry uniqueness obligations (policy_number per
(carrier_code, coverage_line), and the broker-assigned production_code)
are auto-suffixed with a monotonically increasing counter so independent
entities never collide within a test run.
"""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_production_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "production_code": f"PRD-TEST-{n:04d}",
        "title": f"Test Production {n}",
        "production_type": "COMMERCIAL",
        "principal_photography_start": "2026-06-01T00:00:00Z",
        "principal_photography_end": "2026-08-01T00:00:00Z",
        "budget_cents": 100000000,
        "requires_completion_bond": False,
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    n = _seq()
    line = overrides.get("coverage_line", "GENERAL_LIABILITY")
    carrier = overrides.get("carrier_code", "AIG")
    defaults = {
        "coverage_line": line,
        "carrier_code": carrier,
        "policy_number": f"{carrier}-{line}-{n:05d}",
        "limit_cents": 100000000,
        "aggregate_limit_cents": 200000000,
        "deductible_cents": 100000,
        "effective_date": "2026-05-01T00:00:00Z",
        "expiry_date": "2026-12-31T00:00:00Z",
        "payroll_basis_cents": 10000000,
    }
    defaults.update(overrides)
    return defaults


def create_cast_member_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Cast Member {n}",
        "role_tier": "SUPPORTING",
        "weekly_salary_cents": 500000,
        "essential_element": False,
    }
    defaults.update(overrides)
    return defaults


def create_cast_endorsement_payload(cast_member_id: str, policy_id: str,
                                    **overrides) -> dict:
    defaults = {
        "cast_member_id": cast_member_id,
        "policy_id": policy_id,
        "endorsement_type": "PHYSICAL_CLEARANCE",
        "underwriter_notes": "Standard notes",
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "certificate_type": "VENDOR",
        "holder_name": f"Holder {n}",
        "holder_address": f"{n} Holder Lane",
        "coverage_lines": ["GENERAL_LIABILITY"],
        "location_start": "2026-06-01T00:00:00Z",
        "location_end": "2026-06-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(policy_id: str, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "claim_type": "DAMAGE",
        "occurrence_date": "2026-06-05T00:00:00Z",
        "loss_amount_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_clearance_item_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "clearance_kind": "SCRIPT",
        "item_reference": f"Clearance item {n}",
        "legal_reviewer": "Counsel A",
        "notes": "No exceptions",
    }
    defaults.update(overrides)
    return defaults


def create_completion_bond_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "surety_company": f"SuretyCo {n}",
        "bond_amount_cents": 600000000,
    }
    defaults.update(overrides)
    return defaults


def create_travel_extension_payload(**overrides) -> dict:
    defaults = {
        "territory_code": "FR",
        "travel_window_start": "2026-07-01T00:00:00Z",
        "travel_window_end": "2026-07-15T00:00:00Z",
        "travelers_count": 5,
        "repatriation_limit_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_payroll_audit_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "audit_period_start": "2026-05-01T00:00:00Z",
        "audit_period_end": "2026-08-01T00:00:00Z",
        "auditor_name": f"External Audits {n}",
        "reported_payroll_cents": 55000000,
    }
    defaults.update(overrides)
    return defaults


def create_renewal_offer_payload(**overrides) -> dict:
    defaults = {
        "renewal_term_months": 12,
    }
    defaults.update(overrides)
    return defaults
