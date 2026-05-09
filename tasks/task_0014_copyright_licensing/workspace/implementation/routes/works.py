"""Work routes."""
import copy

from flask import Blueprint

from common import check_version, get_json_body, paginate, stamp_new, stamp_update
from db import db
from errors import api_error
from middleware import optional_auth, require_roles
from response import success
from services.audit import append_audit
from services.works import (
    is_owner_or_co_owner,
    serialize_work,
    validate_co_owners_unique,
    validate_ownership_shares,
)

bp = Blueprint("works", __name__)

VALID_WORK_TYPES = {"LITERARY", "MUSIC", "FILM", "SOFTWARE", "ARTWORK"}


@bp.route("/works", methods=["POST"])
def create_work():
    user_id, role = require_roles(["RightsHolder"])
    body = get_json_body()

    title = body.get("title")
    work_type = body.get("work_type")
    creation_date = body.get("creation_date")
    primary_owner_id = body.get("primary_owner_id") or user_id
    co_owners = body.get("co_owners") or []
    primary_share_bps = body.get("primary_share_bps")
    ownership_proof_doc_id = body.get("ownership_proof_doc_id")

    if not title or not isinstance(title, str):
        raise api_error("ERR_VALIDATION", "title required")
    if work_type not in VALID_WORK_TYPES:
        raise api_error("ERR_VALIDATION", "work_type invalid")
    if not creation_date:
        raise api_error("ERR_VALIDATION", "creation_date required")
    if not primary_owner_id or primary_owner_id not in db.rights_holders:
        raise api_error("ERR_VALIDATION", "primary_owner_id invalid")
    if not isinstance(co_owners, list):
        raise api_error("ERR_VALIDATION", "co_owners must be array")

    # 12. duplicate co-owner check before share-total check
    validate_co_owners_unique(co_owners)
    # 13. ownership shares
    validate_ownership_shares(primary_share_bps, co_owners)

    work = {
        "title": title,
        "work_type": work_type,
        "creation_date": creation_date,
        "primary_owner_id": primary_owner_id,
        "co_owners": copy.deepcopy(co_owners),
        "primary_share_bps": int(primary_share_bps),
        "ownership_proof_doc_id": ownership_proof_doc_id or "",
        "registration_status": "DRAFT",
        "certificate_id": None,
        "certificate_issued_at": None,
    }
    stamp_new(work)
    db.works[work["id"]] = work
    return success(serialize_work(work), status=201)


@bp.route("/works/<work_id>", methods=["GET"])
def get_work(work_id):
    require_roles(["PlatformAdmin", "RightsHolder"])
    work = db.works.get(work_id)
    if not work:
        raise api_error("ERR_NOT_FOUND", "work not found")
    return success(serialize_work(work))


@bp.route("/works/<work_id>", methods=["PATCH"])
def patch_work(work_id):
    user_id, role = require_roles(["RightsHolder"])
    work = db.works.get(work_id)
    if not work:
        raise api_error("ERR_NOT_FOUND", "work not found")
    body = get_json_body()
    check_version(work, body)

    if work.get("registration_status") != "DRAFT":
        raise api_error("ERR_INVALID_STATE", "Work must be in DRAFT to patch")

    # Ownership: only primary_owner_id may patch.
    if user_id != work.get("primary_owner_id"):
        raise api_error("ERR_FORBIDDEN", "only the primary owner may patch this work")

    before = {
        "title": work.get("title"),
        "co_owners": copy.deepcopy(work.get("co_owners")),
        "primary_share_bps": work.get("primary_share_bps"),
        "ownership_proof_doc_id": work.get("ownership_proof_doc_id"),
    }

    new_title = body.get("title", work.get("title"))
    new_co_owners = body.get("co_owners", work.get("co_owners")) if "co_owners" in body else work.get("co_owners")
    new_primary_bps = body.get("primary_share_bps", work.get("primary_share_bps"))
    new_proof = body.get("ownership_proof_doc_id", work.get("ownership_proof_doc_id"))

    if "co_owners" in body or "primary_share_bps" in body:
        if not isinstance(new_co_owners, list):
            raise api_error("ERR_VALIDATION", "co_owners must be array")
        validate_co_owners_unique(new_co_owners)
        validate_ownership_shares(new_primary_bps, new_co_owners)

    if "title" in body:
        if not new_title or not isinstance(new_title, str):
            raise api_error("ERR_VALIDATION", "title required")

    work["title"] = new_title
    work["co_owners"] = copy.deepcopy(new_co_owners) if new_co_owners is not None else []
    work["primary_share_bps"] = int(new_primary_bps) if new_primary_bps is not None else 0
    work["ownership_proof_doc_id"] = new_proof if new_proof is not None else ""
    stamp_update(work)

    after = {
        "title": work.get("title"),
        "co_owners": copy.deepcopy(work.get("co_owners")),
        "primary_share_bps": work.get("primary_share_bps"),
        "ownership_proof_doc_id": work.get("ownership_proof_doc_id"),
    }
    append_audit(user_id, "Work", work["id"], "LICENSE_CHANGED", before, after)

    return success(serialize_work(work))


@bp.route("/works/<work_id>/submit", methods=["POST"])
def submit_work(work_id):
    user_id, role = require_roles(["RightsHolder"])
    work = db.works.get(work_id)
    if not work:
        raise api_error("ERR_NOT_FOUND", "work not found")
    body = get_json_body()
    check_version(work, body)

    if work.get("registration_status") != "DRAFT":
        raise api_error("ERR_INVALID_STATE", "Work must be in DRAFT to submit")

    if user_id != work.get("primary_owner_id"):
        raise api_error("ERR_FORBIDDEN", "only the primary owner may submit this work")

    # Preconditions: ownership shares valid and proof present.
    validate_co_owners_unique(work.get("co_owners") or [])
    validate_ownership_shares(work.get("primary_share_bps"), work.get("co_owners") or [])
    if not work.get("ownership_proof_doc_id"):
        raise api_error("ERR_OWNERSHIP_PROOF_MISSING",
                        "ownership_proof_doc_id is required to submit")

    before = {"registration_status": work["registration_status"]}
    work["registration_status"] = "UNDER_REVIEW"
    stamp_update(work)
    append_audit(user_id, "Work", work["id"], "LICENSE_CHANGED",
                 before, {"registration_status": work["registration_status"]})

    return success(serialize_work(work))


@bp.route("/works/<work_id>/rights-chain", methods=["GET"])
def list_rights_chain(work_id):
    # Public endpoint: no auth required.
    optional_auth()
    work = db.works.get(work_id)
    if not work:
        raise api_error("ERR_NOT_FOUND", "work not found")
    events = [e for e in db.rights_chain_events.values() if e.get("work_id") == work_id]
    page, meta = paginate(events)
    return success(page, response_type="array", pagination=meta)
