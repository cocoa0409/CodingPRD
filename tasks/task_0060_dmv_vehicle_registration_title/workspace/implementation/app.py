import os
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from flask import Flask, request, g

from errors import ApiError, err
import errors as E
from store import (
    db, clock, new_id, iso, parse_iso,
    EMISSIONS_VALID_DAYS, REGISTRATION_TERM_DAYS,
)
from envelope import success, success_list, error_response

app = Flask(__name__)

ROLES = {"ClerkAgent", "InspectionStation", "Owner", "DmvAdmin"}


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise err(E.ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    g.user_id = uid
    g.role = role
    return uid, role


def require_role(*allowed):
    if g.role not in allowed:
        raise err(E.ERR_FORBIDDEN, "Role %s not permitted for this operation" % g.role)


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err(E.ERR_VALIDATION, "Request body must be a JSON object")
    return data


def require_fields(data, *names):
    for n in names:
        if n not in data or data[n] is None:
            raise err(E.ERR_VALIDATION, "Missing required field: %s" % n)


def opt(data, name, default=None):
    v = data.get(name, default)
    if v is None:
        return default
    return v


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err(E.ERR_VALIDATION, "Invalid value for %s" % field)
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(E.ERR_VALIDATION, "%s must be an integer" % field)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise err(E.ERR_VALIDATION, "%s must be a boolean" % field)
    return value


# ---------------------------------------------------------------------------
# Common fields / timestamps
# ---------------------------------------------------------------------------
def stamp_create(rec, versioned=True):
    now = clock.now()
    rec["id"] = new_id()
    rec["created_at"] = now
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(rows):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(E.ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(E.ERR_VALIDATION, "limit out of range")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(E.ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise err(E.ERR_VALIDATION, "offset out of range")
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def base_view(rec, versioned=True):
    out = {"id": rec["id"], "created_at": iso(rec["created_at"])}
    if versioned:
        out["updated_at"] = iso(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def view_owner(r):
    v = base_view(r)
    v.update({
        "full_name": r["full_name"],
        "residence_county_code": r["residence_county_code"],
        "credential_type": r["credential_type"],
        "identity_documents_verified": r["identity_documents_verified"],
        "real_id_status": r["real_id_status"],
    })
    return v


def view_vehicle(r):
    v = base_view(r)
    v.update({
        "owner_id": r["owner_id"],
        "vin": r["vin"],
        "model_year": r["model_year"],
        "purchase_price_cents": r["purchase_price_cents"],
        "msrp_cents": r["msrp_cents"],
        "vehicle_class": r["vehicle_class"],
        "vin_status": r["vin_status"],
        "title_status": r["title_status"],
        "is_salvage_branded": r["is_salvage_branded"],
        "active_lien_count": r["active_lien_count"],
    })
    return v


def view_vin_verification(r):
    v = base_view(r, versioned=False)
    v.update({
        "vehicle_id": r["vehicle_id"],
        "submitted_vin": r["submitted_vin"],
        "outcome": r["outcome"],
    })
    return v


def view_title_application(r):
    v = base_view(r)
    v.update({
        "vehicle_id": r["vehicle_id"],
        "applicant_owner_id": r["applicant_owner_id"],
        "application_type": r["application_type"],
        "status": r["status"],
        "requires_salvage_path": r["requires_salvage_path"],
        "issued_title_brand": r["issued_title_brand"],
    })
    return v


def view_salvage_inspection(r):
    v = base_view(r)
    v.update({
        "title_application_id": r["title_application_id"],
        "station_id": r["station_id"],
        "result": r["result"],
        "status": r["status"],
    })
    return v


def view_lien(r):
    v = base_view(r)
    v.update({
        "vehicle_id": r["vehicle_id"],
        "lien_holder_name": r["lien_holder_name"],
        "principal_cents": r["principal_cents"],
        "status": r["status"],
    })
    return v


def view_emissions_inspection(r):
    v = base_view(r)
    v.update({
        "vehicle_id": r["vehicle_id"],
        "station_id": r["station_id"],
        "result": r["result"],
        "inspected_at": iso(r["inspected_at"]),
        "valid_until": iso(r["valid_until"]),
        "status": r["status"],
    })
    return v


def view_fee_assessment(r):
    v = base_view(r)
    v.update({
        "registration_id": r["registration_id"],
        "use_tax_cents": r["use_tax_cents"],
        "registration_fee_cents": r["registration_fee_cents"],
        "real_id_surcharge_cents": r["real_id_surcharge_cents"],
        "total_cents": r["total_cents"],
        "status": r["status"],
    })
    return v


def view_registration(r):
    v = base_view(r)
    v.update({
        "vehicle_id": r["vehicle_id"],
        "owner_id": r["owner_id"],
        "registration_type": r["registration_type"],
        "bundle_real_id": r["bundle_real_id"],
        "status": r["status"],
        "term_start": iso(r["term_start"]),
        "term_end": iso(r["term_end"]),
        "plate_assigned": r["plate_assigned"],
    })
    return v


def view_license_plate(r):
    v = base_view(r)
    v.update({
        "registration_id": r["registration_id"],
        "plate_number": r["plate_number"],
        "plate_type": r["plate_type"],
        "issued_at": iso(r["issued_at"]),
        "surrendered_at": iso(r["surrendered_at"]),
        "status": r["status"],
    })
    return v


def view_real_id_application(r):
    v = base_view(r)
    v.update({
        "owner_id": r["owner_id"],
        "status": r["status"],
        "documents_complete": r["documents_complete"],
    })
    return v


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise err(E.ERR_NOT_FOUND, "Resource not found")
    return rec


# ===========================================================================
# OWNERS
# ===========================================================================
@app.post("/owners")
def create_owner():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    data = body()
    require_fields(data, "full_name", "residence_county_code")
    credential_type = opt(data, "credential_type", "STANDARD")
    require_enum(credential_type, {"STANDARD", "REAL_ID"}, "credential_type")
    idv = opt(data, "identity_documents_verified", False)
    idv = as_bool(idv, "identity_documents_verified")
    rec = {
        "full_name": data["full_name"],
        "residence_county_code": data["residence_county_code"],
        "credential_type": credential_type,
        "identity_documents_verified": idv,
        "real_id_status": "NONE",
    }
    stamp_create(rec)
    db.owners[rec["id"]] = rec
    return success(view_owner(rec), 201)


@app.get("/owners/<rid>")
def get_owner(rid):
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rec = get_or_404(db.owners, rid)
    return success(view_owner(rec), 200)


# ===========================================================================
# VEHICLES
# ===========================================================================
@app.post("/vehicles")
def create_vehicle():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    data = body()
    require_fields(data, "owner_id", "vin", "model_year",
                   "purchase_price_cents", "msrp_cents", "vehicle_class")
    get_or_404(db.owners, data["owner_id"])
    vin = data["vin"]
    model_year = as_int(data["model_year"], "model_year")
    purchase_price = as_int(data["purchase_price_cents"], "purchase_price_cents")
    msrp = as_int(data["msrp_cents"], "msrp_cents")
    vehicle_class = require_enum(data["vehicle_class"],
                                 {"PASSENGER", "TRUCK", "MOTORCYCLE"}, "vehicle_class")
    salvage = opt(data, "is_salvage_branded", False)
    salvage = as_bool(salvage, "is_salvage_branded")

    # VIN validation: exactly 17 chars and unique (priority 14, after structural)
    if not isinstance(vin, str) or len(vin) != 17:
        raise err(E.ERR_INVALID_VIN, "VIN must be exactly 17 characters")
    for v in db.vehicles.values():
        if v["vin"] == vin:
            raise err(E.ERR_INVALID_VIN, "VIN already exists")

    rec = {
        "owner_id": data["owner_id"],
        "vin": vin,
        "model_year": model_year,
        "purchase_price_cents": purchase_price,
        "msrp_cents": msrp,
        "vehicle_class": vehicle_class,
        "vin_status": "UNVERIFIED",
        "title_status": "NONE",
        "is_salvage_branded": salvage,
        "active_lien_count": 0,
    }
    stamp_create(rec)
    db.vehicles[rec["id"]] = rec
    return success(view_vehicle(rec), 201)


@app.get("/vehicles/<rid>")
def get_vehicle(rid):
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rec = get_or_404(db.vehicles, rid)
    return success(view_vehicle(rec), 200)


@app.get("/vehicles")
def list_vehicles():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rows = list(db.vehicles.values())
    owner_id = request.args.get("owner_id")
    vin = request.args.get("vin")
    if owner_id is not None:
        rows = [r for r in rows if r["owner_id"] == owner_id]
    if vin is not None:
        rows = [r for r in rows if r["vin"] == vin]
    page, limit, offset, total = paginate(rows)
    return success_list([view_vehicle(r) for r in page], limit, offset, total)


# ===========================================================================
# VIN VERIFICATIONS
# ===========================================================================
@app.post("/vin-verifications")
def create_vin_verification():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin")
    data = body()
    require_fields(data, "vehicle_id", "submitted_vin", "outcome")
    outcome = require_enum(data["outcome"],
                           {"MATCH", "MISMATCH", "NHTSA_FLAG"}, "outcome")
    vehicle = get_or_404(db.vehicles, data["vehicle_id"])
    rec = {
        "vehicle_id": data["vehicle_id"],
        "submitted_vin": data["submitted_vin"],
        "outcome": outcome,
    }
    stamp_create(rec, versioned=False)
    db.vin_verifications[rec["id"]] = rec
    # side effect: update vehicle vin_status + bump version
    if outcome == "MATCH":
        vehicle["vin_status"] = "VERIFIED"
    else:
        vehicle["vin_status"] = "FLAGGED"
    touch(vehicle)
    return success(view_vin_verification(rec), 201)


@app.get("/vin-verifications/<rid>")
def get_vin_verification(rid):
    require_auth()
    require_role("ClerkAgent", "DmvAdmin")
    rec = get_or_404(db.vin_verifications, rid)
    return success(view_vin_verification(rec), 200)


@app.get("/vin-verifications")
def list_vin_verifications():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin")
    rows = list(db.vin_verifications.values())
    vehicle_id = request.args.get("vehicle_id")
    if vehicle_id is not None:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    page, limit, offset, total = paginate(rows)
    return success_list([view_vin_verification(r) for r in page], limit, offset, total)


# ===========================================================================
# TITLE APPLICATIONS
# ===========================================================================
@app.post("/title-applications")
def create_title_application():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin")
    data = body()
    require_fields(data, "vehicle_id", "applicant_owner_id", "application_type")
    application_type = require_enum(data["application_type"],
                                    {"INITIAL", "TRANSFER"}, "application_type")
    get_or_404(db.vehicles, data["vehicle_id"])
    get_or_404(db.owners, data["applicant_owner_id"])
    rec = {
        "vehicle_id": data["vehicle_id"],
        "applicant_owner_id": data["applicant_owner_id"],
        "application_type": application_type,
        "status": "DRAFT",
        "requires_salvage_path": False,
        "issued_title_brand": None,
    }
    stamp_create(rec)
    db.title_applications[rec["id"]] = rec
    return success(view_title_application(rec), 201)


@app.get("/title-applications/<rid>")
def get_title_application(rid):
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rec = get_or_404(db.title_applications, rid)
    return success(view_title_application(rec), 200)


@app.get("/title-applications")
def list_title_applications():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rows = list(db.title_applications.values())
    vehicle_id = request.args.get("vehicle_id")
    applicant_owner_id = request.args.get("applicant_owner_id")
    if vehicle_id is not None:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    if applicant_owner_id is not None:
        rows = [r for r in rows if r["applicant_owner_id"] == applicant_owner_id]
    page, limit, offset, total = paginate(rows)
    return success_list([view_title_application(r) for r in page], limit, offset, total)


@app.post("/title-applications/<rid>/submit")
def submit_title_application(rid):
    require_auth()
    require_role("ClerkAgent")
    app_rec = get_or_404(db.title_applications, rid)
    if app_rec["status"] != "DRAFT":
        raise err(E.ERR_INVALID_STATE, "Application is not in DRAFT")
    vehicle = db.vehicles[app_rec["vehicle_id"]]
    # business gate 1: VIN verified
    if vehicle["vin_status"] != "VERIFIED":
        raise err(E.ERR_VIN_NOT_VERIFIED, "Vehicle VIN is not VERIFIED")
    # business gate 2: TRANSFER requires existing title
    if app_rec["application_type"] == "TRANSFER":
        if vehicle["title_status"] not in {"CLEAR", "REBUILT"}:
            raise err(E.ERR_TRANSFER_REQUIRES_TITLE,
                      "TRANSFER requires an existing CLEAR/REBUILT title")
    # side effects + branch fork
    app_rec["requires_salvage_path"] = vehicle["is_salvage_branded"]
    if vehicle["is_salvage_branded"]:
        app_rec["status"] = "SALVAGE_HOLD"
    else:
        app_rec["status"] = "SUBMITTED"
    touch(app_rec)
    return success(view_title_application(app_rec), 200)


@app.post("/title-applications/<rid>/approve")
def approve_title_application(rid):
    require_auth()
    require_role("ClerkAgent")
    app_rec = get_or_404(db.title_applications, rid)
    status = app_rec["status"]
    if status == "SUBMITTED":
        pass
    elif status == "SALVAGE_HOLD":
        # requires a PASS SalvageInspection for this application
        has_pass = any(
            s["title_application_id"] == rid and s["result"] == "PASS"
            for s in db.salvage_inspections.values()
        )
        if not has_pass:
            raise err(E.ERR_SALVAGE_INSPECTION_REQUIRED,
                      "A PASS salvage inspection is required")
    else:
        raise err(E.ERR_INVALID_STATE, "Application cannot be approved")
    app_rec["status"] = "APPROVED"
    touch(app_rec)
    return success(view_title_application(app_rec), 200)


@app.post("/title-applications/<rid>/reject")
def reject_title_application(rid):
    require_auth()
    require_role("ClerkAgent")
    app_rec = get_or_404(db.title_applications, rid)
    status = app_rec["status"]
    if status == "SUBMITTED":
        pass
    elif status == "SALVAGE_HOLD":
        has_fail = any(
            s["title_application_id"] == rid and s["result"] == "FAIL"
            for s in db.salvage_inspections.values()
        )
        if not has_fail:
            raise err(E.ERR_SALVAGE_INSPECTION_REQUIRED,
                      "A FAIL salvage inspection is required")
    else:
        raise err(E.ERR_INVALID_STATE, "Application cannot be rejected")
    app_rec["status"] = "REJECTED"
    touch(app_rec)
    return success(view_title_application(app_rec), 200)


@app.post("/title-applications/<rid>/issue")
def issue_title_application(rid):
    require_auth()
    require_role("ClerkAgent")
    app_rec = get_or_404(db.title_applications, rid)
    if app_rec["status"] != "APPROVED":
        raise err(E.ERR_INVALID_STATE, "Application is not APPROVED")
    vehicle = db.vehicles[app_rec["vehicle_id"]]
    requires_salvage = app_rec["requires_salvage_path"]
    brand = "REBUILT" if requires_salvage else "CLEAR"
    # HOP 1: stamp brand on application
    app_rec["issued_title_brand"] = brand
    app_rec["status"] = "ISSUED"
    touch(app_rec)
    # HOP 2: vehicle title_status + owner reassignment + version bump
    vehicle["title_status"] = brand
    vehicle["owner_id"] = app_rec["applicant_owner_id"]
    touch(vehicle)
    # HOP 3/4: only on TRANSFER, release PERFECTED liens, decrement counter
    if app_rec["application_type"] == "TRANSFER":
        for lien in db.liens.values():
            if lien["vehicle_id"] == vehicle["id"] and lien["status"] == "PERFECTED":
                lien["status"] = "RELEASED"
                touch(lien)
                vehicle["active_lien_count"] -= 1
                touch(vehicle)
    return success(view_title_application(app_rec), 200)


# ===========================================================================
# SALVAGE INSPECTIONS
# ===========================================================================
@app.post("/salvage-inspections")
def create_salvage_inspection():
    require_auth()
    require_role("InspectionStation", "DmvAdmin")
    data = body()
    require_fields(data, "title_application_id", "result")
    result = require_enum(data["result"], {"PASS", "FAIL"}, "result")
    get_or_404(db.title_applications, data["title_application_id"])
    rec = {
        "title_application_id": data["title_application_id"],
        "station_id": g.user_id,
        "result": result,
        "status": "RECORDED",
    }
    stamp_create(rec)
    db.salvage_inspections[rec["id"]] = rec
    return success(view_salvage_inspection(rec), 201)


@app.get("/salvage-inspections/<rid>")
def get_salvage_inspection(rid):
    require_auth()
    require_role("ClerkAgent", "InspectionStation", "DmvAdmin")
    rec = get_or_404(db.salvage_inspections, rid)
    return success(view_salvage_inspection(rec), 200)


@app.get("/salvage-inspections")
def list_salvage_inspections():
    require_auth()
    require_role("ClerkAgent", "InspectionStation", "DmvAdmin")
    rows = list(db.salvage_inspections.values())
    tid = request.args.get("title_application_id")
    if tid is not None:
        rows = [r for r in rows if r["title_application_id"] == tid]
    page, limit, offset, total = paginate(rows)
    return success_list([view_salvage_inspection(r) for r in page], limit, offset, total)


# ===========================================================================
# EMISSIONS INSPECTIONS
# ===========================================================================
@app.post("/emissions-inspections")
def create_emissions_inspection():
    require_auth()
    require_role("InspectionStation", "DmvAdmin")
    data = body()
    require_fields(data, "vehicle_id", "result")
    result = require_enum(data["result"], {"PASS", "FAIL"}, "result")
    get_or_404(db.vehicles, data["vehicle_id"])
    now = clock.now()
    rec = {
        "vehicle_id": data["vehicle_id"],
        "station_id": g.user_id,
        "result": result,
        "inspected_at": now,
        "valid_until": now + timedelta(days=EMISSIONS_VALID_DAYS),
        "status": "RECORDED",
    }
    stamp_create(rec)
    db.emissions_inspections[rec["id"]] = rec
    return success(view_emissions_inspection(rec), 201)


@app.get("/emissions-inspections/<rid>")
def get_emissions_inspection(rid):
    require_auth()
    require_role("ClerkAgent", "InspectionStation", "DmvAdmin")
    rec = get_or_404(db.emissions_inspections, rid)
    return success(view_emissions_inspection(rec), 200)


@app.get("/emissions-inspections")
def list_emissions_inspections():
    require_auth()
    require_role("ClerkAgent", "InspectionStation", "DmvAdmin")
    rows = list(db.emissions_inspections.values())
    vehicle_id = request.args.get("vehicle_id")
    if vehicle_id is not None:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    page, limit, offset, total = paginate(rows)
    return success_list([view_emissions_inspection(r) for r in page], limit, offset, total)


# ===========================================================================
# LIENS
# ===========================================================================
@app.post("/liens")
def create_lien():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin")
    data = body()
    require_fields(data, "vehicle_id", "lien_holder_name", "principal_cents")
    get_or_404(db.vehicles, data["vehicle_id"])
    principal = as_int(data["principal_cents"], "principal_cents")
    rec = {
        "vehicle_id": data["vehicle_id"],
        "lien_holder_name": data["lien_holder_name"],
        "principal_cents": principal,
        "status": "FILED",
    }
    stamp_create(rec)
    db.liens[rec["id"]] = rec
    return success(view_lien(rec), 201)


@app.get("/liens/<rid>")
def get_lien(rid):
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rec = get_or_404(db.liens, rid)
    return success(view_lien(rec), 200)


@app.get("/liens")
def list_liens():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rows = list(db.liens.values())
    vehicle_id = request.args.get("vehicle_id")
    if vehicle_id is not None:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    page, limit, offset, total = paginate(rows)
    return success_list([view_lien(r) for r in page], limit, offset, total)


@app.post("/liens/<rid>/perfect")
def perfect_lien(rid):
    require_auth()
    require_role("ClerkAgent")
    lien = get_or_404(db.liens, rid)
    if lien["status"] != "FILED":
        raise err(E.ERR_INVALID_STATE, "Lien is not FILED")
    vehicle = db.vehicles[lien["vehicle_id"]]
    if vehicle["title_status"] == "NONE":
        raise err(E.ERR_LIEN_REQUIRES_TITLE, "Vehicle has no title")
    lien["status"] = "PERFECTED"
    touch(lien)
    vehicle["active_lien_count"] += 1
    touch(vehicle)
    return success(view_lien(lien), 200)


@app.post("/liens/<rid>/release")
def release_lien(rid):
    require_auth()
    require_role("ClerkAgent", "DmvAdmin")
    lien = get_or_404(db.liens, rid)
    if lien["status"] not in {"FILED", "PERFECTED"}:
        raise err(E.ERR_INVALID_STATE, "Lien cannot be released")
    was_perfected = lien["status"] == "PERFECTED"
    lien["status"] = "RELEASED"
    touch(lien)
    if was_perfected:
        vehicle = db.vehicles[lien["vehicle_id"]]
        vehicle["active_lien_count"] -= 1
        touch(vehicle)
    return success(view_lien(lien), 200)


# ===========================================================================
# REGISTRATIONS
# ===========================================================================
@app.post("/registrations")
def create_registration():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin")
    data = body()
    require_fields(data, "vehicle_id", "owner_id", "registration_type")
    registration_type = require_enum(data["registration_type"],
                                     {"INITIAL", "TRANSFER"}, "registration_type")
    get_or_404(db.vehicles, data["vehicle_id"])
    get_or_404(db.owners, data["owner_id"])
    bundle = opt(data, "bundle_real_id", False)
    bundle = as_bool(bundle, "bundle_real_id")
    rec = {
        "vehicle_id": data["vehicle_id"],
        "owner_id": data["owner_id"],
        "registration_type": registration_type,
        "bundle_real_id": bundle,
        "status": "PENDING_FEES",
        "term_start": None,
        "term_end": None,
        "plate_assigned": False,
    }
    stamp_create(rec)
    db.registrations[rec["id"]] = rec
    return success(view_registration(rec), 201)


@app.get("/registrations/<rid>")
def get_registration(rid):
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rec = get_or_404(db.registrations, rid)
    return success(view_registration(rec), 200)


@app.get("/registrations")
def list_registrations():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rows = list(db.registrations.values())
    vehicle_id = request.args.get("vehicle_id")
    owner_id = request.args.get("owner_id")
    if vehicle_id is not None:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    if owner_id is not None:
        rows = [r for r in rows if r["owner_id"] == owner_id]
    page, limit, offset, total = paginate(rows)
    return success_list([view_registration(r) for r in page], limit, offset, total)


def _fee_assessment_for_registration(reg_id):
    # The FeeAssessment for this registration (latest by created_at).
    matches = [f for f in db.fee_assessments.values() if f["registration_id"] == reg_id]
    if not matches:
        return None
    matches.sort(key=lambda f: (f["created_at"], f["id"]))
    return matches[-1]


@app.post("/registrations/<rid>/activate")
def activate_registration(rid):
    require_auth()
    require_role("ClerkAgent")
    reg = get_or_404(db.registrations, rid)
    if reg["status"] != "PENDING_FEES":
        raise err(E.ERR_INVALID_STATE, "Registration is not PENDING_FEES")
    vehicle = db.vehicles[reg["vehicle_id"]]

    # Gate 1 (priority 13): FeeAssessment PAID
    fee = _fee_assessment_for_registration(rid)
    if fee is None or fee["status"] != "PAID":
        raise err(E.ERR_FEES_UNPAID, "FeeAssessment is not PAID")

    # Gate 2 (priority 8): matching ISSUED title for the owner
    has_title = any(
        ta["vehicle_id"] == vehicle["id"]
        and ta["status"] == "ISSUED"
        and ta["applicant_owner_id"] == reg["owner_id"]
        for ta in db.title_applications.values()
    )
    if not has_title:
        raise err(E.ERR_TITLE_NOT_ISSUED, "No matching ISSUED title for owner")

    # Gate 3 (priority 7/17): emissions for >=2010 non-motorcycle
    now = clock.now()
    if vehicle["vehicle_class"] != "MOTORCYCLE" and vehicle["model_year"] >= 2010:
        passes = [
            e for e in db.emissions_inspections.values()
            if e["vehicle_id"] == vehicle["id"] and e["result"] == "PASS"
        ]
        valid = any(
            e["inspected_at"] <= now < e["valid_until"] for e in passes
        )
        if not valid:
            raise err(E.ERR_EMISSIONS_REQUIRED,
                      "A valid PASS emissions inspection is required")

    # Gate 4 (priority 16): term overlap vs ACTIVE registrations on same vehicle
    term_start = now
    term_end = now + timedelta(days=REGISTRATION_TERM_DAYS)
    for other in db.registrations.values():
        if other["id"] == rid:
            continue
        if other["vehicle_id"] != vehicle["id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        e_start = other["term_start"]
        e_end = other["term_end"]
        if e_start is None or e_end is None:
            continue
        if term_start < e_end and e_start < term_end:
            raise err(E.ERR_REGISTRATION_TERM_OVERLAP,
                      "Registration term overlaps an existing ACTIVE term")

    # commit
    reg["status"] = "ACTIVE"
    reg["term_start"] = term_start
    reg["term_end"] = term_end
    reg["plate_assigned"] = any(
        p["registration_id"] == rid for p in db.license_plates.values()
    )
    touch(reg)
    return success(view_registration(reg), 200)


@app.post("/registrations/<rid>/suspend")
def suspend_registration(rid):
    require_auth()
    require_role("DmvAdmin")
    reg = get_or_404(db.registrations, rid)
    if reg["status"] != "ACTIVE":
        raise err(E.ERR_INVALID_STATE, "Registration is not ACTIVE")
    for p in db.license_plates.values():
        if p["registration_id"] == rid and p["plate_type"] == "ELECTRONIC" \
                and p["status"] == "ACTIVE":
            p["status"] = "DEACTIVATED"
            touch(p)
    reg["status"] = "SUSPENDED"
    touch(reg)
    return success(view_registration(reg), 200)


@app.post("/registrations/<rid>/reinstate")
def reinstate_registration(rid):
    require_auth()
    require_role("DmvAdmin")
    data = body()
    require_fields(data, "expected_registration_version")
    expected = as_int(data["expected_registration_version"],
                      "expected_registration_version")
    reg = get_or_404(db.registrations, rid)
    if reg["status"] != "SUSPENDED":
        raise err(E.ERR_INVALID_STATE, "Registration is not SUSPENDED")
    if expected != reg["version"]:
        raise err(E.ERR_STALE_VERSION, "expected_registration_version mismatch")
    for p in db.license_plates.values():
        if p["registration_id"] == rid and p["plate_type"] == "ELECTRONIC" \
                and p["status"] == "DEACTIVATED":
            p["status"] = "ACTIVE"
            touch(p)
    reg["status"] = "ACTIVE"
    touch(reg)
    return success(view_registration(reg), 200)


@app.post("/registrations/<rid>/expire")
def expire_registration(rid):
    require_auth()
    require_role("DmvAdmin")
    reg = get_or_404(db.registrations, rid)
    if reg["status"] != "ACTIVE":
        raise err(E.ERR_INVALID_STATE, "Registration is not ACTIVE")
    now = clock.now()
    for p in db.license_plates.values():
        if p["registration_id"] == rid and p["status"] in {"ISSUED", "ACTIVE", "DEACTIVATED"}:
            p["status"] = "SURRENDERED"
            p["surrendered_at"] = now
            touch(p)
    reg["status"] = "EXPIRED"
    touch(reg)
    return success(view_registration(reg), 200)


# ===========================================================================
# FEE ASSESSMENTS
# ===========================================================================
COUNTY_RATES = {"KING": Decimal("0.025"), "PIERCE": Decimal("0.014")}
COUNTY_DEFAULT = Decimal("0.010")
STATE_USE_TAX_RATE = Decimal("0.065")
TRANSFER_USE_TAX_CAP_CENTS = 150000
REAL_ID_SURCHARGE_CENTS = 3000
CURRENT_REG_YEAR = 2026
WEIGHT_FEE = {"PASSENGER": 4300, "TRUCK": 9000, "MOTORCYCLE": 2500}


def _round_half_up(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _compute_use_tax(vehicle, registration):
    # Use the Owner's residence county code via Owner record.
    owner = db.owners[registration["owner_id"]]
    rate = COUNTY_RATES.get(owner["residence_county_code"], COUNTY_DEFAULT)
    combined = STATE_USE_TAX_RATE + rate
    basis = Decimal(vehicle["purchase_price_cents"])
    raw = basis * combined
    use_tax = _round_half_up(raw)
    if registration["registration_type"] == "TRANSFER":
        use_tax = min(use_tax, TRANSFER_USE_TAX_CAP_CENTS)
    return use_tax


def _compute_registration_fee(vehicle):
    age = CURRENT_REG_YEAR - vehicle["model_year"]
    if age <= 0:
        dep_rate = Decimal("0.0110")
    elif age <= 3:
        dep_rate = Decimal("0.0090")
    elif age <= 7:
        dep_rate = Decimal("0.0060")
    else:
        dep_rate = Decimal("0.0030")
    dep_component = _round_half_up(Decimal(vehicle["msrp_cents"]) * dep_rate)
    weight_fee = WEIGHT_FEE[vehicle["vehicle_class"]]
    return dep_component + weight_fee


@app.post("/fee-assessments")
def create_fee_assessment():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin")
    data = body()
    require_fields(data, "registration_id")
    reg = get_or_404(db.registrations, data["registration_id"])
    vehicle = db.vehicles[reg["vehicle_id"]]
    use_tax = _compute_use_tax(vehicle, reg)
    reg_fee = _compute_registration_fee(vehicle)
    surcharge = REAL_ID_SURCHARGE_CENTS if reg["bundle_real_id"] else 0
    total = use_tax + reg_fee + surcharge
    rec = {
        "registration_id": reg["id"],
        "use_tax_cents": use_tax,
        "registration_fee_cents": reg_fee,
        "real_id_surcharge_cents": surcharge,
        "total_cents": total,
        "status": "ASSESSED",
    }
    stamp_create(rec)
    db.fee_assessments[rec["id"]] = rec
    return success(view_fee_assessment(rec), 201)


@app.get("/fee-assessments/<rid>")
def get_fee_assessment(rid):
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rec = get_or_404(db.fee_assessments, rid)
    return success(view_fee_assessment(rec), 200)


@app.get("/fee-assessments")
def list_fee_assessments():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rows = list(db.fee_assessments.values())
    registration_id = request.args.get("registration_id")
    if registration_id is not None:
        rows = [r for r in rows if r["registration_id"] == registration_id]
    page, limit, offset, total = paginate(rows)
    return success_list([view_fee_assessment(r) for r in page], limit, offset, total)


@app.post("/fee-assessments/<rid>/pay")
def pay_fee_assessment(rid):
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    fee = get_or_404(db.fee_assessments, rid)
    if fee["status"] != "ASSESSED":
        raise err(E.ERR_INVALID_STATE, "FeeAssessment is not ASSESSED")
    fee["status"] = "PAID"
    touch(fee)
    return success(view_fee_assessment(fee), 200)


@app.post("/fee-assessments/<rid>/void")
def void_fee_assessment(rid):
    require_auth()
    require_role("DmvAdmin")
    fee = get_or_404(db.fee_assessments, rid)
    if fee["status"] != "ASSESSED":
        raise err(E.ERR_INVALID_STATE, "FeeAssessment is not ASSESSED")
    reg = db.registrations[fee["registration_id"]]
    if reg["status"] != "PENDING_FEES":
        raise err(E.ERR_REGISTRATION_NOT_ACTIVE,
                  "Registration is not PENDING_FEES")
    fee["status"] = "VOIDED"
    touch(fee)
    return success(view_fee_assessment(fee), 200)


# ===========================================================================
# LICENSE PLATES
# ===========================================================================
@app.post("/license-plates")
def create_license_plate():
    require_auth()
    require_role("ClerkAgent")
    data = body()
    require_fields(data, "registration_id", "plate_number", "plate_type",
                   "expected_registration_version")
    plate_type = require_enum(data["plate_type"],
                              {"PHYSICAL", "ELECTRONIC"}, "plate_type")
    expected = as_int(data["expected_registration_version"],
                      "expected_registration_version")
    reg = get_or_404(db.registrations, data["registration_id"])
    plate_number = data["plate_number"]
    now = clock.now()

    # priority 10: plate_number tenancy overlap
    for p in db.license_plates.values():
        if p["plate_number"] != plate_number:
            continue
        p_start = p["issued_at"]
        p_end = p["surrendered_at"]  # None => still open
        # overlap of half-open [p_start, p_end) with new [now, +inf open).
        # New tenancy is open-ended; forbidden unless prior tenancy closed
        # at or before the new issued_at.
        if p_end is None or p_end > now:
            raise err(E.ERR_PLATE_NUMBER_TAKEN, "plate_number tenancy overlaps")

    # priority 11: at most one non-surrendered plate per registration
    for p in db.license_plates.values():
        if p["registration_id"] == reg["id"] and \
                p["status"] in {"ISSUED", "ACTIVE", "DEACTIVATED"}:
            raise err(E.ERR_PLATE_ALREADY_ASSIGNED,
                      "Registration already has a non-surrendered plate")

    # priority 15: OCC
    if expected != reg["version"]:
        raise err(E.ERR_STALE_VERSION, "expected_registration_version mismatch")

    rec = {
        "registration_id": reg["id"],
        "plate_number": plate_number,
        "plate_type": plate_type,
        "issued_at": now,
        "surrendered_at": None,
        "status": "ISSUED",
    }
    stamp_create(rec)
    db.license_plates[rec["id"]] = rec
    reg["plate_assigned"] = True
    touch(reg)
    return success(view_license_plate(rec), 201)


@app.get("/license-plates/<rid>")
def get_license_plate(rid):
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rec = get_or_404(db.license_plates, rid)
    return success(view_license_plate(rec), 200)


@app.get("/license-plates")
def list_license_plates():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rows = list(db.license_plates.values())
    registration_id = request.args.get("registration_id")
    if registration_id is not None:
        rows = [r for r in rows if r["registration_id"] == registration_id]
    page, limit, offset, total = paginate(rows)
    return success_list([view_license_plate(r) for r in page], limit, offset, total)


@app.post("/license-plates/<rid>/activate")
def activate_license_plate(rid):
    require_auth()
    require_role("ClerkAgent")
    plate = get_or_404(db.license_plates, rid)
    if plate["status"] not in {"ISSUED", "DEACTIVATED"}:
        raise err(E.ERR_INVALID_STATE, "Plate cannot be activated")
    reg = db.registrations[plate["registration_id"]]
    if reg["status"] != "ACTIVE":
        raise err(E.ERR_REGISTRATION_NOT_ACTIVE, "Parent registration is not ACTIVE")
    plate["status"] = "ACTIVE"
    touch(plate)
    return success(view_license_plate(plate), 200)


@app.post("/license-plates/<rid>/deactivate")
def deactivate_license_plate(rid):
    require_auth()
    require_role("ClerkAgent")
    plate = get_or_404(db.license_plates, rid)
    if plate["status"] != "ACTIVE":
        raise err(E.ERR_INVALID_STATE, "Plate is not ACTIVE")
    if plate["plate_type"] != "ELECTRONIC":
        raise err(E.ERR_PLATE_NOT_ELECTRONIC, "Plate is not ELECTRONIC")
    plate["status"] = "DEACTIVATED"
    touch(plate)
    return success(view_license_plate(plate), 200)


# ===========================================================================
# REAL ID APPLICATIONS
# ===========================================================================
@app.post("/real-id-applications")
def create_real_id_application():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    data = body()
    require_fields(data, "owner_id")
    get_or_404(db.owners, data["owner_id"])
    docs = opt(data, "documents_complete", False)
    docs = as_bool(docs, "documents_complete")
    rec = {
        "owner_id": data["owner_id"],
        "status": "SUBMITTED",
        "documents_complete": docs,
    }
    stamp_create(rec)
    db.real_id_applications[rec["id"]] = rec
    return success(view_real_id_application(rec), 201)


@app.get("/real-id-applications/<rid>")
def get_real_id_application(rid):
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rec = get_or_404(db.real_id_applications, rid)
    return success(view_real_id_application(rec), 200)


@app.get("/real-id-applications")
def list_real_id_applications():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin", "Owner")
    rows = list(db.real_id_applications.values())
    owner_id = request.args.get("owner_id")
    if owner_id is not None:
        rows = [r for r in rows if r["owner_id"] == owner_id]
    page, limit, offset, total = paginate(rows)
    return success_list([view_real_id_application(r) for r in page], limit, offset, total)


@app.post("/real-id-applications/<rid>/begin-review")
def begin_review_real_id(rid):
    require_auth()
    require_role("ClerkAgent")
    rec = get_or_404(db.real_id_applications, rid)
    if rec["status"] != "SUBMITTED":
        raise err(E.ERR_INVALID_STATE, "Application is not SUBMITTED")
    rec["status"] = "UNDER_REVIEW"
    touch(rec)
    owner = db.owners[rec["owner_id"]]
    owner["real_id_status"] = "PENDING"
    touch(owner)
    return success(view_real_id_application(rec), 200)


@app.post("/real-id-applications/<rid>/approve")
def approve_real_id(rid):
    require_auth()
    require_role("ClerkAgent")
    rec = get_or_404(db.real_id_applications, rid)
    if rec["status"] != "UNDER_REVIEW":
        raise err(E.ERR_INVALID_STATE, "Application is not UNDER_REVIEW")
    owner = db.owners[rec["owner_id"]]
    if not (rec["documents_complete"] and owner["identity_documents_verified"]):
        raise err(E.ERR_DOCUMENTS_INCOMPLETE,
                  "Documents incomplete or identity not verified")
    rec["status"] = "APPROVED"
    touch(rec)
    owner["credential_type"] = "REAL_ID"
    owner["real_id_status"] = "UPGRADED"
    touch(owner)
    return success(view_real_id_application(rec), 200)


@app.post("/real-id-applications/<rid>/deny")
def deny_real_id(rid):
    require_auth()
    require_role("ClerkAgent")
    rec = get_or_404(db.real_id_applications, rid)
    if rec["status"] != "UNDER_REVIEW":
        raise err(E.ERR_INVALID_STATE, "Application is not UNDER_REVIEW")
    rec["status"] = "DENIED"
    touch(rec)
    owner = db.owners[rec["owner_id"]]
    owner["real_id_status"] = "NONE"
    touch(owner)
    return success(view_real_id_application(rec), 200)


@app.post("/real-id-applications/<rid>/return-for-documents")
def return_real_id(rid):
    require_auth()
    require_role("ClerkAgent")
    rec = get_or_404(db.real_id_applications, rid)
    if rec["status"] != "UNDER_REVIEW":
        raise err(E.ERR_INVALID_STATE, "Application is not UNDER_REVIEW")
    rec["status"] = "SUBMITTED"
    touch(rec)
    owner = db.owners[rec["owner_id"]]
    owner["real_id_status"] = "NONE"
    touch(owner)
    return success(view_real_id_application(rec), 200)


# ===========================================================================
# CLOCK (test-driving)
# ===========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    require_auth()
    require_role("ClerkAgent", "DmvAdmin")
    data = body()
    require_fields(data, "to_iso8601")
    try:
        dt = parse_iso(data["to_iso8601"])
    except (ValueError, TypeError):
        raise err(E.ERR_VALIDATION, "Invalid to_iso8601")
    clock.set(dt)
    return success({}, 200)


# ===========================================================================
# Error handlers
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_VALIDATION", "Internal error: %s" % str(e), 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
