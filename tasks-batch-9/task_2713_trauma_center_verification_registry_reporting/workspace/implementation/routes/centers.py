"""Trauma centers, activation criteria tiers, the triage-rate read, outreach
logging and the center-scoped reverse lookups (PRD 3.1, 3.5, 3.8)."""
from flask import Blueprint

import calc
import cascade
import serializers as ser
from auth import ALL_ROLES, identity, require_roles, require_scope
from common import D, new_record, num, sorted_records
from envelope import respond_list, respond_object
from errors import ApiError
from store import db
from validate import (
    check_enum,
    filter_eq,
    get_body,
    opt_int,
    paginate,
    query_enum,
    req_dt,
    req_int,
    req_num,
    req_str,
    bad,
)

bp = Blueprint("centers", __name__)

DESIGNATION_LEVELS = ("LEVEL_I", "LEVEL_II", "LEVEL_III")
TIER_CODES = ("TIER_1_FULL", "TIER_2_MODIFIED", "TIER_3_CONSULT")
ACTIVITY_KINDS = ("INJURY_PREVENTION", "PROFESSIONAL_EDUCATION", "COMMUNITY_OUTREACH")
TRIAGE_VARIANTS = ("PROVISIONAL_MONITORING", "VERIFICATION_AUDIT")
REFERRING_ALIASES = ("REFERRING", "REFERRING_CENTER", "OUTBOUND", "OUT", "SENDING")
RECEIVING_ALIASES = ("RECEIVING", "RECEIVING_CENTER", "INBOUND", "IN")

READ_ROLES = ALL_ROLES
CENTER_REPORT_ROLES = [
    "SystemAdmin",
    "TraumaProgramManager",
    "TraumaMedicalDirector",
    "VerificationReviewer",
    "StateDesignationOfficer",
]


def load_center(center_id):
    center = db.centers.get(center_id)
    if center is None:
        raise ApiError("ERR_CENTER_NOT_FOUND")
    return center


@bp.route("/trauma-centers", methods=["POST"])
def register_center():
    user_id, role = identity()
    require_roles(role, ["SystemAdmin"])
    body = get_body()
    name = req_str(body, "name")
    state_code = req_str(body, "state_code")
    if len(state_code) != 2 or not state_code.isalpha() or not state_code.isupper():
        bad()
    designation_level = req_str(body, "designation_level")
    cycle_start = req_dt(body, "verification_cycle_start_date")
    check_enum(designation_level, DESIGNATION_LEVELS)
    record = new_record()
    record.update(
        {
            "name": name,
            "state_code": state_code,
            "designation_level": designation_level,
            "verification_cycle_start_date": cycle_start,
            "national_verification_status": "NOT_VERIFIED",
            "state_designation_status": "NOT_DESIGNATED",
            "readiness_posture": "READY",
            "registry_compliance_score": 100.00,
            "under_triage_rate_pct": 0.00,
            "over_triage_rate_pct": 0.00,
            "outreach_credit_hours_ytd": 0.00,
            "open_critical_deficiency_count": 0,
            "escalated_critical_deficiency_count": 0,
            "open_pi_event_count": 0,
            "closed_pi_event_count": 0,
            "registry_included_case_count": 0,
            "registry_excluded_case_count": 0,
        }
    )
    db.centers[record["id"]] = record
    return respond_object(lambda: ser.center(record), 201)


@bp.route("/trauma-centers/<center_id>", methods=["GET"])
def read_center(center_id):
    user_id, role = identity()
    require_roles(role, READ_ROLES)
    center = load_center(center_id)
    return respond_object(lambda: ser.center(center))


@bp.route("/trauma-centers", methods=["GET"])
def list_centers():
    user_id, role = identity()
    require_roles(role, READ_ROLES)
    records = sorted_records(list(db.centers.values()))
    records = filter_eq(records, "state_code")
    from flask import request

    posture = request.args.get("readiness_posture")
    if posture:
        records = [r for r in records if cascade.posture_of(r) == posture]
    page, meta = paginate(records)
    return respond_list(lambda: [ser.center(r) for r in page], meta)


@bp.route("/trauma-centers/<center_id>/activation-tiers", methods=["POST"])
def create_tier(center_id):
    user_id, role = identity()
    require_roles(role, ["SystemAdmin", "TraumaProgramManager"])
    require_scope(user_id, role, center_id)
    center = load_center(center_id)
    body = get_body()
    tier_code = req_str(body, "tier_code")
    surgeon_limit = req_int(body, "surgeon_response_limit_minutes", 1, 240)
    specialty_limit = req_int(body, "specialty_response_limit_minutes", 1, 240)
    iss_threshold = req_int(body, "iss_threshold", 0, 75)
    check_enum(tier_code, TIER_CODES)
    for existing in db.tiers.values():
        if existing["center_id"] == center_id and existing["tier_code"] == tier_code:
            raise ApiError("ERR_DUPLICATE_CONFIGURATION")
    record = new_record()
    record.update(
        {
            "center_id": center_id,
            "tier_code": tier_code,
            "surgeon_response_limit_minutes": surgeon_limit,
            "specialty_response_limit_minutes": specialty_limit,
            "iss_threshold": iss_threshold,
        }
    )
    db.tiers[record["id"]] = record
    return respond_object(lambda: ser.tier(record), 201)


