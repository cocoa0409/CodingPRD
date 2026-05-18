"""Borrower endpoints: create, get, plaid snapshots, approve/suspend/reinstate/ban."""
from __future__ import annotations

from flask import Blueprint, g

from db import store
from errors import (
    err_borrower_has_losses,
    err_borrower_ungraded,
    err_duplicate_ein,
    err_forbidden_for_role,
    err_invalid_request,
    err_invalid_state_transition,
    err_no_plaid_snapshot,
)
from middleware import require_auth
from response import success
from routes._helpers import (
    enforce_compliance_officer_identity,
    get_borrower,
    get_json,
    get_platform,
)
from services.engine import (
    borrower_recompute_final,
    borrower_recompute_provisional,
    cascade_borrower_open_listings_withdraw,
    stamp_audit_only,
    stamp_create,
    stamp_update,
)
from services.serializers import serialize_borrower, serialize_plaid_snapshot
from utils import is_nonneg_int, is_pos_int

bp = Blueprint("borrowers", __name__)


# ── POST /platforms/{platformId}/borrowers ────────────────────────────────


@bp.post("/platforms/<platform_id>/borrowers")
@require_auth(["PlatformOperator"])
def create_borrower(platform_id):
    get_platform(platform_id)
    body = get_json()
    legal_name = body.get("legal_name")
    ein = body.get("ein")
    annual_revenue_cents = body.get("annual_revenue_cents")
    requested_amount_cents = body.get("requested_amount_cents")

    if not isinstance(legal_name, str) or not legal_name.strip():
        raise err_invalid_request("legal_name is required.")
    if not isinstance(ein, str) or not ein.strip():
        raise err_invalid_request("ein is required.")
    if not is_nonneg_int(annual_revenue_cents):
        raise err_invalid_request("annual_revenue_cents must be a non-negative integer.")
    if not is_pos_int(requested_amount_cents):
        raise err_invalid_request("requested_amount_cents must be a positive integer.")

    with store.lock:
        # EIN uniqueness within platform.
        for existing in store.borrowers_for_platform(platform_id):
            if existing["ein"] == ein:
                raise err_duplicate_ein()

        borrower = {
            "platform_id": platform_id,
            "legal_name": legal_name,
            "ein": ein,
            "annual_revenue_cents": annual_revenue_cents,
            "requested_amount_cents": requested_amount_cents,
            "plaid_snapshot_id": None,
            "provisional_grade": None,
            "final_grade": "UNGRADED",
            "status": "PENDING_KYC",
        }
        stamp_create(borrower)
        borrower_recompute_provisional(borrower)
        store.borrowers[borrower["id"]] = borrower
    return success(serialize_borrower(borrower), 201)


# ── GET /platforms/{platformId}/borrowers/{borrowerId} ────────────────────


@bp.get("/platforms/<platform_id>/borrowers/<borrower_id>")
@require_auth(["PlatformOperator", "ComplianceOfficer", "Borrower"])
def get_borrower_route(platform_id, borrower_id):
    b = get_borrower(platform_id, borrower_id)
    # Borrower role can only read its own record.
    if g.role == "Borrower":
        if g.user_id != borrower_id:
            raise err_forbidden_for_role("Borrower may only read their own record.")
    return success(serialize_borrower(b))


# ── POST /platforms/{platformId}/borrowers/{borrowerId}/plaid_snapshots ───


@bp.post("/platforms/<platform_id>/borrowers/<borrower_id>/plaid_snapshots")
@require_auth(["PlatformOperator"])
def attach_plaid_snapshot(platform_id, borrower_id):
    platform = get_platform(platform_id)
    borrower = get_borrower(platform_id, borrower_id)
    body = get_json()

    for f in (
        "deposits_last_90d_cents",
        "avg_daily_balance_cents",
        "nsf_count_last_90d",
        "existing_debt_service_cents",
    ):
        if not is_nonneg_int(body.get(f)):
            raise err_invalid_request(f"{f} must be a non-negative integer.")

    with store.lock:
        snapshot = {
            "borrower_id": borrower_id,
            "pulled_on_day_index": platform["clock_day_index"],
            "deposits_last_90d_cents": body["deposits_last_90d_cents"],
            "avg_daily_balance_cents": body["avg_daily_balance_cents"],
            "nsf_count_last_90d": body["nsf_count_last_90d"],
            "existing_debt_service_cents": body["existing_debt_service_cents"],
        }
        stamp_audit_only(snapshot)
        store.plaid_snapshots[snapshot["id"]] = snapshot

        # Borrower side effects.
        borrower["plaid_snapshot_id"] = snapshot["id"]
        borrower_recompute_final(borrower)
        stamp_update(borrower)
    return success(serialize_plaid_snapshot(snapshot), 201)


