"""Every calculation of the scaffold, plus the recompute appliers (PRD 2.9, 3.x)."""

from datetime import timedelta

import db
from constants import (
    ACTIVE_FEED_STATUSES,
    AIRFLOW_BTU_COEFF,
    BTU_PER_KW,
    CHARGEABLE_RACK_STATUSES,
    CONTINUOUS_LOAD_FACTOR,
    COUNTING_LEAKAGE_STATUSES,
    CRITICAL_MARGIN_KW,
    CUSTODY_FITOUT_STATUSES,
    CUSTODY_OPS_STATUSES,
    DIVERSITY_FACTOR,
    HEAT_RACK_STATUSES,
    LOADBANK_MIN_RETURN_DELTA_T_F,
    LOADBANK_TOLERANCE,
    MOP_SETTLE_BUFFER_MIN,
    OPEN_MOP_STATUSES,
    POWER_FACTOR,
    RACK_OVERHEAD_FACTOR,
    RELEASED_SCOPE_RACK_STATUSES,
    RESERVE_TIER_1_KW,
    RESERVE_TIER_1_MAX_KW,
    RESERVE_TIER_2_KW,
    RESERVE_TIER_2_MAX_KW,
    RESERVE_TIER_3_KW,
    SQRT3,
    TOPOLOGY_FACTOR,
)
from util import D, q

ZERO = D(0)


def _sum(values):
    total = ZERO
    for value in values:
        total += value
    return total


# =========================================================================
# calculation: busway_usable_kw
# =========================================================================

def busway_raw_unrounded(busway):
    return (
        D(busway["rated_amps"])
        * D(busway["voltage_v"])
        * SQRT3
        * POWER_FACTOR
        / D(1000)
    )


def variant_for_hall(hall):
    """DESIGN in PLANNING/FIT_OUT, COMMISSIONED in COMMISSIONING/LIVE."""
    return "DESIGN" if hall["status"] in ("PLANNING", "FIT_OUT") else "COMMISSIONED"


def busway_usable_kw(busway, variant):
    pdu = db.get("pdus", busway["pdu_id"])
    topo = TOPOLOGY_FACTOR[busway["redundancy_topology"]]
    pdu_cap = q(D(pdu["rated_kw"]) * CONTINUOUS_LOAD_FACTOR, 3)
    trunk = busway_raw_unrounded(busway) * CONTINUOUS_LOAD_FACTOR * topo
    base = trunk if trunk < pdu_cap else pdu_cap
    if variant == "COMMISSIONED":
        return q(base * D(pdu["measured_derate_factor"]), 2)
    return q(base, 2)


def apply_busway_ceiling(busway, variant=None):
    if variant is None:
        variant = busway.get("usable_variant")
    db.assign(
        busway,
        {
            "raw_kw": q(busway_raw_unrounded(busway), 3),
            "usable_variant": variant,
            "usable_kw": busway_usable_kw(busway, variant),
        },
    )
    return busway


def breaker_continuous_kw(breaker_amps, voltage_v):
    raw = D(breaker_amps) * D(voltage_v) * SQRT3 * POWER_FACTOR / D(1000)
    return q(raw * CONTINUOUS_LOAD_FACTOR, 2)


# =========================================================================
# feed aggregates
# =========================================================================

def apply_busway_load(busway):
    feeds = db.where("feeds", busway_id=busway["id"], status=ACTIVE_FEED_STATUSES)
    db.assign(
        busway,
        {
            "committed_kw": q(_sum(D(f["allocated_kw"]) for f in feeds), 3),
            "feed_count": len(feeds),
        },
    )
    return busway


def apply_rack_load(rack):
    feeds = db.where("feeds", rack_id=rack["id"])
    active = [f for f in feeds if f["status"] in ACTIVE_FEED_STATUSES]
    db.assign(
        rack,
        {
            "connected_kw": q(_sum(D(f["allocated_kw"]) for f in active), 3),
            "energized_feed_count": len(
                [f for f in feeds if f["status"] == "ENERGIZED"]
            ),
        },
    )
    return rack


# =========================================================================
# calculation: hall_power_ledger
# =========================================================================

def hall_active_feeds(hall):
    rack_ids = set(r["id"] for r in db.where("racks", hall_id=hall["id"]))
    return [
        f
        for f in db.all_rows("feeds")
        if f["rack_id"] in rack_ids and f["status"] in ACTIVE_FEED_STATUSES
    ]


def reserve_tier_for(committed_kw):
    if committed_kw <= RESERVE_TIER_1_MAX_KW:
        return RESERVE_TIER_1_KW
    if committed_kw <= RESERVE_TIER_2_MAX_KW:
        return RESERVE_TIER_2_KW
    return RESERVE_TIER_3_KW


