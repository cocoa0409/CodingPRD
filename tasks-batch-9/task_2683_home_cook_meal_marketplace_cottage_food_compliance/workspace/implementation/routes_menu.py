"""Menu items: drafting, submission for review and the dense approval gate."""
from flask import Blueprint

import calc
import services
import validation as v
from auth import (
    ANONYMOUS,
    COMPLIANCE_REVIEWER,
    COOK,
    DINER,
    PLATFORM_ADMIN,
    SAFETY_OFFICER,
    acting_user,
    guard,
    require_owner,
)
from core import ApiError, created, db, new_row, ok, parse_date, public, touch
from listing import list_rows

bp = Blueprint("menu", __name__)

ITEM_READ_ROLES = [
    ANONYMOUS,
    COOK,
    DINER,
    COMPLIANCE_REVIEWER,
    SAFETY_OFFICER,
    PLATFORM_ADMIN,
]


def find_item(item_id):
    item = db.menu_items.get(item_id)
    if item is None:
        raise ApiError("ERR_MENU_ITEM_NOT_FOUND")
    return item


@bp.route("/menu-items", methods=["POST"])
@guard([COOK, PLATFORM_ADMIN])
def create_item():
    body = v.body()
    cook_id = v.s_id(body, "cook_id")
    name = v.s_str(body, "name", 1, 120)
    category = v.s_enum(body, "food_category", v.FOOD_CATEGORIES)
    allergens = v.s_enum_list(body, "allergens", v.ALLERGENS, allow_empty=True)
    attested = v.s_bool(body, "allergen_free_attested", required=False, default=False)
    shelf_life = v.s_int(body, "shelf_life_days", minimum=1)
    refrigerated = v.s_bool(body, "requires_refrigeration")
    handoff_mode = v.s_enum(body, "handoff_mode", v.HANDOFF_MODES)
    price = v.s_int(body, "unit_price_cents", minimum=1)
    label_fields = v.s_str_list(body, "label_fields", allow_empty=True)

    cook = db.cooks.get(cook_id)
    if cook is None:
        raise ApiError("ERR_COOK_NOT_FOUND")
    require_owner(cook_id)
    policy = calc.policy_for_cook(cook)

    row = new_row(
        db.menu_items,
        {
            "cook_id": cook_id,
            "name": name,
            "food_category": category,
            "allergens": allergens,
            "allergen_free_attested": attested if attested is not None else False,
            "shelf_life_days": shelf_life,
            "requires_refrigeration": refrigerated,
            "handoff_mode": handoff_mode,
            "unit_price_cents": price,
            "label_fields": label_fields,
            "label_compliance_status": "MISSING_FIELDS",
            "review_status": "DRAFT",
            "revision_round": 0,
            "approved_by_user_id": None,
            "approved_at": None,
            "delist_reason": None,
        },
    )
    row["label_compliance_status"] = services.compute_label_status(row, policy)
    return created(public(row))


@bp.route("/menu-items/<item_id>", methods=["GET"])
@guard(ITEM_READ_ROLES)
def get_item(item_id):
    return ok(public(find_item(item_id)))


@bp.route("/menu-items", methods=["GET"])
@guard(ITEM_READ_ROLES)
def list_items():
    return list_rows(list(db.menu_items.values()), ["cook_id", "review_status", "food_category"])


@bp.route("/menu-items/<item_id>/submit", methods=["POST"])
@guard([COOK, PLATFORM_ADMIN])
def submit_item(item_id):
    v.body()
    item = find_item(item_id)
    require_owner(item["cook_id"])
    cook = db.cooks[item["cook_id"]]

    status = item["review_status"]
    if status not in ("DRAFT", "REVISION_REQUESTED", "DELISTED"):
        raise ApiError(
            "ERR_INVALID_MENU_ITEM_TRANSITION", "no submission edge from %s" % status
        )
    if status == "DELISTED" and cook["cap_status"] == "CAP_REACHED":
        raise ApiError(
            "ERR_INVALID_MENU_ITEM_TRANSITION",
            "a cook at the annual cottage-food cap cannot relist",
        )
    if cook["onboarding_status"] != "ACTIVE":
        raise ApiError("ERR_COOK_NOT_ACTIVE", "the owning cook is not ACTIVE")
    if cook["compliance_standing"] not in ("CLEAR", "WARNED"):
        raise ApiError("ERR_COOK_SUSPENDED", "the owning cook is suspended or revoked")

    services.refresh_label_status(item)
    item["review_status"] = "UNDER_REVIEW"
    if status == "DELISTED":
        item["delist_reason"] = None
    touch(item)
    return ok(public(item))


