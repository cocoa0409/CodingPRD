"""Charge / wallet / pending-payout mechanics + derived-field recompute.

Implements the money side effects from PRD §3.5, §3.7, and the derived
balances/counters in §2.4, §2.9. Every derived-field adjustment is a mutation:
it bumps updated_at + version on the owning resource (PRD §2.4).
"""
from db import db, iso_millis
from services import calc
from services.common import init_common, touch


def recompute_active_pledge_count(tier):
    """Tier.active_pledge_count = count of pledges on tier with
    lifecycle_status IN {ACTIVE, PAUSED} (calc active_pledge_count, PRD §2.4).

    Recomputing this derived field bumps the tier's version + updated_at.
    """
    count = 0
    for p in db.pledges.values():
        if p["tier_id"] == tier["id"] and p["lifecycle_status"] in ("ACTIVE", "PAUSED"):
            count += 1
    if tier["active_pledge_count"] != count:
        tier["active_pledge_count"] = count
        touch(tier)
    else:
        # PRD §2.4: adjusting a derived field is a mutation. The count is
        # recomputed as part of an operation that changed membership, so the
        # value will have changed in practice; only touch when it changed to
        # avoid spurious version bumps on no-op recomputes.
        pass


def adjust_pending_payout(creator, delta):
    """Incrementally maintain Creator.pending_payout_cents (calc
    creator_pending_payout, PRD §3.7). Bumps creator version + updated_at."""
    creator["pending_payout_cents"] = creator.get("pending_payout_cents", 0) + delta
    touch(creator)


def apply_wallet_to_charge(patron, gross_amount_cents):
    """At charge creation, apply wallet credit against gross (PRD §3.5).

    wallet_applied = min(wallet_credit, gross), bounded [0, gross].
    net = gross - wallet_applied.
    Consuming wallet credit reduces the patron's balance (a mutation).
    Returns (wallet_applied, net).
    """
    wallet = patron.get("wallet_credit_cents", 0)
    wallet_applied = max(0, min(wallet, gross_amount_cents))
    net = gross_amount_cents - wallet_applied
    if wallet_applied > 0:
        patron["wallet_credit_cents"] = wallet - wallet_applied
        touch(patron)
    return wallet_applied, net


def create_charge(pledge, creator, patron, charge_kind, gross_amount_cents, cycle_anchor_dt):
    """Mint a PENDING Charge against a pledge (PRD §3.5).

    Denormalizes creator_id from the pledge, records cycle_anchor_date, applies
    wallet credit to compute net, starts PENDING.
    """
    wallet_applied, net = apply_wallet_to_charge(patron, gross_amount_cents)
    rec = init_common({
        "pledge_id": pledge["id"],
        "creator_id": creator["id"],
        "charge_kind": charge_kind,
        "cycle_anchor_date": iso_millis(cycle_anchor_dt),
        "gross_amount_cents": gross_amount_cents,
        "wallet_applied_cents": wallet_applied,
        "net_amount_cents": net,
        "processing_fee_cents": 0,
        "status": "PENDING",
        "swept_into_payout_id": None,
    })
    db.charges[rec["id"]] = rec
    return rec


def is_first_charge(pledge, settling_charge):
    """True if settling_charge is the pledge's first-ever charge to settle the
    pledge from DRAFT to ACTIVE (PRD §3.2, §3.5). We treat it as first-charge
    activation when the pledge is currently DRAFT."""
    return pledge["lifecycle_status"] == "DRAFT"


