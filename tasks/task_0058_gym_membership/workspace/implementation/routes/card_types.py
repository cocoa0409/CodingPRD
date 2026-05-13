"""Card type endpoints."""
from flask import Blueprint, request, g
from db import state, new_id, stamp_create, bump, lock
from errors import raise_err
from response import success_object, success_array
from middleware import require_roles
from routes.helpers import get_json, parse_pagination, paginate, sort_by_created, check_occ
from serializers import serialize_card_type


bp = Blueprint("card_types", __name__)


VALID_CATEGORIES = {"PER_VISIT", "MONTHLY", "ANNUAL"}


def _validate_code(code: str):
    if not isinstance(code, str) or not (2 <= len(code) <= 32):
        raise_err("ERR_VALIDATION", "code length 2..32")
    if not code.replace("_", "").isupper() and not all(c.isupper() or c.isdigit() or c == "_" for c in code):
        raise_err("ERR_VALIDATION", "code must be uppercase snake")
    # Looser check: only A-Z, 0-9, underscore
    for c in code:
        if not (c.isupper() or c.isdigit() or c == "_"):
            raise_err("ERR_VALIDATION", "code must be uppercase snake")


@bp.route("/card-types", methods=["POST"])
def create_card_type():
    require_roles("PlatformAdmin")
    body = get_json()
    code = body.get("code")
    _validate_code(code)
    category = body.get("category")
    if category not in VALID_CATEGORIES:
        raise_err("ERR_VALIDATION", "invalid category")
    price_cents = body.get("price_cents")
    if not isinstance(price_cents, int) or price_cents < 0:
        raise_err("ERR_VALIDATION", "price_cents >= 0")
    validity_days = body.get("validity_days")
    if not isinstance(validity_days, int) or not (1 <= validity_days <= 3650):
        raise_err("ERR_VALIDATION", "validity_days 1..3650")
    visit_quota = body.get("visit_quota")
    if not isinstance(visit_quota, int) or visit_quota < 0:
        raise_err("ERR_VALIDATION", "visit_quota >= 0")
    family_shareable = bool(body.get("family_shareable", False))
    max_freeze_days = body.get("max_freeze_days")
    if not isinstance(max_freeze_days, int) or max_freeze_days < 0:
        raise_err("ERR_VALIDATION", "max_freeze_days >= 0")
    transfer_fee_pct_bp = body.get("transfer_fee_pct_bp")
    if not isinstance(transfer_fee_pct_bp, int) or not (0 <= transfer_fee_pct_bp <= 10000):
        raise_err("ERR_VALIDATION", "transfer_fee_pct_bp 0..10000")
    renewal_discount_pct_bp = body.get("renewal_discount_pct_bp", 0)
    if not isinstance(renewal_discount_pct_bp, int) or not (0 <= renewal_discount_pct_bp <= 10000):
        raise_err("ERR_VALIDATION", "renewal_discount_pct_bp 0..10000")
    refund_eligibility_days = body.get("refund_eligibility_days")
    if not isinstance(refund_eligibility_days, int) or refund_eligibility_days < 0:
        raise_err("ERR_VALIDATION", "refund_eligibility_days >= 0")
    # Uniqueness on code
    for ct in state["card_types"].values():
        if ct["code"] == code:
            raise_err("ERR_VALIDATION", "code already exists")
    ct = {
        "id": new_id(),
        "code": code,
        "category": category,
        "price_cents": price_cents,
        "validity_days": validity_days,
        "visit_quota": visit_quota,
        "family_shareable": family_shareable,
        "max_freeze_days": max_freeze_days,
        "transfer_fee_pct_bp": transfer_fee_pct_bp,
        "renewal_discount_pct_bp": renewal_discount_pct_bp,
        "refund_eligibility_days": refund_eligibility_days,
        "status": "ACTIVE",
    }
    stamp_create(ct)
    state["card_types"][ct["id"]] = ct
    return success_object(serialize_card_type(ct), status=201)


@bp.route("/card-types", methods=["GET"])
def list_card_types():
    require_roles("PlatformAdmin", "StaffOps", "Member", "Trainer")
    limit, offset = parse_pagination()
    category = request.args.get("category")
    status_q = request.args.get("status")
    items = list(state["card_types"].values())
    if category:
        items = [x for x in items if x["category"] == category]
    if status_q:
        items = [x for x in items if x.get("status") == status_q]
    items = sort_by_created(items)
    sliced, meta = paginate(items, limit, offset)
    return success_array([serialize_card_type(x) for x in sliced], meta)


@bp.route("/card-types/<id_>", methods=["PATCH"])
def patch_card_type(id_):
    require_roles("PlatformAdmin")
    ct = state["card_types"].get(id_)
    if not ct:
        raise_err("ERR_NOT_FOUND", "card type not found")
    body = get_json()
    check_occ(ct, body)
    if "status" in body and body["status"] is not None:
        if body["status"] not in ("ACTIVE", "RETIRED"):
            raise_err("ERR_VALIDATION", "invalid status")
        ct["status"] = body["status"]
    if "price_cents" in body and body["price_cents"] is not None:
        if not isinstance(body["price_cents"], int) or body["price_cents"] < 0:
            raise_err("ERR_VALIDATION", "price_cents >= 0")
        ct["price_cents"] = body["price_cents"]
    if "renewal_discount_pct_bp" in body and body["renewal_discount_pct_bp"] is not None:
        v = body["renewal_discount_pct_bp"]
        if not isinstance(v, int) or not (0 <= v <= 10000):
            raise_err("ERR_VALIDATION", "renewal_discount_pct_bp 0..10000")
        ct["renewal_discount_pct_bp"] = v
    bump(ct)
    return success_object(serialize_card_type(ct))
