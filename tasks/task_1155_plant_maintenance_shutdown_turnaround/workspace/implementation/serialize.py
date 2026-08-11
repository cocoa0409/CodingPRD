"""Entity serializers: stored fields + computed fields, hidden `_`-prefixed
bookkeeping stripped. Computed aggregates are derived fresh from the store.
"""
import db
from db import public
from services import computed


def turnaround_out(t):
    out = public(t)
    committed, _provisional, posture = computed.forecast(t)
    out["committed_cost_cents"] = committed
    out["reported_cost_cents"] = computed.reported_cost_cents(t["id"])
    out["critical_path_slip_hours"] = computed.critical_path_slip_hours(t["id"])
    out["cost_posture"] = posture
    return out


def work_item_out(w):
    out = public(w)
    out["remaining_hours"] = computed.remaining_hours(w)
    return out


def dependency_out(d):
    return public(d)


def contractor_out(c):
    out = public(c)
    out["badged_headcount"] = computed.badged_headcount(c["id"])
    return out


def worker_out(w):
    out = public(w)
    out["ledger_hours"] = computed.ledger_hours(w["id"])
    out["fatigue_penalty_score"] = computed.fatigue_penalty_score(w["id"])
    out["total_shift_hours"] = computed.total_shift_hours(w["id"])
    return out


def shift_out(s):
    return public(s)


def assignment_out(a):
    return public(a)


def permit_out(p):
    return public(p)


def isolation_out(i):
    return public(i)


def discovery_out(d):
    return public(d)


def laydown_area_out(a):
    out = public(a)
    out["occupied_sqm"] = computed.occupied_sqm(a["id"])
    return out


def reservation_out(r):
    return public(r)


def daily_report_out(r):
    return public(r)


def punch_item_out(p):
    return public(p)
