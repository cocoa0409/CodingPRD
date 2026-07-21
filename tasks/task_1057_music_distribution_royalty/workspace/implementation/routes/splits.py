"""Split sheets and split shares — PRD §3.4."""

from flask import Blueprint, request

from db import db, common_fields, now, touch
from errors import ApiError
from middleware import auth, require_ownership
from response import created, ok, ok_list, paginate, read_pagination
from services import calc, core
import validation as v

bp = Blueprint("splits", __name__)


def owned_sheet(user_id, role, sheet_id):
    sheet = db.split_sheets.get(sheet_id)
    if role == "Artist" and sheet is not None:
        require_ownership(user_id == core.artist_of_sheet(sheet))
    return core.find_sheet(sheet_id)


def owned_share(user_id, role, share_id):
    share = db.split_shares.get(share_id)
    if share is not None:
        if role == "Artist":
            require_ownership(user_id == core.artist_of_share(share))
        elif role == "Collaborator":
            require_ownership(user_id == share["collaborator_id"])
    return core.find_share(share_id)


# ---- split sheets ---------------------------------------------------------

@bp.post("/api/split-sheets")
def create_sheet():
    user_id, role = auth("Artist")
    data = v.body()
    track_id = v.req_id(data, "track_id")
    effective_from = v.req_datetime(data, "effective_from")
    expected_track_version = v.req_int(data, "expected_track_version", minimum=0)

    track = db.tracks.get(track_id)
    if role == "Artist" and track is not None:
        require_ownership(user_id == core.artist_of_track(track))
    track = core.find_track(track_id)

    if expected_track_version != track["version"]:
        raise ApiError("ERR_STALE_VERSION")

    row = common_fields()
    row.update({
        "track_id": track["id"],
        "effective_from": effective_from,
        "status": "DRAFT",
        "total_share_bps": 0,
        "accepted_share_count": 0,
        "locked_at": None,
    })
    db.split_sheets[row["id"]] = row
    touch(track)
    return created(row)


@bp.get("/api/split-sheets/<sheet_id>")
def read_sheet(sheet_id):
    user_id, role = auth("Artist", "Collaborator", "FinanceOps", "PlatformAdmin")
    return ok(owned_sheet(user_id, role, sheet_id))


@bp.get("/api/split-sheets")
def list_sheets():
    user_id, role = auth("Artist", "Collaborator", "FinanceOps", "PlatformAdmin")
    limit, offset = read_pagination(request.args)
    rows = list(db.split_sheets.values())
    if role == "Artist":
        rows = [s for s in rows if core.artist_of_sheet(s) == user_id]
    track_id = request.args.get("track_id")
    if track_id is not None:
        rows = [s for s in rows if s["track_id"] == track_id]
    status = request.args.get("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/api/split-sheets/<sheet_id>/shares")
def create_share(sheet_id):
    user_id, role = auth("Artist")
    data = v.body()
    collaborator_id = v.req_id(data, "collaborator_id")
    share_bps = v.req_int(data, "share_bps", minimum=1, maximum=10000)

    sheet = owned_sheet(user_id, role, sheet_id)
    core.find_collaborator(collaborator_id)

    if sheet["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Shares may only be added to a DRAFT sheet.")

    if any(
        s["split_sheet_id"] == sheet["id"] and s["collaborator_id"] == collaborator_id
        for s in db.split_shares.values()
    ):
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "That payee already holds a share on this sheet.")

    row = common_fields()
    row.update({
        "split_sheet_id": sheet["id"],
        "collaborator_id": collaborator_id,
        "share_bps": share_bps,
        "accepted": False,
        "accepted_at": None,
    })
    db.split_shares[row["id"]] = row
    calc.recompute_sheet_totals(sheet)
    touch(sheet)
    return created(row)


