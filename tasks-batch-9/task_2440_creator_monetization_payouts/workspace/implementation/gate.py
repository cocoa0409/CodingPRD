"""Request gate: PRD 2.9 bands 1-4 (auth, shape, existence, ownership).

Every route declares its roles, path parameters, body field specs, body
references and ownership rule; this decorator runs them in the exact order of
the global rejection ladder so no handler can get precedence wrong.
"""
import functools

from flask import request

from apierrors import fail
from fields import parse_pagination, validate
from store import db

ROLE_NAMES = ("Creator", "PolicyReviewer", "FinanceOperator", "PlatformAdmin", "Auditor")

NOT_FOUND = {
    "creators": "ERR_CREATOR_NOT_FOUND",
    "tax_profiles": "ERR_TAX_PROFILE_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "content_items": "ERR_CONTENT_ITEM_NOT_FOUND",
    "appeals": "ERR_APPEAL_NOT_FOUND",
    "periods": "ERR_PERIOD_NOT_FOUND",
    "statements": "ERR_STATEMENT_NOT_FOUND",
    "payouts": "ERR_PAYOUT_NOT_FOUND",
    "investigations": "ERR_INVESTIGATION_NOT_FOUND",
    "funds": "ERR_FUND_NOT_FOUND",
}


class Ctx(object):
    def __init__(self):
        self.role = None
        self.user_id = None
        self.actor = None          # the Creator row when role == Creator
        self.body = {}
        self.data = {}
        self.path = {}
        self.refs = {}
        self.limit = 10
        self.offset = 0

    def supplied(self, name):
        return name in self.data.get("__supplied__", ())

    def val(self, name, default=None):
        value = self.data.get(name, default)
        return default if value is None and name not in self.data else value

    @property
    def is_creator(self):
        return self.role == "Creator"


def endpoint(roles, path=(), fields=(), refs=(), owner=None, listing=False):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**view_args):
            db.new_request()
            ctx = Ctx()

            # -------- band 1: authentication and authorization, four steps ----
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or not str(user_id).strip() or role is None or not str(role).strip():
                fail("ERR_MISSING_AUTH_HEADERS", "X-User-ID and X-User-Role are required.")
            user_id = user_id.strip()
            role = role.strip()
            if role not in ROLE_NAMES:
                fail("ERR_UNKNOWN_ROLE", "Unknown role '%s'." % role)
            ctx.role = role
            ctx.user_id = user_id
            if role == "Creator":
                actor = db.get("creators", user_id)
                if actor is None:
                    fail("ERR_CREATOR_IDENTITY_UNKNOWN",
                         "X-User-ID does not identify a creator record.")
                ctx.actor = actor
            if role not in roles:
                fail("ERR_ROLE_NOT_PERMITTED",
                     "Role '%s' may not perform this operation." % role)

            # -------- band 2: request shape, five steps -----------------------
            if listing:
                ctx.limit, ctx.offset = parse_pagination(request.args)
            if fields:
                body = request.get_json(silent=True)
                ctx.body = body if isinstance(body, dict) else {}
                ctx.data = validate(ctx.body, fields)
            else:
                body = request.get_json(silent=True)
                ctx.body = body if isinstance(body, dict) else {}
                ctx.data = {"__supplied__": set(ctx.body.keys())}

            # -------- band 3a: addressed rows, left to right ------------------
            for param, coll in path:
                row = db.get(coll, view_args.get(param))
                if row is None:
                    fail(NOT_FOUND[coll], "%s not found." % param)
                ctx.path[param] = row

            # -------- band 3b: body references, in declared order -------------
            for field_name, coll in refs:
                value = ctx.data.get(field_name)
                if value is None:
                    continue
                row = db.get(coll, value)
                if row is None:
                    fail(NOT_FOUND[coll], "%s not found." % field_name)
                ctx.refs[field_name] = row

            # -------- band 4: creator ownership scoping -----------------------
            if role == "Creator" and owner is not None:
                target = owner(ctx)
                if target is not None and target != user_id:
                    fail("ERR_NOT_RESOURCE_OWNER",
                         "The addressed resource does not belong to the acting creator.")

            return fn(ctx, **view_args)

        return wrapper

    return decorator
