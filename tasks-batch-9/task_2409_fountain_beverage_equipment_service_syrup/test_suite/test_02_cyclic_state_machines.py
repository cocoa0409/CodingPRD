"""State cycles that re-enter a state they have already left.

An outlet travels ACTIVE → SUSPENDED → ACTIVE → SUSPENDED, and a service call
travels DISPATCHED → ON_SITE → ESCALATED → DISPATCHED while its van reservation
is unwound and re-taken at a different size.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    activate_agreement,
    arrive_call,
    create_agreement,
    create_call,
    create_outlet,
    create_unit,
    create_van_stock,
    dispatch_call,
    escalate_call,
    outlet_status_change_payload,
    pin_clock,
    read_agreement,
    read_call,
    read_outlet,
    read_unit,
    read_van_stock,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
TECH = TEST_USERS["technician_headers"]
TECH_ALT = TEST_USERS["technician_alt_headers"]


def _outlet_holding_equipment():
    """Outlet at version 2 with a DRAFT agreement and one IN_SERVICE unit."""
    pin_clock("2026-08-01T00:00:00Z")
    outlet = create_outlet(
        name="Campus Union Deli",
        account_code="ACCT-NL-A",
        region_code="R5",
        throughput_tier="MEDIUM",
        water_hardness_gpg=10,
    )
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=4000,
        equipment_value_cents=300000,
        free_on_loan=True,
        shortfall_fee_cents_per_gallon=40,
    )
    unit = create_unit(
        outlet["id"],
        agreement["id"],
        serial_number="SN-NL-A-01",
        installed_at="2026-02-01T00:00:00Z",
    )
    return outlet, agreement, unit


def _call_on_a_loaded_van():
    """An OPEN NO_POUR call plus a van stock row holding five pump assemblies."""
    pin_clock("2026-08-01T00:00:00Z")
    outlet = create_outlet(
        name="Turnpike Plaza 3",
        account_code="ACCT-NL-B",
        region_code="R6",
        throughput_tier="MEDIUM",
        water_hardness_gpg=10,
    )
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=4000,
        equipment_value_cents=300000,
        free_on_loan=True,
        shortfall_fee_cents_per_gallon=40,
    )
    unit = create_unit(
        outlet["id"],
        agreement["id"],
        serial_number="SN-NL-B-01",
        installed_at="2026-02-01T00:00:00Z",
    )
    activate_agreement(agreement["id"])
    stock = create_van_stock("V-77", "PUMP_ASSY_12", 5)
    call = create_call(unit["id"], "NO_POUR", "2026-08-01T00:00:00Z")
    return unit, stock, call


class TestOutletStatusCycle:
    def test_reinstatement_genuinely_returns_the_outlet_to_active(self, api):
        """PRD §3.1: "`SUSPEND` drives the outlet `ACTIVE → SUSPENDED`. `REINSTATE`
        drives it `SUSPENDED → ACTIVE`, and is legal only while no compliance hold
        is open".

        Design: Difficulty/non_linear_state_machine/outlet_suspend_reinstate_suspend_cycle_preserves_version_monotonicity
        """
        outlet, _agreement, _unit = _outlet_holding_equipment()

        first = validate_success(
            api.outlet_status_change(
                outlet["id"], outlet_status_change_payload("SUSPEND"), ADMIN
            )
        )
        assert first["status"] == "SUSPENDED"

        reinstated = validate_success(
            api.outlet_status_change(
                outlet["id"], outlet_status_change_payload("REINSTATE"), ADMIN
            )
        )
        assert reinstated["status"] == "ACTIVE"

        second = validate_success(
            api.outlet_status_change(
                outlet["id"], outlet_status_change_payload("SUSPEND"), ADMIN
            )
        )
        assert second["status"] == "SUSPENDED"

    def test_each_accepted_transition_advances_the_version_without_resetting_it(self, api):
        """PRD §3.1: "Each of these three actions increments the outlet's `version`
        by one."

        Design: Difficulty/non_linear_state_machine/outlet_suspend_reinstate_suspend_cycle_preserves_version_monotonicity
        """
        outlet, agreement, unit = _outlet_holding_equipment()
        assert read_outlet(outlet["id"])["version"] == 2

        for action in ("SUSPEND", "REINSTATE", "SUSPEND"):
            validate_success(
                api.outlet_status_change(
                    outlet["id"], outlet_status_change_payload(action), ADMIN
                )
            )

        final = read_outlet(outlet["id"])
        assert final["version"] == 5
        assert final["status"] == "SUSPENDED"
        assert final["service_posture"] == "OPEN"
        assert final["open_compliance_hold_count"] == 0
        assert final["overdue_task_count"] == 0
        assert read_agreement(agreement["id"])["status"] == "DRAFT"
        assert read_unit(unit["id"])["status"] == "IN_SERVICE"


class TestServiceCallEscalationLoop:
    def test_escalation_reverses_the_reservation_and_frees_the_call(self, api):
        """PRD §3.8: "Escalation fully reverses the parts reservation as a
        compensating movement — every unit held in `reserved_units` for this call
        returns to `on_van_units`, and the call's `reserved_part_units` returns to
        0 with `reserved_part_stock_id` set to null — raises `escalation_count` by
        one, clears `van_code`, `scheduled_window_start`, `scheduled_window_end`
        and `assigned_tech_user_id` so the call is free for re-dispatch".

        Design: Difficulty/non_linear_state_machine/service_call_on_site_escalated_dispatched_loop_reindexes_parts
        """
        _unit, stock, call = _call_on_a_loaded_van()

        dispatch_call(
            call["id"], "V-77", "2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z", TECH,
            part_sku="PUMP_ASSY_12", part_units=2,
        )
        arrive_call(call["id"], TECH)
        escalated = escalate_call(call["id"], "PART_MISMATCH", TECH)

        assert escalated["status"] == "ESCALATED"
        assert escalated["escalation_count"] == 1
        assert escalated["van_code"] is None
        assert escalated["assigned_tech_user_id"] is None
        assert escalated["reserved_part_units"] == 0
        assert escalated["reserved_part_stock_id"] is None

        after = read_van_stock(stock["id"])
        assert after["on_van_units"] == 5
        assert after["reserved_units"] == 0
        assert after["consumed_units"] == 0

    def test_redispatch_out_of_escalated_reserves_a_new_quantity_for_a_new_technician(
        self, api
    ):
        """PRD §3.8: "A successful dispatch writes `van_code`, both window bounds
        and `assigned_tech_user_id` from the acting `X-User-ID`, overwriting
        whatever a previous dispatch had left there when the call is being
        re-dispatched out of `ESCALATED`."

        Design: Difficulty/non_linear_state_machine/service_call_on_site_escalated_dispatched_loop_reindexes_parts
        """
        _unit, stock, call = _call_on_a_loaded_van()

        dispatch_call(
            call["id"], "V-77", "2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z", TECH,
            part_sku="PUMP_ASSY_12", part_units=2,
        )
        arrive_call(call["id"], TECH)
        escalate_call(call["id"], "PART_MISMATCH", TECH)

        redispatched = dispatch_call(
            call["id"], "V-77", "2026-08-01T13:00:00Z", "2026-08-01T15:00:00Z", TECH_ALT,
            part_sku="PUMP_ASSY_12", part_units=3,
        )

        assert redispatched["status"] == "DISPATCHED"
        assert redispatched["assigned_tech_user_id"] == TECH_ALT["X-User-ID"]
        assert redispatched["reserved_part_units"] == 3
        assert redispatched["reserved_part_stock_id"] == stock["id"]

        after = read_van_stock(stock["id"])
        assert after["on_van_units"] == 2
        assert after["reserved_units"] == 3
        assert after["consumed_units"] == 0
        assert (
            after["on_van_units"] + after["reserved_units"] + after["consumed_units"]
            == after["initial_units"] + after["restocked_units"] == 5
        )

        final = read_call(call["id"])
        assert final["escalation_count"] == 1
        assert final["severity_score"] == 60
        assert final["severity"] == "URGENT"
        assert final["version"] == 5
