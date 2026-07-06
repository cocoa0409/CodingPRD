import os

from flask import Flask, request

import errors
import services as svc
from clock import clock, parse_iso8601, format_iso8601_ms
from db import db, base_fields, touch
from errors import ApiError, err
from middleware import require_auth, require_roles, ALL_ROLES, paginate
from response import object_response, array_response, error_response

app = Flask(__name__)


# ===========================================================================
# Error handling
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
        return handle_api_error(e)
    return error_response("ERR_VALIDATION", str(e), 422)


def get_json():
    """Return the request JSON body as a dict (empty dict when absent)."""
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None:
        # Fallback: parse the raw body directly regardless of content-type.
        import json as _json
        try:
            data = _json.loads(raw.decode("utf-8"))
        except Exception:
            raise err(errors.ERR_VALIDATION, "Malformed JSON body")
    if not isinstance(data, dict):
        raise err(errors.ERR_VALIDATION, "Body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(errors.ERR_VALIDATION, f"Missing required field: {f}")


def check_enum(value, allowed, field):
    if value not in allowed:
        raise err(errors.ERR_VALIDATION, f"Invalid value for {field}")


# ---- existence helpers ----
def get_cemetery_or_404(cemetery_id):
    c = db.cemeteries.get(cemetery_id)
    if c is None:
        raise err(errors.ERR_NOT_FOUND, "Cemetery not found")
    return c


def get_scoped(collection, res_id, cemetery_id, cem_field="cemetery_id"):
    """Fetch a resource that must belong to the given cemetery (path scoping)."""
    r = collection.get(res_id)
    if r is None or r.get(cem_field) != cemetery_id:
        raise err(errors.ERR_NOT_FOUND, "Resource not found")
    return r


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin"})
    body = get_json()
    require_fields(body, ["to_iso8601"])
    try:
        clock.set(body["to_iso8601"])
    except Exception:
        raise err(errors.ERR_VALIDATION, "Invalid to_iso8601")
    return object_response({}, 200)


# ===========================================================================
# Cemetery
# ===========================================================================
def serialize_cemetery(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "country_code": c["country_code"],
        "is_overseas": c["is_overseas"],
        "honors_squad_capacity": c["honors_squad_capacity"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "_seq": c["_seq"],
    }


@app.route("/cemeteries", methods=["POST"])
def create_cemetery():
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin"})
    body = get_json()
    require_fields(body, ["name", "honors_squad_capacity"])
    country = body.get("country_code", "US")
    if country is None:
        country = "US"
    cap = body["honors_squad_capacity"]
    if not isinstance(cap, int) or isinstance(cap, bool):
        raise err(errors.ERR_VALIDATION, "honors_squad_capacity must be an integer")
    rec = base_fields()
    rec.update({
        "name": body["name"],
        "country_code": country,
        "is_overseas": country != "US",
        "honors_squad_capacity": cap,
    })
    db.cemeteries[rec["id"]] = rec
    return object_response(serialize_cemetery(rec), 201)


@app.route("/cemeteries", methods=["GET"])
def list_cemeteries():
    _uid, role = require_auth()
    require_roles(role, ALL_ROLES)
    page, limit, offset, total = paginate(list(db.cemeteries.values()))
    return array_response([serialize_cemetery(c) for c in page], limit, offset, total)


@app.route("/cemeteries/<cemetery_id>", methods=["GET"])
def get_cemetery(cemetery_id):
    _uid, role = require_auth()
    require_roles(role, ALL_ROLES)
    c = get_cemetery_or_404(cemetery_id)
    return object_response(serialize_cemetery(c), 200)


# ===========================================================================
# Section
# ===========================================================================
def serialize_section(s):
    svc.recompute_section_inventory(s)
    return {
        "id": s["id"],
        "cemetery_id": s["cemetery_id"],
        "code": s["code"],
        "kind": s["kind"],
        "capacity_units": s["capacity_units"],
        "available_units": s["available_units"],
        "interred_units": s["interred_units"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "_seq": s["_seq"],
    }


@app.route("/cemeteries/<cemetery_id>/sections", methods=["POST"])
def create_section(cemetery_id):
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin"})
    get_cemetery_or_404(cemetery_id)
    body = get_json()
    require_fields(body, ["code", "kind"])
    check_enum(body["kind"], {"IN_GROUND", "COLUMBARIUM"}, "kind")
    rec = base_fields()
    rec.update({
        "cemetery_id": cemetery_id,
        "code": body["code"],
        "kind": body["kind"],
        "capacity_units": 0,
        "available_units": 0,
        "interred_units": 0,
    })
    db.sections[rec["id"]] = rec
    return object_response(serialize_section(rec), 201)


@app.route("/cemeteries/<cemetery_id>/sections", methods=["GET"])
def list_sections(cemetery_id):
    _uid, role = require_auth()
    require_roles(role, ALL_ROLES)
    get_cemetery_or_404(cemetery_id)
    items = [s for s in db.sections.values() if s["cemetery_id"] == cemetery_id]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_section(s) for s in page], limit, offset, total)


@app.route("/cemeteries/<cemetery_id>/sections/<section_id>", methods=["GET"])
def get_section(cemetery_id, section_id):
    _uid, role = require_auth()
    require_roles(role, ALL_ROLES)
    get_cemetery_or_404(cemetery_id)
    s = get_scoped(db.sections, section_id, cemetery_id)
    return object_response(serialize_section(s), 200)


# ===========================================================================
# Gravesite
# ===========================================================================
def serialize_gravesite(g):
    return {
        "id": g["id"],
        "section_id": g["section_id"],
        "grid_ref": g["grid_ref"],
        "gravesite_class": g["gravesite_class"],
        "depth_capacity": g["depth_capacity"],
        "interment_count": g["interment_count"],
        "status": g["status"],
        "reserved_by_case_id": g["reserved_by_case_id"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
        "_seq": g["_seq"],
    }


@app.route("/cemeteries/<cemetery_id>/sections/<section_id>/gravesites", methods=["POST"])
def create_gravesite(cemetery_id, section_id):
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin"})
    get_cemetery_or_404(cemetery_id)
    section = get_scoped(db.sections, section_id, cemetery_id)
    body = get_json()
    require_fields(body, ["grid_ref", "gravesite_class", "depth_capacity"])
    check_enum(body["gravesite_class"], {"STANDARD", "OVERSIZE", "CREMATION"}, "gravesite_class")
    if section["kind"] != "IN_GROUND":
        raise err(errors.ERR_UNIT_KIND_MISMATCH, "Gravesite requires an IN_GROUND section")
    rec = base_fields()
    rec.update({
        "section_id": section_id,
        "grid_ref": body["grid_ref"],
        "gravesite_class": body["gravesite_class"],
        "depth_capacity": body["depth_capacity"],
        "interment_count": 0,
        "status": "AVAILABLE",
        "reserved_by_case_id": None,
    })
    db.gravesites[rec["id"]] = rec
    svc.recompute_section_inventory(section)
    return object_response(serialize_gravesite(rec), 201)


@app.route("/cemeteries/<cemetery_id>/sections/<section_id>/gravesites", methods=["GET"])
def list_gravesites(cemetery_id, section_id):
    _uid, role = require_auth()
    require_roles(role, ALL_ROLES)
    get_cemetery_or_404(cemetery_id)
    get_scoped(db.sections, section_id, cemetery_id)
    status = request.args.get("status")
    items = [g for g in db.gravesites.values() if g["section_id"] == section_id]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_gravesite(g) for g in page], limit, offset, total)


