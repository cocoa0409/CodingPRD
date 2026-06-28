"""Withdrawal routes (PRD 3.6; §1.5)."""
from flask import Blueprint, request

import db
import errors
import helpers
import lookups
import response
from middleware import require
from services import calc, enrollment as esvc

bp = Blueprint("withdrawals", __name__)

WITHDRAWAL_TYPES = {"OFFICIAL", "UNOFFICIAL"}


@bp.post("/school/withdrawals")
@require("FinancialAidOfficer")
def create_withdrawal():
    data = helpers.body()
    helpers.require_fields(data, "enrollment_id", "withdrawal_type", "last_date_of_attendance_iso")
    enrollment_id = helpers.require_str(data, "enrollment_id")
    # Priority 4: body FK existence.
    enrollment = lookups.fk(db.enrollments, enrollment_id)
    withdrawal_type = helpers.require_enum(data, "withdrawal_type", WITHDRAWAL_TYPES)
    last_date = helpers.require_dt(data, "last_date_of_attendance_iso")

    program = db.programs[enrollment["program_id"]]
    # Ensure derived enrollment figures are current before the R2T4/refund snapshot.
    esvc.recompute_hours(enrollment)

    pct_completed = calc.pct_completed(
        enrollment["scheduled_hours_to_date"], program["total_clock_hours"]
    )
    total_posted_net = calc.posted_credits(enrollment, db)
    title_iv_return = calc.r2t4(pct_completed, total_posted_net)
    institutional_refund = calc.institutional_refund(
        program["tuition_cents"], program["admin_fee_cap_cents"],
        enrollment["actual_hours"], program["total_clock_hours"],
    )

    row = {
        "enrollment_id": enrollment_id,
        "withdrawal_type": withdrawal_type,
        "last_date_of_attendance_iso": db.iso(last_date),
        "pct_completed": pct_completed,
        "title_iv_return_cents": title_iv_return,
        "institutional_refund_cents": institutional_refund,
        "status": "CALCULATED",
    }
    db.stamp_new(row)
    db.withdrawals[row["id"]] = row
    return response.created(row)


@bp.get("/school/withdrawals/<wid>")
@require("Registrar", "FinancialAidOfficer")
def get_withdrawal(wid):
    row = lookups.path(db.withdrawals, wid)
    return response.ok(row)


@bp.get("/school/withdrawals")
@require("Registrar", "FinancialAidOfficer")
def list_withdrawals():
    rows = list(db.withdrawals.values())
    enrollment_id = request.args.get("enrollment_id")
    if enrollment_id:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)


@bp.post("/school/withdrawals/<wid>/finalize")
@require("FinancialAidOfficer")
def finalize_withdrawal(wid):
    row = lookups.path(db.withdrawals, wid)
    data = helpers.body()
    helpers.require_fields(data, "expected_enrollment_version")
    expected = helpers.require_int(data, "expected_enrollment_version")

    # Priority 7: withdrawal state precondition.
    if row["status"] != "CALCULATED":
        raise errors.invalid_state()
    enrollment = db.enrollments[row["enrollment_id"]]
    # Owning enrollment must be ACTIVE or SAP_WARNING.
    if enrollment["status"] not in ("ACTIVE", "SAP_WARNING"):
        raise errors.invalid_state("owning enrollment must be ACTIVE or SAP_WARNING")
    # Priority 18: OCC against live enrollment version (checked last).
    if expected != enrollment["version"]:
        raise errors.stale_enrollment_version()

    # Head of the depth-3 cascade.
    row["status"] = "FINALIZED"
    db.touch(row)

    # Enrollment -> WITHDRAWN.
    enrollment["status"] = "WITHDRAWN"

    # Cascade 1: every non-RETURNED disbursement -> RETURNED, each processed
    # through the ledger sync (PRD 3.6): "a disbursement that had been posted is
    # debited back out of total_credits_cents and the ledger_balance_cents
    # recomputed, while a never-posted scheduled disbursement returns with no
    # ledger impact." A POSTED disbursement therefore must also be returned here
    # so the recompute below excludes its net; a SCHEDULED one returns with no
    # ledger effect since it was never credited.
    for d in db.disbursements.values():
        if d["enrollment_id"] == enrollment["id"] and d["status"] in ("SCHEDULED", "POSTED"):
            d["status"] = "RETURNED"
            db.touch(d)

    # Cascade 2: every OPEN clinic ticket -> VOIDED, release station.
    for ct in db.clinic_tickets.values():
        if ct["enrollment_id"] == enrollment["id"] and ct["status"] == "OPEN":
            ct["status"] = "VOIDED"
            db.touch(ct)
            station = db.stations[ct["station_id"]]
            station["status"] = "AVAILABLE"
            db.touch(station)

    # Cascade 3: every RESERVED station assignment -> RELEASED, release station.
    for sa in db.station_assignments.values():
        if sa["enrollment_id"] == enrollment["id"] and sa["status"] == "RESERVED":
            sa["status"] = "RELEASED"
            db.touch(sa)
            station = db.stations[sa["station_id"]]
            station["status"] = "AVAILABLE"
            db.touch(station)

    # Ledger sync (full recompute over POSTED set) and bump enrollment version.
    esvc.recompute_ledger(enrollment)
    db.touch(enrollment)

    return response.ok(row)
