from flask import Blueprint, request

from core import (
    require_ctx, ALL_ROLES, get_body, require_fields, require_enum, require_str,
    respond_object, list_response, fetch, base_record, touch, DB, current_clock,
    iso, ApiError,
)

bp = Blueprint("claims", __name__)

CLAIM_PERILS = {"HURRICANE", "FLOOD", "WILDFIRE", "TORNADO", "HAIL", "WIND", "FIRE", "WATER"}
POLICY_TYPES = {"RCV", "ACV"}


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------
@bp.route("/claims", methods=["POST"])
def create_claim():
    require_ctx({"DeskExaminer"})
    body = get_body()
    require_fields(body, ["claim_number", "policyholder_name", "loss_state",
                          "peril_type", "policy_type"])
    require_str(body["claim_number"], "claim_number")
    require_str(body["policyholder_name"], "policyholder_name")
    require_str(body["loss_state"], "loss_state")
    require_enum(body["peril_type"], CLAIM_PERILS, "peril_type")
    require_enum(body["policy_type"], POLICY_TYPES, "policy_type")
    cat_event_id = body.get("cat_event_id")
    if cat_event_id is not None:
        fetch("cat_events", cat_event_id, "ERR_CAT_EVENT_NOT_FOUND")
    rec = base_record()
    rec.update({
        "claim_number": body["claim_number"],
        "policyholder_name": body["policyholder_name"],
        "loss_state": body["loss_state"],
        "peril_type": body["peril_type"],
        "policy_type": body["policy_type"],
        "cat_event_id": cat_event_id,
        "rcv_cents": 0,
        "reserve_consumed_cents": 0,
        "status": "INTAKE",
    })
    DB["claims"][rec["id"]] = rec
    return respond_object(rec, status=201)


@bp.route("/claims", methods=["GET"])
def list_claims():
    require_ctx(ALL_ROLES)
    return list_response("claims", {
        "cat_event_id": request.args.get("cat_event_id"),
        "status": request.args.get("status"),
        "loss_state": request.args.get("loss_state"),
    })


@bp.route("/claims/<rid>", methods=["GET"])
def get_claim(rid):
    require_ctx(ALL_ROLES)
    return respond_object(fetch("claims", rid, "ERR_CLAIM_NOT_FOUND"))


@bp.route("/claims/<rid>/reopen", methods=["POST"])
def reopen_claim(rid):
    require_ctx({"DeskExaminer"})
    claim = fetch("claims", rid, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "CLOSED":
        raise ApiError("ERR_CLAIM_NOT_CLOSED", 409)
    claim["status"] = "REOPENED"
    touch(claim)
    return respond_object(claim)


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------
@bp.route("/assignments", methods=["POST"])
def create_assignment():
    require_ctx({"DeskExaminer"})
    body = get_body()
    require_fields(body, ["claim_id", "adjuster_id"])
    claim = fetch("claims", body["claim_id"], "ERR_CLAIM_NOT_FOUND")
    fetch("adjusters", body["adjuster_id"], "ERR_ADJUSTER_NOT_FOUND")
    rec = base_record()
    rec.update({
        "claim_id": body["claim_id"],
        "adjuster_id": body["adjuster_id"],
        "offered_at": iso(current_clock()),
        "work_status": "OFFERED",
        "billing_status": "NOT_BILLED",
    })
    DB["assignments"][rec["id"]] = rec
    if claim["status"] == "INTAKE":
        claim["status"] = "ASSIGNED"
        touch(claim)
    return respond_object(rec, status=201)


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    require_ctx(ALL_ROLES)
    return list_response("assignments", {
        "claim_id": request.args.get("claim_id"),
        "adjuster_id": request.args.get("adjuster_id"),
        "work_status": request.args.get("work_status"),
        "billing_status": request.args.get("billing_status"),
    })


@bp.route("/assignments/<rid>", methods=["GET"])
def get_assignment(rid):
    require_ctx(ALL_ROLES)
    return respond_object(fetch("assignments", rid, "ERR_ASSIGNMENT_NOT_FOUND"))


@bp.route("/assignments/<rid>/accept", methods=["POST"])
def accept_assignment(rid):
    uid, role = require_ctx({"FieldAdjuster"})
    asn = fetch("assignments", rid, "ERR_ASSIGNMENT_NOT_FOUND")
    # ownership (priority 5) before legal state (priority 7) before license (8)
    if uid != asn["adjuster_id"]:
        raise ApiError("ERR_NOT_ASSIGNMENT_OWNER", 403)
    if asn["work_status"] != "OFFERED":
        raise ApiError("ERR_ASSIGNMENT_NOT_OFFERED", 409)
    claim = DB["claims"][asn["claim_id"]]
    # license gate: ACTIVE, matching loss_state, current_clock < expires_at
    now = current_clock()
    qualifies = False
    for lic in DB["licenses"].values():
        if (lic["adjuster_id"] == asn["adjuster_id"]
                and lic["status"] == "ACTIVE"
                and lic["state_code"] == claim["loss_state"]
                and now < lic["_expires_dt"]):
            qualifies = True
            break
    if not qualifies:
        raise ApiError("ERR_NO_ACTIVE_LICENSE", 422)
    asn["work_status"] = "ACCEPTED"
    touch(asn)
    if claim["status"] in {"ASSIGNED", "REOPENED"}:
        claim["status"] = "IN_PROGRESS"
        touch(claim)
    return respond_object(asn)


@bp.route("/assignments/<rid>/decline", methods=["POST"])
def decline_assignment(rid):
    uid, role = require_ctx({"FieldAdjuster"})
    asn = fetch("assignments", rid, "ERR_ASSIGNMENT_NOT_FOUND")
    if uid != asn["adjuster_id"]:
        raise ApiError("ERR_NOT_ASSIGNMENT_OWNER", 403)
    if asn["work_status"] != "OFFERED":
        raise ApiError("ERR_ASSIGNMENT_NOT_OFFERED", 409)
    asn["work_status"] = "DECLINED"
    touch(asn)
    return respond_object(asn)
