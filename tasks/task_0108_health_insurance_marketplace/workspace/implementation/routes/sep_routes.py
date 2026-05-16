"""SEPEvent routes: create / verify / reject / appeal."""

from datetime import timedelta
from flask import Blueprint, request, g

from db import db, stamp_created, bump_version, now_iso
from clock import clock
from errors import raise_error
from middleware import auth_required
from response import success_object
from services.constants import VALID_SEP_EVENT_TYPES
from services.dates import parse_iso_date, parse_iso_datetime
from services.sep import compute_sep_dates
from services.serializers import serialize_sep_event
from services.window import refresh_enrollment_window
from services.calculations import (
    compute_household_size,
    compute_total_magi_cents,
    compute_fpl_percentage,
    classify_csr,
    medicaid_eligible_for_member,
    find_benchmark_silver,
    compute_aptc_estimated,
    household_members_for,
)
from services.enrollment_engine import (
    recompute_enrollment_premium,
    issue_premium_invoice,
)
from services.dates import first_day_of_next_month, yyyy_mm


bp = Blueprint("sep", __name__)


def _find_app_or_404(app_id):
    app = db.applications.get(app_id)
    if app is None:
        raise_error("ERR_NOT_FOUND")
    return app


def _check_owner(app):
    if g.user_role == "Applicant" and app["applicant_id"] != g.user_id:
        raise_error("ERR_NOT_APPLICATION_OWNER")


def _find_sep_or_404(sep_id, app_id):
    sep = db.sep_events.get(sep_id)
    if sep is None or sep["application_id"] != app_id:
        raise_error("ERR_NOT_FOUND")
    return sep


# ---- POST /applications/{id}/sep-events ----

@bp.post("/applications/<app_id>/sep-events")
@auth_required(allowed_roles={"Applicant"})
def create_sep_event(app_id):
    app = _find_app_or_404(app_id)
    _check_owner(app)

    body = request.get_json(silent=True) or {}
    event_type = body.get("event_type")
    event_date = body.get("event_date")
    if event_type not in VALID_SEP_EVENT_TYPES or not event_date:
        raise_error("ERR_INVALID_STATE", "event_type and event_date are required")
    try:
        parse_iso_date(event_date)
    except Exception:
        raise_error("ERR_INVALID_STATE", "Invalid event_date")

    sep = {
        "application_id": app_id,
        "event_type": event_type,
        "event_date": event_date,
        "reported_at": now_iso(),
        "status": "SUBMITTED",
        "window_opens_on": None,
        "window_closes_on": None,
        "effective_date": None,
    }
    stamp_created(sep, versioned=True)
    db.sep_events[sep["id"]] = sep
    return success_object(serialize_sep_event(sep), status=201)


# ---- POST /applications/{app_id}/sep-events/{id}/verify ----

