"""Evaluation composite scoring and team-match scoring."""
from db import store
from services import gates
from util import today, parse_date, parse_datetime, round_half_up


# ---------------------------------------------------------------------------
# evaluation_composite
# ---------------------------------------------------------------------------

def composite_score(aptitude, obedience):
    return round_half_up(0.6 * aptitude + 0.4 * obedience, 2)


def evaluation_passes(aptitude, obedience, composite, attempt_number):
    if aptitude < 70 or obedience < 70:
        return False
    if attempt_number >= 2:
        return composite >= 80.0
    return composite >= 75.0


# ---------------------------------------------------------------------------
# team_match_score
# ---------------------------------------------------------------------------

def team_eligible_for_request(team, request):
    """The candidate eligibility filter (PRD §3.6)."""
    if team["status"] != "ACTIVE":
        return False
    handler = store.handlers.get(team["handler_id"])
    if handler is None or handler["status"] != "ACTIVE":
        return False
    animal = store.animals.get(team["animal_id"])
    if animal is None or animal["status"] != "ACTIVE":
        return False
    if animal.get("welfare_hold_until") is not None:
        return False
    cert = None
    for c in store.certifications.values():
        if c["team_id"] == team["id"] and c["status"] == "ACTIVE":
            cert = c
            break
    if cert is None:
        return False
    facility = store.facilities.get(request["facility_id"])
    if facility is None:
        return False
    # SIGNED waiver matching required version
    waiver_ok = any(
        w["team_id"] == team["id"] and w["facility_id"] == facility["id"]
        and w["status"] == "SIGNED"
        and w["waiver_version"] == facility.get("required_waiver_version")
        for w in store.waivers.values()
    )
    if not waiver_ok:
        return False
    # Orientation COMPLETED and unexpired
    today_d = today()
    orientation_ok = any(
        o["team_id"] == team["id"] and o["facility_id"] == facility["id"]
        and o["status"] == "COMPLETED"
        and o.get("expires_on") and parse_date(o["expires_on"]) >= today_d
        for o in store.orientations.values()
    )
    if not orientation_ok:
        return False
    # Insurance adequate per facility-specific requirement
    if not gates.insurance_adequate(handler["id"], gates.facility_required_cents(facility)):
        return False
    # Nursing-home gate
    if facility.get("facility_type") == "NURSING_HOME" and handler.get("recognition_tier") == "NONE":
        return False
    return True


def team_match_score(team, request):
    """Weighted score per team_match_score (assumes eligibility already passed)."""
    handler = store.handlers.get(team["handler_id"])
    animal = store.animals.get(team["animal_id"])
    today_d = today()

    # Experience: 5 pts per full year since volunteer_since, capped at 40.
    years = (today_d - parse_date(handler["volunteer_since"])).days // 365
    exp = min(years * 5, 40)
    if exp < 0:
        exp = 0

    # Species: 25 exact match; 10 when the request is open; 0 on mismatch.
    pref = request.get("species_preference")
    if pref is not None:
        species = 25 if animal["species"] == pref else 0
    else:
        species = 10

    # Recency: 20 - 2 per full week since the latest VERIFIED visit at the
    # facility, clamped to [0, 20]; 0 when never verified there.
    latest_verified = None
    for v in store.visits.values():
        if (v["team_id"] == team["id"] and v["facility_id"] == request["facility_id"]
                and v["verification_status"] == "VERIFIED" and v.get("verified_at")):
            ts = parse_datetime(v["verified_at"])
            if latest_verified is None or ts > latest_verified:
                latest_verified = ts
    if latest_verified is None:
        recency = 0
    else:
        from util import now_dt
        days = (now_dt() - latest_verified).days
        weeks = days // 7
        recency = 20 - 2 * weeks
        recency = max(0, min(20, recency))

    # Workload penalty: 1 per full 10 forward minutes, capped at 30.
    fwd = animal.get("forward_workload_minutes", 0)
    penalty = min(fwd // 10, 30)

    subtotal = exp + species + recency - penalty
    multiplier = {"URGENT": 1.5, "HIGH": 1.2, "ROUTINE": 1.0}[request["priority"]]
    return round_half_up(subtotal * multiplier, 2)


def candidate_teams(request):
    """Ranked eligible slate: score DESC, team created_at ASC tie-break."""
    scored = []
    for team in store.teams.values():
        if not team_eligible_for_request(team, request):
            continue
        scored.append((team, team_match_score(team, request)))
    scored.sort(key=lambda pair: (-pair[1], pair[0].get("_seq", 0)))
    return scored
