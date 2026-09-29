"""Deterministic list ordering (PRD section 2.3).

Every collection is ordered by created_at ascending; the declared per-collection
tie-break settles rows minted in the same millisecond. `id` is never a sort key,
never a tie-break and never an allocation-order input.
"""

from db import db

_FAR = "9999-12-31"


def _channel_code(channel_id):
    channel = db.media_channels.get(channel_id)
    return channel["channel_code"] if channel else _FAR


def _iso(value):
    return value.isoformat() if value is not None else _FAR


def _key(kind):
    if kind == "markets":
        return lambda r: (r["created_at"], r["market_code"])
    if kind == "media_channels":
        return lambda r: (r["created_at"], r["channel_code"])
    if kind == "geo_cells":
        return lambda r: (r["created_at"], r["cell_code"])
    if kind == "data_windows":
        return lambda r: (r["created_at"], _iso(r["_window_start_date"]))
    if kind == "spend_observations":
        return lambda r: (r["created_at"], _iso(r["_period_start_date"]),
                          _channel_code(r["channel_id"]))
    if kind == "sales_observations":
        return lambda r: (r["created_at"], _iso(r["_period_start_date"]))
    if kind == "channel_contributions":
        return lambda r: (r["created_at"], _channel_code(r["channel_id"]))
    if kind == "budget_allocations":
        return lambda r: (r["created_at"], _channel_code(r["channel_id"]))
    if kind == "experiments":
        return lambda r: (r["created_at"], _iso(r["_start_date"]))
    if kind == "budget_scenarios":
        return lambda r: (r["created_at"], _iso(r["_planning_start_date"]))
    # model_runs, calibration_records, reconciliation_reports: created_at only.
    return lambda r: (r["created_at"],)


def sort_rows(kind, rows):
    return sorted(rows, key=_key(kind))


def by_channel_code(rows):
    """Ascending channel_code — the canonical processing order for channel-keyed work."""
    return sorted(rows, key=lambda r: _channel_code(r["channel_id"]))


def channels_by_code(channels):
    return sorted(channels, key=lambda c: c["channel_code"])
