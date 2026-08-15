"""PurchaseAgreement endpoints: create / list / get / sign /
contingency-clearance / cancel / close / acknowledge-warranty
(PRD sections 3.3, 3.4, 3.8, 3.9)."""

import db
from constants import (
    READ_ROLES,
    ROLE_BUYER,
    BUILD_STAGES,
    STAGE_DURATIONS_DAYS,
    CONTINGENCY_TYPES,
    CONTINGENCY_ACTIONS,
    AGREEMENT_CANCEL_REASONS,
    MIN_EARNEST_CENTS,
)
from errors import (
    ApiError,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_BUYER_NOT_FOUND,
    ERR_LOT_NOT_FOUND,
    ERR_PLAN_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_STALE_LOT_VERSION,
    ERR_STALE_AGREEMENT_VERSION,
    ERR_LOT_NOT_RESERVED_BY_BUYER,
    ERR_COMMUNITY_NOT_SELLING,
    ERR_AGREEMENT_INVALID_STATE,
    ERR_CONTINGENCY_NOT_PENDING,
    ERR_CLOSE_BLOCKED,
    ERR_PLAN_NOT_IN_COMMUNITY,
    ERR_ELEVATION_NOT_AVAILABLE,
    ERR_EARNEST_BELOW_MINIMUM,
)
from middleware import authenticate, require_agreement_owner
from response import success_obj, success_list
from routes import make_blueprint
from services import (
    ser_agreement,
    recompute_estimates,
    cancel_agreement,
    close_agreement,
    milestones_of,
)
from util import (
    body_json,
    check_shape,
    require_fk,
    parse_dt,
    pagination_params,
    paginate,
    apply_filters,
)

bp = make_blueprint("agreements")

CREATE_SPEC = {
    "buyer_id": {"type": "string", "required": True},
    "lot_id": {"type": "string", "required": True},
    "plan_id": {"type": "string", "required": True},
    "elevation_name": {"type": "string", "required": True},
    "earnest_money_deposited_cents": {"type": "integer", "required": True},
    "contingency_deadline": {"type": "datetime", "required": True},
    "outside_close_date": {"type": "datetime", "required": True},
    "has_sale_of_home_contingency": {"type": "boolean"},
    "expected_lot_version": {"type": "integer", "required": True},
}

CLEARANCE_SPEC = {
    "contingency_type": {"type": "enum", "required": True, "values": CONTINGENCY_TYPES},
    "action": {"type": "enum", "required": True, "values": CONTINGENCY_ACTIONS},
    "expected_agreement_version": {"type": "integer", "required": True},
}

CANCEL_SPEC = {
    "reason": {"type": "enum", "required": True, "values": AGREEMENT_CANCEL_REASONS},
}

CONTINGENCY_FIELDS = {
    "financing": "financing_contingency_status",
    "appraisal": "appraisal_contingency_status",
    "sale_of_home": "sale_of_home_contingency_status",
}


