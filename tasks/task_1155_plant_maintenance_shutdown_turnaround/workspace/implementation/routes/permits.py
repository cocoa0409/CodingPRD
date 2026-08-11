"""Permit-to-work endpoints (PRD 3.4).

Permit validity is half-open at its end for activation
([valid_from, valid_until)); issuance requires now < valid_until; the
ops-run sweep expires permits when valid_until <= now.
"""
from flask import Blueprint

import db
from clock import logical_now
from errors import bad_request, conflict, cross_scope, invalid_state
from helpers import (actor, as_dt, as_enum, as_str_list, body, get_or_404,
                     req_field, require_roles)
from response import ok
from serialize import permit_out
from util import fmt_iso

bp = Blueprint("permits", __name__)

PC = ("PermitCoordinator",)
PERMIT_TYPES = ("COLD_WORK", "HOT_WORK", "CONFINED_SPACE")
HAZARD_CLASSES = ("LOW", "HIGH")
PERMIT_STATUSES = ("REQUESTED", "ISSUED", "ACTIVE", "SUSPENDED", "CLOSED",
                   "REVOKED", "EXPIRED")
FINISHED_WORK_STATES = ("VERIFIED", "CANCELLED", "COMPLETE")


@bp.post("/work-items/<wid>/permits")
def create_permit(wid):
    _uid, role = actor()
    require_roles(role, PC)
    w = get_or_404(db.work_items, wid, "WorkItem")
    b = body()
    permit_type = as_enum(req_field(b, "permit_type"), "permit_type",
                          PERMIT_TYPES)
    hazard_class = as_enum(req_field(b, "hazard_class"), "hazard_class",
                           HAZARD_CLASSES)
    valid_from = as_dt(req_field(b, "valid_from"), "valid_from")
    valid_until = as_dt(req_field(b, "valid_until"), "valid_until")
    required = as_str_list(req_field(b, "required_isolation_ids"),
                           "required_isolation_ids")
    if valid_until <= valid_from:
        bad_request("valid_until must be strictly after valid_from")
    # Cross-scope (priority 6): every required isolation must resolve within
    # the covered work item's turnaround.
    for iso_id in required:
        iso = db.isolations.get(iso_id)
        if iso is None or iso["turnaround_id"] != w["turnaround_id"]:
            cross_scope("required_isolation_ids must resolve within the same "
                        "turnaround")
    now = db.now_iso()
    p = db.create(db.permits, {
        "id": db.mint_id(),
        "work_item_id": wid,
        "permit_type": permit_type,
        "hazard_class": hazard_class,
        "valid_from": fmt_iso(valid_from),
        "valid_until": fmt_iso(valid_until),
        "required_isolation_ids": list(required),
        "status": "REQUESTED",
        "version": 1,
        "created_at": now,
        "updated_at": now,
        "_valid_from": valid_from,
        "_valid_until": valid_until,
    })
    return ok(permit_out(p), status=201)


@bp.get("/permits/<pid>")
def get_permit(pid):
    actor()
    p = get_or_404(db.permits, pid, "Permit")
    return ok(permit_out(p))


def _isolations_in_status(p, allowed):
    return all(
        (db.isolations.get(i) is not None
         and db.isolations[i]["status"] in allowed)
        for i in p["required_isolation_ids"])


def _cascade_hold_on_revoke_or_expire(p):
    """Cascade link 1: covered IN_PROGRESS work item is forced ON_HOLD
    (slip/posture recompute follows from the on-the-fly aggregates)."""
    wi = db.work_items.get(p["work_item_id"])
    if wi is not None and wi["status"] == "IN_PROGRESS":
        wi["status"] = "ON_HOLD"
        db.touch(wi)


@bp.post("/permits/<pid>/transition")
def transition_permit(pid):
    _uid, role = actor()
    require_roles(role, PC)
    p = get_or_404(db.permits, pid, "Permit")
    b = body()
    to = as_enum(req_field(b, "to"), "to", PERMIT_STATUSES)
    current = p["status"]
    now = logical_now()
    wi = db.work_items.get(p["work_item_id"])
    t = db.turnarounds.get(wi["turnaround_id"]) if wi else None

    pair = (current, to)
    if pair == ("REQUESTED", "ISSUED"):
        # Safety (p9) isolation gate, then temporal (p10) window gate.
        if not _isolations_in_status(p, ("ISOLATED", "VERIFIED")):
            conflict("ERR_ISOLATION_NOT_VERIFIED",
                     "Every required isolation must be ISOLATED or VERIFIED "
                     "before issuance")
        if not now < p["_valid_until"]:
            conflict("ERR_PERMIT_WINDOW_INVALID",
                     "Issuance requires now < valid_until")
    elif pair in (("ISSUED", "ACTIVE"), ("SUSPENDED", "ACTIVE")):
        # State (p7): turnaround EXECUTION; (ISSUED-only) item not finished.
        if t is None or t["status"] != "EXECUTION":
            invalid_state("Permit activation requires the turnaround to be "
                          "EXECUTION")
        if current == "ISSUED" and wi is not None \
                and wi["status"] in FINISHED_WORK_STATES:
            invalid_state("Cannot activate a permit covering finished work")
        # Safety (p9): every required isolation VERIFIED.
        if not _isolations_in_status(p, ("VERIFIED",)):
            conflict("ERR_ISOLATION_NOT_VERIFIED",
                     "Every required isolation must be VERIFIED before "
                     "activation")
        # Temporal (p10): half-open validity window.
        if not (p["_valid_from"] <= now < p["_valid_until"]):
            conflict("ERR_PERMIT_WINDOW_INVALID",
                     "Activation requires valid_from <= now < valid_until")
    elif pair in (("ACTIVE", "SUSPENDED"),
                  ("ACTIVE", "CLOSED"),
                  ("SUSPENDED", "CLOSED"),
                  ("ISSUED", "REVOKED"),
                  ("SUSPENDED", "REVOKED")):
        pass
    elif pair == ("ACTIVE", "REVOKED"):
        _cascade_hold_on_revoke_or_expire(p)
    else:
        invalid_state("Illegal permit transition from %s to %s"
                      % (current, to))
    p["status"] = to
    db.touch(p)
    return ok(permit_out(p))
