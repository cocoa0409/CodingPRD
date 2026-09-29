"""Allowance table lookup with its move-type modifier, and the two shipment dimensions."""

import pytest

from test_helpers import (
    COUNSELOR,
    api_client,
    dispute_weight_payload,
    get_success_data,
    pack_shipment,
    pickup_shipment,
    read_entitlement,
    read_shipment,
    record_actual_weight,
    setup_authorized_entitlement,
    setup_awarded_shipment,
)


def _local_move_officer():
    """An O4 with no dependents on local orders, stopped at the draft entitlement."""
    return setup_authorized_entitlement(
        dod_id="7000000011",
        order_number="ORD-A-01",
        member_overrides={
            "rank_code": "O4",
            "branch": "NAVY",
            "dependents_count": 0,
            "spouse_present": False,
        },
        order_overrides={
            "move_type": "LOCAL",
            "origin_market_code": "MKT-ORF",
            "distance_miles": 22,
        },
        session_overrides={"session_type": "VIRTUAL"},
        authorize=False,
    )


def _separating_senior_enlisted():
    """An E9 with three dependents and a spouse, separating from service."""
    return setup_authorized_entitlement(
        dod_id="7000000012",
        order_number="ORD-B-01",
        member_overrides={
            "rank_code": "E9",
            "branch": "MARINE_CORPS",
            "dependents_count": 3,
            "spouse_present": True,
        },
        order_overrides={
            "move_type": "SEPARATION",
            "origin_market_code": "MKT-OAJ",
            "distance_miles": 1340,
        },
        session_overrides={
            "session_type": "IN_PERSON",
            "scheduled_at": "2026-08-06T00:00:00Z",
        },
        authorize=False,
    )


def _shipment_walked_along_both_dimensions():
    """An awarded shipment weighed, packed, disputed and picked up in that order."""
    scenario = setup_awarded_shipment()
    steps = {}
    steps["weighed"] = record_actual_weight(
        scenario, 6200, 1500, weigh_date="2026-08-05T00:00:00Z"
    )
    steps["packed"] = pack_shipment(scenario, pack_date="2026-08-15T00:00:00Z")
    steps["disputed"] = get_success_data(
        api_client.dispute_weight(
            scenario["shipment"]["id"],
            dispute_weight_payload(
                dispute_reason="Tare weight taken with a partially loaded trailer"
            ),
            scenario["member_headers"],
        )
    )
    steps["picked_up"] = pickup_shipment(
        scenario, actual_pickup_date="2026-08-17T00:00:00Z"
    )
    return scenario, steps


class TestWeightAllowanceTableLookup:
    """The table figure is looked up first and only then bent by the move type."""

    def test_a_local_move_halves_the_table_figure(self):
        """An O4 without dependents draws 14,000 pounds, halved to 7,000 for a local move.

        "If the move is `LOCAL`, the table figure is halved and any fraction of a pound is
        discarded, that is, rounded down to a whole pound."

        Design: Difficulty/combinatorial_formula/weight_allowance_table_lookup_with_move_type_floor_and_cap
        """
        scenario = _local_move_officer()
        entitlement = scenario["entitlement"]

        assert entitlement["dependent_status_effective"] == "WITHOUT_DEPENDENTS"
        assert entitlement["base_weight_allowance_lbs"] == 7000
        assert entitlement["total_billable_cap_lbs"] == 7000

    def test_a_separation_move_caps_the_table_figure(self):
        """An E9 with dependents draws 15,000 pounds, capped at the 13,000 pound ceiling.

        "Otherwise, if the move is a `SEPARATION` or a `RETIREMENT`, the figure is capped
        at 13,000 pounds — the lesser of the table figure and 13,000 is taken."

        Design: Difficulty/combinatorial_formula/weight_allowance_table_lookup_with_move_type_floor_and_cap
        """
        scenario = _separating_senior_enlisted()
        entitlement = scenario["entitlement"]

        assert entitlement["dependent_status_effective"] == "WITH_DEPENDENTS"
        assert entitlement["base_weight_allowance_lbs"] == 13000
        assert entitlement["total_billable_cap_lbs"] == 13000

    def test_the_spouse_pro_gear_allowance_needs_both_dependents_and_a_spouse(self):
        """The single officer gets no spouse allowance; the married senior enlisted gets 500.

        "`pro_gear_spouse_allowance_lbs` is 500 pounds when
        `dependent_status_effective` is `WITH_DEPENDENTS` **and** the member's
        `spouse_present` is true, and 0 pounds otherwise."

        Design: Difficulty/combinatorial_formula/weight_allowance_table_lookup_with_move_type_floor_and_cap
        """
        officer = _local_move_officer()["entitlement"]
        enlisted = _separating_senior_enlisted()["entitlement"]

        assert officer["pro_gear_member_allowance_lbs"] == 2000
        assert officer["pro_gear_spouse_allowance_lbs"] == 0
        assert enlisted["pro_gear_member_allowance_lbs"] == 2000
        assert enlisted["pro_gear_spouse_allowance_lbs"] == 500

    def test_the_counseling_deadline_sits_two_weeks_before_the_report_date(self):
        """Orders reporting on 1 October are counseled by 17 September, and this one was.

        "At booking, the server derives `counseling_deadline_at` as the orders'
        `report_no_later_than_date` less a two-week lead time of 14 days."

        Design: Difficulty/combinatorial_formula/weight_allowance_table_lookup_with_move_type_floor_and_cap
        """
        scenario = _local_move_officer()

        session = get_success_data(
            api_client.get_counseling_session(scenario["session"]["id"], COUNSELOR)
        )
        assert session["counseling_deadline_at"] == "2026-09-17T00:00:00Z"
        assert session["is_late_counseling"] is False


