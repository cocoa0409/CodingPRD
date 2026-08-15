"""Insurance certificates (PRD 3.1)."""

from flask import Blueprint

import db
import response
from middleware import require_roles, check_owner_vessel
from validation import (
    get_body, req_str, req_int, req_date, parse_pagination, page,
)
from .vessels import get_vessel_or_404

bp = Blueprint("insurance", __name__)


@bp.post("/yard/insurance-certificates")
@require_roles("ServiceWriter")
def create_certificate():
    body = get_body()
    vessel_id = req_str(body, "vessel_id")
    vessel = get_vessel_or_404(vessel_id)
    provider = req_str(body, "provider")
    policy_no = req_str(body, "policy_no")
    coverage = req_int(body, "liability_coverage_cents", gt=0)
    effective = req_date(body, "effective_date")
    expiry = req_date(body, "expiry_date")

    now = db.now_iso()
    cert = {
        "id": db.new_id(),
        "vessel_id": vessel["id"],
        "provider": provider,
        "policy_no": policy_no,
        "liability_coverage_cents": coverage,
        "effective_date": effective.isoformat(),
        "expiry_date": expiry.isoformat(),
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "_effective": effective,
        "_expiry": expiry,
    }
    db.certificates[cert["id"]] = cert
    return response.success_object(db.pub(cert), status=201)


@bp.get("/yard/vessels/<vesselId>/insurance-certificates")
@require_roles("ServiceWriter", "YardManager", "Owner")
def list_certificates(vesselId):
    vessel = get_vessel_or_404(vesselId)
    check_owner_vessel(vessel)
    limit, offset = parse_pagination()
    items = [c for c in db.certificates.values() if c["vessel_id"] == vessel["id"]]
    items, total = page(items, limit, offset)
    return response.success_list(items, limit, offset, total)
