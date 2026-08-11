"""Business calculations and cascades (PRD section 3, scaffold Table 3)."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, now, stamp_new, touch
from errors import ApiError, ERR_TOO_FEW_TEAMS, ERR_INSUFFICIENT_CAPTAINS

# --- Physical / schedule / selection constants (PRD 2.5) ---
MAX_ROBOT_WEIGHT_KG = 56.7
MAX_FRAME_PERIMETER_CM = 304
FIELD_RESET_MIN_SECONDS = 300
MIN_TEAMS_FOR_MATCHES = 6
ROUNDS_PER_TEAM = 8
ALLIANCE_COUNT = 8
MIN_MATCHES_FOR_SEEDING = 1
CRITICAL_FREEZE_THRESHOLD = 3

# --- score_match constants ---
TECH_FOUL_PENALTY_PER = 5
YELLOW_CARD_PENALTY = 10
RED_CARD_PENALTY = 30

# --- ranking_points constants ---
WIN_RP = 2
TIE_RP = 1
LOSS_RP = 0
AUTO_BONUS_THRESHOLD = 25
ENDGAME_BONUS_THRESHOLD = 20
AUTO_BONUS_RP = 1
ENDGAME_BONUS_RP = 1

# --- travel_reimbursement constants ---
MODE_CAPS = {
    "AIR": 1500000,
    "RAIL": 800000,
    "BUS": 400000,
    "SELF_DRIVE": 300000,
}
TIER1_LIMIT_CENTS = 200000
TIER1_RATE = Decimal("0.80")
TIER2_RATE = Decimal("0.50")

SEVERITY_WEIGHT = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}


# ---------------------------------------------------------------------------
# Lookup helpers over the store
# ---------------------------------------------------------------------------

def teams_of_event(event_id):
    return [t for t in store.teams.values() if t["event_id"] == event_id]


def persons_of_event(event_id):
    return [p for p in store.persons.values() if p.get("_event_id") == event_id]


def persons_of_team(team_id):
    return [p for p in store.persons.values() if p.get("team_id") == team_id]


def violations_of_event(event_id):
    team_ids = {t["id"] for t in teams_of_event(event_id)}
    return [v for v in store.violations.values() if v["team_id"] in team_ids]


def milestones_of_event(event_id):
    return [m for m in store.milestones.values() if m["event_id"] == event_id]


def matches_of_event(event_id):
    return [m for m in store.matches.values() if m["event_id"] == event_id]


def selection_alliances(event_id):
    """Alliances that participate in selection (seeded); ephemeral qualification
    alliances carry seed=None and are excluded from selection logic."""
    return [a for a in store.alliances.values() if a["event_id"] == event_id and a.get("seed") is not None]


# ---------------------------------------------------------------------------
# event_posture + computed counters + screening_expiry (PRD 2.6, 2.9, 2.10)
# ---------------------------------------------------------------------------

def run_screening_expiry(event_id=None):
    """STEP decay: CLEARED -> EXPIRED when current_utc >= screening_expires_at."""
    expired = []
    for p in store.persons.values():
        if event_id is not None and p.get("_event_id") != event_id:
            continue
        exp = p.get("screening_expires_at")
        if p.get("screening_status") == "CLEARED" and exp is not None and now() >= exp:
            p["screening_status"] = "EXPIRED"
            touch(p)
            expired.append(p)
    return expired


def recompute_counts(event):
    eid = event["id"]
    confirmed = [t for t in teams_of_event(eid) if t["registration_status"] == "CONFIRMED"]
    event["registered_team_count"] = len(confirmed)
    confirmed_ids = {t["id"] for t in confirmed}
    event["cleared_mentor_count"] = len([
        p for p in persons_of_event(eid)
        if p.get("team_id") in confirmed_ids
        and p.get("role_kind") == "MENTOR"
        and p.get("screening_status") == "CLEARED"
    ])
    event["outstanding_violation_count"] = len([
        v for v in violations_of_event(eid) if v["resolution_status"] != "RESOLVED"
    ])


def compute_posture(event):
    eid = event["id"]
    critical_open = len([
        v for v in violations_of_event(eid)
        if v["severity"] == "CRITICAL" and v["resolution_status"] != "RESOLVED"
    ])
    uncleared_mentors = 0
    for t in teams_of_event(eid):
        if t["registration_status"] != "CONFIRMED":
            continue
        has_cleared_mentor = any(
            p.get("role_kind") == "MENTOR" and p.get("screening_status") == "CLEARED"
            for p in persons_of_team(t["id"])
        )
        if not has_cleared_mentor:
            uncleared_mentors += 1
    if critical_open >= CRITICAL_FREEZE_THRESHOLD:
        return "FROZEN"
    if critical_open > 0 or uncleared_mentors > 0:
        return "RESTRICTED"
    return "OPEN"


def recompute_posture(event, bump=True):
    """screening_expiry runs on every posture recompute, then posture recomputed."""
    run_screening_expiry(event_id=event["id"])
    event["posture"] = compute_posture(event)
    recompute_counts(event)
    if bump:
        touch(event)


# ---------------------------------------------------------------------------
# score_match (provisional / final variants) and ranking_points
# ---------------------------------------------------------------------------

def breakdown_for(match_id, color):
    for b in store.breakdowns.values():
        if b["match_id"] == match_id and b["alliance_color"] == color:
            return b
    return None


def alliance_score(breakdown, final):
    base = breakdown["auto_points"] + breakdown["teleop_points"] + breakdown["endgame_points"]
    gross = base + breakdown["foul_points_awarded"] - breakdown["tech_foul_count"] * TECH_FOUL_PENALTY_PER
    if final:
        card = breakdown.get("card_issued", "NONE")
        if card == "YELLOW":
            gross -= YELLOW_CARD_PENALTY
        elif card == "RED":
            gross -= RED_CARD_PENALTY
    return max(0, gross)


def run_score_match(match, final):
    red = breakdown_for(match["id"], "RED")
    blue = breakdown_for(match["id"], "BLUE")
    match["red_score"] = alliance_score(red, final)
    match["blue_score"] = alliance_score(blue, final)


def run_ranking_points(match):
    """QUALIFICATION only; provisional scores at SCORED time. Strict > on bonuses."""
    red = breakdown_for(match["id"], "RED")
    blue = breakdown_for(match["id"], "BLUE")
    rs, bs = match["red_score"], match["blue_score"]

    def rp_for(own, opp, bd):
        if own > opp:
            rp = WIN_RP
        elif own == opp:
            rp = TIE_RP
        else:
            rp = LOSS_RP
        if bd["auto_points"] > AUTO_BONUS_THRESHOLD:
            rp += AUTO_BONUS_RP
        if bd["endgame_points"] > ENDGAME_BONUS_THRESHOLD:
            rp += ENDGAME_BONUS_RP
        return rp

    match["red_ranking_points"] = rp_for(rs, bs, red)
    match["blue_ranking_points"] = rp_for(bs, rs, blue)


def match_includes_team(match, team_id):
    return team_id in match.get("_red_teams", []) or team_id in match.get("_blue_teams", [])


def compute_team_aggregates(team, include_scored=False):
    """team_ranking_score: chronological variant uses FINALIZED qual matches only;
    forward_looking variant additionally includes SCORED. 4dp ROUND_HALF_UP."""
    statuses = {"FINALIZED", "SCORED"} if include_scored else {"FINALIZED"}
    played = [
        m for m in matches_of_event(team["event_id"])
        if m["series"] == "QUALIFICATION"
        and m["status"] in statuses
        and match_includes_team(m, team["id"])
    ]
    played.sort(key=lambda m: (m["match_number"], m.get("created_at") or now(), m.get("_seq", 0)))
    rp_sum = 0
    tb_sum = 0
    n = 0
    for m in played:
        if team["id"] in m.get("_red_teams", []):
            side = "RED"
        else:
            side = "BLUE"
        rp_sum += m.get("red_ranking_points" if side == "RED" else "blue_ranking_points") or 0
        bd = breakdown_for(m["id"], side)
        if bd is not None:
            tb_sum += bd["auto_points"] + bd["endgame_points"]
        n += 1
    if n == 0:
        return Decimal("0.0000"), Decimal("0.0000"), 0
    q = Decimal("0.0001")
    score = (Decimal(rp_sum) / Decimal(n)).quantize(q, rounding=ROUND_HALF_UP)
    tie = (Decimal(tb_sum) / Decimal(n)).quantize(q, rounding=ROUND_HALF_UP)
    return score, tie, n


def recompute_team_aggregates(team, bump=True):
    score, tie, n = compute_team_aggregates(team, include_scored=False)
    team["ranking_score"] = score
    team["ranking_tie_break"] = tie
    team["matches_played"] = n
    if bump:
        touch(team)


def recompute_match_teams(match):
    for tid in match.get("_red_teams", []) + match.get("_blue_teams", []):
        t = store.teams.get(tid)
        if t is not None:
            recompute_team_aggregates(t)


# ---------------------------------------------------------------------------
# generate_match_schedule (FrcEvent INSPECTION -> MATCHES_RUNNING)
# ---------------------------------------------------------------------------

def eligible_match_teams(event):
    teams = [
        t for t in teams_of_event(event["id"])
        if t["registration_status"] == "CONFIRMED"
        and t["robot_inspection_status"] in ("PASSED", "WAIVED")
    ]
    teams.sort(key=lambda t: (t["team_number"], t.get("created_at") or now(), t.get("_seq", 0)))
    return teams


def generate_match_schedule(event):
    teams = eligible_match_teams(event)
    n = len(teams)
    if n < MIN_TEAMS_FOR_MATCHES:
        raise ApiError(ERR_TOO_FEW_TEAMS, 409, "Fewer than %d eligible teams for match generation" % MIN_TEAMS_FOR_MATCHES)

    field_count = max(1, event["field_count"])
    rounds = math.ceil(n / 6.0) * ROUNDS_PER_TEAM
    matches_per_round = n // 6
    slot_seconds = max(event["match_cycle_minutes"] * 60, FIELD_RESET_MIN_SECONDS)
    base = event.get("start_date") if isinstance(event.get("start_date"), type(now())) else now()
    if base is None:
        base = now()

    seq = 0
    for r in range(rounds):
        offset = (r * 6) % n
        rotated = teams[offset:] + teams[:offset]
        for k in range(matches_per_round):
            members = rotated[6 * k: 6 * k + 6]
            if len(members) < 6:
                continue
            red_members = members[:3]
            blue_members = members[3:6]
            red_alliance = _create_ephemeral_alliance(event, red_members)
            blue_alliance = _create_ephemeral_alliance(event, blue_members)
            seq += 1
            match = {
                "event_id": event["id"],
                "match_number": seq,
                "series": "QUALIFICATION",
                "scheduled_at": base + timedelta(seconds=(seq - 1) // field_count * slot_seconds),
                "field_index": (seq - 1) % field_count + 1,
                "red_alliance_id": red_alliance["id"],
                "blue_alliance_id": blue_alliance["id"],
                "status": "SCHEDULED",
                "red_score": None,
                "blue_score": None,
                "red_ranking_points": None,
                "blue_ranking_points": None,
                "_red_teams": [t["id"] for t in red_members],
                "_blue_teams": [t["id"] for t in blue_members],
                "_scored_by": None,
            }
            stamp_new(match)
            store.matches[match["id"]] = match


def _create_ephemeral_alliance(event, member_teams):
    alliance = {
        "event_id": event["id"],
        "seed": None,
        "captain_team_id": member_teams[0]["id"],
        "pick1_team_id": member_teams[1]["id"],
        "pick2_team_id": member_teams[2]["id"],
        "status": "FORMING",
        "_ephemeral": True,
    }
    stamp_new(alliance)
    store.alliances[alliance["id"]] = alliance
    return alliance


# ---------------------------------------------------------------------------
# Alliance selection: seed captains, snake draft order
# ---------------------------------------------------------------------------

def _ranking_sort_key(t):
    return (
        -float(t.get("ranking_score") or 0),
        -float(t.get("ranking_tie_break") or 0),
        t["team_number"],
        t.get("created_at") or now(),
        t.get("_seq", 0),
    )


def seed_alliance_captains(event):
    candidates = [
        t for t in teams_of_event(event["id"])
        if t["registration_status"] == "CONFIRMED" and t["matches_played"] >= MIN_MATCHES_FOR_SEEDING
    ]
    candidates.sort(key=_ranking_sort_key)
    if len(candidates) < ALLIANCE_COUNT:
        raise ApiError(
            ERR_INSUFFICIENT_CAPTAINS,
            409,
            "Fewer than %d eligible captains" % ALLIANCE_COUNT,
        )
    captains = candidates[:ALLIANCE_COUNT]
    created = []
    for i, c in enumerate(captains):
        alliance = {
            "event_id": event["id"],
            "seed": i + 1,
            "captain_team_id": c["id"],
            "pick1_team_id": None,
            "pick2_team_id": None,
            "status": "FORMING",
        }
        stamp_new(alliance)
        store.alliances[alliance["id"]] = alliance
        created.append(alliance)
    return created


def snake_seed_order(event, round_index):
    """Round 1: seed ascending; round 2: seed descending."""
    alliances = sorted(selection_alliances(event["id"]), key=lambda a: a["seed"])
    if round_index == 2:
        alliances = list(reversed(alliances))
    return alliances


def picks_made_in_round(event, round_index):
    field = "pick1_team_id" if round_index == 1 else "pick2_team_id"
    return len([a for a in selection_alliances(event["id"]) if a.get(field) is not None])


def current_captain_for(event, round_index):
    order = snake_seed_order(event, round_index)
    made = picks_made_in_round(event, round_index)
    if made >= len(order):
        return None
    return order[made]["captain_team_id"]


def is_pick_eligible(event, team):
    if team["registration_status"] != "CONFIRMED":
        return False
    if team.get("is_alliance_captain"):
        return False
    for a in selection_alliances(event["id"]):
        if a["status"] in ("FORMING", "SEALED") and team["id"] in (
            a.get("captain_team_id"), a.get("pick1_team_id"), a.get("pick2_team_id")
        ):
            return False
    return True


def seal_forming_alliances(event):
    for a in selection_alliances(event["id"]):
        if a["status"] == "FORMING" and a.get("captain_team_id") and a.get("pick1_team_id") and a.get("pick2_team_id"):
            a["status"] = "SEALED"
            touch(a)
            captain = store.teams.get(a["captain_team_id"])
            if captain is not None and not captain.get("is_alliance_captain"):
                captain["is_alliance_captain"] = True
                touch(captain)


# ---------------------------------------------------------------------------
# award_winner_selection (PRD 3.7)
# ---------------------------------------------------------------------------

def select_award_winner(event, award):
    """Returns the winning Team row, or None when the eligible pool is empty."""
    if award.get("requires_interview"):
        scores = {}
        for s in store.interview_slots.values():
            if s["award_id"] == award["id"] and s["status"] == "COMPLETED" and s.get("score") is not None:
                scores.setdefault(s["team_id"], []).append(s["score"])
        eligible = []
        for tid, vals in scores.items():
            t = store.teams.get(tid)
            if t is not None:
                eligible.append((t, float(sum(vals)) / float(len(vals))))
        if not eligible:
            return None
        eligible.sort(key=lambda pair: (-pair[1],) + _ranking_sort_key(pair[0]))
        return eligible[0][0]

    confirmed = [t for t in teams_of_event(event["id"]) if t["registration_status"] == "CONFIRMED"]

    if award["award_kind"] == "SAFETY":
        # Fewest open violations wins; severity-weighted count breaks open-count ties.
        decorated = []
        for t in confirmed:
            open_vs = [v for v in store.violations.values()
                       if v["team_id"] == t["id"] and v["resolution_status"] != "RESOLVED"]
            weighted = sum(SEVERITY_WEIGHT.get(v["severity"], 0) for v in open_vs)
            decorated.append((t, len(open_vs), weighted))
        if not decorated:
            return None
        decorated.sort(key=lambda d: (d[1], d[2]) + _ranking_sort_key(d[0]))
        return decorated[0][0]

    if award["award_kind"] == "ROOKIE_ALL_STAR":
        pool = [t for t in confirmed if t.get("is_rookie") is True]
    else:
        pool = list(confirmed)
    if not pool:
        return None
    pool.sort(key=_ranking_sort_key)
    return pool[0]


# ---------------------------------------------------------------------------
# travel_reimbursement (marginal, per-tier rounding) — PRD 3.8
# ---------------------------------------------------------------------------

def compute_reimbursement(booking):
    cap = MODE_CAPS[booking["mode"]]
    eligible = min(booking["cost_cents"], cap)
    tier1_amount = min(eligible, TIER1_LIMIT_CENTS)
    tier2_amount = max(0, eligible - TIER1_LIMIT_CENTS)
    tier1 = (Decimal(tier1_amount) * TIER1_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    tier2 = (Decimal(tier2_amount) * TIER2_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(tier1 + tier2)


# ---------------------------------------------------------------------------
# championship_qualification_run (FrcEvent AWARDS -> CLOSED) — PRD 3.8
# ---------------------------------------------------------------------------

def run_championship_qualification(event):
    slots = event["championship_slots"]
    awarded = set()

    def presented_award_winner(kind):
        for a in store.awards.values():
            if a["event_id"] == event["id"] and a["award_kind"] == kind and a["status"] == "PRESENTED":
                return a.get("winner_team_id")
        return None

    chairmans = presented_award_winner("CHAIRMANS")
    if chairmans and slots > 0:
        awarded.add(chairmans)
        slots -= 1

    ei = presented_award_winner("ENGINEERING_INSPIRATION")
    if ei and slots > 0 and ei not in awarded:
        awarded.add(ei)
        slots -= 1

    champion = None
    for a in selection_alliances(event["id"]):
        if a["status"] == "CHAMPION":
            champion = a
            break
    if champion is not None:
        for tid in (champion.get("captain_team_id"), champion.get("pick1_team_id"), champion.get("pick2_team_id")):
            if tid and slots > 0 and tid not in awarded:
                awarded.add(tid)
                slots -= 1

    candidates = [
        t for t in teams_of_event(event["id"])
        if t["registration_status"] == "CONFIRMED" and t["id"] not in awarded
    ]
    candidates.sort(key=_ranking_sort_key)
    for t in candidates:
        if slots <= 0:
            break
        awarded.add(t["id"])
        slots -= 1

    for t in teams_of_event(event["id"]):
        qualified = t["id"] in awarded
        if t.get("qualified_for_championship") != qualified:
            t["qualified_for_championship"] = qualified
            touch(t)
