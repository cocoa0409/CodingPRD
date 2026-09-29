"""Segments, destinations and the activation lifecycle."""

import re
from datetime import timedelta

from flask import Blueprint, request

import db
import middleware
import response
import validators
from errors import ApiError
from routes import common
from services import activation as activation_service
from services import cascade, derive

bp = Blueprint("audience", __name__)

DEST_CODE_RE = re.compile(r"^[A-Z0-9_]+$")
OPERATORS = ("EQ", "GTE", "IN")
SEGMENT_DECISIONS = ("APPROVE", "REJECT")
PLATFORM_KINDS = ("ADVERTISING", "MESSAGING")
HASHING = ("SHA256_EMAIL_LOWER", "SHA256_PHONE_E164")
RATE_BASES = ("GROSS", "NET")
DEST_STATUSES = ("ACTIVE", "INACTIVE")
ATTRIBUTION_BASES = ("TOTAL", "INCREMENTAL")
SUBMITTABLE = ("DRAFT", "GOVERNANCE_EXPIRED")
RETIRABLE = ("DRAFT", "APPROVED", "GOVERNANCE_EXPIRED")


# ---------------------------------------------------------------- segments

def _parse_criteria(body):
    raw_list = validators.req_array(body, "criteria", 1, 6)
    criteria = []
    for index, raw in enumerate(raw_list):
        element = validators.sub_object(raw, "criteria[%d]" % index)
        label = "criteria[%d]" % index
        attribute = validators.req_enum(element, "attribute", derive.SEGMENT_ATTRIBUTES)
        operator = validators.req_enum(element, "operator", OPERATORS)
        if "value" not in element or element["value"] is None:
            raise validators.invalid("%s.value is required." % label)
        value = element["value"]
        if operator == "IN":
            if not isinstance(value, list) or len(value) == 0:
                raise validators.invalid("%s.value must be a non-empty array for IN." % label)
        elif isinstance(value, (list, dict)):
            raise validators.invalid("%s.value must be a scalar." % label)
        criteria.append({"attribute": attribute, "operator": operator, "value": value})
    return criteria


@bp.post("/cdp/segments")
def create_segment():
    middleware.require_role(middleware.ROLE_ANALYST)
    body = validators.body_object()
    name = validators.req_str(body, "name", 1, 120)
    criteria = _parse_criteria(body)
    justification = validators.opt_str(body, "governance_justification", 10, 500)
    valid_days = validators.opt_int(body, "governance_valid_days", 1, 365, 90)
    entity = db.new_entity(
        "segments",
        name=name,
        criteria=criteria,
        uses_sensitive_attributes=derive.uses_sensitive(criteria),
        governance_justification=justification,
        governance_valid_days=valid_days,
        status="DRAFT",
        submitted_by_user_id=None,
        decided_by_user_id=None,
        sensitive_use_approved=False,
        approved_at=None,
        governance_expires_at=None,
        rejection_count=0,
    )
    return common.one("segments", entity, 201)


@bp.get("/cdp/segments/<segment_id>")
def read_segment(segment_id):
    middleware.require_role(*middleware.READ_ROLES)
    return common.one("segments", common.segment(segment_id))


@bp.get("/cdp/segments")
def list_segments():
    middleware.require_role(*middleware.READ_ROLES)
    return common.collection_list(
        "segments",
        {"status": "status", "uses_sensitive_attributes": "uses_sensitive_attributes"},
        common.seq_sort,
    )


@bp.post("/cdp/segments/<segment_id>/submit-for-review")
def submit_segment(segment_id):
    middleware.require_role(middleware.ROLE_ANALYST)
    validators.body_object(required=False)
    entity = common.segment(segment_id)
    common.require_status(entity, SUBMITTABLE)
    if entity["uses_sensitive_attributes"]:
        justification = entity["governance_justification"]
        if justification is None or len(justification.strip()) < 10:
            raise ApiError("ERR_GOVERNANCE_JUSTIFICATION_REQUIRED")
    entity["status"] = "PENDING_GOVERNANCE_REVIEW"
    entity["submitted_by_user_id"] = middleware.actor_id()
    db.touch(entity)
    return common.one("segments", entity)


