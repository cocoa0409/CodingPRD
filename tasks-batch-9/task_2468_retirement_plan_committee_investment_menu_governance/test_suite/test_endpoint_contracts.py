"""Endpoint contracts: what each documented endpoint accepts, what it refuses,
and what the response body has to say afterwards.

The scenarios here exercise the narrow endpoints — the monitoring refresh, the
share-class ratchet, the typed motion subject, the qualified-default slot, the
computed plan read and the listing envelope — against the field lists and
filters PRD 3 and PRD 4 spell out.
"""

from test_helpers.api_client import paginate_params
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_at_risk_bookkeeping,
    assert_capacity_triple,
    assert_cents,
    assert_common_fields,
    assert_contains_ids,
    assert_credit_balance_identity,
    assert_excludes_ids,
    assert_fields,
    assert_ordered_by,
    assert_plan_assets_conserved,
    assert_posture_matches_ratio,
    assert_ratio,
    assert_status,
    assert_version_bumped,
    get_success_data,
    ids_of,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    Paths,
    ips_adopt_payload,
    motion_payload,
    seat_fund_payload,
    share_class_change_payload,
)
from test_helpers.fixtures import (
    create_engagement,
    create_fund,
    draft_ips,
    hold_meeting_and_carry_motion,
    open_meeting,
    read_fund,
    read_plan,
    read_proposal,
    read_slot,
    seat_fund,
)
from test_helpers.test_users import auditor_headers, consultant_headers, sponsor_headers
from test_helpers.types import (
    CharterStatus,
    CreditAccrualStatus,
    FundMenuStatus,
    IpsStatus,
    MenuPosture,
    MotionStatus,
    MotionSubjectType,
    ProposalStatus,
    ProviderRole,
    ShareClass,
    SlotDesignation,
    SlotStatus,
    WatchStatus,
)


def test_patch_fund_touches_only_the_supplied_monitoring_fields(api, full_menu):
    """A monitoring refresh writes exactly the fields it names, reprices the
    plan's asset total and leaves both of the fund's status dimensions alone.

    Design: Corner/endpoints/patch_fund_updates_only_the_supplied_monitoring_fields_and_reprices_the_plan
    """
    ctx = full_menu
    fund_id = ctx.fund("lc_a")["id"]
    before = read_fund(api, fund_id)
    assert_fields(
        before,
        gross_expense_ratio_bps=45,
        net_expense_ratio_bps=45,
        revenue_share_bps=10,
        peer_median_expense_bps=40,
        manager_tenure_quarters=20,
        manager_change_flag=False,
        plan_assets_cents=800000000,
        menu_status=FundMenuStatus.ACTIVE,
        watch_status=WatchStatus.CLEAR,
    )
    assert_ratio(before["style_drift_r2"], "0.9200", "style_drift_r2")
    assert_plan_assets_conserved(read_plan(api, ctx.plan_id), 1200000000)

    first = get_success_data(
        api.patch(
            Paths.fund(fund_id),
            {"net_expense_ratio_bps": 38, "plan_assets_cents": 900000000},
            consultant_headers(),
        )
    )
    assert_fields(
        first,
        net_expense_ratio_bps=38,
        plan_assets_cents=900000000,
        # untouched by this request
        gross_expense_ratio_bps=45,
        revenue_share_bps=10,
        peer_median_expense_bps=40,
        manager_tenure_quarters=20,
        manager_change_flag=False,
        # a data refresh is not a governance decision
        menu_status=FundMenuStatus.ACTIVE,
        watch_status=WatchStatus.CLEAR,
        credit_accrual_status=CreditAccrualStatus.ACCRUING,
    )
    assert_ratio(first["style_drift_r2"], "0.9200", "style_drift_r2")
    assert_version_bumped(before, first)
    # 8,000,000.00 of large-cap assets became 9,000,000.00.
    assert_plan_assets_conserved(read_plan(api, ctx.plan_id), 1300000000)

    second = get_success_data(
        api.patch(
            Paths.fund(fund_id),
            {
                "gross_expense_ratio_bps": 50,
                "revenue_share_bps": 12,
                "peer_median_expense_bps": 42,
                "style_drift_r2": 0.8500,
                "manager_tenure_quarters": 24,
                "manager_change_flag": True,
            },
            consultant_headers(),
        )
    )
    assert_fields(
        second,
        gross_expense_ratio_bps=50,
        revenue_share_bps=12,
        peer_median_expense_bps=42,
        manager_tenure_quarters=24,
        manager_change_flag=True,
        # still carrying what the first refresh wrote
        net_expense_ratio_bps=38,
        plan_assets_cents=900000000,
        menu_status=FundMenuStatus.ACTIVE,
        watch_status=WatchStatus.CLEAR,
    )
    assert_ratio(second["style_drift_r2"], "0.8500", "style_drift_r2")
    assert_version_bumped(first, second)
    assert_plan_assets_conserved(read_plan(api, ctx.plan_id), 1300000000)


