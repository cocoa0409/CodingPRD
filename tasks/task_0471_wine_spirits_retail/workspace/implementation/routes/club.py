"""Club memberships (PRD §3.8)."""
import app as A
import errors
import middleware
import response
from app import app
from db import store


@app.route("/club-memberships", methods=["POST"])
def create_membership():
    role, uid = middleware.require_roles({A.R_CUSTOMER, A.R_ASSOCIATE})
    body = A.get_body()
    customer_id = A.require_str(body, "customer_id")
    customer = A.get_or_404(store.customers, customer_id)
    if role == A.R_CUSTOMER and uid != customer_id:
        raise errors.forbidden()

    # At most one ACTIVE/SUSPENDED membership per customer.
    for m in store.club_memberships.values():
        if m["customer_id"] == customer_id and m["status"] in ("ACTIVE", "SUSPENDED"):
            raise errors.duplicate_membership()

    rec = {
        "customer_id": customer_id,
        "tier": "BRONZE",
        "status": "ACTIVE",
        "accrued_points": 0,
    }
    A.stamp_create(rec)
    store.club_memberships[rec["id"]] = rec
    return response.object_response(A.public(rec), 201)


def _owner_check(role, uid, membership):
    if role == A.R_CUSTOMER and uid != membership["customer_id"]:
        raise errors.forbidden()


@app.route("/club-memberships/<mid>", methods=["GET"])
def get_membership(mid):
    role, uid = middleware.require_roles(
        {A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    rec = A.get_or_404(store.club_memberships, mid)
    _owner_check(role, uid, rec)
    return response.object_response(A.public(rec))


@app.route("/customers/<cid>/club-memberships", methods=["GET"])
def list_customer_memberships(cid):
    role, uid = middleware.require_roles(
        {A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    A.get_or_404(store.customers, cid)
    if role == A.R_CUSTOMER and uid != cid:
        raise errors.forbidden()
    limit, offset = A.get_pagination()
    items = [m for m in store.club_memberships.values() if m["customer_id"] == cid]
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(A.public_list(page), limit, offset, total)


@app.route("/club-memberships/<mid>/suspend", methods=["POST"])
def suspend_membership(mid):
    middleware.require_roles({A.R_COMPLIANCE})
    m = A.get_or_404(store.club_memberships, mid)
    if m["status"] != "ACTIVE":
        raise errors.invalid_state()
    m["status"] = "SUSPENDED"
    A.touch(m)
    return response.object_response(A.public(m))


@app.route("/club-memberships/<mid>/reinstate", methods=["POST"])
def reinstate_membership(mid):
    middleware.require_roles({A.R_COMPLIANCE})
    m = A.get_or_404(store.club_memberships, mid)
    if m["status"] != "SUSPENDED":
        raise errors.invalid_state()
    m["status"] = "ACTIVE"
    A.touch(m)
    return response.object_response(A.public(m))


@app.route("/club-memberships/<mid>/cancel", methods=["POST"])
def cancel_membership(mid):
    role, uid = middleware.require_roles({A.R_CUSTOMER})
    m = A.get_or_404(store.club_memberships, mid)
    _owner_check(role, uid, m)
    if m["status"] not in ("ACTIVE", "SUSPENDED"):
        raise errors.invalid_state()
    m["status"] = "CANCELLED"
    A.touch(m)
    return response.object_response(A.public(m))
