"""Domain logic: entity construction, derived-field reconciliation, state machines,
and the settlement cascade.

All mutations go through touch() which refreshes updated_at and bumps version, so
cascaded side effects are reflected on every affected record (PRD §2.4, §2.8).
"""
from db import db, new_id, now_iso
from services import calc

# ---------------------------------------------------------------------------
# Common-field / mutation plumbing
# ---------------------------------------------------------------------------

# Entities that carry the full common-field set (id, created_at, updated_at, version)
VERSIONED = {
    "creator", "backer", "campaign", "tier", "stretch_goal", "addon",
    "pledge", "survey",
}


def _stamp_new(rec, versioned=True):
    ts = now_iso()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["_seq"] = db.next_seq()
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation: refresh updated_at and bump version (if the record is versioned)."""
    rec["updated_at"] = now_iso()
    if "version" in rec:
        rec["version"] += 1
    return rec


# ---------------------------------------------------------------------------
# Serialization — strip internal fields (_seq, internal links) for output
# ---------------------------------------------------------------------------

_INTERNAL = {"_seq"}


def serialize(rec):
    return {k: v for k, v in rec.items() if k not in _INTERNAL}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_campaign_tiers(campaign_id):
    return [t for t in db.tiers.values() if t["campaign_id"] == campaign_id]


def get_campaign_addons(campaign_id):
    return [a for a in db.addons.values() if a["campaign_id"] == campaign_id]


def get_campaign_stretch_goals(campaign_id):
    return [s for s in db.stretch_goals.values() if s["campaign_id"] == campaign_id]


def get_campaign_pledges(campaign_id):
    return [p for p in db.pledges.values() if p["campaign_id"] == campaign_id]


def get_pledge_addon_lines(pledge_id):
    return [la for la in db.pledge_addons.values() if la["pledge_id"] == pledge_id]


def get_backer_pledges(backer_id):
    return [p for p in db.pledges.values() if p["backer_id"] == backer_id]


# ---------------------------------------------------------------------------
# pledge_total (calculations.pledge_total / PRD §3.6)
# ---------------------------------------------------------------------------

def recompute_pledge_total(pledge):
    """Recompute items_subtotal_cents, shipping_cents, committed_amount_cents."""
    lines = get_pledge_addon_lines(pledge["id"])
    tier = db.tiers.get(pledge["tier_id"])

    items_subtotal = pledge["pledge_amount_cents"]
    for la in lines:
        items_subtotal += la["line_total_cents"]

    total_weight = tier["weight_grams"] if tier else 0
    for la in lines:
        addon = db.addons.get(la["addon_id"])
        if addon:
            total_weight += la["quantity"] * addon["weight_grams"]

    ship = calc.shipping_cents(total_weight, pledge["destination_zone"])

    pledge["items_subtotal_cents"] = items_subtotal
    pledge["shipping_cents"] = ship
    pledge["committed_amount_cents"] = items_subtotal + ship


# ---------------------------------------------------------------------------
# Derived inventory: tier.claimed_quantity / addon.claimed_quantity
# (calculations.tier_claimed_quantity / addon_claimed_quantity)
# A pledge "holds" a unit iff status==ACTIVE and payment_status NOT IN
# {AUTH_DECLINED, REFUNDED}.
# ---------------------------------------------------------------------------

def _pledge_holds(pledge):
    return (pledge["status"] == "ACTIVE"
            and pledge["payment_status"] not in ("AUTH_DECLINED", "REFUNDED"))


def recompute_tier_claimed(tier):
    count = 0
    for p in db.pledges.values():
        if p["tier_id"] == tier["id"] and _pledge_holds(p):
            count += 1
    old_qty = tier.get("claimed_quantity")
    old_status = tier["status"]
    tier["claimed_quantity"] = count

    # Inventory state only cycles while not RETIRED (campaign terminal retires tiers).
    if old_status != "RETIRED":
        if tier["limit_quantity"] is not None and count >= tier["limit_quantity"]:
            new_status = "SOLD_OUT"
        else:
            new_status = "AVAILABLE"
        tier["status"] = new_status
    # Bump version/updated_at only if something actually changed.
    if tier.get("claimed_quantity") != old_qty or tier["status"] != old_status:
        touch(tier)


def recompute_addon_claimed(addon):
    total = 0
    for la in db.pledge_addons.values():
        if la["addon_id"] != addon["id"]:
            continue
        pledge = db.pledges.get(la["pledge_id"])
        if pledge and _pledge_holds(pledge):
            total += la["quantity"]
    if addon.get("claimed_quantity") != total:
        addon["claimed_quantity"] = total
        touch(addon)


def release_pledge_inventory(pledge):
    """Recompute claimed_quantity for the pledge's tier and every add-on it touched."""
    tier = db.tiers.get(pledge["tier_id"])
    if tier:
        recompute_tier_claimed(tier)
    seen = set()
    for la in get_pledge_addon_lines(pledge["id"]):
        if la["addon_id"] in seen:
            continue
        seen.add(la["addon_id"])
        addon = db.addons.get(la["addon_id"])
        if addon:
            recompute_addon_claimed(addon)


