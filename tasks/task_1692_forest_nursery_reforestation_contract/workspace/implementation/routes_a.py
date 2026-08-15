"""Clock, landowners, seed zones, seed lots, crop batches."""
from datetime import datetime, timezone

from server import (STORE, SPECIES, LEAD_DAYS, app, bad_request, body, calc_projected_plantable,
                 create_record, err, fmt_dt, get_path, invalid_state, is_int,
                 lot_remaining, not_found, request_arg, require_role, ser_crop_batch, ser_landowner,
                 ser_seed_lot, ser_seed_zone, success, success_list, today, touch,
                 v_date, v_datetime, v_enum, v_fk, v_int, v_num, v_str, v_bool,
                 release_allocation, check_batch_depleted, parse_date)

NM = "NurseryManager"
CO = "ContractOfficer"
FA = "FieldAuditor"
PA = "ProgramAdministrator"
LO = "Landowner"


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@app.route("/reforestation/_clock/set_current_utc", methods=["POST"])
def set_clock():
    from server import CLOCK
    require_role([NM, CO, PA, FA])
    d = body()
    target = v_datetime(d, "to_iso8601")
    CLOCK["now"] = target
    return success({"current_utc": fmt_dt(CLOCK["now"])}, 200)


# ---------------------------------------------------------------------------
# Landowners
# ---------------------------------------------------------------------------
@app.route("/reforestation/landowners", methods=["POST"])
def create_landowner():
    require_role([CO])
    d = body()
    rec = create_record("landowners", {
        "legal_name": v_str(d, "legal_name"),
        "contact_email": v_str(d, "contact_email"),
        "tax_id": v_str(d, "tax_id"),
        "cost_share_eligible": v_bool(d, "cost_share_eligible", True),
    })
    return success(ser_landowner(rec), 201)


@app.route("/reforestation/landowners/<rid>", methods=["GET"])
def get_landowner(rid):
    uid, role = require_role([CO, PA, LO])
    rec = get_path("landowners", rid)
    if role == LO and rec["id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Landowner may read only its own record")
    return success(ser_landowner(rec))


# ---------------------------------------------------------------------------
# Seed zones
# ---------------------------------------------------------------------------
@app.route("/reforestation/seed-zones", methods=["POST"])
def create_seed_zone():
    require_role([NM])
    d = body()
    zone_code = v_str(d, "zone_code")
    min_e = v_int(d, "min_elevation_ft")
    max_e = v_int(d, "max_elevation_ft")
    if min_e >= max_e:
        err("ERR_WINDOW_INVERTED", 400, "min_elevation_ft must be strictly below max_elevation_ft")
    if min_e < 0:
        bad_request("min_elevation_ft must be >= 0")
    if any(z["zone_code"] == zone_code for z in STORE["seed_zones"].values()):
        bad_request("zone_code must be unique")
    rec = create_record("seed_zones", {
        "zone_code": zone_code,
        "min_elevation_ft": min_e,
        "max_elevation_ft": max_e,
        "band_midpoint_ft": (min_e + max_e) / 2,
    })
    return success(ser_seed_zone(rec), 201)


@app.route("/reforestation/seed-zones/<rid>", methods=["GET"])
def get_seed_zone(rid):
    require_role([NM, CO])
    return success(ser_seed_zone(get_path("seed_zones", rid)))


# ---------------------------------------------------------------------------
# Seed lots
# ---------------------------------------------------------------------------
@app.route("/reforestation/seed-lots", methods=["POST"])
def create_seed_lot():
    require_role([NM])
    d = body()
    zone = v_fk(d, "source_zone_id", "seed_zones")
    species = v_enum(d, "species", SPECIES)
    collected_on = v_date(d, "collected_on")
    quantity_grams = v_int(d, "quantity_grams", minimum=1)
    germ = v_num(d, "germination_pct")
    if not (germ > 0 and germ <= 1):
        bad_request("germination_pct must be in (0, 1]")
    rec = create_record("seed_lots", {
        "source_zone_id": zone["id"],
        "species": species,
        "collected_on": collected_on,
        "quantity_grams": quantity_grams,
        "germination_pct": germ,
        "status": "AVAILABLE",
    })
    return success(ser_seed_lot(rec), 201)


