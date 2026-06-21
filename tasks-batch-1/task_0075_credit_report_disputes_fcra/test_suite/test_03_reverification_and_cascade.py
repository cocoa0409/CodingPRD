"""Reverification responses, resolution cascades, reopen cycle, deadline sweep.

Translates queue A (Difficulty) non_linear_state_machine, transitive_cascade,
boundary_precision_check, compensating_invariant, and the suspended-furnisher
cross-entity dependency, plus queue B (Corner) reverification/reopen instances.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    make_bureau_headers, make_furnisher_headers, make_consumer_headers,
    find_notification,
    setup_reverifying_dispute, setup_investigating_dispute,
    setup_dispute_reopened_twice, setup_resolved_verify_dispute,
    set_clock, get_file_version, create_tradeline, file_dispute,
    setup_consumer_furnisher_file, respond,
)

BUREAU = make_bureau_headers()


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine — reopen cycle
# ---------------------------------------------------------------------------

def test_reverifying_reopen_cycle_returns_to_reverifying(api):
    """PRD §3.6: "Reopening advances the dispute from REVERIFYING to REOPENED,
    increments its reopen_count by one, and recomputes its priority_score"
    PRD §3.6: "From REOPENED, the bureau may dispatch a fresh reverification request,
    which again advances the dispute to REVERIFYING and increments the furnisher's
    open count, forming the revision loop."

    Design: Difficulty/non_linear_state_machine/dispute_reverifying_reopen_cycle
    """
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute()
    reopened = validate_success(api.reopen_dispute(dispute["id"], make_consumer_headers(consumer["id"])))
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    rv_after = validate_success(api.get_reverification(rv["id"], BUREAU))
    assert rv_after["status"] == "CANCELLED"
    rv2 = validate_success(api.create_reverification({"dispute_id": dispute["id"], "furnisher_id": furnisher["id"]}, BUREAU), 201)
    final = validate_success(api.get_dispute(dispute["id"], BUREAU))
    assert final["status"] == "REVERIFYING"
    assert rv2["status"] == "PENDING"


def test_reopen_cancels_pending_reverification(api):
    """PRD §3.6: "Any reverification request still PENDING for this dispute is
    cancelled — moved to CANCELLED — and the furnisher's open_reverification_count is
    decremented by one for each request so cancelled."

    Design: Difficulty/non_linear_state_machine/dispute_reverifying_reopen_cycle
    """
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute()
    validate_success(api.reopen_dispute(dispute["id"], make_consumer_headers(consumer["id"])))
    rv_after = validate_success(api.get_reverification(rv["id"], BUREAU))
    assert rv_after["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine — fork-join (MODIFY vs DELETE)
# ---------------------------------------------------------------------------

def test_modify_response_corrects_tradeline_and_balance(api):
    """PRD §3.5: "The dispute resolves to RESOLVED_CORRECT with outcome_reason
    FURNISHER_CORRECTED. The cascade replaces the tradeline's balance_cents with the
    supplied corrected_balance_cents and moves the tradeline from DISPUTED to CORRECTED"

    Design: Difficulty/non_linear_state_machine/reverification_response_fork_join
    """
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute(
        dispute_overrides={"dispute_reason": "INACCURATE_BALANCE"},
        tradeline_overrides={"balance_cents": 90000},
    )
    respond(rv["id"], furnisher["id"], "MODIFY", corrected_balance_cents=25000)
    d_after = validate_success(api.get_dispute(dispute["id"], BUREAU))
    tl_after = validate_success(api.get_tradeline(tl["id"], BUREAU))
    assert d_after["status"] == "RESOLVED_CORRECT"
    assert tl_after["status"] == "CORRECTED"
    assert tl_after["balance_cents"] == 25000


def test_delete_response_deletes_tradeline(api):
    """PRD §3.5: "When the furnisher answers DELETE, the dispute resolves to
    RESOLVED_DELETE with outcome_reason FURNISHER_DELETED. The cascade then deletes
    the tradeline: the disputed tradeline moves to DELETED"

    Design: Difficulty/non_linear_state_machine/reverification_response_fork_join
    """
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute(
        dispute_overrides={"dispute_reason": "NOT_MINE"},
        tradeline_overrides={"account_type": "INSTALLMENT", "balance_cents": 40000},
    )
    respond(rv["id"], furnisher["id"], "DELETE")
    d_after = validate_success(api.get_dispute(dispute["id"], BUREAU))
    tl_after = validate_success(api.get_tradeline(tl["id"], BUREAU))
    assert d_after["status"] == "RESOLVED_DELETE"
    assert tl_after["status"] == "DELETED"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade — DELETE depth-3
# ---------------------------------------------------------------------------

def test_delete_cascade_recomputes_file_counts(api):
    """PRD §3.5: "after which the file's tradeline_count is recomputed downward by
    one and its open_dispute_count is recomputed downward by one, and finally two
    notifications are minted on the file — one with event_code TRADELINE_DELETED and
    one with event_code DISPUTE_RESOLVED."

    Design: Difficulty/transitive_cascade/furnisher_delete_cascade_depth3
    """
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute(
        tradeline_overrides={"account_type": "COLLECTION", "balance_cents": 30000},
    )
    respond(rv["id"], furnisher["id"], "DELETE")
    d_after = validate_success(api.get_dispute(dispute["id"], BUREAU))
    tl_after = validate_success(api.get_tradeline(tl["id"], BUREAU))
    file_after = validate_success(api.get_credit_file(cfile["id"], BUREAU))
    assert d_after["status"] == "RESOLVED_DELETE"
    assert tl_after["status"] == "DELETED"
    assert file_after["tradeline_count"] == 0
    assert file_after["open_dispute_count"] == 0


def test_delete_cascade_mints_tradeline_deleted_notification(api):
    """PRD §3.5: "finally two notifications are minted on the file — one with
    event_code TRADELINE_DELETED and one with event_code DISPUTE_RESOLVED."

    Design: Difficulty/transitive_cascade/furnisher_delete_cascade_depth3
    """
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute(
        tradeline_overrides={"account_type": "COLLECTION", "balance_cents": 30000},
    )
    respond(rv["id"], furnisher["id"], "DELETE")
    notifs, _meta = validate_paginated(api.list_file_notifications(cfile["id"], BUREAU))
    match = find_notification(notifs, "TRADELINE_DELETED", subject_id=tl["id"])
    assert match is not None, "Expected a TRADELINE_DELETED notification for the deleted tradeline"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check — deadline inclusive respond
# ---------------------------------------------------------------------------

def test_respond_at_exact_deadline_succeeds(api):
    """PRD §2.9: "the deadline is inclusive: an investigation-advancing action whose
    server clock instant exactly equals the dispute's deadline is in time, while an
    instant even one microsecond past the deadline breaches it."

    Design: Difficulty/boundary_precision_check/deadline_inclusive_boundary_respond
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-05T00:00:00.000Z")
    tl = create_tradeline(cfile["id"], furnisher["id"], balance_cents=70000)
    dispute = file_dispute(consumer["id"], cfile["id"], tl["id"], get_file_version(cfile["id"]),
                           dispute_reason="INACCURATE_BALANCE", clock_mode="CALENDAR")
    validate_success(api.open_investigation(dispute["id"], BUREAU))
    rv = validate_success(api.create_reverification({"dispute_id": dispute["id"], "furnisher_id": furnisher["id"]}, BUREAU), 201)
    # Set clock to EXACTLY the deadline (deadline inclusive).
    api.clock_set("2026-02-04T00:00:00.000Z", BUREAU)
    rv_after = validate_success(
        api.respond_reverification(rv["id"], {"response_type": "MODIFY", "corrected_balance_cents": 10000},
                                   make_furnisher_headers(furnisher["id"]))
    )
    assert rv_after["status"] == "RESPONDED"


