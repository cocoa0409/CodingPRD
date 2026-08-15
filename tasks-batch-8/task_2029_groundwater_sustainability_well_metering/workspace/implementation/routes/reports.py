"""ExtractionReport endpoints."""
from flask import Blueprint, request

from db import store, new_id, stamp, touch
from errors import err
from middleware import ALL_ROLES, require_roles, body, paginate, sort_default, query_int
from response import ok, ok_list
from serializers import ser_report
from services import (compute_late_flag, compute_overdraft_af, overdraft_penalty_cents,
                      report_fee_cents, new_assessment)
from util import round3, to_decimal, dp_ok, is_int

bp = Blueprint("reports", __name__)

REPORT_STATUSES = ("SUBMITTED", "VERIFIED", "DISPUTED")


@bp.post("/extraction-reports")
def create_report():
    uid, _ = require_roles("WellOwner")
    b = body()
    wid = b.get("well_id")
    w = store.wells.get(wid) if isinstance(wid, str) else None
    # Ownership (priority 3) before shape (4) and existence (5).
    if w is not None and w["account_id"] != uid:
        raise err("ERR_OWNERSHIP_MISMATCH", "WellOwner may only report on wells of their own account")
    if not isinstance(wid, str) or not wid:
        raise err("ERR_INVALID_REQUEST", "well_id is required")
    wy = b.get("water_year")
    if not is_int(wy):
        raise err("ERR_INVALID_REQUEST", "water_year must be an integer")
    month = b.get("month")
    if not is_int(month) or not (1 <= month <= 12):
        raise err("ERR_INVALID_REQUEST", "month must be an integer between 1 and 12")
    amt = to_decimal(b.get("reported_af"))
    if amt is None or amt < 0 or not dp_ok(amt, 3):
        raise err("ERR_INVALID_REQUEST", "reported_af must be >= 0 with at most 3 decimal places")
    if w is None:
        raise err("ERR_WELL_NOT_FOUND", "No Well with the given id")
    acct = store.accounts[w["account_id"]]
    # Well ACTIVE (priority 8) before the well-type gate (priority 16).
    if w["status"] != "ACTIVE":
        raise err("ERR_WELL_NOT_ACTIVE", "Well must be ACTIVE to accept extraction reports")
    if w["well_type"] != "PRODUCTION":
        raise err("ERR_INVALID_WELL_TYPE", "Extraction reports apply only to PRODUCTION wells")
    dup = any(r["well_id"] == w["id"] and r["water_year"] == wy and r["month"] == month
              for r in store.reports.values())
    if dup:
        raise err("ERR_DUPLICATE_REPORT", "An ExtractionReport already exists for (well_id, water_year, month)")
    if wy != acct["current_water_year"]:
        raise err("ERR_REPORT_YEAR_MISMATCH", "report.water_year must equal the account's current_water_year")
    r = {
        "id": new_id(),
        "well_id": w["id"],
        "water_year": wy,
        "month": month,
        "reported_af": round3(amt),
        "late_flag": compute_late_flag(wy, month),
        "fee_cents": None,
        "amendment_count": 0,
        "status": "SUBMITTED",
    }
    stamp(r)
    store.reports[r["id"]] = r
    acct["pending_extraction_af"] = round3(acct["pending_extraction_af"] + r["reported_af"])
    acct["version"] += 1
    touch(acct)
    return ok(ser_report(r), status=201)


@bp.get("/extraction-reports")
def list_reports():
    require_roles(*ALL_ROLES)
    items = list(store.reports.values())
    wid = request.args.get("well_id")
    if wid is not None:
        items = [r for r in items if r["well_id"] == wid]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    wy = query_int("water_year")
    if wy is not None:
        items = [r for r in items if r["water_year"] == wy]
    items = sort_default(items)
    page, pg = paginate(items)
    return ok_list([ser_report(r) for r in page], pg)


