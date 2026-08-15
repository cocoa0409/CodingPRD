"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. Tests are responsible for their own assertions.

Common chains:
- setup_approved_acidified_formula: customer + ACIDIFIED formula with pepper
  (CUSTOMER_SUPPLIED 0.5/unit, 5000 consigned) and vinegar (COPACKER_SUPPLIED
  0.8/unit @300), trial passed, letter rev1 (4.2 / 0.9) ACTIVE -> APPROVED.
- setup_approved_acid_formula: ACID formula auto-approved by a passed trial
  (no letter required).
- create_run / confirm_run / complete_run drive the production lifecycle.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_formula_payload,
    create_ingredient_supply_payload,
    create_kettle_line_payload,
    create_label_approval_payload,
    create_letter_payload,
    create_packaging_component_payload,
    create_pilot_cell_payload,
    create_production_run_payload,
    create_quality_hold_payload,
    create_scale_up_trial_payload,
)
from .test_users import TEST_USERS, make_qa_reviewer_headers

OPS = TEST_USERS["ops_admin_headers"]
QA = TEST_USERS["qa_reviewer_headers"]
PA = TEST_USERS["process_authority_headers"]


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {step}: {exc}")


# ---------------------------------------------------------------------------
# Tier 0 — single-endpoint creators/readers
# ---------------------------------------------------------------------------

def create_customer(**overrides):
    resp = api_client.create_customer(create_customer_payload(**overrides), OPS)
    return _ok("create_customer", resp)


def get_customer(customer_id):
    return _ok("get_customer", api_client.get_customer(customer_id, OPS))


def create_formula(customer_id, **overrides):
    resp = api_client.create_formula(create_formula_payload(customer_id, **overrides), OPS)
    return _ok("create_formula", resp)


def get_formula(formula_id):
    return _ok("get_formula", api_client.get_formula(formula_id, OPS))


def add_ingredient_supply(formula_id, **overrides):
    resp = api_client.create_ingredient_supply(
        create_ingredient_supply_payload(formula_id, **overrides), OPS
    )
    return _ok("add_ingredient_supply", resp)


def get_ingredient_supply(supply_id):
    return _ok("get_ingredient_supply", api_client.get_ingredient_supply(supply_id, OPS))


def receive_consignment(supply_id, quantity):
    resp = api_client.receive_ingredient_supply(supply_id, {"quantity": quantity}, OPS)
    return _ok("receive_consignment", resp)


def create_pilot_cell(**overrides):
    resp = api_client.create_pilot_cell(create_pilot_cell_payload(**overrides), OPS)
    return _ok("create_pilot_cell", resp)


def schedule_trial(formula_id, pilot_cell_id, **overrides):
    resp = api_client.create_scale_up_trial(
        create_scale_up_trial_payload(formula_id, pilot_cell_id, **overrides), OPS
    )
    return _ok("schedule_trial", resp)


def record_trial_results(trial_id, passed=True, yield_units=480):
    resp = api_client.record_trial_results(
        trial_id, {"passed": passed, "yield_units": yield_units}, OPS
    )
    return _ok("record_trial_results", resp)


def cancel_trial(trial_id):
    return _ok("cancel_trial", api_client.cancel_trial(trial_id, OPS))


def create_letter(formula_id, **overrides):
    resp = api_client.create_process_authority_letter(
        create_letter_payload(formula_id, **overrides), PA
    )
    return _ok("create_letter", resp)


def activate_letter(letter_id):
    resp = api_client.activate_process_authority_letter(letter_id, PA)
    return _ok("activate_letter", resp)


def get_letter(letter_id):
    return _ok("get_letter", api_client.get_process_authority_letter(letter_id, PA))


def create_kettle_line(**overrides):
    resp = api_client.create_kettle_line(create_kettle_line_payload(**overrides), OPS)
    return _ok("create_kettle_line", resp)


def create_packaging_component(**overrides):
    resp = api_client.create_packaging_component(
        create_packaging_component_payload(**overrides), OPS
    )
    return _ok("create_packaging_component", resp)


def get_packaging_component(component_id):
    return _ok(
        "get_packaging_component", api_client.get_packaging_component(component_id, OPS)
    )


def create_run(formula_id, kettle_line_id, **overrides):
    resp = api_client.create_production_run(
        create_production_run_payload(formula_id, kettle_line_id, **overrides), OPS
    )
    return _ok("create_run", resp)


