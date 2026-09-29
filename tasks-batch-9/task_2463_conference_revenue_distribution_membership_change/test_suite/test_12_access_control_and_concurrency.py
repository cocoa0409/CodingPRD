"""Access control, optimistic concurrency, pagination bounds and the immediacy of derived
state: the cross-cutting layers every endpoint sits on top of."""

from test_helpers import (
    AllocationMethod,
    ApiErrorId,
    COMMISSIONER_USER_ID,
    COMPLIANCE_OFFICER_USER_ID,
    NON_EXISTENT_UUID,
    PoolType,
    assert_fields_equal,
    assert_pagination_meta,
    assert_reimbursement,
    assert_tally,
    assert_valuation,
    begin_bowl_review,
    cast_action_ballots,
    close_action_voting,
    execute_membership_action,
    is_valid_uuid,
    make_action_ballot_payload,
    make_audit_report_payload,
    make_auditor_headers,
    make_bowl_appearance_payload,
    make_commissioner_headers,
    make_compliance_officer_headers,
    make_distribution_run_payload,
    make_finance_officer_headers,
    make_member_payload,
    make_member_representative_headers,
    make_member_update_payload,
    make_reserve_transfer_payload,
    make_revenue_pool_payload,
    make_schedule_coordinator_headers,
    make_platform_admin_headers,
    make_treasurer_headers,
    make_venue_payload,
    read_conference,
    read_member,
    read_membership_action,
    read_revenue_pool,
    setup_admit_action_in_voting,
    setup_charter_roster,
    setup_computed_fy2026_final_run,
    setup_fy2027_media_pool,
    setup_operating_conference_with_reserve,
    submit_bowl_appearance,
    validate_error,
    validate_paginated,
    validate_success,
)

# Neither X-User-ID nor X-User-Role is present on an anonymous request.
ANONYMOUS_HEADERS: dict = {}

CHARTER_KEYS = ("north", "south", "east", "west")


def _total(response):
    return validate_paginated(response)[1]["total_count"]


def _read_run(api, run_id):
    return validate_success(
        api.get_distribution_run(run_id, headers=make_finance_officer_headers())
    )


