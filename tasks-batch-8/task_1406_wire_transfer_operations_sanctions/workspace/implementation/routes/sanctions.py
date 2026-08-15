"""Sanctions hit disposition: two-tier desk (PRD §3.6) + screening simulation hook."""

from flask import Blueprint

from db import STORE, base_entity, iso, now, pub, touch
from errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_HIT_ALREADY_RESOLVED,
    ERR_INVALID_STATE,
    ApiError,
)
from listing import list_response
from middleware import (
    SANCTIONS_READ,
    get_body,
    require_fk,
    require_roles,
    validate_body,
)
from response import ok
from services import audit, get_or_404, lazy_eval_wire, release_reservation, unresolved_hits

bp = Blueprint("sanctions", __name__, url_prefix="/wire-ops")

_LISTS = {"OFAC_SDN", "INTERNAL_WATCH", "EU_CONSOLIDATED"}
_DISPOSITION_WIRE_STATES = ("PENDING_APPROVAL", "REPAIR", "APPROVED")


def _tier_gate(hit, role):
    """Disposition authority is split by hit tier: a SanctionsScreener handles
    only OPEN hits; a ComplianceOfficer only ESCALATED hits (priority 2)."""
    if hit["status"] == "OPEN" and role != "SanctionsScreener":
        raise ApiError(*ERR_FORBIDDEN_ROLE, "Only a SanctionsScreener may disposition an OPEN hit.")
    if hit["status"] == "ESCALATED" and role != "ComplianceOfficer":
        raise ApiError(*ERR_FORBIDDEN_ROLE, "Only a ComplianceOfficer may disposition an ESCALATED hit.")


@bp.get("/wires/<wid>/sanctions-hits")
def list_hits(wid):
    require_roles(*SANCTIONS_READ)
    wire = get_or_404(STORE.wires, wid, "wire")
    lazy_eval_wire(wire)
    items = [h for h in STORE.sanctions_hits.values() if h["wire_id"] == wid]
    return list_response(items)


@bp.get("/sanctions-hits/<hid>")
def get_hit(hid):
    require_roles(*SANCTIONS_READ)
    hit = get_or_404(STORE.sanctions_hits, hid, "sanctions hit")
    return ok(pub(hit))


@bp.post("/sanctions-hits/<hid>/release")
def release_hit(hid):
    uid, role = require_roles("SanctionsScreener", "ComplianceOfficer")
    hit = get_or_404(STORE.sanctions_hits, hid, "sanctions hit")
    data = get_body()
    validate_body(data, {"rationale": ("str", True, None)})
    _tier_gate(hit, role)
    wire = STORE.wires[hit["wire_id"]]
    lazy_eval_wire(wire)
    if wire["status"] not in _DISPOSITION_WIRE_STATES:
        raise ApiError(*ERR_INVALID_STATE,
                       "The hit's wire is not in PENDING_APPROVAL, REPAIR, or APPROVED.")
    if hit["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError(*ERR_HIT_ALREADY_RESOLVED, "The hit has already been resolved.")
    hit["status"] = "RELEASED_FALSE_POSITIVE"
    hit["decided_by"] = uid
    hit["decided_at"] = iso(now())
    touch(hit)
    # Releasing the wire's last unresolved hit clears the screening dimension.
    if not unresolved_hits(wire["id"]):
        if wire["screening_status"] == "REVIEW":
            wire["screening_status"] = "CLEAR"
        if wire["hold_reason_code"] == "SANCTIONS_HOLD":
            wire["hold_reason_code"] = None
        touch(wire)
    audit("sanctions.release", "SanctionsHit", hid, wire["id"],
          "status -> RELEASED_FALSE_POSITIVE", actor_user_id=uid, actor_role=role)
    return ok(pub(hit))


@bp.post("/sanctions-hits/<hid>/confirm")
def confirm_hit(hid):
    uid, role = require_roles("SanctionsScreener", "ComplianceOfficer")
    hit = get_or_404(STORE.sanctions_hits, hid, "sanctions hit")
    data = get_body()
    validate_body(data, {"rationale": ("str", True, None)})
    _tier_gate(hit, role)
    wire = STORE.wires[hit["wire_id"]]
    lazy_eval_wire(wire)
    if wire["status"] not in _DISPOSITION_WIRE_STATES:
        raise ApiError(*ERR_INVALID_STATE,
                       "The hit's wire is not in PENDING_APPROVAL, REPAIR, or APPROVED.")
    if hit["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError(*ERR_HIT_ALREADY_RESOLVED, "The hit has already been resolved.")
    hit["status"] = "CONFIRMED"
    hit["decided_by"] = uid
    hit["decided_at"] = iso(now())
    touch(hit)
    wire["screening_status"] = "CONFIRMED_HIT"
    if wire["status"] in ("PENDING_APPROVAL", "REPAIR"):
        # Fatal to a wire still in the pipeline.
        wire["status"] = "REJECTED"
        release_reservation(wire)
        wire["hold_reason_code"] = None
    elif wire["status"] == "APPROVED":
        if wire["hold_reason_code"] == "SANCTIONS_HOLD":
            wire["hold_reason_code"] = None
    touch(wire)
    audit("sanctions.confirm", "SanctionsHit", hid, wire["id"],
          "status -> CONFIRMED; screening_status -> CONFIRMED_HIT",
          actor_user_id=uid, actor_role=role)
    return ok(pub(hit))


@bp.post("/sanctions-hits/<hid>/escalate")
def escalate_hit(hid):
    uid, role = require_roles("SanctionsScreener")
    hit = get_or_404(STORE.sanctions_hits, hid, "sanctions hit")
    data = get_body()
    validate_body(data, {"rationale": ("str", True, None)})
    if hit["status"] != "OPEN":
        raise ApiError(*ERR_HIT_ALREADY_RESOLVED, "Only an OPEN hit can be escalated.")
    hit["status"] = "ESCALATED"
    touch(hit)
    audit("sanctions.escalate", "SanctionsHit", hid, hit["wire_id"],
          "status: OPEN -> ESCALATED", actor_user_id=uid, actor_role=role)
    return ok(pub(hit))


@bp.post("/_screening/simulate")
def simulate_hit():
    uid, role = require_roles("SanctionsScreener")
    data = get_body()
    require_fk(data, "wire_id", STORE.wires, "wire")
    validate_body(data, {
        "wire_id": ("str", True, None),
        "matched_list": ("str", True, _LISTS),
        "matched_party": ("str", True, None),
        "match_score": ("int", True, None),
    })
    if not (0 <= data["match_score"] <= 100):
        raise ApiError("ERR_INVALID_REQUEST", 400, "match_score must be between 0 and 100.")
    wire = STORE.wires[data["wire_id"]]
    lazy_eval_wire(wire)
    hit = base_entity()
    hit.update({
        "wire_id": wire["id"],
        "matched_list": data["matched_list"],
        "matched_party": data["matched_party"],
        "match_score": data["match_score"],
        "status": "OPEN",
        "decided_by": None,
        "decided_at": None,
    })
    STORE.sanctions_hits[hit["id"]] = hit
    # If the wire has already been submitted, screening_status is recomputed
    # immediately — REVIEW while the hit is unresolved.
    if wire["screening_status"] != "NOT_SCREENED":
        wire["screening_status"] = "REVIEW"
        if wire["status"] == "APPROVED" and wire["hold_reason_code"] is None:
            wire["hold_reason_code"] = "SANCTIONS_HOLD"
        touch(wire)
    return ok(pub(hit), 201)
