"""Sponsorship activations: branding, signage and hospitality (PRD 3.8)."""
from db import clock_raw, db, new_row, touch
from errors import fail
from middleware import (
    ROLE_FINANCE_CONTROLLER,
    ROLE_SERIES_PROMOTER,
    ROLE_SPONSOR_REP,
    ROLE_TICKETING_MANAGER,
    auth,
    enum_filter,
    pagination,
    string_filter,
)
from response import list_response, object_response
from services import calc, derive, flow, serialize
import validate

ACTIVATION_STATES = ("PROPOSED", "ACTIVATED", "FULFILLED")


def register(app):
    @app.route("/sponsorship-activations", methods=["POST"])
    def create_activation():
        user_id, role = auth(ROLE_SERIES_PROMOTER, ROLE_SPONSOR_REP)
        payload = validate.body()
        sponsor_id = validate.field_id(payload, "sponsor_id")
        stop_id = validate.field_id(payload, "tour_stop_id")
        fee = validate.field_int(payload, "fee_cents", minimum=0)
        slots = validate.field_int(payload, "vehicle_branding_slots", minimum=0)
        signage = validate.field_int(payload, "signage_units", minimum=0)
        seats = validate.field_int(
            payload, "hospitality_seat_count", required=False, default=0, minimum=0
        )
        tier_id = validate.field_id(payload, "hospitality_tier_id", required=False)
        entry_id = validate.field_id(payload, "branded_vehicle_entry_id", required=False)

        sponsor = derive.get_sponsor(sponsor_id)
        stop = derive.get_stop(stop_id)
        tier = derive.get_tier(tier_id) if tier_id is not None else None
        entry = derive.get_entry(entry_id) if entry_id is not None else None

        if role == ROLE_SPONSOR_REP and user_id != sponsor["id"]:
            fail("ERR_OWNERSHIP_MISMATCH")

        flow.ensure_stop_writable(stop)
        flow.ensure_not_frozen(stop)

        if entry is not None and entry["tech_status"] == "TECH_HELD":
            fail("ERR_ENTRY_TECH_HELD")
        if tier is not None and tier["tour_stop_id"] != stop["id"]:
            fail("ERR_CHILD_STOP_MISMATCH")
        if entry is not None and entry["tour_stop_id"] != stop["id"]:
            fail("ERR_CHILD_STOP_MISMATCH")

        if slots > 0:
            if entry is None:
                fail("ERR_BRANDING_SLOTS_EXCEEDED")
            committed = derive.entry_branding_slots_committed(entry)
            if committed + slots > calc.MAX_BRANDING_SLOTS_PER_VEHICLE:
                fail("ERR_BRANDING_SLOTS_EXCEEDED")
        if seats > 0:
            if tier is None:
                fail("ERR_HOSPITALITY_SEATS_EXCEEDED")
            if derive.tier_held(tier) + seats > tier["allotment"]:
                fail("ERR_HOSPITALITY_SEATS_EXCEEDED")

        row = new_row(
            sponsor_id=sponsor["id"],
            tour_stop_id=stop["id"],
            hospitality_tier_id=tier_id,
            branded_vehicle_entry_id=entry_id,
            fee_cents=fee,
            vehicle_branding_slots=slots,
            signage_units=signage,
            hospitality_seat_count=seats,
            state="PROPOSED",
            obligations_fulfilled_at=None,
            recognized_fee_cents=0,
        )
        db.activations[row["id"]] = row
        return object_response(serialize.activation(row), 201)

    @app.route("/sponsorship-activations", methods=["GET"])
    def list_activations():
        auth(
            ROLE_SERIES_PROMOTER,
            ROLE_SPONSOR_REP,
            ROLE_FINANCE_CONTROLLER,
            ROLE_TICKETING_MANAGER,
        )
        limit, offset = pagination()
        sponsor_id = string_filter("sponsor_id")
        stop_id = string_filter("tour_stop_id")
        tier_id = string_filter("hospitality_tier_id")
        entry_id = string_filter("branded_vehicle_entry_id")
        state = enum_filter("state", ACTIVATION_STATES)
        rows = derive.all_activations()
        if sponsor_id is not None:
            rows = [r for r in rows if r["sponsor_id"] == sponsor_id]
        if stop_id is not None:
            rows = [r for r in rows if r["tour_stop_id"] == stop_id]
        if tier_id is not None:
            rows = [r for r in rows if r["hospitality_tier_id"] == tier_id]
        if entry_id is not None:
            rows = [r for r in rows if r["branded_vehicle_entry_id"] == entry_id]
        if state is not None:
            rows = [r for r in rows if r["state"] == state]
        return list_response([serialize.activation(r) for r in rows], limit, offset)

    @app.route("/sponsorship-activations/<activation_id>", methods=["GET"])
    def read_activation(activation_id):
        auth(ROLE_SERIES_PROMOTER, ROLE_SPONSOR_REP, ROLE_FINANCE_CONTROLLER)
        return object_response(serialize.activation(derive.get_activation(activation_id)))

    @app.route("/sponsorship-activations/<activation_id>/activate", methods=["POST"])
    def activate(activation_id):
        auth(ROLE_SERIES_PROMOTER)
        validate.body()
        row = derive.get_activation(activation_id)
        stop = db.stops[row["tour_stop_id"]]
        flow.ensure_stop_writable(stop)
        if row["state"] != "PROPOSED":
            fail("ERR_INVALID_STATE_TRANSITION")
        flow.ensure_not_frozen(stop)

        entry = (
            db.entries.get(row["branded_vehicle_entry_id"])
            if row["branded_vehicle_entry_id"]
            else None
        )
        tier = (
            db.tiers.get(row["hospitality_tier_id"]) if row["hospitality_tier_id"] else None
        )
        slots = row["vehicle_branding_slots"]
        seats = row["hospitality_seat_count"]

        if slots > 0:
            if entry is None or entry["tour_stop_id"] != stop["id"]:
                fail("ERR_BRANDING_SLOTS_EXCEEDED")
            if derive.entry_branding_slots_committed(entry) + slots > (
                calc.MAX_BRANDING_SLOTS_PER_VEHICLE
            ):
                fail("ERR_BRANDING_SLOTS_EXCEEDED")

        sponsor = db.sponsors[row["sponsor_id"]]
        for other in derive.activations_of_stop(stop["id"]):
            if other["id"] == row["id"] or other["state"] not in ("ACTIVATED", "FULFILLED"):
                continue
            other_sponsor = db.sponsors.get(other["sponsor_id"])
            if other_sponsor is None or other_sponsor["category"] != sponsor["category"]:
                continue
            if sponsor["exclusive_category"] or other_sponsor["exclusive_category"]:
                fail("ERR_SPONSOR_CATEGORY_EXCLUSIVITY")

        if seats > 0:
            if tier is None or tier["tour_stop_id"] != stop["id"]:
                fail("ERR_HOSPITALITY_SEATS_EXCEEDED")
            if derive.tier_available(tier) < seats:
                fail("ERR_HOSPITALITY_SEATS_EXCEEDED")
            if derive.tier_held(tier) + seats > tier["allotment"]:
                fail("ERR_HOSPITALITY_SEATS_EXCEEDED")

        # `recognized_fee_cents` stays 0 here: PRD 3.8 has fulfilment, and only
        # fulfilment, promote it to the full fee. Settlement recognition of a merely
        # ACTIVATED package is derived from the variant, not from this field.
        row["state"] = "ACTIVATED"
        touch(row)
        if tier is not None and seats > 0:
            touch(tier)  # held_seat_count / available_seat_count moved
        if entry is not None and slots > 0:
            touch(entry)  # branding_slots_committed moved
        touch(stop)  # sponsorship_committed_cents / held_hospitality_seat_count moved
        flow.apply_posture(stop)
        return object_response(serialize.activation(row))

    @app.route("/sponsorship-activations/<activation_id>/fulfill", methods=["POST"])
    def fulfill(activation_id):
        user_id, role = auth(ROLE_SERIES_PROMOTER, ROLE_SPONSOR_REP)
        payload = validate.body()
        validate.field_string(payload, "note", required=False)
        row = derive.get_activation(activation_id)
        if role == ROLE_SPONSOR_REP and user_id != row["sponsor_id"]:
            fail("ERR_OWNERSHIP_MISMATCH")
        stop = db.stops[row["tour_stop_id"]]
        flow.ensure_stop_writable(stop)
        if row["state"] != "ACTIVATED":
            fail("ERR_INVALID_STATE_TRANSITION")
        if stop["sales_state"] not in ("ON_SALE", "SALES_HALTED", "SALES_CLOSED"):
            fail("ERR_INVALID_STATE_TRANSITION")

        row["state"] = "FULFILLED"
        row["obligations_fulfilled_at"] = clock_raw()
        row["recognized_fee_cents"] = row["fee_cents"]
        touch(row)
        return object_response(serialize.activation(row))
