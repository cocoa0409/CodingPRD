"""Derived counters, cascade helpers and shared lookups (PRD section 2.8)."""

import calc
import store


# ---------------------------------------------------------------------------
# Ordering helper: created_at ASC with a monotonic insertion tiebreak
# ---------------------------------------------------------------------------
def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def project_of_cabinet(cab):
    return store.display_projects.get(cab["project_id"])


def model_of_project(project):
    return store.display_models.get(project["display_model_id"])


def model_of_cabinet(cab):
    project = project_of_cabinet(cab)
    if project is None:
        return None
    return model_of_project(project)


def project_cabinets(project_id):
    return by_created([c for c in store.cabinets.values() if c["project_id"] == project_id])


def installed_modules(cabinet_id):
    return by_created([m for m in store.modules.values()
                       if m["cabinet_id"] == cabinet_id and m["module_state"] == "INSTALLED"])


def latest_terminal_run(cabinet_id):
    rows = by_created([r for r in store.burn_in_runs.values()
                       if r["cabinet_id"] == cabinet_id
                       and r["run_state"] in ("PASSED", "FAILED")])
    return rows[-1] if rows else None


# ---------------------------------------------------------------------------
# Derived counters
# ---------------------------------------------------------------------------
def chamber_derived(chamber):
    runs = [r for r in store.burn_in_runs.values()
            if r["burn_in_chamber_id"] == chamber["id"] and r["run_state"] == "SCHEDULED"]
    return {
        "reserved_slot_total": sum(r["slots_required"] for r in runs),
        "scheduled_run_count": len(runs),
    }


def crew_derived(crew):
    visits = [v for v in store.commissioning_visits.values()
              if v["commissioning_crew_id"] == crew["id"]
              and v["visit_state"] in ("SCHEDULED", "ON_SITE", "CALIBRATED")]
    return {"scheduled_visit_count": len(visits)}


def contract_derived(contract):
    count = len([m for m in store.modules.values()
                 if m["reserved_service_contract_id"] == contract["id"]
                 and m["module_state"] == "CALIBRATED"])
    return {"spare_reserved_count": count}


def project_counters(project):
    cabs = [c for c in store.cabinets.values() if c["project_id"] == project["id"]]
    qa_passed = len([c for c in cabs if c["cabinet_state"] in ("QA_PASSED", "MOUNTED")])
    mounted = len([c for c in cabs if c["cabinet_state"] == "MOUNTED"])
    quarantined = len([c for c in cabs if c["cabinet_state"] == "QUARANTINED"])
    return qa_passed, mounted, quarantined


def project_derived(project):
    qa_passed, mounted, quarantined = project_counters(project)
    suspended = any(c["project_id"] == project["id"] and c["contract_state"] == "SUSPENDED"
                    for c in store.service_contracts.values())
    return {
        "qa_passed_cabinet_count": qa_passed,
        "mounted_cabinet_count": mounted,
        "quarantined_cabinet_count": quarantined,
        "service_posture": "AT_RISK" if suspended else "NORMAL",
    }


def cabinet_derived(cab):
    model = model_of_cabinet(cab)
    mods = installed_modules(cab["id"])
    total_dead = sum((m["dead_pixel_count"] or 0) for m in mods)
    run = latest_terminal_run(cab["id"])
    if run is not None and run["new_dead_pixel_count"] is not None:
        total_dead += run["new_dead_pixel_count"]
    ppm = None
    if model is not None and model["cabinet_pixel_count"]:
        ppm = calc.dead_pixel_ppm(total_dead, model["cabinet_pixel_count"])
    samples = [(m["measured_brightness_nits"], m["measured_color_x"], m["measured_color_y"])
               for m in mods
               if m["measured_brightness_nits"] is not None
               and m["measured_color_x"] is not None
               and m["measured_color_y"] is not None]
    return {
        "installed_module_count": len(mods),
        "occupied_slot_indexes": sorted(m["slot_index"] for m in mods
                                        if m["slot_index"] is not None),
        "total_dead_pixel_count": total_dead,
        "dead_pixel_ppm": ppm,
        "as_built_uniformity_score": calc.uniformity_score(samples),
    }


def cabinet_dead_pixel_ppm_with(cab, extra_dead):
    """Cabinet dead-pixel ppm as it would read with `extra_dead` new dead pixels."""
    model = model_of_cabinet(cab)
    mods = installed_modules(cab["id"])
    total = sum((m["dead_pixel_count"] or 0) for m in mods) + extra_dead
    if model is None or not model["cabinet_pixel_count"]:
        return None, total
    return calc.dead_pixel_ppm(total, model["cabinet_pixel_count"]), total


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def block_project(project):
    """Burn-in failure cascade hops 3 and 4."""
    if project["production_state"] == "BLOCKED":
        return
    project["production_state"] = "BLOCKED"
    store.touch(project)
    for visit in by_created([v for v in store.commissioning_visits.values()
                             if v["project_id"] == project["id"]
                             and v["visit_state"] in ("SCHEDULED", "ON_SITE", "CALIBRATED")]):
        visit["visit_state"] = "ABORTED"
        visit["abort_reason"] = "PROJECT_BLOCKED"
        store.touch(visit)
        crew = store.commissioning_crews.get(visit["commissioning_crew_id"])
        if crew is not None:
            store.touch(crew)


def activate_contracts_for(project, signed_off_at):
    for contract in by_created([c for c in store.service_contracts.values()
                                if c["project_id"] == project["id"]
                                and c["contract_state"] == "PENDING"]):
        contract["contract_state"] = "ACTIVE"
        contract["warranty_start_at"] = signed_off_at
        store.touch(contract)


def contract_health(contract, already_touched, direction):
    """Re-derive ACTIVE/SUSPENDED after a spare-pool or SLA write.

    `direction` is the only flip the triggering write is allowed to make, and
    each downward trigger carries its own PRD condition:
    "up" for a spare reservation (SUSPENDED -> ACTIVE only, per PRD 3.8);
    "pool_down" for a release or a fulfilment drawdown, which suspends only
    when the pool has dropped below `spare_required_count` (PRD 3.8, 3.9);
    "sla_down" for a breached response, which suspends only when
    `sla_breach_count` has reached 2 (PRD 3.9). A reservation never suspends a
    contract and a release never revives one.
    """
    reserved = contract_derived(contract)["spare_reserved_count"]
    breaches = contract["sla_breach_count"]
    state = contract["contract_state"]
    new_state = state
    if direction == "pool_down" and state == "ACTIVE":
        if reserved < contract["spare_required_count"]:
            new_state = "SUSPENDED"
    elif direction == "sla_down" and state == "ACTIVE":
        if breaches >= calc.MAX_SLA_BREACHES:
            new_state = "SUSPENDED"
    elif direction == "up" and state == "SUSPENDED":
        if reserved >= contract["spare_required_count"] and breaches < calc.MAX_SLA_BREACHES:
            new_state = "ACTIVE"
    if new_state != state:
        contract["contract_state"] = new_state
        project = store.display_projects.get(contract["project_id"])
        if project is not None:
            store.touch(project)
    if not already_touched:
        store.touch(contract)
    return new_state
