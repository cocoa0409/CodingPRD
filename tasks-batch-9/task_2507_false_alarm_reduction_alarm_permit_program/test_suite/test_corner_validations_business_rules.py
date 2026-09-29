"""Business-rule validation corners: temporal windows, interval geometry,
uniqueness, roster minimums, fiscal gates and pagination bounds, including the
cases where two rule violations compete and PRD §2.10 decides the winner.
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


def test_appeal_filed_on_day_twenty_one_with_one_already_pending_returns_window_closed(api):
    """A second appeal filed on day 21 against an incident that already has a live
    appeal is refused with the filing-window error, not the pending-appeal error.

    PRD §2.10: "An appeal must be filed no later than the incident's determination
    instant plus the schedule's `appeal_filing_days` (20 days by default, boundary
    inclusive), failing with `ERR_APPEAL_WINDOW_CLOSED`."
    PRD §2.10: "**Collision C.** An appeal filed on the twenty-first day after
    determination, against an incident that also already has a live appeal, fails
    both the filing-window check at position 30 and the pending-appeal check at
    position 36. The filing-window check wins, and the caller receives
    `ERR_APPEAL_WINDOW_CLOSED`."
    PRD §3.6: "When both faults are present — a late filing against an incident
    that also already has a live appeal — the window rule is the higher-priority
    row and `ERR_APPEAL_WINDOW_CLOSED` is what the caller sees."

    The incident is ruled chargeable at 2026-09-20T01:00:00Z, so the inclusive
    deadline is that instant plus 20 whole days, 2026-10-10T01:00:00Z. The clock
    is moved to 2026-10-11T01:00:00Z, day 21, which is past the deadline, while
    the first appeal is still FILED, so both rows are genuinely violated.

    Design: Corner/validations/appeal_filed_on_day_twenty_one_with_one_already_pending_returns_window_closed
    """
    bundle = X.setup_program_baseline(api, clock="2026-09-20T00:00:00Z")
    incident = X.create_reported_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.set_clock(api, "2026-09-20T01:00:00Z")
    determined = X.determine_counted(api, incident.incident_id)
    assert determined["determined_at"][:19] == "2026-09-20T01:00:00"

    appeal_id = X.file_appeal(api, bundle, incident.incident_id)
    version_now = X.incident_version(api, incident.incident_id)

    X.set_clock(api, "2026-10-11T01:00:00Z")
    response = api.create_appeal(
        F.appeal_payload(
            incident.incident_id,
            grounds="EXEMPT_CAUSE",
            narrative="Late second filing while the first appeal is still awaiting a docket.",
            expected_false_alarm_incident_version=version_now,
        ),
        bundle.holder_headers,
    )
    validate_error(response, E.ERR_APPEAL_WINDOW_CLOSED, expected_status=409)

    A.assert_status(X.get_appeal(api, appeal_id), "FILED")
    assert X.get_appeal(api, appeal_id)["hearing_docket_id"] is None
    listed = api.list_appeals(U.PROGRAM_ADMIN, {"false_alarm_incident_id": incident.incident_id})
    A.assert_total_count(listed, 1)


def test_appeal_filed_inside_the_window_with_one_already_pending_returns_already_pending(api):
    """The same duplicate filing moved inside the 20-day window surfaces the
    lower-priority pending-appeal error instead.

    PRD §2.10: "In order: the contested incident must have no appeal in `FILED`,
    `SCHEDULED` or `HEARD`, failing with `ERR_APPEAL_ALREADY_PENDING`."
    PRD §3.6: "Only one live appeal may exist per incident: if the incident
    already has an appeal in `FILED`, `SCHEDULED` or `HEARD`, the filing is
    rejected with `ERR_APPEAL_ALREADY_PENDING`."

    Determination lands at 2026-09-20T01:00:00Z, so the inclusive deadline is
    2026-10-10T01:00:00Z. The clock is moved only to 2026-09-25T01:00:00Z, day 5,
    which satisfies the window rule, so the pair's outcome flips on the clock
    alone and the pending-appeal row is the only one violated.

    Design: Corner/validations/appeal_filed_inside_the_window_with_one_already_pending_returns_already_pending
    """
    bundle = X.setup_program_baseline(api, clock="2026-09-20T00:00:00Z")
    incident = X.create_reported_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.set_clock(api, "2026-09-20T01:00:00Z")
    X.determine_counted(api, incident.incident_id)

    appeal_id = X.file_appeal(api, bundle, incident.incident_id)
    before = X.get_incident(api, incident.incident_id)
    version_now = before["version"]

    X.set_clock(api, "2026-09-25T01:00:00Z")
    response = api.create_appeal(
        F.appeal_payload(
            incident.incident_id,
            grounds="COUNTING_ERROR",
            narrative="Second grounds filed five days after the first appeal.",
            expected_false_alarm_incident_version=version_now,
        ),
        bundle.holder_headers,
    )
    validate_error(response, E.ERR_APPEAL_ALREADY_PENDING, expected_status=409)

    after = X.get_incident(api, incident.incident_id)
    A.assert_status(after, "APPEALED")
    A.assert_version_unchanged(before, after)
    listed = api.list_appeals(U.PROGRAM_ADMIN, {"false_alarm_incident_id": incident.incident_id})
    rows = A.assert_total_count(listed, 1)
    assert rows[0]["id"] == appeal_id


def test_hearing_docket_create_with_a_session_in_the_past_is_rejected(api):
    """A docket whose window lies before the logical clock, and a docket whose end
    is not after its start, are both refused with the past-session error.

    PRD §3.6: "The session must be in the future: `session_start` must be strictly
    after the current logical clock, and `session_end` strictly after
    `session_start`, else `ERR_HEARING_SESSION_IN_PAST`."
    PRD §2.10: "A new hearing docket must have `session_start` strictly after the
    current logical clock and `session_end` strictly after `session_start`,
    failing with `ERR_HEARING_SESSION_IN_PAST`."

    The clock reads 2026-08-01T00:00:00Z, so a window on 2026-07-15 is in the
    past; the inverted window 16:00 to 14:00 on 2026-10-05 fails the second arm
    of the same row, while the well-formed future window is accepted.

    Design: Corner/validations/hearing_docket_create_with_a_session_in_the_past_is_rejected
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)

    past = api.create_hearing_docket(
        F.hearing_docket_payload(
            U.HEARING_OFFICER_ID,
            "2026-07-15T14:00:00Z",
            "2026-07-15T16:00:00Z",
            location="City Hall Room 210",
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(past, E.ERR_HEARING_SESSION_IN_PAST, expected_status=422)
    A.assert_total_count(api.list_hearing_dockets(U.PROGRAM_ADMIN), 0)

    inverted = api.create_hearing_docket(
        F.hearing_docket_payload(
            U.HEARING_OFFICER_ID,
            "2026-10-05T16:00:00Z",
            "2026-10-05T14:00:00Z",
            location="City Hall Room 210",
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(inverted, E.ERR_HEARING_SESSION_IN_PAST, expected_status=422)
    A.assert_total_count(api.list_hearing_dockets(U.PROGRAM_ADMIN), 0)

    accepted = api.create_hearing_docket(
        F.hearing_docket_payload(
            U.HEARING_OFFICER_ID,
            "2026-10-05T14:00:00Z",
            "2026-10-05T16:00:00Z",
            location="City Hall Room 210",
        ),
        U.PROGRAM_ADMIN,
    )
    validate_success(accepted, 201)


def test_hold_session_before_the_session_start_is_rejected(api):
    """The docket's own officer cannot hold a seated session while the logical
    clock is still short of session_start.

    PRD §3.6: "Holding the session is the officer's own act: only the caller whose
    `X-User-ID` equals the docket's `hearing_officer_user_id` may do it, else
    `ERR_NOT_DOCKET_OFFICER`; the logical clock must have reached `session_start`,
    the boundary inclusive, else `ERR_HEARING_SESSION_NOT_STARTED`; and the docket
    must seat at least one appeal, else `ERR_DOCKET_EMPTY`."
    PRD §2.10: "A docket may only be held once the logical clock has reached
    `session_start`, inclusive, failing with `ERR_HEARING_SESSION_NOT_STARTED`."

    One appeal is seated so the empty-docket row cannot fire, and the acting user
    is ho-03, the docket's own officer, so the role row cannot fire either. The
    clock reads 2026-09-20T02:00:00Z against a session_start of
    2026-10-05T14:00:00Z, so only the temporal row rejects the call.

    Design: Corner/validations/hold_session_before_the_session_start_is_rejected
    """
    bundle = X.setup_program_baseline(api, clock="2026-09-20T00:00:00Z")
    incident = X.create_counted_incident(
        api, bundle, bundle.system_id, C.FIRST_CHARGEABLE_OCCURRED_AT
    )
    X.set_clock(api, "2026-09-20T02:00:00Z")
    appeal_id = X.file_appeal(api, bundle, incident.incident_id)
    docket_id = X.create_docket(api, "2026-10-05T14:00:00Z", "2026-10-05T16:00:00Z")
    X.schedule_appeal(api, appeal_id, docket_id)

    before = get_success_data(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))

    response = api.hold_session(docket_id, {}, U.HEARING_OFFICER)
    validate_error(response, E.ERR_HEARING_SESSION_NOT_STARTED, expected_status=409)

    after = get_success_data(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))
    A.assert_status(after, "OPEN")
    assert after["held_at"] is None
    A.assert_version_unchanged(before, after)
    A.assert_status(X.get_appeal(api, appeal_id), "SCHEDULED")


def test_suspension_order_create_with_a_backdated_effective_from_is_rejected(api):
    """A proposed order whose effective_from precedes both the clock and the
    triggering incident, and one whose closing bound is not strictly later, are
    both refused with the effective-date error.

    PRD §3.7: "The dates must be coherent: `effective_from` at or after the
    current logical clock and at or after the triggering incident's `occurred_at`,
    and `effective_through` strictly after `effective_from`, else
    `ERR_SUSPENSION_EFFECTIVE_DATE_INVALID`."
    PRD §2.10: "A new suspension order's `effective_from` must be at or after the
    logical clock and at or after the triggering incident's occurrence instant,
    with `effective_through` strictly after `effective_from`, failing with
    `ERR_SUSPENSION_EFFECTIVE_DATE_INVALID`."

    The clock reads 2026-09-20T01:00:00Z and the incident fired at
    2026-09-15T03:09:00Z, so 2026-09-10T00:00:00Z precedes both. The temporal row
    sits at position 34 and the basis row — which this single-incident premises
    would also fail, its chargeable count being 1 against a threshold of 6 — sits
    at position 49, so the temporal error is what the caller sees.

    Design: Corner/validations/suspension_order_create_with_a_backdated_effective_from_is_rejected
    """
    bundle = X.setup_program_baseline(api, clock="2026-09-20T00:00:00Z")
    incident = X.create_reported_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.set_clock(api, "2026-09-20T01:00:00Z")
    X.determine_counted(api, incident.incident_id)

    backdated = api.create_suspension_order(
        F.suspension_order_payload(
            bundle.site_id,
            incident.incident_id,
            "2026-09-10T00:00:00Z",
            "2026-10-10T00:00:00Z",
            X.site_version(api, bundle.site_id),
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(backdated, E.ERR_SUSPENSION_EFFECTIVE_DATE_INVALID, expected_status=422)
    assert X.orders_of_site(api, bundle.site_id) == []
    assert X.get_site(api, bundle.site_id)["response_status"] == "RESPONSE_ACTIVE"

    degenerate = api.create_suspension_order(
        F.suspension_order_payload(
            bundle.site_id,
            incident.incident_id,
            "2026-10-01T00:00:00Z",
            "2026-10-01T00:00:00Z",
            X.site_version(api, bundle.site_id),
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(degenerate, E.ERR_SUSPENSION_EFFECTIVE_DATE_INVALID, expected_status=422)
    assert X.orders_of_site(api, bundle.site_id) == []


def test_payment_void_after_the_two_day_window_is_rejected(api):
    """A tender may be voided on the second whole day after it was taken but not
    on the third.

    PRD §3.9: "Only an administrator voids, supplying a `void_reason`, and only
    inside the window: the logical clock must be at or before `tendered_on` plus 2
    whole days, the boundary inclusive, and none of the payment's allocations may
    target an invoice whose `collections_stage` has since become `WRITTEN_OFF`,
    else `ERR_PAYMENT_VOID_WINDOW_CLOSED`."
    PRD §2.10: "And a payment may be voided only within 2 whole days of its tender
    instant, boundary inclusive, and only while none of its allocations targets an
    invoice that has since become `WRITTEN_OFF`, failing with
    `ERR_PAYMENT_VOID_WINDOW_CLOSED`."

    The 5500-cent card tender is taken on 2026-08-01, so the inclusive edge of the
    window is 2026-08-03. A void attempted at 2026-08-04 is one day past it and is
    refused; the identical void issued at 2026-08-03 is accepted.

    Design: Corner/validations/payment_void_after_the_two_day_window_is_rejected
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC
    )
    invoice = X.invoices_of_site(api, bundle.site_id)[0]
    A.assert_invoice_totals(
        invoice, assessed_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS
    )
    payment_id = X.post_payment(
        api, bundle, C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS, "2026-08-01T00:00:00Z", method="CARD"
    )

    X.set_clock(api, "2026-08-04T00:00:00Z")
    late = api.void_payment_record(
        payment_id,
        {"void_reason": "Payer disputed the card charge after the window closed."},
        U.PROGRAM_ADMIN,
    )
    validate_error(late, E.ERR_PAYMENT_VOID_WINDOW_CLOSED, expected_status=409)

    payment = X.get_payment(api, payment_id)
    A.assert_status(payment, "APPLIED")
    assert payment["voided_at"] is None
    allocations = X.allocations_of_payment(api, payment_id)
    assert len(allocations) == 1
    A.assert_status(allocations[0], "APPLIED")
    A.assert_invoice_totals(
        X.get_invoice(api, invoice["id"]), outstanding_cents=0, payment_status="PAID"
    )

    X.set_clock(api, "2026-08-03T00:00:00Z")
    on_edge = api.void_payment_record(
        payment_id,
        {"void_reason": "Payer disputed the card charge inside the window."},
        U.PROGRAM_ADMIN,
    )
    validate_success(on_edge, 200)
    A.assert_status(X.get_payment(api, payment_id), "VOIDED")


def test_hearing_docket_create_ten_minutes_after_an_existing_session_is_rejected(api):
    """A second session for the same officer starting ten minutes after the first
    one ends falls inside the fifteen-minute turnaround buffer and is refused.

    PRD §3.6: "The intervals are half-open, and a 15-minute turnaround buffer is
    applied on both sides of the existing session: a conflict exists when the new
    `session_start` is strictly before the existing `session_end` plus 15 minutes
    **and** the existing `session_start` is strictly before the new `session_end`
    plus 15 minutes."
    PRD §3.6: "Dockets belonging to different officers never collide however their
    intervals sit."
    PRD §2.10: "A new docket must not overlap a live docket of the same hearing
    officer under the buffered geometry of §3.6, failing with
    `ERR_DOCKET_SESSION_OVERLAP`."

    The existing session ends at 2026-10-05T16:00:00Z, so the buffered edge is
    16:15 and the earliest legal back-to-back start is exactly 16:15. A start at
    16:10 is strictly before 16:15, and the existing 14:00 start is strictly
    before the new end 17:10 plus 15 minutes, so both arms hold and the conflict
    fires.

    Design: Corner/validations/hearing_docket_create_ten_minutes_after_an_existing_session_is_rejected
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_docket(api, "2026-10-05T14:00:00Z", "2026-10-05T16:00:00Z")

    conflicting = api.create_hearing_docket(
        F.hearing_docket_payload(
            U.HEARING_OFFICER_ID,
            "2026-10-05T16:10:00Z",
            "2026-10-05T17:10:00Z",
            location="City Hall Room 214",
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(conflicting, E.ERR_DOCKET_SESSION_OVERLAP, expected_status=409)
    A.assert_total_count(
        api.list_hearing_dockets(
            U.PROGRAM_ADMIN, {"hearing_officer_user_id": U.HEARING_OFFICER_ID}
        ),
        1,
    )

    other_officer = api.create_hearing_docket(
        F.hearing_docket_payload(
            U.HEARING_OFFICER_ID_2,
            "2026-10-05T16:10:00Z",
            "2026-10-05T17:10:00Z",
            location="City Hall Room 214",
        ),
        U.PROGRAM_ADMIN,
    )
    validate_success(other_officer, 201)


def test_suspension_order_create_overlapping_a_live_window_is_rejected(api):
    """A second order whose window starts inside a live order's closed interval is
    refused, while one starting the day after that interval ends is accepted.

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

    The sixth chargeable incident is ruled at clock 2026-09-20T00:00:00Z, so the
    auto-proposed order runs 2026-09-30T00:00:00Z through 2026-10-30T00:00:00Z and
    is served while the clock is still at or before its start. With the clock then
    at 2026-10-05, a new window opening 2026-10-10 sits five days inside the live
    interval and collides; one opening 2026-10-31, one day after the through date,
    does not.

    Design: Corner/validations/suspension_order_create_overlapping_a_live_window_is_rejected
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC, system_count=6)
    incidents = X.accumulate_counted_incidents(
        api,
        bundle,
        [
            "2026-09-15T02:00:00Z",
            "2026-09-16T02:00:00Z",
            "2026-09-17T02:00:00Z",
            "2026-09-18T02:00:00Z",
            "2026-09-19T02:00:00Z",
            "2026-09-20T02:00:00Z",
        ],
    )
    orders = X.orders_of_site(api, bundle.site_id)
    assert len(orders) == 1
    order = orders[0]
    A.assert_status(order, "PROPOSED")
    assert order["effective_from"][:19] == "2026-09-30T00:00:00"
    assert order["effective_through"][:19] == "2026-10-30T00:00:00"
    assert order["triggering_incident_id"] == incidents[5].incident_id
    validate_success(api.serve_suspension_order(order["id"], U.PROGRAM_ADMIN), 200)

    X.set_clock(api, "2026-10-05T00:00:00Z")
    overlapping = api.create_suspension_order(
        F.suspension_order_payload(
            bundle.site_id,
            incidents[5].incident_id,
            "2026-10-10T00:00:00Z",
            "2026-11-09T00:00:00Z",
            X.site_version(api, bundle.site_id),
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(overlapping, E.ERR_SUSPENSION_PERIOD_OVERLAP, expected_status=409)

    still_one = X.orders_of_site(api, bundle.site_id)
    assert len(still_one) == 1
    A.assert_status(still_one[0], "EFFECTIVE")
    assert still_one[0]["effective_from"][:19] == "2026-09-30T00:00:00"
    assert still_one[0]["effective_through"][:19] == "2026-10-30T00:00:00"

    consecutive = api.create_suspension_order(
        F.suspension_order_payload(
            bundle.site_id,
            incidents[5].incident_id,
            "2026-10-31T00:00:00Z",
            "2026-11-30T00:00:00Z",
            X.site_version(api, bundle.site_id),
        ),
        U.PROGRAM_ADMIN,
    )
    validate_success(consecutive, 201)


def test_alarm_site_create_with_a_normalized_duplicate_address_key_is_rejected(api):
    """A second premises whose address key differs only in case and padding
    collides with the existing one once normalization is applied.

    PRD §3.1: "Normalization upper-cases and collapses whitespace across street
    and unit, and the resulting key must be unique among premises whose `status` is
    `ACTIVE`; a premises `status` is either `ACTIVE` or `ARCHIVED`."
    PRD §2.10: "A premises' normalized `address_key` must be unique across all
    non-archived premises, failing with `ERR_DUPLICATE_ADDRESS_KEY`."

    The stored key is 1200-MAIN-ST-75201; the incoming spelling
    "  1200-main-st-75201  " normalizes to exactly that, so the raw strings differ
    byte for byte while the normalized keys are identical.

    Design: Corner/validations/alarm_site_create_with_a_normalized_duplicate_address_key_is_rejected
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    site_id = X.create_site(
        api,
        address_key="1200-MAIN-ST-75201",
        street_address="1200 Main St",
        city="Dallas",
        zip_code="75201",
        occupancy_class="COMMERCIAL",
        police_beat="B-114",
    )

    duplicate = api.create_alarm_site(
        F.alarm_site_payload(
            address_key="  1200-main-st-75201  ",
            street_address="1200 Main Street",
            city="Dallas",
            zip_code="75201",
            occupancy_class="COMMERCIAL",
            police_beat="B-114",
        ),
        U.PERMIT_CLERK,
    )
    validate_error(duplicate, E.ERR_DUPLICATE_ADDRESS_KEY, expected_status=409)

    listed = api.list_alarm_sites(U.PERMIT_CLERK, {"address_key": "1200-MAIN-ST-75201"})
    rows = A.assert_total_count(listed, 1)
    assert rows[0]["id"] == site_id
    assert X.get_site(api, site_id)["street_address"] == "1200 Main St"


def test_site_contact_create_with_a_duplicate_priority_is_rejected(api):
    """A contact priority already taken by an active contact of the same premises
    is refused, while the same priority on another premises is free.

    PRD §2.10: "A contact's `contact_priority` must be unique among the `ACTIVE`
    contacts of the same premises, failing with `ERR_DUPLICATE_CONTACT_PRIORITY`."

    The premises already holds active contacts at priorities 1 and 2, so a third
    contact asking for priority 2 collides; priority 3 at the same premises and
    priority 2 at a different premises are both free.

    Design: Corner/validations/site_contact_create_with_a_duplicate_priority_is_rejected
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    site_id = X.create_site(api)
    X.create_contacts(api, site_id, 2)
    before = X.get_site(api, site_id)

    clash = api.create_site_contact(
        F.site_contact_payload(
            site_id,
            full_name="Tobias Reyner",
            relationship="MANAGER",
            contact_priority=2,
            is_ecv_callable=True,
        ),
        U.PERMIT_CLERK,
    )
    validate_error(clash, E.ERR_DUPLICATE_CONTACT_PRIORITY, expected_status=409)

    roster = api.list_site_contacts(
        U.PERMIT_CLERK, {"alarm_site_id": site_id, "status": "ACTIVE"}
    )
    A.assert_total_count(roster, 2)
    after = X.get_site(api, site_id)
    assert after["ecv_callable_contact_count"] == 2
    A.assert_version_unchanged(before, after)

    free_priority = api.create_site_contact(
        F.site_contact_payload(
            site_id,
            full_name="Tobias Reyner",
            relationship="MANAGER",
            contact_priority=3,
            is_ecv_callable=True,
        ),
        U.PERMIT_CLERK,
    )
    validate_success(free_priority, 201)

    other_site_id = X.create_site(api)
    other_premises = api.create_site_contact(
        F.site_contact_payload(
            other_site_id,
            full_name="Tobias Reyner",
            relationship="MANAGER",
            contact_priority=2,
            is_ecv_callable=True,
        ),
        U.PERMIT_CLERK,
    )
    validate_success(other_premises, 201)


def test_site_contact_delete_below_the_ecv_minimum_is_rejected(api):
    """Removing one of exactly two callable contacts at a premises that still
    holds a live registration is refused by the roster floor.

    PRD §2.10: "Removing a contact must not drop the premises' live callable
    roster below 2 while the premises still holds an alarm system in a live
    registration state — `SUBMITTED` or `PERMITTED` — failing with
    `ERR_CONTACT_ROSTER_MINIMUM`."

    The premises has exactly two callable contacts and one permitted system, so
    the delete would leave a live roster of 1, below the floor of 2. Adding a
    third callable contact first raises the roster to 3, so the same delete then
    leaves 2 and succeeds.

    Design: Corner/validations/site_contact_delete_below_the_ecv_minimum_is_rejected
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC
    )
    doomed = bundle.contact_ids[1]
    before = X.get_site(api, bundle.site_id)

    refused = api.delete_site_contact(doomed, U.PERMIT_CLERK)
    validate_error(refused, E.ERR_CONTACT_ROSTER_MINIMUM, expected_status=409)

    contact = get_success_data(api.get_site_contact(doomed, U.PERMIT_CLERK))
    A.assert_status(contact, "ACTIVE")
    assert contact["removed_at"] is None
    after = X.get_site(api, bundle.site_id)
    assert after["ecv_callable_contact_count"] == 2
    A.assert_version_unchanged(before, after)

    X.create_contact(api, bundle.site_id, contact_priority=3, is_ecv_callable=True)
    validate_success(api.delete_site_contact(doomed, U.PERMIT_CLERK), 200)


def test_compliance_report_create_overlapping_an_existing_period_is_rejected(api):
    """A reporting period straddling two of the same company's existing reports is
    refused, while the identical window filed by another company is accepted.

    PRD §2.10: "A compliance report's closed reporting interval must not overlap an
    existing report of the same monitoring company in `SUBMITTED`, `ACCEPTED`,
    `VARIANCE_FLAGGED` or `CORRECTED`, failing with `ERR_REPORT_PERIOD_OVERLAP`."

    The company already holds an August report still in SUBMITTED and a September
    report in ACCEPTED. The window 2026-08-15 through 2026-09-15 lies inside both
    closed intervals, and the still-unreviewed August report is on its own enough
    to block it.

    Design: Corner/validations/compliance_report_create_overlapping_an_existing_period_is_rejected
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC
    )
    X.submit_compliance_report(
        api,
        bundle,
        "2026-08-01T00:00:00Z",
        "2026-08-31T00:00:00Z",
        reported_dispatch_count=3,
        reported_cancellation_count=0,
        ecv_attempt_count=0,
    )
    report_b = X.submit_compliance_report(
        api,
        bundle,
        "2026-09-01T00:00:00Z",
        "2026-09-30T00:00:00Z",
        reported_dispatch_count=1,
        reported_cancellation_count=0,
        ecv_attempt_count=2,
    )
    X.review_compliance_report(
        api, report_b, "ACCEPT", variance_notes="Counts reconcile exactly."
    )
    score_before = X.get_company(api, bundle.company_id)["reporting_compliance_score"]

    straddling = api.create_compliance_report(
        F.compliance_report_payload(
            bundle.company_id,
            "2026-08-15T00:00:00Z",
            "2026-09-15T00:00:00Z",
            reported_dispatch_count=2,
            reported_cancellation_count=0,
            ecv_attempt_count=2,
        ),
        bundle.operator_headers,
    )
    validate_error(straddling, E.ERR_REPORT_PERIOD_OVERLAP, expected_status=409)

    A.assert_total_count(
        api.list_compliance_reports(
            U.REVIEW_OFFICER, {"monitoring_company_id": bundle.company_id}
        ),
        2,
    )
    assert X.get_company(api, bundle.company_id)["reporting_compliance_score"] == score_before

    other_company_id = X.create_company(api)
    other = api.create_compliance_report(
        F.compliance_report_payload(
            other_company_id,
            "2026-08-15T00:00:00Z",
            "2026-09-15T00:00:00Z",
            reported_dispatch_count=2,
            reported_cancellation_count=0,
            ecv_attempt_count=2,
        ),
        U.alarm_company_operator(other_company_id),
    )
    validate_success(other, 201)


def test_alarm_sites_list_with_page_zero_is_rejected(api):
    """A page number below 1 and a per_page outside 1 to 100 are rejected rather
    than clamped, on premises listing and on every other list read alike.

    PRD §2.3: "`page` is an integer that must be at or above 1 and defaults to 1."
    PRD §2.3: "A `page` below 1, a `per_page` outside the range 1 to 100, or a sort
    key that does not name a declared field of the entity being listed is rejected
    with `ERR_INVALID_PAGINATION`."
    PRD §2.10: "Last of all, on list reads, `page` and `per_page` are
    range-checked and any sort key is checked against the listed entity's declared
    fields, failing with `ERR_INVALID_PAGINATION`."

    Three premises exist, so a well-formed page 1 would return rows; page 0 is
    still refused, per_page 0 and per_page 101 sit outside the inclusive range
    1 to 100, and per_page 100 is the largest accepted value.

    Design: Corner/validations/alarm_sites_list_with_page_zero_is_rejected
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    for _ in range(3):
        X.create_site(api)

    page_zero = api.list_alarm_sites(U.PERMIT_CLERK, {"page": 0, "per_page": 25})
    validate_error(page_zero, E.ERR_INVALID_PAGINATION, expected_status=422)

    per_page_zero = api.list_alarm_sites(U.PERMIT_CLERK, {"page": 1, "per_page": 0})
    validate_error(per_page_zero, E.ERR_INVALID_PAGINATION, expected_status=422)

    per_page_over = api.list_alarm_sites(
        U.PERMIT_CLERK, {"page": 1, "per_page": C.PER_PAGE_MAX + 1}
    )
    validate_error(per_page_over, E.ERR_INVALID_PAGINATION, expected_status=422)

    invoices_page_zero = api.list_penalty_invoices(
        U.BILLING_CLERK, {"page": 0, "per_page": 25}
    )
    validate_error(invoices_page_zero, E.ERR_INVALID_PAGINATION, expected_status=422)

    accepted = api.list_alarm_sites(U.PERMIT_CLERK, {"page": 1, "per_page": C.PER_PAGE_MAX})
    A.assert_total_count(accepted, 3)


def test_approve_registration_with_no_active_fee_schedule_is_rejected(api):
    """Registration approval is refused outright when no fee schedule is ACTIVE at
    the logical clock, and nothing about the premises changes.

    PRD §2.10: "Exactly one fee schedule must be `ACTIVE` at the logical clock to
    govern a fee about to be assessed, on registration approval, permit renewal and
    incident determination alike, failing with `ERR_NO_ACTIVE_FEE_SCHEDULE`."
    PRD §3.2: "On the premises' **first** issuance only, two further things happen:
    `governing_fee_schedule_id` is pinned to the `ACTIVE` schedule, and
    `new_installation_grace_through` is set to `term_start_at` plus
    `new_installation_grace_days`; on every renewed term that field stays null."

    The one schedule that exists was created but never activated, so it is still
    DRAFT and the count of ACTIVE schedules is 0. No permit is issued, no
    PERMIT_ISSUE_FEE invoice is raised and the premises' balance stays at 0.

    Design: Corner/validations/approve_registration_with_no_active_fee_schedule_is_rejected
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    schedule_id = X.create_draft_fee_schedule(api)
    company_id = X.create_company(api)
    site_id = X.create_site(api)
    X.create_contacts(api, site_id, 2)
    system_id = X.create_submitted_system(api, site_id, company_id)

    refused = api.approve_registration(system_id, U.PERMIT_CLERK)
    validate_error(refused, E.ERR_NO_ACTIVE_FEE_SCHEDULE, expected_status=409)

    schedule = get_success_data(api.get_fee_schedule(schedule_id, U.PROGRAM_ADMIN))
    A.assert_status(schedule, "DRAFT")
    A.assert_total_count(
        api.list_fee_schedules(U.PROGRAM_ADMIN, {"status": "ACTIVE"}), 0
    )
    A.assert_status(X.get_system(api, system_id), "SUBMITTED")
    A.assert_total_count(api.list_alarm_permits(U.PERMIT_CLERK), 0)
    site = X.get_site(api, site_id)
    assert site["governing_fee_schedule_id"] is None
    A.assert_money_cents(site["outstanding_balance_cents"], 0)
    assert X.invoices_of_site(api, site_id) == []


def test_permit_renewal_at_a_delinquent_site_is_blocked(api):
    """With an active schedule in place the fiscal row surfaces: a permit the
    nightly run pushed to RENEWAL_BLOCKED cannot be renewed.

    PRD §3.2: "A fiscal side loop sits alongside: when the premises'
    `renewal_block_active` becomes true the run moves `RENEWAL_DUE →
    RENEWAL_BLOCKED`, and renewal attempts are then refused with
    `ERR_PERMIT_RENEWAL_BLOCKED` until the balance clears; when the balance falls
    back strictly below the blocking threshold — either on the next nightly run or
    as part of the recompute cascade of a posted payment — the permit returns
    `RENEWAL_BLOCKED → RENEWAL_DUE` and the block is cleared."
    PRD §2.10: "Permit renewal is refused on the same balance condition, with
    `ERR_PERMIT_RENEWAL_BLOCKED` at HTTP 409."

    Four registrations bill 5500 cents each for 22000. Under the free allowance the
    first two occurrences are priced at 0 and raise no invoice; the third is
    10000 plus a 500-cent administrative fee for 10500 and the fourth is 25000 plus
    1250 for 26250, so the premises owes 58750 before dunning. The nightly run at
    2027-07-05 adds the one-time 10 percent late penalty to each of the six live
    invoices — 550 four times, 1050 and 2625, totalling 5875 — leaving 64625, which
    is at or above the 50000-cent block threshold.

    Design: Corner/validations/permit_renewal_at_a_delinquent_site_is_blocked
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC, system_count=4)
    X.accumulate_counted_incidents(
        api,
        bundle,
        [
            "2026-09-15T02:00:00Z",
            "2026-09-16T02:00:00Z",
            "2026-09-17T02:00:00Z",
            "2026-09-18T02:00:00Z",
        ],
    )
    A.assert_money_cents(X.get_site(api, bundle.site_id)["outstanding_balance_cents"], 58750)

    X.set_clock(api, "2027-07-05T00:00:00Z")
    X.run_nightly(api)

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 64625)
    assert site["renewal_block_active"] is True
    permit_id = bundle.permit_ids[0]
    A.assert_status(X.get_permit(api, permit_id), "RENEWAL_BLOCKED")

    refused = api.renew_permit(
        permit_id,
        {"expected_alarm_permit_version": X.permit_version(api, permit_id)},
        U.PERMIT_CLERK,
    )
    validate_error(refused, E.ERR_PERMIT_RENEWAL_BLOCKED, expected_status=409)

    permit = X.get_permit(api, permit_id)
    A.assert_status(permit, "RENEWAL_BLOCKED")
    assert permit["renewal_count"] == 0
    assert X.invoices_of_site(api, bundle.site_id, kind="PERMIT_RENEWAL_FEE") == []


def test_approve_registration_at_a_delinquent_site_returns_payment_required(api):
    """New permit issuance is refused at the exact blocking balance, and accepted
    once a single cent has been paid against it.

    PRD §2.10: "New permit issuance is refused while the premises' delinquent
    balance is at or above `delinquent_balance_block_cents` (50000 cents by
    default, boundary inclusive), with `ERR_SITE_BALANCE_DELINQUENT` at HTTP 402."
    PRD §3.2: "Revoking a permit for cause produces the identical downstream chain:
    an administrator supplies `revocation_reason`, the permit moves from `ACTIVE`,
    `RENEWAL_DUE`, `RENEWAL_BLOCKED` or `GRACE` to `REVOKED` (terminal), the reason
    is stored, and the system falls to `UNPERMITTED` with the same penalty and the
    same fiscal knock-on."

    With administrative fees switched off, the first issuance bills the 5000-cent
    permit fee and revoking that permit bills the 45000-cent unpermitted-operation
    penalty, so the premises stands at exactly 50000 cents outstanding — the
    inclusive edge of the block. Paying 1 cent leaves 49999, strictly below it.

    Design: Corner/validations/approve_registration_at_a_delinquent_site_returns_payment_required
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_STARTUP_UTC,
        installed_at=C.CLOCK_STARTUP_UTC,
        schedule_overrides={
            "unpermitted_operation_penalty_cents": 45000,
            "admin_fee_pct": 0,
            "admin_fee_min_cents": 0,
        },
    )
    validate_success(
        api.revoke_permit(
            bundle.permit_id,
            {"revocation_reason": "Permit revoked for cause: repeated unverified signals."},
            U.PROGRAM_ADMIN,
        ),
        200,
    )
    A.assert_money_cents(X.get_site(api, bundle.site_id)["outstanding_balance_cents"], 50000)

    second_system_id = X.create_submitted_system(
        api, bundle.site_id, bundle.company_id, system_type="HOLDUP_PANIC", zone_count=2
    )
    refused = api.approve_registration(second_system_id, U.PERMIT_CLERK)
    validate_error(refused, E.ERR_SITE_BALANCE_DELINQUENT, expected_status=402)

    A.assert_status(X.get_system(api, second_system_id), "SUBMITTED")
    A.assert_total_count(
        api.list_alarm_permits(U.PERMIT_CLERK, {"alarm_site_id": bundle.site_id}), 1
    )

    X.post_payment(api, bundle, 1, "2026-08-01T00:00:00Z")
    A.assert_money_cents(X.get_site(api, bundle.site_id)["outstanding_balance_cents"], 49999)
    validate_success(api.approve_registration(second_system_id, U.PERMIT_CLERK), 201)


def test_adjustment_amount_above_outstanding_is_rejected(api):
    """A REDUCE larger than the invoice's outstanding amount is refused, while a
    REDUCE of exactly that amount is accepted.

    PRD §3.8: "The invoice revision must still match, else
    `ERR_STALE_PENALTY_INVOICE_VERSION`; a written-off invoice may not be adjusted
    again, else `ERR_INVOICE_WRITTEN_OFF`; the adjusting `X-User-ID` must differ
    from every `recorded_by_user_id` of a payment already posted to that invoice,
    else `ERR_SEGREGATION_OF_DUTIES`; and the amount must fit — a `WAIVE` or
    `REDUCE` may not exceed the invoice's current `outstanding_cents`, and a
    `WRITE_OFF` is taken at exactly `outstanding_cents`, else
    `ERR_ADJUSTMENT_EXCEEDS_OUTSTANDING`."
    PRD §2.10: "A waive or reduce adjustment must not exceed the invoice's current
    `outstanding_cents`, and a write-off is taken at exactly `outstanding_cents`,
    failing with `ERR_ADJUSTMENT_EXCEEDS_OUTSTANDING`."

    The permit-issue invoice stands at 5000 subtotal plus a 500-cent administrative
    fee, so 5500 assessed and 5500 outstanding with nothing paid. A 6000-cent
    reduce exceeds that by 500 and is refused; 5500 exactly is inside the
    inclusive bound.

    Design: Corner/validations/adjustment_amount_above_outstanding_is_rejected
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC
    )
    invoice = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")[0]
    A.assert_invoice_totals(
        invoice,
        subtotal_cents=C.PERMIT_ISSUE_INVOICE_SUBTOTAL_CENTS,
        admin_fee_cents=C.PERMIT_ISSUE_INVOICE_ADMIN_CENTS,
        assessed_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        outstanding_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        payment_status="UNPAID",
    )

    refused = api.adjust_invoice(
        invoice["id"],
        {
            "adjustment_kind": "REDUCE",
            "reason": "Clerk attempted to reduce past zero.",
            "expected_penalty_invoice_version": invoice["version"],
            "amount_cents": 6000,
        },
        U.PROGRAM_ADMIN,
    )
    validate_error(refused, E.ERR_ADJUSTMENT_EXCEEDS_OUTSTANDING, expected_status=422)

    unchanged = X.get_invoice(api, invoice["id"])
    A.assert_invoice_totals(
        unchanged,
        adjusted_cents=0,
        outstanding_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        payment_status="UNPAID",
    )
    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(
        site["outstanding_balance_cents"], C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS
    )
    A.assert_money_cents(site["credit_balance_cents"], 0)

    exact = X.adjust_invoice(
        api,
        invoice["id"],
        "REDUCE",
        amount_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        reason="Reduced to zero at the inclusive bound.",
    )
    A.assert_invoice_totals(
        exact,
        adjusted_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        outstanding_cents=0,
    )


def test_explicit_allocation_sum_below_the_payment_amount_is_rejected(api):
    """An explicit split that does not account for the whole tender is refused
    outright rather than applied in part.

    PRD §3.9: "In `EXPLICIT` mode the caller dictates the split, and all four
    conditions must hold or the whole tender is rejected with
    `ERR_ALLOCATION_MISMATCH`: the sum of the entries' `amount_cents` must equal the
    payment's `amount_cents` exactly, with no remainder permitted; every entry's
    amount must be at least 1 and no more than that invoice's `outstanding_cents`;
    every named invoice must belong to the paying premises, must not be written off,
    and must be `UNPAID` or `PARTIALLY_PAID`; and no `penalty_invoice_id` may appear
    twice in the array."
    PRD §2.10: "And a posted payment must conserve money: the allocation lines must
    account for exactly the tendered amount net of the residual parked as premises
    credit, failing with `ERR_ALLOCATION_MISMATCH`."

    Two registrations leave two unpaid 5500-cent invoices. Lines of 5500 and 5000
    sum to 10500 against an 11000-cent tender, leaving 500 cents unaccounted for,
    and explicit mode parks no residual as credit. Correcting the second line to
    5500 makes the sum 11000 and settles both invoices.

    Design: Corner/validations/explicit_allocation_sum_below_the_payment_amount_is_rejected
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC, system_count=2
    )
    invoices = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")
    assert len(invoices) == 2
    first_id, second_id = invoices[0]["id"], invoices[1]["id"]

    short = api.create_payment_record(
        F.payment_record_payload(
            bundle.site_id,
            11000,
            "2026-08-01T00:00:00Z",
            X.site_version(api, bundle.site_id),
            method="ACH",
            allocation_mode="EXPLICIT",
            explicit_allocations=[
                {"penalty_invoice_id": first_id, "amount_cents": 5500},
                {"penalty_invoice_id": second_id, "amount_cents": 5000},
            ],
        ),
        U.BILLING_CLERK,
    )
    validate_error(short, E.ERR_ALLOCATION_MISMATCH, expected_status=422)

    A.assert_total_count(api.list_payment_records(U.BILLING_CLERK), 0)
    A.assert_total_count(api.list_payment_allocations(U.BILLING_CLERK), 0)
    for invoice_id in (first_id, second_id):
        A.assert_invoice_totals(
            X.get_invoice(api, invoice_id),
            outstanding_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
            payment_status="UNPAID",
        )
    A.assert_money_cents(X.get_site(api, bundle.site_id)["credit_balance_cents"], 0)

    payment_id = X.post_payment(
        api,
        bundle,
        11000,
        "2026-08-01T00:00:00Z",
        method="ACH",
        allocation_mode="EXPLICIT",
        explicit_allocations=[
            {"penalty_invoice_id": first_id, "amount_cents": 5500},
            {"penalty_invoice_id": second_id, "amount_cents": 5500},
        ],
    )
    payment = X.get_payment(api, payment_id)
    A.assert_money_cents(payment["allocated_cents"], 11000)
    A.assert_money_cents(payment["credited_cents"], 0)
    for invoice_id in (first_id, second_id):
        A.assert_invoice_totals(
            X.get_invoice(api, invoice_id), outstanding_cents=0, payment_status="PAID"
        )


def test_compliance_report_correction_with_identical_counts_is_rejected(api):
    """A correction that restates the stored counts unchanged is refused, so no
    correction is spent on a no-op.

    PRD §2.10: "A correction must change at least one reported metric relative to
    the stored values, failing with `ERR_NO_REPORTABLE_VARIANCE`."
    PRD §3.10: "`variance_pct` is that count divided by the greater of 1 and
    `system_dispatch_count`, at four decimal places."

    The August report claims 3 dispatches for a month with none on record, so
    `variance_count` is 3, `variance_pct` is 3 divided by the greater of 1 and 0,
    that is 3.0000, `period_accuracy` is 1 minus the lesser of 1 and 3.0, that is
    0.0000, `period_ecv_rate` is 0 divided by 3, that is 0.0000, and `period_score`
    is 0.6 times 0 plus 0.4 times 0, that is 0.00. Restating 3 / 0 / 0 changes
    nothing; moving `ecv_attempt_count` to 1 does.

    Design: Corner/validations/compliance_report_correction_with_identical_counts_is_rejected
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC
    )
    report_id = X.submit_compliance_report(
        api,
        bundle,
        "2026-08-01T00:00:00Z",
        "2026-08-31T00:00:00Z",
        reported_dispatch_count=3,
        reported_cancellation_count=0,
        ecv_attempt_count=0,
    )
    X.review_compliance_report(
        api,
        report_id,
        "FLAG_VARIANCE",
        variance_notes="Three dispatches reported for a month with none on record.",
    )

    no_op = api.correct_compliance_report(
        report_id,
        {
            "reported_dispatch_count": 3,
            "reported_cancellation_count": 0,
            "ecv_attempt_count": 0,
        },
        bundle.operator_headers,
    )
    validate_error(no_op, E.ERR_NO_REPORTABLE_VARIANCE, expected_status=409)

    report = X.get_report(api, report_id)
    A.assert_status(report, "VARIANCE_FLAGGED")
    assert report["correction_count"] == 0
    assert report["reported_dispatch_count"] == 3
    assert report["ecv_attempt_count"] == 0
    A.assert_ratio_4dp(report["variance_pct"], 3.0)
    A.assert_score_2dp(report["period_score"], 0.0)

    genuine = api.correct_compliance_report(
        report_id,
        {
            "reported_dispatch_count": 3,
            "reported_cancellation_count": 0,
            "ecv_attempt_count": 1,
        },
        bundle.operator_headers,
    )
    validate_success(genuine, 200)


def test_compliance_report_third_correction_is_rejected(api):
    """The third correction of one report is refused even though its counts differ
    from the stored ones.

    PRD §2.10: "A report may be corrected at most twice, with `correction_count`
    evaluated before the increment, failing with `ERR_CORRECTION_LIMIT_REACHED`."

    Two corrections are accepted, taking `correction_count` to 1 and then 2. The
    third supplies 4 / 1 / 4 against stored counts of 1 / 0 / 2, so the
    change-something row at position 47 is satisfied and only the limit row at
    position 48 can reject the call.

    Design: Corner/validations/compliance_report_third_correction_is_rejected
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC
    )
    report_id = X.submit_compliance_report(
        api,
        bundle,
        "2026-08-01T00:00:00Z",
        "2026-08-31T00:00:00Z",
        reported_dispatch_count=3,
        reported_cancellation_count=0,
        ecv_attempt_count=0,
    )
    X.review_compliance_report(
        api,
        report_id,
        "FLAG_VARIANCE",
        variance_notes="Three dispatches reported for a month with none on record.",
    )

    first = api.correct_compliance_report(
        report_id,
        {
            "reported_dispatch_count": 2,
            "reported_cancellation_count": 0,
            "ecv_attempt_count": 1,
        },
        bundle.operator_headers,
    )
    validate_success(first, 200)
    assert get_success_data(first)["correction_count"] == 1
    X.review_compliance_report(
        api,
        report_id,
        "FLAG_VARIANCE",
        variance_notes="Two dispatches reported for a month with none on record.",
    )

    second = api.correct_compliance_report(
        report_id,
        {
            "reported_dispatch_count": 1,
            "reported_cancellation_count": 0,
            "ecv_attempt_count": 2,
        },
        bundle.operator_headers,
    )
    validate_success(second, 200)
    assert get_success_data(second)["correction_count"] == 2
    X.review_compliance_report(
        api,
        report_id,
        "FLAG_VARIANCE",
        variance_notes="One dispatch reported for a month with none on record.",
    )

    third = api.correct_compliance_report(
        report_id,
        {
            "reported_dispatch_count": 4,
            "reported_cancellation_count": 1,
            "ecv_attempt_count": 4,
        },
        bundle.operator_headers,
    )
    validate_error(third, E.ERR_CORRECTION_LIMIT_REACHED, expected_status=409)

    report = X.get_report(api, report_id)
    assert report["correction_count"] == 2
    assert report["reported_dispatch_count"] == 1
    assert report["reported_cancellation_count"] == 0
    assert report["ecv_attempt_count"] == 2


def test_collections_referral_of_an_appealed_incident_invoice_is_rejected(api):
    """While an appeal is live, the linked invoice cannot be referred, and that
    answer outranks the referral-criteria complaint the same call would also earn.

    PRD §2.10: "An invoice whose linked incident is `APPEALED` may be neither
    referred to collections nor escalated in dunning while the appeal is live,
    failing with `ERR_INVOICE_UNDER_APPEAL`."
    PRD §3.6: "That freeze is also enforced synchronously: a collections referral
    against an invoice whose linked incident is `APPEALED` is refused with
    `ERR_INVOICE_UNDER_APPEAL`."
    PRD §3.6: "Withdrawal from either state returns the incident from `APPEALED` to
    `COUNTED` and resumes dunning on its invoice; withdrawal from `SCHEDULED`
    additionally decrements the docket's `scheduled_appeal_count`, and if that
    docket was `CLOSED_FOR_SCHEDULING` the freed seat reopens it,
    `CLOSED_FOR_SCHEDULING → OPEN`."

    The schedule prices the first occurrence at 5000 with the administrative floor
    switched off, so the fee invoice is 5000 plus a 250-cent administrative fee for
    5250 assessed. Its dunning stage is still CURRENT and it is 0 days past due, so
    every referral criterion fails too; the appeal freeze at position 52 answers
    before the criteria row at position 53. Once the appeal is withdrawn the freeze
    lifts and the criteria row is what the caller sees.

    Design: Corner/validations/collections_referral_of_an_appealed_incident_invoice_is_rejected
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-09-20T00:00:00Z",
        schedule_overrides={
            "free_alarm_allowance": 0,
            "fee_tiers": [{"from_index": 1, "to_index": None, "base_fee_cents": 5000}],
            "admin_fee_min_cents": 0,
        },
    )
    incident = X.create_reported_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.set_clock(api, "2026-09-20T01:00:00Z")
    X.determine_counted(api, incident.incident_id)
    invoice = X.invoice_for_incident(api, incident.incident_id)
    A.assert_invoice_totals(
        invoice,
        subtotal_cents=5000,
        admin_fee_cents=250,
        assessed_cents=5250,
        outstanding_cents=5250,
        collections_stage="CURRENT",
    )
    appeal_id = X.file_appeal(api, bundle, incident.incident_id)

    frozen = api.refer_invoice_to_collections(
        invoice["id"],
        {"referral_agency": "Trinity Municipal Recovery Services"},
        U.BILLING_CLERK,
    )
    validate_error(frozen, E.ERR_INVOICE_UNDER_APPEAL, expected_status=409)

    A.assert_status(X.get_incident(api, incident.incident_id), "APPEALED")
    A.assert_status(X.get_appeal(api, appeal_id), "FILED")
    still_current = X.get_invoice(api, invoice["id"])
    assert still_current["collections_stage"] == "CURRENT"
    assert still_current["referred_on"] is None
    assert still_current["referral_total_cents"] is None

    validate_success(api.withdraw_appeal(appeal_id, bundle.holder_headers), 200)
    A.assert_status(X.get_incident(api, incident.incident_id), "COUNTED")

    thawed = api.refer_invoice_to_collections(
        invoice["id"],
        {"referral_agency": "Trinity Municipal Recovery Services"},
        U.BILLING_CLERK,
    )
    validate_error(thawed, E.ERR_REFERRAL_CRITERIA_NOT_MET, expected_status=409)


def test_collections_referral_before_ninety_days_is_rejected(api):
    """A referral is refused while only two of its three criteria hold, and is
    accepted once the delinquency reaches ninety days.

    PRD §3.8: "Every criterion must hold together: `collections_stage` must be
    `FINAL_NOTICE`, `days_delinquent` at or above `delinquency_days`, and
    `outstanding_cents` at or above `collections_referral_threshold_cents`, else
    `ERR_REFERRAL_CRITERIA_NOT_MET`; the linked incident must not be `APPEALED`,
    else `ERR_INVOICE_UNDER_APPEAL`; and a written-off invoice may not be referred,
    else `ERR_INVOICE_WRITTEN_OFF`."
    PRD §3.8: "The nightly run advances `CURRENT → NOTICE` once `days_delinquent` is
    at least 1, and `NOTICE → FINAL_NOTICE` once it is at least 30; both steps
    require `outstanding_cents` above zero and require that the linked incident,
    when there is one, is not in `APPEALED`."

    The revoked permit raises a 24000-cent unpermitted-operation penalty issued
    2026-08-01 and due 30 days later on 2026-08-31. The nightly run at 2026-09-01
    finds 1 day delinquent, moves the stage to NOTICE and adds the one-time 10
    percent late penalty of 2400, so the invoice stands at 26400. The run at
    2026-09-30 finds 30 days delinquent and moves it to FINAL_NOTICE. Stage and
    money both qualify, but 30 is short of the 90-day requirement; at 2026-11-29,
    exactly 90 days past due, the same call succeeds.

    Design: Corner/validations/collections_referral_before_ninety_days_is_rejected
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_STARTUP_UTC,
        installed_at=C.CLOCK_STARTUP_UTC,
        schedule_overrides={
            "permit_issue_fee_cents": 0,
            "unpermitted_operation_penalty_cents": 24000,
            "admin_fee_pct": 0,
            "admin_fee_min_cents": 0,
        },
    )
    validate_success(
        api.revoke_permit(
            bundle.permit_id,
            {"revocation_reason": "Permit revoked for cause: repeated unverified signals."},
            U.PROGRAM_ADMIN,
        ),
        200,
    )
    invoice = X.invoices_of_site(
        api, bundle.site_id, kind="UNPERMITTED_OPERATION_PENALTY"
    )[0]
    A.assert_invoice_totals(invoice, assessed_cents=24000, outstanding_cents=24000)
    assert invoice["due_on"][:10] == "2026-08-31"

    X.set_clock(api, "2026-09-01T00:00:00Z")
    X.run_nightly(api)
    X.set_clock(api, "2026-09-30T00:00:00Z")
    X.run_nightly(api)

    escalated = X.get_invoice(api, invoice["id"])
    assert escalated["collections_stage"] == "FINAL_NOTICE"
    A.assert_money_cents(escalated["late_penalty_cents"], 2400)
    A.assert_money_cents(escalated["outstanding_cents"], 26400)
    assert escalated["days_delinquent"] == 30

    too_early = api.refer_invoice_to_collections(
        invoice["id"],
        {"referral_agency": "Trinity Municipal Recovery Services"},
        U.BILLING_CLERK,
    )
    validate_error(too_early, E.ERR_REFERRAL_CRITERIA_NOT_MET, expected_status=409)

    unchanged = X.get_invoice(api, invoice["id"])
    assert unchanged["collections_stage"] == "FINAL_NOTICE"
    assert unchanged["referred_on"] is None

    X.set_clock(api, "2026-11-29T00:00:00Z")
    X.run_nightly(api)
    assert X.get_invoice(api, invoice["id"])["days_delinquent"] == 90
    accepted = api.refer_invoice_to_collections(
        invoice["id"],
        {"referral_agency": "Trinity Municipal Recovery Services"},
        U.BILLING_CLERK,
    )
    validate_success(accepted, 200)
    assert get_success_data(accepted)["collections_stage"] == "REFERRED"


def test_approve_registration_on_an_already_permitted_system_returns_invalid_state(api):
    """A second approval of the same registration is refused by the declared-state
    row, not by the active-permit row.

    PRD §2.10: "An alarm system may hold at most one permit in `ACTIVE`,
    `RENEWAL_DUE` or `GRACE`, so a second issuance fails with
    `ERR_ACTIVE_PERMIT_EXISTS`."
    PRD §3.2: "Approval then fires a chain of writes."
    PRD §3.2: "Rejection is the sibling branch out of `SUBMITTED`."

    The only issuance surface leaves the system in PERMITTED, so by the time a
    second approval arrives the declared source state no longer holds. The state
    row sits at position 17 and the active-permit row at position 42, so
    ERR_INVALID_STATE is what the caller sees and the active-permit row is
    structurally unreachable here.

    Design: Corner/validations/approve_registration_on_an_already_permitted_system_returns_invalid_state
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC
    )
    before = X.get_system(api, bundle.system_id)
    A.assert_status(before, "PERMITTED")

    second = api.approve_registration(bundle.system_id, U.PERMIT_CLERK)
    validate_error(second, E.ERR_INVALID_STATE, expected_status=409)

    permits = api.list_alarm_permits(
        U.PERMIT_CLERK, {"alarm_system_id": bundle.system_id}
    )
    rows = A.assert_total_count(permits, 1)
    assert rows[0]["id"] == bundle.permit_id
    A.assert_status(rows[0], "ACTIVE")
    after = X.get_system(api, bundle.system_id)
    A.assert_status(after, "PERMITTED")
    A.assert_version_unchanged(before, after)
    A.assert_money_cents(
        X.get_site(api, bundle.site_id)["outstanding_balance_cents"],
        C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
    )


SIX_OCCURRENCES = [
    "2026-09-15T02:00:00Z",
    "2026-09-16T02:00:00Z",
    "2026-09-17T02:00:00Z",
    "2026-09-18T02:00:00Z",
    "2026-09-19T02:00:00Z",
    "2026-09-20T02:00:00Z",
]


def test_reinstatement_request_with_a_stale_technician_inspection_is_rejected(api):
    """An inspection thirty-one days old is refused while one exactly thirty days
    old is accepted.

    PRD §3.7: "The inspection must be fresh and not fictional:
    `technician_inspection_date` must be at or after the logical clock minus 30
    whole days — the boundary inclusive, so an inspection exactly 30 days old still
    qualifies — and at or before the logical clock, else
    `ERR_INSPECTION_EVIDENCE_STALE`."
    PRD §3.7: "Serving also issues a `REINSTATEMENT_FEE` invoice against the
    premises with `suspension_order_id` set, recomputes the premises'
    `response_status` to `RESPONSE_SUSPENDED` along with its
    `outstanding_balance_cents` and `renewal_block_active`, and bumps the premises'
    `version` by 1."

    Freshness is measured against the logical clock and not against the order's own
    dates. At clock 2026-10-05 the cut-off is 2026-09-05, so an inspection dated
    2026-09-04 is one day too old and is refused, while 2026-09-05 sits exactly on
    the inclusive boundary and is accepted. The attestation and the summary are both
    present and well formed in each call, so nothing else can answer.

    Design: Corner/validations/reinstatement_request_with_a_stale_technician_inspection_is_rejected
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC, system_count=6
    )
    X.accumulate_counted_incidents(api, bundle, SIX_OCCURRENCES)
    order_id = X.orders_of_site(api, bundle.site_id)[0]["id"]
    validate_success(api.serve_suspension_order(order_id, U.PROGRAM_ADMIN), 200)
    X.set_clock(api, "2026-10-05T00:00:00Z")
    served = X.get_order(api, order_id)
    A.assert_status(served, "EFFECTIVE")
    assert served["required_conditions"]["min_ecv_contacts"] == 2

    stale = api.request_reinstatement(
        order_id,
        {
            "technician_inspection_date": "2026-09-04T00:00:00Z",
            "ecv_attestation": True,
            "corrective_action_summary": (
                "Panel firmware updated, two zones re-wired and the ECV call list "
                "re-verified."
            ),
        },
        bundle.holder_headers,
    )
    validate_error(stale, E.ERR_INSPECTION_EVIDENCE_STALE, expected_status=409)

    unchanged = X.get_order(api, order_id)
    A.assert_status(unchanged, "EFFECTIVE")
    assert unchanged["reinstatement_requested_at"] is None
    assert unchanged["technician_inspection_date"] is None
    A.assert_version_unchanged(served, unchanged)
    assert X.get_site(api, bundle.site_id)["response_status"] == "RESPONSE_SUSPENDED"

    on_boundary = api.request_reinstatement(
        order_id,
        {
            "technician_inspection_date": "2026-09-05T00:00:00Z",
            "ecv_attestation": True,
            "corrective_action_summary": (
                "Panel firmware updated, two zones re-wired and the ECV call list "
                "re-verified."
            ),
        },
        bundle.holder_headers,
    )
    validate_success(on_boundary, 200)
    A.assert_status(get_success_data(on_boundary), "REINSTATEMENT_PENDING")


def test_reinstatement_request_without_the_ecv_attestation_is_rejected(api):
    """A well-typed but negative attestation, and an empty corrective summary
    beside a true one, both earn the attestation error rather than a missing-field
    complaint.

    PRD §3.7: "The attestation must be affirmative and accompanied by a non-empty
    `corrective_action_summary`, else `ERR_ECV_ATTESTATION_REQUIRED`."
    PRD §3.7: "On success the order moves to `REINSTATEMENT_PENDING`, storing
    `reinstatement_requested_at` at the logical clock together with the inspection
    date and attestation."

    The inspection is dated 2026-10-01 against a clock of 2026-10-05, four days old
    and comfortably inside the thirty-day freshness rule, so the staleness row is
    satisfied and only the attestation requirement can answer. Both halves of that
    requirement are one rule, so a false attestation and an empty summary yield the
    same error id; supplying both correctly moves the order on.

    Design: Corner/validations/reinstatement_request_without_the_ecv_attestation_is_rejected
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC, system_count=6
    )
    X.accumulate_counted_incidents(api, bundle, SIX_OCCURRENCES)
    order_id = X.orders_of_site(api, bundle.site_id)[0]["id"]
    validate_success(api.serve_suspension_order(order_id, U.PROGRAM_ADMIN), 200)
    X.set_clock(api, "2026-10-05T00:00:00Z")

    refused = api.request_reinstatement(
        order_id,
        {
            "technician_inspection_date": "2026-10-01T00:00:00Z",
            "ecv_attestation": False,
            "corrective_action_summary": "Panel firmware updated; ECV list not yet re-verified.",
        },
        bundle.holder_headers,
    )
    validate_error(refused, E.ERR_ECV_ATTESTATION_REQUIRED, expected_status=422)
    A.assert_status(X.get_order(api, order_id), "EFFECTIVE")

    empty_summary = api.request_reinstatement(
        order_id,
        {
            "technician_inspection_date": "2026-10-01T00:00:00Z",
            "ecv_attestation": True,
            "corrective_action_summary": "",
        },
        bundle.holder_headers,
    )
    validate_error(empty_summary, E.ERR_ECV_ATTESTATION_REQUIRED, expected_status=422)
    A.assert_status(X.get_order(api, order_id), "EFFECTIVE")

    accepted = api.request_reinstatement(
        order_id,
        {
            "technician_inspection_date": "2026-10-01T00:00:00Z",
            "ecv_attestation": True,
            "corrective_action_summary": (
                "Panel firmware updated, two zones re-wired and the ECV call list "
                "re-verified."
            ),
        },
        bundle.holder_headers,
    )
    validate_success(accepted, 200)
    pending = get_success_data(accepted)
    A.assert_status(pending, "REINSTATEMENT_PENDING")
    assert pending["reinstatement_requested_at"][:19] == "2026-10-05T00:00:00"
    assert pending["technician_inspection_date"][:19] == "2026-10-01T00:00:00"


