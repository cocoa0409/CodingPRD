"""Private Well Permit & Water Testing API — Flask entry point.

Storage is in-memory only (see store.py); every boot starts empty.
"""
import os
from functools import wraps

from flask import Flask, request

from store import (
    store, PERMIT_VALIDITY_DAYS, DRILL_TRAVEL_BUFFER_HOURS,
    REAL_ESTATE_TEST_VALIDITY_DAYS,
)
from helpers import (
    ApiError, authenticate, authorize, success, error_response,
    get_body, require, require_str, require_enum, require_int, require_number,
    optional_bool, parse_dt, paginate, filter_rows,
)
from models import base_common, touch, serialize
from calc import (
    permit_fee, panel_fee, compute_result_grades, recompute_potability,
    set_potability_direct, recompute_net_fees, recompute_advisory_count,
    OPEN_CASE_STATES,
)
from datetime import timedelta

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(_e):
    return error_response(ApiError("ERR_VALIDATION", "Not found"))


@app.errorhandler(405)
def _handle_405(_e):
    return error_response(ApiError("ERR_VALIDATION", "Method not allowed"))


def endpoint(roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(**kwargs):
            ctx = authenticate()
            authorize(ctx, roles)
            return fn(ctx, **kwargs)
        return wrapper
    return deco


def get_or_404(collection, rid, err):
    rec = collection.get(rid)
    if rec is None:
        raise ApiError(err)
    return rec


# ===========================================================================
# Aquifers
# ===========================================================================
@app.route("/aquifers", methods=["POST"])
@endpoint(["HealthOfficer"])
def create_aquifer(ctx):
    body = get_body()
    name = require_str(body, "name")
    sensitivity = require_enum(body, "sensitivity", {"HIGH", "MODERATE", "LOW"})
    septic = require_int(body, "min_setback_septic_ft")
    prop = require_int(body, "min_setback_property_line_ft")
    depth = require_int(body, "min_well_depth_ft")
    rec = base_common(versioned=False)
    rec.update({
        "name": name,
        "sensitivity": sensitivity,
        "min_setback_septic_ft": septic,
        "min_setback_property_line_ft": prop,
        "min_well_depth_ft": depth,
    })
    store.aquifers[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/aquifers/<rid>", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def get_aquifer(ctx, rid):
    rec = get_or_404(store.aquifers, rid, "ERR_AQUIFER_NOT_FOUND")
    return success(serialize(rec))


# ===========================================================================
# Applicants
# ===========================================================================
@app.route("/applicants", methods=["POST"])
@endpoint(["HealthOfficer"])
def create_applicant(ctx):
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    mailing_state = require_str(body, "mailing_state")
    rec = base_common()
    rec.update({
        "full_name": full_name,
        "email": email,
        "mailing_state": mailing_state,
        "net_fees_paid_cents": 0,
    })
    store.applicants[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/applicants/<rid>", methods=["GET"])
@endpoint(["Applicant", "HealthOfficer"])
def get_applicant(ctx, rid):
    rec = get_or_404(store.applicants, rid, "ERR_APPLICANT_NOT_FOUND")
    if ctx.role == "Applicant" and ctx.user_id != rec["id"]:
        raise ApiError("ERR_UNAUTHORIZED", "Applicants may only fetch their own record")
    return success(serialize(rec))


# ===========================================================================
# Drillers
# ===========================================================================
@app.route("/drillers", methods=["POST"])
@endpoint(["HealthOfficer"])
def create_driller(ctx):
    body = get_body()
    license_number = require_str(body, "license_number")
    license_state = require_str(body, "license_state")
    license_expires_on = parse_dt(require(body, "license_expires_on"))
    rec = base_common()
    rec.update({
        "license_number": license_number,
        "license_state": license_state,
        "license_expires_on": license_expires_on,
        "status": "ACTIVE",
    })
    store.drillers[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/drillers/<rid>", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def get_driller(ctx, rid):
    rec = get_or_404(store.drillers, rid, "ERR_DRILLER_NOT_FOUND")
    return success(serialize(rec))


@app.route("/drillers/<rid>/suspend", methods=["POST"])
@endpoint(["HealthOfficer"])
def suspend_driller(ctx, rid):
    rec = get_or_404(store.drillers, rid, "ERR_DRILLER_NOT_FOUND")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(serialize(rec))


# ===========================================================================
# Wells
# ===========================================================================
@app.route("/wells", methods=["POST"])
@endpoint(["Applicant"])
def create_well(ctx):
    body = get_body()
    applicant_id = require_str(body, "applicant_id")
    aquifer_id = require_str(body, "aquifer_id")
    latitude = require_number(body, "latitude")
    longitude = require_number(body, "longitude")
    parcel_apn = require_str(body, "parcel_apn")
    intended_use = require_enum(body, "intended_use", {"DOMESTIC", "IRRIGATION", "LIVESTOCK"})
    get_or_404(store.applicants, applicant_id, "ERR_APPLICANT_NOT_FOUND")
    get_or_404(store.aquifers, aquifer_id, "ERR_AQUIFER_NOT_FOUND")
    rec = base_common()
    rec.update({
        "applicant_id": applicant_id,
        "aquifer_id": aquifer_id,
        "latitude": latitude,
        "longitude": longitude,
        "parcel_apn": parcel_apn,
        "intended_use": intended_use,
        "registry_status": "PROPOSED",
        "potability_status": "UNKNOWN",
        "depth_ft": None,
        "active_advisory_count": 0,
    })
    store.wells[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/wells/<rid>", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def get_well(ctx, rid):
    rec = get_or_404(store.wells, rid, "ERR_WELL_NOT_FOUND")
    return success(serialize(rec))


@app.route("/wells", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def list_wells(ctx):
    rows = filter_rows(store.wells, {
        "applicant_id": "applicant_id",
        "aquifer_id": "aquifer_id",
        "registry_status": "registry_status",
        "potability_status": "potability_status",
    })
    return paginate(rows, serialize)


@app.route("/wells/<rid>/deactivate", methods=["POST"])
@endpoint(["HealthOfficer"])
def deactivate_well(ctx, rid):
    rec = get_or_404(store.wells, rid, "ERR_WELL_NOT_FOUND")
    if rec["registry_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Well is not ACTIVE")
    rec["registry_status"] = "INACTIVE"
    touch(rec)
    return success(serialize(rec))


@app.route("/wells/<rid>/reactivate", methods=["POST"])
@endpoint(["HealthOfficer"])
def reactivate_well(ctx, rid):
    rec = get_or_404(store.wells, rid, "ERR_WELL_NOT_FOUND")
    if rec["registry_status"] != "INACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Well is not INACTIVE")
    rec["registry_status"] = "ACTIVE"
    touch(rec)
    return success(serialize(rec))


# ===========================================================================
# Construction Permits
# ===========================================================================
@app.route("/construction-permits", methods=["POST"])
@endpoint(["Applicant"])
def create_construction_permit(ctx):
    body = get_body()
    well_id = require_str(body, "well_id")
    applicant_id = require_str(body, "applicant_id")
    driller_id = require_str(body, "driller_id")
    proposed_depth_ft = require_int(body, "proposed_depth_ft")
    setback_septic_ft = require_int(body, "setback_septic_ft")
    setback_property_line_ft = require_int(body, "setback_property_line_ft")
    scheduled_start = parse_dt(require(body, "scheduled_start"))
    scheduled_end = parse_dt(require(body, "scheduled_end"))
    expedite = optional_bool(body, "expedite", False)
    if scheduled_end <= scheduled_start:
        raise ApiError("ERR_VALIDATION", "scheduled_end must be strictly after scheduled_start")
    # existence (left-to-right in body order)
    well = get_or_404(store.wells, well_id, "ERR_WELL_NOT_FOUND")
    get_or_404(store.applicants, applicant_id, "ERR_APPLICANT_NOT_FOUND")
    get_or_404(store.drillers, driller_id, "ERR_DRILLER_NOT_FOUND")
    # referential
    if applicant_id != well["applicant_id"]:
        raise ApiError("ERR_APPLICANT_MISMATCH", "applicant_id does not match the well owner")
    aquifer = store.aquifers[well["aquifer_id"]]
    fee_est = permit_fee(proposed_depth_ft, well["intended_use"], aquifer["sensitivity"], expedite)
    rec = base_common()
    rec.update({
        "well_id": well_id,
        "applicant_id": applicant_id,
        "driller_id": driller_id,
        "proposed_depth_ft": proposed_depth_ft,
        "setback_septic_ft": setback_septic_ft,
        "setback_property_line_ft": setback_property_line_ft,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "expedite": expedite,
        "fee_estimate_cents": fee_est,
        "fee_final_cents": None,
        "fee_charged_cents": 0,
        "fee_refunded_cents": 0,
        "fee_paid": False,
        "issued_on": None,
        "expires_on": None,
        "status": "SUBMITTED",
    })
    store.construction_permits[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/construction-permits/<rid>", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def get_construction_permit(ctx, rid):
    rec = get_or_404(store.construction_permits, rid, "ERR_PERMIT_NOT_FOUND")
    return success(serialize(rec))


@app.route("/construction-permits", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def list_construction_permits(ctx):
    rows = filter_rows(store.construction_permits, {
        "well_id": "well_id",
        "applicant_id": "applicant_id",
        "driller_id": "driller_id",
        "status": "status",
    })
    return paginate(rows, serialize)


@app.route("/construction-permits/<rid>/pay", methods=["POST"])
@endpoint(["Applicant"])
def pay_construction_permit(ctx, rid):
    rec = get_or_404(store.construction_permits, rid, "ERR_PERMIT_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Permit is not SUBMITTED")
    rec["fee_paid"] = True
    rec["fee_charged_cents"] = rec["fee_estimate_cents"]
    touch(rec)
    recompute_net_fees(store.applicants[rec["applicant_id"]])
    return success(serialize(rec))


@app.route("/construction-permits/<rid>/approve", methods=["POST"])
@endpoint(["HealthOfficer"])
def approve_construction_permit(ctx, rid):
    rec = get_or_404(store.construction_permits, rid, "ERR_PERMIT_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Permit is not SUBMITTED")
    well = store.wells[rec["well_id"]]
    aquifer = store.aquifers[well["aquifer_id"]]
    if rec["setback_septic_ft"] < aquifer["min_setback_septic_ft"] or \
            rec["setback_property_line_ft"] < aquifer["min_setback_property_line_ft"]:
        raise ApiError("ERR_SETBACK_VIOLATION", "Setback below aquifer minimum")
    if not rec["fee_paid"]:
        raise ApiError("ERR_FEE_UNPAID", "Permit fee has not been paid")
    rec["status"] = "APPROVED"
    touch(rec)
    return success(serialize(rec))


@app.route("/construction-permits/<rid>/deny", methods=["POST"])
@endpoint(["HealthOfficer"])
def deny_construction_permit(ctx, rid):
    rec = get_or_404(store.construction_permits, rid, "ERR_PERMIT_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Permit is not SUBMITTED")
    rec["status"] = "DENIED"
    if rec["fee_paid"]:
        rec["fee_refunded_cents"] = rec["fee_charged_cents"]
    touch(rec)
    recompute_net_fees(store.applicants[rec["applicant_id"]])
    return success(serialize(rec))


def _buffered_overlap(a_start, a_end, b_start, b_end):
    buf = timedelta(hours=DRILL_TRAVEL_BUFFER_HOURS)
    bs = b_start - buf
    be = b_end + buf
    # half-open [a_start, a_end) vs expanded other [bs, be)
    return a_start < be and bs < a_end


@app.route("/construction-permits/<rid>/issue", methods=["POST"])
@endpoint(["HealthOfficer"])
def issue_construction_permit(ctx, rid):
    rec = get_or_404(store.construction_permits, rid, "ERR_PERMIT_NOT_FOUND")
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Permit is not APPROVED")
    for other in store.construction_permits.values():
        if other["id"] == rec["id"]:
            continue
        if other["driller_id"] != rec["driller_id"]:
            continue
        if other["status"] not in ("ISSUED", "COMPLETED"):
            continue
        if _buffered_overlap(rec["scheduled_start"], rec["scheduled_end"],
                             other["scheduled_start"], other["scheduled_end"]):
            raise ApiError("ERR_DRILLER_SCHEDULE_CONFLICT", "Driller window conflict")
    now = store.now()
    rec["status"] = "ISSUED"
    rec["issued_on"] = now
    rec["expires_on"] = now + timedelta(days=PERMIT_VALIDITY_DAYS)
    touch(rec)
    well = store.wells[rec["well_id"]]
    if well["registry_status"] == "PROPOSED":
        well["registry_status"] = "PERMITTED"
        touch(well)
    return success(serialize(rec))


# ===========================================================================
# Driller Logs
# ===========================================================================
@app.route("/driller-logs", methods=["POST"])
@endpoint(["Driller"])
def create_driller_log(ctx):
    body = get_body()
    construction_permit_id = require_str(body, "construction_permit_id")
    driller_id = require_str(body, "driller_id")
    total_depth_ft = require_int(body, "total_depth_ft")
    static_water_level_ft = require_int(body, "static_water_level_ft")
    casing_depth_ft = require_int(body, "casing_depth_ft")
    grout_type = require_enum(body, "grout_type", {"BENTONITE", "CEMENT", "NEAT_CEMENT"})
    completed_on = parse_dt(require(body, "completed_on"))
    permit = get_or_404(store.construction_permits, construction_permit_id, "ERR_PERMIT_NOT_FOUND")
    driller = get_or_404(store.drillers, driller_id, "ERR_DRILLER_NOT_FOUND")
    if permit["status"] != "ISSUED":
        raise ApiError("ERR_PERMIT_NOT_ISSUED", "Construction permit is not ISSUED")
    if driller["status"] != "ACTIVE" or completed_on >= driller["license_expires_on"]:
        raise ApiError("ERR_DRILLER_LICENSE_INVALID", "Driller license invalid")
    if driller_id != permit["driller_id"]:
        raise ApiError("ERR_DRILLER_NOT_ASSIGNED", "Driller is not assigned to this permit")
    rec = base_common()
    rec.update({
        "construction_permit_id": construction_permit_id,
        "driller_id": driller_id,
        "total_depth_ft": total_depth_ft,
        "static_water_level_ft": static_water_level_ft,
        "casing_depth_ft": casing_depth_ft,
        "grout_type": grout_type,
        "completed_on": completed_on,
    })
    store.driller_logs[rec["id"]] = rec
    # cascade: complete permit, finalize fee, activate well
    well = store.wells[permit["well_id"]]
    aquifer = store.aquifers[well["aquifer_id"]]
    fee_final = permit_fee(total_depth_ft, well["intended_use"], aquifer["sensitivity"], permit["expedite"])
    permit["status"] = "COMPLETED"
    permit["fee_final_cents"] = fee_final
    permit["fee_charged_cents"] = fee_final
    touch(permit)
    recompute_net_fees(store.applicants[permit["applicant_id"]])
    well["depth_ft"] = total_depth_ft
    if well["registry_status"] == "PERMITTED":
        well["registry_status"] = "ACTIVE"
    touch(well)
    return success(serialize(rec), status=201)


@app.route("/driller-logs/<rid>", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def get_driller_log(ctx, rid):
    rec = get_or_404(store.driller_logs, rid, "ERR_DRILLER_LOG_NOT_FOUND")
    return success(serialize(rec))


@app.route("/driller-logs", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def list_driller_logs(ctx):
    rows = filter_rows(store.driller_logs, {
        "construction_permit_id": "construction_permit_id",
        "driller_id": "driller_id",
    })
    return paginate(rows, serialize)


ANALYTES = {"BACTERIA", "NITRATE", "LEAD"}
BAC_ENUM = {"PRESENT", "ABSENT", "NOT_TESTED"}


def _validate_analytes(value):
    if not isinstance(value, list) or len(value) == 0:
        raise ApiError("ERR_VALIDATION", "requested_analytes must be a non-empty list")
    for a in value:
        if a not in ANALYTES:
            raise ApiError("ERR_VALIDATION", "requested_analytes must be a subset of BACTERIA, NITRATE, LEAD")
    return value


# ===========================================================================
# Water Samples
# ===========================================================================
@app.route("/water-samples", methods=["POST"])
@endpoint(["Applicant"])
def create_water_sample(ctx):
    body = get_body()
    well_id = require_str(body, "well_id")
    submitted_by_applicant_id = require_str(body, "submitted_by_applicant_id")
    sample_type = require_enum(body, "sample_type",
                               {"ROUTINE", "REAL_ESTATE", "CONTAMINATION_FOLLOWUP"})
    requested_analytes = _validate_analytes(require(body, "requested_analytes"))
    collected_on = parse_dt(require(body, "collected_on"))
    chain_of_custody_id = require_str(body, "chain_of_custody_id")
    well = get_or_404(store.wells, well_id, "ERR_WELL_NOT_FOUND")
    get_or_404(store.applicants, submitted_by_applicant_id, "ERR_APPLICANT_NOT_FOUND")
    if well["registry_status"] != "ACTIVE":
        raise ApiError("ERR_WELL_NOT_ACTIVE", "Well is not ACTIVE")
    rec = base_common()
    rec.update({
        "well_id": well_id,
        "submitted_by_applicant_id": submitted_by_applicant_id,
        "sample_type": sample_type,
        "requested_analytes": requested_analytes,
        "collected_on": collected_on,
        "chain_of_custody_id": chain_of_custody_id,
        "panel_fee_cents": panel_fee(requested_analytes),
        "status": "SUBMITTED",
    })
    store.water_samples[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/water-samples/<rid>", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def get_water_sample(ctx, rid):
    rec = get_or_404(store.water_samples, rid, "ERR_SAMPLE_NOT_FOUND")
    return success(serialize(rec))


@app.route("/water-samples", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def list_water_samples(ctx):
    rows = filter_rows(store.water_samples, {
        "well_id": "well_id",
        "submitted_by_applicant_id": "submitted_by_applicant_id",
        "status": "status",
        "sample_type": "sample_type",
    })
    return paginate(rows, serialize)


@app.route("/water-samples/<rid>/receive", methods=["POST"])
@endpoint(["LabAnalyst"])
def receive_water_sample(ctx, rid):
    rec = get_or_404(store.water_samples, rid, "ERR_SAMPLE_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Sample is not SUBMITTED")
    rec["status"] = "RECEIVED"
    touch(rec)
    return success(serialize(rec))


@app.route("/water-samples/<rid>/begin-analysis", methods=["POST"])
@endpoint(["LabAnalyst"])
def begin_analysis_water_sample(ctx, rid):
    rec = get_or_404(store.water_samples, rid, "ERR_SAMPLE_NOT_FOUND")
    if rec["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Sample is not RECEIVED")
    rec["status"] = "IN_ANALYSIS"
    touch(rec)
    return success(serialize(rec))


@app.route("/water-samples/<rid>/invalidate", methods=["POST"])
@endpoint(["HealthOfficer"])
def invalidate_water_sample(ctx, rid):
    rec = get_or_404(store.water_samples, rid, "ERR_SAMPLE_NOT_FOUND")
    if rec["status"] != "RESULTED":
        raise ApiError("ERR_INVALID_STATE", "Sample is not RESULTED")
    rec["status"] = "INVALIDATED"
    touch(rec)
    recompute_potability(store.wells[rec["well_id"]])
    return success(serialize(rec))


# ===========================================================================
# Sample Results (+ contamination cascade)
# ===========================================================================
@app.route("/sample-results", methods=["POST"])
@endpoint(["LabAnalyst"])
def create_sample_result(ctx):
    body = get_body()
    water_sample_id = require_str(body, "water_sample_id")
    bacteria_coliform = require_enum(body, "bacteria_coliform", BAC_ENUM)
    ecoli = require_enum(body, "ecoli", BAC_ENUM)
    nitrate_mg_l = require_number(body, "nitrate_mg_l")
    lead_ppb = require_number(body, "lead_ppb")
    analyzed_on = parse_dt(require(body, "analyzed_on"))
    # non-negativity (priority 26, before existence)
    if nitrate_mg_l < 0 or lead_ppb < 0:
        raise ApiError("ERR_ANALYTE_OUT_OF_RANGE", "Concentrations must be non-negative")
    sample = get_or_404(store.water_samples, water_sample_id, "ERR_SAMPLE_NOT_FOUND")
    if sample["status"] != "IN_ANALYSIS":
        raise ApiError("ERR_INVALID_STATE", "Sample is not IN_ANALYSIS")
    well = store.wells[sample["well_id"]]
    rec = base_common(versioned=False)
    rec.update({
        "water_sample_id": water_sample_id,
        "bacteria_coliform": bacteria_coliform,
        "ecoli": ecoli,
        "nitrate_mg_l": nitrate_mg_l,
        "lead_ppb": lead_ppb,
        "analyzed_on": analyzed_on,
        "advisory_level_provisional": None,
        "advisory_level_confirmed": None,
        "exceedances": [],
    })
    store.sample_results[rec["id"]] = rec
    sample["status"] = "RESULTED"
    touch(sample)
    confirmed = compute_result_grades(rec, well["id"])
    # potability recomputed from THIS result's confirmed grade (PRD §3.5)
    set_potability_direct(well, {"SAFE": "POTABLE", "ADVISORY": "ADVISORY", "UNSAFE": "UNSAFE"}[confirmed])
    if confirmed == "UNSAFE":
        _auto_open_case(well, sample["id"])
    return success(serialize(rec), status=201)


def _auto_open_case(well, sample_id):
    now = store.now()
    case = base_common()
    case.update({
        "well_id": well["id"],
        "source_sample_id": sample_id,
        "severity": "HIGH",
        "opened_by_officer_id": None,
        "closed_by_officer_id": None,
        "resolution_notes": None,
        "status": "OPEN",
    })
    store.contamination_cases[case["id"]] = case
    # case entry side effects: potability UNSAFE, auto-issue advisory, bump count
    set_potability_direct(well, "UNSAFE")
    adv = base_common()
    adv.update({
        "well_id": well["id"],
        "source_case_id": case["id"],
        "advisory_type": "DO_NOT_DRINK",
        "effective_from": now,
        "effective_to": now + timedelta(days=365),
        "reason": "Auto-issued advisory: confirmed unsafe water sample result",
        "status": "ACTIVE",
    })
    store.advisories[adv["id"]] = adv
    recompute_advisory_count(well)
    return case


@app.route("/sample-results/<rid>", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def get_sample_result(ctx, rid):
    rec = get_or_404(store.sample_results, rid, "ERR_RESULT_NOT_FOUND")
    return success(serialize(rec))


@app.route("/sample-results", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def list_sample_results(ctx):
    rows = filter_rows(store.sample_results, {"water_sample_id": "water_sample_id"})
    return paginate(rows, serialize)


# ===========================================================================
# Advisories
# ===========================================================================
@app.route("/advisories", methods=["POST"])
@endpoint(["HealthOfficer"])
def create_advisory(ctx):
    body = get_body()
    well_id = require_str(body, "well_id")
    advisory_type = require_enum(body, "advisory_type",
                                 {"BOIL_WATER", "DO_NOT_DRINK", "NITRATE", "LEAD"})
    effective_from = parse_dt(require(body, "effective_from"))
    effective_to = parse_dt(require(body, "effective_to"))
    reason = require_str(body, "reason")
    if effective_to <= effective_from:
        raise ApiError("ERR_VALIDATION", "effective_to must be strictly after effective_from")
    well = get_or_404(store.wells, well_id, "ERR_WELL_NOT_FOUND")
    for adv in store.advisories.values():
        if adv["well_id"] != well_id or adv["status"] != "ACTIVE":
            continue
        if adv["advisory_type"] != advisory_type:
            continue
        # closed-interval overlap: each starts no later than the other ends
        if effective_from <= adv["effective_to"] and adv["effective_from"] <= effective_to:
            raise ApiError("ERR_ADVISORY_WINDOW_OVERLAP", "Overlapping active advisory of same type")
    rec = base_common()
    rec.update({
        "well_id": well_id,
        "source_case_id": None,
        "advisory_type": advisory_type,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "reason": reason,
        "status": "ACTIVE",
    })
    store.advisories[rec["id"]] = rec
    recompute_advisory_count(well)
    return success(serialize(rec), status=201)


@app.route("/advisories/<rid>", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def get_advisory(ctx, rid):
    rec = get_or_404(store.advisories, rid, "ERR_ADVISORY_NOT_FOUND")
    return success(serialize(rec))


@app.route("/advisories", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def list_advisories(ctx):
    rows = filter_rows(store.advisories, {
        "well_id": "well_id",
        "source_case_id": "source_case_id",
        "status": "status",
        "advisory_type": "advisory_type",
    })
    return paginate(rows, serialize)


@app.route("/advisories/<rid>/lift", methods=["POST"])
@endpoint(["HealthOfficer"])
def lift_advisory(ctx, rid):
    rec = get_or_404(store.advisories, rid, "ERR_ADVISORY_NOT_FOUND")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Advisory is not ACTIVE")
    rec["status"] = "LIFTED"
    touch(rec)
    recompute_advisory_count(store.wells[rec["well_id"]])
    return success(serialize(rec))


# ===========================================================================
# Contamination Cases
# ===========================================================================
@app.route("/contamination-cases", methods=["POST"])
@endpoint(["HealthOfficer"])
def create_contamination_case(ctx):
    body = get_body()
    well_id = require_str(body, "well_id")
    severity = require_enum(body, "severity", {"LOW", "MODERATE", "HIGH", "CRITICAL"})
    source_sample_id = body.get("source_sample_id")
    well = get_or_404(store.wells, well_id, "ERR_WELL_NOT_FOUND")
    if source_sample_id is not None:
        get_or_404(store.water_samples, source_sample_id, "ERR_SAMPLE_NOT_FOUND")
    rec = base_common()
    rec.update({
        "well_id": well_id,
        "source_sample_id": source_sample_id,
        "severity": severity,
        "opened_by_officer_id": ctx.user_id,
        "closed_by_officer_id": None,
        "resolution_notes": None,
        "status": "OPEN",
    })
    store.contamination_cases[rec["id"]] = rec
    set_potability_direct(well, "UNSAFE")
    return success(serialize(rec), status=201)


@app.route("/contamination-cases/<rid>", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def get_contamination_case(ctx, rid):
    rec = get_or_404(store.contamination_cases, rid, "ERR_CASE_NOT_FOUND")
    return success(serialize(rec))


@app.route("/contamination-cases", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def list_contamination_cases(ctx):
    rows = filter_rows(store.contamination_cases, {
        "well_id": "well_id",
        "source_sample_id": "source_sample_id",
        "status": "status",
    })
    return paginate(rows, serialize)


CASE_STATES = {"OPEN", "INVESTIGATING", "MITIGATION", "RESOLVED", "CLOSED"}
CASE_TRANSITIONS = {
    "OPEN": {"INVESTIGATING"},
    "INVESTIGATING": {"MITIGATION"},
    "MITIGATION": {"RESOLVED"},
    "RESOLVED": {"INVESTIGATING"},
}


@app.route("/contamination-cases/<rid>/transition", methods=["POST"])
@endpoint(["HealthOfficer"])
def transition_contamination_case(ctx, rid):
    body = get_body()
    to_status = require(body, "to_status")
    if to_status not in CASE_STATES:
        raise ApiError("ERR_VALIDATION", "Invalid to_status")
    rec = get_or_404(store.contamination_cases, rid, "ERR_CASE_NOT_FOUND")
    if to_status not in CASE_TRANSITIONS.get(rec["status"], set()):
        raise ApiError("ERR_INVALID_STATE", "Illegal case transition")
    rec["status"] = to_status
    touch(rec)
    return success(serialize(rec))


@app.route("/contamination-cases/<rid>/close", methods=["POST"])
@endpoint(["HealthOfficer"])
def close_contamination_case(ctx, rid):
    body = get_body()
    resolution_notes = body.get("resolution_notes")
    rec = get_or_404(store.contamination_cases, rid, "ERR_CASE_NOT_FOUND")
    if rec["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", "Case is not RESOLVED")
    if ctx.user_id == rec["opened_by_officer_id"]:
        raise ApiError("ERR_SELF_CLOSE_FORBIDDEN", "Closing officer must differ from opening officer")
    rec["status"] = "CLOSED"
    rec["closed_by_officer_id"] = ctx.user_id
    if resolution_notes is not None:
        rec["resolution_notes"] = resolution_notes
    touch(rec)
    well = store.wells[rec["well_id"]]
    for adv in store.advisories.values():
        if adv["source_case_id"] == rec["id"] and adv["status"] == "ACTIVE":
            adv["status"] = "LIFTED"
            touch(adv)
    recompute_advisory_count(well)
    recompute_potability(well)
    return success(serialize(rec))


# ===========================================================================
# Abandonment Permits
# ===========================================================================
@app.route("/abandonment-permits", methods=["POST"])
@endpoint(["Applicant"])
def create_abandonment_permit(ctx):
    body = get_body()
    well_id = require_str(body, "well_id")
    applicant_id = require_str(body, "applicant_id")
    driller_id = require_str(body, "driller_id")
    reason = require_enum(body, "reason", {"DRY", "CONTAMINATED", "REPLACED", "CODE_VIOLATION"})
    method = require_enum(body, "method", {"PERFORATE_FILL", "OVERDRILL", "EXCAVATE"})
    well = get_or_404(store.wells, well_id, "ERR_WELL_NOT_FOUND")
    get_or_404(store.applicants, applicant_id, "ERR_APPLICANT_NOT_FOUND")
    get_or_404(store.drillers, driller_id, "ERR_DRILLER_NOT_FOUND")
    if applicant_id != well["applicant_id"]:
        raise ApiError("ERR_APPLICANT_MISMATCH", "applicant_id does not match the well owner")
    rec = base_common()
    rec.update({
        "well_id": well_id,
        "applicant_id": applicant_id,
        "driller_id": driller_id,
        "reason": reason,
        "method": method,
        "completed_on": None,
        "status": "SUBMITTED",
    })
    store.abandonment_permits[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/abandonment-permits/<rid>", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def get_abandonment_permit(ctx, rid):
    rec = get_or_404(store.abandonment_permits, rid, "ERR_ABANDONMENT_NOT_FOUND")
    return success(serialize(rec))


@app.route("/abandonment-permits", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def list_abandonment_permits(ctx):
    rows = filter_rows(store.abandonment_permits, {
        "well_id": "well_id",
        "applicant_id": "applicant_id",
        "driller_id": "driller_id",
        "status": "status",
    })
    return paginate(rows, serialize)


@app.route("/abandonment-permits/<rid>/approve", methods=["POST"])
@endpoint(["HealthOfficer"])
def approve_abandonment_permit(ctx, rid):
    rec = get_or_404(store.abandonment_permits, rid, "ERR_ABANDONMENT_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Abandonment permit is not SUBMITTED")
    well = store.wells[rec["well_id"]]
    if well["registry_status"] != "ACTIVE":
        raise ApiError("ERR_WELL_NOT_ACTIVE", "Well is not ACTIVE")
    for p in store.construction_permits.values():
        if p["well_id"] == rec["well_id"] and p["status"] in ("SUBMITTED", "APPROVED", "ISSUED"):
            raise ApiError("ERR_ABANDONMENT_BLOCKED", "Non-terminal construction permit exists on the well")
    rec["status"] = "APPROVED"
    touch(rec)
    return success(serialize(rec))


@app.route("/abandonment-permits/<rid>/deny", methods=["POST"])
@endpoint(["HealthOfficer"])
def deny_abandonment_permit(ctx, rid):
    rec = get_or_404(store.abandonment_permits, rid, "ERR_ABANDONMENT_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Abandonment permit is not SUBMITTED")
    rec["status"] = "DENIED"
    touch(rec)
    return success(serialize(rec))


@app.route("/abandonment-permits/<rid>/complete", methods=["POST"])
@endpoint(["Driller"])
def complete_abandonment_permit(ctx, rid):
    rec = get_or_404(store.abandonment_permits, rid, "ERR_ABANDONMENT_NOT_FOUND")
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Abandonment permit is not APPROVED")
    if ctx.user_id != rec["driller_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "Only the assigned driller may complete this abandonment")
    driller = store.drillers[rec["driller_id"]]
    now = store.now()
    if driller["status"] != "ACTIVE" or now >= driller["license_expires_on"]:
        raise ApiError("ERR_DRILLER_LICENSE_INVALID", "Driller license invalid")
    rec["status"] = "COMPLETED"
    rec["completed_on"] = now
    touch(rec)
    well = store.wells[rec["well_id"]]
    well["registry_status"] = "DECOMMISSIONED"
    touch(well)
    return success(serialize(rec))


# ===========================================================================
# Real-Estate Test Requirements
# ===========================================================================
@app.route("/real-estate-requirements", methods=["POST"])
@endpoint(["Applicant", "HealthOfficer"])
def create_real_estate_requirement(ctx):
    body = get_body()
    well_id = require_str(body, "well_id")
    applicant_id = require_str(body, "applicant_id")
    transaction_type = require_enum(body, "transaction_type", {"SALE", "REFINANCE"})
    closing_date = parse_dt(require(body, "closing_date"))
    if "required_analytes" in body and body["required_analytes"] is not None:
        required_analytes = body["required_analytes"]
        if not isinstance(required_analytes, list):
            raise ApiError("ERR_VALIDATION", "required_analytes must be a list")
        for a in required_analytes:
            if a not in ANALYTES:
                raise ApiError("ERR_VALIDATION", "required_analytes must be a subset of BACTERIA, NITRATE, LEAD")
    else:
        required_analytes = ["BACTERIA", "NITRATE", "LEAD"]
    get_or_404(store.wells, well_id, "ERR_WELL_NOT_FOUND")
    get_or_404(store.applicants, applicant_id, "ERR_APPLICANT_NOT_FOUND")
    rec = base_common()
    rec.update({
        "well_id": well_id,
        "applicant_id": applicant_id,
        "transaction_type": transaction_type,
        "closing_date": closing_date,
        "required_analytes": required_analytes,
        "linked_sample_id": None,
        "status": "OPEN",
    })
    store.real_estate_requirements[rec["id"]] = rec
    return success(serialize(rec), status=201)


@app.route("/real-estate-requirements/<rid>", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def get_real_estate_requirement(ctx, rid):
    rec = get_or_404(store.real_estate_requirements, rid, "ERR_REQUIREMENT_NOT_FOUND")
    return success(serialize(rec))


@app.route("/real-estate-requirements", methods=["GET"])
@endpoint(["Applicant", "Driller", "LabAnalyst", "HealthOfficer"])
def list_real_estate_requirements(ctx):
    rows = filter_rows(store.real_estate_requirements, {
        "well_id": "well_id",
        "applicant_id": "applicant_id",
        "linked_sample_id": "linked_sample_id",
        "status": "status",
    })
    return paginate(rows, serialize)


def _result_for_sample(sample_id):
    for res in store.sample_results.values():
        if res["water_sample_id"] == sample_id:
            return res
    return None


@app.route("/real-estate-requirements/<rid>/link-sample", methods=["POST"])
@endpoint(["Applicant"])
def link_sample_requirement(ctx, rid):
    body = get_body()
    linked_sample_id = require_str(body, "linked_sample_id")
    expected_version = require_int(body, "expected_requirement_version")
    rec = get_or_404(store.real_estate_requirements, rid, "ERR_REQUIREMENT_NOT_FOUND")
    sample = get_or_404(store.water_samples, linked_sample_id, "ERR_SAMPLE_NOT_FOUND")
    if rec["status"] != "OPEN":
        raise ApiError("ERR_REQUIREMENT_NOT_OPEN", "Requirement is not OPEN")
    if expected_version != rec["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_requirement_version does not match")
    # temporal window
    if sample["collected_on"] > rec["closing_date"] or \
            (rec["closing_date"] - sample["collected_on"]) > timedelta(days=REAL_ESTATE_TEST_VALIDITY_DAYS):
        raise ApiError("ERR_SAMPLE_OUTSIDE_VALIDITY_WINDOW", "Sample outside validity window")
    # sample safety
    result = _result_for_sample(linked_sample_id)
    if sample["status"] != "RESULTED" or result is None or \
            result["advisory_level_confirmed"] != "SAFE":
        raise ApiError("ERR_SAMPLE_NOT_SAFE", "Linked sample is not RESULTED/SAFE")
    rec["linked_sample_id"] = linked_sample_id
    touch(rec)
    return success(serialize(rec))


@app.route("/real-estate-requirements/<rid>/certify", methods=["POST"])
@endpoint(["HealthOfficer"])
def certify_requirement(ctx, rid):
    rec = get_or_404(store.real_estate_requirements, rid, "ERR_REQUIREMENT_NOT_FOUND")
    if rec["status"] != "OPEN":
        raise ApiError("ERR_REQUIREMENT_NOT_OPEN", "Requirement is not OPEN")
    if rec["linked_sample_id"] is None:
        raise ApiError("ERR_INVALID_STATE", "No candidate sample is attached")
    rec["status"] = "SATISFIED"
    touch(rec)
    return success(serialize(rec))


@app.route("/real-estate-requirements/<rid>/waive", methods=["POST"])
@endpoint(["HealthOfficer"])
def waive_requirement(ctx, rid):
    rec = get_or_404(store.real_estate_requirements, rid, "ERR_REQUIREMENT_NOT_FOUND")
    if rec["status"] != "OPEN":
        raise ApiError("ERR_REQUIREMENT_NOT_OPEN", "Requirement is not OPEN")
    rec["status"] = "WAIVED"
    touch(rec)
    return success(serialize(rec))


# ===========================================================================
# Clock / Ops (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(["HealthOfficer"])
def set_clock(ctx):
    body = get_body()
    to_iso8601 = parse_dt(require(body, "to_iso8601"))
    store.set_clock(to_iso8601)
    return success({})


@app.route("/_ops/expiry-sweep", methods=["POST"])
@endpoint(["HealthOfficer"])
def expiry_sweep(ctx):
    now = store.now()
    for p in store.construction_permits.values():
        if p["status"] == "ISSUED" and p["expires_on"] is not None and now >= p["expires_on"]:
            p["status"] = "EXPIRED"
            touch(p)
    for r in store.real_estate_requirements.values():
        if r["status"] == "OPEN" and now > r["closing_date"]:
            r["status"] = "EXPIRED"
            touch(r)
    return success({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
