"""Public-comment sign-up, the aggregate comment cap, and the single-active-speaker
rule for the podium queue (PRD §3.4)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, get_success_data,
    create_agenda_item_payload, create_speaker_slip_payload,
    register_requester, make_requester_headers, TEST_USERS,
    setup_scheduled_meeting, setup_convened_meeting, open_agenda_item,
)

CLERK = TEST_USERS["clerk_headers"]


def test_signup_on_disabled_item_rejected(api):
    """PRD §3.4: "Sign-up is refused with `ERR_PUBLIC_COMMENT_DISABLED` if the item's
    `public_comment_enabled` is false."

    Design: Corner/errors/signup_on_disabled_item_rejected
    """
    requester = register_requester(api, "Hal", "hal@example.com")
    ctx = setup_scheduled_meeting(api, meeting_type="EMERGENCY", seat_count=3,
                                  quorum_size=1, num_members=1)
    item = get_success_data(api.create_agenda_item(
        ctx["meeting"]["id"],
        create_agenda_item_payload(title="No comment", sequence=1, item_type="DISCUSSION",
                                   public_comment_enabled=False), CLERK))
    resp = api.create_speaker_slip(
        item["id"], create_speaker_slip_payload(requester["id"], speaker_name="Hal"),
        make_requester_headers(requester["id"]))
    validate_error(resp, ApiErrorId.ERR_PUBLIC_COMMENT_DISABLED.value)


def test_signup_exceeds_comment_cap_rejected(api):
    """PRD §3.4: "if adding the new slip's `allotted_seconds` would make that sum
    strictly exceed 1800 seconds, the sign-up is rejected with
    `ERR_COMMENT_CAP_EXCEEDED`."

    First slip 1000s already QUEUED; a second slip of 900s would total 1900 > 1800.

    Design: Corner/errors/signup_exceeds_comment_cap_rejected
    """
    r1 = register_requester(api, "Ivy", "ivy@example.com")
    r2 = register_requester(api, "Jon", "jon@example.com")
    ctx = setup_scheduled_meeting(api, meeting_type="EMERGENCY", seat_count=3,
                                  quorum_size=1, num_members=1)
    item = get_success_data(api.create_agenda_item(
        ctx["meeting"]["id"],
        create_agenda_item_payload(title="Popular", sequence=1, item_type="DISCUSSION",
                                   public_comment_enabled=True), CLERK))
    validate_success(api.create_speaker_slip(
        item["id"], create_speaker_slip_payload(r1["id"], speaker_name="Ivy",
                                                allotted_seconds=1000),
        make_requester_headers(r1["id"])), 201)
    resp = api.create_speaker_slip(
        item["id"], create_speaker_slip_payload(r2["id"], speaker_name="Jon",
                                                allotted_seconds=900),
        make_requester_headers(r2["id"]))
    validate_error(resp, ApiErrorId.ERR_COMMENT_CAP_EXCEEDED.value)


def test_call_second_speaker_while_active_rejected(api):
    """PRD §3.4: "and that no other slip on the same item is currently `CALLED`
    (else `ERR_SPEAKER_ALREADY_ACTIVE`); calling stamps `called_at` to the logical
    clock."

    Design: Corner/errors/call_second_speaker_while_active_rejected
    """
    r1 = register_requester(api, "Kim", "kim@example.com")
    r2 = register_requester(api, "Lou", "lou@example.com")
    ctx = setup_convened_meeting(api, meeting_type="EMERGENCY", seat_count=3,
                                 quorum_size=1, num_members=1, num_present=1)
    item = open_agenda_item(api, ctx, item_type="DISCUSSION", public_comment_enabled=True)
    slip1 = get_success_data(api.create_speaker_slip(
        item["id"], create_speaker_slip_payload(r1["id"], speaker_name="Kim"),
        make_requester_headers(r1["id"])))
    slip2 = get_success_data(api.create_speaker_slip(
        item["id"], create_speaker_slip_payload(r2["id"], speaker_name="Lou"),
        make_requester_headers(r2["id"])))
    validate_success(api.transition_speaker_slip(
        slip1["id"], {"to_status": "CALLED"}, ctx["presiding_headers"]))
    resp = api.transition_speaker_slip(
        slip2["id"], {"to_status": "CALLED"}, ctx["presiding_headers"])
    validate_error(resp, ApiErrorId.ERR_SPEAKER_ALREADY_ACTIVE.value)