# ---------------------------------------------------------------------------
# Campaign projected/settled raise + stretch goals (calculations.projected_raise,
# settled_raise, stretch_goal_unlock)
# ---------------------------------------------------------------------------

def recompute_projected_raise(campaign):
    """committed_amount_cents = sum over ACTIVE pledges with payment_status IN
    {PENDING_AUTH, AUTHORIZED, CAPTURED}."""
    total = 0
    for p in get_campaign_pledges(campaign["id"]):
        if (p["status"] == "ACTIVE"
                and p["payment_status"] in ("PENDING_AUTH", "AUTHORIZED", "CAPTURED")):
            total += p["committed_amount_cents"]
    campaign["committed_amount_cents"] = total


def reconcile_stretch_goals(campaign):
    """unlocked flag tracks basis >= threshold (LIVE -> projected; closed -> settled)."""
    if campaign["status"] == "LIVE":
        basis = campaign["committed_amount_cents"]
    else:
        basis = campaign.get("settled_amount_cents")
    if basis is None:
        return
    for sg in get_campaign_stretch_goals(campaign["id"]):
        new_val = basis >= sg["threshold_cents"]
        if sg["unlocked"] != new_val:
            sg["unlocked"] = new_val
            touch(sg)


# ---------------------------------------------------------------------------
# Backer derived stats (calculations.backer_lifetime_contribution,
# backer_reliability_score)
# ---------------------------------------------------------------------------

def recompute_backer_stats(backer):
    pledges = get_backer_pledges(backer["id"])

    lifetime_auth = 0
    lifetime_cap = 0
    declined = 0
    good = 0
    total = 0
    for p in pledges:
        ps = p["payment_status"]
        if ps in ("AUTHORIZED", "CAPTURED"):
            lifetime_auth += p["committed_amount_cents"]
        if ps == "CAPTURED":
            lifetime_cap += p["committed_amount_cents"]
        if ps == "AUTH_DECLINED":
            declined += 1
        if ps in ("AUTHORIZED", "CAPTURED", "AUTH_DECLINED"):
            total += 1
            if ps in ("AUTHORIZED", "CAPTURED"):
                good += 1

    if total == 0:
        score = calc.BASE_SCORE
    else:
        score = calc.round_half_up_1dp((good / total) * 100)

    changed = (
        backer["lifetime_authorized_cents"] != lifetime_auth
        or backer["lifetime_captured_cents"] != lifetime_cap
        or backer["declined_auth_count"] != declined
        or backer["reliability_score"] != score
    )
    backer["lifetime_authorized_cents"] = lifetime_auth
    backer["lifetime_captured_cents"] = lifetime_cap
    backer["declined_auth_count"] = declined
    backer["reliability_score"] = score
    if changed:
        touch(backer)


# ---------------------------------------------------------------------------
# Settlement cascade (PRD §3.8–§3.9; scaffold Campaign state machine)
# ---------------------------------------------------------------------------

def settle_campaign(campaign):
    """Run LIVE -> CLOSING -> {SUCCESSFUL | FAILED} with full cascade.

    Precondition (clock >= deadline) is enforced by the caller. Increments the
    campaign version once per transition it makes (LIVE->CLOSING, then
    CLOSING->terminal).
    """
    # --- LIVE -> CLOSING : authorization replay ---
    campaign["status"] = "CLOSING"

    active_pending = [
        p for p in get_campaign_pledges(campaign["id"])
        if p["status"] == "ACTIVE" and p["payment_status"] == "PENDING_AUTH"
    ]
    # created_at ASC, ties broken by _seq (never by id)
    active_pending.sort(key=lambda p: (p["created_at"], p["_seq"]))

    settled = 0
    declined_pledges = []
    authorized_pledges = []
    touched_backers = set()

    for p in active_pending:
        auth = _latest_authorization(p["id"])
        outcome = auth["outcome"] if auth else "DECLINED"
        if outcome == "SUCCEEDED":
            p["payment_status"] = "AUTHORIZED"
            touch(p)
            settled += p["committed_amount_cents"]
            authorized_pledges.append(p)
        else:
            p["payment_status"] = "AUTH_DECLINED"
            touch(p)
            declined_pledges.append(p)
        touched_backers.add(p["backer_id"])

    # Pre-existing AUTHORIZED/CAPTURED pledges also count toward settled raise.
    for p in get_campaign_pledges(campaign["id"]):
        if p in active_pending:
            continue
        if p["payment_status"] in ("AUTHORIZED", "CAPTURED"):
            settled += p["committed_amount_cents"]

    # Declined pledges release inventory.
    for p in declined_pledges:
        release_pledge_inventory(p)

    campaign["settled_amount_cents"] = settled
    campaign["goal_met"] = settled >= campaign["funding_goal_cents"]

    # Recompute backer stats for every backer whose pledge changed status.
    for bid in touched_backers:
        backer = db.backers.get(bid)
        if backer:
            recompute_backer_stats(backer)

    # Stretch goals now track the settled basis.
    reconcile_stretch_goals(campaign)

    touch(campaign)  # version bump for LIVE->CLOSING

    # --- CLOSING -> SUCCESSFUL or FAILED ---
    funded = (campaign["funding_model"] == "FLEXIBLE"
              or (campaign["funding_model"] == "ALL_OR_NOTHING" and campaign["goal_met"]))

    if funded:
        _finalize_successful(campaign)
    else:
        _finalize_failed(campaign)


