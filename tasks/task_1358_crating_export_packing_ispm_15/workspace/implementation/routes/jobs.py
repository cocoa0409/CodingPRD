"""PackingJob endpoints (PRD §3.1, §3.4, §3.8, §3.9)."""
from flask import Blueprint

from db import STORE, new_id, now_iso, logical_now, touch
from errors import (ApiError, ERR_JOB_INVALID_STATE, ERR_CUSTOMER_SUSPENDED,
                    ERR_CREDIT_LIMIT_EXCEEDED, ERR_NO_APPROVED_DESIGN,
                    ERR_PERMIT_REQUIRED, ERR_DOCS_NOT_RELEASED,
                    ERR_CONTAINER_INVALID_STATE, ERR_OPEN_CLAIMS,
                    ERR_STALE_VERSION, ERR_FORBIDDEN, not_found)
from middleware import (ALL_OPERATIONAL, require_roles, body, req_str, req_enum,
                        opt_enum, req_int, paginate, enum_filter, str_filter)
from response import success
from services.state import (get, ser_job, job_items, job_crates, job_cancel_cascade,
                            compute_quote, customer_open_exposure, job_permits,
                            job_claims)

bp = Blueprint("jobs", __name__)

MODES = {"SHOP", "ONSITE"}
INCOTERMS = {"EXW", "FOB", "DDP"}
JOB_STATUSES = {"QUOTED", "DESIGN", "PACKING", "READY_TO_LOAD", "LOADED",
                "SHIPPED", "DELIVERED", "CLOSED", "CANCELLED"}


def _get_job_or_404(jid):
    j = get("jobs", jid)
    if not j:
        raise not_found("PackingJob not found")
    return j


