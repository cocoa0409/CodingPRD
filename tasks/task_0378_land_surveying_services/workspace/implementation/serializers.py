"""Serializers that present each entity with computed fields refreshed."""
from helpers import crew_open_assignment_count


def crew_out(rec):
    out = dict(rec)
    out["open_assignment_count"] = crew_open_assignment_count(rec["id"])
    return out


def plain_out(rec):
    return dict(rec)
