"""The reserve posture ladder and the guards that stand between a computed run and cash."""

from test_helpers import (
    FINANCE_OFFICER_USER_ID,
    TREASURER_USER_ID,
    ApiErrorId,
    RunVariant,
    assert_fields_equal,
    assert_posture,
    create_revenue_pool,
    draft_audit_report,
    fund_reserve,
    issue_audit_report,
    make_distribution_run_payload,
    make_finance_officer_headers,
    make_treasurer_headers,
    open_revenue_pool,
    read_conference,
    read_member,
    read_revenue_pool,
    setup_computed_fy2026_final_run,
    setup_operating_conference,
    setup_operating_conference_with_reserve,
    validate_error,
    validate_success,
)


def test_reserve_funded_to_exactly_6000_bps_of_target_is_open(api):
    """PRD §2.10: "The funded ratio, `funded_ratio_bps`, is 10000 when the target is 0;
    otherwise it is `reserve_balance_cents` multiplied by 10000 and divided by
    `reserve_target_cents`, rounded down to a whole basis point."
    PRD §2.10: "Both boundaries fall on the better-funded side: a reserve funded to exactly
    6000 basis points of target is `OPEN`, and one funded to exactly 2500 basis points is
    `RESERVE_RESTRICTED`, not `FROZEN`."

    Design: Difficulty/boundary_precision_check/reserve_funded_ratio_exactly_6000_bps_is_open
    """
    setup_operating_conference(api)
    assert read_conference(api)["reserve_target_cents"] == 18_000_000

    conference = fund_reserve(api, 10_800_000)

    assert_fields_equal(conference, reserve_balance_cents=10_800_000)
    assert_posture(conference, "OPEN", 6000)


def test_reserve_one_cent_below_the_6000_bps_boundary_is_restricted(api):
    """PRD §2.10: "The posture, `reserve_posture`, is one of `OPEN`, `RESERVE_RESTRICTED` or
    `FROZEN`, and is derived by comparing the balance against the target without dividing:
    when the target is 0 the posture is `OPEN`; otherwise, if the balance multiplied by 10000
    is less than the target multiplied by 2500 basis points the posture is `FROZEN`;
    otherwise, if the balance multiplied by 10000 is less than the target multiplied by 6000
    basis points the posture is `RESERVE_RESTRICTED`; otherwise the posture is `OPEN`."
    PRD §2.10: "Both boundaries fall on the better-funded side: a reserve funded to exactly
    6000 basis points of target is `OPEN`, and one funded to exactly 2500 basis points is
    `RESERVE_RESTRICTED`, not `FROZEN`."

    Design: Difficulty/boundary_precision_check/reserve_funded_ratio_exactly_6000_bps_is_open
    """
    setup_operating_conference(api)

    conference = fund_reserve(api, 10_799_999)

    assert_fields_equal(conference, reserve_balance_cents=10_799_999)
    assert_posture(conference, "RESERVE_RESTRICTED", 5999)


def test_draft_pool_reports_the_pool_status_error_ahead_of_the_frozen_reserve(api):
    """PRD §2.8: "The service evaluates checks in a fixed order, and the first failure
    determines the response."
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
    PRD §3.7: "The variant and the pool status are paired: a `PROVISIONAL` run is only
    accepted while the pool is `OPEN`, and a `FINAL_AUDITED` run only while it is
    `BOOKS_CLOSED`; a mismatch is refused with `ERR_POOL_STATE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/pool_state_precedes_reserve_posture_frozen
    """
    ctx = setup_operating_conference(api)
    # An approved budget with an unfunded reserve leaves the posture FROZEN.
    assert_posture(read_conference(api), "FROZEN", 0)
    pool = create_revenue_pool(api, ctx["conference_id"])
    assert pool["status"] == "DRAFT"

    response = api.create_distribution_run(
        pool["id"],
        make_distribution_run_payload(pool["version"], RunVariant.PROVISIONAL.value),
        headers=make_finance_officer_headers(),
    )

    validate_error(response, ApiErrorId.ERR_POOL_STATE_INVALID.value, 409)


