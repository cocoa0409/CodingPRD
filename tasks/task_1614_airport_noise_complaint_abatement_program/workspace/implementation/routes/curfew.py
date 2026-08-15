"""Curfew rules (PRD §3.2)."""
from flask import Blueprint, request

from db import db, new_id
from errors import err
from middleware import get_caller, require_role, get_body
from response import success_object, success_list
from serialize import ser_curfew_rule
from services import touch
from util import now
from validate import validate, parse_pagination

bp = Blueprint("curfew", __name__)

STAFF = ["NoiseOfficeAdmin", "NoiseAnalyst", "CommunityLiaison",
         "StudyCoordinator", "BoardMember"]

SEASONS = ["SUMMER", "WINTER", "YEAR_ROUND"]
APPLIES = ["ARRIVAL", "DEPARTURE", "BOTH"]


def _seasons_intersect(a, b):
    return a == b or a == "YEAR_ROUND" or b == "YEAR_ROUND"


def _applies_intersect(a, b):
    return a == b or a == "BOTH" or b == "BOTH"


def _get_rule(rid):
    r = db.curfew_rules.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", f"CurfewRule {rid} not found")
    return r


@bp.post("/curfew-rules")
def create_rule():
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("runway_code", "str", True),
        ("season", "enum", True, {"enum": SEASONS}),
        ("window_start_minute", "int", True, {"min": 0, "max": 1439}),
        ("window_end_minute", "int", True, {"min": 0, "max": 1439}),
        ("applies_to", "enum", True, {"enum": APPLIES}),
        ("grace_minutes", "int", False, {"min": 0}),
        ("effective_from", "date", True),
        ("effective_to", "date", True),
    ])
    if data["window_end_minute"] <= data["window_start_minute"]:
        raise err("ERR_VALIDATION",
                  "window_end_minute must be strictly after window_start_minute")
    if data["effective_to"] < data["effective_from"]:
        raise err("ERR_VALIDATION",
                  "effective_to must be on or after effective_from")
    require_role(caller, ["NoiseOfficeAdmin"])
    for r in db.curfew_rules.values():
        if r["status"] != "ACTIVE":
            continue
        if r["runway_code"] != data["runway_code"]:
            continue
        if not _seasons_intersect(r["season"], data["season"]):
            continue
        if not _applies_intersect(r["applies_to"], data["applies_to"]):
            continue
        if not (r["effective_from"] <= data["effective_to"]
                and data["effective_from"] <= r["effective_to"]):
            continue
        # closed minute intervals: touching boundaries conflict
        if (r["window_start_minute"] <= data["window_end_minute"]
                and data["window_start_minute"] <= r["window_end_minute"]):
            raise err("ERR_CURFEW_WINDOW_OVERLAP",
                      "Curfew window conflicts with an existing ACTIVE rule")
    t = now()
    r = {
        "id": new_id(),
        "runway_code": data["runway_code"],
        "season": data["season"],
        "window_start_minute": data["window_start_minute"],
        "window_end_minute": data["window_end_minute"],
        "applies_to": data["applies_to"],
        "grace_minutes": data.get("grace_minutes", 15),
        "effective_from": data["effective_from"],
        "effective_to": data["effective_to"],
        "status": "ACTIVE",
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.curfew_rules[r["id"]] = r
    return success_object(ser_curfew_rule(r), status=201)


@bp.get("/curfew-rules")
def list_rules():
    caller = get_caller()
    require_role(caller, STAFF)
    limit, offset = parse_pagination(request.args)
    runway = request.args.get("runway_code")
    season = request.args.get("season")
    status = request.args.get("status")
    items = sorted(db.curfew_rules.values(), key=lambda r: r["created_at"])
    if runway is not None:
        items = [r for r in items if r["runway_code"] == runway]
    if season is not None:
        items = [r for r in items if r["season"] == season]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_curfew_rule(r) for r in page], limit, offset, total)


@bp.get("/curfew-rules/<curfewRuleId>")
def get_rule(curfewRuleId):
    caller = get_caller()
    require_role(caller, STAFF)
    r = _get_rule(curfewRuleId)
    return success_object(ser_curfew_rule(r))


@bp.post("/curfew-rules/<curfewRuleId>/suspend")
def suspend_rule(curfewRuleId):
    caller = get_caller()
    get_body()
    require_role(caller, ["NoiseOfficeAdmin"])
    r = _get_rule(curfewRuleId)
    if r["status"] != "ACTIVE":
        raise err("ERR_INVALID_CURFEW_RULE_STATE",
                  "Only an ACTIVE curfew rule can be suspended")
    r["status"] = "SUSPENDED"
    touch(r)
    return success_object(ser_curfew_rule(r))
