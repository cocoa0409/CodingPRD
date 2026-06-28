"""BillingPeriod endpoints + finalize/reopen + line-items (PRD §3.8, §3.9)."""
from flask import Blueprint, request

import errors
import serializers
import validation as V
from clock import clock, parse_iso8601
from common import (get_json_body, parse_pagination, sort_by_created,
                    paginate)
from db import db, stamp_create, touch
from middleware import require_roles
from response import object_response, array_response
from services import lookups, periods, care_time

bp = Blueprint("billing_periods", __name__)

DEVICE_DAY_FLOOR = 16
CARE_TIME_FLOOR = 20


def _get_patient_or_404(pid):
    rec = db.patients.get(pid)
    if rec is None:
        raise errors.not_found("Patient not found.")
    return rec


def _get_period_or_404(period_id):
    rec = db.billing_periods.get(period_id)
    if rec is None:
        raise errors.not_found("Billing period not found.")
    return rec


@bp.post("/patients/<pid>/billing-periods")
@require_roles("BillingSpecialist")
def create_billing_period(pid):
    _get_patient_or_404(pid)
    body = get_json_body()
    period_year = V.require_int(body, "period_year", minimum=2024)
    period_month = V.require_int(body, "period_month", minimum=1, maximum=12)

    # Overlap (priority 15): collide with an existing non-REOPENED period on
    # the same (year, month) for the same patient.
    for existing in lookups.billing_periods_of(pid):
        if (existing["status"] != "REOPENED"
                and existing["period_year"] == period_year
                and existing["period_month"] == period_month):
            raise errors.ApiError(errors.ERR_PERIOD_OVERLAP, 409,
                                  "A billing period already exists for this month.")

    rec = {
        "patient_id": pid,
        "period_year": period_year,
        "period_month": period_month,
        "status": "OPEN",
        "provisional_total_minutes": 0,
        "distinct_device_days": 0,
        "finalized_total_minutes": None,
        "finalized_total_cents": None,
    }
    stamp_create(rec)
    db.billing_periods[rec["id"]] = rec
    return object_response(serializers.billing_period(rec), 201)


@bp.get("/patients/<pid>/billing-periods")
@require_roles("BillingSpecialist", "CareCoordinator")
def list_patient_billing_periods(pid):
    _get_patient_or_404(pid)
    limit, offset = parse_pagination()
    records = lookups.billing_periods_of(pid)
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serializers.billing_period(r) for r in page],
                          limit, offset, total)


@bp.get("/billing-periods/<period_id>")
@require_roles("BillingSpecialist", "CareCoordinator", "Physician")
def get_billing_period(period_id):
    rec = _get_period_or_404(period_id)
    return object_response(serializers.billing_period(rec))


def _finalized_minutes(period):
    """Frozen variant of care-time aggregation at finalize-time (PRD §3.8)."""
    acts = lookups.care_activities_of_period(period["id"])
    in_month = [a for a in acts
                if periods.instant_in_month(parse_iso8601(a["performed_at"]),
                                            period["period_year"],
                                            period["period_month"])]
    counted = care_time.compute_counted_minutes(in_month)
    return care_time.period_total(counted)


def _accrue_finalize_line_items(period):
    """Accrue 99454/99457 in pinned order; flip ACCRUED->FINALIZED; set
    finalized_total_cents to the sum of ACCRUED amounts (PRD §3.8)."""
    patient = db.patients.get(period["patient_id"])
    payer = db.payers.get(patient["payer_id"]) if patient else None

    # (1) 99454 device-supply: distinct_device_days >= 16.
    if period["distinct_device_days"] >= DEVICE_DAY_FLOOR:
        rate = payer["rate_99454_cents"] if payer else 0
        li = {
            "billing_period_id": period["id"],
            "cpt_code": "CPT_99454",
            "units": 1,
            "amount_cents": rate,
            "status": "ACCRUED",
        }
        stamp_create(li)
        db.line_items[li["id"]] = li

    # (2) 99457 care-management: finalized_total_minutes >= 20.
    if period["finalized_total_minutes"] >= CARE_TIME_FLOOR:
        rate = payer["rate_99457_cents"] if payer else 0
        li = {
            "billing_period_id": period["id"],
            "cpt_code": "CPT_99457",
            "units": 1,
            "amount_cents": rate,
            "status": "ACCRUED",
        }
        stamp_create(li)
        db.line_items[li["id"]] = li

    # finalized_total_cents = sum of ACCRUED line-item amounts; flip to FINALIZED.
    total_cents = 0
    for li in lookups.line_items_of_period(period["id"]):
        if li["status"] == "ACCRUED":
            total_cents += li["amount_cents"]
            li["status"] = "FINALIZED"
            touch(li)
    period["finalized_total_cents"] = total_cents


@bp.post("/billing-periods/<period_id>/finalize")
@require_roles("BillingSpecialist")
def finalize_billing_period(period_id):
    period = _get_period_or_404(period_id)
    body = get_json_body()

    # Required field (priority 5): expected_billing_period_version present/int.
    expected = V.require_int(body, "expected_billing_period_version")

    # State legality (priority 6): finalize from OPEN or REOPENED.
    if period["status"] not in ("OPEN", "REOPENED"):
        raise errors.invalid_state("Only an OPEN or REOPENED period can be finalized.")

    # OCC (priority 7): expected version must match current version.
    if expected != period["version"]:
        raise errors.stale_version(
            "expected_billing_period_version does not match current version.")

    # Temporal (priority 13): the calendar month must have fully elapsed.
    if not periods.month_fully_elapsed(period["period_year"],
                                       period["period_month"], clock.now()):
        raise errors.ApiError(errors.ERR_PERIOD_NOT_CLOSED, 409,
                              "The billing period's month has not fully elapsed.")

    # Compute finalized_total_minutes (frozen).
    period["finalized_total_minutes"] = _finalized_minutes(period)
    # Accrue eligible CPT line items and freeze totals.
    _accrue_finalize_line_items(period)
    period["status"] = "FINALIZED"
    touch(period)

    return object_response(serializers.billing_period(period))


@bp.post("/billing-periods/<period_id>/reopen")
@require_roles("BillingSpecialist")
def reopen_billing_period(period_id):
    period = _get_period_or_404(period_id)
    # State legality (priority 6): reopen from FINALIZED.
    if period["status"] != "FINALIZED":
        raise errors.invalid_state("Only a FINALIZED period can be reopened.")
    # No claim exists in any status other than DENIED.
    for c in lookups.claims_of_period(period_id):
        if c["status"] != "DENIED":
            raise errors.invalid_state(
                "A live claim exists for this period; cannot reopen.")

    # Void all FINALIZED line items.
    for li in lookups.line_items_of_period(period_id):
        if li["status"] == "FINALIZED":
            li["status"] = "VOIDED"
            touch(li)
    period["finalized_total_minutes"] = None
    period["finalized_total_cents"] = None
    period["status"] = "REOPENED"
    touch(period)

    return object_response(serializers.billing_period(period))


@bp.get("/billing-periods/<period_id>/line-items")
@require_roles("BillingSpecialist", "CareCoordinator")
def list_line_items(period_id):
    _get_period_or_404(period_id)
    limit, offset = parse_pagination()
    records = lookups.line_items_of_period(period_id)
    cpt_code = request.args.get("cpt_code")
    if cpt_code is not None:
        records = [r for r in records if r["cpt_code"] == cpt_code]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return array_response([serializers.line_item(r) for r in page],
                          limit, offset, total)
