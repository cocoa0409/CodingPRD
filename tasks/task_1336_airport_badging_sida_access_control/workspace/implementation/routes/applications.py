"""Badge application endpoints (PRD §3.1, §3.2, §3.4)."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_ACTIVE_BADGE_EXISTS,
    ERR_APPLICATION_NOT_FOUND,
    ERR_APPLICATION_NOT_OPEN,
    ERR_APPLICATION_NOT_READY,
    ERR_APPLICANT_NOT_FOUND,
    ERR_BADGE_NUMBER_TAKEN,
    ERR_OPEN_APPLICATION_EXISTS,
    ERR_SPONSOR_DELINQUENT,
    ERR_SPONSOR_NOT_ACTIVE,
    ERR_SPONSOR_OWNERSHIP_MISMATCH,
    ERR_SPONSOR_QUOTA_EXCEEDED,
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
    require_datetime,
    require_enum,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("applications", __name__)


@bp.route("/applications", methods=["POST"])
@require_roles("SponsorSignatory")
def create_application(user_id: str, role: str):
    body = get_json_body()
    applicant_id = require_string(body, "applicant_id")

    applicant = db.STORES["applicants"].get(applicant_id)
    if applicant is None:
        raise_err(ERR_APPLICANT_NOT_FOUND, "No applicant with the given id")

    # Priority 3: SponsorSignatory ownership over the target applicant.
    if applicant["sponsor_id"] != user_id:
        raise_err(
            ERR_SPONSOR_OWNERSHIP_MISMATCH,
            "SponsorSignatory may open applications only for its own applicants",
        )

    badge_class = require_enum(body, "badge_class", logic.BADGE_CLASSES)

    sponsor = db.STORES["sponsors"].get(applicant["sponsor_id"])
    if sponsor is None or sponsor["status"] != "ACTIVE":
        raise_err(ERR_SPONSOR_NOT_ACTIVE, "Sponsor must be ACTIVE to open applications")

    for app in db.STORES["applications"].values():
        if (
            app["applicant_id"] == applicant_id
            and app["status"] in logic.NON_TERMINAL_APP_STATUSES
        ):
            raise_err(
                ERR_OPEN_APPLICATION_EXISTS,
                "Applicant already has a non-terminal application",
            )

    now = db.clock_now()
    expires = now + timedelta(days=logic.APPLICATION_WINDOW_DAYS)
    rec = {
        "applicant_id": applicant_id,
        "sponsor_id": applicant["sponsor_id"],
        "badge_class": badge_class,
        "status": "SUBMITTED",
        "chrc_outcome": None,
        "sta_outcome": None,
        "denial_reason": None,
        "submitted_at": db.fmt_clock(now),
        "application_expires_at": db.fmt_clock(expires),
        "issued_badge_id": None,
        "_submitted_dt": now,
        "_app_expires_dt": expires,
    }
    db.stamp_new(rec)
    db.STORES["applications"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.route("/applications", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_applications(user_id: str, role: str):
    limit, offset = parse_pagination()
    items = apply_filters(
        list(db.STORES["applications"].values()),
        ["applicant_id", "sponsor_id", "status"],
    )
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/applications/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_application(user_id: str, role: str, aid: str):
    app = fetch_or_404("applications", aid, ERR_APPLICATION_NOT_FOUND, "application")
    return success_object(serialize(app))


@bp.route("/applications/<aid>/record-chrc", methods=["POST"])
@require_roles("BadgingOfficer")
def record_chrc(user_id: str, role: str, aid: str):
    app = fetch_or_404("applications", aid, ERR_APPLICATION_NOT_FOUND, "application")
    body = get_json_body()
    require_datetime(body, "fingerprint_submitted_at")
    outcome = require_enum(body, "outcome", {"PASS", "FAIL"})

    if app["status"] != "SUBMITTED":
        raise_err(
            ERR_APPLICATION_NOT_OPEN,
            "record-chrc requires the application to be SUBMITTED",
        )

    app["chrc_outcome"] = outcome
    if outcome == "PASS":
        # STA is submitted to the TSA as part of the same record.
        app["status"] = "STA_PENDING"
    else:
        app["status"] = "DENIED"
        app["denial_reason"] = "CHRC_FAILED"
    db.touch(app)
    return success_object(serialize(app))


@bp.route("/applications/<aid>/record-sta-result", methods=["POST"])
@require_roles("BadgingOfficer")
def record_sta_result(user_id: str, role: str, aid: str):
    app = fetch_or_404("applications", aid, ERR_APPLICATION_NOT_FOUND, "application")
    body = get_json_body()
    outcome = require_enum(body, "outcome", {"CLEARED", "DENIED"})

    if app["status"] != "STA_PENDING":
        raise_err(
            ERR_APPLICATION_NOT_OPEN,
            "record-sta-result requires the application to be STA_PENDING",
        )

    app["sta_outcome"] = outcome
    if outcome == "DENIED":
        app["status"] = "DENIED"
        app["denial_reason"] = "STA_DENIED"
        db.touch(app)
    else:
        app["status"] = "PENDING_REQUIREMENTS"
        # Readiness evaluation runs immediately; a fully current applicant
        # continues straight through to READY. Exactly one version bump.
        promoted = logic.ready_evaluate(app, db.clock_now())
        if not promoted:
            db.touch(app)
    return success_object(serialize(app))


@bp.route("/applications/<aid>/withdraw", methods=["POST"])
@require_roles("SponsorSignatory")
def withdraw_application(user_id: str, role: str, aid: str):
    app = fetch_or_404("applications", aid, ERR_APPLICATION_NOT_FOUND, "application")

    # Priority 3: SponsorSignatory ownership over the application.
    if app["sponsor_id"] != user_id:
        raise_err(
            ERR_SPONSOR_OWNERSHIP_MISMATCH,
            "SponsorSignatory may withdraw only its own sponsor's applications",
        )

    if app["status"] not in logic.NON_TERMINAL_APP_STATUSES:
        raise_err(
            ERR_APPLICATION_NOT_OPEN,
            "Only a non-terminal application may be withdrawn",
        )

    app["status"] = "WITHDRAWN"
    db.touch(app)
    return success_object(serialize(app))


@bp.route("/applications/<aid>/issue-badge", methods=["POST"])
@require_roles("BadgingOfficer")
def issue_badge(user_id: str, role: str, aid: str):
    app = fetch_or_404("applications", aid, ERR_APPLICATION_NOT_FOUND, "application")
    body = get_json_body()
    badge_number = require_string(body, "badge_number")
    now = db.clock_now()

    # Priority 5: state gate.
    if app["status"] != "READY":
        raise_err(ERR_APPLICATION_NOT_READY, "issue-badge requires a READY application")

    # Priority 7: uniqueness gates (overlap first, then badge_number).
    for badge in db.STORES["badges"].values():
        if (
            badge["applicant_id"] == app["applicant_id"]
            and badge["badge_class"] == app["badge_class"]
            and badge["status"] in ("ACTIVE", "SUSPENDED", "LOST", "STOLEN")
            and badge["_issued_dt"] <= now < badge["_expires_dt"]
        ):
            raise_err(
                ERR_ACTIVE_BADGE_EXISTS,
                "Applicant already holds a conflicting badge of this class",
            )
    for badge in db.STORES["badges"].values():
        if badge["badge_number"] == badge_number:
            raise_err(ERR_BADGE_NUMBER_TAKEN, "badge_number is already in use")

    # Priority 9: sponsor delinquency.
    if logic.sponsor_delinquent(app["sponsor_id"], now):
        raise_err(
            ERR_SPONSOR_DELINQUENT,
            "Sponsor has an overdue unreturned badge",
        )

    # Priority 10: sponsor quota (blocked at count == quota).
    sponsor = db.STORES["sponsors"].get(app["sponsor_id"])
    quota = sponsor["active_badge_quota"] if sponsor else 0
    if logic.sponsor_active_badge_count(app["sponsor_id"]) >= quota:
        raise_err(ERR_SPONSOR_QUOTA_EXCEEDED, "Sponsor active badge quota reached")

    expires = logic.compute_badge_expiry(
        app["applicant_id"], app["badge_class"], now, grace=False
    )

    badge = {
        "application_id": app["id"],
        "applicant_id": app["applicant_id"],
        "sponsor_id": app["sponsor_id"],
        "badge_number": badge_number,
        "badge_class": app["badge_class"],
        "status": "ACTIVE",
        "issued_at": db.fmt_clock(now),
        "expires_at": db.fmt_clock(expires),
        "deactivated_at": None,
        "return_deadline": None,
        "returned_at": None,
        "suspended_by": None,
        "suspended_until": None,
        "suspension_reason": None,
        "superseded_by_badge_id": None,
        "_issued_dt": now,
        "_expires_dt": expires,
        "_deactivated_dt": None,
        "_return_deadline_dt": None,
        "_suspended_until_dt": None,
    }
    db.stamp_new(badge)
    db.STORES["badges"][badge["id"]] = badge

    app["status"] = "ISSUED"
    app["issued_badge_id"] = badge["id"]
    db.touch(app)

    return success_object(serialize(badge), 201)
