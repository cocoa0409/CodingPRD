"""The single ordered evaluation of the 38-rung validation ladder (PRD 2.8).

Rungs are checked strictly in ascending order and the FIRST rung whose condition
fires produces the response; no later rung is evaluated.  Rungs 1-11 and 38 are
generic and implemented here from each endpoint's declaration; rungs 12-37 are
endpoint-specific closures registered under their rung number, and this loop is
what guarantees they run lowest-number-first.
"""

import derive
import store
from constants import (
    ENTITY_BACKED_MEMBER_ROLES,
    RESTRICTED_GATE_BLOCK_LIST,
    ROLES,
    WRITE_GATE_EXCLUSION_LIST,
)
from errors import ApiError
from registry import BODY_FK_KINDS, PATH_KINDS, collection
from timeutil import clock, parse_instant


# --------------------------------------------------------------- type checks
def _type_ok(value, ftype):
    if ftype == "string":
        return isinstance(value, str)
    if ftype == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if ftype == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if ftype == "boolean":
        return isinstance(value, bool)
    if ftype == "array":
        return isinstance(value, list)
    if ftype == "datetime":
        return isinstance(value, str) and parse_instant(value) is not None
    return True


# ------------------------------------------------- reachable households (H2)
def _household_of(kind, row):
    if row is None:
        return None
    if kind == "households":
        return row["id"]
    if kind in (
        "members",
        "subscriptions",
        "rooms",
        "items",
        "policies",
        "packages",
        "claims",
        "estate_plans",
        "share_grants",
    ):
        return row.get("household_id")
    if kind == "assets":
        item = store.items.get(row["item_id"])
        return item.get("household_id") if item else None
    if kind == "appraisals":
        item = store.items.get(row["item_id"])
        return item.get("household_id") if item else None
    if kind == "package_lines":
        package = store.packages.get(row["package_id"])
        return package.get("household_id") if package else None
    if kind == "claim_lines":
        claim = store.claims.get(row["claim_id"])
        return claim.get("household_id") if claim else None
    if kind == "allocations":
        plan = store.estate_plans.get(row["estate_plan_id"])
        return plan.get("household_id") if plan else None
    return None


def reachable_households(spec, path_params, body, args):
    """PRD 2.7 hook H2 operates on the household(s) reachable from the request
    path or body."""
    found = []

    def add(hid):
        if hid and hid in store.households and hid not in found:
            found.append(hid)

    for param in spec.params:
        kind = PATH_KINDS.get(param)
        if kind is None:
            continue
        row = collection(kind[0]).get(path_params.get(param))
        add(_household_of(kind[0], row))
    if spec.share_token:
        token = path_params.get("share_token")
        for grant in store.share_grants.values():
            if grant["share_token"] == token:
                add(grant["household_id"])
                break
    if isinstance(body, dict):
        for field, (kind, _err) in BODY_FK_KINDS.items():
            value = body.get(field)
            if isinstance(value, str):
                add(_household_of(kind, collection(kind).get(value)))
    return found


# ------------------------------------------------------------- the ladder
def run_ladder(ctx):
    spec = ctx.spec

    _rung_1_authenticated(ctx)
    _rung_2_authorized(ctx)
    _rung_3_request_shape(ctx)
    _rung_4_enums(ctx)
    _rung_5_path_ids(ctx)
    _rung_6_body_references(ctx)
    _rung_7_share_token(ctx)
    _rung_8_household_scope(ctx)
    _rung_9_share_grant_usable(ctx)
    _rung_10_write_gate(ctx)
    _rung_11_restricted_gate(ctx)

    for rung in range(12, 38):
        check = spec.rungs.get(rung)
        if check is not None:
            check(ctx)

    _rung_38_occ(ctx)


def _rung_1_authenticated(ctx):
    if ctx.role is None or ctx.role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if ctx.role != "Anonymous" and not (ctx.user_id or "").strip():
        raise ApiError("ERR_UNAUTHENTICATED")


def _rung_2_authorized(ctx):
    if ctx.role not in ctx.spec.roles:
        raise ApiError("ERR_UNAUTHORIZED")


def _rung_3_request_shape(ctx):
    spec = ctx.spec
    for field, (ftype, required) in spec.body.items():
        present = field in ctx.body and ctx.body[field] is not None
        if not present:
            if required:
                raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
            continue
        value = ctx.body[field]
        # Enum-valued fields never route to ERR_INVALID_REQUEST for their value;
        # rung 4's closed iff-list owns them entirely.
        if field in spec.enums:
            continue
        if not _type_ok(value, ftype):
            raise ApiError("ERR_INVALID_REQUEST", "Field %s has the wrong type." % field)
        if ftype == "array" and required and len(value) == 0:
            raise ApiError("ERR_INVALID_REQUEST", "Field %s must not be empty." % field)
    if spec.rung3_extra is not None:
        spec.rung3_extra(ctx)


