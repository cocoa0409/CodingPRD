"""Version pinning, per-write version movement and one threshold at its floor."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ConsultingApiClient
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_economics_view,
    assert_fields,
    assert_money,
    assert_pagination_meta,
    assert_two_dp,
)

LATE_CLOCK = "2026-09-21T09:00:00Z"
THIRD_WEEK = "2026-09-18"
SMALL_CHANGE_SUMMARY = "One extra scenario"
TNM_ACCEPTANCE_SUMMARY = "Monthly invoice acceptance"


def test_a_replayed_pursuit_version_cannot_draft_a_second_document(
    api: ConsultingApiClient,
) -> None:
    """Issuing the first document moves the pin the second one is holding.

    PRD 2.7: "`POST /consulting/sows` requires a non-optional
    `expected_opportunity_version` field carrying the client's last observed
    `version` of the target `Opportunity`. If that value does not equal the
    opportunity's current `version`, the create is rejected with
    `ERR_STALE_OPPORTUNITY_VERSION` (HTTP 412)."

    PRD 3.5: "When a prior non-terminal statement of work already exists for the
    same pursuit — one sitting in `DRAFT`, `INTERNAL_REVIEW`, `CLIENT_REVIEW` or
    `REVISION_REQUESTED` — that earlier row is written to `SUPERSEDED`, its own
    `version` advances, and the new row's `supersedes_sow_id` is set to the
    superseded row's identifier."

    Design: Corner/cross_cutting_complexity_layers/sow_create_rejects_a_stale_opportunity_version
    """
    sc = fx.build_sow_draft(api)
    first_id = sc.sow_id
    # The version the first draft pinned, now one behind the pursuit
    stale_version = sc.opportunity_version

    validate_error(
        api.create_sow(
            F.sow_payload(
                sc.opportunity_id,
                stale_version,
                pricing_model=C.PRICING_TIME_AND_MATERIALS,
                acceptance_summary=TNM_ACCEPTANCE_SUMMARY,
            ),
            sc.partner,
        ),
        E.ERR_STALE_OPPORTUNITY_VERSION,
    )

    assert_fields(fx.read_sow(sc), status="DRAFT")
    _, meta = validate_paginated(
        api.list_sows(sc.partner, {"opportunity_id": sc.opportunity_id})
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)

    fresh_version = fx.read_opportunity(sc)["version"]
    assert fresh_version == stale_version + 1

    second = validate_success(
        api.create_sow(
            F.sow_payload(
                sc.opportunity_id,
                fresh_version,
                pricing_model=C.PRICING_TIME_AND_MATERIALS,
                acceptance_summary=TNM_ACCEPTANCE_SUMMARY,
            ),
            sc.partner,
        ),
        201,
    )

    assert_fields(second, supersedes_sow_id=first_id, status="DRAFT")
    assert_money(second, "quoted_fee_cents", C.CANON_TNM_QUOTED_CENTS)
    assert_fields(get_success_data(api.get_sow(first_id, sc.partner)), status="SUPERSEDED")


def test_an_approved_timesheet_line_invalidates_a_held_engagement_version(
    api: ConsultingApiClient,
) -> None:
    """Nothing is wrong with the body; the row simply moved underneath it.

    PRD 2.7: "`POST /consulting/change-requests` requires a non-optional
    `expected_engagement_version` field carrying the client's last observed
    `version` of the target `Engagement`. A mismatch with the engagement's
    current `version` is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP
    412)."

    PRD 2.4: "`version` is an integer that starts at 1 when the row is created
    and is incremented by exactly 1 on every mutation of that row, including
    mutations that a cascade from another entity performs rather than a direct
    client write."

    Design: Corner/cross_cutting_complexity_layers/change_request_create_rejects_a_stale_engagement_version
    """
    sc = fx.build_started_engagement(api)
    held_version = fx.engagement_version(sc)

    fx.log_and_approve_time(sc, 40.0, C.SEED_WEEK_1)
    engagement = fx.read_engagement(sc)
    assert_two_dp(engagement, "approved_hours_burned", 40.00)
    assert_money(engagement, "burned_cost_cents", 2480000)
    assert engagement["version"] > held_version

    validate_error(
        api.create_change_request(
            F.change_request_payload(
                sc.engagement_id,
                held_version,
                summary=SMALL_CHANGE_SUMMARY,
                added_hours=10.0,
                requested_schedule_days=5,
            ),
            sc.manager,
        ),
        E.ERR_STALE_ENGAGEMENT_VERSION,
    )
    _, meta = validate_paginated(
        api.list_change_requests(sc.manager, {"engagement_id": sc.engagement_id})
    )
    assert_pagination_meta(meta, total_count=0, has_more=False)

    request = fx.raise_change_request(
        sc, summary=SMALL_CHANGE_SUMMARY, added_hours=10.0, requested_schedule_days=5
    )
    assert_fields(request, status=C.CR_DRAFT, fee_delta_cents=None)

    assessed = fx.assess_change_request(sc, request["id"])

    # 10.00 * 21500 * 0.95 = 204250, loaded by the 1.20 risk factor
    assert_money(assessed, "fee_delta_cents", 245100)
    assert_two_dp(assessed, "cumulative_change_pct_at_assessment", 2.38)
    assert_fields(assessed, routing=C.ROUTING_CLIENT_ONLY)


def test_three_writes_move_the_version_three_times_and_reads_move_it_never(
    api: ConsultingApiClient,
) -> None:
    """Two interleaved reads sit between the writes and change nothing.

    PRD 2.4: "`version` is an integer that starts at 1 when the row is created
    and is incremented by exactly 1 on every mutation of that row, including
    mutations that a cascade from another entity performs rather than a direct
    client write."

    PRD 3.3: "A successful assignment writes `lead_consultant_id`, advances the
    deliverable's `version`, and increments the consultant's
    `active_lead_deliverable_count` while advancing that consultant's `version`
    too."

    PRD 3.6: "Every one of these transitions advances the deliverable's `version`
    by 1."

    Design: Corner/cross_cutting_complexity_layers/version_increments_once_per_write_and_never_on_reads
    """
    # Three writes that are all legitimate on the same row in one state: the
    # scope is frozen by now, so the trio is assign-lead and two transitions.
    sc = fx.build_active_engagement(api)
    start = fx.read_deliverable(sc, sc.d1_id)
    consultant_before = fx.read_consultant(sc, sc.consultant_id)

    fx.assign_lead(sc, sc.d1_id, sc.consultant_id)
    first_read = fx.read_deliverable(sc, sc.d1_id)
    second_read = fx.read_deliverable(sc, sc.d1_id)

    assert_fields(first_read, version=start["version"] + 1)
    assert_fields(
        second_read,
        version=start["version"] + 1,
        updated_at=first_read["updated_at"],
    )
    assert_fields(
        fx.read_consultant(sc, sc.consultant_id),
        version=consultant_before["version"] + 1,
        active_lead_deliverable_count=1,
    )

    fx.set_status(sc, sc.d1_id, C.DELIVERABLE_IN_PROGRESS)
    third_read = fx.read_deliverable(sc, sc.d1_id)
    fourth_read = fx.read_deliverable(sc, sc.d1_id)

    assert_fields(third_read, version=start["version"] + 2)
    assert_fields(
        fourth_read, version=start["version"] + 2, status=C.DELIVERABLE_IN_PROGRESS
    )

    fx.set_status(sc, sc.d1_id, C.DELIVERABLE_SUBMITTED)

    final = fx.read_deliverable(sc, sc.d1_id)
    assert_fields(
        final,
        version=start["version"] + 3,
        status=C.DELIVERABLE_SUBMITTED,
        id=start["id"],
        created_at=start["created_at"],
    )


def test_the_overrun_band_opens_at_exactly_thirty_and_not_a_hundredth_below(
    api: ConsultingApiClient,
) -> None:
    """29.99 is still AT_RISK and silent; 30.00 flips the state and escalates.

    PRD 3.7: "The engagement is `OVERRUN` when `progress_variance_pct` is 30.00
    or greater, or when `projected_margin_pct` is below 0.00. Failing that, it is
    `AT_RISK` when `progress_variance_pct` is 15.00 or greater, or when
    `projected_margin_pct` is below 15.00."

    PRD 3.7: "Whenever a recompute lands on `OVERRUN` from a state that was not
    already `OVERRUN` — whether `ON_TRACK → OVERRUN` in a single step or
    `AT_RISK → OVERRUN` — the system raises exactly one risk escalation on the
    engagement with `source` set to `ECONOMICS`, `severity` set to `HIGH`,
    handling status `OPEN`, and an `opened_reason` naming the threshold that was
    breached."

    Design: Corner/cross_cutting_complexity_layers/instantaneous_variance_threshold_trips_at_exactly_thirty
    """
    sc = fx.build_started_engagement(api, clock=LATE_CLOCK)
    fx.log_and_approve_time(sc, 30.0, C.SEED_WEEK_1)
    fx.log_and_approve_time(sc, 30.2, C.SEED_WEEK_2)

    # 60.20 / 200.75 = 29.9875..., which rounds to 29.99 and stays below the bar
    assert_economics_view(
        get_success_data(api.get_economics(sc.engagement_id, sc.partner)),
        hours_burn_pct=29.99,
        completion_pct=0.00,
        progress_variance_pct=29.99,
        projected_cost_cents=8511100,
        projected_margin_pct=17.21,
        economics_state=C.ECONOMICS_AT_RISK,
    )
    assert fx.list_escalations(sc) == []

    fx.log_and_approve_time(sc, 0.03, THIRD_WEEK)

    # 60.23 / 200.75 = 30.0025..., which rounds to exactly the inclusive floor
    assert_economics_view(
        get_success_data(api.get_economics(sc.engagement_id, sc.partner)),
        hours_burn_pct=30.00,
        completion_pct=0.00,
        progress_variance_pct=30.00,
        projected_cost_cents=8511940,
        projected_margin_pct=17.20,
        economics_state=C.ECONOMICS_OVERRUN,
    )

    escalations = fx.list_escalations(sc)
    assert len(escalations) == 1
    assert_fields(
        escalations[0],
        source=C.ESCALATION_SOURCE_ECONOMICS,
        severity=C.SEVERITY_HIGH,
        status=C.ESCALATION_OPEN,
    )
    assert_fields(
        fx.read_engagement(sc),
        leadership_review_required=True,
        delivery_state=C.DELIVERY_ACTIVE,
        suspended_deliverable_count=0,
    )
