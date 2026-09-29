"""Dealerships, covenant tests and remedy issuance."""

from flask import Blueprint

import db
import lookup
import middleware
import response
import validate
from errors import ApiError
from services import calc, ledger, serial, spec

bp = Blueprint("dealers", __name__)


@bp.route("/floorplan/dealers", methods=["POST"])
def create_dealer():
    middleware.require(middleware.CREDIT_OFFICER)
    data = validate.body()
    legal_name = validate.req_str(data, "legal_name", min_len=1, max_len=200)
    dba_name = validate.opt_str(data, "dba_name", min_len=0, max_len=200)
    franchise_type = validate.req_enum(data, "franchise_type", spec.FRANCHISE_TYPES)
    state_code = validate.req_str(data, "state_code", min_len=2, max_len=2)
    if not all("A" <= ch <= "Z" for ch in state_code):
        validate.bad("state_code must be exactly two uppercase letters.")
    record = db.insert(
        "dealers",
        {
            "legal_name": legal_name,
            "dba_name": dba_name,
            "franchise_type": franchise_type,
            "state_code": state_code,
            "status": "PROSPECT",
            "risk_score": 100,
            "risk_rating": "A",
            "audit_frequency_days": spec.AUDIT_FREQUENCY_BY_RATING["A"],
            "next_audit_due_at": None,
            "open_sot_incident_count": 0,
            "open_sot_exposure_cents": 0,
            "delinquent_unit_count": 0,
            "covenant_breach_count": 0,
            "last_covenant_result": None,
            "unapplied_credit_cents": 0,
            "audit_in_progress": False,
        },
    )
    return response.created(serial.dealer(record))


@bp.route("/floorplan/dealers/<dealer_id>", methods=["GET"])
def read_dealer(dealer_id):
    middleware.require(*middleware.ALL_ROLES)
    middleware.guard_dealer_id(dealer_id)
    record = lookup.dealer(dealer_id)
    return response.ok(serial.dealer(record))


@bp.route("/floorplan/dealers", methods=["GET"])
def list_dealers():
    middleware.require(
        middleware.CREDIT_OFFICER,
        middleware.CREDIT_RISK_MANAGER,
        middleware.AUDIT_MANAGER,
        middleware.SYSTEM_OPERATOR,
    )
    status = response.filter_value("status", spec.DEALER_STATUSES)
    rating = response.filter_value("risk_rating", spec.RISK_RATINGS)
    state_code = response.filter_value("state_code")
    franchise_type = response.filter_value("franchise_type", spec.FRANCHISE_TYPES)
    records = response.apply_filters(
        db.rows("dealers"),
        [
            ("status", status),
            ("risk_rating", rating),
            ("state_code", state_code),
            ("franchise_type", franchise_type),
        ],
    )
    return response.paginate(records, serial.dealer)


# --------------------------------------------------------------------------
# Covenant tests (3.8)
# --------------------------------------------------------------------------


@bp.route("/floorplan/dealers/<dealer_id>/covenant-tests", methods=["POST"])
def file_covenant_test(dealer_id):
    user_id, _ = middleware.require(middleware.CREDIT_RISK_MANAGER)
    dealer = lookup.dealer(dealer_id)
    data = validate.body()
    period_end = validate.req_instant(data, "period_end_date")
    tangible_net_worth = validate.req_int(data, "reported_tangible_net_worth_cents")
    ebitda = validate.req_int(data, "reported_ebitda_cents", minimum=0)
    interest = validate.req_int(data, "reported_interest_expense_cents", minimum=0)
    curtailment_paid = validate.req_int(data, "reported_curtailment_paid_cents", minimum=0)
    unrestricted_cash = validate.req_int(data, "reported_unrestricted_cash_cents", minimum=0)
    validate.req_int(data, "trailing_sot_incident_count", minimum=0)

    line = ledger.dealer_line(dealer["id"])
    credit_limit = int(line["credit_limit_cents"]) if line is not None else 0
    required_tnw = calc.required_tangible_net_worth(credit_limit)
    lender_standard, dealer_adjusted = calc.covenant_ratios(ebitda, interest, curtailment_paid)
    trailing = calc.trailing_sot_incident_count(dealer["id"], period_end)

    failures = []
    if tangible_net_worth < required_tnw:
        failures.append("CAPITAL")
    if lender_standard < db.Decimal(spec.DSCR_COVENANT_MIN):
        failures.append("CASH_FLOW")
    if trailing > 1:
        failures.append("OUT_OF_TRUST")
    result = "PASS" if not failures else "FAIL"

    record = db.insert(
        "covenant_tests",
        {
            "dealer_id": dealer["id"],
            "period_end_date": db.fmt_instant(period_end),
            "reported_tangible_net_worth_cents": tangible_net_worth,
            "reported_ebitda_cents": ebitda,
            "reported_interest_expense_cents": interest,
            "reported_curtailment_paid_cents": curtailment_paid,
            "reported_unrestricted_cash_cents": unrestricted_cash,
            "required_tangible_net_worth_cents": required_tnw,
            "dscr_lender_standard": lender_standard,
            "dscr_dealer_adjusted": dealer_adjusted,
            "trailing_sot_incident_count": trailing,
            "result": result,
            "failure_reason_codes": failures,
            "submitted_by_user_id": user_id,
        },
        versioned=False,
    )

    dealer["last_covenant_result"] = result
    if result == "FAIL":
        dealer["covenant_breach_count"] = int(dealer["covenant_breach_count"]) + 1
    ledger.recompute_risk(dealer)
    if int(dealer["covenant_breach_count"]) >= spec.COVENANT_BREACH_SUSPENSION_COUNT:
        ledger.suspend_line(line, dealer, "COVENANT_BREACH_LIMIT")
    db.touch(dealer)
    return response.created(serial.covenant_test(record))


