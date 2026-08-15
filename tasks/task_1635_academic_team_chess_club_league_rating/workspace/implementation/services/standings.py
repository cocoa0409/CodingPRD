"""team_standings calculation (PRD 3.9): board points, match points,
Sonneborn-Berger, forfeit losses, pinned ranking cascade."""
from db import store


def compute_stats(season_id):
    """Per-club aggregates over COMPLETED meets of the season.
    Returns {club_id: {match_points, game_points, forfeit_losses,
    sonneborn_berger, h2h: {opp_club_id: match_points_earned}}}."""
    stats = {}
    for c in store.clubs.values():
        if c["season_id"] == season_id:
            stats[c["id"]] = {"match_points": 0.0, "game_points": 0.0,
                              "forfeit_losses": 0, "sonneborn_berger": 0.0,
                              "h2h": {}}
    meets = [m for m in store.meets.values()
             if m["season_id"] == season_id and m["status"] == "COMPLETED"]
    results = []  # (host_id, away_id, host_match_result) for the SB pass
    for m in meets:
        host, away = m["host_club_id"], m["away_club_id"]
        if host not in stats or away not in stats:
            continue
        gp_h = gp_a = 0.0
        for p in store.pairings.values():
            if p["meet_id"] != m["id"] or p["status"] != "CONFIRMED":
                continue
            r = p["result"]
            if r == "WHITE_WIN":
                gp_h += 1
            elif r == "BLACK_WIN":
                gp_a += 1
            elif r == "DRAW":
                gp_h += 0.5
                gp_a += 0.5
            elif r == "WHITE_FORFEIT_WIN":
                gp_h += 1
                stats[away]["forfeit_losses"] += 1
            elif r == "BLACK_FORFEIT_WIN":
                gp_a += 1
                stats[host]["forfeit_losses"] += 1
            elif r == "DOUBLE_FORFEIT":
                stats[host]["forfeit_losses"] += 1
                stats[away]["forfeit_losses"] += 1
        stats[host]["game_points"] += gp_h
        stats[away]["game_points"] += gp_a
        if gp_h > gp_a:
            mp_h, mp_a, res_h = 2.0, 0.0, 1.0
        elif gp_h == gp_a:
            mp_h, mp_a, res_h = 1.0, 1.0, 0.5
        else:
            mp_h, mp_a, res_h = 0.0, 2.0, 0.0
        stats[host]["match_points"] += mp_h
        stats[away]["match_points"] += mp_a
        stats[host]["h2h"][away] = stats[host]["h2h"].get(away, 0.0) + mp_h
        stats[away]["h2h"][host] = stats[away]["h2h"].get(host, 0.0) + mp_a
        results.append((host, away, res_h))
    # Sonneborn-Berger: opponent's FINAL season match_points * our match result.
    for host, away, res_h in results:
        stats[host]["sonneborn_berger"] += stats[away]["match_points"] * res_h
        stats[away]["sonneborn_berger"] += stats[host]["match_points"] * (1.0 - res_h)
    return stats


def rank_clubs(club_ids, stats):
    """Pinned cascade: match_points DESC; head-to-head match points DESC only
    when exactly two clubs are tied on match points (skipped for larger groups);
    sonneborn_berger DESC; game_points DESC; forfeit_losses ASC; created_at ASC.
    Returns club ids in rank order (best first)."""
    clubs = [store.clubs[cid] for cid in club_ids]
    order = sorted(clubs, key=lambda c: (c["created_at"], c.get("_seq", 0)))
    order.sort(key=lambda c: stats[c["id"]]["forfeit_losses"])
    order.sort(key=lambda c: -stats[c["id"]]["game_points"])
    order.sort(key=lambda c: -stats[c["id"]]["sonneborn_berger"])
    order.sort(key=lambda c: -stats[c["id"]]["match_points"])
    ids = [c["id"] for c in order]
    i = 0
    while i < len(ids):
        j = i
        mp = stats[ids[i]]["match_points"]
        while j + 1 < len(ids) and stats[ids[j + 1]]["match_points"] == mp:
            j += 1
        if j - i == 1:  # exactly two clubs tied on match points
            a, b = ids[i], ids[j]
            h2h_a = stats[a]["h2h"].get(b, 0.0)
            h2h_b = stats[b]["h2h"].get(a, 0.0)
            if h2h_b > h2h_a:
                ids[i], ids[j] = b, a
        i = j + 1
    return ids


def live_standings(season_id):
    """Ranked rows for every club of the season."""
    club_ids = [c["id"] for c in store.clubs.values() if c["season_id"] == season_id]
    stats = compute_stats(season_id)
    ranked = rank_clubs(club_ids, stats)
    rows = []
    for idx, cid in enumerate(ranked):
        s = stats[cid]
        rows.append({
            "season_id": season_id, "club_id": cid,
            "match_points": s["match_points"], "game_points": s["game_points"],
            "sonneborn_berger": s["sonneborn_berger"],
            "forfeit_losses": s["forfeit_losses"], "rank": idx + 1,
        })
    return rows
