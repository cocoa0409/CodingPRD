"""Shared helpers: request body field extraction (deferred shape validation),
pagination, FK existence, derived-value recomputation, and cascade machinery.

Validation gate order (PRD §2.6): auth -> authz -> existence -> state ->
business gates (5..25) -> request shape (26). Shape errors are therefore
collected during extraction and only raised after all earlier gates pass;
business gates skip checks whose inputs failed to parse.
"""
from decimal import Decimal

from flask import request

import errors as E
from db import store, touch, now
from errors import ApiError
from util import parse_dt, is_num, is_int, iso_week_key, intervals_overlap

D0 = Decimal("0.0")
D1 = Decimal("0.1")


# --------------------------------------------------------------------------
# Request body / field extraction
# --------------------------------------------------------------------------

def body_json():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


class FieldSet:
    """Extracts typed fields from the request body. Missing/ill-typed required
    fields mark the set bad; the caller raises ERR_INVALID_REQUEST only after
    all earlier-priority gates have passed (gate 26)."""

    def __init__(self):
        self.body = body_json()
        self.bad = False

    def _get(self, name):
        return self.body.get(name)

    def req_str(self, name):
        v = self._get(name)
        if not isinstance(v, str) or v == "":
            self.bad = True
            return None
        return v

    def opt_str(self, name, default=None):
        if name not in self.body:
            return default
        v = self.body[name]
        if not isinstance(v, str):
            self.bad = True
            return default
        return v

    def req_num(self, name):
        v = self._get(name)
        if not is_num(v):
            self.bad = True
            return None
        return v

    def opt_num(self, name, default=None):
        if name not in self.body or self.body[name] is None:
            return default
        v = self.body[name]
        if not is_num(v):
            self.bad = True
            return default
        return v

    def req_int(self, name):
        v = self._get(name)
        if not is_int(v):
            self.bad = True
            return None
        return v

    def req_bool(self, name):
        v = self._get(name)
        if not isinstance(v, bool):
            self.bad = True
            return None
        return v

    def opt_bool(self, name, default=None):
        if name not in self.body or self.body[name] is None:
            return default
        v = self.body[name]
        if not isinstance(v, bool):
            self.bad = True
            return default
        return v

    def req_dt(self, name):
        v = self._get(name)
        dt = parse_dt(v)
        if dt is None:
            self.bad = True
        return dt

    def req_enum(self, name, allowed):
        v = self._get(name)
        if not isinstance(v, str) or v not in allowed:
            self.bad = True
            return None
        return v

    def raise_if_bad(self, msg="Request body failed validation"):
        if self.bad:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, msg)


