"""DistributionRequests: approve, reject, withdraw (CASCADE B), reads."""
from flask import Blueprint, request

from auth import identity, require_roles, require_ownership
from envelope import ApiError, success
from helpers import resolve, get_body, paginate_list
from store import db, touch
import models
import queries

bp = Blueprint("dist", __name__)


@bp.route("/distribution-requests/<did>/approve", methods=["POST"])
def approve_dr(did):
    uid, role = identity()
    require_roles(role, {"Reviewer"})
    dr = resolve("drequest", did)
    if dr["status"] != "REQUESTED":
        raise ApiError("ERR_DISTRIBUTION_INVALID_STATE",
                       "Distribution request must be REQUESTED to approve")
    dr["status"] = "APPROVED"
    touch(dr)
    fmt = db.formats.get(dr["format_id"])
    # if the format is already PUBLISHED, advance straight to LIVE
    if fmt and fmt["status"] == "PUBLISHED":
        dr["status"] = "LIVE"
        touch(dr)
        title = db.titles.get(fmt["title_id"])
        if title and title["status"] == "DRAFT":
            title["status"] = "LIVE"
            touch(title)
    return success(models.ser_drequest(dr))


@bp.route("/distribution-requests/<did>/reject", methods=["POST"])
def reject_dr(did):
    uid, role = identity()
    require_roles(role, {"Reviewer"})
    dr = resolve("drequest", did)
    if dr["status"] != "REQUESTED":
        raise ApiError("ERR_DISTRIBUTION_INVALID_STATE",
                       "Distribution request must be REQUESTED to reject")
    body = get_body()
    dr["status"] = "REJECTED"
    dr["reason"] = body.get("reason")
    touch(dr)
    return success(models.ser_drequest(dr))


@bp.route("/distribution-requests/<did>/withdraw", methods=["POST"])
def withdraw_dr(did):
    uid, role = identity()
    require_roles(role, {"Publisher"})
    dr = resolve("drequest", did)
    require_ownership(role, uid, "drequest", dr)
    if dr["status"] != "LIVE":
        raise ApiError("ERR_DISTRIBUTION_INVALID_STATE",
                       "Distribution request must be LIVE to withdraw")
    dr["status"] = "WITHDRAWN"
    touch(dr)
    # CASCADE B: if no remaining LIVE request for the format, unlist the format
    fmt = db.formats.get(dr["format_id"])
    if fmt:
        any_live = any(d["format_id"] == fmt["id"] and d["status"] == "LIVE"
                       for d in db.drequests.values())
        if not any_live and fmt["status"] == "PUBLISHED":
            fmt["status"] = "UNLISTED"
            touch(fmt)
            # if every format under the title is UNLISTED, unlist the title
            title = db.titles.get(fmt["title_id"])
            if title and title["status"] == "LIVE":
                sib = [f for f in db.formats.values() if f["title_id"] == title["id"]]
                if sib and all(f["status"] == "UNLISTED" for f in sib):
                    title["status"] = "UNLISTED"
                    touch(title)
    return success(models.ser_drequest(dr))


@bp.route("/distribution-requests/<did>", methods=["GET"])
def get_dr(did):
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin", "Reviewer"})
    rec = resolve("drequest", did)
    require_ownership(role, uid, "drequest", rec)
    return success(models.ser_drequest(rec))


@bp.route("/distribution-requests", methods=["GET"])
def list_dr():
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin", "Reviewer"})
    records = list(db.drequests.values())
    if role == "Publisher":
        records = [d for d in records
                   if queries.publisher_id_of_format(db.formats.get(d["format_id"])) == uid]
    fid = request.args.get("format_id")
    cid = request.args.get("channel_id")
    if fid:
        records = [d for d in records if d.get("format_id") == fid]
    if cid:
        records = [d for d in records if d.get("channel_id") == cid]
    return paginate_list(records, models.ser_drequest)
