"""Residential EV-Charger Installation API — Flask entry point.

All endpoints, error handling, and route registration. In-memory store (db.py).
Boots empty on every invocation; no seeding.
"""
import os
from datetime import datetime, timezone

from flask import Flask, request

import db
import errors
import serializers as S
import calculations as calc
import validators as V
import services
from clock import clock
from errors import ApiError, err
from middleware import require_auth
from response import success, list_response, error_response

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_RESOURCE_NOT_FOUND", "resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", "method not allowed", 400)


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INTERNAL", str(e), 500)


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def base_fields(versioned=True):
    ts = db.now_iso()
    rec = {"id": db.new_id(), "created_at": ts}
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def get_or_404(store, key, message="resource not found"):
    ent = store.get(key)
    if ent is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, message)
    return ent


def fk_or_404(store, key, message="referenced resource not found"):
    ent = store.get(key)
    if ent is None:
        raise err(errors.ERR_FK_NOT_FOUND, message)
    return ent


# ---------------------------------------------------------------------------
# Test-driving clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth({"Coordinator"})
    body = V.get_body()
    iso = V.require_str(body, "to_iso8601")
    parsed = _parse_iso(iso)
    if parsed is None:
        raise err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 instant")
    clock.set(parsed)
    return success({}, status=200)


