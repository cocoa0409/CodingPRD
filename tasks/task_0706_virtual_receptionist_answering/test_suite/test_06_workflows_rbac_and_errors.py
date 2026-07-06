"""Period close/finalize roll-over, receptionist go-online/offline guards, script
publishing, CRM handoff, escalation, FK-filtered listing, period OCC, RBAC, and
remaining error paths."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    fixtures as fx, factories as f,
    make_platform_admin_headers, make_account_owner_headers, make_receptionist_headers,
)

ADMIN = make_platform_admin_headers()


# =============================================================================
# Corner / state_machines / period_finalize_opens_next_period
# =============================================================================
def test_finalize_opens_next_period_and_repoints_account(api):
    """PRD §3.11: "The second step finalizes the period: it moves it from
    PENDING_CLOSE to CLOSED (a terminal state). Finalizing opens a fresh OPEN
    BillingPeriod for the account with period_index one greater than the closed
    period, and repoints the account's current_period_id to that new period."

    Closing then finalizing a fresh period-0 yields CLOSED, and the account's
    current_period_id repoints to a new OPEN period with period_index 1.

    Design: Corner/state_machines/period_finalize_opens_next_period
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    acct_id = account["id"]
    period_id = account["current_period_id"]

    period = validate_success(api.get_billing_period(period_id, ADMIN))
    get_success_data(api.close_billing_period(
        period_id, {"expected_period_version": period["version"]}, ADMIN))
    finalized = validate_success(api.finalize_billing_period(period_id, ADMIN))
    assert finalized["status"] == "CLOSED"

    acct = validate_success(api.get_account(acct_id, ADMIN))
    assert acct["current_period_id"] != period_id, (
        "current_period_id must repoint to a new period after finalize")
    new_period = validate_success(api.get_billing_period(acct["current_period_id"], ADMIN))
    assert new_period["period_index"] == 1, (
        f"new period_index {new_period['period_index']} != 1")
    assert new_period["status"] == "OPEN"


# =============================================================================
# Corner / state_machines / go_online_without_window_rejected
# =============================================================================
def test_go_online_without_availability_window_rejected(api):
    """PRD §3.3: "A receptionist becomes reachable by going online, which
    transitions status from OFFLINE to AVAILABLE; this requires the agent to have
    at least one ACTIVE AvailabilityWindow, and an attempt without one is rejected
    with ERR_NO_AVAILABILITY_WINDOW."

    A receptionist with zero windows calling go-online is rejected with
    ERR_NO_AVAILABILITY_WINDOW and stays OFFLINE.

    Design: Corner/state_machines/go_online_without_window_rejected
    """
    rec = get_success_data(api.create_receptionist(
        f.create_receptionist_payload(display_name="NoWin", languages=["EN"],
                                      max_concurrent_calls=1), ADMIN))
    rec_headers = make_receptionist_headers(rec["id"])
    resp = api.go_online(rec["id"], rec_headers)
    validate_error(resp, ApiErrorId.ERR_NO_AVAILABILITY_WINDOW.value)
    after = validate_success(api.get_receptionist(rec["id"], rec_headers))
    assert after["status"] == "OFFLINE", f"status {after['status']} != OFFLINE"


