"""Endpoint registry.  Every route declares, declaratively, exactly which rungs
of the PRD 2.8 ladder apply to it and with what arguments; ladder.py is the one
place that evaluates them, always in ascending rung order.
"""

import re

import store

ENDPOINTS = []

_PARAM_RE = re.compile(r"\{([a-z_]+)\}")

# Path id -> (collection, error id).  PRD ladder rung 5.
PATH_KINDS = {
    "member_id": ("members", "ERR_REFERENCE_NOT_FOUND"),
    "household_id": ("households", "ERR_HOUSEHOLD_NOT_FOUND"),
    "subscription_id": ("subscriptions", "ERR_REFERENCE_NOT_FOUND"),
    "room_id": ("rooms", "ERR_REFERENCE_NOT_FOUND"),
    "item_id": ("items", "ERR_ITEM_NOT_FOUND"),
    "asset_id": ("assets", "ERR_REFERENCE_NOT_FOUND"),
    "appraiser_id": ("appraisers", "ERR_REFERENCE_NOT_FOUND"),
    "appraisal_id": ("appraisals", "ERR_REFERENCE_NOT_FOUND"),
    "policy_id": ("policies", "ERR_REFERENCE_NOT_FOUND"),
    "package_id": ("packages", "ERR_REFERENCE_NOT_FOUND"),
    "package_line_id": ("package_lines", "ERR_REFERENCE_NOT_FOUND"),
    "claim_id": ("claims", "ERR_REFERENCE_NOT_FOUND"),
    "claim_line_id": ("claim_lines", "ERR_REFERENCE_NOT_FOUND"),
    "estate_plan_id": ("estate_plans", "ERR_REFERENCE_NOT_FOUND"),
    "allocation_id": ("allocations", "ERR_REFERENCE_NOT_FOUND"),
    "share_grant_id": ("share_grants", "ERR_REFERENCE_NOT_FOUND"),
}

# Body foreign key -> (collection, error id).  PRD ladder rung 6.
BODY_FK_KINDS = {
    "household_id": ("households", "ERR_HOUSEHOLD_NOT_FOUND"),
    "room_id": ("rooms", "ERR_REFERENCE_NOT_FOUND"),
    "item_id": ("items", "ERR_REFERENCE_NOT_FOUND"),
    "policy_id": ("policies", "ERR_REFERENCE_NOT_FOUND"),
    "package_id": ("packages", "ERR_REFERENCE_NOT_FOUND"),
    "appraiser_id": ("appraisers", "ERR_REFERENCE_NOT_FOUND"),
    "heir_member_id": ("members", "ERR_REFERENCE_NOT_FOUND"),
    "executor_member_id": ("members", "ERR_REFERENCE_NOT_FOUND"),
    "scope_room_id": ("rooms", "ERR_REFERENCE_NOT_FOUND"),
    "scope_package_id": ("packages", "ERR_REFERENCE_NOT_FOUND"),
    "scope_claim_id": ("claims", "ERR_REFERENCE_NOT_FOUND"),
    "affected_room_ids": ("rooms", "ERR_REFERENCE_NOT_FOUND"),
}


def collection(name):
    return getattr(store, name)


class Spec(object):
    def __init__(self, method, template, roles, code, handler, opts):
        self.method = method
        self.template = template
        self.roles = tuple(roles)
        self.code = code
        self.handler = handler
        self.params = _PARAM_RE.findall(template)
        self.flask_rule = _PARAM_RE.sub(lambda m: "<" + m.group(1) + ">", template)
        self.body = opts.get("body") or {}
        self.enums = opts.get("enums") or {}
        self.array_enums = opts.get("array_enums") or {}
        self.query_enums = opts.get("query_enums") or {}
        self.fks = tuple(opts.get("fks") or ())
        self.mutating = opts.get("mutating", False)
        self.household = opts.get("household")
        self.scope_household = opts.get("scope_household", self.household)
        self.owner_only = opts.get("owner_only", False)
        self.executor_only = opts.get("executor_only", False)
        self.plan_target = opts.get("plan_target")
        self.appraisal_target = opts.get("appraisal_target")
        self.share_token = opts.get("share_token", False)
        self.rung3_extra = opts.get("rung3_extra")
        self.rungs = opts.get("rungs") or {}
        self.occ = opts.get("occ")
        self.name = handler.__name__

    def key(self):
        return (self.method, self.template)


def endpoint(method, template, roles, code=200, **opts):
    def decorator(fn):
        ENDPOINTS.append(Spec(method, template, roles, code, fn, opts))
        return fn

    return decorator


class Ctx(object):
    """Everything a rung or a handler needs about the request in flight."""

    __slots__ = (
        "spec",
        "method",
        "template",
        "role",
        "user_id",
        "body",
        "args",
        "path",
        "resolved",
        "scratch",
    )

    def __init__(self, spec, role, user_id, body, args, path):
        self.spec = spec
        self.method = spec.method
        self.template = spec.template
        self.role = role
        self.user_id = user_id
        self.body = body
        self.args = args
        self.path = path
        self.resolved = {}
        self.scratch = {}

    # -- convenience accessors -------------------------------------------
    def row(self, param):
        return self.resolved.get(param)

    def field(self, name, default=None):
        value = self.body.get(name, default)
        return default if value is None else value

    def has(self, name):
        return name in self.body and self.body[name] is not None
