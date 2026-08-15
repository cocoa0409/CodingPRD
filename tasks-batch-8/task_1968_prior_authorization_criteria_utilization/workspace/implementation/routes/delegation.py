"""Delegation oversight: arrangements and audit findings."""

from flask import request as flask_request

from db import db, base_record, touch
from errors import (
    ApiError,
    ERR_ARRANGEMENT_ALREADY_EXISTS,
    ERR_DELEGATION_SCOPE_MISMATCH,
    ERR_DELEGATION_SUSPENDED,
    ERR_FINDING_NOT_OPEN,
    invalid_request,
)
from middleware import (
    ALL_ROLES,
    ROLE_COMPLIANCE,
    ROLE_UM_ADMIN,
    authorize,
    get_or_404,
    json_body,
    req_enum,
    req_str,
)
from response import list_response, ok, serialize
from services import recompute_arrangement
from . import make_blueprint

bp = make_blueprint("delegation")

FINDING_TYPES = ("COMPLIANT", "NOTICE_DEFICIENT", "CRITERIA_MISAPPLIED", "TAT_VIOLATION")
FINDING_STATUSES = ("OPEN", "CLOSED")


def _q(name):
    v = flask_request.args.get(name)
    return v if v not in (None, "") else None


@bp.route("/delegation-arrangements", methods=["POST"])
def create_arrangement():
    authorize(ROLE_UM_ADMIN)
    body = json_body()
    delegating_plan_name = req_str(body, "delegating_plan_name")
    criteria_set_id = req_str(body, "criteria_set_id")
    if criteria_set_id not in db.criteria_sets:
        raise invalid_request(f"criteria_set_id {criteria_set_id} does not exist")
    # priority 8: at most one arrangement per criteria set
    if any(
        a["criteria_set_id"] == criteria_set_id for a in db.arrangements.values()
    ):
        raise ApiError(
            ERR_ARRANGEMENT_ALREADY_EXISTS,
            409,
            "A delegation arrangement already exists for this criteria set",
        )
    rec = base_record()
    rec.update(
        {
            "delegating_plan_name": delegating_plan_name,
            "criteria_set_id": criteria_set_id,
            "status": "ACTIVE",
            "open_deficiency_count": 0,
        }
    )
    db.arrangements[rec["id"]] = rec
    return ok(serialize(rec), status=201)


@bp.route("/delegation-arrangements/<aid>", methods=["GET"])
def get_arrangement(aid):
    authorize(*ALL_ROLES)
    rec = get_or_404(db.arrangements, aid, "delegation arrangement")
    return ok(serialize(rec))


@bp.route("/delegation-arrangements", methods=["GET"])
def list_arrangements():
    authorize(*ALL_ROLES)
    criteria_set_id = _q("criteria_set_id")
    items = [
        a
        for a in db.arrangements.values()
        if criteria_set_id is None or a["criteria_set_id"] == criteria_set_id
    ]
    return list_response(items)


@bp.route("/delegation-arrangements/<aid>/audit-findings", methods=["POST"])
def create_finding(aid):
    authorize(ROLE_COMPLIANCE)
    arrangement = get_or_404(db.arrangements, aid, "delegation arrangement")
    body = json_body()
    determination_id = req_str(body, "determination_id")
    if determination_id not in db.determinations:
        raise invalid_request(
            f"determination_id {determination_id} does not exist"
        )
    finding_type = req_enum(body, "finding_type", FINDING_TYPES)

    # priority 6: finding creation blocked while the arrangement is SUSPENDED
    if arrangement["status"] != "ACTIVE":
        raise ApiError(
            ERR_DELEGATION_SUSPENDED,
            409,
            "Finding creation blocked: arrangement is SUSPENDED",
        )
    # priority 8: the audited determination must fall in the arrangement's scope
    det = db.determinations[determination_id]
    req = db.requests[det["request_id"]]
    if req["criteria_set_id"] != arrangement["criteria_set_id"]:
        raise ApiError(
            ERR_DELEGATION_SCOPE_MISMATCH,
            422,
            "Finding's determination does not belong to the arrangement's "
            "criteria set",
        )

    rec = base_record()
    rec.update(
        {
            "arrangement_id": aid,
            "determination_id": determination_id,
            "finding_type": finding_type,
            "status": "OPEN",
        }
    )
    db.findings[rec["id"]] = rec
    # deficiency threshold cascade (inclusive: the third open deficiency suspends)
    recompute_arrangement(arrangement)
    return ok(serialize(rec), status=201)


@bp.route("/delegation-arrangements/<aid>/audit-findings", methods=["GET"])
def list_findings_for_arrangement(aid):
    authorize(*ALL_ROLES)
    get_or_404(db.arrangements, aid, "delegation arrangement")
    items = [f for f in db.findings.values() if f["arrangement_id"] == aid]
    return list_response(items)


@bp.route("/audit-findings/<fid>/transition", methods=["POST"])
def transition_finding(fid):
    authorize(ROLE_COMPLIANCE)
    rec = get_or_404(db.findings, fid, "audit finding")
    body = json_body()
    to_status = req_enum(body, "to_status", FINDING_STATUSES)
    if to_status != "CLOSED" or rec["status"] != "OPEN":
        raise ApiError(
            ERR_FINDING_NOT_OPEN,
            409,
            "Finding close requires status OPEN",
        )
    rec["status"] = "CLOSED"
    touch(rec)
    arrangement = db.arrangements[rec["arrangement_id"]]
    recompute_arrangement(arrangement)
    return ok(serialize(rec))
