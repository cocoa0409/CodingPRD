"""Stormwater Utility & Impervious-Area Billing API (Flask, in-memory)."""
import os
from datetime import timedelta

from flask import Flask, request

import store
import calc
from helpers import (
    ApiError,
    authenticate,
    check_ownership,
    error_response,
    exists_if_present,
    get_body,
    must_exist,
    ok_list,
    ok_object,
    paginate,
    pagination,
    require_enum,
    require_fields,
    require_int_ge,
    require_int_gt,
    require_num_range,
)

app = Flask(__name__)

LAND_USES = {"RESIDENTIAL_SF", "RESIDENTIAL_MF", "COMMERCIAL", "INDUSTRIAL",
             "INSTITUTIONAL", "UNDEVELOPED"}
BILLING_METHODS = {"TAX_ROLL", "UTILITY_BILL"}
MEAS_METHODS = {"GIS", "FIELD_SURVEY", "AERIAL"}
MEAS_SOURCES = {"ROUTINE", "APPEAL_REMEASURE"}
EXEMPTION_CATEGORIES = {"GOVERNMENT", "RELIGIOUS", "AGRICULTURAL", "UNDEVELOPED", "LOW_IMPACT"}
BMP_TYPES = {"RAIN_GARDEN", "DETENTION_POND", "PERMEABLE_PAVEMENT", "GREEN_ROOF", "CISTERN"}
PAYMENT_METHODS = {"ACH", "CARD", "CHECK", "TAX_ROLL"}
FEE_VARIANTS = {"MARGINAL", "FLAT"}
APPEAL_GROUNDS = {"MEASUREMENT_ERROR", "LAND_USE_ERROR", "EXEMPTION_DENIED", "CREDIT_DENIED"}


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found."))


@app.errorhandler(405)
def _handle_405(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Method not allowed."))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error."))


def parse_input_dt(body, field):
    try:
        return store.parse_dt(body[field])
    except (ValueError, KeyError, TypeError):
        raise ApiError("ERR_OUT_OF_RANGE", 422, f"{field} is not a valid datetime.")


# ===========================================================================
# Accounts
# ===========================================================================
@app.route("/accounts", methods=["POST"])
def create_account():
    authenticate({"Assessor", "StormwaterAdmin"})
    body = get_body()
    require_fields(body, ["owner_name", "contact_email"])
    billing_method = body.get("billing_method", "UTILITY_BILL")
    if billing_method is None:
        billing_method = "UTILITY_BILL"
    require_enum(billing_method, BILLING_METHODS, "billing_method")

    acct = store.base_entity(common_fields=True)
    acct.update({
        "owner_name": body["owner_name"],
        "contact_email": body["contact_email"],
        "billing_method": billing_method,
        "mailing_address": body.get("mailing_address"),
        "outstanding_balance_cents": 0,
        "delinquency_status": "CURRENT",
    })
    store.accounts[acct["id"]] = acct
    return ok_object(store.public(acct), 201)


@app.route("/accounts/<id>", methods=["GET"])
def get_account(id):
    _uid, role = authenticate({"Assessor", "BillingClerk", "StormwaterAdmin", "PropertyOwner"})
    acct = must_exist(store.accounts, id)
    check_ownership(role, _uid, acct["id"])
    return ok_object(store.public(acct))


# ===========================================================================
# Parcels
# ===========================================================================
@app.route("/parcels", methods=["POST"])
def create_parcel():
    authenticate({"Assessor", "StormwaterAdmin"})
    body = get_body()
    exists_if_present(store.accounts, body, "account_id")
    require_fields(body, ["account_id", "parcel_number", "land_use"])
    require_enum(body["land_use"], LAND_USES, "land_use")
    for p in store.parcels.values():
        if p["parcel_number"] == body["parcel_number"]:
            raise ApiError("ERR_DUPLICATE_PARCEL", 409, "parcel_number already exists.")

    parcel = store.base_entity(common_fields=True)
    parcel.update({
        "account_id": body["account_id"],
        "parcel_number": body["parcel_number"],
        "land_use": body["land_use"],
        "status": "DRAFT",
        "active_measurement_id": None,
        "impervious_area_sqft": 0,
        "exempt_pct": 0,
        "billable_eru": 0,
        "current_fee_cents": 0,
    })
    store.parcels[parcel["id"]] = parcel
    return ok_object(store.public(parcel), 201)


