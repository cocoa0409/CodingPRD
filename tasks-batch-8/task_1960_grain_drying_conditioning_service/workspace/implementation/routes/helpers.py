"""Shared existence lookups (priority 4: each unresolvable reference yields
its own 404) and grower ownership resolution."""

from db import store
from errors import raise_err
from middleware import forbid_unless_owner


def get_customer(cid):
    c = store.customers.get(cid)
    if c is None:
        raise_err("ERR_CUSTOMER_NOT_FOUND", "Referenced customer does not exist")
    return c


def get_lot(lid):
    lot = store.lots.get(lid)
    if lot is None:
        raise_err("ERR_LOT_NOT_FOUND", "Referenced grain lot does not exist")
    return lot


def get_test(tid):
    t = store.tests.get(tid)
    if t is None:
        raise_err("ERR_TEST_NOT_FOUND", "Referenced moisture test does not exist")
    return t


def get_schedule(sid):
    s = store.schedules.get(sid)
    if s is None:
        raise_err("ERR_SCHEDULE_NOT_FOUND", "Referenced charge schedule does not exist")
    return s


def get_unit(uid):
    u = store.units.get(uid)
    if u is None:
        raise_err("ERR_UNIT_NOT_FOUND", "Referenced dryer unit does not exist")
    return u


def get_ticket(tid):
    t = store.tickets.get(tid)
    if t is None:
        raise_err("ERR_TICKET_NOT_FOUND", "Referenced queue ticket does not exist")
    return t


def get_run(rid):
    r = store.runs.get(rid)
    if r is None:
        raise_err("ERR_RUN_NOT_FOUND", "Referenced dryer run does not exist")
    return r


def get_blend(bid):
    b = store.blends.get(bid)
    if b is None:
        raise_err("ERR_BLEND_NOT_FOUND", "Referenced blend order does not exist")
    return b


def get_claim(cid):
    c = store.claims.get(cid)
    if c is None:
        raise_err("ERR_CLAIM_NOT_FOUND", "Referenced damage claim does not exist")
    return c


def get_agreement(aid):
    a = store.agreements.get(aid)
    if a is None:
        raise_err("ERR_AGREEMENT_NOT_FOUND", "Referenced storage agreement does not exist")
    return a


def get_invoice(iid):
    inv = store.invoices.get(iid)
    if inv is None:
        raise_err("ERR_INVOICE_NOT_FOUND", "Referenced invoice does not exist")
    return inv


def get_payment(pid):
    p = store.payments.get(pid)
    if p is None:
        raise_err("ERR_PAYMENT_NOT_FOUND", "Referenced payment does not exist")
    return p


# ------------------------------------------------------- ownership shortcuts

def lot_customer_id(lot):
    return lot["customer_id"]


def check_grower_on_lot(ctx, lot):
    forbid_unless_owner(ctx, lot["customer_id"])


def check_grower_on_ticket(ctx, ticket):
    lot = store.lots.get(ticket["lot_id"])
    if lot is not None:
        forbid_unless_owner(ctx, lot["customer_id"])


def check_grower_on_run(ctx, run):
    lot = store.lots.get(run["lot_id"])
    if lot is not None:
        forbid_unless_owner(ctx, lot["customer_id"])


def check_grower_on_test(ctx, test):
    lot = store.lots.get(test["lot_id"])
    if lot is not None:
        forbid_unless_owner(ctx, lot["customer_id"])


def check_grower_on_blend(ctx, order):
    lot = store.lots.get(order["high_moisture_lot_id"])
    if lot is not None:
        forbid_unless_owner(ctx, lot["customer_id"])


def check_grower_on_claim(ctx, claim):
    lot = store.lots.get(claim["lot_id"])
    if lot is not None:
        forbid_unless_owner(ctx, lot["customer_id"])


def check_grower_on_agreement(ctx, agreement):
    forbid_unless_owner(ctx, agreement["owner_id"])


def check_grower_on_invoice(ctx, invoice):
    forbid_unless_owner(ctx, invoice["customer_id"])


def check_grower_on_payment(ctx, payment):
    inv = store.invoices.get(payment["invoice_id"])
    if inv is not None:
        forbid_unless_owner(ctx, inv["customer_id"])


# ------------------------------------------------------------ list scoping

def scope_lots_for_grower(ctx, lots):
    if ctx["role"] == "Grower":
        return [l for l in lots if l["customer_id"] == ctx["user_id"]]
    return lots


def scope_by_lot_for_grower(ctx, records, lot_key):
    if ctx["role"] != "Grower":
        return records
    out = []
    for r in records:
        lot = store.lots.get(r[lot_key])
        if lot is not None and lot["customer_id"] == ctx["user_id"]:
            out.append(r)
    return out
