"""Payload factories — one per entity, input fields only (PRD §3).

Identifiers that must be unique within a test (parcel numbers, addresses,
names) are auto-generated from a per-process counter; the runner restarts
the API server before every test, so the database each suite run sees is
empty and only intra-test uniqueness matters.
"""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


# --- Work items -------------------------------------------------------------

def work_item(category: str, description: str, estimated_cost_cents: int) -> dict:
    """One declared work item (PRD §3.2)."""
    return {
        "category": category,
        "description": description,
        "estimated_cost_cents": estimated_cost_cents,
    }


def verified_item(category: str, verified_cost_cents: int) -> dict:
    """One staff-verified work item recorded at completeness acceptance (PRD §3.3)."""
    return {"category": category, "verified_cost_cents": verified_cost_cents}


# --- Districts & guideline sets ---------------------------------------------

def create_district_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "name": f"District {n}",
        "boundary_description": f"Blocks {n}-{n + 8}",
        "significance_tier": "LOCAL",
    }
    defaults.update(overrides)
    return defaults


def create_guideline_set_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "title": f"DG-{n}",
        "sections": [{"section_code": f"S{n}", "text": f"Guideline text {n}"}],
    }
    defaults.update(overrides)
    return defaults


# --- Owners & properties ------------------------------------------------------

def create_owner_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"Owner {n}",
        "email": f"owner{n}@example.com",
        "mailing_address": f"{n} Main St",
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(owner_id: str, **overrides) -> dict:
    """Property payload. district_id is optional in the PRD (a null value marks
    an inventory-only property), so it is included only when given."""
    n = _n()
    defaults = {
        "address": f"{n} Elm St",
        "parcel_number": f"P-{n:05d}",
        "owner_id": owner_id,
        "contributing_status": "NON_CONTRIBUTING",
        "construction_year": 1950,
        "assessed_value_cents": 5_000_000,
    }
    defaults.update(overrides)
    return defaults


# --- Meetings -----------------------------------------------------------------

def create_meeting_payload(**overrides) -> dict:
    defaults = {
        "meeting_date": "2026-09-01T00:00:00Z",
        "location": "City Hall",
        "agenda_capacity": 2,
    }
    defaults.update(overrides)
    return defaults


# --- Applications -------------------------------------------------------------

def create_application_payload(property_id: str, owner_id: str, **overrides) -> dict:
    n = _n()
    defaults = {
        "property_id": property_id,
        "owner_id": owner_id,
        "application_type": "ALTERATION",
        "is_visible_from_public_way": False,
        "after_the_fact": False,
        "work_items": [work_item("SITE_WORK", f"work {n}", 200000)],
    }
    defaults.update(overrides)
    return defaults


def resubmit_payload(work_items, **overrides) -> dict:
    defaults = {"work_items": work_items}
    defaults.update(overrides)
    return defaults


# --- Hearings & comments --------------------------------------------------------

def create_hearing_payload(application_id: str, meeting_id: str, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "meeting_id": meeting_id,
        "notice_posted_at": "2026-08-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_comment_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "commenter_name": f"Commenter {n}",
        "stance": "SUPPORT",
        "comment_text": f"Comment text {n}",
    }
    defaults.update(overrides)
    return defaults


# --- Appeals --------------------------------------------------------------------

def create_appeal_payload(application_id: str, **overrides) -> dict:
    n = _n()
    defaults = {"application_id": application_id, "grounds": f"Appeal grounds {n}"}
    defaults.update(overrides)
    return defaults


# --- Violations -----------------------------------------------------------------

def create_violation_payload(property_id: str, **overrides) -> dict:
    n = _n()
    defaults = {
        "property_id": property_id,
        "observed_violation_date": "2026-07-01T00:00:00Z",
        "work_description": f"Unpermitted work {n}",
    }
    defaults.update(overrides)
    return defaults


# --- Hardship reviews -------------------------------------------------------------

def create_hardship_review_payload(application_id: str, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "claimed_rate_of_return_pct": 1.5,
        "appraisal_basis_cents": 6_000_000,
    }
    defaults.update(overrides)
    return defaults


# --- Certificates -----------------------------------------------------------------

def create_certificate_payload(application_id: str, **overrides) -> dict:
    defaults = {"application_id": application_id}
    defaults.update(overrides)
    return defaults
