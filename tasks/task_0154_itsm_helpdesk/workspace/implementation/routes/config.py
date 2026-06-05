"""Configuration-catalog routes: categories, SLA policies, assignment groups,
KB articles, assets, and the test-driving clock (PRD §3.1, §3.9)."""
from datetime import datetime, timezone

from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_auth
from response import success_object, success_array
from services import serialize
from services.common import (
    stamp_create,
    touch,
    paginate,
    require_fields,
    require_string,
    sorted_by_created,
    recompute_open_incident_count,
)
from services.sla import group_load_score, group_csat, evaluate_breaches_on_advance

bp = Blueprint("config", __name__)

VALID_PRIORITIES = {"P1", "P2", "P3", "P4"}
VALID_ASSET_KINDS = {"SERVER", "LAPTOP", "NETWORK_DEVICE", "APPLICATION"}

ALL_ROLES = ["PlatformAdmin", "Agent", "ChangeManager", "CabMember", "Requester"]


def _body():
    return request.get_json(silent=True) or {}


# ---------------- Category ----------------

@bp.route("/categories", methods=["POST"])
def create_category():
    require_auth(["PlatformAdmin"])
    body = _body()
    require_fields(body, ["name", "default_priority", "sla_policy_id", "default_assignment_group_id"])
    name = require_string(body, "name")
    default_priority = body["default_priority"]
    if default_priority not in VALID_PRIORITIES:
        raise err("ERR_INVALID_FIELD_VALUE", "default_priority must be one of P1..P4.")
    sla_policy_id = body["sla_policy_id"]
    default_assignment_group_id = body["default_assignment_group_id"]
    # FK existence (PRD §2.5)
    if sla_policy_id not in store.sla_policies:
        raise err("ERR_FK_NOT_FOUND", "sla_policy_id does not resolve.")
    if default_assignment_group_id not in store.assignment_groups:
        raise err("ERR_FK_NOT_FOUND", "default_assignment_group_id does not resolve.")
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise err("ERR_VALIDATION", "active must be a boolean.")
    rec = {
        "name": name,
        "default_priority": default_priority,
        "sla_policy_id": sla_policy_id,
        "default_assignment_group_id": default_assignment_group_id,
        "active": active,
    }
    stamp_create(rec)
    store.categories[rec["id"]] = rec
    return success_object(serialize.category(rec), 201)


@bp.route("/categories/<cid>", methods=["GET"])
def get_category(cid):
    rec = store.categories.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Category not found.")
    return success_object(serialize.category(rec), 200)


@bp.route("/categories", methods=["GET"])
def list_categories():
    items = list(store.categories.values())
    spid = request.args.get("sla_policy_id")
    dagid = request.args.get("default_assignment_group_id")
    if spid is not None:
        items = [c for c in items if c["sla_policy_id"] == spid]
    if dagid is not None:
        items = [c for c in items if c["default_assignment_group_id"] == dagid]
    items = sorted_by_created(items)
    window, limit, offset, total = paginate(items, request.args)
    return success_array([serialize.category(c) for c in window], limit, offset, total)


# ---------------- SlaPolicy ----------------

@bp.route("/sla-policies", methods=["POST"])
def create_sla_policy():
    require_auth(["PlatformAdmin"])
    body = _body()
    require_fields(
        body,
        ["name", "response_target_minutes", "resolve_target_minutes", "ola_target_minutes", "priority_multipliers"],
    )
    name = require_string(body, "name")
    for f in ["response_target_minutes", "resolve_target_minutes", "ola_target_minutes"]:
        if not isinstance(body[f], int) or isinstance(body[f], bool):
            raise err("ERR_VALIDATION", "{} must be an integer.".format(f))
    pm = body["priority_multipliers"]
    if not isinstance(pm, dict):
        raise err("ERR_VALIDATION", "priority_multipliers must be an object.")
    rec = {
        "name": name,
        "response_target_minutes": body["response_target_minutes"],
        "resolve_target_minutes": body["resolve_target_minutes"],
        "ola_target_minutes": body["ola_target_minutes"],
        "priority_multipliers": pm,
    }
    stamp_create(rec)
    store.sla_policies[rec["id"]] = rec
    return success_object(serialize.sla_policy(rec), 201)


@bp.route("/sla-policies/<pid>", methods=["GET"])
def get_sla_policy(pid):
    rec = store.sla_policies.get(pid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "SLA policy not found.")
    return success_object(serialize.sla_policy(rec), 200)


# ---------------- AssignmentGroup ----------------

@bp.route("/assignment-groups", methods=["POST"])
def create_assignment_group():
    require_auth(["PlatformAdmin"])
    body = _body()
    require_fields(body, ["name"])
    name = require_string(body, "name")
    is_fulfilment_group = body.get("is_fulfilment_group", False)
    if not isinstance(is_fulfilment_group, bool):
        raise err("ERR_VALIDATION", "is_fulfilment_group must be a boolean.")
    rec = {
        "name": name,
        "is_fulfilment_group": is_fulfilment_group,
        "queue_depth": 0,
    }
    stamp_create(rec)
    store.assignment_groups[rec["id"]] = rec
    return success_object(serialize.assignment_group(rec), 201)


