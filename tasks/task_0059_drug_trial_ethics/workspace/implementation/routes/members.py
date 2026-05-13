from __future__ import annotations

"""Committee member + conflict declaration endpoints."""

from flask import Blueprint, g, request

import db
from errors import ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_FORBIDDEN, raise_error
from middleware import require_role
from response import success_array, success_object
from serializers import serialize_committee_member, serialize_conflict
import services_state as svc
from validation import (
    get_json_body,
    get_pagination,
    optional_array_of_strings,
    optional_enum,
    require_datetime,
    require_enum,
    require_string,
    sort_default,
)


bp = Blueprint("members", __name__)

QUALIFICATIONS = {"MEDICAL_EXPERT", "PHARMACOLOGIST", "ETHICIST",
                  "LEGAL_EXPERT", "LAY_REPRESENTATIVE", "STATISTICIAN"}
CONFLICT_TYPES = {"SPONSOR_RELATION", "CO_AUTHOR", "ECONOMIC_INTEREST"}


# ---------------------------------------------------------------------------
# POST /ethics/members
# ---------------------------------------------------------------------------
@bp.post("/ethics/members")
def create_member():
    require_role({"Secretary"})
    body = get_json_body()
    full_name = require_string(body, "full_name", min_len=1, max_len=200)
    qualification = require_enum(body, "qualification", QUALIFICATIONS)
    term_start = require_datetime(body, "term_start")
    term_end = require_datetime(body, "term_end")
    affiliated = optional_array_of_strings(body, "affiliated_sponsors")

    with db.lock:
        m = svc.new_versioned({
            "full_name": full_name,
            "qualification": qualification,
            "term_start": term_start,
            "term_end": term_end,
            "status": "ACTIVE",
            "affiliated_sponsors": affiliated,
            "_creator_role": g.user_role,
            "_creator_id": g.user_id,
        })
        db.committee_members[m["id"]] = m
        svc.maybe_auto_declare_conflicts_on_member_create(m)
    return success_object(serialize_committee_member(m), 201)


# ---------------------------------------------------------------------------
# GET /ethics/members/{id}
# ---------------------------------------------------------------------------
@bp.get("/ethics/members/<mid>")
def get_member(mid):
    require_role({"Secretary", "Chairperson", "CommitteeMember"})
    m = db.committee_members.get(mid)
    if not m:
        raise_error(ERR_NOT_FOUND, f"CommitteeMember {mid} not found")
    return success_object(serialize_committee_member(m))


# ---------------------------------------------------------------------------
# GET /ethics/members
# ---------------------------------------------------------------------------
@bp.get("/ethics/members")
def list_members():
    require_role({"Secretary", "Chairperson", "CommitteeMember"})
    limit, offset = get_pagination()
    status_f = request.args.get("status")
    qual_f = request.args.get("qualification")
    is_active_f = request.args.get("is_active")
    rows = list(db.committee_members.values())
    if status_f:
        rows = [r for r in rows if r["status"] == status_f]
    if qual_f:
        rows = [r for r in rows if r["qualification"] == qual_f]
    if is_active_f is not None:
        want = str(is_active_f).lower() in ("true", "1", "yes")
        rows = [r for r in rows if svc.compute_member_is_active(r) == want]
    rows = sort_default(rows)
    total = len(rows)
    page = svc.paginate(rows, limit, offset)
    return success_array([serialize_committee_member(r) for r in page],
                         limit=limit, offset=offset, total_count=total)


# ---------------------------------------------------------------------------
# POST /ethics/members/{id}/conflicts
# ---------------------------------------------------------------------------
@bp.post("/ethics/members/<mid>/conflicts")
def create_conflict(mid):
    require_role({"Secretary", "CommitteeMember"})
    m = db.committee_members.get(mid)
    if not m:
        raise_error(ERR_NOT_FOUND, f"CommitteeMember {mid} not found")
    body = get_json_body()
    application_id = require_string(body, "application_id")
    conflict_type = require_enum(body, "conflict_type", CONFLICT_TYPES)
    details = require_string(body, "details", min_len=1, max_len=2000)

    app = db.applications.get(application_id)
    if not app:
        raise_error(ERR_REFERENCE_NOT_FOUND, f"application_id {application_id} not found")

    # CommitteeMember acting on own conflicts: enforce identity ownership
    if g.user_role == "CommitteeMember" and mid != g.user_id:
        raise_error(ERR_FORBIDDEN,
                    "CommitteeMember may only declare conflicts on their own membership")

    with db.lock:
        cd = svc.new_append_only({
            "member_id": mid,
            "application_id": application_id,
            "conflict_type": conflict_type,
            "details": details,
            "auto_detected": False,
        })
        db.conflict_declarations[cd["id"]] = cd
        svc.write_audit(g.user_role, g.user_id, "MEMBER_RECUSAL",
                        "ConflictDeclaration", cd["id"],
                        {"member_id": mid, "application_id": application_id,
                         "conflict_type": conflict_type})
    return success_object(serialize_conflict(cd), 201)


# ---------------------------------------------------------------------------
# GET /ethics/members/{id}/conflicts
# ---------------------------------------------------------------------------
@bp.get("/ethics/members/<mid>/conflicts")
def list_conflicts(mid):
    require_role({"Secretary", "CommitteeMember", "Chairperson"})
    m = db.committee_members.get(mid)
    if not m:
        raise_error(ERR_NOT_FOUND, f"CommitteeMember {mid} not found")
    limit, offset = get_pagination()
    rows = [c for c in db.conflict_declarations.values() if c["member_id"] == mid]
    rows = sort_default(rows)
    total = len(rows)
    page = svc.paginate(rows, limit, offset)
    return success_array([serialize_conflict(r) for r in page],
                         limit=limit, offset=offset, total_count=total)