@bp.route("/trauma-centers/<center_id>/activation-tiers", methods=["GET"])
def list_tiers(center_id):
    user_id, role = identity()
    require_roles(role, READ_ROLES)
    center = load_center(center_id)
    records = sorted_records([t for t in db.tiers.values() if t["center_id"] == center_id])
    records = filter_eq(records, "tier_code")
    page, meta = paginate(records)
    return respond_list(lambda: [ser.tier(r) for r in page], meta)


@bp.route("/trauma-centers/<center_id>/triage-rates", methods=["GET"])
def read_triage_rates(center_id):
    user_id, role = identity()
    require_roles(role, CENTER_REPORT_ROLES)
    center = load_center(center_id)
    variant = query_enum("variant", TRIAGE_VARIANTS, "PROVISIONAL_MONITORING")
    rates = calc.triage_rates(center_id, variant)
    payload = {
        "variant": rates["variant"],
        "denominator_case_count": rates["denominator_case_count"],
        "under_triage_numerator": rates["under_triage_numerator"],
        "over_triage_numerator": rates["over_triage_numerator"],
        "under_triage_rate_pct": num(rates["under_triage_rate_pct"]),
        "over_triage_rate_pct": num(rates["over_triage_rate_pct"]),
    }
    return respond_object(payload)


@bp.route("/trauma-centers/<center_id>/outreach-activities", methods=["POST"])
def log_activity(center_id):
    user_id, role = identity()
    require_roles(role, ["TraumaProgramManager"])
    require_scope(user_id, role, center_id)
    center = load_center(center_id)
    body = get_body()
    activity_kind = req_str(body, "activity_kind")
    event_date = req_dt(body, "event_date")
    credit_hours = req_num(body, "credit_hours", gt=0)
    audience_count = req_int(body, "audience_count", 0)
    check_enum(activity_kind, ACTIVITY_KINDS)
    record = new_record()
    record.update(
        {
            "center_id": center_id,
            "activity_kind": activity_kind,
            "event_date": event_date,
            "credit_hours": credit_hours,
            "audience_count": audience_count,
            "verified_status": "LOGGED",
            "weighted_credit_hours": num(
                calc.weighted_credit_hours(activity_kind, credit_hours)
            ),
            "reviewed_by_user_id": None,
            "rejection_reason": None,
        }
    )
    db.activities[record["id"]] = record
    # A LOGGED activity contributes nothing to the ledger.
    return respond_object(lambda: ser.activity(record), 201)


@bp.route("/trauma-centers/<center_id>/outreach-activities", methods=["GET"])
def list_activities(center_id):
    user_id, role = identity()
    require_roles(role, CENTER_REPORT_ROLES)
    center = load_center(center_id)
    records = calc.activities_of_center(center_id)
    records = filter_eq(records, "verified_status")
    records = filter_eq(records, "activity_kind")
    page, meta = paginate(records)
    return respond_list(lambda: [ser.activity(r) for r in page], meta)


@bp.route("/trauma-centers/<center_id>/referral-agreements", methods=["GET"])
def list_center_agreements(center_id):
    user_id, role = identity()
    require_roles(role, CENTER_REPORT_ROLES)
    center = load_center(center_id)
    from flask import request

    direction = (request.args.get("direction") or "").strip().upper()
    records = sorted_records(list(db.agreements.values()))
    if direction in REFERRING_ALIASES:
        records = [a for a in records if a["referring_center_id"] == center_id]
    elif direction in RECEIVING_ALIASES:
        records = [a for a in records if a["receiving_center_id"] == center_id]
    else:
        records = [
            a
            for a in records
            if a["referring_center_id"] == center_id or a["receiving_center_id"] == center_id
        ]
    records = filter_eq(records, "agreement_status")
    page, meta = paginate(records)
    return respond_list(lambda: [ser.agreement(r) for r in page], meta)


@bp.route("/trauma-centers/<center_id>/verification-cycles", methods=["GET"])
def list_center_cycles(center_id):
    user_id, role = identity()
    require_roles(role, CENTER_REPORT_ROLES)
    center = load_center(center_id)
    records = calc.cycles_of_center(center_id)
    records = filter_eq(records, "cycle_type")
    records = filter_eq(records, "status")
    page, meta = paginate(records)
    return respond_list(lambda: [ser.cycle(r) for r in page], meta)
