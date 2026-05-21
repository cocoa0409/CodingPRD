"""Generic list filtering and pagination for collections."""

import projection


def paginate_sorted(values, limit, offset, sort_key=lambda v: v["created_at"]):
    sorted_values = sorted(values, key=sort_key)
    total = len(sorted_values)
    window = sorted_values[offset : offset + limit]
    return window, total


def render_window(window, drop=()):
    return projection.render_list(window, drop=drop)
