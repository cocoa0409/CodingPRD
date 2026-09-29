"""Promotional instruments: quantity discount tiers and combination sales.

PRD section 3.5.
"""

from flask import Blueprint

import calc
import services
from auth import ALL_ROLES, ROLE_FILING_AGENT, authenticate, require_scope
from envelope import object_response
from errors import raise_err
from serialize import out
from store import db, dt_of, new_record
from validators import (
    Field,
    collection_response,
    must_find,
    require_interval,
    validate_body,
)

bp = Blueprint("instruments", __name__)

TIER_STATUSES = ("ACTIVE", "INACTIVE")
COMBINATION_STATUSES = ("ACTIVE", "VOID")


# ---------------------------------------------------------------------------
# quantity discount tiers
# ---------------------------------------------------------------------------
@bp.post("/quantity-discount-tiers")
def create_quantity_discount_tier():
    actor = authenticate([ROLE_FILING_AGENT])
    values = validate_body(
        [
            Field("item_id", "string"),
            Field("min_cases", "int", minimum=2),
            Field("discount_pct", "number", exclusive_minimum=0, maximum=1),
        ]
    )
    item = must_find("price_schedule_item", values["item_id"])
    schedule = services.schedule_of_item(item)
    require_scope(actor, schedule["wholesaler_id"])

    program = services.program_of_schedule(schedule)

    # Priority 15 -- the state must tolerate the instrument at all.
    if not program["quantity_discount_allowed"]:
        raise_err("ERR_QUANTITY_DISCOUNT_PROHIBITED")

    # Priority 17 -- the cap itself is permitted; only exceeding it is refused.
    if calc.dec(values["discount_pct"]) > calc.dec(program["max_quantity_discount_pct"]):
        raise_err("ERR_DISCOUNT_EXCEEDS_STATE_CAP")

    record = new_record(
        {
            "item_id": item["id"],
            "min_cases": values["min_cases"],
            "discount_pct": values["discount_pct"],
            "discounted_case_price_cents": calc.tier_discounted_case_price(
                item["case_price_cents"], values["discount_pct"]
            ),
            "status": "ACTIVE",
        }
    )
    db.quantity_discount_tiers[record["id"]] = record
    return object_response(out(record), 201)


@bp.get("/quantity-discount-tiers/<record_id>")
def get_quantity_discount_tier(record_id):
    authenticate(ALL_ROLES)
    return object_response(out(must_find("quantity_discount_tier", record_id)))


@bp.get("/quantity-discount-tiers")
def list_quantity_discount_tiers():
    authenticate(ALL_ROLES)
    return collection_response(
        list(db.quantity_discount_tiers.values()),
        {"item_id": None, "status": TIER_STATUSES},
        out,
    )


# ---------------------------------------------------------------------------
# combination sales
# ---------------------------------------------------------------------------
@bp.post("/combination-sales")
def create_combination_sale():
    actor = authenticate([ROLE_FILING_AGENT])
    values = validate_body(
        [
            Field("schedule_id", "string"),
            Field("member_item_ids", "string_array"),
            Field("promo_starts_at", "datetime"),
            Field("promo_ends_at", "datetime"),
            Field("combined_case_price_cents", "int", minimum=1),
        ]
    )
    require_interval(values, "promo_starts_at", "promo_ends_at")

    schedule = must_find("price_schedule", values["schedule_id"])
    members = [must_find("price_schedule_item", i) for i in values["member_item_ids"]]
    require_scope(actor, schedule["wholesaler_id"])

    program = services.program_of_schedule(schedule)
    new_start = dt_of(values["promo_starts_at"])
    new_end = dt_of(values["promo_ends_at"])

    # Priority 13 -- promotional windows of one wholesaler must be separated by the
    # program's cooldown buffer. VOID combinations do not occupy the timeline.
    for existing in db.combination_sales.values():
        if existing["status"] != "ACTIVE":
            continue
        existing_schedule = db.price_schedules[existing["schedule_id"]]
        if existing_schedule["wholesaler_id"] != schedule["wholesaler_id"]:
            continue
        if calc.combination_conflicts(
            new_start,
            new_end,
            dt_of(existing["promo_starts_at"]),
            dt_of(existing["promo_ends_at"]),
            program["combo_cooldown_days"],
        ):
            raise_err("ERR_COMBINATION_COOLDOWN_VIOLATION")

    # Priority 15 -- the state must tolerate the instrument at all.
    if not program["combination_sale_allowed"]:
        raise_err("ERR_COMBINATION_SALE_PROHIBITED")

    floor_price, minimum = calc.combination_sale_min_price(members)

    # Priority 17 -- exactly the minimum is permitted; only below it is refused.
    if values["combined_case_price_cents"] < minimum:
        raise_err("ERR_COMBINATION_BELOW_FLOOR")

    # Priority 19 -- the member-count test is evaluated before the membership test.
    if len(set(values["member_item_ids"])) < 2:
        raise_err("ERR_COMBINATION_TOO_FEW_MEMBERS")
    for member in members:
        if member["schedule_id"] != schedule["id"]:
            raise_err("ERR_ITEM_NOT_ON_SAME_SCHEDULE")

    record = new_record(
        {
            "schedule_id": schedule["id"],
            "member_item_ids": list(values["member_item_ids"]),
            "promo_starts_at": values["promo_starts_at"],
            "promo_ends_at": values["promo_ends_at"],
            "combined_case_price_cents": values["combined_case_price_cents"],
            "floor_price_cents": floor_price,
            "min_allowed_price_cents": minimum,
            "status": "ACTIVE",
        }
    )
    db.combination_sales[record["id"]] = record
    return object_response(out(record), 201)


@bp.get("/combination-sales/<record_id>")
def get_combination_sale(record_id):
    authenticate(ALL_ROLES)
    return object_response(out(must_find("combination_sale", record_id)))


@bp.get("/combination-sales")
def list_combination_sales():
    authenticate(ALL_ROLES)
    return collection_response(
        list(db.combination_sales.values()),
        {"schedule_id": None, "status": COMBINATION_STATUSES},
        out,
    )
