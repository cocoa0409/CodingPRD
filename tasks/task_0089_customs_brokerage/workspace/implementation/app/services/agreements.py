"""CommissionAgreement service."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from ..audit import emit_audit
from ..auth import current_actor
from ..clock import now_dt, now_iso_ms, parse_iso
from ..constants import (
    CURRENCIES,
    DECLARATION_NON_TERMINAL,
    SCOPE_CODES,
    TERMINATED_REASONS,
)
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store
from .validation import (
    ensure_currency,
    ensure_enum,
    ensure_int_in_range,
    ensure_string,
    occ_check,
)


def _validate_fee_schedule(scope: list[str], fee_schedule: dict[str, Any]) -> None:
    if not isinstance(fee_schedule, dict):
        raise ApiError("ERR_INVALID_INPUT", "fee_schedule must be an object.")
    scope_set = set(scope)
    fee_keys = set(fee_schedule.keys())
    if scope_set != fee_keys:
        raise ApiError(
            "ERR_FEE_SCHEDULE_INVALID",
            "fee_schedule keys must exactly match scope_of_service.",
        )
    for k, v in fee_schedule.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ApiError("ERR_FEE_SCHEDULE_INVALID", f"fee_schedule[{k}] must be numeric.")
        if v < 0:
            raise ApiError("ERR_FEE_SCHEDULE_INVALID", f"fee_schedule[{k}] must be >= 0.")


def _validate_scope(scope: Any) -> list[str]:
    if not isinstance(scope, list) or not scope:
        raise ApiError("ERR_INVALID_INPUT", "scope_of_service must be a non-empty array.")
    out = []
    seen = set()
    for s in scope:
        if not isinstance(s, str) or s not in SCOPE_CODES:
            raise ApiError(
                "ERR_INVALID_INPUT",
                f"scope_of_service entry {s!r} invalid; must be one of {sorted(SCOPE_CODES)}.",
            )
        if s in seen:
            raise ApiError("ERR_INVALID_INPUT", f"duplicate scope entry {s!r}.")
        seen.add(s)
        out.append(s)
    return out


def create_agreement(body: dict[str, Any]) -> dict[str, Any]:
    client_id = ensure_string(body.get("client_id"), "client_id", 1, 200)
    store = get_store()
    client = store.clients.get(client_id)
    if not client:
        raise ApiError("ERR_NOT_FOUND", f"Client {client_id!r} not found.")

    scope = _validate_scope(body.get("scope_of_service"))
    fee_schedule = body.get("fee_schedule")
    if fee_schedule is None:
        raise ApiError("ERR_INVALID_INPUT", "fee_schedule is required.")
    _validate_fee_schedule(scope, fee_schedule)

    agreement_currency = ensure_currency(body.get("agreement_currency"), "agreement_currency")
    valid_from_raw = body.get("valid_from")
    valid_until_raw = body.get("valid_until")
    if not valid_from_raw or not valid_until_raw:
        raise ApiError("ERR_INVALID_INPUT", "valid_from and valid_until are required.")
    try:
        vf = parse_iso(valid_from_raw)
        vu = parse_iso(valid_until_raw)
    except ValueError as exc:
        raise ApiError("ERR_INVALID_INPUT", f"Invalid date: {exc}")
    if not (vf < vu):
        raise ApiError("ERR_INVALID_INPUT", "valid_until must be strictly greater than valid_from.")

    bps = ensure_int_in_range(
        body.get("late_interest_daily_rate_bps"), "late_interest_daily_rate_bps", 0, 1000
    )

    renewed_from = body.get("renewed_from_agreement_id")
    if renewed_from is not None:
        if not isinstance(renewed_from, str):
            raise ApiError("ERR_INVALID_INPUT", "renewed_from_agreement_id must be string or null.")
        if renewed_from not in store.agreements:
            raise ApiError("ERR_NOT_FOUND", f"Renewed parent {renewed_from!r} not found.")

    record = common_fields_create()
    record.update(
        {
            "client_id": client_id,
            "scope_of_service": scope,
            "fee_schedule": {k: float(v) for k, v in fee_schedule.items()},
            "agreement_currency": agreement_currency,
            "valid_from": valid_from_raw,
            "valid_until": valid_until_raw,
            "late_interest_daily_rate_bps": bps,
            "status": "DRAFT",
            "signed_at": None,
            "signature_token": None,
            "pinned_fee_schedule_version": None,
            "renewed_from_agreement_id": renewed_from,
            "terminated_reason": None,
        }
    )
    store.agreements[record["id"]] = record
    return record


def get_agreement(agreement_id: str) -> dict[str, Any]:
    a = get_store().agreements.get(agreement_id)
    if not a:
        raise ApiError("ERR_NOT_FOUND", f"Agreement {agreement_id!r} not found.")
    return a


def request_signature(agreement_id: str, body: dict[str, Any]) -> dict[str, Any]:
    agreement = get_agreement(agreement_id)
    occ_check(agreement, body.get("version"))

    if agreement.get("status") != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Agreement in status {agreement.get('status')!r}; expected DRAFT.",
        )

    store = get_store()
    client = store.clients.get(agreement.get("client_id"))
    if not client or client.get("status") != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "ClientCompany must be ACTIVE.")

    _validate_fee_schedule(agreement["scope_of_service"], agreement["fee_schedule"])

    # valid_from < valid_until (already enforced at create but re-check defensively)
    vf = parse_iso(agreement["valid_from"])
    vu = parse_iso(agreement["valid_until"])
    if not (vf < vu):
        raise ApiError("ERR_INVALID_INPUT", "valid_until must be strictly greater than valid_from.")

    prev_status = agreement["status"]
    agreement["status"] = "AWAITING_SIGNATURE"
    agreement["signature_token"] = str(uuid.uuid4())
    bump_version(agreement)

    user_id, role = current_actor()
    emit_audit(
        "AGREEMENT",
        agreement["id"],
        "STATE_TRANSITION",
        role,
        user_id,
        {"from": prev_status, "to": "AWAITING_SIGNATURE"},
    )
    return agreement


def sign_agreement(agreement_id: str, body: dict[str, Any]) -> dict[str, Any]:
    agreement = get_agreement(agreement_id)
    occ_check(agreement, body.get("version"))

    if agreement.get("status") != "AWAITING_SIGNATURE":
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Agreement in status {agreement.get('status')!r}; expected AWAITING_SIGNATURE.",
        )

    token = body.get("signature_token")
    if not token or not isinstance(token, str):
        raise ApiError("ERR_INVALID_INPUT", "signature_token is required.")
    if token != agreement.get("signature_token"):
        raise ApiError("ERR_INVALID_STATE", "signature_token mismatch.")

    # ClientUser ownership: X-User-ID must equal client_id
    user_id, role = current_actor()
    if role == "ClientUser" and user_id != agreement.get("client_id"):
        raise ApiError("ERR_FORBIDDEN", "ClientUser may only sign their own agreements.")

    if now_dt() >= parse_iso(agreement["valid_until"]):
        raise ApiError("ERR_INVALID_STATE", "Cannot sign past valid_until.")

    prev_status = agreement["status"]
    agreement["status"] = "ACTIVE"
    agreement["signed_at"] = now_iso_ms()
    bump_version(agreement)
    # pinned_fee_schedule_version = version (post-increment)
    agreement["pinned_fee_schedule_version"] = agreement["version"]

    emit_audit(
        "AGREEMENT",
        agreement["id"],
        "STATE_TRANSITION",
        role,
        user_id,
        {"from": prev_status, "to": "ACTIVE"},
    )
    emit_audit(
        "AGREEMENT",
        agreement["id"],
        "FIELD_CHANGE",
        role,
        user_id,
        {"field": "signed_at", "old": None, "new": agreement["signed_at"]},
    )

    # Renewal: predecessor -> RENEWED
    renewed_from_id = agreement.get("renewed_from_agreement_id")
    if renewed_from_id:
        predecessor = get_store().agreements.get(renewed_from_id)
        if predecessor:
            prev = predecessor.get("status")
            predecessor["status"] = "RENEWED"
            bump_version(predecessor)
            emit_audit(
                "AGREEMENT",
                predecessor["id"],
                "STATE_TRANSITION",
                role,
                user_id,
                {"from": prev, "to": "RENEWED"},
            )

    return agreement


def terminate_agreement(agreement_id: str, body: dict[str, Any]) -> dict[str, Any]:
    agreement = get_agreement(agreement_id)
    occ_check(agreement, body.get("version"))

    if agreement.get("status") not in {"DRAFT", "ACTIVE"}:
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Cannot terminate agreement in {agreement.get('status')!r}.",
        )

    terminated_reason = ensure_enum(
        body.get("terminated_reason"), "terminated_reason", TERMINATED_REASONS
    )

    # ACTIVE -> blocked if any non-terminal declaration exists
    if agreement["status"] == "ACTIVE":
        store = get_store()
        for d in store.declarations.values():
            if (
                d.get("agreement_id") == agreement_id
                and d.get("status") in DECLARATION_NON_TERMINAL
            ):
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "Cannot terminate agreement with non-terminal declarations.",
                )

    prev_status = agreement["status"]
    agreement["status"] = "TERMINATED"
    agreement["terminated_reason"] = terminated_reason
    bump_version(agreement)

    user_id, role = current_actor()
    emit_audit(
        "AGREEMENT",
        agreement_id,
        "STATE_TRANSITION",
        role,
        user_id,
        {"from": prev_status, "to": "TERMINATED"},
    )
    emit_audit(
        "AGREEMENT",
        agreement_id,
        "FIELD_CHANGE",
        role,
        user_id,
        {"field": "terminated_reason", "old": None, "new": terminated_reason},
    )
    return agreement
