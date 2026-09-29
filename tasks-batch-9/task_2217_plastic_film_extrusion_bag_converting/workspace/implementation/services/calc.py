"""Every derived quantity in the system (SCAFFOLD §1.3 / PRD §3)."""

import config as C
from num import D, ZERO, ceil_int_div, dsqrt, f, floor_div, floor_int, r
from services import refs
from store import store


# =====================================================================
# blend_composition_totals / blend_cost_and_density / blend_property_indices
# / regrind_cap_evaluation  — recomputed on every component append and on submit
# =====================================================================
def _resin(component):
    rid = component.get("resin_grade_id")
    if rid is None:
        return None
    return store.resin_grades.get(rid)


def recompute_recipe(recipe):
    product = store.products.get(recipe["product_id"])
    components = recipe["components"]

    # ---- composition totals (3 dp) ----------------------------------
    total = sum((D(c["weight_pct"]) for c in components), ZERO)
    regrind = sum(
        (D(c["weight_pct"]) for c in components if c["component_kind"] == "REGRIND"), ZERO
    )
    additive = sum(
        (D(c["weight_pct"]) for c in components if c["component_kind"] == "ADDITIVE"), ZERO
    )
    hdpe = ZERO
    family_totals = {}
    barrier = False
    for c in components:
        resin = _resin(c)
        if c["component_kind"] == "VIRGIN" and resin is not None:
            if resin["polymer_family"] == "HDPE":
                hdpe += D(c["weight_pct"])
            family_totals[resin["polymer_family"]] = family_totals.get(
                resin["polymer_family"], ZERO
            ) + D(c["weight_pct"])
        if c["component_kind"] in ("VIRGIN", "ADDITIVE") and resin is not None:
            if resin.get("is_barrier"):
                barrier = True

    dominant = None
    for family in sorted(family_totals):  # alphabetical ascending tie-break
        if dominant is None or family_totals[family] > family_totals[dominant]:
            dominant = family

    total_pct = r(total, 3)
    regrind_pct = r(regrind, 3)
    additive_pct = r(additive, 3)
    hdpe_pct = r(hdpe, 3)

    recipe["total_weight_pct"] = f(total_pct)
    recipe["regrind_pct"] = f(regrind_pct)
    recipe["additive_pct"] = f(additive_pct)
    recipe["hdpe_pct"] = f(hdpe_pct)
    recipe["dominant_polymer_family"] = dominant
    recipe["barrier_layer_present"] = barrier

    # ---- cost and density: round each line to 2 dp, then sum, then round
    cost_sum = ZERO
    dens_sum = ZERO
    for c in components:
        resin = _resin(c)
        if c["component_kind"] == "REGRIND" or resin is None:
            unit_cost = C.REGRIND_COST_PER_KG
            unit_dens = C.REGRIND_DENSITY
        else:
            unit_cost = D(resin["cost_per_kg"])
            unit_dens = D(resin["density_kg_m3"])
        share = D(c["weight_pct"]) / D(100)
        cost_sum += r(share * unit_cost, 2)
        dens_sum += r(share * unit_dens, 2)
    recipe["blend_cost_per_kg"] = f(r(cost_sum, 2))
    recipe["blended_density_kg_m3"] = f(r(dens_sum, 2))

    # ---- property indices -------------------------------------------
    dart_base = ZERO
    haze_sum = ZERO
    cof_sum = ZERO
    additive_components = 0
    for c in components:
        resin = _resin(c)
        share = D(c["weight_pct"]) / D(100)
        if c["component_kind"] == "REGRIND" or resin is None:
            dart_base += share * C.REGRIND_DART
            haze_sum += share * C.REGRIND_HAZE
            cof_sum += share * C.REGRIND_COF
        else:
            dart_base += share * D(resin["dart_impact_index"])
            haze_sum += share * D(resin["haze_index"])
            cof_sum += share * D(resin["cof_index"])
        if c["component_kind"] == "ADDITIVE":
            additive_components += 1

    if hdpe_pct <= C.HDPE_FREE_PCT:
        family_factor = D("1.000")
    else:
        family_factor = max(
            C.FAMILY_FACTOR_FLOOR,
            D("1.000") - C.HDPE_PENALTY_PER_PCT * (hdpe_pct - C.HDPE_FREE_PCT),
        )
    regrind_factor = max(
        C.REGRIND_FACTOR_FLOOR, D("1.000") - C.REGRIND_PENALTY_PER_PCT * regrind_pct
    )
    additive_boost = min(
        C.ADDITIVE_BOOST_CEILING,
        D("1.000") + C.ADDITIVE_BOOST_PER_COMPONENT * D(additive_components),
    )
    strength = dart_base * min(family_factor, regrind_factor) * additive_boost
    recipe["strength_index"] = f(r(strength, 2))
    recipe["clarity_index"] = f(r(max(D("0.00"), D(100) - C.HAZE_COEFF * haze_sum), 2))
    slip_raw = (C.COF_REFERENCE - cof_sum) / C.COF_REFERENCE * D(100)
    recipe["slip_index"] = f(r(min(D(100), max(ZERO, slip_raw)), 2))

    # ---- regrind cap evaluation (five pinned steps) -----------------
    virgin_pcr = ZERO
    for c in components:
        if c["component_kind"] != "VIRGIN":
            continue
        resin = _resin(c)
        if resin is None:
            continue
        virgin_pcr += D(c["weight_pct"]) / D(100) * D(resin["pcr_content_pct"])
    virgin_pcr_pct = r(virgin_pcr, 3)
    recipe["virgin_pcr_pct"] = f(virgin_pcr_pct)

    if product is None:
        base_cap = ZERO
        assumed_pcr = ZERO
        food_required = False
    else:
        food_required = bool(product["food_contact_required"])
        base_cap = D(
            product["max_regrind_pct_food"]
            if food_required
            else product["max_regrind_pct_nonfood"]
        )
        assumed_pcr = D(product["assumed_regrind_pcr_pct"])

    if virgin_pcr_pct >= C.PCR_BAND_HIGH_MIN:
        band = "HIGH"
    elif virgin_pcr_pct >= C.PCR_BAND_MID_MIN:
        band = "MID"
    else:
        band = "LOW"
    cap = r(max(ZERO, base_cap + C.CAP_DELTA[band]), 3)
    recipe["pcr_band"] = band
    recipe["regrind_cap_pct"] = f(cap)

    cap_satisfied = regrind_pct <= cap
    recipe["nominal_recycled_content_pct"] = f(
        r(virgin_pcr_pct + regrind_pct / D(100) * assumed_pcr, 3)
    )

    all_approved = True
    for c in components:
        if c["component_kind"] not in ("VIRGIN", "ADDITIVE"):
            continue
        resin = _resin(c)
        if resin is None or not resin.get("food_contact_approved"):
            all_approved = False
            break
    recipe["food_contact_eligible"] = (not food_required) or (all_approved and cap_satisfied)
    return recipe


