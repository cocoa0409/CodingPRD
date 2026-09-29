"""Cross-entity business services: posture, melt ledger, cascades, lot helpers."""

from datetime import timedelta

import calc
from calc import D, ZERO, rhu
from errors import fail
from store import db, base_record, ordered, touch


# --------------------------------------------------------------------------- #
# lookups
# --------------------------------------------------------------------------- #
def require(collection, resource_id, error_id):
    if not isinstance(resource_id, str):
        fail(error_id)
    record = collection.get(resource_id)
    if record is None:
        fail(error_id)
    return record


def code_taken(collection, field, value):
    return any(record.get(field) == value for record in collection.values())


def check_unique(collection, field, value):
    if code_taken(collection, field, value):
        fail("ERR_CODE_NOT_UNIQUE", "%s '%s' is already in use." % (field, value))


def children(collection, key, value):
    return ordered([r for r in collection.values() if r.get(key) == value])


# --------------------------------------------------------------------------- #
# furnace posture / refractory
# --------------------------------------------------------------------------- #
def derive_posture(furnace):
    """PRD 2.6: ordered cascade, first matching rule wins."""
    for campaign in db.campaigns.values():
        if campaign["furnace_id"] == furnace["id"] and campaign["status"] == "REBUILD_SCHEDULED":
            return "COLD"
    if furnace["refractory_remaining_pct"] <= calc.REBUILD_DUE_PCT:
        return "REBUILD_DUE"
    if furnace["refractory_remaining_pct"] <= calc.RESTRICTED_PCT:
        return "RESTRICTED"
    return "OPERATING"


def apply_posture(furnace):
    furnace["posture"] = derive_posture(furnace)


def recompute_remaining(furnace):
    furnace["refractory_remaining_pct"] = calc.remaining_pct(
        furnace["refractory_consumed_units"], furnace["refractory_life_total_units"]
    )


def add_reserved_pull(furnace, delta):
    value = rhu(D(furnace["reserved_pull_tons"]) + D(delta), 2)
    if value < ZERO:
        value = ZERO
    furnace["reserved_pull_tons"] = value


# --------------------------------------------------------------------------- #
# campaign melt ledger
# --------------------------------------------------------------------------- #
def reconcile_campaign(campaign):
    campaign["unaccounted_loss_tons"] = rhu(
        D(campaign["melt_tons_charged"])
        - D(campaign["packed_tons"])
        - D(campaign["transition_loss_tons"])
        - D(campaign["reject_loss_tons"]),
        2,
    )


def add_ledger(campaign, field, delta):
    campaign[field] = rhu(D(campaign[field]) + D(delta), 2)
    reconcile_campaign(campaign)


def live_campaign_for_furnace(furnace_id):
    for campaign in ordered(list(db.campaigns.values())):
        if campaign["furnace_id"] == furnace_id and campaign["status"] in ("ACTIVE", "WIND_DOWN"):
            return campaign
    return None


def campaign_jobs(campaign_id):
    return [j for j in db.production_jobs.values() if j["campaign_id"] == campaign_id]


# --------------------------------------------------------------------------- #
# campaign wind-down cascade (PRD 3.2)
# --------------------------------------------------------------------------- #
def wind_down(campaign):
    furnace = db.furnaces[campaign["furnace_id"]]
    campaign["status"] = "WIND_DOWN"
    for job in ordered(campaign_jobs(campaign["id"])):
        if job["status"] == "SCHEDULED" and job["window_start_at"] >= db.clock:
            job["status"] = "CANCELLED"
            touch(job)
            add_reserved_pull(furnace, -D(job["reserved_melt_tons"]))
            furnace["updated_at"] = db.clock
    touch(campaign)


# --------------------------------------------------------------------------- #
# pack lot helpers
# --------------------------------------------------------------------------- #
def lot_inspection_results(pack_lot_id):
    return ordered([r for r in db.inspection_results.values() if r["pack_lot_id"] == pack_lot_id])


def aging_days_for_design(design):
    days = calc.BASE_AGING_DAYS
    if D(design["min_wall_thickness_mm"]) < calc.THIN_WALL_MM:
        days += calc.THIN_WALL_AGING_DAYS
    for program in db.programs.values():
        if program["baseline_design_id"] == design["id"] and program["status"] == "ADOPTED":
            days += calc.ADOPTED_PROGRAM_AGING_DAYS
            break
    return days