def pagination_params():
    """limit (default 10, min 1, max 100), offset (default 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit, offset = 10, 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "limit must be an integer")
        limit = max(1, min(100, limit))
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(records, filters=None):
    """Filter (exact match), sort by created_at ascending (stable via _seq),
    then slice. Returns (page_records, limit, offset, total_count)."""
    limit, offset = pagination_params()
    items = list(records)
    if filters:
        for key, val in filters.items():
            if val is None:
                continue
            items = [r for r in items if r.get(key) == val]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


# --------------------------------------------------------------------------
# Existence helpers (gate 3)
# --------------------------------------------------------------------------

def get_or_404(table, rid, label="Resource"):
    rec = table.get(rid)
    if rec is None:
        raise ApiError(E.ERR_NOT_FOUND, 404, "%s %s does not exist" % (label, rid))
    return rec


def fk_or_404(table, value, label):
    """Body-FK existence check; skipped when the value failed extraction
    (shape gate 26 will report it later)."""
    if value is None:
        return None
    if not isinstance(value, str) or value not in table:
        raise ApiError(E.ERR_NOT_FOUND, 404, "%s %s does not exist" % (label, value))
    return table[value]


# --------------------------------------------------------------------------
# Lookup helpers
# --------------------------------------------------------------------------

def events_of_offer(offer_id):
    return [e for e in store.events.values() if e["surplus_offer_id"] == offer_id]


def assignments_of_event(event_id):
    return [a for a in store.assignments.values() if a["glean_event_id"] == event_id]


def lots_of_event(event_id):
    return [l for l in store.lots.values() if l["glean_event_id"] == event_id]


def distributions_of_event(event_id):
    return [d for d in store.distributions.values() if d["glean_event_id"] == event_id]


def incidents_of_event(event_id):
    return [i for i in store.incidents.values() if i["glean_event_id"] == event_id]


def offer_of_event(ev):
    return store.offers.get(ev["surplus_offer_id"])


# --------------------------------------------------------------------------
# Derived-value recomputation (each returns True when a stored value changed;
# callers decide whether to touch() — one version bump per resource per request)
# --------------------------------------------------------------------------

def dsum(values):
    total = D0
    for v in values:
        total += v
    return total.quantize(D1)


def recompute_event_totals(ev):
    """calculations.actual_poundage + undistributed. total_distributed_lbs sums
    SCHEDULED planned_lbs and DELIVERED delivered_lbs per the entity field def."""
    eid = ev["id"]
    total_h = dsum(l["net_lbs"] for l in lots_of_event(eid) if l["status"] == "VERIFIED")
    td = D0
    for d in distributions_of_event(eid):
        if d["status"] == "SCHEDULED":
            td += d["planned_lbs"]
        elif d["status"] == "DELIVERED":
            td += d["delivered_lbs"]
    total_d = td.quantize(D1)
    wasted = dsum(i["condemned_lbs"] for i in incidents_of_event(eid)
                  if i["disposition"].startswith("RESOLVED_"))
    undist = (total_h - total_d - wasted).quantize(D1)
    changed = (ev["total_harvested_lbs"] != total_h
               or ev["total_distributed_lbs"] != total_d
               or ev["undistributed_lbs"] != undist)
    ev["total_harvested_lbs"] = total_h
    ev["total_distributed_lbs"] = total_d
    ev["undistributed_lbs"] = undist
    return changed


def recompute_offer_actual(offer):
    actual = dsum(ev["total_harvested_lbs"] for ev in events_of_offer(offer["id"]))
    changed = offer["actual_lbs"] != actual
    offer["actual_lbs"] = actual
    return changed


def recompute_crew(ev):
    """calculations.crew_fill_projection: count CONFIRMED; OPEN->FULL at
    capacity, FULL->OPEN when below."""
    cnt = sum(1 for a in assignments_of_event(ev["id"]) if a["status"] == "CONFIRMED")
    changed = ev["crew_confirmed_count"] != cnt
    ev["crew_confirmed_count"] = cnt
    if ev["status"] == "OPEN" and cnt >= ev["crew_capacity"]:
        ev["status"] = "FULL"
        changed = True
    elif ev["status"] == "FULL" and cnt < ev["crew_capacity"]:
        ev["status"] = "OPEN"
        changed = True
    return changed


def agency_week_committed(agency_id, week_key):
    """calculations.agency_capacity_check committed total for one ISO week."""
    total = D0
    for d in store.distributions.values():
        if d["agency_id"] != agency_id:
            continue
        if iso_week_key(d["delivery_date"]) != week_key:
            continue
        if d["status"] == "SCHEDULED":
            total += d["planned_lbs"]
        elif d["status"] in ("DELIVERED", "SHORTFALL"):
            total += d["delivered_lbs"]
    return total.quantize(D1)


def agency_current_week_committed(agency_id):
    """Agency.current_week_committed_lbs: ISO week containing the logical clock."""
    return agency_week_committed(agency_id, iso_week_key(now()))


def refresh_agency_committed(agency):
    val = agency_current_week_committed(agency["id"])
    if agency["current_week_committed_lbs"] != val:
        agency["current_week_committed_lbs"] = val
        touch(agency)


def reeval_offer_gleaned(offer):
    """SCHEDULED -> GLEANED when no event remains in {DRAFT, OPEN, FULL,
    IN_PROGRESS} and at least one reached HARVESTED. Returns True on transition."""
    if offer["status"] != "SCHEDULED":
        return False
    events = events_of_offer(offer["id"])
    if not events:
        return False
    if any(e["status"] in ("DRAFT", "OPEN", "FULL", "IN_PROGRESS") for e in events):
        return False
    if not any(e["status"] in ("HARVESTED", "RECONCILED") for e in events):
        return False
    offer["status"] = "GLEANED"
    recompute_offer_actual(offer)
    touch(offer)
    return True


def cascade_event_cancel(ev):
    """Cancel a DRAFT/OPEN event: decline PENDING/CONFIRMED assignments,
    release vehicle (OPEN events hold it ASSIGNED), release containers."""
    for a in assignments_of_event(ev["id"]):
        if a["status"] in ("PENDING", "CONFIRMED"):
            a["status"] = "DECLINED"
            touch(a)
    ev["crew_confirmed_count"] = 0
    if ev["status"] == "OPEN":
        vehicle = store.vehicles.get(ev["assigned_vehicle_id"])
        if vehicle is not None and vehicle["status"] == "ASSIGNED":
            vehicle["status"] = "AVAILABLE"
            touch(vehicle)
    for lot in lots_of_event(ev["id"]):
        if lot["status"] == "VERIFIED":
            c = store.containers.get(lot["container_id"])
            if c is not None and c["status"] == "IN_USE":
                c["status"] = "AVAILABLE"
                touch(c)
    ev["status"] = "CANCELLED"
    touch(ev)


def container_in_use_by_event(container_id, event_id):
    for lot in lots_of_event(event_id):
        if lot["container_id"] == container_id and lot["status"] == "VERIFIED":
            return True
    return False


def vehicle_schedule_conflict(vehicle_id, start, end, exclude_event_id=None):
    """Vehicle already sits on an event in {OPEN, FULL, IN_PROGRESS, HARVESTED}
    whose half-open schedule overlaps (adjacency permitted)."""
    if start is None or end is None:
        return False
    for e in store.events.values():
        if e["id"] == exclude_event_id:
            continue
        if e["assigned_vehicle_id"] != vehicle_id:
            continue
        if e["status"] not in ("OPEN", "FULL", "IN_PROGRESS", "HARVESTED"):
            continue
        if intervals_overlap(start, end, e["scheduled_start"], e["scheduled_end"]):
            return True
    return False


def volunteer_double_booked(volunteer_id, event, exclude_assignment_id=None):
    """CONFIRMED assignments of this volunteer on other events whose half-open
    schedules overlap the given event's."""
    for a in store.assignments.values():
        if a["id"] == exclude_assignment_id:
            continue
        if a["volunteer_id"] != volunteer_id or a["status"] != "CONFIRMED":
            continue
        other = store.events.get(a["glean_event_id"])
        if other is None:
            continue
        if intervals_overlap(event["scheduled_start"], event["scheduled_end"],
                             other["scheduled_start"], other["scheduled_end"]):
            return True
    return False