# =============================================================================
# Corner / state_machines / go_offline_with_active_call_rejected
# =============================================================================
def test_go_offline_with_active_call_rejected(api):
    """PRD §3.3: "Going offline transitions status from AVAILABLE to OFFLINE, but
    only when the agent has no calls in progress (active_call_count equal to 0);
    otherwise the request is rejected with ERR_RECEPTIONIST_BUSY."

    A receptionist with one IN_PROGRESS call (active_call_count 1) calling
    go-offline is rejected with ERR_RECEPTIONIST_BUSY.

    Design: Corner/state_machines/go_offline_with_active_call_rejected
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    fx.create_published_script(account["id"])
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)
    rec_headers = make_receptionist_headers(rec["id"])

    call = fx.intake_call(account["id"], rec["id"], caller_id="5550001")
    fx.answer_call(call["id"], rec["id"])
    get_success_data(api.start_call(call["id"], rec_headers))

    before = validate_success(api.get_receptionist(rec["id"], rec_headers))
    assert before["active_call_count"] == 1
    resp = api.go_offline(rec["id"], rec_headers)
    validate_error(resp, ApiErrorId.ERR_RECEPTIONIST_BUSY.value)


# =============================================================================
# Corner / state_machines / publish_retires_prior_published_script
# =============================================================================
def test_publish_retires_prior_published_script(api):
    """PRD §3.2: "Because an account may have at most one live script, publishing a
    draft also retires the account's previously PUBLISHED script, moving that prior
    script to RETIRED."

    Publishing a second DRAFT script flips the account's prior PUBLISHED script to
    RETIRED and the new one to PUBLISHED.

    Design: Corner/state_machines/publish_retires_prior_published_script
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    s1 = get_success_data(api.create_call_script(
        f.create_call_script_payload(account["id"], greeting_en="first"), owner))
    get_success_data(api.publish_call_script(s1["id"], owner))
    s2 = get_success_data(api.create_call_script(
        f.create_call_script_payload(account["id"], greeting_en="second"), owner))

    s2_pub = validate_success(api.publish_call_script(s2["id"], owner))
    assert s2_pub["status"] == "PUBLISHED"
    s1_after = validate_success(api.get_call_script(s1["id"], owner))
    assert s1_after["status"] == "RETIRED", (
        f"prior script status {s1_after['status']} != RETIRED")


# =============================================================================
# Corner / validations / intake_without_published_script_rejected
# =============================================================================
def test_intake_without_published_script_rejected(api):
    """PRD §3.4: "It resolves the account's single PUBLISHED CallScript into the
    call's script_id; if no published script exists, intake fails with
    ERR_NO_PUBLISHED_SCRIPT."

    Intaking a call for an account whose only script is a DRAFT (never published)
    is rejected with ERR_NO_PUBLISHED_SCRIPT.

    Design: Corner/validations/intake_without_published_script_rejected
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    get_success_data(api.create_call_script(
        f.create_call_script_payload(account["id"]), owner))  # DRAFT, never published

    resp = api.create_call(f.create_call_payload(account["id"], caller_id="5550001"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_SCRIPT.value)


# =============================================================================
# Corner / validations / close_period_with_disputed_call_rejected
# =============================================================================
def test_close_period_with_disputed_call_rejected(api):
    """PRD §3.11: "Beginning the close requires the period to be OPEN, carries the
    expected_period_version optimistic-concurrency guard of §2.6, and is blocked if
    any of the period's calls is still in DISPUTED billing status — an open dispute
    prevents close-out and the attempt is rejected with ERR_OPEN_DISPUTE."

    A period holding one DISPUTED call cannot be closed — the close is rejected
    with ERR_OPEN_DISPUTE.

    Design: Corner/validations/close_period_with_disputed_call_rejected
    """
    # setup_disputed_call leaves one DISPUTED call on its OPEN period.
    env = fx.setup_disputed_call()
    period_id = env["period_id"]
    period = validate_success(api.get_billing_period(period_id, ADMIN))
    resp = api.close_billing_period(
        period_id, {"expected_period_version": period["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_OPEN_DISPUTE.value)


# =============================================================================
# Corner / endpoints / crm_handoff_flips_new_messages_handed_off
# =============================================================================
def test_crm_handoff_flips_new_messages_to_handed_off(api):
    """PRD §3.13: "The handoff flips every NEW Message on that call to HANDED_OFF
    and records how many it flipped in messages_pushed; the handoff's status is
    PUSHED on success or FAILED."

    Pushing a call with two NEW messages yields messages_pushed 2, status PUSHED,
    and both messages flip to HANDED_OFF.

    Design: Corner/endpoints/crm_handoff_flips_new_messages_handed_off
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    fx.create_published_script(account["id"])
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)
    rec_headers = make_receptionist_headers(rec["id"])

    call = fx.intake_call(account["id"], rec["id"], caller_id="5550001")
    fx.answer_call(call["id"], rec["id"])
    get_success_data(api.start_call(call["id"], rec_headers))
    msg1 = get_success_data(api.create_message(
        f.create_message_payload(call["id"], caller_name="Joe", body="msg one", is_lead=True),
        rec_headers))
    msg2 = get_success_data(api.create_message(
        f.create_message_payload(call["id"], caller_name="Joe", body="msg two"), rec_headers))
    fx.set_clock("2026-03-01T12:01:00Z")
    get_success_data(api.wrap_call(call["id"], rec_headers))
    get_success_data(api.complete_call(call["id"], rec_headers))

    handoff = validate_success(api.create_crm_handoff(
        f.create_crm_handoff_payload(call["id"], crm_target="SALESFORCE"), owner),
        expected_status=201)
    assert handoff["messages_pushed"] == 2, (
        f"messages_pushed {handoff['messages_pushed']} != 2")
    assert handoff["status"] == "PUSHED"
    assert validate_success(api.get_message(msg1["id"], owner))["status"] == "HANDED_OFF"
    assert validate_success(api.get_message(msg2["id"], owner))["status"] == "HANDED_OFF"


# =============================================================================
# Corner / endpoints / escalate_in_progress_call_creates_escalation
# =============================================================================
def test_escalate_in_progress_call_with_no_senior_stays_queued(api):
    """PRD §3.6: "The escalation routing selector chooses a senior agent — the same
    eligibility and ranking as ordinary answer-routing, but additionally requiring
    the candidate's max_concurrent_calls to be at least 2 ... if the senior
    candidate set is empty the escalation stays QUEUED with
    escalated_to_receptionist_id null."

    With only a max_concurrent_calls=1 (non-senior) agent, escalating an
    IN_PROGRESS call creates an Escalation that stays QUEUED with a null
    escalated_to_receptionist_id.

    Design: Corner/endpoints/escalate_in_progress_call_creates_escalation
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    fx.create_published_script(account["id"], escalation_threshold_seconds=1)
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=1)
    rec_headers = make_receptionist_headers(rec["id"])

    call = fx.intake_call(account["id"], rec["id"], caller_id="5550001")
    fx.answer_call(call["id"], rec["id"])
    get_success_data(api.start_call(call["id"], rec_headers))
    # advance the clock so running duration reaches escalation_threshold_seconds.
    fx.set_clock("2026-03-01T12:00:05Z")

    esc = validate_success(api.escalate_call(
        call["id"], f.escalate_payload(reason="LONG_RUNNING"), rec_headers),
        expected_status=201)
    assert esc["status"] == "QUEUED", (
        f"escalation status {esc['status']} != QUEUED (no senior agent)")
    assert not esc["escalated_to_receptionist_id"], (
        "escalated_to_receptionist_id must be null when QUEUED")


# =============================================================================
# Corner / endpoints / list_appointments_by_origin_call_id
# =============================================================================
def test_list_appointments_filtered_by_origin_call_id(api):
    """PRD §3.12: "an optional origin_call_id linking the booking back to the call
    that produced it (defaulting to the empty string for direct bookings)."

    A booking carrying origin_call_id is returned when listing appointments
    filtered by that origin_call_id, and the returned record echoes the link.

    Design: Corner/endpoints/list_appointments_by_origin_call_id
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    fx.create_published_script(account["id"])
    call = validate_success(api.create_call(
        f.create_call_payload(account["id"], caller_id="5550001"), ADMIN),
        expected_status=201)
    slot = fx.create_slot(account["id"], capacity=1)
    appt = validate_success(api.create_appointment(
        f.create_appointment_payload(account["id"], slot["id"], slot["version"],
                                     origin_call_id=call["id"]), owner),
        expected_status=201)

    data, meta = validate_paginated(
        api.list_appointments(owner, params={"origin_call_id": call["id"]}))
    assert meta["total_count"] == 1, f"total_count {meta['total_count']} != 1"
    assert data[0]["id"] == appt["id"]
    assert data[0]["origin_call_id"] == call["id"]