def test_share_class_change_only_moves_downward_in_cost(api, full_menu):
    """Equal cost, higher cost and a richer revenue share are all refused; only
    a strictly cheaper class with no more revenue sharing is accepted, and the
    ratchet then holds at the new level.

    Design: Corner/endpoints/share_class_change_refuses_every_direction_that_is_not_strictly_cheaper
    """
    ctx = full_menu
    fund_id = ctx.fund("lc_a")["id"]
    before = read_fund(api, fund_id)
    assert_fields(
        before, share_class_code=ShareClass.R6, net_expense_ratio_bps=45, revenue_share_bps=10
    )

    validate_error(
        api.post(
            Paths.share_class_change(fund_id),
            share_class_change_payload(ShareClass.INSTITUTIONAL, 45, 10),
            consultant_headers(),
        ),
        ApiErrorId.SHARE_CLASS_INELIGIBLE,
    )
    validate_error(
        api.post(
            Paths.share_class_change(fund_id),
            share_class_change_payload(ShareClass.INSTITUTIONAL, 50, 10),
            consultant_headers(),
        ),
        ApiErrorId.SHARE_CLASS_INELIGIBLE,
    )
    # Cheaper, but the revenue share paid to the plan would rise.
    validate_error(
        api.post(
            Paths.share_class_change(fund_id),
            share_class_change_payload(ShareClass.INSTITUTIONAL, 40, 12),
            consultant_headers(),
        ),
        ApiErrorId.SHARE_CLASS_INELIGIBLE,
    )
    assert_fields(
        read_fund(api, fund_id),
        share_class_code=ShareClass.R6,
        net_expense_ratio_bps=45,
        revenue_share_bps=10,
        version=before["version"],
    )

    changed = get_success_data(
        api.post(
            Paths.share_class_change(fund_id),
            share_class_change_payload(ShareClass.INSTITUTIONAL, 40, 10),
            consultant_headers(),
        )
    )
    assert_fields(
        changed,
        share_class_code=ShareClass.INSTITUTIONAL,
        net_expense_ratio_bps=40,
        revenue_share_bps=10,
        menu_status=FundMenuStatus.ACTIVE,
    )
    assert_version_bumped(before, changed)

    # The comparison is always against the class the fund now holds.
    validate_error(
        api.post(
            Paths.share_class_change(fund_id),
            share_class_change_payload(ShareClass.ADMIN, 40, 10),
            consultant_headers(),
        ),
        ApiErrorId.SHARE_CLASS_INELIGIBLE,
    )


def test_a_motion_subject_must_resolve_within_its_declared_type(api, adopted_ips):
    """A fund is not a policy statement, so it cannot be the subject of an
    adoption motion; as a watch-list subject it is accepted, and the derived
    provider role is recorded only for a request-for-proposal award.

    Design: Corner/endpoints/motions_are_a_typed_cross_reference_and_the_subject_kind_is_checked
    """
    ctx = adopted_ips
    fund = create_fund(ctx, "lc_a")
    engagement = create_engagement(ctx)
    meeting = open_meeting(ctx, "2026-08-06", key="typed")

    validate_error(
        api.post(
            Paths.MOTIONS,
            motion_payload(meeting["id"], MotionSubjectType.IPS_ADOPTION, fund["id"]),
            ctx.chair,
        ),
        ApiErrorId.MOTION_SUBJECT_MISMATCH,
    )

    watch = get_success_data(
        api.post(
            Paths.MOTIONS,
            motion_payload(meeting["id"], MotionSubjectType.WATCH_LIST_ACTION, fund["id"]),
            ctx.chair,
        ),
        201,
    )
    assert_common_fields(watch)
    assert_fields(
        watch,
        status=MotionStatus.OPEN,
        subject_type=MotionSubjectType.WATCH_LIST_ACTION,
        subject_id=fund["id"],
        subject_provider_role=ProviderRole.NONE,
        closed_at=None,
    )
    # carried_threshold_pct is copied from the plan, never supplied.
    assert_ratio(watch["carried_threshold_pct"], "0.6000", "carried_threshold_pct")

    award = get_success_data(
        api.post(
            Paths.MOTIONS,
            motion_payload(meeting["id"], MotionSubjectType.RFP_AWARD, engagement["id"]),
            ctx.chair,
        ),
        201,
    )
    assert_fields(
        award,
        subject_type=MotionSubjectType.RFP_AWARD,
        subject_id=engagement["id"],
        subject_provider_role=ProviderRole.RECORDKEEPER,
    )