def compute_ledger(hall, extra_kw=None):
    total = _sum(D(f["allocated_kw"]) for f in hall_active_feeds(hall))
    if extra_kw is not None:
        total += D(extra_kw)
    committed = q(total, 2)
    reserve = reserve_tier_for(committed)
    spare = q(D(hall["design_kw_capacity"]) - committed - reserve, 2)
    return committed, reserve, spare


def apply_ledger(hall):
    committed, reserve, spare = compute_ledger(hall)
    db.assign(
        hall,
        {
            "committed_kw": committed,
            "commissioning_reserve_kw": reserve,
            "spare_kw": spare,
        },
    )
    return hall


# =========================================================================
# calculation: rack_chargeable_rollup
# =========================================================================

def rack_chargeable(rack):
    return q(D(rack["design_kw"]) * RACK_OVERHEAD_FACTOR, 2)


def apply_chargeable(hall):
    racks = [
        r
        for r in db.where("racks", hall_id=hall["id"])
        if r["status"] in CHARGEABLE_RACK_STATUSES
    ]
    db.assign(hall, {"chargeable_kw": q(_sum(D(r["chargeable_kw"]) for r in racks), 2)})
    return hall


# =========================================================================
# calculation: rack_custody_partition
# =========================================================================

def apply_custody(hall):
    racks = db.where("racks", hall_id=hall["id"])
    db.assign(
        hall,
        {
            "rack_total_count": len(racks),
            "custody_ops_count": len(
                [r for r in racks if r["status"] in CUSTODY_OPS_STATUSES]
            ),
            "custody_fitout_count": len(
                [r for r in racks if r["status"] in CUSTODY_FITOUT_STATUSES]
            ),
            "at_risk_rack_count": len([r for r in racks if r["status"] == "AT_RISK"]),
        },
    )
    return hall


# =========================================================================
# tenant entitlement
# =========================================================================

def compute_tenant_allocated(tenant, extra_rack=None):
    racks = [
        r for r in db.where("racks", tenant_id=tenant["id"]) if r["status"] != "PLANNED"
    ]
    total = _sum(D(r["design_kw"]) for r in racks)
    if extra_rack is not None:
        total += D(extra_rack["design_kw"])
    return q(total, 2)


def apply_tenant_allocated(tenant):
    if tenant is None:
        return None
    db.assign(tenant, {"allocated_kw": compute_tenant_allocated(tenant)})
    return tenant


def apply_tenants_of_hall(hall):
    seen = set()
    for rack in db.where("racks", hall_id=hall["id"]):
        tenant_id = rack.get("tenant_id")
        if tenant_id and tenant_id not in seen:
            seen.add(tenant_id)
            apply_tenant_allocated(db.get("tenants", tenant_id))


# =========================================================================
# calculation: hall_cooling_model
# =========================================================================

def worst_leakage_pct(hall):
    zones = [
        z
        for z in db.where("zones", hall_id=hall["id"])
        if z["leakage_status"] in COUNTING_LEAKAGE_STATUSES
        and z["measured_leakage_pct"] is not None
    ]
    if not zones:
        return q(0, 2)
    worst = None
    for zone in zones:
        value = D(zone["measured_leakage_pct"])
        if worst is None or value > worst:
            worst = value
    return q(worst, 2)


def unit_airflow_capacity(unit, leak_fraction):
    if unit.get("measured_airflow_cfm") is None:
        return q(0, 5)
    return q(
        D(unit["measured_airflow_cfm"])
        * (D(1) - leak_fraction)
        * D(unit["supply_delta_t_f"])
        * AIRFLOW_BTU_COEFF
        / BTU_PER_KW,
        5,
    )


def compute_cooling(hall, extra_rack_ids=()):
    racks = db.where("racks", hall_id=hall["id"])
    demand = _sum(D(r["design_kw"]) for r in racks if r["status"] in HEAT_RACK_STATUSES)
    for rack_id in extra_rack_ids:
        candidate = db.get("racks", rack_id)
        if candidate is not None:
            demand += D(candidate["design_kw"])
    thermal_load = q(demand * DIVERSITY_FACTOR, 2)

    worst = worst_leakage_pct(hall)
    leak_fraction = worst / D(100)

    units = db.where("cooling_units", hall_id=hall["id"])
    per_unit = {}
    for unit in units:
        per_unit[unit["id"]] = unit_airflow_capacity(unit, leak_fraction)
    duty = [u for u in units if u["status"] == "IN_SERVICE"]
    hold_back = hall["cooling_redundancy"] == "N_PLUS_1" and len(duty) > 0

    gross_nameplate = _sum(D(u["rated_sensible_kw"]) for u in duty)
    withhold_nameplate = ZERO
    if hold_back:
        withhold_nameplate = max(D(u["rated_sensible_kw"]) for u in duty)
    nameplate = q(gross_nameplate - withhold_nameplate, 2)

    gross_airflow = _sum(per_unit[u["id"]] for u in duty)
    withhold_airflow = ZERO
    if hold_back:
        withhold_airflow = max(per_unit[u["id"]] for u in duty)
    airflow = q(gross_airflow - withhold_airflow, 2)

    capacity = nameplate if nameplate < airflow else airflow
    margin = q(capacity - thermal_load, 2)
    if margin >= ZERO:
        posture = "NOMINAL"
    elif margin >= CRITICAL_MARGIN_KW:
        posture = "CONSTRAINED"
    else:
        posture = "CRITICAL"

    return {
        "thermal_load_kw": thermal_load,
        "worst_leakage_pct": worst,
        "cooling_capacity_nameplate_kw": nameplate,
        "cooling_capacity_airflow_kw": airflow,
        "cooling_capacity_kw": capacity,
        "cooling_margin_kw": margin,
        "thermal_posture": posture,
        "per_unit": per_unit,
    }


