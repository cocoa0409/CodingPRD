"""State-machine coverage of sessions, calendar events and informed decisions.

These three machines are all gated on the logical clock or on a strict ordering
between two instants, and two of them hide their product: continuing an event
returns the predecessor, and superseding a decision touches a row the caller
never named.

Each test translates exactly one instance of section 1.9 `state_machines`.
"""

from test_helpers import factories
from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_error,
    assert_error_is_one_of,
    assert_fields,
    assert_no_rows,
    assert_null_fields,
    assert_row_count,
    created,
    ok,
    only_row,
)
from test_helpers.fixtures import template_a, template_b
from test_helpers.test_users import make_client_portal_headers

_CLOCK_UTC = "2026-08-03T09:00:00.000Z"


def test_a_session_already_under_way_can_only_be_completed(api):
    """The three closures need disjoint clock windows and this one is mid-session.

    Cancelling wants the clock before the start and marking a no-show wants it at
    or after the end, so at half past only completion is reachable. Ten actual
    minutes are still billed at the thirty-minute floor.

    Design: Corner/state_machines/session_inside_its_own_window_rejects_cancel_and_no_show
    """
    env = template_a(api, clock="2026-08-03T08:00:00.000Z")
    session = created(
        api.create_session(
            factories.session_payload(
                env["matter_id"],
                language_code="es",
                interpreter_source="TELEPHONIC",
                purpose="HEARING_PREP",
            ),
            headers=env.supervisor,
        )
    )
    assert_fields(session, status="SCHEDULED")
    ok(api.set_clock("2026-08-03T09:30:00.000Z", headers=env.director))

    def transition(action, **payload):
        body = {"action": action}
        body.update(payload)
        return api.transition_session(session["id"], body, headers=env.supervisor)

    # the clock is no longer before the start
    assert_error(
        transition("CANCEL", closure_reason_code="CLIENT_UNAVAILABLE"),
        ERR_INVALID_STATE_TRANSITION,
    )
    # and not yet at the end
    assert_error(
        transition("MARK_NO_SHOW", closure_reason_code="CLIENT_UNAVAILABLE"),
        ERR_INVALID_STATE_TRANSITION,
    )

    completed = ok(transition("COMPLETE", actual_minutes=10))
    assert_fields(
        completed,
        status="COMPLETED",
        # the 30-minute minimum, telephonic at 6200 cents an hour, no surcharge on 'es'
        billed_minutes=30,
        billable_cents=3100,
    )
    assert_fields(env.matter(), interpretation_cost_cents=3100)


def _hearing(env):
    """One SCHEDULED master calendar hearing for the active lead."""
    return created(
        env.api.create_event(
            factories.event_payload(
                env["matter_id"],
                event_type="MASTER_CALENDAR_HEARING",
                starts_at_utc="2026-09-15T09:00:00.000Z",
                ends_at_utc="2026-09-15T10:00:00.000Z",
                location_code="EOIRCRT3",
                assigned_representative_id=env["atty_a_id"],
            ),
            headers=env.supervisor,
        )
    )


def test_continuing_a_hearing_hides_its_successor_behind_a_list_filter(api):
    """The transition returns the predecessor, so the new row needs a filter.

    Design: Corner/state_machines/calendar_continue_mints_successor_discoverable_only_by_continued_from_filter
    """
    env = template_a(api, clock=_CLOCK_UTC)
    hearing = _hearing(env)

    predecessor = ok(
        api.transition_event(
            hearing["id"],
            {
                "action": "CONTINUE",
                "successor_starts_at_utc": "2026-10-20T09:00:00.000Z",
                "successor_ends_at_utc": "2026-10-20T10:00:00.000Z",
            },
            headers=env.supervisor,
        )
    )
    assert_fields(predecessor, id=hearing["id"], status="CONTINUED")

    successor = only_row(
        api.list_events(
            params={"continued_from_event_id": hearing["id"]}, headers=env.supervisor
        )
    )
    assert_fields(
        successor,
        status="SCHEDULED",
        version=1,
        reschedule_count=0,
        matter_id=env["matter_id"],
        event_type="MASTER_CALENDAR_HEARING",
        location_code="EOIRCRT3",
        assigned_representative_id=env["atty_a_id"],
        starts_at_utc="2026-10-20T09:00:00.000Z",
        travel_buffer_minutes=45,
        continued_from_event_id=hearing["id"],
        coverage_gap_flag=False,
    )
    assert_row_count(
        api.list_events(params={"matter_id": env["matter_id"]}, headers=env.supervisor), 2
    )


