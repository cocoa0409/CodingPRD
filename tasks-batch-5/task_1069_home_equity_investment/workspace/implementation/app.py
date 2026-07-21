"""Home-Equity Investment (Point/Hometap style) REST API — Flask app."""

import os

from flask import Flask, request

import core
from core import (
    DB,
    ApiError,
    D,
    add_months,
    base_record,
    error_body,
    floor_cents,
    fund_committed,
    get_clock,
    iso_format,
    parse_dt,
    round_half_up,
    set_clock,
    success_array,
    success_object,
    touch,
    whole_calendar_months,
)

app = Flask(__name__)

# ==========================================================================
# Constants
# ==========================================================================
MAX_COMBINED_LTV = D("0.75")
LOW_MAX = D("0.50")
MODERATE_MAX = D("0.65")
INVESTMENT_LTV_CAP = D("0.30")
ORIGINATION_FEE_PCT = D("0.03")
SERVICING_FEE_PCT = D("0.01")
ADMIN_FLAT_CENTS = 50000
APPRAISER_BUFFER_MINUTES = 60

NOT_FOUND = {
    "funds": ("ERR_FUND_NOT_FOUND", 404),
    "homeowners": ("ERR_HOMEOWNER_NOT_FOUND", 404),
    "applications": ("ERR_APPLICATION_NOT_FOUND", 404),
    "valuations": ("ERR_VALUATION_NOT_FOUND", 404),
    "appraisers": ("ERR_APPRAISER_NOT_FOUND", 404),
    "appointments": ("ERR_APPOINTMENT_NOT_FOUND", 404),
    "offers": ("ERR_OFFER_NOT_FOUND", 404),
    "agreements": ("ERR_AGREEMENT_NOT_FOUND", 404),
    "liens": ("ERR_LIEN_NOT_FOUND", 404),
    "inspectors": ("ERR_INSPECTOR_NOT_FOUND", 404),
    "inspections": ("ERR_INSPECTION_NOT_FOUND", 404),
    "settlements": ("ERR_SETTLEMENT_NOT_FOUND", 404),
    "disputes": ("ERR_DISPUTE_NOT_FOUND", 404),
}


# ==========================================================================
# Error handling
# ==========================================================================
@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_body(err.error_id, err.message), err.http_status


@app.errorhandler(404)
def _handle_404(_e):
    return error_body("ERR_VALIDATION", "No such route"), 404


@app.errorhandler(405)
def _handle_405(_e):
    return error_body("ERR_VALIDATION", "Method not allowed"), 405


@app.errorhandler(Exception)
def _handle_uncaught(err):
    if isinstance(err, ApiError):
        return error_body(err.error_id, err.message), err.http_status
    return error_body("ERR_INTERNAL", str(err)), 500


# ==========================================================================
# Auth / RBAC helpers
# ==========================================================================
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in core.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid credentials")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint")


def require_owner(homeowner_id, user_id):
    if homeowner_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the resource owner")


# ==========================================================================
# Lookup / body helpers
# ==========================================================================
def fetch(collection, rid):
    rec = DB[collection].get(rid)
    if rec is None:
        err_id, http = NOT_FOUND[collection]
        raise ApiError(err_id, http, f"{collection[:-1]} not found")
    return rec


def get_body():
    if request.method in ("GET", "DELETE"):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # Allow empty body for action endpoints with no input.
        if not request.data:
            return {}
        raise ApiError("ERR_VALIDATION", 400, "Malformed JSON body")
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Body must be a JSON object")
    return data


def require_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {name}")
    return body[name]


def require_int(body, name):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_VALIDATION", 400, f"Field {name} must be an integer")
    return val


def require_number(body, name):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, f"Field {name} must be a number")
    return val