@app.route("/cemeteries/<cemetery_id>/sections/<section_id>/gravesites/<gravesite_id>", methods=["GET"])
def get_gravesite(cemetery_id, section_id, gravesite_id):
    _uid, role = require_auth()
    require_roles(role, ALL_ROLES)
    get_cemetery_or_404(cemetery_id)
    get_scoped(db.sections, section_id, cemetery_id)
    g = db.gravesites.get(gravesite_id)
    if g is None or g["section_id"] != section_id:
        raise err(errors.ERR_NOT_FOUND, "Gravesite not found")
    return object_response(serialize_gravesite(g), 200)


@app.route("/cemeteries/<cemetery_id>/sections/<section_id>/gravesites/<gravesite_id>/decommission", methods=["POST"])
def decommission_gravesite(cemetery_id, section_id, gravesite_id):
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin"})
    get_cemetery_or_404(cemetery_id)
    section = get_scoped(db.sections, section_id, cemetery_id)
    g = db.gravesites.get(gravesite_id)
    if g is None or g["section_id"] != section_id:
        raise err(errors.ERR_NOT_FOUND, "Gravesite not found")
    if g["status"] != "AVAILABLE":
        raise err(errors.ERR_INVALID_STATE, "Only AVAILABLE gravesites can be decommissioned")
    g["status"] = "DECOMMISSIONED"
    touch(g)
    svc.recompute_section_inventory(section)
    return object_response(serialize_gravesite(g), 200)


# ===========================================================================
# Niche
# ===========================================================================
def serialize_niche(n):
    return {
        "id": n["id"],
        "section_id": n["section_id"],
        "niche_ref": n["niche_ref"],
        "urn_capacity": n["urn_capacity"],
        "inurnment_count": n["inurnment_count"],
        "status": n["status"],
        "reserved_by_case_id": n["reserved_by_case_id"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
        "_seq": n["_seq"],
    }


@app.route("/cemeteries/<cemetery_id>/sections/<section_id>/niches", methods=["POST"])
def create_niche(cemetery_id, section_id):
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin"})
    get_cemetery_or_404(cemetery_id)
    section = get_scoped(db.sections, section_id, cemetery_id)
    body = get_json()
    require_fields(body, ["niche_ref", "urn_capacity"])
    if section["kind"] != "COLUMBARIUM":
        raise err(errors.ERR_UNIT_KIND_MISMATCH, "Niche requires a COLUMBARIUM section")
    rec = base_fields()
    rec.update({
        "section_id": section_id,
        "niche_ref": body["niche_ref"],
        "urn_capacity": body["urn_capacity"],
        "inurnment_count": 0,
        "status": "AVAILABLE",
        "reserved_by_case_id": None,
    })
    db.niches[rec["id"]] = rec
    svc.recompute_section_inventory(section)
    return object_response(serialize_niche(rec), 201)


@app.route("/cemeteries/<cemetery_id>/sections/<section_id>/niches", methods=["GET"])
def list_niches(cemetery_id, section_id):
    _uid, role = require_auth()
    require_roles(role, ALL_ROLES)
    get_cemetery_or_404(cemetery_id)
    get_scoped(db.sections, section_id, cemetery_id)
    status = request.args.get("status")
    items = [n for n in db.niches.values() if n["section_id"] == section_id]
    if status is not None:
        items = [n for n in items if n["status"] == status]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_niche(n) for n in page], limit, offset, total)


@app.route("/cemeteries/<cemetery_id>/sections/<section_id>/niches/<niche_id>", methods=["GET"])
def get_niche(cemetery_id, section_id, niche_id):
    _uid, role = require_auth()
    require_roles(role, ALL_ROLES)
    get_cemetery_or_404(cemetery_id)
    get_scoped(db.sections, section_id, cemetery_id)
    n = db.niches.get(niche_id)
    if n is None or n["section_id"] != section_id:
        raise err(errors.ERR_NOT_FOUND, "Niche not found")
    return object_response(serialize_niche(n), 200)


