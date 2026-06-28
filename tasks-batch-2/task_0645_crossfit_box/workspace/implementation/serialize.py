"""Public serialization of entities.

Strips internal-only keys (those prefixed with '_') and surfaces computed
fields (Member.reservation_suspended, ClassSession.seats_reserved/waitlist_count,
CompetitionTeam.roster_size, BenchmarkResult.is_pr) which are stored directly on
the record and reconciled on every mutation.
"""

NO_SHOW_SUSPEND_THRESHOLD = 3


def _public(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def member_view(m):
    out = _public(m)
    # reservation_suspended is computed: true iff no_show_strikes >= 3.
    out["reservation_suspended"] = m["no_show_strikes"] >= NO_SHOW_SUSPEND_THRESHOLD
    return out


def view(entity_kind, obj):
    if entity_kind == "member":
        return member_view(obj)
    return _public(obj)


def plain(obj):
    return _public(obj)
