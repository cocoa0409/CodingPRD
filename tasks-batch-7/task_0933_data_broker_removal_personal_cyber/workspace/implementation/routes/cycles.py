"""Billing-cycle closure and the entitlement ledger log (PRD §3.9, §2.10)."""

from flask import Blueprint, request

import cascades
import constants as K
import context
import envelope
import serializers
import states
from context import Ctx
from store import DB, ordered

bp = Blueprint("cycles", __name__)


@bp.post("/billing-cycles/<cycle_id>/close")
def close_cycle(cycle_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN])
    cycle = ctx.path("cycle", cycle_id)
    account = DB.accounts.get(cycle["account_id"])
    # Rung 15 exempt: closure must remain possible for a SUSPENDED account so
    # that billing does not stall.
    ctx.write_gates(account, skip_suspended=True)
    states.gate("cycle_status", cycle["status"], ("OPEN",))
    cascades.close_cycle(cycle, account)
    return envelope.ok(serializers.cycle(cycle))


# --- the entitlement ledger -------------------------------------------------

LEDGER_ROLES = [K.ROLE_PLATFORM_ADMIN, K.ROLE_ACCOUNT_OWNER, K.ROLE_AUDITOR]


@bp.get("/entitlement-ledger")
def list_ledger():
    ctx = Ctx(request, LEDGER_ROLES)
    resource_type = context.enum_filter(request, "resource_type", K.LEDGER_RESOURCE_TYPES)
    entry_type = context.enum_filter(request, "entry_type", K.LEDGER_ENTRY_TYPES)
    limit, offset = context.pagination(request)
    account_id = context.plain_filter(request, "account_id")
    member_id = context.plain_filter(request, "member_id")
    cycle_id_filter = context.plain_filter(request, "cycle_id")
    result = []
    for entry in DB.ledger.values():
        if account_id is not None and entry["account_id"] != account_id:
            continue
        if member_id is not None and entry["member_id"] != member_id:
            continue
        if cycle_id_filter is not None and entry["cycle_id"] != cycle_id_filter:
            continue
        if resource_type is not None and entry["resource_type"] != resource_type:
            continue
        if entry_type is not None and entry["entry_type"] != entry_type:
            continue
        if ctx.is_scoped_caller and entry["account_id"] != ctx.caller_member["account_id"]:
            continue
        result.append(entry)
    page, total = context.window(ordered(result), limit, offset)
    return envelope.listing(
        [serializers.ledger_entry(e) for e in page], limit, offset, total
    )


@bp.get("/entitlement-ledger/<entry_id>")
def read_ledger_entry(entry_id):
    ctx = Ctx(request, LEDGER_ROLES)
    entry = ctx.path("ledger_entry", entry_id)
    ctx.own(entry["account_id"])  # account-level read
    return envelope.ok(serializers.ledger_entry(entry))
