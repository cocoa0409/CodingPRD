"""Payload factories for the AMC API — one per writable entity, input fields only.

Each factory returns a dict carrying only client-supplied (input) fields with
sensible defaults; pass keyword overrides to control specific values. Computed
and system fields (id, status, version, sla_hours, fee shares, etc.) are minted
by the server and never appear here.
"""
from .constants import TEST_DEFAULTS


def create_lender_payload(**overrides) -> dict:
    """POST /amc/lenders — name, approved_panel_appraiser_ids (optional), monthly_fee_budget_cents."""
    payload = {
        "name": "Test Lender",
        "approved_panel_appraiser_ids": [],
        "monthly_fee_budget_cents": TEST_DEFAULTS["LENDER_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def set_lender_panel_payload(appraiser_ids, **overrides) -> dict:
    """PATCH /amc/lenders/{id}/panel — approved_panel_appraiser_ids."""
    payload = {"approved_panel_appraiser_ids": appraiser_ids}
    payload.update(overrides)
    return payload


def create_appraiser_payload(**overrides) -> dict:
    """POST /amc/appraisers — full_name, license_state, base_fee_share_pct."""
    payload = {
        "full_name": "Test Appraiser",
        "license_state": "CA",
        "base_fee_share_pct": TEST_DEFAULTS["BASE_FEE_SHARE_PCT"],
    }
    payload.update(overrides)
    return payload


def set_appraiser_status_payload(status, **overrides) -> dict:
    """POST /amc/appraisers/{id}/status — status."""
    payload = {"status": status}
    payload.update(overrides)
    return payload


def create_property_payload(**overrides) -> dict:
    """POST /amc/properties — street_address, state_code, prior_appraised_value_cents (optional)."""
    payload = {
        "street_address": "1 Test St",
        "state_code": "CA",
    }
    payload.update(overrides)
    return payload


def create_order_payload(lender_id, property_id, **overrides) -> dict:
    """POST /amc/orders — lender_id, property_id, order_fee_cents, product_type, rush (optional)."""
    payload = {
        "lender_id": lender_id,
        "property_id": property_id,
        "order_fee_cents": TEST_DEFAULTS["ORDER_FEE_CENTS"],
        "product_type": "URAR_1004",
    }
    payload.update(overrides)
    return payload


def assignment_create_payload(expected_order_version, **overrides) -> dict:
    """POST /amc/orders/{id}/assignments — expected_order_version (OCC, PRD §2.8)."""
    payload = {"expected_order_version": expected_order_version}
    payload.update(overrides)
    return payload


def accept_assignment_payload(inspection_start, inspection_end, **overrides) -> dict:
    """POST /amc/assignments/{id}/accept — inspection_start, inspection_end."""
    payload = {
        "inspection_start": inspection_start,
        "inspection_end": inspection_end,
    }
    payload.update(overrides)
    return payload


def submit_report_payload(**overrides) -> dict:
    """POST /amc/assignments/{id}/reports — opinion_of_value_cents, uad_condition_rating,
    uad_quality_rating, comparable_count."""
    payload = {
        "opinion_of_value_cents": TEST_DEFAULTS["OPINION_OF_VALUE_CENTS"],
        "uad_condition_rating": "C3",
        "uad_quality_rating": "Q4",
        "comparable_count": 5,
    }
    payload.update(overrides)
    return payload


def finalize_review_payload(finding_codes=None, **overrides) -> dict:
    """POST /amc/compliance-reviews/{id}/finalize — finding_codes (optional)."""
    payload = {}
    if finding_codes is not None:
        payload["finding_codes"] = finding_codes
    payload.update(overrides)
    return payload


def revision_request_payload(reason_category, **overrides) -> dict:
    """POST /amc/reports/{id}/revision-requests — reason_category."""
    payload = {"reason_category": reason_category}
    payload.update(overrides)
    return payload


def reconsideration_payload(requested_value_cents, **overrides) -> dict:
    """POST /amc/orders/{id}/reconsiderations — requested_value_cents."""
    payload = {"requested_value_cents": requested_value_cents}
    payload.update(overrides)
    return payload


def resolve_reconsideration_payload(new_value_cents=None, **overrides) -> dict:
    """POST /amc/reconsiderations/{id}/resolve — new_value_cents (optional; present = VALUE_CHANGED)."""
    payload = {}
    if new_value_cents is not None:
        payload["new_value_cents"] = new_value_cents
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601, **overrides) -> dict:
    """POST /amc/_clock/set_current_utc — to_iso8601."""
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
