"""Proofs: approve, request-revision (revision cycle cascade), reads."""
from flask import Blueprint, request

from auth import identity, require_roles, require_ownership
from envelope import ApiError, success
from helpers import resolve, get_body, paginate_list
from store import db, touch
import models
import queries

bp = Blueprint("proof", __name__)


@bp.route("/proofs/<pid>/approve", methods=["POST"])
def approve_proof(pid):
    uid, role = identity()
    require_roles(role, {"Publisher"})
    proof = resolve("proof", pid)
    require_ownership(role, uid, "proof", proof)
    if proof["status"] != "ORDERED":
        raise ApiError("ERR_PROOF_INVALID_STATE", "Proof must be ORDERED to approve")
    proof["status"] = "APPROVED"
    touch(proof)
    return success(models.ser_proof(proof))


@bp.route("/proofs/<pid>/request-revision", methods=["POST"])
def request_revision(pid):
    uid, role = identity()
    require_roles(role, {"Publisher"})
    proof = resolve("proof", pid)
    require_ownership(role, uid, "proof", proof)
    if proof["status"] != "ORDERED":
        raise ApiError("ERR_PROOF_INVALID_STATE", "Proof must be ORDERED to request revision")
    body = get_body()
    proof["status"] = "REVISION_REQUESTED"
    proof["revision_notes"] = body.get("revision_notes")
    touch(proof)
    # cascade: unlock the format if it is CONTENT_LOCKED (closes the revision cycle)
    fmt = db.formats.get(proof["format_id"])
    if fmt and fmt["status"] == "CONTENT_LOCKED":
        fmt["status"] = "DRAFT"
        touch(fmt)
    return success(models.ser_proof(proof))


@bp.route("/proofs/<pid>", methods=["GET"])
def get_proof(pid):
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    rec = resolve("proof", pid)
    require_ownership(role, uid, "proof", rec)
    return success(models.ser_proof(rec))


@bp.route("/proofs", methods=["GET"])
def list_proofs():
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    records = list(db.proofs.values())
    if role == "Publisher":
        records = [p for p in records
                   if queries.publisher_id_of_format(db.formats.get(p["format_id"])) == uid]
    fid = request.args.get("format_id")
    if fid:
        records = [p for p in records if p.get("format_id") == fid]
    return paginate_list(records, models.ser_proof)
