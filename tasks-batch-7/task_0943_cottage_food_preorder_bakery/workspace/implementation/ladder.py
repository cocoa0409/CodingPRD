"""The 55-rung rejection ladder: rungs 1-14 plus the shared helpers for 15+.

PRD 2.6 fixes the ladder as TOTAL and DETERMINISTIC -- the lowest-numbered
violated rung wins and no later rung is evaluated.  Rungs 1-4 (request shape),
5-7 (path existence, left to right), 8-10 (body foreign keys), 11-12
(ownership) and 13-14 (body shape, then enums) are enforced here, in that
order, before any handler code runs.  Handlers then evaluate rungs 15 and up
in strictly ascending order in straight-line code.
"""

import functools
import json

from flask import request

import config
from db import DB
from errors import ApiError
from response import page_args
from tsutil import parse_dt

# ---------------------------------------------------------------------------
# path parameter -> (collection, error id, rung)
# ---------------------------------------------------------------------------
PATH_SPEC = {
    "offer_window_id": ("offer_windows", "ERR_OFFER_WINDOW_NOT_FOUND", 5),
    "order_id": ("orders", "ERR_ORDER_NOT_FOUND", 6),
    "order_line_id": ("order_lines", "ERR_ORDER_NOT_FOUND", 6),
    "baker_id": ("bakers", "ERR_RESOURCE_NOT_FOUND", 7),
    "customer_id": ("customers", "ERR_RESOURCE_NOT_FOUND", 7),
    "recipe_id": ("recipes", "ERR_RESOURCE_NOT_FOUND", 7),
    "recipe_component_id": ("recipe_components", "ERR_RESOURCE_NOT_FOUND", 7),
    "ingredient_lot_id": ("ingredient_lots", "ERR_RESOURCE_NOT_FOUND", 7),
    "menu_item_id": ("menu_items", "ERR_RESOURCE_NOT_FOUND", 7),
    "batch_id": ("batches", "ERR_RESOURCE_NOT_FOUND", 7),
    "label_id": ("labels", "ERR_RESOURCE_NOT_FOUND", 7),
    "subscription_id": ("subscriptions", "ERR_RESOURCE_NOT_FOUND", 7),
    "subscription_cycle_id": ("subscription_cycles", "ERR_RESOURCE_NOT_FOUND", 7),
    "payment_id": ("payments", "ERR_RESOURCE_NOT_FOUND", 7),
    "money_movement_id": ("money_movements", "ERR_RESOURCE_NOT_FOUND", 7),
    "delivery_route_id": ("delivery_routes", "ERR_RESOURCE_NOT_FOUND", 7),
    "review_id": ("reviews", "ERR_RESOURCE_NOT_FOUND", 7),
}

# ---------------------------------------------------------------------------
# body foreign keys -> (collection, error id, rung)
#   rung 8: body offer_window_id      -> ERR_OFFER_WINDOW_NOT_FOUND
#   rung 9: body menu_item_id         -> ERR_MENU_ITEM_NOT_FOUND
#   rung 10: everything else, in ALPHABETICAL order of the field name
# ---------------------------------------------------------------------------
BODY_FK_SPEC = {
    "offer_window_id": ("offer_windows", "ERR_OFFER_WINDOW_NOT_FOUND", 8),
    "menu_item_id": ("menu_items", "ERR_MENU_ITEM_NOT_FOUND", 9),
    "baker_id": ("bakers", "ERR_RESOURCE_NOT_FOUND", 10),
    "customer_id": ("customers", "ERR_RESOURCE_NOT_FOUND", 10),
    "delivery_route_id": ("delivery_routes", "ERR_RESOURCE_NOT_FOUND", 10),
    "ingredient_lot_id": ("ingredient_lots", "ERR_RESOURCE_NOT_FOUND", 10),
    "order_id": ("orders", "ERR_RESOURCE_NOT_FOUND", 10),
    "order_line_id": ("order_lines", "ERR_RESOURCE_NOT_FOUND", 10),
    "recipe_id": ("recipes", "ERR_RESOURCE_NOT_FOUND", 10),
    "sub_recipe_id": ("recipes", "ERR_RESOURCE_NOT_FOUND", 10),
    "subscription_id": ("subscriptions", "ERR_RESOURCE_NOT_FOUND", 10),
}


