"""Clock-driven system transitions (PRD §2.4) and shared cascade helpers."""
from datetime import timedelta

import db
from services import calculations as calc
from services.clock import now, format_iso
from util import touch


def run_clock_transitions():
    """Apply automatic transitions sensitive to the logical clock:
    - PaymentMilestone INVOICED → OVERDUE when past due_date
    - Deal RENEWAL_OPEN → LAPSED when past term_end without exercise
    - RenewalOffer OPEN → LAPSED when matching_window_end passes without match
    """
    now_dt = now()

    for m in list(db.payment_milestones.values()):
        if m["status"] == "INVOICED" and now_dt > m["due_date"]:
            m["status"] = "OVERDUE"
            touch(m)
            deal = db.deals.get(m["deal_id"])
            if deal is not None:
                deal["payment_delinquency_count"] = deal.get("payment_delinquency_count", 0) + 1
                touch(deal)
                calc.refresh_posture(deal)

    for d in list(db.deals.values()):
        if d["status"] == "RENEWAL_OPEN" and now_dt >= d["term_end"]:
            d["status"] = "LAPSED"
            touch(d)
            for o in db.renewal_offers.values():
                if o["deal_id"] == d["id"] and o["status"] == "OPEN":
                    o["status"] = "LAPSED"
                    touch(o)

    for o in list(db.renewal_offers.values()):
        if o["status"] == "OPEN" and now_dt > o["matching_window_end"]:
            o["status"] = "LAPSED"
            touch(o)


def deal_terminal_statuses():
    return {"RENEWED", "LAPSED", "TERMINATED_BREACH", "TERMINATED_CONVENIENCE"}


def suspend_broadcaster_with_consequences(b):
    """PRD §3.2 suspension, including its market consequences: every live bid
    on packages still OPEN_FOR_BIDS moves to WITHDRAWN, and every PENDING
    sublicense request attached to a deal where this broadcaster is the deal's
    broadcaster is rejected. Used by the suspend endpoint and by any workflow
    that suspends "per §3.2" (e.g. breach termination, §3.9)."""
    b["status"] = "SUSPENDED"
    touch(b)
    for bid in db.bids.values():
        if bid["bidder_id"] != b["id"] or bid["status"] in bid_terminal_statuses():
            continue
        pkg = db.packages.get(bid["package_id"])
        if pkg is not None and pkg["status"] == "OPEN_FOR_BIDS":
            bid["status"] = "WITHDRAWN"
            touch(bid)
    for s in db.sublicense_requests.values():
        if s["status"] != "PENDING":
            continue
        deal = db.deals.get(s["deal_id"])
        if deal is not None and deal["broadcaster_id"] == b["id"]:
            s["status"] = "REJECTED"
            touch(s)


def bid_terminal_statuses():
    return {"ACCEPTED", "REJECTED", "WITHDRAWN", "EXPIRED"}


def milestone_active_statuses():
    return {"SCHEDULED", "INVOICED", "OVERDUE"}
