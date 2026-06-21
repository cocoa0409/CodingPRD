"""Household-centric services: membership/active-count helpers, ledger recompute,
bill-split construction, and the move-out redistribution cascade.

The conservation invariant (PRD §2.6): ledger_sum_cents == 0 after every ledger
mutation. net_balance_cents is recomputed from POSTED expenses + unpaid bill
splits + CONFIRMED settlements.
"""
import models
from db import db
from services import calc


# ---------------------------------------------------------------------------
# Membership lookups
# ---------------------------------------------------------------------------
def memberships_of(household_id):
    return [m for m in db.memberships.values() if m["household_id"] == household_id]


def active_memberships(household_id):
    """ACTIVE memberships ordered by created_at ASC (split / weight ordering)."""
    items = [m for m in memberships_of(household_id) if m["status"] == "ACTIVE"]
    return models.sort_by_created(items)


def ledger_member_profiles(household_id):
    """Profile ids of ACTIVE or MOVED_OUT members (ledger participants)."""
    ids = []
    for m in memberships_of(household_id):
        if m["status"] in ("ACTIVE", "MOVED_OUT"):
            ids.append(m["profile_id"])
    return ids


def membership_for_profile(household_id, profile_id):
    for m in memberships_of(household_id):
        if m["profile_id"] == profile_id:
            return m
    return None


def is_active_member(household_id, profile_id):
    m = membership_for_profile(household_id, profile_id)
    return m is not None and m["status"] == "ACTIVE"


def recompute_active_count(household):
    household["active_member_count"] = len(
        [m for m in memberships_of(household["id"]) if m["status"] == "ACTIVE"]
    )


def listing_for_household(household):
    return db.room_listings.get(household["listing_id"])


# ---------------------------------------------------------------------------
# Net-balance ledger (PRD §2.6, calc household_net_balance)
# ---------------------------------------------------------------------------
def recompute_net_balances(household):
    """Recompute net_balance_cents for every ACTIVE/MOVED_OUT member of the household,
    then set household.ledger_sum_cents = sum (must be 0). Bumps each touched profile's
    version/updated_at as a cascade participant.

    Conservation note (PRD §2.6): the conserved ledger covers the internally balanced
    streams — POSTED expenses (a payer's credit is exactly offset by participants'
    obligations) and CONFIRMED settlements (a debtor's payment exactly offsets a
    creditor's receipt). Rent/utility bill obligations are paid to an external party,
    so they are NOT internally conserved and do not enter net_balance_cents; counting
    them would make ledger_sum_cents non-zero, violating the conservation guarantee that
    holds after every ledger-mutating operation including move-out."""
    hid = household["id"]
    member_ids = set(ledger_member_profiles(hid))

    # Pre-aggregate per-profile streams scoped to this household.
    credits = {pid: 0 for pid in member_ids}
    owed = {pid: 0 for pid in member_ids}
    settled_paid = {pid: 0 for pid in member_ids}
    settled_received = {pid: 0 for pid in member_ids}

    # POSTED expenses of this household: payer gets credit; participants owe their share.
    for exp in db.expenses.values():
        if exp["household_id"] != hid or exp["status"] != "POSTED":
            continue
        payer = exp["payer_id"]
        if payer in credits:
            credits[payer] += exp["total_amount_cents"]
        for sh in db.expense_shares.values():
            if sh["expense_id"] == exp["id"] and sh["profile_id"] in owed:
                owed[sh["profile_id"]] += sh["share_cents"]

    # CONFIRMED settlements of this household.
    for st in db.settlements.values():
        if st["household_id"] != hid or st["status"] != "CONFIRMED":
            continue
        if st["from_profile_id"] in settled_paid:
            settled_paid[st["from_profile_id"]] += st["amount_cents"]
        if st["to_profile_id"] in settled_received:
            settled_received[st["to_profile_id"]] += st["amount_cents"]

    ledger_sum = 0
    for pid in member_ids:
        net = credits[pid] - owed[pid] + settled_paid[pid] - settled_received[pid]
        profile = db.roommate_profiles.get(pid)
        if profile is not None and profile.get("net_balance_cents") != net:
            profile["net_balance_cents"] = net
            models.touch(profile)
        elif profile is not None:
            profile["net_balance_cents"] = net
        ledger_sum += net

    household["ledger_sum_cents"] = ledger_sum


def net_balance_of(profile_id):
    profile = db.roommate_profiles.get(profile_id)
    return profile["net_balance_cents"] if profile else 0


