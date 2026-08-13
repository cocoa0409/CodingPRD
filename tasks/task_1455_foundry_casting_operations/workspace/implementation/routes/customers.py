"""Customer registration and reads (PRD 3.1)."""

from flask import request

from db import all_of, get, new_record
from errors import fail
from middleware import auth, paged, require_role
from response import ok_list, ok_object
from util import as_int, as_str, body_dict, req


def register(app):
    @app.route("/api/customers", methods=["POST"])
    def create_customer():
        auth_user, role = auth()
        require_role(role, {"FoundryAdmin"})
        body = body_dict(request.get_json(silent=True))
        foundry_id = as_str(req(body, "foundry_id"), "foundry_id")
        company_name = as_str(req(body, "company_name"), "company_name")
        credit = as_int(req(body, "credit_limit_cents"), "credit_limit_cents")
        if credit < 0:
            fail("ERR_INVALID_REQUEST", "credit_limit_cents must not be negative")
        if get("foundries", foundry_id) is None:
            fail("ERR_NOT_FOUND", "foundry not found")
        rec = new_record("customers", {
            "foundry_id": foundry_id,
            "company_name": company_name,
            "credit_limit_cents": credit,
        })
        return ok_object(rec, 201)

    @app.route("/api/customers/<cid>", methods=["GET"])
    def get_customer(cid):
        auth_user, role = auth()
        require_role(role, {"FoundryAdmin", "WarrantyManager", "Customer"})
        rec = get("customers", cid)
        if rec is None:
            fail("ERR_NOT_FOUND", "customer not found")
        if role == "Customer" and auth_user != rec["id"]:
            fail("ERR_FORBIDDEN_OWNER", "customer may only read its own record")
        return ok_object(rec, 200)

    @app.route("/api/customers", methods=["GET"])
    def list_customers():
        auth_user, role = auth()
        require_role(role, {"FoundryAdmin", "WarrantyManager"})
        foundry_id = request.args.get("foundry_id")
        recs = list(all_of("customers"))
        if foundry_id is not None:
            recs = [c for c in recs if c["foundry_id"] == foundry_id]
        page, limit, offset, total = paged(recs)
        return ok_list(page, limit, offset, total)
