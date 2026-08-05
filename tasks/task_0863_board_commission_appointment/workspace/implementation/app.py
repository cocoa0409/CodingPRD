"""Board & Commission Appointment Management API (Flask, in-memory)."""
import os
from flask import Flask, request, jsonify

from db import store
from util import (
    ApiError, parse_dt, render_domain_dt, render_system_ts, new_request_id,
    add_days, add_months, round_half_up,
)
import calc
import serialize as S

app = Flask(__name__)

ROLES = {
    "BoardClerk", "AppointingAuthority", "ConfirmingMember",
    "EthicsOfficer", "Applicant", "PublicAuditor",
}


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
def _meta(pagination=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": render_system_ts(store.now()),
    }
    if pagination:
        m.update(pagination)
    return m


def success(data, response_type, status=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def list_response(records, serialize_fn):
    limit, offset = get_pagination()
    records = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(records)
    page = records[offset:offset + limit]
    data = [serialize_fn(r) for r in page]
    pag = {"limit": limit, "offset": offset, "total_count": total,
           "has_more": offset + limit < total}
    return success(data, "array", 200, pag)


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"}}
    return jsonify(body), 404


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid auth headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted")
    return uid, role


# --------------------------------------------------------------------------
# Input validation helpers (ERR_INVALID_REQUEST, 422)
# --------------------------------------------------------------------------
def _invalid(msg):
    return ApiError("ERR_INVALID_REQUEST", 422, msg)


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise _invalid("Body must be a JSON object")
    return data


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise _invalid(f"{name} is required")
    return v


def opt_str(body, name, default=None):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, str):
        raise _invalid(f"{name} must be a string")
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise _invalid(f"{name} must be one of {sorted(allowed)}")
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise _invalid(f"{name} must be a boolean")
    return v


