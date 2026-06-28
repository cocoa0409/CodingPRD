"""Endpoint side effects, reverse-reachability reads, clock-ordering, RBAC peer
denial / shared read, optimistic-concurrency stale-version rejection, derived
field reconciliation, and immediate-visibility consistency.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    build_user_headers,
    ApiErrorId,
    TEST_USERS,
    create_species,
    create_tank,
    create_cohort,
    feed_cohort,
    create_planned_grading,
    create_product_lot,
    create_sales_order,
    add_line,
    get_lot,
    setup_species_tank_cohort,
)

FM = TEST_USERS["farm_manager_headers"]
FT = TEST_USERS["farm_technician_headers"]
VET = TEST_USERS["veterinarian_headers"]
HO = TEST_USERS["harvest_operator_headers"]
SA = TEST_USERS["sales_agent_headers"]


# ===========================================================================
# endpoints :: fulfill_converts_reserved_to_shipped
# ===========================================================================
def test_fulfill_moves_reserved_to_shipped():
    """PRD §3.10: "Fulfilling a confirmed order (CONFIRMED -> FULFILLED) converts
    reservation to shipment: for each line the referenced lot's reserved_weight_kg
    is decreased by the line's weight_kg and its shipped_weight_kg is increased by
    the same amount, leaving available_weight_kg unchanged."

    Design: Corner/endpoints/fulfill_converts_reserved_to_shipped
    """
    lot, _species, _tank = create_product_lot(50.0, price_per_kg=10.0)
    order = create_sales_order(discount_tier="NONE")
    add_line(order["id"], lot["id"], 30.0)
    lot_now = get_lot(lot["id"])
    get_success_data(
        api_client.confirm_sales_order(
            order["id"], {"expected_lot_version": lot_now["version"]}, SA
        )
    )
    get_success_data(api_client.fulfill_sales_order(order["id"], SA))
    after = get_lot(lot["id"])
    assert after["reserved_weight_kg"] == pytest.approx(0.00, abs=0.01)
    assert after["shipped_weight_kg"] == pytest.approx(30.00, abs=0.01)
    assert after["available_weight_kg"] == pytest.approx(20.00, abs=0.01)


# ===========================================================================
# endpoints :: feed_log_reverse_reachability
# ===========================================================================
def test_feed_log_reverse_reachability():
    """PRD §3.3: "The feed list endpoint returns the feed logs for a cohort by
    reverse lookup on the cohort."

    Design: Corner/endpoints/feed_log_reverse_reachability
    """
    species, tank, cohort = setup_species_tank_cohort(
        cohort_overrides={"fish_count": 100})
    feed_cohort(cohort["id"], fed_at="2026-01-01T00:00:00Z", amount_kg=10,
                feed_type="starter")
    logs, meta = validate_paginated(api_client.list_feed_logs(cohort["id"], FT))
    assert meta["total_count"] == 1, f"expected 1 feed log, got {meta['total_count']}"
    assert logs[0]["amount_kg"] == pytest.approx(10, abs=0.01)


# ===========================================================================
# errors :: clock_backwards_event_timestamp
# ===========================================================================
def test_feed_log_future_timestamp_rejected():
    """PRD §2.11: "a timestamp that precedes the relevant cohort or tank creation,
    or that lies in the future relative to the clock when the rule requires a
    past-only event, is rejected with ERR_CLOCK_BACKWARDS (HTTP 422)."

    Design: Corner/errors/clock_backwards_event_timestamp
    """
    species, tank, cohort = setup_species_tank_cohort(
        cohort_overrides={"fish_count": 100})
    # clock at default 2026-01-01; fed_at far in the future
    resp = api_client.create_feed_log(
        cohort["id"], {"fed_at": "2026-12-01T00:00:00Z", "amount_kg": 10,
                       "feed_type": "starter"}, FT,
    )
    validate_error(resp, ApiErrorId.ERR_CLOCK_BACKWARDS.value)


# ===========================================================================
# rbac :: technician_cannot_create_species
# ===========================================================================
def test_technician_cannot_create_species():
    """PRD §2.1: "If the role is recognized but not authorized for that operation,
    the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."
    PRD §4: POST /species is authorized for FarmManager.

    Design: Corner/rbac/technician_cannot_create_species
    """
    resp = api_client.create_species(
        {"common_name": "Cod", "code": "COD", "target_market_weight_g": 4000,
         "base_daily_growth_g": 4.0, "default_processing_yield_pct": 0.55,
         "min_water_temp_c": 0, "max_water_temp_c": 12},
        FT,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# rbac :: sales_agent_cannot_create_health_treatment
# ===========================================================================
def test_sales_agent_cannot_create_health_treatment():
    """PRD §2.1: "If the role is recognized but not authorized for that operation,
    the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."
    PRD §4: POST /health-treatments is authorized for Veterinarian.

    Design: Corner/rbac/sales_agent_cannot_create_health_treatment
    """
    species, tank, cohort = setup_species_tank_cohort(
        cohort_overrides={"fish_count": 100})
    resp = api_client.create_health_treatment(
        {"cohort_id": cohort["id"], "tank_id": tank["id"], "medication": "oxytet",
         "started_at": "2026-01-01T00:00:00Z", "duration_days": 5,
         "withdrawal_days": 10},
        SA,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# rbac :: missing_headers_unauthenticated
# ===========================================================================
def test_unknown_role_unauthenticated():
    """PRD §2.1: "A request missing either header, or carrying an X-User-Role value
    that is not one of the recognized roles, is rejected with ERR_UNAUTHENTICATED
    (HTTP 401)."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    anon = build_user_headers("nobody", "Anonymous")
    resp = api_client.list_tanks(anon)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# rbac :: harvest_operator_shared_read_product_lots
