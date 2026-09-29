"""The profile graph: profiles, households, match rules and identity links."""

import re

from flask import Blueprint

import db
import middleware
import response
import validators
from errors import ApiError
from routes import common
from services import calc, cascade, derive, ingest

bp = Blueprint("graph", __name__)

RULE_CODE_RE = re.compile(r"^[A-Z0-9_]+$")
RULE_KINDS = ("DETERMINISTIC", "PROBABILISTIC")
DETERMINISTIC_KEYS = ("EMAIL_NORM", "PHONE_NORM", "LOYALTY_NUMBER")
POLICIES = ("STRICT_ZERO", "RENORMALIZE")
EVIDENCE_KEYS = ("email_similarity", "phone_similarity", "name_similarity", "address_similarity")
SIMILARITY_VALUES = ("0.0", "0.5", "1.0")
DECISIONS = ("CONFIRM", "REJECT")
JOINED_LINK_STATUSES = ("PROPOSED", "CONFIRMED")


# ---------------------------------------------------------------- profiles

@bp.get("/cdp/profiles/<profile_id>")
def read_profile(profile_id):
    middleware.require_role(*middleware.READ_ROLES)
    return common.one("profiles", common.profile(profile_id))


@bp.get("/cdp/profiles")
def list_profiles():
    middleware.require_role(*middleware.READ_ROLES)
    return common.collection_list(
        "profiles",
        {
            "origin_batch_id": "origin_batch_id",
            "primary_source_system_id": "primary_source_system_id",
            "household_id": "household_id",
            "merged_into_profile_id": "merged_into_profile_id",
            "resolution_status": "resolution_status",
            "privacy_status": "privacy_status",
        },
        common.seq_sort,
    )


@bp.get("/cdp/profiles/<profile_id>/consent-state")
def read_consent_state(profile_id):
    middleware.require_role(*middleware.READ_ROLES)
    entity = common.profile(profile_id)
    moment = db.now()
    decisions = derive.resolve_channels(entity, moment)
    channels = sorted(d["channel"] for d in decisions if d["consent_state"] == "OPT_IN")
    payload = {
        "profile_id": entity["id"],
        "evaluated_at": db.iso(moment),
        "activatable_channels": channels,
        "channel_engagement_score": float(derive.engagement_score(entity, moment)),
        "channels": [],
    }
    ranks = {}
    for decision in decisions:
        record_id = decision["consent_record_id"]
        rank = None
        if record_id is not None:
            record = db.store["consent_records"].get(record_id)
            if record is not None:
                rank = record["precedence_rank"]
        ranks[decision["channel"]] = rank
        payload["channels"].append({
            "channel": decision["channel"],
            "consent_state": decision["consent_state"],
            "resolution": decision["consent_state"],
            "reason": decision["reason"],
            "consent_record_id": record_id,
            "precedence_rank": rank,
            "activatable": decision["consent_state"] == "OPT_IN",
        })
    return response.object_response(payload)


@bp.post("/cdp/profiles/<profile_id>/household-assignment")
def assign_household(profile_id):
    middleware.require_role(middleware.ROLE_STEWARD)
    body = validators.body_object()
    household_id = validators.req_id(body, "household_id")
    entity = common.profile(profile_id)
    target = common.household(household_id)
    if entity["privacy_status"] == "DELETED":
        raise ApiError("ERR_PROFILE_DELETED")
    if target["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_HOUSEHOLD_STATE")
    if entity.get("address_hash") is None or target["address_hash"] != entity["address_hash"]:
        raise ApiError("ERR_INVALID_HOUSEHOLD_STATE")
    if derive.household_member_count(target["id"]) >= calc.HOUSEHOLD_MAX_MEMBERS:
        raise ApiError("ERR_HOUSEHOLD_CAPACITY_EXCEEDED")
    previous_id = entity["household_id"]
    if previous_id == target["id"]:
        db.touch(entity)
        db.touch(target)
        return common.one("profiles", entity)
    entity["household_id"] = target["id"]
    db.touch(entity)
    if previous_id is not None:
        previous = db.store["households"].get(previous_id)
        if previous is not None:
            derive.refresh_household(previous)
            db.touch(previous)
    db.touch(target)
    return common.one("profiles", entity)


