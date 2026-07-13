"""Lane-closure creation guards: half-open overlap on a segment, the utility-cut
moratorium boundary, and state-precedence over the moratorium check."""
from test_helpers import (
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_applicant_headers,
    create_lane_closure_payload,
    fixtures,
)

REVIEWER_1 = TEST_USERS["reviewer_headers"]


def _closure(api, ctx, **overrides):
    return api.create_lane_closure(
        ctx["permit_id"],
        create_lane_closure_payload(ctx["seg_id"], **overrides),
        make_applicant_headers(ctx["app_id"]),
    )


def test_overlapping_closure_rejected(api):
    """PRD §3.5: "a new closure must not overlap any existing closure in `PLANNED`
    or `ACTIVE` status on the same street segment. Because the intervals are
    half-open, two closures that merely touch — where one's `end_date` equals the
    other's `start_date` — do not overlap and are permitted; any true overlap is
    rejected with `ERR_CLOSURE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/lane_closure_halfopen_overlap_on_segment
    """
    # 19-day COMMERCIAL/LANE window => estimated fee 67000, required bond 134000
    # (PRD §3.3: required = max(50000, 2 * estimated fee)); provision accordingly.
    ctx = fixtures.setup_issued_permit(
        api, requested_start_date="2026-05-01", requested_end_date="2026-05-20",
        posted_cents=134000,
    )
    get_success_data(_closure(api, ctx, start_date="2026-05-01", end_date="2026-05-10"))
    get_success_data(_closure(api, ctx, start_date="2026-05-10", end_date="2026-05-15"))
    resp = _closure(api, ctx, start_date="2026-05-05", end_date="2026-05-12")
    validate_error(resp, ApiErrorId.ERR_CLOSURE_CONFLICT.value)


def test_adjacent_closure_allowed(api):
    """PRD §3.5: "two closures that merely touch — where one's `end_date` equals
    the other's `start_date` — do not overlap and are permitted; any true overlap
    is rejected with `ERR_CLOSURE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/lane_closure_halfopen_overlap_on_segment
    """
    # 19-day COMMERCIAL/LANE window => required bond 134000 (PRD §3.3).
    ctx = fixtures.setup_issued_permit(
        api, requested_start_date="2026-05-01", requested_end_date="2026-05-20",
        posted_cents=134000,
    )
    get_success_data(_closure(api, ctx, start_date="2026-05-01", end_date="2026-05-10"))
    adjacent = get_success_data(
        _closure(api, ctx, start_date="2026-05-10", end_date="2026-05-15")
    )
    assert adjacent["status"] == "PLANNED"


def test_utility_cut_on_moratorium_end_date_allowed(api):
    """PRD §3.5: "A `start_date` strictly before the `moratorium_end_date` is
    rejected with `ERR_UTILITY_CUT_MORATORIUM`, and a `start_date` exactly equal
    to the `moratorium_end_date` is allowed."

    Design: Difficulty/boundary_precision_check/moratorium_end_date_inclusive_boundary
    """
    ctx = fixtures.setup_issued_permit(
        api, zone_class="RESIDENTIAL", last_repaved_date="2025-01-01",
        posted_cents=50000, block_label="Elm 9",
    )
    # moratorium_end = 2025-01-01 + 2y = 2027-01-01
    closure = get_success_data(
        _closure(
            api, ctx, start_date="2027-01-01", end_date="2027-01-05",
            requires_utility_cut=True,
        )
    )
    assert closure["status"] == "PLANNED"
    assert closure["start_date"] == "2027-01-01"


