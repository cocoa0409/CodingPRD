"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "EMPLOYEE_NAME": "Test Employee",
    "JOB_LEVEL": "MANAGER",
    "HOME_OWNERSHIP": "RENTER",
    "MOVE_SCOPE": "DOMESTIC",
    "ORIGIN_CITY": "Chicago",
    "DESTINATION_CITY": "Denver",
    "EXPECTED_MOVE_DATE": "2026-09-01T00:00:00Z",
    "VENDOR_NAME": "Test Movers",
    "TRAVEL_DATE": "2026-08-15T00:00:00Z",
}


def create_policy_payload(**overrides) -> dict:
    """Policy tier payload; defaults are the MANAGER/DOMESTIC/RENTER flat-rate tier."""
    defaults = {
        "job_level": "MANAGER",
        "move_scope": "DOMESTIC",
        "home_ownership": "RENTER",
        "hhg_cap_cents": 500000,
        "temp_housing_cap_cents": 300000,
        "temp_housing_max_nights": 30,
        "travel_cap_cents": 100000,
        "loss_on_sale_cap_cents": 0,
        "misc_cap_cents": 200000,
        "home_sale_eligible": False,
        "repayment_window_months": 24,
        "gross_up_method": "FLAT_SUPPLEMENTAL",
        "flat_gross_up_rate": 0.22,
        "marginal_bracket_threshold_cents": 100000,
        "marginal_rate_low": 0.25,
        "marginal_rate_high": 0.4,
        "loss_basis": "APPRAISED",
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["EMPLOYEE_NAME"],
        "job_level": DEFAULTS["JOB_LEVEL"],
        "home_ownership": DEFAULTS["HOME_OWNERSHIP"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["VENDOR_NAME"],
        "service_regions": ["IL", "CO"],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(employee_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "move_scope": DEFAULTS["MOVE_SCOPE"],
        "origin_city": DEFAULTS["ORIGIN_CITY"],
        "destination_city": DEFAULTS["DESTINATION_CITY"],
        "expected_move_date": DEFAULTS["EXPECTED_MOVE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(case_id, vendor_id) -> dict:
    return {"case_id": case_id, "vendor_id": vendor_id}


def create_booking_payload(case_id, kind="TRAVEL", **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "kind": kind,
        "start_date": DEFAULTS["TRAVEL_DATE"],
        "amount_cents": 30000,
    }
    if kind == "TEMP_HOUSING":
        defaults["end_date"] = "2026-08-18T00:00:00Z"
    defaults.update(overrides)
    return defaults


def create_claim_payload(case_id, amount_cents=10000, category="MEALS",
                         payment_method="REIMBURSEMENT", **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "category": category,
        "payment_method": payment_method,
        "lines": [{"description": "line 1", "amount_cents": amount_cents}],
    }
    defaults.update(overrides)
    return defaults


def create_home_sale_payload(case_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "appraised_value_cents": 50000000,
        "original_purchase_price_cents": 48000000,
        "list_price_cents": 52000000,
    }
    defaults.update(overrides)
    return defaults


def create_exception_request_payload(case_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "component": "MISC",
        "requested_cap_increase_cents": 100000,
        "justification": "business need",
    }
    defaults.update(overrides)
    return defaults
