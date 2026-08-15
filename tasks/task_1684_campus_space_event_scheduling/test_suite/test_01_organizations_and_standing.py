"""Organizations: registration defaults, standing thresholds, suspension and
probation gates."""

from test_helpers import (
    SCHEDULER,
    ApiErrorId,
    approve_event,
    assert_organization,
    confirm_event,
    create_event,
    create_organization_payload,
    daily_close,
    find_invoice_for_event,
    get_event,
    get_org,
    get_room,
    make_org_requester_headers,
    org_headers,
    pay_invoice,
    set_clock,
    setup_org_room,
    setup_org_with_no_shows,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_organization_ignores_client_supplied_standing(api):
    """PRD §3.1: "New organizations begin with `standing` of `GOOD`, a
    `no_show_count` of zero, and zero balances."

    Design: Corner/entities/org_create_computed_standing_input_ignored
    """
    payload = create_organization_payload(
        name="Econ Dept",
        org_type="INTERNAL_DEPARTMENT",
        contact_email="econ@univ.edu",
    )
    payload["standing"] = "SUSPENDED"
    response = api.create_organization(payload, SCHEDULER)
    data = validate_success(response, 201)
    assert_organization(data)
    assert data["standing"] == "GOOD", "client-supplied standing must be ignored"
    assert data["no_show_count"] == 0
    assert data["deposit_held_cents"] == 0
    assert data["outstanding_balance_cents"] == 0


def test_two_no_show_strikes_land_on_probation_not_suspended(api):
    """PRD §3.1: "An organization with a `no_show_count` of exactly two moves from
    `GOOD` to `PROBATION`; one whose count reaches three or more moves from
    `PROBATION` to `SUSPENDED`; a count of one or zero keeps the organization
    `GOOD`."
    PRD §2.4: "The checkpoint response reports per-step counters: `terms_advanced`,
    `rooms_returned`, `requests_expired`, `approvals_expired`, `no_shows_marked`,
    `events_completed`, `grants_overdue`, and `orgs_suspended`."

    Design: Corner/cross_cutting_layers/standing_threshold_two_strikes_probation_not_suspended
    """
    scn = setup_org_room(room_overrides={"turnaround_buffer_minutes": 0})
    e1 = create_event(
        scn.org, scn.room["id"],
        start_at="2026-09-10T08:00:00Z", end_at="2026-09-10T09:00:00Z",
        expected_attendance=5, title="N1",
    )
    e2 = create_event(
        scn.org, scn.room["id"],
        start_at="2026-09-10T09:00:00Z", end_at="2026-09-10T10:00:00Z",
        expected_attendance=5, title="N2",
    )
    approve_event(e1["id"])
    approve_event(e2["id"])
    set_clock("2026-08-02T00:00:00Z")
    confirm_event(e1["id"], scn.org)
    confirm_event(e2["id"], scn.org)

    # A third request filed before the close whose decision deadline survives it.
    set_clock("2026-09-10T11:00:00Z")
    e3 = create_event(
        scn.org, scn.room["id"],
        start_at="2026-09-21T14:00:00Z", end_at="2026-09-21T15:00:00Z",
        expected_attendance=5, title="Pending",
    )
    set_clock("2026-09-10T12:00:00Z")
    counters = daily_close()

    assert counters["no_shows_marked"] == 2
    assert counters["orgs_suspended"] == 0

    org = get_org(scn.org["id"])
    assert org["no_show_count"] == 2
    assert org["standing"] == "PROBATION", "exactly two strikes is PROBATION"

    # PROBATION triggers no decline cascade: the pending request survives.
    e3_after = get_event(e3["id"])
    assert e3_after["status"] == "REQUESTED"


def test_suspended_org_cannot_create_event(api):
    """PRD §3.4: "An event created while the organization is `SUSPENDED` is
    rejected with `ERR_ORG_SUSPENDED`."
    PRD §3.1: "a `SUSPENDED` organization cannot create new event requests and its
    events cannot be approved, both rejected with `ERR_ORG_SUSPENDED`"

    Design: Corner/validations/suspended_org_event_create_blocked
    """
    scn = setup_org_with_no_shows(3)
    org = get_org(scn.org["id"])
    assert org["standing"] == "SUSPENDED"
    assert org["no_show_count"] == 3

    response = api.create_event_reservation(
        {
            "room_id": scn.room["id"],
            "title": "N4",
            "expected_attendance": 5,
            "start_at": "2026-09-21T14:00:00Z",
            "end_at": "2026-09-21T15:00:00Z",
            "expected_room_version": get_room(scn.room["id"])["version"],
        },
        make_org_requester_headers(scn.org["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ORG_SUSPENDED)

    # No new event persisted: the system holds exactly the three no-show events.
    data, meta = validate_paginated(api.list_event_reservations(SCHEDULER))
    assert meta["total_count"] == 3


def test_probation_confirm_requires_fully_covered_provisional_invoice(api):
    """PRD §3.4: "an organization on `PROBATION` may confirm only when its
    provisional invoice is fully covered — `paid_cents` plus `waived_cents`
    reaching the invoice's `total_cents` — otherwise `ERR_PREPAYMENT_REQUIRED`."
    PRD §3.6: "Prepayment of a `PROVISIONAL` invoice is allowed — this is how a
    probationary organization satisfies its confirmation gate"

    Design: Corner/validations/probation_confirm_requires_full_prepayment
    """
    scn = setup_org_with_no_shows(
        2,
        room_overrides={
            "internal_hourly_rate_cents": 1000,
            "student_hourly_rate_cents": 500,
            "external_hourly_rate_cents": 2000,
        },
    )
    assert get_org(scn.org["id"])["standing"] == "PROBATION"

    set_clock("2026-09-11T00:00:00Z")
    event = create_event(
        scn.org, scn.room["id"],
        start_at="2026-09-21T14:00:00Z", end_at="2026-09-21T15:00:00Z",
        expected_attendance=5, title="New",
    )
    approve_event(event["id"])
    invoice = find_invoice_for_event(event["id"])
    assert invoice["total_cents"] == 1000, "one off-peak hour at 1000 cents"

    response = api.confirm_event(event["id"], org_headers(scn.org))
    validate_error(response, ApiErrorId.ERR_PREPAYMENT_REQUIRED)
    assert get_event(event["id"])["status"] == "APPROVED"

    paid = pay_invoice(invoice["id"], 1000, scn.org)
    assert paid["status"] == "PAID", "exactly total_cents paid flips to PAID"

    confirmed = validate_success(api.confirm_event(event["id"], org_headers(scn.org)))
    assert confirmed["status"] == "CONFIRMED"
