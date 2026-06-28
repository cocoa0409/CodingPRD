"""ID scans and age verification (PRD §3.2)."""
import app as A
import errors
import middleware
import response
import services
from app import app
from db import store


@app.route("/id-scans", methods=["POST"])
def create_id_scan():
    role, uid = middleware.require_roles({A.R_ASSOCIATE, A.R_CUSTOMER})
    body = A.get_body()
    customer_id = A.require_str(body, "customer_id")
    id_state = A.require_str(body, "id_state_code")
    expiry = A.require_field(body, "id_expiry_date")
    scanned_dob = A.require_field(body, "scanned_dob")

    customer = A.get_or_404(store.customers, customer_id)
    # Ownership: a Customer may only upload for themselves.
    if role == A.R_CUSTOMER and uid != customer_id:
        raise errors.forbidden()

    if not A.is_two_letter_state(id_state):
        raise errors.invalid_request("id_state_code must be two uppercase letters.")
    A.parse_iso(expiry if isinstance(expiry, str) else "")
    A.parse_iso(scanned_dob if isinstance(scanned_dob, str) else "")

    rec = {
        "customer_id": customer_id,
        "id_state_code": id_state,
        "id_expiry_date": expiry,
        "scanned_dob": scanned_dob,
        "status": "PENDING",
        "reject_reason": None,
    }
    # IdScan is append-only audit: id + created_at only (no version/updated_at).
    A.stamp_create(rec, with_version=False)
    store.id_scans[rec["id"]] = rec
    return response.object_response(A.public(rec), 201)


def _scan_ownership(role, uid, scan):
    if role == A.R_CUSTOMER and uid != scan["customer_id"]:
        raise errors.forbidden()


@app.route("/id-scans/<sid>", methods=["GET"])
def get_id_scan(sid):
    role, uid = middleware.require_roles(
        {A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN, A.R_CUSTOMER})
    rec = A.get_or_404(store.id_scans, sid)
    _scan_ownership(role, uid, rec)
    return response.object_response(A.public(rec))


@app.route("/customers/<cid>/id-scans", methods=["GET"])
def list_customer_id_scans(cid):
    role, uid = middleware.require_roles(
        {A.R_ASSOCIATE, A.R_COMPLIANCE, A.R_ADMIN, A.R_CUSTOMER})
    A.get_or_404(store.customers, cid)
    if role == A.R_CUSTOMER and uid != cid:
        raise errors.forbidden()
    limit, offset = A.get_pagination()
    items = [s for s in store.id_scans.values() if s["customer_id"] == cid]
    items = A.sort_created(items)
    page, total = A.paginate(items, limit, offset)
    return response.array_response(A.public_list(page), limit, offset, total)


@app.route("/id-scans/<sid>/verify", methods=["POST"])
def verify_id_scan(sid):
    middleware.require_roles({A.R_ASSOCIATE})
    scan = A.get_or_404(store.id_scans, sid)
    if scan["status"] != "PENDING":
        raise errors.invalid_state()
    customer = store.customers.get(scan["customer_id"])
    if customer is None:
        raise errors.not_found()

    now = store.clock
    expiry = A.parse_iso(scan["id_expiry_date"])
    scanned_dob = A.parse_iso(scan["scanned_dob"])
    cust_dob = A.parse_iso(customer["date_of_birth"])

    # Not expired: id_expiry_date on or after current clock.
    if expiry < now:
        raise errors.invalid_state("ID is expired.")
    # scanned_dob matches owning customer's recorded date_of_birth (same calendar date).
    if scanned_dob.date() != cust_dob.date():
        raise errors.invalid_state("Scanned DOB does not match customer record.")
    # Age >= 21 at current clock.
    if A.whole_years_between(scanned_dob, now) < 21:
        raise errors.invalid_state("Customer is underage.")

    scan["status"] = "VERIFIED"
    # IdScan content change on audit row (no version bump).
    customer["age_verified"] = True
    A.touch(customer)
    services.recompute_compliance_status(customer)
    return response.object_response(A.public(scan))


@app.route("/id-scans/<sid>/reject", methods=["POST"])
def reject_id_scan(sid):
    middleware.require_roles({A.R_ASSOCIATE})
    scan = A.get_or_404(store.id_scans, sid)
    if scan["status"] != "PENDING":
        raise errors.invalid_state()
    body = A.get_body()
    reason = A.require_str(body, "reject_reason")
    if reason not in A.REJECT_REASONS:
        raise errors.invalid_request("reject_reason must be one of EXPIRED, DOB_MISMATCH, UNDERAGE.")
    scan["status"] = "REJECTED"
    scan["reject_reason"] = reason
    customer = store.customers.get(scan["customer_id"])
    if customer is not None:
        services.recompute_compliance_status(customer)
    return response.object_response(A.public(scan))
