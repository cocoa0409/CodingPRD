"""Entity -> public JSON serializers.

Strips internal fields (those prefixed with '_'). Common system fields
(created_at/updated_at/version) are stored directly on each record except
PracticeAttempt, which carries only id + created_at (PRD §2.4).
"""


def _public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def course(rec):
    return _public(rec)


def instructor(rec):
    return _public(rec)


def cohort(rec):
    return _public(rec)


def student(rec):
    return _public(rec)


def enrollment(rec):
    return _public(rec)


def practice_attempt(rec):
    # PracticeAttempt carries only id + created_at among common fields; no
    # updated_at, no version (PRD §2.4). Nothing else to strip — internal keys
    # are already '_'-prefixed.
    return _public(rec)


def installment_plan(rec):
    return _public(rec)


def guarantee_claim(rec):
    return _public(rec)