@bp.post("/crating/packing-jobs")
def create_job():
    require_roles(["SalesRep"])
    d = body()
    customer_id = req_str(d, "customer_id")
    mode = req_enum(d, "mode", MODES)
    incoterm = req_enum(d, "incoterm", INCOTERMS)
    cust = get("customers", customer_id)
    if not cust:
        raise not_found("Customer not found")
    if cust["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_SUSPENDED, "Customer is SUSPENDED", 409)
    rec = {
        "id": new_id(), "customer_id": customer_id, "mode": mode, "incoterm": incoterm,
        "status": "QUOTED", "quoted_price_cents": 0, "invoiced_total_cents": None,
        "delivered_at": None,
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
    }
    STORE["jobs"][rec["id"]] = rec
    return success(ser_job(rec), status=201)


@bp.get("/crating/packing-jobs/<jid>")
def get_job(jid):
    require_roles(ALL_OPERATIONAL)
    return success(ser_job(_get_job_or_404(jid)))


@bp.get("/crating/packing-jobs")
def list_jobs():
    require_roles(ALL_OPERATIONAL)
    customer_id = str_filter("customer_id")
    status = enum_filter("status", JOB_STATUSES)
    recs = [j for j in STORE["jobs"].values()
            if (customer_id is None or j["customer_id"] == customer_id)
            and (status is None or j["status"] == status)]
    recs.sort(key=lambda j: j["created_at"])
    page, meta = paginate(recs)
    return success([ser_job(j) for j in page], pagination=meta)


@bp.patch("/crating/packing-jobs/<jid>")
def patch_job(jid):
    require_roles(["SalesRep"])
    d = body()
    expected = req_int(d, "expected_packing_job_version")
    mode = opt_enum(d, "mode", MODES)
    incoterm = opt_enum(d, "incoterm", INCOTERMS)
    j = _get_job_or_404(jid)
    # OCC (PRD §2.7)
    if expected != j["version"]:
        raise ApiError(ERR_STALE_VERSION, "Stale PackingJob version", 412)
    if j["status"] != "QUOTED":
        raise ApiError(ERR_JOB_INVALID_STATE, "Job terms may only be revised while QUOTED", 409)
    if mode is not None:
        j["mode"] = mode
    if incoterm is not None:
        j["incoterm"] = incoterm
    touch(j)
    return success(ser_job(j))


@bp.get("/crating/packing-jobs/<jid>/quote")
def get_quote(jid):
    require_roles(ALL_OPERATIONAL)
    j = _get_job_or_404(jid)
    variant = "FINAL" if j["status"] == "CLOSED" else "PROVISIONAL"
    return success(compute_quote(j, variant))


@bp.post("/crating/packing-jobs/<jid>/accept-quote")
def accept_quote(jid):
    uid, _ = require_roles(["Customer"])
    j = _get_job_or_404(jid)
    if uid != j["customer_id"]:
        raise ApiError(ERR_FORBIDDEN, "Customers may only accept their own jobs", 403)
    if j["status"] != "QUOTED":
        raise ApiError(ERR_JOB_INVALID_STATE, "accept-quote requires status QUOTED", 409)
    cust = get("customers", j["customer_id"])
    if cust["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_SUSPENDED, "Customer is SUSPENDED", 409)
    quoted = compute_quote(j, "PROVISIONAL")["quoted_price_cents"]
    if customer_open_exposure(cust["id"]) + quoted > cust["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, "Credit limit would be exceeded", 422)
    j["quoted_price_cents"] = quoted  # frozen snapshot
    j["status"] = "DESIGN"
    touch(j)
    return success(ser_job(j))


@bp.post("/crating/packing-jobs/<jid>/start-packing")
def start_packing(jid):
    require_roles(["ShopForeman"])
    j = _get_job_or_404(jid)
    if j["status"] != "DESIGN":
        raise ApiError(ERR_JOB_INVALID_STATE, "start-packing requires status DESIGN", 409)
    items = job_items(jid)
    ok = bool(items)
    for it in items:
        d_ok = any(d["status"] in ("APPROVED", "LOCKED")
                   for d in STORE["designs"].values() if d["item_id"] == it["id"])
        if not d_ok:
            ok = False
            break
    if not ok:
        raise ApiError(ERR_NO_APPROVED_DESIGN,
                       "Every item must hold an APPROVED or LOCKED design", 409)
    if j["mode"] == "ONSITE":
        if not any(p["status"] == "CONFIRMED" for p in job_permits(jid)):
            raise ApiError(ERR_PERMIT_REQUIRED,
                           "ONSITE job requires a CONFIRMED on-site permit", 409)
    j["status"] = "PACKING"
    touch(j)
    return success(ser_job(j))


@bp.post("/crating/packing-jobs/<jid>/ship")
def ship_job(jid):
    require_roles(["LogisticsCoordinator"])
    j = _get_job_or_404(jid)
    if j["status"] != "LOADED":
        raise ApiError(ERR_JOB_INVALID_STATE, "ship requires status LOADED", 409)
    pl = next((p for p in STORE["packing_lists"].values() if p["packing_job_id"] == jid), None)
    ci = next((v for v in STORE["invoices"].values() if v["packing_job_id"] == jid), None)
    if not pl or pl["status"] != "RELEASED" or not ci or ci["status"] != "RELEASED":
        raise ApiError(ERR_DOCS_NOT_RELEASED, "Both documents must be RELEASED", 409)
    container_ids = {c["container_id"] for c in job_crates(jid) if c["container_id"]}
    for cid in container_ids:
        cont = get("containers", cid)
        if cont and cont["status"] != "GATED_OUT":
            raise ApiError(ERR_CONTAINER_INVALID_STATE,
                           "Every container holding this job's crates must be GATED_OUT", 409)
    for c in job_crates(jid):
        if c["status"] == "LOADED":
            c["status"] = "SHIPPED"
            touch(c)
    j["status"] = "SHIPPED"
    touch(j)
    return success(ser_job(j))


@bp.post("/crating/packing-jobs/<jid>/deliver")
def deliver_job(jid):
    require_roles(["LogisticsCoordinator"])
    j = _get_job_or_404(jid)
    if j["status"] != "SHIPPED":
        raise ApiError(ERR_JOB_INVALID_STATE, "deliver requires status SHIPPED", 409)
    for c in job_crates(jid):
        if c["status"] == "SHIPPED":
            c["status"] = "DELIVERED"
            touch(c)
    j["delivered_at"] = logical_now()
    j["status"] = "DELIVERED"
    touch(j)
    return success(ser_job(j))


@bp.post("/crating/packing-jobs/<jid>/close")
def close_job(jid):
    require_roles(["SalesRep"])
    j = _get_job_or_404(jid)
    if j["status"] != "DELIVERED":
        raise ApiError(ERR_JOB_INVALID_STATE, "close requires status DELIVERED", 409)
    if any(c["status"] in ("FILED", "UNDER_REVIEW", "APPROVED") for c in job_claims(jid)):
        raise ApiError(ERR_OPEN_CLAIMS, "Job has open damage claims", 409)
    j["invoiced_total_cents"] = compute_quote(j, "FINAL")["quoted_price_cents"]
    j["status"] = "CLOSED"
    touch(j)
    # permits still CONFIRMED ride the job's fate to CLOSED (PRD §3.6)
    for p in job_permits(jid):
        if p["status"] == "CONFIRMED":
            p["status"] = "CLOSED"
            touch(p)
    return success(ser_job(j))


@bp.post("/crating/packing-jobs/<jid>/cancel")
def cancel_job(jid):
    require_roles(["SalesRep"])
    j = _get_job_or_404(jid)
    if j["status"] not in ("QUOTED", "DESIGN"):
        raise ApiError(ERR_JOB_INVALID_STATE,
                       "cancel requires status QUOTED or DESIGN", 409)
    job_cancel_cascade(j)
    j["status"] = "CANCELLED"
    touch(j)
    return success(ser_job(j))
