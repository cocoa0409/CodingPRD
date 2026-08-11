"""Warranty claim endpoints."""
from datetime import timedelta
from flask import Blueprint

from core import (
    db, ApiError, body, ok_object, paginate, new_record, touch, serialize,
    require_roles, get_case_or_404, get_child_or_404, require_case_active,
    req_str, req_enum, req_int, now, now_iso, iso,
)
from domain import mutate_case, make_claim_number, make_invoice_number, add_months

bp = Blueprint("claims", __name__)

SEVERITIES = ("LOW", "MEDIUM", "HIGH", "SAFETY_CRITICAL")
RESOLUTION_TYPES = ("REPAIR", "REPLACE", "REFUND", "DENIED")


def _get_claim(case_id, claim_id):
    case = get_case_or_404(case_id)
    claim = get_child_or_404("warranty_claims", claim_id, "case_id", case_id,
                             "ERR_CLAIM_NOT_FOUND", "Warranty claim")
    return case, claim


@bp.route("/cases/<caseId>/warranty-claims", methods=["POST"])
def create_claim(caseId):
    require_roles("Client", "ProjectManager")
    case = get_case_or_404(caseId)
    require_case_active(case)
    b = body()
    job_id = req_str(b, "installation_job_id")
    job = db["installation_jobs"].get(job_id)
    if job is None or job["case_id"] != caseId:
        raise ApiError("ERR_JOB_NOT_FOUND", 404,
                       "Installation job with given ID does not exist")
    issue = req_str(b, "issue_description")
    severity = req_enum(b, "severity", SEVERITIES)

    covered = False
    wstart = job.get("_warranty_start_dt")
    if wstart is not None:
        covered = now() <= add_months(wstart, job.get("warranty_months") or 12)

    rec = new_record()
    rec.update({
        "case_id": caseId,
        "installation_job_id": job_id,
        "claim_number": make_claim_number(),
        "status": "OPEN",
        "issue_description": issue,
        "severity": severity,
        "reported_date": now_iso(),
        "resolved_date": None,
        "resolution_type": None,
        "cost_cents": 0,
        "covered_by_warranty": covered,
    })
    db["warranty_claims"][rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/cases/<caseId>/warranty-claims", methods=["GET"])
def list_claims(caseId):
    require_roles()
    get_case_or_404(caseId)
    records = [c for c in db["warranty_claims"].values() if c["case_id"] == caseId]
    return paginate(records)


@bp.route("/cases/<caseId>/warranty-claims/<claimId>", methods=["GET"])
def get_claim(caseId, claimId):
    require_roles()
    _case, claim = _get_claim(caseId, claimId)
    return ok_object(serialize(claim))


@bp.route("/cases/<caseId>/warranty-claims/<claimId>/assign", methods=["POST"])
def assign_claim(caseId, claimId):
    require_roles("ProjectManager")
    case, claim = _get_claim(caseId, claimId)
    require_case_active(case)
    if claim["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Claim must be OPEN to assign")
    claim["status"] = "ASSIGNED"
    touch(claim)
    return ok_object(serialize(claim))


@bp.route("/cases/<caseId>/warranty-claims/<claimId>/start", methods=["POST"])
def start_claim(caseId, claimId):
    require_roles("CrewLead")
    case, claim = _get_claim(caseId, claimId)
    require_case_active(case)
    if claim["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Claim must be ASSIGNED to start work")
    claim["status"] = "IN_PROGRESS"
    touch(claim)
    return ok_object(serialize(claim))


@bp.route("/cases/<caseId>/warranty-claims/<claimId>/resolve", methods=["POST"])
def resolve_claim(caseId, claimId):
    require_roles("CrewLead")
    case, claim = _get_claim(caseId, claimId)
    require_case_active(case)
    if claim["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Claim must be IN_PROGRESS to resolve")
    b = body()
    resolution_type = req_enum(b, "resolution_type", RESOLUTION_TYPES)
    cost = req_int(b, "cost_cents")

    claim["status"] = "RESOLVED"
    claim["resolved_date"] = now_iso()
    claim["resolution_type"] = resolution_type
    claim["cost_cents"] = cost
    touch(claim)

    # Uncovered resolutions are billed to the client.
    if not claim.get("covered_by_warranty") and cost > 0:
        ts = now()
        inv = new_record()
        inv.update({
            "case_id": caseId,
            "invoice_number": make_invoice_number(),
            "invoice_type": "WARRANTY_WORK",
            "status": "DRAFT",
            "issue_date": None,
            "due_date": iso(ts + timedelta(days=30)),
            "paid_date": None,
            "subtotal_cents": cost,
            "tax_cents": 0,
            "total_cents": cost,
            "amount_paid_cents": 0,
            "balance_cents": cost,
            "funding_source_id": None,
            "quote_id": None,
            "rental_ramp_id": None,
            "_due_date_dt": ts + timedelta(days=30),
        })
        db["invoices"][inv["id"]] = inv
        line = new_record()
        line.update({
            "invoice_id": inv["id"],
            "description": f"Warranty claim {claim['claim_number']} resolution",
            "quantity": 1.0,
            "unit_price_cents": cost,
            "extended_price_cents": cost,
            "tax_cents": 0,
            "line_total_cents": cost,
            "period_start": None,
            "period_end": None,
        })
        db["invoice_line_items"][line["id"]] = line
        mutate_case(case)
    return ok_object(serialize(claim))


@bp.route("/cases/<caseId>/warranty-claims/<claimId>/deny", methods=["POST"])
def deny_claim(caseId, claimId):
    require_roles("ProjectManager")
    case, claim = _get_claim(caseId, claimId)
    require_case_active(case)
    if claim["status"] not in ("OPEN", "ASSIGNED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Claim must be OPEN or ASSIGNED to deny")
    claim["status"] = "DENIED"
    claim["resolution_type"] = "DENIED"
    touch(claim)
    return ok_object(serialize(claim))
