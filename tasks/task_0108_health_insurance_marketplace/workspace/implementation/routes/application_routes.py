"""Application-level endpoints: create, list, get, submit/amend/determine/approve/deny/redetermine."""

from datetime import date
from flask import Blueprint, request, g

from db import db, stamp_created, bump_version, now_iso
from clock import clock
from errors import raise_error
from middleware import auth_required
from response import success_object, success_array
from services.constants import VALID_STATES
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
from services.constants import fpl_version_for_year
from services.dates import parse_iso_date
from services.pagination import parse_pagination, paginate
from services.serializers import serialize_application
from services.window import resolve_enrollment_window, refresh_enrollment_window
from services.enrollment_engine import (
    recompute_enrollment_premium,
    issue_premium_invoice,
    derive_coverage_start,
)


bp = Blueprint("applications", __name__)


# ---- helpers ----

def _check_application_owner(app: dict):
    if g.user_role == "Applicant" and app["applicant_id"] != g.user_id:
        raise_error("ERR_NOT_APPLICATION_OWNER")


def _find_application_or_404(app_id: str) -> dict:
    app = db.applications.get(app_id)
    if app is None:
        raise_error("ERR_NOT_FOUND")
    return app


def _refresh_rollups(app: dict) -> None:
    """Recompute household_size and total_magi_cents (and possibly fpl_percentage if pinned)."""
    app["household_size"] = compute_household_size(app["id"])
    if app["status"] != "DRAFT":
        # During SUBMITTED+, recompute total_magi and fpl% from pinned version
        app["total_magi_cents"] = compute_total_magi_cents(app["id"])
        if app.get("pinned_fpl_table_version"):
            app["fpl_percentage"] = compute_fpl_percentage(
                app["total_magi_cents"],
                app["household_size"],
                app["pinned_fpl_table_version"],
            )


# ---- POST /applications ----

@bp.post("/applications")
@auth_required(allowed_roles={"Applicant"})
def create_application():
    body = request.get_json(silent=True) or {}
    coverage_year = body.get("coverage_year")
    filing_state = body.get("filing_state")
    if not isinstance(coverage_year, int) or filing_state not in VALID_STATES:
        raise_error("ERR_COVERAGE_YEAR_INVALID")

    # Reject duplicate non-terminal application for same coverage_year by same applicant
    for existing in db.applications.values():
        if existing["applicant_id"] == g.user_id and existing["coverage_year"] == coverage_year:
            if existing["status"] != "DENIED":
                raise_error("ERR_INVALID_STATE", "Applicant already has an active application for this coverage_year")

    app = {
        "applicant_id": g.user_id,
        "coverage_year": coverage_year,
        "status": "DRAFT",
        "filing_state": filing_state,
        "enrollment_window": "CLOSED",  # filled on resolve
        "household_size": 0,
        "total_magi_cents": None,
        "fpl_percentage": None,
        "csr_eligibility": None,
        "aptc_estimated_cents": None,
        "aptc_reconciled_cents": None,
        "pinned_fpl_table_version": None,
        "submitted_at": None,
        "approved_at": None,
    }
    stamp_created(app, versioned=True)
    db.applications[app["id"]] = app
    refresh_enrollment_window(app)
    return success_object(serialize_application(app), status=201)


# ---- GET /applications/{id} ----

@bp.get("/applications/<app_id>")
@auth_required(allowed_roles={"Applicant", "MarketplaceAdmin", "CustomerService"})
def get_application(app_id):
    app = _find_application_or_404(app_id)
    _check_application_owner(app)
    refresh_enrollment_window(app)
    return success_object(serialize_application(app))


# ---- GET /applications ----

@bp.get("/applications")
@auth_required(allowed_roles={"Applicant", "MarketplaceAdmin", "CustomerService"})
def list_applications():
    items = list(db.applications.values())
    if g.user_role == "Applicant":
        items = [a for a in items if a["applicant_id"] == g.user_id]

    status_f = request.args.get("status")
    if status_f:
        items = [a for a in items if a["status"] == status_f]
    coverage_year_f = request.args.get("coverage_year")
    if coverage_year_f:
        try:
            cy = int(coverage_year_f)
            items = [a for a in items if a["coverage_year"] == cy]
        except ValueError:
            pass
    filing_state_f = request.args.get("filing_state")
    if filing_state_f:
        items = [a for a in items if a["filing_state"] == filing_state_f]

    # default sort: created_at ascending
    items.sort(key=lambda a: a["created_at"])
    for a in items:
        refresh_enrollment_window(a)

    limit, offset = parse_pagination()
    page, meta = paginate(items, limit, offset)
    return success_array([serialize_application(a) for a in page], meta)


