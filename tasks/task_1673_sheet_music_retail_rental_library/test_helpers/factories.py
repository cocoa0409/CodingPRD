"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "PUBLISHER_NAME": "Test Publisher",
    "WORK_TITLE": "Test Work",
    "CATALOG_NUMBER": "CAT-001",
    "ENSEMBLE_TIER": "CHAMBER",
    "BASE_RENTAL_RATE_CENTS": 10000,
    "SALE_PRICE_CENTS": 2000,
    "LICENSE_FORMAT": "PRINT_ONLY",
    "SET_CODE": "SET-001",
    "COPY_COUNT": 30,
    "REPLACEMENT_VALUE_CENTS": 240000,
    "ACCOUNT_NAME": "Test School",
    "ACCOUNT_KIND": "SCHOOL",
    "CREDIT_TIER": "STANDARD",
    "CREDIT_LIMIT_CENTS": 0,
    "PO_NUMBER": "PO-0001",
    "PO_AUTHORIZED_CENTS": 500000,
    "PO_VALID_FROM": "2026-08-01",
    "PO_VALID_UNTIL": "2027-06-30",
    "COPIES_REQUESTED": 1,
    "CHECKOUT_DATE": "2026-08-05",
    "DUE_DATE": "2026-09-04",
    "VENUE_KIND": "EDUCATIONAL",
    "QUESTION": "May we perform this work at our concert?",
}


def create_publisher_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["PUBLISHER_NAME"]}
    defaults.update(overrides)
    return defaults


def create_work_payload(publisher_id, **overrides) -> dict:
    defaults = {
        "publisher_id": publisher_id,
        "title": DEFAULTS["WORK_TITLE"],
        "catalog_number": DEFAULTS["CATALOG_NUMBER"],
        "ensemble_tier": DEFAULTS["ENSEMBLE_TIER"],
        "base_rental_rate_cents": DEFAULTS["BASE_RENTAL_RATE_CENTS"],
        "sale_price_cents": DEFAULTS["SALE_PRICE_CENTS"],
        "license_format": DEFAULTS["LICENSE_FORMAT"],
    }
    defaults.update(overrides)
    return defaults


def create_rental_set_payload(work_id, **overrides) -> dict:
    defaults = {
        "work_id": work_id,
        "set_code": DEFAULTS["SET_CODE"],
        "copy_count": DEFAULTS["COPY_COUNT"],
        "replacement_value_cents": DEFAULTS["REPLACEMENT_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_account_payload(**overrides) -> dict:
    defaults = {
        "account_name": DEFAULTS["ACCOUNT_NAME"],
        "account_kind": DEFAULTS["ACCOUNT_KIND"],
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "po_number": DEFAULTS["PO_NUMBER"],
        "authorized_amount_cents": DEFAULTS["PO_AUTHORIZED_CENTS"],
        "valid_from": DEFAULTS["PO_VALID_FROM"],
        "valid_until": DEFAULTS["PO_VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_rental_order_payload(account_id, rental_set_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "rental_set_id": rental_set_id,
        "copies_requested": DEFAULTS["COPIES_REQUESTED"],
        "checkout_date": DEFAULTS["CHECKOUT_DATE"],
        "due_date": DEFAULTS["DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_perusal_request_payload(account_id, work_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "work_id": work_id,
        "format": "PHYSICAL",
    }
    defaults.update(overrides)
    return defaults


def create_sale_record_payload(account_id, work_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "work_id": work_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_condition_report_payload(rental_line_id, **overrides) -> dict:
    defaults = {
        "rental_line_id": rental_line_id,
        "observed_grade": "B",
    }
    defaults.update(overrides)
    return defaults


def create_damage_invoice_payload(rental_line_id, condition_report_id, **overrides) -> dict:
    defaults = {
        "rental_line_id": rental_line_id,
        "condition_report_id": condition_report_id,
    }
    defaults.update(overrides)
    return defaults


def create_rights_case_payload(account_id, work_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "work_id": work_id,
        "venue_kind": DEFAULTS["VENUE_KIND"],
        "question": DEFAULTS["QUESTION"],
    }
    defaults.update(overrides)
    return defaults
