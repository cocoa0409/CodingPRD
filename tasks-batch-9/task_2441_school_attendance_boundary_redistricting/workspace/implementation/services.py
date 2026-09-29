"""Store-dependent business logic: projection execution, scenario scoring, the
seat pool and the eligibility waterfall wiring."""

from decimal import Decimal

import calc
from core import (
    active_schools_of_study,
    adjacencies_of_study,
    areas_of_study,
    assignments_of_scenario,
    compute_effective_capacity,
    db,
    dec,
    developments_of_area,
    round_half_up,
    rules_of_adoption,
    sort_key,
    transfers_of_adoption,
)


# --------------------------------------------------------------------------
# Adjacency graph
# --------------------------------------------------------------------------
def adjacency_map(study_id):
    graph = {}
    for row in adjacencies_of_study(study_id):
        graph.setdefault(row["area_id"], set()).add(row["neighbor_area_id"])
        graph.setdefault(row["neighbor_area_id"], set()).add(row["area_id"])
    return graph


# --------------------------------------------------------------------------
# Projection execution (PRD 3.3)
# --------------------------------------------------------------------------
def execute_projection(study, variant, horizon_years, epoch):
    # Horizon end: the epoch advanced by horizon_years * 365 days, no leap adjustment.
    horizon_end = epoch + _days(horizon_years * calc.DAYS_PER_YEAR)
    public = []
    internal = {}
    total = 0
    for area in areas_of_study(study["id"]):
        base = calc.base_students(area["resident_student_count"], horizon_years)
        contribs = []
        dev_total = Decimal("0.00")
        for dev in calc.admitted_developments(developments_of_area(area["id"]), variant):
            contribution = calc.development_contribution(
                dev, variant, horizon_end, dev["_first_occupancy_dt"]
            )
            contribs.append((dev["unit_type"], contribution))
            dev_total += contribution
        projected = int(round_half_up(dec(base) + dev_total, 0))
        public.append({
            "area_id": area["id"],
            "base_students": base,
            "development_students": float(dev_total),
            "projected_students": projected,
        })
        internal[area["id"]] = {
            "base": dec(base),
            "dev": dev_total,
            "proj": projected,
            "contribs": contribs,
        }
        total += projected
    return public, internal, total, horizon_end


def _days(count):
    from datetime import timedelta
    return timedelta(days=int(count))


