"""Business services: derived fields, calculations, pairing engine, serializers."""
import math
from decimal import Decimal

from core import (
    ApiError, db, fmt_dt, new_id, now_ts, parse_dt, round_half_up_cents, touch,
)

# ---------------------------------------------------------------------------
# Constants (pinned by PRD / scaffold calculations table)
# ---------------------------------------------------------------------------

DEBATE_ENTRIES_PER_JUDGE = 2
SPEECH_ENTRIES_PER_JUDGE = 5
PREMIUM_THRESHOLD_ROUNDS = 8
HIRED_ROUND_BASE_CENTS = 5000
HIRED_ROUND_PREMIUM_CENTS = 7500
BYE_SPEAKER_POINTS = 27
SECTION_MAX_SIZE = 7
JUDGE_TURNOVER_MINUTES = 30
DISCOUNT_TIER_2_THRESHOLD_CENTS = 100000
DISCOUNT_TIER_2_PCT = Decimal("0.10")
DISCOUNT_TIER_1_THRESHOLD_CENTS = 50000
DISCOUNT_TIER_1_PCT = Decimal("0.05")

INVOICE_STATUS_SET = {"CONFIRMED", "COMPETING", "ADVANCED", "ELIMINATED", "FINISHED"}
COMPETITION_STATUS_SET = {"COMPETING", "ADVANCED", "ELIMINATED", "FINISHED"}
COVERAGE_CONTRACT_STATUSES = {"FILLED", "CONFIRMED", "DISPUTED", "PAID"}
INVOICE_CONTRACT_STATUSES = {"CONFIRMED", "DISPUTED", "PAID"}

QUALIFICATION_POINTS = {
    "CHAMPION": 10,
    "RUNNER_UP": 8,
    "SEMIFINALIST": 6,
    "QUARTERFINALIST": 4,
    "OCTOFINALIST": 2,
    "NON_BREAKING": 1,
}

DEBATE_CODES = {"CX", "LD", "PF"}
SPEECH_CODES = {"OO", "EXT", "INF"}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def get_or_404(coll_name, rid, error_id):
    obj = getattr(db, coll_name).get(rid)
    if obj is None:
        raise ApiError(error_id, 404, "%s %s does not exist" % (coll_name[:-1], rid))
    return obj


def tournament_of_division(div):
    return db.tournaments.get(div["tournament_id"])


def tournament_of_school(school):
    return db.tournaments.get(school["tournament_id"])


def division_of_entry(entry):
    return db.divisions.get(entry["division_id"])


def tournament_of_entry(entry):
    div = division_of_entry(entry)
    return db.tournaments.get(div["tournament_id"]) if div else None


def pairing_members(pairing_id):
    mem = [pe for pe in db.pairing_entries.values() if pe["pairing_id"] == pairing_id]
    mem.sort(key=lambda pe: pe["draw_position"])
    return mem


def pairing_member_ids(pairing_id):
    return [pe["entry_id"] for pe in pairing_members(pairing_id)]


def division_entries(div_id, statuses=None):
    return [
        e
        for e in db.entries.values()
        if e["division_id"] == div_id and (statuses is None or e["status"] in statuses)
    ]


def school_contracts(school_id):
    return [c for c in db.contracts.values() if c["school_id"] == school_id]


def tournament_schools(tournament_id):
    return [s for s in db.schools.values() if s["tournament_id"] == tournament_id]


def tournament_divisions(tournament_id):
    return [d for d in db.divisions.values() if d["tournament_id"] == tournament_id]


def round_pairings(round_id):
    res = [p for p in db.pairings.values() if p["round_id"] == round_id]
    res.sort(key=lambda p: p["created_at"])
    return res


# ---------------------------------------------------------------------------
# School derived fields (obligation / coverage / shortfall / invoice)
# ---------------------------------------------------------------------------


