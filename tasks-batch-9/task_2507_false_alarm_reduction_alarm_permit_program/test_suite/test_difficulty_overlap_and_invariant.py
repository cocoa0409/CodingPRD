"""Interval collision geometry for hearing sessions and suspension orders, plus
the compensating money and counting invariants behind a void and a remand.

The two geometries in this file are deliberately different and must not be
mixed: hearing sessions are half-open with a symmetric strict 15-minute buffer,
while suspension orders are closed intervals with a zero buffer.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID, get_success_data, validate_error,
    validate_error_is_one_of, validate_paginated, validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U


def test_docket_touching_previous_session_end_collides_and_other_officer_is_free(api):
    """A session starting exactly when the same officer's session ends is refused,
    while the identical interval is accepted for a different officer.

    PRD §3.6: "A proposed session is compared against that officer's existing
    dockets in `OPEN`, `CLOSED_FOR_SCHEDULING` or `HELD` — a `CANCELLED` docket
    releases its interval and is ignored — and rejected with
    `ERR_DOCKET_SESSION_OVERLAP` if a conflict is found."
    PRD §3.6: "Both arms are strict and the buffer is symmetric, so back-to-back
    sessions collide — a new session starting exactly at an existing session's
    end leaves a zero-minute gap, which is under the buffer — and the earliest
    legal back-to-back start is exactly the existing `session_end` plus 15
    minutes, since strictness makes that value pass."
    PRD §3.6: "Dockets belonging to different officers never collide however
    their intervals sit."

    The existing session ends at 2026-03-10T12:00Z, so 12:00 is strictly before
    12:00 plus 15 minutes and the zero-length gap is a conflict; the same
    09:00-12:00 window for the second officer is compared against that officer's
    own (empty) calendar and therefore passes.

    Design: Difficulty/resource_temporal_overlap/docket_touching_the_previous_session_end_collides_and_cancellation_frees_the_interval
    """
    X.set_clock(api, "2026-03-01T00:00:00Z")
    base_docket = X.create_docket(
        api,
        "2026-03-10T09:00:00Z",
        "2026-03-10T12:00:00Z",
        officer_user_id=U.HEARING_OFFICER_ID,
        location="Hearing Room A",
        capacity=4,
    )

    touching = api.create_hearing_docket(
        F.hearing_docket_payload(
            U.HEARING_OFFICER_ID,
            "2026-03-10T12:00:00Z",
            "2026-03-10T14:00:00Z",
            location="Hearing Room A",
            capacity=4,
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(touching, E.ERR_DOCKET_SESSION_OVERLAP, expected_status=409)

    other_officer = api.create_hearing_docket(
        F.hearing_docket_payload(
            U.HEARING_OFFICER_ID_2,
            "2026-03-10T09:00:00Z",
            "2026-03-10T12:00:00Z",
            location="Hearing Room B",
            capacity=4,
        ),
        U.PROGRAM_ADMIN,
    )
    created = A.data_of(other_officer, 201)
    A.assert_status(created, "OPEN")
    assert created["hearing_officer_user_id"] == U.HEARING_OFFICER_ID_2
    assert created["session_start"] == "2026-03-10T09:00:00Z"
    assert created["session_end"] == "2026-03-10T12:00:00Z"

    unchanged = A.data_of(api.get_hearing_docket(base_docket, U.PROGRAM_ADMIN))
    A.assert_status(unchanged, "OPEN")
    assert unchanged["scheduled_appeal_count"] == 0

    only_first_officer = api.list_hearing_dockets(
        U.PROGRAM_ADMIN, {"hearing_officer_user_id": U.HEARING_OFFICER_ID}
    )
    rows = A.assert_total_count(only_first_officer, 1)
    assert rows[0]["id"] == base_docket


def test_cancelling_the_earlier_docket_frees_the_touching_interval(api):
    """Cancelling the earlier session releases its interval, so the previously
    refused back-to-back window becomes bookable for the same officer.

    PRD §3.6: "A proposed session is compared against that officer's existing
    dockets in `OPEN`, `CLOSED_FOR_SCHEDULING` or `HELD` — a `CANCELLED` docket
    releases its interval and is ignored — and rejected with
    `ERR_DOCKET_SESSION_OVERLAP` if a conflict is found."
    PRD §3.6: "Cancelling a docket is likewise available symmetrically from
    `OPEN` or `CLOSED_FOR_SCHEDULING`, takes an optional `cancellation_reason`,
    and lands in the terminal `CANCELLED`."
    PRD §3.6: "Its consequences cascade downward: every appeal seated on it in
    `SCHEDULED` reverts to `FILED` with `hearing_docket_id` cleared, returning to
    the unscheduled pool to await a new session; `scheduled_appeal_count` is
    reset to 0; the session's interval is released for overlap purposes; and
    `version` rises by 1."

    The 12:00-14:00 window is refused while the 09:00-12:00 session is OPEN and
    accepted once that session is CANCELLED, leaving the officer with two rows:
    one CANCELLED and one OPEN.

    Design: Difficulty/resource_temporal_overlap/docket_touching_the_previous_session_end_collides_and_cancellation_frees_the_interval
    """
    X.set_clock(api, "2026-03-01T00:00:00Z")
    base_docket = X.create_docket(
        api,
        "2026-03-10T09:00:00Z",
        "2026-03-10T12:00:00Z",
        officer_user_id=U.HEARING_OFFICER_ID,
        location="Hearing Room A",
        capacity=4,
    )

    refused = api.create_hearing_docket(
        F.hearing_docket_payload(
            U.HEARING_OFFICER_ID,
            "2026-03-10T12:00:00Z",
            "2026-03-10T14:00:00Z",
            location="Hearing Room A",
            capacity=4,
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(refused, E.ERR_DOCKET_SESSION_OVERLAP, expected_status=409)

    cancelled = A.data_of(
        api.cancel_docket(
            base_docket,
            {"cancellation_reason": "Officer reassigned to an emergency arraignment calendar."},
            U.PROGRAM_ADMIN,
        )
    )
    A.assert_status(cancelled, "CANCELLED")
    assert cancelled["scheduled_appeal_count"] == 0

    accepted = A.data_of(
        api.create_hearing_docket(
            F.hearing_docket_payload(
                U.HEARING_OFFICER_ID,
                "2026-03-10T12:00:00Z",
                "2026-03-10T14:00:00Z",
                location="Hearing Room A",
                capacity=4,
            ),
            U.PROGRAM_ADMIN,
        ),
        201,
    )
    A.assert_status(accepted, "OPEN")
    assert accepted["session_start"] == "2026-03-10T12:00:00Z"
    assert accepted["session_end"] == "2026-03-10T14:00:00Z"

    listing = api.list_hearing_dockets(
        U.PROGRAM_ADMIN, {"hearing_officer_user_id": U.HEARING_OFFICER_ID}
    )
    rows = A.assert_total_count(listing, 2)
    by_id = {row["id"]: row["status"] for row in rows}
    assert by_id[base_docket] == "CANCELLED"
    assert by_id[accepted["id"]] == "OPEN"


def test_docket_after_neighbour_is_legal_only_from_exactly_fifteen_minutes_later(api):
    """On the later side of an existing session, a start at 12:14 is refused and a
    start at exactly 12:15 is accepted.

    PRD §3.6: "The intervals are half-open, and a 15-minute turnaround buffer is
    applied on both sides of the existing session: a conflict exists when the new
    `session_start` is strictly before the existing `session_end` plus 15 minutes
    **and** the existing `session_start` is strictly before the new `session_end`
    plus 15 minutes."
    PRD §3.6: "Both arms are strict and the buffer is symmetric, so back-to-back
    sessions collide — a new session starting exactly at an existing session's
    end leaves a zero-minute gap, which is under the buffer — and the earliest
    legal back-to-back start is exactly the existing `session_end` plus 15
    minutes, since strictness makes that value pass."
    PRD §3.6: "Seat capacity is a separate gate applied at scheduling time, not
    at session creation; overlap and capacity never substitute for one another."

    The existing session runs 09:00-12:00, so the buffered edge is 12:00 plus 15
    minutes, that is 12:15. A start of 12:14 is strictly before 12:15 and
    collides; a start of exactly 12:15 is not strictly before it and passes.

    Design: Difficulty/resource_temporal_overlap/docket_session_is_legal_only_from_exactly_fifteen_minutes_after_the_neighbouring_session
    """
    X.set_clock(api, "2026-03-01T00:00:00Z")
    middle = X.create_docket(
        api,
        "2026-03-12T09:00:00Z",
        "2026-03-12T12:00:00Z",
        officer_user_id=U.HEARING_OFFICER_ID,
        location="Hearing Room A",
        capacity=4,
    )

    one_minute_short = api.create_hearing_docket(
        F.hearing_docket_payload(
            U.HEARING_OFFICER_ID,
            "2026-03-12T12:14:00Z",
            "2026-03-12T13:00:00Z",
            location="Hearing Room A",
            capacity=4,
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(one_minute_short, E.ERR_DOCKET_SESSION_OVERLAP, expected_status=409)

    assert X.plus_minutes("2026-03-12T12:00:00Z", C.DOCKET_BUFFER_MINUTES) == "2026-03-12T12:15:00Z"
    exactly_buffered = A.data_of(
        api.create_hearing_docket(
            F.hearing_docket_payload(
                U.HEARING_OFFICER_ID,
                "2026-03-12T12:15:00Z",
                "2026-03-12T14:00:00Z",
                location="Hearing Room A",
                capacity=4,
            ),
            U.PROGRAM_ADMIN,
        ),
        201,
    )
    A.assert_status(exactly_buffered, "OPEN")
    assert exactly_buffered["session_start"] == "2026-03-12T12:15:00Z"
    assert exactly_buffered["scheduled_appeal_count"] == 0
    assert exactly_buffered["capacity"] == 4

    still_open = A.data_of(api.get_hearing_docket(middle, U.PROGRAM_ADMIN))
    A.assert_status(still_open, "OPEN")
    assert still_open["scheduled_appeal_count"] == 0
    assert still_open["capacity"] == 4


def test_docket_before_neighbour_is_legal_only_up_to_fifteen_minutes_earlier(api):
    """On the earlier side of an existing session, an end at 08:46 is refused and
    an end at exactly 08:45 is accepted.

    PRD §3.6: "The intervals are half-open, and a 15-minute turnaround buffer is
    applied on both sides of the existing session: a conflict exists when the new
    `session_start` is strictly before the existing `session_end` plus 15 minutes
    **and** the existing `session_start` is strictly before the new `session_end`
    plus 15 minutes."
    PRD §3.6: "Both arms are strict and the buffer is symmetric, so back-to-back
    sessions collide — a new session starting exactly at an existing session's
    end leaves a zero-minute gap, which is under the buffer — and the earliest
    legal back-to-back start is exactly the existing `session_end` plus 15
    minutes, since strictness makes that value pass."

    For a candidate ending at 08:46 the second arm reads 09:00 strictly before
    08:46 plus 15 minutes, that is 09:01, so the pair conflicts. For a candidate
    ending at exactly 08:45 the arm reads 09:00 strictly before 09:00, which is
    false, so the session is legal. With the 12:15 session added as well the
    officer holds three OPEN sessions starting 07:00, 09:00 and 12:15.

    Design: Difficulty/resource_temporal_overlap/docket_session_is_legal_only_from_exactly_fifteen_minutes_after_the_neighbouring_session
    """
    X.set_clock(api, "2026-03-01T00:00:00Z")
    middle = X.create_docket(
        api,
        "2026-03-12T09:00:00Z",
        "2026-03-12T12:00:00Z",
        officer_user_id=U.HEARING_OFFICER_ID,
        location="Hearing Room A",
        capacity=4,
    )
    later = X.create_docket(
        api,
        "2026-03-12T12:15:00Z",
        "2026-03-12T14:00:00Z",
        officer_user_id=U.HEARING_OFFICER_ID,
        location="Hearing Room A",
        capacity=4,
    )

    one_minute_long = api.create_hearing_docket(
        F.hearing_docket_payload(
            U.HEARING_OFFICER_ID,
            "2026-03-12T07:00:00Z",
            "2026-03-12T08:46:00Z",
            location="Hearing Room A",
            capacity=4,
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(one_minute_long, E.ERR_DOCKET_SESSION_OVERLAP, expected_status=409)

    earlier = A.data_of(
        api.create_hearing_docket(
            F.hearing_docket_payload(
                U.HEARING_OFFICER_ID,
                "2026-03-12T07:00:00Z",
                "2026-03-12T08:45:00Z",
                location="Hearing Room A",
                capacity=4,
            ),
            U.PROGRAM_ADMIN,
        ),
        201,
    )
    A.assert_status(earlier, "OPEN")
    assert earlier["session_end"] == "2026-03-12T08:45:00Z"

    listing = api.list_hearing_dockets(
        U.PROGRAM_ADMIN, {"hearing_officer_user_id": U.HEARING_OFFICER_ID, "per_page": 100}
    )
    rows = A.assert_total_count(listing, 3)
    assert {row["id"] for row in rows} == {middle, later, earlier["id"]}
    assert sorted(row["session_start"] for row in rows) == [
        "2026-03-12T07:00:00Z",
        "2026-03-12T09:00:00Z",
        "2026-03-12T12:15:00Z",
    ]
    for row in rows:
        A.assert_status(row, "OPEN")
        assert row["scheduled_appeal_count"] == 0
        assert row["capacity"] == 4


_SUSPENSION_SCHEDULE = {
    "effective_from": "2026-03-01T00:00:00Z",
    "free_alarm_allowance": 0,
    "probation_threshold_count": 4,
    "suspension_threshold_count": 2,
    "invoice_due_days": 3650,
    "fee_tiers": [{"from_index": 1, "to_index": None, "base_fee_cents": 10000}],
}


def _suspension_world(api):
    """A premises whose second chargeable incident auto-proposes one order.

    Two systems are permitted at 2026-03-01, so the first permit's
    new-installation grace runs out on 2026-03-31 and both occurrences below are
    strictly after it. The schedule suspends at a count of exactly 2, so ruling
    the 2026-04-10 incident chargeable auto-proposes an order covering
    2026-04-20 through 2026-05-20. The clock is parked at 2026-04-12 afterwards.
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-03-01T00:00:00Z",
        installed_at="2026-03-01T00:00:00Z",
        schedule_overrides=dict(_SUSPENSION_SCHEDULE),
        contact_count=2,
        system_count=2,
    )
    incidents = X.accumulate_counted_incidents(
        api,
        bundle,
        ["2026-04-05T01:00:00Z", "2026-04-10T01:00:00Z"],
        cause_code="UNKNOWN",
    )
    orders = X.orders_of_site(api, bundle.site_id)
    assert len(orders) == 1, f"expected exactly one auto-proposed order, got {len(orders)}"
    X.set_clock(api, "2026-04-12T00:00:00Z")
    return bundle, incidents, orders[0]


