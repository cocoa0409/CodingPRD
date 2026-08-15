from flask import Blueprint

import db
from errors import ApiError
from middleware import authenticate, require_role, locked
from response import ok, ok_list
from serializers import ser_claim
from validators import body, req_field, opt_field, as_str, as_enum, pagination

bp = Blueprint("claims", __name__)

CLAIM_REASONS = ["DECAY_RECURRENCE", "PRODUCT_FAILURE"]
OUTCOMES = ["HONOR", "DENY"]


@bp.post("/pole-program/warranty-claims")
@locked
def create_claim():
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    d = body()
    treatment_order_id = as_str(req_field(d, "treatment_order_id"),
                                "treatment_order_id")
    claim_reason = as_enum(req_field(d, "claim_reason"), "claim_reason",
                           CLAIM_REASONS)
    order = db.treatments.get(treatment_order_id)
    if order is None:
        raise ApiError("ERR_TREATMENT_NOT_FOUND", 404,
                       "treatment order id does not resolve")
    if order["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "claim requires treatment order status == VERIFIED")
    if any(c["treatment_order_id"] == treatment_order_id
           and c["status"] == "FILED" for c in db.claims.values()):
        raise ApiError("ERR_CLAIM_ALREADY_OPEN", 409,
                       "Another FILED claim exists for the same treatment order")
    n = db.clock_now()
    end = order["warranty_end_date"]
    if end is not None and n > end:
        raise ApiError("ERR_WARRANTY_EXPIRED", 422,
                       "Claim filed_at > warranty_end_date")
    rec = db.new_record()
    rec.update(treatment_order_id=treatment_order_id, claim_reason=claim_reason,
               status="FILED", filed_at=n, filed_by_user_id=uid,
               adjudication_note=None)
    db.claims[rec["id"]] = rec
    return ok(ser_claim(rec), 201)


@bp.get("/pole-program/treatment-work-orders/<tid>/warranty-claims")
def list_claims(tid):
    authenticate()
    order = db.treatments.get(tid)
    if order is None:
        raise ApiError("ERR_TREATMENT_NOT_FOUND", 404,
                       "treatment order id does not resolve")
    limit, offset = pagination()
    items = sorted((c for c in db.claims.values()
                    if c["treatment_order_id"] == tid),
                   key=lambda c: (c["created_at"], c["_seq"]))
    page = items[offset:offset + limit]
    return ok_list([ser_claim(c) for c in page], len(items), limit, offset)


@bp.post("/pole-program/warranty-claims/<cid>/adjudicate")
@locked
def adjudicate_claim(cid):
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    d = body()
    outcome = as_enum(req_field(d, "outcome"), "outcome", OUTCOMES)
    note = opt_field(d, "adjudication_note", None)
    if note is not None:
        as_str(note, "adjudication_note")
    claim = db.claims.get(cid)
    if claim is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", 404,
                       "warranty claim id does not resolve")
    if claim["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "adjudicate requires claim.status == FILED")
    if note is not None:
        claim["adjudication_note"] = note
    if outcome == "HONOR":
        claim["status"] = "HONORED"
        original = db.treatments[claim["treatment_order_id"]]
        retreat = db.new_record()
        retreat.update(pole_id=original["pole_id"],
                       product_code=original["product_code"], crew_id=None,
                       work_start_date=None, work_end_date=None, cost_cents=0,
                       is_warranty_retreat=True, source_claim_id=claim["id"],
                       status="CREATED", applied_at=None, applied_by_crew_id=None,
                       warranty_years=None, warranty_end_date=None,
                       qa_fail_events=0, _verified_dt=None)
        db.treatments[retreat["id"]] = retreat
        pole = db.poles[original["pole_id"]]
        pole["open_treatment_count"] += 1
        db.touch(pole)
    else:
        claim["status"] = "DENIED"
    db.touch(claim)
    return ok(ser_claim(claim), 200)
