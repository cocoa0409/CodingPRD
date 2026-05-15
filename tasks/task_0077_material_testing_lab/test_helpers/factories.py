"""Payload factories — one per endpoint that takes a body.

Only fields whose source is `input` in PRD §3. Each factory accepts
**overrides so individual tests can vary specific values without
re-typing the entire payload.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_MAX_CONCURRENT_TASKS,
    METHOD_TO_CATEGORY,
    TEST_DEFAULTS,
)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
def create_client_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'registers a Client by providing a name and a
    contact_email. An optional contract_id may be supplied at creation'."""
    defaults: Dict[str, Any] = {
        "name": f"{TEST_DEFAULTS['CLIENT_NAME']}-{uuid.uuid4().hex[:6]}",
        "contact_email": TEST_DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def update_client_payload(*, version: int, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'The same update operation may revise contact_email and
    contract_id; both updates require the current version in the request
    body.'"""
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Tester / Reviewer / Signatory
# ---------------------------------------------------------------------------
def qualification(material_category: str, valid_from: str,
                  valid_to: str) -> Dict[str, str]:
    return {
        "material_category": material_category,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }


def create_tester_payload(
    *,
    qualifications: Optional[List[Dict[str, Any]]] = None,
    max_concurrent_tasks: int = DEFAULT_MAX_CONCURRENT_TASKS,
    full_name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'creates a Tester by supplying full_name, a
    qualifications array, and an optional max_concurrent_tasks cap
    (default 5).'"""
    if qualifications is None:
        # Default: qualified for CONCRETE for an extremely broad window
        # that comfortably encloses both real wall-clock startup and any
        # future logical-clock value the test suite advances to.
        qualifications = [
            qualification("CONCRETE", "2024-01-01", "2200-12-31"),
        ]
    payload: Dict[str, Any] = {
        "full_name": full_name or f"{TEST_DEFAULTS['TESTER_NAME']} "
                                  f"{uuid.uuid4().hex[:4]}",
        "qualifications": qualifications,
        "max_concurrent_tasks": max_concurrent_tasks,
    }
    payload.update(overrides)
    return payload


def update_tester_payload(*, version: int, **overrides: Any) -> Dict[str, Any]:
    """PRD §2.4 / §3.5: PATCH /testers/{id} carries the current version."""
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


def create_reviewer_payload(
    *,
    scope_categories: Optional[List[str]] = None,
    full_name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'A Reviewer is created with full_name and scope_categories
    (an array of material-category values the reviewer may review).'"""
    if scope_categories is None:
        scope_categories = ["CONCRETE"]
    payload: Dict[str, Any] = {
        "full_name": full_name or f"{TEST_DEFAULTS['REVIEWER_NAME']} "
                                  f"{uuid.uuid4().hex[:4]}",
        "scope_categories": scope_categories,
    }
    payload.update(overrides)
    return payload


def create_signatory_payload(
    *,
    scope_categories: Optional[List[str]] = None,
    signature_certificate_id: Optional[str] = None,
    full_name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'A Signatory is created with full_name, a
    signature_certificate_id referencing the electronic-signature
    certificate to be embedded in issued reports, and scope_categories.'"""
    if scope_categories is None:
        scope_categories = ["CONCRETE"]
    payload: Dict[str, Any] = {
        "full_name": full_name or f"{TEST_DEFAULTS['SIGNATORY_NAME']} "
                                  f"{uuid.uuid4().hex[:4]}",
        "signature_certificate_id": (
            signature_certificate_id or TEST_DEFAULTS["SIGNATURE_CERT_ID"]
        ),
        "scope_categories": scope_categories,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Instrument & Bookings
# ---------------------------------------------------------------------------
def create_instrument_payload(
    *,
    capabilities: Optional[List[str]] = None,
    calibration_valid_from: str = "2024-01-01T00:00:00.000Z",
    calibration_valid_to: str = "2030-12-31T23:59:59.000Z",
    asset_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'a lab-internal asset_code (unique across all
    instruments), a capabilities array listing the test methods it can
    perform, and a calibration window bounded by calibration_valid_from
    (inclusive start) and calibration_valid_to (inclusive end).'"""
    if capabilities is None:
        capabilities = ["COMPRESSION_STRENGTH"]
    payload: Dict[str, Any] = {
        "asset_code": (
            asset_code
            or f"{TEST_DEFAULTS['INSTRUMENT_ASSET_CODE_PREFIX']}"
               f"{uuid.uuid4().hex[:6].upper()}"
        ),
        "capabilities": capabilities,
        "calibration_valid_from": calibration_valid_from,
        "calibration_valid_to": calibration_valid_to,
    }
    payload.update(overrides)
    return payload


def update_instrument_payload(*, version: int,
                              **overrides: Any) -> Dict[str, Any]:
    """PRD §2.4 / §3.4: PATCH /instruments/{id} carries the current
    version."""
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


def create_booking_payload(*, task_id: str, slot_start: str, slot_end: str,
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'submits a booking with task_id, slot_start, and
    slot_end.'"""
    payload: Dict[str, Any] = {
        "task_id": task_id,
        "slot_start": slot_start,
        "slot_end": slot_end,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Sample
# ---------------------------------------------------------------------------
def create_sample_payload(
    *,
    client_id: str,
    material_category: str = "CONCRETE",
    specification: Optional[str] = None,
    witness_sampled: bool = False,
    witness_name: Optional[str] = None,
    handover_at: str = "2026-01-01T09:00:00.000Z",
    source_project: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'registers a Sample by supplying the owning client_id,
    the source_project it was taken from, the material_category, a
    free-text specification, a boolean witness_sampled flag, an optional
    witness_name, and a handover_record object carrying three required
    keys: delivered_by, received_by, and handover_at.'"""
    spec_default = {
        "CONCRETE": TEST_DEFAULTS["SPEC_CONCRETE_CUBE_150MM"],
        "STEEL_REBAR": TEST_DEFAULTS["SPEC_STEEL_REBAR"],
        "SOIL": TEST_DEFAULTS["SPEC_SOIL"],
        "ASPHALT": TEST_DEFAULTS["SPEC_ASPHALT"],
        "CEMENT": TEST_DEFAULTS["SPEC_CEMENT"],
    }[material_category]
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "source_project": source_project or TEST_DEFAULTS["SOURCE_PROJECT"],
        "material_category": material_category,
        "specification": specification or spec_default,
        "witness_sampled": witness_sampled,
        "handover_record": {
            "delivered_by": "Driver Dan",
            "received_by": "Clerk Carla",
            "handover_at": handover_at,
        },
    }
    if witness_sampled:
        payload["witness_name"] = witness_name or "Inspector Ines"
    elif witness_name is not None:
        # Intentionally include — used by the "inconsistency in the other
        # direction" test case.
        payload["witness_name"] = witness_name
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test task
# ---------------------------------------------------------------------------
def create_test_task_payload(
    *,
    test_method: str = "COMPRESSION_STRENGTH",
    urgent: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'creates a TestTask under a registered sample by
    supplying the test_method enumeration value and the optional urgent
    boolean (default false).'"""
    payload: Dict[str, Any] = {
        "test_method": test_method,
        "urgent": urgent,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test record
# ---------------------------------------------------------------------------
def create_record_payload(
    *,
    peak_load_kn: float = 600.0,
    supersedes_record_id: Optional[str] = None,
    raw_data: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: 'Each record carries the task_id, the tester_id ..., a
    raw_data object holding the instrument-output blob as delivered ...,
    an optional supersedes_record_id linking the record to the abnormal
    record it replaces during a retest.'"""
    if raw_data is None:
        raw_data = {"peak_load_kn": peak_load_kn}
    payload: Dict[str, Any] = {"raw_data": raw_data}
    if supersedes_record_id is not None:
        payload["supersedes_record_id"] = supersedes_record_id
    payload.update(overrides)
    return payload


def update_record_payload(
    *,
    version: int,
    reason: str,
    raw_data: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'The modification operation accepts a partial raw_data
    patch alongside a free-text reason and the current version.'"""
    payload: Dict[str, Any] = {"version": version, "reason": reason}
    if raw_data is not None:
        payload["raw_data"] = raw_data
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------
def create_invoice_payload(*, task_ids: List[str],
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.10: 'A LabManager issues an Invoice for a list of completed
    tasks belonging to one client by submitting a task_ids payload.'"""
    payload: Dict[str, Any] = {"task_ids": list(task_ids)}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Admin / system endpoints
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §2.10: 'takes a target instant `to` and advances the logical
    clock to that instant.'"""
    payload: Dict[str, Any] = {"to": to}
    payload.update(overrides)
    return payload


def emit_event_payload(*, event_type: str, payload: Dict[str, Any],
                       **overrides: Any) -> Dict[str, Any]:
    """PRD §2.10: 'takes an event_type and a payload and synchronises
    with three external systems.'"""
    body: Dict[str, Any] = {"event_type": event_type, "payload": payload}
    body.update(overrides)
    return body


def respond_external_payload(*, inspection_id: str, response_note: str,
                             **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: 'A LabManager may also record an external-inspection
    response by supplying an inspection_id and a response_note.'"""
    payload: Dict[str, Any] = {
        "inspection_id": inspection_id,
        "response_note": response_note,
    }
    payload.update(overrides)
    return payload


__all__ = [
    "create_client_payload",
    "update_client_payload",
    "qualification",
    "create_tester_payload",
    "update_tester_payload",
    "create_reviewer_payload",
    "create_signatory_payload",
    "create_instrument_payload",
    "update_instrument_payload",
    "create_booking_payload",
    "create_sample_payload",
    "create_test_task_payload",
    "create_record_payload",
    "update_record_payload",
    "create_invoice_payload",
    "clock_advance_payload",
    "emit_event_payload",
    "respond_external_payload",
]


# Method ↔ category coupling re-exported for tests that need to choose a
# valid (method, spec) pair for an arbitrary material category.
def method_for_category(category: str) -> str:
    """Reverse-lookup the test_method paired with a material_category by
    PRD §3.3."""
    for method, cat in METHOD_TO_CATEGORY.items():
        if cat == category:
            return method
    raise ValueError(f"Unknown material category: {category}")


__all__.append("method_for_category")
