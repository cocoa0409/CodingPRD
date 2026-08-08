"""Wells, water samples and the groundwater advisory cascade."""
from flask import Blueprint

import calc
import derive
import lookup
import response
import serialize
import store
import validate as v
from auth import authenticate
from store import ordered, touch

bp = Blueprint("wells", __name__)

WELL_TYPES = ("DOMESTIC", "IRRIGATION", "MONITORING")
WELL_READ_ROLES = ["Applicant", "DesignProfessional",
                   "EnvironmentalHealthSpecialist", "HealthOfficer",
                   "RecordsClerk"]

ADVISORY_TRANSITIONS = {
    ("CLEAR", "EXCEEDANCE"): "ADVISORY",
    ("CLEAR", "UNSAFE"): "CONDEMNED",
    ("ADVISORY", "UNSAFE"): "CONDEMNED",
    ("ADVISORY", "PASS"): "CLEAR",
}


@bp.post("/wells")
def create_well():
    authenticate(["Applicant", "DesignProfessional"])
    body = v.body()
    parcel = lookup.parcel(v.req_fk(body, "parcel_id"))
    well_type = v.req_enum(body, "well_type", WELL_TYPES)
    location_x_ft = v.req_num(body, "location_x_ft")
    location_y_ft = v.req_num(body, "location_y_ft")
    depth_ft = v.req_int(body, "depth_ft", minimum=1)

    well = store.new_record()
    well.update({
        "parcel_id": parcel["id"],
        "well_type": well_type,
        "location_x_ft": location_x_ft,
        "location_y_ft": location_y_ft,
        "depth_ft": depth_ft,
        "advisory_status": "CLEAR",
        "last_sample_collected_at": None,
    })
    store.wells[well["id"]] = well

    # Recording a well re-derives every live design's setback posture from bare
    # geometry, discarding any earlier variance verdict (PRD 3.2 / 3.4).
    for design in derive.designs_of_parcel(parcel["id"]):
        if design["status"] in derive.DESIGN_GEOMETRY_STATES:
            before = (design["nearest_well_distance_ft"],
                      design["required_setback_ft"], design["setback_status"])
            derive.recompute_design_setback(design, clear_sticky=True)
            after = (design["nearest_well_distance_ft"],
                     design["required_setback_ft"], design["setback_status"])
            if before != after:
                touch(design)

    derive.recompute_parcel(parcel)
    return response.ok(serialize.well(well), 201)


@bp.get("/wells/<well_id>")
def read_well(well_id):
    authenticate(WELL_READ_ROLES)
    well = lookup.well(well_id)
    return response.ok(serialize.well(well))


@bp.get("/wells/<well_id>/water-samples")
def list_water_samples(well_id):
    authenticate(WELL_READ_ROLES)
    well = lookup.well(well_id)
    limit, offset = v.pagination()
    result = v.q("result")
    rows = [s for s in ordered(store.water_samples.values())
            if s["well_id"] == well["id"]]
    if result is not None:
        rows = [r for r in rows if r["result"] == result]
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(serialize.many("water_sample", page),
                            limit, offset, total)


@bp.post("/wells/<well_id>/water-samples")
def post_water_sample(well_id):
    authenticate(["EnvironmentalHealthSpecialist"])
    well = lookup.well(well_id)
    body = v.body()
    collected_at = v.req_dt(body, "collected_at")
    nitrate_mg_l = v.req_num(body, "nitrate_mg_l", minimum=0)
    coliform_present = v.req_bool(body, "coliform_present")

    result, reasons = calc.water_sample_result(nitrate_mg_l, coliform_present)
    sample = store.new_record(with_version=False)
    sample.update({
        "well_id": well["id"],
        "collected_at": collected_at,
        "nitrate_mg_l": nitrate_mg_l,
        "coliform_present": coliform_present,
        "result": result,
        "exceedance_reasons": reasons,
    })
    store.water_samples[sample["id"]] = sample

    # Cascade step 1 -- the well's own posture.
    well["last_sample_collected_at"] = collected_at
    new_status = ADVISORY_TRANSITIONS.get((well["advisory_status"], result))
    if new_status is not None:
        well["advisory_status"] = new_status
    touch(well)

    # Cascade steps 2-4 -- parcel, operating permits, compliance posture.
    parcel = store.parcels.get(well["parcel_id"])
    if parcel is not None:
        derive.water_quality_cascade(parcel)

    return response.ok(serialize.water_sample(sample), 201)
