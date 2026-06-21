"""Fertility / IVF Clinic API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding). The
deterministic clinic clock drives all temporal validation (PRD §2.5).
"""

import os

from flask import Flask

import db
import errors as E
import calculations as calc
import lookups as L
import serializers as S
import services as svc
import validators as V
from errors import ApiError, fail
from middleware import get_auth, require_roles, get_body
from response import success, error

app = Flask(__name__)
app.url_map.strict_slashes = False

ALL_ROLES = ["ClinicAdmin", "Nurse", "Embryologist", "BillingSpecialist", "Patient"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(err):
    return error(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(_e):
    return error("ERR_CLINIC_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(_e):
    return error("ERR_VALIDATION", "Method not allowed", 422)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return error("ERR_VALIDATION", "Internal error: %s" % err, 500)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def auth_and_roles(allowed):
    user_id, role = get_auth()
    require_roles(role, allowed)
    return user_id, role


# ===========================================================================
# Clinic + deterministic clock
# ===========================================================================
@app.route("/clinics", methods=["POST"])
def create_clinic():
    auth_and_roles(["ClinicAdmin"])
    body = get_body()
    name = V.req_str(body, "name")
    timezone_label = V.opt_str(body, "timezone", "UTC")
    rcl = V.opt_int(body, "room_concurrency_limit", default=2, min_value=1)
    rec = db.new_record({
        "name": name,
        "timezone": timezone_label,
        "room_concurrency_limit": rcl,
        "current_clock_utc": "1970-01-01T00:00:00.000Z",
    })
    db.clinics[rec["id"]] = rec
    return success(S.clinic(rec), status=201)


@app.route("/clinics/<clinic_id>", methods=["GET"])
def get_clinic(clinic_id):
    auth_and_roles(ALL_ROLES)
    rec = L.get_clinic(clinic_id)
    return success(S.clinic(rec))


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth_and_roles(["ClinicAdmin"])
    body = get_body()
    clinic_id = V.req_str(body, "clinic_id")
    to_iso = V.req_datetime(body, "to_iso8601")
    clinic = L.get_clinic(clinic_id)
    if V.parse_iso(to_iso) < V.parse_iso(clinic["current_clock_utc"]):
        fail(E.ERR_CLOCK_NOT_MONOTONIC, "Clock cannot move backwards")
    clinic["current_clock_utc"] = to_iso
    db.touch(clinic)
    return success(S.clinic(clinic))


# ===========================================================================
# Insurance packages
# ===========================================================================
@app.route("/clinics/<clinic_id>/packages", methods=["POST"])
def create_package(clinic_id):
    auth_and_roles(["ClinicAdmin"])
    L.get_clinic(clinic_id)
    body = get_body()
    name = V.req_str(body, "name")
    base_price = V.req_int(body, "base_price_cents", min_value=0)
    coverage_pct = V.req_number(body, "coverage_pct", min_value=0, max_value=1)
    cap = V.req_int(body, "lifetime_coverage_cap_cents", min_value=0)
    stim_covered = V.opt_bool(body, "stim_med_covered", True)
    cryo_covered = V.opt_bool(body, "cryo_storage_covered", False)
    annual_cryo = V.opt_int(body, "annual_cryo_storage_cents", default=60000,
                            min_value=0)
    rec = db.new_record({
        "clinic_id": clinic_id,
        "name": name,
        "base_price_cents": base_price,
        "coverage_pct": coverage_pct,
        "stim_med_covered": stim_covered,
        "cryo_storage_covered": cryo_covered,
        "annual_cryo_storage_cents": annual_cryo,
        "lifetime_coverage_cap_cents": cap,
        "status": "ACTIVE",
    })
    db.packages[rec["id"]] = rec
    return success(S.package(rec), status=201)


@app.route("/clinics/<clinic_id>/packages", methods=["GET"])
def list_packages(clinic_id):
    auth_and_roles(["ClinicAdmin", "BillingSpecialist", "Nurse"])
    L.get_clinic(clinic_id)
    recs = [r for r in db.packages.values() if r["clinic_id"] == clinic_id]
    data, page = L.paginate(recs, S.package)
    return success(data, pagination=page)


@app.route("/clinics/<clinic_id>/packages/<package_id>", methods=["GET"])
def get_package(clinic_id, package_id):
    auth_and_roles(["ClinicAdmin", "BillingSpecialist", "Nurse"])
    L.get_clinic(clinic_id)
    rec = L.get_package(clinic_id, package_id)
    return success(S.package(rec))


@app.route("/clinics/<clinic_id>/packages/<package_id>/retire", methods=["POST"])
def retire_package(clinic_id, package_id):
    auth_and_roles(["ClinicAdmin"])
    L.get_clinic(clinic_id)
    rec = L.get_package(clinic_id, package_id)
    rec["status"] = "RETIRED"
    db.touch(rec)
    return success(S.package(rec))


# ===========================================================================
# Patients
# ===========================================================================
@app.route("/clinics/<clinic_id>/patients", methods=["POST"])
def create_patient(clinic_id):
    auth_and_roles(["ClinicAdmin", "Nurse"])
    L.get_clinic(clinic_id)
    body = get_body()
    full_name = V.req_str(body, "full_name")
    dob = V.req_datetime_or_date(body, "date_of_birth")
    pkg_id = V.opt_str(body, "insurance_package_id")
    if pkg_id is not None:
        L.get_package(clinic_id, pkg_id)
    rec = db.new_record({
        "clinic_id": clinic_id,
        "full_name": full_name,
        "date_of_birth": dob,
        "insurance_package_id": pkg_id,
        "status": "ACTIVE",
    })
    db.patients[rec["id"]] = rec
    return success(S.patient(rec), status=201)


@app.route("/clinics/<clinic_id>/patients", methods=["GET"])
def list_patients(clinic_id):
    auth_and_roles(["ClinicAdmin", "Nurse", "BillingSpecialist"])
    L.get_clinic(clinic_id)
    from flask import request
    recs = [r for r in db.patients.values() if r["clinic_id"] == clinic_id]
    pkg_filter = request.args.get("insurance_package_id")
    if pkg_filter is not None:
        recs = [r for r in recs if r["insurance_package_id"] == pkg_filter]
    data, page = L.paginate(recs, S.patient)
    return success(data, pagination=page)


@app.route("/clinics/<clinic_id>/patients/<patient_id>", methods=["GET"])
def get_patient(clinic_id, patient_id):
    auth_and_roles(["ClinicAdmin", "Nurse", "BillingSpecialist", "Patient"])
    L.get_clinic(clinic_id)
    rec = L.get_patient(clinic_id, patient_id)
    return success(S.patient(rec))


@app.route("/clinics/<clinic_id>/patients/<patient_id>/deactivate", methods=["POST"])
def deactivate_patient(clinic_id, patient_id):
    auth_and_roles(["ClinicAdmin"])
    L.get_clinic(clinic_id)
    rec = L.get_patient(clinic_id, patient_id)
    rec["status"] = "INACTIVE"
    db.touch(rec)
    return success(S.patient(rec))


# ===========================================================================
# Donors / surrogates
# ===========================================================================
@app.route("/clinics/<clinic_id>/donors", methods=["POST"])
def create_donor(clinic_id):
    auth_and_roles(["ClinicAdmin"])
    L.get_clinic(clinic_id)
    body = get_body()
    code = V.req_str(body, "code")
    donor_type = V.req_enum(body, "donor_type", {"EGG", "SPERM"})
    rec = db.new_record({
        "clinic_id": clinic_id,
        "code": code,
        "donor_type": donor_type,
        "status": "AVAILABLE",
    })
    db.donors[rec["id"]] = rec
    return success(S.donor(rec), status=201)


@app.route("/clinics/<clinic_id>/donors", methods=["GET"])
def list_donors(clinic_id):
    auth_and_roles(["ClinicAdmin", "Nurse", "Embryologist"])
    L.get_clinic(clinic_id)
    recs = [r for r in db.donors.values() if r["clinic_id"] == clinic_id]
    data, page = L.paginate(recs, S.donor)
    return success(data, pagination=page)


@app.route("/clinics/<clinic_id>/donors/<donor_id>", methods=["GET"])
def get_donor(clinic_id, donor_id):
    auth_and_roles(["ClinicAdmin", "Nurse", "Embryologist"])
    L.get_clinic(clinic_id)
    rec = L.get_donor(clinic_id, donor_id)
    return success(S.donor(rec))


@app.route("/clinics/<clinic_id>/surrogates", methods=["POST"])
def create_surrogate(clinic_id):
    auth_and_roles(["ClinicAdmin"])
    L.get_clinic(clinic_id)
    body = get_body()
    full_name = V.req_str(body, "full_name")
    rec = db.new_record({
        "clinic_id": clinic_id,
        "full_name": full_name,
        "status": "AVAILABLE",
    })
    db.surrogates[rec["id"]] = rec
    return success(S.surrogate(rec), status=201)


@app.route("/clinics/<clinic_id>/surrogates", methods=["GET"])
def list_surrogates(clinic_id):
    auth_and_roles(["ClinicAdmin", "Nurse"])
    L.get_clinic(clinic_id)
    recs = [r for r in db.surrogates.values() if r["clinic_id"] == clinic_id]
    data, page = L.paginate(recs, S.surrogate)
    return success(data, pagination=page)


@app.route("/clinics/<clinic_id>/surrogates/<surrogate_id>", methods=["GET"])
def get_surrogate(clinic_id, surrogate_id):
    auth_and_roles(["ClinicAdmin", "Nurse"])
    L.get_clinic(clinic_id)
    rec = L.get_surrogate(clinic_id, surrogate_id)
    return success(S.surrogate(rec))


# ===========================================================================
# Consent forms (versioning)
# ===========================================================================
CONSENT_GATES = {"CYCLE_START", "RETRIEVAL", "TRANSFER", "CRYO_STORE"}


@app.route("/clinics/<clinic_id>/consent-forms", methods=["POST"])
def create_consent_form(clinic_id):
    auth_and_roles(["ClinicAdmin"])
    L.get_clinic(clinic_id)
    body = get_body()
    form_key = V.req_str(body, "form_key")
    version_label = V.req_str(body, "version_label")
    required_for = V.require(body, "required_for")
    if not isinstance(required_for, list) or not all(
            isinstance(x, str) for x in required_for):
        fail(E.ERR_VALIDATION, "required_for must be an array of strings")
    for member in required_for:
        if member not in CONSENT_GATES:
            fail(E.ERR_VALIDATION, "invalid required_for member: %s" % member)
    supersedes = V.opt_str(body, "supersedes_form_id")
    if supersedes is not None:
        L.get_consent_form(clinic_id, supersedes)
    rec = db.new_record({
        "clinic_id": clinic_id,
        "form_key": form_key,
        "version_label": version_label,
        "required_for": required_for,
        "status": "DRAFT",
        "supersedes_form_id": supersedes,
    })
    db.consent_forms[rec["id"]] = rec
    return success(S.consent_form(rec), status=201)


@app.route("/clinics/<clinic_id>/consent-forms", methods=["GET"])
def list_consent_forms(clinic_id):
    auth_and_roles(["ClinicAdmin", "Nurse", "Patient"])
    L.get_clinic(clinic_id)
    from flask import request
    recs = [r for r in db.consent_forms.values() if r["clinic_id"] == clinic_id]
    sup = request.args.get("supersedes_form_id")
    if sup is not None:
        recs = [r for r in recs if r.get("supersedes_form_id") == sup]
    fk = request.args.get("form_key")
    if fk is not None:
        recs = [r for r in recs if r["form_key"] == fk]
    data, page = L.paginate(recs, S.consent_form)
    return success(data, pagination=page)


@app.route("/clinics/<clinic_id>/consent-forms/<form_id>", methods=["GET"])
def get_consent_form(clinic_id, form_id):
    auth_and_roles(["ClinicAdmin", "Nurse", "Patient"])
    L.get_clinic(clinic_id)
    rec = L.get_consent_form(clinic_id, form_id)
    return success(S.consent_form(rec))


@app.route("/clinics/<clinic_id>/consent-forms/<form_id>/publish", methods=["POST"])
def publish_consent_form(clinic_id, form_id):
    auth_and_roles(["ClinicAdmin"])
    L.get_clinic(clinic_id)
    form = L.get_consent_form(clinic_id, form_id)
    # state precondition
    if form["status"] != "DRAFT":
        fail(E.ERR_CONSENT_FORM_BAD_STATE, "Form not DRAFT")
    # business-referential: supersede target must be PUBLISHED
    target = None
    sup = form.get("supersedes_form_id")
    if sup:
        target = L.get_consent_form(clinic_id, sup)
        if target["status"] != "PUBLISHED":
            fail(E.ERR_SUPERSEDE_TARGET_NOT_PUBLISHED,
                 "Supersede target not PUBLISHED")
    form["status"] = "PUBLISHED"
    db.touch(form)
    if target is not None:
        # L1: target -> SUPERSEDED
        target["status"] = "SUPERSEDED"
        db.touch(target)
        # L2: ACTIVE consents pinned to target -> STALE
        for consent in db.patient_consents.values():
            if (consent["consent_form_id"] == target["id"]
                    and consent["status"] == "ACTIVE"):
                consent["status"] = "STALE"
                db.touch(consent)
    return success(S.consent_form(form))


# ===========================================================================
# Patient consents (signing; version pinning)
# ===========================================================================
@app.route("/clinics/<clinic_id>/patient-consents", methods=["POST"])
def sign_consent(clinic_id):
    user_id, role = auth_and_roles(["Patient", "Nurse"])
    L.get_clinic(clinic_id)
    body = get_body()
    patient_id = V.req_str(body, "patient_id")
    form_id = V.req_str(body, "consent_form_id")
    # body FK existence
    patient = L.get_patient(clinic_id, patient_id)
    form = L.get_consent_form(clinic_id, form_id)
    # patient self-ownership when caller is Patient
    if role == "Patient" and user_id != patient_id:
        fail(E.ERR_FORBIDDEN_ROLE, "Patient may only sign their own consent")
    # form must be PUBLISHED (non-stale)
    if form["status"] != "PUBLISHED":
        fail(E.ERR_CONSENT_FORM_NOT_PUBLISHED, "Form not PUBLISHED")
    clinic = db.clinics[clinic_id]
    rec = db.new_record({
        "patient_id": patient_id,
        "consent_form_id": form_id,
        "pinned_form_version": form["version"],
        "pinned_form_status_at_sign": "PUBLISHED",
        "status": "ACTIVE",
        "signed_at": clinic["current_clock_utc"],
    })
    db.patient_consents[rec["id"]] = rec
    return success(S.patient_consent(rec), status=201)


@app.route("/clinics/<clinic_id>/patient-consents", methods=["GET"])
def list_consents(clinic_id):
    user_id, role = auth_and_roles(["ClinicAdmin", "Nurse", "Patient"])
    L.get_clinic(clinic_id)
    from flask import request
    recs = []
    for r in db.patient_consents.values():
        pat = db.patients.get(r["patient_id"])
        if pat is None or pat.get("clinic_id") != clinic_id:
            continue
        recs.append(r)
    if role == "Patient":
        recs = [r for r in recs if r["patient_id"] == user_id]
    pid = request.args.get("patient_id")
    if pid is not None:
        recs = [r for r in recs if r["patient_id"] == pid]
    fid = request.args.get("consent_form_id")
    if fid is not None:
        recs = [r for r in recs if r["consent_form_id"] == fid]
    data, page = L.paginate(recs, S.patient_consent)
    return success(data, pagination=page)


@app.route("/clinics/<clinic_id>/patient-consents/<consent_id>", methods=["GET"])
def get_consent(clinic_id, consent_id):
    auth_and_roles(["ClinicAdmin", "Nurse", "Patient"])
    L.get_clinic(clinic_id)
    rec = L.get_consent(clinic_id, consent_id)
    return success(S.patient_consent(rec))


@app.route("/clinics/<clinic_id>/patient-consents/<consent_id>/revoke", methods=["POST"])
def revoke_consent(clinic_id, consent_id):
    user_id, role = auth_and_roles(["Patient"])
    L.get_clinic(clinic_id)
    rec = L.get_consent(clinic_id, consent_id)
    if user_id != rec["patient_id"]:
        fail(E.ERR_FORBIDDEN_ROLE, "Patient may only revoke their own consent")
    if rec["status"] != "ACTIVE":
        fail(E.ERR_CONSENT_BAD_STATE, "Consent not ACTIVE")
    rec["status"] = "REVOKED"
    db.touch(rec)
    return success(S.patient_consent(rec))


# ===========================================================================
# Cryo tanks
# ===========================================================================
@app.route("/clinics/<clinic_id>/tanks", methods=["POST"])
def create_tank(clinic_id):
    auth_and_roles(["ClinicAdmin", "Embryologist"])
    L.get_clinic(clinic_id)
    body = get_body()
    label = V.req_str(body, "label")
    capacity = V.req_int(body, "capacity_slots", min_value=1)
    rec = db.new_record({
        "clinic_id": clinic_id,
        "label": label,
        "capacity_slots": capacity,
        "reserved_slots": 0,
        "status": "ONLINE",
    })
    db.tanks[rec["id"]] = rec
    return success(S.tank(rec), status=201)


@app.route("/clinics/<clinic_id>/tanks", methods=["GET"])
def list_tanks(clinic_id):
    auth_and_roles(["ClinicAdmin", "Embryologist"])
    L.get_clinic(clinic_id)
    recs = [r for r in db.tanks.values() if r["clinic_id"] == clinic_id]
    data, page = L.paginate(recs, S.tank)
    return success(data, pagination=page)


@app.route("/clinics/<clinic_id>/tanks/<tank_id>", methods=["GET"])
def get_tank(clinic_id, tank_id):
    auth_and_roles(["ClinicAdmin", "Embryologist"])
    L.get_clinic(clinic_id)
    rec = L.get_tank(clinic_id, tank_id)
    return success(S.tank(rec))


@app.route("/clinics/<clinic_id>/tanks/<tank_id>/set-maintenance", methods=["POST"])
def set_tank_maintenance(clinic_id, tank_id):
    auth_and_roles(["ClinicAdmin", "Embryologist"])
    L.get_clinic(clinic_id)
    rec = L.get_tank(clinic_id, tank_id)
    rec["status"] = "MAINTENANCE"
    db.touch(rec)
    return success(S.tank(rec))


# ===========================================================================
# Treatment cycles
# ===========================================================================
@app.route("/clinics/<clinic_id>/cycles", methods=["POST"])
def create_cycle(clinic_id):
    auth_and_roles(["Nurse"])
    L.get_clinic(clinic_id)
    body = get_body()
    patient_id = V.req_str(body, "patient_id")
    donor_id = V.opt_str(body, "donor_profile_id")
    surrogate_id = V.opt_str(body, "surrogate_profile_id")
    # body FK existence
    patient = L.get_patient(clinic_id, patient_id)
    donor = L.get_donor(clinic_id, donor_id) if donor_id else None
    surrogate = L.get_surrogate(clinic_id, surrogate_id) if surrogate_id else None
    # business referential
    if patient["status"] != "ACTIVE":
        fail(E.ERR_PATIENT_INACTIVE, "Patient is INACTIVE")
    pkg_id = patient.get("insurance_package_id")
    if pkg_id is not None:
        pkg = db.packages.get(pkg_id)
        if pkg is not None and pkg["status"] == "RETIRED":
            fail(E.ERR_PACKAGE_RETIRED, "Insurance package is RETIRED")
    if donor is not None and donor["status"] != "AVAILABLE":
        fail(E.ERR_DONOR_NOT_AVAILABLE, "Donor not AVAILABLE")
    rec = db.new_record({
        "patient_id": patient_id,
        "insurance_package_id": pkg_id,
        "donor_profile_id": donor_id,
        "surrogate_profile_id": surrogate_id,
        "protocol_status": "DRAFT",
        "billing_status": "UNBILLED",
        "oocytes_retrieved": 0,
        "embryos_fertilized": 0,
        "estimated_patient_owed_cents": 0,
        "final_patient_owed_cents": 0,
        "insurer_paid_cents": 0,
        "gross_charge_cents": 0,
        "cancellation_fee_cents": 0,
        "_stim_start_utc": None,
    })
    db.cycles[rec["id"]] = rec
    # cross-entity reservations
    if donor is not None:
        donor["status"] = "RESERVED"
        db.touch(donor)
    if surrogate is not None:
        surrogate["status"] = "MATCHED"
        db.touch(surrogate)
    return success(S.cycle(rec), status=201)


@app.route("/clinics/<clinic_id>/cycles", methods=["GET"])
def list_cycles(clinic_id):
    user_id, role = auth_and_roles(ALL_ROLES)
    L.get_clinic(clinic_id)
    from flask import request
    recs = []
    for r in db.cycles.values():
        pat = db.patients.get(r["patient_id"])
        if pat is None or pat.get("clinic_id") != clinic_id:
            continue
        recs.append(r)
    if role == "Patient":
        recs = [r for r in recs if r["patient_id"] == user_id]
    for key in ("patient_id", "insurance_package_id", "donor_profile_id",
                "surrogate_profile_id"):
        val = request.args.get(key)
        if val is not None:
            recs = [r for r in recs if r.get(key) == val]
    data, page = L.paginate(recs, S.cycle)
    return success(data, pagination=page)


@app.route("/clinics/<clinic_id>/cycles/<cycle_id>", methods=["GET"])
def get_cycle(clinic_id, cycle_id):
    auth_and_roles(ALL_ROLES)
    L.get_clinic(clinic_id)
    rec = L.get_cycle(clinic_id, cycle_id)
    return success(S.cycle(rec))


@app.route("/clinics/<clinic_id>/cycles/<cycle_id>/start-stim", methods=["POST"])
def start_stim(clinic_id, cycle_id):
    auth_and_roles(["Nurse"])
    clinic = L.get_clinic(clinic_id)
    cycle = L.get_cycle(clinic_id, cycle_id)
    if cycle["protocol_status"] != "DRAFT":
        fail(E.ERR_CYCLE_BAD_PROTOCOL_STATE, "Cycle not DRAFT")
    patient = db.patients.get(cycle["patient_id"])
    if patient is None or patient["status"] != "ACTIVE":
        fail(E.ERR_PATIENT_INACTIVE, "Patient is INACTIVE")
    svc.require_consent(cycle["patient_id"], "CYCLE_START")
    cycle["protocol_status"] = "STIM"
    cycle["_stim_start_utc"] = clinic["current_clock_utc"]
    db.touch(cycle)
    return success(S.cycle(cycle))


@app.route("/clinics/<clinic_id>/cycles/<cycle_id>/retrieve", methods=["POST"])
def retrieve(clinic_id, cycle_id):
    auth_and_roles(["Nurse"])
    L.get_clinic(clinic_id)
    cycle = L.get_cycle(clinic_id, cycle_id)
    body = get_body()
    oocytes = V.req_int(body, "oocytes_retrieved", min_value=0)
    if cycle["protocol_status"] != "STIM":
        fail(E.ERR_CYCLE_BAD_PROTOCOL_STATE, "Cycle not STIM")
    svc.require_consent(cycle["patient_id"], "RETRIEVAL")
    cycle["protocol_status"] = "RETRIEVAL"
    cycle["oocytes_retrieved"] = oocytes
    db.touch(cycle)
    return success(S.cycle(cycle))


@app.route("/clinics/<clinic_id>/cycles/<cycle_id>/revert-to-stim", methods=["POST"])
def revert_to_stim(clinic_id, cycle_id):
    auth_and_roles(["Nurse"])
    L.get_clinic(clinic_id)
    cycle = L.get_cycle(clinic_id, cycle_id)
    if cycle["protocol_status"] != "RETRIEVAL":
        fail(E.ERR_CYCLE_BAD_PROTOCOL_STATE, "Cycle not RETRIEVAL")
    cycle["protocol_status"] = "STIM"
    cycle["oocytes_retrieved"] = 0
    db.touch(cycle)
    return success(S.cycle(cycle))


@app.route("/clinics/<clinic_id>/cycles/<cycle_id>/fertilize", methods=["POST"])
def fertilize(clinic_id, cycle_id):
    auth_and_roles(["Embryologist"])
    L.get_clinic(clinic_id)
    cycle = L.get_cycle(clinic_id, cycle_id)
    body = get_body()
    embryos = V.req_int(body, "embryos_fertilized", min_value=0)
    if cycle["protocol_status"] != "RETRIEVAL":
        fail(E.ERR_CYCLE_BAD_PROTOCOL_STATE, "Cycle not RETRIEVAL")
    if embryos > cycle["oocytes_retrieved"]:
        fail(E.ERR_EMBRYO_COUNT_EXCEEDS_OOCYTES,
             "embryos_fertilized exceeds oocytes_retrieved")
    cycle["protocol_status"] = "FERTILIZATION"
    cycle["embryos_fertilized"] = embryos
    db.touch(cycle)
    # donor RESERVED -> CONSUMED
    donor_id = cycle.get("donor_profile_id")
    if donor_id:
        donor = db.donors.get(donor_id)
        if donor is not None and donor["status"] == "RESERVED":
            donor["status"] = "CONSUMED"
            db.touch(donor)
    return success(S.cycle(cycle))


@app.route("/clinics/<clinic_id>/cycles/<cycle_id>/transfer", methods=["POST"])
def transfer(clinic_id, cycle_id):
    auth_and_roles(["Embryologist"])
    L.get_clinic(clinic_id)
    cycle = L.get_cycle(clinic_id, cycle_id)
    if cycle["protocol_status"] != "FERTILIZATION":
        fail(E.ERR_CYCLE_BAD_PROTOCOL_STATE, "Cycle not FERTILIZATION")
    if cycle["embryos_fertilized"] < 1:
        fail(E.ERR_NO_EMBRYOS_AVAILABLE, "No embryos available")
    svc.require_consent(cycle["patient_id"], "TRANSFER")
    cycle["protocol_status"] = "FRESH_TRANSFER"
    db.touch(cycle)
    return success(S.cycle(cycle))


@app.route("/clinics/<clinic_id>/cycles/<cycle_id>/freeze-all", methods=["POST"])
def freeze_all(clinic_id, cycle_id):
    auth_and_roles(["Embryologist"])
    L.get_clinic(clinic_id)
    cycle = L.get_cycle(clinic_id, cycle_id)
    if cycle["protocol_status"] != "FERTILIZATION":
        fail(E.ERR_CYCLE_BAD_PROTOCOL_STATE, "Cycle not FERTILIZATION")
    if cycle["embryos_fertilized"] < 1:
        fail(E.ERR_NO_EMBRYOS_AVAILABLE, "No embryos available")
    cycle["protocol_status"] = "FREEZE_ALL"
    db.touch(cycle)
    return success(S.cycle(cycle))


@app.route("/clinics/<clinic_id>/cycles/<cycle_id>/complete", methods=["POST"])
def complete_cycle(clinic_id, cycle_id):
    auth_and_roles(["Nurse"])
    L.get_clinic(clinic_id)
    cycle = L.get_cycle(clinic_id, cycle_id)
    if cycle["protocol_status"] not in ("FRESH_TRANSFER", "FREEZE_ALL"):
        fail(E.ERR_CYCLE_BAD_PROTOCOL_STATE, "Cycle not in a completable state")
    has_outcome = any(o["treatment_cycle_id"] == cycle_id
                      for o in db.outcomes.values())
    if not has_outcome:
        fail(E.ERR_OUTCOME_REQUIRED, "Cycle has no OutcomeReport")
    cycle["protocol_status"] = "COMPLETED"
    db.touch(cycle)
    return success(S.cycle(cycle))


@app.route("/clinics/<clinic_id>/cycles/<cycle_id>/cancel", methods=["POST"])
def cancel_cycle(clinic_id, cycle_id):
    auth_and_roles(["Nurse"])
    L.get_clinic(clinic_id)
    cycle = L.get_cycle(clinic_id, cycle_id)
    body = get_body()
    expected = V.req_int(body, "expected_cycle_version")
    # OCC before state/business
    if expected != cycle["version"]:
        fail(E.ERR_STALE_CYCLE_VERSION, "expected_cycle_version mismatch")
    if cycle["protocol_status"] in ("COMPLETED", "CANCELLED"):
        fail(E.ERR_CYCLE_BAD_PROTOCOL_STATE, "Cycle already terminal")
    reached = cycle["protocol_status"]
    cycle["protocol_status"] = "CANCELLED"
    cycle["cancellation_fee_cents"] = calc.cancellation_fee(reached)
    db.touch(cycle)  # increments version by 1
    svc.cancel_cascade(clinic_id, cycle)
    return success(S.cycle(cycle))


# ===========================================================================
# Medication calendar
# ===========================================================================
@app.route("/clinics/<clinic_id>/medications", methods=["POST"])
def create_medication(clinic_id):
    auth_and_roles(["Nurse"])
    L.get_clinic(clinic_id)
    body = get_body()
    cycle_id = V.req_str(body, "treatment_cycle_id")
    cycle = L.get_cycle(clinic_id, cycle_id)
    drug_name = V.req_str(body, "drug_name")
    start_off = V.req_int(body, "start_day_offset", min_value=0)
    end_off = V.req_int(body, "end_day_offset", min_value=0)
    if end_off < start_off:
        fail(E.ERR_VALIDATION, "end_day_offset must be >= start_day_offset")
    daily = V.req_int(body, "daily_dose_units", min_value=1)
    unit_price = V.req_int(body, "unit_price_cents", min_value=0)
    # closed-interval overlap for same drug on same cycle (SCHEDULED/ADMINISTERED)
    for med in db.medications.values():
        if med["treatment_cycle_id"] != cycle_id:
            continue
        if med["drug_name"] != drug_name:
            continue
        if med["status"] not in ("SCHEDULED", "ADMINISTERED"):
            continue
        if start_off <= med["end_day_offset"] and med["start_day_offset"] <= end_off:
            fail(E.ERR_MEDICATION_SCHEDULE_OVERLAP, "Medication schedule overlap")
    line_total = calc.medication_line_total(start_off, end_off, daily, unit_price)
    rec = db.new_record({
        "treatment_cycle_id": cycle_id,
        "clinic_id": clinic_id,
        "drug_name": drug_name,
        "start_day_offset": start_off,
        "end_day_offset": end_off,
        "daily_dose_units": daily,
        "unit_price_cents": unit_price,
        "line_total_cents": line_total,
        "status": "SCHEDULED",
    })
    db.medications[rec["id"]] = rec
    return success(S.medication(rec), status=201)


@app.route("/clinics/<clinic_id>/medications", methods=["GET"])
def list_medications(clinic_id):
    auth_and_roles(["ClinicAdmin", "Nurse", "BillingSpecialist", "Patient"])
    L.get_clinic(clinic_id)
    from flask import request
    recs = [r for r in db.medications.values() if r["clinic_id"] == clinic_id]
    cid = request.args.get("treatment_cycle_id")
    if cid is not None:
        recs = [r for r in recs if r["treatment_cycle_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    data, page = L.paginate(recs, S.medication)
    return success(data, pagination=page)


@app.route("/clinics/<clinic_id>/medications/<med_id>", methods=["GET"])
def get_medication(clinic_id, med_id):
    auth_and_roles(["ClinicAdmin", "Nurse", "BillingSpecialist", "Patient"])
    L.get_clinic(clinic_id)
    rec = L.get_medication(clinic_id, med_id)
    return success(S.medication(rec))


@app.route("/clinics/<clinic_id>/medications/<med_id>/administer", methods=["POST"])
def administer_medication(clinic_id, med_id):
    auth_and_roles(["Nurse"])
    L.get_clinic(clinic_id)
    rec = L.get_medication(clinic_id, med_id)
    if rec["status"] != "SCHEDULED":
        fail(E.ERR_MED_BAD_STATE, "Medication not SCHEDULED")
    rec["status"] = "ADMINISTERED"
    db.touch(rec)
    return success(S.medication(rec))


@app.route("/clinics/<clinic_id>/medications/<med_id>/cancel", methods=["POST"])
def cancel_medication(clinic_id, med_id):
    auth_and_roles(["Nurse"])
    L.get_clinic(clinic_id)
    rec = L.get_medication(clinic_id, med_id)
    if rec["status"] != "SCHEDULED":
        fail(E.ERR_MED_BAD_STATE, "Medication not SCHEDULED")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return success(S.medication(rec))


# ===========================================================================
# Monitoring appointments
# ===========================================================================
def _room_conflict(clinic, candidate_start, candidate_end, weight, exclude_id=None):
    """True if admitting [candidate_start, candidate_end) pushes instantaneous
    aggregate weight above the clinic limit (half-open intervals)."""
    limit = clinic["room_concurrency_limit"]
    cs = V.parse_iso(candidate_start)
    ce = V.parse_iso(candidate_end)
    # Gather other non-terminal appointments in the same clinic.
    others = []
    for appt in db.appointments.values():
        if appt["clinic_id"] != clinic["id"]:
            continue
        if exclude_id is not None and appt["id"] == exclude_id:
            continue
        if appt["status"] not in ("CONFIRMED", "RESCHEDULED"):
            continue
        os_ = V.parse_iso(appt["start_utc"])
        oe = V.parse_iso(appt["end_utc"])
        others.append((os_, oe, appt["room_capacity_weight"]))
    # Sweep at each candidate-overlapping segment boundary. It suffices to test
    # the instants that are start points of any interval that overlaps the
    # candidate, plus the candidate's own start.
    instants = {cs}
    for os_, oe, _w in others:
        if os_ < ce and cs < oe:  # half-open overlap with candidate
            if os_ >= cs:
                instants.add(os_)
    for t in instants:
        if not (cs <= t < ce):
            continue
        agg = weight  # candidate covers t (cs <= t < ce)
        for os_, oe, w in others:
            if os_ <= t < oe:
                agg += w
        if agg > limit:
            return True
    return False


@app.route("/clinics/<clinic_id>/monitoring-appointments", methods=["POST"])
def create_appointment(clinic_id):
    auth_and_roles(["Nurse"])
    clinic = L.get_clinic(clinic_id)
    body = get_body()
    cycle_id = V.req_str(body, "treatment_cycle_id")
    cycle = L.get_cycle(clinic_id, cycle_id)
    appt_type = V.req_enum(body, "appointment_type",
                           {"BLOODWORK", "ULTRASOUND", "CONSULT"})
    start_utc = V.req_datetime(body, "start_utc")
    end_utc = V.req_datetime(body, "end_utc")
    weight = V.opt_int(body, "room_capacity_weight", default=1, min_value=1)
    # temporal validity
    if (V.parse_iso(end_utc) <= V.parse_iso(start_utc)
            or V.parse_iso(start_utc) < V.parse_iso(clinic["current_clock_utc"])):
        fail(E.ERR_APPOINTMENT_IN_PAST, "Invalid appointment interval")
    # room overlap
    if _room_conflict(clinic, start_utc, end_utc, weight):
        fail(E.ERR_MONITORING_SLOT_CONFLICT, "Room capacity exceeded")
    rec = db.new_record({
        "treatment_cycle_id": cycle_id,
        "clinic_id": clinic_id,
        "appointment_type": appt_type,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "room_capacity_weight": weight,
        "status": "CONFIRMED",
    })
    db.appointments[rec["id"]] = rec
    return success(S.appointment(rec), status=201)


@app.route("/clinics/<clinic_id>/monitoring-appointments", methods=["GET"])
def list_appointments(clinic_id):
    auth_and_roles(["ClinicAdmin", "Nurse", "Patient"])
    L.get_clinic(clinic_id)
    from flask import request
    recs = [r for r in db.appointments.values() if r["clinic_id"] == clinic_id]
    cid = request.args.get("treatment_cycle_id")
    if cid is not None:
        recs = [r for r in recs if r["treatment_cycle_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    data, page = L.paginate(recs, S.appointment)
    return success(data, pagination=page)


@app.route("/clinics/<clinic_id>/monitoring-appointments/<appt_id>", methods=["GET"])
def get_appointment(clinic_id, appt_id):
    auth_and_roles(["ClinicAdmin", "Nurse", "Patient"])
    L.get_clinic(clinic_id)
    rec = L.get_appointment(clinic_id, appt_id)
    return success(S.appointment(rec))


@app.route("/clinics/<clinic_id>/monitoring-appointments/<appt_id>/reschedule",
           methods=["POST"])
def reschedule_appointment(clinic_id, appt_id):
    auth_and_roles(["Nurse"])
    clinic = L.get_clinic(clinic_id)
    rec = L.get_appointment(clinic_id, appt_id)
    body = get_body()
    start_utc = V.req_datetime(body, "start_utc")
    end_utc = V.req_datetime(body, "end_utc")
    if rec["status"] not in ("CONFIRMED", "RESCHEDULED"):
        fail(E.ERR_APPT_BAD_STATE, "Appointment not reschedulable")
    if (V.parse_iso(end_utc) <= V.parse_iso(start_utc)
            or V.parse_iso(start_utc) < V.parse_iso(clinic["current_clock_utc"])):
        fail(E.ERR_APPOINTMENT_IN_PAST, "Invalid appointment interval")
    if _room_conflict(clinic, start_utc, end_utc, rec["room_capacity_weight"],
                      exclude_id=rec["id"]):
        fail(E.ERR_MONITORING_SLOT_CONFLICT, "Room capacity exceeded")
    rec["start_utc"] = start_utc
    rec["end_utc"] = end_utc
    rec["status"] = "RESCHEDULED"
    db.touch(rec)
    return success(S.appointment(rec))


@app.route("/clinics/<clinic_id>/monitoring-appointments/<appt_id>/confirm",
           methods=["POST"])
def confirm_appointment(clinic_id, appt_id):
    auth_and_roles(["Nurse"])
    L.get_clinic(clinic_id)
    rec = L.get_appointment(clinic_id, appt_id)
    if rec["status"] != "RESCHEDULED":
        fail(E.ERR_APPT_BAD_STATE, "Appointment not RESCHEDULED")
    rec["status"] = "CONFIRMED"
    db.touch(rec)
    return success(S.appointment(rec))


@app.route("/clinics/<clinic_id>/monitoring-appointments/<appt_id>/complete",
           methods=["POST"])
def complete_appointment(clinic_id, appt_id):
    auth_and_roles(["Nurse"])
    clinic = L.get_clinic(clinic_id)
    rec = L.get_appointment(clinic_id, appt_id)
    if rec["status"] not in ("CONFIRMED", "RESCHEDULED"):
        fail(E.ERR_APPT_BAD_STATE, "Appointment not completable")
    if V.parse_iso(clinic["current_clock_utc"]) < V.parse_iso(rec["start_utc"]):
        fail(E.ERR_APPOINTMENT_NOT_STARTED, "Appointment not started")
    rec["status"] = "COMPLETED"
    db.touch(rec)
    return success(S.appointment(rec))


@app.route("/clinics/<clinic_id>/monitoring-appointments/<appt_id>/no-show",
           methods=["POST"])
def no_show_appointment(clinic_id, appt_id):
    auth_and_roles(["Nurse"])
    clinic = L.get_clinic(clinic_id)
    rec = L.get_appointment(clinic_id, appt_id)
    if rec["status"] not in ("CONFIRMED", "RESCHEDULED"):
        fail(E.ERR_APPT_BAD_STATE, "Appointment not in markable state")
    if V.parse_iso(clinic["current_clock_utc"]) < V.parse_iso(rec["end_utc"]):
        fail(E.ERR_APPOINTMENT_NOT_ENDED, "Appointment not ended")
    rec["status"] = "NO_SHOW"
    db.touch(rec)
    return success(S.appointment(rec))


@app.route("/clinics/<clinic_id>/monitoring-appointments/<appt_id>/cancel",
           methods=["POST"])
def cancel_appointment(clinic_id, appt_id):
    auth_and_roles(["Nurse"])
    L.get_clinic(clinic_id)
    rec = L.get_appointment(clinic_id, appt_id)
    if rec["status"] not in ("CONFIRMED", "RESCHEDULED"):
        fail(E.ERR_APPT_BAD_STATE, "Appointment not cancellable")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return success(S.appointment(rec))


# ===========================================================================
# Cryo specimens
# ===========================================================================
@app.route("/clinics/<clinic_id>/cryo-specimens", methods=["POST"])
def create_specimen(clinic_id):
    auth_and_roles(["Embryologist"])
    L.get_clinic(clinic_id)
    body = get_body()
    cycle_id = V.req_str(body, "treatment_cycle_id")
    cycle = L.get_cycle(clinic_id, cycle_id)
    tank_id = V.req_str(body, "cryo_tank_id")
    tank = L.get_tank(clinic_id, tank_id)
    specimen_type = V.req_enum(body, "specimen_type", {"EMBRYO", "OOCYTE", "SPERM"})
    rec = db.new_record({
        "treatment_cycle_id": cycle_id,
        "clinic_id": clinic_id,
        "cryo_tank_id": tank_id,
        "specimen_type": specimen_type,
        "storage_start_utc": None,
        "storage_years_accrued": 0,
        "status": "PENDING",
    })
    db.specimens[rec["id"]] = rec
    return success(S.specimen(rec), status=201)


@app.route("/clinics/<clinic_id>/cryo-specimens", methods=["GET"])
def list_specimens(clinic_id):
    auth_and_roles(["ClinicAdmin", "Embryologist", "Patient"])
    L.get_clinic(clinic_id)
    from flask import request
    recs = [r for r in db.specimens.values() if r["clinic_id"] == clinic_id]
    cid = request.args.get("treatment_cycle_id")
    if cid is not None:
        recs = [r for r in recs if r["treatment_cycle_id"] == cid]
    tid = request.args.get("cryo_tank_id")
    if tid is not None:
        recs = [r for r in recs if r["cryo_tank_id"] == tid]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    data, page = L.paginate(recs, S.specimen)
    return success(data, pagination=page)


@app.route("/clinics/<clinic_id>/cryo-specimens/<specimen_id>", methods=["GET"])
def get_specimen(clinic_id, specimen_id):
    auth_and_roles(["ClinicAdmin", "Embryologist", "Patient"])
    L.get_clinic(clinic_id)
    rec = L.get_specimen(clinic_id, specimen_id)
    return success(S.specimen(rec))


@app.route("/clinics/<clinic_id>/cryo-specimens/<specimen_id>/store", methods=["POST"])
def store_specimen(clinic_id, specimen_id):
    auth_and_roles(["Embryologist"])
    clinic = L.get_clinic(clinic_id)
    spec = L.get_specimen(clinic_id, specimen_id)
    body = get_body()
    expected = V.req_int(body, "expected_tank_version")
    tank = db.tanks.get(spec["cryo_tank_id"])
    if tank is None:
        fail(E.ERR_TANK_NOT_FOUND, "Tank not found")
    # OCC first (before state/business)
    if expected != tank["version"]:
        fail(E.ERR_STALE_TANK_VERSION, "expected_tank_version mismatch")
    # state
    if spec["status"] != "PENDING":
        fail(E.ERR_SPECIMEN_BAD_STATE, "Specimen not PENDING")
    cycle = db.cycles.get(spec["treatment_cycle_id"])
    if cycle is None or cycle["protocol_status"] not in ("FERTILIZATION", "FREEZE_ALL"):
        fail(E.ERR_CYCLE_BAD_PROTOCOL_STATE, "Cycle not in storable state")
    # consent gate CRYO_STORE
    svc.require_consent(cycle["patient_id"], "CRYO_STORE")
    # tank constraints
    if tank["status"] != "ONLINE":
        fail(E.ERR_TANK_OFFLINE, "Tank not ONLINE")
    if tank["reserved_slots"] + 1 > tank["capacity_slots"]:
        fail(E.ERR_TANK_AT_CAPACITY, "Tank at capacity")
    spec["status"] = "STORED"
    spec["storage_start_utc"] = clinic["current_clock_utc"]
    spec["storage_years_accrued"] = 0
    db.touch(spec)
    tank["reserved_slots"] += 1
    db.touch(tank)
    return success(S.specimen(spec))


@app.route("/clinics/<clinic_id>/cryo-specimens/<specimen_id>/accrue-storage-year",
           methods=["POST"])
def accrue_storage_year(clinic_id, specimen_id):
    auth_and_roles(["Embryologist", "BillingSpecialist"])
    L.get_clinic(clinic_id)
    spec = L.get_specimen(clinic_id, specimen_id)
    if spec["status"] != "STORED":
        fail(E.ERR_SPECIMEN_BAD_STATE, "Specimen not STORED")
    spec["storage_years_accrued"] += 1
    db.touch(spec)
    return success(S.specimen(spec))


def _release_specimen(clinic_id, specimen_id, target_status, allowed_from):
    L.get_clinic(clinic_id)
    spec = L.get_specimen(clinic_id, specimen_id)
    if spec["status"] not in allowed_from:
        fail(E.ERR_SPECIMEN_BAD_STATE, "Specimen not in releasable state")
    was_stored = spec["status"] == "STORED"
    spec["status"] = target_status
    db.touch(spec)
    if was_stored:
        tank = db.tanks.get(spec["cryo_tank_id"])
        if tank is not None:
            tank["reserved_slots"] -= 1
            db.touch(tank)
    return spec


@app.route("/clinics/<clinic_id>/cryo-specimens/<specimen_id>/thaw", methods=["POST"])
def thaw_specimen(clinic_id, specimen_id):
    auth_and_roles(["Embryologist"])
    spec = _release_specimen(clinic_id, specimen_id, "THAWED", ("STORED",))
    return success(S.specimen(spec))


@app.route("/clinics/<clinic_id>/cryo-specimens/<specimen_id>/discard", methods=["POST"])
def discard_specimen(clinic_id, specimen_id):
    auth_and_roles(["Embryologist"])
    spec = _release_specimen(clinic_id, specimen_id, "DISCARDED",
                             ("PENDING", "STORED"))
    return success(S.specimen(spec))


@app.route("/clinics/<clinic_id>/cryo-specimens/<specimen_id>/transfer-out",
           methods=["POST"])
def transfer_out_specimen(clinic_id, specimen_id):
    auth_and_roles(["Embryologist"])
    spec = _release_specimen(clinic_id, specimen_id, "TRANSFERRED_OUT", ("STORED",))
    return success(S.specimen(spec))


# ===========================================================================
# Billing
# ===========================================================================
def _cycle_package(cycle):
    pkg_id = cycle.get("insurance_package_id")
    if pkg_id is None:
        return None
    return db.packages.get(pkg_id)


@app.route("/clinics/<clinic_id>/cycles/<cycle_id>/billing/estimate", methods=["POST"])
def billing_estimate(clinic_id, cycle_id):
    auth_and_roles(["BillingSpecialist"])
    L.get_clinic(clinic_id)
    cycle = L.get_cycle(clinic_id, cycle_id)
    if cycle["billing_status"] != "UNBILLED":
        fail(E.ERR_BILLING_BAD_STATE, "Cycle not UNBILLED")
    if cycle["protocol_status"] not in (
            "STIM", "RETRIEVAL", "FERTILIZATION", "FRESH_TRANSFER", "FREEZE_ALL"):
        fail(E.ERR_CYCLE_BAD_PROTOCOL_STATE, "Cycle protocol not estimable")
    pkg = _cycle_package(cycle)
    stim_med_gross = sum(
        m["line_total_cents"] for m in db.medications.values()
        if m["treatment_cycle_id"] == cycle_id
        and m["status"] in ("SCHEDULED", "ADMINISTERED"))
    cryo_count = sum(
        1 for s in db.specimens.values()
        if s["treatment_cycle_id"] == cycle_id and s["status"] in ("PENDING", "STORED"))
    cycle["estimated_patient_owed_cents"] = calc.cycle_cost_estimate(
        pkg, stim_med_gross, cryo_count)
    cycle["billing_status"] = "ESTIMATED"
    db.touch(cycle)
    return success(S.cycle(cycle))


@app.route("/clinics/<clinic_id>/cycles/<cycle_id>/billing/settle", methods=["POST"])
def billing_settle(clinic_id, cycle_id):
    auth_and_roles(["BillingSpecialist"])
    L.get_clinic(clinic_id)
    cycle = L.get_cycle(clinic_id, cycle_id)
    body = get_body()
    expected = V.req_int(body, "expected_cycle_version")
    if expected != cycle["version"]:
        fail(E.ERR_STALE_CYCLE_VERSION, "expected_cycle_version mismatch")
    if cycle["billing_status"] != "ESTIMATED":
        fail(E.ERR_BILLING_BAD_STATE, "Cycle not ESTIMATED")
    if cycle["protocol_status"] not in ("COMPLETED", "CANCELLED"):
        fail(E.ERR_CYCLE_NOT_FINALIZED, "Cycle protocol not finalized")
    pkg = _cycle_package(cycle)
    stim_med_gross = sum(
        m["line_total_cents"] for m in db.medications.values()
        if m["treatment_cycle_id"] == cycle_id and m["status"] == "ADMINISTERED")
    cryo_gross = sum(
        s["storage_years_accrued"] * pkg["annual_cryo_storage_cents"]
        for s in db.specimens.values()
        if s["treatment_cycle_id"] == cycle_id and s["storage_start_utc"] is not None)
    cancellation = cycle["cancellation_fee_cents"]
    prior = svc.settle_prior_insurer_paid(cycle["insurance_package_id"], cycle_id)
    result = calc.cycle_cost_settlement(pkg, stim_med_gross, cryo_gross,
                                        cancellation, prior)
    cycle["gross_charge_cents"] = result["gross_charge_cents"]
    cycle["insurer_paid_cents"] = result["insurer_paid_cents"]
    cycle["final_patient_owed_cents"] = result["final_patient_owed_cents"]
    cycle["billing_status"] = "SETTLED"
    db.touch(cycle)
    invoice = db.new_record({
        "treatment_cycle_id": cycle_id,
        "clinic_id": clinic_id,
        "line_items": result["line_items"],
        "gross_total_cents": result["gross_total_cents"],
        "insurer_total_cents": result["insurer_total_cents"],
        "patient_total_cents": result["patient_total_cents"],
        "status": "ISSUED",
    })
    db.invoices[invoice["id"]] = invoice
    return success(S.cycle(cycle))


@app.route("/clinics/<clinic_id>/cycles/<cycle_id>/billing/write-off", methods=["POST"])
def billing_writeoff(clinic_id, cycle_id):
    auth_and_roles(["BillingSpecialist"])
    L.get_clinic(clinic_id)
    cycle = L.get_cycle(clinic_id, cycle_id)
    if cycle["billing_status"] != "ESTIMATED":
        fail(E.ERR_BILLING_BAD_STATE, "Cycle not ESTIMATED")
    if cycle["protocol_status"] != "CANCELLED":
        fail(E.ERR_CYCLE_NOT_FINALIZED, "Cycle not CANCELLED")
    fee = cycle["cancellation_fee_cents"]
    cycle["final_patient_owed_cents"] = fee
    cycle["insurer_paid_cents"] = 0
    cycle["gross_charge_cents"] = fee
    cycle["billing_status"] = "WRITTEN_OFF"
    db.touch(cycle)
    line_items = []
    if fee > 0:
        line_items.append({
            "category": "CANCELLATION",
            "gross_cents": fee,
            "covered": False,
            "insurer_cents": 0,
            "patient_cents": fee,
        })
    invoice = db.new_record({
        "treatment_cycle_id": cycle_id,
        "clinic_id": clinic_id,
        "line_items": line_items,
        "gross_total_cents": fee,
        "insurer_total_cents": 0,
        "patient_total_cents": fee,
        "status": "VOID",
    })
    db.invoices[invoice["id"]] = invoice
    return success(S.cycle(cycle))


@app.route("/clinics/<clinic_id>/cycle-invoices", methods=["GET"])
def list_invoices(clinic_id):
    auth_and_roles(["ClinicAdmin", "BillingSpecialist", "Patient"])
    L.get_clinic(clinic_id)
    from flask import request
    recs = [r for r in db.invoices.values() if r["clinic_id"] == clinic_id]
    cid = request.args.get("treatment_cycle_id")
    if cid is not None:
        recs = [r for r in recs if r["treatment_cycle_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    data, page = L.paginate(recs, S.invoice)
    return success(data, pagination=page)


@app.route("/clinics/<clinic_id>/cycle-invoices/<invoice_id>", methods=["GET"])
def get_invoice(clinic_id, invoice_id):
    auth_and_roles(["ClinicAdmin", "BillingSpecialist", "Patient"])
    L.get_clinic(clinic_id)
    rec = L.get_invoice(clinic_id, invoice_id)
    return success(S.invoice(rec))


# ===========================================================================
# Outcome reporting
# ===========================================================================
@app.route("/clinics/<clinic_id>/outcome-reports", methods=["POST"])
def create_outcome(clinic_id):
    auth_and_roles(["Nurse"])
    L.get_clinic(clinic_id)
    body = get_body()
    cycle_id = V.req_str(body, "treatment_cycle_id")
    cycle = L.get_cycle(clinic_id, cycle_id)
    result = V.req_enum(body, "pregnancy_test_result",
                        {"POSITIVE", "NEGATIVE", "INCONCLUSIVE"})
    clinical = V.opt_bool(body, "clinical_pregnancy", False)
    live = V.opt_bool(body, "live_birth", False)
    rate = calc.embryo_utilization_rate(cycle["embryos_fertilized"],
                                        cycle["oocytes_retrieved"])
    rec = db.new_record({
        "treatment_cycle_id": cycle_id,
        "clinic_id": clinic_id,
        "pregnancy_test_result": result,
        "clinical_pregnancy": clinical,
        "live_birth": live,
        "utilization_rate": rate,
    })
    db.outcomes[rec["id"]] = rec
    return success(S.outcome(rec), status=201)


@app.route("/clinics/<clinic_id>/outcome-reports", methods=["GET"])
def list_outcomes(clinic_id):
    auth_and_roles(["ClinicAdmin", "Nurse", "BillingSpecialist", "Patient"])
    L.get_clinic(clinic_id)
    from flask import request
    recs = [r for r in db.outcomes.values() if r["clinic_id"] == clinic_id]
    cid = request.args.get("treatment_cycle_id")
    if cid is not None:
        recs = [r for r in recs if r["treatment_cycle_id"] == cid]
    data, page = L.paginate(recs, S.outcome)
    return success(data, pagination=page)


@app.route("/clinics/<clinic_id>/outcome-reports/<outcome_id>", methods=["GET"])
def get_outcome(clinic_id, outcome_id):
    auth_and_roles(["ClinicAdmin", "Nurse", "BillingSpecialist", "Patient"])
    L.get_clinic(clinic_id)
    rec = L.get_outcome(clinic_id, outcome_id)
    return success(S.outcome(rec))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
