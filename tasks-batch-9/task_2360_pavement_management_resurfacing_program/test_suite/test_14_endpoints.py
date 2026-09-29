"""Computed reads, filtered listings, cross-reference lookups and one-shot actions."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_decimals,
    assert_money,
    assert_pagination_meta,
    ids_of,
)
from test_helpers.constants import MAPLE_CANDIDATE_COST, MILL_AND_OVERLAY
from test_helpers.factories import triage_payload
from test_helpers.test_users import ENGINEER, RESIDENT

# ----------------------------------------------------------------------
# Pinned literals
# ----------------------------------------------------------------------
FULL_MARKS_COMPONENT = 100.00
FULL_MARKS_COMPOSITE = 100.0
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0

MAPLE_AND_OAK_LINES = [
    ("Maple St", "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z"),
    ("Oak St", "2026-09-16T00:00:00Z", "2026-09-30T00:00:00Z"),
]
OAK_LINE_ONLY = [("Oak St", "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z")]

# A MEDIUM complaint filed at 2026-08-01T00:00:00Z is due 168 hours later.
TRIAGE_INSTANT = "2026-08-01T00:00:00"
MEDIUM_SLA_DUE = "2026-08-08T00:00:00"
OAK_COMPLAINT_NOTE = "sunken patch outside 812 Oak St"


def _lines(api, params, headers=ENGINEER):
    return validate_paginated(api.list_project_segments(headers, params))


# ----------------------------------------------------------------------
# The contractor scorecard: a projection, not a stored row
# ----------------------------------------------------------------------


def test_a_brand_new_contractors_scorecard_publishes_both_variants_side_by_side(api):
    """The interim variant reads 100.0 from empty-set defaults while the final stays null.

    PRD: "A dedicated computed read publishes the whole scorecard: the `contractor_id`,
    the current `standing`, both composite scores, and each score's component breakdown
    as `interim_quality_component`, `interim_schedule_component`,
    `interim_remediation_component`, `final_quality_component`,
    `final_schedule_component` and `final_remediation_component`, together with the
    underlying `passed_test_count`, `failed_test_count`, `remediation_event_count`,
    `days_late_total` and `accepted_project_count`."

    PRD: "The quality component is 100.00 when the contractor has no decided tests at
    all; otherwise it is 100 multiplied by the passed-test count, divided by the sum of
    the passed and failed counts, rounded to two decimal places."

    PRD: "The schedule component is 100 less 2.5 points per late day, clamped into 0.00
    through 100.00 and rounded to two decimal places."

    PRD: "The remediation component is 100 less 8 points per remediation event, clamped
    into 0.00 through 100.00 and rounded to two decimal places."

    PRD: "The composite score is 0.45 times the quality component plus 0.30 times the
    schedule component plus 0.25 times the remediation component, rounded to one
    decimal place."

    PRD: "It remains null while `accepted_project_count` is zero."

    A final score of 0.0 would be indistinguishable from a catastrophic record, so the
    absence of any accepted project must publish as null.

    Design: Corner/endpoints/contractor_scorecard_is_a_computed_read_with_a_null_final_score
    """
    fixtures.set_clock(api)
    contractor = fixtures.register_contractor(api)

    scorecard = validate_success(
        api.get_contractor_scorecard(contractor["id"], ENGINEER)
    )
    assert scorecard["contractor_id"] == contractor["id"]
    assert scorecard["standing"] == "GOOD_STANDING"

    for component in (
        "interim_quality_component",
        "interim_schedule_component",
        "interim_remediation_component",
    ):
        assert_decimals(scorecard[component], 2, component)
        assert scorecard[component] == FULL_MARKS_COMPONENT, (
            f"expected {component} {FULL_MARKS_COMPONENT}, got {scorecard[component]}"
        )
    assert_decimals(scorecard["interim_performance_score"], 1, "interim_performance_score")
    assert scorecard["interim_performance_score"] == FULL_MARKS_COMPOSITE
    assert scorecard["final_performance_score"] is None

    assert scorecard["passed_test_count"] == 0
    assert scorecard["failed_test_count"] == 0
    assert scorecard["remediation_event_count"] == 0
    assert scorecard["days_late_total"] == 0
    assert scorecard["accepted_project_count"] == 0

    row = fixtures.read_contractor(api, contractor["id"])
    assert row["version"] == contractor["version"]
    assert row["standing"] == scorecard["standing"]
    assert row["interim_performance_score"] == scorecard["interim_performance_score"]
    assert row["final_performance_score"] is None


# ----------------------------------------------------------------------
# The junction listing: filters plus pagination over the filtered set
# ----------------------------------------------------------------------


def test_the_line_listing_filters_on_state_and_paginates_over_the_filtered_set(api):
    """Pagination walks the filtered result, and an empty filter is 200 with an empty array.

    PRD: "Lines may be listed and filtered by `project_id`, `segment_id`,
    `candidate_id`, `work_state` and `notice_state`, and are readable by every role
    including `Resident`."

    PRD: "List endpoints accept two query parameters. `limit` caps the number of rows
    returned; it defaults to 10, may not be smaller than 1, and may not be larger than
    100. `offset` skips rows from the front of the ordered result and defaults to 0; it
    may not be negative. A `limit` outside the range 1 through 100, or a negative
    `offset`, is a malformed request and yields `ERR_INVALID_REQUEST`."

    PRD: "Every list response reports `limit`, `offset`, `total_count` and `has_more` in
    the envelope's `meta` object."

    PRD: "Unless a list endpoint says otherwise, results are ordered by `created_at`
    ascending."

    Design: Corner/endpoints/project_segments_listing_filters_by_work_state_and_paginates
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_AND_OAK)
    ctx = fixtures.draft_project(api, ctx, MAPLE_AND_OAK_LINES)
    project_id = ctx["project"]["id"]
    oak_segment_id = fixtures.segment_for(ctx, "Oak St")["id"]

    planned = {"project_id": project_id, "work_state": "PLANNED"}

    first, first_meta = _lines(api, dict(planned, limit=1, offset=0))
    assert len(first) == 1
    assert_pagination_meta(first_meta, 1, 0, 2, True)

    second, second_meta = _lines(api, dict(planned, limit=1, offset=1))
    assert len(second) == 1
    assert_pagination_meta(second_meta, 1, 1, 2, False)
    assert ids_of(first) != ids_of(second)

    in_progress, in_progress_meta = _lines(
        api, {"project_id": project_id, "work_state": "IN_PROGRESS"}, RESIDENT
    )
    assert in_progress == []
    assert in_progress_meta["total_count"] == 0

    by_segment, by_segment_meta = _lines(api, {"segment_id": oak_segment_id})
    assert by_segment_meta["total_count"] == 1
    assert by_segment[0]["segment_id"] == oak_segment_id

    unpaged, unpaged_meta = _lines(api, {"project_id": project_id})
    assert len(unpaged) == 2
    assert_pagination_meta(unpaged_meta, DEFAULT_LIMIT, DEFAULT_OFFSET, 2, False)


