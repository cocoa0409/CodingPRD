"""Menu cycle authoring, therapeutic extensions and the committee refresh loop."""
from decimal import Decimal

from flask import Blueprint

import serialize
from auth import authenticate, require_own_resident, rep_scope
from constants import (
    COVERAGE_STATUSES, DECISIONS, DIET_CODES, EXTENSION_STATUSES,
    FEEDBACK_STATUSES, MAX_EXTENSION_REVIEW_ROUNDS, MEAL_PERIODS, SENTIMENTS,
    TEXTURES,
)
from db import base_row, db, snapshot, sort_created, touch, touch_if_changed
from errors import api_error
from response import created, ok, ok_list
from routes.common import (
    CS, DSM, EVERY_ROLE, PA, RD, RR, SKL, get_community, get_extension,
    get_menu_cycle, get_menu_item, get_resident,
)
from services import calc, derive
from shape import (
    body_json, opt_enum_array, opt_object, opt_str, opt_str_array, paginate,
    q_enum, q_int, q_str, req_date, req_enum, req_int, req_str,
)

bp = Blueprint("menus", __name__)

CYCLE_READ_ROLES = [PA, CS, RD, DSM, SKL, RR]
BALLOT_READ_ROLES = [PA, RD, DSM, RR]
EXTENSION_READ_ROLES = [PA, CS, RD, DSM, SKL]
HEAVY_MENU_STATUSES = ("PUBLISHED", "REFRESH_PENDING", "ARCHIVED")


# =============================================================== menu cycles
@bp.get("/menu-cycles/<cycle_id>")
def read_cycle(cycle_id):
    authenticate(EVERY_ROLE)
    return ok(serialize.menu_cycle(get_menu_cycle(cycle_id)))


@bp.get("/menu-cycles/<cycle_id>/items")
def list_items(cycle_id):
    authenticate(CYCLE_READ_ROLES)
    get_menu_cycle(cycle_id)
    day_index = q_int("day_index")
    meal_period = q_enum("meal_period", MEAL_PERIODS)
    coverage = q_enum("extension_coverage_status", COVERAGE_STATUSES)
    rows = derive.cycle_items(cycle_id)
    if day_index is not None:
        rows = [i for i in rows if i["day_index"] == day_index]
    if meal_period is not None:
        rows = [i for i in rows if i["meal_period"] == meal_period]
    if coverage is not None:
        rows = [i for i in rows if i["extension_coverage_status"] == coverage]
    window, pagination = paginate(sort_created(rows))
    return ok_list(serialize.many(serialize.menu_item, window), pagination)


@bp.get("/menu-cycles/<cycle_id>/committee-feedback")
def list_cycle_feedback(cycle_id):
    ctx = authenticate(BALLOT_READ_ROLES)
    resident_id = q_str("resident_id")
    scope = rep_scope(ctx)
    if scope is not None and resident_id is not None and resident_id != scope:
        raise api_error(
            "ERR_FORBIDDEN_ROLE",
            "A ResidentRepresentative may only filter on its own resident",
        )
    get_menu_cycle(cycle_id)
    sentiment = q_enum("sentiment", SENTIMENTS)
    status = q_enum("status", FEEDBACK_STATUSES)
    rows = [f for f in db.feedback.values() if f["menu_cycle_id"] == cycle_id]
    if resident_id is not None:
        rows = [f for f in rows if f["resident_id"] == resident_id]
    if sentiment is not None:
        rows = [f for f in rows if f["sentiment"] == sentiment]
    if status is not None:
        rows = [f for f in rows if f["status"] == status]
    window, pagination = paginate(sort_created(rows))
    return ok_list(serialize.many(serialize.feedback, window), pagination)