@bp.post("/agreements")
def create_agreement():
    authenticate(["SalesAgent"])
    body = body_json()
    check_shape(body, CREATE_SPEC)
    # Existence (tier 4): body FKs validated left to right.
    require_fk("buyers", body["buyer_id"], ERR_BUYER_NOT_FOUND, "buyer")
    lot = require_fk("lots", body["lot_id"], ERR_LOT_NOT_FOUND, "lot")
    plan = require_fk("plans", body["plan_id"], ERR_PLAN_NOT_FOUND, "plan")
    # OCC (tier 6): the client priced the deal from the lot version it last saw.
    if body["expected_lot_version"] != lot["version"]:
        raise ApiError(ERR_STALE_LOT_VERSION, 412, "expected_lot_version does not match the lot's current version")
    # State (tier 7): the lot must be RESERVED by this buyer.
    if lot["status"] != "RESERVED" or lot["reserved_buyer_id"] != body["buyer_id"]:
        raise ApiError(ERR_LOT_NOT_RESERVED_BY_BUYER, 409, "lot is not RESERVED by this buyer")
    # In-community cross-references (tier 10).
    if plan["community_id"] != lot["community_id"]:
        raise ApiError(ERR_PLAN_NOT_IN_COMMUNITY, 422, "plan belongs to a different community than the lot")
    if body["elevation_name"] not in [e["name"] for e in plan["elevations"]]:
        raise ApiError(ERR_ELEVATION_NOT_AVAILABLE, 422, "elevation_name not present in plan.elevations")
    # Money guards (tier 11).
    if body["earnest_money_deposited_cents"] < MIN_EARNEST_CENTS:
        raise ApiError(ERR_EARNEST_BELOW_MINIMUM, 402, "earnest money below the trust minimum")

    agreement = db.new_entity("agreements", {
        "buyer_id": body["buyer_id"],
        "lot_id": body["lot_id"],
        "plan_id": body["plan_id"],
        "community_id": lot["community_id"],  # denormalized from the lot
        "elevation_name": body["elevation_name"],
        "earnest_money_deposited_cents": body["earnest_money_deposited_cents"],
        "contingency_deadline": body["contingency_deadline"],
        "outside_close_date": body["outside_close_date"],
        "has_sale_of_home_contingency": body.get("has_sale_of_home_contingency", False),
        "status": "DRAFT",
        "financing_contingency_status": None,   # initialized at signing
        "appraisal_contingency_status": None,
        "sale_of_home_contingency_status": None,
        "current_stage": "NOT_STARTED",
        "lot_price_snapshot_cents": None,       # captured at signing
        "plan_price_snapshot_cents": None,
        "elevation_price_snapshot_cents": None,
        "provisional_total_cents": None,        # fixed at signing
        "final_total_cents": None,              # set at close
        "estimated_close_standard": None,       # computed at signing
        "estimated_close_padded": None,
        "slippage_flag": False,
        "cancel_reason": None,
        "refund_amount_cents": None,
        "forfeited_amount_cents": None,
        "warranty_status": "NONE",
        "warranty_term_months": 0,
        "warranty_enrolled_at": None,
        "_deadline_dt": parse_dt(body["contingency_deadline"], "contingency_deadline"),
        "_outside_dt": parse_dt(body["outside_close_date"], "outside_close_date"),
    })
    # Linking the agreement marks the lot: version increments though status
    # does not yet change.
    db.touch(lot)
    return success_obj(ser_agreement(agreement), 201)


