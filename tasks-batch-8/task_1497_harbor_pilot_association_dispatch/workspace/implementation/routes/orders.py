"""Vessel order intake, amendment, cancellation, and dispatch."""
from flask import Blueprint, request

from db import DB, now, touch
from errors import ApiError
from middleware import ANY_ROLE, auth
from response import ok, ok_list
from services import (
    active_schedule,
    assignment_view,
    base_entity,
    demote_entry,
    order_view,
    pilot_rotation_entry,
    restore_entry,
    select_boat,
    select_pilot,
    tariff_provisional_average,
)
from util import (
    body,
    opt_int,
    pagination_args,
    paginate,
    req_dt,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("orders", __name__)

ORDER_TYPES = ("ARRIVAL", "DEPARTURE", "SHIFT")


def _get_order(oid):
    o = DB["vessel_orders"].get(oid)
    if o is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Vessel order does not exist")
    return o


def _check_eta_future(eta):
    """ETA must be strictly after the logical clock (priority 18)."""
    if eta <= now():
        raise ApiError(
            "ERR_ETA_IN_PAST", 422, "eta must be strictly after the logical clock"
        )


@bp.post("/pilotage/vessel-orders")
def create_order():
    user_id, _ = auth(["VesselAgent"])
    data = body()

    # Temporal check (priority 18) precedes the structural catch-all (23), but
    # eta must be structurally parseable before it can be compared.
    eta = req_dt(data, "eta")
    _check_eta_future(eta)

    vessel_name = req_str(data, "vessel_name")
    gt = req_int(data, "gt", minimum=1)
    draft_dm = req_int(data, "draft_dm", minimum=1)
    order_type = req_enum(data, "order_type", ORDER_TYPES)

    # Pin the ACTIVE tariff schedule and price the provisional (average-rate)
    # fee over the declared gt/draft. Client-supplied tariff_schedule_id and
    # provisional_fee_cents are ignored (system/computed fields).
    schedule = active_schedule()
    provisional = (
        tariff_provisional_average(schedule, gt, draft_dm) if schedule else None
    )

    order = base_entity()
    order.update(
        {
            "agent_id": user_id,
            "vessel_name": vessel_name,
            "gt": gt,
            "draft_dm": draft_dm,
            "order_type": order_type,
            "eta": eta,
            "tariff_schedule_id": schedule["id"] if schedule else None,
            "provisional_fee_cents": provisional,
            "status": "BOOKED",
        }
    )
    DB["vessel_orders"][order["id"]] = order
    return ok(order_view(order), status=201)


@bp.get("/pilotage/vessel-orders")
def list_orders():
    auth(ANY_ROLE)
    limit, offset = pagination_args()
    status = request.args.get("status")
    schedule_id = request.args.get("tariff_schedule_id")
    items = list(DB["vessel_orders"].values())
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if schedule_id is not None:
        items = [o for o in items if o["tariff_schedule_id"] == schedule_id]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list([order_view(o) for o in page], total, limit, offset)


@bp.get("/pilotage/vessel-orders/<oid>")
def get_order(oid):
    auth(ANY_ROLE)
    return ok(order_view(_get_order(oid)))


@bp.patch("/pilotage/vessel-orders/<oid>")
def patch_order(oid):
    user_id, _ = auth(["VesselAgent"])
    order = _get_order(oid)

    # Ownership (priority 2) precedes the OCC check (priority 4).
    if order["agent_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "VesselAgent may amend only its own orders"
        )

    data = body()
    expected = data.get("expected_order_version")
    if (
        isinstance(expected, int)
        and not isinstance(expected, bool)
        and expected != order["version"]
    ):
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_order_version differs from the order's current version",
        )

    # Amendment is allowed only while the order is BOOKED (priority 6).
    if order["status"] != "BOOKED":
        raise ApiError(
            "ERR_ORDER_LOCKED", 409, "Order may be amended only while BOOKED"
        )

    # ETA temporal rule (priority 18) precedes structural catch-all (23).
    new_eta = None
    if "eta" in data and data["eta"] is not None:
        new_eta = req_dt(data, "eta")
        _check_eta_future(new_eta)

    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "Missing or invalid required field: expected_order_version",
        )
    new_gt = opt_int(data, "gt", minimum=1)
    new_draft = opt_int(data, "draft_dm", minimum=1)

    if new_eta is not None:
        order["eta"] = new_eta
    if new_gt is not None:
        order["gt"] = new_gt
    if new_draft is not None:
        order["draft_dm"] = new_draft

    # A successful amendment re-pins the ACTIVE schedule and recomputes the
    # provisional fee whenever gt or draft_dm was supplied.
    schedule = active_schedule()
    order["tariff_schedule_id"] = schedule["id"] if schedule else None
    if new_gt is not None or new_draft is not None:
        order["provisional_fee_cents"] = (
            tariff_provisional_average(schedule, order["gt"], order["draft_dm"])
            if schedule
            else None
        )
    touch(order)
    return ok(order_view(order))