# ===========================================================================
# BurialCase
# ===========================================================================
def serialize_case(c):
    return {
        "id": c["id"],
        "cemetery_id": c["cemetery_id"],
        "case_type": c["case_type"],
        "applicant_role": c["applicant_role"],
        "reserving_case_id": c["reserving_case_id"],
        "is_overseas_case": c["is_overseas_case"],
        "character_of_discharge": c["character_of_discharge"],
        "service_days": c["service_days"],
        "died_on_active_duty": c["died_on_active_duty"],
        "requested_class": c["requested_class"],
        "entitlement_score": c["entitlement_score"],
        "assigned_unit_type": c["assigned_unit_type"],
        "assigned_gravesite_id": c["assigned_gravesite_id"],
        "assigned_niche_id": c["assigned_niche_id"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "_seq": c["_seq"],
    }


@app.route("/cemeteries/<cemetery_id>/burial-cases", methods=["POST"])
def create_case(cemetery_id):
    _uid, role = require_auth()
    require_roles(role, {"EligibilityOfficer", "SchedulingClerk"})
    get_cemetery_or_404(cemetery_id)
    body = get_json()
    require_fields(body, ["case_type", "applicant_role", "requested_class"])
    check_enum(body["case_type"], {"AT_NEED", "PRE_NEED"}, "case_type")
    check_enum(body["applicant_role"], {"VETERAN", "SPOUSE", "DEPENDENT"}, "applicant_role")
    check_enum(body["requested_class"], {"STANDARD", "OVERSIZE", "CREMATION"}, "requested_class")
    discharge = body.get("character_of_discharge")
    if discharge is not None:
        check_enum(discharge, {"HONORABLE", "GENERAL", "OTHER_THAN_HONORABLE", "DISHONORABLE"},
                   "character_of_discharge")
    reserving_case_id = body.get("reserving_case_id")
    # Body FK resolution (ERR_REFERENCE_NOT_FOUND)
    if reserving_case_id is not None and reserving_case_id not in db.burial_cases:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "reserving_case_id does not resolve")
    rec = base_fields()
    rec.update({
        "cemetery_id": cemetery_id,
        "case_type": body["case_type"],
        "applicant_role": body["applicant_role"],
        "reserving_case_id": reserving_case_id,
        "is_overseas_case": bool(body.get("is_overseas_case", False)),
        "character_of_discharge": discharge,
        "service_days": body.get("service_days", 0) if body.get("service_days") is not None else 0,
        "died_on_active_duty": bool(body.get("died_on_active_duty", False)),
        "requested_class": body["requested_class"],
        "entitlement_score": None,
        "assigned_unit_type": None,
        "assigned_gravesite_id": None,
        "assigned_niche_id": None,
        "status": "SUBMITTED",
    })
    db.burial_cases[rec["id"]] = rec
    return object_response(serialize_case(rec), 201)


@app.route("/cemeteries/<cemetery_id>/burial-cases", methods=["GET"])
def list_cases(cemetery_id):
    _uid, role = require_auth()
    require_roles(role, ALL_ROLES)
    get_cemetery_or_404(cemetery_id)
    items = [c for c in db.burial_cases.values() if c["cemetery_id"] == cemetery_id]
    for field in ("status", "reserving_case_id", "assigned_gravesite_id", "assigned_niche_id"):
        val = request.args.get(field)
        if val is not None:
            items = [c for c in items if c.get(field) == val]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_case(c) for c in page], limit, offset, total)


@app.route("/cemeteries/<cemetery_id>/burial-cases/<case_id>", methods=["GET"])
def get_case(cemetery_id, case_id):
    _uid, role = require_auth()
    require_roles(role, ALL_ROLES)
    get_cemetery_or_404(cemetery_id)
    c = get_scoped(db.burial_cases, case_id, cemetery_id)
    return object_response(serialize_case(c), 200)


# ---- Eligibility ----
def serialize_determination(d):
    return {
        "id": d["id"],
        "burial_case_id": d["burial_case_id"],
        "decision": d["decision"],
        "basis": d["basis"],
        "denial_reason": d["denial_reason"],
        "decided_by_user_id": d["decided_by_user_id"],
        "created_at": d["created_at"],
    }


@app.route("/cemeteries/<cemetery_id>/burial-cases/<case_id>/eligibility", methods=["POST"])
def run_eligibility(cemetery_id, case_id):
    uid, role = require_auth()
    require_roles(role, {"EligibilityOfficer"})
    cemetery = get_cemetery_or_404(cemetery_id)
    case = get_scoped(db.burial_cases, case_id, cemetery_id)
    if case["status"] != "SUBMITTED":
        raise err(errors.ERR_INVALID_STATE, "Case is not SUBMITTED")

    result = svc.eligibility_decision(case, cemetery)
    from db import base_fields as _bf
    det = _bf(with_version=False)
    det.update({
        "burial_case_id": case_id,
        "decision": result["decision"],
        "basis": result["basis"],
        "denial_reason": result["denial_reason"],
        "decided_by_user_id": uid,
    })
    db.eligibility_determinations[det["id"]] = det

    if result["decision"] == "APPROVED":
        case["status"] = "ELIGIBLE"
        case["entitlement_score"] = svc.entitlement_score(case)
    else:
        case["status"] = "INELIGIBLE"
    touch(case)
    return object_response(serialize_determination(det), 201)


@app.route("/cemeteries/<cemetery_id>/burial-cases/<case_id>/eligibility", methods=["GET"])
def get_eligibility(cemetery_id, case_id):
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin", "EligibilityOfficer", "SchedulingClerk"})
    get_cemetery_or_404(cemetery_id)
    get_scoped(db.burial_cases, case_id, cemetery_id)
    items = [d for d in db.eligibility_determinations.values() if d["burial_case_id"] == case_id]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_determination(d) for d in page], limit, offset, total)


