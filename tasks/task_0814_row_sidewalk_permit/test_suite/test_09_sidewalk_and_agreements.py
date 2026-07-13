"""Sidewalk obstructions (buffer + ADA clearance), encroachment execution,
permit date-range validation, and filtered pagination."""
from test_helpers import (
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_applicant_headers,
    create_sidewalk_obstruction_payload,
    create_encroachment_agreement_payload,
    fixtures,
)

REVIEWER_1 = TEST_USERS["reviewer_headers"]


def _obstruction(api, ctx, span_id, **overrides):
    return api.create_sidewalk_obstruction(
        ctx["permit_id"],
        create_sidewalk_obstruction_payload(span_id, **overrides),
        make_applicant_headers(ctx["app_id"]),
    )


def test_obstruction_within_buffer_rejected(api):
    """PRD §3.6: "a new obstruction must keep a gap of at least 3 days from every
    `ACTIVE` obstruction already on the same sidewalk span. Unlike the lane-closure
    rule, adjacency is not allowed here — the separation must be a full 3 days or
    more, so obstructions that merely touch or fall within the 3-day buffer are
    rejected with `ERR_SIDEWALK_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/sidewalk_obstruction_buffer_on_span
    """
    ctx = fixtures.setup_issued_permit(api, posted_cents=80000)
    span = fixtures.create_span(api, block_label="Main 100 N", side="NORTH",
                                width_ft=12, ada_min_clearance_ft=4.0)
    get_success_data(
        _obstruction(api, ctx, span["id"], start_date="2026-05-01", end_date="2026-05-10",
                     maintained_clearance_ft=5.0)
    )
    resp = _obstruction(api, ctx, span["id"], start_date="2026-05-12", end_date="2026-05-15",
                        maintained_clearance_ft=5.0)
    validate_error(resp, ApiErrorId.ERR_SIDEWALK_BUFFER_CONFLICT.value)


def test_obstruction_with_sufficient_gap_allowed(api):
    """PRD §3.6: "a new obstruction must keep a gap of at least 3 days from every
    `ACTIVE` obstruction already on the same sidewalk span."
    PRD §3.6: "A sidewalk obstruction is created directly in `ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/sidewalk_obstruction_buffer_on_span
    """
    ctx = fixtures.setup_issued_permit(api, posted_cents=80000)
    span = fixtures.create_span(api, block_label="Main 100 N", side="NORTH",
                                width_ft=12, ada_min_clearance_ft=4.0)
    get_success_data(
        _obstruction(api, ctx, span["id"], start_date="2026-05-01", end_date="2026-05-10",
                     maintained_clearance_ft=5.0)
    )
    # Second obstruction starts 2026-05-20, well beyond the 3-day buffer after 05-10.
    second = get_success_data(
        _obstruction(api, ctx, span["id"], start_date="2026-05-20", end_date="2026-05-25",
                     maintained_clearance_ft=5.0)
    )
    assert second["status"] == "ACTIVE"


def test_obstruction_below_ada_clearance_rejected(api):
    """PRD §3.6: "The maintained clearance must meet the span's floor:
    `maintained_clearance_ft` must be at least the span's `ada_min_clearance_ft`,
    or the request is rejected with `ERR_ADA_CLEARANCE`."

    Design: Corner/validations/ada_clearance_violation_to_error
    """
    ctx = fixtures.setup_issued_permit(api, posted_cents=80000)
    span = fixtures.create_span(api, block_label="Main 100 S", side="SOUTH",
                                width_ft=10, ada_min_clearance_ft=4.0)
    resp = _obstruction(api, ctx, span["id"], start_date="2026-05-01", end_date="2026-05-10",
                        maintained_clearance_ft=3.0)
    validate_error(resp, ApiErrorId.ERR_ADA_CLEARANCE.value)


def test_execute_encroachment_on_issued_permit(api):
    """PRD §3.8: "Execution moves the agreement from `PROPOSED` to `EXECUTED` and
    locks `agreed_fee_cents` equal to the `proposed_fee_cents` at that moment."

    Design: Corner/endpoints/encroachment_execute_on_issued_permit
    """
    ctx = fixtures.setup_issued_permit(api, posted_cents=80000)
    ea = get_success_data(
        api.create_encroachment_agreement(
            ctx["permit_id"],
            create_encroachment_agreement_payload(term_months=24, proposed_fee_cents=120000),
            make_applicant_headers(ctx["app_id"]),
        )
    )
    executed = get_success_data(api.execute_encroachment_agreement(ea["id"], REVIEWER_1))
    assert executed["status"] == "EXECUTED"
    assert executed["agreed_fee_cents"] == 120000


def test_permit_end_not_after_start_rejected(api):
    """PRD §3.2: "The `requested_end_date` must be strictly after the
    `requested_start_date`; otherwise the draft is rejected with
    `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/invalid_date_range_violation_to_error
    """
    app = fixtures.create_applicant(api)
    seg = fixtures.create_segment(api)
    resp = api.create_permit(
        {
            "applicant_id": app["id"],
            "street_segment_id": seg["id"],
            "primary_obstruction_type": "LANE",
            "requested_start_date": "2026-04-10",
            "requested_end_date": "2026-04-01",
        },
        make_applicant_headers(app["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value)


def test_permits_list_pagination_with_filter(api):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."
    PRD §3.2: "Permits may be fetched individually by any role, and listed —
    filtered by `applicant_id`, `street_segment_id`, or `status` query parameters
    — by administrators, reviewers, and applicants."

    Design: Corner/cross_cutting/permits_list_pagination_with_filter
    """
    app = fixtures.create_applicant(api)
    seg = fixtures.create_segment(api)
    headers = make_applicant_headers(app["id"])
    fixtures.create_draft_permit(api, app["id"], seg["id"],
                                 primary_obstruction_type="LANE",
                                 requested_start_date="2026-04-01", requested_end_date="2026-04-11")
    fixtures.create_draft_permit(api, app["id"], seg["id"],
                                 primary_obstruction_type="SIDEWALK",
                                 requested_start_date="2026-05-01", requested_end_date="2026-05-11")
    resp = api.list_permits(headers, params={"applicant_id": app["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
