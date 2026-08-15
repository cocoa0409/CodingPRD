"""Composite setup helpers — multi-step state builders used across the suite.

Every fixture builds its preconditions from scratch against an empty database
(the harness restarts the server before every test). Setup calls use the
lenient get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_budget_period_payload,
    create_case_payload,
    create_cost_center_payload,
    create_cost_model_payload,
    create_cost_model_refresh_payload,
    create_drg_payload,
    create_payer_contract_payload,
    create_physician_payload,
    create_service_line_payload,
)
from .test_users import TEST_USERS

FC = TEST_USERS["finance_controller_headers"]
CA = TEST_USERS["cost_analyst_headers"]
SLM = TEST_USERS["service_line_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation helpers
# ---------------------------------------------------------------------------

def create_service_line(**overrides):
    payload = create_service_line_payload(**overrides)
    return get_success_data(api_client.create_service_line(payload, FC))


def create_cost_center(**overrides):
    payload = create_cost_center_payload(**overrides)
    # PRD §2.6: a MINUTES center must not carry total_rvu; an RVU center must
    # not carry practical_capacity_minutes; a NONE center carries neither.
    # The factory's MINUTES-oriented default would otherwise leak into
    # RVU/NONE payloads built through this fixture.
    measure = payload.get("capacity_measure")
    if measure == "MINUTES":
        payload.pop("total_rvu", None)
    elif measure == "RVU":
        payload.pop("practical_capacity_minutes", None)
    elif measure == "NONE":
        payload.pop("practical_capacity_minutes", None)
        payload.pop("total_rvu", None)
    return get_success_data(api_client.create_cost_center(payload, FC))


def create_overhead_center(name="Periop Services", code="PERIOP", allocated_cost=7000.00, **overrides):
    kwargs = dict(
        name=name,
        code=code,
        cost_type="OVERHEAD",
        cost_behavior="FIXED",
        allocated_cost=allocated_cost,
        capacity_measure="NONE",
    )
    kwargs.pop("practical_capacity_minutes", None)
    kwargs.update(overrides)
    return create_cost_center(**kwargs)


def create_minutes_center(name="OR Minutes", code="ORMINS", allocated_cost=12000.00,
                          practical_capacity_minutes=8000, **overrides):
    kwargs = dict(
        name=name,
        code=code,
        cost_type="INDIRECT",
        cost_behavior="VARIABLE",
        allocated_cost=allocated_cost,
        capacity_measure="MINUTES",
        practical_capacity_minutes=practical_capacity_minutes,
    )
    kwargs.update(overrides)
    return create_cost_center(**kwargs)


def create_rvu_center(name, code, allocated_cost, total_rvu, **overrides):
    kwargs = dict(
        name=name,
        code=code,
        cost_type="INDIRECT",
        cost_behavior="VARIABLE",
        allocated_cost=allocated_cost,
        capacity_measure="RVU",
        total_rvu=total_rvu,
    )
    kwargs.pop("practical_capacity_minutes", None)
    kwargs.update(overrides)
    return create_cost_center(**kwargs)


def create_physician(**overrides):
    payload = create_physician_payload(**overrides)
    return get_success_data(api_client.create_physician(payload, FC))


def create_drg(**overrides):
    payload = create_drg_payload(**overrides)
    return get_success_data(api_client.create_drg(payload, FC))


def create_draft_cost_model(**overrides):
    payload = create_cost_model_payload(**overrides)
    return get_success_data(api_client.create_cost_model(payload, CA))


def create_active_cost_model(**overrides):
    """Create a DRAFT model then approve it ACTIVE. Returns (model, version)."""
    model = create_draft_cost_model(**overrides)
    approved = get_success_data(api_client.approve_cost_model(model["id"], FC))
    return approved, approved["version"]


def create_case(**overrides):
    payload = create_case_payload(**overrides)
    return get_success_data(api_client.create_case(payload, CA))


def add_activity_line(case_id, cost_center_id, quantity, **overrides):
    payload = {"cost_center_id": cost_center_id, "quantity": quantity}
    payload.update(overrides)
    return get_success_data(api_client.add_activity_line(case_id, payload, CA))


def add_implant(case_id, **overrides):
    from .factories import create_implant_payload
    payload = create_implant_payload(**overrides)
    return get_success_data(api_client.add_implant(case_id, payload, CA))


def add_supply_line(case_id, **overrides):
    from .factories import create_supply_line_payload
    payload = create_supply_line_payload(**overrides)
    return get_success_data(api_client.add_supply_line(case_id, payload, CA))


def post_case(case_id, expected_model_version):
    return get_success_data(
        api_client.post_case(case_id, {"expected_model_version": expected_model_version}, CA)
    )


def create_budget_period(**overrides):
    payload = create_budget_period_payload(**overrides)
    return get_success_data(api_client.create_budget_period(payload, FC))


def create_payer_contract(**overrides):
    payload = create_payer_contract_payload(**overrides)
    return get_success_data(api_client.create_payer_contract(payload, FC))


# ---------------------------------------------------------------------------
# Tier 2: domain scenario builders
# ---------------------------------------------------------------------------

def setup_ortho_tdabc(rate_factor=1.00, period="2026-08", model_effective_period="2026-01",
                      overhead_allocated=7000.00, minutes_allocated=12000.00,
                      minutes_capacity=8000, base_direct_cost=9000.00):
    """ORTHO service line + OR_MINS minutes center + PERIOP overhead + ACTIVE TDABC model
    + physician + DRG. Returns a dict of the created entities and the model version."""
    sl = create_service_line(
        name="Orthopedic Surgery", code="ORTHO",
        base_direct_cost=base_direct_cost, budgeted_volume=120,
    )
    cc_mins = create_minutes_center(allocated_cost=minutes_allocated,
                                    practical_capacity_minutes=minutes_capacity)
    cc_periop = create_overhead_center(allocated_cost=overhead_allocated)
    phys = create_physician(npi="1000000001", full_name="Dr. One", specialty="Orthopedics")
    drg = create_drg(drg_code="470", description="Major joint replacement",
                     target_cost=750.00, base_rate=30000.00)
    model, model_version = create_active_cost_model(
        name="ORTHO-TDABC", service_line_id=sl["id"], allocation_basis="TDABC",
        rate_factor=rate_factor, overhead_cost_center_id=cc_periop["id"],
        effective_period=model_effective_period,
    )
    return {
        "service_line": sl,
        "cc_minutes": cc_mins,
        "cc_overhead": cc_periop,
        "physician": phys,
        "drg": drg,
        "model": model,
        "model_version": model_version,
        "period": period,
    }


def setup_card_rvu(period="2026-08", with_budget_period=False, static_budget_amount=7000.00):
    """CARD service line + LAB (5000/2.0 RVU) + RAD (9000/3.0 RVU) + PERIOP overhead 7000
    + ACTIVE RVU model + physician + DRG 291. Optionally a BudgetPeriod for PERIOP/period."""
    sl = create_service_line(name="Cardiology", code="CARD",
                             base_direct_cost=10000.00, budgeted_volume=60)
    cc_lab = create_rvu_center(name="Laboratory", code="LAB",
                               allocated_cost=5000.00, total_rvu=2.0)
    cc_rad = create_rvu_center(name="Radiology", code="RAD",
                               allocated_cost=9000.00, total_rvu=3.0)
    cc_periop = create_overhead_center(allocated_cost=7000.00)
    phys = create_physician(npi="1000000002", full_name="Dr. Two", specialty="Cardiology")
    drg = create_drg(drg_code="291", description="Heart failure",
                     target_cost=30000.00, base_rate=30000.00)
    model, model_version = create_active_cost_model(
        name="CARD-RVU", service_line_id=sl["id"], allocation_basis="RVU",
        rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
        effective_period="2026-01",
    )
    result = {
        "service_line": sl,
        "cc_lab": cc_lab,
        "cc_rad": cc_rad,
        "cc_overhead": cc_periop,
        "physician": phys,
        "drg": drg,
        "model": model,
        "model_version": model_version,
        "period": period,
    }
    if with_budget_period:
        result["budget_period"] = create_budget_period(
            cost_center_id=cc_periop["id"], period=period,
            static_budget_amount=static_budget_amount,
        )
    return result


def setup_case_with_lines(scenario, quantities, center_key="cc_minutes", case_period=None,
                          expected_reimbursement=30000.00, physician=None, drg=None):
    """Create a DRAFT case under the scenario's model and attach one activity line per
    quantity in `quantities`. Returns the case dict (DRAFT)."""
    case = create_case(
        service_line_id=scenario["service_line"]["id"],
        physician_id=(physician or scenario["physician"])["id"],
        drg_id=(drg or scenario["drg"])["id"],
        cost_model_id=scenario["model"]["id"],
        period=case_period or scenario["period"],
        expected_reimbursement=expected_reimbursement,
    )
    for qty in quantities:
        add_activity_line(case["id"], scenario[center_key]["id"], qty)
    return case


def setup_posted_case(scenario, quantities, center_key="cc_minutes", **case_kwargs):
    """Create a case, attach activity lines, and post it. Returns the POSTED case."""
    case = setup_case_with_lines(scenario, quantities, center_key=center_key, **case_kwargs)
    return post_case(case["id"], scenario["model_version"])


def setup_posted_card_case(scenario, lab_qty=4, rad_qty=6, **case_kwargs):
    """CARD RVU scenario: one case with a LAB line and a RAD line, posted.
    Pre-overhead activity for the default quantities: 4*2500 + 6*3000 = 28000.00."""
    case = create_case(
        service_line_id=scenario["service_line"]["id"],
        physician_id=scenario["physician"]["id"],
        drg_id=scenario["drg"]["id"],
        cost_model_id=scenario["model"]["id"],
        period=case_kwargs.pop("case_period", None) or scenario["period"],
        expected_reimbursement=case_kwargs.pop("expected_reimbursement", 30000.00),
    )
    if lab_qty is not None:
        add_activity_line(case["id"], scenario["cc_lab"]["id"], lab_qty)
    if rad_qty is not None:
        add_activity_line(case["id"], scenario["cc_rad"]["id"], rad_qty)
    return post_case(case["id"], scenario["model_version"])


def propose_refresh(model_id, period, proposed_rates, data_quality_score=95.0):
    payload = create_cost_model_refresh_payload(
        model_id=model_id, period=period,
        proposed_rates=proposed_rates, data_quality_score=data_quality_score,
    )
    return get_success_data(api_client.create_cost_model_refresh(payload, CA))
