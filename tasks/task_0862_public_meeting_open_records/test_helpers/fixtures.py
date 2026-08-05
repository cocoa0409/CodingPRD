"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server with an empty DB before every test).
Setup calls use get_success_data() so failures surface as clear "Setup failed"
errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_public_body_payload, create_requester_payload, create_member_payload,
    create_venue_payload, create_meeting_payload, create_agenda_item_payload,
    create_speaker_slip_payload, create_motion_payload,
    create_records_request_payload, create_document_payload, create_appeal_payload,
)
from .test_users import (
    TEST_USERS, make_requester_headers, make_body_member_headers,
    make_records_officer_headers, make_appeals_officer_headers,
)

CLERK = TEST_USERS["clerk_headers"]


# ---- primitives -------------------------------------------------------------

def set_clock(api, iso, *, headers=CLERK):
    return get_success_data(api.set_clock(iso, headers))


def register_requester(api, full_name="Rey Q", email="rey@example.com", **kw):
    return get_success_data(
        api.create_requester(create_requester_payload(full_name=full_name, email=email, **kw), {}))


def create_body(api, seat_count=5, quorum_size=2, name="City Council",
                jurisdiction_state="TX"):
    return get_success_data(api.create_public_body(
        create_public_body_payload(name=name, jurisdiction_state=jurisdiction_state,
                                   seat_count=seat_count, quorum_size=quorum_size), CLERK))


def add_member(api, body_id, full_name, seat_number):
    return get_success_data(api.add_member(
        body_id, create_member_payload(full_name=full_name, seat_number=seat_number), CLERK))


def add_venue(api, body_id, name="Chamber"):
    return get_success_data(api.add_venue(body_id, create_venue_payload(name=name), CLERK))


# ---- Tier 1/2: bodies, members, meetings ------------------------------------

def setup_body_with_members(api, seat_count=3, quorum_size=2, num_members=2):
    """Body + one venue + num_members members. Returns (body, venue, members)."""
    body = create_body(api, seat_count=seat_count, quorum_size=quorum_size)
    venue = add_venue(api, body["id"])
    members = [add_member(api, body["id"], f"M{i+1}", i + 1) for i in range(num_members)]
    return body, venue, members


def setup_scheduled_meeting(api, *, meeting_type="EMERGENCY", seat_count=3,
                            quorum_size=2, num_members=2,
                            scheduled_start="2026-05-01T02:00:00Z",
                            scheduled_end="2026-05-01T03:00:00Z"):
    """Body + members + a SCHEDULED meeting (no notice posted yet).

    presiding member is members[0]. Returns a dict with body, venue, members,
    presiding, presiding_headers, meeting.
    """
    body, venue, members = setup_body_with_members(api, seat_count, quorum_size, num_members)
    presiding = members[0]
    presiding_headers = make_body_member_headers(presiding["id"])
    meeting = get_success_data(api.create_meeting(
        body["id"],
        create_meeting_payload(venue["id"], presiding["id"], meeting_type=meeting_type,
                               scheduled_start=scheduled_start, scheduled_end=scheduled_end,
                               title="Meeting"), CLERK))
    return {"body": body, "venue": venue, "members": members, "presiding": presiding,
            "presiding_headers": presiding_headers, "meeting": meeting}


def setup_noticed_meeting(api, *, notice_clock=None, notice_channel="WEBSITE", **kw):
    """SCHEDULED meeting advanced to NOTICED (notice posted). Returns ctx."""
    ctx = setup_scheduled_meeting(api, **kw)
    if notice_clock:
        set_clock(api, notice_clock)
    ctx["meeting"] = get_success_data(api.transition_meeting(
        ctx["meeting"]["id"], {"to_status": "NOTICED", "notice_channel": notice_channel}, CLERK))
    return ctx


def setup_convened_meeting(api, *, num_present=2, **kw):
    """Body + members + meeting NOTICED then convened to IN_SESSION.

    present = first num_present members. Returns the noticed-meeting ctx with the
    meeting now IN_SESSION plus a present_ids entry.
    """
    ctx = setup_noticed_meeting(api, **kw)
    present_ids = [m["id"] for m in ctx["members"][:num_present]]
    ctx["present_ids"] = present_ids
    ctx["meeting"] = get_success_data(api.transition_meeting(
        ctx["meeting"]["id"], {"to_status": "IN_SESSION", "present_member_ids": present_ids},
        ctx["presiding_headers"]))
    return ctx


def open_agenda_item(api, ctx, *, item_type="ACTION", public_comment_enabled=True,
                     sequence=1, title="Item"):
    """Add an agenda item to a convened meeting and open it (PENDING -> OPEN)."""
    item = get_success_data(api.create_agenda_item(
        ctx["meeting"]["id"],
        create_agenda_item_payload(title=title, sequence=sequence, item_type=item_type,
                                   public_comment_enabled=public_comment_enabled), CLERK))
    item = get_success_data(api.transition_agenda_item(
        item["id"], {"to_status": "OPEN"}, ctx["presiding_headers"]))
    return item


def setup_open_action_item(api, **kw):
    """Convened meeting + one OPEN ACTION agenda item. Returns ctx with 'item'."""
    ctx = setup_convened_meeting(api, **kw)
    ctx["item"] = open_agenda_item(api, ctx, item_type="ACTION")
    return ctx


def move_motion(api, ctx, *, vote_threshold="SIMPLE", mover=None, seconder=None,
                text="A motion"):
    members = ctx["members"]
    mover = mover or members[0]["id"]
    seconder = seconder or members[1]["id"]
    return get_success_data(api.create_motion(
        ctx["item"]["id"],
        create_motion_payload(mover, seconder, vote_threshold=vote_threshold, text=text),
        ctx["presiding_headers"]))


def setup_open_motion(api, *, vote_threshold="SIMPLE", **kw):
    """Convened meeting + OPEN ACTION item + OPEN motion. Returns ctx with 'motion'."""
    ctx = setup_open_action_item(api, **kw)
    motion = move_motion(api, ctx, vote_threshold=vote_threshold)
    motion = get_success_data(api.transition_motion(
        motion["id"], {"to_status": "OPEN"}, ctx["presiding_headers"]))
    ctx["motion"] = motion
    return ctx


def cast(api, ctx, motion_id, member_id, value):
    return get_success_data(api.cast_vote(
        motion_id, {"member_id": member_id, "value": value},
        make_body_member_headers(member_id)))


def close_motion(api, ctx, motion_id):
    return get_success_data(api.transition_motion(
        motion_id, {"to_status": "CLOSED"}, ctx["presiding_headers"]))


# ---- Records-request lifecycle ----------------------------------------------

def setup_records_request(api, *, estimated_page_count=0, requester_name="Rey Q",
                          requester_email="rey@example.com"):
    """Registered requester + body + a submitted (RECEIVED) records request."""
    requester = register_requester(api, requester_name, requester_email)
    body = create_body(api)
    req_headers = make_requester_headers(requester["id"])
    request = get_success_data(api.create_records_request(
        create_records_request_payload(requester["id"], body["id"],
                                        estimated_page_count=estimated_page_count), req_headers))
    return {"requester": requester, "body": body, "request": request,
            "requester_headers": req_headers}


def setup_request_under_review(api, *, officer_id="officer-1", **kw):
    """Records request advanced to UNDER_REVIEW. Returns ctx with 'officer_headers'."""
    ctx = setup_records_request(api, **kw)
    officer_headers = make_records_officer_headers(officer_id)
    ctx["officer_headers"] = officer_headers
    ctx["officer_id"] = officer_id
    ctx["request"] = get_success_data(api.transition_records_request(
        ctx["request"]["id"], {"to_status": "UNDER_REVIEW"}, officer_headers))
    return ctx