def get_run(run_id):
    return _ok("get_run", api_client.get_production_run(run_id, OPS))


def confirm_run(run_id):
    return _ok("confirm_run", api_client.confirm_production_run(run_id, OPS))


def complete_run(run_id, actual_units_produced, measured_ph, measured_water_activity):
    resp = api_client.complete_production_run(
        run_id,
        {
            "actual_units_produced": actual_units_produced,
            "measured_ph": measured_ph,
            "measured_water_activity": measured_water_activity,
        },
        OPS,
    )
    return _ok("complete_run", resp)


def cancel_run(run_id):
    return _ok("cancel_run", api_client.cancel_production_run(run_id, OPS))


def release_run(run_id):
    return _ok("release_run", api_client.release_production_run(run_id, QA))


def create_label(formula_id, **overrides):
    resp = api_client.create_label_approval(
        create_label_approval_payload(formula_id, **overrides), OPS
    )
    return _ok("create_label", resp)


def submit_label(label_id):
    return _ok("submit_label", api_client.submit_label_approval(label_id, OPS))


def review_label(label_id, approved=True):
    resp = api_client.review_label_approval(label_id, {"approved": approved}, QA)
    return _ok("review_label", resp)


def get_label(label_id):
    return _ok("get_label", api_client.get_label_approval(label_id, OPS))


def create_approved_label(formula_id, allergen_declaration="NONE", **overrides):
    label = create_label(formula_id, allergen_declaration=allergen_declaration, **overrides)
    submit_label(label["id"])
    return review_label(label["id"], approved=True)


def create_manual_hold(run_id, qa_user_id="qa-7", **overrides):
    resp = api_client.create_quality_hold(
        create_quality_hold_payload(run_id, **overrides),
        make_qa_reviewer_headers(qa_user_id),
    )
    return _ok("create_manual_hold", resp)


def get_hold(hold_id):
    return _ok("get_hold", api_client.get_quality_hold(hold_id, QA))


def list_run_holds(run_id):
    """Return (data_list, meta) for GET /copack/quality-holds?production_run_id=."""
    from prd_bench_local_runner.testing import validate_paginated

    resp = api_client.list_quality_holds(QA, params={"production_run_id": run_id})
    return validate_paginated(resp)


# ---------------------------------------------------------------------------
# Tier 1 — formula progression chains
# ---------------------------------------------------------------------------

def setup_approved_acidified_formula(
    disposition_owner="CUSTOMER",
    credit_limit_cents=100_000_000,
    with_supplies=True,
    with_label=False,
):
    """Customer + ACIDIFIED formula (allergen NONE, min_run 1000, rate 120)
    with pepper CUSTOMER_SUPPLIED 0.5/unit (5000 consigned) and vinegar
    COPACKER_SUPPLIED 0.8/unit @300, a passed trial, and a revision-1 letter
    (max_ph 4.2, max_water_activity 0.9) ACTIVE -> formula APPROVED.

    Returns a context dict: customer, formula, pepper, vinegar, cell, trial,
    letter, and optionally label.
    """
    ctx = {}
    ctx["customer"] = create_customer(
        credit_limit_cents=credit_limit_cents,
        default_disposition_owner=disposition_owner,
    )
    ctx["formula"] = create_formula(ctx["customer"]["id"])
    if with_supplies:
        ctx["pepper"] = add_ingredient_supply(
            ctx["formula"]["id"],
            ingredient_name="Ghost pepper mash",
            sourcing_mode="CUSTOMER_SUPPLIED",
            quantity_per_unit=0.5,
        )
        ctx["vinegar"] = add_ingredient_supply(
            ctx["formula"]["id"],
            ingredient_name="White vinegar",
            sourcing_mode="COPACKER_SUPPLIED",
            quantity_per_unit=0.8,
            unit_cost_cents=300,
        )
        receive_consignment(ctx["pepper"]["id"], 5000)
    ctx["cell"] = create_pilot_cell()
    ctx["trial"] = schedule_trial(ctx["formula"]["id"], ctx["cell"]["id"])
    record_trial_results(ctx["trial"]["id"], passed=True, yield_units=480)
    ctx["letter"] = create_letter(ctx["formula"]["id"], formula_revision=1)
    activate_letter(ctx["letter"]["id"])
    ctx["letter"] = get_letter(ctx["letter"]["id"])
    ctx["formula"] = get_formula(ctx["formula"]["id"])
    assert ctx["formula"]["status"] == "APPROVED", (
        f"Setup failed: formula should be APPROVED, got {ctx['formula']['status']}"
    )
    if with_label:
        ctx["label"] = create_approved_label(ctx["formula"]["id"])
    return ctx


