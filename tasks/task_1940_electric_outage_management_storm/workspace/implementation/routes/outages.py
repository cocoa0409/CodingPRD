"""Outage endpoints: create/get/list, confirm, cancel, merge, report_restored,
verify, and ETR revision list/publish (OCC-guarded)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, parse_iso, iso_ms
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_EVENT_NOT_ACTIVE, ERR_EVENT_CLOSED, ERR_OUTAGE_WORK_OPEN,
    ERR_OUTAGE_CHILDREN_OPEN, ERR_UNVERIFIED_WORK_REMAINS,
    ERR_RESTORE_PING_MISSING, ERR_CROSS_EVENT_LINK, ERR_PARENT_OUTAGE_TERMINAL,
    ERR_MERGE_CYCLE, ERR_STALE_OUTAGE_VERSION, ERR_ETR_IN_PAST,
    ERR_ETR_BACKWARD_FORBIDDEN, ERR_ETR_LOCKED_HORIZON,
    ERR_ETR_EXTENSION_EXCEEDS_CAP,
)
from services.core import (
    get_body, req_string, req_enum, req_int, req_datetime, paginate,
    new_common, new_append, bump,
    get_event, get_feeder, get_outage, serialize_outage, serialize_revision,
    sort_created_asc, etr_provisional, create_etr_revision,
    check_event_not_closed,
    CAUSE_CODES, REVISION_REASONS, TERMINAL_OUTAGE,
    MAX_SINGLE_EXTENSION_MINUTES, PUBLIC_LOCK_MINUTES,
)

bp = Blueprint("outages", __name__)


@bp.route("/om/outages", methods=["POST"])
def create_outage():
    require_roles(["Dispatcher"])
    body = get_body()
    event_id = req_string(body, "storm_event_id")
    feeder_id = req_string(body, "feeder_id")
    event = get_event(event_id)
    get_feeder(feeder_id)

    # Event posture gate: manual creation requires the event ACTIVE.
    if event["event_status"] == "CLOSED":
        raise_err(ERR_EVENT_CLOSED, "Mutations scoped to a CLOSED event are rejected")
    if event["event_status"] != "ACTIVE":
        raise_err(ERR_EVENT_NOT_ACTIVE, "Outage creation requires the event ACTIVE")

    parent_id = body.get("parent_outage_id")
    if parent_id is not None:
        if not isinstance(parent_id, str):
            raise_err(ERR_INVALID_REQUEST, "parent_outage_id must be a string")
        parent = get_outage(parent_id)
        # Referential integrity: same storm event, non-terminal parent.
        if parent["storm_event_id"] != event_id:
            raise_err(ERR_CROSS_EVENT_LINK,
                      "Parent outage belongs to a different storm event")
        if parent["outage_status"] in TERMINAL_OUTAGE:
            raise_err(ERR_PARENT_OUTAGE_TERMINAL,
                      "Parent outage is VERIFIED or CANCELLED")

    o = new_common()
    o.update({
        "storm_event_id": event_id,
        "feeder_id": feeder_id,
        "parent_outage_id": parent_id,
        "outage_status": "SUSPECTED",
        "cause_code": None,
        "customers_affected": None,
        "confirmed_at": None,
        "current_etr": None,
        "restoration_reported_at": None,
        "merged_into_outage_id": None,
    })
    db.outages[o["id"]] = o
    return success_object(serialize_outage(o), status=201)


@bp.route("/om/outages/<oid>", methods=["GET"])
def get_one(oid):
    require_roles(ALL_ROLES)
    o = get_outage(oid)
    return success_object(serialize_outage(o))


@bp.route("/om/outages", methods=["GET"])
def list_outages():
    require_roles(ALL_ROLES)
    items = list(db.outages.values())
    for param in ("storm_event_id", "feeder_id", "parent_outage_id",
                  "merged_into_outage_id", "outage_status"):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o.get(param) == v]
    items = sort_created_asc(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_outage(o) for o in page], limit, offset, total)


@bp.route("/om/outages/<oid>/confirm", methods=["POST"])
def confirm(oid):
    require_roles(["Dispatcher"])
    o = get_outage(oid)
    body = get_body()
    customers = req_int(body, "customers_affected", minimum=1)
    cause = req_enum(body, "cause_code", CAUSE_CODES)

    if o["outage_status"] != "SUSPECTED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Outage in {o['outage_status']} cannot be confirmed")
    event = get_event(o["storm_event_id"])
    check_event_not_closed(event)

    o["outage_status"] = "CONFIRMED"
    o["customers_affected"] = customers
    o["cause_code"] = cause
    o["confirmed_at"] = iso_ms(db.now())
    # Provisional ETR: revision seq 1, reason INITIAL, issued_by 'system'.
    etr = etr_provisional(cause, customers, db.now())
    create_etr_revision(o, "INITIAL", etr, "system")
    # Whole confirmation advances the outage version by exactly one.
    bump(o)
    return success_object(serialize_outage(o))


@bp.route("/om/outages/<oid>/cancel", methods=["POST"])
def cancel(oid):
    require_roles(["Dispatcher"])
    o = get_outage(oid)
    if o["outage_status"] not in ("SUSPECTED", "CONFIRMED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Outage in {o['outage_status']} cannot be cancelled")
    event = get_event(o["storm_event_id"])
    check_event_not_closed(event)
    # Cross-entity gate: no work orders may exist at all.
    for w in db.work_orders.values():
        if w["outage_id"] == oid:
            raise_err(ERR_OUTAGE_WORK_OPEN, "Work orders exist on this outage")
    o["outage_status"] = "CANCELLED"
    # Clustered signals on this outage -> DISMISSED.
    for s in db.trouble_signals.values():
        if s.get("outage_id") == oid and s["disposition"] == "CLUSTERED":
            s["disposition"] = "DISMISSED"
    bump(o)
    return success_object(serialize_outage(o))


def _is_transitive_descendant(candidate_id, ancestor_id):
    """True when candidate_id lies on the parent chain rooted at ancestor_id,
    i.e. candidate is a transitive descendant of ancestor."""
    cur = db.outages.get(candidate_id)
    seen = set()
    while cur is not None:
        pid = cur.get("parent_outage_id")
        if pid is None or pid in seen:
            return False
        if pid == ancestor_id:
            return True
        seen.add(pid)
        cur = db.outages.get(pid)
    return False


@bp.route("/om/outages/<oid>/merge", methods=["POST"])
def merge(oid):
    require_roles(["Dispatcher"])
    o = get_outage(oid)
    body = get_body()
    target_id = req_string(body, "target_outage_id")
    target = get_outage(target_id)

    if o["outage_status"] not in ("SUSPECTED", "CONFIRMED", "ASSESSED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Outage in {o['outage_status']} cannot be merged")
    event = get_event(o["storm_event_id"])
    check_event_not_closed(event)
    # Referential gates: same event; target non-terminal; no cycle.
    if target["storm_event_id"] != o["storm_event_id"]:
        raise_err(ERR_CROSS_EVENT_LINK, "Merge target belongs to a different storm event")
    if target["outage_status"] in TERMINAL_OUTAGE:
        raise_err(ERR_INVALID_STATE_TRANSITION, "Merge target is VERIFIED or CANCELLED")
    if target_id == oid or _is_transitive_descendant(target_id, oid):
        raise_err(ERR_MERGE_CYCLE,
                  "Merge target is the source itself or a transitive descendant")

    source_status = o["outage_status"]
    o["outage_status"] = "CANCELLED"
    o["merged_into_outage_id"] = target_id

    # Re-link clustered signals to the target, keeping disposition CLUSTERED.
    for s in db.trouble_signals.values():
        if s.get("outage_id") == oid:
            s["outage_id"] = target_id

    # Transfer customers when the source had been confirmed.
    if source_status in ("CONFIRMED", "ASSESSED") and o.get("customers_affected"):
        target["customers_affected"] = (target.get("customers_affected") or 0) + o["customers_affected"]

    # Cancel every non-terminal work order on the source; release EN_ROUTE crews.
    for w in db.work_orders.values():
        if w["outage_id"] != oid:
            continue
        if w["execution_status"] in ("COMPLETED", "CANCELLED"):
            continue
        _cancel_work_order_cascade(w)

    # Re-parent child outages onto the target.
    for child in db.outages.values():
        if child.get("parent_outage_id") == oid:
            child["parent_outage_id"] = target_id
            bump(child)

    bump(o)
    bump(target)
    return success_object(serialize_outage(o))


def _cancel_work_order_cascade(w):
    """Work-order cancellation side effects shared by cancel and outage merge:
    release an EN_ROUTE internal crew; cancel REQUESTED/STAGED requisitions
    (STAGED releases its reservation, which is derived from status)."""
    if w.get("assigned_crew_id"):
        crew = db.crews.get(w["assigned_crew_id"])
        if crew is not None and crew["crew_status"] == "EN_ROUTE":
            crew["crew_status"] = "AVAILABLE"
            bump(crew)
        w["assigned_crew_id"] = None
    w["execution_status"] = "CANCELLED"
    bump(w)
    for r in db.material_requisitions.values():
        if r["work_order_id"] == w["id"] and r["requisition_status"] in ("REQUESTED", "STAGED"):
            was_staged = r["requisition_status"] == "STAGED"
            r["requisition_status"] = "CANCELLED"
            bump(r)
            if was_staged:
                stock = db.material_stocks.get(r["material_stock_id"])
                if stock is not None:
                    bump(stock)  # quantity_reserved is derived from STAGED rows


@bp.route("/om/outages/<oid>/report_restored", methods=["POST"])
def report_restored(oid):
    require_roles(["Dispatcher"])
    o = get_outage(oid)
    if o["outage_status"] != "WORKING":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Outage in {o['outage_status']} cannot be reported restored")
    event = get_event(o["storm_event_id"])
    check_event_not_closed(event)
    wos = [w for w in db.work_orders.values() if w["outage_id"] == oid]
    any_completed = False
    for w in wos:
        if w["execution_status"] not in ("COMPLETED", "CANCELLED"):
            raise_err(ERR_OUTAGE_WORK_OPEN, "Non-terminal work orders remain on the outage")
        if w["execution_status"] == "COMPLETED":
            any_completed = True
    if not any_completed:
        raise_err(ERR_OUTAGE_WORK_OPEN, "No work order on this outage has COMPLETED")
    o["outage_status"] = "RESTORED"
    o["restoration_reported_at"] = iso_ms(db.now())
    bump(o)
    # Nested children are NOT touched: they are worked independently.
    return success_object(serialize_outage(o))


@bp.route("/om/outages/<oid>/verify", methods=["POST"])
def verify(oid):
    require_roles(["Dispatcher"])
    o = get_outage(oid)
    if o["outage_status"] != "RESTORED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Outage in {o['outage_status']} cannot be verified")
    event = get_event(o["storm_event_id"])
    check_event_not_closed(event)
    # Children gate.
    for child in db.outages.values():
        if child.get("parent_outage_id") == oid and \
                child["outage_status"] not in ("VERIFIED", "CANCELLED"):
            raise_err(ERR_OUTAGE_CHILDREN_OPEN, "A nested child outage is not VERIFIED/CANCELLED")
    # Work verification gate.
    for w in db.work_orders.values():
        if w["outage_id"] == oid and w["execution_status"] != "CANCELLED":
            if w["verification_status"] != "VERIFY_PASSED":
                raise_err(ERR_UNVERIFIED_WORK_REMAINS,
                          "A non-cancelled work order lacks VERIFY_PASSED")
    # Restore ping gate.
    restored_at = parse_iso(o["restoration_reported_at"])
    ping_ok = False
    for s in db.trouble_signals.values():
        if s.get("outage_id") == oid and s["disposition"] == "CLUSTERED" \
                and s["signal_type"] == "METER_RESTORE_PING":
            if parse_iso(s["occurred_at"]) >= restored_at:
                ping_ok = True
                break
    if not ping_ok:
        raise_err(ERR_RESTORE_PING_MISSING,
                  "No CLUSTERED METER_RESTORE_PING at/after restoration_reported_at")
    o["outage_status"] = "VERIFIED"
    bump(o)
    return success_object(serialize_outage(o))


# ---------------------------------------------------------------------------
# ETR revisions
# ---------------------------------------------------------------------------
@bp.route("/om/outages/<oid>/etr-revisions", methods=["GET"])
def list_revisions(oid):
    require_roles(ALL_ROLES)
    get_outage(oid)
    items = [r for r in db.etr_revisions.values() if r["outage_id"] == oid]
    items.sort(key=lambda r: r["revision_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_revision(r) for r in page], limit, offset, total)


@bp.route("/om/outages/<oid>/etr-revisions", methods=["POST"])
def publish_revision(oid):
    user_id, _ = require_roles(["Dispatcher"])
    o = get_outage(oid)
    body = get_body()
    published = req_datetime(body, "published_etr")
    reason = req_enum(body, "revision_reason", REVISION_REASONS)
    expected = body.get("expected_outage_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_outage_version is required and must be an integer")

    event = get_event(o["storm_event_id"])
    check_event_not_closed(event)
    # Outage must be in a non-terminal, confirmable posture for revision.
    if o["outage_status"] in ("SUSPECTED", "VERIFIED", "CANCELLED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Outage in {o['outage_status']} cannot accept an ETR revision")

    # OCC gate: expected_outage_version vs current version.
    if expected != o["version"]:
        raise_err(ERR_STALE_OUTAGE_VERSION,
                  "expected_outage_version does not match the outage's current version")

    now = db.now()
    cur = parse_iso(o["current_etr"]) if o.get("current_etr") else None

    # Gate 1: the new ETR must lie strictly after the logical now.
    if published <= now:
        raise_err(ERR_ETR_IN_PAST, "published_etr is not after the logical now")

    # Gate 2: backward revision discipline.
    if cur is not None and published < cur:
        missed = now > cur
        if reason != "CORRECTION" or o["outage_status"] not in ("CONFIRMED", "ASSESSED") or missed:
            raise_err(ERR_ETR_BACKWARD_FORBIDDEN,
                      "Backward revision requires reason CORRECTION, outage in CONFIRMED/ASSESSED, and an unmissed ETR")

    # Gate 3: single-extension cap (360 minutes, inclusive), DAMAGE_FOUND uncapped.
    if cur is not None and published > cur:
        delta_min = (published - cur).total_seconds() / 60.0
        if reason != "DAMAGE_FOUND" and delta_min > MAX_SINGLE_EXTENSION_MINUTES:
            raise_err(ERR_ETR_EXTENSION_EXCEEDS_CAP,
                      "Single manual ETR extension exceeds 360 minutes")

    # Gate 4: public-commit lock horizon — now within [cur-30min, cur] inclusive.
    if cur is not None and now <= cur:
        lock_start = cur - timedelta(minutes=PUBLIC_LOCK_MINUTES)
        if lock_start <= now <= cur and reason != "NESTED_DISCOVERED":
            raise_err(ERR_ETR_LOCKED_HORIZON,
                      "Revision inside the 30-minute public-commit lock horizon")

    rev = create_etr_revision(o, reason, published, user_id)
    bump(o)
    return success_object(serialize_revision(rev), status=201)
