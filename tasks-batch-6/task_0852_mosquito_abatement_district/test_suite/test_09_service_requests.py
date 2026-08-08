"""Public complaints: the two parallel axes, service levels, the reopen cycle and
the case-count partition."""

import test_helpers as fx
from test_helpers import MANAGER, ApiErrorId, validate_error, validate_success


def test_resolve_is_unreachable_from_assigned_and_needs_a_verdict(api):
    """PRD §3.10: "Resolution advances `INSPECTED → RESOLVED`, is performed by the
    same assigned technician, and requires a `resolution_note`."
    PRD §3.10: "Resolution stamps `resolved_at`, stores the note, and moves one
    case from the area's `request_open_count` to its `request_resolved_count`."
    PRD §3.10: "a `ROUTINE` complaint is due 120 hours after triage — five days — a
    `PRIORITY` complaint 48 hours after triage, and an `URGENT` complaint 24 hours
    after triage."

    Design: Corner/state_machines/corner_request_resolve_before_inspection_returns_not_verified
    """
    bundle = fx.setup_assigned_request(
        priority="URGENT",
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        request_overrides={"description": "Pooled water by the fence"},
    )
    assert bundle["request"]["due_at"] == "2026-06-02T00:00:00.000Z"
    tech_headers = fx.make_field_tech_headers(bundle["applicator"]["id"])

    premature = api.transition_service_request(
        bundle["request"]["id"],
        {"action": "RESOLVE", "resolution_note": "Nothing found"},
        tech_headers,
    )
    validate_error(premature, ApiErrorId.ERR_INVALID_TRANSITION.value, 409)

    fx.request_action(
        bundle["request"]["id"], "INSPECT", tech_headers,
        verification_status="FIELD_CONFIRMED",
    )
    resolved = validate_success(
        api.transition_service_request(
            bundle["request"]["id"],
            {"action": "RESOLVE", "resolution_note": "Treated and drained"},
            tech_headers,
        )
    )

    assert resolved["handling_status"] == "RESOLVED"
    assert resolved["resolved_at"] == "2026-06-01T00:00:00.000Z"
    area = fx.read_area(bundle["area"]["id"])
    assert area["request_open_count"] == 0
    assert area["request_resolved_count"] == 1
    fx.assert_request_count_partition(area)


