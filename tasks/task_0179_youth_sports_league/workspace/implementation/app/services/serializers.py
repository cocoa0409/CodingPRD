"""Resource serializers — produce the wire shape for each entity dict.

We mirror the in-memory dicts directly but ensure derived/computed fields
appear with their published names and types and that decimal values are
rendered as floats with two-decimal precision where appropriate.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def _dec_to_float(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    return v


def serialize_season(s: dict) -> dict:
    return {
        "id": s["id"],
        "name": s["name"],
        "age_division": s["age_division"],
        "min_birth_date": s["min_birth_date"],
        "max_birth_date": s["max_birth_date"],
        "regular_season_start": s["regular_season_start"],
        "regular_season_end": s["regular_season_end"],
        "playoff_cutoff_date": s["playoff_cutoff_date"],
        "status": s["status"],
        "rainout_window_days": s["rainout_window_days"],
        "volunteer_hours_required_per_family": _dec_to_float(
            s["volunteer_hours_required_per_family"]
        ),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_player(p: dict) -> dict:
    return {
        "id": p["id"],
        "season_id": p["season_id"],
        "first_name": p["first_name"],
        "last_name": p["last_name"],
        "birth_date": p["birth_date"],
        "guardian_id": p["guardian_id"],
        "birth_certificate_uri": p.get("birth_certificate_uri"),
        "evaluation_score": _dec_to_float(p.get("evaluation_score")),
        "evaluation_tier": p.get("evaluation_tier"),
        "status": p["status"],
        "team_id": p.get("team_id"),
        "draft_pick_overall": p.get("draft_pick_overall"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_guardian(g: dict) -> dict:
    return {
        "id": g["id"],
        "full_name": g["full_name"],
        "email": g["email"],
        "phone": g["phone"],
        "volunteer_hours_logged": _dec_to_float(g.get("volunteer_hours_logged", 0)),
        "volunteer_status": g.get("volunteer_status", "DEFICIENT"),
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def serialize_team(t: dict) -> dict:
    return {
        "id": t["id"],
        "season_id": t["season_id"],
        "name": t["name"],
        "head_coach_id": t["head_coach_id"],
        "draft_position": t["draft_position"],
        "roster_count": t.get("roster_count", 0),
        "tier_a_count": t.get("tier_a_count", 0),
        "wins": t.get("wins", 0),
        "losses": t.get("losses", 0),
        "playoff_seed": t.get("playoff_seed"),
        "playoff_status": t.get("playoff_status", "NOT_QUALIFIED"),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_coach(c: dict) -> dict:
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "background_check_passed": c.get("background_check_passed", False),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_referee(r: dict) -> dict:
    return {
        "id": r["id"],
        "full_name": r["full_name"],
        "email": r["email"],
        "certification_level": r["certification_level"],
        "weekly_assignment_cap": r["weekly_assignment_cap"],
        "active": r.get("active", True),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_game(g: dict) -> dict:
    return {
        "id": g["id"],
        "season_id": g["season_id"],
        "home_team_id": g["home_team_id"],
        "away_team_id": g["away_team_id"],
        "game_type": g["game_type"],
        "field_id": g["field_id"],
        "scheduled_start": g["scheduled_start"],
        "scheduled_end": g["scheduled_end"],
        "original_scheduled_start": g["original_scheduled_start"],
        "referee_id": g.get("referee_id"),
        "status": g["status"],
        "home_score": g.get("home_score"),
        "away_score": g.get("away_score"),
        "bracket_round": g.get("bracket_round"),
        "forfeiting_team_id": g.get("forfeiting_team_id"),
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def serialize_shift(s: dict) -> dict:
    return {
        "id": s["id"],
        "season_id": s["season_id"],
        "guardian_id": s["guardian_id"],
        "game_id": s.get("game_id"),
        "role": s["role"],
        "scheduled_start": s["scheduled_start"],
        "scheduled_end": s["scheduled_end"],
        "hours_credited": _dec_to_float(s.get("hours_credited", 0)),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_audit(a: dict) -> dict:
    return {
        "id": a["id"],
        "entity_type": a["entity_type"],
        "entity_id": a["entity_id"],
        "actor_role": a.get("actor_role"),
        "actor_id": a.get("actor_id"),
        "action": a["action"],
        "details": a.get("details", {}),
        "created_at": a["created_at"],
    }
