"""Chargeback read endpoints and lifecycle events.

State machine (PRD 3.9): PENDING -> BILLED (manager, line items finalize the
amount); BILLED <-> DISPUTED (resident disputes, manager upholds); BILLED or
DISPUTED -> WAIVED (manager); BILLED -> PAID (resident owner). PAID and WAIVED
are terminal. The resident balance sums final_amount_cents over BILLED and
DISPUTED chargebacks only.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import store, touch
from domain import recompute_resident_balance
from errors import (
    chargeback_lines,
    forbidden,
    invalid_state,
    not_found,
    not_owner,
    validation,
)
from helpers import body, is_int, is_num, is_str, pagination, sorted_page
from middleware import authn, authorize
from response import ok_list, ok_object
from serializers import chargeback_out

bp = Blueprint("chargebacks", __name__)

READ_ROLES = ("Resident", "Dispatcher", "PropertyManager")
MANAGER_EVENTS = ("BILL", "UPHOLD", "WAIVE")
RESIDENT_EVENTS = ("DISPUTE", "PAY")


def _validate_line_items(raw):
    """BILL requires a non-empty array of valid lines (priority 20, HTTP 422).
    Amounts round half-up per line, then the rounded lines are summed."""
    if not isinstance(raw, list) or len(raw) == 0:
        chargeback_lines()
    cleaned = []
    total = 0
    for line in raw:
        if not isinstance(line, dict):
            chargeback_lines()
        description = line.get("description")
        quantity = line.get("quantity")
        unit_cost = line.get("unit_cost_cents")
        share = line.get("resident_share_pct")
        valid = (
            is_str(description)
            and is_int(quantity)
            and quantity >= 1
            and is_int(unit_cost)
            and unit_cost >= 0
            and is_num(share)
            and math.isfinite(float(share))
            and 0 <= share <= 1
        )
        if not valid:
            chargeback_lines()
        amount = int(
            (Decimal(quantity) * Decimal(unit_cost) * Decimal(str(share))).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        total += amount
        cleaned.append(
            {
                "description": description,
                "quantity": quantity,
                "unit_cost_cents": unit_cost,
                "resident_share_pct": share,
            }
        )
    return cleaned, total


@bp.get("/chargebacks")
def list_chargebacks():
    authn_role = authn()[1]
    authorize(authn_role, READ_ROLES)
    limit, offset = pagination()
    items = list(store.chargebacks.values())
    res_filter = request.args.get("resident_id")
    if res_filter is not None:
        items = [c for c in items if c["resident_id"] == res_filter]
    wo_filter = request.args.get("work_order_id")
    if wo_filter is not None:
        items = [c for c in items if c["work_order_id"] == wo_filter]
    page, total = sorted_page(items, limit, offset)
    return ok_list([chargeback_out(c) for c in page], limit, offset, total)


@bp.get("/chargebacks/<cb_id>")
def get_chargeback(cb_id):
    authn_role = authn()[1]
    authorize(authn_role, READ_ROLES)
    cb = store.chargebacks.get(cb_id)
    if cb is None:
        not_found("chargeback")
    return ok_object(chargeback_out(cb))


@bp.post("/chargebacks/<cb_id>/events")
def chargeback_event(cb_id):
    uid, role = authn()
    authorize(role, {"Resident", "PropertyManager"})
    b = body()
    event_type = b.get("event_type")
    # Per-event role gating (RBAC matrix): BILL/UPHOLD/WAIVE are manager-only,
    # DISPUTE/PAY are resident-only.
    if event_type in MANAGER_EVENTS and role != "PropertyManager":
        forbidden()
    if event_type in RESIDENT_EVENTS and role != "Resident":
        forbidden()
    cb = store.chargebacks.get(cb_id)
    if cb is None:
        not_found("chargeback")
    # Ownership (priority 3): residents act only on their own chargebacks.
    if event_type in RESIDENT_EVENTS and cb["resident_id"] != uid:
        not_owner()

    if event_type == "BILL":
        if cb["status"] != "PENDING":
            invalid_state("only a PENDING chargeback can be billed")
        lines, total = _validate_line_items(b.get("line_items"))
        cb["line_items"] = lines
        cb["final_amount_cents"] = total
        cb["status"] = "BILLED"
        touch(cb)
        recompute_resident_balance(cb["resident_id"])
    elif event_type == "DISPUTE":
        if cb["status"] != "BILLED":
            invalid_state("only a BILLED chargeback can be disputed")
        cb["status"] = "DISPUTED"
        cb["dispute_reason"] = b.get("dispute_reason")
        touch(cb)
        # DISPUTED stays in the balance input set: balance unchanged.
    elif event_type == "UPHOLD":
        if cb["status"] != "DISPUTED":
            invalid_state("only a DISPUTED chargeback can be upheld")
        cb["status"] = "BILLED"
        touch(cb)
        # Balance unchanged.
    elif event_type == "WAIVE":
        if cb["status"] not in ("BILLED", "DISPUTED"):
            invalid_state("only a BILLED or DISPUTED chargeback can be waived")
        cb["status"] = "WAIVED"
        touch(cb)
        recompute_resident_balance(cb["resident_id"])
    elif event_type == "PAY":
        if cb["status"] != "BILLED":
            invalid_state("only a BILLED chargeback can be paid")
        cb["status"] = "PAID"
        touch(cb)
        recompute_resident_balance(cb["resident_id"])
    else:
        validation("event_type must be BILL, DISPUTE, UPHOLD, WAIVE, or PAY")
    return ok_object(chargeback_out(cb))