def test_respond_at_exact_deadline_resolves_dispute_correct(api):
    """PRD §3.5: "The dispute resolves to RESOLVED_CORRECT with outcome_reason
    FURNISHER_CORRECTED. The cascade replaces the tradeline's balance_cents with the
    supplied corrected_balance_cents and moves the tradeline from DISPUTED to CORRECTED"
    PRD §2.9: "the deadline is inclusive: an investigation-advancing action whose
    server clock instant exactly equals the dispute's deadline is in time"

    Design: Difficulty/boundary_precision_check/deadline_inclusive_boundary_respond
    """
    consumer, furnisher, cfile = setup_consumer_furnisher_file()
    set_clock("2026-01-05T00:00:00.000Z")
    tl = create_tradeline(cfile["id"], furnisher["id"], balance_cents=70000)
    dispute = file_dispute(consumer["id"], cfile["id"], tl["id"], get_file_version(cfile["id"]),
                           dispute_reason="INACCURATE_BALANCE", clock_mode="CALENDAR")
    validate_success(api.open_investigation(dispute["id"], BUREAU))
    rv = validate_success(api.create_reverification({"dispute_id": dispute["id"], "furnisher_id": furnisher["id"]}, BUREAU), 201)
    api.clock_set("2026-02-04T00:00:00.000Z", BUREAU)
    validate_success(
        api.respond_reverification(rv["id"], {"response_type": "MODIFY", "corrected_balance_cents": 10000},
                                   make_furnisher_headers(furnisher["id"]))
    )
    d_after = validate_success(api.get_dispute(dispute["id"], BUREAU))
    tl_after = validate_success(api.get_tradeline(tl["id"], BUREAU))
    assert d_after["status"] == "RESOLVED_CORRECT"
    assert tl_after["balance_cents"] == 10000


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant — furnisher count + file counts
# ---------------------------------------------------------------------------

