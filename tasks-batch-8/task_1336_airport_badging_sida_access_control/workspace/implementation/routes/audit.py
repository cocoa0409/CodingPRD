"""Audit cycle endpoints (PRD §3.9)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_AUDIT_CYCLE_NOT_FOUND,
    ERR_AUDIT_NOT_OPEN,
    ERR_AUDIT_WINDOW_GAP,
    ERR_AUDIT_WINDOW_OVERLAP,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from services import logic
from services.serializers import serialize_audit_cycle
from util import fetch_or_404, get_json_body, require_datetime

bp = Blueprint("audit", __name__)


@bp.route("/audit-cycles", methods=["POST"])
@require_roles("Auditor")
def create_audit_cycle(user_id: str, role: str):
    body = get_json_body()
    start_raw, start_dt = require_datetime(body, "window_start")
    end_raw, end_dt = require_datetime(body, "window_end")
    if not end_dt > start_dt:
        raise_err(ERR_INVALID_REQUEST, "window_end must be after window_start")

    cycles = list(db.STORES["audit_cycles"].values())

    # Priority 8: overlap checked before gap; [start, end) half-open, touching allowed.
    for c in cycles:
        if start_dt < c["_window_end_dt"] and c["_window_start_dt"] < end_dt:
            raise_err(
                ERR_AUDIT_WINDOW_OVERLAP,
                "New audit window overlaps an existing cycle",
            )
    if cycles:
        latest_end = max(c["_window_end_dt"] for c in cycles)
        if start_dt != latest_end:
            raise_err(
                ERR_AUDIT_WINDOW_GAP,
                "New audit window must start exactly at the latest cycle's window_end",
            )

    rec = {
        "window_start": start_raw,
        "window_end": end_raw,
        "status": "OPEN",
        "scoped_count": None,
        "accounted_count": None,
        "recovery_rate_pct": None,
        "per_class_rates": None,
        "outcome": None,
        "due_scoped_count": None,
        "due_accounted_count": None,
        "recovery_rate_provisional_pct": None,
        "_window_start_dt": start_dt,
        "_window_end_dt": end_dt,
    }
    db.stamp_new(rec)
    db.STORES["audit_cycles"][rec["id"]] = rec
    return success_object(serialize_audit_cycle(rec), 201)


@bp.route("/audit-cycles/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_audit_cycle(user_id: str, role: str, cid: str):
    cycle = fetch_or_404("audit_cycles", cid, ERR_AUDIT_CYCLE_NOT_FOUND, "audit cycle")
    return success_object(serialize_audit_cycle(cycle))


@bp.route("/audit-cycles/<cid>/close", methods=["POST"])
@require_roles("Auditor")
def close_audit_cycle(user_id: str, role: str, cid: str):
    cycle = fetch_or_404("audit_cycles", cid, ERR_AUDIT_CYCLE_NOT_FOUND, "audit cycle")
    if cycle["status"] != "OPEN":
        raise_err(ERR_AUDIT_NOT_OPEN, "close requires the audit cycle to be OPEN")
    logic.close_audit_cycle(cycle)
    return success_object(serialize_audit_cycle(cycle))
