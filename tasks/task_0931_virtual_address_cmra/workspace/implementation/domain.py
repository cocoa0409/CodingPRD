"""Derivations, cascades, metering and the logical-clock re-derivation pass."""

import calc
import store
from errors import ApiError
from response import touch
from store import DB, insert
from util import (
    BILLING_CYCLE_LENGTH_DAYS, CLOCK, add_days, dec, round_half_up,
)

UNIT_COUNTER = {
    "SCAN_PAGE": "scan_pages_consumed",
    "FORWARD": "forwards_consumed",
    "STORAGE_DAY": "storage_days_consumed",
    "RECIPIENT": "recipients_consumed",
}
UNIT_RATE_FIELD = {
    "SCAN_PAGE": "overage_scan_page_cents",
    "FORWARD": "overage_forward_cents",
    "STORAGE_DAY": "overage_storage_day_cents",
    "RECIPIENT": "overage_recipient_cents",
}


# ============================================================ release eligibility
def governing(recipient_id, doc_class):
    """
    PRD 3.3: among the member's documents of this class with status VERIFIED or
    EXPIRED -- deliberately including expired rows -- the greatest verified_at,
    ties broken by created_at ascending.
    """
    rows = [d for d in store.docs_of_recipient(recipient_id)
            if d["doc_class"] == doc_class and d["status"] in ("VERIFIED", "EXPIRED")
            and d.get("verified_at") is not None]
    if not rows:
        return None
    best = rows[0]
    for d in rows[1:]:
        if d["verified_at"] > best["verified_at"]:
            best = d
    return best


def eligibility_clauses(r):
    """Five clauses, evaluated in order, stopping at the first failure."""
    if not any(f["status"] == "ACCEPTED" for f in store.forms_of_recipient(r["id"])):
        return "BLOCKED", "NO_ACCEPTED_1583"
    photo = governing(r["id"], "PHOTO")
    address = governing(r["id"], "ADDRESS")
    if photo is None or address is None:
        return "BLOCKED", "ID_SET_INCOMPLETE"
    if photo["status"] != "VERIFIED" or address["status"] != "VERIFIED":
        return "BLOCKED", "ID_EXPIRED"
    if r["recipient_kind"] == "MINOR":
        g = store.recipient(r["guarantor_recipient_id"]) if r["guarantor_recipient_id"] else None
        if g is None or g["release_eligibility"] != "RELEASABLE":
            return "BLOCKED", "GUARANTOR_BLOCKED"
    if r["roster_status"] != "AUTHORIZED":
        return "BLOCKED", "ROSTER_NOT_AUTHORIZED"
    return "RELEASABLE", "NONE"


def rederive_eligibility(r, _depth=0):
    """Applies the derivation and runs the crossing cascades of PRD 3.3."""
    new_state, reason = eligibility_clauses(r)
    old_state = r["release_eligibility"]
    if new_state == old_state:
        if r["blocked_reason"] != reason:
            r["blocked_reason"] = reason
        return
    r["release_eligibility"] = new_state
    r["blocked_reason"] = reason
    touch(r)
    if new_state == "RELEASABLE":
        if _depth < 4:
            for dep in store.recipients_of_box(r["box_id"]):
                if dep["guarantor_recipient_id"] == r["id"]:
                    rederive_eligibility(dep, _depth + 1)
        for item in store.mail_items_of_box(r["box_id"]):
            if item["matched_recipient_id"] == r["id"] and item["handling_status"] == "AWAITING_CLEARANCE":
                item["handling_status"] = "HELD"
                touch(item)
                evaluate_storage_axis(item)
    else:
        if _depth < 4:
            for dep in store.recipients_of_box(r["box_id"]):
                if dep["guarantor_recipient_id"] == r["id"]:
                    rederive_eligibility(dep, _depth + 1)
        for item in store.mail_items_of_box(r["box_id"]):
            if item["matched_recipient_id"] == r["id"] and item["handling_status"] == "HELD":
                item["handling_status"] = "AWAITING_CLEARANCE"
                touch(item)


# ============================================================ metering
def _allowance(tier, box, unit_type):
    if unit_type == "SCAN_PAGE":
        return tier["included_scan_pages"]
    if unit_type == "FORWARD":
        return tier["included_forwards"]
    if unit_type == "STORAGE_DAY":
        # Deliberately zero: included_storage_days is a PER-PIECE free window
        # the storage-day calculation already subtracted.
        return 0
    # Adjudication of friction 6 (reading B): a newly authorized roster member is
    # tranched by this ONE overage-metering rule, keyed on the cycle's
    # recipients_consumed, not on the live post-transition AUTHORIZED roster
    # count.  Reading A breaks the declared conservation invariant
    # quota_tranche_partition (IN_TIER sum == min(cycle consumption, allowance))
    # for any member authorized in a later cycle, and would also make rung 36's
    # ERR_QUOTA_EXHAUSTED on form acceptance inconsistent with every other
    # consumption event.
    return tier["included_recipients"] + box["extra_recipient_slots"]


