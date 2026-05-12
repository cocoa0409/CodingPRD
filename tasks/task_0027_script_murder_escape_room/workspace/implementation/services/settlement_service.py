"""Settlement run creation, finalize, reversal."""
from db import store, bump
from errors import (
    raise_error,
    ERR_REVENUE_SPLIT_INVALID, ERR_SETTLEMENT_HAS_OPEN_SESSIONS,
    ERR_SETTLEMENT_CHAIN_MISMATCH,
)
from audit import write_audit


def compute_payouts(included_session_ids: list[str]) -> dict:
    """Returns {gross_total, author_payout, host_payout, venue_payout, platform_fee, per_session: list}."""
    author_total = 0
    host_total = 0
    venue_total = 0
    platform_total = 0
    gross_total = 0
    per_session = []

    for sid in included_session_ids:
        slot = store.session_slots.get(sid)
        if not slot:
            continue
        net_S = max(0, slot.get("net_revenue_cents", 0))
        gross_total += slot.get("net_revenue_cents", 0)

        venue = store.venues[slot["venue_id"]]
        theme = store.themes[slot["theme_id"]]

        # Author bps
        if theme.get("author_royalty_bps_override") is not None:
            author_bps = int(theme["author_royalty_bps_override"])
        else:
            author_bps = int(venue["author_royalty_bps"])

        # Host bps: pick HOST StaffAssignment in COMPLETED, ordered by created_at ASC, take first
        completed_hosts = [a for a in store.staff_assignments.values()
                           if a["slot_id"] == sid and a["role_type"] == "HOST"
                           and a["status"] == "COMPLETED"]
        completed_hosts.sort(key=lambda a: (a["created_at"], a["id"]))
        host_bps = 0
        if completed_hosts:
            chosen = completed_hosts[0]
            sm = store.staff_members.get(chosen["staff_member_id"])
            if sm and sm.get("commission_bps_override") is not None:
                host_bps = int(sm["commission_bps_override"])
            else:
                host_bps = int(venue["host_commission_bps"])

        platform_bps_default = int(venue["platform_fee_bps"])
        # Venue bps = max(0, 10000 - author - host - platform)
        venue_bps = 10000 - author_bps - host_bps - platform_bps_default
        if venue_bps < 0:
            raise_error(ERR_REVENUE_SPLIT_INVALID, "negative venue residual after overrides")
        # Per-session split (floor)
        author_S = (net_S * author_bps) // 10000
        host_S = (net_S * host_bps) // 10000
        venue_S = (net_S * venue_bps) // 10000
        platform_S = net_S - author_S - host_S - venue_S
        # platform_S must absorb residue (>=0)
        author_total += author_S
        host_total += host_S
        venue_total += venue_S
        platform_total += platform_S

        per_session.append({
            "session_id": sid,
            "net_S": net_S,
            "author_S": author_S,
            "host_S": host_S,
            "venue_S": venue_S,
            "platform_S": platform_S,
        })

    return {
        "gross_total_cents": gross_total,
        "author_payout_cents": author_total,
        "host_payout_cents": host_total,
        "venue_payout_cents": venue_total,
        "platform_fee_cents": platform_total,
        "per_session": per_session,
    }


def sweep_included_sessions(chain_id: str, period_starts_at_dt, period_ends_at_dt) -> list[str]:
    from db import parse_iso
    sids = []
    for slot in store.session_slots.values():
        if slot["schedule_status"] != "COMPLETED":
            continue
        venue = store.venues.get(slot["venue_id"])
        if not venue:
            continue
        if venue["chain_id"] != chain_id:
            continue
        ends_at = parse_iso(slot["ends_at"])
        if period_starts_at_dt <= ends_at < period_ends_at_dt:
            sids.append(slot["id"])
    sids.sort(key=lambda s: store.session_slots[s]["created_at"])
    return sids


def reverse_run_if_covers_slot(slot_id: str, actor_user_id: str, actor_role: str):
    """If any FINALIZED settlement run covers this slot, flip to REVERSED with recomputed payouts."""
    for run in store.settlement_runs.values():
        if run["status"] != "FINALIZED":
            continue
        if slot_id not in (run.get("included_session_ids") or []):
            continue
        # Recompute and flip
        payouts = compute_payouts(run["included_session_ids"])
        run["gross_total_cents"] = payouts["gross_total_cents"]
        run["author_payout_cents"] = payouts["author_payout_cents"]
        run["host_payout_cents"] = payouts["host_payout_cents"]
        run["venue_payout_cents"] = payouts["venue_payout_cents"]
        run["platform_fee_cents"] = payouts["platform_fee_cents"]
        run["status"] = "REVERSED"
        bump(run)
        write_audit(actor_user_id, actor_role, "SettlementRun", run["id"],
                    "SETTLEMENT_REVERSED", run)


def validate_revenue_split_for_finalize(included_session_ids: list[str], run_chain_id: str):
    venues_seen = set()
    for sid in included_session_ids:
        slot = store.session_slots.get(sid)
        if not slot:
            continue
        venue = store.venues.get(slot["venue_id"])
        if not venue:
            continue
        if venue["chain_id"] != run_chain_id:
            raise_error(ERR_SETTLEMENT_CHAIN_MISMATCH, "venue chain mismatch")
        if venue["id"] in venues_seen:
            continue
        venues_seen.add(venue["id"])
        s = (int(venue["revenue_share_bps"]) + int(venue["author_royalty_bps"]) +
             int(venue["host_commission_bps"]) + int(venue["platform_fee_bps"]))
        if s != 10000:
            raise_error(ERR_REVENUE_SPLIT_INVALID, "venue bps sum != 10000")


def all_included_completed(included_session_ids: list[str]) -> bool:
    for sid in included_session_ids:
        slot = store.session_slots.get(sid)
        if not slot:
            return False
        if slot["schedule_status"] != "COMPLETED":
            return False
    return True
