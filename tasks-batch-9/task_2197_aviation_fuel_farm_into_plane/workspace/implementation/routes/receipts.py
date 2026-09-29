"""Fuel receipts, the quality-control chain and sample test results."""
from flask import Blueprint, request

import calc
import services as svc
from authz import (auth, body, enum, opt_num, out_of_range, req_int, req_num,
                   req_str, resolve, resolve_ref, rng)
from core import (ApiError, D, base_row, created, db, f2, listing, now_iso, ok,
                  public, touch)
from routes.tanks import new_sample, tank_view

bp = Blueprint("receipts", __name__)

DELIVERY_MODES = ("PIPELINE", "TRUCK")
RECEIPT_TERMINAL = ("RELEASED", "REJECTED")


def fk_row(data, field, coll, label):
    """Band-2 FK resolution: only when the value is present and a string."""
    v = data.get(field)
    if isinstance(v, str) and v:
        row = coll.get(v)
        if row is None:
            raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", "%s %s not found" % (label, v))
        return row
    return None


# ------------------------------------------------------------------ receipts
@bp.post("/fuel-receipts")
def create_receipt():
    auth("FarmOperator")
    data = body()
    fk_row(data, "storage_tank_id", db.tanks, "Storage tank")

    tank_id = req_str(data, "storage_tank_id")
    mode = req_str(data, "delivery_mode")
    supplier = req_str(data, "supplier_name")
    ticket = req_str(data, "meter_ticket_number")
    meter_gross = req_num(data, "meter_ticket_gross_liters")
    open_gauge = req_num(data, "tank_opening_gauge_liters")
    close_gauge = req_num(data, "tank_closing_gauge_liters")
    temperature = req_num(data, "temperature_c")
    cert_density = req_num(data, "certificate_density_kg_per_m3")
    water = opt_num(data, "measured_water_liters", "0.0")

    enum(mode, "delivery_mode", DELIVERY_MODES)
    rng(meter_gross, "meter_ticket_gross_liters", minimum=0, exclusive_min=True)
    rng(open_gauge, "tank_opening_gauge_liters", minimum=0)
    if D(close_gauge) <= D(open_gauge):
        out_of_range("tank_closing_gauge_liters must exceed tank_opening_gauge_liters")
    rng(temperature, "temperature_c", minimum=-20, maximum=60)
    rng(cert_density, "certificate_density_kg_per_m3", minimum=750, maximum=850)
    rng(water, "measured_water_liters", minimum=0)

    for r in db.receipts.values():
        if r["meter_ticket_number"] == ticket:
            raise ApiError("ERR_DUPLICATE_KEY", "meter_ticket_number %s already exists" % ticket)

    tank = db.tanks[tank_id]
    farm = db.farms.get(tank["fuel_farm_id"])
    svc.posture_and_permit_guard(farm)

    volumes = calc.receipt_volumes(mode, meter_gross, open_gauge, close_gauge,
                                   temperature, cert_density, water)
    receipt = base_row()
    receipt.update({
        "storage_tank_id": tank_id,
        "delivery_mode": mode,
        "supplier_name": supplier,
        "meter_ticket_number": ticket,
        "meter_ticket_gross_liters": f2(meter_gross),
        "tank_opening_gauge_liters": f2(open_gauge),
        "tank_closing_gauge_liters": f2(close_gauge),
        "temperature_c": float(D(temperature)),
        "certificate_density_kg_per_m3": f2(cert_density),
        "measured_water_liters": f2(water),
        "status": "RECORDED",
        "sampled_by_user_id": None,
        "released_by_user_id": None,
        "released_at_utc": None,
        "retest_round": 0,
    })
    receipt.update(volumes)
    db.receipts[receipt["id"]] = receipt
    return created(public(receipt))


@bp.get("/fuel-receipts")
def list_receipts():
    auth("ConsortiumAdmin", "FarmOperator", "QualityInspector")
    rows = list(db.receipts.values())
    tank_id = request.args.get("storage_tank_id")
    status = request.args.get("status")
    if tank_id:
        rows = [r for r in rows if r["storage_tank_id"] == tank_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows)


@bp.get("/fuel-receipts/<rid>")
def get_receipt(rid):
    auth("ConsortiumAdmin", "FarmOperator", "QualityInspector")
    receipt = resolve(db.receipts, rid, "Fuel receipt not found")
    return ok(public(receipt))


