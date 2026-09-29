"""Provider onboarding, credentialing, network posture and capacity publication."""

from datetime import date

from flask import Blueprint

from db import clock, db
from errors import ApiError
from middleware import assert_provider_scope, auth, json_body
from response import ok, paginate
from util import (
    check_range,
    opt_bool,
    opt_enum,
    opt_int_field,
    opt_str,
    parse_date_value,
    parse_dt_value,
    present,
    req_enum,
    req_str,
    utc_date,
)

from services.cascade import (
    PROVIDER_TRANSITIONS,
    set_provider_status,
    transition_allowed,
)
from services.core import (
    REINSTATE_MIN_LIFETIME_SCORE,
    REQUIRED_CREDENTIAL_TYPES,
    block_status,
    has_full_credentials,
    new_row,
    provider_quality,
    s_block,
    s_credential,
    s_provider,
    sort_created,
    touch,
)
from routes._common import (
    BLOCK_STATUSES,
    CARE_MODES,
    CREDENTIAL_STATUSES,
    CREDENTIAL_TYPES,
    NETWORK_STATUSES,
    keep,
    need,
    qs_bool,
    qs_date,
    qs_enum,
    qs_str,
)

bp = Blueprint("providers", __name__)


@bp.post("/providers")
def create_provider():
    body = json_body()
    provider_name = req_str(body, "provider_name", 200)
    owner_user_id = req_str(body, "owner_user_id", 80)
    care_mode = req_enum(body, "care_mode", CARE_MODES)
    market_code = req_str(body, "market_code", 16)
    postal_code = req_str(body, "postal_code", 16)
    daily_capacity_slots = check_range(
        opt_int_field(body, "daily_capacity_slots"), 0, 500
    )
    max_concurrent = check_range(
        opt_int_field(body, "max_concurrent_assignments"), 1, 10
    )
    same_day = opt_bool(body, "same_day_available")

    auth("network_admin")

    provider = new_row(
        {
            "provider_name": provider_name,
            "owner_user_id": owner_user_id,
            "care_mode": care_mode,
            "market_code": market_code,
            "postal_code": postal_code,
            "network_status": "PENDING",
            "daily_capacity_slots": 0
            if daily_capacity_slots is None
            else daily_capacity_slots,
            "max_concurrent_assignments": 1 if max_concurrent is None else max_concurrent,
            "same_day_available": False if same_day is None else same_day,
            "last_status_reason_code": None,
        }
    )
    db.providers[provider["id"]] = provider
    return ok(s_provider(provider), 201)


@bp.get("/providers/<row_id>")
def get_provider(row_id):
    auth("network_admin", "benefits_admin", "care_coordinator", "provider_manager")
    provider = need(db.providers, row_id, "ERR_PROVIDER_NOT_FOUND")
    return ok(s_provider(provider))


@bp.get("/providers")
def list_providers():
    auth("network_admin", "benefits_admin", "care_coordinator")
    market_code = qs_str("market_code")
    care_mode = qs_enum("care_mode", CARE_MODES)
    network_status = qs_enum("network_status", NETWORK_STATUSES)
    same_day = qs_bool("same_day_available")
    rows = sort_created(list(db.providers.values()))
    rows = keep(rows, "market_code", market_code)
    rows = keep(rows, "care_mode", care_mode)
    rows = keep(rows, "network_status", network_status)
    rows = keep(rows, "same_day_available", same_day)
    return paginate(rows, s_provider)


@bp.patch("/providers/<row_id>")
def patch_provider(row_id):
    body = json_body()
    provider_name = opt_str(body, "provider_name", 200)
    postal_code = opt_str(body, "postal_code", 16)
    daily_capacity_slots = check_range(
        opt_int_field(body, "daily_capacity_slots"), 0, 500
    )
    max_concurrent = check_range(
        opt_int_field(body, "max_concurrent_assignments"), 1, 10
    )
    same_day = opt_bool(body, "same_day_available")
    care_mode = opt_enum(body, "care_mode", CARE_MODES)
    market_code = opt_str(body, "market_code", 16)

    auth("network_admin")
    provider = need(db.providers, row_id, "ERR_PROVIDER_NOT_FOUND")

    if care_mode is not None and care_mode != provider["care_mode"]:
        raise ApiError("ERR_PROVIDER_FIELD_IMMUTABLE")
    if market_code is not None and market_code != provider["market_code"]:
        raise ApiError("ERR_PROVIDER_FIELD_IMMUTABLE")

    if provider_name is not None:
        provider["provider_name"] = provider_name
    if postal_code is not None:
        provider["postal_code"] = postal_code
    if daily_capacity_slots is not None:
        provider["daily_capacity_slots"] = daily_capacity_slots
    if max_concurrent is not None:
        provider["max_concurrent_assignments"] = max_concurrent
    if same_day is not None:
        provider["same_day_available"] = same_day
    touch(provider)
    return ok(s_provider(provider))


