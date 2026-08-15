"""SeedProgram endpoints: CRUD + open / close_sales / settle."""

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION, ERR_PROGRAM_NOT_SETTLABLE
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from services import close_sales_sweep, settle_sweep
from util import body_json, check_shape, pagination_params, paginate, apply_filters, require_fk, dt_of

bp = make_blueprint("programs")

ALL_ROLES = ["DealerAdmin", "SalesRep", "Agronomist", "Grower", "ClaimsAdjuster"]

TIER_EARLY = {"cutoff_at": {"type": "datetime", "required": True},
              "discount_bps": {"type": "integer", "required": True}}
TIER_PREPAY = {"pay_by": {"type": "datetime", "required": True},
               "discount_bps": {"type": "integer", "required": True}}
TIER_REBATE = {"min_units": {"type": "integer", "required": True},
               "rebate_bps": {"type": "integer", "required": True}}
TIER_COMMISSION = {"min_net_units": {"type": "integer", "required": True},
                   "bonus_bps": {"type": "integer", "required": True}}

CREATE_SPEC = {
    "name": {"type": "string", "required": True},
    "crop_year": {"type": "integer", "required": True},
    "early_order_tiers": {"type": "array", "required": True, "items": TIER_EARLY},
    "prepay_tiers": {"type": "array", "items": TIER_PREPAY},
    "volume_rebate_tiers": {"type": "array", "items": TIER_REBATE},
    "return_window_end": {"type": "datetime", "required": True},
    "return_restocking_bps": {"type": "integer", "required": True},
    "returns_untreated_only": {"type": "boolean", "required": True},
    "replant_claim_window_days": {"type": "integer", "required": True, "min": 0},
    "replant_replacement_discount_bps": {"type": "integer", "required": True},
    "daily_delivery_capacity_units": {"type": "integer", "required": True, "min": 1},
    "delivery_window_start": {"type": "datetime", "required": True},
    "delivery_window_end": {"type": "datetime", "required": True},
    "sales_close_at": {"type": "datetime", "required": True},
    "commission_base_bps": {"type": "integer", "required": True},
    "commission_volume_tiers": {"type": "array", "items": TIER_COMMISSION},
    "min_plot_replications": {"type": "integer", "required": True, "min": 1},
}


@bp.post("/programs")
def create_program():
    authenticate(["DealerAdmin"])
    body = body_json()
    check_shape(body, CREATE_SPEC)
    program = db.new_entity("programs", {
        "name": body["name"],
        "crop_year": body["crop_year"],
        "status": "DRAFT",
        "early_order_tiers": body["early_order_tiers"],
        "prepay_tiers": body.get("prepay_tiers", []),
        "volume_rebate_tiers": body.get("volume_rebate_tiers", []),
        "return_window_end": body["return_window_end"],
        "return_restocking_bps": body["return_restocking_bps"],
        "returns_untreated_only": body["returns_untreated_only"],
        "replant_claim_window_days": body["replant_claim_window_days"],
        "replant_replacement_discount_bps": body["replant_replacement_discount_bps"],
        "daily_delivery_capacity_units": body["daily_delivery_capacity_units"],
        "delivery_window_start": body["delivery_window_start"],
        "delivery_window_end": body["delivery_window_end"],
        "sales_close_at": body["sales_close_at"],
        "commission_base_bps": body["commission_base_bps"],
        "commission_volume_tiers": body.get("commission_volume_tiers", []),
        "min_plot_replications": body["min_plot_replications"],
        "opened_at": None,
        "sales_closed_at": None,
        "settled_at": None,
    })
    return success_obj(db.public(program), 201)


@bp.get("/programs/<pid>")
def get_program(pid):
    authenticate(ALL_ROLES)
    program = require_fk("programs", pid, "program")
    return success_obj(db.public(program), 200)


@bp.get("/programs")
def list_programs():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("programs"), ["status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(p) for p in page], limit, offset, total, has_more)


@bp.post("/programs/<pid>/open")
def open_program(pid):
    authenticate(["DealerAdmin"])
    program = require_fk("programs", pid, "program")
    # Structural preconditions (ERR_INVALID_REQUEST) precede the state check
    # per adjudication order (request-shape tier before state tier).
    tiers = program.get("early_order_tiers", [])
    if not tiers:
        raise ApiError(ERR_INVALID_REQUEST, 400, "early_order_tiers must be non-empty")
    cutoffs = [dt_of(t, "cutoff_at") for t in tiers]
    if any(cutoffs[i] > cutoffs[i + 1] for i in range(len(cutoffs) - 1)):
        raise ApiError(ERR_INVALID_REQUEST, 400, "early_order_tiers must be sorted ascending by cutoff_at")
    if not (dt_of(program, "return_window_end") > dt_of(program, "delivery_window_end")):
        raise ApiError(ERR_INVALID_REQUEST, 400, "return_window_end must be after delivery_window_end")
    if program["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a DRAFT program can be opened")
    program["status"] = "OPEN"
    program["opened_at"] = db.fmt_ts(db.now())
    db.touch(program)
    db.new_entity("commission_statements", {
        "program_id": program["id"],
        "status": "ACCRUING",
        "gross_sales_cents": 0,
        "return_credits_cents": 0,
        "net_sales_cents": 0,
        "volume_units": 0,
        "base_commission_cents": 0,
        "volume_bonus_bps": 0,
        "volume_bonus_cents": 0,
        "total_commission_cents": 0,
        "finalized_at": None,
        "paid_at": None,
    })
    return success_obj(db.public(program), 200)


@bp.post("/programs/<pid>/close_sales")
def close_sales(pid):
    authenticate(["DealerAdmin"])
    program = require_fk("programs", pid, "program")
    if program["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only an OPEN program can close sales")
    if not (db.now() >= dt_of(program, "sales_close_at")):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "logical clock has not reached sales_close_at")
    close_sales_sweep(program)
    program["status"] = "SALES_CLOSED"
    program["sales_closed_at"] = db.fmt_ts(db.now())
    db.touch(program)
    return success_obj(db.public(program), 200)


@bp.post("/programs/<pid>/settle")
def settle(pid):
    authenticate(["DealerAdmin"])
    program = require_fk("programs", pid, "program")
    if program["status"] != "SALES_CLOSED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a SALES_CLOSED program can settle")
    if not (db.now() > dt_of(program, "return_window_end")):
        raise ApiError(ERR_PROGRAM_NOT_SETTLABLE, 409, "logical clock must be strictly past return_window_end")
    program_orders = [o for o in db.all_of("orders") if o["program_id"] == program["id"]]
    if any(o["status"] == "COMPLIANCE_HOLD" for o in program_orders):
        raise ApiError(ERR_PROGRAM_NOT_SETTLABLE, 409, "program has orders in COMPLIANCE_HOLD")
    order_ids = {o["id"] for o in program_orders}
    if any(
        c["order_id"] in order_ids and c["status"] in ("FILED", "UNDER_REVIEW", "INFO_REQUESTED")
        for c in db.all_of("replant_claims")
    ):
        raise ApiError(ERR_PROGRAM_NOT_SETTLABLE, 409, "program has open replant claims")
    if any(
        t["order_id"] in order_ids and t["status"] == "SCHEDULED"
        for t in db.all_of("delivery_tickets")
    ):
        raise ApiError(ERR_PROGRAM_NOT_SETTLABLE, 409, "program has scheduled delivery tickets")
    settle_sweep(program)
    program["status"] = "SETTLED"
    program["settled_at"] = db.fmt_ts(db.now())
    db.touch(program)
    return success_obj(db.public(program), 200)
