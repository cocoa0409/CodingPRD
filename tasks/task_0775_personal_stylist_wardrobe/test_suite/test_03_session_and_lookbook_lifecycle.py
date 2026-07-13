"""State-machine lifecycles for sessions and lookbooks: the reschedule and revision cycles,
the cross-entity preconditions (completed assessment to confirm, active engagement to deliver),
the empty-lookbook guard, validation precedence on confirm, and invalid-transition rejections.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_confirmed_session, setup_scheduled_session, setup_lookbook,
    create_stylist, register_client, create_active_engagement,
    reschedule_session_payload, complete_session_payload,
    make_client_headers, make_stylist_headers,
)


# ─────────────── non_linear_state_machine / session_reschedule_confirmed_back_to_scheduled ───────────────
def test_reschedule_confirmed_session_returns_to_scheduled(api):
    """PRD §3.4: "A Client or a Stylist may reschedule a session that is SCHEDULED or CONFIRMED,
    supplying a fresh scheduled_start and scheduled_end; the session returns to SCHEDULED status
    and its estimated_blocks and provisional charge_cents are recomputed."

    Design: Difficulty/non_linear_state_machine/session_reschedule_confirmed_back_to_scheduled
    """
    ctx = setup_confirmed_session(api)
    data = validate_success(api.reschedule_session(
        ctx["session"]["id"],
        reschedule_session_payload("2026-04-05T14:00:00Z", "2026-04-05T15:30:00Z"),
        make_client_headers(ctx["client"]["id"])), 200)
    assert data["status"] == "SCHEDULED"


def test_reschedule_recomputes_estimated_blocks(api):
    """PRD §3.4: "the session returns to SCHEDULED status and its estimated_blocks and provisional
    charge_cents are recomputed."

    Design: Difficulty/non_linear_state_machine/session_reschedule_confirmed_back_to_scheduled
    """
    ctx = setup_confirmed_session(api)
    data = validate_success(api.reschedule_session(
        ctx["session"]["id"],
        reschedule_session_payload("2026-04-05T14:00:00Z", "2026-04-05T15:30:00Z"),
        make_client_headers(ctx["client"]["id"])), 200)
    assert data["estimated_blocks"] == 6, f"90-min window = 6 blocks, got {data['estimated_blocks']}"


# ─────────────── non_linear_state_machine / lookbook_request_revision_delivered_back_to_draft ───────────────
def test_request_revision_returns_lookbook_to_draft(api):
    """PRD §3.6: "A Client accepts a DELIVERED lookbook, moving it to the terminal ACCEPTED state,
    or requests a revision with optional notes, which returns the lookbook from DELIVERED to DRAFT
    and increments revision_round by one."

    Design: Difficulty/non_linear_state_machine/lookbook_request_revision_delivered_back_to_draft
    """
    ctx = setup_lookbook(api, num_outfits=1, deliver=True)
    data = validate_success(api.request_revision(
        ctx["lookbook"]["id"], {"notes": "swap the outerwear"},
        make_client_headers(ctx["client"]["id"])), 200)
    assert data["status"] == "DRAFT"


def test_request_revision_increments_revision_round(api):
    """PRD §3.6: "requests a revision with optional notes, which returns the lookbook from
    DELIVERED to DRAFT and increments revision_round by one."

    Design: Difficulty/non_linear_state_machine/lookbook_request_revision_delivered_back_to_draft
    """
    ctx = setup_lookbook(api, num_outfits=1, deliver=True)
    data = validate_success(api.request_revision(
        ctx["lookbook"]["id"], {"notes": "swap the outerwear"},
        make_client_headers(ctx["client"]["id"])), 200)
    assert data["revision_round"] == 1, f"revision_round should be 1, got {data['revision_round']}"


# ─────────────── boundary_precision_check / deliver_empty_lookbook_zero_outfits_rejected ───────────────
def test_deliver_empty_lookbook_rejected(api):
    """PRD §3.6: "the lookbook must hold at least one outfit (an outfit_count of zero is rejected
    with ERR_LOOKBOOK_EMPTY)."

    Design: Difficulty/boundary_precision_check/deliver_empty_lookbook_zero_outfits_rejected
    """
    ctx = setup_lookbook(api, num_outfits=0, deliver=False)
    resp = api.deliver_lookbook(ctx["lookbook"]["id"], make_stylist_headers(ctx["stylist"]["id"]))
    validate_error(resp, ApiErrorId.ERR_LOOKBOOK_EMPTY.value)


def test_empty_lookbook_stays_draft_after_rejected_deliver(api):
    """PRD §3.6: "the lookbook must hold at least one outfit (an outfit_count of zero is rejected
    with ERR_LOOKBOOK_EMPTY)."

    Design: Difficulty/boundary_precision_check/deliver_empty_lookbook_zero_outfits_rejected
    """
    ctx = setup_lookbook(api, num_outfits=0, deliver=False)
    api.deliver_lookbook(ctx["lookbook"]["id"], make_stylist_headers(ctx["stylist"]["id"]))
    after = validate_success(api.get_lookbook(ctx["lookbook"]["id"],
                                              make_stylist_headers(ctx["stylist"]["id"])), 200)
    assert after["status"] == "DRAFT", "rejected delivery must leave the lookbook DRAFT"


# ─────────────── cross_entity_state_dependency / confirm_session_requires_completed_assessment ───────────────
def test_confirm_session_with_draft_assessment_rejected(api):
    """PRD §3.3: "Confirmation requires the engagement's client to hold a StyleAssessment in
    COMPLETED status; if none exists, the confirm is rejected with ERR_ASSESSMENT_NOT_COMPLETED."

    Design: Difficulty/cross_entity_state_dependency/confirm_session_requires_completed_assessment
    """
    ctx = setup_scheduled_session(api, assessment="draft")
    resp = api.confirm_session(ctx["session"]["id"], make_stylist_headers(ctx["stylist"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_COMPLETED.value)


def test_session_stays_scheduled_when_assessment_incomplete(api):
    """PRD §3.3: "Confirmation requires the engagement's client to hold a StyleAssessment in
    COMPLETED status; if none exists, the confirm is rejected with ERR_ASSESSMENT_NOT_COMPLETED."

    Design: Difficulty/cross_entity_state_dependency/confirm_session_requires_completed_assessment
    """
    ctx = setup_scheduled_session(api, assessment="draft")
    api.confirm_session(ctx["session"]["id"], make_stylist_headers(ctx["stylist"]["id"]))
    after = validate_success(api.get_session(ctx["session"]["id"],
                                             make_stylist_headers(ctx["stylist"]["id"])), 200)
    assert after["status"] == "SCHEDULED", "rejected confirm must leave the session SCHEDULED"


# ─────────────── cross_entity_state_dependency / deliver_lookbook_requires_active_engagement ───────────────
def test_deliver_lookbook_with_cancelled_engagement_rejected(api):
    """PRD §3.6: "the engagement must be ACTIVE or FULFILLED (otherwise ERR_ENGAGEMENT_NOT_ACTIVE)."

    Design: Difficulty/cross_entity_state_dependency/deliver_lookbook_requires_active_engagement
    """
    ctx = setup_lookbook(api, num_outfits=1, deliver=False)
    validate_success(api.cancel_engagement(ctx["engagement"]["id"],
                                            make_client_headers(ctx["client"]["id"])), 200)
    resp = api.deliver_lookbook(ctx["lookbook"]["id"], make_stylist_headers(ctx["stylist"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE.value)


def test_lookbook_stays_draft_when_engagement_cancelled(api):
    """PRD §3.6: "the engagement must be ACTIVE or FULFILLED (otherwise ERR_ENGAGEMENT_NOT_ACTIVE)."

    Design: Difficulty/cross_entity_state_dependency/deliver_lookbook_requires_active_engagement
    """
    ctx = setup_lookbook(api, num_outfits=1, deliver=False)
    validate_success(api.cancel_engagement(ctx["engagement"]["id"],
                                            make_client_headers(ctx["client"]["id"])), 200)
    api.deliver_lookbook(ctx["lookbook"]["id"], make_stylist_headers(ctx["stylist"]["id"]))
    after = validate_success(api.get_lookbook(ctx["lookbook"]["id"],
                                              make_stylist_headers(ctx["stylist"]["id"])), 200)
    assert after["status"] == "DRAFT"


# ─────────────── priority_pair / state_beats_assessment_constraint_on_confirm ───────────────
def test_confirm_cancelled_session_returns_state_error(api):
    """PRD §2.11: "then the target's state eligibility for the requested transition (the
    invalid-state family). Business-specific checks follow the general checks."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_assessment_constraint_on_confirm
    """
    ctx = setup_scheduled_session(api, assessment="draft")
    validate_success(api.cancel_session(ctx["session"]["id"],
                                        make_client_headers(ctx["client"]["id"])), 200)
    resp = api.confirm_session(ctx["session"]["id"], make_stylist_headers(ctx["stylist"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_SESSION_STATE.value)


def test_state_error_preempts_assessment_constraint_on_confirm(api):
    """PRD §2.11: "then the target's state eligibility for the requested transition (the
    invalid-state family). Business-specific checks follow the general checks."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_assessment_constraint_on_confirm
    """
    ctx = setup_scheduled_session(api, assessment="draft")
    validate_success(api.cancel_session(ctx["session"]["id"],
                                        make_client_headers(ctx["client"]["id"])), 200)
    resp = api.confirm_session(ctx["session"]["id"], make_stylist_headers(ctx["stylist"]["id"]))
    body = resp.json()["data"]
    assert body["error_id"] != ApiErrorId.ERR_ASSESSMENT_NOT_COMPLETED.value, (
        "the state check must pre-empt the assessment constraint")
    assert body["error_id"] == ApiErrorId.ERR_INVALID_SESSION_STATE.value


# ─────────────── Corner: invalid transitions / idempotency ───────────────
def test_complete_scheduled_session_rejected(api):
    """PRD §3.4: "Completing a session that is not CONFIRMED, or completing without a positive
    actual_minutes, is rejected with ERR_INVALID_SESSION_STATE."

    Design: Corner/state_machines/complete_from_scheduled_state_rejected
    """
    ctx = setup_scheduled_session(api, assessment=None)
    resp = api.complete_session(ctx["session"]["id"], complete_session_payload(60),
                                make_stylist_headers(ctx["stylist"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_SESSION_STATE.value)


def test_accept_already_accepted_lookbook_rejected(api):
    """PRD §3.6: "Accepting or requesting a revision on a lookbook that is not DELIVERED is
    rejected with ERR_INVALID_LOOKBOOK_STATE."

    Design: Corner/state_machines/accept_already_accepted_lookbook_rejected
    """
    ctx = setup_lookbook(api, num_outfits=1, deliver=True)
    validate_success(api.accept_lookbook(ctx["lookbook"]["id"],
                                         make_client_headers(ctx["client"]["id"])), 200)
    resp = api.accept_lookbook(ctx["lookbook"]["id"], make_client_headers(ctx["client"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_LOOKBOOK_STATE.value)


def test_activate_already_active_engagement_rejected(api):
    """PRD §3.2: "Attempting a transition the engagement's current state does not permit is
    rejected with ERR_INVALID_ENGAGEMENT_STATE."

    Design: Corner/state_machines/activate_engagement_twice_rejected
    """
    sty = create_stylist(api)
    cl = register_client(api)
    eng = create_active_engagement(api, cl["id"], sty["id"], mode="HOURLY", block_rate_cents=3000)
    resp = api.activate_engagement(eng["id"], make_client_headers(cl["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_ENGAGEMENT_STATE.value)
