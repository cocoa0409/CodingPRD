"""Tax remittances, amendments and the renewal calendar (PRD 3.9)."""
from flask import Blueprint, request

import clock
import response
import validate
from errors import ApiError
from middleware import require, own_winery
from routes import common
from services import calendar_svc, remit_svc, serialize
from store import db, base_row, touch

bp = Blueprint("remittances", __name__)

PERIOD_TYPES = ("MONTHLY", "ANNUAL")
BASES = ("ACCRUAL_BASIS", "DELIVERY_BASIS")
STATUSES = ("OPEN", "FILED", "REMITTED", "AMENDED")


@bp.route("/dtc/remittances", methods=["POST"])
def create_remittance():
    require("ComplianceOfficer")
    b = validate.body()
    winery_id = validate.field_str(b, "winery_id")
    state = validate.state_code(b, "state_code")
    period_type = validate.field_enum(b, "period_type", PERIOD_TYPES)
    start_raw, start = validate.field_date(b, "period_start")
    end_raw, end = validate.field_date(b, "period_end")
    basis = validate.field_enum(b, "basis", BASES)
    supersedes_id = validate.field_str(b, "supersedes_remittance_id", required=False)
    if start >= end:
        validate.bad("Field 'period_start' must be strictly before 'period_end'.")
    if end > clock.today():
        validate.bad("Field 'period_end' must fall on or before the current date.")

    winery = common.winery(winery_id)
    common.rule_for_state(state)
    target = common.remittance(supersedes_id) if supersedes_id else None

    collision = remit_svc.period_collision(
        winery["id"], state, period_type, basis, start, end,
        exempt_id=target["id"] if target is not None else None)
    if collision is not None:
        raise ApiError("ERR_REMITTANCE_PERIOD_OVERLAP",
                       "This period overlaps remittance %s." % collision["id"])

    if target is not None and target["status"] == "FILED":
        target["status"] = "AMENDED"
        touch(target)

    row = base_row()
    row.update({
        "winery_id": winery["id"],
        "supersedes_remittance_id": target["id"] if target is not None else None,
        "state_code": state,
        "period_type": period_type,
        "period_start": start_raw,
        "period_end": end_raw,
        "basis": basis,
        "status": "OPEN",
        "filed_at": None,
        "filed_by_user_id": None,
        "remitted_at": None,
        "remitted_by_user_id": None,
        "payment_reference": None,
    })
    row.update(remit_svc.compute_amounts(winery["id"], state, basis, start, end))
    db.remittances[row["id"]] = row
    return response.obj(serialize.remittance(row), 201)


@bp.route("/dtc/remittances/<rid>", methods=["GET"])
def read_remittance(rid):
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator")
    row = common.remittance(rid)
    own_winery(uid, role, row["winery_id"])
    return response.obj(serialize.remittance(row))


@bp.route("/dtc/remittances", methods=["GET"])
def list_remittances():
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator")
    winery_id = common.scope_winery(common.arg("winery_id"), uid, role)
    state = common.arg("state_code")
    period_type = validate.query_enum("period_type", PERIOD_TYPES)
    status = validate.query_enum("status", STATUSES)
    supersedes_id = common.arg("supersedes_remittance_id")
    rows = [r for r in db.remittances.values()
            if (winery_id is None or r["winery_id"] == winery_id)
            and (state is None or r["state_code"] == state)
            and (period_type is None or r["period_type"] == period_type)
            and (status is None or r["status"] == status)
            and (supersedes_id is None
                 or r["supersedes_remittance_id"] == supersedes_id)]
    return common.listing(rows, serialize.remittance)


@bp.route("/dtc/remittances/<rid>/file", methods=["POST"])
def file_remittance(rid):
    uid, _role = require("ComplianceOfficer")
    row = common.remittance(rid)
    if row["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an OPEN remittance may be filed; this one is %s."
                       % row["status"])
    rule = common.rule_for_state(row["state_code"])
    if row["shipment_count"] < 1 and not rule["zero_filing_required"]:
        raise ApiError("ERR_NOTHING_TO_REMIT",
                       "The period is empty and %s does not require zero filings."
                       % row["state_code"])
    row["status"] = "FILED"
    row["filed_at"] = clock.now_iso()
    row["filed_by_user_id"] = uid
    touch(row)
    return response.obj(serialize.remittance(row))


@bp.route("/dtc/remittances/<rid>/remit", methods=["POST"])
def remit_remittance(rid):
    uid, _role = require("ComplianceOfficer")
    row = common.remittance(rid)
    b = validate.body()
    reference = validate.field_str(b, "payment_reference")
    if row["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a FILED remittance may be remitted; this one is %s."
                       % row["status"])
    if row["filed_by_user_id"] is not None and uid == row["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The officer who filed this return may not record its payment.")
    row["status"] = "REMITTED"
    row["remitted_at"] = clock.now_iso()
    row["remitted_by_user_id"] = uid
    row["payment_reference"] = reference
    touch(row)
    return response.obj(serialize.remittance(row))


@bp.route("/dtc/renewal-calendar", methods=["GET"])
def renewal_calendar():
    uid, role = require("ComplianceOfficer", "WineryOperator")
    winery_id = common.arg("winery_id")
    if winery_id is None:
        validate.bad("Query parameter 'winery_id' is required.")
    own_winery(uid, role, winery_id)
    winery = common.winery(winery_id)
    horizon = 90
    raw = request.args.get("horizon_days")
    if raw is not None and raw != "":
        try:
            horizon = int(raw)
        except (TypeError, ValueError):
            validate.bad("Query parameter 'horizon_days' must be an integer.")
        if horizon < 1 or horizon > 365:
            validate.bad("Query parameter 'horizon_days' must be between 1 and 365.")
    return response.obj(calendar_svc.build(winery["id"], horizon))
