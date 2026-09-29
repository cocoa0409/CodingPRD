"""Logical clock, brands, trademark registrations, marketplace enrollments and
authorized representatives."""

from flask import Blueprint

import constants as C
import db
import entities
import ledger
import reps
import validation as V
from errors import fail
from middleware import (ALL_ROLES, BRAND_ADMINISTRATOR, CUSTOMS_COORDINATOR,
                        ENFORCEMENT_ANALYST, LEGAL_COUNSEL,
                        MARKETPLACE_LIAISON, authenticate)
from response import created, ok, public
from timeutil import iso
from versioning import touch

bp = Blueprint("core", __name__)


# ------------------------------------------------------------ logical clock --

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate(BRAND_ADMINISTRATOR, MARKETPLACE_LIAISON, CUSTOMS_COORDINATOR)
    payload = V.body()
    moment = V.datetime_field(payload, "to_iso8601")
    db.set_now(moment)
    return ok({"current_utc": iso(db.now())})


# ------------------------------------------------------------------ brands ---

@bp.route("/brand-protection/brands", methods=["POST"])
def create_brand():
    authenticate(BRAND_ADMINISTRATOR)
    payload = V.body()
    name = V.string_field(payload, "name", 1, 120)
    owner = V.string_field(payload, "owner_legal_entity", 1, 160)
    jurisdiction = V.jurisdiction_field(payload, "home_jurisdiction")
    msrp = V.int_field(payload, "authorized_msrp_cents", minimum=1)
    budget = V.int_field(payload, "enforcement_budget_cents", minimum=0,
                         required=False, default=500000)
    row = entities.new_brand(name, owner, jurisdiction, msrp, budget)
    return created(public(row))


@bp.route("/brand-protection/brands/<brand_id>", methods=["GET"])
def read_brand(brand_id):
    authenticate(ALL_ROLES)
    return ok(public(V.must_exist("brands", brand_id)))


@bp.route("/brand-protection/brands", methods=["GET"])
def list_brands():
    authenticate(ALL_ROLES)
    return V.collection("brands", {"status": C.BRAND_STATUSES,
                                   "home_jurisdiction": None})


@bp.route("/brand-protection/brands/<brand_id>/enforcement-metrics",
          methods=["GET"])
def brand_metrics(brand_id):
    authenticate(BRAND_ADMINISTRATOR, ENFORCEMENT_ANALYST, LEGAL_COUNSEL)
    brand = V.must_exist("brands", brand_id)
    return ok(ledger.brand_enforcement_metrics(brand))


# ----------------------------------------------------- trademark registrations

@bp.route("/brand-protection/trademark-registrations", methods=["POST"])
def create_registration():
    authenticate(BRAND_ADMINISTRATOR)
    payload = V.body()
    brand_id = V.id_field(payload, "brand_id")
    number = V.string_field(payload, "registration_number", 1, 40)
    jurisdiction = V.jurisdiction_field(payload, "jurisdiction")
    nice_class = V.int_field(payload, "nice_class", minimum=1, maximum=45)
    registration_date = V.date_field(payload, "registration_date")
    expiry_date = V.date_field(payload, "expiry_date")
    principal_register = V.bool_field(payload, "principal_register")
    status = V.enum_field(payload, "status", C.REGISTRATION_INPUT_STATUSES)
    if not expiry_date > registration_date:
        fail("ERR_INVALID_REQUEST",
             "expiry_date must fall strictly after registration_date.")
    brand = V.must_exist("brands", brand_id)
    for existing in db.values("registrations"):
        if (existing["jurisdiction"] == jurisdiction
                and existing["registration_number"] == number):
            fail("ERR_INVALID_REQUEST",
                 "registration_number is already recorded in this jurisdiction.")
    row = entities.new_registration(brand["id"], number, jurisdiction,
                                    nice_class, registration_date, expiry_date,
                                    principal_register, status)
    return created(public(row))


@bp.route("/brand-protection/trademark-registrations/<registration_id>",
          methods=["GET"])
def read_registration(registration_id):
    authenticate(ALL_ROLES)
    return ok(public(V.must_exist("registrations", registration_id)))


@bp.route("/brand-protection/trademark-registrations", methods=["GET"])
def list_registrations():
    authenticate(ALL_ROLES)
    return V.collection("registrations", {
        "brand_id": None,
        "status": C.REGISTRATION_STATUSES,
        "jurisdiction": None,
        "nice_class": V.INT_FILTER,
    })


# ------------------------------------------------- marketplace enrollments ---

@bp.route("/brand-protection/enrollments", methods=["POST"])
def create_enrollment():
    authenticate(BRAND_ADMINISTRATOR)
    payload = V.body()
    brand_id = V.id_field(payload, "brand_id")
    registration_id = V.id_field(payload, "asserted_registration_id")
    marketplace_code = V.enum_field(payload, "marketplace_code",
                                    C.MARKETPLACE_CODES)
    requested_nice_class = V.int_field(payload, "requested_nice_class",
                                       minimum=1, maximum=45)
    expected = V.int_field(payload, "expected_brand_version", minimum=None)
    brand = V.must_exist("brands", brand_id)
    registration = V.must_exist("registrations", registration_id)
    if expected != brand["version"]:
        fail("ERR_STALE_BRAND_VERSION")
    siblings = [e for e in db.values("enrollments")
                if e["brand_id"] == brand["id"]
                and e["marketplace_code"] == marketplace_code]
    if any(e["enrollment_status"] == "ACTIVE" for e in siblings):
        fail("ERR_DUPLICATE_ENROLLMENT")
    row = entities.new_enrollment(brand["id"], registration["id"],
                                  marketplace_code, requested_nice_class)
    for old in siblings:
        if old["enrollment_status"] in ("SUBMITTED", "SUSPENDED"):
            ledger.supersede_enrollment(old, row["id"])
    ledger.recompute_brand_posture(brand["id"])
    return created(public(row))