def compute_invoice(school, inv_entries=None):
    if inv_entries is None:
        inv_entries = [
            e
            for e in db.entries.values()
            if e["school_id"] == school["id"] and e["status"] in INVOICE_STATUS_SET
        ]
    contracts = school_contracts(school["id"])
    entry_fees = sum(e["fee_charged_cents"] for e in inv_entries)
    judge_fees = sum(
        c["final_fee_cents"] or 0 for c in contracts if c["status"] in INVOICE_CONTRACT_STATUSES
    )
    pre_discount = entry_fees + judge_fees
    if pre_discount >= DISCOUNT_TIER_2_THRESHOLD_CENTS:
        pct = DISCOUNT_TIER_2_PCT
    elif pre_discount >= DISCOUNT_TIER_1_THRESHOLD_CENTS:
        pct = DISCOUNT_TIER_1_PCT
    else:
        pct = Decimal("0")
    discount = round_half_up_cents(Decimal(entry_fees) * pct) + round_half_up_cents(
        Decimal(judge_fees) * pct
    )
    payments = sum(c["final_fee_cents"] or 0 for c in contracts if c["status"] == "PAID")
    return pre_discount - discount - payments


def projected_invoice_after_confirm(school, fee):
    """Invoice projection with one more confirmed entry charging `fee`."""
    entries = [
        e
        for e in db.entries.values()
        if e["school_id"] == school["id"] and e["status"] in INVOICE_STATUS_SET
    ]
    entry_fees = sum(e["fee_charged_cents"] for e in entries) + fee
    contracts = school_contracts(school["id"])
    judge_fees = sum(
        c["final_fee_cents"] or 0 for c in contracts if c["status"] in INVOICE_CONTRACT_STATUSES
    )
    pre_discount = entry_fees + judge_fees
    if pre_discount >= DISCOUNT_TIER_2_THRESHOLD_CENTS:
        pct = DISCOUNT_TIER_2_PCT
    elif pre_discount >= DISCOUNT_TIER_1_THRESHOLD_CENTS:
        pct = DISCOUNT_TIER_1_PCT
    else:
        pct = Decimal("0")
    discount = round_half_up_cents(Decimal(entry_fees) * pct) + round_half_up_cents(
        Decimal(judge_fees) * pct
    )
    payments = sum(c["final_fee_cents"] or 0 for c in contracts if c["status"] == "PAID")
    return pre_discount - discount - payments


def school_derived(school):
    """Live computation of a school's derived fields (no mutation)."""
    t = db.tournaments.get(school["tournament_id"])
    entries = [e for e in db.entries.values() if e["school_id"] == school["id"]]
    inv_entries = [e for e in entries if e["status"] in INVOICE_STATUS_SET]
    confirmed_entry_count = len(inv_entries)

    per_div = {}
    for e in inv_entries:
        per_div[e["division_id"]] = per_div.get(e["division_id"], 0) + 1
    obligation = 0
    prc = t["prelim_round_count"] if t else 0
    for div_id, n in per_div.items():
        div = db.divisions.get(div_id)
        if not div:
            continue
        per = DEBATE_ENTRIES_PER_JUDGE if div["event_type"] == "DEBATE" else SPEECH_ENTRIES_PER_JUDGE
        obligation += math.ceil(n / per) * prc

    committed = sum(
        j["commitment_rounds"]
        for j in db.judges.values()
        if j["school_id"] == school["id"]
        and j["judge_type"] == "SCHOOL_PROVIDED"
        and j["status"] == "COMMITTED"
    )
    hired = sum(
        c["rounds_requested"] - c["rounds_released"]
        for c in school_contracts(school["id"])
        if c["status"] in COVERAGE_CONTRACT_STATUSES
    )
    covered = committed + hired
    shortfall = max(0, obligation - covered)
    return {
        "confirmed_entry_count": confirmed_entry_count,
        "judge_obligation_rounds": obligation,
        "covered_judge_rounds": covered,
        "shortfall_rounds": shortfall,
        "obligation_status": "SATISFIED" if shortfall == 0 else "DEFICIENT",
        "invoice_balance_cents": compute_invoice(school, inv_entries),
    }


# ---------------------------------------------------------------------------
# Hired-judge tiered fee
# ---------------------------------------------------------------------------


def hired_fee(tournament_id, target_contract, variant):
    statuses = (
        {"REQUESTED", "FILLED", "CONFIRMED", "DISPUTED", "PAID"}
        if variant == "QUOTE"
        else {"FILLED", "CONFIRMED", "DISPUTED", "PAID"}
    )
    school_ids = {s["id"] for s in tournament_schools(tournament_id)}
    cands = [
        c
        for c in db.contracts.values()
        if c["school_id"] in school_ids and c["status"] in statuses
    ]
    cands.sort(key=lambda c: (c["created_at"], c["rounds_requested"]))
    c_pre = 0
    for c in cands:
        if c["id"] == target_contract["id"]:
            break
        c_pre += c["rounds_requested"]
    rr = target_contract["rounds_requested"]
    premium = max(0, min(rr, c_pre + rr - PREMIUM_THRESHOLD_ROUNDS))
    base = rr - premium
    return base * HIRED_ROUND_BASE_CENTS + premium * HIRED_ROUND_PREMIUM_CENTS


# ---------------------------------------------------------------------------
# Entry statistics / standings
# ---------------------------------------------------------------------------


def entry_verified_prelim_ballots(entry):
    res = []
    for b in db.ballots.values():
        if b["status"] != "VERIFIED":
            continue
        p = db.pairings.get(b["pairing_id"])
        if not p or p["is_bye"]:
            continue
        r = db.rounds.get(p["round_id"])
        if not r or r["division_id"] != entry["division_id"] or r["kind"] != "PRELIM":
            continue
        if entry["id"] in pairing_member_ids(p["id"]):
            res.append(b)
    return res


def entry_bye_count(entry):
    n = 0
    for p in db.pairings.values():
        if not p["is_bye"] or p["status"] != "VERIFIED":
            continue
        if p["winner_entry_id"] != entry["id"]:
            continue
        r = db.rounds.get(p["round_id"])
        if r and r["division_id"] == entry["division_id"] and r["kind"] == "PRELIM":
            n += 1
    return n


def recompute_entry_stats(entry, div):
    """Recompute one entry's stat fields (not prelim_rank). Returns True if changed."""
    before = (
        entry["wins"], entry["losses"], entry["speaker_points_raw"],
        entry["speaker_points_adjusted"], entry["rank_points_raw"],
        entry["rank_points_adjusted"], entry["opponent_strength"],
        entry.get("_first_places", 0),
    )
    ballots = entry_verified_prelim_ballots(entry)
    byes = entry_bye_count(entry)
    if div["event_type"] == "DEBATE":
        contribs = []
        wins = 0
        losses = 0
        for b in ballots:
            pts = (b.get("speaker_points") or {}).get(entry["id"])
            if pts is not None:
                contribs.append(int(pts))
            if b.get("winner_entry_id") == entry["id"]:
                wins += 1
            else:
                losses += 1
        contribs += [BYE_SPEAKER_POINTS] * byes
        wins += byes
        raw = sum(contribs)
        adj = raw - max(contribs) - min(contribs) if len(contribs) >= 3 else raw
        entry["wins"] = wins
        entry["losses"] = losses
        entry["speaker_points_raw"] = raw
        entry["speaker_points_adjusted"] = adj
        entry["rank_points_raw"] = 0
        entry["rank_points_adjusted"] = 0
        entry["_first_places"] = 0
    else:
        contribs = []
        first_places = 0
        for b in ballots:
            rank = (b.get("ranks") or {}).get(entry["id"])
            if rank is not None:
                contribs.append(8 - int(rank))
                if int(rank) == 1:
                    first_places += 1
        raw = sum(contribs)
        adj = raw - max(contribs) - min(contribs) if len(contribs) >= 3 else raw
        entry["wins"] = 0
        entry["losses"] = 0
        entry["speaker_points_raw"] = 0
        entry["speaker_points_adjusted"] = 0
        entry["rank_points_raw"] = raw
        entry["rank_points_adjusted"] = adj
        entry["_first_places"] = first_places
    after = (
        entry["wins"], entry["losses"], entry["speaker_points_raw"],
        entry["speaker_points_adjusted"], entry["rank_points_raw"],
        entry["rank_points_adjusted"], entry["opponent_strength"],
        entry.get("_first_places", 0),
    )
    return before != after


def standings_order(div, entries=None):
    if entries is None:
        entries = division_entries(div["id"], COMPETITION_STATUS_SET)
    entries = list(entries)
    if div["event_type"] == "DEBATE":
        entries.sort(
            key=lambda e: (
                -e["wins"],
                -e["speaker_points_adjusted"],
                -e["opponent_strength"],
                -e["speaker_points_raw"],
                e["created_at"],
            )
        )
    else:
        entries.sort(
            key=lambda e: (
                -e["rank_points_adjusted"],
                -e["rank_points_raw"],
                -e.get("_first_places", 0),
                e["created_at"],
            )
        )
    return entries


def recompute_division_stats(div):
    """Full stats + standings recompute for a division (tabulate / ballot void)."""
    entries = division_entries(div["id"], COMPETITION_STATUS_SET)
    changed = {}
    for e in entries:
        changed[e["id"]] = recompute_entry_stats(e, div)
    # Opponent strength (debate) after all wins are refreshed.
    if div["event_type"] == "DEBATE":
        wins_map = {e["id"]: e["wins"] for e in entries}
        for e in entries:
            opps = set()
            for b in entry_verified_prelim_ballots(e):
                p = db.pairings[b["pairing_id"]]
                for mid in pairing_member_ids(p["id"]):
                    if mid != e["id"]:
                        opps.add(mid)
            new_os = sum(wins_map.get(o, 0) for o in opps)
            if e["opponent_strength"] != new_os:
                e["opponent_strength"] = new_os
                changed[e["id"]] = True
    else:
        for e in entries:
            if e["opponent_strength"] != 0:
                e["opponent_strength"] = 0
                changed[e["id"]] = True
    # Standings ranks.
    order = standings_order(div, entries)
    for i, e in enumerate(order):
        new_rank = i + 1
        if e["prelim_rank"] != new_rank:
            e["prelim_rank"] = new_rank
            changed[e["id"]] = True
    for e in entries:
        if changed.get(e["id"]):
            touch(e)


# ---------------------------------------------------------------------------
# Pairing generation engine
# ---------------------------------------------------------------------------


def prior_prelim_meetings(div_id, round_number):
    """frozenset pairs that already met in earlier PRELIM rounds of the division."""
    met = set()
    for r in db.rounds.values():
        if r["division_id"] != div_id or r["kind"] != "PRELIM":
            continue
        if r["round_number"] >= round_number:
            continue
        for p in round_pairings(r["id"]):
            ids = pairing_member_ids(p["id"])
            if len(ids) == 2:
                met.add(frozenset(ids))
    return met


def find_debate_matching(pool, prior_met):
    """Deterministic exhaustive search over perfect matchings, pool-order guided."""
    n = len(pool)
    if n == 0:
        return []
    if n % 2 != 0:
        return None
    school_of = {e["id"]: e["school_id"] for e in pool}
    used = [False] * n
    pairs = []

    def allowed(a, b):
        if school_of[a["id"]] == school_of[b["id"]]:
            return False
        if frozenset((a["id"], b["id"])) in prior_met:
            return False
        return True

    def bt():
        i = -1
        for k in range(n):
            if not used[k]:
                i = k
                break
        if i == -1:
            return True
        used[i] = True
        for j in range(i + 1, n):
            if used[j]:
                continue
            if not allowed(pool[i], pool[j]):
                continue
            used[j] = True
            pairs.append((pool[i], pool[j]))
            if bt():
                return True
            pairs.pop()
            used[j] = False
        used[i] = False
        return False

    return pairs if bt() else None


def serpentine_sections(ordered, max_size):
    """Capacity-aware snake distribution; larger sections first, sizes differ <= 1."""
    n = len(ordered)
    if n == 0:
        return []
    k = math.ceil(n / max_size)
    base = n // k
    rem = n % k
    sizes = [base + 1 if i < rem else base for i in range(k)]
    sections = [[] for _ in range(k)]

    def snake_gen():
        fwd = True
        while True:
            rng = range(k) if fwd else range(k - 1, -1, -1)
            for s in rng:
                yield s
            fwd = not fwd

    gen = snake_gen()
    for e in ordered:
        while True:
            s = next(gen)
            if len(sections[s]) < sizes[s]:
                sections[s].append(e)
                break
    return sections


