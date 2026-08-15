"""Payload factories — one per entity, input fields only (PRD section 3)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_property_payload(**overrides) -> dict:
    defaults = {
        "name": f"Tower {_n()}",
        "address": f"{_n()} Main St",
        "max_concurrent_construction_projects": 2,
    }
    defaults.update(overrides)
    return defaults


def create_lease_space_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "suite_number": f"S{n}",
        "floor": 1 + (n % 40),
        "rentable_sqft": TEST_DEFAULTS["RENTABLE_SQFT"],
    }
    defaults.update(overrides)
    return defaults


def create_tenant_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "legal_name": f"Tenant Co {n}",
        "contact_email": f"ops{n}@tenant.example",
        "tax_id": f"T-{n:04d}",
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(space_id, tenant_id, **overrides) -> dict:
    defaults = {
        "space_id": space_id,
        "tenant_id": tenant_id,
        "base_rent_annual_cents": TEST_DEFAULTS["BASE_RENT_ANNUAL_CENTS"],
        "scheduled_rent_commencement_date": TEST_DEFAULTS["SCHEDULED_RCD"],
        "lease_term_months": TEST_DEFAULTS["LEASE_TERM_MONTHS"],
        "abatement_basis": "CALENDAR",
    }
    defaults.update(overrides)
    return defaults


def create_ti_project_payload(**overrides) -> dict:
    defaults = {
        "project_name": f"Suite Build-Out {_n()}",
        "base_contract_cents": TEST_DEFAULTS["BASE_CONTRACT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_work_letter_payload(**overrides) -> dict:
    defaults = {
        "scope_description": "Full-suite tenant improvement scope",
        "allowance_offer_cents": TEST_DEFAULTS["ALLOWANCE_OFFER_CENTS"],
        "work_delineation": "SPLIT",
    }
    defaults.update(overrides)
    return defaults


def counter_work_letter_payload(expected_work_letter_version, **overrides) -> dict:
    defaults = {
        "scope_description": "Tenant counter-proposal scope",
        "allowance_offer_cents": TEST_DEFAULTS["ALLOWANCE_OFFER_CENTS"],
        "work_delineation": "SPLIT",
        "expected_work_letter_version": expected_work_letter_version,
    }
    defaults.update(overrides)
    return defaults


def create_plan_submission_payload(**overrides) -> dict:
    defaults = {"drawing_set_ref": f"DS-{_n():04d}"}
    defaults.update(overrides)
    return defaults


def create_review_comment_payload(**overrides) -> dict:
    defaults = {"comment_text": "Review note", "severity": "INFO"}
    defaults.update(overrides)
    return defaults


def create_contractor_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "company_name": f"BuildCo {n}",
        "license_number": f"LIC-{n:04d}",
        "insurance_expiry_date": TEST_DEFAULTS["INSURANCE_EXPIRY"],
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(contractor_id, **overrides) -> dict:
    defaults = {"contractor_id": contractor_id, "scope_note": "General contractor"}
    defaults.update(overrides)
    return defaults


def create_milestone_payload(**overrides) -> dict:
    defaults = {
        "milestone_name": f"Milestone {_n()}",
        "window_start": TEST_DEFAULTS["CONSTRUCTION_START"],
        "window_end": "2026-08-14T00:00:00Z",
        "work_type": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(expected_ti_project_version, lines=None, **overrides) -> dict:
    defaults = {
        "description": f"Change order {_n()}",
        "lines": lines
        if lines is not None
        else [{"description": "scope change", "amount_cents": 100_000}],
        "expected_ti_project_version": expected_ti_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_draw_payload(expected_ti_project_version, **overrides) -> dict:
    defaults = {
        "period_end_date": TEST_DEFAULTS["PERIOD_END"],
        "requested_amount_cents": 1_000_000,
        "expected_ti_project_version": expected_ti_project_version,
    }
    defaults.update(overrides)
    return defaults


def approve_draw_payload(approved_amount_cents, **overrides) -> dict:
    defaults = {"approved_amount_cents": approved_amount_cents}
    defaults.update(overrides)
    return defaults


def create_lien_waiver_payload(contractor_id, amount_cents, **overrides) -> dict:
    defaults = {
        "contractor_id": contractor_id,
        "waiver_type": "UNCONDITIONAL_PROGRESS",
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_punch_item_payload(engagement_id, **overrides) -> dict:
    defaults = {
        "assigned_engagement_id": engagement_id,
        "description": f"Deficiency {_n()}",
        "location": "Suite interior",
        "severity": "COSMETIC",
    }
    defaults.update(overrides)
    return defaults


def issue_certificate_payload(**overrides) -> dict:
    defaults = {
        "occupancy_certificate_ref": f"CO-{_n():04d}",
        "issued_on": "2026-09-11T00:00:00Z",
        "delay_responsibility": "NONE",
    }
    defaults.update(overrides)
    return defaults
