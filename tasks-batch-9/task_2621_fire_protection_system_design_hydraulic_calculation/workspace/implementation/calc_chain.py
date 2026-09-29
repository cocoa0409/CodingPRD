"""The pipe-sizing chain: Hazen-Williams friction and chain accumulation (PRD 3.3)."""
import db
from utils import _dec, rhu

PIPE_SIZES = ["1", "1.25", "1.5", "2", "2.5", "3", "4", "6", "8"]

# Schedule 40 internal diameter, inches
INTERNAL_DIAMETER_IN = {
    "1": 1.049,
    "1.25": 1.380,
    "1.5": 1.610,
    "2": 2.067,
    "2.5": 2.469,
    "3": 3.068,
    "4": 4.026,
    "6": 6.065,
    "8": 7.981,
}

HW_COEFFICIENT = 4.52
HW_ROUGHNESS_C = 120.0
HW_FLOW_EXPONENT = 1.85
HW_DIAMETER_EXPONENT = 4.87
ELEVATION_HEAD_PSI_PER_FT = 0.433
VELOCITY_COEFFICIENT = 0.4085
VELOCITY_LIMIT_FPS = 32.00


def friction_loss_psi(pipe_size_in, flow_gpm, length_ft, fitting_equivalent_ft):
    diameter = INTERNAL_DIAMETER_IN[pipe_size_in]
    numerator = HW_COEFFICIENT * (float(flow_gpm) ** HW_FLOW_EXPONENT)
    denominator = (HW_ROUGHNESS_C ** HW_FLOW_EXPONENT) * (diameter ** HW_DIAMETER_EXPONENT)
    total_length = float(length_ft) + float(fitting_equivalent_ft)
    return rhu(numerator / denominator * total_length, 2)


def elevation_loss_psi(elevation_change_ft):
    return rhu(float(elevation_change_ft) * ELEVATION_HEAD_PSI_PER_FT, 2)


def velocity_fps(pipe_size_in, flow_gpm):
    diameter = INTERNAL_DIAMETER_IN[pipe_size_in]
    return rhu(VELOCITY_COEFFICIENT * float(flow_gpm) / (diameter * diameter), 2)


def iterations_of(calculation_id):
    rows = [
        row
        for row in db.iterations.values()
        if row["hydraulic_calculation_id"] == calculation_id
    ]
    return sorted(rows, key=lambda row: row["iteration_index"])


def recompute_chain(calc):
    """Re-derive in_active_chain, cumulative_psi_after and the chain summary.

    The running pressure starts at end_head_psi; each segment's already-rounded
    friction and elevation losses are added and the running total is rounded
    again to 2 decimal places after every segment (PRD 2.6, 3.3).
    """
    rows = iterations_of(calc["id"])
    start = calc.get("chain_start_index", 1)
    active = []
    for row in rows:
        row["in_active_chain"] = row["iteration_index"] >= start
        if row["in_active_chain"]:
            active.append(row)
    if not active:
        calc["end_head_psi"] = 0.0
        calc["iteration_count"] = 0
        calc["required_psi_at_base_of_riser"] = 0.0
        return
    quotient = float(active[0]["flow_gpm"]) / float(calc["k_factor"])
    calc["end_head_psi"] = rhu(quotient * quotient, 2)
    running = _dec(calc["end_head_psi"])
    for row in active:
        running = _dec(
            rhu(running + _dec(row["friction_loss_psi"]) + _dec(row["elevation_loss_psi"]), 2)
        )
        row["cumulative_psi_after"] = float(running)
    calc["iteration_count"] = len(active)
    calc["required_psi_at_base_of_riser"] = active[-1]["cumulative_psi_after"]
