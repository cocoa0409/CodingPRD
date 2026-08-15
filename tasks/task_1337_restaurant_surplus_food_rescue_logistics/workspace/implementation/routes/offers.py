"""DonationOffer endpoints."""
from datetime import timedelta

from flask import Blueprint

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok
from services import (
    CATEGORIES,
    COLD_CHAIN_CATEGORIES,
    OFFER_STATUSES,
    clock_dt,
    file_strike,
    get_donor,
    get_offer,
    ser_offer,
    stamp,
    touch,
)
from util import (
    as_enum,
    as_int,
    as_iso_dt,
    body,
    parse_dt,
    reject_unknown,
    required,
)

bp = Blueprint("offers", __name__)

MIN_WINDOW_MINUTES = 30
MAX_WINDOW_MINUTES = 240


def _cancel_matched_or_scheduled(offer, actor_role):
    """Teardown for cancelling a committed offer: current run -> CANCELLED with
    the release cascade; a DonorCoordinator actor auto-files a SYSTEM strike."""
    from services import _cancel_run

    run = DB["runs"].get(offer.get("current_run_id") or "")
    if run is not None and run["run_status"] in ("PROPOSED", "CONFIRMED"):
        _cancel_run(run)
        if actor_role == "DonorCoordinator":
            file_strike(
                run["id"], "SYSTEM", None, "DONOR_SITE", offer["donor_site_id"], "OTHER"
            )


@bp.post("/api/donation-offers")
def create_offer():
    user_id, role = auth(["DonorCoordinator"])
    data = body()
    # requires_cold_chain is server-derived; a client-supplied value is ignored.
    reject_unknown(
        data,
        {
            "donor_site_id",
            "food_category",
            "estimated_weight_lbs",
            "pickup_window_start",
            "pickup_window_end",
            "requires_cold_chain",
        },
    )
    donor_site_id = required(data, "donor_site_id")
    if not isinstance(donor_site_id, str) or not donor_site_id:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Field donor_site_id must be a string"
        )
    food_category = as_enum(required(data, "food_category"), "food_category", CATEGORIES)
    estimated_weight_lbs = as_int(
        required(data, "estimated_weight_lbs"), "estimated_weight_lbs", minimum=1
    )
    pickup_window_start = as_iso_dt(
        required(data, "pickup_window_start"), "pickup_window_start"
    )
    pickup_window_end = as_iso_dt(
        required(data, "pickup_window_end"), "pickup_window_end"
    )
    ws = parse_dt(pickup_window_start)
    we = parse_dt(pickup_window_end)
    if we <= ws:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "pickup_window_end must be after pickup_window_start"
        )
    length = (we - ws).total_seconds() / 60
    if length < MIN_WINDOW_MINUTES or length > MAX_WINDOW_MINUTES:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "Pickup window length must be within [30, 240] minutes",
        )
    # Existence + ownership masking: the coordinator may only act for its own
    # donor site; anything else is masked as ERR_DONOR_NOT_FOUND.
    if donor_site_id != user_id:
        raise ApiError("ERR_DONOR_NOT_FOUND", 404, "Donor site not found")
    get_donor(donor_site_id)
    rec = {
        "id": new_id(),
        "donor_site_id": donor_site_id,
        "food_category": food_category,
        "requires_cold_chain": food_category in COLD_CHAIN_CATEGORIES,
        "estimated_weight_lbs": estimated_weight_lbs,
        "pickup_window_start": pickup_window_start,
        "pickup_window_end": pickup_window_end,
        "status": "DRAFT",
        "failed_attempts": 0,
        "current_run_id": None,
    }
    stamp(rec)
    DB["offers"][rec["id"]] = rec
    return ok(ser_offer(rec), status=201)


@bp.get("/api/donation-offers/<oid>")
def get_one_offer(oid):
    user_id, role = auth(["DispatchAdmin", "DonorCoordinator"])
    return ok(ser_offer(get_offer(oid, user_id, role)))


@bp.patch("/api/donation-offers/<oid>/status")
def patch_offer_status(oid):
    user_id, role = auth(["DonorCoordinator", "DispatchAdmin"])
    data = body()
    reject_unknown(data, {"target_status"})
    target = as_enum(required(data, "target_status"), "target_status", OFFER_STATUSES)
    offer = get_offer(oid, user_id, role)
    cur = offer["status"]
    if target == "OPEN":
        if cur != "DRAFT":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION", 409,
                f"Cannot publish an offer in {cur}",
            )
        donor = get_donor(offer["donor_site_id"])
        if donor["status"] != "ACTIVE":
            raise ApiError(
                "ERR_DONOR_NOT_ACTIVE", 409, "Donor site must be ACTIVE to publish"
            )
        if not parse_dt(offer["pickup_window_end"]) > clock_dt():
            raise ApiError(
                "ERR_PICKUP_WINDOW_PAST", 409, "Pickup window end has passed"
            )
        offer["status"] = "OPEN"
        touch(offer)
    elif target == "CANCELLED":
        if cur in ("DRAFT", "OPEN"):
            offer["status"] = "CANCELLED"
            touch(offer)
        elif cur in ("MATCHED", "SCHEDULED"):
            offer["status"] = "CANCELLED"
            touch(offer)
            _cancel_matched_or_scheduled(offer, role)
        else:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION", 409,
                f"Cannot cancel an offer in {cur}",
            )
    else:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409,
            f"Cannot move offer from {cur} to {target}",
        )
    return ok(ser_offer(offer))
