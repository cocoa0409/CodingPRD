"""What a freshly written row looks like, and what a read of one returns."""

from test_helpers import (
    ApiErrorId,
    BusinessLineStatus,
    IntakePosture,
    MouStatus,
    MouTier,
    ParticipantStatus,
    ReferralStatus,
    UNKNOWN_UUID_1,
    UNKNOWN_UUID_2,
    UNKNOWN_UUID_3,
    UNKNOWN_UUID_4,
    WorkShiftStatus,
    assert_business_line,
    assert_hours,
    assert_instant_equals,
    assert_participant,
    assert_ratio,
    assert_referral_partner,
    assert_score,
    assert_work_shift,
    factories,
    fixtures,
    make_case_manager_headers,
    make_funder_analyst_headers,
    make_intake_specialist_headers,
    make_job_coach_headers,
    make_program_director_headers,
    parse_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_SEP_07
from test_helpers.types import CustomerServiceStandard


def _launched_line_with_eligible_referral(api):
    """A launched line, a TIER_1 partner, one ELIGIBLE referral and an open period."""
    fixtures.set_clock(api, CLOCK_SEP_07)
    line = fixtures.create_launched_business_line(api)
    partner = fixtures.create_referral_partner(api)
    referral = fixtures.create_eligible_referral(api, partner["id"])
    period = fixtures.create_open_subsidy_period(api, line["id"])
    return {
        "business_line": line,
        "partner": partner,
        "referral": referral,
        "subsidy_period": period,
    }


class TestBusinessLineCreation:
    """A candidate line arrives scored, closed to intake and unlaunched."""

    def test_a_new_line_derives_its_composite_score_and_default_state(self, api):
        """Creation weights the three dimensions and zeroes everything else.

        "On creation the system derives the line's **composite viability score** and
        stores it as `composite_viability_score`: forty percent of
        `market_viability_score`, plus thirty-five percent of
        `training_relevance_score`, plus twenty-five percent of
        `mission_alignment_score`, with the sum rounded half up to two decimal
        places."
        "A newly created line begins in `DRAFT` `status` with `intake_posture` set to
        `CLOSED`, `training_slots_filled` at 0, `cumulative_subsidy_cents` at 0,
        `quality_incident_count` at 0, and both `rejection_reason` and `launched_at`
        null."

        Design: Corner/entities/create_business_line_returns_computed_and_default_fields
        """
        fixtures.set_clock(api, CLOCK_SEP_07)

        response = api.create_business_line(
            factories.business_line_payload(), make_program_director_headers()
        )
        line = validate_success(response, 201)

        assert_business_line(line)
        assert_score(
            line["composite_viability_score"], 82.75, "composite_viability_score"
        )
        assert line["status"] == BusinessLineStatus.DRAFT
        assert line["intake_posture"] == IntakePosture.CLOSED
        assert line["launched_at"] is None
        assert line["rejection_reason"] is None
        assert line["training_slots_total"] == 3
        assert line["training_slots_filled"] == 0
        assert line["supervisor_capacity"] == 2
        assert line["cumulative_subsidy_cents"] == 0
        assert line["quality_incident_count"] == 0
        assert line["subsidy_cap_cents"] == 5000000
        assert_ratio(
            line["target_gross_margin_pct"], 0.2000, "target_gross_margin_pct"
        )
        assert line["version"] == 1


class TestReferralPartnerRegistration:
    """A partner's counters start empty and its conversion rate starts null."""

    def test_reading_a_registered_partner_returns_its_stored_row(self, api):
        """An untouched partner reports a null conversion rate, never zero.

        "A freshly registered partner has `referrals_submitted_count` at 0,
        `enrolled_referral_count` at 0, and `conversion_rate` null."
        "`conversion_rate` is `enrolled_referral_count` divided by
        `referrals_submitted_count`, rounded half up to four decimal places, and is
        `null` — never 0 — while the partner has submitted nothing at all."

        Design: Corner/entities/get_referral_partner_returns_stored_row
        """
        fixtures.set_clock(api, CLOCK_SEP_07)
        created = fixtures.create_referral_partner(api)

        response = api.get_referral_partner(
            created["id"], make_funder_analyst_headers()
        )
        partner = validate_success(response)

        assert_referral_partner(partner)
        assert partner["id"] == created["id"]
        assert partner["organization_name"] == "Eastside Works"
        assert partner["mou_tier"] == MouTier.TIER_1
        assert partner["referral_quota_per_period"] == 5
        assert partner["mou_status"] == MouStatus.ACTIVE
        assert partner["referrals_submitted_count"] == 0
        assert partner["enrolled_referral_count"] == 0
        assert partner["conversion_rate"] is None

    def test_omitting_the_mou_status_registers_an_active_partner(self, api):
        """The optional MOU status defaults to ACTIVE.

        "The partner's `mou_status` may be supplied and defaults to `ACTIVE`; the
        only other permitted value is `LAPSED`."

        Design: Corner/entities/create_referral_partner_omitting_mou_status_applies_default
        """
        fixtures.set_clock(api, CLOCK_SEP_07)

        response = api.create_referral_partner(
            {
                "organization_name": "Riverside Pathways",
                "mou_tier": MouTier.TIER_3,
                "referral_quota_per_period": 2,
            },
            make_program_director_headers(),
        )
        partner = validate_success(response, 201)

        assert_referral_partner(partner)
        assert partner["mou_status"] == MouStatus.ACTIVE
        assert partner["referrals_submitted_count"] == 0
        assert partner["enrolled_referral_count"] == 0
        assert partner["conversion_rate"] is None
        assert partner["mou_tier"] == MouTier.TIER_3
        assert partner["referral_quota_per_period"] == 2
        assert partner["version"] == 1


class TestReferralListing:
    """Three referrals read back across two pages of two."""

    def test_the_referral_listing_reports_the_pre_pagination_total(self, api):
        """total_count counts matching rows before the window is applied.

        "Every paginated response carries `limit`, `offset`, `total_count`, and
        `has_more` inside the `meta` object of the envelope, where `total_count` is
        the number of matching rows before pagination is applied."

        Design: Corner/entities/list_referrals_paginates_with_total_count_and_has_more
        """
        fixtures.set_clock(api, CLOCK_SEP_07)
        partner = fixtures.create_referral_partner(api)
        for reference, barrier in (
            ("CAND-001", "JUSTICE_INVOLVED"),
            ("CAND-002", "HOUSING_INSTABILITY"),
            ("CAND-003", "LONG_TERM_UNEMPLOYED"),
        ):
            fixtures.submit_referral(
                api,
                partner["id"],
                candidate_reference=reference,
                declared_barrier_codes=[barrier],
            )

        first_page, first_meta = validate_paginated(
            api.list_referrals(
                make_intake_specialist_headers(),
                {"referral_partner_id": partner["id"], "limit": 2, "offset": 0},
            )
        )
        second_page, second_meta = validate_paginated(
            api.list_referrals(
                make_intake_specialist_headers(),
                {"referral_partner_id": partner["id"], "limit": 2, "offset": 2},
            )
        )

        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["offset"] == 2

        references = [row["candidate_reference"] for row in first_page + second_page]
        assert sorted(references) == ["CAND-001", "CAND-002", "CAND-003"]


class TestUnknownIdentifiers:
    """An id that resolves to nothing is answered by the type's own 404."""

    def test_reading_an_unknown_work_shift_returns_the_work_shift_code(self, api):
        """Existence is checked against the identifier's own type.

        "Every identifier the request references must resolve to a row."
        "The failure carries the code for the missing type:
        `ERR_BUSINESS_LINE_NOT_FOUND`, `ERR_REFERRAL_PARTNER_NOT_FOUND`,
        `ERR_REFERRAL_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`,
        `ERR_WORK_SHIFT_NOT_FOUND`, `ERR_SHIFT_ASSIGNMENT_NOT_FOUND`,
        `ERR_SUPPORT_ACTIVITY_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`,
        `ERR_PLACEMENT_NOT_FOUND`, `ERR_RETENTION_CHECKPOINT_NOT_FOUND`,
        `ERR_SUBSIDY_PERIOD_NOT_FOUND`, or `ERR_COST_ENTRY_NOT_FOUND`, each with
        HTTP 404."

        Design: Corner/entities/get_work_shift_with_unknown_id_returns_not_found
        """
        fixtures.set_clock(api, CLOCK_SEP_07)

        response = api.get_work_shift(UNKNOWN_UUID_1, make_program_director_headers())

        error = validate_error(response, ApiErrorId.ERR_WORK_SHIFT_NOT_FOUND, 404)
        assert isinstance(error["message"], str) and error["message"]

    def test_a_placement_resolves_its_body_keys_in_declared_order(self, api):
        """The participant is declared first, so its absence is reported first.

        "Every identifier the request references must resolve to a row. Path
        identifiers are checked first, left to right, then body foreign keys in the
        order they are declared in the endpoint's input list."

        Design: Corner/entities/create_placement_with_unknown_ids_returns_not_found_in_declared_order
        """
        setup = _launched_line_with_eligible_referral(api)
        participant = fixtures.enroll_participant(
            api, setup["business_line"]["id"], setup["referral"]["id"]
        )

        unknown_employer = api.create_placement(
            factories.placement_payload(participant["id"], UNKNOWN_UUID_2),
            make_case_manager_headers(),
        )
        both_unknown = api.create_placement(
            factories.placement_payload(UNKNOWN_UUID_3, UNKNOWN_UUID_2),
            make_case_manager_headers(),
        )

        validate_error(unknown_employer, ApiErrorId.ERR_EMPLOYER_NOT_FOUND, 404)
        validate_error(both_unknown, ApiErrorId.ERR_PARTICIPANT_NOT_FOUND, 404)

        _rows, meta = validate_paginated(
            api.list_placements(
                make_case_manager_headers(), {"participant_id": participant["id"]}
            )
        )
        assert meta["total_count"] == 0

        unchanged = fixtures.read_participant(api, participant["id"])
        assert unchanged["status"] == ParticipantStatus.TRANSITIONAL_EMPLOYED

    def test_an_unknown_period_outranks_the_version_guard_on_a_cost_entry(self, api):
        """Existence precedes the version guard, so the answer is a 404.

        "Rules are evaluated strictly in the order below, and the **first** failing
        rule decides the response; no later rule is evaluated, and no state is
        written."

        Design: Corner/entities/create_cost_entry_with_unknown_subsidy_period_returns_not_found
        """
        fixtures.set_clock(api, CLOCK_SEP_07)
        line = fixtures.create_launched_business_line(api)
        period = fixtures.create_open_subsidy_period(api, line["id"])

        response = api.create_cost_entry(
            factories.cost_entry_payload(
                UNKNOWN_UUID_4,
                period["version"],
                category="MATERIALS",
                classification="BUSINESS",
                amount_cents=40000,
            ),
            make_program_director_headers(),
        )

        validate_error(response, ApiErrorId.ERR_SUBSIDY_PERIOD_NOT_FOUND, 404)

        assert fixtures.cost_entry_count(api, {"subsidy_period_id": period["id"]}) == 0
        unchanged = fixtures.read_subsidy_period(api, period["id"])
        assert unchanged["version"] == period["version"]
        assert unchanged["total_cost_cents"] == 0


class TestRequestShapeOnCreation:
    """A body that misses a required field, or names an undeclared member, is 422."""

    def test_enrolling_without_a_transitional_wage_is_a_shape_failure(self, api):
        """A missing required field is refused before any state is written.

        "The body conforms to the endpoint's input schema: required fields present,
        enum members drawn from the declared sets, integers inside their declared
        ranges, datetimes valid ISO 8601 UTC, a shift's `ends_at` strictly after its
        `starts_at`, a period's `period_end` strictly after its `period_start`,
        `duration_minutes` exactly 0 for the two voucher categories and strictly
        greater than 0 for the two contact categories, `actual_hours` strictly
        greater than 0, a `REJECTED` review decision accompanied by a
        `rejection_reason`, and a `VERIFY` wage-verification action accompanied by a
        `verified_wage_cents_per_hour`. Otherwise `ERR_INVALID_REQUEST` (422)."

        Design: Corner/entities/create_participant_missing_required_wage_returns_invalid_request
        """
        setup = _launched_line_with_eligible_referral(api)
        line_id = setup["business_line"]["id"]
        line_version = fixtures.business_line_version(api, line_id)

        payload = factories.participant_payload(
            setup["referral"]["id"], line_id, line_version
        )
        payload.pop("wage_cents_per_hour")
        response = api.create_participant(payload, make_intake_specialist_headers())

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 422)

        referral = fixtures.read_referral(api, setup["referral"]["id"])
        assert referral["status"] == ReferralStatus.ELIGIBLE

        line = fixtures.read_business_line(api, line_id)
        assert line["training_slots_filled"] == 0
        assert line["version"] == line_version

    def test_an_undeclared_category_and_an_inverted_interval_are_shape_failures(
        self, api
    ):
        """Enum membership and interval direction are both shape rules.

        "The body conforms to the endpoint's input schema: required fields present,
        enum members drawn from the declared sets, integers inside their declared
        ranges, datetimes valid ISO 8601 UTC, a shift's `ends_at` strictly after its
        `starts_at`, a period's `period_end` strictly after its `period_start`,
        `duration_minutes` exactly 0 for the two voucher categories and strictly
        greater than 0 for the two contact categories, `actual_hours` strictly
        greater than 0, a `REJECTED` review decision accompanied by a
        `rejection_reason`, and a `VERIFY` wage-verification action accompanied by a
        `verified_wage_cents_per_hour`. Otherwise `ERR_INVALID_REQUEST` (422)."

        Design: Corner/entities/create_support_activity_with_invalid_category_rejected
        """
        setup = _launched_line_with_eligible_referral(api)
        participant = fixtures.enroll_participant(
            api, setup["business_line"]["id"], setup["referral"]["id"]
        )

        undeclared_category = api.create_support_activity(
            factories.support_activity_payload(participant["id"], category="MENTORING"),
            make_job_coach_headers(),
        )
        inverted_interval = api.create_work_shift(
            factories.work_shift_payload(
                setup["business_line"]["id"],
                starts_at="2026-09-07T20:00:00Z",
                ends_at="2026-09-07T08:00:00Z",
            ),
            make_program_director_headers(),
        )

        validate_error(undeclared_category, ApiErrorId.ERR_INVALID_REQUEST, 422)
        validate_error(inverted_interval, ApiErrorId.ERR_INVALID_REQUEST, 422)

        _activities, activity_meta = validate_paginated(
            api.list_support_activities(
                make_job_coach_headers(), {"participant_id": participant["id"]}
            )
        )
        assert activity_meta["total_count"] == 0

        _shifts, shift_meta = validate_paginated(
            api.list_work_shifts(
                make_program_director_headers(),
                {"business_line_id": setup["business_line"]["id"]},
            )
        )
        assert shift_meta["total_count"] == 0


