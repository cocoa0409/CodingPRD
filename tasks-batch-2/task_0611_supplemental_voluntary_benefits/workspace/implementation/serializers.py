"""Public serializers — produce response `data` payloads for each entity.

Each serializer drops internal bookkeeping keys (those prefixed with '_') and
returns exactly the documented field set. Field order does not matter to JSON.
"""


def _public(record):
    """Strip internal '_'-prefixed bookkeeping fields."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def employer(r):
    return _public(r)


def plan_product(r):
    return _public(r)


def schedule_item(r):
    # BenefitScheduleItem is immutable: only id + created_at, no version/updated_at.
    return _public(r)


def enrollment_period(r):
    return _public(r)


def employee(r):
    return _public(r)


def disbursement_account(r):
    return _public(r)


def enrollment(r):
    return _public(r)


def payroll_deduction(r):
    return _public(r)


def claim(r):
    return _public(r)


def disbursement(r):
    return _public(r)


def portability_conversion(r):
    return _public(r)


def section125_election(r):
    return _public(r)
