"""Interval conflicts on two scarce calendars: the half-open outreach window an
investor occupies, and the closed, day-buffered clawback lookback period a live
restatement occupies on its company.
"""

from test_helpers import (
    COUNSEL_ONE,
    IR_LEAD,
    ApiErrorId,
    api_client,
    assert_money,
    create_engagement,
    create_restatement_event,
    create_restatement_event_payload,
    make_securities_counsel_headers,
    read_engagement,
    read_restatement_event,
    read_restatement_events,
    schedule_engagement,
    schedule_engagement_payload,
    setup_issuer,
    setup_pay_program,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Fixtures built from scratch inside each test
# ---------------------------------------------------------------------------
def _blackrock_calendar():
    """Two adjacent BlackRock slots booked, plus two engagements still REQUESTED.

    The program's meeting date is 2027-05-12T00:00:00Z, so the pre-meeting
    blackout is nowhere near the March windows used here.
    """
    env = setup_pay_program(approve=False)
    program_id = env["program"]["id"]
    first = create_engagement(program_id, "BlackRock", 20.00, "MEETING")
    schedule_engagement(first["id"], "2027-03-01T00:00:00Z", "2027-03-05T00:00:00Z")
    second = create_engagement(program_id, "BlackRock", 20.00, "CALL")
    second = schedule_engagement(second["id"], "2027-03-05T00:00:00Z", "2027-03-08T00:00:00Z")
    third = create_engagement(program_id, "BlackRock", 20.00, "LETTER")
    other_investor = create_engagement(program_id, "Vanguard", 11.00, "MEETING")
    env["engagements"] = [first, second, third, other_investor]
    return env


def _issuer_with_one_live_restatement():
    """ACME with a single DECLARED restatement over calendar 2026."""
    env = setup_issuer()
    env["restatement_event"] = create_restatement_event(env["issuer"]["id"])
    return env


# ===========================================================================
# The investor's calendar: half-open windows keyed by investor_key
# ===========================================================================
def test_same_investor_slot_beginning_when_another_ends_is_accepted():
    """Exact adjacency between two windows of the same investor is legal.

    "Because both intervals are half-open, exact adjacency is permitted: a slot
    beginning at the very instant a prior slot ends does not overlap it."

    Design: Difficulty/resource_temporal_overlap/same_investor_half_open_windows_allow_adjacency_but_reject_one_second_overlap
    """
    env = _blackrock_calendar()
    program_id = env["program"]["id"]
    second = env["engagements"][1]
    third = env["engagements"][2]

    assert second["engagement_status"] == "SCHEDULED"
    assert second["window_start"].startswith("2027-03-05T00:00:00")
    assert second["window_end"].startswith("2027-03-08T00:00:00")

    adjacent = validate_success(
        api_client.schedule_outreach_engagement(
            third["id"],
            schedule_engagement_payload("2027-03-08T00:00:00Z", "2027-03-10T00:00:00Z"),
            IR_LEAD,
        ),
        200,
    )
    assert adjacent["engagement_status"] == "SCHEDULED"
    assert adjacent["window_start"].startswith("2027-03-08T00:00:00")
    assert read_engagement(program_id, third["id"])["engagement_status"] == "SCHEDULED"


def test_same_investor_slot_overlapping_by_one_second_is_rejected():
    """One second of intersection with a booked slot of the same investor collides.

    "Second the **same-investor overlap**: gather the program's other engagements
    sharing the candidate's `investor_key` whose status is `SCHEDULED` or `HELD` —
    `REQUESTED` rivals are ignored entirely — and refuse the candidate with
    `ERR_OUTREACH_WINDOW_OVERLAP` if the candidate's start falls strictly before a
    rival's end while that rival's start falls strictly before the candidate's end."

    Design: Difficulty/resource_temporal_overlap/same_investor_half_open_windows_allow_adjacency_but_reject_one_second_overlap
    """
    env = _blackrock_calendar()
    program_id = env["program"]["id"]
    third = env["engagements"][2]
    assert third["engagement_status"] == "REQUESTED"

    response = api_client.schedule_outreach_engagement(
        third["id"],
        schedule_engagement_payload("2027-03-04T23:59:59Z", "2027-03-06T00:00:00Z"),
        IR_LEAD,
    )
    validate_error(response, ApiErrorId.ERR_OUTREACH_WINDOW_OVERLAP, 409)

    unchanged = read_engagement(program_id, third["id"])
    assert unchanged["engagement_status"] == "REQUESTED"
    assert unchanged["window_start"] is None
    assert unchanged["window_end"] is None


def test_window_conflict_is_scoped_to_the_investor_key():
    """A different investor may book a window that swallows every rival slot.

    "The `investor_key` is the `investor_name` trimmed of surrounding whitespace
    and upper-cased, and it — not the display name — is the identity used both for
    window-conflict detection and for coverage de-duplication, so that "BlackRock",
    " blackrock " and "BLACKROCK" are one investor."

    Design: Difficulty/resource_temporal_overlap/same_investor_half_open_windows_allow_adjacency_but_reject_one_second_overlap
    """
    env = _blackrock_calendar()
    other_investor = env["engagements"][3]
    assert other_investor["investor_key"] == "VANGUARD"

    booked = validate_success(
        api_client.schedule_outreach_engagement(
            other_investor["id"],
            schedule_engagement_payload("2027-03-01T00:00:00Z", "2027-03-20T00:00:00Z"),
            IR_LEAD,
        ),
        200,
    )
    assert booked["engagement_status"] == "SCHEDULED"
    assert booked["window_start"].startswith("2027-03-01T00:00:00")
    assert booked["window_end"].startswith("2027-03-20T00:00:00")


# ===========================================================================
# The company's clawback calendar: closed periods with a one-day buffer
# ===========================================================================
def test_lookback_period_starting_the_day_a_live_rival_ends_collides():
    """The one-day buffer makes exact day-boundary adjacency a collision.

    "Gather the company's existing events whose status is `DECLARED`, `ANALYZED`
    or `RECOVERY_ORDERED` — events already `CLOSED` never block a new
    declaration — and reject the candidate with `ERR_LOOKBACK_PERIOD_COLLISION`
    when its lookback start falls at or before a rival's lookback end extended
    forward by one day *and* its lookback end falls at or after that rival's
    lookback start pulled back by one day."

    Design: Difficulty/resource_temporal_overlap/restatement_lookback_windows_reject_adjacency_because_of_the_one_day_buffer
    """
    env = _issuer_with_one_live_restatement()
    company_id = env["issuer"]["id"]
    incumbent = env["restatement_event"]
    assert incumbent["status"] == "DECLARED"

    response = api_client.create_restatement_event(
        company_id,
        create_restatement_event_payload(
            restatement_date="2027-07-01T00:00:00Z",
            lookback_start="2027-01-01T00:00:00Z",
            lookback_end="2027-06-30T23:59:59Z",
            accounting_reason="Lease accounting error in the first half of fiscal 2027.",
        ),
        make_securities_counsel_headers(COUNSEL_ONE),
    )
    validate_error(response, ApiErrorId.ERR_LOOKBACK_PERIOD_COLLISION, 409)

    assert len(read_restatement_events(company_id)) == 1
    untouched = read_restatement_event(company_id, incumbent["id"])
    assert untouched["status"] == "DECLARED"
    assert untouched["determination_count"] == 0
    assert_money(untouched["recoverable_total_usd"], 0.00, "recoverable_total_usd")
    assert_money(untouched["recovered_total_usd"], 0.00, "recovered_total_usd")
    assert untouched["version"] == incumbent["version"]


def test_lookback_period_starting_a_full_day_after_a_rival_ends_is_accepted():
    """A start strictly after the buffered end clears the collision rule.

    "Both bounds are closed and the buffer is symmetric, so unlike the half-open
    outreach windows, exact adjacency between two lookback periods is forbidden."

    Design: Difficulty/resource_temporal_overlap/restatement_lookback_windows_reject_adjacency_because_of_the_one_day_buffer
    """
    env = _issuer_with_one_live_restatement()
    company_id = env["issuer"]["id"]

    accepted = validate_success(
        api_client.create_restatement_event(
            company_id,
            create_restatement_event_payload(
                restatement_date="2027-07-01T00:00:00Z",
                lookback_start="2027-01-02T00:00:00Z",
                lookback_end="2027-06-30T23:59:59Z",
                accounting_reason="Lease accounting error in the first half of fiscal 2027.",
            ),
            make_securities_counsel_headers(COUNSEL_ONE),
        ),
        201,
    )
    assert accepted["status"] == "DECLARED"
    assert accepted["lookback_start"].startswith("2027-01-02T00:00:00")
    assert accepted["determination_count"] == 0
    assert_money(accepted["recoverable_total_usd"], 0.00, "recoverable_total_usd")
    assert len(read_restatement_events(company_id)) == 2


def test_lookback_buffer_is_symmetric_on_the_lower_edge():
    """A candidate ending inside the rival's pulled-back start collides; a day earlier does not.

    "Gather the company's existing events whose status is `DECLARED`, `ANALYZED`
    or `RECOVERY_ORDERED` — events already `CLOSED` never block a new
    declaration — and reject the candidate with `ERR_LOOKBACK_PERIOD_COLLISION`
    when its lookback start falls at or before a rival's lookback end extended
    forward by one day *and* its lookback end falls at or after that rival's
    lookback start pulled back by one day."

    Design: Difficulty/resource_temporal_overlap/restatement_lookback_windows_reject_adjacency_because_of_the_one_day_buffer
    """
    env = _issuer_with_one_live_restatement()
    company_id = env["issuer"]["id"]
    counsel = make_securities_counsel_headers(COUNSEL_ONE)

    on_the_edge = api_client.create_restatement_event(
        company_id,
        create_restatement_event_payload(
            restatement_date="2026-01-15T00:00:00Z",
            lookback_start="2025-06-01T00:00:00Z",
            lookback_end="2025-12-31T00:00:00Z",
            accounting_reason="Inventory valuation error in fiscal 2025.",
        ),
        counsel,
    )
    validate_error(on_the_edge, ApiErrorId.ERR_LOOKBACK_PERIOD_COLLISION, 409)
    assert len(read_restatement_events(company_id)) == 1

    one_second_earlier = validate_success(
        api_client.create_restatement_event(
            company_id,
            create_restatement_event_payload(
                restatement_date="2026-01-15T00:00:00Z",
                lookback_start="2025-06-01T00:00:00Z",
                lookback_end="2025-12-30T23:59:59Z",
                accounting_reason="Inventory valuation error in fiscal 2025.",
            ),
            counsel,
        ),
        201,
    )
    assert one_second_earlier["status"] == "DECLARED"
    assert one_second_earlier["lookback_end"].startswith("2025-12-30T23:59:59")
    assert len(read_restatement_events(company_id)) == 2
