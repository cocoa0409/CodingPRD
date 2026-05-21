"""Sweep operations: expirations, promotion, annual rollover."""

from __future__ import annotations

from typing import Optional

from ..store import store, new_uuid
from ..timeutil import clock, add_months
from .common import bump_version
from .serialize import compute_upgrade_inventory, compute_points_balance, compute_qualifying_ytd
from . import calc, ledger
from . import tier as tier_svc
from .upgrades import recompute_member_waitlist


# -----------------------------------------------------------------------------
# Points expiration sweep.
# -----------------------------------------------------------------------------

def sweep_expire_points() -> int:
    now = clock.now()
    # Iterate ACCRUAL rows FIFO by posted_at ascending then id ascending.
    accruals = [
        t for t in store.points_transactions.values()
        if t["kind"] == "ACCRUAL"
        and t.get("expires_at") is not None
        and t["expires_at"] <= now
        and t.get("remaining_unredeemed", 0) and t["remaining_unredeemed"] > 0
    ]
    accruals.sort(key=lambda t: (t["posted_at"], t["id"]))
    count = 0
    for t in accruals:
        amt = t["remaining_unredeemed"]
        if amt <= 0:
            continue
        ledger.append(
            member_id=t["member_id"],
            kind="EXPIRATION",
            points_delta=-amt,
            posted_at=now,
            related_segment_id=t.get("related_segment_id"),
            now=now,
        )
        # The ledger.append above already calls consume_buckets which would decrement
        # remaining_unredeemed of the bucket. But to be sure, explicitly zero this row.
        t["remaining_unredeemed"] = 0
        count += 1
        # Bump member's updated_at (audit)
        m = store.members.get(t["member_id"])
        if m:
            bump_version(m, now)
    return count


# -----------------------------------------------------------------------------
# Award booking expiration sweep.
# -----------------------------------------------------------------------------

def sweep_expire_bookings() -> int:
    now = clock.now()
    count = 0
    for b in list(store.award_bookings.values()):
        if b["status"] != "HELD":
            continue
        if b["held_until"] > now:
            continue
        b["status"] = "EXPIRED"
        bump_version(b, now)
        count += 1
        cert_id = b.get("companion_certificate_id")
        if cert_id:
            cert = store.companion_certificates.get(cert_id)
            if cert and cert["status"] == "RESERVED":
                if now < cert["expires_at"]:
                    cert["status"] = "ACTIVE"
                    cert["reserved_for_booking_id"] = None
                    bump_version(cert, now)
                # else: leave it as-is; will be picked up by certificate sweep
    return count


# -----------------------------------------------------------------------------
# Certificate expiration sweep.
# -----------------------------------------------------------------------------

def sweep_expire_certificates() -> int:
    now = clock.now()
    count = 0
    for c in list(store.companion_certificates.values()):
        if c["status"] not in ("ACTIVE", "RESERVED"):
            continue
        if c["expires_at"] > now:
            continue
        c["status"] = "EXPIRED"
        bump_version(c, now)
        count += 1
    return count


# -----------------------------------------------------------------------------
# Status-match expiration sweep.
# -----------------------------------------------------------------------------

def sweep_expire_status_matches() -> int:
    now = clock.now()
    count = 0
    for r in list(store.status_match_requests.values()):
        if r["status"] != "ACTIVE":
            continue
        if r.get("expires_at") is None or r["expires_at"] > now:
            continue
        r["status"] = "EXPIRED"
        bump_version(r, now)
        count += 1
        # Revert member tier toward EARNED default (BASIC) if still STATUS_MATCH-sourced.
        m = store.members.get(r["member_id"])
        if m and m["tier_source"] == "STATUS_MATCH":
            m["tier"] = "BASIC"
            m["tier_source"] = "EARNED"
            bump_version(m, now)
            recompute_member_waitlist(r["member_id"], m["tier"], lambda res: bump_version(res, now))
    return count


# -----------------------------------------------------------------------------
# Upgrade promotion sweep.
# -----------------------------------------------------------------------------