def recompute_lot_inspection_totals(lot):
    results = lot_inspection_results(lot["id"])
    reject_units = sum(int(r["rejected_units"]) for r in results)
    major = sum(int(r["rejected_units"]) for r in results if r["defect_class"] == "MAJOR")
    minor = sum(int(r["rejected_units"]) for r in results if r["defect_class"] == "MINOR")
    lot["reject_units"] = reject_units
    lot["net_packed_units"] = int(lot["packed_units"]) - reject_units
    lot["major_ppm"] = calc.ppm(major, lot["packed_units"])
    lot["minor_ppm"] = calc.ppm(minor, lot["packed_units"])
    if lot["logistics_status"] == "PALLETIZED":
        lot["pallet_count"] = calc.ceil_div(
            lot["net_packed_units"], calc.UNITS_PER_PALLET[lot["palletization_standard"]]
        )


def attributed_transition_tons(job):
    """PRD 3.6: the first job to run after a completed transition carries its cost."""
    lookback = timedelta(days=calc.TRANSITION_LOOKBACK_DAYS)
    candidates = [
        cc
        for cc in db.color_changes.values()
        if cc["furnace_id"] == job["furnace_id"]
        and cc["status"] == "COMPLETED"
        and cc["window_end_at"] <= job["window_start_at"]
        and (job["window_start_at"] - cc["window_end_at"]) <= lookback
    ]
    if not candidates:
        return ZERO
    candidate = sorted(
        candidates, key=lambda cc: (cc["window_end_at"], cc["created_at"], cc["_seq"])
    )[-1]
    # ... but tie-break on created_at ASC among equal window_end_at values.
    best_end = candidate["window_end_at"]
    tied = [cc for cc in candidates if cc["window_end_at"] == best_end]
    candidate = sorted(tied, key=lambda cc: (cc["created_at"], cc["_seq"]))[0]

    eligible = [
        j
        for j in campaign_jobs(job["campaign_id"])
        if j["window_start_at"] >= candidate["window_end_at"]
    ]
    if not eligible:
        return ZERO
    earliest = sorted(
        eligible, key=lambda j: (j["window_start_at"], j["created_at"], j["_seq"])
    )[0]
    if earliest["id"] != job["id"]:
        return ZERO
    return D(candidate["transition_loss_tons"])


def lot_tons(lot, units_field):
    return calc.tons_from_units(lot[units_field], lot["unit_weight_g"])


def compute_final_yield(lot):
    job = db.production_jobs.get(lot["production_job_id"])
    net_tons = lot_tons(lot, "net_packed_units")
    transition = attributed_transition_tons(job) if job else ZERO
    reserved = job["reserved_melt_tons"] if job else ZERO
    return calc.final_yield_pct(net_tons, reserved, transition), transition


# --------------------------------------------------------------------------- #
# customer standing (PRD 3.9)
# --------------------------------------------------------------------------- #
def recompute_customer_standing(customer):
    credited = [
        c
        for c in db.complaints.values()
        if c["customer_id"] == customer["id"] and c["status"] == "CREDIT_ISSUED"
    ]
    credited = ordered(credited)
    customer["weighted_breakage_ppm"] = calc.weighted_breakage_ppm(
        [(c["breakage_ppm"], c["affected_units"]) for c in credited]
    )
    customer["quality_standing"] = calc.quality_standing(
        customer["weighted_breakage_ppm"], customer["complaint_ppm_threshold"]
    )
    return customer["quality_standing"]


def suspend_customer_programs(customer_id):
    design_ids = {
        d["id"] for d in db.bottle_designs.values() if d["customer_id"] == customer_id
    }
    for program in ordered(list(db.programs.values())):
        if program["baseline_design_id"] in design_ids and program["status"] in ("PILOT", "ADOPTED"):
            program["status"] = "SUSPENDED"
            touch(program)


# --------------------------------------------------------------------------- #
# design risk helper
# --------------------------------------------------------------------------- #
def design_risk_index(design, weight_override=None):
    customer = db.customers[design["customer_id"]]
    weight = design["nominal_weight_g"] if weight_override is None else weight_override
    return calc.breakage_risk_index(
        weight,
        design["capacity_ml"],
        design["min_wall_thickness_mm"],
        design["target_line_speed_bpm"],
        customer["quality_standing"],
    )


def new_record(versioned=True):
    return base_record(versioned=versioned)
