"""InsuranceCertificate endpoints."""
from flask import Blueprint

import db
from auth import ALL_ROLES, require_ownership, require_roles
from envelope import success_list, success_obj
from errors import ApiError, ERR_INSUFFICIENT_COVERAGE
from routes.leases import get_lease_or_404
from services.core import MIN_LIABILITY_COVERAGE_CENTS
from timeutil import iso_z
from validators import body, paginate, pagination, req_dt, req_int, req_str

bp = Blueprint("insurance", __name__)


@bp.post("/leases/<lid>/insurance-certificates")
def create_certificate(lid):
    uid, _role = require_roles("Tenant")
    lease = get_lease_or_404(lid)
    require_ownership(lease["id"], uid)
    data = body()
    insurer_name = req_str(data, "insurer_name")
    policy_number = req_str(data, "policy_number")
    coverage = req_int(data, "liability_coverage_cents")
    effective_from = req_dt(data, "effective_from")
    effective_to = req_dt(data, "effective_to")
    now = db.clock_now()
    # A certificate is recorded VALID only when coverage and dates pass
    # insurance_compliance_check at submission.
    if coverage < MIN_LIABILITY_COVERAGE_CENTS or not (effective_from <= now < effective_to):
        raise ApiError(
            ERR_INSUFFICIENT_COVERAGE,
            "Certificate fails the compliance check (coverage minimum or coverage window)",
            422,
        )
    cert = db.new_entity({
        "lease_id": lease["id"],
        "insurer_name": insurer_name,
        "policy_number": policy_number,
        "liability_coverage_cents": coverage,
        "effective_from": iso_z(effective_from),
        "effective_to": iso_z(effective_to),
        "status": "VALID",
    })
    db.certificates[cert["id"]] = cert
    return success_obj(db.public(cert), 201)


@bp.get("/leases/<lid>/insurance-certificates")
def list_certificates(lid):
    require_roles(*ALL_ROLES)
    lease = get_lease_or_404(lid)
    items = [c for c in db.certificates.values() if c["lease_id"] == lease["id"]]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([db.public(c) for c in page], limit, offset, total)
