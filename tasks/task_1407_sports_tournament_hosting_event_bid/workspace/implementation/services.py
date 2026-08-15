"""Domain services: queries, serializers, calculations, state-machine cascades.

All computed fields are evaluated live at serialization time unless the spec
pins a snapshot (hotel final rebate/attrition at reconcile; settlement totals
at certify; impact report figures at submit/audit).
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, base_entity, iso, now, parse_date, touch
from errors import ApiError, ERR_NOT_FOUND

# ---------------------------------------------------------------------------
# Status vocabularies
# ---------------------------------------------------------------------------

POSTURES = {"BIDDING", "AWARDED", "PLANNING", "REGISTRATION_OPEN",
            "COMPETITION_SETUP", "LIVE", "COMPLETED", "SETTLED",
            "BID_LOST", "CANCELLED"}

BID_TERMINAL = {"AWARDED", "REJECTED", "WITHDRAWN", "SUPERSEDED"}
BID_NONTERMINAL = {"DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED"}
REQ_TERMINAL = {"VERIFIED", "WAIVED"}
BLOCK_TERMINAL = {"SETTLED", "RELEASED"}
BOOKING_TERMINAL = {"CHECKED_OUT", "CANCELLED", "NO_SHOW"}
DIVISION_TERMINAL = {"COMPLETED", "CANCELLED"}
TEAM_TERMINAL = {"ELIMINATED", "FINISHED", "CHAMPION", "WITHDRAWN", "DISQUALIFIED"}
MATCH_TERMINAL = {"FINAL", "FORFEITED", "CANCELLED"}
OFFICIAL_TERMINAL = {"INACTIVE"}
ASSIGNMENT_TERMINAL = {"DECLINED", "RELEASED", "WORKED"}
VOLUNTEER_TERMINAL = {"REJECTED", "INACTIVE"}
SHIFT_TERMINAL = {"COMPLETED", "CANCELLED"}
SIGNUP_TERMINAL = {"WORKED", "NO_SHOW", "CANCELLED"}
ALERT_TERMINAL = {"RESOLVED", "EXPIRED"}
REPORT_TERMINAL = {"ACCEPTED"}
SETTLEMENT_TERMINAL = {"PAID"}

# Teams counted by Event.registered_team_count / Division.entered_team_count
ENTERED_PLUS = {"ENTERED", "ROSTER_SUBMITTED", "ELIGIBLE", "CHECKED_IN",
                "ELIMINATED", "FINISHED", "CHAMPION", "DISQUALIFIED"}
# Division.eligible_team_count
ELIGIBLE_PLUS = {"ELIGIBLE", "CHECKED_IN", "ELIMINATED", "FINISHED", "CHAMPION"}
# Bookings counting toward pickup (estimated/forward-looking set)
PICKUP_FORWARD = {"RESERVED", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "NO_SHOW"}
# Bookings counting toward actualized pickup (final/audited set)
PICKUP_FINAL = {"CHECKED_OUT", "NO_SHOW"}
# Matches considered finalized for Event.finalized_match_count
MATCH_FINALIZED = {"FINAL", "FORFEITED"}
# Fee-paid team statuses for registration revenue
FEE_PAID = {"ROSTER_SUBMITTED", "ELIGIBLE", "CHECKED_IN", "ELIMINATED",
            "FINISHED", "CHAMPION", "DISQUALIFIED"}

ASSIGNMENT_ACTIVE = {"PROPOSED", "ACCEPTED", "WORKED"}  # assigned_game_count set

REQUIREMENT_KINDS = {"VENUE_CONTRACT", "HOTEL_BLOCKS", "INSURANCE_CERT",
                     "FINANCIAL_GUARANTEE", "VOLUNTEER_PLAN", "MEDICAL_PLAN",
                     "TRANSPORT_PLAN", "LEGACY_PLAN"}
SURFACE_TYPES = {"TURF", "GRASS", "COURT", "INDOOR"}
BOOKER_TYPES = {"TEAM", "OFFICIAL", "COMMISSION"}
CERT_LEVELS = {"TRAINEE", "REGIONAL", "NATIONAL"}
SLOT_ROLES = {"CREW_CHIEF", "ASSISTANT"}
SHIFT_ROLES = {"FIELD_MARSHAL", "REGISTRATION_DESK", "SCORE_RUNNER",
               "HOSPITALITY", "PARKING"}
SEVERITIES = {"WATCH", "WARNING", "EMERGENCY"}
BOOKING_ACTIONS = {"CONFIRM", "CHECK_IN", "CHECK_OUT", "CANCEL", "NO_SHOW"}
OFFICIAL_ACTIONS = {"VET", "ACTIVATE", "SUSPEND", "REINSTATE", "DEACTIVATE"}
VOLUNTEER_ACTIONS = {"APPROVE", "REJECT", "ACTIVATE", "DEACTIVATE"}

# Calculation constants (SCAFFOLD §1.3)
AWARD_MIN_SCORE = 80
CANCEL_FEE_RATE = Decimal("0.5")
ATTRITION_RATE = Decimal("0.5")
PER_CAPITA_SPEND_CENTS = 14500
BASE_STIPEND_CENTS = 9999
LEVEL_MULTIPLIER = {
    "TRAINEE": Decimal("0.6"),
    "REGIONAL": Decimal("1.0"),
    "NATIONAL": Decimal("1.5"),
}
TIER1_CAP_CENTS = 5_000_000
TIER1_RATE = Decimal("0.08")
TIER2_CAP_CENTS = 10_000_000
TIER2_RATE = Decimal("0.10")
TIER3_RATE = Decimal("0.12")


def _cents(x):
    """Round half up to whole cents, returned as int."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lookups (existence checking is done by callers via get_or_404)
# ---------------------------------------------------------------------------

def get_or_404(mapping, rid, what):
    obj = mapping.get(rid)
    if obj is None:
        raise ApiError(*ERR_NOT_FOUND, f"The requested {what} does not exist.")
    return obj


def bids_of_event(event_id):
    return [b for b in STORE.bids.values() if b["event_id"] == event_id]


def reqs_of_bid(bid_id):
    return [r for r in STORE.requirements.values() if r["bid_id"] == bid_id]


def venues_of_event(event_id):
    return [v for v in STORE.venues.values() if v["event_id"] == event_id]


def fields_of_venue(venue_id):
    return [f for f in STORE.fields.values() if f["venue_id"] == venue_id]


def blocks_of_event(event_id):
    return [b for b in STORE.hotel_blocks.values() if b["event_id"] == event_id]


def bookings_of_block(block_id):
    return [b for b in STORE.room_bookings.values() if b["hotel_block_id"] == block_id]


def bookings_of_event(event_id):
    out = []
    for b in STORE.room_bookings.values():
        block = STORE.hotel_blocks.get(b["hotel_block_id"])
        if block and block["event_id"] == event_id:
            out.append(b)
    return out


def divisions_of_event(event_id):
    return [d for d in STORE.divisions.values() if d["event_id"] == event_id]


def teams_of_division(division_id):
    return [t for t in STORE.teams.values() if t["division_id"] == division_id]


def teams_of_event(event_id):
    out = []
    for t in STORE.teams.values():
        d = STORE.divisions.get(t["division_id"])
        if d and d["event_id"] == event_id:
            out.append(t)
    return out


def matches_of_division(division_id):
    return [m for m in STORE.matches.values() if m["division_id"] == division_id]


def matches_of_event(event_id):
    out = []
    for m in STORE.matches.values():
        d = STORE.divisions.get(m["division_id"])
        if d and d["event_id"] == event_id:
            out.append(m)
    return out


def assignments_of_match(match_id):
    return [a for a in STORE.assignments.values() if a["match_id"] == match_id]


def assignments_of_official(official_id):
    return [a for a in STORE.assignments.values() if a["official_id"] == official_id]


def volunteers_of_event(event_id):
    return [v for v in STORE.volunteers.values() if v["event_id"] == event_id]


def shifts_of_event(event_id):
    return [s for s in STORE.shifts.values() if s["event_id"] == event_id]


def signups_of_shift(shift_id):
    return [g for g in STORE.signups.values() if g["shift_id"] == shift_id]


def signups_of_volunteer(volunteer_id):
    return [g for g in STORE.signups.values() if g["volunteer_id"] == volunteer_id]


def alerts_of_event(event_id):
    return [a for a in STORE.alerts.values() if a["event_id"] == event_id]


def reports_of_event(event_id):
    return [r for r in STORE.reports.values() if r["event_id"] == event_id]


def settlements_of_event(event_id):
    return [s for s in STORE.settlements.values() if s["event_id"] == event_id]


def event_of_division(div):
    return STORE.events.get(div["event_id"])


def event_of_match(m):
    d = STORE.divisions.get(m["division_id"])
    return STORE.events.get(d["event_id"]) if d else None


def event_of_field(f):
    v = STORE.venues.get(f["venue_id"])
    return STORE.events.get(v["event_id"]) if v else None


def event_of_block(b):
    return STORE.events.get(b["event_id"])


def event_of_booking(bk):
    b = STORE.hotel_blocks.get(bk["hotel_block_id"])
    return STORE.events.get(b["event_id"]) if b else None


def event_of_team(t):
    d = STORE.divisions.get(t["division_id"])
    return STORE.events.get(d["event_id"]) if d else None


def event_of_volunteer(v):
    return STORE.events.get(v["event_id"])


def event_of_shift(s):
    return STORE.events.get(s["event_id"])


def event_of_signup(g):
    s = STORE.shifts.get(g["shift_id"])
    return STORE.events.get(s["event_id"]) if s else None


def event_of_alert(a):
    return STORE.events.get(a["event_id"])


def event_of_report(r):
    return STORE.events.get(r["event_id"])


def event_of_settlement(s):
    return STORE.events.get(s["event_id"])


# ---------------------------------------------------------------------------
# Calculation: bid_completeness_score (PRD §3.1)
# ---------------------------------------------------------------------------

def bid_review_score(bid):
    total = 0
    for r in reqs_of_bid(bid["id"]):
        if r["status"] == "VERIFIED":
            total += r["weight_points"]
        elif r["status"] == "WAIVED":
            total += r["weight_points"] // 2
    return total


# ---------------------------------------------------------------------------
# Calculation: hotel_pickup_rebate (PRD §3.3) — dual variant
# ---------------------------------------------------------------------------

def _block_nights(block):
    return (parse_date(block["block_end_date"]) - parse_date(block["block_start_date"])).days


def block_supply_room_nights(block):
    return block["contracted_rooms_per_night"] * _block_nights(block)


def picked_up_room_nights(block, status_set):
    return sum(bk["room_nights"] for bk in bookings_of_block(block["id"])
               if bk["status"] in status_set)


def rebate_computation(block, status_set):
    """Returns (picked_up, pickup_pct Decimal 4dp, tier, rebate_cents,
    attrition_penalty_cents)."""
    supply = block_supply_room_nights(block)
    picked = picked_up_room_nights(block, status_set)
    if supply > 0:
        pct = (Decimal(picked) / Decimal(supply)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP)
    else:
        pct = Decimal("0.0000")
    if pct >= Decimal("1.0000"):
        tier, rate = "TIER_3", Decimal("0.12")
    elif pct >= Decimal("0.9000"):
        tier, rate = "TIER_2", Decimal("0.10")
    elif pct >= Decimal("0.8000"):
        tier, rate = "TIER_1", Decimal("0.07")
    else:
        tier, rate = "TIER_0", Decimal("0.00")
    # Per-booking rounding first, then sum (pinned order).
    rebate = sum(_cents(Decimal(bk["total_charge_cents"]) * rate)
                 for bk in bookings_of_block(block["id"])
                 if bk["status"] in status_set)
    floor_pct = Decimal(1) - Decimal(str(block["attrition_allowance_pct"]))
    if pct < floor_pct:
        shortfall = int((floor_pct * Decimal(supply)).to_integral_value(
            rounding="ROUND_FLOOR")) - picked
        penalty = _cents(Decimal(shortfall) * Decimal(block["room_rate_cents"])
                         * ATTRITION_RATE)
    else:
        penalty = 0
    return picked, pct, tier, rebate, penalty


# ---------------------------------------------------------------------------
# Calculation: impact_direct_spend (PRD §3.9) — dual variant
# ---------------------------------------------------------------------------

def impact_figures(event_id, status_set, attendance):
    bookings = [b for b in bookings_of_event(event_id) if b["status"] in status_set]
    room_nights = sum(b["room_nights"] for b in bookings)
    spend = sum(b["total_charge_cents"] for b in bookings) + attendance * PER_CAPITA_SPEND_CENTS
    return room_nights, spend


# ---------------------------------------------------------------------------
# Calculation: sanction_fee (PRD §3.9) — marginal tiers, per-slice rounding
# ---------------------------------------------------------------------------

def sanction_fee_cents(registration_revenue_cents):
    rev = Decimal(registration_revenue_cents)
    t1 = min(rev, Decimal(TIER1_CAP_CENTS))
    t2 = min(max(rev - Decimal(TIER1_CAP_CENTS), Decimal(0)),
             Decimal(TIER2_CAP_CENTS - TIER1_CAP_CENTS))
    t3 = max(rev - Decimal(TIER2_CAP_CENTS), Decimal(0))
    return (_cents(t1 * TIER1_RATE) + _cents(t2 * TIER2_RATE)
            + _cents(t3 * TIER3_RATE))


