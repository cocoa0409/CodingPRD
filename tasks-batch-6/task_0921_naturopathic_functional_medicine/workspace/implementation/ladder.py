"""The order of refusal (PRD 2.6) implemented as ONE ordered engine.

Every endpoint declares a spec; `run()` walks the twenty-eight rungs in strict
priority order and no handler ever re-implements a rung out of band. Rung 6 --
the global clinical write gate -- therefore pre-empts payload shape (11) and
enum membership (12) on exactly the eight gated families and on nothing else.
"""

from flask import request

import config
from clock import parse_date, parse_instant
from envelope import list_response, object_response
from errors import ApiError
from store import db

# --- path / body foreign-key resolution --------------------------------------

PATH_KINDS = {
    "patient": ("patients", "ERR_PATIENT_NOT_FOUND"),
    "practitioner": ("practitioners", "ERR_PRACTITIONER_NOT_FOUND"),
    "protocol": ("protocols", "ERR_PROTOCOL_NOT_FOUND"),
    "lab_order": ("lab_orders", "ERR_LAB_ORDER_NOT_FOUND"),
    "encounter": ("encounters", "ERR_ENCOUNTER_NOT_FOUND"),
    "membership": ("memberships", "ERR_MEMBERSHIP_NOT_FOUND"),
    "intake_section": ("intake_sections", "ERR_RESOURCE_NOT_FOUND"),
    "protocol_item": ("protocol_items", "ERR_RESOURCE_NOT_FOUND"),
    "product": ("products", "ERR_RESOURCE_NOT_FOUND"),
    "lot": ("lots", "ERR_RESOURCE_NOT_FOUND"),
    "dispense": ("dispenses", "ERR_RESOURCE_NOT_FOUND"),
    "thread": ("threads", "ERR_RESOURCE_NOT_FOUND"),
    "superbill": ("superbills", "ERR_RESOURCE_NOT_FOUND"),
    "referral": ("referrals", "ERR_RESOURCE_NOT_FOUND"),
}

BODY_FK_KINDS = {
    "patient_id": ("patients", "ERR_PATIENT_NOT_FOUND"),
    "practitioner_id": ("practitioners", "ERR_PRACTITIONER_NOT_FOUND"),
    "primary_practitioner_id": ("practitioners", "ERR_PRACTITIONER_NOT_FOUND"),
    "encounter_id": ("encounters", "ERR_ENCOUNTER_NOT_FOUND"),
    "supersedes_protocol_id": ("protocols", "ERR_PROTOCOL_NOT_FOUND"),
    "product_id": ("products", "ERR_REFERENCE_NOT_FOUND"),
    "product_lot_id": ("lots", "ERR_REFERENCE_NOT_FOUND"),
    "protocol_item_id": ("protocol_items", "ERR_REFERENCE_NOT_FOUND"),
}


def _lookup(collection_name, value):
    collection = getattr(db, collection_name)
    try:
        return collection.get(value)
    except TypeError:
        return None


class Ctx(object):
    """Everything a handler needs, assembled by the ladder as it descends."""

    def __init__(self):
        self.role = None
        self.user_id = None
        self.body = {}
        self.path = {}
        self.fk = {}
        self.limit = config.PAGE_LIMIT_DEFAULT
        self.offset = config.PAGE_OFFSET_DEFAULT
        self.scratch = {}

    def get(self, field, default=None):
        value = self.body.get(field, default)
        return default if value is None else value

    def present(self, field):
        return field in self.body and self.body[field] is not None

    def args_get(self, name):
        """A query-string filter value, or None when the parameter is absent.

        An off-enum filter value is not a validation failure anywhere in this
        API - it simply matches no rows.
        """
        if name not in request.args:
            return None
        return request.args.get(name)

    def args_bool(self, name):
        raw = self.args_get(name)
        if raw is None:
            return None
        return str(raw).strip().lower() in ("true", "1", "yes")


# --- rung 11 payload shape ----------------------------------------------------


def _type_ok(kind, value):
    if kind == "string":
        return isinstance(value, str) and value != ""
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list)
    if kind == "date":
        return parse_date(value) is not None
    if kind == "datetime":
        return parse_instant(value) is not None
    return True


def _range_ok(opts, value):
    if opts.get("positive") and value <= 0:
        return False
    if "min" in opts and value < opts["min"]:
        return False
    if "max" in opts and value > opts["max"]:
        return False
    return True


def check_shape(ctx, fields, cross=None):
    for spec in fields:
        name, kind, required = spec[0], spec[1], spec[2]
        opts = spec[3] if len(spec) > 3 else {}
        raw = ctx.body.get(name)
        if raw is None:
            if required:
                raise ApiError(
                    "ERR_VALIDATION", "Field '%s' is required." % name
                )
            continue
        if not _type_ok(kind, raw):
            raise ApiError(
                "ERR_VALIDATION", "Field '%s' is not a valid %s." % (name, kind)
            )
        if kind in ("int", "number") and not _range_ok(opts, raw):
            raise ApiError(
                "ERR_VALIDATION", "Field '%s' is out of the accepted range." % name
            )
        if kind == "array" and opts.get("of") == "string":
            for element in raw:
                if not isinstance(element, str):
                    raise ApiError(
                        "ERR_VALIDATION",
                        "Field '%s' must contain only strings." % name,
                    )
    if cross:
        cross(ctx)


