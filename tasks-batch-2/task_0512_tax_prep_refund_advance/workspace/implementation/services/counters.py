"""Denormalized counter maintenance (PRD §2.9).

Office.open_return_count = count of TaxReturn rows in the office whose status is
NOT IN {EFILED_ACCEPTED, CANCELLED}.
Preparer.assigned_open_returns = count of TaxReturn rows assigned to the preparer
whose status is NOT IN {EFILED_ACCEPTED, CANCELLED}.

The PRD specifies incremental deltas for open/assign/accept and a recompute on
cancel. Computing from authoritative state on every counter-affecting event
yields identical results and avoids drift; these helpers do exactly that."""
from db import db
from constants import RETURN_CLOSED_STATES


def recompute_office_open_return_count(office_id):
    office = db.offices.get(office_id)
    if office is None:
        return
    count = sum(
        1 for r in db.returns.values()
        if r["office_id"] == office_id and r["status"] not in RETURN_CLOSED_STATES
    )
    office["open_return_count"] = count


def recompute_preparer_assigned_open_returns(preparer_id):
    if preparer_id is None:
        return
    prep = db.preparers.get(preparer_id)
    if prep is None:
        return
    count = sum(
        1 for r in db.returns.values()
        if r.get("preparer_id") == preparer_id and r["status"] not in RETURN_CLOSED_STATES
    )
    prep["assigned_open_returns"] = count
