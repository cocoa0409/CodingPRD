"""Serialize internal records into API-facing resource dicts.

Field lists trace to the entity tables in scaffold §1.1 / PRD §2.4.
Internal-only keys (those prefixed with '_') are never exposed.
"""

_COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(record, fields):
    return {f: record.get(f) for f in fields}


def venue(r):
    return _pick(r, [
        "id", "name", "settlement_currency", "house_fee_pct", "posture",
        "created_at", "updated_at", "version",
    ])


def show(r):
    return _pick(r, [
        "id", "venue_id", "title", "starts_at", "ends_at",
        "doors_buffer_minutes", "status", "is_private", "ga_sold_count",
        "created_at", "updated_at", "version",
    ])


def section(r):
    return _pick(r, [
        "id", "show_id", "kind", "label", "ga_capacity",
        "created_at", "updated_at", "version",
    ])


def table(r):
    return _pick(r, [
        "id", "section_id", "table_number", "seats", "min_items_per_seat",
        "assigned_server_id", "status",
        "created_at", "updated_at", "version",
    ])


def performer(r):
    return _pick(r, [
        "id", "stage_name", "email", "standard_fee_cents",
        "created_at", "updated_at", "version",
    ])


def lineup_slot(r):
    return _pick(r, [
        "id", "show_id", "performer_id", "slot_order", "role",
        "offered_fee_cents", "agreed_fee_cents", "contract_status",
        "counter_rounds",
        "created_at", "updated_at", "version",
    ])


def tier(r):
    return _pick(r, [
        "id", "show_id", "section_id", "name", "price_cents",
        "min_items_override",
        "created_at", "updated_at", "version",
    ])


def reservation(r):
    return _pick(r, [
        "id", "show_id", "section_id", "tier_id", "table_id", "patron_id",
        "party_size", "is_comp", "booking_status", "settlement_status",
        "ticket_charge_cents", "minimum_due_cents", "items_consumed_cents",
        "refunded_cents",
        "created_at", "updated_at", "version",
    ])


def ticket(r):
    # Immutable: only id + created_at (no updated_at, no version) — PRD §2.4.
    return _pick(r, [
        "id", "reservation_id", "seat_label", "scan_state", "created_at",
    ])


def guest_list_entry(r):
    return _pick(r, [
        "id", "show_id", "host_performer_id", "guest_name", "party_size",
        "minimum_waived", "status", "reservation_id",
        "created_at", "updated_at", "version",
    ])


def server(r):
    return _pick(r, [
        "id", "name", "max_tables", "assigned_table_count",
        "created_at", "updated_at", "version",
    ])


def private_event(r):
    return _pick(r, [
        "id", "show_id", "client_name", "buyout_fee_cents", "deposit_pct",
        "status", "deposit_cents",
        "created_at", "updated_at", "version",
    ])


def settlement(r):
    return _pick(r, [
        "id", "show_id", "status", "gross_ticket_cents", "gross_minimum_cents",
        "buyout_cents", "performer_payout_cents", "house_cut_cents",
        "net_to_venue_cents",
        "created_at", "updated_at", "version",
    ])