# ---- Assign / release / cancel ----
@app.route("/cemeteries/<cemetery_id>/burial-cases/<case_id>/assign-plot", methods=["POST"])
def assign_plot(cemetery_id, case_id):
    _uid, role = require_auth()
    require_roles(role, {"SchedulingClerk"})
    get_cemetery_or_404(cemetery_id)
    case = get_scoped(db.burial_cases, case_id, cemetery_id)
    body = get_json()

    unit_id = body.get("unit_id")
    # Body FK resolution for explicit unit
    if unit_id is not None:
        if unit_id not in db.gravesites and unit_id not in db.niches:
            raise err(errors.ERR_REFERENCE_NOT_FOUND, "unit_id does not resolve")

    if case["status"] != "ELIGIBLE":
        raise err(errors.ERR_INVALID_STATE, "Case is not ELIGIBLE")

    # PRE_NEED gating
    pmc = None
    if case["case_type"] == "PRE_NEED":
        pmcs = [p for p in db.pre_need_determinations.values() if p["burial_case_id"] == case_id]
        approved = [p for p in pmcs if p["status"] == "APPROVED"]
        if not approved:
            raise err(errors.ERR_PMC_REQUIRED, "An APPROVED pre-need determination is required")
        pmc = approved[0]
        if pmc["expires_on"] is not None:
            if clock.now() >= parse_iso8601(pmc["expires_on"]):
                raise err(errors.ERR_PMC_EXPIRED, "The approved PMC window has elapsed")

    # Select the unit
    if unit_id is not None:
        unit_type = body.get("unit_type")
        gunit = db.gravesites.get(unit_id)
        nunit = db.niches.get(unit_id)
        if gunit is not None:
            unit = gunit
            resolved_type = "GRAVESITE"
        else:
            unit = nunit
            resolved_type = "NICHE"
        section = db.sections.get(unit["section_id"])
        # Must belong to the case's cemetery
        if section is None or section["cemetery_id"] != case["cemetery_id"]:
            raise err(errors.ERR_UNIT_KIND_MISMATCH, "Unit is not in the case's cemetery")
        # OCC on explicit gravesite assignment
        if resolved_type == "GRAVESITE":
            expected = body.get("expected_gravesite_version")
            if expected is not None and expected != unit["version"]:
                raise err(errors.ERR_STALE_GRAVESITE_VERSION, "Gravesite version is stale")
        # Assignable state: AVAILABLE or already reserved by this same case
        assignable = unit["status"] == "AVAILABLE" or (
            unit["status"] == "RESERVED" and unit.get("reserved_by_case_id") == case_id
        )
        # class match
        if resolved_type == "GRAVESITE":
            class_ok = unit["gravesite_class"] == case["requested_class"]
        else:
            class_ok = case["requested_class"] == "CREMATION"
        if not assignable or not class_ok:
            raise err(errors.ERR_NO_AVAILABLE_UNIT, "Explicit unit is not assignable")
    else:
        selected = svc.auto_select_unit(case)
        if selected is None:
            raise err(errors.ERR_NO_AVAILABLE_UNIT, "No available unit matches the requested class")
        unit, resolved_type = selected
        section = db.sections.get(unit["section_id"])

    # Commit assignment
    case["assigned_unit_type"] = resolved_type
    if resolved_type == "GRAVESITE":
        case["assigned_gravesite_id"] = unit["id"]
        case["assigned_niche_id"] = None
    else:
        case["assigned_niche_id"] = unit["id"]
        case["assigned_gravesite_id"] = None
    case["status"] = "ASSIGNED"
    touch(case)

    if unit["status"] == "AVAILABLE":
        unit["status"] = "RESERVED"
        unit["reserved_by_case_id"] = case_id
        touch(unit)
    svc.recompute_section_inventory(section)

    # PRE_NEED: APPROVED -> RESERVED
    if pmc is not None:
        pmc["status"] = "RESERVED"
        touch(pmc)

    return object_response(serialize_case(case), 200)


@app.route("/cemeteries/<cemetery_id>/burial-cases/<case_id>/release-plot", methods=["POST"])
def release_plot(cemetery_id, case_id):
    _uid, role = require_auth()
    require_roles(role, {"SchedulingClerk"})
    get_cemetery_or_404(cemetery_id)
    case = get_scoped(db.burial_cases, case_id, cemetery_id)
    if case["status"] != "ASSIGNED":
        raise err(errors.ERR_INVALID_STATE, "Case is not ASSIGNED")
    # No SCHEDULED/COMPLETED schedule references this case
    blocking = [s for s in db.interment_schedules.values()
                if s["burial_case_id"] == case_id and s["status"] in ("SCHEDULED", "COMPLETED")]
    if blocking:
        raise err(errors.ERR_INVALID_STATE, "Case has an active interment schedule")

    _release_case_unit(case)
    case["status"] = "ELIGIBLE"
    touch(case)
    return object_response(serialize_case(case), 200)


def _release_case_unit(case):
    """Return a case's reserved unit to AVAILABLE and clear assignment pointers."""
    unit = None
    if case.get("assigned_gravesite_id"):
        unit = db.gravesites.get(case["assigned_gravesite_id"])
    elif case.get("assigned_niche_id"):
        unit = db.niches.get(case["assigned_niche_id"])
    if unit is not None and unit["status"] == "RESERVED":
        unit["status"] = "AVAILABLE"
        unit["reserved_by_case_id"] = None
        touch(unit)
        section = db.sections.get(unit["section_id"])
        if section is not None:
            svc.recompute_section_inventory(section)
    case["assigned_unit_type"] = None
    case["assigned_gravesite_id"] = None
    case["assigned_niche_id"] = None


@app.route("/cemeteries/<cemetery_id>/burial-cases/<case_id>/cancel", methods=["POST"])
def cancel_case(cemetery_id, case_id):
    _uid, role = require_auth()
    require_roles(role, {"SchedulingClerk"})
    get_cemetery_or_404(cemetery_id)
    case = get_scoped(db.burial_cases, case_id, cemetery_id)
    if case["status"] != "ELIGIBLE":
        raise err(errors.ERR_INVALID_STATE, "Case is not ELIGIBLE")
    case["status"] = "CANCELLED"
    touch(case)
    return object_response(serialize_case(case), 200)


# ===========================================================================
# PreNeedDetermination (PMC)
# ===========================================================================
def serialize_pmc(p):
    return {
        "id": p["id"],
        "burial_case_id": p["burial_case_id"],
        "pmc_number": p["pmc_number"],
        "status": p["status"],
        "expires_on": p["expires_on"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "_seq": p["_seq"],
    }


@app.route("/cemeteries/<cemetery_id>/pre-need-determinations", methods=["POST"])
def create_pmc(cemetery_id):
    _uid, role = require_auth()
    require_roles(role, {"EligibilityOfficer"})
    get_cemetery_or_404(cemetery_id)
    body = get_json()
    require_fields(body, ["burial_case_id"])
    case = db.burial_cases.get(body["burial_case_id"])
    if case is None or case["cemetery_id"] != cemetery_id:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "burial_case_id does not resolve")
    if case["case_type"] != "PRE_NEED":
        raise err(errors.ERR_VALIDATION, "Case must be PRE_NEED")
    rec = base_fields()
    rec.update({
        "burial_case_id": body["burial_case_id"],
        "pmc_number": None,
        "status": "PENDING",
        "expires_on": None,
    })
    db.pre_need_determinations[rec["id"]] = rec
    return object_response(serialize_pmc(rec), 201)


