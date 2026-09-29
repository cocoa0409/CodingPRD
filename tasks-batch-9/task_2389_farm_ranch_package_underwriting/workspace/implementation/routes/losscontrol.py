"""Inspections, loss-control recommendations and the compliance checkpoint."""

from flask import Blueprint

import calc
import services
from auth import (
    ADMIN, AGENT, ALL_ROLES, COMPLIANCE, LOSS_CONTROL, UNDERWRITER,
    authenticate, guard_account, is_agent, user_id,
)
from db import by_created, new_row, now_str, parse_date, parse_datetime, store, today, touch
from errors import ApiError, bad_request
from response import ok, ok_list, created, paginate
from validation import enum_filter, field, pagination, read_body, str_filter, validate

bp = Blueprint("losscontrol", __name__)

INSPECTION_TYPES = ("INITIAL", "RE_INSPECTION", "LOSS_TRIGGERED")
INSPECTION_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED")
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
RECOMMENDATION_STATUSES = ("OPEN", "OVERDUE", "SUBMITTED", "VERIFIED", "WAIVED")

FINDING_SPECS = [
    field("severity", "string", required=True, enum=SEVERITIES),
    field("description", "string", required=True, minlen=1, maxlen=240),
    field("due_date", "date", required=True),
]


def _guard_inspection_read(inspection):
    policy = store.policies.get(inspection["policy_id"])
    if policy is not None:
        guard_account(services.account_of_policy(policy))
    return policy


def _calendar_checks(inspector, start_dt, duration_minutes, exclude_id=None):
    """Priority-12 calendar trio: conflict, then day load, then standing."""
    if services.window_conflict(inspector["id"], start_dt, duration_minutes, exclude_id):
        raise ApiError("ERR_INSPECTOR_WINDOW_CONFLICT")
    booked = services.day_load(inspector["id"], start_dt, exclude_id)
    if booked + duration_minutes > inspector["daily_capacity_minutes"]:
        raise ApiError("ERR_INSPECTOR_DAY_CAPACITY_EXCEEDED")
    if inspector["status"] != "ACTIVE":
        raise ApiError("ERR_INSPECTOR_INACTIVE")


# ---------------------------------------------------------------- inspections

@bp.route("/inspections", methods=["POST"])
def create_inspection():
    authenticate(UNDERWRITER, COMPLIANCE)
    body = validate(read_body(), [
        field("policy_id", "string", required=True, minlen=1),
        field("inspector_id", "string", required=True, minlen=1),
        field("inspection_type", "string", required=True, enum=INSPECTION_TYPES),
        field("scheduled_for", "datetime", required=True),
        field("duration_minutes", "int", required=True, ge=30, le=480),
    ])
    policy = services.require(store.policies, body["policy_id"], "ERR_FARM_POLICY_NOT_FOUND")
    inspector = services.require(
        store.inspectors, body["inspector_id"], "ERR_INSPECTOR_NOT_FOUND"
    )
    services.guard_policy_open(policy)

    start_dt = parse_datetime(body["scheduled_for"])
    _calendar_checks(inspector, start_dt, body["duration_minutes"])

    row = new_row(
        policy_id=policy["id"],
        inspector_id=inspector["id"],
        inspection_type=body["inspection_type"],
        scheduled_for=body["scheduled_for"],
        duration_minutes=body["duration_minutes"],
        status="SCHEDULED",
        completed_at=None,
        hazard_score=0,
        findings_summary=None,
        recommendation_count=0,
    )
    row["_scheduled_for"] = start_dt
    store.inspections[row["id"]] = row
    return created(row)


