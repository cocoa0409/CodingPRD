"""Shared helpers for route modules."""
from datetime import datetime, timezone, timedelta
from clock import clock
from db import store, new_id
from envelope import success_list
from validate import pagination_params


def stamp(rec, common=True):
    """Populate identity + audit fields on a freshly built record dict."""
    rec["id"] = new_id()
    rec["created_at"] = clock.now()
    rec["_seq"] = store.next_seq()
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def sorted_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def list_response(rows, serializer):
    rows = sorted_rows(rows)
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset : offset + limit]
    return success_list([serializer(r) for r in page], limit, offset, total)


def day_window(report_date):
    """[00:00:00Z of report_date, +24h) half-open day window."""
    start = datetime.combine(report_date, datetime.min.time(), tzinfo=timezone.utc)
    return start, start + timedelta(hours=24)
