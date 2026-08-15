"""Payments, fundraising accounts/donations, and scholarship applications."""
from store import DB
from util import (
    ApiError, success_object, success_list, get_body, req_str, opt_str, req_int, req_enum,
)
import domain as D
from web import (
    app, PREFIX, caller, require_role, paginate,
    get_registration, get_account, get_donation, get_payment, get_application, get_trip,
    guardian_owns_or_403,
)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

@app.post(f"{PREFIX}/registrations/<rid>/payments")
def create_payment(rid):
    uid, role = caller()
    body = get_body()
    amount = req_int(body, "amount_cents", min_value=1)
    method = req_enum(body, "method", D.PAYMENT_METHODS)
    require_role(role, ["Treasurer", "Guardian"])
    reg = get_registration(rid)
    guardian_owns_or_403(uid, role, reg["guardian_user_id"])
    if reg["registration_status"] not in ("APPROVED", "CONFIRMED"):
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION",
                       "Registration must be APPROVED or CONFIRMED", 409)
    trip = get_trip(reg["trip_id"])
    payment = {
        "registration_id": rid,
        "amount_cents": amount,
        "method": method,
        "status": "POSTED",
        "posted_at": DB.clock_string(),
    }
    DB.stamp_created(payment)
    DB.payments[payment["id"]] = payment
    D.registration_money(reg, trip, update_status=True)
    return success_object(D.ser_payment(payment), 201)


@app.get(f"{PREFIX}/registrations/<rid>/payments")
def list_payments(rid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "Treasurer", "Guardian"])
    reg = get_registration(rid)
    guardian_owns_or_403(uid, role, reg["guardian_user_id"])
    return paginate(D.payments_of_registration(rid), D.ser_payment)


@app.post(f"{PREFIX}/payments/<pid>/refund")
def refund_payment(pid):
    uid, role = caller()
    require_role(role, ["Treasurer"])
    payment = get_payment(pid)
    if payment["status"] != "POSTED":
        raise ApiError("ERR_PAYMENT_STATE_FORBIDS_ACTION", "Payment is not POSTED", 409)
    payment["status"] = "REFUNDED"
    DB.touch("payments", payment["id"])
    reg = get_registration(payment["registration_id"])
    trip = get_trip(reg["trip_id"])
    D.registration_money(reg, trip, update_status=True)
    return success_object(D.ser_payment(payment))


# ---------------------------------------------------------------------------
# Fundraising accounts and donations
# ---------------------------------------------------------------------------

@app.get(f"{PREFIX}/registrations/<rid>/fundraising-account")
def read_registration_account(rid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "Treasurer", "Guardian"])
    reg = get_registration(rid)
    guardian_owns_or_403(uid, role, reg["guardian_user_id"])
    account = D.account_of_registration(rid)
    items = [account] if account is not None else []
    return success_list([D.ser_account(a) for a in items], 10, 0, len(items))


@app.get(f"{PREFIX}/fundraising-accounts/<aid>")
def read_account(aid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "Treasurer", "Guardian"])
    account = get_account(aid)
    reg = get_registration(account["registration_id"])
    guardian_owns_or_403(uid, role, reg["guardian_user_id"])
    return success_object(D.ser_account(account))


@app.post(f"{PREFIX}/fundraising-accounts/<aid>/donations")
def create_donation(aid):
    uid, role = caller()
    body = get_body()
    donor_name = req_str(body, "donor_name")
    amount = req_int(body, "amount_cents", min_value=1)
    channel = req_enum(body, "channel", D.PAYMENT_METHODS)
    require_role(role, ["Treasurer"])
    account = get_account(aid)
    if account["status"] != "OPEN":
        raise ApiError("ERR_ACCOUNT_CLOSED", "Fundraising account is CLOSED", 409)
    donation = {
        "fundraising_account_id": aid,
        "donor_name": donor_name,
        "amount_cents": amount,
        "channel": channel,
        "fee_cents": D.donation_fee(channel, amount),
        "status": "RECEIVED",
        "received_at": DB.clock_string(),
    }
    DB.stamp_created(donation)
    DB.donations[donation["id"]] = donation
    D.recompute_account(account)
    return success_object(D.ser_donation(donation), 201)


@app.get(f"{PREFIX}/fundraising-accounts/<aid>/donations")
def list_donations(aid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "Treasurer"])
    account = get_account(aid)
    return paginate(D.donations_of_account(aid), D.ser_donation)


