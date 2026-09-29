"""Where the ladder decides: authentication, ownership, intervals and aggregates."""

from test_helpers import (
    AllocationBasis,
    ApiErrorId,
    MouTier,
    ReferralStatus,
    ReleasedReason,
    ShiftAssignmentStatus,
    SubsidyPeriodStatus,
    assert_hours,
    assert_period_ledger,
    assert_ratio,
    factories,
    fixtures,
    headers_without_role,
    headers_with_undeclared_role,
    make_funder_analyst_headers,
    make_intake_specialist_headers,
    make_program_director_headers,
    make_referral_partner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_OCT_01, CLOCK_SEP_07, UNKNOWN_UUID_1

SEPTEMBER_PERIOD_END = "2026-09-30T00:00:00Z"


class TestAuthenticationPrecedesEverything:
    """Rung one asks who is calling before anything else is considered."""

    def test_an_omitted_role_header_is_unauthenticated(self, api):
        """Both headers must be present.

        "**Authentication.** Both `X-User-ID` and `X-User-Role` present, and
        `X-User-Role` one of the seven declared roles — otherwise
        `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

        Design: Corner/validations/missing_x_user_role_header_returns_unauthenticated
        """
        response = api.list_participants(headers_without_role())

        error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)

        assert error["message"]
        meta = response.json()["meta"]
        assert meta["api_request_id"].startswith("req_")
        assert meta["api_request_timestamp"]

    def test_a_role_outside_the_declared_seven_is_unauthenticated(self, api):
        """An unknown role name fails authentication, not authorization.

        "**Authentication.** Both `X-User-ID` and `X-User-Role` present, and
        `X-User-Role` one of the seven declared roles — otherwise
        `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

        Design: Corner/validations/missing_x_user_role_header_returns_unauthenticated
        """
        response = api.list_participants(headers_with_undeclared_role())

        error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)

        assert error["message"]
        meta = response.json()["meta"]
        assert meta["api_request_id"].startswith("req_")
        assert meta["api_request_timestamp"]