def setup_approved_acid_formula(
    customer_id,
    cell_id,
    supplies=None,
    trial_start="2026-09-02T08:00:00Z",
    trial_end="2026-09-02T10:00:00Z",
    batch_size_units=300,
    yield_units=290,
    **formula_overrides,
):
    """ACID formula auto-approved by a passed trial (letter-exempt).

    `supplies` is a list of add_ingredient_supply kwargs applied while the
    formula is DRAFT. Returns the freshly read formula (status APPROVED).
    """
    formula = create_formula(customer_id, process_category="ACID", **formula_overrides)
    for supply_kwargs in (supplies or []):
        add_ingredient_supply(formula["id"], **supply_kwargs)
    trial = schedule_trial(
        formula["id"],
        cell_id,
        batch_size_units=batch_size_units,
        scheduled_start=trial_start,
        scheduled_end=trial_end,
    )
    record_trial_results(trial["id"], passed=True, yield_units=yield_units)
    formula = get_formula(formula["id"])
    assert formula["status"] == "APPROVED", (
        f"Setup failed: ACID formula should auto-approve, got {formula['status']}"
    )
    return formula


def setup_trial_passed_formula(disposition_owner="CUSTOMER"):
    """ACIDIFIED formula advanced to TRIAL_PASSED with a letter created but
    NOT activated. Returns ctx with customer, formula, cell, trial, letter."""
    ctx = {}
    ctx["customer"] = create_customer(default_disposition_owner=disposition_owner)
    ctx["formula"] = create_formula(ctx["customer"]["id"])
    ctx["cell"] = create_pilot_cell()
    ctx["trial"] = schedule_trial(ctx["formula"]["id"], ctx["cell"]["id"])
    record_trial_results(ctx["trial"]["id"], passed=True, yield_units=480)
    ctx["formula"] = get_formula(ctx["formula"]["id"])
    assert ctx["formula"]["status"] == "TRIAL_PASSED", (
        f"Setup failed: expected TRIAL_PASSED, got {ctx['formula']['status']}"
    )
    ctx["letter"] = create_letter(ctx["formula"]["id"], formula_revision=1)
    return ctx


# ---------------------------------------------------------------------------
# Tier 2 — production resources and runs on the approved chain
# ---------------------------------------------------------------------------

def add_kettle_and_components(ctx, with_bottle=True, with_cap=True):
    ctx["kettle"] = create_kettle_line()
    if with_bottle:
        ctx["bottle"] = create_packaging_component(
            component_name="12oz woozy bottle",
            component_type="BOTTLE",
            unit_cost_cents=50,
            initial_on_hand_units=100_000,
        )
    if with_cap:
        ctx["cap"] = create_packaging_component(
            component_name="38mm cap",
            component_type="CAP",
            unit_cost_cents=12,
            initial_on_hand_units=100_000,
        )
    return ctx


def bottle_cap_requirements(ctx):
    return [
        {"component_id": ctx["bottle"]["id"], "quantity_per_unit": 1},
        {"component_id": ctx["cap"]["id"], "quantity_per_unit": 1},
    ]


def bottle_only_requirements(ctx):
    return [{"component_id": ctx["bottle"]["id"], "quantity_per_unit": 1}]


def setup_confirmed_run(
    planned_units=2000,
    packaging="bottle_cap",
    run_start="2026-09-10T08:00:00Z",
    run_end="2026-09-10T16:00:00Z",
    with_label=False,
    disposition_owner="CUSTOMER",
    credit_limit_cents=100_000_000,
):
    """Approved ACIDIFIED chain + kettle + bottle/cap + a CONFIRMED run.

    packaging: "bottle_cap" | "bottle" | None.
    Returns ctx with customer, formula, pepper, vinegar, letter, kettle,
    bottle, cap, run (all freshly read where relevant).
    """
    ctx = setup_approved_acidified_formula(
        disposition_owner=disposition_owner,
        credit_limit_cents=credit_limit_cents,
        with_label=with_label,
    )
    add_kettle_and_components(ctx)
    requirements = None
    if packaging == "bottle_cap":
        requirements = bottle_cap_requirements(ctx)
    elif packaging == "bottle":
        requirements = bottle_only_requirements(ctx)
    elif packaging is None:
        requirements = []
    ctx["run"] = create_run(
        ctx["formula"]["id"],
        ctx["kettle"]["id"],
        planned_units=planned_units,
        scheduled_start=run_start,
        scheduled_end=run_end,
        packaging_requirements=requirements,
    )
    confirm_run(ctx["run"]["id"])
    ctx["run"] = get_run(ctx["run"]["id"])
    assert ctx["run"]["status"] == "CONFIRMED", (
        f"Setup failed: run should be CONFIRMED, got {ctx['run']['status']}"
    )
    return ctx