def test_lift_with_an_outstanding_site_balance_returns_payment_required(api):
    """A properly applied-for reinstatement is still refused while the premises owes
    money.

    PRD §3.7: "The money condition is absolute: every invoice for the premises whose
    `collections_stage` is not `WRITTEN_OFF` must have `payment_status` of `PAID`, so
    that the premises' outstanding penalty balance net of `credit_balance_cents` is
    zero, else `ERR_OUTSTANDING_BALANCE_BLOCKS_REINSTATEMENT`."
    PRD §3.7: "On success the order becomes `LIFTED`, terminal, with `lifted_at`
    stamped; the premises' `lifted_suspension_count` rises by 1, raising the next
    order's fee, probation and contact requirement; `response_status` is recomputed
    to `RESPONSE_PROBATION` for `probation_days` whole days measured from
    `lifted_at`, and the premises' `version` rises by 1."

    Six permits bill 5500 each for 33000. The first two occurrences fall inside the
    free allowance and raise no invoice at all; the residential occurrences 3 to 6
    are priced at 10000, 25000, 40000 and 75000 with administrative fees of 500,
    1250, 2000 and 3750, so their assessments are 10500, 26250, 42000 and 78750 for
    157500. Serving adds a reinstatement fee of 60000 plus 3000 for 63000. The
    premises therefore owes 253500 against a zero credit balance, so the lift is
    refused on money rather than on state or attestation.

    Design: Corner/validations/lift_with_an_outstanding_site_balance_returns_payment_required
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC, system_count=6
    )
    X.accumulate_counted_incidents(api, bundle, SIX_OCCURRENCES)
    order_id = X.orders_of_site(api, bundle.site_id)[0]["id"]
    validate_success(api.serve_suspension_order(order_id, U.PROGRAM_ADMIN), 200)
    X.set_clock(api, "2026-10-05T00:00:00Z")
    request = api.request_reinstatement(
        order_id,
        {
            "technician_inspection_date": "2026-10-01T00:00:00Z",
            "ecv_attestation": True,
            "corrective_action_summary": (
                "Panel firmware updated, two zones re-wired and the ECV call list "
                "re-verified."
            ),
        },
        bundle.holder_headers,
    )
    validate_success(request, 200)
    requested = get_success_data(request)
    A.assert_status(requested, "REINSTATEMENT_PENDING")
    assert requested["reinstatement_requested_at"][:19] == "2026-10-05T00:00:00"

    site_before = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site_before["outstanding_balance_cents"], 253500)
    A.assert_money_cents(site_before["credit_balance_cents"], 0)

    blocked = api.lift_suspension_order(order_id, U.PROGRAM_ADMIN)
    validate_error(
        blocked, E.ERR_OUTSTANDING_BALANCE_BLOCKS_REINSTATEMENT, expected_status=402
    )

    after = X.get_order(api, order_id)
    A.assert_status(after, "REINSTATEMENT_PENDING")
    assert after["lifted_at"] is None
    site_after = X.get_site(api, bundle.site_id)
    assert site_after["lifted_suspension_count"] == 0
    assert site_after["response_status"] == "RESPONSE_SUSPENDED"


def test_company_reinstatement_without_two_good_periods_is_rejected(api):
    """Reinstating a suspended monitoring company is refused while it has filed no
    accepted reporting periods at all.

    PRD §3.10: "`REINSTATE` returns a `SUSPENDED` company to `PROBATION` — never
    straight to `ACTIVE` — and must be earned: two consecutive accepted periods
    scoring at or above the 0.70 good-standing threshold, whose `period_end` falls
    after the `probation_started_at` anchor, else
    `ERR_COMPANY_REINSTATEMENT_NOT_EARNED`."
    PRD §3.10: "`SUSPEND` is available from `ACTIVE` or `PROBATION` and carries the
    same dispatch consequences as the automatic suspension, stamping
    `probation_started_at` when the company was still `ACTIVE`."

    The hand-applied suspension is a declared move out of the active state, so the
    transition itself is legal and the reinstatement request meets a satisfied state
    row. What it cannot meet is the earned condition: the company's accepted-report
    set is empty, so it has zero of the two consecutive qualifying periods, and the
    action is refused with no change to the row.

    Design: Corner/validations/company_reinstatement_without_two_good_periods_is_rejected
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    company_id = X.create_company(api, legal_name="Guardian Signal Monitoring LLC")
    validate_success(
        api.company_status_action(
            company_id,
            {
                "action": "SUSPEND",
                "status_reason": "Repeated unverified dispatch requests from the ECV desk.",
            },
            U.PROGRAM_ADMIN,
        ),
        200,
    )
    suspended = X.get_company(api, company_id)
    A.assert_status(suspended, "SUSPENDED")

    not_earned = api.company_status_action(
        company_id,
        {"action": "REINSTATE", "status_reason": "Owner asserts the ECV desk has been retrained."},
        U.PROGRAM_ADMIN,
    )
    validate_error(not_earned, E.ERR_COMPANY_REINSTATEMENT_NOT_EARNED, expected_status=409)

    after = X.get_company(api, company_id)
    A.assert_status(after, "SUSPENDED")
    A.assert_version_unchanged(suspended, after)
    accepted = api.list_compliance_reports(
        U.REVIEW_OFFICER, {"monitoring_company_id": company_id, "status": "ACCEPTED"}
    )
    A.assert_total_count(accepted, 0)


