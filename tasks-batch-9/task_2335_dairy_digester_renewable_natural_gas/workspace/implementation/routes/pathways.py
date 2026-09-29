from flask import Blueprint

from db import db
from errors import fail
from middleware import endpoint, body
from response import created, ok
from routes.common import get_facility, get_pathway, paged_list, resolve_refs
from services import derive
from validation import require_range

bp = Blueprint("pathways", __name__)

READ_ROLES = ["PlatformAdmin", "ProjectOperator", "ProgramAdministrator",
              "CreditVerifier", "FinanceController"]


@bp.post("/credit-pathways")
@endpoint(["ProgramAdministrator"])
def create_pathway():
    b = body()
    (facility,) = resolve_refs(b, (("facility_id", get_facility),))
    row = db.new_row({
        "facility_id": facility["id"],
        "program": b.enum("program", ("LCFS", "RFS_D3")),
        "pathway_code": b.string("pathway_code"),
        "reference_start_date": None,
        "reference_end_date": None,
        "status": "PROVISIONAL",
        "certified_ci_score": None,
        "verified_ci_score": None,
        "ci_adjustment": None,
    })
    db.pathways[row["id"]] = row
    return created(derive.ser_pathway(row))


@bp.get("/credit-pathways")
@endpoint(READ_ROLES)
def list_pathways():
    return paged_list(db.pathways, derive.ser_pathway,
                      ("facility_id", "program", "status"))


@bp.get("/credit-pathways/<pathway_id>")
@endpoint(READ_ROLES)
def read_pathway(pathway_id):
    return ok(derive.ser_pathway(get_pathway(pathway_id)))


@bp.get("/credit-pathways/<pathway_id>/credit-ledger")
@endpoint(["ProgramAdministrator", "CreditVerifier", "FinanceController"])
def credit_ledger(pathway_id):
    return ok(derive.ser_pathway(get_pathway(pathway_id)))


@bp.post("/credit-pathways/<pathway_id>/certification-decision")
@endpoint(["ProgramAdministrator"])
def certification_decision(pathway_id):
    pathway = get_pathway(pathway_id)
    b = body()
    decision = b.enum("decision", ("CERTIFY", "REINSTATE", "REVOKE"))
    b.string("reason", required=False)

    if decision == "CERTIFY":
        start = b.date("reference_start_date")
        end = b.date("reference_end_date")
        require_range(start, end)
        if pathway["status"] != "PROVISIONAL":
            fail("ERR_INVALID_STATE", "Only a PROVISIONAL pathway may be certified.")
        if not derive.pipeline_days_in_window(pathway["facility_id"], start, end):
            fail("ERR_INVALID_STATE",
                 "No pipeline-quality operations day lies inside the reference window.")
        pathway["reference_start_date"] = b.raw["reference_start_date"]
        pathway["reference_end_date"] = b.raw["reference_end_date"]
        pathway["certified_ci_score"] = derive.certified_ci_score(
            pathway["facility_id"], start, end)
        pathway["status"] = "CERTIFIED"
    elif decision == "REINSTATE":
        if pathway["status"] != "SUSPENDED":
            fail("ERR_INVALID_STATE", "Only a SUSPENDED pathway may be reinstated.")
        for audit in db.audits.values():
            if audit["pathway_id"] == pathway["id"] and audit["status"] != "CLOSED":
                fail("ERR_INVALID_STATE",
                     "Every verification audit on the pathway must be CLOSED.")
        pathway["status"] = "CERTIFIED"
    else:
        if pathway["status"] != "SUSPENDED":
            fail("ERR_INVALID_STATE", "Only a SUSPENDED pathway may be revoked.")
        pathway["status"] = "REVOKED"
        batches = [x for x in derive.batches_of_pathway(pathway["id"])
                   if x["status"] == "ISSUED"]
        batches.sort(key=lambda r: (r["_created"], r["_seq"]))
        for batch in batches:
            batch["status"] = "REVERSED"
            batch["reversal_reason"] = "REGULATOR_ORDER"
            db.touch(batch)

    db.touch(pathway)
    return ok(derive.ser_pathway(pathway))
