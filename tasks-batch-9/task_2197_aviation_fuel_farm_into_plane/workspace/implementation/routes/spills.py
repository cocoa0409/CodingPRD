"""Spill incidents, the freeze cascade and the remediation tail."""
from flask import Blueprint, request

import calc
import services as svc
from authz import (auth, body, enum, opt_str, req_num, req_str, resolve,
                   resolve_ref, rng)
from core import (ApiError, D, base_row, created, db, f2, listing, now_iso, ok,
                  public, touch)

bp = Blueprint("spills", __name__)

SURFACES = ("APRON", "TANK_BUND", "UNSEALED_GROUND", "STORM_DRAIN")


@bp.post("/spill-incidents")
def report_spill():
    auth("EnvironmentalOfficer", "IntoPlaneAgent")
    data = body()
    farm = resolve_ref(db.farms, data.get("fuel_farm_id"), "Fuel farm not found") \
        if isinstance(data.get("fuel_farm_id"), str) else None
    asset = resolve_ref(db.assets, data.get("fueling_asset_id"), "Fueling asset not found") \
        if isinstance(data.get("fueling_asset_id"), str) else None
    tank = resolve_ref(db.tanks, data.get("storage_tank_id"), "Storage tank not found") \
        if isinstance(data.get("storage_tank_id"), str) else None

    farm_id = req_str(data, "fuel_farm_id")
    volume = req_num(data, "spilled_volume_liters")
    surface = req_str(data, "surface")
    rng(volume, "spilled_volume_liters", minimum=0, exclusive_min=True)
    enum(surface, "surface", SURFACES)

    if asset is not None and asset["fuel_farm_id"] != farm_id:
        raise ApiError("ERR_CROSS_FARM_REFERENCE",
                       "The attributed asset belongs to a different farm")
    if tank is not None and tank["fuel_farm_id"] != farm_id:
        raise ApiError("ERR_CROSS_FARM_REFERENCE",
                       "The attributed tank belongs to a different farm")

    spill = base_row()
    spill.update({
        "fuel_farm_id": farm_id,
        "fueling_asset_id": asset["id"] if asset else None,
        "storage_tank_id": tank["id"] if tank else None,
        "spilled_volume_liters": f2(volume),
        "surface": surface,
        "contained_volume_liters": None,
        "regulator_reference": None,
        "reported_at_utc": now_iso(),
        "status": "REPORTED",
    })
    db.spills[spill["id"]] = spill
    svc.apply_posture_change(farm)
    touch(farm)
    return created(public(spill))


@bp.get("/spill-incidents")
def list_spills():
    auth("ConsortiumAdmin", "FarmOperator", "EnvironmentalOfficer", "IntoPlaneAgent")
    rows = list(db.spills.values())
    for field in ("fuel_farm_id", "fueling_asset_id", "storage_tank_id", "status"):
        val = request.args.get(field)
        if val:
            rows = [s for s in rows if s.get(field) == val]
    return listing(rows)


@bp.get("/spill-incidents/<sid>")
def get_spill(sid):
    auth("ConsortiumAdmin", "FarmOperator", "EnvironmentalOfficer", "IntoPlaneAgent")
    spill = resolve(db.spills, sid, "Spill incident not found")
    return ok(public(spill))


@bp.post("/spill-incidents/<sid>/escalate")
def escalate(sid):
    auth("EnvironmentalOfficer")
    spill = resolve(db.spills, sid, "Spill incident not found")
    data = body()
    reference = data.get("regulator_reference")
    if reference is not None and not isinstance(reference, str):
        raise ApiError("ERR_INVALID_PAYLOAD", "regulator_reference must be a string")
    farm = db.farms.get(spill["fuel_farm_id"])

    svc.terminal_guard("spill", spill["status"])
    if spill["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_SPILL_STATE",
                       "Spill status %s cannot be escalated" % spill["status"])

    permit = calc.governing_permit(spill["fuel_farm_id"])
    threshold = D(permit["max_reportable_spill_liters"]) if permit else D("20.0")
    if D(spill["spilled_volume_liters"]) < threshold:
        raise ApiError("ERR_SPILL_NOT_REPORTABLE",
                       "The spilled volume is below the reportable threshold")
    if not reference:
        raise ApiError("ERR_SPILL_NOT_REPORTABLE",
                       "A non-empty regulator_reference is required to escalate")

    spill["status"] = "ESCALATED"
    spill["regulator_reference"] = reference
    touch(spill)
    svc.apply_posture_change(farm, abort_reason="SPILL")
    touch(farm)
    return ok(public(spill))


@bp.post("/spill-incidents/<sid>/contain")
def contain(sid):
    auth("EnvironmentalOfficer")
    spill = resolve(db.spills, sid, "Spill incident not found")
    data = body()
    contained = req_num(data, "contained_volume_liters")
    rng(contained, "contained_volume_liters", minimum=0)
    if D(contained) > D(spill["spilled_volume_liters"]):
        raise ApiError("ERR_FIELD_OUT_OF_RANGE",
                       "contained_volume_liters must not exceed spilled_volume_liters")
    farm = db.farms.get(spill["fuel_farm_id"])

    svc.terminal_guard("spill", spill["status"])
    if spill["status"] not in ("REPORTED", "ESCALATED"):
        raise ApiError("ERR_INVALID_SPILL_STATE",
                       "Spill status %s cannot be contained" % spill["status"])

    if spill["status"] == "REPORTED":
        permit = calc.governing_permit(spill["fuel_farm_id"])
        threshold = D(permit["max_reportable_spill_liters"]) if permit else D("20.0")
        if D(spill["spilled_volume_liters"]) >= threshold:
            raise ApiError("ERR_SPILL_NOT_REPORTABLE",
                           "A reportable spill must be escalated before containment")

    spill["status"] = "CONTAINED"
    spill["contained_volume_liters"] = f2(contained)
    touch(spill)
    asset = db.assets.get(spill.get("fueling_asset_id"))
    if asset is not None:
        calc.recompute_asset(asset)
        touch(asset)
    svc.apply_posture_change(farm, abort_reason="SPILL")
    touch(farm)
    return ok(public(spill))


@bp.post("/spill-incidents/<sid>/remediate")
def remediate(sid):
    auth("EnvironmentalOfficer")
    spill = resolve(db.spills, sid, "Spill incident not found")
    body()
    svc.terminal_guard("spill", spill["status"])
    if spill["status"] != "CONTAINED":
        raise ApiError("ERR_INVALID_SPILL_STATE",
                       "Spill status %s cannot be remediated" % spill["status"])
    spill["status"] = "REMEDIATED"
    touch(spill)
    return ok(public(spill))


@bp.post("/spill-incidents/<sid>/close")
def close(sid):
    auth("EnvironmentalOfficer")
    spill = resolve(db.spills, sid, "Spill incident not found")
    body()
    farm = db.farms.get(spill["fuel_farm_id"])
    svc.terminal_guard("spill", spill["status"])
    if spill["status"] != "REMEDIATED":
        raise ApiError("ERR_INVALID_SPILL_STATE",
                       "Spill status %s cannot be closed" % spill["status"])
    if spill["surface"] == "STORM_DRAIN" and not spill.get("regulator_reference"):
        raise ApiError("ERR_SPILL_NOT_REPORTABLE",
                       "A STORM_DRAIN release cannot be closed without a regulator reference")
    spill["status"] = "CLOSED"
    touch(spill)
    svc.apply_posture_change(farm, abort_reason="SPILL")
    touch(farm)
    return ok(public(spill))
