"""Draft submit-review, model-access, event-completion and instruction states.

Every test in this module translates exactly one corner-design instance of the
``state_machines`` section: the ResponseDraft DRAFT -> IN_REVIEW station and the
inquiry it drags with it, the Contact model-access dimension and its grant and
revoke preconditions, the terminal COMPLETED RoadshowEvent, the release
precondition on a MeetingRequest, and the two branches of the
TransferAgentInstruction acknowledgement fork.

The server is restarted before each test, so every world is built in-test
through the documented endpoints with the logical clock moved explicitly.
"""

from test_helpers import (
    ACK_DECISION_ACKNOWLEDGE,
    ACK_DECISION_REJECT,
    ApiClient,
    ApiErrorId,
    CLASS_PUBLIC_DOMAIN,
    CONTACT_INSTITUTIONAL_HOLDER,
    CONTACT_RETAIL_HOLDER,
    CONTACT_SELL_SIDE_ANALYST,
    COVERAGE_INITIATED,
    DISCLOSURE_OFFICER,
    DRAFT_DRAFT,
    DRAFT_IN_REVIEW,
    EVENT_COMPLETED,
    EVENT_CONFERENCE,
    EVENT_LOCKED,
    EVENT_NDR,
    INQUIRY_AWAITING_APPROVAL,
    INQUIRY_DRAFTING,
    INSTRUCTION_ACKNOWLEDGED,
    INSTRUCTION_RECORD_DATE_SET,
    INSTRUCTION_RECORD_INQUIRY,
    INSTRUCTION_REJECTED,
    IR_ADMIN,
    IR_ANALYST,
    IR_ANALYST_USER_ID,
    MODEL_ACCESS_NONE,
    QUEUE_IR_DESK,
    REQUEST_ALLOCATED,
    REQUEST_WAITLISTED,
    SERVICING_GRANT_MODEL_ACCESS,
    SERVICING_REVOKE_MODEL_ACCESS,
    THREAT_NONE,
    TOPIC_GUIDANCE,
    TRANSFER_AGENT,
    TRANSFER_AGENT_2,
    TRANSFER_AGENT_USER_ID,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Corner/state_machines/submit_review_moves_draft_and_parent_inquiry_together
# ---------------------------------------------------------------------------


def _draft_ready_to_submit(api: ApiClient):
    """A GUIDANCE inquiry routed to IR_DESK carrying one PUBLIC_DOMAIN draft."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api, ticker="SBR", legal_name="Submit Review Corp", shares_outstanding=1000000
    )
    contact = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        display_name="Submit Holder",
        email="sbr@funds.test",
        shares_held=20000,
    )
    inquiry = fixtures.create_inquiry(
        api,
        company["id"],
        contact["id"],
        topic_category=TOPIC_GUIDANCE,
        subject="Any change to the published range?",
    )
    routed = fixtures.route_inquiry(api, inquiry["id"])
    assert routed["routing_queue"] == QUEUE_IR_DESK
    draft = fixtures.create_draft(
        api,
        inquiry["id"],
        body_text="We have nothing to add beyond our published disclosures.",
        disclosure_class=CLASS_PUBLIC_DOMAIN,
    )
    return company, inquiry, draft


def test_submit_review_moves_draft_and_parent_inquiry_together(api: ApiClient):
    """PRD §3.6: "Submitting for review moves the draft `DRAFT` → `IN_REVIEW` and is available only to the author: another user is refused with `ERR_DRAFT_AUTHOR_MISMATCH`, and a draft in any status other than `DRAFT` is refused with `ERR_DRAFT_INVALID_STATE`."

    PRD §3.6: "A successful submission increments the draft's `version` by 1 and drives the parent inquiry `DRAFTING` → `AWAITING_APPROVAL`, incrementing the inquiry's `version` by 1."

    PRD §3.6: "Opening a draft against an inquiry in `ROUTED` transitions that inquiry `ROUTED` → `DRAFTING` and increments its `version` by 1; opening one against an inquiry already in `DRAFTING` leaves the status where it is but still increments the inquiry's `version` by 1, because the new draft row is itself the write."

    Design: Corner/state_machines/submit_review_moves_draft_and_parent_inquiry_together
    """
    _company, inquiry, draft = _draft_ready_to_submit(api)
    assertions.assert_response_draft(
        draft,
        status=DRAFT_DRAFT,
        version=1,
        author_user_id=IR_ANALYST_USER_ID,
        revision_round=1,
    )
    # create 1, route 2, draft opened 3.
    parent_before = fixtures.read_inquiry(api, inquiry["id"])
    assertions.assert_inquiry(parent_before, status=INQUIRY_DRAFTING, version=3)

    submitted = validate_success(api.submit_draft_for_review(draft["id"], IR_ANALYST))

    assertions.assert_response_draft(submitted, status=DRAFT_IN_REVIEW, version=2)
    parent_after = fixtures.read_inquiry(api, inquiry["id"])
    assertions.assert_inquiry(parent_after, status=INQUIRY_AWAITING_APPROVAL, version=4)
    assert fixtures.read_draft(api, draft["id"])["status"] == DRAFT_IN_REVIEW


def test_submit_review_leaves_the_open_count_and_the_deadline_alone(api: ApiClient):
    """PRD §2.11: "It is the number of that issuer's inquiry tickets whose status is `NEW`, `ROUTED`, `DRAFTING`, `AWAITING_APPROVAL` or `ESCALATED` — that is, every status except `ANSWERED`."

    PRD §3.5: "The deadline is recomputed on intake, on routing, and on every cascade link that returns an inquiry to `DRAFTING`."

    PRD §3.5: "Each queue carries its own service-level allowance, and the deadline is the logical clock at the moment of the write plus that allowance: 48 hours for `DISCLOSURE_COMMITTEE`, three days (72 hours) for `IR_DESK`, four days (96 hours) for `TRANSFER_AGENT_DESK` and five days (120 hours) for `SHAREHOLDER_SERVICES`."

    Design: Corner/state_machines/submit_review_moves_draft_and_parent_inquiry_together
    """
    company, inquiry, draft = _draft_ready_to_submit(api)

    fixtures.submit_for_review(api, draft["id"])

    parent = fixtures.read_inquiry(api, inquiry["id"])
    assert parent["status"] == INQUIRY_AWAITING_APPROVAL
    # 2026-08-01T00:00:00Z + the IR_DESK allowance of 72 hours, set at intake.
    assertions.assert_ts_equals(parent["sla_due_at"], "2026-08-04T00:00:00.000Z", "sla_due_at")
    assert fixtures.read_company(api, company["id"])["open_inquiry_count"] == 1


# ---------------------------------------------------------------------------
# Corner/state_machines/model_access_grant_and_revoke_preconditions_enforced
# ---------------------------------------------------------------------------


def _model_access_world(api: ApiClient):
    """An issuer at OPEN posture with an NDA-bearing holder and two analysts."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api, ticker="MDL", legal_name="Model Access Corp", shares_outstanding=1000000
    )
    holder = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        display_name="Model Holder",
        email="mdl1@funds.test",
        shares_held=10000,
        nda_on_file=True,
    )
    no_nda_analyst = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_SELL_SIDE_ANALYST,
        display_name="No NDA Analyst",
        email="mdl2@bank.test",
        nda_on_file=False,
        coverage_status=COVERAGE_INITIATED,
    )
    nda_analyst = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_SELL_SIDE_ANALYST,
        display_name="NDA Analyst",
        email="mdl3@bank.test",
        nda_on_file=True,
        coverage_status=COVERAGE_INITIATED,
    )
    return company, holder, no_nda_analyst, nda_analyst