# ------------------------------------------------------------------ sampling
@bp.post("/fuel-receipts/<rid>/samples")
def draw_receipt_sample(rid):
    uid, role = auth("QualityInspector")
    receipt = resolve(db.receipts, rid, "Fuel receipt not found")
    body()
    tank = db.tanks.get(receipt["storage_tank_id"])
    farm = db.farms.get(tank["fuel_farm_id"]) if tank else None

    svc.terminal_guard("receipt", receipt["status"])
    if receipt["status"] not in ("RECORDED", "QUARANTINED"):
        raise ApiError("ERR_INVALID_RECEIPT_STATE",
                       "Receipt status %s cannot be sampled" % receipt["status"])
    svc.frozen_guard(farm)
    if tank is not None and tank["service_status"] == "OUT_OF_SERVICE":
        raise ApiError("ERR_INVALID_TANK_STATE", "Destination tank is OUT_OF_SERVICE")
    retest = receipt["status"] == "QUARANTINED"
    if retest and receipt["retest_round"] > 1:
        raise ApiError("ERR_RETEST_LIMIT_REACHED",
                       "Receipt has already been re-sampled twice")

    sample = new_sample("RECEIPT_QC", uid, receipt_id=receipt["id"])
    if retest:
        receipt["retest_round"] = receipt["retest_round"] + 1
    receipt["status"] = "SAMPLED"
    receipt["sampled_by_user_id"] = uid
    touch(receipt)
    return created(public(sample))


@bp.post("/quality-samples/<sid>/test-results")
def post_test_results(sid):
    uid, role = auth("QualityInspector")
    sample = resolve(db.samples, sid, "Quality sample not found")
    data = body()

    metrics = {}
    v = data.get("water_reaction_rating")
    if v is not None:
        if not isinstance(v, int) or isinstance(v, bool):
            raise ApiError("ERR_INVALID_PAYLOAD", "water_reaction_rating must be an integer")
        rng(v, "water_reaction_rating", minimum=1, maximum=3)
        metrics["water_reaction_rating"] = v
    particulate = opt_num(data, "particulate_mg_per_l")
    if particulate is not None:
        rng(particulate, "particulate_mg_per_l", minimum=0)
        metrics["particulate_mg_per_l"] = float(particulate)
    conductivity = opt_num(data, "conductivity_ps_per_m")
    if conductivity is not None:
        rng(conductivity, "conductivity_ps_per_m", minimum=0)
        metrics["conductivity_ps_per_m"] = float(conductivity)
    density = opt_num(data, "observed_density_kg_per_m3")
    if density is not None:
        metrics["observed_density_kg_per_m3"] = float(density)
    flash = opt_num(data, "flash_point_c")
    if flash is not None:
        metrics["flash_point_c"] = float(flash)

    receipt = db.receipts.get(sample.get("fuel_receipt_id")) if sample.get("fuel_receipt_id") else None
    tank = db.tanks.get(sample.get("storage_tank_id")) if sample.get("storage_tank_id") else None
    asset = db.assets.get(sample.get("fueling_asset_id")) if sample.get("fueling_asset_id") else None

    if sample["status"] != "DRAWN":
        if receipt is not None:
            raise ApiError("ERR_INVALID_RECEIPT_STATE", "Sample has already been tested")
        if tank is not None:
            raise ApiError("ERR_INVALID_TANK_STATE", "Sample has already been tested")
        raise ApiError("ERR_INVALID_ASSET_STATE", "Sample has already been tested")
    if receipt is not None:
        svc.terminal_guard("receipt", receipt["status"])
        if receipt["status"] != "SAMPLED":
            raise ApiError("ERR_INVALID_RECEIPT_STATE",
                           "Receipt status %s cannot accept test results" % receipt["status"])
    if not metrics:
        raise ApiError("ERR_EMPTY_TEST_RESULT_SET", "At least one metric must be posted")

    for k, val in metrics.items():
        sample[k] = val
    if receipt is not None:
        comparison = receipt["certificate_density_kg_per_m3"]
    else:
        parent_tank = tank
        if parent_tank is None and asset is not None:
            # An asset sample compares against the tank the asset last drew from.
            orders = [o for o in db.orders.values()
                      if o.get("fueling_asset_id") == asset["id"]]
            orders = sorted(orders, key=lambda o: (o["created_at"], o["_seq"]))
            if orders:
                parent_tank = db.tanks.get(orders[-1]["storage_tank_id"])
        comparison = parent_tank["density_kg_per_m3"] if parent_tank else None
    verdict, failed = calc.sample_verdict(sample, comparison)
    sample["verdict"] = verdict
    sample["failed_metrics"] = failed
    sample["status"] = "TESTED"
    sample["tested_by_user_id"] = uid
    touch(sample)
    if receipt is not None:
        receipt["status"] = "UNDER_TEST"
        touch(receipt)
    return ok(public(sample))


