"""Event lifecycle: open / close / draw / start / complete / cancel."""
from decimal import Decimal

import db
from errors import err
from clock import now, parse_iso, iso
from services import seeding, ranking, prize, sync, posture
from services.validation import check_version


READ_ROLES_ALL = {
    "Organizer", "Referee", "Participant", "DisciplinaryOfficer",
    "DopingOfficer", "AppealsBoard",
}


def _ev_repr(ev: dict) -> dict:
    return db.public(ev)


def open_event(event_id: str, body: dict, actor_id: str, actor_role: str) -> dict:
    ev = db.events.get(event_id)
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")
    if ev["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "event not in DRAFT")
    # capacity precondition (already validated on create, re-check)
    if ev["capacity_min"] < 2 or ev["capacity_max"] < ev["capacity_min"]:
        raise err("ERR_INVALID_STATE", "capacity preconditions violated")
    # registration window
    n = now()
    if not (parse_iso(ev["registration_opens_at"]) <= n < parse_iso(ev["registration_closes_at"])):
        raise err("ERR_INVALID_STATE", "now() outside registration window")
    check_version(ev, body)
    ev["status"] = "OPEN"
    db.stamp_update(ev)
    return ev


def close_registration(event_id: str, body: dict) -> dict:
    ev = db.events.get(event_id)
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")
    if ev["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "event not in OPEN")
    if now() < parse_iso(ev["registration_closes_at"]):
        raise err("ERR_INVALID_STATE", "now() < registration_closes_at")
    check_version(ev, body)
    ev["status"] = "REGISTRATION_CLOSED"
    db.stamp_update(ev)
    return ev


def draw_event(event_id: str, body: dict) -> dict:
    ev = db.events.get(event_id)
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")
    if ev["status"] != "REGISTRATION_CLOSED":
        raise err("ERR_INVALID_STATE", "event not in REGISTRATION_CLOSED")
    check_version(ev, body)
    # registered_count >= capacity_min
    registered = [p for p in db.participants.values()
                  if p["event_id"] == event_id and p["status"] == "REGISTERED"]
    if len(registered) < ev["capacity_min"]:
        raise err("ERR_REGISTRATION_BELOW_MIN", "registered_count below capacity_min")
    if ev.get("posture", "CLEAN") != "CLEAN":
        raise err("ERR_INVALID_STATE", "posture is not CLEAN")
    if len(registered) > 256:
        raise err("ERR_VALIDATION", "too many participants")

    ordered = seeding.assign_seeds(ev, registered)
    pairs = seeding.first_round_pairs(ordered)
    pairs = seeding.avoidance(pairs)

    # Schedule matches. PRD §3.2 forbids the same participant from appearing in
    # two overlapping intervals; nothing prevents *different* participants'
    # round-1 matches from being concurrent. We schedule all round-1 matches
    # to start at event.starts_at in parallel (each 1 hour long); subsequent
    # rounds are likewise stacked round-by-round (all matches in a round are
    # parallel; the next round begins when the previous round's interval ends).
    # This is PRD-faithful and lets referee time-conflict checks fire.
    starts_at = parse_iso(ev["starts_at"])
    from datetime import timedelta

    # For round 1: persist Match rows (all parallel at starts_at)
    cap = seeding.bracket_size(len(ordered))
    round_1_matches = []
    round_1_start = starts_at
    round_1_end = starts_at + timedelta(hours=1)
    for idx, (a, b) in enumerate(pairs, start=1):
        # 'a' is the higher-seed slot (smaller seed number); 'b' is the lower-seed slot or None.
        home = a
        away = b
        match_start = round_1_start
        match_end = round_1_end
        m = {
            "event_id": event_id,
            "round_index": 1,
            "bracket_position": idx,
            "home_participant_id": home["id"] if home else None,
            "away_participant_id": away["id"] if away else None,
            "scheduled_start_at": iso(match_start),
            "scheduled_end_at": iso(match_end),
            "status": "BYE" if away is None else "SCHEDULED",
            "locked_home_score": None,
            "locked_away_score": None,
            "locked_home_sets_won": None,
            "locked_away_sets_won": None,
            "winner_participant_id": home["id"] if (away is None and home is not None) else None,
        }
        db.stamp_create(m, common_fields=True)
        db.matches[m["id"]] = m
        round_1_matches.append(m)

    # Build subsequent rounds. Each round begins after the previous one
    # closes plus a 30-minute gap to satisfy PRD §3.2's adjacency rule for
    # any participant who advances from one round to the next.
    rounds = []
    rounds.append(round_1_matches)
    cur_round_idx = 1
    cur_count = cap // 2
    # Next round starts after the previous round ends; pad 30 minutes to
    # respect PRD's participant adjacency buffer.
    next_start = round_1_end + timedelta(minutes=30)
    while cur_count > 1:
        cur_round_idx += 1
        next_round_count = cur_count // 2
        new_round = []
        round_start = next_start
        round_end = round_start + timedelta(hours=1)
        for pos in range(1, next_round_count + 1):
            ms = round_start
            me = round_end
            m = {
                "event_id": event_id,
                "round_index": cur_round_idx,
                "bracket_position": pos,
                "home_participant_id": None,
                "away_participant_id": None,
                "scheduled_start_at": iso(ms),
                "scheduled_end_at": iso(me),
                "status": "SCHEDULED",
                "locked_home_score": None,
                "locked_away_score": None,
                "locked_home_sets_won": None,
                "locked_away_sets_won": None,
                "winner_participant_id": None,
            }
            db.stamp_create(m, common_fields=True)
            db.matches[m["id"]] = m
            new_round.append(m)
        rounds.append(new_round)
        cur_count = next_round_count
        # Round N+1 begins after round N ends plus a 30-minute gap (PRD §3.2
        # participant adjacency rule for the participants who advance).
        next_start = round_end + timedelta(minutes=30)

    # Wire BYE winners up to round 2 seats
    _propagate_bye_winners(rounds)

    # Participant SEEDED (and bye winners SEEDED -> ACTIVE on next round)
    for p in ordered:
        if p["status"] == "REGISTERED":
            p["status"] = "SEEDED"
            db.stamp_update(p)
    # Bye home participants advance: PRD says the home participant moves SEEDED -> ACTIVE on next round
    # We mark them ACTIVE now (since their next round starts immediately conceptually)
    for m in round_1_matches:
        if m["status"] == "BYE":
            home = db.participants.get(m["home_participant_id"])
            if home and home["status"] == "SEEDED":
                home["status"] = "ACTIVE"
                db.stamp_update(home)

    ev["status"] = "DRAWN"
    db.stamp_update(ev)

    # Initial RankingEntry rows for all participants
    for p in db.participants.values():
        if p["event_id"] == event_id:
            ranking._get_or_create_ranking_entry(event_id, p["id"])

    sync.emit(target_system="GOVERNING_BODY", kind="DRAW_ANNOUNCED",
              payload={"event_id": event_id})
    return ev


def _propagate_bye_winners(rounds):
    """For BYE matches in round k, set the winner into the corresponding seat in round k+1."""
    for r_idx, matches in enumerate(rounds):
        if r_idx + 1 >= len(rounds):
            break
        next_round = rounds[r_idx + 1]
        for m in matches:
            if m["status"] == "BYE":
                next_pos = (m["bracket_position"] + 1) // 2
                # Find the next-round match
                next_match = next((nm for nm in next_round if nm["bracket_position"] == next_pos), None)
                if next_match is None:
                    continue
                # Even bracket_position -> away slot, odd -> home
                if m["bracket_position"] % 2 == 1:
                    if next_match.get("home_participant_id") is None:
                        next_match["home_participant_id"] = m["home_participant_id"]
                        db.stamp_update(next_match)
                else:
                    if next_match.get("away_participant_id") is None:
                        next_match["away_participant_id"] = m["home_participant_id"]
                        db.stamp_update(next_match)


def start_event(event_id: str, body: dict) -> dict:
    ev = db.events.get(event_id)
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")
    if ev["status"] != "DRAWN":
        raise err("ERR_INVALID_STATE", "event not in DRAWN")
    if now() < parse_iso(ev["starts_at"]):
        raise err("ERR_INVALID_STATE", "now() < starts_at")
    # Every round-1 non-BYE match has at least one ASSIGNED HEAD assignment
    r1 = [m for m in db.matches.values()
          if m["event_id"] == event_id and m["round_index"] == 1 and m["status"] != "BYE"]
    for m in r1:
        has_head = any(a for a in db.referee_assignments.values()
                       if a["match_id"] == m["id"] and a["role"] == "HEAD"
                       and a["status"] == "ASSIGNED")
        if not has_head:
            raise err("ERR_INVALID_STATE", "round-1 match missing ASSIGNED HEAD referee")
    check_version(ev, body)
    ev["status"] = "IN_PROGRESS"
    db.stamp_update(ev)
    # Participant SEEDED -> ACTIVE for non-BYE round-1 participants
    r1_participant_ids = set()
    for m in r1:
        if m.get("home_participant_id"):
            r1_participant_ids.add(m["home_participant_id"])
        if m.get("away_participant_id"):
            r1_participant_ids.add(m["away_participant_id"])
    for pid in r1_participant_ids:
        p = db.participants.get(pid)
        if p and p["status"] == "SEEDED":
            p["status"] = "ACTIVE"
            db.stamp_update(p)
    return ev


def complete_event(event_id: str, body: dict) -> dict:
    ev = db.events.get(event_id)
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")
    if ev["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "event not in IN_PROGRESS")
    # posture gate
    if ev.get("posture") == "FROZEN":
        raise err("ERR_EVENT_FROZEN", "event posture is FROZEN")
    # All non-BYE matches LOCKED
    for m in db.matches.values():
        if m["event_id"] != event_id:
            continue
        if m["status"] == "BYE":
            continue
        if m["status"] != "LOCKED":
            raise err("ERR_INVALID_STATE", "non-BYE match not LOCKED")
    # No OPEN dispute
    for d in db.disputes.values():
        m = db.matches.get(d["match_id"])
        if m and m["event_id"] == event_id and d["status"] == "OPEN":
            raise err("ERR_INVALID_STATE", "OPEN dispute exists")
    check_version(ev, body)
    ev["status"] = "COMPLETED"
    db.stamp_update(ev)
    # Final ranking
    ranking.recompute_rankings(event_id, finalize=True)
    # Prize calculation
    prize.compute_initial_prize_payments(ev)
    return ev


def cancel_event(event_id: str, body: dict) -> dict:
    ev = db.events.get(event_id)
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")
    if ev["status"] not in ("DRAFT", "OPEN", "REGISTRATION_CLOSED"):
        raise err("ERR_INVALID_STATE", "event not cancellable from current state")
    check_version(ev, body)
    cur = ev["status"]
    ev["status"] = "CANCELLED"
    db.stamp_update(ev)
    if cur in ("OPEN", "REGISTRATION_CLOSED"):
        # Cascade: every participant in REGISTERED/SEEDED/ACTIVE -> WITHDRAWN
        for p in list(db.participants.values()):
            if p["event_id"] != event_id:
                continue
            if p["status"] in ("REGISTERED", "SEEDED", "ACTIVE"):
                p["status"] = "WITHDRAWN"
                db.stamp_update(p)
                # Refund outbox event
                sync.emit(target_system="PAYMENT", kind="ENTRY_FEE_CHARGED",
                          payload={"participant_id": p["id"],
                                   "refund_cents": -p.get("entry_fee_paid_cents", 0)})
                # Decrement is irrelevant since event cancelled, but we still keep counter consistent
        # PrizePayment SCHEDULED -> CANCELLED
        for pp in db.prize_payments.values():
            if pp["event_id"] != event_id:
                continue
            if pp["status"] == "SCHEDULED":
                pp["status"] = "CANCELLED"
                db.stamp_update(pp)
    # registered_count consistent
    _recompute_registered_count(event_id)
    return ev


def _recompute_registered_count(event_id: str) -> None:
    cnt = 0
    for p in db.participants.values():
        if p["event_id"] == event_id and p["status"] in ("REGISTERED", "SEEDED", "ACTIVE"):
            cnt += 1
    ev = db.events.get(event_id)
    if ev and ev.get("registered_count") != cnt:
        ev["registered_count"] = cnt
        db.stamp_update(ev)