# ---- POST /applications/{id}/submit ----

@bp.post("/applications/<app_id>/submit")
@auth_required(allowed_roles={"Applicant"})
def submit_application(app_id):
    app = _find_application_or_404(app_id)
    _check_application_owner(app)
    if app["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE")

    members = household_members_for(app["id"])
    primary_filers = [m for m in members if m["filer_type"] == "PRIMARY_FILER"]
    if len(primary_filers) != 1:
        raise_error("ERR_MISSING_PRIMARY_FILER")

    current_year = clock.now().year
    if app["coverage_year"] not in (current_year, current_year + 1):
        raise_error("ERR_COVERAGE_YEAR_INVALID")

    # Every member with include_in_magi=true must have at least one IncomeRecord
    for m in members:
        if m["include_in_magi"]:
            has_record = any(r["member_id"] == m["id"] for r in db.income_records.values())
            if not has_record:
                raise_error("ERR_INVALID_STATE", "All members with include_in_magi=true must have at least one IncomeRecord")

    # MAGI floor 0 — sum may not be negative
    total_magi = compute_total_magi_cents(app["id"])
    if total_magi < 0:
        raise_error("ERR_MAGI_NEGATIVE")

    app["submitted_at"] = now_iso()
    app["pinned_fpl_table_version"] = fpl_version_for_year(app["coverage_year"])
    app["household_size"] = compute_household_size(app["id"])
    app["total_magi_cents"] = total_magi
    app["fpl_percentage"] = compute_fpl_percentage(
        total_magi, app["household_size"], app["pinned_fpl_table_version"]
    )
    app["status"] = "SUBMITTED"
    bump_version(app)
    refresh_enrollment_window(app)
    return success_object(serialize_application(app))


# ---- POST /applications/{id}/amend ----

@bp.post("/applications/<app_id>/amend")
@auth_required(allowed_roles={"Applicant"})
def amend_application(app_id):
    app = _find_application_or_404(app_id)
    _check_application_owner(app)
    if app["status"] != "SUBMITTED":
        raise_error("ERR_INVALID_STATE")
    app["status"] = "DRAFT"
    app["submitted_at"] = None
    app["pinned_fpl_table_version"] = None
    app["fpl_percentage"] = None
    app["total_magi_cents"] = None
    bump_version(app)
    return success_object(serialize_application(app))


# ---- POST /applications/{id}/determine-eligibility ----

@bp.post("/applications/<app_id>/determine-eligibility")
@auth_required(allowed_roles={"MarketplaceAdmin"})
def determine_eligibility(app_id):
    app = _find_application_or_404(app_id)
    if app["status"] != "SUBMITTED":
        raise_error("ERR_INVALID_STATE")

    # Recompute rollups (membership might have changed mid-flight)
    app["household_size"] = compute_household_size(app["id"])
    app["total_magi_cents"] = compute_total_magi_cents(app["id"])
    app["fpl_percentage"] = compute_fpl_percentage(
        app["total_magi_cents"], app["household_size"], app["pinned_fpl_table_version"]
    )
    # Benchmark must exist
    benchmark = find_benchmark_silver(app["filing_state"], app["coverage_year"])
    if benchmark is None:
        raise_error("ERR_NO_BENCHMARK_PLAN")

    fpl_pct = app["fpl_percentage"] or 0.0
    if fpl_pct < 100.0:
        app["csr_eligibility"] = "NONE"
        app["aptc_estimated_cents"] = 0
    else:
        app["csr_eligibility"] = classify_csr(fpl_pct)
        members = household_members_for(app["id"])
        app["aptc_estimated_cents"] = compute_aptc_estimated(app, members)

    # Per-member Medicaid eligibility
    for m in household_members_for(app["id"]):
        m["medicaid_eligible"] = medicaid_eligible_for_member(m, app)
        bump_version(m)

    app["status"] = "ELIGIBILITY_DETERMINED"
    bump_version(app)
    refresh_enrollment_window(app)
    return success_object(serialize_application(app))


