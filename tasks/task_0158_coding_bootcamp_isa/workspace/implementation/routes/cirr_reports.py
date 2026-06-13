"""CIRRReport creation, read, publish (PRD §3.12)."""
from flask import Blueprint

import errors
from db import db, stamp_create, touch
from middleware import require_role
from response import success
from services import serialize
from services.common import get_json_body, lookup, require_fields, as_enum

bp = Blueprint("cirr_reports", __name__)

BASES = {"GRADUATES_ONLY", "ALL_ENROLLED"}


@bp.post("/cirr-reports")
def create_cirr_report():
    require_role("ComplianceOfficer")
    body = get_json_body()
    require_fields(body, ["cohort_id", "denominator_basis"])
    cohort_id = body["cohort_id"]
    if not isinstance(cohort_id, str):
        raise errors.invalid_request("cohort_id must be a string")
    lookup(db.cohorts, cohort_id)  # existence first
    basis = as_enum(body, "denominator_basis", BASES)

    c = {
        "cohort_id": cohort_id,
        "denominator_basis": basis,
        "status": "DRAFT",
    }
    stamp_create(c)
    db.cirr_reports[c["id"]] = c
    return success(serialize.cirr_report_view(c), status=201)


@bp.get("/cirr-reports/<cid>")
def get_cirr_report(cid):
    require_role("ComplianceOfficer")
    c = lookup(db.cirr_reports, cid)
    return success(serialize.cirr_report_view(c))


@bp.post("/cirr-reports/<cid>/publish")
def publish_cirr_report(cid):
    require_role("ComplianceOfficer")
    c = lookup(db.cirr_reports, cid)
    if c["status"] != "DRAFT":
        raise errors.invalid_state(f"CIRR report is {c['status']}, expected DRAFT")
    cohort = db.cohorts.get(c["cohort_id"])
    if cohort is None or cohort["status"] not in ("GRADUATED", "ARCHIVED"):
        raise errors.invalid_state("Cohort must be GRADUATED or ARCHIVED to publish")

    # freeze computed counts at publish time
    counts = serialize.compute_cirr_counts(c["cohort_id"], c["denominator_basis"])
    c["graduates_count"] = counts["graduates_count"]
    c["enrolled_count"] = counts["enrolled_count"]
    c["placed_count"] = counts["placed_count"]
    c["placement_rate"] = counts["placement_rate"]
    c["status"] = "PUBLISHED"
    touch(c)
    return success(serialize.cirr_report_view(c))