@app.route("/parcels/<id>", methods=["GET"])
def get_parcel(id):
    _uid, role = authenticate({"Assessor", "BillingClerk", "StormwaterAdmin", "PropertyOwner"})
    parcel = must_exist(store.parcels, id)
    check_ownership(role, _uid, parcel["account_id"])
    return ok_object(store.public(parcel))


@app.route("/parcels", methods=["GET"])
def list_parcels():
    authenticate({"Assessor", "BillingClerk", "StormwaterAdmin"})
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    rows = [
        p for p in store.parcels.values()
        if (account_id is None or p["account_id"] == account_id)
        and (status is None or p["status"] == status)
    ]
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@app.route("/parcels/<id>/fee-quote", methods=["GET"])
def parcel_fee_quote(id):
    _uid, role = authenticate({"Assessor", "BillingClerk", "StormwaterAdmin", "PropertyOwner"})
    parcel = must_exist(store.parcels, id)
    check_ownership(role, _uid, parcel["account_id"])

    eru = parcel["billable_eru"]
    credit_pct = calc.parcel_credit_pct(id)
    base_m = calc.base_fee_marginal(eru)
    base_f = calc.base_fee_flat(eru)
    marginal_assessed = store.FIXED_CHARGE_CENTS + base_m - calc.credit_amount_cents(base_m, credit_pct)
    flat_assessed = store.FIXED_CHARGE_CENTS + base_f - calc.credit_amount_cents(base_f, credit_pct)
    return ok_object({
        "billable_eru": eru,
        "credit_pct": credit_pct,
        "base_fee_marginal_cents": base_m,
        "base_fee_flat_cents": base_f,
        "marginal_assessed_cents": marginal_assessed,
        "flat_assessed_cents": flat_assessed,
    })


# ===========================================================================
# Impervious Measurements
# ===========================================================================
@app.route("/impervious-measurements", methods=["POST"])
def create_measurement():
    uid, _role = authenticate({"Assessor"})
    body = get_body()
    parcel = exists_if_present(store.parcels, body, "parcel_id")
    require_fields(body, ["parcel_id", "measured_sqft", "method", "expected_parcel_version"])
    require_int_ge(body["measured_sqft"], 0, "measured_sqft")
    require_enum(body["method"], MEAS_METHODS, "method")
    source = body.get("source", "ROUTINE")
    if source is None:
        source = "ROUTINE"
    require_enum(source, MEAS_SOURCES, "source")

    if body["expected_parcel_version"] != parcel["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Parcel version is stale.")

    # Supersede the prior ACTIVE measurement for this parcel.
    for m in store.measurements.values():
        if m["parcel_id"] == parcel["id"] and m["status"] == "ACTIVE":
            m["status"] = "SUPERSEDED"
            store.touch(m)

    meas = store.base_entity(common_fields=True)
    meas.update({
        "parcel_id": parcel["id"],
        "measured_sqft": body["measured_sqft"],
        "method": body["method"],
        "source": source,
        "status": "ACTIVE",
        "recorded_by_user_id": uid,
    })
    store.measurements[meas["id"]] = meas

    calc.recompute_parcel(parcel)
    store.touch(parcel)

    # Appeal remeasure loop: a NEEDS_REMEASURE appeal for this parcel returns
    # to UNDER_REVIEW when an APPEAL_REMEASURE measurement is recorded.
    if source == "APPEAL_REMEASURE":
        for ap in store.appeals.values():
            if ap["parcel_id"] == parcel["id"] and ap["status"] == "NEEDS_REMEASURE":
                ap["status"] = "UNDER_REVIEW"
                store.touch(ap)

    return ok_object(store.public(meas), 201)


@app.route("/impervious-measurements/<id>", methods=["GET"])
def get_measurement(id):
    uid, role = authenticate({"Assessor", "StormwaterAdmin", "PropertyOwner"})
    meas = must_exist(store.measurements, id)
    if role == "PropertyOwner":
        parcel = store.parcels.get(meas["parcel_id"])
        owner = parcel["account_id"] if parcel else None
        check_ownership(role, uid, owner)
    return ok_object(store.public(meas))


@app.route("/impervious-measurements", methods=["GET"])
def list_measurements():
    authenticate({"Assessor", "StormwaterAdmin"})
    parcel_id = request.args.get("parcel_id")
    status = request.args.get("status")
    rows = [
        m for m in store.measurements.values()
        if (parcel_id is None or m["parcel_id"] == parcel_id)
        and (status is None or m["status"] == status)
    ]
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


