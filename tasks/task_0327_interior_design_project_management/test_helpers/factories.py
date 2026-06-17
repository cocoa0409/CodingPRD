"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional fields with server defaults are omitted from
the base payload (per the PRD's "defaults to ..." prose) and only set via override.
"""

DEFAULTS = {
    "CLIENT_NAME": "Acme Residence",
    "BRIEF": "A bright modern loft refresh",
    "ROOM_NAME": "Primary Bedroom",
    "SCOPE_NOTE": "Full refresh of furnishings and lighting",
    "MOODBOARD_TITLE": "Warm Minimal",
    "PALETTE": ["oak", "linen", "brass"],
    "FFE_NAME": "Eames Lounge Chair",
    "VENDOR_NAME": "Heritage Supply Co.",
    "SPEC_NOTE": "Walnut frame, ivory boucle",
}


# ─── Client ──────────────────────────────────────────────
def create_client_payload(**overrides) -> dict:
    """POST /clients — display_name, email (email unique across clients)."""
    payload = {
        "display_name": DEFAULTS["CLIENT_NAME"],
        "email": "client@example.com",
    }
    payload.update(overrides)
    return payload


# ─── Project ─────────────────────────────────────────────
def create_project_payload(client_user_id: str, **overrides) -> dict:
    """POST /projects — defaults to a FLAT fee model; pass fee_model/fee fields to override.

    PRD §3.2 fee-field consistency: each model carries exactly the fee field it requires
    while the other fee fields must be zero ("Any of these fee fields defaults to zero
    when omitted"). The base payload therefore supplies only the FLAT fee field; when the
    caller overrides fee_model to HOURLY or MARKUP it must supply that model's fee field,
    and the FLAT default is dropped so the payload stays internally consistent.
    """
    payload = {
        "client_name": DEFAULTS["CLIENT_NAME"],
        "client_user_id": client_user_id,
        "brief_summary": DEFAULTS["BRIEF"],
        "budget_cents": 100_000_000,
        "fee_model": "FLAT",
        "flat_fee_cents": 100_000,
    }
    # If the caller selects a non-FLAT fee model, drop the FLAT default fee field so the
    # remaining (omitted) fee fields default to zero per the PRD's consistency rule.
    if overrides.get("fee_model", "FLAT") != "FLAT":
        payload.pop("flat_fee_cents", None)
    payload.update(overrides)
    return payload


# ─── Room ────────────────────────────────────────────────
def create_room_payload(**overrides) -> dict:
    """POST /projects/{project_id}/rooms — name, scope_note, room_budget_cents."""
    payload = {
        "name": DEFAULTS["ROOM_NAME"],
        "scope_note": DEFAULTS["SCOPE_NOTE"],
        "room_budget_cents": 0,
    }
    payload.update(overrides)
    return payload


# ─── MoodBoard ───────────────────────────────────────────
def create_moodboard_payload(**overrides) -> dict:
    """POST /rooms/{room_id}/moodboards — title, palette."""
    payload = {
        "title": DEFAULTS["MOODBOARD_TITLE"],
        "palette": list(DEFAULTS["PALETTE"]),
    }
    payload.update(overrides)
    return payload


# ─── FFEItem ─────────────────────────────────────────────
def create_ffe_item_payload(**overrides) -> dict:
    """POST /ffe-items — sku, name, category, list_unit_cost_cents, lead_time_days; active optional."""
    payload = {
        "sku": "FFE-0001",
        "name": DEFAULTS["FFE_NAME"],
        "category": "FURNITURE",
        "list_unit_cost_cents": 20_000,
        "lead_time_days": 1,
    }
    payload.update(overrides)
    return payload


# ─── DesignSelection ─────────────────────────────────────
def create_selection_payload(room_id: str, ffe_item_id: str, **overrides) -> dict:
    """POST /projects/{project_id}/selections — room_id, ffe_item_id, quantity;
    trade_discount_pct and spec_note are optional."""
    payload = {
        "room_id": room_id,
        "ffe_item_id": ffe_item_id,
        "quantity": 1,
        "spec_note": DEFAULTS["SPEC_NOTE"],
    }
    payload.update(overrides)
    return payload


# ─── Vendor ──────────────────────────────────────────────
def create_vendor_payload(**overrides) -> dict:
    """POST /vendors — name, trade; standing and lead_time_buffer_days optional."""
    payload = {
        "name": DEFAULTS["VENDOR_NAME"],
        "trade": "SUPPLIER",
    }
    payload.update(overrides)
    return payload


# ─── ProcurementOrder ────────────────────────────────────
def create_order_payload(vendor_id: str, **overrides) -> dict:
    """POST /projects/{project_id}/orders — vendor_id, window_start, window_end (end > start)."""
    payload = {
        "vendor_id": vendor_id,
        "window_start": "2026-07-01T00:00:00Z",
        "window_end": "2026-07-02T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ─── OrderLine ───────────────────────────────────────────
def add_order_line_payload(selection_id: str, **overrides) -> dict:
    """POST /orders/{order_id}/lines — selection_id."""
    payload = {"selection_id": selection_id}
    payload.update(overrides)
    return payload


# ─── RevisionRequest ─────────────────────────────────────
def create_revision_payload(target_kind: str, target_id: str, **overrides) -> dict:
    """POST /projects/{project_id}/revisions — target_kind, target_id, note."""
    payload = {
        "target_kind": target_kind,
        "target_id": target_id,
        "note": "Please revise the palette",
    }
    payload.update(overrides)
    return payload


# ─── PunchListItem ───────────────────────────────────────
def create_punch_item_payload(**overrides) -> dict:
    """POST /orders/{order_id}/punch-items — description, severity."""
    payload = {
        "description": "Cracked frame on delivery",
        "severity": "MINOR",
    }
    payload.update(overrides)
    return payload


# ─── TimeEntry ───────────────────────────────────────────
def create_time_entry_payload(**overrides) -> dict:
    """POST /projects/{project_id}/time-entries — designer_user_id, minutes; billable optional."""
    payload = {
        "designer_user_id": "designer-op-1",
        "minutes": 60,
    }
    payload.update(overrides)
    return payload


# ─── PaymentReceipt ──────────────────────────────────────
def create_payment_payload(amount_cents: int, expected_project_version: int, **overrides) -> dict:
    """POST /projects/{project_id}/payments — amount_cents, received_at, expected_project_version; memo optional."""
    payload = {
        "amount_cents": amount_cents,
        "received_at": "2026-07-05T00:00:00Z",
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload
