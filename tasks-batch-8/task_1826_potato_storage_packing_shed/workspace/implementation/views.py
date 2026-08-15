"""All API endpoints (PRD section 4), with validation priority per PRD 2.9:
auth(1) -> rbac/ownership(2) -> existence(3) -> OCC(4) -> state(5) ->
food-safety(6) -> cross-reference(7) -> temporal(8) -> shape(9) -> fiscal(10).
"""
from decimal import Decimal

from flask import Blueprint, g, request

import logic
from auth import require_auth, roles_allowed
from store import STORE, CLOCK
from util import (
    ApiError,
    api_err,
    invalid,
    success,
    get_body,
    check_unknown,
    fld_string,
    fld_decimal,
    fld_int,
    fld_enum,
    fld_dt,
    fld_version,
    paginate,
    sort_created,
    serialize,
    rhu,
    TWO,
    FOUR,
    parse_dt_value,
)

bp = Blueprint("potato_shed", __name__, url_prefix="/potato-shed")
bp.before_request(require_auth)

ALL_STAFF = (
    "ShedAdmin",
    "IntakeClerk",
    "StorageManager",
    "QualityAssuranceManager",
    "SalesManager",
    "PackLineSupervisor",
    "SettlementClerk",
)

GROWER_FIELDS = ["id", "name", "grower_code", "region", "created_at", "updated_at", "version"]
SHED_FIELDS = [
    "id", "name", "posture", "consecutive_wash_failures", "wash_quarantine_flag",
    "audit_failed_flag", "created_at", "updated_at", "version",
]
BIN_FIELDS = [
    "id", "shed_id", "bin_code", "capacity_cwt", "variety_lock", "occupied_cwt",
    "created_at", "updated_at", "version",
]
LOT_FIELDS = [
    "id", "grower_id", "bin_id", "variety", "harvest_date", "original_weight_cwt",
    "shrink_cwt", "packed_total_cwt", "cull_total_cwt", "condemned_cwt",
    "processing_credit_cwt", "available_cwt", "reserved_cwt", "storage_status",
    "quality_status", "binned_at", "closed_at", "last_inhibitor_applied_at",
    "inhibitor_application_count", "created_at", "updated_at", "version",
]
ASSESSMENT_FIELDS = [
    "id", "field_lot_id", "assessment_date", "us1_pct", "us2_pct", "cull_pct",
    "cumulative_shrink_cwt", "packable_fraction", "created_at",
]
CONTRACT_FIELDS = [
    "id", "buyer_name", "variety", "committed_volume_cwt", "price_cents_per_cwt",
    "grade_min_us1_pct", "delivery_window_start", "delivery_window_end",
    "priority_rank", "remaining_committed_cwt", "allocated_active_cwt",
    "packed_to_date_cwt", "status", "created_at", "updated_at", "version",
]
ORDER_FIELDS = [
    "id", "order_type", "contract_id", "shed_id", "variety", "pack_unit_weight_lbs",
    "grade_min_us1_pct", "requested_packed_cwt", "allocation_policy",
    "market_price_cents_per_cwt", "packed_to_date_cwt", "reservations", "status",
    "created_at", "updated_at", "version",
]
RUN_FIELDS = [
    "id", "pack_order_id", "scheduled_start", "scheduled_end", "status",
    "packed_total_cwt", "cull_total_cwt", "completed_at", "created_at",
    "updated_at", "version",
]
DRAW_FIELDS = [
    "id", "pack_run_id", "field_lot_id", "raw_drawn_cwt", "packed_cwt", "us1_cwt",
    "us2_cwt", "cull_cwt", "cull_channel", "created_at",
]
CHECK_FIELDS = [
    "id", "shed_id", "measured_at", "turbidity_ntu", "chlorine_ppm",
    "water_temp_f", "result", "created_at",
]
AUDIT_FIELDS = [
    "id", "shed_id", "field_work_date", "status", "outcome", "critical_findings",
    "minor_findings", "closed_at", "created_at", "updated_at", "version",
]
SETTLEMENT_FIELDS = [
    "id", "grower_id", "season_label", "status", "packed_cwt_basis",
    "pool_price_cents", "gross_cents", "storage_fees_cents",
    "inhibitor_fees_cents", "processing_credits_cents", "net_payable_cents",
    "finalized_by_clerk_id", "paid_at", "created_at", "updated_at", "version",
]


# ---------------------------------------------------------------------------
# Existence helpers (404s)
# ---------------------------------------------------------------------------
def get_grower(gid):
    r = STORE["growers"].get(gid)
    if r is None:
        api_err("ERR_GROWER_NOT_FOUND", 404, "grower id does not exist")
    return r


def get_shed(sid):
    r = STORE["sheds"].get(sid)
    if r is None:
        api_err("ERR_SHED_NOT_FOUND", 404, "shed id does not exist")
    return r


def get_lot(lid):
    r = STORE["lots"].get(lid)
    if r is None:
        api_err("ERR_FIELD_LOT_NOT_FOUND", 404, "field lot id does not exist")
    return r


def get_contract(cid):
    r = STORE["contracts"].get(cid)
    if r is None:
        api_err("ERR_CONTRACT_NOT_FOUND", 404, "contract id does not exist")
    return r


def get_order(oid):
    r = STORE["orders"].get(oid)
    if r is None:
        api_err("ERR_PACK_ORDER_NOT_FOUND", 404, "pack order id does not exist")
    return r


def get_run(rid):
    r = STORE["runs"].get(rid)
    if r is None:
        api_err("ERR_PACK_RUN_NOT_FOUND", 404, "pack run id does not exist")
    return r


def get_audit(aid):
    r = STORE["audits"].get(aid)
    if r is None:
        api_err("ERR_AUDIT_NOT_FOUND", 404, "audit id does not exist")
    return r


def get_settlement(sid):
    r = STORE["settlements"].get(sid)
    if r is None:
        api_err("ERR_SETTLEMENT_NOT_FOUND", 404, "settlement id does not exist")
    return r


def list_response(items, fields):
    items = sort_created(items)
    page, pagination = paginate(items)
    return success([serialize(r, fields) for r in page], 200, pagination)


# ===========================================================================
# Growers
# ===========================================================================
@bp.post("/growers")
@roles_allowed("ShedAdmin")
def create_grower():
    data = get_body()
    check_unknown(data, ["name", "grower_code", "region"])
    name = fld_string(data, "name")
    code = fld_string(data, "grower_code")
    region = fld_string(data, "region", required=False)
    for other in STORE["growers"].values():
        if other["grower_code"] == code:
            invalid("grower_code must be unique across growers")
    rec = logic.new_record()
    rec.update({"name": name, "grower_code": code, "region": region})
    STORE["growers"][rec["id"]] = rec
    return success(serialize(rec, GROWER_FIELDS), 201)


