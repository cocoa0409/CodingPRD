"""Transitive cascades: meeting cancellation (depth-3) and request withdrawal
(depth-2) (PRD §3.3, §3.5, §3.8)."""
from test_helpers import (
    validate_success, validate_paginated, ApiErrorId, get_success_data,
    create_speaker_slip_payload, register_requester, make_requester_headers,
    TEST_USERS, setup_open_action_item, move_motion,
    setup_request_under_review, attach_document,
)

CLERK = TEST_USERS["clerk_headers"]


def _find(items, item_id):
    for it in items:
        if it["id"] == item_id:
            return it
    raise AssertionError(f"id {item_id} not found in list of {len(items)}")


# ===========================================================================
# Meeting cancel -> item cancel -> motion void + slip withdraw (depth 3)
# ===========================================================================

def _setup_cancellable_meeting(api):
    ctx = setup_open_action_item(api, seat_count=3, quorum_size=2, num_members=2, num_present=2)
    ctx["motion"] = move_motion(api, ctx)  # DRAFT (not opened)
    requester = register_requester(api, "Pam", "pam@example.com")
    ctx["slip"] = get_success_data(api.create_speaker_slip(
        ctx["item"]["id"], create_speaker_slip_payload(requester["id"], speaker_name="Pam"),
        make_requester_headers(requester["id"])))
    return ctx


def test_cancel_meeting_cascades_to_agenda_item(api):
    """PRD §3.3: "Cancelling a meeting cascades to every non-terminal `AgendaItem`,
    moving it to `CANCELLED`".

    Design: Difficulty/transitive_cascade/meeting_cancel_depth3_item_motion
    """
    ctx = _setup_cancellable_meeting(api)
    meeting = validate_success(api.transition_meeting(
        ctx["meeting"]["id"], {"to_status": "CANCELLED"}, CLERK))
    assert meeting["status"] == "CANCELLED"
    item = validate_success(api.get_agenda_item(ctx["item"]["id"], CLERK))
    assert item["status"] == "CANCELLED"


def test_cancel_meeting_voids_motion_and_withdraws_slip(api):
    """PRD §3.3: "an agenda item's own cancellation voids its motions and withdraws
    its speaker slips".
    PRD §3.5: "When an agenda item is cancelled, each of its motions in `DRAFT`,
    `OPEN`, or `TABLED` is voided".

    Design: Difficulty/transitive_cascade/meeting_cancel_depth3_item_motion
    """
    ctx = _setup_cancellable_meeting(api)
    validate_success(api.transition_meeting(
        ctx["meeting"]["id"], {"to_status": "CANCELLED"}, CLERK))
    motions, _ = validate_paginated(api.list_motions(ctx["item"]["id"], CLERK))
    assert _find(motions, ctx["motion"]["id"])["status"] == "VOIDED"
    slips, _ = validate_paginated(api.list_speaker_slips(ctx["item"]["id"], CLERK))
    assert _find(slips, ctx["slip"]["id"])["status"] == "WITHDRAWN"


# ===========================================================================
# Request withdraw -> documents cancelled + fee reset (depth 2)
# ===========================================================================

def test_withdraw_under_review_cancels_documents(api):
    """PRD §3.8: "withdrawing from `UNDER_REVIEW` additionally resets
    `assessed_fee_cents` and `fee_balance_cents` to 0 along with cancelling its
    documents."

    Design: Difficulty/transitive_cascade/request_withdraw_depth2_documents
    """
    ctx = setup_request_under_review(api, estimated_page_count=10)
    doc = attach_document(api, ctx, page_count=10, review_minutes=5, title="DocW")
    req = validate_success(api.transition_records_request(
        ctx["request"]["id"], {"to_status": "WITHDRAWN"}, ctx["requester_headers"]))
    assert req["status"] == "WITHDRAWN"
    docs, _ = validate_paginated(api.list_documents(ctx["request"]["id"], ctx["officer_headers"]))
    assert _find(docs, doc["id"])["status"] == "CANCELLED"


def test_withdraw_under_review_resets_fee_balance(api):
    """PRD §3.8: "withdrawing from `UNDER_REVIEW` additionally resets
    `assessed_fee_cents` and `fee_balance_cents` to 0".

    Design: Difficulty/transitive_cascade/request_withdraw_depth2_documents
    """
    ctx = setup_request_under_review(api, estimated_page_count=10)
    attach_document(api, ctx, page_count=10, review_minutes=5, title="DocW")
    req = validate_success(api.transition_records_request(
        ctx["request"]["id"], {"to_status": "WITHDRAWN"}, ctx["requester_headers"]))
    assert req["assessed_fee_cents"] == 0
    assert req["fee_balance_cents"] == 0