@bp.post("/applications/<app_id>/sep-events/<sep_id>/verify")
@auth_required(allowed_roles={"MarketplaceAdmin"})
def verify_sep_event(app_id, sep_id):
    app = _find_app_or_404(app_id)
    sep = _find_sep_or_404(sep_id, app_id)
    if sep["status"] != "SUBMITTED":
        raise_error("ERR_INVALID_STATE")
    if app["status"] not in ("SUBMITTED", "ELIGIBILITY_DETERMINED", "APPROVED"):
        raise_error("ERR_INVALID_STATE")

    # ERR_SEP_WINDOW_EXPIRED: event_date > 60 days before now
    event_date = parse_iso_date(sep["event_date"])
    now_date = clock.now().date()
    if (now_date - event_date).days > 60:
        raise_error("ERR_SEP_WINDOW_EXPIRED")

    # Compute dates
    opens, closes, eff = compute_sep_dates(sep["event_type"], sep["event_date"], sep["reported_at"])
    sep["window_opens_on"] = opens
    sep["window_closes_on"] = closes
    sep["effective_date"] = eff
    sep["status"] = "VERIFIED"
    bump_version(sep)

    # Side effect: set parent app's enrollment_window = SEP
    app["enrollment_window"] = "SEP"
    bump_version(app)

    # Cascade for MARRIAGE / BIRTH_ADOPTION / MEDICAID_LOSS on APPROVED app w/ active enrollment
    if sep["event_type"] in ("MARRIAGE", "BIRTH_ADOPTION", "MEDICAID_LOSS"):
        if app["status"] == "APPROVED":
            active_enrollments = [
                e for e in db.enrollments.values()
                if e["application_id"] == app["id"]
                and e["coverage_status"] in ("ACTIVE", "GRACE_PERIOD", "PENDING_PAYMENT")
            ]
            if active_enrollments:
                # Force redetermine: revert APPROVED -> ELIGIBILITY_DETERMINED
                # Recompute eligibility
                app["household_size"] = compute_household_size(app["id"])
                app["total_magi_cents"] = compute_total_magi_cents(app["id"])
                if not app.get("pinned_fpl_table_version"):
                    from services.constants import fpl_version_for_year
                    app["pinned_fpl_table_version"] = fpl_version_for_year(app["coverage_year"])
                app["fpl_percentage"] = compute_fpl_percentage(
                    app["total_magi_cents"], app["household_size"], app["pinned_fpl_table_version"]
                )
                benchmark = find_benchmark_silver(app["filing_state"], app["coverage_year"])
                if benchmark is not None:
                    fpl_pct = app["fpl_percentage"] or 0.0
                    if fpl_pct < 100.0:
                        app["csr_eligibility"] = "NONE"
                        app["aptc_estimated_cents"] = 0
                    else:
                        app["csr_eligibility"] = classify_csr(fpl_pct)
                        members = household_members_for(app["id"])
                        app["aptc_estimated_cents"] = compute_aptc_estimated(app, members)
                for m in household_members_for(app["id"]):
                    m["medicaid_eligible"] = medicaid_eligible_for_member(m, app)
                    bump_version(m)
                app["status"] = "ELIGIBILITY_DETERMINED"
                bump_version(app)

                # Cascade enrollment recalc + fresh invoice
                for e in active_enrollments:
                    recompute_enrollment_premium(e)
                    next_month = first_day_of_next_month(clock.now().date())
                    issue_premium_invoice(e, yyyy_mm(next_month))

    return success_object(serialize_sep_event(sep))


# ---- POST /applications/{app_id}/sep-events/{id}/reject ----

@bp.post("/applications/<app_id>/sep-events/<sep_id>/reject")
@auth_required(allowed_roles={"MarketplaceAdmin"})
def reject_sep_event(app_id, sep_id):
    app = _find_app_or_404(app_id)
    sep = _find_sep_or_404(sep_id, app_id)
    if sep["status"] != "SUBMITTED":
        raise_error("ERR_INVALID_STATE")

    body = request.get_json(silent=True) or {}
    reason = body.get("reason")
    sep["status"] = "REJECTED"
    sep["rejected_at"] = now_iso()
    if reason is not None:
        sep["reject_reason"] = reason
    bump_version(sep)
    return success_object(serialize_sep_event(sep))


# ---- POST /applications/{app_id}/sep-events/{id}/appeal ----

@bp.post("/applications/<app_id>/sep-events/<sep_id>/appeal")
@auth_required(allowed_roles={"CustomerService"})
def appeal_sep_event(app_id, sep_id):
    app = _find_app_or_404(app_id)
    sep = _find_sep_or_404(sep_id, app_id)
    if sep["status"] != "REJECTED":
        raise_error("ERR_INVALID_STATE")

    rejected_at_str = sep.get("rejected_at")
    if rejected_at_str:
        rejected_at = parse_iso_datetime(rejected_at_str).date()
        now_date = clock.now().date()
        if (now_date - rejected_at).days > 30:
            raise_error("ERR_INVALID_STATE", "Appeal must be filed within 30 days of rejection")

    sep["status"] = "SUBMITTED"
    bump_version(sep)
    return success_object(serialize_sep_event(sep))
