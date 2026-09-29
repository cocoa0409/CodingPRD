"""Cross-cutting layers: the three concurrency tokens and derived counters."""

from test_helpers import (
    api_client,
    ApiErrorId,
    apply_correction,
    assert_amendment,
    assert_cost_estimate,
    assert_technical_correction,
    create_amendment_payload,
    create_cost_estimate_payload,
    create_technical_correction_payload,
    enroll_bill,
    NON_EXISTENT_UUID,
    pass_bill,
    propose_correction,
    read_bill,
    read_committee,
    read_correction,
    read_enrolled_bill,
    read_note,
    read_referral,
    read_session,
    refer_bill,
    report_referral,
    return_note,
    route_fiscal_note,
    set_clock,
    setup_enrolled_bill,
    setup_introduced_bill,
    setup_world,
    submit_note,
    validate_error,
    validate_paginated,
    validate_success,
)

STALE_BILL = ApiErrorId.ERR_STALE_BILL_VERSION.value
STALE_NOTE = ApiErrorId.ERR_STALE_FISCAL_NOTE_VERSION.value
STALE_ENROLLMENT = ApiErrorId.ERR_STALE_ENROLLMENT_VERSION.value


def _committee_amendment_payload(bill_id, referral_id, version, summary, start, due):
    """A COMMITTEE-stage amendment differing from its siblings only by window."""
    return create_amendment_payload(
        version,
        bill_id,
        stage="COMMITTEE",
        committee_referral_id=referral_id,
        summary=summary,
        fiscal_impact_delta_cents=0,
        drafting_start_utc=start,
        drafting_due_utc=due,
    )


def test_a_replayed_expected_bill_version_is_refused_until_the_member_re_reads_the_bill():
    """PRD: "Creating an amendment requires `expected_bill_version` in the body,
    carrying the client's last observed `version` of the target bill." and "An
    amendment is drafted against a specific version of the bill's text; if any
    other writer has advanced that bill's `version` since the requesting member
    read it — another amendment filed, drafted, adopted or rescinded, a referral
    added, a companion linked — the requester's view of the measure is stale and
    the creation is refused with `ERR_STALE_BILL_VERSION` (HTTP 412) rather than
    being silently attached to text the requester never saw." and "Because a bill
    may legitimately carry many amendments, nothing but this version comparison
    distinguishes the accepted case from the refused one." and "**Body reference
    existence.** Every identifier carried in the body resolves — otherwise the
    matching not-found identifier."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_bill_version_blocks_a_second_amendment_until_the_requester_re_reads_the_bill
    """
    world = setup_world(with_committee=True)
    _request, bill = setup_introduced_bill(world, affected_sections_count=3)
    referral = refer_bill(world, bill)
    assert referral["status"] == "IN_COMMITTEE"

    b1v1 = read_bill(world, bill["id"])["version"]

    first = api_client.create_amendment(
        _committee_amendment_payload(
            bill["id"],
            referral["id"],
            b1v1,
            "First amendment, filed against a fresh view.",
            "2026-09-01T13:00:00Z",
            "2026-09-01T15:00:00Z",
        ),
        world["member_headers"],
    )
    accepted = validate_success(first, 201)
    assert_amendment(accepted)
    assert accepted["status"] == "REQUESTED"
    assert accepted["stage"] == "COMMITTEE"
    assert accepted["committee_referral_id"] == referral["id"]

    # Byte-identical except for the summary and the window: only the token is wrong.
    replay = api_client.create_amendment(
        _committee_amendment_payload(
            bill["id"],
            referral["id"],
            b1v1,
            "Second amendment, filed against the same stale view.",
            "2026-09-01T16:00:00Z",
            "2026-09-01T18:00:00Z",
        ),
        world["member_headers"],
    )
    validate_error(replay, STALE_BILL, 412)

    b1v2 = read_bill(world, bill["id"])["version"]
    # The accepted creation is itself what invalidated the replayed token.
    assert b1v2 == b1v1 + 1

    refiled = api_client.create_amendment(
        _committee_amendment_payload(
            bill["id"],
            referral["id"],
            b1v2,
            "Second amendment, refiled after re-reading the bill.",
            "2026-09-01T16:00:00Z",
            "2026-09-01T18:00:00Z",
        ),
        world["member_headers"],
    )
    second = validate_success(refiled, 201)
    assert second["status"] == "REQUESTED"
    assert second["id"] != accepted["id"]

    b1v3 = read_bill(world, bill["id"])["version"]
    # One increment per successful write, none at all for the refusal.
    assert b1v3 == b1v2 + 1

    rows, meta = validate_paginated(
        api_client.list_amendments(
            world["clerk_headers"], {"bill_id": bill["id"], "limit": 20, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {accepted["id"], second["id"]}

    # A stale token against a body reference that does not resolve answers 404 first.
    both_wrong = api_client.create_amendment(
        _committee_amendment_payload(
            NON_EXISTENT_UUID,
            referral["id"],
            b1v1,
            "Stale token against a bill that does not exist.",
            "2026-09-01T19:00:00Z",
            "2026-09-01T20:00:00Z",
        ),
        world["member_headers"],
    )
    validate_error(both_wrong, ApiErrorId.ERR_BILL_NOT_FOUND.value, 404)


def _round_line(version, fiscal_year, operating_cost_cents, assumption_note):
    """One BASELINE line of the round the analyst believes is current."""
    return create_cost_estimate_payload(
        version,
        fiscal_year=fiscal_year,
        scenario="BASELINE",
        personnel_cost_cents=5_000_000 if fiscal_year == 2027 else 3_000_000,
        operating_cost_cents=operating_cost_cents,
        one_time_cost_cents=0,
        fte_count=1.0,
        revenue_impact_cents=0,
        assumption_note=assumption_note,
    )


def test_a_cost_line_goes_stale_on_the_analysts_own_write_and_on_the_officers_return():
    """PRD: "Appending a cost estimate line requires
    `expected_fiscal_note_request_version` in the body, carrying the client's last
    observed `version` of the fiscal note request." and "A line is computed under
    the revision round and methodology the analyst last observed; if the note's
    `version` has moved on — because a prior line was appended, because the note
    was returned for revision, or because an adopted amendment re-opened it — the
    line is refused with `ERR_STALE_FISCAL_NOTE_VERSION` (HTTP 412) instead of
    being filed under a round the analyst did not intend." and "Each accepted line
    raises the note's `version` by one, which is why an analyst filing several
    lines in a row must re-read the note between calls to refresh
    `expected_fiscal_note_request_version`." and "The note moves from `SUBMITTED`
    to `RETURNED_FOR_REVISION` and its `revision_round` rises by one, which flips
    `included_in_certification` to false on every cost estimate line of the prior
    round and drops them out of every total — the analyst must file a fresh set."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_fiscal_note_request_version_blocks_a_cost_line_and_a_return_invalidates_it_too
    """
    world = setup_world(with_agency=True)
    _request, bill = setup_introduced_bill(
        world,
        affected_sections_count=4,
        requested_sections_count=4,
        appropriation_requested_cents=12_000_000,
    )
    note = route_fiscal_note(world, bill, methodology="INCREMENTAL_COST")
    assert note["status"] == "ROUTED"
    assert note["revision_round"] == 0
    nv1 = note["version"]

    first = api_client.create_cost_estimate(
        note["id"],
        _round_line(nv1, 2027, 1_000_000, "Year one, filed against a fresh view."),
        world["analyst_headers"],
    )
    line_one = validate_success(first, 201)
    assert_cost_estimate(line_one)
    assert line_one["revision_round"] == 0
    assert line_one["included_in_certification"] is True
    # An append-only row has no concurrency token of its own to lean on.
    assert "version" not in line_one

    replay = api_client.create_cost_estimate(
        note["id"],
        _round_line(nv1, 2028, 1_000_000, "Year two, filed against the same stale view."),
        world["analyst_headers"],
    )
    validate_error(replay, STALE_NOTE, 412)

    nv2 = read_note(world, note["id"])["version"]
    assert nv2 == nv1 + 1

    refiled = api_client.create_cost_estimate(
        note["id"],
        _round_line(nv2, 2028, 1_000_000, "Year two, refiled after re-reading the note."),
        world["analyst_headers"],
    )
    line_two = validate_success(refiled, 201)
    assert line_two["revision_round"] == 0

    nv3 = read_note(world, note["id"])["version"]
    assert nv3 == nv2 + 1

    submitted = submit_note(world, note, submission_note="Round one filed.")
    assert submitted["status"] == "SUBMITTED"
    assert submitted["revision_round"] == 0

    returned = return_note(world, note, return_reason="Operating assumption understated.")
    assert returned["status"] == "RETURNED_FOR_REVISION"
    # The first return opens the round after the one the fresh note carried.
    assert returned["revision_round"] == 1

    # The analyst wrote nothing since nv3, yet somebody else moved the note.
    stale_after_return = api_client.create_cost_estimate(
        note["id"],
        _round_line(nv3, 2027, 2_000_000, "Fresh round filed against a pre-return version."),
        world["analyst_headers"],
    )
    validate_error(stale_after_return, STALE_NOTE, 412)

    nv4 = read_note(world, note["id"])["version"]
    assert nv4 > nv3

    accepted = api_client.create_cost_estimate(
        note["id"],
        _round_line(nv4, 2027, 2_000_000, "Fresh round filed against the post-return version."),
        world["analyst_headers"],
    )
    fresh_line = validate_success(accepted, 201)
    assert fresh_line["revision_round"] == 1
    assert fresh_line["included_in_certification"] is True

    current_round, meta = validate_paginated(
        api_client.list_cost_estimates(
            note["id"],
            world["analyst_headers"],
            {"revision_round": 1, "limit": 20, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert current_round[0]["id"] == fresh_line["id"]

    superseded, prior_meta = validate_paginated(
        api_client.list_cost_estimates(
            note["id"],
            world["analyst_headers"],
            {"revision_round": 0, "limit": 20, "offset": 0},
        )
    )
    assert prior_meta["total_count"] == 2
    assert all(row["included_in_certification"] is False for row in superseded)


def test_the_enrollment_token_is_invalidated_by_a_proposal_and_again_by_an_apply():
    """PRD: "Proposing a technical correction requires
    `expected_enrolled_bill_version` in the body, carrying the client's last
    observed `version` of the enrolled bill." and "A correction cites a location
    in the enrolled text; if an earlier correction has already been proposed or
    applied, the enrollment's `version` has advanced, the citation may no longer
    point where the drafter believes, and the proposal is refused with
    `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412)." and "Many corrections per
    enrollment are legitimate; the version comparison is the only discriminator."
    and "The proposal lands in `status` `PROPOSED` with `proposed_by_drafter_id`
    stamped from `X-User-ID` and `applied_by_drafter_id` and `applied_utc` null,
    and it raises the enrollment's `open_corrections_count` by one and its
    `version` by one." and "On success the correction moves to `APPLIED` with
    `applied_by_drafter_id` set from `X-User-ID` and `applied_utc` stamped from the
    logical clock, the enrollment's `corrections_applied_count` rises by one, its
    `open_corrections_count` drops by one, and its `version` rises by one." and
    "When a single request violates several rules at once, exactly one error is
    reported, and which one is determined by a fixed ladder evaluated top to
    bottom." and "Evaluation stops at the first violated rung." and "**Substantive
    correction refusal.** `ERR_SUBSTANTIVE_CORRECTION_FORBIDDEN`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_enrolled_bill_version_blocks_a_correction_and_an_apply_invalidates_it_again
    """
    world = setup_world(with_committee=True)
    bill, _referral, enrolled = setup_enrolled_bill(world)
    assert enrolled["status"] == "PREPARED"
    assert enrolled["open_corrections_count"] == 0
    assert read_bill(world, bill["id"])["legislative_status"] == "ENROLLED"
    ebv1 = enrolled["version"]

    first = api_client.create_technical_correction(
        enrolled["id"],
        create_technical_correction_payload(
            ebv1,
            correction_type="CITATION",
            description="First correction, against a fresh view.",
        ),
        world["drafter_headers"],
    )
    tc1 = validate_success(first, 201)
    assert_technical_correction(tc1)
    assert tc1["status"] == "PROPOSED"
    assert tc1["proposed_by_drafter_id"] == world["drafter"]["id"]

    replay = api_client.create_technical_correction(
        enrolled["id"],
        create_technical_correction_payload(
            ebv1,
            correction_type="TYPO",
            description="Second correction, against the same stale view.",
        ),
        world["drafter_headers"],
    )
    validate_error(replay, STALE_ENROLLMENT, 412)

    # Stale and substantive at once: the concurrency rung is reached first, so the
    # substantive refusal further down the ladder is never the reported error.
    doubly_bad = api_client.create_technical_correction(
        enrolled["id"],
        create_technical_correction_payload(
            ebv1,
            correction_type="CROSS_REFERENCE",
            description="Stale and substantive at once.",
            is_substantive=True,
        ),
        world["drafter_headers"],
    )
    body = validate_error(doubly_bad, STALE_ENROLLMENT, 412)
    assert body["error_id"] != ApiErrorId.ERR_SUBSTANTIVE_CORRECTION_FORBIDDEN.value

    ebv2 = read_enrolled_bill(world, enrolled["id"])["version"]
    # One increment for the accepted proposal, none for either refusal.
    assert ebv2 == ebv1 + 1

    refiled = api_client.create_technical_correction(
        enrolled["id"],
        create_technical_correction_payload(
            ebv2,
            correction_type="TYPO",
            description="Second correction, refiled after re-reading.",
        ),
        world["drafter_headers"],
    )
    tc2 = validate_success(refiled, 201)
    assert tc2["status"] == "PROPOSED"

    ebv3 = read_enrolled_bill(world, enrolled["id"])["version"]
    assert ebv3 == ebv2 + 1

    applied = apply_correction(world, tc1)
    assert applied["status"] == "APPLIED"
    assert applied["applied_by_drafter_id"] == world["counsel"]["id"]

    after_apply = read_enrolled_bill(world, enrolled["id"])
    ebv4 = after_apply["version"]
    # Applying a correction is the second verb that moves the same token.
    assert ebv4 == ebv3 + 1
    assert after_apply["corrections_applied_count"] == 1
    assert after_apply["open_corrections_count"] == 1

    stale_after_apply = api_client.create_technical_correction(
        enrolled["id"],
        create_technical_correction_payload(
            ebv3,
            correction_type="CITATION",
            description="Third correction, against the pre-apply version.",
        ),
        world["drafter_headers"],
    )
    validate_error(stale_after_apply, STALE_ENROLLMENT, 412)

    accepted = api_client.create_technical_correction(
        enrolled["id"],
        create_technical_correction_payload(
            ebv4,
            correction_type="CITATION",
            description="Third correction, refiled after the apply.",
        ),
        world["drafter_headers"],
    )
    tc3 = validate_success(accepted, 201)
    assert tc3["status"] == "PROPOSED"

    final = read_enrolled_bill(world, enrolled["id"])
    assert final["corrections_applied_count"] == 1
    assert final["open_corrections_count"] == 2

    rows, meta = validate_paginated(
        api_client.list_technical_corrections(
            world["clerk_headers"],
            {"enrolled_bill_id": enrolled["id"], "limit": 20, "offset": 0},
        )
    )
    assert meta["total_count"] == 3
    assert {row["id"] for row in rows} == {tc1["id"], tc2["id"], tc3["id"]}


def test_five_derived_counters_reconcile_after_a_create_a_transition_and_a_kill():
    """PRD: "`bills_introduced_count` is the number of bills filed under this
    session regardless of their legislative state, while `bills_enrolled_count`
    counts only those bills whose legislative state has reached `ENROLLED` or
    `TRANSMITTED`." and "The committee's `active_referral_count` and the bill's
    `referral_count` each rise by one, and the bill's `version` rises by one." and
    "On success the referral moves from `IN_COMMITTEE` to `REPORTED_FAVORABLE`,
    `reported_utc` is stamped with the logical clock, and the committee's
    `active_referral_count` drops by one." and "The bill moves from
    `PASSED_CHAMBER` to `ENROLLED`, the session's `bills_enrolled_count` rises by
    one, and the bill's `version` rises by one." and "Every committee referral on a
    bill of this session still `IN_COMMITTEE` moves to `DIED_IN_COMMITTEE`, and
    each affected committee's `active_referral_count` is recomputed." and "Every
    technical correction on an enrollment of this session still `PROPOSED` moves to
    `REJECTED`, and each affected enrollment's `open_corrections_count` is
    recomputed downward." and "Every bill of this session whose
    `legislative_status` is `INTRODUCED`, `REFERRED`, `REPORTED` or
    `PASSED_CHAMBER` moves to `DEAD`, and its `fiscal_status` is left exactly as it
    was." and "Bills already `ENROLLED` or `TRANSMITTED` are untouched."

    Design: Corner/cross_cutting_complexity_layers/derived_counters_reconcile_after_create_after_transition_and_after_a_cascading_kill
    """
    world = setup_world(
        with_committee=True,
        committee_overrides={
            "chamber": "HOUSE",
            "name": "House Judiciary",
            "is_fiscal_committee": False,
            "max_concurrent_referrals": 2,
        },
    )
    _request_one, bill_one = setup_introduced_bill(
        world,
        affected_sections_count=3,
        engagement_start_utc="2026-09-02T00:00:00Z",
        engagement_end_utc="2026-09-03T00:00:00Z",
    )
    _request_two, bill_two = setup_introduced_bill(
        world,
        affected_sections_count=3,
        subject="Court interpreter staffing",
        summary="Standardize court interpreter staffing.",
        engagement_start_utc="2026-09-04T00:00:00Z",
        engagement_end_utc="2026-09-05T00:00:00Z",
    )

    after_creates = read_session(world)
    assert after_creates["bills_introduced_count"] == 2
    assert after_creates["bills_enrolled_count"] == 0
    assert read_bill(world, bill_one["id"])["fiscal_status"] == "NOT_REQUIRED"

    referral_one = refer_bill(world, bill_one)
    referral_two = refer_bill(
        world,
        bill_two,
        hearing_window_start_utc="2026-10-06T14:00:00Z",
        hearing_window_end_utc="2026-10-06T16:00:00Z",
    )
    assert read_committee(world, world["committee"]["id"])["active_referral_count"] == 2
    assert read_bill(world, bill_one["id"])["referral_count"] == 1
    assert read_bill(world, bill_two["id"])["referral_count"] == 1

    set_clock("2026-10-07T00:00:00Z")
    reported = report_referral(world, referral_one, "FAVORABLE")
    assert reported["status"] == "REPORTED_FAVORABLE"
    # The forward transition decremented exactly one of the two.
    assert read_committee(world, world["committee"]["id"])["active_referral_count"] == 1

    pass_bill(world, bill_one)
    enrolled = enroll_bill(world, bill_one)
    assert enrolled["status"] == "PREPARED"

    after_enrollment = read_session(world)
    assert after_enrollment["bills_enrolled_count"] == 1
    assert after_enrollment["bills_introduced_count"] == 2

    correction = propose_correction(
        world,
        enrolled,
        correction_type="CITATION",
        description="Left open on purpose.",
    )
    assert correction["status"] == "PROPOSED"
    assert read_enrolled_bill(world, enrolled["id"])["open_corrections_count"] == 1

    adjourned = validate_success(
        api_client.adjourn_session(world["session"]["id"], world["clerk_headers"]), 200
    )
    assert adjourned["status"] == "ADJOURNED"

    # The fan-out killed the live referral and recomputed the committee counter.
    assert read_committee(world, world["committee"]["id"])["active_referral_count"] == 0
    assert read_referral(world, referral_two["id"])["status"] == "DIED_IN_COMMITTEE"

    survivor = read_bill(world, bill_one["id"])
    casualty = read_bill(world, bill_two["id"])
    assert survivor["legislative_status"] == "ENROLLED"
    assert casualty["legislative_status"] == "DEAD"
    # referral_count counts referrals of any status, so the kill does not move it.
    assert casualty["referral_count"] == 1

    assert read_correction(world, correction["id"])["status"] == "REJECTED"
    final_enrollment = read_enrolled_bill(world, enrolled["id"])
    assert final_enrollment["open_corrections_count"] == 0
    assert final_enrollment["corrections_applied_count"] == 0
    assert final_enrollment["status"] == "PREPARED"

    final_session = read_session(world)
    # Introduced counts every status and the enrolled bill survives adjournment.
    assert final_session["bills_introduced_count"] == 2
    assert final_session["bills_enrolled_count"] == 1
