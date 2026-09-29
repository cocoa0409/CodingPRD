"""The seventeen pinned calculations of section 1.3 / PRD section 3."""
from decimal import Decimal

import config
from numeric import D, q, rhu_int, floor_int

ZERO3 = Decimal("0.000")


# ---------------------------------------------------------------- design OLR
def design_olr_limit(thermal_regime):
    return config.DESIGN_OLR[thermal_regime]


# ------------------------------------------------------- organic loading rate
def delivery_derived(gross, tare, ts_pct, vs_pct_of_ts, haul_distance_km):
    net = q(D(gross) - D(tare), 3)
    vs = q(net * (D(ts_pct) / 100) * (D(vs_pct_of_ts) / 100), 3)
    haul = q(net * D(haul_distance_km), 2)
    return net, vs, haul


def organic_loading_rate(accepted_deliveries, digester_volume_m3):
    """round-then-sum: the per-delivery vs_tonnes are already rounded."""
    total_vs = sum((d["vs_tonnes"] for d in accepted_deliveries), Decimal("0"))
    day_vs_kg = total_vs * 1000
    return q(day_vs_kg / D(digester_volume_m3), 3)


# ------------------------------------------------ biological stability score
def biological_stability(avg_temp_c, excursion_minutes, vfa, alkalinity,
                         olr, target_temperature_c, design_max_olr):
    temp_delta = abs(D(avg_temp_c) - D(target_temperature_c))
    if temp_delta > config.THERMAL_CRITICAL_DELTA_C or \
            excursion_minutes > config.THERMAL_CRITICAL_MINUTES:
        thermal_status = "CRITICAL"
    elif temp_delta > config.THERMAL_BAND_DELTA_C or \
            excursion_minutes > config.THERMAL_BAND_MINUTES:
        thermal_status = "EXCURSION"
    else:
        thermal_status = "IN_BAND"

    ratio = q(D(vfa) / D(alkalinity), 3)
    if ratio >= config.VFA_ALK_SEVERE:
        vfa_points = 2
    elif ratio >= config.VFA_ALK_WARNING:
        vfa_points = 1
    else:
        vfa_points = 0

    dmo = D(design_max_olr)
    if D(olr) > dmo * config.OLR_SEVERE_MULTIPLE:
        olr_points = 2
    elif D(olr) > dmo:
        olr_points = 1
    else:
        olr_points = 0

    thermal_points = 2 if thermal_status == "CRITICAL" else (1 if thermal_status == "EXCURSION" else 0)
    stress_points = vfa_points + olr_points + thermal_points

    if stress_points >= config.INHIBITED_POINTS:
        stability_status = "INHIBITED"
    elif stress_points >= config.STRESSED_POINTS:
        stability_status = "STRESSED"
    else:
        stability_status = "STABLE"

    return thermal_status, ratio, stress_points, stability_status


def raw_gas_derived(raw_biogas_scf, raw_ch4_pct):
    hhv = q((D(raw_ch4_pct) / 100) * config.CH4_HHV_BTU_PER_SCF, 2)
    mmbtu = q(D(raw_biogas_scf) * hhv / Decimal("1000000"), 3)
    return hhv, mmbtu


# ------------------------------------------------------ gas conditioning yield
def gas_conditioning_yield(raw_biogas_scf, raw_ch4_pct, treated_ch4_pct,
                           treated_co2_pct, treated_h2s_ppm,
                           treated_moisture_lb_per_mmscf, interconnect):
    scf = q(D(raw_biogas_scf) * (D(raw_ch4_pct) / D(treated_ch4_pct))
            * (Decimal("1") - config.CONDITIONING_CH4_SLIP), 3)
    hhv = q((D(treated_ch4_pct) / 100) * config.CH4_HHV_BTU_PER_SCF, 2)

    if D(treated_h2s_ppm) > D(interconnect["max_h2s_ppm"]):
        offspec = "H2S"
    elif D(treated_moisture_lb_per_mmscf) > D(interconnect["max_moisture_lb_per_mmscf"]):
        offspec = "MOISTURE"
    elif D(treated_co2_pct) > D(interconnect["max_co2_pct"]):
        offspec = "CO2"
    elif hhv < D(interconnect["min_hhv_btu_per_scf"]):
        offspec = "HHV"
    else:
        offspec = None

    mmbtu = ZERO3 if offspec else q(scf * hhv / Decimal("1000000"), 3)
    return scf, hhv, offspec, mmbtu


