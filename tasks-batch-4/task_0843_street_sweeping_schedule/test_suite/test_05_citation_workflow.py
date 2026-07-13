"""Citation issuance gates, contest/adjudicate branches, ledger conservation, and
validation precedence.

Translates queue A (Difficulty) instances for the contest fork, the pending-cents
compensating invariant, the signage-vs-suspension priority pair, the restriction
window boundary, and the Citation<-Block cross-entity dependency; plus queue B
(Corner) issuance-gate and terminal-state instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_citation_payload,
    TEST_USERS, make_officer_headers,
    setup_verified_block, setup_posted_block, setup_issued_citation,
    set_clock, issue_citation, contest_citation, adjudicate_citation, pay_citation,
    create_suspension, activate_suspension,
)

OFFICER = TEST_USERS["enforcement_officer_headers"]


# ─── Contest fork: DISMISS branch (non_linear_state_machine) ──────────────────

def test_dismiss_branch_records_adjudicator(api):
    """PRD §3.7: "Dismissing advances the citation `CONTESTED → DISMISSED`, likewise records `adjudicator_id`, and subtracts `amount_due_cents` from the block's ledger to compensate the original issuance debit."

    Design: Difficulty/non_linear_state_machine/citation_contest_branch_uphold_dismiss
    """
    route, block, cit = setup_issued_citation(plate="CON111", officer_id="officer-1")
    contest_citation(cit["id"], officer_id="officer-1")
    dismissed = adjudicate_citation(cit["id"], "DISMISS", officer_id="officer-2")
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["adjudicator_id"] == "officer-2"


def test_dismiss_branch_debits_block_pending(api):
    """PRD §2.10: "A block's `pending_citation_cents` equals the sum of `amount_due_cents` over that block's citations whose status is `ISSUED` or `CONTESTED`. It rises when a citation is issued and falls when a citation leaves that pending set (by being upheld, dismissed, or paid)."

    Design: Difficulty/non_linear_state_machine/citation_contest_branch_uphold_dismiss
    """
    route, block, cit = setup_issued_citation(plate="CON112", officer_id="officer-1")
    contest_citation(cit["id"], officer_id="officer-1")
    adjudicate_citation(cit["id"], "DISMISS", officer_id="officer-2")
    block_after = validate_success(api.get_block(block["id"], OFFICER), 200)
    assert block_after["pending_citation_cents"] == 0


# ─── Pending-cents conservation (compensating_invariant) ──────────────────────

def test_issue_then_dismiss_conserves_pending_cents(api):
    """PRD §3.7: "Issuing the citation also adds `amount_due_cents` to the block's `pending_citation_cents`."
    PRD §3.7: "Dismissing advances the citation `CONTESTED → DISMISSED`, likewise records `adjudicator_id`, and subtracts `amount_due_cents` from the block's ledger to compensate the original issuance debit."

    Design: Difficulty/compensating_invariant/citation_issue_dismiss_pending_cents_conserved
    """
    route, block, cit = setup_issued_citation(plate="INV001", officer_id="officer-1")
    after_issue = validate_success(api.get_block(block["id"], OFFICER), 200)
    assert after_issue["pending_citation_cents"] == 6000

    contest_citation(cit["id"], officer_id="officer-1")
    adjudicate_citation(cit["id"], "DISMISS", officer_id="officer-2")
    after_dismiss = validate_success(api.get_block(block["id"], OFFICER), 200)
    assert after_dismiss["pending_citation_cents"] == 0


def test_contest_leaves_pending_cents_unchanged(api):
    """PRD §3.7: "A contested citation remains inside the pending-ledger set `{ISSUED, CONTESTED}`, so `pending_citation_cents` is unchanged by a contest."

    Design: Difficulty/compensating_invariant/citation_issue_dismiss_pending_cents_conserved
    """
    route, block, cit = setup_issued_citation(plate="INV002", officer_id="officer-1")
    contest_citation(cit["id"], officer_id="officer-1")
    after_contest = validate_success(api.get_block(block["id"], OFFICER), 200)
    assert after_contest["pending_citation_cents"] == 6000


# ─── Priority pair: signage (P8) vs suspension (P9) (priority_pair) ────────────

def test_signage_referential_wins_over_suspension_temporal(api):
    """PRD §2.9: "Because the order is strict, a check earlier in the list masks any later one"
    PRD §3.7: "First, the block's sign must be enforceable and enforcement enabled — that is, `sign_enforceable` must be true (VERIFIED and unexpired per §3.2) and `enforcement_enabled` must be true — else `ERR_SIGNAGE_NOT_ENFORCEABLE`. Second, no `ACTIVE` suspension may cover the block's route on the scanned date, else `ERR_SWEEP_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/citation_signage_vs_suspension_referential_wins
    """
    route, block = setup_posted_block()  # POSTED but not VERIFIED -> not enforceable
    sus = create_suspension(scope="ROUTE", route_id=route["id"], start_date="2026-03-09", end_date="2026-03-11")
    activate_suspension(sus["id"])
    set_clock("2026-03-10T08:30:00Z", OFFICER)
    res = api.create_citation(
        create_citation_payload(block["id"], plate="PRI001", scanned_at_utc="2026-03-10T08:30:00Z"),
        make_officer_headers("officer-1"))
    validate_error(res, "ERR_SIGNAGE_NOT_ENFORCEABLE", expected_status=422)


def test_signage_rejection_persists_no_citation(api):
    """PRD §3.7: "First, the block's sign must be enforceable and enforcement enabled — that is, `sign_enforceable` must be true (VERIFIED and unexpired per §3.2) and `enforcement_enabled` must be true — else `ERR_SIGNAGE_NOT_ENFORCEABLE`."

    Design: Difficulty/priority_pair_validation_conflict/citation_signage_vs_suspension_referential_wins
    """
    route, block = setup_posted_block()
    sus = create_suspension(scope="ROUTE", route_id=route["id"], start_date="2026-03-09", end_date="2026-03-11")
    activate_suspension(sus["id"])
    set_clock("2026-03-10T08:30:00Z", OFFICER)
    api.create_citation(
        create_citation_payload(block["id"], plate="PRI002", scanned_at_utc="2026-03-10T08:30:00Z"),
        make_officer_headers("officer-1"))
    _, meta = validate_paginated(api.list_citations(OFFICER, params={"block_id": block["id"]}))
    assert meta["total_count"] == 0, "a rejected issuance must not persist a citation"


# ─── Cross-entity dependency: Citation<-Block sign VERIFIED ───────────────────

def test_issue_requires_sign_verified(api):
    """PRD §3.7: "First, the block's sign must be enforceable and enforcement enabled — that is, `sign_enforceable` must be true (VERIFIED and unexpired per §3.2) and `enforcement_enabled` must be true — else `ERR_SIGNAGE_NOT_ENFORCEABLE`."

    Design: Difficulty/cross_entity_state_dependency/citation_requires_block_sign_verified
    """
    route, block = setup_posted_block()  # POSTED, never VERIFIED, no suspension
    set_clock("2026-03-10T08:30:00Z", OFFICER)
    res = api.create_citation(
        create_citation_payload(block["id"], plate="DEP001", scanned_at_utc="2026-03-10T08:30:00Z"),
        make_officer_headers("officer-1"))
    validate_error(res, "ERR_SIGNAGE_NOT_ENFORCEABLE", expected_status=422)


def test_posted_block_is_not_enforceable(api):
    """PRD §3.2: "Enforceability is a derived property, `sign_enforceable`, that is true exactly when `sign_status` is `VERIFIED` *and* the current logical clock is strictly before `sign_expires_at`."

    Design: Difficulty/cross_entity_state_dependency/citation_requires_block_sign_verified
    """
    route, block = setup_posted_block()
    fetched = validate_success(api.get_block(block["id"], OFFICER), 200)
    assert fetched["sign_status"] == "POSTED"
    assert fetched["sign_enforceable"] is False


# ─── Restriction window boundary (boundary_precision) ─────────────────────────

def test_scan_at_window_end_is_outside(api):
    """PRD §2.8: "an instant exactly equal to a window's end is *outside* the window."
    PRD §3.7: "Third, the time-of-day of `scanned_at_utc` must fall within the block's half-open restriction window `[restriction_start_local, restriction_end_local)`, else `ERR_OUTSIDE_RESTRICTION_WINDOW`."

    Design: Difficulty/boundary_precision_check/citation_window_half_open_end_excluded
    """
    route, block = setup_verified_block(restriction_start_local="08:00", restriction_end_local="10:00")
    set_clock("2026-03-10T10:00:00Z", OFFICER)
    res = api.create_citation(
        create_citation_payload(block["id"], plate="BND010", scanned_at_utc="2026-03-10T10:00:00Z"),
        make_officer_headers("officer-1"))
    validate_error(res, "ERR_OUTSIDE_RESTRICTION_WINDOW", expected_status=422)


def test_scan_just_before_window_end_is_inside(api):
    """PRD §3.7: "the time-of-day of `scanned_at_utc` must fall within the block's half-open restriction window `[restriction_start_local, restriction_end_local)`, else `ERR_OUTSIDE_RESTRICTION_WINDOW`."

    Design: Difficulty/boundary_precision_check/citation_window_half_open_end_excluded
    """
    route, block = setup_verified_block(restriction_start_local="08:00", restriction_end_local="10:00")
    set_clock("2026-03-10T09:59:59Z", OFFICER)
    cit = issue_citation(block["id"], plate="BND009", scanned_at_utc="2026-03-10T09:59:59Z")
    assert cit["status"] == "ISSUED"


# ─── Corner: window start included ────────────────────────────────────────────

def test_scan_at_window_start_is_inside(api):
    """PRD §2.8: "an occupation or restriction interval is **half-open**, written `[start, end)` — it includes its start instant and excludes its end instant."

    Design: Corner/validations/citation_window_start_boundary_included_succeeds
    """
    route, block = setup_verified_block(restriction_start_local="08:00", restriction_end_local="10:00")
    set_clock("2026-03-10T08:00:00Z", OFFICER)
    cit = issue_citation(block["id"], plate="STA001", scanned_at_utc="2026-03-10T08:00:00Z")
    res = validate_success(api.get_citation(cit["id"], OFFICER), 200)
    assert res["status"] == "ISSUED"


# ─── Corner: sweep suspended on issue ─────────────────────────────────────────

def test_issue_on_active_suspension_rejected(api):
    """PRD §3.7: "Second, no `ACTIVE` suspension may cover the block's route on the scanned date, else `ERR_SWEEP_SUSPENDED`."

    Design: Corner/validations/error_sweep_suspended_on_citation_issue
    """
    route, block = setup_verified_block()
    sus = create_suspension(reason="LEAF_SEASON", scope="ROUTE", route_id=route["id"],
                            start_date="2026-03-10", end_date="2026-03-10")
    activate_suspension(sus["id"])
    set_clock("2026-03-10T08:30:00Z", OFFICER)
    res = api.create_citation(
        create_citation_payload(block["id"], plate="SUP001", scanned_at_utc="2026-03-10T08:30:00Z"),
        make_officer_headers("officer-1"))
    validate_error(res, "ERR_SWEEP_SUSPENDED", expected_status=409)


# ─── Corner: segregation of duties ────────────────────────────────────────────

def test_adjudicate_by_issuing_officer_rejected(api):
    """PRD §3.7: "Adjudication resolves a contested citation and requires the `decision` field, which is either `UPHOLD` or `DISMISS`; it is permitted only from `CONTESTED` and only when the acting `X-User-ID` differs from the citation's `issuing_officer_id` (segregation of duties, `ERR_SEGREGATION_OF_DUTIES`)."

    Design: Corner/state_machines/adjudicate_by_issuing_officer_returns_sod_error
    """
    route, block, cit = setup_issued_citation(plate="SOD001", officer_id="officer-1")
    contest_citation(cit["id"], officer_id="officer-1")
    res = api.adjudicate_citation(cit["id"], {"decision": "UPHOLD"}, make_officer_headers("officer-1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)


# ─── Corner: terminal PAID rejects further transition ─────────────────────────

def test_contest_paid_citation_rejected(api):
    """PRD §3.7: "Both `DISMISSED` and `PAID` are terminal."
    PRD §3.7: "Contesting advances it `ISSUED → CONTESTED` (permitted only from `ISSUED`)"

    Design: Corner/state_machines/terminal_paid_citation_rejects_further_transition
    """
    route, block, cit = setup_issued_citation(plate="PAY001", officer_id="officer-1")
    pay_citation(cit["id"], officer_id="officer-1")
    res = api.contest_citation(cit["id"], {}, make_officer_headers("officer-1"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