# ===========================================================================
# Exemptions
# ===========================================================================
@app.route("/exemptions", methods=["POST"])
def create_exemption():
    uid, role = authenticate({"PropertyOwner", "Assessor", "StormwaterAdmin"})
    body = get_body()
    parcel = exists_if_present(store.parcels, body, "parcel_id")
    if role == "PropertyOwner" and parcel is not None:
        check_ownership(role, uid, parcel["account_id"])
    require_fields(body, ["parcel_id", "category", "requested_pct"])
    require_enum(body["category"], EXEMPTION_CATEGORIES, "category")
    require_num_range(body["requested_pct"], 0, 1, "requested_pct")

    ex = store.base_entity(common_fields=True)
    ex.update({
        "parcel_id": parcel["id"],
        "category": body["category"],
        "requested_pct": body["requested_pct"],
        "granted_pct": 0,
        "status": "REQUESTED",
        "decision_note": body.get("decision_note"),
    })
    store.exemptions[ex["id"]] = ex
    return ok_object(store.public(ex), 201)


@app.route("/exemptions/<id>", methods=["GET"])
def get_exemption(id):
    uid, role = authenticate({"Assessor", "StormwaterAdmin", "PropertyOwner"})
    ex = must_exist(store.exemptions, id)
    if role == "PropertyOwner":
        parcel = store.parcels.get(ex["parcel_id"])
        owner = parcel["account_id"] if parcel else None
        check_ownership(role, uid, owner)
    return ok_object(store.public(ex))


@app.route("/exemptions", methods=["GET"])
def list_exemptions():
    authenticate({"Assessor", "StormwaterAdmin"})
    parcel_id = request.args.get("parcel_id")
    status = request.args.get("status")
    rows = [
        e for e in store.exemptions.values()
        if (parcel_id is None or e["parcel_id"] == parcel_id)
        and (status is None or e["status"] == status)
    ]
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@app.route("/exemptions/<id>/decision", methods=["POST"])
def decide_exemption(id):
    authenticate({"Assessor", "StormwaterAdmin"})
    ex = must_exist(store.exemptions, id)
    body = get_body()
    require_fields(body, ["outcome"])
    require_enum(body["outcome"], {"GRANT", "DENY"}, "outcome")
    if "granted_pct" in body and body["granted_pct"] is not None:
        require_num_range(body["granted_pct"], 0, 1, "granted_pct")

    if ex["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Exemption is not REQUESTED.")

    if body["outcome"] == "GRANT":
        for other in store.exemptions.values():
            if (other["parcel_id"] == ex["parcel_id"] and other["id"] != ex["id"]
                    and other["status"] == "GRANTED"):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Parcel already has a GRANTED exemption.")
        granted = body.get("granted_pct")
        if granted is None:
            granted = ex["requested_pct"]
        ex["granted_pct"] = granted
        ex["status"] = "GRANTED"
        if "decision_note" in body and body["decision_note"] is not None:
            ex["decision_note"] = body["decision_note"]
        store.touch(ex)

        parcel = store.parcels.get(ex["parcel_id"])
        if parcel is not None:
            calc.recompute_parcel(parcel)
            store.touch(parcel)
    else:
        ex["status"] = "DENIED"
        if "decision_note" in body and body["decision_note"] is not None:
            ex["decision_note"] = body["decision_note"]
        store.touch(ex)

    return ok_object(store.public(ex))


