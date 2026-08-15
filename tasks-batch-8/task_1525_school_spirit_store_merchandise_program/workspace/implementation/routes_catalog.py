"""Programs (+ lifecycle, profit adjustments, valuation, run-ops, clock),
vendors, designs (licensing workflow), product variants, seasonal drops."""
from datetime import timedelta

from flask import Blueprint

from core import (AD, SM, LC, TRE, SC, CUST, ApiError, DB, CLOCK,
                  ERR_ACCOUNT_NF, ERR_ALLOCATION_EXCEEDS, ERR_CAMPAIGN_NF,
                  ERR_DESIGN_NF, ERR_DESIGN_NOT_LICENSED, ERR_DROP_NF,
                  ERR_DROP_NOT_STARTED, ERR_DROP_OVERLAP, ERR_DUP_VARIANT,
                  ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_LICENSE_REVOKED,
                  ERR_PO_NF, ERR_PROGRAM_NF, ERR_PROGRAM_NOT_CLOSED,
                  ERR_PROFIT_NOT_ALLOCATED, ERR_STALE, ERR_UNRESOLVED,
                  ERR_VARIANT_NF, ERR_VENDOR_NF, auth, body, cascade_campaign_cancel,
                  dec, fetch, fetch_scoped, floor_div_dec, gate_active, gate_closed,
                  is_int, is_num, list_response, need_role, new_entity,
                  now_logical, opt_int, paginate, parse_dt, pub, pub_campaign,
                  pub_variant, req_dt, req_fields, req_int, req_pct, rhu,
                  rhu_decimal, ser_dt, success, touch, variant_sellable)

bp = Blueprint("catalog", __name__)


# ============================================================ MerchProgram ==
@bp.post("/spirit-store/programs")
def create_program():
    auth()
    uid, role = auth()
    need_role(role, AD)
    data = body()
    req_fields(data, "name", "school_year", "valuation_method")
    if data["valuation_method"] not in ("FIFO", "WEIGHTED_AVG"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "valuation_method must be FIFO or WEIGHTED_AVG")
    program = new_entity({
        "name": data["name"],
        "school_year": data["school_year"],
        "status": "SETUP",
        "over_short_tolerance_cents": opt_int(data, "over_short_tolerance_cents", 500, 0),
        "exchange_window_days": opt_int(data, "exchange_window_days", 14, 0),
        "pickup_window_days": opt_int(data, "pickup_window_days", 7, 0),
        "register_buffer_minutes": opt_int(data, "register_buffer_minutes", 30, 0),
        "deposit_floor_cents": opt_int(data, "deposit_floor_cents", 500, 0),
        "valuation_method": data["valuation_method"],
        "undistributed_profit_cents": 0,
        "distributed_profit_cents": 0,
        "ops_run_index": 0,
    })
    DB["programs"][program["id"]] = program
    return success(pub(program), code=201)


@bp.get("/spirit-store/programs")
def list_programs():
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, LC, SC)
    items = list(DB["programs"].values())
    return list_response(items, pub)


@bp.get("/spirit-store/programs/<programId>")
def get_program(programId):
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, LC, SC)
    program = fetch("programs", programId, ERR_PROGRAM_NF)
    return success(pub(program))


