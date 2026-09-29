"""Agency batch acceptance cascading into the receiving quarter."""

import pytest

from test_helpers import (
    FindingCode,
    FindingSeverity,
    HourEntrySource,
    SubmissionStatus,
    VendorScenario,
    VendorSubmissionStatus,
    approx_hours,
    approx_ratio,
    build_draft_submission,
    find_finding,
    validate_success,
)


@pytest.fixture
def vendor_batch_over_thin_census(client):
    """A VALIDATED quarter carrying one 12.00-hour facility shift over a single
    census day counting 2 residents, plus a SUBMITTED agency batch of two more
    12.00-hour shifts awaiting the staffing office's acceptance."""
    scenario = build_draft_submission(client)
    vendor = VendorScenario(scenario.universe)

    scenario.capture_hours(
        work_date="2026-04-01", shift_start="07:00", shift_end="19:00"
    )
    scenario.report_census("2026-04-01", 2, 2)
    scenario.validate()

    vendor.file_batch(
        [
            vendor.batch_line("2026-04-02", "07:00", "19:00"),
            vendor.batch_line("2026-04-03", "07:00", "19:00"),
        ]
    )
    vendor.submit_batch()
    return scenario, vendor


class TestVendorBatchAcceptCascade:
    def test_01_acceptance_records_the_batch_totals(
        self, vendor_batch_over_thin_census
    ):
        """PRD: "Acceptance moves the batch to `ACCEPTED` and synthesizes one hour
        entry per element of `lines`, in `lines` order" and "`accepted_direct_care_hours`
        is set to the sum of their `direct_care_hours`". Both lines are full-credit
        RN shifts of 12.00 hours.

        Design: Difficulty/transitive_cascade/vendor_batch_accept_cascade_flips_submission_back_to_draft
        """
        scenario, vendor = vendor_batch_over_thin_census

        data = vendor.accept_batch(scenario.id)

        assert data["status"] == VendorSubmissionStatus.ACCEPTED.value
        assert data["line_count"] == 2
        assert data["accepted_direct_care_hours"] == approx_hours(24.00)
        assert len(data["accepted_hour_entry_ids"]) == 2

    def test_02_the_synthesized_entries_are_marked_as_vendor_sourced(
        self, api, vendor_batch_over_thin_census
    ):
        """PRD: "each with `source` set to `VENDOR_SUBMISSION` and
        `vendor_submission_id` set to this batch."

        Design: Difficulty/transitive_cascade/vendor_batch_accept_cascade_flips_submission_back_to_draft
        """
        scenario, vendor = vendor_batch_over_thin_census
        vendor.accept_batch(scenario.id)

        entries = validate_success(
            api.list_hour_entries(
                scenario.universe.coord_headers,
                {"submission_id": scenario.id, "limit": 100},
            )
        )
        assert len(entries) == 3

        synthesized = [
            entry
            for entry in entries
            if entry["source"] == HourEntrySource.VENDOR_SUBMISSION.value
        ]
        assert len(synthesized) == 2
        assert all(
            entry["vendor_submission_id"] == vendor.batch["id"]
            for entry in synthesized
        )
        assert all(
            entry["worker_id"] == vendor.contractor["id"] for entry in synthesized
        )

    def test_03_the_target_rollups_absorb_the_agency_hours(
        self, vendor_batch_over_thin_census
    ):
        """PRD: "`vendor_sourced_hours` is the sum of `direct_care_hours`
        restricted to entries whose `source` is `VENDOR_SUBMISSION`". PRD: "The
        target submission's rollups and its as-submitted hours-per-resident-day
        figures are then recomputed". 36.00 direct-care hours over the quarter's 2
        counted resident days is 18.0000 hours per resident day.

        Design: Difficulty/transitive_cascade/vendor_batch_accept_cascade_flips_submission_back_to_draft
        """
        scenario, vendor = vendor_batch_over_thin_census
        vendor.accept_batch(scenario.id)

        data = scenario.refresh()
        assert data["total_direct_care_hours"] == approx_hours(36.00)
        assert data["vendor_sourced_hours"] == approx_hours(24.00)
        assert data["total_resident_days"] == 2
        assert data["hprd_reported"] == approx_ratio(18.0000)

    def test_04_a_validated_target_is_flipped_back_to_draft(
        self, vendor_batch_over_thin_census
    ):
        """PRD: "a `VALIDATED` target reverts to `DRAFT`, and the target
        submission's `version` is incremented by one — as is the batch's own
        `version`."

        Design: Difficulty/transitive_cascade/vendor_batch_accept_cascade_flips_submission_back_to_draft
        """
        scenario, vendor = vendor_batch_over_thin_census
        before = scenario.refresh()
        assert before["status"] == SubmissionStatus.VALIDATED.value

        vendor.accept_batch(scenario.id)

        after = scenario.refresh()
        assert after["status"] == SubmissionStatus.DRAFT.value
        assert after["version"] == before["version"] + 1

    def test_05_the_vendor_and_contractor_totals_track_the_acceptance(
        self, api, vendor_batch_over_thin_census
    ):
        """PRD: "the vendor's `accepted_hours_total` is refreshed as the sum of
        `accepted_direct_care_hours` over that vendor's `ACCEPTED` batches." PRD:
        "`reported_hours_total` is refreshed for every worker referenced by the
        active hour population, as the sum of `raw_hours` over that worker's active
        entries in the submission".

        Design: Difficulty/transitive_cascade/vendor_batch_accept_cascade_flips_submission_back_to_draft
        """
        scenario, vendor = vendor_batch_over_thin_census
        universe = scenario.universe
        vendor.accept_batch(scenario.id)

        vendor_row = validate_success(
            api.get_vendor(vendor.vendor_id, universe.coord_headers)
        )
        assert vendor_row["accepted_hours_total"] == approx_hours(24.00)

        contractor = validate_success(
            api.get_worker(vendor.contractor["id"], universe.coord_headers)
        )
        assert contractor["reported_hours_total"] == approx_hours(24.00)

    def test_06_revalidating_the_swollen_quarter_raises_the_fatal_hprd_finding(
        self, vendor_batch_over_thin_census
    ):
        """PRD: "`HPRD_IMPLAUSIBLE`, `severity` `FATAL`, a single finding with
        `subject_ref` set to the literal string `PERIOD`, raised when the
        as-submitted `hprd_reported` exceeds 12.0000."

        Design: Difficulty/transitive_cascade/vendor_batch_accept_cascade_flips_submission_back_to_draft
        """
        scenario, vendor = vendor_batch_over_thin_census
        vendor.accept_batch(scenario.id)

        data = scenario.validate()

        assert data["status"] == SubmissionStatus.VALIDATED.value
        assert data["open_fatal_finding_count"] == 1

        finding = find_finding(
            scenario.findings(), FindingCode.HPRD_IMPLAUSIBLE.value, "PERIOD"
        )
        assert finding is not None
        assert finding["severity"] == FindingSeverity.FATAL.value
