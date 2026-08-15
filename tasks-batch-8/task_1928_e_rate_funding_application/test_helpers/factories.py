"""Payload factories — one per creatable resource, input fields only (PRD §3).

Conditional fields (student_count/square_feet, cep_identified_student_pct,
ineligible_price_cents, applicant_paid_cents, supersedes_substitution_id,
reason) are included only when supplied, so omission-vs-null stays faithful
to the caller's intent.
"""
from .constants import DATES, TEST_DEFAULTS


def create_funding_cycle_payload(**overrides) -> dict:
    defaults = {
        "label": DATES["CYCLE_LABEL"],
        "window_open_date": DATES["WINDOW_OPEN"],
        "window_close_date": DATES["WINDOW_CLOSE"],
        "service_delivery_deadline": DATES["SERVICE_DELIVERY_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_eligible_service_payload(**overrides) -> dict:
    defaults = {
        "funding_cycle_id": None,
        "service_description": "Dedicated Internet Access 1Gbps",
        "category": "CATEGORY_ONE",
        "service_type": "INTERNET_ACCESS",
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "name": "Unified School District 7",
        "entity_type": "SCHOOL",
        "urban_rural": "URBAN",
    }
    defaults.update(overrides)
    if defaults.get("entity_type") == "LIBRARY":
        defaults.setdefault("square_feet", TEST_DEFAULTS["LIBRARY_SQUARE_FEET"])
        defaults.pop("student_count", None)
    else:
        defaults.setdefault("student_count", TEST_DEFAULTS["STUDENT_COUNT"])
        defaults.pop("square_feet", None)
    return defaults


def create_nslp_snapshot_payload(**overrides) -> dict:
    defaults = {
        "applicant_id": None,
        "funding_cycle_id": None,
        "total_students": TEST_DEFAULTS["SNAPSHOT_TOTAL"],
        "free_lunch_eligible_students": TEST_DEFAULTS["SNAPSHOT_FREE"],
        "cep_participating": False,
    }
    defaults.update(overrides)
    if defaults.get("cep_identified_student_pct") is None:
        defaults.pop("cep_identified_student_pct", None)
    return defaults


def create_applicant_user_payload(**overrides) -> dict:
    defaults = {
        "applicant_id": None,
        "display_name": "Casey Coordinator",
        "function": "COORDINATOR",
    }
    defaults.update(overrides)
    return defaults


def create_service_provider_payload(**overrides) -> dict:
    defaults = {"name": "VendorOne", "spin": "SPIN-001"}
    defaults.update(overrides)
    return defaults


def create_procurement_posting_payload(**overrides) -> dict:
    defaults = {
        "applicant_id": None,
        "funding_cycle_id": None,
        "category": "CATEGORY_ONE",
        "description": "Internet access",
        "price_weight_pct": 100,
        "other_factor_weights": [],
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(**overrides) -> dict:
    defaults = {
        "posting_id": None,
        "eligible_price_cents": TEST_DEFAULTS["BID_PRICE_C1"],
        "factor_scores": [],
    }
    defaults.update(overrides)
    if defaults.get("ineligible_price_cents") is None:
        defaults.pop("ineligible_price_cents", None)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "applicant_id": None,
        "service_provider_id": None,
        "posting_id": None,
        "winning_bid_id": None,
        "category": "CATEGORY_ONE",
        "total_eligible_cents": TEST_DEFAULTS["BID_PRICE_C1"],
        "service_start_date": DATES["CONTRACT_START"],
        "service_end_date": DATES["CONTRACT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_funding_request_payload(**overrides) -> dict:
    defaults = {"applicant_id": None, "funding_cycle_id": None}
    defaults.update(overrides)
    return defaults


def create_funding_request_line_payload(**overrides) -> dict:
    defaults = {
        "funding_request_id": None,
        "contract_id": None,
        "eligible_service_id": None,
        "requested_pre_discount_cents": TEST_DEFAULTS["BID_PRICE_C1"],
    }
    defaults.update(overrides)
    return defaults


def create_invoice_submission_payload(**overrides) -> dict:
    defaults = {
        "frn_line_id": None,
        "method": "BEAR",
        "gross_invoiced_cents": 10000,
    }
    defaults.update(overrides)
    if defaults.get("applicant_paid_cents") is None:
        defaults.pop("applicant_paid_cents", None)
    return defaults


def create_service_substitution_payload(**overrides) -> dict:
    defaults = {
        "frn_line_id": None,
        "to_eligible_service_id": None,
        "expected_line_version": None,
    }
    defaults.update(overrides)
    for optional in ("supersedes_substitution_id", "reason"):
        if defaults.get(optional) is None:
            defaults.pop(optional, None)
    return defaults


def create_appeal_payload(**overrides) -> dict:
    defaults = {"funding_request_id": None, "grounds": "Appeal grounds"}
    defaults.update(overrides)
    return defaults
