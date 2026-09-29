"""Credit sales: quoting, pricing, reservation, settlement, assignment and reversal
(PRD 3.8, 3.9)."""
from decimal import Decimal

import auth
import calc
import ledger
import lookup
import serialize
import store
from errors import ApiError
from flask import Blueprint
from response import list_response, object_response
from util import days, dec, now, q2
from validation import (filter_enum, filter_string, json_body, pagination, paginate,
                        v_decimal, v_enum, v_huc8, v_int, v_string)

bp = Blueprint("sales", __name__)

SALE_STATUSES = ("QUOTED", "RESERVED", "EXECUTED", "ASSIGNED", "CANCELLED", "EXPIRED")
CANCEL_REASONS = ("BUYER_WITHDREW", "SPONSOR_WITHDREW", "BANK_POSTURE_RESTRICTED",
                  "HOLD_EXPIRED", "IRT_REVERSAL")
POSTURE_ERRORS = {"FROZEN": "ERR_BANK_SALES_FROZEN",
                  "RESTRICTED": "ERR_BANK_SALES_RESTRICTED",
                  "SOLD_OUT": "ERR_BANK_SOLD_OUT"}


def _sale_state_invalid(message):
    return ApiError("ERR_SALE_STATE_INVALID", message)


def posture_gate(bank, allowed):
    """PRD 2.8: the rejection code is keyed to the offending posture, not the operation."""
    posture = ledger.sales_posture(bank)
    if posture in allowed:
        return posture
    raise ApiError(POSTURE_ERRORS[posture],
                   "The bank's sales posture is %s and does not admit this operation."
                   % posture)


def _sale_owner_checks(actor, sale, bank):
    auth.require_bank_sponsor(actor, bank)
    auth.require_sale_permittee(actor, sale["permittee_id"])


def _executed_price(sale, bank):
    fresh = calc.credit_sale_price(bank["hgm_class"], sale["credits_requested"],
                                   sale["service_area_tier"],
                                   ledger.stewardship_underfunded(bank),
                                   ledger.demand_index(bank["id"]))
    return min(fresh, calc.execution_reprice_cap(sale["quoted_price_cents"]))


# --------------------------------------------------------------------- quoting
@bp.post("/mitigation/credit-sales")
def create_quote():
    actor = auth.authenticate("Sponsor", "Permittee")
    body = json_body()
    bank_id = v_string(body, "bank_id")
    permittee_id = v_string(body, "permittee_id")
    credits = v_decimal(body, "credits_requested", places=2, min_exclusive=0)
    impact_huc8 = v_huc8(body, "impact_huc8_code")
    expected_version = v_int(body, "expected_bank_version", minimum=0)

    bank = lookup.bank(bank_id)
    permittee = lookup.permittee(permittee_id)
    auth.require_bank_sponsor(actor, bank)
    auth.require_sale_permittee(actor, permittee["id"])
    ledger.sweep_expired_holds(bank)

    posture_gate(bank, ("OPEN",))
    if expected_version != bank["version"]:
        raise ApiError("ERR_STALE_BANK_VERSION",
                       "expected_bank_version does not match the bank's current version.")
    if impact_huc8 not in bank["service_area_huc8_codes"]:
        raise ApiError("ERR_OUTSIDE_SERVICE_AREA",
                       "The impact watershed lies outside the bank's service area.")
    tier = "PRIMARY" if impact_huc8 == bank["site_huc8_code"] else "SECONDARY"
    if credits > ledger.unmet_requirement(permittee):
        raise ApiError("ERR_ASSIGNMENT_EXCEEDS_REQUIREMENT",
                       "The requested credits exceed the buyer's outstanding obligation.")
    if credits > ledger.credits_available(bank["id"]):
        raise ApiError("ERR_INSUFFICIENT_CREDITS",
                       "The bank does not have that many credits available.")

    demand_index = ledger.demand_index(bank["id"])
    price = calc.credit_sale_price(bank["hgm_class"], credits, tier,
                                   ledger.stewardship_underfunded(bank), demand_index)
    row = store.new_row({
        "bank_id": bank["id"],
        "permittee_id": permittee["id"],
        "credits_requested": credits,
        "impact_huc8_code": impact_huc8,
        "service_area_tier": tier,
        "status": "QUOTED",
        "quoted_demand_index": demand_index,
        "quoted_price_cents": price,
        "executed_price_cents": None,
        "hold_start_at": None,
        "hold_expires_at": None,
        "executed_at": None,
        "assigned_at": None,
        "assignment_reference": None,
        "cancelled_reason": None,
        "cancelled_at": None,
    })
    store.credit_sales[row["id"]] = row
    store.touch(bank)
    return object_response(serialize.credit_sale(row), 201)


