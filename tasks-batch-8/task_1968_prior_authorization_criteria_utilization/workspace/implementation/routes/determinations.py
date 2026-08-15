"""Determination endpoints: reads, void, appeal filing, finding listing."""

from flask import request as flask_request

import clock
from db import db, base_record, touch
from errors import (
    ApiError,
    ERR_APPEAL_ALREADY_OPEN,
    ERR_DETERMINATION_NOT_VOIDABLE,
    ERR_INVALID_APPEAL_STATE,
)
from middleware import (
    ALL_ROLES,
    ROLE_APPEALS_CLERK,
    ROLE_UM_ADMIN,
    authorize,
    get_or_404,
    json_body,
    req_str,
)
from response import list_response, ok, serialize
from services import (
    EV_DETERMINATION_VOIDED,
    add_event,
    appeal_due_at,
    recompute_provider_stats,
)
from . import make_blueprint

bp = make_blueprint("determinations")


def _q(name):
    v = flask_request.args.get(name)
    return v if v not in (None, "") else None


@bp.route("/determinations/<did>", methods=["GET"])
def get_determination(did):
    authorize(*ALL_ROLES)
    rec = get_or_404(db.determinations, did, "determination")
    return ok(serialize(rec))


@bp.route("/determinations", methods=["GET"])
def list_determinations():
    authorize(*ALL_ROLES)
    request_id = _q("request_id")
    guideline_version_id = _q("guideline_version_id")
    items = [
        d
        for d in db.determinations.values()
        if (request_id is None or d["request_id"] == request_id)
        and (
            guideline_version_id is None
            or d["guideline_version_id"] == guideline_version_id
        )
    ]
    return list_response(items)


@bp.route("/determinations/<did>/void", methods=["POST"])
def void_determination(did):
    authorize(ROLE_UM_ADMIN)
    det = get_or_404(db.determinations, did, "determination")
    open_appeal = any(
        a["determination_id"] == did and a["status"] in ("RECEIVED", "IN_REVIEW")
        for a in db.appeals.values()
    )
    if det["status"] != "FINAL" or open_appeal:
        raise ApiError(
            ERR_DETERMINATION_NOT_VOIDABLE,
            409,
            "Void requires status FINAL and no appeal in RECEIVED or IN_REVIEW",
        )

    det["status"] = "VOID"
    touch(det)

    req = db.requests[det["request_id"]]
    # request reverts by deciding tier; escalated_by_user_id retains its prior
    # value in the medical-director case
    if det["decided_by_role"] in ("SYSTEM_RULE", "CLINICAL_REVIEWER"):
        req["status"] = "PENDED_REVIEW"
    else:  # MEDICAL_DIRECTOR
        req["status"] = "ESCALATED_MD"
    req["determined_at"] = None
    touch(req)

    recompute_provider_stats(req["provider_id"], run_suspend_check=True)
    add_event(
        EV_DETERMINATION_VOIDED,
        req["id"],
        req["provider_id"],
        f"Determination {det['id']} voided; request {req['id']} reverted",
    )
    return ok(serialize(det))


# ------------------------------------------------------------- appeals (filed
# under a determination)

@bp.route("/determinations/<did>/appeals", methods=["POST"])
def file_appeal(did):
    authorize(ROLE_APPEALS_CLERK)
    det = get_or_404(db.determinations, did, "determination")
    body = json_body()
    appeal_reason = req_str(body, "appeal_reason")

    # priority 6: filing requires a FINAL determination
    if det["status"] != "FINAL":
        raise ApiError(
            ERR_INVALID_APPEAL_STATE,
            409,
            "Appeal may only be filed against a FINAL determination",
        )
    # priority 8: at most one non-withdrawn appeal per determination
    clash = any(
        a["determination_id"] == did and a["status"] != "WITHDRAWN"
        for a in db.appeals.values()
    )
    if clash:
        raise ApiError(
            ERR_APPEAL_ALREADY_OPEN,
            409,
            "Another appeal for this determination exists in a non-withdrawn "
            "status",
        )

    now = clock.now()
    rec = base_record()
    rec.update(
        {
            "determination_id": did,
            "appeal_reason": appeal_reason,
            "received_at": now,
            "due_at": appeal_due_at(now),
            "status": "RECEIVED",
            "reviewer_id": None,
            "decided_at": None,
            "is_tat_breached": False,
        }
    )
    db.appeals[rec["id"]] = rec
    return ok(serialize(rec), status=201)


@bp.route("/determinations/<did>/appeals", methods=["GET"])
def list_appeals_for_determination(did):
    authorize(*ALL_ROLES)
    get_or_404(db.determinations, did, "determination")
    items = [a for a in db.appeals.values() if a["determination_id"] == did]
    return list_response(items)


@bp.route("/determinations/<did>/audit-findings", methods=["GET"])
def list_findings_for_determination(did):
    authorize(*ALL_ROLES)
    get_or_404(db.determinations, did, "determination")
    items = [f for f in db.findings.values() if f["determination_id"] == did]
    return list_response(items)
