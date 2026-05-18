"""OptionsApproval routes: submit, get, start-review, decide, patch."""
from __future__ import annotations

from flask import Blueprint, g

import config as cfg
from db import store
from errors import (
    err_account_not_approved,
    err_invalid_state,
    err_kyc_not_verified,
    err_options_approval_in_progress,
    err_options_level_exceeds_eligibility,
    err_ownership,
    err_revision_limit_reached,
    err_validation,
)
from middleware import require_auth
from response import success
from routes._helpers import (
    check_version,
    enforce_customer_owns_account,
    get_account_or_404,
    get_json,
    get_options_approval_or_404,
    require_int,
    require_str,
)
from services.calculations import options_eligibility_max
from services.engine import touch
from services.serializers import options_approval_view
from utils import new_uuid


bp = Blueprint("options_approvals", __name__)


# ── POST /brokerage/options-approvals ──────────────────────────────────────

@bp.post("/brokerage/options-approvals")
@require_auth([cfg.ROLE_CUSTOMER])
def submit_options_approval():
    body = get_json()
    account_id = require_str(body, "account_id")
    a = get_account_or_404(account_id)
    enforce_customer_owns_account(a)

    # Posture gates.
    if a["status"] != cfg.ACCT_STATUS_APPROVED:
        raise err_account_not_approved()
    c = store.customers.get(a["customer_id"])
    if c is None or c["kyc_status"] != cfg.KYC_VERIFIED:
        raise err_kyc_not_verified()

    requested_level = require_int(body, "requested_level", minimum=1, maximum=4)

    # At most one non-terminal OptionsApproval per account.
    for oa in store.options_approvals.values():
        if oa["account_id"] == account_id and oa["status"] in cfg.OA_NON_TERMINAL:
            raise err_options_approval_in_progress()

    now = store.now()
    oid = new_uuid()
    oa = {
        "id": oid,
        "account_id": account_id,
        "requested_level": requested_level,
        "status": cfg.OA_SUBMITTED,
        "approved_level": None,
        "review_notes": None,
        "revision_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    with store.lock:
        store.options_approvals[oid] = oa
    return success(options_approval_view(oa), 201)


# ── GET /brokerage/options-approvals/{id} ──────────────────────────────────

@bp.get("/brokerage/options-approvals/<oa_id>")
@require_auth([cfg.ROLE_CUSTOMER, cfg.ROLE_COMPLIANCE])
def get_options_approval(oa_id: str):
    oa = get_options_approval_or_404(oa_id)
    if g.role == cfg.ROLE_CUSTOMER:
        a = store.accounts.get(oa["account_id"])
        if a is None or a["customer_id"] != g.user_id:
            raise err_ownership()
    return success(options_approval_view(oa), 200)


# ── POST /brokerage/options-approvals/{id}/start-review ────────────────────

@bp.post("/brokerage/options-approvals/<oa_id>/start-review")
@require_auth([cfg.ROLE_COMPLIANCE])
def start_review(oa_id: str):
    oa = get_options_approval_or_404(oa_id)
    a = store.accounts.get(oa["account_id"])
    if a is None:
        raise err_invalid_state("orphaned options approval")
    # Posture gates.
    if a["status"] != cfg.ACCT_STATUS_APPROVED:
        raise err_account_not_approved()
    c = store.customers.get(a["customer_id"])
    if c is None or c["kyc_status"] != cfg.KYC_VERIFIED:
        raise err_kyc_not_verified()

    if oa["status"] != cfg.OA_SUBMITTED:
        raise err_invalid_state("start-review requires SUBMITTED")

    now = store.now()
    with store.lock:
        oa["status"] = cfg.OA_UNDER_REVIEW
        touch(oa, now)
    return success(options_approval_view(oa), 200)


# ── POST /brokerage/options-approvals/{id}/decide ──────────────────────────

@bp.post("/brokerage/options-approvals/<oa_id>/decide")
@require_auth([cfg.ROLE_COMPLIANCE])
def decide(oa_id: str):
    oa = get_options_approval_or_404(oa_id)
    a = store.accounts.get(oa["account_id"])
    if a is None:
        raise err_invalid_state("orphaned options approval")
    if a["status"] != cfg.ACCT_STATUS_APPROVED:
        raise err_account_not_approved()
    c = store.customers.get(a["customer_id"])
    if c is None or c["kyc_status"] != cfg.KYC_VERIFIED:
        raise err_kyc_not_verified()

    if oa["status"] != cfg.OA_UNDER_REVIEW:
        raise err_invalid_state("decide requires UNDER_REVIEW")

    body = get_json()
    decision = require_str(body, "decision")
    if decision not in ("APPROVE", "REJECT", "REQUEST_REVISION"):
        raise err_validation("decision must be APPROVE | REJECT | REQUEST_REVISION")

    now = store.now()

    if decision == "APPROVE":
        approved_level = require_int(body, "approved_level", minimum=1, maximum=4)
        eligibility_max = options_eligibility_max(c)
        if approved_level > eligibility_max:
            raise err_options_level_exceeds_eligibility()
        with store.lock:
            oa["status"] = cfg.OA_APPROVED
            oa["approved_level"] = approved_level
            touch(oa, now)
            # Account.options_level = max(current, approved_level)
            if approved_level > a["options_level"]:
                a["options_level"] = approved_level
                touch(a, now)
    elif decision == "REQUEST_REVISION":
        notes = require_str(body, "notes")
        if not notes.strip():
            raise err_validation("notes required for REQUEST_REVISION")
        if oa["revision_count"] >= cfg.MAX_REVISIONS:
            raise err_revision_limit_reached()
        with store.lock:
            oa["status"] = cfg.OA_REVISION_REQUESTED
            oa["review_notes"] = notes
            touch(oa, now)
    else:  # REJECT
        notes = require_str(body, "notes")
        if not notes.strip():
            raise err_validation("notes required for REJECT")
        with store.lock:
            oa["status"] = cfg.OA_REJECTED
            oa["review_notes"] = notes
            touch(oa, now)

    return success(options_approval_view(oa), 200)


# ── PATCH /brokerage/options-approvals/{id} ────────────────────────────────

@bp.patch("/brokerage/options-approvals/<oa_id>")
@require_auth([cfg.ROLE_CUSTOMER])
def patch_options_approval(oa_id: str):
    oa = get_options_approval_or_404(oa_id)
    a = store.accounts.get(oa["account_id"])
    if a is None:
        raise err_invalid_state("orphaned options approval")
    if a["customer_id"] != g.user_id:
        raise err_ownership()

    if a["status"] != cfg.ACCT_STATUS_APPROVED:
        raise err_account_not_approved()
    c = store.customers.get(a["customer_id"])
    if c is None or c["kyc_status"] != cfg.KYC_VERIFIED:
        raise err_kyc_not_verified()

    body = get_json()
    check_version(oa, body)

    if oa["status"] != cfg.OA_REVISION_REQUESTED:
        raise err_invalid_state("patch requires REVISION_REQUESTED")

    new_level = body.get("requested_level")
    if new_level is not None:
        if not isinstance(new_level, int) or isinstance(new_level, bool):
            raise err_validation("requested_level must be int")
        if not (1 <= new_level <= 4):
            raise err_validation("requested_level out of range")

    now = store.now()
    with store.lock:
        if new_level is not None:
            oa["requested_level"] = new_level
        oa["status"] = cfg.OA_SUBMITTED
        oa["revision_count"] = oa["revision_count"] + 1
        touch(oa, now)
    return success(options_approval_view(oa), 200)