def quota_would_exhaust(box, unit_type, quantity):
    """Rung 36 pre-check: nothing at all is written when this returns True."""
    cycle = store.open_cycle(box["id"])
    tier = store.tier_of_box(box)
    if cycle is None or tier is None:
        return False
    remaining = max(0, _allowance(tier, box, unit_type) - cycle[UNIT_COUNTER[unit_type]])
    overage = quantity - min(quantity, remaining)
    return overage > 0 and not tier["allows_overage"]


def meter(box, unit_type, quantity, source_event, mail_item=None):
    cycle = store.open_cycle(box["id"])
    tier = store.tier_of_box(box)
    if cycle is None or tier is None or quantity <= 0:
        return []
    counter = UNIT_COUNTER[unit_type]
    remaining = max(0, _allowance(tier, box, unit_type) - cycle[counter])
    in_tier = min(quantity, remaining)
    overage = quantity - in_tier
    entries = []
    if in_tier > 0:
        entries.append(_append_entry(cycle, mail_item, unit_type, "IN_TIER", in_tier, 0, source_event))
    if overage > 0:
        rate = tier[UNIT_RATE_FIELD[unit_type]]
        entries.append(_append_entry(cycle, mail_item, unit_type, "OVERAGE", overage, rate, source_event))
    cycle[counter] += quantity
    touch(cycle)
    if entries and mail_item is not None and mail_item["billing_status"] == "UNBILLED":
        mail_item["billing_status"] = "METERED"
        touch(mail_item)
    return entries


def _append_entry(cycle, mail_item, unit_type, tranche, quantity, rate, source_event):
    return insert(DB.usage_entries, {
        "billing_cycle_id": cycle["id"],
        "mail_item_id": mail_item["id"] if mail_item is not None else None,
        "unit_type": unit_type,
        "tranche": tranche,
        "quantity": quantity,
        "unit_rate_cents": rate,
        "amount_cents": quantity * rate,
        "source_event": source_event,
    }, common=False)


# ============================================================ storage axis
def evaluate_storage_axis(item):
    """
    PRD 3.12.  FREE_WINDOW -> ACCRUING is not evaluated at all while
    handling_status is PENDING_DISPOSITION; an already-ACCRUING piece keeps
    accruing one entry per additional whole day.
    """
    if item["storage_status"] not in ("FREE_WINDOW", "ACCRUING"):
        return
    if item["item_class"] == "SOP":
        return
    box = store.box(item["box_id"])
    tier = store.tier_of_box(box) if box else None
    if tier is None:
        return
    free, billable = calc.storage_counters(item)
    if item["storage_status"] == "FREE_WINDOW":
        if item["handling_status"] not in ("RECEIVED", "AWAITING_CLEARANCE", "HELD"):
            return
        if (free + billable) <= tier["included_storage_days"]:
            return
        item["storage_status"] = "ACCRUING"
        touch(item)
    qty = billable - item.get("metered_storage_days", 0)
    if qty > 0:
        item["metered_storage_days"] = billable
        meter(box, "STORAGE_DAY", qty, "STORAGE_ACCRUAL", mail_item=item)
        touch(item)


def end_custody(item, destroyed=False):
    """Any move into FORWARDED/DEPOSITED/RETURNED/REFUSED (or SHREDDED)."""
    if item["storage_status"] in ("FREE_WINDOW", "ACCRUING"):
        item["storage_status"] = "DESTROYED" if destroyed else "RELEASED"
        item["released_at"] = CLOCK.now
        touch(item)


# ============================================================ logical clock
def advance_clock(new_instant):
    CLOCK.now = new_instant
    clock_date = CLOCK.date()

    # 1. identification documents, monotonically
    touched_recipients = []
    for d in store.rows(DB.id_documents):
        if d["status"] in ("EXPIRED", "SUPERSEDED"):
            continue
        exp = d["_expires_date"]
        if exp is not None and clock_date > exp:
            was_verified = d["status"] == "VERIFIED"
            d["status"] = "EXPIRED"
            touch(d)
            if was_verified:
                touched_recipients.append(d["recipient_id"])

    # 2. accepted Form 1583 applications
    for f in store.rows(DB.form1583s):
        if f["status"] == "ACCEPTED" and f["expires_on"] is not None and clock_date > f["expires_on"]:
            f["status"] = "EXPIRED"
            touch(f)

    # 3. release eligibility of every roster member, with the mail-item cascade
    for r in store.rows(DB.recipients):
        rederive_eligibility(r)

    # 4. the storage axis of every piece
    for item in store.rows(DB.mail_items):
        evaluate_storage_axis(item)

    # 5. the notification obligation
    for item in store.rows(DB.mail_items):
        if (item["notification_status"] == "PENDING" and item["notified_at"] is None
                and item["notification_due_at"] is not None
                and CLOCK.now > item["notification_due_at"]):
            item["notification_status"] = "BREACHED"
            touch(item)

    # 6. the cancellation lifecycle
    for c in store.rows(DB.cancellations):
        if c["status"] == "REQUESTED" and clock_date >= c["notice_end_date"]:
            c["status"] = "FINAL_FORWARD"
            touch(c)


