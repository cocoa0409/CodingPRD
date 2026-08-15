"""Charter inquiries: open, quote (OCC), counter, accept, decline, convert."""
from flask import Blueprint, request

import clock
import db
from errors import ApiError, err_invalid_request, err_invalid_state
from response import ok
from services import core as svc
from util import require_auth, get_json, paginate, get_or_404, touch

bp = Blueprint("charter", __name__)

AGENT = ["CharterSalesAgent"]
CUSTOMER = ["Customer"]
OM = ["OperationsManager"]
READ = ["OperationsManager", "CharterSalesAgent", "Customer"]

INQUIRY_STATUSES = ["DRAFT", "QUOTED", "COUNTERED", "ACCEPTED", "CONVERTED", "DECLINED", "EXPIRED"]


@bp.post("/charter-inquiries")
def create_inquiry():
    require_auth(AGENT)
    body = get_json(required_fields=["cruise_id", "customer_id"])
    cruise_id = body["cruise_id"]
    customer_id = body["customer_id"]
    if not isinstance(cruise_id, str) or not isinstance(customer_id, str):
        raise err_invalid_request("cruise_id and customer_id must be strings")
    cruise = db.cruises.get(cruise_id)
    if cruise is None:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS["cruise"], "Cruise not found")
    customer = db.customers.get(customer_id)
    if customer is None:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS["customer"], "Customer not found")
    now_z = clock.to_z(clock.now())
    inquiry = {
        "id": db.new_id(), "created_at": now_z, "updated_at": now_z, "version": 1,
        "cruise_id": cruise["id"], "customer_id": customer["id"],
        "quoted_total_cents": None,
        "quote_round": 0,
        "status": "DRAFT",
        "quoted_at_dt": None,
        "accepted_by_user_id": None,
    }
    db.insert(db.inquiries, inquiry)
    return ok(_serialize(inquiry), status=201)


def _serialize(inq):
    out = {k: v for k, v in inq.items() if k in ("id", "created_at", "updated_at", "version", "cruise_id", "customer_id", "quoted_total_cents", "quote_round", "status")}
    return out


@bp.get("/charter-inquiries")
def list_inquiries():
    require_auth(READ)
    status_filter = request.args.get("status")
    cruise_filter = request.args.get("cruise_id")
    customer_filter = request.args.get("customer_id")
    if status_filter is not None and status_filter not in INQUIRY_STATUSES:
        raise err_invalid_request("Invalid value for status")
    items = list(db.inquiries.values())
    if status_filter is not None:
        items = [i for i in items if i["status"] == status_filter]
    if cruise_filter is not None:
        items = [i for i in items if i["cruise_id"] == cruise_filter]
    if customer_filter is not None:
        items = [i for i in items if i["customer_id"] == customer_filter]
    items.sort(key=lambda i: i["created_at"])
    page, meta = paginate(items)
    return ok([_serialize(i) for i in page], pagination=meta)


@bp.get("/charter-inquiries/<iid>")
def get_inquiry(iid):
    require_auth(READ)
    inquiry = get_or_404(db.inquiries, iid, "inquiry", "Charter inquiry not found")
    return ok(_serialize(inquiry))


