"""
The two temporal-overlap boundaries of the specification: the closed symmetric
blackout buffer around a scheduled monitoring visit (PRD 3.6) and the half-open
collection window of a price cycle (PRD 3.3), together with the ladder positions
that pre-empt the overlap check (PRD 2.7).

Every test builds its own state from scratch through the documented endpoints,
because the server is restarted against an empty database before each one.
"""

from test_helpers import (
    ANALYST_HEADERS,
    SUPERVISOR_HEADERS,
    ApiErrorId,
    PriceCycleStatus,
    VisitOutcome,
    VisitStatus,
    VisitType,
    assert_field_values,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

# The anchor visit every blackout case is measured against, and the four instants
# at exactly seven and exactly eight days on either side of it.
_ANCHOR_AT = "2026-09-01T00:00:00Z"
_ANCHOR_AT_ISO = "2026-09-01T00:00:00.000Z"
_SEVEN_DAYS_AFTER = "2026-09-08T00:00:00Z"
_SEVEN_DAYS_BEFORE = "2026-08-25T00:00:00Z"
_EIGHT_DAYS_AFTER = "2026-09-09T00:00:00Z"
_EIGHT_DAYS_AFTER_ISO = "2026-09-09T00:00:00.000Z"
_EIGHT_DAYS_BEFORE = "2026-08-24T00:00:00Z"
_EIGHT_DAYS_BEFORE_ISO = "2026-08-24T00:00:00.000Z"


def _authorized_vendor_with_anchor_visit(api):
    """An AUTHORIZED vendor holding one ROUTINE visit still SCHEDULED for 1 Sep."""
    bundle = fixtures.authorized_vendor_setup(api)
    bundle["anchor_visit"] = fixtures.schedule_visit(
        api, bundle["vendor"]["id"], _ANCHOR_AT
    )
    return bundle


def _schedule_routine(api, vendor_id: str, scheduled_for: str):
    """Attempt one ROUTINE visit and hand back the raw response."""
    return api.create_monitoring_visit(
        factories.monitoring_visit_payload(
            vendor_id,
            visit_type=VisitType.ROUTINE.value,
            scheduled_for=scheduled_for,
        ),
        ANALYST_HEADERS,
    )


# ---------------------------------------------------------------------------
# The blackout buffer is a closed symmetric window
# ---------------------------------------------------------------------------


def test_visit_exactly_seven_days_on_either_side_of_a_scheduled_visit_conflicts(api):
    """
    A gap of exactly seven days from a still-scheduled visit conflicts, and it
    conflicts in both directions rather than only forward in time.

    "Finally, a blackout buffer keeps visits from clustering: if any other visit of
    the same vendor is still `SCHEDULED` and the gap between its `scheduled_for` and
    the new one is seven days or less in either direction, the new visit is refused
    with `ERR_VISIT_BLACKOUT_CONFLICT`. The buffer is a closed symmetric window, so
    a gap of exactly seven days conflicts and a gap of eight days does not."
    "**Day arithmetic** — cure periods, blackout buffers, election windows,
    reauthorization windows, and risk windows — adds or subtracts a fixed number of
    24-hour days."

    Design: Difficulty/resource_temporal_overlap/visit_scheduling_rejected_at_exactly_seven_day_symmetric_buffer
    """
    bundle = _authorized_vendor_with_anchor_visit(api)
    vendor_id = bundle["vendor"]["id"]

    # 2026-09-08 is exactly +7 days from the anchor of 2026-09-01.
    validate_error(
        _schedule_routine(api, vendor_id, _SEVEN_DAYS_AFTER),
        ApiErrorId.VISIT_BLACKOUT_CONFLICT.value,
    )
    # 2026-08-25 is exactly -7 days from the same anchor.
    validate_error(
        _schedule_routine(api, vendor_id, _SEVEN_DAYS_BEFORE),
        ApiErrorId.VISIT_BLACKOUT_CONFLICT.value,
    )

    visits, meta = validate_paginated(
        api.list_monitoring_visits(
            SUPERVISOR_HEADERS,
            {
                "vendor_id": vendor_id,
                "status": VisitStatus.SCHEDULED.value,
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] == 1, (
        f"both refused creates must leave the anchor alone, got {meta} / {visits}"
    )
    assert_field_values(
        fixtures.get_visit(api, bundle["anchor_visit"]["id"]),
        scheduled_for=_ANCHOR_AT_ISO,
        status=VisitStatus.SCHEDULED.value,
        outcome=VisitOutcome.PENDING.value,
        conducted_at=None,
    )


def test_visit_exactly_eight_days_on_either_side_of_a_scheduled_visit_is_booked(api):
    """
    A gap of exactly eight days clears the buffer on both sides, and each accepted
    visit is booked as a client-created scheduled visit.

    "Finally, a blackout buffer keeps visits from clustering: if any other visit of
    the same vendor is still `SCHEDULED` and the gap between its `scheduled_for` and
    the new one is seven days or less in either direction, the new visit is refused
    with `ERR_VISIT_BLACKOUT_CONFLICT`. The buffer is a closed symmetric window, so
    a gap of exactly seven days conflicts and a gap of eight days does not."
    "Client-created visits begin `SCHEDULED` with `auto_generated` false, an
    `outcome` of `PENDING`, an `overcharge_cents` of 0, a `stock_compliance_pct` of
    0.0, and `conducted_at` and `cancelled_reason` null."

    Design: Difficulty/resource_temporal_overlap/visit_scheduling_rejected_at_exactly_seven_day_symmetric_buffer
    """
    bundle = _authorized_vendor_with_anchor_visit(api)
    vendor_id = bundle["vendor"]["id"]

    # 2026-09-09 is exactly +8 days from the anchor of 2026-09-01.
    later = validate_success(
        _schedule_routine(api, vendor_id, _EIGHT_DAYS_AFTER), 201
    )
    assert_field_values(
        later,
        scheduled_for=_EIGHT_DAYS_AFTER_ISO,
        status=VisitStatus.SCHEDULED.value,
        auto_generated=False,
        outcome=VisitOutcome.PENDING.value,
        overcharge_cents=0,
        stock_compliance_pct=0.0,
        conducted_at=None,
        cancelled_reason=None,
    )

    # 2026-08-24 is 8 days before the anchor and 16 days before the visit just
    # booked, so it clears the buffer of both.
    earlier = validate_success(
        _schedule_routine(api, vendor_id, _EIGHT_DAYS_BEFORE), 201
    )
    assert_field_values(
        earlier,
        scheduled_for=_EIGHT_DAYS_BEFORE_ISO,
        status=VisitStatus.SCHEDULED.value,
        auto_generated=False,
    )

    visits, meta = validate_paginated(
        api.list_monitoring_visits(
            SUPERVISOR_HEADERS,
            {
                "vendor_id": vendor_id,
                "status": VisitStatus.SCHEDULED.value,
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] == 3, (
        f"expected the anchor plus both accepted visits, got {meta} / {visits}"
    )
    assert sorted(visit["scheduled_for"] for visit in visits) == [
        _EIGHT_DAYS_BEFORE_ISO,
        _ANCHOR_AT_ISO,
        _EIGHT_DAYS_AFTER_ISO,
    ], f"unexpected scheduled instants: {[v['scheduled_for'] for v in visits]}"


# ---------------------------------------------------------------------------
# Price cycle windows are half-open, and cheaper rules pre-empt the overlap test
# ---------------------------------------------------------------------------


def test_cycle_starting_at_the_previous_due_instant_is_open_and_a_millisecond_of_overlap_is_refused(
    api,
):
    """
    Because the collection window is half-open, a cycle beginning exactly at an
    existing cycle's due instant is accepted, while a window that intersects by a
    single millisecond is refused.

    "A `VendorUnitSupervisor` opens a cycle with a `cycle_code` unique across all
    cycles and a **half-open** collection window running from `submission_open_at`
    inclusive to `submission_due_at` exclusive." "The new window must also not
    intersect the half-open window of any existing cycle whose `status` is `OPEN`,
    `CLOSED`, or `PUBLISHED`; because the windows are half-open at their upper end,
    a new window beginning exactly at an existing window's `submission_due_at` is
    permitted, while any true overlap is refused with `ERR_CYCLE_WINDOW_OVERLAP`."
    "A new cycle starts `OPEN`, with `closed_at`, `published_at` null and
    `provisional_ceiling_count`, `published_ceiling_count`, and `skipped_pair_count`
    at 0."

    Design: Difficulty/resource_temporal_overlap/price_cycle_window_allows_touching_boundary_but_rejects_overlap
    """
    first = fixtures.create_price_cycle(
        api,
        cycle_code="2026Q3",
        submission_open_at="2026-08-01T00:00:00Z",
        submission_due_at="2026-09-01T00:00:00Z",
    )

    # [2026-09-01, 2026-10-01) begins exactly where [2026-08-01, 2026-09-01) ends.
    touching = validate_success(
        api.create_price_cycle(
            factories.price_cycle_payload(
                cycle_code="2026Q4",
                submission_open_at="2026-09-01T00:00:00Z",
                submission_due_at="2026-10-01T00:00:00Z",
            ),
            SUPERVISOR_HEADERS,
        ),
        201,
    )
    assert_field_values(
        touching,
        status=PriceCycleStatus.OPEN.value,
        submission_open_at="2026-09-01T00:00:00.000Z",
        submission_due_at="2026-10-01T00:00:00.000Z",
        closed_at=None,
        published_at=None,
        provisional_ceiling_count=0,
        published_ceiling_count=0,
        skipped_pair_count=0,
    )

    # Opening one millisecond before 2026-09-01 intersects both existing windows.
    validate_error(
        api.create_price_cycle(
            factories.price_cycle_payload(
                cycle_code="2026Q3-BIS",
                submission_open_at="2026-08-31T23:59:59.999Z",
                submission_due_at="2026-09-15T00:00:00Z",
            ),
            SUPERVISOR_HEADERS,
        ),
        ApiErrorId.CYCLE_WINDOW_OVERLAP.value,
    )

    unchanged = fixtures.get_price_cycle(api, first["id"])
    assert_field_values(
        unchanged,
        status=PriceCycleStatus.OPEN.value,
        submission_open_at="2026-08-01T00:00:00.000Z",
        submission_due_at="2026-09-01T00:00:00.000Z",
        version=first["version"],
    )


def test_inverted_window_and_duplicate_cycle_code_are_reported_before_any_overlap(api):
    """
    An empty window and a re-used cycle code are both decided before the overlap
    test runs, so neither ever reports the overlap error.

    "When a request violates more than one rule, exactly one error is returned: the
    one belonging to the lowest-numbered rule in the ladder below." "The two instants
    must satisfy the earlier being strictly before the later, or the create is
    refused with `ERR_INVALID_CYCLE_WINDOW` (HTTP 422)." "`cycle_code` uniqueness on
    `POST /price-cycles` — otherwise `ERR_DUPLICATE_CYCLE_CODE`." "`submission_open_at`
    strictly before `submission_due_at` on `POST /price-cycles` — otherwise
    `ERR_INVALID_CYCLE_WINDOW`." "Cycle window non-overlap on `POST /price-cycles` —
    otherwise `ERR_CYCLE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/price_cycle_window_allows_touching_boundary_but_rejects_overlap
    """
    incumbent = fixtures.create_price_cycle(
        api,
        cycle_code="2026Q3",
        submission_open_at="2026-08-01T00:00:00Z",
        submission_due_at="2026-09-01T00:00:00Z",
    )

    # [2026-08-15, 2026-08-15) is empty yet sits inside the existing window; the
    # window rule sits above the overlap rule in the ladder, so it decides.
    validate_error(
        api.create_price_cycle(
            factories.price_cycle_payload(
                cycle_code="2026Q3-DUP",
                submission_open_at="2026-08-15T00:00:00Z",
                submission_due_at="2026-08-15T00:00:00Z",
            ),
            SUPERVISOR_HEADERS,
        ),
        ApiErrorId.INVALID_CYCLE_WINDOW.value,
    )

    # Re-using the code with a window that cannot overlap anything still fails on
    # the code, which is the rule above both temporal rules.
    validate_error(
        api.create_price_cycle(
            factories.price_cycle_payload(
                cycle_code="2026Q3",
                submission_open_at="2026-11-01T00:00:00Z",
                submission_due_at="2026-12-01T00:00:00Z",
            ),
            SUPERVISOR_HEADERS,
        ),
        ApiErrorId.DUPLICATE_CYCLE_CODE.value,
    )

    # And re-using the code with a window that does overlap reports the code too.
    validate_error(
        api.create_price_cycle(
            factories.price_cycle_payload(
                cycle_code="2026Q3",
                submission_open_at="2026-08-10T00:00:00Z",
                submission_due_at="2026-08-20T00:00:00Z",
            ),
            SUPERVISOR_HEADERS,
        ),
        ApiErrorId.DUPLICATE_CYCLE_CODE.value,
    )

    # None of the three refused creates may have touched the incumbent cycle.
    assert_field_values(
        fixtures.get_price_cycle(api, incumbent["id"]),
        cycle_code="2026Q3",
        status=PriceCycleStatus.OPEN.value,
        submission_open_at="2026-08-01T00:00:00.000Z",
        submission_due_at="2026-09-01T00:00:00.000Z",
        version=incumbent["version"],
    )
