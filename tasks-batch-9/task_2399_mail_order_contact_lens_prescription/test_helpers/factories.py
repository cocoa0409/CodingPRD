"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PLAN_NAME": "VisionOne",
    "PRODUCT_BRAND": "AcuityFlex",
    "PRODUCT_NAME": "Daily 30",
    "PRESCRIBER_NAME": "Dr. Mira Okonjo",
    "CUSTOMER_NAME": "Ada Lin",
    "CUSTOMER_EMAIL": "ada.lin@example.com",
    "STATE_CODE": "UT",
    "DOCUMENT_REFERENCE": "scan-1",
    "ISSUE_DATE": "2026-07-01",
    "EXPIRY_DATE": "2027-07-01",
}


def create_insurance_plan_payload(**overrides) -> dict:
    """Out-of-network plan with a 15000-cent annual allowance."""
    payload = {
        "name": DEFAULTS["PLAN_NAME"],
        "network_status": "OUT_OF_NETWORK",
        "annual_allowance_cents": 15000,
        "coinsurance_rate": 0.20,
        "requires_itemized_receipt": False,
        "covers_shipping": False,
        "claim_window_days": 90,
        "plan_year_start_month_day": "01-01",
    }
    payload.update(overrides)
    return payload


def create_product_payload(**overrides) -> dict:
    """A 3200-cent daily-disposable box of 30 lenses at base curve 8.60 /
    diameter 14.20."""
    payload = {
        "brand": DEFAULTS["PRODUCT_BRAND"],
        "name": DEFAULTS["PRODUCT_NAME"],
        "wear_schedule": "DAILY_DISPOSABLE",
        "lenses_per_box": 30,
        "unit_price_cents": 3200,
        "base_curve": 8.60,
        "diameter": 14.20,
        "sphere_min": -8.00,
        "sphere_max": 4.00,
        "sphere_step": 0.25,
        "material_family": "silicone_hydrogel",
    }
    payload.update(overrides)
    return payload


def create_lens_equivalence_payload(to_product_id, **overrides) -> dict:
    payload = {
        "to_product_id": to_product_id,
        "equivalence_class": "CLINICAL",
    }
    payload.update(overrides)
    return payload


def create_prescriber_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["PRESCRIBER_NAME"],
        "license_number": "UT-40921",
        "license_state": "UT",
        "contact_channel": "PORTAL",
        "directory_verified": True,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["CUSTOMER_NAME"],
        "email": DEFAULTS["CUSTOMER_EMAIL"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_prescription_payload(customer_id, product_id, **overrides) -> dict:
    """UPLOAD capture with a document reference, valid 2026-07-01 to
    2027-07-01, authorising 24 boxes."""
    payload = {
        "customer_id": customer_id,
        "product_id": product_id,
        "capture_mode": "UPLOAD",
        "document_reference": DEFAULTS["DOCUMENT_REFERENCE"],
        "issue_date": DEFAULTS["ISSUE_DATE"],
        "expiry_date": DEFAULTS["EXPIRY_DATE"],
        "od_sphere": -2.25,
        "os_sphere": -4.00,
        "base_curve": 8.60,
        "diameter": 14.20,
        "boxes_authorized_total": 24,
    }
    payload.update(overrides)
    return payload


def create_doctor_lookup_prescription_payload(
    customer_id, product_id, prescriber_id, **overrides
) -> dict:
    """DOCTOR_LOOKUP capture, which enters passive verification on submit."""
    payload = create_prescription_payload(customer_id, product_id)
    payload.pop("document_reference", None)
    payload["capture_mode"] = "DOCTOR_LOOKUP"
    payload["prescriber_id"] = prescriber_id
    payload.update(overrides)
    return payload


def create_self_report_prescription_payload(
    customer_id, product_id, **overrides
) -> dict:
    """SELF_REPORT capture, which also enters passive verification on submit."""
    payload = create_prescription_payload(customer_id, product_id)
    payload.pop("document_reference", None)
    payload["capture_mode"] = "SELF_REPORT"
    payload["self_reported_prescriber_name"] = DEFAULTS["PRESCRIBER_NAME"]
    payload.update(overrides)
    return payload


def create_order_payload(
    customer_id, prescription_id, ordered_product_id, boxes_od=1, boxes_os=1, **overrides
) -> dict:
    payload = {
        "customer_id": customer_id,
        "prescription_id": prescription_id,
        "ordered_product_id": ordered_product_id,
        "boxes_od": boxes_od,
        "boxes_os": boxes_os,
    }
    payload.update(overrides)
    return payload


def create_reorder_hold_payload(customer_id, prescription_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "prescription_id": prescription_id,
        "reason": "MANUAL",
    }
    payload.update(overrides)
    return payload


def create_auto_reorder_schedule_payload(
    customer_id, prescription_id, product_id, **overrides
) -> dict:
    payload = {
        "customer_id": customer_id,
        "prescription_id": prescription_id,
        "product_id": product_id,
        "boxes_per_run": 2,
        "anchor_date": "2026-09-08",
    }
    payload.update(overrides)
    return payload


def create_return_request_payload(order_id, customer_id, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "customer_id": customer_id,
        "reason": "PRESCRIPTION_CHANGE",
        "unopened_boxes": 1,
    }
    payload.update(overrides)
    return payload


def create_reimbursement_claim_payload(
    order_id, customer_id, insurance_plan_id, **overrides
) -> dict:
    payload = {
        "order_id": order_id,
        "customer_id": customer_id,
        "insurance_plan_id": insurance_plan_id,
    }
    payload.update(overrides)
    return payload


def file_prescriber_dispute_payload(
    prescription_id, prescriber_id, expected_prescription_version, **overrides
) -> dict:
    payload = {
        "prescription_id": prescription_id,
        "prescriber_id": prescriber_id,
        "dispute_reason": "NOT_MY_PATIENT",
        "expected_prescription_version": expected_prescription_version,
    }
    payload.update(overrides)
    return payload


def apply_substitution_payload(
    substitute_product_id, expected_order_version, **overrides
) -> dict:
    payload = {
        "substitute_product_id": substitute_product_id,
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload
