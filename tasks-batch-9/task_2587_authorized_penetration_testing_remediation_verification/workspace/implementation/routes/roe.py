"""Rules of engagement and authorized targets (PRD 3.4)."""
from datetime import timedelta

from flask import Blueprint, g, request

import calc
import core
import serialize
from auth import authorize
from core import new_record, touch
from envelope import object_response
from errors import ApiError
from resolve import filtered, get_asset, get_engagement, get_roe, get_target, paginate
from store import store
from validate import body, get_datetime, get_enum_array, get_str, get_str_array

bp = Blueprint("roe", __name__)

TECHNIQUES = (
    "SQLI",
    "XSS",
    "AUTHZ_BYPASS",
    "PHISHING",
    "LATERAL_MOVEMENT",
    "IAM_ESCALATION",
    "DOS",
)
READ_ROLES = ("ProgramManager", "ComplianceOfficer", "PlatformAdmin", "Tester")
LIVE_ROE_STATUSES = ("DRAFT", "SIGNED", "SUSPENDED")


@bp.post("/rules-of-engagement")
def draft_roe():
    authorize("ProgramManager")
    data = body()
    engagement_id = get_str(data, "engagement_id")
    exclusions = get_str_array(
        data, "exclusions", required=True, min_len=0, max_len=50, allow_duplicates=True
    )
    techniques = get_enum_array(data, "allowed_techniques", TECHNIQUES, required=True, min_len=1)
    procedure = get_str(data, "emergency_stop_procedure", min_len=1, max_len=500)
    contact = get_str(data, "escalation_contact", min_len=1, max_len=120)
    engagement = get_engagement(engagement_id)
    for existing in store.roes.values():
        if existing["engagement_id"] == engagement["id"] and existing["status"] in LIVE_ROE_STATUSES:
            raise ApiError("ERR_ROE_ALREADY_EXISTS")
    record = new_record(
        engagement_id=engagement["id"],
        drafted_by_user_id=g.user_id,
        exclusions=exclusions,
        allowed_techniques=techniques,
        emergency_stop_procedure=procedure,
        escalation_contact=contact,
        status="DRAFT",
        signed_by_user_id=None,
        signed_at=None,
        active_target_count=0,
    )
    store.roes[record["id"]] = record
    return object_response(serialize.roe(record), 201)


@bp.get("/rules-of-engagement/<roe_id>")
def read_roe(roe_id):
    authorize(*READ_ROLES)
    return object_response(serialize.roe(get_roe(roe_id)))


@bp.get("/rules-of-engagement")
def list_roe():
    authorize(*READ_ROLES)
    rows = filtered(
        list(store.roes.values()),
        engagement_id=request.args.get("engagement_id"),
        status=request.args.get("status"),
    )
    return paginate(rows, serialize.roe)


@bp.post("/rules-of-engagement/<roe_id>/sign")
def sign_roe(roe_id):
    """The counter-signature is the act that authorizes testing."""
    authorize("ComplianceOfficer")
    roe = get_roe(roe_id)
    data = body()
    get_str(data, "signature_note", required=False)
    if roe["status"] != "DRAFT":
        raise ApiError("ERR_ROE_ALREADY_SIGNED")
    if roe["active_target_count"] < 1:
        raise ApiError("ERR_NO_AUTHORIZED_TARGETS")
    if g.user_id == roe["drafted_by_user_id"]:
        raise ApiError("ERR_SOD_ROE_SIGNER_CONFLICT")
    now = store.now()
    roe["status"] = "SIGNED"
    roe["signed_by_user_id"] = g.user_id
    roe["signed_at"] = now
    touch(roe)
    engagement = store.engagements.get(roe["engagement_id"])
    if engagement is not None and engagement["authorization_state"] == "ROE_PENDING":
        engagement["authorization_state"] = "AUTHORIZED"
        touch(engagement)
    return object_response(serialize.roe(roe))


@bp.post("/authorized-targets")
def add_target():
    authorize("ProgramManager")
    data = body()
    roe_id = get_str(data, "roe_id")
    asset_id = get_str(data, "asset_id")
    start_raw, window_start = get_datetime(data, "window_start")
    end_raw, window_end = get_datetime(data, "window_end")
    allowlist = get_enum_array(data, "technique_allowlist", TECHNIQUES, required=True, min_len=0)
    if not window_end > window_start:
        raise ApiError("ERR_INVALID_REQUEST", "window_end must fall strictly after window_start.")
    asset = get_asset(asset_id)
    roe = get_roe(roe_id)
    engagement = store.engagements.get(roe["engagement_id"])
    if engagement is not None and engagement["authorization_state"] == "SUSPENDED":
        raise ApiError("ERR_ENGAGEMENT_SUSPENDED")
    if roe["status"] not in ("DRAFT", "SIGNED"):
        raise ApiError("ERR_ROE_NOT_MODIFIABLE")
    if not allowlist or not set(allowlist).issubset(set(roe["allowed_techniques"])):
        raise ApiError("ERR_TECHNIQUE_NOT_ALLOWED")
    if engagement is not None:
        if window_start < engagement["window_start"] or window_end > engagement["window_end"]:
            raise ApiError("ERR_WINDOW_OUTSIDE_ENGAGEMENT")
    cooldown = calc.cooldown_hours(asset)
    buffer = timedelta(hours=cooldown)
    for other in store.targets.values():
        if other["asset_id"] != asset["id"] or other["state"] != "ACTIVE":
            continue
        if window_start <= other["window_end"] + buffer and window_end >= other["window_start"] - buffer:
            raise ApiError("ERR_TARGET_WINDOW_COLLISION")
    record = new_record(
        roe_id=roe["id"],
        asset_id=asset["id"],
        window_start=window_start,
        window_start_raw=start_raw,
        window_end=window_end,
        window_end_raw=end_raw,
        technique_allowlist=allowlist,
        state="ACTIVE",
        exclusion_reason=None,
        cooldown_hours=cooldown,
    )
    store.targets[record["id"]] = record
    roe["active_target_count"] = roe["active_target_count"] + 1
    touch(roe)
    return object_response(serialize.target(record), 201)


@bp.get("/authorized-targets/<target_id>")
def read_target(target_id):
    authorize(*READ_ROLES)
    return object_response(serialize.target(get_target(target_id)))


@bp.get("/authorized-targets")
def list_targets():
    authorize(*READ_ROLES)
    rows = filtered(
        list(store.targets.values()),
        roe_id=request.args.get("roe_id"),
        asset_id=request.args.get("asset_id"),
        state=request.args.get("state"),
    )
    return paginate(rows, serialize.target)


@bp.post("/authorized-targets/<target_id>/exclude")
def exclude_target(target_id):
    authorize("ProgramManager", "ComplianceOfficer")
    target = get_target(target_id)
    data = body()
    reason = get_str(data, "reason", min_len=1)
    roe = store.roes.get(target["roe_id"])
    if roe is None or roe["status"] not in ("DRAFT", "SIGNED"):
        raise ApiError("ERR_ROE_NOT_MODIFIABLE")
    if target["state"] != "ACTIVE":
        raise ApiError("ERR_TARGET_NOT_ACTIVE")
    target["state"] = "EXCLUDED"
    target["exclusion_reason"] = reason
    touch(target)
    roe["active_target_count"] = max(0, roe["active_target_count"] - 1)
    touch(roe)
    return object_response(serialize.target(target))
