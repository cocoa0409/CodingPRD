"""Insurance policies and credit attestation periods."""
from flask import Blueprint, request

import auth
import clock
import db
import serializers as ser
import services
from config import (
    ATTESTATION_STATUSES,
    CREDIT_STATES,
    ROLE_ADJUSTER,
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_HOMEOWNER,
)
from errors import ApiError, bad_request
from response import created, enum_filter, listing, ok, page_params
from util import (
    D,
    get_body,
    req_datetime,
    req_int,
    req_string,
    req_upper,
    opt_int,
    whole_minutes,
)

bp = Blueprint("insurance", __name__)


def _policy(pid):
    row = db.policies.get(pid)
    if row is None:
        raise ApiError("ERR_POLICY_NOT_FOUND", "No policy exists with id %s." % pid)
    return row


def _attestation(aid):
    row = db.attestations.get(aid)
    if row is None:
        raise ApiError("ERR_ATTESTATION_NOT_FOUND", "No credit attestation exists with id %s." % aid)
    return row


# ---------------------------------------------------------------- reads
@bp.get("/policies/<pid>")
def get_policy(pid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ANALYST, ROLE_ADJUSTER, ROLE_ADMIN)
    row = _policy(pid)
    auth.own_policy(actor, row)
    return ok(ser.policy(row))


@bp.get("/policies/<pid>/credit-attestations")
def list_attestations(pid):
    actor = auth.guard(ROLE_HOMEOWNER, ROLE_ANALYST, ROLE_ADMIN)
    row = _policy(pid)
    limit, offset = page_params()
    auth.own_policy(actor, row)
    status = enum_filter("status", ATTESTATION_STATUSES)
    rows = db.attestations_for_policy(pid)
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    rows = db.sort_rows(rows, lambda a: a["period_start_at"])
    return listing(rows, ser.attestation, limit, offset)


# ---------------------------------------------------------------- writes
@bp.post("/policies")
def create_policy():
    auth.guard(ROLE_ANALYST)
    body = get_body(request)
    property_id = req_string(body, "property_id")
    insurer_code = req_upper(body, "insurer_code", 2, 12)
    policy_number = req_string(body, "policy_number", 4, 32)
    premium = req_int(body, "annual_premium_cents", minimum=10000)
    year_start = req_datetime(body, "policy_year_start_at")
    expected = req_int(body, "expected_property_version", minimum=0)
    deductible = opt_int(body, "deductible_cents", minimum=0, default=100000)
    prop = db.properties.get(property_id)
    if prop is None:
        raise ApiError("ERR_PROPERTY_NOT_FOUND", "No property exists with id %s." % property_id)
    auth.alive_property(prop)
    if expected != prop["version"]:
        raise ApiError(
            "ERR_STALE_PROPERTY_VERSION",
            "expected_property_version does not match the property's current version.",
        )
    for existing in db.policies.values():
        if existing["policy_number"] == policy_number:
            raise ApiError(
                "ERR_POLICY_NUMBER_TAKEN",
                "Policy number %s is already held by another policy." % policy_number,
            )

    for prior in db.policies_for_property(property_id):
        if prior["credit_state"] == "TERMINATED":
            continue
        if prior["credit_state"] == "CREDIT_ACTIVE":
            prior["current_credit_tier_pct"] = D("0")
        prior["credit_state"] = "TERMINATED"
        db.touch(prior)

    row = {
        "property_id": property_id,
        "insurer_code": insurer_code,
        "policy_number": policy_number,
        "annual_premium_cents": premium,
        "deductible_cents": deductible,
        "policy_year_start_at": year_start,
        "credit_state": "PENDING_ENROLLMENT",
        "current_credit_tier_pct": D("0"),
        "credited_cents_total": 0,
        "clawback_cents_total": 0,
        "true_up_cents": 0,
        "paid_payout_cents_total": 0,
        "last_attestation_end_at": None,
        "suspended_reason": None,
    }
    db.insert(db.policies, row)
    db.touch(prop)
    return created(ser.policy(row))


@bp.post("/policies/<pid>/credit-attestations")
def open_attestation(pid):
    auth.guard(ROLE_ANALYST)
    policy_row = _policy(pid)
    body = get_body(request)
    start_at = req_datetime(body, "period_start_at")
    end_at = req_datetime(body, "period_end_at")
    if end_at <= start_at:
        raise bad_request("Field 'period_end_at' must be strictly after 'period_start_at'.")
    prop = db.properties[policy_row["property_id"]]
    auth.alive_property(prop)

    device_row = services.resolve_device_for_property(policy_row["property_id"])
    profile = db.profile_for_device(device_row["id"]) if device_row else None
    if profile is None or profile["learning_state"] != "COMPLETE":
        raise ApiError(
            "ERR_BASELINE_NOT_COMPLETE",
            "The property's device has no COMPLETE baseline profile.",
        )
    for existing in db.attestations_for_policy(pid):
        if start_at < existing["period_end_at"] and existing["period_start_at"] < end_at:
            raise ApiError(
                "ERR_ATTESTATION_PERIOD_OVERLAP",
                "The submitted span overlaps an existing attestation period.",
            )
    anchor = policy_row.get("last_attestation_end_at") or policy_row["policy_year_start_at"]
    if start_at != anchor:
        raise ApiError(
            "ERR_ATTESTATION_PERIOD_NOT_CONTIGUOUS",
            "period_start_at must continue the policy's attestation chain.",
        )
    if policy_row["credit_state"] == "TERMINATED":
        raise ApiError("ERR_POLICY_TERMINATED", "This policy has been terminated.")

    row = {
        "policy_id": pid,
        "period_start_at": start_at,
        "period_end_at": end_at,
        "status": "OPEN",
        "period_minutes": whole_minutes(end_at - start_at),
        "covered_minutes": None,
        "uptime_pct": None,
        "offline_gap_count": None,
        "tier_pct": None,
        "credit_cents_awarded": 0,
        "true_up_cents": 0,
        "is_policy_year_close": False,
        "device_snapshot_lifecycle_state": None,
        "denial_reason": None,
        "finalized_at": None,
    }
    db.insert(db.attestations, row)
    return created(ser.attestation(row))


@bp.post("/credit-attestations/<aid>/finalize")
def finalize(aid):
    auth.guard(ROLE_ANALYST)
    att = _attestation(aid)
    policy_row = db.policies[att["policy_id"]]
    prop = db.properties[policy_row["property_id"]]
    auth.alive_property(prop)
    if att["status"] != "OPEN":
        raise ApiError("ERR_ATTESTATION_NOT_OPEN", "This attestation has already been finalized.")
    if clock.now() < att["period_end_at"]:
        raise ApiError(
            "ERR_ATTESTATION_PERIOD_NOT_ENDED",
            "The attestation period has not yet reached its end instant.",
        )
    if policy_row["credit_state"] == "TERMINATED":
        raise ApiError("ERR_POLICY_TERMINATED", "This policy has been terminated.")
    services.finalize_attestation(att, policy_row)
    return ok(ser.attestation(att))