# =============================================================================
# Corner / endpoints / list_calls_by_answered_receptionist
# =============================================================================
def test_list_calls_filtered_by_answered_receptionist(api):
    """PRD §3.5: "On success the call moves from RINGING to ANSWERED and its
    answered_by_receptionist_id is set to the selected agent".

    A call answered by a receptionist is returned when listing calls filtered by
    that answered_by_receptionist_id, and the returned record is that call.

    Design: Corner/endpoints/list_calls_by_answered_receptionist
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    fx.create_published_script(account["id"])
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)
    call = fx.intake_call(account["id"], rec["id"], caller_id="5550001")
    fx.answer_call(call["id"], rec["id"])

    data, meta = validate_paginated(
        api.list_calls(ADMIN, params={"answered_by_receptionist_id": rec["id"]}))
    assert meta["total_count"] == 1, f"total_count {meta['total_count']} != 1"
    assert data[0]["id"] == call["id"]


# =============================================================================
# Corner / errors / dispute_when_period_not_open_rejected
# =============================================================================
def test_dispute_when_period_not_open_rejected(api):
    """PRD §3.10: "A dispute or other usage operation targeting a non-OPEN period
    is rejected with ERR_PERIOD_NOT_OPEN."

    A BILLED call whose period has been moved to PENDING_CLOSE cannot be disputed —
    the dispute is rejected with ERR_PERIOD_NOT_OPEN.

    Design: Corner/errors/dispute_when_period_not_open_rejected
    """
    env = fx.setup_answer_environment(plan_kind="PER_CALL", clock="2026-03-01T09:00:00Z")
    account = get_success_data(api.get_account(env["account"]["id"], ADMIN))
    period_id = account["current_period_id"]
    owner = env["owner_headers"]

    call = fx.create_completed_call(env, "2026-03-01T09:00:00Z", "2026-03-01T09:01:00Z")
    period = validate_success(api.get_billing_period(period_id, ADMIN))
    get_success_data(api.close_billing_period(
        period_id, {"expected_period_version": period["version"]}, ADMIN))

    resp = api.dispute_call(call["id"], owner)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_OPEN.value)


# =============================================================================
# Corner / errors / answer_after_hours_voicemail_blocked
# =============================================================================
def test_answer_after_hours_voicemail_call_blocked(api):
    """PRD §3.5: "An attempt to answer an after-hours call that the script does not
    make routable is rejected with ERR_AFTER_HOURS_BLOCKED."

    A call intaken at 18:00 against a script with business hours [09:00,17:00) and
    after_hours_action VOICEMAIL is after-hours and not routable, so answering it is
    rejected with ERR_AFTER_HOURS_BLOCKED.

    Design: Corner/errors/answer_after_hours_voicemail_blocked
    """
    fx.set_clock("2026-03-01T18:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    fx.create_published_script(account["id"], business_open_minute=540,
                               business_close_minute=1020, after_hours_action="VOICEMAIL")
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)
    rec_headers = make_receptionist_headers(rec["id"])

    call = fx.intake_call(account["id"], rec["id"], caller_id="5550001")
    assert call["is_after_hours"] is True, "call must be after-hours at 18:00"
    resp = api.answer_call(call["id"], rec_headers)
    validate_error(resp, ApiErrorId.ERR_AFTER_HOURS_BLOCKED.value)


# =============================================================================
# Corner / rbac / account_owner_cannot_answer_call
# =============================================================================
def test_account_owner_cannot_answer_call(api):
    """PRD §3.5: "Answering a call is a Receptionist action that runs the
    answer-routing selector to pick which agent takes it."
    PRD §2.1: "When an authenticated role is not permitted to perform a given
    operation, the request is rejected with ERR_FORBIDDEN_ROLE."

    Answering is a Receptionist action; an AccountOwner attempting it is rejected
    with ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/account_owner_cannot_answer_call
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    fx.create_published_script(account["id"])
    call = validate_success(api.create_call(
        f.create_call_payload(account["id"], caller_id="5550001"), ADMIN),
        expected_status=201)
    owner = make_account_owner_headers(account["id"])
    resp = api.answer_call(call["id"], owner)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# =============================================================================
