"""HoldingSnapshot and LookThroughLine endpoints."""

from flask import Blueprint, request

import db
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_DUPLICATE_QUARTER,
)
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, list_response
from validate import body, req_quarter, req_nonneg_num, req_enum

bp = Blueprint("snapshots", __name__)

SECTORS = ["TECH", "HEALTHCARE", "INDUSTRIALS", "CONSUMER", "FINANCIALS",
           "ENERGY", "OTHER"]
GEOGRAPHIES = ["NA", "EU", "APAC", "LATAM", "MEA"]


def get_snapshot_or_404(sid):
    s = STORE.snapshots.get(sid)
    if s is None:
        raise_err(ERR_NOT_FOUND, "snapshot id does not exist")
    return s


@bp.route("/fof/commitments/<cid>/snapshots", methods=["POST"])
def record_snapshot(cid):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    commitment = STORE.commitments.get(cid)
    if commitment is None:
        raise_err(ERR_NOT_FOUND, "commitment id does not exist")
    data = body()
    quarter = req_quarter(data, "as_of_quarter")
    nav = req_nonneg_num(data, "reported_nav")
    for s in STORE.snapshots.values():
        if (s["commitment_id"] == cid and s["as_of_quarter"] == quarter
                and s["status"] != "RESTATED"):
            raise_err(ERR_DUPLICATE_QUARTER,
                      "a snapshot for this quarter already exists")
    s = new_entity(STORE.snapshots, {
        "commitment_id": cid,
        "vehicle_id": commitment["vehicle_id"],
        "as_of_quarter": quarter,
        "reported_nav": nav,
        "reported_at": db.now_iso(),
        "is_final": False,
        "status": "PROVISIONAL",
    })
    return ok(public(s), status=201)


@bp.route("/fof/commitments/<cid>/snapshots", methods=["GET"])
def list_snapshots(cid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if STORE.commitments.get(cid) is None:
        raise_err(ERR_NOT_FOUND, "commitment id does not exist")
    rows = [s for s in STORE.snapshots.values() if s["commitment_id"] == cid]
    return list_response(rows, filters={
        "status": request.args.get("status"),
        "as_of_quarter": request.args.get("as_of_quarter"),
    })


@bp.route("/fof/snapshots/<sid>", methods=["GET"])
def get_snapshot(sid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return ok(public(get_snapshot_or_404(sid)))


def _restate_published_reports(snapshot):
    """Any PUBLISHED ValuationReport for the same program+quarter moves to
    RESTATED (NAV fields recomputed on next publish)."""
    commitment = STORE.commitments.get(snapshot["commitment_id"])
    if commitment is None:
        return
    for r in STORE.valuation_reports.values():
        if (r["program_id"] == commitment["program_id"]
                and r["as_of_quarter"] == snapshot["as_of_quarter"]
                and r["status"] == "PUBLISHED"):
            r["status"] = "RESTATED"
            touch(r)


@bp.route("/fof/snapshots/<sid>/finalize", methods=["POST"])
def finalize_snapshot(sid):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    s = get_snapshot_or_404(sid)
    if s["status"] != "PROVISIONAL":
        raise_err(ERR_INVALID_STATE, "snapshot is not PROVISIONAL")
    s["status"] = "FINAL"
    s["is_final"] = True
    touch(s)
    _restate_published_reports(s)
    return ok(public(s))


@bp.route("/fof/snapshots/<sid>/restate", methods=["POST"])
def restate_snapshot(sid):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    s = get_snapshot_or_404(sid)
    if s["status"] != "FINAL":
        raise_err(ERR_INVALID_STATE, "snapshot is not FINAL")
    s["status"] = "RESTATED"
    s["is_final"] = False
    touch(s)
    _restate_published_reports(s)
    return ok(public(s))


@bp.route("/fof/snapshots/<sid>/look-through-lines", methods=["POST"])
def append_line(sid):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    s = get_snapshot_or_404(sid)
    data = body()
    sector = req_enum(data, "sector", SECTORS)
    geography = req_enum(data, "geography", GEOGRAPHIES)
    exposure = req_nonneg_num(data, "exposure_amount")
    line = new_entity(STORE.look_through_lines, {
        "snapshot_id": s["id"],
        "sector": sector,
        "geography": geography,
        "exposure_amount": exposure,
    }, common=False)
    return ok(public(line), status=201)


@bp.route("/fof/snapshots/<sid>/look-through-lines", methods=["GET"])
def list_lines(sid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_snapshot_or_404(sid)
    rows = [l for l in STORE.look_through_lines.values()
            if l["snapshot_id"] == sid]
    return list_response(rows, filters={
        "sector": request.args.get("sector"),
        "geography": request.args.get("geography"),
    })