# ============================================================ billing cycles
def create_cycle(box, cycle_index, period_start):
    return insert(DB.billing_cycles, {
        "box_id": box["id"],
        "cycle_index": cycle_index,
        "period_start": period_start,
        "period_end": add_days(period_start, BILLING_CYCLE_LENGTH_DAYS),
        "status": "OPEN",
        "plan_tier_id_at_close": None,
        "scan_pages_consumed": 0,
        "forwards_consumed": 0,
        "storage_days_consumed": 0,
        "recipients_consumed": 0,
        "base_fee_cents": 0,
        "overage_total_cents": 0,
        "proration_charge_cents": 0,
        "proration_credit_cents": 0,
        "loyalty_discount_cents": 0,
        "total_charge_cents": 0,
    })


def close_cycle(box, cycle):
    """
    Two transitions inside one request.  Adjudication of friction 7 (reading A):
    Box/BillingCycle rows advance by exactly ONE version per request per PRD 2.4,
    never once per side effect, so the closing cycle's version advances by 1.
    """
    tier = store.tier_of_box(box)
    cycle["status"] = "CLOSING"
    cycle["plan_tier_id_at_close"] = box["plan_tier_id"]
    cycle["base_fee_cents"] = tier["monthly_fee_cents"] if tier else 0
    cycle["overage_total_cents"] = sum(
        e["amount_cents"] for e in store.entries_of_cycle(cycle["id"]) if e["tranche"] == "OVERAGE")
    subtotal = (cycle["base_fee_cents"] + cycle["overage_total_cents"]
                + cycle["proration_charge_cents"] - cycle["proration_credit_cents"])
    cycle["loyalty_discount_cents"] = calc.loyalty_discount(subtotal)
    touch(cycle)

    cycle["status"] = "CLOSED"
    cycle["total_charge_cents"] = subtotal - cycle["loyalty_discount_cents"]
    box["prepaid_balance_cents"] -= min(cycle["total_charge_cents"], box["prepaid_balance_cents"])
    touch(box)

    for item in store.mail_items_of_box(box["id"]):
        if item["billing_status"] != "METERED":
            continue
        if all(e["billing_cycle_id"] == cycle["id"] for e in store.entries_of_item(item["id"])):
            item["billing_status"] = "BILLED"
            touch(item)

    pending = box["pending_plan_tier_id"]
    if pending:
        box["plan_tier_id"] = pending
        box["pending_plan_tier_id"] = None
        touch(box)
    new_cycle = create_cycle(box, cycle["cycle_index"] + 1, cycle["period_end"])
    if pending:
        new_tier = store.plan_tier(pending)
        authorized = sum(1 for r in store.recipients_of_box(box["id"])
                         if r["roster_status"] == "AUTHORIZED")
        new_cap = (new_tier["included_recipients"] + box["extra_recipient_slots"]) if new_tier else 0
        excess = max(0, authorized - new_cap)
        if excess > 0:
            _append_entry(new_cycle, None, "RECIPIENT", "OVERAGE", excess,
                          new_tier["overage_recipient_cents"], "PLAN_CHANGE")
    return cycle


def proration(old_tier, new_tier, cycle):
    """Multiply the WHOLE monthly fee, then divide, then round exactly once."""
    days_elapsed = max(0, (CLOCK.date() - cycle["period_start"]).days)
    days_remaining = max(0, 30 - days_elapsed)
    credit = round_half_up(dec(old_tier["monthly_fee_cents"]) * days_remaining / dec(30))
    charge = round_half_up(dec(new_tier["monthly_fee_cents"]) * days_remaining / dec(30))
    return credit, charge


# ============================================================ misc helpers
def winning_disposition(mail_item_id):
    pend = store.pending_dispositions(mail_item_id)
    if not pend:
        return None
    return min(pend, key=lambda d: (d["precedence_rank"], d["created_at"], d["id"]))


def sop_retention_blocks(item, cancellation=None):
    """
    PRD 3.10 / sop_retention_deadline.  Destruction is refused while the clock
    date is strictly less than the deadline.
    """
    ra = store.active_ra(item["box_id"])
    if item["item_class"] == "SOP" and ra is not None:
        deadline = add_days(item["received_at"].date(), ra["retention_days"])
    elif cancellation is not None:
        deadline = cancellation["destruction_eligible_on"]
    else:
        return False
    return CLOCK.date() < deadline


def raise_quota(box, unit_type, quantity):
    if quota_would_exhaust(box, unit_type, quantity):
        raise ApiError("ERR_QUOTA_EXHAUSTED")