def test_granting_model_access_to_a_holder_is_not_eligible(api: ApiClient):
    """PRD §3.3: "The target's `contact_type` must be `SELL_SIDE_ANALYST`, because financial models go to covering analysts and to nobody else; a holder row is refused with `ERR_MODEL_ACCESS_NOT_ELIGIBLE`."

    PRD §3.2: "Three fields are seeded by the system and cannot be supplied at creation: `model_access_status` starts at `NONE`, `threat_level` starts at `NONE`, and `dividend_received_cents` starts at 0."

    Design: Corner/state_machines/model_access_grant_and_revoke_preconditions_enforced
    """
    _company, holder, _no_nda_analyst, _nda_analyst = _model_access_world(api)
    # The NDA is on file, so contact_type is the only grant precondition that fails.
    assert holder["nda_on_file"] is True

    validate_error(
        api.servicing(
            holder["id"],
            factories.servicing_payload(SERVICING_GRANT_MODEL_ACCESS),
            DISCLOSURE_OFFICER,
        ),
        ApiErrorId.MODEL_ACCESS_NOT_ELIGIBLE.value,
    )

    assertions.assert_contact(
        fixtures.read_contact(api, holder["id"]),
        model_access_status=MODEL_ACCESS_NONE,
        threat_level=THREAT_NONE,
        version=1,
    )