# ---- POST /applications/{id}/approve ----

@bp.post("/applications/<app_id>/approve")
@auth_required(allowed_roles={"MarketplaceAdmin"})
def approve_application(app_id):
    app = _find_application_or_404(app_id)
    if app["status"] != "ELIGIBILITY_DETERMINED":
        raise_error("ERR_INVALID_STATE")
    refresh_enrollment_window(app)
    if app["enrollment_window"] == "CLOSED":
        raise_error("ERR_OUTSIDE_ENROLLMENT_WINDOW")

    included_members = [
        m for m in household_members_for(app["id"]) if m["include_in_household"]
    ]
    if not included_members or all(m.get("medicaid_eligible") for m in included_members):
        raise_error("ERR_INVALID_STATE", "All included members are Medicaid-eligible; application should be denied")

    app["status"] = "APPROVED"
    app["approved_at"] = now_iso()
    bump_version(app)
    return success_object(serialize_application(app))


# ---- POST /applications/{id}/deny ----

@bp.post("/applications/<app_id>/deny")
@auth_required(allowed_roles={"MarketplaceAdmin"})
def deny_application(app_id):
    app = _find_application_or_404(app_id)
    if app["status"] != "ELIGIBILITY_DETERMINED":
        raise_error("ERR_INVALID_STATE")
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")  # optional

    refresh_enrollment_window(app)
    included = [m for m in household_members_for(app["id"]) if m["include_in_household"]]
    everyone_medicaid = bool(included) and all(m.get("medicaid_eligible") for m in included)
    window_closed = app["enrollment_window"] == "CLOSED"
    if not (everyone_medicaid or window_closed):
        raise_error("ERR_INVALID_STATE", "Cannot deny: at least one member is not Medicaid-eligible AND window is open")

    app["status"] = "DENIED"
    if reason is not None:
        app["denial_reason"] = reason  # stored for audit
    bump_version(app)
    return success_object(serialize_application(app))


# ---- POST /applications/{id}/redetermine ----

@bp.post("/applications/<app_id>/redetermine")
@auth_required(allowed_roles={"MarketplaceAdmin"})
def redetermine_application(app_id):
    app = _find_application_or_404(app_id)
    if app["status"] != "APPROVED":
        raise_error("ERR_INVALID_STATE")

    # Must have at least one VERIFIED SEPEvent whose window is currently open
    now_date = clock.now().date()
    open_verified = []
    for s in db.sep_events.values():
        if s["application_id"] != app["id"]:
            continue
        if s["status"] != "VERIFIED":
            continue
        if s.get("window_closes_on") and parse_iso_date(s["window_closes_on"]) >= now_date:
            open_verified.append(s)
    if not open_verified:
        raise_error("ERR_INVALID_STATE", "Redetermine requires at least one open VERIFIED SEPEvent")

    # MAGI floor check
    total_magi = compute_total_magi_cents(app["id"])
    if total_magi < 0:
        raise_error("ERR_MAGI_NEGATIVE")

    # Recompute rollups
    app["household_size"] = compute_household_size(app["id"])
    app["total_magi_cents"] = total_magi
    if not app.get("pinned_fpl_table_version"):
        app["pinned_fpl_table_version"] = fpl_version_for_year(app["coverage_year"])
    app["fpl_percentage"] = compute_fpl_percentage(
        total_magi, app["household_size"], app["pinned_fpl_table_version"]
    )

    benchmark = find_benchmark_silver(app["filing_state"], app["coverage_year"])
    if benchmark is None:
        raise_error("ERR_NO_BENCHMARK_PLAN")

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

    # Cascade: if active Enrollment exists -> recompute premium + issue fresh invoice
    for e in db.enrollments.values():
        if e["application_id"] != app["id"]:
            continue
        if e["coverage_status"] in ("ACTIVE", "GRACE_PERIOD", "PENDING_PAYMENT"):
            recompute_enrollment_premium(e)
            # Determine next billing month based on /_clock.now()
            from services.dates import first_day_of_next_month, yyyy_mm
            next_month = first_day_of_next_month(clock.now().date())
            issue_premium_invoice(e, yyyy_mm(next_month))

    refresh_enrollment_window(app)
    return success_object(serialize_application(app))
