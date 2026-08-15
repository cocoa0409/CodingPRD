"""ProviderAlias endpoints (PRD §3.6)."""

from flask import Blueprint, request

from db import DB
from errors import not_found, invalid_state
from middleware import require_roles
from response import success_object, paginate
from services.common import touch

bp = Blueprint("aliases", __name__)


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


@bp.route("/pdm/providers/<pid>/aliases", methods=["GET"])
def list_aliases(pid):
    require_roles("DataSteward", "IntakeOperator")
    if pid not in DB.providers:
        raise not_found()
    items = [a for a in DB.provider_aliases.values() if a["provider_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate([_public(a) for a in items], request.args)


@bp.route("/pdm/provider-aliases/<aid>/unlink", methods=["POST"])
def unlink_alias(aid):
    require_roles("DataSteward")
    alias = DB.provider_aliases.get(aid)
    if alias is None:
        raise not_found()
    if alias["status"] != "ACTIVE":
        raise invalid_state()
    alias["status"] = "UNLINKED"
    touch(alias)
    return success_object(_public(alias))