# ===========================================================================
def test_harvest_operator_can_read_product_lots():
    """PRD §4: GET /product-lots is authorized for "All roles".
    PRD §2.1: "Once a request is authenticated, the system checks whether the
    acting role is permitted to perform the requested operation."

    Design: Corner/rbac/harvest_operator_shared_read_product_lots
    """
    resp = api_client.list_product_lots(HO)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 0, "empty DB must list zero product lots"


# ===========================================================================
# cross_cutting_complexity_layers :: grading_commit_stale_source_version
# ===========================================================================
def test_grading_commit_stale_source_version_rejected():
    """PRD §2.8: "Committing a grading event requires the request to carry
    expected_source_cohort_version, the version the client last observed on the
    source cohort. If that value does not equal the source cohort's current version
    at commit time, the commit is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/grading_commit_stale_source_version
    """
    species = create_species()
    t1 = create_tank(name="T1")
    t2 = create_tank(name="T2")
    cohort = create_cohort(species["id"], t1["id"], fish_count=100)
    splits = [{"label": "all", "fish_count": 100, "target_tank_id": t2["id"],
               "avg_weight_g": 55}]
    grading = create_planned_grading(cohort["id"], splits)
    resp = api_client.commit_grading_event(
        grading["id"], {"expected_source_cohort_version": cohort["version"] - 1}, FT
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ===========================================================================
# cross_cutting_complexity_layers :: sales_confirm_stale_lot_version
# ===========================================================================
def test_sales_confirm_stale_lot_version_rejected():
    """PRD §2.8: "Confirming a sales order requires the request to carry
    expected_lot_version, the single version that every ProductLot referenced by
    the order's lines must currently equal. If any referenced lot's current version
    differs from expected_lot_version, the confirm is rejected with
    ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/sales_confirm_stale_lot_version
    """
    lot, _species, _tank = create_product_lot(50.0, price_per_kg=10.0)
    order = create_sales_order(discount_tier="NONE")
    add_line(order["id"], lot["id"], 10.0)
    lot_now = get_lot(lot["id"])
    resp = api_client.confirm_sales_order(
        order["id"], {"expected_lot_version": lot_now["version"] - 1}, SA
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ===========================================================================
# cross_cutting_complexity_layers :: version_increments_on_mutation
# ===========================================================================
def test_cumulative_feed_reconciles_and_version_increments():
    """PRD §3.3: "Recording a feed recomputes the cohort's cumulative_feed_kg as
    the sum of amount_kg over all of that cohort's feed logs."
    PRD §2.4: "Whenever an operation mutates a resource ... the system refreshes
    that resource's updated_at and increments its version by one."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_mutation
    """
    species, tank, cohort = setup_species_tank_cohort(
        cohort_overrides={"fish_count": 100})
    feed_cohort(cohort["id"], fed_at="2026-01-01T00:00:00Z", amount_kg=10,
                feed_type="starter")
    feed_cohort(cohort["id"], fed_at="2026-01-01T00:00:00Z", amount_kg=15,
                feed_type="grower")
    refreshed = validate_success(api_client.get_cohort(cohort["id"], FT))
    assert refreshed["cumulative_feed_kg"] == pytest.approx(25.00, abs=0.01), \
        f"cumulative_feed_kg must reconcile to 25.00, got {refreshed['cumulative_feed_kg']}"
    assert refreshed["version"] >= 3, \
        f"version must advance with each feed mutation, got {refreshed['version']}"


# ===========================================================================
# consistency_model :: confirm_reservation_visible_immediately
# ===========================================================================
def test_confirm_reservation_visible_immediately():
    """PRD §3.10: "On a successful confirm the order's order_total is computed
    (below), and for each line the referenced lot's reserved_weight_kg is increased
    by the line's weight_kg, the lot's available_weight_kg is recomputed."

    Design: Corner/consistency_model/confirm_reservation_visible_immediately
    """
    lot, _species, _tank = create_product_lot(50.0, price_per_kg=10.0)
    order = create_sales_order(discount_tier="NONE")
    add_line(order["id"], lot["id"], 20.0)
    lot_now = get_lot(lot["id"])
    get_success_data(
        api_client.confirm_sales_order(
            order["id"], {"expected_lot_version": lot_now["version"]}, SA
        )
    )
    after = get_lot(lot["id"])
    assert after["reserved_weight_kg"] == pytest.approx(20.00, abs=0.01)
    assert after["available_weight_kg"] == pytest.approx(30.00, abs=0.01)