def _sod_conflict(cook_id, actor):
    """Priority 26: the reviewer who graded the kitchen inspection may not approve."""
    if actor is None:
        return False
    for doc in calc.cook_documents(cook_id, "KITCHEN_INSPECTION"):
        if doc.get("reviewed_by_user_id") and doc["reviewed_by_user_id"] == actor:
            return True
    return False


@bp.route("/menu-items/<item_id>/review", methods=["POST"])
@guard([COMPLIANCE_REVIEWER, PLATFORM_ADMIN])
def review_item(item_id):
    body = v.body()
    decision = v.s_enum(body, "decision", ["APPROVE", "REQUEST_REVISION", "REJECT", "DELIST"])
    notes = v.s_str(body, "allergen_review_notes", 0, 4000, required=False)
    v.s_str(body, "revision_note", 0, 4000, required=False)

    item = find_item(item_id)
    cook = db.cooks[item["cook_id"]]
    policy = calc.policy_for_cook(cook)
    status = item["review_status"]
    # label_compliance_status is recomputed on every review.
    fresh_label = services.compute_label_status(item, policy)

    if decision == "DELIST":
        if status != "APPROVED":
            raise ApiError(
                "ERR_INVALID_MENU_ITEM_TRANSITION", "DELIST is legal only from APPROVED"
            )
        item["label_compliance_status"] = fresh_label
        item["review_status"] = "DELISTED"
        item["delist_reason"] = "PLATFORM_REQUEST"
        touch(item)
        return ok(public(item))

    if status != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_MENU_ITEM_TRANSITION", "%s requires an item UNDER_REVIEW" % decision
        )

    if decision == "REQUEST_REVISION":
        item["label_compliance_status"] = fresh_label
        rounds = int(item["revision_round"])
        item["review_status"] = "REVISION_REQUESTED" if rounds < 2 else "REJECTED"
        item["revision_round"] = rounds + 1
        touch(item)
        return ok(public(item))

    if decision == "REJECT":
        item["label_compliance_status"] = fresh_label
        item["review_status"] = "REJECTED"
        touch(item)
        return ok(public(item))

    # ---------------------------------------------------------------- APPROVE
    if cook["compliance_standing"] in ("SUSPENDED", "REVOKED"):
        raise ApiError(
            "ERR_INVALID_MENU_ITEM_TRANSITION", "a suspended or revoked cook cannot be approved"
        )
    if notes is None or not notes.strip():
        raise ApiError(
            "ERR_INVALID_MENU_ITEM_TRANSITION", "allergen_review_notes is required to approve"
        )
    if cook["cap_status"] == "CAP_REACHED":
        raise ApiError(
            "ERR_INVALID_MENU_ITEM_TRANSITION", "the cook has reached the annual cottage-food cap"
        )
    if not calc.has_live_cert(cook["id"]):
        raise ApiError("ERR_CERT_EXPIRED", "no unexpired VERIFIED food-handler certificate")
    if (
        item["food_category"] == "TCS"
        and policy["tcs_requires_commercial_kitchen"]
        and cook["verified_kitchen_type"] != "COMMERCIAL_SHARED"
    ):
        raise ApiError(
            "ERR_TCS_REQUIRES_COMMERCIAL_KITCHEN", "TCS food requires a commercial shared kitchen"
        )
    if not item["allergens"] and not item["allergen_free_attested"]:
        raise ApiError("ERR_ALLERGEN_DISCLOSURE_MISSING", "no allergen disclosure on the item")
    if _sod_conflict(cook["id"], acting_user()):
        raise ApiError(
            "ERR_SOD_SAME_OFFICER", "the kitchen-inspection reviewer may not approve this item"
        )
    if not item["requires_refrigeration"] and int(item["shelf_life_days"]) > int(
        policy["max_shelf_life_days_non_refrigerated"]
    ):
        raise ApiError("ERR_SHELF_LIFE_EXCEEDS_POLICY", "shelf life exceeds the state ceiling")
    if fresh_label != "COMPLIANT":
        raise ApiError("ERR_LABEL_FIELDS_INCOMPLETE", "label_fields is missing required keys")

    item["label_compliance_status"] = fresh_label
    item["review_status"] = "APPROVED"
    item["approved_by_user_id"] = acting_user()
    item["approved_at"] = db.now_iso()
    item["delist_reason"] = None
    touch(item)
    return ok(public(item))