def require_str(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise ApiError("ERR_VALIDATION", 400, f"Field {name} must be a non-empty string")
    return val


def require_enum(body, name, choices):
    val = require_field(body, name)
    if val not in choices:
        raise ApiError("ERR_VALIDATION", 400, f"Field {name} must be one of {choices}")
    return val


# ==========================================================================
# Pagination / listing
# ==========================================================================
def get_pagination():
    args = request.args
    limit, offset = 10, 0
    if args.get("limit") is not None:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if args.get("offset") is not None:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def list_response(collection, serializer, predicate):
    limit, offset = get_pagination()
    records = [r for r in DB[collection].values() if predicate(r)]
    records.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(records)
    page = records[offset : offset + limit]
    return success_array([serializer(r) for r in page], limit, offset, total)


def _filter_match(rec, args, key, field=None):
    field = field or key
    want = args.get(key)
    if want is None:
        return True
    return str(rec.get(field)) == want


# ==========================================================================
# Logical clock
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    _uid, role = authenticate()
    require_roles(role, ["InvestmentAnalyst", "ClosingAgent", "ComplianceOfficer"])
    body = get_body()
    raw = require_field(body, "to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 must be an ISO-8601 instant")
    set_clock(dt)
    return success_object({})


# ==========================================================================
# Fund
# ==========================================================================
@app.route("/hei/funds", methods=["POST"])
def create_fund():
    _uid, role = authenticate()
    require_roles(role, ["InvestmentAnalyst"])
    body = get_body()
    name = require_str(body, "name")
    total = require_int(body, "total_capital_cents")
    rec = base_record()
    rec.update({"name": name, "total_capital_cents": total})
    DB["funds"][rec["id"]] = rec
    return success_object(core.ser_fund(rec), 201)


@app.route("/hei/funds/<rid>", methods=["GET"])
def get_fund(rid):
    _uid, _role = authenticate()
    rec = fetch("funds", rid)
    return success_object(core.ser_fund(rec))


# ==========================================================================
# Homeowner
# ==========================================================================
@app.route("/hei/homeowners", methods=["POST"])
def create_homeowner():
    _uid, role = authenticate()
    require_roles(role, ["InvestmentAnalyst"])
    body = get_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    rec = base_record()
    rec.update({"email": email, "full_name": full_name})
    DB["homeowners"][rec["id"]] = rec
    return success_object(core.ser_homeowner(rec), 201)


@app.route("/hei/homeowners/<rid>", methods=["GET"])
def get_homeowner(rid):
    _uid, _role = authenticate()
    rec = fetch("homeowners", rid)
    return success_object(core.ser_homeowner(rec))


# ==========================================================================
# Application
# ==========================================================================
PROPERTY_TYPES = ["SINGLE_FAMILY", "CONDO", "TOWNHOUSE", "MULTI_UNIT"]


def app_homeowner_id(application):
    return application["homeowner_id"]


def completed_valuations(application_id):
    return [
        v
        for v in DB["valuations"].values()
        if v["application_id"] == application_id and v["status"] == "COMPLETED"
    ]


def latest_completed_valuation(application_id):
    vals = completed_valuations(application_id)
    if not vals:
        return None
    return max(vals, key=lambda v: (v["created_at"], v["_seq"]))


@app.route("/hei/applications", methods=["POST"])
def create_application():
    uid, role = authenticate()
    require_roles(role, ["Homeowner"])
    body = get_body()
    homeowner_id = require_str(body, "homeowner_id")
    fund_id = require_str(body, "fund_id")
    property_address = require_str(body, "property_address")
    property_type = require_enum(body, "property_type", PROPERTY_TYPES)
    est_value = require_int(body, "homeowner_estimated_value_cents")
    mortgage = require_int(body, "existing_mortgage_balance_cents")
    requested = require_int(body, "requested_investment_cents")
    # ownership (priority 4): the applicant must be the acting homeowner
    require_owner(homeowner_id, uid)
    # body FK existence (priority 5)
    fetch("funds", fund_id)
    fetch("homeowners", homeowner_id)
    rec = base_record()
    rec.update(
        {
            "homeowner_id": homeowner_id,
            "fund_id": fund_id,
            "property_address": property_address,
            "property_type": property_type,
            "homeowner_estimated_value_cents": est_value,
            "existing_mortgage_balance_cents": mortgage,
            "requested_investment_cents": requested,
            "status": "DRAFT",
            "combined_ltv": None,
            "risk_band": None,
        }
    )
    DB["applications"][rec["id"]] = rec
    return success_object(core.ser_application(rec), 201)


@app.route("/hei/applications/<rid>", methods=["GET"])
def get_application(rid):
    _uid, _role = authenticate()
    rec = fetch("applications", rid)
    return success_object(core.ser_application(rec))


@app.route("/hei/applications", methods=["GET"])
def list_applications():
    _uid, _role = authenticate()
    args = request.args

    def pred(r):
        return (
            _filter_match(r, args, "homeowner_id")
            and _filter_match(r, args, "fund_id")
            and _filter_match(r, args, "status")
        )

    return list_response("applications", core.ser_application, pred)


@app.route("/hei/applications/<rid>/submit", methods=["POST"])
def submit_application(rid):
    uid, role = authenticate()
    require_roles(role, ["Homeowner"])
    rec = fetch("applications", rid)
    require_owner(app_homeowner_id(rec), uid)
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not DRAFT")
    if not completed_valuations(rid):
        raise ApiError(
            "ERR_NO_COMPLETED_VALUATION", 409, "No COMPLETED valuation exists"
        )
    rec["status"] = "UNDER_REVIEW"
    touch(rec)
    return success_object(core.ser_application(rec))


@app.route("/hei/applications/<rid>/decision", methods=["POST"])
def decide_application(rid):
    _uid, role = authenticate()
    require_roles(role, ["InvestmentAnalyst"])
    rec = fetch("applications", rid)
    body = get_body()
    decision = require_enum(body, "decision", ["APPROVE", "DECLINE"])
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not UNDER_REVIEW")
    if decision == "DECLINE":
        rec["status"] = "DECLINED"
        touch(rec)
        return success_object(core.ser_application(rec))
    # APPROVE
    basis = latest_completed_valuation(rid)
    if basis is None:
        raise ApiError(
            "ERR_NO_COMPLETED_VALUATION", 409, "No COMPLETED valuation exists"
        )
    from fractions import Fraction

    numerator = rec["requested_investment_cents"] + rec["existing_mortgage_balance_cents"]
    denom = basis["valued_amount_cents"]
    ratio = Fraction(numerator, denom)
    if ratio > Fraction(3, 4):  # MAX_COMBINED_LTV = 0.75, inclusive
        raise ApiError("ERR_LTV_EXCEEDED", 422, "combined_ltv exceeds ceiling")
    if ratio <= Fraction(1, 2):
        band = "LOW"
    elif ratio <= Fraction(13, 20):  # 0.65
        band = "MODERATE"
    else:
        band = "ELEVATED"
    rec["combined_ltv"] = numerator / denom
    rec["risk_band"] = band
    rec["status"] = "APPROVED"
    touch(rec)
    return success_object(core.ser_application(rec))


@app.route("/hei/applications/<rid>/withdraw", methods=["POST"])
def withdraw_application(rid):
    uid, role = authenticate()
    require_roles(role, ["Homeowner"])
    rec = fetch("applications", rid)
    require_owner(app_homeowner_id(rec), uid)
    if rec["status"] not in ("DRAFT", "UNDER_REVIEW", "APPROVED", "OFFERED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Application cannot be withdrawn")
    # From OFFERED: only if no offer accepted (guaranteed, since acceptance
    # would have moved the application to FUNDED). Sibling PRESENTED offers
    # are withdrawn, releasing their held capital.
    if rec["status"] == "OFFERED":
        for o in DB["offers"].values():
            if o["application_id"] == rid and o["status"] == "PRESENTED":
                o["status"] = "WITHDRAWN"
                touch(o)
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return success_object(core.ser_application(rec))


# ==========================================================================
# Valuation
# ==========================================================================
def supersede_same_method(application_id, method, exclude_id):
    for v in DB["valuations"].values():
        if (
            v["application_id"] == application_id
            and v["method"] == method
            and v["status"] == "COMPLETED"
            and v["id"] != exclude_id
        ):
            v["status"] = "SUPERSEDED"
            touch(v)


@app.route("/hei/applications/<rid>/valuations", methods=["POST"])
def create_valuation(rid):
    _uid, role = authenticate()
    require_roles(role, ["InvestmentAnalyst"])
    application = fetch("applications", rid)
    body = get_body()
    method = require_enum(body, "method", ["AVM", "APPRAISAL"])
    confidence = body.get("confidence_score")
    rec = base_record()
    if method == "AVM":
        valued = require_int(body, "valued_amount_cents")
        rec.update(
            {
                "application_id": application["id"],
                "method": "AVM",
                "valued_amount_cents": valued,
                "confidence_score": confidence,
                "source_appointment_id": None,
                "status": "COMPLETED",
            }
        )
        DB["valuations"][rec["id"]] = rec
        supersede_same_method(application["id"], "AVM", rec["id"])
    else:
        rec.update(
            {
                "application_id": application["id"],
                "method": "APPRAISAL",
                "valued_amount_cents": 0,
                "confidence_score": None,
                "source_appointment_id": None,
                "status": "PENDING",
            }
        )
        DB["valuations"][rec["id"]] = rec
    return success_object(core.ser_valuation(rec), 201)


@app.route("/hei/valuations/<rid>", methods=["GET"])
def get_valuation(rid):
    _uid, _role = authenticate()
    rec = fetch("valuations", rid)
    return success_object(core.ser_valuation(rec))


@app.route("/hei/valuations", methods=["GET"])
def list_valuations():
    _uid, _role = authenticate()
    args = request.args

    def pred(r):
        return (
            _filter_match(r, args, "application_id")
            and _filter_match(r, args, "source_appointment_id")
            and _filter_match(r, args, "method")
            and _filter_match(r, args, "status")
        )

    return list_response("valuations", core.ser_valuation, pred)


# ==========================================================================
# Appraiser
# ==========================================================================
@app.route("/hei/appraisers", methods=["POST"])
def create_appraiser():
    _uid, role = authenticate()
    require_roles(role, ["InvestmentAnalyst"])
    body = get_body()
    full_name = require_str(body, "full_name")
    region_code = require_str(body, "region_code")
    rec = base_record()
    rec.update({"full_name": full_name, "region_code": region_code})
    DB["appraisers"][rec["id"]] = rec
    return success_object(core.ser_appraiser(rec), 201)


@app.route("/hei/appraisers/<rid>", methods=["GET"])
def get_appraiser(rid):
    _uid, _role = authenticate()
    rec = fetch("appraisers", rid)
    return success_object(core.ser_appraiser(rec))


# ==========================================================================
# AppraisalAppointment
# ==========================================================================
@app.route("/hei/appraisal-appointments", methods=["POST"])
def create_appointment():
    _uid, role = authenticate()
    require_roles(role, ["InvestmentAnalyst"])
    body = get_body()
    appraiser_id = require_str(body, "appraiser_id")
    valuation_id = require_str(body, "valuation_id")
    region_code = require_str(body, "region_code")
    start_raw = require_str(body, "scheduled_start")
    end_raw = require_str(body, "scheduled_end")
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)
    if start_dt is None or end_dt is None:
        raise ApiError("ERR_VALIDATION", 400, "scheduled_start/scheduled_end invalid")
    # body FK existence (priority 5)
    appraiser = fetch("appraisers", appraiser_id)
    valuation = fetch("valuations", valuation_id)
    # cross-entity prerequisites (priority 9)
    if not (valuation["method"] == "APPRAISAL" and valuation["status"] == "PENDING"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Valuation must be a PENDING APPRAISAL"
        )
    if region_code != appraiser["region_code"]:
        raise ApiError(
            "ERR_APPRAISER_REGION_MISMATCH", 409, "Region does not match appraiser"
        )
    # temporal overlap (priority 10): buffer against other SCHEDULED appointments
    buffer_secs = APPRAISER_BUFFER_MINUTES * 60
    for a in DB["appointments"].values():
        if a["appraiser_id"] != appraiser_id or a["status"] != "SCHEDULED":
            continue
        a_start = parse_dt(a["scheduled_start"])
        a_end = parse_dt(a["scheduled_end"])
        # conflict unless the windows are separated by >= buffer
        separated = (
            (start_dt - a_end).total_seconds() >= buffer_secs
            or (a_start - end_dt).total_seconds() >= buffer_secs
        )
        if not separated:
            raise ApiError(
                "ERR_APPRAISER_DOUBLE_BOOKED", 409, "Appraiser is double-booked"
            )
    # constraint gate (priority 11): time-range validity
    if not (end_dt > start_dt):
        raise ApiError(
            "ERR_INVALID_TIME_RANGE", 400, "scheduled_end must be after scheduled_start"
        )
    rec = base_record()
    rec.update(
        {
            "appraiser_id": appraiser_id,
            "valuation_id": valuation_id,
            "region_code": region_code,
            "scheduled_start": start_raw,
            "scheduled_end": end_raw,
            "status": "SCHEDULED",
        }
    )
    DB["appointments"][rec["id"]] = rec
    return success_object(core.ser_appointment(rec), 201)


