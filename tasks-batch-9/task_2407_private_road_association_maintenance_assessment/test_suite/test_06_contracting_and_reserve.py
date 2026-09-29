"""Contracting the work: the reversible award, the inclusive reserve gates, the
half-open work window with its paving cure buffer, and the reserve ledger."""
import pytest

from test_helpers import (
    ApiErrorId,
    award_project,
    cancel_project_payload,
    complete_project_payload,
    create_maintenance_project_payload,
    make_commissioner_headers,
    make_contractor_headers,
    read_association,
    read_bid,
    read_project,
    read_segment,
    record_access_inspection,
    set_clock,
    setup_annual_assessment,
    setup_association,
    setup_project,
    setup_road_segment,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_bid_payload,
)

PINE_HOLLOW = {
    "name": "Pine Hollow Road Association",
    "reserve_target_cents": 1_000_000,
    "default_voting_basis": "PER_PARCEL",
    "delinquency_interest_basis": "STATUTORY",
    "quorum_bps": 5000,
}
SEGMENT_2400 = {
    "name": "Pine Hollow Road",
    "length_feet": 2400,
    "width_feet": 22,
    "max_grade_pct": 9,
    "surface_type": "GRAVEL",
    "turnout_count": 2,
    "culvert_count": 3,
    "turnaround_present": True,
    "bridge_present": False,
}
SINGLE_PARCEL = [
    {
        "deed_book_page": "DB120-P41",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
    }
]
COMPLIANT_MEASUREMENTS = {
    "measured_width_feet": 22,
    "measured_max_grade_pct": 9,
    "measured_turnout_count": 2,
    "turnaround_present": True,
}
FIRST_COMMISSIONER = make_commissioner_headers("rc-user-1")
SECOND_COMMISSIONER = make_commissioner_headers("rc-user-2")


def _levied_association(reserve_target_cents=1_000_000):
    """A single-parcel FY2027 levy, which credits 600000 to the reserve."""
    set_clock("2026-10-01T00:00:00Z")
    scenario = setup_annual_assessment(
        parcel_specs=SINGLE_PARCEL,
        fiscal_year=2027,
        fy_start_date="2026-10-01",
        fy_end_date="2027-09-30",
        budget_requirement_cents=4_000_000,
        method_variant="FRONTAGE_WEIGHTED",
        association_overrides=dict(PINE_HOLLOW, reserve_target_cents=reserve_target_cents),
        segment_overrides=SEGMENT_2400,
    )
    record_access_inspection(
        scenario["segment"]["id"], "2026-10-01T00:00:00Z", **COMPLIANT_MEASUREMENTS
    )
    return scenario