def apply_cooling(hall):
    result = compute_cooling(hall)
    for unit in db.where("cooling_units", hall_id=hall["id"]):
        db.assign(unit, {"airflow_capacity_kw": result["per_unit"][unit["id"]]})
    db.assign(
        hall,
        {
            field: result[field]
            for field in (
                "thermal_load_kw",
                "cooling_capacity_nameplate_kw",
                "cooling_capacity_airflow_kw",
                "cooling_capacity_kw",
                "cooling_margin_kw",
                "thermal_posture",
            )
        },
    )
    return result


# =========================================================================
# calculation: package_state_projection
# =========================================================================

def project_package(package):
    """Never written directly -- always re-derived, in this fixed branch order."""
    if package.get("superseded_by_package_id"):
        state = "SUPERSEDED"
    elif package["witness_status"] == "BLOCKED":
        state = "BLOCKED"
    elif package["witness_status"] == "REJECTED":
        state = "FAILED"
    elif package["script_status"] == "EXECUTED" and package["witness_status"] == "WITNESSED":
        state = "CERTIFIED"
    elif package["script_status"] in ("SCRIPT_APPROVED", "EXECUTED"):
        state = "IN_EXECUTION"
    else:
        state = "DRAFT"
    package["package_state"] = state
    return state


def apply_package_thermal(hall):
    """The third link of the containment-to-commissioning cascade, and its reverse."""
    packages = db.where("packages", hall_id=hall["id"])
    if hall["thermal_posture"] != "NOMINAL":
        for package in packages:
            if package["level"] in ("L4", "L5") and package["witness_status"] == "PENDING":
                package["witness_status"] = "BLOCKED"
                project_package(package)
                db.touch(package)  # a real state change: always a version bump
    else:
        for package in packages:
            if package["witness_status"] == "BLOCKED":
                package["witness_status"] = "PENDING"
                project_package(package)
                db.touch(package)


# =========================================================================
# calculation: hall_release_posture
# =========================================================================

def apply_release_posture(hall):
    mops = db.where("mops", hall_id=hall["id"])
    open_count = len([m for m in mops if m["status"] in OPEN_MOP_STATUSES])
    if any(m["status"] == "IN_EXECUTION" for m in mops):
        posture = "LOCKED"
    elif hall["at_risk_rack_count"] > 0 or hall["thermal_posture"] != "NOMINAL":
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    db.assign(hall, {"open_mop_count": open_count, "release_posture": posture})
    return posture


def thermal_chain(hall):
    """Cooling model -> package block/unblock -> release posture."""
    result = apply_cooling(hall)
    apply_package_thermal(hall)
    apply_release_posture(hall)
    return result


def rack_chain(hall):
    """Every rack status change re-derives the custody partition and everything downstream."""
    apply_custody(hall)
    apply_chargeable(hall)
    return thermal_chain(hall)


# =========================================================================
# hall phase evaluation: COMMISSIONING -> LIVE (system only)
# =========================================================================

def evaluate_hall_live(hall):
    if hall["status"] != "COMMISSIONING":
        return False
    packages = [
        p
        for p in db.where("packages", hall_id=hall["id"])
        if p["package_state"] != "SUPERSEDED"
    ]
    if not packages:
        return False
    if any(p["package_state"] != "CERTIFIED" for p in packages):
        return False
    levels = set(p["level"] for p in packages)
    if "L4" not in levels or "L5" not in levels:
        return False
    hall["status"] = "LIVE"
    db.touch(hall)
    apply_release_posture(hall)
    return True


# =========================================================================
# calculation: cage_security_coverage
# =========================================================================

