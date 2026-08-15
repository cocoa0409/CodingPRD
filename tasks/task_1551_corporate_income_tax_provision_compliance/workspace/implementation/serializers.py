"""Entity -> API dict serializers.

Records are stored with exactly their declared fields plus the common system
fields (id/created_at/updated_at/version), so serialization is a shallow copy —
except UncertainTaxPosition, whose interest_accrued_cents is recomputed
against the logical clock on every read (SCAFFOLD entities / PRD §3.4).
"""
from services.calc import compute_utp_interest
from util import CLOCK


def serialize(rec: dict) -> dict:
    return dict(rec)


def serialize_utp(pos: dict) -> dict:
    out = dict(pos)
    out["interest_accrued_cents"] = compute_utp_interest(pos, CLOCK.today())
    return out


def serialize_many(records) -> list:
    return [serialize(r) for r in records]