@bp.post("/spirit-store/programs/<programId>/lifecycle")
def program_lifecycle(programId):
    auth()
    uid, role = auth()
    need_role(role, AD)
    program = fetch("programs", programId, ERR_PROGRAM_NF)
    data = body()
    req_fields(data, "to_state")
    to_state = data["to_state"]
    if to_state not in ("ACTIVE", "CLOSED", "RECONCILED"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "to_state must be ACTIVE, CLOSED, or RECONCILED")
    if to_state == "ACTIVE":
        if program["status"] != "SETUP":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "program can only be activated from SETUP")
        program["status"] = "ACTIVE"
    elif to_state == "CLOSED":
        if program["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "program can only be closed from ACTIVE")
        # §3.1: every EventSale RECONCILED/CANCELLED, every campaign
        # CLOSED/CANCELLED, else ERR_UNRESOLVED_OPERATIONS.
        for ev in DB["events"].values():
            if (ev["program_id"] == program["id"]
                    and ev["status"] not in ("RECONCILED", "CANCELLED")):
                raise ApiError(ERR_UNRESOLVED, 409,
                               "program has unresolved event sales")
        for c in DB["campaigns"].values():
            if (c["program_id"] == program["id"]
                    and c["status"] not in ("CLOSED", "CANCELLED")):
                raise ApiError(ERR_UNRESOLVED, 409,
                               "program has unresolved preorder campaigns")
        program["status"] = "CLOSED"
    else:  # RECONCILED
        if program["status"] != "CLOSED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "program can only be reconciled from CLOSED")
        # Pipeline: constraint (unresolved DRAFT runs) before fiscal (profit).
        for run in DB["runs"].values():
            if run["program_id"] == program["id"] and run["status"] == "DRAFT":
                raise ApiError(ERR_UNRESOLVED, 409,
                               "program has allocation runs still in DRAFT")
        if program["undistributed_profit_cents"] != 0:
            raise ApiError(ERR_PROFIT_NOT_ALLOCATED, 409,
                           "undistributed profit must be exactly 0")
        program["status"] = "RECONCILED"
    touch(program)
    return success(pub(program))


@bp.post("/spirit-store/programs/<programId>/profit-adjustments")
def profit_adjustment(programId):
    auth()
    uid, role = auth()
    need_role(role, AD)
    program = fetch("programs", programId, ERR_PROGRAM_NF)
    data = body()
    req_fields(data, "amount_cents", "reason")
    amount = req_int(data, "amount_cents")
    if not isinstance(data["reason"], str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "reason must be a string")
    program["undistributed_profit_cents"] += amount
    touch(program)
    return success(pub(program), code=201)


@bp.get("/spirit-store/programs/<programId>/valuation")
def valuation(programId):
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE)
    program = fetch("programs", programId, ERR_PROGRAM_NF)
    from flask import request
    method = request.args.get("method") or program["valuation_method"]
    if method not in ("FIFO", "WEIGHTED_AVG"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "method must be FIFO or WEIGHTED_AVG")
    per_variant = []
    total = 0
    for v in DB["variants"].values():
        if v["program_id"] != program["id"]:
            continue
        layers = sorted(v["_layers"],
                        key=lambda L: (L["received_at"], L["po_seq"]))
        if method == "FIFO":
            # Consume oldest layers first; value the units remaining.
            consume = v["_consumed"]
            value = 0
            for layer in layers:
                used = min(layer["qty"], consume)
                consume -= used
                value += (layer["qty"] - used) * layer["cost"]
        else:
            total_qty = sum(L["qty"] for L in layers)
            total_cost = sum(L["qty"] * L["cost"] for L in layers)
            avg = rhu(total_cost, total_qty) if total_qty else 0
            value = v["on_hand_qty"] * avg
        per_variant.append({"variant_id": v["id"],
                            "on_hand_qty": v["on_hand_qty"],
                            "value_cents": value})
        total += value
    return success({"method": method, "total_value_cents": total,
                    "per_variant": per_variant})


@bp.post("/spirit-store/programs/<programId>/run-ops")
def run_ops(programId):
    auth()
    uid, role = auth()
    need_role(role, AD)
    program = fetch("programs", programId, ERR_PROGRAM_NF)
    clock = now_logical()
    program["ops_run_index"] += 1
    # Auto-close OPEN drops whose closes_at the clock has reached or passed.
    for drop in DB["drops"].values():
        if (drop["program_id"] == program["id"] and drop["status"] == "OPEN"
                and clock >= drop["closes_at"]):
            drop["status"] = "CLOSED"
            touch(drop)
    # Expire READY_FOR_PICKUP orders whose expires_at the clock has passed.
    for order in DB["orders"].values():
        if (order["program_id"] == program["id"]
                and order["fulfillment_status"] == "READY_FOR_PICKUP"
                and order["expires_at"] is not None
                and clock > order["expires_at"]):
            for line in order["lines"]:
                v = DB["variants"].get(line["variant_id"])
                if v is None:
                    continue
                remaining = line["qty"] - line.get("_released", 0)
                if remaining > 0:
                    v["reserved_online_qty"] -= remaining
                    line["_released"] = line["qty"]
                    touch(v)
            order["fulfillment_status"] = "EXPIRED_RELEASED"
            order["payment_status"] = "REFUNDED"
            order["refunded_cents"] = order["total_cents"]
            program["undistributed_profit_cents"] -= order["margin_cents"]
            touch(order)
    touch(program)
    return success(pub(program))


# ------------------------------------------------------------------ clock ---
@bp.post("/spirit-store/_clock/set_current_utc")
def set_clock():
    auth()
    uid, role = auth()
    need_role(role, AD)
    data = body()
    dt = req_dt(data, "to_iso8601")
    CLOCK["dt"] = dt
    return success({"current_utc": ser_dt(CLOCK["dt"])})


