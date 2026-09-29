"""Pure calculation rules (PRD Section 2.7 precision + Section 3 formulas)."""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

D = Decimal

PI = D("3.141592653589793")

ZERO = D("0")


def q(value, places):
    exp = D(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def q2(value):
    return q(value, 2)


def q3(value):
    return q(value, 3)


def q4(value):
    return q(value, 4)


def floor_int(value):
    return D(value).to_integral_value(rounding=ROUND_FLOOR)


def ceil_to_tenth(value):
    return (D(value) * 10).to_integral_value(rounding=ROUND_CEILING) / D(10)


# --------------------------------------------------------------------------- #
# Injection rate cap and seal integrity
# --------------------------------------------------------------------------- #

SEAL_PASS_THRESHOLD = D("1.500")
SEAL_CONDITIONAL_THRESHOLD = D("1.000")


def max_injection_rate(model, requested_rate_tpy):
    """PRD 3.2 max_injection_rate."""
    allowable_buildup_psi = q2(D("0.90") * (model["fracture_pressure_psi"] - model["reservoir_pressure_psi"]))
    denom = D("45.0")
    max_rate = floor_int(
        allowable_buildup_psi * model["permeability_md"] * model["porosity_fraction"] * D(1000) / denom
    )
    if max_rate < 0:
        max_rate = D(0)
    effective = min(D(requested_rate_tpy), max_rate)
    return allowable_buildup_psi, max_rate, effective


def seal_integrity(model, effective_rate_tpy):
    """PRD 3.2 seal_integrity_index — returns (index, index_p10, classification)."""
    perm = model["permeability_md"]
    poro = model["porosity_fraction"]
    pressure_buildup_psi = q2(D("45.0") * D(effective_rate_tpy) / (perm * poro * D(1000)))

    if pressure_buildup_psi <= 0:
        index = D("0.000")
        index_p10 = D("0.000")
    else:
        capacity = model["capillary_entry_pressure_psi"] * (model["seal_thickness_m"] / D("30.0"))
        index = q3(capacity / (pressure_buildup_psi * D("1.0")))
        capacity_p10 = model["p10_capillary_entry_pressure_psi"] * (
            model["p10_seal_thickness_m"] / D("30.0")
        )
        index_p10 = q3(capacity_p10 / (pressure_buildup_psi * D("1.25")))

    governing = index_p10 if model.get("assessment_variant") == "PROBABILISTIC_P10" else index
    return index, index_p10, classify_seal(governing)


def classify_seal(index):
    if index >= SEAL_PASS_THRESHOLD:
        return "PASS"
    if index >= SEAL_CONDITIONAL_THRESHOLD:
        return "CONDITIONAL"
    return "FAIL"


def plume_and_aor(model, effective_rate_tpy, injection_years):
    """PRD 3.2 plume_and_aor_radii — returns (plume_km, front_km, aor_km)."""
    total_mass = D(effective_rate_tpy) * D(injection_years)
    pore_volume_m3 = total_mass * D("1000.0") / D("700.0")
    denom = PI * model["injection_zone_thickness_m"] * model["porosity_fraction"] * D("0.35")
    if denom <= 0 or pore_volume_m3 < 0:
        return D("0.000"), D("0.000"), D("0.0")
    swept_area_m2 = pore_volume_m3 / denom
    plume_km = q3(swept_area_m2.sqrt() / D("1000.0"))
    front_km = q3(plume_km * D("1.8"))
    aor_km = ceil_to_tenth(max(plume_km, front_km))
    return plume_km, front_km, aor_km


# --------------------------------------------------------------------------- #
# Legacy wellbores
# --------------------------------------------------------------------------- #

PLUG_FACTOR = {
    "OPEN_HOLE": D("1.00"),
    "PARTIALLY_PLUGGED": D("0.70"),
    "UNKNOWN": D("0.85"),
    "CEMENTED": D("0.25"),
}

CA_REQUIRED_RISK_THRESHOLD = D("40.00")
CA_WAIVER_RISK_CEILING = D("60.00")

IN_AOR_STATUSES = {"IDENTIFIED", "CA_REQUIRED", "CA_SCHEDULED", "CA_COMPLETE", "CA_WAIVED"}
CA_OBLIGATED_STATUSES = {"CA_REQUIRED", "CA_SCHEDULED", "CA_COMPLETE", "CA_WAIVED"}
CA_CLOSED_STATUSES = {"CA_COMPLETE", "CA_WAIVED"}
CA_COST_SCOPE_STATUSES = {"IDENTIFIED", "CA_REQUIRED", "CA_SCHEDULED"}


def wellbore_risk(wellbore, aor_radius_km):
    """PRD 3.3 legacy_wellbore_risk_score — returns (risk_score, ca_cost_estimate_usd)."""
    seal_factor = D("1.0") if wellbore["penetrates_seal"] else D("0.85")
    plug_factor = PLUG_FACTOR[wellbore["plug_condition"]]
    record_factor = D("0.60") if wellbore["plug_record_available"] else D("1.00")

    aor = D(aor_radius_km)
    if aor <= 0:
        proximity_factor = D("0.20")
    else:
        raw = D("1.0") - (wellbore["distance_from_injector_km"] / aor)
        proximity_factor = max(D("0.20"), min(D("1.00"), raw))

    risk_score = q2(
        D("100.0")
        * seal_factor
        * plug_factor
        * record_factor
        * (D("0.40") + D("0.60") * proximity_factor)
    )
    ca_cost = q2(D("150000.0") + D("120.0") * wellbore["total_depth_m"] + D("2000.0") * risk_score)
    return risk_score, ca_cost


def ca_completion_pct(wellbores):
    """PRD 3.3 corrective_action_completion_pct."""
    obligated = [w for w in wellbores if w["corrective_action_status"] in CA_OBLIGATED_STATUSES]
    if not obligated:
        return D("100.00")
    closed = [w for w in obligated if w["corrective_action_status"] in CA_CLOSED_STATUSES]
    return q2(D("100.0") * D(len(closed)) / D(len(obligated)))


# --------------------------------------------------------------------------- #
# Pore space
# --------------------------------------------------------------------------- #

CONSENT_HOLDER_STATUSES = {"EXECUTED", "UNITIZED"}


def tract_net_acreage(tract):
    return q4(tract["acreage"] * tract["ownership_pct"] / D("100.0"))


def tract_bonus_settlement(tract):
    bonus = tract.get("executed_bonus_per_acre_usd")
    if bonus is None:
        return D("0.00")
    return q2(D(tract["net_acreage"]) * D(bonus))


# --------------------------------------------------------------------------- #
# MRV coverage
# --------------------------------------------------------------------------- #

REF_FREQUENCY = {"SUBSURFACE": D("2"), "SURFACE": D("4"), "ATMOSPHERIC": D("12")}
DETECTION_REF = {"SUBSURFACE": D("1000.0"), "SURFACE": D("100.0"), "ATMOSPHERIC": D("25.0")}

DOMAIN_WEIGHTS = (
    ("SUBSURFACE", "subsurface_subscore", D("0.50")),
    ("SURFACE", "surface_subscore", D("0.30")),
    ("ATMOSPHERIC", "atmospheric_subscore", D("0.20")),
)

MRV_FULL_APPROVAL_THRESHOLD = D("85.00")
MRV_MINIMUM_COVERAGE = D("70.00")


def method_score(method):
    """PRD 3.7 mrv_coverage_score, per-method term."""
    domain = method["domain"]
    coverage_term = min(D("1.00"), method["spatial_coverage_pct"] / D("100.0"))
    frequency_term = min(D("1.00"), D(method["frequency_per_year"]) / REF_FREQUENCY[domain])
    detection_term = min(D("1.00"), DETECTION_REF[domain] / method["detection_threshold_tpy"])
    return q4(coverage_term * frequency_term * detection_term)


def plan_scores(methods):
    """Returns (subsurface, surface, atmospheric, coverage_score)."""
    subscores = {}
    for domain, _field, _weight in DOMAIN_WEIGHTS:
        total = sum(
            (m["method_score"] for m in methods if m["status"] == "ACTIVE" and m["domain"] == domain),
            D("0"),
        )
        subscores[domain] = q4(min(D("1.0000"), total))
    weighted = sum(
        (subscores[domain] * weight for domain, _field, weight in DOMAIN_WEIGHTS), D("0")
    )
    coverage = q2(D("100.0") * weighted)
    return (
        subscores["SUBSURFACE"],
        subscores["SURFACE"],
        subscores["ATMOSPHERIC"],
        coverage,
    )


# --------------------------------------------------------------------------- #
# Financial assurance
# --------------------------------------------------------------------------- #

PLUGGING_COST_PER_WELL = D("850000.0")
PLUGGING_SCOPE_STATUSES = {
    "SUBMITTED",
    "TECHNICAL_REVIEW",
    "REVISION_REQUESTED",
    "APPROVED",
    "ACTIVE",
    "SUSPENDED",
}
EMERGENCY_RESERVE_FLOOR = D("2000000.0")

BUCKET_ORDER = ("CORRECTIVE_ACTION", "PLUGGING", "PISC", "EMERGENCY")


def admin_fee(effective_rate_tpy):
    rate = D(effective_rate_tpy)
    if rate <= D("500000"):
        return D("250000.00")
    if rate <= D("1500000"):
        return D("500000.00")
    return D("900000.00")


def assurance_buckets(project, wellbores, permits, effective_rate_tpy):
    """PRD 3.7 required_financial_assurance — evaluated in the pinned order."""
    ca_cost_total = q2(
        sum(
            (
                w["ca_cost_estimate_usd"]
                for w in wellbores
                if w["corrective_action_status"] in CA_COST_SCOPE_STATUSES
            ),
            D("0"),
        )
    )
    pisc_cost = q2(D(project["pisc_duration_years"]) * D(project["effective_annual_monitoring_cost_usd"]))
    plugging_cost = q2(
        PLUGGING_COST_PER_WELL
        * D(len([p for p in permits if p["permit_status"] in PLUGGING_SCOPE_STATUSES]))
    )
    aor = D(project["aor_radius_km"])
    emergency_reserve = max(EMERGENCY_RESERVE_FLOOR, q2(D("500000.0") * PI * aor * aor))
    emergency_reserve = q2(emergency_reserve)
    fee = admin_fee(effective_rate_tpy)
    required = q2(ca_cost_total + pisc_cost + plugging_cost + emergency_reserve + fee)
    return {
        "ca_cost_total": ca_cost_total,
        "pisc_cost": pisc_cost,
        "plugging_cost": plugging_cost,
        "emergency_reserve": emergency_reserve,
        "admin_fee": fee,
        "required": required,
    }


def waterfall(face_amount_usd, buckets):
    """PRD 3.7 assurance_waterfall_allocation."""
    requirement = {
        "CORRECTIVE_ACTION": buckets["ca_cost_total"],
        "PLUGGING": buckets["plugging_cost"],
        "PISC": buckets["pisc_cost"],
        "EMERGENCY": q2(buckets["emergency_reserve"] + buckets["admin_fee"]),
    }
    remaining = q2(face_amount_usd)
    allocated = {}
    for bucket in BUCKET_ORDER:
        take = q2(min(remaining, requirement[bucket]))
        if take < 0:
            take = D("0.00")
        allocated[bucket] = take
        remaining = q2(remaining - take)
    return allocated, q2(remaining)


def coverage_status(allocated_usd, required_usd):
    allocated = D(allocated_usd)
    required = D(required_usd)
    if allocated <= 0:
        return "UNFUNDED"
    if allocated >= required:
        return "FUNDED"
    return "UNDERFUNDED"


# --------------------------------------------------------------------------- #
# Storage ledger and tax credits
# --------------------------------------------------------------------------- #


def net_stored(mass_injected_tonnes, measured_leakage_tonnes):
    return q3(D(mass_injected_tonnes) - D(measured_leakage_tonnes))


def cumulative_stored(records):
    accepted = [r for r in records if r["status"] == "ACCEPTED"]
    accepted.sort(key=lambda r: (r["period_start_dt"], r["created_at"], r["_seq"]))
    return q3(sum((r["net_stored_tonnes"] for r in accepted), D("0")))


CREDIT_TIER_1_CEILING = D("500000")
CREDIT_TIER_2_CEILING = D("2000000")


def credit_rate(cumulative_stored_tonnes):
    cumulative = D(cumulative_stored_tonnes)
    if cumulative <= CREDIT_TIER_1_CEILING:
        return D("85.00")
    if cumulative <= CREDIT_TIER_2_CEILING:
        return D("70.00")
    return D("55.00")


def claim_figures(records_in_window, lca_factor, cumulative_stored_tonnes, claim_variant):
    """PRD 3.9 tax_credit_amount."""
    reported = q3(sum((r["mass_injected_tonnes"] for r in records_in_window), D("0")))
    leakage = q3(sum((r["measured_leakage_tonnes"] for r in records_in_window), D("0")))
    lca_deduction = q3(reported * D(lca_factor))
    verified = q3(reported - leakage - lca_deduction)
    rate = credit_rate(cumulative_stored_tonnes)
    basis = reported if claim_variant == "REPORTED" else verified
    amount = q2(D(basis) * rate)
    return reported, verified, rate, amount


# --------------------------------------------------------------------------- #
# PISC
# --------------------------------------------------------------------------- #

PISC_DEFAULT_YEARS = 50
PISC_MIN_ALTERNATIVE_YEARS = 10
PISC_MAX_ALTERNATIVE_YEARS = 50


def pisc_duration(alternative_timeframe_years, seal_classification, best_plan_coverage_score):
    eligible = (
        alternative_timeframe_years is not None
        and seal_classification == "PASS"
        and D(best_plan_coverage_score) >= MRV_FULL_APPROVAL_THRESHOLD
    )
    if not eligible:
        return PISC_DEFAULT_YEARS
    return max(
        PISC_MIN_ALTERNATIVE_YEARS,
        min(PISC_MAX_ALTERNATIVE_YEARS, int(alternative_timeframe_years)),
    )


def pisc_elapsed_years(pisc_start_dt, now_dt):
    if pisc_start_dt is None:
        return D("0.000")
    seconds = D(str((now_dt - pisc_start_dt).total_seconds()))
    days = seconds / D("86400")
    return q3(days / D("365.25"))


# --------------------------------------------------------------------------- #
# Remediation
# --------------------------------------------------------------------------- #

EMERGENCY_DRAW_CAP_FRACTION = D("0.25")


def reserve_draw(severity, allocated_emergency_usd, required_financial_assurance_usd):
    if severity != "CRITICAL":
        return D("0.00")
    return q2(
        min(
            D(allocated_emergency_usd),
            EMERGENCY_DRAW_CAP_FRACTION * D(required_financial_assurance_usd),
        )
    )


# --------------------------------------------------------------------------- #
# Mechanical integrity
# --------------------------------------------------------------------------- #

ANNULUS_PRESSURE_LOSS_LIMIT_PSI = D("3.00")


def mit_verdict(test_type, annulus_pressure_loss_psi, anomaly_detected):
    if test_type == "ANNULUS_PRESSURE":
        return "PASS" if D(annulus_pressure_loss_psi) <= ANNULUS_PRESSURE_LOSS_LIMIT_PSI else "FAIL"
    return "FAIL" if anomaly_detected else "PASS"
