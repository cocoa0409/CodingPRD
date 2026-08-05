"""The single global ordered validation ladder (PRD 2.6), twenty-five rungs.

This is ONE engine, not a collection of per-handler checks.  Every request,
whatever handler it is ultimately bound for, walks the same rungs in ascending
order and returns the FIRST failure it hits.  Pre-emption is therefore
structural: rung 3 (confidentiality wall) runs before the path identifier is
resolved at rung 4, and rung 6 (reporting-period freeze) runs before payload
well-formedness at rung 7, enum membership at rung 8, optimistic concurrency
at rung 9 and state at rung 10.

Rungs 1-9 are generic and driven by declarative Spec data.  Rungs 10-25 are
per-endpoint callables held in `Spec.checks`, keyed by rung number, and the
engine runs them strictly in ascending rung order -- an endpoint cannot
accidentally evaluate rung 20 before rung 17.
"""

from flask import request

from . import constants, envelope, serializers, store
from .errors import ApiError, KIND_NOT_FOUND


class ObjectResult(object):
    def __init__(self, data, status=200):
        self.data = data
        self.status = status


class ArrayResult(object):
    def __init__(self, items, limit, offset, total):
        self.items = items
        self.limit = limit
        self.offset = offset
        self.total = total


class Spec(object):
    def __init__(
        self,
        method,
        path,
        roles,
        handler,
        status=200,
        walled=False,
        path_ids=(),
        body_fks=(),
        role_extra=None,
        scope=None,
        freeze=None,
        payload=None,
        enums=(),
        occ=None,
        checks=None,
        is_write=False,
    ):
        self.method = method
        self.path = path
        self.roles = list(roles)
        self.handler = handler
        self.status = status
        self.walled = walled
        self.path_ids = list(path_ids)
        self.body_fks = list(body_fks)
        self.role_extra = role_extra
        self.scope = scope
        self.freeze = freeze
        self.payload = payload
        self.enums = list(enums)
        self.occ = occ
        self.checks = dict(checks or {})
        self.is_write = is_write

    @property
    def flask_rule(self):
        return self.path.replace("{", "<").replace("}", ">")

    @property
    def endpoint_name(self):
        return "%s %s" % (self.method, self.path)


class Ctx(object):
    def __init__(self, spec, path_params):
        self.spec = spec
        self.path_params = path_params
        self.role = request.headers.get("X-User-Role")
        self.user_id = request.headers.get("X-User-ID")
        raw = request.get_json(silent=True)
        self.body = raw if isinstance(raw, dict) else {}
        self.args = request.args
        self.ent = {}
        self.provider = None
        self.scratch = {}

    # convenience accessors -------------------------------------------------
    def entity(self, key):
        return self.ent.get(key)

    def body_get(self, field, default=None):
        value = self.body.get(field, default)
        return value


# ------------------------------------------------------------------ rung 1 --

def rung1_auth(ctx):
    if not ctx.role or not ctx.user_id:
        raise ApiError("ERR_UNAUTHENTICATED")
    if ctx.role not in constants.ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")


# ------------------------------------------------------------------ rung 2 --

def rung2_role(ctx):
    if ctx.role not in ctx.spec.roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    if ctx.spec.role_extra is not None:
        ctx.spec.role_extra(ctx)


# ------------------------------------------------------------------ rung 3 --

def rung3_wall(ctx):
    """CONFIDENTIALITY WALL -- pre-empts existence, scope and every payload
    rung.  Runs before the path identifier is resolved, so a walled read of an
    identifier that does not exist still returns the wall error."""
    if ctx.spec.walled and ctx.role in constants.EMPLOYER_SIDE_ROLES:
        raise ApiError("ERR_CONFIDENTIALITY_WALL")


# ------------------------------------------------------------------ rung 4 --

def rung4_existence(ctx):
    for param, kind in ctx.spec.path_ids:
        rid = ctx.path_params.get(param)
        row = store.get(kind, rid)
        if row is None:
            raise ApiError(KIND_NOT_FOUND[kind])
        ctx.ent[param] = row
    for field, kind, required in ctx.spec.body_fks:
        value = ctx.body.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            continue  # a wrong-typed identifier is a rung 7 payload defect
        row = store.get(kind, value)
        if row is None:
            raise ApiError(KIND_NOT_FOUND[kind])
        ctx.ent[field] = row


# ------------------------------------------------------------------ rung 5 --