# -------------------------------------------------------------- households

@bp.get("/cdp/households/<household_id>")
def read_household(household_id):
    middleware.require_role(*middleware.READ_ROLES)
    return common.one("households", common.household(household_id))


@bp.get("/cdp/households")
def list_households():
    middleware.require_role(*middleware.READ_ROLES)
    return common.collection_list(
        "households",
        {"address_hash": "address_hash", "status": "status"},
        lambda h: (h["created_at"], h["_seq"]),
    )


# ------------------------------------------------------------- match rules

@bp.post("/cdp/match-rules")
def create_rule():
    middleware.require_role(middleware.ROLE_ADMIN)
    body = validators.body_object()
    code = validators.req_str(body, "code", 3, 24, RULE_CODE_RE)
    rule_kind = validators.req_enum(body, "rule_kind", RULE_KINDS)
    deterministic_key = validators.opt_enum(body, "deterministic_key", DETERMINISTIC_KEYS)
    policy = validators.opt_enum(body, "missing_identifier_policy", POLICIES, "STRICT_ZERO")
    auto_merge = validators.opt_decimal(body, "auto_merge_threshold", 0, 1, 4, 0.92)
    review_floor = validators.opt_decimal(body, "review_floor", 0, 1, 4, 0.65)
    min_precision = validators.opt_decimal(body, "min_precision", 0, 1, 4, 0.60)
    if any(r["code"] == code for r in db.all_of("match_rules")):
        raise ApiError("ERR_DUPLICATE_CODE")
    if calc.dec(auto_merge) <= calc.dec(review_floor):
        raise ApiError("ERR_INVALID_THRESHOLD_ORDER")
    if rule_kind == "DETERMINISTIC" and deterministic_key is None:
        raise ApiError("ERR_DETERMINISTIC_KEY_MISMATCH")
    if rule_kind == "PROBABILISTIC" and deterministic_key is not None:
        raise ApiError("ERR_DETERMINISTIC_KEY_MISMATCH")
    entity = db.new_entity(
        "match_rules",
        code=code,
        rule_kind=rule_kind,
        deterministic_key=deterministic_key,
        missing_identifier_policy=policy,
        auto_merge_threshold=auto_merge,
        review_floor=review_floor,
        min_precision=min_precision,
        status="ENABLED",
        confirmed_count=0,
        rejected_count=0,
    )
    return common.one("match_rules", entity, 201)


@bp.get("/cdp/match-rules/<rule_id>")
def read_rule(rule_id):
    middleware.require_role(*middleware.READ_ROLES)
    return common.one("match_rules", common.rule(rule_id))


@bp.get("/cdp/match-rules")
def list_rules():
    middleware.require_role(*middleware.READ_ROLES)
    return common.collection_list(
        "match_rules",
        {"rule_kind": "rule_kind", "status": "status"},
        common.seq_sort,
    )


# ---------------------------------------------------------- identity links