def recipe_food_contact_resins_ok(recipe):
    for c in recipe["components"]:
        if c["component_kind"] not in ("VIRGIN", "ADDITIVE"):
            continue
        resin = _resin(c)
        if resin is None or not resin.get("food_contact_approved"):
            return False
    return True


def recompute_pinned_run_count(recipe):
    """Number of runs pinning this recipe in SCHEDULED / RUNNING / HELD."""
    count = 0
    for run in store.extrusion_runs.values():
        if run["blend_recipe_id"] == recipe["id"] and run["status"] in C.OCCUPYING_RUN_STATES:
            count += 1
    recipe["pinned_run_count"] = count
    return count


# =====================================================================
# gauge_capability
# =====================================================================
def recompute_gauge(run):
    product = refs.product_of_run(run)
    readings = run["gauge_readings"]
    n = len(readings)
    run["gauge_sample_count"] = n

    if n < C.MIN_GAUGE_SAMPLES:
        run["gauge_mean_micron"] = None
        run["gauge_sd_micron"] = None
        run["gauge_cv_pct"] = None
        run["gauge_capability_index"] = None
        run["gauge_capability_state"] = "INSUFFICIENT_DATA"
    else:
        thicknesses = [D(x["thickness_micron"]) for x in readings]
        mean = sum(thicknesses, ZERO) / D(n)
        variance = sum(((t - mean) ** 2 for t in thicknesses), ZERO) / D(n)
        sd = dsqrt(variance)
        target = D(product["target_gauge_micron"])
        tol = D(product["gauge_tolerance_pct"])
        usl = target * (D(1) + tol / D(100))
        lsl = target * (D(1) - tol / D(100))
        if sd == 0:
            cpk_raw = C.CPK_CEILING
        else:
            cpk_raw = min((usl - mean) / (D(3) * sd), (mean - lsl) / (D(3) * sd))
        index = r(min(C.CPK_CEILING, cpk_raw), 3)
        run["gauge_mean_micron"] = f(r(mean, 3))
        run["gauge_sd_micron"] = f(r(sd, 4))
        run["gauge_cv_pct"] = f(r(sd / mean * D(100), 3)) if mean != 0 else None
        run["gauge_capability_index"] = f(index)
        if index >= C.CPK_CAPABLE_MIN:
            run["gauge_capability_state"] = "CAPABLE"
        elif index >= C.CPK_MARGINAL_MIN:
            run["gauge_capability_state"] = "MARGINAL"
        else:
            run["gauge_capability_state"] = "INCAPABLE"

    if n == 0:
        run["layflat_deviation_max_mm"] = None
        run["bubble_instability_events"] = 0
    else:
        target_layflat = D(product["layflat_width_mm"])
        worst = max(abs(D(x["layflat_mm"]) - target_layflat) for x in readings)
        run["layflat_deviation_max_mm"] = f(r(worst, 2))
        run["bubble_instability_events"] = sum(
            1 for x in readings if abs(D(x["bubble_deviation_mm"])) > C.BUBBLE_LIMIT_MM
        )
    return run


