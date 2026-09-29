"""Merchant classification and bonus category rotations (PRD 3.2)."""

from decimal import Decimal

from flask import Blueprint, request

from auth import endpoint
from core import DB, clock_dt, clock_iso, fmt_dt, must_find, new_row, ok, parse_dt, store, touch
from errors import ApiError, invalid
from rhelp import require_state
from shapes import body, bool_filter, opt_bool, req_decimal, req_dt, req_enum, req_int, req_string
from views import ADMIN, OPS_CARD, listing, plain

bp = Blueprint("catalog", __name__)

BASE_CATEGORIES = ("DINING", "TRAVEL_AIR", "TRAVEL_HOTEL", "GROCERY", "GAS", "OTHER")
LIVE_ROTATION_STATUSES = ("DRAFT", "SCHEDULED", "ACTIVE")


@bp.post("/merchant-categories")
@endpoint(ADMIN)
def create_category():
    data = body()
    mcc_code = req_string(data, "mcc_code")
    display_name = req_string(data, "display_name")
    base_category = req_enum(data, "base_category", BASE_CATEGORIES)
    req_decimal(data, "base_multiplier", minimum=Decimal("1.0"), max_decimals=2)
    is_fallback = opt_bool(data, "is_fallback", False)

    for existing in DB["merchant_categories"].values():
        if existing["mcc_code"] == mcc_code:
            raise ApiError(
                "ERR_DUPLICATE_CATEGORY_MAPPING",
                "MCC code '%s' is already mapped." % mcc_code,
            )
    if is_fallback:
        for existing in DB["merchant_categories"].values():
            if existing["is_fallback"]:
                raise ApiError(
                    "ERR_DUPLICATE_CATEGORY_MAPPING",
                    "A fallback merchant category already exists.",
                )

    row = store(
        "merchant_categories",
        new_row(
            "merchant_categories",
            {
                "mcc_code": mcc_code,
                "display_name": display_name,
                "base_category": base_category,
                "base_multiplier": data["base_multiplier"],
                "is_fallback": is_fallback,
            },
        ),
    )
    return ok(plain(row), 201)


@bp.get("/merchant-categories/<category_id>")
@endpoint(OPS_CARD)
def read_category(category_id):
    return ok(plain(must_find("merchant_categories", category_id)))


@bp.get("/merchant-categories")
@endpoint(OPS_CARD)
def list_categories():
    args = request.args
    filters = {
        "mcc_code": args.get("mcc_code"),
        "base_category": args.get("base_category"),
        "is_fallback": bool_filter(args, "is_fallback"),
    }
    return listing("merchant_categories", args, filters)


# --------------------------------------------------------------------------
# rotations
# --------------------------------------------------------------------------
@bp.post("/rotations")
@endpoint(ADMIN)
def create_rotation():
    data = body()
    category_id = data.get("merchant_category_id")
    if not isinstance(category_id, str) or category_id.strip() == "":
        raise invalid("'merchant_category_id' is required")
    must_find("merchant_categories", category_id)

    rotation_code = req_string(data, "rotation_code")
    req_decimal(data, "bonus_multiplier", exclusive_minimum=Decimal("1.0"), max_decimals=2)
    capped_spend_cents = req_int(data, "capped_spend_cents", minimum=1)
    window_start = req_dt(data, "window_start")
    window_end = req_dt(data, "window_end")
    if window_end <= window_start:
        raise invalid("'window_end' must be strictly later than 'window_start'")

    for other in DB["rotations"].values():
        if other["merchant_category_id"] != category_id:
            continue
        if other["status"] not in LIVE_ROTATION_STATUSES:
            continue
        other_start = parse_dt(other["window_start"])
        other_end = parse_dt(other["window_end"])
        if window_start < other_end and other_start < window_end:
            raise ApiError(
                "ERR_ROTATION_WINDOW_OVERLAP",
                "Rotation window overlaps rotation '%s'." % other["id"],
            )

    for other in DB["rotations"].values():
        if other["rotation_code"] == rotation_code:
            raise ApiError(
                "ERR_DUPLICATE_PROGRAM_CODE",
                "Rotation code '%s' is already in use." % rotation_code,
            )

    row = store(
        "rotations",
        new_row(
            "rotations",
            {
                "merchant_category_id": category_id,
                "rotation_code": rotation_code,
                "bonus_multiplier": data["bonus_multiplier"],
                "capped_spend_cents": capped_spend_cents,
                "window_start": fmt_dt(window_start),
                "window_end": fmt_dt(window_end),
                "status": "DRAFT",
                "published_at": None,
                "activated_at": None,
                "expired_at": None,
            },
        ),
    )
    return ok(plain(row), 201)


@bp.get("/rotations/<rotation_id>")
@endpoint(OPS_CARD)
def read_rotation(rotation_id):
    return ok(plain(must_find("rotations", rotation_id)))


@bp.get("/rotations")
@endpoint(OPS_CARD)
def list_rotations():
    args = request.args
    filters = {
        "merchant_category_id": args.get("merchant_category_id"),
        "status": args.get("status"),
        "rotation_code": args.get("rotation_code"),
    }
    return listing("rotations", args, filters)


@bp.post("/rotations/<rotation_id>/publish")
@endpoint(ADMIN)
def publish_rotation(rotation_id):
    rotation = must_find("rotations", rotation_id)
    require_state(rotation, ("DRAFT",))
    if parse_dt(rotation["window_start"]) <= clock_dt():
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "A rotation whose window has already opened cannot be published.",
        )
    rotation["status"] = "SCHEDULED"
    rotation["published_at"] = clock_iso()
    touch(rotation)
    return ok(plain(rotation))