def _parse_iso(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Homeowner
# ---------------------------------------------------------------------------
@app.route("/homeowners", methods=["POST"])
def create_homeowner():
    # Anonymous self-registration: no auth headers required.
    body = V.get_body()
    email = V.require_str(body, "email")
    full_name = V.require_str(body, "full_name")
    state_code = V.require_str(body, "state_code")
    _check_state_code(state_code)
    # unique email
    for h in db.homeowners.values():
        if h["email"] == email:
            raise err(errors.ERR_INVALID_REQUEST, "email already registered")
    rec = base_fields()
    rec.update({"email": email, "full_name": full_name, "state_code": state_code})
    db.homeowners[rec["id"]] = rec
    return success(S.homeowner(rec), status=201)


def _check_state_code(code):
    if not (isinstance(code, str) and len(code) == 2 and code.isalpha() and code.isupper()):
        raise err(errors.ERR_INVALID_REQUEST, "state_code must be 2-letter uppercase")


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------
@app.route("/properties", methods=["POST"])
def create_property():
    require_auth({"Homeowner", "Coordinator"})
    body = V.get_body()
    homeowner_id = V.require_str(body, "homeowner_id")
    address_line = V.require_str(body, "address_line")
    state_code = V.require_str(body, "state_code")
    utility_territory_code = V.require_str(body, "utility_territory_code")
    main_breaker_amps = V.require_int(body, "main_breaker_amps")
    floor_area_sqft = V.require_int(body, "floor_area_sqft")
    service_voltage = V.opt_int(body, "service_voltage", 240)

    # FK existence
    fk_or_404(db.homeowners, homeowner_id, "homeowner not found")

    _check_state_code(state_code)
    if main_breaker_amps not in (100, 150, 200):
        raise err(errors.ERR_VALIDATION_LIMIT, "main_breaker_amps must be one of {100,150,200}")
    if floor_area_sqft <= 0:
        raise err(errors.ERR_INVALID_REQUEST, "floor_area_sqft must be positive")
    if service_voltage != 240:
        raise err(errors.ERR_INVALID_REQUEST, "service_voltage must be 240")

    rec = base_fields()
    rec.update({
        "homeowner_id": homeowner_id,
        "address_line": address_line,
        "state_code": state_code,
        "utility_territory_code": utility_territory_code,
        "service_voltage": service_voltage,
        "main_breaker_amps": main_breaker_amps,
        "floor_area_sqft": floor_area_sqft,
    })
    db.properties[rec["id"]] = rec
    return success(S.property_(rec), status=201)


@app.route("/properties/<pid>", methods=["GET"])
def get_property(pid):
    require_auth({"Homeowner", "Coordinator"})
    ent = get_or_404(db.properties, pid, "property not found")
    return success(S.property_(ent))


@app.route("/properties", methods=["GET"])
def list_properties():
    require_auth({"Homeowner", "Coordinator"})
    homeowner_id = request.args.get("homeowner_id")
    items = list(db.properties.values())
    if homeowner_id is not None:
        items = [p for p in items if p["homeowner_id"] == homeowner_id]
    page, limit, offset, total = services.paginate(items)
    return list_response([S.property_(p) for p in page], limit, offset, total)


# ---------------------------------------------------------------------------
# ChargerProduct (catalog) — keyed by sku, immutable (no updated_at/version)
# ---------------------------------------------------------------------------
@app.route("/charger-products", methods=["POST"])
def create_charger_product():
    require_auth({"Coordinator"})
    body = V.get_body()
    sku = V.require_str(body, "sku")
    name = V.require_str(body, "name")
    rated_amps = V.require_int(body, "rated_amps")
    required_circuit_amps = V.require_int(body, "required_circuit_amps")
    msrp_cents = V.require_int(body, "msrp_cents")

    if rated_amps not in (32, 40, 48):
        raise err(errors.ERR_INVALID_REQUEST, "rated_amps must be one of {32,40,48}")
    if required_circuit_amps not in (40, 50, 60):
        raise err(errors.ERR_INVALID_REQUEST, "required_circuit_amps must be one of {40,50,60}")
    if msrp_cents < 0:
        raise err(errors.ERR_INVALID_REQUEST, "msrp_cents must be non-negative")
    if sku in db.charger_products:
        raise err(errors.ERR_INVALID_REQUEST, "sku already exists")

    rec = base_fields(versioned=False)
    rec.update({
        "sku": sku,
        "name": name,
        "rated_amps": rated_amps,
        "required_circuit_amps": required_circuit_amps,
        "msrp_cents": msrp_cents,
    })
    db.charger_products[sku] = rec
    return success(S.charger_product(rec), status=201)


@app.route("/charger-products/<sku>", methods=["GET"])
def get_charger_product(sku):
    require_auth({"Homeowner", "Coordinator"})
    ent = get_or_404(db.charger_products, sku, "charger product not found")
    return success(S.charger_product(ent))


# ---------------------------------------------------------------------------
# Electrician
# ---------------------------------------------------------------------------
@app.route("/electricians", methods=["POST"])
def create_electrician():
    require_auth({"Coordinator"})
    body = V.get_body()
    full_name = V.require_str(body, "full_name")
    license_state_code = V.require_str(body, "license_state_code")
    max_daily_jobs = V.opt_int(body, "max_daily_jobs", 2)

    _check_state_code(license_state_code)
    if max_daily_jobs <= 0:
        raise err(errors.ERR_INVALID_REQUEST, "max_daily_jobs must be positive")

    rec = base_fields()
    rec.update({
        "full_name": full_name,
        "license_state_code": license_state_code,
        "max_daily_jobs": max_daily_jobs,
        "status": "ACTIVE",
    })
    db.electricians[rec["id"]] = rec
    return success(S.electrician(rec), status=201)


@app.route("/electricians/<eid>", methods=["GET"])
def get_electrician(eid):
    require_auth({"Coordinator", "Electrician"})
    ent = get_or_404(db.electricians, eid, "electrician not found")
    return success(S.electrician(ent))


@app.route("/_electricians/<eid>/set-status", methods=["POST"])
def set_electrician_status(eid):
    require_auth({"Coordinator"})
    ent = get_or_404(db.electricians, eid, "electrician not found")
    body = V.get_body()
    status = V.require_enum(body, "status", {"ACTIVE", "SUSPENDED"})
    ent["status"] = status
    db.touch(ent)
    return success(S.electrician(ent))


# ---------------------------------------------------------------------------
# InstallJob
# ---------------------------------------------------------------------------
def _circuit_band_for_panel(main_breaker_amps):
    return {100: 40, 150: 50, 200: 60}[main_breaker_amps]


def _check_circuit_fits_panel(charger, prop):
    band = _circuit_band_for_panel(prop["main_breaker_amps"])
    if charger["required_circuit_amps"] > band:
        raise err(errors.ERR_CIRCUIT_EXCEEDS_PANEL,
                  "charger required_circuit_amps exceeds property panel band")


@app.route("/install-jobs", methods=["POST"])
def create_install_job():
    require_auth({"Homeowner", "Coordinator"})
    body = V.get_body()
    property_id = V.require_str(body, "property_id")
    charger_product_sku = V.require_str(body, "charger_product_sku")

    # FK existence, left-to-right
    prop = fk_or_404(db.properties, property_id, "property not found")
    charger = fk_or_404(db.charger_products, charger_product_sku, "charger product not found")

    # circuit-to-panel sizing
    _check_circuit_fits_panel(charger, prop)

    rec = base_fields()
    rec.update({
        "property_id": property_id,
        "charger_product_sku": charger_product_sku,
        "workflow_status": "CREATED",
        "compliance_status": "PENDING_REVIEW",
        "requires_panel_upgrade": False,
        "activation_pairing_code": None,
    })
    db.install_jobs[rec["id"]] = rec
    return success(S.install_job(rec), status=201)


@app.route("/install-jobs/<jid>", methods=["GET"])
def get_install_job(jid):
    require_auth({"Homeowner", "Coordinator", "Electrician"})
    ent = get_or_404(db.install_jobs, jid, "install job not found")
    return success(S.install_job(ent))


@app.route("/install-jobs", methods=["GET"])
def list_install_jobs():
    require_auth({"Homeowner", "Coordinator"})
    property_id = request.args.get("property_id")
    items = list(db.install_jobs.values())
    if property_id is not None:
        items = [j for j in items if j["property_id"] == property_id]
    page, limit, offset, total = services.paginate(items)
    return list_response([S.install_job(j) for j in page], limit, offset, total)


@app.route("/install-jobs/<jid>/scope", methods=["PATCH"])
def scope_install_job(jid):
    require_auth({"Coordinator"})
    job = get_or_404(db.install_jobs, jid, "install job not found")
    body = V.get_body()
    new_sku = V.require_str(body, "charger_product_sku")
    expected_version = V.require_int(body, "expected_install_job_version")

    charger = fk_or_404(db.charger_products, new_sku, "charger product not found")

    # OCC check (priority 7) precedes circuit-to-panel sizing (priority 14)
    if expected_version != job["version"]:
        raise err(errors.ERR_STALE_JOB_VERSION, "expected_install_job_version is stale")

    prop = db.properties.get(job["property_id"])
    _check_circuit_fits_panel(charger, prop)

    job["charger_product_sku"] = new_sku
    db.touch(job)
    return success(S.install_job(job))


@app.route("/install-jobs/<jid>/activate", methods=["POST"])
def activate_install_job(jid):
    user_id, role = require_auth({"Homeowner"})
    job = get_or_404(db.install_jobs, jid, "install job not found")
    body = V.get_body()
    pairing_code = V.require_str(body, "pairing_code")

    # ownership (priority 5)
    if not services.homeowner_owns_job(user_id, job):
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the owner of this job")
    # state (priority 6)
    if job["workflow_status"] != "INSTALLED":
        raise err(errors.ERR_INVALID_STATE, "job is not INSTALLED")
    # pairing code check
    if pairing_code != job.get("activation_pairing_code"):
        raise err(errors.ERR_INVALID_REQUEST, "pairing_code does not match")

    job["workflow_status"] = "ACTIVATED"
    db.touch(job)
    return success(S.install_job(job))


@app.route("/install-jobs/<jid>/cancel", methods=["POST"])
def cancel_install_job(jid):
    user_id, role = require_auth({"Homeowner"})
    job = get_or_404(db.install_jobs, jid, "install job not found")
    if not services.homeowner_owns_job(user_id, job):
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the owner of this job")
    if job["workflow_status"] not in ("CREATED", "ASSESSED", "QUOTED", "SCHEDULED"):
        raise err(errors.ERR_INVALID_STATE, "job cannot be cancelled from current state")

    # cascade: dispatch assignments
    for da in db.dispatch_assignments.values():
        if da["install_job_id"] == jid and da["status"] in ("BOOKED", "EN_ROUTE"):
            da["status"] = "CANCELLED"
            db.touch(da)
    # cascade: quotes
    for q in db.quotes.values():
        if q["install_job_id"] == jid and q["status"] in ("DRAFT", "SENT"):
            q["status"] = "REJECTED"
            db.touch(q)

    job["workflow_status"] = "CANCELLED"
    db.touch(job)
    return success(S.install_job(job))


@app.route("/install-jobs/<jid>/close", methods=["POST"])
def close_install_job(jid):
    require_auth({"Coordinator"})
    job = get_or_404(db.install_jobs, jid, "install job not found")
    if job["workflow_status"] != "ACTIVATED":
        raise err(errors.ERR_INVALID_STATE, "job is not ACTIVATED")
    # no open warranty ticket
    for wt in db.warranty_tickets.values():
        if wt["install_job_id"] == jid and wt["status"] in ("OPEN", "DIAGNOSING", "AWAITING_PARTS"):
            raise err(errors.ERR_OPEN_WARRANTY_BLOCKS_CLOSE,
                      "an unresolved warranty ticket blocks closure")
    job["workflow_status"] = "CLOSED"
    db.touch(job)
    return success(S.install_job(job))


# ---------------------------------------------------------------------------
# SiteAssessment
# ---------------------------------------------------------------------------
@app.route("/site-assessments", methods=["POST"])
def create_site_assessment():
    require_auth({"Coordinator"})
    body = V.get_body()
    property_id = V.require_str(body, "property_id")
    install_job_id = V.require_str(body, "install_job_id")
    assessment_method = V.require_enum(body, "assessment_method",
                                       {"STANDARD_220_83", "LOAD_STUDY_220_87"})
    declared_fixed_appliance_va = V.require_int(body, "declared_fixed_appliance_va")
    max_measured_demand_va = V.opt_int(body, "max_measured_demand_va", 0)

    # FK existence, left-to-right: property_id then install_job_id
    prop = fk_or_404(db.properties, property_id, "property not found")
    job = fk_or_404(db.install_jobs, install_job_id, "install job not found")

    if declared_fixed_appliance_va < 0:
        raise err(errors.ERR_INVALID_REQUEST, "declared_fixed_appliance_va must be non-negative")
    if max_measured_demand_va < 0:
        raise err(errors.ERR_INVALID_REQUEST, "max_measured_demand_va must be non-negative")

    rec = base_fields()
    rec.update({
        "property_id": property_id,
        "install_job_id": install_job_id,
        "assessment_method": assessment_method,
        "declared_fixed_appliance_va": declared_fixed_appliance_va,
        "max_measured_demand_va": max_measured_demand_va,
        "existing_demand_va": 0,
        "spare_capacity_va": 0,
        "charger_fits": False,
        "status": "DRAFT",
    })
    charger = db.charger_products.get(job["charger_product_sku"])
    calc.compute_assessment(rec, prop, charger)
    db.site_assessments[rec["id"]] = rec
    return success(S.site_assessment(rec), status=201)


def _refresh_assessment(a):
    """Recompute computed fields on re-read (PRD §3.2)."""
    job = db.install_jobs.get(a["install_job_id"])
    prop = db.properties.get(a["property_id"])
    if job is None or prop is None:
        return
    charger = db.charger_products.get(job["charger_product_sku"])
    if charger is None:
        return
    calc.compute_assessment(a, prop, charger)


@app.route("/site-assessments/<aid>", methods=["GET"])
def get_site_assessment(aid):
    require_auth({"Coordinator", "Homeowner"})
    ent = get_or_404(db.site_assessments, aid, "site assessment not found")
    _refresh_assessment(ent)
    return success(S.site_assessment(ent))


@app.route("/site-assessments", methods=["GET"])
def list_site_assessments():
    require_auth({"Coordinator", "Homeowner"})
    install_job_id = request.args.get("install_job_id")
    property_id = request.args.get("property_id")
    items = list(db.site_assessments.values())
    if install_job_id is not None:
        items = [a for a in items if a["install_job_id"] == install_job_id]
    if property_id is not None:
        items = [a for a in items if a["property_id"] == property_id]
    for a in items:
        _refresh_assessment(a)
    page, limit, offset, total = services.paginate(items)
    return list_response([S.site_assessment(a) for a in page], limit, offset, total)


@app.route("/site-assessments/<aid>/accept", methods=["POST"])
def accept_site_assessment(aid):
    require_auth({"Coordinator"})
    assessment = get_or_404(db.site_assessments, aid, "site assessment not found")
    job = db.install_jobs.get(assessment["install_job_id"])
    if job is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "install job not found")

    # state precondition: job CREATED and assessment DRAFT
    if job["workflow_status"] != "CREATED" or assessment["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "assessment cannot be accepted from current state")

    # finalize computed fields at the accept transition
    _refresh_assessment(assessment)

    # accept; supersede other ACCEPTED assessments on the same job
    assessment["status"] = "ACCEPTED"
    db.touch(assessment)
    for other in db.site_assessments.values():
        if (other["id"] != assessment["id"]
                and other["install_job_id"] == job["id"]
                and other["status"] == "ACCEPTED"):
            other["status"] = "SUPERSEDED"
            db.touch(other)

    requires_upgrade = not assessment["charger_fits"]
    job["requires_panel_upgrade"] = requires_upgrade

    if requires_upgrade:
        # cascade: create PanelUpgradeReferral; its creation BLOCKS compliance
        recommended = _recommend_main_amps(job)
        ref = base_fields()
        ref.update({
            "install_job_id": job["id"],
            "recommended_main_amps": recommended,
            "status": "OPEN",
        })
        db.panel_upgrade_referrals[ref["id"]] = ref
        if job["compliance_status"] == "PENDING_REVIEW":
            job["compliance_status"] = "BLOCKED"
            # compliance change is a job mutation
            # (folded into the single job touch below via version bump)

    # workflow CREATED -> ASSESSED
    job["workflow_status"] = "ASSESSED"
    db.touch(job)
    return success(S.site_assessment(assessment))


def _recommend_main_amps(job):
    """Recommend an upgraded main amperage (150 or 200)."""
    prop = db.properties.get(job["property_id"])
    if prop is not None and prop["main_breaker_amps"] < 150:
        return 150
    return 200


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------
@app.route("/quotes", methods=["POST"])
def create_quote():
    require_auth({"Coordinator"})
    body = V.get_body()
    install_job_id = V.require_str(body, "install_job_id")
    labor_cents = V.require_int(body, "labor_cents")
    parts_line_cents = V.require_int_array(body, "parts_line_cents", non_negative=True)

    fk_or_404(db.install_jobs, install_job_id, "install job not found")

    if labor_cents < 0:
        raise err(errors.ERR_INVALID_REQUEST, "labor_cents must be non-negative")

    rec = base_fields()
    rec.update({
        "install_job_id": install_job_id,
        "labor_cents": labor_cents,
        "parts_line_cents": parts_line_cents,
        "base_subtotal_cents": 0,
        "discount_cents": 0,
        "tax_cents": 0,
        "permit_fee_cents": 0,
        "quote_total_cents": 0,
        "status": "DRAFT",
    })
    calc.compute_quote(rec)
    db.quotes[rec["id"]] = rec
    return success(S.quote(rec), status=201)


@app.route("/quotes/<qid>", methods=["GET"])
def get_quote(qid):
    require_auth({"Coordinator", "Homeowner"})
    ent = get_or_404(db.quotes, qid, "quote not found")
    calc.compute_quote(ent)
    return success(S.quote(ent))


@app.route("/quotes", methods=["GET"])
def list_quotes():
    require_auth({"Coordinator", "Homeowner"})
    install_job_id = request.args.get("install_job_id")
    items = list(db.quotes.values())
    if install_job_id is not None:
        items = [q for q in items if q["install_job_id"] == install_job_id]
    for q in items:
        calc.compute_quote(q)
    page, limit, offset, total = services.paginate(items)
    return list_response([S.quote(q) for q in page], limit, offset, total)


@app.route("/quotes/<qid>/send", methods=["POST"])
def send_quote(qid):
    require_auth({"Coordinator"})
    quote = get_or_404(db.quotes, qid, "quote not found")
    job = db.install_jobs.get(quote["install_job_id"])
    if quote["status"] != "DRAFT" or job is None or job["workflow_status"] != "ASSESSED":
        raise err(errors.ERR_INVALID_STATE, "quote cannot be sent from current state")
    quote["status"] = "SENT"
    db.touch(quote)
    return success(S.quote(quote))


@app.route("/quotes/<qid>/accept", methods=["POST"])
def accept_quote(qid):
    user_id, role = require_auth({"Homeowner"})
    quote = get_or_404(db.quotes, qid, "quote not found")
    body = V.get_body()
    expected_version = V.require_int(body, "expected_install_job_version")

    job = db.install_jobs.get(quote["install_job_id"])
    if job is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "install job not found")

    # ownership (priority 5)
    if not services.homeowner_owns_job(user_id, job):
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the owner of this job")

    # state (priority 6): quote SENT and job ASSESSED
    if quote["status"] != "SENT" or job["workflow_status"] != "ASSESSED":
        raise err(errors.ERR_INVALID_STATE, "quote cannot be accepted from current state")

    # OCC (priority 7)
    if expected_version != job["version"]:
        raise err(errors.ERR_STALE_JOB_VERSION, "expected_install_job_version is stale")

    quote["status"] = "ACCEPTED"
    db.touch(quote)
    # reject peer quotes in ACCEPTED/SENT on the same job
    for other in db.quotes.values():
        if (other["id"] != quote["id"]
                and other["install_job_id"] == job["id"]
                and other["status"] in ("ACCEPTED", "SENT")):
            other["status"] = "REJECTED"
            db.touch(other)

    job["workflow_status"] = "QUOTED"
    db.touch(job)
    return success(S.quote(quote))