class TestAwardIsReversibleAndRepeatable:
    """BID_SOLICITATION to AWARDED and back, then to AWARDED again."""

    def _awarded_grading_project(self, api):
        set_clock("2026-10-01T00:00:00Z")
        association = setup_association(
            name="Switchback Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(
            association["id"], **dict(SEGMENT_2400, name="Switchback Road", culvert_count=2)
        )
        project = setup_project(
            segment["id"],
            category="GRADING",
            window_start_date="2026-11-01",
            window_end_date="2026-11-10",
            headers=FIRST_COMMISSIONER,
        )
        bid_version = read_project(project["id"])["version"]
        bid_a = submit_bid(
            project,
            800_000,
            contractor_user_id="firm-alpha",
            contractor_name="Alpha Grading LLC",
            expected_project_version=bid_version,
        )
        awarded = award_project(project["id"], bid_a["id"], headers=SECOND_COMMISSIONER)
        return {
            "association": association,
            "segment": segment,
            "project": awarded,
            "bid_a": bid_a,
            "bid_version": bid_version,
        }

    def test_the_first_award_records_the_bid_and_draws_nothing_for_grading(self, api):
        """PRD §3.7: "A successful award moves the project `BID_SOLICITATION →
        AWARDED` and the nominated bid `SUBMITTED → AWARDED`; every other bid on the
        project whose `status` is `SUBMITTED` moves `SUBMITTED → REJECTED`. The
        project's `awarded_bid_id`, `awarded_amount_cents` (taken from the awarded
        bid's `amount_cents`), and `awarded_by_user_id` are set, and
        `reserve_draw_cents` is set to the computed draw."
        PRD §3.7: "for the operating categories `GRADING`, `SNOW`, and `DUST` the draw
        is zero, because operating work is funded from the annual levy"

        Design: Difficulty/non_linear_state_machine/project_returns_to_solicitation_when_awarded_bid_withdraws
        """
        world = self._awarded_grading_project(api)
        project = world["project"]

        assert project["status"] == "AWARDED"
        assert project["awarded_bid_id"] == world["bid_a"]["id"]
        assert project["awarded_amount_cents"] == 800_000
        assert project["awarded_by_user_id"] == "rc-user-2"
        assert project["reserve_draw_cents"] == 0
        assert read_bid(world["bid_a"]["id"])["status"] == "AWARDED"
        assert read_association(world["association"]["id"])["reserve_balance_cents"] == 0

    def test_withdrawing_the_awarded_bid_returns_the_project_to_solicitation(self, api):
        """PRD §3.7: "If the withdrawn bid was the awarded one, the full reversion
        cascade runs: the project moves `AWARDED → BID_SOLICITATION`,
        `awarded_bid_id` returns to null, `awarded_amount_cents` returns to zero, and
        `awarded_by_user_id` returns to null"
        PRD §3.7: "The submission increments the project's `version` by one, which is
        exactly why the next bidder's stale version is detectable."

        Design: Difficulty/non_linear_state_machine/project_returns_to_solicitation_when_awarded_bid_withdraws
        """
        world = self._awarded_grading_project(api)

        validate_success(
            api.withdraw_bid(
                world["bid_a"]["id"],
                withdraw_bid_payload("crew reassigned to a county job"),
                make_contractor_headers("firm-alpha"),
            )
        )

        project = read_project(world["project"]["id"])
        assert project["status"] == "BID_SOLICITATION"
        assert project["awarded_bid_id"] is None
        assert project["awarded_amount_cents"] == 0
        assert project["awarded_by_user_id"] is None
        assert project["reserve_draw_cents"] == 0
        assert read_bid(world["bid_a"]["id"])["status"] == "WITHDRAWN"
        assert project["version"] > world["bid_version"], (
            "a replacement bid must carry the newer project version"
        )

    def test_a_higher_replacement_bid_wins_once_the_lower_one_is_withdrawn(self, api):
        """PRD §3.7: "The responsive candidate set is every bid on the project whose
        `status` is `SUBMITTED` and whose `bond_on_file` is true; `SUPERSEDED`,
        `REJECTED`, and `WITHDRAWN` bids are excluded."
        PRD §3.7: "Bids that this award had already pushed to `REJECTED` stay
        `REJECTED` — a new round needs fresh bids, so the project can travel
        `BID_SOLICITATION → AWARDED → BID_SOLICITATION → AWARDED` more than once."

        Design: Difficulty/non_linear_state_machine/project_returns_to_solicitation_when_awarded_bid_withdraws
        """
        world = self._awarded_grading_project(api)
        validate_success(
            api.withdraw_bid(
                world["bid_a"]["id"],
                withdraw_bid_payload("crew reassigned to a county job"),
                make_contractor_headers("firm-alpha"),
            )
        )
        reopened = read_project(world["project"]["id"])

        bid_b = submit_bid(
            reopened,
            850_000,
            contractor_user_id="firm-beta",
            contractor_name="Beta Roadworks",
            expected_project_version=reopened["version"],
        )
        assert bid_b["status"] == "SUBMITTED", (
            "850000 is responsive even though a withdrawn 800000 bid exists"
        )

        rewarded = award_project(reopened["id"], bid_b["id"], headers=SECOND_COMMISSIONER)
        assert rewarded["status"] == "AWARDED"
        assert rewarded["awarded_bid_id"] == bid_b["id"]
        assert rewarded["awarded_amount_cents"] == 850_000

        bids, _meta = validate_paginated(
            api.list_project_bids(reopened["id"], SECOND_COMMISSIONER)
        )
        assert [b["id"] for b in bids] == [world["bid_a"]["id"], bid_b["id"]]
        assert [b["status"] for b in bids] == ["WITHDRAWN", "AWARDED"]
        assert read_association(world["association"]["id"])["reserve_balance_cents"] == 0, (
            "GRADING never touches the reserve"
        )


