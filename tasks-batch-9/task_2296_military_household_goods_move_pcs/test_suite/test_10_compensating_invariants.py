"""Compensating actions that put back exactly what they took: waivers and award releases."""

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    award_shipment,
    capacity_block_version,
    create_capacity_block,
    get_success_data,
    read_capacity_block,
    read_entitlement,
    read_shipment,
    record_actual_weight,
    release_award_payload,
    revoke_waiver_payload,
    setup_booked_shipment,
    setup_surveyed_shipment,
    survey_shipment,
    validate_error,
    waive_excess_cost,
)

E5_WITHOUT_DEPENDENTS = {
    "rank_code": "E5",
    "branch": "AIR_FORCE",
    "dependents_count": 0,
    "spouse_present": False,
}
OCTOBER_WEEK = "2026-10-05T00:00:00Z"


def _entitlement_owing_three_thousand_dollars():
    """An E5 ledger charged 10,000 pounds against a 7,000 pound cap."""
    scenario = setup_surveyed_shipment(member_overrides=E5_WITHOUT_DEPENDENTS)
    record_actual_weight(scenario, 11800, 1800, weigh_date="2026-08-03T00:00:00Z")
    return scenario


def _revoke(entitlement_id):
    return api_client.revoke_waiver(
        entitlement_id,
        revoke_waiver_payload(revocation_reason="Waiver authority withdrawn on audit"),
        ADMIN,
    )


def _waiver_cycle():
    """Three ledger readings: before a 1,200.00 waiver, after it, and after revoking it."""
    scenario = _entitlement_owing_three_thousand_dollars()
    entitlement_id = scenario["entitlement"]["id"]

    before = read_entitlement(entitlement_id)
    waive_excess_cost(
        entitlement_id,
        1200.00,
        waiver_reason="Command-directed partial waiver for a short-notice reassignment",
    )
    waived = read_entitlement(entitlement_id)
    _revoke(entitlement_id)
    revoked = read_entitlement(entitlement_id)
    return scenario, [before, waived, revoked]


def _block_shipments(block_id):
    return get_success_data(api_client.list_capacity_block_shipments(block_id, ADMIN))


def _award_release_and_reaward():
    """Three block readings: after an award, after releasing it, and after re-awarding."""
    scenario = setup_booked_shipment(
        order_overrides={"report_no_later_than_date": "2026-11-01T00:00:00Z"},
        shipment_overrides={
            "requested_pack_date": "2026-10-06T00:00:00Z",
            "requested_pickup_date": "2026-10-07T00:00:00Z",
            "requested_delivery_date": "2026-10-14T00:00:00Z",
        },
    )
    scenario["shipment"] = survey_shipment(scenario)
    scenario["block"] = create_capacity_block(
        scenario["tsp"]["id"],
        week_start_date=OCTOBER_WEEK,
        total_capacity_lbs=12000,
        short_notice_reserve_pct=0.15,
    )
    block_id = scenario["block"]["id"]
    shipment_id = scenario["shipment"]["id"]

    award_shipment(block_id, shipment_id)
    awarded = read_capacity_block(block_id)

    get_success_data(
        api_client.release_award(
            block_id,
            release_award_payload(
                shipment_id, release_reason="Crew reassigned to another market"
            ),
            scenario["tsp_headers"],
        )
    )
    released = read_capacity_block(block_id)

    award_shipment(block_id, shipment_id, capacity_block_version(block_id))
    reawarded = read_capacity_block(block_id)
    return scenario, [awarded, released, reawarded]


