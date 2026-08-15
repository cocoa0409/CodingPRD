"""Public hearings and budget adoption: notice windows, venue exclusivity,
the adoption calendar, the hearing-held gate, and the adoption cascade
(PRD §3.5)."""
from test_helpers import (
    ApiErrorId, get_success_data, validate_error, validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_hearing_payload
from test_helpers.fixtures import (
    adopt, cancel_hearing, create_budget_version, create_hearing,
    create_open_fiscal_year, hold_hearing, propose, set_clock,
    setup_adopted_budget, setup_draft_budget, setup_hearing_held_budget,
    setup_proposed_budget,
)
from test_helpers.test_users import TEST_USERS

BC = TEST_USERS["board_clerk_headers"]
AU = TEST_USERS["auditor_headers"]


class TestNoticeWindow:
    def test_notice_window_exactly_ten_days_allowed_nine_rejected(self, api):
        """PRD §3.5: "Statute requires at least ten days of notice, so the
        `hearing_date` must fall no earlier than ten days after the
        `notice_publication_date`; the tenth day itself is acceptable, and
        anything shorter fails with `ERR_NOTICE_WINDOW_TOO_SHORT`."

        Design: Corner/validations/notice_window_exactly_ten_days_allowed_nine_rejected
        """
        ctx = setup_proposed_budget()
        set_clock("2027-03-01T00:00:00Z", BC)  # notice date becomes 2027-03-01
        # notice + 9 days: too short.
        resp = api.create_hearing(ctx["bv"]["id"], create_hearing_payload(
            "BOARD_ROOM", "2027-03-10"), BC)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_TOO_SHORT, 409)
        # notice + 10 days exactly: acceptable.
        data = validate_success(api.create_hearing(
            ctx["bv"]["id"], create_hearing_payload("BOARD_ROOM",
                                                    "2027-03-11"), BC), 201)
        # PRD pins the calendar date, not the serialization (date vs
        # timestamp): compare the calendar date carried by the value.
        assert str(data["notice_publication_date"]).startswith("2027-03-01")
        assert data["status"] == "NOTICE_PUBLISHED"


class TestVenueExclusivity:
    def _two_proposed_versions(self):
        fy = create_open_fiscal_year()
        bv1 = create_budget_version(fy["id"])
        bv2 = create_budget_version(fy["id"])
        propose(bv1["id"])
        propose(bv2["id"])
        set_clock("2027-03-01T00:00:00Z", BC)
        return fy, bv1, bv2

    def test_same_venue_same_date_conflicts(self, api):
        """PRD §3.5: "The calendar is venue-exclusive across the whole
        district: no two hearings in `NOTICE_PUBLISHED` or `HELD` status may
        share the same `venue` on the same calendar date, regardless of which
        budget version they belong to — day-equality semantics with no buffer
        — and a conflicting request is rejected with
        `ERR_HEARING_VENUE_DATE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/hearing_venue_date_day_equality_conflict
        """
        _, bv1, bv2 = self._two_proposed_versions()
        create_hearing(bv1["id"], "BOARD_ROOM", "2027-03-20")
        # Same venue + same date (different budget version): conflict.
        resp = api.create_hearing(bv2["id"], create_hearing_payload(
            "BOARD_ROOM", "2027-03-20"), BC)
        validate_error(resp, ApiErrorId.ERR_HEARING_VENUE_DATE_CONFLICT, 409)
        # Same venue + next day: day-equality semantics, no buffer.
        create_hearing(bv2["id"], "BOARD_ROOM", "2027-03-21")
        # Different venue + same date: no conflict.
        create_hearing(bv2["id"], "GYMNASIUM", "2027-03-20")

    def test_cancelled_hearing_releases_its_slot(self, api):
        """PRD §3.5: "no two hearings in `NOTICE_PUBLISHED` or `HELD` status
        may share the same `venue` on the same calendar date" — a CANCELLED
        hearing is outside the conflict set, so its slot is freed. PRD §3.5:
        "A clerk may also cancel a published hearing outright —
        `NOTICE_PUBLISHED` → `CANCELLED`".

        Design: Difficulty/resource_temporal_overlap/hearing_venue_date_day_equality_conflict
        """
        _, bv1, _ = self._two_proposed_versions()
        h1 = create_hearing(bv1["id"], "BOARD_ROOM", "2027-03-20")
        cancel_hearing(h1["id"])
        # The freed (BOARD_ROOM, 2027-03-20) slot accepts a new hearing.
        h2 = create_hearing(bv1["id"], "BOARD_ROOM", "2027-03-20")
        assert h2["status"] == "NOTICE_PUBLISHED"