@app.route("/quotes/<qid>/reject", methods=["POST"])
def reject_quote(qid):
    user_id, role = require_auth({"Homeowner"})
    quote = get_or_404(db.quotes, qid, "quote not found")
    job = db.install_jobs.get(quote["install_job_id"])
    if job is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "install job not found")
    if not services.homeowner_owns_job(user_id, job):
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the owner of this job")
    if quote["status"] != "SENT":
        raise err(errors.ERR_INVALID_STATE, "quote is not SENT")
    quote["status"] = "REJECTED"
    db.touch(quote)
    return success(S.quote(quote))


@app.route("/quotes/<qid>/revise", methods=["POST"])
def revise_quote(qid):
    require_auth({"Coordinator"})
    quote = get_or_404(db.quotes, qid, "quote not found")
    body = V.get_body()
    if quote["status"] != "REJECTED":
        raise err(errors.ERR_INVALID_STATE, "quote is not REJECTED")

    new_labor = V.opt_int(body, "labor_cents", None)
    new_parts = None
    if "parts_line_cents" in body and body["parts_line_cents"] is not None:
        new_parts = V.require_int_array(body, "parts_line_cents", non_negative=True)

    if new_labor is not None:
        if new_labor < 0:
            raise err(errors.ERR_INVALID_REQUEST, "labor_cents must be non-negative")
        quote["labor_cents"] = new_labor
    if new_parts is not None:
        quote["parts_line_cents"] = new_parts

    quote["status"] = "DRAFT"
    calc.compute_quote(quote)
    db.touch(quote)
    return success(S.quote(quote))


