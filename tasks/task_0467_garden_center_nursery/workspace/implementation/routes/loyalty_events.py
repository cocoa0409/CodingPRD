"""LoyaltyEvent serializer (no direct create endpoint; ledger is system-written)."""


def loyalty_event_view(e):
    return {
        "id": e["id"],
        "account_id": e["account_id"],
        "event_type": e["event_type"],
        "points_delta": e["points_delta"],
        "source_kind": e["source_kind"],
        "source_ref_id": e["source_ref_id"],
        "recorded_at": e["recorded_at"],
        "created_at": e["created_at"],
    }
