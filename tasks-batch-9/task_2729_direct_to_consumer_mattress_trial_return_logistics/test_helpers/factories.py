"""Payload factories — one per write endpoint, carrying input fields only.

Every monetary amount is an integer count of cents (PRD §2.6), so no factory
ever emits a float for a ``_cents`` field.
"""

import uuid

from .constants import TEST_DEFAULTS


def _suffix() -> str:
    return uuid.uuid4().hex[:8].upper()


# --- logical clock (PRD §2.5) ---------------------------------------------


def clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# --- catalogue (PRD §3.1) -------------------------------------------------


def mattress_model_payload(**overrides) -> dict:
    defaults = {
        "sku": f"MDL-{_suffix()}",
        "name": "Comfort Queen Medium",
        "firmness": "MEDIUM",
        "size": "QUEEN",
        "list_price_cents": TEST_DEFAULTS["QUEEN_LIST_PRICE_CENTS"],
        "break_in_nights": 21,
        "trial_nights": 100,
    }
    defaults.update(overrides)
    return defaults


def promotion_bundle_payload(**overrides) -> dict:
    defaults = {
        "code": f"BND-{_suffix()}",
        "unwind_policy": "DEDUCT_RETAIL",
    }
    defaults.update(overrides)
    return defaults


def retail_partner_payload(**overrides) -> dict:
    defaults = {
        "name": f"Sleep Gallery {_suffix()[:4]}",
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "commission_bps": 800,
        "price_match_policy": "MATCH_TO_LOWEST",
    }
    defaults.update(overrides)
    return defaults


def disposition_partner_payload(**overrides) -> dict:
    defaults = {
        "name": f"Second Sleep {_suffix()[:4]}",
        "partner_type": "CHARITY",
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "daily_intake_capacity_units": TEST_DEFAULTS["PARTNER_DAILY_CAPACITY_UNITS"],
        "accepts_condition_grades": ["A", "B"],
        "soil_policy": "REJECT_SOILED",
        "priority_rank": 1,
    }
    defaults.update(overrides)
    return defaults


# --- customers and fraud (PRD §3.2) ---------------------------------------


def customer_payload(**overrides) -> dict:
    tag = _suffix()
    defaults = {
        "email": f"sleeper-{tag.lower()}@example.com",
        "full_name": f"Test Sleeper {tag[:4]}",
        "household_hash": f"HH-{tag}",
    }
    defaults.update(overrides)
    return defaults


def trial_abuse_signal_payload(customer_id: str, signal_type: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "signal_type": signal_type}
    defaults.update(overrides)
    return defaults


# --- trial orders (PRD §3.3) ----------------------------------------------


def trial_order_payload(customer_id: str, model_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "model_id": model_id,
        "channel": "DTC",
        "gross_price_cents": TEST_DEFAULTS["QUEEN_LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


# --- quality claims (PRD §3.4) --------------------------------------------


def quality_claim_payload(order_id: str, claim_type: str, photo_evidence_count: int,
                          **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "claim_type": claim_type,
        "photo_evidence_count": photo_evidence_count,
    }
    defaults.update(overrides)
    return defaults


def submit_evidence_payload(photo_evidence_count: int, **overrides) -> dict:
    defaults = {"photo_evidence_count": photo_evidence_count}
    defaults.update(overrides)
    return defaults


def adjudicate_payload(resolution: str, **overrides) -> dict:
    defaults = {"resolution": resolution}
    defaults.update(overrides)
    return defaults


# --- comfort exchanges (PRD §3.5) -----------------------------------------


def comfort_exchange_payload(original_order_id: str, target_model_id: str,
                             **overrides) -> dict:
    defaults = {
        "original_order_id": original_order_id,
        "target_model_id": target_model_id,
    }
    defaults.update(overrides)
    return defaults


def approve_exchange_payload(expected_trial_order_version, **overrides) -> dict:
    defaults = {"expected_trial_order_version": expected_trial_order_version}
    defaults.update(overrides)
    return defaults


def decline_exchange_payload(decline_note: str = "the requested firmness is out of stock",
                             **overrides) -> dict:
    defaults = {"decline_note": decline_note}
    defaults.update(overrides)
    return defaults


# --- return cases (PRD §3.6, §3.8) ----------------------------------------


def return_case_payload(order_id: str, reason_code: str = "COMFORT", **overrides) -> dict:
    defaults = {"order_id": order_id, "reason_code": reason_code}
    defaults.update(overrides)
    return defaults


def inspect_payload(condition_grade: str = "A", soil_flag: bool = False,
                    accessory_returned: bool = False, **overrides) -> dict:
    defaults = {
        "condition_grade": condition_grade,
        "soil_flag": soil_flag,
        "accessory_returned": accessory_returned,
    }
    defaults.update(overrides)
    return defaults


def disposition_payload(disposition: str = "DONATION",
                        intake_date: str = TEST_DEFAULTS["INTAKE_DATE"],
                        **overrides) -> dict:
    defaults = {"disposition": disposition, "intake_date": intake_date}
    defaults.update(overrides)
    return defaults


# --- pickup routing (PRD §3.7) --------------------------------------------


def pickup_route_payload(**overrides) -> dict:
    defaults = {
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "route_date": TEST_DEFAULTS["ROUTE_DATE"],
        "window_start_at": TEST_DEFAULTS["ROUTE_WINDOW_START_AT"],
        "window_end_at": TEST_DEFAULTS["ROUTE_WINDOW_END_AT"],
        "capacity_units": TEST_DEFAULTS["ROUTE_CAPACITY_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def pickup_appointment_payload(route_id: str, return_case_id: str,
                               expected_pickup_route_version, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "return_case_id": return_case_id,
        "slot_start_at": TEST_DEFAULTS["SLOT_START_AT"],
        "slot_end_at": TEST_DEFAULTS["SLOT_END_AT"],
        "expected_pickup_route_version": expected_pickup_route_version,
    }
    defaults.update(overrides)
    return defaults


def complete_appointment_payload(outcome: str = "COMPLETED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def confirm_intake_payload(outcome: str = "DELIVERED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


# --- refunds (PRD §3.9) ---------------------------------------------------


def refund_authorization_payload(return_case_id: str, expected_return_case_version,
                                 **overrides) -> dict:
    defaults = {
        "return_case_id": return_case_id,
        "expected_return_case_version": expected_return_case_version,
    }
    defaults.update(overrides)
    return defaults


def void_refund_payload(void_reason: str = "the customer disputed the proration",
                        **overrides) -> dict:
    defaults = {"void_reason": void_reason}
    defaults.update(overrides)
    return defaults


# --- attribution (PRD §3.10) ---------------------------------------------


def attribution_claim_payload(partner_id: str, order_id: str, claim_type: str,
                              evidence_url_count: int = 2, **overrides) -> dict:
    defaults = {
        "partner_id": partner_id,
        "order_id": order_id,
        "claim_type": claim_type,
        "evidence_url_count": evidence_url_count,
    }
    defaults.update(overrides)
    return defaults


def review_attribution_payload(action: str = "ACCEPT_FOR_REVIEW", **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults


def resubmit_attribution_payload(evidence_url_count: int, **overrides) -> dict:
    defaults = {"evidence_url_count": evidence_url_count}
    defaults.update(overrides)
    return defaults


def resolve_attribution_payload(decision: str = "APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults
