"""Customer registration and reads (PRD §3.2)."""
import app as A
import errors
import middleware
import response
import services
from app import app
from db import store


@app.route("/customers/register", methods=["POST"])
def register_customer():
    # Anonymous (or any authenticated role) may register; PRD: performed by Anonymous.
    role, _uid = middleware.get_principal()
    # Anonymous is the canonical caller; other roles are also permitted to create
    # customers in practice, but the PRD lists only Anonymous. Accept any known role.
    body = A.get_body()
    email = A.require_str(body, "email")
    full_name = A.require_str(body, "full_name")
    dob = A.require_field(body, "date_of_birth")
    ship_state = A.require_str(body, "ship_state_code")

    if not A.is_two_letter_state(ship_state):
        raise errors.invalid_request("ship_state_code must be two uppercase letters.")
    # date_of_birth must be parseable
    A.parse_iso(dob if isinstance(dob, str) else "")

    # email uniqueness
    for c in store.customers.values():
        if c["email"] == email:
            raise errors.invalid_request("email must be unique.")

    rec = {
        "email": email,
        "full_name": full_name,
        "date_of_birth": dob,
        "ship_state_code": ship_state,
        "age_verified": False,
        "compliance_status": "CLEAR",
        "lifetime_spend_cents": 0,
    }
    A.stamp_create(rec)
    store.customers[rec["id"]] = rec
    return response.object_response(A.public(rec), 201)


def _ownership_ok(role, uid, customer_id):
    if role == A.R_CUSTOMER and uid != customer_id:
        raise errors.forbidden()


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    role, uid = middleware.require_roles(
        {A.R_CUSTOMER, A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    rec = A.get_or_404(store.customers, cid)
    _ownership_ok(role, uid, cid)
    return response.object_response(services.customer_view(rec))


@app.route("/customers", methods=["GET"])
def list_customers():
    middleware.require_roles({A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN})
    limit, offset = A.get_pagination()
    items = list(store.customers.values())
    ship = A.request.args.get("ship_state_code")
    comp = A.request.args.get("compliance_status")
    if ship is not None:
        items = [c for c in items if c["ship_state_code"] == ship]
    if comp is not None:
        items = [c for c in items if services.compliance_status_value(c) == comp]
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(
        [services.customer_view(c) for c in page], limit, offset, total)