# =====================================================================
# run_mass_balance
# =====================================================================
def run_reincorporations(run):
    return [
        t
        for t in refs.transactions_of_run(run)
        if t["origin_kind"] == "REINCORPORATION" and not refs.is_reversed(t)
    ]


def recompute_run_regrind(run):
    txns = run_reincorporations(run)
    consumed = r(sum((D(t["kg"]) for t in txns), ZERO), 3)
    run["regrind_consumed_kg"] = f(consumed)
    gross = run.get("gross_output_kg")
    if gross is not None:
        gross_d = D(gross)
        run["regrind_actual_pct"] = (
            f(r(consumed / gross_d * D(100), 3)) if gross_d != 0 else f(ZERO, 3)
        )
    return consumed


def run_mass_balance(run, gross_output_kg, scrap_kg):
    recipe = refs.recipe_of_run(run)
    txns = run_reincorporations(run)
    consumed = r(sum((D(t["kg"]) for t in txns), ZERO), 3)
    regrind_pcr = sum((D(t["pcr_kg"]) for t in txns), ZERO)

    gross = D(gross_output_kg)
    scrap = D(scrap_kg)
    net_good = r(gross - scrap, 3)
    virgin_feed = r(max(ZERO, gross - consumed), 3)
    virgin_pcr_pct = D(recipe["virgin_pcr_pct"]) if recipe else ZERO
    pcr_mass = r(virgin_feed * virgin_pcr_pct / D(100) + regrind_pcr, 3)

    run["regrind_consumed_kg"] = f(consumed)
    run["net_good_kg"] = f(net_good)
    run["pcr_mass_kg"] = f(pcr_mass)
    if gross != 0:
        actual = r(pcr_mass / gross * D(100), 3)
        run["regrind_actual_pct"] = f(r(consumed / gross * D(100), 3))
    else:
        actual = r(ZERO, 3)
        run["regrind_actual_pct"] = f(ZERO, 3)
    run["actual_recycled_content_pct"] = f(actual)
    scrap_pcr = r(scrap * actual / D(100), 3)
    return actual, scrap_pcr


# =====================================================================
# pool_mass_balance
# =====================================================================
def _pool_input_set(pool):
    rows = []
    for t in refs.transactions_of_pool(pool):
        if t["origin_kind"] == "REVERSAL":
            continue
        if refs.is_reversed(t):
            continue
        rows.append(t)
    return rows