def test_suspension_order_whose_basis_fell_away_after_a_grant_is_rejected(api):
    """A granted appeal drops the window count below the threshold, and a fresh
    enforcement order is then refused even though six incidents are still on record.

    PRD §2.10: "A suspension order's basis must still hold — the premises'
    chargeable count under its governing window must be at or above
    `suspension_threshold_count`, which defaults to 6 — both when the order is
    created and when it is served, failing with
    `ERR_SUSPENSION_BASIS_NO_LONGER_MET`."
    PRD §3.6: "Hop two: because the incident left the chargeable set, the premises'
    chargeable counters decrement and every remaining chargeable incident at that
    premises — those in `COUNTED` or `APPEALED` — is renumbered contiguously in
    order of occurrence instant ascending then creation instant ascending, and its
    fee re-derived at its new tier."
    PRD §3.6: "Hop four: because the premises' `chargeable_count_window` has fallen
    below `suspension_threshold_count`, every suspension order for that premises in
    `PROPOSED`, `EFFECTIVE` or `REINSTATEMENT_PENDING` moves to `VACATED` and
    `response_status` is recomputed."

    Six chargeable occurrences met the threshold of 6 and auto-proposed an order.
    Granting the appeal on the third occurrence takes it out of the chargeable set,
    leaving five survivors renumbered 1 through 5 and vacating the stale order. The
    threshold is therefore re-tested at issuance and 5 is below 6, so the fresh
    order is refused: the quoted premises revision is current and the interval lies
    wholly in the future, and the only live order was vacated, so neither the
    revision, the temporal nor the overlap row can answer instead.

    Design: Corner/validations/suspension_order_whose_basis_fell_away_after_a_grant_is_rejected
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC, system_count=6
    )
    incidents = X.accumulate_counted_incidents(api, bundle, SIX_OCCURRENCES)
    auto_order = X.orders_of_site(api, bundle.site_id)[0]
    A.assert_status(auto_order, "PROPOSED")

    appeal_id, _docket_id = X.create_heard_appeal(
        api,
        bundle,
        incidents[2].incident_id,
        session_start="2026-10-05T14:00:00Z",
        session_end="2026-10-05T16:00:00Z",
        grounds="EXEMPT_CAUSE",
    )
    granted = X.decide_appeal(
        api, appeal_id, "GRANTED", exempt_cause_code="UTILITY_POWER_FAILURE"
    )
    A.assert_status(granted, "GRANTED", field="decision")

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 5
    survivors = [
        row for row in X.incidents_of_site(api, bundle.site_id) if row["status"] == "COUNTED"
    ]
    assert {row["occurrence_index"] for row in survivors} == {1, 2, 3, 4, 5}
    A.assert_status(X.get_order(api, auto_order["id"]), "VACATED")

    refused = api.create_suspension_order(
        F.suspension_order_payload(
            bundle.site_id,
            incidents[5].incident_id,
            "2026-10-06T00:00:00Z",
            "2026-11-05T00:00:00Z",
            site["version"],
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(refused, E.ERR_SUSPENSION_BASIS_NO_LONGER_MET, expected_status=409)

    still_proposed = api.list_suspension_orders(
        U.PROGRAM_ADMIN, {"alarm_site_id": bundle.site_id, "status": "PROPOSED"}
    )
    A.assert_total_count(still_proposed, 0)


def test_rehearing_of_a_withdrawn_appeal_is_rejected(api):
    """A withdrawn appeal grants no second bite, while a denied one does.

    PRD §3.6: "It is accepted only when the prior appeal actually reached `DENIED` —
    a `WITHDRAWN` or `GRANTED` appeal grants no second bite — and only when no
    rehearing has already been filed against that prior appeal, else
    `ERR_REHEARING_NOT_ELIGIBLE`."
    PRD §3.6: "The new row's `rehearing_depth` is the prior appeal's
    `rehearing_depth` plus 1, and an original appeal has depth 0."
    PRD §3.6: "A withdrawn appeal is not eligible for rehearing."

    Withdrawing the first appeal returns its incident to the counted state, so the
    live-appeal row is satisfied and the rehearing row is the one left to answer:
    the named prior appeal is withdrawn, the filing is refused, and no depth-1 row
    is created. The second incident's appeal is heard and denied instead, and the
    identical filing against it is accepted at depth 1.

    Design: Corner/validations/rehearing_of_a_withdrawn_appeal_is_rejected
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC, system_count=2
    )
    incidents = X.accumulate_counted_incidents(
        api, bundle, ["2026-09-15T02:00:00Z", "2026-09-16T02:00:00Z"]
    )
    X.set_clock(api, "2026-09-20T01:00:00Z")

    first_appeal = X.file_appeal(api, bundle, incidents[0].incident_id)
    validate_success(
        api.withdraw_appeal(
            first_appeal,
            bundle.holder_headers,
            {"withdrawal_reason": "Owner decided to pay rather than attend the hearing."},
        ),
        200,
    )
    A.assert_status(X.get_appeal(api, first_appeal), "WITHDRAWN")
    A.assert_status(X.get_incident(api, incidents[0].incident_id), "COUNTED")

    refused = api.create_appeal(
        F.appeal_payload(
            incidents[0].incident_id,
            grounds="COUNTING_ERROR",
            narrative="Owner reconsidered and asks for a rehearing of the withdrawn matter.",
            expected_false_alarm_incident_version=X.incident_version(
                api, incidents[0].incident_id
            ),
            prior_appeal_id=first_appeal,
        ),
        bundle.holder_headers,
    )
    validate_error(refused, E.ERR_REHEARING_NOT_ELIGIBLE, expected_status=409)
    A.assert_total_count(
        api.list_appeals(U.PROGRAM_ADMIN, {"prior_appeal_id": first_appeal}), 0
    )

    denied_appeal, _docket_id = X.create_heard_appeal(
        api,
        bundle,
        incidents[1].incident_id,
        session_start="2026-09-21T14:00:00Z",
        session_end="2026-09-21T16:00:00Z",
    )
    X.decide_appeal(api, denied_appeal, "DENIED")
    A.assert_status(X.get_incident(api, incidents[1].incident_id), "COUNTED")

    rehearing = api.create_appeal(
        F.appeal_payload(
            incidents[1].incident_id,
            grounds="COUNTING_ERROR",
            narrative="Owner asks for a rehearing of the denied matter on the counting point.",
            expected_false_alarm_incident_version=X.incident_version(
                api, incidents[1].incident_id
            ),
            prior_appeal_id=denied_appeal,
        ),
        bundle.holder_headers,
    )
    validate_success(rehearing, 201)
    assert get_success_data(rehearing)["rehearing_depth"] == 1