def test_an_adoption_cannot_consume_a_motion_about_something_else(api, adopted_ips):
    """A carried watch-list motion cannot authorise a policy-statement adoption,
    and the refused adoption leaves both statements where they were.

    Design: Corner/endpoints/motions_are_a_typed_cross_reference_and_the_subject_kind_is_checked
    """
    ctx = adopted_ips
    fund = create_fund(ctx, "lc_a")
    successor = draft_ips(
        api, ctx.plan_id, version_label="IPS-2026-B", effective_date="2026-08-06"
    )
    carried = hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.WATCH_LIST_ACTION,
        fund["id"],
        meeting_date="2026-08-06",
        minutes_doc_ref="MIN-2026-Q0-002",
        key="watch",
    )
    assert_status(carried, MotionStatus.CARRIED)

    refused = api.post(
        Paths.ips_adopt(successor["id"]), ips_adopt_payload(carried["id"]), ctx.chair
    )
    validate_error(refused, ApiErrorId.MOTION_SUBJECT_MISMATCH)

    assert_status(
        get_success_data(api.get(Paths.ips(successor["id"]), auditor_headers())), IpsStatus.DRAFT
    )
    assert_status(
        get_success_data(api.get(Paths.ips(ctx.ips_id), auditor_headers())), IpsStatus.ADOPTED
    )


def test_the_qdia_slot_accepts_only_the_suite_the_committee_moved(api, qdia_candidates):
    """Seating the qualified-default slot needs a carried target-date-selection
    motion naming that very suite; without one, or with a different suite, the
    seating is refused.

    Design: Corner/endpoints/the_qdia_slot_only_accepts_a_suite_the_committee_actually_moved_and_can_never_be_retired
    """
    ctx = qdia_candidates
    qdia_slot = ctx.slot("qdia")
    assert_fields(
        qdia_slot, designation=SlotDesignation.QDIA, status=SlotStatus.EMPTY, current_fund_id=None
    )
    moved = ctx.fund("td_thru")
    other = ctx.fund("td_tie")

    # No committee decision has named any suite yet.
    validate_error(
        api.post(
            Paths.seat_fund(qdia_slot["id"]),
            seat_fund_payload(moved["id"]),
            consultant_headers(),
        ),
        ApiErrorId.QDIA_REQUIRES_TARGET_DATE_SUITE,
    )

    hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.TARGET_DATE_SELECTION,
        moved["id"],
        meeting_date="2026-08-12",
        minutes_doc_ref="MIN-2026-Q0-002",
        key="suite",
    )

    # The motion named one suite, so its equally eligible twin is still refused.
    validate_error(
        api.post(
            Paths.seat_fund(qdia_slot["id"]),
            seat_fund_payload(other["id"]),
            consultant_headers(),
        ),
        ApiErrorId.QDIA_REQUIRES_TARGET_DATE_SUITE,
    )

    seated = seat_fund(ctx, "qdia", "td_thru")
    assert_fields(seated, status=SlotStatus.ACTIVE, current_fund_id=moved["id"])
    assert_fields(
        read_fund(api, moved["id"]),
        menu_status=FundMenuStatus.ACTIVE,
        credit_accrual_status=CreditAccrualStatus.ACCRUING,
        qdia_flag=True,
    )
    assert_fields(read_fund(api, other["id"]), menu_status=FundMenuStatus.CANDIDATE, qdia_flag=False)
    assert_capacity_triple(read_plan(api, ctx.plan_id), occupied=6, reserved=0, available=0)