def test_open_pool_under_a_frozen_reserve_reports_the_frozen_posture(api):
    """PRD §3.7: "Computing a run is discretionary spending, so it is refused with
    `ERR_RESERVE_POSTURE_FROZEN` while the conference's `reserve_posture` is `FROZEN`."
    PRD §2.10: "While the posture is `FROZEN`, computing a distribution run and awarding a
    championship event are both refused with `ERR_RESERVE_POSTURE_FROZEN` (HTTP 409) — those
    are the only two operations the freeze blocks."

    Design: Difficulty/priority_pair_validation_conflict/pool_state_precedes_reserve_posture_frozen
    """
    ctx = setup_operating_conference(api)
    assert_posture(read_conference(api), "FROZEN", 0)
    pool = create_revenue_pool(api, ctx["conference_id"])
    pool = open_revenue_pool(api, pool["id"])

    response = api.create_distribution_run(
        pool["id"],
        make_distribution_run_payload(pool["version"], RunVariant.PROVISIONAL.value),
        headers=make_finance_officer_headers(),
    )

    validate_error(response, ApiErrorId.ERR_RESERVE_POSTURE_FROZEN.value, 409)
    assert read_revenue_pool(api, pool["id"])["status"] == "OPEN"


def test_posting_by_the_computing_user_reports_segregation_before_the_missing_report(api):
    """PRD §2.11: "Posting a distribution run requires the acting `X-User-ID` to differ from
    that run's `computed_by_user_id`."
    PRD §2.11: "In each case the check runs after the addressed record's status check and
    before the operation's remaining referential and fiscal preconditions."
    PRD §3.7: "It is only available from `COMPUTED` — anything else is refused with
    `ERR_RUN_STATE_INVALID` — the acting `X-User-ID` must differ from the run's
    `computed_by_user_id` or the request is refused with `ERR_SEGREGATION_OF_DUTIES`, a
    `FINAL_AUDITED` run additionally requires an audit report on that run to be in status
    `ISSUED` and is otherwise refused with `ERR_AUDIT_REPORT_NOT_ISSUED`, and the parent pool
    must still be `OPEN` or `BOOKS_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_audit_report_requirement
    """
    ctx = setup_operating_conference_with_reserve(api)
    run = setup_computed_fy2026_final_run(api, ctx)
    assert run["computed_by_user_id"] == FINANCE_OFFICER_USER_ID

    # No audit report exists at all, yet the acting user is the one who computed the run.
    response = api.post_distribution_run(
        run["id"], headers=make_treasurer_headers(FINANCE_OFFICER_USER_ID)
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)
    still_computed = validate_success(
        api.get_distribution_run(run["id"], headers=make_finance_officer_headers())
    )
    assert still_computed["status"] == "COMPUTED"


def test_posting_by_a_second_user_then_reports_the_unissued_audit_report(api):
    """PRD §3.7: "It is only available from `COMPUTED` — anything else is refused with
    `ERR_RUN_STATE_INVALID` — the acting `X-User-ID` must differ from the run's
    `computed_by_user_id` or the request is refused with `ERR_SEGREGATION_OF_DUTIES`, a
    `FINAL_AUDITED` run additionally requires an audit report on that run to be in status
    `ISSUED` and is otherwise refused with `ERR_AUDIT_REPORT_NOT_ISSUED`, and the parent pool
    must still be `OPEN` or `BOOKS_CLOSED`."
    PRD §2.11: "In each case the check runs after the addressed record's status check and
    before the operation's remaining referential and fiscal preconditions."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_audit_report_requirement
    """
    ctx = setup_operating_conference_with_reserve(api)
    run = setup_computed_fy2026_final_run(api, ctx)

    response = api.post_distribution_run(
        run["id"], headers=make_treasurer_headers(TREASURER_USER_ID)
    )

    # With the duties properly separated the masked referential precondition surfaces.
    validate_error(response, ApiErrorId.ERR_AUDIT_REPORT_NOT_ISSUED.value, 409)


