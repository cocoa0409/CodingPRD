"""Two overlap conventions that point in opposite directions.

A property's measuring periods are half-open, so two windows that abut are fine.
A reviewer's occupation windows are closed, so two windows that merely touch at a
single date already conflict. The same date arithmetic therefore produces opposite
verdicts depending on which resource is being contended for.
"""

from test_helpers import (
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_success,
)


def test_a_second_project_abutting_the_first_measuring_period_is_accepted(api):
    """Periods that meet at one date do not overlap, so the abutting project opens.

    Project A holds the half-open window from 2026-09-01 for 24 months, ending
    exclusively on 2028-09-01. Project B on the same building opens its own 24-month
    window on exactly that date, which is the first date A no longer occupies, so it
    is accepted and runs to 2030-09-01.

    PRD: "Periods that merely abut — one ending on the day the next begins — are accepted."
    PRD: "Two measuring periods overlap precisely when the first period's start precedes the second period's end **and** the second period's start precedes the first period's end; periods that merely touch, where one period's end date equals the other's start date, do not overlap."

    Design: Difficulty/resource_temporal_overlap/property_measuring_period_half_open_adjacent_ok_overlap_rejected
    """
    cast = fixtures.seed_cast(api)
    project_a = fixtures.open_project(
        api,
        cast,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    assertions.assert_fields(
        project_a, "project A", measuring_period_end_date="2028-09-01"
    )

    project_b = validate_success(
        api.create_project(
            cast.developer_headers,
            **factories.project_payload(
                cast.developer_id,
                cast.property_id,
                project_name="Elm Mill Phase B",
                structure_type="SINGLE_TIER",
                adjusted_basis_cents=30_000_000,
                measuring_period_months=24,
                measuring_period_start_date="2028-09-01",
            ),
        ),
        201,
    )

    assertions.assert_fields(
        project_b,
        "abutting project B",
        measuring_period_start_date="2028-09-01",
        measuring_period_end_date="2030-09-01",
        certification_status="PRE_CERTIFICATION",
    )
    stored_property = get_success_data(
        api.get_property(cast.property_id, cast.developer_headers)
    )
    assertions.assert_fields(stored_property, "property", open_project_count=2)


def test_a_third_project_overlapping_an_existing_measuring_period_is_refused(api):
    """A window starting one month before the incumbent's end date conflicts.

    With project A holding 2026-09-01 to 2028-09-01 and project B holding
    2028-09-01 to 2030-09-01, a third window opening on 2028-08-01 runs into A's
    last month and is refused. The building is left with exactly the two projects
    that were legally opened on it.

    PRD: "A project whose measuring period overlaps the measuring period of any other project on the same property is refused with `ERR_PROPERTY_MEASURING_PERIOD_OVERLAP`, applying the half-open overlap test of §2.11."
    PRD: "The `open_project_count` counts the property's projects whose certification dimension is any of `PRE_CERTIFICATION`, `PART1_CERTIFIED`, `PART2_APPROVED`, or `PART3_CERTIFIED`; opening a project raises it by one, and a project driven to `DECERTIFIED` drops out of it."

    Design: Difficulty/resource_temporal_overlap/property_measuring_period_half_open_adjacent_ok_overlap_rejected
    """
    cast = fixtures.seed_cast(api)
    fixtures.open_project(
        api,
        cast,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    validate_success(
        api.create_project(
            cast.developer_headers,
            **factories.project_payload(
                cast.developer_id,
                cast.property_id,
                project_name="Elm Mill Phase B",
                structure_type="SINGLE_TIER",
                adjusted_basis_cents=30_000_000,
                measuring_period_months=24,
                measuring_period_start_date="2028-09-01",
            ),
        ),
        201,
    )

    response = api.create_project(
        cast.developer_headers,
        **factories.project_payload(
            cast.developer_id,
            cast.property_id,
            project_name="Elm Mill Phase C",
            structure_type="SINGLE_TIER",
            adjusted_basis_cents=30_000_000,
            measuring_period_months=24,
            measuring_period_start_date="2028-08-01",
        ),
    )

    validate_error(
        response, ApiErrorId.PROPERTY_MEASURING_PERIOD_OVERLAP.value, 409
    )
    assertions.assert_page(
        api.list_projects(cast.developer_headers, property_id=cast.property_id),
        total_count=2,
    )
    stored_property = get_success_data(
        api.get_property(cast.property_id, cast.developer_headers)
    )
    assertions.assert_fields(stored_property, "property", open_project_count=2)


def test_a_second_review_window_sharing_one_endpoint_date_is_still_accepted(api):
    """Touching windows do overlap, but one conflict is under the cap of two.

    The first application is submitted on 2026-09-01, occupying the reviewer through
    2026-10-01. The second is submitted on exactly 2026-10-01, so the two windows
    share that single endpoint date and therefore overlap under the closed-interval
    convention. That is one conflicting window, which is below the cap of two, so
    the submission is accepted and the reviewer now holds two overlapping windows.

    PRD: "It runs from the date of `submitted_at` through the date of `review_window_end`, both endpoints included."
    PRD: "Two closed windows overlap precisely when the first window's start is on or before the second window's end **and** the second window's start is on or before the first window's end — so two windows that share only a single endpoint date **do** overlap."
    PRD: "A reviewer may hold at most two such overlapping windows: when the count of conflicting applications is two or more, the submission is refused with `ERR_REVIEWER_WINDOW_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/reviewer_closed_review_window_capacity_rejects_third_touching_window
    """
    cast = fixtures.seed_cast(api)
    first_project = fixtures.open_project(api, cast)
    second_property = fixtures.create_property(
        api, name="Canal Warehouse", street_address="8 Canal Street"
    )
    second_project = fixtures.open_project(
        api, cast, property_id=second_property["id"]
    )
    first = fixtures.create_part_application(api, cast, first_project["id"], 1)
    second = fixtures.create_part_application(api, cast, second_project["id"], 1)

    first_submitted = fixtures.submit_part_application(api, cast, first["id"])
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    second_submitted = fixtures.submit_part_application(api, cast, second["id"])

    assertions.assert_fields(
        first_submitted, "first application", status="SHPO_REVIEW"
    )
    assert first_submitted["review_window_end"].startswith("2026-10-01T00:00:00"), (
        "the first window closes thirty days after its 2026-09-01 submission"
    )
    assertions.assert_fields(
        second_submitted,
        "second application sharing one endpoint date",
        status="SHPO_REVIEW",
        shpo_reviewer_id=cast.shpo_reviewer_id,
    )
    assert second_submitted["review_window_end"].startswith("2026-10-31T00:00:00"), (
        "the second window closes thirty days after its 2026-10-01 submission"
    )


def test_a_third_submission_touching_both_held_windows_hits_the_capacity_cap(api):
    """Two conflicting windows is the cap, so the third submission is refused.

    The reviewer already holds 2026-09-01 through 2026-10-01 and 2026-10-01 through
    2026-10-31, both still in SHPO_REVIEW. A third application submitted on
    2026-10-01 would occupy a window overlapping both of them, so the count of
    conflicting applications reaches two and the submission is refused. That
    application stays DRAFT with no reviewer and no submission timestamp written
    onto it.

    PRD: "Before a submission is accepted, the system counts the *other* applications assigned to the same `shpo_reviewer_id` whose status is `SHPO_REVIEW`, `NPS_REVIEW`, or `CONDITIONAL` and whose closed occupation interval — from the date of their `submitted_at` through the date of their `review_window_end` — overlaps the prospective closed interval of this submission, which runs from the current logical clock date through that date advanced by thirty days."
    PRD: "Overlap here uses the closed-interval convention of §2.11, so windows sharing only one endpoint date do overlap."
    PRD: "Submission stamps `submitted_at` from the logical clock and derives `review_window_end` as that instant advanced by thirty days, which together bound the reviewer's occupation interval as a closed date interval."

    Design: Difficulty/resource_temporal_overlap/reviewer_closed_review_window_capacity_rejects_third_touching_window
    """
    cast = fixtures.seed_cast(api)
    first_project = fixtures.open_project(api, cast)
    second_property = fixtures.create_property(
        api, name="Canal Warehouse", street_address="8 Canal Street"
    )
    third_property = fixtures.create_property(
        api, name="Foundry Annex", street_address="19 Foundry Row"
    )
    second_project = fixtures.open_project(
        api, cast, property_id=second_property["id"]
    )
    third_project = fixtures.open_project(api, cast, property_id=third_property["id"])
    first = fixtures.create_part_application(api, cast, first_project["id"], 1)
    second = fixtures.create_part_application(api, cast, second_project["id"], 1)
    third = fixtures.create_part_application(api, cast, third_project["id"], 1)
    fixtures.submit_part_application(api, cast, first["id"])
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    fixtures.submit_part_application(api, cast, second["id"])

    response = api.submit_part_application(
        third["id"], cast.developer_headers, shpo_reviewer_id=cast.shpo_reviewer_id
    )

    validate_error(response, ApiErrorId.REVIEWER_WINDOW_CAPACITY.value, 409)
    stored = get_success_data(
        api.get_part_application(third["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        stored,
        "third application after the refused submission",
        status="DRAFT",
        submitted_at=None,
        shpo_reviewer_id=None,
        review_window_end=None,
    )