@bp.post("/menu-cycles")
def create_cycle():
    authenticate([DSM])
    body = body_json()
    community_id = req_str(body, "community_id")
    cycle_number = req_int(body, "cycle_number", minimum=1)
    week_count = req_int(body, "week_count", minimum=1)
    start_str, start_date = req_date(body, "effective_start_date")
    end_str, end_date = req_date(body, "effective_end_date")
    if end_date < start_date:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "effective_end_date must not precede effective_start_date",
        )

    get_community(community_id)

    row = base_row()
    row.update({
        "community_id": community_id,
        "cycle_number": cycle_number,
        "week_count": week_count,
        "effective_start_date": start_str,
        "effective_end_date": end_str,
        "status": "DRAFT",
        "refresh_index": Decimal("0.00"),
        "refresh_tier": "ADVISORY",
        "refresh_round": 0,
        "refresh_reason": None,
        "signed_off_by_user_id": None,
    })
    db.menu_cycles[row["id"]] = row
    return created(serialize.menu_cycle(row))


@bp.post("/menu-cycles/<cycle_id>/items")
def create_item(cycle_id):
    authenticate([DSM])
    body = body_json()
    item_code = req_str(body, "item_code")
    name = req_str(body, "name")
    day_index = req_int(body, "day_index", minimum=1)
    meal_period = req_enum(body, "meal_period", MEAL_PERIODS)
    base_texture = req_enum(body, "base_texture", TEXTURES)
    allergen_tags = opt_str_array(body, "allergen_tags")
    required_codes = opt_enum_array(body, "required_therapeutic_codes", DIET_CODES)

    cycle = get_menu_cycle(cycle_id)

    span = cycle["week_count"] * 7
    if day_index > span:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "day_index must be between 1 and %d for a %d week cycle"
            % (span, cycle["week_count"]),
        )

    for existing in derive.cycle_items(cycle_id):
        if existing["item_code"] == item_code:
            raise api_error(
                "ERR_DUPLICATE_ITEM_CODE",
                "item_code %s is already used by another item of this cycle" % item_code,
            )

    row = base_row()
    row.update({
        "menu_cycle_id": cycle_id,
        "item_code": item_code,
        "name": name,
        "day_index": day_index,
        "meal_period": meal_period,
        "base_texture": base_texture,
        "allergen_tags": allergen_tags,
        "required_therapeutic_codes": required_codes,
        "extension_coverage_status": "NOT_REQUIRED" if not required_codes else "INCOMPLETE",
    })
    db.menu_items[row["id"]] = row
    return created(serialize.menu_item(row))


@bp.post("/menu-cycles/<cycle_id>/submit")
def submit_cycle(cycle_id):
    authenticate([DSM])
    body_json()
    cycle = get_menu_cycle(cycle_id)
    if cycle["status"] != "DRAFT":
        raise api_error("ERR_INVALID_STATE", "Only a DRAFT cycle may be submitted for sign-off")
    if not derive.cycle_items(cycle_id):
        raise api_error("ERR_INVALID_STATE", "An empty menu cycle cannot be submitted")
    cycle["status"] = "PENDING_DIETITIAN_SIGNOFF"
    touch(cycle)
    return ok(serialize.menu_cycle(cycle))


@bp.post("/menu-cycles/<cycle_id>/publish")
def publish_cycle(cycle_id):
    ctx = authenticate([RD])
    body_json()
    cycle = get_menu_cycle(cycle_id)
    if cycle["status"] != "PENDING_DIETITIAN_SIGNOFF":
        raise api_error(
            "ERR_INVALID_STATE",
            "Only a PENDING_DIETITIAN_SIGNOFF cycle may be published",
        )

    for item in derive.cycle_items(cycle_id):
        if item["required_therapeutic_codes"] and item["extension_coverage_status"] != "COMPLETE":
            raise api_error(
                "ERR_THERAPEUTIC_COVERAGE_INCOMPLETE",
                "Menu item %s still lacks approved therapeutic extensions" % item["item_code"],
            )

    for other in db.menu_cycles.values():
        if other["id"] == cycle_id or other["community_id"] != cycle["community_id"]:
            continue
        if other["status"] != "PUBLISHED":
            continue
        if (
            other["effective_start_date"] <= cycle["effective_end_date"]
            and cycle["effective_start_date"] <= other["effective_end_date"]
        ):
            raise api_error(
                "ERR_MENU_CYCLE_DATE_OVERLAP",
                "The effective range intersects PUBLISHED cycle %s" % other["id"],
            )

    cycle["status"] = "PUBLISHED"
    cycle["signed_off_by_user_id"] = ctx["user_id"]
    touch(cycle)

    for other in db.menu_cycles.values():
        if other["id"] == cycle_id or other["community_id"] != cycle["community_id"]:
            continue
        if other["status"] != "PUBLISHED":
            continue
        if other["effective_end_date"] < cycle["effective_start_date"]:
            other["status"] = "ARCHIVED"
            touch(other)

    return ok(serialize.menu_cycle(cycle))


