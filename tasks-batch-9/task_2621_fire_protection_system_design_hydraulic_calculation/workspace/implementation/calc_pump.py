"""Fire pump selection and the sizing verdict (PRD 3.4)."""
from decimal import Decimal

from calc_supply import project_pressure
from errors import ApiError
from utils import _dec, ceil_div_steps, rhu

PUMP_CATALOGUE_GPM = [500, 750, 1000, 1250, 1500, 2000, 2500]
SIZING_VERDICTS = [
    "ACCEPTABLE",
    "INSUFFICIENT_SUCTION_AT_150_PCT",
    "REQUIRES_PRESSURE_RELIEF_VALVE",
    "INSUFFICIENT_AT_150_PCT",
]

PUMP_SAFETY_ALLOWANCE_PSI = Decimal("10.0")
CATALOGUE_PRESSURE_STEP_PSI = Decimal("5")
MIN_RATED_PRESSURE_PSI = 40
CHURN_FACTOR = Decimal("1.40")
OVERLOAD_FLOW_FACTOR = Decimal("1.5")
OVERLOAD_PRESSURE_FACTOR = Decimal("0.65")
MIN_SUCTION_PSI = Decimal("20.0")
MAX_CHURN_PSI = Decimal("175.0")


def select_rating(design_demand_gpm):
    """The smallest catalogue rating reaching the evaluated design demand."""
    demand = _dec(design_demand_gpm)
    for rating in PUMP_CATALOGUE_GPM:
        if _dec(rating) >= demand:
            return rating
    raise ApiError(
        "ERR_PUMP_CAPACITY_UNAVAILABLE",
        "No catalogue rating reaches the evaluated design demand.",
    )


def size(evaluation):
    rated_flow = select_rating(evaluation["design_demand_gpm"])
    static = evaluation["basis_static_psi"]
    residual = evaluation["basis_residual_psi"]
    test_flow = evaluation["basis_test_flow_gpm"]

    suction_at_rated = project_pressure(static, residual, test_flow, rated_flow)
    required_discharge = rhu(
        _dec(evaluation["required_psi_at_demand"]) + PUMP_SAFETY_ALLOWANCE_PSI, 2
    )
    steps = ceil_div_steps(
        _dec(required_discharge) - _dec(suction_at_rated), CATALOGUE_PRESSURE_STEP_PSI
    )
    rated_pressure = steps * int(CATALOGUE_PRESSURE_STEP_PSI)
    if rated_pressure < MIN_RATED_PRESSURE_PSI:
        rated_pressure = MIN_RATED_PRESSURE_PSI
    rated_pressure = float(rated_pressure)

    churn = rhu(_dec(rated_pressure) * CHURN_FACTOR + _dec(static), 1)
    flow_150 = rhu(_dec(rated_flow) * OVERLOAD_FLOW_FACTOR, 1)
    suction_at_150 = project_pressure(static, residual, test_flow, flow_150)
    available_at_150 = rhu(
        _dec(rated_pressure) * OVERLOAD_PRESSURE_FACTOR + _dec(suction_at_150), 2
    )

    if _dec(suction_at_150) < MIN_SUCTION_PSI:
        verdict = "INSUFFICIENT_SUCTION_AT_150_PCT"
    elif _dec(churn) > MAX_CHURN_PSI:
        verdict = "REQUIRES_PRESSURE_RELIEF_VALVE"
    elif _dec(available_at_150) < _dec(evaluation["required_psi_at_demand"]):
        verdict = "INSUFFICIENT_AT_150_PCT"
    else:
        verdict = "ACCEPTABLE"

    return {
        "rated_flow_gpm": float(rated_flow),
        "suction_psi_at_rated": suction_at_rated,
        "required_discharge_psi": required_discharge,
        "rated_pressure_psi": rated_pressure,
        "churn_discharge_psi": churn,
        "flow_150_pct_gpm": flow_150,
        "suction_psi_at_150_pct": suction_at_150,
        "available_psi_at_150_pct": available_at_150,
        "sizing_verdict": verdict,
    }
