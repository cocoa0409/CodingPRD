"""Calculation rules per SCAFFOLD.yaml Table 3 / PRD section 3.

All money is integer cents; scores/percentages use Decimal with ROUND_HALF_UP.
"""

from decimal import Decimal, ROUND_HALF_UP

import db


# ---------------------------------------------------------------------------
# screening_fit_score
# ---------------------------------------------------------------------------

AGE_POINTS = 40
REGION_POINTS = 30
PLATFORM_POINTS = 30
FIT_PASS_THRESHOLD = 60


def _round_half_up_int(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def screening_fit_score(participant, study, variant):
    """variant: 'self_reported' (uses platform_tags) or 'verified' (verified_platform_tags)."""
    age_points = AGE_POINTS if study["min_age"] <= participant["age_years"] <= study["max_age"] else 0
    region_points = REGION_POINTS if participant["region_code"] in (study.get("allowed_regions") or []) else 0

    if variant == "verified":
        basis = participant.get("verified_platform_tags") or []
    else:
        basis = participant.get("platform_tags") or []

    required = study.get("required_platforms") or []
    if len(required) == 0:
        platform_points = PLATFORM_POINTS
    else:
        overlap = len(set(basis) & set(required))
        platform_points = _round_half_up_int(
            Decimal(PLATFORM_POINTS) * Decimal(overlap) / Decimal(len(required))
        )
    return age_points + region_points + platform_points


# ---------------------------------------------------------------------------
# incentive_amount
# ---------------------------------------------------------------------------

BASE_PER_SESSION_CENTS = 5000
SURVEY_BONUS_CENTS = 1000
NO_SHOW_PENALTY_CENTS = 2000


def _study_session_ids(study_id):
    return {s["id"] for s in db.sessions.values() if s["study_id"] == study_id}


def _study_instrument_ids(study_id):
    return {i["id"] for i in db.instruments.values() if i["study_id"] == study_id}


def incentive_amounts(study_id, participant_id):
    """Return (attended, no_shows, passed_surveys)."""
    session_ids = _study_session_ids(study_id)
    attended = 0
    no_shows = 0
    for b in db.bookings.values():
        if b["participant_id"] != participant_id:
            continue
        if b["session_id"] not in session_ids:
            continue
        if b["status"] == "ATTENDED":
            attended += 1
        elif b["status"] == "NO_SHOW":
            no_shows += 1
    instrument_ids = _study_instrument_ids(study_id)
    passed_surveys = 0
    for r in db.responses.values():
        if r["participant_id"] != participant_id:
            continue
        if r["instrument_id"] not in instrument_ids:
            continue
        if r["status"] == "SUBMITTED" and r.get("passed") is True:
            passed_surveys += 1
    return attended, no_shows, passed_surveys


def _tier_multiplier(attended):
    if attended >= 3:
        return Decimal("1.5")
    if attended == 2:
        return Decimal("1.25")
    return Decimal("1.0")


def _scaled_base(attended):
    base = Decimal(attended * BASE_PER_SESSION_CENTS)
    scaled = (base * _tier_multiplier(attended)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(scaled)


def incentive_amount_provisional(study_id, participant_id):
    attended, _no_shows, passed_surveys = incentive_amounts(study_id, participant_id)
    return _scaled_base(attended) + passed_surveys * SURVEY_BONUS_CENTS


def incentive_amount_final(study_id, participant_id):
    attended, no_shows, passed_surveys = incentive_amounts(study_id, participant_id)
    raw = _scaled_base(attended) + passed_surveys * SURVEY_BONUS_CENTS - no_shows * NO_SHOW_PENALTY_CENTS
    return max(0, raw)


# ---------------------------------------------------------------------------
# survey_weighted_score
# ---------------------------------------------------------------------------

def _round2(x):
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def survey_weighted_score(response, instrument):
    """Return (weighted_score, score_pct, passed) as floats/bool per pinned rounding."""
    questions = instrument.get("questions") or []
    total_weight = Decimal("0")
    q_by_key = {}
    for q in questions:
        q_by_key[q["question_key"]] = q
        total_weight += Decimal(str(q["weight"]))

    weighted_sum = Decimal("0")
    for a in (response.get("answers") or []):
        q = q_by_key.get(a.get("question_key"))
        if q is None:
            continue  # existence validated earlier
        contribution = (
            Decimal(str(a["points"])) / Decimal(str(q["max_points"])) * Decimal(str(q["weight"]))
        )
        weighted_sum += _round2(contribution)

    weighted_score = _round2(weighted_sum)
    if total_weight == 0:
        score_pct = Decimal("0.00")
    else:
        score_pct = _round2(weighted_score / total_weight * Decimal("100"))
    passed = score_pct >= Decimal(str(instrument["pass_threshold"]))
    return float(weighted_score), float(score_pct), bool(passed)


# ---------------------------------------------------------------------------
# feedback_priority_score
# ---------------------------------------------------------------------------

SEVERITY_WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 5}
REACH_CAP = 1000
REACH_FACTOR = Decimal("0.5")
P1_MIN = Decimal("400")
P2_MIN = Decimal("200")
P3_MIN = Decimal("80")
FORCE_P1_REACH = 100


def feedback_priority_score(ticket):
    sev_w = Decimal(SEVERITY_WEIGHT[ticket["severity"]])
    repro = Decimal(str(ticket["reproducibility_pct"]))
    reach = Decimal(min(int(ticket["reach_count"]), REACH_CAP))
    raw = sev_w * Decimal("100") * repro + reach * REACH_FACTOR
    score = float(_round2(raw))
    score_dec = _round2(raw)
    if score_dec >= P1_MIN:
        tier = "P1"
    elif score_dec >= P2_MIN:
        tier = "P2"
    elif score_dec >= P3_MIN:
        tier = "P3"
    else:
        tier = "P4"
    if ticket["severity"] == "CRITICAL" and int(ticket["reach_count"]) >= FORCE_P1_REACH:
        tier = "P1"
    return score, tier


# ---------------------------------------------------------------------------
# cohort_build_summary
# ---------------------------------------------------------------------------

def cohort_build_summary(study_id):
    """Per PRD 3.4: only builds with released_at set; ordered released_at ASC, created_at ASC."""
    builds = [
        b for b in db.builds.values()
        if b["study_id"] == study_id and b.get("released_at") is not None
    ]
    builds.sort(key=lambda b: (_parse_sort(b["released_at"]), _parse_sort(b["created_at"]), b["_seq"]))

    entries = []
    prev_entry = None
    prev_participants = None
    for b in builds:
        issued = [
            e for e in db.exposure_records.values()
            if e["build_id"] == b["id"] and e["event_type"] == "KEY_ISSUED"
        ]
        redeemed = [
            e for e in db.exposure_records.values()
            if e["build_id"] == b["id"] and e["event_type"] == "KEY_REDEEMED"
        ]
        keys_issued = len(issued)
        keys_redeemed = len(redeemed)
        cur_participants = {e["participant_id"] for e in issued}

        if prev_entry is None or prev_entry["keys_issued"] == 0:
            retained = None
            retention_pct = None
        else:
            retained = len(prev_participants & cur_participants)
            retention_pct = float(_round2(
                Decimal(retained) / Decimal(prev_entry["keys_issued"]) * Decimal("100")
            ))

        entry = {
            "build_id": b["id"],
            "build_label": b["build_label"],
            "released_at": b["released_at"],
            "keys_issued": keys_issued,
            "keys_redeemed": keys_redeemed,
            "retained_from_previous": retained,
            "retention_pct": retention_pct,
        }
        entries.append(entry)
        prev_entry = entry
        prev_participants = cur_participants
    return {"study_id": study_id, "builds": entries}


def _parse_sort(s):
    from db import _parse_iso
    return _parse_iso(s)