@bp.post("/menu-cycles/<cycle_id>/refresh")
def refresh_cycle(cycle_id):
    authenticate([DSM])
    body = body_json()
    refresh_reason = req_str(body, "refresh_reason")

    cycle = get_menu_cycle(cycle_id)
    if cycle["status"] != "REFRESH_PENDING":
        raise api_error("ERR_INVALID_STATE", "Only a REFRESH_PENDING cycle may be refreshed")

    cycle["status"] = "DRAFT"
    cycle["refresh_round"] = cycle["refresh_round"] + 1
    cycle["refresh_reason"] = refresh_reason
    cycle["refresh_index"] = Decimal("0.00")
    cycle["refresh_tier"] = "ADVISORY"
    touch(cycle)

    for ballot in db.feedback.values():
        if ballot["menu_cycle_id"] == cycle_id and ballot["status"] == "SUBMITTED":
            ballot["status"] = "ACKNOWLEDGED"

    for item in derive.cycle_items(cycle_id):
        retired = False
        for ext in derive.item_extensions(item["id"]):
            if ext["review_status"] == "APPROVED":
                ext["review_status"] = "RETIRED"
                touch(ext)
                retired = True
        if retired:
            derive.recompute_coverage(item)

    return ok(serialize.menu_cycle(cycle))


@bp.post("/menu-cycles/<cycle_id>/committee-feedback")
def cast_ballot(cycle_id):
    ctx = authenticate([RR])
    body = body_json()
    resident_id = req_str(body, "resident_id")
    require_own_resident(ctx, resident_id)
    menu_item_code = req_str(body, "menu_item_code")
    sentiment = req_enum(body, "sentiment", SENTIMENTS)

    cycle = get_menu_cycle(cycle_id)
    resident = get_resident(resident_id)

    if resident["community_id"] != cycle["community_id"]:
        raise api_error(
            "ERR_CROSS_COMMUNITY_REFERENCE",
            "The balloting resident must belong to the cycle's community",
        )

    codes = set(i["item_code"] for i in derive.cycle_items(cycle_id))
    if menu_item_code not in codes:
        raise api_error(
            "ERR_MENU_ITEM_NOT_IN_CYCLE",
            "menu_item_code %s does not name an item of this cycle" % menu_item_code,
        )

    if resident["dining_status"] != "ACTIVE":
        raise api_error(
            "ERR_RESIDENT_NOT_ACTIVE",
            "Only an ACTIVE resident may cast a food-committee ballot",
        )

    for ballot in db.feedback.values():
        if (
            ballot["menu_cycle_id"] == cycle_id
            and ballot["resident_id"] == resident_id
            and ballot["menu_item_code"] == menu_item_code
            and ballot["status"] == "SUBMITTED"
        ):
            raise api_error(
                "ERR_DUPLICATE_BALLOT",
                "A SUBMITTED ballot already exists for this cycle, resident and item code",
            )

    row = base_row(versioned=False)
    row.update({
        "menu_cycle_id": cycle_id,
        "resident_id": resident_id,
        "menu_item_code": menu_item_code,
        "sentiment": sentiment,
        "vote_weight": 2 if resident["care_level"] in ("MEMORY_CARE", "SKILLED_NURSING") else 1,
        "status": "SUBMITTED",
    })
    db.feedback[row["id"]] = row

    refresh_index, refresh_tier, eligible = calc.menu_refresh_index(cycle)
    snap = snapshot(cycle, ["refresh_index", "refresh_tier", "status"])
    cycle["refresh_index"] = refresh_index
    cycle["refresh_tier"] = refresh_tier
    if eligible and cycle["status"] == "PUBLISHED":
        cycle["status"] = "REFRESH_PENDING"
    touch_if_changed(cycle, snap)

    return created(serialize.feedback(row))


