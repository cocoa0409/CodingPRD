"""ServiceOrder endpoints."""
from flask import request

from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth, require_shipper_party
from response import ok, ok_list
from services import (
    apply_expiry_sweep_to_agreement,
    get_agreement_or_404,
    mint_common_fields,
    touch,
)
from util import (
    as_enum,
    as_int,
    as_iso_date,
    as_non_negative_int,
    as_str,
    body,
    day_of_week_code,
    pagination_args,
    parse_ymd,
    required,
)

ORDER_TYPES = {"SWITCHING", "MAINTENANCE_POSSESSION"}


def _get_order_or_404(order_id):
    o = DB["service_orders"].get(order_id)
    if o is None:
        raise ApiError("ERR_SERVICE_ORDER_NOT_FOUND", 404, "ServiceOrder not found")
    return o


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap check."""
    return a_start < b_end and b_start < a_end


def register(app):
    @app.route("/service-orders", methods=["POST"])
    def create_order():
        user_id, role = auth(["ShipperFacilityManager"])
        data = body()
        agreement_id = as_str(required(data, "agreement_id"), "agreement_id")
        segment_id = as_str(required(data, "segment_id"), "segment_id")
        order_type = as_enum(required(data, "order_type"), "order_type", ORDER_TYPES)
        service_date = as_iso_date(required(data, "service_date"), "service_date")
        start_hour = as_int(required(data, "start_hour"), "start_hour")
        end_hour = as_int(required(data, "end_hour"), "end_hour")

        agreement = get_agreement_or_404(agreement_id)
        apply_expiry_sweep_to_agreement(agreement)
        segment = DB["segments"].get(segment_id)
        if segment is None:
            raise ApiError("ERR_SEGMENT_NOT_FOUND", 404, "TrackSegment not found")
        require_shipper_party(user_id, agreement)

        # Body shape
        if start_hour < 0 or start_hour > 23:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "start_hour must be between 0 and 23"
            )
        if end_hour < 1 or end_hour > 24:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "end_hour must be between 1 and 24"
            )
        if end_hour <= start_hour:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "end_hour must be greater than start_hour"
            )

        # Cross-entity: agreement must be ACTIVE (priority 7)
        if agreement["status"] != "ACTIVE":
            raise ApiError(
                "ERR_AGREEMENT_NOT_ACTIVE", 409, "Parent agreement must be ACTIVE"
            )

        # Segment safety gates (priority 8): in-service, then suspension
        if segment["status"] != "IN_SERVICE":
            raise ApiError(
                "ERR_SEGMENT_OUT_OF_SERVICE",
                409,
                "Segment must be IN_SERVICE",
            )
        if segment.get("safety_suspended"):
            raise ApiError(
                "ERR_SEGMENT_SAFETY_SUSPENDED",
                409,
                "Segment is safety-suspended",
            )

        # Temporal (priority 9): SWITCHING only on service days
        if order_type == "SWITCHING":
            dow = day_of_week_code(parse_ymd(service_date))
            if dow not in agreement["service_days_of_week"]:
                raise ApiError(
                    "ERR_NOT_A_SERVICE_DAY",
                    409,
                    "Service date is not a scheduled service day",
                )

        # Frequency / overlap / buffer checks (priority 10)
        same_day_orders = [
            o
            for o in DB["service_orders"].values()
            if o.get("segment_id") == segment["id"]
            and o.get("service_date") == service_date
            and o.get("status") != "CANCELLED"
        ]

        if order_type == "MAINTENANCE_POSSESSION":
            # Possession-vs-possession overlap (half-open)
            for o in same_day_orders:
                if o["order_type"] != "MAINTENANCE_POSSESSION":
                    continue
                if _windows_overlap(
                    start_hour, end_hour, o["start_hour"], o["end_hour"]
                ):
                    raise ApiError(
                        "ERR_POSSESSION_OVERLAP",
                        409,
                        "Maintenance possession window overlaps an existing possession",
                    )
            # Possession vs switching with 1-hour buffer on both sides
            for o in same_day_orders:
                if o["order_type"] != "SWITCHING":
                    continue
                if _windows_overlap(
                    start_hour - 1, end_hour + 1, o["start_hour"], o["end_hour"]
                ):
                    raise ApiError(
                        "ERR_POSSESSION_BUFFER_CONFLICT",
                        409,
                        "Maintenance possession conflicts with switching window (1-hour buffer)",
                    )
        else:  # SWITCHING
            # Switching vs possessions with 1-hour buffer
            for o in same_day_orders:
                if o["order_type"] != "MAINTENANCE_POSSESSION":
                    continue
                if _windows_overlap(
                    start_hour, end_hour, o["start_hour"] - 1, o["end_hour"] + 1
                ):
                    raise ApiError(
                        "ERR_POSSESSION_BUFFER_CONFLICT",
                        409,
                        "Switching window conflicts with a possession (1-hour buffer)",
                    )
            # Switching frequency cap
            switching_count = sum(
                1 for o in same_day_orders if o["order_type"] == "SWITCHING"
            )
            if switching_count >= int(agreement["max_switches_per_day"]):
                raise ApiError(
                    "ERR_SWITCH_LIMIT_EXCEEDED",
                    409,
                    "max_switches_per_day reached for this segment and date",
                )

        # Cross-FK consistency (priority 11): segment must belong to agreement
        if segment.get("agreement_id") != agreement["id"]:
            raise ApiError(
                "ERR_CROSS_REFERENCE_MISMATCH",
                422,
                "segment_id does not belong to agreement_id",
            )

        order = {
            "agreement_id": agreement["id"],
            "segment_id": segment["id"],
            "order_type": order_type,
            "service_date": service_date,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "cars_spotted": None,
            "cars_pulled": None,
            "status": "REQUESTED",
        }
        mint_common_fields(order)
        DB["service_orders"][order["id"]] = order
        return ok(order, 201)

    @app.route("/service-orders", methods=["GET"])
    def list_orders():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        agreement_id = request.args.get("agreement_id")
        segment_id = request.args.get("segment_id")
        service_date = request.args.get("service_date")
        items = list(DB["service_orders"].values())
        if agreement_id is not None:
            items = [o for o in items if o.get("agreement_id") == agreement_id]
        if segment_id is not None:
            items = [o for o in items if o.get("segment_id") == segment_id]
        if service_date is not None:
            items = [o for o in items if o.get("service_date") == service_date]
        items.sort(key=lambda x: (x["created_at"], x["id"]))
        total = len(items)
        return ok_list(items[offset : offset + limit], total, limit, offset)

    @app.route("/service-orders/<orderId>", methods=["GET"])
    def get_order(orderId):
        auth(ALL_ROLES)
        return ok(_get_order_or_404(orderId))

    @app.route("/service-orders/<orderId>/complete", methods=["POST"])
    def complete_order(orderId):
        auth(["RailroadServiceManager"])
        o = _get_order_or_404(orderId)
        data = body()
        cars_spotted = as_non_negative_int(
            required(data, "cars_spotted"), "cars_spotted"
        )
        cars_pulled = as_non_negative_int(required(data, "cars_pulled"), "cars_pulled")
        if o["status"] != "REQUESTED":
            raise ApiError(
                "ERR_ORDER_INVALID_STATE", 409, "Order must be REQUESTED to complete"
            )
        o["cars_spotted"] = cars_spotted
        o["cars_pulled"] = cars_pulled
        o["status"] = "COMPLETED"
        touch(o)
        return ok(o)
