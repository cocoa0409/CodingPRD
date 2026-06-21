"""UccFiling endpoints — PRD §3.7, §4.

Coverage window is half-open [filed, coverage_end). A new FILED window for the
same lease+jurisdiction is rejected (ERR_UCC_OVERLAP) if the lessor's current
clock falls inside an existing FILED filing's half-open window. LAPSED/TERMINATED
windows free the interval. Lapse is a derived projection of the logical clock
(see services/domain.effective_ucc_status).
"""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_roles, ALL_ROLES
from response import object_response, array_response
from services.common import (
    get_json_body, require_string, paginate, sort_by_created,
    parse_iso8601, to_iso, add_months,
)
from services import domain
from services import calculations as calc

bp = Blueprint("ucc", __name__)


@bp.post("/lessors/<lessor_id>/leases/<lease_id>/ucc-filings")
def create_ucc_filing(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ["FundingOfficer"])
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        domain.get_lease(lessor_id, lease_id)
        body = get_json_body()
        jurisdiction = require_string(body, "jurisdiction_state_code")
        now = parse_iso8601(lessor["clock_utc"])

        # Overlap check: existing filing (same lease+jurisdiction) whose effective
        # status is FILED and whose half-open window [filed, coverage_end)
        # contains now. LAPSED/TERMINATED windows do not occupy the interval.
        for f in db.ucc_filings.values():
            if (f["lease_id"] == lease_id
                    and f["jurisdiction_state_code"] == jurisdiction
                    and domain.effective_ucc_status(lessor, f) == "FILED"):
                filed = parse_iso8601(f["filed_clock_utc"])
                cov_end = parse_iso8601(f["coverage_end_clock_utc"])
                if filed <= now < cov_end:
                    raise errors.conflict(errors.ERR_UCC_OVERLAP,
                                          "overlapping active coverage window")
        # Jurisdiction must equal Lessor.home_state_code.
        if jurisdiction != lessor["home_state_code"]:
            raise errors.conflict(errors.ERR_UCC_WRONG_JURISDICTION,
                                  "jurisdiction does not match lessor home state")

        rec = db.init_record({
            "lessor_id": lessor_id,
            "lease_id": lease_id,
            "jurisdiction_state_code": jurisdiction,
            "filing_number": None,
            "filed_clock_utc": None,
            "coverage_end_clock_utc": None,
            "status": "PENDING",
        })
        db.ucc_filings[rec["id"]] = rec
        rec["status"] = "FILED"
        rec["filed_clock_utc"] = to_iso(now)
        rec["coverage_end_clock_utc"] = to_iso(add_months(now, calc.UCC_LAPSE_MONTHS))
        rec["filing_number"] = "UCC-" + rec["id"][:12].upper()
        db.touch(rec)
        return object_response(domain.serialize_ucc(rec, lessor), 201)


@bp.get("/lessors/<lessor_id>/ucc-filings/<ucc_id>")
def get_ucc_filing(lessor_id, ucc_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        rec = domain.get_ucc_filing(lessor_id, ucc_id)
        return object_response(domain.serialize_ucc(rec, lessor), 200)


@bp.get("/lessors/<lessor_id>/leases/<lease_id>/ucc-filings")
def list_ucc_filings(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        domain.get_lease(lessor_id, lease_id)
        items = [f for f in db.ucc_filings.values() if f["lease_id"] == lease_id]
        status = request.args.get("status")
        if status is not None and status != "":
            items = [f for f in items
                     if domain.effective_ucc_status(lessor, f) == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response(
            [domain.serialize_ucc(r, lessor) for r in page],
            limit, offset, total, 200,
        )


@bp.post("/lessors/<lessor_id>/ucc-filings/<ucc_id>/terminate")
def terminate_ucc_filing(lessor_id, ucc_id):
    user_id, role = get_user_context()
    require_roles(role, ["FundingOfficer"])
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        rec = domain.get_ucc_filing(lessor_id, ucc_id)
        # Only a FILED (effective) filing can be terminated.
        if domain.effective_ucc_status(lessor, rec) != "FILED":
            raise errors.invalid_state("Only a FILED filing can be terminated")
        rec["status"] = "TERMINATED"
        db.touch(rec)
        return object_response(domain.serialize_ucc(rec, lessor), 200)
