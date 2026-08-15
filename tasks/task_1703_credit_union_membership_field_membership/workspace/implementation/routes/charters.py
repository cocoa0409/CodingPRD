"""Charter, segments, and charter amendment application endpoints."""
from flask import Blueprint, request

import db
from auth import require_roles, STAFF_ROLES
from errors import ApiError
from response import ok_object, paginate, now_iso
from serializers import (serialize_charter, serialize_segment, serialize_amendment)
from services.sweep import new_id, bump
from validators import (get_body, req_str, req_int, req_enum, req_date,
                        req_doc_codes, req_str_array)

bp = Blueprint("charters", __name__)

BOND_TYPES = {"SINGLE_OCCUPATIONAL", "COMMUNITY", "ASSOCIATIONAL", "MULTIPLE_COMMON_BOND"}
SEGMENT_TYPES = {"OCCUPATIONAL", "COMMUNITY", "ASSOCIATIONAL"}

BOND_COMPATIBLE = {
    "SINGLE_OCCUPATIONAL": {"OCCUPATIONAL"},
    "COMMUNITY": {"COMMUNITY"},
    "ASSOCIATIONAL": {"ASSOCIATIONAL"},
    "MULTIPLE_COMMON_BOND": {"OCCUPATIONAL", "COMMUNITY", "ASSOCIATIONAL"},
}


def _get_charter_or_404(charter_id):
    c = db.charters.get(charter_id)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", f"charter {charter_id} not found")
    return c


@bp.post("/credit-union/charters")
def create_charter():
    require_roles({"BoardDirector"})
    body = get_body()
    bond_type = req_enum(body, "bond_type", BOND_TYPES)
    par_value_cents = req_int(body, "par_value_cents")
    if par_value_cents <= 0:
        raise ApiError("ERR_VALIDATION_FAILED", "par_value_cents must be a positive integer")
    segs_in = body.get("segments")
    if not isinstance(segs_in, list):
        raise ApiError("ERR_VALIDATION_FAILED", "segments must be an array")
    parsed_segments = []
    for el in segs_in:
        if not isinstance(el, dict):
            raise ApiError("ERR_VALIDATION_FAILED", "each segment must be an object")
        parsed_segments.append({
            "segment_type": req_enum(el, "segment_type", SEGMENT_TYPES),
            "descriptor": req_str(el, "descriptor"),
            "required_documents": req_doc_codes(el, "required_documents"),
        })
    # Tier 10: singleton
    if db.charters:
        raise ApiError("ERR_CHARTER_ALREADY_EXISTS", "a charter already exists")
    charter = {
        "id": new_id(),
        "bond_type": bond_type,
        "par_value_cents": par_value_cents,
        "status": "ACTIVE",
        "note": "",
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "_seq": db.next_seq(),
    }
    db.charters[charter["id"]] = charter
    for ps in parsed_segments:
        seg = {
            "id": new_id(),
            "charter_id": charter["id"],
            "segment_type": ps["segment_type"],
            "descriptor": ps["descriptor"],
            "required_documents": ps["required_documents"],
            "status": "ACTIVE",
            "retired_at": None,
            "version": 1,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "_seq": db.next_seq(),
        }
        db.segments[seg["id"]] = seg
    return ok_object(serialize_charter(charter), 201)


@bp.get("/credit-union/charters/<cid>")
def get_charter(cid):
    require_roles(STAFF_ROLES)
    charter = _get_charter_or_404(cid)
    return ok_object(serialize_charter(charter), 200)


@bp.get("/credit-union/charters/<cid>/segments")
def list_segments(cid):
    require_roles(STAFF_ROLES)
    _get_charter_or_404(cid)
    items = [s for s in db.segments.values() if s["charter_id"] == cid]
    status_f = request.args.get("status")
    if status_f is not None:
        items = [s for s in items if s["status"] == status_f]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return paginate([serialize_segment(s) for s in items])


@bp.get("/credit-union/charters/<cid>/amendment-applications")
def list_charter_amendments(cid):
    require_roles(STAFF_ROLES)
    _get_charter_or_404(cid)
    items = [a for a in db.amendments.values() if a["charter_id"] == cid]
    status_f = request.args.get("status")
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return paginate([serialize_amendment(a) for a in items])


# ---------------------------------------------------------------------------
# Charter amendment applications
# ---------------------------------------------------------------------------

