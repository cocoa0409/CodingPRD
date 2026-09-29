from decimal import Decimal

from flask import Blueprint, g

from db import db
from errors import fail
from middleware import endpoint, body
from numeric import q
from response import created, ok
from routes.common import get_batch, get_facility, get_pathway, paged_list, resolve_refs
from services import calc, cascade, derive
from validation import date_of, require_range

bp = Blueprint("batches", __name__)

READ_ROLES = ["PlatformAdmin", "ProgramAdministrator", "CreditVerifier",
              "FinanceController"]
ZERO3 = Decimal("0.000")


@bp.post("/credit-batches")
@endpoint(["ProgramAdministrator"])
def create_batch():
    b = body(allow_version_fields=("expected_pathway_version",))
    pathway, facility = resolve_refs(b, (("pathway_id", get_pathway),
                                         ("facility_id", get_facility)))
    start = b.date("period_start_date")
    end = b.date("period_end_date")
    expected = b.integer("expected_pathway_version")
    require_range(start, end)
    if expected != pathway["version"]:
        fail("ERR_STALE_VERSION", "The pathway has moved since it was last read.")
    if facility["id"] != pathway["facility_id"]:
        fail("ERR_FACILITY_PATHWAY_MISMATCH",
             "facility_id must equal the pathway's own facility.")
    for other in derive.batches_of_pathway(pathway["id"]):
        if other["status"] not in ("CLAIMED", "VERIFIED", "ISSUED"):
            continue
        if date_of(other["period_start_date"]) <= end and \
                date_of(other["period_end_date"]) >= start:
            fail("ERR_CREDIT_PERIOD_OVERLAP",
                 "A claimed, verified or issued batch already covers this period.")

    row = db.new_row({
        "pathway_id": pathway["id"],
        "facility_id": facility["id"],
        "period_start_date": b.raw["period_start_date"],
        "period_end_date": b.raw["period_end_date"],
        "superseded_by_batch_id": None,
        "status": "DRAFT",
        "delivered_mmbtu": ZERO3,
        "ci_score_used": None,
        "credit_quantity_provisional": None,
        "credit_quantity_final": None,
        "credit_value_cents": None,
        "reversal_reason": None,
        "_verified_by": None,
        "_ever_issued": False,
    })
    db.batches[row["id"]] = row

    stale = [x for x in derive.batches_of_pathway(pathway["id"])
             if x["status"] == "DRAFT" and x["id"] != row["id"]
             and date_of(x["period_start_date"]) <= end
             and date_of(x["period_end_date"]) >= start]
    stale.sort(key=lambda r: (r["_created"], r["_seq"]))
    for old in stale:
        old["status"] = "SUPERSEDED"
        old["superseded_by_batch_id"] = row["id"]
        db.touch(old)

    db.touch(pathway)
    return created(derive.ser_batch(row))


@bp.get("/credit-batches")
@endpoint(READ_ROLES)
def list_batches():
    return paged_list(db.batches, derive.ser_batch,
                      ("pathway_id", "facility_id", "status", "superseded_by_batch_id"))


@bp.get("/credit-batches/<batch_id>")
@endpoint(READ_ROLES)
def read_batch(batch_id):
    return ok(derive.ser_batch(get_batch(batch_id)))


@bp.post("/credit-batches/<batch_id>/claim")
@endpoint(["ProgramAdministrator"])
def claim_batch(batch_id):
    batch = get_batch(batch_id)
    b = body()
    b.string("claim_note", required=False)
    pathway = db.pathways[batch["pathway_id"]]

    if batch["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT batch may be claimed.")
    if pathway["status"] != "CERTIFIED":
        fail("ERR_PATHWAY_NOT_CERTIFIED", "The pathway is not CERTIFIED.")

    start = date_of(batch["period_start_date"])
    end = date_of(batch["period_end_date"])
    total = Decimal("0")
    found = False
    for nom in db.nominations.values():
        if nom["status"] != "DELIVERED":
            continue
        day = db.ops_days.get(nom["ops_day_id"])
        if day is None or day["facility_id"] != batch["facility_id"]:
            continue
        if not (start <= date_of(day["ops_date"]) <= end):
            continue
        found = True
        total += Decimal(str(nom["delivered_mmbtu"] or 0))
    if not found:
        fail("ERR_NO_DELIVERED_VOLUME",
             "No delivered injection falls inside the batch period.")

    batch["delivered_mmbtu"] = q(total, 3)
    batch["ci_score_used"] = pathway["certified_ci_score"]
    qty, _value = calc.credit_quantity(pathway["program"], batch["ci_score_used"],
                                       batch["delivered_mmbtu"])
    batch["credit_quantity_provisional"] = qty
    batch["status"] = "CLAIMED"
    db.touch(batch)
    return ok(derive.ser_batch(batch))


@bp.post("/credit-batches/<batch_id>/verify")
@endpoint(["CreditVerifier"])
def verify_batch(batch_id):
    batch = get_batch(batch_id)
    b = body()
    b.string("verifier_note", required=False)
    pathway = db.pathways[batch["pathway_id"]]

    if batch["status"] != "CLAIMED":
        fail("ERR_INVALID_STATE", "Only a CLAIMED batch may be verified.")
    if pathway["status"] != "CERTIFIED":
        fail("ERR_PATHWAY_NOT_CERTIFIED", "The pathway is not CERTIFIED.")

    cascade.recompute_batch_final(batch, pathway)
    batch["status"] = "VERIFIED"
    batch["_verified_by"] = g.user_id
    db.touch(batch)
    return ok(derive.ser_batch(batch))


@bp.post("/credit-batches/<batch_id>/issue")
@endpoint(["ProgramAdministrator"])
def issue_batch(batch_id):
    batch = get_batch(batch_id)
    b = body()
    b.string("issuance_reference", required=False)
    pathway = db.pathways[batch["pathway_id"]]

    if batch["status"] != "VERIFIED":
        fail("ERR_INVALID_STATE", "Only a VERIFIED batch may be issued.")
    if pathway["status"] != "CERTIFIED":
        fail("ERR_PATHWAY_NOT_CERTIFIED", "The pathway is not CERTIFIED.")
    if batch["_verified_by"] is not None and g.user_id == batch["_verified_by"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The issuer must differ from the verifier of this batch.")

    batch["status"] = "ISSUED"
    batch["_ever_issued"] = True
    db.touch(batch)
    db.touch(pathway)
    return ok(derive.ser_batch(batch))


@bp.post("/credit-batches/<batch_id>/reverse")
@endpoint(["ProgramAdministrator"])
def reverse_batch(batch_id):
    batch = get_batch(batch_id)
    b = body()
    reason = b.enum("reversal_reason",
                    ("MATERIAL_FINDING", "REGULATOR_ORDER", "OPERATOR_WITHDRAWAL"))
    pathway = db.pathways[batch["pathway_id"]]

    if batch["status"] != "ISSUED":
        fail("ERR_INVALID_STATE", "Only an ISSUED batch may be reversed.")

    batch["status"] = "REVERSED"
    batch["reversal_reason"] = reason
    db.touch(batch)
    db.touch(pathway)
    cascade.recompute_draft_statements_for_batches(batch["facility_id"], [batch])
    return ok(derive.ser_batch(batch))
