"""Readiness scoring: the two variants, the deficiency cap, and the outreach requirement.

The readiness read is the only place where a cycle's penalties are visible term by term,
so these cases check the terms as well as the total.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ApiClient,
    CycleStatus,
    CycleType,
    DeficiencyClass,
    DesignationLevel,
    ReadinessPosture,
    ReadinessVariant,
    assert_decimal,
    assert_readiness_read,
    fixtures as fx,
    make_trauma_program_manager_headers,
    make_verification_reviewer_headers,
)


def _cycle_with_one_remediated_major(api: ApiClient):
    """A national cycle whose major deficiency has a remediation packet on file.

    The minor deficiency beside it is left untouched, which is what makes the two
    variants disagree by exactly one deficiency's weight.
    """
    fx.anchor_clock(api)
    center = fx.create_center(
        api,
        name="Lakeshore Trauma",
        state_code="MI",
        designation_level=DesignationLevel.LEVEL_II,
    )
    cycle = fx.create_cycle(
        api,
        center["id"],
        cycle_type=CycleType.NATIONAL_VERIFICATION,
        site_visit_date="2026-11-10T13:00:00Z",
    )
    major = fx.record_deficiency(
        api,
        cycle,
        criterion_code="CD-11-01",
        deficiency_class=DeficiencyClass.TYPE_II_MAJOR,
        remediation_due_at="2026-10-01T00:00:00Z",
    )
    fx.record_deficiency(
        api,
        cycle,
        criterion_code="CD-11-02",
        deficiency_class=DeficiencyClass.TYPE_III_MINOR,
        remediation_due_at="2026-10-01T00:00:00Z",
    )
    fx.submit_remediation(
        api,
        cycle,
        major,
        remediation_note="Call panel roster updated and monthly audit attached.",
    )
    return center, cycle


def _cycle_with_five_criticals(api: ApiClient):
    """A national cycle carrying five open critical deficiencies."""
    fx.anchor_clock(api)
    center = fx.create_center(
        api,
        name="Riverbend Trauma",
        state_code="TX",
        designation_level=DesignationLevel.LEVEL_I,
    )
    cycle = fx.create_cycle(
        api,
        center["id"],
        cycle_type=CycleType.NATIONAL_VERIFICATION,
        site_visit_date="2026-12-01T13:00:00Z",
    )
    fx.deficiencies_of_class(
        api,
        cycle,
        ["CD-01-01", "CD-01-02", "CD-01-03", "CD-01-04", "CD-01-05"],
        deficiency_class=DeficiencyClass.TYPE_I_CRITICAL,
        remediation_due_at="2026-09-15T00:00:00Z",
    )
    return center, cycle


class TestReadinessVariantDivergence:
    """A filed remediation packet is worth nothing to the reviewer and 6 points to the center."""

    def test_the_two_variants_disagree_on_a_remediation_submitted_deficiency(
        self, api: ApiClient
    ) -> None:
        """The same two deficiencies score 74.00 for the reviewer and 80.00 for the center.

        Design: Difficulty/dual_variant_calc/readiness_score_variants_diverge_on_remediation_submitted_deficiency
        """
        center, cycle = _cycle_with_one_remediated_major(api)
        manager = make_trauma_program_manager_headers(center["id"])

        reviewer_view = get_success_data(api.get_cycle_readiness(cycle["id"], manager))
        assert_readiness_read(
            reviewer_view,
            None,
            deficiency_penalty=8,
            outreach_penalty=18.00,
            pi_penalty=0,
            readiness_score=74.00,
            submit_eligible=True,
        )

        self_view = get_success_data(
            api.get_cycle_readiness(
                cycle["id"], manager, {"variant": ReadinessVariant.SELF_ASSESSMENT}
            )
        )
        assert_readiness_read(
            self_view,
            ReadinessVariant.SELF_ASSESSMENT,
            deficiency_penalty=2,
            outreach_penalty=18.00,
            pi_penalty=0,
            readiness_score=80.00,
            submit_eligible=True,
        )

    def test_the_persisted_score_follows_the_reviewer_variant_only(
        self, api: ApiClient
    ) -> None:
        """Remediation moves neither the stored score nor the per-class open counters.

        Design: Difficulty/dual_variant_calc/readiness_score_variants_diverge_on_remediation_submitted_deficiency
        """
        center, cycle = _cycle_with_one_remediated_major(api)

        get_success_data(
            api.get_cycle_readiness(
                cycle["id"],
                make_trauma_program_manager_headers(center["id"]),
                {"variant": ReadinessVariant.SELF_ASSESSMENT},
            )
        )

        after = fx.get_cycle(api, cycle["id"])
        assert_decimal(after["readiness_score"], 74.00, "readiness_score")
        assert after["open_type_ii_count"] == 1, (
            "a filed packet does not decrement the open counters"
        )
        assert after["open_type_iii_count"] == 1
        assert after["open_type_i_count"] == 0


class TestDeficiencyPenaltyCap:
    """Five critical deficiencies weigh more than the penalty term can carry."""

    def test_the_deficiency_term_clips_to_sixty_rather_than_seventy_five(
        self, api: ApiClient
    ) -> None:
        """Raw weight 75 is reported as 60, so the score is 22.00 and not 7.00.

        Design: Difficulty/combinatorial_formula/readiness_deficiency_penalty_saturates_at_sixty_point_cap
        """
        _, cycle = _cycle_with_five_criticals(api)

        read = get_success_data(
            api.get_cycle_readiness(cycle["id"], make_verification_reviewer_headers())
        )
        assert_readiness_read(
            read,
            None,
            deficiency_penalty=60,
            outreach_penalty=18.00,
            pi_penalty=0,
            readiness_score=22.00,
            submit_eligible=False,
        )

    def test_the_capped_score_blocks_the_cycle_and_marks_the_center_at_risk(
        self, api: ApiClient
    ) -> None:
        """The clipped score is the one stored, and it is what drives the block.

        Design: Difficulty/combinatorial_formula/readiness_deficiency_penalty_saturates_at_sixty_point_cap
        """
        center, cycle = _cycle_with_five_criticals(api)

        stored = fx.get_cycle(api, cycle["id"])
        assert_decimal(stored["readiness_score"], 22.00, "readiness_score")
        assert stored["open_type_i_count"] == 5
        assert stored["status"] == CycleStatus.PREP_BLOCKED

        after_center = fx.get_center(api, center["id"])
        assert after_center["open_critical_deficiency_count"] == 5
        assert after_center["readiness_posture"] == ReadinessPosture.AT_RISK


class TestOutreachRequirementByCycleType:
    """A national audit asks for more community hours than a state designation does."""

    def test_the_outreach_penalty_tracks_the_cycle_types_required_hours(
        self, api: ApiClient
    ) -> None:
        """Two empty programs differ only in cycle type, and score 82.00 against 88.00.

        Design: Corner/endpoints/readiness_read_reflects_the_cycle_types_required_outreach_hours
        """
        fx.anchor_clock(api)
        national_center = fx.create_center(
            api,
            name="Larkspur Trauma",
            state_code="CO",
            designation_level=DesignationLevel.LEVEL_II,
        )
        state_center = fx.create_center(
            api,
            name="Cedar Bluff Trauma",
            state_code="CO",
            designation_level=DesignationLevel.LEVEL_III,
        )
        national_cycle = fx.create_cycle(
            api,
            national_center["id"],
            cycle_type=CycleType.NATIONAL_VERIFICATION,
            site_visit_date="2026-11-04T13:00:00Z",
        )
        state_cycle = fx.create_cycle(
            api,
            state_center["id"],
            cycle_type=CycleType.STATE_DESIGNATION,
            site_visit_date="2026-11-05T13:00:00Z",
        )

        national_read = get_success_data(
            api.get_cycle_readiness(
                national_cycle["id"],
                make_trauma_program_manager_headers(national_center["id"]),
            )
        )
        assert_readiness_read(
            national_read,
            None,
            deficiency_penalty=0,
            outreach_penalty=18.00,
            pi_penalty=0,
            readiness_score=82.00,
            submit_eligible=True,
        )

        state_read = get_success_data(
            api.get_cycle_readiness(
                state_cycle["id"],
                make_trauma_program_manager_headers(state_center["id"]),
            )
        )
        assert_readiness_read(
            state_read,
            None,
            deficiency_penalty=0,
            outreach_penalty=12.00,
            pi_penalty=0,
            readiness_score=88.00,
            submit_eligible=True,
        )

        assert fx.get_cycle(api, national_cycle["id"])["status"] == CycleStatus.PREP
        assert fx.get_cycle(api, state_cycle["id"])["status"] == CycleStatus.PREP