def _latest_authorization(pledge_id):
    """The authorization to consume at close. If multiple were queued, use the
    most recently created one (it snapshots the latest committed amount)."""
    auths = [a for a in db.authorizations.values() if a["pledge_id"] == pledge_id]
    if not auths:
        return None
    auths.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return auths[-1]


def _finalize_successful(campaign):
    campaign["status"] = "SUCCESSFUL"
    touched_backers = set()

    for p in get_campaign_pledges(campaign["id"]):
        if p["payment_status"] == "AUTHORIZED":
            p["payment_status"] = "CAPTURED"
            # fulfillment: NOT_STARTED -> SURVEY_SENT + survey row
            if p["fulfillment_status"] == "NOT_STARTED":
                p["fulfillment_status"] = "SURVEY_SENT"
                _create_survey(p)
            touch(p)
            touched_backers.add(p["backer_id"])

    for bid in touched_backers:
        backer = db.backers.get(bid)
        if backer:
            recompute_backer_stats(backer)

    _retire_tiers(campaign)
    touch(campaign)  # version bump for CLOSING->SUCCESSFUL


def _finalize_failed(campaign):
    campaign["status"] = "FAILED"
    refunded = []

    for p in get_campaign_pledges(campaign["id"]):
        if p["payment_status"] == "AUTHORIZED":
            p["payment_status"] = "REFUNDED"
            _create_refund(p, "FAILED_CAMPAIGN", p["committed_amount_cents"])
            touch(p)
            refunded.append(p)

    # Each refunded pledge releases tier + add-on inventory (depth-3 cascade).
    for p in refunded:
        release_pledge_inventory(p)

    _retire_tiers(campaign)
    touch(campaign)  # version bump for CLOSING->FAILED


def _retire_tiers(campaign):
    for tier in get_campaign_tiers(campaign["id"]):
        if tier["status"] != "RETIRED":
            tier["status"] = "RETIRED"
            touch(tier)


# ---------------------------------------------------------------------------
# Event-record constructors
# ---------------------------------------------------------------------------

def _create_survey(pledge):
    survey = {
        "pledge_id": pledge["id"],
        "shipping_address": None,
        "completed": False,
    }
    _stamp_new(survey, versioned=True)
    db.surveys[survey["id"]] = survey
    return survey


def _create_refund(pledge, reason, amount):
    refund = {
        "pledge_id": pledge["id"],
        "reason": reason,
        "amount_cents": amount,
    }
    _stamp_new(refund, versioned=False)
    db.refunds[refund["id"]] = refund
    return refund


# ---------------------------------------------------------------------------
# Campaign cancel cascade (PRD §3.10)
# ---------------------------------------------------------------------------

def cancel_campaign(campaign):
    touched_backers = set()
    for p in get_campaign_pledges(campaign["id"]):
        if p["status"] != "ACTIVE":
            continue
        if p["payment_status"] == "AUTHORIZED":
            p["payment_status"] = "REFUNDED"
            _create_refund(p, "FAILED_CAMPAIGN", p["committed_amount_cents"])
            p["status"] = "CANCELED"
            touch(p)
            touched_backers.add(p["backer_id"])
        elif p["payment_status"] == "PENDING_AUTH":
            # simply voided
            p["status"] = "CANCELED"
            touch(p)
            touched_backers.add(p["backer_id"])

    campaign["status"] = "CANCELED"

    # Release all tier + add-on inventory (canceled pledges no longer hold).
    for tier in get_campaign_tiers(campaign["id"]):
        recompute_tier_claimed(tier)
    for addon in get_campaign_addons(campaign["id"]):
        recompute_addon_claimed(addon)

    _retire_tiers(campaign)

    for bid in touched_backers:
        backer = db.backers.get(bid)
        if backer:
            recompute_backer_stats(backer)

    touch(campaign)
