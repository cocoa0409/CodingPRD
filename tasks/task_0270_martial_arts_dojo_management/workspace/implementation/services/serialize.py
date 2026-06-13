"""Entity -> API-view serializers.

Computed fields (Family.active_member_count, Member.outstanding_balance_cents,
Enrollment.rank_attendance_count, ClassSession.confirmed_count, ProShop
gross/net) are stored on the record and kept reconciled by the domain layer, so
serialization simply returns the stored representation (a shallow copy).
"""
import copy


def view(rec):
    """Return a JSON-safe shallow copy of a stored record."""
    return copy.deepcopy(rec)


def view_list(recs):
    return [view(r) for r in recs]
