"""Transfer requests: create (OWNERSHIP/LOCATION), fetch, approve, reject."""
from flask import Blueprint

import errors
from auth import require_auth, ALL_READERS
from db import db, new_id, common_fields, touch
from helpers import body, out, get_or_404
import validate
from response import ok, created

bp = Blueprint("transfers", __name__)

TRANSFER_TYPES = {"OWNERSHIP", "LOCATION"}
NON_TERMINAL = {"ACTIVE", "RENEWAL_DUE", "SUSPENDED"}


@bp.route("/transfer-requests", methods=["POST"])
def create_transfer_request():
    require_auth(["Applicant", "Director"])
    data = body()
    license_id = validate.require_str(data, "license_id")
    if license_id not in db.licenses:
        raise errors.err(errors.ERR_NOT_FOUND, "License not found")
    transfer_type = validate.require_enum(data, "transfer_type", TRANSFER_TYPES)

    new_applicant_id = data.get("new_applicant_id")
    new_premise_id = data.get("new_premise_id")

    # Existence of provided FKs (priority 3) before type integrity (priority 20).
    if new_applicant_id is not None and new_applicant_id not in db.applicants:
        raise errors.err(errors.ERR_NOT_FOUND, "New applicant not found")
    if new_premise_id is not None and new_premise_id not in db.premises:
        raise errors.err(errors.ERR_NOT_FOUND, "New premise not found")

    lic = db.licenses[license_id]
    # priority 20: transfer type integrity
    if transfer_type == "OWNERSHIP":
        if not new_applicant_id or new_premise_id:
            raise errors.err(errors.ERR_TRANSFER_TYPE_INVALID,
                             "OWNERSHIP requires new_applicant_id and forbids new_premise_id")
    else:  # LOCATION
        if not new_premise_id or new_applicant_id:
            raise errors.err(errors.ERR_TRANSFER_TYPE_INVALID,
                             "LOCATION requires new_premise_id and forbids new_applicant_id")
        target_premise = db.premises[new_premise_id]
        if target_premise["region_code"] != lic["region_code"]:
            raise errors.err(errors.ERR_TRANSFER_TYPE_INVALID, "LOCATION crosses region")

    ent = {
        "id": new_id(), "license_id": license_id, "transfer_type": transfer_type,
        "new_applicant_id": new_applicant_id, "new_premise_id": new_premise_id,
        "status": "PENDING",
    }
    ent.update(common_fields())
    db.transfer_requests[ent["id"]] = ent
    return created(out(ent))


@bp.route("/transfer-requests/<id>", methods=["GET"])
def get_transfer_request(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.transfer_requests, id)
    return ok(out(ent))


@bp.route("/transfer-requests/<id>/approve", methods=["POST"])
def approve_transfer(id):
    require_auth(["Director"])
    tr = get_or_404(db.transfer_requests, id)
    if tr["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Transfer not PENDING")
    lic = db.licenses.get(tr["license_id"])
    if lic is None:
        raise errors.err(errors.ERR_NOT_FOUND, "License not found")

    # License must be ACTIVE.
    if lic["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "License not ACTIVE")
    # priority 16: outstanding fine blocks transfer approval
    if lic["outstanding_fine_cents"] > 0:
        raise errors.err(errors.ERR_OUTSTANDING_FINE, "Outstanding fine")

    if tr["transfer_type"] == "OWNERSHIP":
        new_applicant = db.applicants.get(tr["new_applicant_id"])
        if new_applicant is None:
            raise errors.err(errors.ERR_NOT_FOUND, "New applicant not found")
        # priority 6: new applicant must not be disqualified
        if new_applicant["disqualified"]:
            raise errors.err(errors.ERR_APPLICANT_DISQUALIFIED, "New applicant disqualified")
        lic["applicant_id"] = tr["new_applicant_id"]
        touch(lic)
    else:  # LOCATION
        target_premise = db.premises.get(tr["new_premise_id"])
        if target_premise is None:
            raise errors.err(errors.ERR_NOT_FOUND, "New premise not found")
        # priority 20: same-region (re-checked at approval time)
        if target_premise["region_code"] != lic["region_code"]:
            raise errors.err(errors.ERR_TRANSFER_TYPE_INVALID, "LOCATION crosses region")
        # priority 21: closed-interval premise term overlap
        _check_premise_term_overlap(lic, tr["new_premise_id"])
        lic["premise_id"] = tr["new_premise_id"]
        touch(lic)

    tr["status"] = "APPROVED"
    touch(tr)
    return ok(out(tr))


@bp.route("/transfer-requests/<id>/reject", methods=["POST"])
def reject_transfer(id):
    require_auth(["Director"])
    tr = get_or_404(db.transfer_requests, id)
    if tr["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Transfer not PENDING")
    tr["status"] = "REJECTED"
    touch(tr)
    return ok(out(tr))


def _check_premise_term_overlap(relocating, target_premise_id):
    """CLOSED-interval overlap: relocating.start <= cand.end AND cand.start <=
    relocating.end. Candidates: non-terminal same-class licenses already at the
    target premise (excluding the relocating license itself)."""
    r_start = relocating["term_start_at"]
    r_end = relocating["term_end_at"]
    for cand in db.licenses.values():
        if cand["id"] == relocating["id"]:
            continue
        if cand["status"] not in NON_TERMINAL:
            continue
        if cand["license_class_code"] != relocating["license_class_code"]:
            continue
        if cand.get("premise_id") != target_premise_id:
            continue
        if r_start <= cand["term_end_at"] and cand["term_start_at"] <= r_end:
            raise errors.err(errors.ERR_PREMISE_TERM_CONFLICT, "Premise term conflict")
