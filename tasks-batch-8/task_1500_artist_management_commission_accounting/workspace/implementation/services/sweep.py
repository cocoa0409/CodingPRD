"""Logical-clock sweep: applies every time-driven transition (PRD 2.6)."""
from db import db
from services.core import touch, cancel_pending_approvals_for, has_active_dispute
from util import parse_date, parse_datetime


def run_sweep(clock_dt):
    counts = {
        "agreements_expired": 0,
        "agreements_sunset": 0,
        "agreements_closed": 0,
        "options_lapsed": 0,
        "opportunities_expired": 0,
        "statements_acknowledged": 0,
        "team_members_ended": 0,
    }
    clock_date = clock_dt.date()

    # --- Agreements ---
    for ag in list(db["agreements"].values()):
        if ag["status"] == "ACTIVE" and clock_date > parse_date(ag["term_end_date"]):
            ag["status"] = "EXPIRED"
            from services.core import set_sunset_window
            from datetime import timedelta
            set_sunset_window(ag, parse_date(ag["term_end_date"]) + timedelta(days=1))
            artist = db["artists"].get(ag["artist_id"])
            if artist is not None and artist.get("current_agreement_id") == ag["id"]:
                artist["current_agreement_id"] = None
                touch(artist)
            touch(ag)
            counts["agreements_expired"] += 1

    # Postures EXPIRED / TERMINATED / SUPERSEDED -> SUNSET or CLOSED (same sweep)
    for ag in list(db["agreements"].values()):
        if ag["status"] in ("EXPIRED", "TERMINATED", "SUPERSEDED"):
            sunset_end = ag.get("sunset_end_date")
            if sunset_end is not None and clock_date <= parse_date(sunset_end):
                ag["status"] = "SUNSET"
                touch(ag)
                counts["agreements_sunset"] += 1
            else:
                ag["status"] = "CLOSED"
                touch(ag)
                counts["agreements_closed"] += 1

    # SUNSET -> CLOSED once past the window
    for ag in list(db["agreements"].values()):
        if ag["status"] == "SUNSET":
            sunset_end = ag.get("sunset_end_date")
            if sunset_end is not None and clock_date > parse_date(sunset_end):
                ag["status"] = "CLOSED"
                touch(ag)
                counts["agreements_closed"] += 1

    # --- Options: OPEN -> LAPSED when clock now > exercise_window_end ---
    for opt in list(db["options"].values()):
        if opt["status"] == "OPEN" and clock_dt > parse_datetime(opt["exercise_window_end"]):
            opt["status"] = "LAPSED"
            touch(opt)
            counts["options_lapsed"] += 1

    # --- Opportunities: RECEIVED/UNDER_EVALUATION/NEGOTIATING -> EXPIRED past offer expiry ---
    for opp in list(db["opportunities"].values()):
        if opp["status"] in ("RECEIVED", "UNDER_EVALUATION", "NEGOTIATING"):
            if clock_date > parse_date(opp["offer_expiry_date"]):
                opp["status"] = "EXPIRED"
                touch(opp)
                cancel_pending_approvals_for("OPPORTUNITY", opp["id"])
                counts["opportunities_expired"] += 1

    # --- Statements: ISSUED -> ACKNOWLEDGED (deemed acceptance) ---
    for st in list(db["statements"].values()):
        if st["status"] == "ISSUED" and st.get("dispute_window_ends_at"):
            if clock_dt > parse_datetime(st["dispute_window_ends_at"]):
                if not has_active_dispute(st["id"]):
                    st["status"] = "ACKNOWLEDGED"
                    touch(st)
                    counts["statements_acknowledged"] += 1

    # --- TeamMembers: ACTIVE -> ENDED past window_end_date ---
    for tm in list(db["team_members"].values()):
        if tm["status"] == "ACTIVE" and tm.get("window_end_date"):
            if clock_date > parse_date(tm["window_end_date"]):
                tm["status"] = "ENDED"
                touch(tm)
                counts["team_members_ended"] += 1

    return counts