# ===========================================================================
# BMP Credits
# ===========================================================================
@app.route("/bmp-credits", methods=["POST"])
def create_bmp_credit():
    uid, role = authenticate({"PropertyOwner", "Assessor"})
    body = get_body()
    parcel = exists_if_present(store.parcels, body, "parcel_id")
    if role == "PropertyOwner" and parcel is not None:
        check_ownership(role, uid, parcel["account_id"])
    require_fields(body, ["parcel_id", "bmp_type", "self_reported_score",
                          "effective_date", "expiry_date"])
    require_enum(body["bmp_type"], BMP_TYPES, "bmp_type")
    require_num_range(body["self_reported_score"], 0, 100, "self_reported_score")
    eff_dt = parse_input_dt(body, "effective_date")
    exp_dt = parse_input_dt(body, "expiry_date")

    for ex in store.exemptions.values():
        if ex["parcel_id"] == parcel["id"] and ex["status"] == "GRANTED":
            raise ApiError("ERR_PARCEL_EXEMPT", 409,
                           "Parcel already has a GRANTED exemption.")

    if eff_dt >= exp_dt:
        raise ApiError("ERR_INVALID_PERIOD", 422, "effective_date must precede expiry_date.")

    for c in store.bmp_credits.values():
        if (c["parcel_id"] == parcel["id"] and c["status"] == "ACTIVE"
                and c["bmp_type"] == body["bmp_type"]):
            c_eff = store.parse_dt(c["effective_date"])
            c_exp = store.parse_dt(c["expiry_date"])
            # Half-open [eff, exp): overlap iff eff < c_exp and c_eff < exp.
            if eff_dt < c_exp and c_eff < exp_dt:
                raise ApiError("ERR_CREDIT_WINDOW_OVERLAP", 409,
                               "Credit window overlaps an existing ACTIVE credit.")

    credit = store.base_entity(common_fields=True)
    credit.update({
        "parcel_id": parcel["id"],
        "bmp_type": body["bmp_type"],
        "self_reported_score": body["self_reported_score"],
        "inspected_score": None,
        "credit_pct": calc.credit_pct_from_score(body["self_reported_score"]),
        "status": "ACTIVE",
        "effective_date": body["effective_date"],
        "expiry_date": body["expiry_date"],
        "next_inspection_due": store.fmt_dt(eff_dt + timedelta(days=store.INSPECTION_INTERVAL_DAYS)),
    })
    store.bmp_credits[credit["id"]] = credit

    calc.recompute_parcel(parcel)
    store.touch(parcel)
    return ok_object(store.public(credit), 201)


@app.route("/bmp-credits/<id>", methods=["GET"])
def get_bmp_credit(id):
    uid, role = authenticate({"PropertyOwner", "Assessor", "CreditInspector", "StormwaterAdmin"})
    credit = must_exist(store.bmp_credits, id)
    if role == "PropertyOwner":
        parcel = store.parcels.get(credit["parcel_id"])
        owner = parcel["account_id"] if parcel else None
        check_ownership(role, uid, owner)
    return ok_object(store.public(credit))


@app.route("/bmp-credits", methods=["GET"])
def list_bmp_credits():
    authenticate({"Assessor", "CreditInspector", "StormwaterAdmin"})
    parcel_id = request.args.get("parcel_id")
    status = request.args.get("status")
    rows = [
        c for c in store.bmp_credits.values()
        if (parcel_id is None or c["parcel_id"] == parcel_id)
        and (status is None or c["status"] == status)
    ]
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


# ===========================================================================
# Credit Inspections
# ===========================================================================
@app.route("/credit-inspections", methods=["POST"])
def create_inspection():
    authenticate({"CreditInspector"})
    body = get_body()
    exists_if_present(store.bmp_credits, body, "bmp_credit_id")
    require_fields(body, ["bmp_credit_id", "scheduled_date"])

    insp = store.base_entity(common_fields=True)
    insp.update({
        "bmp_credit_id": body["bmp_credit_id"],
        "scheduled_date": body["scheduled_date"],
        "observed_score": None,
        "result": None,
        "status": "SCHEDULED",
        "inspector_note": body.get("inspector_note"),
    })
    store.inspections[insp["id"]] = insp
    return ok_object(store.public(insp), 201)


@app.route("/credit-inspections/<id>", methods=["GET"])
def get_inspection(id):
    authenticate({"CreditInspector", "Assessor", "StormwaterAdmin"})
    insp = must_exist(store.inspections, id)
    return ok_object(store.public(insp))


@app.route("/credit-inspections", methods=["GET"])
def list_inspections():
    authenticate({"CreditInspector", "StormwaterAdmin"})
    bmp_credit_id = request.args.get("bmp_credit_id")
    status = request.args.get("status")
    rows = [
        i for i in store.inspections.values()
        if (bmp_credit_id is None or i["bmp_credit_id"] == bmp_credit_id)
        and (status is None or i["status"] == status)
    ]
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@app.route("/credit-inspections/<id>/complete", methods=["POST"])
def complete_inspection(id):
    authenticate({"CreditInspector"})
    insp = must_exist(store.inspections, id)
    body = get_body()
    require_fields(body, ["result", "observed_score"])
    require_enum(body["result"], {"PASS", "FAIL"}, "result")
    require_num_range(body["observed_score"], 0, 100, "observed_score")

    if insp["status"] != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_ALREADY_COMPLETED", 409,
                       "Inspection is not SCHEDULED.")
    credit = must_exist(store.bmp_credits, insp["bmp_credit_id"])
    if credit["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Credit is not ACTIVE.")

    insp["status"] = "COMPLETED"
    insp["result"] = body["result"]
    insp["observed_score"] = body["observed_score"]
    if "inspector_note" in body and body["inspector_note"] is not None:
        insp["inspector_note"] = body["inspector_note"]
    store.touch(insp)

    credit["inspected_score"] = body["observed_score"]
    if body["result"] == "PASS":
        credit["credit_pct"] = calc.credit_pct_from_score(body["observed_score"])
    else:
        credit["status"] = "REVOKED"
        credit["credit_pct"] = 0
    store.touch(credit)

    parcel = store.parcels.get(credit["parcel_id"])
    if parcel is not None:
        calc.recompute_parcel(parcel)
        store.touch(parcel)

    return ok_object(store.public(insp))


