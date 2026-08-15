"""Shareholder, ShareholderSnapshot, ShareholderPosition endpoints."""

from flask import Blueprint, request

import errors
from db import db
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.calculations import calc_five_fifty
from services.common import (
    get_json_body, make_entity, parse_date, req_date, req_enum, req_int, req_string, touch,
)

bp = Blueprint("shareholders", __name__)
ALL = ("ComplianceOfficer", "TaxDirector", "BoardDirector")
HOLDER_TYPES = ("INDIVIDUAL", "ENTITY")


def _is_half_year_last_day(date_str):
    d = parse_date(date_str)
    return (d.month, d.day) in ((6, 30), (12, 31))


# ------------------------------- Shareholder -------------------------------

@bp.route("/reit-compliance/shareholders", methods=["POST"])
def create_shareholder():
    require_roles("ComplianceOfficer")
    body = get_json_body()
    reit_id = body.get("reit_id")
    if not isinstance(reit_id, str) or not reit_id:
        raise errors.validation("Field 'reit_id' is required")
    if db.reits.get(reit_id) is None:
        raise errors.not_found("reit_id does not resolve to an existing REIT")

    display_name = req_string(body, "display_name")
    holder_type = req_enum(body, "holder_type", HOLDER_TYPES)

    sh = make_entity({
        "reit_id": reit_id,
        "display_name": display_name,
        "holder_type": holder_type,
        "status": "ACTIVE",
    })
    db.shareholders[sh["id"]] = sh
    return success_object(dict(sh), status=201)


@bp.route("/reit-compliance/shareholders/<sid>", methods=["GET"])
def get_shareholder(sid):
    require_roles(*ALL)
    sh = db.shareholders.get(sid)
    if sh is None:
        raise errors.not_found("Shareholder not found")
    return success_object(dict(sh))


@bp.route("/reit-compliance/shareholders", methods=["GET"])
def list_shareholders():
    require_roles(*ALL)
    limit, offset = parse_pagination(request.args)
    rows = list(db.shareholders.values())
    reit_id = request.args.get("reit_id")
    if reit_id is not None:
        rows = [s for s in rows if s["reit_id"] == reit_id]
    page, total = paginate(rows, limit, offset)
    return success_list([dict(s) for s in page], limit, offset, total)


@bp.route("/reit-compliance/shareholders/<sid>/unfreeze", methods=["POST"])
def unfreeze_shareholder(sid):
    require_roles("TaxDirector")
    sh = db.shareholders.get(sid)
    if sh is None:
        raise errors.not_found("Shareholder not found")
    if sh["status"] != "FROZEN":
        raise errors.invalid_state("Only FROZEN shareholders can be unfrozen")
    sh["status"] = "ACTIVE"
    touch(sh)
    return success_object(dict(sh))


# --------------------------- ShareholderSnapshot ---------------------------

@bp.route("/reit-compliance/shareholder-snapshots", methods=["POST"])
def create_snapshot():
    require_roles("ComplianceOfficer")
    body = get_json_body()
    reit_id = body.get("reit_id")
    if not isinstance(reit_id, str) or not reit_id:
        raise errors.validation("Field 'reit_id' is required")
    if db.reits.get(reit_id) is None:
        raise errors.not_found("reit_id does not resolve to an existing REIT")

    snapshot_date = req_date(body, "snapshot_date")
    total_shares = req_int(body, "total_shares_outstanding", min_value=0)
    if total_shares <= 0:
        raise errors.validation("total_shares_outstanding must be > 0")

    # Uniqueness: snapshot_date unique within reit (priority 6, before date sanity)
    for s in db.shareholder_snapshots.values():
        if s["reit_id"] == reit_id and s["snapshot_date"] == snapshot_date:
            raise errors.duplicate("snapshot_date must be unique within the REIT")

    # Half-year last-day rule (priority 10)
    if not _is_half_year_last_day(snapshot_date):
        raise errors.invalid_date_range(
            "snapshot_date must fall on a half-year last day (Jun 30 or Dec 31)"
        )

    snap = make_entity({
        "reit_id": reit_id,
        "snapshot_date": snapshot_date,
        "total_shares_outstanding": total_shares,
        "status": "DRAFT",
        "top5_individual_pct": None,
        "five_fifty_passed": None,
        "violator_shareholder_ids": [],
    })
    db.shareholder_snapshots[snap["id"]] = snap
    return success_object(dict(snap), status=201)


@bp.route("/reit-compliance/shareholder-snapshots/<sid>", methods=["GET"])
def get_snapshot(sid):
    require_roles(*ALL)
    snap = db.shareholder_snapshots.get(sid)
    if snap is None:
        raise errors.not_found("Shareholder snapshot not found")
    return success_object(dict(snap))


