"""Dual control on the approval axis, and the settlement axis end to end."""

from test_helpers import (
    ApiErrorId,
    SPECIALIST_USER_ID,
    TEST_USERS,
    add_payee,
    api_client,
    approval_decision_payload,
    assert_ledger_identity,
    assert_payment,
    cancel_payment,
    list_ledger_entries,
    make_fiduciary_manager_headers,
    payment_request,
    post_adjustment,
    read_account,
    read_bond,
    read_budget_category,
    read_payee,
    read_payment,
    reject_payment,
    release_payment,
    revise_payment_payload,
    schedule_payment,
    set_clock,
    settle_payment,
    settlement_event_payload,
    setup_billpay_world,
    return_payment,
    validate_error,
    validate_success,
)

SPECIALIST = TEST_USERS["bill_pay_specialist_headers"]
SPECIALIST_ALT = TEST_USERS["bill_pay_specialist_alt_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
MANAGER = TEST_USERS["fiduciary_manager_headers"]


def test_a_payment_of_exactly_the_threshold_lands_in_dual_control():
    """PRD §3.3: "On the approval axis, the machine's entry state `PREPARED` is
    resolved inside the very same request: a payment whose `amount_cents` is
    **below** 100000 cents lands in `APPROVED` under single control with
    `approved_by_user_id` left null, and a payment whose `amount_cents` is **at
    or above** 100000 cents lands in `PENDING_SECOND_APPROVAL` under dual
    control. The threshold boundary is inclusive on the dual-control side — a
    payment of exactly 100000 cents needs a second approver."

    Design: Difficulty/boundary_precision_check/second_approval_threshold_is_inclusive_at_exactly_one_hundred_thousand
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")

    payment = schedule_payment(world, amount_cents=100000, channel="ACH")

    assert_payment(payment)
    assert payment["approval_status"] == "PENDING_SECOND_APPROVAL"
    assert payment["settlement_status"] == "SCHEDULED"
    assert payment["service_fee_cents"] == 500
    assert payment["total_charge_cents"] == 100500
    assert payment["approved_by_user_id"] is None
    assert read_account(world["account"]["id"])["available_balance_cents"] == 4899500


def test_a_payment_one_cent_below_the_threshold_is_approved_under_single_control():
    """PRD §3.3: "a payment whose `amount_cents` is **below** 100000 cents
    lands in `APPROVED` under single control with `approved_by_user_id` left
    null, and a payment whose `amount_cents` is **at or above** 100000 cents
    lands in `PENDING_SECOND_APPROVAL` under dual control."

    Design: Difficulty/boundary_precision_check/second_approval_threshold_is_inclusive_at_exactly_one_hundred_thousand
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")

    payment = schedule_payment(world, amount_cents=99999, channel="ACH")

    assert payment["approval_status"] == "APPROVED"
    assert payment["approved_by_user_id"] is None
    assert payment["settlement_status"] == "SCHEDULED"


def test_the_preparer_cannot_approve_and_the_unapproved_payment_cannot_release():
    """PRD §2.9 rung 29: "**Segregation of duties.** The approver's
    `X-User-ID` differs from the payment's `prepared_by_user_id`. The same
    natural person may not prepare and approve the same disbursement even when
    acting under a different role. Otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD §2.9 rung 30: "**Second approval present.** The payment being released
    has `approval_status` equal to `APPROVED`. Otherwise
    `ERR_SECOND_APPROVAL_REQUIRED` (409). Applies to releasing a payment. A
    payment that is `SCHEDULED` but still `PENDING_SECOND_APPROVAL` therefore
    returns this code, never `ERR_INVALID_STATE`."

    Design: Corner/validations/corner_preparer_cannot_approve_and_unapproved_payment_cannot_release
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z", allocation_cents=400000)
    payment = schedule_payment(world, amount_cents=150000, channel="ACH")
    assert payment["prepared_by_user_id"] == SPECIALIST_USER_ID

    same_person_wearing_the_managers_hat = make_fiduciary_manager_headers(SPECIALIST_USER_ID)
    approval = api_client.decide_payment_approval(
        payment["id"],
        approval_decision_payload("APPROVE", note="Approving my own preparation."),
        same_person_wearing_the_managers_hat,
    )
    validate_error(approval, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    release = api_client.release_payment(payment["id"], SPECIALIST)
    validate_error(release, ApiErrorId.ERR_SECOND_APPROVAL_REQUIRED.value, 409)

    after = read_payment(payment["id"])
    assert after["approval_status"] == "PENDING_SECOND_APPROVAL"
    assert after["settlement_status"] == "SCHEDULED"
    assert after["approved_by_user_id"] is None


def test_a_bill_pay_specialist_is_not_on_the_approval_endpoint_at_all():
    """PRD §2.1: "A `BillPaySpecialist` prepares, revises, releases and settles
    disbursements, posts deposits and holds, and imports and matches statement
    lines. Under segregation of duties this role never appears on the approval
    endpoint at all."
    PRD §2.9 rung 2: "**Role authorization.** The caller's role appears in the
    endpoint's authorized-role list. Otherwise `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/rbac/corner_bill_pay_specialist_cannot_approve_a_payment
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z", allocation_cents=400000)
    payment = schedule_payment(world, amount_cents=150000, channel="ACH")

    response = api_client.decide_payment_approval(
        payment["id"], approval_decision_payload("APPROVE"), SPECIALIST_ALT
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    assert read_payment(payment["id"])["approval_status"] == "PENDING_SECOND_APPROVAL"


def test_rejecting_the_approval_leaves_the_settlement_axis_scheduled():
    """PRD §3.3: "A `REJECT` moves `approval_status` to `REJECTED`, sets
    `approved_by_user_id` back to null, and — this is the point of keeping the
    axes independent — **leaves `settlement_status` at `SCHEDULED`**, so the
    funds stay committed against the account, the budget line and the bond
    while the payment is reworked."

    Design: Difficulty/non_linear_state_machine/payment_approval_reject_revise_cycle_leaves_settlement_axis_untouched
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z", allocation_cents=400000)
    payment = schedule_payment(world, amount_cents=150000, channel="ACH")

    rejected = reject_payment(
        payment["id"], note="Invoice attached does not match the amount requested."
    )

    assert rejected["approval_status"] == "REJECTED"
    assert rejected["settlement_status"] == "SCHEDULED"
    assert rejected["approved_by_user_id"] is None
    assert read_account(world["account"]["id"])["committed_disbursements_cents"] == 150500
    assert read_budget_category(world["budget_category"]["id"])["committed_cents"] == 150000


def test_revising_a_rejected_payment_re_enters_dual_control_on_the_delta():
    """PRD §3.3: "It recomputes `service_fee_cents` and `total_charge_cents`
    from the revised principal using the same band table, adjusts the account's
    `committed_disbursements_cents` by the `total_charge_cents` delta and
    recomputes `available_balance_cents`, adjusts the budget line's
    `committed_cents` by the `amount_cents` delta and recomputes the variance
    figures, adjusts the bond's `exposure_committed_cents` by the
    `amount_cents` delta, and increments `revision_count` by one."
    PRD §3.3: "Where the rework lands depends only on the revised amount: a
    revised `amount_cents` at or above 100000 cents re-enters
    `PENDING_SECOND_APPROVAL` for another round of dual control, and a revised
    `amount_cents` below 100000 cents goes straight to `APPROVED`, dropping the
    payment out of dual control entirely."

    Design: Difficulty/non_linear_state_machine/payment_approval_reject_revise_cycle_leaves_settlement_axis_untouched
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z", allocation_cents=400000)
    payment = schedule_payment(world, amount_cents=150000, channel="ACH")
    reject_payment(payment["id"], note="Invoice attached does not match the amount requested.")

    response = api_client.revise_payment(
        payment["id"],
        revise_payment_payload(120000, memo="Corrected to the invoiced amount."),
        SPECIALIST,
    )
    revised = validate_success(response, 200)

    assert revised["approval_status"] == "PENDING_SECOND_APPROVAL"
    assert revised["settlement_status"] == "SCHEDULED"
    assert revised["revision_count"] == 1
    assert revised["amount_cents"] == 120000
    assert revised["service_fee_cents"] == 500
    assert revised["total_charge_cents"] == 120500

    account = read_account(world["account"]["id"])
    assert account["committed_disbursements_cents"] == 120500
    assert account["available_balance_cents"] == 4879500
    assert read_budget_category(world["budget_category"]["id"])["committed_cents"] == 120000


def test_a_returned_payment_applies_the_nsf_fee_and_unwinds_the_counters():
    """PRD §3.4: "It appends two more entries dated the current logical date: a
    `RETURN_REVERSAL` of positive `total_charge_cents`, giving back principal
    and fee alike, and an `NSF_FEE` of negative 3500 cents. The net effect on
    the account is therefore `total_charge_cents` minus 3500 cents — the
    compensation is deliberately lossy by exactly the insufficient-funds fee."
    PRD §3.4: "The payee's `settled_payment_count` falls by one. The budget
    line's `committed_cents` **and** `settled_cents` both fall by
    `amount_cents` and the variance figures are recomputed."

    Design: Corner/state_machines/corner_returned_payment_applies_nsf_fee_and_unwinds_counters
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    payment = schedule_payment(world, amount_cents=80000, channel="ACH")
    release_payment(payment["id"])
    settle_payment(payment["id"])

    returned = return_payment(payment["id"], "Account closed at the receiving bank.")

    assert returned["settlement_status"] == "RETURNED"
    account = read_account(world["account"]["id"])
    assert account["cleared_balance_cents"] == 4996500
    assert account["available_balance_cents"] == 4996500
    assert account["committed_disbursements_cents"] == 0
    assert read_payee(world["payee"]["id"])["settled_payment_count"] == 0
    line = read_budget_category(world["budget_category"]["id"])
    assert line["committed_cents"] == 0
    assert line["settled_cents"] == 0

    entries = list_ledger_entries(world["account"]["id"])
    assert len(entries) == 4, f"Expected four ledger entries, got {entries}"
    assert sorted(entry["entry_type"] for entry in entries) == [
        "DISBURSEMENT",
        "NSF_FEE",
        "RETURN_REVERSAL",
        "SERVICE_FEE",
    ]
    assert sum(entry["amount_cents"] for entry in entries) == -3500
    assert_ledger_identity(account, entries)


def test_cancelling_an_already_cancelled_payment_is_refused():
    """PRD §3.4: "It starts at `SCHEDULED`, advances through `IN_FLIGHT` to
    `SETTLED`, and has three terminal exits — `CANCELLED`, `STOPPED`, and
    `RETURNED` — the last of which is reached from `SETTLED`, after the money
    has already moved."
    PRD §2.9 rung 12: "**State gate.** The target row is in a from-state that
    its transition table permits for this trigger, terminal states included.
    Otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/corner_cancel_an_already_cancelled_payment_is_rejected
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    payment = schedule_payment(world, amount_cents=80000, channel="ACH")
    cancel_payment(payment["id"], reason="Bill already paid.")

    response = api_client.cancel_payment(
        payment["id"], {"reason": "Cancelling again by mistake."}, SPECIALIST
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert read_payment(payment["id"])["settlement_status"] == "CANCELLED"
    account = read_account(world["account"]["id"])
    assert account["committed_disbursements_cents"] == 0
    assert account["available_balance_cents"] == 5000000
    assert read_budget_category(world["budget_category"]["id"])["committed_cents"] == 0


def test_a_stop_one_second_past_the_window_is_refused():
    """PRD §3.4: "A stop is legal from either `SCHEDULED` or `IN_FLIGHT` — the
    two branches behave identically — and it is bounded by a window: the
    current logical instant must be at or before the payment's `created_at`
    plus 48 hours, with the boundary inclusive, so a stop request landing at
    exactly 48 hours after creation still succeeds and one at 48 hours and one
    second is refused with `ERR_STOP_WINDOW_EXPIRED` at rung 21."

    Design: Corner/validations/corner_stop_payment_one_second_past_the_window_is_rejected
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    payment = schedule_payment(world, amount_cents=80000, channel="ACH")

    set_clock("2026-06-03T09:00:01Z")
    response = api_client.stop_payment(
        payment["id"], {"stop_reason": "Client changed their mind about this vendor."}, MANAGER
    )

    validate_error(response, ApiErrorId.ERR_STOP_WINDOW_EXPIRED.value, 409)
    assert read_payment(payment["id"])["settlement_status"] == "SCHEDULED"
    assert read_account(world["account"]["id"])["cleared_balance_cents"] == 5000000
    entries = list_ledger_entries(world["account"]["id"])
    assert [e for e in entries if e["entry_type"] == "STOP_PAYMENT_FEE"] == []


def test_a_settled_payment_refuses_a_stop_at_the_state_gate_not_the_window_rung():
    """PRD §2.9: "When a single request violates several rules at once, exactly
    one error comes back, and which one is fully determined: the rung with the
    lowest number wins."
    PRD §2.9 rung 12: "**State gate.** The target row is in a from-state that
    its transition table permits for this trigger, terminal states included.
    Otherwise `ERR_INVALID_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/terminal_settlement_state_wins_over_expired_stop_payment_window
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    payment = schedule_payment(world, amount_cents=80000, channel="ACH")
    release_payment(payment["id"])
    set_clock("2026-06-03T09:00:00Z")
    settle_payment(payment["id"])

    # Four days after creation, so the 48-hour stop window closed two days ago
    # as well; the state gate must still be the one that answers.
    set_clock("2026-06-05T09:00:00Z")
    response = api_client.stop_payment(
        payment["id"], {"stop_reason": "Family asked us to claw this back."}, MANAGER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_the_settled_payment_is_untouched_by_the_refused_stop():
    """PRD §3.4: "A `SETTLE` moves the payment `IN_FLIGHT` → `SETTLED` and
    writes the current logical date to `settled_on`, which is the moment that
    starts the dispute filing window."
    PRD §3.4: "The account's `committed_disbursements_cents` falls by
    `total_charge_cents` while its `cleared_balance_cents` falls by the same
    total, so `available_balance_cents` is exactly unchanged by settlement —
    the money simply moves from promised to gone."

    Design: Difficulty/priority_pair_validation_conflict/terminal_settlement_state_wins_over_expired_stop_payment_window
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    payment = schedule_payment(world, amount_cents=80000, channel="ACH")
    release_payment(payment["id"])
    set_clock("2026-06-03T09:00:00Z")
    settle_payment(payment["id"])

    set_clock("2026-06-05T09:00:00Z")
    api_client.stop_payment(
        payment["id"], {"stop_reason": "Family asked us to claw this back."}, MANAGER
    )

    after = read_payment(payment["id"])
    assert after["settlement_status"] == "SETTLED"
    assert after["settled_on"] == "2026-06-03"
    assert read_account(world["account"]["id"])["cleared_balance_cents"] == 4919500


def test_scheduling_commits_and_cancelling_restores_the_available_balance():
    """PRD §2.12: "**Account availability.** An account's
    `available_balance_cents` equals its `cleared_balance_cents` minus its
    `pending_holds_cents` minus its `committed_disbursements_cents`. This
    quantity is conserved across compensating actions: scheduling a payment and
    then cancelling it leaves `available_balance_cents` exactly as it was
    before the schedule"

    Design: Difficulty/compensating_invariant/schedule_then_cancel_conserves_account_available_balance
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    post_adjustment(
        world["account"]["id"],
        "WITHDRAWAL_HOLD",
        120000,
        "2026-06-01",
        memo="Pending debit-card authorisation.",
    )
    before = read_account(world["account"]["id"])
    assert before["available_balance_cents"] == 4880000

    payment = schedule_payment(world, amount_cents=80000, channel="ACH")
    committed = read_account(world["account"]["id"])
    assert committed["available_balance_cents"] == 4799500

    cancel_payment(payment["id"], reason="Bill was paid directly by the client's daughter.")

    after = read_account(world["account"]["id"])
    assert after["available_balance_cents"] == 4880000
    assert after["cleared_balance_cents"] == 5000000
    assert after["pending_holds_cents"] == 120000
    assert after["committed_disbursements_cents"] == 0
    assert read_payment(payment["id"])["settlement_status"] == "CANCELLED"


def test_a_cancellation_appends_no_ledger_entry():
    """PRD §3.4: "Crucially, **cancellation appends no ledger entry at all** —
    no money ever left the account, so there is nothing to record and there is
    deliberately no cancellation entry type in the ledger's vocabulary."
    PRD §2.12: "**The ledger identity.** An account's `cleared_balance_cents`
    minus its `opening_balance_cents` equals the signed sum of `amount_cents`
    over every `LedgerEntry` belonging to that account, frozen entries
    included."

    Design: Difficulty/compensating_invariant/schedule_then_cancel_conserves_account_available_balance
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    post_adjustment(
        world["account"]["id"],
        "WITHDRAWAL_HOLD",
        120000,
        "2026-06-01",
        memo="Pending debit-card authorisation.",
    )
    payment = schedule_payment(world, amount_cents=80000, channel="ACH")

    cancel_payment(payment["id"], reason="Bill was paid directly by the client's daughter.")

    entries = list_ledger_entries(world["account"]["id"])
    assert [e for e in entries if e.get("source_payment_id") == payment["id"]] == [], (
        "a cancellation must append no ledger entry"
    )
    assert_ledger_identity(read_account(world["account"]["id"]), entries)


def test_two_scheduled_payments_raise_the_organization_wide_committed_exposure():
    """PRD §3.3: "`exposure_committed_cents` is the sum of `amount_cents` over
    **every payment belonging to any client in the system** whose
    `settlement_status` is `SCHEDULED` or `IN_FLIGHT` — money promised but not
    yet gone."

    Design: Difficulty/compensating_invariant/schedule_then_cancel_conserves_organization_wide_bond_exposure
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    second_payee = add_payee(world)

    schedule_payment(world, amount_cents=50000, channel="ACH", payee=second_payee)
    schedule_payment(world, amount_cents=80000, channel="ACH")

    bond = read_bond(world["bond"]["id"])
    assert bond["exposure_committed_cents"] == 130000
    assert bond["headroom_committed_cents"] == 99870000


def test_cancelling_one_payment_releases_exactly_its_own_bond_exposure():
    """PRD §2.12: "**Organization-wide committed exposure.** Scheduling a
    payment and then cancelling it leaves the bond's
    `exposure_committed_cents` identical to its pre-scheduling value."
    PRD §3.4: "Cancellation is the exact compensating action for scheduling:
    the account's `committed_disbursements_cents` falls by `total_charge_cents`
    and `available_balance_cents` is recomputed, the budget line's
    `committed_cents` falls by `amount_cents` and its variance figures are
    recomputed, and the bond's `exposure_committed_cents` falls by
    `amount_cents`."

    Design: Difficulty/compensating_invariant/schedule_then_cancel_conserves_organization_wide_bond_exposure
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    second_payee = add_payee(world)
    kept = schedule_payment(world, amount_cents=50000, channel="ACH", payee=second_payee)
    doomed = schedule_payment(world, amount_cents=80000, channel="ACH")

    cancel_payment(
        doomed["id"],
        reason="Duplicate of a payment the family already made.",
        headers=MANAGER,
    )

    bond = read_bond(world["bond"]["id"])
    assert bond["exposure_committed_cents"] == 50000
    assert bond["headroom_committed_cents"] == 99950000
    assert read_payment(kept["id"])["settlement_status"] == "SCHEDULED"
    assert read_payment(doomed["id"])["settlement_status"] == "CANCELLED"
    assert read_account(world["account"]["id"])["committed_disbursements_cents"] == 50500
    assert read_budget_category(world["budget_category"]["id"])["committed_cents"] == 50000