class TestMovementAndWeightDimensionsAreIndependent:
    """Movement and weight reconciliation advance without waiting for each other."""

    def test_the_weight_of_record_arrives_while_the_movement_holds_at_surveyed(self):
        """Reading the scale moves only the weight dimension.

        "The weight of record arrives from a truck scale, and recording it is a
        coordinator action that moves `weight_recon_status` `ESTIMATED →
        ACTUAL_RECORDED`."

        Design: Difficulty/non_linear_state_machine/shipment_movement_and_weight_dimensions_advance_independently
        """
        _, steps = _shipment_walked_along_both_dimensions()

        assert steps["weighed"]["weight_recon_status"] == "ACTUAL_RECORDED"
        assert steps["weighed"]["movement_status"] == "SURVEYED"

    def test_packing_moves_only_the_movement_dimension(self):
        """The crew packs the goods and the recorded weight is untouched.

        "Packing is a coordinator action that moves `movement_status` `SURVEYED →
        PACKED`."

        Design: Difficulty/non_linear_state_machine/shipment_movement_and_weight_dimensions_advance_independently
        """
        _, steps = _shipment_walked_along_both_dimensions()

        assert steps["packed"]["movement_status"] == "PACKED"
        assert steps["packed"]["weight_recon_status"] == "ACTUAL_RECORDED"

    def test_a_dispute_moves_only_the_weight_dimension_and_forces_a_reweigh(self):
        """The member contests the weight of already-packed goods.

        "Disputing moves `weight_recon_status` `ACTUAL_RECORDED → DISPUTED` and is
        available to the member (as the disputing party) and to a counselor acting on
        their behalf, with a `dispute_reason` in the body."

        Design: Difficulty/non_linear_state_machine/shipment_movement_and_weight_dimensions_advance_independently
        """
        _, steps = _shipment_walked_along_both_dimensions()

        assert steps["disputed"]["weight_recon_status"] == "DISPUTED"
        assert steps["disputed"]["movement_status"] == "PACKED"
        assert steps["disputed"]["reweigh_required"] is True

    def test_pickup_leaves_the_shipment_in_a_combined_parallel_state(self):
        """The goods are on the road while their weight is still contested.

        "Pickup follows and moves `movement_status` `PACKED → PICKED_UP`."

        Design: Difficulty/non_linear_state_machine/shipment_movement_and_weight_dimensions_advance_independently
        """
        _, steps = _shipment_walked_along_both_dimensions()

        assert steps["picked_up"]["movement_status"] == "PICKED_UP"
        assert steps["picked_up"]["weight_recon_status"] == "DISPUTED"
        assert steps["picked_up"]["required_delivery_by"] == "2026-08-23T00:00:00Z"

    def test_the_disputed_pounds_keep_charging_the_ledger(self):
        """4,700 disputed pounds stay on the entitlement while the matter is open.

        "A dispute forces `reweigh_required` to true and changes no ledger figure
        whatsoever: `DISPUTED` sits inside the inclusion set, so the disputed pounds
        continue to be charged while the matter is resolved."

        Design: Difficulty/non_linear_state_machine/shipment_movement_and_weight_dimensions_advance_independently
        """
        scenario, _ = _shipment_walked_along_both_dimensions()

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["charged_billable_weight_lbs"] == 4700
        assert read_shipment(scenario["shipment"]["id"])["billable_weight_lbs"] == 4700
        assert entitlement["excess_weight_lbs"] == 0
        assert entitlement["gross_excess_cost_usd"] == pytest.approx(0.00, abs=0.01)