def settle_succeeded(charge, pledge, creator, patron):
    """Charge PENDING->SUCCEEDED side effects (PRD §3.5, §3.7, SCAFFOLD §1.2).

    - processing_fee computed and stored (calc processing_fee)
    - pledge.current_cycle_charged_cents += gross
    - creator.pending_payout_cents += net (calc creator_pending_payout)
    - first charge -> pledge DRAFT->ACTIVE (+ active_pledge_count, anchor set)
    - GRACE -> CURRENT if applicable
    """
    charge["status"] = "SUCCEEDED"
    charge["processing_fee_cents"] = calc.processing_fee(charge["net_amount_cents"])
    touch(charge)

    # pledge cycle running total
    first = is_first_charge(pledge, charge)
    if first:
        # First successful charge activates the pledge: cycle_anchor_date is
        # established and current_cycle_charged_cents is SET to the settled
        # charge amount (PRD §3.2).
        pledge["lifecycle_status"] = "ACTIVE"
        pledge["cycle_anchor_date"] = charge["cycle_anchor_date"]
        pledge["current_cycle_charged_cents"] = charge["gross_amount_cents"]
        touch(pledge)
        tier = db.tiers.get(pledge["tier_id"])
        if tier is not None:
            recompute_active_pledge_count(tier)
    else:
        pledge["current_cycle_charged_cents"] = \
            pledge.get("current_cycle_charged_cents", 0) + charge["gross_amount_cents"]
        touch(pledge)
        # GRACE -> CURRENT: a successful settle while in GRACE restores standing
        # (PRD §3.3). The grace_deadline check is enforced by the caller path;
        # per PRD §3.3 "if a charge settles SUCCEEDED before the grace_deadline".
        if pledge["billing_status"] == "GRACE":
            if _grace_still_open(pledge):
                pledge["billing_status"] = "CURRENT"
                pledge["grace_deadline"] = None
                touch(pledge)

    # creator pending payout
    adjust_pending_payout(creator, charge["net_amount_cents"])


def _grace_still_open(pledge):
    """True if the grace window has not yet elapsed (PRD §3.3)."""
    from db import db as _db
    from datetime import datetime, timezone
    deadline = pledge.get("grace_deadline")
    if deadline is None:
        return True
    dl = _parse_iso(deadline)
    return _db.now() <= dl


def _parse_iso(s):
    from datetime import datetime, timezone
    if s is None:
        return None
    txt = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def settle_failed(charge, pledge, creator, patron):
    """Charge PENDING->FAILED side effects (PRD §3.5, §3.3, SCAFFOLD §1.2).

    - wallet_applied refunded to patron.wallet_credit_cents (conserved)
    - drives pledge billing axis CURRENT->PAST_DUE->GRACE per retry
      (only for CYCLE_RENEWAL / PER_CREATION failures per PRD §3.3)
    - a failed FIRST charge leaves the pledge DRAFT with billing_status PAST_DUE
      (PRD §3.2)
    """
    charge["status"] = "FAILED"
    touch(charge)

    # Conserve wallet: refund the consumed credit (PRD §3.5).
    if charge["wallet_applied_cents"] > 0:
        patron["wallet_credit_cents"] = \
            patron.get("wallet_credit_cents", 0) + charge["wallet_applied_cents"]
        touch(patron)

    # Billing axis advance.
    if pledge["lifecycle_status"] == "DRAFT":
        # First charge failed: pledge stays DRAFT, billing_status -> PAST_DUE
        # (PRD §3.2).
        if pledge["billing_status"] == "CURRENT":
            pledge["billing_status"] = "PAST_DUE"
            touch(pledge)
        return

    # For renewal / per-creation failures the billing axis advances
    # CURRENT->PAST_DUE->GRACE (PRD §3.3).
    if charge["charge_kind"] in ("CYCLE_RENEWAL", "PER_CREATION"):
        if pledge["billing_status"] == "CURRENT":
            pledge["billing_status"] = "PAST_DUE"
            touch(pledge)
        elif pledge["billing_status"] == "PAST_DUE":
            pledge["billing_status"] = "GRACE"
            pledge["grace_deadline"] = iso_millis(calc.grace_deadline(db.now()))
            touch(pledge)


def refund_charge(charge, pledge, creator, patron):
    """Charge SUCCEEDED->REFUNDED side effects (PRD §3.5, SCAFFOLD §1.2).

    - net_amount_cents returned to patron.wallet_credit_cents
    - creator.pending_payout_cents -= net (conserved)
    - pledge.current_cycle_charged_cents -= gross
    """
    charge["status"] = "REFUNDED"
    touch(charge)

    patron["wallet_credit_cents"] = \
        patron.get("wallet_credit_cents", 0) + charge["net_amount_cents"]
    touch(patron)

    adjust_pending_payout(creator, -charge["net_amount_cents"])

    pledge["current_cycle_charged_cents"] = \
        pledge.get("current_cycle_charged_cents", 0) - charge["gross_amount_cents"]
    touch(pledge)
