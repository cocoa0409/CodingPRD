"""Distribution event endpoints and the completion cascade (PRD §3.5)."""

from flask import request

from db import store, base_fields, touch, now
from errors import (ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_EVENT_STATE,
                    ERR_AGENCY_NOT_ACTIVE, ERR_EVENT_ALREADY_ENDED,
                    ERR_SITE_SCHEDULE_CONFLICT, ERR_EVENT_NOT_OPEN,
                    ERR_PRIVACY_RESTRICTED, ERR_HOUSEHOLD_NOT_ELIGIBLE,
                    ERR_DUPLICATE_HOUSEHOLD_ISSUANCE,
                    ERR_NO_PUBLISHED_ALLOCATION, ERR_ALLOCATION_EXCEEDED,
                    ERR_INSUFFICIENT_STOCK, ERR_ALLOTMENT_EXCEEDED, raise_err)
from middleware import authenticate, require_role, forbid
from response import success_object, get_body, paginate
from serialize import event_json, issuance_json
from services import calc
from validate import req_str, parse_datetime, req_quantity_lines
from . import make_blueprint

bp = make_blueprint("events")

EVENT_ROLES = ["BankAdmin", "AgencyCoordinator"]
READ_ROLES = ["BankAdmin", "AgencyCoordinator", "WarehouseManager"]
ISSUANCE_READ_ROLES = ["BankAdmin", "AgencyCoordinator", "PrivacyOfficer"]


def _get_event_or_404(event_id):
    ev = store.distribution_events.get(event_id)
    if ev is None:
        raise_err(ERR_NOT_FOUND, "Distribution event not found.")
    return ev


def _scope_event(uid, role, ev):
    """AgencyCoordinator may only touch events their agency hosts (PRD §2.1)."""
    if role == "AgencyCoordinator" and ev["host_agency_id"] != uid:
        forbid()


@bp.route("/distribution-events", methods=["POST"])
def create_event():
    uid, role = authenticate()
    require_role(role, EVENT_ROLES)
    body = get_body()
    host_id = body.get("host_agency_id")
    if role == "AgencyCoordinator" and host_id != uid:
        forbid()
    site = req_str(body, "site_name")
    starts = parse_datetime(body.get("starts_at"), "starts_at")
    ends = parse_datetime(body.get("ends_at"), "ends_at")
    if not isinstance(host_id, str) or host_id not in store.partner_agencies:
        raise_err(ERR_VALIDATION, "host_agency_id must reference an existing agency.")
    # Half-open single-booking rule (category 6) precedes the start<end
    # body rule (category 10): [starts, ends) vs existing non-terminal events
    # at the same site; mere adjacency is allowed.
    for other in store.distribution_events.values():
        if other["site_name"] != site:
            continue
        if other["status"] not in ("SCHEDULED", "OPEN", "LOCKED"):
            continue
        if starts < other["ends_at"] and other["starts_at"] < ends:
            raise_err(ERR_SITE_SCHEDULE_CONFLICT,
                      "Window intersects an existing event at this site.")
    if not (starts < ends):
        raise_err(ERR_VALIDATION, "starts_at must be before ends_at.")
    ev = base_fields()
    ev.update({
        "host_agency_id": host_id,
        "site_name": site,
        "starts_at": starts,
        "ends_at": ends,
        "status": "SCHEDULED",
        "completed_at": None,
    })
    store.distribution_events[ev["id"]] = ev
    return success_object(event_json(ev), status=201)


@bp.route("/distribution-events", methods=["GET"])
def list_events():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    host = request.args.get("host_agency_id")
    site = request.args.get("site_name")
    status = request.args.get("status")
    items = [ev for ev in store.distribution_events.values()
             if (host is None or ev["host_agency_id"] == host)
             and (site is None or ev["site_name"] == site)
             and (status is None or ev["status"] == status)]
    items.sort(key=lambda ev: ev["created_at"])
    return paginate([event_json(ev) for ev in items])


@bp.route("/distribution-events/<event_id>", methods=["GET"])
def get_event(event_id):
    uid, role = authenticate()
    require_role(role, READ_ROLES)
    ev = _get_event_or_404(event_id)
    _scope_event(uid, role, ev)
    return success_object(event_json(ev))