# ================================================================ menu items
@bp.get("/menu-items/<item_id>")
def read_item(item_id):
    authenticate(CYCLE_READ_ROLES)
    return ok(serialize.menu_item(get_menu_item(item_id)))


@bp.get("/menu-items/<item_id>/therapeutic-extensions")
def list_extensions(item_id):
    authenticate(EXTENSION_READ_ROLES)
    get_menu_item(item_id)
    diet_code = q_enum("diet_code", DIET_CODES)
    review_status = q_enum("review_status", EXTENSION_STATUSES)
    rows = derive.item_extensions(item_id)
    if diet_code is not None:
        rows = [e for e in rows if e["diet_code"] == diet_code]
    if review_status is not None:
        rows = [e for e in rows if e["review_status"] == review_status]
    window, pagination = paginate(sort_created(rows))
    return ok_list(serialize.many(serialize.extension, window), pagination)


@bp.post("/menu-items/<item_id>/therapeutic-extensions")
def create_extension(item_id):
    ctx = authenticate([RD])
    body = body_json()
    diet_code = req_enum(body, "diet_code", DIET_CODES)
    nutrient_overrides = opt_object(body, "nutrient_overrides")

    get_menu_item(item_id)

    row = base_row()
    row.update({
        "menu_item_id": item_id,
        "diet_code": diet_code,
        "nutrient_overrides": nutrient_overrides,
        "review_status": "DRAFT",
        "review_round": 0,
        "authored_by_user_id": ctx["user_id"],
        "reviewed_by_user_id": None,
        "reviewer_note": None,
    })
    db.extensions[row["id"]] = row
    return created(serialize.extension(row))


# ====================================================== extension lifecycle
@bp.post("/therapeutic-extensions/<extension_id>/submit")
def submit_extension(extension_id):
    authenticate([RD])
    body_json()
    ext = get_extension(extension_id)

    if ext["review_status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise api_error(
            "ERR_INVALID_STATE",
            "Only a DRAFT or CHANGES_REQUESTED extension may be submitted",
        )

    item = db.menu_items.get(ext["menu_item_id"])
    cycle = None if item is None else db.menu_cycles.get(item["menu_cycle_id"])
    if cycle is not None and cycle["status"] in HEAVY_MENU_STATUSES:
        raise api_error(
            "ERR_INVALID_STATE",
            "The owning cycle is %s and can no longer accept extension submissions"
            % cycle["status"],
        )

    ext["review_status"] = "SUBMITTED"
    touch(ext)
    return ok(serialize.extension(ext))


@bp.post("/therapeutic-extensions/<extension_id>/review")
def review_extension(extension_id):
    ctx = authenticate([RD])
    body = body_json()
    decision = req_enum(body, "decision", DECISIONS)
    reviewer_note = opt_str(body, "reviewer_note")

    ext = get_extension(extension_id)

    if ext["review_status"] != "SUBMITTED":
        raise api_error("ERR_INVALID_STATE", "Only a SUBMITTED extension may be reviewed")
    if ctx["user_id"] == ext["authored_by_user_id"]:
        raise api_error(
            "ERR_SEGREGATION_OF_DUTIES",
            "The reviewing dietitian must differ from the extension's authored_by_user_id",
        )
    if decision == "REQUEST_CHANGES" and ext["review_round"] >= MAX_EXTENSION_REVIEW_ROUNDS:
        raise api_error(
            "ERR_REVIEW_ROUND_LIMIT",
            "review_round has reached the ceiling of %d" % MAX_EXTENSION_REVIEW_ROUNDS,
        )

    if decision == "APPROVE":
        ext["review_status"] = "APPROVED"
    else:
        ext["review_status"] = "CHANGES_REQUESTED"
        ext["review_round"] = ext["review_round"] + 1
    ext["reviewed_by_user_id"] = ctx["user_id"]
    ext["reviewer_note"] = reviewer_note
    touch(ext)

    item = db.menu_items.get(ext["menu_item_id"])
    if item is not None:
        derive.recompute_coverage(item)

    return ok(serialize.extension(ext))
