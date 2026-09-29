"""Precedence, ownership, input-validation, conditional and idempotency errors."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_money
from test_helpers.constants import (
    CLOCK_2026_10_01,
    DEFAULT_CLOCK,
    SEG_MAPLE,
    SEG_OAK,
    UNKNOWN_UUID,
)
from test_helpers.factories import advance_payload, cut_decide_payload, respond_payload
from test_helpers.test_users import (
    COORDINATOR,
    ENGINEER,
    make_contractor_headers,
)

# ----------------------------------------------------------------------
# Pinned literals
# ----------------------------------------------------------------------
RIVAL_NAME = "Rival Asphalt Co"

OVER_MAX_LIMIT = 101
MAX_LIMIT = 100
UNDER_MIN_LIMIT = 0

# A 200.00 sqft trench bills 850 cents per square foot before any multiplier.
CUT_AREA_SQFT = 200.0
UNENCUMBERED_FEE = 170000
MORATORIUM_TIER_FEE = 510000
MORATORIUM_TIER_MULTIPLIER = 3.0
MORATORIUM_REMAINING_DAYS = 1096
WAIVER_REASON = "trunk main break risk accepted by the city engineer"

CUT_WINDOW_START = "2026-11-01T00:00:00Z"
CUT_WINDOW_END = "2026-11-03T00:00:00Z"
EARLY_CUT_WINDOW_START = "2026-08-10T00:00:00Z"
EARLY_CUT_WINDOW_END = "2026-08-12T00:00:00Z"

FIRST_COMPLETION_CLOCK = "2026-08-05T00:00:00Z"
FIRST_COMPLETION_INSTANT = "2026-08-05T00:00:00"
LATER_CLOCK = "2026-08-06T00:00:00Z"

REPLAY_NOTE = "resubmitting the same clearance"
CLEARANCE_NOTE = "no facilities in conflict"


# ----------------------------------------------------------------------
# Entity-backed identity: resolution outranks ownership outranks not-found
# ----------------------------------------------------------------------


def test_a_contractor_header_naming_no_contractor_row_is_refused_at_identity(api):
    """Identity resolution runs before the ownership check and before any not-found.

    PRD: "If a caller declares the `Contractor` role but `X-User-ID` does not resolve
    to an existing `Contractor` row, the request is rejected with
    `ERR_UNKNOWN_CONTRACTOR_IDENTITY`."

    PRD: "Checks run in the following order, and the first violation short-circuits
    every later check:"

    PRD: "A `Contractor` caller's `X-User-ID` resolves to a contractor row, else
    `ERR_UNKNOWN_CONTRACTOR_IDENTITY`."

    PRD: "A `Contractor` caller acts only on its own project, else
    `ERR_NOT_PROJECT_CONTRACTOR`."

    PRD: "The `message` provides a human-readable explanation of what went wrong."

    The addressed project genuinely exists, so the later not-found check cannot be
    what answered, and the same URL read under the real contractor identity is 200.

    Design: Corner/errors/contractor_role_with_an_unknown_user_id_returns_403
    """
    ctx = fixtures.maple_in_construction(api)
    project_id = ctx["project"]["id"]
    contractor_id = ctx["contractor"]["id"]

    error = validate_error(
        api.get_project(project_id, make_contractor_headers(UNKNOWN_UUID)),
        ApiErrorId.UNKNOWN_CONTRACTOR_IDENTITY,
        403,
    )
    assert isinstance(error["message"], str) and error["message"].strip()

    owned = validate_success(
        api.get_project(project_id, make_contractor_headers(contractor_id))
    )
    assert owned["id"] == project_id
    assert owned["delivery_status"] == "IN_CONSTRUCTION"


def test_a_rival_firm_cannot_report_completion_on_another_contractors_project(api):
    """A real contractor row clears identity but still fails row-level ownership.

    PRD: "Separately, a `Contractor` caller acting on a project whose `contractor_id`
    is not the caller's `X-User-ID` is rejected with `ERR_NOT_PROJECT_CONTRACTOR`;
    this guards both the substantial-completion action and the single-project read."

    PRD: "The project must be in construction, else
    `ERR_PROJECT_NOT_IN_CONSTRUCTION`; the caller's `X-User-ID` must equal the
    project's `contractor_id`, else `ERR_NOT_PROJECT_CONTRACTOR`; and no line on the
    project may still be `PLANNED` or `IN_PROGRESS`, else
    `ERR_LINES_WORK_INCOMPLETE`."

    PRD: "A contractor's `passed_test_count`, `failed_test_count`,
    `remediation_event_count`, `days_late_total` and `accepted_project_count` are
    likewise derived from its projects and their tests."

    Design: Corner/errors/contractor_reporting_completion_on_another_firms_project_returns_403
    """
    ctx = fixtures.maple_in_construction(api)
    project_id = ctx["project"]["id"]
    owner_id = ctx["contractor"]["id"]
    rival = fixtures.register_contractor(api, RIVAL_NAME)

    validate_error(
        api.substantial_completion(project_id, {}, make_contractor_headers(rival["id"])),
        ApiErrorId.NOT_PROJECT_CONTRACTOR,
        403,
    )

    project = fixtures.read_project(api, project_id)
    assert project["delivery_status"] == "IN_CONSTRUCTION"
    assert project["substantial_completion_at"] is None
    assert project["contractor_id"] == owner_id
    assert fixtures.read_line(api, ctx["lines"]["Maple St"]["id"])["work_state"] == "IN_PROGRESS"

    scorecard = validate_success(api.get_contractor_scorecard(rival["id"], ENGINEER))
    assert scorecard["days_late_total"] == 0
    assert scorecard["accepted_project_count"] == 0


# ----------------------------------------------------------------------
# Pagination bounds are validated, not clamped
# ----------------------------------------------------------------------


def test_a_page_size_outside_the_declared_bounds_is_a_malformed_request(api):
    """Both an oversized and an undersized page size are 400, never a clamped page.

    PRD: "List endpoints accept two query parameters. `limit` caps the number of rows
    returned; it defaults to 10, may not be smaller than 1, and may not be larger than
    100. `offset` skips rows from the front of the ordered result and defaults to 0; it
    may not be negative. A `limit` outside the range 1 through 100, or a negative
    `offset`, is a malformed request and yields `ERR_INVALID_REQUEST`."

    PRD: "Required body fields present, JSON types correct, enum values in range,
    numeric fields within their declared bounds, pagination parameters legal,
    timestamps ISO 8601 UTC, and every window's end strictly after its start — else
    `ERR_INVALID_REQUEST`."

    PRD: "The network can be listed with filters on `geo_zone`, `functional_class` and
    `condition_band`, which is how an engineer assembles the candidate list for a
    geographic bundle, and every role in the system may read the inventory."

    Design: Corner/errors/segments_listing_with_limit_one_hundred_one_returns_invalid_request
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    fixtures.create_segment(api, SEG_MAPLE)

    validate_error(
        api.list_segments(ENGINEER, {"geo_zone": "Z1", "limit": OVER_MAX_LIMIT}),
        ApiErrorId.INVALID_REQUEST,
        400,
    )
    validate_error(
        api.list_segments(ENGINEER, {"geo_zone": "Z1", "limit": UNDER_MIN_LIMIT}),
        ApiErrorId.INVALID_REQUEST,
        400,
    )


