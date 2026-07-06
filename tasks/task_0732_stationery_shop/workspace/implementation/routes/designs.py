"""Design endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import models
import response as resp
import util

bp = Blueprint("designs", __name__)


@bp.route("/designs", methods=["POST"])
def create_design():
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["Customer"])
    body = util.get_body()
    customer_id = util.get_str(body, "customer_id")
    event_package_id = util.get_str(body, "event_package_id")
    paper_stock_id = util.get_str(body, "paper_stock_id")
    finish_option_id = util.get_str(body, "finish_option_id")
    notes = util.get_str(body, "notes", required=False, allow_empty=True) or ""

    # AuthZ: customer_id must equal acting user id
    middleware.require_owner(user_id, customer_id)
    # Existence checks (customer, event package, paper, finish) — 404 family
    models.get_customer(customer_id)
    models.get_event_package(event_package_id)
    ps = models.get_paper_stock(paper_stock_id)
    fo = models.get_finish_option(finish_option_id)

    # State: catalog integrity — paper/finish must be ACTIVE
    if ps["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_PAPER_DISCONTINUED, "paper stock is discontinued")
    if fo["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_FINISH_DISCONTINUED, "finish option is discontinued")

    d = models.make_common({
        "customer_id": customer_id,
        "designer_id": None,
        "event_package_id": event_package_id,
        "paper_stock_id": paper_stock_id,
        "finish_option_id": finish_option_id,
        "notes": notes,
        "status": "DRAFT",
    })
    db.designs[d["id"]] = d
    return resp.created(d)


@bp.route("/designs/<did>", methods=["GET"])
def get_design(did):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer", "Designer"])
    d = models.get_design(did)
    if role == "Customer":
        middleware.require_owner(user_id, d["customer_id"])
    if role == "Designer":
        # designer may see designs where they are the assigned designer OR unassigned
        if d.get("designer_id") is not None and d["designer_id"] != user_id:
            errors.raise_error(errors.ERR_UNAUTHORIZED, "designer does not own this design")
    return resp.ok(d)


@bp.route("/designs/<did>", methods=["PATCH"])
def patch_design(did):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["Customer"])
    d = models.get_design(did)
    middleware.require_owner(user_id, d["customer_id"])
    if d["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE, "design is not in DRAFT state")
    body = util.get_body()
    changed = False
    if "paper_stock_id" in body and body["paper_stock_id"] is not None:
        pid = util.get_str(body, "paper_stock_id")
        ps = models.get_paper_stock(pid)
        if ps["status"] != "ACTIVE":
            errors.raise_error(errors.ERR_PAPER_DISCONTINUED, "paper stock is discontinued")
        d["paper_stock_id"] = pid
        changed = True
    if "finish_option_id" in body and body["finish_option_id"] is not None:
        fid = util.get_str(body, "finish_option_id")
        fo = models.get_finish_option(fid)
        if fo["status"] != "ACTIVE":
            errors.raise_error(errors.ERR_FINISH_DISCONTINUED, "finish option is discontinued")
        d["finish_option_id"] = fid
        changed = True
    if "notes" in body:
        n = body["notes"]
        if n is not None and not isinstance(n, str):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "notes must be a string")
        d["notes"] = n if n is not None else ""
        changed = True
    if changed:
        models.bump(d)
    return resp.ok(d)


@bp.route("/designs", methods=["GET"])
def list_designs():
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer", "Designer"])
    limit, offset = util.get_pagination()

    def match(d):
        cid = request.args.get("customer_id")
        did = request.args.get("designer_id")
        eid = request.args.get("event_package_id")
        pid = request.args.get("paper_stock_id")
        fid = request.args.get("finish_option_id")
        st = request.args.get("status")
        if cid and d.get("customer_id") != cid:
            return False
        if did and d.get("designer_id") != did:
            return False
        if eid and d.get("event_package_id") != eid:
            return False
        if pid and d.get("paper_stock_id") != pid:
            return False
        if fid and d.get("finish_option_id") != fid:
            return False
        if st and d.get("status") != st:
            return False
        return True

    items = [d for d in db.designs.values() if match(d)]
    if role == "Customer":
        items = [d for d in items if d["customer_id"] == user_id]
    elif role == "Designer":
        items = [d for d in items if d.get("designer_id") in (None, user_id)]
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)
