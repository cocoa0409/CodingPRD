"""Badge endpoints (PRD §3.4, §3.5)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_BADGE_NOT_ACTIVE,
    ERR_BADGE_NOT_FOUND,
    ERR_BADGE_NOT_INACTIVE,
    ERR_BADGE_NOT_REPLACEABLE,
    ERR_BADGE_NOT_SUSPENDED,
    ERR_BADGE_NUMBER_TAKEN,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SPONSOR_OWNERSHIP_MISMATCH,
    ERR_SUSPENSION_NOT_SERVED,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import logic
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("badges", __name__)


@bp.route("/badges", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_badges(user_id: str, role: str):
    limit, offset = parse_pagination()
    items = apply_filters(
        list(db.STORES["badges"].values()),
        ["applicant_id", "sponsor_id", "application_id", "superseded_by_badge_id", "status"],
    )
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/badges/<bid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_badge(user_id: str, role: str, bid: str):
    badge = fetch_or_404("badges", bid, ERR_BADGE_NOT_FOUND, "badge")
    return success_object(serialize(badge))


@bp.route("/badges/<bid>/suspend", methods=["POST"])
@require_roles("SecurityManager")
def suspend_badge(user_id: str, role: str, bid: str):
    badge = fetch_or_404("badges", bid, ERR_BADGE_NOT_FOUND, "badge")
    if badge["status"] != "ACTIVE":
        raise_err(ERR_BADGE_NOT_ACTIVE, "suspend requires the badge to be ACTIVE")
    logic.suspend_badge(badge, by=user_id, reason="MANUAL", until_dt=None)
    return success_object(serialize(badge))


@bp.route("/badges/<bid>/reinstate", methods=["POST"])
@require_roles("SecurityManager")
def reinstate_badge(user_id: str, role: str, bid: str):
    badge = fetch_or_404("badges", bid, ERR_BADGE_NOT_FOUND, "badge")
    if badge["status"] != "SUSPENDED":
        raise_err(ERR_BADGE_NOT_SUSPENDED, "reinstate requires the badge to be SUSPENDED")
    # Priority 7: segregation of duties.
    if badge["suspended_by"] == user_id:
        raise_err(
            ERR_SEGREGATION_OF_DUTIES,
            "Reinstating manager must differ from the suspending manager",
        )
    # Priority 8: suspension must be served when a term was set.
    until = badge.get("_suspended_until_dt")
    if until is not None and db.clock_now() < until:
        raise_err(ERR_SUSPENSION_NOT_SERVED, "Suspension term has not been served")
    badge["status"] = "ACTIVE"
    badge["suspended_by"] = None
    badge["suspended_until"] = None
    badge["suspension_reason"] = None
    badge["_suspended_until_dt"] = None
    db.touch(badge)
    return success_object(serialize(badge))


@bp.route("/badges/<bid>/report-lost", methods=["POST"])
@require_roles("SponsorSignatory", "BadgingOfficer")
def report_lost(user_id: str, role: str, bid: str):
    badge = fetch_or_404("badges", bid, ERR_BADGE_NOT_FOUND, "badge")
    # Priority 3: SponsorSignatory ownership over the badge's sponsor.
    if role == "SponsorSignatory" and badge["sponsor_id"] != user_id:
        raise_err(
            ERR_SPONSOR_OWNERSHIP_MISMATCH,
            "SponsorSignatory may report only its own sponsor's badges",
        )
    body = get_json_body()
    report_type = require_enum(body, "report_type", {"LOST", "STOLEN"})
    if badge["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(
            ERR_BADGE_NOT_ACTIVE,
            "report-lost requires the badge to be ACTIVE or SUSPENDED",
        )
    logic.deactivate_badge(badge, report_type, db.clock_now())
    return success_object(serialize(badge))


@bp.route("/badges/<bid>/mark-returned", methods=["POST"])
@require_roles("BadgingOfficer")
def mark_returned(user_id: str, role: str, bid: str):
    badge = fetch_or_404("badges", bid, ERR_BADGE_NOT_FOUND, "badge")
    if badge["status"] not in logic.RETURNABLE_STATUSES:
        raise_err(
            ERR_BADGE_NOT_INACTIVE,
            "mark-returned requires the badge to be LOST, STOLEN, EXPIRED, or REVOKED",
        )
    now = db.clock_now()
    badge["status"] = "RETURNED"
    badge["returned_at"] = db.fmt_clock(now)
    db.touch(badge)
    return success_object(serialize(badge))


@bp.route("/badges/<bid>/revoke", methods=["POST"])
@require_roles("SecurityManager")
def revoke_badge(user_id: str, role: str, bid: str):
    badge = fetch_or_404("badges", bid, ERR_BADGE_NOT_FOUND, "badge")
    if badge["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(
            ERR_BADGE_NOT_ACTIVE,
            "revoke requires the badge to be ACTIVE or SUSPENDED",
        )
    logic.deactivate_badge(badge, "REVOKED", db.clock_now())
    return success_object(serialize(badge))


@bp.route("/badges/<bid>/replace", methods=["POST"])
@require_roles("BadgingOfficer")
def replace_badge(user_id: str, role: str, bid: str):
    badge = fetch_or_404("badges", bid, ERR_BADGE_NOT_FOUND, "badge")
    body = get_json_body()
    badge_number = require_string(body, "badge_number")
    now = db.clock_now()

    # Priority 5: replaceability gates (all reported as ERR_BADGE_NOT_REPLACEABLE).
    if badge["status"] not in ("ACTIVE", "SUSPENDED", "EXPIRED"):
        raise_err(
            ERR_BADGE_NOT_REPLACEABLE,
            "replace requires an ACTIVE, SUSPENDED, or EXPIRED badge",
        )
    if not logic.all_courses_current(
        badge["applicant_id"], badge["badge_class"], now, grace=True
    ):
        raise_err(
            ERR_BADGE_NOT_REPLACEABLE,
            "Required training is not current under the renewal-grace regime",
        )
    new_expiry = logic.compute_badge_expiry(
        badge["applicant_id"], badge["badge_class"], now, grace=True
    )
    if new_expiry is None or not new_expiry > now:
        raise_err(
            ERR_BADGE_NOT_REPLACEABLE,
            "Computed expiry of the replacement badge is not in the future",
        )

    # Priority 7: badge_number uniqueness.
    for other in db.STORES["badges"].values():
        if other["badge_number"] == badge_number:
            raise_err(ERR_BADGE_NUMBER_TAKEN, "badge_number is already in use")

    new_badge = {
        "application_id": badge["application_id"],
        "applicant_id": badge["applicant_id"],
        "sponsor_id": badge["sponsor_id"],
        "badge_number": badge_number,
        "badge_class": badge["badge_class"],
        "status": "ACTIVE",
        "issued_at": db.fmt_clock(now),
        "expires_at": db.fmt_clock(new_expiry),
        "deactivated_at": None,
        "return_deadline": None,
        "returned_at": None,
        "suspended_by": None,
        "suspended_until": None,
        "suspension_reason": None,
        "superseded_by_badge_id": None,
        "_issued_dt": now,
        "_expires_dt": new_expiry,
        "_deactivated_dt": None,
        "_return_deadline_dt": None,
        "_suspended_until_dt": None,
    }
    db.stamp_new(new_badge)
    db.STORES["badges"][new_badge["id"]] = new_badge

    # Old badge -> VOIDED: administratively accounted, no return obligation.
    badge["status"] = "VOIDED"
    badge["deactivated_at"] = db.fmt_clock(now)
    badge["_deactivated_dt"] = now
    badge["return_deadline"] = None
    badge["_return_deadline_dt"] = None
    badge["superseded_by_badge_id"] = new_badge["id"]
    logic.revoke_granted_privilege(badge["id"], "SUPERSEDED")
    db.touch(badge)

    return success_object(serialize(new_badge), 201)
