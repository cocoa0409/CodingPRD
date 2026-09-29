"""Determination runs: variant selection, the design score and the measured share."""

from test_helpers import (
    OFFICER_HEADERS,
    STARTUP_CLOCK,
    add_audience_sample,
    add_design_factor,
    add_design_factors,
    api_client,
    assert_audience_child_share,
    assert_design_score,
    assert_instant,
    create_service,
    read_service,
    run_determination,
    validate_error,
    validate_paginated,
)


class TestDeterminationVariantDivergence:
    """The two reasoning variants reach different conclusions from identical design evidence."""

    def test_01_verified_panel_selects_audience_first_and_caps_at_mixed_audience(self):
        """A verified panel sample makes measured composition lead.

        "When a verified panel sample exists — that is, when `audience_child_share` is
        non-null — `determination_variant_applied` is `AUDIENCE_FIRST`: measured
        composition leads." A share of 600/4000 is 0.1500, below both the 0.4000 primary
        and 0.2000 mixed thresholds, so the escalation clause applies: "Otherwise, if
        `design_score` is 0.65 or more, design evidence escalates the service to
        `MIXED_AUDIENCE`." Under this variant design evidence "can never reach
        `CHILD_DIRECTED_PRIMARY`, because measured composition has already spoken."

        Design: Difficulty/dual_variant_calc/determination_variant_divergence_audience_first_vs_design_first
        """
        service = create_service(name="Panel Measured Service")
        add_audience_sample(
            service["id"],
            total_users=4000,
            users_under_13=600,
            measurement_method="PANEL",
            period_start="2026-05-01T00:00:00Z",
            period_end="2026-06-01T00:00:00Z",
            sample_verified=True,
        )
        add_design_factor(service["id"], "SUBJECT_MATTER", "STRONG")

        determined = run_determination(service["id"])

        assert determined["determination_variant_applied"] == "AUDIENCE_FIRST", (
            "a verified panel sample must select the AUDIENCE_FIRST variant, got "
            f"{determined['determination_variant_applied']}"
        )
        assert_audience_child_share(determined, 0.1500)
        assert_design_score(determined, 1.00)
        assert determined["determination_status"] == "MIXED_AUDIENCE", (
            "a share of 0.1500 with a design score of 1.00 escalates only as far as "
            f"MIXED_AUDIENCE, got {determined['determination_status']}"
        )
        assert_instant(
            determined["determination_evaluated_at"], STARTUP_CLOCK, "determination_evaluated_at"
        )
        assert determined["compliance_posture"] == "OPEN", (
            "a determination alone must not move the posture axis"
        )

    def test_02_age_screen_log_sample_selects_design_first_and_reaches_primary(self):
        """An age-screen-log sample never qualifies, so design evidence decides alone.

        "Rows measured by `AGE_SCREEN_LOG` or `SELF_REPORTED`, and unverified panel rows,
        are stored as evidence and are visible in the evidence listing, but they never
        enter this aggregate". With no qualifying sample, "`determination_variant_applied`
        is `DESIGN_FIRST` and design evidence decides alone. A `design_score` of 0.75 or
        more makes the service `CHILD_DIRECTED_PRIMARY`."

        Design: Difficulty/dual_variant_calc/determination_variant_divergence_audience_first_vs_design_first
        """
        service = create_service(name="Screen Log Measured Service")
        add_audience_sample(
            service["id"],
            total_users=4000,
            users_under_13=600,
            measurement_method="AGE_SCREEN_LOG",
            period_start="2026-05-01T00:00:00Z",
            period_end="2026-06-01T00:00:00Z",
            sample_verified=True,
        )
        add_design_factor(service["id"], "SUBJECT_MATTER", "STRONG")

        determined = run_determination(service["id"])

        assert determined["determination_variant_applied"] == "DESIGN_FIRST", (
            "an age-screen-log sample does not qualify, so the DESIGN_FIRST variant must "
            f"apply, got {determined['determination_variant_applied']}"
        )
        assert_audience_child_share(determined, None)
        assert_design_score(determined, 1.00)
        assert determined["determination_status"] == "CHILD_DIRECTED_PRIMARY", (
            "a design score of 1.00 under DESIGN_FIRST reaches CHILD_DIRECTED_PRIMARY, got "
            f"{determined['determination_status']}"
        )
        assert determined["compliance_posture"] == "OPEN", (
            "a first determination on a service with no integrations leaves the posture OPEN"
        )


