"""Settlement lifecycle: read/list, finalize, pay, void (PRD §3.8)."""

from flask import Blueprint, request

import db
import serialize
import utils
from errors import (ApiError, ERR_FINALIZE_ITEMS_PENDING, ERR_INVALID_STATE,
                    ERR_SETTLEMENT_NOT_FINALIZED, ERR_SETTLEMENT_NOT_FOUND)
from middleware import require_roles, check_owns_account
from response import ok_object, paginate, sort_created
from services import calculations as calc
from services import workflow

bp = Blueprint("settlements", __name__)


def get_settlement_or_404(settlement_id):
    settlement = db.settlements.get(settlement_id)
    if settlement is None:
        raise ApiError(ERR_SETTLEMENT_NOT_FOUND, 404, "no Settlement with the given id")
    return settlement


def settlement_account_id(settlement):
    manifest = db.manifests.get(settlement["manifest_id"])
    return manifest["account_id"] if manifest else None


@bp.get("/itad/settlements/<settlement_id>")
def read_settlement(settlement_id):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "IntakeOperator")
    settlement = get_settlement_or_404(settlement_id)
    check_owns_account(uid, role, settlement_account_id(settlement))
    return ok_object(serialize.settlement(settlement))


@bp.get("/itad/settlements")
def list_settlements():
    uid, role = require_roles("PlatformAdmin", "AccountManager", "IntakeOperator")
    records = list(db.settlements.values())
    if role == "AccountManager":
        records = [s for s in records if settlement_account_id(s) == uid]
    supersedes = request.args.get("supersedes_settlement_id")
    if supersedes is not None:
        records = [s for s in records if s.get("supersedes_settlement_id") == supersedes]
    records = sort_created(records)
    return paginate([serialize.settlement(s) for s in records])


@bp.post("/itad/settlements/<settlement_id>/finalize")
def finalize_settlement(settlement_id):
    uid, role = require_roles("PlatformAdmin")
    settlement = get_settlement_or_404(settlement_id)
    if settlement["kind"] != "QUOTE" or settlement["status"] != "QUOTE_OPEN":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a QUOTE_OPEN settlement can be finalized")
    manifest = db.manifests[settlement["manifest_id"]]
    if manifest["status"] != "RECONCILED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "the owning manifest must be RECONCILED")
    items = workflow.manifest_items(manifest["id"])
    if any(i["processing_status"] not in ("SOLD", "COMPLETE") for i in items):
        raise ApiError(ERR_FINALIZE_ITEMS_PENDING, 422,
                       "every manifest item must be SOLD or COMPLETE")

    account = db.accounts[manifest["account_id"]]

    # SOLD items complete first; FINAL totals compute afterwards (PRD §3.8).
    for item in items:
        if item["processing_status"] == "SOLD":
            workflow.complete_item(item, account)
            utils.touch(item)

    settlement["kind"] = "FINAL"
    settlement["status"] = "FINALIZED"
    figures = calc.compute_settlement_figures(manifest, items, "FINAL")
    settlement.update(figures)
    utils.touch(settlement)

    gross = figures["gross_buyback_cents"]
    fees = figures["total_fees_cents"]
    rebate = figures["volume_rebate_cents"]
    if gross != 0:
        workflow.post_ledger(account, settlement["id"], "BUYBACK_CREDIT", gross)
    if fees != 0:
        workflow.post_ledger(account, settlement["id"], "FEE_DEBIT", -fees)
    if rebate != 0:
        workflow.post_ledger(account, settlement["id"], "BONUS_CREDIT", rebate)
    utils.touch(account)
    return ok_object(serialize.settlement(settlement))


@bp.post("/itad/settlements/<settlement_id>/pay")
def pay_settlement(settlement_id):
    uid, role = require_roles("PlatformAdmin")
    settlement = get_settlement_or_404(settlement_id)
    if settlement["status"] != "FINALIZED":
        raise ApiError(ERR_SETTLEMENT_NOT_FINALIZED, 409,
                       "only FINALIZED settlements can be paid")
    manifest = db.manifests[settlement["manifest_id"]]
    account = db.accounts[manifest["account_id"]]
    workflow.post_ledger(account, settlement["id"], "PAYOUT_DEBIT",
                         -settlement["net_amount_cents"])
    settlement["status"] = "PAID"
    utils.touch(settlement)
    utils.touch(account)
    return ok_object(serialize.settlement(settlement))


@bp.post("/itad/settlements/<settlement_id>/void")
def void_settlement(settlement_id):
    uid, role = require_roles("PlatformAdmin")
    settlement = get_settlement_or_404(settlement_id)
    if settlement["status"] != "FINALIZED":
        raise ApiError(ERR_SETTLEMENT_NOT_FINALIZED, 409,
                       "only FINALIZED settlements can be voided")
    manifest = db.manifests[settlement["manifest_id"]]
    account = db.accounts[manifest["account_id"]]
    finalize_entries = sort_created([
        e for e in db.ledger_entries.values()
        if e["settlement_id"] == settlement["id"]
        and e["entry_type"] in ("BUYBACK_CREDIT", "FEE_DEBIT", "BONUS_CREDIT")
    ])
    for entry in finalize_entries:
        workflow.post_ledger(account, settlement["id"], "REVERSAL",
                             -entry["amount_cents"])
    settlement["status"] = "VOIDED"
    utils.touch(settlement)
    utils.touch(account)
    return ok_object(serialize.settlement(settlement))


@bp.get("/itad/settlements/<settlement_id>/ledger-entries")
def list_settlement_ledger(settlement_id):
    uid, role = require_roles("PlatformAdmin", "AccountManager")
    settlement = get_settlement_or_404(settlement_id)
    check_owns_account(uid, role, settlement_account_id(settlement))
    records = sort_created([e for e in db.ledger_entries.values()
                            if e["settlement_id"] == settlement["id"]])
    return paginate([serialize.ledger_entry(e) for e in records])
