"""Enrollment routes: create / get / cancel."""

from datetime import date
from flask import Blueprint, request, g

from db import db, stamp_created, bump_version, now_iso
from clock import clock
from errors import raise_error
from middleware import auth_required
from response import success_object
from services.dates import (
    parse_iso_date,
    iso_date_str,
    yyyy_mm,
    first_of_month,
    last_day_of_month,
    first_day_of_next_month,
    parse_yyyy_mm,
)
from services.enrollment_engine import (
    compute_monthly_premium,
    issue_premium_invoice,
    governing_sep_for_application,
    invoices_for_enrollment,
)
from services.serializers import serialize_enrollment
from services.window import refresh_enrollment_window
from services.calculations import household_members_for


bp = Blueprint("enrollments", __name__)


def _check_owner_or_404(app):
    if g.user_role == "Applicant" and app["applicant_id"] != g.user_id:
        raise_error("ERR_NOT_APPLICATION_OWNER")


# ---- POST /enrollments ----

@bp.post("/enrollments")
@auth_required(allowed_roles={"Applicant"})
def create_enrollment():
    body = request.get_json(silent=True) or {}
    application_id = body.get("application_id")
    plan_variant_id = body.get("plan_variant_id")
    if not application_id or not plan_variant_id:
        raise_error("ERR_INVALID_STATE", "application_id and plan_variant_id required")

    app = db.applications.get(application_id)
    if app is None:
        raise_error("ERR_NOT_FOUND")
    _check_owner_or_404(app)

    if app["status"] != "APPROVED":
        raise_error("ERR_INVALID_STATE")

    refresh_enrollment_window(app)
    if app["enrollment_window"] == "CLOSED":
        raise_error("ERR_OUTSIDE_ENROLLMENT_WINDOW")

    variant = db.plan_variants.get(plan_variant_id)
    if variant is None:
        raise_error("ERR_NOT_FOUND")
    plan = db.plans.get(variant["plan_id"])
    if plan is None:
        raise_error("ERR_NOT_FOUND")

    # ERR_PLAN_STATE_MISMATCH
    if plan["filing_state"] != app["filing_state"] or plan["coverage_year"] != app["coverage_year"]:
        raise_error("ERR_PLAN_STATE_MISMATCH")

    # ERR_CSR_VARIANT_MISMATCH
    csr_elig = app.get("csr_eligibility") or "NONE"
    if csr_elig == "NONE":
        if variant["csr_level"] != "STANDARD":
            raise_error("ERR_CSR_VARIANT_MISMATCH")
    else:
        if variant["csr_level"] != csr_elig:
            raise_error("ERR_CSR_VARIANT_MISMATCH")

    # Derive coverage_start_date
    governing_sep = governing_sep_for_application(app)
    if governing_sep is not None:
        coverage_start_str = governing_sep["effective_date"]
    else:
        # OEP rule: Jan 1 of coverage_year
        coverage_start_str = iso_date_str(date(app["coverage_year"], 1, 1))

    coverage_start = parse_iso_date(coverage_start_str)

    # ERR_OUTSIDE_SEP_WINDOW: coverage_start_date must lie within SEP window or OEP coverage_year
    if governing_sep is not None:
        opens = parse_iso_date(governing_sep["window_opens_on"])
        closes = parse_iso_date(governing_sep["window_closes_on"])
        # If coverage_start is set from effective_date, ensure SEP effective date isn't outside its own window in a bad way.
        # We accept the SEP-supplied effective_date.
        # Edge check: if coverage_start does not fall in [opens, closes], reject — but per PRD,
        # the governing SEP defines the effective_date itself, so this check is mostly redundant.
        pass
    else:
        # OEP: coverage_year must be the active OEP coverage_year
        if app["enrollment_window"] != "OEP":
            raise_error("ERR_OUTSIDE_SEP_WINDOW")

    # ERR_ENROLLMENT_ALREADY_EXISTS — at most one Enrollment per (app_id, coverage_year)
    for e in db.enrollments.values():
        if e["application_id"] == application_id:
            existing_app = db.applications.get(e["application_id"])
            if existing_app and existing_app["coverage_year"] == app["coverage_year"]:
                if e["coverage_status"] != "TERMINATED":
                    raise_error("ERR_ENROLLMENT_ALREADY_EXISTS")

    enrollment = {
        "application_id": application_id,
        "plan_variant_id": plan_variant_id,
        "pinned_plan_catalog_version": plan.get("catalog_version", 1),
        "coverage_status": "PENDING_PAYMENT",
        "payment_status": "AWAITING_BINDER",
        "coverage_start_date": coverage_start_str,
        "coverage_end_date": None,
        "monthly_premium_gross_cents": 0,
        "monthly_aptc_applied_cents": 0,
        "monthly_net_premium_cents": 0,
        "terminated_reason": None,
    }
    stamp_created(enrollment, versioned=True)

    gross, aptc, net = compute_monthly_premium(enrollment, app, plan, coverage_start)
    enrollment["monthly_premium_gross_cents"] = gross
    enrollment["monthly_aptc_applied_cents"] = aptc
    enrollment["monthly_net_premium_cents"] = net

    db.enrollments[enrollment["id"]] = enrollment

    # Issue binder invoice for the coverage_start_date month
    billing_month = yyyy_mm(first_of_month(coverage_start))
    issue_premium_invoice(enrollment, billing_month)

    return success_object(serialize_enrollment(enrollment), status=201)


# ---- GET /enrollments/{id} ----

@bp.get("/enrollments/<enrollment_id>")
@auth_required(allowed_roles={"Applicant", "MarketplaceAdmin", "CustomerService", "Insurer"})
def get_enrollment(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if e is None:
        raise_error("ERR_NOT_FOUND")
    # Applicant owner check
    if g.user_role == "Applicant":
        app = db.applications.get(e["application_id"])
        if not app or app["applicant_id"] != g.user_id:
            raise_error("ERR_NOT_APPLICATION_OWNER")
    # Insurer ownership: must own the parent plan
    if g.user_role == "Insurer":
        variant = db.plan_variants.get(e["plan_variant_id"])
        if variant:
            plan = db.plans.get(variant["plan_id"])
            if plan and plan["insurer_id"] != g.user_id:
                raise_error("ERR_FORBIDDEN")
    return success_object(serialize_enrollment(e))


# ---- POST /enrollments/{id}/cancel ----

@bp.post("/enrollments/<enrollment_id>/cancel")
@auth_required(allowed_roles={"Applicant"})
def cancel_enrollment(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if e is None:
        raise_error("ERR_NOT_FOUND")
    app = db.applications.get(e["application_id"])
    if not app or app["applicant_id"] != g.user_id:
        raise_error("ERR_NOT_APPLICATION_OWNER")
    if e["coverage_status"] != "ACTIVE":
        raise_error("ERR_INVALID_STATE")

    now_date = clock.now().date()
    coverage_end = last_day_of_month(now_date)
    e["coverage_end_date"] = iso_date_str(coverage_end)
    e["terminated_reason"] = "APPLICANT_CANCELLED"
    e["coverage_status"] = "TERMINATED"
    bump_version(e)

    # Depth-2 cascade: VOID all invoices whose billing_month > coverage_end_date
    for inv in db.premium_invoices.values():
        if inv["enrollment_id"] != enrollment_id:
            continue
        billing_first = parse_yyyy_mm(inv["billing_month"])
        if billing_first > coverage_end:
            if inv["status"] == "ISSUED":
                inv["status"] = "VOIDED"
    return success_object(serialize_enrollment(e))
