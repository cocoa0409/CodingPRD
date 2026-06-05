"""NofoApplication endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import errors
from middleware import require_roles
from response import success
from services import common as c

bp = Blueprint("applications", __name__)

APPLICATION_STATUSES = {
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISIONS_REQUESTED",
    "AWARDED", "REJECTED", "WITHDRAWN",
}


def _serialize(app):
    return c.serialize(app)


@bp.route("/applications", methods=["POST"])
@require_roles("GrantWriter")
def create_application(user_id, role):
    body = c.get_body()

    nofo_number = c.require_nonempty_string(body, "nofo_number")
    applicant_org_name = c.require_nonempty_string(body, "applicant_org_name")
    requested_amount_cents = c.require_int(body, "requested_amount_cents", minimum=1)

    # federal_share_pct: optional, default 0.80, 0 < pct <= 1 (PRD §3.1).
    if "federal_share_pct" in body and body["federal_share_pct"] is not None:
        federal_share_pct = c.require_number(body, "federal_share_pct")
        if not (0 < federal_share_pct <= 1):
            raise errors.invalid_request("federal_share_pct must be in (0, 1].")
    else:
        federal_share_pct = 0.80

    period_start_date = c.require_datetime_str(body, "period_start_date")
    period_end_date = c.require_datetime_str(body, "period_end_date")

    # supersedes_application_id: optional FK -> NofoApplication.id, nullable.
    supersedes = body.get("supersedes_application_id")
    if supersedes is not None:
        if not isinstance(supersedes, str):
            raise errors.invalid_request("supersedes_application_id must be a string.")
        if supersedes not in db.applications:
            raise errors.not_found("supersedes_application_id does not exist.")

    with db.LOCK:
        record = {
            "nofo_number": nofo_number,
            "applicant_org_name": applicant_org_name,
            "requested_amount_cents": requested_amount_cents,
            "federal_share_pct": federal_share_pct,
            "period_start_date": period_start_date,
            "period_end_date": period_end_date,
            "supersedes_application_id": supersedes,
            "status": "DRAFT",
        }
        db.stamp_create(record)
        db.applications[record["id"]] = record
        out = _serialize(record)
    return success(out, status=201)


@bp.route("/applications", methods=["GET"])
@require_roles("GrantWriter", "AgencyOfficer")
def list_applications(user_id, role):
    limit, offset = c.parse_pagination()
    from flask import request
    supersedes = request.args.get("supersedes_application_id")
    status = request.args.get("status")

    with db.LOCK:
        records = list(db.applications.values())
    if supersedes is not None:
        records = [r for r in records if r.get("supersedes_application_id") == supersedes]
    if status is not None:
        records = [r for r in records if r["status"] == status]

    page, pagination = c.paginate(records, limit, offset)
    return success([_serialize(r) for r in page], status=200, pagination=pagination)


@bp.route("/applications/<app_id>", methods=["GET"])
@require_roles("GrantWriter", "AgencyOfficer")
def get_application(app_id, user_id, role):
    with db.LOCK:
        app = db.applications.get(app_id)
        if app is None:
            raise errors.not_found("Application not found.")
        return success(_serialize(app), status=200)


def _load(app_id):
    app = db.applications.get(app_id)
    if app is None:
        raise errors.not_found("Application not found.")
    return app


@bp.route("/applications/<app_id>/submit", methods=["POST"])
@require_roles("GrantWriter")
def submit_application(app_id, user_id, role):
    with db.LOCK:
        app = _load(app_id)
        # State: only DRAFT or REVISIONS_REQUESTED may submit (PRD §3.1).
        if app["status"] not in ("DRAFT", "REVISIONS_REQUESTED"):
            raise errors.invalid_state("Application is not DRAFT or REVISIONS_REQUESTED.")
        # Period ordering (ERR_INVALID_PERIOD, priority 11) after state check.
        start = c.parse_dt(app["period_start_date"])
        end = c.parse_dt(app["period_end_date"])
        if start is None or end is None or not (end > start):
            raise errors.invalid_period()
        app["status"] = "SUBMITTED"
        db.touch(app)
        return success(_serialize(app), status=200)


@bp.route("/applications/<app_id>/withdraw", methods=["POST"])
@require_roles("GrantWriter")
def withdraw_application(app_id, user_id, role):
    with db.LOCK:
        app = _load(app_id)
        if app["status"] != "DRAFT":
            raise errors.invalid_state("Only a DRAFT application may be withdrawn.")
        app["status"] = "WITHDRAWN"
        db.touch(app)
        return success(_serialize(app), status=200)


@bp.route("/applications/<app_id>/begin-review", methods=["POST"])
@require_roles("AgencyOfficer")
def begin_review(app_id, user_id, role):
    with db.LOCK:
        app = _load(app_id)
        if app["status"] != "SUBMITTED":
            raise errors.invalid_state("Only a SUBMITTED application may begin review.")
        app["status"] = "UNDER_REVIEW"
        db.touch(app)
        return success(_serialize(app), status=200)


@bp.route("/applications/<app_id>/request-revisions", methods=["POST"])
@require_roles("AgencyOfficer")
def request_revisions(app_id, user_id, role):
    with db.LOCK:
        app = _load(app_id)
        if app["status"] != "UNDER_REVIEW":
            raise errors.invalid_state("Application must be UNDER_REVIEW.")
        app["status"] = "REVISIONS_REQUESTED"
        db.touch(app)
        return success(_serialize(app), status=200)


@bp.route("/applications/<app_id>/reject", methods=["POST"])
@require_roles("AgencyOfficer")
def reject_application(app_id, user_id, role):
    with db.LOCK:
        app = _load(app_id)
        if app["status"] != "UNDER_REVIEW":
            raise errors.invalid_state("Application must be UNDER_REVIEW.")
        app["status"] = "REJECTED"
        db.touch(app)
        return success(_serialize(app), status=200)


@bp.route("/applications/<app_id>/award", methods=["POST"])
@require_roles("AgencyOfficer")
def award_application(app_id, user_id, role):
    from services.award import create_award_from_application
    with db.LOCK:
        app = _load(app_id)
        if app["status"] != "UNDER_REVIEW":
            raise errors.invalid_state("Application must be UNDER_REVIEW.")
        app["status"] = "AWARDED"
        db.touch(app)
        award = create_award_from_application(app)
        from services.award import serialize_award
        return success(serialize_award(award), status=201)
