"""Reference data routes: jurisdictions, counselors, interpreters, orgs."""

from flask import Blueprint, request

from db import store
from errors import (
    raise_err, invalid_request, not_found, forbidden, invalid_state,
    ERR_JURISDICTION_LEVEL_MISMATCH,
)
from middleware import require_roles
from response import ok_object, ok_list
from serializers import (
    jurisdiction_out, counselor_out, interpreter_out, org_out, note_out,
)
from services import make_record, bump, org_week_reserved, ISSUE_CATEGORIES
from util import (
    get_payload, check_unknown, require, as_str, as_int, as_bool, as_number,
    as_str_array, as_enum, parse_dt, page_of, query_enum,
)

bp = Blueprint("reference", __name__)

LEVELS = ("STATE", "COUNTY", "CITY")
COUNSELOR_STATUSES = ("ACTIVE", "SUSPENDED", "INACTIVE")
ORG_STATUSES = ("ACTIVE", "PAUSED")
COUNSELOR_TRANSITIONS = {
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "INACTIVE"),
    ("SUSPENDED", "INACTIVE"),
}


# ---------------------------------------------------------------------------
# Jurisdictions
# ---------------------------------------------------------------------------

@bp.route("/hotline/jurisdictions", methods=["POST"])
def create_jurisdiction():
    require_roles("AgencyAdmin")
    data = get_payload()
    check_unknown(data, {
        "parent_jurisdiction_id", "code", "name", "level",
        "eviction_notice_days", "habitability_repair_days",
        "deposit_cap_months", "deposit_interest_required",
        "deposit_interest_rate_pct",
    })
    parent_id = data.get("parent_jurisdiction_id")
    if parent_id is not None:
        as_str(parent_id, "parent_jurisdiction_id")
    code = as_str(require(data, "code"), "code")
    name = as_str(require(data, "name"), "name")
    level = as_enum(require(data, "level"), "level", LEVELS)
    eviction_notice_days = as_int(require(data, "eviction_notice_days"), "eviction_notice_days")
    habitability_repair_days = as_int(require(data, "habitability_repair_days"), "habitability_repair_days")
    deposit_cap_months = as_number(require(data, "deposit_cap_months"), "deposit_cap_months")
    deposit_interest_required = as_bool(require(data, "deposit_interest_required"), "deposit_interest_required")
    deposit_interest_rate_pct = as_number(require(data, "deposit_interest_rate_pct"), "deposit_interest_rate_pct")

    # level/parent consistency
    parent = None
    if level == "STATE":
        if parent_id is not None:
            raise_err(ERR_JURISDICTION_LEVEL_MISMATCH, "STATE jurisdiction must have a null parent")
    elif level == "COUNTY":
        if parent_id is None:
            invalid_request("parent_jurisdiction_id is required for COUNTY")
        parent = store.jurisdictions.get(parent_id)
        if parent is None:
            invalid_request("parent jurisdiction does not exist")
        if parent["level"] != "STATE":
            raise_err(ERR_JURISDICTION_LEVEL_MISMATCH, "COUNTY parent must be a STATE")
    elif level == "CITY":
        if parent_id is None:
            invalid_request("parent_jurisdiction_id is required for CITY")
        parent = store.jurisdictions.get(parent_id)
        if parent is None:
            invalid_request("parent jurisdiction does not exist")
        if parent["level"] != "COUNTY":
            raise_err(ERR_JURISDICTION_LEVEL_MISMATCH, "CITY parent must be a COUNTY")

    # code unique across all jurisdictions
    for j in store.jurisdictions.values():
        if j["code"] == code:
            invalid_request("jurisdiction code already exists: %s" % code)

    rec = make_record({
        "parent_jurisdiction_id": parent_id,
        "code": code,
        "name": name,
        "level": level,
        "eviction_notice_days": eviction_notice_days,
        "habitability_repair_days": habitability_repair_days,
        "deposit_cap_months": deposit_cap_months,
        "deposit_interest_required": deposit_interest_required,
        "deposit_interest_rate_pct": deposit_interest_rate_pct,
    })
    store.jurisdictions[rec["id"]] = rec
    return ok_object(jurisdiction_out(rec), status=201)


@bp.route("/hotline/jurisdictions/<jid>", methods=["GET"])
def get_jurisdiction(jid):
    require_roles("AgencyAdmin", "Counselor", "HotlineSupervisor", "DataProtectionOfficer", "Analyst")
    rec = store.jurisdictions.get(jid)
    if rec is None:
        not_found("jurisdiction not found")
    return ok_object(jurisdiction_out(rec))


