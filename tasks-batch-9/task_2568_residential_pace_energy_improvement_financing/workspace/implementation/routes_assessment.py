"""Assessments, the amortization schedule, collections, payoffs and roll runs."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint

import calc
import db
import response
import services
import validation as v
from errors import fail
from middleware import ALL_ROLES, ROLE_COUNTY_OFFICER, authorize

bp = Blueprint("assessment", __name__)


def _list(rows, limit, offset):
    window, total = response.paginate(rows, limit, offset)
    return response.listing([db.public(row) for row in window], limit, offset, total)


def _midnight(day):
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _recompute_delinquency(assessment):
    installments = services.installments_of(assessment["id"])
    delinquent = [row for row in installments if row["status"] == "DELINQUENT"]
    assessment["delinquent_installment_count"] = len(delinquent)
    assessment["accrued_penalty_cents"] = sum(
        int(row["penalty_cents"]) for row in delinquent
    )


def _retire(assessment, prop):
    """The terminal payoff picture shared by payment, prepayment and sale payoff."""
    assessment["principal_balance_cents"] = 0
    assessment["billing_status"] = "PAID_OFF"
    assessment["lien_status"] = "RELEASED"
    for row in services.installments_of(assessment["id"]):
        if row["status"] == "SCHEDULED":
            row["status"] = "CANCELLED"
            db.touch(row)
    services.recompute_property_rollups(prop)


# ------------------------------------------------------------- assessments ----
@bp.post("/pace/assessments")
def record_assessment():
    authorize([ROLE_COUNTY_OFFICER])
    payload = v.body()
    application_id = v.req_id(payload, "application_id")
    first_tax_year = v.req_int(payload, "first_tax_year", minimum=2027, maximum=2060)
    application = services.get_application(application_id)
    if application["status"] != "FUNDED":
        fail("ERR_APPLICATION_STATE_INVALID", "Application is not FUNDED")
    agreement = services.live_agreement_of(application["id"])
    if agreement is None or agreement["status"] != "EFFECTIVE":
        fail("ERR_AGREEMENT_STATE_INVALID", "The financing agreement is not EFFECTIVE")
    prop = services.get_property(application["property_id"])
    term_years = int(agreement["term_years"])
    final_tax_year = first_tax_year + term_years - 1
    for other in services.assessments_of_property(prop["id"]):
        if (
            first_tax_year <= int(other["final_tax_year"])
            and int(other["first_tax_year"]) <= final_tax_year
        ):
            fail(
                "ERR_ASSESSMENT_YEAR_OVERLAP",
                "Another assessment on this parcel already occupies those tax years",
            )
    if first_tax_year < db.today().year:
        fail("ERR_TAX_YEAR_IN_PAST", "first_tax_year is earlier than the current tax year")
    recorded_on = db.today().isoformat()
    original_principal = int(agreement["financed_amount_cents"])
    assessment = db.create(
        "assessments",
        {
            "application_id": application["id"],
            "property_id": prop["id"],
            "apn": prop["apn"],
            "first_tax_year": first_tax_year,
            "final_tax_year": final_tax_year,
            "term_years": term_years,
            "apr_bps": int(agreement["apr_bps"]),
            "original_principal_cents": original_principal,
            "principal_balance_cents": original_principal,
            "annual_installment_cents": int(agreement["annual_installment_cents"]),
            "recorded_on": recorded_on,
            "interest_accrual_from": recorded_on,
            "billing_status": "PENDING_ROLL",
            "lien_status": "SENIOR_RECORDED",
            "delinquent_installment_count": 0,
            "accrued_penalty_cents": 0,
            "transfer_status": "NONE",
        },
    )
    for line in calc.amortization_schedule(
        original_principal,
        assessment["annual_installment_cents"],
        assessment["apr_bps"],
        term_years,
        first_tax_year,
    ):
        row = dict(line)
        row["assessment_id"] = assessment["id"]
        row["status"] = "SCHEDULED"
        row["billed_on"] = None
        row["paid_on"] = None
        row["paid_amount_cents"] = 0
        row["penalty_cents"] = 0
        row["months_past_due"] = 0
        db.create("installments", row)
    application["status"] = "ASSESSED"
    db.touch(application)
    agreement["status"] = "RECORDED"
    db.touch(agreement)
    services.recompute_property_rollups(prop)
    return response.created(db.public(assessment))


@bp.get("/pace/assessments/<row_id>")
def read_assessment(row_id):
    authorize(ALL_ROLES)
    return response.ok(db.public(services.get_assessment(row_id)))


@bp.get("/pace/assessments")
def list_assessments():
    authorize(ALL_ROLES)
    limit, offset = v.pagination()
    property_id = v.filter_value("property_id")
    application_id = v.filter_value("application_id")
    billing_status = v.filter_value("billing_status")
    lien_status = v.filter_value("lien_status")
    rows = db.by_created_at(db.rows("assessments"))
    if property_id:
        rows = [row for row in rows if row["property_id"] == property_id]
    if application_id:
        rows = [row for row in rows if row["application_id"] == application_id]
    if billing_status:
        rows = [row for row in rows if row["billing_status"] == billing_status]
    if lien_status:
        rows = [row for row in rows if row["lien_status"] == lien_status]
    return _list(rows, limit, offset)


# ------------------------------------------------------------- installments ---
@bp.get("/pace/assessments/<row_id>/installments")
def list_installments(row_id):
    authorize(ALL_ROLES)
    limit, offset = v.pagination()
    status = v.filter_value("status")
    tax_year = v.filter_value("tax_year")
    assessment = services.get_assessment(row_id)
    rows = sorted(
        services.installments_of(assessment["id"]), key=lambda item: item["tax_year"]
    )
    if status:
        rows = [row for row in rows if row["status"] == status]
    if tax_year:
        if not v.INT_RE.match(tax_year):
            fail("ERR_VALIDATION", "tax_year must be an integer")
        rows = [row for row in rows if int(row["tax_year"]) == int(tax_year)]
    return _list(rows, limit, offset)


@bp.get("/pace/assessments/<row_id>/installments/<installment_id>")
def read_installment(row_id, installment_id):
    authorize(ALL_ROLES)
    assessment = services.get_assessment(row_id)
    installment = services.get_installment(installment_id)
    if installment["assessment_id"] != assessment["id"]:
        fail(
            "ERR_INSTALLMENT_ASSESSMENT_MISMATCH",
            "That installment belongs to a different assessment",
        )
    return response.ok(db.public(installment))


# ------------------------------------------------------------- collection -----
@bp.post("/pace/assessments/<row_id>/installments/<installment_id>/payments")
def pay_installment(row_id, installment_id):
    authorize([ROLE_COUNTY_OFFICER])
    payload = v.body()
    amount_cents = v.req_int(payload, "amount_cents", minimum=0)
    paid_on = v.opt_date(payload, "paid_on")
    assessment = services.get_assessment(row_id)
    installment = services.get_installment(installment_id)
    if installment["assessment_id"] != assessment["id"]:
        fail(
            "ERR_INSTALLMENT_ASSESSMENT_MISMATCH",
            "That installment belongs to a different assessment",
        )
    if assessment["billing_status"] != "ON_ROLL":
        fail("ERR_ASSESSMENT_STATE_INVALID", "Assessment is not ON_ROLL")
    if installment["status"] not in ("BILLED", "DELINQUENT"):
        fail("ERR_INSTALLMENT_STATE_INVALID", "Installment is not BILLED or DELINQUENT")
    expected = int(installment["total_due_cents"])
    if installment["status"] == "DELINQUENT":
        expected += int(installment["penalty_cents"])
    if amount_cents != expected:
        fail(
            "ERR_PAYMENT_AMOUNT_MISMATCH",
            "amount_cents must equal exactly %d" % expected,
        )
    was_delinquent = installment["status"] == "DELINQUENT"
    installment["status"] = "PAID"
    installment["paid_on"] = paid_on or db.today().isoformat()
    installment["paid_amount_cents"] = amount_cents
    db.touch(installment)
    assessment["principal_balance_cents"] = int(
        assessment["principal_balance_cents"]
    ) - int(installment["principal_cents"])
    paid = [
        row for row in services.installments_of(assessment["id"]) if row["status"] == "PAID"
    ]
    if paid:
        assessment["interest_accrual_from"] = paid[-1]["due_on"]
    _recompute_delinquency(assessment)
    if (
        was_delinquent
        and assessment["delinquent_installment_count"] == 0
        and assessment["lien_status"] == "LIEN_SALE_REFERRED"
    ):
        assessment["lien_status"] = "SENIOR_RECORDED"
        assessment["accrued_penalty_cents"] = 0
    prop = services.get_property(assessment["property_id"])
    if (
        int(assessment["principal_balance_cents"]) == 0
        and assessment["delinquent_installment_count"] == 0
    ):
        _retire(assessment, prop)
    db.touch(assessment)
    services.recompute_property_rollups(prop)
    return response.ok(db.public(installment))


@bp.post("/pace/assessments/<row_id>/prepayments")
def prepay_assessment(row_id):
    authorize([ROLE_COUNTY_OFFICER])
    payload = v.body()
    amount_cents = v.req_int(payload, "amount_cents", minimum=0)
    expected_version = v.req_int(payload, "expected_assessment_version", minimum=1)
    assessment = services.get_assessment(row_id)
    if int(assessment["version"]) != expected_version:
        fail(
            "ERR_ASSESSMENT_VERSION_CONFLICT",
            "expected_assessment_version does not match the assessment version",
        )
    if assessment["billing_status"] != "ON_ROLL":
        fail("ERR_ASSESSMENT_STATE_INVALID", "Assessment is not ON_ROLL")
    if assessment["lien_status"] != "SENIOR_RECORDED":
        fail("ERR_ASSESSMENT_STATE_INVALID", "Assessment lien is not SENIOR_RECORDED")
    quote = calc.payoff_quote(
        assessment["principal_balance_cents"],
        assessment["apr_bps"],
        calc.date_from_iso(assessment["interest_accrual_from"]),
        db.today(),
    )
    if amount_cents != int(quote["payoff_total_cents"]):
        fail(
            "ERR_PREPAYMENT_AMOUNT_MISMATCH",
            "amount_cents must equal the payoff total of %d"
            % quote["payoff_total_cents"],
        )
    prop = services.get_property(assessment["property_id"])
    _retire(assessment, prop)
    db.touch(assessment)
    return response.ok(db.public(assessment))


# ---------------------------------------------------------------- transfers ---
@bp.get("/pace/assessments/<row_id>/transfers")
def list_assessment_transfers(row_id):
    authorize(ALL_ROLES)
    limit, offset = v.pagination()
    status = v.filter_value("status")
    assessment = services.get_assessment(row_id)
    rows = services.transfers_of(assessment["id"])
    if status:
        rows = [row for row in rows if row["status"] == status]
    return _list(rows, limit, offset)


@bp.post("/pace/assessment-transfers")
def create_transfer():
    authorize([ROLE_COUNTY_OFFICER])
    payload = v.body()
    assessment_id = v.req_id(payload, "assessment_id")
    mode = v.req_enum(payload, "mode", v.TRANSFER_MODES)
    closing_date = v.req_date(payload, "closing_date")
    buyer_full_name = v.req_str(payload, "buyer_full_name")
    buyer_birth_date = v.req_date(payload, "buyer_birth_date")
    assessment = services.get_assessment(assessment_id)
    if assessment["billing_status"] != "ON_ROLL":
        fail("ERR_ASSESSMENT_STATE_INVALID", "Assessment is not ON_ROLL")
    if assessment["lien_status"] != "SENIOR_RECORDED":
        fail("ERR_ASSESSMENT_STATE_INVALID", "Assessment lien is not SENIOR_RECORDED")
    closing = calc.date_from_iso(closing_date)
    if closing < db.today():
        fail("ERR_CLOSING_DATE_IN_PAST", "closing_date is before the current logical date")
    instant = db.now()
    for other in services.transfers_of(assessment["id"]):
        if other["status"] != "QUOTED":
            continue
        start = db.parse_instant(other["quoted_at"])
        end = _midnight(
            calc.date_from_iso(other["good_through_date"])
            + timedelta(days=calc.QUOTE_BUFFER_DAYS)
        )
        if start is not None and start <= instant < end:
            fail(
                "ERR_QUOTE_WINDOW_OVERLAP",
                "A live payoff quote already covers this instant",
            )
    quote = calc.payoff_quote(
        assessment["principal_balance_cents"],
        assessment["apr_bps"],
        calc.date_from_iso(assessment["interest_accrual_from"]),
        closing,
    )
    good_through = instant.date() + timedelta(days=calc.QUOTE_GOOD_THROUGH_DAYS)
    transfer = db.create(
        "transfers",
        {
            "assessment_id": assessment["id"],
            "mode": mode,
            "closing_date": closing_date,
            "buyer_full_name": buyer_full_name,
            "buyer_birth_date": buyer_birth_date,
            "quoted_at": db.iso(instant),
            "good_through_date": good_through.isoformat(),
            "payoff_principal_cents": quote["payoff_principal_cents"],
            "accrued_interest_cents": quote["accrued_interest_cents"],
            "payoff_admin_fee_cents": quote["payoff_admin_fee_cents"],
            "base_payoff_cents": quote["base_payoff_cents"],
            "prepayment_premium_bps": quote["prepayment_premium_bps"],
            "prepayment_premium_cents": quote["prepayment_premium_cents"],
            "payoff_total_cents": quote["payoff_total_cents"],
            "status": "QUOTED",
            "recorded_on": None,
        },
    )
    assessment["transfer_status"] = "QUOTED"
    db.touch(assessment)
    return response.created(db.public(transfer))


@bp.get("/pace/assessment-transfers/<row_id>")
def read_transfer(row_id):
    authorize(ALL_ROLES)
    return response.ok(db.public(services.get_transfer(row_id)))


@bp.post("/pace/assessment-transfers/<row_id>/record")
def record_transfer(row_id):
    authorize([ROLE_COUNTY_OFFICER])
    payload = v.body()
    recorded_on = v.opt_date(payload, "recorded_on")
    transfer = services.get_transfer(row_id)
    if transfer["status"] != "QUOTED":
        fail("ERR_TRANSFER_STATE_INVALID", "Transfer is not QUOTED")
    assessment = services.get_assessment(transfer["assessment_id"])
    if db.today() >= calc.date_from_iso(transfer["good_through_date"]):
        transfer["status"] = "EXPIRED"
        db.touch(transfer)
        assessment["transfer_status"] = "NONE"
        db.touch(assessment)
        fail("ERR_QUOTE_EXPIRED", "The payoff quote is no longer current")
    if assessment["lien_status"] != "SENIOR_RECORDED":
        fail("ERR_ASSESSMENT_STATE_INVALID", "Assessment lien is not SENIOR_RECORDED")
    for row in services.installments_of(assessment["id"]):
        if row["status"] == "DELINQUENT":
            fail(
                "ERR_ASSESSMENT_STATE_INVALID",
                "A delinquent installment must be settled before closing",
            )
    prop = services.get_property(assessment["property_id"])
    prop["owner_full_name"] = transfer["buyer_full_name"]
    prop["owner_birth_date"] = transfer["buyer_birth_date"]
    db.touch(prop)
    transfer["recorded_on"] = recorded_on or db.today().isoformat()
    if transfer["mode"] == "ASSUME_WITH_PROPERTY":
        transfer["status"] = "RECORDED_ASSUMED"
        assessment["transfer_status"] = "ASSUMED"
    else:
        transfer["status"] = "RECORDED_PAID_OFF"
        assessment["transfer_status"] = "PAID_OFF_AT_SALE"
        _retire(assessment, prop)
    db.touch(transfer)
    db.touch(assessment)
    return response.ok(db.public(transfer))


# ----------------------------------------------------------------- roll run ---
LIVE_CURE_STATUSES = ("UNDER_REVIEW", "CONSENT_PENDING")


@bp.post("/pace/counties/<county_code>/roll-runs")
def roll_run(county_code):
    authorize([ROLE_COUNTY_OFFICER])
    payload = v.body()
    tax_year = v.req_int(payload, "tax_year", minimum=0)
    effective_date = v.req_date(payload, "effective_date")
    effective = calc.date_from_iso(effective_date)

    scope = []
    for assessment in db.by_created_at(db.rows("assessments")):
        prop = db.get("properties", assessment["property_id"])
        if prop is None or prop["county_code"] != county_code:
            continue
        if assessment["lien_status"] == "RELEASED":
            continue
        scope.append((assessment, prop))

    # --- step one: bill -----------------------------------------------------
    billed_count = 0
    for assessment, _prop in scope:
        moved = 0
        for row in services.installments_of(assessment["id"]):
            if row["status"] == "SCHEDULED" and int(row["tax_year"]) == tax_year:
                row["status"] = "BILLED"
                row["billed_on"] = effective_date
                db.touch(row)
                moved += 1
        billed_count += moved
        if moved and assessment["billing_status"] == "PENDING_ROLL":
            assessment["billing_status"] = "ON_ROLL"
            db.touch(assessment)

    # --- step two: sweep and price -----------------------------------------
    lien_at_start = {
        assessment["id"]: assessment["lien_status"] for assessment, _prop in scope
    }
    delinquent_count = 0
    total_penalty = 0
    for assessment, _prop in scope:
        swept = 0
        referred_already = lien_at_start[assessment["id"]] == "LIEN_SALE_REFERRED"
        for row in services.installments_of(assessment["id"]):
            if row["status"] != "BILLED":
                continue
            if calc.date_from_iso(row["due_on"]) >= effective:
                continue
            penalty, months = calc.delinquency_penalty(
                row["total_due_cents"],
                calc.date_from_iso(row["due_on"]),
                effective,
                referred_already,
            )
            row["status"] = "DELINQUENT"
            row["penalty_cents"] = penalty
            row["months_past_due"] = months
            db.touch(row)
            swept += 1
            total_penalty += penalty
        if swept:
            delinquent_count += swept
            _recompute_delinquency(assessment)
            db.touch(assessment)

    # --- step three: refer --------------------------------------------------
    referred = []
    for assessment, _prop in scope:
        if (
            int(assessment["delinquent_installment_count"]) >= 2
            and assessment["lien_status"] == "SENIOR_RECORDED"
        ):
            assessment["lien_status"] = "LIEN_SALE_REFERRED"
            db.touch(assessment)
            referred.append((assessment, _prop))

    # --- step four: cascade -------------------------------------------------
    voided_transfer_ids = []
    cured_application_ids = []
    incremented_property_ids = []
    for assessment, prop in referred:
        for transfer in services.transfers_of(assessment["id"]):
            if transfer["status"] == "QUOTED":
                transfer["status"] = "VOID_STALE"
                db.touch(transfer)
                voided_transfer_ids.append(transfer["id"])
                assessment["transfer_status"] = "NONE"
                db.touch(assessment)
        prop["tax_delinquency_count_36m"] = int(prop["tax_delinquency_count_36m"]) + 1
        db.touch(prop)
        if prop["id"] not in incremented_property_ids:
            incremented_property_ids.append(prop["id"])
        for application in services.applications_of_property(prop["id"]):
            if application["status"] in LIVE_CURE_STATUSES:
                application["status"] = "NEEDS_CURE"
                application["cure_reason_codes"] = ["TAX_DELINQUENCY"]
                db.touch(application)
                if application["id"] not in cured_application_ids:
                    cured_application_ids.append(application["id"])

    return response.ok(
        {
            "county_code": county_code,
            "tax_year": tax_year,
            "effective_date": effective_date,
            "billed_installment_count": billed_count,
            "delinquent_installment_count": delinquent_count,
            "total_penalty_cents": total_penalty,
            "referred_assessment_ids": ",".join(row["id"] for row, _p in referred),
            "voided_transfer_ids": ",".join(voided_transfer_ids),
            "cured_application_ids": ",".join(cured_application_ids),
            "incremented_property_ids": ",".join(incremented_property_ids),
        }
    )