@bp.route("/brand-protection/enrollments/<enrollment_id>", methods=["GET"])
def read_enrollment(enrollment_id):
    authenticate(ALL_ROLES)
    return ok(public(V.must_exist("enrollments", enrollment_id)))


@bp.route("/brand-protection/enrollments", methods=["GET"])
def list_enrollments():
    authenticate(ALL_ROLES)
    return V.collection("enrollments", {
        "brand_id": None,
        "asserted_registration_id": None,
        "superseded_by_enrollment_id": None,
        "marketplace_code": C.MARKETPLACE_CODES,
        "enrollment_status": C.ENROLLMENT_STATUSES,
    })


@bp.route("/brand-protection/enrollments/<enrollment_id>/activate",
          methods=["POST"])
def activate_enrollment(enrollment_id):
    authenticate(MARKETPLACE_LIAISON)
    V.body()
    enrollment = V.must_exist("enrollments", enrollment_id)
    if enrollment["enrollment_status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    registration = db.get("registrations",
                          enrollment["asserted_registration_id"])
    if registration is None or registration["status"] != "REGISTERED":
        fail("ERR_REGISTRATION_NOT_ELIGIBLE")
    if registration["expiry_date"] < db.now().date():
        fail("ERR_REGISTRATION_NOT_ELIGIBLE")
    if registration["nice_class"] != enrollment["requested_nice_class"]:
        fail("ERR_REGISTRATION_NOT_ELIGIBLE")
    enrollment["enrollment_status"] = "ACTIVE"
    enrollment["activated_at"] = db.now()
    touch(enrollment)
    ledger.recompute_brand_posture(enrollment["brand_id"])
    return ok(public(enrollment))


@bp.route("/brand-protection/enrollments/<enrollment_id>/suspend",
          methods=["POST"])
def suspend_enrollment(enrollment_id):
    authenticate(MARKETPLACE_LIAISON)
    payload = V.body()
    reason_code = V.enum_field(payload, "reason_code",
                               C.SUSPENSION_REASON_CODES)
    enrollment = V.must_exist("enrollments", enrollment_id)
    if enrollment["enrollment_status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    ledger.suspend_enrollment(enrollment, reason_code)
    return ok(public(enrollment))


# ------------------------------------------- authorized representatives ------

@bp.route("/brand-protection/representatives", methods=["POST"])
def create_representative():
    authenticate(BRAND_ADMINISTRATOR)
    payload = V.body()
    enrollment_id = V.id_field(payload, "enrollment_id")
    authority_scope = V.enum_field(payload, "authority_scope",
                                   C.AUTHORITY_SCOPES)
    effective_from = V.datetime_field(payload, "effective_from")
    power_of_attorney_ref = V.string_field(payload, "power_of_attorney_ref",
                                           1, 80)
    effective_to = V.datetime_field(payload, "effective_to", required=False)
    if effective_to is not None and not effective_from < effective_to:
        fail("ERR_INVALID_REQUEST",
             "effective_from must fall strictly before effective_to.")
    enrollment = V.must_exist("enrollments", enrollment_id)
    if enrollment["enrollment_status"] != "ACTIVE":
        fail("ERR_ENROLLMENT_NOT_ACTIVE")
    reps.check_designation_overlap(enrollment["id"], authority_scope,
                                   effective_from, effective_to)
    row = entities.new_representative(enrollment["id"], authority_scope,
                                      effective_from, effective_to,
                                      power_of_attorney_ref)
    return created(public(row))


@bp.route("/brand-protection/representatives/<representative_id>",
          methods=["GET"])
def read_representative(representative_id):
    authenticate(ALL_ROLES)
    return ok(public(V.must_exist("representatives", representative_id)))


@bp.route("/brand-protection/representatives", methods=["GET"])
def list_representatives():
    authenticate(ALL_ROLES)
    return V.collection("representatives", {
        "enrollment_id": None,
        "designation_status": C.DESIGNATION_STATUSES,
        "authority_scope": C.AUTHORITY_SCOPES,
    })


@bp.route("/brand-protection/representatives/<representative_id>/revoke",
          methods=["POST"])
def revoke_representative(representative_id):
    authenticate(BRAND_ADMINISTRATOR)
    payload = V.body()
    V.string_field(payload, "reason_code", 1, 80, required=False)
    rep = V.must_exist("representatives", representative_id)
    if rep["designation_status"] != "DESIGNATED":
        fail("ERR_INVALID_STATE")
    rep["designation_status"] = "REVOKED"
    rep["revoked_at"] = db.now()
    touch(rep)
    return ok(public(rep))