class TestDesignScoreRoundingOrder:
    """Per-contribution rounding, not end-of-sum rounding, decides the threshold."""

    def test_03_three_factor_score_rounds_to_the_inclusive_mixed_threshold(self):
        """Rounding each contribution first lifts the score onto the mixed threshold.

        "each individual factor contribution is rounded half-up to 2 decimal places
        **first**, those rounded contributions are then summed, and the sum is rounded
        half-up to 2 decimal places again." With a present total of 55, the contributions
        round to 0.33, 0.07 and 0.05, summing to 0.45 — where summing unrounded
        contributions would yield 0.44 and miss the threshold, since "a `design_score` of
        exactly 0.45 *is* mixed".

        Design: Difficulty/combinatorial_formula/design_score_rounding_order_flips_two_determination_thresholds
        """
        service = create_service(name="Three Factor Service")
        add_design_factors(
            service["id"],
            [
                ("SUBJECT_MATTER", "MODERATE"),
                ("CHILD_CELEBRITIES", "INCIDENTAL"),
                ("LANGUAGE", "INCIDENTAL"),
            ],
        )

        determined = run_determination(service["id"])

        assert_design_score(determined, 0.45)
        assert_audience_child_share(determined, None)
        assert determined["determination_variant_applied"] == "DESIGN_FIRST"
        assert determined["determination_status"] == "MIXED_AUDIENCE", (
            "a design score of exactly 0.45 is MIXED_AUDIENCE, got "
            f"{determined['determination_status']}"
        )

    def test_04_four_factor_score_rounds_to_the_inclusive_primary_threshold(self):
        """The same rounding order lifts a four-factor score onto the primary threshold.

        With a present total of 70 the contributions round to 0.26, 0.29, 0.13 and 0.07,
        summing to 0.75, where "Summing unrounded contributions and rounding once at the
        end is explicitly rejected as an implementation, because it produces different
        scores" — 0.74, which would fall short of "A `design_score` of 0.75 or more makes
        the service `CHILD_DIRECTED_PRIMARY`."

        Design: Difficulty/combinatorial_formula/design_score_rounding_order_flips_two_determination_thresholds
        """
        service = create_service(name="Four Factor Service")
        add_design_factors(
            service["id"],
            [
                ("SUBJECT_MATTER", "MODERATE"),
                ("VISUAL_CONTENT", "STRONG"),
                ("CHILD_CELEBRITIES", "MODERATE"),
                ("INTERACTIVE_DESIGN", "STRONG"),
            ],
        )

        determined = run_determination(service["id"])

        assert_design_score(determined, 0.75)
        assert_audience_child_share(determined, None)
        assert determined["determination_variant_applied"] == "DESIGN_FIRST"
        assert determined["determination_status"] == "CHILD_DIRECTED_PRIMARY", (
            "a design score of exactly 0.75 is CHILD_DIRECTED_PRIMARY, got "
            f"{determined['determination_status']}"
        )

    def test_05_every_scored_factor_row_is_kept_in_sequence_order(self):
        """The rows that produced the score remain visible in evidence-sequence order.

        "Every accepted row advances the service's `evidence_sequence_counter` by one and
        is stamped with that new value as its `evidence_sequence`, starting at 1 for the
        first row", and the reverse lookup is "ordered by `evidence_sequence` ascending".

        Design: Difficulty/combinatorial_formula/design_score_rounding_order_flips_two_determination_thresholds
        """
        service = create_service(name="Four Factor Evidence Service")
        add_design_factors(
            service["id"],
            [
                ("SUBJECT_MATTER", "MODERATE"),
                ("VISUAL_CONTENT", "STRONG"),
                ("CHILD_CELEBRITIES", "MODERATE"),
                ("INTERACTIVE_DESIGN", "STRONG"),
            ],
        )

        rows, meta = validate_paginated(
            api_client.list_service_determination_evidence(service["id"], OFFICER_HEADERS)
        )

        assert meta["total_count"] == 4, f"four evidence rows were appended, got {meta['total_count']}"
        sequences = [row["evidence_sequence"] for row in rows]
        assert sequences == [1, 2, 3, 4], (
            f"evidence must be stamped 1..4 and listed in that order, got {sequences}"
        )


