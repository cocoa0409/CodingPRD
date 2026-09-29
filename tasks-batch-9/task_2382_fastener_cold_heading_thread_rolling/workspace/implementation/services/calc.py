"""The eleven calculation families described in PRD section 3."""

from decimal import Decimal

from util import ceil_int, ceil_sqrt, dec, dsqrt, floor_int, rhu, rhu_int

D = Decimal


# --------------------------------------------------------------------------
# 1. wire draw reduction
# --------------------------------------------------------------------------

def reduction_pct(inlet_diameter_mm, outlet_diameter_mm):
    inlet = dec(inlet_diameter_mm)
    outlet = dec(outlet_diameter_mm)
    ratio = outlet / inlet
    return rhu((D(1) - ratio * ratio) * D(100), 2)


REDUCTION_MIN = D("8.0")
REDUCTION_MAX = D("35.0")
COATING_WEIGHT_MIN = D("2.0")


# --------------------------------------------------------------------------
# 2. wire mass ledger
# --------------------------------------------------------------------------

def required_reservation_kg(planned_pieces, blank_mass_g, scrap_allowance_pct):
    total = (
        dec(planned_pieces)
        * dec(blank_mass_g)
        * (D(1) + dec(scrap_allowance_pct))
        / D(1000)
    )
    return rhu(total, 3)


def consumed_kg(headed_count, heading_scrap_count, blank_mass_g):
    total = (dec(headed_count) + dec(heading_scrap_count)) * dec(blank_mass_g) / D(1000)
    return rhu(total, 3)


# --------------------------------------------------------------------------
# 3. tool effective life
# --------------------------------------------------------------------------

def refresh_tool_life(tool):
    """Recompute the derived life budgets and lifetime totals of a tool."""
    rated = dec(tool["rated_life_pieces"])
    regrinds = dec(tool["regrind_count"])
    tool["rated_derated_life_pieces"] = floor_int(rated * (D(1) - D("0.15") * regrinds))
    history = tool.get("cycle_pieces_history") or []
    if not tool.get("completed_cycle_count"):
        tool["observed_avg_cycle_pieces"] = None
        tool["conservative_life_pieces"] = tool["rated_derated_life_pieces"]
    else:
        total = sum(dec(x) for x in history)
        observed = rhu(total / dec(len(history)), 2)
        tool["observed_avg_cycle_pieces"] = observed
        tool["conservative_life_pieces"] = floor_int(
            min(dec(tool["rated_derated_life_pieces"]), observed * D("0.90"))
        )
    tool["lifetime_pieces"] = int(sum(int(x) for x in history)) + int(
        tool.get("cumulative_pieces_current_cycle") or 0
    )
    return tool


def life_budget(tool, qualification_program):
    if qualification_program == "AEROSPACE_NADCAP":
        return int(tool["conservative_life_pieces"])
    return int(tool["rated_derated_life_pieces"])


def heading_demand_pieces(planned_pieces, scrap_allowance_pct):
    return ceil_int(dec(planned_pieces) * (D(1) + dec(scrap_allowance_pct)))


def heading_allowance_pieces(planned_pieces, scrap_allowance_pct):
    return floor_int(dec(planned_pieces) * (D(1) + dec(scrap_allowance_pct)))


def tool_utilization_pct(cumulative_pieces, rated_derated_life_pieces):
    derated = dec(rated_derated_life_pieces)
    if derated == 0:
        return rhu(D(0), 2)
    return rhu(D(100) * dec(cumulative_pieces) / derated, 2)


# --------------------------------------------------------------------------
# 4. heat treat charge mass
# --------------------------------------------------------------------------

def charge_mass_kg(piece_count, blank_mass_g):
    return rhu(dec(piece_count) * dec(blank_mass_g) / D(1000), 3)


# --------------------------------------------------------------------------
# 5. heat treat metallurgy evaluation
# --------------------------------------------------------------------------

def total_decarb_depth_mm(surface_decarb_depth_mm, carbon_potential_pct):
    carbon_deficit = max(D(0), D("0.40") - dec(carbon_potential_pct))
    return rhu(dec(surface_decarb_depth_mm) * (D(1) + D("2.0") * carbon_deficit), 3)


def metallurgy_result(spec, core_hardness_hv, total_decarb):
    """Hardness is judged first, then decarburisation (order is pinned)."""
    hv = dec(core_hardness_hv)
    if hv < dec(spec["min_core_hardness_hv"]) or hv > dec(spec["max_core_hardness_hv"]):
        return "FAIL_HARDNESS"
    if dec(total_decarb) > dec(spec["max_decarb_depth_mm"]):
        return "FAIL_DECARB"
    return "PASS"


