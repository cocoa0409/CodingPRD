"""Lifecycle / state-machine workflow tests: the revision cycle, parallel invoice
dimensions, cascading side effects (cancel -> void -> crew minutes; complete -> invoice
-> balance), and conserved-quantity invariants.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_scheduled_job, setup_dispatched_job, setup_completed_job_with_invoice,
    setup_cancellation_invoice_after_dispatched_cancel,
    make_customer_headers, make_crew_lead_headers,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_headers"]


# ─── non_linear_state_machine: revision cycle ─────────

def test_revise_sends_scheduled_job_back_to_estimated(api):
    """PRD §3.5: "A customer may revise a `SCHEDULED` job to send it back for
    re-estimation, and this forms the system's revision cycle (`SCHEDULED → ESTIMATED`,
    mirroring the `ESTIMATED → SCHEDULED` scheduling edge)."

    Design: Difficulty/non_linear_state_machine/hauljob_revision_cycle_scheduled_back_to_estimated
    """
    ctx = setup_scheduled_job(raw_fraction=0.30)
    job_v = validate_success(
        api.get_haul_job(ctx["job"]["id"], make_customer_headers(ctx["customer"]["id"]))
    )["version"]
    job = validate_success(api.revise_haul_job(
        ctx["job"]["id"], {"expected_job_version": job_v}, make_customer_headers(ctx["customer"]["id"])
    ))
    assert job["status"] == "ESTIMATED", f"status={job['status']}"


def test_revise_voids_reserved_dispatch_and_releases_crew_minutes(api):
    """PRD §3.5: "On revision, the job's `RESERVED` dispatch transitions to `VOIDED`; the
    crew's `reserved_minutes` is recomputed to drop that voided window; the job returns to
    `ESTIMATED` so the customer may submit a fresh estimate, re-accept, and re-dispatch;
    and the job's `version` is incremented by one."

    The single 60-minute reserved window is the only one on the crew, so after the void
    reserved_minutes returns to 0.

    Design: Difficulty/non_linear_state_machine/hauljob_revision_cycle_scheduled_back_to_estimated
    """
    ctx = setup_scheduled_job(raw_fraction=0.30)
    job_v = validate_success(
        api.get_haul_job(ctx["job"]["id"], make_customer_headers(ctx["customer"]["id"]))
    )["version"]
    validate_success(api.revise_haul_job(
        ctx["job"]["id"], {"expected_job_version": job_v}, make_customer_headers(ctx["customer"]["id"])
    ))
    dispatch = validate_success(api.get_dispatch(ctx["dispatch"]["id"], DISPATCHER))
    assert dispatch["dispatch_status"] == "VOIDED", f"dispatch_status={dispatch['dispatch_status']}"
    crew = validate_success(api.get_crew(ctx["crew"]["id"], DISPATCHER))
    assert crew["reserved_minutes"] == 0, f"reserved_minutes={crew['reserved_minutes']}"


# ─── non_linear_state_machine: parallel invoice dims ──

def test_dispute_moves_dispute_status_without_changing_billing_status(api):
    """PRD §3.8: "A customer may dispute its own invoice while the invoice is `ISSUED`
    (otherwise `ERR_INVOICE_NOT_ISSUED`) and its `dispute_status` is `NONE` (otherwise
    `ERR_INVOICE_ALREADY_DISPUTED`); disputing moves `dispute_status` to `DISPUTED` and
    leaves `billing_status` unchanged at `ISSUED`."

    Design: Difficulty/non_linear_state_machine/invoice_parallel_dimensions_billing_and_dispute_independent
    """
    ctx = setup_completed_job_with_invoice(raw_fraction=0.10, measured_truck_fraction=0.10)
    inv = validate_success(api.dispute_invoice(
        ctx["invoice"]["id"], make_customer_headers(ctx["customer"]["id"])
    ))
    assert inv["dispute_status"] == "DISPUTED", f"dispute_status={inv['dispute_status']}"
    assert inv["billing_status"] == "ISSUED", f"billing_status={inv['billing_status']}"


def test_resolve_dispute_leaves_billing_status_issued(api):
    """PRD §3.8: "Billing resolves a dispute when `dispute_status` is `DISPUTED`
    (otherwise `ERR_INVOICE_NOT_DISPUTED`); resolving moves `dispute_status` to
    `RESOLVED`, again leaving `billing_status` unchanged, after which the invoice may be
    settled."

    Design: Difficulty/non_linear_state_machine/invoice_parallel_dimensions_billing_and_dispute_independent
    """
    ctx = setup_completed_job_with_invoice(raw_fraction=0.10, measured_truck_fraction=0.10)
    validate_success(api.dispute_invoice(ctx["invoice"]["id"], make_customer_headers(ctx["customer"]["id"])))
    inv = validate_success(api.resolve_dispute(ctx["invoice"]["id"], BILLING))
    assert inv["dispute_status"] == "RESOLVED", f"dispute_status={inv['dispute_status']}"
    assert inv["billing_status"] == "ISSUED", f"billing_status={inv['billing_status']}"


# ─── transitive_cascade: cancel -> void -> minutes ────

def test_cancel_scheduled_job_voids_dispatch_and_clears_crew_minutes(api):
    """PRD §3.9: "If the job has a `RESERVED` or `ACTIVE` dispatch, that dispatch
    transitions to `VOIDED` and the crew's `reserved_minutes` is recomputed to drop its
    window."
    PRD §3.9: "A customer may cancel its own job while the job is in `ESTIMATED`,
    `SCHEDULED`, or `DISPATCHED` status (otherwise `ERR_JOB_NOT_CANCELLABLE`)."

    Cancel from SCHEDULED with a 120-min reserved window: job CANCELLED, dispatch VOIDED,
    reserved_minutes back to 0.

    Design: Difficulty/transitive_cascade/cancel_voids_dispatch_releases_crew_minutes_depth3
    """
    ctx = setup_scheduled_job(
        raw_fraction=0.10,
        window_start_utc="2026-06-10T09:00:00.000Z",
        window_end_utc="2026-06-10T11:00:00.000Z",
    )
    job = validate_success(api.cancel_haul_job(ctx["job"]["id"], make_customer_headers(ctx["customer"]["id"])))
    assert job["status"] == "CANCELLED", f"status={job['status']}"
    dispatch = validate_success(api.get_dispatch(ctx["dispatch"]["id"], DISPATCHER))
    assert dispatch["dispatch_status"] == "VOIDED", f"dispatch_status={dispatch['dispatch_status']}"
    crew = validate_success(api.get_crew(ctx["crew"]["id"], DISPATCHER))
    assert crew["reserved_minutes"] == 0, f"reserved_minutes={crew['reserved_minutes']}"


def test_cancel_scheduled_job_assesses_scheduled_cancellation_fee(api):
    """PRD §3.9: "a `SCHEDULED` job cancels with a fee equal to its
    `estimated_total_cents` multiplied by the policy's `cancel_pct_scheduled`, rounded".

    estimated_total for raw 0.30 (billed 0.375, no items, SCHEDULED) = 21750; cancel fee
    round(21750*0.25) = 5438.

    Design: Difficulty/transitive_cascade/cancel_voids_dispatch_releases_crew_minutes_depth3
    """
    ctx = setup_scheduled_job(
        raw_fraction=0.30,
        window_start_utc="2026-06-10T09:00:00.000Z",
        window_end_utc="2026-06-10T11:00:00.000Z",
    )
    job = validate_success(api.cancel_haul_job(ctx["job"]["id"], make_customer_headers(ctx["customer"]["id"])))
    assert job["cancellation_fee_cents"] == 5438, f"cancellation_fee_cents={job['cancellation_fee_cents']}"


# ─── transitive_cascade: complete -> invoice -> balance

def test_complete_issues_service_invoice_with_final_total(api):
    """PRD §3.8: "Completion issues a **service invoice**: a new `Invoice` is created with
    `kind` `SERVICE`, `billing_status` `ISSUED`, `dispute_status` `NONE`, `total_cents`
    equal to the job's `final_total_cents`, and `customer_id` copied from the job."

    final for measured 0.10 (billed 0.125, no items) = 8100.

    Design: Difficulty/transitive_cascade/complete_issues_invoice_bumps_customer_balance_depth2
    """
    ctx = setup_completed_job_with_invoice(raw_fraction=0.10, measured_truck_fraction=0.10)
    inv = ctx["invoice"]
    assert inv["kind"] == "SERVICE", f"kind={inv['kind']}"
    assert inv["billing_status"] == "ISSUED", f"billing_status={inv['billing_status']}"
    assert inv["total_cents"] == 8100, f"total_cents={inv['total_cents']}"
    assert ctx["job"]["final_total_cents"] == 8100, f"final={ctx['job']['final_total_cents']}"


def test_complete_raises_customer_outstanding_balance(api):
    """PRD §3.8: "Issuing that invoice raises the customer's `outstanding_balance_cents`
    (recomputed from the customer's `ISSUED` invoice set, per §2.9)."

    Single issued invoice of 8100 -> balance 8100.

    Design: Difficulty/transitive_cascade/complete_issues_invoice_bumps_customer_balance_depth2
    """
    ctx = setup_completed_job_with_invoice(raw_fraction=0.10, measured_truck_fraction=0.10)
    cust = validate_success(api.get_customer(ctx["customer"]["id"], make_customer_headers(ctx["customer"]["id"])))
    assert cust["outstanding_balance_cents"] == 8100, f"balance={cust['outstanding_balance_cents']}"


# ─── compensating_invariant ───────────────────────────

def test_crew_minutes_conserved_after_dispatch_then_cancel(api):
    """PRD §3.5: "A crew's `reserved_minutes` is at all times the sum, in whole minutes,
    of the window lengths of every dispatch on that crew whose `dispatch_status` is
    `RESERVED` or `ACTIVE`. It is recomputed from that set — never delta-drifted — on
    every dispatch creation, void, or release, and starts at 0 for a new crew."

    Reserve a 120-min window then cancel the job: the invariant holds, so reserved_minutes
    returns to its pre-reserve baseline of 0.

    Design: Difficulty/compensating_invariant/crew_minutes_conserved_dispatch_then_cancel
    """
    ctx = setup_scheduled_job(
        raw_fraction=0.10,
        window_start_utc="2026-06-10T09:00:00.000Z",
        window_end_utc="2026-06-10T11:00:00.000Z",
    )
    crew_after = validate_success(api.get_crew(ctx["crew"]["id"], DISPATCHER))
    assert crew_after["reserved_minutes"] == 120, f"reserved after dispatch={crew_after['reserved_minutes']}"
    validate_success(api.cancel_haul_job(ctx["job"]["id"], make_customer_headers(ctx["customer"]["id"])))
    crew_final = validate_success(api.get_crew(ctx["crew"]["id"], DISPATCHER))
    assert crew_final["reserved_minutes"] == 0, f"reserved after cancel={crew_final['reserved_minutes']}"


def test_crew_reserved_minutes_equals_window_length_while_reserved(api):
    """PRD §3.5: "A crew's `reserved_minutes` is at all times the sum, in whole minutes,
    of the window lengths of every dispatch on that crew whose `dispatch_status` is
    `RESERVED` or `ACTIVE`."

    With one RESERVED 120-minute dispatch on the crew, the conserved quantity equals the
    window length (the recompute-on-create direction of the invariant).

    Design: Difficulty/compensating_invariant/crew_minutes_conserved_dispatch_then_cancel
    """
    ctx = setup_scheduled_job(
        raw_fraction=0.10,
        window_start_utc="2026-06-10T09:00:00.000Z",
        window_end_utc="2026-06-10T11:00:00.000Z",
    )
    crew = validate_success(api.get_crew(ctx["crew"]["id"], DISPATCHER))
    assert crew["reserved_minutes"] == 120, f"reserved_minutes={crew['reserved_minutes']}"


def test_customer_balance_conserved_after_issue_then_settle(api):
    """PRD §2.9: "It is defined as the sum of `total_cents` over every invoice belonging
    to that customer whose `billing_status` is `ISSUED` ... Issuing an invoice (on job
    completion, or on a cancellation that carries a fee) raises the balance; settling an
    invoice lowers it."

    Issue 8100 then settle it: the recomputed balance returns to 0 (no ISSUED invoices
    remain).

    Design: Difficulty/compensating_invariant/customer_balance_conserved_issue_then_settle
    """
    ctx = setup_completed_job_with_invoice(raw_fraction=0.10, measured_truck_fraction=0.10)
    inv = validate_success(api.settle_invoice(ctx["invoice"]["id"], BILLING))
    assert inv["billing_status"] == "SETTLED", f"billing_status={inv['billing_status']}"
    cust = validate_success(api.get_customer(ctx["customer"]["id"], make_customer_headers(ctx["customer"]["id"])))
    assert cust["outstanding_balance_cents"] == 0, f"balance={cust['outstanding_balance_cents']}"


def test_customer_balance_equals_issued_total_before_settle(api):
    """PRD §2.9: "It is defined as the sum of `total_cents` over every invoice belonging
    to that customer whose `billing_status` is `ISSUED` — that is, invoices that have been
    billed but not yet settled."

    Before settling, the single ISSUED SERVICE invoice (8100) is the whole of the
    conserved money quantity, so the balance equals it exactly.

    Design: Difficulty/compensating_invariant/customer_balance_conserved_issue_then_settle
    """
    ctx = setup_completed_job_with_invoice(raw_fraction=0.10, measured_truck_fraction=0.10)
    cust = validate_success(api.get_customer(ctx["customer"]["id"], make_customer_headers(ctx["customer"]["id"])))
    assert cust["outstanding_balance_cents"] == 8100, f"balance={cust['outstanding_balance_cents']}"


# ─── corner: state_machines (invalid / guarded transitions) ─

def test_dispatch_from_draft_job_rejected_not_estimated(api):
    """PRD §3.4: "The job must be in `ESTIMATED` status (otherwise
    `ERR_JOB_NOT_ESTIMATED`)."

    Design: Corner/state_machines/dispatch_from_draft_job_returns_job_not_estimated
    """
    from test_helpers import create_policy, create_customer, create_crew, create_truck, create_job
    from test_helpers import create_dispatch_payload
    create_policy()
    cust = create_customer()
    crew = create_crew()
    truck = create_truck()
    job = create_job(cust["id"])  # remains DRAFT
    crew_v = validate_success(api.get_crew(crew["id"], DISPATCHER))["version"]
    resp = api.create_dispatch(
        create_dispatch_payload(job["id"], crew["id"], truck["id"], crew_v), DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_ESTIMATED.value)


def test_cancel_completed_job_rejected_not_cancellable(api):
    """PRD §3.9: "A customer may cancel its own job while the job is in `ESTIMATED`,
    `SCHEDULED`, or `DISPATCHED` status (otherwise `ERR_JOB_NOT_CANCELLABLE`)."

    Design: Corner/state_machines/cancel_completed_job_returns_not_cancellable
    """
    ctx = setup_completed_job_with_invoice(raw_fraction=0.10, measured_truck_fraction=0.10)
    resp = api.cancel_haul_job(ctx["job"]["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_CANCELLABLE.value)


def test_activate_already_active_dispatch_rejected_not_reserved(api):
    """PRD §3.6: "Activation requires the dispatch to be `RESERVED` (otherwise
    `ERR_DISPATCH_NOT_RESERVED`) and the crew to be `ON_DUTY` (otherwise
    `ERR_CREW_OFF_DUTY`); it transitions the dispatch `RESERVED → ACTIVE` and drives the
    job `SCHEDULED → DISPATCHED`."

    Design: Corner/state_machines/activate_already_active_dispatch_returns_not_reserved
    """
    ctx = setup_dispatched_job(raw_fraction=0.10)
    resp = api.activate_dispatch(ctx["dispatch"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_DISPATCH_NOT_RESERVED.value)


def test_resolve_dispute_when_not_disputed_rejected(api):
    """PRD §3.8: "Billing resolves a dispute when `dispute_status` is `DISPUTED`
    (otherwise `ERR_INVOICE_NOT_DISPUTED`)".

    Design: Corner/state_machines/resolve_dispute_when_not_disputed_returns_not_disputed
    """
    ctx = setup_completed_job_with_invoice(raw_fraction=0.10, measured_truck_fraction=0.10)
    resp = api.resolve_dispute(ctx["invoice"]["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_DISPUTED.value)


def test_settle_disputed_invoice_blocked(api):
    """PRD §3.8: "Billing settles an invoice that is `ISSUED` (otherwise
    `ERR_INVOICE_NOT_ISSUED`), is not currently `DISPUTED` (otherwise
    `ERR_INVOICE_DISPUTED`), and whose linked job is in the appropriate terminal state".

    Design: Corner/state_machines/settle_disputed_invoice_blocked
    """
    ctx = setup_completed_job_with_invoice(raw_fraction=0.10, measured_truck_fraction=0.10)
    validate_success(api.dispute_invoice(ctx["invoice"]["id"], make_customer_headers(ctx["customer"]["id"])))
    resp = api.settle_invoice(ctx["invoice"]["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_INVOICE_DISPUTED.value)


# ─── cross_entity_state_dependency: settle billable ──

def test_settle_cancellation_invoice_succeeds_when_job_cancelled(api):
    """PRD §3.8: "whose linked job is in the appropriate terminal state — `COMPLETED` for
    a `SERVICE` invoice or `CANCELLED` for a `CANCELLATION` invoice (otherwise
    `ERR_JOB_NOT_BILLABLE`). Settling transitions `billing_status` `ISSUED → SETTLED` and
    recomputes the customer's `outstanding_balance_cents` downward".

    DISPATCHED job cancelled -> fee round(7500*0.50)=3750 cancellation invoice; the linked
    job is CANCELLED so settle is allowed and balance returns to 0.

    Design: Difficulty/cross_entity_state_dependency/settle_blocked_until_linked_job_completed
    """
    ctx = setup_cancellation_invoice_after_dispatched_cancel(raw_fraction=0.10)
    assert ctx["job"]["cancellation_fee_cents"] == 3750, f"fee={ctx['job']['cancellation_fee_cents']}"
    inv = validate_success(api.settle_invoice(ctx["invoice"]["id"], BILLING))
    assert inv["billing_status"] == "SETTLED", f"billing_status={inv['billing_status']}"
    cust = validate_success(api.get_customer(ctx["customer"]["id"], make_customer_headers(ctx["customer"]["id"])))
    assert cust["outstanding_balance_cents"] == 0, f"balance={cust['outstanding_balance_cents']}"


def test_cancellation_invoice_issued_for_dispatched_cancel_with_fee(api):
    """PRD §3.9: "If the cancellation fee is greater than 0, a **cancellation invoice** is
    issued: a new `Invoice` with `kind` `CANCELLATION`, `billing_status` `ISSUED`,
    `dispute_status` `NONE`, and `total_cents` equal to the cancellation fee, and the
    customer's `outstanding_balance_cents` is recomputed upward accordingly."

    A DISPATCHED job cancelled produces a CANCELLATION invoice (fee 3750) whose linked job
    is CANCELLED — the terminal state the settle guard requires.

    Design: Difficulty/cross_entity_state_dependency/settle_blocked_until_linked_job_completed
    """
    ctx = setup_cancellation_invoice_after_dispatched_cancel(raw_fraction=0.10)
    inv = ctx["invoice"]
    assert inv["kind"] == "CANCELLATION", f"kind={inv['kind']}"
    assert inv["billing_status"] == "ISSUED", f"billing_status={inv['billing_status']}"
    assert inv["total_cents"] == 3750, f"total_cents={inv['total_cents']}"
    job = validate_success(api.get_haul_job(ctx["job"]["id"], make_customer_headers(ctx["customer"]["id"])))
    assert job["status"] == "CANCELLED", f"status={job['status']}"