class TestDeterminationEvidenceSufficiencyAndShareBoundaries:
    """What counts as something to reason from, and where the share thresholds sit."""

    def test_06_determination_without_qualifying_evidence_is_refused(self):
        """A service with nothing to reason from cannot be determined.

        "Before anything else, the service must have something to reason from — at least
        one `DESIGN_FACTOR` evidence row, or at least one `AUDIENCE_SAMPLE` row that was
        measured by `PANEL` and has `sample_verified` true. A service with neither is
        refused with `ERR_INSUFFICIENT_EVIDENCE`, and its `determination_status` remains
        where it was."

        Design: Difficulty/boundary_precision_check/determination_evidence_sufficiency_and_share_threshold_boundaries
        """
        service = create_service(name="No Evidence Service")

        validate_error(
            api_client.run_determination(service["id"], OFFICER_HEADERS),
            "ERR_INSUFFICIENT_EVIDENCE",
        )

        unchanged = read_service(service["id"])
        assert unchanged["determination_status"] == "NOT_ASSESSED", (
            "a refused determination leaves determination_status where it was, got "
            f"{unchanged['determination_status']}"
        )

    def test_07_unverified_panel_row_is_stored_but_is_not_evidence_enough(self):
        """An unverified panel row is kept yet neither qualifies nor feeds the share.

        An unverified panel row does not satisfy "at least one `AUDIENCE_SAMPLE` row that
        was measured by `PANEL` and has `sample_verified` true", and "unverified panel
        rows, are stored as evidence and are visible in the evidence listing, but they
        never enter this aggregate". `sample_verified` "defaults to false".

        Design: Difficulty/boundary_precision_check/determination_evidence_sufficiency_and_share_threshold_boundaries
        """
        service = create_service(name="Unverified Panel Service")
        row = add_audience_sample(
            service["id"],
            total_users=4000,
            users_under_13=1600,
            measurement_method="PANEL",
            period_start="2026-05-01T00:00:00Z",
            period_end="2026-06-01T00:00:00Z",
            sample_verified=None,
        )

        assert row["evidence_sequence"] == 1, (
            f"the stored row must carry evidence_sequence 1, got {row['evidence_sequence']}"
        )
        assert row["sample_verified"] is False, (
            f"sample_verified defaults to false, got {row['sample_verified']}"
        )

        after_append = read_service(service["id"])
        assert_audience_child_share(after_append, None)
        assert_design_score(after_append, 0.00)

        validate_error(
            api_client.run_determination(service["id"], OFFICER_HEADERS),
            "ERR_INSUFFICIENT_EVIDENCE",
        )

    def test_08_share_of_exactly_the_primary_threshold_is_child_directed_primary(self):
        """A measured share of exactly 0.4000 is primary, inclusively.

        "A share of 0.4000 or more makes the service `CHILD_DIRECTED_PRIMARY`" and "Every
        threshold in both variants is inclusive: a share of exactly 0.4000 *is* primary".
        1600/4000 rounds to 0.4000 at four decimal places.

        Design: Difficulty/boundary_precision_check/determination_evidence_sufficiency_and_share_threshold_boundaries
        """
        service = create_service(name="Exactly Forty Percent Service")
        add_audience_sample(
            service["id"],
            total_users=4000,
            users_under_13=1600,
            measurement_method="PANEL",
            period_start="2026-05-01T00:00:00Z",
            period_end="2026-06-01T00:00:00Z",
            sample_verified=True,
        )

        determined = run_determination(service["id"])

        assert_audience_child_share(determined, 0.4000)
        assert determined["determination_variant_applied"] == "AUDIENCE_FIRST"
        assert determined["determination_status"] == "CHILD_DIRECTED_PRIMARY", (
            "a share of exactly 0.4000 is CHILD_DIRECTED_PRIMARY, got "
            f"{determined['determination_status']}"
        )

    def test_09_share_one_user_below_the_primary_threshold_is_only_mixed(self):
        """One user fewer under 13 keeps the service short of primary.

        1599/4000 rounds to 0.3998, so the first clause does not fire and "Otherwise a
        share of 0.2000 or more makes it `MIXED_AUDIENCE`" applies instead. The share is
        "carried to 4 decimal places using round-half-up".

        Design: Difficulty/boundary_precision_check/determination_evidence_sufficiency_and_share_threshold_boundaries
        """
        service = create_service(name="Just Below Forty Percent Service")
        add_design_factor(service["id"], "SUBJECT_MATTER", "MODERATE")
        add_audience_sample(
            service["id"],
            total_users=4000,
            users_under_13=1599,
            measurement_method="PANEL",
            period_start="2026-05-01T00:00:00Z",
            period_end="2026-06-01T00:00:00Z",
            sample_verified=True,
        )

        determined = run_determination(service["id"])

        assert_audience_child_share(determined, 0.3998)
        assert_design_score(determined, 0.60)
        assert determined["determination_variant_applied"] == "AUDIENCE_FIRST"
        assert determined["determination_status"] == "MIXED_AUDIENCE", (
            "a share of 0.3998 falls to the mixed clause, got "
            f"{determined['determination_status']}"
        )

    def test_10_absent_design_factor_scores_zero_and_yields_general_audience(self):
        """A factor documented as absent is evidence enough, and scores nothing.

        A design-factor row satisfies the sufficiency test on its own, while "`ABSENT`
        contributes a multiplier of `0.00`". "When no verified panel sample exists but at
        least one design-factor row does, `determination_variant_applied` is `DESIGN_FIRST`
        and design evidence decides alone. A `design_score` of 0.75 or more makes the service
        `CHILD_DIRECTED_PRIMARY`. Otherwise a `design_score` of 0.45 or more makes it
        `MIXED_AUDIENCE`. Otherwise the service is `GENERAL_AUDIENCE`."

        Design: Difficulty/boundary_precision_check/determination_evidence_sufficiency_and_share_threshold_boundaries
        """
        service = create_service(name="Absent Factor Service")
        add_design_factor(service["id"], "VISUAL_CONTENT", "ABSENT")

        determined = run_determination(service["id"])

        assert_design_score(determined, 0.00)
        assert determined["determination_variant_applied"] == "DESIGN_FIRST"
        assert determined["determination_status"] == "GENERAL_AUDIENCE", (
            "a design score of 0.00 is GENERAL_AUDIENCE, got "
            f"{determined['determination_status']}"
        )


