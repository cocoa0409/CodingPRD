"""Entity serializers — computed fields are derived fresh on every read."""
from db import store
from response import num_out
from services.common import (club_balance, projected_stipend,
                             section_current_entries, performance_points)


def base_fields(o):
    return {"id": o["id"], "created_at": o["created_at"],
            "updated_at": o["updated_at"], "version": o["version"]}


def season_json(s):
    d = base_fields(s)
    d.update({
        "name": s["name"], "start_date": s["start_date"], "end_date": s["end_date"],
        "dues_deadline": s["dues_deadline"],
        "regular_due_cents": s["regular_due_cents"],
        "late_due_cents": s["late_due_cents"],
        "provisional_game_threshold": s["provisional_game_threshold"],
        "base_rating": s["base_rating"],
        "state_bid_slots_per_region": s["state_bid_slots_per_region"],
        "travel_base_cents": s["travel_base_cents"],
        "status": s["status"],
    })
    return d


def club_json(c):
    d = base_fields(c)
    d.update({
        "season_id": c["season_id"], "name": c["name"],
        "school_name": c["school_name"], "region_code": c["region_code"],
        "travel_tier": c["travel_tier"],
        "account_balance_cents": club_balance(c["id"]),
        "projected_travel_stipend_cents": projected_stipend(c),
        "status": c["status"],
    })
    return d


def coach_json(c):
    d = base_fields(c)
    d.update({
        "club_id": c["club_id"], "full_name": c["full_name"], "email": c["email"],
        "certification_level": c["certification_level"], "status": c["status"],
    })
    return d


def player_json(p):
    d = base_fields(p)
    d.update({
        "club_id": p["club_id"], "full_name": p["full_name"],
        "grade_level": p["grade_level"],
        "initial_rating": p["initial_rating"],
        "initial_rated_games": p["initial_rated_games"],
        "rating": p["rating"], "peak_rating": p["peak_rating"],
        "rated_games_played": p["rated_games_played"],
        "is_provisional": p["is_provisional"],
        "performance_points": performance_points(p),
        "status": p["status"],
    })
    return d


def membership_json(m):
    d = base_fields(m)
    d.update({
        "player_id": m["player_id"], "season_id": m["season_id"],
        "fee_cents": m["fee_cents"], "paid_at": m["paid_at"], "status": m["status"],
    })
    return d


def ledger_json(le):
    return {
        "id": le["id"], "created_at": le["created_at"],
        "club_id": le["club_id"], "entry_type": le["entry_type"],
        "amount_cents": le["amount_cents"], "memo": le.get("memo"),
        "posted_by_user_id": le["posted_by_user_id"],
        "membership_id": le.get("membership_id"),
        "entry_id": le.get("entry_id"),
        "reversal_of_id": le.get("reversal_of_id"),
        "reversed_by_id": le.get("reversed_by_id"),
    }


def meet_json(m):
    d = base_fields(m)
    d.update({
        "season_id": m["season_id"], "host_club_id": m["host_club_id"],
        "away_club_id": m["away_club_id"], "scheduled_date": m["scheduled_date"],
        "rounds_count": m["rounds_count"], "boards_count": m["boards_count"],
        "status": m["status"],
    })
    return d


def pairing_json(p):
    d = base_fields(p)
    d.update({
        "meet_id": p["meet_id"], "round_number": p["round_number"],
        "board_number": p["board_number"],
        "white_player_id": p["white_player_id"],
        "black_player_id": p["black_player_id"],
        "result": p["result"],
        "reported_by_coach_id": p.get("reported_by_coach_id"),
        "was_confirmed": p["was_confirmed"],
        "confirmed_at": p.get("confirmed_at"),
        "status": p["status"],
    })
    return d


def dispute_json(x):
    d = base_fields(x)
    d.update({
        "pairing_id": x["pairing_id"], "raised_by_coach_id": x["raised_by_coach_id"],
        "reason": x["reason"], "resolved_result": x.get("resolved_result"),
        "resolution_notes": x.get("resolution_notes"), "status": x["status"],
    })
    return d


def tournament_json(t):
    d = base_fields(t)
    d.update({
        "season_id": t["season_id"], "host_club_id": t.get("host_club_id"),
        "name": t["name"], "start_date": t["start_date"], "end_date": t["end_date"],
        "entry_fee_cents": t["entry_fee_cents"],
        "early_bird_deadline": t.get("early_bird_deadline"),
        "early_bird_discount_pct": t.get("early_bird_discount_pct"),
        "capacity": t["capacity"], "status": t["status"],
    })
    return d


def section_json(s):
    d = base_fields(s)
    d.update({
        "tournament_id": s["tournament_id"], "name": s["name"],
        "min_rating": s["min_rating"], "max_rating": s["max_rating"],
        "allow_provisional": s["allow_provisional"],
        "max_entries": s["max_entries"],
        "current_entries": section_current_entries(s["id"]),
        "status": s["status"],
    })
    return d


def entry_json(e):
    d = base_fields(e)
    d.update({
        "section_id": e["section_id"], "player_id": e["player_id"],
        "fee_cents": e["fee_cents"], "refund_cents": e["refund_cents"],
        "status": e["status"],
    })
    return d


def assignment_json(a):
    d = base_fields(a)
    d.update({
        "coach_id": a["coach_id"], "event_type": a["event_type"],
        "meet_id": a.get("meet_id"), "tournament_id": a.get("tournament_id"),
        "status": a["status"],
    })
    return d


def bid_json(b):
    d = base_fields(b)
    d.update({
        "season_id": b["season_id"], "club_id": b["club_id"],
        "player_id": b.get("player_id"), "bid_type": b["bid_type"],
        "offer_deadline": b["offer_deadline"], "status": b["status"],
    })
    return d


def rating_event_json(e):
    return {
        "id": e["id"], "created_at": e["created_at"],
        "player_id": e["player_id"], "pairing_id": e["pairing_id"],
        "season_id": e["season_id"], "formula_variant": e["formula_variant"],
        "opponent_rating_snapshot": e["opponent_rating_snapshot"],
        "score": num_out(e["score"]), "k_factor": e["k_factor"],
        "rating_before": e["rating_before"], "rating_after": e["rating_after"],
        "confirmed_at": e["confirmed_at"], "status": e["status"],
    }


def snapshot_json(s):
    d = base_fields(s)
    d.update({
        "season_id": s["season_id"], "club_id": s["club_id"],
        "match_points": num_out(s["match_points"]),
        "game_points": num_out(s["game_points"]),
        "sonneborn_berger": num_out(s["sonneborn_berger"]),
        "forfeit_losses": s["forfeit_losses"],
        "rank": s["rank"], "is_final": s["is_final"],
    })
    return d


def stipend_json(s):
    d = base_fields(s)
    d.update({
        "season_id": s["season_id"], "club_id": s["club_id"],
        "meets_counted": s["meets_counted"], "amount_cents": s["amount_cents"],
        "ledger_entry_id": s.get("ledger_entry_id"),
    })
    return d


def standing_row_json(row):
    return {
        "season_id": row["season_id"], "club_id": row["club_id"],
        "match_points": num_out(row["match_points"]),
        "game_points": num_out(row["game_points"]),
        "sonneborn_berger": num_out(row["sonneborn_berger"]),
        "forfeit_losses": row["forfeit_losses"],
        "rank": row["rank"],
    }
