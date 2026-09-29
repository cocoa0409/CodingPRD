"""Declared initial states, the withdrawal cascade, phase close-out and the issuance ledger row."""

from __future__ import annotations

from decimal import Decimal

import pytest

from test_helpers import (
    acknowledged_plan,
    activate_phase,
    assert_field_equals,
    assert_item_state,
    assert_ledger_contains,
    assert_plan_dimensions,
    assert_posture,
    book_crew,
    bootstrap_portfolio,
    close_out_phase,
    get_success_data,
    issued_plan,
    ledger_entries,
    list_rows,
    read_booking,
    read_extension,
    read_franchisee,
    read_item,
    read_phase,
    read_plan,
    read_property,
    register_contractor,
    request_extension,
    schedule_inspection,
    schedule_phase,
    scope_plan,
    set_clock,
)


@pytest.fixture
def freshly_created_rows(api):
    """One draft plan with an item, a scoping visit and a closure window, all newly created."""
    portfolio = bootstrap_portfolio(
        api, "Quarrystone Hotels LLC", "development@quarrystonehotels.example"
    )
    scenario = scope_plan(
        api,
        portfolio,
        [
            {
                "key": "receiving",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-2.1.1",
                "brand_estimated_cost_cents": 600000,
            }
        ],
    )
    inspection = schedule_inspection(
        api, scenario, scheduled_date="2026-08-20", inspection_type="SCOPING"
    )
    phase = schedule_phase(
        api,
        scenario,
        phase_number=1,
        start_date="2026-09-01",
        end_date="2026-09-05",
        rooms_out_of_service=12,
    )
    return scenario, inspection, phase


class TestDeclaredInitialStates:
    def test_a_scoped_plan_and_its_item_start_where_the_contract_says(
        self, api, freshly_created_rows
    ):
        """"The plan is born with `status` at `DRAFT` and `dispute_state` at `NONE`". "A new item is
        created with `status` `SCOPED`, with `approved_cost_cents` equal to its
        `brand_estimated_cost_cents`, with `owner_claimed_cost_cents` null, with
        `extension_days_granted` at 0, with `item_funding_cents` at 0, and with `deadline_date`,
        `priority_rank` and `is_overdue` left null, null and false respectively for as long as the
        plan remains `DRAFT`." Every resource also carries "`version`, an integer that starts at 1 on
        creation and increments by one on every mutation of that row".

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        scenario, _inspection, _phase = freshly_created_rows

        plan = read_plan(api, scenario.plan_id)
        item = read_item(api, scenario.item_id("receiving"))

        assert_plan_dimensions(plan, status="DRAFT", dispute_state="NONE")
        assert_item_state(item, status="SCOPED", is_overdue=False)
        assert_field_equals(item, "version", 1, "item")
        assert_field_equals(item, "approved_cost_cents", 600000, "item")
        assert_field_equals(item, "extension_days_granted", 0, "item")
        assert_field_equals(item, "item_funding_cents", 0, "item")
        assert item["priority_rank"] is None, f"unexpected rank on a draft item: {item!r}"
        assert item["owner_claimed_cost_cents"] is None, f"unexpected claim in {item!r}"

    def test_a_new_inspection_starts_scheduled_with_an_empty_punch_list(
        self, api, freshly_created_rows
    ):
        """"The inspection is created in `SCHEDULED` with `punch_open_count` 0 and `performed_at`,
        `signed_off_at` and `signed_off_by_user_id` all null."

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        _scenario, inspection, _phase = freshly_created_rows

        assert_field_equals(inspection, "status", "SCHEDULED", "inspection")
        assert_field_equals(inspection, "punch_open_count", 0, "inspection")
        for field in ("performed_at", "signed_off_at", "signed_off_by_user_id"):
            assert inspection[field] is None, (
                f"a scheduled visit carries a null {field}, got {inspection[field]!r}"
            )

    def test_a_new_phase_starts_planned_holding_no_keys_yet(self, api, freshly_created_rows):
        """"The phase is created in `PLANNED` with `ooo_pct_at_activation` null." "The number of
        closed nights is the count of days from `start_date` to `end_date` inclusive — the difference
        between the two dates plus one." "the recapture is 30 percent, that is 0.30, when the ratio is
        below 0.10".

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        scenario, _inspection, phase = freshly_created_rows

        assert_field_equals(phase, "status", "PLANNED", "phase")
        assert phase["ooo_pct_at_activation"] is None, (
            f"only activation writes ooo_pct_at_activation, got {phase!r}"
        )
        assert_field_equals(phase, "displacement_revenue_impact_cents", 529200, "phase")
        assert_field_equals(
            read_property(api, scenario.property_id), "rooms_out_of_service_current", 0, "property"
        )


@pytest.fixture
def issued_plan_with_a_pending_extension(api, brand_manager):
    """Two issued items, one of them deferred behind an extension request, then withdrawn."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "alarm_panel",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-9.1.1",
                "brand_estimated_cost_cents": 500000,
            },
            {
                "key": "soft_goods",
                "category": "GUEST_FACING",
                "standards_reference": "GF-9.1.1",
                "brand_estimated_cost_cents": 500000,
            },
        ],
        legal_name="Thistlewood Lodging LLC",
        contact_email="asset@thistlewoodlodging.example",
    )
    request = request_extension(
        api,
        scenario,
        scenario.item_id("soft_goods"),
        requested_days=30,
        business_justification=(
            "The soft goods package ships from a single mill whose dye lot is delayed by six weeks."
        ),
    )
    get_success_data(api.withdraw_plan(scenario.plan_id, brand_manager))
    return scenario, request


