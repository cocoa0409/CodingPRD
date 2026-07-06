"""Public serialization of records.

Strips the internal `_seq` ordering key and surfaces computed fields. Computed
fields (campaign earned/cost/roi, client lifetime, period totals/hours, etc.)
are kept current on the stored record by the mutation paths, so serialization
mostly just hides internals.
"""


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def client_out(rec):
    return _public(rec)


def outlet_out(rec):
    return _public(rec)


def journalist_out(rec):
    return _public(rec)


def campaign_out(rec):
    return _public(rec)


def retainer_period_out(rec):
    return _public(rec)


def spokesperson_out(rec):
    return _public(rec)


def media_list_out(rec):
    return _public(rec)


def pitch_out(rec):
    return _public(rec)


def press_release_out(rec):
    return _public(rec)


def distribution_out(rec):
    return _public(rec)


def coverage_out(rec):
    return _public(rec)


def interview_out(rec):
    return _public(rec)


def crisis_event_out(rec):
    return _public(rec)


def time_entry_out(rec):
    return _public(rec)