@bp.get("/growers/<gid>")
@roles_allowed("ShedAdmin", "IntakeClerk", "StorageManager", "SettlementClerk", "Grower")
def read_grower(gid):
    if g.user_role == "Grower" and gid != g.user_id:
        api_err("ERR_INSUFFICIENT_PERMISSIONS", 403, "growers may only read their own record")
    rec = get_grower(gid)
    return success(serialize(rec, GROWER_FIELDS))


# ===========================================================================
# Sheds / bins / wash checks / audits
# ===========================================================================
@bp.post("/sheds")
@roles_allowed("ShedAdmin")
def create_shed():
    data = get_body()
    check_unknown(data, ["name"])
    name = fld_string(data, "name")
    rec = logic.new_record()
    rec.update(
        {
            "name": name,
            "posture": "NORMAL",
            "consecutive_wash_failures": 0,
            "wash_quarantine_flag": False,
            "audit_failed_flag": False,
        }
    )
    STORE["sheds"][rec["id"]] = rec
    return success(serialize(rec, SHED_FIELDS), 201)


@bp.get("/sheds/<sid>")
@roles_allowed(*ALL_STAFF)
def read_shed(sid):
    rec = get_shed(sid)
    return success(serialize(rec, SHED_FIELDS))


@bp.post("/sheds/<sid>/bins")
@roles_allowed("ShedAdmin")
def create_bin(sid):
    shed = get_shed(sid)
    data = get_body()
    check_unknown(data, ["bin_code", "capacity_cwt"])
    code = fld_string(data, "bin_code")
    capacity = fld_decimal(data, "capacity_cwt", gt=0)
    for other in STORE["bins"].values():
        if other["shed_id"] == shed["id"] and other["bin_code"] == code:
            invalid("bin_code must be unique within the shed")
    rec = logic.new_record()
    rec.update(
        {
            "shed_id": shed["id"],
            "bin_code": code,
            "capacity_cwt": capacity,
            "variety_lock": None,
            "occupied_cwt": Decimal("0"),
        }
    )
    STORE["bins"][rec["id"]] = rec
    return success(serialize(rec, BIN_FIELDS), 201)


@bp.get("/sheds/<sid>/bins")
@roles_allowed("ShedAdmin", "IntakeClerk", "StorageManager", "QualityAssuranceManager", "SalesManager")
def list_bins(sid):
    shed = get_shed(sid)
    return list_response(
        [b for b in STORE["bins"].values() if b["shed_id"] == shed["id"]], BIN_FIELDS
    )


# ===========================================================================
# Field lots
# ===========================================================================
@bp.post("/growers/<gid>/field-lots")
@roles_allowed("IntakeClerk")
def create_field_lot(gid):
    grower = get_grower(gid)
    data = get_body()
    check_unknown(data, ["variety", "harvest_date", "original_weight_cwt"])
    variety = fld_enum(data, "variety", logic.VARIETIES)
    harvest_raw, harvest_dt = fld_dt(data, "harvest_date")
    weight = fld_decimal(data, "original_weight_cwt", gt=0)
    rec = logic.new_record()
    rec.update(
        {
            "grower_id": grower["id"],
            "bin_id": None,
            "variety": variety,
            "harvest_date": harvest_raw,
            "_dt_harvest_date": harvest_dt,
            "original_weight_cwt": weight,
            "shrink_cwt": Decimal("0"),
            "packed_total_cwt": Decimal("0"),
            "cull_total_cwt": Decimal("0"),
            "condemned_cwt": Decimal("0"),
            "processing_credit_cwt": Decimal("0"),
            "available_cwt": weight,
            "reserved_cwt": Decimal("0"),
            "storage_status": "INTAKE",
            "quality_status": "CLEAR",
            "binned_at": None,
            "closed_at": None,
            "last_inhibitor_applied_at": None,
            "inhibitor_application_count": 0,
            "_dt_binned_at": None,
            "_dt_closed_at": None,
        }
    )
    STORE["lots"][rec["id"]] = rec
    return success(serialize(rec, LOT_FIELDS), 201)


@bp.get("/field-lots/<lid>")
@roles_allowed(*ALL_STAFF, "Grower")
def read_field_lot(lid):
    lot = get_lot(lid)
    if g.user_role == "Grower" and lot["grower_id"] != g.user_id:
        api_err("ERR_INSUFFICIENT_PERMISSIONS", 403, "growers may only read their own lots")
    return success(serialize(lot, LOT_FIELDS))


@bp.get("/field-lots")
@roles_allowed(*ALL_STAFF, "Grower")
def list_field_lots():
    items = list(STORE["lots"].values())
    if g.user_role == "Grower":
        items = [l for l in items if l["grower_id"] == g.user_id]
    f_grower = request.args.get("grower_id")
    f_bin = request.args.get("bin_id")
    f_variety = request.args.get("variety")
    f_status = request.args.get("storage_status")
    if f_grower is not None:
        items = [l for l in items if l["grower_id"] == f_grower]
    if f_bin is not None:
        items = [l for l in items if l["bin_id"] == f_bin]
    if f_variety is not None:
        items = [l for l in items if l["variety"] == f_variety]
    if f_status is not None:
        items = [l for l in items if l["storage_status"] == f_status]
    return list_response(items, LOT_FIELDS)


@bp.post("/field-lots/<lid>/bin-assignment")
@roles_allowed("IntakeClerk")
def assign_bin(lid):
    lot = get_lot(lid)
    data = get_body()
    check_unknown(data, ["bin_id"])
    bin_id = data.get("bin_id")
    if not isinstance(bin_id, str) or bin_id == "":
        invalid("missing required field: bin_id")
    b = STORE["bins"].get(bin_id)
    if b is None:
        api_err("ERR_BIN_NOT_FOUND", 404, "bin_id reference does not exist")
    if lot["storage_status"] != "INTAKE":
        api_err("ERR_LOT_INVALID_STATE", 409, "lot must be INTAKE to be assigned to a bin")
    shed = STORE["sheds"][b["shed_id"]]
    if shed["posture"] == "QUARANTINED":
        api_err("ERR_SHED_QUARANTINED", 409, "shed is quarantined; bin assignment blocked")
    if shed["posture"] == "RESTRICTED":
        api_err("ERR_SHED_RESTRICTED", 409, "shed is restricted; bin assignment blocked")
    if b["variety_lock"] is not None and b["variety_lock"] != lot["variety"]:
        api_err("ERR_BIN_VARIETY_MISMATCH", 409, "bin variety_lock differs from lot variety")
    logic.recompute_bin(b)
    if b["occupied_cwt"] + lot["available_cwt"] > b["capacity_cwt"]:
        api_err("ERR_BIN_CAPACITY_EXCEEDED", 422, "bin capacity would be exceeded")
    lot["bin_id"] = b["id"]
    lot["binned_at"] = logic.clock_stamp()
    lot["_dt_binned_at"] = logic.clock_now()
    lot["storage_status"] = "BINNED"
    logic.touch(lot)
    if b["variety_lock"] is None:
        b["variety_lock"] = lot["variety"]
    logic.recompute_bin(b)
    return success(serialize(lot, LOT_FIELDS))


@bp.post("/field-lots/<lid>/assessments")
@roles_allowed("StorageManager")
def create_assessment(lid):
    lot = get_lot(lid)
    data = get_body()
    check_unknown(
        data,
        [
            "assessment_date", "us1_pct", "us2_pct", "cull_pct",
            "cumulative_shrink_cwt", "expected_field_lot_version",
        ],
    )
    # OCC (priority 4)
    expected = fld_version(data, "expected_field_lot_version")
    if expected != lot["version"]:
        api_err("ERR_STALE_VERSION", 412, "expected_field_lot_version does not match lot version")
    # State gate (priority 5)
    if lot["storage_status"] != "BINNED":
        api_err("ERR_LOT_INVALID_STATE", 409, "assessments require a BINNED lot")
    # Shape checks (priority 9)
    date_raw, date_dt = fld_dt(data, "assessment_date")
    us1 = fld_decimal(data, "us1_pct", gte=0, lte=100)
    us2 = fld_decimal(data, "us2_pct", gte=0, lte=100)
    cull = fld_decimal(data, "cull_pct", gte=0, lte=100)
    if us1 + us2 + cull != Decimal("100"):
        api_err("ERR_GRADE_PERCENT_SUM_INVALID", 422, "us1_pct + us2_pct + cull_pct must equal 100.00")
    shrink = fld_decimal(data, "cumulative_shrink_cwt", gte=0)
    prev = logic.latest_assessment(lot)
    if prev is not None and shrink < prev["cumulative_shrink_cwt"]:
        api_err("ERR_SHRINK_INVALID", 422, "cumulative_shrink_cwt must be monotonic non-decreasing")
    ceiling = (
        lot["original_weight_cwt"]
        - lot["packed_total_cwt"]
        - lot["cull_total_cwt"]
        - lot["condemned_cwt"]
    )
    if shrink > ceiling:
        api_err("ERR_SHRINK_INVALID", 422, "cumulative_shrink_cwt exceeds available ceiling")
    rec = logic.new_record(common=False)
    rec.update(
        {
            "field_lot_id": lot["id"],
            "assessment_date": date_raw,
            "_dt_assessment_date": date_dt,
            "us1_pct": us1,
            "us2_pct": us2,
            "cull_pct": cull,
            "cumulative_shrink_cwt": shrink,
            "packable_fraction": rhu((us1 + us2) / Decimal("100"), FOUR),
        }
    )
    STORE["assessments"][rec["id"]] = rec
    # Re-baseline: the new assessment REPLACES the lot's shrink baseline.
    lot["shrink_cwt"] = shrink
    logic.recompute_lot_available(lot)
    logic.touch(lot)
    logic.maybe_auto_close_lot(lot)
    return success(serialize(rec, ASSESSMENT_FIELDS), 201)


@bp.get("/field-lots/<lid>/assessments")
@roles_allowed("ShedAdmin", "StorageManager", "QualityAssuranceManager", "SettlementClerk")
def list_assessments(lid):
    lot = get_lot(lid)
    return list_response(
        [a for a in STORE["assessments"].values() if a["field_lot_id"] == lot["id"]],
        ASSESSMENT_FIELDS,
    )


@bp.post("/field-lots/<lid>/sprout-inhibitor-applications")
@roles_allowed("StorageManager")
def apply_inhibitor(lid):
    lot = get_lot(lid)
    data = get_body()
    check_unknown(data, ["applied_at"])
    # Food-safety gate (priority 6)
    if lot["quality_status"] == "ON_HOLD":
        api_err("ERR_LOT_QUALITY_HOLD", 409, "cannot apply sprout inhibitor to an ON_HOLD lot")
    applied_raw, applied_dt = fld_dt(data, "applied_at")
    # Retreat window (priority 8): at least 21 days after the previous application;
    # exactly 21 days is allowed.
    if lot["last_inhibitor_applied_at"] is not None:
        earliest = lot["_dt_last_inhibitor"] + timedelta_days(logic.RETREAT_WINDOW_DAYS)
        if applied_dt < earliest:
            api_err(
                "ERR_RETREAT_WINDOW_VIOLATION",
                409,
                "application earlier than 21 days after the previous application",
            )
    lot["inhibitor_application_count"] += 1
    lot["last_inhibitor_applied_at"] = applied_raw
    lot["_dt_last_inhibitor"] = applied_dt
    logic.touch(lot)
    return success(serialize(lot, LOT_FIELDS))


def timedelta_days(days):
    from datetime import timedelta

    return timedelta(days=days)


@bp.post("/field-lots/<lid>/quality-transition")
@roles_allowed("QualityAssuranceManager")
def quality_transition(lid):
    lot = get_lot(lid)
    data = get_body()
    check_unknown(data, ["to_status", "diversion_channel"])
    to_status = fld_enum(data, "to_status", ["ON_HOLD", "CLEAR", "CONDEMNED"])
    if to_status == "ON_HOLD":
        if lot["storage_status"] != "BINNED" or lot["quality_status"] != "CLEAR":
            api_err(
                "ERR_LOT_INVALID_STATE",
                409,
                "ON_HOLD requires a BINNED lot currently CLEAR",
            )
        lot["quality_status"] = "ON_HOLD"
        logic.touch(lot)
        logic.release_lot_reservations_and_recheck(lot)
    elif to_status == "CLEAR":
        if lot["quality_status"] != "ON_HOLD":
            api_err("ERR_LOT_INVALID_STATE", 409, "release requires an ON_HOLD lot")
        shed = lot_shed(lot)
        if shed is not None and shed["posture"] == "QUARANTINED":
            api_err(
                "ERR_SHED_QUARANTINED",
                409,
                "hold release blocked while shed is quarantined",
            )
        lot["quality_status"] = "CLEAR"
        logic.touch(lot)
    else:  # CONDEMNED
        if lot["quality_status"] != "ON_HOLD":
            api_err(
                "ERR_LOT_INVALID_STATE",
                409,
                "CONDEMNED is reachable only from ON_HOLD",
            )
        channel = fld_enum(
            data, "diversion_channel", ["PROCESSING_CREDIT", "WASTE"]
        )
        lot["quality_status"] = "CONDEMNED"
        lot["condemned_cwt"] += lot["available_cwt"]
        if channel == "PROCESSING_CREDIT":
            lot["processing_credit_cwt"] += lot["available_cwt"]
        logic.recompute_lot_available(lot)
        logic.touch(lot)
        logic.maybe_auto_close_lot(lot)
        if lot["storage_status"] == "CLOSED" and lot["closed_at"] is None:
            lot["closed_at"] = logic.clock_stamp()
            lot["_dt_closed_at"] = logic.clock_now()
        logic.release_lot_reservations_and_recheck(lot)
        if lot["bin_id"] is not None:
            b = STORE["bins"].get(lot["bin_id"])
            if b is not None:
                logic.recompute_bin(b)
    return success(serialize(lot, LOT_FIELDS))


def lot_shed(lot):
    if lot["bin_id"] is None:
        return None
    b = STORE["bins"].get(lot["bin_id"])
    if b is None:
        return None
    return STORE["sheds"].get(b["shed_id"])


@bp.post("/field-lots/<lid>/close")
@roles_allowed("StorageManager")
def close_lot(lid):
    lot = get_lot(lid)
    data = get_body()
    check_unknown(data, [])
    if lot["storage_status"] != "BINNED":
        api_err("ERR_LOT_INVALID_STATE", 409, "only a BINNED lot can be manually closed")
    if lot["available_cwt"] > logic.REMNANT_MAX_CWT:
        api_err(
            "ERR_LOT_REMNANT_TOO_LARGE",
            409,
            "manual close requires available_cwt <= 5.0",
        )
    # Manual close books the remnant into shrink.
    lot["shrink_cwt"] = (
        lot["original_weight_cwt"]
        - lot["packed_total_cwt"]
        - lot["cull_total_cwt"]
        - lot["condemned_cwt"]
    )
    logic.recompute_lot_available(lot)
    lot["storage_status"] = "CLOSED"
    lot["closed_at"] = logic.clock_stamp()
    lot["_dt_closed_at"] = logic.clock_now()
    logic.touch(lot)
    if lot["bin_id"] is not None:
        b = STORE["bins"].get(lot["bin_id"])
        if b is not None:
            logic.recompute_bin(b)
    return success(serialize(lot, LOT_FIELDS))


@bp.get("/field-lots/<lid>/lot-draws")
@roles_allowed("ShedAdmin", "StorageManager", "SalesManager", "PackLineSupervisor", "SettlementClerk")
def list_lot_draws(lid):
    lot = get_lot(lid)
    return list_response(
        [d for d in STORE["draws"].values() if d["field_lot_id"] == lot["id"]],
        DRAW_FIELDS,
    )


# ===========================================================================
# Contracts
# ===========================================================================
@bp.post("/contracts")
@roles_allowed("SalesManager")
def create_contract():
    data = get_body()
    check_unknown(
        data,
        [
            "buyer_name", "variety", "committed_volume_cwt", "price_cents_per_cwt",
            "grade_min_us1_pct", "delivery_window_start", "delivery_window_end",
            "priority_rank",
        ],
    )
    buyer = fld_string(data, "buyer_name")
    variety = fld_enum(data, "variety", logic.VARIETIES)
    committed = fld_decimal(data, "committed_volume_cwt", gt=0)
    price = fld_int(data, "price_cents_per_cwt", gt=0)
    grade_min = fld_decimal(data, "grade_min_us1_pct", gte=0, lte=100)
    start_raw, start_dt = fld_dt(data, "delivery_window_start")
    end_raw, end_dt = fld_dt(data, "delivery_window_end")
    rank = fld_int(data, "priority_rank")
    # Temporal (priority 8): delivery window must be ordered.
    if end_dt <= start_dt:
        invalid("delivery_window_end must be strictly after delivery_window_start")
    rec = logic.new_record()
    rec.update(
        {
            "buyer_name": buyer,
            "variety": variety,
            "committed_volume_cwt": committed,
            "price_cents_per_cwt": price,
            "grade_min_us1_pct": grade_min,
            "delivery_window_start": start_raw,
            "delivery_window_end": end_raw,
            "_dt_delivery_window_end": end_dt,
            "priority_rank": rank,
            "remaining_committed_cwt": committed,
            "allocated_active_cwt": Decimal("0"),
            "packed_to_date_cwt": Decimal("0"),
            "status": "ACTIVE",
        }
    )
    STORE["contracts"][rec["id"]] = rec
    return success(serialize(rec, CONTRACT_FIELDS), 201)


@bp.get("/contracts/<cid>")
@roles_allowed("ShedAdmin", "SalesManager", "SettlementClerk")
def read_contract(cid):
    rec = get_contract(cid)
    return success(serialize(rec, CONTRACT_FIELDS))


