"""Sync license routes: create, read, list, counter, requote, accept, execute,
decline."""
from flask import Blueprint, request

import db
from errors import (fail, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
                    ERR_NOT_RESOURCE_OWNER, ERR_SHARES_NOT_LOCKED,
                    ERR_RIGHTS_NOT_AVAILABLE)
from middleware import authorize, get_auth
from response import success
from services import serialize as S
from services import calculations as C
from services.common import (stamp_create, touch, require_body, require_enum,
                             require_str, require_int, parse_pagination,
                             paginate, sorted_by_creation, parse_dt)
from services.lookup import path_get, fk_get
from services.allocation import distribute_earnings
from routes.usage_events import _rights_window_covers

bp = Blueprint("sync_licenses", __name__)

MEDIA_TYPES = {"FILM", "TV", "AD", "GAME"}


@bp.route("/sync-licenses", methods=["POST"])
def create_sync_license():
    authorize({"RoyaltyOperator"})
    data = require_body(request.get_json(silent=True))
    recording_id = data.get("recording_id")
    licensee_id = data.get("licensee_id")
    fk_get(db.recordings, recording_id)
    fk_get(db.rightsholders, licensee_id)
    media_type = require_enum(data, "media_type", MEDIA_TYPES)
    territory = require_str(data, "territory")
    term_months = require_int(data, "term_months", minimum=1)
    base_fee_cents = require_int(data, "base_fee_cents", minimum=0)
    quoted_fee_cents = C.sync_quote_fee(base_fee_cents, media_type, territory, term_months)
    rec = {
        "recording_id": recording_id,
        "licensee_id": licensee_id,
        "media_type": media_type,
        "territory": territory,
        "term_months": term_months,
        "base_fee_cents": base_fee_cents,
        "quoted_fee_cents": quoted_fee_cents,
        "status": "DRAFT",
        "counter_fee_cents": 0,
    }
    stamp_create(rec)
    db.sync_licenses[rec["id"]] = rec
    return success(S.sync_license(rec), status=201)


@bp.route("/sync-licenses/<rid>", methods=["GET"])
def get_sync_license(rid):
    authorize({"Administrator", "RoyaltyOperator", "Licensee"})
    rec = path_get(db.sync_licenses, rid)
    # Licensee may read only its own license (entity-backed ownership).
    user_id, role = get_auth()
    if role == "Licensee" and rec["licensee_id"] != user_id:
        fail(ERR_NOT_RESOURCE_OWNER, "Licensee does not own this sync license")
    return success(S.sync_license(rec))