def recompute_pool(pool):
    rows = _pool_input_set(pool)
    cum_in = r(sum((D(t["kg"]) for t in rows if t["direction"] == "IN"), ZERO), 3)
    cum_out = r(sum((D(t["kg"]) for t in rows if t["direction"] == "OUT"), ZERO), 3)
    cum_in_pcr = r(sum((D(t["pcr_kg"]) for t in rows if t["direction"] == "IN"), ZERO), 3)
    available = r(cum_in - cum_out, 3)
    pool["cumulative_in_kg"] = f(cum_in)
    pool["cumulative_out_kg"] = f(cum_out)
    pool["cumulative_in_pcr_kg"] = f(cum_in_pcr)
    pool["available_kg"] = f(available)
    pool["embedded_pcr_pct"] = (
        f(ZERO, 3) if cum_in == 0 else f(r(cum_in_pcr / cum_in * D(100), 3))
    )
    pool["generation_count"] = sum(1 for t in rows if t["direction"] == "IN")
    pool["reincorporation_count"] = sum(1 for t in rows if t["direction"] == "OUT")
    return available


def simulate_pool_available_without(pool, excluded_id):
    cum_in = ZERO
    cum_out = ZERO
    for t in refs.transactions_of_pool(pool):
        if t["origin_kind"] == "REVERSAL" or t["id"] == excluded_id:
            continue
        if refs.is_reversed(t):
            continue
        if t["direction"] == "IN":
            cum_in += D(t["kg"])
        else:
            cum_out += D(t["kg"])
    return r(r(cum_in, 3) - r(cum_out, 3), 3)


# =====================================================================
# seal_strength_qualification
# =====================================================================
def bottom_seal_specimens(lot):
    return [s for s in lot["seal_specimens"] if s["test_kind"] == "BOTTOM_SEAL"]


def recompute_seal_provisional(lot):
    product = refs.product_of_lot(lot)
    first_pass = [s for s in bottom_seal_specimens(lot) if not s["is_retest"]]
    if len(first_pass) < C.MIN_SEAL_SPECIMENS:
        lot["seal_provisional_mean_n"] = None
        lot["seal_provisional_verdict"] = "PENDING"
        return
    mean = sum((D(s["measured_n_per_15mm"]) for s in first_pass), ZERO) / D(len(first_pass))
    mean_r = r(mean, 2)
    lot["seal_provisional_mean_n"] = f(mean_r)
    spec = D(product["min_bottom_seal_n_per_15mm"])
    lot["seal_provisional_verdict"] = "PASS" if mean_r >= spec else "FAIL"


def superseding_panel(lot):
    """For each specimen_index among BOTTOM_SEAL rows keep only the highest attempt."""
    best = {}
    for s in bottom_seal_specimens(lot):
        idx = s["specimen_index"]
        if idx not in best or s["attempt"] > best[idx]["attempt"]:
            best[idx] = s
    return [best[k] for k in sorted(best)]


def final_seal_verdict(lot):
    product = refs.product_of_lot(lot)
    panel = superseding_panel(lot)
    values = [D(s["measured_n_per_15mm"]) for s in panel]
    min_n = r(min(values), 2)
    mean_n = r(sum(values, ZERO) / D(len(values)), 2)
    spec = D(product["min_bottom_seal_n_per_15mm"])
    pass_floor = r(spec * C.SEAL_PASS_MIN_RATIO, 2)
    conditional_floor = r(spec * C.SEAL_COND_MIN_RATIO, 2)
    conditional_mean = r(spec * C.SEAL_COND_MEAN_RATIO, 2)
    if min_n >= pass_floor and mean_n >= spec:
        verdict = "PASS"
    elif min_n >= conditional_floor and mean_n >= conditional_mean:
        verdict = "CONDITIONAL"
    else:
        verdict = "FAIL"
    return verdict, min_n, mean_n


