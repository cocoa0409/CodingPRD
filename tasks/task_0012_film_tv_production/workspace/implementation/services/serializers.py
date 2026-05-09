"""Resource serializers — produce dicts ready for the response envelope."""
import copy

from db import store
from services.budget import evaluate_posture, category_alert_state


def serialize_production(p, *, derive_posture=True):
    out = copy.deepcopy(p)
    if derive_posture:
        out["posture"] = evaluate_posture(p)
    return out


def serialize_scene(s):
    return copy.deepcopy(s)


def serialize_role(r):
    return copy.deepcopy(r)


def serialize_actor(a):
    return copy.deepcopy(a)


def serialize_audition(a):
    return copy.deepcopy(a)


def serialize_location(l):
    return copy.deepcopy(l)


def serialize_reservation(r):
    return copy.deepcopy(r)


def serialize_budget_category(c):
    out = copy.deepcopy(c)
    out["alert_state"] = category_alert_state(c)
    return out


def serialize_change_order(c):
    return copy.deepcopy(c)


def serialize_equipment(e):
    return copy.deepcopy(e)


def serialize_equipment_event(e):
    return copy.deepcopy(e)


def serialize_crew_assignment(c):
    return copy.deepcopy(c)


def serialize_vendor_invoice(v):
    out = copy.deepcopy(v)
    out["net_cents"] = (out.get("gross_cents", 0) or 0) - (out.get("deduction_cents", 0) or 0)
    return out


def serialize_audit_log(a):
    return copy.deepcopy(a)


def paginate(items, limit, offset):
    """Sort by created_at asc, slice [offset:offset+limit], return (page, total, has_more)."""
    sorted_items = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(sorted_items)
    page = sorted_items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, total, has_more
