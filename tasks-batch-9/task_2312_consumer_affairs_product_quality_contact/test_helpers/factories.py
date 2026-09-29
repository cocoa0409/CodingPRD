"""Payload builders.

Each builder returns a minimally valid body for its endpoint and lets the caller
override or drop any field via ``**overrides``.  Passing ``field=None`` for an
optional field removes it from the payload entirely, which is how a test omits a
field rather than sending an explicit null.
"""

from typing import Any, Dict

from .constants import (
    CANONICAL_BATCH_CODE,
    CANONICAL_CODE_DATE,
    CANONICAL_NORMALIZED_BATCH_CODE,
    CANONICAL_UNITS_PRODUCED,
    CLOCK_EPOCH,
    STAFF_ROLE_CARE_AGENT,
)

_OMIT = object()


def _build(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


OMIT = _OMIT


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
def staff_user_payload(
    staff_code: str = "AG1",
    full_name: str = "Ada Grant",
    role: str = STAFF_ROLE_CARE_AGENT,
    **overrides,
) -> dict:
    return _build(
        {"staff_code": staff_code, "full_name": full_name, "role": role}, overrides
    )


def consumer_payload(
    external_ref: str = "C-1", full_name: str = "Rin Sato", **overrides
) -> dict:
    return _build({"external_ref": external_ref, "full_name": full_name}, overrides)


def plant_payload(
    plant_code: str = "P-CHI", name: str = "Chicago Bakery", region: str = "MW", **overrides
) -> dict:
    return _build(
        {"plant_code": plant_code, "name": name, "region": region}, overrides
    )


def production_line_payload(
    plant_id: str,
    line_code: str = "L-01",
    nominal_units_per_hour: int = 12000,
    **overrides,
) -> dict:
    return _build(
        {
            "plant_id": plant_id,
            "line_code": line_code,
            "nominal_units_per_hour": nominal_units_per_hour,
        },
        overrides,
    )


def product_payload(
    sku: str = "SKU-CRACKER",
    name: str = "Sea Salt Crackers",
    category: str = "SNACK",
    unit_retail_price_cents: int = 2500,
    units_per_case: int = 12,
    is_regulated_food: bool = True,
    **overrides,
) -> dict:
    return _build(
        {
            "sku": sku,
            "name": name,
            "category": category,
            "unit_retail_price_cents": unit_retail_price_cents,
            "units_per_case": units_per_case,
            "is_regulated_food": is_regulated_food,
        },
        overrides,
    )


def production_lot_payload(
    product_id: str,
    production_line_id: str,
    batch_code: str = CANONICAL_BATCH_CODE,
    code_date: str = CANONICAL_CODE_DATE,
    units_produced: int = CANONICAL_UNITS_PRODUCED,
    **overrides,
) -> dict:
    return _build(
        {
            "product_id": product_id,
            "production_line_id": production_line_id,
            "batch_code": batch_code,
            "code_date": code_date,
            "units_produced": units_produced,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------
def contact_payload(
    consumer_id: str,
    channel: str = "PHONE",
    received_at: str = CLOCK_EPOCH,
    raw_message: str = "Found something in the pack.",
    **overrides,
) -> dict:
    return _build(
        {
            "consumer_id": consumer_id,
            "channel": channel,
            "received_at": received_at,
            "raw_message": raw_message,
        },
        overrides,
    )


def complaint_payload(
    contact_id: str,
    complaint_type: str = "QUALITY",
    reported_batch_code: str = CANONICAL_NORMALIZED_BATCH_CODE,
    **overrides,
) -> dict:
    return _build(
        {
            "contact_id": contact_id,
            "complaint_type": complaint_type,
            "reported_batch_code": reported_batch_code,
        },
        overrides,
    )


def identify_product_payload(reported_batch_code: str, **overrides) -> dict:
    return _build({"reported_batch_code": reported_batch_code}, overrides)


def triage_payload(reviewer_note: str = "Reviewed.", **overrides) -> dict:
    return _build({"reviewer_note": reviewer_note}, overrides)


def respond_payload(response_template_id: str, **overrides) -> dict:
    return _build({"response_template_id": response_template_id}, overrides)


def mark_duplicate_payload(duplicate_of_complaint_id: str, **overrides) -> dict:
    return _build({"duplicate_of_complaint_id": duplicate_of_complaint_id}, overrides)


# ---------------------------------------------------------------------------
# Sample kits
# ---------------------------------------------------------------------------
def sample_kit_payload(
    complaint_id: str,
    kit_code: str = "K-001",
    seal_id_issued: str = "SEAL-001",
    **overrides,
) -> dict:
    return _build(
        {
            "complaint_id": complaint_id,
            "kit_code": kit_code,
            "seal_id_issued": seal_id_issued,
        },
        overrides,
    )


def custody_event_payload(
    event_type: str,
    occurred_at: str,
    expected_sample_kit_version: int,
    actor_label: str = "Chain custodian",
    **overrides,
) -> dict:
    return _build(
        {
            "event_type": event_type,
            "occurred_at": occurred_at,
            "actor_label": actor_label,
            "expected_sample_kit_version": expected_sample_kit_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Remedies
# ---------------------------------------------------------------------------
def remedy_payload(
    complaint_id: str,
    expected_complaint_version: int,
    remedy_type: str = "COUPON",
    requested_value_cents: int = 2000,
    **overrides,
) -> dict:
    return _build(
        {
            "complaint_id": complaint_id,
            "remedy_type": remedy_type,
            "requested_value_cents": requested_value_cents,
            "expected_complaint_version": expected_complaint_version,
        },
        overrides,
    )


def decide_payload(decision: str, **overrides) -> dict:
    return _build({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Regulatory
# ---------------------------------------------------------------------------
def regulatory_report_payload(
    complaint_id: str, report_kind: str = "ADVERSE_EVENT", **overrides
) -> dict:
    return _build({"complaint_id": complaint_id, "report_kind": report_kind}, overrides)


def determine_payload(determination: str, **overrides) -> dict:
    return _build({"determination": determination}, overrides)


def submit_report_payload(agency_reference: str = "AG-90001", **overrides) -> dict:
    return _build({"agency_reference": agency_reference}, overrides)


# ---------------------------------------------------------------------------
# Trend signals
# ---------------------------------------------------------------------------
def trend_signal_payload(
    scope_level: str,
    plant_id: str,
    window_start: str,
    window_end: str,
    **overrides,
) -> dict:
    return _build(
        {
            "scope_level": scope_level,
            "plant_id": plant_id,
            "window_start": window_start,
            "window_end": window_end,
        },
        overrides,
    )


def initiate_recall_payload(recall_reference: str = "RC-1", **overrides) -> dict:
    return _build({"recall_reference": recall_reference}, overrides)


# ---------------------------------------------------------------------------
# Response templates
# ---------------------------------------------------------------------------
def response_template_payload(
    template_code: str = "T-ANY",
    title: str = "General apology",
    body: str = "We are sorry to hear this.",
    applies_to_type: str = "ANY",
    max_band_allowed: str = "S2",
    **overrides,
) -> dict:
    return _build(
        {
            "template_code": template_code,
            "title": title,
            "body": body,
            "applies_to_type": applies_to_type,
            "max_band_allowed": max_band_allowed,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Operations checkpoint
# ---------------------------------------------------------------------------
def quality_ops_run_payload(**overrides) -> dict:
    return _build({}, overrides)
