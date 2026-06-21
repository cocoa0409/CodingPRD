"""WarrantyClaim endpoints: file, fetch, approve, deny."""
from flask import Blueprint, g

import clock
from db import db, stamp_create, touch
from errors import err
from middleware import require_roles
from response import created, ok
from services import serialize
from services.helpers import body, require_fields

bp = Blueprint("warranty_claims", __name__)


def _add_years(dt, years):
    """Return dt + the given whole years, handling Feb 29 by clamping to Feb 28."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> non-leap year: clamp to Feb 28.
        return dt.replace(year=dt.year + years, day=28)


@bp.post("/flooring/warranty-claims")
@require_roles("Customer", "Admin")
def file_claim():
    data = body()
    require_fields(data, ["job_id", "defect_description"])
    job_id = data["job_id"]
    defect_description = data["defect_description"]
    if not isinstance(defect_description, str):
        raise err("ERR_INVALID_REQUEST", "defect_description must be a string.")

    with db.lock:
        job = db.jobs.get(job_id)
        if job is None:
            raise err("ERR_NOT_FOUND", "Job not found.")

        # Ownership: a Customer filer must own the job. Admin is exempt from ownership.
        if g.user_role == "Customer" and g.user_id != job["customer_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "You do not own this job.")

        # Job must be COMPLETED.
        if job["status"] != "COMPLETED":
            raise err("ERR_JOB_NOT_COMPLETED", "Warranty claims may only be filed against COMPLETED jobs.")

        record = stamp_create(
            {
                "job_id": job_id,
                "filed_at": clock.iso(clock.now()),
                "defect_description": defect_description,
                "status": "FILED",
                "resolution_note": None,
            }
        )
        db.warranty_claims[record["id"]] = record
    return created(serialize.claim_view(record))


@bp.get("/flooring/warranty-claims/<wid>")
@require_roles("Admin", "SalesRep", "Customer")
def get_claim(wid):
    with db.lock:
        w = db.warranty_claims.get(wid)
        if w is None:
            raise err("ERR_NOT_FOUND", "Warranty claim not found.")
        return ok(serialize.claim_view(w))


@bp.post("/flooring/warranty-claims/<wid>/approve")
@require_roles("Admin")
def approve_claim(wid):
    data = body()
    require_fields(data, ["resolution_note"])
    resolution_note = data["resolution_note"]
    with db.lock:
        w = db.warranty_claims.get(wid)
        if w is None:
            raise err("ERR_NOT_FOUND", "Warranty claim not found.")
        if w["status"] != "FILED":
            raise err("ERR_INVALID_STATE", "Only a FILED claim can be approved.")

        job = db.jobs[w["job_id"]]
        product = db.products[job["product_id"]]

        # Warranty window: filed_at must be within completion + warranty_years.
        completed_at = clock.parse(job["_completed_at"])
        window_end = _add_years(completed_at, product["warranty_years"])
        filed_at = clock.parse(w["filed_at"])
        if filed_at >= window_end:
            raise err("ERR_WARRANTY_EXPIRED", "Claim filed after the warranty window closed.")

        # Risk gate: warranty_risk_score must be <= 70.
        if job["warranty_risk_score"] is not None and job["warranty_risk_score"] > 70:
            raise err("ERR_RISK_TOO_HIGH", "Job warranty risk is too high for auto-approval.")

        w["status"] = "APPROVED"
        w["resolution_note"] = resolution_note
        touch(w)
        return ok(serialize.claim_view(w))


@bp.post("/flooring/warranty-claims/<wid>/deny")
@require_roles("Admin")
def deny_claim(wid):
    data = body()
    require_fields(data, ["resolution_note"])
    resolution_note = data["resolution_note"]
    with db.lock:
        w = db.warranty_claims.get(wid)
        if w is None:
            raise err("ERR_NOT_FOUND", "Warranty claim not found.")
        if w["status"] != "FILED":
            raise err("ERR_INVALID_STATE", "Only a FILED claim can be denied.")
        w["status"] = "DENIED"
        w["resolution_note"] = resolution_note
        touch(w)
        return ok(serialize.claim_view(w))
