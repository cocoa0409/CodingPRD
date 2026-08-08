"""Meeting lifecycle legality, terminal lockdown, the parallel minutes dimension,
and the cross-entity dependency of agenda-item opening on the meeting (PRD §3.3-§3.6)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_agenda_item_payload, TEST_USERS,
    setup_scheduled_meeting, setup_noticed_meeting, setup_convened_meeting,
    setup_open_motion, get_success_data,
)

CLERK = TEST_USERS["clerk_headers"]


# ===========================================================================
# Cross-entity: opening an agenda item requires the meeting IN_SESSION
# ===========================================================================

def test_open_item_while_meeting_only_noticed_rejected(api):
    """PRD §3.4: "The presiding `BodyMember` opens an item `PENDING → OPEN`, which
    requires that the acting member be the presiding officer and that the parent
    meeting be `IN_SESSION`, else `ERR_MEETING_NOT_IN_SESSION`."

    Design: Difficulty/cross_entity_state_dependency/agenda_item_open_requires_meeting_in_session
    """
    ctx = setup_noticed_meeting(api, meeting_type="EMERGENCY", seat_count=3,
                                quorum_size=2, num_members=1)
    item = get_success_data(api.create_agenda_item(
        ctx["meeting"]["id"], create_agenda_item_payload(title="Item L", sequence=1,
                                                         item_type="DISCUSSION"), CLERK))
    resp = api.transition_agenda_item(item["id"], {"to_status": "OPEN"},
                                      ctx["presiding_headers"])
    validate_error(resp, ApiErrorId.ERR_MEETING_NOT_IN_SESSION.value)


def test_item_stays_pending_after_rejected_open(api):
    """PRD §3.4: "A new item starts `PENDING`; its lifecycle is
    `PENDING → OPEN → CLOSED`" — a rejected open (meeting not IN_SESSION) leaves the
    item in PENDING.

    Design: Difficulty/cross_entity_state_dependency/agenda_item_open_requires_meeting_in_session
    """
    ctx = setup_noticed_meeting(api, meeting_type="EMERGENCY", seat_count=3,
                                quorum_size=2, num_members=1)
    item = get_success_data(api.create_agenda_item(
        ctx["meeting"]["id"], create_agenda_item_payload(title="Item L", sequence=1,
                                                         item_type="DISCUSSION"), CLERK))
    api.transition_agenda_item(item["id"], {"to_status": "OPEN"}, ctx["presiding_headers"])
    fetched = validate_success(api.get_agenda_item(item["id"], CLERK))
    assert fetched["status"] == "PENDING"


# ===========================================================================
# Corner: invalid transitions / terminal lockdown / idempotency
# ===========================================================================

def test_convene_from_scheduled_without_notice_invalid(api):
    """PRD §3.3: "Convening advances `NOTICED → IN_SESSION`" — a still-SCHEDULED
    meeting is not in the legal from-state.
    PRD §2.10: "legality of the requested state transition from the current state and
    any cross-dimension or cross-entity state guard, failing with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/convene_from_scheduled_without_notice_invalid
    """
    ctx = setup_scheduled_meeting(api, meeting_type="EMERGENCY", seat_count=3,
                                  quorum_size=1, num_members=1)
    resp = api.transition_meeting(
        ctx["meeting"]["id"],
        {"to_status": "IN_SESSION", "present_member_ids": [ctx["members"][0]["id"]]},
        ctx["presiding_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancelled_meeting_terminal_lockdown(api):
    """PRD §3.3: "A meeting moves through its lifecycle dimension
    `SCHEDULED → NOTICED → IN_SESSION → ADJOURNED`, with `CANCELLED` reachable from
    `SCHEDULED`, `NOTICED`, or `IN_SESSION`." CANCELLED is terminal; a further
    transition is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/transition_cancelled_meeting_terminal_lockdown
    """
    ctx = setup_scheduled_meeting(api, meeting_type="EMERGENCY", seat_count=3,
                                  quorum_size=1, num_members=1)
    validate_success(api.transition_meeting(
        ctx["meeting"]["id"], {"to_status": "CANCELLED"}, CLERK))
    resp = api.transition_meeting(
        ctx["meeting"]["id"], {"to_status": "NOTICED", "notice_channel": "WEBSITE"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_double_convene_rejected(api):
    """PRD §3.3: "Convening advances `NOTICED → IN_SESSION`" — an already IN_SESSION
    meeting is no longer in NOTICED, so a second convene is rejected with
    ERR_INVALID_STATE (the transition is not idempotent).

    Design: Corner/state_machines/double_convene_idempotency_rejected
    """
    ctx = setup_convened_meeting(api, meeting_type="EMERGENCY", seat_count=3,
                                 quorum_size=2, num_members=2, num_present=2)
    resp = api.transition_meeting(
        ctx["meeting"]["id"],
        {"to_status": "IN_SESSION", "present_member_ids": ctx["present_ids"]},
        ctx["presiding_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_minutes_amend_cycle_reapproves(api):
    """PRD §3.6: "The values are `NONE → DRAFT → APPROVED → AMENDED`, and the
    amendment cycle closes with `AMENDED → APPROVED`." Re-approval returns
    minutes_status to APPROVED.

    Design: Corner/state_machines/minutes_amend_cycle_reapproves
    """
    ctx = setup_convened_meeting(api, meeting_type="EMERGENCY", seat_count=3,
                                 quorum_size=2, num_members=2, num_present=2)
    mid = ctx["meeting"]["id"]
    ph = ctx["presiding_headers"]
    validate_success(api.transition_meeting(mid, {"to_status": "ADJOURNED"}, ph))
    validate_success(api.meeting_minutes(mid, {"to_status": "DRAFT", "minutes_text": "v1"}, CLERK))
    validate_success(api.meeting_minutes(mid, {"to_status": "APPROVED"}, ph))
    validate_success(api.meeting_minutes(mid, {"to_status": "AMENDED", "minutes_text": "v2"}, CLERK))
    data = validate_success(api.meeting_minutes(mid, {"to_status": "APPROVED"}, ph))
    assert data["minutes_status"] == "APPROVED"


def test_adjourn_with_open_motion_blocked(api):
    """PRD §3.3: "Adjournment requires that the acting member be the presiding
    officer and that no `Motion` under any agenda item remains `OPEN`, else
    `ERR_OPEN_MOTIONS_EXIST`."

    Design: Corner/state_machines/adjourn_with_open_motion_blocked
    """
    ctx = setup_open_motion(api, seat_count=3, quorum_size=2, num_members=2, num_present=2)
    resp = api.transition_meeting(
        ctx["meeting"]["id"], {"to_status": "ADJOURNED"}, ctx["presiding_headers"])
    validate_error(resp, ApiErrorId.ERR_OPEN_MOTIONS_EXIST.value)
