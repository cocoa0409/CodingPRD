"""Output shapes.  Records are stored with exactly their public field set plus
private keys prefixed with an underscore, so serialization is a filtered copy
with the computed-on-read figures overlaid."""

from decimal import Decimal

import calc


def public(row, extra=None):
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = float(value) if isinstance(value, Decimal) else value
    if extra:
        for key, value in extra.items():
            out[key] = float(value) if isinstance(value, Decimal) else value
    return out


def institution(row):
    """period_count, audited_period_count and the giving aggregates are
    recomputed against the logical clock on every read (PRD 3.1)."""
    return public(row, calc.institution_computed(row))


def giving_period(row):
    return public(row)


def governance_authorization(row):
    return public(row)


def pledge_campaign(row):
    return public(row)


def pledge(row):
    return public(row)


def collateral_asset(row):
    return public(row, {"appraisal_age_days": calc.appraisal_age_days(row)})


def loan_application(row):
    return public(row)


def loan(row):
    return public(row)


def draw_request(row):
    return public(row)


def covenant(row):
    return public(row)


def workout_plan(row):
    return public(row)
