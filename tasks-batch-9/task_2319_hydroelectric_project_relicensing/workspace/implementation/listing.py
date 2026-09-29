"""Shared list-endpoint plumbing: filters then pagination (PRD 2.3)."""
import payload
import response


def _matches(row, filters):
    for field, raw in filters.items():
        if raw is None:
            continue
        value = row.get(field)
        if isinstance(value, bool):
            wanted = raw.strip().lower()
            if wanted in ("true", "1", "yes"):
                if value is not True:
                    return False
            elif wanted in ("false", "0", "no"):
                if value is not False:
                    return False
            else:
                return False
        elif isinstance(value, int) and not isinstance(value, bool):
            try:
                if value != int(raw):
                    return False
            except (TypeError, ValueError):
                return False
        else:
            if value is None or str(value) != raw:
                return False
    return True


def respond(rows, serializer, filter_names=()):
    filters = {name: payload.query_filter(name) for name in filter_names}
    selected = [r for r in rows if _matches(r, filters)]
    limit, offset = payload.pagination()
    page = selected[offset : offset + limit]
    return response.list_response(
        [serializer(row) for row in page], limit, offset, len(selected)
    )
