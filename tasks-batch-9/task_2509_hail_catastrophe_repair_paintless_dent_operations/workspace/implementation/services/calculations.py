"""The calculation rules of SCAFFOLD §1.3 / PRD §3, implemented literally."""

from clock import clock, parse_date
from db import db, newest_first
from numeric import D, ceil_int, frac, round_half_up
from services import aggregates
from services.constants import (
    ALUMINUM_MULTIPLIER,
    COMPETITOR_CAP,
    COMPETITOR_PENALTY_PER_SHOP,
    DENT_TIER_LIGHT_MAX,
    DENT_TIER_MEDIUM_MAX,
    DISCOUNT_PCT_TIER_0,
    DISCOUNT_PCT_TIER_1,
    DISCOUNT_PCT_TIER_2,
    DISCOUNT_TIER_1_FLOOR_CENTS,
    DISCOUNT_TIER_2_FLOOR_CENTS,
    HAIL_MM_CAP,
    LABOR_POOL_PCT,
    POOL_SPLIT_PCT,
    POPULATION_CAP,
    POPULATION_DIVISOR,
    SEVERITY_DIVISOR,
    SEVERITY_WEIGHT_GROUND_TRUTHED,
    SEVERITY_WEIGHT_MODELED,
    SUPPLEMENT_AUTO_APPROVE_FLOOR_CENTS,
    SUPPLEMENT_CUMULATIVE_CAP_PCT,
    SWATH_BONUS_KM2_THRESHOLD,
    SWATH_BONUS_POINTS,
    TIER_MULT_HEAVY,
    TIER_MULT_LIGHT,
    TIER_MULT_MEDIUM,
    TIER_WEIGHT,
    TOTAL_LOSS_THRESHOLD_PCT,
    VEHICLES_PER_TECH_PER_DAY,
    OPEN_REPAIR_STATUSES,
    TERMINAL_REPAIR_STATUSES,
)


# =============================================================================
# storm_targeting_score
# =============================================================================
def storm_targeting_score(event):
    severity_weight = (
        SEVERITY_WEIGHT_GROUND_TRUTHED
        if event["swath_confidence"] == "GROUND_TRUTHED"
        else SEVERITY_WEIGHT_MODELED
    )
    capped_hail_mm = min(event["max_hail_size_mm"], HAIL_MM_CAP)
    severity_term = severity_weight * D(capped_hail_mm) / SEVERITY_DIVISOR
    density_term = D(min(event["vehicle_population_estimate"], POPULATION_CAP)) / POPULATION_DIVISOR
    swath_bonus = SWATH_BONUS_POINTS if event["swath_area_km2"] >= SWATH_BONUS_KM2_THRESHOLD else D(0)
    competition_term = COMPETITOR_PENALTY_PER_SHOP * D(min(event["competitor_shop_count"], COMPETITOR_CAP))
    raw = severity_term + density_term + swath_bonus - competition_term
    return max(0, min(100, round_half_up(raw)))


# =============================================================================
# rate_agreement_selector
# =============================================================================
def select_rate_agreement(vehicle):
    facility = db.facilities.get(vehicle["facility_id"])
    if facility is None:
        return None
    storm_event_id = facility["storm_event_id"]
    clock_date = clock.date()
    candidates = []
    for agreement in db.rate_agreements.values():
        if agreement["insurer_id"] != vehicle["insurer_id"]:
            continue
        if agreement["storm_event_id"] != storm_event_id:
            continue
        if agreement["status"] != "ACTIVE":
            continue
        effective_from = parse_date(agreement["effective_from"])
        if effective_from is None or effective_from > clock_date:
            continue
        candidates.append(agreement)
    if not candidates:
        return None
    # ranking: effective_from DESC, tie-break created_at DESC (never id)
    ranked = sorted(
        newest_first(candidates),
        key=lambda a: parse_date(a["effective_from"]),
        reverse=True,
    )
    return ranked[0]


# =============================================================================
# vehicle_repair_estimate
# =============================================================================
def _tier_multiplier(dent_count):
    if dent_count <= DENT_TIER_LIGHT_MAX:
        return TIER_MULT_LIGHT
    if dent_count <= DENT_TIER_MEDIUM_MAX:
        return TIER_MULT_MEDIUM
    return TIER_MULT_HEAVY


def _matrix_rate(agreement, dent_size_class):
    return agreement["matrix_rate_%s_cents" % dent_size_class.lower()]


