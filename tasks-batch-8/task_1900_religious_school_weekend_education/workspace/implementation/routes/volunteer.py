"""VolunteerCommitment endpoints."""

from flask import Blueprint, request

from db import store, new_id
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from errors import (
    ApiError, invalid_request, invalid_state, not_found, ownership_mismatch,
)
from services.core import (
    public, get_commitment, recompute_commitment, regress_commitment_if_needed,
    touch, base_record, recompute_family_outstanding,
)

bp = Blueprint("volunteer", __name__)


@bp.route("/school/volunteer-commitments/<commitment_id>", methods=["GET"])
def get_commitment_endpoint(commitment_id):
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    rec = get_commitment(commitment_id)
    if role == "Parent" and rec["family_id"] != user_id:
        raise ownership_mismatch()
    return success_object(public(rec))


@bp.route("/school/volunteer-commitments", methods=["GET"])
def list_commitments():
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    limit, offset = parse_pagination(request.args)
    family_id = request.args.get("family_id")
    school_year_id = request.args.get("school_year_id")
    status = request.args.get("status")

    items = list(store.commitments.values())
    if role == "Parent":
        if family_id is not None and family_id != user_id:
            raise ownership_mismatch()
        items = [c for c in items if c["family_id"] == user_id]
    if family_id is not None:
        items = [c for c in items if c["family_id"] == family_id]
    if school_year_id is not None:
        items = [c for c in items if c["school_year_id"] == school_year_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([public(c) for c in page], limit, offset, total)


@bp.route("/school/volunteer-commitments/<commitment_id>/entries", methods=["POST"])
def add_entry(commitment_id):
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    rec = get_commitment(commitment_id)
    if role == "Parent" and rec["family_id"] != user_id:
        raise ownership_mismatch()
    body = request.get_json(silent=True) or {}
    hours = body.get("hours")
    note = body.get("note")
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours <= 0:
        raise invalid_request("hours must be a number > 0")
    if not isinstance(note, str):
        raise invalid_request("note is required")

    entry = {
        "entry_id": new_id(),
        "hours": hours,
        "note": note,
        "status": "ACTIVE",
        "created_at": store.now_str(),
    }
    rec["entries"].append(entry)
    logged = recompute_commitment(rec)
    if rec["status"] == "OPEN" and logged >= rec["required_hours"]:
        rec["status"] = "FULFILLED"
    touch(rec)
    return success_object(public(rec), status=201)


@bp.route("/school/volunteer-commitments/<commitment_id>/entries/<entry_id>/void", methods=["POST"])
def void_entry(commitment_id, entry_id):
    require_roles(["SchoolAdmin"])
    rec = get_commitment(commitment_id)
    entry = None
    for e in rec["entries"]:
        if e["entry_id"] == entry_id:
            entry = e
            break
    if entry is None:
        raise not_found("Entry not found")
    if entry["status"] != "ACTIVE":
        raise invalid_state("Entry is not ACTIVE")
    entry["status"] = "VOIDED"
    regress_commitment_if_needed(rec)
    return success_object(public(rec))


@bp.route("/school/volunteer-commitments/<commitment_id>/waive", methods=["POST"])
def waive_commitment(commitment_id):
    require_roles(["SchoolAdmin"])
    rec = get_commitment(commitment_id)
    if rec["status"] not in ("OPEN", "DEFAULTED"):
        raise invalid_state("Commitment cannot be waived from current state")
    was_defaulted = rec["status"] == "DEFAULTED"
    rec["status"] = "WAIVED"
    touch(rec)

    if was_defaulted:
        # void the buyout fee invoice created at default
        # find the family's VOLUNTEER_FEE invoice for this year in ISSUED/PARTIALLY_PAID
        for inv in store.invoices.values():
            if (
                inv["family_id"] == rec["family_id"]
                and inv["school_year_id"] == rec["school_year_id"]
                and inv.get("kind") == "VOLUNTEER_FEE"
                and inv["status"] in ("ISSUED", "PARTIALLY_PAID")
            ):
                inv["status"] = "VOID"
                touch(inv)
                family = store.families.get(rec["family_id"])
                if family is not None:
                    recompute_family_outstanding(family)
                    touch(family)
                break

    return success_object(public(rec))