class TestAdoptionCalendar:
    def test_adoption_before_seven_day_delay_rejected(self, api):
        """PRD §3.5: "adoption is permitted no earlier than seven days after
        the `hearing_held_date` — sooner fails with `ERR_ADOPTION_TOO_SOON`".

        Design: Corner/validations/adoption_before_seven_day_delay_rejected
        """
        ctx = setup_hearing_held_budget()  # held 2027-03-20
        set_clock("2027-03-26T09:00:00Z", BC)  # hearing + 6 days
        resp = api.adopt_budget_version(ctx["bv"]["id"], BC)
        validate_error(resp, ApiErrorId.ERR_ADOPTION_TOO_SOON, 409)
        bv = validate_success(api.get_budget_version(ctx["bv"]["id"], AU), 200)
        assert bv["status"] == "HEARING_HELD"

    def test_adoption_on_fiscal_year_start_rejected_deadline(self, api):
        """PRD §3.5: "it must complete strictly before the fiscal year's
        `start_date`, with `ERR_ADOPTION_DEADLINE_PASSED` on or after that
        first day."

        Design: Corner/validations/adoption_on_fiscal_year_start_rejected_deadline
        """
        # Hearing 2027-06-20; held+7 = 2027-06-27 is satisfied on 2027-07-01,
        # isolating the strict start-date deadline.
        ctx = setup_hearing_held_budget(hearing_date="2027-06-20")
        set_clock("2027-07-01T09:00:00Z", BC)  # the start_date itself
        resp = api.adopt_budget_version(ctx["bv"]["id"], BC)
        validate_error(resp, ApiErrorId.ERR_ADOPTION_DEADLINE_PASSED, 409)


