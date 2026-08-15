"""Sizing studies: dual-variant calculation, OCC, capacity gate, supersession (PRD §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_sizing_study,
    create_sizing_study_payload,
    get_success_data,
    setup_catalog,
    setup_order,
    create_study,
    create_submitted_study,
    create_approved_study,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["sales_engineer_headers"]
APP_ENG = TEST_USERS["application_engineer_headers"]

THREE_STEP_LOAD = [
    {"description": "A", "kva": 100, "duty": "CONTINUOUS"},
    {"description": "B", "kva": 80, "duty": "CONTINUOUS"},
    {"description": "C", "kva": 60, "duty": "CONTINUOUS"},
]


def _order_with_catalog():
    customer, engine, alternator = setup_catalog()
    order = setup_order(customer["id"])
    return customer, engine, alternator, order


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/sizing_nameplate_vs_derated_divergence
# ---------------------------------------------------------------------------

def test_sizing_nameplate_sum_required_kva_value(api):
    """PRD §3.2: "Under `NAMEPLATE_SUM`, that base, rounded half-up to one decimal
    place, is the `required_kva`."

    For steps 100/80/60 CONTINUOUS with largest_motor 100 and DOL: running 240,
    starting 240 - 100 + 100*3.0 = 440, so required_kva is 440.0.

    Design: Difficulty/dual_variant_calc/sizing_nameplate_vs_derated_divergence
    """
    _, engine, alternator, order = _order_with_catalog()
    study = create_study(
        order, engine["id"], alternator["id"], load_steps=THREE_STEP_LOAD,
        altitude_m=2000, ambient_c=50, method="NAMEPLATE_SUM",
    )
    assert study["required_kva"] == pytest.approx(440.0, abs=0.001)


def test_sizing_derated_stochastic_strictly_larger(api):
    """PRD §3.2: "Identical inputs therefore always yield a strictly larger
    `required_kva` under `DERATED_STOCHASTIC` whenever any derate applies."

    Same inputs as the NAMEPLATE_SUM twin at altitude 2000 m and ambient 50 C:
    derate 0.01*floor(1000/500)=0.02 and 0.02*floor(10/5)=0.04, factor 0.94,
    so required_kva = 440/0.94*1.10 = 514.9.

    Design: Difficulty/dual_variant_calc/sizing_nameplate_vs_derated_divergence
    """
    _, engine, alternator, order = _order_with_catalog()
    study_a = create_study(
        order, engine["id"], alternator["id"], load_steps=THREE_STEP_LOAD,
        altitude_m=2000, ambient_c=50, method="NAMEPLATE_SUM",
    )
    study_b = create_study(
        order, engine["id"], alternator["id"], load_steps=THREE_STEP_LOAD,
        altitude_m=2000, ambient_c=50, method="DERATED_STOCHASTIC",
    )
    assert study_b["required_kva"] == pytest.approx(514.9, abs=0.001)
    assert study_b["required_kva"] > study_a["required_kva"]


# ---------------------------------------------------------------------------
# Corner/calculations/sizing_study_load_step_input_set_filtering
# ---------------------------------------------------------------------------

def test_sizing_standby_start_steps_excluded_from_running_kva(api):
    """PRD §3.2: "the running load `running_kva` is the sum of `kva` over exactly
    those `load_steps` whose `duty` is `CONTINUOUS`; steps marked `STANDBY_START`
    never enter this sum."

    Steps 100 CONTINUOUS + 500 STANDBY_START with largest_motor 50 DOL:
    running 100; starting 100 - 50 + 150 = 200; required_kva 200.0.

    Design: Corner/calculations/sizing_study_load_step_input_set_filtering
    """
    _, engine, alternator, order = _order_with_catalog()
    steps = [
        {"description": "run", "kva": 100, "duty": "CONTINUOUS"},
        {"description": "stdby", "kva": 500, "duty": "STANDBY_START"},
    ]
    study = create_study(
        order, engine["id"], alternator["id"], load_steps=steps,
        largest_motor_kva=50, starting_method="DOL", method="NAMEPLATE_SUM",
    )
    assert study["required_kva"] == pytest.approx(200.0, abs=0.001)


# ---------------------------------------------------------------------------
# Corner/calculations/sizing_derated_floor_at_070
# ---------------------------------------------------------------------------

def test_sizing_derated_stochastic_floor_clamps_at_070(api):
    """PRD §3.2: "The derate factor is one minus both derates, floored at 0.70;
    the base is divided by that factor and then multiplied by the 1.10 stochastic
    reserve, and the result, rounded half-up to one decimal place, is the
    `required_kva`."

    Altitude 15000 m and ambient 60 C: raw derates 0.28 + 0.08 = 0.36 give
    factor 0.64, clamped to 0.70; base 300 -> 300/0.70*1.10 = 471.4.

    Design: Corner/calculations/sizing_derated_floor_at_070
    """
    _, engine, alternator, order = _order_with_catalog()
    study = create_study(
        order, engine["id"], alternator["id"],
        load_steps=[{"description": "A", "kva": 100, "duty": "CONTINUOUS"}],
        largest_motor_kva=100, starting_method="DOL",
        altitude_m=15000, ambient_c=60, method="DERATED_STOCHASTIC",
    )
    assert study["required_kva"] == pytest.approx(471.4, abs=0.001)


# ---------------------------------------------------------------------------
# Corner/entities/sizing_study_computed_field_ignores_client_input
# ---------------------------------------------------------------------------

def test_sizing_study_required_kva_server_computed(api):
    """PRD §3.2: "The `required_kva` is computed at creation. First, the running
    load `running_kva` is the sum of `kva` over exactly those `load_steps` whose
    `duty` is `CONTINUOUS`..."

    One 100-kVA CONTINUOUS step with largest_motor 100 DOL: running 100,
    starting 100 - 100 + 300 = 300, so required_kva is 300.0 regardless of any
    client-side expectation.

    Design: Corner/entities/sizing_study_computed_field_ignores_client_input
    """
    _, engine, alternator, order = _order_with_catalog()
    study = create_study(order, engine["id"], alternator["id"])
    assert study["required_kva"] == pytest.approx(300.0, abs=0.001)
    assert study["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner/state_machines/sizing_study_initial_state_is_draft
# ---------------------------------------------------------------------------

def test_sizing_study_initial_state_is_draft(api):
    """PRD §3.2: "On approval, any other study for the same order that is currently
    `APPROVED` is flipped to `SUPERSEDED` with its `superseded_by_id` set to the
    newly approved study's `id` (a study not yet superseded carries
    `superseded_by_id` null)..."

    A freshly created study starts in DRAFT with null superseded_by_id and null
    rejection_reason.

    Design: Corner/state_machines/sizing_study_initial_state_is_draft
    """
    _, engine, alternator, order = _order_with_catalog()
    study = create_study(order, engine["id"], alternator["id"])
    assert_sizing_study(study)
    assert study["status"] == "DRAFT"
    assert study["superseded_by_id"] is None
    assert study["rejection_reason"] is None


# ---------------------------------------------------------------------------
# Corner/state_machines/approve_draft_study_rejected_invalid_state
# ---------------------------------------------------------------------------

def test_approve_draft_study_rejected_invalid_state(api):
    """PRD §2.8: "...then state-machine from-state checks..." and PRD §3.2:
    "Approval belongs to the `SalesEngineer` and carries the capacity gate,
    checked with the error `ERR_CAPACITY_UNDERSIZED`..." — approval operates on
    a `SUBMITTED` study, so approving a DRAFT fails the from-state check with
    ERR_STUDY_STATE_INVALID.

    Design: Corner/state_machines/approve_draft_study_rejected_invalid_state
    """
    _, engine, alternator, order = _order_with_catalog()
    study = create_study(order, engine["id"], alternator["id"])
    resp = api.approve_sizing_study(study["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_STUDY_STATE_INVALID)
    current = get_success_data(api.get_sizing_study(study["id"], SALES))
    assert current["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner/state_machines/rejected_study_resubmit_loop
# ---------------------------------------------------------------------------

def test_rejected_study_resubmit_loop(api):
    """PRD §3.2: "Rejection is not the end: a `REJECTED` study may be submitted
    again (looping back to `SUBMITTED` under the same not-cancelled gate), which
    clears `rejection_reason` to null."

    Design: Corner/state_machines/rejected_study_resubmit_loop
    """
    _, engine, alternator, order = _order_with_catalog()
    study = create_submitted_study(order, engine["id"], alternator["id"])
    rejected = get_success_data(api.reject_sizing_study(
        study["id"], {"reason": "load profile incomplete"}, SALES
    ))
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "load profile incomplete"

    resubmitted = get_success_data(api.submit_sizing_study(study["id"], APP_ENG))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["rejection_reason"] is None


# ---------------------------------------------------------------------------
# Corner/state_machines/study_approval_supersedes_prior_approved
# ---------------------------------------------------------------------------

def test_study_approval_supersedes_prior_approved(api):
    """PRD §3.2: "On approval, any other study for the same order that is currently
    `APPROVED` is flipped to `SUPERSEDED` with its `superseded_by_id` set to the
    newly approved study's `id`..."

    Design: Corner/state_machines/study_approval_supersedes_prior_approved
    """
    _, engine, alternator, order = _order_with_catalog()
    study_a = create_approved_study(order, engine["id"], alternator["id"])
    assert study_a["status"] == "APPROVED"

    order_now = get_success_data(api.get_order(order["id"], SALES))
    payload = create_sizing_study_payload(
        order_id=order["id"], engine_model_id=engine["id"],
        alternator_model_id=alternator["id"],
        load_steps=[{"description": "B", "kva": 200, "duty": "CONTINUOUS"}],
        largest_motor_kva=100, starting_method="SOFT_START",
        expected_order_version=order_now["version"],
    )
    study_b = get_success_data(api.create_sizing_study(payload, APP_ENG))
    study_b = get_success_data(api.submit_sizing_study(study_b["id"], APP_ENG))
    study_b = get_success_data(api.approve_sizing_study(study_b["id"], SALES))
    assert study_b["status"] == "APPROVED"

    study_a_now = get_success_data(api.get_sizing_study(study_a["id"], SALES))
    assert study_a_now["status"] == "SUPERSEDED"
    assert study_a_now["superseded_by_id"] == study_b["id"]

    data, meta = __import__("test_helpers").validate_paginated(
        api.list_sizing_studies(SALES, params={"superseded_by_id": study_b["id"]})
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == study_a["id"]


# ---------------------------------------------------------------------------
# Corner/calculations/sizing_approve_capacity_gate_undersized_engine
# ---------------------------------------------------------------------------

def test_approve_undersized_engine_rejected(api):
    """PRD §3.2: "Approval belongs to the `SalesEngineer` and carries the capacity
    gate, checked with the error `ERR_CAPACITY_UNDERSIZED`: the engine's
    `rated_kw` divided by 0.8 must be at least the study's `required_kva`, and
    the alternator's `rated_kva` must be at least the `required_kva`."

    Derated study requires 514.9 kVA; the 400 kW engine supplies only 500 kVA
    of capacity (400 / 0.8), so approval fails.

    Design: Corner/calculations/sizing_approve_capacity_gate_undersized_engine
    """
    _, engine, alternator, order = _order_with_catalog()
    study = create_submitted_study(
        order, engine["id"], alternator["id"], load_steps=THREE_STEP_LOAD,
        altitude_m=2000, ambient_c=50, method="DERATED_STOCHASTIC",
    )
    assert study["required_kva"] == pytest.approx(514.9, abs=0.001)
    resp = api.approve_sizing_study(study["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_UNDERSIZED)
    current = get_success_data(api.get_sizing_study(study["id"], SALES))
    assert current["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Corner/cross_cutting_layers/occ_sizing_create_stale_order_version
# ---------------------------------------------------------------------------

def test_sizing_create_stale_order_version_rejected(api):
    """PRD §2.7: "Creating a sizing study requires the request to carry
    `expected_order_version`, holding the `version` of the target `PackageOrder`
    as the client last observed it. If the order's current `version` has advanced
    since that observation — for example because another writer created or
    approved a study against the same order in the meantime — the create is
    rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)..."

    Design: Corner/cross_cutting_layers/occ_sizing_create_stale_order_version
    """
    _, engine, alternator, order = _order_with_catalog()
    version_at_read = order["version"]
    # First study creation advances the order's version by 1.
    first = create_study(order, engine["id"], alternator["id"])
    assert first["status"] == "DRAFT"
    order_now = get_success_data(api.get_order(order["id"], SALES))
    assert order_now["version"] == version_at_read + 1

    # Second create presenting the pre-bump version is stale.
    stale_payload = create_sizing_study_payload(
        order_id=order["id"], engine_model_id=engine["id"],
        alternator_model_id=alternator["id"],
        load_steps=[{"description": "B", "kva": 50, "duty": "CONTINUOUS"}],
        largest_motor_kva=50, expected_order_version=version_at_read,
    )
    resp = api.create_sizing_study(stale_payload, APP_ENG)
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)

    # The same create with the fresh version succeeds.
    fresh_payload = create_sizing_study_payload(
        order_id=order["id"], engine_model_id=engine["id"],
        alternator_model_id=alternator["id"],
        load_steps=[{"description": "B", "kva": 50, "duty": "CONTINUOUS"}],
        largest_motor_kva=50, expected_order_version=order_now["version"],
    )
    ok = validate_success(api.create_sizing_study(fresh_payload, APP_ENG), expected_status=201)
    assert ok["status"] == "DRAFT"
