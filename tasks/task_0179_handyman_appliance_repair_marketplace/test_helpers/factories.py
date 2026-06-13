"""Payload factories — one per entity, input fields only.

Each factory provides PRD-coherent defaults for the required input fields and accepts
**overrides for the values a given test needs to control. Optional fields (those the PRD
declares with a default) are omitted unless explicitly supplied as an override.
"""


def create_service_category_payload(**overrides) -> dict:
    """Required: code, name, pricing_model. Optional (PRD defaults): requires_license,
    flat_task_fee_cents, hourly_rate_cents, instant_quote_eligible, instant_quote_flat_cents,
    callback_warranty_days, skill_tags.

    The pricing field must be coherent with pricing_model: a FLAT category carries
    flat_task_fee_cents and leaves hourly_rate_cents null, and vice versa. So the rate default
    is chosen to match the requested pricing_model and is NOT injected for the other model
    (which would trip the §3.1 coherence check). Any explicit override still wins.
    """
    defaults = {
        "code": "TEST_CAT",
        "name": "Test Category",
        "pricing_model": "HOURLY",
    }
    pricing_model = overrides.get("pricing_model", defaults["pricing_model"])
    if pricing_model == "FLAT":
        defaults["flat_task_fee_cents"] = 12000
    else:  # HOURLY
        defaults["hourly_rate_cents"] = 9000
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    """Required: email, full_name, zip_code."""
    defaults = {
        "email": "customer@example.com",
        "full_name": "Test Customer",
        "zip_code": "30301",
    }
    defaults.update(overrides)
    return defaults


def create_pro_payload(**overrides) -> dict:
    """Required: email, full_name, home_zip_code. Optional: skill_tags, truck_stock_markup_pct."""
    defaults = {
        "email": "pro@example.com",
        "full_name": "Test Pro",
        "home_zip_code": "30301",
    }
    defaults.update(overrides)
    return defaults


def create_background_check_payload(**overrides) -> dict:
    """Required: check_type. Optional: license_expires_on (LICENSE only)."""
    defaults = {
        "check_type": "CRIMINAL",
    }
    defaults.update(overrides)
    return defaults


def decide_background_check_payload(**overrides) -> dict:
    """Required: decision. Optional: expected_pro_version."""
    defaults = {
        "decision": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_job_payload(customer_id, category_id, **overrides) -> dict:
    """Required: customer_id, category_id, address_zip_code."""
    defaults = {
        "customer_id": customer_id,
        "category_id": category_id,
        "address_zip_code": "30301",
    }
    defaults.update(overrides)
    return defaults


def submit_quote_payload(**overrides) -> dict:
    """Optional: estimated_labor_hours (required for HOURLY, null for FLAT)."""
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def accept_quote_payload(quote_id, **overrides) -> dict:
    """Required: quote_id."""
    defaults = {"quote_id": quote_id}
    defaults.update(overrides)
    return defaults


def create_dispatch_window_payload(pro_id, window_start, window_end, service_zip_code="30301", **overrides) -> dict:
    """Required: pro_id, window_start, window_end, service_zip_code."""
    defaults = {
        "pro_id": pro_id,
        "window_start": window_start,
        "window_end": window_end,
        "service_zip_code": service_zip_code,
    }
    defaults.update(overrides)
    return defaults


def book_window_payload(job_id, expected_dispatchwindow_version, **overrides) -> dict:
    """Required: job_id, expected_dispatchwindow_version."""
    defaults = {
        "job_id": job_id,
        "expected_dispatchwindow_version": expected_dispatchwindow_version,
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(dispatch_window_id, arrived_at, **overrides) -> dict:
    """Required: dispatch_window_id, arrived_at."""
    defaults = {
        "dispatch_window_id": dispatch_window_id,
        "arrived_at": arrived_at,
    }
    defaults.update(overrides)
    return defaults


def create_labor_line_payload(hours_worked, **overrides) -> dict:
    """Required: hours_worked."""
    defaults = {"hours_worked": hours_worked}
    defaults.update(overrides)
    return defaults


def create_part_line_payload(description, unit_cost_cents, quantity, **overrides) -> dict:
    """Required: description, unit_cost_cents, quantity. Optional: from_truck_stock (default false)."""
    defaults = {
        "description": description,
        "unit_cost_cents": unit_cost_cents,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def pay_invoice_payload(amount_cents, **overrides) -> dict:
    """Required: amount_cents."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(job_id, invoice_id, reason, requested_refund_cents, **overrides) -> dict:
    """Required: job_id, invoice_id, reason, requested_refund_cents. Optional: refund_destination."""
    defaults = {
        "job_id": job_id,
        "invoice_id": invoice_id,
        "reason": reason,
        "requested_refund_cents": requested_refund_cents,
    }
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(decision, **overrides) -> dict:
    """Required: decision. Optional: approved_refund_cents (required for APPROVE)."""
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601, **overrides) -> dict:
    """Required: to_iso8601."""
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