@bp.get("/extraction-reports/<report_id>")
def get_report(report_id):
    require_roles(*ALL_ROLES)
    r = store.reports.get(report_id)
    if r is None:
        raise err("ERR_REPORT_NOT_FOUND", "No ExtractionReport with the given id")
    return ok(ser_report(r))


@bp.post("/extraction-reports/<report_id>/verify")
def verify_report(report_id):
    require_roles("WaterMaster")
    r = store.reports.get(report_id)
    if r is None:
        raise err("ERR_REPORT_NOT_FOUND", "No ExtractionReport with the given id")
    if r["status"] != "SUBMITTED":
        raise err("ERR_INVALID_REPORT_STATE", "verify requires status SUBMITTED")
    w = store.wells[r["well_id"]]
    acct = store.accounts[w["account_id"]]
    before = compute_overdraft_af(acct)
    amt = r["reported_af"]
    acct["pending_extraction_af"] = round3(acct["pending_extraction_af"] - amt)
    acct["extracted_af_ytd"] = round3(acct["extracted_af_ytd"] + amt)
    r["fee_cents"] = report_fee_cents(amt)
    r["status"] = "VERIFIED"
    r["version"] += 1
    touch(r)
    after = compute_overdraft_af(acct)
    if before <= 0 and after > 0:
        amount = overdraft_penalty_cents(acct, after)
        new_assessment(acct, "OVERDRAFT", r["water_year"], after, amount, "system")
        acct["penalty_balance_cents"] += amount
    acct["version"] += 1
    touch(acct)
    return ok(ser_report(r))


@bp.post("/extraction-reports/<report_id>/dispute")
def dispute_report(report_id):
    require_roles("WaterMaster")
    r = store.reports.get(report_id)
    if r is None:
        raise err("ERR_REPORT_NOT_FOUND", "No ExtractionReport with the given id")
    if r["status"] != "SUBMITTED":
        raise err("ERR_INVALID_REPORT_STATE", "dispute requires status SUBMITTED")
    w = store.wells[r["well_id"]]
    acct = store.accounts[w["account_id"]]
    acct["pending_extraction_af"] = round3(acct["pending_extraction_af"] - r["reported_af"])
    r["status"] = "DISPUTED"
    r["version"] += 1
    touch(r)
    acct["version"] += 1
    touch(acct)
    return ok(ser_report(r))


@bp.post("/extraction-reports/<report_id>/resubmit")
def resubmit_report(report_id):
    uid, _ = require_roles("WellOwner")
    r = store.reports.get(report_id)
    if r is not None:
        w = store.wells[r["well_id"]]
        if w["account_id"] != uid:
            raise err("ERR_OWNERSHIP_MISMATCH", "WellOwner may only resubmit their own reports")
    b = body()
    amt = to_decimal(b.get("reported_af"))
    if amt is None or amt < 0 or not dp_ok(amt, 3):
        raise err("ERR_INVALID_REQUEST", "reported_af must be >= 0 with at most 3 decimal places")
    if r is None:
        raise err("ERR_REPORT_NOT_FOUND", "No ExtractionReport with the given id")
    if r["status"] != "DISPUTED":
        raise err("ERR_INVALID_REPORT_STATE", "resubmit requires status DISPUTED")
    w = store.wells[r["well_id"]]
    acct = store.accounts[w["account_id"]]
    if r["water_year"] != acct["current_water_year"]:
        raise err("ERR_REPORT_YEAR_MISMATCH", "report.water_year must equal the account's current_water_year")
    r["reported_af"] = round3(amt)
    r["amendment_count"] += 1
    r["late_flag"] = compute_late_flag(r["water_year"], r["month"])
    r["status"] = "SUBMITTED"
    r["version"] += 1
    touch(r)
    acct["pending_extraction_af"] = round3(acct["pending_extraction_af"] + r["reported_af"])
    acct["version"] += 1
    touch(acct)
    return ok(ser_report(r))
