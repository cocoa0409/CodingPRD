"""Endpoint mechanics: partial writes, computed reads, links and page windows."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import ConsultingApiClient
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_economics_view,
    assert_fields,
    assert_ids_equal,
    assert_money,
    assert_pagination_meta,
    assert_two_dp,
)

SECOND_CLIENT_CODE = "NWR004"
MISMATCHED_PRACTICE_CODE = "RISK"


def test_the_economics_read_is_a_pure_projection_of_the_stored_ledger(
    api: ConsultingApiClient,
) -> None:
    """Six keys, twice the same answer, and no version movement on the row.

    PRD 3.7: "Engagement economics are recomputed after every mutation that can
    move them — an approved timesheet line, a reversed timesheet line, a
    deliverable reaching `ACCEPTED`, an approved change request, and a rescinded
    change request — and the same figures are also available as a read-only
    computed view exposing `hours_burn_pct`, `completion_pct`,
    `progress_variance_pct`, `projected_cost_cents`, `projected_margin_pct` and
    `economics_state`."

    Design: Corner/endpoints/economics_computed_read_matches_the_stored_ledger
    """
    sc = fx.build_burned_engagement(api)
    before = fx.read_engagement(sc)
    assert_two_dp(before, "approved_hours_burned", 100.00)
    assert_money(before, "burned_cost_cents", 6200000)

    first = get_success_data(api.get_economics(sc.engagement_id, sc.manager))
    get_success_data(api.get_engagement(sc.engagement_id, sc.partner))
    second = get_success_data(api.get_economics(sc.engagement_id, sc.leadership))

    for view in (first, second):
        assert_economics_view(
            view,
            hours_burn_pct=49.81,
            completion_pct=40.00,
            progress_variance_pct=9.81,
            projected_cost_cents=9625500,
            projected_margin_pct=6.37,
            economics_state=C.ECONOMICS_AT_RISK,
        )

    after = fx.read_engagement(sc)
    assert_fields(after, version=before["version"])
    assert_two_dp(after, "contracted_hours", C.CANON_TOTAL_ESTIMATED_HOURS)
    assert_money(after, "contracted_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)


def test_the_waiver_flag_turns_one_overlap_into_a_cleared_position(
    api: ConsultingApiClient,
) -> None:
    """Identical screened codes, two conflict positions, two qualification answers.

    PRD 3.2: "The submitted list is persisted verbatim onto the pursuit's
    `screened_adverse_party_codes`, and `conflict_status` is resolved from the
    overlap between that list and the client's own `adverse_party_codes`: an
    overlap of two or more codes writes `BLOCKED`, an overlap of exactly one code
    with `waiver_obtained` true writes `CLEARED_WITH_WAIVER`, an overlap of
    exactly one code with `waiver_obtained` false or absent writes
    `WAIVER_REQUIRED`, and no overlap at all writes `CLEAR`."

    Design: Corner/endpoints/conflict_check_waiver_flag_selects_the_cleared_variant
    """
    sc = fx.build_screening_pursuit(api)
    overlapping = list(C.SEED_CLIENT_ADVERSE_PARTY_CODES)

    unwaived = fx.screen_conflicts(sc, screened=overlapping)
    assert_fields(
        unwaived,
        conflict_status="WAIVER_REQUIRED",
        screened_adverse_party_codes=overlapping,
    )
    fx.verify_budget(sc, C.SEED_VERIFIED_BUDGET_CENTS)
    validate_error(
        api.qualify(sc.opportunity_id, {}, sc.partner), E.ERR_CONFLICT_NOT_CLEARED
    )

    waived = fx.screen_conflicts(sc, screened=overlapping, waiver_obtained=True)
    assert_fields(
        waived,
        conflict_status="CLEARED_WITH_WAIVER",
        screened_adverse_party_codes=overlapping,
        status="SCREENING",
    )

    decided = get_success_data(api.qualify(sc.opportunity_id, {}, sc.partner))
    assert_fields(decided, status="QUALIFIED")
    assert_two_dp(decided, "qualification_score_verified", 68.00)


def test_a_deliverable_patch_touches_only_the_field_it_carries(
    api: ConsultingApiClient,
) -> None:
    """One field moves, six stand still, and the next baseline re-prices around it.

    PRD 3.3: "Editing accepts any subset of `name`, `primary_grade`,
    `effort_hours_estimate`, `completion_weight_pct`, `acceptance_criteria`,
    `planned_start_date`, `planned_end_date` and `depends_on_deliverable_id`, and
    advances the deliverable's `version`."

    PRD 3.4: "That total then selects a volume discount, stored as
    `scope_discount_pct`, from three tiers whose lower bounds are inclusive: a
    total below 200 hours earns no discount at all, that is 0.00; a total of 200
    hours or more but below 500 hours earns 0.05; and a total of 500 hours or more
    earns 0.10."

    Design: Corner/endpoints/deliverable_patch_updates_only_the_supplied_fields
    """
    sc = fx.build_scoped_pursuit(api)
    before = fx.read_deliverable(sc, sc.d1_id)

    get_success_data(
        api.patch_deliverable(sc.d1_id, {"effort_hours_estimate": 90.0}, sc.manager)
    )

    after = fx.read_deliverable(sc, sc.d1_id)
    assert_two_dp(after, "effort_hours_estimate", 90.00)
    assert_fields(
        after,
        version=before["version"] + 1,
        name=C.SEED_D1["name"],
        primary_grade=C.GRADE_CONSULTANT,
        acceptance_criteria=C.SEED_D1["acceptance_criteria"],
        planned_start_date=C.SEED_D1["planned_start_date"],
        planned_end_date=C.SEED_D1["planned_end_date"],
        depends_on_deliverable_id=None,
    )
    assert_two_dp(after, "completion_weight_pct", 40.00)

    baselined = fx.baseline_scope(sc)

    # 90.00 + 80.50 falls below the 200-hour tier floor
    assert_two_dp(baselined, "total_estimated_hours", 170.50)
    assert_two_dp(baselined, "scope_discount_pct", C.SCOPE_DISCOUNT_TIER_NONE)
    assert_money(fx.read_deliverable(sc, sc.d1_id), "line_cost_cents", 3285000)
    assert_money(fx.read_deliverable(sc, sc.d2_id), "line_cost_cents", 4628750)
    assert_money(baselined, "baseline_effort_cost_cents", 7913750)


def test_the_lead_link_checks_the_path_row_before_the_body_row(
    api: ConsultingApiClient,
) -> None:
    """Two unknown ids in one call, and the path one is the error reported.

    PRD 2.10: "Existence checks follow — path identifiers first, then body
    foreign keys, both at HTTP 404."

    PRD 3.3: "A successful assignment writes `lead_consultant_id`, advances the
    deliverable's `version`, and increments the consultant's
    `active_lead_deliverable_count` while advancing that consultant's `version`
    too."

    Design: Corner/endpoints/assign_lead_requires_both_rows_to_exist
    """
    sc = fx.build_scoped_pursuit(api)

    validate_error(
        api.assign_lead(
            C.NON_EXISTENT_ID,
            {"lead_consultant_id": C.NON_EXISTENT_ID},
            sc.manager,
        ),
        E.ERR_DELIVERABLE_NOT_FOUND,
    )
    validate_error(
        api.assign_lead(
            sc.d1_id, {"lead_consultant_id": C.NON_EXISTENT_ID}, sc.manager
        ),
        E.ERR_CONSULTANT_NOT_FOUND,
    )
    assert_fields(
        fx.read_consultant(sc, sc.consultant_id), active_lead_deliverable_count=0
    )

    assigned = fx.assign_lead(sc, sc.d1_id, sc.consultant_id)

    assert_fields(assigned, lead_consultant_id=sc.consultant_id)
    assert_fields(
        fx.read_consultant(sc, sc.consultant_id), active_lead_deliverable_count=1
    )


def test_mobilisation_staffs_the_manager_and_happens_exactly_once(
    api: ConsultingApiClient,
) -> None:
    """An out-of-practice manager is refused, the right one activates delivery.

    PRD 3.6: "The payload carries a single `engagement_manager_consultant_id`;
    the named consultant must exist, otherwise `ERR_CONSULTANT_NOT_FOUND`, and
    that consultant's `practice_code` must equal the pursuit's
    `requested_practice_code`, otherwise `ERR_CONSULTANT_PRACTICE_MISMATCH`."

    PRD 3.6: "Mobilising an engagement twice is refused with
    `ERR_ENGAGEMENT_STATE_INVALID`."

    Design: Corner/endpoints/mobilize_writes_the_manager_and_activates_delivery
    """
    sc = fx.build_signed_engagement(api)
    assert_fields(
        fx.read_engagement(sc),
        delivery_state=C.DELIVERY_MOBILIZING,
        engagement_manager_consultant_id=None,
    )
    outsider_id = fx.create_consultant(
        api,
        name="Z. Iqbal",
        grade=C.GRADE_MANAGER,
        practice_code=MISMATCHED_PRACTICE_CODE,
        cost_rate_cents_per_hour=C.SEED_MANAGER_COST_RATE,
    )["id"]

    validate_error(
        api.mobilize(
            sc.engagement_id,
            {"engagement_manager_consultant_id": outsider_id},
            sc.partner,
        ),
        E.ERR_CONSULTANT_PRACTICE_MISMATCH,
    )
    assert_fields(fx.read_engagement(sc), delivery_state=C.DELIVERY_MOBILIZING)

    mobilised = fx.mobilize(sc)

    assert_fields(
        mobilised,
        delivery_state=C.DELIVERY_ACTIVE,
        engagement_manager_consultant_id=sc.manager_id,
        economics_state=C.ECONOMICS_ON_TRACK,
    )
    assert_money(mobilised, "original_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)
    assert_money(mobilised, "contracted_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)
    assert_two_dp(mobilised, "contracted_hours", C.CANON_TOTAL_ESTIMATED_HOURS)

    validate_error(
        api.mobilize(
            sc.engagement_id,
            {"engagement_manager_consultant_id": sc.manager_id},
            sc.partner,
        ),
        E.ERR_ENGAGEMENT_STATE_INVALID,
    )


def test_a_replacement_statement_of_work_supersedes_the_first(
    api: ConsultingApiClient,
) -> None:
    """The old row is retired with its price intact and the new one points back.

    PRD 3.5: "When a prior non-terminal statement of work already exists for the
    same pursuit — one sitting in `DRAFT`, `INTERNAL_REVIEW`, `CLIENT_REVIEW` or
    `REVISION_REQUESTED` — that earlier row is written to `SUPERSEDED`, its own
    `version` advances, and the new row's `supersedes_sow_id` is set to the
    superseded row's identifier."

    PRD 3.5: "A pursuit sitting at `SCOPE_BASELINED` moves `SCOPE_BASELINED →
    SOW_ISSUED`; a pursuit already at `SOW_ISSUED` stays there but still has its
    `version` incremented, which is precisely the movement the stale-version
    guard is there to expose."

    PRD 3.5: "A fresh document begins in `DRAFT` with `revision_round` at 0,
    `signature_name` null and `signed_at` null."

    Design: Corner/endpoints/second_sow_supersedes_the_prior_one
    """
    sc = fx.build_sow_draft(api)
    first_id = sc.sow_id
    issued_version = fx.read_opportunity(sc)["version"]

    replacement = get_success_data(
        api.create_sow(
            F.sow_payload(
                sc.opportunity_id,
                issued_version,
                pricing_model=C.PRICING_TIME_AND_MATERIALS,
                acceptance_summary="Monthly invoice acceptance against the ceiling",
            ),
            sc.partner,
        )
    )

    assert_fields(
        replacement,
        status="DRAFT",
        supersedes_sow_id=first_id,
        risk_score=C.CANON_TNM_RISK_SCORE,
        revision_round=0,
        signature_name=None,
        signed_at=None,
    )
    assert_two_dp(replacement, "risk_premium_pct", 0.12)
    assert_money(replacement, "quoted_fee_cents", C.CANON_TNM_QUOTED_CENTS)
    assert_money(replacement, "not_to_exceed_cents", C.CANON_TNM_QUOTED_CENTS)

    superseded = get_success_data(api.get_sow(first_id, sc.partner))
    assert_fields(superseded, status="SUPERSEDED", supersedes_sow_id=None)
    assert_money(
        superseded, "quoted_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS
    )

    opportunity = fx.read_opportunity(sc)
    assert_fields(opportunity, status="SOW_ISSUED")
    assert_two_dp(opportunity, "total_estimated_hours", C.CANON_TOTAL_ESTIMATED_HOURS)
    _, meta = validate_paginated(
        api.list_sows(sc.partner, {"opportunity_id": sc.opportunity_id})
    )
    assert_pagination_meta(meta, total_count=2, has_more=False)


def test_a_filter_a_page_window_and_the_created_at_order_compose(
    api: ConsultingApiClient,
) -> None:
    """Four pursuits, two filters and two page windows over the same rows.

    PRD 2.3: "List results are ordered by `created_at` ascending unless a
    specific endpoint narrative says otherwise."

    PRD 2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows
    matching the supplied filters before pagination is applied and `has_more` is
    true when rows remain beyond the current page."

    Design: Corner/endpoints/list_filter_sort_and_offset_interact_consistently
    """
    sc = fx.build_qualified_pursuit(api)
    # A distinct clock instant per row, so created_at ascending is unambiguous
    fx.set_clock(api, "2026-08-04T09:00:00Z")
    first_screening = fx.build_sibling_screening_pursuit(sc).opportunity_id
    fx.set_clock(api, "2026-08-05T09:00:00Z")
    second_screening = fx.build_sibling_screening_pursuit(sc).opportunity_id
    fx.set_clock(api, "2026-08-06T09:00:00Z")
    other_client_id = fx.create_client(
        api, client_code=SECOND_CLIENT_CODE, name="Southwind Foods"
    )["id"]
    outsider = get_success_data(
        api.create_opportunity(
            F.opportunity_payload(other_client_id, sc.partner_id, sc.manager_id),
            sc.partner,
        )
    )

    page_one, meta_one = validate_paginated(
        api.list_opportunities(
            sc.partner, {"client_id": sc.client_id, "limit": 2, "offset": 0}
        )
    )
    assert_ids_equal(page_one, [sc.opportunity_id, first_screening])
    assert_pagination_meta(meta_one, total_count=3, has_more=True)

    page_two, meta_two = validate_paginated(
        api.list_opportunities(
            sc.partner, {"client_id": sc.client_id, "limit": 2, "offset": 2}
        )
    )
    assert_ids_equal(page_two, [second_screening])
    assert_pagination_meta(meta_two, total_count=3, has_more=False)

    narrowed, meta_three = validate_paginated(
        api.list_opportunities(
            sc.partner,
            {
                "client_id": sc.client_id,
                "status": "SCREENING",
                "limit": 2,
                "offset": 0,
            },
        )
    )
    assert_ids_equal(narrowed, [first_screening, second_screening])
    assert_pagination_meta(meta_three, total_count=2, has_more=False)
    for rows in (page_one, page_two, narrowed):
        assert outsider["id"] not in {row["id"] for row in rows}
