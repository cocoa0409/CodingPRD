def ser_season(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "salary_cap_cents": s["salary_cap_cents"],
        "roster_min": s["roster_min"],
        "roster_max": s["roster_max"],
        "two_way_max": s["two_way_max"],
        "penalty_threshold": s["penalty_threshold"],
        "trade_window_state": s["trade_window_state"],
        "phase": s["phase"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_team(t):
    return {
        "id": t["id"],
        "season_id": t["season_id"],
        "name": t["name"],
        "market_size_weight": t["market_size_weight"],
        "payroll_active_cents": t["payroll_active_cents"],
        "penalty_points": t["penalty_points"],
        "posture": t["posture"],
        "seed": t["seed"],
        "eliminated": t["eliminated"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_player(p):
    return {
        "id": p["id"],
        "season_id": p["season_id"],
        "handle": p["handle"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_contract(c):
    return {
        "id": c["id"],
        "team_id": c["team_id"],
        "player_id": c["player_id"],
        "base_salary_cents": c["base_salary_cents"],
        "contract_type": c["contract_type"],
        "term_start": c["term_start"],
        "term_end": c["term_end"],
        "two_way_promoted": c["two_way_promoted"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_stint(s):
    return {
        "id": s["id"],
        "contract_id": s["contract_id"],
        "player_id": s["player_id"],
        "starts_at": s["starts_at"],
        "ends_at": s["ends_at"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_trade(t):
    return {
        "id": t["id"],
        "season_id": t["season_id"],
        "from_team_id": t["from_team_id"],
        "to_team_id": t["to_team_id"],
        "contract_ids_out": list(t["contract_ids_out"]),
        "contract_ids_in": list(t["contract_ids_in"]),
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_fine(f):
    return {
        "id": f["id"],
        "team_id": f["team_id"],
        "player_id": f["player_id"],
        "amount_cents": f["amount_cents"],
        "penalty_points": f["penalty_points"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def ser_sponsorship(s):
    return {
        "id": s["id"],
        "season_id": s["season_id"],
        "sponsor_name": s["sponsor_name"],
        "pool_cents": s["pool_cents"],
        "league_share_pct": s["league_share_pct"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_revenue_share(r):
    # immutable audit record: only id + created_at, plus its data fields
    return {
        "id": r["id"],
        "sponsorship_id": r["sponsorship_id"],
        "team_id": r["team_id"],
        "amount_cents": r["amount_cents"],
        "weight_used": r["weight_used"],
        "created_at": r["created_at"],
    }
