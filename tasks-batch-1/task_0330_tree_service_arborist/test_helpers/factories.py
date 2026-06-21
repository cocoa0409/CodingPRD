"""Payload factories — one per entity, source: input fields only (PRD §3).

Optional fields are omitted unless explicitly overridden so the server applies
its declared defaults; only required fields carry factory defaults.
"""


# ─── ServiceArea (PRD §3.1) ─────────────────────────────


def create_service_area_payload(
    name: str = "Northwest",
    region_code: str = "NW-01",
    disposal_fee_cents_per_ton: int = 8000,
    **overrides,
) -> dict:
    defaults = {
        "name": name,
        "region_code": region_code,
        "disposal_fee_cents_per_ton": disposal_fee_cents_per_ton,
    }
    defaults.update(overrides)
    return defaults


# ─── Crew (PRD §3.1) ────────────────────────────────────


def create_crew_payload(
    service_area_id: str,
    name: str = "Crew A",
    hourly_rate_cents: int = 9000,
    **overrides,
) -> dict:
    defaults = {
        "service_area_id": service_area_id,
        "name": name,
        "hourly_rate_cents": hourly_rate_cents,
    }
    defaults.update(overrides)
    return defaults


# ─── Equipment (PRD §3.1) ───────────────────────────────


def create_equipment_payload(
    service_area_id: str,
    kind: str = "CHIPPER",
    name: str = "Chip-1",
    hourly_rate_cents: int = 15000,
    **overrides,
) -> dict:
    defaults = {
        "service_area_id": service_area_id,
        "kind": kind,
        "name": name,
        "hourly_rate_cents": hourly_rate_cents,
    }
    defaults.update(overrides)
    return defaults


# ─── WorkOrder (PRD §3.2) ───────────────────────────────


def create_work_order_payload(
    service_area_id: str,
    client_user_id: str = "client-1",
    site_address: str = "1 Oak St",
    pricing_mode: str = "PER_JOB",
    **overrides,
) -> dict:
    defaults = {
        "service_area_id": service_area_id,
        "client_user_id": client_user_id,
        "site_address": site_address,
        "pricing_mode": pricing_mode,
    }
    defaults.update(overrides)
    return defaults


# ─── TreeAsset (PRD §3.2) ───────────────────────────────


def create_tree_payload(
    species: str = "Maple",
    dbh_inches: float = 20,
    **overrides,
) -> dict:
    defaults = {
        "species": species,
        "dbh_inches": dbh_inches,
    }
    defaults.update(overrides)
    return defaults


# ─── LineItem (PRD §3.4) ────────────────────────────────


def create_line_item_payload(
    estimate_id: str,
    service_type: str = "REMOVAL",
    quantity: float = 1,
    **overrides,
) -> dict:
    defaults = {
        "estimate_id": estimate_id,
        "service_type": service_type,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


# ─── Permit (PRD §3.6) ──────────────────────────────────


def create_permit_payload(
    authority_ref: str = "PRM-001",
    **overrides,
) -> dict:
    defaults = {
        "authority_ref": authority_ref,
    }
    defaults.update(overrides)
    return defaults


def decide_permit_payload(decision: str = "APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


# ─── Booking (PRD §3.8) ─────────────────────────────────


def create_booking_payload(
    work_order_id: str,
    resource_kind: str,
    expected_work_order_version: int,
    start_at: str = "2026-07-01T09:00:00Z",
    end_at: str = "2026-07-01T12:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "resource_kind": resource_kind,
        "start_at": start_at,
        "end_at": end_at,
        "expected_work_order_version": expected_work_order_version,
    }
    defaults.update(overrides)
    return defaults


def finalize_booking_payload(actual_hours: float, **overrides) -> dict:
    defaults = {"actual_hours": actual_hours}
    defaults.update(overrides)
    return defaults


# ─── DisposalTicket (PRD §3.9) ──────────────────────────


def create_disposal_ticket_payload(debris_tons: float = 3.5, **overrides) -> dict:
    defaults = {"debris_tons": debris_tons}
    defaults.update(overrides)
    return defaults
