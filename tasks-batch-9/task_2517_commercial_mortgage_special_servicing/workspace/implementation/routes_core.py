"""Trusts, loans, servicing transfer events, the computed read and the clock."""
from flask import Blueprint, request

from calc import ara_adjusted_advance_obligation, transfer_event_qualification
from datetimes import (add_days, iso, parse_dt, render_like, whole_days_between)
from db import base_row, db, touch
from errors import ApiError
from middleware import (ALL_STAFF, ASSET_MANAGER, BORROWER, CCR, COMMITTEE,
                        MASTER_SERVICER, PLATFORM_ADMIN, STAFF_PLUS_BORROWER,
                        STAFF_PLUS_CCR, TRUSTEE, authenticate, require_owner,
                        role, user_id)
from money import D, ZERO, q2, q6
from response import array_response, listing, object_response
from routing import (filter_rows, reject_system_only, require_target_role,
                     require_transition)
from services import (children, find, recompute_loan, recompute_trust,
                      refresh_loan_advances, reductions_of,
                      run_liquidation_waterfall, finalize_liquidation,
                      rows_of, sort_created, trust_of_loan)
from validate import (body, forbid, get_bool, get_datetime, get_enum, get_int,
                      get_number, get_string, present)

bp = Blueprint("core", __name__)

TRANSFER_EVENT_CODES = (
    "MONETARY_DEFAULT_60D",
    "IMMINENT_DEFAULT",
    "MATURITY_DEFAULT",
    "BANKRUPTCY",
    "RECEIVERSHIP",
    "OTHER_MATERIAL_DEFAULT",
)
FEE_BASIS_CONVENTIONS = ("STATED_PRINCIPAL", "ARA_ADJUSTED")

SERVICING_TRANSITIONS = {
    "MASTER_SERVICING": ("SPECIAL_SERVICING",),
    "SPECIAL_SERVICING": ("IN_WORKOUT",),
    "IN_WORKOUT": ("CORRECTED", "REO", "LIQUIDATED"),
    "CORRECTED": ("MASTER_SERVICING",),
    "REO": ("LIQUIDATED", "WRITTEN_OFF"),
    "LIQUIDATED": (),
    "WRITTEN_OFF": (),
}
SERVICING_TARGET_ROLES = {
    "SPECIAL_SERVICING": (MASTER_SERVICER,),
    "CORRECTED": (COMMITTEE,),
    "MASTER_SERVICING": (ASSET_MANAGER,),
    "LIQUIDATED": (ASSET_MANAGER,),
}
SERVICING_STATUSES = tuple(SERVICING_TRANSITIONS)

PAYMENT_TRANSITIONS = {
    "CURRENT": ("DELINQUENT_30", "CURRENT", "MATURED_UNPAID", "PAID_OFF"),
    "DELINQUENT_30": ("DELINQUENT_60", "CURRENT", "MATURED_UNPAID", "PAID_OFF"),
    "DELINQUENT_60": ("DELINQUENT_90_PLUS", "CURRENT", "MATURED_UNPAID", "PAID_OFF"),
    "DELINQUENT_90_PLUS": ("CURRENT", "MATURED_UNPAID", "PAID_OFF"),
    "MATURED_UNPAID": ("CURRENT", "PAID_OFF"),
    "PAID_OFF": (),
}
PAYMENT_STATUSES = tuple(PAYMENT_TRANSITIONS)


