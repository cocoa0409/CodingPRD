"""Appointment and recurring-plan lifecycles: the cyclic re-quote loop, the fork
to CANCELLED, the plan pause/resume/generate cycle, initial states, and invalid
transition rejections.

Difficulty queue: non_linear_state_machine.
Corner queue: state_machines.
"""
from test_helpers import validate_error, ApiErrorId
from test_helpers import fixtures as fx


class TestRequoteLoopAndFork:
    def test_requote_increments_quote_round(self, api):
        """PRD §3.3: "Each quote issuance — first quote or re-quote — recomputes
        both the duration estimate and the forward-looking price from the pet, tier,
        and currently attached add-ons, pins them onto the appointment, increments
        quote_round by one, and bumps the appointment's version."

        Design: Difficulty/non_linear_state_machine/appointment_requote_loop_then_fork_cancel
        """
        fx.set_clock("2026-06-12T08:00:00Z")
        world = fx.setup_world(zip_code="90005", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=50,
                               with_groomer=False)
        appt = fx.create_appointment(world["pet"]["id"], world["tier"]["id"], world["customer"]["id"])
        fx.quote(appt["id"])
        second = fx.quote(appt["id"])
        assert second["status"] == "QUOTED", second
        assert second["quote_round"] == 2, second

    def test_quoted_forks_to_cancelled(self, api):
        """PRD §3.5: "Cancelling a QUOTED appointment likewise moves it to CANCELLED
        with no fee."

        Design: Difficulty/non_linear_state_machine/appointment_requote_loop_then_fork_cancel
        """
        fx.set_clock("2026-06-12T08:00:00Z")
        world = fx.setup_world(zip_code="90005", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=50,
                               with_groomer=False)
        appt = fx.create_appointment(world["pet"]["id"], world["tier"]["id"], world["customer"]["id"])
        fx.quote(appt["id"])
        fx.quote(appt["id"])
        cancelled = fx.cancel(appt["id"], world["customer"]["id"])
        assert cancelled["status"] == "CANCELLED", cancelled


class TestRecurringPlanCycle:
    def _plan(self, zip_code="90006"):
        tier = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=45, coat_type="DOUBLE", size_class="SMALL")
        customer = fx.create_customer(service_zip=zip_code)
        pet = fx.create_pet(customer["id"], breed["id"], weight_lbs=25)
        plan = fx.create_recurring_plan(pet["id"], tier["id"], customer["id"],
                                        cadence_days=28, discount_pct=0.05)
        return customer, plan

    def test_pause_moves_to_paused(self, api):
        """PRD §3.8: "The owning customer ... may pause an ACTIVE plan, moving it to
        PAUSED and suspending generation, and may resume a PAUSED plan back to ACTIVE
        to resume generation."

        Design: Difficulty/non_linear_state_machine/recurring_plan_pause_resume_cycle
        """
        customer, plan = self._plan()
        paused = fx.get_success_data(api.pause_recurring_plan(
            plan["id"], fx.make_customer_headers(customer["id"])))
        assert paused["status"] == "PAUSED", paused

    def test_resume_returns_to_active_and_generates(self, api):
        """PRD §3.8: "may resume a PAUSED plan back to ACTIVE to resume generation."
        PRD §3.8: "Generation creates a new REQUESTED appointment with its
        recurring_plan_id set to this plan and its service_tier_id copied from the
        plan, and bumps the plan's version."

        Design: Difficulty/non_linear_state_machine/recurring_plan_pause_resume_cycle
        """
        customer, plan = self._plan()
        ch = fx.make_customer_headers(customer["id"])
        fx.get_success_data(api.pause_recurring_plan(plan["id"], ch))
        resumed = fx.get_success_data(api.resume_recurring_plan(plan["id"], ch))
        assert resumed["status"] == "ACTIVE", resumed
        appt = fx.generate_plan_appointment(plan["id"])
        assert appt["recurring_plan_id"] == plan["id"], appt
        assert appt["status"] == "REQUESTED", appt