def check_enums(ctx, enums):
    for name, members in enums.items():
        raw = ctx.body.get(name)
        if raw is None:
            continue
        if raw not in members:
            raise ApiError(
                "ERR_INVALID_ENUM",
                "Field '%s' must be one of %s." % (name, ", ".join(members)),
            )


# --- rung 13 pagination -------------------------------------------------------


def _parse_pagination(ctx):
    args = request.args
    limit = config.PAGE_LIMIT_DEFAULT
    offset = config.PAGE_OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if str(raw).strip() != str(limit):
            raise ApiError("ERR_INVALID_PAGINATION")
        if limit < config.PAGE_LIMIT_MIN or limit > config.PAGE_LIMIT_MAX:
            raise ApiError("ERR_INVALID_PAGINATION")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if str(raw).strip() != str(offset):
            raise ApiError("ERR_INVALID_PAGINATION")
        if offset < config.PAGE_OFFSET_DEFAULT:
            raise ApiError("ERR_INVALID_PAGINATION")
    ctx.limit = limit
    ctx.offset = offset


# --- the engine ---------------------------------------------------------------


def run(spec):
    ctx = Ctx()

    # ---- rung 1: authentication
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise ApiError("ERR_UNAUTHENTICATED")
    ctx.role = role
    ctx.user_id = user_id

    # body is parsed up front but never judged before its rung
    if request.method in ("POST", "PATCH", "PUT"):
        try:
            parsed = request.get_json(force=True, silent=True)
        except Exception:  # pragma: no cover - defensive
            parsed = None
        ctx.body = parsed if isinstance(parsed, dict) else {}

    # ---- rung 2: role permission
    roles = spec.get("roles", [])
    if role not in roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    role_action = spec.get("role_action")
    if role_action:
        role_action(ctx)

    # ---- rung 3: path existence, strictly left to right
    for kind, value in spec.get("path", []):
        collection_name, error_id = PATH_KINDS[kind]
        row = _lookup(collection_name, value)
        if row is None:
            raise ApiError(error_id)
        ctx.path[kind] = row

    # ---- rung 4: body foreign-key existence, in declared input order
    for field in spec.get("body_fks", []):
        if field not in ctx.body or ctx.body[field] is None:
            continue
        collection_name, error_id = BODY_FK_KINDS[field]
        row = _lookup(collection_name, ctx.body[field])
        if row is None:
            raise ApiError(error_id)
        ctx.fk[field] = row

    # ---- rung 5: patient ownership
    owner = spec.get("owner")
    if owner and ctx.role == config.ROLE_PATIENT:
        owner_patient_id = owner(ctx)
        if owner_patient_id is not None and owner_patient_id != ctx.user_id:
            raise ApiError("ERR_OWNERSHIP_VIOLATION")

    # ---- rung 6: global clinical write gate
    gate = spec.get("gate")
    if gate:
        patient = gate(ctx)
        if patient is not None and patient.get("clinical_write_gate") != "OPEN":
            raise ApiError("ERR_CLINICAL_WRITE_FROZEN")

    # ---- rung 7: segregation of duties
    if spec.get("segregation"):
        spec["segregation"](ctx)

    # ---- rung 8: own-state validity
    if spec.get("own_state"):
        spec["own_state"](ctx)

    # ---- rung 9: dependent-state validity
    if spec.get("dependent_state"):
        spec["dependent_state"](ctx)

    # ---- rung 10: optimistic concurrency
    occ = spec.get("occ")
    if occ:
        field, parent_of = occ
        if field in ctx.body and ctx.body[field] is not None:
            parent = parent_of(ctx)
            supplied = ctx.body[field]
            if (
                parent is None
                or not isinstance(supplied, int)
                or isinstance(supplied, bool)
                or supplied != parent.get("version")
            ):
                raise ApiError("ERR_STALE_VERSION")

    # ---- rung 11: payload shape
    if spec.get("shape") is not None:
        check_shape(ctx, spec["shape"], spec.get("cross"))

    # ---- rung 12: enum membership
    if spec.get("enums"):
        check_enums(ctx, spec["enums"])

    # ---- rung 13: pagination shape
    if spec.get("paginated"):
        _parse_pagination(ctx)

    # ---- rungs 14..28: the domain-safety tail, in ladder order
    for check in spec.get("business", []):
        check(ctx)

    result = spec["handler"](ctx)
    if isinstance(result, tuple):
        return result
    return object_response(result, spec.get("status", 200))


def paginate(ctx, rows):
    total = len(rows)
    page = rows[ctx.offset: ctx.offset + ctx.limit]
    return page, total


def list_result(ctx, rows, serializer):
    page, total = paginate(ctx, rows)
    return list_response([serializer(r) for r in page], ctx.limit, ctx.offset, total)