@app.route("/hei/appraisal-appointments/<rid>", methods=["GET"])
def get_appointment(rid):
    _uid, _role = authenticate()
    rec = fetch("appointments", rid)
    return success_object(core.ser_appointment(rec))


@app.route("/hei/appraisal-appointments", methods=["GET"])
def list_appointments():
    _uid, _role = authenticate()
    args = request.args

    def pred(r):
        return (
            _filter_match(r, args, "appraiser_id")
            and _filter_match(r, args, "valuation_id")
            and _filter_match(r, args, "status")
        )

    return list_response("appointments", core.ser_appointment, pred)


@app.route("/hei/appraisal-appointments/<rid>/complete", methods=["POST"])
def complete_appointment(rid):
    _uid, role = authenticate()
    require_roles(role, ["Appraiser"])
    rec = fetch("appointments", rid)
    body = get_body()
    valued = require_int(body, "valued_amount_cents")
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Appointment is not SCHEDULED")
    valuation = DB["valuations"].get(rec["valuation_id"])
    if valuation is None or valuation["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Linked valuation is not PENDING")
    rec["status"] = "COMPLETED"
    touch(rec)
    valuation["valued_amount_cents"] = valued
    valuation["source_appointment_id"] = rec["id"]
    valuation["status"] = "COMPLETED"
    touch(valuation)
    supersede_same_method(valuation["application_id"], "APPRAISAL", valuation["id"])
    return success_object(core.ser_appointment(rec))