def test_the_qdia_slot_can_never_be_retired(api, qdia_candidates):
    """The designation alone bars retirement, empty or seated, while an ordinary
    core slot of the same plan retires normally.

    Design: Corner/endpoints/the_qdia_slot_only_accepts_a_suite_the_committee_actually_moved_and_can_never_be_retired
    """
    ctx = qdia_candidates
    qdia_id = ctx.slot("qdia")["id"]

    validate_error(
        api.post(Paths.slot_retire(qdia_id), {}, sponsor_headers()),
        ApiErrorId.QDIA_SLOT_REQUIRED,
    )
    assert_status(read_slot(api, qdia_id), SlotStatus.EMPTY)

    hold_meeting_and_carry_motion(
        ctx,
        MotionSubjectType.TARGET_DATE_SELECTION,
        ctx.fund("td_thru")["id"],
        meeting_date="2026-08-12",
        minutes_doc_ref="MIN-2026-Q0-002",
        key="suite",
    )
    seat_fund(ctx, "qdia", "td_thru")

    validate_error(
        api.post(
            Paths.slot_retire(qdia_id),
            {"reason": "The committee wants to drop the default option."},
            sponsor_headers(),
        ),
        ApiErrorId.QDIA_SLOT_REQUIRED,
    )
    assert_status(read_slot(api, qdia_id), SlotStatus.ACTIVE)

    # A core slot is retirable, so it is the designation that bars the QDIA one.
    retired = get_success_data(
        api.post(
            Paths.slot_retire(ctx.slot("bond")["id"]),
            {"reason": "Consolidating the fixed-income sleeve."},
            sponsor_headers(),
        )
    )
    assert_status(retired, SlotStatus.RETIRED)


def test_the_plan_read_reconciles_the_menu_and_the_credit_ledger(api, executed_replacement):
    """After a full replacement has executed, the plan read still partitions its
    capacity exactly, conserves the asset total across the mapping and keeps the
    credit ledger identity, and reading it is not a mutation.

    Design: Corner/endpoints/the_plan_read_reconciles_the_capacity_triple_and_the_credit_ledger_after_a_full_replacement
    """
    ctx = executed_replacement
    plan = read_plan(api, ctx.plan_id)
    assert_common_fields(plan)
    assert_fields(
        plan,
        menu_slot_capacity=6,
        charter_status=CharterStatus.ADOPTED,
        fiscal_quarter_index=0,
        documented_acceptance_count=3,
        # Hop 3 of PRD 3.7's execution cascade "flips the plan's
        # fee_disclosure_status from COMPLIANT to RESTATEMENT_REQUIRED", and PRD
        # 2.9 makes the posture "RESTRICTED when ... the plan's
        # fee_disclosure_status is RESTATEMENT_REQUIRED" -- recomputed, per the
        # same section, as a side effect of "executing a replacement".  The
        # at-risk ratio is still 0.0000; it is the stale disclosure that restricts.
        menu_posture=MenuPosture.RESTRICTED,
    )
    assert_capacity_triple(plan, occupied=5, reserved=0, available=1)
    assert_ratio(plan["at_risk_slot_ratio"], "0.0000")
    assert_posture_matches_ratio(plan)
    # The mapping moved assets between two funds, so the total is unchanged.
    assert_plan_assets_conserved(plan, 1200000000)
    assert_credit_balance_identity(plan)
    assert_cents(plan["revenue_credit_allocated_cents"], 0, "revenue_credit_allocated_cents")

    slots = [read_slot(api, ctx.slots[key]["id"]) for key in ("lc", "bond", "small", "intl", "tips")]
    assert_at_risk_bookkeeping(plan, slots)
    assert_fields(slots[0], status=SlotStatus.ACTIVE, current_fund_id=ctx.fund("lc_b")["id"])

    outgoing = read_fund(api, ctx.fund("lc_a")["id"])
    incoming = read_fund(api, ctx.fund("lc_b")["id"])
    assert_fields(
        outgoing,
        menu_status=FundMenuStatus.REMOVED,
        credit_accrual_status=CreditAccrualStatus.CLOSED_OUT,
        qdia_flag=False,
    )
    assert_cents(outgoing["plan_assets_cents"], 0, "outgoing plan_assets_cents")
    assert_fields(incoming, menu_status=FundMenuStatus.ACTIVE)
    assert_cents(incoming["plan_assets_cents"], 800000000, "incoming plan_assets_cents")

    proposal = read_proposal(api, ctx.proposals["proposal"]["id"])
    assert_status(proposal, ProposalStatus.EXECUTED)
    assert_cents(proposal["mapped_assets_cents"], 800000000, "mapped_assets_cents")

    again = read_plan(api, ctx.plan_id)
    assert again["version"] == plan["version"], "a read must not bump version"


