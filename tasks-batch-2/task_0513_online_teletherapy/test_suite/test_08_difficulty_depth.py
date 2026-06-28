"""Second-angle assertions for every difficulty instance.

Each difficulty instance is covered by a primary test elsewhere in the suite
and a complementary test here that pins a different observable consequence of
the same rule — every assertion still traces verbatim to PRD prose.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, cleared_client, accepting_therapist, propose_match, accept_match,
    create_client, submit_intake, get_client, get_therapist,
    create_subscription, charge_cycle, subscription_with_paid_cycle,
    approve_financial_aid, paused_subscription, get_subscription,
    cancel_scheduled_subscription, get_match, get_match_version, get_thread,
    raise_escalation, acknowledge_escalation,
    active_match, active_match_with_credits, schedule_session, count_credits,
    completed_session_in_window, draft_superbill, get_subscription_version,
    api_client, make_client_headers, make_therapist_headers,
)
from test_helpers import TEST_USERS


def _client(cid):
    return make_client_headers(cid)


def _therapist(tid):
    return make_therapist_headers(tid)


def _clinical():
    return TEST_USERS["clinical_admin_headers"]


def _billing():
    return TEST_USERS["billing_admin_headers"]


# ==========================================================================
# dual_variant_calc / pause_refund_forward_looking_on_subscription
# Second angle: subscription itself reaches PAUSED with pause_resumes_on set.
# ==========================================================================
def test_pause_records_resume_instant_and_paused_status(api):
    """PRD §3.7: "Pausing moves the subscription to `PAUSED`, records `pause_resumes_on` as the
    supplied resume instant, computes a prorated refund credited to the wallet, and expires the
    current period's `AVAILABLE` credits by moving them to `EXPIRED`; the subscription's `version`
    increments."

    Design: Difficulty/dual_variant_calc/pause_refund_forward_looking_on_subscription
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"])
    charge_cycle(sub["id"])
    set_clock("2026-06-04T00:00:00Z")
    paused = paused_subscription(client["id"], sub["id"], "2026-07-01T00:00:00Z")
    assert paused["status"] == "PAUSED", paused
    assert paused["pause_resumes_on"] == "2026-07-01T00:00:00Z", paused