def promote_upgrades_for_flight(flight_id: str) -> int:
    """Resolve waitlists for every cabin of *flight_id*. Returns promoted count."""
    flight = store.flights.get(flight_id)
    if not flight:
        return 0
    now = clock.now()
    promoted = 0
    for cabin in ("BUSINESS", "FIRST"):
        # Build candidates list
        candidates = [
            u for u in store.upgrade_requests.values()
            if u["flight_id"] == flight_id
            and u["status"] == "WAITLISTED"
            and u["target_cabin"] == cabin
        ]
        # Refresh priority_score on each candidate against current member tier
        for u in candidates:
            m = store.members.get(u["member_id"])
            if m is None:
                continue
            u["priority_score"] = calc.priority_score(
                m["tier"], u["points_offered"], u["waitlist_join_seq"]
            )
        # Sort by priority_score DESC then waitlist_join_seq ASC
        candidates.sort(key=lambda u: (-u["priority_score"], u["waitlist_join_seq"]))
        for u in candidates:
            inv = compute_upgrade_inventory(flight, cabin)
            if inv <= 0:
                break
            m = store.members.get(u["member_id"])
            if m is None:
                continue
            if not tier_svc.at_least(m["tier"], "GOLD"):
                continue
            bal = compute_points_balance(m["id"], now)
            if bal < u["points_offered"]:
                continue
            # Confirm
            ledger.append(
                member_id=m["id"],
                kind="REDEMPTION",
                points_delta=-u["points_offered"],
                posted_at=now,
                related_segment_id=u["flight_segment_id"],
                now=now,
            )
            u["status"] = "CONFIRMED"
            u["held_points"] = u["points_offered"]
            bump_version(u, now)
            m["last_activity_at"] = now
            bump_version(m, now)
            promoted += 1
    # If flight has departed, deny remaining waitlisted on this flight
    if flight["status"] == "DEPARTED":
        for u in store.upgrade_requests.values():
            if u["flight_id"] != flight_id or u["status"] != "WAITLISTED":
                continue
            u["status"] = "DENIED"
            u["held_points"] = 0
            bump_version(u, now)
    return promoted


def sweep_promote_upgrades(flight_id: Optional[str] = None) -> int:
    total = 0
    if flight_id is not None:
        return promote_upgrades_for_flight(flight_id)
    for fid in list(store.flights.keys()):
        total += promote_upgrades_for_flight(fid)
    return total


# -----------------------------------------------------------------------------
# Annual rollover sweep.
# -----------------------------------------------------------------------------

def sweep_annual_rollover(target_year: int) -> int:
    now = clock.now()
    rolled = 0
    for m in list(store.members.values()):
        qs, qp = compute_qualifying_ytd(m["id"], target_year)
        starting_tier = m["tier"]
        awarded = tier_svc.awarded_tier(qs, qp)
        # Snapshot
        sid = new_uuid()
        snap = {
            "id": sid,
            "member_id": m["id"],
            "year": target_year,
            "qualifying_segments_final": qs,
            "qualifying_points_final": qp,
            "starting_tier": starting_tier,
            "awarded_tier": awarded,
            "created_at": now,
        }
        store.membership_years[sid] = snap
        prior_tier = m["tier"]
        prior_source = m["tier_source"]
        m["tier"] = awarded
        m["tier_source"] = "EARNED"
        m["tier_valid_through_year"] = target_year
        # PRD §3.1: "The two year-scoped counters are reset to zero."
        # We mark the reset instant; compute_qualifying_ytd excludes any
        # segment whose FLOWN commit happened on or before this instant.
        m["qualifying_counter_reset_at"] = now
        bump_version(m, now)
        # If awarded PLATINUM and this is via EARNED path (not status match) — auto-issue cert.
        if awarded == "PLATINUM":
            cid = new_uuid()
            cert = {
                "id": cid,
                "member_id": m["id"],
                "status": "ACTIVE",
                "issued_at": now,
                "expires_at": add_months(now, 12),
                "reserved_for_booking_id": None,
                "used_on_booking_id": None,
                "issued_reason": "TIER_REACHED_PLATINUM",
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }
            store.companion_certificates[cid] = cert
        # Recompute WAITLISTED upgrade priority_score for this member
        recompute_member_waitlist(m["id"], m["tier"], lambda res: bump_version(res, now))
        rolled += 1
    return rolled
