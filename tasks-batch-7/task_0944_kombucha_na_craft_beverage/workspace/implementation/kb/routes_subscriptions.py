"""Subscriptions, pause windows, skips and box allocations."""

from decimal import Decimal
from flask import Blueprint

from . import constants as C
from . import lookup
from .auth import authorize, subscriber_owns
from .calc import (
    fefo_candidates,
    lot_shelf_ok,
    lot_units_available,
    recompute_completed_cycles,
    subscription_cycle_charge,
    subscription_skip_credit,
)
from .cascades import deplete_lot_if_empty
from .envelope import list_response, object_response
from .errors import ApiError
from .routes_recipes import require_id
from .store import base_record, collection_sorted, db, touch
from .util import add_days, age_at_least, dec, normalise_date, round2
from .validate import (
    body_dict,
    field,
    pagination,
    paginate,
    parse_body,
    query_enum,
    query_string,
)

bp = Blueprint("subscriptions", __name__)

SUBSCRIPTION_STATUSES = ("ACTIVE", "PAUSED", "CANCELLED")
ALLOCATION_STATUSES = ("ALLOCATED", "SHIPPED", "REVERSED")


def allocations_of(subscription_id):
    return collection_sorted(
        db.subscription_allocations, lambda a: a["subscription_id"] == subscription_id
    )


@bp.post("/subscriptions")
def create_subscription():
    authorize("PlatformAdmin")
    payload = body_dict()
    recipe = lookup.recipe(require_id(payload, "preferred_recipe_id"))
    data = parse_body(
        payload,
        [
            field("subscriber_email", "string", required=True),
            field("subscriber_birth_date", "datetime", required=True),
            field("preferred_recipe_id", "string", required=True),
        ],
    )
    clash = any(
        s["subscriber_email"] == data["subscriber_email"]
        and s["status"] in ("ACTIVE", "PAUSED")
        for s in db.subscriptions.values()
    )
    if clash:
        raise ApiError(
            "ERR_VALIDATION",
            "subscriber_email is already held by an ACTIVE or PAUSED subscription.",
        )

    record = base_record()
    record.update(
        {
            "subscriber_email": data["subscriber_email"],
            "subscriber_birth_date": data["subscriber_birth_date"],
            "preferred_recipe_id": recipe["id"],
            "status": "ACTIVE",
            "completed_cycles": 0,
            "skips_used_this_year": 0,
            "pause_windows": [],
            "current_pause_start_date": None,
            "current_pause_end_date": None,
            "cycle_start_date": db.clock,
            "cycle_index": 1,
            "next_cycle_charge": Decimal("0.00"),
            "credit_balance": Decimal("0.00"),
            "age_verified": False,
        }
    )
    record["next_cycle_charge"] = subscription_cycle_charge(record)
    db.subscriptions[record["id"]] = record
    return object_response(record, 201)


@bp.post("/subscriptions/<id>/pause")
def pause_subscription(id):
    user_id, role = authorize("Subscriber", "PlatformAdmin")
    subscriber_owns(user_id, role, id)
    subscription = lookup.subscription(id)
    payload = body_dict()
    data = parse_body(
        payload,
        [
            field("start_date", "datetime", required=True),
            field("end_date", "datetime", required=True),
        ],
    )
    start = normalise_date(data["start_date"])
    end = normalise_date(data["end_date"])
    if end < start:
        raise ApiError("ERR_VALIDATION", "end_date must be on or after start_date.")
    if subscription["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE subscription may pause.")

    span_days = (end.date() - start.date()).days + 1
    if span_days > C.SUBSCRIPTION_PAUSE_MAX_DAYS:
        raise ApiError(
            "ERR_PAUSE_WINDOW_CONFLICT",
            "A pause may span at most %d days." % C.SUBSCRIPTION_PAUSE_MAX_DAYS,
        )
    for window in subscription["pause_windows"]:
        if start <= window["end_date"] and window["start_date"] <= end:
            raise ApiError(
                "ERR_PAUSE_WINDOW_CONFLICT",
                "The requested pause interval intersects a recorded one.",
            )

    subscription["status"] = "PAUSED"
    subscription["current_pause_start_date"] = start
    subscription["current_pause_end_date"] = end
    subscription["next_cycle_charge"] = subscription_cycle_charge(subscription)
    touch(subscription)
    return object_response(subscription)


@bp.post("/subscriptions/<id>/resume")
def resume_subscription(id):
    user_id, role = authorize("Subscriber", "PlatformAdmin")
    subscriber_owns(user_id, role, id)
    subscription = lookup.subscription(id)
    body_dict()
    if subscription["status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE", "Only a PAUSED subscription may resume.")

    subscription["pause_windows"].append(
        {
            "start_date": subscription["current_pause_start_date"],
            "end_date": subscription["current_pause_end_date"],
        }
    )
    subscription["current_pause_start_date"] = None
    subscription["current_pause_end_date"] = None
    subscription["status"] = "ACTIVE"
    subscription["next_cycle_charge"] = subscription_cycle_charge(subscription)
    touch(subscription)
    return object_response(subscription)


@bp.post("/subscriptions/<id>/skip")
def skip_cycle(id):
    user_id, role = authorize("Subscriber", "PlatformAdmin")
    subscriber_owns(user_id, role, id)
    subscription = lookup.subscription(id)
    body_dict()
    if subscription["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE subscription may skip.")
    if int(subscription["skips_used_this_year"]) >= C.SUBSCRIPTION_SKIP_CAP_PER_YEAR:
        raise ApiError(
            "ERR_SUBSCRIPTION_SKIP_CAP",
            "The annual skip cap of %d has been reached."
            % C.SUBSCRIPTION_SKIP_CAP_PER_YEAR,
        )
    if any(
        a["cycle_index"] == subscription["cycle_index"] and a["status"] == "ALLOCATED"
        for a in allocations_of(subscription["id"])
    ):
        raise ApiError(
            "ERR_SUBSCRIPTION_SKIP_CAP",
            "An allocation for the current cycle is still ALLOCATED.",
        )

    credit = subscription_skip_credit(subscription)
    subscription["skips_used_this_year"] = int(subscription["skips_used_this_year"]) + 1
    subscription["cycle_index"] = int(subscription["cycle_index"]) + 1
    subscription["cycle_start_date"] = add_days(
        subscription["cycle_start_date"], C.SUBSCRIPTION_CYCLE_DAYS
    )
    subscription["credit_balance"] = round2(
        dec(subscription["credit_balance"]) + credit
    )
    subscription["next_cycle_charge"] = subscription_cycle_charge(subscription)
    touch(subscription)
    return object_response(subscription)


@bp.post("/subscriptions/<id>/cancel")
def cancel_subscription(id):
    user_id, role = authorize("Subscriber", "PlatformAdmin")
    subscriber_owns(user_id, role, id)
    subscription = lookup.subscription(id)
    payload = body_dict()
    parse_body(payload, [field("reason", "string")])
    if subscription["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError(
            "ERR_INVALID_STATE", "Only an ACTIVE or PAUSED subscription may cancel."
        )

    for allocation in allocations_of(subscription["id"]):
        if allocation["status"] != "ALLOCATED":
            continue
        allocation["status"] = "REVERSED"
        allocation["reversal_reason"] = "SUBSCRIPTION_CANCELLED"
        touch(allocation)
        lot = db.finished_lots.get(allocation["finished_lot_id"])
        if lot is not None:
            lot["reserved_units"] = max(
                0, int(lot["reserved_units"]) - int(allocation["units"])
            )
            touch(lot)

    subscription["status"] = "CANCELLED"
    touch(subscription)
    return object_response(subscription)


@bp.get("/subscriptions/<id>")
def read_subscription(id):
    user_id, role = authorize("Subscriber", "SalesRep", "PlatformAdmin")
    subscriber_owns(user_id, role, id)
    return object_response(lookup.subscription(id))


@bp.get("/subscriptions")
def list_subscriptions():
    authorize("SalesRep", "PlatformAdmin")
    status = query_enum("status", SUBSCRIPTION_STATUSES)
    preferred_recipe_id = query_string("preferred_recipe_id")
    limit, offset = pagination()

    def keep(s):
        if status is not None and s["status"] != status:
            return False
        if (
            preferred_recipe_id is not None
            and s["preferred_recipe_id"] != preferred_recipe_id
        ):
            return False
        return True

    rows = collection_sorted(db.subscriptions, keep)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/subscriptions/<id>/allocations")
