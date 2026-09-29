"""Cross-entity gates: the favourable report and fiscal note routing."""

from test_helpers import (
    ApiErrorId,
    STANDARD_COST_LINES,
    add_agency,
    api_client,
    assert_committee_referral,
    assert_instant,
    certify_note,
    create_fiscal_note_request_payload,
    get_success_data,
    read_agency,
    read_bill,
    read_committee,
    read_referral,
    read_session,
    refer_bill,
    report_payload,
    route_fiscal_note,
    setup_introduced_bill,
    setup_submitted_note,
    setup_world,
    validate_error,
    validate_success,
)


def _severance_bill_with_submitted_note():
    """A referred severance-tax bill whose note is submitted but not certified."""
    world = setup_world(
        with_committee=True,
        with_agency=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Appropriations",
            "is_fiscal_committee": True,
            "max_concurrent_referrals": 2,
        },
        agency_overrides={
            "name": "Dept of Revenue",
            "agency_code": "DOR",
            "status": "ACTIVE",
            "max_open_requests": 3,
        },
    )
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=4,
        requested_sections_count=4,
        subject="Severance tax rebasing",
        summary="Rebase the severance tax schedule.",
        target_code_chapter="Title 39",
        appropriation_requested_cents=12_000_000,
    )
    referral = refer_bill(world, bill)
    note = setup_submitted_note(world, bill, lines=STANDARD_COST_LINES)
    return world, bill, referral, note


def test_favourable_report_is_refused_while_the_bill_still_awaits_a_certified_note():
    """PRD: "The favourable branch is the gated one. It requires the bill's
    `fiscal_status` to be `NOT_REQUIRED` or `NOTE_COMPLETE`; a bill sitting at
    `NOTE_PENDING` or `NOTE_STALE` cannot be reported favourably until a note is
    certified, and the refusal is `ERR_FISCAL_NOTE_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/favorable_committee_report_blocked_until_the_bills_fiscal_status_reaches_note_complete
    """
    world, bill, referral, _note = _severance_bill_with_submitted_note()
    assert_instant(referral["report_deadline_utc"], "2026-10-12T16:00:00Z")

    response = api_client.report_referral(
        referral["id"], report_payload("FAVORABLE"), world["clerk_headers"]
    )

    validate_error(response, ApiErrorId.ERR_FISCAL_NOTE_REQUIRED.value, 409)

    held = read_referral(world, referral["id"])
    assert held["status"] == "IN_COMMITTEE"
    assert held["reported_utc"] is None
    assert read_committee(world, world["committee"]["id"])["active_referral_count"] == 1

    unchanged = read_bill(world, bill["id"])
    assert unchanged["legislative_status"] == "REFERRED"
    assert unchanged["fiscal_status"] == "NOTE_PENDING"


def test_certifying_the_note_unblocks_the_same_favourable_report():
    """PRD: "On success the referral moves from `IN_COMMITTEE` to
    `REPORTED_FAVORABLE`, `reported_utc` is stamped with the logical clock, and
    the committee's `active_referral_count` drops by one." and "If — and only if
    — no referral of that bill remains `IN_COMMITTEE`, the bill advances from
    `REFERRED` to `REPORTED`; a bill with a second committee still holding it
    stays in `REFERRED`."

    Design: Difficulty/cross_entity_state_dependency/favorable_committee_report_blocked_until_the_bills_fiscal_status_reaches_note_complete
    """
    world, bill, referral, note = _severance_bill_with_submitted_note()
    api_client.report_referral(
        referral["id"], report_payload("FAVORABLE"), world["clerk_headers"]
    )

    certified = certify_note(world, note)
    assert certified["certified_total_cents"] == 26_568_000
    priced = read_bill(world, bill["id"])
    assert priced["fiscal_status"] == "NOTE_COMPLETE"
    assert read_session(world)["fiscal_posture"] == "NORMAL"

    response = api_client.report_referral(
        referral["id"], report_payload("FAVORABLE"), world["clerk_headers"]
    )

    reported = validate_success(response, 200)
    assert_committee_referral(reported)
    assert reported["status"] == "REPORTED_FAVORABLE"
    assert_instant(reported["reported_utc"], "2026-09-01T00:00:00Z")
    assert read_bill(world, bill["id"])["legislative_status"] == "REPORTED"
    assert read_committee(world, world["committee"]["id"])["active_referral_count"] == 0


def _three_agencies_and_two_bills():
    """One inactive agency, one already at capacity, one with room to spare."""
    world = setup_world()
    obsolete = add_agency(
        world,
        name="Dept of Obsolete Programs",
        agency_code="DOP",
        status="INACTIVE",
        max_open_requests=3,
    )
    corrections = add_agency(
        world,
        name="Dept of Corrections",
        agency_code="DOC",
        status="ACTIVE",
        max_open_requests=1,
    )
    revenue = add_agency(
        world,
        name="Dept of Revenue",
        agency_code="DOR",
        status="ACTIVE",
        max_open_requests=3,
    )
    _request_x, bill_x = setup_introduced_bill(
        world,
        affected_sections_count=4,
        requested_sections_count=4,
        subject="Sentencing credit reform",
        summary="Adjust earned-time credits.",
        target_code_chapter="Title 17",
        appropriation_requested_cents=8_000_000,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-04T00:00:00Z",
    )
    _request_y, bill_y = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Visitation scheduling",
        summary="Standardize visitation scheduling.",
        target_code_chapter="Title 17",
        appropriation_requested_cents=500_000,
        engagement_start_utc="2026-09-05T00:00:00Z",
        engagement_end_utc="2026-09-07T00:00:00Z",
    )
    # This fills the corrections department's single open-request slot.
    route_fiscal_note(world, bill_y, agency=corrections)
    return world, bill_x, obsolete, corrections, revenue


def test_routing_a_fiscal_note_to_an_inactive_agency_is_refused():
    """PRD: "The agency's `status` must be `ACTIVE`, or the call is
    `ERR_AGENCY_INACTIVE`." and "Routing is admitted only while the bill's
    `fiscal_status` is `NOTE_PENDING` or `NOTE_STALE` — a bill at `NOT_REQUIRED`
    or `NOTE_COMPLETE` has nothing to price, and the attempt is
    `ERR_INVALID_BILL_STATE`, as is any routing against a bill whose
    `legislative_status` has reached `DEAD` or `TRANSMITTED`."

    Design: Difficulty/cross_entity_state_dependency/fiscal_note_routing_refused_by_agency_status_then_by_agency_open_request_capacity
    """
    world, bill_x, obsolete, _corrections, _revenue = _three_agencies_and_two_bills()

    response = api_client.create_fiscal_note_request(
        bill_x["id"],
        create_fiscal_note_request_payload(obsolete["id"]),
        world["fiscal_officer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_AGENCY_INACTIVE.value, 409)
    assert read_agency(world, obsolete["id"])["open_request_count"] == 0
    assert read_bill(world, bill_x["id"])["fiscal_status"] == "NOTE_PENDING"


def test_routing_is_refused_by_open_request_capacity_then_accepted_by_a_free_agency():
    """PRD: "The agency's `open_request_count` — the number of its notes currently
    in `ROUTED`, `SUBMITTED` or `RETURNED_FOR_REVISION` — must be strictly below
    its `max_open_requests`, or the call is `ERR_AGENCY_CAPACITY_EXCEEDED`." and
    "The total grant in whole days is added to `routed_utc` to produce `due_utc`,
    preserving `routed_utc`'s time-of-day exactly."

    Design: Difficulty/cross_entity_state_dependency/fiscal_note_routing_refused_by_agency_status_then_by_agency_open_request_capacity
    """
    world, bill_x, _obsolete, corrections, revenue = _three_agencies_and_two_bills()

    refused = api_client.create_fiscal_note_request(
        bill_x["id"],
        create_fiscal_note_request_payload(corrections["id"]),
        world["fiscal_officer_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_AGENCY_CAPACITY_EXCEEDED.value, 409)

    accepted = api_client.create_fiscal_note_request(
        bill_x["id"],
        create_fiscal_note_request_payload(revenue["id"]),
        world["fiscal_officer_headers"],
    )
    note = validate_success(accepted, 201)

    assert note["status"] == "ROUTED"
    assert note["agency_id"] == revenue["id"]
    assert note["revision_round"] == 0
    assert_instant(note["routed_utc"], "2026-09-01T00:00:00Z")
    assert_instant(note["due_utc"], "2026-09-22T00:00:00Z")

    assert read_agency(world, corrections["id"])["open_request_count"] == 1
    assert read_agency(world, revenue["id"])["open_request_count"] == 1
    assert read_bill(world, bill_x["id"])["fiscal_status"] == "NOTE_PENDING"

    listing = get_success_data(
        api_client.list_fiscal_note_requests(world["fiscal_officer_headers"])
    )
    for_bill_x = [row for row in listing if row["bill_id"] == bill_x["id"]]
    assert len(for_bill_x) == 1