def test_the_phase_ladder_climbs_four_rungs_and_then_refuses_a_fifth(api):
    """PRD §3.1: "Each advance is a distinct step taken by a `Commissioner` or a
    `FinanceOfficer`, requires the member to be `ADMITTED_PHASING`, and requires the entry fee
    to be fully settled — that is, `entry_fee_paid_cents` at least equal to `entry_fee_cents`;
    a member still owing any part of its fee is refused with `ERR_ENTRY_FEE_OUTSTANDING` (HTTP
    402)."
    PRD §3.1: "An advance increments `phase_year` by 1 and then re-derives the share
    multiplier."
    PRD §3.1: "With the default of three phasing years the ladder is therefore: `phase_year` 1
    gives 2500 basis points, 2 gives 5000, 3 gives 7500, and 4 gives 10000."
    PRD §3.1: "The advance that carries the member to 10000 — equivalently, the advance whose
    resulting `phase_year` reaches one more than `phase_schedule_years` — is also the advance
    that promotes it out of `ADMITTED_PHASING` into `FULL_SHARE`, with `distribution_phase_bps`
    and `voting_weight_bps` both set to 10000."
    PRD §3.1: "Voting weight tracks the ladder but is not identical to it: `voting_weight_bps`
    is 0 for a member in `PETITIONED`, `ADMISSION_DENIED`, `WITHDRAWAL_NOTICED` or `DEPARTED`,
    is 10000 for a member in `FULL_SHARE`, and otherwise equals `distribution_phase_bps`."
    PRD §2.8: "The full ladder is: authentication (`ERR_UNAUTHENTICATED`), role authorisation
    (`ERR_UNAUTHORIZED`), member ownership for a `MemberRepresentative`
    (`ERR_NOT_MEMBER_OWNER`), conference existence (`ERR_CONFERENCE_NOT_INITIALIZED`, or
    `ERR_CONFERENCE_ALREADY_EXISTS` on initialisation), path-identifier resolution (the 404
    family), request-shape validation (`ERR_INVALID_REQUEST`), pagination bounds
    (`ERR_INVALID_PAGINATION`), body foreign-key resolution (the 404 family again),
    institution-code uniqueness (`ERR_DUPLICATE_INSTITUTION_CODE`), member-pair distinctness
    (`ERR_MEMBER_PAIR_INVALID`), rivalry uniqueness (`ERR_DUPLICATE_RIVALRY`), the
    optimistic-concurrency version checks (the 412 family), the charter-window check
    (`ERR_CHARTER_WINDOW_CLOSED`), the per-entity status checks (`ERR_POOL_STATE_INVALID`,
    `ERR_RUN_STATE_INVALID`, `ERR_APPEARANCE_STATE_INVALID`, `ERR_ACTION_STATE_INVALID`,
    `ERR_PROPOSAL_STATE_INVALID`, `ERR_GAME_STATE_INVALID`, `ERR_EVENT_STATE_INVALID`,
    `ERR_REPORT_STATE_INVALID`, `ERR_MEMBER_STATE_INVALID`, in that relative order), the
    amendment budget (`ERR_AMEND_LIMIT_REACHED`), segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`), the already-distributed guard on voiding an appearance
    (`ERR_UNITS_ALREADY_DISTRIBUTED`), the temporal checks
    (`ERR_MEMBER_REST_BUFFER_VIOLATION`, then `ERR_VENUE_CAPACITY_EXCEEDED`, then
    `ERR_INVALID_EFFECTIVE_YEAR`), the remaining shape constraints
    (`ERR_VENUE_NOT_HOME_VENUE`, then `ERR_INVALID_EVENT_WINDOW`, then
    `ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE`, then `ERR_DUPLICATE_BALLOT`), the referential
    preconditions (`ERR_NO_APPROVED_BUDGET`, then `ERR_BOWL_REVIEW_PENDING`, then
    `ERR_AUDIT_REPORT_NOT_ISSUED`, then `ERR_HOST_COMPLIANCE_INSUFFICIENT`, then
    `ERR_POOL_CLOSED_TO_REVENUE`, then `ERR_RECONCILIATION_IMBALANCE`), and finally the
    fiscal checks (`ERR_RESERVE_POSTURE_FROZEN`, then `ERR_AUDITED_EXPENSE_MISSING`, then
    `ERR_EMPTY_ALLOCATION_BASIS`, then `ERR_ENTRY_FEE_OUTSTANDING`, then
    `ERR_ENTRY_FEE_OVERPAYMENT`, then `ERR_RESERVE_INSUFFICIENT`)."

    Design: Corner/endpoints/corner_phase_advance_action_endpoint_walks_the_ladder
    """
    ctx = setup_admit_action_in_voting(api)
    central_id = ctx["member_ids"]["central"]
    cast_action_ballots(
        api,
        ctx["action_id"],
        [(ctx["member_ids"][key], "FOR") for key in CHARTER_KEYS],
    )
    close_action_voting(api, ctx["action_id"])
    execute_membership_action(api, ctx["action_id"])

    assert_fields_equal(
        read_member(api, central_id),
        status="ADMITTED_PHASING",
        phase_year=1,
        distribution_phase_bps=2500,
        voting_weight_bps=2500,
    )
    rungs = [
        validate_success(
            api.advance_member_phase(central_id, headers=make_finance_officer_headers())
        )
        for _ in range(3)
    ]
    fifth = api.advance_member_phase(
        central_id, headers=make_finance_officer_headers()
    )

    assert_fields_equal(
        rungs[0],
        status="ADMITTED_PHASING",
        phase_year=2,
        distribution_phase_bps=5000,
        voting_weight_bps=5000,
    )
    assert_fields_equal(
        rungs[1],
        status="ADMITTED_PHASING",
        phase_year=3,
        distribution_phase_bps=7500,
        voting_weight_bps=7500,
    )
    # The promotion is keyed on the multiplier reaching 10000, not on phase_year
    # reaching phase_schedule_years.
    assert_fields_equal(
        rungs[2],
        status="FULL_SHARE",
        phase_year=4,
        distribution_phase_bps=10000,
        voting_weight_bps=10000,
    )
    validate_error(fifth, ApiErrorId.ERR_MEMBER_STATE_INVALID.value, 409)
    assert read_member(api, central_id)["phase_year"] == 4


