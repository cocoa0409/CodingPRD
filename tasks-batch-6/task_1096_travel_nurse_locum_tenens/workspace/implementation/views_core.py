"""Reference data, clinicians, and licenses."""
import uuid

from app import app
from store import store, parse_instant
from common import (
    ApiError, ok, ok_list, authenticate, authorize, body, verr,
    req_str, opt_str, req_enum, opt_enum, req_int, opt_bool, req_state_code,
    req_date, opt_date, new_common, touch, pagination, paginate, READ_ROLES,
)
from serializers import (
    ser_clinician, ser_license, ser_facility, ser_per_diem,
)
from domain import (
    DISCIPLINES, SPECIALTIES, EMPLOYMENT_TYPES, LICENSE_TYPES,
)


def _uuid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    authorize(role, ["PlatformAdmin"])
    b = body()
    to_iso = req_str(b, "to_iso8601")
    try:
        store.clock = parse_instant(to_iso)
    except Exception:
        verr("to_iso8601 must be a valid ISO-8601 instant")
    return ok({"current_utc": store.now_ts()}, 200)


# ---------------------------------------------------------------------------
@app.route("/per-diem-localities", methods=["POST"])
def create_per_diem():
    _uid, role = authenticate()
    authorize(role, ["PlatformAdmin"])
    b = body()
    row = new_common(extra_common=False)
    row["id"] = _uuid()
    row["locality_code"] = req_str(b, "locality_code")
    row["state_code"] = req_state_code(b, "state_code")
    row["daily_lodging_cents"] = req_int(b, "daily_lodging_cents")
    row["daily_mie_cents"] = req_int(b, "daily_mie_cents")
    row["effective_from"] = req_date(b, "effective_from")
    store.per_diem[row["id"]] = row
    return ok(ser_per_diem(row), 201)


# ---------------------------------------------------------------------------
@app.route("/facilities", methods=["POST"])
def create_facility():
    _uid, role = authenticate()
    authorize(role, ["PlatformAdmin"])
    b = body()
    name = req_str(b, "name")
    state_code = req_state_code(b, "state_code")
    per_diem_locality_code = req_str(b, "per_diem_locality_code")
    billing_contact_email = req_str(b, "billing_contact_email")
    is_compact_member = opt_bool(b, "is_compact_member", False)
    mct = b.get("max_concurrent_travelers")
    if mct is None:
        mct = 2
    else:
        if isinstance(mct, bool) or not isinstance(mct, int):
            verr("max_concurrent_travelers must be an integer")
        if mct < 1:
            verr("max_concurrent_travelers must be >= 1")
    f = new_common(True)
    f["id"] = _uuid()
    f.update({
        "name": name, "state_code": state_code,
        "per_diem_locality_code": per_diem_locality_code,
        "billing_contact_email": billing_contact_email,
        "is_compact_member": is_compact_member,
        "max_concurrent_travelers": mct,
    })
    store.facilities[f["id"]] = f
    return ok(ser_facility(f), 201)


# ---------------------------------------------------------------------------
@app.route("/clinicians", methods=["POST"])
def create_clinician():
    _uid, role = authenticate()
    authorize(role, ["Recruiter"])
    b = body()
    c = new_common(True)
    c["id"] = _uuid()
    c.update({
        "full_name": req_str(b, "full_name"),
        "discipline": req_enum(b, "discipline", DISCIPLINES),
        "specialty": req_enum(b, "specialty", SPECIALTIES),
        "employment_type": req_enum(b, "employment_type", EMPLOYMENT_TYPES),
        "primary_residence_state": req_state_code(b, "primary_residence_state"),
        "tax_home_verified": opt_bool(b, "tax_home_verified", False),
        "status": "AVAILABLE",
        "active_assignment_count": 0,
        "ytd_taxable_wages_cents": 0,
        "ytd_nontaxable_stipend_cents": 0,
    })
    store.clinicians[c["id"]] = c
    return ok(ser_clinician(c), 201)


@app.route("/clinicians/<cid>", methods=["GET"])
def get_clinician(cid):
    _uid, role = authenticate()
    authorize(role, READ_ROLES)
    c = store.clinicians.get(cid)
    if not c:
        raise ApiError("ERR_CLINICIAN_NOT_FOUND", 404, "Clinician not found")
    return ok(ser_clinician(c), 200)


@app.route("/clinicians/<cid>/licenses", methods=["GET"])
def list_clinician_licenses(cid):
    _uid, role = authenticate()
    authorize(role, READ_ROLES)
    if cid not in store.clinicians:
        raise ApiError("ERR_CLINICIAN_NOT_FOUND", 404, "Clinician not found")
    limit, offset = pagination()
    status_f = pagination_filter("status")
    state_f = pagination_filter("state_code")
    rows = [l for l in store.licenses.values() if l["clinician_id"] == cid]
    if status_f is not None:
        rows = [l for l in rows if l["status"] == status_f]
    if state_f is not None:
        rows = [l for l in rows if l["state_code"] == state_f]
    window, total = paginate(rows, limit, offset)
    return ok_list([ser_license(l) for l in window], limit, offset, total)


# ---------------------------------------------------------------------------
@app.route("/licenses", methods=["POST"])
def create_license():
    _uid, role = authenticate()
    authorize(role, ["Recruiter"])
    b = body()
    clinician_id = req_str(b, "clinician_id")
    state_code = req_state_code(b, "state_code")
    license_type = req_enum(b, "license_type", LICENSE_TYPES)
    license_number = req_str(b, "license_number")
    expires_on = req_date(b, "expires_on")
    is_compact = opt_bool(b, "is_compact", False)
    if clinician_id not in store.clinicians:
        raise ApiError("ERR_CLINICIAN_NOT_FOUND", 404, "Clinician not found")
    lic = new_common(True)
    lic["id"] = _uuid()
    lic.update({
        "clinician_id": clinician_id, "state_code": state_code,
        "license_type": license_type, "license_number": license_number,
        "is_compact": is_compact, "expires_on": expires_on,
        "status": "PENDING_VERIFICATION",
        "verified_by_user_id": None, "verified_at": None,
    })
    store.licenses[lic["id"]] = lic
    return ok(ser_license(lic), 201)


LICENSE_STATES = {"PENDING_VERIFICATION", "VERIFIED", "SUSPENDED", "EXPIRED"}
LICENSE_EDGES = {
    "PENDING_VERIFICATION": {"VERIFIED"},
    "VERIFIED": {"SUSPENDED", "EXPIRED"},
    "SUSPENDED": {"VERIFIED"},
    "EXPIRED": set(),
}


@app.route("/licenses/<lid>/transition", methods=["POST"])
def transition_license(lid):
    uid, role = authenticate()
    authorize(role, ["CredentialingSpecialist"])
    lic = store.licenses.get(lid)
    if not lic:
        raise ApiError("ERR_LICENSE_NOT_FOUND", 404, "License not found")
    b = body()
    to = req_str(b, "to")
    if to not in LICENSE_STATES:
        verr("to must be one of %s" % sorted(LICENSE_STATES))
    if to not in LICENSE_EDGES[lic["status"]]:
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal license transition")
    lic["status"] = to
    if to == "VERIFIED":
        lic["verified_by_user_id"] = uid
        lic["verified_at"] = store.now_ts()
    touch(lic)
    return ok(ser_license(lic), 200)


def pagination_filter(name):
    from flask import request
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v
