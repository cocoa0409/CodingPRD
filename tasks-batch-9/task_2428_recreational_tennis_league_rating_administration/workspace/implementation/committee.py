"""Shared committee mechanics: vote tallies, quorum and the chair-voted guard."""

from decimal import Decimal

from store import db, touch

SUBJECT_TYPES = ("RATING_APPEAL", "GRIEVANCE")
SUBJECT_COLLECTIONS = {"RATING_APPEAL": "rating_appeals", "GRIEVANCE": "grievances"}
QUORUM_SUPPORT = 2

REQUIRED_MATCHES_COMPUTER = 3
REQUIRED_MATCHES_OTHER = 5
GAP_UNIT = Decimal("0.10")
STRIKE_RELIEF = Decimal("0.05")
STRIKE_RELIEF_CAP = 3
THRESHOLD_FLOOR = Decimal("0.20")
THRESHOLD_CEILING = Decimal("0.50")
DOWN_EXTRA_MARGIN = Decimal("0.10")


def subject_collection(subject_type):
    return SUBJECT_COLLECTIONS.get(subject_type)


def resolve_subject(subject_type, subject_id):
    name = subject_collection(subject_type)
    if name is None or not isinstance(subject_id, str):
        return None
    return getattr(db, name).get(subject_id)


def votes_for(subject_type, subject_id):
    return [v for v in db.committee_votes.values()
            if v.get("subject_type") == subject_type and v.get("subject_id") == subject_id]


def recount_votes(subject_type, subject):
    rows = votes_for(subject_type, subject["id"])
    support = sum(1 for v in rows if v.get("vote") == "SUPPORT")
    oppose = sum(1 for v in rows if v.get("vote") == "OPPOSE")
    subject["support_vote_count"] = support
    subject["oppose_vote_count"] = oppose
    touch(subject)
    return subject


def chair_voted(subject_type, subject_id, chair_player_id):
    return any(v.get("voter_player_id") == chair_player_id
               for v in votes_for(subject_type, subject_id))


def quorum_met(subject):
    support = int(subject.get("support_vote_count") or 0)
    oppose = int(subject.get("oppose_vote_count") or 0)
    return support >= QUORUM_SUPPORT and support > oppose


def round3(value):
    from credit import round3 as _round3
    return _round3(value)


def auto_grant_evaluation(direction, requested_level, rating_type, pinned_level,
                          pinned_dynamic, pinned_matches, pinned_strikes):
    """calculations.appeal_auto_grant_evaluation over the four pinned snapshots."""
    if pinned_dynamic is None or pinned_level is None:
        return False
    level = Decimal(str(pinned_level))
    dynamic = Decimal(str(pinned_dynamic))
    gap = round3(dynamic - level)
    required = (REQUIRED_MATCHES_COMPUTER if rating_type == "COMPUTER_RATED"
                else REQUIRED_MATCHES_OTHER)
    raw = GAP_UNIT * Decimal(required) - STRIKE_RELIEF * Decimal(
        min(int(pinned_strikes or 0), STRIKE_RELIEF_CAP))
    if raw > THRESHOLD_CEILING:
        raw = THRESHOLD_CEILING
    if raw < THRESHOLD_FLOOR:
        raw = THRESHOLD_FLOOR
    threshold = round3(raw)
    requested = Decimal(str(requested_level))
    if int(pinned_matches or 0) < required:
        return False
    if direction == "UP":
        return gap >= threshold and requested == level + Decimal("0.5")
    return (round3(-gap) >= round3(threshold + DOWN_EXTRA_MARGIN)
            and requested == level - Decimal("0.5")
            and int(pinned_strikes or 0) == 0)