def test_granting_model_access_without_an_nda_is_refused(api: ApiClient):
    """PRD §3.3: "The target's `nda_on_file` must be true, because the model is confidential; a missing NDA is refused with `ERR_NDA_REQUIRED`."

    PRD §3.3: "Granting model access moves `model_access_status` from `NONE` to `GRANTED`, and equally from `REVOKED` back to `GRANTED` — the re-grant closing a `GRANTED` → `REVOKED` → `GRANTED` cycle on that dimension."

    Design: Corner/state_machines/model_access_grant_and_revoke_preconditions_enforced
    """
    _company, _holder, no_nda_analyst, _nda_analyst = _model_access_world(api)
    # A covering analyst at an OPEN issuer: the NDA is the only failing precondition.
    assert no_nda_analyst["contact_type"] == CONTACT_SELL_SIDE_ANALYST
    assert no_nda_analyst["nda_on_file"] is False

    validate_error(
        api.servicing(
            no_nda_analyst["id"],
            factories.servicing_payload(SERVICING_GRANT_MODEL_ACCESS),
            DISCLOSURE_OFFICER,
        ),
        ApiErrorId.NDA_REQUIRED.value,
    )

    assertions.assert_contact(
        fixtures.read_contact(api, no_nda_analyst["id"]),
        model_access_status=MODEL_ACCESS_NONE,
        version=1,
    )


def test_revoking_model_access_that_was_never_granted_is_not_eligible(api: ApiClient):
    """PRD §3.3: "Revoking model access moves `model_access_status` from `GRANTED` to `REVOKED` and requires the current value to be exactly `GRANTED`; revoking an access that was never granted, or revoking twice, is refused with `ERR_MODEL_ACCESS_NOT_ELIGIBLE`."

    PRD §3.3: "A successful revocation increments the contact's `version` by 1."

    Design: Corner/state_machines/model_access_grant_and_revoke_preconditions_enforced
    """
    _company, _holder, _no_nda_analyst, nda_analyst = _model_access_world(api)
    assert nda_analyst["model_access_status"] == MODEL_ACCESS_NONE

    validate_error(
        api.servicing(
            nda_analyst["id"],
            factories.servicing_payload(SERVICING_REVOKE_MODEL_ACCESS),
            DISCLOSURE_OFFICER,
        ),
        ApiErrorId.MODEL_ACCESS_NOT_ELIGIBLE.value,
    )

    assertions.assert_contact(
        fixtures.read_contact(api, nda_analyst["id"]),
        model_access_status=MODEL_ACCESS_NONE,
        version=1,
    )


# ---------------------------------------------------------------------------
# Corner/state_machines/completed_event_rejects_every_further_trigger
# ---------------------------------------------------------------------------


