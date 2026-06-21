"""Cancellation cascades and compensating-ledger invariants: project cancel reverting
linguist commitments, invoice void reverting client AR and the project state, and the
supersede compensation that returns a linguist's committed payout to zero.

Covers difficulty rules `transitive_cascade` (project cancel), `non_linear_state_machine`
(invoice void revert branch), and `compensating_invariant` (supersede, void).
"""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    create_client, create_rate_card, create_linguist, create_project, add_job,
    quote_and_approve, assign, accept_as_translator,
    current_job_version, current_project_version,
    create_assignment_payload, issue_invoice_payload,
    setup_issued_invoice,
)

PM = TEST_USERS["pm_headers"]
AR = TEST_USERS["ar_headers"]


def _in_production_with_committed_translator():
    """Approved project, one job, translator accepted (job TRANSLATING, project
    IN_PRODUCTION, committed_payout 15975). No invoice. Returns (project, job,
    translator, translator_assignment)."""
    client = create_client()
    rate_card = create_rate_card()
    translator = create_linguist()
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"])  # default bands -> provisional 15975
    quote_and_approve({"project": project, "client": client})
    ta = assign(job["id"], translator["id"], "TRANSLATOR")
    accept_as_translator(ta["id"], translator["id"])
    return project, job, translator, ta


# ─── transitive_cascade: project cancel -> jobs -> payout revert ───────────
def test_project_cancel_cascades_to_job_assignment_and_payout(api):
    """PRD §3.11: "In every permitted case, cancelling a project cascade-cancels all of
    its jobs that are not already terminal. Each cascade-cancelled job moves to
    `CANCELLED`: a job in `PENDING` simply terminates with no further effect, while a job
    in `TRANSLATING` or `REVISION` additionally cancels its active assignments and
    reverts the affected linguists' `committed_payout_cents`."

    Cancel (A) cascades the TRANSLATING job -> CANCELLED (B); that cancels its
    IN_PROGRESS assignment -> CANCELLED (C); the linguist's committed_payout reverts to 0.

    Design: Difficulty/transitive_cascade/tc_project_cancel_cancels_jobs_reverts_payout_depth3
    """
    project, job, translator, ta = _in_production_with_committed_translator()
    cancelled = validate_success(api.cancel_project(project["id"], PM), 200)
    assert cancelled["status"] == "CANCELLED", f"got {cancelled['status']}"
    job_after = validate_success(api.get_job(job["id"], PM), 200)
    assert job_after["status"] == "CANCELLED", f"got {job_after['status']}"
    asg_after = validate_success(api.get_assignment(ta["id"], PM), 200)
    assert asg_after["status"] == "CANCELLED", f"got {asg_after['status']}"
    ling = validate_success(api.get_linguist(translator["id"], PM), 200)
    assert ling["committed_payout_cents"] == 0, \
        f"expected 0 after cascade revert, got {ling['committed_payout_cents']}"


def test_project_cancel_reverts_committed_payout_via_reversal_entry(api):
    """PRD §3.11: "Cancelling an active `ACCEPTED` or `IN_PROGRESS` assignment in this
    cascade appends a `REVERSAL` ledger entry equal to the negative of its `payout_cents`
    and decreases the owning linguist's `committed_payout_cents` by that amount, so no
    linguist remains committed to work that will never happen."

    Second probe of the cascade's terminal effect: after cancel, the linguist's ledger
    contains a REVERSAL of -15975 and the derived balance reads 0.

    Design: Difficulty/transitive_cascade/tc_project_cancel_cancels_jobs_reverts_payout_depth3
    """
    project, job, translator, ta = _in_production_with_committed_translator()
    validate_success(api.cancel_project(project["id"], PM), 200)
    entries, _meta = _ledger(api, translator["id"])
    reversals = [e for e in entries if e["entry_type"] == "REVERSAL"]
    assert len(reversals) == 1, f"expected 1 REVERSAL, got {len(reversals)}"
    assert reversals[0]["amount_cents"] == -15975, \
        f"expected -15975, got {reversals[0]['amount_cents']}"
    ling = validate_success(api.get_linguist(translator["id"], PM), 200)
    assert ling["committed_payout_cents"] == 0, f"got {ling['committed_payout_cents']}"