class TestWithdrawalFromIssued:
    def test_withdrawal_voids_every_open_item_of_the_plan(
        self, api, issued_plan_with_a_pending_extension
    ):
        """"Both source states behave identically: `DRAFT → WITHDRAWN` and `ISSUED → WITHDRAWN` each
        void every item of the plan whose `status` is `SCOPED` or `DEFERRED_PENDING_EXTENSION`".

        Design: Corner/state_machines/withdrawal_from_issued_voids_open_items_and_clears_the_property
        """
        scenario, _request = issued_plan_with_a_pending_extension

        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="WITHDRAWN")
        assert_item_state(read_item(api, scenario.item_id("alarm_panel")), status="VOIDED")
        assert_item_state(read_item(api, scenario.item_id("soft_goods")), status="VOIDED")

    def test_the_voided_scope_empties_every_plan_aggregate(
        self, api, issued_plan_with_a_pending_extension
    ):
        """"every item of the plan whose `status` is `SCOPED`, `DEFERRED_PENDING_EXTENSION`,
        `IN_PROGRESS`, `WORK_COMPLETE` or `PUNCH_FAIL` becomes `VOIDED` and thereby leaves every plan
        aggregate". "An empty included set yields 0 for both totals, 0 variance and `0.00` for the
        variance percentage."

        Design: Corner/state_machines/withdrawal_from_issued_voids_open_items_and_clears_the_property
        """
        scenario, _request = issued_plan_with_a_pending_extension

        plan = read_plan(api, scenario.plan_id)

        assert_field_equals(plan, "scope_item_count", 0, "plan")
        assert_field_equals(plan, "brand_scoped_total_cents", 0, "plan")
        assert_field_equals(plan, "owner_claimed_total_cents", 0, "plan")
        assert_field_equals(plan, "funding_requirement_cents", 0, "plan")

    def test_the_property_and_the_portfolio_come_back_clean(
        self, api, issued_plan_with_a_pending_extension
    ):
        """"recompute the property's `open_plan_count`, `compliance_risk_score` and
        `compliance_posture` and then the franchisee's `standing`, and increment the plan's `version`
        by one." "The franchisee's `standing` then rolls up across every property it owns:
        `TERMINATED_PORTFOLIO` when any of its properties is `TERMINATED`, else `DEFAULT` when any is
        `IN_DEFAULT`, else `WATCH` when any is `AT_RISK`, else `GOOD`."

        Design: Corner/state_machines/withdrawal_from_issued_voids_open_items_and_clears_the_property
        """
        scenario, request = issued_plan_with_a_pending_extension

        prop = read_property(api, scenario.property_id)

        assert_posture(prop, 100, "COMPLIANT")
        assert_field_equals(prop, "open_plan_count", 0, "property")
        assert_field_equals(
            read_franchisee(api, scenario.franchisee_id), "standing", "GOOD", "franchisee"
        )
        assert_field_equals(
            read_extension(api, request["id"]), "status", "SUBMITTED", "extension request"
        )