@bp.route("/distribution-events/<event_id>/open", methods=["POST"])
def open_event(event_id):
    uid, role = authenticate()
    require_role(role, EVENT_ROLES)
    ev = _get_event_or_404(event_id)
    _scope_event(uid, role, ev)
    if ev["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_EVENT_STATE, "Only a SCHEDULED event can be opened.")
    agency = store.partner_agencies.get(ev["host_agency_id"])
    if agency is None or agency["status"] != "ACTIVE":
        raise_err(ERR_AGENCY_NOT_ACTIVE, "The host agency is not ACTIVE.")
    if not (now() < ev["ends_at"]):
        raise_err(ERR_EVENT_ALREADY_ENDED,
                  "The event's window has already ended.")
    ev["status"] = "OPEN"
    touch(ev)
    return success_object(event_json(ev))


@bp.route("/distribution-events/<event_id>/lock", methods=["POST"])
def lock_event(event_id):
    uid, role = authenticate()
    require_role(role, EVENT_ROLES)
    ev = _get_event_or_404(event_id)
    _scope_event(uid, role, ev)
    if ev["status"] != "OPEN":
        raise_err(ERR_INVALID_EVENT_STATE, "Only an OPEN event can be locked.")
    ev["status"] = "LOCKED"
    touch(ev)
    return success_object(event_json(ev))


@bp.route("/distribution-events/<event_id>/unlock", methods=["POST"])
def unlock_event(event_id):
    uid, role = authenticate()
    require_role(role, EVENT_ROLES)
    ev = _get_event_or_404(event_id)
    _scope_event(uid, role, ev)
    if ev["status"] != "LOCKED":
        raise_err(ERR_INVALID_EVENT_STATE, "Only a LOCKED event can be unlocked.")
    ev["status"] = "OPEN"
    touch(ev)
    return success_object(event_json(ev))


@bp.route("/distribution-events/<event_id>/complete", methods=["POST"])
def complete_event(event_id):
    uid, role = authenticate()
    require_role(role, EVENT_ROLES)
    ev = _get_event_or_404(event_id)
    _scope_event(uid, role, ev)
    if ev["status"] != "LOCKED":
        raise_err(ERR_INVALID_EVENT_STATE, "Only a LOCKED event can be completed.")
    inv = store.inventory
    clock = now()
    touched_lines = {}
    # Hop 1: every RECORDED issuance transitions to FULFILLED.
    fulfilled = [i for i in store.issuances.values()
                 if i["event_id"] == ev["id"] and i["status"] == "RECORDED"]
    fulfilled.sort(key=lambda i: i["created_at"])
    for i in fulfilled:
        i["status"] = "FULFILLED"
        i["fulfilled_at"] = clock
        touch(i)
    # Hop 2: per fulfilled line, debit on_hand and reserved by the same
    # quantity (reservation consumed; available unchanged), and credit the
    # allocation line selected by (clock month, PUBLISHED run, host, size).
    for i in fulfilled:
        for ln in i["lines"]:
            size, qty = ln["size_code"], ln["quantity"]
            if inv is not None:
                inv["sizes"][size]["on_hand_units"] -= qty
                inv["sizes"][size]["reserved_units"] -= qty
            line = calc.find_active_line(ev["host_agency_id"], size)
            if line is not None:
                calc.credit_line(line, qty)
                touched_lines[line["id"]] = line
    for line in touched_lines.values():
        touch(line)
    # Hop 3: a run whose lines all reached FULFILLED auto-finalizes.
    for run_id in {ln["allocation_run_id"] for ln in touched_lines.values()}:
        calc.maybe_auto_finalize_run(run_id)
    ev["status"] = "COMPLETED"
    ev["completed_at"] = clock
    touch(ev)
    if inv is not None:
        touch(inv)
    return success_object(event_json(ev))


@bp.route("/distribution-events/<event_id>/cancel", methods=["POST"])
def cancel_event(event_id):
    uid, role = authenticate()
    require_role(role, EVENT_ROLES)
    ev = _get_event_or_404(event_id)
    _scope_event(uid, role, ev)
    if ev["status"] not in ("SCHEDULED", "OPEN"):
        raise_err(ERR_INVALID_EVENT_STATE,
                  "Only a SCHEDULED or OPEN event can be cancelled.")
    if ev["status"] == "OPEN":
        # Auto-void RECORDED issuances; stock moves only on fulfillment.
        for i in store.issuances.values():
            if i["event_id"] == ev["id"] and i["status"] == "RECORDED":
                i["status"] = "VOIDED"
                touch(i)
    ev["status"] = "CANCELLED"
    touch(ev)
    return success_object(event_json(ev))


@bp.route("/distribution-events/<event_id>/issuances", methods=["POST"])
def record_issuance(event_id):
    uid, role = authenticate()
    require_role(role, ["AgencyCoordinator", "PrivacyOfficer"])
    ev = _get_event_or_404(event_id)
    _scope_event(uid, role, ev)
    # State gate (category 4).
    if ev["status"] != "OPEN":
        raise_err(ERR_EVENT_NOT_OPEN, "Issuances may be recorded only while OPEN.")
    body = get_body()
    household_id = body.get("household_id")
    if not isinstance(household_id, str) or household_id not in store.households:
        raise_err(ERR_VALIDATION, "household_id must reference an existing household.")
    h = store.households[household_id]
    # Safety gates (category 5): privacy wall, then eligibility.
    if h["privacy_restricted"] and role != "PrivacyOfficer":
        raise_err(ERR_PRIVACY_RESTRICTED,
                  "Only a PrivacyOfficer may record for this household.")
    if h["eligibility_status"] != "ELIGIBLE":
        raise_err(ERR_HOUSEHOLD_NOT_ELIGIBLE,
                  "Household is not currently ELIGIBLE.")
    # Uniqueness (category 6): one live issuance per household per event.
    for i in store.issuances.values():
        if (i["event_id"] == ev["id"] and i["household_id"] == h["id"]
                and i["status"] in ("RECORDED", "FULFILLED")):
            raise_err(ERR_DUPLICATE_HOUSEHOLD_ISSUANCE,
                      "Household already has an issuance at this event.")
    lines = req_quantity_lines(body, "lines")
    # Fiscal chain (category 9) in its declared order: allocation existence,
    # allocation sufficiency, stock sufficiency, then household allotment.
    matched = []
    for ln in lines:
        line = calc.find_active_line(ev["host_agency_id"], ln["size_code"])
        if line is None:
            raise_err(ERR_NO_PUBLISHED_ALLOCATION,
                      "No PUBLISHED allocation line for this month, agency, "
                      "and size %s." % ln["size_code"])
        matched.append((ln, line))
    for ln, line in matched:
        if ln["quantity"] > line["allocated_units"] - line["fulfilled_units"]:
            raise_err(ERR_ALLOCATION_EXCEEDED,
                      "Quantity exceeds the line's unfulfilled remainder for %s."
                      % ln["size_code"])
    inv = store.inventory
    for ln, _line in matched:
        on_hand = inv["sizes"][ln["size_code"]]["on_hand_units"] if inv is not None else 0
        if ln["quantity"] > on_hand:
            raise_err(ERR_INSUFFICIENT_STOCK,
                      "Quantity exceeds on-hand stock for %s." % ln["size_code"])
    requested_total = sum(ln["quantity"] for ln in lines)
    if requested_total > calc.household_remaining(h):
        raise_err(ERR_ALLOTMENT_EXCEEDED,
                  "Requested total exceeds the household's remaining monthly "
                  "allotment.")
    i = base_fields()
    i.update({
        "event_id": ev["id"],
        "household_id": h["id"],
        "lines": lines,
        "total_units": requested_total,
        "status": "RECORDED",
        "fulfilled_at": None,
        "recorded_by_role": role,
    })
    store.issuances[i["id"]] = i
    return success_object(issuance_json(i), status=201)


@bp.route("/distribution-events/<event_id>/issuances", methods=["GET"])
def list_event_issuances(event_id):
    uid, role = authenticate()
    require_role(role, ISSUANCE_READ_ROLES)
    ev = _get_event_or_404(event_id)
    _scope_event(uid, role, ev)
    items = [i for i in store.issuances.values() if i["event_id"] == ev["id"]]
    items.sort(key=lambda i: i["created_at"])
    return paginate([issuance_json(i) for i in items])
