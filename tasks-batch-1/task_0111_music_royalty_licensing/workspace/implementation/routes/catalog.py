"""Catalog routes: rightsholders, works, composition-shares, recordings,
recording-shares, rights-windows."""
from flask import Blueprint, request

import db
from errors import (fail, ERR_INVALID_STATE, ERR_DUPLICATE_CODE,
                    ERR_SPLIT_TOTAL_INVALID, ERR_SHARES_LOCKED,
                    ERR_WINDOW_OVERLAP)
from middleware import authorize
from response import success
from services import serialize as S
from services.common import (stamp_create, touch, require_body, require_str,
                             require_enum, require_int, optional_int,
                             optional_number, require_datetime,
                             parse_pagination, paginate, sorted_by_creation,
                             parse_dt)
from services.lookup import path_get, fk_get, require_owner

bp = Blueprint("catalog", __name__)

PARTY_TYPES = {"WRITER", "PUBLISHER", "LABEL"}
PRO_AFFILIATIONS = {"ASCAP", "BMI", "NONE"}
SHARE_ROLES = {"WRITER", "PUBLISHER"}
RELEASE_TYPES = {"STREAMING", "PHYSICAL"}
RIGHTS_TYPES = {"SYNC", "MECHANICAL", "PERFORMANCE"}

SECONDS_PER_DAY = 86400


