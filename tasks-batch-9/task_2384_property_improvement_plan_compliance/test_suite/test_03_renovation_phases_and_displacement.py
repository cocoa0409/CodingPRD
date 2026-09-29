"""The closure calendar, the out-of-service cap, displacement revenue and key inventory."""

from __future__ import annotations

from decimal import Decimal

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledged_plan,
    activate_phase,
    assert_field_equals,
    assert_key_inventory_conserved,
    close_out_phase,
    issued_plan,
    list_rows,
    read_phase,
    read_property,
    renovation_phase_payload,
    schedule_phase,
    set_clock,
    validate_error,
    validate_success,
)


@pytest.fixture
def two_scheduled_phases(api):
    """A quarter of the keys held out of service by the first phase, one more key by the second."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "kitchen",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-4.1.1",
                "brand_estimated_cost_cents": 500000,
            }
        ],
        legal_name="Stonebridge Hotels LLC",
        contact_email="ops@stonebridgehotels.example",
    )
    first = schedule_phase(
        api,
        scenario,
        phase_number=1,
        start_date="2026-09-01",
        end_date="2026-09-10",
        rooms_out_of_service=50,
    )
    second = schedule_phase(
        api,
        scenario,
        phase_number=2,
        start_date="2026-09-13",
        end_date="2026-09-20",
        rooms_out_of_service=1,
    )
    set_clock(api, "2026-09-01T00:00:00Z")
    first = activate_phase(api, scenario, first["id"])
    return scenario, first, second


class TestOutOfServiceCapAtActivation:
    def test_a_ratio_of_exactly_a_quarter_is_admitted(self, api, two_scheduled_phases):
        """"the comparison is inclusive, so a ratio of exactly 0.25 is admitted and only a ratio
        strictly greater than 0.25 is refused with `ERR_OOO_CAP_EXCEEDED` (409)". Activation
        "writes `ooo_pct_at_activation` as the phase's own out-of-service ratio rounded half up to
        4 decimal places — a field only the activation writes".

        Design: Difficulty/boundary_precision_check/out_of_service_ratio_boundary_at_activation
        """
        _scenario, first, _second = two_scheduled_phases

        assert_field_equals(first, "status", "ACTIVE", "first phase")
        assert Decimal(str(first["ooo_pct_at_activation"])) == Decimal("0.2500"), (
            "50 of 200 keys is a ratio of 0.2500 at activation, got "
            f"{first['ooo_pct_at_activation']!r}"
        )

    def test_a_quarter_of_the_keys_falls_in_the_zero_recapture_band(
        self, api, two_scheduled_phases
    ):
        """"the recapture is 30 percent, that is 0.30, when the ratio is below 0.10; 15 percent,
        that is 0.15, when the ratio is at least 0.10 and below 0.25; and zero when the ratio is
        0.25 or above. Note that tier selection is inclusive on the lower edge of each band, so a
        ratio of exactly 0.25 lands in the zero-recapture band even though the cap rule above
        still admits it."

        Design: Difficulty/boundary_precision_check/out_of_service_ratio_boundary_at_activation
        """
        _scenario, first, _second = two_scheduled_phases

        assert_field_equals(
            first, "displacement_revenue_impact_cents", 6300000, "first phase"
        )

    def test_activation_re_evaluates_the_cap_against_the_then_current_position(
        self, api, two_scheduled_phases
    ):
        """"The identical ratio is re-evaluated at activation against the property's
        *then-current* `rooms_out_of_service_current`, not against the position that held at
        creation — a phase that fitted when it was scheduled can therefore be refused activation
        because another phase went active in the meantime."

        Design: Difficulty/boundary_precision_check/out_of_service_ratio_boundary_at_activation
        """
        scenario, _first, second = two_scheduled_phases

        response = api.activate_renovation_phase(second["id"], scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_OOO_CAP_EXCEEDED, 409)
        refused = read_phase(api, second["id"])
        assert_field_equals(refused, "status", "PLANNED", "second phase")
        assert refused["ooo_pct_at_activation"] is None, (
            "a phase refused activation keeps a null ooo_pct_at_activation, got "
            f"{refused['ooo_pct_at_activation']!r}"
        )
        assert_field_equals(
            read_property(api, scenario.property_id),
            "rooms_out_of_service_current",
            50,
            "property",
        )


@pytest.fixture
def plan_with_one_planned_phase(api):
    """An issued plan carrying a single planned closure window ending 2026-09-10."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "laundry",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-6.2.1",
                "brand_estimated_cost_cents": 500000,
            }
        ],
        legal_name="Alderwood Inns LLC",
        contact_email="pm@alderwoodinns.example",
    )
    first = schedule_phase(
        api,
        scenario,
        phase_number=1,
        start_date="2026-09-01",
        end_date="2026-09-10",
        rooms_out_of_service=10,
    )
    return scenario, first


