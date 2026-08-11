"""Payload factories — one per resource, input fields only."""

import itertools

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A per-process monotonically increasing token, used to keep owner emails unique."""
    return f"{next(_counter):05d}"


def create_owner_payload(**overrides) -> dict:
    n = unique_suffix()
    payload = {
        "full_name": f"Snowbird Owner {n}",
        "email": f"owner.{n}@example.com",
        "phone": f"+1555{n}",
        "primary_residence_state": "MN",
    }
    payload.update(overrides)
    return payload


def create_property_payload(owner_id: str, **overrides) -> dict:
    payload = {
        "owner_id": owner_id,
        "label": "Naples Beach House",
        "address_line": "12 Gulf Rd",
        "state_code": "FL",
        "travel_distance_miles": 18.0,
    }
    payload.update(overrides)
    return payload


def create_service_plan_payload(**overrides) -> dict:
    payload = {
        "tier": "STANDARD",
        "monthly_fee_cents": 19986,
        "included_visit_units": 4,
        "covered_visit_types": ["ROUTINE_WATCH"],
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(property_id: str, service_plan_id: str,
                                started_on: str = "2026-06-01T00:00:00Z", **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "service_plan_id": service_plan_id,
        "started_on": started_on,
    }
    payload.update(overrides)
    return payload


def create_away_period_payload(property_id: str, owner_id: str,
                               start_at: str = "2026-07-01T00:00:00Z",
                               end_at: str = "2026-09-29T00:00:00Z",
                               cadence_days: int = 14, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "owner_id": owner_id,
        "start_at": start_at,
        "end_at": end_at,
        "cadence_days": cadence_days,
    }
    payload.update(overrides)
    return payload


def create_checklist_template_payload(visit_type: str = "ROUTINE_WATCH", **overrides) -> dict:
    payload = {
        "visit_type": visit_type,
        "version_label": "2026.1",
        "item_codes": ["EXT_WALK"],
        "critical_item_codes": [],
    }
    payload.update(overrides)
    return payload


def create_visit_payload(property_id: str, checklist_template_id: str,
                         visit_type: str = "ROUTINE_WATCH",
                         trigger_source: str = "SCHEDULED",
                         scheduled_start_at: str = "2026-06-02T13:00:00Z",
                         scheduled_end_at: str = "2026-06-02T15:00:00Z", **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "checklist_template_id": checklist_template_id,
        "visit_type": visit_type,
        "trigger_source": trigger_source,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    payload.update(overrides)
    return payload


def create_finding_payload(item_code: str = "EXT_WALK", severity: str = "MEDIUM",
                           category: str = "PLUMBING",
                           description: str = "Observed during the watch visit",
                           **overrides) -> dict:
    payload = {
        "item_code": item_code,
        "severity": severity,
        "category": category,
        "description": description,
    }
    payload.update(overrides)
    return payload


def create_vendor_payload(**overrides) -> dict:
    n = unique_suffix()
    payload = {
        "legal_name": f"Gulf Trades {n}",
        "trade": "PLUMBING",
        "coi_expires_at": "2027-01-01T00:00:00Z",
        "license_expires_at": "2027-01-01T00:00:00Z",
        "hourly_rate_cents": 8500,
        "rating": 4.0,
    }
    payload.update(overrides)
    return payload


def create_work_order_payload(expected_finding_version: int, work_type: str = "REPAIR",
                              estimated_labour_hours: float = 2.0,
                              estimated_parts_cents: int = 5000, **overrides) -> dict:
    payload = {
        "work_type": work_type,
        "estimated_labour_hours": estimated_labour_hours,
        "estimated_parts_cents": estimated_parts_cents,
        "expected_finding_version": expected_finding_version,
    }
    payload.update(overrides)
    return payload


def create_key_asset_payload(key_type: str = "PHYSICAL", label: str = "Front door",
                             copies_total: int = 2, **overrides) -> dict:
    payload = {"key_type": key_type, "label": label, "copies_total": copies_total}
    payload.update(overrides)
    return payload


def create_key_issuance_payload(vendor_id: str, **overrides) -> dict:
    payload = {"vendor_id": vendor_id}
    payload.update(overrides)
    return payload


def create_access_grant_payload(vendor_id: str, window_start_at: str, window_end_at: str,
                                expected_key_asset_version: int, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "expected_key_asset_version": expected_key_asset_version,
    }
    payload.update(overrides)
    return payload


def create_rental_turnover_payload(checkout_at: str = "2026-06-10T11:00:00Z",
                                   checkin_at: str = "2026-06-12T15:00:00Z",
                                   guest_reference: str = "BK-9001", **overrides) -> dict:
    payload = {
        "checkout_at": checkout_at,
        "checkin_at": checkin_at,
        "guest_reference": guest_reference,
    }
    payload.update(overrides)
    return payload


def create_mail_hold_payload(start_on: str = "2026-06-01T00:00:00Z",
                             end_on: str = "2026-06-20T00:00:00Z", **overrides) -> dict:
    payload = {"start_on": start_on, "end_on": end_on}
    payload.update(overrides)
    return payload


def create_security_incident_payload(incident_type: str = "ALARM_INTRUSION",
                                     severity: str = "HIGH", **overrides) -> dict:
    payload = {"incident_type": incident_type, "severity": severity}
    payload.update(overrides)
    return payload


def create_storm_event_payload(name: str = "Hurricane Delta", region_state_code: str = "FL",
                               landfall_eta_at: str = "2026-06-05T00:00:00Z", **overrides) -> dict:
    payload = {
        "name": name,
        "region_state_code": region_state_code,
        "landfall_eta_at": landfall_eta_at,
    }
    payload.update(overrides)
    return payload


def create_invoice_line_payload(line_type: str = "TRAVEL_SURCHARGE", description: str = "Trip",
                                amount_cents: int = 1500, **overrides) -> dict:
    payload = {
        "line_type": line_type,
        "description": description,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload
