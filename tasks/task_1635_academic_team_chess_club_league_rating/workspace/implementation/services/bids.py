"""Qualification bid generation, promotion, and the clock expiry sweep."""
from datetime import timedelta

from db import store, new_id, next_seq, now_iso, clock_now, iso
from services.common import performance_points, membership_for
from services.standings import compute_stats, rank_clubs

MIN_BID_POINTS = 6
BID_OFFER_DAYS = 7


def _offer_deadline():
    return iso(clock_now() + timedelta(days=BID_OFFER_DAYS))


def create_bid(season_id, club_id, player_id, bid_type):
    b = {
        "id": new_id(), "_seq": next_seq(),
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
        "season_id": season_id, "club_id": club_id, "player_id": player_id,
        "bid_type": bid_type, "offer_deadline": _offer_deadline(),
        "status": "OFFERED",
    }
    store.bids[b["id"]] = b
    return b


def _eligible_individual(player, season):
    if player["status"] != "ACTIVE":
        return False
    club = store.clubs[player["club_id"]]
    if club["status"] == "SUSPENDED":
        return False
    m = membership_for(player["id"], season["id"])
    if m is None or m["status"] not in ("PAID", "WAIVED"):
        return False
    if performance_points(player) < MIN_BID_POINTS:
        return False
    for b in store.bids.values():
        if (b.get("player_id") == player["id"] and b["season_id"] == season["id"]
                and b["status"] in ("OFFERED", "ACCEPTED")):
            return False
    return True


def _rank_players(players):
    return sorted(players,
                  key=lambda p: (-performance_points(p), -p["rating"],
                                 -p["rated_games_played"], p["created_at"],
                                 p.get("_seq", 0)))


def generate_bids(season):
    """Bulk generation (season must be FINALIZING — enforced by the route)."""
    season_id = season["id"]
    season_clubs = [c for c in store.clubs.values() if c["season_id"] == season_id]
    regions = sorted({c["region_code"] for c in season_clubs})
    stats = compute_stats(season_id)
    created = []
    for region in regions:
        pool = [p for p in store.players.values()
                if store.clubs[p["club_id"]]["season_id"] == season_id
                and store.clubs[p["club_id"]]["region_code"] == region
                and _eligible_individual(p, season)]
        pool = _rank_players(pool)
        for p in pool[:season["state_bid_slots_per_region"]]:
            created.append(create_bid(season_id, p["club_id"], p["id"],
                                      "INDIVIDUAL_STATE"))
        region_club_ids = [c["id"] for c in season_clubs if c["region_code"] == region]
        if region_club_ids:
            top_club_id = rank_clubs(region_club_ids, stats)[0]
            created.append(create_bid(season_id, top_club_id, None, "TEAM_STATE"))
    return created


def promote_next_individual(declined_bid):
    """After an INDIVIDUAL_STATE bid is DECLINED or EXPIRED: offer to the
    single highest-ranked eligible player in the same region having no
    INDIVIDUAL_STATE bid for the season in ANY status. Empty pool -> nothing."""
    season = store.seasons[declined_bid["season_id"]]
    region = store.clubs[declined_bid["club_id"]]["region_code"]
    candidates = []
    for p in store.players.values():
        club = store.clubs[p["club_id"]]
        if club["season_id"] != season["id"] or club["region_code"] != region:
            continue
        if not _eligible_individual(p, season):
            continue
        has_any = any(b.get("player_id") == p["id"]
                      and b["season_id"] == season["id"]
                      and b["bid_type"] == "INDIVIDUAL_STATE"
                      for b in store.bids.values())
        if has_any:
            continue
        candidates.append(p)
    if not candidates:
        return None
    winner = _rank_players(candidates)[0]
    return create_bid(season["id"], winner["club_id"], winner["id"],
                      "INDIVIDUAL_STATE")


def sweep_expired_bids():
    """Every OFFERED bid whose offer_deadline is strictly earlier than the new
    clock becomes EXPIRED (equal survives); individual expiries promote."""
    now = clock_now()
    expired = []
    for b in sorted(store.bids.values(), key=lambda b: b.get("_seq", 0)):
        if b["status"] != "OFFERED":
            continue
        from db import parse_dt
        if parse_dt(b["offer_deadline"]) < now:
            b["status"] = "EXPIRED"
            b["updated_at"] = now_iso()
            b["version"] += 1
            expired.append(b)
    for b in expired:
        if b["bid_type"] == "INDIVIDUAL_STATE":
            promote_next_individual(b)
