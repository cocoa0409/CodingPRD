"""Enrollment derived-field recompute + serialization (PRD 2.5, 3.2, 3.5).

The Enrollment carries many derived fields (actual_hours, pace_pct,
total_charges_cents, total_credits_cents, ledger_balance_cents,
projected_balance_cents). They are recomputed from scratch over the qualifying
child records so that compensating events leave no drift.

Storage strategy: total_charges_cents is snapshotted at enrollment create.
total_credits_cents is maintained as the running ledger sum bumped on each
post/return (per the state-machine side effects), but because every recompute is
full, it always equals the from-scratch sum of POSTED net. We store the
persisted figures on the row and refresh the read-time figures on serialization.
"""
import db
from services import calc


def recompute_hours(enrollment):
    """Refresh actual_hours and pace_pct from the qualifying child records."""
    enrollment["actual_hours"] = calc.actual_hours(enrollment, db)
    enrollment["pace_pct"] = calc.sap_pace(
        enrollment["actual_hours"], enrollment["scheduled_hours_to_date"]
    )


def recompute_pace(enrollment):
    enrollment["pace_pct"] = calc.sap_pace(
        enrollment["actual_hours"], enrollment["scheduled_hours_to_date"]
    )


def recompute_ledger(enrollment):
    """Full recompute of total_credits_cents and ledger_balance_cents over the
    set of POSTED disbursements (CALC ledger_balance)."""
    enrollment["total_credits_cents"] = calc.posted_credits(enrollment, db)
    enrollment["ledger_balance_cents"] = (
        enrollment["total_charges_cents"] - enrollment["total_credits_cents"]
    )


def serialize(enrollment):
    """Produce the API view of an enrollment with all derived fields current.

    Derived fields are recomputed at read time (PRD 2.5 lists actual_hours,
    pace_pct, the ledger figures, and projected_balance_cents as derived) so a
    GET always reflects the current child records.
    """
    e = dict(enrollment)
    # Refresh derived read-time figures.
    e["actual_hours"] = calc.actual_hours(enrollment, db)
    e["pace_pct"] = calc.sap_pace(e["actual_hours"], e["scheduled_hours_to_date"])
    e["total_credits_cents"] = calc.posted_credits(enrollment, db)
    e["ledger_balance_cents"] = e["total_charges_cents"] - e["total_credits_cents"]
    e["projected_balance_cents"] = (
        e["total_charges_cents"] - calc.projected_credits(enrollment, db)
    )
    return e
