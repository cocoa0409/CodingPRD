"""EPCRA Hazmat / Tier II Reporting API — Flask entry point and routes."""

import os

from flask import Flask

import core
import logic
from core import (
    authenticate, require_roles, require_owner, get_body, ApiError,
    ok_object, ok_array, error_response, paginate, sort_by_created,
    base_record, touch, now, parse_dt,
    as_str, as_enum, as_int, as_number, as_bool, as_dt, bad, require_present,
    MIN_INSPECTION_GAP_HOURS,
)
from datetime import timedelta

app = Flask(__name__)

READ_ROLES = ["Regulator", "FacilityOperator", "LEPCCoordinator"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Method not allowed"))


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INTERNAL", 500, str(e)))


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_facility(fid):
    f = core.facilities.get(fid)
    if not f:
        raise ApiError("ERR_FACILITY_NOT_FOUND", 404, "Facility not found")
    return f


def get_chemical(cid):
    c = core.chemicals.get(cid)
    if not c:
        raise ApiError("ERR_CHEMICAL_NOT_FOUND", 404, "Chemical not found")
    return c


def get_inventory(iid):
    v = core.inventories.get(iid)
    if not v:
        raise ApiError("ERR_INVENTORY_NOT_FOUND", 404, "Inventory not found")
    return v


def get_filing(fid):
    f = core.filings.get(fid)
    if not f:
        raise ApiError("ERR_FILING_NOT_FOUND", 404, "Filing not found")
    return f


def get_sds(sid):
    s = core.sds_docs.get(sid)
    if not s:
        raise ApiError("ERR_SDS_NOT_FOUND", 404, "SDS not found")
    return s


def get_release(rid):
    r = core.releases.get(rid)
    if not r:
        raise ApiError("ERR_RELEASE_NOT_FOUND", 404, "Release not found")
    return r


def get_notice(nid):
    n = core.lepc_notices.get(nid)
    if not n:
        raise ApiError("ERR_LEPC_NOTICE_NOT_FOUND", 404, "LEPC notice not found")
    return n


def get_permit(pid):
    p = core.permits.get(pid)
    if not p:
        raise ApiError("ERR_PERMIT_NOT_FOUND", 404, "Permit not found")
    return p


def get_inspection(iid):
    i = core.inspections.get(iid)
    if not i:
        raise ApiError("ERR_INSPECTION_NOT_FOUND", 404, "Inspection not found")
    return i


def get_case(cid):
    c = core.cases.get(cid)
    if not c:
        raise ApiError("ERR_CASE_NOT_FOUND", 404, "Case not found")
    return c


def get_rmp(rid):
    r = core.rmps.get(rid)
    if not r:
        raise ApiError("ERR_RMP_NOT_FOUND", 404, "Risk management plan not found")
    return r


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    require_roles(role, ["Regulator"])
    body = get_body()
    core.set_clock(as_dt(body, "to_iso8601"))
    return ok_object({}, 200)


# ---------------------------------------------------------------------------
# Facilities
# ---------------------------------------------------------------------------
@app.route("/epcra/facilities", methods=["POST"])
def create_facility():
    _uid, role = authenticate()
    require_roles(role, ["Regulator"])
    body = get_body()
    name = as_str(body, "name")
    epa = as_str(body, "epa_facility_id")
    state_code = as_str(body, "state_code")
    county = as_str(body, "county")
    operator_name = as_str(body, "operator_name")
    for f in core.facilities.values():
        if f["epa_facility_id"] == epa:
            raise bad("epa_facility_id must be unique")
    rec = base_record()
    rec.update({
        "name": name,
        "epa_facility_id": epa,
        "state_code": state_code,
        "county": county,
        "operator_name": operator_name,
        "erp_contact_name": None,
        "erp_contact_phone": None,
        "erp_plan_ref": None,
        "erp_linked_lepc_district": None,
        "erp_status": "NONE",
    })
    core.facilities[rec["id"]] = rec
    return ok_object(logic.ser_facility(rec), 201)


@app.route("/epcra/facilities", methods=["GET"])
def list_facilities():
    _uid, role = authenticate()
    require_roles(role, READ_ROLES)
    from flask import request
    items = list(core.facilities.values())
    sc = request.args.get("state_code")
    if sc is not None:
        items = [f for f in items if f["state_code"] == sc]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_array([logic.ser_facility(f) for f in page], limit, offset, total)


@app.route("/epcra/facilities/<fid>", methods=["GET"])
def get_facility_route(fid):
    _uid, role = authenticate()
    require_roles(role, READ_ROLES)
    f = get_facility(fid)
    return ok_object(logic.ser_facility(f))


@app.route("/epcra/facilities/<fid>/emergency-response-plan", methods=["POST"])
def link_erp(fid):
    uid, role = authenticate()
    require_roles(role, ["FacilityOperator"])
    require_owner(role, uid, fid)
    body = get_body()
    contact_name = as_str(body, "contact_name")
    contact_phone = as_str(body, "contact_phone")
    plan_ref = as_str(body, "plan_ref")
    district = as_str(body, "linked_lepc_district")
    f = get_facility(fid)
    f["erp_contact_name"] = contact_name
    f["erp_contact_phone"] = contact_phone
    f["erp_plan_ref"] = plan_ref
    f["erp_linked_lepc_district"] = district
    f["erp_status"] = "ACTIVE"
    touch(f)
    return ok_object(logic.ser_facility(f))


def _facility_subcollection(fid, store, serializer):
    _uid, role = authenticate()
    require_roles(role, READ_ROLES)
    get_facility(fid)
    items = [x for x in store.values() if x["facility_id"] == fid]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_array([serializer(x) for x in page], limit, offset, total)


@app.route("/epcra/facilities/<fid>/tier-ii-filings", methods=["GET"])
def facility_filings(fid):
    return _facility_subcollection(fid, core.filings, logic.ser_filing)


@app.route("/epcra/facilities/<fid>/permits", methods=["GET"])
def facility_permits(fid):
    return _facility_subcollection(fid, core.permits, logic.ser_permit)


@app.route("/epcra/facilities/<fid>/inspections", methods=["GET"])
def facility_inspections(fid):
    return _facility_subcollection(fid, core.inspections, logic.ser_inspection)


@app.route("/epcra/facilities/<fid>/compliance-cases", methods=["GET"])
def facility_cases(fid):
    return _facility_subcollection(fid, core.cases, logic.ser_case)


@app.route("/epcra/facilities/<fid>/risk-management-plans", methods=["GET"])
def facility_rmps(fid):
    return _facility_subcollection(fid, core.rmps, logic.ser_rmp)


# ---------------------------------------------------------------------------
# Chemicals
# ---------------------------------------------------------------------------
@app.route("/epcra/chemicals", methods=["POST"])
def create_chemical():
    _uid, role = authenticate()
    require_roles(role, ["Regulator"])
    body = get_body()
    cas = as_str(body, "cas_number")
    name = as_str(body, "name")
    is_ehs = as_bool(body, "is_ehs")
    rq_lbs = as_int(body, "rq_lbs")
    hazard_weight = as_number(body, "hazard_weight")
    physical_state = as_enum(body, "physical_state", {"SOLID", "LIQUID", "GAS"})
    tpq_lbs = None
    if is_ehs:
        tpq_lbs = as_int(body, "tpq_lbs")
    for c in core.chemicals.values():
        if c["cas_number"] == cas:
            raise bad("cas_number must be unique")
    rec = base_record()
    rec.update({
        "cas_number": cas,
        "name": name,
        "is_ehs": is_ehs,
        "tpq_lbs": tpq_lbs,
        "rq_lbs": rq_lbs,
        "hazard_weight": hazard_weight,
        "physical_state": physical_state,
    })
    core.chemicals[rec["id"]] = rec
    return ok_object(logic.ser_chemical(rec), 201)


@app.route("/epcra/chemicals", methods=["GET"])
def list_chemicals():
    _uid, role = authenticate()
    require_roles(role, READ_ROLES)
    from flask import request
    items = list(core.chemicals.values())
    ehs = request.args.get("is_ehs")
    if ehs is not None:
        want = ehs.lower() == "true"
        items = [c for c in items if c["is_ehs"] == want]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_array([logic.ser_chemical(c) for c in page], limit, offset, total)


@app.route("/epcra/chemicals/<cid>", methods=["GET"])
def get_chemical_route(cid):
    _uid, role = authenticate()
    require_roles(role, READ_ROLES)
    c = get_chemical(cid)
    return ok_object(logic.ser_chemical(c))


# ---------------------------------------------------------------------------
# Chemical Inventories
# ---------------------------------------------------------------------------
@app.route("/epcra/chemical-inventories", methods=["POST"])
def create_inventory():
    uid, role = authenticate()
    require_roles(role, ["FacilityOperator"])
    body = get_body()
    if "facility_id" in body and body["facility_id"] is not None:
        require_owner(role, uid, body["facility_id"])
    facility_id = as_str(body, "facility_id")
    require_owner(role, uid, facility_id)
    chemical_id = as_str(body, "chemical_id")
    reporting_year = as_int(body, "reporting_year")
    max_daily = as_number(body, "max_daily_amount_lbs")
    avg_daily = as_number(body, "average_daily_amount_lbs")
    days_on_site = as_int(body, "days_on_site")
    storage_type = as_enum(body, "storage_type", {"TANK", "CYLINDER", "DRUM", "BULK"})
    f = get_facility(facility_id)
    chem = get_chemical(chemical_id)
    rec = base_record()
    rec.update({
        "facility_id": facility_id,
        "chemical_id": chemical_id,
        "reporting_year": reporting_year,
        "max_daily_amount_lbs": max_daily,
        "average_daily_amount_lbs": avg_daily,
        "days_on_site": days_on_site,
        "storage_type": storage_type,
        "status": "ACTIVE",
    })
    logic.compute_inventory_derived(rec, chem)
    core.inventories[rec["id"]] = rec
    return ok_object(logic.ser_inventory(rec), 201)


@app.route("/epcra/chemical-inventories", methods=["GET"])
def list_inventories():
    _uid, role = authenticate()
    require_roles(role, READ_ROLES)
    from flask import request
    items = list(core.inventories.values())
    fid = request.args.get("facility_id")
    cid = request.args.get("chemical_id")
    year = request.args.get("reporting_year")
    if fid is not None:
        items = [x for x in items if x["facility_id"] == fid]
    if cid is not None:
        items = [x for x in items if x["chemical_id"] == cid]
    if year is not None:
        try:
            y = int(year)
        except (ValueError, TypeError):
            raise bad("reporting_year must be an integer")
        items = [x for x in items if x["reporting_year"] == y]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_array([logic.ser_inventory(x) for x in page], limit, offset, total)


@app.route("/epcra/chemical-inventories/<iid>", methods=["GET"])
def get_inventory_route(iid):
    _uid, role = authenticate()
    require_roles(role, READ_ROLES)
    v = get_inventory(iid)
    return ok_object(logic.ser_inventory(v))


@app.route("/epcra/chemical-inventories/<iid>/retire", methods=["POST"])
def retire_inventory(iid):
    uid, role = authenticate()
    require_roles(role, ["FacilityOperator"])
    v = get_inventory(iid)
    require_owner(role, uid, v["facility_id"])
    if v["status"] != "ACTIVE":
        raise ApiError("ERR_INVENTORY_NOT_ACTIVE", 409, "Inventory is not ACTIVE")
    v["status"] = "RETIRED"
    touch(v)
    return ok_object(logic.ser_inventory(v))


# ---------------------------------------------------------------------------
# Tier II Filings
# ---------------------------------------------------------------------------
@app.route("/epcra/tier-ii-filings", methods=["POST"])
def create_filing():
    uid, role = authenticate()
    require_roles(role, ["FacilityOperator"])
    body = get_body()
    if "facility_id" in body and body["facility_id"] is not None:
        require_owner(role, uid, body["facility_id"])
    facility_id = as_str(body, "facility_id")
    require_owner(role, uid, facility_id)
    reporting_year = as_int(body, "reporting_year")
    get_facility(facility_id)
    rec = base_record()
    rec.update({
        "facility_id": facility_id,
        "reporting_year": reporting_year,
        "status": "DRAFT",
        "provisional_fee_cents": logic.provisional_fee(facility_id, reporting_year),
        "assessed_fee_cents": 0,
        "fee_paid_cents": 0,
        "is_late": False,
        "submitted_at": None,
        "deadline": logic.filing_deadline(reporting_year),
        "revision_count": 0,
    })
    core.filings[rec["id"]] = rec
    return ok_object(logic.ser_filing(rec), 201)


@app.route("/epcra/tier-ii-filings/<fid>/submit", methods=["POST"])
def submit_filing(fid):
    uid, role = authenticate()
    require_roles(role, ["FacilityOperator"])
    filing = get_filing(fid)
    require_owner(role, uid, filing["facility_id"])
    # 1. state
    if filing["status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        raise ApiError("ERR_FILING_NOT_SUBMITTABLE", 409, "Filing is not submittable")
    facility_id = filing["facility_id"]
    year = filing["reporting_year"]
    reportable = logic.reportable_inventories_for_year(facility_id, year)
    # 2. every reportable chemical has an ACTIVE SDS
    for inv in reportable:
        has_sds = any(
            s["facility_id"] == facility_id and s["chemical_id"] == inv["chemical_id"]
            and s["status"] == "ACTIVE"
            for s in core.sds_docs.values()
        )
        if not has_sds:
            raise ApiError("ERR_MISSING_SDS", 409, "Reportable chemical lacks an ACTIVE SDS")
    # 3. at least one reportable inventory
    if not reportable:
        raise ApiError("ERR_NO_REPORTABLE_CHEMICALS", 422, "No reportable chemicals for the year")
    # 4. facility not under enforcement
    if logic.facility_posture(facility_id) == "ENFORCEMENT":
        raise ApiError("ERR_FACILITY_UNDER_ENFORCEMENT", 409, "Facility is under enforcement")

    n, e = logic.filing_counts(filing)
    submitted_at = now()
    is_late = submitted_at > filing["deadline"]
    filing["assessed_fee_cents"] = logic.assessed_fee(n, e, is_late)
    filing["submitted_at"] = submitted_at
    filing["is_late"] = is_late
    filing["status"] = "SUBMITTED"
    touch(filing)
    if is_late:
        logic.open_case(facility_id, "LATE_FILING", "LOW", filing["id"])
    return ok_object(logic.ser_filing(filing))


@app.route("/epcra/tier-ii-filings/<fid>/review", methods=["POST"])
def review_filing(fid):
    _uid, role = authenticate()
    require_roles(role, ["Regulator"])
    body = get_body()
    decision = as_enum(body, "decision", {"BEGIN", "ACCEPT", "RETURN"})
    filing = get_filing(fid)
    if decision == "BEGIN":
        if filing["status"] != "SUBMITTED":
            raise ApiError("ERR_FILING_NOT_REVIEWABLE", 409, "Filing not reviewable")
        filing["status"] = "UNDER_REVIEW"
        touch(filing)
    elif decision == "ACCEPT":
        if filing["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_FILING_NOT_REVIEWABLE", 409, "Filing not reviewable")
        if filing["fee_paid_cents"] < filing["assessed_fee_cents"]:
            raise ApiError("ERR_FEE_UNPAID", 402, "Filing fee not fully paid")
        filing["status"] = "ACCEPTED"
        touch(filing)
    else:  # RETURN
        if filing["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_FILING_NOT_REVIEWABLE", 409, "Filing not reviewable")
        filing["assessed_fee_cents"] = 0
        filing["revision_count"] += 1
        filing["status"] = "RETURNED_FOR_REVISION"
        touch(filing)
    return ok_object(logic.ser_filing(filing))


@app.route("/epcra/tier-ii-filings/<fid>/pay", methods=["POST"])
def pay_filing(fid):
    uid, role = authenticate()
    require_roles(role, ["FacilityOperator"])
    body = get_body()
    amount = as_int(body, "amount_cents")
    filing = get_filing(fid)
    require_owner(role, uid, filing["facility_id"])
    filing["fee_paid_cents"] += amount
    touch(filing)
    return ok_object(logic.ser_filing(filing))


# ---------------------------------------------------------------------------
# SDS
# ---------------------------------------------------------------------------
@app.route("/epcra/sds", methods=["POST"])
def create_sds():
    uid, role = authenticate()
    require_roles(role, ["FacilityOperator"])
    body = get_body()
    if "facility_id" in body and body["facility_id"] is not None:
        require_owner(role, uid, body["facility_id"])
    facility_id = as_str(body, "facility_id")
    require_owner(role, uid, facility_id)
    chemical_id = as_str(body, "chemical_id")
    document_ref = as_str(body, "document_ref")
    revision_date = as_dt(body, "revision_date")
    expected_version = as_int(body, "expected_facility_version")
    f = get_facility(facility_id)
    get_chemical(chemical_id)
    if expected_version != f["version"]:
        raise ApiError("ERR_STALE_FACILITY_VERSION", 412, "Stale facility version")
    # supersede prior ACTIVE sheet for same (facility, chemical)
    for s in core.sds_docs.values():
        if (s["facility_id"] == facility_id and s["chemical_id"] == chemical_id
                and s["status"] == "ACTIVE"):
            s["status"] = "SUPERSEDED"
            touch(s)
    rec = base_record()
    rec.update({
        "facility_id": facility_id,
        "chemical_id": chemical_id,
        "document_ref": document_ref,
        "revision_date": revision_date,
        "status": "ACTIVE",
    })
    core.sds_docs[rec["id"]] = rec
    touch(f)  # SDS repository mutated -> facility version bumps
    return ok_object(logic.ser_sds(rec), 201)


@app.route("/epcra/sds", methods=["GET"])
def list_sds():
    _uid, role = authenticate()
    require_roles(role, READ_ROLES)
    from flask import request
    items = list(core.sds_docs.values())
    fid = request.args.get("facility_id")
    cid = request.args.get("chemical_id")
    if fid is not None:
        items = [x for x in items if x["facility_id"] == fid]
    if cid is not None:
        items = [x for x in items if x["chemical_id"] == cid]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_array([logic.ser_sds(x) for x in page], limit, offset, total)


@app.route("/epcra/sds/<sid>", methods=["GET"])
def get_sds_route(sid):
    _uid, role = authenticate()
    require_roles(role, READ_ROLES)
    s = get_sds(sid)
    return ok_object(logic.ser_sds(s))


# ---------------------------------------------------------------------------
# Release Notifications
# ---------------------------------------------------------------------------
@app.route("/epcra/release-notifications", methods=["POST"])
def create_release():
    uid, role = authenticate()
    require_roles(role, ["FacilityOperator"])
    body = get_body()
    if "facility_id" in body and body["facility_id"] is not None:
        require_owner(role, uid, body["facility_id"])
    facility_id = as_str(body, "facility_id")
    require_owner(role, uid, facility_id)
    chemical_id = as_str(body, "chemical_id")
    release_datetime = as_dt(body, "release_datetime")
    quantity = as_number(body, "quantity_released_lbs")
    medium = as_enum(body, "medium", {"AIR", "WATER", "SOIL"})
    get_facility(facility_id)
    chem = get_chemical(chemical_id)
    if release_datetime > now():
        raise ApiError("ERR_FUTURE_RELEASE", 422, "Release datetime is in the future")
    exceeds_rq = quantity >= chem["rq_lbs"]
    rec = base_record()
    rec.update({
        "facility_id": facility_id,
        "chemical_id": chemical_id,
        "release_datetime": release_datetime,
        "quantity_released_lbs": quantity,
        "medium": medium,
        "reporting_status": "PENDING_VERBAL",
        "remediation_status": "ONGOING",
        "exceeds_rq": exceeds_rq,
        "requires_lepc": exceeds_rq,
        "origin_case_opened": False,
    })
    core.releases[rec["id"]] = rec
    if exceeds_rq:
        logic.open_case(facility_id, "RELEASE_RQ_EXCEEDED", "HIGH", rec["id"])
        rec["origin_case_opened"] = True
        logic.suspend_active_permits(facility_id)
    return ok_object(logic.ser_release(rec), 201)


@app.route("/epcra/release-notifications", methods=["GET"])
def list_releases():
    _uid, role = authenticate()
    require_roles(role, READ_ROLES)
    from flask import request
    items = list(core.releases.values())
    fid = request.args.get("facility_id")
    cid = request.args.get("chemical_id")
    if fid is not None:
        items = [x for x in items if x["facility_id"] == fid]
    if cid is not None:
        items = [x for x in items if x["chemical_id"] == cid]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_array([logic.ser_release(x) for x in page], limit, offset, total)


@app.route("/epcra/release-notifications/<rid>", methods=["GET"])
def get_release_route(rid):
    _uid, role = authenticate()
    require_roles(role, READ_ROLES)
    r = get_release(rid)
    return ok_object(logic.ser_release(r))


@app.route("/epcra/release-notifications/<rid>/report", methods=["POST"])
def report_release(rid):
    uid, role = authenticate()
    require_roles(role, ["FacilityOperator"])
    body = get_body()
    stage = as_enum(body, "stage", {"VERBAL", "WRITTEN"})
    r = get_release(rid)
    require_owner(role, uid, r["facility_id"])
    if stage == "VERBAL":
        if r["reporting_status"] != "PENDING_VERBAL":
            raise ApiError("ERR_RELEASE_INVALID_STAGE", 409, "Invalid reporting stage")
        r["reporting_status"] = "VERBAL_GIVEN"
    else:  # WRITTEN
        if r["reporting_status"] != "VERBAL_GIVEN":
            raise ApiError("ERR_RELEASE_INVALID_STAGE", 409, "Invalid reporting stage")
        f = core.facilities.get(r["facility_id"])
        if not f or f["erp_status"] != "ACTIVE":
            raise ApiError("ERR_NO_ERP_LINKAGE", 409, "Facility has no active emergency-response plan")
        r["reporting_status"] = "WRITTEN_FILED"
    touch(r)
    return ok_object(logic.ser_release(r))


@app.route("/epcra/release-notifications/<rid>/remediation", methods=["POST"])
def remediate_release(rid):
    uid, role = authenticate()
    require_roles(role, ["FacilityOperator"])
    body = get_body()
    to = as_enum(body, "to", {"CONTAINED", "CLOSED"})
    r = get_release(rid)
    require_owner(role, uid, r["facility_id"])
    if to == "CONTAINED":
        if r["remediation_status"] != "ONGOING":
            raise ApiError("ERR_RELEASE_INVALID_STAGE", 409, "Invalid remediation stage")
        r["remediation_status"] = "CONTAINED"
    else:  # CLOSED
        if r["remediation_status"] != "CONTAINED":
            raise ApiError("ERR_RELEASE_INVALID_STAGE", 409, "Invalid remediation stage")
        r["remediation_status"] = "CLOSED"
    touch(r)
    return ok_object(logic.ser_release(r))


@app.route("/epcra/release-notifications/<rid>/lepc-notices", methods=["GET"])
def list_release_notices(rid):
    _uid, role = authenticate()
    require_roles(role, READ_ROLES)
    get_release(rid)
    items = [n for n in core.lepc_notices.values() if n["release_id"] == rid]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_array([logic.ser_notice(n) for n in page], limit, offset, total)


# ---------------------------------------------------------------------------
# LEPC Notices
# ---------------------------------------------------------------------------
@app.route("/epcra/lepc-notices", methods=["POST"])
def create_notice():
    uid, role = authenticate()
    require_roles(role, ["FacilityOperator"])
    body = get_body()
    release_id = as_str(body, "release_id")
    notice_type = as_enum(body, "notice_type", {"VERBAL", "WRITTEN"})
    recipient = as_enum(body, "recipient", {"LEPC", "SERC", "NRC"})
    r = get_release(release_id)
    require_owner(role, uid, r["facility_id"])
    rec = base_record()
    rec.update({
        "release_id": release_id,
        "notice_type": notice_type,
        "recipient": recipient,
        "sent_at": now(),
        "acknowledged": False,
    })
    core.lepc_notices[rec["id"]] = rec
    return ok_object(logic.ser_notice(rec), 201)


@app.route("/epcra/lepc-notices/<nid>/acknowledge", methods=["POST"])
def acknowledge_notice(nid):
    _uid, role = authenticate()
    require_roles(role, ["LEPCCoordinator"])
    n = get_notice(nid)
    n["acknowledged"] = True
    touch(n)
    return ok_object(logic.ser_notice(n))


# ---------------------------------------------------------------------------
# Permits
# ---------------------------------------------------------------------------
@app.route("/epcra/permits", methods=["POST"])
def create_permit():
    _uid, role = authenticate()
    require_roles(role, ["Regulator"])
    body = get_body()
    facility_id = as_str(body, "facility_id")
    permit_type = as_enum(body, "permit_type", {"OPERATING", "STORAGE", "AIR"})
    issued_date = as_dt(body, "issued_date")
    expiry_date = as_dt(body, "expiry_date")
    fee_cents = as_int(body, "fee_cents")
    f = get_facility(facility_id)
    # temporal: overlap with existing same-type permit on facility
    for p in core.permits.values():
        if p["facility_id"] == facility_id and p["permit_type"] == permit_type:
            if issued_date <= p["expiry_date"] and p["issued_date"] <= expiry_date:
                raise ApiError("ERR_PERMIT_PERIOD_OVERLAP", 409, "Permit period overlaps existing permit")
    # fiscal: facility must owe nothing
    if logic.facility_outstanding_fee(facility_id) > 0:
        raise ApiError("ERR_OUTSTANDING_FEES", 402, "Facility has outstanding fees")
    rec = base_record()
    rec.update({
        "facility_id": facility_id,
        "permit_type": permit_type,
        "issued_date": issued_date,
        "expiry_date": expiry_date,
        "fee_cents": fee_cents,
        "status": "ACTIVE",
    })
    core.permits[rec["id"]] = rec
    return ok_object(logic.ser_permit(rec), 201)


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------
@app.route("/epcra/inspections", methods=["POST"])
def create_inspection():
    _uid, role = authenticate()
    require_roles(role, ["Regulator"])
    body = get_body()
    facility_id = as_str(body, "facility_id")
    inspector_id = as_str(body, "inspector_id")
    scheduled_date = as_dt(body, "scheduled_date")
    get_facility(facility_id)
    gap = timedelta(hours=MIN_INSPECTION_GAP_HOURS)
    for i in core.inspections.values():
        if i["inspector_id"] == inspector_id:
            if abs(scheduled_date - i["scheduled_date"]) < gap:
                raise ApiError("ERR_INSPECTOR_DOUBLE_BOOKED", 409, "Inspector double-booked")
    rec = base_record()
    rec.update({
        "facility_id": facility_id,
        "inspector_id": inspector_id,
        "scheduled_date": scheduled_date,
        "status": "SCHEDULED",
        "result": None,
        "findings_count": 0,
    })
    core.inspections[rec["id"]] = rec
    return ok_object(logic.ser_inspection(rec), 201)


@app.route("/epcra/inspections/<iid>/start", methods=["POST"])
def start_inspection(iid):
    _uid, role = authenticate()
    require_roles(role, ["Regulator"])
    i = get_inspection(iid)
    if i["status"] != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_NOT_SCHEDULED", 409, "Inspection not scheduled")
    i["status"] = "IN_PROGRESS"
    touch(i)
    return ok_object(logic.ser_inspection(i))


@app.route("/epcra/inspections/<iid>/complete", methods=["POST"])
def complete_inspection(iid):
    _uid, role = authenticate()
    require_roles(role, ["Regulator"])
    body = get_body()
    result = as_enum(body, "result", {"PASS", "FAIL"})
    findings = 0
    if "findings_count" in body and body["findings_count"] is not None:
        findings = as_int(body, "findings_count")
    i = get_inspection(iid)
    if i["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INSPECTION_NOT_IN_PROGRESS", 409, "Inspection not in progress")
    if result == "PASS":
        i["status"] = "PASSED"
        i["result"] = "PASS"
        i["findings_count"] = 0
        touch(i)
    else:
        i["status"] = "FAILED"
        i["result"] = "FAIL"
        i["findings_count"] = findings
        touch(i)
        logic.open_case(i["facility_id"], "INSPECTION_FAILED", "MEDIUM", i["id"])
    return ok_object(logic.ser_inspection(i))


# ---------------------------------------------------------------------------
# Compliance Cases
# ---------------------------------------------------------------------------
@app.route("/epcra/compliance-cases", methods=["POST"])
def create_case():
    _uid, role = authenticate()
    require_roles(role, ["Regulator"])
    body = get_body()
    facility_id = as_str(body, "facility_id")
    severity = "LOW"
    if "severity" in body and body["severity"] is not None:
        severity = as_enum(body, "severity", {"LOW", "MEDIUM", "HIGH"})
    get_facility(facility_id)
    rec = base_record()
    rec.update({
        "facility_id": facility_id,
        "origin": "MANUAL",
        "origin_ref": None,
        "severity": severity,
        "status": "OPEN",
        "penalty_cents": 0,
    })
    core.cases[rec["id"]] = rec
    return ok_object(logic.ser_case(rec), 201)


@app.route("/epcra/compliance-cases/<cid>/review", methods=["POST"])
def review_case(cid):
    _uid, role = authenticate()
    require_roles(role, ["Regulator"])
    c = get_case(cid)
    if c["status"] != "OPEN":
        raise ApiError("ERR_CASE_NOT_OPEN", 409, "Case not open")
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return ok_object(logic.ser_case(c))


@app.route("/epcra/compliance-cases/<cid>/resolve", methods=["POST"])
def resolve_case(cid):
    _uid, role = authenticate()
    require_roles(role, ["Regulator"])
    body = get_body()
    penalty = None
    if "penalty_cents" in body and body["penalty_cents"] is not None:
        penalty = as_int(body, "penalty_cents")
    c = get_case(cid)
    if c["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CASE_NOT_UNDER_REVIEW", 409, "Case not under review")
    # cross-entity: facility's most recent inspection must be PASSED
    facility_inspections = [i for i in core.inspections.values()
                            if i["facility_id"] == c["facility_id"]]
    if facility_inspections:
        latest = max(facility_inspections, key=lambda i: (i["created_at"], i["_seq"]))
    else:
        latest = None
    if latest is None or latest["status"] != "PASSED":
        raise ApiError("ERR_UNRESOLVED_INSPECTION", 409, "Facility's most recent inspection is not PASSED")
    if penalty is not None:
        c["penalty_cents"] = penalty
    c["status"] = "RESOLVED"
    touch(c)
    # recompute posture; if it leaves ENFORCEMENT, reinstate suspended permits
    if logic.facility_posture(c["facility_id"]) != "ENFORCEMENT":
        logic.reinstate_suspended_permits(c["facility_id"])
    return ok_object(logic.ser_case(c))


# ---------------------------------------------------------------------------
# Risk Management Plans
# ---------------------------------------------------------------------------
@app.route("/epcra/risk-management-plans", methods=["POST"])
def create_rmp():
    uid, role = authenticate()
    require_roles(role, ["FacilityOperator"])
    body = get_body()
    if "facility_id" in body and body["facility_id"] is not None:
        require_owner(role, uid, body["facility_id"])
    facility_id = as_str(body, "facility_id")
    require_owner(role, uid, facility_id)
    program_level = as_int(body, "program_level")
    if program_level not in (1, 2, 3):
        raise bad("program_level must be 1, 2, or 3")
    submitted_date = as_dt(body, "submitted_date")
    get_facility(facility_id)
    rec = base_record()
    rec.update({
        "facility_id": facility_id,
        "program_level": program_level,
        "submitted_date": submitted_date,
        "next_due_date": core.add_years(submitted_date, core.RMP_RESUBMIT_YEARS),
        "status": "ACTIVE",
    })
    core.rmps[rec["id"]] = rec
    return ok_object(logic.ser_rmp(rec), 201)


@app.route("/epcra/risk-management-plans/<rid>/resubmit", methods=["POST"])
def resubmit_rmp(rid):
    uid, role = authenticate()
    require_roles(role, ["FacilityOperator"])
    body = get_body()
    submitted_date = as_dt(body, "submitted_date")
    r = get_rmp(rid)
    require_owner(role, uid, r["facility_id"])
    r["submitted_date"] = submitted_date
    r["next_due_date"] = core.add_years(submitted_date, core.RMP_RESUBMIT_YEARS)
    r["status"] = "ACTIVE"
    touch(r)
    return ok_object(logic.ser_rmp(r))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
