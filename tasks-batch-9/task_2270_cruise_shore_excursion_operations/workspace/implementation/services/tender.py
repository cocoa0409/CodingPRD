"""Tender wave eligibility and selection policy (PRD 3.4)."""

from db import db


def waves_of_call(port_call_id):
    rows = [w for w in db.tender_waves.values() if w["port_call_id"] == port_call_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def eligible_waves(departure):
    """EXCURSION_PRIORITY waves that land by the meeting time and fit the whole group."""
    pool = []
    for wave in waves_of_call(departure["port_call_id"]):
        if wave["priority_class"] != "EXCURSION_PRIORITY":
            continue
        if wave["window_end_utc"] > departure["meeting_time_utc"]:
            continue
        already = wave["assigned_guest_count"]
        if departure.get("tender_wave_id") == wave["id"]:
            already -= departure["total_capacity"]
        if already + departure["total_capacity"] > wave["guest_capacity"]:
            continue
        pool.append(wave)
    return pool


def select_wave(departure):
    pool = eligible_waves(departure)
    if not pool:
        return None
    pool.sort(key=lambda w: (-w["window_end_utc"].timestamp(), w["wave_index"],
                             w["created_at"], w["_seq"]))
    return pool[0]


def release_wave(departure):
    """Detach the currently assigned wave and give its counters back."""
    wave_id = departure.get("tender_wave_id")
    if not wave_id:
        return None
    wave = db.tender_waves.get(wave_id)
    departure["tender_wave_id"] = None
    if wave is None:
        return None
    wave["assigned_guest_count"] = max(0, wave["assigned_guest_count"] - departure["total_capacity"])
    wave["assigned_departure_count"] = max(0, wave["assigned_departure_count"] - 1)
    db.touch(wave)
    return wave


def attach_wave(departure, wave):
    departure["tender_wave_id"] = wave["id"]
    wave["assigned_guest_count"] = wave["assigned_guest_count"] + departure["total_capacity"]
    wave["assigned_departure_count"] = wave["assigned_departure_count"] + 1
    db.touch(wave)
    return wave
