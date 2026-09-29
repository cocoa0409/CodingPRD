"""Multi-hop cascades where each hop is caused by the hop before it.

Declaring a sharp unaccounted runs four hops from the shadow board through the
posture gate into the food and the work details, plus an independent fan-out.
Closing a short service record runs three hops from the record through the
contract ledger back down onto every facility.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import ApiClient, assertions, factories, fixtures
from test_helpers import test_users as users


# ---------------------------------------------------------------------------
# Unaccounted sharp
# ---------------------------------------------------------------------------


def _facility_with_live_food_and_a_knife_out(api: ApiClient) -> dict:
    """A facility holding a live PLANNED batch, a worker on the cook-chill detail
    and one sharp knife signed off the shadow board."""
    ctx = fixtures.locked_forecast(
        api,
        contract_overrides={"contract_code": "CFS-2515-TC1"},
        facility_overrides={
            "facility_code": "FAC-TC1",
            "sharps_authorized_count": 12,
        },
    )
    ctx = fixtures.planned_batch(api, ctx, planned_trays=10)
    facility_id = ctx["facility"]["id"]

    enrolment = fixtures.enrolled_worker(
        api, facility_id, booking_number="BK-TC1-W01", sharps_eligible=True
    )
    worker = validate_success(
        api.assign_inmate_worker(
            enrolment["worker"]["id"],
            factories.assign_payload("COOK_CHILL"),
            users.FOOD_SUPERVISOR,
        )
    )
    issuance = fixtures.issued_tool(
        api,
        facility_id,
        worker["id"],
        tool_class="SHARP_KNIFE",
        tool_serial="KN-001",
        shadow_board_slot=1,
    )
    ctx["worker"] = worker
    ctx["issuance"] = issuance
    return ctx


def test_unaccounted_sharp_locks_the_kitchen_down_and_discards_live_food(
    api: ApiClient,
) -> None:
    """Hops one through three: the sharps counters move, the posture goes to
    lockdown and every in-flight batch is discarded.

    The PRD states that declaring a tool unaccounted "moves `status` to
    `UNACCOUNTED`, stamps `unaccounted_at` and increments `version` by 1, and then
    cascades four hops deep, with each hop caused by the hop before it", where "for
    a sharp class the facility's `sharps_unaccounted_count` rises by 1 and
    `open_sharps_discrepancy_count` rises by 1", then "For a sharp class the first
    waterfall clause fires and the posture becomes `LOCKDOWN`", and then "every
    production batch at that facility whose `production_stage` is `PLANNED`,
    `COOKED` or `CHILLED` becomes `DISCARDED` with `qa_status` set to `QA_HELD`".

    Design: Difficulty/transitive_cascade/unaccounted_sharp_cascades_facility_lockdown_batch_discard_worker_unassignment
    """
    ctx = _facility_with_live_food_and_a_knife_out(api)

    declared = validate_success(
        api.declare_tool_unaccounted(
            ctx["issuance"]["id"],
            factories.declare_unaccounted_payload(),
            users.OFFICER,
        )
    )

    assertions.assert_tool_issuance(declared)
    assert declared["status"] == "UNACCOUNTED"
    assertions.assert_instant(declared["unaccounted_at"], "2026-08-01T00:00:00Z")
    assert declared["recovered"] is False

    facility = fixtures.read_facility(api, ctx["facility"]["id"])
    assert facility["sharps_unaccounted_count"] == 1
    assert facility["sharps_issued_count"] == 0
    assert facility["open_sharps_discrepancy_count"] == 1
    assert facility["sharps_on_board_count"] == 11
    assertions.assert_sharps_conservation(facility)
    assert facility["kitchen_posture"] == "LOCKDOWN"
    assert facility["sharps_audit_shortfall"] == 0
    assert facility["corrective_action_required"] is False

    batch = fixtures.read_batch(api, ctx["batch"]["id"])
    assert batch["production_stage"] == "DISCARDED"
    assert batch["qa_status"] == "QA_HELD"


def test_unaccounted_sharp_clears_the_cook_chill_detail_and_raises_a_system_incident(
    api: ApiClient,
) -> None:
    """Hop four plus the independent fan-out: the cook-chill worker loses the
    detail while keeping clearance, and one contraband incident is raised by the
    system itself.

    The PRD states: "Because those batches became `DISCARDED`, every worker at that
    facility whose `assignment_status` is `ASSIGNED` and whose `work_area` is
    `COOK_CHILL` or `SERVING_LINE` becomes `UNASSIGNED` with `work_area` null and
    `version` incremented by 1." It adds: "Independently of that hop chain, and on
    both branches, a contraband incident is automatically raised as a fan-out: at
    this facility, with `related_tool_issuance_id` naming this issuance and
    `inmate_worker_id` copied from `issued_to_worker_id`, with `item_class` set to
    `SHARP` for a sharp class ... `severity` set to `CRITICAL` for a sharp class ...
    `status` `OPEN`, and `discovered_by_user_id` set to the literal string `system`."

    Design: Difficulty/transitive_cascade/unaccounted_sharp_cascades_facility_lockdown_batch_discard_worker_unassignment
    """
    ctx = _facility_with_live_food_and_a_knife_out(api)

    validate_success(
        api.declare_tool_unaccounted(
            ctx["issuance"]["id"],
            factories.declare_unaccounted_payload(),
            users.OFFICER,
        )
    )

    worker = fixtures.read_worker(api, ctx["worker"]["id"])
    assert worker["assignment_status"] == "UNASSIGNED"
    assert worker["work_area"] is None
    assert worker["clearance_status"] == "CLEARED"

    incidents, meta = validate_paginated(
        api.list_contraband_incidents(
            users.OFFICER, {"facility_id": ctx["facility"]["id"]}
        )
    )
    assert meta["total_count"] == 1, "exactly one incident must be raised by the fan-out"
    incident = incidents[0]
    assertions.assert_contraband_incident(incident)
    assert incident["related_tool_issuance_id"] == ctx["issuance"]["id"]
    assert incident["inmate_worker_id"] == ctx["worker"]["id"]
    assert incident["item_class"] == "SHARP"
    assert incident["severity"] == "CRITICAL"
    assert incident["status"] == "OPEN"
    assert incident["discovered_by_user_id"] == "system"

    facility = fixtures.read_facility(api, ctx["facility"]["id"])
    assert facility["open_contraband_incident_count"] == 1


# ---------------------------------------------------------------------------
# Service record close
# ---------------------------------------------------------------------------


def _short_service_ready_to_close(api: ApiClient) -> dict:
    """An OPEN service record expecting 156 trays against which only 100 general
    trays were served."""
    ctx = fixtures.facility_with_active_cycle(
        api,
        contract_overrides={"contract_code": "CFS-2515-TC2"},
        facility_overrides={
            "facility_code": "FAC-TC2",
            "sharps_authorized_count": 12,
        },
    )
    facility_id = ctx["facility"]["id"]
    count = fixtures.create_population_count(
        api,
        facility_id,
        general_population=130,
        segregation_population=20,
        satellite_population=12,
        medical_population=0,
    )
    forecast = validate_success(
        api.create_meal_forecast(
            factories.meal_forecast_payload(
                facility_id,
                count["id"],
                service_date="2026-08-02",
                meal_slot="LUNCH",
                forecast_variant="COUNT_DRIVEN",
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    locked = validate_success(
        api.lock_meal_forecast(forecast["id"], users.FOOD_SUPERVISOR)
    )
    assert locked["line_trays"] == 156
    assert locked["waste_allowance_trays"] == 8
    assert locked["total_forecast_trays"] == 164

    record = validate_success(
        api.create_meal_service_record(
            factories.meal_service_record_payload(
                facility_id,
                locked["id"],
                service_date="2026-08-02",
                meal_slot="LUNCH",
                trays_served_general=100,
                trays_served_segregation=0,
                trays_served_satellite=0,
                special_diet_trays_served=0,
            ),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    ctx["forecast"] = locked
    ctx["record"] = record
    return ctx


def _close(api: ApiClient, ctx: dict) -> dict:
    contract = fixtures.read_contract(api, ctx["contract"]["id"])
    return validate_success(
        api.close_meal_service_record(
            ctx["record"]["id"],
            factories.close_service_record_payload(contract["version"]),
            users.FOOD_SUPERVISOR,
        )
    )


def test_closing_a_short_service_posts_the_weighted_shortfall_to_the_ledger(
    api: ApiClient,
) -> None:
    """Hop one: the record's weighted missed meals land on the contract and the
    whole damages waterfall is recomputed on the spot.

    The PRD states: "Because the record closed, the contract's `total_trays_served`
    rises by this record's `total_trays_served`, `meal_days_served` is recomputed,
    and `missed_meal_total` rises by this record's `missed_meal_count`. The whole
    liquidated-damages waterfall of §3.9 and `performance_score` are recomputed, and
    the contract's `version` is incremented by 1." A shortfall of 56 trays less the
    tolerance of 3 gives 53 weighted missed meals, and the incremental recompute
    runs on the incident-based default while `ld_variant` is still null.

    Design: Difficulty/transitive_cascade/service_record_close_cascades_contract_ledger_to_facility_corrective_posture
    """
    ctx = _short_service_ready_to_close(api)

    closed = _close(api, ctx)

    assertions.assert_meal_service_record(closed)
    assert closed["status"] == "CLOSED"
    assertions.assert_instant(closed["closed_at"], "2026-08-01T00:00:00Z")
    assert closed["expected_service_trays"] == 156
    assert closed["total_trays_served"] == 100
    assert closed["missed_meal_count"] == 53

    contract = fixtures.read_contract(api, ctx["contract"]["id"])
    assert contract["status"] == "ACTIVE"
    assert contract["ld_variant"] is None
    assert contract["total_trays_served"] == 100
    assert contract["meal_days_served"] == 33
    assert contract["missed_meal_total"] == 53
    assert contract["gross_food_cost_cents"] == 10395
    assertions.assert_decimal_2dp(contract["cost_cents_per_meal_day_actual"], 315.00)
    assert contract["raw_liquidated_damages_cents"] == 39750
    assert contract["liquidated_damages_cents"] == 39750
    assert contract["cost_recovery_credit_cents"] == 2079
    assert contract["net_liquidated_damages_cents"] == 37671
    assertions.assert_decimal_2dp(contract["performance_score"], 0.00)


def test_crossing_the_escalation_threshold_restricts_every_facility_kitchen(
    api: ApiClient,
) -> None:
    """Hops two and three: the escalation threshold flags corrective action, and
    the posture recomputation restricts the kitchen without locking it down.

    The PRD states: "Because the contract's `missed_meal_total` reached the
    escalation threshold of 25 weighted missed meals, every facility under that
    contract has `corrective_action_required` set to true with `version` incremented
    by 1." It continues: "Because `corrective_action_required` became true, every
    such facility whose `kitchen_posture` reads `OPEN` moves to `RESTRICTED`."

    Design: Difficulty/transitive_cascade/service_record_close_cascades_contract_ledger_to_facility_corrective_posture
    """
    ctx = _short_service_ready_to_close(api)
    before = fixtures.read_facility(api, ctx["facility"]["id"])
    assert before["corrective_action_required"] is False
    assert before["kitchen_posture"] == "OPEN"

    _close(api, ctx)

    facility = fixtures.read_facility(api, ctx["facility"]["id"])
    assert facility["corrective_action_required"] is True
    assert facility["kitchen_posture"] == "RESTRICTED"
    assert facility["open_sharps_discrepancy_count"] == 0
    assert facility["open_contraband_incident_count"] == 0
