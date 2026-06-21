"""Payload factories — one per entity, input fields only.

Each factory returns a dict carrying exactly the client-supplied (input) fields
for a create/record call; computed and system fields are never included.
"""
import itertools

_code_counter = itertools.count(1)


def unique_code(prefix: str = "CAT") -> str:
    """Generate a process-unique activity code so parallel creates do not collide."""
    return f"{prefix}_{next(_code_counter)}"


# ─── ActivityCategory (POST /activity-categories) ──────────────────────────
def create_activity_category_payload(**overrides) -> dict:
    """Inputs: code, risk_tier, activity_base_risk, required_inspection_count,
    requires_zoning_check, term_months, allowed_zones."""
    defaults = {
        "code": unique_code("ACT"),
        "risk_tier": "LOW",
        "activity_base_risk": 10,
        "required_inspection_count": 0,
        "requires_zoning_check": False,
        "term_months": 12,
        "allowed_zones": ["C1"],
    }
    defaults.update(overrides)
    return defaults


# ─── Business (POST /businesses) ───────────────────────────────────────────
def create_business_payload(**overrides) -> dict:
    """Inputs: legal_name, owner_name, zone_code."""
    defaults = {
        "legal_name": "Test Business",
        "owner_name": "Test Owner",
        "zone_code": "C1",
    }
    defaults.update(overrides)
    return defaults


# ─── Application (POST /applications) ──────────────────────────────────────
def create_application_payload(business_id: str, activity_category_id: str,
                               **overrides) -> dict:
    """Inputs: business_id, activity_category_id, declared_employee_count,
    requested_zone_code."""
    defaults = {
        "business_id": business_id,
        "activity_category_id": activity_category_id,
        "declared_employee_count": 1,
        "requested_zone_code": "C1",
    }
    defaults.update(overrides)
    return defaults


# ─── Inspection (POST /inspections) ────────────────────────────────────────
def create_inspection_payload(application_id: str, inspector_user_id: str,
                              **overrides) -> dict:
    """Inputs: application_id, inspector_user_id (required); verified_employee_count
    and failed_item_count are optional at scheduling."""
    defaults = {
        "application_id": application_id,
        "inspector_user_id": inspector_user_id,
    }
    defaults.update(overrides)
    return defaults


def record_inspection_payload(result: str, verified_employee_count: int,
                              failed_item_count: int, **overrides) -> dict:
    """Inputs for POST /inspections/{id}/record: result, verified_employee_count,
    failed_item_count."""
    defaults = {
        "result": result,
        "verified_employee_count": verified_employee_count,
        "failed_item_count": failed_item_count,
    }
    defaults.update(overrides)
    return defaults


# ─── Endorsement (POST /endorsements) ──────────────────────────────────────
def create_endorsement_payload(license_id: str, **overrides) -> dict:
    """Inputs: license_id, kind, condition_text."""
    defaults = {
        "license_id": license_id,
        "kind": "LATE_HOURS",
        "condition_text": "Standard condition text",
    }
    defaults.update(overrides)
    return defaults


# ─── OwnershipTransfer (POST /transfers) ───────────────────────────────────
def create_transfer_payload(license_id: str, from_business_id: str,
                            to_business_id: str, **overrides) -> dict:
    """Inputs: license_id, from_business_id, to_business_id."""
    defaults = {
        "license_id": license_id,
        "from_business_id": from_business_id,
        "to_business_id": to_business_id,
    }
    defaults.update(overrides)
    return defaults


def complete_transfer_payload(expected_license_version: int, **overrides) -> dict:
    """Input for POST /transfers/{id}/complete: expected_license_version (OCC)."""
    defaults = {"expected_license_version": expected_license_version}
    defaults.update(overrides)
    return defaults