# ----------------------------------------------------------- pathway CI score
def pathway_ci_score(pipeline_mmbtu, vs_by_baseline, haul_tonne_km, process_g_per_mj):
    energy_mj = q(D(pipeline_mmbtu) * config.MJ_PER_MMBTU, 3)

    avoided_ch4_kg = Decimal("0")
    for baseline, mcf in config.MCF.items():
        vs = D(vs_by_baseline.get(baseline, 0) or 0)
        avoided_ch4_kg += vs * 1000 * config.BMP_M3_CH4_PER_KG_VS * mcf * config.CH4_DENSITY_KG_PER_M3
    avoided_g = q(avoided_ch4_kg * config.GWP_CH4 * 1000, 3)

    if energy_mj == 0:
        raw_avoidance = Decimal("0.00")
        transport = Decimal("0.00")
    else:
        raw_avoidance = q(avoided_g / energy_mj, 2)
        transport = q(D(haul_tonne_km) * config.TRANSPORT_G_PER_TONNE_KM / energy_mj, 2)

    direct = q(D(process_g_per_mj) + transport, 2)
    credit = min(raw_avoidance, q(direct * config.AVOIDANCE_CREDIT_CAP_MULTIPLE, 2))
    return max(q(direct - credit, 2), config.CI_FLOOR)


# -------------------------------------------------------------- credit quantity
def credit_quantity(program, ci_score_used, delivered_mmbtu):
    """Returns (quantity Decimal(3dp), value_cents int)."""
    if program == "LCFS":
        energy_mj = D(delivered_mmbtu) * config.MJ_PER_MMBTU
        qty = q((config.LCFS_BENCHMARK_CI - D(ci_score_used)) * config.LCFS_EER
                * energy_mj / Decimal("1000000"), 3)
        value = rhu_int(qty * config.LCFS_CREDIT_PRICE_CENTS)
    else:
        whole = floor_int(D(delivered_mmbtu) * config.D3_RIN_PER_MMBTU)
        qty = q(whole, 3)
        value = rhu_int(D(whole) * config.D3_RIN_PRICE_CENTS)
    return qty, value


# ------------------------------------------------------------ digestate split
def digestate_separation(accepted_deliveries, solids_capture_pct, bedding_recovery_pct):
    feed = sum((d["net_tonnes"] for d in accepted_deliveries), Decimal("0"))
    total_solids = q(sum((d["net_tonnes"] * D(d["total_solids_pct"]) / 100
                          for d in accepted_deliveries), Decimal("0")), 2)
    solids = q(total_solids * (D(solids_capture_pct) / 100) / config.CAKE_DRY_MATTER_FRACTION, 3)
    liquid = q(feed - solids, 3)
    bedding = q(solids * (D(bedding_recovery_pct) / 100), 3)
    return solids, liquid, bedding


# --------------------------------------------------- plant available nitrogen
def liquid_availability_factor(pan_basis):
    if pan_basis == "LAB":
        return config.PAN_LAB_FACTOR
    return q(config.NH4_FRACTION * config.VOLATILIZATION_RETENTION
             + (Decimal("1") - config.NH4_FRACTION) * config.ORGANIC_MINERALIZATION, 4)


