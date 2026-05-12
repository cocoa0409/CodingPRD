"""Payload factories — one per entity, input fields only.

Field names match the PRD §3.x prose verbatim. Defaults are picked to
satisfy every PRD-stated input constraint so factories are usable as-is
in setup paths. Tests pass overrides for the values they want to control.
"""
from __future__ import annotations
import itertools
from typing import Any, Dict, List, Optional


_skill_counter = itertools.count(1)
_volunteer_counter = itertools.count(1)
_activity_counter = itertools.count(1)
_id_hash_counter = itertools.count(1)
_template_counter = itertools.count(1)
_sku_counter = itertools.count(1)


def unique_skill_code(prefix: str = "SKILL") -> str:
    n = next(_skill_counter)
    return f"{prefix}_{n:06d}"


def unique_id_number_hash(prefix: str = "HASH") -> str:
    n = next(_id_hash_counter)
    return f"{prefix}_{n:08d}"


def unique_volunteer_full_name() -> str:
    n = next(_volunteer_counter)
    return f"Volunteer {n}"


def unique_activity_title() -> str:
    n = next(_activity_counter)
    return f"Activity {n}"


def unique_template_code() -> str:
    n = next(_template_counter)
    return f"TPL_{n:06d}"


def unique_sku() -> str:
    n = next(_sku_counter)
    return f"SKU_{n:06d}"