# ===========================================================================
# Bills
# ===========================================================================
def _compute_bill_fee(parcel, fee_variant):
    eru = parcel["billable_eru"]
    credit_pct = calc.parcel_credit_pct(parcel["id"])
    base = calc.base_fee_for_variant(eru, fee_variant)
    credit_amt = calc.credit_amount_cents(base, credit_pct)
    assessed = store.FIXED_CHARGE_CENTS + base - credit_amt
    return eru, base, credit_amt, assessed


@app.route("/bills", methods=["POST"])
def create_bill():
    authenticate({"BillingClerk"})
    body = get_body()
    parcel = exists_if_present(store.parcels, body, "parcel_id")
    account = exists_if_present(store.accounts, body, "account_id")
    require_fields(body, ["parcel_id", "account_id", "period_start", "period_end", "due_date"])
    fee_variant = body.get("fee_variant", "MARGINAL")
    if fee_variant is None:
        fee_variant = "MARGINAL"
    require_enum(fee_variant, FEE_VARIANTS, "fee_variant")
    ps = parse_input_dt(body, "period_start")
    pe = parse_input_dt(body, "period_end")
    parse_input_dt(body, "due_date")

    if parcel["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Parcel is not ACTIVE.")
    if body["account_id"] != parcel["account_id"]:
        raise ApiError("ERR_ACCOUNT_PARCEL_MISMATCH", 422,
                       "account_id does not match parcel.account_id.")
    if ps > pe:
        raise ApiError("ERR_INVALID_PERIOD", 422, "period_start after period_end.")

    for b in store.bills.values():
        if b["parcel_id"] == parcel["id"] and b["status"] != "VOID":
            b_ps = store.parse_dt(b["period_start"])
            b_pe = store.parse_dt(b["period_end"])
            # Closed [start, end]: overlap iff ps <= b_pe and b_ps <= pe.
            if ps <= b_pe and b_ps <= pe:
                raise ApiError("ERR_BILL_PERIOD_OVERLAP", 409,
                               "Bill period overlaps an existing non-VOID bill.")

    eru, base, credit_amt, assessed = _compute_bill_fee(parcel, fee_variant)
    bill = store.base_entity(common_fields=True)
    bill.update({
        "parcel_id": parcel["id"],
        "account_id": body["account_id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "due_date": body["due_date"],
        "fee_variant": fee_variant,
        "eru_snapshot": eru,
        "base_fee_cents": base,
        "fixed_charge_cents": store.FIXED_CHARGE_CENTS,
        "credit_amount_cents": credit_amt,
        "penalty_cents": 0,
        "assessed_fee_cents": assessed,
        "net_fee_cents": assessed,
        "amount_paid_cents": 0,
        "status": "ISSUED",
    })
    store.bills[bill["id"]] = bill

    calc.recompute_account(account, touch_delinquency=False)
    return ok_object(store.public(bill), 201)


@app.route("/bills/<id>", methods=["GET"])
def get_bill(id):
    uid, role = authenticate({"PropertyOwner", "BillingClerk", "StormwaterAdmin"})
    bill = must_exist(store.bills, id)
    check_ownership(role, uid, bill["account_id"])
    return ok_object(store.public(bill))


@app.route("/bills", methods=["GET"])
def list_bills():
    authenticate({"BillingClerk", "StormwaterAdmin"})
    parcel_id = request.args.get("parcel_id")
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    rows = [
        b for b in store.bills.values()
        if (parcel_id is None or b["parcel_id"] == parcel_id)
        and (account_id is None or b["account_id"] == account_id)
        and (status is None or b["status"] == status)
    ]
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@app.route("/bills/<id>/void", methods=["POST"])
def void_bill(id):
    authenticate({"BillingClerk", "StormwaterAdmin"})
    bill = must_exist(store.bills, id)
    if bill["status"] not in {"ISSUED", "PARTIALLY_PAID", "DELINQUENT"}:
        raise ApiError("ERR_INVALID_STATE", 409, "Bill is not in a voidable state.")
    for p in store.payments.values():
        if p["bill_id"] == bill["id"] and p["status"] == "APPLIED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Bill has an APPLIED payment; refund it first.")
    bill["status"] = "VOID"
    store.touch(bill)
    account = store.accounts.get(bill["account_id"])
    if account is not None:
        calc.recompute_account(account, touch_delinquency=True)
    return ok_object(store.public(bill))


