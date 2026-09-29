"""Consent elections and suppression windows."""

from flask import Blueprint

import db
import middleware
import validators
from errors import ApiError
from routes import common
from services import calc, cascade, derive, privacy

bp = Blueprint("consent", __name__)

PURPOSES = ("MARKETING", "PERSONALIZATION", "MEASUREMENT")
CONSENT_STATES = ("OPT_IN", "OPT_OUT")
ENTRY_TYPES = ("PRIVACY_DELETE", "DO_NOT_SELL", "GLOBAL_OPT_OUT", "LEGAL_HOLD")


# --------------------------------------------------------- consent records

@bp.post("/cdp/consent-records")
def create_consent():
    middleware.require_role(middleware.ROLE_PRIVACY)
    body = validators.body_object()
    profile_id = validators.req_id(body, "profile_id")
    source_id = validators.req_id(body, "source_system_id")
    channel = validators.req_enum(body, "channel", calc.CHANNELS)
    purpose = validators.req_enum(body, "purpose", PURPOSES)
    consent_state = validators.req_enum(body, "consent_state", CONSENT_STATES)
    captured_at = validators.req_ts(body, "captured_at")
    expires_at = validators.opt_ts(body, "expires_at")
    expected_version = validators.req_int(body, "expected_profile_version", 1)

    source = common.source(source_id)
    profile = common.profile(profile_id)
    common.check_version(profile, expected_version, "ERR_STALE_PROFILE_VERSION")
    if profile["resolution_status"] == "MERGED_AWAY":
        raise ApiError("ERR_PROFILE_MERGED_AWAY")
    if source["status"] == "QUARANTINED":
        raise ApiError("ERR_SOURCE_SYSTEM_QUARANTINED")
    if profile["privacy_status"] == "DELETED":
        raise ApiError("ERR_PROFILE_DELETED")
    if expires_at is not None and expires_at <= captured_at:
        raise ApiError("ERR_INVALID_WINDOW")
    if captured_at > db.now():
        raise ApiError("ERR_FUTURE_CAPTURED_AT")

    entity = db.new_entity(
        "consent_records",
        profile_id=profile["id"],
        source_system_id=source["id"],
        channel=channel,
        purpose=purpose,
        consent_state=consent_state,
        captured_at=captured_at,
        expires_at=expires_at,
        status="ACTIVE",
        precedence_rank=1,
    )
    derive.rerank_consent_group(profile["id"], channel, purpose, (entity["id"],))
    db.touch(profile)
    cascade.audience_cascade()
    return common.one("consent_records", entity, 201)


@bp.get("/cdp/consent-records/<consent_id>")
def read_consent(consent_id):
    middleware.require_role(*middleware.READ_ROLES)
    return common.one("consent_records", common.consent(consent_id))


def _consent_sort(entity):
    return (entity["precedence_rank"], entity["created_at"], entity["_seq"])


@bp.get("/cdp/consent-records")
def list_consents():
    middleware.require_role(*middleware.READ_ROLES)
    return common.collection_list(
        "consent_records",
        {
            "profile_id": "profile_id",
            "source_system_id": "source_system_id",
            "channel": "channel",
            "purpose": "purpose",
            "status": "status",
        },
        _consent_sort,
    )


# ------------------------------------------------------ suppression entries

@bp.post("/cdp/suppression-entries")
def create_suppression():
    middleware.require_role(middleware.ROLE_PRIVACY)
    body = validators.body_object()
    profile_id = validators.req_id(body, "profile_id")
    entry_type = validators.req_enum(body, "entry_type", ENTRY_TYPES)
    reason_code = validators.req_str(body, "reason_code", 1, 40)
    effective_at = validators.req_ts(body, "effective_at")
    expires_at = validators.opt_ts(body, "expires_at")

    profile = common.profile(profile_id)
    if profile["resolution_status"] == "MERGED_AWAY":
        raise ApiError("ERR_PROFILE_MERGED_AWAY")
    if profile["privacy_status"] == "DELETED":
        raise ApiError("ERR_PROFILE_DELETED")
    if expires_at is not None and expires_at <= effective_at:
        raise ApiError("ERR_INVALID_WINDOW")
    if privacy.has_window_conflict(profile["id"], entry_type, effective_at, expires_at):
        raise ApiError("ERR_SUPPRESSION_WINDOW_OVERLAP")

    entity = privacy.create_suppression(
        profile, entry_type, reason_code, effective_at, expires_at, middleware.actor_id()
    )
    return common.one("suppression_entries", entity, 201)


@bp.get("/cdp/suppression-entries/<suppression_id>")
def read_suppression(suppression_id):
    middleware.require_role(*middleware.READ_ROLES)
    return common.one("suppression_entries", common.suppression(suppression_id))


@bp.get("/cdp/suppression-entries")
def list_suppressions():
    middleware.require_role(*middleware.READ_ROLES)
    return common.collection_list(
        "suppression_entries",
        {
            "profile_id": "profile_id",
            "deletion_request_id": "deletion_request_id",
            "entry_type": "entry_type",
            "status": "status",
        },
        common.seq_sort,
    )


@bp.post("/cdp/suppression-entries/<suppression_id>/release")
def release_suppression(suppression_id):
    middleware.require_role(middleware.ROLE_PRIVACY)
    validators.body_object(required=False)
    entity = common.suppression(suppression_id)
    common.require_status(entity, ("ACTIVE",))
    if entity["entry_type"] == "PRIVACY_DELETE" and entity["deletion_request_id"] is not None:
        raise ApiError("ERR_INVALID_STATE")
    actor = middleware.actor_id()
    if entity["entry_type"] == "LEGAL_HOLD" and entity["created_by_user_id"] == actor:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    profile = db.store["profiles"][entity["profile_id"]]
    privacy.release_suppression(entity, profile, actor)
    return common.one("suppression_entries", entity)
