"""PriceQuote endpoints (PRD §3.2)."""
from flask import Blueprint, request
import db
import response
import common
import errors
import middleware
from services import serializers, calculations

bp = Blueprint("price_quotes", __name__)

READ_ROLES = ["Anonymous", "Member", "PlatformAdmin", "PharmacyOperator"]
WRITE_ROLES = ["PharmacyOperator", "PlatformAdmin"]


def _windows_overlap(a_eff, a_exp, b_eff, b_exp):
    """Half-open [eff, exp) intersection test. Abutment (touching) is NOT overlap."""
    return a_eff < b_exp and b_eff < a_exp


@bp.route("/price-quotes", methods=["POST"])
def create_quote():
    middleware.require_auth(WRITE_ROLES)
    body = common.get_body()
    drug_id = common.req_str(body, "drug_id")
    pharmacy_id = common.req_str(body, "pharmacy_id")
    cash = common.req_int(body, "cash_price_cents")
    discount = common.req_int(body, "discount_price_cents")
    gold = common.req_int(body, "gold_price_cents")
    effective_at = common.req_str(body, "effective_at")
    expires_at = common.req_str(body, "expires_at")

    eff_dt = db.parse_iso(effective_at)
    exp_dt = db.parse_iso(expires_at)
    if eff_dt is None or exp_dt is None:
        raise errors.invalid_request("effective_at/expires_at must be valid ISO 8601 instants.")
    if not (exp_dt > eff_dt):
        raise errors.invalid_request("expires_at must be strictly after effective_at.")
    for label, val in (("cash_price_cents", cash), ("discount_price_cents", discount), ("gold_price_cents", gold)):
        if val < 1:
            raise errors.invalid_request("%s must be >= 1." % label)

    # existence (priority 4): FKs left-to-right
    drug = common.must_exist(db.drugs, drug_id, "Drug")
    pharmacy = common.must_exist(db.pharmacies, pharmacy_id, "Pharmacy")

    # pharmacy must be ACTIVE at quote time (PRD §3.2). No dedicated error id -> generic.
    if pharmacy["status"] != "ACTIVE":
        raise errors.validation("Pharmacy must be ACTIVE to publish a quote.")

    # price ordering (priority 11): cash<=awp, discount<=cash, gold<=discount
    if not (cash <= drug["awp_cents"] and discount <= cash and gold <= discount):
        raise errors.ApiError(errors.ERR_PRICE_ORDER_VIOLATION, 422,
                              "Quote price ordering violated (cash<=awp, discount<=cash, gold<=discount).")

    # period overlap (priority 11.5): no two PUBLISHED quotes for same (pharmacy, drug)
    # with intersecting half-open windows; abutment allowed.
    for q in db.price_quotes.values():
        if q["pharmacy_id"] != pharmacy_id or q["drug_id"] != drug_id:
            continue
        if q["status"] != "PUBLISHED":
            continue
        q_eff = db.parse_iso(q["effective_at"])
        q_exp = db.parse_iso(q["expires_at"])
        if _windows_overlap(eff_dt, exp_dt, q_eff, q_exp):
            raise errors.ApiError(errors.ERR_QUOTE_PERIOD_OVERLAP, 409,
                                  "Overlapping PUBLISHED quote window for this pharmacy/drug.")

    rec = {
        "drug_id": drug_id,
        "pharmacy_id": pharmacy_id,
        "cash_price_cents": cash,
        "discount_price_cents": discount,
        "gold_price_cents": gold,
        "effective_at": effective_at,
        "expires_at": expires_at,
        "status": "PUBLISHED",
    }
    db.stamp_create(rec, common_fields=True)
    db.price_quotes[rec["id"]] = rec
    return response.object_response(serializers.serialize(rec), 201)


@bp.route("/price-quotes/<qid>", methods=["GET"])
def get_quote(qid):
    middleware.require_auth(READ_ROLES)
    rec = common.must_exist(db.price_quotes, qid, "PriceQuote")
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/price-quotes", methods=["GET"])
def list_quotes():
    middleware.require_auth(READ_ROLES)
    limit, offset = common.parse_pagination()
    drug_id = request.args.get("drug_id")
    pharmacy_id = request.args.get("pharmacy_id")
    status = request.args.get("status")
    items = list(db.price_quotes.values())
    if drug_id is not None:
        items = [q for q in items if q["drug_id"] == drug_id]
    if pharmacy_id is not None:
        items = [q for q in items if q["pharmacy_id"] == pharmacy_id]
    if status is not None:
        items = [q for q in items if q["status"] == status]
    window, total = common.paginate(items, limit, offset)
    return response.array_response(serializers.serialize_list(window), limit, offset, total, 200)


@bp.route("/price-quotes/<qid>/expire", methods=["POST"])
def expire_quote(qid):
    middleware.require_auth(WRITE_ROLES)
    rec = common.must_exist(db.price_quotes, qid, "PriceQuote")
    if rec["status"] != "PUBLISHED":
        raise errors.invalid_state("Quote is not PUBLISHED.")
    rec["status"] = "EXPIRED"
    db.touch(rec)
    return response.object_response(serializers.serialize(rec), 200)