def plant_available_nitrogen(liquid_tonnes, solids_tonnes, lab_total_nitrogen_mg_per_l, pan_basis):
    lab_n = D(lab_total_nitrogen_mg_per_l) if lab_total_nitrogen_mg_per_l is not None else Decimal("0")
    liquid_n = q(D(liquid_tonnes) * lab_n / 1000, 3)
    solids_n = q(D(solids_tonnes) * config.SOLIDS_N_KG_PER_TONNE, 3)
    factor = liquid_availability_factor(pan_basis)
    pan = q(liquid_n * factor + solids_n * config.ORGANIC_MINERALIZATION, 3)
    return liquid_n, solids_n, pan


# ---------------------------------------------------------------- waterfall
def net_distributable_waterfall(gas_revenue_cents, credit_revenue_cents,
                                reserve_target_cents, reserve_balance_cents):
    gross = int(gas_revenue_cents) + int(credit_revenue_cents)
    if gross <= config.FEE_TIER_1_MAX_CENTS:
        rate = config.FEE_RATE_TIER_1
    elif gross <= config.FEE_TIER_2_MAX_CENTS:
        rate = config.FEE_RATE_TIER_2
    else:
        rate = config.FEE_RATE_TIER_3
    fee = rhu_int(D(gross) * rate)
    after_fee = gross - fee
    unfunded = max(int(reserve_target_cents) - int(reserve_balance_cents), 0)
    sweep = min(rhu_int(D(after_fee) * config.RESERVE_SWEEP_RATE), unfunded)
    net = after_fee - sweep
    return {
        "gross_revenue_cents": gross,
        "management_fee_rate": rate,
        "management_fee_cents": fee,
        "after_fee_cents": after_fee,
        "reserve_sweep_cents": sweep,
        "net_distributable_cents": net,
    }


# ------------------------------------------------------- dairy share allocation
def dairy_share_allocation(agreements, net_distributable_cents, gross_revenue_cents):
    """`agreements` must already be ordered committed DESC, created_at ASC."""
    exacts = []
    lines = []
    for a in agreements:
        base = net_distributable_cents if a["revenue_share_basis"] == "NET" else gross_revenue_cents
        exact = D(base) * D(a["revenue_share_pct"])
        floor_c = floor_int(exact)
        exacts.append(exact)
        lines.append({
            "agreement_id": a["id"],
            "dairy_id": a["dairy_id"],
            "revenue_share_basis": a["revenue_share_basis"],
            "revenue_share_pct": a["revenue_share_pct"],
            "committed_tonnes_per_day": a["committed_tonnes_per_day"],
            "floor_cents": floor_c,
            "residual_cents": 0,
            "share_cents": floor_c,
        })
    residual_pool = floor_int(sum(exacts, Decimal("0"))) - sum(l["floor_cents"] for l in lines)
    if residual_pool < 0:
        residual_pool = 0
    for i in range(min(residual_pool, len(lines))):
        lines[i]["residual_cents"] = 1
    for l in lines:
        l["share_cents"] = l["floor_cents"] + l["residual_cents"]
    total = sum(l["share_cents"] for l in lines)
    retained = net_distributable_cents - total
    return lines, total, retained


# ------------------------------------------------------------------ covenant
def dscr_value(after_fee_cents, annual_debt_service_cents):
    return q(D(after_fee_cents) * config.MONTHS_PER_YEAR / D(annual_debt_service_cents), 3)


def distribution_posture_for(dscr, dscr_minimum, posture_override_active):
    if D(dscr) >= D(dscr_minimum):
        return "OPEN"
    if D(dscr) >= D(dscr_minimum) - config.DSCR_RESTRICTED_BAND:
        return "RESTRICTED"
    return "RESTRICTED" if posture_override_active else "LOCKED"


# ------------------------------------------------------------- audit severity
def finding_severity(ci_delta):
    abs_delta = abs(D(ci_delta))
    if abs_delta == Decimal("0.00"):
        return "NONE"
    if abs_delta <= config.MATERIAL_CI_TOLERANCE:
        return "MINOR"
    return "MATERIAL"