# ---------------------------------------------------------------------------
# Rightsholders
# ---------------------------------------------------------------------------
@bp.route("/rightsholders", methods=["POST"])
def create_rightsholder():
    authorize({"Administrator"})
    data = require_body(request.get_json(silent=True))
    legal_name = require_str(data, "legal_name")
    party_type = require_enum(data, "party_type", PARTY_TYPES)
    payee_country = require_str(data, "payee_country")
    minimum_payout_cents = optional_int(data, "minimum_payout_cents", 5000, minimum=0)
    withholding_pct = optional_number(data, "withholding_pct", 0, minimum=0, maximum=0.30)
    rec = {
        "legal_name": legal_name,
        "party_type": party_type,
        "payee_country": payee_country,
        "minimum_payout_cents": minimum_payout_cents,
        "withholding_pct": withholding_pct,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.rightsholders[rec["id"]] = rec
    return success(S.rightsholder(rec), status=201)


@bp.route("/rightsholders/<rid>", methods=["GET"])
def get_rightsholder(rid):
    _, role = authorize({"Administrator", "RoyaltyOperator", "Rightsholder"})
    rec = path_get(db.rightsholders, rid)
    user_id = request.headers.get("X-User-ID")
    require_owner(rec["id"], user_id, role)
    return success(S.rightsholder(rec))


@bp.route("/rightsholders/<rid>/suspend", methods=["POST"])
def suspend_rightsholder(rid):
    authorize({"Administrator"})
    rec = path_get(db.rightsholders, rid)
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(S.rightsholder(rec))


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------
@bp.route("/works", methods=["POST"])
def create_work():
    authorize({"Administrator"})
    data = require_body(request.get_json(silent=True))
    title = require_str(data, "title")
    iswc = require_str(data, "iswc")
    pro_affiliation = require_enum(data, "pro_affiliation", PRO_AFFILIATIONS)
    duration_seconds = require_int(data, "duration_seconds", minimum=1)
    # ERR_DUPLICATE_CODE: iswc unique across works (priority 8).
    for w in db.works.values():
        if w["iswc"] == iswc:
            fail(ERR_DUPLICATE_CODE, "ISWC already exists")
    rec = {
        "title": title,
        "iswc": iswc,
        "pro_affiliation": pro_affiliation,
        "duration_seconds": duration_seconds,
        "shares_locked": False,
    }
    stamp_create(rec)
    db.works[rec["id"]] = rec
    return success(S.work(rec), status=201)


@bp.route("/works/<rid>", methods=["GET"])
def get_work(rid):
    authorize({"Administrator", "RoyaltyOperator", "Rightsholder", "Licensee"})
    rec = path_get(db.works, rid)
    return success(S.work(rec))


@bp.route("/works/<rid>/register", methods=["POST"])
def register_work(rid):
    authorize({"Administrator"})
    rec = path_get(db.works, rid)
    # State precondition: shares_locked is a boolean gate; re-registering a
    # locked work has no defined transition -> ERR_INVALID_STATE.
    if rec["shares_locked"]:
        fail(ERR_INVALID_STATE, "Work shares already locked")
    if S.work_split_total(rid) != 10000:
        fail(ERR_SPLIT_TOTAL_INVALID, "split_total_bps must equal exactly 10000 to register")
    rec["shares_locked"] = True
    touch(rec)
    return success(S.work(rec))


# ---------------------------------------------------------------------------
# Composition shares
# ---------------------------------------------------------------------------
@bp.route("/composition-shares", methods=["POST"])
def create_composition_share():
    authorize({"Administrator"})
    data = require_body(request.get_json(silent=True))
    # FK existence (priority 4) before body well-formedness (priority 5).
    # A missing/absent FK value cannot resolve -> ERR_FK_NOT_FOUND.
    work_id = data.get("work_id")
    rightsholder_id = data.get("rightsholder_id")
    work = fk_get(db.works, work_id)
    fk_get(db.rightsholders, rightsholder_id)
    role = require_enum(data, "role", SHARE_ROLES)
    split_bps = require_int(data, "split_bps", minimum=1, maximum=10000)
    # State / lock check (priority 10) then split-total constraint (priority 9).
    if work["shares_locked"]:
        fail(ERR_SHARES_LOCKED, "Work shares are locked")
    current_total = S.work_split_total(work_id)
    if current_total + split_bps > 10000:
        fail(ERR_SPLIT_TOTAL_INVALID, "Share would push split_total_bps above 10000")
    rec = {
        "work_id": work_id,
        "rightsholder_id": rightsholder_id,
        "role": role,
        "split_bps": split_bps,
    }
    stamp_create(rec)
    db.composition_shares[rec["id"]] = rec
    return success(S.composition_share(rec), status=201)


@bp.route("/composition-shares/<rid>", methods=["GET"])
def get_composition_share(rid):
    authorize({"Administrator", "RoyaltyOperator"})
    rec = path_get(db.composition_shares, rid)
    return success(S.composition_share(rec))


@bp.route("/composition-shares", methods=["GET"])
def list_composition_shares():
    authorize({"Administrator", "RoyaltyOperator"})
    limit, offset = parse_pagination(request.args)
    items = list(db.composition_shares.values())
    work_id = request.args.get("work_id")
    rightsholder_id = request.args.get("rightsholder_id")
    role = request.args.get("role")
    if work_id is not None:
        items = [s for s in items if s["work_id"] == work_id]
    if rightsholder_id is not None:
        items = [s for s in items if s["rightsholder_id"] == rightsholder_id]
    if role is not None:
        items = [s for s in items if s["role"] == role]
    items = sorted_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return success([S.composition_share(s) for s in page], pagination=meta)


# ---------------------------------------------------------------------------
# Recordings
# ---------------------------------------------------------------------------
@bp.route("/recordings", methods=["POST"])
def create_recording():
    authorize({"Administrator"})
    data = require_body(request.get_json(silent=True))
    work_id = data.get("work_id")
    fk_get(db.works, work_id)
    isrc = require_str(data, "isrc")
    title = require_str(data, "title")
    release_type = require_enum(data, "release_type", RELEASE_TYPES)
    duration_seconds = require_int(data, "duration_seconds", minimum=1)
    for r in db.recordings.values():
        if r["isrc"] == isrc:
            fail(ERR_DUPLICATE_CODE, "ISRC already exists")
    rec = {
        "work_id": work_id,
        "isrc": isrc,
        "title": title,
        "release_type": release_type,
        "duration_seconds": duration_seconds,
        "shares_locked": False,
    }
    stamp_create(rec)
    db.recordings[rec["id"]] = rec
    return success(S.recording(rec), status=201)


@bp.route("/recordings/<rid>", methods=["GET"])
def get_recording(rid):
    authorize({"Administrator", "RoyaltyOperator", "Licensee"})
    rec = path_get(db.recordings, rid)
    return success(S.recording(rec))


@bp.route("/recordings", methods=["GET"])
def list_recordings():
    authorize({"Administrator", "RoyaltyOperator", "Licensee"})
    limit, offset = parse_pagination(request.args)
    items = list(db.recordings.values())
    work_id = request.args.get("work_id")
    release_type = request.args.get("release_type")
    if work_id is not None:
        items = [r for r in items if r["work_id"] == work_id]
    if release_type is not None:
        items = [r for r in items if r["release_type"] == release_type]
    items = sorted_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return success([S.recording(r) for r in page], pagination=meta)


@bp.route("/recordings/<rid>/lock-shares", methods=["POST"])
def lock_recording_shares(rid):
    authorize({"Administrator"})
    rec = path_get(db.recordings, rid)
    if rec["shares_locked"]:
        fail(ERR_INVALID_STATE, "Recording shares already locked")
    if S.recording_split_total(rid) != 10000:
        fail(ERR_SPLIT_TOTAL_INVALID, "split_total_bps must equal exactly 10000 to lock")
    rec["shares_locked"] = True
    touch(rec)
    return success(S.recording(rec))


# ---------------------------------------------------------------------------
# Recording shares
# ---------------------------------------------------------------------------
@bp.route("/recording-shares", methods=["POST"])
def create_recording_share():
    authorize({"Administrator"})
    data = require_body(request.get_json(silent=True))
    recording_id = data.get("recording_id")
    rightsholder_id = data.get("rightsholder_id")
    recording = fk_get(db.recordings, recording_id)
    fk_get(db.rightsholders, rightsholder_id)
    split_bps = require_int(data, "split_bps", minimum=1, maximum=10000)
    if recording["shares_locked"]:
        fail(ERR_SHARES_LOCKED, "Recording shares are locked")
    current_total = S.recording_split_total(recording_id)
    if current_total + split_bps > 10000:
        fail(ERR_SPLIT_TOTAL_INVALID, "Share would push split_total_bps above 10000")
    rec = {
        "recording_id": recording_id,
        "rightsholder_id": rightsholder_id,
        "split_bps": split_bps,
    }
    stamp_create(rec)
    db.recording_shares[rec["id"]] = rec
    return success(S.recording_share(rec), status=201)


@bp.route("/recording-shares/<rid>", methods=["GET"])
def get_recording_share(rid):
    authorize({"Administrator", "RoyaltyOperator"})
    rec = path_get(db.recording_shares, rid)
    return success(S.recording_share(rec))


@bp.route("/recording-shares", methods=["GET"])
def list_recording_shares():
    authorize({"Administrator", "RoyaltyOperator"})
    limit, offset = parse_pagination(request.args)
    items = list(db.recording_shares.values())
    recording_id = request.args.get("recording_id")
    rightsholder_id = request.args.get("rightsholder_id")
    if recording_id is not None:
        items = [s for s in items if s["recording_id"] == recording_id]
    if rightsholder_id is not None:
        items = [s for s in items if s["rightsholder_id"] == rightsholder_id]
    items = sorted_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return success([S.recording_share(s) for s in page], pagination=meta)


# ---------------------------------------------------------------------------
# Rights windows
# ---------------------------------------------------------------------------
@bp.route("/rights-windows", methods=["POST"])
def create_rights_window():
    authorize({"Administrator"})
    data = require_body(request.get_json(silent=True))
    recording_id = data.get("recording_id")
    fk_get(db.recordings, recording_id)
    territory = require_str(data, "territory")
    rights_type = require_enum(data, "rights_type", RIGHTS_TYPES)
    term_start_dt = require_datetime(data, "term_start")
    term_end_dt = require_datetime(data, "term_end")
    # Overlap check (priority 14) against ACTIVE same-type windows on same
    # recording + territory.
    new_start = term_start_dt.timestamp()
    new_end = term_end_dt.timestamp()
    for w in db.rights_windows.values():
        if w["recording_id"] != recording_id:
            continue
        if w["rights_type"] != rights_type:
            continue
        if w["territory"] != territory:
            continue
        if w["status"] != "ACTIVE":
            continue
        ex_start = parse_dt(w["term_start"]).timestamp()
        ex_end = parse_dt(w["term_end"]).timestamp()
        if rights_type == "SYNC":
            # 86400s cooldown buffer: ok if new_start >= ex_end+buf OR
            # new_end+buf <= ex_start.
            ok = (new_start >= ex_end + SECONDS_PER_DAY) or \
                 (new_end + SECONDS_PER_DAY <= ex_start)
        else:
            # plain half-open: touching boundaries allowed; interior overlap bad.
            # non-overlap when new_start >= ex_end OR new_end <= ex_start.
            ok = (new_start >= ex_end) or (new_end <= ex_start)
        if not ok:
            fail(ERR_WINDOW_OVERLAP, "Rights window collides with an existing ACTIVE window")
    rec = {
        "recording_id": recording_id,
        "territory": territory,
        "rights_type": rights_type,
        "term_start": data["term_start"],
        "term_end": data["term_end"],
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.rights_windows[rec["id"]] = rec
    return success(S.rights_window(rec), status=201)


@bp.route("/rights-windows/<rid>", methods=["GET"])
def get_rights_window(rid):
    authorize({"Administrator", "RoyaltyOperator", "Licensee"})
    rec = path_get(db.rights_windows, rid)
    return success(S.rights_window(rec))


@bp.route("/rights-windows", methods=["GET"])
def list_rights_windows():
    authorize({"Administrator", "RoyaltyOperator", "Licensee"})
    limit, offset = parse_pagination(request.args)
    items = list(db.rights_windows.values())
    recording_id = request.args.get("recording_id")
    rights_type = request.args.get("rights_type")
    status = request.args.get("status")
    if recording_id is not None:
        items = [w for w in items if w["recording_id"] == recording_id]
    if rights_type is not None:
        items = [w for w in items if w["rights_type"] == rights_type]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items = sorted_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return success([S.rights_window(w) for w in page], pagination=meta)


@bp.route("/rights-windows/<rid>/revoke", methods=["POST"])
def revoke_rights_window(rid):
    authorize({"Administrator"})
    rec = path_get(db.rights_windows, rid)
    if rec["status"] != "ACTIVE":
        fail(ERR_INVALID_STATE, "Only ACTIVE windows can be revoked")
    rec["status"] = "REVOKED"
    touch(rec)
    return success(S.rights_window(rec))