def rung5_scope(ctx):
    """Identity scope for the entity-backed roles (PRD 2.1 / 2.6 rung 5)."""
    if ctx.role in (constants.ROLE_CLINICIAN, constants.ROLE_CARE_NAVIGATOR):
        provider = store.get("provider", ctx.user_id)
        wanted = "CLINICIAN" if ctx.role == constants.ROLE_CLINICIAN else "NAVIGATOR"
        if provider is None or provider.get("provider_function") != wanted:
            raise ApiError("ERR_SCOPE_VIOLATION")
        ctx.provider = provider
    if ctx.spec.scope is not None:
        ctx.spec.scope(ctx)


# ------------------------------------------------------------------ rung 6 --

def rung6_freeze(ctx):
    if ctx.spec.freeze is not None:
        ctx.spec.freeze(ctx)


def frozen_period_covers(employer_id, governing_date):
    """A FINALIZED or CLOSED period of that employer whose closed span
    contains the governing date.  RESTATING and OPEN do not freeze."""
    from . import timeutil

    if governing_date is None or employer_id is None:
        return None
    for period in store.all_rows("period"):
        if period["employer_id"] != employer_id:
            continue
        if period["status"] not in ("FINALIZED", "CLOSED"):
            continue
        start = timeutil.parse_date(period["period_start"])
        end = timeutil.parse_date(period["period_end"])
        if start is None or end is None:
            continue
        if start <= governing_date <= end:
            return period
    return None


def freeze_if_covered(employer_id, governing_date):
    if frozen_period_covers(employer_id, governing_date) is not None:
        raise ApiError("ERR_PERIOD_FINALIZED")


# ------------------------------------------------------------------ rung 7 --

def rung7_payload(ctx):
    if ctx.spec.payload is not None:
        ctx.spec.payload(ctx)


# ------------------------------------------------------------------ rung 8 --

def rung8_enum(ctx):
    """Enum membership for EVERY enum-valued input on a write endpoint.

    The catalogue rule adopted for this API: any field whose declared type is
    an enumeration reports membership failure here as ERR_INVALID_ENUM -- not
    only the thirteen the PRD prose happens to name.  A missing required enum
    field, or a non-string value, is a rung 7 payload defect and has already
    been reported above.
    """
    for field, enum_name in ctx.spec.enums:
        if field not in ctx.body:
            continue
        value = ctx.body.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            continue
        if value not in constants.ENUMS[enum_name]:
            raise ApiError("ERR_INVALID_ENUM", "Field '%s' is not a declared member." % field)


# ------------------------------------------------------------------ rung 9 --

def rung9_occ(ctx):
    if ctx.spec.occ is None:
        return
    field, resolver = ctx.spec.occ
    supplied = ctx.body.get(field)
    parent = resolver(ctx)
    if parent is None:
        return
    if supplied != parent["version"]:
        raise ApiError("ERR_STALE_VERSION")


GENERIC_RUNGS = [
    (1, rung1_auth),
    (2, rung2_role),
    (3, rung3_wall),
    (4, rung4_existence),
    (5, rung5_scope),
    (6, rung6_freeze),
    (7, rung7_payload),
    (8, rung8_enum),
    (9, rung9_occ),
]


def run_ladder(ctx):
    for _number, fn in GENERIC_RUNGS:
        fn(ctx)
    for number in sorted(ctx.spec.checks):
        ctx.spec.checks[number](ctx)


# ------------------------------------------------------------- dispatching --

def make_view(spec):
    def view(**path_params):
        with store.request_lock:
            store.begin()
            try:
                ctx = Ctx(spec, path_params)
                run_ladder(ctx)
                result = spec.handler(ctx)
                store.commit()
            except ApiError as err:
                store.rollback()
                return envelope.error_response(err.error_id, err.message, err.http_status)
            except Exception:  # pragma: no cover - defensive
                store.rollback()
                raise
            if isinstance(result, ArrayResult):
                return envelope.array_response(
                    result.items, result.limit, result.offset, result.total
                )
            status = result.status if isinstance(result, ObjectResult) else spec.status
            data = result.data if isinstance(result, ObjectResult) else result
            return envelope.object_response(data, status)

    view.__name__ = "view_%s" % abs(hash(spec.endpoint_name))
    return view


def paginate(ctx, kind, rows):
    limit, offset = envelope.read_pagination(ctx.args)
    ordered = store.sorted_rows(kind, rows)
    total = len(ordered)
    page = ordered[offset: offset + limit]
    return ArrayResult(serializers.dump_many(kind, page), limit, offset, total)