@bp.route("/inspections/<inspection_id>", methods=["GET"])
def get_inspection(inspection_id):
    authenticate(*ALL_ROLES)
    inspection = services.require(store.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
    _guard_inspection_read(inspection)
    return ok(inspection)


@bp.route("/inspections", methods=["GET"])
def list_inspections():
    authenticate(*ALL_ROLES)
    limit, offset = pagination()
    policy_id = str_filter("policy_id")
    inspector_id = str_filter("inspector_id")
    status = enum_filter("status", INSPECTION_STATUSES)
    inspection_type = enum_filter("inspection_type", INSPECTION_TYPES)
    rows = []
    for inspection in store.inspections.values():
        if policy_id is not None and inspection["policy_id"] != policy_id:
            continue
        if inspector_id is not None and inspection["inspector_id"] != inspector_id:
            continue
        if status is not None and inspection["status"] != status:
            continue
        if inspection_type is not None and inspection["inspection_type"] != inspection_type:
            continue
        if is_agent():
            policy = store.policies.get(inspection["policy_id"])
            account = services.account_of_policy(policy) if policy else None
            if account is None or account["agent_id"] != user_id():
                continue
        rows.append(inspection)
    window, total = paginate(by_created(rows), limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/inspections/<inspection_id>/complete", methods=["POST"])
def complete_inspection(inspection_id):
    actor, _role = authenticate(LOSS_CONTROL)
    body = validate(read_body(), [
        field("findings_summary", "string", required=True, minlen=1),
        field("findings", "array", required=True),
    ])
    findings = body["findings"]
    for element in findings:
        if not isinstance(element, dict):
            raise bad_request("Each finding must be a JSON object.")
        validate(element, FINDING_SPECS)

    inspection = services.require(store.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
    if inspection["inspector_id"] != actor:
        raise ApiError("ERR_NOT_ASSIGNED_INSPECTOR")
    policy = store.policies.get(inspection["policy_id"])
    services.guard_policy_open(policy)
    if inspection["status"] != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")

    # Hop one: the inspection itself.
    inspection["status"] = "COMPLETED"
    inspection["completed_at"] = now_str()
    inspection["findings_summary"] = body["findings_summary"]
    inspection["recommendation_count"] = len(findings)
    inspection["hazard_score"] = calc.hazard_score(inspection["inspection_type"], findings)
    existing = services.recommendations_of_inspection(inspection["id"])
    next_seq = (existing[-1]["sequence_no"] + 1) if existing else 1
    for offset, element in enumerate(findings):
        row = new_row(
            inspection_id=inspection["id"],
            severity=element["severity"],
            description=element["description"],
            due_date=element["due_date"],
            sequence_no=next_seq + offset,
            status="OPEN",
            evidence_note=None,
            completed_date=None,
            reviewed_by_user_id=None,
        )
        store.recommendations[row["id"]] = row
    touch(inspection)

    # Hops two through four: the compliance axis and its endorsement cascade.
    if findings:
        if policy["compliance_status"] in ("NOT_INSPECTED", "COMPLIANT"):
            policy["compliance_status"] = "RECS_OPEN"
            services.suspend_inspection_endorsements(policy)
    elif not services.unresolved_recommendations(policy["id"]):
        if policy["compliance_status"] != "COMPLIANT":
            services.move_to_compliant(policy)
    touch(policy)
    return ok(inspection)


@bp.route("/inspections/<inspection_id>/reinspection", methods=["POST"])
def reinspect(inspection_id):
    authenticate(UNDERWRITER, COMPLIANCE)
    body = validate(read_body(), [
        field("scheduled_for", "datetime", required=True),
        field("duration_minutes", "int", required=True, ge=30, le=480),
    ])
    inspection = services.require(store.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
    policy = store.policies.get(inspection["policy_id"])
    services.guard_policy_open(policy)
    if inspection["status"] != "COMPLETED":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")

    inspector = store.inspectors.get(inspection["inspector_id"])
    if inspector is None:
        raise ApiError("ERR_INSPECTOR_NOT_FOUND")
    start_dt = parse_datetime(body["scheduled_for"])
    _calendar_checks(inspector, start_dt, body["duration_minutes"], exclude_id=inspection["id"])

    inspection["status"] = "SCHEDULED"
    inspection["inspection_type"] = "RE_INSPECTION"
    inspection["scheduled_for"] = body["scheduled_for"]
    inspection["_scheduled_for"] = start_dt
    inspection["duration_minutes"] = body["duration_minutes"]
    inspection["completed_at"] = None
    touch(inspection)
    return ok(inspection)


# ------------------------------------------------------------ recommendations

@bp.route("/inspections/<inspection_id>/recommendations", methods=["GET"])
def list_recommendations(inspection_id):
    authenticate(*ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", RECOMMENDATION_STATUSES)
    severity = enum_filter("severity", SEVERITIES)
    inspection = services.require(store.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
    _guard_inspection_read(inspection)
    rows = [
        r for r in services.recommendations_of_inspection(inspection["id"])
        if (status is None or r["status"] == status)
        and (severity is None or r["severity"] == severity)
    ]
    window, total = paginate(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/recommendations/<recommendation_id>", methods=["GET"])
def get_recommendation(recommendation_id):
    authenticate(*ALL_ROLES)
    recommendation = services.require(
        store.recommendations, recommendation_id, "ERR_RECOMMENDATION_NOT_FOUND"
    )
    inspection = services.inspection_of_recommendation(recommendation)
    if inspection is not None:
        _guard_inspection_read(inspection)
    return ok(recommendation)


@bp.route("/recommendations/<recommendation_id>/evidence", methods=["POST"])
def submit_evidence(recommendation_id):
    authenticate(AGENT)
    body = validate(read_body(), [
        field("evidence_note", "string", required=True, minlen=1),
        field("completed_date", "date", required=True),
    ])
    recommendation = services.require(
        store.recommendations, recommendation_id, "ERR_RECOMMENDATION_NOT_FOUND"
    )
    inspection = services.inspection_of_recommendation(recommendation)
    policy = store.policies.get(inspection["policy_id"]) if inspection else None
    guard_account(services.account_of_policy(policy) if policy else None)
    if policy is not None:
        services.guard_policy_open(policy)
    if recommendation["status"] not in ("OPEN", "OVERDUE"):
        raise ApiError("ERR_RECOMMENDATION_STATE_INVALID")

    recommendation["evidence_note"] = body["evidence_note"]
    recommendation["completed_date"] = body["completed_date"]
    recommendation["status"] = "SUBMITTED"
    touch(recommendation)
    return ok(recommendation)


@bp.route("/recommendations/<recommendation_id>/review", methods=["POST"])
def review_recommendation(recommendation_id):
    actor, _role = authenticate(COMPLIANCE)
    body = validate(read_body(), [
        field("decision", "string", required=True, enum=("ACCEPT", "REJECT", "WAIVE")),
        field("review_note", "string", minlen=1),
    ])
    recommendation = services.require(
        store.recommendations, recommendation_id, "ERR_RECOMMENDATION_NOT_FOUND"
    )
    inspection = services.inspection_of_recommendation(recommendation)
    policy = store.policies.get(inspection["policy_id"]) if inspection else None
    if policy is not None:
        services.guard_policy_open(policy)

    decision = body["decision"]
    if decision in ("ACCEPT", "REJECT"):
        if recommendation["status"] != "SUBMITTED":
            raise ApiError("ERR_RECOMMENDATION_STATE_INVALID")
    elif recommendation["status"] not in ("OPEN", "OVERDUE", "SUBMITTED"):
        raise ApiError("ERR_RECOMMENDATION_STATE_INVALID")

    recommendation["reviewed_by_user_id"] = actor
    if decision == "ACCEPT":
        recommendation["status"] = "VERIFIED"
    elif decision == "REJECT":
        recommendation["status"] = "OPEN"
    else:
        recommendation["status"] = "WAIVED"
    touch(recommendation)

    if (
        decision in ("ACCEPT", "WAIVE")
        and policy is not None
        and policy["compliance_status"] in ("RECS_OPEN", "RECS_OVERDUE", "SUSPENDED")
        and not services.unresolved_recommendations(policy["id"])
    ):
        services.move_to_compliant(policy)
        touch(policy)
    return ok(recommendation)


# ------------------------------------------------------------ compliance sweep

@bp.route("/compliance-sweeps", methods=["POST"])
def compliance_sweep():
    authenticate(COMPLIANCE, ADMIN)
    body = validate(read_body(), [field("policy_id", "string", minlen=1)])
    if "policy_id" in body:
        policies = [
            services.require(store.policies, body["policy_id"], "ERR_FARM_POLICY_NOT_FOUND")
        ]
    else:
        policies = by_created(list(store.policies.values()))

    clock_date = today()
    counters = {
        "policies_scanned": 0,
        "recommendations_marked_overdue": 0,
        "policies_marked_recs_overdue": 0,
        "policies_suspended": 0,
        "labor_profiles_lapsed": 0,
    }

    for policy in policies:
        counters["policies_scanned"] += 1
        aged_any = False
        for recommendation in services.recommendations_of_policy(policy["id"]):
            if recommendation["status"] != "OPEN":
                continue
            due = parse_date(recommendation["due_date"])
            if due is not None and due < clock_date:
                recommendation["status"] = "OVERDUE"
                touch(recommendation)
                counters["recommendations_marked_overdue"] += 1
                aged_any = True
        if aged_any and policy["compliance_status"] == "RECS_OPEN":
            policy["compliance_status"] = "RECS_OVERDUE"
            touch(policy)
            counters["policies_marked_recs_overdue"] += 1
        if (
            policy["compliance_status"] == "RECS_OVERDUE"
            and policy["uw_status"] in ("RATED", "BOUND")
            and any(
                r["severity"] == "CRITICAL" and r["status"] == "OVERDUE"
                for r in services.recommendations_of_policy(policy["id"])
            )
        ):
            policy["compliance_status"] = "SUSPENDED"
            services.suspend_inspection_endorsements(policy)
            touch(policy)
            counters["policies_suspended"] += 1

    scanned_ids = {p["id"] for p in policies}
    for profile in by_created(list(store.labor_profiles.values())):
        if profile["policy_id"] not in scanned_ids:
            continue
        if profile.get("coordination_status") != "VERIFIED":
            continue
        expiry = parse_date(profile.get("wc_expiry_date"))
        if expiry is None or expiry >= clock_date:
            continue
        profile["coordination_status"] = "LAPSED"
        profile["verified_at"] = None
        profile["verified_by_user_id"] = None
        touch(profile)
        counters["labor_profiles_lapsed"] += 1

    return ok(counters)