# ------------------------------------------------------------------- Trust
def _new_trust(data):
    row = base_row()
    original = get_number(data, "original_controlling_class_balance_usd",
                          exclusive_minimum=0)
    row.update(
        {
            "deal_name": get_string(data, "deal_name"),
            "closing_date": get_datetime(data, "closing_date")[0],
            "original_controlling_class_balance_usd": q2(original),
            "total_ara_usd": ZERO,
            "realized_loss_usd": ZERO,
            "controlling_class_notional_usd": q2(original),
            "control_status": "CONTROLLING",
            "total_advances_outstanding_usd": ZERO,
            "excess_liquidation_proceeds_usd": ZERO,
            "loans_in_special_servicing_count": 0,
            "special_servicing_fee_annual_pct": get_number(
                data, "special_servicing_fee_annual_pct", required=False,
                default=D("0.25"), minimum=0),
            "workout_fee_rate_pct": get_number(
                data, "workout_fee_rate_pct", required=False, default=D("1.0"),
                minimum=0),
            "liquidation_fee_rate_pct": get_number(
                data, "liquidation_fee_rate_pct", required=False, default=D("1.0"),
                minimum=0),
            "advance_interest_rate_pct": get_number(
                data, "advance_interest_rate_pct", required=False, default=D("5.0"),
                minimum=0),
            "fee_basis_convention": get_enum(
                data, "fee_basis_convention", FEE_BASIS_CONVENTIONS, required=False)
            or "STATED_PRINCIPAL",
            "consultation_response_business_days": get_int(
                data, "consultation_response_business_days", required=False,
                default=10, minimum=1),
        }
    )
    row["_closing_date_dt"] = parse_dt(row["closing_date"])
    return row


@bp.route("/trusts", methods=["POST"])
def create_trust():
    authenticate((PLATFORM_ADMIN,))
    row = _new_trust(body())
    recompute_trust(row, cascade=False)
    db.trusts[row["id"]] = row
    return object_response(row, 201)


@bp.route("/trusts/<trust_id>", methods=["GET"])
def get_trust(trust_id):
    authenticate(STAFF_PLUS_CCR)
    row = find("trusts", trust_id, "ERR_TRUST_NOT_FOUND")
    require_owner(row["id"])
    return object_response(row)


@bp.route("/trusts", methods=["GET"])
def list_trusts():
    authenticate(ALL_STAFF)
    rows = sorted(rows_of("trusts"), key=lambda r: (r["created_at"], r["_seq"]),
                  reverse=True)
    return listing(rows)


# -------------------------------------------------------------------- Loan
@bp.route("/loans", methods=["POST"])
def create_loan():
    authenticate((MASTER_SERVICER, PLATFORM_ADMIN))
    data = body()
    trust_id = get_string(data, "trust_id")
    loan_number = get_string(data, "loan_number")
    original = get_number(data, "original_balance_usd", exclusive_minimum=0)
    cpb = get_number(data, "current_principal_balance_usd", minimum=0)
    note_rate = get_number(data, "note_rate_pct")
    mds = get_number(data, "monthly_debt_service_usd")
    maturity_raw, maturity_dt = get_datetime(data, "maturity_date")
    sec_value = get_number(data, "securitization_value_usd")
    aui = get_number(data, "accrued_unpaid_interest_usd", required=False,
                     default=ZERO, minimum=0)

    trust = find("trusts", trust_id, "ERR_TRUST_NOT_FOUND")
    for other in rows_of("loans"):
        if other["trust_id"] == trust["id"] and other["loan_number"] == loan_number:
            raise ApiError("ERR_DUPLICATE_LOAN_NUMBER")

    row = base_row()
    row.update(
        {
            "trust_id": trust["id"],
            "loan_number": loan_number,
            "original_balance_usd": q2(original),
            "current_principal_balance_usd": q2(cpb),
            "accrued_unpaid_interest_usd": q2(aui),
            "note_rate_pct": q6(note_rate),
            "monthly_debt_service_usd": q2(mds),
            "maturity_date": maturity_raw,
            "securitization_value_usd": q2(sec_value),
            "servicing_status": "MASTER_SERVICING",
            "payment_status": "CURRENT",
            "consecutive_timely_payments": 0,
            "transferred_to_special_on": None,
            "transfer_event_code": None,
            "asset_business_plan_due_date": None,
            "last_appraised_value_usd": None,
            "ara_amount_usd": ZERO,
            "required_monthly_pi_advance_usd": q2(mds),
            "advances_outstanding_usd": ZERO,
            "fees_payable_usd": ZERO,
            "realized_loss_usd": ZERO,
            "active_workout_plan_id": None,
            "correction_source_plan_id": None,
            "appraisal_required": False,
            "is_modified": False,
            "_maturity_dt": maturity_dt,
            "_due_dt": None,
        }
    )
    row["required_monthly_pi_advance_usd"] = ara_adjusted_advance_obligation(
        mds, cpb, ZERO)
    db.loans[row["id"]] = row
    return object_response(row, 201)


