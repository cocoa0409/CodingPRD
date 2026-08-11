"""Billing Repair Card ledger operations shared by the billing routes and
the shop sweep: net-settled recomputation, balance posting, counter lookups."""
import db
from common import touch, rhu_cents
from decimal import Decimal


def brc_lines_of(brc_id):
    return [l for l in db.STORE["brc_lines"].values() if l["brc_id"] == brc_id]


def counters_of(brc_id):
    return [c for c in db.STORE["counter_bills"].values() if c["brc_id"] == brc_id]


def active_counters(brc_id):
    return [c for c in counters_of(brc_id) if c["status"] in ("OPEN", "REBUTTED")]


def recompute_net_settled(brc):
    """net_settled_cents = submitted_total_cents - sum(accepted credits)."""
    credits = sum(l["accepted_credit_cents"] for l in brc_lines_of(brc["id"]))
    brc["net_settled_cents"] = brc["submitted_total_cents"] - credits
    touch(brc)


def parties_for_work_order(wo):
    railcar = db.STORE["railcars"][wo["railcar_id"]]
    owner = db.STORE["car_owners"].get(railcar["owner_id"])
    line = db.STORE["handling_lines"].get(railcar["handling_line_id"])
    return railcar, owner, line


def accepted_credit_party_shares(brc):
    """Split each card line's accepted counter credits by the repair line's
    owner_pct (remainder to the handling line)."""
    owner_share = 0
    handling_share = 0
    for bl in brc_lines_of(brc["id"]):
        rl = db.STORE["repair_lines"].get(bl["repair_line_id"])
        pct = (rl["owner_pct"] or 0) if rl else 0
        oc = rhu_cents(Decimal(bl["accepted_credit_cents"]) * Decimal(pct) / Decimal(100))
        owner_share += oc
        handling_share += bl["accepted_credit_cents"] - oc
    return owner_share, handling_share


def post_balances(brc, sign):
    """Net posting (PRD 2.10): party totals minus that party's share of the
    accepted counter credits. sign=+1 at acceptance, -1 at settlement."""
    wo = db.STORE["work_orders"][brc["work_order_id"]]
    _, owner, line = parties_for_work_order(wo)
    owner_credit, handling_credit = accepted_credit_party_shares(brc)
    owner_post = brc["owner_total_cents"] - owner_credit
    handling_post = brc["handling_line_total_cents"] - handling_credit
    if owner is not None:
        owner["outstanding_balance_cents"] += sign * owner_post
        touch(owner)
    if line is not None:
        line["outstanding_balance_cents"] += sign * handling_post
        touch(line)


def maybe_resolve_disputed_brc(brc):
    """When the last active counter resolves, DISPUTED -> SUBMITTED."""
    if brc["status"] == "DISPUTED" and not active_counters(brc["id"]):
        brc["status"] = "SUBMITTED"
        recompute_net_settled(brc)


def party_match_or_403(wo):
    """PRD 2.1 scoped party rule: OWNER/SHARED -> CarOwnerRep == owner_id;
    HANDLING_LINE -> HandlingLineRep == handling_line_id."""
    from flask import g
    railcar = db.STORE["railcars"][wo["railcar_id"]]
    party = wo.get("responsible_party")
    role = g.user_role
    uid = g.user_id
    ok = False
    if party in ("OWNER", "SHARED"):
        ok = role == "CarOwnerRep" and uid == railcar["owner_id"]
    elif party == "HANDLING_LINE":
        ok = role == "HandlingLineRep" and uid == railcar["handling_line_id"]
    if not ok:
        from errors import ApiError
        raise ApiError("ERR_RESPONSIBILITY_MISMATCH", 403,
                       "Acting party does not match the work order's responsible party")