@app.route("/hei/appraisal-appointments/<rid>/cancel", methods=["POST"])
def cancel_appointment(rid):
    _uid, role = authenticate()
    require_roles(role, ["InvestmentAnalyst"])
    rec = fetch("appointments", rid)
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Appointment is not SCHEDULED")
    rec["status"] = "CANCELLED"
    touch(rec)
    return success_object(core.ser_appointment(rec))


# ==========================================================================
# Offer
# ==========================================================================
def fund_available(fund_id):
    fund = DB["funds"][fund_id]
    return fund["total_capital_cents"] - fund_committed(fund_id)


def compute_adjusted_start_value(valued, risk_adj):
    return round_half_up(D(valued) * (D(1) - D(risk_adj)))


def offer_owner_homeowner(offer):
    application = DB["applications"][offer["application_id"]]
    return application["homeowner_id"]


@app.route("/hei/applications/<rid>/offers", methods=["POST"])
def create_offer(rid):
    _uid, role = authenticate()
    require_roles(role, ["InvestmentAnalyst"])
    application = fetch("applications", rid)
    body = get_body()
    valuation_id = require_str(body, "valuation_id")
    investment = require_int(body, "investment_amount_cents")
    option_pct = require_number(body, "option_percentage")
    risk_adj = require_number(body, "risk_adjustment_pct")
    term_months = require_int(body, "term_months")
    capped_rate = require_number(body, "capped_annual_rate")
    expires_raw = require_str(body, "expires_at")
    if parse_dt(expires_raw) is None:
        raise ApiError("ERR_VALIDATION", 400, "expires_at invalid")
    # body FK existence (priority 5)
    valuation = fetch("valuations", valuation_id)
    # state (priority 6)
    if application["status"] not in ("APPROVED", "OFFERED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Application not APPROVED/OFFERED")
    # cross-entity (priority 9): basis valuation must be COMPLETED
    if valuation["status"] != "COMPLETED":
        raise ApiError(
            "ERR_VALUATION_NOT_COMPLETED", 409, "Basis valuation is not COMPLETED"
        )
    # fiscal gates (priority 12)
    max_investment = floor_cents(INVESTMENT_LTV_CAP * D(valuation["valued_amount_cents"]))
    if investment > max_investment:
        raise ApiError(
            "ERR_INVESTMENT_EXCEEDS_LTV_CAP", 422, "Investment exceeds LTV cap"
        )
    if investment > fund_available(application["fund_id"]):
        raise ApiError(
            "ERR_INSUFFICIENT_FUND_CAPITAL", 422, "Insufficient available fund capital"
        )
    rec = base_record()
    rec.update(
        {
            "application_id": application["id"],
            "fund_id": application["fund_id"],
            "valuation_id": valuation_id,
            "investment_amount_cents": investment,
            "option_percentage": option_pct,
            "risk_adjustment_pct": risk_adj,
            "term_months": term_months,
            "capped_annual_rate": capped_rate,
            "expires_at": expires_raw,
            "adjusted_start_value_cents": compute_adjusted_start_value(
                valuation["valued_amount_cents"], risk_adj
            ),
            "status": "PRESENTED",
            "counter_notes": None,
        }
    )
    DB["offers"][rec["id"]] = rec
    if application["status"] == "APPROVED":
        application["status"] = "OFFERED"
        touch(application)
    return success_object(core.ser_offer(rec), 201)


@app.route("/hei/offers/<rid>", methods=["GET"])
def get_offer(rid):
    _uid, _role = authenticate()
    rec = fetch("offers", rid)
    return success_object(core.ser_offer(rec))


@app.route("/hei/offers", methods=["GET"])
def list_offers():
    _uid, _role = authenticate()
    args = request.args

    def pred(r):
        return (
            _filter_match(r, args, "application_id")
            and _filter_match(r, args, "fund_id")
            and _filter_match(r, args, "valuation_id")
            and _filter_match(r, args, "status")
        )

    return list_response("offers", core.ser_offer, pred)


