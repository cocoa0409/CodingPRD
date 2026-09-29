"""Quantities the specification never lets leak: raw hours and surcharge cents."""

import pytest

from test_helpers import (
    AppealScenario,
    AppealStatus,
    MeasureScenario,
    PublicationStatus,
    SubmissionStatus,
    allocation_line,
    approx_hours,
    assert_hours_conserved,
    build_accepted_quarter,
    validate_success,
)

LATE_CLOCK = "2026-08-20T12:00:00Z"
GRANT_NOTE = (
    "Keying error confirmed; measure suppressed and amendment fee waived."
)
APPEAL_NARRATIVE = "Two RN shifts were keyed against the wrong reporting period."


@pytest.fixture
def published_quarter_with_appeal(client):
    """An accepted quarter with a published measure and an open appeal, with the
    clock moved six days past the submission deadline."""
    scenario = build_accepted_quarter(client)
    measure = MeasureScenario(scenario)
    measure.publish()
    appeal = AppealScenario(measure, narrative=APPEAL_NARRATIVE)
    scenario.universe.set_clock(LATE_CLOCK)
    return scenario, measure, appeal


class TestHoursConservedAcrossAllocationReplacements:
    def test_01_moving_every_percent_to_an_uncredited_category_moves_the_hours_to_excluded(
        self, split_allocation_quarter
    ):
        """PRD: "Replacement re-runs the classification above from scratch on the
        stored `raw_hours`, increments `allocation_revision` by one, and re-records
        `submission_version` from the parent's new `version`." PRD: "`excluded_hours`
        is `raw_hours` less `direct_care_hours`, rounded half up to 2 decimal places
        — this is where non-direct-care and administrative time lands."

        Design: Difficulty/compensating_invariant/hours_conservation_across_allocation_replacements
        """
        scenario = split_allocation_quarter
        universe = scenario.universe
        entry = scenario.entries[0]

        data = scenario.replace_allocations(
            entry["id"], [allocation_line(universe.jc_admin["id"], 100.00)]
        )

        assert data["raw_hours"] == approx_hours(7.50)
        assert data["direct_care_hours"] == approx_hours(0.00)
        assert data["excluded_hours"] == approx_hours(7.50)
        assert data["rn_hours"] == approx_hours(0.00)
        assert data["allocation_revision"] == 1
        assert_hours_conserved(data)

    def test_02_moving_every_percent_back_to_full_credit_restores_the_direct_hours(
        self, split_allocation_quarter
    ):
        """PRD: "The array's order is the pinned processing order: lines are
        processed exactly as supplied, first element first, and are never re-sorted."
        PRD: "`rn_hours` is the sum of the line contributions whose category has
        `nurse_group` `RN`". A second replacement raises `allocation_revision` again.

        Design: Difficulty/compensating_invariant/hours_conservation_across_allocation_replacements
        """
        scenario = split_allocation_quarter
        universe = scenario.universe
        entry = scenario.entries[0]
        scenario.replace_allocations(
            entry["id"], [allocation_line(universe.jc_admin["id"], 100.00)]
        )

        data = scenario.replace_allocations(
            entry["id"], [allocation_line(universe.jc_rn["id"], 100.00)]
        )

        assert data["raw_hours"] == approx_hours(7.50)
        assert data["direct_care_hours"] == approx_hours(7.50)
        assert data["excluded_hours"] == approx_hours(0.00)
        assert data["rn_hours"] == approx_hours(7.50)
        assert data["allocation_revision"] == 2
        assert_hours_conserved(data)

    def test_03_the_submission_raw_total_is_invariant_while_the_split_moves(
        self, split_allocation_quarter
    ):
        """PRD: "`total_raw_hours` is the sum of `raw_hours`, `total_direct_care_hours`
        the sum of `direct_care_hours`, `total_excluded_hours` the sum of
        `excluded_hours`". Replacement never touches the stored `raw_hours`, so only
        the direct/excluded split moves.

        Design: Difficulty/compensating_invariant/hours_conservation_across_allocation_replacements
        """
        scenario = split_allocation_quarter
        universe = scenario.universe
        entry = scenario.entries[0]

        first = scenario.refresh()
        assert first["total_raw_hours"] == approx_hours(7.50)
        assert first["total_direct_care_hours"] == approx_hours(4.62)
        assert first["total_excluded_hours"] == approx_hours(2.88)

        scenario.replace_allocations(
            entry["id"], [allocation_line(universe.jc_admin["id"], 100.00)]
        )
        second = scenario.refresh()
        assert second["total_raw_hours"] == approx_hours(7.50)
        assert second["total_direct_care_hours"] == approx_hours(0.00)
        assert second["total_excluded_hours"] == approx_hours(7.50)

        scenario.replace_allocations(
            entry["id"], [allocation_line(universe.jc_rn["id"], 100.00)]
        )
        third = scenario.refresh()
        assert third["total_raw_hours"] == approx_hours(7.50)
        assert third["total_direct_care_hours"] == approx_hours(7.50)
        assert third["total_excluded_hours"] == approx_hours(0.00)

        assert third["version"] == first["version"] + 2

    def test_04_the_workers_reported_total_never_moves(
        self, api, split_allocation_quarter
    ):
        """PRD: "`reported_hours_total` is refreshed for every worker referenced by
        the active hour population, as the sum of `raw_hours` over that worker's
        active entries in the submission, rounded half up to 2 decimal places." The
        figure sums `raw_hours`, which a replacement leaves alone.

        Design: Difficulty/compensating_invariant/hours_conservation_across_allocation_replacements
        """
        scenario = split_allocation_quarter
        universe = scenario.universe
        entry = scenario.entries[0]

        for allocations in (
            [allocation_line(universe.jc_admin["id"], 100.00)],
            [allocation_line(universe.jc_rn["id"], 100.00)],
        ):
            scenario.replace_allocations(entry["id"], allocations)
            worker = validate_success(
                api.get_worker(universe.w_rn["id"], universe.coord_headers)
            )
            assert worker["reported_hours_total"] == approx_hours(7.50)


