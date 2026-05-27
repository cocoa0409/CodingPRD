"""Non-linear state machines: divergent side-effect branches and revert cycles.
Queue A (Difficulty)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    set_clock,
    setup_confirmed_reservation,
    setup_pending_reservation,
    create_pending_reservation,
    confirm_reservation,
    cancel_reservation,
    fetch_reservation,
    fetch_guest,
    fetch_dining_plan,
    list_credit_ledger_for_reservation,
    list_no_show_assessments_for_reservation,
    cancel_reservation_payload,
    create_allergy_meal_payload,
    make_guest_headers,
    make_restaurant_headers,
)


# ─── Reservation CONFIRMED branching ─────────────────────────────────────

class TestReservationConfirmedBranching:
    """Difficulty/non_linear_state_machine/reservation_branching_confirmed_to_cancelled_vs_no_show_divergent_side_effects"""

    def test_cancelled_releases_credits_but_no_strike_no_assessment(self, api):
        """PRD §3.4: "Cancellation from CONFIRMED requires expected_reservation_version,
        runs the OCC check, reverses the hold (decrement the plan's
        table_service_credits_held by Reservation.credits_held, zero
        Reservation.credits_held, append a CreditLedgerEntry of entry_type RELEASE
        with a credits_delta equal to the negated released quantity), and cascades
        any LightningLaneAddOn for this reservation that is in REQUESTED or
        ALLOCATED to CANCELLED."

        Design: Difficulty/non_linear_state_machine/reservation_branching_confirmed_to_cancelled_vs_no_show_divergent_side_effects
        """
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=2,
            dining_plan_credit_cost=1,
            table_service_credits_initial=10,
        )
        # Cancel within free-cancel window (clock at 2026-01-15 vs slot 2026-02-15).
        cancelled = cancel_reservation(
            reservation["id"], reservation["version"], guest["id"],
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["credits_held"] == 0
        plan = fetch_dining_plan(dp["id"], guest["id"])
        assert plan["table_service_credits_held"] == 0
        assert plan["table_service_credits_remaining"] == 10
        # No strike, no NoShowFeeAssessment.
        g = fetch_guest(guest["id"])
        assert g["no_show_strike_count"] == 0
        assessments = list_no_show_assessments_for_reservation(reservation["id"])
        assert not any(a["reservation_id"] == reservation["id"] for a in assessments)
        # CreditLedgerEntry RELEASE with credits_delta = -2 exists.
        entries = list_credit_ledger_for_reservation(reservation["id"])
        rel = [e for e in entries
               if e["entry_type"] == "RELEASE"
               and e["credits_delta"] == -2
               and e["dining_plan_id"] == dp["id"]]
        assert len(rel) >= 1

    def test_no_show_branch_increments_strike_and_creates_assessment(self, api):
        """PRD §3.5: "Either path runs the same cascade, in this order: the platform
        increments the booking Guest.no_show_strike_count by 1 ... it creates a
        NoShowFeeAssessment (described below); it decreases the plan's
        table_service_credits_held by the reservation's credits_held and appends
        a CreditLedgerEntry of entry_type RELEASE with a negative credits_delta
        equal to the released quantity (no-show releases the hold but does not
        debit the plan)"

        The companion divergent branch to the CANCELLED test: NO_SHOW also releases
        credits but additionally bumps strike count and creates an assessment.

        Design: Difficulty/non_linear_state_machine/reservation_branching_confirmed_to_cancelled_vs_no_show_divergent_side_effects
        """
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=2,
            dining_plan_credit_cost=1,
            no_show_base_fee_cents=1000,
            is_character_dining=False,
            table_service_credits_initial=10,
        )
        set_clock("2026-02-15T19:00:00Z")
        from test_helpers import TEST_USERS
        marked = validate_success(
            api.mark_no_show_reservation(reservation["id"], TEST_USERS["platform_admin_headers"]),
            expected_status=200,
        )
        assert marked["status"] == "NO_SHOW"
        # Strike incremented.
        g = fetch_guest(guest["id"])
        assert g["no_show_strike_count"] == 1
        # Assessment created.
        assessments = list_no_show_assessments_for_reservation(reservation["id"])
        relevant = [a for a in assessments if a["reservation_id"] == reservation["id"]]
        assert len(relevant) == 1
        # Plan credits released (held = 0; remaining unchanged).
        plan = fetch_dining_plan(dp["id"], guest["id"])
        assert plan["table_service_credits_held"] == 0
        assert plan["table_service_credits_remaining"] == 10


# ─── AllergyMeal revert cycle ────────────────────────────────────────────

class TestAllergyMealRevertCycle:
    """Difficulty/non_linear_state_machine/allergy_meal_revert_cycle_acknowledged_to_requested"""

    def test_acknowledge_revert_acknowledge_cycle(self, api):
        """PRD §3.6: "The kitchen may also bounce an acknowledged meal back to
        REQUESTED — the revert loop, valid only while the reservation is in
        CONFIRMED or CHECKED_IN — when allergens need amending."
        PRD §3.6: "The kitchen acknowledges the request, advancing REQUESTED to
        ACKNOWLEDGED, but this action is only valid when the underlying
        reservation is in CONFIRMED, CHECKED_IN, or SEATED."

        Design: Difficulty/non_linear_state_machine/allergy_meal_revert_cycle_acknowledged_to_requested
        """
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=2,
            is_character_dining=True,
            park_code="EPCOT",
            opening_local_time="08:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
        )
        # Create allergy meal.
        am = validate_success(
            api.create_allergy_meal(
                create_allergy_meal_payload(
                    reservation_id=reservation["id"],
                    allergen_codes=["PEANUT", "TREE_NUT"],
                ),
                make_guest_headers(guest["id"]),
            ),
            expected_status=201,
        )
        assert am["status"] == "REQUESTED"
        rh = make_restaurant_headers(restaurant["id"])
        # ACK1.
        ack1 = validate_success(
            api.acknowledge_allergy_meal(am["id"], rh), expected_status=200,
        )
        assert ack1["status"] == "ACKNOWLEDGED"
        # Revert.
        reverted = validate_success(
            api.revert_allergy_meal(am["id"], rh), expected_status=200,
        )
        assert reverted["status"] == "REQUESTED"
        # ACK2.
        ack2 = validate_success(
            api.acknowledge_allergy_meal(am["id"], rh), expected_status=200,
        )
        assert ack2["status"] == "ACKNOWLEDGED"

    def test_each_transition_increments_version(self, api):
        """PRD §2.4: "The version field is an integer that begins at 1 on creation
        and is incremented by exactly 1 on every server-committed mutation"

        After ack → revert → ack, the AllergyMeal version must strictly increase
        across each commit (3 mutations beyond create).

        Design: Difficulty/non_linear_state_machine/allergy_meal_revert_cycle_acknowledged_to_requested
        """
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=2,
            is_character_dining=True,
            park_code="EPCOT",
            opening_local_time="08:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
        )
        am = validate_success(
            api.create_allergy_meal(
                create_allergy_meal_payload(
                    reservation_id=reservation["id"],
                    allergen_codes=["PEANUT"],
                ),
                make_guest_headers(guest["id"]),
            ),
            expected_status=201,
        )
        v_created = am["version"]
        rh = make_restaurant_headers(restaurant["id"])
        v_ack1 = validate_success(api.acknowledge_allergy_meal(am["id"], rh), 200)["version"]
        v_revert = validate_success(api.revert_allergy_meal(am["id"], rh), 200)["version"]
        v_ack2 = validate_success(api.acknowledge_allergy_meal(am["id"], rh), 200)["version"]
        assert v_ack1 > v_created
        assert v_revert > v_ack1
        assert v_ack2 > v_revert