@app.route("/reforestation/seed-lots/<rid>", methods=["GET"])
def get_seed_lot(rid):
    require_role([NM, CO])
    return success(ser_seed_lot(get_path("seed_lots", rid)))


@app.route("/reforestation/seed-lots", methods=["GET"])
def list_seed_lots():
    require_role([NM, CO])
    items = list(STORE["seed_lots"].values())
    for f in ("source_zone_id", "species", "status"):
        val = request_arg(f)
        if val is not None:
            items = [r for r in items if str(r.get(f)) == val]
    return success_list(items, ser_seed_lot)



@app.route("/reforestation/seed-lots/<rid>/quarantine", methods=["POST"])
def quarantine_seed_lot(rid):
    require_role([NM])
    lot = get_path("seed_lots", rid)
    if lot["status"] != "AVAILABLE":
        invalid_state("only an AVAILABLE lot can be quarantined")
    lot["status"] = "QUARANTINED"
    touch(lot)
    return success(ser_seed_lot(lot))


@app.route("/reforestation/seed-lots/<rid>/release", methods=["POST"])
def release_seed_lot(rid):
    require_role([NM])
    lot = get_path("seed_lots", rid)
    if lot["status"] != "QUARANTINED":
        invalid_state("only a QUARANTINED lot can be released")
    d = body()
    retest = v_num(d, "retest_germination_pct")
    if not (retest > 0 and retest <= 1):
        bad_request("retest_germination_pct must be in (0, 1]")
    lot["germination_pct"] = retest
    lot["status"] = "AVAILABLE"
    touch(lot)
    # Recompute projected_plantable for PLANNED batches of this lot.
    for b in STORE["crop_batches"].values():
        if b["seed_lot_id"] == lot["id"] and b["status"] == "PLANNED" and b.get("sown_grams"):
            b["projected_plantable"] = calc_projected_plantable(
                b["sown_grams"], lot["germination_pct"], lot["species"])
            touch(b)
    return success(ser_seed_lot(lot))


# ---------------------------------------------------------------------------
# Crop batches
# ---------------------------------------------------------------------------
@app.route("/reforestation/crop-batches", methods=["POST"])
def create_crop_batch():
    require_role([NM])
    d = body()
    lot = v_fk(d, "seed_lot_id", "seed_lots")
    # OCC (priority 4) before state/shape/window checks.
    expected = d.get("expected_seed_lot_version")
    if expected is None:
        bad_request("missing required field: expected_seed_lot_version")
    if not is_int(expected):
        bad_request("expected_seed_lot_version must be an integer")
    if int(expected) != lot["version"]:
        err("ERR_STALE_VERSION", 412, "expected_seed_lot_version does not match lot version")
    planned_sow_date = v_date(d, "planned_sow_date")
    lw_start = v_date(d, "lift_window_start")
    lw_end = v_date(d, "lift_window_end")
    if lw_end < lw_start:
        err("ERR_WINDOW_INVERTED", 400, "lift_window_end must be >= lift_window_start")
    rec = create_record("crop_batches", {
        "seed_lot_id": lot["id"],
        "planned_sow_date": planned_sow_date,
        "lift_window_start": lw_start,
        "lift_window_end": lw_end,
        "actual_sow_date": None,
        "sown_grams": None,
        "projected_plantable": None,
        "lifted_on": None,
        "lifted_count": None,
        "plantable_count": None,
        "status": "PLANNED",
    })
    # Recording the plan advances the lot's version.
    touch(lot)
    return success(ser_crop_batch(rec), 201)


@app.route("/reforestation/crop-batches/<rid>", methods=["GET"])
def get_crop_batch(rid):
    require_role([NM, CO])
    return success(ser_crop_batch(get_path("crop_batches", rid)))


