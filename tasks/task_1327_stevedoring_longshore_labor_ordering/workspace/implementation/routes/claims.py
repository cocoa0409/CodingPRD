"""DamageClaim endpoints (PRD §3.7)."""
from flask import Blueprint, g, request

import errors
import services
from db import get, new_resource, pub, save, touch
from middleware import list_response, req_enum, req_field, req_int, req_str, require_roles
from response import get_body, ok

bp = Blueprint("claims", __name__)

READ_ROLES = ("StevedoreAdmin", "StevedoreSuperintendent", "GangForeman", "ClaimsAdjuster")


@bp.post("/api/damage-claims")
def create_claim():
    require_roles("GangForeman")
    body = get_body()
    # existence (3)
    gang_order_id = req_field(body, "gang_order_id")
    if get("gang_orders", gang_order_id) is None:
        raise errors.not_found("Gang order not found")
    # schema (4)
    cargo_ref = req_str(body, "cargo_ref")
    damage_description = req_str(body, "damage_description")
    estimated_amount_cents = req_int(body, "estimated_amount_cents", min_value=1)
    rec = new_resource("damage_claims")
    rec.update({
        "gang_order_id": gang_order_id,
        "reported_by_worker_id": g.user_id,
        "cargo_ref": cargo_ref,
        "damage_description": damage_description,
        "estimated_amount_cents": estimated_amount_cents,
        "status": "REPORTED",
        "provisional_stevedore_share_cents": services.provisional_share(estimated_amount_cents),
        "fault_pct": None,
        "final_stevedore_liability_cents": None,
        "decided_by_user_id": None,
    })
    save("damage_claims", rec)
    return ok(pub(rec), 201)


@bp.get("/api/damage-claims")
def list_claims():
    require_roles(*READ_ROLES)
    return list_response("damage_claims", {
        "gang_order_id": request.args.get("gang_order_id"),
        "status": request.args.get("status"),
    })


def _get_claim(cid):
    c = get("damage_claims", cid)
    if c is None:
        raise errors.not_found("Damage claim not found")
    return c


@bp.get("/api/damage-claims/<cid>")
def get_claim(cid):
    require_roles(*READ_ROLES)
    return ok(pub(_get_claim(cid)))


@bp.post("/api/damage-claims/<cid>/decide")
def decide_claim(cid):
    require_roles("ClaimsAdjuster")
    c = _get_claim(cid)
    body = get_body()
    # schema (4)
    decision = req_enum(body, "decision", ("ACCEPTED", "DENIED"))
    fault_pct = None
    if decision == "ACCEPTED":
        raw = body.get("fault_pct")
        if raw is None or not isinstance(raw, int) or isinstance(raw, bool) \
                or raw < 0 or raw > 100:
            raise errors.fault_pct_out_of_range()
        fault_pct = raw
    else:
        raw = body.get("fault_pct")
        if isinstance(raw, int) and not isinstance(raw, bool):
            fault_pct = raw
    # state (6)
    if c["status"] != "REPORTED":
        raise errors.invalid_state("Only a REPORTED claim can be decided")
    # segregation of duties (10)
    if g.user_id == c["reported_by_worker_id"]:
        raise errors.segregation("The claims adjuster may not adjudicate a claim they reported")
    c["decided_by_user_id"] = g.user_id
    c["fault_pct"] = fault_pct
    if decision == "ACCEPTED":
        c["status"] = "ACCEPTED"
    else:
        c["status"] = "DENIED"
        c["final_stevedore_liability_cents"] = 0
    touch(c)
    return ok(pub(c))


@bp.post("/api/damage-claims/<cid>/settle")
def settle_claim(cid):
    require_roles("ClaimsAdjuster")
    c = _get_claim(cid)
    if c["status"] != "ACCEPTED":
        raise errors.invalid_state("Only an ACCEPTED claim can be settled")
    c["final_stevedore_liability_cents"] = services.final_liability(
        c["estimated_amount_cents"], c["fault_pct"])
    c["status"] = "SETTLED"
    touch(c)
    return ok(pub(c))
