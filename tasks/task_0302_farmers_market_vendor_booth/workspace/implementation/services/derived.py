"""Derived-field reconciliation: market ledgers (PRD §2.9), vendor permit_ok
(PRD §2.10), no_show_strikes, booth_count, attendance_count, batch tokens_redeemed.

A recompute that changes a derived field is itself a mutation: it refreshes
updated_at and increments version on the resource whose derived field changed
(PRD §2.4). Helpers here bump version only when the value actually changes,
EXCEPT where a transition's spec explicitly says "increments Market.version"
(those call sites force the bump).
"""
from common import touch
from db import db

HEALTH_GATED_CATEGORIES = {"DAIRY", "MEAT", "PREPARED_FOOD"}


# ---------------------------------------------------------------------------
# Vendor.permit_ok (PRD §2.10) — evaluated at a given window date.
# The stored permit_ok is a "best effort" flag recomputed on permit verify/
# expire; the authoritative assignment-time check re-evaluates against the
# specific window date via vendor_permit_ok_for_date().
# ---------------------------------------------------------------------------
def _approved_category(vendor_id):
    cats = []
    for a in db.applications.values():
        if a["vendor_id"] == vendor_id and a["status"] == "APPROVED":
            cats.append(a["product_category"])
    return cats


def vendor_permit_ok_for_date(vendor, window_date):
    """True iff the vendor's APPROVED category needs no health permit, OR a
    VERIFIED HEALTH permit with expiry_date >= window_date exists."""
    cats = _approved_category(vendor["id"])
    needs_health = any(c in HEALTH_GATED_CATEGORIES for c in cats)
    if not needs_health:
        # No approved health-gated category -> no health permit needed.
        return True
    for p in db.permits.values():
        if (p["vendor_id"] == vendor["id"]
                and p["permit_type"] == "HEALTH"
                and p["status"] == "VERIFIED"
                and p["expiry_date"] >= window_date):
            return True
    return False


def recompute_vendor_permit_ok(vendor):
    """Recompute the stored permit_ok flag against today's date."""
    today = db.clock.today_date()
    new_val = vendor_permit_ok_for_date(vendor, today)
    if vendor["permit_ok"] != new_val:
        vendor["permit_ok"] = new_val
        touch(vendor)


def recompute_no_show_strikes(vendor):
    count = sum(1 for c in db.check_ins.values()
                if c["status"] == "NO_SHOW" and _checkin_vendor_id(c) == vendor["id"])
    if vendor["no_show_strikes"] != count:
        vendor["no_show_strikes"] = count
        touch(vendor)


def _checkin_vendor_id(check_in):
    asg = db.booth_assignments.get(check_in["booth_assignment_id"])
    return asg["vendor_id"] if asg else None


# ---------------------------------------------------------------------------
# Market ledgers (PRD §2.9)
# ---------------------------------------------------------------------------
def recompute_market_fees(market, force_bump=False):
    """total_fees_collected_cents = sum(fee_charged - fee_refunded) over
    BoothAssignment rows in {RESERVED, ACTIVE}."""
    total = 0
    for a in db.booth_assignments.values():
        if a["market_id"] == market["id"] and a["status"] in ("RESERVED", "ACTIVE"):
            total += a["fee_charged_cents"] - a["fee_refunded_cents"]
    changed = market["total_fees_collected_cents"] != total
    market["total_fees_collected_cents"] = total
    if changed or force_bump:
        touch(market)


def recompute_market_commission(market, force_bump=False):
    """total_commission_accrued_cents = sum(commission_cents) over RECONCILED
    sales reports under the market."""
    total = 0
    for s in db.sales_reports.values():
        if s["market_id"] == market["id"] and s["status"] == "RECONCILED":
            total += s["commission_cents"]
    changed = market["total_commission_accrued_cents"] != total
    market["total_commission_accrued_cents"] = total
    if changed or force_bump:
        touch(market)


def recompute_batch_tokens_redeemed(batch):
    """tokens_redeemed = min(tokens_issued, sum RECONCILED redemption token_count)."""
    s = sum(r["token_count"] for r in db.voucher_redemptions.values()
            if r["voucher_batch_id"] == batch["id"] and r["status"] == "RECONCILED")
    capped = min(batch["tokens_issued"], s)
    if batch["tokens_redeemed"] != capped:
        batch["tokens_redeemed"] = capped
        touch(batch)


def recompute_market_voucher_liability(market, force_bump=False):
    """voucher_liability_cents (PRD §2.9 / scaffold entity definition):

        voucher_face_value_cents * (total tokens redeemed across all RECONCILED
        redemptions [capped per batch by issuance] minus tokens already reimbursed)

    There is no disbursement/reimbursement action in the API, so "tokens already
    reimbursed" (cash disbursed to vendors) is 0 — the disbursement lags
    redemption, leaving the liability positive on an ordinary day (§3.7). When a
    redemption is REVERSED its tokens drop out of the redeemed sum (via the batch
    tokens_redeemed recompute) and the liability falls back toward 0."""
    face = market["voucher_face_value_cents"]
    redeemed_total = 0
    for b in db.voucher_batches.values():
        if b["market_id"] == market["id"]:
            redeemed_total += b["tokens_redeemed"]
    reimbursed_tokens_to_date = 0  # no disbursement endpoint -> nothing reimbursed yet
    liability = face * (redeemed_total - reimbursed_tokens_to_date)
    changed = market["voucher_liability_cents"] != liability
    market["voucher_liability_cents"] = liability
    if changed or force_bump:
        touch(market)


def recompute_booth_count(market):
    count = sum(1 for b in db.booths.values() if b["market_id"] == market["id"])
    if market["booth_count"] != count:
        market["booth_count"] = count
        touch(market)


# ---------------------------------------------------------------------------
# MarketDay.attendance_count (PRD §3.5): count of PRESENT check-ins, excluding
# voided check-ins on a CANCELLED day.
# ---------------------------------------------------------------------------
def recompute_attendance(market_day):
    if market_day["status"] == "CANCELLED":
        count = 0
    else:
        count = sum(1 for c in db.check_ins.values()
                    if c["market_day_id"] == market_day["id"] and c["status"] == "PRESENT")
    if market_day["attendance_count"] != count:
        market_day["attendance_count"] = count
        touch(market_day)