# --------------------------------------------------------------------------- #
# credentials
# --------------------------------------------------------------------------- #

@bp.post("/providers/<row_id>/credentials")
def file_credential(row_id):
    body = json_body()
    credential_type = req_enum(body, "credential_type", CREDENTIAL_TYPES)
    if not present(body, "issued_on") or not present(body, "expires_on"):
        raise ApiError("ERR_INVALID_REQUEST")
    issued_on = parse_date_value(body["issued_on"])
    expires_on = parse_date_value(body["expires_on"])
    if not expires_on > issued_on:
        raise ApiError("ERR_INVALID_REQUEST")
    verified_by = req_str(body, "verified_by", 80)

    user_id, role = auth("network_admin", "provider_manager")
    provider = need(db.providers, row_id, "ERR_PROVIDER_NOT_FOUND")
    assert_provider_scope(user_id, role, provider["id"])

    for row in db.credentials.values():
        if row["provider_id"] != provider["id"]:
            continue
        if row["credential_type"] != credential_type:
            continue
        if row["status"] != "REVOKED":
            raise ApiError("ERR_DUPLICATE_KEY")

    credential = new_row(
        {
            "provider_id": provider["id"],
            "credential_type": credential_type,
            "issued_on": issued_on.isoformat(),
            "expires_on": expires_on.isoformat(),
            "verified_by": verified_by,
            "status": "VALID",
            "revoked_reason_code": None,
        }
    )
    db.credentials[credential["id"]] = credential
    return ok(s_credential(credential), 201)


@bp.get("/providers/<row_id>/credentials")
def provider_credentials(row_id):
    user_id, role = auth("network_admin", "care_coordinator", "provider_manager")
    provider = need(db.providers, row_id, "ERR_PROVIDER_NOT_FOUND")
    assert_provider_scope(user_id, role, provider["id"])
    credential_type = qs_enum("credential_type", CREDENTIAL_TYPES)
    status = qs_enum("status", CREDENTIAL_STATUSES)
    rows = [c for c in db.credentials.values() if c["provider_id"] == provider["id"]]
    rows = keep(rows, "credential_type", credential_type)
    rows = keep(rows, "status", status)
    return paginate(sort_created(rows), s_credential)


@bp.get("/credentials/<row_id>")
def get_credential(row_id):
    user_id, role = auth("network_admin", "care_coordinator", "provider_manager")
    credential = need(db.credentials, row_id, "ERR_CREDENTIAL_NOT_FOUND")
    assert_provider_scope(user_id, role, credential["provider_id"])
    return ok(s_credential(credential))


@bp.post("/credentials/<row_id>/revoke")
def revoke_credential(row_id):
    body = json_body()
    reason_code = req_str(body, "revoked_reason_code", 80)

    auth("network_admin")
    credential = need(db.credentials, row_id, "ERR_CREDENTIAL_NOT_FOUND")
    if credential["status"] != "VALID":
        raise ApiError("ERR_CREDENTIAL_TERMINAL")

    credential["status"] = "REVOKED"
    credential["revoked_reason_code"] = reason_code
    touch(credential)

    provider = db.providers.get(credential["provider_id"])
    if (
        provider is not None
        and credential["credential_type"] in REQUIRED_CREDENTIAL_TYPES
        and provider["network_status"] in ("CREDENTIALED", "PROBATION")
    ):
        set_provider_status(provider, "SUSPENDED", "CREDENTIAL_REVOKED")

    return ok(s_credential(credential))


# --------------------------------------------------------------------------- #
# network posture
# --------------------------------------------------------------------------- #