@bp.post("/pilotage/vessel-orders/<oid>/cancel")
def cancel_order(oid):
    user_id, _ = auth(["VesselAgent"])
    order = _get_order(oid)
    if order["agent_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "VesselAgent may cancel only its own orders"
        )
    if order["status"] not in ("BOOKED", "DISPATCHED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Order cannot be cancelled from {order['status']}",
        )

    if order["status"] == "DISPATCHED":
        # Cascade hop 1: the order's non-terminal assignment -> CANCELLED.
        # Hop 2 side effects of that cancellation are state-dependent (PRD
        # 3.5): from ASSIGNED the pilot's board slot is restored; from
        # RECALLED only the boat interval is released (implicit, since the
        # assignment leaves the open-state set).
        assignment = _non_terminal_assignment(order["id"])
        if assignment is not None:
            if assignment["service_status"] == "ASSIGNED":
                entry = pilot_rotation_entry(assignment["pilot_id"])
                if entry is not None:
                    restore_entry(entry)
            assignment["service_status"] = "CANCELLED"
            touch(assignment)
        # Cascaded from the order cancel: the order proceeds to CANCELLED
        # (it does NOT revert to BOOKED).
    order["status"] = "CANCELLED"
    touch(order)
    return ok(order_view(order))


def _non_terminal_assignment(order_id):
    for a in DB["assignments"].values():
        if a["order_id"] == order_id and a["service_status"] not in (
            "COMPLETED",
            "CANCELLED",
        ):
            return a
    return None


@bp.post("/pilotage/vessel-orders/<oid>/dispatch")
def dispatch_order(oid):
    auth(["Dispatcher"])
    order = _get_order(oid)
    data = body()

    # Existence of body-referenced ids (priority 3) precedes selector logic.
    boat = None
    if data.get("boat_id") is not None:
        boat = DB["pilot_boats"].get(data["boat_id"])
        if boat is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Pilot boat does not exist")
    apprentice = None
    if data.get("apprentice_id") is not None:
        apprentice = DB["apprentices"].get(data["apprentice_id"])
        if apprentice is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Apprentice does not exist")

    # Dispatch is legal only while the order is BOOKED (priority 7).
    if order["status"] != "BOOKED":
        raise ApiError(
            "ERR_ORDER_NOT_DISPATCHABLE",
            409,
            "Order may be dispatched only while BOOKED",
        )

    # The planned window is required to evaluate the selector pools.
    scheduled_start = req_dt(data, "scheduled_start")
    scheduled_end = req_dt(data, "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "scheduled_end must be strictly after scheduled_start",
        )

    # Selector pool emptiness: pilot (priority 13) before boat (priority 14).
    # An empty pool rejects the dispatch with no partial write.
    pilot = select_pilot(order, scheduled_start, scheduled_end)
    if pilot is None:
        raise ApiError(
            "ERR_NO_ELIGIBLE_PILOT", 422, "No eligible pilot for this dispatch"
        )
    if boat is None:
        boat = select_boat(scheduled_start, scheduled_end)
        if boat is None:
            raise ApiError(
                "ERR_NO_ELIGIBLE_BOAT", 422, "No eligible pilot boat for this dispatch"
            )

    # Apprentice gating (priority 17).
    if apprentice is not None and apprentice["status"] != "ENROLLED":
        raise ApiError(
            "ERR_APPRENTICE_NOT_ENROLLED",
            422,
            "Riding apprentice must be ENROLLED",
        )

    assignment = base_entity()
    assignment.update(
        {
            "order_id": order["id"],
            "pilot_id": pilot["id"],
            "boat_id": boat["id"],
            "apprentice_id": apprentice["id"] if apprentice else None,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "actual_start": None,
            "actual_end": None,
            "detention_minutes": None,
            "delay_minutes": None,
            "service_status": "ASSIGNED",
            "billing_status": "UNBILLED",
            "recall_count": 0,
        }
    )
    DB["assignments"][assignment["id"]] = assignment

    order["status"] = "DISPATCHED"
    touch(order)

    # The selected pilot is demoted to the bottom of the board; the prior
    # slot is recorded so a later cancellation can restore it.
    entry = pilot_rotation_entry(pilot["id"])
    if entry is not None:
        demote_entry(entry)

    return ok(assignment_view(assignment), status=201)
