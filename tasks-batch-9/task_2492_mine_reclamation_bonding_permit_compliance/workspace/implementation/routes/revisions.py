"""Permit revisions: the review cycle and the expansion cascade (PRD 3.4)."""

from flask import Blueprint

import constants as C
import engine
import serialization as ser
from db import D, base_row, db, money, now
from engine import bump
from errors import ApiError
from response import created_response, object_response
from routes._shared import (
    check_decision_reason,
    collection_filtered,
    precheck_denial_reason,
    require_permit_operator,
    require_permit_status,
    require_state,
)
from validation import (
    authorize,
    enum_field,
    get_body,
    lookup,
    number_field,
    resolve,
    str_field,
)

bp = Blueprint("revisions", __name__)

LIST_FILTERS = [
    ("permit_id", "permit_id", None),
    ("status", "status", C.REVISION_STATUSES),
    ("revision_type", "revision_type", C.REVISION_TYPES),
]


def _check_shape(revision_type, acreage_delta, new_pmlu, sequence_note):
    """Band 13 — the revision-type-conditional body shape."""
    if revision_type == "EXPANSION":
        ok = acreage_delta is not None and new_pmlu is None
    elif revision_type == "PMLU_CHANGE":
        ok = new_pmlu is not None and acreage_delta is None
    else:
        ok = sequence_note is not None and acreage_delta is None and new_pmlu is None
    if not ok:
        raise ApiError(
            "ERR_REVISION_FIELDS_MISMATCH",
            "The supplied fields do not match the declared revision_type.",
        )


@bp.post("/mining/permit-revisions")
def create_revision():
    user_id, role = authorize([C.ROLE_OPERATOR])
    body = get_body()
    permit_id = str_field(body, "permit_id")
    revision_type = enum_field(body, "revision_type", C.REVISION_TYPES)
    acreage_delta = number_field(body, "acreage_delta", required=False, gt=0)
    new_pmlu = enum_field(
        body, "new_post_mining_land_use", C.POST_MINING_LAND_USES, required=False
    )
    sequence_note = str_field(body, "sequence_note", required=False)

    permit = resolve(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")
    require_permit_operator(role, user_id, permit)
    require_permit_status(permit, C.PERMIT_STATUSES_REVISION)
    _check_shape(revision_type, acreage_delta, new_pmlu, sequence_note)

    row = base_row()
    row.update(
        {
            "permit_id": permit_id,
            "revision_type": revision_type,
            "acreage_delta": acreage_delta,
            "new_post_mining_land_use": new_pmlu,
            "sequence_note": sequence_note,
            "status": "SUBMITTED",
            "round_count": 1,
            "info_request_note": None,
            "response_note": None,
            "denial_reason": None,
            "decided_at": None,
        }
    )
    db.revisions[row["id"]] = row
    return created_response(ser.revision_out(row))


@bp.get("/mining/permit-revisions/<revision_id>")
def get_revision(revision_id):
    authorize(C.ROLES_REVISION_READ)
    row = lookup(db.revisions, revision_id, "ERR_REVISION_NOT_FOUND")
    return object_response(ser.revision_out(row))


@bp.get("/mining/permit-revisions")
def list_revisions():
    authorize(C.ROLES_REVISION_READ)
    return collection_filtered(db.revisions.values(), LIST_FILTERS, ser.revision_out)


@bp.post("/mining/permit-revisions/<revision_id>/request-info")
def request_info(revision_id):
    authorize([C.ROLE_PERMIT_REVIEWER])
    body = get_body()
    info_request_note = str_field(body, "info_request_note")

    row = lookup(db.revisions, revision_id, "ERR_REVISION_NOT_FOUND")
    require_state(row, "status", ["SUBMITTED"], "ERR_REVISION_STATE_INVALID")

    row["status"] = "INFO_REQUESTED"
    row["info_request_note"] = info_request_note
    bump(row)
    return object_response(ser.revision_out(row))


@bp.post("/mining/permit-revisions/<revision_id>/resubmit")
def resubmit(revision_id):
    user_id, role = authorize([C.ROLE_OPERATOR])
    body = get_body()
    response_note = str_field(body, "response_note")

    row = lookup(db.revisions, revision_id, "ERR_REVISION_NOT_FOUND")
    permit = db.permits[row["permit_id"]]

    # Band 6, band 9, then band 13.
    require_permit_operator(role, user_id, permit)
    require_state(row, "status", ["INFO_REQUESTED"], "ERR_REVISION_STATE_INVALID")
    if row["round_count"] >= C.REVISION_ROUND_CAP:
        raise ApiError(
            "ERR_REVISION_ROUND_LIMIT",
            "This revision has already consumed its review rounds.",
        )

    row["status"] = "SUBMITTED"
    row["response_note"] = response_note
    row["round_count"] = row["round_count"] + 1
    bump(row)
    return object_response(ser.revision_out(row))


@bp.post("/mining/permit-revisions/<revision_id>/decide")
def decide_revision(revision_id):
    authorize([C.ROLE_PERMIT_REVIEWER])
    body = get_body()
    decision = enum_field(body, "decision", C.DECISIONS_APPROVE)
    precheck_denial_reason(body)

    row = lookup(db.revisions, revision_id, "ERR_REVISION_NOT_FOUND")
    permit = db.permits[row["permit_id"]]

    # Band 9, then band 10.
    require_state(row, "status", ["SUBMITTED"], "ERR_REVISION_STATE_INVALID")
    require_permit_status(permit, C.PERMIT_STATUSES_REVISION)

    # Band 11 — the state does not enlarge a permit that is already in trouble.
    if decision == "APPROVE" and permit["compliance_posture"] not in (
        "COMPLIANT",
        "NOTICE_ACTIVE",
    ):
        raise ApiError(
            "ERR_PERMIT_NOT_COMPLIANT",
            "A revision cannot be approved while the permit is out of compliance.",
        )

    # Band 13.
    denial_reason = check_decision_reason(decision, body)

    row["decided_at"] = now()
    if decision == "APPROVE":
        row["status"] = "APPROVED"
        bump(row)
        if row["revision_type"] == "EXPANSION":
            permit["mining_plan_acres"] = money(
                D(permit["mining_plan_acres"]) + D(row["acreage_delta"])
            )
            engine.rerun_bond_determination(permit)
        elif row["revision_type"] == "PMLU_CHANGE":
            permit["post_mining_land_use"] = row["new_post_mining_land_use"]
        engine.recompute_posture(permit)
        bump(permit)
    else:
        row["status"] = "DENIED"
        row["denial_reason"] = denial_reason
        bump(row)
        # A denial changes no field on the permit at all.

    return object_response(ser.revision_out(row))