# ===========================================================================
# Appeals
# ===========================================================================
def _reassess_bill(bill):
    parcel = store.parcels.get(bill["parcel_id"])
    if parcel is None:
        return
    was_delinquent = bill["status"] == "DELINQUENT"
    _eru, base, credit_amt, assessed = _compute_bill_fee(parcel, bill["fee_variant"])
    bill["eru_snapshot"] = parcel["billable_eru"]
    bill["base_fee_cents"] = base
    bill["credit_amount_cents"] = credit_amt
    bill["assessed_fee_cents"] = assessed
    if was_delinquent:
        bill["penalty_cents"] = calc.penalty_cents(assessed, bill["amount_paid_cents"])
    bill["net_fee_cents"] = assessed + bill["penalty_cents"]
    bill["status"] = "ADJUSTED"
    store.touch(bill)


@app.route("/appeals", methods=["POST"])
def create_appeal():
    uid, role = authenticate({"PropertyOwner", "StormwaterAdmin"})
    body = get_body()
    if role == "PropertyOwner" and body.get("account_id") is not None:
        check_ownership(role, uid, body["account_id"])
    parcel = exists_if_present(store.parcels, body, "parcel_id")
    exists_if_present(store.accounts, body, "account_id")
    bill = exists_if_present(store.bills, body, "bill_id")
    require_fields(body, ["parcel_id", "account_id", "grounds", "narrative"])
    require_enum(body["grounds"], APPEAL_GROUNDS, "grounds")

    if bill is not None and bill["parcel_id"] != parcel["id"]:
        raise ApiError("ERR_APPEAL_BILL_MISMATCH", 422,
                       "bill_id belongs to a different parcel.")

    appeal = store.base_entity(common_fields=True)
    appeal.update({
        "parcel_id": parcel["id"],
        "bill_id": body.get("bill_id"),
        "account_id": body["account_id"],
        "grounds": body["grounds"],
        "narrative": body["narrative"],
        "status": "SUBMITTED",
        "resolution_note": body.get("resolution_note"),
        "filed_by_user_id": uid,
    })
    store.appeals[appeal["id"]] = appeal
    return ok_object(store.public(appeal), 201)


@app.route("/appeals/<id>", methods=["GET"])
def get_appeal(id):
    uid, role = authenticate({"PropertyOwner", "StormwaterAdmin", "Assessor"})
    appeal = must_exist(store.appeals, id)
    check_ownership(role, uid, appeal["account_id"])
    return ok_object(store.public(appeal))


@app.route("/appeals", methods=["GET"])
def list_appeals():
    authenticate({"StormwaterAdmin", "Assessor"})
    parcel_id = request.args.get("parcel_id")
    bill_id = request.args.get("bill_id")
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    rows = [
        a for a in store.appeals.values()
        if (parcel_id is None or a["parcel_id"] == parcel_id)
        and (bill_id is None or a["bill_id"] == bill_id)
        and (account_id is None or a["account_id"] == account_id)
        and (status is None or a["status"] == status)
    ]
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@app.route("/appeals/<id>/review", methods=["POST"])
def review_appeal(id):
    authenticate({"StormwaterAdmin"})
    appeal = must_exist(store.appeals, id)
    if appeal["status"] != "SUBMITTED":
        raise ApiError("ERR_APPEAL_NOT_REVIEWABLE", 409, "Appeal is not SUBMITTED.")
    appeal["status"] = "UNDER_REVIEW"
    store.touch(appeal)
    return ok_object(store.public(appeal))


@app.route("/appeals/<id>/remeasure", methods=["POST"])
def remeasure_appeal(id):
    authenticate({"StormwaterAdmin"})
    appeal = must_exist(store.appeals, id)
    if appeal["status"] != "UNDER_REVIEW" or appeal["grounds"] != "MEASUREMENT_ERROR":
        raise ApiError("ERR_APPEAL_NOT_REVIEWABLE", 409,
                       "Appeal must be UNDER_REVIEW with MEASUREMENT_ERROR grounds.")
    appeal["status"] = "NEEDS_REMEASURE"
    store.touch(appeal)
    return ok_object(store.public(appeal))