@bp.route("/assignment-groups/<gid>", methods=["GET"])
def get_assignment_group(gid):
    rec = store.assignment_groups.get(gid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Assignment group not found.")
    return success_object(serialize.assignment_group(rec), 200)


@bp.route("/assignment-groups/<gid>/load", methods=["GET"])
def get_group_load(gid):
    require_auth(["PlatformAdmin", "Agent"])
    rec = store.assignment_groups.get(gid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Assignment group not found.")
    load_score, ticket_count = group_load_score(gid)
    return success_object({"load_score": load_score, "ticket_count": ticket_count}, 200)


@bp.route("/assignment-groups/<gid>/csat", methods=["GET"])
def get_group_csat(gid):
    require_auth(["PlatformAdmin", "Agent"])
    rec = store.assignment_groups.get(gid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Assignment group not found.")
    return success_object(group_csat(gid), 200)


# ---------------- KbArticle ----------------

@bp.route("/kb-articles", methods=["POST"])
def create_kb_article():
    require_auth(["PlatformAdmin", "Agent"])
    body = _body()
    require_fields(body, ["title", "category_id", "body"])
    title = require_string(body, "title")
    article_body = require_string(body, "body")
    category_id = body["category_id"]
    if category_id not in store.categories:
        raise err("ERR_FK_NOT_FOUND", "category_id does not resolve.")
    rec = {
        "title": title,
        "category_id": category_id,
        "body": article_body,
        "view_count": 0,
        "deflection_count": 0,
    }
    stamp_create(rec)
    store.kb_articles[rec["id"]] = rec
    return success_object(serialize.kb_article(rec), 201)


@bp.route("/kb-articles/<aid>", methods=["GET"])
def get_kb_article(aid):
    rec = store.kb_articles.get(aid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "KB article not found.")
    return success_object(serialize.kb_article(rec), 200)


@bp.route("/kb-articles", methods=["GET"])
def list_kb_articles():
    items = list(store.kb_articles.values())
    cid = request.args.get("category_id")
    if cid is not None:
        items = [a for a in items if a["category_id"] == cid]
    items = sorted_by_created(items)
    window, limit, offset, total = paginate(items, request.args)
    return success_array([serialize.kb_article(a) for a in window], limit, offset, total)


# ---------------- Asset ----------------

@bp.route("/assets", methods=["POST"])
def create_asset():
    require_auth(["PlatformAdmin"])
    body = _body()
    require_fields(body, ["asset_tag", "kind"])
    asset_tag = require_string(body, "asset_tag")
    kind = body["kind"]
    if kind not in VALID_ASSET_KINDS:
        raise err("ERR_INVALID_FIELD_VALUE", "kind must be one of SERVER/LAPTOP/NETWORK_DEVICE/APPLICATION.")
    # uniqueness (PRD §3.1)
    for a in store.assets.values():
        if a["asset_tag"] == asset_tag:
            raise err("ERR_DUPLICATE_ASSET_TAG", "asset_tag already exists.")
    rec = {
        "asset_tag": asset_tag,
        "kind": kind,
        "status": "OPERATIONAL",
        "open_incident_count": 0,
    }
    stamp_create(rec)
    store.assets[rec["id"]] = rec
    return success_object(serialize.asset(rec), 201)


@bp.route("/assets/<aid>", methods=["GET"])
def get_asset(aid):
    rec = store.assets.get(aid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Asset not found.")
    return success_object(serialize.asset(rec), 200)


@bp.route("/assets/<aid>/tickets", methods=["GET"])
def list_asset_tickets(aid):
    rec = store.assets.get(aid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Asset not found.")
    items = [t for t in store.tickets.values() if t.get("asset_id") == aid]
    items = sorted_by_created(items)
    window, limit, offset, total = paginate(items, request.args)
    return success_array([serialize.ticket(t) for t in window], limit, offset, total)


@bp.route("/assets/<aid>/retire", methods=["POST"])
def retire_asset(aid):
    require_auth(["PlatformAdmin"])
    rec = store.assets.get(aid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Asset not found.")
    if rec["status"] != "OPERATIONAL":
        raise err("ERR_INVALID_STATE", "Asset must be OPERATIONAL to retire.")
    recompute_open_incident_count(aid)
    if rec["open_incident_count"] > 0:
        raise err("ERR_ASSET_HAS_OPEN_INCIDENTS", "Asset has open incidents.")
    rec["status"] = "RETIRED"
    touch(rec)
    return success_object(serialize.asset(rec), 200)


# ---------------- Test-driving clock ----------------

@bp.route("/_clock/set", methods=["POST"])
def clock_set():
    require_auth(["PlatformAdmin"])
    body = _body()
    require_fields(body, ["to_iso8601"])
    raw = body["to_iso8601"]
    if not isinstance(raw, str):
        raise err("ERR_VALIDATION", "to_iso8601 must be a string.")
    try:
        s = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
    except ValueError:
        raise err("ERR_VALIDATION", "to_iso8601 is not a valid ISO 8601 instant.")
    # Setting the clock does NOT retroactively fire breaches (PRD §2.8).
    store.set_clock(dt)
    from db import iso
    return success_object({"now": iso(store.now())}, 200)


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    require_auth(["PlatformAdmin"])
    body = _body()
    require_fields(body, ["minutes"])
    minutes = body["minutes"]
    if not isinstance(minutes, int) or isinstance(minutes, bool):
        raise err("ERR_VALIDATION", "minutes must be an integer.")
    store.advance_clock(minutes)
    breached = evaluate_breaches_on_advance()
    from db import iso
    return success_object({"now": iso(store.now()), "breached_ticket_ids": breached}, 200)
