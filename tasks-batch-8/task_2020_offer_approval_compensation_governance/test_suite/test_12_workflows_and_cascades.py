"""Workflows: counter re-approval cycle, rejection cascade, clearance gates."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_candidate_headers, event_types,
    create_open_requisition, create_candidate_recruited, create_standard_peers,
    create_peer_snapshots, setup_exception_policy_rows, create_accepted_offer,
    create_extended_offer, create_offer_with_perks, create_hired_offer,
    submit_offer_and_get_steps, approve_chain,
)

HM = TEST_USERS["hm_headers"]
REC = TEST_USERS["recruiter_headers"]
CA = TEST_USERS["comp_analyst_headers"]
DIR = TEST_USERS["director_headers"]
VP = TEST_USERS["vp_headers"]
SCR = TEST_USERS["screener_headers"]


def _counter_reapproval_setup(api):
    setup_exception_policy_rows()
    req = create_open_requisition(HM, annual_budget_cents=80000000)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand H")
    offer = create_extended_offer(req, cand, REC, base_cents=20000000)
    # capture the first (GENERATED) letter
    letters = validate_success(api.list_offer_letters(offer["id"], REC))
    letter1 = letters[0]
    return req, cand, offer, letter1


def test_counter_accept_with_new_role_reroutes_to_pending_approval(api):
    """PRD §3.7: "If the recomputed chain introduces a role the approved chain
    lacked, the offer returns to `PENDING_APPROVAL` and a fresh chain is
    generated — the old chain, fully decided, is left in place for audit rather
    than superseded."

    Design: Difficulty/non_linear_state_machine/offer_counter_reapproval_cycle
    """
    req, cand, offer, letter1 = _counter_reapproval_setup(api)
    current = validate_success(api.get_offer(offer["id"], REC))
    # 24000000 is EXCEPTION band and 20% over the 20000000 anchor: only VP's cap covers it
    rnd = get_success_data(api.create_negotiation_round(
        offer["id"], {"expected_offer_version": current["version"], "proposed_base_cents": 24000000}, REC
    ))
    validate_success(api.decide_negotiation_round(rnd["id"], {"outcome": "ACCEPTED"}, VP))
    mid = validate_success(api.get_offer(offer["id"], REC))
    assert mid["status"] == "PENDING_APPROVAL"
    assert mid["base_cents"] == 24000000
    assert mid["band"] == "EXCEPTION"
    letters = validate_success(api.list_offer_letters(offer["id"], REC))
    l1 = [l for l in letters if l["id"] == letter1["id"]][0]
    assert l1["status"] == "SUPERSEDED"


def test_counter_reapproval_cycle_completes_back_to_extended(api):
    """PRD §3.7: "A successful acceptance marks the round `ACCEPTED`, applies
    the proposed base and any proposed bonus or equity to the offer, recomputes
    every computed field, increments the offer's `version`, supersedes any
    `GENERATED` letters with `LETTER_SUPERSEDED` events, recomputes the
    committed budget, and appends `COUNTER_ACCEPTED`."
    PRD §3.5: "Step zero is always the `HiringManager`."
    PRD §3.6: "Extension sets `expires_at` to the logical clock plus ten days".

    Design: Difficulty/non_linear_state_machine/offer_counter_reapproval_cycle
    """
    req, cand, offer, letter1 = _counter_reapproval_setup(api)
    current = validate_success(api.get_offer(offer["id"], REC))
    rnd = get_success_data(api.create_negotiation_round(
        offer["id"], {"expected_offer_version": current["version"], "proposed_base_cents": 24000000}, REC
    ))
    validate_success(api.decide_negotiation_round(rnd["id"], {"outcome": "ACCEPTED"}, VP))
    # fresh chain [HM, CompAnalyst, DepartmentDirector, VPPeople] — approve it in order
    steps = validate_success(api.list_approval_steps(offer["id"], REC))
    pending = sorted([s for s in steps if s["status"] in ("ACTIONABLE", "WAITING")],
                     key=lambda s: s["sequence"])
    role_headers = {"HiringManager": HM, "CompAnalyst": CA, "DepartmentDirector": DIR, "VPPeople": VP}
    assert [s["required_role"] for s in pending] == ["HiringManager", "CompAnalyst", "DepartmentDirector", "VPPeople"]
    # fresh chain sequences restart at 0 for the regenerated chain
    base_seq = pending[0]["sequence"]
    assert [s["sequence"] - base_seq for s in pending] == [0, 1, 2, 3]
    for s in pending:
        get_success_data(api.decide_approval_step(s["id"], {"decision": "APPROVED"}, role_headers[s["required_role"]]))
    approved = validate_success(api.get_offer(offer["id"], REC))
    assert approved["status"] == "APPROVED"
    # the cycle loops: letter again, extend again
    validate_success(api.create_offer_letter(offer["id"], REC), expected_status=201)
    extended = validate_success(api.extend_offer(offer["id"], REC))
    assert extended["status"] == "EXTENDED"
    assert extended["expires_at"] == "2026-08-11T00:00:00Z"


def _exception_offer_step0_approved(api):
    setup_exception_policy_rows()
    req = create_open_requisition(HM, title="Staff Eng", annual_budget_cents=80000000)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand J")
    offer, steps = submit_offer_and_get_steps(
        create_offer_with_perks(req, cand, [], REC, base_cents=24000000)[0], REC
    )
    assert len(steps) == 4
    get_success_data(api.decide_approval_step(steps[0]["id"], {"decision": "APPROVED"}, HM))
    return req, offer, steps


def test_step_rejection_returns_offer_and_supersedes_siblings(api):
    """PRD §3.5: "A rejection appends `STEP_REJECTED` and cascades: the offer
    drops `PENDING_APPROVAL → RETURNED`, every sibling step still `WAITING` or
    `ACTIONABLE` is superseded with a `STEP_SUPERSEDED` event apiece".

    Design: Difficulty/transitive_cascade/step_rejection_supersession_event_chain
    """
    req, offer, steps = _exception_offer_step0_approved(api)
    validate_success(
        api.decide_approval_step(steps[1]["id"], {"decision": "REJECTED", "note": "equity posture too hot"}, CA)
    )
    offer_after = validate_success(api.get_offer(offer["id"], REC))
    assert offer_after["status"] == "RETURNED"
    steps_after = sorted(validate_success(api.list_approval_steps(offer["id"], REC)),
                         key=lambda s: s["sequence"])
    assert [s["status"] for s in steps_after] == ["APPROVED", "REJECTED", "SUPERSEDED", "SUPERSEDED"]


def test_step_rejection_event_chain_and_budget_release(api):
    """PRD §3.5: "A rejection appends `STEP_REJECTED` and cascades: the offer
    drops `PENDING_APPROVAL → RETURNED`, every sibling step still `WAITING` or
    `ACTIONABLE` is superseded with a `STEP_SUPERSEDED` event apiece, `LOCKED`
    perks fall back to `DRAFT`, the requisition's committed budget releases the
    offer, and `RETURNED` closes the sequence."

    Design: Difficulty/transitive_cascade/step_rejection_supersession_event_chain
    """
    req, offer, steps = _exception_offer_step0_approved(api)
    validate_success(
        api.decide_approval_step(steps[1]["id"], {"decision": "REJECTED", "note": "equity posture too hot"}, CA)
    )
    types = event_types(validate_success(api.list_offer_events(offer["id"], REC)))
    assert types.count("STEP_REJECTED") == 1
    assert types.count("STEP_SUPERSEDED") == 2
    assert "RETURNED" in types
    assert types.index("STEP_REJECTED") < types.index("RETURNED")
    req_after = validate_success(api.get_requisition(req["id"], REC))
    assert req_after["committed_budget_cents"] == 0


def _accepted_offer_with_two_checks(api, perk_payloads=None):
    req = create_open_requisition(HM)
    create_standard_peers()
    cand = create_candidate_recruited(REC)
    if perk_payloads is not None:
        offer, perks = create_offer_with_perks(req, cand, perk_payloads, REC, base_cents=20000000)
        submitted, steps = submit_offer_and_get_steps(offer, REC)
        final = approve_chain(steps)
        get_success_data(api.create_offer_letter(final["id"], REC))
        get_success_data(api.extend_offer(final["id"], REC))
        offer = get_success_data(api.accept_offer(final["id"], make_candidate_headers(cand["id"])))
    else:
        offer = create_accepted_offer(req, cand, REC, base_cents=20000000)
        perks = []
    bg = get_success_data(api.create_clearance_check(offer["id"], {"kind": "BACKGROUND"}, SCR))
    ref = get_success_data(api.create_clearance_check(offer["id"], {"kind": "REFERENCE"}, SCR))
    return req, cand, offer, bg, ref, perks


def test_hire_gated_by_clearance_posture(api):
    """PRD §3.8: "The offer's `clearance_posture` aggregates its checks:
    `FAILED` if any check has failed; otherwise `NOT_STARTED` if no checks
    exist; otherwise `CLEARED` when every check is `CLEARED` or `WAIVED`;
    otherwise `PENDING`." and "A posture of `CLEARED` hires: the offer moves
    `ACCEPTED → HIRED`".

    Design: Difficulty/cross_entity_state_dependency/hire_gated_by_clearance_posture
    """
    req, cand, offer, bg, ref, _ = _accepted_offer_with_two_checks(api)
    get_success_data(api.transition_clearance_check(bg["id"], {"to": "IN_PROGRESS"}, SCR))
    get_success_data(api.transition_clearance_check(bg["id"], {"to": "CLEARED"}, SCR))
    mid = validate_success(api.get_offer(offer["id"], REC))
    assert mid["status"] == "ACCEPTED"
    assert mid["clearance_posture"] == "PENDING"
    get_success_data(api.transition_clearance_check(ref["id"], {"to": "IN_PROGRESS"}, SCR))
    get_success_data(api.transition_clearance_check(ref["id"], {"to": "CLEARED"}, SCR))
    final = validate_success(api.get_offer(offer["id"], REC))
    assert final["status"] == "HIRED"
    assert final["clearance_posture"] == "CLEARED"


def test_hire_flips_candidate_to_hired(api):
    """PRD §3.8: "A posture of `CLEARED` hires: the offer moves `ACCEPTED →
    HIRED`, `APPROVED` perks become `ACTIVE`, the candidate moves to `HIRED`".

    Design: Difficulty/cross_entity_state_dependency/hire_gated_by_clearance_posture
    """
    req, cand, offer, bg, ref, _ = _accepted_offer_with_two_checks(api)
    for chk in (bg, ref):
        get_success_data(api.transition_clearance_check(chk["id"], {"to": "IN_PROGRESS"}, SCR))
        get_success_data(api.transition_clearance_check(chk["id"], {"to": "CLEARED"}, SCR))
    cand_after = validate_success(api.get_candidate(cand["id"], REC))
    assert cand_after["status"] == "HIRED"


def test_clearance_flag_recheck_cycle(api):
    """PRD §3.8: "The declared edges are `INITIATED → IN_PROGRESS`,
    `IN_PROGRESS → CLEARED`, `IN_PROGRESS → FLAGGED`, `FLAGGED → IN_PROGRESS`
    (the re-check cycle), and `FLAGGED → FAILED`".

    Design: Difficulty/non_linear_state_machine/clearance_flag_recheck_cycle
    """
    req, cand, offer, bg, ref, _ = _accepted_offer_with_two_checks(api)
    get_success_data(api.transition_clearance_check(bg["id"], {"to": "IN_PROGRESS"}, SCR))
    flagged = get_success_data(api.transition_clearance_check(bg["id"], {"to": "FLAGGED"}, SCR))
    assert flagged["status"] == "FLAGGED"
    recheck = get_success_data(
        api.transition_clearance_check(bg["id"], {"to": "IN_PROGRESS", "note": "re-check after candidate dispute"}, SCR)
    )
    assert recheck["status"] == "IN_PROGRESS"
    cleared = get_success_data(api.transition_clearance_check(bg["id"], {"to": "CLEARED"}, SCR))
    assert cleared["status"] == "CLEARED"
    mid = validate_success(api.get_offer(offer["id"], REC))
    assert mid["status"] == "ACCEPTED"
    assert mid["clearance_posture"] == "PENDING"


def test_clearance_flag_recheck_cycle_completes_hire(api):
    """PRD §3.8: "otherwise `CLEARED` when every check is `CLEARED` or
    `WAIVED`; otherwise `PENDING`" — the offer hires only once BOTH checks are
    clear.
    PRD §3.1: "`headcount_filled`, the count of the requisition's offers in
    `HIRED` status" (via §2.8 standing aggregate).

    Design: Difficulty/non_linear_state_machine/clearance_flag_recheck_cycle
    """
    req, cand, offer, bg, ref, _ = _accepted_offer_with_two_checks(api)
    get_success_data(api.transition_clearance_check(bg["id"], {"to": "IN_PROGRESS"}, SCR))
    get_success_data(api.transition_clearance_check(bg["id"], {"to": "FLAGGED"}, SCR))
    get_success_data(api.transition_clearance_check(bg["id"], {"to": "IN_PROGRESS"}, SCR))
    get_success_data(api.transition_clearance_check(bg["id"], {"to": "CLEARED"}, SCR))
    get_success_data(api.transition_clearance_check(ref["id"], {"to": "IN_PROGRESS"}, SCR))
    get_success_data(api.transition_clearance_check(ref["id"], {"to": "CLEARED"}, SCR))
    final = validate_success(api.get_offer(offer["id"], REC))
    assert final["status"] == "HIRED"
    assert final["clearance_posture"] == "CLEARED"
    req_after = validate_success(api.get_requisition(req["id"], REC))
    assert req_after["headcount_filled"] == 1


def test_clearance_failure_auto_rescind_chain(api):
    """PRD §3.8: "A posture of `FAILED` rescinds: the offer moves `ACCEPTED →
    RESCINDED` with `rescind_reason` set to `CONTIGENCY_FAILED`, every in-flight
    check is cancelled, `APPROVED` perks are voided, the committed budget is
    released, and `RESCINDED` is appended with the failure as its `detail`."

    Design: Difficulty/transitive_cascade/clearance_failure_auto_rescind_chain
    """
    req, cand, offer, bg, ref, perks = _accepted_offer_with_two_checks(
        api, perk_payloads=[{"kind": "SIGN_ON", "amount_cents": 1000000, "clawback_months": 12,
                             "clawback_variant": "FULL_CLIFF"}]
    )
    get_success_data(api.transition_clearance_check(bg["id"], {"to": "IN_PROGRESS"}, SCR))
    get_success_data(api.transition_clearance_check(bg["id"], {"to": "FLAGGED"}, SCR))
    get_success_data(
        api.transition_clearance_check(bg["id"], {"to": "FAILED", "note": "criminal record confirmed"}, SCR)
    )
    final = validate_success(api.get_offer(offer["id"], REC))
    assert final["status"] == "RESCINDED"
    assert final["rescind_reason"] == "CONTIGENCY_FAILED"
    checks = {c["id"]: c for c in validate_success(api.list_clearance_checks(offer["id"], REC))}
    assert checks[ref["id"]]["status"] == "CANCELLED"
    perk_after = [p for p in validate_success(api.list_perks(offer["id"], REC)) if p["id"] == perks[0]["id"]][0]
    assert perk_after["status"] == "VOIDED"
    req_after = validate_success(api.get_requisition(req["id"], REC))
    assert req_after["committed_budget_cents"] == 0


def test_clearance_failure_event_ordering(api):
    """PRD §3.8: the FAILED transition "appends `CHECK_TRANSITIONED` and
    recomputes the offer's posture"; the failure cascade then "cancels every
    in-flight check" (CHECK_CANCELLED), voids perks (PERK_VOIDED), and appends
    `RESCINDED` with the failure as its `detail`.

    Design: Difficulty/transitive_cascade/clearance_failure_auto_rescind_chain
    """
    req, cand, offer, bg, ref, perks = _accepted_offer_with_two_checks(
        api, perk_payloads=[{"kind": "SIGN_ON", "amount_cents": 1000000, "clawback_months": 12,
                             "clawback_variant": "FULL_CLIFF"}]
    )
    get_success_data(api.transition_clearance_check(bg["id"], {"to": "IN_PROGRESS"}, SCR))
    get_success_data(api.transition_clearance_check(bg["id"], {"to": "FLAGGED"}, SCR))
    get_success_data(api.transition_clearance_check(bg["id"], {"to": "FAILED", "note": "confirmed"}, SCR))
    # This offer accumulates 16 events — beyond the PRD §2.3 default page of
    # 10 — so the full trail must be requested with an explicit limit.
    events = validate_success(api.list_offer_events(offer["id"], REC, params={"limit": 100}))
    types = event_types(events)
    fail_idx = len(types) - 1 - types[::-1].index("CHECK_TRANSITIONED")
    assert "RESCINDED" in types[fail_idx:]
    assert "CHECK_CANCELLED" in types[fail_idx:]
    assert "PERK_VOIDED" in types[fail_idx:]
    assert types.index("RESCINDED") > fail_idx
    assert types.index("CHECK_CANCELLED") > fail_idx
    assert types.index("PERK_VOIDED") > fail_idx


def test_hire_headcount_autoclose_withdrawal_chain(api):
    """PRD §3.1: "When a hire recomputation finds `headcount_filled` exactly
    equal to `headcount_authorized` on an `OPEN` requisition, the requisition
    closes itself: `OPEN → CLOSED`, with `CLOSED` recording `close_reason` as
    `FILLED` and the auto-withdraw cascade firing with event detail
    `REQUISITION_FILLED`."
    PRD §3.9: "Every offer of that requisition in `DRAFT`, `RETURNED`,
    `PENDING_APPROVAL`, `APPROVED`, `LETTER_GENERATED`, `EXTENDED`, or
    `COUNTERED` transitions to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/hire_headcount_autoclose_withdrawal_chain
    """
    req = create_open_requisition(HM, headcount_authorized=1)
    create_standard_peers()
    cand_a = create_candidate_recruited(REC, full_name="Cand L")
    offer_a = create_accepted_offer(req, cand_a, REC, base_cents=20000000)
    bg_a = get_success_data(api.create_clearance_check(offer_a["id"], {"kind": "BACKGROUND"}, SCR))
    ref_a = get_success_data(api.create_clearance_check(offer_a["id"], {"kind": "REFERENCE"}, SCR))
    # sibling offer B in PENDING_APPROVAL on the same requisition
    cand_b = create_candidate_recruited(REC, full_name="Cand M")
    from test_helpers import create_draft_offer
    offer_b = create_draft_offer(req, cand_b, REC, base_cents=18000000)
    submitted_b, steps_b = submit_offer_and_get_steps(offer_b, REC)
    # clear both checks -> offer A HIRED -> requisition CLOSED(FILLED) -> offer B withdrawn
    for chk in (bg_a, ref_a):
        get_success_data(api.transition_clearance_check(chk["id"], {"to": "IN_PROGRESS"}, SCR))
        get_success_data(api.transition_clearance_check(chk["id"], {"to": "CLEARED"}, SCR))
    a_after = validate_success(api.get_offer(offer_a["id"], REC))
    assert a_after["status"] == "HIRED"
    req_after = validate_success(api.get_requisition(req["id"], REC))
    assert req_after["headcount_filled"] == 1
    assert req_after["status"] == "CLOSED"
    assert req_after["close_reason"] == "FILLED"
    b_after = validate_success(api.get_offer(offer_b["id"], REC))
    assert b_after["status"] == "WITHDRAWN"


def test_hire_autoclose_supersedes_sibling_steps_and_recomputes_budget(api):
    """PRD §3.9: "For each such offer: every non-terminal ApprovalStep becomes
    `SUPERSEDED` with a `STEP_SUPERSEDED` event ... and the offer's own
    `WITHDRAWN` event carries `detail` of `REQUISITION_FILLED` ... The
    requisition's `committed_budget_cents` is then recomputed."
    PRD §3.9: "Note what the cascade deliberately spares: offers already
    `ACCEPTED` or `HIRED` are left standing".

    Design: Difficulty/transitive_cascade/hire_headcount_autoclose_withdrawal_chain
    """
    req = create_open_requisition(HM, headcount_authorized=1)
    create_standard_peers()
    cand_a = create_candidate_recruited(REC, full_name="Cand L")
    offer_a = create_accepted_offer(req, cand_a, REC, base_cents=20000000)
    bg_a = get_success_data(api.create_clearance_check(offer_a["id"], {"kind": "BACKGROUND"}, SCR))
    ref_a = get_success_data(api.create_clearance_check(offer_a["id"], {"kind": "REFERENCE"}, SCR))
    cand_b = create_candidate_recruited(REC, full_name="Cand M")
    from test_helpers import create_draft_offer
    offer_b = create_draft_offer(req, cand_b, REC, base_cents=18000000)
    submitted_b, steps_b = submit_offer_and_get_steps(offer_b, REC)
    for chk in (bg_a, ref_a):
        get_success_data(api.transition_clearance_check(chk["id"], {"to": "IN_PROGRESS"}, SCR))
        get_success_data(api.transition_clearance_check(chk["id"], {"to": "CLEARED"}, SCR))
    steps_b_after = validate_success(api.list_approval_steps(offer_b["id"], REC))
    assert all(s["status"] == "SUPERSEDED" for s in steps_b_after)
    b_events = validate_success(api.list_offer_events(offer_b["id"], REC))
    withdrawn_events = [e for e in b_events if e["event_type"] == "WITHDRAWN"]
    assert len(withdrawn_events) == 1
    assert withdrawn_events[0]["detail"] == "REQUISITION_FILLED"
    assert "STEP_SUPERSEDED" in event_types(b_events)
    # only the HIRED offer remains counted: 26000000
    req_after = validate_success(api.get_requisition(req["id"], REC))
    assert req_after["committed_budget_cents"] == 26000000


def test_hire_reneg_headcount_conservation(api):
    """PRD §3.9: "From `HIRED`, `ACTIVE` perks are voided, `headcount_filled`
    is recomputed downward, a requisition that had closed `FILLED` reopens
    `CLOSED → OPEN` with `close_reason` cleared, the candidate returns `HIRED →
    IN_PROCESS`, and the committed budget is released."
    PRD §3.4: "a hire activates `APPROVED` perks to `ACTIVE`."

    Design: Difficulty/compensating_invariant/hire_reneg_headcount_conservation
    """
    req = create_open_requisition(HM, headcount_authorized=1)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand X")
    offer, perks = create_hired_offer(
        req, cand, REC,
        perk_payloads=[{"kind": "SIGN_ON", "amount_cents": 1000000, "clawback_months": 12,
                        "clawback_variant": "PRORATED_MONTHLY"}],
        base_cents=20000000,
    )
    req_pre = validate_success(api.get_requisition(req["id"], REC))
    assert req_pre["headcount_filled"] == 1
    assert req_pre["status"] == "CLOSED"
    assert req_pre["close_reason"] == "FILLED"
    perk_pre = validate_success(api.list_perks(offer["id"], REC))[0]
    assert perk_pre["status"] == "ACTIVE"
    # reneg rescind
    rescinded = validate_success(api.rescind_offer(offer["id"], {"reason": "RENEG"}, TEST_USERS["hr_admin_headers"]))
    assert rescinded["status"] == "RESCINDED"
    assert rescinded["rescind_reason"] == "RENEG"
    req_post = validate_success(api.get_requisition(req["id"], REC))
    assert req_post["headcount_filled"] == 0
    assert req_post["status"] == "OPEN"
    assert req_post["close_reason"] is None
    perk_post = validate_success(api.list_perks(offer["id"], REC))[0]
    assert perk_post["status"] == "VOIDED"
    cand_after = validate_success(api.get_candidate(cand["id"], REC))
    assert cand_after["status"] == "IN_PROCESS"


def test_hire_reneg_restores_headcount_invariant(api):
    """PRD §2.8: "`headcount_filled`, the count of the requisition's offers in
    `HIRED` status, recomputed whenever an offer enters or leaves `HIRED`" —
    the aggregate is derived, so after the reneg it must equal the count of
    remaining HIRED offers (zero) exactly.

    Design: Difficulty/compensating_invariant/hire_reneg_headcount_conservation
    """
    req = create_open_requisition(HM, headcount_authorized=1)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand X2")
    offer, _ = create_hired_offer(req, cand, REC, base_cents=20000000)
    validate_success(api.rescind_offer(offer["id"], {"reason": "RENEG"}, TEST_USERS["hr_admin_headers"]))
    req_post = validate_success(api.get_requisition(req["id"], REC))
    assert req_post["headcount_filled"] == 0
    assert req_post["status"] == "OPEN"
    assert req_post["close_reason"] is None
    offer_after = validate_success(api.get_offer(offer["id"], REC))
    assert offer_after["status"] == "RESCINDED"
    assert offer_after["rescind_reason"] == "RENEG"


def test_withdraw_from_extended_returns_invalid_offer_state(api):
    """PRD §3.9: "Withdrawal is the gentler, desk-side exit, available to a
    `Recruiter` or `HiringManager` while the offer is in `DRAFT`, `RETURNED`,
    or `PENDING_APPROVAL` ... Attempting to withdraw from any later status
    fails with `ERR_INVALID_OFFER_STATE`."

    Design: Corner/state_machines/withdraw_from_extended_returns_invalid_offer_state
    """
    req = create_open_requisition(HM)
    create_peer_snapshots("L5", "T1", [17000000, 18000000, 19000000])
    cand = create_candidate_recruited(REC, full_name="Cand WD")
    offer = create_extended_offer(req, cand, REC, base_cents=18000000)
    resp = api.withdraw_offer(offer["id"], {"reason": "try late withdraw"}, REC)
    validate_error(resp, ApiErrorId.ERR_INVALID_OFFER_STATE)
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["status"] == "EXTENDED"
    req_after = validate_success(api.get_requisition(req["id"], REC))
    assert req_after["committed_budget_cents"] == 23400000