# --------------------------------------------------------------------------
# Scenario scoring (PRD 3.5)
# --------------------------------------------------------------------------
def score_scenario(scenario):
    study = db.studies[scenario["study_id"]]
    run = db.runs.get(scenario["projection_run_id"])
    projections = (run or {}).get("_proj", {})
    live = assignments_of_scenario(scenario["id"], live_only=True)
    active = active_schools_of_study(study["id"])
    areas = {a["id"]: a for a in areas_of_study(study["id"])}

    total_assigned = sum(a["projected_students"] for a in live)

    # --- contiguity ---
    graph = adjacency_map(study["id"])
    noncontiguous = []
    for school in active:
        member_ids = []
        for row in live:
            if row["assigned_school_id"] == school["id"] and row["area_id"] not in member_ids:
                member_ids.append(row["area_id"])
        member_ids.sort(key=lambda aid: sort_key(areas[aid]) if aid in areas else (aid, 0))
        if not calc.is_contiguous(member_ids, graph):
            noncontiguous.append(school["id"])
    contiguity_ok = not noncontiguous

    # --- capacity utilization ---
    placements = scenario.get("program_placements") or []
    per_school = []
    critical_school_ids = []
    max_util = Decimal("0.00")
    for school in active:
        load = sum(a["projected_students"] for a in live if a["assigned_school_id"] == school["id"])
        load += sum(int(p["seats"]) for p in placements if p["school_id"] == school["id"])
        capacity = compute_effective_capacity(school, study)
        util = calc.utilization_pct(load, capacity)
        if util is None:
            util = Decimal("0.00")
        band = calc.utilization_band(util, study["capacity_target_low_pct"], study["capacity_target_high_pct"])
        per_school.append({
            "school_id": school["id"],
            "utilization_pct": float(util),
            "band": band,
        })
        if util >= calc.CRITICAL_UTILIZATION_PCT:
            critical_school_ids.append(school["id"])
        if util > max_util:
            max_util = util
    if not active:
        max_util = Decimal("0.00")

    # --- transportation and walkability ---
    walking = 0
    cost_accumulator = Decimal(0)
    for row in live:
        area = areas.get(row["area_id"])
        school = db.schools.get(row["assigned_school_id"])
        if area is None or school is None:
            continue
        option = None
        for entry in area["travel_options"]:
            if entry["school_id"] == school["id"]:
                option = entry
                break
        head = row["projected_students"]
        if option is not None and calc.walk_eligible(option, school["level"]):
            walking += head
            riders = 0
        else:
            riders = head
        bus_minutes = option["bus_minutes"] if option is not None else 0
        cost_accumulator += calc.assignment_transport_cost(riders, bus_minutes)
    transport_cost = round_half_up(cost_accumulator, 2)
    if total_assigned:
        walk_pct = round_half_up(dec(100) * dec(walking) / dec(total_assigned), 2)
    else:
        walk_pct = Decimal("0.00")

    # --- socioeconomic impact ---
    variant = scenario["impact_variant"]
    tallies = {s["id"]: [Decimal(0), Decimal(0)] for s in active}
    for row in live:
        target = row["assigned_school_id"]
        if target not in tallies:
            continue
        area = areas.get(row["area_id"])
        if area is None:
            continue
        if variant == "RESIDENT_BASED":
            frl_part = dec(area["frl_student_count"])
            nonfrl_part = dec(area["resident_student_count"]) - frl_part
        else:
            entry = projections.get(row["area_id"])
            if entry is None:
                frl_part = Decimal("0.00")
                nonfrl_part = Decimal("0.00")
            else:
                resident = dec(area["resident_student_count"])
                resident_rate = (dec(area["frl_student_count"]) / resident) if resident != 0 else Decimal(0)
                dev_students = entry["dev"]
                if dev_students != 0:
                    weighted = Decimal(0)
                    for unit_type, contribution in entry["contribs"]:
                        weighted += contribution * calc.DEVELOPMENT_FRL_RATE[unit_type]
                    dev_rate = weighted / dev_students
                else:
                    dev_rate = Decimal(0)
                frl_part = round_half_up(entry["base"] * resident_rate + dev_students * dev_rate, 2)
                nonfrl_part = round_half_up(dec(entry["proj"]) - frl_part, 2)
        tallies[target][0] += frl_part
        tallies[target][1] += nonfrl_part

    frl_total = sum((t[0] for t in tallies.values()), Decimal(0))
    nonfrl_total = sum((t[1] for t in tallies.values()), Decimal(0))
    ordered_tallies = [tuple(tallies[s["id"]]) for s in active]
    index = calc.dissimilarity_index(ordered_tallies, frl_total, nonfrl_total)

    reassigned = 0
    for row in live:
        area = areas.get(row["area_id"])
        if area is not None and row["assigned_school_id"] != area["current_school_id"]:
            reassigned += row["projected_students"]
    if total_assigned:
        reassigned_pct = round_half_up(dec(100) * dec(reassigned) / dec(total_assigned), 2)
    else:
        reassigned_pct = Decimal("0.00")

    return {
        "contiguity_ok": contiguity_ok,
        "noncontiguous_school_ids": noncontiguous,
        "total_assigned_students": total_assigned,
        "max_utilization_pct": float(max_util),
        "walk_eligible_pct": float(walk_pct),
        "transport_cost_annual_usd": float(transport_cost),
        "students_reassigned_count": reassigned,
        "students_reassigned_pct": float(reassigned_pct),
        "frl_dissimilarity_index": float(index),
        "critical_school_ids": critical_school_ids,
        "per_school": per_school,
        "_max_util": max_util,
    }


SCORE_FIELDS = (
    "contiguity_ok",
    "noncontiguous_school_ids",
    "total_assigned_students",
    "max_utilization_pct",
    "walk_eligible_pct",
    "transport_cost_annual_usd",
    "students_reassigned_count",
    "students_reassigned_pct",
    "frl_dissimilarity_index",
)


# --------------------------------------------------------------------------
# Seat pool (PRD 3.8)
# --------------------------------------------------------------------------
def school_seat_pool(adoption, school, exclude_transfer_id=None):
    scenario = db.scenarios[adoption["scenario_id"]]
    study = db.studies[adoption["study_id"]]
    post_boundary = 0
    for row in assignments_of_scenario(scenario["id"], live_only=True):
        if row["assigned_school_id"] == school["id"]:
            post_boundary += row["projected_students"]
    inbound = 0
    outbound = 0
    for request in transfers_of_adoption(adoption["id"]):
        if exclude_transfer_id is not None and request["id"] == exclude_transfer_id:
            continue
        if request["status"] != "APPROVED" or not request["consumes_seat_pool"]:
            continue
        if request["requested_school_id"] == school["id"]:
            inbound += 1
        if request["origin_school_id"] == school["id"]:
            outbound += 1
    head_count = post_boundary + inbound - outbound
    capacity = compute_effective_capacity(school, study)
    return calc.seat_pool(capacity, adoption["transfer_cap_pct"], head_count)


# --------------------------------------------------------------------------
# Eligibility waterfall (PRD 3.8)
# --------------------------------------------------------------------------
def sibling_link_usable(request):
    sibling_id = request.get("sibling_transfer_id")
    if not sibling_id:
        return False
    sibling = db.transfers.get(sibling_id)
    if sibling is None or sibling["id"] == request["id"]:
        return False
    return (
        sibling["adoption_id"] == request["adoption_id"]
        and sibling["status"] == "APPROVED"
        and sibling["requested_school_id"] == request["requested_school_id"]
    )


def resolve_request_eligibility(request, adoption):
    rules = rules_of_adoption(adoption["id"])
    return calc.resolve_eligibility(
        rules,
        request["student_grade"],
        request["reason"],
        sibling_link_usable(request),
        adoption["effective_school_year"],
    )
