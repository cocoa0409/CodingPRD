"""Payload factories — one per entity, request-input fields only."""

from typing import Any, Dict, List, Optional


def create_property_payload(**overrides) -> Dict[str, Any]:
    """Register a rental unit. Required: code, name, zone_code, size_tier,
    owner_contact_email."""
    payload: Dict[str, Any] = {
        "code": "AUS-101",
        "name": "Barton Loft",
        "zone_code": "ZONE_A",
        "size_tier": "TWO_BR",
        "owner_contact_email": "owner1@example.com",
    }
    payload.update(overrides)
    return payload


def create_cleaner_payload(**overrides) -> Dict[str, Any]:
    """Onboard a cleaner. Required: name, home_zone_code, skill_level."""
    payload: Dict[str, Any] = {
        "name": "Cleaner C",
        "home_zone_code": "ZONE_A",
        "skill_level": 4,
    }
    payload.update(overrides)
    return payload


def create_supply_line_payload(**overrides) -> Dict[str, Any]:
    """Add a par-level stock line. Required: sku, name, category,
    unit_cost_cents, par_qty."""
    payload: Dict[str, Any] = {
        "sku": "LIN-SHEET-Q",
        "name": "Queen Sheet Set",
        "category": "LINEN",
        "unit_cost_cents": 260,
        "par_qty": 6,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(property_id: str, **overrides) -> Dict[str, Any]:
    """Import a reservation. Required: property_id, external_ref, guest_name,
    checkin_at, checkout_at."""
    payload: Dict[str, Any] = {
        "property_id": property_id,
        "external_ref": "OUT-1",
        "guest_name": "Guest Out",
        "checkin_at": "2026-08-05T21:00:00Z",
        "checkout_at": "2026-08-08T16:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_turnover_payload(outgoing_booking_id: str,
                            incoming_booking_id: Optional[str] = None,
                            **overrides) -> Dict[str, Any]:
    """Open a turnover. Required: outgoing_booking_id. Omit
    incoming_booking_id for a vacant gap."""
    payload: Dict[str, Any] = {"outgoing_booking_id": outgoing_booking_id}
    if incoming_booking_id is not None:
        payload["incoming_booking_id"] = incoming_booking_id
    payload.update(overrides)
    return payload


def assign_turnover_payload(expected_turnover_version: int,
                            cleaner_id: Optional[str] = None,
                            **overrides) -> Dict[str, Any]:
    """Create an offer. expected_turnover_version is mandatory; omit
    cleaner_id to run the weighted selector."""
    payload: Dict[str, Any] = {
        "expected_turnover_version": expected_turnover_version,
    }
    if cleaner_id is not None:
        payload["cleaner_id"] = cleaner_id
    payload.update(overrides)
    return payload


def replenish_payload(qty: int, expected_supply_line_version: int,
                      **overrides) -> Dict[str, Any]:
    """Record received stock. qty and expected_supply_line_version are
    mandatory."""
    payload: Dict[str, Any] = {
        "qty": qty,
        "expected_supply_line_version": expected_supply_line_version,
    }
    payload.update(overrides)
    return payload


def restock_entry(supply_line_id: str, qty_used: int) -> Dict[str, Any]:
    """One entry of a submission's restock_entries list."""
    return {"supply_line_id": supply_line_id, "qty_used": qty_used}


def submit_task_payload(photo_uri: Optional[str] = None,
                        note: Optional[str] = None,
                        restock_entries: Optional[List[Dict[str, Any]]] = None,
                        **overrides) -> Dict[str, Any]:
    """Submit a checklist task."""
    payload: Dict[str, Any] = {}
    if photo_uri is not None:
        payload["photo_uri"] = photo_uri
    if note is not None:
        payload["note"] = note
    if restock_entries is not None:
        payload["restock_entries"] = restock_entries
    payload.update(overrides)
    return payload


def review_task_payload(action: str, reject_reason: Optional[str] = None,
                        **overrides) -> Dict[str, Any]:
    """Review a checklist task with APPROVE, REJECT or WAIVE."""
    payload: Dict[str, Any] = {"action": action}
    if reject_reason is not None:
        payload["reject_reason"] = reject_reason
    payload.update(overrides)
    return payload


def create_issue_report_payload(turnover_id: str, **overrides) -> Dict[str, Any]:
    """File a damage or maintenance finding. Required: turnover_id, issue_type,
    severity, description, estimated_cost_cents."""
    payload: Dict[str, Any] = {
        "turnover_id": turnover_id,
        "issue_type": "MAINTENANCE",
        "severity": "LOW",
        "description": "shower valve drips continuously",
        "estimated_cost_cents": 2000,
    }
    payload.update(overrides)
    return payload


def dispatch_payload(vendor_name: str = "Hill Country Plumbing",
                     scheduled_at: str = "2026-08-08T18:00:00Z",
                     **overrides) -> Dict[str, Any]:
    """Dispatch a repair vendor. Required: vendor_name, scheduled_at."""
    payload: Dict[str, Any] = {
        "vendor_name": vendor_name,
        "scheduled_at": scheduled_at,
    }
    payload.update(overrides)
    return payload


def complete_repair_payload(actual_cost_cents: int, **overrides) -> Dict[str, Any]:
    """Close a repair order."""
    payload: Dict[str, Any] = {"actual_cost_cents": actual_cost_cents}
    payload.update(overrides)
    return payload


def create_quality_audit_payload(turnover_id: str, score: int,
                                 **overrides) -> Dict[str, Any]:
    """Sample a completed turnover. Required: turnover_id, score."""
    payload: Dict[str, Any] = {"turnover_id": turnover_id, "score": score}
    payload.update(overrides)
    return payload


def cleaner_status_payload(action: str, reason: Optional[str] = None,
                           **overrides) -> Dict[str, Any]:
    """Suspend, reactivate or offboard a cleaner."""
    payload: Dict[str, Any] = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


def schedule_change_payload(change_type: str, new_time_at: str,
                            override_reason: Optional[str] = None,
                            **overrides) -> Dict[str, Any]:
    """Grant a late checkout or an early check-in."""
    payload: Dict[str, Any] = {
        "change_type": change_type,
        "new_time_at": new_time_at,
    }
    if override_reason is not None:
        payload["override_reason"] = override_reason
    payload.update(overrides)
    return payload