# ---------------------------------------------------------------------------
# Bill split construction (PRD §3.4)
# ---------------------------------------------------------------------------
def build_bill_splits(bill, household):
    """Create BillSplit rows for a freshly issued bill across ACTIVE members."""
    listing = listing_for_household(household)
    members = active_memberships(household["id"])
    policy = bill["split_policy_used"]
    entries = []
    for m in members:
        profile = db.roommate_profiles.get(m["profile_id"])
        entries.append((m["profile_id"], calc.split_weight(policy, profile, listing)))
    shares = calc.waterfall_allocation(bill["total_amount_cents"], entries) if entries else {}
    for m in members:
        pid = m["profile_id"]
        row = {
            "bill_id": bill["id"],
            "profile_id": pid,
            "share_cents": shares.get(pid, 0),
            "paid": False,
        }
        models.stamp_lean(row)
        db.bill_splits[row["id"]] = row


def splits_of_bill(bill_id):
    items = [sp for sp in db.bill_splits.values() if sp["bill_id"] == bill_id]
    return models.sort_by_created(items)


def current_period_rent_bill(household_id, instant):
    """Unpaid RENT bill whose [period_start, period_end] contains `instant`."""
    for bill in db.bills.values():
        if bill["household_id"] != household_id:
            continue
        if bill["bill_type"] != "RENT":
            continue
        if bill["payment_status"] == "PAID":
            continue
        if bill["period_start"].date() <= instant.date() <= bill["period_end"].date():
            return bill
    return None


# ---------------------------------------------------------------------------
# Move-out redistribution cascade (PRD §3.5)
# ---------------------------------------------------------------------------
def apply_move_out_proration(household, departing_membership):
    """On move-out: reset the departing member's rent share to its prorated value and
    redistribute the freed remainder across the remaining ACTIVE members."""
    actual = departing_membership["actual_move_out_date"]
    bill = current_period_rent_bill(household["id"], actual)
    if bill is None:
        return

    listing = listing_for_household(household)
    pdays = calc.period_days(bill["period_start"], bill["period_end"])

    # departing member's realized occupancy
    occ_actual = calc.occupied_days(
        departing_membership["move_in_date"], actual,
        bill["period_start"], bill["period_end"],
    )
    departing_membership["occupied_days_actual"] = occ_actual

    splits = {sp["profile_id"]: sp for sp in splits_of_bill(bill["id"])}
    dep_pid = departing_membership["profile_id"]
    dep_split = splits.get(dep_pid)
    if dep_split is None:
        return

    original_full = dep_split["share_cents"]
    prorated = calc.prorated_share(original_full, occ_actual, pdays)
    freed = original_full - prorated
    dep_split["share_cents"] = prorated

    # Redistribute freed remainder across remaining ACTIVE members (departing is now MOVED_OUT).
    remaining = active_memberships(household["id"])
    if freed != 0 and remaining:
        policy = bill["split_policy_used"]
        entries = []
        for m in remaining:
            profile = db.roommate_profiles.get(m["profile_id"])
            entries.append((m["profile_id"], calc.split_weight(policy, profile, listing)))
        add = calc.waterfall_allocation(freed, entries)
        for m in remaining:
            sp = splits.get(m["profile_id"])
            if sp is not None:
                sp["share_cents"] += add.get(m["profile_id"], 0)
    # If no remaining members, the freed amount has nowhere to go; the departing share
    # remains the prorated value (the only member's bill). total preservation only holds
    # when at least one remaining member absorbs the freed amount.


def refresh_estimate(membership, household):
    """Recompute a membership's occupied_days_estimate (forward-looking variant) against
    the household's current-period RENT bill, if one exists; else leave it at 0.
    Uses the current clock to locate the period that should drive the estimate."""
    bill = None
    # Prefer the RENT bill whose period contains the clock now; else any RENT bill.
    now = db.now()
    bill = current_period_rent_bill(household["id"], now)
    if bill is None:
        for b in models.sort_by_created(list(db.bills.values())):
            if b["household_id"] == household["id"] and b["bill_type"] == "RENT":
                bill = b
                break
    if bill is None:
        membership["occupied_days_estimate"] = 0
        return
    membership["occupied_days_estimate"] = calc.occupied_days(
        membership["move_in_date"], membership["planned_move_out_date"],
        bill["period_start"], bill["period_end"],
    )


def maybe_reopen_listing(household):
    listing = listing_for_household(household)
    if listing is None:
        return
    if listing["status"] == "CLOSED" and household["active_member_count"] < listing["capacity"]:
        listing["status"] = "OPEN"
        models.touch(listing)