class TestReserveGatesAtTheirBoundaries:
    """A draw equal to the whole balance, and the gate the next award meets."""

    def _two_culvert_projects(self, api):
        scenario = _levied_association()
        first = setup_project(
            scenario["segment"]["id"],
            category="CULVERT",
            window_start_date="2026-11-01",
            window_end_date="2026-11-10",
            headers=FIRST_COMMISSIONER,
        )
        second = setup_project(
            scenario["segment"]["id"],
            category="CULVERT",
            window_start_date="2026-11-10",
            window_end_date="2026-11-20",
            headers=FIRST_COMMISSIONER,
        )
        scenario["first"] = first
        scenario["second"] = second
        scenario["bid_one"] = submit_bid(
            first, 600_000, contractor_user_id="firm-alpha", contractor_name="Alpha Culvert Co"
        )
        scenario["bid_two"] = submit_bid(
            second, 50_000, contractor_user_id="firm-beta", contractor_name="Beta Drainage LLC"
        )
        return scenario

    def test_a_draw_equal_to_the_whole_balance_is_permitted(self, api):
        """PRD §3.7: "And the computed reserve draw must not exceed the association's
        `reserve_balance_cents`, an inclusive comparison that permits a draw equal to
        the whole balance and drives it to exactly zero; exceeding it is
        `ERR_INSUFFICIENT_RESERVE`."
        PRD §2.6: "otherwise it is `ADEQUATE` when the balance multiplied by one
        hundred is at least the target multiplied by sixty — so a balance of exactly
        sixty percent of target is `ADEQUATE`"

        Design: Difficulty/boundary_precision_check/reserve_draw_equal_to_balance_allowed_then_underfunded_gate_blocks_next_award
        """
        scenario = self._two_culvert_projects(api)
        before = read_association(scenario["association"]["id"])
        assert before["reserve_balance_cents"] == 600_000
        assert before["reserve_funding_ratio"] == pytest.approx(0.6, abs=0.0001)
        assert before["reserve_posture"] == "ADEQUATE", "600000 * 100 == 1000000 * 60"

        awarded = award_project(
            scenario["first"]["id"], scenario["bid_one"]["id"], headers=SECOND_COMMISSIONER
        )
        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_amount_cents"] == 600_000
        assert awarded["reserve_draw_cents"] == 600_000
        assert read_bid(scenario["bid_one"]["id"])["status"] == "AWARDED"

        after = read_association(scenario["association"]["id"])
        assert after["reserve_balance_cents"] == 0
        assert after["reserve_funding_ratio"] == pytest.approx(0.0, abs=0.0001)
        assert after["reserve_posture"] == "UNDERFUNDED"

    def test_the_underfunded_gate_answers_before_the_amount_comparison(self, api):
        """PRD §3.7: "If the project's `category` is `CULVERT` or `BRIDGE` and the
        association's `reserve_posture` is `UNDERFUNDED` as of the start of the award
        request, the project's `proposal_id` must reference an `ADOPTED` proposal;
        without one, the award is rejected with `ERR_RESERVE_UNDERFUNDED`."
        PRD §2.10: "More generally, every request walks the following checks in this
        exact order, and the first failure is the error returned. Where several checks
        could all fire, the earlier one masks the later ones."

        Design: Difficulty/boundary_precision_check/reserve_draw_equal_to_balance_allowed_then_underfunded_gate_blocks_next_award
        """
        scenario = self._two_culvert_projects(api)
        award_project(
            scenario["first"]["id"], scenario["bid_one"]["id"], headers=SECOND_COMMISSIONER
        )

        validate_error(
            api.award_project(
                scenario["second"]["id"],
                {"bid_id": scenario["bid_two"]["id"]},
                SECOND_COMMISSIONER,
            ),
            ApiErrorId.ERR_RESERVE_UNDERFUNDED.value,
        )

        second = read_project(scenario["second"]["id"])
        assert second["status"] == "BID_SOLICITATION"
        assert second["reserve_draw_cents"] == 0
        assert second["awarded_bid_id"] is None
        assert read_bid(scenario["bid_two"]["id"])["status"] == "SUBMITTED"
        assert read_association(scenario["association"]["id"])["reserve_balance_cents"] == 0, (
            "the rejected award takes no partial draw"
        )