def vehicle_repair_estimate(vehicle, agreement):
    """Prices every damage line under both variants and writes the results."""
    lines = aggregates.damage_lines_of_vehicle(vehicle["id"])
    matrix_total = 0
    conventional_total = 0
    any_capped = False
    oversize_sum = 0

    for line in lines:
        size_rate = _matrix_rate(agreement, line["dent_size_class"])
        tier_multiplier = _tier_multiplier(line["dent_count"])
        alum_multiplier = ALUMINUM_MULTIPLIER if line["aluminum"] else D("1.00")
        raw_line = (
            D(size_rate) * D(line["dent_count"]) * tier_multiplier * alum_multiplier
            + D(line["r_and_i_hours"]) * D(agreement["labor_rate_cents_per_hour"])
        )
        # ROUNDING ORDER IS PINNED: round every panel first, then sum panels.
        pdr_line_cents = round_half_up(raw_line)
        capped = pdr_line_cents > agreement["panel_cap_cents"]
        if capped:
            pdr_line_cents = agreement["panel_cap_cents"]
        routed_to = "CONVENTIONAL" if (capped or line["oversize_dent_count"] > 0) else "PDR"
        conventional_line_cents = round_half_up(
            D(line["conventional_labor_hours"]) * D(agreement["labor_rate_cents_per_hour"])
            + D(line["conventional_paint_materials_cents"])
        )

        line["pdr_line_cents"] = pdr_line_cents
        line["conventional_line_cents"] = conventional_line_cents
        line["capped"] = capped
        line["routed_to"] = routed_to

        matrix_total += pdr_line_cents
        conventional_total += conventional_line_cents
        any_capped = any_capped or capped
        oversize_sum += line["oversize_dent_count"]

    vehicle["matrix_variant_total_cents"] = matrix_total
    vehicle["conventional_variant_total_cents"] = conventional_total
    vehicle["pdr_feasible"] = (not any_capped) and oversize_sum == 0


# =============================================================================
# repairability_triage
# =============================================================================
def repairability_triage(vehicle, agreement, force_conventional=False):
    """Returns (triage_disposition, approved_repair_cents)."""
    if vehicle["rental_required"] and agreement is not None:
        projected_rental_exposure_cents = (
            agreement["rental_cap_days"] * agreement["rental_daily_rate_cents"]
        )
    else:
        projected_rental_exposure_cents = 0

    matrix_total = vehicle["matrix_variant_total_cents"] or 0
    conventional_total = vehicle["conventional_variant_total_cents"] or 0

    if force_conventional or not vehicle["pdr_feasible"]:
        candidate = "CONVENTIONAL"
        candidate_cost = conventional_total
    elif matrix_total <= conventional_total:
        candidate = "PDR_REPAIR"
        candidate_cost = matrix_total
    else:
        candidate = "CONVENTIONAL"
        candidate_cost = conventional_total

    total_loss_floor_cents = round_half_up(TOTAL_LOSS_THRESHOLD_PCT * D(vehicle["acv_cents"]))
    if candidate_cost + projected_rental_exposure_cents >= total_loss_floor_cents:
        return "TOTAL_LOSS", 0
    return candidate, candidate_cost


# =============================================================================
# vehicle_net_billable
# =============================================================================
def recompute_net_billable(vehicle):
    agreement = db.rate_agreements.get(vehicle.get("pinned_rate_agreement_id"))
    if agreement is None:
        vehicle["admin_fee_cents"] = 0
        vehicle["gross_billable_cents"] = 0
        vehicle["discount_cents"] = 0
        vehicle["net_billable_cents"] = 0
        return

    # step 1
    repair_subtotal_cents = (
        vehicle["approved_repair_cents"]
        + aggregates.vehicle_approved_supplement_cents(vehicle["id"])
    )
    # step 2 — the fee is keyed on the subtotal
    admin_fee_cents = min(
        round_half_up(D(agreement["admin_fee_pct"]) * D(repair_subtotal_cents)),
        agreement["admin_fee_cap_cents"],
    )
    # step 3
    gross_billable_cents = repair_subtotal_cents + admin_fee_cents
    # step 4 — higher tier checked first, both comparisons inclusive
    if gross_billable_cents >= DISCOUNT_TIER_2_FLOOR_CENTS:
        volume_discount_pct = DISCOUNT_PCT_TIER_2
    elif gross_billable_cents >= DISCOUNT_TIER_1_FLOOR_CENTS:
        volume_discount_pct = DISCOUNT_PCT_TIER_1
    else:
        volume_discount_pct = DISCOUNT_PCT_TIER_0
    # step 5
    discount_cents = round_half_up(volume_discount_pct * D(gross_billable_cents))
    # step 6
    net_billable_cents = gross_billable_cents - discount_cents

    vehicle["admin_fee_cents"] = admin_fee_cents
    vehicle["gross_billable_cents"] = gross_billable_cents
    vehicle["discount_cents"] = discount_cents
    vehicle["net_billable_cents"] = net_billable_cents


# =============================================================================
# supplement_gate
# =============================================================================
def supplement_auto_approve_threshold_cents(vehicle, agreement):
    return max(
        SUPPLEMENT_AUTO_APPROVE_FLOOR_CENTS,
        round_half_up(
            D(agreement["supplement_auto_approve_pct"]) * D(vehicle["approved_repair_cents"])
        ),
    )


