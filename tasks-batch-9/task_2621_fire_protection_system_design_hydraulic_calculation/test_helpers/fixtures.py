"""Composite setup builders and pytest fixtures.

The harness restarts the server before every test, so every fixture builds its
state from scratch through the documented endpoints. Identity-backed roles are
always threaded through the real backing row's id, because a design write is
compared against the project's lead_engineer_id and an authority write against
its ahj_reviewer_id.
"""
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient, api_client
from .test_users import (
    make_ahj_reviewer_headers,
    make_contractor_headers,
    make_design_engineer_headers,
    make_firm_admin_headers,
    make_qc_reviewer_headers,
)

ADMIN_HEADERS = make_firm_admin_headers()
CONTRACTOR_HEADERS = make_contractor_headers()

# The canonical FP-2601 pipeline. Hazard area HA-1 declares ORDINARY_2 over
# CLASS_IV stock stored 18 ft high, which escalates one position to EXTRA_1
# (0.300 gpm/sqft over 2500 sqft, 500.0 gpm hose), and the 36 ft ceiling earns
# one 0.02 density step, so the design demand settles at 1380.0 gpm.
HA1_DESIGN_DENSITY = 0.320
HA1_DESIGN_AREA_SQFT = 2500
HA1_HOSE_ALLOWANCE_GPM = 500.0
HC1_DESIGN_FLOW_GPM = 880.0
HC1_TOTAL_DEMAND_GPM = 1380.0
STANDPIPE_DEMAND_GPM = 750.0
PROJECT_TOTAL_DEMAND_GPM = 2130.0
HC1_REQUIRED_PSI = 50.54
HC1_REQUIRED_PSI_AT_DEMAND = 55.54
RAW_AVAILABLE_PSI = 65.54
LEAD_IN_LOSS_PSI = 5.0

# The chain that demonstrates HC-1: two feed segments and the supply connection.
CHAIN_ITERATION_1 = dict(
    iteration_index=1, pipe_size_in="2", length_ft=150, fitting_equivalent_ft=40,
    flow_gpm=110, elevation_change_ft=0,
)
CHAIN_ITERATION_2 = dict(
    iteration_index=2, pipe_size_in="4", length_ft=90, fitting_equivalent_ft=5,
    flow_gpm=420, elevation_change_ft=0,
)
CHAIN_SUPPLY_ITERATION = dict(
    iteration_index=3, pipe_size_in="6", length_ft=60, fitting_equivalent_ft=5,
    flow_gpm=880, elevation_change_ft=8, is_supply_connection=True,
)


def _data(response: Any) -> Dict[str, Any]:
    return get_success_data(response)


# --------------------------------------------------------------------------
# Directory builders
# --------------------------------------------------------------------------


def create_engineer(
    client: ApiClient,
    full_name: str = "Dana Ruiz",
    license_state: str = "TX",
    license_number: str = "PE-77120",
    license_status: Optional[str] = None,
    discipline: Optional[str] = None,
) -> Dict[str, Any]:
    payload = factories.build_engineer_payload(
        full_name=full_name,
        license_state=license_state,
        license_number=license_number,
        license_status=license_status,
        discipline=discipline,
    )
    return _data(client.create_engineer(payload, ADMIN_HEADERS))


def create_reviewer(
    client: ApiClient,
    full_name: str = "Marisol Vega",
    jurisdiction_code: str = "TX-AUS",
    discipline: Optional[str] = None,
) -> Dict[str, Any]:
    payload = factories.build_ahj_reviewer_payload(
        full_name=full_name,
        jurisdiction_code=jurisdiction_code,
        discipline=discipline,
    )
    return _data(client.create_ahj_reviewer(payload, ADMIN_HEADERS))