class TestReferralOwnership:
    """A partner sees its own candidates and nobody else's."""

    def _two_partners_and_one_referral(self, api):
        """Partner A owns CAND-401; partner B owns nothing."""
        fixtures.set_clock(api, CLOCK_SEP_07)
        partner_a = fixtures.create_referral_partner(
            api,
            organization_name="Partner A",
            mou_tier=MouTier.TIER_1,
            referral_quota_per_period=5,
        )
        partner_b = fixtures.create_referral_partner(
            api,
            organization_name="Partner B",
            mou_tier=MouTier.TIER_1,
            referral_quota_per_period=5,
        )
        referral = fixtures.submit_referral(
            api,
            partner_a["id"],
            candidate_reference="CAND-401",
            declared_barrier_codes=["JUSTICE_INVOLVED"],
        )
        return {"partner_a": partner_a, "partner_b": partner_b, "referral": referral}

    def test_a_partner_may_not_read_another_partners_referral(self, api):
        """Ownership is checked against the target row, and the row does exist.

        "**Ownership.** For the two entity-backed roles, `X-User-ID` must equal
        the owning entity id of the target resource — otherwise
        `ERR_NOT_RESOURCE_OWNER` (403). Applies to referral submission,
        single-referral read, placement separation, placement wage verification,
        and retention-checkpoint confirmation."

        Design: Corner/validations/referral_partner_reading_another_partners_referral_is_forbidden
        """
        rows = self._two_partners_and_one_referral(api)

        response = api.get_referral(
            rows["referral"]["id"], make_referral_partner_headers(rows["partner_b"]["id"])
        )

        validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    def test_the_owning_partner_and_the_intake_specialist_both_read_it(self, api):
        """The ownership rung binds only the two entity-backed roles.

        "**Ownership.** For the two entity-backed roles, `X-User-ID` must equal
        the owning entity id of the target resource — otherwise
        `ERR_NOT_RESOURCE_OWNER` (403). Applies to referral submission,
        single-referral read, placement separation, placement wage verification,
        and retention-checkpoint confirmation."

        Design: Corner/validations/referral_partner_reading_another_partners_referral_is_forbidden
        """
        rows = self._two_partners_and_one_referral(api)

        owner_view = validate_success(
            api.get_referral(
                rows["referral"]["id"],
                make_referral_partner_headers(rows["partner_a"]["id"]),
            )
        )
        assert owner_view["id"] == rows["referral"]["id"]
        assert owner_view["referral_partner_id"] == rows["partner_a"]["id"]

        operator_view = validate_success(
            api.get_referral(rows["referral"]["id"], make_intake_specialist_headers())
        )
        assert operator_view["id"] == rows["referral"]["id"]

    def test_a_partner_may_not_submit_under_another_partners_identity(self, api):
        """Submission is ownership-scoped on the body's partner id.

        "Submission is the one operation a `ReferralPartner` performs, and it is
        ownership-scoped: the `referral_partner_id` in the body must equal the
        acting `X-User-ID`."

        Design: Corner/validations/referral_partner_reading_another_partners_referral_is_forbidden
        """
        rows = self._two_partners_and_one_referral(api)

        response = api.create_referral(
            factories.referral_payload(
                rows["partner_a"]["id"], candidate_reference="CAND-402"
            ),
            make_referral_partner_headers(rows["partner_b"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)


class TestSubsidyPeriodOverlap:
    """Accounting periods are closed on both ends, so they may not share a day."""

    def test_a_period_may_not_start_on_the_previous_period_end(self, api):
        """The shared boundary day is an intersection.

        "Periods of the same business line may never intersect, whatever their
        status: a new period is rejected when its `period_start` is at or before
        an existing period's `period_end` and that existing period's
        `period_start` is at or before the new period's `period_end`."

        Design: Corner/validations/subsidy_period_overlap_rejected_on_closed_interval_boundary
        """
        fixtures.set_clock(api, CLOCK_SEP_07)
        line = fixtures.create_launched_business_line(api)
        fixtures.create_open_subsidy_period(api, line["id"])

        response = api.create_subsidy_period(
            factories.subsidy_period_payload(
                line["id"],
                period_start=SEPTEMBER_PERIOD_END,
                period_end="2026-10-31T00:00:00Z",
            ),
            make_program_director_headers(),
        )

        validate_error(response, ApiErrorId.ERR_SUBSIDY_PERIOD_OVERLAP, 409)

        _rows, meta = validate_paginated(
            api.list_subsidy_periods(
                make_program_director_headers(), {"business_line_id": line["id"]}
            )
        )
        assert meta["total_count"] == 1

    def test_a_period_starting_the_next_day_is_accepted_and_empty(self, api):
        """Abutting periods must begin at least one day later.

        "Abutting periods must therefore begin at least one day after the previous
        period's `period_end`."

        Design: Corner/validations/subsidy_period_overlap_rejected_on_closed_interval_boundary
        """
        fixtures.set_clock(api, CLOCK_SEP_07)
        line = fixtures.create_launched_business_line(api)
        fixtures.create_open_subsidy_period(api, line["id"])

        response = api.create_subsidy_period(
            factories.subsidy_period_payload(
                line["id"],
                period_start="2026-10-01T00:00:00Z",
                period_end="2026-10-31T00:00:00Z",
            ),
            make_program_director_headers(),
        )
        period = validate_success(response, 201)

        assert period["status"] == SubsidyPeriodStatus.OPEN
        assert period["allocation_basis"] == AllocationBasis.HOURS
        assert period["revenue_cents"] is None
        assert_period_ledger(period, 0, 0, 0)
        assert_ratio(period["mission_share"], 0.0000, "mission_share")
        assert period["true_cost_per_trainee_hour_cents"] is None
        assert period["subsidy_per_trainee_hour_cents"] is None

        _rows, meta = validate_paginated(
            api.list_subsidy_periods(
                make_program_director_headers(), {"business_line_id": line["id"]}
            )
        )
        assert meta["total_count"] == 2


class TestCandidateReferenceUniqueness:
    """A candidate handle is unique inside one partner's own book."""

    def _partner_holding_one_candidate(self, api):
        fixtures.set_clock(api, CLOCK_SEP_07)
        partner = fixtures.create_referral_partner(api)
        referral = fixtures.submit_referral(
            api,
            partner["id"],
            candidate_reference="CAND-501",
            declared_barrier_codes=["JUSTICE_INVOLVED"],
        )
        return {"partner": partner, "referral": referral}

    def test_a_repeated_candidate_reference_is_refused_and_writes_nothing(self, api):
        """The stored row keeps the figures it was submitted with.

        "Alongside it the partner supplies `candidate_reference`, its own handle
        for the candidate (1 to 64 characters), which must be unique for that
        partner — a repeat is refused with `ERR_DUPLICATE_CANDIDATE_REFERENCE`."

        Design: Corner/validations/duplicate_candidate_reference_rejected_per_partner
        """
        rows = self._partner_holding_one_candidate(api)

        response = api.create_referral(
            factories.referral_payload(
                rows["partner"]["id"],
                candidate_reference="CAND-501",
                declared_barrier_codes=["HOUSING_INSTABILITY"],
                household_income_cents=150000,
                household_size=3,
                hours_available_per_week=30,
            ),
            make_referral_partner_headers(rows["partner"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_CANDIDATE_REFERENCE, 409)

        stored = fixtures.read_referral(api, rows["referral"]["id"])
        assert stored["household_income_cents"] == 100000

    def test_a_fresh_reference_is_accepted_unscored(self, api):
        """Scoring waits for screening, and the rate is a real zero.

        "A new referral lands in `SUBMITTED` `status` with `verified_barrier_codes`
        an empty list and `fpl_ratio`, `eligibility_score`, `priority_band`,
        `screened_at` and `decided_by_user_id` all null."

        Design: Corner/validations/duplicate_candidate_reference_rejected_per_partner
        """
        rows = self._partner_holding_one_candidate(api)

        response = api.create_referral(
            factories.referral_payload(
                rows["partner"]["id"],
                candidate_reference="CAND-502",
                declared_barrier_codes=["HOUSING_INSTABILITY"],
                household_income_cents=150000,
                household_size=3,
                hours_available_per_week=30,
            ),
            make_referral_partner_headers(rows["partner"]["id"]),
        )
        referral = validate_success(response, 201)

        assert referral["status"] == ReferralStatus.SUBMITTED
        assert referral["eligibility_score"] is None

        partner = fixtures.read_referral_partner(api, rows["partner"]["id"])
        assert partner["referrals_submitted_count"] == 2
        assert_ratio(partner["conversion_rate"], 0.0000, "conversion_rate")


class TestOpenSeatsBlockThePeriodClose:
    """An unresolved seat means an unknown labour cost, so the period stays open."""

    def _period_with_one_unresolved_seat(self, api):
        """A September shift still holding an ASSIGNED seat, with October begun."""
        program = fixtures.enrolled_participant_program(api)
        shift = fixtures.create_work_shift(
            api,
            program["business_line"]["id"],
            "2026-09-07T08:00:00Z",
            "2026-09-07T20:00:00Z",
        )
        program["work_shift"] = shift
        program["assignment"] = fixtures.seat_participant(
            api, shift["id"], program["participant"]["id"]
        )
        fixtures.set_clock(api, CLOCK_OCT_01)
        return program

    def test_an_assigned_seat_refuses_the_close(self, api):
        """The aggregate is checked across the shifts starting inside the period.

        "Four preconditions apply: the period must be `OPEN`; the logical clock
        must be strictly after `period_end`, with an earlier attempt refused as
        `ERR_PERIOD_NOT_ENDED`; `revenue_cents` must be present; and no assignment
        in `ASSIGNED` status may remain on a shift of this line whose `starts_at`
        falls inside the period interval, since an unresolved seat means an unknown
        labour cost — that failure reports `ERR_OPEN_ASSIGNMENTS_BLOCK_CLOSE`."

        Design: Corner/validations/open_assignment_blocks_period_close_until_released
        """
        program = self._period_with_one_unresolved_seat(api)

        response = api.close_subsidy_period(
            program["subsidy_period"]["id"],
            factories.period_close_payload(AllocationBasis.HOURS, 500000),
            make_program_director_headers(),
        )

        validate_error(response, ApiErrorId.ERR_OPEN_ASSIGNMENTS_BLOCK_CLOSE, 409)

        period = fixtures.read_subsidy_period(api, program["subsidy_period"]["id"])
        assert period["status"] == SubsidyPeriodStatus.OPEN

    def test_releasing_the_seat_unblocks_an_empty_close(self, api):
        """A period that never billed an hour still closes on its revenue.

        "Both are `null` when `trainee_hours` is zero — never 0, and never an
        error."

        Design: Corner/validations/open_assignment_blocks_period_close_until_released
        """
        program = self._period_with_one_unresolved_seat(api)

        released = fixtures.release_assignment(api, program["assignment"]["id"])
        assert released["status"] == ShiftAssignmentStatus.RELEASED
        assert released["released_reason"] == ReleasedReason.MANUAL_RELEASE
        shift = fixtures.read_work_shift(api, program["work_shift"]["id"])
        assert shift["assigned_count"] == 0

        closed = validate_success(
            api.close_subsidy_period(
                program["subsidy_period"]["id"],
                factories.period_close_payload(AllocationBasis.HOURS, 500000),
                make_program_director_headers(),
            )
        )

        assert closed["status"] == SubsidyPeriodStatus.CLOSED
        assert closed["revenue_cents"] == 500000
        assert_hours(closed["trainee_hours"], 0.000, "trainee_hours")
        assert_ratio(closed["mission_share"], 0.0000, "mission_share")
        assert_period_ledger(closed, 0, 0, 0)
        assert closed["true_cost_per_trainee_hour_cents"] is None
        assert closed["subsidy_per_trainee_hour_cents"] is None
        assert_ratio(closed["margin_pct"], 1.0000, "margin_pct")
        assert closed["subsidy_draw_cents"] == 0


class TestRolePrecedesExistence:
    """Rung two answers before rung three ever looks for the row."""

    def test_an_unpermitted_role_never_learns_the_row_is_missing(self, api):
        """Role authorization is decided before existence.

        "**Role authorization.** The acting role appears in the endpoint's
        authorized-role list — otherwise `ERR_ROLE_NOT_PERMITTED` (403). Applies
        to every endpoint."

        Design: Corner/validations/unpermitted_role_on_unknown_business_line_returns_forbidden
        """
        fixtures.set_clock(api, CLOCK_SEP_07)

        response = api.launch_business_line(
            UNKNOWN_UUID_1, make_funder_analyst_headers()
        )

        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, 403)

    def test_the_permitted_role_gets_the_not_found_verdict(self, api):
        """With the role cleared, the missing row decides the answer.

        "**Existence.** Every identifier the request references must resolve to a
        row."

        "The failure carries the code for the missing type:
        `ERR_BUSINESS_LINE_NOT_FOUND`, `ERR_REFERRAL_PARTNER_NOT_FOUND`,
        `ERR_REFERRAL_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`,
        `ERR_WORK_SHIFT_NOT_FOUND`, `ERR_SHIFT_ASSIGNMENT_NOT_FOUND`,
        `ERR_SUPPORT_ACTIVITY_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`,
        `ERR_PLACEMENT_NOT_FOUND`, `ERR_RETENTION_CHECKPOINT_NOT_FOUND`,
        `ERR_SUBSIDY_PERIOD_NOT_FOUND`, or `ERR_COST_ENTRY_NOT_FOUND`, each with
        HTTP 404."

        Design: Corner/validations/unpermitted_role_on_unknown_business_line_returns_forbidden
        """
        fixtures.set_clock(api, CLOCK_SEP_07)

        response = api.launch_business_line(
            UNKNOWN_UUID_1, make_program_director_headers()
        )

        validate_error(response, ApiErrorId.ERR_BUSINESS_LINE_NOT_FOUND, 404)

        assert fixtures.participant_count(api) == 0
        _rows, meta = validate_paginated(
            api.list_subsidy_periods(make_program_director_headers())
        )
        assert meta["total_count"] == 0
