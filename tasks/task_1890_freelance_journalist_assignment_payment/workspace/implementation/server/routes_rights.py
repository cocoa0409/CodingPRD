"""Rights purchase endpoints."""

from flask import request

from . import calc
from .auth import require, require_owner
from .blueprint import bp
from .envelope import ok_list, ok_obj
from .errors import ApiError, not_found
from .serialize import ser_rights_purchase
from .store import STORE, touch
from .util import paged, pagination_params, sort_created

READ_ROLES = ["DeskAdmin", "Editor", "FinanceUser", "Contributor"]


@bp.get("/freelance-desk/assignments/<aid>/rights-purchases")
def list_rights_purchases(aid):
    uid, role = require(READ_ROLES)
    a = STORE.assignments.get(aid)
    if a is None:
        not_found("Assignment")
    if role == "Contributor":
        require_owner(uid, a["contributor_id"])
    items = [r for r in STORE.rights_purchases.values() if r["assignment_id"] == aid]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_rights_purchase(r) for r in page], limit, offset, total)


@bp.get("/freelance-desk/rights-purchases/<rid>")
def get_rights_purchase(rid):
    uid, role = require(READ_ROLES)
    r = STORE.rights_purchases.get(rid)
    if r is None:
        not_found("RightsPurchase")
    if role == "Contributor":
        a = STORE.assignments.get(r["assignment_id"])
        require_owner(uid, a["contributor_id"] if a else None)
    return ok_obj(ser_rights_purchase(r))


@bp.post("/freelance-desk/rights-purchases/<rid>/record-reuse")
def record_reuse(rid):
    require(["Editor"])
    r = STORE.rights_purchases.get(rid)
    if r is None:
        not_found("RightsPurchase")
    a = STORE.assignments.get(r["assignment_id"])
    # Priority 17: reuse allowed only for ACTIVE ONE_TIME rights on an
    # ACCEPTED_FOR_PUBLICATION assignment.
    if (
        r["status"] != "ACTIVE"
        or r["rights_kind"] != "ONE_TIME"
        or a is None
        or a["editorial_status"] != "ACCEPTED_FOR_PUBLICATION"
    ):
        raise ApiError(
            "ERR_RIGHTS_NOT_REUSABLE",
            409,
            "Reuse requires ONE_TIME ACTIVE rights on an ACCEPTED_FOR_PUBLICATION assignment",
        )
    royalty = calc.reuse_royalty(a["final_fee_cents"])
    r["reuse_count"] += 1
    r["reuse_fee_cents_total"] += royalty
    touch(r)
    calc.post_ledger(None, a["contributor_id"], "REUSE_ROYALTY_CREDIT", royalty)
    contributor = STORE.contributors.get(a["contributor_id"])
    if contributor is not None:
        calc.sync_ytd(contributor)
    return ok_obj(ser_rights_purchase(r))
