"""SettlementBatch advance (DISPATCH/SETTLE), reconcile, reads, GL postings."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch
from errors import (
    raise_err,
    ERR_BATCH_NOT_OPEN,
    ERR_NOT_FOUND,
    ERR_RECONCILIATION_MISMATCH,
    ERR_SOD_VIOLATION,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.domain import dispatch_batch, settle_batch
from util import get_json_body, require_enum, parse_pagination, paginate, sort_by_created_at

bp = Blueprint("batches", __name__)

ACTIONS = {"DISPATCH", "SETTLE"}


def get_batch_or_404(batch_id: str) -> dict:
    b = db.settlement_batches.get(batch_id)
    if b is None:
        raise_err(ERR_NOT_FOUND, "SettlementBatch not found")
    return b


@bp.route("/ach/settlement-batches/<batch_id>/advance", methods=["POST"])
@require_roles("OdfiOperations")
def advance_batch(batch_id: str, _user_id: str, _role: str):
    batch = get_batch_or_404(batch_id)
    body = get_json_body()
    action = require_enum(body, "action", ACTIONS)
    # State (p6)
    if action == "DISPATCH":
        if batch["status"] != "OPEN":
            raise_err(ERR_BATCH_NOT_OPEN, "DISPATCH requires an OPEN batch")
        dispatch_batch(batch, _user_id)
    else:
        if batch["status"] != "DISPATCHED":
            raise_err(ERR_BATCH_NOT_OPEN, "SETTLE requires a DISPATCHED batch")
        settle_batch(batch)
    return success_object(batch)


@bp.route("/ach/settlement-batches/<batch_id>/reconcile", methods=["POST"])
@require_roles("OdfiFinance")
def reconcile_batch(batch_id: str, _user_id: str, _role: str):
    batch = get_batch_or_404(batch_id)
    # State (p6)
    if batch["status"] != "SETTLED":
        raise_err(ERR_BATCH_NOT_OPEN, "Reconcile requires a SETTLED batch")
    # SoD (p8): reconciler must differ from the recorded dispatcher.
    if batch["dispatched_by_user_id"] == _user_id:
        raise_err(ERR_SOD_VIOLATION, "Reconciler must differ from the dispatcher")
    # Fiscal (p11): zero-variance requirement. The variance is computed (and
    # persisted) on every reconcile attempt.
    batch["recon_variance_cents"] = (batch["posted_net_cents"] or 0) - (
        batch["expected_net_cents"] or 0
    )
    if batch["recon_variance_cents"] != 0:
        touch(batch)
        raise_err(
            ERR_RECONCILIATION_MISMATCH,
            "posted_net_cents != expected_net_cents",
        )
    batch["status"] = "RECONCILED"
    batch["reconciled_by_user_id"] = _user_id
    touch(batch)
    return success_object(batch)


@bp.route("/ach/settlement-batches/<batch_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_batch(batch_id: str, _user_id: str, _role: str):
    return success_object(get_batch_or_404(batch_id))


@bp.route("/ach/settlement-batches/<batch_id>/gl-postings", methods=["GET"])
@require_roles("OdfiOperations", "OdfiFinance", "OdfiRiskOfficer", "OdfiUnderwriter")
def list_gl_postings(batch_id: str, _user_id: str, _role: str):
    get_batch_or_404(batch_id)
    limit, offset = parse_pagination()
    items = sort_by_created_at(
        [r for r in db.gl_postings.values() if r["settlement_batch_id"] == batch_id]
    )
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)