@bp.route("/floorplan/dealers/<dealer_id>/covenant-tests", methods=["GET"])
def list_covenant_tests(dealer_id):
    middleware.require(
        middleware.CREDIT_OFFICER,
        middleware.CREDIT_RISK_MANAGER,
        middleware.DEALER_PRINCIPAL,
        middleware.SYSTEM_OPERATOR,
    )
    middleware.guard_dealer_id(dealer_id)
    dealer = lookup.dealer(dealer_id)
    result = response.filter_value("result", spec.COVENANT_RESULTS)
    records = response.apply_filters(
        [t for t in db.rows("covenant_tests") if t["dealer_id"] == dealer["id"]],
        [("result", result)],
    )
    # Explicit exception to the default ordering: newest period first.
    records = sorted(records, key=lambda t: (t["period_end_date"], t["_seq"]), reverse=True)
    return response.paginate(records, serial.covenant_test)


# --------------------------------------------------------------------------
# Remedy issuance (3.8)
# --------------------------------------------------------------------------


@bp.route("/floorplan/dealers/<dealer_id>/remedy-actions", methods=["POST"])
def issue_remedy(dealer_id):
    user_id, _ = middleware.require(middleware.CREDIT_RISK_MANAGER)
    dealer = lookup.dealer(dealer_id)
    data = validate.body()
    action_type = validate.req_enum(data, "action_type", spec.REMEDY_ACTION_TYPES)
    reason_code = validate.req_enum(data, "reason_code", spec.REMEDY_REASON_CODES)

    if action_type == "LINE_SUSPENSION":
        justified = (
            int(dealer["open_sot_incident_count"]) > 0 or int(dealer["covenant_breach_count"]) > 0
        )
    elif action_type == "REPOSSESSION":
        justified = bool(
            [u for u in ledger.dealer_units(dealer["id"]) if u["funding_status"] == "SOT_OPEN"]
        )
    else:
        justified = dealer["status"] == "DEFAULTED"
    if not justified:
        raise ApiError("ERR_REMEDY_NOT_JUSTIFIED")

    record = db.insert(
        "remedy_actions",
        {
            "dealer_id": dealer["id"],
            "action_type": action_type,
            "status": "ISSUED",
            "reason_code": reason_code,
            "justification_snapshot": {
                "open_sot_incident_count": int(dealer["open_sot_incident_count"]),
                "covenant_breach_count": int(dealer["covenant_breach_count"]),
                "delinquent_unit_count": int(dealer["delinquent_unit_count"]),
            },
            "issued_by_user_id": user_id,
            "executed_by_user_id": None,
            "executed_at": None,
            "units_repossessed_count": 0,
            "principal_charged_off_cents": 0,
        },
    )
    db.touch(dealer)
    return response.created(serial.remedy(record))


@bp.route("/floorplan/dealers/<dealer_id>/remedy-actions", methods=["GET"])
def list_dealer_remedies(dealer_id):
    middleware.require(
        middleware.CREDIT_OFFICER,
        middleware.CREDIT_RISK_MANAGER,
        middleware.SYSTEM_OPERATOR,
    )
    dealer = lookup.dealer(dealer_id)
    status = response.filter_value("status", spec.REMEDY_STATUSES)
    action_type = response.filter_value("action_type", spec.REMEDY_ACTION_TYPES)
    records = response.apply_filters(
        [r for r in db.rows("remedy_actions") if r["dealer_id"] == dealer["id"]],
        [("status", status), ("action_type", action_type)],
    )
    return response.paginate(records, serial.remedy)