def _completed_event_world(api: ApiClient):
    """A one-slot NDR taken all the way to COMPLETED with a single allocated request."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api, ticker="CMP", legal_name="Completed Event Corp", shares_outstanding=1000000
    )
    holder = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        display_name="Complete Holder",
        email="cmp@funds.test",
        shares_held=120000,
        nda_on_file=True,
    )
    event = fixtures.open_event(
        api,
        company["id"],
        event_type=EVENT_NDR,
        venue_city="Oslo",
        window_start="2026-09-01T13:00:00Z",
        window_end="2026-09-01T18:00:00Z",
        slot_minutes=30,
        capacity_slots=1,
    )
    request = fixtures.create_meeting_request(
        api,
        event["id"],
        holder["id"],
        requested_slot_start="2026-09-01T13:00:00Z",
        requested_slot_end="2026-09-01T13:30:00Z",
    )
    fixtures.allocate_event(api, event["id"])
    completed = fixtures.complete_event(api, event["id"])
    assert completed["status"] == EVENT_COMPLETED
    return company, holder, event, request


def test_completed_event_rejects_complete_open_requests_and_allocate(api: ApiClient):
    """PRD §3.8: "Completing the event is the last `IRAdmin` step and transitions it `LOCKED` → `COMPLETED`, refused with `ERR_EVENT_INVALID_STATE` from any other status."

    PRD §3.8: "Opening the event for business transitions it `PLANNING` → `OPEN_FOR_REQUESTS` and is refused with `ERR_EVENT_INVALID_STATE` from any other status."

    PRD §3.8: "Three preconditions guard it: the event must be in `OPEN_FOR_REQUESTS` (otherwise `ERR_EVENT_INVALID_STATE`), the issuer's stored `disclosure_posture` must not be `BLACKOUT` (otherwise `ERR_DISCLOSURE_BLACKOUT`, since a quiet period is no time to be taking investor meetings), and at least one of the event's requests must be in `REQUESTED` (otherwise `ERR_NO_PENDING_REQUESTS`)."

    Design: Corner/state_machines/completed_event_rejects_every_further_trigger
    """
    _company, _holder, event, _request = _completed_event_world(api)

    validate_error(
        api.complete_event(event["id"], IR_ADMIN), ApiErrorId.EVENT_INVALID_STATE.value
    )
    validate_error(
        api.open_event_requests(event["id"], IR_ADMIN),
        ApiErrorId.EVENT_INVALID_STATE.value,
    )
    validate_error(
        api.allocate_event(event["id"], IR_ADMIN), ApiErrorId.EVENT_INVALID_STATE.value
    )

    assert fixtures.read_event(api, event["id"])["status"] == EVENT_COMPLETED


def test_completed_event_keeps_its_allocation_counters(api: ApiClient):
    """PRD §3.8: "The second link, caused by the first, transitions every one of that event's requests still in `WAITLISTED` to `DECLINED`, incrementing each of those requests' `version` by 1."

    PRD §3.8: "`request_ledger_total` is the count of every meeting request ever created against the event and is monotonic: it never decreases."

    PRD §3.8: "A request that lands on `ALLOCATED` stores its `final_priority_score`, stamps `allocated_at` with the logical clock, sets `promoted_from_waitlist` to false, increments its own `version` by 1, and increases the event's `allocated_count` by 1."

    PRD §3.8: "Start with tier points read from the contact's `target_tier`: 50 for `TIER_1`, 35 for `TIER_2`, 20 for `TIER_3` and 5 for `UNTIERED`."

    PRD §3.8: "Add 8 when the contact's `nda_on_file` is true, and nothing when it is false."

    PRD §3.8: "Add an engagement term equal to the contact's `ownership_pct` multiplied by 4, rounded half up to 2 decimal places and then capped at 20 — the rounding happening before the term is added, and the cap meaning that any holder above five percent of the register contributes exactly 20."

    PRD §3.8: "Multiply the result by a type multiplier read from the contact's `contact_type`: 1.20 for an `INSTITUTIONAL_HOLDER`, 1.00 for a `SELL_SIDE_ANALYST` and 0.60 for a `RETAIL_HOLDER`."

    PRD §3.8: "The **final** variant runs during the allocation waterfall, is written to `final_priority_score`, uses the contact as it stands at allocation time, and adds a genuine lead-time bonus: 5 when the lead time is at least 14 days, otherwise 2 when the lead time is at least 7 days, otherwise 0."

    Design: Corner/state_machines/completed_event_rejects_every_further_trigger
    """
    _company, _holder, event, request = _completed_event_world(api)

    reread_event = fixtures.read_event(api, event["id"])
    assertions.assert_roadshow_event(
        reread_event,
        status=EVENT_COMPLETED,
        allocated_count=1,
        waitlisted_count=0,
        declined_count=0,
        released_count=0,
        request_ledger_total=1,
    )

    # TIER_1 50 + NDA 8 + engagement cap 20 + 14-day lead bonus 5 = 83, times 1.20.
    reread_request = fixtures.read_meeting_request(api, request["id"])
    assertions.assert_meeting_request(
        reread_request, status=REQUEST_ALLOCATED, promoted_from_waitlist=False
    )
    assert reread_request["final_priority_score"] == assertions.approx_2dp(99.60)


# ---------------------------------------------------------------------------
# Corner/state_machines/release_requires_an_allocated_request
# ---------------------------------------------------------------------------


def _locked_event_with_a_waitlisted_request(api: ApiClient):
    """One allocated TIER_1 holder and one threshold-deferred retail holder."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api, ticker="RLS", legal_name="Release Guard Corp", shares_outstanding=1000000
    )
    holder_a = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
        display_name="Release Holder A",
        email="rls1@funds.test",
        shares_held=120000,
        nda_on_file=True,
    )
    holder_b = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_RETAIL_HOLDER,
        display_name="Release Holder B",
        email="rls2@retail.test",
        shares_held=5000,
    )
    event = fixtures.open_event(
        api,
        company["id"],
        event_type=EVENT_CONFERENCE,
        venue_city="Madrid",
        window_start="2026-09-01T13:00:00Z",
        window_end="2026-09-01T18:00:00Z",
        slot_minutes=30,
        capacity_slots=1,
    )
    request_a = fixtures.create_meeting_request(
        api,
        event["id"],
        holder_a["id"],
        requested_slot_start="2026-09-01T13:00:00Z",
        requested_slot_end="2026-09-01T13:30:00Z",
    )
    request_b = fixtures.create_meeting_request(
        api,
        event["id"],
        holder_b["id"],
        requested_slot_start="2026-09-01T14:00:00Z",
        requested_slot_end="2026-09-01T14:30:00Z",
    )
    fixtures.allocate_event(api, event["id"])
    assert fixtures.read_event(api, event["id"])["status"] == EVENT_LOCKED
    return company, event, request_a, request_b


