"""Corner-queue breadth: invalid transitions, precondition enforcement, terminal
lockdown, guarded transitions (cooling-off, milestone order, psych-clearance,
unfreeze block), auto-open escrow, parentage jurisdiction, milestone gate,
journey precondition, insufficient escrow, wrong-policy identify-gap, and the
OCC / derived-field cross-cutting instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    TEST_USERS,
    ApiErrorId,
    make_intended_parent_actor_headers,
    make_carrier_actor_headers,
    create_carrier_in_screening,
    create_psych_cleared_match,
    create_ip_signed_contract,
    create_active_journey,
    create_funded_journey,
    add_comp_schedule_line,
    add_milestone,
    add_and_achieve_milestone,
)
from test_helpers import factories as f

CM = TEST_USERS["case_manager_headers"]
SCREENER = TEST_USERS["screener_headers"]
FO = TEST_USERS["finance_officer_headers"]


# ==========================================================================
# State machines — invalid transitions & precondition enforcement
# ==========================================================================
def test_submit_intended_parent_from_screening_invalid_state(api):
    """PRD §3.1: "Submitting an intended parent advances `intake_status` from
    `DRAFT` to `SUBMITTED`". PRD §3.10: "State validity is then checked: a
    resource not in a valid state for the requested transition fails with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/submit_intended_parent_from_screening_invalid_state
    """
    ip = get_success_data(api.create_intended_parent(f.create_intended_parent_payload(), CM))
    get_success_data(api.submit_intended_parent(ip["id"], CM))
    get_success_data(api.start_screening_intended_parent(ip["id"], SCREENER))
    resp = api.submit_intended_parent(ip["id"], CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = validate_success(api.get_intended_parent(ip["id"], CM))
    assert refreshed["intake_status"] == "SCREENING"


def test_reject_terminal_rejected_carrier_invalid_state(api):
    """PRD §3.1: "A carrier in screening may instead be rejected, moving
    `SCREENING` to `REJECTED` (terminal), which requires the record to be in
    `SCREENING`."

    Design: Corner/state_machines/reject_from_terminal_rejected_carrier_invalid_state
    """
    car = create_carrier_in_screening(psych=None)
    get_success_data(api.reject_carrier(car["id"], SCREENER))  # SCREENING -> REJECTED
    resp = api.reject_carrier(car["id"], SCREENER)  # terminal
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_carrier_sign_before_cooling_off_rejected(api):
    """PRD §3.4: "The carrier, acting as `CarrierActor`, counter-signs to move
    `IP_SIGNED` to `EXECUTED`; this requires the contract to be `IP_SIGNED` and
    the current clock time to be at or after `ip_signed_at` plus
    `cooling_off_days`. A counter-signature attempted before that window has
    fully elapsed is rejected with `ERR_COOLING_OFF_ACTIVE`."

    Design: Corner/state_machines/carrier_sign_before_cooling_off_returns_cooling_off_active
    """
    ctx = create_ip_signed_contract()  # clock at startup 2026-05-01; ip_signed_at stamped there
    # Advance only 1 day — cooling-off (3 days) not elapsed.
    get_success_data(api.set_clock({"to_iso8601": "2026-05-02T00:00:00Z"}, CM))
    carrier_headers = make_carrier_actor_headers(ctx["carrier"]["id"])
    resp = api.carrier_sign_contract(ctx["contract"]["id"], carrier_headers)
    validate_error(resp, ApiErrorId.ERR_COOLING_OFF_ACTIVE.value)
    refreshed = validate_success(api.get_contract(ctx["contract"]["id"], CM))
    assert refreshed["status"] == "IP_SIGNED"


def test_milestone_heartbeat_before_transfer_order_violation(api):
    """PRD §3.6: "a `HEARTBEAT` milestone may be achieved only if this journey's
    `EMBRYO_TRANSFER` milestone is already `ACHIEVED` ... An out-of-order
    achievement is rejected with `ERR_MILESTONE_ORDER_VIOLATION`."

    Design: Corner/state_machines/milestone_heartbeat_before_transfer_order_violation
    """
    ctx = create_active_journey()
    jr_id = ctx["journey"]["id"]
    hb = add_milestone(jr_id, "HEARTBEAT", scheduled_utc="2026-05-20T00:00:00Z")
    resp = api.achieve_milestone(jr_id, hb["id"], CM)
    validate_error(resp, ApiErrorId.ERR_MILESTONE_ORDER_VIOLATION.value)
    refreshed = validate_success(api.list_milestones(jr_id, CM))
    hb_state = next(m for m in refreshed if m["id"] == hb["id"])
    assert hb_state["status"] == "SCHEDULED"


def test_match_accept_before_all_parties_cleared_psych_missing(api):
    """PRD §3.3: "Acceptance requires that the match currently be `PROPOSED`,
    that `expected_match_version` equal the current `version`, and that every
    party be cleared ... If any required party is not cleared, acceptance is
    rejected with `ERR_PSYCH_CLEARANCE_MISSING`."

    Design: Corner/state_machines/match_accept_before_all_parties_cleared_psych_missing
    """
    from test_helpers import create_cleared_intended_parent
    ip = create_cleared_intended_parent()
    car = create_carrier_in_screening(psych="PASSED")  # only SCREENING, not CLEARED
    match = get_success_data(api.create_match(
        f.create_match_payload(ip["id"], car["id"], proposed_carrier_comp_cents=4_000_000), CM))
    resp = api.accept_match(match["id"], {"expected_match_version": match["version"]}, CM)
    validate_error(resp, ApiErrorId.ERR_PSYCH_CLEARANCE_MISSING.value)
    refreshed = validate_success(api.get_match(match["id"], CM))
    assert refreshed["status"] == "PROPOSED"


def test_escrow_unfreeze_blocked_when_contract_void(api):
    """PRD §3.9: "Unfreezing moves a `FROZEN` account back to `OPEN`, but only if
    the account is `FROZEN` and the linked contract's status is not `VOID`; a
    frozen account whose contract has been voided cannot be reopened".

    Design: Corner/state_machines/escrow_unfreeze_blocked_when_contract_void
    """
    ctx = create_active_journey()
    get_success_data(api.void_match(ctx["match"]["id"], CM))  # cascades: contract VOID, escrow FROZEN
    resp = api.unfreeze_escrow(ctx["escrow"]["id"], FO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = validate_success(api.get_escrow_account(ctx["escrow"]["id"], FO))
    assert refreshed["status"] == "FROZEN"


def test_journey_auto_opens_escrow_on_create(api):
    """PRD §3.5: "Creating the journey puts it in `ACTIVE` status ... and — as an
    automatic cascade — opens a companion escrow account for this journey, in
    `OPEN` status ... The escrow account's `deposited_cents`, `disbursed_cents`,
    and `reserved_cents` all begin at 0, and its `available_cents` is therefore 0."

    Design: Corner/state_machines/journey_auto_opens_escrow_on_create
    """
    ctx = create_active_journey()
    escrow = validate_success(api.get_escrow_account(ctx["escrow"]["id"], FO))
    assert escrow["status"] == "OPEN"
    assert escrow["deposited_cents"] == 0
    assert escrow["available_cents"] == 0


# ==========================================================================
# Validations — parentage, milestone gate, journey precondition
# ==========================================================================
def test_parentage_file_hostile_state_blocked(api):
    """PRD §3.6: "Filing is blocked when the linked intended parent's
    `state_code` is a parentage-hostile jurisdiction — specifically `LA` or `NE`
    — because those states forbid pre-birth orders; an attempt in such a state
    is rejected with `ERR_PARENTAGE_JURISDICTION_BLOCKED`."

    Design: Corner/validations/parentage_file_hostile_state_blocked
    """
    ctx = create_active_journey(ip_state_code="NE")
    jr_id = ctx["journey"]["id"]
    resp = api.file_parentage(jr_id, CM)
    validate_error(resp, ApiErrorId.ERR_PARENTAGE_JURISDICTION_BLOCKED.value)
    refreshed = validate_success(api.get_journey(jr_id, CM))
    assert refreshed["parentage_order_status"] == "NOT_FILED"


def test_disbursement_approve_before_milestone_achieved_gate_not_met(api):
    """PRD §3.8: "Approval requires the disbursement to be `REQUESTED`, the
    schedule line's `trigger_milestone_type` to have a corresponding `ACHIEVED`
    milestone on this journey, and the escrow account to be `OPEN`. If the
    trigger milestone has not been achieved, approval is rejected with
    `ERR_MILESTONE_GATE_NOT_MET`."

    Design: Corner/validations/disbursement_approve_before_milestone_achieved_gate_not_met
    """
    ctx = create_funded_journey(deposit_cents=6_000_000)
    jr_id = ctx["journey"]["id"]
    schedule = add_comp_schedule_line(jr_id, "BIRTH", 3_000_000)  # no BIRTH milestone achieved
    disb = get_success_data(api.create_disbursement(
        jr_id, f.create_disbursement_payload(schedule["id"], ctx["escrow"]["id"]), CM))
    resp = api.approve_disbursement(jr_id, disb["id"], CM)
    validate_error(resp, ApiErrorId.ERR_MILESTONE_GATE_NOT_MET.value)
    refreshed_disb = validate_success(api.get_disbursement(disb["id"], FO))
    assert refreshed_disb["status"] == "REQUESTED"
    escrow = validate_success(api.get_escrow_account(ctx["escrow"]["id"], FO))
    assert escrow["reserved_cents"] == 0


def test_journey_create_from_non_executed_match_precondition(api):
    """PRD §3.5: "A journey may only be started from a match that is
    `PSYCH_CLEARED` and whose contract is `EXECUTED`; an attempt from a match
    that does not meet both conditions is rejected with `ERR_JOURNEY_PRECONDITION`."

    Design: Corner/validations/journey_create_from_non_executed_match_precondition
    """
    ctx = create_ip_signed_contract()  # contract IP_SIGNED (not EXECUTED)
    resp = api.create_journey(f.create_journey_payload(ctx["match"]["id"]), CM)
    validate_error(resp, ApiErrorId.ERR_JOURNEY_PRECONDITION.value)


def test_insufficient_escrow_at_approve_with_achieved_milestone(api):
    """PRD §3.8: "Approval also enforces fiscal sufficiency: the disbursement's
    `amount_cents` must be at or below the escrow account's `available_cents`; an
    amount exceeding available funds is rejected with `ERR_INSUFFICIENT_ESCROW`."

    Design: Corner/errors/insufficient_escrow_at_approve_with_achieved_milestone
    """
    ctx = create_funded_journey(deposit_cents=500_000)
    jr_id = ctx["journey"]["id"]
    schedule = add_comp_schedule_line(jr_id, "EMBRYO_TRANSFER", 1_000_000)
    add_and_achieve_milestone(jr_id, "EMBRYO_TRANSFER")
    disb = get_success_data(api.create_disbursement(
        jr_id, f.create_disbursement_payload(schedule["id"], ctx["escrow"]["id"]), CM))
    resp = api.approve_disbursement(jr_id, disb["id"], CM)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ESCROW.value)
    escrow = validate_success(api.get_escrow_account(ctx["escrow"]["id"], FO))
    assert escrow["reserved_cents"] == 0


# ==========================================================================
# Endpoints — conditional action
# ==========================================================================
def test_identify_gap_wrong_policy_kind_invalid_state(api):
    """PRD §3.2: "If `policy_kind` is `EXCLUSION`, the review may be moved from
    `PENDING` to `GAP_IDENTIFIED` ... Each outcome requires the review to
    currently be `PENDING` and its `policy_kind` to match the outcome as
    described."

    Design: Corner/endpoints/insurance_identify_gap_wrong_policy_kind_invalid_state
    """
    car = get_success_data(api.create_carrier(f.create_carrier_payload(), CM))
    ins = get_success_data(api.create_insurance_review(
        f.create_insurance_review_payload(car["id"], policy_kind="SURROGACY_FRIENDLY"), SCREENER))
    resp = api.identify_gap_insurance_review(ins["id"], SCREENER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = validate_success(api.get_insurance_review(ins["id"], SCREENER))
    assert refreshed["status"] == "PENDING"


# ==========================================================================
# Cross-cutting — OCC and derived-field reconciliation
# ==========================================================================
def test_match_accept_stale_version_occ_conflict(api):
    """PRD §2.7: "That request must carry `expected_match_version`, which must
    equal the target `Match`'s current `version`. If a counter or re-propose has
    advanced the match's `version` since the client last read it — changing the
    compensation being agreed to — the accept carries a stale value and is
    rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/match_accept_stale_version_occ_conflict
    """
    from test_helpers import create_cleared_intended_parent, create_cleared_carrier
    ip = create_cleared_intended_parent()
    car, _ = create_cleared_carrier()
    match = get_success_data(api.create_match(
        f.create_match_payload(ip["id"], car["id"], proposed_carrier_comp_cents=4_000_000), CM))
    stale_version = match["version"]
    countered = get_success_data(api.counter_match(
        match["id"], {"proposed_carrier_comp_cents": 4_500_000,
                      "expected_match_version": stale_version}, CM))
    get_success_data(api.re_propose_match(
        match["id"], {"proposed_carrier_comp_cents": 4_200_000,
                      "expected_match_version": countered["version"]}, CM))
    resp = api.accept_match(match["id"], {"expected_match_version": stale_version}, CM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    refreshed = validate_success(api.get_match(match["id"], CM))
    assert refreshed["status"] == "PROPOSED"


def test_escrow_deposit_stale_version_occ_conflict(api):
    """PRD §2.7: "That request must carry `expected_escrow_version`, which must
    equal the target `EscrowAccount`'s current `version`. If a prior deposit or a
    cascaded freeze has advanced the account's `version` since the client last
    read it, the deposit carries a stale value and is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/escrow_deposit_stale_version_occ_conflict
    """
    ctx = create_active_journey()
    escrow = ctx["escrow"]
    stale_version = escrow["version"]
    ip_headers = make_intended_parent_actor_headers(ctx["ip"]["id"])
    get_success_data(api.deposit_escrow(
        escrow["id"], f.deposit_payload(1_000_000, stale_version), ip_headers))
    resp = api.deposit_escrow(escrow["id"], f.deposit_payload(1_000_000, stale_version), ip_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    refreshed = validate_success(api.get_escrow_account(escrow["id"], FO))
    assert refreshed["deposited_cents"] == 1_000_000


def test_milestone_achieve_recomputes_current_phase(api):
    """PRD §3.6: "On achievement the system stamps `achieved_utc` with the
    current logical-clock time and recomputes the journey's `current_phase` from
    its achieved milestones — the phase advances along `PRE_TRANSFER`, then
    `TRANSFERRED` once `EMBRYO_TRANSFER` is achieved".

    Design: Corner/cross_cutting_complexity_layers/milestone_achieve_recomputes_current_phase_derived_field
    """
    ctx = create_active_journey()
    jr_id = ctx["journey"]["id"]
    ms = add_and_achieve_milestone(jr_id, "EMBRYO_TRANSFER")
    assert ms["status"] == "ACHIEVED"
    journey = validate_success(api.get_journey(jr_id, CM))
    assert journey["current_phase"] == "TRANSFERRED"