def supplement_cumulative_cap_cents(vehicle):
    return round_half_up(SUPPLEMENT_CUMULATIVE_CAP_PCT * D(vehicle["approved_repair_cents"]))


def supplement_cap_exceeded(vehicle, amount_under_test):
    already_approved = aggregates.vehicle_approved_supplement_cents(vehicle["id"])
    return already_approved + amount_under_test > supplement_cumulative_cap_cents(vehicle)


# =============================================================================
# crew_pay_split
# =============================================================================
def crew_pay_split(vehicle, tickets, pay_model):
    """Writes both pay variants onto every ticket in `tickets` (created_at ASC)."""
    vehicle_labor_pool_cents = round_half_up(LABOR_POOL_PCT * D(vehicle["approved_repair_cents"]))
    total_labor_units = sum(D(t["labor_units"]) for t in tickets)

    # --- VARIANT A: FLAT ---
    for ticket in tickets:
        if total_labor_units == 0:
            work_value_cents = 0
        else:
            work_value_cents = round_half_up(
                D(vehicle_labor_pool_cents) * D(ticket["labor_units"]) / total_labor_units
            )
        technician = db.technicians.get(ticket["technician_id"])
        split_pct = D(technician["flat_split_pct"]) if technician else D(0)
        ticket["payable_flat_cents"] = round_half_up(D(work_value_cents) * split_pct)

    # --- VARIANT B: POOLED ---
    pool_amount_cents = round_half_up(POOL_SPLIT_PCT * D(vehicle_labor_pool_cents))
    weights = []
    for ticket in tickets:
        technician = db.technicians.get(ticket["technician_id"])
        tier_weight = TIER_WEIGHT.get(technician["skill_tier"], D(0)) if technician else D(0)
        weights.append(D(ticket["labor_units"]) * tier_weight)
    total_weight = sum(weights, D(0))

    exact_shares = []
    for index, ticket in enumerate(tickets):
        if total_weight == 0:
            exact = D(0)
        else:
            exact = D(pool_amount_cents) * weights[index] / total_weight
        exact_shares.append(exact)
        ticket["payable_pooled_cents"] = round_half_up(exact)

    if tickets:
        residual = pool_amount_cents - sum(t["payable_pooled_cents"] for t in tickets)
        if residual != 0:
            winner_index = 0
            best_frac = None
            for index in range(len(tickets)):
                fraction = frac(exact_shares[index])
                if best_frac is None or fraction > best_frac:
                    best_frac = fraction
                    winner_index = index
            tickets[winner_index]["payable_pooled_cents"] += residual

    # --- selection ---
    for ticket in tickets:
        ticket["pay_model_applied"] = pay_model
        ticket["payable_cents"] = (
            ticket["payable_flat_cents"] if pay_model == "FLAT" else ticket["payable_pooled_cents"]
        )


# =============================================================================
# rental_exposure
# =============================================================================
def rental_exposure(vehicle, agreement):
    """Returns (rental_days_billed, shop_absorbed_rental_cents)."""
    if not vehicle["rental_required"]:
        return 0, 0
    opened = vehicle.get("rental_opened_at")
    closed = vehicle.get("rental_closed_at")
    if not opened or not closed:
        return 0, 0
    from clock import parse_instant

    opened_date = parse_instant(opened).date()
    closed_date = parse_instant(closed).date()
    rental_days_billed = max(1, (closed_date - opened_date).days)
    if agreement is None:
        return rental_days_billed, 0
    excess_days = max(0, rental_days_billed - agreement["rental_cap_days"])
    shop_absorbed_rental_cents = excess_days * agreement["rental_daily_rate_cents"]
    return rental_days_billed, shop_absorbed_rental_cents


# =============================================================================
# facility_throughput_projection
# =============================================================================
def facility_throughput_projection(facility):
    from services import posture as posture_service

    vehicles = aggregates.vehicles_of_facility(facility["id"])
    open_vehicle_count = sum(1 for v in vehicles if v["repair_status"] in OPEN_REPAIR_STATUSES)
    on_site_count = posture_service.on_site_technician_count(facility)
    daily_capacity = D(max(1, on_site_count)) * VEHICLES_PER_TECH_PER_DAY
    projected_days_to_clear = (
        0 if open_vehicle_count == 0 else ceil_int(D(open_vehicle_count) / daily_capacity)
    )
    return {
        "open_vehicle_count": open_vehicle_count,
        "on_site_technician_count": on_site_count,
        "projected_days_to_clear": projected_days_to_clear,
        "vehicles_in_repair": sum(1 for v in vehicles if v["repair_status"] == "IN_REPAIR"),
        "vehicles_ready": sum(1 for v in vehicles if v["repair_status"] == "READY"),
        "released_count": sum(
            1 for v in vehicles if v["repair_status"] in TERMINAL_REPAIR_STATUSES
        ),
    }
