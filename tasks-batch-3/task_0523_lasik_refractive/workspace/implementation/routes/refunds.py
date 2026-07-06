from flask import Blueprint, request

from db import db
from middleware import require_auth
from response import success
from helpers import (
    stamp_create, touch, serialize, get_json_body, get_or_404,
    as_str, as_enum, paginate, sorted_by_created,
)
from errors import err
from services.calc import refund_payout_cents

bp = Blueprint("refunds", __name__)


@bp.post("/refractive/refund-claims")
@require_auth(["Coordinator", "Patient"])
def create_refund_claim():
    body = get_json_body()
    case_id = as_str(body, "case_id")
    case = get_or_404(db.cases, case_id)

    # must be HEALED
    if case["clinical_status"] != "HEALED":
        raise err("ERR_INVALID_STATE", "case must be HEALED to file a refund claim")

    package = db.packages[case["package_id"]]
    # guarantee missed iff final_uncorrected_va < outcome_guarantee_uncorrected_va
    if not (case["final_uncorrected_va"] < package["outcome_guarantee_uncorrected_va"]):
        raise err("ERR_GUARANTEE_NOT_MET", "outcome guarantee was met")

    rec = {
        "case_id": case_id,
        "measured_uncorrected_va": case["final_uncorrected_va"],
        "refund_mode": package["refund_mode"],
        "refund_amount_cents": None,
        "status": "PENDING",
    }
    stamp_create(rec)
    db.refunds[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/refractive/refund-claims/<rid>")
@require_auth(["Coordinator", "Patient"])
def get_refund_claim(rid):
    return success(serialize(get_or_404(db.refunds, rid)), 200)


@bp.get("/refractive/refund-claims")
@require_auth(["Coordinator", "Patient"])
def list_refund_claims():
    items = list(db.refunds.values())
    for field in ("case_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [x for x in items if x[field] == v]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([serialize(x) for x in page], 200, is_array=True, pagination=meta)


@bp.post("/refractive/refund-claims/<rid>/adjudicate")
@require_auth(["Coordinator"])
def adjudicate_refund_claim(rid):
    claim = get_or_404(db.refunds, rid)
    body = get_json_body()
    decision = as_enum(body, "decision", {"PAY", "REJECT"})

    if claim["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "claim must be PENDING to adjudicate")

    if decision == "REJECT":
        claim["status"] = "REJECTED"
        touch(claim)
        return success(serialize(claim), 200)

    # PAY preconditions
    case = db.cases[claim["case_id"]]
    if case["financial_status"] != "PAID_IN_FULL":
        raise err("ERR_INVALID_STATE", "origin case must be PAID_IN_FULL to pay refund")

    # no FULFILLED enhancement for origin case
    if any(e["origin_case_id"] == case["id"] and e["status"] == "FULFILLED"
           for e in db.enhancements.values()):
        raise err("ERR_ENHANCEMENT_ALREADY_FULFILLED",
                  "a fulfilled enhancement already honored the guarantee")

    # compute payout from the case's financing plan settled amount
    package = db.packages[case["package_id"]]
    settled = 0
    for f in db.financing.values():
        if f["case_id"] == case["id"] and f["status"] in ("OPEN", "SETTLED"):
            settled = f["amount_settled_cents"]
            break

    payout = refund_payout_cents(claim["refund_mode"], settled, package["deposit_cents"])
    claim["refund_amount_cents"] = payout
    claim["status"] = "PAID"
    touch(claim)

    case["financial_status"] = "REFUNDED"
    touch(case)
    return success(serialize(claim), 200)
