"""PickupEvent and ContaminationTag endpoints."""

from datetime import datetime, time, timedelta, timezone

from flask import Blueprint, request

import db
import response
from db import new_entity, store, touch
from errors import (ERR_PICKUP_LOCKED_BY_WEIGH_TICKET,
                    ERR_PICKUP_NOT_ACTIONABLE, ERR_SEGREGATION_OF_DUTIES,
                    ERR_SKIP_CUTOFF_PASSED, ERR_SKIP_LIMIT_EXCEEDED,
                    ERR_SUBSCRIPTION_NOT_ACTIVE, ERR_TAG_ALREADY_OPEN,
                    ERR_TAG_NOT_RESOLVABLE, ApiError, bad_request, conflict,
                    not_found, unprocessable)
from middleware import auth, own_or_403, require_roles
from services import (CATEGORIES, SEVERITIES, SKIP_CUTOFF_HOURS, by_seq,
                      complete_pickup, confirm_tag, forfeit_pickup_credit,
                      ser_pickup, ser_tag, subscription_of,
                      void_pickup, waive_tag, weigh_ticket_exists)
from utils import (get_body, is_num, paginate, pagination_params,
                   quarter_label)

bp = Blueprint("pickups", __name__)


def _get_pickup_or_404(pid):
    p = store["pickups"].get(pid)
    if p is None:
        not_found("Pickup not found")
    return p


def _pickup_owner(p):
    return subscription_of(p)["subscriber_id"]


# ---------------------------------------------------------------------------
# Pickup reads
# ---------------------------------------------------------------------------
@bp.get("/pickups")
def list_pickups():
    uid, role = auth()
    require_roles(role, "Subscriber", "Driver", "OperationsManager")
    limit, offset = pagination_params()
    items = by_seq(store["pickups"].values())
    if role == "Subscriber":
        items = [p for p in items if _pickup_owner(p) == uid]
    for param, field in (("subscription_id", "subscription_id"),
                         ("route_id", "route_id"),
                         ("collected_bin_id", "collected_bin_id"),
                         ("replacement_bin_id", "replacement_bin_id"),
                         ("status", "status")):
        val = request.args.get(param)
        if val is not None:
            items = [p for p in items if p[field] == val]
    page, total = paginate(items, limit, offset)
    return response.ok_list([ser_pickup(p) for p in page], limit, offset,
                            total)


@bp.get("/pickups/<pid>")
def get_pickup(pid):
    uid, role = auth()
    require_roles(role, "Subscriber", "Driver", "OperationsManager")
    p = _get_pickup_or_404(pid)
    if role == "Subscriber":
        own_or_403(_pickup_owner(p), uid)
    return response.ok(ser_pickup(p))


# ---------------------------------------------------------------------------
# Pickup transitions
# ---------------------------------------------------------------------------
@bp.post("/pickups/<pid>/complete")
def complete(pid):
    _, role = auth()
    require_roles(role, "Driver")
    body = get_body()
    fullness = body.get("fullness_pct")
    if not is_num(fullness) or not (0 <= fullness <= 1):
        bad_request("fullness_pct must be a number between 0 and 1 inclusive")
    p = _get_pickup_or_404(pid)
    if p["status"] != "SCHEDULED":
        conflict(ERR_PICKUP_NOT_ACTIONABLE, "Pickup is not SCHEDULED")
    complete_pickup(p, fullness)
    return response.ok(ser_pickup(p))


@bp.post("/pickups/<pid>/miss")
def miss(pid):
    _, role = auth()
    require_roles(role, "Driver")
    p = _get_pickup_or_404(pid)
    if p["status"] != "SCHEDULED":
        conflict(ERR_PICKUP_NOT_ACTIONABLE, "Pickup is not SCHEDULED")
    p["status"] = "MISSED"
    touch(p)
    return response.ok(ser_pickup(p))


@bp.post("/pickups/<pid>/skip")
def skip(pid):
    uid, role = auth()
    require_roles(role, "Subscriber")
    p = _get_pickup_or_404(pid)
    own_or_403(_pickup_owner(p), uid)
    if p["status"] != "SCHEDULED":
        conflict(ERR_PICKUP_NOT_ACTIONABLE, "Pickup is not SCHEDULED")
    sub = subscription_of(p)
    if sub["service_status"] != "ACTIVE":
        conflict(ERR_SUBSCRIPTION_NOT_ACTIVE,
                 "Subscription is not ACTIVE")
    plan = store["service_plans"][sub["plan_id"]]
    # Lazy quarter reset (calculations.skip_allowance).
    q = quarter_label(db.logical_now().date())
    if sub["current_quarter"] != q:
        sub["current_quarter"] = q
        sub["skips_used_this_quarter"] = 0
        touch(sub)
    if sub["skips_used_this_quarter"] >= plan["skip_allowance_per_quarter"]:
        unprocessable(ERR_SKIP_LIMIT_EXCEEDED,
                      "Quarterly skip allowance exhausted")
    service_midnight = datetime.combine(
        date_from_iso(p["service_date"]), time.min, tzinfo=timezone.utc)
    cutoff = service_midnight - timedelta(hours=SKIP_CUTOFF_HOURS)
    if not db.logical_now() < cutoff:
        unprocessable(ERR_SKIP_CUTOFF_PASSED,
                      "Skip attempted at or after the 48-hour cutoff")
    p["status"] = "SKIPPED"
    touch(p)
    sub["skips_used_this_quarter"] += 1
    touch(sub)
    return response.ok(ser_pickup(p))


