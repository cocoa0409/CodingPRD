"""Payload factories — one per entity, input fields only (PRD Section 3 & 4)."""

DEFAULTS = {
    "TRAVELER_EMAIL": "traveler@example.com",
    "TRAVELER_NAME": "Test Traveler",
    "HOME_STATE": "CA",
    "APPROVER_EMAIL": "approver@example.com",
    "APPROVER_NAME": "Test Approver",
    "APPROVAL_LIMIT": 1_000_000,
    "POLICY_NAME": "Std",
    "DEST_STATE": "CA",
}


def create_traveler_payload(manager_id, **overrides) -> dict:
    """Traveler input fields (PRD §3.1): email, full_name, home_office_state, manager_id."""
    payload = {
        "email": DEFAULTS["TRAVELER_EMAIL"],
        "full_name": DEFAULTS["TRAVELER_NAME"],
        "home_office_state": DEFAULTS["HOME_STATE"],
        "manager_id": manager_id,
    }
    payload.update(overrides)
    return payload


def create_approver_payload(**overrides) -> dict:
    """Approver input fields (PRD §3.1): email, full_name, approval_limit_cents."""
    payload = {
        "email": DEFAULTS["APPROVER_EMAIL"],
        "full_name": DEFAULTS["APPROVER_NAME"],
        "approval_limit_cents": DEFAULTS["APPROVAL_LIMIT"],
    }
    payload.update(overrides)
    return payload


def create_travel_policy_payload(**overrides) -> dict:
    """TravelPolicy input fields (PRD §3.1)."""
    payload = {
        "name": DEFAULTS["POLICY_NAME"],
        "max_economy_fare_cents": 50000,
        "business_class_min_hours": 6,
        "advance_purchase_days": 14,
        "cdw_daily_cap_cents": 3000,
        "mileage_rate_milli_cents": 67000,
        "receipt_required_threshold_cents": 7500,
    }
    payload.update(overrides)
    return payload


def create_per_diem_rate_payload(**overrides) -> dict:
    """PerDiemRate input fields (PRD §3.1): state_code, lodging_cap_cents, mie_cents."""
    payload = {
        "state_code": "CA",
        "lodging_cap_cents": 20000,
        "mie_cents": 8000,
    }
    payload.update(overrides)
    return payload


def create_trip_request_payload(traveler_id, **overrides) -> dict:
    """TripRequest input fields (PRD §3.2)."""
    payload = {
        "traveler_id": traveler_id,
        "destination_state": DEFAULTS["DEST_STATE"],
        "start_date": "2026-06-01",
        "end_date": "2026-06-03",
        "budget_total_cents": 100000,
    }
    payload.update(overrides)
    return payload


def issue_virtual_card_payload(expected_trip_request_version, **overrides) -> dict:
    """VirtualCard issuance input fields (PRD §3.3): load_limit_cents, expected_trip_request_version."""
    payload = {
        "load_limit_cents": 100000,
        "expected_trip_request_version": expected_trip_request_version,
    }
    payload.update(overrides)
    return payload


def create_expense_report_payload(trip_request_id, **overrides) -> dict:
    """ExpenseReport input fields (PRD §3.4): trip_request_id, title, per_diem_method?."""
    payload = {
        "trip_request_id": trip_request_id,
        "title": "Test Report",
    }
    payload.update(overrides)
    return payload


def create_expense_line_payload(report_id, line_type, **overrides) -> dict:
    """ExpenseLine input fields (PRD §3.4). Type-specific fields supplied via overrides."""
    payload = {
        "report_id": report_id,
        "line_type": line_type,
        "claimed_amount_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_receipt_payload(expense_line_id, **overrides) -> dict:
    """Receipt input fields (PRD §3.7): expense_line_id, image_ref."""
    payload = {
        "expense_line_id": expense_line_id,
        "image_ref": "img://test-receipt",
    }
    payload.update(overrides)
    return payload


def ocr_receipt_payload(ocr_amount_cents, **overrides) -> dict:
    """OCR input fields (PRD §3.7): ocr_amount_cents, ocr_merchant."""
    payload = {
        "ocr_amount_cents": ocr_amount_cents,
        "ocr_merchant": "Test Merchant",
    }
    payload.update(overrides)
    return payload


def create_approval_step_payload(report_id, approver_id, step_order, **overrides) -> dict:
    """ApprovalStep input fields (PRD §3.9): report_id, approver_id, step_order."""
    payload = {
        "report_id": report_id,
        "approver_id": approver_id,
        "step_order": step_order,
    }
    payload.update(overrides)
    return payload
