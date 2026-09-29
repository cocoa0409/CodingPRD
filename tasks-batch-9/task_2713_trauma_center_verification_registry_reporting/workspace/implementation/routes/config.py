"""Global configuration (data dictionary), referral agreements, the logical clock
and outreach adjudication (PRD 3.1, 3.6, 3.8, 2.4)."""
from flask import Blueprint, request

import calc
import cascade
import serializers as ser
from auth import ALL_ROLES, identity, require_roles, require_scope, require_scope_any
from common import iso, new_record, num, sorted_records
from envelope import respond_list, respond_object, touch
from errors import ApiError
from store import clock_now, db, set_clock
from validate import (
    bad,
    check_enum,
    filter_eq,
    get_body,
    paginate,
    req_dt,
    req_int,
    req_str,
)

bp = Blueprint("config", __name__)

FIELD_NAMES = ("iss_abstracted", "gcs_arrival", "mechanism_code", "ed_departure_at")
RULE_KINDS = ("REQUIRED", "RANGE", "CONFORMANCE")
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")


# --- data dictionary ------------------------------------------------------


@bp.route("/data-dictionary-rules", methods=["POST"])
def create_rule():
    user_id, role = identity()
    require_roles(role, ["SystemAdmin"])
    body = get_body()
    field_name = req_str(body, "field_name")
    if field_name not in FIELD_NAMES:
        bad()
    rule_kind = req_str(body, "rule_kind")
    severity = req_str(body, "severity")
    min_value = body.get("min_value")
    max_value = body.get("max_value")
    allowed_codes = body.get("allowed_codes")
    if rule_kind == "RANGE":
        for bound in (min_value, max_value):
            if bound is None or isinstance(bound, bool) or not isinstance(bound, (int, float)):
                bad()
    if rule_kind == "CONFORMANCE":
        if not isinstance(allowed_codes, list) or not allowed_codes:
            bad()
        for code in allowed_codes:
            if not isinstance(code, str):
                bad()
    check_enum(rule_kind, RULE_KINDS)
    check_enum(severity, SEVERITIES)
    for existing in db.rules.values():
        if existing["field_name"] == field_name and existing["rule_kind"] == rule_kind:
            raise ApiError("ERR_DUPLICATE_CONFIGURATION")
    record = new_record(versioned=False)
    record.update(
        {
            "field_name": field_name,
            "rule_kind": rule_kind,
            "severity": severity,
            "min_value": min_value if rule_kind == "RANGE" else None,
            "max_value": max_value if rule_kind == "RANGE" else None,
            "allowed_codes": allowed_codes if rule_kind == "CONFORMANCE" else None,
            "error_weight": calc.ERROR_WEIGHT[severity],
        }
    )
    db.rules[record["id"]] = record
    return respond_object(lambda: ser.rule(record), 201)


@bp.route("/data-dictionary-rules", methods=["GET"])
def list_rules():
    user_id, role = identity()
    require_roles(role, ALL_ROLES)
    records = sorted_records(list(db.rules.values()))
    records = filter_eq(records, "severity")
    records = filter_eq(records, "rule_kind")
    page, meta = paginate(records)
    return respond_list(lambda: [ser.rule(r) for r in page], meta)


# --- referral agreements --------------------------------------------------


def load_agreement(agreement_id):
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND")
    return agreement


@bp.route("/referral-agreements", methods=["POST"])
def draft_agreement():
    user_id, role = identity()
    require_roles(role, ["TraumaProgramManager"])
    body = get_body()
    referring_raw = body.get("referring_center_id")
    require_scope(user_id, role, referring_raw if isinstance(referring_raw, str) else None)
    referring_id = req_str(body, "referring_center_id")
    if referring_id not in db.centers:
        raise ApiError("ERR_CENTER_NOT_FOUND")
    receiving_id = req_str(body, "receiving_center_id")
    if receiving_id not in db.centers:
        raise ApiError("ERR_CENTER_NOT_FOUND")
    effective_from = req_dt(body, "effective_from")
    effective_to = req_dt(body, "effective_to")
    minutes = req_int(body, "guaranteed_acceptance_minutes", 1, 720)
    if not effective_to > effective_from:
        raise ApiError("ERR_INVALID_INTERVAL_DATES")
    record = new_record()
    record.update(
        {
            "referring_center_id": referring_id,
            "receiving_center_id": receiving_id,
            "agreement_status": "DRAFT",
            "effective_from": effective_from,
            "effective_to": effective_to,
            "guaranteed_acceptance_minutes": minutes,
            "activated_at": None,
            "terminated_at": None,
            "termination_reason": None,
        }
    )
    db.agreements[record["id"]] = record
    return respond_object(lambda: ser.agreement(record), 201)