class TestChangeoverBufferOnTheClosureCalendar:
    def test_an_adjacent_successor_is_refused(self, api, plan_with_one_planned_phase):
        """"Concretely, a phase ending `2026-09-10` admits a successor starting `2026-09-13` but
        rejects one starting `2026-09-12` — adjacency is forbidden here, unlike the contractor
        rule below."

        Design: Difficulty/resource_temporal_overlap/phase_window_changeover_buffer_forbids_adjacency
        """
        scenario, _first = plan_with_one_planned_phase

        response = api.create_renovation_phase(
            renovation_phase_payload(
                scenario.plan_id,
                phase_number=2,
                start_date="2026-09-12",
                end_date="2026-09-20",
                rooms_out_of_service=10,
            ),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_PHASE_WINDOW_CONFLICT, 409)

    def test_a_successor_starting_past_the_buffer_is_admitted(
        self, api, plan_with_one_planned_phase
    ):
        """"each phase's closed date interval is expanded by a mandatory two-day changeover buffer
        on its **end** side. Two phases of the same plan conflict when the new phase's
        `start_date` is no later than the other phase's `end_date` advanced by two days *and* the
        other phase's `start_date` is no later than the new phase's `end_date` advanced by two
        days; both conditions must hold for a conflict."

        Design: Difficulty/resource_temporal_overlap/phase_window_changeover_buffer_forbids_adjacency
        """
        scenario, _first = plan_with_one_planned_phase

        created = validate_success(
            api.create_renovation_phase(
                renovation_phase_payload(
                    scenario.plan_id,
                    phase_number=2,
                    start_date="2026-09-13",
                    end_date="2026-09-20",
                    rooms_out_of_service=10,
                ),
                scenario.owner_headers,
            ),
            expected_status=201,
        )

        assert_field_equals(created, "status", "PLANNED", "successor phase")

    def test_both_windows_sit_on_the_calendar_without_taking_keys_yet(
        self, api, plan_with_one_planned_phase
    ):
        """"The phase is created in `PLANNED` with `ooo_pct_at_activation` null." "Activating a
        phase ... adds the phase's `rooms_out_of_service` to the property's
        `rooms_out_of_service_current`".

        Design: Difficulty/resource_temporal_overlap/phase_window_changeover_buffer_forbids_adjacency
        """
        scenario, first = plan_with_one_planned_phase
        validate_success(
            api.create_renovation_phase(
                renovation_phase_payload(
                    scenario.plan_id,
                    phase_number=2,
                    start_date="2026-09-13",
                    end_date="2026-09-20",
                    rooms_out_of_service=10,
                ),
                scenario.owner_headers,
            ),
            expected_status=201,
        )

        rows, meta = list_rows(api, "list_renovation_phases", plan_id=scenario.plan_id)

        assert meta["total_count"] == 2, f"the plan should carry two phases, got {meta}"
        assert_field_equals(read_phase(api, first["id"]), "status", "PLANNED", "first phase")
        assert_field_equals(
            read_property(api, scenario.property_id),
            "rooms_out_of_service_current",
            0,
            "property",
        )
        assert len(rows) == 2, f"both phases should be listed, got {len(rows)}"


