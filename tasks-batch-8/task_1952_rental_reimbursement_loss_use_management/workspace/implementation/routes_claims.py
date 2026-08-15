"""Claims and their nested list endpoints."""
from flask import Blueprint, request

import db
from errors import api_error
from middleware import ALL_ROLES, require_roles
from response import ok, paginate
from services import (authorized_days_total, bump, claim_lou_claims,
                      claim_recovery_cases, claim_reservations, claim_view,
                      get_claim, new_entity, need_date, need_int,
                      recovery_balance_cents, require_claim_open,
                      reservation_view, sorted_by_creation, view)

bp = Blueprint("claims", __name__)


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/claims")
def create_claim():
    require_roles(["ClaimsAdjuster"])
    b = body()
    # rung 4: body FK existence
    check = b.get("policyholder_id")
    if check is not None and check not in db.policyholders:
        raise api_error("ERR_POLICYHOLDER_NOT_FOUND", 404,
                        "policyholder not found: %s" % check)
    # shape
    policyholder_id = b.get("policyholder_id")
    if not isinstance(policyholder_id, str) or not policyholder_id:
        raise api_error("ERR_INVALID_REQUEST", 400, "policyholder_id is required")
    incident_date = need_date(b, "incident_date")
    daily_limit = need_int(b, "coverage_daily_limit_cents")
    duration_cap = need_int(b, "coverage_duration_cap_days")
    per_diem = need_int(b, "loss_of_use_per_diem_cents")
    e = new_entity()
    e.update({
        "policyholder_id": policyholder_id,
        "incident_date": incident_date,
        "coverage_daily_limit_cents": daily_limit,
        "coverage_duration_cap_days": duration_cap,
        "loss_of_use_per_diem_cents": per_diem,
        "rental_track_status": "OPEN",
        "loss_of_use_track_status": "NONE",
        "overall_status": "OPEN",
    })
    db.claims[e["id"]] = e
    return ok(claim_view(e), status=201)


@bp.get("/claims/<cid>")
def get_one_claim(cid):
    require_roles(ALL_ROLES)
    return ok(claim_view(get_claim(cid)))


@bp.post("/claims/<cid>/settle")
def settle_claim(cid):
    require_roles(["SettlementApprover"])
    claim = get_claim(cid)
    require_claim_open(claim)
    reservations = claim_reservations(cid)
    if any(r["status"] not in ("CLOSED", "CANCELLED") for r in reservations):
        raise api_error("ERR_CLAIM_SETTLE_BLOCKED", 409,
                        "claim has non-terminal reservations")
    lou = claim_lou_claims(cid)
    if any(l["status"] not in ("PAID", "DENIED") for l in lou):
        raise api_error("ERR_CLAIM_SETTLE_BLOCKED", 409,
                        "claim has non-terminal loss-of-use claims")
    if recovery_balance_cents(claim) != 0:
        raise api_error("ERR_CLAIM_SETTLE_BLOCKED", 409,
                        "claim recovery balance is non-zero")
    claim["overall_status"] = "SETTLED"
    bump(claim)
    return ok(claim_view(claim))


@bp.post("/claims/<cid>/close")
def close_claim(cid):
    require_roles(["SettlementApprover"])
    claim = get_claim(cid)
    if claim["overall_status"] != "SETTLED":
        raise api_error("ERR_CLAIM_NOT_SETTLED", 409, "claim is not SETTLED")
    claim["overall_status"] = "CLOSED"
    bump(claim)
    return ok(claim_view(claim))


# ---------------------------------------------------------------------------
# Nested claim collections
# ---------------------------------------------------------------------------


def _list(items):
    page, meta = paginate(sorted_by_creation(items), request.args)
    return page, meta


@bp.get("/claims/<cid>/coverage-verifications")
def list_claim_verifications(cid):
    require_roles(ALL_ROLES)
    get_claim(cid)
    items = [v for v in db.verifications.values() if v["claim_id"] == cid]
    page, meta = _list(items)
    return ok([view(v) for v in page], response_type="array", pagination=meta)


@bp.get("/claims/<cid>/repair-orders")
def list_claim_repair_orders(cid):
    require_roles(ALL_ROLES)
    get_claim(cid)
    items = [o for o in db.repair_orders.values() if o["claim_id"] == cid]
    page, meta = _list(items)
    return ok([view(o) for o in page], response_type="array", pagination=meta)


@bp.get("/claims/<cid>/rental-reservations")
def list_claim_reservations(cid):
    require_roles(ALL_ROLES)
    get_claim(cid)
    page, meta = _list(claim_reservations(cid))
    return ok([reservation_view(r) for r in page], response_type="array", pagination=meta)


@bp.get("/claims/<cid>/loss-of-use-claims")
def list_claim_lou(cid):
    require_roles(ALL_ROLES)
    get_claim(cid)
    page, meta = _list(claim_lou_claims(cid))
    return ok([view(l) for l in page], response_type="array", pagination=meta)


@bp.get("/claims/<cid>/recovery-cases")
def list_claim_recovery(cid):
    require_roles(ALL_ROLES)
    get_claim(cid)
    page, meta = _list(claim_recovery_cases(cid))
    return ok([view(rc) for rc in page], response_type="array", pagination=meta)


@bp.get("/claims/<cid>/communication-logs")
def list_claim_comms(cid):
    require_roles(ALL_ROLES)
    get_claim(cid)
    items = [c for c in db.communication_logs.values() if c["claim_id"] == cid]
    page, meta = _list(items)
    return ok([view(c) for c in page], response_type="array", pagination=meta)