class TestSurchargeCentsConservedThroughWaiver:
    def test_01_the_late_reopen_assesses_the_surcharge_onto_the_facility_balance(
        self, api, published_quarter_with_appeal
    ):
        """PRD: reopening "increments `amendment_index` by one, adds the assessed
        surcharge to `amendment_surcharge_cents`, refreshes the facility's
        `outstanding_surcharge_cents`". PRD: "A base fee of 25000 cents with 6 late
        days yields 28000 cents under the pinned order, where reading the tier off
        the total would yield 29500."

        Design: Difficulty/compensating_invariant/surcharge_cents_conservation_reopen_then_appeal_waiver
        """
        scenario, _, _ = published_quarter_with_appeal
        universe = scenario.universe

        data = scenario.reopen()

        assert data["status"] == SubmissionStatus.DRAFT.value
        assert data["amendment_index"] == 1
        assert data["amendment_surcharge_cents"] == 28000
        assert data["waived_surcharge_cents"] == 0

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["outstanding_surcharge_cents"] == 28000

    def test_02_granting_the_appeal_waives_exactly_the_amount_still_outstanding(
        self, published_quarter_with_appeal
    ):
        """PRD: "`surcharge_waived_cents` on the appeal is set to the source
        submission's `amendment_surcharge_cents` less its `waived_surcharge_cents` —
        that is, the whole amount still outstanding on that submission — that amount
        is added to the submission's `waived_surcharge_cents`, and the facility's
        `outstanding_surcharge_cents` is refreshed accordingly."

        Design: Difficulty/compensating_invariant/surcharge_cents_conservation_reopen_then_appeal_waiver
        """
        scenario, _, appeal = published_quarter_with_appeal
        scenario.reopen()

        data = appeal.grant(GRANT_NOTE)

        assert data["status"] == AppealStatus.GRANTED.value
        assert data["surcharge_waived_cents"] == 28000
        assert data["decision_note"] == GRANT_NOTE

    def test_03_the_assessed_and_waived_cents_cancel_to_a_zero_balance(
        self, api, published_quarter_with_appeal
    ):
        """PRD: "`outstanding_surcharge_cents` is the sum, over every
        `QuarterlySubmission` of the facility whose `status` is anything other than
        `VOID`, of that submission's `amendment_surcharge_cents` less its
        `waived_surcharge_cents`." The assessment stays on the record; only the
        balance goes to zero.

        Design: Difficulty/compensating_invariant/surcharge_cents_conservation_reopen_then_appeal_waiver
        """
        scenario, _, appeal = published_quarter_with_appeal
        universe = scenario.universe
        scenario.reopen()
        appeal.grant(GRANT_NOTE)

        submission = scenario.refresh()
        assert submission["amendment_surcharge_cents"] == 28000
        assert submission["waived_surcharge_cents"] == 28000

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["outstanding_surcharge_cents"] == 0

    def test_04_the_granted_appeal_suppresses_the_measure_and_clears_the_rating(
        self, api, published_quarter_with_appeal
    ):
        """PRD: "The appealed measure moves from `PUBLISHED` to `SUPPRESSED` and its
        `has_open_appeal` is cleared, with the facility's `latest_staffing_rating`
        refreshed — cleared to null when no other published measure remains."

        Design: Difficulty/compensating_invariant/surcharge_cents_conservation_reopen_then_appeal_waiver
        """
        scenario, measure, appeal = published_quarter_with_appeal
        universe = scenario.universe
        scenario.reopen()
        appeal.grant(GRANT_NOTE)

        data = measure.refresh()
        assert data["publication_status"] == PublicationStatus.SUPPRESSED.value
        assert data["has_open_appeal"] is False

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["latest_staffing_rating"] is None