# ----------------------------------------------------------------- Vendor ---
def validate_quotes(quotes):
    if not isinstance(quotes, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "quotes must be an array")
    active_designs = set()
    for q in quotes:
        if not isinstance(q, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "each quote must be an object")
        for field in ("design_id", "unit_cost_cents", "min_order_qty",
                      "production_days", "status"):
            if q.get(field) is None:
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "quote missing field: %s" % field)
        if q["status"] not in ("ACTIVE", "RETIRED"):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "quote status must be ACTIVE or RETIRED")
        if not is_int(q["unit_cost_cents"]) or q["unit_cost_cents"] < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "quote unit_cost_cents must be an integer >= 0")
        if not is_int(q["min_order_qty"]) or q["min_order_qty"] < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "quote min_order_qty must be an integer >= 0")
        if not is_int(q["production_days"]) or q["production_days"] < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "quote production_days must be an integer >= 0")
        if q["status"] == "ACTIVE":
            # At most one ACTIVE quote per design per vendor.
            if q["design_id"] in active_designs:
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "at most one ACTIVE quote per design per vendor")
            active_designs.add(q["design_id"])


@bp.post("/spirit-store/vendors")
def create_vendor():
    auth()
    uid, role = auth()
    need_role(role, SM)
    data = body()
    program = None
    if data.get("program_id") is not None:
        program = fetch("programs", data["program_id"], ERR_PROGRAM_NF)
    req_fields(data, "program_id", "name", "contact_email")
    if data.get("quotes") is not None:
        validate_quotes(data["quotes"])
    gate_active(program)
    vendor = new_entity({
        "program_id": data["program_id"],
        "name": data["name"],
        "contact_email": data["contact_email"],
        "status": "PENDING",
        "quotes": data.get("quotes") or [],
    })
    DB["vendors"][vendor["id"]] = vendor
    return success(pub(vendor), code=201)


@bp.get("/spirit-store/vendors")
def list_vendors():
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE)
    items = list(DB["vendors"].values())
    from flask import request
    pid = request.args.get("program_id")
    if pid is not None:
        items = [v for v in items if v["program_id"] == pid]
    return list_response(items, pub)


@bp.get("/spirit-store/vendors/<vendorId>")
def get_vendor(vendorId):
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE)
    return success(pub(fetch("vendors", vendorId, ERR_VENDOR_NF)))


@bp.patch("/spirit-store/vendors/<vendorId>")
def patch_vendor(vendorId):
    auth()
    uid, role = auth()
    need_role(role, SM)
    vendor = fetch("vendors", vendorId, ERR_VENDOR_NF)
    data = body()
    program = DB["programs"].get(vendor["program_id"])
    gate_active(program)
    changed = False
    if data.get("status") is not None:
        target = data["status"]
        if target not in ("PENDING", "APPROVED", "SUSPENDED"):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "status must be PENDING, APPROVED, or SUSPENDED")
        allowed = {("PENDING", "APPROVED"), ("APPROVED", "SUSPENDED"),
                   ("SUSPENDED", "APPROVED")}
        if (vendor["status"], target) not in allowed:
            raise ApiError(ERR_INVALID_STATE, 409,
                           "vendor status transition %s -> %s not allowed"
                           % (vendor["status"], target))
        vendor["status"] = target
        changed = True
    if data.get("quotes") is not None:
        validate_quotes(data["quotes"])
        vendor["quotes"] = data["quotes"]
        changed = True
    if changed:
        touch(vendor)
    return success(pub(vendor))


# ----------------------------------------------------------------- Design ---
@bp.post("/spirit-store/designs")
def create_design():
    auth()
    uid, role = auth()
    need_role(role, SM)
    data = body()
    program = None
    if data.get("program_id") is not None:
        program = fetch("programs", data["program_id"], ERR_PROGRAM_NF)
    req_fields(data, "program_id", "name", "artwork_ref", "royalty_pct",
               "licensing_fee_cents")
    royalty = req_pct(data, "royalty_pct")
    fee = req_int(data, "licensing_fee_cents", 0)
    gate_active(program)
    design = new_entity({
        "program_id": data["program_id"],
        "name": data["name"],
        "artwork_ref": data["artwork_ref"],
        "royalty_pct": royalty,
        "licensing_fee_cents": fee,
        "status": "DRAFT",
        "revision_count": 0,
        "rejection_reason": None,
    })
    DB["designs"][design["id"]] = design
    return success(pub(design), code=201)