def _parse_evidence(body):
    if "evidence" not in body or body["evidence"] is None:
        raise validators.invalid("evidence is required.")
    raw = body["evidence"]
    if not isinstance(raw, dict):
        raise validators.invalid("evidence must be an object.")
    evidence = {}
    for key in EVIDENCE_KEYS:
        if key not in raw:
            raise validators.invalid("evidence.%s is required." % key)
        value = raw[key]
        if value is None:
            evidence[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise validators.invalid("evidence.%s must be a number or null." % key)
        text = str(calc.dec(value).normalize())
        if text not in ("0", "0.0", "0.5", "1", "1.0"):
            raise validators.invalid("evidence.%s must be 0.0, 0.5, 1.0 or null." % key)
        evidence[key] = float(value)
    return evidence


def _already_joined(left_id, right_id):
    pair = {left_id, right_id}
    for link in db.all_of("identity_links"):
        if link["status"] not in JOINED_LINK_STATUSES:
            continue
        if {link["left_profile_id"], link["right_profile_id"]} == pair:
            return True
    return False


def _mergeable(profile):
    return profile["resolution_status"] == "RESOLVED" \
        and profile["privacy_status"] not in ("LEGAL_HOLD", "DELETION_PENDING", "DELETED")


@bp.post("/cdp/identity-links")
def create_link():
    middleware.require_role(middleware.ROLE_STEWARD)
    body = validators.body_object()
    left_id = validators.req_id(body, "left_profile_id")
    right_id = validators.req_id(body, "right_profile_id")
    rule_id = validators.req_id(body, "match_rule_id")
    evidence = _parse_evidence(body)
    left = common.profile(left_id)
    right = common.profile(right_id)
    rule = common.rule(rule_id)
    for profile in (left, right):
        if profile["resolution_status"] == "MERGED_AWAY":
            raise ApiError("ERR_PROFILE_MERGED_AWAY")
    if rule["status"] != "ENABLED":
        raise ApiError("ERR_MATCH_RULE_DISABLED")
    for profile in (left, right):
        if profile["privacy_status"] == "DELETED":
            raise ApiError("ERR_PROFILE_DELETED")
    if left["id"] == right["id"]:
        raise ApiError("ERR_SELF_LINK_FORBIDDEN")
    if _already_joined(left["id"], right["id"]):
        raise ApiError("ERR_DUPLICATE_IDENTITY_LINK")
    confidence = calc.match_confidence(evidence, rule["missing_identifier_policy"])
    if confidence < calc.dec(rule["review_floor"]):
        raise ApiError("ERR_CONFIDENCE_BELOW_FLOOR")
    entity = db.new_entity(
        "identity_links",
        left_profile_id=left["id"],
        right_profile_id=right["id"],
        match_rule_id=rule["id"],
        survivor_profile_id=None,
        evidence=evidence,
        match_method=rule["rule_kind"],
        confidence=confidence,
        status="PROPOSED",
        decided_by_user_id=None,
        decided_at=None,
        void_reason=None,
    )
    if confidence >= calc.dec(rule["auto_merge_threshold"]) \
            and _mergeable(left) and _mergeable(right):
        ingest.confirm_link(entity, rule, "system", bump_link=False)
    return common.one("identity_links", entity, 201)


@bp.get("/cdp/identity-links/<link_id>")
def read_link(link_id):
    middleware.require_role(*middleware.READ_ROLES)
    return common.one("identity_links", common.link(link_id))


@bp.get("/cdp/identity-links")
def list_links():
    middleware.require_role(*middleware.READ_ROLES)
    return common.collection_list(
        "identity_links",
        {
            "left_profile_id": "left_profile_id",
            "right_profile_id": "right_profile_id",
            "match_rule_id": "match_rule_id",
            "survivor_profile_id": "survivor_profile_id",
            "status": "status",
        },
        common.seq_sort,
    )


@bp.post("/cdp/identity-links/<link_id>/decision")
def decide_link(link_id):
    middleware.require_role(middleware.ROLE_STEWARD)
    body = validators.body_object()
    decision = validators.req_enum(body, "decision", DECISIONS)
    entity = common.link(link_id)
    common.require_status(entity, ("PROPOSED",))
    rule = db.store["match_rules"][entity["match_rule_id"]]
    actor = middleware.actor_id()
    if decision == "REJECT":
        ingest.reject_link(entity, rule, actor)
        return common.one("identity_links", entity)
    left = db.store["profiles"][entity["left_profile_id"]]
    right = db.store["profiles"][entity["right_profile_id"]]
    for profile in (left, right):
        if profile["resolution_status"] == "MERGED_AWAY":
            raise ApiError("ERR_PROFILE_MERGED_AWAY")
    for profile in (left, right):
        if profile["privacy_status"] == "DELETED":
            raise ApiError("ERR_PROFILE_DELETED")
    for profile in (left, right):
        if profile["privacy_status"] == "LEGAL_HOLD":
            raise ApiError("ERR_LEGAL_HOLD_ACTIVE")
    for profile in (left, right):
        if profile["resolution_status"] != "RESOLVED" \
                or profile["privacy_status"] == "DELETION_PENDING":
            raise ApiError("ERR_INVALID_STATE")
    ingest.confirm_link(entity, rule, actor)
    return common.one("identity_links", entity)
