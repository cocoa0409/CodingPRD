"""Cast member and cast endorsement endpoints."""

from flask import request

from db import db
from errors import err
from middleware import require_roles
from response import success_list, success_object
from routes import bp
from services.lifecycle import sweep
from services.posture import recompute_posture
from util import (
    add_days,
    body,
    get_child,
    get_production,
    make_entity,
    now,
    opt_bool,
    opt_string,
    paginate,
    req_enum,
    req_int,
    req_string,
    serialize,
    touch,
)

ROLE_TIERS = ("PRINCIPAL", "SUPPORTING", "DAY_PLAYER", "STUNT")
EXAM_OUTCOMES = ("CLEARED", "CONDITIONAL", "FAILED")
ENDORSEMENT_TYPES = ("PHYSICAL_CLEARANCE", "ESSENTIAL_ELEMENT", "STUNT_RIDER")

CAST_LIST_ROLES = {
    "BrokerAgent", "ProductionManager", "UnderwriterAgent",
    "ClaimsAdjuster", "PlatformOperator",
}
CAST_GET_ROLES = {"BrokerAgent", "ProductionManager", "UnderwriterAgent", "PlatformOperator"}
ENDORSEMENT_ROLES = {"BrokerAgent", "ProductionManager", "UnderwriterAgent", "PlatformOperator"}


def get_cast_member(prod_id, member_id):
    return get_child(db.cast_members, member_id, "production_id", prod_id, "CastMember")


def get_endorsement(prod_id, endorsement_id):
    rec = db.cast_endorsements.get(endorsement_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "CastEndorsement '%s' not found" % endorsement_id)
    cm = db.cast_members.get(rec["cast_member_id"])
    if cm is None or cm["production_id"] != prod_id:
        raise err("ERR_NOT_FOUND", "CastEndorsement '%s' not found" % endorsement_id)
    return rec


# ---------------------------------------------------------------------------
# Cast members
# ---------------------------------------------------------------------------

@bp.route("/productions/<id>/cast-members", methods=["POST"])
def create_cast_member(id):
    require_roles({"ProductionManager"})
    with db.lock:
        prod = get_production(id)
        data = body()
        full_name = req_string(data, "full_name")
        role_tier = req_enum(data, "role_tier", ROLE_TIERS)
        weekly_salary_cents = req_int(data, "weekly_salary_cents")
        essential_element = opt_bool(data, "essential_element", False)
        if weekly_salary_cents <= 0:
            raise err("ERR_FISCAL_CONSTRAINT_VIOLATED",
                      "weekly_salary_cents must be greater than zero")

        rec = make_entity({
            "production_id": id,
            "full_name": full_name,
            "role_tier": role_tier,
            "weekly_salary_cents": weekly_salary_cents,
            "essential_element": essential_element,
            "physical_exam_status": "PENDING",
            "physical_exam_expires_at": None,
            "endorsement_required": bool(essential_element or role_tier == "PRINCIPAL"),
        })
        db.cast_members[rec["id"]] = rec
        recompute_posture(prod)
        return success_object(serialize(rec), status=201)


@bp.route("/productions/<id>/cast-members", methods=["GET"])
def list_cast_members(id):
    require_roles(CAST_LIST_ROLES)
    get_production(id)
    role_tier = request.args.get("role_tier")
    exam = request.args.get("physical_exam_status")
    records = [c for c in db.cast_members.values() if c["production_id"] == id]
    if role_tier is not None:
        records = [r for r in records if r["role_tier"] == role_tier]
    if exam is not None:
        records = [r for r in records if r["physical_exam_status"] == exam]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/productions/<id>/cast-members/<childId>", methods=["GET"])
def get_cast_member_by_id(id, childId):
    require_roles(CAST_GET_ROLES)
    get_production(id)
    rec = get_cast_member(id, childId)
    return success_object(serialize(rec))


@bp.route("/productions/<id>/cast-members/<childId>/physical-exam", methods=["POST"])
def record_physical_exam(id, childId):
    require_roles({"UnderwriterAgent"})
    with db.lock:
        prod = get_production(id)
        cm = get_cast_member(id, childId)
        data = body()
        outcome = data.get("outcome")

        current = cm["physical_exam_status"]
        valid = (current == "PENDING") or (current == "CONDITIONAL" and outcome == "CLEARED")
        if isinstance(outcome, str) and outcome in EXAM_OUTCOMES and not valid:
            raise err("ERR_INVALID_STATE",
                      "Exam outcome %s cannot be recorded from status %s" % (outcome, current))
        outcome = req_enum(data, "outcome", EXAM_OUTCOMES)

        if outcome in ("CLEARED", "CONDITIONAL") and prod["status"] == "CANCELLED":
            raise err("ERR_INVALID_STATE",
                      "Cannot record exam outcome on a CANCELLED production")

        ts = now()
        if outcome == "CLEARED":
            cm["physical_exam_status"] = "CLEARED"
            cm["physical_exam_expires_at"] = add_days(ts, 90)
        elif outcome == "CONDITIONAL":
            cm["physical_exam_status"] = "CONDITIONAL"
            cm["physical_exam_expires_at"] = add_days(ts, 30)
        else:
            cm["physical_exam_status"] = "FAILED"
            cm["physical_exam_expires_at"] = None
        touch(cm)
        recompute_posture(prod)
        return success_object(serialize(cm))


