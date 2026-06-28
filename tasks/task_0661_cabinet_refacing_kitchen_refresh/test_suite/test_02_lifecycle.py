"""Lifecycle / state-machine tests: the quote revision cycle, install branching,
invalid transitions, guarded transitions, lazy expiry, and action endpoints.

Queue A: non_linear_state_machine.
Queue B: state_machines + endpoints corner instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    fixtures as fx,
)

_SALES = TEST_USERS["sales_rep_headers"]
_SCHED = TEST_USERS["scheduler_headers"]
_CREW = TEST_USERS["install_crew_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================

def test_quote_revision_cycle_returns_to_quoted(api):
    """PRD §3.5: "A `SalesRep` reopens a `QUOTED` quote to revise it, moving it
    `QUOTED → REVISING`; reopening requires the quote to be in `QUOTED` with its
    `is_active` flag true and increments the quote's `version` by one."
    PRD §3.4: "it is also the transition `REVISING → QUOTED` that closes the
    revision loop described in §3.5."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_quoted_revising_quoted
    """
    cust, proj, meas, quote = fx.setup_quoted_quote(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    validate_success(api.reopen_quote(quote["id"], _SALES))
    reissued = validate_success(api.issue_quote(quote["id"], _SALES))
    assert reissued["status"] == "QUOTED", \
        f"expected status QUOTED after reopen+reissue, got {reissued['status']}"
    # Firm recomputed identically (same measure): 715000.
    assert reissued["firm_total_cents"] == 715000, \
        f"expected firm 715000 after re-issue, got {reissued['firm_total_cents']}"


def test_quote_version_advances_over_revision_cycle(api):
    """PRD §3.5: "Because each reopen and each re-issue advances the quote's
    `version`, a customer who read the quote before a revision cycle and then tries
    to approve with the old version will be turned away on the stale-version check
    described in §2.9."

    Design: Difficulty/non_linear_state_machine/quote_revision_cycle_quoted_revising_quoted
    """
    cust, proj, meas, quote = fx.setup_quoted_quote(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    v_before = quote["version"]
    reopened = validate_success(api.reopen_quote(quote["id"], _SALES))
    reissued = validate_success(api.issue_quote(quote["id"], _SALES))
    assert reopened["version"] == v_before + 1, \
        f"reopen must bump version by 1: {v_before} -> {reopened['version']}"
    assert reissued["version"] == v_before + 2, \
        f"reopen+reissue must bump version by 2: {v_before} -> {reissued['version']}"


def test_install_branch_complete_drives_project_installed(api):
    """PRD §3.10: "The crew then completes the job, moving it `IN_PROGRESS → DONE`...
    Completion transitions the linked material order `READY → RECEIVED` if it is
    still in `READY`, bubbles the project up `IN_PRODUCTION → INSTALLED`, records
    the install-completion clock instant for the warranty window, and increments
    the project's `version` by one."

    Design: Difficulty/non_linear_state_machine/install_job_branching_done_vs_cancelled
    """
    cust, proj, meas, quote, mo, crew, ij = fx.setup_installed_project(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    assert ij["status"] == "DONE", f"expected install job DONE, got {ij['status']}"
    proj_read = validate_success(api.get_project(proj["id"], _SALES))
    mo_read = validate_success(api.get_material_order(mo["id"], _SCHED))
    assert proj_read["status"] == "INSTALLED", \
        f"expected project INSTALLED, got {proj_read['status']}"
    assert mo_read["status"] == "RECEIVED", \
        f"expected material order RECEIVED, got {mo_read['status']}"


def test_install_branch_cancel_reverts_project_to_sold(api):
    """PRD §3.10: "A `Scheduler` may cancel a scheduled job, moving it
    `SCHEDULED → CANCELLED`; cancellation is permitted only when the job is in
    `SCHEDULED` and reverts the project `IN_PRODUCTION → SOLD` if it was in
    production."

    Design: Difficulty/non_linear_state_machine/install_job_branching_done_vs_cancelled
    """
    cust, proj, meas, quote, mo, crew, ij = fx.setup_scheduled_install(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z",
        window_start="2026-06-10T08:00:00Z", window_end="2026-06-10T17:00:00Z")
    cancelled = validate_success(api.cancel_install_job(ij["id"], _SCHED))
    assert cancelled["status"] == "CANCELLED", \
        f"expected install job CANCELLED, got {cancelled['status']}"
    proj_read = validate_success(api.get_project(proj["id"], _SALES))
    assert proj_read["status"] == "SOLD", \
        f"expected project reverted to SOLD, got {proj_read['status']}"


# ===========================================================================
# Queue B — state_machines corner instances
# ===========================================================================

def test_cancel_completed_measure_rejected(api):
    """PRD §3.2: "A scheduled measure may simply be cancelled by a `SalesRep`,
    moving it `SCHEDULED → CANCELLED` with no effect on the project's dimensions."
    PRD §3.13: "for any transition, that the target entity is in a state from which
    the transition is defined (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/cancel_measure_from_completed_returns_invalid_state
    """
    cust, proj, meas = fx.setup_project_with_completed_measure()
    resp = api.cancel_measure(proj["id"], meas["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_approve_already_approved_quote_rejected(api):
    """PRD §3.5: "Approval is the transition `QUOTED → APPROVED` and is permitted
    only when the quote is in `QUOTED`".
    PRD §3.13: "for any transition, that the target entity is in a state from which
    the transition is defined (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/approve_quote_twice_second_returns_invalid_state
    """
    cust, proj, meas, quote = fx.setup_approved_quote()
    # quote dict carries the post-approve version; re-approving an APPROVED quote.
    resp = api.approve_quote(quote["id"], {"expected_quote_version": quote["version"]},
                             make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_close_project_blocked_by_open_warranty_claim(api):
    """PRD §3.1: "closing is permitted only when the project's `status` is
    `INSTALLED` and no warranty claim on the project is in either `SUBMITTED` or
    `APPROVED` status".

    Design: Corner/state_machines/close_project_blocked_by_open_warranty_claim
    """
    cust, proj, meas, quote, mo, crew, ij = fx.setup_installed_project(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z",
        window_start="2026-05-06T08:00:00Z", window_end="2026-05-06T17:00:00Z",
        start_clock="2026-05-06T08:00:00Z")
    # Submit a covered claim (clock at install completion, well within warranty).
    # PRD §4: "Operations that create a brand-new resource return 201 Created."
    validate_success(api.create_warranty_claim(
        proj["id"], {"description": "drawer misaligned"}, make_customer_headers(cust["id"])),
        expected_status=201)
    resp = api.close_project(proj["id"], _SCHED)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_mark_ready_before_lead_elapsed_rejected(api):
    """PRD §3.8: "A `Scheduler` marks an order ready, moving it `PLACED → READY`,
    but only once the current time is at or after the order's `ready_at`; an attempt
    to mark ready before the lead time has elapsed is rejected with
    `ERR_LEAD_TIME_NOT_ELAPSED` (HTTP 409)."

    Design: Corner/state_machines/material_order_mark_ready_before_lead_elapsed_blocked
    """
    cust, proj, meas, quote, mo = fx.setup_in_production(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    # Clock still at placement default 2026-04-01; ready_at is 33 days out.
    resp = api.mark_ready_material_order(mo["id"], _SCHED)
    validate_error(resp, ApiErrorId.ERR_LEAD_TIME_NOT_ELAPSED.value)


def test_quote_lazily_expires_and_approval_rejected(api):
    """PRD §3.5: "If the quote's `expires_at` has already passed, the quote is
    treated as expired and approval is rejected with `ERR_QUOTE_EXPIRED` (HTTP 409)."
    PRD §3.4: "It sets `expires_at` to the current time plus the quote-validity
    window of 30 days."

    Design: Corner/state_machines/quote_lazily_expires_after_validity_window
    """
    fx.reset_clock()
    cust, proj, meas, quote = fx.setup_quoted_quote(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    fx.set_clock("2026-07-01T00:00:00Z")  # well past issuance + 30 days.
    resp = api.approve_quote(quote["id"], {"expected_quote_version": quote["version"]},
                             make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED.value)


def test_superseded_quote_locked_against_reopen(api):
    """PRD §3.4: "It marks this quote's `is_active` flag true and marks any prior
    active quote on the same project as `SUPERSEDED` with its `is_active` cleared to
    false."
    PRD §3.5: "reopening requires the quote to be in `QUOTED`".

    Design: Corner/state_machines/terminal_quote_superseded_locked_against_reopen
    """
    cust, proj, meas = fx.setup_project_with_completed_measure()
    q_a = fx.create_draft_quote(proj["id"], meas["id"], scope="REFACE")
    validate_success(api.issue_quote(q_a["id"], _SALES))
    q_b = fx.create_draft_quote(proj["id"], meas["id"], scope="REDOOR")
    validate_success(api.issue_quote(q_b["id"], _SALES))  # supersedes q_a.
    resp = api.reopen_quote(q_a["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_sold_project_rejected(api):
    """PRD §3.1: "A pre-sale project may be cancelled by a `SalesRep`: this is
    permitted only while the project's `status` is `LEAD`, `MEASURED`, or `QUOTED`".

    Design: Corner/state_machines/cancel_sold_project_rejected_invalid_state
    """
    cust, proj, meas, quote = fx.setup_approved_quote()  # project is SOLD.
    resp = api.cancel_project(proj["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue B — endpoints corner instances
# ===========================================================================

def test_financing_decline_reflected_on_read(api):
    """PRD §3.12: "A `PlatformAdmin` may instead decline a submitted application,
    moving it `SUBMITTED → DECLINED`."

    Design: Corner/endpoints/financing_decline_then_get_reflects_status
    """
    cust, proj, fa = fx.setup_submitted_financing(amount_cents=1_500_000, term_months=36)
    declined = validate_success(api.decline_financing_application(fa["id"], _ADMIN))
    assert declined["status"] == "DECLINED", \
        f"expected status DECLINED, got {declined['status']}"
    read = validate_success(api.get_financing_application(fa["id"], _ADMIN))
    assert read["status"] == "DECLINED", \
        f"GET must reflect DECLINED, got {read['status']}"


def test_financing_approve_within_dti_succeeds(api):
    """PRD §3.12: "A `PlatformAdmin` approves a submitted application, moving it
    `SUBMITTED → APPROVED`, but only when the `dti_ratio` is at most 0.20".

    Design: Corner/endpoints/financing_approve_within_dti_succeeds
    """
    cust, proj, fa = fx.setup_submitted_financing(
        annual_income_cents=3_800_000, amount_cents=2_000_000, term_months=36)
    assert fa["dti_ratio"] == 0.1979, f"setup expected dti 0.1979, got {fa['dti_ratio']}"
    approved = validate_success(api.approve_financing_application(fa["id"], _ADMIN))
    assert approved["status"] == "APPROVED", \
        f"expected status APPROVED, got {approved['status']}"


def test_warranty_adjudicate_approve_covered_claim(api):
    """PRD §3.11: "A decision to approve moves the claim `SUBMITTED → APPROVED` but
    is allowed only when the claim's `covered` flag is true".
    PRD §3.11: "a claim is covered when the current time is at or before the
    install-completion instant plus the warranty window of 90 days, and uncovered
    otherwise."

    Design: Corner/endpoints/warranty_adjudicate_approve_covered_claim_succeeds
    """
    cust, proj, meas, quote, mo, crew, ij = fx.setup_installed_project(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER",
        ready_clock="2026-05-05T00:00:00Z",
        window_start="2026-05-06T08:00:00Z", window_end="2026-05-06T17:00:00Z",
        start_clock="2026-05-06T08:00:00Z")
    # PRD §4: "Operations that create a brand-new resource return 201 Created."
    claim = validate_success(api.create_warranty_claim(
        proj["id"], {"description": "hinge squeak"}, make_customer_headers(cust["id"])),
        expected_status=201)
    assert claim["covered"] is True, "claim filed immediately after install must be covered"
    adjudicated = validate_success(api.adjudicate_warranty_claim(
        claim["id"], {"decision": "APPROVE"}, _ADMIN))
    assert adjudicated["status"] == "APPROVED", \
        f"expected status APPROVED, got {adjudicated['status']}"


def test_material_orders_filterable_by_quote(api):
    """PRD §3.8: "Material orders can be listed per project (optional `status`,
    `limit`, `offset`) and across the system filterable by `quote_id`."

    Design: Corner/endpoints/material_order_filtered_list_by_quote
    """
    cust, proj, meas, quote, mo = fx.setup_in_production(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    from test_helpers import validate_paginated
    data, meta = validate_paginated(api.list_material_orders(_SCHED, params={"quote_id": quote["id"]}))
    assert meta["total_count"] == 1, \
        f"expected exactly 1 material order for the quote, got {meta['total_count']}"
    assert data[0]["id"] == mo["id"], "filtered list must return the placed material order"
