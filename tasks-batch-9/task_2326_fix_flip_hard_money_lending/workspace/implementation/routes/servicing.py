"""Loan reads, accrual, payments, extensions, exit monitoring, default and foreclosure."""

from datetime import timedelta

from flask import Blueprint, request as flask_request

import calc
import serialize as ser
import services as svc
from core import (
    ROLES, ROLE_BORROWER, ROLE_CREDIT_COMMITTEE, ROLE_LOAN_OFFICER,
    ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN,
    ApiError, authenticate, caller_id, caller_role, clock_date, conflict, db,
    f_date, f_enum, f_int, f_str, invalid, iso_instant, json_body, new_record,
    ok, ok_list, paginate, parse_datetime, q_enum, q_str, require_borrower_owner,
    touch,
)

bp = Blueprint("servicing", __name__)
clock_bp = Blueprint("clock", __name__)

PAYMENT_STATUSES = ("CURRENT", "DELINQUENT", "DEFAULT", "PAID_OFF", "CHARGED_OFF")
CONSTRUCTION_STATUSES = ("NOT_STARTED", "IN_PROGRESS", "COMPLETE",
                         "LENDER_COMPLETING", "LENDER_COMPLETE")
EXIT_STATUSES = ("NOT_LISTED", "LISTED", "UNDER_CONTRACT", "REFI_IN_PROCESS",
                 "EXITED", "FORECLOSED")
FORECLOSURE_STATUSES = ("NOTICE_FILED", "TAKEOVER_COMPLETE", "COMPLETION_FUNDED", "RESOLVED")
LISTING_TYPES = ("LISTED", "PRICE_REDUCED")
REFI_TYPES = ("REFI_APPLICATION", "REFI_APPRAISAL_COMPLETE", "REFI_COMMITMENT_ISSUED")


# ---------------------------------------------------------------------------
# Loan reads
# ---------------------------------------------------------------------------
@bp.get("/loans/<rec_id>")
def read_loan(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_CREDIT_COMMITTEE, ROLE_LOAN_SERVICER,
                  ROLE_BORROWER, ROLE_PLATFORM_ADMIN))
    loan = ser.find_loan(rec_id)
    require_borrower_owner(loan["borrower_id"])
    return ok(ser.loan_out(loan))


@bp.get("/loans")
def list_loans():
    authenticate((ROLE_LOAN_OFFICER, ROLE_CREDIT_COMMITTEE, ROLE_LOAN_SERVICER,
                  ROLE_BORROWER, ROLE_PLATFORM_ADMIN))
    application_id = q_str("application_id")
    borrower_id = q_str("borrower_id")
    payment_status = q_enum("payment_status", PAYMENT_STATUSES)
    construction_status = q_enum("construction_status", CONSTRUCTION_STATUSES)
    exit_status = q_enum("exit_status", EXIT_STATUSES)
    if borrower_id is not None:
        require_borrower_owner(borrower_id)
    rows = list(db.loans.values())
    if caller_role() == ROLE_BORROWER:
        rows = [l for l in rows if l["borrower_id"] == caller_id()]
    if application_id is not None:
        rows = [l for l in rows if l["application_id"] == application_id]
    if borrower_id is not None:
        rows = [l for l in rows if l["borrower_id"] == borrower_id]
    if payment_status is not None:
        rows = [l for l in rows if l["payment_status"] == payment_status]
    if construction_status is not None:
        rows = [l for l in rows if l["construction_status"] == construction_status]
    if exit_status is not None:
        rows = [l for l in rows if l["exit_status"] == exit_status]
    items, meta = paginate(rows, ser.loan_out)
    return ok_list(items, meta)


