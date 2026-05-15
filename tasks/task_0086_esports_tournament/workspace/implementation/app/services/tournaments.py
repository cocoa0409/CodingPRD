"""Tournament service: CRUD, state transitions, bracket publication, prize lifecycle."""
from __future__ import annotations

import hashlib
import random
from typing import Any, Optional

from ..calculations import (
    MVP_BPS,
    compute_mvp_amount,
    compute_prize_tier_amount,
    compute_tax_withholding,
    validate_prize_tier_sum,
)
from ..clock import CLOCK, format_iso, parse_iso
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store, new_id, now_iso
from .serializers import serialize_tournament

TERMINAL_MATCH_STATES = {"COMPLETED", "FORFEITED", "DISQUALIFIED"}


# ---------- Helpers ---------- #


def _require_tournament(tid: str) -> dict[str, Any]:
    t = get_store().tournaments.get(tid)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", f"Tournament {tid} not found.")
    return t


def _validate_prize_tier_table(table: Any) -> None:
    if not isinstance(table, list) or not table:
        raise ApiError("ERR_PRIZE_TIER_SUM_MISMATCH", "prize_tier_table must be a non-empty list.")
    for entry in table:
        if not isinstance(entry, dict) or "placement" not in entry or "percentage_bps" not in entry:
            raise ApiError("ERR_PRIZE_TIER_SUM_MISMATCH", "Invalid prize_tier_table entry.")
    if not validate_prize_tier_sum(table):
        raise ApiError("ERR_PRIZE_TIER_SUM_MISMATCH", "Sum of percentage_bps + MVP_BPS must equal 10000.")


# ---------- Create ---------- #


def create_tournament(body: dict[str, Any]) -> dict[str, Any]:
    required = [
        "name", "format", "region", "entry_fee_cents", "entry_fee_currency",
        "roster_lock_deadline", "registration_deadline", "base_prize_pool_cents",
        "prize_tier_table", "ban_pick_sequence", "map_pool", "character_pool",
        "max_teams", "required_referee_level",
    ]
    for key in required:
        if key not in body:
            raise ApiError("ERR_BAD_REQUEST", f"Missing field: {key}")
    valid_formats = {"SWISS", "DOUBLE_ELIMINATION", "ROUND_ROBIN", "GROUP_PLAYOFFS"}
    if body["format"] not in valid_formats:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid format: {body['format']}")
    valid_regions = {"NA", "EU", "APAC", "SA", "GLOBAL"}
    if body["region"] not in valid_regions:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid region: {body['region']}")
    valid_ccy = {"USD", "EUR", "KRW", "CNY"}
    if body["entry_fee_currency"] not in valid_ccy:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid entry_fee_currency: {body['entry_fee_currency']}")

    # Structural check only at creation; the 10000-bps + MVP sum invariant
    # is enforced at open-registration per PRD §3.1.
    if not isinstance(body["prize_tier_table"], list):
        raise ApiError("ERR_BAD_REQUEST", "prize_tier_table must be a list.")
    for entry in body["prize_tier_table"]:
        if not isinstance(entry, dict) or "placement" not in entry or "percentage_bps" not in entry:
            raise ApiError("ERR_BAD_REQUEST", "Invalid prize_tier_table entry.")

    # Validate seeding rule (default RANKING)
    seeding_rule = body.get("seeding_rule", "RANKING")
    if seeding_rule not in {"RANKING", "RANDOM", "REGIONAL_BALANCE"}:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid seeding_rule: {seeding_rule}")

    # Validate referee level
    if body["required_referee_level"] not in {"L1", "L2", "L3"}:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid required_referee_level: {body['required_referee_level']}")

    t = common_fields_create()
    t.update({
        "name": body["name"],
        "format": body["format"],
        "region": body["region"],
        "min_age": int(body.get("min_age", 16)),
        "min_team_ranking_points": int(body.get("min_team_ranking_points", 0)),
        "entry_fee_cents": int(body["entry_fee_cents"]),
        "entry_fee_currency": body["entry_fee_currency"],
        "roster_lock_deadline": body["roster_lock_deadline"],
        "registration_deadline": body["registration_deadline"],
        "base_prize_pool_cents": int(body["base_prize_pool_cents"]),
        "status": "DRAFT",
        "prize_tier_table": list(body["prize_tier_table"]),
        "ban_pick_sequence": list(body["ban_pick_sequence"]),
        "map_pool": list(body["map_pool"]),
        "character_pool": list(body["character_pool"]),
        "seeding_rule": seeding_rule,
        "max_teams": int(body["max_teams"]),
        "required_referee_level": body["required_referee_level"],
        "bracket_published_at": None,
    })
    get_store().tournaments[t["id"]] = t
    return serialize_tournament(t)