def test_reopen_conserves_open_reverification_count(api):
    """PRD §3.5: "Dispatch creates a reverification request in status PENDING,
    advances the dispute to REVERIFYING, and increments the target furnisher's
    open_reverification_count by one."
    PRD §3.6: "Any reverification request still PENDING for this dispute is cancelled
    — moved to CANCELLED — and the furnisher's open_reverification_count is
    decremented by one for each request so cancelled."

    Design: Difficulty/compensating_invariant/reopen_cancel_conserves_open_reverification_count
    """
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute()
    before = validate_success(api.get_furnisher(furnisher["id"], BUREAU))
    assert before["open_reverification_count"] == 1
    validate_success(api.reopen_dispute(dispute["id"], make_consumer_headers(consumer["id"])))
    after = validate_success(api.get_furnisher(furnisher["id"], BUREAU))
    assert after["open_reverification_count"] == 0
    rv_after = validate_success(api.get_reverification(rv["id"], BUREAU))
    assert rv_after["status"] == "CANCELLED"


def test_reopen_cancels_pending_reverification_to_cancelled(api):
    """PRD §3.6: "Any reverification request still PENDING for this dispute is
    cancelled — moved to CANCELLED — and the furnisher's open_reverification_count is
    decremented by one for each request so cancelled."

    Design: Difficulty/compensating_invariant/reopen_cancel_conserves_open_reverification_count
    """
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute()
    rv_before = validate_success(api.get_reverification(rv["id"], BUREAU))
    assert rv_before["status"] == "PENDING"
    validate_success(api.reopen_dispute(dispute["id"], make_consumer_headers(consumer["id"])))
    rv_after = validate_success(api.get_reverification(rv["id"], BUREAU))
    assert rv_after["status"] == "CANCELLED"


def test_auto_delete_conserves_file_counts(api):
    """PRD §3.6: "An auto-deleted dispute moves to AUTO_DELETED with outcome_reason
    DEADLINE_BREACH ... The cascade mirrors the furnisher-delete cascade: the
    tradeline moves to DELETED, the file's tradeline_count and open_dispute_count are
    recomputed"
    PRD §3.6: "any reverification request still PENDING for the breached dispute is
    moved to EXPIRED, with the furnisher's open_reverification_count decremented by
    one per expired request."

    Design: Difficulty/compensating_invariant/auto_delete_conserves_file_counts
    """
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute()
    before = validate_success(api.get_credit_file(cfile["id"], BUREAU))
    assert before["tradeline_count"] == 1
    assert before["open_dispute_count"] == 1
    api.clock_advance("2026-02-05T00:00:00.000Z", BUREAU)
    after = validate_success(api.get_credit_file(cfile["id"], BUREAU))
    d_after = validate_success(api.get_dispute(dispute["id"], BUREAU))
    tl_after = validate_success(api.get_tradeline(tl["id"], BUREAU))
    rv_after = validate_success(api.get_reverification(rv["id"], BUREAU))
    assert d_after["status"] == "AUTO_DELETED"
    assert tl_after["status"] == "DELETED"
    assert after["tradeline_count"] == 0
    assert after["open_dispute_count"] == 0
    assert rv_after["status"] == "EXPIRED"


