"""REO assets, fee accruals and CREFC distribution reports (PRD 3.8 / 3.9)."""
from flask import Blueprint

from calc import (liquidation_fee_amount, special_servicing_fee_accrual,
                  workout_fee_accrual)
from datetimes import add_years, iso, render_like
from db import base_row, db, touch
from errors import ApiError
from middleware import (ALL_STAFF, ASSET_MANAGER, CCR, COMMITTEE,
                        MASTER_SERVICER, STAFF_PLUS_CCR, TRUSTEE, authenticate,
                        require_owner, role, user_id)
from money import D, ZERO, q2, q6
from response import listing, object_response
from routing import filter_rows, require_target_role, require_transition
from services import (children, find, finalize_liquidation, new_fee_accrual,
                      recompute_loan, recompute_trust, refresh_loan_advances,
                      rows_of, run_liquidation_waterfall, sort_created,
                      trust_of_loan, write_off_loan)
from validate import (body, forbid, get_datetime, get_enum, get_int, get_number,
                      get_string, get_string_array, present)

bp = Blueprint("disposition", __name__)

ACQUISITION_TYPES = ("FORECLOSURE", "DEED_IN_LIEU")
REO_STATUSES = ("ACQUIRED", "STABILIZING", "MARKETED", "UNDER_CONTRACT",
                "SOLD", "WRITTEN_OFF")
REO_TRANSITIONS = {
    "ACQUIRED": ("STABILIZING", "MARKETED", "WRITTEN_OFF"),
    "STABILIZING": ("MARKETED", "WRITTEN_OFF"),
    "MARKETED": ("UNDER_CONTRACT", "WRITTEN_OFF"),
    "UNDER_CONTRACT": ("MARKETED", "SOLD"),
    "SOLD": (),
    "WRITTEN_OFF": (),
}
REO_TARGET_ROLES = {
    "STABILIZING": (ASSET_MANAGER, COMMITTEE),
    "MARKETED": (ASSET_MANAGER, COMMITTEE),
    "UNDER_CONTRACT": (ASSET_MANAGER, COMMITTEE),
    "SOLD": (COMMITTEE,),
    "WRITTEN_OFF": (COMMITTEE,),
}

FEE_TYPES = ("SPECIAL_SERVICING_FEE", "WORKOUT_FEE", "LIQUIDATION_FEE")
FEE_STATUSES = ("ACCRUED", "COLLECTED", "WAIVED")
FEE_TRANSITIONS = {
    "ACCRUED": ("COLLECTED", "WAIVED"),
    "COLLECTED": (),
    "WAIVED": (),
}
FEE_TARGET_ROLES = {
    "COLLECTED": (MASTER_SERVICER,),
    "WAIVED": (COMMITTEE,),
}

REPORT_TYPES = ("DELINQUENT_LOAN_STATUS", "REO_STATUS", "FINAL_ASSET_DISPOSITION")
REPORT_STATUSES = ("DRAFT", "CERTIFIED", "DISTRIBUTED", "VOID")
REPORT_TRANSITIONS = {
    "DRAFT": ("CERTIFIED", "VOID"),
    "CERTIFIED": ("DISTRIBUTED", "VOID"),
    "DISTRIBUTED": (),
    "VOID": (),
}
REPORT_TARGET_ROLES = {
    "CERTIFIED": (TRUSTEE,),
    "DISTRIBUTED": (TRUSTEE,),
    "VOID": (TRUSTEE,),
}
RECIPIENTS = ("TRUSTEE", "RATING_AGENCIES", "CERTIFICATE_HOLDERS",
              "CONTROLLING_CLASS_REPRESENTATIVE")