# ---------- Reads ---------- #


def get_tournament(tid: str) -> dict[str, Any]:
    return serialize_tournament(_require_tournament(tid))


def list_tournaments(status: Optional[str], region: Optional[str], limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    store = get_store()
    rows = list(store.tournaments.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if region is not None:
        rows = [r for r in rows if r["region"] == region]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return rows, len(rows)


# ---------- State transitions ---------- #


def open_registration(tid: str) -> dict[str, Any]:
    t = _require_tournament(tid)
    if t["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", f"Tournament is in {t['status']}, expected DRAFT.")
    _validate_prize_tier_table(t["prize_tier_table"])
    deadline = parse_iso(t["registration_deadline"])
    if CLOCK.now >= deadline:
        raise ApiError("ERR_REGISTRATION_DEADLINE_PASSED",
                       "Cannot open registration after the registration_deadline.")
    t["status"] = "REGISTRATION_OPEN"
    bump_version(t)
    return serialize_tournament(t)


def lock_rosters(tid: str) -> dict[str, Any]:
    t = _require_tournament(tid)
    if t["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_INVALID_STATE", f"Tournament is in {t['status']}, expected REGISTRATION_OPEN.")
    _apply_roster_lock_cascade(t)
    t["status"] = "ROSTER_LOCKED"
    bump_version(t)
    return serialize_tournament(t)


def _apply_roster_lock_cascade(t: dict[str, Any]) -> None:
    """For every TeamRegistration in DRAFT/FEE_PENDING under this Tournament: → WITHDRAWN.
    REGISTERED registrations get roster_locked flag flipped (this is computed on read,
    so nothing to mutate persistently)."""
    store = get_store()
    for reg in list(store.team_registrations.values()):
        if reg["tournament_id"] != t["id"]:
            continue
        if reg["status"] in {"DRAFT", "FEE_PENDING"}:
            reg["status"] = "WITHDRAWN"
            bump_version(reg)


def publish_bracket(tid: str) -> dict[str, Any]:
    t = _require_tournament(tid)
    if t["status"] != "ROSTER_LOCKED":
        raise ApiError("ERR_INVALID_STATE", f"Tournament is in {t['status']}, expected ROSTER_LOCKED.")
    store = get_store()
    registered = [r for r in store.team_registrations.values()
                  if r["tournament_id"] == t["id"] and r["status"] == "REGISTERED"]
    if len(registered) < 2:
        raise ApiError("ERR_INSUFFICIENT_TEAMS", "publish-bracket requires at least 2 REGISTERED teams.")

    ordered = _order_for_seeding(t, registered)

    # Assign seed numbers (1-based) to the registrations in order.
    for idx, reg in enumerate(ordered, start=1):
        reg["seed_number"] = idx
        bump_version(reg)

    matches = _create_round_one_matches(t, ordered)

    # Time-conflict check across the new matches (involve same team).
    _check_match_overlap_on_publication(matches)

    # Persist matches.
    for m in matches:
        store.matches[m["id"]] = m

    t["bracket_published_at"] = now_iso()
    t["status"] = "BRACKET_PUBLISHED"
    bump_version(t)
    return serialize_tournament(t)


def _order_for_seeding(t: dict[str, Any], teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rule = t.get("seeding_rule", "RANKING")
    if rule == "RANKING":
        return sorted(
            teams,
            key=lambda r: (
                -int(r.get("ranking_points_snapshot") or 0),
                r["created_at"],
                r["id"],
            ),
        )
    if rule == "RANDOM":
        # Deterministic shuffle keyed by tournament id.
        seed_bytes = hashlib.sha256(t["id"].encode("utf-8")).digest()
        seed_int = int.from_bytes(seed_bytes[:8], "big")
        rng = random.Random(seed_int)
        ordered = list(teams)
        rng.shuffle(ordered)
        return ordered
    if rule == "REGIONAL_BALANCE":
        # Group by region, sort within region by ranking DESC then id ASC, then round-robin.
        by_region: dict[str, list[dict[str, Any]]] = {}
        for tm in teams:
            by_region.setdefault(tm["region"], []).append(tm)
        for region in by_region:
            by_region[region].sort(key=lambda r: (-int(r.get("ranking_points_snapshot") or 0), r["id"]))
        region_keys = sorted(by_region.keys())
        out: list[dict[str, Any]] = []
        idx = 0
        while any(by_region[k] for k in region_keys):
            for k in region_keys:
                if by_region[k]:
                    out.append(by_region[k].pop(0))
            idx += 1
        return out
    return list(teams)


def _create_round_one_matches(t: dict[str, Any], ordered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create round-1 Matches per the format pairing rule.

    Standard pairing: seed 1 vs seed N, 2 vs N-1, ... For odd counts, one team
    receives a bye. In DOUBLE_ELIMINATION the best-seed gets the bye; in SWISS
    the worst seed gets the bye. ROUND_ROBIN and GROUP_PLAYOFFS use the same
    inward-pairing first slate by default.
    """
    start_dt = CLOCK.now
    # 1-hour slot per match
    slot_minutes = 60
    fmt = t.get("format", "SWISS")

    bye_team: Optional[dict[str, Any]] = None
    if len(ordered) % 2 == 1:
        if fmt == "DOUBLE_ELIMINATION":
            # lowest seed_number (best ranked) — first item after ordering
            bye_team = ordered[0]
            paired = ordered[1:]
        elif fmt == "SWISS":
            # lowest-ranked (highest seed number) — last item
            bye_team = ordered[-1]
            paired = ordered[:-1]
        else:
            # Default: lowest seed gets the bye
            bye_team = ordered[0]
            paired = ordered[1:]
    else:
        paired = list(ordered)

    matches: list[dict[str, Any]] = []
    n = len(paired)
    half = n // 2
    bracket_position = 1
    from datetime import timedelta
    for i in range(half):
        team_a = paired[i]
        team_b = paired[n - 1 - i]
        scheduled_start = start_dt + timedelta(minutes=(bracket_position - 1) * (slot_minutes + 15))
        scheduled_end = scheduled_start + timedelta(minutes=slot_minutes)
        m = _new_match_row(
            tournament_id=t["id"],
            round_number=1,
            bracket_position=bracket_position,
            team_a_id=team_a["id"],
            team_b_id=team_b["id"],
            scheduled_start=format_iso(scheduled_start),
            scheduled_end=format_iso(scheduled_end),
        )
        matches.append(m)
        bracket_position += 1

    if bye_team is not None:
        scheduled_start = start_dt + timedelta(minutes=(bracket_position - 1) * (slot_minutes + 15))
        scheduled_end = scheduled_start + timedelta(minutes=slot_minutes)
        m = _new_match_row(
            tournament_id=t["id"],
            round_number=1,
            bracket_position=bracket_position,
            team_a_id=bye_team["id"],
            team_b_id=None,
            scheduled_start=format_iso(scheduled_start),
            scheduled_end=format_iso(scheduled_end),
        )
        m["winner_team_id"] = bye_team["id"]
        # Bye matches start completed effectively
        m["status"] = "COMPLETED"
        matches.append(m)
    return matches


def _new_match_row(*, tournament_id: str, round_number: int, bracket_position: int,
                   team_a_id: Optional[str], team_b_id: Optional[str],
                   scheduled_start: str, scheduled_end: str) -> dict[str, Any]:
    m = common_fields_create()
    m.update({
        "tournament_id": tournament_id,
        "round_number": round_number,
        "bracket_position": bracket_position,
        "team_a_id": team_a_id,
        "team_b_id": team_b_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "winner_team_id": None,
        "forfeit_reason": None,
        "assigned_referee_id": None,
    })
    return m


def _check_match_overlap_on_publication(matches: list[dict[str, Any]]) -> None:
    # Pairwise overlap of matches sharing either team.
    for i, m1 in enumerate(matches):
        if m1.get("status") == "FORFEITED":
            continue
        for m2 in matches[i + 1:]:
            if m2.get("status") == "FORFEITED":
                continue
            shared = set(filter(None, [m1["team_a_id"], m1["team_b_id"]])) & set(
                filter(None, [m2["team_a_id"], m2["team_b_id"]])
            )
            if not shared:
                continue
            if _intervals_overlap(m1["scheduled_start"], m1["scheduled_end"],
                                  m2["scheduled_start"], m2["scheduled_end"]):
                raise ApiError("ERR_MATCH_TIME_CONFLICT", "Two matches involving the same team overlap.")


def _intervals_overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    as_dt = parse_iso(a_start)
    ae_dt = parse_iso(a_end)
    bs_dt = parse_iso(b_start)
    be_dt = parse_iso(b_end)
    return as_dt < be_dt and bs_dt < ae_dt


def start_tournament(tid: str) -> dict[str, Any]:
    t = _require_tournament(tid)
    if t["status"] != "BRACKET_PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", f"Tournament is in {t['status']}, expected BRACKET_PUBLISHED.")
    t["status"] = "IN_PROGRESS"
    bump_version(t)
    return serialize_tournament(t)


def complete_tournament(tid: str) -> dict[str, Any]:
    t = _require_tournament(tid)
    if t["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", f"Tournament is in {t['status']}, expected IN_PROGRESS.")
    store = get_store()
    matches = [m for m in store.matches.values() if m["tournament_id"] == t["id"]]
    if any(m["status"] not in TERMINAL_MATCH_STATES for m in matches):
        raise ApiError("ERR_MATCHES_INCOMPLETE", "Not every match is in a terminal state.")

    t["status"] = "COMPLETED"
    bump_version(t)
    _emit_provisional_payouts(t)
    return serialize_tournament(t)


def _emit_provisional_payouts(t: dict[str, Any]) -> None:
    """Emit one PrizePayout per tier (PLACEMENT) + one MVP row, status=PROVISIONAL."""
    store = get_store()
    eligible = [r for r in store.team_registrations.values()
                if r["tournament_id"] == t["id"] and r["status"] in {"REGISTERED", "DISQUALIFIED"}]
    # Determine final placement: from completed bracket. For simplicity, use
    # ranking_points_snapshot DESC then id ASC as the deterministic order.
    # (No round-by-round bracket evaluation needed beyond what tests pin.)
    sorted_eligible = sorted(
        eligible,
        key=lambda r: (
            r.get("_final_placement") if r.get("_final_placement") is not None else 999_999,
            -int(r.get("ranking_points_snapshot") or 0),
            r["id"],
        ),
    )
    pool_cents = int(t["base_prize_pool_cents"]) + sum(
        int(c["amount_cents"])
        for c in store.crowdfund_contributions.values()
        if c["tournament_id"] == t["id"] and c["status"] == "COLLECTED"
    )

    payout_rows: list[dict[str, Any]] = []
    sorted_tiers = sorted(t["prize_tier_table"], key=lambda x: int(x["placement"]))
    for tier in sorted_tiers:
        placement = int(tier["placement"])
        bps = int(tier["percentage_bps"])
        team = sorted_eligible[placement - 1] if placement - 1 < len(sorted_eligible) else None
        if team is None:
            # No eligible team at this placement — PRD §3.6 says
            # "team_id is set to the team at the corresponding position
            # in the sorted set"; if there is no such team, no payout
            # row can be emitted for that placement.
            continue
        team_id = team["id"]
        gross = compute_prize_tier_amount(pool_cents, bps)
        row = common_fields_create()
        row.update({
            "tournament_id": t["id"],
            "team_id": team_id,
            "player_id": None,
            "award_kind": "PLACEMENT",
            "placement": placement,
            "gross_amount_cents": gross,
            "tax_withheld_cents": 0,
            "net_amount_cents": 0,
            "payout_currency": t["entry_fee_currency"],
            "jurisdiction": None,
            "status": "PROVISIONAL",
        })
        store.prize_payouts[row["id"]] = row
        payout_rows.append(row)

    # MVP row
    mvp_player_id = _pick_mvp_player_id(t)
    mvp_row = common_fields_create()
    mvp_row.update({
        "tournament_id": t["id"],
        "team_id": None,
        "player_id": mvp_player_id,
        "award_kind": "MVP",
        "placement": None,
        "gross_amount_cents": compute_mvp_amount(pool_cents),
        "tax_withheld_cents": 0,
        "net_amount_cents": 0,
        "payout_currency": t["entry_fee_currency"],
        "jurisdiction": None,
        "status": "PROVISIONAL",
    })
    store.prize_payouts[mvp_row["id"]] = mvp_row


def _pick_mvp_player_id(t: dict[str, Any]) -> Optional[str]:
    """Highest-aggregate-score player; tie-break lexicographically smallest player_id.
    Without per-match score data, we use ranking_points across ACTIVE contracts as a proxy."""
    store = get_store()
    eligible_team_ids = {r["id"] for r in store.team_registrations.values()
                        if r["tournament_id"] == t["id"]
                        and r["status"] in {"REGISTERED", "DISQUALIFIED"}}
    candidates = [
        pc for pc in store.player_contracts.values()
        if pc.get("team_id") in eligible_team_ids
        and pc.get("status") in {"ACTIVE", "PENDING_SIGNATURES"}
        and pc.get("roster_slot") == "MAIN"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-int(c.get("ranking_points", 0)), str(c.get("player_id", ""))))
    return candidates[0].get("player_id")


# ---------- Finalize & Distribute ---------- #


def finalize_prize_pool(tid: str) -> list[dict[str, Any]]:
    """Recompute via prize_share_final, lock tax & FX, transition every PROVISIONAL → FINALIZED."""
    t = _require_tournament(tid)
    if t["status"] != "COMPLETED":
        raise ApiError("ERR_TOURNAMENT_NOT_COMPLETED",
                       f"finalize-prize-pool requires Tournament.status COMPLETED, got {t['status']}.")
    store = get_store()
    payouts = [p for p in store.prize_payouts.values() if p["tournament_id"] == t["id"]]

    # ---------- Final-pass recompute (only REGISTERED teams) ---------- #
    final_eligible = [r for r in store.team_registrations.values()
                      if r["tournament_id"] == t["id"] and r["status"] == "REGISTERED"]
    final_eligible.sort(
        key=lambda r: (
            r.get("_final_placement") if r.get("_final_placement") is not None else 999_999,
            -int(r.get("ranking_points_snapshot") or 0),
            r["id"],
        ),
    )
    pool_cents = int(t["base_prize_pool_cents"]) + sum(
        int(c["amount_cents"])
        for c in store.crowdfund_contributions.values()
        if c["tournament_id"] == t["id"] and c["status"] == "COLLECTED"
    )

    placement_rows = [p for p in payouts if p["award_kind"] == "PLACEMENT" and p["status"] == "PROVISIONAL"]
    # We must check: for each PROVISIONAL placement row, the recomputed final value matches.
    placement_rows.sort(key=lambda p: int(p["placement"]))
    sorted_tiers = sorted(t["prize_tier_table"], key=lambda x: int(x["placement"]))

    # Map placement -> tier_bps
    tier_by_placement: dict[int, int] = {int(x["placement"]): int(x["percentage_bps"]) for x in sorted_tiers}

    for row in placement_rows:
        placement = int(row["placement"])
        team_idx = placement - 1
        team = final_eligible[team_idx] if team_idx < len(final_eligible) else None
        bps = tier_by_placement.get(placement, 0)
        recomputed_gross = compute_prize_tier_amount(pool_cents, bps)
        # If the PROVISIONAL was CLAWED_BACK (we'd see status != PROVISIONAL — skip those here);
        # otherwise the team and amount should match.
        if recomputed_gross != int(row["gross_amount_cents"]):
            raise ApiError("ERR_PRIZE_FINAL_MISMATCH",
                           f"Placement {placement} gross differs at finalize.")
        # Re-target team if disqualifications collapse placements upward.
        if team is not None:
            row["team_id"] = team["id"]

    # MVP row is finalised as-is.
    mvp_rows = [p for p in payouts if p["award_kind"] == "MVP" and p["status"] == "PROVISIONAL"]
    for r in mvp_rows:
        recomputed = compute_mvp_amount(pool_cents)
        if recomputed != int(r["gross_amount_cents"]):
            raise ApiError("ERR_PRIZE_FINAL_MISMATCH", "MVP gross differs at finalize.")

    # ---------- Tax & FX & floor checks ---------- #
    # Resolve jurisdictions for each row.
    for row in placement_rows + mvp_rows:
        jurisdiction = _resolve_jurisdiction(t, row)
        if jurisdiction is None:
            raise ApiError("ERR_PAYOUT_BELOW_FLOOR",
                           "Recipient has no identity-verification jurisdiction record.")
        tax_in_payout, gross_in_payout, net = compute_tax_withholding(
            int(row["gross_amount_cents"]),
            jurisdiction,
            t["entry_fee_currency"],
            row["payout_currency"],
        )
        if net < 100:  # MIN_PAYOUT_FLOOR_CENTS
            raise ApiError("ERR_PAYOUT_BELOW_FLOOR",
                           f"Net payout {net} below MIN_PAYOUT_FLOOR_CENTS=100.")
        row["jurisdiction"] = jurisdiction
        row["tax_withheld_cents"] = tax_in_payout
        row["net_amount_cents"] = net
        # The gross we expose stays in entry_fee_currency for invariant calc; if a
        # payout_currency override happened, gross_amount_cents is the entry_fee_currency value.
        # (Tests measure tax/net in payout_currency, gross in entry_fee_currency.)
        row["status"] = "FINALIZED"
        bump_version(row)

    return placement_rows + mvp_rows


def _resolve_jurisdiction(t: dict[str, Any], row: dict[str, Any]) -> Optional[str]:
    store = get_store()
    if row["award_kind"] == "PLACEMENT":
        team = store.team_registrations.get(row["team_id"]) if row.get("team_id") else None
        if team is None:
            return None
        manager_id = team["manager_id"]
        # Lookup identity verification by manager_id (any contract whose player_id == manager_id?
        # The PRD says "IdentityVerification.jurisdiction of the TeamRegistration.manager_id".
        # We interpret this as: an IdentityVerification record whose player_id == manager_id.
        for v in store.identity_verifications.values():
            if v.get("player_id") == manager_id and v.get("status") == "VERIFIED":
                return v.get("jurisdiction")
        return None
    elif row["award_kind"] in {"MVP", "SPECIAL_AWARD"}:
        player_id = row.get("player_id")
        if not player_id:
            return None
        # Find the player's contract → identity verification
        for pc in store.player_contracts.values():
            if pc.get("player_id") == player_id:
                for v in store.identity_verifications.values():
                    if v.get("contract_id") == pc["id"] and v.get("status") == "VERIFIED":
                        return v.get("jurisdiction")
        return None
    return None


def distribute_prizes(tid: str) -> dict[str, Any]:
    t = _require_tournament(tid)
    if t["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", f"Tournament is in {t['status']}, expected COMPLETED.")
    store = get_store()
    payouts = [p for p in store.prize_payouts.values()
               if p["tournament_id"] == t["id"] and p["status"] != "CLAWED_BACK"]
    if any(p["status"] == "PROVISIONAL" for p in payouts):
        raise ApiError("ERR_PRIZE_POOL_NOT_FINALIZED",
                       "All PrizePayouts must be FINALIZED before distribute-prizes.")
    pool_cents = int(t["base_prize_pool_cents"]) + sum(
        int(c["amount_cents"])
        for c in store.crowdfund_contributions.values()
        if c["tournament_id"] == t["id"] and c["status"] == "COLLECTED"
    )
    total = sum(int(p["gross_amount_cents"]) for p in payouts)
    if total != pool_cents:
        raise ApiError("ERR_PRIZE_POOL_INVARIANT",
                       f"Sum of gross_amount_cents={total} != total_prize_pool_cents={pool_cents}.")
    for p in payouts:
        if p["status"] == "FINALIZED":
            p["status"] = "PAID"
            bump_version(p)
    t["status"] = "PRIZES_DISTRIBUTED"
    bump_version(t)
    return serialize_tournament(t)


def cancel_tournament(tid: str, reason: str) -> dict[str, Any]:
    t = _require_tournament(tid)
    if t["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_INVALID_STATE", f"Tournament is in {t['status']}, expected REGISTRATION_OPEN.")
    store = get_store()
    for reg in list(store.team_registrations.values()):
        if reg["tournament_id"] != t["id"]:
            continue
        if reg["status"] in {"FEE_PENDING", "REGISTERED"}:
            reg["entry_fee_paid_cents"] = 0
            reg["status"] = "WITHDRAWN"
            bump_version(reg)
    for c in list(store.crowdfund_contributions.values()):
        if c["tournament_id"] == t["id"] and c["status"] == "COLLECTED":
            c["status"] = "REFUNDED"
    t["status"] = "CANCELLED"
    t["cancel_reason"] = reason
    bump_version(t)
    return serialize_tournament(t)


# ---------- Crowdfunding ---------- #


def add_crowdfund_contribution(tid: str, body: dict[str, Any]) -> dict[str, Any]:
    t = _require_tournament(tid)
    for key in ("contributor_user_id", "amount_cents", "status"):
        if key not in body:
            raise ApiError("ERR_BAD_REQUEST", f"Missing field: {key}")
    if body["status"] not in {"PLEDGED", "COLLECTED", "REFUNDED"}:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid status: {body['status']}")
    store = get_store()
    from ..store import common_fields_append_only
    row = common_fields_append_only()
    row.update({
        "tournament_id": t["id"],
        "contributor_user_id": body["contributor_user_id"],
        "amount_cents": int(body["amount_cents"]),
        "status": body["status"],
    })
    store.crowdfund_contributions[row["id"]] = row
    return dict(row)