class TestWorkWindowsAndTheCureBuffer:
    """Half-open windows on a contended segment, plus three cure days."""

    def _open(self, api, category, start, end, headers=None):
        return api.create_maintenance_project(
            create_maintenance_project_payload(
                self.segment_id,
                category=category,
                window_start_date=start,
                window_end_date=end,
            ),
            headers or FIRST_COMMISSIONER,
        )

    def _segment(self, api):
        scenario = _levied_association()
        self.segment_id = scenario["segment"]["id"]
        return scenario

    def _windows_through_h(self, api):
        scenario = self._segment(api)
        scenario["a"] = validate_success(
            self._open(api, "GRADING", "2026-11-01", "2026-11-10"), 201
        )
        scenario["b"] = validate_success(
            self._open(api, "SNOW", "2026-11-10", "2026-11-15"), 201
        )
        scenario["d"] = validate_success(
            self._open(api, "DUST", "2026-11-15", "2026-11-16"), 201
        )
        validate_success(
            api.cancel_project(
                scenario["a"]["id"],
                cancel_project_payload("grader unavailable"),
                FIRST_COMMISSIONER,
            )
        )
        scenario["h"] = validate_success(
            self._open(api, "GRADING", "2026-11-01", "2026-11-05"), 201
        )
        return scenario

    def test_touching_windows_are_legal_and_intersecting_ones_are_not(self, api):
        """PRD §3.7: "The new half-open window may not intersect the window of any
        project on the same segment whose `status` is `BID_SOLICITATION` or
        `AWARDED`; windows that merely touch, one ending the day the next starts, are
        permitted, and an intersection is rejected with `ERR_WORK_WINDOW_CONFLICT`."
        PRD §3.7: "The new project starts in `BID_SOLICITATION` with
        `created_by_user_id` set from `X-User-ID`, a null `awarded_bid_id`,
        `awarded_amount_cents` and `reserve_draw_cents` at zero, and null
        `awarded_by_user_id`, `completed_at`, `actual_cost_cents`, and
        `cancellation_reason`."

        Design: Difficulty/resource_temporal_overlap/work_windows_touch_legally_overlap_illegally_and_respect_the_paving_cure_buffer
        """
        self._segment(api)
        first = validate_success(self._open(api, "GRADING", "2026-11-01", "2026-11-10"), 201)
        assert first["status"] == "BID_SOLICITATION"
        assert first["reserve_draw_cents"] == 0
        assert first["created_by_user_id"] == "rc-user-1"
        assert first["awarded_bid_id"] is None
        assert first["completed_at"] is None

        touching = validate_success(self._open(api, "SNOW", "2026-11-10", "2026-11-15"), 201)
        assert touching["status"] == "BID_SOLICITATION"

        validate_error(
            self._open(api, "DUST", "2026-11-09", "2026-11-12"),
            ApiErrorId.ERR_WORK_WINDOW_CONFLICT.value,
        )

        after_end = validate_success(self._open(api, "DUST", "2026-11-15", "2026-11-16"), 201)
        assert after_end["window_start_date"] == "2026-11-15", (
            "window_end_date is exclusive, not the last worked day"
        )

    def test_a_cancelled_project_stops_reserving_its_window(self, api):
        """PRD §3.7: "Cancellation is the commissioner's version of the same reversal.
        It takes a `cancellation_reason`, is available while the project is
        `BID_SOLICITATION` or `AWARDED`, and moves the project to `CANCELLED`."
        PRD §3.7: "The new half-open window may not intersect the window of any
        project on the same segment whose `status` is `BID_SOLICITATION` or `AWARDED`"

        Design: Difficulty/resource_temporal_overlap/work_windows_touch_legally_overlap_illegally_and_respect_the_paving_cure_buffer
        """
        scenario = self._windows_through_h(api)

        assert read_project(scenario["a"]["id"])["status"] == "CANCELLED"
        assert scenario["h"]["window_start_date"] == "2026-11-01", (
            "the cancelled project no longer reserves 2026-11-01"
        )
        assert scenario["h"]["status"] == "BID_SOLICITATION"

    def test_a_completed_paving_project_keeps_reserving_three_cure_days(self, api):
        """PRD §3.7: "Separately, if the segment already hosts a `PAVING` project
        whose `status` is `AWARDED` or `COMPLETE`, the new window must start on or
        after that paving project's `window_end_date` plus three days of cure buffer;
        starting inside that buffer is rejected with
        `ERR_PAVING_CURE_BUFFER_VIOLATION`."
        PRD §3.7: "One category carries an extra consequence: on a `PAVING` project
        only, the segment's `surface_type` becomes `PAVED` and its
        `emergency_access_grade` resets to `UNKNOWN`, because a rebuilt travelway must
        be re-inspected before the association may again assert compliance."

        Design: Difficulty/resource_temporal_overlap/work_windows_touch_legally_overlap_illegally_and_respect_the_paving_cure_buffer
        """
        scenario = self._windows_through_h(api)
        paving = validate_success(self._open(api, "PAVING", "2026-11-16", "2026-11-20"), 201)
        bid = submit_bid(
            paving, 250_000, contractor_user_id="firm-alpha", contractor_name="Alpha Paving LLC"
        )
        awarded = award_project(paving["id"], bid["id"], headers=SECOND_COMMISSIONER)
        assert awarded["reserve_draw_cents"] == 250_000
        mid = read_association(scenario["association"]["id"])
        assert mid["reserve_balance_cents"] == 350_000
        assert mid["reserve_posture"] == "UNDERFUNDED"

        set_clock("2026-11-20T00:00:00Z")
        completed = validate_success(
            api.complete_project(
                paving["id"],
                complete_project_payload("2026-11-20", 250_000),
                FIRST_COMMISSIONER,
            )
        )
        assert completed["status"] == "COMPLETE"
        assert completed["actual_cost_cents"] == 250_000
        assert completed["reserve_draw_cents"] == 250_000, "the draw has been spent"
        segment = read_segment(scenario["segment"]["id"])
        assert segment["surface_type"] == "PAVED"
        assert segment["emergency_access_grade"] == "UNKNOWN"
        assert read_association(scenario["association"]["id"])["reserve_balance_cents"] == 350_000

        validate_error(
            self._open(api, "GRADING", "2026-11-22", "2026-11-25"),
            ApiErrorId.ERR_PAVING_CURE_BUFFER_VIOLATION.value,
        )
        cleared = validate_success(self._open(api, "GRADING", "2026-11-23", "2026-11-26"), 201)
        assert cleared["status"] == "BID_SOLICITATION", (
            "window_end_date plus three days is an inclusive earliest start"
        )

    def test_the_segment_ends_up_hosting_exactly_six_projects(self, api):
        """PRD §3.7: "Projects may be listed with `road_segment_id`, `proposal_id`,
        `awarded_bid_id`, `status`, and `category` filters."
        PRD §3.7: "The project moves `AWARDED → COMPLETE` with both values recorded,
        and its `reserve_draw_cents` is retained rather than reversed, because the
        draw has now actually been spent."

        Design: Difficulty/resource_temporal_overlap/work_windows_touch_legally_overlap_illegally_and_respect_the_paving_cure_buffer
        """
        scenario = self._windows_through_h(api)
        paving = validate_success(self._open(api, "PAVING", "2026-11-16", "2026-11-20"), 201)
        bid = submit_bid(
            paving, 250_000, contractor_user_id="firm-alpha", contractor_name="Alpha Paving LLC"
        )
        award_project(paving["id"], bid["id"], headers=SECOND_COMMISSIONER)
        set_clock("2026-11-20T00:00:00Z")
        validate_success(
            api.complete_project(
                paving["id"],
                complete_project_payload("2026-11-20", 250_000),
                FIRST_COMMISSIONER,
            )
        )
        final = validate_success(self._open(api, "GRADING", "2026-11-23", "2026-11-26"), 201)

        projects, _meta = validate_paginated(
            api.list_maintenance_projects(
                FIRST_COMMISSIONER,
                params={"road_segment_id": scenario["segment"]["id"], "limit": 100},
            )
        )
        by_id = {p["id"]: p["status"] for p in projects}
        assert len(projects) == 6
        assert by_id[scenario["a"]["id"]] == "CANCELLED"
        assert by_id[paving["id"]] == "COMPLETE"
        solicited = [
            scenario["b"]["id"],
            scenario["d"]["id"],
            scenario["h"]["id"],
            final["id"],
        ]
        for project_id in solicited:
            assert by_id[project_id] == "BID_SOLICITATION"


