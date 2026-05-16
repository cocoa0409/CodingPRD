"""Admin / test-driving endpoints: clock advance, age-invoices sweep, reconcile-aptc sweep."""

from datetime import date
from decimal import Decimal

from flask import Blueprint, request

from db import db, bump_version
from clock import clock
from errors import raise_error
from middleware import auth_required
from response import success_object
from services.calculations import (
    compute_aptc_estimated,
    find_benchmark_silver,
    household_members_for,
    classify_csr,
)
from services.constants import (
    applicable_percentage,
    fpl_denominator,
)
from services.dates import parse_iso_date, parse_iso_datetime
from services.enrollment_engine import (
    rollup_payment_status,
    maybe_update_coverage_status,
    ensure_monthly_invoices_issued,
)
from services.window import refresh_enrollment_window
from services.money import half_up_int


bp = Blueprint("admin", __name__)


# ---- POST /__test__/reset ----
# Test-infrastructure-only endpoint. Wipes in-memory state and resets the
# logical clock so each test starts from a clean slate. Not part of the
# PRD-described API surface; mirrors the harness contract used by every
# task's conftest to isolate tests.
@bp.post("/__test__/reset")
def __test_reset():
    db.reset()
    # Default the logical clock to a date safely inside the OEP for
    # coverage_year=2026 (the default coverage_year used by fixtures).
    # PRD §3.4 ties enrollment_window to a date-based OEP; with the
    # real clock at 2026-05-16 the window is CLOSED, blocking fixtures
    # that need to /approve and /enroll. Setting a fixed clock here
    # gives every test a deterministic, in-OEP starting point. Tests
    # that need a different date will call /_clock/advance afterwards.
    clock.advance_to("2025-12-15T00:00:00.000Z")
    return success_object({"ok": True})


# ---- POST /_clock/advance ----

@bp.post("/_clock/advance")
@auth_required(allowed_roles={"MarketplaceAdmin"})
def clock_advance():
    body = request.get_json(silent=True) or {}
    to_ts = body.get("to_timestamp")
    if not to_ts:
        raise_error("ERR_INVALID_STATE", "to_timestamp required")
    try:
        new_now = clock.advance_to(to_ts)
    except Exception:
        raise_error("ERR_INVALID_STATE", "Invalid to_timestamp")

    # Side effects:
    # 1. Expire VERIFIED SEPEvents whose window_closes_on < new_now and have no Enrollment
    now_date = new_now.date()
    for sep in list(db.sep_events.values()):
        if sep["status"] != "VERIFIED":
            continue
        if not sep.get("window_closes_on"):
            continue
        closes = parse_iso_date(sep["window_closes_on"])
        if closes < now_date:
            # Has Enrollment been created for this app within the SEP window?
            app_id = sep["application_id"]
            has_enrollment_in_window = any(
                e["application_id"] == app_id
                and parse_iso_date(e["created_at"][:10]) <= closes
                for e in db.enrollments.values()
            )
            if not has_enrollment_in_window:
                sep["status"] = "EXPIRED"
                bump_version(sep)

    # 2. Refresh enrollment_window for every application
    for app in db.applications.values():
        refresh_enrollment_window(app)

    # 3. Rollup payment_status for every ACTIVE/GRACE/PENDING enrollment
    for e in db.enrollments.values():
        if e["coverage_status"] in ("ACTIVE", "GRACE_PERIOD", "PENDING_PAYMENT"):
            rollup_payment_status(e)
            maybe_update_coverage_status(e)

    return success_object({"now": clock.now_iso()})


# ---- POST /_sweep/age-invoices ----

@bp.post("/_sweep/age-invoices")
@auth_required(allowed_roles={"MarketplaceAdmin"})
def sweep_age_invoices():
    transitions = []
    for e in list(db.enrollments.values()):
        if e["coverage_status"] not in ("ACTIVE", "GRACE_PERIOD", "PENDING_PAYMENT"):
            continue
        before = (e["coverage_status"], e["payment_status"])
        rollup_payment_status(e)
        maybe_update_coverage_status(e)
        after = (e["coverage_status"], e["payment_status"])
        if before != after:
            transitions.append({
                "enrollment_id": e["id"],
                "before_coverage_status": before[0],
                "after_coverage_status": after[0],
                "before_payment_status": before[1],
                "after_payment_status": after[1],
            })
    return success_object({"transitions": transitions})


# ---- POST /_sweep/reconcile-aptc ----

@bp.post("/_sweep/reconcile-aptc")
@auth_required(allowed_roles={"MarketplaceAdmin"})
def sweep_reconcile_aptc():
    body = request.get_json(silent=True) or {}
    coverage_year = body.get("coverage_year")
    if not isinstance(coverage_year, int):
        raise_error("ERR_INVALID_STATE", "coverage_year required")

    affected = []
    for app in db.applications.values():
        if app["status"] != "APPROVED":
            continue
        if app["coverage_year"] != coverage_year:
            continue

        # Replay chronological income for each month
        benchmark = find_benchmark_silver(app["filing_state"], coverage_year)
        if benchmark is None:
            app["aptc_reconciled_cents"] = 0
            bump_version(app)
            continue

        members = household_members_for(app["id"])
        # Pre-compute annual benchmark premium (use coverage_year start as reference)
        from services.calculations import monthly_premium_for_plan
        ref_date = date(coverage_year, 1, 1)
        monthly_benchmark = monthly_premium_for_plan(benchmark, members, ref_date)

        # household_size: count of include_in_household=True members
        household_size = sum(1 for m in members if m["include_in_household"])
        if household_size < 1:
            household_size = 1
        fpl_version = app.get("pinned_fpl_table_version") or "v1"
        denom = fpl_denominator(fpl_version, household_size)

        income_members = [m for m in members if m["include_in_magi"]]
        income_members_ids = {m["id"] for m in income_members}

        total_aptc_year = 0
        for month in range(1, 13):
            month_start = date(coverage_year, month, 1)
            # Sum income records effective at month_start
            month_total = 0
            for rec in db.income_records.values():
                if rec["member_id"] not in income_members_ids:
                    continue
                eff = parse_iso_date(rec["effective_date"])
                if eff > month_start:
                    continue
                # Effective unless superseded by an earlier-or-same effective_date record
                if rec.get("superseded_by_id"):
                    super_rec = db.income_records.get(rec["superseded_by_id"])
                    if super_rec is not None:
                        super_eff = parse_iso_date(super_rec["effective_date"])
                        if super_eff <= month_start:
                            # Superseded for this month
                            continue
                month_total += rec["amount_cents"]
            # Compute fpl% for this month
            if denom <= 0:
                fpl_pct = 0.0
            else:
                raw = (Decimal(month_total) / Decimal(denom)) * Decimal(100)
                from decimal import ROUND_HALF_UP as RH
                fpl_pct = float(raw.quantize(Decimal("0.1"), rounding=RH))

            if fpl_pct < 100.0:
                continue
            fraction = applicable_percentage(fpl_pct)
            if fraction >= 1.0:
                continue
            expected_contrib = half_up_int(Decimal(month_total) * Decimal(str(fraction)))
            annual_benchmark = monthly_benchmark * 12
            month_aptc_annual = max(0, annual_benchmark - expected_contrib)
            month_aptc = half_up_int(Decimal(month_aptc_annual) / Decimal(12))
            total_aptc_year += month_aptc

        app["aptc_reconciled_cents"] = total_aptc_year
        bump_version(app)
        affected.append(app["id"])

    return success_object({"reconciled_application_ids": affected})
