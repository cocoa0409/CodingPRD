"""Endpoints: round trips, filter narrowing, action side effects and link guards."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    CLERK,
    add_member,
    api_client,
    assert_bill,
    assert_committee,
    assert_committee_referral,
    assert_enrolled_bill,
    assert_instant,
    assert_technical_correction,
    assign_request,
    certify_draft,
    companion_payload,
    complete_research,
    create_committee_payload,
    create_drafting_request_payload,
    create_technical_correction_payload,
    get_success_data,
    introduce_bill,
    read_bill,
    read_committee,
    read_enrolled_bill,
    read_session,
    refer_bill,
    report_payload,
    set_clock,
    setup_enrolled_bill,
    setup_introduced_bill,
    setup_world,
    signature_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The committee fields a client supplies or reads back; identifiers, timestamps
# and the optimistic-concurrency counter are excluded on purpose.
COMMITTEE_ROUND_TRIP_FIELDS = (
    "id",
    "session_id",
    "chamber",
    "name",
    "is_fiscal_committee",
    "max_concurrent_referrals",
    "active_referral_count",
)


def _bill_for_member(world, member_headers, **overrides):
    """Walk a request filed by an arbitrary member all the way to an introduced bill."""
    engagement = {
        "engagement_start_utc": overrides.pop("engagement_start_utc", "2026-09-02T00:00:00Z"),
        "engagement_end_utc": overrides.pop("engagement_end_utc", "2026-09-03T00:00:00Z"),
    }
    sections = overrides.get("requested_sections_count", 3)
    request = get_success_data(
        api_client.create_drafting_request(
            create_drafting_request_payload(world["session"]["id"], **overrides),
            member_headers,
        )
    )
    assign_request(world, request, **engagement)
    complete_research(world, request, affected_sections_count=sections)
    certify_draft(world, request)
    return request, introduce_bill(world, request)


def test_a_committee_round_trips_through_both_routes_and_every_filter_narrows():
    """PRD: "Committees are created beneath their session, so a committee's
    `session_id` comes from the path and is never read from the body." and "Either a
    `Clerk` or a `PlatformAdmin` may create one, supplying its `chamber` (`HOUSE` or
    `SENATE`), its `name`, an optional `is_fiscal_committee` flag defaulting to false,
    and an optional `max_concurrent_referrals` defaulting to 2 and required to be at
    least 1." and "Filters are additive: supplying two filters narrows to rows matching
    both, and an unsupplied filter imposes no restriction." and "The
    committees-of-a-session list accepts `chamber` and `is_fiscal_committee`."

    Design: Corner/endpoints/committee_create_read_and_sub_resource_list_round_trip_with_every_declared_filter
    """
    world = setup_world()
    session_id = world["session"]["id"]

    house_fiscal = validate_success(
        api_client.create_committee(
            session_id,
            create_committee_payload(
                chamber="HOUSE",
                name="House Appropriations",
                is_fiscal_committee=True,
                max_concurrent_referrals=2,
            ),
            CLERK,
        ),
        201,
    )
    # The same creation route is open to the platform administrator.
    house_local = validate_success(
        api_client.create_committee(
            session_id,
            create_committee_payload(
                chamber="HOUSE",
                name="House Local Government",
                is_fiscal_committee=False,
                max_concurrent_referrals=3,
            ),
            ADMIN,
        ),
        201,
    )
    senate_finance = validate_success(
        api_client.create_committee(
            session_id,
            create_committee_payload(
                chamber="SENATE",
                name="Senate Finance",
                is_fiscal_committee=True,
                max_concurrent_referrals=1,
            ),
            CLERK,
        ),
        201,
    )
    for created in (house_fiscal, house_local, senate_finance):
        assert_committee(created)
        assert created["active_referral_count"] == 0
        assert created["session_id"] == session_id

    flat_read = validate_success(
        api_client.get_committee(house_local["id"], world["drafter_headers"]), 200
    )
    assert flat_read["is_fiscal_committee"] is False
    assert flat_read["max_concurrent_referrals"] == 3
    for field in COMMITTEE_ROUND_TRIP_FIELDS:
        assert flat_read[field] == house_local[field], (
            f"the flat read disagrees with the creation response on {field}"
        )

    by_chamber, _meta = validate_paginated(
        api_client.list_session_committees(session_id, CLERK, params={"chamber": "HOUSE"})
    )
    assert sorted(row["id"] for row in by_chamber) == sorted(
        [house_fiscal["id"], house_local["id"]]
    )

    by_designation, designation_meta = validate_paginated(
        api_client.list_session_committees(
            session_id, CLERK, params={"is_fiscal_committee": True}
        )
    )
    assert designation_meta["total_count"] == 2
    assert sorted(row["id"] for row in by_designation) == sorted(
        [house_fiscal["id"], senate_finance["id"]]
    )

    both, both_meta = validate_paginated(
        api_client.list_session_committees(
            session_id,
            CLERK,
            params={
                "chamber": "HOUSE",
                "is_fiscal_committee": True,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert both_meta["total_count"] == 1
    assert both_meta["has_more"] is False
    assert [row["id"] for row in both] == [house_fiscal["id"]]


def test_the_bill_report_narrows_by_every_declared_filter_and_returns_an_empty_page():
    """PRD: "The bill list — which doubles as the bill status report — accepts
    `session_id`, `drafting_request_id`, `sponsor_member_id`, `companion_bill_id`,
    `chamber`, `legislative_status`, `fiscal_status` and `priority_bill`." and "All
    four pagination fields — `limit`, `offset`, `total_count` and `has_more` — appear
    in the `meta` object of every list response, where `total_count` is the number of
    rows matching the filter before the page window is applied and `has_more` is true
    when rows remain beyond the current window."

    Design: Corner/endpoints/bill_list_filters_narrow_independently_by_chamber_status_fiscal_status_and_sponsor
    """
    world = setup_world()
    session_id = world["session"]["id"]
    _senator, senator_headers = add_member(
        world, full_name="Sen Beta", chamber="SENATE", party="IND", priority_slots_total=2
    )

    request_one, house_bill = setup_introduced_bill(
        world,
        affected_sections_count=3,
        requested_sections_count=3,
        subject="Open meetings notice reform",
        summary="Standardize open meetings notice.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-03T00:00:00Z",
    )
    _request_two, senate_bill = _bill_for_member(
        world,
        senator_headers,
        subject="Severance tax rebasing",
        summary="Rebase the severance tax schedule.",
        target_code_chapter="Title 39",
        appropriation_requested_cents=6_000_000,
        engagement_start_utc="2026-09-04T00:00:00Z",
        engagement_end_utc="2026-09-05T00:00:00Z",
    )
    assert_bill(house_bill)
    assert_bill(senate_bill)
    assert house_bill["fiscal_status"] == "NOT_REQUIRED"
    assert senate_bill["fiscal_status"] == "NOTE_PENDING"

    def page(params):
        params = dict(params)
        params["session_id"] = session_id
        return validate_paginated(api_client.list_bills(CLERK, params=params))

    by_chamber, chamber_meta = page({"chamber": "HOUSE"})
    assert chamber_meta["total_count"] == 1
    assert [row["id"] for row in by_chamber] == [house_bill["id"]]
    assert by_chamber[0]["bill_number"] == "HB 1"

    by_fiscal, fiscal_meta = validate_paginated(
        api_client.list_bills(
            world["fiscal_officer_headers"],
            params={"session_id": session_id, "fiscal_status": "NOTE_PENDING"},
        )
    )
    assert fiscal_meta["total_count"] == 1
    assert [row["id"] for row in by_fiscal] == [senate_bill["id"]]
    assert by_fiscal[0]["bill_number"] == "SB 1"

    by_sponsor, sponsor_meta = page({"sponsor_member_id": senate_bill["sponsor_member_id"]})
    assert sponsor_meta["total_count"] == 1
    assert [row["id"] for row in by_sponsor] == [senate_bill["id"]]

    shared, shared_meta = page({"legislative_status": "INTRODUCED"})
    assert shared_meta["total_count"] == 2
    assert sorted(row["id"] for row in shared) == sorted(
        [house_bill["id"], senate_bill["id"]]
    )

    # The one-to-one conversion edge is queryable from the request side.
    by_request, request_meta = page({"drafting_request_id": request_one["id"]})
    assert request_meta["total_count"] == 1
    assert [row["id"] for row in by_request] == [house_bill["id"]]

    empty, empty_meta = page({"chamber": "SENATE", "legislative_status": "REPORTED"})
    assert empty == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False


def _referred_house_bill():
    """A note-free HOUSE bill sitting in one fiscal committee, clock at hearing time."""
    world = setup_world(
        with_committee=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Appropriations",
            "is_fiscal_committee": True,
            "max_concurrent_referrals": 2,
        },
    )
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Records retention schedule",
        summary="Modernize the records retention schedule.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
    )
    referral = refer_bill(world, bill)
    set_clock("2026-10-06T00:00:00Z")
    return world, bill, referral


def test_one_favourable_report_moves_the_referral_the_bill_and_the_committee_counter():
    """PRD: "On success the referral moves from `IN_COMMITTEE` to
    `REPORTED_FAVORABLE`, `reported_utc` is stamped with the logical clock, and the
    committee's `active_referral_count` drops by one." and "If — and only if — no
    referral of that bill remains `IN_COMMITTEE`, the bill advances from `REFERRED` to
    `REPORTED`; a bill with a second committee still holding it stays in `REFERRED`."
    and "The bill's `version` rises by one in either branch." and "`fiscal_status` runs
    among `NOT_REQUIRED`, `NOTE_PENDING`, `NOTE_STALE` and `NOTE_COMPLETE` and has no
    terminal value at all — a bill can cycle through the fiscal dimension repeatedly
    while its legislative dimension stands still, and vice versa."

    Design: Corner/endpoints/favorable_report_action_applies_every_declared_side_effect_in_one_call
    """
    world, bill, referral = _referred_house_bill()
    committee_id = world["committee"]["id"]
    assert_instant(referral["report_deadline_utc"], "2026-10-12T16:00:00Z")
    assert read_committee(world, committee_id)["active_referral_count"] == 1
    before = read_bill(world, bill["id"])
    assert before["legislative_status"] == "REFERRED"

    reported = validate_success(
        api_client.report_referral(
            referral["id"], report_payload("FAVORABLE"), world["clerk_headers"]
        ),
        200,
    )

    assert_committee_referral(reported)
    assert reported["status"] == "REPORTED_FAVORABLE"
    assert_instant(reported["reported_utc"], "2026-10-06T00:00:00Z")

    after = read_bill(world, bill["id"])
    assert after["legislative_status"] == "REPORTED"
    assert after["version"] == before["version"] + 1
    # Nothing in the referral row shows this, so it is read from the committee.
    assert read_committee(world, committee_id)["active_referral_count"] == 0

    assert after["fiscal_status"] == "NOT_REQUIRED"
    assert read_session(world)["certified_fiscal_total_cents"] == 0


def test_passage_is_refused_from_referred_admitted_once_and_never_twice():
    """PRD: "Passage moves a reported bill through its chamber and takes no input
    fields at all." and "The bill's `legislative_status` must be `REPORTED`." and "On
    success the bill moves from `REPORTED` to `PASSED_CHAMBER` and its `version` rises
    by one."

    Design: Corner/endpoints/pass_action_is_refused_from_referred_and_admitted_only_from_reported
    """
    world, bill, referral = _referred_house_bill()
    referred_version = read_bill(world, bill["id"])["version"]

    too_early = api_client.pass_bill(bill["id"], world["clerk_headers"])
    validate_error(too_early, ApiErrorId.ERR_INVALID_BILL_STATE.value, 409)
    still_referred = read_bill(world, bill["id"])
    assert still_referred["legislative_status"] == "REFERRED"
    assert still_referred["version"] == referred_version

    api_client.report_referral(
        referral["id"], report_payload("FAVORABLE"), world["clerk_headers"]
    )
    reported_version = read_bill(world, bill["id"])["version"]

    passed = validate_success(api_client.pass_bill(bill["id"], world["clerk_headers"]), 200)
    assert_bill(passed)
    assert passed["legislative_status"] == "PASSED_CHAMBER"
    assert passed["version"] == reported_version + 1

    again = api_client.pass_bill(bill["id"], world["clerk_headers"])
    validate_error(again, ApiErrorId.ERR_INVALID_BILL_STATE.value, 409)
    # The refused second call is a real guard, not an idempotent no-op: it writes
    # nothing at all, so the version stands exactly where the first pass left it.
    final = read_bill(world, bill["id"])
    assert final["legislative_status"] == "PASSED_CHAMBER"
    assert final["version"] == reported_version + 1


def test_the_companion_link_is_written_on_both_rows_and_four_guards_refuse_the_rest():
    """PRD: "Companion tracking links a measure to its opposite-chamber twin." and "A
    `Clerk` supplies `companion_bill_id`, and the link is written reciprocally: this
    bill's `companion_bill_id` is set to the named bill and the named bill's
    `companion_bill_id` is set back to this one, with the `version` of **both** rows
    rising by one." and "Four refusals guard the link, each carrying HTTP 422: naming
    the path bill itself is `ERR_COMPANION_SELF_LINK`; naming a bill in the same
    `chamber` is `ERR_COMPANION_CHAMBER_INVALID`; naming a bill belonging to a
    different session is `ERR_COMPANION_SESSION_MISMATCH`; and naming a bill when
    either side already carries a `companion_bill_id` is
    `ERR_COMPANION_ALREADY_LINKED`."

    Design: Corner/endpoints/companion_link_pairs_two_chambers_once_and_rejects_every_malformed_pairing
    """
    first_world = setup_world(session_overrides={"name": "2027 Regular Session"})
    first_session_id = first_world["session"]["id"]
    _senator, senator_headers = add_member(
        first_world,
        full_name="Sen Beta",
        chamber="SENATE",
        party="IND",
        priority_slots_total=2,
    )
    _request_one, house_first = _bill_for_member(
        first_world,
        first_world["member_headers"],
        subject="Open meetings notice reform",
        summary="Standardize open meetings notice.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-03T00:00:00Z",
    )
    _request_two, senate_first = _bill_for_member(
        first_world,
        senator_headers,
        subject="Open records fee schedule",
        summary="Set a uniform records fee schedule.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-04T00:00:00Z",
        engagement_end_utc="2026-09-05T00:00:00Z",
    )
    _request_three, house_spare = _bill_for_member(
        first_world,
        first_world["member_headers"],
        subject="Notary commission renewal",
        summary="Simplify notary commission renewal.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-06T00:00:00Z",
        engagement_end_utc="2026-09-07T00:00:00Z",
    )
    _request_four, house_other = _bill_for_member(
        first_world,
        first_world["member_headers"],
        subject="Public notice consolidation",
        summary="Consolidate statutory public notices.",
        target_code_chapter="Title 24",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-08T00:00:00Z",
        engagement_end_utc="2026-09-09T00:00:00Z",
    )

    # A second convened session, whose only bill is the cross-session partner.
    second_world = setup_world(
        session_overrides={"name": "2027 Special Session"},
        member_overrides={
            "full_name": "Sen Gamma",
            "chamber": "SENATE",
            "party": "IND",
            "priority_slots_total": 2,
        },
    )
    _request_five, senate_other_session = _bill_for_member(
        second_world,
        second_world["member_headers"],
        subject="Emergency appropriation cleanup",
        summary="Clean up the emergency appropriation language.",
        target_code_chapter="Title 41",
        appropriation_requested_cents=0,
        engagement_start_utc="2026-09-10T00:00:00Z",
        engagement_end_utc="2026-09-11T00:00:00Z",
    )
    assert senate_other_session["session_id"] != first_session_id

    linked = validate_success(
        api_client.link_companion(
            house_first["id"], companion_payload(senate_first["id"]), CLERK
        ),
        200,
    )
    assert linked["id"] == house_first["id"]
    assert linked["companion_bill_id"] == senate_first["id"]
    # The one call wrote the far side of the edge too.
    assert (
        read_bill(first_world, senate_first["id"])["companion_bill_id"] == house_first["id"]
    )

    reverse, reverse_meta = validate_paginated(
        api_client.list_bills(
            CLERK,
            params={"session_id": first_session_id, "companion_bill_id": house_first["id"]},
        )
    )
    assert reverse_meta["total_count"] == 1
    assert [row["id"] for row in reverse] == [senate_first["id"]]

    self_link = api_client.link_companion(
        house_spare["id"], companion_payload(house_spare["id"]), CLERK
    )
    validate_error(self_link, ApiErrorId.ERR_COMPANION_SELF_LINK.value, 422)

    same_chamber = api_client.link_companion(
        house_spare["id"], companion_payload(house_other["id"]), CLERK
    )
    validate_error(same_chamber, ApiErrorId.ERR_COMPANION_CHAMBER_INVALID.value, 422)

    other_session = api_client.link_companion(
        house_other["id"], companion_payload(senate_other_session["id"]), CLERK
    )
    validate_error(other_session, ApiErrorId.ERR_COMPANION_SESSION_MISMATCH.value, 422)

    already_paired = api_client.link_companion(
        house_spare["id"], companion_payload(senate_first["id"]), CLERK
    )
    validate_error(already_paired, ApiErrorId.ERR_COMPANION_ALREADY_LINKED.value, 422)

    assert read_bill(first_world, house_spare["id"])["companion_bill_id"] is None
    assert read_bill(first_world, house_other["id"])["companion_bill_id"] is None
    assert (
        read_bill(second_world, senate_other_session["id"])["companion_bill_id"] is None
    )


def test_transmittal_waits_for_the_signature_order_and_for_every_correction_to_clear():
    """PRD: "The supplied `signature_role` must equal the enrollment's current
    `expected_next_signature`, or the call is `ERR_SIGNATURE_OUT_OF_ORDER`." and "From
    `PREPARED`, presenting the origin chamber's presiding officer moves the enrollment
    to `ORIGIN_SIGNED`, stamps `origin_signed_utc` from the logical clock, and advances
    `expected_next_signature` to the other presiding officer — `SENATE_PRESIDENT` for a
    house bill, `SPEAKER` for a senate bill." and "`is_substantive` must be false: a
    correction declaring itself substantive is refused outright with
    `ERR_SUBSTANTIVE_CORRECTION_FORBIDDEN`, because enrolled text may only be corrected
    non-substantively." and "That final step has one extra gate: transmittal is refused
    while `open_corrections_count` is greater than 0, with `ERR_UNAPPLIED_CORRECTIONS`
    — a bill may not go to the governor with a proposed correction still hanging." and
    "From `SECOND_SIGNED`, presenting `GOVERNOR_TRANSMITTAL` moves the enrollment to
    `TRANSMITTED`, stamps `transmitted_utc`, sets `expected_next_signature` to `NONE`,
    and carries the bill from `ENROLLED` to `TRANSMITTED`."

    Design: Corner/endpoints/transmittal_is_admitted_only_after_the_signature_chain_and_every_open_correction_clear
    """
    world = setup_world(
        with_committee=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Appropriations",
            "is_fiscal_committee": True,
            "max_concurrent_referrals": 2,
        },
    )
    bill, _referral, enrollment = setup_enrolled_bill(
        world,
        appropriation_requested_cents=0,
        affected_sections_count=2,
        requested_sections_count=2,
        subject="Records retention schedule",
        summary="Modernize the records retention schedule.",
        target_code_chapter="Title 24",
    )
    assert_enrolled_bill(enrollment)
    assert enrollment["status"] == "PREPARED"
    assert enrollment["origin_signature_role"] == "SPEAKER"
    assert enrollment["expected_next_signature"] == "SPEAKER"

    out_of_order = api_client.create_signature(
        enrollment["id"], signature_payload("SENATE_PRESIDENT"), world["clerk_headers"]
    )
    validate_error(out_of_order, ApiErrorId.ERR_SIGNATURE_OUT_OF_ORDER.value, 409)
    assert read_enrolled_bill(world, enrollment["id"])["status"] == "PREPARED"

    origin_signed = validate_success(
        api_client.create_signature(
            enrollment["id"], signature_payload("SPEAKER"), world["clerk_headers"]
        ),
        200,
    )
    assert origin_signed["status"] == "ORIGIN_SIGNED"
    assert origin_signed["origin_signed_utc"] is not None
    assert origin_signed["expected_next_signature"] == "SENATE_PRESIDENT"

    second_signed = validate_success(
        api_client.create_signature(
            enrollment["id"], signature_payload("SENATE_PRESIDENT"), world["clerk_headers"]
        ),
        200,
    )
    assert second_signed["status"] == "SECOND_SIGNED"
    assert second_signed["second_signed_utc"] is not None
    assert second_signed["expected_next_signature"] == "GOVERNOR_TRANSMITTAL"

    signed_version = read_enrolled_bill(world, enrollment["id"])["version"]

    substantive = api_client.create_technical_correction(
        enrollment["id"],
        create_technical_correction_payload(
            signed_version,
            correction_type="TYPO",
            description="Rewrite the effective date clause substantively.",
            is_substantive=True,
        ),
        world["drafter_headers"],
    )
    validate_error(
        substantive, ApiErrorId.ERR_SUBSTANTIVE_CORRECTION_FORBIDDEN.value, 422
    )
    untouched = read_enrolled_bill(world, enrollment["id"])
    assert untouched["open_corrections_count"] == 0
    assert untouched["version"] == signed_version

    correction = validate_success(
        api_client.create_technical_correction(
            enrollment["id"],
            create_technical_correction_payload(
                signed_version,
                correction_type="CITATION",
                description="Correct an internal cross-reference.",
                is_substantive=False,
            ),
            world["drafter_headers"],
        ),
        201,
    )
    assert_technical_correction(correction)
    assert correction["status"] == "PROPOSED"
    assert correction["proposed_by_drafter_id"] == world["drafter"]["id"]
    assert correction["applied_by_drafter_id"] is None
    assert read_enrolled_bill(world, enrollment["id"])["open_corrections_count"] == 1

    blocked = api_client.create_signature(
        enrollment["id"], signature_payload("GOVERNOR_TRANSMITTAL"), world["clerk_headers"]
    )
    validate_error(blocked, ApiErrorId.ERR_UNAPPLIED_CORRECTIONS.value, 409)
    assert read_enrolled_bill(world, enrollment["id"])["status"] == "SECOND_SIGNED"

    # The proposer may not clear its own correction, so the senior counsel does.
    applied = validate_success(
        api_client.apply_technical_correction(correction["id"], world["counsel_headers"]),
        200,
    )
    assert applied["status"] == "APPLIED"
    assert applied["applied_by_drafter_id"] == world["counsel"]["id"]
    cleared = read_enrolled_bill(world, enrollment["id"])
    assert cleared["corrections_applied_count"] == 1
    assert cleared["open_corrections_count"] == 0

    transmitted = validate_success(
        api_client.create_signature(
            enrollment["id"],
            signature_payload("GOVERNOR_TRANSMITTAL"),
            world["clerk_headers"],
        ),
        200,
    )
    assert transmitted["status"] == "TRANSMITTED"
    assert transmitted["transmitted_utc"] is not None
    assert transmitted["expected_next_signature"] == "NONE"
    assert read_bill(world, bill["id"])["legislative_status"] == "TRANSMITTED"