def test_releasing_a_waitlisted_request_is_refused(api: ApiClient):
    """PRD §3.8: "The request must be in `ALLOCATED`, or the release is refused with `ERR_MEETING_REQUEST_NOT_ALLOCATED`, and the parent event must be in `LOCKED`, or it is refused with `ERR_EVENT_INVALID_STATE`."

    PRD §3.8: "Candidates whose score is at least 25 are eligible; candidates below 25 are **threshold-deferred** and are never allocated in this run, however much capacity remains."

    PRD §3.8: "A request that lands on `WAITLISTED` also stores its `final_priority_score` and increments its own `version` by 1, but `allocated_at` stays null — a waitlisted request has never been given a time — and it increases the event's `waitlisted_count` by 1 instead."

    Design: Corner/state_machines/release_requires_an_allocated_request
    """
    _company, _event, _request_a, request_b = _locked_event_with_a_waitlisted_request(api)

    validate_error(
        api.release_meeting_request(
            request_b["id"], "Investor asked to withdraw the request.", IR_ADMIN
        ),
        ApiErrorId.MEETING_REQUEST_NOT_ALLOCATED.value,
    )

    # TIER_3 20 + no NDA + engagement 2.00 + lead bonus 5 = 27, times 0.60 = 16.20.
    reread = fixtures.read_meeting_request(api, request_b["id"])
    assertions.assert_meeting_request(
        reread, status=REQUEST_WAITLISTED, release_reason=None, allocated_at=None
    )
    assert reread["final_priority_score"] == assertions.approx_2dp(16.20)