@app.route("/appeals/<id>/decide", methods=["POST"])
def decide_appeal(id):
    authenticate({"StormwaterAdmin"})
    appeal = must_exist(store.appeals, id)
    body = get_body()
    require_fields(body, ["outcome"])
    require_enum(body["outcome"], {"UPHELD", "DENIED"}, "outcome")
    if appeal["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPEAL_NOT_REVIEWABLE", 409, "Appeal is not UNDER_REVIEW.")

    if "resolution_note" in body and body["resolution_note"] is not None:
        appeal["resolution_note"] = body["resolution_note"]

    if body["outcome"] == "UPHELD":
        appeal["status"] = "UPHELD"
        store.touch(appeal)
        if appeal["bill_id"] is not None:
            bill = store.bills.get(appeal["bill_id"])
            if bill is not None and bill["status"] in {"ISSUED", "PARTIALLY_PAID", "DELINQUENT"}:
                _reassess_bill(bill)
                account = store.accounts.get(bill["account_id"])
                if account is not None:
                    calc.recompute_account(account, touch_delinquency=True)
    else:
        appeal["status"] = "DENIED"
        store.touch(appeal)

    return ok_object(store.public(appeal))


# ===========================================================================
# Payments & Fund Ledger
# ===========================================================================
def _recompute_bill_status(bill):
    paid = bill["amount_paid_cents"]
    net = bill["net_fee_cents"]
    if paid <= 0:
        bill["status"] = "ISSUED"
    elif paid >= net:
        bill["status"] = "PAID"
    else:
        bill["status"] = "PARTIALLY_PAID"


def _write_ledger(payment_id, capital, operating, entry_type):
    for fund, amount in (("CAPITAL", capital), ("OPERATING", operating)):
        entry = store.base_entity(common_fields=False)
        entry.update({
            "source_payment_id": payment_id,
            "fund": fund,
            "amount_cents": amount,
            "entry_type": entry_type,
        })
        store.fund_ledger[entry["id"]] = entry


@app.route("/payments", methods=["POST"])
def create_payment():
    uid, role = authenticate({"PropertyOwner", "BillingClerk"})
    body = get_body()
    if role == "PropertyOwner" and body.get("account_id") is not None:
        check_ownership(role, uid, body["account_id"])
    bill = exists_if_present(store.bills, body, "bill_id")
    exists_if_present(store.accounts, body, "account_id")
    require_fields(body, ["bill_id", "account_id", "amount_cents", "method"])
    require_int_gt(body["amount_cents"], 0, "amount_cents")
    require_enum(body["method"], PAYMENT_METHODS, "method")

    if bill["status"] not in {"ISSUED", "PARTIALLY_PAID", "DELINQUENT"}:
        raise ApiError("ERR_BILL_NOT_PAYABLE", 409, "Bill is not payable.")
    if body["account_id"] != bill["account_id"]:
        raise ApiError("ERR_ACCOUNT_PARCEL_MISMATCH", 422,
                       "account_id does not match bill.account_id.")
    outstanding = bill["net_fee_cents"] - bill["amount_paid_cents"]
    if body["amount_cents"] > outstanding:
        raise ApiError("ERR_OVERPAYMENT", 422, "Payment exceeds bill outstanding.")

    payment = store.base_entity(common_fields=True)
    payment.update({
        "bill_id": bill["id"],
        "account_id": body["account_id"],
        "amount_cents": body["amount_cents"],
        "applied_amount_cents": body["amount_cents"],
        "method": body["method"],
        "status": "APPLIED",
        "created_by_user_id": uid,
    })
    store.payments[payment["id"]] = payment

    bill["amount_paid_cents"] += payment["applied_amount_cents"]
    _recompute_bill_status(bill)
    store.touch(bill)

    capital, operating = calc.fund_split(payment["applied_amount_cents"])
    _write_ledger(payment["id"], capital, operating, "ALLOCATION")

    account = store.accounts.get(bill["account_id"])
    if account is not None:
        calc.recompute_account(account, touch_delinquency=True)

    return ok_object(store.public(payment), 201)


@app.route("/payments/<id>", methods=["GET"])
def get_payment(id):
    uid, role = authenticate({"PropertyOwner", "BillingClerk", "StormwaterAdmin"})
    payment = must_exist(store.payments, id)
    check_ownership(role, uid, payment["account_id"])
    return ok_object(store.public(payment))