# ===========================================================================
# Pack orders
# ===========================================================================
@bp.post("/pack-orders")
@roles_allowed("SalesManager")
def create_pack_order():
    data = get_body()
    check_unknown(
        data,
        [
            "order_type", "contract_id", "shed_id", "variety", "pack_unit_weight_lbs",
            "grade_min_us1_pct", "requested_packed_cwt", "allocation_policy",
            "market_price_cents_per_cwt",
        ],
    )
    order_type = fld_enum(data, "order_type", ["CONTRACT", "OPEN_MARKET"])
    variety = fld_enum(data, "variety", logic.VARIETIES)
    # Body FK existence (priority 3): shed first, then contract.
    shed_id = fld_string(data, "shed_id")
    shed = STORE["sheds"].get(shed_id)
    if shed is None:
        api_err("ERR_SHED_NOT_FOUND", 404, "shed_id reference does not exist")
    contract = None
    market_price = None
    if order_type == "CONTRACT":
        contract_id = data.get("contract_id")
        if contract_id is None:
            invalid("contract_id is required for CONTRACT orders")
        if not isinstance(contract_id, str) or contract_id == "":
            invalid("contract_id must be a string")
        contract = STORE["contracts"].get(contract_id)
        if contract is None:
            api_err("ERR_CONTRACT_NOT_FOUND", 404, "contract_id reference does not exist")
        # Cross-reference integrity (priority 7): variety must match.
        if contract["variety"] != variety:
            invalid("order variety must match contract variety")
    else:  # OPEN_MARKET
        if data.get("contract_id") is not None:
            invalid("contract_id must be null for OPEN_MARKET orders")
        market_price = fld_int(data, "market_price_cents_per_cwt", gt=0)
    pack_unit = fld_decimal(data, "pack_unit_weight_lbs", gt=0)
    grade_min = fld_decimal(data, "grade_min_us1_pct", gte=0, lte=100)
    requested = fld_decimal(data, "requested_packed_cwt", gt=0)
    policy = fld_enum(
        data, "allocation_policy", ["LOT_ASSESSMENT", "SHED_BLEND"],
        required=False, default="LOT_ASSESSMENT",
    )
    rec = logic.new_record()
    rec.update(
        {
            "order_type": order_type,
            "contract_id": contract["id"] if contract is not None else None,
            "shed_id": shed["id"],
            "variety": variety,
            "pack_unit_weight_lbs": pack_unit,
            "grade_min_us1_pct": grade_min,
            "requested_packed_cwt": requested,
            "allocation_policy": policy,
            "market_price_cents_per_cwt": market_price,
            "packed_to_date_cwt": Decimal("0"),
            "reservations": [],
            "status": "REQUESTED",
        }
    )
    STORE["orders"][rec["id"]] = rec
    return success(serialize(rec, ORDER_FIELDS), 201)


@bp.get("/pack-orders/<oid>")
@roles_allowed("ShedAdmin", "SalesManager", "PackLineSupervisor", "SettlementClerk")
def read_pack_order(oid):
    rec = get_order(oid)
    return success(serialize(rec, ORDER_FIELDS))


@bp.get("/pack-orders")
@roles_allowed("ShedAdmin", "SalesManager", "PackLineSupervisor", "SettlementClerk")
def list_pack_orders():
    items = list(STORE["orders"].values())
    f_contract = request.args.get("contract_id")
    f_shed = request.args.get("shed_id")
    f_status = request.args.get("status")
    if f_contract is not None:
        items = [o for o in items if o["contract_id"] == f_contract]
    if f_shed is not None:
        items = [o for o in items if o["shed_id"] == f_shed]
    if f_status is not None:
        items = [o for o in items if o["status"] == f_status]
    return list_response(items, ORDER_FIELDS)


@bp.post("/pack-orders/<oid>/allocate")
@roles_allowed("SalesManager")
def allocate_order(oid):
    order = get_order(oid)
    data = get_body()
    check_unknown(data, [])
    # State gate (priority 5)
    if order["status"] not in ("REQUESTED", "ALLOCATED"):
        api_err(
            "ERR_ORDER_INVALID_STATE",
            409,
            "allocation requires a REQUESTED or ALLOCATED order",
        )
    first = order["status"] == "REQUESTED"
    contract = None
    if order["contract_id"] is not None:
        contract = STORE["contracts"].get(order["contract_id"])
        if contract is None or contract["status"] != "ACTIVE":
            api_err(
                "ERR_CONTRACT_INVALID_STATE",
                409,
                "contract must be ACTIVE when an allocation references it",
            )
    # Fiscal ceilings (priority 10) apply to the first allocation from REQUESTED;
    # top-ups from ALLOCATED were already debited/capped at first allocation.
    if first and contract is not None:
        if order["requested_packed_cwt"] > contract["remaining_committed_cwt"]:
            api_err(
                "ERR_COMMITMENT_EXCEEDED",
                402,
                "requested_packed_cwt exceeds contract remaining_committed_cwt",
            )
    if first and order["order_type"] == "OPEN_MARKET":
        cap = logic.open_market_cap(order)
        if order["requested_packed_cwt"] > cap:
            api_err(
                "ERR_OPEN_MARKET_CAP_EXCEEDED",
                422,
                "requested_packed_cwt exceeds the open-market cap",
            )
    need = logic.allocation_need(order)
    if need <= 0 or not logic.pool_covers(order, need):
        api_err(
            "ERR_INSUFFICIENT_ALLOCATION_POOL",
            422,
            "eligible lot pool cannot cover the allocation need",
        )
    logic.run_waterfall(order, need)
    order["status"] = "ALLOCATED"
    logic.touch(order)
    # Reconcile reserved_cwt now that the order is ALLOCATED (reserved_cwt only
    # counts reservations on ALLOCATED/PACKING orders).
    for lid in {r["field_lot_id"] for r in order["reservations"]}:
        lot = STORE["lots"].get(lid)
        if lot is not None:
            logic.recompute_lot_reserved(lot)
    if contract is not None:
        logic.recompute_contract(contract)
    return success(serialize(order, ORDER_FIELDS))


@bp.post("/pack-orders/<oid>/cancel")
@roles_allowed("SalesManager")
def cancel_order(oid):
    order = get_order(oid)
    data = get_body()
    check_unknown(data, [])
    if order["status"] not in ("REQUESTED", "ALLOCATED"):
        api_err(
            "ERR_ORDER_INVALID_STATE",
            409,
            "cancel requires a REQUESTED or ALLOCATED order",
        )
    released_lots = {r["field_lot_id"] for r in order["reservations"]}
    order["reservations"] = []
    order["status"] = "CANCELLED"
    logic.touch(order)
    for lid in released_lots:
        lot = STORE["lots"].get(lid)
        if lot is not None:
            logic.recompute_lot_reserved(lot)
            logic.touch(lot)
    if order["contract_id"] is not None:
        c = STORE["contracts"].get(order["contract_id"])
        if c is not None:
            logic.recompute_contract(c)
    return success(serialize(order, ORDER_FIELDS))