# ==========================================================================
# dual_variant_calc / superbill_service_value_basis_on_superbill
# Second angle: a draft superbill computes session_count over the window.
# ==========================================================================
def test_superbill_session_count_over_window(api):
    """PRD §3.9: "The system gathers every `LiveSession` whose match belongs to this client, whose
    status is `COMPLETED`, and whose `starts_at` falls within the half-open window (at or after
    `period_start` and strictly before `period_end`) ... The `session_count` is the number of such
    sessions."

    Design: Difficulty/dual_variant_calc/superbill_service_value_basis_on_superbill
    """
    set_clock("2026-06-01T00:00:00Z")
    info = completed_session_in_window(
        state_code="CA", weekly_credit_grant=1,
        session_start="2026-06-02T10:00:00Z", session_end="2026-06-02T11:00:00Z",
    )
    sb = draft_superbill(info["client"]["id"], "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    issued = validate_success(api.issue_superbill(sb["id"], _billing()))
    assert issued["session_count"] == 1, issued


# ==========================================================================
# combinatorial_formula / match_score_three_input_nonlinear_mode_a
# Second angle: severity-only contribution with no specialty overlap.
# ==========================================================================
def test_match_score_severity_and_license_only(api):
    """PRD §3.3: "it adds 10 points for each specialty the therapist shares with the client (the
    size of the intersection between the intake's `presenting_concerns` and the therapist's
    `specialties`), plus 25 points if the therapist holds a `VALID` license covering the client's
    `state_code` and 0 otherwise, plus 2 points for each unit of the intake's `severity_score`."

    Design: Difficulty/combinatorial_formula/match_score_three_input_nonlinear_mode_a
    """
    set_clock("2026-06-01T00:00:00Z")
    # No specialty overlap (client GRIEF vs therapist ANXIETY); CA license; severity 4.
    client = cleared_client(state_code="CA", severity_score=4, presenting_concerns=["GRIEF"])
    therapist = accepting_therapist(state_code="CA", specialties=["ANXIETY"])
    match = propose_match(client["id"], therapist["id"])
    # overlap 0 -> 0; license 25; severity 4 -> 8; total 33.
    assert match["match_score"] == 33, match


# ==========================================================================
# combinatorial_formula / cycle_billing_pinned_eval_order_mode_c
# Second angle: NONE-tier first cycle charges the full base (no discount, no wallet).
# ==========================================================================
def test_first_cycle_no_aid_charges_full_base(api):
    """PRD §3.6: "The `list_amount_cents` is the `base_weekly_fee_cents` reduced by the
    financial-aid discount and rounded half-up to whole cents, where the discount fraction is 0 for
    `NONE`, 0.20 for `TIER_1`, 0.40 for `TIER_2`, and 0.60 for `TIER_3` based on the client's
    current `financial_aid_tier`."
    PRD §3.6: "The `charged_amount_cents` is the `list_amount_cents` minus the
    `wallet_applied_cents`."

    Design: Difficulty/combinatorial_formula/cycle_billing_pinned_eval_order_mode_c
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"], base_weekly_fee_cents=9900)
    cycle = validate_success(api.charge_cycle(sub["id"], _billing()), 201)
    # NONE tier: list = 9900; wallet 0; charged 9900.
    assert cycle["list_amount_cents"] == 9900, cycle
    assert cycle["wallet_applied_cents"] == 0, cycle
    assert cycle["charged_amount_cents"] == 9900, cycle


# ==========================================================================
# non_linear_state_machine / match_reassignment_cycle
# Second angle: the successor gets a fresh OPEN thread and the new therapist's caseload rises.
# ==========================================================================
def test_reassignment_successor_thread_open_and_caseload_moves(api):
    """PRD §3.4: "It creates a successor `Match` in `ACTIVE` for the selected new therapist — and
    that successor's own activation side effects fire, incrementing the new therapist's
    `active_caseload` (possibly bubbling them to `FULL`) and creating a fresh `OPEN` message
    thread."

    Design: Difficulty/non_linear_state_machine/match_reassignment_cycle
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    ta = accepting_therapist(state_code="CA", full_name="T A")
    tb = accepting_therapist(state_code="CA", full_name="T B")
    proposed = propose_match(client["id"], ta["id"])
    match = accept_match(proposed["id"], client["id"])
    validate_success(api.request_switch(
        match["id"], {"switch_reason": "FIT"}, _client(client["id"])
    ))
    successor = validate_success(api.reassign_match(match["id"], _clinical()), 201)
    succ_thread = get_thread(successor["id"], client["id"])
    assert succ_thread["status"] == "OPEN", succ_thread
    tb_after = get_therapist(tb["id"])
    assert tb_after["active_caseload"] == 1, tb_after


# ==========================================================================
# non_linear_state_machine / subscription_pause_resume_cycle
# Second angle: resume resets current_period_start to the current clock.
# ==========================================================================
def test_resume_resets_current_period_start_to_clock(api):
    """PRD §3.7: "Resuming clears `pause_resumes_on` back to null and resets `current_period_start`
    to the current clock; the subscription's `version` increments."

    Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"])
    charge_cycle(sub["id"])
    set_clock("2026-06-02T00:00:00Z")
    paused_subscription(client["id"], sub["id"], "2026-07-01T00:00:00Z")
    set_clock("2026-06-03T00:00:00Z")
    resumed = validate_success(api.resume_subscription(sub["id"], _client(client["id"])))
    assert resumed["current_period_start"] == "2026-06-03T00:00:00Z", resumed


# ==========================================================================
# transitive_cascade / finalize_cancel_subscription_client_match_caseload_depth4
# Second angle: the client's credits are expired by the close cascade.
# ==========================================================================
def test_finalize_cancel_expires_client_credits(api):
    """PRD §3.7: "a client in `ACTIVE` or `SUSPENDED` with no other non-terminal subscription
    moves to `CLOSED`, which in turn ends all of the client's `ACTIVE` matches (moving them to
    `ENDED`), expires all of the client's `AVAILABLE` or `RESERVED` credits (moving them to
    `EXPIRED`), and archives all of the client's `OPEN` or `FROZEN` message threads (moving them to
    `ARCHIVED`)."

    Design: Difficulty/transitive_cascade/finalize_cancel_subscription_client_match_caseload_depth4
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    therapist = accepting_therapist(state_code="CA")
    proposed = propose_match(client["id"], therapist["id"])
    accept_match(proposed["id"], client["id"])
    sub = create_subscription(client["id"], weekly_credit_grant=1)
    charge_cycle(sub["id"])  # grants 1 AVAILABLE credit
    cancel_scheduled_subscription(client["id"], sub["id"])
    # PRD §2.10: advancing the clock to cancel_effective_on auto-finalizes the
    # CANCEL_SCHEDULED subscription to CANCELLED, firing the close cascade.
    set_clock("2026-06-08T00:00:00Z")
    finalized = get_subscription(sub["id"], client["id"])
    assert finalized["status"] == "CANCELLED", finalized
    assert count_credits(client["id"], "AVAILABLE") == 0, "AVAILABLE credits should be expired"
    assert count_credits(client["id"], "EXPIRED") == 1, "credit should be EXPIRED by close cascade"


