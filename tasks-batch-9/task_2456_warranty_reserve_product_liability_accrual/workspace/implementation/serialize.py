"""Resource representations.

Rows are stored with exactly the keys the representation exposes plus private
``_``-prefixed bookkeeping keys, so serialisation is a filter.  ClaimObservation
and ReserveRollforward carry only ``id`` and ``created_at`` — no ``updated_at``
and no ``version`` (PRD §2.4).
"""

import store

SIGNIFICANT_EXPOSURE_THRESHOLD_CENTS = 50_000_000


def _plain(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def period_disclosure_counters(period):
    """The three computed disclosure counters of an accrual period (PRD §3.1)."""
    pid = period["id"]
    rollforward_generated = any(
        r["period_id"] == pid for r in store.all_rows("rollforwards")
    )
    significant = 0
    for fa in store.all_rows("field_actions"):
        if (
            fa["approved_period_id"] == pid
            and fa["approval_state"] == "APPROVED"
            and fa["specific_accrual_cents"] >= SIGNIFICANT_EXPOSURE_THRESHOLD_CENTS
        ):
            significant += 1
    return {
        "rollforward_generated": rollforward_generated,
        "significant_exposure_count": significant,
        "requires_significant_exposure_disclosure": significant >= 1,
    }


def dump(row):
    """Serialise one row, applying read-time derivations where declared."""
    out = _plain(row)
    kind = row.get("_kind")
    if kind == "AccrualPeriod":
        out.update(period_disclosure_counters(row))
    return out


def dump_many(rows):
    return [dump(r) for r in rows]