@bp.get("/quality-samples")
def list_samples():
    auth("ConsortiumAdmin", "FarmOperator", "QualityInspector")
    rows = list(db.samples.values())
    for field in ("fuel_receipt_id", "storage_tank_id", "fueling_asset_id", "status"):
        val = request.args.get(field)
        if val:
            rows = [s for s in rows if s.get(field) == val]
    return listing(rows)


@bp.get("/quality-samples/<sid>")
def get_sample(sid):
    auth("ConsortiumAdmin", "FarmOperator", "QualityInspector")
    sample = resolve(db.samples, sid, "Quality sample not found")
    return ok(public(sample))


# ------------------------------------------------------------------ verdict
@bp.post("/fuel-receipts/<rid>/verdict")
def sign_verdict(rid):
    uid, role = auth("QualityInspector")
    receipt = resolve(db.receipts, rid, "Fuel receipt not found")
    data = body()
    decision = req_str(data, "decision")
    enum(decision, "decision", ("RELEASE", "QUARANTINE"))

    tank = db.tanks.get(receipt["storage_tank_id"])
    farm = db.farms.get(tank["fuel_farm_id"]) if tank else None

    svc.terminal_guard("receipt", receipt["status"])
    if receipt["status"] != "UNDER_TEST":
        raise ApiError("ERR_INVALID_RECEIPT_STATE",
                       "Receipt status %s cannot be signed" % receipt["status"])
    permit = svc.posture_and_permit_guard(farm)
    if uid == receipt.get("sampled_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The inspector who drew the sample may not sign the verdict")

    sample = svc.latest_tested_sample(receipt["id"])
    if sample is None:
        raise ApiError("ERR_SAMPLE_VERDICT_FAIL", "No TESTED sample exists for this receipt")
    if decision == "RELEASE" and sample.get("verdict") == "FAIL":
        raise ApiError("ERR_SAMPLE_VERDICT_FAIL", "The latest tested sample verdict is FAIL")

    if decision == "RELEASE":
        calc.recompute_tank(tank)
        net = D(receipt["net_volume_liters"])
        if D(tank["book_volume_liters"]) + net > D(tank["safe_fill_liters"]):
            raise ApiError("ERR_SAFE_FILL_EXCEEDED",
                           "Release would exceed the tank's safe fill volume")
        used = calc.permit_day_throughput(farm["id"])
        if used + net > D(permit["max_daily_throughput_liters"]):
            raise ApiError("ERR_PERMIT_THROUGHPUT_EXCEEDED",
                           "Release would exceed the permitted daily throughput")
        receipt["status"] = "RELEASED"
        receipt["released_at_utc"] = now_iso()
        receipt["released_by_user_id"] = uid
        touch(receipt)
        calc.recompute_tank(tank)
        touch(tank)
        svc.refresh_farm(farm)
        touch(farm)
    else:
        receipt["status"] = "QUARANTINED"
        receipt["released_by_user_id"] = uid
        touch(receipt)
        svc.quarantine_tank(tank)
        touch(tank)
        svc.refresh_farm(farm)
        touch(farm)
    return ok(public(receipt))


@bp.post("/fuel-receipts/<rid>/reject")
def reject_receipt(rid):
    auth("FarmOperator")
    receipt = resolve(db.receipts, rid, "Fuel receipt not found")
    body()
    tank = db.tanks.get(receipt["storage_tank_id"])
    farm = db.farms.get(tank["fuel_farm_id"]) if tank else None

    svc.terminal_guard("receipt", receipt["status"])
    if receipt["status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_RECEIPT_STATE",
                       "Receipt status %s cannot be rejected" % receipt["status"])

    receipt["status"] = "REJECTED"
    touch(receipt)
    if tank is not None:
        svc.maybe_heal_tank(tank)
        calc.recompute_tank(tank)
        touch(tank)
    if farm is not None:
        svc.refresh_farm(farm)
    return ok(public(receipt))
