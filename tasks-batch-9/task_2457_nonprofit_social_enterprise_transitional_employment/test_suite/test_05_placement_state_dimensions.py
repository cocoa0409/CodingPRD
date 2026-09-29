"""A placement carries two state dimensions on one row, and neither gates the other."""

from test_helpers import (
    EmploymentStatus,
    RetentionOutcome,
    SeparationType,
    WageVerificationAction,
    WageVerificationStatus,
    assert_placement,
    assert_ratio,
    factories,
    fixtures,
    make_case_manager_headers,
    make_employer_partner_headers,
    validate_success,
)


def _placement_ready_to_move(api):
    """A live placement at 1900 cents an hour, with the clock two weeks past hire."""
    program = fixtures.placed_participant_program(api)
    fixtures.set_clock(api, "2026-10-15T00:00:00Z")
    return program


def _verify_wage(api, program, wage_cents_per_hour=1900):
    return validate_success(
        api.record_wage_verification(
            program["placement"]["id"],
            factories.wage_verification_payload(
                WageVerificationAction.VERIFY, wage_cents_per_hour
            ),
            make_employer_partner_headers(program["employer"]["id"]),
        )
    )


class TestParallelPlacementDimensions:
    """Wage evidence and employment status move independently of each other."""

    def test_employer_attestation_moves_only_the_wage_dimension(self, api):
        """Verification sets the wage evidence and leaves the job alone.

        "It sets `wage_verification_status` to `VERIFIED`, stores
        `verified_wage_cents_per_hour`, recomputes `wage_progression_pct`, and does
        **not** touch `employment_status`."

        Design: Difficulty/non_linear_state_machine/placement_parallel_dimensions_move_independently
        """
        program = _placement_ready_to_move(api)

        placement = _verify_wage(api, program)

        assert_placement(placement)
        assert placement["wage_verification_status"] == WageVerificationStatus.VERIFIED
        assert placement["verified_wage_cents_per_hour"] == 1900
        assert_ratio(
            placement["wage_progression_pct"], 0.1515, "wage_progression_pct"
        )
        assert placement["employment_status"] == EmploymentStatus.ACTIVE

    def test_separation_moves_only_the_employment_dimension(self, api):
        """Reporting the end of the job leaves verified wage evidence standing.

        "A placement may perfectly legitimately be `SEPARATED_INVOLUNTARY` with
        `VERIFIED` wage evidence, or still `ACTIVE` with `DISPUTED` evidence."

        Design: Difficulty/non_linear_state_machine/placement_parallel_dimensions_move_independently
        """
        program = _placement_ready_to_move(api)
        _verify_wage(api, program)

        placement = fixtures.separate_placement(
            api,
            program["placement"]["id"],
            program["employer"]["id"],
            separation_type=SeparationType.VOLUNTARY,
            separation_date="2026-10-15T00:00:00Z",
        )

        assert placement["employment_status"] == EmploymentStatus.SEPARATED_VOLUNTARY
        assert placement["retention_outcome"] == RetentionOutcome.FAILED_EARLY
        assert placement["separation_days_after_hire"] == 14
        assert placement["wage_verification_status"] == WageVerificationStatus.VERIFIED
        assert placement["verified_wage_cents_per_hour"] == 1900
        assert_ratio(
            placement["wage_progression_pct"], 0.1515, "wage_progression_pct"
        )

    def test_dispute_clears_the_wage_evidence_without_reviving_the_job(self, api):
        """A case manager can dispute the wage on an already separated placement.

        "A `CaseManager` raises a dispute by supplying `action` `DISPUTE`,
        permitted when `wage_verification_status` is `UNVERIFIED` or `VERIFIED`; it
        sets `wage_verification_status` to `DISPUTED`, clears
        `verified_wage_cents_per_hour` to null and `wage_progression_pct` to null,
        and again leaves `employment_status` alone."

        Design: Difficulty/non_linear_state_machine/placement_parallel_dimensions_move_independently
        """
        program = _placement_ready_to_move(api)
        _verify_wage(api, program)
        fixtures.separate_placement(
            api,
            program["placement"]["id"],
            program["employer"]["id"],
            separation_type=SeparationType.VOLUNTARY,
            separation_date="2026-10-15T00:00:00Z",
        )

        placement = validate_success(
            api.record_wage_verification(
                program["placement"]["id"],
                factories.wage_verification_payload(WageVerificationAction.DISPUTE),
                make_case_manager_headers(),
            )
        )

        assert placement["wage_verification_status"] == WageVerificationStatus.DISPUTED
        assert placement["verified_wage_cents_per_hour"] is None
        assert placement["wage_progression_pct"] is None
        assert placement["employment_status"] == EmploymentStatus.SEPARATED_VOLUNTARY
        assert placement["retention_outcome"] == RetentionOutcome.FAILED_EARLY