@app.post(f"{PREFIX}/donations/<did>/refund")
def refund_donation(did):
    uid, role = caller()
    require_role(role, ["Treasurer"])
    donation = get_donation(did)
    if donation["status"] != "RECEIVED":
        raise ApiError("ERR_DONATION_STATE_FORBIDS_ACTION", "Donation is not RECEIVED", 409)
    donation["status"] = "REFUNDED"
    DB.touch("donations", donation["id"])
    account = get_account(donation["fundraising_account_id"])
    D.recompute_account(account)
    return success_object(D.ser_donation(donation))


@app.post(f"{PREFIX}/fundraising-accounts/<aid>/apply-credit")
def apply_credit(aid):
    uid, role = caller()
    require_role(role, ["Treasurer"])
    account = get_account(aid)
    reg = get_registration(account["registration_id"])
    if reg["registration_status"] not in ("APPROVED", "CONFIRMED"):
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION",
                       "Registration must be APPROVED or CONFIRMED", 409)
    if account["status"] != "OPEN":
        raise ApiError("ERR_ACCOUNT_CLOSED", "Fundraising account is CLOSED", 409)
    D.recompute_account(account)
    if account["available_credit_cents"] <= 0:
        raise ApiError("ERR_NO_CREDIT_AVAILABLE", "No fundraising credit is available", 422)
    delta = account["available_credit_cents"]
    account["credit_applied_cents"] = account["raised_net_cents"]
    DB.touch("fundraising_accounts", account["id"])
    D.recompute_account(account)
    reg["fundraising_credit_applied_cents"] += delta
    trip = get_trip(reg["trip_id"])
    D.registration_money(reg, trip, update_status=True)
    for donation in D.donations_of_account(aid):
        if donation["status"] == "RECEIVED":
            donation["status"] = "APPLIED"
            DB.touch("donations", donation["id"])
    return success_object(D.ser_account(account))


# ---------------------------------------------------------------------------
# Scholarship applications
# ---------------------------------------------------------------------------

@app.post(f"{PREFIX}/scholarship-applications")
def create_application():
    uid, role = caller()
    body = get_body()
    registration_id = req_str(body, "registration_id")
    requested = req_int(body, "requested_cents", min_value=1)
    require_role(role, ["ProgramDirector", "Guardian"])
    reg = get_registration(registration_id)
    guardian_owns_or_403(uid, role, reg["guardian_user_id"])
    if reg["registration_status"] not in ("APPROVED", "CONFIRMED"):
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION",
                       "Registration must be APPROVED or CONFIRMED", 409)
    for other in D.applications_of_registration(registration_id):
        if other["status"] in ("UNDER_REVIEW", "APPROVED"):
            raise ApiError("ERR_DUPLICATE_ACTIVE_APPLICATION",
                           "An application in UNDER_REVIEW or APPROVED already exists", 409)
    application = {
        "registration_id": registration_id,
        "requested_cents": requested,
        "need_score": D.compute_need_score(reg),
        "award_cents": 0,
        "status": "UNDER_REVIEW",
        "approved_by_user_id": "",
        "disbursed_by_user_id": "",
        "decision_reason": "",
    }
    DB.stamp_created(application)
    DB.scholarship_applications[application["id"]] = application
    return success_object(D.ser_application(application), 201)


@app.get(f"{PREFIX}/scholarship-applications")
def list_applications():
    uid, role = caller()
    require_role(role, ["ProgramDirector", "ScholarshipReviewer", "Treasurer"])
    items = list(DB.scholarship_applications.values())
    from flask import request
    registration_id = request.args.get("registration_id")
    status = request.args.get("status")
    if registration_id is not None:
        items = [a for a in items if a["registration_id"] == registration_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate(items, D.ser_application)


@app.get(f"{PREFIX}/scholarship-applications/<aid>")
def read_application(aid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "ScholarshipReviewer", "Treasurer", "Guardian"])
    application = get_application(aid)
    reg = get_registration(application["registration_id"])
    guardian_owns_or_403(uid, role, reg["guardian_user_id"])
    return success_object(D.ser_application(application))