@bp.get("/agreements")
def list_agreements():
    user_id, role = authenticate(READ_ROLES)
    limit, offset = pagination_params()
    items = db.all_of("agreements")
    if role == ROLE_BUYER:
        items = [a for a in items if a["buyer_id"] == user_id]
    items = apply_filters(items, ["buyer_id", "lot_id", "plan_id", "community_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([ser_agreement(a) for a in page], limit, offset, total, has_more)


@bp.get("/agreements/<aid>")
def get_agreement(aid):
    user_id, role = authenticate(READ_ROLES)
    agreement = require_fk("agreements", aid, ERR_AGREEMENT_NOT_FOUND, "agreement")
    # A Buyer reading a single agreement may read only their own.
    require_agreement_owner(agreement, user_id, role)
    return success_obj(ser_agreement(agreement), 200)


@bp.post("/agreements/<aid>/sign")
def sign_agreement(aid):
    user_id, role = authenticate(["Buyer"])
    agreement = require_fk("agreements", aid, ERR_AGREEMENT_NOT_FOUND, "agreement")
    require_agreement_owner(agreement, user_id, role)
    # State tier (scaffold order): agreement DRAFT, lot RESERVED by the buyer,
    # community SELLING.
    if agreement["status"] != "DRAFT":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, 409, "only a DRAFT agreement can be signed")
    lot = db.get("lots", agreement["lot_id"])
    if lot is None or lot["status"] != "RESERVED" or lot["reserved_buyer_id"] != agreement["buyer_id"]:
        raise ApiError(ERR_LOT_NOT_RESERVED_BY_BUYER, 409, "lot is not RESERVED by this buyer")
    community = db.get("communities", agreement["community_id"])
    if community is None or community["status"] != "SELLING":
        raise ApiError(ERR_COMMUNITY_NOT_SELLING, 409, "community is not open for sales")

    now = db.now()
    plan = db.get("plans", agreement["plan_id"])
    elevation_price = next(
        e["price_cents"] for e in plan["elevations"] if e["name"] == agreement["elevation_name"]
    )
    # Price snapshots frozen at signing; provisional total never changes after.
    agreement["lot_price_snapshot_cents"] = lot["release_price_cents"]
    agreement["plan_price_snapshot_cents"] = plan["base_price_cents"]
    agreement["elevation_price_snapshot_cents"] = elevation_price
    agreement["provisional_total_cents"] = (
        lot["release_price_cents"] + plan["base_price_cents"] + elevation_price
    )
    # Contingency trackers initialized.
    agreement["financing_contingency_status"] = "PENDING"
    agreement["appraisal_contingency_status"] = "PENDING"
    agreement["sale_of_home_contingency_status"] = (
        "PENDING" if agreement["has_sale_of_home_contingency"] else "WAIVED"
    )
    agreement["current_stage"] = "PRE_CONSTRUCTION"
    agreement["status"] = "PENDING_CONTINGENCIES"

    # The construction plan: five milestones, one per build stage in order.
    for seq, stage in enumerate(BUILD_STAGES, start=1):
        db.new_entity("milestones", {
            "agreement_id": agreement["id"],
            "stage": stage,
            "sequence_no": seq,
            "planned_duration_days": STAGE_DURATIONS_DAYS[stage],
            "status": "NOT_STARTED",
            "completed_at": None,
            "buyer_notified_at": None,
        })

    recompute_estimates(agreement, now)

    # Lot RESERVED -> SOLD; reserved_buyer_id retained as purchaser record.
    lot["status"] = "SOLD"
    lot["hold_expires_at"] = None
    db.touch(lot)

    db.touch(agreement)
    return success_obj(ser_agreement(agreement), 200)


@bp.post("/agreements/<aid>/contingency-clearance")
def contingency_clearance(aid):
    authenticate(["SalesAgent"])
    body = body_json()
    check_shape(body, CLEARANCE_SPEC)
    agreement = require_fk("agreements", aid, ERR_AGREEMENT_NOT_FOUND, "agreement")
    # OCC (tier 6).
    if body["expected_agreement_version"] != agreement["version"]:
        raise ApiError(ERR_STALE_AGREEMENT_VERSION, 412, "expected_agreement_version does not match the agreement's current version")
    # State (tier 7): only a tracker still PENDING may be cleared or waived.
    field = CONTINGENCY_FIELDS[body["contingency_type"]]
    if agreement[field] != "PENDING":
        raise ApiError(ERR_CONTINGENCY_NOT_PENDING, 409, "contingency is not PENDING")
    agreement[field] = body["action"]
    db.touch(agreement)
    # Bubble-up: when all three trackers rest in {CLEARED, WAIVED}, the
    # agreement promotes itself — a further mutation, a further version bump.
    if agreement["status"] == "PENDING_CONTINGENCIES" and all(
        agreement[f] in ("CLEARED", "WAIVED") for f in CONTINGENCY_FIELDS.values()
    ):
        agreement["status"] = "CONTINGENCIES_CLEARED"
        db.touch(agreement)
    return success_obj(ser_agreement(agreement), 200)


@bp.post("/agreements/<aid>/cancel")
def cancel(aid):
    user_id, role = authenticate(["Buyer", "SalesAgent"])
    body = body_json()
    check_shape(body, CANCEL_SPEC)
    agreement = require_fk("agreements", aid, ERR_AGREEMENT_NOT_FOUND, "agreement")
    require_agreement_owner(agreement, user_id, role)
    if agreement["status"] not in ("DRAFT", "PENDING_CONTINGENCIES", "CONTINGENCIES_CLEARED"):
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, 409, "agreement cannot be cancelled from its current status")
    cancel_agreement(agreement, body["reason"], db.now())
    return success_obj(ser_agreement(agreement), 200)


@bp.post("/agreements/<aid>/close")
def close(aid):
    authenticate(["SalesAgent"])
    agreement = require_fk("agreements", aid, ERR_AGREEMENT_NOT_FOUND, "agreement")
    if agreement["status"] != "CONTINGENCIES_CLEARED":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, 409, "close requires CONTINGENCIES_CLEARED")
    if any(m["status"] != "COMPLETE" for m in milestones_of(agreement["id"])):
        raise ApiError(ERR_CLOSE_BLOCKED, 409, "all five milestones must be COMPLETE before close")
    close_agreement(agreement, db.now())
    return success_obj(ser_agreement(agreement), 200)


@bp.post("/agreements/<aid>/acknowledge-warranty")
def acknowledge_warranty(aid):
    user_id, role = authenticate(["Buyer"])
    agreement = require_fk("agreements", aid, ERR_AGREEMENT_NOT_FOUND, "agreement")
    require_agreement_owner(agreement, user_id, role)
    if not (agreement["status"] == "CLOSED" and agreement["warranty_status"] == "ENROLLED"):
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, 409, "warranty is not ENROLLED on a CLOSED agreement")
    # Self-transition restricted to the warranty dimension; status stays CLOSED.
    agreement["warranty_status"] = "ACKNOWLEDGED"
    db.touch(agreement)
    return success_obj(ser_agreement(agreement), 200)
