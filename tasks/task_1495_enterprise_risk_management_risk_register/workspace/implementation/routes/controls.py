"""Control library (PRD 3.3): lifecycle, attestation/retirement cascades."""
from flask import Blueprint

from db import store
from errors import ApiError
from middleware import authenticate, ALL_ROLES
from response import ok_object, ok_list
from services import (new_entity, touch, serialize_control, serialize_mapping,
                      cascade_recompute_risk, mapped_active_count,
                      sorted_by_creation)
from util import json_body, req_str, opt_str, req_num, opt_int, paginate

bp = Blueprint("controls", __name__)


def get_control_or_404(cid):
    c = store["controls"].get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Control not found")
    return c


@bp.post("/controls")
def create_control():
    authenticate(("ControlOwner",))
    data = json_body()
    name = req_str(data, "name")
    effectiveness = req_num(data, "effectiveness_pct")
    description = opt_str(data, "description")
    max_mapped = opt_int(data, "max_mapped_risks")
    if max_mapped is None:
        max_mapped = 10
    if max_mapped < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "max_mapped_risks must be >= 1")
    if effectiveness <= 0 or effectiveness > 1:
        raise ApiError("ERR_SCORE_OUT_OF_RANGE", 422,
                       "effectiveness_pct must be in (0, 1.00]")
    c = new_entity()
    c.update({"name": name, "description": description,
              "effectiveness_pct": effectiveness, "max_mapped_risks": max_mapped,
              "status": "PROPOSED"})
    store["controls"][c["id"]] = c
    return ok_object(serialize_control(c), 201)


@bp.get("/controls/<cid>")
def get_control(cid):
    authenticate(ALL_ROLES)
    return ok_object(serialize_control(get_control_or_404(cid)))


def _control_transition(cid, allowed_from, target):
    authenticate(("ControlOwner",))
    c = get_control_or_404(cid)
    if c["status"] != allowed_from:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Control in status %s cannot perform this transition" % c["status"])
    c["status"] = target
    touch(c)
    return c


@bp.post("/controls/<cid>/activate")
def activate_control(cid):
    c = _control_transition(cid, "PROPOSED", "ACTIVE")
    return ok_object(serialize_control(c))


@bp.post("/controls/<cid>/review")
def review_control(cid):
    c = _control_transition(cid, "ACTIVE", "UNDER_REVIEW")
    return ok_object(serialize_control(c))


@bp.post("/controls/<cid>/attest")
def attest_control(cid):
    authenticate(("ControlOwner",))
    data = json_body()
    effectiveness = req_num(data, "effectiveness_pct")
    c = get_control_or_404(cid)
    if c["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an UNDER_REVIEW control can be attested")
    if effectiveness <= 0 or effectiveness > 1:
        raise ApiError("ERR_SCORE_OUT_OF_RANGE", 422,
                       "effectiveness_pct must be in (0, 1.00]")
    c["effectiveness_pct"] = effectiveness
    c["status"] = "ACTIVE"
    touch(c)
    # cascade: recompute residual + breach evaluation for each actively-mapped
    # risk that already has an inherent score
    touched = set()
    for m in store["mappings"].values():
        if m["control_id"] == c["id"] and m["status"] == "ACTIVE":
            risk = store["risks"].get(m["risk_id"])
            if risk is not None and risk["id"] not in touched:
                touched.add(risk["id"])
                cascade_recompute_risk(risk)
    return ok_object(serialize_control(c))


@bp.post("/controls/<cid>/retire")
def retire_control(cid):
    c = _control_transition(cid, "ACTIVE", "RETIRED")
    # every ACTIVE mapping becomes RETIRED; each affected risk recomputes
    affected_risks = []
    seen = set()
    for m in store["mappings"].values():
        if m["control_id"] == c["id"] and m["status"] == "ACTIVE":
            m["status"] = "RETIRED"
            touch(m)
            risk = store["risks"].get(m["risk_id"])
            if risk is not None and risk["id"] not in seen:
                seen.add(risk["id"])
                affected_risks.append(risk)
    for risk in affected_risks:
        cascade_recompute_risk(risk)
    return ok_object(serialize_control(c))


@bp.get("/controls/<cid>/control-mappings")
def list_control_mappings(cid):
    authenticate(ALL_ROLES)
    get_control_or_404(cid)
    items = sorted_by_creation(
        m for m in store["mappings"].values() if m["control_id"] == cid)
    page, meta = paginate(items)
    return ok_list([serialize_mapping(m) for m in page], meta)


# ---------------------------------------------------------------------------
# Flat mapping actions (PRD 3.3)
# ---------------------------------------------------------------------------

@bp.post("/control-mappings/<mid>/approve")
def approve_mapping(mid):
    authenticate(("RiskManager",))
    m = store["mappings"].get(mid)
    if m is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Control mapping not found")
    if m["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Mapping in status %s cannot be approved" % m["status"])
    control = store["controls"].get(m["control_id"])
    if control is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Control not found")
    # control-state guard reports before the capacity guard (PRD 2.8, 3.3)
    if control["status"] != "ACTIVE":
        raise ApiError("ERR_CONTROL_NOT_ACTIVE", 409,
                       "Mapping approve requires the control to be ACTIVE")
    if mapped_active_count(control["id"]) >= control["max_mapped_risks"]:
        raise ApiError("ERR_CONTROL_CAPACITY_EXCEEDED", 422,
                       "Control has reached max_mapped_risks")
    m["status"] = "ACTIVE"
    touch(m)
    touch(control)
    risk = store["risks"].get(m["risk_id"])
    if risk is not None:
        cascade_recompute_risk(risk)
    return ok_object(serialize_mapping(m))


@bp.post("/control-mappings/<mid>/retire")
def retire_mapping(mid):
    authenticate(("RiskManager",))
    m = store["mappings"].get(mid)
    if m is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Control mapping not found")
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Mapping in status %s cannot be retired" % m["status"])
    control = store["controls"].get(m["control_id"])
    m["status"] = "RETIRED"
    touch(m)
    if control is not None:
        touch(control)
    risk = store["risks"].get(m["risk_id"])
    if risk is not None:
        cascade_recompute_risk(risk)
    return ok_object(serialize_mapping(m))