def test_the_maximum_page_size_of_one_hundred_is_itself_accepted(api):
    """The declared maximum is inclusive, so 100 pages normally and echoes back.

    PRD: "List endpoints accept two query parameters. `limit` caps the number of rows
    returned; it defaults to 10, may not be smaller than 1, and may not be larger than
    100. `offset` skips rows from the front of the ordered result and defaults to 0; it
    may not be negative. A `limit` outside the range 1 through 100, or a negative
    `offset`, is a malformed request and yields `ERR_INVALID_REQUEST`."

    PRD: "Every list response reports `limit`, `offset`, `total_count` and `has_more`
    in the envelope's `meta` object."

    Design: Corner/errors/segments_listing_with_limit_one_hundred_one_returns_invalid_request
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    segment = fixtures.create_segment(api, SEG_MAPLE)

    rows, meta = validate_paginated(
        api.list_segments(ENGINEER, {"geo_zone": "Z1", "limit": MAX_LIMIT})
    )
    assert meta["limit"] == MAX_LIMIT
    assert meta["total_count"] == 1
    assert rows[0]["id"] == segment["id"]


# ----------------------------------------------------------------------
# A field that is optional in the schema but required by state
# ----------------------------------------------------------------------


def test_approving_a_moratorium_review_permit_without_a_waiver_is_refused(api):
    """The waiver is demanded by the permit's state, and the frozen fee never moves.

    PRD: "When the segment's `moratorium_until` is still in the future and the
    application is not an emergency, the permit opens at `MORATORIUM_REVIEW` instead,
    requiring a written waiver before it can be approved."

    PRD: "**Second**, because each of those lines was accepted, its segment
    absorbs the new pavement: `last_treatment_type` records the line's
    `treatment_type`, `last_treatment_date` is set to the project's `accepted_at`,
    `baseline_condition_index` is reset to the smaller of 100.0 and the sum of the
    segment's current `condition_index` and the executing candidate's
    `treatment_pci_gain`, `condition_index` is set to that same value,
    `condition_index_source` becomes `MODEL_PROJECTED`, `condition_band` is
    recomputed, `active_project_count` is decremented, and `moratorium_until` is
    set to `accepted_at` plus the moratorium length for the treatment placed — one
    calendar year after a `CRACK_SEAL`, three calendar years after a
    `MILL_AND_OVERLAY`, and five calendar years after a `RECONSTRUCTION`."

    PRD: "Second, a tier multiplier follows from that remaining count: 3.0 when at
    least 1,096 days remain, 2.0 when at least 366 remain, 1.5 when at least 1
    remains, and 1.0 when none remains."

    PRD: "Fourth, the base fee is the trench area multiplied by 850 cents per square
    foot, rounded to whole cents, but never less than the 45,000-cent ($450)
    minimum."

    PRD: "Approving a `MORATORIUM_REVIEW` permit requires a non-empty
    `waiver_reason`, which is recorded on the permit; without it the approval reports
    `ERR_MORATORIUM_WAIVER_REQUIRED`."

    PRD: "Approval moves the permit to `APPROVED`, stamps `decided_at` and freezes
    `degradation_fee_cents` at its current value."

    A mill-and-overlay accepted on 2026-10-01 runs its moratorium to 2029-10-01, and
    with the clock still at the acceptance instant exactly 1096 days remain.

    Design: Corner/errors/approving_a_moratorium_review_permit_without_a_waiver_rejected
    """
    ctx = fixtures.moratorium_segment(api)
    segment = fixtures.segment_for(ctx, "Maple St")
    assert segment["moratorium_until"].startswith("2029-10-01T00:00:00")
    assert ctx["clock"] == CLOCK_2026_10_01

    permit = fixtures.apply_cut_permit(
        api,
        segment["id"],
        applicant_utility="WATER",
        requested_start=CUT_WINDOW_START,
        requested_end=CUT_WINDOW_END,
        cut_area_sqft=CUT_AREA_SQFT,
        emergency=False,
    )
    assert permit["permit_status"] == "MORATORIUM_REVIEW"
    assert permit["moratorium_remaining_days"] == MORATORIUM_REMAINING_DAYS
    assert permit["fee_multiplier"] == MORATORIUM_TIER_MULTIPLIER
    assert_money(permit["degradation_fee_cents"], MORATORIUM_TIER_FEE)

    validate_error(
        api.decide_cut_permit(permit["id"], cut_decide_payload("APPROVE"), ENGINEER),
        ApiErrorId.MORATORIUM_WAIVER_REQUIRED,
        422,
    )

    untouched = validate_success(api.get_cut_permit(permit["id"], COORDINATOR))
    assert untouched["permit_status"] == "MORATORIUM_REVIEW"
    assert untouched["decided_at"] is None
    assert untouched["waiver_reason"] is None
    assert_money(untouched["degradation_fee_cents"], MORATORIUM_TIER_FEE)

    approved = validate_success(
        api.decide_cut_permit(
            permit["id"],
            cut_decide_payload("APPROVE", waiver_reason=WAIVER_REASON),
            ENGINEER,
        )
    )
    assert approved["permit_status"] == "APPROVED"
    assert approved["waiver_reason"] == WAIVER_REASON
    assert_money(approved["degradation_fee_cents"], MORATORIUM_TIER_FEE)


def test_the_same_waiver_less_approval_body_is_accepted_on_an_unencumbered_permit(api):
    """The demand is state-conditional: a PENDING permit takes the identical body.

    PRD: "When the segment's `moratorium_until` is null, or has already passed the
    logical clock, or when the application is flagged as an emergency, the permit
    opens at `permit_status` `PENDING`."

    PRD: "A `PENDING` permit needs no waiver, and its `waiver_reason` stays null."

    PRD: "Approval moves the permit to `APPROVED`, stamps `decided_at` and freezes
    `degradation_fee_cents` at its current value."

    PRD: "Then the roster check: the `applicant_utility` must appear on the city's
    coordination roster, meaning some utility coordination row somewhere in the system
    carries the same utility value, else `ERR_UTILITY_NOT_ON_COORDINATION_ROSTER`."

    Design: Corner/errors/approving_a_moratorium_review_permit_without_a_waiver_rejected
    """
    fixtures.moratorium_segment(api)
    fresh = fixtures.create_segment(api, SEG_OAK)
    assert fresh["moratorium_until"] is None

    permit = fixtures.apply_cut_permit(
        api,
        fresh["id"],
        applicant_utility="WATER",
        requested_start=CUT_WINDOW_START,
        requested_end=CUT_WINDOW_END,
        cut_area_sqft=CUT_AREA_SQFT,
        emergency=False,
    )
    assert permit["permit_status"] == "PENDING"

    approved = validate_success(
        api.decide_cut_permit(permit["id"], cut_decide_payload("APPROVE"), ENGINEER)
    )
    assert approved["permit_status"] == "APPROVED"
    assert approved["waiver_reason"] is None
    assert approved["decided_at"].startswith("2026-10-01T00:00:00")


# ----------------------------------------------------------------------
# Trench completion is a one-shot report
# ----------------------------------------------------------------------


def _approved_permit_on_a_coordinating_project(api):
    """An unencumbered 200 sqft WATER cut, approved, on a COORDINATING Maple bundle."""
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.coordinating_project(api, ctx, fixtures.MAPLE_LINE)
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]
    assert fixtures.read_segment(api, segment_id)["moratorium_until"] is None

    permit = fixtures.apply_cut_permit(
        api,
        segment_id,
        applicant_utility="WATER",
        requested_start=EARLY_CUT_WINDOW_START,
        requested_end=EARLY_CUT_WINDOW_END,
        cut_area_sqft=CUT_AREA_SQFT,
        emergency=False,
    )
    assert permit["permit_status"] == "PENDING"
    assert_money(permit["degradation_fee_cents"], UNENCUMBERED_FEE)
    return ctx, permit


def test_reporting_the_same_completed_cut_twice_keeps_the_first_timestamp(api):
    """A replayed completion would re-stamp the trench closure, so it is refused.

    PRD: "The `UtilityCoordinator` reports the trench backfilled and restored, which
    stamps `cut_completed_at` from the logical clock and releases the
    construction-start block of §3.7."

    PRD: "That report is permitted only once and only on an approved permit; a permit
    that is not `APPROVED`, or one whose `cut_completed_at` is already set, reports
    `ERR_CUT_NOT_APPROVED_OR_ALREADY_COMPLETE`."

    PRD: "Approval moves the permit to `APPROVED`, stamps `decided_at` and freezes
    `degradation_fee_cents` at its current value."

    PRD: "Fourth, the base fee is the trench area multiplied by 850 cents per square
    foot, rounded to whole cents, but never less than the 45,000-cent ($450)
    minimum."

    The clock has moved a day past the first report, so a permissive replay would be
    visible as a later `cut_completed_at`.

    Design: Corner/errors/reporting_a_completed_cut_twice_rejected
    """
    _ctx, permit = _approved_permit_on_a_coordinating_project(api)
    fixtures.decide_cut_permit(api, permit["id"], "APPROVE")

    fixtures.set_clock(api, FIRST_COMPLETION_CLOCK)
    first = validate_success(api.complete_cut(permit["id"], {}, COORDINATOR))
    assert first["cut_completed_at"].startswith(FIRST_COMPLETION_INSTANT)

    fixtures.set_clock(api, LATER_CLOCK)
    validate_error(
        api.complete_cut(permit["id"], {}, COORDINATOR),
        ApiErrorId.CUT_NOT_APPROVED_OR_ALREADY_COMPLETE,
        409,
    )

    after = validate_success(api.get_cut_permit(permit["id"], COORDINATOR))
    assert after["permit_status"] == "APPROVED"
    assert after["cut_completed_at"] == first["cut_completed_at"]
    assert after["cut_completed_at"].startswith(FIRST_COMPLETION_INSTANT)
    assert_money(after["degradation_fee_cents"], UNENCUMBERED_FEE)


def test_the_same_code_answers_a_completion_on_a_pending_or_denied_permit(api):
    """One error code covers both halves of its name: not approved, or already done.

    PRD: "That report is permitted only once and only on an approved permit; a permit
    that is not `APPROVED`, or one whose `cut_completed_at` is already set, reports
    `ERR_CUT_NOT_APPROVED_OR_ALREADY_COMPLETE`."

    PRD: "Denial from either state moves the permit to `DENIED` and stamps
    `decided_at`; the computed fee stays on the record for audit but is not charged."

    Design: Corner/errors/reporting_a_completed_cut_twice_rejected
    """
    _ctx, undecided = _approved_permit_on_a_coordinating_project(api)

    validate_error(
        api.complete_cut(undecided["id"], {}, COORDINATOR),
        ApiErrorId.CUT_NOT_APPROVED_OR_ALREADY_COMPLETE,
        409,
    )

    denied = fixtures.decide_cut_permit(api, undecided["id"], "DENY")
    assert denied["permit_status"] == "DENIED"
    assert_money(denied["degradation_fee_cents"], UNENCUMBERED_FEE)

    validate_error(
        api.complete_cut(undecided["id"], {}, COORDINATOR),
        ApiErrorId.CUT_NOT_APPROVED_OR_ALREADY_COMPLETE,
        409,
    )
    assert validate_success(api.get_cut_permit(undecided["id"], COORDINATOR))[
        "cut_completed_at"
    ] is None


# ----------------------------------------------------------------------
# The clearance counter cannot be double-decremented
# ----------------------------------------------------------------------


def test_a_second_clearance_from_one_utility_cannot_decrement_the_counter_twice(api):
    """A replayed CLEAR is 409, and three utilities remain genuinely outstanding.

    PRD: "The transition creates four **utility coordination** rows on the project —
    one each for `WATER`, `SEWER`, `FRANCHISE_GAS` and `FRANCHISE_TELECOM` — each with
    `coordination_status` `CLEARANCE_REQUESTED`, `round_count` 1, and
    `planned_work_start`, `planned_work_end`, `work_completed_at` and `response_note`
    null, and sets `clearance_outstanding_count` to 4."

    PRD: "Either clearing decrements the project's `clearance_outstanding_count`."

    PRD: "Both `CLEAR` and `CONFLICT` require the row to be in `CLEARANCE_REQUESTED`,
    else `ERR_COORDINATION_NOT_PENDING`."

    PRD: "It requires the project to be in `COORDINATING`, else
    `ERR_PROJECT_NOT_COORDINATING`; it requires at least one non-removed line, else
    `ERR_PROJECT_HAS_NO_SEGMENTS`; and it requires `clearance_outstanding_count` to
    have reached zero, meaning every utility row on the project is either `CLEARED` or
    `CLEARED_AFTER_WORK`, else `ERR_UTILITY_CLEARANCE_PENDING`."

    PRD: "Clearance rows can be listed and filtered by `project_id`,
    `coordination_status` and `utility`."

    Design: Corner/errors/second_clear_response_on_an_already_cleared_utility_rejected
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.coordinating_project(api, ctx, fixtures.MAPLE_LINE)
    project_id = ctx["project"]["id"]
    water = fixtures.coordination_for(ctx, "WATER")
    assert ctx["project"]["clearance_outstanding_count"] == 4

    cleared = fixtures.respond_coordination(
        api, water["id"], "CLEAR", response_note=CLEARANCE_NOTE
    )
    assert cleared["coordination_status"] == "CLEARED"
    assert fixtures.read_project(api, project_id)["clearance_outstanding_count"] == 3

    validate_error(
        api.respond_coordination(
            water["id"], respond_payload("CLEAR", response_note=REPLAY_NOTE), COORDINATOR
        ),
        ApiErrorId.COORDINATION_NOT_PENDING,
        409,
    )

    replayed = validate_success(api.get_coordination(water["id"], COORDINATOR))
    assert replayed["coordination_status"] == "CLEARED"
    assert replayed["round_count"] == 1

    project = fixtures.read_project(api, project_id)
    assert project["clearance_outstanding_count"] == 3
    assert project["delivery_status"] == "COORDINATING"

    validate_error(
        api.advance_project(project_id, advance_payload("BID_READY"), ENGINEER),
        ApiErrorId.UTILITY_CLEARANCE_PENDING,
        409,
    )

    _rows, meta = validate_paginated(
        api.list_coordinations(
            COORDINATOR,
            {"project_id": project_id, "coordination_status": "CLEARED", "limit": 100},
        )
    )
    assert meta["total_count"] == 1
