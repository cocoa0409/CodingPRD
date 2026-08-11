"""Claim routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from clock import fmt_ts, now_iso
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services import constants as C
from services.audit import log
from services.core import (
    body,
    compute_coverage_confirmed,
    find_tpa,
    get_captive,
    get_claim,
    get_program,
    next_claim_number,
    parse_dt_field,
    recompute_captive_ledger,
    recompute_claim_net,
    recompute_program_loss_ratio,
    recompute_unit_loss_ratio,
    req_num,
    req_str,
    stamp_new,
    touch,
    touch_captive,
)

bp = Blueprint("claims", __name__)

READ_ROLES = ("CaptiveManager", "Underwriter", "Actuary", "ClaimsAdjuster")


def _chain(captiveId, programId):
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    return captive, program


def _unit_ratio_sync(claim):
    unit = db.units.get(claim.get("operating_unit_id"))
    if unit:
        recompute_unit_loss_ratio(unit)


@bp.post("/api/captives/<captiveId>/programs/<programId>/claims")
def create_claim(captiveId, programId):
    user_id, role = require_roles("ClaimsAdjuster")
    captive, program = _chain(captiveId, programId)
    data = body()

    unit_id = data.get("operating_unit_id")
    if not unit_id or not isinstance(unit_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "operating_unit_id is required")
    unit = db.units.get(unit_id)
    if unit is None or unit["captive_id"] != captiveId:
        raise ApiError("ERR_OPERATING_UNIT_MISMATCH",
                       "Operating unit does not belong to the same captive")

    claimant = req_str(data, "claimant_name")
    loss_dt = parse_dt_field(data, "loss_date")
    claimed = req_num(data, "claimed_amount_cents")
    tpa_id = data.get("tpa_assigned_id")

    from clock import parse_ts
    start = parse_ts(program["policy_period_start"])
    end = parse_ts(program["policy_period_end"])
    if start is None or end is None or loss_dt < start or loss_dt > end:
        raise ApiError("ERR_LOSS_DATE_OUT_OF_PERIOD",
                       "Loss date falls outside the policy period")

    coverage = compute_coverage_confirmed(program, loss_dt, int(claimed))

    claim = stamp_new()
    claim.update({
        "program_id": programId,
        "operating_unit_id": unit_id,
        "captive_id": captiveId,
        "claim_number": next_claim_number(),
        "claimant_name": claimant,
        "loss_date": fmt_ts(loss_dt),
        "reported_date": now_iso(),
        "claimed_amount_cents": int(claimed),
        "reserved_amount_cents": 0,
        "paid_amount_cents": 0,
        "recoverable_amount_cents": 0,
        "net_incurred_cents": 0,
        "tpa_assigned_id": tpa_id,
        "coverage_confirmed": coverage,
        "claim_status": "REPORTED",
        "payment_status": "UNPAID",
        "litigation_status": "NOT_LITIGATED",
    })
    db.claims[claim["id"]] = claim
    _unit_ratio_sync(claim)
    log(captiveId, "STATE_CHANGE", "Claim", claim["id"], role, user_id,
        f"Claim {claim['claim_number']} reported", None, "REPORTED")
    return ok(claim, 201)


@bp.get("/api/captives/<captiveId>/programs/<programId>/claims")
def list_claims(captiveId, programId):
    require_roles(*READ_ROLES)
    _chain(captiveId, programId)
    items = [c for c in db.claims.values() if c["program_id"] == programId]
    unit_filter = request.args.get("operating_unit_id")
    if unit_filter:
        items = [c for c in items if c["operating_unit_id"] == unit_filter]
    status_filter = request.args.get("claim_status")
    if status_filter:
        items = [c for c in items if c["claim_status"] == status_filter]
    items.sort(key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok(page, 200, meta)


@bp.get("/api/captives/<captiveId>/programs/<programId>/claims/<claimId>")
def get_claim_route(captiveId, programId, claimId):
    require_roles(*READ_ROLES)
    _, program = _chain(captiveId, programId)
    return ok(get_claim(program, claimId), 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/claims/<claimId>/acknowledge")
def acknowledge_claim(captiveId, programId, claimId):
    user_id, role = require_roles("ClaimsAdjuster")
    captive, program = _chain(captiveId, programId)
    claim = get_claim(program, claimId)
    if claim["claim_status"] != "REPORTED":
        raise ApiError("ERR_CLAIM_NOT_REPORTED",
                       "Claim must be in REPORTED state")
    if not claim.get("coverage_confirmed"):
        raise ApiError("ERR_COVERAGE_NOT_CONFIRMED",
                       "Claim coverage not confirmed")
    prev = claim["claim_status"]
    claim["claim_status"] = "ACKNOWLEDGED"
    touch(claim)
    recompute_program_loss_ratio(program)
    log(captiveId, "STATE_CHANGE", "Claim", claimId, role, user_id,
        "Claim acknowledged", prev, "ACKNOWLEDGED")
    return ok(claim, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/claims/<claimId>/investigate")
def investigate_claim(captiveId, programId, claimId):
    user_id, role = require_roles("ClaimsAdjuster")
    captive, program = _chain(captiveId, programId)
    claim = get_claim(program, claimId)
    if claim["claim_status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_CLAIM_NOT_ACKNOWLEDGED",
                       "Claim must be in ACKNOWLEDGED state")
    prev = claim["claim_status"]
    claim["claim_status"] = "UNDER_INVESTIGATION"
    touch(claim)
    log(captiveId, "STATE_CHANGE", "Claim", claimId, role, user_id,
        "Claim under investigation", prev, "UNDER_INVESTIGATION")
    return ok(claim, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/claims/<claimId>/set-reserve")
def set_reserve_claim(captiveId, programId, claimId):
    user_id, role = require_roles("Actuary")
    captive, program = _chain(captiveId, programId)
    claim = get_claim(program, claimId)
    if claim["claim_status"] != "UNDER_INVESTIGATION":
        raise ApiError("ERR_CLAIM_NOT_UNDER_INVESTIGATION",
                       "Claim must be in UNDER_INVESTIGATION state")
    data = body()
    reserve_amount = req_num(data, "reserve_amount_cents")
    prev = claim["claim_status"]
    claim["reserved_amount_cents"] = int(reserve_amount)
    claim["claim_status"] = "RESERVED"
    recompute_claim_net(claim)
    touch(claim)
    recompute_program_loss_ratio(program)
    _unit_ratio_sync(claim)
    recompute_captive_ledger(captive)
    log(captiveId, "STATE_CHANGE", "Claim", claimId, role, user_id,
        f"Reserve set to {int(reserve_amount)} cents", prev, "RESERVED")
    return ok(claim, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/claims/<claimId>/settle")
def settle_claim(captiveId, programId, claimId):
    user_id, role = require_roles("ClaimsAdjuster")
    captive, program = _chain(captiveId, programId)
    claim = get_claim(program, claimId)
    data = body()

    # OCC guard against the parent captive's version.
    expected = data.get("expected_captive_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST",
                       "expected_captive_version is required and must be an integer")
    if expected != captive["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "Expected version does not match current version; resource has been modified")

    settlement = req_num(data, "settlement_amount_cents")
    settlement = int(settlement)

    if claim["claim_status"] != "RESERVED":
        raise ApiError("ERR_CLAIM_NOT_RESERVED",
                       "Claim must be in RESERVED state")
    if settlement > int(program.get("per_occurrence_limit_cents") or 0):
        raise ApiError("ERR_SETTLEMENT_EXCEEDS_LIMIT",
                       "Settlement amount exceeds per-occurrence limit")
    tpa = find_tpa(claim.get("tpa_assigned_id"))
    if tpa is not None and settlement > int(tpa.get("authority_limit_cents") or 0):
        raise ApiError("ERR_SETTLEMENT_EXCEEDS_TPA_AUTHORITY",
                       "Settlement amount exceeds TPA authority limit")

    prev_reserved = int(claim.get("reserved_amount_cents") or 0)
    prev = claim["claim_status"]
    claim["claim_status"] = "SETTLED"
    claim["paid_amount_cents"] = settlement
    claim["payment_status"] = ("FULLY_PAID" if settlement >= prev_reserved
                               else "PARTIALLY_PAID")
    claim["reserved_amount_cents"] = 0
    recompute_claim_net(claim)
    touch(claim)
    recompute_program_loss_ratio(program)
    _unit_ratio_sync(claim)
    recompute_captive_ledger(captive)
    touch_captive(captive)  # settle increments captive version
    log(captiveId, "STATE_CHANGE", "Claim", claimId, role, user_id,
        f"Claim settled for {settlement} cents", prev, "SETTLED")
    return ok(claim, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/claims/<claimId>/deny")
def deny_claim(captiveId, programId, claimId):
    user_id, role = require_roles("ClaimsAdjuster")
    captive, program = _chain(captiveId, programId)
    claim = get_claim(program, claimId)
    if claim["claim_status"] != "RESERVED":
        raise ApiError("ERR_CLAIM_NOT_RESERVED",
                       "Claim must be in RESERVED state")
    prev = claim["claim_status"]
    claim["claim_status"] = "DENIED"
    claim["reserved_amount_cents"] = 0
    recompute_claim_net(claim)
    touch(claim)
    recompute_program_loss_ratio(program)
    _unit_ratio_sync(claim)
    recompute_captive_ledger(captive)
    log(captiveId, "STATE_CHANGE", "Claim", claimId, role, user_id,
        "Claim denied; reserve released", prev, "DENIED")
    return ok(claim, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/claims/<claimId>/close-without-payment")
def close_without_payment_claim(captiveId, programId, claimId):
    user_id, role = require_roles("ClaimsAdjuster")
    captive, program = _chain(captiveId, programId)
    claim = get_claim(program, claimId)
    if claim["claim_status"] != "RESERVED":
        raise ApiError("ERR_CLAIM_NOT_RESERVED",
                       "Claim must be in RESERVED state")
    if int(claim.get("paid_amount_cents") or 0) != 0:
        raise ApiError("ERR_CLAIM_HAS_PAYMENTS",
                       "Claim has existing payments; cannot close without payment")
    prev = claim["claim_status"]
    claim["claim_status"] = "CLOSED_WITHOUT_PAYMENT"
    claim["reserved_amount_cents"] = 0
    recompute_claim_net(claim)
    touch(claim)
    recompute_program_loss_ratio(program)
    _unit_ratio_sync(claim)
    recompute_captive_ledger(captive)
    log(captiveId, "STATE_CHANGE", "Claim", claimId, role, user_id,
        "Claim closed without payment; reserve released", prev,
        "CLOSED_WITHOUT_PAYMENT")
    return ok(claim, 200)
