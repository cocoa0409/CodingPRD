"""One triggering scenario for each remaining refusal in the error catalogue.

Every test drives the refusal on state that would otherwise have satisfied the
neighbouring rules, then reads the affected rows back to show that the rejected
request left nothing behind.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    activate_agreement,
    add_stop,
    add_telemetry,
    allocate,
    ApiErrorId,
    arrive_call,
    create_agreement,
    create_agreement_payload,
    create_call,
    create_dispenser_unit_payload,
    create_maintenance_task_payload,
    create_outlet,
    create_outlet_payload,
    create_position,
    create_route,
    create_route_payload,
    create_route_stop_payload,
    create_supply_item,
    create_supply_item_payload,
    create_supply_position_payload,
    create_task,
    create_unit,
    create_van_part_stock_payload,
    create_van_stock,
    dispatch_call,
    dispatch_call_payload,
    escalate_call,
    escalate_call_payload,
    outlet_version,
    pin_clock,
    read_agreement,
    read_call,
    read_outlet,
    read_position,
    read_route,
    read_stop,
    read_supply_item,
    read_task,
    read_unit,
    read_van_stock,
    recall_decision_payload,
    resolve_call_payload,
    route_version,
    run_forecast,
    setup_shortfall_review,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]
TECH = TEST_USERS["technician_headers"]
OFFICER = TEST_USERS["officer_headers"]

CLOCK = "2026-08-01T00:00:00Z"


def _outlet(account_code="OUT-1001", name="Riverside Diner", region_code="R-WEST"):
    pin_clock(CLOCK)
    return create_outlet(name=name, account_code=account_code, region_code=region_code)


def _outlet_agreement_and_unit(activate=True, installed_at="2025-11-01T00:00:00Z",
                               **agreement_overrides):
    """Riverside Diner, an 8000-gallon agreement, and one IN_SERVICE machine."""
    outlet = _outlet()
    terms = {"annual_commitment_gallons": 8000, "equipment_value_cents": 480000}
    terms.update(agreement_overrides)
    agreement = create_agreement(outlet["id"], **terms)
    unit = create_unit(
        outlet["id"], agreement["id"],
        serial_number="SN-9001", installed_at=installed_at,
    )
    if activate:
        activate_agreement(agreement["id"])
    return outlet, agreement, unit


class TestServiceCallRefusals:
    def test_a_third_escalation_is_refused_after_two_round_trips(self, api):
        """PRD §3.8: "A technician may escalate `ON_SITE → ESCALATED` only while
        `escalation_count` is strictly below 2, and an attempt once it has reached 2 is
        refused with `ERR_ESCALATION_LIMIT_REACHED`; a call can therefore travel the
        `DISPATCHED → ON_SITE → ESCALATED → DISPATCHED` cycle at most twice." Re-dispatch
        itself stays legal: "Dispatch is a `ServiceTechnician` action and is declared from
        two states: `OPEN → DISPATCHED` for a fresh call, and `ESCALATED → DISPATCHED`
        for a call handed back for another attempt, which is legal while
        `escalation_count` is at most 2."

        Design: Corner/errors/err_escalation_limit_reached_on_the_third_escalation
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        call = create_call(unit["id"], "LEAK", CLOCK)
        for window_start, window_end in (
            ("2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z"),
            ("2026-08-02T13:00:00Z", "2026-08-02T15:00:00Z"),
        ):
            dispatch_call(call["id"], "VAN-7", window_start, window_end, TECH)
            arrive_call(call["id"], TECH)
            escalate_call(call["id"], "PART_UNAVAILABLE", TECH)
        dispatch_call(
            call["id"], "VAN-7", "2026-08-02T17:00:00Z", "2026-08-02T19:00:00Z", TECH
        )
        arrive_call(call["id"], TECH)

        validate_error(
            api.escalate_service_call(
                call["id"], escalate_call_payload("PART_UNAVAILABLE"), TECH
            ),
            ApiErrorId.ERR_ESCALATION_LIMIT_REACHED,
            409,
        )

        held = read_call(call["id"])
        assert held["status"] == "ON_SITE"
        assert held["escalation_count"] == 2
        assert held["van_code"] == "VAN-7"
        assert held["assigned_tech_user_id"] == TECH["X-User-ID"]

    def test_fitting_more_parts_than_were_held_is_refused(self, api):
        """PRD §3.8: "The technician supplies the `resolution_code`, one of
        `PART_REPLACED`, `CALIBRATED`, `CLEANED` or `NO_FAULT_FOUND`, and optionally the
        `consumed_part_units` actually fitted, which may not exceed the
        `reserved_part_units` the call is holding — an excess is
        `ERR_CONSUMED_EXCEEDS_RESERVED`." Per §2.6 rung 27: "`consumed_part_units` must
        not exceed the call's `reserved_part_units`, otherwise
        `ERR_CONSUMED_EXCEEDS_RESERVED` (422) on
        `POST /fountain-network/service-calls/{id}/resolve`."

        Design: Corner/errors/err_consumed_exceeds_reserved_units_on_resolve
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        stock = create_van_stock("VAN-7", "PUMP_ASSY_12", 5)
        call = create_call(unit["id"], "NO_POUR", CLOCK)
        dispatch_call(
            call["id"], "VAN-7", "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z", TECH,
            part_sku="PUMP_ASSY_12", part_units=2,
        )
        arrive_call(call["id"], TECH)

        validate_error(
            api.resolve_service_call(
                call["id"],
                resolve_call_payload("PART_REPLACED", consumed_part_units=3),
                TECH,
            ),
            ApiErrorId.ERR_CONSUMED_EXCEEDS_RESERVED,
            422,
        )

        untouched_call = read_call(call["id"])
        assert untouched_call["status"] == "ON_SITE"
        assert untouched_call["reserved_part_units"] == 2
        untouched_stock = read_van_stock(stock["id"])
        assert untouched_stock["on_van_units"] == 3
        assert untouched_stock["reserved_units"] == 2
        assert untouched_stock["consumed_units"] == 0

    def test_reserving_a_part_the_van_does_not_carry_is_refused(self, api):
        """PRD §3.8: "Where a part is requested, the van stock row for that van and that
        part must exist — otherwise `ERR_PART_NOT_ON_VAN` — and must carry at least
        `part_units` in `on_van_units`, otherwise `ERR_INSUFFICIENT_VAN_PARTS`." Per §2.6
        rung 25: "When `part_sku` is supplied, a van stock row must exist for that van and
        that part, otherwise `ERR_PART_NOT_ON_VAN` (404) on
        `POST /fountain-network/service-calls/{id}/dispatch`."

        Design: Corner/errors/err_part_not_on_van_for_an_unstocked_part_sku
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        stock = create_van_stock("VAN-7", "PUMP_ASSY_12", 5)
        call = create_call(unit["id"], "CO2_LOW", CLOCK)

        validate_error(
            api.dispatch_service_call(
                call["id"],
                dispatch_call_payload(
                    "VAN-7", "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z",
                    part_sku="GASKET_KIT_04", part_units=1,
                ),
                TECH,
            ),
            ApiErrorId.ERR_PART_NOT_ON_VAN,
            404,
        )

        undispatched = read_call(call["id"])
        assert undispatched["status"] == "OPEN"
        assert undispatched["van_code"] is None
        assert undispatched["reserved_part_stock_id"] is None
        kept = read_van_stock(stock["id"])
        assert kept["on_van_units"] == 5
        assert kept["reserved_units"] == 0