@bp.route("/productions/<id>/cast-members/<childId>/physical-exam-retake", methods=["POST"])
def physical_exam_retake(id, childId):
    require_roles({"UnderwriterAgent"})
    with db.lock:
        prod = get_production(id)
        cm = get_cast_member(id, childId)
        if cm["physical_exam_status"] != "FAILED":
            raise err("ERR_INVALID_STATE",
                      "Only a FAILED exam can be retaken (current: %s)"
                      % cm["physical_exam_status"])
        cm["physical_exam_status"] = "PENDING"
        cm["physical_exam_expires_at"] = None
        touch(cm)
        recompute_posture(prod)
        return success_object(serialize(cm))


# ---------------------------------------------------------------------------
# Cast endorsements
# ---------------------------------------------------------------------------

@bp.route("/productions/<id>/cast-endorsements", methods=["POST"])
def create_cast_endorsement(id):
    require_roles({"UnderwriterAgent"})
    with db.lock:
        get_production(id)
        data = body()
        cast_member_id = data.get("cast_member_id")
        policy_id = data.get("policy_id")
        if not isinstance(cast_member_id, str) or not cast_member_id:
            raise err("ERR_INVALID_REQUEST", "Field 'cast_member_id' is required")
        if not isinstance(policy_id, str) or not policy_id:
            raise err("ERR_INVALID_REQUEST", "Field 'policy_id' is required")
        cm = get_cast_member(id, cast_member_id)
        pol = get_child(db.policies, policy_id, "production_id", id, "Policy")
        if pol["coverage_line"] != "CAST":
            raise err("ERR_REFERENCED_STATE_INVALID",
                      "policy_id must reference a CAST coverage policy")
        endorsement_type = req_enum(data, "endorsement_type", ENDORSEMENT_TYPES)
        notes = opt_string(data, "underwriter_notes")

        rec = make_entity({
            "cast_member_id": cm["id"],
            "policy_id": pol["id"],
            "endorsement_type": endorsement_type,
            "underwriter_notes": notes,
            "issued_at": None,
            "revoked_at": None,
            "status": "DRAFT",
        })
        db.cast_endorsements[rec["id"]] = rec

        # Drafting against a BOUND cast policy holds it as ENDORSED_PENDING.
        if pol["status"] == "BOUND":
            pol["status"] = "ENDORSED_PENDING"
            touch(pol)
            recompute_posture(db.productions[id])

        return success_object(serialize(rec), status=201)


@bp.route("/productions/<id>/cast-endorsements", methods=["GET"])
def list_cast_endorsements(id):
    require_roles(ENDORSEMENT_ROLES)
    get_production(id)
    cm_id = request.args.get("cast_member_id")
    pol_id = request.args.get("policy_id")
    etype = request.args.get("endorsement_type")
    status = request.args.get("status")
    records = []
    for e in db.cast_endorsements.values():
        cm = db.cast_members.get(e["cast_member_id"])
        if cm is None or cm["production_id"] != id:
            continue
        records.append(e)
    if cm_id is not None:
        records = [r for r in records if r["cast_member_id"] == cm_id]
    if pol_id is not None:
        records = [r for r in records if r["policy_id"] == pol_id]
    if etype is not None:
        records = [r for r in records if r["endorsement_type"] == etype]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/productions/<id>/cast-endorsements/<childId>", methods=["GET"])
def get_cast_endorsement_by_id(id, childId):
    require_roles(ENDORSEMENT_ROLES)
    get_production(id)
    rec = get_endorsement(id, childId)
    return success_object(serialize(rec))


@bp.route("/productions/<id>/cast-endorsements/<childId>/issue", methods=["POST"])
def issue_cast_endorsement(id, childId):
    require_roles({"UnderwriterAgent"})
    with db.lock:
        prod = get_production(id)
        e = get_endorsement(id, childId)
        if e["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE",
                      "Endorsement must be DRAFT to issue (current: %s)" % e["status"])

        cm = db.cast_members[e["cast_member_id"]]
        etype = e["endorsement_type"]
        if etype == "PHYSICAL_CLEARANCE":
            if cm["physical_exam_status"] not in ("CLEARED", "CONDITIONAL"):
                raise err("ERR_CAST_ENDORSEMENT_INVALID",
                          "PHYSICAL_CLEARANCE requires exam CLEARED or CONDITIONAL")
        elif etype == "ESSENTIAL_ELEMENT":
            if not cm["essential_element"]:
                raise err("ERR_CAST_ENDORSEMENT_INVALID",
                          "ESSENTIAL_ELEMENT requires essential_element true")
        elif etype == "STUNT_RIDER":
            if cm["role_tier"] != "STUNT":
                raise err("ERR_CAST_ENDORSEMENT_INVALID",
                          "STUNT_RIDER requires role_tier STUNT")

        pol = db.policies[e["policy_id"]]
        if pol["status"] not in ("BOUND", "ENDORSED_PENDING", "ACTIVE"):
            raise err("ERR_REFERENCED_STATE_INVALID",
                      "Policy must be BOUND, ENDORSED_PENDING or ACTIVE (current: %s)"
                      % pol["status"])

        e["status"] = "ISSUED"
        e["issued_at"] = now()
        touch(e)
        recompute_posture(prod)
        sweep()  # may release an ENDORSED_PENDING policy to ACTIVE
        return success_object(serialize(e))


@bp.route("/productions/<id>/cast-endorsements/<childId>/revoke", methods=["POST"])
def revoke_cast_endorsement(id, childId):
    require_roles({"UnderwriterAgent"})
    with db.lock:
        prod = get_production(id)
        e = get_endorsement(id, childId)
        if e["status"] not in ("DRAFT", "ISSUED"):
            raise err("ERR_INVALID_STATE",
                      "Endorsement must be DRAFT or ISSUED to revoke (current: %s)" % e["status"])
        e["status"] = "REVOKED"
        e["revoked_at"] = now()
        touch(e)
        recompute_posture(prod)
        sweep()
        return success_object(serialize(e))