# Corner / rbac / receptionist_cannot_create_service_plan
# =============================================================================
def test_receptionist_cannot_create_service_plan(api):
    """PRD §3.1: "The commercial relationship begins with a ServicePlan, an
    immutable price card created by a PlatformAdmin."
    PRD §2.1: "When an authenticated role is not permitted to perform a given
    operation, the request is rejected with ERR_FORBIDDEN_ROLE."

    Service-plan creation is a PlatformAdmin operation; a Receptionist attempting
    it is rejected with ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/receptionist_cannot_create_service_plan
    """
    rec = get_success_data(api.create_receptionist(
        f.create_receptionist_payload(display_name="R", languages=["EN"],
                                      max_concurrent_calls=1), ADMIN))
    rec_headers = make_receptionist_headers(rec["id"])
    resp = api.create_service_plan(
        f.create_per_call_plan_payload(name="Nope", base_fee_cents=0), rec_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# =============================================================================
# Corner / rbac / account_owner_cannot_publish_other_accounts_script
# =============================================================================
def test_account_owner_cannot_publish_other_accounts_script(api):
    """PRD §2.1: "An AccountOwner may therefore only act on its own scripts, spam
    rules, calendar slots, appointments, calls, billing periods, and CRM handoffs;
    acting on a resource belonging to another account is rejected with
    ERR_NOT_RESOURCE_OWNER."

    AccountOwner A publishing account B's call script is rejected with
    ERR_NOT_RESOURCE_OWNER (X-User-ID == A != the script's account_id B).

    Design: Corner/rbac/account_owner_cannot_publish_other_accounts_script
    """
    plan = get_success_data(api.create_service_plan(
        f.create_per_call_plan_payload(name="Pown", base_fee_cents=0), ADMIN))
    acct_a = get_success_data(api.create_account(
        f.create_account_payload(plan["id"], business_name="A"), ADMIN))
    acct_b = get_success_data(api.create_account(
        f.create_account_payload(plan["id"], business_name="B"), ADMIN))
    owner_b = make_account_owner_headers(acct_b["id"])
    script_b = get_success_data(api.create_call_script(
        f.create_call_script_payload(acct_b["id"]), owner_b))

    owner_a = make_account_owner_headers(acct_a["id"])
    resp = api.publish_call_script(script_b["id"], owner_a)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# =============================================================================
# Corner / rbac / missing_auth_headers_unauthenticated
# =============================================================================
def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: X-User-ID,
    identifying the acting user, and X-User-Role, declaring the capacity in which
    they act. A request missing either header is rejected with ERR_UNAUTHENTICATED."

    A request issued with no auth headers is rejected with ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.list_service_plans({})  # no X-User-ID / X-User-Role
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# =============================================================================
# Corner / cross_cutting_complexity_layers / occ_close_stale_period_version_rejected
# =============================================================================
def test_close_period_with_stale_version_rejected(api):
    """PRD §2.6: "Beginning the close-out of a billing period must carry
    expected_period_version matching the target BillingPeriod's current version; a
    mismatch is rejected with ERR_STALE_PERIOD_VERSION (HTTP 412)."

    Closing a period with an expected_period_version one less than the current
    version is rejected with ERR_STALE_PERIOD_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_close_stale_period_version_rejected
    """
    plan, account = fx.create_account_on_per_call_plan()
    period_id = account["current_period_id"]
    period = validate_success(api.get_billing_period(period_id, ADMIN))
    stale = period["version"] - 1
    resp = api.close_billing_period(period_id, {"expected_period_version": stale}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_PERIOD_VERSION.value)