class Ctx:
    """Per-request context: identity, parsed body, resolved path entities."""

    __slots__ = ("role", "user_id", "body", "args", "p", "now", "method", "path")

    def __init__(self, role, user_id, body, args, method, path):
        self.role = role
        self.user_id = user_id
        self.body = body
        self.args = args
        self.p = {}
        self.now = DB.now()
        self.method = method
        self.path = path

    # -- rungs 8/9/10 -----------------------------------------------------
    def body_fks(self, required=(), optional=()):
        """Resolve body foreign keys in rung order (8, then 9, then 10 in
        alphabetical field-name order).  A key that is absent or null is NOT
        resolved here -- a missing required key is a rung-13 ERR_VALIDATION."""
        names = list(required) + list(optional)
        unknown = [n for n in names if n not in BODY_FK_SPEC]
        if unknown:  # pragma: no cover - programming error
            raise RuntimeError("undeclared body fk %r" % unknown)
        out = {}
        ordered = sorted(names, key=lambda n: (BODY_FK_SPEC[n][2], n))
        for name in ordered:
            coll, err, _rung = BODY_FK_SPEC[name]
            raw = self.body.get(name)
            if raw is None:
                out[name] = None
                continue
            rec = DB.get(coll, raw) if isinstance(raw, str) else None
            if rec is None:
                raise ApiError(err, "%s does not resolve." % name)
            out[name] = rec
        return out

    # -- rungs 11/12 ------------------------------------------------------
    def ownership(self, customer_id=None, baker_id=None):
        """Rung 11 then rung 12.  Admin and inspector identities are opaque and
        are never compared to any entity id."""
        if self.role == config.ROLE_CUSTOMER and customer_id is not None:
            if self.user_id != customer_id:
                raise ApiError("ERR_NOT_RESOURCE_OWNER",
                               "The acting customer does not own this resource.")
        if self.role == config.ROLE_BAKER and baker_id is not None:
            if self.user_id != baker_id:
                raise ApiError("ERR_NOT_RESOURCE_OWNER",
                               "The acting baker does not own this resource.")

    # -- rung 13 ----------------------------------------------------------
    def req_str(self, name, allow_empty=True):
        v = self.body.get(name)
        if not isinstance(v, str) or (not allow_empty and v == ""):
            raise ApiError("ERR_VALIDATION", "%s must be a string." % name)
        return v

    def opt_str(self, name, default=None, allow_empty=True):
        if name not in self.body or self.body.get(name) is None:
            return default
        return self.req_str(name, allow_empty=allow_empty)

    def req_int(self, name, minimum=None, maximum=None):
        v = self.body.get(name)
        if not isinstance(v, int) or isinstance(v, bool):
            raise ApiError("ERR_VALIDATION", "%s must be an integer." % name)
        if minimum is not None and v < minimum:
            raise ApiError("ERR_VALIDATION", "%s must be at least %s." % (name, minimum))
        if maximum is not None and v > maximum:
            raise ApiError("ERR_VALIDATION", "%s must be at most %s." % (name, maximum))
        return v

    def opt_int(self, name, default=None, minimum=None, maximum=None):
        if name not in self.body or self.body.get(name) is None:
            return default
        return self.req_int(name, minimum=minimum, maximum=maximum)

    def req_num(self, name, minimum=None):
        v = self.body.get(name)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ApiError("ERR_VALIDATION", "%s must be a number." % name)
        if minimum is not None and v < minimum:
            raise ApiError("ERR_VALIDATION", "%s must be at least %s." % (name, minimum))
        return v

    def opt_num(self, name, default=None, minimum=None):
        if name not in self.body or self.body.get(name) is None:
            return default
        return self.req_num(name, minimum=minimum)

    def req_bool(self, name):
        v = self.body.get(name)
        if not isinstance(v, bool):
            raise ApiError("ERR_VALIDATION", "%s must be a boolean." % name)
        return v

    def opt_bool(self, name, default=False):
        if name not in self.body or self.body.get(name) is None:
            return default
        return self.req_bool(name)

    def req_dt(self, name):
        v = self.body.get(name)
        if not isinstance(v, str) or parse_dt(v) is None:
            raise ApiError("ERR_VALIDATION",
                           "%s must be an ISO 8601 instant." % name)
        return v

    def opt_dt(self, name, default=None):
        if name not in self.body or self.body.get(name) is None:
            return default
        return self.req_dt(name)

    def req_list(self, name):
        v = self.body.get(name)
        if not isinstance(v, list):
            raise ApiError("ERR_VALIDATION", "%s must be an array." % name)
        return v

    def opt_list(self, name, default=None):
        if name not in self.body or self.body.get(name) is None:
            return [] if default is None else default
        return self.req_list(name)

    # -- rung 14 ----------------------------------------------------------
    def enum(self, name, set_name, required=True, default=None):
        """Rung 14.  ONLY the closed list of enum-valued body fields named in
        PRD 2.6 reaches this method; nothing else routes to ERR_INVALID_ENUM."""
        if name not in self.body or self.body.get(name) is None:
            if required:
                # absence is rung 13, not rung 14 -- caller ordered it already
                raise ApiError("ERR_VALIDATION", "%s is required." % name)
            return default
        v = self.body.get(name)
        allowed = config.ENUM_SETS[set_name]
        if not isinstance(v, str) or v not in allowed:
            raise ApiError("ERR_INVALID_ENUM",
                           "%s must be one of %s." % (name, ", ".join(allowed)))
        return v


