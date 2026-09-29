"""Shared list helpers."""
from core import public_list, success_array


def sort_created_asc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sort_charters(rows):
    by_id = sorted(rows, key=lambda r: r["id"])
    return sorted(by_id, key=lambda r: r["created_at"], reverse=True)


def sort_milestones(rows):
    return sorted(rows, key=lambda r: (r["planned_start_utc"], r["created_at"], r["_seq"]))


def paged(rows, limit, offset):
    total = len(rows)
    window = rows[offset : offset + limit]
    return success_array(public_list(window), limit, offset, total)


def apply_eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]