# ==========================================================================
# transitive_cascade / acute_resolve_escalation_client_thread_depth3
# Second angle: the escalation itself reaches RESOLVED through ACKNOWLEDGED.
# ==========================================================================
def test_escalation_resolves_through_acknowledged(api):
    """PRD §3.8: "A `ClinicalAdmin` works an escalation forward: acknowledging moves it from
    `OPEN` to `ACKNOWLEDGED`, and resolving moves it from `ACKNOWLEDGED` to `RESOLVED`; each step
    increments the escalation's `version`."

    Design: Difficulty/transitive_cascade/acute_resolve_escalation_client_thread_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    therapist = accepting_therapist(state_code="CA")
    proposed = propose_match(client["id"], therapist["id"])
    accept_match(proposed["id"], client["id"])
    esc = raise_escalation(client["id"], severity="ACUTE")
    acked = acknowledge_escalation(esc["id"])
    assert acked["status"] == "ACKNOWLEDGED", acked
    resolved = validate_success(api.resolve_escalation(esc["id"], _clinical()))
    assert resolved["status"] == "RESOLVED", resolved


# ==========================================================================
# priority_pair_validation_conflict / state_vs_safety_accept_acute_already_active
# Second angle: a fresh PROPOSED match for the same ACUTE client is blocked by risk, not state.
# ==========================================================================
def test_accept_proposed_match_acute_client_blocked_by_risk(api):
    """PRD §3.3: "An attempt to accept while the client's risk posture is `ACUTE` is rejected with
    `ERR_CLIENT_RISK_BLOCKED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_accept_acute_already_active
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    therapist = accepting_therapist(state_code="CA", max_active_caseload=5)
    proposed = propose_match(client["id"], therapist["id"])
    # Client becomes ACUTE while this match is still validly PROPOSED -> only risk can fire.
    raise_escalation(client["id"], severity="ACUTE", as_clinical=True)
    resp = api.accept_match(proposed["id"], _client(client["id"]))
    validate_error(resp, ApiErrorId.ERR_CLIENT_RISK_BLOCKED.value)


# ==========================================================================
# priority_pair_validation_conflict / safety_vs_referential_intake_uncleared_and_unlicensed
# Second angle: uncleared client to a properly-licensed therapist still blocks on intake gate.
# ==========================================================================
def test_propose_uncleared_client_blocked_by_intake_gate(api):
    """PRD §3.3: "Proposal is blocked by the intake safety gate described in §3.1, surfacing
    `ERR_INTAKE_NOT_CLEARED` for an uncleared at-risk client"
    PRD §3.1: "Should a proposal be attempted for a client whose intake severity is at least 8 or
    whose crisis indicator is true and who has not been cleared, the proposal is rejected with
    `ERR_INTAKE_NOT_CLEARED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_intake_uncleared_and_unlicensed
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=9)  # uncleared gate, stays PENDING_INTAKE
    therapist = accepting_therapist(state_code="CA")  # properly licensed for CA
    resp = api.create_match(
        {"client_id": client["id"], "therapist_id": therapist["id"]}, _clinical()
    )
    validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_CLEARED.value)


