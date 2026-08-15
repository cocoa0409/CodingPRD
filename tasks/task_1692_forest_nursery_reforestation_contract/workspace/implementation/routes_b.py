"""Seedling orders and allocations."""
from server import (STORE, SPECIES, LEAD_DAYS, app, bad_request, batch_allocatable_basis,
                 batch_reserved, batch_species, body, calc_order_total, create_record,
                 err, get_path, invalid_state, is_int, order_allocated, order_shipped,
                 release_allocation, require_owner, require_role, seed_transfer_ok,
                 ser_allocation, ser_order, success, success_list, today, touch,
                 v_date, v_enum, v_fk, v_int)
from server import request_arg

NM = "NurseryManager"
CO = "ContractOfficer"
LO = "Landowner"


def check_lead_time(species, ship_date):
    if (ship_date - today()).days < LEAD_DAYS[species]:
        err("ERR_LEAD_TIME_INSUFFICIENT", 422,
            "requested_ship_date violates the species lead time")


# ---------------------------------------------------------------------------
# Seedling orders
# ---------------------------------------------------------------------------
@app.route("/reforestation/seedling-orders", methods=["POST"])
def create_order():
    uid, role = require_role([LO])
    d = body()
    landowner_id = d.get("landowner_id")
    if landowner_id is None:
        bad_request("missing required field: landowner_id")
    if not isinstance(landowner_id, str):
        bad_request("landowner_id must be a string id")
    if landowner_id != uid:
        err("ERR_UNAUTHORIZED", 403, "Landowner may order only for its own account")
    zone = v_fk(d, "destination_zone_id", "seed_zones")
    species = v_enum(d, "species", SPECIES)
    quantity = v_int(d, "quantity", minimum=1)
    ship_date = v_date(d, "requested_ship_date")
    check_lead_time(species, ship_date)
    rec = create_record("seedling_orders", {
        "landowner_id": landowner_id,
        "destination_zone_id": zone["id"],
        "species": species,
        "quantity": quantity,
        "requested_ship_date": ship_date,
        "unit_price_cents": {"DOUGLAS_FIR": 320, "LOBLOLLY_PINE": 280, "WHITE_OAK": 540}[species],
        "total_price_cents": calc_order_total(quantity, species),
        "status": "PENDING_REVIEW",
    })
    return success(ser_order(rec), 201)


@app.route("/reforestation/seedling-orders/<rid>", methods=["GET"])
def get_order(rid):
    uid, role = require_role([LO, CO, NM])
    rec = get_path("seedling_orders", rid)
    if role == LO:
        require_owner(rec, uid)
    return success(ser_order(rec))


@app.route("/reforestation/seedling-orders", methods=["GET"])
def list_orders():
    uid, role = require_role([LO, CO, NM])
    items = list(STORE["seedling_orders"].values())
    if role == LO:
        items = [r for r in items if r["landowner_id"] == uid]
    for f in ("landowner_id", "destination_zone_id", "status"):
        val = request_arg(f)
        if val is not None:
            items = [r for r in items if str(r.get(f)) == val]
    return success_list(items, ser_order)


@app.route("/reforestation/seedling-orders/<rid>/confirm", methods=["POST"])
def confirm_order(rid):
    require_role([CO])
    order = get_path("seedling_orders", rid)
    if order["status"] != "PENDING_REVIEW":
        invalid_state("only a PENDING_REVIEW order can be confirmed")
    check_lead_time(order["species"], order["requested_ship_date"])
    order["status"] = "CONFIRMED"
    touch(order)
    return success(ser_order(order))


@app.route("/reforestation/seedling-orders/<rid>/amend", methods=["POST"])
def amend_order(rid):
    uid, role = require_role([LO])
    order = get_path("seedling_orders", rid)
    require_owner(order, uid)
    d = body()
    # OCC (priority 4) precedes the state check (priority 5).
    expected = d.get("expected_seedling_order_version")
    if expected is None:
        bad_request("missing required field: expected_seedling_order_version")
    if not is_int(expected):
        bad_request("expected_seedling_order_version must be an integer")
    if int(expected) != order["version"]:
        err("ERR_STALE_VERSION", 412, "expected_seedling_order_version does not match")
    if order["status"] not in ("PENDING_REVIEW", "CONFIRMED"):
        invalid_state("only PENDING_REVIEW or CONFIRMED orders can be amended")
    new_qty = order["quantity"]
    if "quantity" in d and d["quantity"] is not None:
        new_qty = v_int(d, "quantity", minimum=1)
    new_ship = order["requested_ship_date"]
    if "requested_ship_date" in d and d["requested_ship_date"] is not None:
        new_ship = v_date(d, "requested_ship_date")
    check_lead_time(order["species"], new_ship)
    order["quantity"] = new_qty
    order["requested_ship_date"] = new_ship
    order["total_price_cents"] = calc_order_total(new_qty, order["species"])
    order["status"] = "PENDING_REVIEW"
    touch(order)
    return success(ser_order(order))


