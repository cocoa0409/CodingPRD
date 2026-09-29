"""Opening engagements, their phases, and the two forward lifecycle gates."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    assert_engagement,
    assert_hours,
    assert_pct,
    create_assignment,
    create_client,
    create_engagement,
    create_engagement_payload,
    create_engagement_phase_payload,
    create_partner,
    create_phase,
    create_senior,
    create_staff_member_payload,
    read_engagement,
    read_phase,
    schedule_engagement,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestEngagementCreation:
    """The opening state of an engagement and the shape of the request."""

    def test_new_engagement_reports_setup_and_zeroed_counters(
        self, api, admin_headers, partner_headers_for
    ):
        """A freshly opened engagement carries no history at all.

        PRD 3.2: "A newly created engagement is `SETUP`. Its `client_block_count`
        and `scope_change_count` both start at 0, `staffing_completion_pct` starts
        at 0.00, both `realization_pct_provisional` and `realization_pct_final`
        start at 0.00, `pre_block_status` is null, and `schedule_risk_band` is
        computed straight away."

        PRD 3.2: "otherwise the band is `LOW`"

        PRD 2.7: "`version` — an integer that increments by one on every mutation
        of the row."

        Design: Corner/entities/engagement_retrieval_returns_initial_status_and_derived_bands
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        engagement = create_engagement(api, client["id"], partner["id"])

        read_back = validate_success(
            api.get_engagement(engagement["id"], partner_headers_for(partner["id"]))
        )

        assert_engagement(read_back)
        assert read_back["status"] == "SETUP"
        assert read_back["pre_block_status"] is None
        assert read_back["client_block_count"] == 0
        assert read_back["scope_change_count"] == 0
        assert_pct(read_back["staffing_completion_pct"], 0.00)
        assert read_back["schedule_risk_band"] == "LOW"
        assert_pct(read_back["realization_pct_provisional"], 0.00)
        assert_pct(read_back["realization_pct_final"], 0.00)
        assert read_back["version"] == 1

    def test_omitted_budget_fee_amount_is_rejected(
        self, api, admin_headers, manager_headers
    ):
        """The agreed fee is required, and its absence writes nothing.

        PRD 3.2: "A `SchedulingManager` opens an **Engagement** by naming the
        `client_id` it serves, the `engagement_partner_staff_id` who signs it, a
        `service_line` of `AUDIT`, `TAX` or `ADVISORY`, the `busy_season_year` it
        belongs to (an integer from 2020 through 2035), the `deadline_date` by
        which it must be delivered, and the `budget_fee_amount` agreed with the
        client, which must be strictly greater than zero."

        PRD 2.9: "Request shape: every required field present, every type
        correct, every enumerated value a declared member, and every numeric
        field inside its declared range — including a phase's `expected_hours`
        strictly greater than zero and a booking's `allocated_hours` strictly
        greater than zero — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/engagement_create_missing_required_budget_fee_amount_rejected
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)

        payload = create_engagement_payload(
            client["id"],
            partner["id"],
            service_line="AUDIT",
            busy_season_year=2026,
            deadline_date="2026-10-15",
            budget_fee_amount=None,
        )
        assert "budget_fee_amount" not in payload

        validate_error(
            api.create_engagement(payload, manager_headers),
            ApiErrorId.INVALID_REQUEST.value,
            422,
        )

        client_after = validate_success(api.get_client(client["id"], admin_headers))
        assert client_after["engagement_count"] == 0

    def test_engagement_partner_must_be_a_domestic_partner(
        self, api, admin_headers, manager_headers
    ):
        """Neither a senior nor an offshore partner may sign an engagement.

        PRD 3.2: "The nominated partner must be a staff member whose `level` is
        `PARTNER` and whose `service_center` is `DOMESTIC`; anyone else is refused
        with `ERR_PARTNER_LEVEL_REQUIRED`."

        Design: Corner/validations/engagement_partner_must_be_a_domestic_partner
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        senior = create_senior(api)
        offshore_partner = validate_success(
            api.create_staff_member(
                create_staff_member_payload(
                    full_name="Tomas Reyes",
                    level="PARTNER",
                    service_center="OFFSHORE",
                    industry_specialization="MANUFACTURING",
                    cpa_licensed=False,
                    base_weekly_cap_hours=45.00,
                    hourly_bill_rate=300.00,
                ),
                admin_headers,
            ),
            201,
        )
        domestic_partner = create_partner(api)

        for candidate in (senior, offshore_partner):
            validate_error(
                api.create_engagement(
                    create_engagement_payload(
                        client["id"],
                        candidate["id"],
                        service_line="AUDIT",
                        busy_season_year=2026,
                        deadline_date="2026-10-15",
                        budget_fee_amount=6000.00,
                    ),
                    manager_headers,
                ),
                ApiErrorId.PARTNER_LEVEL_REQUIRED.value,
                422,
            )

        accepted = validate_success(
            api.create_engagement(
                create_engagement_payload(
                    client["id"],
                    domestic_partner["id"],
                    service_line="AUDIT",
                    busy_season_year=2026,
                    deadline_date="2026-10-15",
                    budget_fee_amount=6000.00,
                ),
                manager_headers,
            ),
            201,
        )
        assert accepted["status"] == "SETUP"
        assert_pct(accepted["staffing_completion_pct"], 0.00)

        client_after = validate_success(api.get_client(client["id"], admin_headers))
        assert client_after["engagement_count"] == 1

    def test_same_client_partner_and_year_may_not_repeat(
        self, api, admin_headers, manager_headers
    ):
        """The triple is unique; a different busy season is a different row.

        PRD 3.2: "No two engagements may share the same combination of
        `client_id`, `engagement_partner_staff_id` and `busy_season_year`, and an
        attempt to create one is refused with `ERR_DUPLICATE_ENGAGEMENT_YEAR`."

        Design: Corner/validations/second_engagement_for_same_client_partner_year_rejected
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        create_engagement(api, client["id"], partner["id"])

        validate_error(
            api.create_engagement(
                create_engagement_payload(
                    client["id"],
                    partner["id"],
                    service_line="TAX",
                    busy_season_year=2026,
                    deadline_date="2026-09-15",
                    budget_fee_amount=4000.00,
                ),
                manager_headers,
            ),
            ApiErrorId.DUPLICATE_ENGAGEMENT_YEAR.value,
            409,
        )

        next_year = validate_success(
            api.create_engagement(
                create_engagement_payload(
                    client["id"],
                    partner["id"],
                    service_line="TAX",
                    busy_season_year=2027,
                    deadline_date="2027-09-15",
                    budget_fee_amount=4000.00,
                ),
                manager_headers,
            ),
            201,
        )
        assert next_year["busy_season_year"] == 2027
        assert next_year["status"] == "SETUP"

        client_after = validate_success(api.get_client(client["id"], admin_headers))
        assert client_after["engagement_count"] == 2


class TestPartnerRotation:
    """The consecutive-years run walked backwards at engagement creation."""

    def test_sixth_consecutive_year_for_a_public_interest_client_is_refused(
        self, api, admin_headers, manager_headers
    ):
        """Five unbroken prior years plus the request is six, over the limit of five.

        PRD 3.2: "If that number is strictly greater than the client's
        `partner_rotation_limit_years` — 5 for a public-interest entity, 7
        otherwise — the request is refused with `ERR_PARTNER_ROTATION_LIMIT`."

        PRD 3.1: "That flag has one immediate effect: the server sets the derived
        `partner_rotation_limit_years` to 5 when `public_interest_entity` is true
        and to 7 otherwise."

        Design: Corner/calculations/pie_rotation_limit_rejects_sixth_consecutive_year
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(
            api,
            name="Aurora Federal Bancorp",
            industry_code="FINANCIAL_SERVICES",
            public_interest_entity=True,
        )
        partner = create_partner(api, industry_specialization="FINANCIAL_SERVICES")

        for year in (2021, 2022, 2023, 2024, 2025):
            create_engagement(
                api,
                client["id"],
                partner["id"],
                busy_season_year=year,
                deadline_date="%d-10-15" % year,
            )

        validate_error(
            api.create_engagement(
                create_engagement_payload(
                    client["id"],
                    partner["id"],
                    service_line="AUDIT",
                    busy_season_year=2026,
                    deadline_date="2026-10-15",
                    budget_fee_amount=6000.00,
                ),
                manager_headers,
            ),
            ApiErrorId.PARTNER_ROTATION_LIMIT.value,
            409,
        )

        client_after = validate_success(api.get_client(client["id"], admin_headers))
        assert client_after["engagement_count"] == 5
        assert client_after["partner_rotation_limit_years"] == 5

    def test_gap_year_resets_the_rotation_run(self, api, admin_headers):
        """2020 through 2024 with 2025 missing leaves a run of nothing.

        PRD 3.2: "The server walks backwards from the year immediately before the
        requested `busy_season_year`, looking for an engagement with the same
        `client_id` and the same `engagement_partner_staff_id` in that year; each
        year it finds adds one to the run and it steps back another year, stopping
        at the first year with no such engagement."

        PRD 3.2: "Only an unbroken backwards run counts: a single missing year
        resets the run to nothing, which is precisely the effect a cooling-off
        period is supposed to have."

        Design: Corner/calculations/rotation_run_resets_after_a_gap_year
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(
            api,
            name="Aurora Federal Bancorp",
            industry_code="FINANCIAL_SERVICES",
            public_interest_entity=True,
        )
        partner = create_partner(api, industry_specialization="FINANCIAL_SERVICES")

        for year in (2020, 2021, 2022, 2023, 2024):
            create_engagement(
                api,
                client["id"],
                partner["id"],
                busy_season_year=year,
                deadline_date="%d-10-15" % year,
            )

        accepted = create_engagement(
            api,
            client["id"],
            partner["id"],
            busy_season_year=2026,
            deadline_date="2026-10-15",
        )
        assert accepted["busy_season_year"] == 2026
        assert accepted["status"] == "SETUP"

        client_after = validate_success(api.get_client(client["id"], admin_headers))
        assert client_after["engagement_count"] == 6


class TestPhaseCreation:
    """The phase window against the engagement deadline."""

    def test_phase_window_may_not_extend_past_the_deadline(self, api, manager_headers):
        """One day past the deadline is refused; landing on it is accepted.

        PRD 3.2: "A phase window may never extend past its engagement's
        `deadline_date`; a `window_end_date` later than the deadline is refused
        with `ERR_PHASE_WINDOW_AFTER_DEADLINE`."

        PRD 3.2: "A new phase begins at `NOT_STAFFED` with `staffed_hours` 0.00
        and `unstaffed_hours` equal to its `expected_hours`; creating it refreshes
        the engagement's `staffing_completion_pct` and `schedule_risk_band` and
        increments the engagement's `version`."

        Design: Corner/validations/phase_window_ending_after_deadline_rejected
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        engagement = create_engagement(api, client["id"], partner["id"])
        assert engagement["deadline_date"] == "2026-10-15"

        validate_error(
            api.create_engagement_phase(
                create_engagement_phase_payload(
                    engagement["id"],
                    phase_type="FIELDWORK",
                    expected_hours=20.00,
                    window_start_date="2026-08-03",
                    window_end_date="2026-10-16",
                ),
                manager_headers,
            ),
            ApiErrorId.PHASE_WINDOW_AFTER_DEADLINE.value,
            422,
        )

        accepted = validate_success(
            api.create_engagement_phase(
                create_engagement_phase_payload(
                    engagement["id"],
                    phase_type="FIELDWORK",
                    expected_hours=20.00,
                    window_start_date="2026-08-03",
                    window_end_date="2026-10-15",
                ),
                manager_headers,
            ),
            201,
        )
        assert accepted["window_end_date"] == "2026-10-15"
        assert accepted["staffing_status"] == "NOT_STAFFED"
        assert_hours(accepted["staffed_hours"], 0.00)
        assert_hours(accepted["unstaffed_hours"], 20.00)


