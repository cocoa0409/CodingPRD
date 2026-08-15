"""Fumigation endpoints (PRD 3.3): creation by the applicator acting as self,
REI lockout, segregated clearance."""
from datetime import timedelta

from flask import Blueprint

import db
from clock import CLOCK
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services import core
from util import (as_dt, as_enum, as_str, body, paginate_sorted, present,
                  query_enum, query_str, required, resolve_body_fk,
                  resolve_path)

bp = Blueprint("fumigations", __name__)


@bp.route("/grain/fumigations", methods=["POST"])
def create_fumigation():
    user_id, _ = require_roles("CertifiedApplicator")
    data = body()
    # priority 3: the applicator acts as self — payload applicator_id must
    # equal the caller's X-User-ID, before any existence or shape check.
    if present(data, "applicator_id") and data["applicator_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "applicator_id must equal the caller's X-User-ID")
    # existence (4): body FKs left to right: bin_id, applicator_id
    bin_rec = resolve_body_fk(db.bins, data, "bin_id", "bin")
    applicator = resolve_body_fk(db.applicators, data, "applicator_id", "applicator")
    # shape (6)
    bin_id = as_str(required(data, "bin_id"), "bin_id")
    applicator_id = as_str(required(data, "applicator_id"), "applicator_id")
    product = as_enum(required(data, "product"), "product", core.PRODUCTS)
    start = as_dt(required(data, "application_start"), "application_start")
    end = as_dt(required(data, "application_end"), "application_end")
    if end <= start:
        raise ApiError("ERR_VALIDATION", 400,
                       "application_end must be strictly after application_start")
    # cert (18): certification must cover the application start
    if applicator["cert_expires_at"] < start:
        raise ApiError("ERR_APPLICATOR_CERT_EXPIRED", 409,
                       "applicator certification expired at application_start")
    # double-booking (22): CLOSED interval semantics over all of the
    # applicator's existing records; touching endpoints conflict.
    for f in db.fumigations.values():
        if f["applicator_id"] != applicator_id:
            continue
        if start <= f["application_end"] and f["application_start"] <= end:
            raise ApiError("ERR_APPLICATOR_DOUBLE_BOOKED", 409,
                           "occupancy interval conflicts with an existing record")

    rec = core.new_common()
    rec.update({
        "bin_id": bin_id,
        "applicator_id": applicator_id,
        "product": product,
        "application_start": start,
        "application_end": end,
        "lockout_until": start + timedelta(hours=core.REI_HOURS[product]),
        "status": "ACTIVE",
        "cleared_at": None,
        "cleared_by_applicator_id": None,
    })
    db.fumigations[rec["id"]] = rec

    snap = core.bin_snap(bin_rec)
    core.recompute_posture(bin_rec)
    core.finalize_bin(bin_rec, snap)
    return ok(core.fumigation_view(rec), 201)


@bp.route("/grain/fumigations/<fid>", methods=["GET"])
def get_fumigation(fid):
    require_roles(*ALL_ROLES)
    return ok(core.fumigation_view(resolve_path(db.fumigations, fid, "fumigation")))


@bp.route("/grain/fumigations", methods=["GET"])
def list_fumigations():
    require_roles(*ALL_ROLES)
    f_bin = query_str("bin_id")
    f_app = query_str("applicator_id")
    f_cleared = query_str("cleared_by_applicator_id")
    f_status = query_enum("status", core.FUMIGATION_STATUSES)
    items = list(db.fumigations.values())
    if f_bin is not None:
        items = [f for f in items if f["bin_id"] == f_bin]
    if f_app is not None:
        items = [f for f in items if f["applicator_id"] == f_app]
    if f_cleared is not None:
        items = [f for f in items if f["cleared_by_applicator_id"] == f_cleared]
    if f_status is not None:
        items = [f for f in items if f["status"] == f_status]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([core.fumigation_view(f) for f in page], total, limit, offset)


@bp.route("/grain/fumigations/<fid>/clear", methods=["POST"])
def clear_fumigation(fid):
    user_id, _ = require_roles("CertifiedApplicator")
    # existence (4)
    rec = resolve_path(db.fumigations, fid, "fumigation")
    # segregation (7): the clearer must differ from the applicator; this
    # precedes the state check.
    if user_id == rec["applicator_id"]:
        raise ApiError("ERR_SOD_SAME_APPLICATOR", 403,
                       "the applicator who applied the fumigation may not clear it")
    # state (10)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_FUMIGATION_NOT_ACTIVE", 409, "fumigation is not ACTIVE")
    # REI (17): now must be at or after lockout_until; exactly at passes.
    now = CLOCK.now()
    if now < rec["lockout_until"]:
        raise ApiError("ERR_REI_NOT_ELAPSED", 409,
                       "restricted-entry interval has not elapsed")

    rec["status"] = "CLEARED"
    rec["cleared_at"] = now
    rec["cleared_by_applicator_id"] = user_id
    core.touch(rec)

    bin_rec = db.bins.get(rec["bin_id"])
    if bin_rec is not None:
        snap = core.bin_snap(bin_rec)
        core.recompute_posture(bin_rec)
        core.finalize_bin(bin_rec, snap)
    return ok(core.fumigation_view(rec))
