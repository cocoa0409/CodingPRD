"""UsageReport endpoints (PRD §3.6)."""

from flask import Blueprint, request

from db import DB
from errors import fail
from middleware import body, is_role, req_datetime, req_string, require_role, user_id
from response import object_response, page_response, pagination
from routes.common import PREFIX, guard_licensee, require_state
from services.cascade import (
    accept_usage_report,
    bump_once,
    cadence_periods,
    refresh_reporting_status,
)
from services.derive import lookup, report_sheets, rows, serialize_report

bp = Blueprint("usage_reports", __name__)


@bp.post(PREFIX + "/usage-reports")
def create_report():
    data = body()
    blanket_id = req_string(data, "blanket_agreement_id")
    raw_start, start = req_datetime(data, "period_start")
    raw_end, end = req_datetime(data, "period_end")

    blanket = lookup("blankets", blanket_id)                          # 3
    require_role("Licensee", "LicensingAgent")                       # 4
    guard_licensee(blanket["licensee_id"])                           # 5

    matched = None
    for p_start, p_end in cadence_periods(blanket):
        if p_start == start:
            matched = (p_start, p_end)
            break
    if matched is None or matched[1] != end:                          # 22
        fail("ERR_REPORT_PERIOD_INVALID", "the period is not a cadence period of this agreement.")

    for other in rows("usage_reports"):                               # 23
        if other["blanket_agreement_id"] != blanket["id"]:
            continue
        if other["_period_start_dt"] == start and other["status"] in (
            "DUE",
            "SUBMITTED",
            "ACCEPTED",
        ):
            fail("ERR_REPORT_PERIOD_DUPLICATE", "this period is already reported.")

    row = DB.new_row()
    row.update(
        {
            "blanket_agreement_id": blanket["id"],
            "period_start": raw_start,
            "_period_start_dt": start,
            "period_end": raw_end,
            "_period_end_dt": end,
            "status": "DUE",
            "reported_minutes_total": 0,
            "_reported_credits_total": None,
            "pool_cents": 0,
            "pool_admin_fee_cents": 0,
            "pool_distributable_cents": 0,
            "pool_allocations": [],
            "rejection_reason": None,
            "submitted_at": None,
            "accepted_at": None,
            "resubmission_count": 0,
        }
    )
    DB.usage_reports[row["id"]] = row
    return object_response(serialize_report(row), 201)


@bp.get(PREFIX + "/usage-reports/<usage_report_id>")
def get_report(usage_report_id):
    row = lookup("usage_reports", usage_report_id)
    require_role("LicensingAgent", "RightsManager", "RoyaltyAccountant", "Licensee")
    blanket = DB.blankets.get(row["blanket_agreement_id"])
    if blanket is not None:
        guard_licensee(blanket["licensee_id"])
    return object_response(serialize_report(row))


@bp.get(PREFIX + "/usage-reports")
def list_reports():
    limit, offset = pagination(request.args)
    require_role("LicensingAgent", "RightsManager", "RoyaltyAccountant", "Licensee")
    result = rows("usage_reports")
    wanted_blanket = request.args.get("blanket_agreement_id")
    if is_role("Licensee"):
        if wanted_blanket not in (None, ""):
            blanket = DB.blankets.get(wanted_blanket)
            if blanket is not None and blanket["licensee_id"] != user_id():
                fail("ERR_LICENSEE_MISMATCH", "that agreement belongs to another licensee.")
        mine = {
            b["id"] for b in DB.blankets.values() if b["licensee_id"] == user_id()
        }
        result = [r for r in result if r["blanket_agreement_id"] in mine]
    if wanted_blanket not in (None, ""):
        result = [r for r in result if r["blanket_agreement_id"] == wanted_blanket]
    status = request.args.get("status")
    if status not in (None, ""):
        result = [r for r in result if r["status"] == status]
    return page_response(result, limit, offset, serialize_report)


@bp.post(PREFIX + "/usage-reports/<usage_report_id>/submit")
def submit(usage_report_id):
    row = lookup("usage_reports", usage_report_id)
    require_role("Licensee")
    blanket = DB.blankets[row["blanket_agreement_id"]]
    guard_licensee(blanket["licensee_id"])                            # 5
    require_state(row, "status", ("DUE", "REJECTED"), "report")       # 10
    if not report_sheets(row["id"]):                                  # 40
        fail("ERR_REPORT_HAS_NO_CUE_SHEETS", "no cue sheet is attached to this report.")

    if row["status"] == "REJECTED":
        row["resubmission_count"] = row["resubmission_count"] + 1
    row["status"] = "SUBMITTED"
    row["submitted_at"] = DB.now_iso
    row["rejection_reason"] = None
    bump_once(row)
    refresh_reporting_status(blanket)
    return object_response(serialize_report(row))


@bp.post(PREFIX + "/usage-reports/<usage_report_id>/accept")
def accept(usage_report_id):
    row = lookup("usage_reports", usage_report_id)
    require_role("RightsManager")
    require_state(row, "status", ("SUBMITTED",), "report")             # 10
    blanket = DB.blankets[row["blanket_agreement_id"]]
    if blanket["coverage_status"] not in ("ACTIVE", "EXPIRED"):        # 19
        fail("ERR_BLANKET_NOT_ACTIVE", "the blanket agreement is not available.")
    accept_usage_report(row)
    return object_response(serialize_report(row))


@bp.post(PREFIX + "/usage-reports/<usage_report_id>/reject")
def reject(usage_report_id):
    data = body()
    reason = req_string(data, "reason", allow_empty=False)
    row = lookup("usage_reports", usage_report_id)
    require_role("RightsManager")
    require_state(row, "status", ("SUBMITTED",), "report")
    row["status"] = "REJECTED"
    row["rejection_reason"] = reason
    bump_once(row)
    return object_response(serialize_report(row))