class TestInitialAndInvalidTransitions:
    def test_new_appointment_starts_requested(self, api):
        """PRD §3.3: "The new appointment enters REQUESTED status with a quote_round
        of 0 and all computed pricing and duration fields at their zero defaults."

        Design: Corner/state_machines/new_appointment_starts_in_requested
        """
        tier = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=60, size_class="GIANT")
        customer = fx.create_customer(service_zip="10009")
        pet = fx.create_pet(customer["id"], breed["id"], weight_lbs=120)
        appt = fx.create_appointment(pet["id"], tier["id"], customer["id"])
        assert appt["status"] == "REQUESTED", appt
        assert appt["quote_round"] == 0, appt

    def test_quote_on_completed_is_invalid_state(self, api):
        """PRD §3.4: "First, the appointment must currently be QUOTED; attempting to
        schedule from any other state yields ERR_INVALID_STATE (HTTP 409)."
        PRD §3.3: "A dispatcher issues a quote, which advances a REQUESTED
        appointment to QUOTED."

        Design: Corner/state_machines/quote_from_completed_returns_invalid_state
        """
        fx.set_clock("2026-07-01T08:00:00Z")
        world = fx.setup_world(zip_code="10007", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=30,
                               window_start="2026-07-01T09:00:00Z",
                               window_end="2026-07-01T17:00:00Z",
                               service_date="2026-07-01T00:00:00Z")
        appt = fx.create_scheduled_appointment(world, "2026-07-01T09:30:00Z")
        fx.complete(appt["id"], world["groomer"]["id"])
        resp = api.quote_appointment(appt["id"], fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_cancel_terminal_appointment_is_invalid_state(self, api):
        """PRD §3.5: "Cancelling a REQUESTED appointment moves it to CANCELLED with
        no fee, because it was never scheduled."

        Design: Corner/state_machines/cancel_terminal_appointment_returns_invalid_state
        """
        tier = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=50)
        customer = fx.create_customer(service_zip="10008")
        pet = fx.create_pet(customer["id"], breed["id"], weight_lbs=30)
        appt = fx.create_appointment(pet["id"], tier["id"], customer["id"])
        fx.cancel(appt["id"], customer["id"])
        resp = api.cancel_appointment(appt["id"], fx.make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_schedule_unquoted_appointment_is_invalid_state(self, api):
        """PRD §3.4: "First, the appointment must currently be QUOTED; attempting to
        schedule from any other state yields ERR_INVALID_STATE (HTTP 409)."

        Design: Corner/state_machines/schedule_from_requested_unquoted_invalid_state
        """
        fx.set_clock("2026-07-03T08:00:00Z")
        world = fx.setup_world(zip_code="10011", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=55, weight_lbs=30,
                               window_start="2026-07-03T09:00:00Z",
                               window_end="2026-07-03T17:00:00Z",
                               service_date="2026-07-03T00:00:00Z")
        appt = fx.create_appointment(world["pet"]["id"], world["tier"]["id"], world["customer"]["id"])
        # never quoted -> schedule should be rejected on state, not other checks
        resp = api.schedule_appointment(appt["id"], {
            "route_day_id": world["route_day"]["id"],
            "slot_start": "2026-07-03T09:30:00Z",
            "expected_route_day_version": world["rd_version"],
        }, fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_quote_without_vaccination_rejected(self, api):
        """PRD §3.3: "The pet's vaccination_status must be VALID — that is, a
        non-expired RABIES record must exist at the current clock — or the quote is
        rejected with ERR_VACCINATION_REQUIRED (HTTP 422)."

        Design: Corner/state_machines/error_vaccination_required_on_quote
        """
        fx.set_clock("2026-07-02T08:00:00Z")
        tier = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=60, coat_type="DOUBLE", size_class="LARGE")
        customer = fx.create_customer(service_zip="10010")
        pet = fx.create_pet(customer["id"], breed["id"], weight_lbs=70)  # no vaccination
        appt = fx.create_appointment(pet["id"], tier["id"], customer["id"])
        resp = api.quote_appointment(appt["id"], fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_VACCINATION_REQUIRED.value)
        # appointment stays REQUESTED
        after = fx.get_success_data(api.get_appointment(appt["id"], fx.DISPATCH))
        assert after["status"] == "REQUESTED", after