@bp.post("/api/split-sheets/<sheet_id>/send")
def send_sheet(sheet_id):
    user_id, role = auth("Artist")
    sheet = owned_sheet(user_id, role, sheet_id)
    if sheet["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    _check_sheet_composition(sheet)
    sheet["status"] = "PENDING_ACCEPTANCE"
    touch(sheet)
    return ok(sheet)


def _check_sheet_composition(sheet):
    shares = core.shares_of_sheet(sheet["id"])
    if not shares:
        raise ApiError("ERR_SPLIT_SHEET_EMPTY")
    if sum(s["share_bps"] for s in shares) != core.SPLIT_TOTAL_BPS:
        raise ApiError("ERR_SPLIT_TOTAL_INVALID")


@bp.post("/api/split-sheets/<sheet_id>/lock")
def lock_sheet(sheet_id):
    user_id, role = auth("Artist")
    sheet = owned_sheet(user_id, role, sheet_id)
    if sheet["status"] != "PENDING_ACCEPTANCE":
        raise ApiError("ERR_INVALID_STATE")
    _check_sheet_composition(sheet)

    shares = core.shares_of_sheet(sheet["id"])
    if any(not s["accepted"] for s in shares):
        raise ApiError("ERR_SPLIT_NOT_ACCEPTED")

    track = db.tracks.get(sheet["track_id"])
    if track is not None:
        for other in core.sheets_of_track(track["id"]):
            if other["id"] != sheet["id"] and other["status"] == "LOCKED":
                other["status"] = "SUPERSEDED"
                touch(other)
        track["locked_split_sheet_id"] = sheet["id"]

    sheet["status"] = "LOCKED"
    sheet["locked_at"] = now()
    touch(sheet)
    return ok(sheet)


# ---- split shares ---------------------------------------------------------

@bp.get("/api/split-shares/<share_id>")
def read_share(share_id):
    user_id, role = auth("Artist", "Collaborator", "FinanceOps", "PlatformAdmin")
    return ok(owned_share(user_id, role, share_id))


@bp.get("/api/split-shares")
def list_shares():
    user_id, role = auth("Artist", "Collaborator", "FinanceOps", "PlatformAdmin")
    limit, offset = read_pagination(request.args)
    rows = list(db.split_shares.values())
    if role == "Artist":
        rows = [s for s in rows if core.artist_of_share(s) == user_id]
    elif role == "Collaborator":
        rows = [s for s in rows if s["collaborator_id"] == user_id]
    split_sheet_id = request.args.get("split_sheet_id")
    if split_sheet_id is not None:
        rows = [s for s in rows if s["split_sheet_id"] == split_sheet_id]
    collaborator_id = request.args.get("collaborator_id")
    if collaborator_id is not None:
        rows = [s for s in rows if s["collaborator_id"] == collaborator_id]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/api/split-shares/<share_id>/accept")
def accept_share(share_id):
    user_id, role = auth("Collaborator")
    share = owned_share(user_id, role, share_id)
    sheet = db.split_sheets.get(share["split_sheet_id"])
    if sheet is None or sheet["status"] != "PENDING_ACCEPTANCE":
        raise ApiError("ERR_INVALID_STATE")

    share["accepted"] = True
    share["accepted_at"] = now()
    touch(share)
    calc.recompute_sheet_totals(sheet)
    return ok(share)


@bp.post("/api/split-shares/<share_id>/reject")
def reject_share(share_id):
    user_id, role = auth("Collaborator")
    data = v.body()
    v.req_string(data, "reason_code")

    share = owned_share(user_id, role, share_id)
    sheet = db.split_sheets.get(share["split_sheet_id"])
    if sheet is None or sheet["status"] != "PENDING_ACCEPTANCE" or share["accepted"]:
        raise ApiError("ERR_INVALID_STATE")

    for sibling in core.shares_of_sheet(sheet["id"]):
        sibling["accepted"] = False
        sibling["accepted_at"] = None
    sheet["status"] = "DRAFT"
    sheet["accepted_share_count"] = 0
    touch(sheet)
    touch(share)
    return ok(share)
