"""Calculation reliance_metrics (PRD 3.9)."""

import constants as C
from db import db
from services.numbers import D, pct1, round_half_up


def governing_study(school_id):
    """Latest CERTIFIED study: school_year DESC, then created_at DESC."""
    candidates = [
        s for s in db.studies.values()
        if s["school_id"] == school_id and s["status"] == "CERTIFIED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda s: s["_seq"])
    candidates.sort(key=lambda s: (s["school_year"], s["created_at"]), reverse=True)
    return candidates[0]


def school_metrics(school):
    study = governing_study(school["id"])
    permanent_seats = study["program_capacity_seats"] if study else 0
    hosted = school["hosted_portable_seats"]
    denominator = permanent_seats + hosted
    if denominator <= 0:
        share = D("0.0")
    else:
        share = round_half_up(D(hosted) * 100 / D(denominator), 1)

    if (
        share >= C.LONG_TERM_SHARE_PCT
        or school["consecutive_reliance_years"] >= C.LONG_TERM_RELIANCE_YEARS
    ):
        flag = "LONG_TERM_RELIANCE"
    elif share >= C.MONITOR_SHARE_PCT:
        flag = "MONITOR"
    else:
        flag = "NONE"

    return {
        "certified_study_id": study["id"] if study else None,
        "permanent_seats": permanent_seats,
        "hosted_portable_seats": hosted,
        "portable_seat_share_pct": pct1(share),
        "_share": share,
        "consecutive_reliance_years": school["consecutive_reliance_years"],
        "reliance_flag": flag,
        "narrative_required": flag == "LONG_TERM_RELIANCE",
    }


def recompute_school_flag(school):
    """Recomputed on certification, legacy placement, install and decommission."""
    school["reliance_flag"] = school_metrics(school)["reliance_flag"]
    return school["reliance_flag"]


def district_summary():
    qualifying = [s for s in db.schools.values() if s.get("certified_study_id")]
    count = len(qualifying)
    if count == 0:
        average = D("0.0")
        long_term = 0
    else:
        shares = []
        long_term = 0
        for school in qualifying:
            metrics = school_metrics(school)
            shares.append(metrics["_share"])
            if metrics["reliance_flag"] == "LONG_TERM_RELIANCE":
                long_term += 1
        average = round_half_up(sum(shares, D(0)) / D(count), 1)
    return {
        "qualifying_school_count": count,
        "district_average_portable_share_pct": pct1(average),
        "long_term_reliance_school_count": long_term,
        "rounding_basis": C.RELIANCE_ROUNDING_BASIS,
    }
