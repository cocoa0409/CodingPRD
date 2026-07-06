"""Serializers stripping internal fields for API output."""
from db import public

# Internal-only field names (prefixed with underscore or explicit).
_INTERNAL = ("_seq", "_delivered_at", "_initial_partner_charge_cents", "_default_payout_fee_bps_snapshot")


def serialize(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if k not in _INTERNAL}