@bp.get("/spirit-store/designs")
def list_designs():
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, LC)
    items = list(DB["designs"].values())
    from flask import request
    pid = request.args.get("program_id")
    if pid is not None:
        items = [d for d in items if d["program_id"] == pid]
    return list_response(items, pub)


@bp.get("/spirit-store/designs/<designId>")
def get_design(designId):
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, LC)
    return success(pub(fetch("designs", designId, ERR_DESIGN_NF)))


@bp.post("/spirit-store/designs/<designId>/licensing-transition")
def licensing_transition(designId):
    auth()
    uid, role = auth()
    need_role(role, LC)
    design = fetch("designs", designId, ERR_DESIGN_NF)
    data = body()
    req_fields(data, "to_state", "expected_design_version")
    to_state = data["to_state"]
    if to_state not in ("SUBMITTED", "APPROVED", "REJECTED", "REVOKED"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "to_state must be SUBMITTED, APPROVED, REJECTED, or "
                       "REVOKED")
    if not is_int(data["expected_design_version"]):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_design_version must be an integer")
    # State precondition (pipeline step 7).
    allowed = {("DRAFT", "SUBMITTED"), ("REJECTED", "SUBMITTED"),
               ("SUBMITTED", "APPROVED"), ("SUBMITTED", "REJECTED"),
               ("APPROVED", "REVOKED")}
    if (design["status"], to_state) not in allowed:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "licensing transition %s -> %s not allowed"
                       % (design["status"], to_state))
    # OCC (pipeline step 13, after all other checks).
    if data["expected_design_version"] != design["version"]:
        raise ApiError(ERR_STALE, 412,
                       "expected_design_version does not match the design's "
                       "current version")
    note = data.get("note")
    if to_state == "SUBMITTED" and design["status"] == "REJECTED":
        design["revision_count"] += 1
        design["rejection_reason"] = None
    if to_state == "REJECTED":
        design["rejection_reason"] = note
    if to_state == "REVOKED":
        # §3.2 cascade: variants recompute sellable (computed on read);
        # OPEN / IN_PRODUCTION campaigns of this design auto-cancel;
        # their PAID preorders refund, PLACED ones cancel.
        for c in DB["campaigns"].values():
            if (c["design_id"] == design["id"]
                    and c["status"] in ("OPEN", "IN_PRODUCTION")):
                c["status"] = "CANCELLED"
                touch(c)
                cascade_campaign_cancel(c)
    design["status"] = to_state
    touch(design)
    return success(pub(design))


# ---------------------------------------------------------- ProductVariant --
@bp.post("/spirit-store/product-variants")
def create_variant():
    auth()
    uid, role = auth()
    need_role(role, SM)
    data = body()
    program = None
    if data.get("program_id") is not None:
        program = fetch("programs", data["program_id"], ERR_PROGRAM_NF)
    if data.get("design_id") is not None:
        fetch_scoped("designs", data["design_id"], ERR_DESIGN_NF,
                     data.get("program_id"))
    if data.get("drop_id") is not None:
        fetch_scoped("drops", data["drop_id"], ERR_DROP_NF,
                     data.get("program_id"))
    req_fields(data, "program_id", "design_id", "size", "unit_price_cents")
    if data["size"] not in ("XS", "S", "M", "L", "XL", "2XL", "ONE_SIZE"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid size")
    price = req_int(data, "unit_price_cents", 1)
    reorder_point = opt_int(data, "reorder_point", 0, 0)
    gate_active(program)
    # Unique (design_id, size) per program.
    for v in DB["variants"].values():
        if (v["program_id"] == data["program_id"]
                and v["design_id"] == data["design_id"]
                and v["size"] == data["size"]):
            raise ApiError(ERR_DUP_VARIANT, 409,
                           "a variant with this design and size already "
                           "exists in the program")
    variant = new_entity({
        "program_id": data["program_id"],
        "design_id": data["design_id"],
        "drop_id": data.get("drop_id"),
        "size": data["size"],
        "unit_price_cents": price,
        "reorder_point": reorder_point,
        "on_hand_qty": 0,
        "reserved_online_qty": 0,
        "landed_unit_cost_cents": 0,
        "_layers": [],
        "_consumed": 0,
    })
    DB["variants"][variant["id"]] = variant
    return success(pub_variant(variant), code=201)


@bp.get("/spirit-store/product-variants")
def list_variants():
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, SC)
    from flask import request
    items = list(DB["variants"].values())
    for param in ("program_id", "design_id", "drop_id"):
        value = request.args.get(param)
        if value is not None:
            items = [v for v in items if v[param] == value]
    return list_response(items, pub_variant)