def compute_cage_coverage(cage):
    active = db.where("devices", cage_id=cage["id"], status="ACTIVE")
    cameras = [d for d in active if d["device_type"] == "CAMERA"]
    if not cameras:
        pct = q(0, 2)
    else:
        covered = _sum(D(d["covered_length_m"]) for d in cameras)
        raw = covered / D(cage["perimeter_length_m"]) * D(100)
        capped = raw if raw < D("100.00") else D("100.00")
        pct = q(capped, 2)
    zones = set()
    for device in active:
        if device["device_type"] == "CARD_READER" and device.get("reader_zone_label") is not None:
            zones.add(device["reader_zone_label"])
    return pct, len(zones)


def cage_floors_met(cage):
    return (
        D(cage["camera_coverage_pct"]) >= D(cage["required_camera_coverage_pct"])
        and cage["active_reader_zone_count"] >= cage["required_reader_zone_count"]
    )


def apply_cage_coverage(cage):
    pct, zone_count = compute_cage_coverage(cage)
    db.assign(
        cage, {"camera_coverage_pct": pct, "active_reader_zone_count": zone_count}
    )
    if cage["operational_status"] == "FIT_OUT" and cage_floors_met(cage):
        db.assign(cage, {"operational_status": "SECURED"})
    return cage


# =========================================================================
# calculation: asset_tag_completion + the release packet figures
# =========================================================================

def cage_scope_racks(cage):
    return [
        r
        for r in db.where("racks", cage_id=cage["id"])
        if r["status"] in RELEASED_SCOPE_RACK_STATUSES
    ]


def compute_packet_figures(cage):
    racks = cage_scope_racks(cage)
    count = len(racks)
    released_kw = q(_sum(rack_chargeable(r) for r in racks), 2)
    tagged = len([r for r in racks if r.get("asset_tag") not in (None, "")])
    if count == 0:
        pct = q(0, 2)
    else:
        pct = q(D(tagged) / D(count) * D(100), 2)
    return count, released_kw, pct


def apply_packet_figures(packet):
    cage = db.get("cages", packet["cage_id"])
    count, released_kw, pct = compute_packet_figures(cage)
    db.assign(
        packet,
        {
            "released_kw": released_kw,
            "rack_in_scope_count": count,
            "asset_tag_completion_pct": pct,
        },
    )
    return packet


# =========================================================================
# calculation: load_bank_result
# =========================================================================

def grade_load_bank(test, measured_kw, measured_delta_t):
    kw_floor = q(D(test["target_kw"]) * LOADBANK_TOLERANCE, 2)
    kw_ok = D(measured_kw) >= kw_floor
    delta_ok = D(measured_delta_t) >= LOADBANK_MIN_RETURN_DELTA_T_F
    return "PASS" if (kw_ok and delta_ok) else "FAIL"


def apply_package_measured_load(package):
    completed = db.where("load_bank_tests", package_id=package["id"], status="COMPLETED")
    best = None
    for test in completed:
        if test["measured_kw"] is None:
            continue
        value = D(test["measured_kw"])
        if best is None or value > best:
            best = value
    db.assign(package, {"measured_load_kw": best})
    return package


# =========================================================================
# calculation: mop_approval_requirement
# =========================================================================

def required_approvals_for(risk_class):
    return 2 if risk_class == "HIGH" else 1


def approvals_of(mop):
    return db.ordered(db.where("approvals", mop_id=mop["id"]))


def round_start_seq(mop):
    revisions = [a for a in approvals_of(mop) if a["decision"] == "REQUEST_REVISION"]
    if not revisions:
        return 0
    return revisions[-1]["_seq"]


def round_approvals(mop):
    start = round_start_seq(mop)
    return [
        a
        for a in approvals_of(mop)
        if a["decision"] == "APPROVE" and a["_seq"] > start
    ]


# =========================================================================
# calculation: mop_window_collision_set  (half-open, symmetric 60 min buffer)
# =========================================================================

def mop_window_collision(mop, start, end):
    buffer = timedelta(minutes=MOP_SETTLE_BUFFER_MIN)
    peers = [
        m
        for m in db.where(
            "mops",
            target_resource_id=mop["target_resource_id"],
            status=OPEN_MOP_STATUSES,
        )
        if m["id"] != mop["id"]
    ]
    for other in db.ordered(peers):
        if start < other["window_end"] + buffer and end + buffer > other["window_start"]:
            return other
    return None


# =========================================================================
# calculation: load_bank_window_occupancy  (closed windows, pooled reserve)
# =========================================================================

def load_bank_peers(hall, start, end, exclude_id=None):
    peers = []
    for test in db.all_rows("load_bank_tests"):
        if test["id"] == exclude_id:
            continue
        if test["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        package = db.get("packages", test["package_id"])
        if package is None or package["hall_id"] != hall["id"]:
            continue
        if start <= test["window_end"] and end >= test["window_start"]:
            peers.append(test)
    return db.ordered(peers)


def load_bank_reserve_demand(peers, target_kw):
    return q(_sum(D(t["target_kw"]) for t in peers) + D(target_kw), 2)
