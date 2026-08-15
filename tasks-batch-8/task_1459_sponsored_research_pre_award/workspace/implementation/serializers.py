"""Entity serializers — shape each stored record into its API representation."""

from db import public
from services import committed_effort_pct
from utils import fmt_dt, num_out


def opportunity_out(o):
    rec = public(o)
    rec["internal_deadline_at"] = fmt_dt(o["_internal_deadline_dt"])
    rec["fa_rate_cap_pct"] = num_out(o["fa_rate_cap_pct"])
    rec["min_cost_share_pct_of_request"] = num_out(o["min_cost_share_pct_of_request"])
    return rec


def pi_out(pi):
    rec = public(pi)
    rec["is_eligible"] = pi["delinquent_report_count"] == 0
    rec["committed_effort_pct"] = num_out(committed_effort_pct(pi))
    return rec


def proposal_out(p):
    rec = public(p)
    rec["pi_effort_pct"] = num_out(p["pi_effort_pct"])
    rec["fa_rate_pct_applied"] = num_out(p["fa_rate_pct_applied"])
    return rec


def budget_line_out(l):
    return public(l)


def snapshot_out(s):
    rec = public(s)
    rec["selected_rate_pct"] = num_out(s["selected_rate_pct"])
    rec["applied_rate_pct"] = num_out(s["applied_rate_pct"])
    return rec


def rate_out(r):
    rec = public(r)
    rec["rate_pct"] = num_out(r["rate_pct"])
    return rec


def cost_share_out(c):
    return public(c)


def review_out(r):
    return public(r)


def org_out(o):
    return public(o)


def sub_commitment_out(s):
    return public(s)


def offer_out(o):
    rec = public(o)
    rec["offered_fa_rate_pct"] = num_out(o["offered_fa_rate_pct"])
    return rec


def package_out(p):
    return public(p)


def handoff_out(h):
    return public(h)