def setup_run_on_hold(
    actual_units_produced=2000,
    measured_ph=4.5,
    measured_water_activity=0.88,
    disposition_owner="CUSTOMER",
    with_label=False,
):
    """Confirmed run completed with deviating measurements -> ON_HOLD with an
    automatic hold. Returns ctx extended with hold."""
    ctx = setup_confirmed_run(
        packaging="bottle_cap",
        with_label=with_label,
        disposition_owner=disposition_owner,
    )
    complete_run(
        ctx["run"]["id"], actual_units_produced, measured_ph, measured_water_activity
    )
    ctx["run"] = get_run(ctx["run"]["id"])
    assert ctx["run"]["status"] == "ON_HOLD", (
        f"Setup failed: run should be ON_HOLD, got {ctx['run']['status']}"
    )
    holds, _meta = list_run_holds(ctx["run"]["id"])
    assert len(holds) == 1, f"Setup failed: expected 1 auto-hold, got {len(holds)}"
    ctx["hold"] = holds[0]
    return ctx


def setup_completed_clean_run(with_label=False, disposition_owner="CUSTOMER"):
    """Confirmed run completed within letter limits -> COMPLETED, no holds."""
    ctx = setup_confirmed_run(
        packaging="bottle_cap", with_label=with_label, disposition_owner=disposition_owner
    )
    complete_run(ctx["run"]["id"], 2000, 4.1, 0.88)
    ctx["run"] = get_run(ctx["run"]["id"])
    assert ctx["run"]["status"] == "COMPLETED", (
        f"Setup failed: run should be COMPLETED, got {ctx['run']['status']}"
    )
    return ctx


def setup_nut_and_none_formulas():
    """One customer with two APPROVED formulas on one shared pilot cell and
    one kettle line: f_nut (ACID, NUT, min 500, rate 200, salt COPACKER
    0.1/unit @50, auto-approved) and f_none (ACIDIFIED, NONE, min 1000,
    rate 120, pepper consigned 5000 + vinegar 0.8 @300, letter-approved).
    Returns ctx with customer, cell, kettle, f_nut, f_none_ctx."""
    ctx = {}
    ctx["customer"] = create_customer()
    ctx["cell"] = create_pilot_cell()
    ctx["f_nut"] = setup_approved_acid_formula(
        ctx["customer"]["id"],
        ctx["cell"]["id"],
        product_name="Nut Pesto",
        sku_code="NP-001",
        allergen_class="NUT",
        min_run_units=500,
        unit_rate_cents=200,
        supplies=[
            {
                "ingredient_name": "Sea salt",
                "sourcing_mode": "COPACKER_SUPPLIED",
                "quantity_per_unit": 0.1,
                "unit_cost_cents": 50,
            }
        ],
    )
    # ACIDIFIED chain on the same customer, trialing on a non-overlapping day.
    f1 = create_formula(ctx["customer"]["id"])
    pepper = add_ingredient_supply(
        f1["id"],
        ingredient_name="Ghost pepper mash",
        sourcing_mode="CUSTOMER_SUPPLIED",
        quantity_per_unit=0.5,
    )
    add_ingredient_supply(
        f1["id"],
        ingredient_name="White vinegar",
        sourcing_mode="COPACKER_SUPPLIED",
        quantity_per_unit=0.8,
        unit_cost_cents=300,
    )
    receive_consignment(pepper["id"], 5000)
    trial = schedule_trial(f1["id"], ctx["cell"]["id"])
    record_trial_results(trial["id"], passed=True, yield_units=480)
    letter = create_letter(f1["id"], formula_revision=1)
    activate_letter(letter["id"])
    ctx["f_none"] = get_formula(f1["id"])
    assert ctx["f_none"]["status"] == "APPROVED"
    ctx["kettle"] = create_kettle_line()
    return ctx