def date_from_iso(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


@bp.post("/pickups/<pid>/void")
def void(pid):
    _, role = auth()
    require_roles(role, "OperationsManager")
    p = _get_pickup_or_404(pid)
    if p["status"] != "COMPLETED":
        conflict(ERR_PICKUP_NOT_ACTIONABLE, "Pickup is not COMPLETED")
    void_pickup(p)
    return response.ok(ser_pickup(p))


# ---------------------------------------------------------------------------
# Contamination tags
# ---------------------------------------------------------------------------
@bp.post("/pickups/<pid>/contamination-tags")
def create_tag(pid):
    uid, role = auth()
    require_roles(role, "Driver")
    body = get_body()
    severity = body.get("severity")
    if severity not in SEVERITIES:
        bad_request("severity must be one of LOW, MEDIUM, HIGH")
    category = body.get("category")
    if category not in CATEGORIES:
        bad_request("category must be one of PLASTIC, GLASS, METAL, LIQUIDS, OTHER")
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        bad_request("note must be a string")
    p = _get_pickup_or_404(pid)
    if p["status"] not in ("SCHEDULED", "COMPLETED"):
        conflict(ERR_PICKUP_NOT_ACTIONABLE,
                 "Pickup is not SCHEDULED or COMPLETED")
    for t in store["tags"].values():
        if t["pickup_id"] == pid and t["status"] in ("TAGGED", "DISPUTED"):
            raise ApiError(ERR_TAG_ALREADY_OPEN, 409,
                           "Pickup already has an open contamination tag")
    if p["status"] == "COMPLETED" and weigh_ticket_exists(p["route_id"],
                                                          p["service_date"]):
        raise ApiError(ERR_PICKUP_LOCKED_BY_WEIGH_TICKET, 409,
                       "Weigh ticket already posted for this route and date")
    t = new_entity(common=True)
    t.update({
        "pickup_id": pid, "subscription_id": p["subscription_id"],
        "severity": severity, "category": category, "note": note,
        "tagged_by_driver_id": uid, "status": "TAGGED",
        "surcharge_cents": None, "resolved_by": None, "resolved_at": None,
    })
    store["tags"][t["id"]] = t
    if p["status"] == "SCHEDULED":
        p["status"] = "REJECTED_CONTAMINATION"
        touch(p)
    else:
        forfeit_pickup_credit(p)
    return response.ok(ser_tag(t), code=201)


@bp.get("/contamination-tags")
def list_tags():
    uid, role = auth()
    require_roles(role, "Subscriber", "Driver", "OperationsManager")
    limit, offset = pagination_params()
    items = by_seq(store["tags"].values())
    if role == "Subscriber":
        items = [t for t in items
                 if store["subscriptions"][t["subscription_id"]]["subscriber_id"] == uid]
    for param, field in (("pickup_id", "pickup_id"),
                         ("subscription_id", "subscription_id"),
                         ("status", "status")):
        val = request.args.get(param)
        if val is not None:
            items = [t for t in items if t[field] == val]
    page, total = paginate(items, limit, offset)
    return response.ok_list([ser_tag(t) for t in page], limit, offset, total)


@bp.get("/contamination-tags/<tid>")
def get_tag(tid):
    uid, role = auth()
    require_roles(role, "Subscriber", "Driver", "OperationsManager")
    t = _get_tag_or_404(tid)
    if role == "Subscriber":
        own_or_403(store["subscriptions"][t["subscription_id"]]["subscriber_id"], uid)
    return response.ok(ser_tag(t))


def _get_tag_or_404(tid):
    t = store["tags"].get(tid)
    if t is None:
        not_found("Contamination tag not found")
    return t


@bp.post("/contamination-tags/<tid>/dispute")
def dispute_tag(tid):
    uid, role = auth()
    require_roles(role, "Subscriber")
    t = _get_tag_or_404(tid)
    own_or_403(store["subscriptions"][t["subscription_id"]]["subscriber_id"], uid)
    if t["status"] != "TAGGED":
        conflict(ERR_TAG_NOT_RESOLVABLE, "Tag is not TAGGED")
    t["status"] = "DISPUTED"
    touch(t)
    return response.ok(ser_tag(t))


@bp.post("/contamination-tags/<tid>/confirm")
def confirm(tid):
    uid, role = auth()
    require_roles(role, "OperationsManager")
    t = _get_tag_or_404(tid)
    if t["status"] not in ("TAGGED", "DISPUTED"):
        conflict(ERR_TAG_NOT_RESOLVABLE, "Tag is not TAGGED or DISPUTED")
    if uid == t["tagged_by_driver_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "Resolver must differ from the tagging driver")
    confirm_tag(t, uid)
    return response.ok(ser_tag(t))


@bp.post("/contamination-tags/<tid>/waive")
def waive(tid):
    uid, role = auth()
    require_roles(role, "OperationsManager")
    t = _get_tag_or_404(tid)
    if t["status"] not in ("TAGGED", "DISPUTED"):
        conflict(ERR_TAG_NOT_RESOLVABLE, "Tag is not TAGGED or DISPUTED")
    if uid == t["tagged_by_driver_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "Resolver must differ from the tagging driver")
    waive_tag(t, uid)
    return response.ok(ser_tag(t))