def test_a_successor_touching_the_predecessors_end_is_refused(api):
    """"Strictly after" excludes the shared instant, and attendance is not yet recordable.

    Design: Corner/state_machines/calendar_continue_with_successor_at_or_before_predecessor_end_is_rejected
    """
    env = template_a(api, clock=_CLOCK_UTC)
    hearing = _hearing(env)

    def transition(action, **payload):
        body = {"action": action}
        body.update(payload)
        return api.transition_event(hearing["id"], body, headers=env.supervisor)

    # a successor beginning exactly when the predecessor ends. PRD 3.8 requires
    # "successor_starts_at_utc strictly after the predecessor's ends_at_utc" but
    # does not pin which catalogued id reports the breach, so either the shape id
    # or the transition-legality id of section 2.7 tier 4 is faithful.
    assert_error_is_one_of(
        transition(
            "CONTINUE",
            successor_starts_at_utc="2026-09-15T10:00:00.000Z",
            successor_ends_at_utc="2026-09-15T11:00:00.000Z",
        ),
        [ERR_VALIDATION, ERR_INVALID_STATE_TRANSITION],
    )
    # the clock is still six weeks before the hearing ends
    assert_error(transition("COMPLETE"), ERR_INVALID_STATE_TRANSITION)
    assert_error(transition("MARK_MISSED"), ERR_INVALID_STATE_TRANSITION)

    assert_fields(env.event(hearing["id"]), status="SCHEDULED", version=1)
    assert_no_rows(
        api.list_events(
            params={"continued_from_event_id": hearing["id"]}, headers=env.supervisor
        )
    )
    assert_fields(env.matter(), coverage_gap_flag=False)


def test_a_second_decision_of_the_same_type_supersedes_the_acknowledged_one(api):
    """Creation supersedes without being asked, which is why it carries a token.

    The older row is moved aside and pointed at its replacement, while the new row
    starts pending -- so immediately afterwards the matter holds no documented
    decision at all.

    Design: Corner/state_machines/second_informed_decision_of_same_type_supersedes_the_documented_one
    """
    env = template_b(api, clock=_CLOCK_UTC)
    portal = make_client_portal_headers(env["client_id"])

    first = created(
        api.create_informed_decision(
            factories.informed_decision_payload(
                env["matter_id"],
                env["lead_id"],
                env.matter_version(),
                risks_disclosed=["REMOVAL_RISK", "DETENTION_RISK"],
                alternatives_disclosed=["DO_NOTHING"],
            ),
            headers=env.lead_rep,
        )
    )
    assert_fields(first, status="PENDING", language_match_verified=True)
    acknowledged = ok(
        api.transition_informed_decision(
            first["id"], {"action": "ACKNOWLEDGE"}, headers=portal
        )
    )
    assert_fields(acknowledged, status="DOCUMENTED", acknowledged_at_utc=_CLOCK_UTC)

    version_before = env.matter_version()
    second = created(
        api.create_informed_decision(
            factories.informed_decision_payload(
                env["matter_id"],
                env["lead_id"],
                version_before,
                risks_disclosed=["REMOVAL_RISK", "DETENTION_RISK", "FEE_LOSS"],
                alternatives_disclosed=["DO_NOTHING", "ALTERNATIVE_RELIEF_PATH"],
            ),
            headers=env.lead_rep,
        )
    )
    assert_fields(second, status="PENDING", language_match_verified=True)
    assert_null_fields(second, "superseded_by_decision_id")

    superseded = env.informed_decision(first["id"])
    assert_fields(
        superseded,
        status="SUPERSEDED",
        superseded_by_decision_id=second["id"],
        acknowledged_at_utc=_CLOCK_UTC,
    )
    assert_no_rows(
        api.list_informed_decisions(
            params={"matter_id": env["matter_id"], "status": "DOCUMENTED"},
            headers=env.supervisor,
        )
    )
    pointed_at = only_row(
        api.list_informed_decisions(
            params={"superseded_by_decision_id": second["id"]}, headers=env.supervisor
        )
    )
    assert_fields(pointed_at, id=first["id"])
    assert env.matter_version() == version_before + 1, env.matter_version()