@bp.get("/spirit-store/product-variants/<variantId>")
def get_variant(variantId):
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE, SC)
    return success(pub_variant(fetch("variants", variantId, ERR_VARIANT_NF)))


# ------------------------------------------------------------ SeasonalDrop --
@bp.post("/spirit-store/seasonal-drops")
def create_drop():
    auth()
    uid, role = auth()
    need_role(role, SM)
    data = body()
    program = None
    if data.get("program_id") is not None:
        program = fetch("programs", data["program_id"], ERR_PROGRAM_NF)
    req_fields(data, "program_id", "name", "opens_at", "closes_at",
               "expected_program_version")
    opens_at = req_dt(data, "opens_at")
    closes_at = req_dt(data, "closes_at")
    if not closes_at > opens_at:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "closes_at must be strictly after opens_at")
    if not is_int(data["expected_program_version"]):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_program_version must be an integer")
    gate_active(program)
    # Half-open window [opens_at, closes_at): adjacency allowed, true overlap
    # rejected; checked against the program's other non-terminal drops.
    for other in DB["drops"].values():
        if (other["program_id"] == program["id"]
                and other["status"] != "SETTLED"
                and opens_at < other["closes_at"]
                and other["opens_at"] < closes_at):
            raise ApiError(ERR_DROP_OVERLAP, 409,
                           "drop window overlaps an existing drop window")
    # OCC on MerchProgram.version (pipeline step 13).
    if data["expected_program_version"] != program["version"]:
        raise ApiError(ERR_STALE, 412,
                       "expected_program_version does not match the "
                       "program's current version")
    drop = new_entity({
        "program_id": program["id"],
        "name": data["name"],
        "opens_at": opens_at,
        "closes_at": closes_at,
        "status": "SCHEDULED",
        "settled_margin_cents": None,
    })
    DB["drops"][drop["id"]] = drop
    touch(program)  # drop creation advances the program's version by 1
    return success(pub(drop), code=201)


@bp.get("/spirit-store/seasonal-drops")
def list_drops():
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE)
    from flask import request
    items = list(DB["drops"].values())
    pid = request.args.get("program_id")
    if pid is not None:
        items = [d for d in items if d["program_id"] == pid]
    return list_response(items, pub)


@bp.get("/spirit-store/seasonal-drops/<dropId>")
def get_drop(dropId):
    auth()
    uid, role = auth()
    need_role(role, AD, SM, TRE)
    return success(pub(fetch("drops", dropId, ERR_DROP_NF)))


@bp.post("/spirit-store/seasonal-drops/<dropId>/transition")
def drop_transition(dropId):
    auth()
    uid, role = auth()
    need_role(role, SM)
    drop = fetch("drops", dropId, ERR_DROP_NF)
    data = body()
    req_fields(data, "to_state")
    to_state = data["to_state"]
    if to_state not in ("OPEN", "CLOSED", "SETTLED"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "to_state must be OPEN, CLOSED, or SETTLED")
    program = DB["programs"].get(drop["program_id"])
    gate_active(program)
    clock = now_logical()
    if to_state == "OPEN":
        if drop["status"] != "SCHEDULED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "drop can only be opened from SCHEDULED")
        if clock < drop["opens_at"]:
            raise ApiError(ERR_DROP_NOT_STARTED, 409,
                           "drop window has not started")
        drop["status"] = "OPEN"
    elif to_state == "CLOSED":
        if drop["status"] != "OPEN":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "drop can only be closed from OPEN")
        drop["status"] = "CLOSED"
    else:  # SETTLED
        if drop["status"] != "CLOSED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "drop can only be settled from CLOSED")
        # Snapshot: sum of margin over orders (payment PAID or
        # PARTIALLY_REFUNDED) containing at least one line of this drop,
        # with refunded portions already netted out.
        margin = 0
        for order in DB["orders"].values():
            if order["program_id"] != drop["program_id"]:
                continue
            if order["payment_status"] not in ("PAID", "PARTIALLY_REFUNDED"):
                continue
            hit = False
            for line in order["lines"]:
                v = DB["variants"].get(line["variant_id"])
                if v is not None and v["drop_id"] == drop["id"]:
                    hit = True
                    break
            if hit:
                margin += order["margin_cents"] - order["_clawed_cents"]
        drop["settled_margin_cents"] = margin
        drop["status"] = "SETTLED"
    touch(drop)
    return success(pub(drop))