@bp.post("/cdp/segments/<segment_id>/governance-decision")
def decide_segment(segment_id):
    middleware.require_role(middleware.ROLE_GOVERNANCE)
    body = validators.body_object()
    decision = validators.req_enum(body, "decision", SEGMENT_DECISIONS)
    sensitive_approved = validators.opt_bool(body, "sensitive_use_approved", False)
    entity = common.segment(segment_id)
    common.require_status(entity, ("PENDING_GOVERNANCE_REVIEW",))
    actor = middleware.actor_id()
    if entity["submitted_by_user_id"] == actor:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if decision == "APPROVE":
        if entity["uses_sensitive_attributes"] and sensitive_approved is not True:
            raise ApiError("ERR_GOVERNANCE_JUSTIFICATION_REQUIRED")
        entity["status"] = "APPROVED"
        entity["sensitive_use_approved"] = bool(sensitive_approved)
        entity["approved_at"] = db.now()
        entity["governance_expires_at"] = db.now() + timedelta(days=entity["governance_valid_days"])
    else:
        entity["status"] = "DRAFT"
        entity["rejection_count"] += 1
        entity["sensitive_use_approved"] = False
        entity["submitted_by_user_id"] = None
    entity["decided_by_user_id"] = actor
    db.touch(entity)
    return common.one("segments", entity)


@bp.post("/cdp/segments/<segment_id>/retire")
def retire_segment(segment_id):
    middleware.require_role(middleware.ROLE_ANALYST, middleware.ROLE_GOVERNANCE)
    validators.body_object(required=False)
    entity = common.segment(segment_id)
    if middleware.actor_role() == middleware.ROLE_ANALYST:
        common.require_status(entity, ("DRAFT",))
    else:
        common.require_status(entity, RETIRABLE)
    cascade.retire_segment(entity)
    return common.one("segments", entity)


@bp.get("/cdp/segments/<segment_id>/performance")
def segment_performance(segment_id):
    middleware.require_role(*middleware.REPORT_ROLES)
    basis = validators.query_enum("attribution_basis", ATTRIBUTION_BASES, "TOTAL")
    entity = common.segment(segment_id)
    return response.object_response(activation_service.performance(entity, basis))


@bp.get("/cdp/segments/<segment_id>/overlap")
def segment_overlap(segment_id):
    middleware.require_role(*middleware.REPORT_ROLES)
    other_id = validators.query_str("other_segment_id")
    if other_id is None:
        raise validators.invalid("other_segment_id is required.")
    entity = common.segment(segment_id)
    other = common.segment(other_id)
    if other["id"] == entity["id"]:
        raise ApiError("ERR_OVERLAP_SAME_SEGMENT")
    return response.object_response(activation_service.overlap(entity, other))


# ------------------------------------------------------------ destinations

@bp.post("/cdp/destinations")
def create_destination():
    middleware.require_role(middleware.ROLE_ADMIN)
    body = validators.body_object()
    code = validators.req_str(body, "code", 3, 24, DEST_CODE_RE)
    platform_kind = validators.req_enum(body, "platform_kind", PLATFORM_KINDS)
    channel = validators.req_enum(body, "channel", ("EMAIL", "SMS", "PUSH", "DIRECT_MAIL", "ADVERTISING"))
    hashing = validators.req_enum(body, "hashing_algorithm", HASHING)
    quota = validators.req_int(body, "daily_hash_quota", 1)
    basis = validators.opt_enum(body, "match_rate_basis", RATE_BASES, "GROSS")
    min_rate = validators.opt_decimal(body, "min_match_rate", 0, 1, 4, 0.70)
    min_audience = validators.opt_int(body, "min_audience_size", 1, None, 50)
    cooldown = validators.opt_int(body, "cooldown_minutes", 0, None, 60)
    max_concurrent = validators.opt_int(body, "max_concurrent_activations", 1, None, 2)
    sensitive = validators.opt_bool(body, "sensitive_attribute_permitted", False)
    sla_hours = validators.opt_int(body, "deletion_ack_sla_hours", 1, None, 72)
    status = validators.opt_enum(body, "status", DEST_STATUSES, "ACTIVE")
    if any(d["code"] == code for d in db.all_of("destinations")):
        raise ApiError("ERR_DUPLICATE_CODE")
    entity = db.new_entity(
        "destinations",
        code=code,
        platform_kind=platform_kind,
        channel=channel,
        hashing_algorithm=hashing,
        match_rate_basis=basis,
        min_match_rate=min_rate,
        min_audience_size=min_audience,
        daily_hash_quota=quota,
        remaining_daily_hash_quota=quota,
        quota_reset_on=db.date_str(db.now()),
        cooldown_minutes=cooldown,
        max_concurrent_activations=max_concurrent,
        sensitive_attribute_permitted=bool(sensitive),
        deletion_ack_sla_hours=sla_hours,
        status=status,
    )
    return common.one("destinations", entity, 201)