def test_listing_endpoints_filter_on_derived_state(api, breach_quarter_finalized):
    """Fund and slot listings filter on the states the quarter's scoring derived,
    and every filtered window reports the matching row count.

    Design: Corner/endpoints/listing_endpoints_filter_on_derived_state_and_page_without_losing_rows
    """
    ctx = breach_quarter_finalized
    seated_ids = [ctx.fund(key)["id"] for key in ("lc_a", "bond", "small", "intl", "tips")]
    breaching_ids = [ctx.fund("small")["id"], ctx.fund("intl")["id"]]
    candidate_ids = [ctx.fund("lc_b")["id"], ctx.fund("td_thru")["id"]]

    active, meta = validate_paginated(
        api.get(
            Paths.FUNDS,
            auditor_headers(),
            paginate_params(limit=100, plan_id=ctx.plan_id, menu_status=FundMenuStatus.ACTIVE),
        )
    )
    assert meta["total_count"] == 5, meta
    assert_contains_ids(active, *seated_ids)
    assert_excludes_ids(active, *candidate_ids)

    candidates, meta = validate_paginated(
        api.get(
            Paths.FUNDS,
            auditor_headers(),
            paginate_params(limit=100, plan_id=ctx.plan_id, menu_status=FundMenuStatus.CANDIDATE),
        )
    )
    assert meta["total_count"] == 2, meta
    assert_contains_ids(candidates, *candidate_ids)

    # Two of the five seated funds breached, so they are no longer CLEAR.
    clear, meta = validate_paginated(
        api.get(
            Paths.FUNDS,
            auditor_headers(),
            paginate_params(limit=100, plan_id=ctx.plan_id, watch_status=WatchStatus.CLEAR),
        )
    )
    assert meta["total_count"] == 5, meta
    assert_excludes_ids(clear, *breaching_ids)

    suites, meta = validate_paginated(
        api.get(
            Paths.FUNDS,
            auditor_headers(),
            paginate_params(limit=100, plan_id=ctx.plan_id, is_target_date_suite=True),
        )
    )
    assert meta["total_count"] == 1, meta
    assert_contains_ids(suites, ctx.fund("td_thru")["id"])

    at_risk, meta = validate_paginated(
        api.get(
            Paths.SLOTS,
            auditor_headers(),
            paginate_params(limit=100, plan_id=ctx.plan_id, status=SlotStatus.AT_RISK),
        )
    )
    assert meta["total_count"] == 2, meta
    assert_contains_ids(at_risk, ctx.slot("small")["id"], ctx.slot("intl")["id"])

    healthy, meta = validate_paginated(
        api.get(
            Paths.SLOTS,
            auditor_headers(),
            paginate_params(limit=100, plan_id=ctx.plan_id, status=SlotStatus.ACTIVE),
        )
    )
    assert meta["total_count"] == 3, meta
    assert_excludes_ids(healthy, ctx.slot("small")["id"], ctx.slot("intl")["id"])

    core, meta = validate_paginated(
        api.get(
            Paths.SLOTS,
            auditor_headers(),
            paginate_params(limit=100, plan_id=ctx.plan_id, designation=SlotDesignation.CORE),
        )
    )
    assert meta["total_count"] == 5, meta


def test_paging_a_listing_loses_no_rows(api, breach_quarter_finalized):
    """Three windows over the seven-fund catalogue return every row exactly once
    in created_at order, with limit and offset echoed and has_more true only
    while rows remain; out-of-range window parameters are refused.

    Design: Corner/endpoints/listing_endpoints_filter_on_derived_state_and_page_without_losing_rows
    """
    ctx = breach_quarter_finalized
    walked = []
    for offset, expected_rows, expected_more in ((0, 3, True), (3, 3, True), (6, 1, False)):
        rows, meta = validate_paginated(
            api.get(
                Paths.FUNDS,
                auditor_headers(),
                paginate_params(limit=3, offset=offset, plan_id=ctx.plan_id),
            )
        )
        assert len(rows) == expected_rows, (offset, ids_of(rows))
        assert meta["limit"] == 3 and meta["offset"] == offset, meta
        assert meta["total_count"] == 7, meta
        assert meta["has_more"] is expected_more, meta
        assert_ordered_by(rows, "created_at")
        walked.extend(ids_of(rows))

    assert len(walked) == 7, walked
    assert len(set(walked)) == 7, "a paged walk returned a row twice"

    whole, meta = validate_paginated(
        api.get(Paths.FUNDS, auditor_headers(), paginate_params(plan_id=ctx.plan_id))
    )
    assert meta["limit"] == 10 and meta["offset"] == 0, meta
    assert meta["total_count"] == 7 and meta["has_more"] is False, meta
    assert set(ids_of(whole)) == set(walked)
    assert_ordered_by(whole, "created_at")

    for bad in (paginate_params(limit=0), paginate_params(limit=101), paginate_params(offset=-1)):
        bad["plan_id"] = ctx.plan_id
        validate_error(
            api.get(Paths.FUNDS, auditor_headers(), bad), ApiErrorId.INVALID_REQUEST
        )