# ==========================================================================
# boundary_precision_check / renewal_cycle_due_exactly_at_seven_days
# Second angle: a renewal one second before +7 days is rejected (X-1 boundary).
# ==========================================================================
def test_renewal_one_second_before_boundary_rejected(api):
    """PRD §3.6: "a renewal is only due once the clock has reached or passed `current_period_start`
    plus 7 days, and a premature renewal is rejected with `ERR_CYCLE_NOT_DUE` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/renewal_cycle_due_exactly_at_seven_days
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"])
    charge_cycle(sub["id"])  # current_period_start = 2026-06-01
    set_clock("2026-06-07T23:59:59Z")  # one second before +7 days
    resp = api.charge_cycle(sub["id"], _billing())
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_DUE.value)


# ==========================================================================
# boundary_precision_check / financial_aid_band_exactly_at_ceiling_falls_to_next_band
# Second angle: one cent below the TIER_2 ceiling lands in the more-generous TIER_2 band.
# ==========================================================================
def test_aid_one_cent_below_ceiling_awards_more_generous_band(api):
    """PRD §3.6: "an adjusted income exactly equal to a ceiling falls into the next-less-generous
    band: an adjusted income below $25,000 (2,500,000 cents) awards `TIER_3`; otherwise an
    adjusted income below $40,000 (4,000,000 cents) awards `TIER_2`; otherwise an adjusted income
    below $60,000 (6,000,000 cents) awards `TIER_1`; and any adjusted income of $60,000 or more
    awards `NONE`."

    Design: Difficulty/boundary_precision_check/financial_aid_band_exactly_at_ceiling_falls_to_next_band
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    # adjusted_income = 3,999,999 (household 1) < 4,000,000 -> TIER_2 (one cent below the ceiling).
    app = approve_financial_aid(client["id"], annual_income_cents=3_999_999, household_size=1)
    assert app["awarded_tier"] == "TIER_2", app


# ==========================================================================
# cross_entity_state_dependency / match_accept_blocked_by_therapist_full_pair_match_therapist
# Second angle: the first acceptance succeeds and drives caseload to the cap.
# ==========================================================================
def test_first_accept_at_cap_drives_caseload_to_max(api):
    """PRD §3.3: "Acceptance fires a cascade: the match becomes `ACTIVE`, the therapist's
    `active_caseload` increases by one (which may bubble that therapist from `ACCEPTING` to
    `FULL`)"

    Design: Difficulty/cross_entity_state_dependency/match_accept_blocked_by_therapist_full_pair_match_therapist
    """
    set_clock("2026-06-01T00:00:00Z")
    therapist = accepting_therapist(state_code="CA", max_active_caseload=1)
    client = cleared_client(state_code="CA")
    proposed = propose_match(client["id"], therapist["id"])
    match = accept_match(proposed["id"], client["id"])
    assert match["status"] == "ACTIVE", match
    t_after = get_therapist(therapist["id"])
    assert t_after["active_caseload"] == 1, t_after


