"""DigitizationTicket routes (PRD §3.5) — capture loop, QC SoD, hours, cancel."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    ERR_OWNERSHIP_MISMATCH, ERR_QC_SELF_REVIEW, ERR_VOLUNTEER_HOUR_CAP_EXCEEDED,
)
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from services.rollup import recompute_project_active_count
from util import get_json_body, paginate, public_view, require_field

bp = Blueprint("tickets", __name__)


def serialize_ticket(t: dict) -> dict:
    return public_view(t)


def _get_ticket(tid: str) -> dict:
    t = db.tickets.get(tid)
    if t is None:
        raise_err(ERR_NOT_FOUND, f"DigitizationTicket not found: {tid}")
    return t


@bp.route("/digitization-tickets", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_tickets(_user_id: str, _role: str):
    project_id = request.args.get("project_id")
    item_id = request.args.get("item_id")
    status = request.args.get("status")
    rows = list(db.tickets.values())
    if project_id is not None:
        rows = [t for t in rows if t["project_id"] == project_id]
    if item_id is not None:
        rows = [t for t in rows if t["item_id"] == item_id]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    page, limit, offset, total = paginate(rows)
    return success_list([serialize_ticket(t) for t in page], limit, offset, total)


@bp.route("/digitization-tickets/<tid>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_ticket(tid: str, _user_id: str, _role: str):
    return success_object(serialize_ticket(_get_ticket(tid)))


@bp.route("/digitization-tickets/<tid>/begin-capture", methods=["POST"])
@require_roles("Volunteer")
def begin_capture(tid: str, _user_id: str, _role: str):
    t = _get_ticket(tid)
    if t["status"] != "CLAIMED":
        raise_err(ERR_INVALID_STATE, "Only a CLAIMED ticket may begin capture")
    if t["claimed_by_user_id"] != _user_id:
        raise_err(ERR_OWNERSHIP_MISMATCH, "Only the claimant may begin capture")
    t["status"] = "IN_CAPTURE"
    db.touch(t)
    return success_object(serialize_ticket(t))


@bp.route("/digitization-tickets/<tid>/submit-qc", methods=["POST"])
@require_roles("Volunteer")
def submit_qc(tid: str, _user_id: str, _role: str):
    t = _get_ticket(tid)
    if t["status"] != "IN_CAPTURE":
        raise_err(ERR_INVALID_STATE, "Only an IN_CAPTURE ticket may be submitted for QC")
    if t["claimed_by_user_id"] != _user_id:
        raise_err(ERR_OWNERSHIP_MISMATCH, "Only the claimant may submit for QC")
    t["status"] = "QC_REVIEW"
    db.touch(t)
    return success_object(serialize_ticket(t))


@bp.route("/digitization-tickets/<tid>/qc-pass", methods=["POST"])
@require_roles("VolunteerCoordinator")
def qc_pass(tid: str, _user_id: str, _role: str):
    t = _get_ticket(tid)
    if t["status"] != "QC_REVIEW":
        raise_err(ERR_INVALID_STATE, "Only a QC_REVIEW ticket may be passed")
    if t["claimed_by_user_id"] == _user_id:
        raise_err(ERR_QC_SELF_REVIEW, "The QC reviewer must differ from the claimant")
    t["status"] = "COMPLETE"
    db.touch(t)
    proj = db.projects.get(t["project_id"])
    if proj is not None:
        recompute_project_active_count(proj)
    return success_object(serialize_ticket(t))


@bp.route("/digitization-tickets/<tid>/qc-fail", methods=["POST"])
@require_roles("VolunteerCoordinator")
def qc_fail(tid: str, _user_id: str, _role: str):
    t = _get_ticket(tid)
    if t["status"] != "QC_REVIEW":
        raise_err(ERR_INVALID_STATE, "Only a QC_REVIEW ticket may be failed")
    if t["claimed_by_user_id"] == _user_id:
        raise_err(ERR_QC_SELF_REVIEW, "The QC reviewer must differ from the claimant")
    t["status"] = "IN_CAPTURE"
    t["qc_fail_count"] += 1
    db.touch(t)
    # active_ticket_count unchanged — the ticket remains active
    return success_object(serialize_ticket(t))


@bp.route("/digitization-tickets/<tid>/release", methods=["POST"])
@require_roles("Volunteer")
def release(tid: str, _user_id: str, _role: str):
    t = _get_ticket(tid)
    if t["status"] not in ("CLAIMED", "IN_CAPTURE"):
        raise_err(ERR_INVALID_STATE, "Only a CLAIMED or IN_CAPTURE ticket may be released")
    if t["claimed_by_user_id"] != _user_id:
        raise_err(ERR_OWNERSHIP_MISMATCH, "Only the claimant may release the ticket")
    t["status"] = "QUEUED"
    t["claimed_by_user_id"] = None
    db.touch(t)
    proj = db.projects.get(t["project_id"])
    if proj is not None:
        recompute_project_active_count(proj)  # compensates the claim
    return success_object(serialize_ticket(t))


@bp.route("/digitization-tickets/<tid>/log-hours", methods=["POST"])
@require_roles("Volunteer")
def log_hours(tid: str, _user_id: str, _role: str):
    body = get_json_body()
    raw_hours = require_field(body, "hours")
    if isinstance(raw_hours, bool) or not isinstance(raw_hours, (int, float, Decimal)):
        raise_err(ERR_INVALID_REQUEST, "Field 'hours' must be a number")
    hours = raw_hours if isinstance(raw_hours, Decimal) else Decimal(str(raw_hours))
    # positive multiple of 0.25 (priority 3 shape check)
    if hours <= 0 or (hours % Decimal("0.25")) != 0:
        raise_err(ERR_INVALID_REQUEST, "hours must be a positive multiple of 0.25")

    t = _get_ticket(tid)
    if t["status"] not in ("CLAIMED", "IN_CAPTURE"):
        raise_err(ERR_INVALID_STATE, "Hours may be logged only on a CLAIMED or IN_CAPTURE ticket")

    proj = db.projects.get(t["project_id"])
    if proj is None:
        raise_err(ERR_NOT_FOUND, f"VolunteerProject not found: {t['project_id']}")

    # hour cap (priority 10): strictly above the cap is rejected; == allowed
    current = proj["volunteer_hours"].get(_user_id, Decimal("0"))
    if not isinstance(current, Decimal):
        current = Decimal(str(current))
    new_total = current + hours
    if new_total > proj["max_hours_per_volunteer"]:
        raise_err(ERR_VOLUNTEER_HOUR_CAP_EXCEEDED, "Logging these hours exceeds the per-volunteer cap")

    # ownership (priority 11)
    if t["claimed_by_user_id"] != _user_id:
        raise_err(ERR_OWNERSHIP_MISMATCH, "Only the claimant may log hours on the ticket")

    ticket_hours = t["hours_logged"] if isinstance(t["hours_logged"], Decimal) else Decimal(str(t["hours_logged"]))
    t["hours_logged"] = ticket_hours + hours
    db.touch(t)

    proj_total = proj["hours_logged_total"] if isinstance(proj["hours_logged_total"], Decimal) else Decimal(str(proj["hours_logged_total"]))
    proj["hours_logged_total"] = proj_total + hours
    proj["volunteer_hours"][_user_id] = new_total
    db.touch(proj)
    return success_object(serialize_ticket(t))


@bp.route("/digitization-tickets/<tid>/cancel", methods=["POST"])
@require_roles("VolunteerCoordinator")
def cancel_ticket(tid: str, _user_id: str, _role: str):
    t = _get_ticket(tid)
    if t["status"] not in ("QUEUED", "CLAIMED", "IN_CAPTURE", "QC_REVIEW"):
        raise_err(ERR_INVALID_STATE, "Only a non-terminal ticket may be cancelled")
    was_active = t["status"] in ("CLAIMED", "IN_CAPTURE", "QC_REVIEW")
    t["status"] = "CANCELLED"
    db.touch(t)
    if was_active:
        proj = db.projects.get(t["project_id"])
        if proj is not None:
            recompute_project_active_count(proj)
    return success_object(serialize_ticket(t))