class TestWaiverAndRevocationConserveTheGrossCost:
    """Waiving moves money between two columns; revoking moves it back."""

    def test_the_unwaived_ledger_owes_the_whole_gross_cost(self):
        """3,000 pounds over the cap cost 3,005.10 and nothing has been forgiven.

        "`excess_cost_due_usd` is `gross_excess_cost_usd` less `excess_cost_waived_usd`,
        rounded half up to cents and floored at zero. `excess_cost_waived_usd` itself
        defaults to 0.00 and can never exceed `gross_excess_cost_usd`."

        Design: Difficulty/compensating_invariant/excess_cost_waiver_and_revocation_conserve_gross_excess_cost
        """
        _, readings = _waiver_cycle()
        before = readings[0]

        assert before["charged_billable_weight_lbs"] == 10000
        assert before["excess_weight_lbs"] == 3000
        assert before["gross_excess_cost_usd"] == pytest.approx(3005.10, abs=0.01)
        assert before["excess_cost_waived_usd"] == pytest.approx(0.00, abs=0.01)
        assert before["excess_cost_due_usd"] == pytest.approx(3005.10, abs=0.01)

    def test_the_waiver_lowers_the_amount_due_without_touching_the_gross(self):
        """1,200.00 forgiven leaves 1,805.10 outstanding against the same 3,005.10 gross.

        "Acceptance increases `excess_cost_waived_usd` by the waived amount, records the
        reason in `waiver_reason`, and reduces `excess_cost_due_usd` by the same amount;
        `gross_excess_cost_usd` is deliberately left untouched, preserving the invariant of
        §2.8."

        Design: Difficulty/compensating_invariant/excess_cost_waiver_and_revocation_conserve_gross_excess_cost
        """
        _, readings = _waiver_cycle()
        waived = readings[1]

        assert waived["gross_excess_cost_usd"] == pytest.approx(3005.10, abs=0.01)
        assert waived["excess_cost_waived_usd"] == pytest.approx(1200.00, abs=0.01)
        assert waived["excess_cost_due_usd"] == pytest.approx(1805.10, abs=0.01)
        assert waived["charged_billable_weight_lbs"] == 10000
        assert waived["excess_weight_lbs"] == 3000

    def test_the_revocation_restores_the_amount_due_exactly(self):
        """Withdrawing the waiver puts all 3,005.10 back on the member.

        "Supplying a `revocation_reason` resets `excess_cost_waived_usd` to 0.00 and
        restores `excess_cost_due_usd` to the full `gross_excess_cost_usd`."

        Design: Difficulty/compensating_invariant/excess_cost_waiver_and_revocation_conserve_gross_excess_cost
        """
        _, readings = _waiver_cycle()
        revoked = readings[2]

        assert revoked["gross_excess_cost_usd"] == pytest.approx(3005.10, abs=0.01)
        assert revoked["excess_cost_waived_usd"] == pytest.approx(0.00, abs=0.01)
        assert revoked["excess_cost_due_usd"] == pytest.approx(3005.10, abs=0.01)

    def test_the_waiver_invariant_holds_at_every_reading(self):
        """Due plus waived equals gross before, during and after the waiver.

        "First, the waiver invariant: `excess_cost_due_usd` plus `excess_cost_waived_usd`
        always equals `gross_excess_cost_usd`, which is why waiving cost never reduces the
        gross figure and revoking a waiver restores the amount due exactly."

        Design: Difficulty/compensating_invariant/excess_cost_waiver_and_revocation_conserve_gross_excess_cost
        """
        _, readings = _waiver_cycle()

        for reading in readings:
            assert reading["excess_cost_due_usd"] + reading[
                "excess_cost_waived_usd"
            ] == pytest.approx(reading["gross_excess_cost_usd"], abs=0.01)
            assert reading["status"] == "SUSPENDED"
            assert reading["suspension_reason"] == "EXCESS_COST_UNPAID"

    def test_a_second_revocation_has_nothing_left_to_revoke(self):
        """With the columns already restored the request is refused and nothing moves.

        "Revocation requires that something has in fact been waived: when
        `excess_cost_waived_usd` is already zero, the request is refused with
        `ERR_NO_WAIVER_TO_REVOKE`."

        Design: Difficulty/compensating_invariant/excess_cost_waiver_and_revocation_conserve_gross_excess_cost
        """
        scenario, _ = _waiver_cycle()
        entitlement_id = scenario["entitlement"]["id"]

        validate_error(
            _revoke(entitlement_id), ApiErrorId.ERR_NO_WAIVER_TO_REVOKE.value, 409
        )

        after = read_entitlement(entitlement_id)
        assert after["gross_excess_cost_usd"] == pytest.approx(3005.10, abs=0.01)
        assert after["excess_cost_waived_usd"] == pytest.approx(0.00, abs=0.01)
        assert after["excess_cost_due_usd"] == pytest.approx(3005.10, abs=0.01)