# ----------------------------------------------------------------------
# The complaint-to-capital link, read from both ends
# ----------------------------------------------------------------------


def test_a_deferred_complaint_is_reachable_from_the_project_it_was_attached_to(api):
    """The capital link is a real foreign key, filterable in the reverse direction.

    PRD: "A `disposition` of `DEFER_TO_CAPITAL` moves `request_status` from `NEW` to
    `DEFERRED_TO_CAPITAL`, stamps `triaged_at`, and sets `capital_project_id` to the
    supplied `target_project_id`, attaching the complaint to a resurfacing project so
    that it closes automatically when the street is rebuilt rather than being closed by
    a patch crew."

    PRD: "Complaints may be listed and filtered by `segment_id`, `capital_project_id`,
    `request_status` and `reported_severity`, and residents may read their own complaint
    views."

    PRD: "`sla_due_at` is the request's `created_at` plus the response allowance for its
    severity: 72 hours for `HIGH`, 168 hours for `MEDIUM`, and 720 hours for `LOW`."

    PRD: "Triage requires the request to still be `NEW`, else
    `ERR_SERVICE_REQUEST_NOT_NEW`, and — per §2.11 — never changes the segment's
    `open_service_request_count`."

    A deferred pothole is still an open complaint: the street has not been paved yet.

    Design: Corner/endpoints/triage_deferral_writes_the_capital_link_readable_from_both_directions
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_AND_OAK)
    ctx = fixtures.draft_project(api, ctx, OAK_LINE_ONLY)
    project_id = ctx["project"]["id"]
    oak_segment_id = fixtures.segment_for(ctx, "Oak St")["id"]

    request = fixtures.file_service_request(
        api,
        oak_segment_id,
        reported_severity="MEDIUM",
        location_note=OAK_COMPLAINT_NOTE,
    )
    assert request["request_status"] == "NEW"
    assert request["sla_due_at"].startswith(MEDIUM_SLA_DUE)
    assert fixtures.read_segment(api, oak_segment_id)["open_service_request_count"] == 1

    deferred = fixtures.triage_service_request(
        api, request["id"], "DEFER_TO_CAPITAL", project_id
    )
    assert deferred["request_status"] == "DEFERRED_TO_CAPITAL"
    assert deferred["capital_project_id"] == project_id
    assert deferred["triaged_at"].startswith(TRIAGE_INSTANT)
    assert deferred["sla_due_at"].startswith(MEDIUM_SLA_DUE)
    assert deferred["sla_breached"] is False
    assert deferred["closed_at"] is None
    assert deferred["closure_code"] is None

    reverse, reverse_meta = validate_paginated(
        api.list_service_requests(
            ENGINEER, {"capital_project_id": project_id, "limit": 100}
        )
    )
    assert reverse_meta["total_count"] == 1
    assert reverse[0]["id"] == request["id"]

    assert fixtures.read_segment(api, oak_segment_id)["open_service_request_count"] == 1


def test_triage_payload_carries_the_target_only_for_the_capital_branch(api):
    """A PATCH disposition leaves the capital link null, so the two branches differ.

    PRD: "Triage is a `PavementEngineer` action and branches. A `disposition` of `PATCH`
    moves `request_status` from `NEW` to `TRIAGED_PATCH`, stamps `triaged_at`, and
    leaves `capital_project_id` null — the complaint stays with the maintenance crew."

    PRD: "Complaints may be listed and filtered by `segment_id`, `capital_project_id`,
    `request_status` and `reported_severity`, and residents may read their own complaint
    views."

    PRD: "Triage requires the request to still be `NEW`, else
    `ERR_SERVICE_REQUEST_NOT_NEW`, and — per §2.11 — never changes the segment's
    `open_service_request_count`."

    Design: Corner/endpoints/triage_deferral_writes_the_capital_link_readable_from_both_directions
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_AND_OAK)
    ctx = fixtures.draft_project(api, ctx, OAK_LINE_ONLY)
    oak_segment_id = fixtures.segment_for(ctx, "Oak St")["id"]

    request = fixtures.file_service_request(
        api,
        oak_segment_id,
        reported_severity="MEDIUM",
        location_note=OAK_COMPLAINT_NOTE,
    )
    patched = validate_success(
        api.triage_service_request(request["id"], triage_payload("PATCH"), ENGINEER)
    )
    assert patched["request_status"] == "TRIAGED_PATCH"
    assert patched["capital_project_id"] is None
    assert patched["triaged_at"].startswith(TRIAGE_INSTANT)

    _rows, meta = validate_paginated(
        api.list_service_requests(
            ENGINEER, {"capital_project_id": ctx["project"]["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0
    assert fixtures.read_segment(api, oak_segment_id)["open_service_request_count"] == 1


# ----------------------------------------------------------------------
# Generation is a one-shot action, not an idempotent projection
# ----------------------------------------------------------------------


def test_a_second_candidate_generation_on_one_survey_is_refused_and_changes_nothing(api):
    """Re-running selection would let one street be funded twice, so it is a 409.

    PRD: "Selection may only run on a sealed survey — attempting it earlier reports
    `ERR_SURVEY_NOT_SEALED` — and may only run once per survey; a second run reports
    `ERR_CANDIDATES_ALREADY_GENERATED`."

    PRD: "Candidates may be listed and filtered by `survey_id`, `segment_id`,
    `candidate_status` and `treatment_type`."

    PRD: "`OPEN` and `SEALED` are the only two states a survey ever holds; sealing is
    the sole exit and there is no un-seal."

    The refused call must not leave the survey half-generated: the original candidate
    keeps its id, its RECOMMENDED status and its estimate.

    Design: Corner/endpoints/generating_candidates_a_second_time_for_one_survey_rejected
    """
    ctx = fixtures.survey_with_candidates(api, fixtures.MAPLE_ONLY)
    survey_id = ctx["survey"]["id"]
    original = fixtures.candidate_for(ctx, "Maple St")
    assert original["treatment_type"] == MILL_AND_OVERLAY
    assert_money(original["estimated_cost_cents"], MAPLE_CANDIDATE_COST)

    validate_error(
        api.generate_candidates(survey_id, ENGINEER),
        ApiErrorId.CANDIDATES_ALREADY_GENERATED,
        409,
    )

    rows, meta = validate_paginated(
        api.list_candidates(ENGINEER, {"survey_id": survey_id, "limit": 100})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == original["id"]

    again = fixtures.read_candidate(api, original["id"])
    assert again["candidate_status"] == "RECOMMENDED"
    assert again["treatment_type"] == MILL_AND_OVERLAY
    assert_money(again["estimated_cost_cents"], MAPLE_CANDIDATE_COST)

    survey = validate_success(api.get_survey(survey_id, ENGINEER))
    assert survey["survey_status"] == "SEALED"
