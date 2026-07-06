"""Payload factories — one per entity, input fields only.

Every factory covers only `source: input` fields from the PRD entity table.
Optional/defaulted fields (PRD §3.x) are omitted unless the caller overrides.
"""

DEFAULTS = {
    "COMPANY_NAME": "Test Co",
    "PRIMARY_CONTACT_EMAIL": "contact@test.example",
    "SITE_LABEL": "HQ",
    "SITE_ADDRESS": "1 Test Way",
    "TECH_NAME": "Test Tech",
    "TECH_RATE_CENTS": 8000,
    "SEAT_COUNT": 5,
    "PER_SEAT_RATE_CENTS": 5000,
    "SERVICE_TIER": "SILVER",
    "ASSET_TYPE": "LAPTOP",
    "HOSTNAME": "host-1",
    "TICKET_SUBJECT": "test subject",
    "TICKET_PRIORITY": "P3",
    "QUOTE_TITLE": "Test Quote",
    "VALID_UNTIL": "2026-12-31T00:00:00Z",
}


def create_client_payload(**overrides) -> dict:
    """POST /clients: company_name, primary_contact_email, credit_limit_cents (opt)."""
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "primary_contact_email": DEFAULTS["PRIMARY_CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(client_id: str, **overrides) -> dict:
    """POST /sites: client_id, label, address."""
    defaults = {
        "client_id": client_id,
        "label": DEFAULTS["SITE_LABEL"],
        "address": DEFAULTS["SITE_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    """POST /technicians: full_name, hourly_rate_cents, skill_level (opt)."""
    defaults = {
        "full_name": DEFAULTS["TECH_NAME"],
        "hourly_rate_cents": DEFAULTS["TECH_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(client_id: str, **overrides) -> dict:
    """POST /contracts: client_id, service_tier, seat_count, per_seat_rate_cents,
    backup_addon (opt), security_addon (opt)."""
    defaults = {
        "client_id": client_id,
        "service_tier": DEFAULTS["SERVICE_TIER"],
        "seat_count": DEFAULTS["SEAT_COUNT"],
        "per_seat_rate_cents": DEFAULTS["PER_SEAT_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(client_id: str, site_id: str, **overrides) -> dict:
    """POST /assets: client_id, site_id, asset_type, hostname."""
    defaults = {
        "client_id": client_id,
        "site_id": site_id,
        "asset_type": DEFAULTS["ASSET_TYPE"],
        "hostname": DEFAULTS["HOSTNAME"],
    }
    defaults.update(overrides)
    return defaults


def create_patch_job_payload(window_start: str, window_end: str, **overrides) -> dict:
    """POST /assets/{id}/patch-jobs: window_start, window_end, patch_count (opt)."""
    defaults = {
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(client_id: str, contract_id: str, **overrides) -> dict:
    """POST /tickets: client_id, contract_id, priority, subject, asset_id (opt)."""
    defaults = {
        "client_id": client_id,
        "contract_id": contract_id,
        "priority": DEFAULTS["TICKET_PRIORITY"],
        "subject": DEFAULTS["TICKET_SUBJECT"],
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_payload(technician_id: str, mode: str,
                            scheduled_start: str, scheduled_end: str,
                            **overrides) -> dict:
    """POST /tickets/{id}/dispatches: technician_id, mode, scheduled_start,
    scheduled_end, resolves_ticket (opt, default true)."""
    defaults = {
        "technician_id": technician_id,
        "mode": mode,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_seat_adjustment_payload(delta: int, effective_at: str,
                                   expected_contract_version: int,
                                   **overrides) -> dict:
    """POST /contracts/{id}/seat-adjustments: delta, effective_at,
    expected_contract_version, reason (opt)."""
    defaults = {
        "delta": delta,
        "effective_at": effective_at,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(client_id: str, quote_type: str,
                         line_items: list, **overrides) -> dict:
    """POST /quotes: client_id, quote_type, title, line_items, valid_until,
    tax_rate (opt)."""
    defaults = {
        "client_id": client_id,
        "quote_type": quote_type,
        "title": DEFAULTS["QUOTE_TITLE"],
        "line_items": line_items,
        "valid_until": DEFAULTS["VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_procurement_order_payload(client_id: str, line_items: list,
                                     **overrides) -> dict:
    """POST /procurement-orders: client_id, line_items, quote_id (opt),
    tax_rate (opt)."""
    defaults = {
        "client_id": client_id,
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(variant: str) -> dict:
    """POST /contracts/{id}/invoices: variant."""
    return {"variant": variant}