@app.route("/payments", methods=["GET"])
def list_payments():
    authenticate({"BillingClerk", "StormwaterAdmin"})
    bill_id = request.args.get("bill_id")
    account_id = request.args.get("account_id")
    rows = [
        p for p in store.payments.values()
        if (bill_id is None or p["bill_id"] == bill_id)
        and (account_id is None or p["account_id"] == account_id)
    ]
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@app.route("/payments/<id>/refund", methods=["POST"])
def refund_payment(id):
    uid, _role = authenticate({"BillingClerk"})
    payment = must_exist(store.payments, id)
    if payment["status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Payment is not APPLIED.")
    if uid == payment["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Refunder must differ from the payment creator.")

    payment["status"] = "REFUNDED"
    store.touch(payment)

    bill = store.bills.get(payment["bill_id"])
    if bill is not None:
        bill["amount_paid_cents"] -= payment["applied_amount_cents"]
        _recompute_bill_status(bill)
        store.touch(bill)
        account = store.accounts.get(bill["account_id"])
        if account is not None:
            calc.recompute_account(account, touch_delinquency=True)

    capital, operating = calc.fund_split(payment["applied_amount_cents"])
    _write_ledger(payment["id"], capital, operating, "REVERSAL")

    return ok_object(store.public(payment))


@app.route("/fund-ledger/<id>", methods=["GET"])
def get_fund_ledger_entry(id):
    authenticate({"BillingClerk", "StormwaterAdmin"})
    entry = must_exist(store.fund_ledger, id)
    return ok_object(store.public(entry))


@app.route("/fund-ledger", methods=["GET"])
def list_fund_ledger():
    authenticate({"BillingClerk", "StormwaterAdmin"})
    source_payment_id = request.args.get("source_payment_id")
    fund = request.args.get("fund")
    rows = [
        e for e in store.fund_ledger.values()
        if (source_payment_id is None or e["source_payment_id"] == source_payment_id)
        and (fund is None or e["fund"] == fund)
    ]
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


# ===========================================================================
# Operations cycle & logical clock
# ===========================================================================
def _credit_has_passing_inspection(credit_id):
    for i in store.inspections.values():
        if (i["bmp_credit_id"] == credit_id and i["status"] == "COMPLETED"
                and i["result"] == "PASS"):
            return True
    return False


@app.route("/billing/run-cycle", methods=["POST"])
def run_cycle():
    authenticate({"BillingClerk", "StormwaterAdmin"})
    clock = store.get_clock()
    grace = timedelta(days=store.GRACE_DAYS)

    bills_marked = 0
    for bill in store.bills.values():
        if bill["status"] not in {"ISSUED", "PARTIALLY_PAID"}:
            continue
        if bill["amount_paid_cents"] >= bill["net_fee_cents"]:
            continue
        try:
            due = store.parse_dt(bill["due_date"])
        except ValueError:
            continue
        if clock >= due + grace:
            penalty = calc.penalty_cents(bill["assessed_fee_cents"], bill["amount_paid_cents"])
            bill["penalty_cents"] = penalty
            bill["net_fee_cents"] = bill["assessed_fee_cents"] + penalty
            bill["status"] = "DELINQUENT"
            store.touch(bill)
            bills_marked += 1

    credits_expired = 0
    for credit in store.bmp_credits.values():
        if credit["status"] != "ACTIVE":
            continue
        if _credit_has_passing_inspection(credit["id"]):
            continue
        try:
            due = store.parse_dt(credit["next_inspection_due"])
        except (ValueError, KeyError):
            continue
        if clock >= due:
            credit["status"] = "EXPIRED"
            credit["credit_pct"] = 0
            store.touch(credit)
            parcel = store.parcels.get(credit["parcel_id"])
            if parcel is not None:
                calc.recompute_parcel(parcel)
                store.touch(parcel)
            credits_expired += 1

    for account in store.accounts.values():
        calc.recompute_account(account, touch_delinquency=True)

    return ok_object({
        "bills_marked_delinquent": bills_marked,
        "credits_expired": credits_expired,
    })


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate({"Assessor", "BillingClerk", "CreditInspector", "StormwaterAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    try:
        dt = store.parse_dt(body["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError("ERR_OUT_OF_RANGE", 422, "to_iso8601 is not a valid datetime.")
    store.set_clock(dt)
    return ok_object({"current_utc": store.fmt_dt(dt)})


def _count_routes():
    return len([r for r in app.url_map.iter_rules() if r.endpoint != "static"])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
