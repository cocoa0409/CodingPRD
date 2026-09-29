"""Water supply projection, safety margin and the margin verdict (PRD 3.4)."""
from utils import _dec, rhu

EVALUATION_BASES = ["RAW_TEST", "SEASONAL_ADJUSTED"]
MARGIN_VERDICTS = ["ADEQUATE", "MARGINAL", "INADEQUATE_PUMP_REQUIRED"]

SEASONAL_PRESSURE_ALLOWANCE_PSI = 10.0
SEASONAL_FLOW_DERATE = 0.90
PROJECTION_EXPONENT = 1.85
ADEQUATE_MARGIN_PSI = 10.00
MARGINAL_MARGIN_PSI = 0.00
FLOW_TEST_VALIDITY_DAYS = 365


def basis_figures(flow_test, evaluation_basis):
    """The witnessed curve, raw or seasonally derated."""
    if evaluation_basis == "SEASONAL_ADJUSTED":
        return {
            "basis_static_psi": rhu(
                _dec(flow_test["static_psi"]) - _dec(SEASONAL_PRESSURE_ALLOWANCE_PSI), 2
            ),
            "basis_residual_psi": rhu(
                _dec(flow_test["residual_psi"]) - _dec(SEASONAL_PRESSURE_ALLOWANCE_PSI), 2
            ),
            "basis_test_flow_gpm": rhu(
                _dec(flow_test["flow_gpm"]) * _dec(SEASONAL_FLOW_DERATE), 1
            ),
        }
    return {
        "basis_static_psi": float(flow_test["static_psi"]),
        "basis_residual_psi": float(flow_test["residual_psi"]),
        "basis_test_flow_gpm": float(flow_test["flow_gpm"]),
    }


def project_pressure(basis_static_psi, basis_residual_psi, basis_test_flow_gpm, flow_gpm):
    """Pressure still available once `flow_gpm` is flowing, rounded to 2 places."""
    static = float(basis_static_psi)
    residual = float(basis_residual_psi)
    test_flow = float(basis_test_flow_gpm)
    if test_flow == 0:
        return rhu(static, 2)
    ratio = float(flow_gpm) / test_flow
    return rhu(static - (static - residual) * (ratio ** PROJECTION_EXPONENT), 2)


def margin_verdict(safety_margin_psi):
    """The three-way threshold, evaluated in order (PRD 3.4)."""
    margin = _dec(safety_margin_psi)
    if margin >= _dec(ADEQUATE_MARGIN_PSI):
        return "ADEQUATE"
    if margin >= _dec(MARGINAL_MARGIN_PSI):
        return "MARGINAL"
    return "INADEQUATE_PUMP_REQUIRED"


def evaluate(flow_test, calc, project, evaluation_basis):
    figures = basis_figures(flow_test, evaluation_basis)
    design_demand = rhu(
        _dec(calc["hazard_total_demand_gpm"]) + _dec(project["auxiliary_demand_gpm"]), 1
    )
    required = rhu(
        _dec(calc["required_psi_at_base_of_riser"])
        + _dec(project["underground_lead_in_loss_psi"]),
        2,
    )
    available = project_pressure(
        figures["basis_static_psi"],
        figures["basis_residual_psi"],
        figures["basis_test_flow_gpm"],
        design_demand,
    )
    margin = rhu(_dec(available) - _dec(required), 2)
    if _dec(available) == 0:
        margin_pct = 0.0
    else:
        margin_pct = rhu(_dec(margin) / _dec(available) * _dec(100), 1)
    figures.update(
        {
            "design_demand_gpm": design_demand,
            "required_psi_at_demand": required,
            "available_psi_at_demand": available,
            "safety_margin_psi": margin,
            "safety_margin_pct": margin_pct,
            "margin_verdict": margin_verdict(margin),
        }
    )
    return figures