# ---------------------------------------------------------------------------
# PermitApplication
# ---------------------------------------------------------------------------
@app.route("/permit-applications", methods=["POST"])
def create_permit_application():
    require_auth({"Coordinator"})
    body = V.get_body()
    install_job_id = V.require_str(body, "install_job_id")
    jurisdiction_code = V.require_str(body, "jurisdiction_code")

    job = fk_or_404(db.install_jobs, install_job_id, "install job not found")

    # PRD §3.5: a job whose requires_panel_upgrade is true (and is therefore
    # BLOCKED) cannot start permitting and is rejected with
    # ERR_PANEL_UPGRADE_REQUIRED. This specific claim takes precedence over the
    # generic state check for the BLOCKED-due-to-upgrade case.
    if job["requires_panel_upgrade"]:
        raise err(errors.ERR_PANEL_UPGRADE_REQUIRED, "job requires a panel upgrade")
    # state (priority 6): compliance must otherwise be PENDING_REVIEW
    if job["compliance_status"] != "PENDING_REVIEW":
        raise err(errors.ERR_INVALID_STATE, "job compliance is not PENDING_REVIEW")

    rec = base_fields()
    rec.update({
        "install_job_id": install_job_id,
        "jurisdiction_code": jurisdiction_code,
        "status": "SUBMITTED",
        "correction_rounds": 0,
    })
    db.permit_applications[rec["id"]] = rec

    job["compliance_status"] = "PERMIT_PENDING"
    db.touch(job)
    return success(S.permit_application(rec), status=201)


@app.route("/permit-applications/<pid>", methods=["GET"])
def get_permit_application(pid):
    require_auth({"Coordinator"})
    ent = get_or_404(db.permit_applications, pid, "permit application not found")
    return success(S.permit_application(ent))


@app.route("/permit-applications", methods=["GET"])
def list_permit_applications():
    require_auth({"Coordinator"})
    install_job_id = request.args.get("install_job_id")
    items = list(db.permit_applications.values())
    if install_job_id is not None:
        items = [p for p in items if p["install_job_id"] == install_job_id]
    page, limit, offset, total = services.paginate(items)
    return list_response([S.permit_application(p) for p in page], limit, offset, total)


