"""Caller registration and consent lifecycle."""

from datetime import timedelta

from flask import Blueprint, request

from db import store, now
from errors import (
    raise_err, invalid_request, not_found, forbidden, invalid_state,
    ERR_STALE_VERSION, ERR_ANONYMOUS_FOLLOW_UP_FORBIDDEN, ERR_CALLER_PII_PURGED,
)
from middleware import require_roles
from response import ok_object, ok_list
from serializers import caller_out, consent_out
from services import make_record, bump, revoke_consent_cascades, TTL_DAYS
from util import (
    get_payload, check_unknown, require, as_str, as_bool, as_str_array,
    as_enum, as_int, page_of, query_enum,
)

bp = Blueprint("callers", __name__)

CHANNELS = ("PHONE", "CHAT", "TTY", "VIDEO")
CONSENT_TYPES = ("RECORDING", "FOLLOW_UP", "LEGAL_AID_RELEASE", "DATA_SHARING")
CONSENT_STATUSES = ("GRANTED", "REVOKED", "EXPIRED")


# ---------------------------------------------------------------------------
# Callers
# ---------------------------------------------------------------------------

@bp.route("/hotline/callers", methods=["POST"])
def create_caller():
    require_roles("Anonymous")
    data = get_payload()
    check_unknown(data, {"alias", "phone", "preferred_language", "channel", "accessibility_needs", "is_anonymous"})
    alias = as_str(require(data, "alias"), "alias")
    phone = data.get("phone")
    if phone is not None:
        as_str(phone, "phone")
    preferred_language = as_str(require(data, "preferred_language"), "preferred_language")
    channel = as_enum(require(data, "channel"), "channel", CHANNELS)
    accessibility_needs = data.get("accessibility_needs", [])
    as_str_array(accessibility_needs, "accessibility_needs")
    is_anonymous = as_bool(require(data, "is_anonymous"), "is_anonymous")
    if is_anonymous and phone is not None:
        invalid_request("anonymous callers must have a null phone")
    rec = make_record({
        "alias": alias,
        "phone": phone,
        "preferred_language": preferred_language,
        "channel": channel,
        "accessibility_needs": accessibility_needs,
        "is_anonymous": is_anonymous,
        "pii_purged": False,
        "do_not_aggregate": False,
    })
    store.callers[rec["id"]] = rec
    return ok_object(caller_out(rec), status=201)


@bp.route("/hotline/callers/<cid>", methods=["GET"])
def get_caller(cid):
    role, uid = require_roles("Caller", "Counselor", "HotlineSupervisor", "DataProtectionOfficer")
    if role == "Caller" and uid != cid:
        forbidden("a Caller may act only on their own record")
    rec = store.callers.get(cid)
    if rec is None:
        not_found("caller not found")
    return ok_object(caller_out(rec))


# ---------------------------------------------------------------------------
# Consents
# ---------------------------------------------------------------------------

@bp.route("/hotline/callers/<cid>/consents", methods=["POST"])
def grant_consent(cid):
    role, uid = require_roles("Caller")
    if uid != cid:
        forbidden("a Caller may grant consent only on their own record")
    caller = store.callers.get(cid)
    if caller is None:
        not_found("caller not found")
    data = get_payload()
    check_unknown(data, {"consent_type", "expected_caller_version"})
    consent_type = as_enum(require(data, "consent_type"), "consent_type", CONSENT_TYPES)
    expected = as_int(require(data, "expected_caller_version"), "expected_caller_version")
    if expected != caller["version"]:
        raise_err(ERR_STALE_VERSION, "expected_caller_version does not match the caller's current version")
    if consent_type == "FOLLOW_UP" and caller["is_anonymous"]:
        raise_err(ERR_ANONYMOUS_FOLLOW_UP_FORBIDDEN,
                  "anonymous callers cannot grant FOLLOW_UP consent")
    if caller["pii_purged"]:
        raise_err(ERR_CALLER_PII_PURGED, "caller PII has been purged")
    t = now()
    rec = make_record({
        "caller_id": cid,
        "consent_type": consent_type,
        "status": "GRANTED",
        "granted_at": t,
        "expires_at": t + timedelta(days=TTL_DAYS[consent_type]),
        "revoked_at": None,
    })
    store.consents[rec["id"]] = rec
    bump(caller)
    return ok_object(consent_out(rec), status=201)


@bp.route("/hotline/callers/<cid>/consents", methods=["GET"])
def list_consents(cid):
    role, uid = require_roles("Caller", "Counselor", "HotlineSupervisor", "DataProtectionOfficer")
    if role == "Caller" and uid != cid:
        forbidden("a Caller may act only on their own record")
    caller = store.callers.get(cid)
    if caller is None:
        not_found("caller not found")
    consent_type = query_enum("consent_type", CONSENT_TYPES)
    status = query_enum("status", CONSENT_STATUSES)
    recs = [c for c in store.consents.values() if c["caller_id"] == cid]
    if consent_type is not None:
        recs = [c for c in recs if c["consent_type"] == consent_type]
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    page, total, limit, offset = page_of(recs)
    return ok_list([consent_out(c) for c in page], total, limit, offset)


@bp.route("/hotline/consents/<cid>/revoke", methods=["POST"])
def revoke_consent(cid):
    role, uid = require_roles("Caller", "DataProtectionOfficer")
    consent = store.consents.get(cid)
    if consent is None:
        not_found("consent not found")
    if role == "Caller" and uid != consent["caller_id"]:
        forbidden("a Caller may revoke only their own consent")
    if consent["status"] != "GRANTED":
        invalid_state("only a GRANTED consent can be revoked")
    consent["status"] = "REVOKED"
    consent["revoked_at"] = now()
    bump(consent)
    caller = store.callers.get(consent["caller_id"])
    if caller is not None:
        bump(caller)  # revoke explicitly advances the caller's version
    revoke_consent_cascades(consent)
    return ok_object(consent_out(consent))