class TestAwardReleaseRestoresThePoolsWithoutDrift:
    """The pounds leave the pool they entered and come back to the same figure."""

    def test_the_award_commits_the_pounds_to_the_general_pool(self):
        """5,286 surveyed pounds sit in the general pool of a 12,000 pound week.

        "For a shipment whose `is_short_notice` is false, only the general pool is
        available"

        Design: Difficulty/compensating_invariant/award_release_restores_capacity_pools_without_drift
        """
        scenario, readings = _award_release_and_reaward()
        awarded = readings[0]

        assert awarded["committed_general_lbs"] == 5286
        assert awarded["committed_short_notice_lbs"] == 0
        assert awarded["committed_lbs"] == 5286
        assert awarded["status"] == "OPEN"
        assert len(_block_shipments(scenario["block"]["id"])) == 1

    def test_the_release_subtracts_from_the_very_same_counter(self):
        """The week empties out and the shipment loses its slot without being cancelled.

        "Release clears the shipment's `capacity_block_id` to null and subtracts its
        `billable_weight_lbs` from the very same pool counter that received it, then
        re-derives `committed_lbs` and the block `status`."

        Design: Difficulty/compensating_invariant/award_release_restores_capacity_pools_without_drift
        """
        scenario, readings = _award_release_and_reaward()
        released = readings[1]

        assert released["committed_general_lbs"] == 0
        assert released["committed_short_notice_lbs"] == 0
        assert released["committed_lbs"] == 0
        assert released["status"] == "OPEN"

    def test_the_shipment_keeps_its_surveyed_pounds_through_the_cycle(self):
        """The release empties the counter; the surveyed pounds stay on the shipment.

        "Release clears the shipment's `capacity_block_id` to null and subtracts its
        `billable_weight_lbs` from the very same pool counter that received it"

        Design: Difficulty/compensating_invariant/award_release_restores_capacity_pools_without_drift
        """
        scenario, readings = _award_release_and_reaward()

        assert readings[1]["committed_lbs"] == 0
        shipment = read_shipment(scenario["shipment"]["id"])
        assert shipment["billable_weight_lbs"] == 5286
        assert shipment["movement_status"] == "SURVEYED"

    def test_re_awarding_lands_on_exactly_the_first_figures(self):
        """The block returns to 5,286 committed pounds with no rounding drift.

        "In both branches `committed_lbs` is then re-derived as `committed_general_lbs`
        plus `committed_short_notice_lbs`, and the shipment's `capacity_block_id` is set to
        the block."

        Design: Difficulty/compensating_invariant/award_release_restores_capacity_pools_without_drift
        """
        scenario, readings = _award_release_and_reaward()
        awarded, _, reawarded = readings

        assert reawarded["committed_general_lbs"] == awarded["committed_general_lbs"]
        assert reawarded["committed_lbs"] == awarded["committed_lbs"] == 5286
        assert (
            read_shipment(scenario["shipment"]["id"])["capacity_block_id"]
            == scenario["block"]["id"]
        )
        assert len(_block_shipments(scenario["block"]["id"])) == 1

    def test_the_pools_and_the_weight_ledger_never_move(self):
        """The published pools and the charged pounds are identical at all three readings.

        "Second, the capacity conservation invariant: a block's `committed_lbs` always
        equals the sum of `billable_weight_lbs` over the shipments whose
        `capacity_block_id` names that block and whose `movement_status` is not
        `CANCELLED`."

        Design: Difficulty/compensating_invariant/award_release_restores_capacity_pools_without_drift
        """
        scenario, readings = _award_release_and_reaward()

        for reading in readings:
            assert reading["total_capacity_lbs"] == 12000
            assert reading["general_pool_lbs"] == 10200
            assert reading["short_notice_pool_lbs"] == 1800

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["charged_billable_weight_lbs"] == 5286