@app.route("/hei/offers/<rid>/accept", methods=["POST"])
def accept_offer(rid):
    uid, role = authenticate()
    require_roles(role, ["Homeowner"])
    offer = fetch("offers", rid)
    require_owner(offer_owner_homeowner(offer), uid)
    application = DB["applications"][offer["application_id"]]
    # state (priority 6)
    if offer["status"] != "PRESENTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Offer is not PRESENTED")
    if application["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not OFFERED")
    # constraint gate (priority 11): offer expiry
    if get_clock() >= parse_dt(offer["expires_at"]):
        raise ApiError("ERR_OFFER_EXPIRED", 409, "Offer has expired")
    # cascade offer_accept_chain
    offer["status"] = "ACCEPTED"
    touch(offer)
    application["status"] = "FUNDED"
    touch(application)
    for sib in DB["offers"].values():
        if (
            sib["application_id"] == application["id"]
            and sib["id"] != offer["id"]
            and sib["status"] == "PRESENTED"
        ):
            sib["status"] = "DECLINED"
            touch(sib)
    funded_at = get_clock()
    maturity = add_months(funded_at, offer["term_months"])
    agr = base_record()
    agr.update(
        {
            "offer_id": offer["id"],
            "application_id": application["id"],
            "fund_id": offer["fund_id"],
            "investment_amount_cents": offer["investment_amount_cents"],
            "option_percentage": offer["option_percentage"],
            "adjusted_start_value_cents": offer["adjusted_start_value_cents"],
            "term_months": offer["term_months"],
            "capped_annual_rate": offer["capped_annual_rate"],
            "funded_at": iso_format(funded_at),
            "maturity_at": iso_format(maturity),
            "status": "FUNDED",
            "covenant_status": "COMPLIANT",
        }
    )
    DB["agreements"][agr["id"]] = agr
    lien = base_record()
    lien.update(
        {
            "agreement_id": agr["id"],
            "title_status": "PENDING",
            "lien_position": None,
            "status": "PENDING",
        }
    )
    DB["liens"][lien["id"]] = lien
    return success_object(core.ser_offer(offer))


@app.route("/hei/offers/<rid>/decline", methods=["POST"])
def decline_offer(rid):
    uid, role = authenticate()
    require_roles(role, ["Homeowner"])
    offer = fetch("offers", rid)
    require_owner(offer_owner_homeowner(offer), uid)
    if offer["status"] != "PRESENTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Offer is not PRESENTED")
    offer["status"] = "DECLINED"
    touch(offer)
    return success_object(core.ser_offer(offer))


@app.route("/hei/offers/<rid>/counter", methods=["POST"])
def counter_offer(rid):
    uid, role = authenticate()
    require_roles(role, ["Homeowner"])
    offer = fetch("offers", rid)
    require_owner(offer_owner_homeowner(offer), uid)
    body = get_body()
    notes = require_str(body, "counter_notes")
    if offer["status"] != "PRESENTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Offer is not PRESENTED")
    offer["status"] = "COUNTERED"
    offer["counter_notes"] = notes
    touch(offer)
    return success_object(core.ser_offer(offer))


@app.route("/hei/offers/<rid>/represent", methods=["POST"])
def represent_offer(rid):
    _uid, role = authenticate()
    require_roles(role, ["InvestmentAnalyst"])
    offer = fetch("offers", rid)
    body = get_body()
    if offer["status"] != "COUNTERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Offer is not COUNTERED")
    # optional overrides
    new_vals = dict(offer)
    for field, kind in (
        ("investment_amount_cents", "int"),
        ("option_percentage", "num"),
        ("risk_adjustment_pct", "num"),
        ("term_months", "int"),
        ("capped_annual_rate", "num"),
        ("expires_at", "str"),
    ):
        if field in body and body[field] is not None:
            if kind == "int":
                new_vals[field] = require_int(body, field)
            elif kind == "num":
                new_vals[field] = require_number(body, field)
            else:
                val = require_str(body, field)
                if parse_dt(val) is None:
                    raise ApiError("ERR_VALIDATION", 400, "expires_at invalid")
                new_vals[field] = val
    valuation = DB["valuations"].get(offer["valuation_id"])
    valued = valuation["valued_amount_cents"] if valuation else 0
    investment = new_vals["investment_amount_cents"]
    # fiscal gates (priority 12)
    max_investment = floor_cents(INVESTMENT_LTV_CAP * D(valued))
    if investment > max_investment:
        raise ApiError(
            "ERR_INVESTMENT_EXCEEDS_LTV_CAP", 422, "Investment exceeds LTV cap"
        )
    if investment > fund_available(offer["fund_id"]):
        raise ApiError(
            "ERR_INSUFFICIENT_FUND_CAPITAL", 422, "Insufficient available fund capital"
        )
    offer["investment_amount_cents"] = investment
    offer["option_percentage"] = new_vals["option_percentage"]
    offer["risk_adjustment_pct"] = new_vals["risk_adjustment_pct"]
    offer["term_months"] = new_vals["term_months"]
    offer["capped_annual_rate"] = new_vals["capped_annual_rate"]
    offer["expires_at"] = new_vals["expires_at"]
    offer["adjusted_start_value_cents"] = compute_adjusted_start_value(
        valued, offer["risk_adjustment_pct"]
    )
    offer["status"] = "PRESENTED"
    touch(offer)
    return success_object(core.ser_offer(offer))


@app.route("/hei/offers/<rid>/withdraw", methods=["POST"])
def withdraw_offer(rid):
    _uid, role = authenticate()
    require_roles(role, ["InvestmentAnalyst"])
    offer = fetch("offers", rid)
    if offer["status"] != "PRESENTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Offer is not PRESENTED")
    offer["status"] = "WITHDRAWN"
    touch(offer)
    return success_object(core.ser_offer(offer))


# ==========================================================================
# Agreement
# ==========================================================================
def agreement_owner_homeowner(agreement):
    application = DB["applications"][agreement["application_id"]]
    return application["homeowner_id"]


def lien_for_agreement(agreement_id):
    for lien in DB["liens"].values():
        if lien["agreement_id"] == agreement_id:
            return lien
    return None


@app.route("/hei/agreements/<rid>", methods=["GET"])
def get_agreement(rid):
    _uid, _role = authenticate()
    rec = fetch("agreements", rid)
    return success_object(core.ser_agreement(rec))


