"""Fleet accounts, ledger snapshot and GL/expense export (PRD §3.1, §2.7, §3.9)."""
import copy

from flask import Blueprint

import response
from db import base_record, db
from errors import err
from middleware import (body, check_fleet, opt_enum, req_int, req_str, require_roles)
from services import serialize
from services.ledger import hold_amount, ledger
from services.store import (ACCOUNT_STATUSES, DEFAULT_REBATE_TIERS, account_transactions,
                            get_account)
from db import sort_key

bp = Blueprint("fleet_accounts", __name__)


def _parse_rebate_tiers(data):
    if "rebate_tiers" not in data or data["rebate_tiers"] is None:
        return copy.deepcopy(DEFAULT_REBATE_TIERS)
    tiers = data["rebate_tiers"]
    if not isinstance(tiers, list) or not tiers:
        raise err("ERR_VALIDATION", "Field 'rebate_tiers' must be a non-empty array.")
    parsed = []
    for tier in tiers:
        if not isinstance(tier, dict):
            raise err("ERR_VALIDATION", "Each rebate tier must be an object.")
        floor = tier.get("min_month_gallons")
        rate = tier.get("cpg_rebate")
        if isinstance(floor, bool) or not isinstance(floor, int) or floor < 0:
            raise err("ERR_VALIDATION", "Each rebate tier needs an integer 'min_month_gallons' >= 0.")
        if isinstance(rate, bool) or not isinstance(rate, int):
            raise err("ERR_VALIDATION", "Each rebate tier needs an integer 'cpg_rebate'.")
        parsed.append({"min_month_gallons": floor, "cpg_rebate": rate})
    parsed.sort(key=lambda t: t["min_month_gallons"])
    if parsed[0]["min_month_gallons"] != 0:
        raise err("ERR_VALIDATION", "The first rebate tier must have min_month_gallons = 0.")
    return parsed


@bp.post("/fleet-accounts")
@require_roles("ProgramAdmin")
def create_fleet_account():
    data = body()
    record = base_record()
    record.update({
        "company_name": req_str(data, "company_name"),
        "base_jurisdiction": req_str(data, "base_jurisdiction"),
        "credit_limit_cents": req_int(data, "credit_limit_cents", minimum=0),
        "status": opt_enum(data, "status", ACCOUNT_STATUSES, "ACTIVE"),
        "rebate_tiers": _parse_rebate_tiers(data),
    })
    db.fleet_accounts[record["id"]] = record
    return response.created(serialize.fleet_account(record))


@bp.get("/fleet-accounts/<account_id>")
@require_roles("ProgramAdmin", "FleetManager")
def fetch_fleet_account(account_id):
    account = get_account(account_id)
    check_fleet(account["id"])
    return response.ok(serialize.fleet_account(account))


@bp.get("/fleet-accounts/<account_id>/summary")
@require_roles("ProgramAdmin", "FleetManager")
def fleet_account_summary(account_id):
    account = get_account(account_id)
    check_fleet(account["id"])

    snapshot = ledger(account)
    gl_lines = []
    for txn in sorted(account_transactions(account["id"]), key=sort_key):
        if txn["posting_status"] == "SETTLED":
            rebate = txn["final_rebate_cents"]
        elif txn["posting_status"] == "CAPTURED":
            rebate = txn["provisional_rebate_cents"]
        else:
            rebate = 0
        gl_lines.append({
            "transaction_id": txn["id"],
            "card_id": txn["card_id"],
            "vehicle_id": txn["vehicle_id"],
            "driver_id": txn["driver_id"],
            "product": txn["product"],
            "gallons": txn["gallons"],
            "unit_price_cents": txn["unit_price_cents"],
            "jurisdiction": txn["jurisdiction"],
            "gross_amount_cents": txn["gross_amount_cents"],
            "hold_amount_cents": hold_amount(txn),
            "rebate_cents": rebate,
            "posting_status": txn["posting_status"],
            "review_status": txn["review_status"],
            "purchased_at": txn["purchased_at"],
        })

    payload = {
        "available_credit_cents": snapshot["available_credit_cents"],
        "outstanding_holds_cents": snapshot["outstanding_holds_cents"],
        "settled_spend_cents": snapshot["settled_spend_cents"],
        "rebate_accrual_cents": snapshot["rebate_accrual_cents"],
        "gl_lines": gl_lines,
    }
    return response.ok(payload)