@app.route("/reforestation/crop-batches", methods=["GET"])
def list_crop_batches():
    require_role([NM, CO])
    items = list(STORE["crop_batches"].values())
    for f in ("seed_lot_id", "status"):
        val = request_arg(f)
        if val is not None:
            items = [r for r in items if str(r.get(f)) == val]
    return success_list(items, ser_crop_batch)


@app.route("/reforestation/crop-batches/<rid>/sow", methods=["POST"])
def sow_crop_batch(rid):
    require_role([NM])
    batch = get_path("crop_batches", rid)
    if batch["status"] != "PLANNED":
        invalid_state("only a PLANNED batch can be sown")
    lot = STORE["seed_lots"][batch["seed_lot_id"]]
    if lot["status"] == "QUARANTINED":
        err("ERR_LOT_QUARANTINED", 422, "seed lot is quarantined")
    if lot["status"] != "AVAILABLE":
        # PRD §3.2: sowing "requires the lot to be AVAILABLE"; a non-quarantined
        # non-AVAILABLE lot (DEPLETED, terminal per §3.1) fails state legality.
        invalid_state("sowing requires the seed lot to be AVAILABLE")
    d = body()
    actual_sow_date = v_date(d, "actual_sow_date")
    sown_grams = v_int(d, "sown_grams", minimum=1)
    if sown_grams > lot_remaining(lot):
        bad_request("sown_grams exceeds the lot's remaining_grams")
    batch["actual_sow_date"] = actual_sow_date
    batch["sown_grams"] = sown_grams
    batch["status"] = "SOWN"
    batch["projected_plantable"] = calc_projected_plantable(
        sown_grams, lot["germination_pct"], lot["species"])
    touch(batch)
    # Lot debit: remaining_grams is derived; advance version, auto-DEPLETED at 0.
    touch(lot)
    if lot_remaining(lot) == 0:
        lot["status"] = "DEPLETED"
    return success(ser_crop_batch(batch))


@app.route("/reforestation/crop-batches/<rid>/lift", methods=["POST"])
def lift_crop_batch(rid):
    require_role([NM])
    batch = get_path("crop_batches", rid)
    if batch["status"] != "SOWN":
        invalid_state("only a SOWN batch can be lifted")
    d = body()
    lifted_on = v_date(d, "lifted_on")
    if not (batch["lift_window_start"] <= lifted_on <= batch["lift_window_end"]):
        err("ERR_LIFT_WINDOW_INVALID", 422, "lifted_on outside the lift window")
    lifted_count = v_int(d, "lifted_count", minimum=1)
    batch["lifted_on"] = lifted_on
    batch["lifted_count"] = lifted_count
    batch["status"] = "LIFTED"
    touch(batch)
    return success(ser_crop_batch(batch))


@app.route("/reforestation/crop-batches/<rid>/grade", methods=["POST"])
def grade_crop_batch(rid):
    require_role([NM])
    batch = get_path("crop_batches", rid)
    if batch["status"] != "LIFTED":
        invalid_state("only a LIFTED batch can be graded")
    d = body()
    plantable_count = v_int(d, "plantable_count", minimum=1)
    if plantable_count > batch["lifted_count"]:
        bad_request("plantable_count may not exceed lifted_count")
    batch["plantable_count"] = plantable_count
    batch["status"] = "GRADED"
    touch(batch)
    # CASCADE A: release newest-created ACTIVE allocations until reserved <= plantable.
    from server import batch_reserved
    guard = 0
    while batch_reserved(batch["id"]) > plantable_count:
        guard += 1
        if guard > 100000:
            break
        actives = [a for a in STORE["allocations"].values()
                   if a["crop_batch_id"] == batch["id"] and a["status"] == "ACTIVE"]
        if not actives:
            break
        latest = max(actives, key=lambda a: a["_seq"])
        release_allocation(latest)
    return success(ser_crop_batch(batch))