@app.route("/hei/agreements", methods=["GET"])
def list_agreements():
    _uid, _role = authenticate()
    args = request.args

    def pred(r):
        return (
            _filter_match(r, args, "offer_id")
            and _filter_match(r, args, "application_id")
            and _filter_match(r, args, "fund_id")
            and _filter_match(r, args, "status")
        )

    return list_response("agreements", core.ser_agreement, pred)


@app.route("/hei/agreements/<rid>/activate", methods=["POST"])
def activate_agreement(rid):
    _uid, role = authenticate()
    require_roles(role, ["ClosingAgent"])
    agr = fetch("agreements", rid)
    if agr["status"] != "FUNDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement is not FUNDED")
    lien = lien_for_agreement(agr["id"])
    if lien is None or lien["status"] != "RECORDED":
        raise ApiError("ERR_LIEN_NOT_RECORDED", 409, "Lien is not RECORDED")
    agr["status"] = "ACTIVE"
    touch(agr)
    return success_object(core.ser_agreement(agr))


@app.route("/hei/agreements/<rid>/initiate-exit", methods=["POST"])
def initiate_exit(rid):
    uid, role = authenticate()
    require_roles(role, ["Homeowner"])
    agr = fetch("agreements", rid)
    require_owner(agreement_owner_homeowner(agr), uid)
    if agr["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement is not ACTIVE")
    if agr["covenant_status"] == "BREACH_NOTICED":
        raise ApiError("ERR_COVENANT_BREACH_OPEN", 409, "Open covenant breach")
    agr["status"] = "EXIT_INITIATED"
    touch(agr)
    return success_object(core.ser_agreement(agr))


@app.route("/hei/agreements/<rid>/default", methods=["POST"])
def default_agreement(rid):
    _uid, role = authenticate()
    require_roles(role, ["ComplianceOfficer"])
    agr = fetch("agreements", rid)
    if agr["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement is not ACTIVE")
    if agr["covenant_status"] != "BREACH_NOTICED":
        raise ApiError("ERR_NO_OPEN_BREACH", 409, "No open covenant breach")
    agr["status"] = "DEFAULTED"
    touch(agr)
    return success_object(core.ser_agreement(agr))


# ==========================================================================
# Lien
# ==========================================================================
@app.route("/hei/liens/<rid>", methods=["GET"])
def get_lien(rid):
    _uid, _role = authenticate()
    rec = fetch("liens", rid)
    return success_object(core.ser_lien(rec))


@app.route("/hei/liens", methods=["GET"])
def list_liens():
    _uid, _role = authenticate()
    args = request.args

    def pred(r):
        return _filter_match(r, args, "agreement_id") and _filter_match(
            r, args, "status"
        )

    return list_response("liens", core.ser_lien, pred)


@app.route("/hei/liens/<rid>/record", methods=["POST"])
def record_lien(rid):
    _uid, role = authenticate()
    require_roles(role, ["ClosingAgent"])
    lien = fetch("liens", rid)
    body = get_body()
    title_status = require_enum(body, "title_status", ["CLEAR", "CLOUDED"])
    lien_position = require_int(body, "lien_position")
    if lien["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Lien is not PENDING")
    # constraint gate (priority 11): title must resolve to CLEAR
    if title_status == "CLOUDED":
        raise ApiError("ERR_TITLE_NOT_CLEAR", 409, "Title is not clear")
    lien["title_status"] = title_status
    lien["lien_position"] = lien_position
    lien["status"] = "RECORDED"
    touch(lien)
    return success_object(core.ser_lien(lien))


# ==========================================================================
# Inspector
# ==========================================================================
@app.route("/hei/inspectors", methods=["POST"])
def create_inspector():
    _uid, role = authenticate()
    require_roles(role, ["InvestmentAnalyst"])
    body = get_body()
    full_name = require_str(body, "full_name")
    region_code = require_str(body, "region_code")
    rec = base_record()
    rec.update({"full_name": full_name, "region_code": region_code})
    DB["inspectors"][rec["id"]] = rec
    return success_object(core.ser_inspector(rec), 201)


@app.route("/hei/inspectors/<rid>", methods=["GET"])
def get_inspector(rid):
    _uid, _role = authenticate()
    rec = fetch("inspectors", rid)
    return success_object(core.ser_inspector(rec))


# ==========================================================================
# Inspection
# ==========================================================================
def _valid_date(s):
    if not isinstance(s, str):
        return False
    try:
        from datetime import datetime as _dt

        _dt.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


@app.route("/hei/agreements/<rid>/inspections", methods=["POST"])
def create_inspection(rid):
    _uid, role = authenticate()
    require_roles(role, ["InvestmentAnalyst", "ClosingAgent"])
    agr = fetch("agreements", rid)
    body = get_body()
    inspector_id = require_str(body, "inspector_id")
    scheduled_date = require_str(body, "scheduled_date")
    if not _valid_date(scheduled_date):
        raise ApiError("ERR_VALIDATION", 400, "scheduled_date must be YYYY-MM-DD")
    # body FK existence (priority 5)
    fetch("inspectors", inspector_id)
    # temporal overlap (priority 10): one property per inspector per day
    for insp in DB["inspections"].values():
        if (
            insp["inspector_id"] == inspector_id
            and insp["scheduled_date"] == scheduled_date
            and insp["status"] != "CANCELLED"
        ):
            raise ApiError(
                "ERR_INSPECTOR_DOUBLE_BOOKED", 409, "Inspector double-booked that day"
            )
    rec = base_record()
    rec.update(
        {
            "agreement_id": agr["id"],
            "inspector_id": inspector_id,
            "scheduled_date": scheduled_date,
            "status": "SCHEDULED",
            "condition_score": None,
        }
    )
    DB["inspections"][rec["id"]] = rec
    return success_object(core.ser_inspection(rec), 201)


@app.route("/hei/inspections/<rid>", methods=["GET"])
def get_inspection(rid):
    _uid, _role = authenticate()
    rec = fetch("inspections", rid)
    return success_object(core.ser_inspection(rec))