@bp.get("/cdp/destinations/<destination_id>")
def read_destination(destination_id):
    middleware.require_role(*middleware.READ_ROLES)
    return common.one("destinations", common.destination(destination_id))


@bp.get("/cdp/destinations")
def list_destinations():
    middleware.require_role(*middleware.READ_ROLES)
    return common.collection_list(
        "destinations",
        {"platform_kind": "platform_kind", "channel": "channel", "status": "status"},
        common.seq_sort,
    )


# ------------------------------------------------------------- activations

def _sensitive_blocked(segment, destination):
    if not segment["uses_sensitive_attributes"]:
        return False
    if not segment["sensitive_use_approved"]:
        return True
    return not destination["sensitive_attribute_permitted"]


def _require_governance(segment):
    if segment["status"] != "APPROVED":
        raise ApiError("ERR_GOVERNANCE_NOT_APPROVED")
    expires = segment["governance_expires_at"]
    if expires is None or db.now() >= expires:
        raise ApiError("ERR_GOVERNANCE_NOT_APPROVED")


def _resolve_and_gate(activation, segment, destination):
    """Compute the four counts, apply the three gates, then commit the counts."""
    counts = cascade.resolve_audience(segment, destination)
    if counts["audience_size"] < 1:
        raise ApiError("ERR_EMPTY_AUDIENCE")
    if counts["audience_size"] < destination["min_audience_size"]:
        raise ApiError("ERR_AUDIENCE_BELOW_K_ANONYMITY")
    if counts["dispatched_hash_count"] > destination["remaining_daily_hash_quota"]:
        raise ApiError("ERR_HASH_QUOTA_EXCEEDED")
    activation["candidate_count"] = counts["candidate_count"]
    activation["audience_size"] = counts["audience_size"]
    activation["suppressed_count"] = counts["suppressed_count"]
    activation["dispatched_hash_count"] = counts["dispatched_hash_count"]
    return counts


@bp.post("/cdp/activations")
def create_activation():
    middleware.require_role(middleware.ROLE_ANALYST)
    body = validators.body_object()
    segment_id = validators.req_id(body, "segment_id")
    destination_id = validators.req_id(body, "destination_id")
    window_start = validators.req_ts(body, "window_start_at")
    window_end = validators.req_ts(body, "window_end_at")
    expected_version = validators.req_int(body, "expected_segment_version", 1)

    segment = common.segment(segment_id)
    destination = common.destination(destination_id)
    common.check_version(segment, expected_version, "ERR_STALE_SEGMENT_VERSION")
    if segment["status"] == "RETIRED":
        raise ApiError("ERR_INVALID_STATE")
    if destination["status"] != "ACTIVE":
        raise ApiError("ERR_DESTINATION_INACTIVE")
    if _sensitive_blocked(segment, destination):
        raise ApiError("ERR_SENSITIVE_ATTRIBUTE_NOT_PERMITTED")
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_WINDOW")
    if activation_service.cooldown_violation(destination, window_start, window_end):
        raise ApiError("ERR_ACTIVATION_COOLDOWN_VIOLATION")
    if activation_service.concurrency_violation(destination, window_start, window_end):
        raise ApiError("ERR_ACTIVATION_CONCURRENCY_EXCEEDED")

    entity = db.new_entity(
        "activations",
        segment_id=segment["id"],
        destination_id=destination["id"],
        window_start_at=window_start,
        window_end_at=window_end,
        status="DRAFT",
        candidate_count=0,
        audience_size=0,
        suppressed_count=0,
        dispatched_hash_count=0,
        unusable_hash_count=0,
        vendor_matched_count=0,
        gross_match_rate=None,
        net_match_rate=None,
        effective_match_rate=None,
        attributed_conversions=[],
        dispatched_at=None,
        paused_reason=None,
        terminated_at=None,
    )
    db.touch(segment)
    return common.one("activations", entity, 201)