def req_int(body, name, minimum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise _invalid(f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise _invalid(f"{name} must be >= {minimum}")
    return v


def opt_int(body, name, default=None, minimum=None):
    if name not in body or body.get(name) is None:
        return default
    return req_int(body, name, minimum)


def req_number(body, name, gt=None, gte=None, lte=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _invalid(f"{name} must be a number")
    if gt is not None and not v > gt:
        raise _invalid(f"{name} must be > {gt}")
    if gte is not None and not v >= gte:
        raise _invalid(f"{name} must be >= {gte}")
    if lte is not None and not v <= lte:
        raise _invalid(f"{name} must be <= {lte}")
    return v


def opt_bool(body, name, default=None):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise _invalid(f"{name} must be a boolean")
    return v


def req_dt(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        raise _invalid(f"{name} is required")
    try:
        return parse_dt(v)
    except Exception:
        raise _invalid(f"{name} must be an ISO-8601 instant")


# --------------------------------------------------------------------------
# Existence helpers (ERR_NOT_FOUND, 404)
# --------------------------------------------------------------------------
def must_exist(coll, ident):
    rec = coll.get(ident)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return rec


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
def get_pagination():
    def parse_int(name, default):
        v = request.args.get(name)
        if v is None:
            return default
        try:
            return int(v)
        except Exception:
            return default
    limit = parse_int("limit", 10)
    offset = parse_int("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def term_serializer(r):
    return S.term_out(store, r)


# ==========================================================================
# ROUTES  (inserted below)
# ==========================================================================
# ---- Logical clock ----
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = body_json()
    dt = req_dt(body, "to_iso8601")
    store.set_clock(dt)
    return success({}, "object", 200)


# ---- Board ----
BOARD_TYPES = {"BOARD", "COMMISSION", "AUTHORITY"}


@app.route("/civic/boards", methods=["POST"])
def create_board():
    authenticate({"BoardClerk"})
    body = body_json()
    name = req_str(body, "name")
    jurisdiction = req_str(body, "jurisdiction")
    board_type = req_enum(body, "board_type", BOARD_TYPES)
    authorized_seat_count = req_int(body, "authorized_seat_count", minimum=1)
    quorum_count = req_int(body, "quorum_count", minimum=1)
    term_length_months = req_int(body, "term_length_months", minimum=1)
    max_consecutive_terms = req_int(body, "max_consecutive_terms", minimum=1)
    max_cumulative_years = req_number(body, "max_cumulative_years", gt=0)
    attendance_threshold_pct = req_number(body, "attendance_threshold_pct", gt=0, lte=100)
    sunshine_notice_days = req_int(body, "sunshine_notice_days", minimum=0)
    max_holdover_days = opt_int(body, "max_holdover_days", default=90, minimum=0)
    is_sunshine_subject = opt_bool(body, "is_sunshine_subject", default=True)

    r = store.new_record()
    r.update({
        "name": name, "jurisdiction": jurisdiction, "board_type": board_type,
        "authorized_seat_count": authorized_seat_count, "quorum_count": quorum_count,
        "term_length_months": term_length_months,
        "max_consecutive_terms": max_consecutive_terms,
        "max_cumulative_years": max_cumulative_years,
        "attendance_threshold_pct": attendance_threshold_pct,
        "sunshine_notice_days": sunshine_notice_days,
        "max_holdover_days": max_holdover_days,
        "is_sunshine_subject": is_sunshine_subject,
        "status": "ACTIVE",
    })
    store.boards[r["id"]] = r
    return success(S.board_out(r), "object", 201)


@app.route("/civic/boards", methods=["GET"])
def list_boards():
    authenticate({"BoardClerk", "PublicAuditor"})
    recs = list(store.boards.values())
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return list_response(recs, S.board_out)


@app.route("/civic/boards/<bid>", methods=["GET"])
def get_board(bid):
    authenticate({"BoardClerk", "PublicAuditor"})
    r = must_exist(store.boards, bid)
    return success(S.board_out(r), "object", 200)


# ---- Seat ----
SEAT_CATEGORIES = {"AT_LARGE", "DISTRICT", "EX_OFFICIO"}
RESIDENCY_REQS = {"IN_JURISDICTION", "DISTRICT_SPECIFIC", "NONE"}


@app.route("/civic/seats", methods=["POST"])
def create_seat():
    authenticate({"BoardClerk"})
    body = body_json()
    board_id = req_str(body, "board_id")
    seat_number = req_int(body, "seat_number", minimum=1)
    seat_category = req_enum(body, "seat_category", SEAT_CATEGORIES)
    residency_requirement = req_enum(body, "residency_requirement", RESIDENCY_REQS)
    required_district = opt_str(body, "required_district", default=None)
    # existence
    board = must_exist(store.boards, board_id)
    # business: district-required first, then capacity
    if residency_requirement == "DISTRICT_SPECIFIC" and not required_district:
        raise ApiError("ERR_DISTRICT_REQUIRED", 422, "required_district is required")
    existing = [s for s in store.seats.values() if s["board_id"] == board_id]
    if len(existing) + 1 > board["authorized_seat_count"]:
        raise ApiError("ERR_SEAT_LIMIT_REACHED", 409, "Seat limit reached")

    r = store.new_record()
    r.update({
        "board_id": board_id, "seat_number": seat_number,
        "seat_category": seat_category,
        "residency_requirement": residency_requirement,
        "required_district": required_district,
        "occupancy_status": "VACANT",
    })
    store.seats[r["id"]] = r
    return success(S.seat_out(r), "object", 201)


@app.route("/civic/seats", methods=["GET"])
def list_seats():
    authenticate({"BoardClerk", "PublicAuditor"})
    recs = list(store.seats.values())
    board_id = request.args.get("board_id")
    occ = request.args.get("occupancy_status")
    if board_id is not None:
        recs = [r for r in recs if r["board_id"] == board_id]
    if occ is not None:
        recs = [r for r in recs if r["occupancy_status"] == occ]
    return list_response(recs, S.seat_out)


@app.route("/civic/seats/<sid>", methods=["GET"])
def get_seat(sid):
    authenticate({"BoardClerk", "PublicAuditor", "AppointingAuthority"})
    r = must_exist(store.seats, sid)
    return success(S.seat_out(r), "object", 200)


# ---- Vacancy ----
VACANCY_REASONS = {"NEW_SEAT", "RESIGNATION", "TERM_EXPIRY", "REMOVAL"}


@app.route("/civic/vacancies", methods=["POST"])
def create_vacancy():
    authenticate({"BoardClerk"})
    body = body_json()
    seat_id = req_str(body, "seat_id")
    reason = req_enum(body, "reason", VACANCY_REASONS)
    application_deadline = req_dt(body, "application_deadline")
    must_exist(store.seats, seat_id)
    r = store.new_record()
    r.update({
        "seat_id": seat_id, "reason": reason,
        "application_deadline": render_domain_dt(application_deadline),
        "status": "OPEN",
    })
    store.vacancies[r["id"]] = r
    return success(S.vacancy_out(r), "object", 201)


@app.route("/civic/vacancies", methods=["GET"])
def list_vacancies():
    authenticate({"BoardClerk", "PublicAuditor", "Applicant"})
    recs = list(store.vacancies.values())
    seat_id = request.args.get("seat_id")
    status = request.args.get("status")
    if seat_id is not None:
        recs = [r for r in recs if r["seat_id"] == seat_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return list_response(recs, S.vacancy_out)


@app.route("/civic/vacancies/<vid>", methods=["GET"])
def get_vacancy(vid):
    authenticate({"BoardClerk", "PublicAuditor", "Applicant"})
    r = must_exist(store.vacancies, vid)
    return success(S.vacancy_out(r), "object", 200)


@app.route("/civic/vacancies/<vid>/close", methods=["POST"])
def close_vacancy(vid):
    authenticate({"BoardClerk"})
    r = must_exist(store.vacancies, vid)
    if r["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Vacancy is not OPEN")
    r["status"] = "CLOSED"
    store.touch(r)
    return success(S.vacancy_out(r), "object", 200)


# ---- helpers for residency ----
def residency_ok(seat, applicant):
    req = seat["residency_requirement"]
    if req == "IN_JURISDICTION":
        return bool(applicant["resides_in_jurisdiction"])
    if req == "DISTRICT_SPECIFIC":
        return applicant["residence_district"] == seat["required_district"]
    return True  # NONE


def seat_for_vacancy(vacancy):
    return store.seats.get(vacancy["seat_id"])


# ---- Applicant ----
@app.route("/civic/applicants", methods=["POST"])
def create_applicant():
    # Self-registration: no authentication required.
    body = body_json()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    residence_district = req_str(body, "residence_district")
    resides_in_jurisdiction = req_bool(body, "resides_in_jurisdiction")
    is_registered_voter = req_bool(body, "is_registered_voter")
    employer = opt_str(body, "employer", default=None)
    r = store.new_record()
    r.update({
        "full_name": full_name, "email": email,
        "residence_district": residence_district,
        "resides_in_jurisdiction": resides_in_jurisdiction,
        "is_registered_voter": is_registered_voter,
        "employer": employer, "status": "ACTIVE",
    })
    store.applicants[r["id"]] = r
    return success(S.applicant_out(r), "object", 201)


@app.route("/civic/applicants/<aid>", methods=["GET"])
def get_applicant(aid):
    authenticate({"Applicant", "BoardClerk", "PublicAuditor"})
    r = must_exist(store.applicants, aid)
    return success(S.applicant_out(r), "object", 200)


# ---- Application ----
@app.route("/civic/applications", methods=["POST"])
def create_application():
    authenticate({"Applicant"})
    body = body_json()
    applicant_id = req_str(body, "applicant_id")
    vacancy_id = req_str(body, "vacancy_id")
    residency_attested = req_bool(body, "residency_attested")
    statement = opt_str(body, "statement", default=None)
    # existence: body FKs
    applicant = must_exist(store.applicants, applicant_id)
    vacancy = must_exist(store.vacancies, vacancy_id)
    # state: vacancy OPEN
    if vacancy["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Vacancy is not OPEN")
    seat = seat_for_vacancy(vacancy)
    # residency check first
    if not residency_attested or not residency_ok(seat, applicant):
        raise ApiError("ERR_RESIDENCY_REQUIREMENT_NOT_MET", 422,
                       "Residency requirement not met")
    # then window check
    if store.now() > parse_dt(vacancy["application_deadline"]):
        raise ApiError("ERR_APPLICATION_WINDOW_CLOSED", 422,
                       "Application window closed")
    r = store.new_record()
    r.update({
        "applicant_id": applicant_id, "vacancy_id": vacancy_id,
        "residency_attested": residency_attested, "statement": statement,
        "return_count": 0, "status": "SUBMITTED",
    })
    store.applications[r["id"]] = r
    return success(S.application_out(r), "object", 201)


@app.route("/civic/applications", methods=["GET"])
def list_applications():
    authenticate({"BoardClerk", "Applicant"})
    recs = list(store.applications.values())
    for key in ("applicant_id", "vacancy_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r[key] == val]
    return list_response(recs, S.application_out)


@app.route("/civic/applications/<aid>", methods=["GET"])
def get_application(aid):
    authenticate({"BoardClerk", "Applicant"})
    r = must_exist(store.applications, aid)
    return success(S.application_out(r), "object", 200)


@app.route("/civic/applications/<aid>/start-review", methods=["POST"])
def app_start_review(aid):
    authenticate({"BoardClerk"})
    r = must_exist(store.applications, aid)
    if r["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not SUBMITTED")
    r["status"] = "UNDER_REVIEW"
    store.touch(r)
    return success(S.application_out(r), "object", 200)


@app.route("/civic/applications/<aid>/return-for-info", methods=["POST"])
def app_return_for_info(aid):
    authenticate({"BoardClerk"})
    body = body_json()
    opt_str(body, "notes", default=None)
    r = must_exist(store.applications, aid)
    if r["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not UNDER_REVIEW")
    r["status"] = "RETURNED_FOR_INFO"
    r["return_count"] = r["return_count"] + 1
    store.touch(r)
    return success(S.application_out(r), "object", 200)


@app.route("/civic/applications/<aid>/resubmit", methods=["POST"])
def app_resubmit(aid):
    uid, role = authenticate({"Applicant"})
    body = body_json()
    statement = opt_str(body, "statement", default=None)
    r = must_exist(store.applications, aid)
    if r["status"] != "RETURNED_FOR_INFO":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not RETURNED_FOR_INFO")
    if uid != r["applicant_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the owning applicant")
    if statement is not None:
        r["statement"] = statement
    r["status"] = "UNDER_REVIEW"
    store.touch(r)
    return success(S.application_out(r), "object", 200)


@app.route("/civic/applications/<aid>/decide-eligibility", methods=["POST"])
def app_decide_eligibility(aid):
    authenticate({"BoardClerk"})
    body = body_json()
    eligible = req_bool(body, "eligible")
    r = must_exist(store.applications, aid)
    if r["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not UNDER_REVIEW")
    if eligible:
        vacancy = store.vacancies.get(r["vacancy_id"])
        seat = seat_for_vacancy(vacancy) if vacancy else None
        applicant = store.applicants.get(r["applicant_id"])
        if seat is None or applicant is None or not r["residency_attested"] \
                or not residency_ok(seat, applicant):
            raise ApiError("ERR_RESIDENCY_REQUIREMENT_NOT_MET", 422,
                           "Residency requirement not met")
        r["status"] = "ELIGIBLE"
    else:
        r["status"] = "INELIGIBLE"
    store.touch(r)
    return success(S.application_out(r), "object", 200)


# ---- confirmation cascade (shared by confirm + reappointment approve) ----
def do_confirm_cascade(seat, board, applicant_id, appointment_id,
                       term_start_dt, term_end_dt, term_seq):
    term = store.new_record()
    term.update({
        "appointment_id": appointment_id, "seat_id": seat["id"],
        "applicant_id": applicant_id, "board_id": board["id"],
        "term_start_date": render_domain_dt(term_start_dt),
        "term_end_date": render_domain_dt(term_end_dt),
        "term_sequence_number": term_seq,
        "is_holdover": False, "status": "ACTIVE",
    })
    store.terms[term["id"]] = term
    # seat -> FILLED
    seat["occupancy_status"] = "FILLED"
    store.touch(seat)
    # mint 2 PENDING disclosures
    due = render_domain_dt(calc.disclosure_due(term_start_dt))
    for ftype in ("FINANCIAL_DISCLOSURE", "ETHICS_PLEDGE"):
        d = store.new_record()
        d.update({
            "term_id": term["id"], "board_id": board["id"],
            "filing_type": ftype, "due_date": due,
            "filed_at": None, "content": None, "status": "PENDING",
        })
        store.disclosures[d["id"]] = d
    # fill any OPEN vacancy on the seat
    for v in store.vacancies.values():
        if v["seat_id"] == seat["id"] and v["status"] == "OPEN":
            v["status"] = "FILLED"
            store.touch(v)
    return term


# ---- Appointment ----
@app.route("/civic/appointments", methods=["POST"])
def create_appointment():
    uid, role = authenticate({"AppointingAuthority"})
    body = body_json()
    application_id = req_str(body, "application_id")
    seat_id = req_str(body, "seat_id")
    term_start_dt = req_dt(body, "term_start_date")
    expected_seat_version = req_int(body, "expected_seat_version")
    # existence: body FKs, in input order
    application = must_exist(store.applications, application_id)
    seat = must_exist(store.seats, seat_id)
    # state: application ELIGIBLE
    if application["status"] != "ELIGIBLE":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not ELIGIBLE")
    # OCC on seat
    if expected_seat_version != seat["version"]:
        raise ApiError("ERR_STALE_SEAT_VERSION", 412, "Stale seat version")
    board = store.boards[seat["board_id"]]
    applicant_id = application["applicant_id"]
    term_end_dt = calc.term_end(term_start_dt, board["term_length_months"])
    term_seq = 1 + calc.consecutive_terms(store, applicant_id, board["id"])
    # supersede prior live NOMINATED appointment for this seat
    for a in store.appointments.values():
        if a["seat_id"] == seat_id and a["status"] == "NOMINATED":
            a["status"] = "SUPERSEDED"
            store.touch(a)
    # each accepted nomination advances the seat version
    store.touch(seat)
    r = store.new_record()
    r.update({
        "application_id": application_id, "seat_id": seat_id,
        "applicant_id": applicant_id,
        "term_start_date": render_domain_dt(term_start_dt),
        "term_end_date": render_domain_dt(term_end_dt),
        "term_sequence_number": term_seq,
        "nominated_by_user_id": uid,
        "yes_votes": None, "no_votes": None, "confirmed_by_user_id": None,
        "status": "NOMINATED",
    })
    store.appointments[r["id"]] = r
    return success(S.appointment_out(r), "object", 201)


@app.route("/civic/appointments", methods=["GET"])
def list_appointments():
    authenticate({"BoardClerk", "AppointingAuthority", "ConfirmingMember"})
    recs = list(store.appointments.values())
    for key in ("application_id", "seat_id", "applicant_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r[key] == val]
    return list_response(recs, S.appointment_out)


@app.route("/civic/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    authenticate({"BoardClerk", "AppointingAuthority", "ConfirmingMember"})
    r = must_exist(store.appointments, aid)
    return success(S.appointment_out(r), "object", 200)


@app.route("/civic/appointments/<aid>/confirm", methods=["POST"])
def confirm_appointment(aid):
    uid, role = authenticate({"ConfirmingMember"})
    body = body_json()
    yes_votes = req_int(body, "yes_votes", minimum=0)
    no_votes = req_int(body, "no_votes", minimum=0)
    r = must_exist(store.appointments, aid)
    # state
    if r["status"] != "NOMINATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Appointment is not NOMINATED")
    # SoD
    if uid == r["nominated_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Nominator cannot confirm")
    seat = store.seats[r["seat_id"]]
    # seat must be VACANT
    if seat["occupancy_status"] != "VACANT":
        raise ApiError("ERR_INVALID_STATE", 409, "Seat is not VACANT")
    board = store.boards[seat["board_id"]]
    # quorum
    if not (yes_votes >= board["quorum_count"] and yes_votes > no_votes):
        raise ApiError("ERR_QUORUM_NOT_MET", 422, "Quorum not met")
    # term overlap
    start_dt = parse_dt(r["term_start_date"])
    end_dt = parse_dt(r["term_end_date"])
    if calc.term_overlaps(store, seat["id"], start_dt, end_dt):
        raise ApiError("ERR_TERM_OVERLAP", 409, "Term window overlaps existing term")
    # success
    r["yes_votes"] = yes_votes
    r["no_votes"] = no_votes
    r["confirmed_by_user_id"] = uid
    r["status"] = "CONFIRMED"
    store.touch(r)
    do_confirm_cascade(seat, board, r["applicant_id"], r["id"], start_dt, end_dt,
                       r["term_sequence_number"])
    return success(S.appointment_out(r), "object", 200)


@app.route("/civic/appointments/<aid>/reject", methods=["POST"])
def reject_appointment(aid):
    uid, role = authenticate({"ConfirmingMember"})
    body = body_json()
    opt_str(body, "reason", default=None)
    r = must_exist(store.appointments, aid)
    if r["status"] != "NOMINATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Appointment is not NOMINATED")
    if uid == r["nominated_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Nominator cannot reject")
    r["confirmed_by_user_id"] = uid
    r["status"] = "REJECTED"
    store.touch(r)
    return success(S.appointment_out(r), "object", 200)


# ---- Term ----
@app.route("/civic/terms", methods=["GET"])
def list_terms():
    authenticate({"BoardClerk", "PublicAuditor"})
    recs = list(store.terms.values())
    for key in ("seat_id", "applicant_id", "board_id", "appointment_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r[key] == val]
    return list_response(recs, term_serializer)


@app.route("/civic/terms/<tid>", methods=["GET"])
def get_term(tid):
    authenticate({"BoardClerk", "PublicAuditor"})
    r = must_exist(store.terms, tid)
    return success(S.term_out(store, r), "object", 200)


def _find_active_successor(seat_id, scheduled_end, exclude_id):
    candidates = []
    for t in store.terms.values():
        if t["id"] == exclude_id:
            continue
        if t["seat_id"] != seat_id or t["status"] != "ACTIVE":
            continue
        if parse_dt(t["term_start_date"]) >= scheduled_end:
            candidates.append(t)
    candidates.sort(key=lambda t: (t["term_start_date"], t["_seq"]))
    return candidates[0] if candidates else None


@app.route("/civic/terms/<tid>/expire", methods=["POST"])
def expire_term(tid):
    authenticate({"BoardClerk"})
    r = must_exist(store.terms, tid)
    if r["status"] not in ("ACTIVE", "HOLDOVER"):
        raise ApiError("ERR_INVALID_STATE", 409, "Term is not ACTIVE or HOLDOVER")
    scheduled_end = parse_dt(r["term_end_date"])
    now = store.now()
    if now < scheduled_end:
        raise ApiError("ERR_INVALID_STATE", 409, "Term end not yet reached")
    seat = store.seats[r["seat_id"]]
    board = store.boards[r["board_id"]]

    if r["status"] == "HOLDOVER":
        # holdover-extended end reached -> clean expiry
        r["status"] = "EXPIRED"
        store.touch(r)
        successor = _find_active_successor(seat["id"], scheduled_end, r["id"])
        if seat["occupancy_status"] == "HOLDOVER" and successor is None:
            seat["occupancy_status"] = "VACANT"
            store.touch(seat)
        return success(S.term_out(store, r), "object", 200)

    # ACTIVE term
    successor = _find_active_successor(seat["id"], scheduled_end, r["id"])
    if successor is not None and parse_dt(successor["term_start_date"]) <= now:
        # successor already seated -> clean expiry
        r["status"] = "EXPIRED"
        store.touch(r)
        return success(S.term_out(store, r), "object", 200)
    # holdover
    holdover_ceiling = add_days(scheduled_end, board["max_holdover_days"])
    if successor is not None:
        candidate_end = min(parse_dt(successor["term_start_date"]), holdover_ceiling)
    else:
        candidate_end = holdover_ceiling
    resolved_end = max(candidate_end, scheduled_end)
    r["term_end_date"] = render_domain_dt(resolved_end)
    r["is_holdover"] = True
    r["status"] = "HOLDOVER"
    store.touch(r)
    seat["occupancy_status"] = "HOLDOVER"
    store.touch(seat)
    return success(S.term_out(store, r), "object", 200)


# ---- Meeting ----
@app.route("/civic/meetings", methods=["POST"])
def create_meeting():
    authenticate({"BoardClerk"})
    body = body_json()
    board_id = req_str(body, "board_id")
    scheduled_dt = req_dt(body, "scheduled_date")
    must_exist(store.boards, board_id)
    # spacing: >= 24h from every other meeting on the same board
    for m in store.meetings.values():
        if m["board_id"] != board_id:
            continue
        other = parse_dt(m["scheduled_date"])
        gap = abs((scheduled_dt - other).total_seconds())
        if gap < calc.MEETING_MIN_GAP_HOURS * 3600:
            raise ApiError("ERR_MEETING_TOO_CLOSE", 409, "Meeting too close to another")
    r = store.new_record()
    r.update({
        "board_id": board_id, "scheduled_date": render_domain_dt(scheduled_dt),
        "notice_posted_at": None, "notice_compliant": None, "status": "SCHEDULED",
    })
    store.meetings[r["id"]] = r
    return success(S.meeting_out(r), "object", 201)


@app.route("/civic/meetings", methods=["GET"])
def list_meetings():
    authenticate({"BoardClerk", "PublicAuditor"})
    recs = list(store.meetings.values())
    for key in ("board_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r[key] == val]
    return list_response(recs, S.meeting_out)


@app.route("/civic/meetings/<mid>", methods=["GET"])
def get_meeting(mid):
    authenticate({"BoardClerk", "PublicAuditor"})
    r = must_exist(store.meetings, mid)
    return success(S.meeting_out(r), "object", 200)


@app.route("/civic/meetings/<mid>/post-notice", methods=["POST"])
def post_notice(mid):
    authenticate({"BoardClerk"})
    r = must_exist(store.meetings, mid)
    if r["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Meeting is not SCHEDULED")
    board = store.boards[r["board_id"]]
    now = store.now()
    scheduled = parse_dt(r["scheduled_date"])
    required_by = add_days(scheduled, -board["sunshine_notice_days"])
    r["notice_posted_at"] = render_domain_dt(now)
    r["notice_compliant"] = now <= required_by
    r["status"] = "NOTICED"
    store.touch(r)
    return success(S.meeting_out(r), "object", 200)


@app.route("/civic/meetings/<mid>/hold", methods=["POST"])
def hold_meeting(mid):
    authenticate({"BoardClerk"})
    r = must_exist(store.meetings, mid)
    if r["status"] != "NOTICED":
        raise ApiError("ERR_INVALID_STATE", 409, "Meeting is not NOTICED")
    if store.now() < parse_dt(r["scheduled_date"]):
        raise ApiError("ERR_MEETING_NOT_YET_DUE", 409, "Meeting not yet due")
    r["status"] = "HELD"
    store.touch(r)
    return success(S.meeting_out(r), "object", 200)


# ---- Attendance ----
PRESENCE = {"PRESENT", "ABSENT", "EXCUSED"}


@app.route("/civic/attendance", methods=["POST"])
def create_attendance():
    authenticate({"BoardClerk"})
    body = body_json()
    term_id = req_str(body, "term_id")
    meeting_id = req_str(body, "meeting_id")
    presence = req_enum(body, "presence", PRESENCE)
    term = must_exist(store.terms, term_id)
    meeting = must_exist(store.meetings, meeting_id)
    if meeting["status"] != "HELD" or term["status"] not in ("ACTIVE", "HOLDOVER") \
            or meeting["board_id"] != term["board_id"]:
        raise ApiError("ERR_MEETING_NOT_HELD", 409, "Attendance context invalid")
    r = store.new_record(common=False)
    r.update({"term_id": term_id, "meeting_id": meeting_id, "presence": presence})
    store.attendance[r["id"]] = r
    # refresh the owning term's counts (mutation)
    store.touch(term)
    return success(S.attendance_out(r), "object", 201)


@app.route("/civic/attendance", methods=["GET"])
def list_attendance():
    authenticate({"BoardClerk", "PublicAuditor"})
    recs = list(store.attendance.values())
    for key in ("term_id", "meeting_id"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r[key] == val]
    return list_response(recs, S.attendance_out)


@app.route("/civic/attendance/<aid>", methods=["GET"])
def get_attendance(aid):
    authenticate({"BoardClerk", "PublicAuditor"})
    r = must_exist(store.attendance, aid)
    return success(S.attendance_out(r), "object", 200)


# ---- DisclosureFiling ----
@app.route("/civic/disclosures", methods=["GET"])
def list_disclosures():
    authenticate({"BoardClerk", "EthicsOfficer", "Applicant"})
    recs = list(store.disclosures.values())
    for key in ("term_id", "board_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r[key] == val]
    return list_response(recs, S.disclosure_out)


@app.route("/civic/disclosures/<did>", methods=["GET"])
def get_disclosure(did):
    authenticate({"BoardClerk", "EthicsOfficer", "Applicant"})
    r = must_exist(store.disclosures, did)
    return success(S.disclosure_out(r), "object", 200)


@app.route("/civic/disclosures/<did>/file", methods=["POST"])
def file_disclosure(did):
    uid, role = authenticate({"Applicant"})
    body = body_json()
    content = req_str(body, "content")
    r = must_exist(store.disclosures, did)
    if r["status"] not in ("PENDING", "DEFICIENT"):
        raise ApiError("ERR_INVALID_STATE", 409, "Filing is not PENDING/DEFICIENT")
    term = store.terms.get(r["term_id"])
    if term is None or uid != term["applicant_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the filing's member")
    r["content"] = content
    r["filed_at"] = render_domain_dt(store.now())
    r["status"] = "FILED"
    store.touch(r)
    return success(S.disclosure_out(r), "object", 200)


@app.route("/civic/disclosures/<did>/review", methods=["POST"])
def review_disclosure(did):
    authenticate({"EthicsOfficer"})
    body = body_json()
    accept = req_bool(body, "accept")
    r = must_exist(store.disclosures, did)
    if accept:
        if r["status"] not in ("FILED", "DEFICIENT"):
            raise ApiError("ERR_INVALID_STATE", 409, "Filing is not FILED/DEFICIENT")
        r["status"] = "ACCEPTED"
    else:
        if r["status"] != "FILED":
            raise ApiError("ERR_INVALID_STATE", 409, "Filing is not FILED")
        r["status"] = "DEFICIENT"
    store.touch(r)
    return success(S.disclosure_out(r), "object", 200)


# ---- RemovalAction ----
REMOVAL_REASONS = {"RESIGNATION", "TERM_LIMIT", "ATTENDANCE", "ETHICS_VIOLATION", "FOR_CAUSE"}


@app.route("/civic/removals", methods=["POST"])
def create_removal():
    uid, role = authenticate({"EthicsOfficer", "AppointingAuthority"})
    body = body_json()
    term_id = req_str(body, "term_id")
    reason = req_enum(body, "reason", REMOVAL_REASONS)
    effective_dt = req_dt(body, "effective_date")
    term = must_exist(store.terms, term_id)
    if term["status"] not in ("ACTIVE", "HOLDOVER"):
        raise ApiError("ERR_INVALID_STATE", 409, "Term is not ACTIVE or HOLDOVER")
    if reason == "ATTENDANCE":
        board = store.boards[term["board_id"]]
        present, absent, excused = calc.attendance_counts(store, term_id)
        fr = calc.final_rate(present, absent, excused)
        rate = 100.0 if fr is None else fr
        if rate >= board["attendance_threshold_pct"]:
            raise ApiError("ERR_ATTENDANCE_ABOVE_THRESHOLD", 422,
                           "Attendance rate is at or above threshold")
    r = store.new_record()
    r.update({
        "term_id": term_id, "reason": reason,
        "effective_date": render_domain_dt(effective_dt),
        "initiated_by_user_id": uid, "status": "INITIATED",
    })
    store.removals[r["id"]] = r
    return success(S.removal_out(r), "object", 201)


@app.route("/civic/removals", methods=["GET"])
def list_removals():
    authenticate({"BoardClerk", "EthicsOfficer", "AppointingAuthority"})
    recs = list(store.removals.values())
    for key in ("term_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r[key] == val]
    return list_response(recs, S.removal_out)


@app.route("/civic/removals/<rid>", methods=["GET"])
def get_removal(rid):
    authenticate({"BoardClerk", "EthicsOfficer", "AppointingAuthority"})
    r = must_exist(store.removals, rid)
    return success(S.removal_out(r), "object", 200)


@app.route("/civic/removals/<rid>/execute", methods=["POST"])
def execute_removal(rid):
    authenticate({"AppointingAuthority"})
    r = must_exist(store.removals, rid)
    if r["status"] != "INITIATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Removal is not INITIATED")
    term = store.terms[r["term_id"]]
    if term["status"] not in ("ACTIVE", "HOLDOVER"):
        raise ApiError("ERR_INVALID_STATE", 409, "Term is not ACTIVE or HOLDOVER")
    # link1: term -> VACATED
    term["status"] = "VACATED"
    store.touch(term)
    # link2: seat -> VACANT
    seat = store.seats[term["seat_id"]]
    seat["occupancy_status"] = "VACANT"
    store.touch(seat)
    # link3: open a new Vacancy(reason=REMOVAL)
    v = store.new_record()
    v.update({
        "seat_id": seat["id"], "reason": "REMOVAL",
        "application_deadline": None, "status": "OPEN",
    })
    store.vacancies[v["id"]] = v
    # close still-open disclosure filings for the term
    for d in store.disclosures.values():
        if d["term_id"] == term["id"] and d["status"] in ("PENDING", "DEFICIENT"):
            d["status"] = "CLOSED"
            store.touch(d)
    # removal -> EXECUTED
    r["status"] = "EXECUTED"
    store.touch(r)
    return success(S.removal_out(r), "object", 200)


# ---- ReappointmentRequest ----
@app.route("/civic/reappointments", methods=["POST"])
def create_reappointment():
    authenticate({"AppointingAuthority"})
    body = body_json()
    term_id = req_str(body, "term_id")
    seat_id = req_str(body, "seat_id")
    applicant_id = req_str(body, "applicant_id")
    requested_dt = req_dt(body, "requested_term_start")
    must_exist(store.terms, term_id)
    must_exist(store.seats, seat_id)
    must_exist(store.applicants, applicant_id)
    r = store.new_record()
    r.update({
        "term_id": term_id, "seat_id": seat_id, "applicant_id": applicant_id,
        "requested_term_start": render_domain_dt(requested_dt),
        "consecutive_terms_at_request": None,
        "cumulative_years_at_request": None,
        "resulting_appointment_id": None, "status": "REQUESTED",
    })
    store.reappointments[r["id"]] = r
    return success(S.reappointment_out(r), "object", 201)


@app.route("/civic/reappointments", methods=["GET"])
def list_reappointments():
    authenticate({"BoardClerk", "AppointingAuthority", "ConfirmingMember"})
    recs = list(store.reappointments.values())
    for key in ("term_id", "seat_id", "applicant_id", "status"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r[key] == val]
    return list_response(recs, S.reappointment_out)


@app.route("/civic/reappointments/<rid>", methods=["GET"])
def get_reappointment(rid):
    authenticate({"BoardClerk", "AppointingAuthority", "ConfirmingMember"})
    r = must_exist(store.reappointments, rid)
    return success(S.reappointment_out(r), "object", 200)


@app.route("/civic/reappointments/<rid>/decide", methods=["POST"])
def decide_reappointment(rid):
    uid, role = authenticate({"ConfirmingMember"})
    body = body_json()
    approve = req_bool(body, "approve")
    r = must_exist(store.reappointments, rid)
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Request is not REQUESTED")
    term = store.terms[r["term_id"]]
    seat = store.seats[r["seat_id"]]
    board = store.boards[seat["board_id"]]
    applicant_id = r["applicant_id"]
    consec = calc.consecutive_terms(store, applicant_id, board["id"])
    cumyears = calc.cumulative_years(store, applicant_id, board["id"],
                                     board["term_length_months"])
    if not approve:
        r["consecutive_terms_at_request"] = consec
        r["cumulative_years_at_request"] = cumyears
        r["status"] = "DENIED"
        store.touch(r)
        return success(S.reappointment_out(r), "object", 200)

    # approve path
    if term["status"] not in ("EXPIRED", "HOLDOVER"):
        raise ApiError("ERR_INVALID_STATE", 409, "Term is not EXPIRED or HOLDOVER")
    if not (consec < board["max_consecutive_terms"]
            and cumyears < board["max_cumulative_years"]):
        raise ApiError("ERR_TERM_LIMIT_EXCEEDED", 422, "Term limit exceeded")
    start_dt = parse_dt(r["requested_term_start"])
    end_dt = calc.term_end(start_dt, board["term_length_months"])
    if calc.term_overlaps(store, seat["id"], start_dt, end_dt):
        raise ApiError("ERR_TERM_OVERLAP", 409, "Term window overlaps existing term")

    r["consecutive_terms_at_request"] = consec
    r["cumulative_years_at_request"] = cumyears
    term_seq = consec + 1
    appt = store.new_record()
    appt.update({
        "application_id": None, "seat_id": seat["id"], "applicant_id": applicant_id,
        "term_start_date": render_domain_dt(start_dt),
        "term_end_date": render_domain_dt(end_dt),
        "term_sequence_number": term_seq,
        "nominated_by_user_id": None,
        "yes_votes": None, "no_votes": None, "confirmed_by_user_id": uid,
        "status": "CONFIRMED",
    })
    store.appointments[appt["id"]] = appt
    do_confirm_cascade(seat, board, applicant_id, appt["id"], start_dt, end_dt, term_seq)
    r["resulting_appointment_id"] = appt["id"]
    if term["status"] == "HOLDOVER":
        term["status"] = "COMPLETED"
        store.touch(term)
    r["status"] = "APPROVED"
    store.touch(r)
    return success(S.reappointment_out(r), "object", 200)


# ---- Board computed views (roster + compliance report) ----
@app.route("/civic/boards/<bid>/roster", methods=["GET"])
def board_roster(bid):
    authenticate({"BoardClerk", "PublicAuditor"})
    board = must_exist(store.boards, bid)
    seats = [s for s in store.seats.values() if s["board_id"] == bid]
    seats.sort(key=lambda s: (s["created_at"], s["_seq"]))
    seat_entries = []
    filled = vacant = holdover = 0
    for s in seats:
        current_term = None
        for t in store.terms.values():
            if t["seat_id"] == s["id"] and t["status"] in ("ACTIVE", "HOLDOVER"):
                current_term = S.term_out(store, t)
                break
        entry = S.seat_out(s)
        entry["current_term"] = current_term
        seat_entries.append(entry)
        if s["occupancy_status"] == "FILLED":
            filled += 1
        elif s["occupancy_status"] == "VACANT":
            vacant += 1
        elif s["occupancy_status"] == "HOLDOVER":
            holdover += 1
    active_member_count = sum(
        1 for t in store.terms.values()
        if t["board_id"] == bid and t["status"] == "ACTIVE"
    )
    data = {
        "board_id": bid, "seats": seat_entries,
        "filled_seat_count": filled, "vacant_seat_count": vacant,
        "holdover_count": holdover, "active_member_count": active_member_count,
    }
    return success(data, "object", 200)


@app.route("/civic/boards/<bid>/compliance-report", methods=["GET"])
def board_compliance_report(bid):
    authenticate({"BoardClerk", "PublicAuditor"})
    must_exist(store.boards, bid)
    idx = calc.board_attendance_index(store, bid)
    sunshine_meeting_count = 0
    sunshine_violation_count = 0
    for m in store.meetings.values():
        if m["board_id"] != bid:
            continue
        if m["notice_compliant"] is not None:
            sunshine_meeting_count += 1
            if m["notice_compliant"] is False:
                sunshine_violation_count += 1
    now = store.now()
    delinquent = 0
    for d in store.disclosures.values():
        if d["board_id"] != bid:
            continue
        if d["status"] in ("PENDING", "DEFICIENT") and d["due_date"] is not None \
                and parse_dt(d["due_date"]) <= now:
            delinquent += 1
    data = {
        "board_id": bid, "board_attendance_index": idx,
        "sunshine_meeting_count": sunshine_meeting_count,
        "sunshine_violation_count": sunshine_violation_count,
        "delinquent_disclosure_count": delinquent,
    }
    return success(data, "object", 200)


# __ROUTES__

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
