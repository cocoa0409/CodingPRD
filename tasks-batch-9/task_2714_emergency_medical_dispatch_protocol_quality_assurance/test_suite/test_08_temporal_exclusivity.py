"""Half-open protocol windows and the buffered retraining-session window.

Two exclusivity checks with opposite endpoint conventions: protocol version
intervals are compared half-open, so touching endpoints are adjacency rather than
collision, while the retraining-session buffer is compared closed, so a touching
buffered endpoint really does collide.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import approx2
from test_helpers.test_users import ADMIN, DIRECTOR, SUPERVISOR

WORKING_CLOCK = "2026-08-20T00:00:00Z"


def _window_env(api):
    """Five DRAFT versions around one already-APPROVED baseline window."""
    program = fx.new_program(api, name="Verdant EMD QA", accreditation_body="IAED")
    baseline = fx.new_version(
        api,
        program["id"],
        version_label="MPDS-13.0",
        effective_from="2026-07-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    successor = fx.new_version(
        api,
        program["id"],
        version_label="MPDS-13.1",
        effective_from="2026-09-01T00:00:00Z",
    )
    predecessor = fx.new_version(
        api,
        program["id"],
        version_label="MPDS-12.9",
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-07-01T00:00:00Z",
    )
    straddler = fx.new_version(
        api,
        program["id"],
        version_label="MPDS-13.0-regional",
        effective_from="2026-08-15T00:00:00Z",
        effective_to="2026-10-01T00:00:00Z",
    )
    other_family = fx.new_version(
        api,
        program["id"],
        protocol_family="LOCAL_CARDSET",
        version_label="LOCAL-2.0",
        effective_from="2026-08-15T00:00:00Z",
        effective_to="2026-10-01T00:00:00Z",
    )
    fx.approve_version(api, baseline["id"], "baseline")
    return {
        "program_id": program["id"],
        "baseline_id": baseline["id"],
        "successor_id": successor["id"],
        "predecessor_id": predecessor["id"],
        "straddler_id": straddler["id"],
        "other_family_id": other_family["id"],
    }


def test_a_successor_starting_exactly_where_the_baseline_ends_approves(api):
    """PRD 3.2: "The comparison is half-open on both sides, so a version whose `effective_to`
    equals another's `effective_from` touches without colliding and is fine, while any
    genuine overlap — including an overlap with an open-ended interval that has no upper
    bound — is rejected with `ERR_PROTOCOL_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/protocol_version_windows_are_half_open_so_touching_endpoints_approve
    """
    env = _window_env(api)

    approved = validate_success(
        api.approve_protocol_version(
            env["successor_id"],
            {"approval_note": "successor starting where the baseline ends"},
            DIRECTOR,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["effective_to"] is None, "an open-ended successor still only touches"
    assert fx.get_version(api, env["baseline_id"])["status"] == "APPROVED"


def test_a_predecessor_ending_exactly_where_the_baseline_starts_approves(api):
    """PRD 3.1: "`effective_from` is the inclusive lower bound and `effective_to` the
    exclusive upper bound, with `effective_to` omitted or null meaning the interval runs
    forward without end."
    PRD 3.2: "The comparison is half-open on both sides, so a version whose `effective_to`
    equals another's `effective_from` touches without colliding and is fine, while any
    genuine overlap — including an overlap with an open-ended interval that has no upper
    bound — is rejected with `ERR_PROTOCOL_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/protocol_version_windows_are_half_open_so_touching_endpoints_approve
    """
    env = _window_env(api)
    fx.approve_version(api, env["successor_id"], "successor")

    approved = validate_success(
        api.approve_protocol_version(
            env["predecessor_id"],
            {"approval_note": "predecessor ending where the baseline starts"},
            DIRECTOR,
        )
    )
    assert approved["status"] == "APPROVED"


def test_a_window_straddling_two_adjacent_versions_is_refused_and_stays_a_draft(api):
    """PRD 3.2: "The interval check is the substantive gate: within one programme and one
    protocol family, the governing intervals of versions already in `APPROVED`, `ACTIVE` or
    `SUPERSEDED` must not overlap the interval of the version being approved."

    Design: Difficulty/resource_temporal_overlap/protocol_version_windows_are_half_open_so_touching_endpoints_approve
    """
    env = _window_env(api)
    fx.approve_version(api, env["successor_id"], "successor")
    fx.approve_version(api, env["predecessor_id"], "predecessor")

    response = api.approve_protocol_version(
        env["straddler_id"], {"approval_note": "straddling window"}, DIRECTOR
    )
    validate_error(response, err.ERR_PROTOCOL_WINDOW_OVERLAP)

    still_draft = fx.get_version(api, env["straddler_id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["approved_by_user_id"] is None


def test_the_same_straddling_window_in_another_card_set_family_approves(api):
    """PRD 3.2: "The interval check is the substantive gate: within one programme and one
    protocol family, the governing intervals of versions already in `APPROVED`, `ACTIVE` or
    `SUPERSEDED` must not overlap the interval of the version being approved."

    Design: Difficulty/resource_temporal_overlap/protocol_version_windows_are_half_open_so_touching_endpoints_approve
    """
    env = _window_env(api)
    fx.approve_version(api, env["successor_id"], "successor")
    fx.approve_version(api, env["predecessor_id"], "predecessor")
    validate_error(
        api.approve_protocol_version(
            env["straddler_id"], {"approval_note": "straddling window"}, DIRECTOR
        ),
        err.ERR_PROTOCOL_WINDOW_OVERLAP,
    )

    approved = validate_success(
        api.approve_protocol_version(
            env["other_family_id"],
            {"approval_note": "same window, different family"},
            DIRECTOR,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["protocol_family"] == "LOCAL_CARDSET"

    approved_ids = {
        row["id"]
        for row in validate_success(
            api.list_protocol_versions(
                env["program_id"], ADMIN, {"status": "APPROVED", "limit": 100}
            )
        )
    }
    assert approved_ids == {
        env["baseline_id"],
        env["successor_id"],
        env["predecessor_id"],
        env["other_family_id"],
    }
    drafts = validate_success(
        api.list_protocol_versions(
            env["program_id"], ADMIN, {"status": "DRAFT", "limit": 100}
        )
    )
    assert [row["id"] for row in drafts] == [env["straddler_id"]]


def _superseded_plan_with_a_completed_session(api):
    """A COMPLETED 10:00-11:00 session hanging off a plan that a later manual plan cancelled."""
    program = fx.new_program(
        api,
        name="Windrow EMD QA",
        accreditation_body="STATE_OEMS",
        hours_owed_restriction_threshold=6.0,
    )
    version = fx.new_approved_version(
        api, program["id"], version_label="MPDS-13.0",
        effective_from="2026-07-01T00:00:00Z",
    )
    dispatcher = fx.new_dispatcher(api, program["id"], employee_code="EMD-M01",
                                   full_name="Zaid Marchetti")
    fx.set_clock(api, WORKING_CLOCK)
    first_plan = fx.new_coaching_plan(
        api, dispatcher["id"], severity="ADVISORY", focus_area="CASE_ENTRY"
    )
    session = fx.new_session(
        api,
        first_plan["id"],
        version["id"],
        starts_at="2026-08-15T10:00:00Z",
        ends_at="2026-08-15T11:00:00Z",
        modality="CLASSROOM",
    )
    completed = fx.complete_session(api, session["id"])
    second_plan = fx.new_coaching_plan(
        api, dispatcher["id"], severity="STANDARD", focus_area="PRE_ARRIVAL_INSTRUCTIONS"
    )
    return {
        "program_id": program["id"],
        "version_id": version["id"],
        "dispatcher_id": dispatcher["id"],
        "first_plan_id": first_plan["id"],
        "second_plan_id": second_plan["id"],
        "session_id": session["id"],
        "completed": completed,
    }


def _back_to_back_request(version_id):
    return f.retraining_session_payload(
        version_id,
        starts_at="2026-08-15T11:00:00Z",
        ends_at="2026-08-15T12:00:00Z",
        modality="SIMULATION",
    )


def test_a_completed_session_on_a_cancelled_plan_still_blocks_a_back_to_back_booking(api):
    """PRD 3.8: "The new session's window is widened by **45 minutes on each side** and
    compared, inclusive of the endpoints, against every other `SCHEDULED` or `COMPLETED`
    session of the same dispatcher; any touching or overlap is refused with
    `ERR_SESSION_WINDOW_OVERLAP`."
    PRD 3.8: "Because the comparison is closed rather than half-open, two genuinely
    back-to-back sessions do collide — the buffer is a hard rest requirement, not a
    formality."

    Design: Difficulty/resource_temporal_overlap/session_buffer_counts_completed_sessions_and_releases_cancelled_ones
    """
    env = _superseded_plan_with_a_completed_session(api)
    blocker = fx.get_session(api, env["first_plan_id"], env["session_id"])
    assert blocker["status"] == "COMPLETED"
    assert blocker["duration_hours"] == approx2(1.00)
    cancelled_plan = fx.get_plan(api, env["first_plan_id"])
    assert cancelled_plan["status"] == "CANCELLED"
    assert cancelled_plan["closure_reason"] == "SUPERSEDED"
    assert fx.get_plan(api, env["second_plan_id"])["status"] == "ASSIGNED"

    response = api.create_retraining_session(
        env["second_plan_id"], _back_to_back_request(env["version_id"]), SUPERVISOR
    )
    validate_error(response, err.ERR_SESSION_WINDOW_OVERLAP)

    sessions = validate_success(
        api.list_retraining_sessions(env["second_plan_id"], SUPERVISOR, {"limit": 100})
    )
    assert sessions == [], f"the refused booking must create nothing, got {sessions}"
    assert fx.get_plan(api, env["second_plan_id"])["status"] == "ASSIGNED"


def test_cancelling_the_completed_session_releases_its_buffered_window(api):
    """PRD 3.8: "Sessions already `CANCELLED` release their window and no longer participate
    in the check."
    PRD 3.8: "A session in `SCHEDULED` may be cancelled, in which case `credited_hours` never
    changed and no ledger moves at all; a session already in `COMPLETED` may also be
    cancelled, which is a genuine compensating action: `completed_at` is cleared to null and
    `credited_hours` is recomputed over the remaining completed sessions, returning it to
    exactly its pre-completion value."

    Design: Difficulty/resource_temporal_overlap/session_buffer_counts_completed_sessions_and_releases_cancelled_ones
    """
    env = _superseded_plan_with_a_completed_session(api)
    validate_error(
        api.create_retraining_session(
            env["second_plan_id"], _back_to_back_request(env["version_id"]), SUPERVISOR
        ),
        err.ERR_SESSION_WINDOW_OVERLAP,
    )

    released = validate_success(
        api.cancel_retraining_session(
            env["session_id"], {"cancel_reason": "RESCHEDULED"}, SUPERVISOR
        )
    )
    assert released["status"] == "CANCELLED"
    assert released["completed_at"] is None

    booked = validate_success(
        api.create_retraining_session(
            env["second_plan_id"], _back_to_back_request(env["version_id"]), SUPERVISOR
        ),
        expected_status=201,
    )
    assert booked["status"] == "SCHEDULED"
    assert booked["duration_hours"] == approx2(1.00)
    assert fx.get_plan(api, env["second_plan_id"])["status"] == "IN_PROGRESS"


def test_a_buffered_endpoint_that_merely_touches_still_collides(api):
    """PRD 3.8: "The new session's window is widened by **45 minutes on each side** and
    compared, inclusive of the endpoints, against every other `SCHEDULED` or `COMPLETED`
    session of the same dispatcher; any touching or overlap is refused with
    `ERR_SESSION_WINDOW_OVERLAP`."
    PRD 3.8: "Because the comparison is closed rather than half-open, two genuinely
    back-to-back sessions do collide — the buffer is a hard rest requirement, not a
    formality."

    Design: Difficulty/resource_temporal_overlap/session_buffer_counts_completed_sessions_and_releases_cancelled_ones
    """
    env = _superseded_plan_with_a_completed_session(api)
    fx.cancel_session(api, env["session_id"], "RESCHEDULED")
    fx.new_session(
        api,
        env["second_plan_id"],
        env["version_id"],
        starts_at="2026-08-15T11:00:00Z",
        ends_at="2026-08-15T12:00:00Z",
        modality="SIMULATION",
    )

    touching = api.create_retraining_session(
        env["second_plan_id"],
        f.retraining_session_payload(
            env["version_id"],
            starts_at="2026-08-15T12:45:00Z",
            ends_at="2026-08-15T13:45:00Z",
            modality="ONE_ON_ONE",
        ),
        SUPERVISOR,
    )
    validate_error(touching, err.ERR_SESSION_WINDOW_OVERLAP)

    clear = validate_success(
        api.create_retraining_session(
            env["second_plan_id"],
            f.retraining_session_payload(
                env["version_id"],
                starts_at="2026-08-15T12:46:00Z",
                ends_at="2026-08-15T13:46:00Z",
                modality="ONE_ON_ONE",
            ),
            SUPERVISOR,
        ),
        expected_status=201,
    )
    assert clear["status"] == "SCHEDULED"
    assert clear["duration_hours"] == approx2(1.00)