class TestForwardLifecycleGates:
    """Reaching SCHEDULED and then IN_FIELDWORK."""

    def test_schedule_blocked_while_a_phase_is_still_unstaffed(
        self, api, manager_headers
    ):
        """One untouched phase is enough to hold the whole engagement back.

        PRD 3.2: "A `SchedulingManager` moves an engagement from `SETUP` to
        `SCHEDULED` once it has at least one phase and *every* phase of the
        engagement sits at `PARTIALLY_STAFFED` or `FULLY_STAFFED`. A single phase
        still at `NOT_STAFFED`, `IN_PROGRESS` or `COMPLETE` blocks the move."

        PRD 2.10: "State-transition rejections are similarly split by target row,
        all of them HTTP 409"

        PRD 2.10 names both members of the invalid-state family that a blocked
        `schedule` could legitimately report — `ERR_ENGAGEMENT_INVALID_STATE`
        because the engagement cannot make the requested move, and
        `ERR_PHASE_INVALID_STATE` because the row whose state blocks it is a
        phase — but no PRD sentence assigns one of them to this operation, so
        either is accepted.

        Design: Corner/state_machines/schedule_rejected_while_one_phase_is_still_not_staffed
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        senior = create_senior(api)
        engagement = create_engagement(api, client["id"], partner["id"])
        fieldwork = create_phase(
            api,
            engagement["id"],
            phase_type="FIELDWORK",
            expected_hours=20.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
        )
        planning = create_phase(
            api,
            engagement["id"],
            phase_type="PLANNING",
            expected_hours=10.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
            required_level="SENIOR",
            required_industry_specialization=None,
            requires_cpa_licensed=None,
        )
        create_assignment(
            api,
            fieldwork["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=20.00,
        )

        blocked = api.schedule_engagement(engagement["id"], manager_headers)
        assert blocked.status_code == 409
        validate_error_is_one_of(
            blocked,
            [
                ApiErrorId.PHASE_INVALID_STATE.value,
                ApiErrorId.ENGAGEMENT_INVALID_STATE.value,
            ],
        )

        planning_after = read_phase(api, planning["id"])
        assert planning_after["staffing_status"] == "NOT_STAFFED"
        assert_hours(planning_after["staffed_hours"], 0.00)
        assert_hours(planning_after["unstaffed_hours"], 10.00)

        assert read_engagement(api, engagement["id"])["status"] == "SETUP"

    def test_start_fieldwork_blocked_below_half_staffed(self, api, manager_headers):
        """Twenty of forty-five hours is 44.44 percent, short of the fifty needed.

        PRD 3.2: "From `SCHEDULED`, the manager starts fieldwork, advancing the
        engagement `SCHEDULED → IN_FIELDWORK`, provided `staffing_completion_pct`
        is at least 50.00."

        PRD 2.10: "`ERR_ENGAGEMENT_INVALID_STATE` when an engagement is not in a
        state its requested transition allows (including `DELIVERED` terminal
        lockdown)"

        Design: Corner/state_machines/start_fieldwork_rejected_below_fifty_percent_staffing_completion
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        senior = create_senior(api)
        engagement = create_engagement(api, client["id"], partner["id"])
        phase = create_phase(
            api,
            engagement["id"],
            expected_hours=45.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
        )
        create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=20.00,
        )
        schedule_engagement(api, engagement["id"])

        validate_error(
            api.start_fieldwork(engagement["id"], manager_headers),
            ApiErrorId.ENGAGEMENT_INVALID_STATE.value,
            409,
        )

        after = read_engagement(api, engagement["id"])
        assert after["status"] == "SCHEDULED"
        assert_pct(after["staffing_completion_pct"], 44.44)
