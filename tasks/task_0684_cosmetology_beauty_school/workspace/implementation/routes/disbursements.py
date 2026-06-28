"""Disbursement routes (PRD 3.4, 3.5; §1.5)."""
from flask import Blueprint, request

import clock
import db
import errors
import helpers
import lookups
import response
from middleware import require
from services import calc, enrollment as esvc

bp = Blueprint("disbursements", __name__)


def _whole_weeks_elapsed(enrolled_on_iso):
    """Whole number of weeks elapsed since enrolled_on_iso, measured against the
    current logical clock (floor of days/7)."""
    enrolled = helpers.parse_dt(enrolled_on_iso)
    delta = clock.now() - enrolled
    days = delta.total_seconds() / 86400.0
    return int(days // 7)


@bp.post("/school/disbursements")
@require("FinancialAidOfficer")
def create_disbursement():
    data = helpers.body()
    helpers.require_fields(
        data, "enrollment_id", "payment_period", "period_hours",
        "period_weeks", "gross_amount_cents",
    )
    enrollment_id = helpers.require_str(data, "enrollment_id")
    # Priority 4: body FK existence.
    lookups.fk(db.enrollments, enrollment_id)
    payment_period = helpers.require_int(data, "payment_period")
    period_hours = helpers.require_int(data, "period_hours")
    if period_hours < 1:
        raise errors.invalid_request("period_hours must be >= 1")
    period_weeks = helpers.require_int(data, "period_weeks")
    if period_weeks < 1:
        raise errors.invalid_request("period_weeks must be >= 1")
    gross_amount_cents = helpers.require_int(data, "gross_amount_cents")
    if gross_amount_cents < 0:
        raise errors.invalid_request("gross_amount_cents must be >= 0")
    origination_fee_cents = helpers.opt_int(data, "origination_fee_cents", 0)
    if origination_fee_cents < 0:
        raise errors.invalid_request("origination_fee_cents must be >= 0")

    # Priority 6.2: payment_period in {1,2} and not already held by another
    # non-RETURNED disbursement on the same enrollment.
    if payment_period not in (1, 2):
        raise errors.invalid_period("payment_period must be 1 or 2")
    for d in db.disbursements.values():
        if (d["enrollment_id"] == enrollment_id
                and d["payment_period"] == payment_period
                and d["status"] != "RETURNED"):
            raise errors.invalid_period("payment_period already used")

    row = {
        "enrollment_id": enrollment_id,
        "payment_period": payment_period,
        "period_hours": period_hours,
        "period_weeks": period_weeks,
        "gross_amount_cents": gross_amount_cents,
        "origination_fee_cents": origination_fee_cents,
        "net_amount_cents": None,
        "status": "SCHEDULED",
    }
    db.stamp_new(row)
    db.disbursements[row["id"]] = row
    return response.created(row)


@bp.get("/school/disbursements/<did>")
@require("Registrar", "FinancialAidOfficer")
def get_disbursement(did):
    row = lookups.path(db.disbursements, did)
    return response.ok(row)


@bp.get("/school/disbursements")
@require("Registrar", "FinancialAidOfficer")
def list_disbursements():
    rows = list(db.disbursements.values())
    enrollment_id = request.args.get("enrollment_id")
    if enrollment_id:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)


@bp.post("/school/disbursements/<did>/post")
@require("FinancialAidOfficer")
def post_disbursement(did):
    row = lookups.path(db.disbursements, did)
    data = helpers.body()
    # OCC field is non-optional in the request body (priority 5 shape, then 18).
    helpers.require_fields(data, "expected_enrollment_version")
    expected = helpers.require_int(data, "expected_enrollment_version")

    # Priority 7: state precondition on the disbursement.
    if row["status"] != "SCHEDULED":
        raise errors.invalid_state()
    enrollment = db.enrollments[row["enrollment_id"]]
    # Owning enrollment must be ACTIVE or SAP_WARNING.
    if enrollment["status"] not in ("ACTIVE", "SAP_WARNING"):
        raise errors.invalid_state("owning enrollment must be ACTIVE or SAP_WARNING")

    # Priority 14: clock-hour gate.
    esvc.recompute_hours(enrollment)
    if enrollment["actual_hours"] < row["period_hours"]:
        raise errors.period_hours_not_earned()
    # Priority 15: time gate.
    if _whole_weeks_elapsed(enrollment["enrolled_on_iso"]) < row["period_weeks"]:
        raise errors.period_weeks_not_elapsed()

    # Priority 18: OCC against live enrollment version (checked last).
    if expected != enrollment["version"]:
        raise errors.stale_enrollment_version()

    # Side effects: net computed, credited to ledger, enrollment version bumped.
    row["status"] = "POSTED"
    row["net_amount_cents"] = calc.disbursement_net(
        row["gross_amount_cents"], row["origination_fee_cents"]
    )
    db.touch(row)
    esvc.recompute_ledger(enrollment)
    db.touch(enrollment)
    return response.ok(row)


@bp.post("/school/disbursements/<did>/return")
@require("FinancialAidOfficer")
def return_disbursement(did):
    row = lookups.path(db.disbursements, did)
    # Direct return endpoint applies only to POSTED disbursements.
    if row["status"] != "POSTED":
        raise errors.invalid_state()
    enrollment = db.enrollments[row["enrollment_id"]]
    row["status"] = "RETURNED"
    db.touch(row)
    # Reverse the ledger credit (full recompute over POSTED set).
    esvc.recompute_ledger(enrollment)
    db.touch(enrollment)
    return response.ok(row)
