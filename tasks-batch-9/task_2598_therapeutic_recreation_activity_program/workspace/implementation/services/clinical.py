"""Assessment provenance, supervision tier, engagement index, refusal streak."""
from services import constants as C
from services.numbers import divide, num, rhu


def resident_assessments(st, resident_id):
    return [a for a in st.assessments.values() if a["resident_id"] == resident_id]


def rank_assessments(rows):
    """effective_date DESC, then created_at DESC (filing order breaks ties)."""
    return sorted(
        rows,
        key=lambda a: (a["effective_date"], a["created_at"], a["_seq"]),
        reverse=True,
    )


def governing_assessment(st, resident_id):
    rows = rank_assessments(resident_assessments(st, resident_id))
    return rows[0] if rows else None


def refresh_superseded(st, resident_id):
    """Exactly one assessment in a resident's history carries superseded=false."""
    rows = rank_assessments(resident_assessments(st, resident_id))
    for index, row in enumerate(rows):
        row["superseded"] = index != 0
    return rows[0] if rows else None


def tier_for_assessment(assessment):
    if assessment is None:
        return None
    cognition = C.COGNITION_BAND[assessment["cognitive_level"]]
    function = C.FUNCTION_BAND[assessment["functional_mobility"]]
    return "TIER_%d" % max(cognition, function)


def tier_weight(tier):
    return C.TIER_WEIGHT.get(tier, "0")


def apply_clinical_mirrors(st, resident):
    """Mirror the governing assessment onto the resident row."""
    winner = governing_assessment(st, resident["id"])
    if winner is None:
        resident["cognitive_level"] = None
        resident["functional_mobility"] = None
        resident["interest_domains"] = []
        resident["supervision_tier"] = None
        return None
    resident["cognitive_level"] = winner["cognitive_level"]
    resident["functional_mobility"] = winner["functional_mobility"]
    resident["interest_domains"] = list(winner["interest_domains"])
    resident["supervision_tier"] = tier_for_assessment(winner)
    return winner


def resident_tier(st, resident):
    return resident.get("supervision_tier")


def record_outcome(record):
    """Records report `outcome`; every calculation reads it, never `status`."""
    if record["status"] == "FINALIZED":
        return record.get("finalized_from")
    return record["status"]


def resident_records(st, resident_id):
    return [r for r in st.participation.values() if r["resident_id"] == resident_id]


def rank_records_desc(st, rows):
    """session starts_at DESC, then record created_at DESC."""
    def key(record):
        session = st.sessions.get(record["session_id"])
        starts_at = session["starts_at"] if session else ""
        return (starts_at, record["created_at"], record["_seq"])

    return sorted(rows, key=key, reverse=True)


def engagement_index(st, resident_id):
    candidates = [
        r
        for r in resident_records(st, resident_id)
        if record_outcome(r) in ("ATTENDED", "REFUSED")
    ]
    window = rank_records_desc(st, candidates)[: C.ENGAGEMENT_WINDOW_SIZE]
    if not window:
        return num(0, 3)
    points = 0
    for record in window:
        if record_outcome(record) == "ATTENDED":
            points += C.ENGAGEMENT_POINTS.get(record.get("engagement_level"), 0)
    denominator = C.MAX_ENGAGEMENT_POINTS * len(window)
    return float(rhu(divide(points, denominator), 3))


def refusal_streak(st, resident_id):
    candidates = [
        r
        for r in resident_records(st, resident_id)
        if record_outcome(r) in ("ATTENDED", "REFUSED", "ABSENT")
    ]
    streak = 0
    for record in rank_records_desc(st, candidates):
        if record_outcome(record) == "REFUSED":
            streak += 1
        else:
            break
    return streak


def absence_count(st, resident_id):
    return len(
        [r for r in resident_records(st, resident_id) if record_outcome(r) == "ABSENT"]
    )
