"""Rent schedules: state-capped vs uncapped increase computation, the nested
min/floor cap formula, the strict-greater cap_applied boundary, the
contest/revise/accept cycle, the 12-month spacing rule, and apply side effects.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_resident_headers,
    fixtures as fx,
)

MGR = TEST_USERS["manager_headers"]


class TestCappedVsUncapped:
    def test_ca_proposal_above_cap_is_reduced(self, api):
        """PRD §3.4: "For a capped state, the maximum allowed rent is
        `prior_rent_cents` multiplied by one plus that state's fraction, with the
        product floored to a whole cent; the legally effective `new_rent_cents` is
        then the smaller of `proposed_rent_cents` and that floored maximum."
        PRD §3.4: "The `cap_applied` flag is true exactly when `proposed_rent_cents`
        is strictly greater than the maximum allowed — meaning the proposal was
        reduced — and is therefore always false in Texas."

        Design: Difficulty/dual_variant_calc/rent_increase_capped_vs_uncapped_state
        """
        community = fx.create_community(api, state_code="CA")
        lot = fx.create_lot(community["id"], api, lot_number="C1", base_rent_cents=60000)
        sched = fx.propose_rent_schedule(
            lot["id"], api=api, proposed_rent_cents=70000, effective_date="2027-01-01"
        )
        assert sched["new_rent_cents"] == 63000
        assert sched["cap_applied"] is True

    def test_tx_proposal_is_uncapped(self, api):
        """PRD §3.4: "For Texas, the maximum allowed equals `proposed_rent_cents`
        itself, so the effective `new_rent_cents` is simply the proposed amount
        and the cap never binds."

        Design: Difficulty/dual_variant_calc/rent_increase_capped_vs_uncapped_state
        """
        community = fx.create_community(api, state_code="TX")
        lot = fx.create_lot(community["id"], api, lot_number="T1", base_rent_cents=60000)
        sched = fx.propose_rent_schedule(
            lot["id"], api=api, proposed_rent_cents=70000, effective_date="2027-01-01"
        )
        assert sched["new_rent_cents"] == 70000
        assert sched["cap_applied"] is False


class TestNestedCapFormula:
    def test_or_proposal_under_ceiling_keeps_proposed(self, api):
        """PRD §3.4: "California permits at most 5 percent, Oregon at most 7
        percent, and Florida at most 10 percent."
        PRD §3.4: "the legally effective `new_rent_cents` is then the smaller of
        `proposed_rent_cents` and that floored maximum."

        Design: Difficulty/combinatorial_formula/rent_cap_nested_min_floor_branch
        """
        community = fx.create_community(api, state_code="OR")
        lot = fx.create_lot(community["id"], api, lot_number="O1", base_rent_cents=60000)
        # OR ceiling = floor(60000 * 1.07) = 64200; proposed 63000 is below it.
        sched = fx.propose_rent_schedule(
            lot["id"], api=api, proposed_rent_cents=63000, effective_date="2027-01-01"
        )
        assert sched["new_rent_cents"] == 63000
        assert sched["cap_applied"] is False

    def test_ca_proposal_at_ceiling_is_not_flagged_capped(self, api):
        """PRD §3.4: "The `cap_applied` flag is true exactly when
        `proposed_rent_cents` is strictly greater than the maximum allowed —
        meaning the proposal was reduced — and is therefore always false in
        Texas."

        Design: Difficulty/boundary_precision_check/rent_cap_strict_greater_boundary
        """
        community = fx.create_community(api, state_code="CA")
        lot = fx.create_lot(community["id"], api, lot_number="B1", base_rent_cents=60000)
        # CA ceiling = floor(60000 * 1.05) = 63000; proposed exactly 63000 -> not strictly greater.
        sched = fx.propose_rent_schedule(
            lot["id"], api=api, proposed_rent_cents=63000, effective_date="2027-01-01"
        )
        assert sched["new_rent_cents"] == 63000
        assert sched["cap_applied"] is False

    def test_or_proposal_above_ceiling_is_reduced_to_floored_max(self, api):
        """PRD §3.4: "For a capped state, the maximum allowed rent is
        `prior_rent_cents` multiplied by one plus that state's fraction, with the
        product floored to a whole cent; the legally effective `new_rent_cents` is
        then the smaller of `proposed_rent_cents` and that floored maximum."

        Design: Difficulty/combinatorial_formula/rent_cap_nested_min_floor_branch
        """
        community = fx.create_community(api, state_code="OR")
        lot = fx.create_lot(community["id"], api, lot_number="O2", base_rent_cents=60000)
        # OR ceiling = floor(60000 * 1.07) = 64200; proposed 70000 above it -> reduced.
        sched = fx.propose_rent_schedule(
            lot["id"], api=api, proposed_rent_cents=70000, effective_date="2027-01-01"
        )
        assert sched["new_rent_cents"] == 64200
        assert sched["cap_applied"] is True

    def test_ca_proposal_one_cent_above_ceiling_is_flagged_capped(self, api):
        """PRD §3.4: "The `cap_applied` flag is true exactly when
        `proposed_rent_cents` is strictly greater than the maximum allowed —
        meaning the proposal was reduced — and is therefore always false in
        Texas."

        Design: Difficulty/boundary_precision_check/rent_cap_strict_greater_boundary
        """
        community = fx.create_community(api, state_code="CA")
        lot = fx.create_lot(community["id"], api, lot_number="B2", base_rent_cents=60000)
        # CA ceiling = 63000; proposed 63001 is strictly greater -> capped, reduced to 63000.
        sched = fx.propose_rent_schedule(
            lot["id"], api=api, proposed_rent_cents=63001, effective_date="2027-01-01"
        )
        assert sched["new_rent_cents"] == 63000
        assert sched["cap_applied"] is True


class TestContestReviseCycle:
    def test_contest_then_revise_then_accept(self, api):
        """PRD §3.4: "The `Resident` may accept the proposal, taking it from
        `PROPOSED → ACCEPTED`, or contest it, taking it from `PROPOSED →
        CONTESTED`; each transition requires the schedule to be `PROPOSED` and
        otherwise fails with `ERR_INVALID_STATE`."
        PRD §3.4: "When a proposal is `CONTESTED`, the `ParkManager` may revise it
        by supplying a new `proposed_rent_cents`; revision requires the schedule
        to be `CONTESTED`, recomputes `new_rent_cents` and `cap_applied` against
        the same `prior_rent_cents` and `effective_date` baseline, and returns the
        schedule to `PROPOSED` so the resident may respond again."

        Design: Difficulty/non_linear_state_machine/rent_schedule_contest_revise_cycle
        """
        community, lot, resident, lease = fx.setup_occupied_lot(
            api, community_overrides={"state_code": "CA"}, lot_overrides={"lot_number": "Y1"}
        )
        res_headers = make_resident_headers(resident["id"])
        sched = fx.propose_rent_schedule(
            lot["id"], api=api, proposed_rent_cents=62000, effective_date="2027-01-01"
        )
        get_success_data(api.contest_rent_schedule(sched["id"], res_headers))
        get_success_data(api.revise_rent_schedule(sched["id"], 61000, MGR))
        get_success_data(api.accept_rent_schedule(sched["id"], res_headers))
        final = get_success_data(api.get_rent_schedule(sched["id"], MGR))
        assert final["status"] == "ACCEPTED"
        assert final["proposed_rent_cents"] == 61000
        assert final["new_rent_cents"] == 61000

    def test_revise_recomputes_against_same_baseline(self, api):
        """PRD §3.4: "revision requires the schedule to be `CONTESTED`, recomputes
        `new_rent_cents` and `cap_applied` against the same `prior_rent_cents` and
        `effective_date` baseline, and returns the schedule to `PROPOSED` so the
        resident may respond again."

        Design: Difficulty/non_linear_state_machine/rent_schedule_contest_revise_cycle
        """
        community, lot, resident, lease = fx.setup_occupied_lot(
            api, community_overrides={"state_code": "CA"}, lot_overrides={"lot_number": "Y2"}
        )
        res_headers = make_resident_headers(resident["id"])
        sched = fx.propose_rent_schedule(
            lot["id"], api=api, proposed_rent_cents=62000, effective_date="2027-01-01"
        )
        get_success_data(api.contest_rent_schedule(sched["id"], res_headers))
        revised = get_success_data(api.revise_rent_schedule(sched["id"], 61000, MGR))
        assert revised["status"] == "PROPOSED"
        assert revised["proposed_rent_cents"] == 61000
        # 61000 stays under the CA ceiling (63000) so cap is not applied.
        assert revised["new_rent_cents"] == 61000
        assert revised["cap_applied"] is False


class TestTwelveMonthSpacing:
    def test_second_increase_within_12_months_rejected(self, api):
        """PRD §3.4: "It also requires that the schedule's `effective_date` fall
        at least 12 months after the `effective_date` of the lot's most recent
        already-effective schedule; an `effective_date` that is less than 12
        months after that prior effective date is rejected with
        `ERR_INCREASE_TOO_SOON` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/rent_increase_12_month_spacing_overlap
        """
        community, lot, resident, lease = fx.setup_occupied_lot(
            api, community_overrides={"state_code": "CA"}, lot_overrides={"lot_number": "T1"}
        )
        res_headers = make_resident_headers(resident["id"])
        fx.make_effective_schedule(lot["id"], resident["id"], 62000, "2027-01-01", api=api)
        sched2 = fx.propose_rent_schedule(
            lot["id"], api=api, proposed_rent_cents=63000, effective_date="2027-07-01"
        )
        get_success_data(api.accept_rent_schedule(sched2["id"], res_headers))
        resp = api.apply_rent_schedule(sched2["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_INCREASE_TOO_SOON.value)

    def test_second_increase_exactly_12_months_later_applies(self, api):
        """PRD §3.4: "It also requires that the schedule's `effective_date` fall
        at least 12 months after the `effective_date` of the lot's most recent
        already-effective schedule; an `effective_date` that is less than 12
        months after that prior effective date is rejected with
        `ERR_INCREASE_TOO_SOON` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/rent_increase_12_month_spacing_overlap
        """
        community, lot, resident, lease = fx.setup_occupied_lot(
            api, community_overrides={"state_code": "CA"}, lot_overrides={"lot_number": "T3"}
        )
        res_headers = make_resident_headers(resident["id"])
        fx.make_effective_schedule(lot["id"], resident["id"], 62000, "2027-01-01", api=api)
        # Exactly 12 months later (2028-01-01) satisfies "at least 12 months".
        sched2 = fx.propose_rent_schedule(
            lot["id"], api=api, proposed_rent_cents=63000, effective_date="2028-01-01"
        )
        get_success_data(api.accept_rent_schedule(sched2["id"], res_headers))
        applied = get_success_data(api.apply_rent_schedule(sched2["id"], MGR))
        assert applied["status"] == "EFFECTIVE"

    def test_apply_proposed_schedule_rejected_invalid_state(self, api):
        """PRD §3.4: "Application requires the schedule to be `ACCEPTED`, failing
        otherwise with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_increase_too_soon_temporal
        """
        community = fx.create_community(api, state_code="CA")
        lot = fx.create_lot(community["id"], api, lot_number="P2", base_rent_cents=60000)
        # PROPOSED (un-accepted) schedule whose effective_date is only 1 month out.
        sched = fx.propose_rent_schedule(
            lot["id"], api=api, proposed_rent_cents=61000, effective_date="2026-02-01"
        )
        resp = api.apply_rent_schedule(sched["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_apply_too_soon_proposed_schedule_leaves_schedule_proposed(self, api):
        """PRD §3.4: "Application requires the schedule to be `ACCEPTED`, failing
        otherwise with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_increase_too_soon_temporal
        """
        community = fx.create_community(api, state_code="CA")
        lot = fx.create_lot(community["id"], api, lot_number="P3", base_rent_cents=60000)
        # PROPOSED (not ACCEPTED) and effective_date only one month out (too soon).
        sched = fx.propose_rent_schedule(
            lot["id"], api=api, proposed_rent_cents=61000, effective_date="2026-02-01"
        )
        api.apply_rent_schedule(sched["id"], MGR)
        after = get_success_data(api.get_rent_schedule(sched["id"], MGR))
        assert after["status"] == "PROPOSED"


class TestApplyEffective:
    def test_apply_updates_lot_current_rent(self, api):
        """PRD §3.4: "On success the schedule transitions `ACCEPTED → EFFECTIVE`,
        the lot's `current_rent_cents` recomputes to the schedule's
        `new_rent_cents`, and the lot's `version` increments by one."

        Design: Corner/state_machines/rent_apply_effective_updates_lot_current_rent
        """
        community, lot, resident, lease = fx.setup_occupied_lot(
            api, community_overrides={"state_code": "CA"}, lot_overrides={"lot_number": "AP"}
        )
        res_headers = make_resident_headers(resident["id"])
        sched = fx.propose_rent_schedule(
            lot["id"], api=api, proposed_rent_cents=63000, effective_date="2027-01-01"
        )
        get_success_data(api.accept_rent_schedule(sched["id"], res_headers))
        applied = get_success_data(api.apply_rent_schedule(sched["id"], MGR))
        assert applied["status"] == "EFFECTIVE"
        lot_after = get_success_data(api.get_lot(lot["id"], MGR))
        assert lot_after["current_rent_cents"] == 63000