def test_auto_delete_expires_pending_reverification_and_clears_furnisher_count(api):
    """PRD §3.6: "any reverification request still PENDING for the breached dispute is
    moved to EXPIRED, with the furnisher's open_reverification_count decremented by
    one per expired request."

    Design: Difficulty/compensating_invariant/auto_delete_conserves_file_counts
    """
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute()
    before = validate_success(api.get_furnisher(furnisher["id"], BUREAU))
    assert before["open_reverification_count"] == 1
    api.clock_advance("2026-02-05T00:00:00.000Z", BUREAU)
    rv_after = validate_success(api.get_reverification(rv["id"], BUREAU))
    furn_after = validate_success(api.get_furnisher(furnisher["id"], BUREAU))
    assert rv_after["status"] == "EXPIRED"
    assert furn_after["open_reverification_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency — suspended furnisher
# ---------------------------------------------------------------------------

def test_reverification_blocked_by_suspended_furnisher(api):
    """PRD §3.5: "Dispatching requires that the dispute be in INVESTIGATING (or in
    REOPENED ...), that the target furnisher's status be ACTIVE (otherwise
    ERR_FURNISHER_SUSPENDED), and that the server clock be at or before the dispute's
    deadline"

    Design: Difficulty/cross_entity_state_dependency/reverification_blocked_by_suspended_furnisher
    """
    consumer, furnisher, cfile, tl, dispute = setup_investigating_dispute()
    validate_success(api.suspend_furnisher(furnisher["id"], BUREAU))
    resp = api.create_reverification({"dispute_id": dispute["id"], "furnisher_id": furnisher["id"]}, BUREAU)
    validate_error(resp, ApiErrorId.ERR_FURNISHER_SUSPENDED.value)


def test_reverification_to_suspended_furnisher_leaves_dispute_investigating(api):
    """PRD §3.5: "Dispatching requires that the dispute be in INVESTIGATING ... that
    the target furnisher's status be ACTIVE (otherwise ERR_FURNISHER_SUSPENDED)"
    PRD §3.5: "Dispatch creates a reverification request in status PENDING, advances
    the dispute to REVERIFYING"

    Design: Difficulty/cross_entity_state_dependency/reverification_blocked_by_suspended_furnisher
    """
    consumer, furnisher, cfile, tl, dispute = setup_investigating_dispute()
    validate_success(api.suspend_furnisher(furnisher["id"], BUREAU))
    api.create_reverification({"dispute_id": dispute["id"], "furnisher_id": furnisher["id"]}, BUREAU)
    d_after = validate_success(api.get_dispute(dispute["id"], BUREAU))
    assert d_after["status"] == "INVESTIGATING", "dispute must remain INVESTIGATING when dispatch is blocked"


# ---------------------------------------------------------------------------
# Corner: state_machines — terminal/idempotency guards, modify-missing-balance,
# reopen limit
# ---------------------------------------------------------------------------

def test_open_investigation_on_terminal_dispute_invalid_state(api):
    """PRD §3.4: "Opening requires that the dispute currently be FILED"
    PRD §2.7: "the state-machine check that the target is in a state from which the
    requested transition is defined (ERR_INVALID_STATE)"

    Design: Corner/state_machines/dispute_open_investigation_from_terminal_returns_invalid_state
    """
    consumer, furnisher, cfile, tl, dispute, rv = setup_resolved_verify_dispute()
    assert dispute["status"] == "RESOLVED_VERIFY"
    resp = api.open_investigation(dispute["id"], BUREAU)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_respond_to_already_responded_reverification_invalid_state(api):
    """PRD §3.5: "Any response requires that the reverification request still be
    PENDING (otherwise ERR_INVALID_STATE), that the acting furnisher be the request's
    own furnisher_id (otherwise ERR_NOT_RESOURCE_OWNER), and that the server clock be
    at or before the dispute's deadline"

    Design: Corner/state_machines/respond_to_already_responded_reverification_invalid_state
    """
    consumer, furnisher, cfile, tl, dispute, rv = setup_resolved_verify_dispute()
    assert rv["status"] == "RESPONDED"
    resp = api.respond_reverification(rv["id"], {"response_type": "DELETE"}, make_furnisher_headers(furnisher["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_modify_response_missing_corrected_balance(api):
    """PRD §3.5: "When the furnisher answers MODIFY, the response must include a
    corrected_balance_cents of at least 0; a modifying response that omits it is
    rejected with ERR_MISSING_CORRECTED_BALANCE."

    Design: Corner/state_machines/modify_response_missing_corrected_balance
    """
    consumer, furnisher, cfile, tl, dispute, rv = setup_reverifying_dispute(
        dispute_overrides={"dispute_reason": "INACCURATE_BALANCE"},
    )
    resp = api.respond_reverification(rv["id"], {"response_type": "MODIFY"}, make_furnisher_headers(furnisher["id"]))
    validate_error(resp, ApiErrorId.ERR_MISSING_CORRECTED_BALANCE.value)


def test_third_reopen_exceeds_limit(api):
    """PRD §3.6: "that the dispute's reopen_count be less than 2 (otherwise
    ERR_REOPEN_LIMIT_REACHED, since a dispute may be reopened at most twice)"

    Design: Corner/state_machines/reopen_limit_reached_on_third_reopen
    """
    consumer, furnisher, cfile, tl, dispute = setup_dispute_reopened_twice()
    assert dispute["reopen_count"] == 2
    assert dispute["status"] == "REVERIFYING"
    resp = api.reopen_dispute(dispute["id"], make_consumer_headers(consumer["id"]))
    validate_error(resp, ApiErrorId.ERR_REOPEN_LIMIT_REACHED.value)