class TestServerOwnedFields:
    """Derived fields and system fields are the server's, whatever the caller sends."""

    def test_a_shift_derives_its_duration_and_ignores_supplied_derived_values(
        self, api
    ):
        """The half-open interval, not the caller, sets duration_hours.

        "Derived fields are never client-supplied."
        "On creation the shift is `SCHEDULED`, its `duration_hours` is derived from
        the half-open interval, `assigned_count` is 0, both quality counters are 0,
        and `billable_labor_cost_cents` is null."

        Design: Corner/entities/create_work_shift_computed_fields_input_ignored
        """
        fixtures.set_clock(api, CLOCK_SEP_07)
        line = fixtures.create_launched_business_line(api)

        response = api.create_work_shift(
            factories.work_shift_payload(
                line["id"],
                duration_hours=99.0,
                status=WorkShiftStatus.CLOSED,
                assigned_count=7,
                billable_labor_cost_cents=12345,
            ),
            make_program_director_headers(),
        )
        shift = validate_success(response, 201)

        assert_work_shift(shift)
        assert_hours(shift["duration_hours"], 12.000, "duration_hours")
        assert shift["status"] == WorkShiftStatus.SCHEDULED
        assert shift["assigned_count"] == 0
        assert shift["billable_labor_cost_cents"] is None
        assert shift["quality_defect_count"] == 0
        assert shift["customer_complaint_count"] == 0
        assert shift["customer_service_standard"] == CustomerServiceStandard.STANDARD
        assert shift["version"] == 1

    def test_enrollment_stamps_its_timestamps_from_the_logical_clock(self, api):
        """created_at, updated_at and enrolled_at all read the pinned instant.

        "A successful enrollment writes a participant in `TRANSITIONAL_EMPLOYED`
        `status` with `enrolled_at` stamped from the logical clock, all four progress
        metrics at their zero values, `re_entry_count` at 0, and
        `readiness_certified_by_user_id`, `readiness_certified_at`, `graduated_at`,
        `graduation_wage_cents_per_hour` and `eligible_re_entry_at` all null."
        "Optionally the specialist may set `max_transitional_weeks`, the duration
        limit on this person's transitional employment, which defaults to 26 and must
        be between 8 and 52."

        Design: Corner/entities/enroll_participant_stamps_system_fields_from_logical_clock
        """
        setup = _launched_line_with_eligible_referral(api)
        line_id = setup["business_line"]["id"]

        response = api.create_participant(
            factories.participant_payload(
                setup["referral"]["id"],
                line_id,
                fixtures.business_line_version(api, line_id),
            ),
            make_intake_specialist_headers(),
        )
        participant = validate_success(response, 201)

        assert_participant(participant)
        assert participant["version"] == 1
        assert parse_instant(participant["created_at"]) == parse_instant(
            participant["updated_at"]
        )
        assert_instant_equals(participant["created_at"], CLOCK_SEP_07, "created_at")
        assert_instant_equals(participant["enrolled_at"], CLOCK_SEP_07, "enrolled_at")
        assert participant["max_transitional_weeks"] == 26
        assert participant["status"] == ParticipantStatus.TRANSITIONAL_EMPLOYED
        assert_hours(
            participant["transitional_hours_worked"],
            0.000,
            "transitional_hours_worked",
        )
        assert participant["support_activity_minutes"] == 0
        assert participant["delivered_coaching_count"] == 0
        assert participant["re_entry_count"] == 0
        assert participant["graduated_at"] is None
        assert participant["graduation_wage_cents_per_hour"] is None
        assert participant["eligible_re_entry_at"] is None