@bp.post("/providers/<row_id>/credential-review")
def credential_review(row_id):
    body = json_body()
    reason_code = opt_str(body, "reason_code", 80)

    auth("network_admin")
    provider = need(db.providers, row_id, "ERR_PROVIDER_NOT_FOUND")

    if provider["network_status"] == "DEPROVISIONED":
        raise ApiError("ERR_PROVIDER_TERMINAL")
    if provider["network_status"] != "PENDING":
        raise ApiError("ERR_PROVIDER_STATE_INVALID")
    if not has_full_credentials(provider["id"], utc_date(clock())):
        raise ApiError("ERR_PROVIDER_NOT_CREDENTIALED")

    provider["network_status"] = "CREDENTIALED"
    provider["last_status_reason_code"] = reason_code or "CREDENTIAL_REVIEW_PASSED"
    touch(provider)
    return ok(s_provider(provider))


@bp.post("/providers/<row_id>/network-status")
def network_status(row_id):
    body = json_body()
    target_status = req_enum(body, "target_status", NETWORK_STATUSES)
    reason_code = req_str(body, "reason_code", 80)

    auth("network_admin")
    provider = need(db.providers, row_id, "ERR_PROVIDER_NOT_FOUND")

    if provider["network_status"] == "DEPROVISIONED":
        raise ApiError("ERR_PROVIDER_TERMINAL")
    if not transition_allowed(provider["network_status"], target_status):
        raise ApiError("ERR_PROVIDER_STATE_INVALID")

    if target_status == "CREDENTIALED":
        if not has_full_credentials(provider["id"], utc_date(clock())):
            raise ApiError("ERR_PROVIDER_NOT_CREDENTIALED")
        if provider_quality(provider, "LIFETIME_UNDECAYED") < REINSTATE_MIN_LIFETIME_SCORE:
            raise ApiError("ERR_REINSTATE_SCORE_TOO_LOW")

    set_provider_status(provider, target_status, reason_code)
    return ok(s_provider(provider))


# --------------------------------------------------------------------------- #
# capacity blocks
# --------------------------------------------------------------------------- #

@bp.post("/providers/<row_id>/capacity-blocks")
def create_block(row_id):
    body = json_body()
    if not present(body, "start_time_utc") or not present(body, "end_time_utc"):
        raise ApiError("ERR_INVALID_REQUEST")
    start_time = parse_dt_value(body["start_time_utc"])
    end_time = parse_dt_value(body["end_time_utc"])
    total_slots = check_range(opt_int_field(body, "total_slots"), 0, 500)
    if not end_time > start_time:
        raise ApiError("ERR_INVALID_WINDOW")

    user_id, role = auth("network_admin", "provider_manager")
    provider = need(db.providers, row_id, "ERR_PROVIDER_NOT_FOUND")
    assert_provider_scope(user_id, role, provider["id"])

    if provider["network_status"] == "DEPROVISIONED":
        raise ApiError("ERR_PROVIDER_TERMINAL")

    service_date = utc_date(start_time)
    if utc_date(end_time) != service_date:
        raise ApiError("ERR_BLOCK_DATE_MISMATCH")

    for other in db.capacity_blocks.values():
        if other["provider_id"] != provider["id"]:
            continue
        if other["service_date"] != service_date.isoformat():
            continue
        if block_status(other) == "CLOSED":
            continue
        if start_time < other["end_time_utc"] and other["start_time_utc"] < end_time:
            raise ApiError("ERR_BLOCK_OVERLAP")

    block = new_row(
        {
            "provider_id": provider["id"],
            "service_date": service_date.isoformat(),
            "start_time_utc": start_time,
            "end_time_utc": end_time,
            "total_slots": provider["daily_capacity_slots"]
            if total_slots is None
            else total_slots,
            "closed": False,
        }
    )
    db.capacity_blocks[block["id"]] = block
    return ok(s_block(block), 201)


@bp.get("/providers/<row_id>/capacity-blocks")
def provider_blocks(row_id):
    user_id, role = auth("network_admin", "care_coordinator", "provider_manager")
    provider = need(db.providers, row_id, "ERR_PROVIDER_NOT_FOUND")
    assert_provider_scope(user_id, role, provider["id"])
    service_date = qs_date("service_date")
    status = qs_enum("block_status", BLOCK_STATUSES)
    rows = [
        b for b in db.capacity_blocks.values() if b["provider_id"] == provider["id"]
    ]
    rows = keep(rows, "service_date", service_date)
    if status is not None:
        rows = [b for b in rows if block_status(b) == status]
    return paginate(sort_created(rows), s_block)


@bp.get("/capacity-blocks/<row_id>")
def get_block(row_id):
    auth("network_admin", "care_coordinator", "provider_manager", "benefits_admin")
    block = need(db.capacity_blocks, row_id, "ERR_CAPACITYBLOCK_NOT_FOUND")
    return ok(s_block(block))
