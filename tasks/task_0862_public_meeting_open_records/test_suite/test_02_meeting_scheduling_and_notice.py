"""Meeting scheduling conflicts (venue buffered half-open, presiding closed) and
the convene-time notice / quorum gates (PRD §3.2, §3.3)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_body, add_venue, add_member, create_meeting_payload,
    setup_noticed_meeting, make_body_member_headers, TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]


def _schedule(api, body_id, venue_id, presiding_id, start, end, meeting_type="REGULAR"):
    return api.create_meeting(body_id, create_meeting_payload(
        venue_id, presiding_id, meeting_type=meeting_type,
        scheduled_start=start, scheduled_end=end), CLERK)


# ===========================================================================
# Venue conflict — buffered, half-open occupancy interval
# ===========================================================================

def test_venue_buffered_overlap_rejected(api):
    """PRD §3.2: "Two meetings sharing a `venue_id` conflict when the new meeting's
    buffered start falls before the other's buffered end and the other's buffered
    start falls before the new meeting's buffered end; such a collision is rejected
    with `ERR_VENUE_CONFLICT`."

    Same venue, [09:30,11:00) vs [10:15,11:45) overlap; distinct presiding members
    isolate the venue rule.

    Design: Difficulty/resource_temporal_overlap/venue_buffered_halfopen_conflict
    """
    body = create_body(api)
    venue = add_venue(api, body["id"], "Shared V")
    m1 = add_member(api, body["id"], "M1", 1)
    m2 = add_member(api, body["id"], "M2", 2)
    validate_success(_schedule(api, body["id"], venue["id"], m1["id"],
                               "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z"), 201)
    resp = _schedule(api, body["id"], venue["id"], m2["id"],
                     "2026-06-01T10:45:00Z", "2026-06-01T11:45:00Z")
    validate_error(resp, ApiErrorId.ERR_VENUE_CONFLICT.value)


def test_venue_back_to_back_setup_buffer_conflict(api):
    """PRD §3.2: "Because of the setup buffer, two back-to-back meetings in the same
    room still collide."

    A [10:00,11:00) and back-to-back B [11:00,12:00) collide because B's buffered
    start 10:30 precedes A's end 11:00; distinct presiding members isolate venue.

    Design: Difficulty/resource_temporal_overlap/venue_buffered_halfopen_conflict
    """
    body = create_body(api)
    venue = add_venue(api, body["id"], "Shared V")
    m1 = add_member(api, body["id"], "M1", 1)
    m2 = add_member(api, body["id"], "M2", 2)
    validate_success(_schedule(api, body["id"], venue["id"], m1["id"],
                               "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z"), 201)
    resp = _schedule(api, body["id"], venue["id"], m2["id"],
                     "2026-06-01T11:00:00Z", "2026-06-01T12:00:00Z")
    validate_error(resp, ApiErrorId.ERR_VENUE_CONFLICT.value)


# ===========================================================================
# Presiding conflict — unbuffered, closed occupancy interval
# ===========================================================================

def test_presiding_touching_endpoint_rejected(api):
    """PRD §3.2: "Because this interval is closed, two adjacent meetings that share
    only a single endpoint instant still collide for the presiding member."

    Same presiding member; different venues isolate the presiding rule; [10:00,11:00]
    and [11:00,12:00] share the endpoint 11:00.

    Design: Difficulty/resource_temporal_overlap/presiding_closed_touching_conflict
    """
    body = create_body(api)
    v1 = add_venue(api, body["id"], "V1")
    v2 = add_venue(api, body["id"], "V2")
    m1 = add_member(api, body["id"], "M1", 1)
    validate_success(_schedule(api, body["id"], v1["id"], m1["id"],
                               "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z"), 201)
    resp = _schedule(api, body["id"], v2["id"], m1["id"],
                     "2026-06-01T11:00:00Z", "2026-06-01T12:00:00Z")
    validate_error(resp, ApiErrorId.ERR_PRESIDING_CONFLICT.value)


def test_presiding_non_touching_gap_allowed(api):
    """PRD §3.2: "Two meetings sharing a `presiding_member_id` conflict when the new
    meeting's start is at or before the other's end and the other's start is at or
    before the new meeting's end".

    A [10:00,11:00] and B [11:01,12:00] do not touch (11:01 is after 11:00), so the
    closed-interval check passes and B is accepted; different venues isolate presiding.

    Design: Difficulty/resource_temporal_overlap/presiding_closed_touching_conflict
    """
    body = create_body(api)
    v1 = add_venue(api, body["id"], "V1")
    v2 = add_venue(api, body["id"], "V2")
    m1 = add_member(api, body["id"], "M1", 1)
    validate_success(_schedule(api, body["id"], v1["id"], m1["id"],
                               "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z"), 201)
    resp = _schedule(api, body["id"], v2["id"], m1["id"],
                     "2026-06-01T11:01:00Z", "2026-06-01T12:00:00Z")
    validate_success(resp, 201)


# ===========================================================================
# Notice lead-time boundary at convene (exactly 72h for REGULAR)
# ===========================================================================

def _convene(api, ctx, present_ids):
    return api.transition_meeting(
        ctx["meeting"]["id"],
        {"to_status": "IN_SESSION", "present_member_ids": present_ids},
        ctx["presiding_headers"])


def test_convene_at_exactly_72h_succeeds(api):
    """PRD §3.3: "the meeting's `notice_lead_hours` must be at least the statutory
    minimum for its `meeting_type`, else `ERR_NOTICE_NONCOMPLIANT`" ... "the
    comparison is inclusive — a lead time exactly equal to the minimum complies."

    REGULAR minimum is 72h; notice posted exactly 72h before start convenes.

    Design: Difficulty/boundary_precision_check/notice_lead_exactly_72h_convene_succeeds
    """
    ctx = setup_noticed_meeting(api, meeting_type="REGULAR", seat_count=5, quorum_size=2,
                                num_members=2, scheduled_start="2026-06-01T18:00:00Z",
                                scheduled_end="2026-06-01T20:00:00Z",
                                notice_clock="2026-05-29T18:00:00Z")
    present = [m["id"] for m in ctx["members"]]
    data = validate_success(_convene(api, ctx, present))
    assert data["status"] == "IN_SESSION"


def test_notice_lead_hours_computed_as_72(api):
    """PRD §3.3: "computes `notice_lead_hours` as the number of hours between
    `notice_posted_at` and `scheduled_start` — that is, the difference
    `scheduled_start` minus `notice_posted_at` expressed in hours."

    Design: Difficulty/boundary_precision_check/notice_lead_exactly_72h_convene_succeeds
    """
    ctx = setup_noticed_meeting(api, meeting_type="REGULAR", seat_count=5, quorum_size=2,
                                num_members=2, scheduled_start="2026-06-01T18:00:00Z",
                                scheduled_end="2026-06-01T20:00:00Z",
                                notice_clock="2026-05-29T18:00:00Z")
    present = [m["id"] for m in ctx["members"]]
    data = validate_success(_convene(api, ctx, present))
    assert data["notice_lead_hours"] == 72


# ===========================================================================
# Priority pair: notice (temporal, p10) before quorum (constraint, p11)
# ===========================================================================

def test_convene_notice_noncompliant_wins_over_quorum(api):
    """PRD §2.10: "(10) temporal compliance gates for notice, appeal window, and
    retention; (11) resource-conflict and quorum constraints for venue, presiding
    overlap, quorum count, and comment cap".

    A REGULAR meeting with 71h lead AND only 1 of 2 required members present fails
    the temporal notice check first: ERR_NOTICE_NONCOMPLIANT.

    Design: Difficulty/priority_pair_validation_conflict/convene_notice_temporal_before_quorum_constraint
    """
    ctx = setup_noticed_meeting(api, meeting_type="REGULAR", seat_count=5, quorum_size=2,
                                num_members=2, scheduled_start="2026-06-01T18:00:00Z",
                                scheduled_end="2026-06-01T20:00:00Z",
                                notice_clock="2026-05-29T19:00:00Z")
    resp = _convene(api, ctx, [ctx["members"][0]["id"]])
    validate_error(resp, ApiErrorId.ERR_NOTICE_NONCOMPLIANT.value)


def test_convene_compliant_notice_surfaces_quorum(api):
    """PRD §2.10: "(10) temporal compliance gates for notice, appeal window, and
    retention; (11) resource-conflict and quorum constraints for venue, presiding
    overlap, quorum count, and comment cap".

    With the same short-quorum attempt but a compliant 72h notice, the temporal
    gate passes and the lower-priority quorum constraint surfaces:
    ERR_QUORUM_NOT_MET — confirming notice is evaluated before quorum.

    Design: Difficulty/priority_pair_validation_conflict/convene_notice_temporal_before_quorum_constraint
    """
    ctx = setup_noticed_meeting(api, meeting_type="REGULAR", seat_count=5, quorum_size=2,
                                num_members=2, scheduled_start="2026-06-01T18:00:00Z",
                                scheduled_end="2026-06-01T20:00:00Z",
                                notice_clock="2026-05-29T18:00:00Z")
    resp = _convene(api, ctx, [ctx["members"][0]["id"]])
    validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET.value)


# ===========================================================================
# Corner: quorum-not-met (isolated), end<=start validation
# ===========================================================================

def test_convene_below_quorum_rejected(api):
    """PRD §3.3: "the count of `present_member_ids` must be at least the body's
    `quorum_size`, else `ERR_QUORUM_NOT_MET`".

    An EMERGENCY meeting with a compliant notice but only 1 of the required 2
    members present is rejected for quorum.

    Design: Corner/errors/convene_below_quorum_rejected
    """
    ctx = setup_noticed_meeting(api, meeting_type="EMERGENCY", seat_count=3, quorum_size=2,
                                num_members=2)
    resp = _convene(api, ctx, [ctx["members"][0]["id"]])
    validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET.value)


def test_meeting_end_before_start_rejected(api):
    """PRD §3.2: "a `scheduled_start` and `scheduled_end` in ISO 8601 UTC where the
    end is strictly after the start".
    PRD §2.10: "`scheduled_end` strictly after `scheduled_start` ... failing with
    `ERR_VALIDATION`".

    Design: Corner/entities/meeting_end_before_start_rejected
    """
    body = create_body(api)
    venue = add_venue(api, body["id"])
    m1 = add_member(api, body["id"], "M1", 1)
    resp = _schedule(api, body["id"], venue["id"], m1["id"],
                     "2026-06-01T11:00:00Z", "2026-06-01T10:00:00Z")
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