# ── State-changing borrower endpoints (ComplianceOfficer only) ────────────


def _co_route(platform_id, borrower_id, op):
    enforce_compliance_officer_identity(platform_id)
    return op(platform_id, borrower_id)


@bp.post("/platforms/<platform_id>/borrowers/<borrower_id>/approve")
@require_auth(["ComplianceOfficer"])
def approve_borrower(platform_id, borrower_id):
    enforce_compliance_officer_identity(platform_id)
    borrower = get_borrower(platform_id, borrower_id)
    if borrower["status"] != "PENDING_KYC":
        raise err_invalid_state_transition(
            f"Borrower not in PENDING_KYC (was {borrower['status']})."
        )
    if not borrower.get("plaid_snapshot_id"):
        raise err_no_plaid_snapshot()
    with store.lock:
        # Recompute final grade from latest snapshot before approving.
        borrower_recompute_final(borrower)
        if borrower["final_grade"] == "UNGRADED":
            raise err_borrower_ungraded()
        borrower["status"] = "APPROVED"
        stamp_update(borrower)
    return success(serialize_borrower(borrower))


@bp.post("/platforms/<platform_id>/borrowers/<borrower_id>/suspend")
@require_auth(["ComplianceOfficer"])
def suspend_borrower(platform_id, borrower_id):
    enforce_compliance_officer_identity(platform_id)
    borrower = get_borrower(platform_id, borrower_id)
    if borrower["status"] != "APPROVED":
        raise err_invalid_state_transition(
            f"Borrower not in APPROVED (was {borrower['status']})."
        )
    with store.lock:
        borrower["status"] = "SUSPENDED"
        stamp_update(borrower)
        cascade_borrower_open_listings_withdraw(borrower)
    return success(serialize_borrower(borrower))


@bp.post("/platforms/<platform_id>/borrowers/<borrower_id>/reinstate")
@require_auth(["ComplianceOfficer"])
def reinstate_borrower(platform_id, borrower_id):
    enforce_compliance_officer_identity(platform_id)
    borrower = get_borrower(platform_id, borrower_id)
    if borrower["status"] != "SUSPENDED":
        raise err_invalid_state_transition(
            f"Borrower not in SUSPENDED (was {borrower['status']})."
        )
    # ERR_BORROWER_HAS_LOSSES blocks reinstate when any loan is CHARGED_OFF.
    for loan in store.loans_for_borrower(borrower_id):
        if loan["status"] == "CHARGED_OFF":
            raise err_borrower_has_losses()
    with store.lock:
        borrower["status"] = "APPROVED"
        stamp_update(borrower)
    return success(serialize_borrower(borrower))


@bp.post("/platforms/<platform_id>/borrowers/<borrower_id>/ban")
@require_auth(["ComplianceOfficer"])
def ban_borrower(platform_id, borrower_id):
    enforce_compliance_officer_identity(platform_id)
    borrower = get_borrower(platform_id, borrower_id)
    if borrower["status"] not in ("APPROVED", "SUSPENDED"):
        raise err_invalid_state_transition(
            f"Borrower not bannable from {borrower['status']}."
        )
    with store.lock:
        was_suspended = borrower["status"] == "SUSPENDED"
        borrower["status"] = "BANNED"
        stamp_update(borrower)
        # Cascade only from APPROVED — SUSPENDED already collapsed open listings.
        if not was_suspended:
            cascade_borrower_open_listings_withdraw(borrower)
    return success(serialize_borrower(borrower))