def _get_amendment_or_404(aid):
    a = db.amendments.get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", f"amendment application {aid} not found")
    return a


@bp.post("/credit-union/charter-amendment-applications")
def create_amendment():
    uid, _ = require_roles({"ComplianceOfficer"})
    body = get_body()
    # Tier 4: syntactic
    amendment_type = req_enum(body, "amendment_type", {"ADD_SEGMENT", "RETIRE_SEGMENT"})
    charter_id = req_str(body, "charter_id")
    effective_date = req_date(body, "effective_date")
    expected_charter_version = req_int(body, "expected_charter_version")
    proposed_type = proposed_desc = proposed_docs = None
    retire_ids = None
    if amendment_type == "ADD_SEGMENT":
        proposed_type = req_enum(body, "proposed_segment_type", SEGMENT_TYPES)
        proposed_desc = req_str(body, "proposed_segment_descriptor")
        proposed_docs = req_doc_codes(body, "proposed_segment_required_documents")
    else:
        retire_ids = req_str_array(body, "retire_segment_ids")
        if not retire_ids:
            raise ApiError("ERR_VALIDATION_FAILED",
                           "retire_segment_ids must be a non-empty array")
    # Tier 5: existence
    charter = _get_charter_or_404(charter_id)
    if retire_ids is not None:
        for sid in retire_ids:
            if sid not in db.segments:
                raise ApiError("ERR_NOT_FOUND", f"segment {sid} not found")
    # Tier 6: OCC
    if expected_charter_version != charter["version"]:
        raise ApiError("ERR_STALE_CHARTER_VERSION",
                       "expected_charter_version does not match the charter version")
    # Tier 9: bond-type compatibility
    if amendment_type == "ADD_SEGMENT" \
            and proposed_type not in BOND_COMPATIBLE[charter["bond_type"]]:
        raise ApiError("ERR_BOND_TYPE_MISMATCH",
                       "proposed segment type incompatible with charter bond_type")
    # Tier 11: effective date strictly future
    if effective_date <= db.clock.current_date_str():
        raise ApiError("ERR_EFFECTIVE_DATE_NOT_FUTURE",
                       "effective_date must be strictly later than the current date")
    amendment = {
        "id": new_id(),
        "charter_id": charter_id,
        "amendment_type": amendment_type,
        "proposed_segment_type": proposed_type,
        "proposed_segment_descriptor": proposed_desc,
        "proposed_segment_required_documents": proposed_docs,
        "retire_segment_ids": retire_ids,
        "effective_date": effective_date,
        "baseline_charter_version": expected_charter_version,
        "status": "SUBMITTED",
        "submitted_by_user_id": uid,
        "decided_by_user_id": None,
        "denial_reason": None,
        "applied_segment_id": None,
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "_seq": db.next_seq(),
    }
    db.amendments[amendment["id"]] = amendment
    # Baseline rebinding: every accepted submission bumps the charter version.
    charter["version"] += 1
    charter["updated_at"] = now_iso()
    return ok_object(serialize_amendment(amendment), 201)


@bp.post("/credit-union/charter-amendment-applications/<aid>/approve")
def approve_amendment(aid):
    uid, _ = require_roles({"Regulator"})
    amendment = _get_amendment_or_404(aid)
    if amendment["status"] != "SUBMITTED":
        raise ApiError("ERR_AMENDMENT_INVALID_STATE",
                       "amendment application is not SUBMITTED")
    if amendment["effective_date"] <= db.clock.current_date_str():
        raise ApiError("ERR_EFFECTIVE_DATE_NOT_FUTURE",
                       "effective_date must be strictly later than the current date")
    amendment["status"] = "APPROVED"
    amendment["decided_by_user_id"] = uid
    bump(amendment)
    return ok_object(serialize_amendment(amendment), 200)


@bp.post("/credit-union/charter-amendment-applications/<aid>/deny")
def deny_amendment(aid):
    uid, _ = require_roles({"Regulator"})
    body = get_body()
    denial_reason = req_str(body, "denial_reason")
    amendment = _get_amendment_or_404(aid)
    if amendment["status"] != "SUBMITTED":
        raise ApiError("ERR_AMENDMENT_INVALID_STATE",
                       "amendment application is not SUBMITTED")
    amendment["status"] = "DENIED"
    amendment["denial_reason"] = denial_reason
    amendment["decided_by_user_id"] = uid
    bump(amendment)
    return ok_object(serialize_amendment(amendment), 200)