class TestReserveBalanceIsAReconciledLedger:
    """Six mutations, two compensation paths, and no drift."""

    def _two_culverts(self, api):
        scenario = _levied_association(reserve_target_cents=500_000)
        c1 = setup_project(
            scenario["segment"]["id"],
            category="CULVERT",
            window_start_date="2026-11-01",
            window_end_date="2026-11-05",
            headers=FIRST_COMMISSIONER,
        )
        c2 = setup_project(
            scenario["segment"]["id"],
            category="CULVERT",
            window_start_date="2026-11-05",
            window_end_date="2026-11-10",
            headers=FIRST_COMMISSIONER,
        )
        scenario["c1"] = c1
        scenario["c2"] = c2
        scenario["bid1"] = submit_bid(
            c1, 200_000, contractor_user_id="firm-alpha", contractor_name="Alpha Culvert Co"
        )
        scenario["bid2"] = submit_bid(
            c2, 100_000, contractor_user_id="firm-beta", contractor_name="Beta Drainage LLC"
        )
        return scenario

    def _balance(self, association_id):
        return read_association(association_id)

    def test_two_awards_walk_the_balance_down_to_the_adequate_boundary(self, api):
        """PRD §2.6: "The reconciliation takes the sum of `reserve_contribution_cents`
        over every assessment roll of the association whose `status` is `LEVIED`, adds
        the sum of `reserve_buyin_cents` over every connection request whose `status`
        is `APPROVED` and whose parcel sits on a road segment of this association, and
        subtracts the sum of `reserve_draw_cents` over every maintenance project on a
        segment of this association whose `status` is `AWARDED` or `COMPLETE`."
        PRD §2.6: "the posture is `FULLY_FUNDED` when the balance is at least the
        target"

        Design: Difficulty/compensating_invariant/reserve_balance_conserved_across_award_cancel_and_bid_withdrawal
        """
        scenario = self._two_culverts(api)
        association_id = scenario["association"]["id"]
        start = self._balance(association_id)
        assert start["reserve_balance_cents"] == 600_000
        assert start["reserve_funding_ratio"] == pytest.approx(1.2, abs=0.0001)
        assert start["reserve_posture"] == "FULLY_FUNDED"

        first = award_project(
            scenario["c1"]["id"], scenario["bid1"]["id"], headers=SECOND_COMMISSIONER
        )
        assert first["reserve_draw_cents"] == 200_000
        after_first = self._balance(association_id)
        assert after_first["reserve_balance_cents"] == 400_000
        assert after_first["reserve_posture"] == "ADEQUATE"

        second = award_project(
            scenario["c2"]["id"], scenario["bid2"]["id"], headers=SECOND_COMMISSIONER
        )
        assert second["reserve_draw_cents"] == 100_000
        after_second = self._balance(association_id)
        assert after_second["reserve_balance_cents"] == 300_000
        assert after_second["reserve_posture"] == "ADEQUATE", (
            "300000 * 100 == 500000 * 60 is the inclusive boundary"
        )

    def test_cancellation_and_withdrawal_each_return_their_draw(self, api):
        """PRD §3.7: "Every bid on the project whose `status` is `SUBMITTED` or
        `AWARDED` moves to `REJECTED`; the project's `reserve_draw_cents` is added
        back to the association's `reserve_balance_cents` and then zeroed; and because
        the balance changed, the funding ratio, the posture, and every `DRAFT`
        proposal's threshold are recomputed."
        PRD §3.7: "the prior `reserve_draw_cents` is added back to the association's
        `reserve_balance_cents` and the project's draw is zeroed; and because the
        balance rose, `reserve_funding_ratio`, `reserve_posture`, and every `DRAFT`
        proposal's `required_threshold_bps` are recomputed."

        Design: Difficulty/compensating_invariant/reserve_balance_conserved_across_award_cancel_and_bid_withdrawal
        """
        scenario = self._two_culverts(api)
        association_id = scenario["association"]["id"]
        award_project(scenario["c1"]["id"], scenario["bid1"]["id"], headers=SECOND_COMMISSIONER)
        award_project(scenario["c2"]["id"], scenario["bid2"]["id"], headers=SECOND_COMMISSIONER)

        validate_success(
            api.cancel_project(
                scenario["c1"]["id"],
                cancel_project_payload("culvert pipe unavailable"),
                FIRST_COMMISSIONER,
            )
        )
        after_cancel = self._balance(association_id)
        assert after_cancel["reserve_balance_cents"] == 500_000
        assert after_cancel["reserve_posture"] == "FULLY_FUNDED"
        cancelled = read_project(scenario["c1"]["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["reserve_draw_cents"] == 0
        assert read_bid(scenario["bid1"]["id"])["status"] == "REJECTED"

        validate_success(
            api.withdraw_bid(
                scenario["bid2"]["id"],
                withdraw_bid_payload("crew reassigned"),
                make_contractor_headers("firm-beta"),
            )
        )
        after_withdraw = self._balance(association_id)
        assert after_withdraw["reserve_balance_cents"] == 600_000, (
            "600000 levied plus zero buy-ins minus zero draws, since no project is "
            "AWARDED or COMPLETE"
        )
        assert read_bid(scenario["bid2"]["id"])["status"] == "WITHDRAWN"
        reopened = read_project(scenario["c2"]["id"])
        assert reopened["status"] == "BID_SOLICITATION"
        assert reopened["reserve_draw_cents"] == 0
        assert reopened["awarded_bid_id"] is None
        assert reopened["awarded_amount_cents"] == 0

    def test_the_ledger_returns_to_exactly_its_starting_value(self, api):
        """PRD §2.6: "Its `reserve_balance_cents` is not a free-standing counter but a
        reconciled aggregate, recomputed from first principles on every event that
        moves reserve money: an assessment roll levy, a connection approval, a project
        award, a project cancellation, and the withdrawal of an awarded bid."
        PRD §2.6: "Projects still in `BID_SOLICITATION` and projects that were
        `CANCELLED` contribute nothing to the subtraction."

        Design: Difficulty/compensating_invariant/reserve_balance_conserved_across_award_cancel_and_bid_withdrawal
        """
        scenario = self._two_culverts(api)
        association_id = scenario["association"]["id"]
        award_project(scenario["c1"]["id"], scenario["bid1"]["id"], headers=SECOND_COMMISSIONER)
        award_project(scenario["c2"]["id"], scenario["bid2"]["id"], headers=SECOND_COMMISSIONER)
        validate_success(
            api.cancel_project(
                scenario["c1"]["id"],
                cancel_project_payload("culvert pipe unavailable"),
                FIRST_COMMISSIONER,
            )
        )
        validate_success(
            api.withdraw_bid(
                scenario["bid2"]["id"],
                withdraw_bid_payload("crew reassigned"),
                make_contractor_headers("firm-beta"),
            )
        )
        assert self._balance(association_id)["reserve_balance_cents"] == 600_000

        reopened = read_project(scenario["c2"]["id"])
        bid3 = submit_bid(
            reopened,
            100_000,
            contractor_user_id="firm-gamma",
            contractor_name="Gamma Earthworks",
            expected_project_version=reopened["version"],
        )
        rewarded = award_project(reopened["id"], bid3["id"], headers=SECOND_COMMISSIONER)
        assert rewarded["reserve_draw_cents"] == 100_000, "no stale draw was left behind"
        assert self._balance(association_id)["reserve_balance_cents"] == 500_000

        validate_success(
            api.cancel_project(
                scenario["c2"]["id"],
                cancel_project_payload("deferred to next fiscal year"),
                FIRST_COMMISSIONER,
            )
        )
        final = self._balance(association_id)
        assert final["reserve_balance_cents"] == 600_000, "zero drift across six mutations"
        assert final["reserve_funding_ratio"] == pytest.approx(1.2, abs=0.0001)
        assert final["reserve_posture"] == "FULLY_FUNDED"
