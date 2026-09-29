"""Version guards, multi-hop cascades, and writes that are visible immediately.

The two stale-version guards in their refused and refreshed forms, the version ladder
of a route across four writes, the freeze and the suspension cascades, a re-assessment
that switches the exposure variant, and the counters that settle before the response.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    activate_agreement,
    add_stop,
    add_telemetry,
    allocate,
    allocation_payload,
    ApiErrorId,
    arrive_stop,
    assess_shortfall_payload,
    cancel_route_payload,
    compliance_hold_payload,
    create_agreement,
    create_agreement_payload,
    create_outlet,
    create_position,
    create_route,
    create_route_stop_payload,
    create_supply_item,
    create_task,
    create_unit,
    dispatch_route,
    dispatch_route_payload,
    outlet_status_change_payload,
    pin_clock,
    read_agreement,
    read_outlet,
    read_position,
    read_route,
    read_stop,
    read_supply_item,
    read_task,
    read_unit,
    recall_decision_payload,
    route_version,
    run_forecast,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]
DRIVER = TEST_USERS["driver_headers"]
OFFICER = TEST_USERS["officer_headers"]

CLOCK = "2026-08-01T00:00:00Z"


def _outlet(account_code="OUT-1001", name="Riverside Diner", region_code="R-WEST"):
    pin_clock(CLOCK)
    return create_outlet(name=name, account_code=account_code, region_code=region_code)


def _outlet_and_first_draft():
    """An outlet read at version 1 and one DRAFT agreement created with that version."""
    outlet = _outlet()
    agreement = create_agreement(
        outlet["id"], outlet["version"],
        annual_commitment_gallons=8000, equipment_value_cents=480000,
    )
    return outlet, agreement


def _second_agreement_payload(outlet_id, expected_outlet_version):
    return create_agreement_payload(
        outlet_id, expected_outlet_version,
        term_start_date="2026-02-01T00:00:00Z",
        term_end_date="2027-02-01T00:00:00Z",
        annual_commitment_gallons=9000,
        equipment_value_cents=500000,
    )


def _route_read_at_version_one_with_one_stop():
    """RT-01 with one PENDING stop, plus the route version as first read."""
    outlet = _outlet()
    route = create_route(
        route_code="RT-01", depot_region_code="R-WEST",
        service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
    )
    stop = add_stop(
        route["id"], outlet["id"], 1,
        "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z",
    )
    return outlet, route, stop, route["version"]


def _case_pack_allocation():
    """A stop holding a whole-case grant of 4 units out of a 100-unit pool.

    A 7000-ounce week over a 2000-ounce unit is 1000 ounces a day, so the 14-day
    projection of 14000 ounces is 7 units; less the 2 on hand that is 5 requested,
    truncated down to one whole case pack of 4.
    """
    outlet = _outlet()
    agreement = create_agreement(
        outlet["id"], annual_commitment_gallons=8000, equipment_value_cents=480000
    )
    unit = create_unit(
        outlet["id"], agreement["id"],
        serial_number="SN-9001", installed_at="2025-11-01T00:00:00Z",
    )
    item = create_supply_item(
        sku_code="SKU-COLA", brand_name="Cola Classic", supply_form="BAG_IN_BOX",
        case_pack_units=4, ounces_per_unit=2000, national_allocation_units=100,
    )
    add_telemetry(unit["id"], item["id"], 7000, "2026-07-28T00:00:00Z", window_days=7)
    position = create_position(outlet["id"], item["id"], 2)
    run_forecast(position["id"], "TRAILING_ACTUAL", 7)
    route = create_route(
        route_code="RT-01", depot_region_code="R-WEST",
        service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
    )
    stop = add_stop(
        route["id"], outlet["id"], 1,
        "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z",
    )
    return outlet, item, position, route, stop


class TestOutletVersionGuard:
    def test_the_version_spent_by_the_first_agreement_no_longer_opens_a_second(self, api):
        """PRD §2.6 rung 7: "`expected_outlet_version` must equal the stored `version` of
        the outlet, otherwise `ERR_STALE_OUTLET_VERSION` (412). This rung guards
        `POST /fountain-network/placement-agreements`." Per §2.8: "Creating a new agreement
        legitimately supersedes any agreement of the same outlet that is still in `DRAFT` —
        that older agreement is moved to `EXPIRED` — so a writer holding an outdated view
        of the outlet would discard paperwork it never saw. If `expected_outlet_version`
        does not equal the outlet's current stored `version`, the request is rejected with
        `ERR_STALE_OUTLET_VERSION` and HTTP 412, and no agreement is created."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_outlet_version_rejects_the_second_agreement_create
        """
        outlet, first = _outlet_and_first_draft()

        validate_error(
            api.create_agreement(
                _second_agreement_payload(outlet["id"], outlet["version"]), ADMIN
            ),
            ApiErrorId.ERR_STALE_OUTLET_VERSION,
            412,
        )

        survivor = read_agreement(first["id"])
        assert survivor["status"] == "DRAFT"
        assert survivor["annual_commitment_gallons"] == 8000
        assert read_outlet(outlet["id"])["version"] == 2

    def test_the_refreshed_version_lets_the_second_draft_supersede_the_first(self, api):
        """PRD §2.8: "Creating a new agreement legitimately supersedes any agreement of the
        same outlet that is still in `DRAFT` — that older agreement is moved to `EXPIRED` —
        so a writer holding an outdated view of the outlet would discard paperwork it never
        saw." The new contract starts clean, per §3.2: "Creation answers with 201, the
        agreement's `status` is `DRAFT` and its `version` is 1; its assessment outputs start
        empty, with `assessed_shortfall_gallons` and `assessed_fee_cents` at 0,
        `recall_exposure_cents` at 0, `exposure_variant` recorded as `BOOK_VALUE`,
        `assessment_period_start` and `assessment_period_end` null, and both
        `shortfall_assessed_by_user_id` and `recall_decided_by_user_id` null."

        Design: Corner/cross_cutting_complexity_layers/occ_refreshed_outlet_version_supersedes_the_draft_agreement
        """
        outlet, first = _outlet_and_first_draft()
        refreshed = read_outlet(outlet["id"])["version"]

        second = validate_success(
            api.create_agreement(
                _second_agreement_payload(outlet["id"], refreshed), ADMIN
            ),
            201,
        )
        assert second["status"] == "DRAFT"
        assert second["annual_commitment_gallons"] == 9000
        assert second["version"] == 1

        assert read_agreement(first["id"])["status"] == "EXPIRED"
        assert read_outlet(outlet["id"])["version"] == 3


class TestRouteVersionGuard:
    def test_the_version_the_first_stop_consumed_no_longer_adds_a_second(self, api):
        """PRD §2.6 rung 8: "`expected_route_version` must equal the stored `version` of the
        replenishment route, otherwise `ERR_STALE_ROUTE_VERSION` (412)." Per §2.8: "Adding a
        stop is legal from `PLANNED` no matter how many stops already exist, so no state
        precondition can catch a writer whose window plan was computed against an earlier
        stop set; the version comparison is the only signal that the route's stop list has
        moved on. A mismatch against the route's current stored `version` is rejected with
        `ERR_STALE_ROUTE_VERSION` and HTTP 412, and no stop is created."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_route_version_rejects_the_second_stop_create
        """
        outlet, route, first_stop, stale = _route_read_at_version_one_with_one_stop()

        validate_error(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(
                    outlet["id"], stale, 2,
                    "2026-08-03T11:00:00Z", "2026-08-03T12:00:00Z",
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_STALE_ROUTE_VERSION,
            412,
        )

        unmoved = read_route(route["id"])
        assert unmoved["version"] == 2
        assert unmoved["status"] == "PLANNED"
        assert read_stop(first_stop["id"])["sequence_index"] == 1

    def test_the_same_guard_refuses_a_dispatch_computed_before_the_stop(self, api):
        """PRD §2.8: "The same mandatory `expected_route_version` field and the same
        `ERR_STALE_ROUTE_VERSION` rejection at HTTP 412 apply to
        `POST /fountain-network/replenishment-routes/{id}/dispatch` and
        `POST /fountain-network/replenishment-routes/{id}/cancel`." Per §3.7: "Dispatch
        releases a planned route to the driver."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_route_version_rejects_the_route_dispatch
        """
        _outlet, route, stop, stale = _route_read_at_version_one_with_one_stop()

        validate_error(
            api.dispatch_route(route["id"], dispatch_route_payload(stale), PLANNER),
            ApiErrorId.ERR_STALE_ROUTE_VERSION,
            412,
        )

        undispatched = read_route(route["id"])
        assert undispatched["status"] == "PLANNED"
        assert undispatched["version"] == 2
        assert read_stop(stop["id"])["status"] == "PENDING"

    def test_four_writes_walk_the_route_version_from_one_to_four(self, api):
        """PRD §2.4: "Every resource touched anywhere along a cascade is a mutated resource:
        its `updated_at` is refreshed and its `version` advances by one, exactly once per
        request." The last of the four writes is the cancellation, per §3.7: "Cancellation
        moves it to `CANCELLED` from either `PLANNED` or `DISPATCHED`, requires
        `expected_route_version` and accepts an optional `reason_code`; it drives every stop
        of the route in `PENDING` or `ARRIVED` to `SKIPPED` with `skip_reason_code`
        `ACCESS_DENIED`, releases each of those stops' positions restoring both the SKUs'
        `reserved_pool_units` and the route's `committed_units`, and advances the route's
        `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_route_version_increments_on_every_write_of_the_route
        """
        _outlet, route, stop, _stale = _route_read_at_version_one_with_one_stop()
        assert route["version"] == 1
        assert route_version(route["id"]) == 2
        dispatch_route(route["id"])
        assert route_version(route["id"]) == 3

        cancelled = validate_success(
            api.cancel_route(
                route["id"],
                cancel_route_payload(route_version(route["id"]), reason_code="VAN_BREAKDOWN"),
                PLANNER,
            )
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["version"] == 4
        assert cancelled["committed_units"] == 0

        swept = read_stop(stop["id"])
        assert swept["status"] == "SKIPPED"
        assert swept["skip_reason_code"] == "ACCESS_DENIED"


class TestCascades:
    def test_one_hold_freezes_the_outlet_skips_the_stop_and_returns_the_pool(self, api):
        """PRD §3.1: "Placing sets `open_compliance_hold_count` to 1, records the acting
        `X-User-ID` in `last_hold_placed_by_user_id`, recomputes `service_posture`, which
        necessarily lands on `FROZEN`, drives the outlet's `PENDING` stops to `SKIPPED` with
        `skip_reason_code` `POSTURE_FROZEN`, releases each of those stops' allocations back
        to the pool and the route, and increments the outlet's `version` by one." Per §2.10:
        "Releases are always the same four movements, applied to every outlet supply
        position whose `planned_route_stop_id` points at the stop being released: the
        position's `allocated_units` returns to 0, its `planned_route_stop_id` returns to
        null, the referenced supply item's `reserved_pool_units` is reduced by the released
        amount, and the owning route's `committed_units` is reduced by the released amount."

        Design: Corner/cross_cutting_complexity_layers/cascade_compliance_hold_freezes_skips_the_stop_and_returns_the_pool
        """
        outlet, item, position, route, stop = _case_pack_allocation()
        allocate(stop["id"], [position["id"]])
        assert read_supply_item(item["id"])["reserved_pool_units"] == 4

        held = validate_success(
            api.outlet_compliance_hold(
                outlet["id"],
                compliance_hold_payload("PLACE", "SANITATION_LAPSE"),
                OFFICER,
            )
        )
        assert held["open_compliance_hold_count"] == 1
        assert held["overdue_task_count"] == 0
        assert held["service_posture"] == "FROZEN"
        assert held["version"] == 3

        swept = read_stop(stop["id"])
        assert swept["status"] == "SKIPPED"
        assert swept["skip_reason_code"] == "POSTURE_FROZEN"
        released = read_position(position["id"])
        assert released["allocated_units"] == 0
        assert released["planned_route_stop_id"] is None
        assert read_supply_item(item["id"])["reserved_pool_units"] == 0
        assert read_route(route["id"])["committed_units"] == 0

    def test_a_suspension_sweeps_the_arrived_stop_as_well_as_the_pending_one(self, api):
        """PRD §3.1: "Whenever an outlet moves `ACTIVE → SUSPENDED`, every route stop of
        that outlet still sitting in `PENDING` **or** `ARRIVED` is driven to `SKIPPED` and
        stamped with `skip_reason_code` `OUTLET_CLOSED`, and every one of those skipped
        stops releases the consumable it was holding exactly as described in §2.10." The
        route itself is not touched, per §2.4: "When one request mutates several resources,
        each mutated resource independently advances its own `version` by one; the counters
        of untouched resources stand still."

        Design: Corner/cross_cutting_complexity_layers/cascade_operator_suspend_skips_both_the_pending_and_the_arrived_stop
        """
        outlet = _outlet()
        route = create_route(
            route_code="RT-01", depot_region_code="R-WEST",
            service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
        )
        first = add_stop(
            route["id"], outlet["id"], 1,
            "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z",
        )
        second = add_stop(
            route["id"], outlet["id"], 2,
            "2026-08-03T11:00:00Z", "2026-08-03T12:00:00Z",
        )
        dispatch_route(route["id"])
        arrive_stop(first["id"])
        assert read_stop(first["id"])["status"] == "ARRIVED"

        suspended = validate_success(
            api.outlet_status_change(
                outlet["id"],
                outlet_status_change_payload("SUSPEND", reason_code="HEALTH_ORDER"),
                ADMIN,
            )
        )
        assert suspended["status"] == "SUSPENDED"

        for stop in (first, second):
            swept = read_stop(stop["id"])
            assert swept["status"] == "SKIPPED"
            assert swept["skip_reason_code"] == "OUTLET_CLOSED"
        assert read_route(route["id"])["status"] == "DISPATCHED"


class TestExposureVariantSwitch:
    def test_a_reassessment_under_replacement_risk_clears_the_recall_floor(self, api):
        """PRD §3.9: "Under the `BOOK_VALUE` variant the unit's exposure is the agreement's
        `equipment_value_cents` multiplied by one minus one percent per whole month in
        service, with that multiplier clamped up to zero so a very old machine is worth
        nothing rather than a negative amount. Under the `REPLACEMENT_RISK` variant the
        unit's exposure is instead `equipment_value_cents` multiplied by one plus one half
        of one percent per whole month in service, so age escalates rather than erodes the
        figure." And the floor: "And the exposure must be worth the trouble:
        `recall_exposure_cents` must be at least 450000 — four thousand five hundred
        dollars in cents — with anything below that floor refused as
        `ERR_RECALL_EXPOSURE_BELOW_FLOOR`."

        Design: Corner/cross_cutting_complexity_layers/dual_variant_reassessment_switches_the_exposure_and_unlocks_the_recall
        """
        outlet = _outlet()
        agreement = create_agreement(
            outlet["id"], annual_commitment_gallons=8000, equipment_value_cents=480000
        )
        unit = create_unit(
            outlet["id"], agreement["id"],
            serial_number="SN-9001", installed_at="2025-11-01T00:00:00Z",
        )
        activate_agreement(agreement["id"])
        period = assess_shortfall_payload(
            period_start_date="2026-07-01T00:00:00Z",
            period_end_date="2026-10-01T00:00:00Z",
        )

        eroded = validate_success(
            api.assess_shortfall(
                agreement["id"], dict(period, exposure_variant="BOOK_VALUE"), ADMIN
            )
        )
        assert eroded["recall_exposure_cents"] == 436800
        assert eroded["assessed_fee_cents"] == 100000
        validate_success(
            api.recall_decision(
                agreement["id"], recall_decision_payload("FEE_ONLY"), OFFICER
            )
        )
        escalated = validate_success(
            api.assess_shortfall(
                agreement["id"], dict(period, exposure_variant="REPLACEMENT_RISK"), ADMIN
            )
        )
        assert escalated["recall_exposure_cents"] == 501600

        recalled = validate_success(
            api.recall_decision(
                agreement["id"], recall_decision_payload("RECALL"), OFFICER
            )
        )
        assert recalled["status"] == "RECALL_PENDING"
        assert recalled["exposure_variant"] == "REPLACEMENT_RISK"
        assert recalled["recall_exposure_cents"] == 501600
        assert recalled["assessed_fee_cents"] == 100000
        assert recalled["recall_decided_by_user_id"] == OFFICER["X-User-ID"]
        assert recalled["version"] == 6
        assert read_unit(unit["id"])["status"] == "RECALL_STAGED"


class TestDerivedFieldReconciliation:
    def test_service_hands_over_the_case_and_lifts_the_alert_band(self, api):
        """PRD §3.7: "Serving a stop moves it `ARRIVED → SERVED` and is the moment stock
        actually changes hands: for every position pointing at this stop, the position's
        `allocated_units` are added to its `on_hand_units`, then `allocated_units` returns to
        0 and `planned_route_stop_id` to null; the stop's `delivered_units` is written as the
        total units handed over; the SKU's `reserved_pool_units` is reduced per SKU by what
        was delivered, because that pool commitment has now been consumed rather than
        returned; and the route's `committed_units` is deliberately **not** reduced." The
        band then follows §3.6: "The resulting `alert_level` is `CRITICAL` when the position
        has zero `on_hand_units` **or** its cover is under 3 days, `LOW` when the cover is
        under 7 days without meeting the critical test, and `NONE` otherwise."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_of_the_pool_and_alert_level_after_serve
        """
        _outlet, item, position, route, stop = _case_pack_allocation()
        allocate(stop["id"], [position["id"]])
        assert read_position(position["id"])["alert_level"] == "LOW"
        dispatch_route(route["id"])
        arrive_stop(stop["id"])

        served = validate_success(api.serve_stop(stop["id"], DRIVER))
        assert served["status"] == "SERVED"
        assert served["delivered_units"] == 4

        delivered = read_position(position["id"])
        assert delivered["on_hand_units"] == 6
        assert delivered["allocated_units"] == 0
        assert delivered["planned_route_stop_id"] is None
        assert delivered["alert_level"] == "NONE"
        assert read_supply_item(item["id"])["reserved_pool_units"] == 0


class TestImmediateVisibility:
    def test_the_allocation_reply_and_the_next_sku_read_already_agree(self, api):
        """PRD §3.7: "The reply to a successful run is not the stop but a summary object
        carrying `route_stop_id`, `allocated_position_count` giving the number of positions
        that actually received a positive grant, `total_allocated_units` giving the sum of
        all grants in this run, and `granted_units_by_position`, an array pairing each
        granted position with the units it received." Nothing lags behind it, per §2.10: "A
        single operator action routinely walks several hops of consequence, and every hop is
        mandatory, immediate and part of the same request."

        Design: Corner/consistency_model/immediate_allocation_response_already_carries_the_committed_numbers
        """
        _outlet, item, position, route, stop = _case_pack_allocation()

        summary = validate_success(
            api.allocate_stop(
                stop["id"], allocation_payload([position["id"]]), PLANNER
            )
        )
        assert summary["route_stop_id"] == stop["id"]
        assert summary["allocated_position_count"] == 1
        assert summary["total_allocated_units"] == 4

        sku = validate_success(api.get_supply_item(item["id"], PLANNER))
        assert sku["reserved_pool_units"] == 4
        assert sku["national_allocation_units"] == 100
        assert read_position(position["id"])["allocated_units"] == 4
        assert read_route(route["id"])["committed_units"] == 4

    def test_the_outlet_read_after_an_evaluation_needs_no_second_recompute(self, api):
        """PRD §2.10: "A single operator action routinely walks several hops of consequence,
        and every hop is mandatory, immediate and part of the same request." The counter and
        the posture move with the task, per §3.5: "Both moves that land in `OVERDUE`
        additionally raise the owning outlet's `overdue_task_count` by one and recompute
        `service_posture`, and where that recomputation lands on `FROZEN` the outlet's
        `PENDING` stops are skipped and their allocations released as in §2.10." The band
        itself comes from §2.10: "otherwise, if it has at least one overdue maintenance task
        the posture is `RESTRICTED`; otherwise the posture is `OPEN`."

        Design: Corner/consistency_model/immediate_posture_recompute_is_visible_on_the_next_outlet_read
        """
        outlet = _outlet()
        agreement = create_agreement(
            outlet["id"], annual_commitment_gallons=8000, equipment_value_cents=480000
        )
        unit = create_unit(
            outlet["id"], agreement["id"],
            serial_number="SN-9001", installed_at="2025-11-01T00:00:00Z",
        )
        activate_agreement(agreement["id"])
        task = create_task(unit["id"], "SANITATION", "2026-07-01T00:00:00Z")

        evaluated = validate_success(api.evaluate_task_due(task["id"], OFFICER))
        assert evaluated["status"] == "OVERDUE"

        reconciled = validate_success(api.get_outlet(outlet["id"], OFFICER))
        assert reconciled["overdue_task_count"] == 1
        assert reconciled["service_posture"] == "RESTRICTED"
        assert reconciled["open_compliance_hold_count"] == 0
        assert read_task(task["id"])["breach_kind"] == "DATE"
