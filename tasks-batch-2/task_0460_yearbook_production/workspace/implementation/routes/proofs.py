"""Proof routes: create, get, list, request-changes, reopen, submit-plant,
approve-plant."""
from flask import Blueprint, request

from db import db, stamp_create, touch, sorted_by_created
from middleware import authenticate, authorize
from validators import (
    get_json_body, require, as_str, parse_pagination,
)
from lookups import get_proof_path, get_ref
from response import success_object, success_array
import serializers as ser
from services.derive import recompute_yearbook
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_LADDER_INCOMPLETE, ERR_PAGES_NOT_ALL_APPROVED,
)

bp = Blueprint("proofs", __name__)


@bp.route("/yearbooks/proofs", methods=["POST"])
def create_proof():
    _, role = authenticate()
    authorize(role, {"Adviser"})
    body = get_json_body()
    yearbook_id = as_str(require(body, "yearbook_id"), "yearbook_id")
    get_ref(db.yearbooks, yearbook_id)

    reviewer_note = body.get("reviewer_note", "")
    if reviewer_note is None:
        reviewer_note = ""
    reviewer_note = as_str(reviewer_note, "reviewer_note")

    existing = [p["round_number"] for p in db.proofs.values()
                if p["yearbook_id"] == yearbook_id]
    round_number = (max(existing) + 1) if existing else 1

    proof = {
        "yearbook_id": yearbook_id,
        "round_number": round_number,
        "reviewer_note": reviewer_note,
        "status": "OPEN",
    }
    stamp_create(proof)
    db.proofs[proof["id"]] = proof
    return success_object(ser.proof(proof), 201)


@bp.route("/yearbooks/proofs/<proof_id>", methods=["GET"])
def get_proof(proof_id):
    _, role = authenticate()
    authorize(role, {"Adviser", "Staff"})
    proof = get_proof_path(proof_id)
    return success_object(ser.proof(proof), 200)


@bp.route("/yearbooks/proofs", methods=["GET"])
def list_proofs():
    _, role = authenticate()
    authorize(role, {"Adviser", "Staff"})
    limit, offset = parse_pagination()
    yearbook_id = request.args.get("yearbook_id")
    records = list(db.proofs.values())
    if yearbook_id is not None:
        records = [r for r in records if r["yearbook_id"] == yearbook_id]
    records = sorted_by_created(records)
    total = len(records)
    page = records[offset:offset + limit]
    return success_array([ser.proof(r) for r in page], limit, offset, total, 200)


@bp.route("/yearbooks/proofs/<proof_id>/request-changes", methods=["POST"])
def request_changes_proof(proof_id):
    _, role = authenticate()
    authorize(role, {"Adviser"})
    proof = get_proof_path(proof_id)
    body = get_json_body()
    if proof["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "proof is not OPEN")
    if "reviewer_note" in body and body["reviewer_note"] is not None:
        proof["reviewer_note"] = as_str(body["reviewer_note"], "reviewer_note")
    proof["status"] = "CHANGES_REQUESTED"
    touch(proof)
    return success_object(ser.proof(proof), 200)


@bp.route("/yearbooks/proofs/<proof_id>/reopen", methods=["POST"])
def reopen_proof(proof_id):
    _, role = authenticate()
    authorize(role, {"Adviser"})
    proof = get_proof_path(proof_id)
    if proof["status"] != "CHANGES_REQUESTED":
        raise ApiError(ERR_INVALID_STATE, 409, "proof is not in CHANGES_REQUESTED")
    proof["status"] = "OPEN"
    touch(proof)
    return success_object(ser.proof(proof), 200)


@bp.route("/yearbooks/proofs/<proof_id>/submit-plant", methods=["POST"])
def submit_plant(proof_id):
    _, role = authenticate()
    authorize(role, {"Adviser"})
    proof = get_proof_path(proof_id)
    if proof["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "proof is not OPEN")

    yb = db.yearbooks.get(proof["yearbook_id"])
    pages = [p for p in db.ladder_pages.values() if p["yearbook_id"] == yb["id"]]

    # completeness gates (ladder first, then all-approved)
    ladder_complete = (len(pages) == yb["target_page_count"])
    if not ladder_complete:
        raise ApiError(ERR_LADDER_INCOMPLETE, 409, "ladder is not complete")
    if any(p["status"] != "APPROVED" for p in pages):
        raise ApiError(ERR_PAGES_NOT_ALL_APPROVED, 409, "not all pages are APPROVED")

    proof["status"] = "PLANT_SUBMITTED"
    touch(proof)

    # cascade: every APPROVED page -> LOCKED (independent touch each)
    for p in pages:
        if p["status"] == "APPROVED":
            p["status"] = "LOCKED"
            touch(p)

    recompute_yearbook(yb)
    return success_object(ser.proof(proof), 200)


@bp.route("/yearbooks/proofs/<proof_id>/approve-plant", methods=["POST"])
def approve_plant(proof_id):
    _, role = authenticate()
    authorize(role, {"Adviser"})
    proof = get_proof_path(proof_id)
    if proof["status"] != "PLANT_SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "proof is not PLANT_SUBMITTED")
    proof["status"] = "PLANT_APPROVED"
    touch(proof)
    yb = db.yearbooks.get(proof["yearbook_id"])
    if yb is not None:
        recompute_yearbook(yb)
    return success_object(ser.proof(proof), 200)
