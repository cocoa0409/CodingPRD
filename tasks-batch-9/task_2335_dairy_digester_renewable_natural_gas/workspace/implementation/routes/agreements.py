from flask import Blueprint, g

import config
from db import db, fmt_dt
from errors import fail
from middleware import endpoint, body
from response import created, ok
from routes.common import get_agreement, get_dairy, get_facility, paged_list, resolve_refs
from services import cascade, derive
from validation import require_range

bp = Blueprint("agreements", __name__)

READ_ROLES = ["PlatformAdmin", "ProjectOperator", "DairyPartner",
              "FinanceController", "ProgramAdministrator"]


@bp.post("/feedstock-agreements")
@endpoint(["ProjectOperator"])
def create_agreement():
    b = body()
    dairy, facility = resolve_refs(b, (("dairy_id", get_dairy), ("facility_id", get_facility)))
    committed = b.number("committed_tonnes_per_day", 3, gt=0)
    min_ts = b.number("minimum_total_solids_pct", 1, gt=0, lt=100)
    term_start = b.date("term_start_date")
    term_end = b.date("term_end_date")
    share_pct = b.number("revenue_share_pct", 4, gt=0, le="0.95")
    basis = b.enum("revenue_share_basis", ("NET", "GROSS"))
    curtailable = b.boolean("curtailable")
    require_range(term_start, term_end)

    row = db.new_row({
        "dairy_id": dairy["id"],
        "facility_id": facility["id"],
        "committed_tonnes_per_day": committed,
        "minimum_total_solids_pct": min_ts,
        "term_start_date": b.raw["term_start_date"],
        "term_end_date": b.raw["term_end_date"],
        "revenue_share_pct": share_pct,
        "revenue_share_basis": basis,
        "curtailable": curtailable,
        "status": "DRAFT",
        "negotiation_round": 0,
        "countered_tonnes_per_day": None,
        "countered_revenue_share_pct": None,
        "suspension_reason": None,
        "signed_at": None,
    })
    db.agreements[row["id"]] = row
    return created(derive.ser_agreement(row))


@bp.get("/feedstock-agreements")
@endpoint(READ_ROLES)
def list_agreements():
    return paged_list(db.agreements, derive.ser_agreement,
                      ("dairy_id", "facility_id", "status"))


@bp.get("/feedstock-agreements/<agreement_id>")
@endpoint(READ_ROLES)
def read_agreement(agreement_id):
    return ok(derive.ser_agreement(get_agreement(agreement_id)))


@bp.post("/feedstock-agreements/<agreement_id>/offer")
@endpoint(["ProjectOperator"])
def offer_agreement(agreement_id):
    agreement = get_agreement(agreement_id)
    b = body()
    b.string("cover_note", required=False)
    if agreement["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT agreement may be offered.")
    dairy = db.dairies[agreement["dairy_id"]]
    active, contracted = derive.dairy_counts(dairy["id"])
    if derive.dairy_status(active, contracted) not in ("PROSPECT", "CONTRACTED"):
        fail("ERR_INVALID_STATE", "A SUSPENDED dairy cannot be offered new business.")
    agreement["status"] = "PENDING_DAIRY_SIGNATURE"
    db.touch(agreement)
    return ok(derive.ser_agreement(agreement))


@bp.post("/feedstock-agreements/<agreement_id>/counter")
@endpoint(["DairyPartner"])
def counter_agreement(agreement_id):
    agreement = get_agreement(agreement_id)
    if g.user_id != agreement["dairy_id"]:
        fail("ERR_NOT_OWNING_DAIRY", "The acting dairy does not own this agreement.")
    b = body()
    tonnes = b.number("countered_tonnes_per_day", 3, gt=0)
    pct = b.number("countered_revenue_share_pct", 4, gt=0)
    b.string("comment", required=False)
    if agreement["status"] != "PENDING_DAIRY_SIGNATURE":
        fail("ERR_INVALID_STATE", "Only an agreement pending signature may be countered.")
    if agreement["negotiation_round"] >= config.MAX_NEGOTIATION_ROUNDS:
        fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED", "The negotiation round ceiling is reached.")
    agreement["countered_tonnes_per_day"] = tonnes
    agreement["countered_revenue_share_pct"] = pct
    agreement["negotiation_round"] += 1
    agreement["status"] = "COUNTERED"
    db.touch(agreement)
    return ok(derive.ser_agreement(agreement))


@bp.post("/feedstock-agreements/<agreement_id>/revise")
@endpoint(["ProjectOperator"])
def revise_agreement(agreement_id):
    agreement = get_agreement(agreement_id)
    b = body()
    committed = b.number("committed_tonnes_per_day", 3, gt=0)
    min_ts = b.number("minimum_total_solids_pct", 1, gt=0, lt=100)
    share_pct = b.number("revenue_share_pct", 4, gt=0, le="0.95")
    if agreement["status"] != "COUNTERED":
        fail("ERR_INVALID_STATE", "Only a COUNTERED agreement may be revised.")
    agreement["committed_tonnes_per_day"] = committed
    agreement["minimum_total_solids_pct"] = min_ts
    agreement["revenue_share_pct"] = share_pct
    agreement["countered_tonnes_per_day"] = None
    agreement["countered_revenue_share_pct"] = None
    agreement["status"] = "DRAFT"
    db.touch(agreement)
    return ok(derive.ser_agreement(agreement))


@bp.post("/feedstock-agreements/<agreement_id>/sign")
@endpoint(["DairyPartner"])
def sign_agreement(agreement_id):
    agreement = get_agreement(agreement_id)
    if g.user_id != agreement["dairy_id"]:
        fail("ERR_NOT_OWNING_DAIRY", "The acting dairy does not own this agreement.")
    b = body()
    b.string("signatory_name")
    if agreement["status"] != "PENDING_DAIRY_SIGNATURE":
        fail("ERR_INVALID_STATE", "Only an agreement pending signature may be signed.")
    agreement["status"] = "ACTIVE"
    agreement["signed_at"] = fmt_dt(db.now_logical())
    db.touch(agreement)
    db.touch(db.dairies[agreement["dairy_id"]])
    return ok(derive.ser_agreement(agreement))


@bp.post("/feedstock-agreements/<agreement_id>/status-change")
@endpoint(["ProjectOperator"])
def status_change_agreement(agreement_id):
    agreement = get_agreement(agreement_id)
    b = body()
    action = b.enum("action", ("SUSPEND", "REINSTATE", "TERMINATE"))
    b.string("reason", required=False)
    facility = db.facilities[agreement["facility_id"]]

    if action == "SUSPEND":
        if agreement["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "Only an ACTIVE agreement may be suspended.")
        cascade.suspend_agreement(agreement, "COMPLIANCE")
    elif action == "REINSTATE":
        if agreement["status"] != "SUSPENDED":
            fail("ERR_INVALID_STATE", "Only a SUSPENDED agreement may be reinstated.")
        if facility["ops_posture"] == "UPSET":
            fail("ERR_INVALID_STATE", "The facility is in biological upset.")
        agreement["status"] = "ACTIVE"
        agreement["suspension_reason"] = None
        db.touch(agreement)
        db.touch(db.dairies[agreement["dairy_id"]])
    else:
        if agreement["status"] not in ("ACTIVE", "SUSPENDED"):
            fail("ERR_INVALID_STATE", "Only an ACTIVE or SUSPENDED agreement may be terminated.")
        agreement["status"] = "TERMINATED"
        db.touch(agreement)
        db.touch(db.dairies[agreement["dairy_id"]])
    return ok(derive.ser_agreement(agreement))