def test_refused_release_leaves_the_event_ledger_untouched(api: ApiClient):
    """PRD §3.8: "The request must be in `ALLOCATED`, or the release is refused with `ERR_MEETING_REQUEST_NOT_ALLOCATED`, and the parent event must be in `LOCKED`, or it is refused with `ERR_EVENT_INVALID_STATE`."

    PRD §3.8: "`allocated_count`, `waitlisted_count`, `released_count` and `declined_count` are the counts of that event's requests in the corresponding statuses, and `request_ledger_total` always equals the sum of those four counters plus the number of the event's requests still in `REQUESTED`."

    Design: Corner/state_machines/release_requires_an_allocated_request
    """
    _company, event, request_a, request_b = _locked_event_with_a_waitlisted_request(api)

    validate_error(
        api.release_meeting_request(
            request_b["id"], "Investor asked to withdraw the request.", IR_ADMIN
        ),
        ApiErrorId.MEETING_REQUEST_NOT_ALLOCATED.value,
    )

    reread_a = fixtures.read_meeting_request(api, request_a["id"])
    assertions.assert_meeting_request(reread_a, status=REQUEST_ALLOCATED)
    assert reread_a["final_priority_score"] == assertions.approx_2dp(99.60)

    reread_event = fixtures.read_event(api, event["id"])
    assertions.assert_roadshow_event(
        reread_event,
        status=EVENT_LOCKED,
        allocated_count=1,
        waitlisted_count=1,
        released_count=0,
        declined_count=0,
        request_ledger_total=2,
    )
    assertions.assert_request_ledger_conserved(reread_event, still_requested=0)


# ---------------------------------------------------------------------------
# Corner/state_machines/instruction_rejection_skips_the_snapshot_and_locks_the_decision
# ---------------------------------------------------------------------------

REJECTION_REASON = "Holder identity could not be verified."


