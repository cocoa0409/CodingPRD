"""Roster slot helpers."""
from __future__ import annotations

from db import store
from services.common import new_common_fields


def create_roster_slot(*, team_id: str, player_id: str, slot_type: str = "BENCH") -> dict:
    s = store()
    common = new_common_fields(s.next_seq())
    slot = {
        **common,
        "team_id": team_id,
        "player_id": player_id,
        "slot_type": slot_type,
        "week_locked": 0,
    }
    s.roster_slots[slot["id"]] = slot
    return slot


def delete_roster_slots_for(team_id: str, player_id: str):
    s = store()
    for sid in list(s.roster_slots.keys()):
        slot = s.roster_slots[sid]
        if slot["team_id"] == team_id and slot["player_id"] == player_id:
            del s.roster_slots[sid]


def get_roster_slots_for_team(team_id: str):
    s = store()
    return [slot for slot in s.roster_slots.values() if slot["team_id"] == team_id]


def get_non_ir_count(team_id: str) -> int:
    return sum(
        1 for slot in get_roster_slots_for_team(team_id)
        if slot["slot_type"] != "IR"
    )


def get_ir_count(team_id: str) -> int:
    return sum(
        1 for slot in get_roster_slots_for_team(team_id)
        if slot["slot_type"] == "IR"
    )


def find_player_slot(team_id: str, player_id: str) -> dict | None:
    for slot in get_roster_slots_for_team(team_id):
        if slot["player_id"] == player_id:
            return slot
    return None