class TestHearingGates:
    def test_hearing_creation_requires_proposed_version(self, api):
        """PRD §3.5: "A `BoardClerk` schedules a **public hearing** for a
        budget version in `PROPOSED` — against a version in any other state
        the request fails with `ERR_INVALID_STATE`".

        Design: Corner/validations/hearing_creation_requires_proposed_version
        """
        ctx = setup_draft_budget()
        set_clock("2027-03-01T00:00:00Z", BC)
        resp = api.create_hearing(ctx["bv"]["id"], create_hearing_payload(
            "BOARD_ROOM", "2027-03-20"), BC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_cancel_held_hearing_rejected_invalid_state(self, api):
        """PRD §3.5: "A clerk may also cancel a published hearing outright —
        `NOTICE_PUBLISHED` → `CANCELLED`" — cancel exists only from
        NOTICE_PUBLISHED, so cancelling a HELD hearing is the generic
        from-state violation (`ERR_INVALID_STATE`, PRD §2.9 stage 8).

        Design: Corner/state_machines/cancel_held_hearing_rejected_invalid_state
        """
        ctx = setup_hearing_held_budget()
        resp = api.cancel_hearing(ctx["hearing"]["id"], BC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestAdoptionGate:
    def test_adopt_rejected_while_hearing_only_published(self, api):
        """PRD §3.5: "The version must be `HEARING_HELD`, failing with
        `ERR_BUDGET_VERSION_NOT_HEARING_HELD` otherwise."

        Design: Difficulty/cross_entity_state_dependency/budget_adoption_gated_by_hearing_held
        """
        ctx = setup_proposed_budget()
        set_clock("2027-03-01T00:00:00Z", BC)
        create_hearing(ctx["bv"]["id"], "BOARD_ROOM", "2027-03-20")
        # The hearing is merely NOTICE_PUBLISHED; the version is PROPOSED.
        resp = api.adopt_budget_version(ctx["bv"]["id"], BC)
        validate_error(resp, ApiErrorId.ERR_BUDGET_VERSION_NOT_HEARING_HELD,
                       409)

    def test_adopt_succeeds_after_hearing_held_and_delay(self, api):
        """PRD §3.5: "A held hearing moves `NOTICE_PUBLISHED` → `HELD`,
        increments the hearing's `version`, and pulls its budget version from
        `PROPOSED` to `HEARING_HELD`, stamping the version's
        `hearing_held_date` with the hearing's `hearing_date` and incrementing
        the version's `version`." and "A successful adoption moves the version
        `HEARING_HELD` → `ADOPTED`, stamps `adopted_at` with the current
        timestamp, and fires the adoption cascade downward through the
        version."

        Design: Difficulty/cross_entity_state_dependency/budget_adoption_gated_by_hearing_held
        """
        ctx = setup_hearing_held_budget()  # hearing 2027-03-20 held
        bv = validate_success(api.get_budget_version(ctx["bv"]["id"], AU), 200)
        assert bv["status"] == "HEARING_HELD"
        # Stamped with the hearing's hearing_date; PRD pins the calendar
        # date, not the serialization.
        assert str(bv["hearing_held_date"]).startswith("2027-03-20")
        set_clock("2027-03-27T09:00:00Z", BC)  # hearing_held_date + 7 days
        adopted = validate_success(api.adopt_budget_version(ctx["bv"]["id"],
                                                            BC), 200)
        assert adopted["status"] == "ADOPTED"
        assert adopted["adopted_at"] is not None


class TestAdoptionPriorityPair:
    def test_state_error_beats_fiscal_balance_error(self, api):
        """PRD §2.9: "Every mutation request passes a fixed validation
        pipeline, and the earliest failing stage determines the error
        returned" — stage 8 state admission (`ERR_BUDGET_VERSION_NOT_...`,
        HTTP 409) precedes stage 13 fiscal guards (`ERR_BUDGET_NOT_BALANCED`,
        HTTP 422). PRD §3.5: "Adoption is the budget's point of no return,
        and its guards run in pipeline order. The version must be
        `HEARING_HELD`, failing with `ERR_BUDGET_VERSION_NOT_HEARING_HELD`
        otherwise."

        Design: Difficulty/priority_pair_validation_conflict/adopt_state_error_beats_fiscal_balance_error
        """
        # DRAFT version whose lines (20,000,000) exceed its revenue
        # (10,200,000): BOTH the state gate and the balance rule fail.
        ctx = setup_draft_budget(pupils_by_band={"ELEMENTARY": 1200},
                                 line_amounts=(20000000,))
        set_clock("2027-05-01T00:00:00Z", BC)
        resp = api.adopt_budget_version(ctx["bv"]["id"], BC)
        validate_error(resp, ApiErrorId.ERR_BUDGET_VERSION_NOT_HEARING_HELD,
                       409)
        bv = validate_success(api.get_budget_version(ctx["bv"]["id"], AU), 200)
        assert bv["status"] == "DRAFT"

    def test_balance_error_fires_once_state_gate_passes(self, api):
        """PRD §3.5: "Finally the budget must balance: the version's
        `total_appropriations` may not exceed the estimate's current
        authoritative `total_revenue`, and an unbalanced adoption is rejected
        with `ERR_BUDGET_NOT_BALANCED`."

        Design: Difficulty/priority_pair_validation_conflict/adopt_state_error_beats_fiscal_balance_error
        """
        # HEARING_HELD version with 20,000,000 of lines against 10,200,000 of
        # revenue: only the fiscal rule can fail now.
        ctx = setup_hearing_held_budget(
            pupils_by_band={"ELEMENTARY": 1200}, line_amounts=(20000000,))
        set_clock("2027-03-27T09:00:00Z", BC)
        resp = api.adopt_budget_version(ctx["bv"]["id"], BC)
        validate_error(resp, ApiErrorId.ERR_BUDGET_NOT_BALANCED, 422)
        bv = validate_success(api.get_budget_version(ctx["bv"]["id"], AU), 200)
        assert bv["status"] == "HEARING_HELD"


class TestAdoptionPrerequisiteErrors:
    def test_err_budget_not_balanced_trigger(self, api):
        """PRD §3.5: "Finally the budget must balance: the version's
        `total_appropriations` may not exceed the estimate's current
        authoritative `total_revenue`, and an unbalanced adoption is rejected
        with `ERR_BUDGET_NOT_BALANCED`."

        Design: Corner/errors/err_budget_not_balanced_trigger
        """
        # Lines 12M + 6M + 2M + 4M = 24,000,000 > total_revenue 23,404,000.
        ctx = setup_hearing_held_budget(
            pupils_by_band={"ELEMENTARY": 1200, "MIDDLE": 800, "HIGH": 1000},
            line_amounts=(12000000, 6000000, 2000000, 4000000))
        set_clock("2027-03-27T09:00:00Z", BC)
        resp = api.adopt_budget_version(ctx["bv"]["id"], BC)
        validate_error(resp, ApiErrorId.ERR_BUDGET_NOT_BALANCED, 422)
        bv = validate_success(api.get_budget_version(ctx["bv"]["id"], AU), 200)
        assert bv["status"] == "HEARING_HELD"

    def test_err_no_revenue_estimate_trigger(self, api):
        """PRD §3.5: "A revenue estimate must exist for the version, failing
        with `ERR_NO_REVENUE_ESTIMATE` when absent."

        Design: Corner/errors/err_no_revenue_estimate_trigger
        """
        ctx = setup_hearing_held_budget(with_revenue_estimate=False)
        set_clock("2027-03-27T09:00:00Z", BC)
        resp = api.adopt_budget_version(ctx["bv"]["id"], BC)
        validate_error(resp, ApiErrorId.ERR_NO_REVENUE_ESTIMATE, 409)


class TestAdoptionCascade:
    def _adoptable_with_staffing(self):
        """HEARING_HELD budget: three projections, four lines (23M <= revenue
        23,404,000), three allocations (60.0 + 36.5 + 40.0), two PROPOSED
        positions under the ELEMENTARY allocation."""
        return setup_hearing_held_budget(
            pupils_by_band={"ELEMENTARY": 1200, "MIDDLE": 800, "HIGH": 1000},
            line_amounts=(12000000, 6000000, 2000000, 3000000),
            allocation_specs=[("ELEMENTARY", 60.0), ("MIDDLE", 36.5),
                              ("HIGH", 40.0)],
            position_specs=[("ELEMENTARY", "Teacher A", 1.0, 60000),
                            ("ELEMENTARY", "Aide B", 0.5, 32000)])

    def test_adoption_cascade_authorizes_allocations_and_opens_positions(
            self, api):
        """PRD §3.5: "Every staffing allocation of the version moves `DRAFT` →
        `AUTHORIZED`; each such authorization opens its positions, moving
        every `PROPOSED` position of the allocation to `OPEN`" and "In
        parallel, every budget line of the version moves `DRAFT` →
        `ADOPTED`."

        Design: Difficulty/transitive_cascade/adoption_cascade_version_to_allocation_to_position_to_fiscal_year
        """
        ctx = self._adoptable_with_staffing()
        set_clock("2027-03-27T09:00:00Z", BC)
        adopted = validate_success(api.adopt_budget_version(ctx["bv"]["id"],
                                                            BC), 200)
        assert adopted["status"] == "ADOPTED"
        allocations, _ = validate_paginated(
            api.list_staffing_allocations(ctx["bv"]["id"], AU))
        assert all(row["status"] == "AUTHORIZED" for row in allocations)
        sa_e = ctx["allocations"]["ELEMENTARY"]
        positions, _ = validate_paginated(api.list_positions(sa_e["id"], AU))
        assert [row["status"] for row in positions] == ["OPEN", "OPEN"]
        lines, _ = validate_paginated(
            api.list_budget_lines(ctx["bv"]["id"], AU))
        assert all(row["status"] == "ADOPTED" for row in lines)

    def test_adoption_cascade_recomputes_fiscal_year_aggregates(self, api):
        """PRD §3.5: "and the fiscal year's `authorized_fte_total` — the
        summed `allocated_fte` over the year's `AUTHORIZED` allocations —
        together with its `open_position_count` are recomputed against the new
        reality."

        Design: Difficulty/transitive_cascade/adoption_cascade_version_to_allocation_to_position_to_fiscal_year
        """
        ctx = self._adoptable_with_staffing()
        fy_before = validate_success(api.get_fiscal_year(ctx["fy"]["id"], AU),
                                     200)
        assert fy_before["authorized_fte_total"] == 0
        assert fy_before["open_position_count"] == 0
        set_clock("2027-03-27T09:00:00Z", BC)
        validate_success(api.adopt_budget_version(ctx["bv"]["id"], BC), 200)
        fy_after = validate_success(api.get_fiscal_year(ctx["fy"]["id"], AU),
                                    200)
        # 60.0 + 36.5 + 40.0 = 136.5 authorized FTE; two positions opened.
        assert fy_after["authorized_fte_total"] == 136.5
        assert fy_after["open_position_count"] == 2
