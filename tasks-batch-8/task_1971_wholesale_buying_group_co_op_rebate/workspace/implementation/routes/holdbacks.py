"""HoldbackRelease read endpoints (PRD §3.7)."""

from flask import Blueprint, request

from db import store, public
from errors import err_not_found
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate

bp = Blueprint("holdbacks", __name__)

READ_ROLES = ("CoopAdmin", "FinanceOfficer", "MemberRep")


def get_release_or_404(release_id):
    release = store.holdbacks.get(release_id)
    if release is None:
        raise err_not_found("HoldbackRelease not found")
    return release


def _arg(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.route("/coop/holdback-releases/<release_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_release(uid, role, release_id):
    return success_object(public(get_release_or_404(release_id)), code=200)


@bp.route("/coop/holdback-releases", methods=["GET"])
@require_roles(*READ_ROLES)
def list_releases(uid, role):
    limit, offset = parse_pagination()
    items = list(store.holdbacks.values())
    member_id = _arg("member_id")
    if member_id is not None:
        items = [h for h in items if h["member_id"] == member_id]
    status = _arg("status")
    if status is not None:
        items = [h for h in items if h["status"] == status]
    source = _arg("source_distribution_id")
    if source is not None:
        items = [h for h in items if h["source_distribution_id"] == source]
    page, total = paginate(items, limit, offset)
    return success_list([public(h) for h in page], limit, offset, total)
