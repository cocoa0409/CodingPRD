"""Request plumbing and validation rungs 1 to 5 (PRD 2.9).

Rungs 1 through 5 have no data dependencies, so they are executed uniformly by
the endpoint decorator before any handler body runs.  Rungs 6 onward are
data-dependent and are driven from the handlers in ladder order.
"""
import functools

from flask import request

import config
import envelope
import store
import util
from errors import ApiError


# ------------------------------------------------------------ field specs --
def field(name, kind, required=False, **opts):
    return {"name": name, "kind": kind, "required": required, "opts": opts}


class Ctx:
    def __init__(self, role, user_id, raw, source):
        self.role = role
        self.user_id = user_id
        self.raw = raw
        self.source = source
        self.values = {}
        self.present = set()

    def get(self, name, default=None):
        if name in self.values:
            return self.values[name]
        return default

    def has(self, name):
        return name in self.present

    def raw_get(self, name):
        return self.raw.get(name)


def _bad(message):
    raise ApiError("ERR_VALIDATION", message)


def _coerce(spec, value, source):
    kind = spec["kind"]
    name = spec["name"]
    opts = spec["opts"]

    if kind in ("string", "text", "id", "enum", "filter"):
        if not isinstance(value, str):
            _bad("%s must be a string." % name)
        if kind in ("string", "id") and value == "":
            _bad("%s must be a non-empty string." % name)
        return value

    if kind == "integer":
        if source == "query":
            try:
                value = int(str(value))
            except (TypeError, ValueError):
                _bad("%s must be an integer." % name)
        else:
            if isinstance(value, bool) or not isinstance(value, int):
                _bad("%s must be an integer." % name)
        _check_bounds(name, value, opts)
        return value

    if kind == "number":
        if source == "query":
            try:
                value = float(str(value))
            except (TypeError, ValueError):
                _bad("%s must be a number." % name)
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _bad("%s must be a number." % name)
        _check_bounds(name, value, opts)
        return value

    if kind == "boolean":
        if source == "query":
            low = str(value).lower()
            if low not in ("true", "false"):
                _bad("%s must be a boolean." % name)
            return low == "true"
        if not isinstance(value, bool):
            _bad("%s must be a boolean." % name)
        return value

    if kind == "datetime":
        try:
            return util.parse_dt(value)
        except util.DatetimeParseError:
            _bad("%s must be an ISO 8601 UTC instant." % name)

    if kind == "enum_array":
        if not isinstance(value, list):
            _bad("%s must be an array." % name)
        for item in value:
            if not isinstance(item, str):
                _bad("%s members must be strings." % name)
        return list(value)

    return value


def _check_bounds(name, value, opts):
    if "gt" in opts and not value > opts["gt"]:
        _bad("%s must be greater than %s." % (name, opts["gt"]))
    if "gte" in opts and not value >= opts["gte"]:
        _bad("%s must be at least %s." % (name, opts["gte"]))
    if "lte" in opts and not value <= opts["lte"]:
        _bad("%s must be no greater than %s." % (name, opts["lte"]))


def _apply_shape(ctx, specs):
    """Rung 4 -- presence, declared type and declared numeric bounds."""
    for spec in specs:
        name = spec["name"]
        raw = ctx.raw.get(name, None)
        missing = name not in ctx.raw or raw is None
        if missing:
            if spec["required"]:
                _bad("%s is required." % name)
            if "default" in spec["opts"]:
                ctx.values[name] = spec["opts"]["default"]
            continue
        ctx.present.add(name)
        ctx.values[name] = _coerce(spec, raw, ctx.source)


def _apply_enums(ctx, specs):
    """Rung 5 -- declared enum membership, for the exhaustive field list."""
    for spec in specs:
        name = spec["name"]
        if name not in ctx.present:
            continue
        kind = spec["kind"]
        members = spec["opts"].get("members")
        if not members:
            continue
        rung5 = spec["opts"].get("rung5", True)
        value = ctx.values[name]
        if kind == "enum":
            if value not in members:
                if rung5:
                    raise ApiError("ERR_INVALID_ENUM", "%s is not a declared member." % name)
                _bad("%s is not a declared member." % name)
        elif kind == "enum_array":
            for item in value:
                if item not in members:
                    if rung5:
                        raise ApiError(
                            "ERR_INVALID_ENUM", "%s members must be declared members." % name
                        )
                    _bad("%s members must be declared members." % name)


PAGINATION_SPECS = (
    field("limit", "integer", False,
          gte=config.PAGINATION_MIN_LIMIT, lte=config.PAGINATION_MAX_LIMIT,
          default=config.PAGINATION_DEFAULT_LIMIT),
    field("offset", "integer", False, gte=0, default=config.PAGINATION_DEFAULT_OFFSET),
)


def endpoint(roles, specs=(), source=None, paginated=False, role_hook=None):
    """Wrap a handler with validation rungs 1 to 5."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**path_params):
            eff_source = source or ("query" if request.method == "GET" else "body")
            # ---- rung 1: both identity headers present and non-empty --------
            role = request.headers.get("X-User-Role")
            user_id = request.headers.get("X-User-ID")
            if not role or not user_id:
                raise ApiError("ERR_UNAUTHENTICATED")
            # ---- rung 2: the role names one of the seven declared roles -----
            if role not in config.ALL_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")

            raw = _read_payload(eff_source)
            ctx = Ctx(role, user_id, raw, eff_source)

            # ---- rung 3: the role is authorised on this endpoint ------------
            if role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            if role_hook is not None:
                role_hook(ctx)

            all_specs = list(specs)
            if paginated:
                all_specs = list(PAGINATION_SPECS) + all_specs
            # ---- rung 4 then rung 5 -----------------------------------------
            _apply_shape(ctx, all_specs)
            _apply_enums(ctx, all_specs)

            return fn(ctx, **path_params)

        return wrapper

    return decorator


def _read_payload(source):
    if source == "query":
        return {k: v for k, v in request.args.items()}
    body = None
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:  # pragma: no cover - defensive
        body = None
    # A missing or non-object body is treated as empty so that the ladder still
    # reports rung 3 before rung 4 when both would fire.
    if not isinstance(body, dict):
        return {}
    return body


def pagination_window(ctx, rows):
    limit = ctx.get("limit", config.PAGINATION_DEFAULT_LIMIT)
    offset = ctx.get("offset", config.PAGINATION_DEFAULT_OFFSET)
    return envelope.paginate(rows, limit, offset)


def apply_filters(ctx, rows, mapping):
    """Narrow rows by exact match on every supplied filter (PRD 2.3)."""
    out = rows
    for param, fieldname in mapping.items():
        if ctx.has(param):
            wanted = ctx.get(param)
            out = [r for r in out if _as_text(r.get(fieldname)) == wanted]
    return out


def _as_text(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def order_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def require_row(table, row_id, code):
    row = store.get(table, row_id)
    if row is None:
        raise ApiError(code)
    return row