def test_assignment_to_a_suspended_applicator_is_refused(api):
    """PRD §3.10: "The referenced applicator must have `status` of `ACTIVE`;
    assigning to a suspended applicator is refused with
    `ERR_APPLICATOR_SUSPENDED`."
    PRD §3.2: "Duty status is administratively togglable: a `DistrictAdmin` may set
    an applicator's `status` to `ACTIVE` or `SUSPENDED`."

    Design: Corner/state_machines/corner_request_assign_to_suspended_applicator_rejected
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator(license_category="LARVICIDE_ONLY")
    suspended = fx.set_applicator_status(tech["id"], "SUSPENDED")
    assert suspended["status"] == "SUSPENDED"
    request = fx.file_request(
        area["id"], category="ADULT_ACTIVITY", description="Swarming at dusk"
    )
    fx.request_action(request["id"], "TRIAGE", priority="ROUTINE")

    blocked = api.transition_service_request(
        request["id"], {"action": "ASSIGN", "assigned_applicator_id": tech["id"]}, MANAGER
    )
    validate_error(blocked, ApiErrorId.ERR_APPLICATOR_SUSPENDED.value, 409)

    fx.set_applicator_status(tech["id"], "ACTIVE")
    assigned = validate_success(
        api.transition_service_request(
            request["id"], {"action": "ASSIGN", "assigned_applicator_id": tech["id"]}, MANAGER
        )
    )

    assert assigned["handling_status"] == "ASSIGNED"
    assert assigned["assigned_applicator_id"] == tech["id"]
    assert assigned["due_at"] == "2026-06-06T00:00:00.000Z"


def test_reopen_window_closes_one_minute_after_thirty_days(api):
    """PRD §3.10: "A resolved complaint may be reopened by an `AbatementManager`
    within 30 days of `resolved_at`, inclusive at the boundary; later than that the
    request is refused with `ERR_REOPEN_WINDOW_EXPIRED` (HTTP 422)."
    PRD §3.10: "`due_at` is always measured from the request's *current*
    `triaged_at`, meaning the most recent triage including one reached by
    reopening, and never from the instant an escalation happened."

    Design: Corner/state_machines/corner_request_reopen_after_thirty_days_rejected
    """
    first = fx.setup_resolved_request(
        priority="ROUTINE", verification_status="UNFOUNDED",
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        resolution_note="No source found",
        request_overrides={"description": "First"},
    )
    area, tech = first["area"], first["applicator"]
    second = fx.file_request(
        area["id"], reporter_user_id="u-res-2", reporter_contact="b@example.com",
        description="Second", x_m=20, y_m=20,
    )
    fx.request_action(second["id"], "TRIAGE", priority="ROUTINE")
    fx.request_action(second["id"], "ASSIGN", assigned_applicator_id=tech["id"])
    fx.request_action(
        second["id"], "INSPECT", fx.make_field_tech_headers(tech["id"]),
        verification_status="UNFOUNDED",
    )
    fx.request_action(
        second["id"], "RESOLVE", fx.make_field_tech_headers(tech["id"]),
        resolution_note="No source found",
    )

    fx.set_clock("2026-07-01T00:00:00.000Z")
    reopened = validate_success(
        api.transition_service_request(first["request"]["id"], {"action": "REOPEN"}, MANAGER)
    )
    assert reopened["handling_status"] == "TRIAGED"
    assert reopened["triaged_at"] == "2026-07-01T00:00:00.000Z"
    assert reopened["due_at"] == "2026-07-06T00:00:00.000Z"

    fx.set_clock("2026-07-01T00:01:00.000Z")
    too_late = api.transition_service_request(second["id"], {"action": "REOPEN"}, MANAGER)
    validate_error(too_late, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED.value, 422)

    assert fx.read_request(second["id"])["handling_status"] == "RESOLVED"
    area_now = fx.read_area(area["id"])
    assert area_now["request_open_count"] == 1
    assert area_now["request_resolved_count"] == 1
    assert area_now["request_total_count"] == 2


def test_inconclusive_visit_blocks_resolution_until_a_re_inspection(api):
    """PRD §3.10: "Inspection advances `ASSIGNED → INSPECTED` and may optionally
    carry a `verification_status`. When it is supplied it must be `FIELD_CONFIRMED`
    or `UNFOUNDED`, and anything else is `ERR_VALIDATION`; when it is omitted the
    visit is recorded as inconclusive and the evidence axis stays `UNVERIFIED`."
    PRD §3.10: "Here the evidence axis finally gates the workflow: a complaint
    whose `verification_status` is still `UNVERIFIED` cannot be resolved and is
    refused with `ERR_REQUEST_NOT_VERIFIED` (HTTP 409) until a re-inspection
    supplies a verdict."

    Design: Corner/state_machines/corner_inconclusive_inspection_blocks_resolve_until_reinspection
    """
    bundle = fx.setup_assigned_request(
        priority="PRIORITY",
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        request_overrides={"category": "SPRAY_CONCERN",
                           "description": "Odour after last spray"},
    )
    tech_headers = fx.make_field_tech_headers(bundle["applicator"]["id"])

    inconclusive = validate_success(
        api.transition_service_request(
            bundle["request"]["id"], {"action": "INSPECT"}, tech_headers
        )
    )
    assert inconclusive["handling_status"] == "INSPECTED"
    assert inconclusive["verification_status"] == "UNVERIFIED"

    blocked = api.transition_service_request(
        bundle["request"]["id"],
        {"action": "RESOLVE", "resolution_note": "Closing without a finding"},
        tech_headers,
    )
    validate_error(blocked, ApiErrorId.ERR_REQUEST_NOT_VERIFIED.value, 409)

    fx.request_action(
        bundle["request"]["id"], "INSPECT", tech_headers,
        verification_status="FIELD_CONFIRMED",
    )
    resolved = validate_success(
        api.transition_service_request(
            bundle["request"]["id"],
            {"action": "RESOLVE", "resolution_note": "Source located and treated"},
            tech_headers,
        )
    )

    assert resolved["handling_status"] == "RESOLVED"
    assert resolved["verification_status"] == "FIELD_CONFIRMED"
    assert resolved["due_at"] == "2026-06-03T00:00:00.000Z"


def test_reopen_rewinds_the_workflow_axis_and_resets_the_evidence_axis(api):
    """PRD §3.10: "Reopening advances `RESOLVED → TRIAGED`, increases
    `reopen_count` by 1, resets `verification_status` to `UNVERIFIED` on its own
    axis, clears `assigned_applicator_id` back to null so the case must be
    re-assigned, re-stamps `triaged_at` with the logical clock, and recomputes
    `due_at` from that new triage instant against the **retained** `priority` —
    reopening never lowers a priority that escalation has raised."

    Design: Difficulty/non_linear_state_machine/service_request_two_axes_evolve_independently_across_reopen
    """
    bundle = fx.setup_resolved_request(
        priority="ROUTINE", verification_status="FIELD_CONFIRMED",
        request_overrides={"category": "STANDING_WATER",
                           "description": "Ditch full of larvae behind the school",
                           "x_m": 500, "y_m": 500},
        resolution_note="Catch basin treated",
    )

    reopened = validate_success(
        api.transition_service_request(bundle["request"]["id"], {"action": "REOPEN"}, MANAGER)
    )

    fx.assert_service_request(reopened)
    assert reopened["handling_status"] == "TRIAGED"
    assert reopened["verification_status"] == "UNVERIFIED"
    assert reopened["assigned_applicator_id"] is None
    assert reopened["reopen_count"] == 1
    assert reopened["priority"] == "ROUTINE"
    assert reopened["triaged_at"] == "2026-06-01T00:00:00.000Z"
    assert reopened["due_at"] == "2026-06-06T00:00:00.000Z"


def test_second_inspection_after_reopen_moves_only_the_evidence_axis(api):
    """PRD §3.10: "`verification_status` is the field-evidence axis, moving from
    `UNVERIFIED` to either `FIELD_CONFIRMED` or `UNFOUNDED`, advanced only by
    inspection and reset only by reopening."
    PRD §3.10: "An inconclusive first visit can be upgraded later by a
    re-inspection, a self-loop that leaves `handling_status` at `INSPECTED` while
    overwriting `verification_status` on its own axis."

    Design: Difficulty/non_linear_state_machine/service_request_two_axes_evolve_independently_across_reopen
    """
    bundle = fx.setup_resolved_request(
        priority="ROUTINE", verification_status="FIELD_CONFIRMED",
        request_overrides={"category": "STANDING_WATER",
                           "description": "Ditch full of larvae behind the school",
                           "x_m": 500, "y_m": 500},
        resolution_note="Catch basin treated",
    )
    tech_headers = fx.make_field_tech_headers(bundle["applicator"]["id"])
    fx.request_action(bundle["request"]["id"], "REOPEN")
    fx.request_action(
        bundle["request"]["id"], "ASSIGN",
        assigned_applicator_id=bundle["applicator"]["id"],
    )

    inspected = validate_success(
        api.transition_service_request(
            bundle["request"]["id"],
            {"action": "INSPECT", "verification_status": "UNFOUNDED"},
            tech_headers,
        )
    )

    assert inspected["handling_status"] == "INSPECTED"
    assert inspected["verification_status"] == "UNFOUNDED"
    assert inspected["reopen_count"] == 1
    assert inspected["priority"] == "ROUTINE"


def test_case_counters_partition_before_and_after_a_reopen(api):
    """PRD §2.10: "`request_open_count` plus `request_resolved_count` plus
    `request_closed_count` always equals `request_total_count`."
    PRD §2.10: "Reopening moves it back from resolved to open, restoring all four
    counters exactly to their pre-resolution values."

    Design: Difficulty/compensating_invariant/service_request_case_count_partition_unchanged_by_resolve_then_reopen
    """
    bundle = fx.setup_case_count_partition_area()
    before = fx.read_area(bundle["area"]["id"])
    assert before["request_total_count"] == 3
    assert before["request_open_count"] == 1
    assert before["request_resolved_count"] == 1
    assert before["request_closed_count"] == 1
    fx.assert_request_count_partition(before)

    validate_success(
        api.transition_service_request(
            bundle["request_a"]["id"], {"action": "REOPEN"}, MANAGER
        )
    )

    after = fx.read_area(bundle["area"]["id"])
    assert after["request_total_count"] == 3
    assert after["request_open_count"] == 2
    assert after["request_resolved_count"] == 0
    assert after["request_closed_count"] == 1
    fx.assert_request_count_partition(after)


def test_reopen_restores_the_case_without_disturbing_its_siblings(api):
    """PRD §2.10: "`request_total_count` counts every complaint ever filed for the
    area and never decreases."
    PRD §3.10: "It also moves one case back from `request_resolved_count` to
    `request_open_count`, restoring the four counters exactly to their
    pre-resolution values, and the cycle `RESOLVED → TRIAGED → ASSIGNED →
    INSPECTED → RESOLVED` may run again."
    PRD §3.10: "Closing directly from `RECEIVED` advances `RECEIVED → CLOSED` — the
    disposition for a duplicate or out-of-district complaint that never warranted
    triage — and moves one case from `request_open_count` to
    `request_closed_count`, leaving `verification_status` at `UNVERIFIED` forever."

    Design: Difficulty/compensating_invariant/service_request_case_count_partition_unchanged_by_resolve_then_reopen
    """
    bundle = fx.setup_case_count_partition_area()

    reopened = validate_success(
        api.transition_service_request(
            bundle["request_a"]["id"], {"action": "REOPEN"}, MANAGER
        )
    )

    assert reopened["handling_status"] == "TRIAGED"
    assert reopened["verification_status"] == "UNVERIFIED"
    assert reopened["assigned_applicator_id"] is None
    assert reopened["reopen_count"] == 1
    assert reopened["priority"] == "PRIORITY"
    assert reopened["due_at"] == "2026-06-03T00:00:00.000Z"
    assert fx.read_request(bundle["request_b"]["id"])["handling_status"] == "RECEIVED"
    assert fx.read_request(bundle["request_c"]["id"])["handling_status"] == "CLOSED"