@app.route("/cemeteries/<cemetery_id>/pre-need-determinations", methods=["GET"])
def list_pmc(cemetery_id):
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin", "EligibilityOfficer", "SchedulingClerk"})
    get_cemetery_or_404(cemetery_id)
    case_ids = {c["id"] for c in db.burial_cases.values() if c["cemetery_id"] == cemetery_id}
    items = [p for p in db.pre_need_determinations.values() if p["burial_case_id"] in case_ids]
    for field in ("burial_case_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [p for p in items if p.get(field) == val]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_pmc(p) for p in page], limit, offset, total)


def _get_pmc_scoped(cemetery_id, pmc_id):
    p = db.pre_need_determinations.get(pmc_id)
    if p is None:
        raise err(errors.ERR_NOT_FOUND, "PMC not found")
    case = db.burial_cases.get(p["burial_case_id"])
    if case is None or case["cemetery_id"] != cemetery_id:
        raise err(errors.ERR_NOT_FOUND, "PMC not found")
    return p, case


@app.route("/cemeteries/<cemetery_id>/pre-need-determinations/<pmc_id>", methods=["GET"])
def get_pmc(cemetery_id, pmc_id):
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin", "EligibilityOfficer", "SchedulingClerk"})
    get_cemetery_or_404(cemetery_id)
    p, _case = _get_pmc_scoped(cemetery_id, pmc_id)
    return object_response(serialize_pmc(p), 200)


@app.route("/cemeteries/<cemetery_id>/pre-need-determinations/<pmc_id>/approve", methods=["POST"])
def approve_pmc(cemetery_id, pmc_id):
    _uid, role = require_auth()
    require_roles(role, {"EligibilityOfficer"})
    get_cemetery_or_404(cemetery_id)
    p, case = _get_pmc_scoped(cemetery_id, pmc_id)
    body = get_json()
    require_fields(body, ["expected_pmc_version"])
    # OCC staleness precedes the state check: §2.9 specifies that when the version
    # has advanced (e.g. a denial was recorded against the pending certificate),
    # a stale approval is rejected with ERR_STALE_PMC_VERSION rather than overwriting.
    if body["expected_pmc_version"] != p["version"]:
        raise err(errors.ERR_STALE_PMC_VERSION, "PMC version is stale")
    if p["status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "PMC is not PENDING")
    # Business precondition: linked case PRE_NEED and ELIGIBLE
    if case["case_type"] != "PRE_NEED" or case["status"] != "ELIGIBLE":
        raise err(errors.ERR_INVALID_STATE, "Linked case must be PRE_NEED and ELIGIBLE")
    p["status"] = "APPROVED"
    p["pmc_number"] = "PMC-" + p["id"][:8].upper()
    from datetime import timedelta
    p["expires_on"] = format_iso8601_ms(clock.now() + timedelta(days=svc.PMC_RESERVATION_DAYS))
    touch(p)
    return object_response(serialize_pmc(p), 200)


@app.route("/cemeteries/<cemetery_id>/pre-need-determinations/<pmc_id>/deny", methods=["POST"])
def deny_pmc(cemetery_id, pmc_id):
    _uid, role = require_auth()
    require_roles(role, {"EligibilityOfficer"})
    get_cemetery_or_404(cemetery_id)
    p, _case = _get_pmc_scoped(cemetery_id, pmc_id)
    if p["status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "PMC is not PENDING")
    p["status"] = "DENIED"
    touch(p)
    return object_response(serialize_pmc(p), 200)


@app.route("/cemeteries/<cemetery_id>/pre-need-determinations/<pmc_id>/expire-sweep", methods=["POST"])
def expire_pmc(cemetery_id, pmc_id):
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin"})
    get_cemetery_or_404(cemetery_id)
    p, case = _get_pmc_scoped(cemetery_id, pmc_id)
    if p["status"] != "APPROVED":
        raise err(errors.ERR_INVALID_STATE, "PMC is not APPROVED")
    # Precondition: current >= expires_on and case not INTERRED
    if p["expires_on"] is None or clock.now() < parse_iso8601(p["expires_on"]):
        raise err(errors.ERR_INVALID_STATE, "PMC reservation window has not elapsed")
    if case["status"] == "INTERRED":
        raise err(errors.ERR_INVALID_STATE, "Linked case is already interred")

    # Release reserved unit / revert ASSIGNED case
    if case["status"] == "ASSIGNED":
        _release_case_unit(case)
        case["status"] = "ELIGIBLE"
        touch(case)
    else:
        # Not ASSIGNED but may still hold a reserved unit defensively
        _release_case_unit(case)

    p["status"] = "EXPIRED"
    touch(p)
    return object_response(serialize_pmc(p), 200)


# ===========================================================================
# IntermentSchedule
# ===========================================================================
def serialize_schedule(s):
    return {
        "id": s["id"],
        "burial_case_id": s["burial_case_id"],
        "gravesite_id": s["gravesite_id"],
        "niche_id": s["niche_id"],
        "window_start": s["window_start"],
        "window_end": s["window_end"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "_seq": s["_seq"],
    }


@app.route("/cemeteries/<cemetery_id>/interment-schedules", methods=["POST"])
def create_schedule(cemetery_id):
    _uid, role = require_auth()
    require_roles(role, {"SchedulingClerk"})
    get_cemetery_or_404(cemetery_id)
    body = get_json()
    require_fields(body, ["burial_case_id", "window_start", "window_end"])
    case = db.burial_cases.get(body["burial_case_id"])
    if case is None or case["cemetery_id"] != cemetery_id:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "burial_case_id does not resolve")
    if case["status"] != "ASSIGNED":
        raise err(errors.ERR_INVALID_STATE, "Case is not ASSIGNED")

    try:
        w_start = parse_iso8601(body["window_start"])
        w_end = parse_iso8601(body["window_end"])
    except Exception:
        raise err(errors.ERR_VALIDATION, "Invalid window datetime")

    # ERR_INVALID_WINDOW: window_end must be strictly > window_start
    if not (w_end > w_start):
        raise err(errors.ERR_INVALID_WINDOW, "window_end must be after window_start")

    is_gravesite = case["assigned_unit_type"] == "GRAVESITE"
    if is_gravesite:
        gid = case["assigned_gravesite_id"]
        existing = [s for s in db.interment_schedules.values()
                    if s["gravesite_id"] == gid and s["status"] in ("SCHEDULED", "COMPLETED")]
        if svc.gravesite_conflict(w_start, w_end, existing):
            raise err(errors.ERR_GRAVESITE_WINDOW_CONFLICT, "Gravesite window conflict")
    else:
        nid = case["assigned_niche_id"]
        existing = [s for s in db.interment_schedules.values()
                    if s["niche_id"] == nid and s["status"] in ("SCHEDULED", "COMPLETED")]
        if svc.niche_conflict(w_start, w_end, existing):
            raise err(errors.ERR_NICHE_WINDOW_CONFLICT, "Niche window conflict")

    rec = base_fields()
    rec.update({
        "burial_case_id": case["id"],
        "gravesite_id": case["assigned_gravesite_id"] if is_gravesite else None,
        "niche_id": case["assigned_niche_id"] if not is_gravesite else None,
        "window_start": format_iso8601_ms(w_start),
        "window_end": format_iso8601_ms(w_end),
        "status": "SCHEDULED",
    })
    db.interment_schedules[rec["id"]] = rec

    case["status"] = "SCHEDULED"
    touch(case)
    return object_response(serialize_schedule(rec), 201)


@app.route("/cemeteries/<cemetery_id>/interment-schedules", methods=["GET"])
def list_schedules(cemetery_id):
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin", "EligibilityOfficer", "SchedulingClerk", "HonorsCoordinator"})
    get_cemetery_or_404(cemetery_id)
    case_ids = {c["id"] for c in db.burial_cases.values() if c["cemetery_id"] == cemetery_id}
    items = [s for s in db.interment_schedules.values() if s["burial_case_id"] in case_ids]
    for field in ("burial_case_id", "gravesite_id", "niche_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [s for s in items if s.get(field) == val]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_schedule(s) for s in page], limit, offset, total)


def _get_schedule_scoped(cemetery_id, schedule_id):
    s = db.interment_schedules.get(schedule_id)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "Schedule not found")
    case = db.burial_cases.get(s["burial_case_id"])
    if case is None or case["cemetery_id"] != cemetery_id:
        raise err(errors.ERR_NOT_FOUND, "Schedule not found")
    return s, case


@app.route("/cemeteries/<cemetery_id>/interment-schedules/<schedule_id>", methods=["GET"])
def get_schedule(cemetery_id, schedule_id):
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin", "EligibilityOfficer", "SchedulingClerk", "HonorsCoordinator"})
    get_cemetery_or_404(cemetery_id)
    s, _case = _get_schedule_scoped(cemetery_id, schedule_id)
    return object_response(serialize_schedule(s), 200)


@app.route("/cemeteries/<cemetery_id>/interment-schedules/<schedule_id>/complete", methods=["POST"])
def complete_schedule(cemetery_id, schedule_id):
    _uid, role = require_auth()
    require_roles(role, {"SchedulingClerk"})
    get_cemetery_or_404(cemetery_id)
    s, case = _get_schedule_scoped(cemetery_id, schedule_id)
    if s["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Schedule is not SCHEDULED")

    s["status"] = "COMPLETED"
    touch(s)

    # Increment unit count; RESERVED -> OCCUPIED at capacity
    if s["gravesite_id"]:
        unit = db.gravesites.get(s["gravesite_id"])
        if unit is not None:
            unit["interment_count"] += 1
            if unit["interment_count"] >= unit["depth_capacity"] and unit["status"] == "RESERVED":
                unit["status"] = "OCCUPIED"
            touch(unit)
            section = db.sections.get(unit["section_id"])
            if section is not None:
                svc.recompute_section_inventory(section)
    elif s["niche_id"]:
        unit = db.niches.get(s["niche_id"])
        if unit is not None:
            unit["inurnment_count"] += 1
            if unit["inurnment_count"] >= unit["urn_capacity"] and unit["status"] == "RESERVED":
                unit["status"] = "OCCUPIED"
            touch(unit)
            section = db.sections.get(unit["section_id"])
            if section is not None:
                svc.recompute_section_inventory(section)

    case["status"] = "INTERRED"
    touch(case)

    # CONFIRMED honors -> RENDERED
    for h in db.military_honors.values():
        if h["interment_schedule_id"] == schedule_id and h["status"] == "CONFIRMED":
            h["status"] = "RENDERED"
            touch(h)

    # PRE_NEED: APPROVED PMC -> RESERVED
    if case["case_type"] == "PRE_NEED":
        for p in db.pre_need_determinations.values():
            if p["burial_case_id"] == case["id"] and p["status"] == "APPROVED":
                p["status"] = "RESERVED"
                touch(p)

    return object_response(serialize_schedule(s), 200)


@app.route("/cemeteries/<cemetery_id>/interment-schedules/<schedule_id>/cancel", methods=["POST"])
def cancel_schedule(cemetery_id, schedule_id):
    _uid, role = require_auth()
    require_roles(role, {"SchedulingClerk"})
    get_cemetery_or_404(cemetery_id)
    s, case = _get_schedule_scoped(cemetery_id, schedule_id)
    if s["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Schedule is not SCHEDULED")

    s["status"] = "CANCELLED"
    touch(s)

    case["status"] = "ASSIGNED"
    touch(case)

    # Cascade honors REQUESTED/CONFIRMED -> CANCELLED, reset flag
    for h in db.military_honors.values():
        if h["interment_schedule_id"] == schedule_id and h["status"] in ("REQUESTED", "CONFIRMED"):
            h["status"] = "CANCELLED"
            if h["flag_issued"]:
                h["flag_issued"] = False
            touch(h)

    return object_response(serialize_schedule(s), 200)


# ===========================================================================
# MarkerOrder
# ===========================================================================
def serialize_marker(m):
    return {
        "id": m["id"],
        "burial_case_id": m["burial_case_id"],
        "marker_type": m["marker_type"],
        "inscription_lines": m["inscription_lines"],
        "emblem_of_belief": m["emblem_of_belief"],
        "billable_characters": m["billable_characters"],
        "marker_charge_cents": m["marker_charge_cents"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "_seq": m["_seq"],
    }


@app.route("/cemeteries/<cemetery_id>/marker-orders", methods=["POST"])
def create_marker(cemetery_id):
    _uid, role = require_auth()
    require_roles(role, {"MarkerClerk"})
    get_cemetery_or_404(cemetery_id)
    body = get_json()
    require_fields(body, ["burial_case_id", "marker_type", "inscription_lines"])
    check_enum(body["marker_type"], {"UPRIGHT_MARBLE", "FLAT_GRANITE", "FLAT_BRONZE", "NICHE_COVER"}, "marker_type")
    if not isinstance(body["inscription_lines"], list):
        raise err(errors.ERR_VALIDATION, "inscription_lines must be an array")
    case = db.burial_cases.get(body["burial_case_id"])
    if case is None or case["cemetery_id"] != cemetery_id:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "burial_case_id does not resolve")
    if case["status"] not in ("ASSIGNED", "SCHEDULED", "INTERRED"):
        raise err(errors.ERR_INVALID_STATE, "Case must be at least ASSIGNED")
    rec = base_fields()
    rec.update({
        "burial_case_id": body["burial_case_id"],
        "marker_type": body["marker_type"],
        "inscription_lines": body["inscription_lines"],
        "emblem_of_belief": body.get("emblem_of_belief"),
        "billable_characters": None,
        "marker_charge_cents": None,
        "status": "DRAFT",
    })
    db.marker_orders[rec["id"]] = rec
    return object_response(serialize_marker(rec), 201)


@app.route("/cemeteries/<cemetery_id>/marker-orders", methods=["GET"])
def list_markers(cemetery_id):
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin", "MarkerClerk", "SchedulingClerk"})
    get_cemetery_or_404(cemetery_id)
    case_ids = {c["id"] for c in db.burial_cases.values() if c["cemetery_id"] == cemetery_id}
    items = [m for m in db.marker_orders.values() if m["burial_case_id"] in case_ids]
    for field in ("burial_case_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [m for m in items if m.get(field) == val]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_marker(m) for m in page], limit, offset, total)


def _get_marker_scoped(cemetery_id, marker_id):
    m = db.marker_orders.get(marker_id)
    if m is None:
        raise err(errors.ERR_NOT_FOUND, "Marker order not found")
    case = db.burial_cases.get(m["burial_case_id"])
    if case is None or case["cemetery_id"] != cemetery_id:
        raise err(errors.ERR_NOT_FOUND, "Marker order not found")
    return m, case


@app.route("/cemeteries/<cemetery_id>/marker-orders/<marker_id>", methods=["GET"])
def get_marker(cemetery_id, marker_id):
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin", "MarkerClerk", "SchedulingClerk"})
    get_cemetery_or_404(cemetery_id)
    m, _case = _get_marker_scoped(cemetery_id, marker_id)
    return object_response(serialize_marker(m), 200)


@app.route("/cemeteries/<cemetery_id>/marker-orders/<marker_id>/submit", methods=["POST"])
def submit_marker(cemetery_id, marker_id):
    _uid, role = require_auth()
    require_roles(role, {"MarkerClerk"})
    get_cemetery_or_404(cemetery_id)
    m, case = _get_marker_scoped(cemetery_id, marker_id)
    if m["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "Marker order is not DRAFT")

    lines = m["inscription_lines"]
    # Inscription limits (ERR_INSCRIPTION_LIMIT_EXCEEDED) — checked before kind mismatch per §2.6 order
    if len(lines) > svc.INSCRIPTION_MAX_LINES or any(len(l) > svc.INSCRIPTION_MAX_CHARS_PER_LINE for l in lines):
        raise err(errors.ERR_INSCRIPTION_LIMIT_EXCEEDED, "Inscription exceeds limits")

    # marker_type NICHE_COVER iff assigned_unit_type == NICHE
    is_niche = case.get("assigned_unit_type") == "NICHE"
    if (m["marker_type"] == "NICHE_COVER") != is_niche:
        raise err(errors.ERR_UNIT_KIND_MISMATCH, "marker_type does not match unit kind")

    billable, charge = svc.marker_charge(lines, m["emblem_of_belief"])
    m["billable_characters"] = billable
    m["marker_charge_cents"] = charge
    m["status"] = "SUBMITTED"
    touch(m)
    return object_response(serialize_marker(m), 200)


@app.route("/cemeteries/<cemetery_id>/marker-orders/<marker_id>/engrave", methods=["POST"])
def engrave_marker(cemetery_id, marker_id):
    _uid, role = require_auth()
    require_roles(role, {"MarkerClerk"})
    get_cemetery_or_404(cemetery_id)
    m, case = _get_marker_scoped(cemetery_id, marker_id)
    if m["status"] != "SUBMITTED":
        raise err(errors.ERR_INVALID_STATE, "Marker order is not SUBMITTED")
    if case["status"] != "INTERRED":
        raise err(errors.ERR_INVALID_STATE, "Linked case is not INTERRED")
    m["status"] = "ENGRAVED"
    touch(m)
    return object_response(serialize_marker(m), 200)


@app.route("/cemeteries/<cemetery_id>/marker-orders/<marker_id>/cancel", methods=["POST"])
def cancel_marker(cemetery_id, marker_id):
    _uid, role = require_auth()
    require_roles(role, {"MarkerClerk"})
    get_cemetery_or_404(cemetery_id)
    m, _case = _get_marker_scoped(cemetery_id, marker_id)
    if m["status"] not in ("DRAFT", "SUBMITTED"):
        raise err(errors.ERR_INVALID_STATE, "Marker order cannot be cancelled")
    m["status"] = "CANCELLED"
    touch(m)
    return object_response(serialize_marker(m), 200)


# ===========================================================================
# MilitaryHonors
# ===========================================================================
def serialize_honors(h):
    return {
        "id": h["id"],
        "interment_schedule_id": h["interment_schedule_id"],
        "detail_size": h["detail_size"],
        "flag_issued": h["flag_issued"],
        "honors_date": h["honors_date"],
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
        "_seq": h["_seq"],
    }


def _honors_date(window_start_iso):
    dt = parse_iso8601(window_start_iso)
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return format_iso8601_ms(midnight)


@app.route("/cemeteries/<cemetery_id>/military-honors", methods=["POST"])
def create_honors(cemetery_id):
    _uid, role = require_auth()
    require_roles(role, {"HonorsCoordinator"})
    get_cemetery_or_404(cemetery_id)
    body = get_json()
    require_fields(body, ["interment_schedule_id", "detail_size"])
    check_enum(body["detail_size"], {"TWO_PERSON", "FULL_SQUAD"}, "detail_size")
    schedule = db.interment_schedules.get(body["interment_schedule_id"])
    if schedule is None:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "interment_schedule_id does not resolve")
    case = db.burial_cases.get(schedule["burial_case_id"])
    if case is None or case["cemetery_id"] != cemetery_id:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "interment_schedule_id does not resolve")
    if schedule["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Schedule is not SCHEDULED")
    rec = base_fields()
    rec.update({
        "interment_schedule_id": body["interment_schedule_id"],
        "detail_size": body["detail_size"],
        "flag_issued": False,
        "honors_date": _honors_date(schedule["window_start"]),
        "status": "REQUESTED",
    })
    db.military_honors[rec["id"]] = rec
    return object_response(serialize_honors(rec), 201)


@app.route("/cemeteries/<cemetery_id>/military-honors", methods=["GET"])
def list_honors(cemetery_id):
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin", "HonorsCoordinator", "SchedulingClerk"})
    get_cemetery_or_404(cemetery_id)
    # Scope: honors whose schedule's case belongs to this cemetery
    case_ids = {c["id"] for c in db.burial_cases.values() if c["cemetery_id"] == cemetery_id}
    sched_ids = {s["id"] for s in db.interment_schedules.values() if s["burial_case_id"] in case_ids}
    items = [h for h in db.military_honors.values() if h["interment_schedule_id"] in sched_ids]
    for field in ("interment_schedule_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [h for h in items if h.get(field) == val]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_honors(h) for h in page], limit, offset, total)


def _get_honors_scoped(cemetery_id, honors_id):
    h = db.military_honors.get(honors_id)
    if h is None:
        raise err(errors.ERR_NOT_FOUND, "Honors not found")
    schedule = db.interment_schedules.get(h["interment_schedule_id"])
    if schedule is None:
        raise err(errors.ERR_NOT_FOUND, "Honors not found")
    case = db.burial_cases.get(schedule["burial_case_id"])
    if case is None or case["cemetery_id"] != cemetery_id:
        raise err(errors.ERR_NOT_FOUND, "Honors not found")
    return h, schedule, case


@app.route("/cemeteries/<cemetery_id>/military-honors/<honors_id>", methods=["GET"])
def get_honors(cemetery_id, honors_id):
    _uid, role = require_auth()
    require_roles(role, {"NCA_Admin", "HonorsCoordinator", "SchedulingClerk"})
    get_cemetery_or_404(cemetery_id)
    h, _s, _c = _get_honors_scoped(cemetery_id, honors_id)
    return object_response(serialize_honors(h), 200)


@app.route("/cemeteries/<cemetery_id>/military-honors/<honors_id>/confirm", methods=["POST"])
def confirm_honors(cemetery_id, honors_id):
    _uid, role = require_auth()
    require_roles(role, {"HonorsCoordinator"})
    cemetery = get_cemetery_or_404(cemetery_id)
    h, schedule, case = _get_honors_scoped(cemetery_id, honors_id)
    if h["status"] != "REQUESTED":
        raise err(errors.ERR_INVALID_STATE, "Honors is not REQUESTED")
    # Linked schedule must still be SCHEDULED
    if schedule["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Linked schedule is not SCHEDULED")

    # FULL_SQUAD entitlement (priority 10) before capacity (priority 12)
    if h["detail_size"] == "FULL_SQUAD":
        if (case.get("entitlement_score") or 0) < svc.HONORS_FULL_SQUAD_MIN_SCORE:
            raise err(errors.ERR_HONORS_ENTITLEMENT_INSUFFICIENT, "entitlement_score too low for FULL_SQUAD")

    # Daily capacity within the same cemetery on the same honors_date
    honors_date = h["honors_date"]
    confirmed_today = 0
    for other in db.military_honors.values():
        if other["status"] != "CONFIRMED":
            continue
        if other["honors_date"] != honors_date:
            continue
        o_sched = db.interment_schedules.get(other["interment_schedule_id"])
        if o_sched is None:
            continue
        o_case = db.burial_cases.get(o_sched["burial_case_id"])
        if o_case is None or o_case["cemetery_id"] != cemetery_id:
            continue
        confirmed_today += 1
    if confirmed_today >= cemetery["honors_squad_capacity"]:
        raise err(errors.ERR_HONORS_CAPACITY_FULL, "Daily honors capacity is full")

    h["status"] = "CONFIRMED"
    h["flag_issued"] = True
    touch(h)
    return object_response(serialize_honors(h), 200)


@app.route("/cemeteries/<cemetery_id>/military-honors/<honors_id>/cancel", methods=["POST"])
def cancel_honors(cemetery_id, honors_id):
    _uid, role = require_auth()
    require_roles(role, {"HonorsCoordinator"})
    get_cemetery_or_404(cemetery_id)
    h, _s, _c = _get_honors_scoped(cemetery_id, honors_id)
    if h["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err(errors.ERR_INVALID_STATE, "Honors cannot be cancelled")
    h["status"] = "CANCELLED"
    if h["flag_issued"]:
        h["flag_issued"] = False
    touch(h)
    return object_response(serialize_honors(h), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