# ----------------------------------------------------------------- reservation
@bp.post("/mitigation/credit-sales/<row_id>/reserve")
def reserve(row_id):
    actor = auth.authenticate("Permittee")
    sale = lookup.credit_sale(row_id)
    bank = lookup.bank(sale["bank_id"])
    auth.require_sale_permittee(actor, sale["permittee_id"])
    ledger.sweep_expired_holds(bank)

    if sale["status"] != "QUOTED":
        raise _sale_state_invalid("Only a QUOTED sale may be reserved.")
    posture_gate(bank, ("OPEN",))
    clock = now()
    hold_start = clock
    hold_end = clock + days(calc.RESERVATION_HOLD_DAYS)
    for other in ledger.permittee_sales(sale["permittee_id"]):
        if other["id"] == sale["id"] or other["status"] != "RESERVED":
            continue
        if other["hold_start_at"] is None or other["hold_expires_at"] is None:
            continue
        if hold_start <= other["hold_expires_at"] and other["hold_start_at"] <= hold_end:
            raise ApiError("ERR_RESERVATION_HOLD_CONFLICT",
                           "The prospective hold overlaps another hold of this permit holder.")
    if sale["credits_requested"] > ledger.credits_available(bank["id"]):
        raise ApiError("ERR_INSUFFICIENT_CREDITS",
                       "The bank does not have that many credits available.")

    sale["status"] = "RESERVED"
    sale["hold_start_at"] = hold_start
    sale["hold_expires_at"] = hold_end
    store.touch(sale)
    ledger.append_entry(bank["id"], "HOLD_PLACED", -dec(sale["credits_requested"]),
                        "CREDIT_SALE", sale["id"],
                        "HOLD PLACED sale=%s credits=%s" % (sale["id"], sale["credits_requested"]))
    store.touch(bank)
    return object_response(serialize.credit_sale(sale))


# ------------------------------------------------------------------ settlement
@bp.post("/mitigation/credit-sales/<row_id>/execute")
def execute(row_id):
    actor = auth.authenticate("Sponsor")
    sale = lookup.credit_sale(row_id)
    bank = lookup.bank(sale["bank_id"])
    auth.require_bank_sponsor(actor, bank)
    ledger.sweep_expired_holds(bank)

    if sale["status"] != "RESERVED":
        raise _sale_state_invalid("Only a RESERVED sale may be settled.")
    posture_gate(bank, ("OPEN", "SOLD_OUT"))
    if sale["hold_expires_at"] is not None and now() > sale["hold_expires_at"]:
        raise _sale_state_invalid("The reservation hold has lapsed.")

    settled = _executed_price(sale, bank)
    permittee = store.permittees.get(sale["permittee_id"])
    escrow = ledger.escrow_balance(permittee) if permittee else 0
    if escrow < settled:
        raise ApiError("ERR_INSUFFICIENT_ESCROW",
                       "The buyer's escrow balance does not cover the settled price.")

    sale["status"] = "EXECUTED"
    sale["executed_price_cents"] = settled
    sale["executed_at"] = now()
    store.touch(sale)
    credits = dec(sale["credits_requested"])
    ledger.append_entry(bank["id"], "HOLD_RELEASED", credits, "CREDIT_SALE", sale["id"],
                        "HOLD RELEASED ON SETTLEMENT sale=%s credits=%s" % (sale["id"], credits))
    ledger.append_entry(bank["id"], "SOLD", -credits, "CREDIT_SALE", sale["id"],
                        "SOLD sale=%s credits=%s price_cents=%d" % (sale["id"], credits, settled))
    store.touch(bank)
    return object_response(serialize.credit_sale(sale))