# ---------------------------------------------------------------------------
# Interest accrual
# ---------------------------------------------------------------------------
@bp.post("/loans/<rec_id>/interest-accruals")
def accrue_interest(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    period_start = f_date(body, "period_start")
    period_end = f_date(body, "period_end")
    if period_end < period_start:
        raise invalid("period_end may not precede period_start.")
    loan = ser.find_loan(rec_id)
    svc.require_loan_writable(loan)

    for existing in ser.loan_accrual_periods(loan["id"]):
        if period_start <= existing["period_end"] and existing["period_start"] <= period_end:
            raise conflict("ERR_ACCRUAL_PERIOD_OVERLAP",
                           "The requested period overlaps an existing accrual period.")

    if loan["last_accrual_through"] is None:
        expected_start = loan["closing_date"]
    else:
        expected_start = loan["last_accrual_through"] + timedelta(days=1)
    if period_start != expected_start:
        raise conflict("ERR_ACCRUAL_PERIOD_GAP",
                       "period_start must continue directly from the last accrued day.")

    if period_end > clock_date():
        raise conflict("ERR_ACCRUAL_BEYOND_CLOCK",
                       "period_end may not be later than the current logical date.")

    day_count, note_days, default_days = calc.rate_day_split(
        period_start, period_end, loan["default_effective_date"])
    principal_snapshot = loan["funded_principal_cents"]
    note_interest = calc.rate_interest(principal_snapshot, loan["note_rate_bps"], note_days)
    default_interest = calc.rate_interest(principal_snapshot, loan["default_rate_bps"], default_days)
    accrued = note_interest + default_interest
    swept = min(accrued, loan["interest_reserve_balance_cents"])
    unpaid = accrued - swept

    period = new_record(full=False)
    period.update({
        "loan_id": loan["id"],
        "period_start": period_start,
        "period_end": period_end,
        "day_count": day_count,
        "note_rate_days": note_days,
        "default_rate_days": default_days,
        "principal_snapshot_cents": principal_snapshot,
        "note_rate_interest_cents": note_interest,
        "default_rate_interest_cents": default_interest,
        "interest_accrued_cents": accrued,
        "swept_from_reserve_cents": swept,
        "unpaid_added_cents": unpaid,
    })
    db.accrual_periods[period["id"]] = period

    loan["interest_reserve_balance_cents"] -= swept
    loan["funded_principal_cents"] += swept
    loan["accrued_interest_unpaid_cents"] += unpaid
    loan["last_accrual_through"] = period_end
    if unpaid > 0 and loan["payment_status"] == "CURRENT":
        loan["payment_status"] = "DELINQUENT"
        loan["delinquent_since"] = period_end
    touch(loan)

    if swept > 0:
        svc.write_ledger(loan, "RESERVE_SWEEP", swept, period_end,
                         "Interest reserve sweep", period["id"])
    return ok(ser.accrual_period_out(period), 201)


@bp.get("/loans/<rec_id>/interest-periods")
def list_interest_periods(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_LOAN_SERVICER, ROLE_BORROWER, ROLE_PLATFORM_ADMIN))
    loan = ser.find_loan(rec_id)
    require_borrower_owner(loan["borrower_id"])
    items, meta = paginate(ser.loan_accrual_periods(loan["id"]), ser.accrual_period_out)
    return ok_list(items, meta)


@bp.get("/loans/<rec_id>/ledger-entries")
def list_ledger_entries(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_LOAN_SERVICER, ROLE_BORROWER, ROLE_PLATFORM_ADMIN))
    entry_type = q_enum("entry_type", calc.LEDGER_ENTRY_TYPES)
    loan = ser.find_loan(rec_id)
    require_borrower_owner(loan["borrower_id"])
    rows = ser.loan_ledger_entries(loan["id"])
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    items, meta = paginate(rows, ser.ledger_entry_out)
    return ok_list(items, meta)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