def test_the_pagination_window_brackets_its_two_accepted_edges(api):
    """PRD §2.3: "When `limit` is omitted it defaults to 10; the smallest accepted value is 1
    and the largest is 100."
    PRD §2.3: "When `offset` is omitted it defaults to 0, and the smallest accepted value is
    0."
    PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."
    PRD §2.3: "For every list response, the `meta` object carries `limit` and `offset` as they
    were applied, `total_count` as the number of records matching the filters before the window
    was applied, and `has_more` as a boolean that is true when records remain beyond the current
    window."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific
    error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/corner_pagination_bounds_and_error_envelope_rejected
    """
    ctx = setup_charter_roster(api)
    scope = {"conference_id": ctx["conference_id"]}
    headers = make_auditor_headers()

    below = api.list_members(params={**scope, "limit": 0, "offset": 0}, headers=headers)
    above = api.list_members(
        params={**scope, "limit": 101, "offset": 0}, headers=headers
    )
    negative = api.list_members(
        params={**scope, "limit": 2, "offset": -1}, headers=headers
    )
    smallest, smallest_meta = validate_paginated(
        api.list_members(params={**scope, "limit": 1, "offset": 0}, headers=headers)
    )
    largest, largest_meta = validate_paginated(
        api.list_members(params={**scope, "limit": 100, "offset": 0}, headers=headers)
    )

    # validate_error also proves the envelope carries a non-empty data.message.
    validate_error(below, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)
    validate_error(above, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)
    validate_error(negative, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)
    assert len(smallest) == 1
    assert_pagination_meta(smallest_meta, 1, 0, 4, True)
    assert len(largest) == 4
    assert_pagination_meta(largest_meta, 100, 0, 4, False)