# --------------------------------------------------------------------------
# 6. hydrogen embrittlement relief bake compliance
# --------------------------------------------------------------------------

BAKE_DELAY_MAX_HOURS = D("4.0")
BAKE_TEMP_MIN = D("190")
BAKE_TEMP_MAX = D("230")


def bake_delay_hours(plated_at, now):
    seconds = dec((now - plated_at).total_seconds())
    return rhu(seconds / D(3600), 3)


def he_bake_required(plating_spec, strength_class):
    return plating_spec != "NONE" and strength_class in (
        "CLASS_10_9",
        "CLASS_12_9",
        "GRADE_8",
    )


def he_bake_min_minutes(plating_spec, strength_class):
    if not he_bake_required(plating_spec, strength_class):
        return 0
    if strength_class in ("CLASS_12_9", "GRADE_8"):
        return 480
    return 240


# --------------------------------------------------------------------------
# 7. lot sampling plan
# --------------------------------------------------------------------------

TIGHTENED_RISK_THRESHOLD = D("40.0")


def sampling_plan(severity, available_count):
    available = int(available_count)
    if severity == "TIGHTENED":
        sample_size = max(13, ceil_int(D("1.5") * dsqrt(max(available, 0))))
        acceptance_number = 0
    else:
        sample_size = max(8, ceil_sqrt(max(available, 0)))
        acceptance_number = 1 if sample_size >= 20 else 0
    return sample_size, acceptance_number


# --------------------------------------------------------------------------
# 8. lot release risk score
# --------------------------------------------------------------------------

def risk_score_pre_test(heat_cert_status, tool_util_pct, bake_required, delay_hours,
                        total_decarb, max_decarb):
    heat_term = D(0) if heat_cert_status == "VERIFIED" else D(25)
    tool_term = min(D(100), dec(tool_util_pct if tool_util_pct is not None else 0))
    if not bake_required or delay_hours is None:
        bake_term = D(0)
    else:
        delay = dec(delay_hours)
        if delay <= D("2.0"):
            bake_term = D(0)
        else:
            bake_term = min(D(100), (delay - D("2.0")) * D(40))
    if total_decarb is None or max_decarb is None or dec(max_decarb) == 0:
        decarb_term = D(0)
    else:
        decarb_term = min(
            D(100), rhu(D(100) * dec(total_decarb) / dec(max_decarb), 2)
        )
    raw = (
        D("0.30") * heat_term
        + D("0.20") * tool_term
        + D("0.25") * bake_term
        + D("0.25") * decarb_term
    )
    return rhu(raw, 2)


def risk_score_final(pre_test, total_failures):
    base = dec(pre_test if pre_test is not None else 0)
    return rhu(min(D(100), base + D("12.5") * dec(total_failures)), 2)


RISK_SCORE_CEILING = D("55.00")
AEROSPACE_TOOL_UTILIZATION_CEILING = D("80.00")


# --------------------------------------------------------------------------
# 9. certified strength class derivation
# --------------------------------------------------------------------------

STRENGTH_BANDS = {
    "CLASS_8_8": (D(242), D(318)),
    "CLASS_10_9": (D(304), D(361)),
    "CLASS_12_9": (D(366), D(414)),
    "GRADE_5": (D(241), D(302)),
    "GRADE_8": (D(321), D(352)),
}

SCAN_ORDER = ("CLASS_12_9", "CLASS_10_9", "GRADE_8", "CLASS_8_8", "GRADE_5")


def certified_strength_class(part_strength_class, min_measured_core_hardness_hv):
    hv = dec(min_measured_core_hardness_hv)
    own = STRENGTH_BANDS.get(part_strength_class)
    if own and own[0] <= hv <= own[1]:
        return part_strength_class
    for name in SCAN_ORDER:
        low, high = STRENGTH_BANDS[name]
        if low <= hv <= high:
            return name
    return "NONE"


# --------------------------------------------------------------------------
# 10. pack unit count reconciliation
# --------------------------------------------------------------------------

def count_tolerance_pieces(nominal_pack_count, count_tolerance_pct):
    return floor_int(dec(nominal_pack_count) * dec(count_tolerance_pct))


def declared_count(pack_mode, actual_count, net_weight_kg, pieces_per_kg):
    if pack_mode == "BY_COUNT":
        return int(actual_count)
    return rhu_int(dec(net_weight_kg) * dec(pieces_per_kg))


def load_mass_kg(piece_count, blank_mass_g):
    return charge_mass_kg(piece_count, blank_mass_g)
