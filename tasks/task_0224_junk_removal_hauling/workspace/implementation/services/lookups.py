"""Existence lookups raising the scaffold's exact not-found errors, and ownership checks."""
import errors
from errors import err
from db import db


def get_job_or_404(job_id):
    job = db.haul_jobs.get(job_id)
    if job is None:
        err(errors.ERR_JOB_NOT_FOUND, "HaulJob not found")
    return job


def get_estimate_on_job_or_404(job, estimate_id):
    est = db.photo_estimates.get(estimate_id)
    if est is None or est["haul_job_id"] != job["id"]:
        err(errors.ERR_ESTIMATE_NOT_FOUND, "PhotoEstimate not found on this job")
    return est


def get_dispatch_or_404(dispatch_id):
    d = db.dispatches.get(dispatch_id)
    if d is None:
        err(errors.ERR_DISPATCH_NOT_FOUND, "Dispatch not found")
    return d


def get_invoice_or_404(invoice_id):
    inv = db.invoices.get(invoice_id)
    if inv is None:
        err(errors.ERR_INVOICE_NOT_FOUND, "Invoice not found")
    return inv


def get_crew_or_404(crew_id):
    c = db.crews.get(crew_id)
    if c is None:
        err(errors.ERR_CREW_NOT_FOUND, "Crew not found")
    return c


def get_truck_or_404(truck_id):
    t = db.trucks.get(truck_id)
    if t is None:
        err(errors.ERR_TRUCK_NOT_FOUND, "Truck not found")
    return t


def get_customer_or_404(customer_id):
    c = db.customers.get(customer_id)
    if c is None:
        err(errors.ERR_CUSTOMER_NOT_FOUND, "Customer not found")
    return c


def get_policy_or_404(policy_id):
    p = db.pricing_policies.get(policy_id)
    if p is None:
        err(errors.ERR_POLICY_NOT_FOUND, "PricingPolicy not found")
    return p


def active_policy():
    for p in db.pricing_policies.values():
        if p["status"] == "ACTIVE":
            return p
    return None


def require_customer_owns_job(auth, job):
    """Ownership check for Customer role acting on a job (PRD §2.1)."""
    if auth.role == "Customer" and job["customer_id"] != auth.user_id:
        err(errors.ERR_FORBIDDEN_ROLE, "Customer does not own this job")


def crew_id_for_job(job):
    """Crew assigned to the job via its non-terminal (RESERVED/ACTIVE) dispatch, if any."""
    for d in db.dispatches.values():
        if d["haul_job_id"] == job["id"] and d["dispatch_status"] in ("RESERVED", "ACTIVE"):
            return d["crew_id"]
    return None


def require_crewlead_owns_job(auth, job):
    """CrewLead ownership: X-User-ID must equal the crew_id assigned to the job (PRD §2.1)."""
    if auth.role == "CrewLead":
        cid = crew_id_for_job(job)
        if cid is None or cid != auth.user_id:
            err(errors.ERR_FORBIDDEN_ROLE, "CrewLead is not assigned to this job")