def test_an_anonymous_request_learns_nothing_at_all(api):
    """PRD §2.1: "Every request to the service must carry two headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, naming the role that user is acting in."
    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the declared role
    names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "This check runs before every other check in the system."
    PRD §4: "An endpoint that creates a new resource returns HTTP 201 with the created resource
    in `data`; every other successful call returns HTTP 200, with the updated resource in `data`
    for a write and the requested resource or array for a read."

    Design: Corner/RBAC/corner_missing_auth_headers_returns_unauthenticated
    """
    setup_charter_roster(api)
    anonymous_venue = make_venue_payload(
        name="Anonymous Field", city="Nowhere", seating_capacity=10000
    )

    read = api.get_conference(headers=ANONYMOUS_HEADERS)
    write = api.create_venue(anonymous_venue, headers=ANONYMOUS_HEADERS)
    unknown_member = api.get_member(NON_EXISTENT_UUID, headers=ANONYMOUS_HEADERS)

    validate_error(read, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    validate_error(write, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    # 401 rather than 404: authentication precedes path resolution, so the refusal
    # does not disclose whether that member id exists.
    validate_error(unknown_member, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    retry = validate_success(
        api.create_venue(anonymous_venue, headers=make_platform_admin_headers()), 201
    )
    assert is_valid_uuid(retry["id"])
    assert retry["version"] == 1, "the anonymous attempt persisted nothing"


def test_no_role_may_reach_into_another_roles_exclusive_operation(api):
    """PRD §2.1: "Once the caller is identified, the role is matched against the set of roles
    authorised for the addressed endpoint (the authorisation column of the endpoint table in
    §4); a role outside that set is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "Authorisation is evaluated immediately after authentication and before any
    resource is loaded, so an unauthorised caller learns nothing about whether the addressed
    record exists."
    PRD §2.1: "A **`FinanceOfficer`** owns the money-shaping side: creating revenue pools and
    driving their lifecycle, computing distribution runs, settling championship events, drafting
    budget proposals and opening and closing budget voting, and advancing a member's
    distribution phase; a `FinanceOfficer` may never post a run, because posting belongs to the
    `Treasurer` and additionally requires a different user than the one who computed it."
    PRD §2.1: "A **`Treasurer`** moves cash: posting and reversing distribution runs, recording
    entry-fee instalments, and contributing to or withdrawing from the conference reserve; a
    `Treasurer` may not post a run whose `computed_by_user_id` equals the acting `X-User-ID`."
    PRD §2.1: "An **`Auditor`** attests runs to the membership by drafting and issuing audit
    reports, and may not issue a report on a run it computed itself."
    PRD §2.1: "A **`ScheduleCoordinator`** builds the competitive calendar: registering venues,
    creating protected rivalries, creating, playing and cancelling games, and awarding and
    cancelling championship events."

    Design: Corner/RBAC/corner_peer_role_cannot_perform_another_roles_exclusive_operation
    """
    ctx = setup_operating_conference_with_reserve(api)
    run = setup_computed_fy2026_final_run(api, ctx)

    commissioner_pool = api.create_revenue_pool(
        make_revenue_pool_payload(
            ctx["conference_id"],
            fiscal_year=2028,
            pool_type=PoolType.MEDIA_RIGHTS.value,
            allocation_method=AllocationMethod.EQUAL_SHARE.value,
            gross_revenue_cents=100_000_000,
            estimated_expense_cents=0,
        ),
        headers=make_commissioner_headers(),
    )
    finance_officer_post = api.post_distribution_run(
        run["id"], headers=make_finance_officer_headers()
    )
    treasurer_member = api.create_member(
        make_member_payload(
            ctx["conference_id"],
            ctx["venue_east"]["id"],
            name="Treasurer's Pick College",
            institution_code="TPC",
            admission_path="PETITIONED",
            grant_of_rights_through_fiscal_year=2034,
        ),
        headers=make_treasurer_headers(),
    )
    coordinator_report = api.create_audit_report(
        make_audit_report_payload(
            ctx["conference_id"], run["id"], fiscal_year=2026, note="not my job"
        ),
        headers=make_schedule_coordinator_headers(),
    )

    validate_error(commissioner_pool, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    # 403, not ERR_AUDIT_REPORT_NOT_ISSUED or ERR_SEGREGATION_OF_DUTIES: the role
    # check runs before any of the operation's own preconditions.
    validate_error(finance_officer_post, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    validate_error(treasurer_member, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    validate_error(coordinator_report, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    assert_fields_equal(
        _read_run(api, run["id"]), status="COMPUTED", posted_by_user_id=None
    )
    assert _total(api.list_revenue_pools(headers=make_auditor_headers())) == 1
    assert _total(api.list_members(headers=make_auditor_headers())) == 4
    assert _total(api.list_audit_reports(headers=make_auditor_headers())) == 0


def test_a_representative_is_confined_to_its_own_institution_in_path_and_body(api):
    """PRD §2.1: "`MemberRepresentative` is the exception: when `X-User-Role` is
    `MemberRepresentative`, `X-User-ID` is the `id` of the acting member institution, and
    ownership checks compare it against the member the request targets."
    PRD §2.1: "Concretely, for a member profile amendment, an entry-fee payment, a
    bowl-appearance submission, a bowl-appearance resubmission, and a ballot cast on either a
    membership action or a budget proposal, `X-User-ID` must equal the `Member` `id` named in
    the path or carried in the request body as `member_id`; a mismatch is rejected with
    `ERR_NOT_MEMBER_OWNER` (HTTP 403)."
    PRD §2.1: "That ownership check is the third check in the ladder — it runs after
    authentication and role authorisation, and before the conference-initialisation check, path
    resolution and every business rule."
    PRD §3.2: "On acceptance the ballot is created in status `CAST` with its `weight_bps`
    snapshotted from the member's `voting_weight_bps` at that moment, so later changes to the
    member's weight do not retroactively re-weight a vote already cast."

    Design: Corner/RBAC/corner_member_representative_cannot_act_for_another_member
    """
    ctx = setup_admit_action_in_voting(api)
    north_id = ctx["member_ids"]["north"]
    south_id = ctx["member_ids"]["south"]
    south = read_member(api, south_id)
    action_version = read_membership_action(api, ctx["action_id"])["version"]
    impostor = make_member_representative_headers(north_id)

    cross_patch = api.update_member(
        south_id,
        make_member_update_payload(
            south["version"], grant_of_rights_through_fiscal_year=2040
        ),
        headers=impostor,
    )
    cross_appearance = api.create_bowl_appearance(
        south_id,
        make_bowl_appearance_payload(
            event_name="Impostor Invitational",
            event_tier="BOWL",
            payout_cents=5_000_000,
            submitted_expense_cents=1_000_000,
            travel_miles=100,
            units_claimed=1,
        ),
        headers=impostor,
    )
    cross_ballot = api.cast_action_ballot(
        ctx["action_id"],
        make_action_ballot_payload(south_id, action_version),
        headers=impostor,
    )
    own_ballot = api.cast_action_ballot(
        ctx["action_id"],
        make_action_ballot_payload(north_id, action_version),
        headers=impostor,
    )

    validate_error(cross_patch, ApiErrorId.ERR_NOT_MEMBER_OWNER.value, 403)
    assert read_member(api, south_id)["version"] == south["version"]
    validate_error(cross_appearance, ApiErrorId.ERR_NOT_MEMBER_OWNER.value, 403)
    assert (
        _total(api.list_member_bowl_appearances(south_id, headers=make_auditor_headers()))
        == 0
    )
    # A path-only ownership check would wrongly allow this one: the path names the
    # action, and it is the body's member_id that belongs to somebody else.
    validate_error(cross_ballot, ApiErrorId.ERR_NOT_MEMBER_OWNER.value, 403)
    validate_success(own_ballot, 201)
    ballots, meta = validate_paginated(
        api.list_action_ballots(ctx["action_id"], headers=make_commissioner_headers())
    )
    assert meta["total_count"] == 1
    assert_fields_equal(
        ballots[0], member_id=north_id, choice="FOR", status="CAST", weight_bps=10000
    )


def test_the_proposer_may_not_close_the_ballot_it_opened(api):
    """PRD §2.11: "Closing the voting on a membership action requires the acting `X-User-ID` to
    differ from that action's `proposed_by_user_id`."
    PRD §2.11: "These are checks on the user identifier, not merely on the role: a `Treasurer`
    and a `FinanceOfficer` are different roles, but if the same operator identifier appears in
    both requests the second one fails."
    PRD §3.2: "Closing the ballot is where the weighted arithmetic happens, and it is performed
    by a `ComplianceOfficer` or a `Commissioner` other than the one who proposed the action —
    the same user who proposed it is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.2: "A new action is created in `PROPOSED` with `amend_count` of 0,
    `quorum_weight_bps` of 6000, `proposed_by_user_id` taken from the acting `X-User-ID`, and
    `version` 1."
    PRD §3.2: "Whichever branch is taken, the tally fields — `eligible_weight_bps`,
    `cast_weight_bps`, `for_weight_bps`, `against_weight_bps`, `quorum_met`,
    `approval_ratio_bps` and `required_approval_bps` — are written onto the action,
    `closed_by_user_id` records the acting `X-User-ID`, and the action's `version` advances."
    PRD §3.2: "The outcome is `APPROVED` when quorum was met and `approval_ratio_bps` is
    greater than or equal to `required_approval_bps`, and `REJECTED` otherwise; both comparisons
    are inclusive, so an `ADMIT` whose ratio lands on exactly 7500 basis points passes, and a
    `WITHDRAW` at exactly 6000 passes."

    Design: Corner/RBAC/corner_proposer_cannot_close_the_vote_it_opened
    """
    ctx = setup_admit_action_in_voting(api)
    action_id = ctx["action_id"]
    cast_action_ballots(
        api, action_id, [(ctx["member_ids"][key], "FOR") for key in CHARTER_KEYS]
    )
    assert (
        read_membership_action(api, action_id)["proposed_by_user_id"]
        == COMMISSIONER_USER_ID
    )

    # Commissioner is a declared role for this endpoint, so the refusal cannot be
    # role-based: it is this particular operator that is disqualified.
    refused = api.close_action_voting(action_id, headers=make_commissioner_headers())

    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)
    assert_fields_equal(
        read_membership_action(api, action_id),
        status="VOTING",
        approval_ratio_bps=0,
        closed_by_user_id=None,
    )

    closed = validate_success(
        api.close_action_voting(action_id, headers=make_compliance_officer_headers())
    )

    assert_tally(closed, 40000, 40000, 40000, 0, True, 10000, status="APPROVED")
    assert closed["closed_by_user_id"] == COMPLIANCE_OFFICER_USER_ID


def test_each_of_the_four_write_endpoints_carries_its_own_stale_version_code(api):
    """PRD §2.6: "Four write operations require the client to prove it is working from a current
    read, by echoing back the `version` it last observed on a parent record."
    PRD §2.6: "Computing a distribution run on a revenue pool requires `expected_pool_version`
    to equal that pool's current `version`; if it does not, the request is rejected with
    `ERR_STALE_POOL_VERSION` (HTTP 412)."
    PRD §2.6: "Casting a ballot on a membership action requires `expected_action_version` to
    equal that action's current `version`, failing with `ERR_STALE_ACTION_VERSION` (HTTP 412)."
    PRD §2.6: "A reserve transfer requires `expected_conference_version` to equal the conference
    record's current `version`, failing with `ERR_STALE_CONFERENCE_VERSION` (HTTP 412)."
    PRD §2.6: "Amending a member profile requires `expected_member_version` to equal that
    member's current `version`, failing with `ERR_STALE_MEMBER_VERSION` (HTTP 412)."
    PRD §2.6: "No other write in the system takes an expected-version field."
    PRD §3.7: "The `net_pool_cents` is `gross_revenue_cents` minus that basis, and it may be
    negative if expenses exceed receipts."
    PRD §3.7: "Under `APPEARANCE_PERFORMANCE_WEIGHTED` it is 10000, plus 1500 for each media
    appearance, plus 2500 for each postseason berth."
    PRD §4: "An endpoint that creates a new resource returns HTTP 201 with the created resource
    in `data`; every other successful call returns HTTP 200, with the updated resource in `data`
    for a write and the requested resource or array for a read."

    Design: Corner/cross-cutting complexity layers/corner_occ_stale_version_on_all_four_declared_write_endpoints
    """
    ctx = setup_admit_action_in_voting(api)
    pool = setup_fy2027_media_pool(api, ctx)
    north_id = ctx["member_ids"]["north"]
    east_id = ctx["member_ids"]["east"]
    action_version = read_membership_action(api, ctx["action_id"])["version"]
    conference = read_conference(api)
    east = read_member(api, east_id)

    stale_run = api.create_distribution_run(
        pool["id"],
        make_distribution_run_payload(pool["version"] - 1, memo="stale pool view"),
        headers=make_finance_officer_headers(),
    )
    stale_ballot = api.cast_action_ballot(
        ctx["action_id"],
        make_action_ballot_payload(north_id, action_version - 1),
        headers=make_member_representative_headers(north_id),
    )
    stale_transfer = api.create_reserve_transfer(
        make_reserve_transfer_payload(
            1_000_000, conference["version"] - 1, memo="stale conference view"
        ),
        headers=make_treasurer_headers(),
    )
    stale_patch = api.update_member(
        east_id,
        make_member_update_payload(
            east["version"] - 1, grant_of_rights_through_fiscal_year=2035
        ),
        headers=make_commissioner_headers(),
    )

    validate_error(stale_run, ApiErrorId.ERR_STALE_POOL_VERSION.value, 412)
    validate_error(stale_ballot, ApiErrorId.ERR_STALE_ACTION_VERSION.value, 412)
    validate_error(stale_transfer, ApiErrorId.ERR_STALE_CONFERENCE_VERSION.value, 412)
    validate_error(stale_patch, ApiErrorId.ERR_STALE_MEMBER_VERSION.value, 412)
    assert _total(api.list_distribution_runs(headers=make_finance_officer_headers())) == 0
    assert read_conference(api)["reserve_balance_cents"] == 12_000_000
    assert read_member(api, east_id)["grant_of_rights_through_fiscal_year"] == 2032

    # Every retry re-uses the very version the refusal was measured against, which
    # proves no refusal bumped its parent.
    run = validate_success(
        api.create_distribution_run(
            pool["id"],
            make_distribution_run_payload(pool["version"], memo="current pool view"),
            headers=make_finance_officer_headers(),
        ),
        201,
    )
    validate_success(
        api.cast_action_ballot(
            ctx["action_id"],
            make_action_ballot_payload(north_id, action_version),
            headers=make_member_representative_headers(north_id),
        ),
        201,
    )
    transfer = validate_success(
        api.create_reserve_transfer(
            make_reserve_transfer_payload(
                1_000_000, conference["version"], memo="current conference view"
            ),
            headers=make_treasurer_headers(),
        )
    )
    patched = validate_success(
        api.update_member(
            east_id,
            make_member_update_payload(
                east["version"], grant_of_rights_through_fiscal_year=2035
            ),
            headers=make_commissioner_headers(),
        )
    )

    assert read_revenue_pool(api, pool["id"])["version"] == pool["version"] + 1
    # No assertion on the action's version after a ballot: the PRD advances an
    # action's version on amend, close and execute, and never states that casting
    # a ballot mutates the action itself (§2.5 keeps a ballot a light resource
    # whose parent is only retallied at close).
    assert transfer["version"] == conference["version"] + 1
    assert patched["version"] == east["version"] + 1
    # Central at 0 basis points receives no line, so the four charter seats carry
    # the whole basis.
    assert_fields_equal(
        run,
        net_pool_cents=480_000_000,
        reserve_draw_cents=6_000_000,
        total_weight_bps=40000,
    )


def test_the_approval_response_already_carries_every_derived_figure(api):
    """PRD §3.6: "First, `allowable_expense_cents` is the smaller of the claimed
    `submitted_expense_cents` and the allowable-expense cap of 8,000,000 cents (80,000
    dollars)."
    PRD §3.6: "Second, `travel_allowance_cents` is the smaller of `travel_miles` multiplied by
    the travel rate of 95 cents per mile and the travel-allowance cap of 2,500,000 cents (25,000
    dollars)."
    PRD §3.6: "The `reimbursement_ceiling_cents` is `payout_cents` multiplied by the selected
    band and divided by 10000, rounded up to the next whole cent."
    PRD §3.6: "Then `reimbursed_cents` is the smaller of the sum of `allowable_expense_cents`
    and `travel_allowance_cents` and that ceiling, and `residual_to_pool_cents` is
    `payout_cents` minus `reimbursed_cents`."
    PRD §3.6: "Approving therefore moves the appearance `UNDER_REVIEW` → `APPROVED`, writes
    `allowable_expense_cents`, `travel_allowance_cents`, `reimbursement_ceiling_cents`,
    `reimbursed_cents` and `residual_to_pool_cents`, adds `residual_to_pool_cents` to the
    conference's `escrow_balance_cents`, transitions every postseason unit of the appearance
    `PROVISIONAL` → `VALIDATED`, advances the conference's `validated_postseason_unit_count` by
    `units_claimed`, and increments the conference's `version` by 1."
    PRD §3.6: "Within the window, `validated_unit_count` is the number of that member's
    postseason units in status `VALIDATED` whose `fiscal_year` falls inside the window —
    provisional and voided units never count — and `valuation_cents` is that count multiplied by
    the conference's `unit_value_cents`, an exact multiplication with no rounding."
    PRD §3.6: "The appearance is created in `SUBMITTED`, and submitting it mints `units_claimed`
    postseason units in status `PROVISIONAL`, each carrying its parent's identifier as
    `bowl_appearance_id`, the credited `member_id`, a `fiscal_year` copied from the parent
    appearance, and a 1-based `unit_index` giving its ordinal within the appearance."

    Design: Corner/consistency model/corner_immediate_visibility_of_derived_fields_within_the_response
    """
    ctx = setup_charter_roster(api)
    north_id = ctx["member_ids"]["north"]
    appearance = submit_bowl_appearance(api, north_id)
    begin_bowl_review(api, appearance["id"])

    approved = validate_success(
        api.approve_bowl_appearance(
            appearance["id"], headers=make_compliance_officer_headers()
        )
    )

    # No follow-up read is needed to see the five figures.
    assert approved["status"] == "APPROVED"
    assert_reimbursement(approved, 8_000_000, 133_000, 7_200_000, 7_200_000, 4_800_000)
    assert_fields_equal(
        read_conference(api),
        escrow_balance_cents=4_800_000,
        validated_postseason_unit_count=2,
    )
    valuation = validate_success(
        api.get_postseason_unit_valuation(
            north_id, headers=make_finance_officer_headers()
        )
    )
    # The valuation is derived from units that did not exist before the approve call.
    assert_valuation(valuation, "ROLLING_SIX_YEAR", 2022, 2027, 2, 68_000_000)
    units, meta = validate_paginated(
        api.list_appearance_postseason_units(
            appearance["id"], headers=make_auditor_headers()
        )
    )
    assert meta["total_count"] == 2
    assert [unit["unit_index"] for unit in units] == [1, 2]
    for unit in units:
        assert_fields_equal(unit, status="VALIDATED", fiscal_year=2027)