@bp.route("/sync-licenses", methods=["GET"])
def list_sync_licenses():
    user_id, role = authorize({"Administrator", "RoyaltyOperator", "Licensee"})
    limit, offset = parse_pagination(request.args)
    items = list(db.sync_licenses.values())
    licensee_id = request.args.get("licensee_id")
    recording_id = request.args.get("recording_id")
    status = request.args.get("status")
    if licensee_id is not None:
        items = [s for s in items if s["licensee_id"] == licensee_id]
    if recording_id is not None:
        items = [s for s in items if s["recording_id"] == recording_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    # Licensee sees only its own licenses (PRD §1.7 RBAC).
    if role == "Licensee":
        items = [s for s in items if s["licensee_id"] == user_id]
    items = sorted_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return success([S.sync_license(s) for s in page], pagination=meta)


@bp.route("/sync-licenses/<rid>/counter", methods=["POST"])
def counter_sync_license(rid):
    user_id, role = authorize({"Licensee"})
    rec = path_get(db.sync_licenses, rid)
    # State (priority 6) before ownership (priority 7) per §2.8.
    if rec["status"] != "DRAFT":
        fail(ERR_INVALID_STATE, "Counter requires DRAFT status")
    if rec["licensee_id"] != user_id:
        fail(ERR_NOT_RESOURCE_OWNER, "Licensee does not own this sync license")
    data = require_body(request.get_json(silent=True))
    counter_fee_cents = require_int(data, "counter_fee_cents", minimum=1)
    rec["counter_fee_cents"] = counter_fee_cents
    rec["status"] = "COUNTERED"
    touch(rec)
    return success(S.sync_license(rec))


@bp.route("/sync-licenses/<rid>/requote", methods=["POST"])
def requote_sync_license(rid):
    authorize({"RoyaltyOperator"})
    rec = path_get(db.sync_licenses, rid)
    if rec["status"] != "COUNTERED":
        fail(ERR_INVALID_STATE, "Requote requires COUNTERED status")
    data = require_body(request.get_json(silent=True))
    base_fee_cents = require_int(data, "base_fee_cents", minimum=0)
    rec["base_fee_cents"] = base_fee_cents
    rec["quoted_fee_cents"] = C.sync_quote_fee(
        base_fee_cents, rec["media_type"], rec["territory"], rec["term_months"])
    rec["status"] = "DRAFT"
    touch(rec)
    return success(S.sync_license(rec))


def _sync_window_covers(recording_id, territory):
    """True if an ACTIVE SYNC window on the recording covers the territory.
    No instant check for sync accept (PRD §3.4)."""
    for w in db.rights_windows.values():
        if w["recording_id"] != recording_id:
            continue
        if w["status"] != "ACTIVE" or w["rights_type"] != "SYNC":
            continue
        if w["territory"] == "WW" or w["territory"] == territory:
            return True
    return False


@bp.route("/sync-licenses/<rid>/accept", methods=["POST"])
def accept_sync_license(rid):
    user_id, role = authorize({"Licensee", "RoyaltyOperator"})
    rec = path_get(db.sync_licenses, rid)
    if role == "Licensee":
        # Licensee accepts from DRAFT (PRD §3.4).
        if rec["status"] != "DRAFT":
            fail(ERR_INVALID_STATE, "Licensee may accept only from DRAFT")
        if rec["licensee_id"] != user_id:
            fail(ERR_NOT_RESOURCE_OWNER, "Licensee does not own this sync license")
        if not _sync_window_covers(rec["recording_id"], rec["territory"]):
            fail(ERR_RIGHTS_NOT_AVAILABLE, "No covering ACTIVE SYNC window")
        rec["status"] = "ACCEPTED"
        touch(rec)
    else:  # RoyaltyOperator accepts from COUNTERED
        if rec["status"] != "COUNTERED":
            fail(ERR_INVALID_STATE, "Operator may accept only from COUNTERED")
        if not _sync_window_covers(rec["recording_id"], rec["territory"]):
            fail(ERR_RIGHTS_NOT_AVAILABLE, "No covering ACTIVE SYNC window")
        # Operator accepts the licensee's counter.
        rec["quoted_fee_cents"] = rec["counter_fee_cents"]
        rec["status"] = "ACCEPTED"
        touch(rec)
    return success(S.sync_license(rec))


@bp.route("/sync-licenses/<rid>/execute", methods=["POST"])
def execute_sync_license(rid):
    authorize({"RoyaltyOperator"})
    rec = path_get(db.sync_licenses, rid)
    if rec["status"] != "ACCEPTED":
        fail(ERR_INVALID_STATE, "Execute requires ACCEPTED status")
    recording = db.recordings[rec["recording_id"]]
    work = db.works[recording["work_id"]]
    if not (work["shares_locked"] and recording["shares_locked"]):
        fail(ERR_SHARES_NOT_LOCKED, "Work and Recording shares must both be locked")
    # Open-statement check uses the server clock current UTC (PRD §3.4).
    now_iso = db.get_clock()
    instant_dt = parse_dt(now_iso) if now_iso else parse_dt(db.now_iso())
    holders = [{"rightsholder_id": s["rightsholder_id"], "split_bps": s["split_bps"]}
               for s in db.recording_shares.values()
               if s["recording_id"] == recording["id"]]
    allocations = C.allocate_to_holders(rec["quoted_fee_cents"], holders)
    # Atomic: raises ERR_NO_OPEN_STATEMENT before writing anything.
    distribute_earnings(allocations, instant_dt, "SYNC_LICENSE", rec["id"])
    rec["status"] = "EXECUTED"
    touch(rec)
    return success(S.sync_license(rec))


@bp.route("/sync-licenses/<rid>/decline", methods=["POST"])
def decline_sync_license(rid):
    authorize({"RoyaltyOperator"})
    rec = path_get(db.sync_licenses, rid)
    if rec["status"] not in ("DRAFT", "COUNTERED"):
        fail(ERR_INVALID_STATE, "Decline requires DRAFT or COUNTERED status")
    rec["status"] = "DECLINED"
    touch(rec)
    return success(S.sync_license(rec))