def create_project(
    client: ApiClient, lead_engineer_id: str, ahj_reviewer_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.build_project_payload(
        lead_engineer_id=lead_engineer_id,
        ahj_reviewer_id=ahj_reviewer_id,
        **overrides,
    )
    return _data(client.create_project(payload, ADMIN_HEADERS))


def read_project(client: ApiClient, project_id: str) -> Dict[str, Any]:
    return _data(client.get_project(project_id, ADMIN_HEADERS))


# --------------------------------------------------------------------------
# Design object builders
# --------------------------------------------------------------------------


def create_hazard_area(
    client: ApiClient, project_id: str, engineer_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.build_hazard_area_payload(project_id=project_id, **overrides)
    return _data(
        client.create_hazard_area(payload, make_design_engineer_headers(engineer_id))
    )


def create_auxiliary_system(
    client: ApiClient,
    project_id: str,
    engineer_id: str,
    system_type: str = "STANDPIPE_CLASS_I",
    **overrides: Any,
) -> Dict[str, Any]:
    overrides.setdefault("label", "Stair Standpipe Risers")
    if system_type in ("STANDPIPE_CLASS_I", "STANDPIPE_CLASS_II"):
        overrides.setdefault("riser_count", 2)
    payload = factories.build_auxiliary_system_payload(
        project_id=project_id, system_type=system_type, **overrides
    )
    return _data(
        client.create_auxiliary_system(
            payload, make_design_engineer_headers(engineer_id)
        )
    )


def create_flow_test(
    client: ApiClient, project_id: str, engineer_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.build_flow_test_payload(project_id=project_id, **overrides)
    return _data(
        client.create_flow_test(payload, make_design_engineer_headers(engineer_id))
    )


def create_calculation(
    client: ApiClient,
    project_id: str,
    hazard_area_id: str,
    engineer_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.build_hydraulic_calculation_payload(
        project_id=project_id, hazard_area_id=hazard_area_id, **overrides
    )
    return _data(
        client.create_hydraulic_calculation(
            payload, make_design_engineer_headers(engineer_id)
        )
    )


def append_iteration(
    client: ApiClient, calculation_id: str, engineer_id: str, **iteration: Any
) -> Dict[str, Any]:
    payload = factories.build_iteration_payload(**iteration)
    return _data(
        client.append_iteration(
            calculation_id, payload, make_design_engineer_headers(engineer_id)
        )
    )


def create_evaluation(
    client: ApiClient,
    project_id: str,
    flow_test_id: str,
    calculation_id: str,
    engineer_id: str,
    evaluation_basis: str = "RAW_TEST",
) -> Dict[str, Any]:
    payload = factories.build_water_supply_evaluation_payload(
        project_id=project_id,
        flow_test_id=flow_test_id,
        governing_hydraulic_calculation_id=calculation_id,
        evaluation_basis=evaluation_basis,
    )
    return _data(
        client.create_water_supply_evaluation(
            payload, make_design_engineer_headers(engineer_id)
        )
    )


def create_fire_pump(
    client: ApiClient,
    project_id: str,
    evaluation_id: str,
    evaluation_version: int,
    engineer_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.build_fire_pump_payload(
        project_id=project_id,
        water_supply_evaluation_id=evaluation_id,
        expected_water_supply_evaluation_version=evaluation_version,
        **overrides,
    )
    return _data(
        client.create_fire_pump(payload, make_design_engineer_headers(engineer_id))
    )


def qc_pass(
    client: ApiClient, calculation_id: str, reviewer_engineer_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.build_qc_review_payload(**overrides)
    return _data(
        client.qc_review_calculation(
            calculation_id, payload, make_qc_reviewer_headers(reviewer_engineer_id)
        )
    )


def seal(client: ApiClient, calculation_id: str, engineer_id: str) -> Dict[str, Any]:
    return _data(
        client.seal_calculation(calculation_id, make_design_engineer_headers(engineer_id))
    )


# --------------------------------------------------------------------------
# Coordination, package and acceptance builders
# --------------------------------------------------------------------------

CLEARANCE_BANDS = {
    "STRUCTURAL": (120.0, 132.0),
    "MECHANICAL": (132.0, 144.0),
    "LIGHTING": (108.0, 120.0),
}


def create_shop_drawing(
    client: ApiClient, project_id: str, calculation_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.build_shop_drawing_payload(
        project_id=project_id, hydraulic_calculation_id=calculation_id, **overrides
    )
    return _data(client.create_shop_drawing(payload, CONTRACTOR_HEADERS))


def open_clearance(
    client: ApiClient, shop_drawing_id: str, trade: str
) -> Dict[str, Any]:
    low, high = CLEARANCE_BANDS[trade]
    payload = factories.build_trade_clearance_payload(
        trade=trade, elevation_low_in=low, elevation_high_in=high
    )
    return _data(
        client.create_trade_clearance(shop_drawing_id, payload, CONTRACTOR_HEADERS)
    )


def record_clearance(
    client: ApiClient, clearance_id: str, engineer_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.build_record_clearance_payload(**overrides)
    return _data(
        client.record_trade_clearance(
            clearance_id, payload, make_design_engineer_headers(engineer_id)
        )
    )


def coordinate_sheet(
    client: ApiClient,
    project_id: str,
    calculation_id: str,
    engineer_id: str,
    trades: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a sheet over a sealed calculation and clear the named trades."""
    sheet = create_shop_drawing(client, project_id, calculation_id, **overrides)
    clearances = []
    for trade in trades if trades is not None else ["STRUCTURAL", "MECHANICAL", "LIGHTING"]:
        item = open_clearance(client, sheet["id"], trade)
        clearances.append(record_clearance(client, item["id"], engineer_id))
    return {"sheet": read_shop_drawing(client, sheet["id"]), "clearances": clearances}


def read_shop_drawing(client: ApiClient, shop_drawing_id: str) -> Dict[str, Any]:
    return _data(client.get_shop_drawing(shop_drawing_id, ADMIN_HEADERS))


def lodge_submittal(
    client: ApiClient,
    project_id: str,
    calculation_ids: List[str],
    engineer_id: str,
    expected_project_version: Optional[int] = None,
) -> Dict[str, Any]:
    if expected_project_version is None:
        expected_project_version = read_project(client, project_id)["version"]
    payload = factories.build_submittal_payload(
        project_id=project_id,
        included_calculation_ids=calculation_ids,
        expected_project_version=expected_project_version,
    )
    return _data(
        client.create_submittal(payload, make_design_engineer_headers(engineer_id))
    )


def begin_review(client: ApiClient, submittal_id: str, reviewer_id: str) -> Dict[str, Any]:
    return _data(
        client.begin_review(submittal_id, make_ahj_reviewer_headers(reviewer_id))
    )


def raise_comment(
    client: ApiClient, submittal_id: str, reviewer_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.build_review_comment_payload(**overrides)
    return _data(
        client.create_review_comment(
            submittal_id, payload, make_ahj_reviewer_headers(reviewer_id)
        )
    )


def complete_review(client: ApiClient, submittal_id: str, reviewer_id: str) -> Dict[str, Any]:
    return _data(
        client.complete_review(submittal_id, make_ahj_reviewer_headers(reviewer_id))
    )


def respond_to_comment(
    client: ApiClient, comment_id: str, engineer_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.build_comment_response_payload(**overrides)
    return _data(
        client.respond_to_review_comment(
            comment_id, payload, make_design_engineer_headers(engineer_id)
        )
    )


def close_comment(
    client: ApiClient, comment_id: str, reviewer_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.build_comment_close_payload(**overrides)
    return _data(
        client.close_review_comment(
            comment_id, payload, make_ahj_reviewer_headers(reviewer_id)
        )
    )


def open_acceptance_test(
    client: ApiClient, project_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.build_acceptance_test_payload(project_id=project_id, **overrides)
    return _data(client.create_acceptance_test(payload, CONTRACTOR_HEADERS))


def schedule_witness(
    client: ApiClient, acceptance_test_id: str, reviewer_id: str, start: str, end: str
) -> Dict[str, Any]:
    payload = factories.build_schedule_witness_payload(
        witness_window_start=start, witness_window_end=end
    )
    return _data(
        client.schedule_witness(
            acceptance_test_id, payload, make_ahj_reviewer_headers(reviewer_id)
        )
    )


def record_witness(
    client: ApiClient,
    acceptance_test_id: str,
    reviewer_id: str,
    measured_flow_gpm: float,
    measured_residual_psi: float,
) -> Dict[str, Any]:
    payload = factories.build_record_witness_payload(
        measured_flow_gpm=measured_flow_gpm, measured_residual_psi=measured_residual_psi
    )
    return _data(
        client.record_witness(
            acceptance_test_id, payload, make_ahj_reviewer_headers(reviewer_id)
        )
    )


# --------------------------------------------------------------------------
# The FP-2601 pipeline, staged
# --------------------------------------------------------------------------


def build_directory(client: ApiClient) -> Dict[str, Any]:
    """Two engineers and the assigned examiner."""
    lead = create_engineer(client)
    second = create_engineer(
        client, full_name="Sam Oyelaran", license_state="TX", license_number="PE-88431"
    )
    reviewer = create_reviewer(client)
    return {"lead_engineer": lead, "second_engineer": second, "reviewer": reviewer}


def build_project_stage(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Directory plus the open project FP-2601."""
    ctx = build_directory(client)
    ctx["project"] = create_project(
        client, ctx["lead_engineer"]["id"], ctx["reviewer"]["id"], **overrides
    )
    ctx["lead_id"] = ctx["lead_engineer"]["id"]
    ctx["second_id"] = ctx["second_engineer"]["id"]
    ctx["reviewer_id"] = ctx["reviewer"]["id"]
    ctx["project_id"] = ctx["project"]["id"]
    ctx["lead_headers"] = make_design_engineer_headers(ctx["lead_id"])
    ctx["qc_headers"] = make_qc_reviewer_headers(ctx["second_id"])
    ctx["reviewer_headers"] = make_ahj_reviewer_headers(ctx["reviewer_id"])
    return ctx


def build_design_stage(client: ApiClient) -> Dict[str, Any]:
    """Project plus hazard area HA-1, the two-riser standpipe and flow test H-14."""
    ctx = build_project_stage(client)
    ctx["hazard_area"] = create_hazard_area(client, ctx["project_id"], ctx["lead_id"])
    ctx["hazard_area_id"] = ctx["hazard_area"]["id"]
    ctx["standpipe"] = create_auxiliary_system(client, ctx["project_id"], ctx["lead_id"])
    ctx["flow_test"] = create_flow_test(client, ctx["project_id"], ctx["lead_id"])
    ctx["flow_test_id"] = ctx["flow_test"]["id"]
    return ctx


def build_iterating_stage(client: ApiClient) -> Dict[str, Any]:
    """HA-1 plus calculation HC-1 carrying the first two chain segments."""
    ctx = build_design_stage(client)
    ctx["calculation"] = create_calculation(
        client, ctx["project_id"], ctx["hazard_area_id"], ctx["lead_id"]
    )
    ctx["calculation_id"] = ctx["calculation"]["id"]
    ctx["iteration_1"] = append_iteration(
        client, ctx["calculation_id"], ctx["lead_id"], **CHAIN_ITERATION_1
    )
    ctx["iteration_2"] = append_iteration(
        client, ctx["calculation_id"], ctx["lead_id"], **CHAIN_ITERATION_2
    )
    return ctx


def build_converged_stage(client: ApiClient) -> Dict[str, Any]:
    """A preliminary evaluation, then the supply connection that converges HC-1."""
    ctx = build_iterating_stage(client)
    ctx["preliminary_evaluation"] = create_evaluation(
        client,
        ctx["project_id"],
        ctx["flow_test_id"],
        ctx["calculation_id"],
        ctx["lead_id"],
    )
    ctx["supply_iteration"] = append_iteration(
        client, ctx["calculation_id"], ctx["lead_id"], **CHAIN_SUPPLY_ITERATION
    )
    ctx["calculation"] = read_calculation(client, ctx["calculation_id"])
    return ctx


def build_evaluated_stage(client: ApiClient) -> Dict[str, Any]:
    """The final evaluation taken against the converged chain and the full ledger."""
    ctx = build_converged_stage(client)
    ctx["evaluation"] = create_evaluation(
        client,
        ctx["project_id"],
        ctx["flow_test_id"],
        ctx["calculation_id"],
        ctx["lead_id"],
    )
    ctx["evaluation_id"] = ctx["evaluation"]["id"]
    return ctx


def build_qc_passed_stage(client: ApiClient) -> Dict[str, Any]:
    ctx = build_evaluated_stage(client)
    ctx["calculation"] = qc_pass(client, ctx["calculation_id"], ctx["second_id"])
    return ctx


def build_sealed_stage(client: ApiClient) -> Dict[str, Any]:
    ctx = build_qc_passed_stage(client)
    ctx["calculation"] = seal(client, ctx["calculation_id"], ctx["lead_id"])
    return ctx


def build_coordinated_stage(client: ApiClient) -> Dict[str, Any]:
    """A sealed calculation drawn on sheet FP-101 with all three trades cleared."""
    ctx = build_sealed_stage(client)
    coordination = coordinate_sheet(
        client, ctx["project_id"], ctx["calculation_id"], ctx["lead_id"]
    )
    ctx["sheet"] = coordination["sheet"]
    ctx["sheet_id"] = coordination["sheet"]["id"]
    ctx["clearances"] = coordination["clearances"]
    return ctx


def build_submitted_stage(client: ApiClient) -> Dict[str, Any]:
    ctx = build_coordinated_stage(client)
    ctx["submittal"] = lodge_submittal(
        client, ctx["project_id"], [ctx["calculation_id"]], ctx["lead_id"]
    )
    ctx["submittal_id"] = ctx["submittal"]["id"]
    return ctx


def build_under_review_stage(client: ApiClient) -> Dict[str, Any]:
    ctx = build_submitted_stage(client)
    ctx["submittal"] = begin_review(client, ctx["submittal_id"], ctx["reviewer_id"])
    return ctx


def build_permitted_stage(client: ApiClient) -> Dict[str, Any]:
    """Review closes with no comments, so the package is approved and the sheet issued."""
    ctx = build_under_review_stage(client)
    ctx["submittal"] = complete_review(client, ctx["submittal_id"], ctx["reviewer_id"])
    ctx["sheet"] = read_shop_drawing(client, ctx["sheet_id"])
    ctx["project"] = read_project(client, ctx["project_id"])
    return ctx


def read_calculation(client: ApiClient, calculation_id: str) -> Dict[str, Any]:
    return _data(client.get_hydraulic_calculation(calculation_id, ADMIN_HEADERS))


def read_evaluation(client: ApiClient, evaluation_id: str) -> Dict[str, Any]:
    return _data(client.get_water_supply_evaluation(evaluation_id, ADMIN_HEADERS))


def read_auxiliary_system(client: ApiClient, system_id: str) -> Dict[str, Any]:
    return _data(client.get_auxiliary_system(system_id, ADMIN_HEADERS))


def read_hazard_area(client: ApiClient, hazard_area_id: str) -> Dict[str, Any]:
    return _data(client.get_hazard_area(hazard_area_id, ADMIN_HEADERS))


def read_submittal(client: ApiClient, submittal_id: str) -> Dict[str, Any]:
    return _data(client.get_submittal(submittal_id, ADMIN_HEADERS))


def read_comment(client: ApiClient, comment_id: str) -> Dict[str, Any]:
    return _data(client.get_review_comment(comment_id, ADMIN_HEADERS))


def read_acceptance_test(client: ApiClient, acceptance_test_id: str) -> Dict[str, Any]:
    return _data(client.get_acceptance_test(acceptance_test_id, ADMIN_HEADERS))


def read_fire_pump(client: ApiClient, fire_pump_id: str) -> Dict[str, Any]:
    return _data(client.get_fire_pump(fire_pump_id, ADMIN_HEADERS))


def read_trade_clearance(
    client: ApiClient, shop_drawing_id: str, clearance_id: str
) -> Dict[str, Any]:
    rows = _data(client.list_trade_clearances(shop_drawing_id, ADMIN_HEADERS))
    for row in rows:
        if row["id"] == clearance_id:
            return row
    raise AssertionError(f"clearance {clearance_id} not listed on sheet {shop_drawing_id}")


# --------------------------------------------------------------------------
# Pytest fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def client() -> ApiClient:
    return api_client


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    return dict(ADMIN_HEADERS)


@pytest.fixture
def contractor_headers() -> Dict[str, str]:
    return dict(CONTRACTOR_HEADERS)


@pytest.fixture
def directory(client: ApiClient) -> Dict[str, Any]:
    return build_directory(client)


@pytest.fixture
def project_ctx(client: ApiClient) -> Dict[str, Any]:
    return build_project_stage(client)


@pytest.fixture
def design_ctx(client: ApiClient) -> Dict[str, Any]:
    return build_design_stage(client)


@pytest.fixture
def iterating_ctx(client: ApiClient) -> Dict[str, Any]:
    return build_iterating_stage(client)


@pytest.fixture
def converged_ctx(client: ApiClient) -> Dict[str, Any]:
    return build_converged_stage(client)


@pytest.fixture
def evaluated_ctx(client: ApiClient) -> Dict[str, Any]:
    return build_evaluated_stage(client)


@pytest.fixture
def qc_passed_ctx(client: ApiClient) -> Dict[str, Any]:
    return build_qc_passed_stage(client)


@pytest.fixture
def sealed_ctx(client: ApiClient) -> Dict[str, Any]:
    return build_sealed_stage(client)


@pytest.fixture
def coordinated_ctx(client: ApiClient) -> Dict[str, Any]:
    return build_coordinated_stage(client)


@pytest.fixture
def submitted_ctx(client: ApiClient) -> Dict[str, Any]:
    return build_submitted_stage(client)


@pytest.fixture
def under_review_ctx(client: ApiClient) -> Dict[str, Any]:
    return build_under_review_stage(client)


@pytest.fixture
def permitted_ctx(client: ApiClient) -> Dict[str, Any]:
    return build_permitted_stage(client)
