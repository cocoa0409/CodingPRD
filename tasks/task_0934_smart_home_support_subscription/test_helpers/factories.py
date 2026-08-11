"""Payload factories — one per created resource, input fields only."""

from typing import Dict, List, Optional

from .constants import CATALOG_TEMPLATES, PLAN_TEMPLATES, TEST_DEFAULTS


def create_household_payload(**overrides) -> dict:
    payload = {
        "name": "Test House",
        "region_code": TEST_DEFAULTS["REGION"],
        "billing_email": "house@example.com",
    }
    payload.update(overrides)
    return payload


def create_member_payload(member_role: str = "OWNER", **overrides) -> dict:
    payload = {
        "full_name": "Test Member",
        "email": "member@example.com",
        "member_role": member_role,
    }
    payload.update(overrides)
    return payload


def create_plan_payload(kind: str = "PRO", **overrides) -> dict:
    payload = dict(PLAN_TEMPLATES[kind])
    payload.update(overrides)
    return payload


def create_subscription_payload(household_id: str, plan_id: str, **overrides) -> dict:
    payload = {"household_id": household_id, "plan_id": plan_id}
    payload.update(overrides)
    return payload


def create_catalog_payload(kind: str = "HUB", **overrides) -> dict:
    payload = dict(CATALOG_TEMPLATES[kind])
    payload.update(overrides)
    return payload


def claim_device_payload(
    household_id: str,
    catalog_entry_id: str,
    serial_number: str,
    purchase_date: str = TEST_DEFAULTS["PURCHASE_DATE"],
    **overrides,
) -> dict:
    payload = {
        "household_id": household_id,
        "catalog_entry_id": catalog_entry_id,
        "serial_number": serial_number,
        "purchase_date": purchase_date,
    }
    payload.update(overrides)
    return payload


def create_ticket_payload(
    household_id: str,
    severity: str = "P2",
    summary: str = "Device misbehaving",
    **overrides,
) -> dict:
    payload = {
        "household_id": household_id,
        "severity": severity,
        "summary": summary,
    }
    payload.update(overrides)
    return payload


def create_technician_payload(
    full_name: str = "Test Tech",
    region_code: str = TEST_DEFAULTS["REGION"],
    skills: Optional[List[str]] = None,
    **overrides,
) -> dict:
    payload = {
        "full_name": full_name,
        "region_code": region_code,
        "skills": list(skills) if skills else ["HUB"],
    }
    payload.update(overrides)
    return payload


def create_slot_payload(start_at: str, end_at: str, **overrides) -> dict:
    payload = {"start_at": start_at, "end_at": end_at}
    payload.update(overrides)
    return payload


def create_campaign_payload(
    catalog_entry_id: str,
    kind: str = "SECURITY_MANDATORY",
    target_firmware_version: str = "1.1.0",
    **overrides,
) -> dict:
    payload = {
        "catalog_entry_id": catalog_entry_id,
        "kind": kind,
        "target_firmware_version": target_firmware_version,
    }
    payload.update(overrides)
    return payload


def launch_ring_payload(
    ring_index: int,
    device_ids: List[str],
    window_start_at: str,
    window_end_at: str,
) -> dict:
    return {
        "ring_index": ring_index,
        "device_ids": list(device_ids),
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }


def order_line(catalog_entry_id: str, quantity: int = 1) -> Dict[str, object]:
    return {"catalog_entry_id": catalog_entry_id, "quantity": quantity}


def place_order_payload(
    household_id: str,
    subscription_id: str,
    lines: List[dict],
    expected_subscription_version: int,
) -> dict:
    return {
        "household_id": household_id,
        "subscription_id": subscription_id,
        "lines": list(lines),
        "expected_subscription_version": expected_subscription_version,
    }


def open_rma_payload(device_id: str, expected_device_version: int, **overrides) -> dict:
    payload = {
        "device_id": device_id,
        "expected_device_version": expected_device_version,
    }
    payload.update(overrides)
    return payload


def survey_payload(score: int, **overrides) -> dict:
    payload = {"score": score}
    payload.update(overrides)
    return payload