@bp.post("/charter-inquiries/<iid>/quote")
def quote_inquiry(iid):
    uid, _ = require_auth(AGENT)
    body = get_json(required_fields=["expected_inquiry_version"])
    expected = body["expected_inquiry_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_inquiry_version must be an integer")
    inquiry = get_or_404(db.inquiries, iid, "inquiry", "Charter inquiry not found")
    if inquiry["status"] not in ("DRAFT", "COUNTERED"):
        raise err_invalid_state("Inquiry is not quotable in its current state")
    cruise = db.cruises[inquiry["cruise_id"]]
    if cruise["status"] != "SCHEDULED":
        raise ApiError("ERR_CRUISE_NOT_BOOKABLE", 409, "Cruise is not SCHEDULED")
    # Rung 10: rounds cap applies to the re-quote from COUNTERED, not the opening quote
    if inquiry["status"] == "COUNTERED" and inquiry["quote_round"] >= svc.MAX_QUOTE_ROUNDS:
        raise ApiError("ERR_QUOTE_ROUNDS_EXHAUSTED", 409, "Charter negotiation rounds exhausted")
    # Rung 13: segregation of duties — quote poster must differ from the counter poster
    if inquiry.get("last_actor_user_id") is not None and inquiry["last_actor_user_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Quote poster must differ from the counter poster")
    # Rung 14: OCC on the inquiry
    if expected != inquiry["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_inquiry_version is stale")
    inquiry["quoted_total_cents"] = svc.compute_charter_quote(cruise)
    inquiry["quote_round"] += 1
    inquiry["status"] = "QUOTED"
    inquiry["quoted_at_dt"] = clock.now()
    inquiry["last_actor_user_id"] = uid
    touch(inquiry)
    return ok(_serialize(inquiry))


@bp.post("/charter-inquiries/<iid>/counter")
def counter_inquiry(iid):
    uid, _ = require_auth(CUSTOMER)
    get_json()
    inquiry = get_or_404(db.inquiries, iid, "inquiry", "Charter inquiry not found")
    if inquiry["status"] != "QUOTED":
        raise err_invalid_state("Inquiry is not QUOTED")
    if inquiry["quote_round"] >= svc.MAX_QUOTE_ROUNDS:
        raise ApiError("ERR_QUOTE_ROUNDS_EXHAUSTED", 409, "Charter negotiation rounds exhausted")
    if inquiry.get("last_actor_user_id") is not None and inquiry["last_actor_user_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Counter poster must differ from the quote poster")
    inquiry["status"] = "COUNTERED"
    inquiry["quote_round"] += 1
    inquiry["last_actor_user_id"] = uid
    touch(inquiry)
    return ok(_serialize(inquiry))


@bp.post("/charter-inquiries/<iid>/accept")
def accept_inquiry(iid):
    uid, _ = require_auth(CUSTOMER)
    get_json()
    inquiry = get_or_404(db.inquiries, iid, "inquiry", "Charter inquiry not found")
    if inquiry["status"] != "QUOTED":
        raise err_invalid_state("Inquiry is not QUOTED")
    inquiry["status"] = "ACCEPTED"
    inquiry["accepted_by_user_id"] = uid
    touch(inquiry)
    return ok(_serialize(inquiry))


@bp.post("/charter-inquiries/<iid>/decline")
def decline_inquiry(iid):
    require_auth(CUSTOMER)
    get_json()
    inquiry = get_or_404(db.inquiries, iid, "inquiry", "Charter inquiry not found")
    if inquiry["status"] not in ("QUOTED", "COUNTERED"):
        raise err_invalid_state("Inquiry is not QUOTED or COUNTERED")
    inquiry["status"] = "DECLINED"
    touch(inquiry)
    return ok(_serialize(inquiry))


@bp.post("/charter-inquiries/<iid>/convert")
def convert_inquiry(iid):
    uid, _ = require_auth(OM)
    get_json()
    inquiry = get_or_404(db.inquiries, iid, "inquiry", "Charter inquiry not found")
    if inquiry["status"] != "ACCEPTED":
        raise err_invalid_state("Inquiry is not ACCEPTED")
    cruise = db.cruises[inquiry["cruise_id"]]
    if cruise["status"] != "SCHEDULED":
        raise ApiError("ERR_CRUISE_NOT_BOOKABLE", 409, "Cruise is not SCHEDULED")
    # Rung 13: converting OperationsManager must differ from the accepting Customer
    if inquiry.get("accepted_by_user_id") == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Converting operator must differ from the accepting customer")
    svc.charter_convert_cascade(inquiry, cruise)
    return ok(_serialize(inquiry))