def attach_document(api, ctx, *, page_count=10, review_minutes=0, exemption_code=None,
                    retention_series="ADMIN", title="Document"):
    payload = create_document_payload(page_count=page_count, review_minutes=review_minutes,
                                      retention_series=retention_series, title=title)
    if exemption_code is not None:
        payload["exemption_code"] = exemption_code
    return get_success_data(api.create_document(ctx["request"]["id"], payload,
                                                ctx["officer_headers"]))


def move_document(api, ctx, doc_id, to_status, *, headers=None):
    return get_success_data(api.transition_document(
        ctx["request"]["id"], doc_id, {"to_status": to_status},
        headers or ctx["officer_headers"]))


def release_document(api, ctx, *, page_count=10, review_minutes=0,
                     retention_series="ADMIN", title="Document"):
    """Attach a document then walk IDENTIFIED -> REVIEWED -> RELEASED."""
    doc = attach_document(api, ctx, page_count=page_count, review_minutes=review_minutes,
                          retention_series=retention_series, title=title)
    move_document(api, ctx, doc["id"], "REVIEWED")
    return move_document(api, ctx, doc["id"], "RELEASED")


def current_version(api, ctx):
    return get_success_data(api.get_records_request(
        ctx["request"]["id"], ctx["officer_headers"]))["version"]


def issue_determination(api, ctx, *, decision="GRANTED", waive_fee_cents=None,
                        expected_version=None):
    """Read the current version, then issue a determination. Returns the response
    object (NOT unwrapped) so callers can assert error paths too."""
    version = expected_version if expected_version is not None else current_version(api, ctx)
    payload = {"decision": decision, "expected_records_request_version": version}
    if waive_fee_cents is not None:
        payload["waive_fee_cents"] = waive_fee_cents
    return api.determine_request(ctx["request"]["id"], payload, ctx["officer_headers"])


def setup_determined_request(api, *, decision="GRANTED", docs=None, waive_fee_cents=None,
                             officer_id="officer-1", **kw):
    """Full path: request UNDER_REVIEW + released docs + a successful determination.

    docs is a list of (page_count, review_minutes) tuples, each RELEASED.
    Returns ctx with the request in its post-determination state.
    """
    ctx = setup_request_under_review(api, officer_id=officer_id, **kw)
    for i, (pc, rm) in enumerate(docs or []):
        release_document(api, ctx, page_count=pc, review_minutes=rm, title=f"D{i+1}")
    resp = issue_determination(api, ctx, decision=decision, waive_fee_cents=waive_fee_cents)
    ctx["request"] = get_success_data(resp)
    return ctx


def setup_denied_request(api, *, officer_id="officer-1", **kw):
    """Request DENIED by officer_id (no documents). Ready for an appeal."""
    return setup_determined_request(api, decision="DENIED", docs=[], officer_id=officer_id, **kw)


def file_appeal(api, ctx, *, grounds="Wrongful denial"):
    return get_success_data(api.create_appeal(
        ctx["request"]["id"], create_appeal_payload(grounds=grounds),
        ctx["requester_headers"]))


def setup_appeal_under_review(api, *, officer_id="officer-1", appeals_id="appeals-9", **kw):
    """DENIED request + FILED appeal moved to UNDER_REVIEW by a distinct appeals officer.

    Returns ctx with 'appeal' and 'appeals_headers'.
    """
    ctx = setup_denied_request(api, officer_id=officer_id, **kw)
    ctx["appeal"] = file_appeal(api, ctx)
    ctx["appeals_headers"] = make_appeals_officer_headers(appeals_id)
    ctx["appeals_id"] = appeals_id
    ctx["appeal"] = get_success_data(api.transition_appeal(
        ctx["request"]["id"], ctx["appeal"]["id"], {"to_status": "UNDER_REVIEW"},
        ctx["appeals_headers"]))
    return ctx
