"""The entity contract: seeded computed fields, declared defaults, ignored input and identity."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    ApiErrorId,
    assert_fields_equal,
    assert_light_resource,
    assert_pagination_meta,
    assert_posture,
    assert_timestamp_format,
    create_conference,
    create_revenue_pool,
    create_schedule_game,
    is_valid_uuid,
    make_auditor_headers,
    make_championship_event_payload,
    make_commissioner_headers,
    make_finance_officer_headers,
    make_member_payload,
    make_member_representative_headers,
    make_platform_admin_headers,
    make_protected_rivalry_payload,
    make_revenue_pool_payload,
    make_schedule_coordinator_headers,
    make_schedule_game_payload,
    make_venue_payload,
    read_conference,
    read_run_lines,
    set_logical_clock,
    setup_charter_roster,
    setup_computed_fy2026_final_run,
    setup_conference_and_venues,
    setup_operating_conference_with_reserve,
    validate_error,
    validate_paginated,
    validate_success,
)


def _members(api, params=None):
    return validate_paginated(api.list_members(params=params, headers=make_auditor_headers()))


def _member_total(api):
    return _members(api)[1]["total_count"]


def _list_total(api, response):
    return validate_paginated(response)[1]["total_count"]


def test_conference_initialisation_seeds_every_system_maintained_figure(api):
    """PRD §2.4: "The conference record itself carries the office's `name`, the
    `fiscal_year_start_month` in which its fiscal year opens (a calendar month from 1 through
    12, defaulting to 7), the `current_fiscal_year` it is operating in (defaulting to 2027),
    the cash `unit_value_cents` of one validated postseason unit (defaulting to 34,000,000
    cents, that is 340,000 dollars), and `phase_schedule_years`, the number of phasing years a
    petitioning institution serves before reaching full share (at least 1, defaulting to 3)."
    PRD §2.4: "Its `governance_status` is `FORMING` while charter membership is still being
    seated and `OPERATING` once the first budget proposal has been approved; those are the only
    two values it takes, and it starts at `FORMING`."
    PRD §2.4: "Eight further conference-level figures are maintained by the system rather than
    supplied: `approved_operating_expense_cents` and `approved_governance_expense_cents` (both
    starting at 0), `reserve_target_cents` and `reserve_balance_cents` (both starting at 0),
    `reserve_posture` (starting at `OPEN`), `funded_ratio_bps` (starting at 10000),
    `escrow_balance_cents` (starting at 0), `governance_fee_revenue_cents` (starting at 0), and
    `validated_postseason_unit_count` (starting at 0)."
    PRD §2.4: "A freshly initialised conference is at `version` 1."

    Design: Corner/entities/corner_conference_create_initializes_computed_fields
    """
    set_logical_clock(api)

    conference = create_conference(api)

    assert_fields_equal(
        conference,
        name=TEST_DEFAULTS["CONFERENCE_NAME"],
        fiscal_year_start_month=7,
        current_fiscal_year=2027,
        unit_value_cents=34_000_000,
        phase_schedule_years=3,
        governance_status="FORMING",
        approved_operating_expense_cents=0,
        approved_governance_expense_cents=0,
        reserve_target_cents=0,
        reserve_balance_cents=0,
        escrow_balance_cents=0,
        governance_fee_revenue_cents=0,
        validated_postseason_unit_count=0,
        version=1,
    )
    assert_posture(conference, "OPEN", 10000)
    assert read_conference(api)["id"] == conference["id"]


def test_charter_member_read_back_returns_the_stored_representation(api):
    """PRD §3.1: "`CHARTER` seats the institution immediately at full share: the member is
    created in status `FULL_SHARE` with `distribution_phase_bps` of 10000, `voting_weight_bps`
    of 10000, `phase_year` of 4 and `entry_fee_cents` of 0."
    PRD §3.1: "The roster can be read whole or filtered — by `conference_id`, by
    `home_venue_id`, by `travel_partner_member_id`, or by `status` — and each member's record
    also exposes the computed values other subsections describe: `withdrawal_notice_at`,
    `withdrawal_effective_fiscal_year`, `notice_days`, `last_full_annual_distribution_cents`,
    `exit_settlement_total_cents`, `exit_settlement_paid_cents` and
    `schedule_compliance_score`."
    PRD §3.4: "The compliance score itself is the conference's measure of whether a member is
    scheduling in good faith, and it starts at 100 for a brand-new member."
    PRD §3.8: "Step three computes `base_assessment_cents` as the member's
    `last_full_annual_distribution_cents` multiplied by `notice_multiplier_bps` and divided by
    10000, rounded up; a member that has never appeared on a posted final audited media-rights
    run has a `last_full_annual_distribution_cents` of 0 and therefore a base assessment of 0."
    PRD §3.8: "Rescission returns the member's `status` to `FULL_SHARE`, restores its
    `voting_weight_bps` to 10000, clears `withdrawal_notice_at`, `notice_days` and
    `withdrawal_effective_fiscal_year` back to null, zeroes `notice_multiplier_bps`,
    `base_assessment_cents`, `surcharge_bracket_bps`, `exit_settlement_total_cents` and
    `exit_settlement_paid_cents`, restores the `ROLLING_SIX_YEAR` valuation variant so the
    member's whole six-year unit history counts again, and advances the member's `version`
    by 1."

    Design: Corner/entities/corner_member_retrieval_returns_stored_representation
    """
    ctx = setup_charter_roster(api, member_keys=("north",))
    member_id = ctx["member_ids"]["north"]

    # Read back through the member's own representative rather than the seating role.
    member = validate_success(
        api.get_member(member_id, headers=make_member_representative_headers(member_id))
    )

    assert_fields_equal(
        member,
        id=member_id,
        conference_id=ctx["conference_id"],
        name="North State University",
        institution_code="NOR",
        admission_path="CHARTER",
        home_venue_id=ctx["venue_north"]["id"],
        grant_of_rights_through_fiscal_year=2032,
        status="FULL_SHARE",
        distribution_phase_bps=10000,
        voting_weight_bps=10000,
        phase_year=4,
        entry_fee_cents=0,
        entry_fee_paid_cents=0,
        schedule_compliance_score=100,
        last_full_annual_distribution_cents=0,
        exit_settlement_total_cents=0,
        exit_settlement_paid_cents=0,
        withdrawal_notice_at=None,
        withdrawal_effective_fiscal_year=None,
        notice_days=None,
        version=1,
    )


def test_member_listing_pages_the_roster_and_reports_total_count(api):
    """PRD §2.3: "When `limit` is omitted it defaults to 10; the smallest accepted value is 1
    and the largest is 100."
    PRD §2.3: "Unless a specific endpoint states another ordering, list results are sorted by
    `created_at` ascending, so the oldest record appears first and pagination over an unchanging
    data set is stable."
    PRD §2.3: "For every list response, the `meta` object carries `limit` and `offset` as they
    were applied, `total_count` as the number of records matching the filters before the window
    was applied, and `has_more` as a boolean that is true when records remain beyond the current
    window."
    PRD §2.3: "All other filters offered by a list endpoint are additive: supplying several
    narrows the result to records matching all of them."
    PRD §3.1: "The roster can be read whole or filtered — by `conference_id`, by
    `home_venue_id`, by `travel_partner_member_id`, or by `status` — and each member's record
    also exposes the computed values other subsections describe: `withdrawal_notice_at`,
    `withdrawal_effective_fiscal_year`, `notice_days`, `last_full_annual_distribution_cents`,
    `exit_settlement_total_cents`, `exit_settlement_paid_cents` and
    `schedule_compliance_score`."

    Design: Corner/entities/corner_members_listing_paginates_with_total_count_and_has_more
    """
    ctx = setup_charter_roster(api)

    first_page, first_meta = _members(api, {"limit": 2, "offset": 0})
    second_page, second_meta = _members(api, {"limit": 2, "offset": 2})
    whole, whole_meta = _members(api)
    at_east, east_meta = _members(api, {"home_venue_id": ctx["venue_east"]["id"]})

    assert_pagination_meta(first_meta, limit=2, offset=0, total_count=4, has_more=True)
    assert_pagination_meta(second_meta, limit=2, offset=2, total_count=4, has_more=False)
    assert [row["institution_code"] for row in first_page] == ["NOR", "SOU"]
    assert [row["institution_code"] for row in second_page] == ["EAS", "WES"]
    # The omitted limit falls back to 10, which is wide enough for the whole roster.
    assert_pagination_meta(whole_meta, limit=10, offset=0, total_count=4, has_more=False)
    assert [row["institution_code"] for row in whole] == ["NOR", "SOU", "EAS", "WES"]
    assert east_meta["total_count"] == 2
    for row in at_east:
        assert row["home_venue_id"] == ctx["venue_east"]["id"]


def test_reads_with_an_unknown_path_id_report_the_entity_specific_not_found(api):
    """PRD §2.8: "Identifiers embedded in a URL are resolved left to right, and the first one
    that does not resolve produces its own 404 code: `ERR_VENUE_NOT_FOUND`,
    `ERR_MEMBER_NOT_FOUND`, `ERR_REVENUE_POOL_NOT_FOUND`, `ERR_DISTRIBUTION_RUN_NOT_FOUND`,
    `ERR_BOWL_APPEARANCE_NOT_FOUND`, `ERR_MEMBERSHIP_ACTION_NOT_FOUND`,
    `ERR_BUDGET_PROPOSAL_NOT_FOUND`, `ERR_PROTECTED_RIVALRY_NOT_FOUND`,
    `ERR_SCHEDULE_GAME_NOT_FOUND`, `ERR_CHAMPIONSHIP_EVENT_NOT_FOUND` or
    `ERR_AUDIT_REPORT_NOT_FOUND`."

    Design: Corner/entities/corner_reads_with_unknown_path_id_return_entity_specific_not_found
    """
    setup_conference_and_venues(api)
    headers = make_auditor_headers()

    attempts = (
        (api.get_member(NON_EXISTENT_UUID, headers=headers), ApiErrorId.ERR_MEMBER_NOT_FOUND),
        (
            api.get_revenue_pool(NON_EXISTENT_UUID, headers=headers),
            ApiErrorId.ERR_REVENUE_POOL_NOT_FOUND,
        ),
        (
            api.get_distribution_run(NON_EXISTENT_UUID, headers=headers),
            ApiErrorId.ERR_DISTRIBUTION_RUN_NOT_FOUND,
        ),
        (
            api.get_bowl_appearance(NON_EXISTENT_UUID, headers=headers),
            ApiErrorId.ERR_BOWL_APPEARANCE_NOT_FOUND,
        ),
        (
            api.get_membership_action(NON_EXISTENT_UUID, headers=headers),
            ApiErrorId.ERR_MEMBERSHIP_ACTION_NOT_FOUND,
        ),
        (
            api.get_budget_proposal(NON_EXISTENT_UUID, headers=headers),
            ApiErrorId.ERR_BUDGET_PROPOSAL_NOT_FOUND,
        ),
        (
            api.get_protected_rivalry(NON_EXISTENT_UUID, headers=headers),
            ApiErrorId.ERR_PROTECTED_RIVALRY_NOT_FOUND,
        ),
        (
            api.get_schedule_game(NON_EXISTENT_UUID, headers=headers),
            ApiErrorId.ERR_SCHEDULE_GAME_NOT_FOUND,
        ),
        (
            api.get_championship_event(NON_EXISTENT_UUID, headers=headers),
            ApiErrorId.ERR_CHAMPIONSHIP_EVENT_NOT_FOUND,
        ),
        (
            api.get_audit_report(NON_EXISTENT_UUID, headers=headers),
            ApiErrorId.ERR_AUDIT_REPORT_NOT_FOUND,
        ),
    )

    for response, expected in attempts:
        validate_error(response, expected.value, 404)


def test_body_foreign_keys_that_miss_their_target_are_rejected(api):
    """PRD §2.8: "Identifiers carried in a request body are resolved the same way and produce
    the same codes; body-level resolution covers member creation, revenue-pool creation,
    membership-action creation, budget-proposal creation, protected-rivalry creation,
    schedule-game creation, championship-event creation, audit-report creation, both
    ballot-casting operations, and member profile amendment, and the codes it can raise there
    are `ERR_VENUE_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_REVENUE_POOL_NOT_FOUND`,
    `ERR_DISTRIBUTION_RUN_NOT_FOUND` and `ERR_PROTECTED_RIVALRY_NOT_FOUND`."

    Design: Corner/entities/corner_body_foreign_keys_missing_required_target_rejected
    """
    ctx = setup_charter_roster(api)
    pool = create_revenue_pool(api, ctx["conference_id"])
    ids = ctx["member_ids"]

    missing_venue = api.create_member(
        make_member_payload(
            ctx["conference_id"],
            NON_EXISTENT_UUID,
            name="Lakeside College",
            institution_code="LAK",
        ),
        headers=make_commissioner_headers(),
    )
    missing_member = api.create_schedule_game(
        make_schedule_game_payload(
            ctx["conference_id"],
            ids["north"],
            NON_EXISTENT_UUID,
            ctx["venue_north"]["id"],
            "2026-09-05T19:00:00Z",
        ),
        headers=make_schedule_coordinator_headers(),
    )
    missing_pool = api.create_championship_event(
        make_championship_event_payload(
            ctx["conference_id"],
            ctx["venue_north"]["id"],
            ids["north"],
            NON_EXISTENT_UUID,
            "2027-03-05T00:00:00Z",
            "2027-03-08T00:00:00Z",
        ),
        headers=make_commissioner_headers(),
    )
    missing_run = api.create_audit_report(
        {
            "conference_id": ctx["conference_id"],
            "distribution_run_id": NON_EXISTENT_UUID,
            "fiscal_year": 2027,
            "opinion": "UNQUALIFIED",
        },
        headers=make_auditor_headers(),
    )
    missing_rivalry = api.create_schedule_game(
        make_schedule_game_payload(
            ctx["conference_id"],
            ids["north"],
            ids["south"],
            ctx["venue_north"]["id"],
            "2026-09-05T19:00:00Z",
            protected_rivalry_id=NON_EXISTENT_UUID,
        ),
        headers=make_schedule_coordinator_headers(),
    )

    validate_error(missing_venue, ApiErrorId.ERR_VENUE_NOT_FOUND.value, 404)
    validate_error(missing_member, ApiErrorId.ERR_MEMBER_NOT_FOUND.value, 404)
    validate_error(missing_pool, ApiErrorId.ERR_REVENUE_POOL_NOT_FOUND.value, 404)
    validate_error(missing_run, ApiErrorId.ERR_DISTRIBUTION_RUN_NOT_FOUND.value, 404)
    validate_error(missing_rivalry, ApiErrorId.ERR_PROTECTED_RIVALRY_NOT_FOUND.value, 404)
    # None of the five refused creates left a row behind.
    assert _member_total(api) == 4
    assert (
        _list_total(
            api, api.list_schedule_games(headers=make_schedule_coordinator_headers())
        )
        == 0
    )
    assert (
        _list_total(
            api, api.list_championship_events(headers=make_schedule_coordinator_headers())
        )
        == 0
    )
    assert _list_total(api, api.list_audit_reports(headers=make_auditor_headers())) == 0
    assert _list_total(api, api.list_revenue_pools(headers=make_finance_officer_headers())) == 1
    assert pool["status"] == "DRAFT"


def test_member_create_missing_a_required_field_is_rejected(api):
    """PRD §2.8: "Request-shape validation is uniform across the API and raises
    `ERR_INVALID_REQUEST` (HTTP 400): every required field must be present, every enumerated
    value must be one the specification declares, every amount field named in cents and every
    count must be a non-negative integer, and every instant must parse as an ISO 8601 UTC
    timestamp."
    PRD §3.1: "Creating a member institution takes a payload naming the owning conference as
    `conference_id`, the institution's display `name`, its short `institution_code`, its
    `admission_path`, the `home_venue_id` at which it will host, and the
    `grant_of_rights_through_fiscal_year` that bounds its media-rights commitment; three
    further values are optional — an `entry_fee_cents` assessment, a `travel_partner_member_id`,
    and a `primary_contact_email` for the athletics business office."

    Design: Corner/entities/corner_member_create_missing_required_fields_rejected
    """
    ctx = setup_conference_and_venues(api)

    for omitted in (
        "institution_code",
        "admission_path",
        "home_venue_id",
        "grant_of_rights_through_fiscal_year",
    ):
        payload = make_member_payload(ctx["conference_id"], ctx["venue_north"]["id"])
        payload.pop(omitted)

        response = api.create_member(payload, headers=make_commissioner_headers())

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    assert _member_total(api) == 0, "no partial member row survives a shape failure"


def test_optional_inputs_fall_back_to_their_declared_defaults(api):
    """PRD §3.4: "A `ScheduleCoordinator` or `PlatformAdmin` registers one with a `name`, a
    `city`, a `seating_capacity` that must be strictly greater than 0, and a
    `concurrent_event_capacity` that defaults to 1 and must be at least 1 — the latter governs
    how many championship occupancy windows may overlap on that venue at once, and is used in
    §3.5 rather than in ordinary game scheduling."
    PRD §3.4: "Protecting one records the `conference_id`, the two parties as `member_a_id` and
    `member_b_id`, the `required_annual_meetings` the pair must schedule each fiscal year
    (defaulting to 1, minimum 1), and an optional `label` naming the trophy or series."
    PRD §3.4: "A rivalry is created `ACTIVE` and has exactly one other status, `LAPSED`, which
    is terminal."
    PRD §3.4: "Scheduling a game is a `ScheduleCoordinator` action and takes the
    `conference_id`, the `home_member_id`, the `away_member_id`, the `venue_id`, the
    `game_date` kickoff instant, the `fiscal_year` the game counts toward, and optionally
    `media_designated` (defaulting to false, and the flag that decides whether the game counts
    as a media appearance in the distribution weighting) and `protected_rivalry_id` when the
    game is meant to satisfy a protected series."
    PRD §3.4: "A game is created in `SCHEDULED` and immediately triggers a recomputation of
    `schedule_compliance_score` for both participants."
    PRD §3.1: "`CHARTER` seats the institution immediately at full share: the member is created
    in status `FULL_SHARE` with `distribution_phase_bps` of 10000, `voting_weight_bps` of
    10000, `phase_year` of 4 and `entry_fee_cents` of 0."

    Design: Corner/entities/corner_optional_inputs_fall_back_to_declared_defaults
    """
    ctx = setup_charter_roster(api, member_keys=("north", "south"))
    ids = ctx["member_ids"]

    venue_payload = make_venue_payload(
        name="Prairie Fieldhouse", city="Prairie", seating_capacity=8000
    )
    venue_payload.pop("concurrent_event_capacity")
    venue = validate_success(
        api.create_venue(venue_payload, headers=make_platform_admin_headers()), 201
    )
    game_payload = make_schedule_game_payload(
        ctx["conference_id"],
        ids["north"],
        ids["south"],
        ctx["venue_north"]["id"],
        "2026-09-05T19:00:00Z",
    )
    game_payload.pop("media_designated")
    game = validate_success(
        api.create_schedule_game(game_payload, headers=make_schedule_coordinator_headers()),
        201,
    )
    rivalry_payload = make_protected_rivalry_payload(
        ctx["conference_id"], ids["north"], ids["south"], label="Prairie Trophy"
    )
    rivalry_payload.pop("required_annual_meetings")
    rivalry = validate_success(
        api.create_protected_rivalry(
            rivalry_payload, headers=make_schedule_coordinator_headers()
        ),
        201,
    )

    assert_fields_equal(venue, concurrent_event_capacity=1, seating_capacity=8000)
    assert_fields_equal(game, media_designated=False, status="SCHEDULED")
    assert game["media_designated"] is False, "the default is false rather than null"
    assert_fields_equal(rivalry, required_annual_meetings=1, status="ACTIVE")
    # The charter path pins the fee fields without either one being supplied.
    assert_fields_equal(
        ctx["members"]["north"], entry_fee_cents=0, entry_fee_paid_cents=0
    )


def test_revenue_pool_create_ignores_supplied_computed_fields(api):
    """PRD §3.7: "A `FinanceOfficer` creates it with the `conference_id`, the `fiscal_year`
    whose revenue it books, the `pool_type` as one of `MEDIA_RIGHTS`, `POSTSEASON_UNIT` or
    `CHAMPIONSHIP`, the `allocation_method` as one of `APPEARANCE_PERFORMANCE_WEIGHTED`,
    `EQUAL_SHARE` or `UNIT_BASED`, the `gross_revenue_cents` receipts booked into it, and the
    `estimated_expense_cents` pre-audit expense estimate."
    PRD §3.7: "The pool is created in `DRAFT` with `audited_expense_cents` null and
    `version` 1."
    PRD §3.7: "Closing the books on an `OPEN` pool supplies the `audited_expense_cents` and
    sets the pool `BOOKS_CLOSED`, which is the only status from which a final audited run may
    be computed; before that is allowed, every bowl appearance whose `fiscal_year` equals the
    pool's `fiscal_year` must have reached `APPROVED` or `VOIDED`, and a single appearance
    still `SUBMITTED`, `UNDER_REVIEW` or `REVISION_REQUESTED` refuses the operation with
    `ERR_BOWL_REVIEW_PENDING`."

    Design: Corner/entities/corner_revenue_pool_computed_fields_ignored_input
    """
    ctx = setup_charter_roster(api)

    pool = validate_success(
        api.create_revenue_pool(
            make_revenue_pool_payload(
                ctx["conference_id"],
                fiscal_year=2026,
                gross_revenue_cents=600_000_000,
                estimated_expense_cents=4_000_000,
                audited_expense_cents=999,
                status="BOOKS_CLOSED",
            ),
            headers=make_finance_officer_headers(),
        ),
        201,
    )

    # The audited figure has one source only, and it is the close-books transition.
    assert_fields_equal(
        pool,
        status="DRAFT",
        audited_expense_cents=None,
        gross_revenue_cents=600_000_000,
        estimated_expense_cents=4_000_000,
        fiscal_year=2026,
        version=1,
    )


def test_member_create_ignores_client_supplied_identity_fields(api):
    """PRD §2.5: "Every resource is identified by an `id` that the server mints as a UUID, with
    no type prefix and no client control over its value."
    PRD §2.5: "Most resources also carry three housekeeping properties: `created_at`, the ISO
    8601 UTC instant of creation with three fractional digits; `updated_at`, in the same
    format, refreshed on every mutation of that record; and `version`, an integer that starts
    at 1 when the record is created and increases by exactly 1 on each mutation."
    PRD §2.4: "Every server-side reference to "now" — the instant a withdrawal notice is filed,
    the instant a distribution run is posted, resource creation and update timestamps —
    resolves against this logical clock."
    PRD §3.1: "`CHARTER` seats the institution immediately at full share: the member is created
    in status `FULL_SHARE` with `distribution_phase_bps` of 10000, `voting_weight_bps` of
    10000, `phase_year` of 4 and `entry_fee_cents` of 0."

    Design: Corner/entities/corner_system_identity_fields_ignored_input
    """
    ctx = setup_conference_and_venues(api)
    spoofed_id = "11111111-2222-3333-4444-555555555555"

    member = validate_success(
        api.create_member(
            make_member_payload(
                ctx["conference_id"],
                ctx["venue_north"]["id"],
                id=spoofed_id,
                created_at="2020-01-01T00:00:00.000Z",
                version=77,
                status="DEPARTED",
            ),
            headers=make_commissioner_headers(),
        ),
        201,
    )

    assert member["id"] != spoofed_id, "the server mints the identifier itself"
    assert is_valid_uuid(member["id"])
    assert_timestamp_format(member["created_at"])
    assert_timestamp_format(member["updated_at"])
    # Both stamps come from the logical clock, which is still at its default instant.
    assert member["created_at"].startswith("2026-08-01T00:00:00")
    assert member["updated_at"].startswith("2026-08-01T00:00:00")
    assert_fields_equal(member, version=1, status="FULL_SHARE")


def test_undeclared_enum_values_and_ranges_are_rejected(api):
    """PRD §2.8: "Request-shape validation is uniform across the API and raises
    `ERR_INVALID_REQUEST` (HTTP 400): every required field must be present, every enumerated
    value must be one the specification declares, every amount field named in cents and every
    count must be a non-negative integer, and every instant must parse as an ISO 8601 UTC
    timestamp."
    PRD §3.1: "`PETITIONED` is the other path: the institution is created in status
    `PETITIONED` with `distribution_phase_bps` of 0, `voting_weight_bps` of 0, `phase_year` of
    0 and `entry_fee_paid_cents` of 0."
    PRD §3.7: "A `FinanceOfficer` creates it with the `conference_id`, the `fiscal_year` whose
    revenue it books, the `pool_type` as one of `MEDIA_RIGHTS`, `POSTSEASON_UNIT` or
    `CHAMPIONSHIP`, the `allocation_method` as one of `APPEARANCE_PERFORMANCE_WEIGHTED`,
    `EQUAL_SHARE` or `UNIT_BASED`, the `gross_revenue_cents` receipts booked into it, and the
    `estimated_expense_cents` pre-audit expense estimate."
    PRD §3.5: "The window is half-open: it includes its start instant and excludes its end
    instant."
    PRD §3.5: "Next, `window_end` must be strictly after `window_start`; an inverted or
    zero-length window is refused with `ERR_INVALID_EVENT_WINDOW` (HTTP 422)."

    Design: Corner/entities/corner_enum_and_range_constraints_invalid_enum_rejected
    """
    ctx = setup_charter_roster(api)
    pool = create_revenue_pool(api, ctx["conference_id"])

    bad_path = api.create_member(
        make_member_payload(
            ctx["conference_id"],
            ctx["venue_north"]["id"],
            name="Lakeside College",
            institution_code="LAK",
            admission_path="INVITED",
        ),
        headers=make_commissioner_headers(),
    )
    bad_pool_type = api.create_revenue_pool(
        make_revenue_pool_payload(ctx["conference_id"], pool_type="MERCHANDISE"),
        headers=make_finance_officer_headers(),
    )
    inverted_window = api.create_championship_event(
        make_championship_event_payload(
            ctx["conference_id"],
            ctx["venue_east"]["id"],
            ctx["member_ids"]["south"],
            pool["id"],
            "2027-03-08T00:00:00Z",
            "2027-03-05T00:00:00Z",
        ),
        headers=make_commissioner_headers(),
    )
    empty_window = api.create_championship_event(
        make_championship_event_payload(
            ctx["conference_id"],
            ctx["venue_east"]["id"],
            ctx["member_ids"]["south"],
            pool["id"],
            "2027-03-05T00:00:00Z",
            "2027-03-05T00:00:00Z",
        ),
        headers=make_commissioner_headers(),
    )

    validate_error(bad_path, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    validate_error(bad_pool_type, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    validate_error(inverted_window, ApiErrorId.ERR_INVALID_EVENT_WINDOW.value, 422)
    # A zero-length window is refused for the same reason as an inverted one.
    validate_error(empty_window, ApiErrorId.ERR_INVALID_EVENT_WINDOW.value, 422)
    assert _member_total(api) == 4
    assert _list_total(api, api.list_revenue_pools(headers=make_finance_officer_headers())) == 1
    assert (
        _list_total(
            api, api.list_championship_events(headers=make_schedule_coordinator_headers())
        )
        == 0
    )


def test_distribution_lines_and_ballots_carry_no_version_or_updated_at(api):
    """PRD §2.5: "Three resource types are deliberately lighter: a distribution line, a
    postseason unit and a ballot carry only `id` and `created_at`."
    PRD §2.5: "They have neither an `updated_at` nor a `version` field, because they are never
    independently updated — their state changes only as a consequence of a transition on their
    parent, and their status field is the only thing that moves."
    PRD §3.7: "Under `EQUAL_SHARE` the raw weight is the base weight of 10000 basis points for
    everyone."
    PRD §3.2: "On acceptance the ballot is created in status `CAST` with its `weight_bps`
    snapshotted from the member's `voting_weight_bps` at that moment, so later changes to the
    member's weight do not retroactively re-weight a vote already cast."

    Design: Corner/entities/corner_distribution_line_immutability_has_no_version_field
    """
    ctx = setup_operating_conference_with_reserve(api)
    setup_computed_fy2026_final_run(api, ctx)

    lines = read_run_lines(api, ctx["run_2026_id"])
    ballots = validate_success(
        api.list_budget_ballots(
            ctx["budget_proposal"]["id"], headers=make_auditor_headers()
        )
    )

    assert len(lines) == 4
    for line in lines:
        assert_light_resource(line)
        assert_fields_equal(line, status="ACTIVE", weight_bps=10000)
    assert len(ballots) == 4
    for ballot in ballots:
        assert_light_resource(ballot)
        assert_fields_equal(ballot, status="CAST", weight_bps=10000)


def test_cross_aggregate_associations_are_validated_against_the_home_venue(api):
    """PRD §3.4: "Only after the rest buffer passes does the home-venue check run: the supplied
    `venue_id` must be the home member's own `home_venue_id`, and a mismatch is refused with
    `ERR_VENUE_NOT_HOME_VENUE` (HTTP 422)."
    PRD §3.5: "Awarding an event — a `Commissioner` or `ScheduleCoordinator` capability — names
    the `conference_id`, the `venue_id` to be occupied, the `host_member_id` that will host and
    receive the host share, the `revenue_pool_id` that will be credited at settlement, the
    `sport` contested, the `fiscal_year` the event settles into, and the occupancy window as
    `window_start` and `window_end`."
    PRD §3.5: "A successful award creates the event in `SCHEDULED` and snapshots the host's
    score at that moment as `host_compliance_score_at_award`."

    Design: Corner/entities/corner_hybrid_topology_cross_aggregate_association_validated
    """
    ctx = setup_charter_roster(api)
    pool = create_revenue_pool(api, ctx["conference_id"])
    ids = ctx["member_ids"]

    # North hosts at Northfield, so Eastport is not an address it can be scheduled at.
    wrong_venue = api.create_schedule_game(
        make_schedule_game_payload(
            ctx["conference_id"],
            ids["north"],
            ids["east"],
            ctx["venue_east"]["id"],
            "2026-09-05T19:00:00Z",
        ),
        headers=make_schedule_coordinator_headers(),
    )
    validate_error(wrong_venue, ApiErrorId.ERR_VENUE_NOT_HOME_VENUE.value, 422)

    game = create_schedule_game(
        api,
        ctx["conference_id"],
        ids["north"],
        ids["east"],
        ctx["venue_north"]["id"],
        "2026-09-05T19:00:00Z",
    )
    # A championship event is a different association: any venue may be occupied.
    event = validate_success(
        api.create_championship_event(
            make_championship_event_payload(
                ctx["conference_id"],
                ctx["venue_east"]["id"],
                ids["south"],
                pool["id"],
                "2027-03-05T00:00:00Z",
                "2027-03-08T00:00:00Z",
            ),
            headers=make_commissioner_headers(),
        ),
        201,
    )

    assert_fields_equal(game, status="SCHEDULED", venue_id=ctx["venue_north"]["id"])
    assert_fields_equal(
        event,
        status="SCHEDULED",
        venue_id=ctx["venue_east"]["id"],
        host_member_id=ids["south"],
        revenue_pool_id=pool["id"],
        host_compliance_score_at_award=100,
    )
