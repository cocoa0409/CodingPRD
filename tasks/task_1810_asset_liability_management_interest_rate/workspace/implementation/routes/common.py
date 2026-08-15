"""Shared request pipeline: rung-1 auth headers, rung-2 role authorization,
then the handler executes rungs 3+ (path existence, body shape, OCC, state,
business rules) in the PRD 2.9 priority order.
"""

from flask import Blueprint, request

from errors import ApiError
from validate import authenticate, get_body

bp = Blueprint("api", __name__)

READ_ROLES = ["TreasuryAnalyst", "ModelRiskValidator", "ALCOChair", "Regulator"]


class Ctx(object):
    def __init__(self, user_id, role, body, args, path):
        self.user_id = user_id
        self.role = role
        self.body = body
        self.args = args
        self.path = path

    def param(self, name):
        return self.path[name]


def endpoint(method, rule, roles):
    """Register a handler behind rungs 1-2 of the validation ladder."""
    def deco(fn):
        def view(**path_params):
            user_id, role = authenticate()          # rung 1
            if role not in roles:                   # rung 2
                raise ApiError("ERR_FORBIDDEN_FOR_ROLE")
            body = get_body() if method in ("POST", "PATCH", "PUT", "DELETE") else {}
            ctx = Ctx(user_id, role, body, request.args, path_params)
            return fn(ctx)

        view.__name__ = fn.__name__
        bp.add_url_rule(rule, fn.__name__, view, methods=[method])
        return fn

    return deco


def get_or_404(table, record_id):
    """Rung 3: path existence."""
    record = table.get(record_id)
    if record is None:
        raise ApiError("ERR_NOT_FOUND")
    return record
