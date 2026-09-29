"""Route blueprints and shared query-filter helpers."""

from flask import request


def q(name):
    """Read an optional query-string filter; blank is treated as absent."""
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def apply_filters(rows, spec):
    """Filter rows by exact equality on (field -> query parameter name)."""
    out = list(rows)
    for field, param in spec.items():
        wanted = q(param)
        if wanted is None:
            continue
        out = [r for r in out if _as_text(r.get(field)) == wanted]
    return out


def _as_text(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return value if isinstance(value, str) else str(value)
