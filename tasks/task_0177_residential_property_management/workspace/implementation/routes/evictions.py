"""EvictionCase routes (PRD §3.8) — serve, get, list, cure, file, enforce, dismiss."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, require_enum, require_iso_date,
    parse_pagination, paginate, filter_param, parse_date,
)
from services import domain

bp = Blueprint("evictions", __name__)

REASONS = {"NONPAYMENT", "LEASE_VIOLATION", "HOLDOVER"}
NON_TERMINAL = {"NOTICE_SERVED", "CURED", "FILED"}


@bp.route("/evictions", methods=["POST"])
def serve_notice():
    require_role({"PropertyManager"})
    body = get_json_body()
    lease_id = require_string(body, "lease_id")
    reason = require_enum(body, "reason", REASONS)
    notice_date = require_iso_date(body, "notice_date")
    with db.LOCK:
        lease = db.leases.get(lease_id)
        if lease is None:
            raise err(errors.ERR_FK_NOT_FOUND, "lease_id does not resolve")
        prop = domain.property_of_lease(lease)

        # Eviction-notice window overlap (priority 9.5): the new notice_date must
        # not fall inside an existing non-terminal case's closed window
        # [notice_date, cure_deadline_date] (inclusive of both endpoints).
        nd = parse_date(notice_date)
        for ev in db.evictions.values():
            if ev["lease_id"] != lease_id:
                continue
            if ev["status"] not in NON_TERMINAL:
                continue
            win_start = parse_date(ev["notice_date"])
            win_end = parse_date(ev["cure_deadline_date"])
            if win_start <= nd <= win_end:
                raise err(errors.ERR_EVICTION_WINDOW_OVERLAP,
                          "Notice date overlaps an in-flight eviction window")

        cure_deadline = domain.compute_cure_deadline(notice_date, prop["state_code"], reason)
        common = db.new_common()
        record = {
            **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
            "lease_id": lease_id,
            "reason": reason,
            "notice_date": notice_date,
            "cure_deadline_date": cure_deadline,
            "arrears_at_notice_cents": lease["balance_due_cents"],
            "status": "NOTICE_SERVED",
        }
        db.evictions[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/evictions/<id>", methods=["GET"])
def get_eviction(id):
    require_role({"PropertyManager", "ComplianceOfficer", "Owner"})
    with db.LOCK:
        record = db.evictions.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Eviction case not found")
        return object_response(serialize(record), 200)


@bp.route("/evictions", methods=["GET"])
def list_evictions():
    require_role({"PropertyManager", "ComplianceOfficer", "Owner"})
    lease_id = filter_param(request.args, "lease_id")
    status = filter_param(request.args, "status")
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.evictions.values())
        if lease_id is not None:
            records = [r for r in records if r["lease_id"] == lease_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/evictions/<id>/cure", methods=["POST"])
def cure_eviction(id):
    require_role({"PropertyManager"})
    body = get_json_body()
    as_of = require_iso_date(body, "as_of_date")
    with db.LOCK:
        ev = db.evictions.get(id)
        if ev is None:
            raise err(errors.ERR_NOT_FOUND, "Eviction case not found")
        # State-admissibility (priority 7) precedes cure-window (priority 9).
        if ev["status"] != "NOTICE_SERVED":
            raise err(errors.ERR_INVALID_STATE, "Eviction is not NOTICE_SERVED")
        if parse_date(as_of) > parse_date(ev["cure_deadline_date"]):
            raise err(errors.ERR_CURE_WINDOW_CLOSED, "Cure window has closed")
        if ev["reason"] == "NONPAYMENT":
            lease = db.leases.get(ev["lease_id"])
            if lease is not None and lease["balance_due_cents"] != 0:
                raise err(errors.ERR_ARREARS_NOT_CLEARED, "Lease arrears not cleared")
        ev["status"] = "CURED"
        db.touch(ev)
        return object_response(serialize(ev), 200)


@bp.route("/evictions/<id>/file", methods=["POST"])
def file_eviction(id):
    require_role({"ComplianceOfficer"})
    body = get_json_body()
    as_of = require_iso_date(body, "as_of_date")
    with db.LOCK:
        ev = db.evictions.get(id)
        if ev is None:
            raise err(errors.ERR_NOT_FOUND, "Eviction case not found")
        if ev["status"] != "NOTICE_SERVED":
            raise err(errors.ERR_INVALID_STATE, "Eviction is not NOTICE_SERVED")
        if parse_date(as_of) <= parse_date(ev["cure_deadline_date"]):
            raise err(errors.ERR_CURE_WINDOW_OPEN, "Cure window is still open")
        ev["status"] = "FILED"
        db.touch(ev)
        return object_response(serialize(ev), 200)


@bp.route("/evictions/<id>/enforce", methods=["POST"])
def enforce_eviction(id):
    require_role({"ComplianceOfficer"})
    with db.LOCK:
        ev = db.evictions.get(id)
        if ev is None:
            raise err(errors.ERR_NOT_FOUND, "Eviction case not found")
        if ev["status"] != "FILED":
            raise err(errors.ERR_INVALID_STATE, "Eviction is not FILED")
        lease = db.leases.get(ev["lease_id"])
        if lease is None or lease["status"] != "ACTIVE":
            raise err(errors.ERR_INVALID_STATE, "Underlying lease is not ACTIVE")
        # Cascade (PRD §3.8): lease -> TERMINATED, tenant -> FORMER,
        # unit -> VACANT_TURN, and auto-open a TurnoverProject whose opened_date
        # is the enforcement date. /enforce takes no date input, so the
        # enforcement date is the server's current UTC date.
        enforce_date = _server_date()
        domain.terminate_lease_via_eviction(lease, enforce_date)
        ev["status"] = "ENFORCED"
        db.touch(ev)
        return object_response(serialize(ev), 200)


@bp.route("/evictions/<id>/dismiss", methods=["POST"])
def dismiss_eviction(id):
    require_role({"ComplianceOfficer"})
    with db.LOCK:
        ev = db.evictions.get(id)
        if ev is None:
            raise err(errors.ERR_NOT_FOUND, "Eviction case not found")
        if ev["status"] not in ("CURED", "FILED"):
            raise err(errors.ERR_INVALID_STATE, "Eviction is not CURED or FILED")
        ev["status"] = "DISMISSED"
        db.touch(ev)
        return object_response(serialize(ev), 200)


def _server_date():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).date().isoformat()
