"""Shared list-endpoint plumbing: filters are applied to created_at-ordered rows,
then the page is cut (PRD 2.3)."""
from core import rows, paginate, pagination_params, filter_arg


def std_list(table, filters=(), items=None, extra=None):
    """filters: iterable of (query_param, row_field) compared as strings.
    extra: optional callable(items) -> items applied after the simple filters."""
    pagination_params()  # priority 28: pagination sanity before anything else
    data = rows(table) if items is None else items
    for param, field in filters:
        value = filter_arg(param)
        if value is None:
            continue
        data = [r for r in data if r.get(field) is not None and str(r.get(field)) == value]
    if extra is not None:
        data = extra(data)
    return paginate(data)


def array_contains_filter(param, field):
    def apply(data):
        value = filter_arg(param)
        if value is None:
            return data
        return [r for r in data if value in (r.get(field) or [])]
    return apply