def _parse_body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        raise ApiError("ERR_VALIDATION", "The request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_VALIDATION", "The request body must be a JSON object.")
    return parsed


def endpoint(roles, path=(), list_ep=False):
    """Wrap a handler with rungs 1-7.

    `path` is the ordered tuple of templated segment names as they appear in
    the URL; they are resolved by (rung, url position) so path existence is
    reported left to right within each rung.
    """

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            # ---- rung 1: both headers present and non-empty ---------------
            role = request.headers.get("X-User-Role")
            user_id = request.headers.get("X-User-ID")
            if not role or not user_id:
                raise ApiError("ERR_UNAUTHENTICATED",
                               "X-User-ID and X-User-Role are required.")
            # ---- rung 2: role names one of the four declared roles --------
            if role not in config.ALL_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED",
                               "X-User-Role is not a recognised role.")
            # ---- rung 3: role is admitted by this endpoint ----------------
            if role not in roles:
                raise ApiError("ERR_UNAUTHORIZED",
                               "Role %s may not call this endpoint." % role)
            # ---- rung 4: body parses / pagination bounds ------------------
            body = {}
            if request.method in ("POST", "PUT", "PATCH"):
                body = _parse_body()
            ctx = Ctx(role, user_id, body, request.args,
                      request.method, request.path)
            if list_ep:
                ctx.p["_page"] = page_args(request.args)
            # ---- rungs 5-7: path existence, by rung then url position -----
            order = sorted(
                range(len(path)),
                key=lambda i: (PATH_SPEC[path[i]][2], i),
            )
            for i in order:
                name = path[i]
                coll, err, _rung = PATH_SPEC[name]
                rec = DB.get(coll, kwargs.get(name))
                if rec is None:
                    raise ApiError(err, "%s does not resolve." % name)
                ctx.p[name] = rec
            return fn(ctx)

        return wrapper

    return deco
