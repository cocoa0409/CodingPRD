"""Marketing allocations and event settlement (PRD 3.9)."""
from db import clock_raw, db, new_row, touch
from errors import fail
from middleware import (
    ROLE_FINANCE_CONTROLLER,
    ROLE_SERIES_PROMOTER,
    ROLE_VENUE_MANAGER,
    auth,
    enum_filter,
    pagination,
)
from response import list_response, object_response
from services import calc, derive, flow, serialize
import validate

CHANNELS = ("RADIO", "DIGITAL", "GRASSROOTS")
ALLOCATION_STATES = ("COMMITTED", "RELEASED")


def register(app):
    # ------------------------------------------------------ marketing spend
    @app.route("/tour-stops/<stop_id>/marketing-allocations", methods=["POST"])
    def create_allocation(stop_id):
        auth(ROLE_SERIES_PROMOTER)
        payload = validate.body()
        channel = validate.field_enum(payload, "channel", CHANNELS)
        amount = validate.field_int(payload, "amount_cents", minimum=1)
        expected_version = validate.field_int(payload, "expected_season_version")

        stop = derive.get_stop(stop_id)
        season = derive.season_of_stop(stop)
        if expected_version != season["version"]:
            fail("ERR_STALE_SEASON_VERSION")

        flow.ensure_stop_writable(stop)
        flow.ensure_not_frozen(stop)

        channel_total = sum(
            a["amount_cents"]
            for a in derive.allocations_of_stop(stop["id"])
            if a["state"] == "COMMITTED" and a["channel"] == channel
        )
        if channel_total + amount > calc.channel_cap(season, channel):
            fail("ERR_CHANNEL_CAP_EXCEEDED")
        if derive.stop_marketing_committed(stop) + amount > calc.stop_marketing_cap(season):
            fail("ERR_STOP_MARKETING_CAP_EXCEEDED")
        if amount > derive.season_marketing_unallocated(season):
            fail("ERR_MARKETING_BUDGET_EXCEEDED")

        row = new_row(
            tour_stop_id=stop["id"],
            channel=channel,
            amount_cents=amount,
            state="COMMITTED",
            released_at=None,
        )
        db.allocations[row["id"]] = row
        touch(season)  # marketing_allocated_cents / marketing_unallocated_cents moved
        touch(stop)  # marketing_spend_committed_cents moved
        flow.apply_posture(stop)
        return object_response(serialize.allocation(row), 201)

    @app.route("/tour-stops/<stop_id>/marketing-allocations", methods=["GET"])
    def list_allocations(stop_id):
        auth(ROLE_SERIES_PROMOTER, ROLE_FINANCE_CONTROLLER)
        limit, offset = pagination()
        channel = enum_filter("channel", CHANNELS)
        state = enum_filter("state", ALLOCATION_STATES)
        stop = derive.get_stop(stop_id)
        rows = derive.allocations_of_stop(stop["id"])
        if channel is not None:
            rows = [r for r in rows if r["channel"] == channel]
        if state is not None:
            rows = [r for r in rows if r["state"] == state]
        return list_response([serialize.allocation(r) for r in rows], limit, offset)

    @app.route("/marketing-allocations/<allocation_id>", methods=["GET"])
    def read_allocation(allocation_id):
        auth(ROLE_SERIES_PROMOTER, ROLE_FINANCE_CONTROLLER)
        return object_response(serialize.allocation(derive.get_allocation(allocation_id)))

    @app.route("/marketing-allocations/<allocation_id>", methods=["DELETE"])
    def release_allocation(allocation_id):
        auth(ROLE_SERIES_PROMOTER)
        row = derive.get_allocation(allocation_id)
        stop = db.stops[row["tour_stop_id"]]
        flow.ensure_stop_writable(stop)
        if row["state"] != "COMMITTED":
            fail("ERR_INVALID_STATE_TRANSITION")

        row["state"] = "RELEASED"
        row["released_at"] = clock_raw()
        touch(row)
        touch(derive.season_of_stop(stop))
        touch(stop)
        flow.apply_posture(stop)
        return object_response(serialize.allocation(row))

    # ---------------------------------------------------------- settlement
    @app.route("/tour-stops/<stop_id>/settlement", methods=["POST"])
    def prepare_settlement(stop_id):
        user_id, _role = auth(ROLE_FINANCE_CONTROLLER)
        validate.body()
        stop = derive.get_stop(stop_id)
        flow.ensure_stop_writable(stop)

        existing = derive.settlement_of_stop(stop["id"])
        if existing is not None and existing["state"] == "DISPUTED":
            if stop["sales_state"] != "SALES_CLOSED":
                fail(
                    "ERR_INVALID_STATE_TRANSITION",
                    "re-preparation requires the stop's sales to be closed",
                )
        flow.ensure_not_frozen(stop)

        for order in derive.orders_of_stop(stop["id"]):
            if order["status"] == "PENDING":
                fail("ERR_PENDING_ORDERS_OUTSTANDING")
        if derive.plan_of_stop(stop["id"]) is None:
            fail("ERR_SAFETY_PLAN_MISSING")
        if existing is not None and existing["state"] != "DISPUTED":
            fail("ERR_DUPLICATE_CHILD")

        figures = flow.settlement_figures(stop, "PROVISIONAL")
        if existing is not None:
            existing.update(figures)
            existing["state"] = "PREPARED"
            existing["variant"] = "PROVISIONAL"
            existing["prepared_by_user_id"] = user_id
            existing["approved_by_user_id"] = None
            touch(existing)
            return object_response(serialize.settlement(existing), 201)

        row = new_row(
            tour_stop_id=stop["id"],
            state="PREPARED",
            variant="PROVISIONAL",
            prepared_by_user_id=user_id,
            approved_by_user_id=None,
            dispute_reason=None,
            dispute_count=0,
            **figures
        )
        db.settlements[row["id"]] = row
        return object_response(serialize.settlement(row), 201)

    @app.route("/tour-stops/<stop_id>/settlement", methods=["GET"])
    def read_stop_settlement(stop_id):
        auth(ROLE_SERIES_PROMOTER, ROLE_FINANCE_CONTROLLER, ROLE_VENUE_MANAGER)
        limit, offset = pagination()
        stop = derive.get_stop(stop_id)
        row = derive.settlement_of_stop(stop["id"])
        rows = [] if row is None else [serialize.settlement(row)]
        return list_response(rows, limit, offset)

    @app.route("/settlements/<settlement_id>", methods=["GET"])
    def read_settlement(settlement_id):
        auth(ROLE_SERIES_PROMOTER, ROLE_FINANCE_CONTROLLER, ROLE_VENUE_MANAGER)
        return object_response(serialize.settlement(derive.get_settlement(settlement_id)))

    @app.route("/settlements/<settlement_id>/approve", methods=["POST"])
    def approve_settlement(settlement_id):
        user_id, _role = auth(ROLE_FINANCE_CONTROLLER)
        payload = validate.body()
        validate.field_string(payload, "note", required=False)
        row = derive.get_settlement(settlement_id)
        if user_id == row["prepared_by_user_id"]:
            fail("ERR_SETTLEMENT_SELF_APPROVAL")
        stop = db.stops[row["tour_stop_id"]]
        flow.ensure_season_open(derive.season_of_stop(stop))
        if row["state"] != "PREPARED":
            fail("ERR_INVALID_STATE_TRANSITION")
        if stop["sales_state"] != "SALES_CLOSED":
            fail("ERR_INVALID_STATE_TRANSITION", "the stop's sales are not closed")

        row.update(flow.settlement_figures(stop, "FINAL"))
        row["variant"] = "FINAL"
        row["state"] = "APPROVED"
        row["approved_by_user_id"] = user_id
        touch(row)
        flow.cascade_c(row, stop)
        return object_response(serialize.settlement(row))

    @app.route("/settlements/<settlement_id>/dispute", methods=["POST"])
    def dispute_settlement(settlement_id):
        user_id, role = auth(ROLE_FINANCE_CONTROLLER, ROLE_VENUE_MANAGER)
        payload = validate.body()
        reason = validate.field_string(payload, "dispute_reason")
        row = derive.get_settlement(settlement_id)
        stop = db.stops[row["tour_stop_id"]]
        if role == ROLE_VENUE_MANAGER:
            booking = derive.booking_of_stop(stop)
            if user_id != booking["venue_id"]:
                fail("ERR_OWNERSHIP_MISMATCH")
        flow.ensure_season_open(derive.season_of_stop(stop))
        if row["state"] != "PREPARED":
            fail("ERR_INVALID_STATE_TRANSITION")

        row["state"] = "DISPUTED"
        row["dispute_reason"] = reason
        row["dispute_count"] = row["dispute_count"] + 1
        touch(row)
        return object_response(serialize.settlement(row))