# ==========================================================================
# cross_entity_state_dependency / message_post_blocked_by_thread_frozen_pair_message_thread
# Second angle: posting to an OPEN thread succeeds, proving the gate is thread-state driven.
# ==========================================================================
def test_post_to_open_thread_succeeds(api):
    """PRD §3.4: "Messages may be posted only to a thread that is `OPEN`; posting to a `FROZEN` or
    `ARCHIVED` thread is rejected with `ERR_THREAD_NOT_OPEN` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/message_post_blocked_by_thread_frozen_pair_message_thread
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    therapist = accepting_therapist(state_code="CA")
    proposed = propose_match(client["id"], therapist["id"])
    match = accept_match(proposed["id"], client["id"])
    thread = get_thread(match["id"], client["id"])
    msg = validate_success(api.post_message(
        thread["id"], {"body": "hello"}, _client(client["id"])
    ), 201)
    assert msg["sender_role"] == "CLIENT", msg


# ==========================================================================
# resource_temporal_overlap / same_match_overlap_closed_adjacency_allowed
# Second angle: a wholly-contained later window on the same match is rejected as overlap.
# ==========================================================================
def test_same_match_contained_interval_rejected(api):
    """PRD §3.5: "two sessions conflict when their half-open time intervals
    `[starts_at, ends_at)` intersect, though touching end-to-start (one session's end exactly equal
    to the next's start) is allowed; an overlap is rejected with `ERR_SESSION_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/same_match_overlap_closed_adjacency_allowed
    """
    set_clock("2026-06-01T00:00:00Z")
    info = active_match_with_credits(state_code="CA", weekly_credit_grant=2)
    match_id = info["match"]["id"]
    client_id = info["client"]["id"]
    schedule_session(match_id, client_id, "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
    version = get_match_version(match_id)
    # 09:15-09:45 is fully inside the first session -> intervals intersect.
    resp = api.schedule_live_session(
        match_id,
        {"starts_at": "2026-06-02T09:15:00Z", "ends_at": "2026-06-02T09:45:00Z",
         "expected_match_version": version},
        _client(client_id),
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP.value)


# ==========================================================================
# resource_temporal_overlap / therapist_double_book_buffer_adjacency_rejected
# Second angle: a 15-minute gap (exactly the buffer) on a second client's match is allowed.
# ==========================================================================
def test_therapist_exact_buffer_gap_allowed(api):
    """PRD §3.5: "the new session must respect a 15-minute buffer against every other non-terminal
    session belonging to the same therapist across all of that therapist's matches — two of the
    therapist's sessions must be at least 15 minutes apart, so a gap of less than a quarter hour
    between them is rejected with `ERR_THERAPIST_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/therapist_double_book_buffer_adjacency_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    therapist = accepting_therapist(state_code="CA", max_active_caseload=5)
    client_a = cleared_client(state_code="CA")
    proposed_a = propose_match(client_a["id"], therapist["id"])
    match_a = accept_match(proposed_a["id"], client_a["id"])
    sub_a = create_subscription(client_a["id"])
    charge_cycle(sub_a["id"])
    schedule_session(match_a["id"], client_a["id"], "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
    client_b = cleared_client(state_code="CA")
    proposed_b = propose_match(client_b["id"], therapist["id"])
    match_b = accept_match(proposed_b["id"], client_b["id"])
    sub_b = create_subscription(client_b["id"])
    charge_cycle(sub_b["id"])
    version_b = get_match_version(match_b["id"])
    # 10:15 start is exactly 15 minutes after the 10:00 end -> >= 15 min apart -> allowed.
    ls = validate_success(api.schedule_live_session(
        match_b["id"],
        {"starts_at": "2026-06-02T10:15:00Z", "ends_at": "2026-06-02T11:00:00Z",
         "expected_match_version": version_b},
        _client(client_b["id"]),
    ), 201)
    assert ls["status"] == "SCHEDULED", ls


# ==========================================================================
# compensating_invariant / credit_count_conserved_on_schedule_then_cancel_outside_window
# Second angle: scheduling reserves the credit (RESERVED) before the cancel returns it.
# ==========================================================================
def test_schedule_reserves_the_credit(api):
    """PRD §3.5: "The act of scheduling reserves exactly one `AVAILABLE`, non-expired
    `SessionCredit` for the client by moving that credit to `RESERVED` and writing the new
    session's `id` onto the credit's `live_session_id`, and it increments the match's `version`."

    Design: Difficulty/compensating_invariant/credit_count_conserved_on_schedule_then_cancel_outside_window
    """
    set_clock("2026-06-01T00:00:00Z")
    info = active_match_with_credits(state_code="CA", weekly_credit_grant=1)
    match_id = info["match"]["id"]
    client_id = info["client"]["id"]
    schedule_session(match_id, client_id, "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    assert count_credits(client_id, "RESERVED") == 1, "credit should be RESERVED while scheduled"
    assert count_credits(client_id, "AVAILABLE") == 0, "no AVAILABLE credit while reserved"


# ==========================================================================
# compensating_invariant / wallet_cents_conserved_on_pause_refund_then_charge_debit
# Second angle: the same-day pause refund credits the full paid amount to the wallet first.
# ==========================================================================
def test_same_day_pause_credits_full_amount_to_wallet(api):
    """PRD §3.7: "a pause on the same day as the charge leaves all 7 days remaining and refunds
    the full paid amount"
    PRD §3.7: "The refund is forward-looking and credited to `wallet_credit_cents` rather than
    charged back to a card."

    Design: Difficulty/compensating_invariant/wallet_cents_conserved_on_pause_refund_then_charge_debit
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"], base_weekly_fee_cents=9900)
    charge_cycle(sub["id"])
    paused_subscription(client["id"], sub["id"], "2026-07-01T00:00:00Z")
    after = get_client(client["id"])
    assert after["wallet_credit_cents"] == 9900, after