@pytest.fixture
def active_phase_holding_forty_keys(api):
    """Forty of two hundred keys out of service under an active closure window."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "back_corridor",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-8.1.1",
                "brand_estimated_cost_cents": 500000,
            }
        ],
        legal_name="Havenbrook Lodging LLC",
        contact_email="ops@havenbrooklodging.example",
    )
    phase = schedule_phase(
        api,
        scenario,
        phase_number=1,
        start_date="2026-09-01",
        end_date="2026-09-10",
        rooms_out_of_service=40,
    )
    set_clock(api, "2026-09-01T00:00:00Z")
    phase = activate_phase(api, scenario, phase["id"])
    return scenario, phase


class TestKeyInventoryConservation:
    def test_activation_debits_sellable_keys_and_credits_keys_out_of_service(
        self, api, active_phase_holding_forty_keys
    ):
        """"`rooms_out_of_service_current` must equal the sum of `rooms_out_of_service` over the
        renovation phases of that property's plans that are currently active, and
        `rooms_out_of_service_current` plus the derived count of sellable keys must equal
        `room_count`."

        Design: Difficulty/compensating_invariant/room_inventory_conserved_across_phase_activation_and_closeout
        """
        scenario, phase = active_phase_holding_forty_keys

        prop = read_property(api, scenario.property_id)

        assert_field_equals(prop, "rooms_out_of_service_current", 40, "property")
        assert_key_inventory_conserved(prop, [phase])

    def test_close_out_restores_the_split_exactly(self, api, active_phase_holding_forty_keys):
        """"Close-out subtracts the phase's `rooms_out_of_service` from the property's
        `rooms_out_of_service_current`, increments the property's `version`, restores the
        key-inventory invariant of §2.10". "closing the phase out and cancelling it are the two
        compensating actions, and both restore the split exactly".

        Design: Difficulty/compensating_invariant/room_inventory_conserved_across_phase_activation_and_closeout
        """
        scenario, phase = active_phase_holding_forty_keys

        closed = close_out_phase(api, scenario, phase["id"])

        prop = read_property(api, scenario.property_id)
        assert_field_equals(closed, "status", "CLOSED_OUT", "phase")
        assert_field_equals(prop, "rooms_out_of_service_current", 0, "property")
        assert_key_inventory_conserved(prop, [])

    def test_no_phase_remains_active_after_close_out(self, api, active_phase_holding_forty_keys):
        """"`CLOSED_OUT` and `CANCELLED` are the terminal phase states." "The conflict is
        evaluated against every other phase of the same plan whose `status` is `PLANNED` or
        `ACTIVE`; phases that are `CLOSED_OUT` or `CANCELLED` free their window."

        Design: Difficulty/compensating_invariant/room_inventory_conserved_across_phase_activation_and_closeout
        """
        scenario, phase = active_phase_holding_forty_keys
        close_out_phase(api, scenario, phase["id"])

        rows, meta = list_rows(
            api, "list_renovation_phases", plan_id=scenario.plan_id, status="ACTIVE"
        )

        assert meta["total_count"] == 0, f"no phase should still be ACTIVE, got {meta}"
        assert rows == [], f"the active-phase page should be empty, got {rows}"

    def test_the_activation_snapshot_survives_the_close_out(
        self, api, active_phase_holding_forty_keys
    ):
        """"The phase's `displacement_revenue_impact_cents` is that rounded gross figure
        multiplied by one minus the recapture fraction, rounded half up to whole cents again — the
        second rounding. The order is pinned: round the gross first, then apply the recapture and
        round again."

        Design: Difficulty/compensating_invariant/room_inventory_conserved_across_phase_activation_and_closeout
        """
        scenario, phase = active_phase_holding_forty_keys
        close_out_phase(api, scenario, phase["id"])

        settled = read_phase(api, phase["id"])

        assert Decimal(str(settled["ooo_pct_at_activation"])) == Decimal("0.2000"), (
            "40 of 200 keys is a ratio of 0.2000 at activation, got "
            f"{settled['ooo_pct_at_activation']!r}"
        )
        assert_field_equals(
            settled, "displacement_revenue_impact_cents", 4284000, "phase"
        )
