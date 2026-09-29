"""BlanketAgreement endpoints (PRD §3.6)."""

from flask import Blueprint, request

from db import DB, date_only
from errors import fail
from middleware import (
    body,
    is_role,
    req_datetime,
    req_enum,
    req_int,
    req_number,
    req_string,
    require_role,
    user_id,
)
from response import object_response, page_response, pagination
from routes.common import CADENCES, PREFIX, guard_licensee, require_state, set_dt
from services import calc
from services.cascade import bump_once
from services.derive import lookup, rows, serialize_blanket

bp = Blueprint("blanket", __name__)


@bp.post(PREFIX + "/blanket-agreements")
def create_blanket():
    data = body()
    licensee_id = req_string(data, "licensee_id")
    raw_start, start = req_datetime(data, "coverage_start")
    raw_end, end = req_datetime(data, "coverage_end")
    annual_fee = req_int(data, "annual_fee_cents", 1, None)
    cadence = req_enum(data, "reporting_cadence", CADENCES)
    cap = req_int(data, "usage_cap_minutes", 0, None)
    pool_share = req_number(data, "pool_share_pct", 0, 100)

    licensee = lookup("licensees", licensee_id)                      # 3
    require_role("LicensingAgent")                                   # 4

    for other in rows("blankets"):                                   # 20
        if other["licensee_id"] != licensee["id"]:
            continue
        if other["coverage_status"] not in ("DRAFT", "ACTIVE"):
            continue
        if start < other["_coverage_end_dt"] and other["_coverage_start_dt"] < end:
            fail("ERR_BLANKET_COVERAGE_OVERLAP", "coverage overlaps an existing agreement.")
    if end <= start:                                                 # 21
        fail("ERR_COVERAGE_DATES_INVALID", "coverage_end must be after coverage_start.")

    row = DB.new_row()
    row.update(
        {
            "licensee_id": licensee["id"],
            "annual_fee_cents": annual_fee,
            "reporting_cadence": cadence,
            "usage_cap_minutes": cap,
            "_pool_share_pct": calc.dp2(pool_share),
            "coverage_status": "DRAFT",
            "reporting_status": "COMPLIANT",
            "delinquent_since": None,
        }
    )
    set_dt(row, "coverage_start", raw_start, start)
    set_dt(row, "coverage_end", raw_end, end)
    DB.blankets[row["id"]] = row
    return object_response(serialize_blanket(row), 201)


@bp.get(PREFIX + "/blanket-agreements/<blanket_agreement_id>")
def get_blanket(blanket_agreement_id):
    row = lookup("blankets", blanket_agreement_id)
    require_role("LicensingAgent", "RightsManager", "RoyaltyAccountant", "Licensee")
    guard_licensee(row["licensee_id"])
    return object_response(serialize_blanket(row))


@bp.get(PREFIX + "/blanket-agreements")
def list_blankets():
    limit, offset = pagination(request.args)
    require_role("LicensingAgent", "RightsManager", "RoyaltyAccountant")
    result = rows("blankets")
    for name in ("licensee_id", "coverage_status", "reporting_status"):
        wanted = request.args.get(name)
        if wanted not in (None, ""):
            result = [r for r in result if r[name] == wanted]
    return page_response(result, limit, offset, serialize_blanket)


@bp.post(PREFIX + "/blanket-agreements/<blanket_agreement_id>/activate")
def activate(blanket_agreement_id):
    row = lookup("blankets", blanket_agreement_id)
    require_role("LicensingAgent")
    require_state(row, "coverage_status", ("DRAFT",), "blanket")
    if date_only(DB.now) >= row["_coverage_end_dt"]:                 # 49
        fail("ERR_COVERAGE_WINDOW_PASSED", "the coverage window has already passed.")
    row["coverage_status"] = "ACTIVE"
    bump_once(row)
    return object_response(serialize_blanket(row))


@bp.post(PREFIX + "/blanket-agreements/<blanket_agreement_id>/terminate")
def terminate(blanket_agreement_id):
    data = body()
    reason = req_string(data, "reason", allow_empty=False)
    row = lookup("blankets", blanket_agreement_id)
    require_role("LicensingAgent")
    require_state(row, "coverage_status", ("DRAFT", "ACTIVE"), "blanket")

    row["coverage_status"] = "TERMINATED"
    row["termination_reason"] = reason
    bump_once(row)
    for report in rows("usage_reports"):
        if report["blanket_agreement_id"] != row["id"]:
            continue
        if report["status"] != "DUE":
            continue
        report["status"] = "REJECTED"
        report["rejection_reason"] = "BLANKET_TERMINATED"
        bump_once(report)
    return object_response(serialize_blanket(row))
