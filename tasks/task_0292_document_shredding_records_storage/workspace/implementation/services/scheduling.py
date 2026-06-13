"""Slot-conflict and on-site buffer conflict checks (PRD §3.3, validations §9-§10)."""
from datetime import datetime, timedelta

from db import db
from errors import err

ONSITE_BUFFER_MINUTES = 30

TERMINAL_ORDER_STATES = {"ON_SITE_SHREDDED", "DESTROYED", "CANCELLED"}


def _parse_dt(value):
    # Accept ISO 8601, tolerate trailing 'Z'.
    s = value
    if isinstance(s, str) and s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def check_slot_conflict(order_id, account_id, container_ids, start, end):
    """ERR_SLOT_CONFLICT: half-open [start,end) overlap with any non-terminal order
    sharing any container. Touching endpoints (a.end == b.start) do NOT overlap."""
    cids = set(container_ids or [])
    if not cids:
        return
    s_new = _parse_dt(start)
    e_new = _parse_dt(end)
    for o in db.service_orders.values():
        if o["id"] == order_id:
            continue
        if o["status"] in TERMINAL_ORDER_STATES:
            continue
        other_cids = set(o.get("container_ids") or [])
        if cids.isdisjoint(other_cids):
            continue
        s_o = _parse_dt(o["scheduled_slot_start"])
        e_o = _parse_dt(o["scheduled_slot_end"])
        # Half-open overlap: s_new < e_o and s_o < e_new.
        if s_new < e_o and s_o < e_new:
            raise err("ERR_SLOT_CONFLICT", "Order window overlaps another order sharing a container")


def check_onsite_buffer_conflict(order_id, location_id, service_mode, start, end):
    """ERR_ONSITE_BUFFER_CONFLICT: two non-terminal ON_SITE orders at the same
    location whose buffered (CLOSED) windows overlap. Buffer = 30 min each side;
    touching buffered endpoints DO conflict."""
    if service_mode != "ON_SITE":
        return
    buf = timedelta(minutes=ONSITE_BUFFER_MINUTES)
    s_new = _parse_dt(start) - buf
    e_new = _parse_dt(end) + buf
    for o in db.service_orders.values():
        if o["id"] == order_id:
            continue
        if o["status"] in TERMINAL_ORDER_STATES:
            continue
        if o["service_mode"] != "ON_SITE":
            continue
        if o["location_id"] != location_id:
            continue
        s_o = _parse_dt(o["scheduled_slot_start"]) - buf
        e_o = _parse_dt(o["scheduled_slot_end"]) + buf
        # Closed overlap: s_new <= e_o and s_o <= e_new.
        if s_new <= e_o and s_o <= e_new:
            raise err("ERR_ONSITE_BUFFER_CONFLICT", "On-site buffered windows overlap at the location")