@bp.route("/reit-compliance/shareholder-snapshots", methods=["GET"])
def list_snapshots():
    require_roles(*ALL)
    limit, offset = parse_pagination(request.args)
    rows = list(db.shareholder_snapshots.values())
    reit_id = request.args.get("reit_id")
    if reit_id is not None:
        rows = [s for s in rows if s["reit_id"] == reit_id]
    page, total = paginate(rows, limit, offset)
    return success_list([dict(s) for s in page], limit, offset, total)


@bp.route("/reit-compliance/shareholder-snapshots/<sid>/finalize", methods=["POST"])
def finalize_snapshot(sid):
    require_roles("ComplianceOfficer")
    snap = db.shareholder_snapshots.get(sid)
    if snap is None:
        raise errors.not_found("Shareholder snapshot not found")
    # State check (priority 7) before empty-snapshot check
    if snap["status"] != "DRAFT":
        raise errors.invalid_state("Only DRAFT snapshots can be finalized")

    positions = [
        p for p in db.shareholder_positions.values() if p["snapshot_id"] == sid
    ]
    if len(positions) == 0:
        raise errors.snapshot_empty("Finalize requested on a snapshot with zero positions")

    reit = db.reits.get(snap["reit_id"])
    if reit is None:
        raise errors.not_found("REIT not found")

    result = calc_five_fifty(snap, reit)

    # Persist per-position concentration
    for p in positions:
        p["concentration_pct"] = result["concentration_by_position"][p["id"]]
        p["updated_at"] = p["updated_at"]  # concentration write; no version bump specified

    snap["top5_individual_pct"] = result["top5_individual_pct"]
    snap["five_fifty_passed"] = result["five_fifty_passed"]
    snap["violator_shareholder_ids"] = result["violator_shareholder_ids"]
    snap["status"] = "FINALIZED"
    touch(snap)

    # Cascade: freeze violators
    for vid in result["violator_shareholder_ids"]:
        sh = db.shareholders.get(vid)
        if sh is not None and sh["status"] == "ACTIVE":
            sh["status"] = "FROZEN"
            touch(sh)

    # five_fifty_blocked := NOT five_fifty_passed; reit version bumps when the flag flips
    new_blocked = not result["five_fifty_passed"]
    if reit["five_fifty_blocked"] != new_blocked:
        reit["five_fifty_blocked"] = new_blocked
        touch(reit)

    return success_object(dict(snap))


# --------------------------- ShareholderPosition ---------------------------

@bp.route("/reit-compliance/shareholder-positions", methods=["POST"])
def create_position():
    require_roles("ComplianceOfficer")
    body = get_json_body()
    snapshot_id = body.get("snapshot_id")
    shareholder_id = body.get("shareholder_id")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise errors.validation("Field 'snapshot_id' is required")
    if not isinstance(shareholder_id, str) or not shareholder_id:
        raise errors.validation("Field 'shareholder_id' is required")
    snap = db.shareholder_snapshots.get(snapshot_id)
    if snap is None:
        raise errors.not_found("snapshot_id does not resolve to an existing snapshot")
    sh = db.shareholders.get(shareholder_id)
    if sh is None:
        raise errors.not_found("shareholder_id does not resolve to an existing shareholder")

    shares_held = req_int(body, "shares_held", min_value=0)

    # Snapshot-open gate (priority 8) precedes cross-reit check (priority 9)
    if snap["status"] != "DRAFT":
        raise errors.quarter_locked("Positions may only be added while the snapshot is DRAFT")
    if sh["reit_id"] != snap["reit_id"]:
        raise errors.cross_reit("shareholder_id belongs to a different REIT than the snapshot")

    pos = make_entity({
        "snapshot_id": snapshot_id,
        "shareholder_id": shareholder_id,
        "shares_held": shares_held,
        "concentration_pct": None,
    })
    db.shareholder_positions[pos["id"]] = pos
    return success_object(dict(pos), status=201)


@bp.route("/reit-compliance/shareholder-positions/<pid>", methods=["GET"])
def get_position(pid):
    require_roles(*ALL)
    pos = db.shareholder_positions.get(pid)
    if pos is None:
        raise errors.not_found("Shareholder position not found")
    return success_object(dict(pos))


@bp.route("/reit-compliance/shareholder-positions", methods=["GET"])
def list_positions():
    require_roles(*ALL)
    limit, offset = parse_pagination(request.args)
    rows = list(db.shareholder_positions.values())
    snapshot_id = request.args.get("snapshot_id")
    shareholder_id = request.args.get("shareholder_id")
    if snapshot_id is not None:
        rows = [p for p in rows if p["snapshot_id"] == snapshot_id]
    if shareholder_id is not None:
        rows = [p for p in rows if p["shareholder_id"] == shareholder_id]
    page, total = paginate(rows, limit, offset)
    return success_list([dict(p) for p in page], limit, offset, total)
