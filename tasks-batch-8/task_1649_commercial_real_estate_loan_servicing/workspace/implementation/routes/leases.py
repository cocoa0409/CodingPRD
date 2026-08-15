from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success
from services.common import parse_dt, stamp_new, touch
from services.pagination import get_pagination, paginate
from services.serialize import estoppel as ser_estoppel, lease as ser_lease
from services.validate import (
    body_json, opt_int, require_fields, req_enum, req_int, req_str,
)

bp = Blueprint("leases", __name__)


def _approval_flags(rent, sqft, term):
    return rent > 500000 or sqft > 5000 or term > 60


def _load_lease(lid):
    lease = db.leases.get(lid)
    if lease is None:
        raise errors.not_found("Lease not found")
    return lease


def _estoppel_gate_satisfied(lease):
    clock = db.get_clock()
    for e in db.estoppels.values():
        if e["lease_id"] != lease["id"]:
            continue
        if e["status"] == "EXECUTED" and e.get("expires_at_dt") and e["expires_at_dt"] > clock:
            return True
    return False


@bp.post("/properties/<pid>/leases")
def create_lease(pid):
    actor = mw.authenticate()
    mw.authorize(actor, ["Borrower"])
    prop = db.properties.get(pid)
    if prop is None:
        raise errors.not_found("Property not found")
    mw.require_borrower_ownership(actor, "property", prop)
    data = body_json()
    require_fields(data, [
        "tenant_name", "suite_ref", "commencement_date", "expiry_date",
        "base_rent_cents_monthly", "sqft", "term_months",
    ])
    tenant = req_str(data, "tenant_name")
    suite = req_str(data, "suite_ref")
    start = parse_dt(data.get("commencement_date"), "commencement_date")
    end = parse_dt(data.get("expiry_date"), "expiry_date")
    if end < start:
        raise errors.invalid_request("expiry_date must not precede commencement_date")
    rent = req_int(data, "base_rent_cents_monthly", gt=0)
    sqft = req_int(data, "sqft", gt=0)
    term = req_int(data, "term_months", gt=0)
    flag = _approval_flags(rent, sqft, term)
    lease = {
        "id": db.new_id(),
        "property_id": pid,
        "tenant_name": tenant,
        "suite_ref": suite,
        "commencement_date": db.fmt_ts(start),
        "commencement_date_dt": start,
        "expiry_date": db.fmt_ts(end),
        "expiry_date_dt": end,
        "base_rent_cents_monthly": rent,
        "sqft": sqft,
        "term_months": term,
        "status": "DRAFT",
        "lender_approval_required": flag,
        "estoppel_required": flag,
        "conditions": None,
    }
    stamp_new(lease)
    db.leases[lease["id"]] = lease
    return success(ser_lease(lease), status=201)


@bp.get("/properties/<pid>/leases")
def list_leases(pid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    prop = db.properties.get(pid)
    if not mw.read_scope_allows(actor, "property", prop):
        raise errors.not_found("Property not found")
    limit, offset = get_pagination()
    items = [l for l in db.leases.values() if l["property_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    page, pg = paginate([ser_lease(l) for l in items], limit, offset)
    return success(page, pagination=pg, is_array=True)


@bp.get("/leases/<lid>")
def get_lease(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    lease = db.leases.get(lid)
    if not mw.read_scope_allows(actor, "lease", lease):
        raise errors.not_found("Lease not found")
    return success(ser_lease(lease))


@bp.post("/leases/<lid>/submit")
def submit_lease(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["Borrower"])
    lease = _load_lease(lid)
    mw.require_borrower_ownership(actor, "lease", lease)
    if lease["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT lease can be submitted")
    # Closed-interval suite overlap among live leases on same property+suite.
    for other in db.leases.values():
        if other["id"] == lease["id"]:
            continue
        if other["property_id"] != lease["property_id"]:
            continue
        if other["suite_ref"] != lease["suite_ref"]:
            continue
        if other["status"] not in ("SUBMITTED", "APPROVED", "CONDITIONALLY_APPROVED"):
            continue
        if lease["commencement_date_dt"] <= other["expiry_date_dt"] and \
           other["commencement_date_dt"] <= lease["expiry_date_dt"]:
            raise errors.ApiError(
                errors.ERR_LEASE_SUITE_OVERLAP,
                "Suite occupancy overlaps a live lease", 409)
    lease["status"] = "SUBMITTED"
    touch(lease)
    return success(ser_lease(lease))


@bp.post("/leases/<lid>/decide")
def decide_lease(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer"])
    lease = _load_lease(lid)
    data = body_json()
    require_fields(data, ["decision"])
    decision = req_enum(data, "decision", ("APPROVE", "CONDITIONAL", "REJECT"))
    conditions = data.get("conditions")
    if decision == "CONDITIONAL":
        if not isinstance(conditions, str) or not conditions:
            raise errors.invalid_request("conditions text is required for a CONDITIONAL decision")
    if decision == "APPROVE":
        if lease["status"] not in ("SUBMITTED", "CONDITIONALLY_APPROVED"):
            raise errors.invalid_state("Approval requires SUBMITTED or CONDITIONALLY_APPROVED")
        if lease["estoppel_required"] and not _estoppel_gate_satisfied(lease):
            raise errors.ApiError(
                errors.ERR_ESTOPPEL_REQUIRED,
                "An EXECUTED unexpired estoppel is required", 409)
        lease["status"] = "APPROVED"
    elif decision == "CONDITIONAL":
        if lease["status"] != "SUBMITTED":
            raise errors.invalid_state("Conditional approval requires SUBMITTED")
        lease["status"] = "CONDITIONALLY_APPROVED"
        lease["conditions"] = conditions
    else:  # REJECT
        if lease["status"] not in ("SUBMITTED", "CONDITIONALLY_APPROVED"):
            raise errors.invalid_state("Rejection requires SUBMITTED or CONDITIONALLY_APPROVED")
        lease["status"] = "REJECTED"
    touch(lease)
    return success(ser_lease(lease))


@bp.post("/leases/<lid>/revise")
def revise_lease(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["Borrower"])
    lease = _load_lease(lid)
    mw.require_borrower_ownership(actor, "lease", lease)
    data = body_json()
    if lease["status"] != "REJECTED":
        raise errors.invalid_state("Only a REJECTED lease can be revised")
    rent = opt_int(data, "base_rent_cents_monthly", default=lease["base_rent_cents_monthly"], gt=0)
    sqft = opt_int(data, "sqft", default=lease["sqft"], gt=0)
    term = opt_int(data, "term_months", default=lease["term_months"], gt=0)
    start = lease["commencement_date_dt"]
    end = lease["expiry_date_dt"]
    if data.get("commencement_date") is not None:
        start = parse_dt(data.get("commencement_date"), "commencement_date")
    if data.get("expiry_date") is not None:
        end = parse_dt(data.get("expiry_date"), "expiry_date")
    if end < start:
        raise errors.invalid_request("expiry_date must not precede commencement_date")
    lease["base_rent_cents_monthly"] = rent
    lease["sqft"] = sqft
    lease["term_months"] = term
    lease["commencement_date_dt"] = start
    lease["commencement_date"] = db.fmt_ts(start)
    lease["expiry_date_dt"] = end
    lease["expiry_date"] = db.fmt_ts(end)
    flag = _approval_flags(rent, sqft, term)
    lease["lender_approval_required"] = flag
    lease["estoppel_required"] = flag
    lease["conditions"] = None
    lease["status"] = "DRAFT"
    touch(lease)
    return success(ser_lease(lease))


@bp.post("/leases/<lid>/estoppels")
def create_estoppel(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer"])
    lease = _load_lease(lid)
    data = body_json()
    require_fields(data, ["due_date"])
    due = parse_dt(data.get("due_date"), "due_date")
    clock = db.get_clock()
    for e in db.estoppels.values():
        if e["lease_id"] != lid:
            continue
        if e["status"] == "PENDING" and e["due_date_dt"] >= clock:
            raise errors.ApiError(
                errors.ERR_DUPLICATE_ACTIVE_ESTOPPEL,
                "An unexpired PENDING estoppel already exists for this lease", 409)
        if e["status"] == "EXECUTED" and e.get("expires_at_dt") and e["expires_at_dt"] > clock:
            raise errors.ApiError(
                errors.ERR_DUPLICATE_ACTIVE_ESTOPPEL,
                "An unexpired EXECUTED estoppel already exists for this lease", 409)
    e = {
        "id": db.new_id(),
        "lease_id": lid,
        "status": "PENDING",
        "due_date": db.fmt_ts(due),
        "due_date_dt": due,
        "executed_at": None,
        "executed_at_dt": None,
        "expires_at": None,
        "expires_at_dt": None,
    }
    stamp_new(e)
    db.estoppels[e["id"]] = e
    return success(ser_estoppel(e), status=201)


@bp.get("/leases/<lid>/estoppels")
def list_estoppels(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    lease = db.leases.get(lid)
    if not mw.read_scope_allows(actor, "lease", lease):
        raise errors.not_found("Lease not found")
    limit, offset = get_pagination()
    items = [e for e in db.estoppels.values() if e["lease_id"] == lid]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, pg = paginate([ser_estoppel(e) for e in items], limit, offset)
    return success(page, pagination=pg, is_array=True)


@bp.post("/estoppels/<eid>/execute")
def execute_estoppel(eid):
    from datetime import timedelta
    actor = mw.authenticate()
    mw.authorize(actor, ["Borrower"])
    e = db.estoppels.get(eid)
    if e is None:
        raise errors.not_found("EstoppelCertificate not found")
    mw.require_borrower_ownership(actor, "estoppel", e)
    if e["status"] != "PENDING":
        raise errors.invalid_state("Only a PENDING estoppel can be executed")
    now = db.get_clock()
    e["status"] = "EXECUTED"
    e["executed_at_dt"] = now
    e["executed_at"] = db.fmt_ts(now)
    e["expires_at_dt"] = now + timedelta(days=90)
    e["expires_at"] = db.fmt_ts(e["expires_at_dt"])
    touch(e)
    return success(ser_estoppel(e))
