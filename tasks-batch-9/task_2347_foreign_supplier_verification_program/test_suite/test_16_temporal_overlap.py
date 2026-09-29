"""Two calendars, two opposite endpoint conventions.

The onsite-audit calendar compares closed intervals widened by a cool-off, so
touching endpoints conflict; the assignment calendar compares half-open windows
against a capacity, so touching endpoints are fine. Each is probed one day either
side of its boundary.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as err
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.factories import activity_payload, record_payload
from test_helpers.test_users import COMPLIANCE_OFFICER_HEADERS, make_qualified_individual_headers

FOLLOW_UP_AUDIT = dict(
    activity_type="ONSITE_AUDIT",
    frequency_per_year=1,
    justification_text=(
        "Follow up onsite audit window opened after the sanitation observations"
    ),
    window_start="2026-10-10T00:00:00Z",
    window_end="2026-10-31T00:00:00Z",
)
TOUCHING_AUDIT_RECORD = dict(
    outcome="PASS",
    performed_start="2026-10-14T00:00:00Z",
    performed_end="2026-10-16T00:00:00Z",
    findings_count=0,
    document_reference="AUD-2026-1014-RV",
)
SEPARATED_AUDIT_RECORD = dict(
    outcome="PASS",
    performed_start="2026-10-15T00:00:00Z",
    performed_end="2026-10-16T00:00:00Z",
    findings_count=0,
    document_reference="AUD-2026-1015-RV",
)


def _supplier_with_a_september_audit_on_file(api: ApiClient) -> SimpleNamespace:
    """One audit performed 2026-09-12 to 2026-09-14, and an October audit window."""
    world = fx.analyzed_program(api, hazards=[fx.HAZARD_LISTERIA])
    world.first_activity = fx.create_activity(
        api, world.pair_id, world.qi_a_id, world.qi_a_id, **fx.ACTIVITY_ONSITE_AUDIT
    )
    fx.review_activity(api, world.first_activity["id"], world.qi_b_id, "APPROVE")
    world.follow_up_activity = fx.create_activity(
        api, world.pair_id, world.qi_a_id, world.qi_b_id, **FOLLOW_UP_AUDIT
    )
    world.follow_up_activity_id = world.follow_up_activity["id"]
    fx.review_activity(
        api,
        world.follow_up_activity_id,
        world.qi_b_id,
        "APPROVE",
        reviewer_note="Follow up audit window approved by the reviewing qualified individual",
    )
    fx.set_clock(api, "2026-09-20T00:00:00Z")
    world.first_record = fx.file_record(
        api,
        world.first_activity["id"],
        world.qi_a_id,
        outcome="PASS",
        performed_start="2026-09-12T00:00:00Z",
        performed_end="2026-09-14T00:00:00Z",
        findings_count=0,
        document_reference="AUD-2026-0912-RV",
    )
    world.first_record_id = world.first_record["id"]
    fx.set_clock(api, "2026-11-01T00:00:00Z")
    return world


def test_second_audit_whose_cool_off_touches_the_first_is_refused(
    api: ApiClient,
) -> None:
    """The widened interval only touches, and touching is enough.

    "take the new record's closed interval from `performed_start` through
    `performed_end`, widen it by 30 days on each side, and compare it against the
    closed interval of every existing non-rescinded onsite-audit record on the same
    supplier. If the widened interval touches or overlaps any of them the filing is
    refused with `ERR_AUDIT_WINDOW_CONFLICT`. Because the intervals are closed,
    endpoints that merely touch are a conflict".

    Design: Difficulty/resource_temporal_overlap/onsite_audit_cooloff_closed_interval_conflict_on_supplier
    """
    world = _supplier_with_a_september_audit_on_file(api)

    response = api.create_verification_record(
        record_payload(world.follow_up_activity_id, **TOUCHING_AUDIT_RECORD),
        make_qualified_individual_headers(world.qi_b_id),
    )

    validate_error(response, err.ERR_AUDIT_WINDOW_CONFLICT, 409)
    assert fx.get_record(api, world.first_record_id)["record_status"] == "RECEIVED"
    rows, meta = validate_paginated(
        api.list_verification_records(
            COMPLIANCE_OFFICER_HEADERS, {"activity_id": world.follow_up_activity_id}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_second_audit_one_day_later_clears_the_cool_off_and_is_filed(
    api: ApiClient,
) -> None:
    """Moving the start by a single day clears the widened interval entirely.

    "onsite audits on one supplier must be genuinely separated". Because "the
    comparison is made pairwise against each existing record rather than against
    any merged union of them", the only interval that matters is the September one,
    and a start of 2026-10-15 no longer touches it.

    Design: Difficulty/resource_temporal_overlap/onsite_audit_cooloff_closed_interval_conflict_on_supplier
    """
    world = _supplier_with_a_september_audit_on_file(api)

    response = api.create_verification_record(
        record_payload(world.follow_up_activity_id, **SEPARATED_AUDIT_RECORD),
        make_qualified_individual_headers(world.qi_b_id),
    )

    record = validate_success(response, 201)
    assert record["record_status"] == "RECEIVED"
    assert record["performed_start"].startswith("2026-10-15T00:00:00")
    rows, meta = validate_paginated(
        api.list_verification_records(
            COMPLIANCE_OFFICER_HEADERS, {"activity_id": world.follow_up_activity_id}
        )
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1


# --- The assignment calendar, where adjacency is allowed --------------------
OVERLAPPING_REVIEW = dict(
    activity_type="RECORDS_REVIEW",
    frequency_per_year=1,
    justification_text=(
        "Overlapping records review assigned to the same part time qualified individual"
    ),
    window_start="2026-11-15T00:00:00Z",
    window_end="2026-12-15T00:00:00Z",
)
ADJACENT_REVIEW = dict(
    activity_type="RECORDS_REVIEW",
    frequency_per_year=1,
    justification_text=(
        "Adjacent records review starting exactly when the sampling window closes"
    ),
    window_start="2026-12-01T00:00:00Z",
    window_end="2026-12-05T00:00:00Z",
)


def _assignee_of_capacity_one_already_booked(api: ApiClient) -> SimpleNamespace:
    """A part-time individual holding the single assignment her capacity allows."""
    world = fx.single_qi_program(api)
    analysis = fx.create_hazard_analysis(api, world.pair_id, world.qi_a_id)
    fx.add_hazard(api, analysis["id"], world.qi_a_id, **fx.HAZARD_LISTERIA)
    fx.approve_analysis(api, analysis["id"], world.qi_a_id)
    assignee = fx.create_qualified_individual(
        api,
        world.importer_id,
        full_name="Eve Larsen",
        email="eve@northbrook.example",
        qualification_summary=(
            "Part time qualified individual available for one overlapping assignment"
        ),
        training_completed_at="2025-09-01T00:00:00Z",
        concurrent_activity_capacity=1,
    )
    world.assignee_id = assignee["id"]
    world.booked_activity = fx.create_activity(
        api,
        world.pair_id,
        world.qi_a_id,
        world.assignee_id,
        activity_type="SAMPLING_AND_TESTING",
        frequency_per_year=2,
        justification_text=(
            "November sampling campaign assigned to the part time qualified individual"
        ),
        window_start="2026-11-01T00:00:00Z",
        window_end="2026-12-01T00:00:00Z",
    )
    world.booked_activity_id = world.booked_activity["id"]
    return world


def _assignee_row(api: ApiClient, world: SimpleNamespace) -> dict:
    rows, _ = validate_paginated(
        api.list_importer_qualified_individuals(world.importer_id, COMPLIANCE_OFFICER_HEADERS)
    )
    return next(row for row in rows if row["id"] == world.assignee_id)


def test_overlapping_assignment_exceeds_the_capacity_of_one(api: ApiClient) -> None:
    """One overlapping window is already one too many at a capacity of 1.

    "Count the existing activities that share the same `assigned_qi_id`, whose
    `status` is `PROPOSED`, `CHANGES_REQUESTED` or `APPROVED`, and whose half-open
    window from `window_start` up to but excluding `window_end` overlaps the
    requested half-open window. That count must be strictly less than the assigned
    individual's `concurrent_activity_capacity`, otherwise the request is refused
    with `ERR_QI_WINDOW_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/qi_assignment_capacity_half_open_window_aggregate
    """
    world = _assignee_of_capacity_one_already_booked(api)

    response = api.create_verification_activity(
        activity_payload(world.pair_id, world.assignee_id, **OVERLAPPING_REVIEW),
        make_qualified_individual_headers(world.qi_a_id),
    )

    validate_error(response, err.ERR_QI_WINDOW_CAPACITY_EXCEEDED, 409)
    assert fx.get_activity(api, world.booked_activity_id)["status"] == "PROPOSED"
    assert _assignee_row(api, world)["active_assignment_count"] == 1


def test_assignment_starting_exactly_at_the_previous_window_end_is_accepted(
    api: ApiClient,
) -> None:
    """Adjacency is not overlap, so the same individual may take the next window.

    "Because the windows are half-open, adjacency does not overlap: an existing
    window whose `window_end` equals the new `window_start` never counts, and is
    always allowed." The new row starts "in `status` `PROPOSED` with
    `revision_count` 0", and "the assigned individual's `active_assignment_count`
    is recomputed".

    Design: Difficulty/resource_temporal_overlap/qi_assignment_capacity_half_open_window_aggregate
    """
    world = _assignee_of_capacity_one_already_booked(api)

    response = api.create_verification_activity(
        activity_payload(world.pair_id, world.assignee_id, **ADJACENT_REVIEW),
        make_qualified_individual_headers(world.qi_a_id),
    )

    activity = validate_success(response, 201)
    assert activity["status"] == "PROPOSED"
    assert activity["window_start"].startswith("2026-12-01T00:00:00")
    assert _assignee_row(api, world)["active_assignment_count"] == 2
    rows, meta = validate_paginated(
        api.list_verification_activities(
            COMPLIANCE_OFFICER_HEADERS, {"assigned_qi_id": world.assignee_id}
        )
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2
