"""Storage units and storage placements."""
from server import (STORE, app, bad_request, batch_placed_remainder_capacity, body,
                 check_batch_depleted, create_record, err, get_path, invalid_state,
                 require_role, ser_storage_placement, ser_storage_unit, success,
                 success_list, touch, unit_load, v_date, v_fk, v_int, v_num, v_str)
from server import request_arg

NM = "NurseryManager"


# ---------------------------------------------------------------------------
# Storage units
# ---------------------------------------------------------------------------
@app.route("/reforestation/storage-units", methods=["POST"])
def create_storage_unit():
    require_role([NM])
    d = body()
    unit_code = v_str(d, "unit_code")
    capacity = v_int(d, "capacity_units", minimum=1)
    tmin = v_num(d, "temp_min_c")
    tmax = v_num(d, "temp_max_c")
    if not (tmax > tmin):
        bad_request("temp_max_c must be strictly greater than temp_min_c")
    if any(u["unit_code"] == unit_code for u in STORE["storage_units"].values()):
        bad_request("unit_code must be unique")
    rec = create_record("storage_units", {
        "unit_code": unit_code, "capacity_units": capacity,
        "temp_min_c": tmin, "temp_max_c": tmax,
    })
    return success(ser_storage_unit(rec), 201)


@app.route("/reforestation/storage-units/<rid>", methods=["GET"])
def get_storage_unit(rid):
    require_role([NM])
    return success(ser_storage_unit(get_path("storage_units", rid)))


# ---------------------------------------------------------------------------
# Storage placements
# ---------------------------------------------------------------------------
@app.route("/reforestation/storage-placements", methods=["POST"])
def create_storage_placement():
    require_role([NM])
    d = body()
    batch = v_fk(d, "crop_batch_id", "crop_batches")
    unit = v_fk(d, "storage_unit_id", "storage_units")
    quantity = v_int(d, "quantity", minimum=1)
    placed_on = v_date(d, "placed_on")
    plantable = batch.get("plantable_count") or 0
    if quantity > plantable - batch_placed_remainder_capacity(batch["id"]):
        err("ERR_PLACEMENT_EXCEEDS_PLANTABLE", 422,
            "placement exceeds the batch's unplaced plantable remainder")
    if unit_load(unit["id"]) + quantity > unit["capacity_units"]:
        err("ERR_STORAGE_CAPACITY_EXCEEDED", 422,
            "placement would exceed the unit's capacity")
    rec = create_record("storage_placements", {
        "crop_batch_id": batch["id"],
        "storage_unit_id": unit["id"],
        "quantity": quantity,
        "placed_on": placed_on,
        "withdrawn_quantity": 0,
        "status": "ACTIVE",
    })
    return success(ser_storage_placement(rec), 201)


@app.route("/reforestation/storage-placements/<rid>", methods=["GET"])
def get_storage_placement(rid):
    require_role([NM])
    return success(ser_storage_placement(get_path("storage_placements", rid)))


@app.route("/reforestation/storage-placements", methods=["GET"])
def list_storage_placements():
    require_role([NM])
    items = list(STORE["storage_placements"].values())
    for f in ("crop_batch_id", "storage_unit_id", "status"):
        val = request_arg(f)
        if val is not None:
            items = [r for r in items if str(r.get(f)) == val]
    return success_list(items, ser_storage_placement)


@app.route("/reforestation/storage-placements/<rid>/discard", methods=["POST"])
def discard_storage_placement(rid):
    require_role([NM])
    placement = get_path("storage_placements", rid)
    if placement["status"] != "ACTIVE":
        invalid_state("only an ACTIVE placement can be discarded")
    d = body()
    reason = d.get("reason")
    if reason is None:
        bad_request("missing required field: reason")
    if not isinstance(reason, str):
        bad_request("reason must be a string")
    placement["discard_reason"] = reason
    placement["status"] = "DISCARDED"
    touch(placement)
    check_batch_depleted(STORE["crop_batches"][placement["crop_batch_id"]])
    return success(ser_storage_placement(placement))