def _submitted_record_inquiry(api: ApiClient):
    """A RECORD_INQUIRY submitted by the desk, with one share-holding holder on file."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api, ticker="RJI", legal_name="Rejected Inquiry Corp", shares_outstanding=1000000
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        shares_held=4000,
        display_name="Record Inquiry Holder",
        email="rji@funds.test",
    )
    instruction = fixtures.create_instruction(
        api,
        company["id"],
        instruction_type=INSTRUCTION_RECORD_INQUIRY,
        notes="The holder disputes the address of record.",
    )
    assertions.assert_instruction(
        instruction, instruction_type=INSTRUCTION_RECORD_INQUIRY, version=1
    )
    return company, holder, instruction


def test_rejecting_an_instruction_stores_the_reason_and_takes_no_snapshot(api: ApiClient):
    """PRD §3.9: "The `REJECT` branch instead transitions the instruction `SUBMITTED` → `REJECTED`, requires a non-empty `rejection_reason` (otherwise `ERR_INVALID_REQUEST`) which it stores as `decision_reason`, and deliberately takes **no** snapshot at all: `snapshot_holder_count` and `snapshot_shares_total` stay null on a rejected instruction."

    PRD §3.9: "Both branches require the instruction to still be in `SUBMITTED` — anything else is refused with `ERR_INSTRUCTION_ALREADY_DECIDED` — both are barred to the user recorded as `submitted_by_user_id` by `ERR_SEGREGATION_OF_DUTIES`, and both stamp the acting user as `acknowledged_by_user_id` and increment the instruction's `version` by 1."

    PRD §3.9: "A new instruction is born in `SUBMITTED` with `acknowledged_by_user_id`, `executed_by_user_id`, `snapshot_holder_count`, `snapshot_shares_total`, `payout_ledger`, `total_payout_cents`, `executed_at` and `decision_reason` all null, and `version` at 1."

    Design: Corner/state_machines/instruction_rejection_skips_the_snapshot_and_locks_the_decision
    """
    _company, _holder, instruction = _submitted_record_inquiry(api)

    decided = validate_success(
        api.acknowledge_instruction(
            instruction["id"],
            factories.acknowledge_payload(ACK_DECISION_REJECT, REJECTION_REASON),
            TRANSFER_AGENT,
        )
    )
    assertions.assert_instruction(
        decided,
        status=INSTRUCTION_REJECTED,
        decision_reason=REJECTION_REASON,
        acknowledged_by_user_id=TRANSFER_AGENT_USER_ID,
        snapshot_holder_count=None,
        snapshot_shares_total=None,
        executed_by_user_id=None,
        executed_at=None,
        version=2,
    )

    # The register still carries a qualifying holder: the snapshot was skipped,
    # not merely empty.
    assertions.assert_instruction(
        fixtures.read_instruction(api, instruction["id"]),
        status=INSTRUCTION_REJECTED,
        snapshot_holder_count=None,
        snapshot_shares_total=None,
        version=2,
    )


def test_a_rejected_instruction_refuses_a_second_decision(api: ApiClient):
    """PRD §3.9: "Both branches require the instruction to still be in `SUBMITTED` — anything else is refused with `ERR_INSTRUCTION_ALREADY_DECIDED` — both are barred to the user recorded as `submitted_by_user_id` by `ERR_SEGREGATION_OF_DUTIES`, and both stamp the acting user as `acknowledged_by_user_id` and increment the instruction's `version` by 1."

    PRD §3.9: "The `REJECT` branch instead transitions the instruction `SUBMITTED` → `REJECTED`, requires a non-empty `rejection_reason` (otherwise `ERR_INVALID_REQUEST`) which it stores as `decision_reason`, and deliberately takes **no** snapshot at all: `snapshot_holder_count` and `snapshot_shares_total` stay null on a rejected instruction."

    Design: Corner/state_machines/instruction_rejection_skips_the_snapshot_and_locks_the_decision
    """
    _company, _holder, instruction = _submitted_record_inquiry(api)
    fixtures.acknowledge_instruction(
        api,
        instruction["id"],
        decision=ACK_DECISION_REJECT,
        rejection_reason=REJECTION_REASON,
        headers=TRANSFER_AGENT,
    )

    # A second liaison, so segregation of duties cannot be the reason for the refusal.
    validate_error(
        api.acknowledge_instruction(
            instruction["id"],
            factories.acknowledge_payload(ACK_DECISION_ACKNOWLEDGE),
            TRANSFER_AGENT_2,
        ),
        ApiErrorId.INSTRUCTION_ALREADY_DECIDED.value,
    )

    assertions.assert_instruction(
        fixtures.read_instruction(api, instruction["id"]),
        status=INSTRUCTION_REJECTED,
        decision_reason=REJECTION_REASON,
        acknowledged_by_user_id=TRANSFER_AGENT_USER_ID,
        version=2,
    )


# ---------------------------------------------------------------------------
# Corner/state_machines/acknowledge_freezes_a_holder_only_record_date_snapshot
# ---------------------------------------------------------------------------


def _record_date_world(api: ApiClient):
    """A register of four contacts, only two of which qualify for the snapshot."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api, ticker="SNP", legal_name="Snapshot Register Corp", shares_outstanding=1000000
    )
    institutional = fixtures.create_holder(
        api,
        company["id"],
        shares_held=1000,
        display_name="Snapshot Institution",
        email="snp1@funds.test",
    )
    retail = fixtures.create_holder(
        api,
        company["id"],
        shares_held=500,
        display_name="Snapshot Retail",
        email="snp2@retail.test",
        contact_type=CONTACT_RETAIL_HOLDER,
    )
    analyst = fixtures.create_contact(
        api,
        company["id"],
        contact_type=CONTACT_SELL_SIDE_ANALYST,
        display_name="Snapshot Analyst",
        email="snp3@bank.test",
        shares_held=2000,
        nda_on_file=True,
        coverage_status=COVERAGE_INITIATED,
    )
    empty_holder = fixtures.create_holder(
        api,
        company["id"],
        shares_held=0,
        display_name="Snapshot Zero Holder",
        email="snp4@funds.test",
    )
    instruction = fixtures.create_instruction(
        api,
        company["id"],
        instruction_type=INSTRUCTION_RECORD_DATE_SET,
        record_date="2026-08-15",
    )
    return company, [institutional, retail, analyst, empty_holder], instruction


