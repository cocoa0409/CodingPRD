"""
Endpoint behaviour: the three-condition reissue gate, the clock surface every
role shares, the junction row that is findable from both sides, an analytics
read over a window that contains nothing, and the composed citation filters.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_ENCOUNTER_ALREADY_CITED,
    ERR_REISSUE_WINDOW_CLOSED,
)
from test_helpers.assertions import (
    assert_citation_money_identity,
    assert_immutable_record,
    assert_instant_equals,
    assert_rate_equals,
    ids_of,
)
from test_helpers.constants import (
    ADJUDICATION_DISMISSED,
    ADJUDICATION_ISSUED,
    CLOCK_EPOCH,
    DECISION_DISMISS,
    DISMISSAL_REASON_PROCEDURAL_DEFECT,
    GROUP_BY_DEMOGRAPHIC_BAND,
    GROUP_BY_GEO_TRACT,
    SETTLEMENT_OUTSTANDING,
    SETTLEMENT_WRITTEN_OFF,
)
from test_helpers.fixtures import OBSERVATION_AT
from test_helpers.test_users import (
    ANALYST_HEADERS,
    HEARING_OFFICER_HEADERS,
    PLANNER_HEADERS,
    UNBOUND_RIDER_HEADERS,
)

FIFTEEN_DAYS_ON = "2026-08-20T09:00:00Z"
FOURTEEN_DAYS_ON = "2026-08-19T09:00:00Z"
INHERITED_CONTEST_DEADLINE = "2026-09-04T09:00:00Z"
RIDER_CLOCK_INSTANT = "2026-08-03T12:30:00Z"
ANALYST_CLOCK_INSTANT = "2026-08-04T00:00:00Z"
REPORT_WINDOW_END = "2026-09-01T00:00:00Z"


def test_reissue_is_refused_a_day_late_and_permitted_on_the_inclusive_edge(api):
    """
    The window is 14 days: the logical clock must be at or before the dismissed
    citation's `dismissed_at` plus 14 days, and a later request is refused with
    `ERR_REISSUE_WINDOW_CLOSED`. ... The new record carries
    `reissued_from_citation_id` pointing at the citation it replaces ... and
    inherits the original citation's `issued_at` ... `contest_deadline_at` is
    consequently 30 days after that inherited instant.

    Design: Corner/endpoints/reissue_is_allowed_only_inside_the_window_after_a_procedural_defect_dismissal
    """
    chain = fixtures.build_citation_chain(api)
    citation = chain["citation"]
    encounter_id = chain["encounter"]["id"]
    hearing = fixtures.contest(api, citation["id"], chain["rider"]["id"])
    fixtures.decide_hearing(
        api,
        hearing["id"],
        DECISION_DISMISS,
        dismissal_reason_code=DISMISSAL_REASON_PROCEDURAL_DEFECT,
    )

    dismissed = fixtures.read_citation(api, citation["id"])
    assert dismissed["adjudication_status"] == ADJUDICATION_DISMISSED
    assert dismissed["dismissal_reason_code"] == DISMISSAL_REASON_PROCEDURAL_DEFECT
    assert_instant_equals(dismissed["dismissed_at"], OBSERVATION_AT, "citation.dismissed_at")
    assert dismissed["settlement_status"] == SETTLEMENT_WRITTEN_OFF

    fixtures.move_clock(api, FIFTEEN_DAYS_ON)
    validate_error(
        api.reissue_citation(citation["id"], PLANNER_HEADERS),
        ERR_REISSUE_WINDOW_CLOSED,
        422,
    )

    fixtures.move_clock(api, FOURTEEN_DAYS_ON)
    reissued = validate_success(api.reissue_citation(citation["id"], PLANNER_HEADERS), 201)

    assert reissued["reissued_from_citation_id"] == citation["id"]
    assert reissued["encounter_id"] == encounter_id
    assert reissued["adjudication_status"] == ADJUDICATION_ISSUED
    assert reissued["settlement_status"] == SETTLEMENT_OUTSTANDING
    assert reissued["offense_sequence"] == 1
    assert reissued["assessed_penalty_cents"] == 9000
    assert reissued["admin_fee_cents"] == 720
    assert reissued["total_due_cents"] == 9720
    assert_citation_money_identity(reissued)
    assert_instant_equals(reissued["issued_at"], OBSERVATION_AT, "reissue.issued_at")
    assert_instant_equals(
        reissued["contest_deadline_at"],
        INHERITED_CONTEST_DEADLINE,
        "reissue.contest_deadline_at",
    )

    # One encounter, one live citation: the reissue now holds that slot itself.
    validate_error(
        api.reissue_citation(citation["id"], PLANNER_HEADERS),
        ERR_ENCOUNTER_ALREADY_CITED,
        409,
    )

    rows, meta = validate_paginated(
        api.list_citations(
            PLANNER_HEADERS, {"reissued_from_citation_id": citation["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [reissued["id"]]

    assert fixtures.read_rider(api, chain["rider"]["id"])["prior_citation_count"] == 1


def test_any_role_may_move_the_clock_and_the_next_write_is_stamped_from_it(api):
    """
    Any role may move the clock by supplying a `to_iso8601` instant; the response
    echoes the value now in effect as `current_utc`.  Moving the clock advances or
    rewinds it to exactly the supplied instant and modifies no business record
    whatsoever.

    Design: Corner/endpoints/the_logical_clock_endpoint_is_open_to_every_role_and_stamps_created_at
    """
    fixtures.move_clock(api, CLOCK_EPOCH)

    by_rider = validate_success(
        api.set_clock(factories.clock_payload(RIDER_CLOCK_INSTANT), UNBOUND_RIDER_HEADERS)
    )
    assert_instant_equals(by_rider["current_utc"], RIDER_CLOCK_INSTANT, "clock.current_utc")

    zone = validate_success(
        api.create_fare_zone(
            factories.fare_zone_payload(
                zone_code="ZN1", name="Downtown POP Zone", required_sign_count=10
            ),
            PLANNER_HEADERS,
        ),
        201,
    )
    assert_instant_equals(zone["created_at"], RIDER_CLOCK_INSTANT, "zone.created_at")
    assert_instant_equals(zone["updated_at"], RIDER_CLOCK_INSTANT, "zone.updated_at")

    by_analyst = validate_success(
        api.set_clock(factories.clock_payload(ANALYST_CLOCK_INSTANT), ANALYST_HEADERS)
    )
    assert_instant_equals(by_analyst["current_utc"], ANALYST_CLOCK_INSTANT, "clock.current_utc")

    line = validate_success(
        api.create_transit_line(factories.transit_line_payload(), PLANNER_HEADERS), 201
    )
    assert_instant_equals(line["created_at"], ANALYST_CLOCK_INSTANT, "line.created_at")

    # The clock is process-wide: the zone written before the second move keeps
    # the instant that was in effect when it was written.
    assert_instant_equals(
        fixtures.read_zone(api, zone["id"])["created_at"],
        RIDER_CLOCK_INSTANT,
        "zone.created_at",
    )


def test_the_junction_row_is_findable_by_id_by_zone_and_by_line(api):
    """
    Attaching a line to a zone creates an immutable junction record naming the
    `zone_id` ... the `line_id` ... a `platform_segment_count` of at least 1 ...
    and an `effective_from` instant from which the line becomes enforceable
    inside the zone, inclusive of that instant.

    Design: Corner/endpoints/zone_line_assignment_links_two_existing_rows_and_is_findable_from_both_sides
    """
    fixtures.move_clock(api, CLOCK_EPOCH)
    zone = fixtures.register_zone(
        api,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
        max_concurrent_deployments=None,
    )
    line = fixtures.register_line(api)

    assignment = validate_success(
        api.create_zone_line_assignment(
            factories.zone_line_assignment_payload(zone["id"], line["id"]),
            PLANNER_HEADERS,
        ),
        201,
    )
    assert assignment["zone_id"] == zone["id"]
    assert assignment["line_id"] == line["id"]
    assert assignment["platform_segment_count"] == 4
    assert_instant_equals(
        assignment["effective_from"], CLOCK_EPOCH, "assignment.effective_from"
    )
    assert_immutable_record(assignment, "assignment")

    by_id = validate_success(api.get_zone_line_assignment(assignment["id"], ANALYST_HEADERS))
    assert by_id["id"] == assignment["id"]
    assert by_id["zone_id"] == zone["id"]
    assert by_id["line_id"] == line["id"]

    for params in ({"zone_id": zone["id"]}, {"line_id": line["id"]}):
        rows, meta = validate_paginated(
            api.list_zone_line_assignments(ANALYST_HEADERS, params)
        )
        assert meta["total_count"] == 1
        assert ids_of(rows) == [assignment["id"]]


def test_an_equity_window_holding_no_encounter_reports_zeroes_not_an_error(api):
    """
    An empty encounter pool is a legitimate answer rather than an error: the
    report returns `groups_evaluated` of 0, a `systemwide_citation_rate` of 0.0000
    and a `disparity_index` of 0.0000.  Both echo `window_start` and `window_end`
    back in their payloads.

    Design: Corner/endpoints/equity_report_over_an_empty_window_returns_zeroed_aggregates
    """
    fixtures.move_clock(api, CLOCK_EPOCH)
    fixtures.register_zone(
        api,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
        max_concurrent_deployments=None,
    )
    fixtures.register_rider(api)

    for group_by, headers in (
        (GROUP_BY_DEMOGRAPHIC_BAND, ANALYST_HEADERS),
        (GROUP_BY_GEO_TRACT, PLANNER_HEADERS),
    ):
        params = factories.equity_report_params(
            window_start=CLOCK_EPOCH, window_end=REPORT_WINDOW_END, group_by=group_by
        )
        report = validate_success(api.get_equity_distribution_report(params, headers))

        assert_instant_equals(report["window_start"], CLOCK_EPOCH, "report.window_start")
        assert_instant_equals(report["window_end"], REPORT_WINDOW_END, "report.window_end")
        assert report["group_by"] == group_by
        assert report["encounter_pool_count"] == 0
        assert report["citation_count"] == 0
        assert report["groups_evaluated"] == 0
        assert report["groups"] == []
        assert_rate_equals(
            report["systemwide_citation_rate"], 0.0000, "report.systemwide_citation_rate"
        )
        assert_rate_equals(report["disparity_index"], 0.0000, "report.disparity_index")


def test_the_citation_list_applies_each_filter_it_is_handed(api):
    """
    Beyond pagination, several list surfaces accept filters that narrow the
    collection before paging: ... citations by `rider_id`, `zone_id`,
    `encounter_id`, `issuing_inspector_id`, `reissued_from_citation_id`,
    `adjudication_status` and `settlement_status`.

    Design: Corner/endpoints/citation_list_filters_compose_with_pagination
    """
    chain = fixtures.build_citation_chain(api)
    citation_id = chain["citation"]["id"]
    rider_id = chain["rider"]["id"]
    other_rider = fixtures.register_rider(
        api,
        rider_ref="R-200",
        display_name="Rider Two",
        demographic_band="BAND_B",
        residence_geo_tract="T-002",
    )

    rows, meta = validate_paginated(
        api.list_citations(
            ANALYST_HEADERS,
            {
                "rider_id": rider_id,
                "adjudication_status": ADJUDICATION_ISSUED,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert ids_of(rows) == [citation_id]

    rows, meta = validate_paginated(
        api.list_citations(
            ANALYST_HEADERS,
            {"rider_id": rider_id, "adjudication_status": ADJUDICATION_DISMISSED},
        )
    )
    assert meta["total_count"] == 0
    assert rows == []

    rows, meta = validate_paginated(
        api.list_citations(ANALYST_HEADERS, {"rider_id": other_rider["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    rows, meta = validate_paginated(
        api.list_citations(
            HEARING_OFFICER_HEADERS,
            {
                "encounter_id": chain["encounter"]["id"],
                "settlement_status": SETTLEMENT_OUTSTANDING,
            },
        )
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [citation_id]
