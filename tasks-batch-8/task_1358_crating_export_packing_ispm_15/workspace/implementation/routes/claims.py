"""DamageClaim endpoints (PRD §3.9)."""
from flask import Blueprint

from db import STORE, new_id, now_iso, logical_now, touch
from errors import (ApiError, ERR_JOB_INVALID_STATE, ERR_CLAIM_INVALID_STATE,
                    ERR_CLAIM_WINDOW_EXPIRED, ERR_FORBIDDEN, bad_request,
                    not_found)
from middleware import (ALL_OPERATIONAL, require_roles, body, req_str, req_enum,
                        req_int, paginate, enum_filter, str_filter)
from response import success
from services import calc
from services.state import get, ser_claim

bp = Blueprint("claims", __name__)

CLAIM_TYPES = {"IMPACT", "TILT", "MOISTURE", "OTHER"}
CLAIM_STATUSES = {"FILED", "UNDER_REVIEW", "APPROVED", "DENIED", "SETTLED"}
CLAIM_WINDOW_SECONDS = 30 * 86400


def _get_claim_or_404(cid):
    c = get("claims", cid)
    if not c:
        raise not_found("DamageClaim not found")
    return c


@bp.post("/crating/packing-jobs/<jid>/claims")
def create_claim(jid):
    uid, _ = require_roles(["Customer"])
    d = body()
    crate_id = req_str(d, "crate_id")
    claim_type = req_enum(d, "claim_type", CLAIM_TYPES)
    description = req_str(d, "description")
    amount = req_int(d, "amount_claimed_cents", minimum=1)
    j = get("jobs", jid)
    if not j:
        raise not_found("PackingJob not found")
    if uid != j["customer_id"]:
        raise ApiError(ERR_FORBIDDEN, "Customers may only claim on their own jobs", 403)
    crate = get("crates", crate_id)
    if not crate or crate["packing_job_id"] != jid:
        raise not_found("Crate not found within this job")
    if j["status"] != "DELIVERED":
        raise ApiError(ERR_JOB_INVALID_STATE,
                       "Claims may only be filed on DELIVERED jobs", 409)
    now = logical_now()
    if (now - j["delivered_at"]).total_seconds() > CLAIM_WINDOW_SECONDS:
        raise ApiError(ERR_CLAIM_WINDOW_EXPIRED,
                       "Claim filed more than 30 days after delivery", 422)
    rec = {"id": new_id(), "packing_job_id": jid, "crate_id": crate_id,
           "claim_type": claim_type, "description": description,
           "amount_claimed_cents": amount, "amount_approved_cents": None,
           "amount_settled_cents": 0, "amount_waived_cents": 0,
           "appeal_used": False, "filed_at": now, "status": "FILED",
           "created_at": now_iso(), "updated_at": now_iso(), "version": 1}
    STORE["claims"][rec["id"]] = rec
    return success(ser_claim(rec), status=201)


@bp.get("/crating/claims/<cid>")
def get_claim(cid):
    require_roles(ALL_OPERATIONAL)
    return success(ser_claim(_get_claim_or_404(cid)))


@bp.get("/crating/claims")
def list_claims():
    require_roles(ALL_OPERATIONAL)
    job_id = str_filter("packing_job_id")
    crate_id = str_filter("crate_id")
    status = enum_filter("status", CLAIM_STATUSES)
    recs = [c for c in STORE["claims"].values()
            if (job_id is None or c["packing_job_id"] == job_id)
            and (crate_id is None or c["crate_id"] == crate_id)
            and (status is None or c["status"] == status)]
    recs.sort(key=lambda c: c["created_at"])
    page, meta = paginate(recs)
    return success([ser_claim(c) for c in page], pagination=meta)


@bp.post("/crating/claims/<cid>/review")
def review_claim(cid):
    require_roles(["ClaimsAdjuster"])
    c = _get_claim_or_404(cid)
    if c["status"] != "FILED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "review requires status FILED", 409)
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return success(ser_claim(c))


@bp.post("/crating/claims/<cid>/approve")
def approve_claim(cid):
    require_roles(["ClaimsAdjuster"])
    c = _get_claim_or_404(cid)
    if c["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "approve requires status UNDER_REVIEW", 409)
    j = get("jobs", c["packing_job_id"])
    crate = get("crates", c["crate_id"])
    item = get("items", crate["item_id"]) if crate else None
    c["amount_approved_cents"] = calc.claim_approved_amount(
        c["claim_type"], c["amount_claimed_cents"],
        item["declared_value_cents"], j["delivered_at"], c["filed_at"])
    c["status"] = "APPROVED"
    touch(c)
    return success(ser_claim(c))


@bp.post("/crating/claims/<cid>/deny")
def deny_claim(cid):
    require_roles(["ClaimsAdjuster"])
    c = _get_claim_or_404(cid)
    if c["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "deny requires status UNDER_REVIEW", 409)
    c["status"] = "DENIED"
    touch(c)
    return success(ser_claim(c))


@bp.post("/crating/claims/<cid>/settle")
def settle_claim(cid):
    require_roles(["ClaimsAdjuster"])
    d = body()
    paid = req_int(d, "amount_paid_cents", minimum=0)
    c = _get_claim_or_404(cid)
    if c["status"] != "APPROVED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "settle requires status APPROVED", 409)
    if paid > c["amount_approved_cents"]:
        raise bad_request("amount_paid_cents may not exceed amount_approved_cents")
    c["amount_settled_cents"] = paid
    c["amount_waived_cents"] = c["amount_approved_cents"] - paid
    c["status"] = "SETTLED"
    touch(c)
    return success(ser_claim(c))


@bp.post("/crating/claims/<cid>/appeal")
def appeal_claim(cid):
    uid, _ = require_roles(["Customer"])
    c = _get_claim_or_404(cid)
    j = get("jobs", c["packing_job_id"])
    if not j or uid != j["customer_id"]:
        raise ApiError(ERR_FORBIDDEN, "Customers may only appeal their own claims", 403)
    if c["status"] != "DENIED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "appeal requires status DENIED", 409)
    if c["appeal_used"]:
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Only one appeal is allowed", 409)
    c["appeal_used"] = True
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return success(ser_claim(c))
