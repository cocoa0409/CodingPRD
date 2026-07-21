"""Claim endpoints: refer, read, list, assess-liability, withdraw, documents."""
from flask import Blueprint, request

import calc
import errors
import serialize
import validate as v
from auth import authorize
from cascade import withdraw_open_demands, withdraw_live_arbitrations
from envelope import success
from helpers import lookup_or_404, respond_list
from store import db, stamp, touch, clock_now
from timeutil import parse_iso

bp = Blueprint("claims", __name__)

DOC_TYPES = {"POLICE_REPORT", "ESTIMATE", "POLICY", "CORRESPONDENCE", "OTHER"}


@bp.route("/subro/claims", methods=["POST"])
def refer_claim():
    uid, role = authorize(request, {"CarrierUser", "RecoverySpecialist"})
    body = v.get_body(request)

    # (3) existence of body FKs, validated only when a usable id is present.
    carrier_id_raw = body.get("carrier_id")
    if isinstance(carrier_id_raw, str) and carrier_id_raw:
        if carrier_id_raw not in db.carriers:
            raise errors.not_found()
    adverse_id_raw = body.get("adverse_party_id")
    if isinstance(adverse_id_raw, str) and adverse_id_raw:
        if adverse_id_raw not in db.adverse_parties:
            raise errors.not_found()

    # (4) carrier ownership for CarrierUser refer.
    if role == "CarrierUser" and isinstance(carrier_id_raw, str) and carrier_id_raw:
        if carrier_id_raw != uid:
            raise errors.not_claim_owner()

    # (5) full body well-formedness.
    carrier_id = v.req_str(body, "carrier_id")
    adverse_party_id = v.req_str(body, "adverse_party_id")
    claim_reference = v.req_str(body, "claim_reference")
    loss_date = v.req_datetime(body, "loss_date")
    paid_loss = v.req_int(body, "paid_loss_cents", min=0)
    deductible = v.req_int(body, "deductible_cents", min=0)
    total_damages = v.req_int(body, "total_damages_cents", min=0)
    statute_deadline = v.req_datetime(body, "statute_deadline")

    carrier = lookup_or_404(db.carriers, carrier_id)
    lookup_or_404(db.adverse_parties, adverse_party_id)

    # (12) carrier must be ACTIVE.
    if carrier["status"] != "ACTIVE":
        raise errors.carrier_suspended()

    claim = stamp({
        "carrier_id": carrier_id,
        "adverse_party_id": adverse_party_id,
        "claim_reference": claim_reference,
        "loss_date": loss_date,
        "referral_date": clock_now(),
        "paid_loss_cents": paid_loss,
        "deductible_cents": deductible,
        "total_damages_cents": total_damages,
        "statute_deadline": statute_deadline,
        "liability_pct": None,
        "provisional_recoverable_cents": None,
        "settled_amount_cents": None,
        "final_recovered_cents": 0,
        "deductible_reimbursed_cents": 0,
        "carrier_recovered_cents": 0,
        "accrued_commission_cents": 0,
        "status": "REFERRED",
    })
    db.claims[claim["id"]] = claim
    return success(serialize.claim(claim), "object", 201)


@bp.route("/subro/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    authorize(request, None)
    claim = lookup_or_404(db.claims, claim_id)
    return success(serialize.claim(claim), "object", 200)


@bp.route("/subro/claims", methods=["GET"])
def list_claims():
    authorize(request, None)
    carrier_id = request.args.get("carrier_id")
    adverse_party_id = request.args.get("adverse_party_id")
    status = request.args.get("status")
    items = []
    for c in db.claims.values():
        if carrier_id is not None and c["carrier_id"] != carrier_id:
            continue
        if adverse_party_id is not None and c["adverse_party_id"] != adverse_party_id:
            continue
        if status is not None and c["status"] != status:
            continue
        items.append(c)
    return respond_list(request, items, serialize.claim)


@bp.route("/subro/claims/<claim_id>/assess-liability", methods=["POST"])
def assess_liability(claim_id):
    authorize(request, {"RecoverySpecialist"})
    claim = lookup_or_404(db.claims, claim_id)
    body = v.get_body(request)
    liability_pct = v.req_number(body, "liability_pct", 0, 100)

    # (7) state
    if claim["status"] != "REFERRED":
        raise errors.invalid_state()
    # (9) statute not expired
    if clock_now() >= parse_iso(claim["statute_deadline"]):
        raise errors.statute_expired()
    # (12) carrier still ACTIVE
    carrier = db.carriers[claim["carrier_id"]]
    if carrier["status"] != "ACTIVE":
        raise errors.carrier_suspended()

    adverse = db.adverse_parties[claim["adverse_party_id"]]
    claim["liability_pct"] = liability_pct
    claim["provisional_recoverable_cents"] = calc.provisional_recoverable_cents(claim, adverse)
    claim["status"] = "LIABILITY_ASSESSED"
    touch(claim)
    return success(serialize.claim(claim), "object", 200)


@bp.route("/subro/claims/<claim_id>/withdraw", methods=["POST"])
def withdraw_claim(claim_id):
    uid, role = authorize(request, {"CarrierUser"})
    claim = lookup_or_404(db.claims, claim_id)
    # (4) ownership
    if claim["carrier_id"] != uid:
        raise errors.not_claim_owner()
    # (7) state: only pre-recovery, non-terminal claims may be withdrawn
    prev = claim["status"]
    if prev not in {"REFERRED", "LIABILITY_ASSESSED", "DEMAND_ISSUED", "ARBITRATION"}:
        raise errors.invalid_state()

    claim["status"] = "WITHDRAWN"
    touch(claim)
    if prev == "DEMAND_ISSUED":
        withdraw_open_demands(claim_id)
    elif prev == "ARBITRATION":
        withdraw_open_demands(claim_id)
        withdraw_live_arbitrations(claim_id)
    return success(serialize.claim(claim), "object", 200)


@bp.route("/subro/claims/<claim_id>/documents", methods=["POST"])
def add_document(claim_id):
    uid, role = authorize(request, {"RecoverySpecialist", "CarrierUser"})
    claim = lookup_or_404(db.claims, claim_id)
    # (4) ownership for CarrierUser
    if role == "CarrierUser" and claim["carrier_id"] != uid:
        raise errors.not_claim_owner()
    body = v.get_body(request)
    doc_type = v.req_enum(body, "doc_type", DOC_TYPES)
    title = v.req_str(body, "title")
    uri = v.req_str(body, "uri")
    doc = stamp({
        "claim_id": claim_id,
        "doc_type": doc_type,
        "title": title,
        "uri": uri,
    }, versioned=False)
    db.claim_documents[doc["id"]] = doc
    return success(serialize.claim_document(doc), "object", 201)


@bp.route("/subro/claims/<claim_id>/documents", methods=["GET"])
def list_documents(claim_id):
    authorize(request, None)
    lookup_or_404(db.claims, claim_id)
    items = [d for d in db.claim_documents.values() if d["claim_id"] == claim_id]
    return respond_list(request, items, serialize.claim_document)
