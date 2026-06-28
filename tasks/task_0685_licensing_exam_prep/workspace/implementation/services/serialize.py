"""Entity -> public JSON serialization. Strips internal-only keys (_seq).

QuestionItem carries ONLY id + created_at (PRD §2.4 — immutable, no updated_at /
version). Every other entity carries the id/created_at/updated_at/version quartet.
"""

# Fields that are stored but never returned to clients.
_INTERNAL = {"_seq"}


def public(rec):
    return {k: v for k, v in rec.items() if k not in _INTERNAL}


def public_list(recs):
    return [public(r) for r in recs]