def _rung_4_enums(ctx):
    spec = ctx.spec
    for field, allowed in spec.enums.items():
        if field in ctx.body and ctx.body[field] is not None:
            if ctx.body[field] not in allowed:
                raise ApiError("ERR_INVALID_ENUM", "%s is not a declared value of %s." % (ctx.body[field], field))
    for field, allowed in spec.array_enums.items():
        value = ctx.body.get(field)
        if isinstance(value, list):
            for element in value:
                if element not in allowed:
                    raise ApiError("ERR_INVALID_ENUM", "%s is not a declared value of %s." % (element, field))
    for field, allowed in spec.query_enums.items():
        raw = ctx.args.get(field)
        if raw is not None and raw not in allowed:
            raise ApiError("ERR_INVALID_ENUM", "%s is not a declared value of %s." % (raw, field))


def _rung_5_path_ids(ctx):
    """Path ids are validated left to right; the leftmost unresolvable segment
    decides the error."""
    for param in ctx.spec.params:
        kind = PATH_KINDS.get(param)
        if kind is None:
            continue
        name, error_id = kind
        row = collection(name).get(ctx.path.get(param))
        if row is None:
            raise ApiError(error_id)
        ctx.resolved[param] = row


def _rung_6_body_references(ctx):
    for field in ctx.spec.fks:
        kind, error_id = BODY_FK_KINDS[field]
        value = ctx.body.get(field)
        if value is None:
            continue
        if field == "affected_room_ids":
            if isinstance(value, list):
                for element in value:
                    if not isinstance(element, str) or element not in collection(kind):
                        raise ApiError(error_id)
            continue
        if not isinstance(value, str) or value not in collection(kind):
            raise ApiError(error_id)


def _rung_7_share_token(ctx):
    if not ctx.spec.share_token:
        return
    token = ctx.path.get("share_token")
    for grant in store.all_of(store.share_grants):
        if grant["share_token"] == token:
            ctx.scratch["grant"] = grant
            return
    raise ApiError("ERR_SHARE_TOKEN_UNKNOWN")


def _rung_8_household_scope(ctx):
    spec = ctx.spec
    role = ctx.role
    if role == "Appraiser":
        appraisal = spec.appraisal_target(ctx) if spec.appraisal_target else None
        if appraisal is not None and ctx.user_id != appraisal["appraiser_id"]:
            raise ApiError("ERR_HOUSEHOLD_SCOPE_VIOLATION")
        return
    if role not in ENTITY_BACKED_MEMBER_ROLES:
        return
    member = store.members.get(ctx.user_id)
    target = spec.scope_household(ctx) if spec.scope_household else None
    if target is not None:
        if member is None or member.get("household_id") != target:
            raise ApiError("ERR_HOUSEHOLD_SCOPE_VIOLATION")
    if spec.owner_only:
        if member is None or member.get("member_role") != "OWNER":
            raise ApiError("ERR_HOUSEHOLD_SCOPE_VIOLATION")
    if spec.executor_only:
        if member is None or member.get("member_role") != "EXECUTOR":
            raise ApiError("ERR_HOUSEHOLD_SCOPE_VIOLATION")
        plan = spec.plan_target(ctx) if spec.plan_target else None
        if plan is not None and ctx.user_id != plan.get("executor_member_id"):
            raise ApiError("ERR_HOUSEHOLD_SCOPE_VIOLATION")


def _rung_9_share_grant_usable(ctx):
    if not ctx.spec.share_token:
        return
    grant = ctx.scratch["grant"]
    if grant["status"] != "ACTIVE":
        raise ApiError("ERR_SHARE_GRANT_INACTIVE")
    starts = grant.get("_starts_at_dt")
    expires = grant.get("_expires_at_dt")
    now = clock.now
    if starts is not None and now < starts:
        raise ApiError("ERR_SHARE_GRANT_INACTIVE")
    if expires is not None and now >= expires:
        raise ApiError("ERR_SHARE_GRANT_INACTIVE")
    if grant["access_count"] >= grant["access_cap"]:
        raise ApiError("ERR_SHARE_GRANT_INACTIVE")


def _gate_household(ctx):
    if ctx.spec.household is None:
        return None
    hid = ctx.spec.household(ctx)
    return store.households.get(hid) if hid else None


def _rung_10_write_gate(ctx):
    spec = ctx.spec
    if not spec.mutating:
        return
    if spec.key() in WRITE_GATE_EXCLUSION_LIST:
        return
    household = _gate_household(ctx)
    if household is not None and household["write_gate_state"] == "READ_ONLY":
        raise ApiError("ERR_VAULT_READ_ONLY")


def _rung_11_restricted_gate(ctx):
    if ctx.spec.key() not in RESTRICTED_GATE_BLOCK_LIST:
        return
    household = _gate_household(ctx)
    if household is not None and household["write_gate_state"] == "RESTRICTED":
        raise ApiError("ERR_REFRESH_OVERDUE")


def _rung_38_occ(ctx):
    occ = ctx.spec.occ
    if occ is None:
        return
    field, error_id, parent_of = occ
    parent = parent_of(ctx)
    supplied = ctx.body.get(field)
    if parent is None:
        return
    if supplied != parent["version"]:
        raise ApiError(error_id)
