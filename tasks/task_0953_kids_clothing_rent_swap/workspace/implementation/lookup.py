"""G3_EXISTENCE (rungs 6-12), G4_STANDING (rungs 14-16), G5_PAUSE (rungs 17-18)."""

import store
from errors import ApiError


def _need(table, row_id, error_id):
    row = store.get(table, row_id)
    if row is None:
        raise ApiError(error_id)
    return row


# rung 6
def member(row_id):
    return _need("members", row_id, "ERR_MEMBER_NOT_FOUND")


def plan(row_id):
    return _need("plans", row_id, "ERR_PLAN_NOT_FOUND")


# rung 7
def cycle(row_id):
    return _need("cycles", row_id, "ERR_CYCLE_NOT_FOUND")


def box(row_id):
    return _need("boxes", row_id, "ERR_CYCLE_NOT_FOUND")


def box_item(row_id):
    return _need("box_items", row_id, "ERR_CYCLE_NOT_FOUND")


def swap_request(row_id):
    return _need("swap_requests", row_id, "ERR_CYCLE_NOT_FOUND")


# rung 8
def style(row_id):
    return _need("styles", row_id, "ERR_STYLE_NOT_FOUND")


def unit(row_id):
    return _need("units", row_id, "ERR_STYLE_NOT_FOUND")


# rung 9
def shipment(row_id):
    return _need("shipments", row_id, "ERR_SHIPMENT_NOT_FOUND")


def label(row_id):
    return _need("labels", row_id, "ERR_SHIPMENT_NOT_FOUND")


# rung 10
def submission(row_id):
    return _need("submissions", row_id, "ERR_TRADE_IN_NOT_FOUND")


def trade_in_item(row_id):
    return _need("trade_in_items", row_id, "ERR_TRADE_IN_NOT_FOUND")


# rung 11
def assessment(row_id):
    return _need("assessments", row_id, "ERR_ASSESSMENT_NOT_FOUND")


def job(row_id):
    return _need("jobs", row_id, "ERR_ASSESSMENT_NOT_FOUND")


# rung 12
def capsule(row_id):
    return _need("capsules", row_id, "ERR_RESOURCE_NOT_FOUND")


def capsule_allocation(row_id):
    return _need("capsule_allocations", row_id, "ERR_RESOURCE_NOT_FOUND")


def buyout_order(row_id):
    return _need("buyout_orders", row_id, "ERR_RESOURCE_NOT_FOUND")


def pause_request(row_id):
    return _need("pause_requests", row_id, "ERR_RESOURCE_NOT_FOUND")


def claim(row_id):
    return _need("claims", row_id, "ERR_RESOURCE_NOT_FOUND")


def credit_entry(row_id):
    return _need("credit_entries", row_id, "ERR_RESOURCE_NOT_FOUND")


def charge_entry(row_id):
    return _need("charge_entries", row_id, "ERR_RESOURCE_NOT_FOUND")


# ---------- G4_STANDING --------------------------------------------------

def standing(member_row, block_pending=False, block_delinquent=False):
    """Rung 14 always; rung 15 for circulation/intake writes; rung 16 for the
    five endpoints PRD rung 16 names and no others."""
    if member_row["status"] == "CANCELLED":
        raise ApiError("ERR_MEMBER_CANCELLED")
    if block_pending and member_row["status"] == "PENDING":
        raise ApiError("ERR_MEMBER_NOT_ACTIVATED")
    if block_delinquent and member_row["status"] == "DELINQUENT":
        raise ApiError("ERR_MEMBER_DELINQUENT")


# ---------- G5_PAUSE -----------------------------------------------------

def pause_gate_r(member_row):
    """Rung 17: Pipeline R circulation write."""
    if member_row["status"] == "PAUSED":
        raise ApiError("ERR_MEMBER_PAUSED")


def pause_gate_t(member_row):
    """Rung 18: Pipeline T intake write."""
    if member_row["status"] == "PAUSED":
        raise ApiError("ERR_INTAKE_BLOCKED_WHILE_PAUSED")
