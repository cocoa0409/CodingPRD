"""Routes: logical clock, funding opportunities, PIs, rate agreements, sub orgs."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import store, mint, touch
from errors import (ApiError, bad_request, not_found, ERR_RATE_OVERLAP,
                    ERR_UEI_NOT_UNIQUE, ERR_RATE_AGREEMENT_STATE)
from middleware import authenticate, require_roles
from response import ok_object, ok_list, parse_pagination
from serializers import (opportunity_out, pi_out, rate_out, org_out,
                         sub_commitment_out)
from services import (ACTIVITY_CODES, RATE_TYPES, run_clock_sweeps,
                      risk_score_standard, risk_tier_of)
from utils import (json_body, req_field, opt_field, as_str, as_int, as_bool,
                   as_number, as_enum, parse_datetime_value, parse_date_value)

bp = Blueprint("core", __name__)

ANY_ROLE = None  # sentinel: any authenticated role may read


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/pre-award/_clock/set_current_utc")
def set_clock():
    require_roles(["OSPSystemAdmin"])
    body = json_body()
    raw = as_str(req_field(body, "to_iso8601"), "to_iso8601")
    store.clock = parse_datetime_value(raw, "to_iso8601")
    run_clock_sweeps()
    return ok_object({"current_utc": raw}, 200)


# ---------------------------------------------------------------------------
# Funding opportunities
# ---------------------------------------------------------------------------

@bp.post("/pre-award/funding-opportunities")
def create_opportunity():
    require_roles(["OSPSystemAdmin"])
    body = json_body()
    sponsor_code = as_str(req_field(body, "sponsor_code"), "sponsor_code")
    title = as_str(req_field(body, "title"), "title")
    codes_raw = req_field(body, "activity_codes_allowed")
    if not isinstance(codes_raw, list):
        raise bad_request("Field 'activity_codes_allowed' must be an array")
    activity_codes = [as_enum(c, "activity_codes_allowed", ACTIVITY_CODES)
                      for c in codes_raw]
    deadline_raw = as_str(req_field(body, "sponsor_deadline_at"), "sponsor_deadline_at")
    sponsor_deadline = parse_datetime_value(deadline_raw, "sponsor_deadline_at")
    lead_days = opt_field(body, "internal_lead_days", 5)
    lead_days = as_int(lead_days, "internal_lead_days")
    cap = opt_field(body, "fa_rate_cap_pct", None)
    if cap is not None:
        cap = as_number(cap, "fa_rate_cap_pct")
    requires_cs = as_bool(opt_field(body, "requires_cost_share", False),
                          "requires_cost_share")
    min_cs = opt_field(body, "min_cost_share_pct_of_request", 0)
    min_cs = as_number(min_cs, "min_cost_share_pct_of_request")
    max_request = opt_field(body, "max_request_cents", None)
    if max_request is not None:
        max_request = as_int(max_request, "max_request_cents")
    max_per_pi = opt_field(body, "max_proposals_per_pi", None)
    if max_per_pi is not None:
        max_per_pi = as_int(max_per_pi, "max_proposals_per_pi")

    internal_deadline = sponsor_deadline - timedelta(days=lead_days)
    rec = mint({
        "sponsor_code": sponsor_code,
        "title": title,
        "activity_codes_allowed": activity_codes,
        "sponsor_deadline_at": deadline_raw,
        "internal_lead_days": lead_days,
        "fa_rate_cap_pct": cap,
        "requires_cost_share": requires_cs,
        "min_cost_share_pct_of_request": min_cs,
        "max_request_cents": max_request,
        "max_proposals_per_pi": max_per_pi,
        "status": "PUBLISHED",
        "_sponsor_deadline_dt": sponsor_deadline,
        "_internal_deadline_dt": internal_deadline,
    })
    store.funding_opportunities[rec["id"]] = rec
    return ok_object(opportunity_out(rec), 201)


@bp.get("/pre-award/funding-opportunities/<oid>")
def get_opportunity(oid):
    authenticate()
    rec = store.funding_opportunities.get(oid)
    if rec is None:
        raise not_found("Funding opportunity not found")
    return ok_object(opportunity_out(rec), 200)


# ---------------------------------------------------------------------------
# Principal investigators
# ---------------------------------------------------------------------------

PI_RANKS = ["ASSISTANT", "ASSOCIATE", "FULL", "RESEARCH_SCIENTIST"]


@bp.post("/pre-award/principal-investigators")
def create_pi():
    require_roles(["OSPSystemAdmin"])
    body = json_body()
    full_name = as_str(req_field(body, "full_name"), "full_name")
    department_code = as_str(req_field(body, "department_code"), "department_code")
    rank = as_enum(req_field(body, "rank"), "rank", PI_RANKS)
    delinquent = as_int(opt_field(body, "delinquent_report_count", 0),
                        "delinquent_report_count")
    if delinquent < 0:
        raise bad_request("Field 'delinquent_report_count' must be >= 0")
    rec = mint({
        "full_name": full_name,
        "department_code": department_code,
        "rank": rank,
        "delinquent_report_count": delinquent,
    })
    store.principal_investigators[rec["id"]] = rec
    return ok_object(pi_out(rec), 201)


@bp.get("/pre-award/principal-investigators/<pid>")
def get_pi(pid):
    authenticate()
    rec = store.principal_investigators.get(pid)
    if rec is None:
        raise not_found("Principal investigator not found")
    return ok_object(pi_out(rec), 200)


# ---------------------------------------------------------------------------
# F&A rate agreements
# ---------------------------------------------------------------------------

def _check_final_overlap(candidate):
    for other in store.fa_rate_agreements.values():
        if other["id"] == candidate["id"]:
            continue
        if other["rate_type"] != candidate["rate_type"]:
            continue
        if other["status"] != "FINAL":
            continue
        if candidate["_start"] < other["_end"] and other["_start"] < candidate["_end"]:
            raise ApiError(
                ERR_RATE_OVERLAP, 409,
                "A FINAL agreement of the same rate type has an overlapping "
                "effectiveness window")


@bp.post("/pre-award/fa-rate-agreements")
def create_rate_agreement():
    require_roles(["OSPDirector"])
    body = json_body()
    rate_type = as_enum(req_field(body, "rate_type"), "rate_type", RATE_TYPES)
    rate_pct = as_number(req_field(body, "rate_pct"), "rate_pct")
    if rate_pct <= 0 or rate_pct > 100:
        raise bad_request("Field 'rate_pct' must be greater than 0 and at most 100")
    start_raw = as_str(req_field(body, "effective_start_on"), "effective_start_on")
    end_raw = as_str(req_field(body, "effective_end_on"), "effective_end_on")
    start = parse_date_value(start_raw, "effective_start_on")
    end = parse_date_value(end_raw, "effective_end_on")
    if end < start:
        raise bad_request("effective_end_on is earlier than effective_start_on")
    initial_status = as_enum(opt_field(body, "initial_status", "PROVISIONAL"),
                             "initial_status", ["PROVISIONAL", "FINAL"])
    rec = mint({
        "rate_type": rate_type,
        "rate_pct": rate_pct,
        "effective_start_on": start_raw,
        "effective_end_on": end_raw,
        "status": initial_status,
        "_start": start,
        "_end": end,
    })
    if initial_status == "FINAL":
        _check_final_overlap(rec)
    store.fa_rate_agreements[rec["id"]] = rec
    return ok_object(rate_out(rec), 201)


@bp.post("/pre-award/fa-rate-agreements/<rid>/finalize")
def finalize_rate_agreement(rid):
    require_roles(["OSPDirector"])
    rec = store.fa_rate_agreements.get(rid)
    if rec is None:
        raise not_found("Rate agreement not found")
    if rec["status"] != "PROVISIONAL":
        raise ApiError(ERR_RATE_AGREEMENT_STATE, 409,
                       "Only a PROVISIONAL rate agreement can be finalized")
    rec["status"] = "FINAL"
    try:
        _check_final_overlap(rec)
    except ApiError:
        rec["status"] = "PROVISIONAL"
        raise
    touch(rec)
    return ok_object(rate_out(rec), 200)


@bp.get("/pre-award/fa-rate-agreements/<rid>")
def get_rate_agreement(rid):
    authenticate()
    rec = store.fa_rate_agreements.get(rid)
    if rec is None:
        raise not_found("Rate agreement not found")
    return ok_object(rate_out(rec), 200)


# ---------------------------------------------------------------------------
# Subrecipient organizations
# ---------------------------------------------------------------------------

AUDIT_STATUSES = ["CURRENT", "DELINQUENT", "NOT_REQUIRED", "MISSING"]


@bp.post("/pre-award/subrecipient-orgs")
def create_sub_org():
    require_roles(["SubrecipientManager"])
    body = json_body()
    legal_name = as_str(req_field(body, "legal_name"), "legal_name")
    uei = as_str(req_field(body, "uei"), "uei")
    is_foreign = as_bool(opt_field(body, "is_foreign", False), "is_foreign")
    audit_status = as_enum(req_field(body, "single_audit_status"),
                           "single_audit_status", AUDIT_STATUSES)
    findings = as_int(opt_field(body, "audit_finding_count", 0),
                      "audit_finding_count")
    if findings < 0:
        raise bad_request("Field 'audit_finding_count' must be >= 0")
    first_time = as_bool(opt_field(body, "first_time_subrecipient", False),
                         "first_time_subrecipient")
    for other in store.subrecipient_orgs.values():
        if other["uei"] == uei:
            raise ApiError(ERR_UEI_NOT_UNIQUE, 409,
                           "A subrecipient organization with this uei already "
                           "exists")
    rec = mint({
        "legal_name": legal_name,
        "uei": uei,
        "is_foreign": is_foreign,
        "single_audit_status": audit_status,
        "audit_finding_count": findings,
        "first_time_subrecipient": first_time,
    })
    rec["risk_score"] = risk_score_standard(rec)
    rec["risk_tier"] = risk_tier_of(rec["risk_score"])
    store.subrecipient_orgs[rec["id"]] = rec
    return ok_object(org_out(rec), 201)


@bp.get("/pre-award/subrecipient-orgs/<oid>")
def get_sub_org(oid):
    authenticate()
    rec = store.subrecipient_orgs.get(oid)
    if rec is None:
        raise not_found("Subrecipient organization not found")
    return ok_object(org_out(rec), 200)


@bp.get("/pre-award/subrecipient-orgs/<oid>/subrecipient-commitments")
def list_org_commitments(oid):
    authenticate()
    rec = store.subrecipient_orgs.get(oid)
    if rec is None:
        raise not_found("Subrecipient organization not found")
    limit, offset = parse_pagination()
    items = [c for c in store.subrecipient_commitments.values()
             if c["subrecipient_org_id"] == oid]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page = items[offset:offset + limit]
    return ok_list([sub_commitment_out(c) for c in page], limit, offset,
                   len(items))
