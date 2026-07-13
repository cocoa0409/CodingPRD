"""Payload factories — one per entity, input fields only (PRD §3.1–§3.9).

Every factory generates unique values for the PRD's unique fields (frame `sku`,
lens option `code`, customer `email`) so a single test can mint several rows
without colliding.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


# ─── Catalog ─────────────────────────────────────────────────────────────────

def create_insurance_policy_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1 — a vision plan. `oon_reimburse_pct` and `oon_fee_schedule` are
    the only optional inputs."""
    n = _next()
    payload: Dict[str, Any] = {
        "member_id": f"MEM-{n:04d}",
        "network": "IN_NETWORK",
        "frame_allowance_cents": 15000,
        "lens_copay_cents": 2500,
        "annual_max_cents": 30000,
        "plan_year_start": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_store_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1 — a store. `status`, `buffer_minutes` and `pickup_capacity_per_day`
    are optional."""
    n = _next()
    payload: Dict[str, Any] = {
        "name": f"Store {n}",
        "exam_chairs": 1,
    }
    payload.update(overrides)
    return payload


def create_frame_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1 — a catalog frame. `status` is the only optional input."""
    n = _next()
    payload: Dict[str, Any] = {
        "sku": f"FRM-{n:04d}",
        "name": f"Frame {n}",
        "brand": "WP",
        "price_cents": TEST_DEFAULTS["FRAME_PRICE_CENTS"],
        "tryon_stock": TEST_DEFAULTS["FRAME_TRYON_STOCK"],
        "min_pd_mm": TEST_DEFAULTS["FRAME_MIN_PD_MM"],
        "max_pd_mm": TEST_DEFAULTS["FRAME_MAX_PD_MM"],
    }
    payload.update(overrides)
    return payload


def create_material_option_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1 — a MATERIAL lens option; it carries a `material_index`."""
    n = _next()
    payload: Dict[str, Any] = {
        "code": f"MAT{n:04d}",
        "category": "MATERIAL",
        "base_price_cents": 6000,
        "material_index": 1.60,
    }
    payload.update(overrides)
    return payload


def create_coating_option_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1 — a COATING lens option; it leaves `material_index` null."""
    n = _next()
    payload: Dict[str, Any] = {
        "code": f"COAT{n:04d}",
        "category": "COATING",
        "base_price_cents": 4000,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1 — a customer. `insurance_policy_id` and `fsa_balance_cents` are
    the only optional inputs."""
    n = _next()
    payload: Dict[str, Any] = {
        "full_name": f"Test Customer {n}",
        "email": f"customer{n}@example.com",
        "dob": "1990-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ─── Clinical ────────────────────────────────────────────────────────────────

def create_prescription_payload(customer_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.2 — a prescription. `prism_diopters` is the only optional input.
    Defaults describe a low-power Rx: power == 1.00, requiring index tier 1.50."""
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "od_sphere": -1.00,
        "od_cylinder": 0.00,
        "os_sphere": -1.00,
        "os_cylinder": 0.00,
        "pd_mm": TEST_DEFAULTS["PD_MM"],
        "issued_at": TEST_DEFAULTS["ISSUED_AT"],
        "expires_at": TEST_DEFAULTS["EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def resubmit_prescription_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.2 — resubmission overwrites ALL the measurement fields."""
    payload: Dict[str, Any] = {
        "od_sphere": -1.00,
        "od_cylinder": 0.00,
        "os_sphere": -1.00,
        "os_cylinder": 0.00,
        "pd_mm": TEST_DEFAULTS["PD_MM"],
        "issued_at": TEST_DEFAULTS["ISSUED_AT"],
        "expires_at": TEST_DEFAULTS["EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


# ─── Try-on ──────────────────────────────────────────────────────────────────

def create_kit_payload(
    customer_id: str,
    frame_ids: List[str],
    ship_date: str = "2026-05-05T00:00:00Z",
    due_date: str = "2026-05-15T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.4 — a home try-on kit over the closed [ship_date, due_date] window."""
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "frame_ids": frame_ids,
        "ship_date": ship_date,
        "due_date": due_date,
    }
    payload.update(overrides)
    return payload


# ─── Orders ──────────────────────────────────────────────────────────────────

def create_order_payload(
    customer_id: str,
    prescription_id: str,
    frame_id: str,
    material_option_id: str,
    delivery_method: str = "SHIP",
    coating_option_ids: Optional[List[str]] = None,
    store_id: Optional[str] = None,
    exam_appointment_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.5 — an order. `coating_option_ids`, `store_id` and
    `exam_appointment_id` are the optional inputs."""
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "prescription_id": prescription_id,
        "frame_id": frame_id,
        "material_option_id": material_option_id,
        "delivery_method": delivery_method,
    }
    if coating_option_ids is not None:
        payload["coating_option_ids"] = coating_option_ids
    if store_id is not None:
        payload["store_id"] = store_id
    if exam_appointment_id is not None:
        payload["exam_appointment_id"] = exam_appointment_id
    payload.update(overrides)
    return payload


# ─── Exams ───────────────────────────────────────────────────────────────────

def create_exam_appointment_payload(
    customer_id: str,
    store_id: str,
    start_at: str = "2026-06-01T10:00:00Z",
    end_at: str = "2026-06-01T10:30:00Z",
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.3 — an eye exam booking."""
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "store_id": store_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


# ─── Insurance / warranty ────────────────────────────────────────────────────

def create_insurance_claim_payload(
    order_id: str,
    expected_order_version: int,
    service_lines: Optional[List[Dict[str, Any]]] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §2.7 / §3.8 — an explicit claim filing; `expected_order_version` is
    non-optional."""
    payload: Dict[str, Any] = {
        "order_id": order_id,
        "service_lines": service_lines if service_lines is not None else [],
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


def create_warranty_claim_payload(
    lab_order_id: str,
    customer_id: str,
    reason: str,
    expected_lab_order_version: int,
    **overrides,
) -> Dict[str, Any]:
    """PRD §2.7 / §3.9 — a warranty filing; `expected_lab_order_version` is
    non-optional."""
    payload: Dict[str, Any] = {
        "lab_order_id": lab_order_id,
        "customer_id": customer_id,
        "reason": reason,
        "expected_lab_order_version": expected_lab_order_version,
    }
    payload.update(overrides)
    return payload