# ===========================================================================
# Volunteer (PRD §3.1)
# ===========================================================================
def create_volunteer_payload(
    *,
    full_name: Optional[str] = None,
    id_number_hash: Optional[str] = None,
    home_lat: float = 30.0,
    home_lng: float = 120.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name if full_name is not None else unique_volunteer_full_name(),
        "id_number_hash": (
            id_number_hash if id_number_hash is not None else unique_id_number_hash()
        ),
        "home_lat": home_lat,
        "home_lng": home_lng,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Skill catalog (PRD §3.2)
# ===========================================================================
def create_skill_payload(
    *,
    code: Optional[str] = None,
    name: Optional[str] = None,
    requires_certificate: bool = False,
    sensitivity_level: str = "STANDARD",
    **overrides: Any,
) -> Dict[str, Any]:
    code_value = code if code is not None else unique_skill_code()
    payload: Dict[str, Any] = {
        "code": code_value,
        "name": name if name is not None else f"Skill {code_value}",
        "requires_certificate": requires_certificate,
        "sensitivity_level": sensitivity_level,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# VolunteerSkill (PRD §3.2)
# ===========================================================================
def declare_volunteer_skill_payload(
    *,
    skill_id: str,
    certificate_url: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"skill_id": skill_id}
    if certificate_url is not None:
        payload["certificate_url"] = certificate_url
    payload.update(overrides)
    return payload


def resubmit_volunteer_skill_payload(
    *,
    certificate_url: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"certificate_url": certificate_url}
    payload.update(overrides)
    return payload


# ===========================================================================
# Activity (PRD §3.3)
# ===========================================================================
def create_activity_payload(
    *,
    title: Optional[str] = None,
    description: Optional[str] = None,
    location_lat: float = 30.0,
    location_lng: float = 120.0,
    start_at: str = "2030-04-01T10:00:00.000Z",
    end_at: str = "2030-04-01T12:00:00.000Z",
    recruit_open_at: str = "2030-03-15T08:00:00.000Z",
    recruit_close_at: str = "2030-03-31T20:00:00.000Z",
    required_skill_codes: Optional[List[str]] = None,
    position_quota: int = 5,
    difficulty: Optional[str] = None,
    hour_rule_type: Optional[str] = None,
    fixed_hour_value: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title": title if title is not None else unique_activity_title(),
        "description": description if description is not None
        else "PRD-driven activity description for the test harness.",
        "location_lat": location_lat,
        "location_lng": location_lng,
        "start_at": start_at,
        "end_at": end_at,
        "recruit_open_at": recruit_open_at,
        "recruit_close_at": recruit_close_at,
        "required_skill_codes": required_skill_codes
        if required_skill_codes is not None
        else [],
        "position_quota": position_quota,
    }
    if difficulty is not None:
        payload["difficulty"] = difficulty
    if hour_rule_type is not None:
        payload["hour_rule_type"] = hour_rule_type
    if fixed_hour_value is not None:
        payload["fixed_hour_value"] = fixed_hour_value
    payload.update(overrides)
    return payload


def define_activity_role_payload(
    *,
    role_label: str = "LEAD",
    coefficient: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"role_label": role_label}
    if coefficient is not None:
        payload["coefficient"] = coefficient
    payload.update(overrides)
    return payload


# ===========================================================================
# Application (PRD §3.4 / §3.5)
# ===========================================================================
def apply_to_activity_payload(
    *,
    activity_id: str,
    activity_role_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"activity_id": activity_id}
    if activity_role_id is not None:
        payload["activity_role_id"] = activity_role_id
    payload.update(overrides)
    return payload


def check_in_payload(
    *,
    site_code: Optional[str] = None,
    check_in_lat: Optional[float] = None,
    check_in_lng: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if site_code is not None:
        payload["site_code"] = site_code
    if check_in_lat is not None:
        payload["check_in_lat"] = check_in_lat
    if check_in_lng is not None:
        payload["check_in_lng"] = check_in_lng
    payload.update(overrides)
    return payload


def leave_payload(
    *,
    leave_reason: str = "Family emergency requiring brief absence.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"leave_reason": leave_reason}
    payload.update(overrides)
    return payload


def manual_correction_payload(
    *,
    check_in_at: Optional[str] = None,
    check_out_at: Optional[str] = None,
    late_marker: Optional[bool] = None,
    early_departure_marker: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if check_in_at is not None:
        payload["check_in_at"] = check_in_at
    if check_out_at is not None:
        payload["check_out_at"] = check_out_at
    if late_marker is not None:
        payload["late_marker"] = late_marker
    if early_departure_marker is not None:
        payload["early_departure_marker"] = early_departure_marker
    payload.update(overrides)
    return payload


# ===========================================================================
# HourAdjustment (PRD §3.7)
# ===========================================================================
def file_hour_adjustment_payload(
    *,
    application_id: str,
    delta_hours: float = 0.50,
    reason: str = "Volunteer assisted with extra cleanup duties.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "delta_hours": delta_hours,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Point mall (PRD §3.7)
# ===========================================================================
def create_point_mall_item_payload(
    *,
    sku: Optional[str] = None,
    name: Optional[str] = None,
    point_cost: int = 50,
    stock: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    sku_value = sku if sku is not None else unique_sku()
    payload: Dict[str, Any] = {
        "sku": sku_value,
        "name": name if name is not None else f"Item {sku_value}",
        "point_cost": point_cost,
        "stock": stock,
    }
    payload.update(overrides)
    return payload


def restock_payload(*, delta: int = 5, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"delta": delta}
    payload.update(overrides)
    return payload


def create_redemption_order_payload(
    *,
    item_id: str,
    quantity: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"item_id": item_id, "quantity": quantity}
    payload.update(overrides)
    return payload


# ===========================================================================
# Certificate templates and certificates (PRD §3.9)
# ===========================================================================
def create_certificate_template_payload(
    *,
    code: Optional[str] = None,
    title: Optional[str] = None,
    min_hours: float = 5.00,
    min_completed_activities: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    code_value = code if code is not None else unique_template_code()
    payload: Dict[str, Any] = {
        "code": code_value,
        "title": title if title is not None else f"Template {code_value}",
        "min_hours": min_hours,
        "min_completed_activities": min_completed_activities,
    }
    payload.update(overrides)
    return payload


def issue_certificate_payload(
    *,
    template_id: str,
    volunteer_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "template_id": template_id,
        "volunteer_id": volunteer_id,
    }
    payload.update(overrides)
    return payload


def issue_certificates_batch_payload(
    *,
    template_id: str,
    volunteer_ids: List[str],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "template_id": template_id,
        "volunteer_ids": list(volunteer_ids),
    }
    payload.update(overrides)
    return payload


__all__ = [
    "unique_skill_code",
    "unique_id_number_hash",
    "unique_volunteer_full_name",
    "unique_activity_title",
    "unique_template_code",
    "unique_sku",
    "create_volunteer_payload",
    "create_skill_payload",
    "declare_volunteer_skill_payload",
    "resubmit_volunteer_skill_payload",
    "create_activity_payload",
    "define_activity_role_payload",
    "apply_to_activity_payload",
    "check_in_payload",
    "leave_payload",
    "manual_correction_payload",
    "file_hour_adjustment_payload",
    "create_point_mall_item_payload",
    "restock_payload",
    "create_redemption_order_payload",
    "create_certificate_template_payload",
    "issue_certificate_payload",
    "issue_certificates_batch_payload",
]