def create_pairing(round_obj, fmt, members, is_bye=False, winner_entry_id=None):
    p = {
        "id": new_id(),
        "round_id": round_obj["id"],
        "format": fmt,
        "room_id": None,
        "judge_id": None,
        "status": "VERIFIED" if is_bye else "PENDING_STAFFING",
        "is_bye": is_bye,
        "winner_entry_id": winner_entry_id,
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
    }
    db.pairings[p["id"]] = p
    for pos, (entry, side) in enumerate(members, start=1):
        pe = {
            "id": new_id(),
            "pairing_id": p["id"],
            "entry_id": entry["id"],
            "side": side,
            "draw_position": pos,
            "created_at": now_ts(),
        }
        db.pairing_entries[pe["id"]] = pe
    return p


def generate_pairings(round_obj):
    """Runs the pinned pairing algorithm. Raises ERR_PAIRING_INFEASIBLE."""
    div = db.divisions[round_obj["division_id"]]
    is_debate = div["event_type"] == "DEBATE"
    fmt = "HEAD_TO_HEAD" if is_debate else "SECTION"

    if round_obj["kind"] == "PRELIM":
        eligible = division_entries(div["id"], {"COMPETING"})
        if round_obj["round_number"] == 1:
            ordered = sorted(eligible, key=lambda e: e["created_at"])
        else:
            ordered = standings_order(div, eligible)
    else:  # ELIM
        eligible = division_entries(div["id"], {"ADVANCED"})
        ordered = sorted(
            eligible,
            key=lambda e: (e["seed"] if e["seed"] is not None else 1 << 30, e["created_at"]),
        )

    created = []

    if round_obj["kind"] == "PRELIM" and is_debate:
        pool = list(ordered)
        bye_entry = None
        if len(pool) % 2 == 1:
            for e in reversed(pool):
                if not e["has_received_bye"]:
                    bye_entry = e
                    break
            if bye_entry is None:
                bye_entry = pool[-1]
            pool.remove(bye_entry)
        prior_met = prior_prelim_meetings(div["id"], round_obj["round_number"])
        pairs = find_debate_matching(pool, prior_met)
        if pairs is None:
            raise ApiError(
                "ERR_PAIRING_INFEASIBLE",
                409,
                "No complete valid arrangement exists under same-school and rematch constraints",
            )
        for a, b in pairs:
            created.append(create_pairing(round_obj, fmt, [(a, "AFF"), (b, "NEG")]))
        if bye_entry is not None:
            bp = create_pairing(
                round_obj, fmt, [(bye_entry, "AFF")], is_bye=True, winner_entry_id=bye_entry["id"]
            )
            created.append(bp)
            bye_entry["has_received_bye"] = True
            recompute_entry_stats(bye_entry, div)
            touch(bye_entry)
    elif round_obj["kind"] == "PRELIM":  # speech prelim
        for section in serpentine_sections(ordered, SECTION_MAX_SIZE):
            members = [(e, "SPEAKER") for e in section]
            created.append(create_pairing(round_obj, fmt, members))
    else:  # ELIM
        if is_debate:
            f = len(ordered)
            for i in range(f // 2):
                a = ordered[i]
                b = ordered[f - 1 - i]
                created.append(create_pairing(round_obj, fmt, [(a, "AFF"), (b, "NEG")]))
        else:
            for section in serpentine_sections(ordered, SECTION_MAX_SIZE):
                members = [(e, "SPEAKER") for e in section]
                created.append(create_pairing(round_obj, fmt, members))
    return created


# ---------------------------------------------------------------------------
# Break determination
# ---------------------------------------------------------------------------


def _largest_pow2(x):
    if x < 1:
        return 0
    return 1 << (x.bit_length() - 1)


def determine_breaks_service(div, t):
    competing = division_entries(div["id"], {"COMPETING"})
    n = len(competing)
    if n < 4:
        raise ApiError(
            "ERR_INSUFFICIENT_BREAK_CANDIDATES", 409,
            "Fewer than 4 competing entries in the division",
        )
    w = t["prelim_round_count"]
    win_threshold = w // 2 + 1
    if div["event_type"] == "DEBATE":
        candidates = {e["id"] for e in competing if e["wins"] >= win_threshold}
    else:
        candidates = {e["id"] for e in competing}
    size_cap = min(16, _largest_pow2(n // 2))
    bracket = _largest_pow2(min(size_cap, len(candidates)))
    if bracket < 2:
        raise ApiError(
            "ERR_INSUFFICIENT_BREAK_CANDIDATES", 409,
            "Fewer than 2 break candidates remain",
        )
    order = standings_order(div, competing)
    advancing = [e for e in order if e["id"] in candidates][:bracket]
    advancing_ids = {e["id"] for e in advancing}
    for i, e in enumerate(advancing):
        e["status"] = "ADVANCED"
        e["seed"] = i + 1
        touch(e)
    for e in competing:
        if e["id"] not in advancing_ids:
            e["status"] = "ELIMINATED"
            e["final_placement"] = "NON_BREAKING"
            touch(e)
    div["bracket_size"] = bracket
    touch(div)


# ---------------------------------------------------------------------------
# Elim placements / completion / publication
# ---------------------------------------------------------------------------


def elim_tier(f):
    if f == 2:
        return "RUNNER_UP"
    if 3 <= f <= 4:
        return "SEMIFINALIST"
    if 5 <= f <= 8:
        return "QUARTERFINALIST"
    return "OCTOFINALIST"


def verified_ballot_of_pairing(pairing_id):
    for b in db.ballots.values():
        if b["pairing_id"] == pairing_id and b["status"] == "VERIFIED":
            return b
    return None


def resolve_elim_placements(round_obj, div):
    """Applied at ELIM tabulation. F = ADVANCED count at the start of the round."""
    advanced = division_entries(div["id"], {"ADVANCED"})
    f = len(advanced)
    is_debate = div["event_type"] == "DEBATE"
    later_elims = [
        r
        for r in db.rounds.values()
        if r["division_id"] == div["id"]
        and r["kind"] == "ELIM"
        and r["round_number"] > round_obj["round_number"]
    ]
    is_final_section = (not is_debate) and f <= SECTION_MAX_SIZE and not later_elims

    for p in round_pairings(round_obj["id"]):
        if p["is_bye"]:
            continue
        ballot = verified_ballot_of_pairing(p["id"])
        member_ids = pairing_member_ids(p["id"])
        if is_debate:
            winner_id = p["winner_entry_id"]
            for mid in member_ids:
                if mid != winner_id:
                    loser = db.entries.get(mid)
                    if loser and loser["status"] == "ADVANCED":
                        loser["status"] = "ELIMINATED"
                        loser["final_placement"] = elim_tier(f)
                        touch(loser)
        else:
            if not ballot or not ballot.get("ranks"):
                continue
            ranks = ballot["ranks"]
            for mid in member_ids:
                rank = ranks.get(mid)
                if rank is None:
                    continue
                rank = int(rank)
                e = db.entries.get(mid)
                if not e or e["status"] != "ADVANCED":
                    continue
                if rank <= 2:
                    continue  # top-2 stay ADVANCED
                if is_final_section:
                    placement = "SEMIFINALIST" if rank <= 4 else "QUARTERFINALIST"
                else:
                    placement = elim_tier(f)
                e["status"] = "ELIMINATED"
                e["final_placement"] = placement
                touch(e)


def resolve_champions(t):
    for div in tournament_divisions(t["id"]):
        advanced = division_entries(div["id"], {"ADVANCED"})
        if not advanced:
            continue
        if div["event_type"] == "DEBATE":
            if len(advanced) == 1:
                e = advanced[0]
                e["status"] = "FINISHED"
                e["final_placement"] = "CHAMPION"
                touch(e)
        else:
            elim_rounds = [
                r
                for r in db.rounds.values()
                if r["division_id"] == div["id"] and r["kind"] == "ELIM"
            ]
            if not elim_rounds:
                continue
            final_r = max(elim_rounds, key=lambda r: r["round_number"])
            rank_of = {}
            for p in round_pairings(final_r["id"]):
                b = verified_ballot_of_pairing(p["id"])
                if b and b.get("ranks"):
                    for eid, rk in b["ranks"].items():
                        rank_of[eid] = int(rk)
            adv_sorted = sorted(
                advanced, key=lambda e: (rank_of.get(e["id"], 1 << 30), e["created_at"])
            )
            if len(adv_sorted) >= 1:
                adv_sorted[0]["status"] = "FINISHED"
                adv_sorted[0]["final_placement"] = "CHAMPION"
                touch(adv_sorted[0])
            if len(adv_sorted) >= 2:
                adv_sorted[1]["status"] = "FINISHED"
                adv_sorted[1]["final_placement"] = "RUNNER_UP"
                touch(adv_sorted[1])


def award_qualification_points(t):
    for div in tournament_divisions(t["id"]):
        for e in division_entries(div["id"]):
            if e["status"] == "REGISTERED":
                continue
            if e["status"] == "WITHDRAWN":
                pts = 0
            else:
                pts = QUALIFICATION_POINTS.get(e["final_placement"] or "NON_BREAKING", 1)
            if e["qualification_points"] != pts:
                e["qualification_points"] = pts
                touch(e)


def auto_release_contracts(school):
    """Withdrawal cascade link 2: drain surplus hired coverage, most recent first.

    The surplus is measured against all live hired coverage, including the active
    rounds of still-REQUESTED contracts: a REQUESTED contract holds rounds against
    a shortfall the withdrawal may have erased, which is exactly the surplus the
    cascade exists to drain (PRD §3.2).
    """
    d = school_derived(school)
    requested_active = sum(
        c["rounds_requested"] - c["rounds_released"]
        for c in school_contracts(school["id"])
        if c["status"] == "REQUESTED"
    )
    surplus = (
        d["covered_judge_rounds"] + requested_active - d["judge_obligation_rounds"]
    )
    if surplus <= 0:
        return []
    candidates = [
        c
        for c in school_contracts(school["id"])
        if c["status"] in ("REQUESTED", "CONFIRMED")
    ]
    candidates.sort(key=lambda c: c["created_at"], reverse=True)
    touched = []
    for c in candidates:
        if surplus <= 0:
            break
        active = c["rounds_requested"] - c["rounds_released"]
        rel = min(surplus, active)
        if rel <= 0:
            continue
        c["rounds_released"] += rel
        surplus -= rel
        if c["status"] == "CONFIRMED":
            c["final_fee_cents"] = hired_fee(
                tournament_of_school(school)["id"], c, "FINAL"
            )
        if c["status"] == "REQUESTED" and c["rounds_released"] >= c["rounds_requested"]:
            c["status"] = "CANCELLED"
        touch(c)
        touched.append(c)
    return touched


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_tournament(t):
    return {
        "id": t["id"],
        "name": t["name"],
        "status": t["status"],
        "results_visibility": t["results_visibility"],
        "registration_opens_at": fmt_dt(t["registration_opens_at"]),
        "registration_locks_at": fmt_dt(t["registration_locks_at"]),
        "prelim_round_count": t["prelim_round_count"],
        "entry_fee_cents": t["entry_fee_cents"],
        "tournament_staff_count": t["tournament_staff_count"],
        "late_fee_starts_at": fmt_dt(t["late_fee_starts_at"]) if t["late_fee_starts_at"] else None,
        "late_fee_surcharge_pct": t["late_fee_surcharge_pct"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_school(s):
    out = {
        "id": s["id"],
        "tournament_id": s["tournament_id"],
        "name": s["name"],
        "status": s["status"],
        "credit_limit_cents": s["credit_limit_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }
    out.update(school_derived(s))
    return out


def serialize_division(d):
    competing = len(division_entries(d["id"], COMPETITION_STATUS_SET))
    return {
        "id": d["id"],
        "tournament_id": d["tournament_id"],
        "event_type": d["event_type"],
        "event_code": d["event_code"],
        "division": d["division"],
        "per_school_entry_cap": d["per_school_entry_cap"],
        "global_entry_cap": d["global_entry_cap"],
        "competing_entry_count": competing,
        "bracket_size": d["bracket_size"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_entry(e):
    return {
        "id": e["id"],
        "school_id": e["school_id"],
        "division_id": e["division_id"],
        "competitor_name": e["competitor_name"],
        "status": e["status"],
        "wins": e["wins"],
        "losses": e["losses"],
        "speaker_points_raw": e["speaker_points_raw"],
        "speaker_points_adjusted": e["speaker_points_adjusted"],
        "rank_points_raw": e["rank_points_raw"],
        "rank_points_adjusted": e["rank_points_adjusted"],
        "opponent_strength": e["opponent_strength"],
        "prelim_rank": e["prelim_rank"],
        "has_received_bye": e["has_received_bye"],
        "seed": e["seed"],
        "final_placement": e["final_placement"],
        "qualification_points": e["qualification_points"],
        "fee_charged_cents": e["fee_charged_cents"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_judge(j):
    assigned = sum(1 for p in db.pairings.values() if p["judge_id"] == j["id"])
    return {
        "id": j["id"],
        "tournament_id": j["tournament_id"],
        "school_id": j["school_id"],
        "name": j["name"],
        "judge_type": j["judge_type"],
        "status": j["status"],
        "commitment_rounds": j["commitment_rounds"],
        "assigned_round_count": assigned,
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
    }


def serialize_judge_conflict(jc):
    return {
        "id": jc["id"],
        "judge_id": jc["judge_id"],
        "school_id": jc["school_id"],
        "reason": jc["reason"],
        "created_at": jc["created_at"],
    }


def serialize_room(r):
    return {
        "id": r["id"],
        "tournament_id": r["tournament_id"],
        "name": r["name"],
        "capacity": r["capacity"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_round(r):
    return {
        "id": r["id"],
        "division_id": r["division_id"],
        "round_number": r["round_number"],
        "kind": r["kind"],
        "starts_at": fmt_dt(r["starts_at"]),
        "ends_at": fmt_dt(r["ends_at"]),
        "status": r["status"],
        "pairings_total": r["pairings_total"],
        "pairings_verified_count": r["pairings_verified_count"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_pairing(p):
    return {
        "id": p["id"],
        "round_id": p["round_id"],
        "format": p["format"],
        "room_id": p["room_id"],
        "judge_id": p["judge_id"],
        "status": p["status"],
        "is_bye": p["is_bye"],
        "winner_entry_id": p["winner_entry_id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_pairing_entry(pe):
    return {
        "id": pe["id"],
        "pairing_id": pe["pairing_id"],
        "entry_id": pe["entry_id"],
        "side": pe["side"],
        "draw_position": pe["draw_position"],
        "created_at": pe["created_at"],
    }


def serialize_ballot(b):
    return {
        "id": b["id"],
        "pairing_id": b["pairing_id"],
        "judge_id": b["judge_id"],
        "status": b["status"],
        "winner_entry_id": b["winner_entry_id"],
        "speaker_points": b["speaker_points"],
        "ranks": b["ranks"],
        "allow_low_point_win": b["allow_low_point_win"],
        "submitted_at": fmt_dt(b["submitted_at"]) if b["submitted_at"] else None,
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_contract(c):
    return {
        "id": c["id"],
        "school_id": c["school_id"],
        "status": c["status"],
        "rounds_requested": c["rounds_requested"],
        "rounds_released": c["rounds_released"],
        "rounds_active": c["rounds_requested"] - c["rounds_released"],
        "hired_judge_id": c["hired_judge_id"],
        "fee_quote_cents": c["fee_quote_cents"],
        "final_fee_cents": c["final_fee_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def order_live_fields(o):
    t = db.tournaments.get(o["tournament_id"])
    if not t:
        return {"headcount_demand": 0, "meal_count": 0, "awards_count": 0}
    headcount = 0
    meals = 0
    awards = 0
    if o["kind"] == "CATERING":
        div_ids = {d["id"] for d in tournament_divisions(t["id"])}
        headcount = sum(
            1
            for e in db.entries.values()
            if e["division_id"] in div_ids and e["status"] in COMPETITION_STATUS_SET
        )
        headcount += sum(
            1
            for j in db.judges.values()
            if j["tournament_id"] == t["id"] and j["status"] == "COMMITTED"
        )
        headcount += t["tournament_staff_count"]
        meals = (headcount * 110 + 99) // 100  # ceil(headcount * 1.10), integer math
    else:
        awards = sum(
            d["bracket_size"] for d in tournament_divisions(t["id"]) if d["bracket_size"]
        )
    return {"headcount_demand": headcount, "meal_count": meals, "awards_count": awards}


def serialize_order(o):
    out = {
        "id": o["id"],
        "tournament_id": o["tournament_id"],
        "kind": o["kind"],
        "status": o["status"],
        "frozen_meal_count": o["frozen_meal_count"],
        "frozen_awards_count": o["frozen_awards_count"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }
    out.update(order_live_fields(o))
    return out