# =====================================================================
# bag_count_and_accuracy
# =====================================================================
def recompute_bag_counts(lot):
    product = refs.product_of_lot(lot)
    job, roll, run, line, recipe, plate = refs.lot_chain(lot)
    density = D(recipe["blended_density_kg_m3"]) if recipe else ZERO
    unit = (
        D(product["layflat_width_mm"]) / D(1000)
        * D(2)
        * ((D(product["bag_length_mm"]) + D(product["gusset_depth_mm"])) / D(1000))
        * (D(product["target_gauge_micron"]) / D(1000000))
        * density
    )
    unit_r = r(unit, 6)
    lot["bag_unit_weight_kg"] = f(unit_r)
    printed = job.get("printed_kg") if job else None
    if printed is None or unit_r == 0:
        theoretical = 0
    else:
        theoretical = floor_div(D(printed), unit_r)
    lot["bag_count_theoretical"] = theoretical
    if theoretical == 0:
        lot["count_accuracy_pct"] = None
        lot["count_accuracy_conforming"] = False
    else:
        accuracy = r(D(lot["bag_count_produced"]) / D(theoretical) * D(100), 2)
        lot["count_accuracy_pct"] = f(accuracy)
        lot["count_accuracy_conforming"] = abs(accuracy - D(100)) <= D(
            product["count_accuracy_tolerance_pct"]
        )


def case_packout_allocation(lot, product, requested_bags):
    per_case = int(product["bags_per_case"])
    full_cases = requested_bags // per_case
    remainder = requested_bags - full_cases * per_case
    threshold = int(product["min_partial_case_bags"])
    partial_case = 1 if (remainder > 0 and remainder >= threshold) else 0
    partial_bags = remainder if partial_case == 1 else 0
    packed_now = full_cases * per_case + partial_bags

    lot["packed_bag_count"] = lot["packed_bag_count"] + packed_now
    lot["packed_case_count"] = lot["packed_case_count"] + full_cases + partial_case
    lot["partial_case_bag_count"] = lot["partial_case_bag_count"] + partial_bags
    lot["bag_count_unpacked"] = lot["bag_count_unpacked"] - packed_now
    lot["pallet_count"] = ceil_int_div(lot["packed_case_count"], int(product["cases_per_pallet"]))
    return packed_now


# =====================================================================
# line_posture
# =====================================================================
def derive_posture(line):
    active_holds = sum(
        1
        for run in store.extrusion_runs.values()
        if run["line_id"] == line["id"] and run["status"] == "HELD"
    )
    line["active_hold_count"] = active_holds
    incapable = int(line["incapable_run_count"])
    revoked = int(line["revoked_dossier_count"])
    if incapable >= C.POSTURE_FROZEN_MIN_INCAPABLE or revoked >= C.POSTURE_FROZEN_MIN_REVOKED:
        return "FROZEN"
    if incapable == 1 or active_holds >= C.POSTURE_RESTRICTED_MIN_HOLDS:
        return "RESTRICTED"
    return "OPEN"


# =====================================================================
# line_occupancy_conflict
# =====================================================================
def has_window_conflict(line, blend_recipe_id, start, end, exclude_run_id=None):
    from datetime import timedelta

    new_product = refs.product_of_recipe(store.blend_recipes.get(blend_recipe_id))
    new_food = bool(new_product["food_contact_required"]) if new_product else False
    buffer_minutes = int(line["purge_buffer_minutes"])
    for other in refs.runs_of_line(line):
        if other["id"] == exclude_run_id:
            continue
        if other["status"] not in C.OCCUPYING_RUN_STATES:
            continue
        other_product = refs.product_of_run(other)
        other_food = bool(other_product["food_contact_required"]) if other_product else False
        same = other["blend_recipe_id"] == blend_recipe_id and other_food == new_food
        gap = timedelta(minutes=0 if same else buffer_minutes)
        if start < other["_scheduled_end"] + gap and other["_scheduled_start"] < end + gap:
            return True
    return False


# =====================================================================
# press_cylinder_capacity
# =====================================================================
def cylinders_occupied(press, start, end, exclude_job_id=None):
    total = 0
    for job in store.sorted_values(store.print_jobs):
        if job["press_id"] != press["id"] or job["id"] == exclude_job_id:
            continue
        if job["status"] not in ("SETUP", "PRINTING"):
            continue
        if job["_window_start"] < end and start < job["_window_end"]:
            total += int(job["cylinders_required"])
    return total
