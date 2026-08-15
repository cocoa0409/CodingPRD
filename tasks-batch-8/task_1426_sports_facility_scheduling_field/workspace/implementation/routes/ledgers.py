"""Usage ledger routes: list, read (PRD 3.1)."""

from flask import Blueprint, request

import util
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object
from services import core

bp = Blueprint("ledgers", __name__)


@bp.get("/usage-ledgers")
def list_ledgers():
    require_roles(*ANY_ROLE)
    items = list(store.usage_ledgers.values())
    for param in ("organization_id", "season_code"):
        val = request.args.get(param)
        if val is not None:
            items = [l for l in items if l.get(param) == val]
    return util.paginate(items)


@bp.get("/usage-ledgers/<lid>")
def get_ledger(lid):
    require_roles(*ANY_ROLE)
    return success_object(core.get_ledger(lid))