@app.route("/hei/inspections", methods=["GET"])
def list_inspections():
    _uid, _role = authenticate()
    args = request.args

    def pred(r):
        return (
            _filter_match(r, args, "agreement_id")
            and _filter_match(r, args, "inspector_id")
            and _filter_match(r, args, "status")
        )

    return list_response("inspections", core.ser_inspection, pred)


@app.route("/hei/inspections/<rid>/complete", methods=["POST"])
def complete_inspection(rid):
    _uid, role = authenticate()
    require_roles(role, ["Inspector"])
    rec = fetch("inspections", rid)
    body = get_body()
    result = require_enum(body, "result", ["PASSED", "FAILED"])
    score = require_number(body, "condition_score")
    if score < 0 or score > 100:
        raise ApiError("ERR_VALIDATION", 400, "condition_score must be in [0,100]")
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Inspection is not SCHEDULED")
    rec["condition_score"] = score
    agr = DB["agreements"].get(rec["agreement_id"])
    if result == "PASSED":
        rec["status"] = "PASSED"
        if agr is not None and agr["covenant_status"] == "BREACH_NOTICED":
            agr["covenant_status"] = "CURED"
            touch(agr)
    else:
        rec["status"] = "FAILED"
        if agr is not None and agr["covenant_status"] in ("COMPLIANT", "CURED"):
            agr["covenant_status"] = "BREACH_NOTICED"
            touch(agr)
    touch(rec)
    return success_object(core.ser_inspection(rec))


@app.route("/hei/inspections/<rid>/cancel", methods=["POST"])
def cancel_inspection(rid):
    _uid, role = authenticate()
    require_roles(role, ["InvestmentAnalyst"])
    rec = fetch("inspections", rid)
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Inspection is not SCHEDULED")
    rec["status"] = "CANCELLED"
    touch(rec)
    return success_object(core.ser_inspection(rec))


# ==========================================================================
# Settlement
# ==========================================================================
def settlement_owner_homeowner(settlement):
    agr = DB["agreements"][settlement["agreement_id"]]
    application = DB["applications"][agr["application_id"]]
    return application["homeowner_id"]


def compute_figures(agreement, settlement_type, ending_value, mortgage_payoff):
    funded_at = parse_dt(agreement["funded_at"])
    elapsed = whole_calendar_months(funded_at, get_clock())
    gain = max(0, ending_value - agreement["adjusted_start_value_cents"])
    raw_share = round_half_up(D(agreement["option_percentage"]) * D(gain))
    cap = round_half_up(
        D(agreement["investment_amount_cents"])
        * D(agreement["capped_annual_rate"])
        * D(elapsed)
        / D(12)
    )
    if settlement_type == "SALE":
        share = min(raw_share, cap)
    else:
        share = raw_share
    origination = round_half_up(ORIGINATION_FEE_PCT * D(agreement["investment_amount_cents"]))
    servicing = round_half_up(SERVICING_FEE_PCT * D(ending_value))
    fee = origination + servicing + ADMIN_FLAT_CENTS
    net_proceeds = ending_value - mortgage_payoff - fee
    payout = net_proceeds - agreement["investment_amount_cents"] - share
    return {
        "elapsed_months": elapsed,
        "appreciation_share_cents": share,
        "settlement_fee_cents": fee,
        "net_proceeds_cents": net_proceeds,
        "homeowner_payout_cents": payout,
    }


def build_settlement(agreement, settlement_type, sale_price, appraised, mortgage_payoff, proposed_by):
    ending_value = sale_price if settlement_type == "SALE" else appraised
    figs = compute_figures(agreement, settlement_type, ending_value, mortgage_payoff)
    rec = base_record()
    rec.update(
        {
            "agreement_id": agreement["id"],
            "settlement_type": settlement_type,
            "sale_price_cents": sale_price,
            "current_appraised_value_cents": appraised,
            "mortgage_payoff_cents": mortgage_payoff,
            "ending_value_cents": ending_value,
            "status": "PROPOSED",
            "proposed_by_user_id": proposed_by,
        }
    )
    rec.update(figs)
    DB["settlements"][rec["id"]] = rec
    return rec


@app.route("/hei/agreements/<rid>/settlements", methods=["POST"])
def propose_settlement(rid):
    uid, role = authenticate()
    require_roles(role, ["ComplianceOfficer"])
    agr = fetch("agreements", rid)
    body = get_body()
    settlement_type = require_enum(body, "settlement_type", ["SALE", "BUYOUT"])
    mortgage_payoff = require_int(body, "mortgage_payoff_cents")
    expected_version = require_int(body, "expected_agreement_version")
    sale_price = None
    appraised = None
    if settlement_type == "SALE":
        sale_price = require_int(body, "sale_price_cents")
    else:
        appraised = require_int(body, "current_appraised_value_cents")
    # state (priority 6)
    if agr["status"] not in ("EXIT_INITIATED", "SETTLEMENT_PROPOSED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement not in a proposable state")
    # OCC (priority 7)
    if expected_version != agr["version"]:
        raise ApiError(
            "ERR_STALE_AGREEMENT_VERSION", 412, "Stale expected_agreement_version"
        )
    # re-proposal: void the prior PROPOSED settlement
    if agr["status"] == "SETTLEMENT_PROPOSED":
        for s in DB["settlements"].values():
            if s["agreement_id"] == agr["id"] and s["status"] == "PROPOSED":
                s["status"] = "VOID"
                touch(s)
    rec = build_settlement(agr, settlement_type, sale_price, appraised, mortgage_payoff, uid)
    agr["status"] = "SETTLEMENT_PROPOSED"
    touch(agr, bump_version=True)
    return success_object(core.ser_settlement(rec), 201)


