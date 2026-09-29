"""Co-brand issuers, mile sale agreements and mile purchase orders
(PRD 3.1, 3.2 and 3.3)."""

from flask import Blueprint

import calc
import validators as v
from db import store
from errors import fail
from middleware import authenticate, body, page_params, qfilter
from response import created, ok, ok_list
from services.core import (base_row, dump, dump_all, find, finish_row, fk, ordered,
                           paginate, pdate, program_add_deferred,
                           recompute_issuer_aggregate, today, touch)

bp = Blueprint("issuers", __name__)

ISSUER_READ_ROLES = ("ProgramAdmin", "PartnerManager", "ContractsOfficer",
                     "RevenueAccountant", "IssuerRepresentative")
AGREEMENT_ALIVE = ("DRAFT", "ISSUER_REVIEW", "COUNTERED", "RATIFIED", "ACTIVE")
AGREEMENT_STATUSES = ("DRAFT", "ISSUER_REVIEW", "COUNTERED", "RATIFIED", "ACTIVE",
                      "EXPIRED", "TERMINATED")
FULFILLMENT_STATUSES = ("PENDING", "ISSUED", "REVERSED")
SETTLEMENT_STATUSES = ("PENDING", "INVOICED", "SETTLED", "WRITTEN_OFF")


def _program_of_issuer(issuer):
    return store.programs[issuer["program_id"]]


def _issuer_of_agreement(agreement):
    return store.issuers[agreement["issuer_id"]]


def _scope_issuer(caller, issuer_id):
    if caller.is_issuer_rep and issuer_id != caller.user_id:
        fail("ERR_ISSUER_SCOPE_VIOLATION", "issuer may read only its own records")


# --------------------------------------------------------------------------
# /co-brand-issuers
# --------------------------------------------------------------------------


@bp.post("/co-brand-issuers")
def create_issuer():
    authenticate(("ProgramAdmin", "PartnerManager"))
    data = body()
    program = fk(store.programs, data, "program_id", "ERR_PROGRAM_NOT_FOUND", required=True)
    name = v.req_str(data, "name")
    cap = v.req_int(data, "annual_mile_purchase_cap_miles", minimum=1)

    row = base_row()
    row["program_id"] = program["id"]
    row["name"] = name
    row["annual_mile_purchase_cap_miles"] = cap
    row["aggregate_committed_miles"] = 0
    row["status"] = "ACTIVE"
    row["suspension_reason"] = "NONE"
    finish_row(row)
    store.issuers[row["id"]] = row
    return created(dump(row))