def test_utility_cut_before_moratorium_end_rejected(api):
    """PRD §3.5: "A `start_date` strictly before the `moratorium_end_date` is
    rejected with `ERR_UTILITY_CUT_MORATORIUM`, and a `start_date` exactly equal
    to the `moratorium_end_date` is allowed."

    Design: Difficulty/boundary_precision_check/moratorium_end_date_inclusive_boundary
    """
    ctx = fixtures.setup_issued_permit(
        api, zone_class="RESIDENTIAL", last_repaved_date="2025-01-01",
        posted_cents=50000, block_label="Elm 9",
    )
    resp = _closure(
        api, ctx, start_date="2026-12-31", end_date="2027-01-04",
        requires_utility_cut=True,
    )
    validate_error(resp, ApiErrorId.ERR_UTILITY_CUT_MORATORIUM.value)


def test_utility_cut_moratorium_rejected(api):
    """PRD §3.5: "when the new closure's `requires_utility_cut` is true, it is
    subject to the pavement-cut moratorium: its `start_date` must fall on or after
    the segment's `moratorium_end_date`."

    Design: Corner/validations/utility_cut_moratorium_rejected_violation_to_error
    """
    ctx = fixtures.setup_issued_permit(
        api, zone_class="RESIDENTIAL", last_repaved_date="2025-01-01",
        posted_cents=50000, block_label="Elm 7",
    )
    resp = _closure(
        api, ctx, start_date="2026-12-31", end_date="2027-01-04",
        requires_utility_cut=True,
    )
    validate_error(resp, ApiErrorId.ERR_UTILITY_CUT_MORATORIUM.value)


def test_state_error_precedes_moratorium_under_review(api):
    """PRD §3.5: "Creating a lane closure requires the parent permit to be
    `ISSUED`; otherwise the attempt is rejected with `ERR_PERMIT_NOT_ISSUED`."
    PRD §2.9: "After existence come date-range sanity checks
    (`ERR_INVALID_DATE_RANGE`), then state-machine preconditions
    (`ERR_INVALID_PERMIT_STATE`, `ERR_PERMIT_NOT_ISSUED`,
    `ERR_INVALID_CLOSURE_STATE`, `ERR_INVALID_STATE`, `ERR_NOT_YET_EXPIRED`),
    then the bond-post optimistic-concurrency check (`ERR_STALE_PERMIT_VERSION`)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_lane_closure_create
    """
    app = fixtures.create_applicant(api)
    seg = fixtures.create_segment(
        api, zone_class="RESIDENTIAL", last_repaved_date="2025-01-01", block_label="Elm 5"
    )
    headers = make_applicant_headers(app["id"])
    permit = fixtures.create_draft_permit(
        api, app["id"], seg["id"],
        requested_start_date="2026-06-01", requested_end_date="2026-06-10",
    )
    get_success_data(api.submit_permit(permit["id"], headers))  # -> UNDER_REVIEW, not ISSUED
    resp = api.create_lane_closure(
        permit["id"],
        create_lane_closure_payload(
            seg["id"], start_date="2026-06-01", end_date="2026-06-05",
            requires_utility_cut=True,
        ),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED.value)


def test_state_error_precedes_moratorium_on_draft(api):
    """PRD §3.5: "Creating a lane closure requires the parent permit to be
    `ISSUED`; otherwise the attempt is rejected with `ERR_PERMIT_NOT_ISSUED`."
    PRD §2.9: "the utility-cut moratorium (`ERR_UTILITY_CUT_MORATORIUM`)" appears
    after "state-machine preconditions" in the "fixed priority order so that the
    returned `error_id` is deterministic."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_lane_closure_create
    """
    app = fixtures.create_applicant(api)
    seg = fixtures.create_segment(
        api, zone_class="RESIDENTIAL", last_repaved_date="2025-01-01", block_label="Elm 6"
    )
    headers = make_applicant_headers(app["id"])
    permit = fixtures.create_draft_permit(
        api, app["id"], seg["id"],
        requested_start_date="2026-06-01", requested_end_date="2026-06-10",
    )
    # Permit left in DRAFT (never submitted) — also a not-ISSUED state.
    resp = api.create_lane_closure(
        permit["id"],
        create_lane_closure_payload(
            seg["id"], start_date="2026-06-01", end_date="2026-06-05",
            requires_utility_cut=True,
        ),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED.value)