# ===========================================================================
# Pack runs
# ===========================================================================
@bp.post("/pack-orders/<oid>/pack-runs")
@roles_allowed("PackLineSupervisor")
def create_pack_run(oid):
    order = get_order(oid)
    data = get_body()
    check_unknown(data, ["scheduled_start", "scheduled_end"])
    # State gate (priority 5)
    if order["status"] != "ALLOCATED":
        api_err("ERR_ORDER_INVALID_STATE", 409, "run creation requires an ALLOCATED order")
    # Food-safety gates (priority 6)
    shed = STORE["sheds"].get(order["shed_id"])
    if shed is not None and shed["posture"] == "QUARANTINED":
        api_err("ERR_SHED_QUARANTINED", 409, "shed is quarantined; pack runs blocked")
    if shed is not None and not logic.shed_wash_fresh(shed):
        api_err(
            "ERR_WASH_CHECK_STALE",
            409,
            "no PASS wash-water check within the validity window",
        )
    # Temporal (priority 8)
    start_raw, start_dt = fld_dt(data, "scheduled_start")
    end_raw, end_dt = fld_dt(data, "scheduled_end")
    if end_dt <= start_dt:
        invalid("scheduled_end must be strictly after scheduled_start")
    if logic.line_schedule_conflict(order, start_dt, end_dt):
        api_err(
            "ERR_LINE_SCHEDULE_CONFLICT",
            409,
            "pack-line window overlaps another scheduled run on this shed",
        )
    rec = logic.new_record()
    rec.update(
        {
            "pack_order_id": order["id"],
            "scheduled_start": start_raw,
            "scheduled_end": end_raw,
            "_dt_scheduled_start": start_dt,
            "_dt_scheduled_end": end_dt,
            "status": "SCHEDULED",
            "packed_total_cwt": Decimal("0"),
            "cull_total_cwt": Decimal("0"),
            "completed_at": None,
        }
    )
    STORE["runs"][rec["id"]] = rec
    order["status"] = "PACKING"
    logic.touch(order)
    if order["contract_id"] is not None:
        c = STORE["contracts"].get(order["contract_id"])
        if c is not None:
            logic.recompute_contract(c)
    return success(serialize(rec, RUN_FIELDS), 201)


@bp.get("/pack-orders/<oid>/pack-runs")
@roles_allowed("ShedAdmin", "SalesManager", "PackLineSupervisor")
def list_order_runs(oid):
    order = get_order(oid)
    return list_response(
        [r for r in STORE["runs"].values() if r["pack_order_id"] == order["id"]],
        RUN_FIELDS,
    )


@bp.get("/pack-runs/<rid>")
@roles_allowed("ShedAdmin", "SalesManager", "PackLineSupervisor")
def read_pack_run(rid):
    rec = get_run(rid)
    return success(serialize(rec, RUN_FIELDS))


@bp.get("/pack-runs/<rid>/lot-draws")
@roles_allowed("ShedAdmin", "SalesManager", "PackLineSupervisor", "SettlementClerk")
def list_run_draws(rid):
    run = get_run(rid)
    return list_response(
        [d for d in STORE["draws"].values() if d["pack_run_id"] == run["id"]],
        DRAW_FIELDS,
    )


@bp.post("/pack-runs/<rid>/close")
@roles_allowed("PackLineSupervisor")
def close_pack_run(rid):
    run = get_run(rid)
    data = get_body()
    check_unknown(data, ["outcome", "draws"])
    if run["status"] != "SCHEDULED":
        api_err("ERR_RUN_INVALID_STATE", 409, "only a SCHEDULED run can be closed")
    outcome = fld_enum(data, "outcome", ["COMPLETED", "ABORTED"])
    order = STORE["orders"].get(run["pack_order_id"])
    if outcome == "ABORTED":
        # Compensating action: no draws, no weight or contract changes;
        # reservations retained; order PACKING -> ALLOCATED.
        run["status"] = "ABORTED"
        logic.touch(run)
        if order is not None and order["status"] == "PACKING":
            order["status"] = "ALLOCATED"
            logic.touch(order)
        return success(serialize(run, RUN_FIELDS))

    # COMPLETED ----------------------------------------------------------------
    draws_in = data.get("draws")
    if not isinstance(draws_in, list) or len(draws_in) == 0:
        api_err(
            "ERR_RUN_DRAW_IMBALANCE",
            422,
            "a completing close requires a non-empty draws list",
        )
    parsed = []
    for d in draws_in:
        if not isinstance(d, dict):
            invalid("each draw must be an object")
        check_unknown(
            d,
            [
                "field_lot_id", "raw_drawn_cwt", "packed_cwt", "us1_cwt", "us2_cwt",
                "cull_cwt", "cull_channel",
            ],
        )
        lot_id = fld_string(d, "field_lot_id")
        raw = fld_decimal(d, "raw_drawn_cwt", gt=0)
        packed = fld_decimal(d, "packed_cwt", gte=0)
        us1 = fld_decimal(d, "us1_cwt", gte=0)
        us2 = fld_decimal(d, "us2_cwt", gte=0)
        cull = fld_decimal(d, "cull_cwt", gte=0)
        channel = fld_enum(d, "cull_channel", ["PROCESSING", "WASTE"])
        parsed.append(
            {
                "field_lot_id": lot_id,
                "raw_drawn_cwt": raw,
                "packed_cwt": packed,
                "us1_cwt": us1,
                "us2_cwt": us2,
                "cull_cwt": cull,
                "cull_channel": channel,
            }
        )
    # Duplicate lot within a single run -> imbalance.
    lot_ids = [d["field_lot_id"] for d in parsed]
    if len(set(lot_ids)) != len(lot_ids):
        api_err("ERR_RUN_DRAW_IMBALANCE", 422, "duplicate field lot within one run")
    # Reservation checks (PRD order: reservation within-reservation first).
    for d in parsed:
        res = next(
            (
                r
                for r in (order["reservations"] if order else [])
                if r["field_lot_id"] == d["field_lot_id"]
            ),
            None,
        )
        if res is None or d["raw_drawn_cwt"] > res["raw_cwt"]:
            api_err(
                "ERR_RUN_DRAW_EXCEEDS_RESERVATION",
                422,
                "draw references a lot without an active reservation on this order, "
                "or exceeds the reserved raw_cwt",
            )
    # Balance checks.
    for d in parsed:
        if d["raw_drawn_cwt"] != d["packed_cwt"] + d["cull_cwt"]:
            api_err(
                "ERR_RUN_DRAW_IMBALANCE",
                422,
                "raw_drawn_cwt must equal packed_cwt + cull_cwt",
            )
        if d["us1_cwt"] + d["us2_cwt"] != d["packed_cwt"]:
            api_err(
                "ERR_RUN_DRAW_IMBALANCE",
                422,
                "us1_cwt + us2_cwt must equal packed_cwt",
            )
    # Grade gate: aggregate US1 share across draws >= order.grade_min_us1_pct.
    sum_packed = sum((d["packed_cwt"] for d in parsed), Decimal("0"))
    sum_us1 = sum((d["us1_cwt"] for d in parsed), Decimal("0"))
    grade_min = order["grade_min_us1_pct"]
    if sum_packed == 0:
        if grade_min > 0:
            api_err("ERR_GRADE_SPEC_NOT_MET", 422, "aggregate US1 share below grade minimum")
    elif sum_us1 * Decimal("100") < grade_min * sum_packed:
        api_err("ERR_GRADE_SPEC_NOT_MET", 422, "aggregate US1 share below grade minimum")

    # Apply the draw ledger to every affected lot in one transaction.
    sum_cull = sum((d["cull_cwt"] for d in parsed), Decimal("0"))
    for d in parsed:
        lot = STORE["lots"][d["field_lot_id"]]
        lot["packed_total_cwt"] += d["packed_cwt"]
        lot["cull_total_cwt"] += d["cull_cwt"]
        if d["cull_channel"] == "PROCESSING":
            lot["processing_credit_cwt"] += d["cull_cwt"]
        # The reservation on that lot is consumed.
        order["reservations"] = [
            r for r in order["reservations"] if r["field_lot_id"] != lot["id"]
        ]
        logic.recompute_lot_available(lot)
        logic.recompute_lot_reserved(lot)
        logic.touch(lot)
        logic.maybe_auto_close_lot(lot)
        if lot["bin_id"] is not None:
            b = STORE["bins"].get(lot["bin_id"])
            if b is not None:
                logic.recompute_bin(b)
        rec = logic.new_record(common=False)
        rec.update(
            {
                "pack_run_id": run["id"],
                "field_lot_id": lot["id"],
                "raw_drawn_cwt": d["raw_drawn_cwt"],
                "packed_cwt": d["packed_cwt"],
                "us1_cwt": d["us1_cwt"],
                "us2_cwt": d["us2_cwt"],
                "cull_cwt": d["cull_cwt"],
                "cull_channel": d["cull_channel"],
            }
        )
        STORE["draws"][rec["id"]] = rec

    run["packed_total_cwt"] = sum_packed
    run["cull_total_cwt"] = sum_cull
    run["completed_at"] = logic.clock_stamp()
    run["status"] = "COMPLETED"
    logic.touch(run)

    order["packed_to_date_cwt"] += sum_packed
    if order["packed_to_date_cwt"] >= order["requested_packed_cwt"]:
        order["status"] = "SHIPPED"
    else:
        order["status"] = "ALLOCATED"
    logic.touch(order)
    if order["contract_id"] is not None:
        c = STORE["contracts"].get(order["contract_id"])
        if c is not None:
            logic.recompute_contract(c)
    return success(serialize(run, RUN_FIELDS))


