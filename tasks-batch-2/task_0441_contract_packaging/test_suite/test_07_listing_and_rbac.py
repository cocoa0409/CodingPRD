"""List endpoints (pagination envelope, FK-reverse filters) and RBAC denials."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_customer, create_component, build_approved_recipe,
    create_production_line, create_crew,
    setup_basic_scenario, setup_pending_qa_run, schedule_run, set_clock,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import RECEIVER, SCHEDULER, QA


# ---------------------------------------------------------------------------
# Queue B — endpoints / list_components_pagination_envelope
# ---------------------------------------------------------------------------

def test_list_components_pagination_envelope(api):
    """PRD 2.3: "The `limit` parameter caps the number of items returned ... Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object."

    Design: Corner/endpoints/list_components_pagination_envelope
    """
    customer = create_customer()
    create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")

    data, meta = validate_paginated(
        api.list_components(RECEIVER, params={"customer_id": customer["id"], "limit": 1})
    )
    assert len(data) <= 1, f"limit=1 must cap the page to 1 item, got {len(data)}"
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"pagination meta must include {key}"


# ---------------------------------------------------------------------------
# Queue B — endpoints / filtered_list_lot_consumptions_by_component_lot
# ---------------------------------------------------------------------------

def test_filtered_lot_consumptions_by_component_lot(api):
    """PRD 3.4: "one `LotConsumption` record is written per lot-and-line touched, recording the `production_run_id`, the `component_lot_id`, the `bom_line_id`, and the `consumed_qty` actually drawn from that lot."

    Design: Corner/endpoints/filtered_list_lot_consumptions_by_component_lot
    """
    # ALMOND lot 500; run draws exactly 210.
    scenario = setup_basic_scenario(almond_qty=2, almond_scrap=5, almond_received=500)
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")
    validate_success(api.start_run(run["id"],
        {"expected_line_version": scenario["line"]["version"]}, SCHEDULER))

    data, _meta = validate_paginated(
        api.list_lot_consumptions(SCHEDULER,
                                  params={"component_lot_id": scenario["almond_lot"]["id"]})
    )
    assert len(data) == 1, f"one consumption row for the single drawn lot, got {len(data)}"
    assert float(data[0]["consumed_qty"]) == 210.000, (
        f"the consumed_qty drawn from the lot must be 210.000, got {data[0]['consumed_qty']}"
    )


# ---------------------------------------------------------------------------
# Queue B — rbac / scheduler_cannot_release_run_unauthorized
# ---------------------------------------------------------------------------

def test_scheduler_cannot_release_run(api):
    """PRD 2.1: "A request whose role is recognized but is not permitted to perform the requested operation is rejected with `ERR_UNAUTHORIZED`."
    PRD 2.1: "A `QAInspector` owns quality: ... releasing and quarantining runs"

    Design: Corner/rbac/scheduler_cannot_release_run_unauthorized
    """
    scenario, run = setup_pending_qa_run(
        almond_received=1000, actual_units_good=100, actual_units_scrapped=0,
    )
    resp = api.release_run(run["id"], SCHEDULER)  # release is QAInspector-exclusive
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Queue B — rbac / receiver_cannot_create_recipe_unauthorized
# ---------------------------------------------------------------------------

def test_receiver_cannot_create_recipe(api):
    """PRD 2.1: "A `Scheduler` owns production planning: authoring recipes and their bill-of-materials lines"
    PRD 2.1: "A request whose role is recognized but is not permitted to perform the requested operation is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/receiver_cannot_create_recipe_unauthorized
    """
    customer = create_customer()
    resp = api.create_recipe(
        {"customer_id": customer["id"], "name": "Granola",
         "target_fill_weight_g": 200, "fill_tolerance_pct": 5, "shelf_life_days": 90},
        RECEIVER,  # recipe creation is Scheduler-exclusive
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Queue B — rbac / missing_headers_unauthenticated
# ---------------------------------------------------------------------------

def test_unknown_role_unauthenticated(api, unknown_role_headers):
    """PRD 2.1: "A request that omits either header, or whose `X-User-Role` is not one of these three known roles, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    resp = api.list_customers(unknown_role_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
