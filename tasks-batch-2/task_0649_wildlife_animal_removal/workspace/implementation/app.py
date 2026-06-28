"""Wildlife & Nuisance-Animal Removal API — Flask entry point.

Single in-memory store, wiped on every boot. No entity seeding at startup.
"""
import os

from flask import Flask, request

import db
import calculations as calc
import services as svc
from clock import clock, parse_iso
from errors import ApiError, err
from middleware import (
    auth,
    require_role,
    pagination,
    paginate,
    body,
    require_str,
    opt_str,
    require_int,
    opt_int,
    require_number,
    opt_number,
    require_bool,
    require_enum,
)
from response import object_response, array_response, error_response
from serialize import public

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(400)
def handle_400(e):
    return error_response("ERR_INVALID_REQUEST", "Malformed request.", 422)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 422)


# ---------------------------------------------------------------------------
# List helper: sort by created_at asc (tiebreak by insertion seq), paginate.
# ---------------------------------------------------------------------------
def list_response(records):
    limit, offset = pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = paginate(ordered, limit, offset)
    return array_response([public(r) for r in window], limit, offset, total)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    _uid, role = auth()
    require_role(role, {"Dispatcher", "ComplianceOfficer"})
    data = body()
    to_iso = require_str(data, "to_iso8601")
    try:
        clock.set_iso(to_iso)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 datetime.")
    return object_response({}, 200)


# ===========================================================================
# SpeciesProfile
# ===========================================================================
@app.route("/species-profiles", methods=["POST"])
def create_species_profile():
    _uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    data = body()
    common_name = require_str(data, "common_name")
    code = require_str(data, "code")
    is_regulated = require_bool(data, "is_regulated", default=False)
    relocation_min = opt_number(data, "relocation_min_miles", 0, minimum=0)
    relocation_max = opt_number(data, "relocation_max_miles", 25)
    # constraints: min >= 0 and min <= max; max >= min
    if relocation_max < relocation_min:
        raise err("ERR_INVALID_REQUEST", "relocation_max_miles must be >= relocation_min_miles.")
    humane = opt_int(data, "humane_check_interval_hours", 24, minimum=1)
    base_trap_fee = require_int(data, "base_trap_fee_cents", minimum=0)
    risk_weight = opt_number(data, "risk_weight", 1.0, minimum=0)

    # code unique across all species profiles (case-sensitive exact match)
    for sp in db.values("species_profiles"):
        if sp["code"] == code:
            raise err("ERR_INVALID_REQUEST", "code must be unique across species profiles.")

    rec = db.new_record({
        "common_name": common_name,
        "code": code,
        "is_regulated": is_regulated,
        "relocation_min_miles": relocation_min,
        "relocation_max_miles": relocation_max,
        "humane_check_interval_hours": humane,
        "base_trap_fee_cents": base_trap_fee,
        "risk_weight": risk_weight,
    })
    db.insert("species_profiles", rec)
    return object_response(public(rec), 201)


@app.route("/species-profiles/<rec_id>", methods=["GET"])
def get_species_profile(rec_id):
    _uid, role = auth()
    require_role(role, {"ComplianceOfficer", "Dispatcher", "FieldTechnician", "PropertyOwner"})
    rec = svc.must_get("species_profiles", rec_id)
    return object_response(public(rec), 200)


@app.route("/species-profiles", methods=["GET"])
def list_species_profiles():
    _uid, role = auth()
    require_role(role, {"ComplianceOfficer", "Dispatcher", "FieldTechnician", "PropertyOwner"})
    return list_response(db.values("species_profiles"))


# ===========================================================================
# Technician
# ===========================================================================
@app.route("/technicians", methods=["POST"])
def create_technician():
    _uid, role = auth()
    require_role(role, {"Dispatcher"})
    data = body()
    full_name = require_str(data, "full_name")
    license_tier = require_enum(data, "license_tier", {"BASIC", "CERTIFIED"}, default="BASIC")
    kit_cap = require_int(data, "kit_trap_capacity", minimum=0)
    rec = db.new_record({
        "full_name": full_name,
        "license_tier": license_tier,
        "kit_trap_capacity": kit_cap,
        "traps_deployed": 0,
        "traps_available": kit_cap,
    })
    db.insert("technicians", rec)
    return object_response(public(rec), 201)


