"""Payload factories — one per entity, input fields only.

Field names match the PRD verbatim. Optional fields are omitted from defaults
unless a test overrides them, so a faithful server applies its own defaults.
"""

DEFAULTS = {
    "JURISDICTION_NAME": "Test City",
    "CODE_EDITION": "IBC-2021",
    "VALUATION_FEE_RATE_PER_1000": 10,
    "SQUARE_FOOT_RATE": 120,
    "PLAN_REVIEW_FEE_PCT": 0.65,
    "MINIMUM_PERMIT_FEE": 100,
    "BUSINESS_NAME": "Acme Builders",
    "LICENSE_EXPIRY_FAR": "2030-01-01T00:00:00Z",
    "BOND_AMOUNT_OK": 20000,
    "DECLARED_VALUATION_SMALL": 2000,
}


def create_jurisdiction_payload(**overrides) -> dict:
    """POST /jurisdictions. renewal_fee_pct and permit_valid_days are optional."""
    payload = {
        "name": DEFAULTS["JURISDICTION_NAME"],
        "code_edition": DEFAULTS["CODE_EDITION"],
        "valuation_fee_rate_per_1000": DEFAULTS["VALUATION_FEE_RATE_PER_1000"],
        "square_foot_rate": DEFAULTS["SQUARE_FOOT_RATE"],
        "plan_review_fee_pct": DEFAULTS["PLAN_REVIEW_FEE_PCT"],
        "minimum_permit_fee": DEFAULTS["MINIMUM_PERMIT_FEE"],
    }
    payload.update(overrides)
    return payload


def create_contractor_payload(**overrides) -> dict:
    """POST /contractors. license_status and bond_status are optional."""
    payload = {
        "business_name": DEFAULTS["BUSINESS_NAME"],
        "license_number": "L-DEFAULT",
        "license_status": "ACTIVE",
        "license_expiry": DEFAULTS["LICENSE_EXPIRY_FAR"],
        "bond_amount": DEFAULTS["BOND_AMOUNT_OK"],
        "bond_status": "VERIFIED",
    }
    payload.update(overrides)
    return payload


def create_inspector_payload(**overrides) -> dict:
    """POST /inspectors."""
    payload = {
        "full_name": "Test Inspector",
        "badge_number": "B-DEFAULT",
    }
    payload.update(overrides)
    return payload


def create_plan_reviewer_payload(**overrides) -> dict:
    """POST /plan-reviewers."""
    payload = {
        "full_name": "Test Reviewer",
        "cert_number": "C-DEFAULT",
    }
    payload.update(overrides)
    return payload


def create_permit_payload(jurisdiction_id, contractor_id, **overrides) -> dict:
    """POST /permits. declared_valuation / floor_area_sqft are conditional inputs."""
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "contractor_id": contractor_id,
        "work_class": "REPAIR",
        "fee_method": "VALUATION",
        "declared_valuation": DEFAULTS["DECLARED_VALUATION_SMALL"],
    }
    payload.update(overrides)
    return payload


def create_payment_payload(amount, **overrides) -> dict:
    """POST /permits/{id}/payments. payment_status is optional (defaults CLEARED)."""
    payload = {"amount": amount}
    payload.update(overrides)
    return payload


def open_review_payload(reviewer_id, **overrides) -> dict:
    """POST /permits/{id}/reviews."""
    payload = {"reviewer_id": reviewer_id}
    payload.update(overrides)
    return payload


def correction_notice_payload(**overrides) -> dict:
    """POST /reviews/{id}/correction-notices."""
    payload = {
        "code_section": "R311.7",
        "description": "Correction required",
    }
    payload.update(overrides)
    return payload


def create_slot_payload(inspector_id, window_start, window_end, **overrides) -> dict:
    """POST /inspection-slots. max_inspections is optional (defaults 1)."""
    payload = {
        "inspector_id": inspector_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def schedule_inspection_payload(slot_id, inspection_type, scheduled_start, scheduled_end, **overrides) -> dict:
    """POST /permits/{id}/inspections."""
    payload = {
        "slot_id": slot_id,
        "inspection_type": inspection_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def stop_work_order_payload(**overrides) -> dict:
    """POST /permits/{id}/stop-work-orders."""
    payload = {"reason": "Safety hazard observed"}
    payload.update(overrides)
    return payload