@app.route("/permit-applications/<pid>/approve", methods=["POST"])
def approve_permit(pid):
    require_auth({"Coordinator"})
    permit = get_or_404(db.permit_applications, pid, "permit application not found")
    if permit["status"] == "REJECTED":
        raise err(errors.ERR_PERMIT_REJECTED_FINAL, "permit is terminally REJECTED")
    if permit["status"] != "SUBMITTED":
        raise err(errors.ERR_INVALID_STATE, "permit is not SUBMITTED")
    permit["status"] = "APPROVED"
    db.touch(permit)
    job = db.install_jobs.get(permit["install_job_id"])
    if job is not None:
        services.reevaluate_clearance(job)
    return success(S.permit_application(permit))


@app.route("/permit-applications/<pid>/request-corrections", methods=["POST"])
def request_corrections(pid):
    require_auth({"Coordinator"})
    permit = get_or_404(db.permit_applications, pid, "permit application not found")
    if permit["status"] == "REJECTED":
        raise err(errors.ERR_PERMIT_REJECTED_FINAL, "permit is terminally REJECTED")
    if permit["status"] != "SUBMITTED":
        raise err(errors.ERR_INVALID_STATE, "permit is not SUBMITTED")
    permit["correction_rounds"] += 1
    permit["status"] = "CORRECTIONS_REQUESTED"
    db.touch(permit)
    return success(S.permit_application(permit))


@app.route("/permit-applications/<pid>/resubmit", methods=["POST"])
def resubmit_permit(pid):
    require_auth({"Coordinator"})
    permit = get_or_404(db.permit_applications, pid, "permit application not found")
    if permit["status"] == "REJECTED":
        raise err(errors.ERR_PERMIT_REJECTED_FINAL, "permit is terminally REJECTED")
    if permit["status"] != "CORRECTIONS_REQUESTED":
        raise err(errors.ERR_INVALID_STATE, "permit is not CORRECTIONS_REQUESTED")
    if permit["correction_rounds"] >= 3:
        permit["status"] = "REJECTED"
    else:
        permit["status"] = "SUBMITTED"
    db.touch(permit)
    return success(S.permit_application(permit))


# ---------------------------------------------------------------------------
# InterconnectionRequest
# ---------------------------------------------------------------------------
@app.route("/interconnection-requests", methods=["POST"])
def create_interconnection_request():
    require_auth({"Coordinator"})
    body = V.get_body()
    install_job_id = V.require_str(body, "install_job_id")
    utility_territory_code = V.require_str(body, "utility_territory_code")
    requested_load_amps = V.require_int(body, "requested_load_amps")

    fk_or_404(db.install_jobs, install_job_id, "install job not found")
    if requested_load_amps <= 0:
        raise err(errors.ERR_INVALID_REQUEST, "requested_load_amps must be positive")

    rec = base_fields()
    rec.update({
        "install_job_id": install_job_id,
        "utility_territory_code": utility_territory_code,
        "requested_load_amps": requested_load_amps,
        "status": "FILED",
    })
    db.interconnection_requests[rec["id"]] = rec
    return success(S.interconnection_request(rec), status=201)


@app.route("/interconnection-requests/<rid>", methods=["GET"])
def get_interconnection_request(rid):
    require_auth({"Coordinator", "UtilityReviewer"})
    ent = get_or_404(db.interconnection_requests, rid, "interconnection request not found")
    return success(S.interconnection_request(ent))


@app.route("/interconnection-requests", methods=["GET"])
def list_interconnection_requests():
    require_auth({"Coordinator", "UtilityReviewer"})
    install_job_id = request.args.get("install_job_id")
    items = list(db.interconnection_requests.values())
    if install_job_id is not None:
        items = [r for r in items if r["install_job_id"] == install_job_id]
    page, limit, offset, total = services.paginate(items)
    return list_response([S.interconnection_request(r) for r in page], limit, offset, total)


@app.route("/interconnection-requests/<rid>/start-review", methods=["POST"])
def start_review_interconnection(rid):
    require_auth({"UtilityReviewer"})
    req = get_or_404(db.interconnection_requests, rid, "interconnection request not found")
    if req["status"] != "FILED":
        raise err(errors.ERR_INVALID_STATE, "request is not FILED")
    req["status"] = "UNDER_REVIEW"
    db.touch(req)
    return success(S.interconnection_request(req))


@app.route("/interconnection-requests/<rid>/approve", methods=["POST"])
def approve_interconnection(rid):
    require_auth({"UtilityReviewer"})
    req = get_or_404(db.interconnection_requests, rid, "interconnection request not found")
    if req["status"] != "UNDER_REVIEW":
        raise err(errors.ERR_INVALID_STATE, "request is not UNDER_REVIEW")
    job = db.install_jobs.get(req["install_job_id"])
    prop = db.properties.get(job["property_id"]) if job else None
    # territory match (priority 11)
    if prop is None or req["utility_territory_code"] != prop["utility_territory_code"]:
        raise err(errors.ERR_TERRITORY_MISMATCH, "territory mismatch")
    req["status"] = "APPROVED"
    db.touch(req)
    if job is not None:
        services.reevaluate_clearance(job)
    return success(S.interconnection_request(req))


@app.route("/interconnection-requests/<rid>/deny", methods=["POST"])
def deny_interconnection(rid):
    require_auth({"UtilityReviewer"})
    req = get_or_404(db.interconnection_requests, rid, "interconnection request not found")
    if req["status"] != "UNDER_REVIEW":
        raise err(errors.ERR_INVALID_STATE, "request is not UNDER_REVIEW")
    req["status"] = "DENIED"
    db.touch(req)
    return success(S.interconnection_request(req))


# ---------------------------------------------------------------------------
# DispatchAssignment
# ---------------------------------------------------------------------------
def _utc_date(iso_dt):
    parsed = _parse_iso(iso_dt)
    if parsed is None:
        return None
    return parsed.date().isoformat()