def test_acknowledge_snapshots_only_share_holding_holders(api: ApiClient):
    """PRD §3.9: "The `ACKNOWLEDGE` branch transitions the instruction `SUBMITTED` → `ACKNOWLEDGED` and freezes the record-date position."

    PRD §3.9: "The snapshot counts the issuer's contacts whose `contact_type` is `INSTITUTIONAL_HOLDER` or `RETAIL_HOLDER` and whose `shares_held` is strictly greater than zero, writing that count to `snapshot_holder_count`, and sums those same rows' `shares_held` into `snapshot_shares_total`."

    PRD §3.9: "Analyst rows are excluded even when they happen to hold shares, and holders sitting at exactly zero shares are excluded because the boundary is strict."

    PRD §3.9: "Both branches require the instruction to still be in `SUBMITTED` — anything else is refused with `ERR_INSTRUCTION_ALREADY_DECIDED` — both are barred to the user recorded as `submitted_by_user_id` by `ERR_SEGREGATION_OF_DUTIES`, and both stamp the acting user as `acknowledged_by_user_id` and increment the instruction's `version` by 1."

    Design: Corner/state_machines/acknowledge_freezes_a_holder_only_record_date_snapshot
    """
    _company, contacts, instruction = _record_date_world(api)

    acknowledged = validate_success(
        api.acknowledge_instruction(
            instruction["id"],
            factories.acknowledge_payload(ACK_DECISION_ACKNOWLEDGE),
            TRANSFER_AGENT,
        )
    )
    # 1000 institutional + 500 retail; the analyst's 2000 and the zero-share
    # holder are both outside the snapshot.
    assertions.assert_instruction(
        acknowledged,
        status=INSTRUCTION_ACKNOWLEDGED,
        snapshot_holder_count=2,
        snapshot_shares_total=1500,
        acknowledged_by_user_id=TRANSFER_AGENT_USER_ID,
        decision_reason=None,
        version=2,
    )
    assertions.assert_snapshot_excludes_analysts(acknowledged, contacts)


def test_acknowledged_record_date_set_has_no_payout_step(api: ApiClient):
    """PRD §3.9: "The `instruction_type` must be `DIVIDEND_PAYMENT`, or it is refused with `ERR_INSTRUCTION_TYPE_NOT_PAYABLE` — a `RECORD_DATE_SET` or `RECORD_INQUIRY` instruction is complete at `ACKNOWLEDGED` and has no payout step at all."

    PRD §3.9: "A new instruction is born in `SUBMITTED` with `acknowledged_by_user_id`, `executed_by_user_id`, `snapshot_holder_count`, `snapshot_shares_total`, `payout_ledger`, `total_payout_cents`, `executed_at` and `decision_reason` all null, and `version` at 1."

    PRD §3.1: "`dividend_reserve_cents` is the cash, in whole cents, available to fund dividend execution; when omitted it starts at zero, and it may never be negative."

    PRD §3.1: "Registration also stamps the derived fields: `disclosure_posture` is derived immediately and `posture_recomputed_at` is stamped with the logical clock, `open_inquiry_count` and `dividend_paid_cents` both begin at zero, and `version` begins at 1."

    Design: Corner/state_machines/acknowledge_freezes_a_holder_only_record_date_snapshot
    """
    company, _contacts, instruction = _record_date_world(api)
    fixtures.acknowledge_instruction(
        api, instruction["id"], decision=ACK_DECISION_ACKNOWLEDGE, headers=TRANSFER_AGENT
    )

    reread = fixtures.read_instruction(api, instruction["id"])
    assertions.assert_instruction(
        reread,
        status=INSTRUCTION_ACKNOWLEDGED,
        payout_ledger=None,
        total_payout_cents=None,
        executed_at=None,
        executed_by_user_id=None,
        version=2,
    )

    # Acknowledgement freezes a position; it moves no cash.
    assertions.assert_company(
        fixtures.read_company(api, company["id"]),
        dividend_reserve_cents=0,
        dividend_paid_cents=0,
    )
