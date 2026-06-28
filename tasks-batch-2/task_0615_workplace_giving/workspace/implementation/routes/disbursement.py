"""DisbursementBatch and Grant endpoints (PRD §3.8)."""
from flask import Blueprint, request

from db import db, parse_iso
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_STALE_BATCH_VERSION,
    ERR_CHARITY_NOT_APPROVED,
    ERR_BATCH_PERIOD_OVERLAP,
    ERR_EMPTY_BATCH,
    ERR_SOURCE_NOT_DISBURSABLE,
    ERR_SOURCE_ALREADY_GRANTED,
    ERR_GRANT_CHARITY_MISMATCH,
)
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.common import (
    get_json_body,
    require_fields,
    require_string,
    require_int,
    require_enum,
    require_datetime,
    stamp_create,
    touch,
    serialize,
    find_or_404,
    paginate,
)
from services.disbursement import settle_batch

bp = Blueprint("disbursement", __name__)

SOURCE_TYPES = {"DONATION", "MATCH", "DFD"}


def _periods_overlap_closed(a_start, a_end, b_start, b_end):
    """Closed [start, end] overlap: touching endpoints conflict."""
    return a_start <= b_end and b_start <= a_end


@bp.route("/disbursement-batches", methods=["POST"])
def open_batch():
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    body = get_json_body()
    require_fields(body, ["program_id", "charity_id", "period_start", "period_end"])
    program_id = require_string(body, "program_id")
    charity_id = require_string(body, "charity_id")
    period_start = require_datetime(body, "period_start")
    period_end = require_datetime(body, "period_end")

    find_or_404(db.programs, program_id)
    find_or_404(db.charities, charity_id)

    ps = parse_iso(period_start)
    pe = parse_iso(period_end)
    # Closed-period overlap vs existing OPEN/LOCKED/SETTLED for same charity.
    for b in db.disbursement_batches.values():
        if b["charity_id"] != charity_id:
            continue
        if b["status"] not in ("OPEN", "LOCKED", "SETTLED"):
            continue
        if _periods_overlap_closed(ps, pe, parse_iso(b["period_start"]), parse_iso(b["period_end"])):
            raise err(ERR_BATCH_PERIOD_OVERLAP,
                      "Batch coverage period overlaps an existing OPEN/LOCKED/SETTLED batch")

    rec = {
        "program_id": program_id,
        "charity_id": charity_id,
        "period_start": period_start,
        "period_end": period_end,
        "gross_total_cents": 0,
        "admin_fee_cents": 0,
        "net_total_cents": 0,
        "status": "OPEN",
    }
    stamp_create(rec)
    db.disbursement_batches[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/disbursement-batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager"})
    rec = find_or_404(db.disbursement_batches, batch_id)
    return object_response(serialize(rec), 200)


@bp.route("/disbursement-batches", methods=["GET"])
def list_batches():
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager"})
    program_id = request.args.get("program_id")
    charity_id = request.args.get("charity_id")
    status = request.args.get("status")
    items = []
    for b in db.disbursement_batches.values():
        if program_id is not None and b["program_id"] != program_id:
            continue
        if charity_id is not None and b["charity_id"] != charity_id:
            continue
        if status is not None and b["status"] != status:
            continue
        items.append(b)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(b) for b in page], limit, offset, total, 200)


def _source_lookup(source_type, source_id):
    """Resolve the source entity (existence). Returns the record or None."""
    if source_type == "DONATION":
        return db.donations.get(source_id)
    if source_type == "MATCH":
        return db.matching_gifts.get(source_id)
    if source_type == "DFD":
        return db.volunteer_logs.get(source_id)
    return None


def _source_charity_id(source_type, source):
    """Beneficiary charity for a grant source (PRD §3.8)."""
    if source_type == "DONATION":
        campaign = db.campaigns.get(source["campaign_id"])
        return campaign["charity_id"] if campaign else None
    if source_type == "MATCH":
        donation = db.donations.get(source["donation_id"])
        if donation is None:
            return None
        campaign = db.campaigns.get(donation["campaign_id"])
        return campaign["charity_id"] if campaign else None
    if source_type == "DFD":
        return source["charity_id"]
    return None


def _source_gross(source_type, source):
    if source_type == "DONATION":
        return source["base_amount_cents"]
    if source_type == "MATCH":
        return source["matched_amount_cents"]
    if source_type == "DFD":
        return source["grant_amount_cents"]
    return 0


def _source_disbursable_state(source_type):
    return {"DONATION": "SETTLED", "MATCH": "FINALIZED", "DFD": "APPROVED"}[source_type]