@bp.route("/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    authenticate(STAFF_PLUS_BORROWER)
    row = find("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    require_owner(row["id"])
    return object_response(row)


@bp.route("/loans", methods=["GET"])
def list_loans():
    authenticate(ALL_STAFF)
    rows = filter_rows(
        sort_created(rows_of("loans")),
        (
            ("trust_id", "trust_id"),
            ("servicing_status", "servicing_status"),
            ("payment_status", "payment_status"),
            ("active_workout_plan_id", "active_workout_plan_id"),
            ("correction_source_plan_id", "correction_source_plan_id"),
        ),
    )
    return listing(rows)


# ------------------------------------------ ServicingTransferEvent (append-only)
def _record_transfer_event(loan, event_code, occurred_raw, occurred_dt,
                           evidence_note, days_delinquent, imminent, recorded_by):
    row = base_row(with_common_fields=False)
    triggers = transfer_event_qualification(
        event_code, days_delinquent, imminent, occurred_dt, loan.get("_maturity_dt"))
    row.update(
        {
            "loan_id": loan["id"],
            "event_code": event_code,
            "occurred_on": occurred_raw,
            "evidence_note": evidence_note,
            "days_delinquent_at_event": int(days_delinquent or 0),
            "imminent_default_certified": bool(imminent),
            "triggers_transfer": bool(triggers),
            "consumed_by_transfer": False,
            "recorded_by_user_id": recorded_by,
            "_occurred_on_dt": occurred_dt,
        }
    )
    db.transfer_events[row["id"]] = row
    return row


@bp.route("/transfer-events", methods=["POST"])
def create_transfer_event():
    authenticate((MASTER_SERVICER, ASSET_MANAGER))
    data = body()
    loan_id = get_string(data, "loan_id")
    event_code = get_enum(data, "event_code", TRANSFER_EVENT_CODES)
    occurred_raw, occurred_dt = get_datetime(data, "occurred_on")
    evidence_note = get_string(data, "evidence_note")
    days = get_int(data, "days_delinquent_at_event", required=False, default=0,
                   minimum=0)
    imminent = get_bool(data, "imminent_default_certified", required=False,
                        default=False)
    loan = find("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    row = _record_transfer_event(loan, event_code, occurred_raw, occurred_dt,
                                 evidence_note, days, imminent, user_id())
    return object_response(row, 201)


@bp.route("/transfer-events/<event_id>", methods=["GET"])
def get_transfer_event(event_id):
    authenticate(ALL_STAFF)
    return object_response(find("transfer_events", event_id,
                                "ERR_TRANSFER_EVENT_NOT_FOUND"))


@bp.route("/loans/<loan_id>/transfer-events", methods=["GET"])
def list_loan_transfer_events(loan_id):
    authenticate(ALL_STAFF)
    loan = find("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    rows = [r for r in rows_of("transfer_events") if r["loan_id"] == loan["id"]]
    rows.sort(key=lambda r: (r["_occurred_on_dt"], r["created_at"], r["_seq"]))
    rows = filter_rows(rows, (("event_code", "event_code"),))
    return listing(rows)


@bp.route("/loans/<loan_id>/asset-business-plan", methods=["GET"])
def get_asset_business_plan(loan_id):
    authenticate(ALL_STAFF)
    loan = find("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    if loan.get("transferred_to_special_on") is None:
        payload = dict.fromkeys(
            ("loan_id", "transferred_to_special_on", "asset_business_plan_due_date",
             "days_until_due", "is_overdue", "active_workout_plan_id",
             "recommended_alternative_type", "ara_amount_usd",
             "required_monthly_pi_advance_usd"),
            None,
        )
        return object_response(payload)

    now = db.now()
    due_dt = loan.get("_due_dt")
    alternative_type = None
    plan = db.workout_plans.get(loan.get("active_workout_plan_id"))
    if plan is not None:
        alternative = db.workout_alternatives.get(plan.get("recommended_alternative_id"))
        if alternative is not None:
            alternative_type = alternative["alternative_type"]
    payload = {
        "loan_id": loan["id"],
        "transferred_to_special_on": loan["transferred_to_special_on"],
        "asset_business_plan_due_date": loan["asset_business_plan_due_date"],
        "days_until_due": whole_days_between(now, due_dt),
        "is_overdue": now > due_dt,
        "active_workout_plan_id": loan.get("active_workout_plan_id"),
        "recommended_alternative_type": alternative_type,
        "ara_amount_usd": loan["ara_amount_usd"],
        "required_monthly_pi_advance_usd": loan["required_monthly_pi_advance_usd"],
    }
    return object_response(payload)


# ------------------------------------------------------------- logical clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate((PLATFORM_ADMIN,))
    raw, parsed = get_datetime(body(), "current_utc")
    db.clock = parsed
    return object_response({"current_utc": iso(parsed)})


# ------------------------------------------------ Loan servicing dimension
def _selected_alternative_type(plan):
    if plan is None:
        return None
    alternative = db.workout_alternatives.get(plan.get("selected_alternative_id"))
    return alternative["alternative_type"] if alternative else None


def _require_executed_plan_type(loan, expected_type):
    plan = db.workout_plans.get(loan.get("active_workout_plan_id"))
    if plan is None or plan["status"] != "EXECUTED":
        raise ApiError("ERR_ALTERNATIVE_TYPE_MISMATCH")
    if _selected_alternative_type(plan) != expected_type:
        raise ApiError("ERR_ALTERNATIVE_TYPE_MISMATCH")
    return plan


@bp.route("/loans/<loan_id>/servicing-status", methods=["POST"])
def set_loan_servicing_status(loan_id):
    authenticate((MASTER_SERVICER, ASSET_MANAGER, COMMITTEE))
    loan = find("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    data = body()
    to_status = get_enum(data, "to_status", SERVICING_STATUSES)
    reject_system_only(to_status, SERVICING_TARGET_ROLES)
    get_string(data, "note", required=False)

    gross = expenses = None
    closing_raw = closing_dt = None
    if to_status == "LIQUIDATED":
        gross = get_number(data, "gross_proceeds_usd", minimum=0)
        expenses = get_number(data, "liquidation_expenses_usd", minimum=0)
        closing_raw, closing_dt = get_datetime(data, "closing_date")

    current = loan["servicing_status"]
    require_transition(current, to_status, SERVICING_TRANSITIONS)
    if to_status == "CORRECTED" and loan["payment_status"] != "CURRENT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    require_target_role(role(), to_status, SERVICING_TARGET_ROLES)

    trust = trust_of_loan(loan)

    if to_status == "SPECIAL_SERVICING":
        pool = [
            row
            for row in rows_of("transfer_events")
            if row["loan_id"] == loan["id"]
            and row["triggers_transfer"] is True
            and row["consumed_by_transfer"] is False
        ]
        if not pool:
            raise ApiError("ERR_NO_QUALIFYING_TRANSFER_EVENT")
        pool.sort(key=lambda r: (r["_occurred_on_dt"], r["created_at"], r["_seq"]))
        event = pool[0]
        event["consumed_by_transfer"] = True
        now = db.now()
        due = add_days(now, 60)
        loan["transfer_event_code"] = event["event_code"]
        loan["transferred_to_special_on"] = iso(now)
        loan["asset_business_plan_due_date"] = iso(due)
        loan["_due_dt"] = due
        loan["servicing_status"] = to_status

    elif to_status == "CORRECTED":
        plan = _require_executed_plan_type(loan, "MODIFICATION")
        loan["correction_source_plan_id"] = plan["id"]
        loan["active_workout_plan_id"] = None
        for reduction in reductions_of(loan["id"]):
            if reduction["status"] == "EFFECTIVE":
                reduction["status"] = "REVERSED"
                reduction["reversal_reason"] = "loan corrected"
                reduction["advance_reduction_applies"] = False
                touch(reduction)
        loan["servicing_status"] = to_status

    elif to_status == "MASTER_SERVICING":
        if int(loan["consecutive_timely_payments"]) < 3:
            raise ApiError("ERR_INSUFFICIENT_TIMELY_PAYMENTS")
        loan["servicing_status"] = to_status

    elif to_status == "LIQUIDATED":
        _require_executed_plan_type(loan, "NOTE_SALE")
        from calc import liquidation_fee_amount
        if expenses <= 0:
            raise ApiError("ERR_LIQUIDATION_EXPENSE_REQUIRED")
        fee = liquidation_fee_amount(gross, trust["liquidation_fee_rate_pct"])
        if q2(expenses + fee) > q2(gross):
            raise ApiError("ERR_LIQUIDATION_EXPENSE_REQUIRED")
        refresh_loan_advances(loan)
        run_liquidation_waterfall(loan, trust, gross, expenses)
        loan["active_workout_plan_id"] = None
        finalize_liquidation(loan, trust)

    recompute_loan(loan)
    recompute_trust(trust)
    touch(loan)
    touch(trust)
    return object_response(loan)


# -------------------------------------------------- Loan payment dimension
@bp.route("/loans/<loan_id>/payment-status", methods=["POST"])
def set_loan_payment_status(loan_id):
    authenticate((MASTER_SERVICER,))
    loan = find("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    data = body()
    to_status = get_enum(data, "to_status", PAYMENT_STATUSES)
    as_of_raw, as_of_dt = get_datetime(data, "as_of_date")
    timely = get_bool(data, "timely_payment_recorded", required=False, default=False)

    current = loan["payment_status"]
    require_transition(current, to_status, PAYMENT_TRANSITIONS)
    if to_status == "MATURED_UNPAID":
        if as_of_dt < loan["_maturity_dt"]:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if D(loan["current_principal_balance_usd"]) <= 0:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if to_status == "PAID_OFF":
        if D(loan["current_principal_balance_usd"]) != 0 or \
                D(loan["accrued_unpaid_interest_usd"]) != 0:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if to_status == "CURRENT" and current == "CURRENT" and not timely:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if to_status == "CURRENT":
        if timely:
            loan["consecutive_timely_payments"] = int(
                loan["consecutive_timely_payments"]) + 1
        else:
            loan["consecutive_timely_payments"] = 0
    else:
        loan["consecutive_timely_payments"] = 0

    if to_status == "DELINQUENT_60":
        _record_transfer_event(
            loan, "MONETARY_DEFAULT_60D", as_of_raw, as_of_dt,
            "auto-recorded on 60-day monetary delinquency", 60, False, user_id())
    elif to_status == "DELINQUENT_90_PLUS":
        loan["appraisal_required"] = True
    elif to_status == "MATURED_UNPAID":
        _record_transfer_event(
            loan, "MATURITY_DEFAULT", as_of_raw, as_of_dt,
            "auto-recorded on maturity default", 0, False, user_id())

    loan["payment_status"] = to_status
    recompute_loan(loan)
    touch(loan)
    return object_response(loan)
