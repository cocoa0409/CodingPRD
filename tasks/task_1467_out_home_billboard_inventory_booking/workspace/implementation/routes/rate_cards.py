"""RateCard endpoints (PRD 3.1)."""
from flask import Blueprint, request

import db
from errors import ApiError, err_invalid_request, err_invalid_state, err_stale
from middleware import require_roles
from response import success, paginate, sort_created
from serializers import rate_card_out, flight_out
from util import req_int, req_num, req_str, req_enum, opt_int, opt_num, is_int

bp = Blueprint("rate_cards", __name__, url_prefix="/api")

DISPLAY_TYPES = ("STATIC", "DIGITAL")
RATE_FIELDS = ("base_weekly_cents", "illumination_premium_pct",
               "traffic_tier_1_threshold", "traffic_tier_1_uplift_pct",
               "traffic_tier_2_threshold", "traffic_tier_2_uplift_pct")


def get_rate_card_or_404(rc_id):
    rc = db.rate_cards.get(rc_id)
    if rc is None:
        raise ApiError("ERR_RATE_CARD_NOT_FOUND", 404, "Rate card not found")
    return rc


@bp.route("/rate-cards", methods=["POST"])
def create_rate_card():
    require_roles("InventoryManager")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    rc = db.new_resource()
    rc.update({
        "market_code": req_str(body, "market_code"),
        "display_type": req_enum(body, "display_type", DISPLAY_TYPES),
        "base_weekly_cents": req_int(body, "base_weekly_cents", 0),
        "illumination_premium_pct": req_num(body, "illumination_premium_pct", 0),
        "traffic_tier_1_threshold": req_int(body, "traffic_tier_1_threshold", 0),
        "traffic_tier_1_uplift_pct": req_num(body, "traffic_tier_1_uplift_pct", 0),
        "traffic_tier_2_threshold": req_int(body, "traffic_tier_2_threshold", 0),
        "traffic_tier_2_uplift_pct": req_num(body, "traffic_tier_2_uplift_pct", 0),
        "status": "DRAFT",
    })
    db.rate_cards[rc["id"]] = rc
    return success(rate_card_out(rc), code=201)


@bp.route("/rate-cards/<rc_id>", methods=["GET"])
def get_rate_card(rc_id):
    require_roles("InventoryManager", "SalesPlanner")
    rc = get_rate_card_or_404(rc_id)
    return success(rate_card_out(rc))


@bp.route("/rate-cards/<rc_id>", methods=["PUT"])
def update_rate_card(rc_id):
    require_roles("InventoryManager")
    rc = get_rate_card_or_404(rc_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    # Family 4: request shape
    expected = body.get("expected_rate_card_version")
    if not is_int(expected):
        raise err_invalid_request(
            "expected_rate_card_version is required and must be an integer")
    new_status = None
    if "status" in body and body["status"] is not None:
        if body["status"] not in ("DRAFT", "PUBLISHED", "RETIRED"):
            raise err_invalid_request("status must be DRAFT, PUBLISHED or RETIRED")
        new_status = body["status"]
    updates = {}
    for field in ("base_weekly_cents", "traffic_tier_1_threshold",
                  "traffic_tier_2_threshold"):
        v = opt_int(body, field, 0)
        if v is not None:
            updates[field] = v
    for field in ("illumination_premium_pct", "traffic_tier_1_uplift_pct",
                  "traffic_tier_2_uplift_pct"):
        v = opt_num(body, field, 0)
        if v is not None:
            updates[field] = v

    # Family 5: state legality + optimistic concurrency
    if rc["status"] == "RETIRED":
        raise err_invalid_state("A RETIRED rate card rejects all mutations")
    if new_status is not None and new_status != rc["status"]:
        allowed = {
            ("DRAFT", "PUBLISHED"), ("DRAFT", "RETIRED"),
            ("PUBLISHED", "RETIRED"),
        }
        if (rc["status"], new_status) not in allowed:
            raise err_invalid_state(
                "Rate card cannot transition %s -> %s" % (rc["status"], new_status))
    if expected != rc["version"]:
        raise err_stale()

    # Publish preconditions (PRD 3.1): tier ordering then uniqueness
    if new_status == "PUBLISHED" and rc["status"] == "DRAFT":
        t1 = updates.get("traffic_tier_1_threshold", rc["traffic_tier_1_threshold"])
        t2 = updates.get("traffic_tier_2_threshold", rc["traffic_tier_2_threshold"])
        if not t2 > t1:
            raise err_invalid_request(
                "traffic_tier_2_threshold must be strictly greater than "
                "traffic_tier_1_threshold")
        for other in db.rate_cards.values():
            if other["id"] != rc["id"] and other["status"] == "PUBLISHED" \
                    and other["market_code"] == rc["market_code"] \
                    and other["display_type"] == rc["display_type"]:
                raise ApiError("ERR_RATE_CARD_DUPLICATE_PUBLISHED", 409,
                               "Another rate card for this market and display "
                               "type is already PUBLISHED")

    for field, v in updates.items():
        rc[field] = v
    if new_status is not None:
        rc["status"] = new_status
    db.touch(rc)
    return success(rate_card_out(rc))


@bp.route("/rate-cards/<rc_id>/flights", methods=["GET"])
def rate_card_flights(rc_id):
    require_roles("InventoryManager", "SalesPlanner")
    rc = get_rate_card_or_404(rc_id)
    items = sort_created([f for f in db.flights.values()
                          if f["rate_card_id"] == rc["id"]])
    page, meta = paginate(items)
    return success([flight_out(f) for f in page], response_type="array",
                   page_meta=meta)
