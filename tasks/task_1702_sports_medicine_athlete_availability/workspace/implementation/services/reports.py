"""Confidentiality redaction filter, availability report rows, injury-rate analytics."""
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, clock_dt
from services.common import find_all, find_one
from services.derived import TIER_RANK, driving_case, effective_designation

SCOPE_RANK = {"TIER_ONLY": 1, "GENERAL": 2, "FULL": 3}
SURFACES = ["GRASS", "TURF", "COURT", "ICE", "TRAINING_ROOM"]


def materialize_lazy_expiry(grant):
    """Lazy EXPIRED: if ACTIVE and current_utc > effective_to, treat as EXPIRED
    (persisted state change; no version bump per scaffold empty side_effects)."""
    if grant["status"] == "ACTIVE" and clock_dt() > grant["_effective_to_dt"]:
        grant["status"] = "EXPIRED"
    return grant


def select_grant(athlete_id, audience):
    """Grant selection: grantee_role == audience, ACTIVE after lazy expiry,
    current_utc within [effective_from, effective_to] inclusive; max scope rank,
    ties by created_at asc."""
    now = clock_dt()
    best = None
    for g in STORE["disclosure_grants"].values():
        if g["athlete_id"] != athlete_id or g["grantee_role"] != audience:
            continue
        materialize_lazy_expiry(g)
        if g["status"] != "ACTIVE":
            continue
        if not (g["_effective_from_dt"] <= now <= g["_effective_to_dt"]):
            continue
        if best is None:
            best = g
        else:
            r_new = SCOPE_RANK[g["scope"]]
            r_old = SCOPE_RANK[best["scope"]]
            if r_new > r_old or (r_new == r_old and g["created_at"] < best["created_at"]):
                best = g
    return best


def compute_report_rows(team_id, audience):
    team = STORE["teams"].get(team_id)
    athletes = find_all("athletes", lambda a: a["team_id"] == team_id)
    rows = []
    for a in athletes:
        row = {"athlete_id": a["id"], "availability_tier": a["availability_tier"]}
        driving = driving_case(a["id"])
        designation = body_region = diagnosis_detail = None
        if driving is not None:
            designation = effective_designation(driving)
            code = STORE["diagnosis_codes"].get(driving["diagnosis_code_id"])
            if code is not None:
                body_region = code["body_region"]
                diagnosis_detail = code["code"]

        if audience == "MEDICAL":
            visible = {"designation", "body_region", "diagnosis_detail"}
            scope = None
        else:
            grant = select_grant(a["id"], audience)
            scope = grant["scope"] if grant is not None else None
            visible = set()
            if scope in ("GENERAL", "FULL"):
                visible |= {"designation", "body_region"}
            if scope == "FULL":
                visible.add("diagnosis_detail")
            # STRICT override applied LAST
            if team is not None and team.get("hipaa_mode", "STRICT") == "STRICT":
                visible.discard("diagnosis_detail")
                if scope == "GENERAL":
                    visible.discard("designation")
                    visible.discard("body_region")

        if "designation" in visible:
            row["designation"] = designation
        if "body_region" in visible:
            row["body_region"] = body_region
        if "diagnosis_detail" in visible:
            row["diagnosis_detail"] = diagnosis_detail

        rows.append((a, row))

    rows.sort(key=lambda ar: (TIER_RANK[ar[0]["availability_tier"]],
                              ar[0]["position"], ar[0]["created_at"]))
    return [r for _, r in rows]


def injury_rate_groups(team_id, from_d, to_d):
    """position x surface groups over inclusive window."""
    athletes = find_all("athletes",
                        lambda a: a["team_id"] == team_id
                        and a["roster_status"] != "RELEASED")
    positions = sorted({a["position"] for a in athletes})
    groups = []
    sessions = find_all("workload_sessions", lambda s: s["team_id"] == team_id)
    cases = find_all("injury_cases", lambda c: c["team_id"] == team_id)
    ath_by_id = {a["id"]: a for a in find_all("athletes", lambda a: a["team_id"] == team_id)}

    for pos in positions:
        for surface in SURFACES:
            exposures = 0
            for s in sessions:
                if not s["counts_as_exposure"]:
                    continue
                ath = ath_by_id.get(s["athlete_id"])
                if ath is None or ath["position"] != pos:
                    continue
                if s["surface"] != surface:
                    continue
                if not (from_d <= s["_session_date"] <= to_d):
                    continue
                if s["_session_date"] < ath["_enrollment_date"]:
                    continue
                exposures += 1
            if exposures == 0:
                continue
            injuries = 0
            for c in cases:
                ath = ath_by_id.get(c["athlete_id"])
                if ath is None or ath["position"] != pos:
                    continue
                if c["surface"] != surface:
                    continue
                if not (from_d <= c["_occurred_on"] <= to_d):
                    continue
                if c["status"] == "CLOSED" and c.get("_closed_on") is not None \
                        and c["_closed_on"] < from_d:
                    continue
                injuries += 1
            rate = (Decimal(injuries * 1000) / Decimal(exposures)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
            groups.append({
                "position": pos,
                "surface": surface,
                "exposures": exposures,
                "injuries": injuries,
                "rate_per_1000": float(rate),
            })
    return groups
