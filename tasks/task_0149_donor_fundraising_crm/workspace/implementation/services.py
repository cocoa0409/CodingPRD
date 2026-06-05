"""Business logic: calculations, ledger reconciliation, and state-machine
cascades for the Donor & Fundraising CRM.

All money is integer cents. The only float is employer.match_ratio, applied
ratio-first then floored to whole cents (PRD §2.5 / §3.6).

Reconciliation is immediate: every derived total is recomputed inside the
request that triggers it.
"""

from datetime import timedelta

import db
import models
import util

# Gift statuses that count as "hard credit realized".
HARD_STATUSES = {"ACKNOWLEDGED", "RECEIPTED"}


# ===========================================================================
# Date arithmetic for installment due dates (§1.3 installment_schedule)
# ===========================================================================
def add_months(dt, months):
    """Add a whole number of months to a datetime, clamping the day to the
    last valid day of the target month."""
    if months == 0:
        return dt
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp day to last day of target month.
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def add_years(dt, years):
    if years == 0:
        return dt
    year = dt.year + years
    month = dt.month
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def _days_in_month(year, month):
    if month == 12:
        nxt = (year + 1, 1)
    else:
        nxt = (year, month + 1)
    from datetime import date
    return (date(nxt[0], nxt[1], 1) - date(year, month, 1)).days


# ===========================================================================
# §1.3 installment_schedule — per-installment amounts + due dates
# ===========================================================================
def compute_installment_amounts(total, n, schedule_basis):
    base = total // n
    rem = total - base * n  # 0 <= rem < n
    amounts = []
    for seq in range(1, n + 1):
        if schedule_basis == "FRONT_LOADED":
            extra = 1 if seq <= rem else 0
        else:  # BACK_LOADED
            extra = 1 if seq > (n - rem) else 0
        amounts.append(base + extra)
    return amounts


def compute_installment_due(created_dt, seq, frequency):
    """due_on offset from pledge.created_at by (seq-1) units of frequency."""
    k = seq - 1
    if frequency == "ONE_TIME":
        return created_dt
    if frequency == "MONTHLY":
        return add_months(created_dt, k)
    if frequency == "QUARTERLY":
        return add_months(created_dt, k * 3)
    if frequency == "ANNUAL":
        return add_years(created_dt, k)
    return created_dt


def mint_installments(pledge):
    """Create the installment rows for a pledge as a creation cascade."""
    n = pledge["installment_count"]
    total = pledge["total_amount_cents"]
    amounts = compute_installment_amounts(total, n, pledge["schedule_basis"])
    created_dt = util.parse_iso_string(pledge["created_at"])
    for seq in range(1, n + 1):
        due_dt = compute_installment_due(created_dt, seq, pledge["frequency"])
        inst = models.new_record({
            "pledge_id": pledge["id"],
            "sequence_no": seq,
            "amount_cents": amounts[seq - 1],
            "due_on": util.iso_from_dt(due_dt),
            "status": "DUE",
            "paid_by_gift_id": None,
        }, common=True)
        db.pledge_installments[inst["id"]] = inst


# ===========================================================================
# §1.3 deductible_amount
# ===========================================================================
def compute_deductible(amount_cents, benefit_value_cents):
    return max(0, amount_cents - benefit_value_cents)


# ===========================================================================
# §1.3 donor_giving_tier
# ===========================================================================
ENTRY_CEILING_CENTS = 50000
MAJOR_FLOOR_CENTS = 1000000


def compute_giving_tier(lifetime_cents):
    if lifetime_cents == 0:
        return "NONE"
    if lifetime_cents < ENTRY_CEILING_CENTS:
        return "ENTRY"
    if lifetime_cents < MAJOR_FLOOR_CENTS:
        return "MID"
    return "MAJOR"


# ===========================================================================
# §1.3 donor_lifetime_hard_credit + last_gift_at  (aggregation)
# ===========================================================================
def _donor_hard_gifts(donor_id):
    return [g for g in db.gifts.values()
            if g["donor_id"] == donor_id and g["status"] in HARD_STATUSES]


def recompute_donor_aggregates(donor):
    """Recompute lifetime_hard_credit_cents, giving_status, last_gift_at for a
    donor. Bumps the donor's version/updated_at (server-driven mutation)."""
    hard = _donor_hard_gifts(donor["id"])
    lifetime = sum(g["amount_cents"] for g in hard)
    donor["lifetime_hard_credit_cents"] = lifetime
    donor["giving_status"] = compute_giving_tier(lifetime)
    # last_gift_at = created_at of the most recent hard gift (by created_at).
    if hard:
        most_recent = max(hard, key=lambda g: (g["created_at"], g.get("_seq", 0)))
        donor["last_gift_at"] = most_recent["created_at"]
    else:
        donor["last_gift_at"] = None
    models.touch(donor)