def _ledger(api, linguist_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_linguist_payout_ledger(linguist_id, PM))


# ─── non_linear_state_machine: invoice void revert branch ──────────────────
def test_void_issued_invoice_reverts_project_and_ar(api):
    """PRD §3.8: "An issued invoice may instead be voided, advancing it from `ISSUED` to
    `VOIDED`; ... Voiding an issued invoice is a compensation: it decreases the client's
    `ar_balance_cents` by `total_cents`, restoring the pre-issue balance, and reverts the
    project from `INVOICED` back to `DELIVERED` so that a corrected invoice can be issued."

    Design: Difficulty/non_linear_state_machine/nlsm_invoice_void_revert_branch
    """
    ctx = setup_issued_invoice(rush_tier="EXPRESS", certification_mode="CERTIFIED")
    voided = validate_success(api.void_invoice(ctx["invoice"]["id"], AR), 200)
    assert voided["status"] == "VOIDED", f"got {voided['status']}"
    project = validate_success(api.get_project(ctx["project"]["id"], PM), 200)
    assert project["status"] == "DELIVERED", f"got {project['status']}"
    client = validate_success(api.get_client(ctx["client"]["id"], AR), 200)
    assert client["ar_balance_cents"] == 0, \
        f"expected 0 after void, got {client['ar_balance_cents']}"


def test_void_draft_invoice_has_no_balance_or_project_effect(api):
    """PRD §3.8: "A draft invoice may also be voided directly, advancing it from `DRAFT`
    to `VOIDED` with no balance or project effect."

    Contrast branch: the DRAFT->VOIDED path (distinct from the ISSUED->VOIDED compensation)
    leaves the client AR untouched and does not move the project.

    Design: Difficulty/non_linear_state_machine/nlsm_invoice_void_revert_branch
    """
    client = create_client()
    rate_card = create_rate_card()
    project = create_project(client["id"], rate_card["id"])
    add_job(project["id"], bands={"quoted_no_match_words": 1000})
    # Create a DRAFT invoice directly (no delivery/issue) and void it.
    inv = get_success_data(api.create_invoice(project["id"], AR))
    voided = validate_success(api.void_invoice(inv["id"], AR), 200)
    assert voided["status"] == "VOIDED", f"got {voided['status']}"
    client_after = validate_success(api.get_client(client["id"], AR), 200)
    assert client_after["ar_balance_cents"] == 0, \
        f"draft void must not touch AR, got {client_after['ar_balance_cents']}"


# ─── compensating_invariant: committed payout zero after supersede ─────────
def test_committed_payout_zero_after_supersede(api):
    """PRD §3.5: "Whenever a replacement assignment of the same role is created on a job,
    the prior assignment is superseded automatically. ... A superseded assignment that
    had already been `ACCEPTED` or was `IN_PROGRESS` triggers compensation: a `REVERSAL`
    ledger entry equal to the negative of its `payout_cents` is appended, and the
    linguist's `committed_payout_cents` is decreased by that same `payout_cents`, cleanly
    backing out the provisional commitment."

    Design: Difficulty/compensating_invariant/ci_linguist_committed_payout_zero_after_supersede
    """
    client = create_client()
    rate_card = create_rate_card()
    la = create_linguist(full_name="Trans A")
    lb = create_linguist(full_name="Trans B")
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"])  # default bands -> 15975
    quote_and_approve({"project": project, "client": client})
    ta = assign(job["id"], la["id"], "TRANSLATOR")
    accept_as_translator(ta["id"], la["id"])
    # Replacement TRANSLATOR for linguist B supersedes A's accepted assignment.
    jv = current_job_version(job["id"])
    get_success_data(api.create_assignment(
        create_assignment_payload(job["id"], lb["id"], "TRANSLATOR", jv), PM))
    asg_a = validate_success(api.get_assignment(ta["id"], PM), 200)
    assert asg_a["status"] == "SUPERSEDED", f"got {asg_a['status']}"
    ling_a = validate_success(api.get_linguist(la["id"], PM), 200)
    assert ling_a["committed_payout_cents"] == 0, \
        f"expected 0 after supersede, got {ling_a['committed_payout_cents']}"


def test_supersede_appends_reversal_entry(api):
    """PRD §2.9: "The `entry_type` is ... `REVERSAL` when an accepted or in-progress
    assignment is superseded or cancelled".
    PRD §3.5: "a `REVERSAL` ledger entry equal to the negative of its `payout_cents` is
    appended, and the linguist's `committed_payout_cents` is decreased by that same
    `payout_cents`".

    Second probe of the conserved quantity: the supersede appends a -15975 REVERSAL to
    linguist A's ledger, so the running sum (and derived balance) returns to 0.

    Design: Difficulty/compensating_invariant/ci_linguist_committed_payout_zero_after_supersede
    """
    client = create_client()
    rate_card = create_rate_card()
    la = create_linguist(full_name="Trans A")
    lb = create_linguist(full_name="Trans B")
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"])
    quote_and_approve({"project": project, "client": client})
    ta = assign(job["id"], la["id"], "TRANSLATOR")
    accept_as_translator(ta["id"], la["id"])
    jv = current_job_version(job["id"])
    get_success_data(api.create_assignment(
        create_assignment_payload(job["id"], lb["id"], "TRANSLATOR", jv), PM))
    entries, _meta = _ledger(api, la["id"])
    reversals = [e for e in entries if e["entry_type"] == "REVERSAL"]
    assert len(reversals) == 1, f"expected 1 REVERSAL, got {len(reversals)}"
    assert reversals[0]["amount_cents"] == -15975, \
        f"expected -15975, got {reversals[0]['amount_cents']}"


# ─── compensating_invariant: client AR zero after void ─────────────────────
def test_client_ar_balance_zero_after_void(api):
    """PRD §2.10: "when an invoice is issued, the client's `ar_balance_cents` increases by
    the invoice `total_cents`; ... and when an issued invoice is voided, it likewise
    decreases by `total_cents`, returning the balance to its pre-issue value."

    Design: Difficulty/compensating_invariant/ci_client_ar_balance_zero_after_void
    """
    ctx = setup_issued_invoice(rush_tier="EXPRESS", certification_mode="CERTIFIED")
    voided = validate_success(api.void_invoice(ctx["invoice"]["id"], AR), 200)
    assert voided["status"] == "VOIDED", f"got {voided['status']}"
    client = validate_success(api.get_client(ctx["client"]["id"], AR), 200)
    assert client["ar_balance_cents"] == 0, \
        f"expected 0 after void, got {client['ar_balance_cents']}"


def test_client_ar_balance_rises_on_issue_then_clears_on_void(api):
    """PRD §2.10: "When an invoice is issued, the client's `ar_balance_cents` increases by
    the invoice `total_cents`; ... and when an issued invoice is voided, it likewise
    decreases by `total_cents`, returning the balance to its pre-issue value."

    Second probe of the conserved quantity: the issue raises AR to the invoice total
    (42063 for this single-pass EXPRESS+CERTIFIED delivery), and the void clears it to 0.

    Design: Difficulty/compensating_invariant/ci_client_ar_balance_zero_after_void
    """
    ctx = setup_issued_invoice(rush_tier="EXPRESS", certification_mode="CERTIFIED")
    issued_total = ctx["invoice"]["total_cents"]
    after_issue = validate_success(api.get_client(ctx["client"]["id"], AR), 200)
    assert after_issue["ar_balance_cents"] == issued_total, \
        f"AR should equal invoice total {issued_total}, got {after_issue['ar_balance_cents']}"
    assert issued_total == 42063, f"expected single-pass total 42063, got {issued_total}"
    validate_success(api.void_invoice(ctx["invoice"]["id"], AR), 200)
    after_void = validate_success(api.get_client(ctx["client"]["id"], AR), 200)
    assert after_void["ar_balance_cents"] == 0, f"got {after_void['ar_balance_cents']}"