@app.route("/technicians/<rec_id>", methods=["GET"])
def get_technician(rec_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher", "FieldTechnician", "ComplianceOfficer"})
    rec = svc.must_get("technicians", rec_id)
    return object_response(public(rec), 200)


@app.route("/technicians", methods=["GET"])
def list_technicians():
    _uid, role = auth()
    require_role(role, {"Dispatcher", "FieldTechnician", "ComplianceOfficer"})
    return list_response(db.values("technicians"))


# ===========================================================================
# ServiceAccount
# ===========================================================================
@app.route("/service-accounts", methods=["POST"])
def create_service_account():
    _uid, role = auth()
    require_role(role, {"Dispatcher"})
    data = body()
    account_name = require_str(data, "account_name")
    contact_email = require_str(data, "contact_email")
    rec = db.new_record({
        "account_name": account_name,
        "contact_email": contact_email,
    })
    db.insert("service_accounts", rec)
    return object_response(public(rec), 201)


@app.route("/service-accounts/<rec_id>", methods=["GET"])
def get_service_account(rec_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher", "PropertyOwner", "ComplianceOfficer"})
    rec = svc.must_get("service_accounts", rec_id)
    return object_response(public(rec), 200)


# ===========================================================================
# Property
# ===========================================================================
@app.route("/properties", methods=["POST"])
def create_property():
    _uid, role = auth()
    require_role(role, {"Dispatcher"})
    data = body()
    account_id = require_str(data, "account_id")
    latitude = require_number(data, "latitude", minimum=-90, maximum=90)
    longitude = require_number(data, "longitude", minimum=-180, maximum=180)
    svc.must_get("service_accounts", account_id)
    rec = db.new_record({
        "account_id": account_id,
        "latitude": latitude,
        "longitude": longitude,
        "posture": "OPEN",
    })
    db.insert("properties", rec)
    return object_response(public(rec), 201)


@app.route("/properties/<rec_id>", methods=["GET"])
def get_property(rec_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher", "PropertyOwner", "ComplianceOfficer", "FieldTechnician"})
    rec = svc.must_get("properties", rec_id)
    return object_response(public(rec), 200)


@app.route("/properties", methods=["GET"])
def list_properties():
    _uid, role = auth()
    require_role(role, {"Dispatcher", "PropertyOwner", "ComplianceOfficer"})
    account_id = request.args.get("account_id")
    items = db.values("properties")
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    return list_response(items)


# ===========================================================================
# Inspection
# ===========================================================================
@app.route("/properties/<prop_id>/inspections", methods=["POST"])
def create_inspection(prop_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher"})
    svc.must_get("properties", prop_id)
    data = body()
    scheduled_for = require_str(data, "scheduled_for")
    _validate_datetime(scheduled_for)
    is_emergency = require_bool(data, "is_emergency", default=False)
    rec = db.new_record({
        "property_id": prop_id,
        "scheduled_for": scheduled_for,
        "is_emergency": is_emergency,
        "status": "DRAFT",
        "detected_individual_count": 0,
    })
    db.insert("inspections", rec)
    return object_response(public(rec), 201)


@app.route("/properties/<prop_id>/inspections", methods=["GET"])
def list_property_inspections(prop_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher", "PropertyOwner", "ComplianceOfficer", "FieldTechnician"})
    svc.must_get("properties", prop_id)
    items = [i for i in db.values("inspections") if i["property_id"] == prop_id]
    return list_response(items)


@app.route("/inspections/<rec_id>", methods=["GET"])
def get_inspection(rec_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher", "PropertyOwner", "ComplianceOfficer", "FieldTechnician"})
    rec = svc.must_get("inspections", rec_id)
    return object_response(public(rec), 200)


@app.route("/properties/<prop_id>/inspections/<inspection_id>/complete", methods=["POST"])
def complete_inspection(prop_id, inspection_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher"})
    prop = svc.must_get("properties", prop_id)
    insp = svc.must_get("inspections", inspection_id)
    # state: must be DRAFT
    if insp["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Inspection is not DRAFT.")
    # precondition: at least one entry point
    if not svc.entry_points_of_inspection(inspection_id):
        raise err("ERR_INVALID_STATE", "Inspection has no entry points.")
    # precondition: property not in REGULATORY_HOLD
    if prop["posture"] == "REGULATORY_HOLD":
        raise err("ERR_INVALID_STATE", "Property is in REGULATORY_HOLD.")
    insp["status"] = "COMPLETED"
    db.touch(insp)
    svc.refresh_detected_individual_count(insp)
    return object_response(public(insp), 200)


@app.route("/properties/<prop_id>/inspections/<inspection_id>/cancel", methods=["POST"])
def cancel_inspection(prop_id, inspection_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher"})
    svc.must_get("properties", prop_id)
    insp = svc.must_get("inspections", inspection_id)
    if insp["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Inspection is not DRAFT.")
    insp["status"] = "CANCELLED"
    db.touch(insp)
    return object_response(public(insp), 200)


# ===========================================================================
# EntryPoint
# ===========================================================================
@app.route("/inspections/<inspection_id>/entry-points", methods=["POST"])
def create_entry_point(inspection_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher", "FieldTechnician"})
    insp = svc.must_get("inspections", inspection_id)
    data = body()
    species_id = require_str(data, "species_id")
    location_label = require_str(data, "location_label")
    severity = require_enum(data, "severity", {"MINOR", "MODERATE", "MAJOR"}, default="MODERATE")
    estimated = require_int(data, "estimated_individuals", minimum=0)
    svc.species_by_id(species_id)
    rec = db.new_record({
        "inspection_id": inspection_id,
        "species_id": species_id,
        "location_label": location_label,
        "severity": severity,
        "estimated_individuals": estimated,
        "seal_status": "OPEN",
    })
    db.insert("entry_points", rec)
    svc.refresh_detected_individual_count(insp)
    return object_response(public(rec), 201)


@app.route("/inspections/<inspection_id>/entry-points", methods=["GET"])
def list_inspection_entry_points(inspection_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher", "PropertyOwner", "ComplianceOfficer", "FieldTechnician"})
    svc.must_get("inspections", inspection_id)
    items = [ep for ep in db.values("entry_points") if ep["inspection_id"] == inspection_id]
    return list_response(items)


@app.route("/entry-points/<rec_id>", methods=["GET"])
def get_entry_point(rec_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher", "PropertyOwner", "ComplianceOfficer", "FieldTechnician"})
    rec = svc.must_get("entry_points", rec_id)
    return object_response(public(rec), 200)


@app.route("/entry-points", methods=["GET"])
def list_entry_points():
    _uid, role = auth()
    require_role(role, {"Dispatcher", "ComplianceOfficer", "FieldTechnician"})
    species_id = request.args.get("species_id")
    items = db.values("entry_points")
    if species_id is not None:
        items = [ep for ep in items if ep["species_id"] == species_id]
    return list_response(items)


# ===========================================================================
# Quote
# ===========================================================================
@app.route("/quotes", methods=["POST"])
def create_quote():
    _uid, role = auth()
    require_role(role, {"Dispatcher"})
    data = body()
    inspection_id = require_str(data, "inspection_id")
    expected_version = require_int(data, "expected_inspection_version")
    insp = svc.must_get("inspections", inspection_id)
    # state: inspection must be COMPLETED
    if insp["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "Quote can only be created from a COMPLETED inspection.")
    # OCC on inspection.version
    if expected_version != insp["version"]:
        raise err("ERR_STALE_VERSION", "expected_inspection_version does not match.")
    # supersede prior non-terminal quotes on this inspection
    for q in db.values("quotes"):
        if q["inspection_id"] == inspection_id and q["status"] in ("DRAFT", "SENT", "REVISION_REQUESTED"):
            q["status"] = "SUPERSEDED"
            db.touch(q)
    rec = db.new_record({
        "inspection_id": inspection_id,
        "status": "DRAFT",
        "provisional_total_cents": 0,
        "final_total_cents": 0,
        "emergency_flag": insp["is_emergency"],
    })
    db.insert("quotes", rec)
    # increment inspection version by one
    db.touch(insp)
    return object_response(public(rec), 201)


@app.route("/quotes/<rec_id>", methods=["GET"])
def get_quote(rec_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher", "PropertyOwner", "ComplianceOfficer"})
    rec = svc.must_get("quotes", rec_id)
    return object_response(public(rec), 200)


@app.route("/quotes", methods=["GET"])
def list_quotes():
    _uid, role = auth()
    require_role(role, {"Dispatcher", "PropertyOwner", "ComplianceOfficer"})
    inspection_id = request.args.get("inspection_id")
    items = db.values("quotes")
    if inspection_id is not None:
        items = [q for q in items if q["inspection_id"] == inspection_id]
    return list_response(items)


@app.route("/quotes/<quote_id>/line-items", methods=["POST"])
def create_line_item(quote_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher"})
    quote = svc.must_get("quotes", quote_id)
    if quote["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Line items may only be added to a DRAFT quote.")
    data = body()
    species_id = require_str(data, "species_id")
    line_type = require_enum(data, "line_type", {"TRAP", "EXCLUSION"})
    quantity = require_int(data, "quantity", minimum=1)
    unit_price = require_int(data, "unit_price_cents", minimum=0)
    svc.species_by_id(species_id)
    rec = db.new_record({
        "quote_id": quote_id,
        "species_id": species_id,
        "line_type": line_type,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "performed": False,
    })
    db.insert("quote_line_items", rec)
    return object_response(public(rec), 201)


@app.route("/quotes/<quote_id>/line-items", methods=["GET"])
def list_quote_line_items(quote_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher", "PropertyOwner", "ComplianceOfficer"})
    svc.must_get("quotes", quote_id)
    items = [li for li in db.values("quote_line_items") if li["quote_id"] == quote_id]
    return list_response(items)


@app.route("/line-items/<rec_id>", methods=["GET"])
def get_line_item(rec_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher", "ComplianceOfficer", "PropertyOwner"})
    rec = svc.must_get("quote_line_items", rec_id)
    return object_response(public(rec), 200)


@app.route("/line-items", methods=["GET"])
def list_line_items():
    _uid, role = auth()
    require_role(role, {"Dispatcher", "ComplianceOfficer"})
    species_id = request.args.get("species_id")
    items = db.values("quote_line_items")
    if species_id is not None:
        items = [li for li in items if li["species_id"] == species_id]
    return list_response(items)


@app.route("/quotes/<quote_id>/send", methods=["POST"])
def send_quote(quote_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher"})
    quote = svc.must_get("quotes", quote_id)
    if quote["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Quote is not DRAFT.")
    line_items = svc.line_items_of_quote(quote_id)
    if not line_items:
        raise err("ERR_EMPTY_SET", "Cannot send a quote with zero line items.")
    quote["status"] = "SENT"
    quote["provisional_total_cents"] = calc.quote_provisional_total(line_items, quote["emergency_flag"])
    db.touch(quote)
    return object_response(public(quote), 200)


@app.route("/quotes/<quote_id>/request-revision", methods=["POST"])
def request_revision(quote_id):
    _uid, role = auth()
    require_role(role, {"PropertyOwner"})
    quote = svc.must_get("quotes", quote_id)
    _require_owner_of_quote(quote, _uid)
    if quote["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Quote is not SENT.")
    quote["status"] = "REVISION_REQUESTED"
    db.touch(quote)
    return object_response(public(quote), 200)


@app.route("/quotes/<quote_id>/reopen", methods=["POST"])
def reopen_quote(quote_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher"})
    quote = svc.must_get("quotes", quote_id)
    if quote["status"] != "REVISION_REQUESTED":
        raise err("ERR_INVALID_STATE", "Quote is not REVISION_REQUESTED.")
    quote["status"] = "DRAFT"
    db.touch(quote)
    return object_response(public(quote), 200)


@app.route("/quotes/<quote_id>/accept", methods=["POST"])
def accept_quote(quote_id):
    _uid, role = auth()
    require_role(role, {"PropertyOwner"})
    quote = svc.must_get("quotes", quote_id)
    _require_owner_of_quote(quote, _uid)
    if quote["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Quote is not SENT.")
    data = body()
    assigned_tech_id = require_str(data, "assigned_technician_id")
    tech = svc.must_get("technicians", assigned_tech_id)
    insp = db.get("inspections", quote["inspection_id"])
    prop = db.get("properties", insp["property_id"])

    # quote -> ACCEPTED
    quote["status"] = "ACCEPTED"
    db.touch(quote)

    # CASCADE L1: create WorkOrder
    wo = db.new_record({
        "quote_id": quote_id,
        "property_id": prop["id"],
        "assigned_technician_id": assigned_tech_id,
        "lifecycle": "OPEN",
        "removal_status": "PENDING",
        "exclusion_status": "PENDING",
        "net_charged_cents": quote["provisional_total_cents"],
        "initial_risk_score": svc.compute_initial_risk(insp["id"]),
        "residual_risk_score": 0,
    })
    db.insert("work_orders", wo)

    # CASCADE L3: a Permit per distinct regulated species among inspection's entry points
    regulated_species = []
    for ep in svc.entry_points_of_inspection(insp["id"]):
        sp = svc.species_by_id(ep["species_id"])
        if sp.get("is_regulated") and ep["species_id"] not in regulated_species:
            regulated_species.append(ep["species_id"])
    any_permit = False
    for sid in regulated_species:
        permit = db.new_record({
            "work_order_id": wo["id"],
            "species_id": sid,
            "status": "REQUESTED",
            "permit_number": None,
        })
        db.insert("permits", permit)
        any_permit = True

    # CASCADE L4: posture
    if any_permit:
        svc.set_posture(prop, "REGULATORY_HOLD")
    else:
        svc.set_posture(prop, "ACTIVE_REMEDIATION")

    return object_response(public(wo), 200)


@app.route("/quotes/<quote_id>/decline", methods=["POST"])
def decline_quote(quote_id):
    _uid, role = auth()
    require_role(role, {"PropertyOwner"})
    quote = svc.must_get("quotes", quote_id)
    _require_owner_of_quote(quote, _uid)
    if quote["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Quote is not SENT.")
    quote["status"] = "DECLINED"
    db.touch(quote)
    return object_response(public(quote), 200)


def _require_owner_of_quote(quote, user_id):
    """PropertyOwner must own the ServiceAccount of the Property of the quote's
    parent inspection (PRD §2.1 / §3.3)."""
    insp = db.get("inspections", quote["inspection_id"])
    if insp is None:
        return
    prop = db.get("properties", insp["property_id"])
    if prop is None:
        return
    if prop["account_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "PropertyOwner does not own this resource.")


# ===========================================================================
# WorkOrder
# ===========================================================================
@app.route("/work-orders/<rec_id>", methods=["GET"])
def get_work_order(rec_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher", "PropertyOwner", "ComplianceOfficer", "FieldTechnician"})
    rec = svc.must_get("work_orders", rec_id)
    return object_response(public(rec), 200)


@app.route("/work-orders", methods=["GET"])
def list_work_orders():
    _uid, role = auth()
    require_role(role, {"Dispatcher", "ComplianceOfficer", "FieldTechnician", "PropertyOwner"})
    quote_id = request.args.get("quote_id")
    property_id = request.args.get("property_id")
    tech_id = request.args.get("assigned_technician_id")
    items = db.values("work_orders")
    if quote_id is not None:
        items = [w for w in items if w["quote_id"] == quote_id]
    if property_id is not None:
        items = [w for w in items if w["property_id"] == property_id]
    if tech_id is not None:
        items = [w for w in items if w["assigned_technician_id"] == tech_id]
    return list_response(items)


@app.route("/work-orders/<wo_id>/cancel", methods=["POST"])
def cancel_work_order(wo_id):
    _uid, role = auth()
    require_role(role, {"Dispatcher"})
    wo = svc.must_get("work_orders", wo_id)
    data = body()
    expected_version = require_int(data, "expected_work_order_version")
    # state: lifecycle OPEN
    if wo["lifecycle"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Work order is not OPEN.")
    # OCC
    if expected_version != wo["version"]:
        raise err("ERR_STALE_VERSION", "expected_work_order_version does not match.")

    quote = db.get("quotes", wo["quote_id"])
    line_items = svc.line_items_of_quote(quote["id"])
    completed_sanitation = sum(
        1 for er in svc.exclusion_repairs_of_wo(wo["id"])
        if er["status"] == "COMPLETED" and er.get("sanitation_included")
    )
    subtotal = calc.performed_subtotal(line_items, completed_sanitation, quote["emergency_flag"])

    # lifecycle -> CANCELLED; net settles to performed subtotal
    wo["lifecycle"] = "CANCELLED"
    wo["net_charged_cents"] = subtotal
    # cancel SET traps + restore kit
    svc.cancel_set_traps_and_restore(wo)
    # posture -> OPEN
    prop = db.get("properties", wo["property_id"])
    if prop:
        svc.set_posture(prop, "OPEN")
    # increments WorkOrder.version by 1 (db.touch bumps version once)
    db.touch(wo)
    return object_response(public(wo), 200)


# ===========================================================================
# Permit
# ===========================================================================
@app.route("/work-orders/<wo_id>/permits", methods=["GET"])
def list_wo_permits(wo_id):
    _uid, role = auth()
    require_role(role, {"ComplianceOfficer", "Dispatcher", "FieldTechnician"})
    svc.must_get("work_orders", wo_id)
    items = [p for p in db.values("permits") if p["work_order_id"] == wo_id]
    return list_response(items)


@app.route("/permits/<rec_id>", methods=["GET"])
def get_permit(rec_id):
    _uid, role = auth()
    require_role(role, {"ComplianceOfficer", "Dispatcher", "FieldTechnician"})
    rec = svc.must_get("permits", rec_id)
    return object_response(public(rec), 200)


@app.route("/permits", methods=["GET"])
def list_permits():
    _uid, role = auth()
    require_role(role, {"ComplianceOfficer", "Dispatcher"})
    species_id = request.args.get("species_id")
    items = db.values("permits")
    if species_id is not None:
        items = [p for p in items if p["species_id"] == species_id]
    return list_response(items)


@app.route("/permits/<permit_id>/approve", methods=["POST"])
def approve_permit(permit_id):
    _uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    permit = svc.must_get("permits", permit_id)
    if permit["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Permit is not REQUESTED.")
    data = body()
    permit_number = require_str(data, "permit_number")
    permit["status"] = "APPROVED"
    permit["permit_number"] = permit_number
    db.touch(permit)
    # BUBBLE: if all permits on the WO are APPROVED, posture -> ACTIVE_REMEDIATION
    wo = db.get("work_orders", permit["work_order_id"])
    all_permits = svc.permits_of_wo(wo["id"])
    if all(p["status"] == "APPROVED" for p in all_permits):
        prop = db.get("properties", wo["property_id"])
        if prop:
            svc.set_posture(prop, "ACTIVE_REMEDIATION")
    return object_response(public(permit), 200)


@app.route("/permits/<permit_id>/deny", methods=["POST"])
def deny_permit(permit_id):
    _uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    permit = svc.must_get("permits", permit_id)
    if permit["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Permit is not REQUESTED.")
    permit["status"] = "DENIED"
    db.touch(permit)
    # CASCADE: WorkOrder -> CANCELLED; posture -> OPEN; SET traps -> CANCELLED + restore kit
    wo = db.get("work_orders", permit["work_order_id"])
    if wo and wo["lifecycle"] == "OPEN":
        wo["lifecycle"] = "CANCELLED"
        db.touch(wo)
        svc.cancel_set_traps_and_restore(wo)
        prop = db.get("properties", wo["property_id"])
        if prop:
            svc.set_posture(prop, "OPEN")
    return object_response(public(permit), 200)


# ===========================================================================
# TrapPlacement
# ===========================================================================
@app.route("/work-orders/<wo_id>/trap-placements", methods=["POST"])
def create_trap_placement(wo_id):
    _uid, role = auth()
    require_role(role, {"FieldTechnician"})
    wo = svc.must_get("work_orders", wo_id)
    data = body()
    species_id = require_str(data, "species_id")
    technician_id = require_str(data, "technician_id")
    window_start = require_str(data, "window_start")
    window_end = require_str(data, "window_end")
    # existence of body FKs (priority 3)
    sp = svc.species_by_id(species_id)
    tech = svc.must_get("technicians", technician_id)
    # Parse windows; defer any format error to the ERR_INVALID_REQUEST stage
    # (priority 15) so higher-priority gates fire first.
    ws = _try_parse_dt(window_start)
    we = _try_parse_dt(window_end)

    # state: work order OPEN (priority 4)
    if wo["lifecycle"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Work order is not OPEN.")

    # priority 6: permit gate (regulated species needs APPROVED permit)
    if sp.get("is_regulated"):
        approved = any(
            p["species_id"] == species_id and p["status"] == "APPROVED"
            for p in svc.permits_of_wo(wo_id)
        )
        if not approved:
            raise err("ERR_PERMIT_REQUIRED", "Regulated species requires an APPROVED permit.")
        # priority 7: certification gate
        if tech["license_tier"] != "CERTIFIED":
            raise err("ERR_TECH_NOT_CERTIFIED", "Regulated species requires a CERTIFIED technician.")

    # priority 10: technician window conflict (buffered closed-interval)
    if ws is not None and we is not None:
        for tp in db.values("trap_placements"):
            if tp["technician_id"] == technician_id and tp["status"] == "SET":
                o_ws = parse_iso(tp["window_start"])
                o_we = parse_iso(tp["window_end"])
                if svc.trap_windows_overlap(ws, we, o_ws, o_we, calc.TRAP_VISIT_BUFFER_MINUTES):
                    raise err("ERR_TECH_WINDOW_CONFLICT", "Trap window overlaps another SET trap on this technician.")

    # priority 12: window well-formedness
    if ws is not None and we is not None and not (we > ws):
        raise err("ERR_INVALID_WINDOW", "window_end must be strictly after window_start.")

    # priority 14: kit capacity
    if tech["traps_available"] - 1 < 0:
        raise err("ERR_KIT_EXHAUSTED", "Technician kit exhausted.")

    # priority 15: deferred datetime-format validation
    if ws is None or we is None:
        raise err("ERR_INVALID_REQUEST", "window_start/window_end must be valid ISO 8601 datetimes.")

    rec = db.new_record({
        "work_order_id": wo_id,
        "species_id": species_id,
        "technician_id": technician_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SET",
    })
    db.insert("trap_placements", rec)
    # first SET advances removal PENDING -> TRAPPING
    if wo["removal_status"] == "PENDING":
        wo["removal_status"] = "TRAPPING"
    # PRD §2.6: setting a trap mutates the work order and bumps its version.
    db.touch(wo)
    svc.kit_deploy(tech)
    return object_response(public(rec), 201)


@app.route("/work-orders/<wo_id>/trap-placements", methods=["GET"])
def list_wo_trap_placements(wo_id):
    _uid, role = auth()
    require_role(role, {"FieldTechnician", "Dispatcher", "ComplianceOfficer"})
    svc.must_get("work_orders", wo_id)
    items = [tp for tp in db.values("trap_placements") if tp["work_order_id"] == wo_id]
    return list_response(items)


@app.route("/trap-placements/<rec_id>", methods=["GET"])
def get_trap_placement(rec_id):
    _uid, role = auth()
    require_role(role, {"FieldTechnician", "Dispatcher", "ComplianceOfficer"})
    rec = svc.must_get("trap_placements", rec_id)
    return object_response(public(rec), 200)


@app.route("/trap-placements", methods=["GET"])
def list_trap_placements():
    _uid, role = auth()
    require_role(role, {"FieldTechnician", "Dispatcher", "ComplianceOfficer"})
    species_id = request.args.get("species_id")
    technician_id = request.args.get("technician_id")
    items = db.values("trap_placements")
    if species_id is not None:
        items = [tp for tp in items if tp["species_id"] == species_id]
    if technician_id is not None:
        items = [tp for tp in items if tp["technician_id"] == technician_id]
    return list_response(items)


@app.route("/trap-placements/<tp_id>/captures", methods=["POST"])
def create_capture(tp_id):
    _uid, role = auth()
    require_role(role, {"FieldTechnician"})
    tp = svc.must_get("trap_placements", tp_id)
    data = body()
    captured_at = require_str(data, "captured_at")
    release_lat = require_number(data, "release_latitude", minimum=-90, maximum=90)
    release_lon = require_number(data, "release_longitude", minimum=-180, maximum=180)
    _validate_datetime(captured_at)

    wo = db.get("work_orders", tp["work_order_id"])
    # state: trap SET and work order OPEN
    if tp["status"] != "SET":
        raise err("ERR_INVALID_STATE", "Trap is not SET.")
    if wo["lifecycle"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Work order is not OPEN.")

    # relocation distance band (priority 8)
    prop = db.get("properties", wo["property_id"])
    distance = calc.relocation_distance_miles(prop["latitude"], prop["longitude"], release_lat, release_lon)
    sp = db.get("species_profiles", tp["species_id"])
    if not (distance >= sp["relocation_min_miles"] and distance <= sp["relocation_max_miles"]):
        raise err("ERR_RELOCATION_DISTANCE", "Release distance out of the species relocation band.")

    rec = db.new_record({
        "trap_placement_id": tp_id,
        "captured_at": captured_at,
        "release_latitude": release_lat,
        "release_longitude": release_lon,
        "release_distance_miles": distance,
        "disposition": "RELOCATED",
    })
    db.insert("capture_events", rec)

    # cascade: trap SET -> SPENT; kit restored
    tp["status"] = "SPENT"
    db.touch(tp)
    tech = db.get("technicians", tp["technician_id"])
    if tech:
        svc.kit_restore(tech)
    # if no SET trap remains, removal -> CLEARED; matching TRAP line performed
    svc.maybe_clear_removal(wo)
    # PRD §2.6: relocating a capture mutates the work order and bumps its version.
    db.touch(wo)
    return object_response(public(rec), 201)


@app.route("/trap-placements/<tp_id>/pull", methods=["POST"])
def pull_trap(tp_id):
    _uid, role = auth()
    require_role(role, {"FieldTechnician"})
    tp = svc.must_get("trap_placements", tp_id)
    wo = db.get("work_orders", tp["work_order_id"])
    if tp["status"] != "SET":
        raise err("ERR_INVALID_STATE", "Trap is not SET.")
    if wo["lifecycle"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Work order is not OPEN.")

    # trap SET -> EMPTY; kit restored
    tp["status"] = "EMPTY"
    db.touch(tp)
    tech = db.get("technicians", tp["technician_id"])
    if tech:
        svc.kit_restore(tech)
    # if no SET trap remains and at least one was ever SET -> CLEARED.
    if not svc.remaining_set_traps(wo["id"]):
        # ever_set_any_trap counts SET/SPENT/EMPTY; this trap was just SET, so it
        # is always satisfied for a real pull. (empty-set guard, priority 13)
        if not svc.ever_set_any_trap(wo["id"]):
            raise err("ERR_EMPTY_SET", "Cannot clear removal when no trap was ever SET.")
        svc.maybe_clear_removal(wo)
    # PRD §2.6: pulling a trap mutates the work order and bumps its version.
    db.touch(wo)
    return object_response(public(tp), 200)


@app.route("/trap-placements/<tp_id>/captures", methods=["GET"])
def list_captures(tp_id):
    _uid, role = auth()
    require_role(role, {"FieldTechnician", "Dispatcher", "ComplianceOfficer"})
    svc.must_get("trap_placements", tp_id)
    items = [c for c in db.values("capture_events") if c["trap_placement_id"] == tp_id]
    return list_response(items)


# ===========================================================================
# ExclusionRepair
# ===========================================================================
@app.route("/work-orders/<wo_id>/exclusion-repairs", methods=["POST"])
def create_exclusion_repair(wo_id):
    _uid, role = auth()
    require_role(role, {"FieldTechnician"})
    wo = svc.must_get("work_orders", wo_id)
    data = body()
    entry_point_id = require_str(data, "entry_point_id")
    sanitation_included = require_bool(data, "sanitation_included", default=False)
    ep = svc.must_get("entry_points", entry_point_id)

    # state: work order OPEN
    if wo["lifecycle"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Work order is not OPEN.")

    # priority 9: entry point must belong to the WO's quote's inspection and be OPEN
    quote = db.get("quotes", wo["quote_id"])
    if ep["inspection_id"] != quote["inspection_id"] or ep["seal_status"] != "OPEN":
        raise err("ERR_ENTRY_POINT_MISMATCH", "Entry point not on this work order's inspection, or already sealed.")

    rec = db.new_record({
        "work_order_id": wo_id,
        "entry_point_id": entry_point_id,
        "sanitation_included": sanitation_included,
        "status": "STARTED",
    })
    db.insert("exclusion_repairs", rec)
    # first repair advances exclusion PENDING -> SEALING
    if wo["exclusion_status"] == "PENDING":
        wo["exclusion_status"] = "SEALING"
        db.touch(wo)
    return object_response(public(rec), 201)


@app.route("/work-orders/<wo_id>/exclusion-repairs", methods=["GET"])
def list_wo_exclusion_repairs(wo_id):
    _uid, role = auth()
    require_role(role, {"FieldTechnician", "Dispatcher", "ComplianceOfficer"})
    svc.must_get("work_orders", wo_id)
    items = [er for er in db.values("exclusion_repairs") if er["work_order_id"] == wo_id]
    return list_response(items)


@app.route("/exclusion-repairs/<rec_id>", methods=["GET"])
def get_exclusion_repair(rec_id):
    _uid, role = auth()
    require_role(role, {"FieldTechnician", "Dispatcher", "ComplianceOfficer"})
    rec = svc.must_get("exclusion_repairs", rec_id)
    return object_response(public(rec), 200)


@app.route("/exclusion-repairs", methods=["GET"])
def list_exclusion_repairs():
    _uid, role = auth()
    require_role(role, {"FieldTechnician", "Dispatcher", "ComplianceOfficer"})
    entry_point_id = request.args.get("entry_point_id")
    items = db.values("exclusion_repairs")
    if entry_point_id is not None:
        items = [er for er in items if er["entry_point_id"] == entry_point_id]
    return list_response(items)


@app.route("/work-orders/<wo_id>/exclusion-repairs/<repair_id>/complete", methods=["POST"])
def complete_exclusion_repair(wo_id, repair_id):
    _uid, role = auth()
    require_role(role, {"FieldTechnician"})
    wo = svc.must_get("work_orders", wo_id)
    repair = svc.must_get("exclusion_repairs", repair_id)
    # nested ownership: repair must belong to the work order in the path
    if repair["work_order_id"] != wo_id:
        raise err("ERR_NOT_FOUND", "Exclusion repair not found on this work order.")

    # state checks: WO OPEN, removal CLEARED, repair STARTED
    if wo["lifecycle"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Work order is not OPEN.")
    if repair["status"] != "STARTED":
        raise err("ERR_INVALID_STATE", "Repair is not STARTED.")
    if wo["removal_status"] != "CLEARED":
        raise err("ERR_INVALID_STATE", "Removal dimension must be CLEARED before sealing.")

    repair["status"] = "COMPLETED"
    db.touch(repair)
    # seal the targeted entry point
    ep = db.get("entry_points", repair["entry_point_id"])
    if ep:
        ep["seal_status"] = "SEALED"
        db.touch(ep)
    # matching EXCLUSION line performed
    _perform_exclusion_line(wo["quote_id"], repair["entry_point_id"])
    # exclusion_status SEALING -> SEALED when all targeted open entry points sealed
    svc.maybe_seal_exclusion(wo)
    # PRD §2.6: completing an exclusion repair mutates the work order, bumps version.
    db.touch(wo)
    # auto-close if both dimensions terminal (its own OPEN->CLOSED transition)
    svc.maybe_auto_close(wo)
    return object_response(public(repair), 200)


def _perform_exclusion_line(quote_id, entry_point_id):
    """Flip the matching EXCLUSION line performed.

    The EXCLUSION line is matched by the entry point's species. Pick the first
    unperformed EXCLUSION line for that species.
    """
    ep = db.get("entry_points", entry_point_id)
    species_id = ep["species_id"] if ep else None
    candidates = [
        li for li in svc.line_items_of_quote(quote_id)
        if li["line_type"] == "EXCLUSION" and (species_id is None or li["species_id"] == species_id)
    ]
    for li in candidates:
        if not li["performed"]:
            li["performed"] = True
            db.touch(li)
            return


# ===========================================================================
# MonitoringVisit
# ===========================================================================
@app.route("/work-orders/<wo_id>/monitoring-visits", methods=["POST"])
def create_monitoring_visit(wo_id):
    _uid, role = auth()
    require_role(role, {"FieldTechnician"})
    wo = svc.must_get("work_orders", wo_id)
    data = body()
    visit_start = require_str(data, "visit_start")
    visit_end = require_str(data, "visit_end")
    traps_reset = opt_int(data, "traps_reset", 0, minimum=0)
    vs = _try_parse_dt(visit_start)
    ve = _try_parse_dt(visit_end)

    # state: work order CLOSED (monitoring on closed work order's property)
    if wo["lifecycle"] != "CLOSED":
        raise err("ERR_INVALID_STATE", "Monitoring visits require a CLOSED work order.")

    property_id = wo["property_id"]
    # priority 11: visit overlap (half-open) on the same property
    if vs is not None and ve is not None:
        for mv in db.values("monitoring_visits"):
            if mv["property_id"] == property_id:
                o_vs = parse_iso(mv["visit_start"])
                o_ve = parse_iso(mv["visit_end"])
                if svc.visit_windows_overlap(vs, ve, o_vs, o_ve):
                    raise err("ERR_VISIT_OVERLAP", "Monitoring visit overlaps another visit on the property.")

    # priority 12: window well-formedness
    if vs is not None and ve is not None and not (ve > vs):
        raise err("ERR_INVALID_WINDOW", "visit_end must be strictly after visit_start.")

    # priority 15: deferred datetime-format validation
    if vs is None or ve is None:
        raise err("ERR_INVALID_REQUEST", "visit_start/visit_end must be valid ISO 8601 datetimes.")

    rec = db.new_record({
        "work_order_id": wo_id,
        "property_id": property_id,
        "visit_start": visit_start,
        "visit_end": visit_end,
        "traps_reset": traps_reset,
    })
    db.insert("monitoring_visits", rec)
    return object_response(public(rec), 201)


@app.route("/work-orders/<wo_id>/monitoring-visits", methods=["GET"])
def list_wo_monitoring_visits(wo_id):
    _uid, role = auth()
    require_role(role, {"FieldTechnician", "Dispatcher", "ComplianceOfficer", "PropertyOwner"})
    svc.must_get("work_orders", wo_id)
    items = [mv for mv in db.values("monitoring_visits") if mv["work_order_id"] == wo_id]
    return list_response(items)


@app.route("/monitoring-visits/<rec_id>", methods=["GET"])
def get_monitoring_visit(rec_id):
    _uid, role = auth()
    require_role(role, {"FieldTechnician", "Dispatcher", "ComplianceOfficer", "PropertyOwner"})
    rec = svc.must_get("monitoring_visits", rec_id)
    return object_response(public(rec), 200)


@app.route("/monitoring-visits", methods=["GET"])
def list_monitoring_visits():
    _uid, role = auth()
    require_role(role, {"FieldTechnician", "Dispatcher", "ComplianceOfficer", "PropertyOwner"})
    property_id = request.args.get("property_id")
    items = db.values("monitoring_visits")
    if property_id is not None:
        items = [mv for mv in items if mv["property_id"] == property_id]
    return list_response(items)


# ===========================================================================
# WarrantyClaim
# ===========================================================================
@app.route("/work-orders/<wo_id>/warranty-claims", methods=["POST"])
def create_warranty_claim(wo_id):
    _uid, role = auth()
    require_role(role, {"PropertyOwner"})
    wo = svc.must_get("work_orders", wo_id)
    # ownership: PropertyOwner must own the property's account
    _require_owner_of_work_order(wo, _uid)
    data = body()
    reported_at = require_str(data, "reported_at")
    description = require_str(data, "description")
    _validate_datetime(reported_at)
    # PRD §3.9: file a warranty claim against a CLOSED work order
    if wo["lifecycle"] != "CLOSED":
        raise err("ERR_INVALID_STATE", "Warranty claim requires a CLOSED work order.")
    rec = db.new_record({
        "work_order_id": wo_id,
        "reported_at": reported_at,
        "description": description,
        "status": "FILED",
    })
    db.insert("warranty_claims", rec)
    return object_response(public(rec), 201)


@app.route("/work-orders/<wo_id>/warranty-claims", methods=["GET"])
def list_wo_warranty_claims(wo_id):
    _uid, role = auth()
    require_role(role, {"PropertyOwner", "Dispatcher", "ComplianceOfficer"})
    svc.must_get("work_orders", wo_id)
    items = [wc for wc in db.values("warranty_claims") if wc["work_order_id"] == wo_id]
    return list_response(items)


@app.route("/warranty-claims/<rec_id>", methods=["GET"])
def get_warranty_claim(rec_id):
    _uid, role = auth()
    require_role(role, {"PropertyOwner", "Dispatcher", "ComplianceOfficer"})
    rec = svc.must_get("warranty_claims", rec_id)
    return object_response(public(rec), 200)


@app.route("/warranty-claims/<claim_id>/adjudicate", methods=["POST"])
def adjudicate_warranty_claim(claim_id):
    _uid, role = auth()
    require_role(role, {"ComplianceOfficer"})
    claim = svc.must_get("warranty_claims", claim_id)
    if claim["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Warranty claim is not FILED.")
    wo = db.get("work_orders", claim["work_order_id"])

    from datetime import timedelta
    accepted = False
    if wo and wo["lifecycle"] == "CLOSED":
        close_dt = parse_iso(wo.get("_closed_at") or wo["updated_at"])
        deadline = close_dt + timedelta(days=calc.WARRANTY_DAYS)
        reported = parse_iso(claim["reported_at"])
        eligible = reported <= deadline
        qualified = _work_order_qualified(wo)
        accepted = eligible and qualified

    claim["status"] = "ACCEPTED" if accepted else "REJECTED"
    db.touch(claim)
    return object_response(public(claim), 200)


def _work_order_qualified(wo):
    """Qualified iff at least one EXCLUSION line item was performed."""
    quote = db.get("quotes", wo["quote_id"])
    if not quote:
        return False
    for li in svc.line_items_of_quote(quote["id"]):
        if li["line_type"] == "EXCLUSION" and li["performed"]:
            return True
    return False


def _require_owner_of_work_order(wo, user_id):
    prop = db.get("properties", wo["property_id"])
    if prop is None:
        return
    if prop["account_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "PropertyOwner does not own this resource.")


# ===========================================================================
# Helpers
# ===========================================================================
def _validate_datetime(value):
    """Parse an ISO 8601 datetime, raising ERR_INVALID_REQUEST on failure."""
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Invalid ISO 8601 datetime: %s" % value)


def _try_parse_dt(value):
    """Parse an ISO 8601 datetime; return None on failure (deferred validation)."""
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
