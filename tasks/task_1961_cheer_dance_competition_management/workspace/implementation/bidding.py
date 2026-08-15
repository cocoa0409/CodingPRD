"""Bid allocation waterfall (PRD §3.7): INITIAL, REOFFER, REEVALUATE.

Pool conservation invariant: count(Bid.status IN {OFFERED, ACCEPTED})
+ division.bid_pool_available == paid_bid_count + at_large_bid_count.
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from calc import AT_LARGE_PCT, BID_ACCEPTANCE_HOURS
from store import db, now, set_fields, stamp, touch


def _division_event(division):
    return db.events.get(division["event_id"])


def _official_perfs(division_id):
    ranked = [p for p in db.performances.values()
              if p["division_id"] == division_id and p["status"] == "OFFICIAL"]
    ranked.sort(key=lambda p: (p["rank_in_division"] is None,
                               p["rank_in_division"] or 0))
    return ranked


def _team_has_accepted_bid_in_event(team_id, event_id):
    for b in db.bids.values():
        if b["team_id"] != team_id or b["status"] != "ACCEPTED":
            continue
        div = db.divisions.get(b["division_id"])
        if div and div["event_id"] == event_id:
            return True
    return False


def _eligible_candidates(division, exclude_team_id=None):
    """OFFICIAL performances' teams, rank ASC, passing the eligibility filter."""
    out = []
    for perf in _official_perfs(division["id"]):
        team = db.teams.get(perf["team_id"])
        if team is None:
            continue
        if exclude_team_id is not None and team["id"] == exclude_team_id:
            continue
        if team["reg_status"] in ("WITHDRAWN", "DISQUALIFIED"):
            continue
        if _team_has_accepted_bid_in_event(team["id"], division["event_id"]):
            continue
        out.append((perf, team))
    return out


def _at_large_threshold(division):
    ranked = _official_perfs(division["id"])
    if not ranked:
        return None
    winner_score = ranked[0]["official_score"]
    if winner_score is None:
        return None
    return (AT_LARGE_PCT * winner_score).quantize(Decimal("0.01"),
                                                  rounding=ROUND_HALF_UP)


def _team_offered_bid(division_id, team_id, kind=None):
    for b in db.bids.values():
        if (b["division_id"] == division_id and b["team_id"] == team_id
                and b["status"] == "OFFERED"
                and (kind is None or b["kind"] == kind)):
            return b
    return None


def _create_bid(division, team, perf, kind, offered_ids=None):
    pool_before = division["bid_pool_available"]
    if pool_before <= 0:
        return None
    division["bid_pool_available"] = pool_before - 1
    touch(division)
    bid = stamp({
        "division_id": division["id"],
        "team_id": team["id"],
        "kind": kind,
        "status": "OFFERED",
        "rank_at_offer": perf["rank_in_division"],
        "offered_at": now(),
        "acceptance_deadline": now() + timedelta(hours=BID_ACCEPTANCE_HOURS),
    })
    db.bids[bid["id"]] = bid
    if offered_ids is not None:
        offered_ids.append(bid["id"])
    return bid


def revoke_bid(bid):
    """Bid OFFERED/ACCEPTED -> REVOKED; slot returns to the division pool."""
    division = db.divisions.get(bid["division_id"])
    set_fields(bid, status="REVOKED")
    if division is not None:
        division["bid_pool_available"] += 1
        touch(division)
    return division


def initial_allocation(division, offered_ids=None):
    """PAID slots to top-paid_bid_count eligible teams by rank, then AT_LARGE
    to next eligible teams meeting the 90% threshold. Pool-capped."""
    if division["bid_pool_available"] <= 0:
        return
    candidates = _eligible_candidates(division)
    if not candidates:
        return
    threshold = _at_large_threshold(division)
    # PAID offers first
    paid_offered = 0
    for perf, team in candidates:
        if paid_offered >= division["paid_bid_count"]:
            break
        if division["bid_pool_available"] <= 0:
            return
        if _create_bid(division, team, perf, "PAID", offered_ids) is not None:
            paid_offered += 1
    # AT_LARGE offers next
    at_large_offered = 0
    for perf, team in candidates[paid_offered:]:
        if at_large_offered >= division["at_large_bid_count"]:
            break
        if division["bid_pool_available"] <= 0:
            return
        if threshold is not None and perf["official_score"] is not None \
                and perf["official_score"] >= threshold:
            if _create_bid(division, team, perf, "AT_LARGE", offered_ids) is not None:
                at_large_offered += 1


def reoffer_slot(division, kind, freed_team_id):
    """A freed slot is re-offered immediately; the freeing team is excluded."""
    if division["bid_pool_available"] <= 0:
        return
    candidates = _eligible_candidates(division, exclude_team_id=freed_team_id)
    if kind == "PAID":
        for perf, team in candidates:
            if _team_offered_bid(division["id"], team["id"], "PAID"):
                continue
            at_large = _team_offered_bid(division["id"], team["id"], "AT_LARGE")
            bid = _create_bid(division, team, perf, "PAID")
            if bid is None:
                return
            if at_large is not None:
                # Upgrade: the OFFERED AT_LARGE bid is revoked and that slot
                # is itself re-offered (excluding the upgraded team).
                set_fields(at_large, status="REVOKED")
                division["bid_pool_available"] += 1
                touch(division)
                reoffer_slot(division, "AT_LARGE", freed_team_id=team["id"])
            return
        return
    # AT_LARGE reoffer: threshold applies; PAID holders skipped (downgrade).
    threshold = _at_large_threshold(division)
    for perf, team in candidates:
        if _team_offered_bid(division["id"], team["id"], "PAID"):
            continue
        if _team_offered_bid(division["id"], team["id"], "AT_LARGE"):
            continue
        if threshold is not None and perf["official_score"] is not None \
                and perf["official_score"] >= threshold:
            _create_bid(division, team, perf, "AT_LARGE")
            return


def reevaluate(division, offered_ids=None):
    """Post-appeal rank change: revoke every OFFERED bid, then INITIAL.

    ACCEPTED bids are never revoked by re-evaluation.
    """
    from calc import recompute_ranking
    recompute_ranking(division["id"])
    for bid in sorted([b for b in db.bids.values()
                       if b["division_id"] == division["id"]
                       and b["status"] == "OFFERED"],
                      key=lambda b: (b["created_at"], b["_seq"])):
        revoke_bid(bid)
    initial_allocation(division, offered_ids)


def division_complete(division):
    """Every non-CANCELLED performance of the division is OFFICIAL|EXCLUDED."""
    perfs = [p for p in db.performances.values()
             if p["division_id"] == division["id"] and p["status"] != "CANCELLED"]
    if not perfs:
        return False
    return all(p["status"] in ("OFFICIAL", "EXCLUDED") for p in perfs)


def revoke_team_bids(team):
    """Withdrawal/disqualification cascade: revoke OFFERED+ACCEPTED bids of
    the team, credit the pool, and run the re-offer cascade per freed slot."""
    bids = sorted([b for b in db.bids.values()
                   if b["team_id"] == team["id"]
                   and b["status"] in ("OFFERED", "ACCEPTED")],
                  key=lambda b: (b["created_at"], b["_seq"]))
    for bid in bids:
        division = revoke_bid(bid)
        if division is not None:
            reoffer_slot(division, bid["kind"], freed_team_id=team["id"])