def test_fourth_scheduled_appeal_fills_the_docket_exactly_to_capacity(api):
    """The fourth seat on a capacity-4 session is legal, closes the docket in the
    same request, and makes a fifth attempt meet the not-open error.

    PRD §3.6: "the docket's seat count including the appeal being added must not
    exceed `capacity`, else `ERR_DOCKET_CAPACITY_EXCEEDED`; and the session must not
    already have begun — the logical clock must be strictly before `session_start`,
    else `ERR_HEARING_SESSION_IN_PAST`."
    PRD §3.6: "On success the appeal moves to `SCHEDULED` with its
    `hearing_docket_id` set, and the docket's `scheduled_appeal_count` and `version`
    each rise by 1."
    PRD §3.6: "When the count reaches `capacity` the docket closes itself, `OPEN →
    CLOSED_FOR_SCHEDULING`, and further seating attempts meet
    `ERR_DOCKET_NOT_OPEN`."
    PRD §2.10: "Scheduling must not push a docket's scheduled appeal count above its
    `capacity`, the count being evaluated including the appeal being added, failing
    with `ERR_DOCKET_CAPACITY_EXCEEDED`."

    The docket is created at the default capacity of 4 with version 1 and an empty
    seat count. Each accepted seat raises both the count and the version by 1, so
    the first three seats read 1, 2, 3 against versions 2, 3, 4 with the docket
    still open. The fourth seat is the boundary case: the count including the appeal
    being added is exactly 4, which does not exceed the capacity, so it is accepted
    and the version reaches 5 while the docket auto-closes in the same response. A
    fifth attempt therefore meets the not-open row at position 20 rather than the
    capacity row at position 38.

    Design: Corner/validations/fourth_scheduled_appeal_fills_the_docket_exactly_to_capacity
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, installed_at=C.CLOCK_STARTUP_UTC, system_count=5
    )
    incidents = X.accumulate_counted_incidents(
        api,
        bundle,
        [
            "2026-09-15T02:00:00Z",
            "2026-09-16T02:00:00Z",
            "2026-09-17T02:00:00Z",
            "2026-09-18T02:00:00Z",
            "2026-09-19T02:00:00Z",
        ],
    )
    X.set_clock(api, "2026-09-20T01:00:00Z")
    docket_id = X.create_docket(api, "2026-10-05T14:00:00Z", "2026-10-05T16:00:00Z")
    fresh = get_success_data(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))
    assert fresh["capacity"] == 4
    assert fresh["scheduled_appeal_count"] == 0
    assert fresh["version"] == 1
    A.assert_status(fresh, "OPEN")

    grounds = [
        "WRONG_CAUSE_CODE",
        "EXEMPT_CAUSE",
        "COUNTING_ERROR",
        "FEE_CALCULATION_ERROR",
        "NOT_MY_SYSTEM",
    ]
    appeals = [
        X.file_appeal(api, bundle, incidents[index].incident_id, grounds=grounds[index])
        for index in range(5)
    ]

    for seat, expected_count in enumerate([1, 2, 3], start=1):
        seated = X.schedule_appeal(api, appeals[seat - 1], docket_id)
        A.assert_status(seated, "SCHEDULED")
        assert seated["hearing_docket_id"] == docket_id
        row = get_success_data(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))
        assert row["scheduled_appeal_count"] == expected_count
        assert row["version"] == expected_count + 1
        A.assert_status(row, "OPEN")

    fourth = api.schedule_appeal(
        appeals[3],
        {
            "hearing_docket_id": docket_id,
            "expected_hearing_docket_version": X.docket_version(api, docket_id),
        },
        U.HEARING_OFFICER,
    )
    validate_success(fourth, 200)
    fourth_appeal = get_success_data(fourth)
    A.assert_status(fourth_appeal, "SCHEDULED")
    assert fourth_appeal["hearing_docket_id"] == docket_id

    full = get_success_data(api.get_hearing_docket(docket_id, U.HEARING_OFFICER))
    assert full["scheduled_appeal_count"] == 4
    assert full["capacity"] == 4
    assert full["version"] == 5
    A.assert_status(full, "CLOSED_FOR_SCHEDULING")

    fifth = api.schedule_appeal(
        appeals[4],
        {
            "hearing_docket_id": docket_id,
            "expected_hearing_docket_version": full["version"],
        },
        U.HEARING_OFFICER,
    )
    validate_error(fifth, E.ERR_DOCKET_NOT_OPEN, expected_status=409)
    A.assert_status(X.get_appeal(api, appeals[4]), "FILED")
