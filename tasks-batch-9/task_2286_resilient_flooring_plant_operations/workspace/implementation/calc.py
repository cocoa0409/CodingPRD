"""Deterministic calculations (SCAFFOLD calculations / PRD 2.6, 3.1-3.9)."""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from db import db, ordered

ZERO = Decimal("0")


def d(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return None
    return Decimal(str(value))


def rhu(value, places):
    """ROUND_HALF_UP to `places` decimals."""
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def cents(value):
    return int(rhu(value, 0))


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def components_of(formulation_id):
    return ordered([c for c in db.formulation_components.values()
                    if c["formulation_id"] == formulation_id])


def film_of(sku):
    return db.print_films.get(sku["print_film_id"])


def license_of_film(film):
    return db.design_licenses.get(film["license_id"]) if film else None


def license_of_sku(sku):
    return license_of_film(film_of(sku))


def license_of_run(run):
    sku = db.product_skus.get(run["sku_id"])
    return license_of_sku(sku) if sku else None


CLICK_LOCK = ("CLICK_LOCK_SPC", "CLICK_LOCK_WPC")


# ---------------------------------------------------------------------------
# formulation_blend_metrics
# ---------------------------------------------------------------------------

BLEND_FIELDS = (
    "total_phr", "resin_phr", "plasticizer_phr", "filler_phr", "stabilizer_phr",
    "blended_cost_per_kg_cents", "performance_score", "indentation_resistance_class",
)


def formulation_blend_metrics(formulation):
    comps = components_of(formulation["id"])
    if not comps:
        return {
            "total_phr": Decimal("0.00"),
            "resin_phr": None,
            "plasticizer_phr": None,
            "filler_phr": None,
            "stabilizer_phr": None,
            "blended_cost_per_kg_cents": None,
            "performance_score": None,
            "indentation_resistance_class": None,
        }

    pinned = formulation.get("cost_basis") == "PINNED"
    total_raw = ZERO
    by_cat = {"VINYL_RESIN": ZERO, "PLASTICIZER": ZERO, "FILLER": ZERO, "STABILIZER": ZERO}
    cost_sum = ZERO
    ind_sum = ZERO
    thm_sum = ZERO
    mig_sum = ZERO

    for c in comps:
        material = db.raw_materials[c["raw_material_id"]]
        phr = d(c["phr"])
        total_raw += phr
        by_cat[material["category"]] = by_cat[material["category"]] + phr
        snap = c.get("material_cost_snapshot_cents")
        unit_cost = d(snap) if (pinned and snap is not None) else d(material["cost_per_kg_cents"])
        cost_sum += phr * unit_cost
        ind_sum += phr * d(material["indentation_index"])
        thm_sum += phr * d(material["thermal_stability_index"])
        mig_sum += phr * (Decimal(100) - d(material["plasticizer_migration_index"]))

    total_phr = rhu(total_raw, 2)
    resin_phr = rhu(by_cat["VINYL_RESIN"], 2)
    plasticizer_phr = rhu(by_cat["PLASTICIZER"], 2)
    filler_phr = rhu(by_cat["FILLER"], 2)
    stabilizer_phr = rhu(by_cat["STABILIZER"], 2)

    blended_cost = cents(cost_sum / total_phr)
    blended_indentation = rhu(ind_sum / total_phr, 6)
    blended_thermal = rhu(thm_sum / total_phr, 6)
    blended_migration = rhu(mig_sum / total_phr, 6)

    if resin_phr > 0:
        plasticizer_ratio = rhu(plasticizer_phr / resin_phr, 4)
        filler_ratio = rhu(filler_phr / resin_phr, 4)
        softness = 12 if plasticizer_ratio > Decimal("0.35") else (5 if plasticizer_ratio > Decimal("0.25") else 0)
        brittleness = 8 if filler_ratio >= Decimal("3.00") else (3 if filler_ratio >= Decimal("2.00") else 0)
    else:
        softness = 0
        brittleness = 0

    raw_score = (Decimal("0.40") * blended_indentation
                 + Decimal("0.35") * blended_thermal
                 + Decimal("0.25") * blended_migration
                 - softness - brittleness)
    clamped = max(Decimal(0), min(Decimal(100), raw_score))
    performance_score = rhu(clamped, 2)

    if blended_indentation >= Decimal("88.00"):
        cls = "CLASS_34_43"
    elif blended_indentation >= Decimal("70.00"):
        cls = "CLASS_33_42"
    else:
        cls = "CLASS_23_31"

    return {
        "total_phr": total_phr,
        "resin_phr": resin_phr,
        "plasticizer_phr": plasticizer_phr,
        "filler_phr": filler_phr,
        "stabilizer_phr": stabilizer_phr,
        "blended_cost_per_kg_cents": blended_cost,
        "performance_score": performance_score,
        "indentation_resistance_class": cls,
    }


def apply_blend_metrics(formulation):
    formulation.update(formulation_blend_metrics(formulation))


# ---------------------------------------------------------------------------
# sku_required_test_types
# ---------------------------------------------------------------------------

CANONICAL_TEST_ORDER = [
    "RESIDUAL_INDENTATION",
    "DIMENSIONAL_STABILITY_HEAT",
    "SLIP_RESISTANCE",
    "PEEL_ADHESION_DELAMINATION",
    "LOCK_SHEAR",
]


def sku_required_test_types(sku):
    required = {"RESIDUAL_INDENTATION", "DIMENSIONAL_STABILITY_HEAT"}
    if sku["waterproof_rated"]:
        required.add("SLIP_RESISTANCE")
    if sku["attached_underlayment_type"] != "NONE":
        required.add("PEEL_ADHESION_DELAMINATION")
    if sku["construction_type"] in CLICK_LOCK:
        required.add("LOCK_SHEAR")
    return [t for t in CANONICAL_TEST_ORDER if t in required]


# ---------------------------------------------------------------------------
# test_spec_limit_and_outcome
# ---------------------------------------------------------------------------

def test_spec_limit_and_outcome(sku, formulation, test_type, measured_value):
    measured = d(measured_value)
    if test_type == "RESIDUAL_INDENTATION":
        unit = "mm"
        lower_is_better = True
        cls = formulation.get("indentation_resistance_class") if formulation else None
        if cls == "CLASS_34_43":
            spec = Decimal("0.10")
        elif cls == "CLASS_33_42":
            spec = Decimal("0.20")
        else:
            spec = Decimal("0.30")
    elif test_type == "DIMENSIONAL_STABILITY_HEAT":
        unit = "PCT"
        lower_is_better = True
        spec = Decimal("0.15") if sku["construction_type"] in CLICK_LOCK else Decimal("0.25")
    elif test_type == "SLIP_RESISTANCE":
        unit = "DCOF"
        lower_is_better = False
        spec = Decimal("0.42") if sku["waterproof_rated"] else Decimal("0.36")
    elif test_type == "PEEL_ADHESION_DELAMINATION":
        unit = "N_PER_25MM"
        lower_is_better = False
        under = sku["attached_underlayment_type"]
        if under == "IXPE_1MM":
            spec = Decimal("35.0")
        elif under == "EVA_1_5MM":
            spec = Decimal("30.0")
        else:
            spec = Decimal("45.0")
    else:  # LOCK_SHEAR
        unit = "N_PER_MM"
        lower_is_better = False
        spec = d(sku["target_lock_shear_n_per_mm"])

    if spec is None:
        return unit, None, "FAIL"

    if lower_is_better:
        edge = rhu(spec * Decimal("1.05"), 4)
        if measured <= spec:
            outcome = "PASS"
        elif measured <= edge:
            outcome = "MARGINAL"
        else:
            outcome = "FAIL"
    else:
        edge = rhu(spec * Decimal("0.95"), 4)
        if measured >= spec:
            outcome = "PASS"
        elif measured >= edge:
            outcome = "MARGINAL"
        else:
            outcome = "FAIL"
    return unit, spec, outcome


# ---------------------------------------------------------------------------
# sku_warranty_terms
# ---------------------------------------------------------------------------

def sku_warranty_terms(sku):
    wear = d(sku["wear_layer_mil"])
    if wear >= 20:
        residential, commercial = 25, 15
    elif wear >= 12:
        residential, commercial = 20, 10
    elif wear >= 6:
        residential, commercial = 15, 5
    else:
        residential, commercial = 10, 0
    bonus = 5 if (sku["waterproof_rated"] and sku["construction_type"] in CLICK_LOCK) else 0
    return min(residential + bonus, 30), min(commercial + bonus, 20)


# ---------------------------------------------------------------------------
# sku_standard_cost
# ---------------------------------------------------------------------------

UNDERLAYMENT_CENTS = {"NONE": 0, "IXPE_1MM": 22, "EVA_1_5MM": 17, "CORK_2MM": 41}


def live_blended_cost(formulation):
    comps = components_of(formulation["id"])
    if not comps:
        return None
    total = ZERO
    weighted = ZERO
    for c in comps:
        material = db.raw_materials[c["raw_material_id"]]
        phr = d(c["phr"])
        total += phr
        weighted += phr * d(material["cost_per_kg_cents"])
    total_phr = rhu(total, 2)
    if total_phr == 0:
        return None
    return cents(weighted / total_phr)


def pinned_blended_cost(formulation):
    comps = components_of(formulation["id"])
    if not comps:
        return None
    if any(c.get("material_cost_snapshot_cents") is None for c in comps):
        return live_blended_cost(formulation)
    total = ZERO
    weighted = ZERO
    for c in comps:
        phr = d(c["phr"])
        total += phr
        weighted += phr * d(c["material_cost_snapshot_cents"])
    total_phr = rhu(total, 2)
    if total_phr == 0:
        return None
    return cents(weighted / total_phr)


def cost_components(sku, film, license_row):
    max_repeat = max(d(film["pattern_repeat_mm_length"]), d(film["pattern_repeat_mm_width"]))
    if max_repeat >= 1800:
        repeat_surcharge = 6
    elif max_repeat >= 1200:
        repeat_surcharge = 2
    else:
        repeat_surcharge = 0
    wear_cost = cents(d(sku["wear_layer_mil"]) * Decimal("3.5"))
    film_cost = 18 + repeat_surcharge
    under_cost = UNDERLAYMENT_CENTS[sku["attached_underlayment_type"]]
    water_cost = 9 if sku["waterproof_rated"] else 0
    conv_cost = 35 + (12 if sku["construction_type"] in CLICK_LOCK else 0)
    royalty_cost = cents(d(sku["royalty_basis_price_cents_per_sqm"])
                         * d(license_row["royalty_rate_bps"]) / Decimal(10000))
    return {
        "wear_layer_cost_cents": wear_cost,
        "print_film_cost_cents": film_cost,
        "underlayment_cost_cents": under_cost,
        "waterproof_cost_cents": water_cost,
        "conversion_cost_cents": conv_cost,
        "royalty_cost_cents": royalty_cost,
    }


def core_cost(blended_cost_per_kg_cents, sku):
    if blended_cost_per_kg_cents is None:
        return 0
    return cents(d(blended_cost_per_kg_cents) * Decimal("1.90") * d(sku["overall_thickness_mm"]))


def list_price(standard_cost, sku):
    return cents(d(standard_cost) * (Decimal(10000) + d(sku["target_margin_bps"])) / Decimal(10000))


def sku_standard_cost(sku, basis):
    """basis is 'LIVE_BASIS' or 'PINNED_BASIS'.  Returns (standard, list, parts)."""
    formulation = db.formulations.get(sku["formulation_id"])
    film = film_of(sku)
    license_row = license_of_film(film)
    if formulation is None or film is None or license_row is None:
        return None, None, None
    blended = (live_blended_cost(formulation) if basis == "LIVE_BASIS"
               else pinned_blended_cost(formulation))
    parts = cost_components(sku, film, license_row)
    core = core_cost(blended, sku)
    standard = (core + parts["wear_layer_cost_cents"] + parts["print_film_cost_cents"]
                + parts["underlayment_cost_cents"] + parts["waterproof_cost_cents"]
                + parts["conversion_cost_cents"] + parts["royalty_cost_cents"])
    parts = dict(parts)
    parts["core_cost_cents"] = core
    parts["blended_cost_per_kg_cents"] = blended
    return standard, list_price(standard, sku), parts


def cost_summary(sku):
    live_standard, live_list, live_parts = sku_standard_cost(sku, "LIVE_BASIS")
    pinned_standard, pinned_list, pinned_parts = sku_standard_cost(sku, "PINNED_BASIS")
    if live_parts is None:
        return None
    return {
        "live_basis_core_cost_cents": live_parts["core_cost_cents"],
        "pinned_basis_core_cost_cents": pinned_parts["core_cost_cents"],
        "live_basis_blended_cost_per_kg_cents": live_parts["blended_cost_per_kg_cents"],
        "pinned_basis_blended_cost_per_kg_cents": pinned_parts["blended_cost_per_kg_cents"],
        "wear_layer_cost_cents": live_parts["wear_layer_cost_cents"],
        "print_film_cost_cents": live_parts["print_film_cost_cents"],
        "underlayment_cost_cents": live_parts["underlayment_cost_cents"],
        "waterproof_cost_cents": live_parts["waterproof_cost_cents"],
        "conversion_cost_cents": live_parts["conversion_cost_cents"],
        "royalty_cost_cents": live_parts["royalty_cost_cents"],
        "live_basis_standard_cost_cents_per_sqm": live_standard,
        "pinned_basis_standard_cost_cents_per_sqm": pinned_standard,
        "basis_delta_cents_per_sqm": live_standard - pinned_standard,
        "live_basis_list_price_cents_per_sqm": live_list,
        "pinned_basis_list_price_cents_per_sqm": pinned_list,
        "pin_stale": sku["pin_stale"],
    }


# ---------------------------------------------------------------------------
# press_line_changeover_gap
# ---------------------------------------------------------------------------

def predecessor_run(press_line_id, start_utc, exclude_run_id=None):
    best = None
    for run in db.production_runs.values():
        if run["press_line_id"] != press_line_id:
            continue
        if exclude_run_id is not None and run["id"] == exclude_run_id:
            continue
        if run["run_status"] == "ABORTED":
            continue
        if run["planned_end_utc"] > start_utc:
            continue
        if best is None:
            best = run
            continue
        if run["planned_end_utc"] > best["planned_end_utc"]:
            best = run
        elif run["planned_end_utc"] == best["planned_end_utc"]:
            if (run["created_at"], run["_seq"]) < (best["created_at"], best["_seq"]):
                best = run
    return best


def changeover_gap_minutes(press_line, sku, prev_run):
    if prev_run is None:
        return 0
    prev_sku = db.product_skus.get(prev_run["sku_id"])
    if prev_sku is None:
        return 0
    if prev_sku["formulation_id"] == sku["formulation_id"]:
        multiplier = Decimal("0.50")
    elif prev_sku["print_film_id"] == sku["print_film_id"]:
        multiplier = Decimal("0.75")
    else:
        multiplier = Decimal("1.00")
    base = (d(press_line["changeover_minutes"]) * multiplier).to_integral_value(rounding=ROUND_CEILING)
    delta = abs(d(sku["overall_thickness_mm"]) - d(prev_sku["overall_thickness_mm"]))
    if delta >= Decimal("2.0"):
        surcharge = 30
    elif delta >= Decimal("0.5"):
        surcharge = 10
    else:
        surcharge = 0
    return int(base) + surcharge


# ---------------------------------------------------------------------------
# license ledger / royalty
# ---------------------------------------------------------------------------

def clamp_qty(value):
    result = rhu(value, 2)
    return result if result > 0 else Decimal("0.00")


def run_royalty_cents(run, sku, license_row):
    return cents(d(run["actual_quantity_sqm"])
                 * d(sku["royalty_basis_price_cents_per_sqm"])
                 * d(license_row["royalty_rate_bps"]) / Decimal(10000))


def license_utilization(license_row):
    projected = rhu(d(license_row["consumed_volume_sqm"]) + d(license_row["reserved_volume_sqm"]), 2)
    remaining = rhu(d(license_row["term_volume_cap_sqm"]) - projected, 2)
    contributing = 0
    for run in db.production_runs.values():
        if run["run_status"] != "COMPLETED" or run["qc_disposition"] == "SCRAPPED":
            continue
        governing = license_of_run(run)
        if governing is not None and governing["id"] == license_row["id"]:
            contributing += 1
    return {
        "term_volume_cap_sqm": d(license_row["term_volume_cap_sqm"]),
        "reserved_volume_sqm": d(license_row["reserved_volume_sqm"]),
        "consumed_volume_sqm": d(license_row["consumed_volume_sqm"]),
        "projected_volume_sqm": projected,
        "remaining_volume_sqm": remaining,
        "accrued_royalty_cents": license_row["accrued_royalty_cents"],
        "contributing_run_count": contributing,
    }


# ---------------------------------------------------------------------------
# run_quality_metrics
# ---------------------------------------------------------------------------

def run_quality_metrics(run, sku, film, press_line):
    max_repeat = max(d(film["pattern_repeat_mm_length"]), d(film["pattern_repeat_mm_width"]))
    pattern_waste = rhu(d(run["actual_quantity_sqm"]) * max_repeat / Decimal(60000) * Decimal("0.35"), 2)

    registration_ok = abs(d(run["registration_drift_mm"])) <= d(film["registration_tolerance_mm"])
    emboss_ok = abs(d(run["emboss_alignment_offset_mm"]) - d(film["emboss_alignment_offset_mm"])) <= Decimal("0.30")
    curl_allowance = rhu(Decimal("2.00") * (Decimal(100) - d(press_line["curl_control_index"])) / Decimal(100), 2)
    curl_ok = abs(d(run["curl_deviation_mm"])) <= curl_allowance

    if sku["profile_family"] == "NONE":
        tongue_ok = True
    else:
        measured = d(run["measured_tongue_thickness_mm"])
        if measured is None:
            tongue_ok = False
        else:
            target = d(sku["tongue_thickness_target_mm"])
            low = target - d(sku["tolerance_minus_mm"])
            high = target + d(sku["tolerance_plus_mm"])
            tongue_ok = low <= measured <= high

    gates_hold = registration_ok and emboss_ok and curl_ok and tongue_ok
    return {
        "pattern_waste_sqm": pattern_waste,
        "registration_within_tolerance": registration_ok,
        "emboss_within_tolerance": emboss_ok,
        "curl_within_tolerance": curl_ok,
        "tongue_within_tolerance": tongue_ok,
        "auto_disposition_recommendation": "RELEASED" if gates_hold else "QUARANTINED",
    }


# ---------------------------------------------------------------------------
# allocation_fill_plan
# ---------------------------------------------------------------------------

SUBSTITUTION_RANK = {"EXACT": 0, "UNDERLAYMENT_UPGRADE": 1, "WEAR_LAYER_UPGRADE": 2}


def _substitution_kind(allocation, requested, candidate_sku, batch):
    if batch["sku_id"] == allocation["sku_id"]:
        return "EXACT"
    policy = allocation["substitution_policy"]
    if policy == "ALLOW_UNDERLAYMENT_UPGRADE":
        if (requested["attached_underlayment_type"] == "NONE"
                and candidate_sku["attached_underlayment_type"] != "NONE"
                and candidate_sku["formulation_id"] == requested["formulation_id"]
                and candidate_sku["print_film_id"] == requested["print_film_id"]
                and candidate_sku["construction_type"] == requested["construction_type"]
                and d(candidate_sku["wear_layer_mil"]) == d(requested["wear_layer_mil"])):
            return "UNDERLAYMENT_UPGRADE"
    elif policy == "ALLOW_WEAR_LAYER_UPGRADE":
        if (d(candidate_sku["wear_layer_mil"]) > d(requested["wear_layer_mil"])
                and candidate_sku["formulation_id"] == requested["formulation_id"]
                and candidate_sku["print_film_id"] == requested["print_film_id"]
                and candidate_sku["construction_type"] == requested["construction_type"]
                and candidate_sku["attached_underlayment_type"] == requested["attached_underlayment_type"]
                and candidate_sku["waterproof_rated"] == requested["waterproof_rated"]):
            return "WEAR_LAYER_UPGRADE"
    return None


def fill_candidates(allocation):
    """Step 1 (eligibility) + step 2 (ranking)."""
    requested = db.product_skus.get(allocation["sku_id"])
    if requested is None:
        return []
    found = []
    for batch in db.batches.values():
        if batch["status"] != "IN_STOCK":
            continue
        if d(batch["available_quantity_sqm"]) <= 0:
            continue
        run = db.production_runs.get(batch["production_run_id"])
        if run is None or run["qc_disposition"] != "RELEASED":
            continue
        candidate_sku = db.product_skus.get(batch["sku_id"])
        if candidate_sku is None or candidate_sku["commercial_status"] == "DISCONTINUED":
            continue
        kind = _substitution_kind(allocation, requested, candidate_sku, batch)
        if kind is None:
            continue
        found.append((SUBSTITUTION_RANK[kind], batch["created_at"], batch["batch_code"],
                      batch["_seq"], batch, kind))
    found.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    return [(item[4], item[5]) for item in found]


def upgrade_premium_per_sqm(candidate_sku, requested_sku):
    a = candidate_sku.get("standard_cost_cents_per_sqm")
    b = requested_sku.get("standard_cost_cents_per_sqm")
    if a is None or b is None:
        return 0
    return max(0, a - b)


# ---------------------------------------------------------------------------
# warranty_settlement_amount
# ---------------------------------------------------------------------------

STEPPED_TYPES = ("DELAMINATION", "LOCK_FAILURE")


def elapsed_whole_months(installed_on, reported_on):
    months = (reported_on.year - installed_on.year) * 12 + (reported_on.month - installed_on.month)
    if (reported_on.day, reported_on.hour, reported_on.minute, reported_on.second,
            reported_on.microsecond) < (installed_on.day, installed_on.hour, installed_on.minute,
                                        installed_on.second, installed_on.microsecond):
        months -= 1
    return max(0, months)


def settlement_variant_for(claim_type):
    return "STEPPED_SCHEDULE" if claim_type in STEPPED_TYPES else "PRORATED_STRAIGHT_LINE"


def warranty_settlement(claim, batch, sku):
    elapsed_months = claim["elapsed_months"]
    coverage_months = sku["warranty_years"] * 12
    remaining_months = max(0, coverage_months - elapsed_months)

    replacement_value = cents(d(claim["claimed_area_sqm"]) * d(sku["royalty_basis_price_cents_per_sqm"]))
    labor = cents(d(claim["claimed_area_sqm"]) * Decimal(350)) if claim["installed_by_certified_installer"] else 0

    variant = settlement_variant_for(claim["claim_type"])
    defect_confirmed = d(batch["wear_layer_measured_mil"]) < (d(sku["wear_layer_mil"]) - Decimal("0.5"))

    if defect_confirmed:
        covered = replacement_value
    elif variant == "PRORATED_STRAIGHT_LINE":
        if coverage_months == 0:
            covered = 0
        else:
            covered = cents(d(replacement_value) * Decimal(remaining_months) / Decimal(coverage_months))
    else:
        elapsed_years = int((Decimal(elapsed_months) / Decimal(12)).to_integral_value(rounding=ROUND_FLOOR))
        if elapsed_years <= 1:
            step_pct = 100
        elif elapsed_years <= 3:
            step_pct = 80
        elif elapsed_years <= 7:
            step_pct = 60
        elif elapsed_years <= 12:
            step_pct = 40
        else:
            step_pct = 20
        covered = cents(d(replacement_value) * Decimal(step_pct) / Decimal(100))

    return {
        "settlement_variant": variant,
        "replacement_value_cents": replacement_value,
        "labor_allowance_cents": labor,
        "settlement_amount_cents": covered + labor,
    }
