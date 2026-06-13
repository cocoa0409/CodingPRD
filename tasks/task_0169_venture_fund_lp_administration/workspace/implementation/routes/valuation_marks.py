"""ValuationMark routes (PRD §3.4)."""
from flask import Blueprint, request

import db
import errors
from middleware import authenticate, require_role
from response import success
from services import dates, lookup, serialize
import validation as V

bp = Blueprint("valuation_marks", __name__)

READ_OPS_ROLES = ["FundManager", "FundAdministrator", "ComplianceOfficer"]
METHODOLOGIES = ("LAST_ROUND", "DCF", "COMPARABLES", "WRITE_OFF")


@bp.route("/valuation-marks", methods=["POST"])
def create_mark():
    caller = authenticate()
    require_role(caller, ["FundAdministrator"])
    body = V.get_json_body()
    investment_id = V.require_string(body, "investment_id")
    as_of_date = V.require(body, "as_of_date")
    fair_value_cents = V.require_int(body, "fair_value_cents")
    methodology = V.require_enum(body, "methodology", METHODOLOGIES)

    with db.lock:
        inv = lookup.get_investment(investment_id)
        V.check_range(fair_value_cents, "fair_value_cents", lo=0)
        # as_of_date may not be after the moment of the request.
        parsed = dates.parse_dt(as_of_date)
        if parsed is None:
            errors.fail(errors.ERR_INVALID_PERIOD, "as_of_date is not a valid date.")
        if parsed > dates.now_utc():
            errors.fail(errors.ERR_INVALID_PERIOD, "as_of_date is in the future.")
        obj = db.stamp_new(
            {
                "investment_id": investment_id,
                "as_of_date": as_of_date,
                "fair_value_cents": fair_value_cents,
                "methodology": methodology,
                "status": "DRAFT",
            }
        )
        db.valuation_marks[obj["id"]] = obj
    return success(serialize.valuation_mark(obj), status=201)


@bp.route("/valuation-marks/<mid>", methods=["GET"])
def read_mark(mid):
    caller = authenticate()
    require_role(caller, READ_OPS_ROLES)
    obj = lookup.get_valuation_mark(mid)
    return success(serialize.valuation_mark(obj))


@bp.route("/valuation-marks", methods=["GET"])
def list_marks():
    caller = authenticate()
    require_role(caller, READ_OPS_ROLES)
    limit, offset = V.parse_pagination()
    investment_id = request.args.get("investment_id")
    status = request.args.get("status")
    items = list(db.valuation_marks.values())
    if investment_id is not None:
        items = [m for m in items if m["investment_id"] == investment_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    items = V.sort_by_created(items)
    page, meta = V.paginate(items, limit, offset)
    return success([serialize.valuation_mark(o) for o in page], pagination=meta)


@bp.route("/valuation-marks/<mid>/finalize", methods=["POST"])
def finalize_mark(mid):
    caller = authenticate()
    require_role(caller, ["FundAdministrator"])
    with db.lock:
        mark = lookup.get_valuation_mark(mid)
        if mark["status"] != "DRAFT":
            errors.fail(errors.ERR_INVALID_STATE, "Mark is not DRAFT.")
        inv = db.investments[mark["investment_id"]]
        # Permitted only while the owning Investment is ACTIVE.
        if inv["status"] != "ACTIVE":
            errors.fail(errors.ERR_INVALID_STATE, "Owning investment is not ACTIVE.")

        # as_of_date must be strictly later than the current FINAL mark's date.
        finals = [
            m
            for m in db.valuation_marks.values()
            if m["investment_id"] == inv["id"] and m["status"] == "FINAL"
        ]
        if finals:
            current_final = max(
                finals, key=lambda m: (m["as_of_date"], m["created_at"])
            )
            this_date = dates.parse_dt(mark["as_of_date"])
            cur_date = dates.parse_dt(current_final["as_of_date"])
            if this_date is None or cur_date is None or this_date <= cur_date:
                errors.fail(
                    errors.ERR_MARK_DATE_CONFLICT,
                    "Mark as_of_date not strictly later than current FINAL mark.",
                )

        mark["status"] = "FINAL"
        db.touch(mark)
        # Supersede any prior FINAL mark on the same investment.
        for m in finals:
            m["status"] = "SUPERSEDED"
            db.touch(m)
        # Investment.current_mark_cents recomputed (derived); bump investment.
        db.touch(inv)
        # WRITE_OFF cascade: Investment -> IMPAIRED, PortfolioCompany -> WRITTEN_OFF.
        if mark["methodology"] == "WRITE_OFF":
            inv["status"] = "IMPAIRED"
            db.touch(inv)
            company = db.portfolio_companies.get(inv["portfolio_company_id"])
            if company:
                company["status"] = "WRITTEN_OFF"
                db.touch(company)
    return success(serialize.valuation_mark(mark))