# ---------------------------------------------------------------------------
# Calculation: official_stipend_total (PRD §3.9) — per-assignment rounding
# ---------------------------------------------------------------------------

def officials_stipend_total_cents(event_id):
    total = 0
    for a in STORE.assignments.values():
        if a["status"] != "WORKED":
            continue
        m = STORE.matches.get(a["match_id"])
        if not m:
            continue
        d = STORE.divisions.get(m["division_id"])
        if not d or d["event_id"] != event_id:
            continue
        o = STORE.officials.get(a["official_id"])
        mult = LEVEL_MULTIPLIER[o["certification_level"]] if o else Decimal(1)
        total += _cents(Decimal(BASE_STIPEND_CENTS) * mult)
    return total


def registration_revenue_cents(event_id):
    total = 0
    for t in teams_of_event(event_id):
        if t["status"] in FEE_PAID:
            d = STORE.divisions.get(t["division_id"])
            total += d["registration_fee_cents"] if d else 0
    return total


# ---------------------------------------------------------------------------
# Calculation: volunteer_hours (PRD §3.8)
# ---------------------------------------------------------------------------

def volunteer_hours_worked(volunteer_id):
    total = Decimal(0)
    for g in signups_of_volunteer(volunteer_id):
        if g["status"] == "WORKED" and g["credited_hours"] is not None:
            total += Decimal(str(g["credited_hours"]))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def shift_duration_hours(shift):
    """(ends_at - starts_at) in minutes / 60, rounded half up to 2dp."""
    minutes = Decimal(str((shift["ends_at"] - shift["starts_at"]).total_seconds())) / Decimal(60)
    hours = minutes / Decimal(60)
    return float(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Calculation: bracket_seeding (PRD §3.5)
# ---------------------------------------------------------------------------

def assign_seeds(division):
    """Order ELIGIBLE teams by strength_rating DESC, created_at ASC; assign 1..N."""
    cands = [t for t in teams_of_division(division["id"]) if t["status"] == "ELIGIBLE"]
    cands.sort(key=lambda t: (-t["strength_rating"], t["created_at"], t["_seq"]))
    for i, t in enumerate(cands, start=1):
        t["seed_number"] = i
        touch(t)
    return cands


# ---------------------------------------------------------------------------
# Calculation: bracket_topology (PRD §3.5)
# ---------------------------------------------------------------------------

def _slot_firsts(n):
    """Home seeds of round-1 slots 1..n/2 for a bracket of size n (power of 2).

    Slot k pairs seed F[k] with seed n+1-F[k]. Produces the standard balanced
    draw: n=4 -> [1,2] (pairs 1v4, 2v3); n=8 -> [1,4,3,2] (pairs 1v8, 4v5,
    3v6, 2v7), so the 2-seed's quarter sits at the bottom of the draw.
    """
    if n == 2:
        return [1]
    prev = _slot_firsts(n // 2)
    half = n // 2
    out = []
    for i, a in enumerate(prev):
        if i % 2 == 0:
            out.append(a)
            out.append(half + 1 - a)
        else:
            out.append(half + 1 - a)
            out.append(a)
    return out


def publish_bracket(division):
    """Generate matches per bracket_topology; returns list of created matches."""
    seeded = [t for t in teams_of_division(division["id"]) if t["seed_number"] is not None]
    by_seed = {t["seed_number"]: t for t in seeded}
    n = len(seeded)
    size = 2
    while size < max(2, n):
        size *= 2
    rounds = size.bit_length() - 1  # log2(size)
    byes = size - n
    firsts = _slot_firsts(size)

    matches = {}  # (round, slot) -> match dict
    # Round 1: create real matches only where the low-half seed has no bye.
    for k in range(1, size // 2 + 1):
        hs = firsts[k - 1]
        if hs <= byes:
            continue  # bye: no match created
        away_seed = size + 1 - hs
        m = base_entity()
        m.update({
            "division_id": division["id"],
            "round_number": 1,
            "bracket_slot": k,
            "home_team_id": by_seed[hs]["id"],
            "away_team_id": by_seed[away_seed]["id"],
            "winner_advances_to_match_id": None,
            "field_id": None,
            "scheduled_start": None,
            "scheduled_end": None,
            "original_scheduled_start": None,
            "status": "PENDING_TEAMS",
            "home_score": None,
            "away_score": None,
            "winner_team_id": None,
        })
        STORE.matches[m["id"]] = m
        matches[(1, k)] = m
    # Later rounds: all matches created empty.
    for r in range(2, rounds + 1):
        for k in range(1, size // (2 ** r) + 1):
            m = base_entity()
            m.update({
                "division_id": division["id"],
                "round_number": r,
                "bracket_slot": k,
                "home_team_id": None,
                "away_team_id": None,
                "winner_advances_to_match_id": None,
                "field_id": None,
                "scheduled_start": None,
                "scheduled_end": None,
                "original_scheduled_start": None,
                "status": "PENDING_TEAMS",
                "home_score": None,
                "away_score": None,
                "winner_team_id": None,
            })
            STORE.matches[m["id"]] = m
            matches[(r, k)] = m
    # Wire advancement: (r, k) -> (r+1, ceil(k/2)).
    for (r, k), m in matches.items():
        if r < rounds:
            target = matches.get((r + 1, -(-k // 2)))
            if target is not None:
                m["winner_advances_to_match_id"] = target["id"]
    # Place bye seeds directly into their round-2 slots at publish time.
    if rounds >= 2:
        for s in range(1, byes + 1):
            k = firsts.index(s) + 1  # the phantom round-1 slot of seed s
            target = matches.get((2, -(-k // 2)))
            if target is not None:
                if k % 2 == 1:
                    target["home_team_id"] = by_seed[s]["id"]
                else:
                    target["away_team_id"] = by_seed[s]["id"]
    division["bracket_size"] = size
    division["total_rounds"] = rounds
    return list(matches.values())


# ---------------------------------------------------------------------------
# Match window helpers
# ---------------------------------------------------------------------------

def _overlaps(s1, e1, s2, e2):
    """Half-open interval intersection: [s1,e1) vs [s2,e2)."""
    return s1 < e2 and s2 < e1


def field_window_conflicts(field_id, start, end, exclude_match_id=None):
    for m in STORE.matches.values():
        if m["id"] == exclude_match_id:
            continue
        if m["field_id"] != field_id:
            continue
        if m["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if m["scheduled_start"] is None or m["scheduled_end"] is None:
            continue
        if _overlaps(start, end, m["scheduled_start"], m["scheduled_end"]):
            return m
    return None


def official_window_conflict(official_id, start, end):
    """Candidate window expanded +/-30 minutes vs ACCEPTED/WORKED assignments."""
    from datetime import timedelta as _td
    buf_start = start - _td(minutes=30)
    buf_end = end + _td(minutes=30)
    for a in assignments_of_official(official_id):
        if a["status"] not in ("ACCEPTED", "WORKED"):
            continue
        m = STORE.matches.get(a["match_id"])
        if not m or m["scheduled_start"] is None or m["scheduled_end"] is None:
            continue
        if _overlaps(buf_start, buf_end, m["scheduled_start"], m["scheduled_end"]):
            return a
    return None


def official_daily_load(official_id, day):
    count = 0
    for a in assignments_of_official(official_id):
        if a["status"] not in ("ACCEPTED", "WORKED"):
            continue
        m = STORE.matches.get(a["match_id"])
        if m and m["scheduled_start"] is not None and m["scheduled_start"].date() == day:
            count += 1
    return count


def official_assigned_game_count(official_id):
    return sum(1 for a in assignments_of_official(official_id)
               if a["status"] in ASSIGNMENT_ACTIVE)


# ---------------------------------------------------------------------------
# Reschedule queue order (PRD §3.6)
# ---------------------------------------------------------------------------

def reschedule_queue_predecessors(match):
    """Other RESCHEDULE_QUEUE matches of the same division sorting earlier."""
    queue = [m for m in matches_of_division(match["division_id"])
             if m["status"] == "RESCHEDULE_QUEUE" and m["id"] != match["id"]]

    def key(m):
        return (m["round_number"],
                m["original_scheduled_start"] is None,
                m["original_scheduled_start"] or m["created_at"],
                m["created_at"],
                m["_seq"])

    this = key(match)
    return [m for m in queue if key(m) < this]


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def release_assignment(a, reason):
    a["status"] = "RELEASED"
    a["released_reason"] = reason
    touch(a)


def release_match_assignments(match, reason):
    for a in assignments_of_match(match["id"]):
        if a["status"] in ("PROPOSED", "ACCEPTED"):
            release_assignment(a, reason)


def apply_match_result(match, winner_id):
    """Shared advancement/elimination cascade for FINAL and FORFEITED.

    Caller sets match status/scores before invoking. Returns nothing.
    """
    division = STORE.divisions.get(match["division_id"])
    loser_id = None
    if match["home_team_id"] == winner_id:
        loser_id = match["away_team_id"]
    elif match["away_team_id"] == winner_id:
        loser_id = match["home_team_id"]
    match["winner_team_id"] = winner_id

    is_final = division is not None and match["round_number"] == division.get("total_rounds")

    # Advancement: winner fills home slot when this match's bracket_slot is odd.
    if match["winner_advances_to_match_id"]:
        target = STORE.matches.get(match["winner_advances_to_match_id"])
        if target is not None:
            if match["bracket_slot"] % 2 == 1:
                target["home_team_id"] = winner_id
            else:
                target["away_team_id"] = winner_id
            touch(target)

    # Elimination / championship.
    winner = STORE.teams.get(winner_id)
    loser = STORE.teams.get(loser_id) if loser_id else None
    if is_final:
        if winner is not None and winner["status"] in ("ELIGIBLE", "CHECKED_IN"):
            winner["status"] = "CHAMPION"
            touch(winner)
        if loser is not None and loser["status"] in ("ELIGIBLE", "CHECKED_IN"):
            loser["status"] = "FINISHED"
            touch(loser)
    else:
        if loser is not None and loser["status"] in ("ELIGIBLE", "CHECKED_IN"):
            loser["status"] = "ELIMINATED"
            touch(loser)

    # Division completion bubble-up.
    if division is not None and division["status"] == "BRACKET_PUBLISHED":
        remaining = [m for m in matches_of_division(division["id"])
                     if m["status"] not in MATCH_TERMINAL]
        if not remaining:
            division["status"] = "COMPLETED"
            touch(division)


def cancel_event_cascade(event, from_posture):
    """Event -> CANCELLED cascades, cumulative by maturity (PRD §2.5)."""
    if from_posture == "BIDDING":
        for b in bids_of_event(event["id"]):
            if b["status"] in BID_NONTERMINAL:
                b["status"] = "WITHDRAWN"
                touch(b)
        event["active_bid_id"] = None
    if from_posture in ("AWARDED", "PLANNING", "REGISTRATION_OPEN", "COMPETITION_SETUP"):
        for block in blocks_of_event(event["id"]):
            if block["status"] in ("NEGOTIATING", "CONTRACTED"):
                for bk in bookings_of_block(block["id"]):
                    if bk["status"] in ("RESERVED", "CONFIRMED"):
                        bk["status"] = "CANCELLED"
                        bk["cancellation_fee_cents"] = 0
                        touch(bk)
                block["status"] = "RELEASED"
                touch(block)
    if from_posture in ("REGISTRATION_OPEN", "COMPETITION_SETUP"):
        for t in teams_of_event(event["id"]):
            if t["status"] in ("ENTERED", "WAITLISTED", "ROSTER_SUBMITTED", "ELIGIBLE"):
                t["status"] = "WITHDRAWN"
                touch(t)
    if from_posture == "COMPETITION_SETUP":
        for m in matches_of_event(event["id"]):
            if m["status"] in ("PENDING_TEAMS", "SCHEDULED", "RESCHEDULE_QUEUE"):
                release_match_assignments(m, "MATCH_CANCELLED")
                m["status"] = "CANCELLED"
                touch(m)


def shift_recompute_bubble(shift):
    """Maintain confirmed_count and the OPEN <-> FILLED bubble."""
    if shift["status"] not in ("OPEN", "FILLED"):
        return
    count = sum(1 for g in signups_of_shift(shift["id"]) if g["status"] in ("CONFIRMED", "WORKED"))
    if count >= shift["capacity"] and shift["status"] == "OPEN":
        shift["status"] = "FILLED"
        touch(shift)
    elif count < shift["capacity"] and shift["status"] == "FILLED":
        shift["status"] = "OPEN"
        touch(shift)


def division_entered_count(division):
    return sum(1 for t in teams_of_division(division["id"]) if t["status"] in ENTERED_PLUS)


def division_eligible_count(division):
    return sum(1 for t in teams_of_division(division["id"]) if t["status"] in ELIGIBLE_PLUS)


# ---------------------------------------------------------------------------
# Serializers (whitelist declared fields; compute derived fields live)
# ---------------------------------------------------------------------------

def ser_event(e):
    teams = teams_of_event(e["id"])
    matches = matches_of_event(e["id"])
    return {
        "id": e["id"],
        "name": e["name"],
        "sanctioning_body": e["sanctioning_body"],
        "host_city": e["host_city"],
        "starts_on": e["starts_on"],
        "ends_on": e["ends_on"],
        "posture": e["posture"],
        "active_bid_id": e["active_bid_id"],
        "registered_team_count": sum(1 for t in teams if t["status"] in ENTERED_PLUS),
        "finalized_match_count": sum(1 for m in matches if m["status"] in MATCH_FINALIZED),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_bid(b):
    return {
        "id": b["id"],
        "event_id": b["event_id"],
        "cycle_number": b["cycle_number"],
        "status": b["status"],
        "notes": b["notes"],
        "revision_count": b["revision_count"],
        "submitted_at": b["submitted_at"],
        "decided_at": b["decided_at"],
        "decided_by_user_id": b["decided_by_user_id"],
        "review_score": bid_review_score(b),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_requirement(r):
    return {
        "id": r["id"],
        "bid_id": r["bid_id"],
        "kind": r["kind"],
        "is_mandatory": r["is_mandatory"],
        "weight_points": r["weight_points"],
        "notes": r["notes"],
        "status": r["status"],
        "evidence_uri": r["evidence_uri"],
        "evidence_submitted_by_user_id": r["evidence_submitted_by_user_id"],
        "verified_by_user_id": r["verified_by_user_id"],
        "review_notes": r["review_notes"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_venue(v):
    return {
        "id": v["id"],
        "event_id": v["event_id"],
        "name": v["name"],
        "address": v["address"],
        "rental_fee_cents": v["rental_fee_cents"],
        "revenue_share_pct": v["revenue_share_pct"],
        "contract_uri": v["contract_uri"],
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def ser_field(f):
    return {
        "id": f["id"],
        "venue_id": f["venue_id"],
        "name": f["name"],
        "surface_type": f["surface_type"],
        "has_lights": f["has_lights"],
        "slot_minutes": f["slot_minutes"],
        "status": f["status"],
        "blackout_start": iso(f["blackout_start"]) if f["blackout_start"] else None,
        "blackout_end": iso(f["blackout_end"]) if f["blackout_end"] else None,
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def ser_block(b):
    picked, _pct, est_tier, est_rebate, _pen = rebate_computation(b, PICKUP_FORWARD)
    tier = b.get("_frozen_tier") if b["status"] in ("RECONCILED", "SETTLED") else est_tier
    return {
        "id": b["id"],
        "event_id": b["event_id"],
        "hotel_name": b["hotel_name"],
        "contracted_rooms_per_night": b["contracted_rooms_per_night"],
        "room_rate_cents": b["room_rate_cents"],
        "block_start_date": b["block_start_date"],
        "block_end_date": b["block_end_date"],
        "cutoff_date": b["cutoff_date"],
        "attrition_allowance_pct": b["attrition_allowance_pct"],
        "status": b["status"],
        "picked_up_room_nights": picked,
        "rebate_tier": tier,
        "estimated_rebate_cents": est_rebate,
        "final_rebate_cents": b["final_rebate_cents"],
        "attrition_penalty_cents": b["attrition_penalty_cents"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_booking(bk):
    return {
        "id": bk["id"],
        "hotel_block_id": bk["hotel_block_id"],
        "booker_type": bk["booker_type"],
        "team_id": bk["team_id"],
        "official_id": bk["official_id"],
        "guest_name": bk["guest_name"],
        "rooms_count": bk["rooms_count"],
        "check_in_date": bk["check_in_date"],
        "check_out_date": bk["check_out_date"],
        "rate_cents": bk["rate_cents"],
        "room_nights": bk["room_nights"],
        "total_charge_cents": bk["total_charge_cents"],
        "cancellation_fee_cents": bk["cancellation_fee_cents"],
        "status": bk["status"],
        "created_at": bk["created_at"],
        "updated_at": bk["updated_at"],
        "version": bk["version"],
    }


def ser_division(d):
    return {
        "id": d["id"],
        "event_id": d["event_id"],
        "name": d["name"],
        "team_cap": d["team_cap"],
        "min_teams": d["min_teams"],
        "registration_fee_cents": d["registration_fee_cents"],
        "status": d["status"],
        "entered_team_count": division_entered_count(d),
        "eligible_team_count": division_eligible_count(d),
        "bracket_size": d["bracket_size"],
        "total_rounds": d["total_rounds"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_team(t):
    return {
        "id": t["id"],
        "division_id": t["division_id"],
        "name": t["name"],
        "contact_email": t["contact_email"],
        "strength_rating": t["strength_rating"],
        "roster_player_count": t["roster_player_count"],
        "status": t["status"],
        "seed_number": t["seed_number"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_match(m):
    return {
        "id": m["id"],
        "division_id": m["division_id"],
        "round_number": m["round_number"],
        "bracket_slot": m["bracket_slot"],
        "home_team_id": m["home_team_id"],
        "away_team_id": m["away_team_id"],
        "winner_advances_to_match_id": m["winner_advances_to_match_id"],
        "field_id": m["field_id"],
        "scheduled_start": iso(m["scheduled_start"]) if m["scheduled_start"] else None,
        "scheduled_end": iso(m["scheduled_end"]) if m["scheduled_end"] else None,
        "original_scheduled_start": iso(m["original_scheduled_start"]) if m["original_scheduled_start"] else None,
        "status": m["status"],
        "home_score": m["home_score"],
        "away_score": m["away_score"],
        "winner_team_id": m["winner_team_id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_official(o):
    return {
        "id": o["id"],
        "event_id": o["event_id"],
        "name": o["name"],
        "certification_level": o["certification_level"],
        "needs_housing": o["needs_housing"],
        "game_limit_per_day": o["game_limit_per_day"],
        "status": o["status"],
        "assigned_game_count": official_assigned_game_count(o["id"]),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"],
        "match_id": a["match_id"],
        "official_id": a["official_id"],
        "slot_role": a["slot_role"],
        "status": a["status"],
        "released_reason": a["released_reason"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_volunteer(v):
    return {
        "id": v["id"],
        "event_id": v["event_id"],
        "name": v["name"],
        "email": v["email"],
        "background_check_cleared": v["background_check_cleared"],
        "status": v["status"],
        "hours_worked": volunteer_hours_worked(v["id"]),
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def ser_shift(s):
    confirmed = sum(1 for g in signups_of_shift(s["id"]) if g["status"] in ("CONFIRMED", "WORKED"))
    return {
        "id": s["id"],
        "event_id": s["event_id"],
        "role_needed": s["role_needed"],
        "starts_at": iso(s["starts_at"]),
        "ends_at": iso(s["ends_at"]),
        "capacity": s["capacity"],
        "status": s["status"],
        "confirmed_count": confirmed,
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_signup(g):
    return {
        "id": g["id"],
        "shift_id": g["shift_id"],
        "volunteer_id": g["volunteer_id"],
        "status": g["status"],
        "credited_hours": g["credited_hours"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def ser_alert(a):
    return {
        "id": a["id"],
        "event_id": a["event_id"],
        "venue_id": a["venue_id"],
        "severity": a["severity"],
        "window_start": iso(a["window_start"]),
        "window_end": iso(a["window_end"]),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_report(r):
    return {
        "id": r["id"],
        "event_id": r["event_id"],
        "status": r["status"],
        "projected_attendance": r["projected_attendance"],
        "notes": r["notes"],
        "projected_room_nights": r["projected_room_nights"],
        "projected_direct_spend_cents": r["projected_direct_spend_cents"],
        "actual_attendance": r["actual_attendance"],
        "actual_room_nights": r["actual_room_nights"],
        "audited_direct_spend_cents": r["audited_direct_spend_cents"],
        "created_by_user_id": r["created_by_user_id"],
        "audited_by_user_id": r["audited_by_user_id"],
        "revision_count": r["revision_count"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_settlement(s):
    return {
        "id": s["id"],
        "event_id": s["event_id"],
        "status": s["status"],
        "sponsor_contributions_cents": s["sponsor_contributions_cents"],
        "expense_lines": s["expense_lines"],
        "registration_revenue_cents": s["registration_revenue_cents"],
        "rebate_total_cents": s["rebate_total_cents"],
        "sanction_fee_cents": s["sanction_fee_cents"],
        "venue_rental_total_cents": s["venue_rental_total_cents"],
        "officials_stipend_total_cents": s["officials_stipend_total_cents"],
        "expense_total_cents": s["expense_total_cents"],
        "gross_revenue_cents": s["gross_revenue_cents"],
        "net_to_commission_cents": s["net_to_commission_cents"],
        "certified_by_user_id": s["certified_by_user_id"],
        "approved_by_user_id": s["approved_by_user_id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }
