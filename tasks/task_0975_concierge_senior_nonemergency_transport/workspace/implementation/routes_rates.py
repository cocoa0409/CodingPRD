"""Rate card endpoints."""

from flask import request

from core import (
    db, get_caller, require_role, get_body, ok, parse_pagination, paginate,
    field_int, field_enum, field_date, stamp_new, touch, sort_created,
    ApiError, err_not_found,
)
from domain import ser_rate_card

SERVICE_CLASSES = {"STANDARD", "WAV"}


def register(app):

    @app.route("/rate-cards", methods=["POST"])
    def create_rate_card():
        body = get_body()
        service_class = field_enum(body, "service_class", SERVICE_CLASSES, required=True)
        effective_from = field_date(body, "effective_from", required=True)
        effective_to = field_date(body, "effective_to", required=True)
        hourly = field_int(body, "hourly_rate_cents", required=True, minimum=0)
        per_mile = field_int(body, "per_mile_cents", required=True, minimum=0)
        wait_rate = field_int(body, "wait_per_minute_cents", required=True, minimum=0)
        included_wait = field_int(body, "included_wait_minutes", required=True, minimum=0)
        minimum = field_int(body, "minimum_charge_cents", required=True, minimum=0)
        mult_bp = field_int(body, "after_hours_multiplier_bp", required=True, minimum=0)
        ah_start = field_int(
            body, "after_hours_start_minute", required=True, minimum=0, maximum=1439
        )
        wav_surcharge = field_int(body, "wav_surcharge_cents", minimum=0)
        caller = get_caller()
        require_role(caller, {"PlatformAdmin"})
        card = {
            "service_class": service_class,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "hourly_rate_cents": hourly,
            "per_mile_cents": per_mile,
            "wait_per_minute_cents": wait_rate,
            "included_wait_minutes": included_wait,
            "minimum_charge_cents": minimum,
            "after_hours_multiplier_bp": mult_bp,
            "after_hours_start_minute": ah_start,
            "wav_surcharge_cents": 0 if wav_surcharge is None else wav_surcharge,
            "status": "DRAFT",
        }
        stamp_new(card)
        db.rate_cards[card["id"]] = card
        return ok(ser_rate_card(card), status=201)

    @app.route("/rate-cards/<rid>", methods=["GET"])
    def get_rate_card(rid):
        caller = get_caller()
        require_role(caller, {"PlatformAdmin", "Coordinator", "BillingAdmin"})
        card = db.rate_cards.get(rid)
        if card is None:
            raise err_not_found("Rate card not found")
        return ok(ser_rate_card(card))

    @app.route("/rate-cards", methods=["GET"])
    def list_rate_cards():
        caller = get_caller()
        require_role(caller, {"PlatformAdmin", "Coordinator", "BillingAdmin"})
        limit, offset = parse_pagination()
        items = sort_created(db.rate_cards.values())
        service_class = request.args.get("service_class")
        status = request.args.get("status")
        if service_class is not None:
            items = [c for c in items if c["service_class"] == service_class]
        if status is not None:
            items = [c for c in items if c["status"] == status]
        page, meta = paginate(items, limit, offset)
        return ok([ser_rate_card(c) for c in page], response_type="array", pagination=meta)

    @app.route("/rate-cards/<rid>/activate", methods=["POST"])
    def activate_rate_card(rid):
        get_body()
        caller = get_caller()
        require_role(caller, {"PlatformAdmin"})
        card = db.rate_cards.get(rid)
        if card is None:
            raise err_not_found("Rate card not found")
        if card["status"] != "DRAFT":
            raise ApiError(
                "ERR_RATE_CARD_STATE_INVALID", 409,
                "Only a DRAFT rate card can be activated",
            )
        if card["effective_to"] <= card["effective_from"]:
            raise ApiError(
                "ERR_RATE_WINDOW_INVALID", 422,
                "effective_to must be strictly after effective_from",
            )
        for other in db.rate_cards.values():
            if other["id"] == card["id"]:
                continue
            if other["service_class"] != card["service_class"]:
                continue
            if other["status"] != "ACTIVE":
                continue
            if (
                card["effective_from"] < other["effective_to"]
                and other["effective_from"] < card["effective_to"]
            ):
                raise ApiError(
                    "ERR_RATE_WINDOW_OVERLAP", 409,
                    "Window intersects another ACTIVE card of the same class",
                )
        card["status"] = "ACTIVE"
        touch(card)
        return ok(ser_rate_card(card))

    @app.route("/rate-cards/<rid>/retire", methods=["POST"])
    def retire_rate_card(rid):
        get_body()
        caller = get_caller()
        require_role(caller, {"PlatformAdmin"})
        card = db.rate_cards.get(rid)
        if card is None:
            raise err_not_found("Rate card not found")
        if card["status"] == "RETIRED":
            raise ApiError(
                "ERR_RATE_CARD_STATE_INVALID", 409,
                "Rate card is already RETIRED",
            )
        card["status"] = "RETIRED"
        touch(card)
        return ok(ser_rate_card(card))