@app.route("/reforestation/seedling-orders/<rid>/cancel", methods=["POST"])
def cancel_order(rid):
    uid, role = require_role([LO, CO])
    order = get_path("seedling_orders", rid)
    if role == LO:
        require_owner(order, uid)
    if order["status"] not in ("PENDING_REVIEW", "CONFIRMED"):
        invalid_state("order cannot be cancelled from its current state")
    if order_shipped(order["id"]) > 0:
        err("ERR_NOT_CANCELLABLE", 409, "order has shipped quantity")
    for a in list(STORE["allocations"].values()):
        if a["seedling_order_id"] == order["id"] and a["status"] == "ACTIVE":
            release_allocation(a)
    order["status"] = "CANCELLED"
    touch(order)
    return success(ser_order(order))


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------
@app.route("/reforestation/seedling-orders/<rid>/allocations", methods=["POST"])
def create_allocation(rid):
    require_role([CO])
    order = get_path("seedling_orders", rid)
    d = body()
    batch = v_fk(d, "crop_batch_id", "crop_batches")
    # State legality (priority 5): allocation is a write on the order, whose
    # state machine admits it only from CONFIRMED or ALLOCATED (§3.3).
    if order["status"] not in ("CONFIRMED", "ALLOCATED"):
        invalid_state("allocations require a CONFIRMED or ALLOCATED order")
    lot = STORE["seed_lots"].get(batch["seed_lot_id"])
    if lot is not None and lot["status"] == "QUARANTINED":
        err("ERR_LOT_QUARANTINED", 422, "seed lot is quarantined")
    # Seed-transfer rule (priority 14) before grading-status check (priority 19).
    dest_zone = STORE["seed_zones"].get(order["destination_zone_id"])
    if lot is None or dest_zone is None or not seed_transfer_ok(batch, order, dest_zone):
        err("ERR_SPECIES_ZONE_MISMATCH", 422,
            "species mismatch or elevation midpoints more than 500 ft apart")
    quantity = v_int(d, "quantity", minimum=1)
    if batch["status"] not in ("SOWN", "LIFTED", "GRADED"):
        err("ERR_BATCH_NOT_GRADED", 422, "batch must be SOWN, LIFTED or GRADED")
    basis = batch_allocatable_basis(batch)
    ceiling = min(order["quantity"] - order_allocated(order["id"]),
                  basis - batch_reserved(batch["id"]))
    if quantity > ceiling:
        err("ERR_ALLOCATION_EXCEEDS_AVAILABLE", 422,
            "allocation exceeds order remainder or unreserved batch basis")
    rec = create_record("allocations", {
        "seedling_order_id": order["id"],
        "crop_batch_id": batch["id"],
        "quantity": quantity,
        "status": "ACTIVE",
    })
    # Creating an allocation advances the order's version by one.
    if order["status"] == "CONFIRMED" and order_allocated(order["id"]) == order["quantity"]:
        order["status"] = "ALLOCATED"
    touch(order)
    return success(ser_allocation(rec), 201)


@app.route("/reforestation/allocations/<rid>", methods=["GET"])
def get_allocation(rid):
    require_role([CO, NM])
    return success(ser_allocation(get_path("allocations", rid)))


@app.route("/reforestation/allocations", methods=["GET"])
def list_allocations():
    require_role([CO, NM])
    items = list(STORE["allocations"].values())
    for f in ("seedling_order_id", "crop_batch_id", "status"):
        val = request_arg(f)
        if val is not None:
            items = [r for r in items if str(r.get(f)) == val]
    return success_list(items, ser_allocation)


@app.route("/reforestation/allocations/<rid>/release", methods=["POST"])
def release_allocation_endpoint(rid):
    require_role([CO])
    alloc = get_path("allocations", rid)
    if alloc["status"] != "ACTIVE":
        invalid_state("only an ACTIVE allocation can be released")
    # Manual release blocked while in-flight shipments reference this batch
    # for any contract of the allocation's order.
    from server import order_contracts
    order = STORE["seedling_orders"].get(alloc["seedling_order_id"])
    cids = {c["id"] for c in order_contracts(order["id"])} if order else set()
    blocking = any(s["crop_batch_id"] == alloc["crop_batch_id"]
                   and s["planting_contract_id"] in cids
                   and s["status"] in ("DISPATCHED", "DELIVERED")
                   for s in STORE["shipments"].values())
    if blocking:
        invalid_state("in-flight shipments reference this allocation's batch")
    release_allocation(alloc)
    return success(ser_allocation(alloc))
