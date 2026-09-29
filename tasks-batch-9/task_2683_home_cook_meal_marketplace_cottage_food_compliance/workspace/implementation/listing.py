"""Shared list-endpoint plumbing (PRD 2.3)."""
from core import ok_list, ordered
from validation import filters, pagination


def list_rows(rows, filter_names):
    limit, offset = pagination()
    args = filters(*filter_names)
    selected = []
    for row in ordered(rows):
        keep = True
        for name, value in args.items():
            stored = row.get(name)
            if stored is None:
                keep = False
                break
            if str(stored) != value:
                keep = False
                break
        if keep:
            selected.append(row)
    total = len(selected)
    page = selected[offset : offset + limit]
    return ok_list(page, limit, offset, total)
