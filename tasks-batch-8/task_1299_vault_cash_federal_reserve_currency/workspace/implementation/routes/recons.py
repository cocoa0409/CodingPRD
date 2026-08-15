"""Reconciliation endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth, ALL_ROLES, SITE_SCOPED_STAFF_ROLES, require_site_scope
from response import ok, ok_list
from services import (
    stamp_new, touch, public, refresh_recon_final, ledger_sum_for_recon_at,
    derive_site_posture, RECON_TOLERANCE_CENTS,
)
from util import body, required, as_int, as_str, as_ymd, pagination_args, created_ts_key

bp = Blueprint("recons", __name__)


def _get_recon_or_404(recon_id):
    recon = DB["reconciliations"].get(recon_id)
    if recon is None:
        raise ApiError(
            "ERR_RECONCILIATION_NOT_FOUND", 404, "Reconciliation not found"
        )
    return recon


def _site_or_404(site_id):
    site = DB["vault_sites"].get(site_id)
    if site is None:
        raise ApiError("ERR_VAULT_SITE_NOT_FOUND", 404, "Vault site not found")
    return site


@bp.post("/vault-cash/reconciliations")
def create_recon():
    principal = auth(["VaultCustodian"])
    data = body()
    site_id = as_str(required(data, "site_id"), "site_id")
    _site_or_404(site_id)
    require_site_scope(principal, site_id)
    business_date = as_ymd(required(data, "business_date"), "business_date")
    opening = as_int(
        required(data, "opening_balance_cents"), "opening_balance_cents"
    )
    # One reconciliation per (site, business_date).
    for r in DB["reconciliations"].values():
        if r["site_id"] == site_id and r["business_date"] == business_date:
            raise ApiError(
                "ERR_DUPLICATE_RECONCILIATION",
                409,
                "Reconciliation already exists for this site and business date",
            )
    recon = stamp_new({
        "id": new_id(),
        "site_id": site_id,
        "business_date": business_date,
        "opening_balance_cents": opening,
        "counted_on_hand_cents": None,
        "counted_by_staff_id": None,
        "provisional_expected_cents": 0,
        "final_expected_cents": 0,
        "variance_cents": None,
        "approved_by_staff_id": None,
        "status": "OPEN",
    })
    # Provisional snapshot frozen at open: entries created at/before this instant.
    recon["provisional_expected_cents"] = opening + ledger_sum_for_recon_at(
        site_id, business_date, recon["_seq"]
    )
    DB["reconciliations"][recon["id"]] = recon
    # Final expectation includes all matching entries regardless of creation time.
    refresh_recon_final(recon)
    return ok(public(recon), status=201)


@bp.get("/vault-cash/reconciliations")
def list_recons():
    principal = auth(ALL_ROLES)
    limit, offset = pagination_args()
    site_id = request.args.get("site_id")
    business_date = request.args.get("business_date")
    status = request.args.get("status")
    rows = list(DB["reconciliations"].values())
    if site_id is not None:
        rows = [r for r in rows if r["site_id"] == site_id]
    if business_date is not None:
        rows = [r for r in rows if r["business_date"] == business_date]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if principal.role in SITE_SCOPED_STAFF_ROLES:
        rows = [r for r in rows if r["site_id"] == principal.home_site_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return ok_list([public(r) for r in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/vault-cash/reconciliations/<reconId>")
def get_recon(reconId):
    principal = auth(ALL_ROLES)
    recon = _get_recon_or_404(reconId)
    require_site_scope(principal, recon["site_id"])
    return ok(public(recon))


@bp.post("/vault-cash/reconciliations/<reconId>/count")
def count_recon(reconId):
    principal = auth(["VaultCustodian"])
    recon = _get_recon_or_404(reconId)
    require_site_scope(principal, recon["site_id"])
    data = body()
    counted = as_int(required(data, "counted_on_hand_cents"), "counted_on_hand_cents")
    if recon["status"] != "OPEN":
        raise ApiError(
            "ERR_RECON_INVALID_STATE", 409, "Only OPEN reconciliations may be counted"
        )
    recon["counted_on_hand_cents"] = counted
    recon["counted_by_staff_id"] = principal.user_id
    recon["variance_cents"] = counted - recon["final_expected_cents"]
    # Auto-fork: within tolerance -> BALANCED, else VARIANCE_PENDING.
    if abs(recon["variance_cents"]) <= RECON_TOLERANCE_CENTS:
        recon["status"] = "BALANCED"
    else:
        recon["status"] = "VARIANCE_PENDING"
    touch(recon)
    return ok(public(recon))


@bp.post("/vault-cash/reconciliations/<reconId>/escalate")
def escalate_recon(reconId):
    principal = auth(["VaultCustodian"])
    recon = _get_recon_or_404(reconId)
    require_site_scope(principal, recon["site_id"])
    if recon["status"] != "VARIANCE_PENDING":
        raise ApiError(
            "ERR_RECON_INVALID_STATE",
            409,
            "Only VARIANCE_PENDING reconciliations may be escalated",
        )
    recon["status"] = "ESCALATED"
    touch(recon)
    site = _site_or_404(recon["site_id"])
    derive_site_posture(site)
    touch(site)
    return ok(public(recon))


@bp.post("/vault-cash/reconciliations/<reconId>/approve")
def approve_recon(reconId):
    principal = auth(["CashOperationsAdmin"])
    recon = _get_recon_or_404(reconId)
    if recon["status"] not in ("VARIANCE_PENDING", "ESCALATED"):
        raise ApiError(
            "ERR_RECON_INVALID_STATE",
            409,
            "Only VARIANCE_PENDING or ESCALATED reconciliations may be approved",
        )
    recon["status"] = "APPROVED"
    recon["approved_by_staff_id"] = principal.user_id
    touch(recon)
    return ok(public(recon))


@bp.post("/vault-cash/reconciliations/<reconId>/lock")
def lock_recon(reconId):
    principal = auth(["VaultCustodian", "CashOperationsAdmin"])
    recon = _get_recon_or_404(reconId)
    require_site_scope(principal, recon["site_id"])
    if recon["status"] not in ("BALANCED", "APPROVED"):
        raise ApiError(
            "ERR_RECON_INVALID_STATE",
            409,
            "Only BALANCED or APPROVED reconciliations may be locked",
        )
    # SoD: locker must not be the identity that submitted the count.
    if principal.user_id == recon.get("counted_by_staff_id"):
        raise ApiError(
            "ERR_SOD_VIOLATION", 403, "Locker must differ from the counter"
        )
    recon["status"] = "LOCKED"
    recon["approved_by_staff_id"] = principal.user_id
    touch(recon)
    return ok(public(recon))