# ===========================================================================
# §1.3 campaign_raised (dual variant: hard vs with-match)
# ===========================================================================
def recompute_campaign_raised(campaign):
    cid = campaign["id"]
    hard = sum(g["amount_cents"] for g in db.gifts.values()
               if g["campaign_id"] == cid and g["status"] in HARD_STATUSES)
    paid_match = 0
    for mc in db.match_claims.values():
        if mc["status"] != "PAID":
            continue
        gift = db.gifts.get(mc["gift_id"])
        if gift is not None and gift["campaign_id"] == cid:
            paid_match += mc["matched_amount_cents"]
    campaign["raised_hard_cents"] = hard
    campaign["raised_with_match_cents"] = hard + paid_match
    models.touch(campaign)


# ===========================================================================
# Appeal attributed_gift_count
# ===========================================================================
def recompute_appeal_count(appeal):
    aid = appeal["id"]
    count = sum(1 for g in db.gifts.values()
                if g.get("appeal_id") == aid and g["status"] in HARD_STATUSES)
    appeal["attributed_gift_count"] = count
    models.touch(appeal)


# ===========================================================================
# §1.3 soft_credit_distribution
# ===========================================================================
def recompute_household_total(household):
    hid = household["id"]
    total = sum(sc["soft_credit_cents"] for sc in db.soft_credits.values()
                if sc["household_id"] == hid and not sc["reversed"])
    household["total_soft_credit_cents"] = total
    models.touch(household)


def recompute_household_member_count(household):
    hid = household["id"]
    count = sum(1 for d in db.donors.values() if d.get("household_id") == hid)
    household["member_count"] = count
    models.touch(household)


def create_soft_credits(gift, donor, household):
    """Mint SoftCredit rows for a household gift acknowledgement per policy."""
    hid = household["id"]
    members = [d for d in db.donors.values() if d.get("household_id") == hid]
    others = [m for m in members if m["id"] != donor["id"]]
    policy = household["soft_credit_policy"]
    amount = gift["amount_cents"]

    rows_to_make = []  # list of (beneficiary_id, cents)

    if policy == "FULL_TO_ALL":
        for m in others:
            rows_to_make.append((m["id"], amount))
    elif policy == "SPLIT_EVEN":
        n = len(others)
        if n > 0:
            base = amount // n
            rem = amount - base * n
            sorted_others = util.sort_by_created(others)
            for i, m in enumerate(sorted_others):
                cents = base + (1 if i < rem else 0)
                rows_to_make.append((m["id"], cents))
    elif policy == "PRIMARY_ONLY":
        primary_id = household.get("primary_donor_id")
        if primary_id is not None and primary_id != donor["id"]:
            rows_to_make.append((primary_id, amount))

    for beneficiary_id, cents in rows_to_make:
        sc = models.new_record({
            "gift_id": gift["id"],
            "household_id": hid,
            "beneficiary_donor_id": beneficiary_id,
            "soft_credit_cents": cents,
            "reversed": False,
        }, common=False)  # SoftCredit: only id + created_at + reversed
        db.soft_credits[sc["id"]] = sc

    recompute_household_total(household)


def reverse_soft_credits(gift, household):
    """Flip reversed=true on this gift's soft-credit rows; recompute total."""
    for sc in db.soft_credits.values():
        if sc["gift_id"] == gift["id"] and not sc["reversed"]:
            sc["reversed"] = True
    recompute_household_total(household)


# ===========================================================================
# §1.3 match_amount
# ===========================================================================
def compute_requested_match(gift, employer):
    """At MatchClaim creation: ratio-first floor, then per-gift cap."""
    import math
    raw = math.floor(gift["amount_cents"] * employer["match_ratio"])
    return min(raw, employer["max_match_cents"])


def compute_matched_amount(claim, gift, employer):
    """At APPROVED->PAID: clamp requested_amount by remaining annual cap for
    the (donor, employer, calendar-year-of-gift) tuple."""
    gift_dt = util.parse_iso_string(gift["created_at"])
    year = gift_dt.year
    donor_id = gift["donor_id"]
    emp_id = employer["id"]
    already_paid = 0
    for mc in db.match_claims.values():
        if mc is claim:
            continue
        if mc["status"] != "PAID":
            continue
        if mc["employer_id"] != emp_id:
            continue
        other_gift = db.gifts.get(mc["gift_id"])
        if other_gift is None:
            continue
        if other_gift["donor_id"] != donor_id:
            continue
        ogd = util.parse_iso_string(other_gift["created_at"])
        if ogd.year != year:
            continue
        already_paid += mc["matched_amount_cents"]
    remaining = max(0, employer["annual_match_cap_cents"] - already_paid)
    return min(claim["requested_amount_cents"], remaining)


