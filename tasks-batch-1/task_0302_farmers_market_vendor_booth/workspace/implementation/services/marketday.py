"""MarketDay lifecycle cascades: open, close (§3.5), cancel/weather (§3.6)."""
from common import touch
from db import db
from services import assignment as asg_svc
from services import derived


def do_open(market_day):
    market_day["status"] = "OPEN"
    market_day["opened_at"] = db.clock.now_iso()
    touch(market_day)


def do_close(market_day):
    """OPEN -> CLOSED. Three cascades (§3.5):
    - EXPECTED check-ins -> NO_SHOW (bump owning vendor no_show_strikes)
    - RESERVED/ACTIVE DAILY assignments on this day -> COMPLETED
    - ISSUED voucher batches for this day -> CLOSED
    """
    market_day["status"] = "CLOSED"
    touch(market_day)

    # Check-ins EXPECTED -> NO_SHOW
    affected_vendors = set()
    for c in db.check_ins.values():
        if c["market_day_id"] == market_day["id"] and c["status"] == "EXPECTED":
            c["status"] = "NO_SHOW"
            touch(c)
            asg = db.booth_assignments.get(c["booth_assignment_id"])
            if asg:
                affected_vendors.add(asg["vendor_id"])
    for vid in affected_vendors:
        v = db.vendors.get(vid)
        if v:
            derived.recompute_no_show_strikes(v)

    # DAILY assignments RESERVED/ACTIVE on this day -> COMPLETED
    for a in list(db.booth_assignments.values()):
        if (a["market_day_id"] == market_day["id"]
                and a["assignment_type"] == "DAILY"
                and a["status"] in ("RESERVED", "ACTIVE")):
            asg_svc.do_complete(a)

    # Voucher batches ISSUED -> CLOSED
    for b in db.voucher_batches.values():
        if b["market_day_id"] == market_day["id"] and b["status"] == "ISSUED":
            b["status"] = "CLOSED"
            touch(b)


def do_cancel(market_day, reason):
    """SCHEDULED/OPEN -> CANCELLED. Master cascade (§3.6)."""
    market = db.markets[market_day["market_id"]]
    market_day["status"] = "CANCELLED"
    market_day["cancellation_reason"] = reason
    market_day["daily_fee_refundable"] = (reason == "WEATHER")
    touch(market_day)
    weather = (reason == "WEATHER")

    # Depth-1: DAILY assignments on this day in REQUESTED/WAITLISTED/RESERVED/ACTIVE
    # -> CANCELLED (with weather refund + booth freeing where applicable).
    for a in list(db.booth_assignments.values()):
        if (a["market_day_id"] == market_day["id"]
                and a["assignment_type"] == "DAILY"
                and a["status"] in ("REQUESTED", "WAITLISTED", "RESERVED", "ACTIVE")):
            asg_svc.do_cancel(a, weather=weather)

    # Check-ins for a cancelled day are voided (status untouched, excluded from
    # attendance_count). recompute_attendance returns 0 for a CANCELLED day.
    derived.recompute_attendance(market_day)

    # Voucher redemptions for this day RECONCILED/SUBMITTED -> REVERSED.
    for r in db.voucher_redemptions.values():
        if r["market_day_id"] == market_day["id"] and r["status"] in ("SUBMITTED", "RECONCILED"):
            r["status"] = "REVERSED"
            r["reimbursed_cents"] = 0
            touch(r)
    # Recompute batch tokens_redeemed + market voucher liability after reversal.
    for b in db.voucher_batches.values():
        if b["market_id"] == market["id"]:
            derived.recompute_batch_tokens_redeemed(b)
    derived.recompute_market_voucher_liability(market, force_bump=True)

    # Voucher batches for this day -> CLOSED.
    for b in db.voucher_batches.values():
        if b["market_day_id"] == market_day["id"] and b["status"] == "ISSUED":
            b["status"] = "CLOSED"
            touch(b)
