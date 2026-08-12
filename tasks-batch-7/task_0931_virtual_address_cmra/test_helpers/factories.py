"""Payload factories — one per resource, input fields only."""

from .constants import TEST_DEFAULTS


def plan_tier_payload(**overrides) -> dict:
    payload = {
        "tier_code": TEST_DEFAULTS["PLAN_TIER_CODE"],
        "name": TEST_DEFAULTS["PLAN_NAME"],
        "rank": TEST_DEFAULTS["PLAN_RANK"],
        "monthly_fee_cents": TEST_DEFAULTS["PLAN_MONTHLY_FEE_CENTS"],
        "included_recipients": TEST_DEFAULTS["PLAN_INCLUDED_RECIPIENTS"],
        "included_scan_pages": TEST_DEFAULTS["PLAN_INCLUDED_SCAN_PAGES"],
        "included_forwards": TEST_DEFAULTS["PLAN_INCLUDED_FORWARDS"],
        "included_storage_days": TEST_DEFAULTS["PLAN_INCLUDED_STORAGE_DAYS"],
        "overage_scan_page_cents": TEST_DEFAULTS["PLAN_OVERAGE_SCAN_PAGE_CENTS"],
        "overage_forward_cents": TEST_DEFAULTS["PLAN_OVERAGE_FORWARD_CENTS"],
        "overage_storage_day_cents": TEST_DEFAULTS["PLAN_OVERAGE_STORAGE_DAY_CENTS"],
        "overage_recipient_cents": TEST_DEFAULTS["PLAN_OVERAGE_RECIPIENT_CENTS"],
        "allows_overage": True,
    }
    payload.update(overrides)
    return payload


def carrier_rule_payload(**overrides) -> dict:
    payload = {
        "carrier_code": TEST_DEFAULTS["CARRIER_CODE"],
        "dim_divisor": TEST_DEFAULTS["CARRIER_DIM_DIVISOR"],
        "max_length_plus_girth_in": TEST_DEFAULTS["CARRIER_MAX_LENGTH_PLUS_GIRTH_IN"],
        "max_actual_weight_lb": TEST_DEFAULTS["CARRIER_MAX_ACTUAL_WEIGHT_LB"],
        "accepts_signature_required": True,
        "acceptance_fee_cents": TEST_DEFAULTS["CARRIER_ACCEPTANCE_FEE_CENTS"],
        "base_rate_cents_per_lb": TEST_DEFAULTS["CARRIER_BASE_RATE_CENTS_PER_LB"],
    }
    payload.update(overrides)
    return payload


def box_payload(box_number: str, plan_tier_id: str, **overrides) -> dict:
    payload = {
        "box_number": box_number,
        "plan_tier_id": plan_tier_id,
        "holder_name": "Test Holder",
        "holder_email": "holder@example.com",
        "security_deposit_cents": 0,
        "extra_recipient_slots": 0,
        "prepaid_balance_cents": 0,
    }
    payload.update(overrides)
    return payload


def recipient_payload(legal_name: str, **overrides) -> dict:
    payload = {
        "legal_name": legal_name,
        "recipient_kind": "INDIVIDUAL",
        "signature_authorization_on_file": False,
    }
    payload.update(overrides)
    return payload


def id_document_payload(doc_class: str, doc_type: str, expires_on: str) -> dict:
    return {"doc_class": doc_class, "doc_type": doc_type, "expires_on": expires_on}


def form_1583_payload(home_address_line: str = None) -> dict:
    return {
        "home_address_line": home_address_line or TEST_DEFAULTS["HOME_ADDRESS_LINE"]
    }


def letter_payload(addressee_name: str, **overrides) -> dict:
    """A LETTER carries no carrier_rule_id (PRD §3.4 forbids it for LETTER/FLAT)."""
    payload = {
        "addressee_name": addressee_name,
        "item_class": "LETTER",
        "signature_required": False,
        "actual_weight_lb": 0.1,
        "length_in": 9.0,
        "width_in": 4.0,
        "height_in": 0.2,
        "interior_scan_consent": False,
    }
    payload.update(overrides)
    return payload


def flat_payload(addressee_name: str, **overrides) -> dict:
    payload = {
        "addressee_name": addressee_name,
        "item_class": "FLAT",
        "signature_required": False,
        "actual_weight_lb": 3.0,
        "length_in": 12.0,
        "width_in": 9.0,
        "height_in": 1.0,
        "interior_scan_consent": False,
    }
    payload.update(overrides)
    return payload


def package_payload(addressee_name: str, carrier_rule_id: str, **overrides) -> dict:
    payload = {
        "addressee_name": addressee_name,
        "item_class": "PACKAGE",
        "carrier_rule_id": carrier_rule_id,
        "signature_required": False,
        "actual_weight_lb": 5.0,
        "length_in": 10.0,
        "width_in": 8.0,
        "height_in": 6.0,
        "interior_scan_consent": False,
    }
    payload.update(overrides)
    return payload


def sop_payload(addressee_name: str, carrier_rule_id: str, **overrides) -> dict:
    payload = {
        "addressee_name": addressee_name,
        "item_class": "SOP",
        "carrier_rule_id": carrier_rule_id,
        "signature_required": False,
        "actual_weight_lb": 5.0,
        "length_in": 10.0,
        "width_in": 8.0,
        "height_in": 6.0,
        "interior_scan_consent": False,
    }
    payload.update(overrides)
    return payload


def scan_job_payload(scan_tier: str, requested_pages: int) -> dict:
    return {"scan_tier": scan_tier, "requested_pages": requested_pages}


def disposition_payload(disposition_type: str, expected_mail_item_version: int) -> dict:
    return {
        "disposition_type": disposition_type,
        "expected_mail_item_version": expected_mail_item_version,
    }


def forward_shipment_payload(
    service_level: str,
    destination_address: str,
    mail_item_ids: list,
    expected_box_version: int,
) -> dict:
    return {
        "service_level": service_level,
        "destination_address": destination_address,
        "mail_item_ids": mail_item_ids,
        "expected_box_version": expected_box_version,
    }


def check_payload(
    mail_item_id: str,
    payee_name_on_check: str,
    amount_cents: int,
    expected_deposit_batch_version: int,
    endorsed: bool = True,
) -> dict:
    return {
        "mail_item_id": mail_item_id,
        "payee_name_on_check": payee_name_on_check,
        "amount_cents": amount_cents,
        "endorsed": endorsed,
        "expected_deposit_batch_version": expected_deposit_batch_version,
    }


def registered_agent_payload(jurisdiction_code: str, retention_days: int = None) -> dict:
    payload = {"jurisdiction_code": jurisdiction_code}
    if retention_days is not None:
        payload["retention_days"] = retention_days
    return payload


def plan_change_payload(new_plan_tier_id: str, expected_box_version: int) -> dict:
    return {
        "new_plan_tier_id": new_plan_tier_id,
        "expected_box_version": expected_box_version,
    }