# ===========================================================================
# §1.3 receipt_numbering
# ===========================================================================
def next_receipt_number():
    count = sum(1 for a in db.acknowledgements.values() if a["kind"] == "RECEIPT")
    return "RCPT-" + str(count + 1).zfill(6)


# ===========================================================================
# Pledge recomputation + installment allocation/delinquency cascades
# ===========================================================================
def _pledge_hard_gifts(pledge_id):
    return [g for g in db.gifts.values()
            if g.get("pledge_id") == pledge_id and g["status"] in HARD_STATUSES]


def recompute_pledge_paid_balance(pledge):
    paid = sum(g["amount_cents"] for g in _pledge_hard_gifts(pledge["id"]))
    pledge["paid_cents"] = paid
    pledge["balance_cents"] = max(0, pledge["total_amount_cents"] - paid)
    models.touch(pledge)


def _pledge_installments(pledge_id):
    return [i for i in db.pledge_installments.values() if i["pledge_id"] == pledge_id]


def recompute_installments_due_count(pledge):
    clock = db.logical_now()
    count = 0
    for inst in _pledge_installments(pledge["id"]):
        if inst["status"] != "DUE":
            continue
        due_dt = util.parse_iso_string(inst["due_on"])
        if due_dt <= clock:
            count += 1
    pledge["installments_due_count"] = count
    models.touch(pledge)


def _earliest_due_installment(pledge_id):
    due = [i for i in db.pledge_installments.values()
           if i["pledge_id"] == pledge_id and i["status"] == "DUE"]
    if not due:
        return None
    due.sort(key=lambda i: (i["due_on"], i["sequence_no"]))
    return due[0]


def allocate_gift_to_pledge(gift, pledge):
    """Gift acknowledgement allocation cascade for a pledge-bearing gift.

    Recompute paid/balance, mark earliest DUE installment PAID, then resolve
    the pledge state (FULFILLED / back-to-ACTIVE)."""
    recompute_pledge_paid_balance(pledge)

    # Allocate to the single earliest DUE installment (due_on ASC, seq ASC).
    inst = _earliest_due_installment(pledge["id"])
    if inst is not None:
        inst["status"] = "PAID"
        inst["paid_by_gift_id"] = gift["id"]
        models.touch(inst)

    _resolve_pledge_state_after_payment(pledge)


def _resolve_pledge_state_after_payment(pledge):
    """After a payment allocation, drive ACTIVE/DELINQUENT -> FULFILLED if
    balance hit 0 (waiving remaining DUE installments), else DELINQUENT ->
    ACTIVE if no overdue installments remain."""
    if pledge["status"] in ("ACTIVE", "DELINQUENT"):
        if pledge["balance_cents"] == 0:
            # Mark remaining DUE installments WAIVED, then FULFILLED.
            for inst in _pledge_installments(pledge["id"]):
                if inst["status"] == "DUE":
                    inst["status"] = "WAIVED"
                    models.touch(inst)
            pledge["status"] = "FULFILLED"
            models.touch(pledge)
            recompute_installments_due_count(pledge)
            return

    # DELINQUENT -> ACTIVE when no overdue installment remains DUE.
    if pledge["status"] == "DELINQUENT":
        recompute_installments_due_count(pledge)
        if pledge["installments_due_count"] == 0:
            pledge["status"] = "ACTIVE"
            models.touch(pledge)
    else:
        recompute_installments_due_count(pledge)


def reverse_gift_from_pledge(gift, pledge):
    """Refund cascade for a pledge-bearing gift: recompute paid/balance, return
    the installment this gift paid to DUE, revert FULFILLED -> ACTIVE if the
    balance lifts above zero."""
    recompute_pledge_paid_balance(pledge)

    for inst in _pledge_installments(pledge["id"]):
        if inst["status"] == "PAID" and inst.get("paid_by_gift_id") == gift["id"]:
            inst["status"] = "DUE"
            inst["paid_by_gift_id"] = None
            models.touch(inst)

    if pledge["status"] == "FULFILLED" and pledge["balance_cents"] > 0:
        pledge["status"] = "ACTIVE"
        models.touch(pledge)

    recompute_installments_due_count(pledge)