def list_subscription_allocations(id):
    user_id, role = authorize("Subscriber", "SalesRep", "PlatformAdmin")
    subscriber_owns(user_id, role, id)
    subscription = lookup.subscription(id)
    status = query_enum("status", ALLOCATION_STATUSES)
    limit, offset = pagination()
    rows = collection_sorted(
        db.subscription_allocations,
        lambda a: a["subscription_id"] == subscription["id"]
        and (status is None or a["status"] == status),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------- allocations


def _select_fefo_lot(subscription):
    released = fefo_candidates(subscription["preferred_recipe_id"])
    eligible = [
        lot
        for lot in released
        if lot_units_available(lot) >= C.SUBSCRIPTION_BOX_UNITS and lot_shelf_ok(lot)
    ]
    if eligible:
        return eligible[0]
    if released and all(
        (not lot_shelf_ok(lot))
        and lot_units_available(lot) >= C.SUBSCRIPTION_BOX_UNITS
        for lot in released
    ):
        raise ApiError(
            "ERR_SHELF_LIFE_TOO_SHORT",
            "Every released lot of this recipe is too close to its best-by date.",
        )
    raise ApiError(
        "ERR_INSUFFICIENT_LOT_UNITS",
        "No released lot of this recipe has six uncommitted units.",
    )


@bp.post("/subscription-allocations")
def create_allocation():
    authorize("PlatformAdmin")
    payload = body_dict()

    subscription = lookup.subscription(require_id(payload, "subscription_id"))
    explicit_lot = None
    raw_lot = payload.get("finished_lot_id")
    if isinstance(raw_lot, str) and raw_lot.strip():
        explicit_lot = lookup.finished_lot(raw_lot)

    data = parse_body(
        payload,
        [
            field("subscription_id", "string", required=True),
            field("cycle_index", "integer", required=True),
            field("expected_finished_lot_version", "integer", required=True),
            field("finished_lot_id", "string"),
        ],
    )
    cycle_index = int(data["cycle_index"])
    if any(
        a["cycle_index"] == cycle_index and a["status"] in ("ALLOCATED", "SHIPPED")
        for a in allocations_of(subscription["id"])
    ):
        raise ApiError(
            "ERR_VALIDATION",
            "cycle_index is already taken by an ALLOCATED or SHIPPED allocation.",
        )

    if subscription["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an ACTIVE subscription may take a box."
        )

    lot = explicit_lot if explicit_lot is not None else _select_fefo_lot(subscription)

    if int(data["expected_finished_lot_version"]) != int(lot["version"]):
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_finished_lot_version does not match the lot's current version.",
        )
    if lot["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE", "Only a RELEASED lot may back a box.")
    if lot["recipe_id"] != subscription["preferred_recipe_id"]:
        raise ApiError(
            "ERR_VALIDATION",
            "The lot's recipe does not match the subscription's preferred recipe.",
        )
    if not lot_shelf_ok(lot):
        raise ApiError(
            "ERR_SHELF_LIFE_TOO_SHORT",
            "The lot's best_by_date leaves too little shelf life.",
        )
    age_applied = lot["abv_class"] == "ALCOHOLIC"
    if age_applied and not age_at_least(
        subscription["subscriber_birth_date"],
        db.clock,
        C.AGE_VERIFICATION_MIN_AGE_YEARS,
    ):
        raise ApiError(
            "ERR_AGE_VERIFICATION_REQUIRED",
            "An alcoholic box needs a subscriber of at least %d years."
            % C.AGE_VERIFICATION_MIN_AGE_YEARS,
        )
    if lot_units_available(lot) < C.SUBSCRIPTION_BOX_UNITS:
        raise ApiError(
            "ERR_INSUFFICIENT_LOT_UNITS",
            "The lot has fewer than %d uncommitted units." % C.SUBSCRIPTION_BOX_UNITS,
        )

    record = base_record()
    record.update(
        {
            "subscription_id": subscription["id"],
            "finished_lot_id": lot["id"],
            "cycle_index": cycle_index,
            "units": C.SUBSCRIPTION_BOX_UNITS,
            "status": "ALLOCATED",
            "reversal_reason": None,
            "reallocation_attempt_count": 0,
            "charge_amount": round2(subscription["next_cycle_charge"]),
        }
    )
    db.subscription_allocations[record["id"]] = record

    lot["reserved_units"] = int(lot["reserved_units"]) + C.SUBSCRIPTION_BOX_UNITS
    touch(lot)

    if age_applied:
        subscription["age_verified"] = True
    touch(subscription)

    return object_response(record, 201)


@bp.post("/subscription-allocations/<id>/ship")
def ship_allocation(id):
    authorize("PlatformAdmin")
    allocation = lookup.subscription_allocation(id)
    body_dict()
    if allocation["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE", "Only an ALLOCATED box may be shipped.")

    units = int(allocation["units"])
    lot = db.finished_lots.get(allocation["finished_lot_id"])
    allocation["status"] = "SHIPPED"
    touch(allocation)

    if lot is not None:
        lot["reserved_units"] = max(0, int(lot["reserved_units"]) - units)
        lot["on_hand_units"] = int(lot["on_hand_units"]) - units
        lot["shipped_units"] = int(lot["shipped_units"]) + units
        deplete_lot_if_empty(lot)
        touch(lot)

    subscription = db.subscriptions.get(allocation["subscription_id"])
    if subscription is not None:
        recompute_completed_cycles(subscription)
        subscription["next_cycle_charge"] = subscription_cycle_charge(subscription)
        touch(subscription)

    return object_response(allocation)
