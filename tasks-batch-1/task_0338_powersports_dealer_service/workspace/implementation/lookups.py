"""Existence lookups that raise the correct not-found error (PRD 2.7)."""

import errors
from db import db


def get_customer(cid):
    r = db.customers.get(cid)
    if r is None:
        errors.err(errors.ERR_CUSTOMER_NOT_FOUND)
    return r


def get_unit(uid):
    r = db.units.get(uid)
    if r is None:
        errors.err(errors.ERR_UNIT_NOT_FOUND)
    return r


def get_loan(lid):
    r = db.floor_plan_loans.get(lid)
    if r is None:
        errors.err(errors.ERR_FLOOR_PLAN_LOAN_NOT_FOUND)
    return r


def get_deal(did):
    r = db.deals.get(did)
    if r is None:
        errors.err(errors.ERR_DEAL_NOT_FOUND)
    return r


def get_trade(tid):
    r = db.trade_ins.get(tid)
    if r is None:
        errors.err(errors.ERR_TRADE_IN_NOT_FOUND)
    return r


def get_technician(tid):
    r = db.technicians.get(tid)
    if r is None:
        errors.err(errors.ERR_TECHNICIAN_NOT_FOUND)
    return r


def get_repair_order(rid):
    r = db.repair_orders.get(rid)
    if r is None:
        errors.err(errors.ERR_REPAIR_ORDER_NOT_FOUND)
    return r


def get_part(pid):
    r = db.parts.get(pid)
    if r is None:
        errors.err(errors.ERR_PART_NOT_FOUND)
    return r


def get_part_line(plid):
    r = db.part_lines.get(plid)
    if r is None:
        errors.err(errors.ERR_PART_LINE_NOT_FOUND)
    return r


def get_service_line(slid):
    r = db.service_lines.get(slid)
    if r is None:
        errors.err(errors.ERR_SERVICE_LINE_NOT_FOUND)
    return r


def get_curtailment(cid):
    r = db.curtailments.get(cid)
    if r is None:
        errors.err(errors.ERR_CURTAILMENT_NOT_FOUND)
    return r


def get_storage_bay(bid):
    r = db.storage_bays.get(bid)
    if r is None:
        errors.err(errors.ERR_STORAGE_BAY_NOT_FOUND)
    return r


def get_storage_agreement(aid):
    r = db.storage_agreements.get(aid)
    if r is None:
        errors.err(errors.ERR_STORAGE_AGREEMENT_NOT_FOUND)
    return r


def get_waiver(wid):
    r = db.test_ride_waivers.get(wid)
    if r is None:
        errors.err(errors.ERR_WAIVER_NOT_FOUND)
    return r


def get_warranty_claim(wid):
    r = db.warranty_claims.get(wid)
    if r is None:
        errors.err(errors.ERR_WARRANTY_CLAIM_NOT_FOUND)
    return r