@bp.route("/disbursement-batches/<batch_id>/grants", methods=["POST"])
def stage_grant(batch_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    # Existence: batch (path) before body refs (priority 4).
    batch = find_or_404(db.disbursement_batches, batch_id)
    body = get_json_body()
    require_fields(body, ["source_type", "source_id", "expected_batch_version"])
    source_type = require_enum(body, "source_type", SOURCE_TYPES)
    source_id = require_string(body, "source_id")
    expected_version = require_int(body, "expected_batch_version")

    # Body-ref existence (priority 4) for source_id.
    source = _source_lookup(source_type, source_id)
    if source is None:
        raise err(ERR_NOT_FOUND, "Referenced source id does not exist")

    # OCC (priority 6) before state (priority 7).
    if expected_version != batch["version"]:
        raise err(ERR_STALE_BATCH_VERSION, "expected_batch_version does not match the live batch version")

    # State: batch must be OPEN to stage (priority 7).
    if batch["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Batch must be OPEN to stage grants")

    # Source business checks (priority 13), in pinned order:
    # 1. disbursable state
    if source["status"] != _source_disbursable_state(source_type):
        raise err(ERR_SOURCE_NOT_DISBURSABLE, "Grant source is not in a disbursable state")
    # 2. not already staged/settled elsewhere
    for g in db.grants.values():
        if g["source_type"] == source_type and g["source_id"] == source_id and g["status"] in ("STAGED", "SETTLED"):
            raise err(ERR_SOURCE_ALREADY_GRANTED, "Source already staged or settled in another grant")
    # 3. source charity must match batch charity
    src_charity = _source_charity_id(source_type, source)
    if src_charity != batch["charity_id"]:
        raise err(ERR_GRANT_CHARITY_MISMATCH, "Grant source charity differs from the batch charity")

    rec = {
        "program_id": batch["program_id"],
        "batch_id": batch["id"],
        "charity_id": batch["charity_id"],
        "source_type": source_type,
        "source_id": source_id,
        "gross_amount_cents": _source_gross(source_type, source),
        "admin_fee_cents": 0,
        "net_amount_cents": 0,
        "status": "STAGED",
    }
    stamp_create(rec)
    db.grants[rec["id"]] = rec

    # Staging bumps the batch version (makes OCC meaningful).
    touch(batch)
    return object_response(serialize(rec), 201)


@bp.route("/disbursement-batches/<batch_id>/grants", methods=["GET"])
def list_batch_grants(batch_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager"})
    find_or_404(db.disbursement_batches, batch_id)
    status = request.args.get("status")
    items = []
    for g in db.grants.values():
        if g["batch_id"] != batch_id:
            continue
        if status is not None and g["status"] != status:
            continue
        items.append(g)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(g) for g in page], limit, offset, total, 200)


@bp.route("/grants/<grant_id>", methods=["GET"])
def get_grant(grant_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager"})
    rec = find_or_404(db.grants, grant_id)
    return object_response(serialize(rec), 200)


@bp.route("/grants", methods=["GET"])
def list_grants():
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager"})
    program_id = request.args.get("program_id")
    charity_id = request.args.get("charity_id")
    batch_id = request.args.get("batch_id")
    source_id = request.args.get("source_id")
    source_type = request.args.get("source_type")
    status = request.args.get("status")
    items = []
    for g in db.grants.values():
        if program_id is not None and g["program_id"] != program_id:
            continue
        if charity_id is not None and g["charity_id"] != charity_id:
            continue
        if batch_id is not None and g["batch_id"] != batch_id:
            continue
        if source_id is not None and g["source_id"] != source_id:
            continue
        if source_type is not None and g["source_type"] != source_type:
            continue
        if status is not None and g["status"] != status:
            continue
        items.append(g)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(g) for g in page], limit, offset, total, 200)


@bp.route("/disbursement-batches/<batch_id>/lock", methods=["POST"])
def lock_batch(batch_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    batch = find_or_404(db.disbursement_batches, batch_id)
    if batch["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Batch must be OPEN to lock")
    staged = [g for g in db.grants.values()
              if g["batch_id"] == batch_id and g["status"] == "STAGED"]
    if len(staged) < 1:
        raise err(ERR_EMPTY_BATCH, "Cannot lock a batch with no STAGED grants")
    batch["status"] = "LOCKED"
    touch(batch)
    return object_response(serialize(batch), 200)


@bp.route("/disbursement-batches/<batch_id>/settle", methods=["POST"])
def settle_batch_route(batch_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    batch = find_or_404(db.disbursement_batches, batch_id)
    if batch["status"] != "LOCKED":
        raise err(ERR_INVALID_STATE, "Batch must be LOCKED to settle")
    charity = db.charities.get(batch["charity_id"])
    if charity is None or charity["status"] != "APPROVED":
        raise err(ERR_CHARITY_NOT_APPROVED, "Beneficiary charity must be APPROVED to settle")
    settle_batch(batch)
    return object_response(serialize(batch), 200)


@bp.route("/disbursement-batches/<batch_id>/void", methods=["POST"])
def void_batch(batch_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    batch = find_or_404(db.disbursement_batches, batch_id)
    if batch["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Batch must be OPEN to void")
    for g in db.grants.values():
        if g["batch_id"] == batch_id and g["status"] == "STAGED":
            g["status"] = "VOIDED"
            touch(g)
    batch["status"] = "VOIDED"
    touch(batch)
    return object_response(serialize(batch), 200)
