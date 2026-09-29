"""Voiding and verification as independent dimensions on one hour entry."""

from test_helpers import (
    EntryStatus,
    VERIFYING_AUDITOR_USER_ID,
    VerificationStatus,
    approx_hours,
    validate_success,
)


def _verified_entry(scenario):
    """The quarter's single RN shift: payroll-backed, verified, still ACTIVE."""
    return scenario.entries[0]


class TestHourEntryVoidAndVerificationDimensions:
    def test_01_voiding_does_not_touch_the_verification_dimension(
        self, api, supported_quarter
    ):
        """PRD: "Note that `entry_status` and `verification_status` are two
        independent dimensions on the same entry: voiding never touches the
        verification dimension, and verifying never touches the void dimension."

        Design: Difficulty/non_linear_state_machine/hour_entry_orthogonal_void_and_verification_dimensions
        """
        scenario = supported_quarter
        entry = _verified_entry(scenario)

        data = validate_success(
            api.void_hour_entry(entry["id"], scenario.universe.coord_headers)
        )

        assert data["entry_status"] == EntryStatus.VOID.value
        assert data["verification_status"] == VerificationStatus.SUPPORTED.value
        assert data["verified_by_user_id"] == VERIFYING_AUDITOR_USER_ID

    def test_02_the_voided_row_keeps_its_own_computed_hour_figures(
        self, api, supported_quarter
    ):
        """PRD: "Voiding moves `entry_status` from `ACTIVE` to `VOID`, which is
        terminal, and requires the entry to be `ACTIVE`, the parent submission to
        be in `DRAFT` or `VALIDATED`, and the logical clock to be at or before the
        period's correction window end. The void removes the entry's hours from
        every submission rollup, refreshes the owning worker's
        `reported_hours_total`, reverts a `VALIDATED` parent submission to
        `DRAFT`, and increments the submission's `version` by one." The row's own
        `raw_hours` and `direct_care_hours` are not among the fields the void
        rewrites.

        Design: Difficulty/non_linear_state_machine/hour_entry_orthogonal_void_and_verification_dimensions
        """
        scenario = supported_quarter
        entry = _verified_entry(scenario)
        validate_success(
            api.void_hour_entry(entry["id"], scenario.universe.coord_headers)
        )

        data = validate_success(
            api.get_hour_entry(entry["id"], scenario.universe.coord_headers)
        )
        assert data["raw_hours"] == approx_hours(8.00)
        assert data["direct_care_hours"] == approx_hours(8.00)

    def test_03_the_voided_hours_leave_every_submission_rollup(
        self, api, supported_quarter
    ):
        """PRD: "the submission's aggregates are recomputed from scratch over two
        populations: the hour entries of that submission whose `entry_status` is
        `ACTIVE` (voided entries contribute to nothing)".

        Design: Difficulty/non_linear_state_machine/hour_entry_orthogonal_void_and_verification_dimensions
        """
        scenario = supported_quarter
        entry = _verified_entry(scenario)
        validate_success(
            api.void_hour_entry(entry["id"], scenario.universe.coord_headers)
        )

        submission = scenario.refresh()
        assert submission["total_raw_hours"] == approx_hours(0.00)
        assert submission["total_direct_care_hours"] == approx_hours(0.00)
        assert submission["total_rn_direct_care_hours"] == approx_hours(0.00)

    def test_04_the_owning_workers_reported_total_drops_to_zero(
        self, api, supported_quarter
    ):
        """PRD: "In the same pass, `reported_hours_total` is refreshed for every
        worker referenced by the active hour population, as the sum of `raw_hours`
        over that worker's active entries in the submission, rounded half up to 2
        decimal places."

        Design: Difficulty/non_linear_state_machine/hour_entry_orthogonal_void_and_verification_dimensions
        """
        scenario = supported_quarter
        universe = scenario.universe
        entry = _verified_entry(scenario)
        validate_success(api.void_hour_entry(entry["id"], universe.coord_headers))

        worker = validate_success(
            api.get_worker(universe.w_rn["id"], universe.coord_headers)
        )
        assert worker["reported_hours_total"] == approx_hours(0.00)