@app.route("/dispatch-assignments", methods=["POST"])
def create_dispatch_assignment():
    require_auth({"Coordinator"})
    body = V.get_body()
    install_job_id = V.require_str(body, "install_job_id")
    electrician_id = V.require_str(body, "electrician_id")
    window_date = V.require_str(body, "window_date")
    window_start_minute = V.require_int(body, "window_start_minute")
    window_end_minute = V.require_int(body, "window_end_minute")

    # FK existence, left-to-right
    job = fk_or_404(db.install_jobs, install_job_id, "install job not found")
    electrician = fk_or_404(db.electricians, electrician_id, "electrician not found")

    # state (priority 6): job must be QUOTED
    if job["workflow_status"] != "QUOTED":
        raise err(errors.ERR_INVALID_STATE, "job is not QUOTED")

    # electrician active (priority 9.5)
    if electrician["status"] != "ACTIVE":
        raise err(errors.ERR_ELECTRICIAN_SUSPENDED, "electrician is SUSPENDED")

    # territory (priority 10)
    prop = db.properties.get(job["property_id"])
    if prop is None or electrician["license_state_code"] != prop["state_code"]:
        raise err(errors.ERR_ELECTRICIAN_OUT_OF_TERRITORY, "electrician out of territory")

    # window minute range (ERR_VALIDATION_LIMIT, 422)
    if not (0 <= window_start_minute <= 1439):
        raise err(errors.ERR_VALIDATION_LIMIT, "window_start_minute out of range")
    if not (1 <= window_end_minute <= 1440):
        raise err(errors.ERR_VALIDATION_LIMIT, "window_end_minute out of range")
    # window ordering (ERR_INVALID_REQUEST, 400)
    if window_end_minute <= window_start_minute:
        raise err(errors.ERR_INVALID_REQUEST, "window_end_minute must exceed window_start_minute")

    booking_date = _utc_date(window_date)
    if booking_date is None:
        raise err(errors.ERR_INVALID_REQUEST, "window_date must be a valid ISO 8601 instant")

    # window overlap (priority 12)
    for da in db.dispatch_assignments.values():
        if (da["electrician_id"] == electrician_id
                and da["status"] != "CANCELLED"
                and _utc_date(da["window_date"]) == booking_date):
            if (window_start_minute < da["window_end_minute"]
                    and da["window_start_minute"] < window_end_minute):
                raise err(errors.ERR_WINDOW_OVERLAP, "window overlaps an existing assignment")

    # daily capacity (priority 13): count BOOKED+EN_ROUTE on same date, strict <
    day_count = 0
    for da in db.dispatch_assignments.values():
        if (da["electrician_id"] == electrician_id
                and da["status"] in ("BOOKED", "EN_ROUTE")
                and _utc_date(da["window_date"]) == booking_date):
            day_count += 1
    if day_count >= electrician["max_daily_jobs"]:
        raise err(errors.ERR_DAILY_CAPACITY_EXCEEDED, "electrician at daily capacity")

    rec = base_fields()
    rec.update({
        "install_job_id": install_job_id,
        "electrician_id": electrician_id,
        "window_date": window_date,
        "window_start_minute": window_start_minute,
        "window_end_minute": window_end_minute,
        "status": "BOOKED",
    })
    db.dispatch_assignments[rec["id"]] = rec

    job["workflow_status"] = "SCHEDULED"
    db.touch(job)
    return success(S.dispatch_assignment(rec), status=201)


@app.route("/dispatch-assignments/<did>", methods=["GET"])
def get_dispatch_assignment(did):
    require_auth({"Coordinator", "Electrician"})
    ent = get_or_404(db.dispatch_assignments, did, "dispatch assignment not found")
    return success(S.dispatch_assignment(ent))


@app.route("/dispatch-assignments", methods=["GET"])
def list_dispatch_assignments():
    require_auth({"Coordinator", "Electrician"})
    install_job_id = request.args.get("install_job_id")
    electrician_id = request.args.get("electrician_id")
    items = list(db.dispatch_assignments.values())
    if install_job_id is not None:
        items = [d for d in items if d["install_job_id"] == install_job_id]
    if electrician_id is not None:
        items = [d for d in items if d["electrician_id"] == electrician_id]
    page, limit, offset, total = services.paginate(items)
    return list_response([S.dispatch_assignment(d) for d in page], limit, offset, total)


@app.route("/dispatch-assignments/<did>/depart", methods=["POST"])
def depart_dispatch(did):
    user_id, role = require_auth({"Electrician"})
    da = get_or_404(db.dispatch_assignments, did, "dispatch assignment not found")
    # ownership (priority 5)
    if da["electrician_id"] != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the assigned electrician")
    if da["status"] != "BOOKED":
        raise err(errors.ERR_INVALID_STATE, "assignment is not BOOKED")
    da["status"] = "EN_ROUTE"
    db.touch(da)
    return success(S.dispatch_assignment(da))