@bp.post("/loans/<rec_id>/payments")
def apply_payment(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_BORROWER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    amount_cents = f_int(body, "amount_cents", minimum=1)
    payment_date = f_date(body, "payment_date")
    intent = f_enum(body, "intent", ("REGULAR", "PAYOFF"))
    loan = ser.find_loan(rec_id)
    require_borrower_owner(loan["borrower_id"])
    svc.require_loan_writable(loan)

    if intent == "PAYOFF" and loan["payment_status"] == "DEFAULT":
        for case in ser.loan_foreclosure_cases(loan["id"]):
            if case["status"] == "RESOLVED":
                raise conflict("ERR_LOAN_NOT_SERVICEABLE",
                               "A resolved foreclosure case bars a reinstatement payoff.")

    if intent == "REGULAR":
        remaining = amount_cents
        fee_paid = min(remaining, loan["fee_balance_cents"])
        remaining -= fee_paid
        interest_paid = min(remaining, loan["accrued_interest_unpaid_cents"])
        remaining -= interest_paid
        principal_paid = min(remaining, loan["funded_principal_cents"])
        remaining -= principal_paid
        if remaining > 0:
            raise conflict("ERR_PAYMENT_EXCEEDS_BALANCE",
                           "The payment exceeds the borrower's total obligation.")
        loan["fee_balance_cents"] -= fee_paid
        loan["accrued_interest_unpaid_cents"] -= interest_paid
        loan["funded_principal_cents"] -= principal_paid
        loan["repaid_principal_cents"] += principal_paid
        if (loan["payment_status"] == "DELINQUENT"
                and loan["fee_balance_cents"] == 0
                and loan["accrued_interest_unpaid_cents"] == 0):
            loan["payment_status"] = "CURRENT"
            loan["delinquent_since"] = None
        touch(loan)
        svc.write_ledger(loan, "BORROWER_PAYMENT", amount_cents, payment_date,
                         "Borrower payment", loan["id"])
        return ok(ser.loan_out(loan))

    quote = calc.payoff_quote(loan, payment_date)
    if amount_cents < quote:
        raise conflict("ERR_PAYOFF_SHORT",
                       "The payment is below the payoff quote as of payment_date.")

    svc.settle_principal_and_revenue(loan)
    loan["decommitted_holdback_cents"] += (loan["interest_reserve_balance_cents"]
                                           + loan["undisbursed_holdback_cents"])
    loan["interest_reserve_balance_cents"] = 0
    loan["undisbursed_holdback_cents"] = 0
    loan["payment_status"] = "PAID_OFF"
    loan["delinquent_since"] = None
    svc.set_exit_status(loan, "EXITED")
    touch(loan)
    svc.move_property(loan, "SOLD", ("BORROWER_OWNED",))
    svc.write_ledger(loan, "PAYOFF", amount_cents, payment_date, "Loan payoff", loan["id"])
    return ok(ser.loan_out(loan))


# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------
@bp.post("/loans/<rec_id>/extensions")
def grant_extension(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    months = f_int(body, "months", minimum=1)
    loan = ser.find_loan(rec_id)
    svc.require_loan_writable(loan)
    svc.require_serviceable(loan)

    if loan["extension_count"] >= calc.MAX_EXTENSIONS:
        raise conflict("ERR_EXTENSION_LIMIT_REACHED",
                       "This loan has already been extended the maximum number of times.")
    if calc.exit_watch_flag(loan):
        raise conflict("ERR_EXTENSION_BLOCKED_BY_EXIT_WATCH",
                       "The listing must be repriced before another extension is granted.")

    fee = calc.extension_fee(loan["funded_principal_cents"], months)
    loan["fee_balance_cents"] += fee
    loan["note_rate_bps"] += calc.EXTENSION_RATE_STEP_BPS
    loan["default_rate_bps"] = loan["note_rate_bps"] + calc.DEFAULT_RATE_SPREAD_BPS
    loan["extension_count"] += 1
    loan["extension_months_total"] += months
    loan["maturity_date"] = calc.maturity_date_for(loan)
    touch(loan)
    svc.write_ledger(loan, "EXTENSION_FEE", fee, clock_date(), "Extension fee", loan["id"])
    return ok(ser.loan_out(loan))


# ---------------------------------------------------------------------------
# Exit milestones
# ---------------------------------------------------------------------------
@bp.post("/loans/<rec_id>/exit-milestones")
def create_exit_milestone(rec_id):
    authenticate((ROLE_BORROWER, ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    milestone_type = f_enum(body, "milestone_type", calc.MILESTONE_TYPES)
    effective_date = f_date(body, "effective_date")
    listing_price_cents = f_int(body, "listing_price_cents", required=False, minimum=1)
    lender_name = f_str(body, "lender_name", required=False)
    note = f_str(body, "note", required=False)
    if milestone_type in LISTING_TYPES and listing_price_cents is None:
        raise invalid("listing_price_cents is required for a %s milestone." % milestone_type)
    if milestone_type not in LISTING_TYPES and listing_price_cents is not None:
        raise invalid("listing_price_cents is not accepted for a %s milestone." % milestone_type)
    if milestone_type in REFI_TYPES and lender_name is None:
        raise invalid("lender_name is required for a %s milestone." % milestone_type)
    if milestone_type not in REFI_TYPES and lender_name is not None:
        raise invalid("lender_name is not accepted for a %s milestone." % milestone_type)

    loan = ser.find_loan(rec_id)
    require_borrower_owner(loan["borrower_id"])
    svc.require_loan_writable(loan)
    svc.require_serviceable(loan)

    if effective_date < loan["closing_date"]:
        raise conflict("ERR_MILESTONE_BACKDATED",
                       "A milestone may not precede the loan's closing_date.")
    latest = calc.latest_milestone(loan["id"])
    if latest is not None and effective_date < latest["effective_date"]:
        raise conflict("ERR_MILESTONE_BACKDATED",
                       "A milestone may not precede the latest milestone already on file.")

    milestone = new_record(full=False)
    milestone.update({
        "loan_id": loan["id"],
        "milestone_type": milestone_type,
        "effective_date": effective_date,
        "listing_price_cents": listing_price_cents,
        "lender_name": lender_name,
        "note": note,
        "derived_exit_status": calc.MILESTONE_EXIT_MAP[milestone_type],
    })
    db.exit_milestones[milestone["id"]] = milestone
    svc.refresh_exit_status(loan)
    touch(loan)
    return ok(ser.exit_milestone_out(milestone), 201)


@bp.get("/loans/<rec_id>/exit-milestones")
def list_exit_milestones(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_LOAN_SERVICER, ROLE_BORROWER, ROLE_PLATFORM_ADMIN))
    milestone_type = q_enum("milestone_type", calc.MILESTONE_TYPES)
    loan = ser.find_loan(rec_id)
    require_borrower_owner(loan["borrower_id"])
    rows = calc.loan_milestones(loan["id"])
    if milestone_type is not None:
        rows = [m for m in rows if m["milestone_type"] == milestone_type]
    items, meta = paginate(rows, ser.exit_milestone_out)
    return ok_list(items, meta)


# ---------------------------------------------------------------------------
# Default declaration
# ---------------------------------------------------------------------------
@bp.post("/loans/<rec_id>/default-declaration")
def declare_default(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    f_str(body, "reason")
    loan = ser.find_loan(rec_id)

    if loan["payment_status"] not in ("CURRENT", "DELINQUENT"):
        raise conflict("ERR_LOAN_STATE_INVALID",
                       "Only a CURRENT or DELINQUENT loan can be declared in default.")

    today = clock_date()
    aged = (loan["payment_status"] == "DELINQUENT"
            and loan["delinquent_since"] is not None
            and (today - loan["delinquent_since"]).days >= calc.DELINQUENCY_TO_DEFAULT_DAYS)
    matured = today > loan["maturity_date"]
    if not aged and not matured:
        raise conflict("ERR_DEFAULT_PRECONDITION_NOT_MET",
                       "Neither the delinquency aging test nor the maturity-breach test is met.")

    loan["payment_status"] = "DEFAULT"
    loan["default_effective_date"] = today
    svc.suspend_open_requests(loan)
    touch(loan)

    borrower = db.borrowers.get(loan["borrower_id"])
    if borrower is not None:
        borrower["prior_default_count"] += 1
        svc.suspend_borrower(borrower, "LOAN_DEFAULT",
                             skip_application_id=loan["application_id"])
    return ok(ser.loan_out(loan))


# ---------------------------------------------------------------------------
# Foreclosure
# ---------------------------------------------------------------------------
@bp.post("/loans/<rec_id>/foreclosure-cases")
def open_foreclosure_case(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    notice_date = f_date(body, "notice_date")
    county_code = f_str(body, "county_code")
    loan = ser.find_loan(rec_id)
    svc.require_loan_writable(loan)

    case = new_record()
    case.update({
        "loan_id": loan["id"],
        "notice_date": notice_date,
        "county_code": county_code,
        "redemption_expires_on": notice_date + timedelta(days=calc.REDEMPTION_DAYS),
        "takeover_date": None,
        "completion_budget_cents": None,
        "completion_advanced_cents": 0,
        "sale_price_cents": None,
        "selling_costs_cents": None,
        "net_proceeds_cents": None,
        "recovery_cents": None,
        "charge_off_cents": None,
        "surplus_returned_cents": None,
        "status": "NOTICE_FILED",
    })
    db.foreclosure_cases[case["id"]] = case
    return ok(ser.foreclosure_case_out(case), 201)


@bp.get("/loans/<rec_id>/foreclosure-cases")
def list_foreclosure_cases(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    status = q_enum("status", FORECLOSURE_STATUSES)
    loan = ser.find_loan(rec_id)
    rows = ser.loan_foreclosure_cases(loan["id"])
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    items, meta = paginate(rows, ser.foreclosure_case_out)
    return ok_list(items, meta)


@bp.get("/foreclosure-cases/<rec_id>")
def read_foreclosure_case(rec_id):
    authenticate((ROLE_LOAN_OFFICER, ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    return ok(ser.foreclosure_case_out(ser.find_foreclosure_case(rec_id)))


@bp.post("/foreclosure-cases/<rec_id>/takeover")
def foreclosure_takeover(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    takeover_date = f_date(body, "takeover_date")
    case = ser.find_foreclosure_case(rec_id)
    loan = ser.find_loan(case["loan_id"])

    if case["status"] != "NOTICE_FILED":
        raise conflict("ERR_FORECLOSURE_CASE_STATE_INVALID",
                       "Only a NOTICE_FILED case can be taken over.")
    if loan["payment_status"] != "DEFAULT":
        raise conflict("ERR_LOAN_STATE_INVALID",
                       "The loan must be in DEFAULT for a takeover.")
    if clock_date() < case["redemption_expires_on"]:
        raise conflict("ERR_REDEMPTION_PERIOD_ACTIVE",
                       "The redemption period has not expired.")

    case["takeover_date"] = takeover_date
    case["status"] = "TAKEOVER_COMPLETE"
    touch(case)

    svc.move_property(loan, "LENDER_REO", ("BORROWER_OWNED",))
    svc.set_exit_status(loan, "FORECLOSED")
    if loan["construction_status"] in ("NOT_STARTED", "IN_PROGRESS", "COMPLETE"):
        loan["construction_status"] = "LENDER_COMPLETING"
    swept = loan["undisbursed_holdback_cents"]
    loan["undisbursed_holdback_cents"] = 0
    loan["decommitted_holdback_cents"] += swept
    touch(loan)
    if swept > 0:
        svc.write_ledger(loan, "HOLDBACK_DECOMMIT", swept, takeover_date,
                         "Holdback decommitted on lender takeover", case["id"])
    return ok(ser.foreclosure_case_out(case))


@bp.post("/foreclosure-cases/<rec_id>/completion-budget")
def completion_budget(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    budget_cents = f_int(body, "budget_cents", minimum=0)
    expected_version = f_int(body, "expected_foreclosure_case_version", minimum=0)
    case = ser.find_foreclosure_case(rec_id)
    loan = ser.find_loan(case["loan_id"])

    if expected_version != case["version"]:
        raise ApiError("ERR_STALE_FORECLOSURE_CASE_VERSION", 412,
                       "expected_foreclosure_case_version does not match the case's version.")

    if case["status"] not in ("TAKEOVER_COMPLETE", "COMPLETION_FUNDED"):
        raise conflict("ERR_FORECLOSURE_CASE_STATE_INVALID",
                       "A completion budget requires a case in TAKEOVER_COMPLETE or COMPLETION_FUNDED.")
    svc.require_loan_writable(loan)

    prop = svc.property_of_loan(loan)
    cap = calc.completion_budget_cap(prop["arv_cents"]) if prop is not None else 0
    if budget_cents > cap:
        raise conflict("ERR_COMPLETION_BUDGET_EXCEEDS_CAP",
                       "budget_cents exceeds the completion-budget ceiling.")

    previous = case["completion_budget_cents"] or 0
    delta = budget_cents - previous
    case["completion_budget_cents"] = budget_cents
    case["status"] = "COMPLETION_FUNDED"
    touch(case)
    loan["committed_amount_cents"] += delta
    loan["undisbursed_holdback_cents"] += delta
    touch(loan)
    return ok(ser.foreclosure_case_out(case))


@bp.post("/foreclosure-cases/<rec_id>/disposition")
def foreclosure_disposition(rec_id):
    authenticate((ROLE_LOAN_SERVICER, ROLE_PLATFORM_ADMIN))
    body = json_body()
    sale_price_cents = f_int(body, "sale_price_cents", minimum=1)
    sale_date = f_date(body, "sale_date")
    completion_spend_cents = f_int(body, "completion_spend_cents", minimum=0)
    case = ser.find_foreclosure_case(rec_id)
    loan = ser.find_loan(case["loan_id"])

    if case["status"] not in ("TAKEOVER_COMPLETE", "COMPLETION_FUNDED"):
        raise conflict("ERR_FORECLOSURE_CASE_STATE_INVALID",
                       "Only a taken-over case can be disposed.")
    svc.require_loan_writable(loan)

    budget = case["completion_budget_cents"] or 0
    if completion_spend_cents > budget:
        raise conflict("ERR_COMPLETION_SPEND_EXCEEDS_BUDGET",
                       "completion_spend_cents exceeds the funded completion budget.")

    # The advance lands before the payoff arithmetic; the cash comes out of the
    # holdback the completion budget committed, so the identity is preserved.
    case["completion_advanced_cents"] = completion_spend_cents
    loan["funded_principal_cents"] += completion_spend_cents
    loan["undisbursed_holdback_cents"] -= completion_spend_cents
    if completion_spend_cents > 0:
        svc.write_ledger(loan, "COMPLETION_ADVANCE", completion_spend_cents, sale_date,
                         "Lender completion advance", case["id"])

    # Unspent budget plus any residual holdback is decommitted.
    loan["decommitted_holdback_cents"] += loan["undisbursed_holdback_cents"]
    loan["undisbursed_holdback_cents"] = 0

    selling_costs = calc.reo_selling_costs(sale_price_cents)
    net_proceeds = sale_price_cents - selling_costs
    payoff = calc.payoff_quote(loan, sale_date, force_default_rate=True)

    case["sale_price_cents"] = sale_price_cents
    case["selling_costs_cents"] = selling_costs
    case["net_proceeds_cents"] = net_proceeds
    case["recovery_cents"] = min(payoff, net_proceeds)
    case["charge_off_cents"] = payoff - net_proceeds if payoff > net_proceeds else 0
    case["surplus_returned_cents"] = net_proceeds - payoff if net_proceeds > payoff else 0
    case["status"] = "RESOLVED"
    touch(case)

    loan["recovery_cents"] = case["recovery_cents"]
    loan["charge_off_cents"] = case["charge_off_cents"]
    loan["surplus_returned_cents"] = case["surplus_returned_cents"]

    svc.write_ledger(loan, "REO_SALE_PROCEEDS", net_proceeds, sale_date,
                     "REO sale proceeds", case["id"])
    if loan["charge_off_cents"] > 0:
        svc.write_ledger(loan, "CHARGE_OFF", loan["charge_off_cents"], sale_date,
                         "Charge off after REO disposition", case["id"])
        loan["payment_status"] = "CHARGED_OFF"
    else:
        loan["payment_status"] = "PAID_OFF"

    svc.settle_principal_and_revenue(loan)
    loan["construction_status"] = "LENDER_COMPLETE"
    touch(loan)
    svc.move_property(loan, "SOLD", ("LENDER_REO",))
    return ok(ser.foreclosure_case_out(case))


# ---------------------------------------------------------------------------
# Logical clock (test-driving capability)
# ---------------------------------------------------------------------------
@clock_bp.post("/_clock/set_current_utc")
def set_current_utc():
    role = flask_request.headers.get("X-User-Role") or flask_request.headers.get("X-Role")
    if role is not None and role.strip() != "" and role != ROLE_PLATFORM_ADMIN:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403)
    body = json_body()
    raw = body.get("to_iso8601")
    if raw is None:
        raise invalid("Field 'to_iso8601' is required.")
    db.clock = parse_datetime(raw, "to_iso8601")
    return ok({"current_utc": iso_instant(db.clock)})
