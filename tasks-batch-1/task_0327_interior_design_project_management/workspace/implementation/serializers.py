"""Output serialization — exposes exactly the declared entity fields (SCAFFOLD §1.1).

Strips internal bookkeeping (_seq). OrderLine carries only id/created_at plus its
own fields (no updated_at/version) per PRD §2.4.
"""

_COMMON = ["id", "created_at", "updated_at", "version"]

_FIELDS = {
    "client": _COMMON + ["display_name", "email"],
    "project": _COMMON + [
        "client_name", "client_user_id", "brief_summary", "budget_cents",
        "fee_model", "flat_fee_cents", "hourly_rate_cents", "markup_pct",
        "status", "posture", "committed_cents", "design_fee_cents",
        "budget_remaining_cents", "budget_status", "client_credit_cents",
    ],
    "room": _COMMON + [
        "project_id", "name", "scope_note", "room_budget_cents", "status",
        "approved_moodboard_id",
    ],
    "moodboard": _COMMON + ["room_id", "title", "palette", "status"],
    "ffe_item": _COMMON + [
        "sku", "name", "category", "list_unit_cost_cents", "lead_time_days", "active",
    ],
    "selection": _COMMON + [
        "project_id", "room_id", "ffe_item_id", "quantity", "unit_cost_cents",
        "trade_discount_pct", "spec_note", "status", "line_net_cents",
    ],
    "vendor": _COMMON + ["name", "trade", "standing", "lead_time_buffer_days"],
    "order": _COMMON + [
        "project_id", "vendor_id", "window_start", "window_end", "status",
        "order_subtotal_cents", "amount_paid_cents", "balance_due_cents",
        "expected_delivery_at",
    ],
    "order_line": ["id", "created_at", "order_id", "selection_id", "line_net_cents_snapshot"],
    "revision": _COMMON + [
        "project_id", "target_kind", "target_id", "note", "round_no", "status",
    ],
    "punch_item": _COMMON + ["order_id", "description", "severity", "status"],
    "time_entry": _COMMON + [
        "project_id", "designer_user_id", "minutes", "billable", "status",
    ],
    "payment": _COMMON + ["project_id", "amount_cents", "received_at", "memo"],
}


def _ser(kind, record):
    return {f: record.get(f) for f in _FIELDS[kind]}


def client(r):
    return _ser("client", r)


def project(r):
    return _ser("project", r)


def room(r):
    return _ser("room", r)


def moodboard(r):
    return _ser("moodboard", r)


def ffe_item(r):
    return _ser("ffe_item", r)


def selection(r):
    return _ser("selection", r)


def vendor(r):
    return _ser("vendor", r)


def order(r):
    return _ser("order", r)


def order_line(r):
    return _ser("order_line", r)


def revision(r):
    return _ser("revision", r)


def punch_item(r):
    return _ser("punch_item", r)


def time_entry(r):
    return _ser("time_entry", r)


def payment(r):
    return _ser("payment", r)