class TestAudienceSamplePeriodPartition:
    """Overlap is judged half-open and only within one measurement method."""

    def test_11_touching_windows_are_compatible_but_straddling_ones_are_not(self):
        """A window may start where the previous one ended, but may not straddle it.

        "Because the interval is half-open, windows that merely touch are compatible: a
        new window whose `period_start` is exactly an existing window's `period_end` is
        accepted." A straddling window instead satisfies the overlap test and "a new
        sample is refused with `ERR_SAMPLE_PERIOD_OVERLAP`".

        Design: Difficulty/resource_temporal_overlap/audience_sample_half_open_overlap_within_measurement_method_partition
        """
        service = create_service(name="Panel Partition Service")
        first = add_audience_sample(
            service["id"],
            total_users=2000,
            users_under_13=500,
            period_start="2026-05-01T00:00:00Z",
            period_end="2026-06-01T00:00:00Z",
        )
        second = add_audience_sample(
            service["id"],
            total_users=2000,
            users_under_13=300,
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
        )

        assert [first["evidence_sequence"], second["evidence_sequence"]] == [1, 2], (
            "two touching panel windows are both accepted and stamped 1 then 2"
        )

        validate_error(
            api_client.create_determination_evidence(
                {
                    "service_id": service["id"],
                    "evidence_kind": "AUDIENCE_SAMPLE",
                    "measurement_method": "PANEL",
                    "period_start": "2026-05-15T00:00:00Z",
                    "period_end": "2026-06-15T00:00:00Z",
                    "total_users": 1000,
                    "users_under_13": 100,
                    "sample_verified": True,
                },
                OFFICER_HEADERS,
            ),
            "ERR_SAMPLE_PERIOD_OVERLAP",
        )

    def test_12_zero_width_window_is_an_invalid_period(self):
        """A window that ends where it starts measures nothing.

        "`period_end` must be strictly later than `period_start`, otherwise the row is
        rejected with `ERR_INVALID_PERIOD`."

        Design: Difficulty/resource_temporal_overlap/audience_sample_half_open_overlap_within_measurement_method_partition
        """
        service = create_service(name="Zero Width Window Service")

        validate_error(
            api_client.create_determination_evidence(
                {
                    "service_id": service["id"],
                    "evidence_kind": "AUDIENCE_SAMPLE",
                    "measurement_method": "PANEL",
                    "period_start": "2026-07-01T00:00:00Z",
                    "period_end": "2026-07-01T00:00:00Z",
                    "total_users": 1000,
                    "users_under_13": 100,
                    "sample_verified": True,
                },
                OFFICER_HEADERS,
            ),
            "ERR_INVALID_PERIOD",
        )

    def test_13_a_different_method_may_reuse_a_refused_interval_and_refusals_consume_no_sequence(
        self,
    ):
        """The overlap partition is per method, and a refused row is stamped nothing.

        "Windows measured by different methods, or belonging to different services, never
        conflict with one another." Because only an accepted row advances the counter —
        "Every accepted row advances the service's `evidence_sequence_counter` by one" —
        the refused panel windows leave the sequence untouched.

        Design: Difficulty/resource_temporal_overlap/audience_sample_half_open_overlap_within_measurement_method_partition
        """
        service = create_service(name="Method Partition Service")
        add_audience_sample(
            service["id"],
            total_users=2000,
            users_under_13=500,
            period_start="2026-05-01T00:00:00Z",
            period_end="2026-06-01T00:00:00Z",
        )
        add_audience_sample(
            service["id"],
            total_users=2000,
            users_under_13=300,
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
        )
        validate_error(
            api_client.create_determination_evidence(
                {
                    "service_id": service["id"],
                    "evidence_kind": "AUDIENCE_SAMPLE",
                    "measurement_method": "PANEL",
                    "period_start": "2026-05-15T00:00:00Z",
                    "period_end": "2026-06-15T00:00:00Z",
                    "total_users": 1000,
                    "users_under_13": 100,
                    "sample_verified": True,
                },
                OFFICER_HEADERS,
            ),
            "ERR_SAMPLE_PERIOD_OVERLAP",
        )

        log_row = add_audience_sample(
            service["id"],
            total_users=1000,
            users_under_13=100,
            measurement_method="AGE_SCREEN_LOG",
            period_start="2026-05-15T00:00:00Z",
            period_end="2026-06-15T00:00:00Z",
        )
        factor_row = add_design_factor(service["id"], "SUBJECT_MATTER", "MODERATE")

        assert log_row["evidence_sequence"] == 3, (
            "the age-screen-log window on the refused interval is the third accepted row, "
            f"got evidence_sequence {log_row['evidence_sequence']}"
        )
        assert factor_row["evidence_sequence"] == 4, (
            "the design-factor row is the fourth accepted row, got evidence_sequence "
            f"{factor_row['evidence_sequence']}"
        )

    def test_14_share_is_one_ratio_over_summed_numerator_and_denominator(self):
        """Two qualifying panels are summed once, not averaged.

        "It is computed once, as a single ratio over a summed numerator and a summed
        denominator across all qualifying samples — never as an average of per-sample
        ratios." 500+300 over 2000+2000 is 0.2000, which meets "Otherwise a share of
        0.2000 or more makes it `MIXED_AUDIENCE`."

        Design: Difficulty/resource_temporal_overlap/audience_sample_half_open_overlap_within_measurement_method_partition
        """
        service = create_service(name="Summed Panel Service")
        add_audience_sample(
            service["id"],
            total_users=2000,
            users_under_13=500,
            period_start="2026-05-01T00:00:00Z",
            period_end="2026-06-01T00:00:00Z",
        )
        add_audience_sample(
            service["id"],
            total_users=2000,
            users_under_13=300,
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
        )
        add_audience_sample(
            service["id"],
            total_users=1000,
            users_under_13=900,
            measurement_method="AGE_SCREEN_LOG",
            period_start="2026-05-15T00:00:00Z",
            period_end="2026-06-15T00:00:00Z",
        )
        add_design_factor(service["id"], "SUBJECT_MATTER", "MODERATE")

        determined = run_determination(service["id"])

        assert_audience_child_share(determined, 0.2000)
        assert_design_score(determined, 0.60)
        assert determined["determination_variant_applied"] == "AUDIENCE_FIRST"
        assert determined["determination_status"] == "MIXED_AUDIENCE", (
            "a share of exactly 0.2000 is MIXED_AUDIENCE, got "
            f"{determined['determination_status']}"
        )

        panel_rows, panel_meta = validate_paginated(
            api_client.list_service_determination_evidence(
                service["id"], OFFICER_HEADERS, {"measurement_method": "PANEL"}
            )
        )
        assert panel_meta["total_count"] == 2, (
            f"only the two panel rows qualify as PANEL, got {panel_meta['total_count']}"
        )
        assert all(row["measurement_method"] == "PANEL" for row in panel_rows)