# ---------------------------------------------------------------- REOAsset
@bp.route("/reo-assets", methods=["POST"])
def create_reo_asset():
    authenticate((ASSET_MANAGER,))
    data = body()
    loan_id = get_string(data, "loan_id")
    plan_id = get_string(data, "source_workout_plan_id")
    acquisition_type = get_enum(data, "acquisition_type", ACQUISITION_TYPES)
    acquired_raw, acquired_dt = get_datetime(data, "acquired_on")
    noi = get_number(data, "initial_noi_annual_usd", minimum=0)

    loan = find("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    plan = find("workout_plans", plan_id, "ERR_WORKOUT_PLAN_NOT_FOUND")
    if plan["loan_id"] != loan["id"]:
        raise ApiError("ERR_SUBJECT_REFERENCE_MISMATCH")
    if loan["servicing_status"] != "IN_WORKOUT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if plan["status"] != "EXECUTED":
        raise ApiError("ERR_ALTERNATIVE_TYPE_MISMATCH")
    alternative = db.workout_alternatives.get(plan.get("selected_alternative_id"))
    if alternative is None or alternative["alternative_type"] != acquisition_type:
        raise ApiError("ERR_ALTERNATIVE_TYPE_MISMATCH")

    deadline = add_years(acquired_dt, 3)
    row = base_row()
    row.update(
        {
            "loan_id": loan["id"],
            "source_workout_plan_id": plan["id"],
            "acquisition_type": acquisition_type,
            "acquired_on": acquired_raw,
            "remic_disposition_deadline": render_like(deadline, acquired_raw),
            "status": "ACQUIRED",
            "initial_noi_annual_usd": q2(noi),
            "list_price_usd": None,
            "gross_sale_proceeds_usd": None,
            "liquidation_expenses_usd": None,
            "closing_date": None,
            "contract_fallthrough_count": 0,
            "_deadline_dt": deadline,
        }
    )
    db.reo_assets[row["id"]] = row

    loan["servicing_status"] = "REO"
    loan["active_workout_plan_id"] = None
    recompute_loan(loan)
    touch(loan)
    trust = trust_of_loan(loan)
    if trust is not None:
        recompute_trust(trust)
        touch(trust)
    return object_response(row, 201)


@bp.route("/reo-assets/<asset_id>", methods=["GET"])
def get_reo_asset(asset_id):
    authenticate(ALL_STAFF)
    return object_response(find("reo_assets", asset_id, "ERR_REO_ASSET_NOT_FOUND"))


@bp.route("/reo-assets", methods=["GET"])
def list_reo_assets():
    authenticate(ALL_STAFF)
    rows = sort_created(rows_of("reo_assets"))
    rows = filter_rows(rows, (("loan_id", "loan_id"),
                              ("source_workout_plan_id", "source_workout_plan_id"),
                              ("acquisition_type", "acquisition_type"),
                              ("status", "status")))
    return listing(rows)


@bp.route("/reo-assets/<asset_id>/status", methods=["POST"])
def set_reo_asset_status(asset_id):
    authenticate((ASSET_MANAGER, COMMITTEE))
    asset = find("reo_assets", asset_id, "ERR_REO_ASSET_NOT_FOUND")
    data = body()
    to_status = get_enum(data, "to_status", REO_STATUSES)

    list_price = None
    gross = expenses = None
    closing_raw = closing_dt = None
    if to_status == "MARKETED":
        list_price = get_number(data, "list_price_usd", minimum=0)
    elif to_status == "SOLD":
        gross = get_number(data, "gross_proceeds_usd", minimum=0)
        expenses = get_number(data, "liquidation_expenses_usd", minimum=0)
        closing_raw, closing_dt = get_datetime(data, "closing_date")

    current = asset["status"]
    require_transition(current, to_status, REO_TRANSITIONS)
    require_target_role(role(), to_status, REO_TARGET_ROLES)

    loan = db.loans.get(asset["loan_id"])
    trust = trust_of_loan(loan) if loan is not None else None

    if to_status == "SOLD":
        if closing_dt > asset["_deadline_dt"]:
            raise ApiError("ERR_REMIC_DEADLINE_EXCEEDED")
        if expenses <= 0:
            raise ApiError("ERR_LIQUIDATION_EXPENSE_REQUIRED")
        fee = liquidation_fee_amount(gross, trust["liquidation_fee_rate_pct"])
        if q2(expenses + fee) > q2(gross):
            raise ApiError("ERR_LIQUIDATION_EXPENSE_REQUIRED")

        asset["gross_sale_proceeds_usd"] = q2(gross)
        asset["liquidation_expenses_usd"] = q2(expenses)
        asset["closing_date"] = closing_raw
        refresh_loan_advances(loan)
        run_liquidation_waterfall(loan, trust, gross, expenses)
        finalize_liquidation(loan, trust)
        touch(loan)
        touch(trust)

    elif to_status == "MARKETED":
        asset["list_price_usd"] = q2(list_price)
        if current == "UNDER_CONTRACT":
            asset["contract_fallthrough_count"] = int(
                asset["contract_fallthrough_count"]) + 1

    elif to_status == "WRITTEN_OFF":
        recompute_loan(loan)
        write_off_loan(loan, trust)
        touch(loan)
        touch(trust)

    asset["status"] = to_status
    touch(asset)
    return object_response(asset)


# --------------------------------------------------------------- FeeAccrual
def _overlaps(start_a, end_a, start_b, end_b):
    """Closed-interval overlap: [start_a, end_a] against [start_b, end_b]."""
    return start_a <= end_b and start_b <= end_a


@bp.route("/fee-accruals", methods=["POST"])
def create_fee_accrual():
    authenticate((MASTER_SERVICER, ASSET_MANAGER))
    data = body()
    loan_id = get_string(data, "loan_id")
    fee_type = get_enum(data, "fee_type", FEE_TYPES)

    period_start_raw = period_end_raw = None
    period_start_dt = period_end_dt = None
    collection = None
    if fee_type == "SPECIAL_SERVICING_FEE":
        forbid(data, "collection_amount_usd",
               "a special servicing fee is accrued on a closed period.")
        period_start_raw, period_start_dt = get_datetime(data, "period_start")
        period_end_raw, period_end_dt = get_datetime(data, "period_end")
        if period_end_dt < period_start_dt:
            raise ApiError("ERR_INVALID_REQUEST")
    elif fee_type == "WORKOUT_FEE":
        forbid(data, "period_start", "a workout fee is accrued on a collection.")
        forbid(data, "period_end", "a workout fee is accrued on a collection.")
        collection = get_number(data, "collection_amount_usd", minimum=0)
    else:
        forbid(data, "period_start", "a liquidation fee is created by the waterfall.")
        forbid(data, "period_end", "a liquidation fee is created by the waterfall.")
        forbid(data, "collection_amount_usd",
               "a liquidation fee is created by the waterfall.")

    loan = find("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    trust = trust_of_loan(loan)
    siblings = children("fee_accruals", "loan_id", loan["id"])

    if fee_type == "SPECIAL_SERVICING_FEE":
        for other in siblings:
            if other["fee_type"] != fee_type or other["status"] == "WAIVED":
                continue
            other_start = other.get("_period_start_dt")
            other_end = other.get("_period_end_dt")
            if other_start is None or other_end is None:
                continue
            if _overlaps(period_start_dt, period_end_dt, other_start, other_end):
                raise ApiError("ERR_FEE_PERIOD_OVERLAP")

    conflicting = {"WORKOUT_FEE": "LIQUIDATION_FEE",
                   "LIQUIDATION_FEE": "WORKOUT_FEE"}.get(fee_type)
    if conflicting is not None:
        for other in siblings:
            if other["fee_type"] == conflicting and other["status"] != "WAIVED":
                raise ApiError("ERR_FEE_TYPE_CONFLICT")

    if fee_type == "LIQUIDATION_FEE":
        raise ApiError("ERR_INVALID_REQUEST")

    if fee_type == "WORKOUT_FEE":
        if loan["servicing_status"] != "MASTER_SERVICING" or \
                not loan.get("correction_source_plan_id"):
            raise ApiError("ERR_WORKOUT_FEE_NOT_ELIGIBLE")
        basis, rate, amount = workout_fee_accrual(
            collection, trust["workout_fee_rate_pct"])
    else:
        basis, rate, amount = special_servicing_fee_accrual(
            loan["current_principal_balance_usd"],
            loan["ara_amount_usd"],
            trust["special_servicing_fee_annual_pct"],
            trust["fee_basis_convention"],
        )

    row = new_fee_accrual(
        loan, fee_type, period_start_raw, period_end_raw, basis, rate, amount,
        user_id(), collection_amount=(q2(collection) if collection is not None else None),
    )
    row["_period_start_dt"] = period_start_dt
    row["_period_end_dt"] = period_end_dt

    recompute_loan(loan)
    touch(loan)
    return object_response(row, 201)


@bp.route("/fee-accruals/<accrual_id>", methods=["GET"])
def get_fee_accrual(accrual_id):
    authenticate(ALL_STAFF)
    return object_response(find("fee_accruals", accrual_id, "ERR_FEE_ACCRUAL_NOT_FOUND"))


@bp.route("/fee-accruals", methods=["GET"])
def list_fee_accruals():
    authenticate(ALL_STAFF)
    rows = sort_created(rows_of("fee_accruals"))
    rows = filter_rows(rows, (("loan_id", "loan_id"),
                              ("fee_type", "fee_type"),
                              ("status", "status")))
    return listing(rows)


@bp.route("/fee-accruals/<accrual_id>/status", methods=["POST"])
def set_fee_accrual_status(accrual_id):
    authenticate((MASTER_SERVICER, COMMITTEE))
    accrual = find("fee_accruals", accrual_id, "ERR_FEE_ACCRUAL_NOT_FOUND")
    data = body()
    to_status = get_enum(data, "to_status", FEE_STATUSES)
    waived_reason = None
    if to_status == "WAIVED":
        waived_reason = get_string(data, "waived_reason")

    require_transition(accrual["status"], to_status, FEE_TRANSITIONS)
    if to_status == "WAIVED" and user_id() == accrual["accrued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    require_target_role(role(), to_status, FEE_TARGET_ROLES)

    if to_status == "COLLECTED":
        accrual["collected_on"] = iso(db.now())
    else:
        accrual["waived_reason"] = waived_reason

    accrual["status"] = to_status
    touch(accrual)

    loan = db.loans.get(accrual["loan_id"])
    if loan is not None:
        recompute_loan(loan)
        touch(loan)
    return object_response(accrual)


# -------------------------------------------------------- DistributionReport
@bp.route("/distribution-reports", methods=["POST"])
def create_distribution_report():
    authenticate((ASSET_MANAGER, TRUSTEE))
    data = body()
    trust_id = get_string(data, "trust_id")
    report_type = get_enum(data, "report_type", REPORT_TYPES)
    period_end_raw, _period_end_dt = get_datetime(data, "period_end")
    expected_version = get_int(data, "expected_trust_version", minimum=1)

    trust = find("trusts", trust_id, "ERR_TRUST_NOT_FOUND")
    if int(expected_version) != int(trust["version"]):
        raise ApiError("ERR_STALE_TRUST_VERSION")

    row = base_row()
    row.update(
        {
            "trust_id": trust["id"],
            "report_type": report_type,
            "period_end": period_end_raw,
            "status": "DRAFT",
            "loans_in_special_count": int(trust["loans_in_special_servicing_count"]),
            "total_ara_snapshot_usd": q2(trust["total_ara_usd"]),
            "total_advances_outstanding_snapshot_usd": q2(
                trust["total_advances_outstanding_usd"]),
            "realized_loss_snapshot_usd": q2(trust["realized_loss_usd"]),
            "control_status_snapshot": trust["control_status"],
            "recipients": None,
            "certified_by_user_id": None,
            "distributed_at": None,
        }
    )
    db.distribution_reports[row["id"]] = row
    return object_response(row, 201)


@bp.route("/distribution-reports/<report_id>", methods=["GET"])
def get_distribution_report(report_id):
    authenticate(STAFF_PLUS_CCR)
    row = find("distribution_reports", report_id, "ERR_DISTRIBUTION_REPORT_NOT_FOUND")
    require_owner(row["trust_id"])
    return object_response(row)


@bp.route("/distribution-reports", methods=["GET"])
def list_distribution_reports():
    authenticate(STAFF_PLUS_CCR)
    rows = rows_of("distribution_reports")
    if role() == CCR:
        rows = [r for r in rows if r["trust_id"] == user_id()]
    rows = sort_created(rows)
    rows = filter_rows(rows, (("trust_id", "trust_id"),
                              ("report_type", "report_type"),
                              ("status", "status")))
    return listing(rows)


@bp.route("/distribution-reports/<report_id>/status", methods=["POST"])
def set_distribution_report_status(report_id):
    authenticate((TRUSTEE,))
    report = find("distribution_reports", report_id,
                  "ERR_DISTRIBUTION_REPORT_NOT_FOUND")
    data = body()
    to_status = get_enum(data, "to_status", REPORT_STATUSES)
    recipients = None
    if to_status == "DISTRIBUTED":
        recipients = get_string_array(data, "recipients", RECIPIENTS)

    require_transition(report["status"], to_status, REPORT_TRANSITIONS)
    require_target_role(role(), to_status, REPORT_TARGET_ROLES)
    if user_id() == "system":
        raise ApiError("ERR_ROLE_NOT_PERMITTED_FOR_STATUS")

    if to_status == "CERTIFIED":
        report["certified_by_user_id"] = user_id()
    elif to_status == "DISTRIBUTED":
        report["recipients"] = recipients
        report["distributed_at"] = iso(db.now())

    report["status"] = to_status
    touch(report)
    return object_response(report)
