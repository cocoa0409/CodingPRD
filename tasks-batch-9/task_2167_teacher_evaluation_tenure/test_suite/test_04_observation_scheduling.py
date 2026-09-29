"""Scheduling observations: calendars, formal spacing, certification currency
and the dispute lock."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_cycle,
    file_appeal,
    get_cycle,
    get_evaluator,
    make_evaluator_headers,
    observation_payload,
    schedule_observation,
    set_clock,
    setup_cycle,
    setup_district,
    setup_finalized_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

HR = TEST_USERS["hr_admin_headers"]


class TestEvaluatorCalendar:
    """Occupation is the half-open interval [scheduled_start, scheduled_end)."""

    @staticmethod
    def _two_educators_one_booked_window():
        ctx = setup_district(extra_educators=1)
        cycle_one = create_cycle(ctx["educator"]["id"], ctx["policy"]["id"])
        cycle_two = create_cycle(ctx["other_educators"][0]["id"], ctx["policy"]["id"])
        schedule_observation(
            cycle_one["id"], ctx["evaluator"]["id"],
            observation_type="FORMAL",
            scheduled_start="2026-09-10T09:00:00Z",
            scheduled_end="2026-09-10T10:00:00Z",
        )
        return ctx, cycle_one, cycle_two

    def test_overlapping_window_for_the_same_evaluator_is_rejected(self, api):
        """PRD §3.3: "First, the requested window occupies the evaluator's
        calendar as a half-open interval — the instant at `scheduled_start` is
        occupied, the instant at `scheduled_end` is not — and it must not
        intersect the window of any other non-`VOIDED` observation of the same
        evaluator."
        PRD §3.3: "Two windows that merely touch, where one ends at precisely
        the instant the other begins, are adjacent rather than overlapping and are
        permitted. An intersection yields `ERR_EVALUATOR_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/evaluator_window_half_open_rejects_overlap_allows_adjacency
        """
        ctx, _cycle_one, cycle_two = self._two_educators_one_booked_window()

        response = api.create_observation(
            observation_payload(cycle_two["id"], ctx["evaluator"]["id"],
                                observation_type="FORMAL",
                                scheduled_start="2026-09-10T09:30:00Z",
                                scheduled_end="2026-09-10T10:30:00Z"),
            make_evaluator_headers(ctx["evaluator"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_EVALUATOR_WINDOW_CONFLICT.value, 409)

        listed, _meta = validate_paginated(
            api.list_observations(HR, params={"cycle_id": cycle_two["id"]})
        )
        assert listed == [], "the rejected window must create no observation"

    def test_adjacent_window_touching_the_previous_end_is_accepted(self, api):
        """PRD §3.3: "Two windows that merely touch, where one ends at precisely
        the instant the other begins, are adjacent rather than overlapping and are
        permitted."
        PRD §3.3: "A newly scheduled observation begins at `status` `SCHEDULED`,
        with `scored_domain_count`, `evidence_count`, `stipend_cents` and
        `return_count` all 0, `weighted_score` null, and `return_reason` and
        `void_reason` null."

        Design: Difficulty/resource_temporal_overlap/evaluator_window_half_open_rejects_overlap_allows_adjacency
        """
        ctx, _cycle_one, cycle_two = self._two_educators_one_booked_window()

        response = api.create_observation(
            observation_payload(cycle_two["id"], ctx["evaluator"]["id"],
                                observation_type="FORMAL",
                                scheduled_start="2026-09-10T10:00:00Z",
                                scheduled_end="2026-09-10T11:00:00Z"),
            make_evaluator_headers(ctx["evaluator"]["id"]),
        )
        adjacent = validate_success(response, 201)

        assert adjacent["status"] == "SCHEDULED"
        assert adjacent["scheduled_start"].startswith("2026-09-10T10:00:00")
        assert adjacent["scored_domain_count"] == 0
        assert adjacent["stipend_cents"] == 0
        assert adjacent["weighted_score"] is None

        listed, _meta = validate_paginated(
            api.list_observations(HR, params={"evaluator_id": ctx["evaluator"]["id"]})
        )
        assert len(listed) == 2, "the evaluator now holds two adjacent windows"


class TestFormalSpacing:
    """Formal observations of one educator must be spread out."""

    @staticmethod
    def _cycle_with_first_formal():
        ctx = setup_cycle(policy_overrides={"min_days_between_formals": 10})
        schedule_observation(
            ctx["cycle"]["id"], ctx["evaluator"]["id"],
            observation_type="FORMAL",
            scheduled_start="2026-09-10T09:00:00Z",
            scheduled_end="2026-09-10T10:00:00Z",
        )
        return ctx

    def test_second_formal_nine_days_later_violates_the_spacing_rule(self, api):
        """PRD §3.3: "Second, formal observations of a single educator must be
        spread out: for a `FORMAL` observation, no other non-`VOIDED` `FORMAL`
        observation belonging to *any* cycle of that same educator may have a
        `scheduled_start` closer than the policy's `min_days_between_formals`
        whole days away."
        PRD §3.3: "The comparison is strict, so two formals exactly
        `min_days_between_formals` days apart are acceptable and only a strictly
        smaller separation is rejected, with `ERR_FORMAL_SPACING_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/educator_formal_spacing_buffer_rejects_nine_days_allows_ten
        """
        ctx = self._cycle_with_first_formal()

        response = api.create_observation(
            observation_payload(ctx["cycle"]["id"], ctx["evaluator"]["id"],
                                observation_type="FORMAL",
                                scheduled_start="2026-09-19T09:00:00Z",
                                scheduled_end="2026-09-19T10:00:00Z"),
            make_evaluator_headers(ctx["evaluator"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_FORMAL_SPACING_VIOLATION.value, 409)

        listed, _meta = validate_paginated(
            api.list_observations(HR, params={"cycle_id": ctx["cycle"]["id"]})
        )
        assert len(listed) == 1, "the rejected formal must not be recorded"

    def test_second_formal_exactly_ten_days_later_is_accepted(self, api):
        """PRD §3.3: "The comparison is strict, so two formals exactly
        `min_days_between_formals` days apart are acceptable and only a strictly
        smaller separation is rejected, with `ERR_FORMAL_SPACING_VIOLATION`."
        PRD §2.5: "`tenure_required_years` defaults to 3 and
        `tenure_min_consecutive_effective` to 2. `min_days_between_formals`
        defaults to 10."

        Design: Difficulty/resource_temporal_overlap/educator_formal_spacing_buffer_rejects_nine_days_allows_ten
        """
        ctx = self._cycle_with_first_formal()

        response = api.create_observation(
            observation_payload(ctx["cycle"]["id"], ctx["evaluator"]["id"],
                                observation_type="FORMAL",
                                scheduled_start="2026-09-20T09:00:00Z",
                                scheduled_end="2026-09-20T10:00:00Z"),
            make_evaluator_headers(ctx["evaluator"]["id"]),
        )
        accepted = validate_success(response, 201)

        assert accepted["status"] == "SCHEDULED"
        assert accepted["scheduled_start"].startswith("2026-09-20T09:00:00")
        listed, _meta = validate_paginated(
            api.list_observations(HR, params={"cycle_id": ctx["cycle"]["id"]})
        )
        assert len(listed) == 2, "the cycle now carries two spaced formals"


class TestCertificationCurrencyBeatsCalendarConflict:
    """The clock has passed the expiry and the window intersects; the 422 wins."""

    @staticmethod
    def _lapsed_evaluator_with_a_booked_window():
        ctx = setup_cycle()
        schedule_observation(
            ctx["cycle"]["id"], ctx["evaluator"]["id"],
            observation_type="FORMAL",
            scheduled_start="2026-09-10T09:00:00Z",
            scheduled_end="2026-09-10T10:00:00Z",
        )
        set_clock("2027-09-02T00:00:00Z")
        return ctx

    def test_lapsed_certification_is_reported_before_the_window_conflict(self, api):
        """PRD §3.3: "The logical clock's date must be on or before that
        evaluator's `certification_expires_on`; a date after it yields
        `ERR_EVALUATOR_CERTIFICATION_LAPSED`."
        PRD §2.8: "When several checks could reject the same request, the order in
        which they are evaluated is fixed, because the error the caller receives
        must be predictable. Checks are applied in this sequence, and the first
        one that fails determines the response:"
        PRD §2.8: "**Certification currency**, `ERR_EVALUATOR_CERTIFICATION_LAPSED`
        (HTTP 422), guarding exactly two operations: scheduling an observation and
        marking an observation conducted."
        PRD §2.8: "**Evaluator window conflict**, `ERR_EVALUATOR_WINDOW_CONFLICT`
        (HTTP 409), on observation scheduling."

        Design: Difficulty/priority_pair_validation_conflict/certification_lapse_beats_evaluator_window_conflict_on_schedule
        """
        ctx = self._lapsed_evaluator_with_a_booked_window()

        response = api.create_observation(
            observation_payload(ctx["cycle"]["id"], ctx["evaluator"]["id"],
                                observation_type="INFORMAL",
                                scheduled_start="2026-09-10T09:30:00Z",
                                scheduled_end="2026-09-10T10:30:00Z"),
            make_evaluator_headers(ctx["evaluator"]["id"]),
        )
        error_data = validate_error(
            response, ApiErrorId.ERR_EVALUATOR_CERTIFICATION_LAPSED.value, 422
        )
        assert error_data["error_id"] != ApiErrorId.ERR_EVALUATOR_WINDOW_CONFLICT.value
        assert error_data["error_id"] != ApiErrorId.ERR_EVALUATOR_NOT_CERTIFIED.value

    def test_the_lapse_leaves_the_certification_status_and_the_calendar_untouched(self, api):
        """PRD §3.3: "The named evaluator's `certification_status` must read
        `CERTIFIED` — a `PROVISIONAL` or `SUSPENDED` evaluator yields
        `ERR_EVALUATOR_NOT_CERTIFIED`."
        PRD §3.3: "The logical clock's date must be on or before that evaluator's
        `certification_expires_on`; a date after it yields
        `ERR_EVALUATOR_CERTIFICATION_LAPSED`."
        PRD §3.2: "A `PROVISIONAL` evaluator becomes `CERTIFIED` when a review
        resolves `PASS` *and* the recomputed `calibration_drift_rolling` is at or
        below the policy's `calibration_drift_tolerance`; on that transition
        `certification_expires_on` is set to the logical clock's current date plus
        a one-year certification term of 365 days,
        `consecutive_failed_calibrations` is reset to 0, and
        `passed_calibration_count` increases by 1."

        Design: Difficulty/priority_pair_validation_conflict/certification_lapse_beats_evaluator_window_conflict_on_schedule
        """
        ctx = self._lapsed_evaluator_with_a_booked_window()

        api.create_observation(
            observation_payload(ctx["cycle"]["id"], ctx["evaluator"]["id"],
                                observation_type="INFORMAL",
                                scheduled_start="2026-09-10T09:30:00Z",
                                scheduled_end="2026-09-10T10:30:00Z"),
            make_evaluator_headers(ctx["evaluator"]["id"]),
        )

        evaluator = get_evaluator(ctx["evaluator"]["id"])
        assert evaluator["certification_status"] == "CERTIFIED", (
            "only the date comparison failed; the status field is untouched"
        )
        assert evaluator["certification_expires_on"] == "2027-09-01"

        listed, _meta = validate_paginated(
            api.list_observations(HR, params={"cycle_id": ctx["cycle"]["id"]})
        )
        assert len(listed) == 1, "no second observation may exist for the cycle"


def test_an_open_appeal_locks_the_cycle_against_further_scheduling(api):
    """PRD §3.8: "The `educator_id` is copied onto the appeal from the cycle at
    filing time rather than supplied."
    PRD §3.8: "A successful filing creates the appeal at `status` `FILED` with
    `panelist_evaluator_id`, `adjusted_composite` and `decided_at` all null, moves
    the cycle's `dispute_state` from `NONE` to `APPEALED`, and increments the
    cycle's `version`."
    PRD §3.3: "The cycle's `dispute_state` must read `NONE`, because scoring-side
    work stops while a dispute is live; anything else yields
    `ERR_DISPUTE_IN_PROGRESS`."

    Design: Corner/validations/dispute_lock_blocks_scoring_writes_while_an_appeal_is_open
    """
    ctx = setup_finalized_cycle(
        policy_overrides={"required_formal_count": 1, "required_informal_count": 0,
                          "evidence_min_artifacts": 2},
        formal_scores=(3, 3, 4, 3), artifacts=2,
    )

    appeal = file_appeal(ctx["cycle"]["id"], ctx["educator"]["id"])
    assert appeal["status"] == "FILED"
    assert appeal["educator_id"] == ctx["educator"]["id"], (
        "the appeal copies educator_id from the cycle"
    )
    assert get_cycle(ctx["cycle"]["id"])["dispute_state"] == "APPEALED"

    response = api.create_observation(
        observation_payload(ctx["cycle"]["id"], ctx["evaluator"]["id"],
                            observation_type="INFORMAL",
                            scheduled_start="2026-09-20T09:00:00Z",
                            scheduled_end="2026-09-20T09:30:00Z"),
        make_evaluator_headers(ctx["evaluator"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DISPUTE_IN_PROGRESS.value, 409)

    listed, _meta = validate_paginated(
        api.list_observations(HR, params={"cycle_id": ctx["cycle"]["id"]})
    )
    assert len(listed) == 1, "the locked cycle still carries exactly one observation"