@bp.get("/co-brand-issuers")
def list_issuers():
    caller = authenticate(ISSUER_READ_ROLES)
    limit, offset = page_params()
    rows = ordered(store.issuers)
    program_id = qfilter("program_id")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    status = qfilter("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if caller.is_issuer_rep:
        rows = [r for r in rows if r["id"] == caller.user_id]
    page, total = paginate(rows, limit, offset)
    return ok_list(dump_all(page), limit, offset, total)


@bp.get("/co-brand-issuers/<issuer_id>")
def read_issuer(issuer_id):
    caller = authenticate(ISSUER_READ_ROLES)
    issuer = find(store.issuers, issuer_id, "ERR_ISSUER_NOT_FOUND")
    _scope_issuer(caller, issuer["id"])
    return ok(dump(issuer))


# --------------------------------------------------------------------------
# /mile-sale-agreements
# --------------------------------------------------------------------------


@bp.post("/mile-sale-agreements")
def create_agreement():
    caller = authenticate(("PartnerManager",))
    data = body()
    issuer = fk(store.issuers, data, "issuer_id", "ERR_ISSUER_NOT_FOUND", required=True)
    target = fk(store.agreements, data, "supersedes_agreement_id",
                "ERR_AGREEMENT_NOT_FOUND")

    start_text = v.req_str(data, "term_start_date")
    start = v.parse_date(start_text, "term_start_date")
    end_text = v.req_str(data, "term_end_date")
    end = v.parse_date(end_text, "term_end_date")
    volume = v.req_int(data, "committed_volume_miles", minimum=1)
    schedule = v.req_tier_schedule(data)

    # Rung 14
    if start > end:
        fail("ERR_INVALID_INTERVAL", "term_start_date must not be after term_end_date")

    # Rung 17
    if (end - start).days < 90 or start < today():
        fail("ERR_INVALID_TERM",
             "the term must be at least 90 whole days and may not start in the past")

    # Rung 21
    for other in store.agreements.values():
        if other["issuer_id"] != issuer["id"]:
            continue
        if other["status"] not in AGREEMENT_ALIVE:
            continue
        if target is not None and other["id"] == target["id"]:
            continue
        if start <= pdate(other["term_end_date"]) and pdate(other["term_start_date"]) <= end:
            fail("ERR_AGREEMENT_TERM_OVERLAP",
                 "the term overlaps a live agreement of the same issuer")

    # Rung 22
    if target is not None:
        if target["issuer_id"] != issuer["id"] or target["status"] not in ("RATIFIED", "ACTIVE"):
            fail("ERR_SUPERSEDE_TARGET_INVALID",
                 "supersedes_agreement_id must name a RATIFIED or ACTIVE agreement of the same issuer")
        for other in store.agreements.values():
            if other.get("supersedes_agreement_id") == target["id"]:
                fail("ERR_SUPERSEDE_TARGET_INVALID",
                     "that agreement is already superseded")

    row = base_row()
    row["issuer_id"] = issuer["id"]
    row["supersedes_agreement_id"] = target["id"] if target else None
    row["term_start_date"] = start_text
    row["term_end_date"] = end_text
    row["committed_volume_miles"] = volume
    row["tier_schedule"] = schedule
    row["status"] = "DRAFT"
    row["negotiation_round"] = 1
    row["countered_price_per_mile_centicents"] = None
    row["countered_committed_volume_miles"] = None
    row["drawn_miles"] = 0
    row["prepayment_balance_miles"] = 0
    row["negotiated_by_user_id"] = caller.user_id
    row["ratified_by_user_id"] = None
    finish_row(row)
    store.agreements[row["id"]] = row
    return created(dump(row))


@bp.get("/mile-sale-agreements")
def list_agreements():
    caller = authenticate(ISSUER_READ_ROLES)
    limit, offset = page_params()
    rows = ordered(store.agreements)
    issuer_id = qfilter("issuer_id")
    if issuer_id is not None:
        rows = [r for r in rows if r["issuer_id"] == issuer_id]
    supersedes = qfilter("supersedes_agreement_id")
    if supersedes is not None:
        rows = [r for r in rows if r["supersedes_agreement_id"] == supersedes]
    status = qfilter("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if caller.is_issuer_rep:
        rows = [r for r in rows if r["issuer_id"] == caller.user_id]
    page, total = paginate(rows, limit, offset)
    return ok_list(dump_all(page), limit, offset, total)


@bp.get("/mile-sale-agreements/<agreement_id>")
def read_agreement(agreement_id):
    caller = authenticate(ISSUER_READ_ROLES)
    agreement = find(store.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    _scope_issuer(caller, agreement["issuer_id"])
    return ok(dump(agreement))


@bp.post("/mile-sale-agreements/<agreement_id>/submit")
def submit_agreement(agreement_id):
    caller = authenticate(("PartnerManager",))
    agreement = find(store.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    if agreement["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT agreement may be submitted")
    issuer = _issuer_of_agreement(agreement)
    if issuer["status"] != "ACTIVE":
        fail("ERR_ISSUER_SUSPENDED", "the issuer is suspended")
    agreement["status"] = "ISSUER_REVIEW"
    agreement["negotiated_by_user_id"] = caller.user_id
    touch(agreement)
    return ok(dump(agreement))


@bp.post("/mile-sale-agreements/<agreement_id>/counter")
def counter_agreement(agreement_id):
    caller = authenticate(("IssuerRepresentative",))
    agreement = find(store.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    _scope_issuer(caller, agreement["issuer_id"])
    data = body()
    price = v.req_int(data, "counter_price_per_mile_centicents", minimum=0)
    volume = v.req_int(data, "counter_committed_volume_miles", minimum=0)
    v.opt_str(data, "note", allow_empty=True)
    if agreement["status"] != "ISSUER_REVIEW":
        fail("ERR_INVALID_STATE", "only an agreement under issuer review may be countered")
    agreement["status"] = "COUNTERED"
    agreement["countered_price_per_mile_centicents"] = price
    agreement["countered_committed_volume_miles"] = volume
    touch(agreement)
    return ok(dump(agreement))


@bp.post("/mile-sale-agreements/<agreement_id>/revise")
def revise_agreement(agreement_id):
    caller = authenticate(("PartnerManager",))
    agreement = find(store.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    data = body()
    volume = v.req_int(data, "committed_volume_miles", minimum=1)
    schedule = v.req_tier_schedule(data)
    if agreement["status"] != "COUNTERED":
        fail("ERR_INVALID_STATE", "only a COUNTERED agreement may be revised")
    agreement["status"] = "DRAFT"
    agreement["committed_volume_miles"] = volume
    agreement["tier_schedule"] = schedule
    agreement["negotiation_round"] += 1
    agreement["negotiated_by_user_id"] = caller.user_id
    touch(agreement)
    return ok(dump(agreement))


@bp.post("/mile-sale-agreements/<agreement_id>/ratify")
def ratify_agreement(agreement_id):
    caller = authenticate(("ContractsOfficer",))
    agreement = find(store.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    if agreement["status"] != "ISSUER_REVIEW":
        fail("ERR_INVALID_STATE", "only an agreement under issuer review may be ratified")
    # Rung 10
    if caller.user_id == agreement.get("negotiated_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the negotiator of an agreement may not ratify it")

    issuer = _issuer_of_agreement(agreement)
    target = None
    if agreement["supersedes_agreement_id"]:
        target = store.agreements.get(agreement["supersedes_agreement_id"])

    # Rung 34 -- aggregate net of the agreement this one supersedes
    net_aggregate = issuer["aggregate_committed_miles"]
    if target is not None and target["status"] in ("RATIFIED", "ACTIVE"):
        net_aggregate -= target["committed_volume_miles"]
    if net_aggregate + agreement["committed_volume_miles"] > issuer["annual_mile_purchase_cap_miles"]:
        fail("ERR_ISSUER_CAP_EXCEEDED",
             "ratification would exceed the issuer's annual mile purchase cap")

    agreement["status"] = "RATIFIED"
    agreement["ratified_by_user_id"] = caller.user_id
    touch(agreement)

    # Hop 1 + hop 2 -- terminate the superseded agreement and sweep its prepayment
    if target is not None and target["status"] in ("RATIFIED", "ACTIVE"):
        target["status"] = "TERMINATED"
        swept = target["prepayment_balance_miles"]
        target["prepayment_balance_miles"] = 0
        touch(target)
        if swept:
            agreement["prepayment_balance_miles"] += swept

    # Hop 2 (cont.) -- recompute the issuer aggregate
    aggregate = recompute_issuer_aggregate(issuer)

    # Hop 3 -- utilisation alarm at 90% of the cap, inclusive
    threshold = calc.issuer_alert_threshold(issuer["annual_mile_purchase_cap_miles"])
    if aggregate >= threshold and issuer["status"] != "SUSPENDED":
        issuer["status"] = "SUSPENDED"
        issuer["suspension_reason"] = "CAP_BREACH"
        touch(issuer)

    return ok(dump(agreement))


@bp.post("/mile-sale-agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    authenticate(("ContractsOfficer",))
    agreement = find(store.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    if agreement["status"] != "RATIFIED":
        fail("ERR_INVALID_STATE", "only a RATIFIED agreement may be activated")
    issuer = _issuer_of_agreement(agreement)
    if issuer["status"] != "ACTIVE":
        fail("ERR_ISSUER_SUSPENDED", "the issuer is suspended")
    agreement["status"] = "ACTIVE"
    touch(agreement)
    recompute_issuer_aggregate(issuer)
    return ok(dump(agreement))


# --------------------------------------------------------------------------
# /mile-purchase-orders
# --------------------------------------------------------------------------


@bp.post("/mile-purchase-orders")
def create_order():
    authenticate(("PartnerManager",))
    data = body()
    agreement = fk(store.agreements, data, "agreement_id",
                   "ERR_AGREEMENT_NOT_FOUND", required=True)
    order_miles = v.req_int(data, "order_miles", minimum=1)
    expected = v.req_int(data, "expected_agreement_version")

    # Rung 8
    if agreement["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "miles may be drawn only against an ACTIVE agreement")
    # Rung 9
    if expected != agreement["version"]:
        fail("ERR_STALE_VERSION", "expected_agreement_version does not match the agreement")
    # Rung 32
    ceiling = calc.volume_ceiling(agreement["committed_volume_miles"])
    if agreement["drawn_miles"] + order_miles > ceiling:
        fail("ERR_VOLUME_COMMITMENT_EXCEEDED",
             "the cumulative draw exceeds 110% of the committed volume")
    # Rung 33
    issuer = _issuer_of_agreement(agreement)
    if issuer["status"] != "ACTIVE":
        fail("ERR_ISSUER_SUSPENDED", "the issuer is suspended")

    drawn_before = agreement["drawn_miles"]
    price, gross = calc.provisional_pricing(
        agreement["tier_schedule"], drawn_before, order_miles)

    row = base_row()
    row["agreement_id"] = agreement["id"]
    row["order_miles"] = order_miles
    row["drawn_miles_before"] = drawn_before
    row["provisional_tier_price_centicents"] = price
    row["gross_amount_cents"] = gross
    row["final_amount_cents"] = None
    row["volume_true_up_cents"] = 0
    row["net_amount_cents"] = None
    row["fulfillment_status"] = "PENDING"
    row["settlement_status"] = "PENDING"
    row["posted_period"] = None
    row["reversal_reason"] = None
    finish_row(row)
    store.orders[row["id"]] = row

    touch(agreement)
    return created(dump(row))


@bp.get("/mile-purchase-orders")
def list_orders():
    caller = authenticate(ISSUER_READ_ROLES)
    limit, offset = page_params()
    rows = ordered(store.orders)
    agreement_id = qfilter("agreement_id")
    if agreement_id is not None:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    fulfillment = qfilter("fulfillment_status")
    if fulfillment is not None:
        rows = [r for r in rows if r["fulfillment_status"] == fulfillment]
    settlement = qfilter("settlement_status")
    if settlement is not None:
        rows = [r for r in rows if r["settlement_status"] == settlement]
    if caller.is_issuer_rep:
        rows = [r for r in rows
                if store.agreements[r["agreement_id"]]["issuer_id"] == caller.user_id]
    page, total = paginate(rows, limit, offset)
    return ok_list(dump_all(page), limit, offset, total)


@bp.get("/mile-purchase-orders/<order_id>")
def read_order(order_id):
    caller = authenticate(ISSUER_READ_ROLES)
    order = find(store.orders, order_id, "ERR_ORDER_NOT_FOUND")
    _scope_issuer(caller, store.agreements[order["agreement_id"]]["issuer_id"])
    return ok(dump(order))


@bp.post("/mile-purchase-orders/<order_id>/issue")
def issue_order(order_id):
    authenticate(("PartnerManager",))
    order = find(store.orders, order_id, "ERR_ORDER_NOT_FOUND")
    agreement = store.agreements[order["agreement_id"]]
    if order["fulfillment_status"] != "PENDING" or agreement["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE",
             "only a PENDING order on an ACTIVE agreement may be issued")
    order["fulfillment_status"] = "ISSUED"
    touch(order)
    agreement["drawn_miles"] += order["order_miles"]
    agreement["prepayment_balance_miles"] += order["order_miles"]
    touch(agreement)
    program = _program_of_issuer(_issuer_of_agreement(agreement))
    program_add_deferred(program, order["gross_amount_cents"])
    return ok(dump(order))


@bp.post("/mile-purchase-orders/<order_id>/invoice")
def invoice_order(order_id):
    authenticate(("RevenueAccountant",))
    order = find(store.orders, order_id, "ERR_ORDER_NOT_FOUND")
    agreement = store.agreements[order["agreement_id"]]
    if order["settlement_status"] != "PENDING" or order["fulfillment_status"] != "ISSUED":
        fail("ERR_INVALID_STATE",
             "only an ISSUED order awaiting settlement may be invoiced")
    program = _program_of_issuer(_issuer_of_agreement(agreement))
    if program["revenue_recognition_state"] == "LOCKED":
        fail("ERR_PERIOD_LOCKED", "the accounting period is locked")

    final = calc.final_pricing(agreement["tier_schedule"],
                               order["drawn_miles_before"], order["order_miles"])
    true_up = final - order["gross_amount_cents"]
    order["final_amount_cents"] = final
    order["volume_true_up_cents"] = true_up
    order["net_amount_cents"] = final
    order["settlement_status"] = "INVOICED"
    order["posted_period"] = program["current_period"]
    touch(order)
    program_add_deferred(program, true_up)
    return ok(dump(order))


@bp.post("/mile-purchase-orders/<order_id>/settle")
def settle_order(order_id):
    authenticate(("RevenueAccountant",))
    order = find(store.orders, order_id, "ERR_ORDER_NOT_FOUND")
    if order["settlement_status"] != "INVOICED":
        fail("ERR_INVALID_STATE", "only an INVOICED order may be settled")
    order["settlement_status"] = "SETTLED"
    touch(order)
    return ok(dump(order))


@bp.post("/mile-purchase-orders/<order_id>/reverse")
def reverse_order(order_id):
    authenticate(("PartnerManager",))
    order = find(store.orders, order_id, "ERR_ORDER_NOT_FOUND")
    agreement = store.agreements[order["agreement_id"]]
    data = body()
    reason = v.req_str(data, "reason")
    if (order["fulfillment_status"] != "ISSUED"
            or order["settlement_status"] == "SETTLED"
            or agreement["prepayment_balance_miles"] < order["order_miles"]):
        fail("ERR_INVALID_STATE",
             "only an issued, unsettled order still backed by prepayment may be reversed")

    was_invoiced = order["settlement_status"] == "INVOICED"
    debit = order["net_amount_cents"] if was_invoiced else order["gross_amount_cents"]

    order["fulfillment_status"] = "REVERSED"
    order["settlement_status"] = "WRITTEN_OFF"
    order["reversal_reason"] = reason
    touch(order)

    agreement["drawn_miles"] -= order["order_miles"]
    agreement["prepayment_balance_miles"] -= order["order_miles"]
    touch(agreement)

    program = _program_of_issuer(_issuer_of_agreement(agreement))
    program_add_deferred(program, -(debit or 0))
    return ok(dump(order))
