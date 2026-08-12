"""Difficulty queue A — resource_temporal_overlap instances."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case_in_fieldwork,
    create_interview_payload, create_collection_scope_payload,
    add_acknowledged_notice,
    make_investigator_headers, TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
GC = TEST_USERS["gc_headers"]


def test_interviewer_half_open_adjacency_accepted(api):
    """PRD §3.5: "First, the same `interviewer_id` may not have another
    interview in `SCHEDULED` or `UPJOHN_DELIVERED` whose half-open interval —
    start inclusive, end exclusive — intersects the requested window;
    adjacent windows where one's end equals the other's start are permitted.
    Violations are rejected with `ERR_INTERVIEWER_OVERLAP`."

    A second interview starting exactly at the first's end (15:00 == 15:00)
    is accepted.

    Design: Difficulty/resource_temporal_overlap/interviewer_half_open_adjacency
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="Case TO-1", allegation_category="HARASSMENT", severity="MEDIUM",
        department="Ops",
    )
    case = bundle["case"]
    get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-10T14:00:00Z",
            scheduled_end="2026-05-10T15:00:00Z",
        ),
        INV,
    ))
    resp = api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-2", interviewer_id="inv-9",
            scheduled_start="2026-05-10T15:00:00Z",
            scheduled_end="2026-05-10T16:00:00Z",
        ),
        INV,
    )
    second = validate_success(resp, expected_status=201)
    assert second["status"] == "SCHEDULED"


def test_interviewer_half_open_adjacency_overlap_rejected(api):
    """PRD §3.5: "First, the same `interviewer_id` may not have another
    interview in `SCHEDULED` or `UPJOHN_DELIVERED` whose half-open interval
    — start inclusive, end exclusive — intersects the requested window;
    adjacent windows where one's end equals the other's start are permitted.
    Violations are rejected with `ERR_INTERVIEWER_OVERLAP`."

    A window starting inside the first's window (14:30) overlaps and is
    rejected.

    Design: Difficulty/resource_temporal_overlap/interviewer_half_open_adjacency
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="Case TO-1", allegation_category="HARASSMENT", severity="MEDIUM",
        department="Ops",
    )
    case = bundle["case"]
    get_success_data(api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-1", interviewer_id="inv-9",
            scheduled_start="2026-05-10T14:00:00Z",
            scheduled_end="2026-05-10T15:00:00Z",
        ),
        INV,
    ))
    resp = api.create_interview(
        case["id"],
        create_interview_payload(
            witness_ref="W-3", interviewer_id="inv-9",
            scheduled_start="2026-05-10T14:30:00Z",
            scheduled_end="2026-05-10T15:30:00Z",
        ),
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_INTERVIEWER_OVERLAP, expected_status=409)


def test_scope_window_closed_interval_touching_conflicts(api):
    """PRD §3.4: "Two scopes of the same case with the same `custodian_ref`
    and `data_source` may not have overlapping planned windows while either
    is in `PROPOSED`, `APPROVED`, or `IN_PROGRESS`; the closed-interval
    intersection test treats touching endpoints as a conflict
    (`ERR_SCOPE_OVERLAP`)."

    A window [05-10, 05-15] against [05-05, 05-10] is rejected because the
    closed intervals share the 05-10 endpoint.

    Design: Difficulty/resource_temporal_overlap/scope_window_closed_interval_touching_conflicts
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="Case TO-2", allegation_category="DATA_BREACH", severity="HIGH",
        department="IT",
    )
    case = bundle["case"]
    notice = add_acknowledged_notice(case["id"], custodian_ref="EMP-100")
    get_success_data(api.create_collection_scope(
        case["id"],
        create_collection_scope_payload(
            custodian_ref="EMP-100", data_source="EMAIL",
            planned_start="2026-05-05T00:00:00Z", planned_end="2026-05-10T00:00:00Z",
            preservation_notice_id=notice["id"],
        ),
        INV,
    ))
    resp = api.create_collection_scope(
        case["id"],
        create_collection_scope_payload(
            custodian_ref="EMP-100", data_source="EMAIL",
            planned_start="2026-05-10T00:00:00Z", planned_end="2026-05-15T00:00:00Z",
            preservation_notice_id=notice["id"],
        ),
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_SCOPE_OVERLAP, expected_status=409)


def test_scope_window_closed_interval_disjoint_accepted(api):
    """PRD §3.4: "Two scopes of the same case with the same `custodian_ref`
    and `data_source` may not have overlapping planned windows ... the
    closed-interval intersection test treats touching endpoints as a
    conflict (`ERR_SCOPE_OVERLAP`)."
    PRD §3.4: "A new scope enters `PROPOSED`..."

    A disjoint window [05-11, 05-15] does not intersect [05-05, 05-10] and
    is accepted with status PROPOSED.

    Design: Difficulty/resource_temporal_overlap/scope_window_closed_interval_touching_conflicts
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="Case TO-2", allegation_category="DATA_BREACH", severity="HIGH",
        department="IT",
    )
    case = bundle["case"]
    notice = add_acknowledged_notice(case["id"], custodian_ref="EMP-100")
    get_success_data(api.create_collection_scope(
        case["id"],
        create_collection_scope_payload(
            custodian_ref="EMP-100", data_source="EMAIL",
            planned_start="2026-05-05T00:00:00Z", planned_end="2026-05-10T00:00:00Z",
            preservation_notice_id=notice["id"],
        ),
        INV,
    ))
    resp = api.create_collection_scope(
        case["id"],
        create_collection_scope_payload(
            custodian_ref="EMP-100", data_source="EMAIL",
            planned_start="2026-05-11T00:00:00Z", planned_end="2026-05-15T00:00:00Z",
            preservation_notice_id=notice["id"],
        ),
        INV,
    )
    s3 = validate_success(resp, expected_status=201)
    assert s3["status"] == "PROPOSED"