@app.route("/hei/settlements/<rid>", methods=["GET"])
def get_settlement(rid):
    _uid, _role = authenticate()
    rec = fetch("settlements", rid)
    return success_object(core.ser_settlement(rec))


@app.route("/hei/settlements", methods=["GET"])
def list_settlements():
    _uid, _role = authenticate()
    args = request.args

    def pred(r):
        return _filter_match(r, args, "agreement_id") and _filter_match(
            r, args, "status"
        )

    return list_response("settlements", core.ser_settlement, pred)


@app.route("/hei/settlements/<rid>/finalize", methods=["POST"])
def finalize_settlement(rid):
    _uid, role = authenticate()
    require_roles(role, ["ComplianceOfficer"])
    settlement = fetch("settlements", rid)
    if settlement["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Settlement is not PROPOSED")
    agr = DB["agreements"].get(settlement["agreement_id"])
    if agr is None or agr["status"] != "SETTLEMENT_PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Agreement not SETTLEMENT_PROPOSED")
    # fiscal gate (priority 12)
    if settlement["net_proceeds_cents"] < 0:
        raise ApiError("ERR_PROCEEDS_INSUFFICIENT", 422, "Net proceeds are negative")
    # cascade settlement_finalize_chain (depth 3)
    settlement["status"] = "FINALIZED"
    touch(settlement)
    agr["status"] = "SETTLED"
    touch(agr)
    lien = lien_for_agreement(agr["id"])
    if lien is not None and lien["status"] == "RECORDED":
        lien["status"] = "RELEASED"
        touch(lien)
    for insp in DB["inspections"].values():
        if insp["agreement_id"] == agr["id"] and insp["status"] == "SCHEDULED":
            insp["status"] = "CANCELLED"
            touch(insp)
    return success_object(core.ser_settlement(settlement))


@app.route("/hei/settlements/<rid>/dispute", methods=["POST"])
def dispute_settlement(rid):
    uid, role = authenticate()
    require_roles(role, ["Homeowner"])
    settlement = fetch("settlements", rid)
    require_owner(settlement_owner_homeowner(settlement), uid)
    body = get_body()
    reason = require_str(body, "reason")
    disputed_value = require_int(body, "disputed_value_cents")
    if settlement["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Settlement is not PROPOSED")
    agr = DB["agreements"][settlement["agreement_id"]]
    settlement["status"] = "DISPUTED"
    touch(settlement)
    agr["status"] = "DISPUTED"
    touch(agr)
    rec = base_record()
    rec.update(
        {
            "settlement_id": settlement["id"],
            "agreement_id": agr["id"],
            "reason": reason,
            "disputed_value_cents": disputed_value,
            "resolved_value_cents": None,
            "status": "OPEN",
            "resolved_by_user_id": None,
        }
    )
    DB["disputes"][rec["id"]] = rec
    return success_object(core.ser_dispute(rec), 201)


# ==========================================================================
# Dispute
# ==========================================================================
@app.route("/hei/disputes/<rid>", methods=["GET"])
def get_dispute(rid):
    _uid, _role = authenticate()
    rec = fetch("disputes", rid)
    return success_object(core.ser_dispute(rec))


@app.route("/hei/disputes", methods=["GET"])
def list_disputes():
    _uid, _role = authenticate()
    args = request.args

    def pred(r):
        return (
            _filter_match(r, args, "settlement_id")
            and _filter_match(r, args, "agreement_id")
            and _filter_match(r, args, "status")
        )

    return list_response("disputes", core.ser_dispute, pred)


@app.route("/hei/disputes/<rid>/resolve", methods=["POST"])
def resolve_dispute(rid):
    uid, role = authenticate()
    require_roles(role, ["ComplianceOfficer"])
    dispute = fetch("disputes", rid)
    body = get_body()
    resolved_value = require_int(body, "resolved_value_cents")
    if dispute["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute is not OPEN")
    disputed_settlement = DB["settlements"][dispute["settlement_id"]]
    # segregation of duties (priority 8)
    if uid == disputed_settlement["proposed_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", 403, "Resolver must differ from proposer"
        )
    agr = DB["agreements"][dispute["agreement_id"]]
    # void the disputed settlement
    disputed_settlement["status"] = "VOID"
    touch(disputed_settlement)
    # create a replacement settlement with ending value = resolved_value_cents
    stype = disputed_settlement["settlement_type"]
    sale_price = resolved_value if stype == "SALE" else None
    appraised = resolved_value if stype == "BUYOUT" else None
    build_settlement(
        agr, stype, sale_price, appraised, disputed_settlement["mortgage_payoff_cents"], uid
    )
    agr["status"] = "SETTLEMENT_PROPOSED"
    touch(agr, bump_version=True)
    dispute["resolved_value_cents"] = resolved_value
    dispute["resolved_by_user_id"] = uid
    dispute["status"] = "RESOLVED"
    touch(dispute)
    return success_object(core.ser_dispute(dispute))


@app.route("/hei/disputes/<rid>/reject", methods=["POST"])
def reject_dispute(rid):
    uid, role = authenticate()
    require_roles(role, ["ComplianceOfficer"])
    dispute = fetch("disputes", rid)
    if dispute["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute is not OPEN")
    disputed_settlement = DB["settlements"][dispute["settlement_id"]]
    # segregation of duties (priority 8)
    if uid == disputed_settlement["proposed_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", 403, "Rejecter must differ from proposer"
        )
    agr = DB["agreements"][dispute["agreement_id"]]
    # reinstate the original settlement
    disputed_settlement["status"] = "PROPOSED"
    touch(disputed_settlement)
    agr["status"] = "SETTLEMENT_PROPOSED"
    touch(agr)
    dispute["resolved_by_user_id"] = uid
    dispute["status"] = "REJECTED"
    touch(dispute)
    return success_object(core.ser_dispute(dispute))


# ==========================================================================
# Entrypoint
# ==========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