# ===========================================================================
# Food safety: wash-water checks and audits
# ===========================================================================
@bp.post("/sheds/<sid>/wash-water-checks")
@roles_allowed("QualityAssuranceManager")
def create_wash_check(sid):
    shed = get_shed(sid)
    data = get_body()
    check_unknown(data, ["measured_at", "turbidity_ntu", "chlorine_ppm", "water_temp_f"])
    measured_raw, measured_dt = fld_dt(data, "measured_at")
    turbidity = fld_decimal(data, "turbidity_ntu", gte=0)
    chlorine = fld_decimal(data, "chlorine_ppm", gte=0)
    temp = fld_decimal(data, "water_temp_f")
    result = logic.wash_result(turbidity, chlorine, temp)
    rec = logic.new_record(common=False)
    rec.update(
        {
            "shed_id": shed["id"],
            "measured_at": measured_raw,
            "_dt_measured_at": measured_dt,
            "turbidity_ntu": turbidity,
            "chlorine_ppm": chlorine,
            "water_temp_f": temp,
            "result": result,
        }
    )
    STORE["checks"][rec["id"]] = rec
    if result == "FAIL":
        shed["consecutive_wash_failures"] += 1
        if turbidity > logic.QUARANTINE_TURBIDITY_NTU:
            shed["wash_quarantine_flag"] = True
    else:
        shed["consecutive_wash_failures"] = 0
        shed["wash_quarantine_flag"] = False
    logic.touch(shed)
    logic.recompute_posture(shed)
    return success(serialize(rec, CHECK_FIELDS), 201)


@bp.get("/sheds/<sid>/wash-water-checks")
@roles_allowed("ShedAdmin", "QualityAssuranceManager", "PackLineSupervisor")
def list_wash_checks(sid):
    shed = get_shed(sid)
    return list_response(
        [c for c in STORE["checks"].values() if c["shed_id"] == shed["id"]],
        CHECK_FIELDS,
    )


@bp.post("/sheds/<sid>/audits")
@roles_allowed("QualityAssuranceManager")
def create_audit(sid):
    shed = get_shed(sid)
    data = get_body()
    check_unknown(data, ["field_work_date"])
    fwd_raw, _ = fld_dt(data, "field_work_date")
    rec = logic.new_record()
    rec.update(
        {
            "shed_id": shed["id"],
            "field_work_date": fwd_raw,
            "status": "FIELD_WORK",
            "outcome": None,
            "critical_findings": None,
            "minor_findings": None,
            "closed_at": None,
        }
    )
    STORE["audits"][rec["id"]] = rec
    return success(serialize(rec, AUDIT_FIELDS), 201)


@bp.post("/audits/<aid>/close")
@roles_allowed("QualityAssuranceManager")
def close_audit(aid):
    audit = get_audit(aid)
    data = get_body()
    check_unknown(data, ["outcome", "critical_findings", "minor_findings"])
    if audit["status"] != "FIELD_WORK":
        api_err("ERR_AUDIT_INVALID_STATE", 409, "only a FIELD_WORK audit can be closed")
    outcome = fld_enum(data, "outcome", ["PASS", "FAIL"])
    critical = fld_int(data, "critical_findings", gte=0)
    minor = fld_int(data, "minor_findings", gte=0)
    audit["status"] = "PASSED" if outcome == "PASS" else "FAILED"
    audit["outcome"] = outcome
    audit["critical_findings"] = critical
    audit["minor_findings"] = minor
    audit["closed_at"] = logic.clock_stamp()
    logic.touch(audit)
    shed = STORE["sheds"].get(audit["shed_id"])
    if shed is not None:
        shed["audit_failed_flag"] = outcome == "FAIL"
        logic.touch(shed)
        logic.recompute_posture(shed)
    return success(serialize(audit, AUDIT_FIELDS))


@bp.get("/sheds/<sid>/audits")
@roles_allowed("ShedAdmin", "QualityAssuranceManager")
def list_audits(sid):
    shed = get_shed(sid)
    return list_response(
        [a for a in STORE["audits"].values() if a["shed_id"] == shed["id"]],
        AUDIT_FIELDS,
    )


