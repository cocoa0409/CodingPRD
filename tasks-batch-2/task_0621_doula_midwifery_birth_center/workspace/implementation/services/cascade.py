"""Cross-aggregate cascades and helpers shared by the state-machine routes."""
from db import db
from common import touch, stamp_new
from services import calc


def episode_global_charge(episode):
    for ch in db.charges.values():
        if ch["episode_id"] == episode["id"] and ch["charge_kind"] == "GLOBAL_FEE":
            return ch
    return None


def episode_active_booking(episode, statuses):
    """Return the episode's booking whose status is in `statuses` (first found)."""
    for b in db.bookings.values():
        if b["episode_id"] == episode["id"] and b["status"] in statuses:
            return b
    return None


def episode_in_use_booking(episode):
    return episode_active_booking(episode, ("IN_USE",))


def episode_primary_assignment(episode, statuses):
    for a in db.on_call_assignments.values():
        if (a["episode_id"] == episode["id"]
                and a["coverage_role"] == "PRIMARY"
                and a["status"] in statuses):
            return a
    return None


# ---------------------------------------------------------------------------
# Claim adjudication / denial / void recompute cascade (§3.6)
# ---------------------------------------------------------------------------
def recompute_after_claim_change(episode):
    """Recompute GLOBAL_FEE charge responsibility + episode balance, bump episode
    version once (the PRD treats the whole claim cascade as one episode mutation)."""
    calc.recompute_global_charge(episode)
    calc.rederive_balance(episode)
    touch(episode)


# ---------------------------------------------------------------------------
# Transfer cascade (§3.8)
# ---------------------------------------------------------------------------
def transfer_cascade(episode):
    """Fire the coordinated cascades of a hospital transfer. The episode's
    clinical_status is set to TRANSFERRED and its version bumped by the caller."""
    # 1. Active room booking HELD/CONFIRMED/IN_USE -> TRANSFERRED.
    booking = episode_active_booking(episode, ("HELD", "CONFIRMED", "IN_USE"))
    if booking is not None:
        booking["status"] = "TRANSFERRED"
        touch(booking)
        # release room interval immediately (implicit — terminal booking no
        # longer occupies the room); create the TRANSFER_FEE charge.
        _create_transfer_fee_charge(episode)

    # 2. Primary OnCallAssignment in {ASSIGNED, ON_DUTY} -> STOOD_DOWN.
    primary = episode_primary_assignment(episode, ("ASSIGNED", "ON_DUTY"))
    if primary is not None:
        primary["status"] = "STOOD_DOWN"
        touch(primary)
        prov = db.providers.get(primary["provider_id"])
        if prov is not None:
            prov["active_assignment_count"] = max(0, prov["active_assignment_count"] - 1)
            touch(prov)
        # promote a named backup, if any.
        backup_id = primary.get("backup_assignment_id")
        if backup_id:
            backup = db.on_call_assignments.get(backup_id)
            if (backup is not None and backup["coverage_role"] == "BACKUP"
                    and backup["status"] == "ASSIGNED"):
                backup["status"] = "PROMOTED"
                touch(backup)
                bprov = db.providers.get(backup["provider_id"])
                if bprov is not None:
                    bprov["active_assignment_count"] += 1
                    touch(bprov)

    # 3. Kit reserved unit treated as consumed (recompute counters after the
    #    episode clinical_status has been flipped to TRANSFERRED).
    _reconcile_episode_kit(episode)


def _create_transfer_fee_charge(episode):
    charge = {
        "episode_id": episode["id"],
        "claim_id": "",
        "charge_kind": "TRANSFER_FEE",
        "amount_cents": calc.TRANSFER_FEE_CENTS,
        "client_responsibility_cents": calc.TRANSFER_FEE_CENTS,
        "status": "DRAFT",
    }
    stamp_new(charge)
    db.charges[charge["id"]] = charge
    # transfer fee adds to balance; re-derive (the episode version bump is the
    # single transfer bump applied by the caller, so do not double-bump here).
    calc.rederive_balance(episode)
    return charge


# ---------------------------------------------------------------------------
# Record-birth cascade (§3.2)
# ---------------------------------------------------------------------------
def record_birth_cascade(episode):
    booking = episode_in_use_booking(episode)
    if booking is not None:
        booking["status"] = "COMPLETED"
        touch(booking)
    # Kit reserved unit consumed (recompute after clinical_status flip to BORN).
    _reconcile_episode_kit(episode)
    # GLOBAL_FEE charge in DRAFT becomes billable (remains DRAFT; billing is a
    # separate explicit BillingClerk action). No status change required here.


# ---------------------------------------------------------------------------
# Write-off cascade (§3.11)
# ---------------------------------------------------------------------------
def write_off_cascade(episode):
    # Cancel the OPEN payment plan if one exists.
    for p in db.payment_plans.values():
        if p["episode_id"] == episode["id"] and p["status"] == "OPEN":
            p["status"] = "CANCELLED"
            touch(p)
    # Void every DRAFT/BILLED charge on the episode.
    for ch in db.charges.values():
        if ch["episode_id"] == episode["id"] and ch["status"] in ("DRAFT", "BILLED"):
            ch["status"] = "VOID"
            touch(ch)
    # No kit movement on write-off (§3.11).


# ---------------------------------------------------------------------------
# Payment settlement cascade (§3.10)
# ---------------------------------------------------------------------------
def settle_cascade(episode):
    """PLAN_ACTIVE -> SETTLED: mark all BILLED charges PAID."""
    episode["financial_status"] = "SETTLED"
    for ch in db.charges.values():
        if ch["episode_id"] == episode["id"] and ch["status"] == "BILLED":
            ch["status"] = "PAID"
            touch(ch)
    touch(episode)


# ---------------------------------------------------------------------------
# Kit reconciliation helper
# ---------------------------------------------------------------------------
def _reconcile_episode_kit(episode):
    sku = episode.get("_kit_sku")
    if not sku:
        return
    kit = db.supply_kits.get(sku)
    if kit is not None and calc.reconcile_kit(kit):
        touch(kit)
