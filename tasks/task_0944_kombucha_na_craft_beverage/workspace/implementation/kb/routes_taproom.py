"""Taproom pours and growler fills."""

from decimal import Decimal
from flask import Blueprint, g

from . import constants as C
from . import lookup
from .auth import authorize
from .calc import taproom_fill_charge
from .envelope import object_response
from .errors import ApiError
from .routes_recipes import require_id
from .store import base_record, db, touch
from .util import add_hours, age_at_least, dec, round2
from .validate import body_dict, field, parse_body

bp = Blueprint("taproom", __name__)


@bp.post("/taproom-fills")
def open_fill():
    authorize("TaproomStaff", "PlatformAdmin")
    payload = body_dict()
    keg = lookup.keg(require_id(payload, "keg_id"))
    data = parse_body(
        payload,
        [
            field("keg_id", "string", required=True),
            field(
                "container_type", "enum", required=True, members=C.CONTAINER_TYPES
            ),
            field("requested_liters", "number", required=True, positive=True),
            field("customer_birth_date", "datetime"),
        ],
    )
    if keg["status"] != "ON_TAP":
        raise ApiError(
            "ERR_INVALID_STATE", "A fill may only be opened against an ON_TAP keg."
        )

    requested = round2(data["requested_liters"])
    if requested < C.POUR_MIN_LITERS:
        raise ApiError(
            "ERR_VALIDATION",
            "requested_liters must be at or above %s liters." % C.POUR_MIN_LITERS,
        )
    if data["container_type"] in ("HOUSE_GROWLER", "CUSTOMER_GROWLER"):
        if requested > C.GROWLER_MAX_FILL_LITERS:
            raise ApiError(
                "ERR_VALIDATION",
                "A growler fill may not exceed %s liters."
                % C.GROWLER_MAX_FILL_LITERS,
            )

    record = base_record()
    record.update(
        {
            "keg_id": keg["id"],
            "container_type": data["container_type"],
            "requested_liters": requested,
            "fill_status": "REQUESTED",
            "inspected_at": None,
            "inspected_by_user_id": None,
            "customer_birth_date": data["customer_birth_date"],
            "age_verified": False,
            "poured_liters": Decimal("0.00"),
            "charge_amount": Decimal("0.00"),
            "poured_at": None,
        }
    )
    db.taproom_fills[record["id"]] = record
    return object_response(record, 201)


@bp.post("/taproom-fills/<id>/inspect")
def inspect_fill(id):
    authorize("TaproomStaff", "PlatformAdmin")
    fill = lookup.taproom_fill(id)
    body_dict()
    if fill["fill_status"] != "REQUESTED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a REQUESTED fill may be inspected."
        )
    if fill["container_type"] != "CUSTOMER_GROWLER":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Inspection is only offered for a customer-owned growler.",
        )
    fill["fill_status"] = "INSPECTED"
    fill["inspected_at"] = db.clock
    fill["inspected_by_user_id"] = g.user_id
    touch(fill)
    return object_response(fill)


@bp.post("/taproom-fills/<id>/pour")
def pour_fill(id):
    authorize("TaproomStaff", "PlatformAdmin")
    fill = lookup.taproom_fill(id)
    body_dict()

    # gate 4 -- fill state
    if fill["fill_status"] not in ("REQUESTED", "INSPECTED"):
        raise ApiError("ERR_INVALID_STATE", "This fill has already been poured.")

    # gate 5 -- the container gate
    if fill["container_type"] == "CUSTOMER_GROWLER":
        if fill["fill_status"] != "INSPECTED" or fill["inspected_at"] is None:
            raise ApiError(
                "ERR_GROWLER_INSPECTION_REQUIRED",
                "A customer-owned growler must pass a sanitation inspection first.",
            )
        if db.clock > add_hours(
            fill["inspected_at"], C.GROWLER_INSPECTION_VALID_HOURS
        ):
            raise ApiError(
                "ERR_GROWLER_INSPECTION_REQUIRED",
                "The sanitation inspection has gone stale.",
            )

    # gate 6 -- keg state
    keg = db.kegs.get(fill["keg_id"])
    if keg is None or keg["status"] != "ON_TAP":
        raise ApiError("ERR_INVALID_STATE", "The keg is no longer on tap.")

    # gate 7 -- the person gate
    lot = db.finished_lots.get(keg.get("finished_lot_id"))
    age_applied = lot is not None and lot["abv_class"] == "ALCOHOLIC"
    if age_applied:
        birth = fill.get("customer_birth_date")
        if birth is None or not age_at_least(
            birth, db.clock, C.AGE_VERIFICATION_MIN_AGE_YEARS
        ):
            raise ApiError(
                "ERR_AGE_VERIFICATION_REQUIRED",
                "An alcoholic pour needs a customer of at least %d years."
                % C.AGE_VERIFICATION_MIN_AGE_YEARS,
            )

    # gate 8 -- volume
    requested = dec(fill["requested_liters"])
    if requested > dec(keg["remaining_liters"]):
        raise ApiError(
            "ERR_INSUFFICIENT_KEG_VOLUME",
            "requested_liters exceeds the keg's remaining_liters.",
        )

    fill["fill_status"] = "POURED"
    fill["poured_liters"] = round2(requested)
    fill["poured_at"] = db.clock
    if age_applied:
        fill["age_verified"] = True
    fill["charge_amount"] = taproom_fill_charge(requested, fill["container_type"])
    touch(fill)

    remaining = round2(dec(keg["remaining_liters"]) - requested)
    if remaining < C.KEG_MIN_RESIDUAL_LITERS:
        keg["status"] = "EMPTY"
        keg["remaining_liters"] = Decimal("0.00")
        keg["finished_lot_id"] = None
        keg["last_untapped_at"] = db.clock
    else:
        keg["remaining_liters"] = remaining
    touch(keg)

    return object_response(fill)