class TestMaintenanceTaskRefusals:
    def test_a_filter_change_without_its_gallon_interval_is_refused(self, api):
        """PRD §3.5: "One optional input, `gallon_interval`, expresses the nominal
        gallons-since-last-change that also trips the task, and it is tied strictly to one
        task type: it is required when `task_type` is `FILTER_CHANGE`, and its absence
        there is `ERR_GALLON_INTERVAL_REQUIRED`; it must be absent for every other task
        type, and its presence there is `ERR_GALLON_INTERVAL_NOT_APPLICABLE`."

        Design: Corner/errors/err_gallon_interval_required_for_a_filter_change_task
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()

        validate_error(
            api.create_maintenance_task(
                create_maintenance_task_payload(
                    unit["id"], "FILTER_CHANGE", "2026-09-01T00:00:00Z"
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_GALLON_INTERVAL_REQUIRED,
            422,
        )

        assert read_unit(unit["id"])["version"] == 1

    def test_a_preventive_task_carrying_a_gallon_interval_is_refused(self, api):
        """PRD §3.5: "One optional input, `gallon_interval`, expresses the nominal
        gallons-since-last-change that also trips the task, and it is tied strictly to one
        task type: it is required when `task_type` is `FILTER_CHANGE`, and its absence
        there is `ERR_GALLON_INTERVAL_REQUIRED`; it must be absent for every other task
        type, and its presence there is `ERR_GALLON_INTERVAL_NOT_APPLICABLE`." Per §2.6
        rung 28: "On `POST /fountain-network/maintenance-tasks`, `gallon_interval` must be
        present when `task_type` is `FILTER_CHANGE` — its absence is
        `ERR_GALLON_INTERVAL_REQUIRED` (422) — and must be absent for every other
        `task_type`, its presence being `ERR_GALLON_INTERVAL_NOT_APPLICABLE` (422)."

        Design: Corner/errors/err_gallon_interval_not_applicable_on_a_preventive_task
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()

        validate_error(
            api.create_maintenance_task(
                create_maintenance_task_payload(
                    unit["id"], "PREVENTIVE", "2026-09-01T00:00:00Z",
                    gallon_interval=4000,
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_GALLON_INTERVAL_NOT_APPLICABLE,
            422,
        )

        assert read_unit(unit["id"])["version"] == 1

    def test_completing_a_calibration_without_a_measurement_is_refused(self, api):
        """PRD §3.5: "A `BRIX_CALIBRATION` completion requires `measured_brix_ratio` in
        the request — its absence is `ERR_BRIX_MEASUREMENT_REQUIRED` — and writes the
        task's `calibration_outcome` together with the machine's `brix_ratio_last_measured`
        and `calibration_status` as graded in §3.3; `measured_brix_ratio` is ignored on
        every other task type." The machine therefore keeps what §3.3 gave it: "A newly
        recorded unit answers 201 with `status` `IN_SERVICE`, `calibration_status`
        `UNVERIFIED`, `lifetime_dispensed_gallons` at 0, `gallons_at_last_filter_change`
        at 0, `brix_ratio_last_measured` null and `version` 1."

        Design: Corner/errors/err_brix_measurement_required_when_completing_a_calibration
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        task = create_task(unit["id"], "BRIX_CALIBRATION", "2026-09-01T00:00:00Z")

        validate_error(
            api.complete_task(task["id"], TECH, {}),
            ApiErrorId.ERR_BRIX_MEASUREMENT_REQUIRED,
            422,
        )

        unchanged = read_task(task["id"])
        assert unchanged["status"] == "SCHEDULED"
        assert unchanged["calibration_outcome"] is None
        assert unchanged["version"] == 1
        assert read_unit(unit["id"])["calibration_status"] == "UNVERIFIED"


class TestAgreementRefusals:
    def test_a_term_that_ends_before_it_starts_is_refused(self, api):
        """PRD §2.6 rung 21: "Every submitted interval must have its end bound strictly
        after its start bound: `term_end_date` after `term_start_date`, `window_end` after
        `window_start`, `scheduled_window_end` after `scheduled_window_start`,
        `promo_window_end` after `promo_window_start`, and `period_end_date` after
        `period_start_date`. A violation yields `ERR_INVALID_INTERVAL` (422)." The same
        section promises that "Nothing is persisted when a request fails at any rung of
        this ladder."

        Design: Corner/errors/err_invalid_interval_when_the_agreement_term_ends_before_it_starts
        """
        outlet = _outlet()

        validate_error(
            api.create_agreement(
                create_agreement_payload(
                    outlet["id"], outlet_version(outlet["id"]),
                    term_start_date="2027-01-01T00:00:00Z",
                    term_end_date="2026-01-01T00:00:00Z",
                    annual_commitment_gallons=8000,
                    equipment_value_cents=480000,
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_INVALID_INTERVAL,
            422,
        )

        untouched = read_outlet(outlet["id"])
        assert untouched["version"] == 1
        assert untouched["status"] == "ACTIVE"

    def test_closing_the_term_before_it_has_elapsed_is_refused(self, api):
        """PRD §3.2: "A `NetworkAdmin` closes the term of an `ACTIVE` agreement, moving it
        `ACTIVE → EXPIRED` and incrementing its `version` by one, but only once the
        logical clock has reached or passed the agreement's `term_end_date`; attempting it
        earlier is `ERR_TERM_NOT_ELAPSED`."

        Design: Corner/errors/err_term_not_elapsed_before_the_term_end_date
        """
        outlet, agreement, _unit = _outlet_agreement_and_unit()

        validate_error(
            api.close_term(agreement["id"], ADMIN),
            ApiErrorId.ERR_TERM_NOT_ELAPSED,
            409,
        )

        standing = read_agreement(agreement["id"])
        assert standing["status"] == "ACTIVE"
        assert standing["version"] == 2
        assert read_outlet(outlet["id"])["status"] == "ACTIVE"

    def test_an_assessment_that_yields_no_fee_is_refused(self, api):
        """PRD §3.9: "The quarterly commitment is the agreement's
        `annual_commitment_gallons` divided by four, held exactly and **never** rounded."
        With the quarter met there is nothing to charge: "If the assessment produces a fee
        of zero cents there is nothing to review, and the whole request is refused with
        `ERR_NO_SHORTFALL_TO_ASSESS` — the agreement stays `ACTIVE`." The poured volume is
        on the machine's odometer, per §3.4: "Each ingestion refreshes the receiving
        machine's `lifetime_dispensed_gallons`, which is defined as the total ounces ever
        reported for that unit divided by 128 and then rounded half up to two decimal
        places."

        Design: Corner/errors/err_no_shortfall_to_assess_when_telemetry_meets_the_quarter_commitment
        """
        _outlet, agreement, unit = _outlet_agreement_and_unit()
        item = create_supply_item(
            sku_code="SKU-COLA", brand_name="Cola Classic", supply_form="BAG_IN_BOX",
            case_pack_units=4, ounces_per_unit=2000, national_allocation_units=100,
        )
        add_telemetry(unit["id"], item["id"], 256000, "2026-07-15T00:00:00Z")

        validate_error(
            api.assess_shortfall(
                agreement["id"],
                {
                    "period_start_date": "2026-07-01T00:00:00Z",
                    "period_end_date": "2026-10-01T00:00:00Z",
                },
                ADMIN,
            ),
            ApiErrorId.ERR_NO_SHORTFALL_TO_ASSESS,
            422,
        )

        unassessed = read_agreement(agreement["id"])
        assert unassessed["status"] == "ACTIVE"
        assert unassessed["assessed_shortfall_gallons"] == pytest.approx(0, abs=0.01)
        assert unassessed["assessed_fee_cents"] == 0
        assert unassessed["shortfall_assessed_by_user_id"] is None
        assert unassessed["version"] == 2
        assert read_unit(unit["id"])["lifetime_dispensed_gallons"] == pytest.approx(
            2000.00, abs=0.01
        )

    def test_purchased_equipment_cannot_be_recalled_however_valuable(self, api):
        """PRD §3.9: "The equipment must actually be recallable, meaning the agreement's
        `free_on_loan` is true; equipment the outlet purchased outright cannot be taken
        back and the attempt is refused with `ERR_RECALL_NOT_PERMITTED`." The exposure
        that would otherwise have cleared the floor is computed as: "Under the
        `BOOK_VALUE` variant the unit's exposure is the agreement's
        `equipment_value_cents` multiplied by one minus one percent per whole month in
        service, with that multiplier clamped up to zero so a very old machine is worth
        nothing rather than a negative amount."

        Design: Corner/errors/err_recall_not_permitted_on_purchased_equipment
        """
        base, _item, reviewed = setup_shortfall_review(
            annual_commitment_gallons=8000,
            equipment_value_cents=480000,
            installed_at="2026-07-20T00:00:00Z",
            assess_clock=CLOCK,
            period_start_date="2026-07-01T00:00:00Z",
            period_end_date="2026-10-01T00:00:00Z",
            exposure_variant="BOOK_VALUE",
            free_on_loan=False,
        )
        assert reviewed["status"] == "SHORTFALL_REVIEW"

        validate_error(
            api.recall_decision(
                base.agreement_id, recall_decision_payload("RECALL"), OFFICER
            ),
            ApiErrorId.ERR_RECALL_NOT_PERMITTED,
            422,
        )

        refused = read_agreement(base.agreement_id)
        assert refused["recall_exposure_cents"] == 480000
        assert refused["status"] == "SHORTFALL_REVIEW"
        assert refused["recall_decided_by_user_id"] is None
        assert read_unit(base.unit_id)["status"] == "IN_SERVICE"


class TestUniquenessRefusals:
    def test_an_account_code_cannot_be_reused_in_another_region(self, api):
        """PRD §3.1: "The `account_code` must not already belong to another outlet; a
        collision is `ERR_DUPLICATE_ACCOUNT_CODE`." The uniqueness scopes are listed in
        §2.6 rung 30: "An outlet's `account_code`, a dispenser's `serial_number`, a supply
        item's `sku_code`, a route's `route_code`, the outlet-and-SKU pair behind a supply
        position, the van-and-part pair behind a van stock row, and a stop's
        `sequence_index` within its route are each unique."

        Design: Corner/errors/err_duplicate_account_code_on_a_second_outlet
        """
        outlet = _outlet()

        validate_error(
            api.create_outlet(
                create_outlet_payload(
                    name="Eastside Grill", account_code="OUT-1001",
                    region_code="R-EAST",
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_DUPLICATE_ACCOUNT_CODE,
            409,
        )

        original = read_outlet(outlet["id"])
        assert original["name"] == "Riverside Diner"
        assert original["region_code"] == "R-WEST"

    def test_a_serial_number_cannot_be_reused_under_another_agreement(self, api):
        """PRD §3.3: "The `serial_number` must be unique across the whole fleet, with
        `ERR_DUPLICATE_SERIAL_NUMBER` on a collision, and the submitted `outlet_id` must
        match the `outlet_id` recorded on the submitted agreement, with
        `ERR_OUTLET_AGREEMENT_MISMATCH` when the two disagree."

        Design: Corner/errors/err_duplicate_serial_number_under_a_second_agreement
        """
        outlet, _agreement, unit = _outlet_agreement_and_unit(activate=False)
        neighbour = create_outlet(
            name="Eastside Grill", account_code="OUT-1002", region_code="R-EAST"
        )
        neighbour_agreement = create_agreement(
            neighbour["id"], annual_commitment_gallons=4000,
            equipment_value_cents=300000,
        )

        validate_error(
            api.create_dispenser_unit(
                create_dispenser_unit_payload(
                    neighbour["id"], neighbour_agreement["id"],
                    serial_number="SN-9001", model_code="FREESTYLE_7100",
                    installed_at="2026-01-15T00:00:00Z",
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_DUPLICATE_SERIAL_NUMBER,
            409,
        )

        placed = read_unit(unit["id"])
        assert placed["outlet_id"] == outlet["id"]
        assert placed["model_code"] == "FREESTYLE_9100"

    def test_a_sku_code_cannot_be_reused_in_another_supply_form(self, api):
        """PRD §3.6: "Each carries a `sku_code`, unique across the catalogue with
        `ERR_DUPLICATE_SKU_CODE` on a collision; a `brand_name`, which is the grouping
        label the brand-mix report reports against; a `supply_form` of either `CARTRIDGE`
        or `BAG_IN_BOX`; a `case_pack_units` count of at least 1, which is the indivisible
        shippable case size; and an `ounces_per_unit` figure greater than zero stating how
        many finished-beverage ounces one unit yields, which is the bridge that turns
        telemetry ounces into orderable units."

        Design: Corner/errors/err_duplicate_sku_code_on_a_second_supply_item
        """
        pin_clock(CLOCK)
        item = create_supply_item(
            sku_code="SKU-COLA", brand_name="Cola Classic", supply_form="BAG_IN_BOX",
            case_pack_units=4, ounces_per_unit=2000, national_allocation_units=100,
        )

        validate_error(
            api.create_supply_item(
                create_supply_item_payload(
                    sku_code="SKU-COLA", brand_name="Cola Classic",
                    supply_form="CARTRIDGE", case_pack_units=6, ounces_per_unit=1000,
                    national_allocation_units=50,
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_DUPLICATE_SKU_CODE,
            409,
        )

        catalogued = read_supply_item(item["id"])
        assert catalogued["supply_form"] == "BAG_IN_BOX"
        assert catalogued["case_pack_units"] == 4
        assert catalogued["national_allocation_units"] == 100

    def test_a_route_code_cannot_be_reused_on_another_day(self, api):
        """PRD §3.7: "A `SupplyPlanner` plans a **ReplenishmentRoute** out of one depot
        for one day and one van, supplying a `route_code` that must be unique across all
        routes — a collision is `ERR_DUPLICATE_ROUTE_CODE` — together with the
        `depot_region_code` the route serves, the `service_date` on which it runs expressed
        as an ISO 8601 UTC midnight instant, the `van_code` of the van that will run it,
        and a `capacity_units` figure of at least 1 giving the total consumable units the
        van can carry."

        Design: Corner/errors/err_duplicate_route_code_on_a_second_route
        """
        pin_clock(CLOCK)
        route = create_route(
            route_code="RT-01", depot_region_code="R-WEST",
            service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
        )

        validate_error(
            api.create_route(
                create_route_payload(
                    route_code="RT-01", depot_region_code="R-WEST",
                    service_date="2026-08-04T00:00:00Z", van_code="VAN-9",
                    capacity_units=30,
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_DUPLICATE_ROUTE_CODE,
            409,
        )

        planned = read_route(route["id"])
        assert planned["van_code"] == "VAN-7"
        assert planned["capacity_units"] == 60
        assert planned["version"] == 1

    def test_one_outlet_and_sku_pair_can_hold_only_one_position(self, api):
        """PRD §3.6: "The outlet-and-SKU pair is unique, so a second position for the same
        combination is `ERR_DUPLICATE_SUPPLY_POSITION`." The first position keeps what it
        was opened with: "A newly opened position answers 201 with `forecast_variant`
        recorded as `TRAILING_ACTUAL`, `forecast_units` at 0, `requested_units` at 0,
        `allocated_units` at 0, `planned_route_stop_id` null, `alert_level` `NONE`,
        `promo_suppressed` false, `alert_acknowledged_by_user_id` null and `version` 1."

        Design: Corner/errors/err_duplicate_supply_position_for_the_same_outlet_and_sku
        """
        outlet = _outlet()
        item = create_supply_item(
            sku_code="SKU-COLA", brand_name="Cola Classic", supply_form="BAG_IN_BOX",
            case_pack_units=4, ounces_per_unit=2000, national_allocation_units=100,
        )
        position = create_position(outlet["id"], item["id"], 2)

        validate_error(
            api.create_supply_position(
                create_supply_position_payload(outlet["id"], item["id"], on_hand_units=9),
                PLANNER,
            ),
            ApiErrorId.ERR_DUPLICATE_SUPPLY_POSITION,
            409,
        )

        opened = read_position(position["id"])
        assert opened["on_hand_units"] == 2
        assert opened["version"] == 1

    def test_a_second_row_for_the_same_van_and_part_is_refused(self, api):
        """PRD §3.8: "The van-and-part pair is unique, so a duplicate load is
        `ERR_DUPLICATE_VAN_PART`." Adding units has its own route: "A `NetworkAdmin`
        restocks a row by supplying a count of `units`, which raises both `on_van_units`
        and `restocked_units` by that amount and advances the row's `version` by one;
        restocking is the only operation that raises the row's conserved total."

        Design: Corner/errors/err_duplicate_van_part_for_the_same_van_and_part_sku
        """
        pin_clock(CLOCK)
        stock = create_van_stock("VAN-7", "PUMP_ASSY_12", 5)

        validate_error(
            api.create_van_part_stock(
                create_van_part_stock_payload("VAN-7", "PUMP_ASSY_12", 3), ADMIN
            ),
            ApiErrorId.ERR_DUPLICATE_VAN_PART,
            409,
        )

        loaded = read_van_stock(stock["id"])
        assert loaded["on_van_units"] == 5
        assert loaded["initial_units"] == 5
        assert loaded["restocked_units"] == 0

    def test_a_stop_sequence_cannot_repeat_even_with_a_free_window(self, api):
        """PRD §3.7: "The `sequence_index` must be at least 1 and must not already be used
        by another stop of the same route, a collision being `ERR_DUPLICATE_STOP_SEQUENCE`."
        The first stop's own write is what advanced the route: "A created stop answers 201
        with `status` `PENDING`, `delivered_units` at 0, `skip_reason_code` null and
        `version` 1, and the owning route's `version` also increments by one."

        Design: Corner/errors/err_duplicate_stop_sequence_with_disjoint_windows
        """
        outlet = _outlet()
        route = create_route(
            route_code="RT-01", depot_region_code="R-WEST",
            service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
        )
        stop = add_stop(
            route["id"], outlet["id"], 1,
            "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z",
        )

        validate_error(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(
                    outlet["id"], route_version(route["id"]), sequence_index=1,
                    window_start="2026-08-03T11:00:00Z",
                    window_end="2026-08-03T12:00:00Z",
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_DUPLICATE_STOP_SEQUENCE,
            409,
        )

        only_stop = read_stop(stop["id"])
        assert only_stop["sequence_index"] == 1
        assert only_stop["status"] == "PENDING"
        assert read_route(route["id"])["version"] == 2


class TestPoolGuard:
    def test_the_pool_cannot_be_cut_below_what_is_already_reserved(self, api):
        """PRD §3.6: "One guard applies: `national_allocation_units` may never be lowered
        below the SKU's current `reserved_pool_units`, since that would leave more units
        committed to routes than the pool contains, and the attempt is refused with
        `ERR_POOL_BELOW_RESERVED`."

        Design: Corner/errors/err_pool_below_reserved_when_a_patch_undercuts_the_reservation
        """
        outlet, _agreement, unit = _outlet_agreement_and_unit(activate=False)
        item = create_supply_item(
            sku_code="SKU-COLA", brand_name="Cola Classic", supply_form="BAG_IN_BOX",
            case_pack_units=4, ounces_per_unit=2000, national_allocation_units=8,
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
        allocate(stop["id"], [position["id"]])

        validate_error(
            api.patch_supply_item(item["id"], {"national_allocation_units": 3}, ADMIN),
            ApiErrorId.ERR_POOL_BELOW_RESERVED,
            422,
        )

        guarded = read_supply_item(item["id"])
        assert guarded["national_allocation_units"] == 8
        assert guarded["reserved_pool_units"] == 4
        assert guarded["version"] == 2


class TestRequestGates:
    def test_a_request_without_headers_is_rejected_before_its_body_is_read(self, api):
        """PRD §2.1: "If either header is absent, or if `X-User-Role` is not exactly one of
        the six declared role names, the request is rejected with `ERR_UNAUTHENTICATED`
        and HTTP 401. This is the very first check performed on any request."

        Design: Corner/errors/err_unauthenticated_outranks_the_malformed_body
        """
        outlet = _outlet()

        validate_error(
            api.create_outlet({"name": "Ghost Diner"}, {}),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )

        untouched = read_outlet(outlet["id"])
        assert untouched["account_code"] == "OUT-1001"
        assert untouched["version"] == 1

    def test_a_page_size_above_the_cap_is_rejected_rather_than_clamped(self, api):
        """PRD §2.5: "`limit` caps the number of items returned; when it is omitted it
        defaults to 10, its minimum accepted value is 1 and its maximum accepted value is
        100. A `limit` below 1 or above 100 is a malformed request and is rejected with
        `ERR_INVALID_REQUEST` and HTTP 400."

        Design: Corner/errors/err_invalid_request_when_the_pagination_limit_exceeds_the_cap
        """
        outlet = _outlet()

        validate_error(
            api.list_outlets(ADMIN, {"limit": 101}),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        assert read_outlet(outlet["id"])["version"] == 1
