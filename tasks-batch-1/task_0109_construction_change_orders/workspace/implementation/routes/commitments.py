"""Subcontractor-commitment endpoints (PRD §3.6)."""
from flask import Blueprint, request

import db
import helpers as h
from errors import err, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import authenticate, require_role
from response import success

bp = Blueprint("commitments", __name__)


def _get_or_404(cid):
    c = db.subcontractor_commitments.get(cid)
    if c is None:
        raise err(ERR_NOT_FOUND, "SubcontractorCommitment not found.")
    return c


@bp.post("/subcontractor-commitments")
def create_commitment():
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    body = h.get_json()
    h.require_fields(body, ["project_id", "subcontractor_name", "committed_amount_cents"])

    project_id = h.as_string(body["project_id"], "project_id")
    if db.projects.get(project_id) is None:
        raise err(ERR_NOT_FOUND, "Project not found.")
    name = h.as_nonempty_string(body["subcontractor_name"], "subcontractor_name")
    committed = h.as_int(body["committed_amount_cents"], "committed_amount_cents", minimum=1)

    record = {
        "project_id": project_id,
        "subcontractor_name": name,
        "committed_amount_cents": committed,
        "invoiced_to_date_cents": 0,
        "status": "OPEN",
    }
    db.stamp_create(record)
    db.subcontractor_commitments[record["id"]] = record
    return success(h.subcontractor_commitment_out(record), status=201)


@bp.get("/subcontractor-commitments/<cid>")
def get_commitment(cid):
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    return success(h.subcontractor_commitment_out(_get_or_404(cid)))


@bp.get("/subcontractor-commitments")
def list_commitments():
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    limit, offset = h.parse_pagination()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    records = list(db.subcontractor_commitments.values())
    if project_id:
        records = [r for r in records if r["project_id"] == project_id]
    if status:
        records = [r for r in records if r["status"] == status]
    page, meta = h.paginate(records, limit, offset)
    return success([h.subcontractor_commitment_out(r) for r in page], pagination=meta)


@bp.post("/subcontractor-commitments/<cid>/close")
def close_commitment(cid):
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    c = _get_or_404(cid)
    if c["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Commitment is not OPEN.")
    if c["invoiced_to_date_cents"] != c["committed_amount_cents"]:
        raise err(ERR_INVALID_STATE, "Commitment is not fully invoiced.")
    c["status"] = "CLOSED"
    db.touch(c)
    return success(h.subcontractor_commitment_out(c))
