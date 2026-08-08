"""School-Based Medicaid Billing (LEA) API — Flask reference implementation.

In-memory only. All state resets on process boot (per-test-server isolation).
No entity seeding at startup.
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": CLOCK_DEFAULT}


def clock_now():
    return CLOCK["now"]


def clock_date():
    return CLOCK["now"].astimezone(timezone.utc).date()


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_now():
    return fmt_ts(CLOCK["now"])


def parse_iso_dt(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 400, "Invalid ISO datetime")
    try:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Invalid ISO datetime")


def parse_date(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 400, "Invalid date")
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Invalid date")


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
students = {}
providers = {}
credentials = {}
authorizations = {}
consents = {}
service_logs = {}
claims = {}
quarters = {}
moments = {}
settlements = {}

_seq_counter = {"n": 0}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def new_id():
    return str(uuid.uuid4())


def new_entity(**fields):
    now = iso_now()
    e = {"id": new_id(), "created_at": now, "updated_at": now, "version": 1, "_seq": next_seq()}
    e.update(fields)
    return e


def touch(e):
    e["version"] += 1
    e["updated_at"] = iso_now()


def to_public(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Roles / errors
# ---------------------------------------------------------------------------
ALL_ROLES = {"ServiceProvider", "BillingCoordinator", "MedicaidCoordinator", "StateReviewer"}


class ApiError(Exception):
    def __init__(self, error_id, status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": iso_now()}


def ok(data, status=200, response_type="object", pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def ok_list(items, limit, offset, total):
    page = [to_public(x) for x in items]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return ok(page, 200, "array", pagination)


@app.errorhandler(ApiError)
def handle_api_error(e):
    meta = meta_base()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.status


@app.errorhandler(404)
def handle_404(e):
    meta = meta_base()
    return jsonify({"meta": meta, "response_type": "error",
                    "data": {"error_id": "ERR_VALIDATION", "message": "Not found"}}), 404


@app.errorhandler(405)
def handle_405(e):
    meta = meta_base()
    return jsonify({"meta": meta, "response_type": "error",
                    "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"}}), 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return uid, role


# ---------------------------------------------------------------------------
# Body / field validation
# ---------------------------------------------------------------------------
def body_json():
    if request.data and request.data.strip():
        data = request.get_json(silent=True)
        if data is None or not isinstance(data, dict):
            raise ApiError("ERR_VALIDATION", 400, "Malformed request body")
        return data
    return {}


def req_str(data, key):
    if key not in data or data[key] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {key}")
    v = data[key]
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, f"Field {key} must be a non-empty string")
    return v


def opt_str(data, key):
    if key not in data or data[key] is None:
        return None
    v = data[key]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"Field {key} must be a string")
    return v


def req_int(data, key):
    if key not in data or data[key] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {key}")
    v = data[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, f"Field {key} must be an integer")
    return v


def opt_int(data, key, default):
    if key not in data or data[key] is None:
        return default
    v = data[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, f"Field {key} must be an integer")
    return v


def req_enum(data, key, domain):
    v = req_str(data, key)
    if v not in domain:
        raise ApiError("ERR_VALIDATION", 400, f"Field {key} has invalid value")
    return v


def opt_bool(data, key, default):
    if key not in data or data[key] is None:
        return default
    v = data[key]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"Field {key} must be a boolean")
    return v


def parse_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "Invalid limit")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "Invalid offset")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", 400, "limit out of range")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", 400, "offset out of range")
    return limit, offset


def get_or_404(store, rid, err_id):
    e = store.get(rid)
    if e is None:
        raise ApiError(err_id, 404, "Resource not found")
    return e


def list_page(items):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------
def rhu(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def provider_has_credential(provider_id, svc_date, lazy):
    """svc_date is a date object."""
    cd = clock_date()
    for c in credentials.values():
        if c["provider_id"] != provider_id or c["status"] != "ACTIVE":
            continue
        eff = parse_date(c["effective_date"])
        exp = parse_date(c["expiration_date"])
        if lazy and cd > exp:
            continue  # lazily expired
        if eff <= svc_date <= exp:
            return True
    return False


def recompute_claim(claim):
    total = 0
    count = 0
    for log in service_logs.values():
        if log.get("claim_id") == claim["id"] and log["status"] in ("CLAIMED", "PAID", "DENIED"):
            total += log["charge_cents"]
            count += 1
    claim["total_charge_cents"] = total
    claim["attached_log_count"] = count


def recompute_student(student_id):
    st = students.get(student_id)
    if st is None:
        return
    units = 0
    for log in service_logs.values():
        if log["student_id"] == student_id and log["status"] in ("VERIFIED", "CLAIMED", "PAID", "DENIED"):
            units += log["delivered_units"]
    paid = 0
    for cl in claims.values():
        if cl["student_id"] == student_id and cl["status"] == "PAID":
            paid += cl["interim_payment_cents"]
    changed = (st["verified_service_units"] != units) or (st["interim_paid_cents"] != paid)
    st["verified_service_units"] = units
    st["interim_paid_cents"] = paid
    if changed:
        touch(st)


def void_log_cascade(log):
    """Void a non-terminal (LOGGED/DOCUMENTED/VERIFIED) log as part of a cascade."""
    log["status"] = "VOID"
    touch(log)
    recompute_student(log["student_id"])


def discontinue_authorization_cascade(auth):
    """Set auth DISCONTINUED and void its non-terminal service logs."""
    auth["status"] = "DISCONTINUED"
    touch(auth)
    for log in service_logs.values():
        if log["iep_authorization_id"] == auth["id"] and log["status"] in ("LOGGED", "DOCUMENTED", "VERIFIED"):
            void_log_cascade(log)


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(ALL_ROLES)
    data = body_json()
    target = req_str(data, "to_iso8601")
    CLOCK["now"] = parse_iso_dt(target)
    return ok({}, 200, "object")


# ===========================================================================
# Students
# ===========================================================================
@app.route("/sbmb/students", methods=["POST"])
def create_student():
    require_auth({"MedicaidCoordinator"})
    data = body_json()
    medicaid_id = req_str(data, "medicaid_id")
    first_name = req_str(data, "first_name")
    last_name = req_str(data, "last_name")
    date_of_birth = req_str(data, "date_of_birth")
    district_student_id = req_str(data, "district_student_id")
    medicaid_eligible = opt_bool(data, "medicaid_eligible", True)
    st = new_entity(
        medicaid_id=medicaid_id, first_name=first_name, last_name=last_name,
        date_of_birth=date_of_birth, district_student_id=district_student_id,
        medicaid_eligible=medicaid_eligible, status="ACTIVE",
        interim_paid_cents=0, verified_service_units=0,
    )
    students[st["id"]] = st
    return ok(to_public(st), 201)


@app.route("/sbmb/students/<student_id>", methods=["GET"])
def get_student(student_id):
    require_auth(ALL_ROLES)
    st = get_or_404(students, student_id, "ERR_STUDENT_NOT_FOUND")
    return ok(to_public(st))


@app.route("/sbmb/students/<student_id>/withdraw", methods=["POST"])
def withdraw_student(student_id):
    require_auth({"MedicaidCoordinator"})
    st = get_or_404(students, student_id, "ERR_STUDENT_NOT_FOUND")
    if st["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Student is not ACTIVE")
    st["status"] = "WITHDRAWN"
    touch(st)
    for auth in list(authorizations.values()):
        if auth["student_id"] == student_id and auth["status"] == "ACTIVE":
            discontinue_authorization_cascade(auth)
    recompute_student(student_id)
    return ok(to_public(st))


# ===========================================================================
# Providers
# ===========================================================================
@app.route("/sbmb/providers", methods=["POST"])
def create_provider():
    require_auth({"MedicaidCoordinator"})
    data = body_json()
    npi = req_str(data, "npi")
    first_name = req_str(data, "first_name")
    last_name = req_str(data, "last_name")
    discipline = req_enum(data, "discipline", {"SLP", "OT", "PT", "PSYCH", "RN", "AUD"})
    p = new_entity(npi=npi, first_name=first_name, last_name=last_name,
                   discipline=discipline, employment_status="ACTIVE")
    providers[p["id"]] = p
    return ok(to_public(p), 201)


@app.route("/sbmb/providers/<provider_id>", methods=["GET"])
def get_provider(provider_id):
    require_auth(ALL_ROLES)
    p = get_or_404(providers, provider_id, "ERR_PROVIDER_NOT_FOUND")
    return ok(to_public(p))


# ===========================================================================
# Provider Credentials
# ===========================================================================
@app.route("/sbmb/provider-credentials", methods=["POST"])
def create_credential():
    require_auth({"MedicaidCoordinator"})
    data = body_json()
    provider_id = req_str(data, "provider_id")
    credential_type = req_enum(data, "credential_type",
                               {"STATE_LICENSE", "NPI_ENROLLMENT", "MEDICAID_ENROLLMENT"})
    license_number = req_str(data, "license_number")
    effective_date = req_str(data, "effective_date")
    expiration_date = req_str(data, "expiration_date")
    parse_date(effective_date)
    parse_date(expiration_date)
    get_or_404(providers, provider_id, "ERR_PROVIDER_NOT_FOUND")
    c = new_entity(provider_id=provider_id, credential_type=credential_type,
                   license_number=license_number, effective_date=effective_date,
                   expiration_date=expiration_date, status="PENDING")
    credentials[c["id"]] = c
    return ok(to_public(c), 201)


@app.route("/sbmb/provider-credentials/<credential_id>", methods=["GET"])
def get_credential(credential_id):
    require_auth(ALL_ROLES)
    c = get_or_404(credentials, credential_id, "ERR_CREDENTIAL_NOT_FOUND")
    return ok(to_public(c))


@app.route("/sbmb/provider-credentials", methods=["GET"])
def list_credentials():
    require_auth(ALL_ROLES)
    provider_id = request.args.get("provider_id")
    status = request.args.get("status")
    items = [c for c in credentials.values()
             if (provider_id is None or c["provider_id"] == provider_id)
             and (status is None or c["status"] == status)]
    page, limit, offset, total = list_page(items)
    return ok_list(page, limit, offset, total)


def _credential_overlap(cred):
    eff = parse_date(cred["effective_date"])
    exp = parse_date(cred["expiration_date"])
    for other in credentials.values():
        if other["id"] == cred["id"]:
            continue
        if other["provider_id"] != cred["provider_id"]:
            continue
        if other["credential_type"] != cred["credential_type"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        o_eff = parse_date(other["effective_date"])
        o_exp = parse_date(other["expiration_date"])
        # closed intervals overlap (touching endpoints count)
        if eff <= o_exp and o_eff <= exp:
            return True
    return False


@app.route("/sbmb/provider-credentials/<credential_id>/activate", methods=["POST"])
def activate_credential(credential_id):
    require_auth({"MedicaidCoordinator"})
    c = get_or_404(credentials, credential_id, "ERR_CREDENTIAL_NOT_FOUND")
    if c["status"] not in ("PENDING", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Credential is not PENDING or SUSPENDED")
    if _credential_overlap(c):
        raise ApiError("ERR_CREDENTIAL_PERIOD_OVERLAP", 409,
                       "Overlapping active credential of same type exists")
    c["status"] = "ACTIVE"
    touch(c)
    return ok(to_public(c))


@app.route("/sbmb/provider-credentials/<credential_id>/suspend", methods=["POST"])
def suspend_credential(credential_id):
    require_auth({"MedicaidCoordinator"})
    c = get_or_404(credentials, credential_id, "ERR_CREDENTIAL_NOT_FOUND")
    body_json()  # reason optional, ignored beyond parse
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Credential is not ACTIVE")
    c["status"] = "SUSPENDED"
    touch(c)
    return ok(to_public(c))


# ===========================================================================
# IEP Authorizations
# ===========================================================================
@app.route("/sbmb/iep-authorizations", methods=["POST"])
def create_authorization():
    require_auth({"MedicaidCoordinator"})
    data = body_json()
    student_id = req_str(data, "student_id")
    service_type = req_enum(data, "service_type",
                            {"SPEECH_THERAPY", "OCCUPATIONAL_THERAPY", "PHYSICAL_THERAPY",
                             "PSYCH_COUNSELING", "NURSING", "AUDIOLOGY"})
    procedure_code = req_str(data, "procedure_code")
    unit_minutes = req_int(data, "unit_minutes")
    unit_rate_cents = req_int(data, "unit_rate_cents")
    authorized_minutes_per_session = req_int(data, "authorized_minutes_per_session")
    sessions_per_week = req_int(data, "sessions_per_week")
    effective_date = req_str(data, "effective_date")
    expiration_date = req_str(data, "expiration_date")
    parse_date(effective_date)
    parse_date(expiration_date)
    get_or_404(students, student_id, "ERR_STUDENT_NOT_FOUND")
    a = new_entity(
        student_id=student_id, service_type=service_type, procedure_code=procedure_code,
        unit_minutes=unit_minutes, unit_rate_cents=unit_rate_cents,
        authorized_minutes_per_session=authorized_minutes_per_session,
        sessions_per_week=sessions_per_week, effective_date=effective_date,
        expiration_date=expiration_date, status="DRAFT",
    )
    authorizations[a["id"]] = a
    return ok(to_public(a), 201)


@app.route("/sbmb/iep-authorizations/<authorization_id>", methods=["GET"])
def get_authorization(authorization_id):
    require_auth(ALL_ROLES)
    a = get_or_404(authorizations, authorization_id, "ERR_AUTHORIZATION_NOT_FOUND")
    return ok(to_public(a))


@app.route("/sbmb/iep-authorizations", methods=["GET"])
def list_authorizations():
    require_auth(ALL_ROLES)
    student_id = request.args.get("student_id")
    status = request.args.get("status")
    items = [a for a in authorizations.values()
             if (student_id is None or a["student_id"] == student_id)
             and (status is None or a["status"] == status)]
    page, limit, offset, total = list_page(items)
    return ok_list(page, limit, offset, total)


@app.route("/sbmb/iep-authorizations/<authorization_id>/activate", methods=["POST"])
def activate_authorization(authorization_id):
    require_auth({"MedicaidCoordinator"})
    a = get_or_404(authorizations, authorization_id, "ERR_AUTHORIZATION_NOT_FOUND")
    if a["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Authorization is not DRAFT")
    a["status"] = "ACTIVE"
    touch(a)
    return ok(to_public(a))


@app.route("/sbmb/iep-authorizations/<authorization_id>/discontinue", methods=["POST"])
def discontinue_authorization(authorization_id):
    require_auth({"MedicaidCoordinator"})
    a = get_or_404(authorizations, authorization_id, "ERR_AUTHORIZATION_NOT_FOUND")
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Authorization is not ACTIVE")
    discontinue_authorization_cascade(a)
    return ok(to_public(a))


# ===========================================================================
# Parental Consents
# ===========================================================================
@app.route("/sbmb/parental-consents", methods=["POST"])
def create_consent():
    require_auth({"MedicaidCoordinator"})
    data = body_json()
    student_id = req_str(data, "student_id")
    consent_type = req_enum(data, "consent_type", {"BILLING", "DISCLOSURE"})
    signed_by = req_str(data, "signed_by")
    get_or_404(students, student_id, "ERR_STUDENT_NOT_FOUND")
    c = new_entity(student_id=student_id, consent_type=consent_type, signed_by=signed_by,
                   status="PENDING", granted_date=None, revoked_date=None)
    consents[c["id"]] = c
    return ok(to_public(c), 201)


@app.route("/sbmb/parental-consents/<consent_id>", methods=["GET"])
def get_consent(consent_id):
    require_auth(ALL_ROLES)
    c = get_or_404(consents, consent_id, "ERR_CONSENT_NOT_FOUND")
    return ok(to_public(c))


@app.route("/sbmb/parental-consents", methods=["GET"])
def list_consents():
    require_auth(ALL_ROLES)
    student_id = request.args.get("student_id")
    status = request.args.get("status")
    items = [c for c in consents.values()
             if (student_id is None or c["student_id"] == student_id)
             and (status is None or c["status"] == status)]
    page, limit, offset, total = list_page(items)
    return ok_list(page, limit, offset, total)


@app.route("/sbmb/parental-consents/<consent_id>/grant", methods=["POST"])
def grant_consent(consent_id):
    require_auth({"MedicaidCoordinator"})
    c = get_or_404(consents, consent_id, "ERR_CONSENT_NOT_FOUND")
    if c["status"] not in ("PENDING", "REVOKED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Consent is not PENDING or REVOKED")
    c["status"] = "GRANTED"
    c["granted_date"] = iso_now()
    c["revoked_date"] = None
    touch(c)
    return ok(to_public(c))


@app.route("/sbmb/parental-consents/<consent_id>/revoke", methods=["POST"])
def revoke_consent(consent_id):
    require_auth({"MedicaidCoordinator"})
    c = get_or_404(consents, consent_id, "ERR_CONSENT_NOT_FOUND")
    if c["status"] != "GRANTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Consent is not GRANTED")
    c["status"] = "REVOKED"
    c["revoked_date"] = iso_now()
    touch(c)
    return ok(to_public(c))


def student_has_billing_consent(student_id):
    for c in consents.values():
        if c["student_id"] == student_id and c["consent_type"] == "BILLING" and c["status"] == "GRANTED":
            return True
    return False


# ===========================================================================
# Service Logs
# ===========================================================================
@app.route("/sbmb/service-logs", methods=["POST"])
def create_service_log():
    uid, role = require_auth({"ServiceProvider"})
    data = body_json()
    iep_authorization_id = req_str(data, "iep_authorization_id")
    provider_id = req_str(data, "provider_id")
    student_id = req_str(data, "student_id")
    service_date = req_str(data, "service_date")
    start_time = req_str(data, "start_time")
    end_time = req_str(data, "end_time")
    delivered_minutes = req_int(data, "delivered_minutes")
    group_size = opt_int(data, "group_size", 1)
    svc_date = parse_date(service_date)
    st_dt = parse_iso_dt(start_time)
    en_dt = parse_iso_dt(end_time)

    # FK existence (body), in input order
    auth = get_or_404(authorizations, iep_authorization_id, "ERR_AUTHORIZATION_NOT_FOUND")
    get_or_404(providers, provider_id, "ERR_PROVIDER_NOT_FOUND")
    get_or_404(students, student_id, "ERR_STUDENT_NOT_FOUND")

    # ownership
    if uid != provider_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the delivering provider")

    # provider credentialed (ACTIVE credential covering service_date)
    if not provider_has_credential(provider_id, svc_date, lazy=False):
        raise ApiError("ERR_PROVIDER_NOT_CREDENTIALED", 422, "Provider has no active credential covering service_date")

    # billing consent granted
    if not student_has_billing_consent(student_id):
        raise ApiError("ERR_CONSENT_NOT_GRANTED", 422, "Student lacks granted billing consent")

    # authorization active (with lazy expiration)
    exp = parse_date(auth["expiration_date"])
    eff = parse_date(auth["effective_date"])
    active = auth["status"] == "ACTIVE" and not (clock_date() > exp)
    if not active:
        raise ApiError("ERR_AUTHORIZATION_NOT_ACTIVE", 422, "Authorization is not active")

    # service window
    if not (eff <= svc_date <= exp):
        raise ApiError("ERR_SERVICE_OUTSIDE_AUTH_WINDOW", 422, "service_date outside authorization window")

    # double booking (half-open interval overlap, same provider, non-void logs)
    for log in service_logs.values():
        if log["provider_id"] != provider_id or log["status"] == "VOID":
            continue
        o_start = parse_iso_dt(log["start_time"])
        o_end = parse_iso_dt(log["end_time"])
        if st_dt < o_end and o_start < en_dt:
            raise ApiError("ERR_PROVIDER_DOUBLE_BOOKED", 409, "Provider session overlaps an existing log")

    log = new_entity(
        iep_authorization_id=iep_authorization_id, provider_id=provider_id, student_id=student_id,
        claim_id=None, service_date=service_date, start_time=start_time, end_time=end_time,
        delivered_minutes=delivered_minutes, group_size=group_size,
        documentation_note=None, return_reason=None,
        delivered_units=0, charge_cents=0, status="LOGGED",
    )
    service_logs[log["id"]] = log
    return ok(to_public(log), 201)


@app.route("/sbmb/service-logs/<log_id>", methods=["GET"])
def get_service_log(log_id):
    require_auth(ALL_ROLES)
    log = get_or_404(service_logs, log_id, "ERR_SERVICE_LOG_NOT_FOUND")
    return ok(to_public(log))


@app.route("/sbmb/service-logs", methods=["GET"])
def list_service_logs():
    require_auth(ALL_ROLES)
    f_auth = request.args.get("iep_authorization_id")
    f_prov = request.args.get("provider_id")
    f_stud = request.args.get("student_id")
    f_claim = request.args.get("claim_id")
    f_status = request.args.get("status")
    items = [l for l in service_logs.values()
             if (f_auth is None or l["iep_authorization_id"] == f_auth)
             and (f_prov is None or l["provider_id"] == f_prov)
             and (f_stud is None or l["student_id"] == f_stud)
             and (f_claim is None or l.get("claim_id") == f_claim)
             and (f_status is None or l["status"] == f_status)]
    page, limit, offset, total = list_page(items)
    return ok_list(page, limit, offset, total)


@app.route("/sbmb/service-logs/<log_id>/document", methods=["POST"])
def document_service_log(log_id):
    uid, role = require_auth({"ServiceProvider"})
    log = get_or_404(service_logs, log_id, "ERR_SERVICE_LOG_NOT_FOUND")
    data = body_json()
    documentation_note = req_str(data, "documentation_note")
    if uid != log["provider_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the delivering provider")
    if log["status"] != "LOGGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Service log is not LOGGED")
    log["documentation_note"] = documentation_note
    log["status"] = "DOCUMENTED"
    touch(log)
    return ok(to_public(log))


@app.route("/sbmb/service-logs/<log_id>/verify", methods=["POST"])
def verify_service_log(log_id):
    require_auth({"BillingCoordinator"})
    log = get_or_404(service_logs, log_id, "ERR_SERVICE_LOG_NOT_FOUND")
    if log["status"] != "DOCUMENTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Service log is not DOCUMENTED")
    auth = authorizations[log["iep_authorization_id"]]
    units = rhu(Decimal(log["delivered_minutes"]) / Decimal(auth["unit_minutes"]))
    if units < 1:
        raise ApiError("ERR_ZERO_BILLABLE_UNITS", 422, "Verification yields zero billable units")
    log["delivered_units"] = units
    log["charge_cents"] = units * auth["unit_rate_cents"]
    log["status"] = "VERIFIED"
    touch(log)
    recompute_student(log["student_id"])
    return ok(to_public(log))


@app.route("/sbmb/service-logs/<log_id>/return", methods=["POST"])
def return_service_log(log_id):
    require_auth({"BillingCoordinator"})
    log = get_or_404(service_logs, log_id, "ERR_SERVICE_LOG_NOT_FOUND")
    data = body_json()
    return_reason = req_str(data, "return_reason")
    if log["status"] != "DOCUMENTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Service log is not DOCUMENTED")
    log["return_reason"] = return_reason
    log["documentation_note"] = None
    log["status"] = "LOGGED"
    touch(log)
    return ok(to_public(log))


@app.route("/sbmb/service-logs/<log_id>/void", methods=["POST"])
def void_service_log(log_id):
    require_auth({"BillingCoordinator"})
    log = get_or_404(service_logs, log_id, "ERR_SERVICE_LOG_NOT_FOUND")
    if log["status"] not in ("LOGGED", "DOCUMENTED", "VERIFIED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Service log cannot be voided from its current state")
    if log.get("claim_id") is not None:
        raise ApiError("ERR_INVALID_STATE", 409, "Attached service log cannot be voided")
    log["status"] = "VOID"
    touch(log)
    recompute_student(log["student_id"])
    return ok(to_public(log))


# ===========================================================================
# Claims
# ===========================================================================
@app.route("/sbmb/claims", methods=["POST"])
def create_claim():
    require_auth({"BillingCoordinator"})
    data = body_json()
    student_id = req_str(data, "student_id")
    service_month = req_str(data, "service_month")
    get_or_404(students, student_id, "ERR_STUDENT_NOT_FOUND")
    cl = new_entity(
        student_id=student_id, service_month=service_month, status="DRAFT",
        total_charge_cents=0, interim_payment_cents=0, denial_reason=None,
        rebill_count=0, submitted_date=None, attached_log_count=0,
    )
    claims[cl["id"]] = cl
    return ok(to_public(cl), 201)


@app.route("/sbmb/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    require_auth(ALL_ROLES)
    cl = get_or_404(claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    return ok(to_public(cl))


@app.route("/sbmb/claims", methods=["GET"])
def list_claims():
    require_auth(ALL_ROLES)
    student_id = request.args.get("student_id")
    status = request.args.get("status")
    items = [c for c in claims.values()
             if (student_id is None or c["student_id"] == student_id)
             and (status is None or c["status"] == status)]
    page, limit, offset, total = list_page(items)
    return ok_list(page, limit, offset, total)


@app.route("/sbmb/claims/<claim_id>/attach", methods=["POST"])
def attach_claim(claim_id):
    require_auth({"BillingCoordinator"})
    cl = get_or_404(claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    data = body_json()
    service_log_id = req_str(data, "service_log_id")
    log = get_or_404(service_logs, service_log_id, "ERR_SERVICE_LOG_NOT_FOUND")
    if cl["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not DRAFT")
    if log["status"] != "VERIFIED" or log.get("claim_id") is not None:
        raise ApiError("ERR_LOG_NOT_BILLABLE", 409, "Service log is not verified-and-unattached")
    if log["student_id"] != cl["student_id"]:
        raise ApiError("ERR_LOG_NOT_BILLABLE", 409, "Service log belongs to a different student")
    log["claim_id"] = cl["id"]
    log["status"] = "CLAIMED"
    touch(log)
    recompute_claim(cl)
    touch(cl)
    return ok(to_public(cl))


def attached_logs_of(claim):
    return [l for l in service_logs.values()
            if l.get("claim_id") == claim["id"] and l["status"] in ("CLAIMED", "PAID", "DENIED")]


TIMELY_FILING_DAYS = 365


def _submit_guards(cl):
    logs = attached_logs_of(cl)
    if cl["attached_log_count"] < 1 or len(logs) < 1:
        raise ApiError("ERR_CLAIM_NO_ENCOUNTERS", 422, "Claim has no attached encounters")
    for log in logs:
        if not provider_has_credential(log["provider_id"], parse_date(log["service_date"]), lazy=True):
            raise ApiError("ERR_PROVIDER_NOT_CREDENTIALED", 422, "An attached log's provider is not credentialed")
    max_service = max(parse_date(log["service_date"]) for log in logs)
    if (clock_date() - max_service).days > TIMELY_FILING_DAYS:
        raise ApiError("ERR_TIMELY_FILING_EXCEEDED", 422, "Claim exceeds timely filing window")


@app.route("/sbmb/claims/<claim_id>/submit", methods=["POST"])
def submit_claim(claim_id):
    require_auth({"BillingCoordinator"})
    cl = get_or_404(claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    if cl["status"] not in ("DRAFT", "DENIED"):
        raise ApiError("ERR_CLAIM_NOT_SUBMITTABLE", 409, "Claim is not submittable")
    _submit_guards(cl)
    if cl["status"] == "DENIED":
        # rebill
        cl["rebill_count"] += 1
        cl["denial_reason"] = None
        for log in attached_logs_of(cl):
            if log["status"] == "DENIED":
                log["status"] = "CLAIMED"
                touch(log)
    cl["status"] = "SUBMITTED"
    cl["submitted_date"] = iso_now()
    touch(cl)
    return ok(to_public(cl))


@app.route("/sbmb/claims/<claim_id>/adjudicate", methods=["POST"])
def adjudicate_claim(claim_id):
    require_auth({"StateReviewer"})
    cl = get_or_404(claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    data = body_json()
    outcome = req_enum(data, "outcome", {"APPROVE", "DENY"})
    if cl["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not SUBMITTED")
    if outcome == "APPROVE":
        cl["interim_payment_cents"] = cl["total_charge_cents"]
        cl["status"] = "PAID"
        for log in attached_logs_of(cl):
            if log["status"] == "CLAIMED":
                log["status"] = "PAID"
                touch(log)
        touch(cl)
        recompute_student(cl["student_id"])
    else:
        denial_reason = req_enum(data, "denial_reason",
                                 {"MISSING_CONSENT", "CREDENTIAL_LAPSED", "DUPLICATE_CLAIM", "DOC_INCOMPLETE"})
        cl["denial_reason"] = denial_reason
        cl["status"] = "DENIED"
        for log in attached_logs_of(cl):
            if log["status"] == "CLAIMED":
                log["status"] = "DENIED"
                touch(log)
        touch(cl)
    return ok(to_public(cl))


@app.route("/sbmb/claims/<claim_id>/void", methods=["POST"])
def void_claim(claim_id):
    require_auth({"BillingCoordinator"})
    cl = get_or_404(claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    if cl["status"] not in ("DRAFT", "DENIED", "PAID"):
        raise ApiError("ERR_INVALID_STATE", 409, "Claim cannot be voided from its current state")
    for log in attached_logs_of(cl):
        log["status"] = "VERIFIED"
        log["claim_id"] = None
        touch(log)
    cl["total_charge_cents"] = 0
    cl["interim_payment_cents"] = 0
    cl["attached_log_count"] = 0
    cl["status"] = "VOID"
    touch(cl)
    recompute_student(cl["student_id"])
    return ok(to_public(cl))


# ===========================================================================
# RMTS Quarters
# ===========================================================================
@app.route("/sbmb/rmts-quarters", methods=["POST"])
def create_quarter():
    require_auth({"MedicaidCoordinator"})
    data = body_json()
    fiscal_quarter = req_str(data, "fiscal_quarter")
    q = new_entity(
        fiscal_quarter=fiscal_quarter, status="OPEN", total_moments=0,
        responded_moments=0, medicaid_eligible_moments=0, medicaid_eligibility_ratio=0,
    )
    quarters[q["id"]] = q
    return ok(to_public(q), 201)


@app.route("/sbmb/rmts-quarters/<quarter_id>", methods=["GET"])
def get_quarter(quarter_id):
    require_auth(ALL_ROLES)
    q = get_or_404(quarters, quarter_id, "ERR_QUARTER_NOT_FOUND")
    return ok(to_public(q))


MIN_RESPONDED_MOMENTS = 4


def recompute_quarter_counts(q):
    responded = 0
    eligible = 0
    for m in moments.values():
        if m["rmts_quarter_id"] == q["id"] and m["status"] == "CODED":
            responded += 1
            if m["is_medicaid_eligible_moment"]:
                eligible += 1
    q["responded_moments"] = responded
    q["medicaid_eligible_moments"] = eligible


@app.route("/sbmb/rmts-quarters/<quarter_id>/close", methods=["POST"])
def close_quarter(quarter_id):
    require_auth({"MedicaidCoordinator"})
    q = get_or_404(quarters, quarter_id, "ERR_QUARTER_NOT_FOUND")
    if q["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Quarter is not OPEN")
    if q["responded_moments"] < MIN_RESPONDED_MOMENTS:
        raise ApiError("ERR_INSUFFICIENT_SAMPLE", 422, "Not enough responded moments to close")
    ratio = rhu4(Decimal(q["medicaid_eligible_moments"]) / Decimal(q["responded_moments"]))
    q["medicaid_eligibility_ratio"] = float(ratio)
    q["status"] = "CLOSED"
    touch(q)
    return ok(to_public(q))


# ===========================================================================
# RMTS Moments
# ===========================================================================
@app.route("/sbmb/rmts-moments", methods=["POST"])
def create_moment():
    require_auth({"MedicaidCoordinator"})
    data = body_json()
    rmts_quarter_id = req_str(data, "rmts_quarter_id")
    provider_id = req_str(data, "provider_id")
    moment_timestamp = req_str(data, "moment_timestamp")
    q = get_or_404(quarters, rmts_quarter_id, "ERR_QUARTER_NOT_FOUND")
    get_or_404(providers, provider_id, "ERR_PROVIDER_NOT_FOUND")
    if q["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Quarter is not OPEN")
    m = new_entity(
        rmts_quarter_id=rmts_quarter_id, provider_id=provider_id, moment_timestamp=moment_timestamp,
        activity_response=None, activity_category=None, is_medicaid_eligible_moment=False,
        status="GENERATED",
    )
    moments[m["id"]] = m
    q["total_moments"] += 1
    touch(q)
    return ok(to_public(m), 201)


@app.route("/sbmb/rmts-moments/<moment_id>", methods=["GET"])
def get_moment(moment_id):
    require_auth(ALL_ROLES)
    m = get_or_404(moments, moment_id, "ERR_MOMENT_NOT_FOUND")
    return ok(to_public(m))


@app.route("/sbmb/rmts-moments", methods=["GET"])
def list_moments():
    require_auth(ALL_ROLES)
    f_quarter = request.args.get("rmts_quarter_id")
    f_prov = request.args.get("provider_id")
    f_status = request.args.get("status")
    items = [m for m in moments.values()
             if (f_quarter is None or m["rmts_quarter_id"] == f_quarter)
             and (f_prov is None or m["provider_id"] == f_prov)
             and (f_status is None or m["status"] == f_status)]
    page, limit, offset, total = list_page(items)
    return ok_list(page, limit, offset, total)


@app.route("/sbmb/rmts-moments/<moment_id>/respond", methods=["POST"])
def respond_moment(moment_id):
    uid, role = require_auth({"ServiceProvider"})
    m = get_or_404(moments, moment_id, "ERR_MOMENT_NOT_FOUND")
    data = body_json()
    activity_response = req_str(data, "activity_response")
    if uid != m["provider_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the sampled provider")
    q = quarters[m["rmts_quarter_id"]]
    if m["status"] != "GENERATED" or q["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Moment cannot be responded from its current state")
    m["activity_response"] = activity_response
    m["status"] = "RESPONDED"
    touch(m)
    return ok(to_public(m))


@app.route("/sbmb/rmts-moments/<moment_id>/code", methods=["POST"])
def code_moment(moment_id):
    require_auth({"MedicaidCoordinator"})
    m = get_or_404(moments, moment_id, "ERR_MOMENT_NOT_FOUND")
    data = body_json()
    activity_category = req_enum(data, "activity_category",
                                 {"DIRECT_MEDICAL", "MEDICAL_ADMIN", "GENERAL_ADMIN",
                                  "NON_MEDICAL", "NON_RESPONSE"})
    q = quarters[m["rmts_quarter_id"]]
    if m["status"] != "RESPONDED" or q["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Moment cannot be coded from its current state")
    m["activity_category"] = activity_category
    m["is_medicaid_eligible_moment"] = activity_category in ("DIRECT_MEDICAL", "MEDICAL_ADMIN")
    m["status"] = "CODED"
    touch(m)
    recompute_quarter_counts(q)
    touch(q)
    return ok(to_public(m))


# ===========================================================================
# Cost Settlements
# ===========================================================================
@app.route("/sbmb/cost-settlements", methods=["POST"])
def create_settlement():
    require_auth({"MedicaidCoordinator"})
    data = body_json()
    rmts_quarter_id = req_str(data, "rmts_quarter_id")
    certified_cost_cents = req_int(data, "certified_cost_cents")
    iep_ratio_bps = req_int(data, "iep_ratio_bps")
    fmap_bps = req_int(data, "fmap_bps")
    interim_paid_cents = req_int(data, "interim_paid_cents")
    expected_rmts_quarter_version = req_int(data, "expected_rmts_quarter_version")
    q = get_or_404(quarters, rmts_quarter_id, "ERR_QUARTER_NOT_FOUND")
    if q["status"] != "CLOSED":
        raise ApiError("ERR_QUARTER_NOT_CLOSED", 422, "Linked quarter is not CLOSED")
    if expected_rmts_quarter_version != q["version"]:
        raise ApiError("ERR_STALE_QUARTER_VERSION", 412, "Stale quarter version")

    ratio = Decimal(str(q["medicaid_eligibility_ratio"]))
    medicaid_allocated = rhu(Decimal(certified_cost_cents) * ratio)
    gross = rhu(Decimal(medicaid_allocated * iep_ratio_bps) / Decimal(10000))
    federal_share = rhu(Decimal(gross * fmap_bps) / Decimal(10000))
    net = federal_share - interim_paid_cents

    s = new_entity(
        rmts_quarter_id=rmts_quarter_id, certified_cost_cents=certified_cost_cents,
        iep_ratio_bps=iep_ratio_bps, fmap_bps=fmap_bps, interim_paid_cents=interim_paid_cents,
        gross_medicaid_cost_cents=gross, federal_share_cents=federal_share,
        net_settlement_cents=net, status="CALCULATED",
    )
    settlements[s["id"]] = s
    touch(q)  # OCC: each successful settlement create bumps the quarter version by 1
    return ok(to_public(s), 201)


@app.route("/sbmb/cost-settlements/<settlement_id>", methods=["GET"])
def get_settlement(settlement_id):
    require_auth(ALL_ROLES)
    s = get_or_404(settlements, settlement_id, "ERR_SETTLEMENT_NOT_FOUND")
    return ok(to_public(s))


@app.route("/sbmb/cost-settlements", methods=["GET"])
def list_settlements():
    require_auth(ALL_ROLES)
    f_quarter = request.args.get("rmts_quarter_id")
    f_status = request.args.get("status")
    items = [s for s in settlements.values()
             if (f_quarter is None or s["rmts_quarter_id"] == f_quarter)
             and (f_status is None or s["status"] == f_status)]
    page, limit, offset, total = list_page(items)
    return ok_list(page, limit, offset, total)


@app.route("/sbmb/cost-settlements/<settlement_id>/certify", methods=["POST"])
def certify_settlement(settlement_id):
    require_auth({"MedicaidCoordinator"})
    s = get_or_404(settlements, settlement_id, "ERR_SETTLEMENT_NOT_FOUND")
    if s["status"] != "CALCULATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Settlement is not CALCULATED")
    s["status"] = "CERTIFIED"
    touch(s)
    return ok(to_public(s))


@app.route("/sbmb/cost-settlements/<settlement_id>/settle", methods=["POST"])
def settle_settlement(settlement_id):
    require_auth({"StateReviewer"})
    s = get_or_404(settlements, settlement_id, "ERR_SETTLEMENT_NOT_FOUND")
    if s["status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Settlement is not CERTIFIED")
    s["status"] = "SETTLED"
    touch(s)
    return ok(to_public(s))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
