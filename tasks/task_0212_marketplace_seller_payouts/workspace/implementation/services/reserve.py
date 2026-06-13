"""Reserve service: pct selection by risk tier, release.

PRD §3.9, §3.10, §2.6.

Reserve accounting model (derived from the literal PRD §2.6 formula and the
pinned numeric assertions in the design indices):

  available_balance_cents = sum(AVAILABLE ledger amounts) - reserve_held_cents
  reserve_held_cents      = sum of held_amount_cents over the seller's OPEN reserves

The RESERVE_HOLD / RESERVE_RELEASE ledger entries are immutable AUDIT records of
the reserve movement; the reserve's effect on available flows ONLY through
reserve_held_cents (the mirror of the open reserve). To avoid double-counting,
these audit entries are posted in REVERSED hold_state so they never enter the
AVAILABLE or PENDING sums. This reproduces the pinned results: an ELEVATED
release of a 6630 pool yields reserve_held_cents 1326 and available 0; a
STANDARD release yields available 0; a release-then-reverse nets available to
its pre-release value.
"""
from db import db
from services.entity import touch
from services.ledger import post_ledger_entry, HOLD_REVERSED


def active_schedule_any():
    """Return the active fee schedule used for reserve pcts (PRD §3.9).

    Uses the most-recently-active schedule across categories. Returns None when
    no schedule exists."""
    actives = [s for s in db.fee_schedules.values() if s.get("is_active")]
    if not actives:
        return None
    return sorted(actives, key=lambda s: (s["created_at"], s["id"]))[-1]


def reserve_pct_for_tier(seller):
    """Select reserve percentage from the active schedule by seller.risk_tier
    (PRD §3.9). Returns 0 when no active schedule exists."""
    schedule = active_schedule_any()
    if schedule is None:
        return 0
    tier = seller["risk_tier"]
    if tier == "STANDARD":
        return schedule["reserve_pct_standard"]
    if tier == "ELEVATED":
        return schedule["reserve_pct_elevated"]
    return schedule["reserve_pct_high"]


def open_or_extend_reserve(seller, amount_cents, reserve_pct, source_id):
    """Withhold `amount_cents` into the seller's reserve (PRD §3.9 release).

    Opens a fresh OPEN reserve row (pinning reserve_pct_applied) holding the
    withheld amount, and posts a RESERVE_HOLD audit ledger entry. Returns the
    reserve row."""
    from services.entity import stamp_create
    reserve = {
        "seller_id": seller["id"],
        "reserve_status": "OPEN",
        "held_amount_cents": amount_cents,
        "reserve_pct_applied": reserve_pct,
        "release_due_at": None,
        "released_at": None,
    }
    stamp_create(reserve)
    db.reserves[reserve["id"]] = reserve
    post_ledger_entry(
        seller_id=seller["id"],
        source_type="RESERVE_HOLD",
        source_id=source_id,
        amount_cents=-amount_cents,
        hold_state=HOLD_REVERSED,
        memo="Reserve hold",
    )
    return reserve


def release_reserve_row(seller, reserve, source_id=None):
    """Move a reserve OPEN->RELEASED and post a RESERVE_RELEASE audit entry for
    the previously-held amount (PRD §3.2 close cascade, §3.9 reverse, §3.10
    clock sweep). Clearing held_amount_cents removes its hold from available."""
    held = reserve["held_amount_cents"]
    post_ledger_entry(
        seller_id=seller["id"],
        source_type="RESERVE_RELEASE",
        source_id=source_id if source_id is not None else reserve["id"],
        amount_cents=held,
        hold_state=HOLD_REVERSED,
        memo="Reserve release",
    )
    reserve["reserve_status"] = "RELEASED"
    reserve["released_at"] = db.now_iso()
    reserve["held_amount_cents"] = 0
    touch(reserve)