# ===========================================================================
# Grower settlements
# ===========================================================================
@bp.post("/growers/<gid>/settlements")
@roles_allowed("SettlementClerk")
def create_settlement(gid):
    grower = get_grower(gid)
    data = get_body()
    check_unknown(data, ["season_label", "expected_grower_version"])
    # OCC (priority 4)
    expected = fld_version(data, "expected_grower_version")
    if expected != grower["version"]:
        api_err(
            "ERR_STALE_VERSION",
            412,
            "expected_grower_version does not match grower version",
        )
    season = fld_string(data, "season_label")
    # Season-label uniqueness among non-SUPERSEDED settlements (priority 7):
    # FINALIZED/DISPUTED/PAID conflict; PROVISIONAL is superseded.
    prior_provisional = None
    for s in STORE["settlements"].values():
        if s["grower_id"] != grower["id"] or s["season_label"] != season:
            continue
        if s["status"] in ("FINALIZED", "DISPUTED", "PAID"):
            api_err(
                "ERR_SETTLEMENT_SEASON_CONFLICT",
                409,
                "a non-superseded settlement already exists for this season",
            )
        if s["status"] == "PROVISIONAL":
            prior_provisional = s
    money = logic.compute_settlement(grower["id"], "provisional")
    rec = logic.new_record()
    rec.update(
        {
            "grower_id": grower["id"],
            "season_label": season,
            "status": "PROVISIONAL",
            "packed_cwt_basis": money["packed_cwt_basis"],
            "pool_price_cents": money["pool_price_cents"],
            "gross_cents": money["gross_cents"],
            "storage_fees_cents": money["storage_fees_cents"],
            "inhibitor_fees_cents": money["inhibitor_fees_cents"],
            "processing_credits_cents": money["processing_credits_cents"],
            "net_payable_cents": money["net_payable_cents"],
            "finalized_by_clerk_id": None,
            "paid_at": None,
        }
    )
    STORE["settlements"][rec["id"]] = rec
    if prior_provisional is not None:
        prior_provisional["status"] = "SUPERSEDED"
        logic.touch(prior_provisional)
    logic.touch(grower)
    return success(serialize(rec, SETTLEMENT_FIELDS), 201)


@bp.get("/settlements/<sid>")
@roles_allowed("ShedAdmin", "SettlementClerk", "Grower")
def read_settlement(sid):
    rec = get_settlement(sid)
    if g.user_role == "Grower" and rec["grower_id"] != g.user_id:
        api_err(
            "ERR_INSUFFICIENT_PERMISSIONS",
            403,
            "growers may only read their own settlements",
        )
    return success(serialize(rec, SETTLEMENT_FIELDS))


@bp.get("/growers/<gid>/settlements")
@roles_allowed("ShedAdmin", "SettlementClerk", "Grower")
def list_settlements(gid):
    if g.user_role == "Grower" and gid != g.user_id:
        api_err(
            "ERR_INSUFFICIENT_PERMISSIONS",
            403,
            "growers may only list their own settlements",
        )
    grower = get_grower(gid)
    return list_response(
        [s for s in STORE["settlements"].values() if s["grower_id"] == grower["id"]],
        SETTLEMENT_FIELDS,
    )


@bp.post("/settlements/<sid>/finalize")
@roles_allowed("SettlementClerk")
def finalize_settlement(sid):
    rec = get_settlement(sid)
    data = get_body()
    check_unknown(data, [])
    if rec["status"] == "PROVISIONAL":
        pass
    elif rec["status"] == "DISPUTED":
        # Segregation of duties (evaluated with state checks, priority 5).
        if g.user_id == rec["finalized_by_clerk_id"]:
            api_err(
                "ERR_SOD_REFINALIZE_CLERK",
                403,
                "re-finalize requires a different clerk than finalized_by_clerk_id",
            )
    else:
        api_err(
            "ERR_SETTLEMENT_INVALID_STATE",
            409,
            "finalize requires a PROVISIONAL or DISPUTED settlement",
        )
    lots = logic.grower_lots(rec["grower_id"])
    if any(l["storage_status"] != "CLOSED" for l in lots):
        api_err(
            "ERR_SETTLEMENT_LOTS_NOT_CLOSED",
            409,
            "every field lot of the grower must be CLOSED to finalize",
        )
    money = logic.compute_settlement(rec["grower_id"], "final")
    rec.update(money)
    rec["status"] = "FINALIZED"
    rec["finalized_by_clerk_id"] = g.user_id
    logic.touch(rec)
    return success(serialize(rec, SETTLEMENT_FIELDS))


@bp.post("/settlements/<sid>/dispute")
@roles_allowed("Grower")
def dispute_settlement(sid):
    rec = get_settlement(sid)
    data = get_body()
    check_unknown(data, ["reason"])
    # Ownership (priority 2): a grower may dispute only their own settlement.
    if rec["grower_id"] != g.user_id:
        api_err(
            "ERR_INSUFFICIENT_PERMISSIONS",
            403,
            "growers may only dispute their own settlements",
        )
    if rec["status"] != "FINALIZED":
        api_err(
            "ERR_SETTLEMENT_INVALID_STATE",
            409,
            "dispute requires a FINALIZED settlement",
        )
    rec["status"] = "DISPUTED"
    logic.touch(rec)
    return success(serialize(rec, SETTLEMENT_FIELDS))


@bp.post("/settlements/<sid>/pay")
@roles_allowed("SettlementClerk")
def pay_settlement(sid):
    rec = get_settlement(sid)
    data = get_body()
    check_unknown(data, [])
    if rec["status"] != "FINALIZED":
        api_err("ERR_SETTLEMENT_INVALID_STATE", 409, "pay requires a FINALIZED settlement")
    rec["status"] = "PAID"
    rec["paid_at"] = logic.clock_stamp()
    logic.touch(rec)
    return success(serialize(rec, SETTLEMENT_FIELDS))


# ===========================================================================
# Logical clock
# ===========================================================================
@bp.post("/_clock/set_current_utc")
@roles_allowed("ShedAdmin")
def set_clock():
    data = get_body()
    check_unknown(data, ["to_iso8601"])
    raw, dt = fld_dt(data, "to_iso8601")
    CLOCK["dt"] = dt
    CLOCK["raw"] = raw
    # Season-settle sweep: ACTIVE contracts whose window is now in the past.
    for c in STORE["contracts"].values():
        if c["status"] != "ACTIVE":
            continue
        if dt > c["_dt_delivery_window_end"]:
            if c["packed_to_date_cwt"] >= c["committed_volume_cwt"]:
                c["status"] = "FULFILLED"
            else:
                c["status"] = "SHORTFALLED"
            logic.touch(c)
    return success({"current_utc": raw})