@bp.route("/referral-agreements/<agreement_id>/activate", methods=["POST"])
def activate_agreement(agreement_id):
    user_id, role = identity()
    require_roles(role, ["TraumaProgramManager"])
    agreement = load_agreement(agreement_id)
    # only the guaranteeing (receiving) party may bring an agreement into force
    require_scope(user_id, role, agreement["receiving_center_id"])
    if agreement["agreement_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE")
    conflict = calc.agreement_overlap(
        agreement["effective_from"],
        agreement["effective_to"],
        agreement["referring_center_id"],
        agreement["receiving_center_id"],
        exclude_id=agreement["id"],
    )
    if conflict is not None:
        raise ApiError("ERR_AGREEMENT_INTERVAL_OVERLAP")
    agreement["agreement_status"] = "ACTIVE"
    agreement["activated_at"] = clock_now()
    return respond_object(lambda: ser.agreement(agreement))


@bp.route("/referral-agreements/<agreement_id>/terminate", methods=["POST"])
def terminate_agreement(agreement_id):
    user_id, role = identity()
    require_roles(role, ["TraumaProgramManager"])
    agreement = load_agreement(agreement_id)
    require_scope_any(
        user_id,
        role,
        [agreement["referring_center_id"], agreement["receiving_center_id"]],
    )
    body = get_body()
    reason = req_str(body, "termination_reason")
    if agreement["agreement_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE")
    agreement["agreement_status"] = "TERMINATED"
    agreement["terminated_at"] = clock_now()
    agreement["termination_reason"] = reason
    return respond_object(lambda: ser.agreement(agreement))


# --- the logical clock ----------------------------------------------------


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    user_id, role = identity()
    require_roles(role, ["SystemAdmin"])
    body = get_body()
    instant = req_dt(body, "to_iso8601")
    set_clock(instant)
    return respond_object({"current_utc": iso(instant)})


# --- outreach adjudication ------------------------------------------------


def load_activity(activity_id):
    activity = db.activities.get(activity_id)
    if activity is None:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND")
    return activity


@bp.route("/outreach-activities/<activity_id>/verify", methods=["POST"])
def verify_activity(activity_id):
    user_id, role = identity()
    require_roles(role, ["TraumaMedicalDirector"])
    activity = load_activity(activity_id)
    if activity["verified_status"] not in ("LOGGED", "REJECTED"):
        raise ApiError("ERR_INVALID_OUTREACH_STATE")
    activity["verified_status"] = "VERIFIED"
    activity["reviewed_by_user_id"] = user_id
    center = db.centers.get(activity["center_id"])
    cascade.cascade_center(center, cycles=True)
    return respond_object(lambda: ser.activity(activity))


@bp.route("/outreach-activities/<activity_id>/reject", methods=["POST"])
def reject_activity(activity_id):
    user_id, role = identity()
    require_roles(role, ["TraumaMedicalDirector"])
    activity = load_activity(activity_id)
    body = get_body()
    reason = req_str(body, "rejection_reason")
    if activity["verified_status"] not in ("LOGGED", "VERIFIED"):
        raise ApiError("ERR_INVALID_OUTREACH_STATE")
    activity["verified_status"] = "REJECTED"
    activity["reviewed_by_user_id"] = user_id
    activity["rejection_reason"] = reason
    center = db.centers.get(activity["center_id"])
    cascade.cascade_center(center, cycles=True)
    return respond_object(lambda: ser.activity(activity))