@app.route("/dispatch-assignments/<did>/complete", methods=["POST"])
def complete_dispatch(did):
    user_id, role = require_auth({"Electrician"})
    da = get_or_404(db.dispatch_assignments, did, "dispatch assignment not found")
    job = db.install_jobs.get(da["install_job_id"])
    # ownership (priority 5)
    if da["electrician_id"] != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the assigned electrician")
    # state (priority 6)
    if da["status"] != "EN_ROUTE":
        raise err(errors.ERR_INVALID_STATE, "assignment is not EN_ROUTE")
    if job is None or job["workflow_status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "job is not SCHEDULED")
    # compliance gate (priority 8)
    if job["compliance_status"] != "CLEARED":
        raise err(errors.ERR_COMPLIANCE_NOT_CLEARED, "compliance is not CLEARED")

    da["status"] = "COMPLETED"
    db.touch(da)

    job["activation_pairing_code"] = _mint_pairing_code()
    job["workflow_status"] = "INSTALLED"
    db.touch(job)
    return success(S.dispatch_assignment(da))


def _mint_pairing_code():
    import random
    import string
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


@app.route("/dispatch-assignments/<did>/cancel", methods=["POST"])
def cancel_dispatch(did):
    require_auth({"Coordinator"})
    da = get_or_404(db.dispatch_assignments, did, "dispatch assignment not found")
    if da["status"] != "BOOKED":
        raise err(errors.ERR_INVALID_STATE, "assignment is not BOOKED")
    da["status"] = "CANCELLED"
    db.touch(da)
    job = db.install_jobs.get(da["install_job_id"])
    if job is not None and job["workflow_status"] == "SCHEDULED":
        job["workflow_status"] = "QUOTED"
        db.touch(job)
    return success(S.dispatch_assignment(da))


# ---------------------------------------------------------------------------
# IncentiveClaim
# ---------------------------------------------------------------------------
def _fed_existing_award(install_job_id):
    """award_cents of this job's FEDERAL_45W claim in {SUBMITTED, PAID}, earliest
    by created_at; else 0."""
    candidates = [
        c for c in db.incentive_claims.values()
        if c["install_job_id"] == install_job_id
        and c["program_kind"] == "FEDERAL_45W"
        and c["status"] in ("SUBMITTED", "PAID")
    ]
    if not candidates:
        return 0
    candidates.sort(key=lambda c: (c["created_at"], c["id"]))
    return candidates[0]["award_cents"]


@app.route("/incentive-claims", methods=["POST"])
def create_incentive_claim():
    require_auth({"Coordinator"})
    body = V.get_body()
    install_job_id = V.require_str(body, "install_job_id")
    program_kind = V.require_enum(body, "program_kind", {"FEDERAL_45W", "UTILITY_REBATE"})
    eligible_cost_cents = V.require_int(body, "eligible_cost_cents")
    utility_program_tier = V.opt_enum(body, "utility_program_tier", {"BASIC", "PREMIUM"}, "BASIC")
    includes_panel_upgrade = V.opt_bool(body, "includes_panel_upgrade", False)

    job = fk_or_404(db.install_jobs, install_job_id, "install job not found")

    if eligible_cost_cents < 0:
        raise err(errors.ERR_INVALID_REQUEST, "eligible_cost_cents must be non-negative")

    # job must be ACTIVATED or CLOSED (gate applied at creation)
    if job["workflow_status"] not in ("ACTIVATED", "CLOSED"):
        raise err(errors.ERR_JOB_NOT_ACTIVATED, "job is not ACTIVATED/CLOSED")

    fed_existing = _fed_existing_award(install_job_id)
    award = calc.incentive_award(program_kind, eligible_cost_cents, utility_program_tier,
                                 includes_panel_upgrade, fed_existing)

    # fully-absorbed check: a UTILITY_REBATE claim clamped to 0 is non-fundable
    if program_kind == "UTILITY_REBATE" and award == 0:
        raise err(errors.ERR_INCENTIVE_FULLY_ABSORBED, "utility award fully absorbed")

    rec = base_fields()
    rec.update({
        "install_job_id": install_job_id,
        "program_kind": program_kind,
        "eligible_cost_cents": eligible_cost_cents,
        "utility_program_tier": utility_program_tier,
        "includes_panel_upgrade": includes_panel_upgrade,
        "award_cents": award,
        "status": "DRAFT",
    })
    db.incentive_claims[rec["id"]] = rec
    return success(S.incentive_claim(rec), status=201)


def _refresh_incentive(c):
    fed_existing = _fed_existing_award(c["install_job_id"])
    # exclude self when this is itself a federal claim (self never counts as fed_existing
    # against itself since federal branch ignores fed_existing).
    c["award_cents"] = calc.incentive_award(
        c["program_kind"], c["eligible_cost_cents"], c["utility_program_tier"],
        c["includes_panel_upgrade"], fed_existing)


@app.route("/incentive-claims/<cid>", methods=["GET"])
def get_incentive_claim(cid):
    require_auth({"Coordinator"})
    ent = get_or_404(db.incentive_claims, cid, "incentive claim not found")
    _refresh_incentive(ent)
    return success(S.incentive_claim(ent))


@app.route("/incentive-claims", methods=["GET"])
def list_incentive_claims():
    require_auth({"Coordinator"})
    install_job_id = request.args.get("install_job_id")
    items = list(db.incentive_claims.values())
    if install_job_id is not None:
        items = [c for c in items if c["install_job_id"] == install_job_id]
    for c in items:
        _refresh_incentive(c)
    page, limit, offset, total = services.paginate(items)
    return list_response([S.incentive_claim(c) for c in page], limit, offset, total)


@app.route("/incentive-claims/<cid>/submit", methods=["POST"])
def submit_incentive_claim(cid):
    require_auth({"Coordinator"})
    claim = get_or_404(db.incentive_claims, cid, "incentive claim not found")
    if claim["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "claim is not DRAFT")
    job = db.install_jobs.get(claim["install_job_id"])
    if job is None or job["workflow_status"] not in ("ACTIVATED", "CLOSED"):
        raise err(errors.ERR_JOB_NOT_ACTIVATED, "job is not ACTIVATED/CLOSED")
    claim["status"] = "SUBMITTED"
    db.touch(claim)
    return success(S.incentive_claim(claim))


@app.route("/incentive-claims/<cid>/pay", methods=["POST"])
def pay_incentive_claim(cid):
    require_auth({"Coordinator"})
    claim = get_or_404(db.incentive_claims, cid, "incentive claim not found")
    if claim["status"] != "SUBMITTED":
        raise err(errors.ERR_INVALID_STATE, "claim is not SUBMITTED")
    claim["status"] = "PAID"
    db.touch(claim)
    return success(S.incentive_claim(claim))


@app.route("/incentive-claims/<cid>/reverse", methods=["POST"])
def reverse_incentive_claim(cid):
    require_auth({"Coordinator"})
    claim = get_or_404(db.incentive_claims, cid, "incentive claim not found")
    if claim["status"] != "PAID":
        raise err(errors.ERR_INVALID_STATE, "claim is not PAID")
    claim["status"] = "REVERSED"
    db.touch(claim)
    return success(S.incentive_claim(claim))


# ---------------------------------------------------------------------------
# PanelUpgradeReferral
# ---------------------------------------------------------------------------
@app.route("/panel-upgrade-referrals/<rid>", methods=["GET"])
def get_panel_referral(rid):
    require_auth({"Coordinator", "Homeowner"})
    ent = get_or_404(db.panel_upgrade_referrals, rid, "panel-upgrade referral not found")
    return success(S.panel_upgrade_referral(ent))


@app.route("/panel-upgrade-referrals", methods=["GET"])
def list_panel_referrals():
    require_auth({"Coordinator", "Homeowner"})
    install_job_id = request.args.get("install_job_id")
    items = list(db.panel_upgrade_referrals.values())
    if install_job_id is not None:
        items = [r for r in items if r["install_job_id"] == install_job_id]
    page, limit, offset, total = services.paginate(items)
    return list_response([S.panel_upgrade_referral(r) for r in page], limit, offset, total)


@app.route("/panel-upgrade-referrals/<rid>/accept", methods=["POST"])
def accept_panel_referral(rid):
    require_auth({"Homeowner"})
    ref = get_or_404(db.panel_upgrade_referrals, rid, "panel-upgrade referral not found")
    if ref["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "referral is not OPEN")
    ref["status"] = "ACCEPTED"
    db.touch(ref)
    return success(S.panel_upgrade_referral(ref))


@app.route("/panel-upgrade-referrals/<rid>/decline", methods=["POST"])
def decline_panel_referral(rid):
    require_auth({"Homeowner"})
    ref = get_or_404(db.panel_upgrade_referrals, rid, "panel-upgrade referral not found")
    if ref["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "referral is not OPEN")
    ref["status"] = "DECLINED"
    db.touch(ref)
    return success(S.panel_upgrade_referral(ref))


@app.route("/panel-upgrade-referrals/<rid>/complete", methods=["POST"])
def complete_panel_referral(rid):
    require_auth({"Coordinator"})
    ref = get_or_404(db.panel_upgrade_referrals, rid, "panel-upgrade referral not found")
    job = db.install_jobs.get(ref["install_job_id"])
    if ref["status"] != "ACCEPTED":
        raise err(errors.ERR_INVALID_STATE, "referral is not ACCEPTED")
    if job is None or job["compliance_status"] != "BLOCKED":
        raise err(errors.ERR_INVALID_STATE, "job compliance is not BLOCKED")

    ref["status"] = "COMPLETED"
    db.touch(ref)

    prop = db.properties.get(job["property_id"])
    if prop is not None:
        prop["main_breaker_amps"] = ref["recommended_main_amps"]
        db.touch(prop)

    job["requires_panel_upgrade"] = False
    job["compliance_status"] = "PENDING_REVIEW"
    db.touch(job)
    return success(S.panel_upgrade_referral(ref))


# ---------------------------------------------------------------------------
# WarrantyTicket
# ---------------------------------------------------------------------------
@app.route("/warranty-tickets", methods=["POST"])
def create_warranty_ticket():
    user_id, role = require_auth({"Homeowner"})
    body = V.get_body()
    install_job_id = V.require_str(body, "install_job_id")
    summary = V.require_str(body, "summary")

    job = fk_or_404(db.install_jobs, install_job_id, "install job not found")

    # ownership (priority 5)
    if not services.homeowner_owns_job(user_id, job):
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the owner of this job")
    # job activated/closed gate
    if job["workflow_status"] not in ("ACTIVATED", "CLOSED"):
        raise err(errors.ERR_JOB_NOT_ACTIVATED, "job is not ACTIVATED/CLOSED")

    rec = base_fields()
    rec.update({
        "install_job_id": install_job_id,
        "summary": summary,
        "reopen_count": 0,
        "status": "OPEN",
    })
    db.warranty_tickets[rec["id"]] = rec
    return success(S.warranty_ticket(rec), status=201)


@app.route("/warranty-tickets/<wid>", methods=["GET"])
def get_warranty_ticket(wid):
    require_auth({"Homeowner", "Coordinator", "Electrician"})
    ent = get_or_404(db.warranty_tickets, wid, "warranty ticket not found")
    return success(S.warranty_ticket(ent))


@app.route("/warranty-tickets", methods=["GET"])
def list_warranty_tickets():
    require_auth({"Homeowner", "Coordinator", "Electrician"})
    install_job_id = request.args.get("install_job_id")
    items = list(db.warranty_tickets.values())
    if install_job_id is not None:
        items = [w for w in items if w["install_job_id"] == install_job_id]
    page, limit, offset, total = services.paginate(items)
    return list_response([S.warranty_ticket(w) for w in page], limit, offset, total)


@app.route("/warranty-tickets/<wid>/diagnose", methods=["POST"])
def diagnose_warranty(wid):
    require_auth({"Electrician"})
    wt = get_or_404(db.warranty_tickets, wid, "warranty ticket not found")
    if wt["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "ticket is not OPEN")
    job = db.install_jobs.get(wt["install_job_id"])
    if job is None or job["workflow_status"] not in ("ACTIVATED", "CLOSED"):
        raise err(errors.ERR_INVALID_STATE, "job is not ACTIVATED/CLOSED")
    wt["status"] = "DIAGNOSING"
    db.touch(wt)
    return success(S.warranty_ticket(wt))


@app.route("/warranty-tickets/<wid>/order-parts", methods=["POST"])
def order_parts_warranty(wid):
    require_auth({"Electrician"})
    wt = get_or_404(db.warranty_tickets, wid, "warranty ticket not found")
    if wt["status"] != "DIAGNOSING":
        raise err(errors.ERR_INVALID_STATE, "ticket is not DIAGNOSING")
    wt["status"] = "AWAITING_PARTS"
    db.touch(wt)
    return success(S.warranty_ticket(wt))


@app.route("/warranty-tickets/<wid>/parts-received", methods=["POST"])
def parts_received_warranty(wid):
    require_auth({"Electrician"})
    wt = get_or_404(db.warranty_tickets, wid, "warranty ticket not found")
    if wt["status"] != "AWAITING_PARTS":
        raise err(errors.ERR_INVALID_STATE, "ticket is not AWAITING_PARTS")
    wt["status"] = "DIAGNOSING"
    db.touch(wt)
    return success(S.warranty_ticket(wt))


@app.route("/warranty-tickets/<wid>/resolve", methods=["POST"])
def resolve_warranty(wid):
    require_auth({"Electrician"})
    wt = get_or_404(db.warranty_tickets, wid, "warranty ticket not found")
    if wt["status"] != "DIAGNOSING":
        raise err(errors.ERR_INVALID_STATE, "ticket is not DIAGNOSING")
    wt["status"] = "RESOLVED"
    db.touch(wt)
    return success(S.warranty_ticket(wt))


@app.route("/warranty-tickets/<wid>/reopen", methods=["POST"])
def reopen_warranty(wid):
    require_auth({"Homeowner"})
    wt = get_or_404(db.warranty_tickets, wid, "warranty ticket not found")
    if wt["status"] != "RESOLVED":
        raise err(errors.ERR_INVALID_STATE, "ticket is not RESOLVED")
    if wt["reopen_count"] >= 2:
        raise err(errors.ERR_REOPEN_LIMIT_REACHED, "reopen limit reached")
    wt["reopen_count"] += 1
    wt["status"] = "OPEN"
    db.touch(wt)
    return success(S.warranty_ticket(wt))


@app.route("/warranty-tickets/<wid>/close", methods=["POST"])
def close_warranty(wid):
    require_auth({"Coordinator"})
    wt = get_or_404(db.warranty_tickets, wid, "warranty ticket not found")
    if wt["status"] != "RESOLVED":
        raise err(errors.ERR_INVALID_STATE, "ticket is not RESOLVED")
    wt["status"] = "CLOSED"
    db.touch(wt)
    return success(S.warranty_ticket(wt))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