@pytest.fixture
def active_phase_with_a_booked_crew(api):
    """An active closure window holding a tenth of the keys, with one crew booked inside it."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "service_lift",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-3.3.3",
                "brand_estimated_cost_cents": 600000,
            }
        ],
        legal_name="Vinegrove Hospitality LLC",
        contact_email="construction@vinegrovehospitality.example",
    )
    phase = schedule_phase(
        api,
        scenario,
        phase_number=1,
        start_date="2026-09-01",
        end_date="2026-09-10",
        rooms_out_of_service=20,
    )
    contractor = register_contractor(
        api,
        name="Westline Interiors",
        trade="GENERAL",
        brand_approved=False,
        max_concurrent_bookings=1,
    )
    set_clock(api, "2026-09-01T00:00:00Z")
    phase = activate_phase(api, scenario, phase["id"])
    booking = book_crew(
        api,
        scenario,
        contractor["id"],
        phase["id"],
        start_datetime="2026-09-02T08:00:00Z",
        end_datetime="2026-09-04T17:00:00Z",
        crew_size=8,
    )
    return scenario, phase, booking


class TestPhaseCloseOutCompletesItsBookings:
    def test_close_out_completes_the_engagements_rather_than_cancelling_them(
        self, api, active_phase_with_a_booked_crew
    ):
        """"Close-out subtracts the phase's `rooms_out_of_service` from the property's
        `rooms_out_of_service_current`, increments the property's `version`, restores the
        key-inventory invariant of §2.10, and marks every booking of the phase that is still
        `BOOKED` as `COMPLETED`, freeing that contractor's capacity."

        Design: Corner/state_machines/phase_closeout_completes_its_contractor_bookings
        """
        scenario, phase, booking = active_phase_with_a_booked_crew

        closed = close_out_phase(api, scenario, phase["id"])

        assert_field_equals(closed, "status", "CLOSED_OUT", "phase")
        assert_field_equals(read_booking(api, booking["id"]), "status", "COMPLETED", "booking")
        assert_field_equals(
            read_property(api, scenario.property_id), "rooms_out_of_service_current", 0, "property"
        )

    def test_the_activation_figures_and_the_plan_survive_the_close_out(
        self, api, active_phase_with_a_booked_crew
    ):
        """"Activation adds the phase's `rooms_out_of_service` to the property's
        `rooms_out_of_service_current` and increments the property's `version`, recomputes
        `displacement_revenue_impact_cents` against the property's current `adr_baseline_cents` and
        `occupancy_baseline_pct`, and writes `ooo_pct_at_activation` as the phase's own
        out-of-service ratio rounded half up to 4 decimal places". "15 percent, that is 0.15, when the
        ratio is at least 0.10 and below 0.25".

        Design: Corner/state_machines/phase_closeout_completes_its_contractor_bookings
        """
        scenario, phase, _booking = active_phase_with_a_booked_crew
        close_out_phase(api, scenario, phase["id"])

        settled = read_phase(api, phase["id"])

        assert Decimal(str(settled["ooo_pct_at_activation"])) == Decimal("0.1000"), (
            "20 of 200 keys is a ratio of 0.1000 at activation, got "
            f"{settled['ooo_pct_at_activation']!r}"
        )
        assert_field_equals(settled, "displacement_revenue_impact_cents", 2142000, "phase")
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="OWNER_ACKNOWLEDGED")

    def test_no_engagement_of_the_phase_is_left_booked(self, api, active_phase_with_a_booked_crew):
        """"A booking is created in `BOOKED`; `CANCELLED` and `COMPLETED` are reached only through
        the phase cascades above, which means the filtered booking list is the only channel through
        which those cascade-driven states can be observed."

        Design: Corner/state_machines/phase_closeout_completes_its_contractor_bookings
        """
        scenario, phase, _booking = active_phase_with_a_booked_crew
        close_out_phase(api, scenario, phase["id"])

        booked, booked_meta = list_rows(
            api, "list_contractor_bookings", phase_id=phase["id"], status="BOOKED"
        )
        _completed, completed_meta = list_rows(
            api, "list_contractor_bookings", phase_id=phase["id"], status="COMPLETED"
        )

        assert booked_meta["total_count"] == 0, (
            f"no engagement of a closed-out phase stays BOOKED, got {booked}"
        )
        assert completed_meta["total_count"] == 1, (
            f"the phase's one engagement should now be COMPLETED, got {completed_meta}"
        )


@pytest.fixture
def plan_issued_with_two_life_safety_items(api):
    """Two life-safety items issued together, so one ledger row must carry their whole total."""
    return issued_plan(
        api,
        [
            {
                "key": "standpipe",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-2.2.1",
                "brand_estimated_cost_cents": 300000,
            },
            {
                "key": "egress_lighting",
                "category": "LIFE_SAFETY",
                "standards_reference": "LS-2.2.2",
                "brand_estimated_cost_cents": 700000,
            },
        ],
        legal_name="Wrenfield Hotels LLC",
        contact_email="compliance@wrenfieldhotels.example",
    )


class TestIssuanceLedgerRow:
    def test_issuance_appends_exactly_one_scope_issued_row(
        self, api, plan_issued_with_two_life_safety_items
    ):
        """"It appends a ledger entry of type `SCOPE_ISSUED` with a null item reference and a
        `delta_cents` equal to the plan's brand-scoped total." "A `ComplianceLedgerEntry` is
        append-only: it carries only `id` and `created_at`."

        Design: Corner/state_machines/issuance_appends_a_scope_issued_ledger_row_matching_the_plan_total
        """
        scenario = plan_issued_with_two_life_safety_items

        entry = assert_ledger_contains(
            ledger_entries(api, plan_id=scenario.plan_id),
            "SCOPE_ISSUED",
            delta_cents=1000000,
            item_id=None,
            count=1,
        )

        assert entry["recorded_at_clock"] == "2026-08-01T00:00:00Z", (
            f"the row must carry the issuance clock instant, got {entry!r}"
        )

    def test_the_row_reconciles_with_the_plan_it_records(
        self, api, plan_issued_with_two_life_safety_items
    ):
        """"The **brand-scoped variant**, published as `brand_scoped_total_cents`, always reads
        `brand_estimated_cost_cents` and ignores every owner claim; it is the sole input to the
        funding maths." "Only after every item has been individually rounded are those rounded
        figures summed, and the sum is the plan's `funding_requirement_cents`."

        Design: Corner/state_machines/issuance_appends_a_scope_issued_ledger_row_matching_the_plan_total
        """
        scenario = plan_issued_with_two_life_safety_items

        plan = read_plan(api, scenario.plan_id)

        assert_field_equals(plan, "brand_scoped_total_cents", 1000000, "plan")
        assert_field_equals(plan, "funding_requirement_cents", 1100000, "plan")

    def test_no_other_entry_type_was_written_by_issuance(
        self, api, plan_issued_with_two_life_safety_items
    ):
        """"Filter parameters on list endpoints behave differently from path identifiers: a filter
        value that resolves to nothing — a `plan_id` that does not exist, a `status` no row currently
        holds — yields an empty page with `total_count` of 0, never a 404."

        Design: Corner/state_machines/issuance_appends_a_scope_issued_ledger_row_matching_the_plan_total
        """
        scenario = plan_issued_with_two_life_safety_items

        rows, meta = list_rows(
            api,
            "list_compliance_ledger_entries",
            plan_id=scenario.plan_id,
            entry_type="DEFAULT_ISSUED",
        )

        assert meta["total_count"] == 0, (
            f"issuance writes no DEFAULT_ISSUED row, got {meta} with {rows}"
        )
