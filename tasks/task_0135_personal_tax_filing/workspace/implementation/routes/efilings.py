"""EFiling routes (PRD §3.8)."""
from __future__ import annotations

from flask import Blueprint, g

from config import (
    EFILING_ACCEPTED,
    EFILING_PENDING,
    EFILING_REJECTED,
    RETURN_STATUS_ACCEPTED,
    RETURN_STATUS_FILED,
    RETURN_STATUS_REJECTED,
    ROLE_IRSADJUDICATOR,
    ROLE_TAXPAYER,
)
from db import store
from errors import (
    err_forbidden,
    err_invalid_input,
    err_invalid_state,
)
from middleware import require_auth
from response import success
from services import engine
from services.audit import append_audit
from utils import iso_now, is_nonempty_str

from routes._helpers import (
    get_efiling_or_404,
    get_json,
    get_return_or_404,
)


bp = Blueprint("efilings", __name__)


def _serialize_efiling(e: dict) -> dict:
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "tax_return_id": e["tax_return_id"],
        "submission_id": e["submission_id"],
        "outcome": e["outcome"],
        "rejection_code": e.get("rejection_code"),
        "rejection_message": e.get("rejection_message"),
        "filed_at": e.get("filed_at"),
        "processed_at": e.get("processed_at"),
    }


# ── GET /efilings/{id} ──────────────────────────────────────────────────


@bp.get("/efilings/<efiling_id>")
@require_auth([ROLE_TAXPAYER, ROLE_IRSADJUDICATOR])
def get_efiling(efiling_id):
    e = get_efiling_or_404(efiling_id)
    if g.role == ROLE_TAXPAYER:
        # Taxpayer must own the underlying return.
        r = get_return_or_404(e["tax_return_id"])
        if r["taxpayer_id"] != g.user_id:
            raise err_forbidden("Taxpayer can only access their own EFilings")
    return success(_serialize_efiling(e), 200)


# ── POST /efilings/{id}/decide ──────────────────────────────────────────


@bp.post("/efilings/<efiling_id>/decide")
@require_auth([ROLE_IRSADJUDICATOR])
def decide_efiling(efiling_id):
    body = get_json()
    outcome = body.get("outcome")
    rejection_code = body.get("rejection_code")
    rejection_message = body.get("rejection_message")

    if outcome not in (EFILING_ACCEPTED, EFILING_REJECTED):
        raise err_invalid_input("outcome must be ACCEPTED or REJECTED")
    if outcome == EFILING_REJECTED and not is_nonempty_str(rejection_code):
        raise err_invalid_input("rejection_code is required when outcome=REJECTED")

    with store.lock:
        e = get_efiling_or_404(efiling_id)
        if e["outcome"] != EFILING_PENDING:
            raise err_invalid_state("EFiling has already been decided")
        r = get_return_or_404(e["tax_return_id"])
        if r["status"] != RETURN_STATUS_FILED:
            raise err_invalid_state("Underlying TaxReturn is not in FILED state")

        now_iso = iso_now(store.clock_now())
        e["outcome"] = outcome
        e["processed_at"] = now_iso
        if outcome == EFILING_ACCEPTED:
            r["status"] = RETURN_STATUS_ACCEPTED
            r["accepted_at"] = now_iso
            engine.stamp_update(r)
            append_audit(
                actor_role=g.role,
                actor_id=g.user_id,
                action="RETURN_ACCEPTED",
                target_entity="TaxReturn",
                target_id=r["id"],
                payload={"efiling_id": e["id"]},
            )
        else:
            e["rejection_code"] = rejection_code
            e["rejection_message"] = rejection_message
            r["status"] = RETURN_STATUS_REJECTED
            engine.stamp_update(r)
            append_audit(
                actor_role=g.role,
                actor_id=g.user_id,
                action="RETURN_REJECTED",
                target_entity="TaxReturn",
                target_id=r["id"],
                payload={
                    "efiling_id": e["id"],
                    "rejection_code": rejection_code,
                    "rejection_message": rejection_message,
                },
            )

    return success(_serialize_efiling(e), 200)
