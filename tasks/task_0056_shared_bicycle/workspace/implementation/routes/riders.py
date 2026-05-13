"""Rider endpoints (PRD §3.3)."""
from __future__ import annotations

from flask import Blueprint, g

from constants import MONTHLY_PASS_DURATION_MINUTES, MONTHLY_PASS_PRICE_CENTS
from db import LOCK, new_id, regions, riders
from errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_INSUFFICIENT_BALANCE,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    raise_err,
)
from middleware import require_role, require_rider_owner
from response import success_object
from services.audit import write_audit
from services.validators import (
    bump_version,
    ensure_positive_int,
    get_json_body,
)
from time_utils import now_iso


bp = Blueprint("riders", __name__)


def serialize_rider(r: dict) -> dict:
    return dict(r)


def _global_clock() -> int:
    """A 'global' clock value for monthly-pass arithmetic.

    PRD §3.3: pass expiration is `current clock_minutes + 43200 minutes`,
    but there is no truly global clock — only per-region clocks. We use
    the maximum clock_minutes across regions as a coherent proxy (or 0 if
    no regions exist).
    """
    if not regions:
        return 0
    return max(int(r.get("clock_minutes", 0)) for r in regions.values())


@bp.post("/riders")
def create_rider():
    require_role("Admin")
    body = get_json_body()
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise_err(ERR_VALIDATION, "name is required")
    with LOCK:
        rid = new_id()
        ts = now_iso()
        rider = {
            "id": rid,
            "name": name,
            "wallet_balance_cents": 0,
            "monthly_pass_expires_minute": 0,
            "free_minutes_remaining": 0,
            "status": "ACTIVE",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        riders[rid] = rider
    return success_object(serialize_rider(rider), status=201)


@bp.get("/riders/<rider_id>")
def get_rider(rider_id):
    require_role("Rider", "Admin")
    rider = riders.get(rider_id)
    if rider is None:
        raise_err(ERR_NOT_FOUND, "Rider not found")
    require_rider_owner(rider_id)
    return success_object(serialize_rider(rider))


@bp.post("/riders/<rider_id>/wallet/credit")
def credit_wallet(rider_id):
    require_role("Admin")
    rider = riders.get(rider_id)
    if rider is None:
        raise_err(ERR_NOT_FOUND, "Rider not found")
    body = get_json_body()
    if "amount_cents" not in body:
        raise_err(ERR_VALIDATION, "amount_cents is required")
    amount = ensure_positive_int(body["amount_cents"], "amount_cents")
    with LOCK:
        before = {"wallet_balance_cents": rider["wallet_balance_cents"]}
        rider["wallet_balance_cents"] += amount
        bump_version(rider)
        write_audit(
            event_kind="BILLING_ADJUSTMENT",
            action="WALLET_CREDIT",
            subject_type="Rider",
            subject_id=rider_id,
            before=before,
            after={"wallet_balance_cents": rider["wallet_balance_cents"]},
        )
    return success_object(serialize_rider(rider))


@bp.post("/riders/<rider_id>/monthly-pass")
def buy_monthly_pass(rider_id):
    require_role("Rider")
    rider = riders.get(rider_id)
    if rider is None:
        raise_err(ERR_NOT_FOUND, "Rider not found")
    require_rider_owner(rider_id)
    with LOCK:
        if rider["wallet_balance_cents"] < MONTHLY_PASS_PRICE_CENTS:
            raise_err(ERR_INSUFFICIENT_BALANCE, "Wallet balance too low for monthly pass")
        before = {
            "wallet_balance_cents": rider["wallet_balance_cents"],
            "monthly_pass_expires_minute": rider["monthly_pass_expires_minute"],
        }
        rider["wallet_balance_cents"] -= MONTHLY_PASS_PRICE_CENTS
        rider["monthly_pass_expires_minute"] = _global_clock() + MONTHLY_PASS_DURATION_MINUTES
        bump_version(rider)
        write_audit(
            event_kind="BILLING_ADJUSTMENT",
            action="MONTHLY_PASS_PURCHASE",
            subject_type="Rider",
            subject_id=rider_id,
            before=before,
            after={
                "wallet_balance_cents": rider["wallet_balance_cents"],
                "monthly_pass_expires_minute": rider["monthly_pass_expires_minute"],
            },
        )
        write_audit(
            event_kind="EXTERNAL_SYNC",
            action="PAYMENT_SYNC",
            subject_type="Rider",
            subject_id=rider_id,
            before={},
            after={
                "kind": "monthly_pass_purchase",
                "price_cents": MONTHLY_PASS_PRICE_CENTS,
            },
        )
    return success_object(serialize_rider(rider))


@bp.post("/riders/<rider_id>/free-minutes/grant")
def grant_free_minutes(rider_id):
    require_role("Admin")
    rider = riders.get(rider_id)
    if rider is None:
        raise_err(ERR_NOT_FOUND, "Rider not found")
    body = get_json_body()
    if "minutes" not in body:
        raise_err(ERR_VALIDATION, "minutes is required")
    minutes = ensure_positive_int(body["minutes"], "minutes")
    with LOCK:
        rider["free_minutes_remaining"] += minutes
        bump_version(rider)
    return success_object(serialize_rider(rider))
