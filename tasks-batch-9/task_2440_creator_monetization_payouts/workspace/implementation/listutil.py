"""Filtered, sorted, paginated list reads (PRD 2.3, 3.10)."""
from envelope import listing, paginate


def _match(value, raw):
    if isinstance(value, bool):
        return raw.strip().lower() in ("true", "1") if value else raw.strip().lower() in ("false", "0")
    if value is None:
        return raw.strip().lower() in ("null", "none", "")
    return str(value) == raw


def filter_rows(rows, args, spec):
    """spec maps query-parameter name -> record field name."""
    for param, field in spec.items():
        if param in args:
            raw = args.get(param)
            rows = [r for r in rows if _match(r.get(field), raw)]
    return rows


def respond(ctx, rows, serializer):
    window, total = paginate(rows, ctx.limit, ctx.offset)
    return listing([serializer(r) for r in window], ctx.limit, ctx.offset, total)
