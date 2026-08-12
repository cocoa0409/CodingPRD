"""Certificates and warranty claims (PRD §3.8, §3.9)."""
from flask import Blueprint, request

from db import stores, clock_date, parse_date
from errors import fail
from response import ok
from serializers import ser_certificate, ser_warranty_claim
from services import (
    CLAIM_TERMINAL, warranty_coverage, award_for, touch,
)
from validation import auth, require_role, get_body, v_str, v_int, v_num, v_enum
from routes.common import (
    project_or_404, get_or_404, require_contractor_owner,
    require_homeowner_owner, new_entity, list_response,
)

bp = Blueprint("warranty", __name__)

DECIDE_OUTCOMES = {"APPROVED", "DENIED"}


@bp.get("/api/projects/<project_id>/certificates")
def list_certificates(project_id):
    auth()
    project_or_404(project_id)
    items = [c for c in stores["certificates"].values() if c["project_id"] == project_id]
    return list_response(items, ser_certificate)


@bp.get("/api/certificates/<cert_id>")
def get_certificate(cert_id):
    auth()
    return ok(ser_certificate(get_or_404("certificates", cert_id, "Certificate")))


@bp.get("/api/certificates/<cert_id>/warranty-claims")
def list_certificate_claims(cert_id):
    auth()
    get_or_404("certificates", cert_id, "Certificate")
    items = [c for c in stores["warranty_claims"].values() if c["certificate_id"] == cert_id]
    return list_response(items, ser_warranty_claim)


@bp.post("/api/projects/<project_id>/warranty-claims")
def create_claim(project_id):
    role, uid = auth()
    require_role(role, "Homeowner")
    project = project_or_404(project_id)
    require_homeowner_owner(project, uid)
    body = get_body()
    # Priority 5: certificate_id must resolve to this project's certificate.
    raw_cert = body.get("certificate_id")
    cert = None
    if isinstance(raw_cert, str):
        cert = stores["certificates"].get(raw_cert)
        if cert is None or cert["project_id"] != project_id:
            fail("ERR_REFERENCED_NOT_FOUND", "certificate_id does not reference an existing certificate of this project")
    # Priority 7: claims open only once the project is COMPLETED.
    if project["status"] != "COMPLETED":
        fail("ERR_PROJECT_STATE_FORBIDS", "Warranty claims open only once the project is COMPLETED")
    # Priority 21: inside the certificate's active warranty window.
    if cert is not None:
        today = clock_date()
        if cert["status"] != "ACTIVE" or today > cert["_warranty_end_date"]:
            fail("ERR_WARRANTY_EXPIRED", "Claim is outside the certificate's active warranty window")
    # Priority 25: claimed_cents must be greater than zero.
    raw_claimed = body.get("claimed_cents")
    if isinstance(raw_claimed, int) and not isinstance(raw_claimed, bool) and raw_claimed <= 0:
        fail("ERR_INVALID_CLAIM_AMOUNT", "claimed_cents must be greater than zero")
    # Priority 26: shape.
    certificate_id = v_str(body, "certificate_id")
    description = v_str(body, "description")
    claimed_cents = v_int(body, "claimed_cents")
    fresh_slab = v_num(body, "fresh_slab_moisture_lbs")
    fresh_rh = v_num(body, "fresh_interior_rh_pct")
    # coverage_pct preview (and recurrence flag) computed at filing.
    recurrence, coverage = warranty_coverage(project, cert, clock_date(), fresh_slab)
    e = new_entity({
        "project_id": project_id,
        "certificate_id": certificate_id,
        "description": description,
        "claimed_cents": claimed_cents,
        "fresh_slab_moisture_lbs": fresh_slab,
        "fresh_interior_rh_pct": fresh_rh,
        "moisture_recurrence_confirmed": recurrence,
        "coverage_pct": coverage,
        "awarded_cents": None,
        "status": "UNDER_REVIEW",
    })
    stores["warranty_claims"][e["id"]] = e
    return ok(ser_warranty_claim(e), 201)


@bp.get("/api/projects/<project_id>/warranty-claims")
def list_claims(project_id):
    auth()
    project_or_404(project_id)
    items = [c for c in stores["warranty_claims"].values() if c["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, ser_warranty_claim)


@bp.post("/api/warranty-claims/<claim_id>/decide")
def decide_claim(claim_id):
    role, uid = auth()
    require_role(role, "Contractor")
    claim = get_or_404("warranty_claims", claim_id, "WarrantyClaim")
    project = project_or_404(claim["project_id"])
    require_contractor_owner(project, uid)
    if claim["status"] in CLAIM_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "Claim is terminal and refuses further mutation")
    if claim["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW claim can be decided")
    body = get_body()
    outcome = v_enum(body, "outcome", DECIDE_OUTCOMES)
    v_str(body, "notes", required=False)
    if outcome == "APPROVED":
        cert = stores["certificates"].get(claim["certificate_id"])
        claim_date = parse_date(claim["created_at"][:10])
        recurrence, coverage = warranty_coverage(
            project, cert, claim_date, claim["fresh_slab_moisture_lbs"]
        )
        claim["moisture_recurrence_confirmed"] = recurrence
        claim["coverage_pct"] = coverage
        claim["awarded_cents"] = award_for(claim["claimed_cents"], coverage)
        claim["status"] = "APPROVED"
    else:
        claim["awarded_cents"] = 0
        claim["status"] = "DENIED"
    touch(claim)
    return ok(ser_warranty_claim(claim))
