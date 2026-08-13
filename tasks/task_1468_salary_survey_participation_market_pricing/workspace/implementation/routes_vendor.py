"""SurveyVendors, Surveys, SurveyBenchmarks."""
from flask import Blueprint, g, request

from common import (
    ApiError, ALL_ROLES, body, current_date, db, emit_audit, filter_records,
    get_or_404, new_record, ok, ok_list, parse_date, pub, require_roles, touch,
    v_date, v_enum, v_int, v_str,
)
from lifecycle import close_survey, reject_surveys_for_vendor
from routes_core import CAREER_LEVELS, INDUSTRY_CUTS

bp = Blueprint("vendor", __name__)

DATA_USE_SCOPES = ("BENCHMARK_ONLY", "FULL_PARTICIPATION")
CONFIDENTIALITY_TIERS = ("PUBLIC", "CONFIDENTIAL", "RESTRICTED")


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------
@bp.route("/orgs/<oid>/vendors", methods=["POST"])
@require_roles("VendorAdmin")
def create_vendor(oid):
    org = get_or_404("orgs", oid)
    b = body()
    rec = new_record()
    rec.update({
        "org_id": org["id"],
        "vendor_name": v_str(b, "vendor_name"),
        "contract_start_date": v_date(b, "contract_start_date"),
        "contract_end_date": v_date(b, "contract_end_date"),
        "data_use_scope": v_enum(b, "data_use_scope", DATA_USE_SCOPES),
        "confidentiality_tier": v_enum(b, "confidentiality_tier", CONFIDENTIALITY_TIERS),
        "status": "DRAFT",
    })
    db["vendors"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.route("/vendors/<vid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_vendor(vid):
    return ok(pub(get_or_404("vendors", vid)))


@bp.route("/vendors", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_vendors():
    return ok_list(filter_records("vendors", {
        "org_id": request.args.get("org_id"),
        "status": request.args.get("status"),
    }))


@bp.route("/orgs/<oid>/vendors", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_org_vendors(oid):
    org = get_or_404("orgs", oid)
    return ok_list(filter_records("vendors", {"org_id": org["id"]}))


@bp.route("/vendors/<vid>/activate", methods=["POST"])
@require_roles("VendorAdmin")
def activate_vendor(vid):
    v = get_or_404("vendors", vid)
    if v["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot activate a vendor in status {v['status']}")
    d = current_date()
    if not (parse_date(v["contract_start_date"]) <= d < parse_date(v["contract_end_date"])):
        raise ApiError("ERR_VENDOR_CONTRACT_WINDOW", 409,
                       "Current date is outside [contract_start_date, contract_end_date)")
    v["status"] = "ACTIVE"
    touch(v)
    emit_audit(v["org_id"], None, "VENDOR_ACTIVATE", "SurveyVendor", v["id"],
               {"status": "ACTIVE"})
    return ok(pub(v))


@bp.route("/vendors/<vid>/terminate", methods=["POST"])
@require_roles("VendorAdmin")
def terminate_vendor(vid):
    v = get_or_404("vendors", vid)
    if v["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot terminate a vendor in status {v['status']}")
    for s in db["surveys"].values():
        if s["vendor_id"] == v["id"] and s["status"] == "SUBMITTED":
            raise ApiError("ERR_VENDOR_HAS_OPEN_SUBMISSIONS", 409,
                           "Vendor has at least one child Survey in SUBMITTED status")
    v["status"] = "TERMINATED"
    touch(v)
    reject_surveys_for_vendor(v, "VENDOR_TERMINATED")
    emit_audit(v["org_id"], None, "VENDOR_TERMINATE", "SurveyVendor", v["id"],
               {"status": "TERMINATED"})
    return ok(pub(v))


# ---------------------------------------------------------------------------
# Surveys
# ---------------------------------------------------------------------------
@bp.route("/vendors/<vid>/surveys", methods=["POST"])
@require_roles("VendorAdmin")
def create_survey(vid):
    vendor = get_or_404("vendors", vid)
    b = body()
    survey_code = v_str(b, "survey_code")
    edition_year = v_int(b, "edition_year")
    data_effective_date = v_date(b, "data_effective_date")
    submission_deadline = v_date(b, "submission_deadline")
    cuts = b.get("industry_cut_supported")
    if not isinstance(cuts, list) or any(c not in INDUSTRY_CUTS for c in cuts):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "industry_cut_supported must be a list of declared industry cuts")
    for s in db["surveys"].values():
        if s["vendor_id"] == vendor["id"] and s["survey_code"] == survey_code:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           f"survey_code {survey_code} already exists for this vendor")
    rec = new_record()
    rec.update({
        "vendor_id": vendor["id"],
        "org_id": vendor["org_id"],
        "survey_code": survey_code,
        "edition_year": edition_year,
        "data_effective_date": data_effective_date,
        "submission_deadline": submission_deadline,
        "industry_cut_supported": cuts,
        "status": "DRAFT",
    })
    db["surveys"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.route("/surveys/<sid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_survey(sid):
    return ok(pub(get_or_404("surveys", sid)))


@bp.route("/surveys", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_surveys():
    return ok_list(filter_records("surveys", {
        "org_id": request.args.get("org_id"),
        "vendor_id": request.args.get("vendor_id"),
        "status": request.args.get("status"),
        "edition_year": request.args.get("edition_year"),
    }))


@bp.route("/vendors/<vid>/surveys", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_vendor_surveys(vid):
    vendor = get_or_404("vendors", vid)
    return ok_list(filter_records("surveys", {"vendor_id": vendor["id"]}))


@bp.route("/orgs/<oid>/surveys", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_org_surveys(oid):
    org = get_or_404("orgs", oid)
    return ok_list(filter_records("surveys", {"org_id": org["id"]}))


@bp.route("/surveys/<sid>/open", methods=["POST"])
@require_roles("VendorAdmin")
def open_survey(sid):
    s = get_or_404("surveys", sid)
    if s["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot open a survey in status {s['status']}")
    # Ladder rung 9 (temporal) precedes rung 12 (vendor referential gate)
    if current_date() > parse_date(s["submission_deadline"]):
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED", 409,
                       "Current date is past the submission deadline")
    vendor = db["vendors"][s["vendor_id"]]
    if vendor["status"] != "ACTIVE":
        raise ApiError("ERR_VENDOR_NOT_ACTIVE", 409,
                       f"Vendor is in status {vendor['status']}, not ACTIVE")
    s["status"] = "OPEN"
    touch(s)
    return ok(pub(s))


@bp.route("/surveys/<sid>/close", methods=["POST"])
@require_roles("VendorAdmin")
def close_survey_endpoint(sid):
    s = get_or_404("surveys", sid)
    if s["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot close a survey in status {s['status']}")
    close_survey(s)
    return ok(pub(s))


@bp.route("/surveys/<sid>/accept", methods=["POST"])
@require_roles("VendorAdmin")
def accept_survey(sid):
    s = get_or_404("surveys", sid)
    if s["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot accept a survey in status {s['status']}")
    subs = [x for x in db["submissions"].values() if x["survey_id"] == s["id"]]
    if any(x["status"] not in ("SUBMITTED", "ACCEPTED", "RETURNED") for x in subs):
        raise ApiError("ERR_SUBMISSIONS_PENDING", 409,
                       "At least one submission is still in a non-terminal state")
    for x in subs:
        if x["status"] == "SUBMITTED":
            x["status"] = "ACCEPTED"
            touch(x)
    s["status"] = "ACCEPTED"
    touch(s)
    emit_audit(s["org_id"], None, "SURVEY_ACCEPT", "Survey", s["id"],
               {"status": "ACCEPTED"})
    return ok(pub(s))


@bp.route("/surveys/<sid>/reject", methods=["POST"])
@require_roles("VendorAdmin")
def reject_survey(sid):
    s = get_or_404("surveys", sid)
    b = body()
    reason = v_str(b, "reason")
    if s["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       f"Cannot reject a survey in status {s['status']}")
    for x in db["submissions"].values():
        if x["survey_id"] == s["id"] and x["status"] == "SUBMITTED":
            x["status"] = "RETURNED"
            x["rejection_reason"] = reason
            touch(x)
    s["status"] = "REJECTED"
    touch(s)
    emit_audit(s["org_id"], None, "SURVEY_REJECT", "Survey", s["id"],
               {"status": "REJECTED", "reason": reason})
    return ok(pub(s))


# ---------------------------------------------------------------------------
# Survey benchmarks
# ---------------------------------------------------------------------------
@bp.route("/surveys/<sid>/benchmarks", methods=["POST"])
@require_roles("VendorAdmin")
def create_benchmark(sid):
    survey = get_or_404("surveys", sid)
    b = body()
    rec = new_record()
    rec.update({
        "survey_id": survey["id"],
        "benchmark_code": v_str(b, "benchmark_code"),
        "benchmark_title": v_str(b, "benchmark_title"),
        "career_level": v_enum(b, "career_level", CAREER_LEVELS),
        "industry_cut": v_enum(b, "industry_cut", INDUSTRY_CUTS),
        "geo_scope": v_str(b, "geo_scope"),
        "p25_cents": v_int(b, "p25_cents"),
        "p50_cents": v_int(b, "p50_cents"),
        "p75_cents": v_int(b, "p75_cents"),
        "p90_cents": v_int(b, "p90_cents"),
        "sample_size": v_int(b, "sample_size", min_v=0),
    })
    db["benchmarks"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.route("/benchmarks/<bid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_benchmark(bid):
    return ok(pub(get_or_404("benchmarks", bid)))


@bp.route("/benchmarks", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_benchmarks():
    return ok_list(filter_records("benchmarks", {
        "survey_id": request.args.get("survey_id"),
        "career_level": request.args.get("career_level"),
        "industry_cut": request.args.get("industry_cut"),
    }))


@bp.route("/surveys/<sid>/benchmarks", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_survey_benchmarks(sid):
    survey = get_or_404("surveys", sid)
    return ok_list(filter_records("benchmarks", {"survey_id": survey["id"]}))