def test_final_audited_run_with_a_drafted_report_still_cannot_be_posted(api):
    """PRD §3.9: "Issuing the report is what unlocks the posting of a final audited run, and
    it will not happen unless the run's arithmetic conserves every cent."
    PRD §3.7: "It is only available from `COMPUTED` — anything else is refused with
    `ERR_RUN_STATE_INVALID` — the acting `X-User-ID` must differ from the run's
    `computed_by_user_id` or the request is refused with `ERR_SEGREGATION_OF_DUTIES`, a
    `FINAL_AUDITED` run additionally requires an audit report on that run to be in status
    `ISSUED` and is otherwise refused with `ERR_AUDIT_REPORT_NOT_ISSUED`, and the parent pool
    must still be `OPEN` or `BOOKS_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/posting_final_run_depends_on_issued_audit_report
    """
    ctx = setup_operating_conference_with_reserve(api)
    run = setup_computed_fy2026_final_run(api, ctx)
    report = draft_audit_report(api, ctx["conference_id"], run["id"], fiscal_year=2026)
    assert_fields_equal(report, status="DRAFT", reconciliation_delta_cents=0)

    response = api.post_distribution_run(
        run["id"], headers=make_treasurer_headers(TREASURER_USER_ID)
    )

    validate_error(response, ApiErrorId.ERR_AUDIT_REPORT_NOT_ISSUED.value, 409)
    still_computed = validate_success(
        api.get_distribution_run(run["id"], headers=make_finance_officer_headers())
    )
    assert still_computed["status"] == "COMPUTED"
    for member_id in ctx["member_ids"].values():
        assert read_member(api, member_id)["last_full_annual_distribution_cents"] == 0


def test_issuing_the_report_unlocks_the_post_that_writes_the_annual_distribution(api):
    """PRD §3.9: "A successful issue recomputes and writes `reconciliation_delta_cents`, sets
    the status to `ISSUED`, records `issued_by_user_id` from the acting user, and advances the
    report's `version` by 1."
    PRD §3.7: "Posting sets the run `POSTED`, stamps `posted_at` from the logical clock and
    `posted_by_user_id` from the acting user, increases the conference's
    `reserve_balance_cents` by the run's `reserve_draw_cents` and re-derives `reserve_posture`
    and `funded_ratio_bps` from the new balance, increases `escrow_balance_cents` by the sum
    of the lines' `withheld_cents`, increases `governance_fee_revenue_cents` by the sum of the
    lines' `governance_fee_cents`, advances each affected member's `exit_settlement_paid_cents`
    by that member's line's `gor_offset_cents` where it is positive, and — only when the run's
    `variant` is `FINAL_AUDITED` and the pool's `pool_type` is `MEDIA_RIGHTS` — writes each
    line's `gross_share_cents` into that member's `last_full_annual_distribution_cents`, which
    is the figure every future exit settlement is assessed against."

    Design: Difficulty/cross_entity_state_dependency/posting_final_run_depends_on_issued_audit_report
    """
    ctx = setup_operating_conference_with_reserve(api)
    run = setup_computed_fy2026_final_run(api, ctx)
    report = draft_audit_report(api, ctx["conference_id"], run["id"], fiscal_year=2026)

    issued = issue_audit_report(api, report["id"])
    posted = validate_success(
        api.post_distribution_run(
            run["id"], headers=make_treasurer_headers(TREASURER_USER_ID)
        )
    )

    assert_fields_equal(issued, status="ISSUED", reconciliation_delta_cents=0)
    assert_fields_equal(
        posted, status="POSTED", posted_by_user_id=TREASURER_USER_ID
    )
    assert posted["posted_at"] is not None
    for member_id in ctx["member_ids"].values():
        assert_fields_equal(
            read_member(api, member_id),
            last_full_annual_distribution_cents=147_500_000,
        )
    conference = read_conference(api)
    assert_fields_equal(
        conference,
        reserve_balance_cents=18_000_000,
        escrow_balance_cents=0,
        governance_fee_revenue_cents=5_000_000,
    )
    assert_posture(conference, "OPEN", 10000)
