"""VOC rule endpoints with half-open window overlap enforcement."""
from datetime import datetime, timezone

from flask import Blueprint, request

from .domain import PRODUCT_CATEGORIES, ser_voc_rule
from .errors import bad_request, conflict, invalid_state, not_found
from .store import store
from .util import (
    auth,
    body,
    list_response,
    new_record,
    parse_datetime_value,
    success,
    touch,
    v_enum,
    v_num,
    v_state_code,
)

bp = Blueprint("voc_rules", __name__)

ALL = ("PlantManager", "LabTechnician", "ProductionOperator", "QCInspector", "RegulatoryClerk", "Dealer")
FAR_FUTURE = datetime(9999, 12, 31, tzinfo=timezone.utc).date()


def _window(rec):
    start = rec["_from_d"]
    end = rec["_to_d"] if rec["_to_d"] is not None else FAR_FUTURE
    return start, end


def _intersects(a_from, a_to, b_from, b_to):
    """Half-open [from, to) intersection; adjacency allowed."""
    return a_from < b_to and b_from < a_to


@bp.post("/coatings/voc-rules")
def create_voc_rule():
    auth(("RegulatoryClerk",))
    b = body()
    category = v_enum(b, "category", PRODUCT_CATEGORIES)
    state_code = v_state_code(b, "state_code", allow_wildcard=True)
    max_voc_gpl = v_num(b, "max_voc_gpl", minv=0)
    from_raw = b.get("effective_from")
    from_dt = parse_datetime_value(from_raw, "effective_from")
    to_raw = b.get("effective_to")
    to_dt = None
    if to_raw is not None:
        to_dt = parse_datetime_value(to_raw, "effective_to")
        if to_dt.date() <= from_dt.date():
            raise bad_request("effective_to must be strictly after effective_from")
    exempt = v_num(b, "exempt_container_l", required=False)
    rec = new_record()
    rec.update({
        "category": category,
        "state_code": state_code,
        "max_voc_gpl": max_voc_gpl,
        "effective_from": from_raw,
        "effective_to": to_raw,
        "exempt_container_l": exempt,
        "status": "DRAFT",
        "_from_d": from_dt.date(),
        "_to_d": to_dt.date() if to_dt is not None else None,
    })
    store.voc_rules[rec["id"]] = rec
    return success(ser_voc_rule(rec), 201)


@bp.get("/coatings/voc-rules/<rid>")
def get_voc_rule(rid):
    auth(ALL)
    rec = store.voc_rules.get(rid)
    if rec is None:
        raise not_found()
    return success(ser_voc_rule(rec), 200)


@bp.get("/coatings/voc-rules")
def list_voc_rules():
    auth(ALL)
    recs = list(store.voc_rules.values())
    cat = request.args.get("category")
    if cat is not None:
        recs = [r for r in recs if r["category"] == cat]
    sc = request.args.get("state_code")
    if sc is not None:
        recs = [r for r in recs if r["state_code"] == sc]
    return list_response(recs, ser_voc_rule)


@bp.post("/coatings/voc-rules/<rid>/activate")
def activate_voc_rule(rid):
    auth(("RegulatoryClerk",))
    rec = store.voc_rules.get(rid)
    if rec is None:
        raise not_found()
    if rec["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT rule can be activated")
    if rec["_to_d"] is not None and rec["_to_d"] <= rec["_from_d"]:
        raise bad_request("effective_to must be strictly after effective_from")
    a_from, a_to = _window(rec)
    for other in store.voc_rules.values():
        if other["id"] == rid or other["status"] != "ACTIVE":
            continue
        if other["category"] != rec["category"] or other["state_code"] != rec["state_code"]:
            continue
        b_from, b_to = _window(other)
        if _intersects(a_from, a_to, b_from, b_to):
            raise conflict("ERR_VOC_RULE_OVERLAP", "Window overlaps an ACTIVE rule for the same category and state")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(ser_voc_rule(rec), 200)


@bp.post("/coatings/voc-rules/<rid>/retire")
def retire_voc_rule(rid):
    auth(("RegulatoryClerk",))
    rec = store.voc_rules.get(rid)
    if rec is None:
        raise not_found()
    if rec["status"] not in ("DRAFT", "ACTIVE"):
        raise invalid_state("Rule is already RETIRED")
    rec["status"] = "RETIRED"
    touch(rec)
    return success(ser_voc_rule(rec), 200)