@bp.get("/cdp/activations/<activation_id>")
def read_activation(activation_id):
    middleware.require_role(*middleware.READ_ROLES)
    return common.one("activations", common.activation(activation_id))


@bp.get("/cdp/activations")
def list_activations():
    middleware.require_role(*middleware.READ_ROLES)
    return common.collection_list(
        "activations",
        {"segment_id": "segment_id", "destination_id": "destination_id", "status": "status"},
        common.seq_sort,
    )


@bp.post("/cdp/activations/<activation_id>/dispatch")
def dispatch_activation(activation_id):
    middleware.require_role(middleware.ROLE_ANALYST)
    validators.body_object(required=False)
    entity = common.activation(activation_id)
    common.require_status(entity, ("DRAFT",))
    segment = db.store["segments"][entity["segment_id"]]
    destination = db.store["destinations"][entity["destination_id"]]
    if destination["status"] != "ACTIVE":
        raise ApiError("ERR_DESTINATION_INACTIVE")
    _require_governance(segment)
    if _sensitive_blocked(segment, destination):
        raise ApiError("ERR_SENSITIVE_ATTRIBUTE_NOT_PERMITTED")
    _resolve_and_gate(entity, segment, destination)
    activation_service.dispatch(entity, segment, destination)
    return common.one("activations", entity)


@bp.post("/cdp/activations/<activation_id>/resume")
def resume_activation(activation_id):
    middleware.require_role(middleware.ROLE_ANALYST)
    validators.body_object(required=False)
    entity = common.activation(activation_id)
    common.require_status(entity, ("PAUSED",))
    segment = db.store["segments"][entity["segment_id"]]
    destination = db.store["destinations"][entity["destination_id"]]
    if destination["status"] != "ACTIVE":
        raise ApiError("ERR_DESTINATION_INACTIVE")
    _require_governance(segment)
    if _sensitive_blocked(segment, destination):
        raise ApiError("ERR_SENSITIVE_ATTRIBUTE_NOT_PERMITTED")
    _resolve_and_gate(entity, segment, destination)
    activation_service.resume(entity, segment, destination)
    return common.one("activations", entity)


@bp.post("/cdp/activations/<activation_id>/pause")
def pause_activation(activation_id):
    middleware.require_role(middleware.ROLE_ANALYST)
    validators.body_object(required=False)
    entity = common.activation(activation_id)
    common.require_status(entity, derive.DELIVERING_ACTIVATION_STATUSES)
    segment = db.store["segments"][entity["segment_id"]]
    destination = db.store["destinations"][entity["destination_id"]]
    activation_service.pause(entity, segment, destination, "OPERATOR")
    return common.one("activations", entity)


def _parse_conversions(body):
    raw_list = validators.opt_array(body, "attributed_conversions")
    conversions = []
    for index, raw in enumerate(raw_list):
        element = validators.sub_object(raw, "attributed_conversions[%d]" % index)
        conversions.append({
            "profile_id": validators.req_id(element, "profile_id"),
            "converted_at": validators.req_ts(element, "converted_at"),
            "revenue_cents": validators.req_int(element, "revenue_cents", 0),
        })
    return conversions


@bp.post("/cdp/activations/<activation_id>/match-report")
def report_activation(activation_id):
    middleware.require_role(middleware.ROLE_DESTINATION)
    entity = common.activation(activation_id)
    middleware.require_destination_actor(entity["destination_id"])
    body = validators.body_object()
    matched = validators.req_int(body, "vendor_matched_count", 0)
    unusable = validators.req_int(body, "unusable_hash_count", 0)
    conversions = _parse_conversions(body)
    for conversion in conversions:
        common.profile(conversion["profile_id"])
    common.require_status(entity, derive.DELIVERING_ACTIVATION_STATUSES)
    if matched + unusable > entity["dispatched_hash_count"]:
        raise ApiError("ERR_MATCH_REPORT_EXCEEDS_DISPATCH")
    destination = db.store["destinations"][entity["destination_id"]]
    activation_service.report(entity, destination, matched, unusable, conversions)
    return common.one("activations", entity)