@app.post(f"{PREFIX}/scholarship-applications/<aid>/decide")
def decide_application(aid):
    uid, role = caller()
    body = get_body()
    decision = req_enum(body, "decision", ["APPROVE", "DENY"])
    reason = opt_str(body, "reason", "")
    require_role(role, ["ScholarshipReviewer"])
    application = get_application(aid)
    reg = get_registration(application["registration_id"])
    if decision == "APPROVE":
        if uid == reg["guardian_user_id"]:
            raise ApiError("ERR_SOD_VIOLATION",
                           "Decide actor must differ from the registration's guardian", 403)
    if application["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPLICATION_STATE_FORBIDS_ACTION", "Application is not UNDER_REVIEW", 409)
    if decision == "DENY":
        application["need_score"] = D.compute_need_score(reg)
        application["decision_reason"] = reason
        application["status"] = "DENIED"
        DB.touch("scholarship_applications", application["id"])
        return success_object(D.ser_application(application))

    # APPROVE gate chain
    if reg["registration_status"] not in ("APPROVED", "CONFIRMED"):
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION",
                       "Registration must be APPROVED or CONFIRMED", 409)
    trip = get_trip(reg["trip_id"])
    program = DB.programs.get(trip["program_id"])
    D.recompute_program_fund(program)
    if program["scholarship_available_cents"] <= 0:
        raise ApiError("ERR_SCHOLARSHIP_FUND_EXHAUSTED", "Scholarship fund is exhausted", 402)
    need_score, award = D.compute_award_cents(application, reg, trip, program)
    if award <= 0:
        raise ApiError("ERR_AWARD_WOULD_BE_ZERO", "Computed award would be zero", 422)
    application["need_score"] = need_score
    application["award_cents"] = award
    application["approved_by_user_id"] = uid
    application["status"] = "APPROVED"
    DB.touch("scholarship_applications", application["id"])
    D.recompute_program_fund(program)
    return success_object(D.ser_application(application))


@app.post(f"{PREFIX}/scholarship-applications/<aid>/appeal")
def appeal_application(aid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "Guardian"])
    application = get_application(aid)
    reg = get_registration(application["registration_id"])
    guardian_owns_or_403(uid, role, reg["guardian_user_id"])
    if application["status"] != "DENIED":
        raise ApiError("ERR_APPLICATION_STATE_FORBIDS_ACTION", "Application is not DENIED", 409)
    if reg["registration_status"] not in ("APPROVED", "CONFIRMED"):
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION",
                       "Registration must be APPROVED or CONFIRMED", 409)
    application["status"] = "UNDER_REVIEW"
    application["decision_reason"] = ""
    DB.touch("scholarship_applications", application["id"])
    return success_object(D.ser_application(application))


@app.post(f"{PREFIX}/scholarship-applications/<aid>/disburse")
def disburse_application(aid):
    uid, role = caller()
    require_role(role, ["Treasurer"])
    application = get_application(aid)
    reg = get_registration(application["registration_id"])
    if uid == application["approved_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", "Disburser must differ from the approver", 403)
    if application["status"] != "APPROVED":
        raise ApiError("ERR_APPLICATION_STATE_FORBIDS_ACTION", "Application is not APPROVED", 409)
    if reg["registration_status"] not in ("APPROVED", "CONFIRMED"):
        raise ApiError("ERR_REGISTRATION_STATE_FORBIDS_ACTION",
                       "Registration must be APPROVED or CONFIRMED", 409)
    trip = get_trip(reg["trip_id"])
    program = DB.programs.get(trip["program_id"])
    application["status"] = "DISBURSED"
    application["disbursed_by_user_id"] = uid
    DB.touch("scholarship_applications", application["id"])
    D.recompute_program_fund(program)
    reg["scholarship_awarded_cents"] = application["award_cents"]
    D.registration_money(reg, trip, update_status=True)
    return success_object(D.ser_application(application))


@app.post(f"{PREFIX}/scholarship-applications/<aid>/rescind")
def rescind_application(aid):
    uid, role = caller()
    body = get_body()
    reason = opt_str(body, "reason", "")
    require_role(role, ["ScholarshipReviewer"])
    application = get_application(aid)
    if application["status"] != "APPROVED":
        raise ApiError("ERR_APPLICATION_STATE_FORBIDS_ACTION", "Application is not APPROVED", 409)
    reg = get_registration(application["registration_id"])
    trip = get_trip(reg["trip_id"])
    program = DB.programs.get(trip["program_id"])
    application["status"] = "RESCINDED"
    application["decision_reason"] = reason
    DB.touch("scholarship_applications", application["id"])
    D.recompute_program_fund(program)
    return success_object(D.ser_application(application))