@bp.route("/hotline/jurisdictions", methods=["GET"])
def list_jurisdictions():
    require_roles("AgencyAdmin", "Counselor", "HotlineSupervisor", "DataProtectionOfficer", "Analyst")
    parent_filter = request.args.get("parent_jurisdiction_id")
    level = query_enum("level", LEVELS)
    recs = list(store.jurisdictions.values())
    if parent_filter is not None:
        recs = [r for r in recs if r["parent_jurisdiction_id"] == parent_filter]
    if level is not None:
        recs = [r for r in recs if r["level"] == level]
    page, total, limit, offset = page_of(recs)
    return ok_list([jurisdiction_out(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Counselors
# ---------------------------------------------------------------------------

@bp.route("/hotline/counselors", methods=["POST"])
def create_counselor():
    require_roles("AgencyAdmin")
    data = get_payload()
    check_unknown(data, {
        "display_name", "languages", "certified_jurisdiction_codes",
        "certified_categories", "certification_expires_at", "is_script_reviewer",
    })
    display_name = as_str(require(data, "display_name"), "display_name")
    languages = as_str_array(require(data, "languages"), "languages")
    certified_jurisdiction_codes = as_str_array(
        require(data, "certified_jurisdiction_codes"), "certified_jurisdiction_codes")
    certified_categories = as_str_array(
        require(data, "certified_categories"), "certified_categories")
    for c in certified_categories:
        if c not in ISSUE_CATEGORIES:
            invalid_request("certified_categories must contain only: %s" % ", ".join(ISSUE_CATEGORIES))
    certification_expires_at = parse_dt(require(data, "certification_expires_at"), "certification_expires_at")
    is_script_reviewer = data.get("is_script_reviewer", False)
    as_bool(is_script_reviewer, "is_script_reviewer")

    rec = make_record({
        "display_name": display_name,
        "languages": languages,
        "certified_jurisdiction_codes": certified_jurisdiction_codes,
        "certified_categories": certified_categories,
        "certification_expires_at": certification_expires_at,
        "is_script_reviewer": is_script_reviewer,
        "trained_script_ids": [],
        "status": "ACTIVE",
    })
    store.counselors[rec["id"]] = rec
    return ok_object(counselor_out(rec), status=201)


@bp.route("/hotline/counselors/<cid>", methods=["GET"])
def get_counselor(cid):
    require_roles("AgencyAdmin", "Counselor", "HotlineSupervisor", "DataProtectionOfficer")
    rec = store.counselors.get(cid)
    if rec is None:
        not_found("counselor not found")
    return ok_object(counselor_out(rec))


@bp.route("/hotline/counselors/<cid>", methods=["PATCH"])
def patch_counselor(cid):
    require_roles("AgencyAdmin")
    rec = store.counselors.get(cid)
    if rec is None:
        not_found("counselor not found")
    data = get_payload()
    check_unknown(data, {
        "display_name", "languages", "certified_jurisdiction_codes",
        "certified_categories", "certification_expires_at", "is_script_reviewer", "status",
    })
    new_status = None
    if "status" in data:
        new_status = as_enum(data["status"], "status", COUNSELOR_STATUSES)
        if new_status != rec["status"] and (rec["status"], new_status) not in COUNSELOR_TRANSITIONS:
            invalid_state("counselor status transition %s -> %s is not allowed"
                          % (rec["status"], new_status))
    if "display_name" in data:
        rec["display_name"] = as_str(data["display_name"], "display_name")
    if "languages" in data:
        rec["languages"] = as_str_array(data["languages"], "languages")
    if "certified_jurisdiction_codes" in data:
        rec["certified_jurisdiction_codes"] = as_str_array(
            data["certified_jurisdiction_codes"], "certified_jurisdiction_codes")
    if "certified_categories" in data:
        cats = as_str_array(data["certified_categories"], "certified_categories")
        for c in cats:
            if c not in ISSUE_CATEGORIES:
                invalid_request("certified_categories must contain only: %s" % ", ".join(ISSUE_CATEGORIES))
        rec["certified_categories"] = cats
    if "certification_expires_at" in data:
        rec["certification_expires_at"] = parse_dt(data["certification_expires_at"], "certification_expires_at")
    if "is_script_reviewer" in data:
        rec["is_script_reviewer"] = as_bool(data["is_script_reviewer"], "is_script_reviewer")
    if new_status is not None:
        rec["status"] = new_status
    bump(rec)
    return ok_object(counselor_out(rec))


@bp.route("/hotline/counselors/<cid>/training-certifications", methods=["POST"])
def record_training(cid):
    _, uid = require_roles("HotlineSupervisor")
    rec = store.counselors.get(cid)
    if rec is None:
        not_found("counselor not found")
    # the acting supervisor's identifier must differ from the subject counselor's
    if uid == cid:
        forbidden("training-certifications actor must differ from the subject counselor")
    data = get_payload()
    check_unknown(data, {"script_id", "score"})
    script_id = as_str(require(data, "script_id"), "script_id")
    score = as_int(require(data, "score"), "score")
    script = store.scripts.get(script_id)
    if script is None:
        invalid_request("script_id does not reference an existing script")
    if score >= 80 and script["status"] in ("PUBLISHED", "SUPERSEDED"):
        if script_id not in rec["trained_script_ids"]:
            rec["trained_script_ids"].append(script_id)
            bump(rec)
    return ok_object(counselor_out(rec), status=201)


@bp.route("/hotline/counselors/<cid>/notes", methods=["GET"])
def list_counselor_notes(cid):
    require_roles("HotlineSupervisor", "DataProtectionOfficer")
    rec = store.counselors.get(cid)
    if rec is None:
        not_found("counselor not found")
    recs = [n for n in store.notes.values() if n["counselor_id"] == cid]
    page, total, limit, offset = page_of(recs)
    return ok_list([note_out(n) for n in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Interpreters
# ---------------------------------------------------------------------------

@bp.route("/hotline/interpreters", methods=["POST"])
def create_interpreter():
    require_roles("AgencyAdmin")
    data = get_payload()
    check_unknown(data, {"display_name", "language_code"})
    rec = make_record({
        "display_name": as_str(require(data, "display_name"), "display_name"),
        "language_code": as_str(require(data, "language_code"), "language_code"),
    })
    store.interpreters[rec["id"]] = rec
    return ok_object(interpreter_out(rec), status=201)


@bp.route("/hotline/interpreters/<iid>", methods=["GET"])
def get_interpreter(iid):
    require_roles("AgencyAdmin", "Counselor", "HotlineSupervisor")
    rec = store.interpreters.get(iid)
    if rec is None:
        not_found("interpreter not found")
    return ok_object(interpreter_out(rec))


# ---------------------------------------------------------------------------
# Legal-aid organizations
# ---------------------------------------------------------------------------

@bp.route("/hotline/legal-aid-orgs", methods=["POST"])
def create_org():
    require_roles("AgencyAdmin")
    data = get_payload()
    check_unknown(data, {"name", "covered_jurisdiction_codes", "accepted_categories", "weekly_capacity"})
    name = as_str(require(data, "name"), "name")
    covered = as_str_array(require(data, "covered_jurisdiction_codes"), "covered_jurisdiction_codes")
    accepted = as_str_array(require(data, "accepted_categories"), "accepted_categories")
    for c in accepted:
        if c not in ISSUE_CATEGORIES:
            invalid_request("accepted_categories must contain only: %s" % ", ".join(ISSUE_CATEGORIES))
    weekly_capacity = as_int(require(data, "weekly_capacity"), "weekly_capacity")
    if weekly_capacity < 0:
        invalid_request("weekly_capacity must be >= 0")
    rec = make_record({
        "name": name,
        "covered_jurisdiction_codes": covered,
        "accepted_categories": accepted,
        "weekly_capacity": weekly_capacity,
        "status": "ACTIVE",
    })
    store.orgs[rec["id"]] = rec
    return ok_object(org_out(rec, org_week_reserved(rec["id"])), status=201)


@bp.route("/hotline/legal-aid-orgs/<oid>", methods=["GET"])
def get_org(oid):
    require_roles("AgencyAdmin", "Counselor", "HotlineSupervisor")
    rec = store.orgs.get(oid)
    if rec is None:
        not_found("legal-aid org not found")
    return ok_object(org_out(rec, org_week_reserved(rec["id"])))


@bp.route("/hotline/legal-aid-orgs/<oid>", methods=["PATCH"])
def patch_org(oid):
    require_roles("AgencyAdmin")
    rec = store.orgs.get(oid)
    if rec is None:
        not_found("legal-aid org not found")
    data = get_payload()
    check_unknown(data, {"status", "weekly_capacity"})
    if "status" in data:
        new_status = as_enum(data["status"], "status", ORG_STATUSES)
        rec["status"] = new_status
    if "weekly_capacity" in data:
        cap = as_int(data["weekly_capacity"], "weekly_capacity")
        if cap < 0:
            invalid_request("weekly_capacity must be >= 0")
        rec["weekly_capacity"] = cap
    bump(rec)
    return ok_object(org_out(rec, org_week_reserved(rec["id"])))