def test_suspension_period_touching_or_contained_interval_collides_under_closed_semantics(api):
    """A new order starting on the day the live order ends collides, and so does a
    fully contained interval, because suspension intervals are closed with no buffer.

    PRD §3.7: "The intervals are **closed**, `effective_from` through
    `effective_through`, and the buffer is **zero**: a conflict exists when the new
    `effective_from` is at or before the existing `effective_through` **and** the
    existing `effective_from` is at or before the new `effective_through`."
    PRD §3.7: "Touching endpoints therefore collide — a new order starting on the
    very day an existing order ends is a conflict — and the earliest accepted
    consecutive start is one day after the existing `effective_through`."
    PRD §3.5: "And when `chargeable_count_window` reaches or exceeds
    `suspension_threshold_count`, an enforcement order is auto-proposed for the
    premises: a suspension order in `PROPOSED` with `basis` of
    `EXCESSIVE_FALSE_ALARMS`, its `triggering_incident_id` set to this incident,
    `effective_from` at the logical clock plus 10 days and `effective_through` at
    30 days after that."

    The live order covers 2026-04-20 through 2026-05-20. A candidate starting on
    2026-05-20 satisfies 2026-05-20 at or before 2026-05-20, so both arms hold; a
    candidate of 2026-05-01 through 2026-05-10 sits entirely inside the window
    and likewise fails both arms.

    Design: Difficulty/resource_temporal_overlap/suspension_period_with_a_touching_or_contained_interval_collides_under_closed_semantics
    """
    bundle, incidents, live_order = _suspension_world(api)
    assert X.same_instant(live_order["effective_from"], "2026-04-20T00:00:00Z")
    assert X.same_instant(live_order["effective_through"], "2026-05-20T00:00:00Z")
    A.assert_status(live_order, "PROPOSED")

    touching = api.create_suspension_order(
        F.suspension_order_payload(
            bundle.site_id,
            incidents[1].incident_id,
            "2026-05-20T00:00:00Z",
            "2026-06-19T00:00:00Z",
            X.site_version(api, bundle.site_id),
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(touching, E.ERR_SUSPENSION_PERIOD_OVERLAP, expected_status=409)

    contained = api.create_suspension_order(
        F.suspension_order_payload(
            bundle.site_id,
            incidents[1].incident_id,
            "2026-05-01T00:00:00Z",
            "2026-05-10T00:00:00Z",
            X.site_version(api, bundle.site_id),
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(contained, E.ERR_SUSPENSION_PERIOD_OVERLAP, expected_status=409)

    assert len(X.orders_of_site(api, bundle.site_id)) == 1
    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 2
    A.assert_status(site, "RESPONSE_ACTIVE", field="response_status")


def test_suspension_period_ending_the_day_before_the_live_order_is_accepted(api):
    """An order whose closed interval ends the day before the live order begins is
    accepted, leaving the premises with two non-overlapping proposed orders.

    PRD §3.7: "The intervals are **closed**, `effective_from` through
    `effective_through`, and the buffer is **zero**: a conflict exists when the new
    `effective_from` is at or before the existing `effective_through` **and** the
    existing `effective_from` is at or before the new `effective_through`."
    PRD §3.7: "The premises may not already be under a live order across the same
    days, else `ERR_SUSPENSION_PERIOD_OVERLAP`."
    PRD §3.5: "Otherwise, if `chargeable_count_window` is at or above
    `probation_threshold_count`, the posture is `RESPONSE_PROBATION`. Otherwise it
    is `RESPONSE_ACTIVE`."

    For a candidate of 2026-04-13 through 2026-04-19 the second arm reads
    2026-04-20 at or before 2026-04-19, which is false, so no conflict exists.
    The count of 2 stays below the probation threshold of 4, so the premises keeps
    police response while two PROPOSED orders stand.

    Design: Difficulty/resource_temporal_overlap/suspension_period_with_a_touching_or_contained_interval_collides_under_closed_semantics
    """
    bundle, incidents, live_order = _suspension_world(api)

    accepted = A.data_of(
        api.create_suspension_order(
            F.suspension_order_payload(
                bundle.site_id,
                incidents[0].incident_id,
                "2026-04-13T00:00:00Z",
                "2026-04-19T00:00:00Z",
                X.site_version(api, bundle.site_id),
            ),
            U.PROGRAM_ADMIN,
        ),
        201,
    )
    A.assert_status(accepted, "PROPOSED")
    assert accepted["effective_from"] == "2026-04-13T00:00:00Z"
    assert accepted["effective_through"] == "2026-04-19T00:00:00Z"

    listing = api.list_suspension_orders(
        U.PROGRAM_ADMIN, {"alarm_site_id": bundle.site_id, "per_page": 100}
    )
    rows = A.assert_total_count(listing, 2)
    assert {row["id"] for row in rows} == {live_order["id"], accepted["id"]}
    for row in rows:
        A.assert_status(row, "PROPOSED")
    windows = sorted(
        (X.parse(row["effective_from"]), X.parse(row["effective_through"]))
        for row in rows
    )
    assert windows == [
        (X.parse("2026-04-13T00:00:00Z"), X.parse("2026-04-19T00:00:00Z")),
        (X.parse("2026-04-20T00:00:00Z"), X.parse("2026-05-20T00:00:00Z")),
    ]

    site = X.get_site(api, bundle.site_id)
    A.assert_status(site, "RESPONSE_ACTIVE", field="response_status")


def test_suspension_period_one_day_after_the_live_order_is_accepted(api):
    """The earliest legal consecutive order starts exactly one day after the live
    order's effective_through.

    PRD §3.7: "Touching endpoints therefore collide — a new order starting on the
    very day an existing order ends is a conflict — and the earliest accepted
    consecutive start is one day after the existing `effective_through`."
    PRD §3.7: "The intervals are **closed**, `effective_from` through
    `effective_through`, and the buffer is **zero**: a conflict exists when the new
    `effective_from` is at or before the existing `effective_through` **and** the
    existing `effective_from` is at or before the new `effective_through`."

    The live order ends 2026-05-20, so a candidate starting 2026-05-21 fails the
    first arm: 2026-05-21 is not at or before 2026-05-20. One day earlier, the
    same candidate would collide, which is what the touching case shows.

    Design: Difficulty/resource_temporal_overlap/suspension_period_is_free_one_day_after_the_live_order_and_again_once_it_is_vacated
    """
    bundle, incidents, live_order = _suspension_world(api)
    assert X.plus_days(live_order["effective_through"], 1) == "2026-05-21T00:00:00Z"

    consecutive = A.data_of(
        api.create_suspension_order(
            F.suspension_order_payload(
                bundle.site_id,
                incidents[1].incident_id,
                "2026-05-21T00:00:00Z",
                "2026-06-20T00:00:00Z",
                X.site_version(api, bundle.site_id),
            ),
            U.PROGRAM_ADMIN,
        ),
        201,
    )
    A.assert_status(consecutive, "PROPOSED")
    assert consecutive["effective_from"] == "2026-05-21T00:00:00Z"
    assert consecutive["effective_through"] == "2026-06-20T00:00:00Z"

    still_live = X.get_order(api, live_order["id"])
    A.assert_status(still_live, "PROPOSED")
    assert len(X.orders_of_site(api, bundle.site_id)) == 2


def test_vacating_the_live_order_frees_its_own_window_for_rebooking(api):
    """Vacating the proposed order removes it from the candidate set, so its exact
    window becomes bookable again without disturbing the consecutive order.

    PRD §3.7: "Candidates are the premises' own orders in `PROPOSED`, `EFFECTIVE`
    or `REINSTATEMENT_PENDING`; `LIFTED`, `VACATED` and `EXPIRED` orders free
    their interval."
    PRD §3.7: "It is reachable from `PROPOSED`, `EFFECTIVE` or
    `REINSTATEMENT_PENDING` and lands in the terminal `VACATED`."
    PRD §3.7: "In neither case is `lifted_suspension_count` incremented: a vacated
    order never counted as a suspension at all."

    The 2026-04-20 through 2026-05-20 window is refused while the original order
    is PROPOSED and accepted once it is VACATED; the rebooked window does not
    collide with the 2026-05-21 through 2026-06-20 order because 2026-05-21 is not
    at or before 2026-05-20.

    Design: Difficulty/resource_temporal_overlap/suspension_period_is_free_one_day_after_the_live_order_and_again_once_it_is_vacated
    """
    bundle, incidents, live_order = _suspension_world(api)
    consecutive_id = X.propose_suspension_order(
        api,
        bundle,
        incidents[1].incident_id,
        "2026-05-21T00:00:00Z",
        "2026-06-20T00:00:00Z",
    )

    while_proposed = api.create_suspension_order(
        F.suspension_order_payload(
            bundle.site_id,
            incidents[1].incident_id,
            "2026-04-20T00:00:00Z",
            "2026-05-20T00:00:00Z",
            X.site_version(api, bundle.site_id),
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(while_proposed, E.ERR_SUSPENSION_PERIOD_OVERLAP, expected_status=409)

    vacated = A.data_of(
        api.vacate_suspension_order(
            live_order["id"],
            {
                "vacated_reason": (
                    "Basis re-examined by the program administrator; the original window is released."
                )
            },
            U.PROGRAM_ADMIN,
        )
    )
    A.assert_status(vacated, "VACATED")
    assert vacated["vacated_reason"] == (
        "Basis re-examined by the program administrator; the original window is released."
    )
    assert X.get_site(api, bundle.site_id)["lifted_suspension_count"] == 0

    rebooked = A.data_of(
        api.create_suspension_order(
            F.suspension_order_payload(
                bundle.site_id,
                incidents[1].incident_id,
                "2026-04-20T00:00:00Z",
                "2026-05-20T00:00:00Z",
                X.site_version(api, bundle.site_id),
            ),
            U.PROGRAM_ADMIN,
        ),
        201,
    )
    A.assert_status(rebooked, "PROPOSED")
    assert rebooked["effective_from"] == "2026-04-20T00:00:00Z"
    assert rebooked["effective_through"] == "2026-05-20T00:00:00Z"

    listing = api.list_suspension_orders(
        U.PROGRAM_ADMIN, {"alarm_site_id": bundle.site_id, "per_page": 100}
    )
    rows = A.assert_total_count(listing, 3)
    by_id = {row["id"]: row for row in rows}
    A.assert_status(by_id[live_order["id"]], "VACATED")
    A.assert_status(by_id[consecutive_id], "PROPOSED")
    A.assert_status(by_id[rebooked["id"]], "PROPOSED")
    live_windows = sorted(
        (row["effective_from"], row["effective_through"])
        for row in rows
        if row["status"] == "PROPOSED"
    )
    assert live_windows == [
        ("2026-04-20T00:00:00Z", "2026-05-20T00:00:00Z"),
        ("2026-05-21T00:00:00Z", "2026-06-20T00:00:00Z"),
    ]


def _money_world(api):
    """A premises owing 16000 that has just tendered 20000 on 2026-02-10.

    The single system is permitted at 2026-01-01, so the new-installation grace
    runs out on 2026-01-31 and the 2026-02-05 occurrence is chargeable. The
    permit-issue invoice is 5000 plus the 500 administrative floor, the fee
    invoice is 10000 plus 500, and the tender is posted with AUTO_WATERFALL so the
    older permit invoice is settled first and 4000 is parked as credit.
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-02-05T00:00:00Z",
        installed_at="2026-01-01T00:00:00Z",
        schedule_overrides={
            "effective_from": "2026-01-01T00:00:00Z",
            "free_alarm_allowance": 0,
            "invoice_due_days": 3650,
            "fee_tiers": [{"from_index": 1, "to_index": None, "base_fee_cents": 10000}],
        },
        contact_count=2,
        system_count=1,
    )
    permit_invoices = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")
    assert len(permit_invoices) == 1, f"expected one permit-issue invoice, got {len(permit_invoices)}"
    incident = X.create_counted_incident(
        api, bundle, bundle.system_id, "2026-02-05T01:00:00Z", cause_code="OPERATOR_ERROR"
    )
    assert incident.invoice_id is not None
    X.set_clock(api, "2026-02-10T00:00:00Z")
    payment_id = X.post_payment(
        api,
        bundle,
        20000,
        "2026-02-10T00:00:00Z",
        method="CARD",
        allocation_mode="AUTO_WATERFALL",
    )
    return bundle, permit_invoices[0]["id"], incident.invoice_id, payment_id


def test_auto_waterfall_payment_splits_two_invoices_and_parks_the_residual_as_credit(api):
    """Before the void, the cash identity reads 20000 in equals 16000 sitting on
    invoices plus 4000 sitting in credit.

    PRD §3.9: "Candidates are ordered by dunning stage rank descending, where
    `REFERRED` ranks 4, `FINAL_NOTICE` ranks 3, `NOTICE` ranks 2 and `CURRENT`
    ranks 1; ties are broken by `due_on` ascending and then by `created_at`
    ascending."
    PRD §3.9: "Whatever remains after every candidate is exhausted becomes the
    payment's `credited_cents` and is added to the premises' `credit_balance_cents`;
    `allocated_cents` is the tendered amount minus that credit."
    PRD §3.9: "After every posted payment and after every void, one identity must
    hold exactly for each premises: the sum of `amount_cents` over that premises'
    payments in `APPLIED` equals the sum of `amount_cents` over allocations in
    `APPLIED` whose payment is also in `APPLIED` and whose invoice belongs to that
    premises, plus the premises' `credit_balance_cents`."

    Both invoices stand at CURRENT, so due_on ascending puts the permit invoice of
    5500 first and the fee invoice of 10500 second. 20000 minus 5500 minus 10500
    leaves 4000, which becomes credited_cents, and 5500 plus 10500 is the
    allocated 16000.

    Design: Difficulty/compensating_invariant/voiding_a_payment_on_the_last_legal_day_restores_both_sides_of_the_cash_identity
    """
    bundle, permit_invoice_id, fee_invoice_id, payment_id = _money_world(api)

    payment = X.get_payment(api, payment_id)
    A.assert_status(payment, "APPLIED")
    A.assert_money_cents(payment["amount_cents"], 20000, "amount_cents")
    A.assert_money_cents(payment["credited_cents"], 4000, "credited_cents")
    A.assert_money_cents(payment["allocated_cents"], 16000, "allocated_cents")
    A.assert_cash_conservation(payment)
    assert payment["voided_at"] is None
    assert payment["void_reason"] is None

    allocations = X.allocations_of_payment(api, payment_id)
    assert len(allocations) == 2
    by_invoice = {row["penalty_invoice_id"]: row for row in allocations}
    for row in allocations:
        A.assert_allocation_row(row)
        A.assert_status(row, "APPLIED")
    A.assert_money_cents(by_invoice[permit_invoice_id]["amount_cents"], 5500, "permit allocation")
    A.assert_money_cents(by_invoice[fee_invoice_id]["amount_cents"], 10500, "fee allocation")
    assert by_invoice[permit_invoice_id]["sequence_index"] == 1
    assert by_invoice[fee_invoice_id]["sequence_index"] == 2

    permit_invoice = X.get_invoice(api, permit_invoice_id)
    A.assert_invoice_totals(
        permit_invoice,
        subtotal_cents=5000,
        admin_fee_cents=500,
        assessed_cents=5500,
        paid_cents=5500,
        outstanding_cents=0,
        payment_status="PAID",
    )
    A.assert_outstanding_identity(permit_invoice)
    fee_invoice = X.get_invoice(api, fee_invoice_id)
    A.assert_invoice_totals(
        fee_invoice,
        subtotal_cents=10000,
        admin_fee_cents=500,
        assessed_cents=10500,
        paid_cents=10500,
        outstanding_cents=0,
        payment_status="PAID",
    )
    A.assert_outstanding_identity(fee_invoice)

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["credit_balance_cents"], 4000, "credit_balance_cents")
    A.assert_money_cents(site["outstanding_balance_cents"], 0, "outstanding_balance_cents")
    A.assert_money_cents(site["lifetime_assessed_cents"], 16000, "lifetime_assessed_cents")
    assert payment["amount_cents"] == (
        by_invoice[permit_invoice_id]["amount_cents"]
        + by_invoice[fee_invoice_id]["amount_cents"]
        + site["credit_balance_cents"]
    )


def test_voiding_a_payment_on_the_last_legal_day_restores_the_cash_identity(api):
    """Voiding on tendered_on plus exactly 2 whole days is accepted and drives both
    sides of the cash identity back to zero with no credit drift.

    PRD §3.9: "Only an administrator voids, supplying a `void_reason`, and only
    inside the window: the logical clock must be at or before `tendered_on` plus 2
    whole days, the boundary inclusive, and none of the payment's allocations may
    target an invoice whose `collections_stage` has since become `WRITTEN_OFF`,
    else `ERR_PAYMENT_VOID_WINDOW_CLOSED`."
    PRD §3.9: "The payment moves `APPLIED → VOIDED` with `voided_at` stamped,
    every one of its allocations flips `APPLIED → REVERSED`, each touched invoice's
    `paid_cents` drops by the reversed amount and its `payment_status` recomputes
    downward, the payment's `credited_cents` is subtracted back out of the
    premises' `credit_balance_cents`, and the premises' `version` rises by 1."
    PRD §3.9: "A void is the exact compensating action: it removes the payment from
    the left side and its allocations from the right side within the same request,
    restoring both sides to their pre-payment values with zero drift in
    `credit_balance_cents`, which may never fall below zero."
    PRD §3.9: "Third, `lifetime_assessed_cents` is the sum of `assessed_cents` over
    every invoice of the premises whose `payment_status` is not `VOIDED` — so a
    written-off invoice still counts toward lifetime assessment even though it has
    left the outstanding balance."

    The tender is dated 2026-02-10 and the clock reads 2026-02-12, which is exactly
    2 whole days later and therefore still inside the inclusive window. Afterwards
    cash in is 0, cash out is 0 and credit is 0, while the 16000 assessed stands.

    Design: Difficulty/compensating_invariant/voiding_a_payment_on_the_last_legal_day_restores_both_sides_of_the_cash_identity
    """
    bundle, permit_invoice_id, fee_invoice_id, payment_id = _money_world(api)
    X.set_clock(api, "2026-02-12T00:00:00Z")
    assert X.plus_days("2026-02-10T00:00:00Z", 2) == "2026-02-12T00:00:00Z"

    voided = A.data_of(
        api.void_payment_record(
            payment_id,
            {"void_reason": "Card chargeback initiated by the issuer; funds never settled."},
            U.PROGRAM_ADMIN,
        )
    )
    A.assert_status(voided, "VOIDED")
    assert voided["voided_at"] == "2026-02-12T00:00:00Z"
    assert voided["void_reason"] == (
        "Card chargeback initiated by the issuer; funds never settled."
    )

    allocations = X.allocations_of_payment(api, payment_id)
    assert len(allocations) == 2
    for row in allocations:
        A.assert_status(row, "REVERSED")

    permit_invoice = X.get_invoice(api, permit_invoice_id)
    A.assert_invoice_totals(
        permit_invoice,
        assessed_cents=5500,
        paid_cents=0,
        outstanding_cents=5500,
        payment_status="UNPAID",
    )
    A.assert_outstanding_identity(permit_invoice)
    fee_invoice = X.get_invoice(api, fee_invoice_id)
    A.assert_invoice_totals(
        fee_invoice,
        assessed_cents=10500,
        paid_cents=0,
        outstanding_cents=10500,
        payment_status="UNPAID",
    )
    A.assert_outstanding_identity(fee_invoice)

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["credit_balance_cents"], 0, "credit_balance_cents")
    A.assert_money_cents(site["outstanding_balance_cents"], 16000, "outstanding_balance_cents")
    A.assert_money_cents(site["lifetime_assessed_cents"], 16000, "lifetime_assessed_cents")

    still_applied = api.list_payment_records(
        U.BILLING_CLERK, {"alarm_site_id": bundle.site_id, "status": "APPLIED"}
    )
    A.assert_total_count(still_applied, 0)


def _remand_world(api):
    """Three chargeable incidents at one premises, with the middle one paid in full
    and its appeal already heard.

    Three systems are permitted at 2026-02-01, so the first permit's
    new-installation grace runs out on 2026-03-03 and all three occurrences are
    chargeable. The tiers price index 1 at 10000, index 2 at 20000 and index 3 at
    30000, so the invoices are 10500, 21000 and 31500 with the five-percent
    administrative fee. The 21000 invoice of the middle incident is settled
    explicitly on 2026-03-18 and the appeal against that incident is heard on
    2026-03-20.
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-02-01T00:00:00Z",
        installed_at="2026-02-01T00:00:00Z",
        schedule_overrides={
            "effective_from": "2026-02-01T00:00:00Z",
            "free_alarm_allowance": 0,
            "invoice_due_days": 3650,
            "fee_tiers": [
                {"from_index": 1, "to_index": 1, "base_fee_cents": 10000},
                {"from_index": 2, "to_index": 2, "base_fee_cents": 20000},
                {"from_index": 3, "to_index": None, "base_fee_cents": 30000},
            ],
        },
        contact_count=2,
        system_count=3,
    )
    incidents = X.accumulate_counted_incidents(
        api,
        bundle,
        ["2026-03-05T01:00:00Z", "2026-03-10T01:00:00Z", "2026-03-15T01:00:00Z"],
        cause_code="EQUIPMENT_MALFUNCTION",
    )
    X.set_clock(api, "2026-03-18T00:00:00Z")
    payment_id = X.pay_invoice_in_full(
        api, bundle, incidents[1].invoice_id, "2026-03-18T00:00:00Z"
    )
    appeal_id, _docket_id = X.create_heard_appeal(
        api,
        bundle,
        incidents[1].incident_id,
        session_start="2026-03-20T09:00:00Z",
        session_end="2026-03-20T12:00:00Z",
    )
    return bundle, incidents, payment_id, appeal_id


def test_remanding_the_middle_incident_conserves_a_contiguous_index_set(api):
    """Remanding the second of three chargeable incidents drops the window count to
    2, renumbers the third incident down to index 2 and re-prices it at that tier.

    PRD §3.6: "`REMANDED` sends the determination back for another look. The
    incident returns from `APPEALED` to `UNDER_REVIEW` with `determination`,
    `determined_at`, `determined_by_user_id`, `occurrence_index`,
    `assessed_fee_cents` and `counted_window_mode` all cleared; any invoice
    carrying that `false_alarm_incident_id` is voided and its allocations reversed,
    the reversed amounts landing in the premises' `credit_balance_cents`; the
    premises' counters are recomputed and its remaining chargeable incidents
    renumbered contiguously."
    PRD §3.5: "The set of `occurrence_index` values across those incidents is
    exactly the contiguous run from 1 to that count, with no gaps and no
    duplicates, assigned in order of occurrence instant ascending and, for ties,
    creation instant ascending."
    PRD §3.5: "Renumbering is therefore not optional bookkeeping: when an incident
    leaves the chargeable set, every remaining chargeable incident is renumbered
    contiguously in that same order and re-priced at its new tier, until the
    premises' state is what it would have been had the removed incident never been
    counted."

    The third incident falls from index 3 to index 2, so its fee is re-derived from
    the 30000 tier to the 20000 tier and its invoice from 30000 plus 1500 to 20000
    plus 1000, that is 31500 down to 21000.

    Design: Difficulty/compensating_invariant/remanding_the_middle_incident_conserves_a_contiguous_index_set_and_returns_the_money_as_credit
    """
    bundle, incidents, _payment_id, appeal_id = _remand_world(api)
    third_invoice_id = incidents[2].invoice_id

    decided = X.decide_appeal(
        api,
        appeal_id,
        "REMANDED",
        findings=(
            "Cause determination made without the panel inspection required by the program; "
            "returned for re-determination."
        ),
    )
    A.assert_status(decided, "REMANDED")

    remanded = X.get_incident(api, incidents[1].incident_id)
    A.assert_status(remanded, "UNDER_REVIEW")
    for cleared in (
        "determination",
        "determined_at",
        "determined_by_user_id",
        "occurrence_index",
        "counted_window_mode",
    ):
        assert remanded[cleared] is None, f"{cleared} must be cleared by the remand, got {remanded[cleared]!r}"
    # PRD §3.6 says only that `assessed_fee_cents` is "cleared"; it pins neither
    # null nor 0 for the remand (contrast §3.6's grant, "set to 0").
    assert remanded["assessed_fee_cents"] in (None, 0), remanded["assessed_fee_cents"]

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 2

    first = X.get_incident(api, incidents[0].incident_id)
    third = X.get_incident(api, incidents[2].incident_id)
    A.assert_status(first, "COUNTED")
    A.assert_status(third, "COUNTED")
    assert first["occurrence_index"] == 1
    assert third["occurrence_index"] == 2
    assert {first["occurrence_index"], third["occurrence_index"]} == {1, 2}

    A.assert_money_cents(first["assessed_fee_cents"], 10000, "first assessed_fee_cents")
    A.assert_money_cents(third["assessed_fee_cents"], 20000, "third assessed_fee_cents")
    third_invoice = X.get_invoice(api, third_invoice_id)
    A.assert_invoice_totals(
        third_invoice,
        subtotal_cents=20000,
        admin_fee_cents=1000,
        assessed_cents=21000,
    )
    A.assert_outstanding_identity(third_invoice)


def test_remanding_the_middle_incident_returns_the_paid_money_as_credit(api):
    """The remand voids the paid invoice, reverses its allocation into credit and
    leaves the credit unspent against the re-assessed invoice.

    PRD §3.6: "`REMANDED` sends the determination back for another look. The
    incident returns from `APPEALED` to `UNDER_REVIEW` with `determination`,
    `determined_at`, `determined_by_user_id`, `occurrence_index`,
    `assessed_fee_cents` and `counted_window_mode` all cleared; any invoice
    carrying that `false_alarm_incident_id` is voided and its allocations reversed,
    the reversed amounts landing in the premises' `credit_balance_cents`; the
    premises' counters are recomputed and its remaining chargeable incidents
    renumbered contiguously."
    PRD §3.9: "A parked credit is not spent by itself: it is released only by a
    later payment's allocation or by a void reversal, never auto-consumed by the
    next invoice the premises incurs."
    PRD §3.5: "Otherwise, if `chargeable_count_window` is at or above
    `probation_threshold_count`, the posture is `RESPONSE_PROBATION`. Otherwise it
    is `RESPONSE_ACTIVE`."

    The 21000 settled on the remanded incident returns as credit, and the premises
    still owes 16500 of permit-issue fees plus 10500 for the first incident plus
    the re-assessed 21000 for the third, that is 48000; the voided invoice
    contributes nothing.

    Design: Difficulty/compensating_invariant/remanding_the_middle_incident_conserves_a_contiguous_index_set_and_returns_the_money_as_credit
    """
    bundle, incidents, payment_id, appeal_id = _remand_world(api)
    second_invoice_id = incidents[1].invoice_id
    third_invoice_id = incidents[2].invoice_id

    X.decide_appeal(
        api,
        appeal_id,
        "REMANDED",
        findings=(
            "Cause determination made without the panel inspection required by the program; "
            "returned for re-determination."
        ),
    )

    second_invoice = X.get_invoice(api, second_invoice_id)
    A.assert_invoice_totals(
        second_invoice,
        assessed_cents=21000,
        outstanding_cents=0,
        payment_status="VOIDED",
    )

    allocations = X.allocations_of_payment(api, payment_id)
    assert len(allocations) == 1
    A.assert_status(allocations[0], "REVERSED")
    A.assert_money_cents(allocations[0]["amount_cents"], 21000, "reversed allocation")

    payment = X.get_payment(api, payment_id)
    A.assert_status(payment, "APPLIED")
    A.assert_money_cents(payment["amount_cents"], 21000, "amount_cents")

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["credit_balance_cents"], 21000, "credit_balance_cents")
    A.assert_money_cents(site["outstanding_balance_cents"], 48000, "outstanding_balance_cents")
    A.assert_status(site, "RESPONSE_ACTIVE", field="response_status")

    third_invoice = X.get_invoice(api, third_invoice_id)
    A.assert_invoice_totals(
        third_invoice,
        assessed_cents=21000,
        paid_cents=0,
        outstanding_cents=21000,
        payment_status="UNPAID",
    )
    assert X.orders_of_site(api, bundle.site_id) == []