# ------------------------------------------------------------------ assignment
@bp.post("/mitigation/credit-sales/<row_id>/assign")
def assign(row_id):
    actor = auth.authenticate("Sponsor")
    sale = lookup.credit_sale(row_id)
    bank = lookup.bank(sale["bank_id"])
    auth.require_bank_sponsor(actor, bank)
    ledger.sweep_expired_holds(bank)

    if sale["status"] != "EXECUTED":
        raise _sale_state_invalid("Only a settled sale may be assigned.")
    permittee = store.permittees.get(sale["permittee_id"])
    credits = dec(sale["credits_requested"])
    if permittee is not None and credits > ledger.unmet_requirement(permittee):
        raise ApiError("ERR_ASSIGNMENT_EXCEEDS_REQUIREMENT",
                       "The assignment would exceed the buyer's remaining obligation.")

    sale["status"] = "ASSIGNED"
    sale["assigned_at"] = now()
    sale["assignment_reference"] = "%s/%s/%s" % (
        permittee["permit_number"] if permittee else "",
        bank["site_huc8_code"], q2(credits))
    store.touch(sale)
    ledger.append_entry(bank["id"], "ASSIGNED", Decimal("0.00"), "CREDIT_SALE", sale["id"],
                        "ASSIGNED sale=%s reference=%s" % (sale["id"],
                                                           sale["assignment_reference"]))
    return object_response(serialize.credit_sale(sale))


# ----------------------------------------------------------------- withdrawal
@bp.post("/mitigation/credit-sales/<row_id>/cancel")
def cancel(row_id):
    actor = auth.authenticate("Sponsor", "Permittee")
    body = json_body()
    reason = v_enum(body, "cancelled_reason", CANCEL_REASONS)
    sale = lookup.credit_sale(row_id)
    bank = lookup.bank(sale["bank_id"])
    _sale_owner_checks(actor, sale, bank)
    ledger.sweep_expired_holds(bank)

    if sale["status"] not in ("QUOTED", "RESERVED"):
        raise _sale_state_invalid("Only an uncommitted sale may be withdrawn.")
    was_reserved = sale["status"] == "RESERVED"
    sale["status"] = "CANCELLED"
    sale["cancelled_reason"] = reason
    sale["cancelled_at"] = now()
    store.touch(sale)
    if was_reserved:
        ledger.append_entry(bank["id"], "HOLD_RELEASED", dec(sale["credits_requested"]),
                            "CREDIT_SALE", sale["id"],
                            "HOLD RELEASED reason=%s" % reason)
    return object_response(serialize.credit_sale(sale))


# -------------------------------------------------------------------- reversal
@bp.post("/mitigation/credit-sales/<row_id>/reverse")
def reverse(row_id):
    auth.authenticate("IRTChair")
    sale = lookup.credit_sale(row_id)
    bank = lookup.bank(sale["bank_id"])
    ledger.sweep_expired_holds(bank)

    if sale["status"] != "EXECUTED":
        raise _sale_state_invalid("Only a settled sale may be reversed.")
    sale["status"] = "CANCELLED"
    sale["cancelled_reason"] = "IRT_REVERSAL"
    sale["cancelled_at"] = now()
    store.touch(sale)
    ledger.append_entry(bank["id"], "SALE_REVERSED", dec(sale["credits_requested"]),
                        "CREDIT_SALE", sale["id"],
                        "SALE REVERSED sale=%s credits=%s"
                        % (sale["id"], sale["credits_requested"]))
    permittee = store.permittees.get(sale["permittee_id"])
    store.touch(bank)
    return object_response(serialize.credit_sale(sale))


# ----------------------------------------------------------------------- reads
@bp.get("/mitigation/credit-sales/<row_id>")
def read_sale(row_id):
    auth.authenticate("ProgramAdmin", "Sponsor", "Permittee", "IRTChair")
    return object_response(serialize.credit_sale(lookup.credit_sale(row_id)))


@bp.get("/mitigation/credit-sales")
def list_sales():
    auth.authenticate("ProgramAdmin", "Sponsor", "Permittee", "IRTChair")
    limit, offset = pagination()
    bank_id = filter_string("bank_id")
    permittee_id = filter_string("permittee_id")
    status = filter_enum("status", SALE_STATUSES)
    rows = store.ordered(list(store.credit_sales.values()))
    if bank_id is not None:
        rows = [r for r in rows if r["bank_id"] == bank_id]
    if permittee_id is not None:
        rows = [r for r in rows if r["permittee_id"] == permittee_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.credit_sale(r) for r in page], limit, offset, total)