def has_valid_waiver(volunteer_id, event_id):
    for w in store.waivers.values():
        if (w["volunteer_id"] == volunteer_id
                and w["glean_event_id"] == event_id
                and w["witness_volunteer_id"] != volunteer_id):
            return True
    return False


def event_available_lbs(ev):
    """calculations.event_allocation_feasibility."""
    avail = ev["total_harvested_lbs"]
    for d in distributions_of_event(ev["id"]):
        if d["status"] == "SCHEDULED":
            avail -= d["planned_lbs"]
        elif d["status"] in ("DELIVERED", "SHORTFALL"):
            avail -= d["delivered_lbs"]
    for i in incidents_of_event(ev["id"]):
        if i["disposition"].startswith("RESOLVED_"):
            avail -= i["condemned_lbs"]
    return avail.quantize(D1)


def breach_logs_in_delivery_window(ev):
    """Breach TempLogs of the event with recorded_at >= the HARVESTED instant
    (the window between event HARVESTED and a distribution's delivery)."""
    harvested_at = ev.get("_harvested_at")
    out = []
    for t in store.templogs.values():
        if t["glean_event_id"] != ev["id"] or not t["breach_flag"]:
            continue
        if harvested_at is not None and t["recorded_at"] >= harvested_at:
            out.append(t)
    return out


def compute_cold_chain_intact(ev):
    return len(breach_logs_in_delivery_window(ev)) == 0
