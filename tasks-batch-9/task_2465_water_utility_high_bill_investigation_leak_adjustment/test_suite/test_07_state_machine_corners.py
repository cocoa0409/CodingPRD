"""State-machine corners of the high-bill workflow.

Every declared trigger must move its entity exactly one declared step, refuse
every step that is not declared from the current state, apply the whole set of
side effects a transition promises, and cascade into the derived layers —
ledger, balance, credit status, service status — without firing effects that
belong to a different branch.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    CSR_HEADERS,
    SUPERVISOR_HEADERS,
    TECHNICIAN_HEADERS,
    assertions,
    factories,
    fixtures,
)

# The two single-month SUMMER periods the billing chains below are built on.
JUNE_PERIOD = {
    "period_code": "2025-06",
    "start_date": "2025-06-01",
    "end_date": "2025-06-30",
    "season": "SUMMER",
    "rebilling_deadline_date": "2026-12-31",
}
JULY_PERIOD = {
    "period_code": "2025-07",
    "start_date": "2025-07-01",
    "end_date": "2025-07-31",
    "season": "SUMMER",
    "rebilling_deadline_date": "2026-12-31",
}

# A 4000-gallon SUMMER period on the standard tariff.
FOUR_KGAL_TOTAL_CENTS = 5210


def _june_draft_bill(api):
    """One OPEN June period carrying one DRAFT 4000-gallon bill."""
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    period = fixtures.create_billing_period(api, **JUNE_PERIOD)
    account = fixtures.create_account(api, schedule["id"])
    meter = fixtures.create_master_meter(api, account["id"])
    fixtures.post_reading(api, meter["id"], "2025-05-31", 100000)
    fixtures.post_reading(api, meter["id"], "2025-06-30", 104000)
    bill = fixtures.generate_bill(api, account["id"], period["id"], meter["id"])
    return {
        "period": period,
        "period_id": period["id"],
        "account": account,
        "account_id": account["id"],
        "meter_id": meter["id"],
        "bill": bill,
        "bill_id": bill["id"],
    }


def _june_issued_bill(api):
    """The June chain with its bill ISSUED, leaving the account past due."""
    ctx = _june_draft_bill(api)
    ctx["bill"] = fixtures.issue_bill(api, ctx["bill_id"])
    return ctx


def _two_period_draft_bills(api):
    """A LOCKED June period and a CLOSED July period, one DRAFT bill each."""
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    june = fixtures.create_billing_period(api, **JUNE_PERIOD)
    july = fixtures.create_billing_period(api, **JULY_PERIOD)
    account = fixtures.create_account(api, schedule["id"])
    meter = fixtures.create_master_meter(api, account["id"])
    for read_date, value in (
        ("2025-05-31", 100000),
        ("2025-06-30", 104000),
        ("2025-07-31", 108000),
    ):
        fixtures.post_reading(api, meter["id"], read_date, value)
    june_bill = fixtures.generate_bill(api, account["id"], june["id"], meter["id"])
    july_bill = fixtures.generate_bill(api, account["id"], july["id"], meter["id"])
    fixtures.lock_period(api, june["id"])
    fixtures.close_period(api, july["id"])
    return {
        "june_id": june["id"],
        "july_id": july["id"],
        "account_id": account["id"],
        "meter_id": meter["id"],
        "june_bill_id": june_bill["id"],
        "july_bill_id": july_bill["id"],
    }


def test_close_then_lock_walks_a_billing_period_exactly_one_step(api):
    """PRD §2.10: "A `BillingPeriod` advances through exactly two transitions, both driven by a `SystemAdmin`, and its `status` starts at `OPEN`."

    PRD §2.10: "Closing an `OPEN` period moves it to `CLOSED`; from that point no further bill may be created for the period and an attempt returns `ERR_BILLING_PERIOD_CLOSED`, but leak-adjustment posting and rebilling remain permitted so that in-flight disputes can still settle."
    PRD §2.4: "Any operation that changes a row refreshes its `updated_at` and increments its `version`, including changes made as a downstream side effect of an operation aimed at a different resource."

    Design: Corner/state_machines/corner_state_valid_transition_billing_period_open_close_lock_chain
    """
    fixtures.set_clock(api)
    created = fixtures.create_billing_period(api, **JUNE_PERIOD)
    assertions.assert_fields(created, status="OPEN", version=1)

    closed = validate_success(api.close_billing_period(created["id"], ADMIN_HEADERS))
    assertions.assert_fields(closed, status="CLOSED", version=2)

    locked = validate_success(api.lock_billing_period(created["id"], ADMIN_HEADERS))
    assertions.assert_fields(locked, status="LOCKED", version=3)

    # Neither trigger is allowed to touch any other field of the period.
    assertions.assert_fields(
        locked,
        period_code="2025-06",
        start_date="2025-06-01",
        end_date="2025-06-30",
        season="SUMMER",
        rebilling_deadline_date="2026-12-31",
    )

    rows, meta = validate_paginated(
        api.list_billing_periods(ADMIN_HEADERS, {"status": "LOCKED"})
    )
    assertions.assert_pagination_meta(meta, total_count=1)
    assertions.assert_listing_ids(rows, [created["id"]])


def test_locked_period_blocks_bill_issue_while_a_closed_period_permits_it(api):
    """PRD §3.2: "Issuing moves the bill from `DRAFT` to `ISSUED` and is permitted while the period is `OPEN` or `CLOSED`."

    PRD §2.7: "The subject entity must sit in a state from which the requested transition exists, and every cross-entity state precondition of that transition must hold → `ERR_INVALID_STATE_TRANSITION` (409) on every action operation."
    PRD §3.2: "Issuing stamps `due_date` as the period's `end_date` plus twenty-one calendar days, inserts a `CHARGE` ledger entry with `source_kind` `BILL_CHARGE` for the positive `total_charge_cents`, naming this bill in both `bill_id` and `source_id`, and then recomputes the account's `balance_cents`, then its `credit_status`, then its `service_status`, in that order."

    Design: Corner/state_machines/corner_state_precondition_enforcement_period_status_gates_bill_create_and_issue
    """
    ctx = _two_period_draft_bills(api)

    validate_error(
        api.issue_bill(ctx["june_bill_id"], SUPERVISOR_HEADERS),
        "ERR_INVALID_STATE_TRANSITION",
    )
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["june_bill_id"]), billing_status="DRAFT"
    )

    issued = validate_success(api.issue_bill(ctx["july_bill_id"], SUPERVISOR_HEADERS))
    assertions.assert_fields(
        issued, billing_status="ISSUED", due_date="2025-08-21"
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account, balance_cents=FOUR_KGAL_TOTAL_CENTS, credit_status="PAST_DUE"
    )
    entries = assertions.ledger_entries(api, ctx["account_id"], SUPERVISOR_HEADERS)
    assertions.assert_source_kinds(entries, ["BILL_CHARGE"])
    assertions.assert_balance_is_ledger_sum(account, entries)


def test_closed_period_refuses_bill_creation_ahead_of_the_duplicate_rule(api):
    """PRD §2.7: "Two state checks carry their own codes: opening an investigation requires the target bill to be `ISSUED` and requires that no non-terminal investigation already exists for it, else `ERR_INVESTIGATION_ALREADY_OPEN` (409); generating a bill requires its period to be `OPEN`, else `ERR_BILLING_PERIOD_CLOSED` (409)."

    PRD §3.2: "And no bill for the same meter and period may already exist in any state other than `REBILLED`, else `ERR_DUPLICATE_BILL_FOR_PERIOD`."

    Design: Corner/state_machines/corner_state_precondition_enforcement_period_status_gates_bill_create_and_issue
    """
    ctx = _two_period_draft_bills(api)
    fixtures.issue_bill(api, ctx["july_bill_id"])

    # The same body breaks both the closed-period gate and the duplicate rule;
    # the earlier check in the ladder is the one that must surface.
    validate_error(
        api.create_bill(
            factories.bill_payload(
                ctx["account_id"], ctx["july_id"], ctx["meter_id"]
            ),
            SUPERVISOR_HEADERS,
        ),
        "ERR_BILLING_PERIOD_CLOSED",
    )

    _rows, meta = validate_paginated(
        api.list_bills(SUPERVISOR_HEADERS, {"account_id": ctx["account_id"]})
    )
    assertions.assert_pagination_meta(meta, total_count=2)


def test_triggers_absent_from_the_current_state_are_refused(api):
    """PRD §3.5: "The operation is available only from `REBILL_PENDING`, is refused with `ERR_BILLING_PERIOD_LOCKED` when the period is `LOCKED`, and is refused with `ERR_REBILL_WINDOW_EXPIRED` when today's date on the logical clock is later than the period's `rebilling_deadline_date` — the deadline day itself is still inside the window."

    PRD §2.10: "Attempting to close a period that is not `OPEN`, or to lock a period that is not `CLOSED`, is an invalid transition."
    PRD §3.2: "Issuing moves the bill from `DRAFT` to `ISSUED` and is permitted while the period is `OPEN` or `CLOSED`."

    Design: Corner/state_machines/corner_state_invalid_transitions_triggers_absent_from_the_current_state_are_refused
    """
    ctx = _june_draft_bill(api)

    validate_error(
        api.rebill_bill(ctx["bill_id"], SUPERVISOR_HEADERS),
        "ERR_INVALID_STATE_TRANSITION",
    )
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]), billing_status="DRAFT"
    )

    validate_error(
        api.lock_billing_period(ctx["period_id"], ADMIN_HEADERS),
        "ERR_INVALID_STATE_TRANSITION",
    )
    assertions.assert_fields(
        validate_success(api.get_billing_period(ctx["period_id"], ADMIN_HEADERS)),
        status="OPEN",
    )

    issued = validate_success(api.issue_bill(ctx["bill_id"], SUPERVISOR_HEADERS))
    assertions.assert_fields(issued, billing_status="ISSUED", version=2)

    validate_error(
        api.issue_bill(ctx["bill_id"], SUPERVISOR_HEADERS),
        "ERR_INVALID_STATE_TRANSITION",
    )
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]), billing_status="ISSUED", version=2
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    entries = assertions.ledger_entries(api, ctx["account_id"], SUPERVISOR_HEADERS)
    assertions.assert_single_entry(
        entries, "BILL_CHARGE", amount_cents=FOUR_KGAL_TOTAL_CENTS
    )
    assertions.assert_account_state(account, balance_cents=FOUR_KGAL_TOTAL_CENTS)
    assertions.assert_balance_is_ledger_sum(account, entries)


def test_closing_an_already_closed_period_is_refused_without_effect(api):
    """PRD §2.10: "Attempting to close a period that is not `OPEN`, or to lock a period that is not `CLOSED`, is an invalid transition."

    PRD §2.4: "Any operation that changes a row refreshes its `updated_at` and increments its `version`, including changes made as a downstream side effect of an operation aimed at a different resource."

    Design: Corner/state_machines/corner_state_idempotency_repeating_a_completed_action_is_refused_without_side_effects
    """
    fixtures.set_clock(api)
    period = fixtures.create_billing_period(api, **JUNE_PERIOD)
    closed = fixtures.close_period(api, period["id"])
    assertions.assert_fields(closed, status="CLOSED", version=2)

    validate_error(
        api.close_billing_period(period["id"], ADMIN_HEADERS),
        "ERR_INVALID_STATE_TRANSITION",
    )
    assertions.assert_fields(
        validate_success(api.get_billing_period(period["id"], ADMIN_HEADERS)),
        status="CLOSED",
        version=2,
    )


def test_replayed_schedule_shutoff_does_not_re_anchor_the_statutory_notice(api):
    """PRD §3.8: "The account must be in `ACTIVE` service and its `credit_status` must be `PAST_DUE` or `ARRANGEMENT_DEFAULTED`."

    PRD §3.8: "Scheduling sets `shutoff_scheduled_for` to the current logical-clock instant plus a ten-calendar-day statutory notice and moves `service_status` to `SHUTOFF_SCHEDULED`."

    Design: Corner/state_machines/corner_state_idempotency_repeating_a_completed_action_is_refused_without_side_effects
    """
    ctx = _june_issued_bill(api)
    scheduled = validate_success(
        api.schedule_shutoff(ctx["account_id"], SUPERVISOR_HEADERS)
    )
    assertions.assert_account_state(
        scheduled, service_status="SHUTOFF_SCHEDULED", credit_status="PAST_DUE"
    )
    first_notice = scheduled["shutoff_scheduled_for"]
    assert first_notice.startswith("2026-08-11"), (
        f"notice anchored on the 2026-08-01 clock plus ten days, got {first_notice!r}"
    )

    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    validate_error(
        api.schedule_shutoff(ctx["account_id"], SUPERVISOR_HEADERS),
        "ERR_INVALID_STATE_TRANSITION",
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account,
        service_status="SHUTOFF_SCHEDULED",
        balance_cents=FOUR_KGAL_TOTAL_CENTS,
    )
    assert account["shutoff_scheduled_for"] == first_notice, (
        "a refused replay must not extend the customer's notice period"
    )
    entries = assertions.ledger_entries(api, ctx["account_id"], SUPERVISOR_HEADERS)
    assertions.assert_source_kinds(entries, ["BILL_CHARGE"])


def test_every_created_entity_starts_in_its_declared_initial_state(api):
    """PRD §2.10: "A `BillingPeriod` advances through exactly two transitions, both driven by a `SystemAdmin`, and its `status` starts at `OPEN`."

    PRD §3.2: "A newly generated bill sits in `DRAFT` with `rebill_of_bill_id` null and writes nothing to the ledger."
    PRD §3.1: "A fresh account starts fully clean: `service_status` is `ACTIVE`, `credit_status` is `CURRENT`, `balance_cents` is zero, both `open_investigation_hold_count` and `open_rebill_count` are zero, and `shutoff_scheduled_for` is null."
    PRD §3.8: "A new plan opens in `PROPOSED` with `paid_installment_count`, `missed_payment_count` and `reinstatement_count` all zero, and any other arrangement on the same account sitting in `PROPOSED` or `ACTIVE` is moved to the terminal `CANCELLED`, which stops it counting toward the account's `credit_status` and therefore triggers a recompute."
    PRD §3.8: "`installment_cents` is the financed amount divided by `installment_count`, taking the floor — the largest whole number of cents not exceeding the quotient — and it applies to every instalment from the first through the second-to-last."

    Design: Corner/state_machines/corner_state_initial_state_every_created_entity_starts_in_its_declared_initial_state
    """
    fixtures.set_clock(api)
    schedule = fixtures.create_rate_schedule(api)
    period = fixtures.create_billing_period(api, **JUNE_PERIOD)
    assertions.assert_fields(period, status="OPEN")

    account = fixtures.create_account(api, schedule["id"])
    assertions.assert_account_state(
        account,
        balance_cents=0,
        credit_status="CURRENT",
        service_status="ACTIVE",
        open_investigation_hold_count=0,
        open_rebill_count=0,
    )
    assertions.assert_null_fields(account, "shutoff_scheduled_for")

    meter = fixtures.create_master_meter(api, account["id"])
    fixtures.post_reading(api, meter["id"], "2025-05-31", 100000)
    fixtures.post_reading(api, meter["id"], "2025-06-30", 104000)

    bill = fixtures.generate_bill(api, account["id"], period["id"], meter["id"])
    assertions.assert_fields(bill, billing_status="DRAFT")
    assertions.assert_null_fields(bill, "rebill_of_bill_id")

    issued = fixtures.issue_bill(api, bill["id"])
    assertions.assert_fields(issued, billing_status="ISSUED")
    assertions.assert_account_state(
        fixtures.fetch_account(api, account["id"]),
        balance_cents=FOUR_KGAL_TOTAL_CENTS,
        credit_status="PAST_DUE",
    )

    arrangement = validate_success(
        api.create_payment_arrangement(
            factories.payment_arrangement_payload(
                account["id"],
                bill["id"],
                FOUR_KGAL_TOTAL_CENTS,
                1042,
                4,
                fixtures.account_version(api, account["id"]),
            ),
            CSR_HEADERS,
        ),
        expected_status=201,
    )
    assertions.assert_fields(
        arrangement,
        status="PROPOSED",
        paid_installment_count=0,
        missed_payment_count=0,
        reinstatement_count=0,
        installment_cents=1042,
        final_installment_cents=1042,
    )

    # A merely PROPOSED plan moves no money and pins no credit status.
    assertions.assert_account_state(
        fixtures.fetch_account(api, account["id"]),
        balance_cents=FOUR_KGAL_TOTAL_CENTS,
        credit_status="PAST_DUE",
    )
    assertions.assert_source_kinds(
        assertions.ledger_entries(api, account["id"], CSR_HEADERS), ["BILL_CHARGE"]
    )
    assertions.assert_fields(
        validate_success(api.get_billing_period(period["id"], ADMIN_HEADERS)),
        status="OPEN",
    )


def test_locked_period_refuses_both_declared_triggers_but_still_reads(api):
    """PRD §2.10: "Locking a `CLOSED` period moves it to `LOCKED`, the terminal state, after which every fiscal write touching a bill of that period is refused with `ERR_BILLING_PERIOD_LOCKED`: leak-adjustment approval, leak-adjustment denial, leak-adjustment reversal, rebilling, and the posting of a `CORRECTED` meter reading."

    PRD §2.10: "Attempting to close a period that is not `OPEN`, or to lock a period that is not `CLOSED`, is an invalid transition."

    Design: Corner/state_machines/corner_state_terminal_state_lockdown_locked_period_refuses_both_declared_triggers
    """
    fixtures.set_clock(api)
    period = fixtures.create_billing_period(api, **JUNE_PERIOD)
    locked = fixtures.lock_period(api, period["id"])
    assertions.assert_fields(locked, status="LOCKED", version=3)

    validate_error(
        api.close_billing_period(period["id"], ADMIN_HEADERS),
        "ERR_INVALID_STATE_TRANSITION",
    )
    validate_error(
        api.lock_billing_period(period["id"], ADMIN_HEADERS),
        "ERR_INVALID_STATE_TRANSITION",
    )

    read_back = validate_success(api.get_billing_period(period["id"], ADMIN_HEADERS))
    assertions.assert_fields(
        read_back,
        status="LOCKED",
        version=3,
        period_code="2025-06",
        start_date="2025-06-01",
        end_date="2025-06-30",
        season="SUMMER",
    )


def test_bill_issue_applies_every_declared_side_effect(api):
    """PRD §3.2: "Issuing stamps `due_date` as the period's `end_date` plus twenty-one calendar days, inserts a `CHARGE` ledger entry with `source_kind` `BILL_CHARGE` for the positive `total_charge_cents`, naming this bill in both `bill_id` and `source_id`, and then recomputes the account's `balance_cents`, then its `credit_status`, then its `service_status`, in that order."

    PRD §2.9: "It is evaluated as a strict precedence chain in which the first matching clause wins: if any arrangement on the account is `DEFAULTED`, the status is `ARRANGEMENT_DEFAULTED`; otherwise if any arrangement on the account is `ACTIVE`, the status is `IN_ARRANGEMENT`; otherwise if `balance_cents` is strictly greater than 5,000 cents (fifty dollars), the status is `PAST_DUE`; otherwise it is `CURRENT`."
    PRD §3.8: "The account must be in `ACTIVE` service and its `credit_status` must be `PAST_DUE` or `ARRANGEMENT_DEFAULTED`."

    Design: Corner/state_machines/corner_state_side_effect_execution_bill_issue_applies_every_declared_side_effect
    """
    ctx = _june_draft_bill(api)

    issued = validate_success(api.issue_bill(ctx["bill_id"], SUPERVISOR_HEADERS))
    assertions.assert_fields(
        issued, billing_status="ISSUED", due_date="2025-07-21"
    )

    entries = assertions.bill_ledger_entries(api, ctx["bill_id"], SUPERVISOR_HEADERS)
    assert len(entries) == 1, f"expected exactly one bill ledger row, got {len(entries)}"
    entry = assertions.assert_single_entry(
        entries,
        "BILL_CHARGE",
        entry_type="CHARGE",
        amount_cents=FOUR_KGAL_TOTAL_CENTS,
        source_id=ctx["bill_id"],
        bill_id=ctx["bill_id"],
    )
    assert entry["effective_at"].startswith("2026-08-01T00:00:00"), (
        f"effective_at must be the logical clock, got {entry['effective_at']!r}"
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account,
        balance_cents=FOUR_KGAL_TOTAL_CENTS,
        credit_status="PAST_DUE",
        service_status="ACTIVE",
    )
    assertions.assert_null_fields(account, "shutoff_scheduled_for")


def test_arrangement_activation_reconciles_ledger_balance_and_both_dimensions(api):
    """PRD §3.8: "Activation inserts a `PAYMENT` entry with `source_kind` `ARRANGEMENT_DOWN_PAYMENT` for the negative `down_payment_cents` against the plan's `bill_id`, recomputes `balance_cents`, pins `credit_status` to `IN_ARRANGEMENT`, and moves `service_status` to `ACTIVE` from `SHUTOFF_SCHEDULED`, `SHUTOFF_HELD` or `SHUTOFF_EXECUTED` precisely because `credit_status` became `IN_ARRANGEMENT`."

    PRD §2.9: "An account's `balance_cents` is therefore not stored independently of the log — it is the sum of `amount_cents` over every ledger entry on that account, recomputed as a full replay after each insert."
    PRD §3.8: "And whenever `credit_status` becomes `CURRENT` or `IN_ARRANGEMENT`, the account returns to `ACTIVE` from `SHUTOFF_HELD`, from `SHUTOFF_SCHEDULED`, or from `SHUTOFF_EXECUTED` — in the last case service is restored — and `shutoff_scheduled_for` is set to null."

    Design: Corner/state_machines/corner_state_ledger_sync_arrangement_activation_reconciles_balance_and_both_account_dimensions
    """
    ctx = _june_issued_bill(api)
    before = validate_success(
        api.schedule_shutoff(ctx["account_id"], SUPERVISOR_HEADERS)
    )
    assertions.assert_account_state(
        before,
        balance_cents=FOUR_KGAL_TOTAL_CENTS,
        credit_status="PAST_DUE",
        service_status="SHUTOFF_SCHEDULED",
    )
    assert before["shutoff_scheduled_for"].startswith("2026-08-11")

    arrangement = fixtures.propose_arrangement(
        api,
        ctx["account_id"],
        ctx["bill_id"],
        FOUR_KGAL_TOTAL_CENTS,
        fixtures.account_version(api, ctx["account_id"]),
        installment_count=4,
    )
    assertions.assert_fields(
        arrangement, status="PROPOSED", down_payment_cents=1042
    )

    activated = validate_success(
        api.activate_payment_arrangement(arrangement["id"], CSR_HEADERS)
    )
    assertions.assert_fields(activated, status="ACTIVE")

    entries, meta = validate_paginated(
        api.list_account_ledger_entries(ctx["account_id"], CSR_HEADERS, {"limit": 100})
    )
    assertions.assert_pagination_meta(meta, total_count=2)
    assertions.assert_source_kinds(
        entries, ["BILL_CHARGE", "ARRANGEMENT_DOWN_PAYMENT"]
    )
    assertions.assert_single_entry(
        entries,
        "ARRANGEMENT_DOWN_PAYMENT",
        entry_type="PAYMENT",
        amount_cents=-1042,
        source_id=arrangement["id"],
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account,
        balance_cents=4168,
        credit_status="IN_ARRANGEMENT",
        service_status="ACTIVE",
    )
    assertions.assert_null_fields(account, "shutoff_scheduled_for")
    assertions.assert_balance_is_ledger_sum(account, entries)


def test_final_installment_completes_the_plan_and_releases_credit_status(api):
    """PRD §3.8: "When `paid_installment_count` reaches `installment_count` the plan moves from `ACTIVE` to the terminal `COMPLETED` and `credit_status` falls back to the balance comparison."

    PRD §3.8: "Recording inserts a `PAYMENT` entry with `source_kind` `ARRANGEMENT_INSTALLMENT` for the negative amount against the plan's `bill_id`, increases `paid_installment_count` by one, and — when `on_time` is false — increases `missed_payment_count` by one as well."
    PRD §2.9: "It is evaluated as a strict precedence chain in which the first matching clause wins: if any arrangement on the account is `DEFAULTED`, the status is `ARRANGEMENT_DEFAULTED`; otherwise if any arrangement on the account is `ACTIVE`, the status is `IN_ARRANGEMENT`; otherwise if `balance_cents` is strictly greater than 5,000 cents (fifty dollars), the status is `PAST_DUE`; otherwise it is `CURRENT`."

    Design: Corner/state_machines/corner_state_bubble_up_final_installment_completes_the_arrangement_and_releases_credit_status
    """
    ctx = _june_issued_bill(api)
    arrangement = fixtures.propose_arrangement(
        api,
        ctx["account_id"],
        ctx["bill_id"],
        FOUR_KGAL_TOTAL_CENTS,
        fixtures.account_version(api, ctx["account_id"]),
        installment_count=4,
    )
    activated = validate_success(
        api.activate_payment_arrangement(arrangement["id"], CSR_HEADERS)
    )
    assertions.assert_fields(activated, status="ACTIVE")

    for _ in range(3):
        validate_success(
            api.record_installment_payment(
                arrangement["id"],
                factories.installment_payment_payload(1042, True),
                CSR_HEADERS,
            )
        )

    after_three = fixtures.fetch_arrangement(api, arrangement["id"])
    assertions.assert_fields(after_three, status="ACTIVE", paid_installment_count=3)
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]),
        balance_cents=1042,
        credit_status="IN_ARRANGEMENT",
        service_status="ACTIVE",
    )

    final = validate_success(
        api.record_installment_payment(
            arrangement["id"],
            factories.installment_payment_payload(1042, True),
            CSR_HEADERS,
        )
    )
    assertions.assert_fields(
        final, status="COMPLETED", paid_installment_count=4, missed_payment_count=0
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(
        account, balance_cents=0, credit_status="CURRENT", service_status="ACTIVE"
    )
    entries, meta = validate_paginated(
        api.list_account_ledger_entries(ctx["account_id"], CSR_HEADERS, {"limit": 100})
    )
    assertions.assert_pagination_meta(meta, total_count=6)
    assertions.assert_source_kinds(
        entries,
        [
            "BILL_CHARGE",
            "ARRANGEMENT_DOWN_PAYMENT",
            "ARRANGEMENT_INSTALLMENT",
            "ARRANGEMENT_INSTALLMENT",
            "ARRANGEMENT_INSTALLMENT",
            "ARRANGEMENT_INSTALLMENT",
        ],
    )
    assertions.assert_balance_is_ledger_sum(account, entries)


def test_board_uphold_settles_appeal_investigation_and_bill_together(api):
    """PRD §3.9: "`UPHOLD` moves the appeal to the terminal `UPHELD`, moves the investigation from `APPEALED` to `RESOLVED` with `shutoff_hold_active` becoming false, settles the bill from `UNDER_INVESTIGATION` to `UPHELD_AS_BILLED`, and writes no ledger entry at all."

    PRD §3.9: "Every branch stamps `hearing_officer_user_id` with the acting `X-User-ID` and records the `decision` and `decision_note`; beyond that the three branches diverge completely, and each carries its own full set of effects."
    PRD §3.3: "`shutoff_hold_active` is not a stored decision but a function of the investigation's own `status`: it is true while the status is `OPEN`, `EVIDENCE_REQUESTED`, `EVIDENCE_UNDER_REVIEW`, `EVIDENCE_EXHAUSTED`, `DETERMINED`, `ADJUSTMENT_PENDING` or `APPEALED`, and false in `RESOLVED` and `CLOSED_NO_ADJUSTMENT`."
    PRD §2.9: "`open_investigation_hold_count` is the number of `HighBillInvestigation` rows on the account whose `shutoff_hold_active` is true, and `open_rebill_count` is the number of the account's bills sitting in `REBILL_PENDING`."

    Design: Corner/state_machines/corner_state_cross_entity_board_upheld_decision_settles_investigation_and_bill_without_money
    """
    ctx = fixtures.appeal_case(
        api,
        filer_headers=CSR_HEADERS,
        hearing_date="2026-08-15",
        advance_to_hearing=True,
    )
    assertions.assert_fields(
        ctx["investigation"], status="APPEALED", shutoff_hold_active=True
    )
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]),
        billing_status="UNDER_INVESTIGATION",
    )
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]),
        open_investigation_hold_count=1,
    )

    decided = validate_success(
        api.record_board_decision(
            ctx["appeal_id"], factories.board_decision_payload("UPHOLD"), CLERK_HEADERS
        )
    )
    assertions.assert_fields(
        decided,
        status="UPHELD",
        decision="UPHOLD",
        hearing_officer_user_id=CLERK_HEADERS["X-User-ID"],
    )

    assertions.assert_fields(
        fixtures.fetch_investigation(api, ctx["investigation_id"]),
        status="RESOLVED",
        shutoff_hold_active=False,
    )
    assertions.assert_account_state(
        fixtures.fetch_account(api, ctx["account_id"]),
        open_investigation_hold_count=0,
    )
    assertions.assert_fields(
        fixtures.fetch_bill(api, ctx["bill_id"]),
        billing_status="UPHELD_AS_BILLED",
        total_charge_cents=44939,
        adjusted_total_cents=44939,
    )


def test_board_uphold_moves_no_money_and_creates_no_leak_adjustment(api):
    """PRD §3.9: "`UPHOLD` moves the appeal to the terminal `UPHELD`, moves the investigation from `APPEALED` to `RESOLVED` with `shutoff_hold_active` becoming false, settles the bill from `UNDER_INVESTIGATION` to `UPHELD_AS_BILLED`, and writes no ledger entry at all."

    PRD §2.9: "An account's `balance_cents` is therefore not stored independently of the log — it is the sum of `amount_cents` over every ledger entry on that account, recomputed as a full replay after each insert."

    Design: Corner/state_machines/corner_state_cross_entity_board_upheld_decision_settles_investigation_and_bill_without_money
    """
    ctx = fixtures.appeal_case(
        api,
        filer_headers=CSR_HEADERS,
        hearing_date="2026-08-15",
        advance_to_hearing=True,
    )
    before = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(before, balance_cents=60569)

    validate_success(
        api.record_board_decision(
            ctx["appeal_id"], factories.board_decision_payload("UPHOLD"), CLERK_HEADERS
        )
    )

    entries, meta = validate_paginated(
        api.list_account_ledger_entries(ctx["account_id"], CSR_HEADERS, {"limit": 100})
    )
    assertions.assert_pagination_meta(meta, total_count=4)
    assertions.assert_source_kinds(
        entries, ["BILL_CHARGE", "BILL_CHARGE", "BILL_CHARGE", "BILL_CHARGE"]
    )
    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(account, balance_cents=60569)
    assertions.assert_balance_is_ledger_sum(account, entries)

    _rows, adj_meta = validate_paginated(
        api.list_leak_adjustments(
            CSR_HEADERS, {"investigation_id": ctx["investigation_id"]}
        )
    )
    assertions.assert_pagination_meta(adj_meta, total_count=0)


def test_suspect_field_result_escalates_to_bench_without_closure_effects(api):
    """PRD §3.4: "`SUSPECT` records the `field_result` and escalates the request to `BENCH_TEST_PENDING`, releasing the meter reservation so that a later request may claim an adjacent window; no meter field is written and no deposit decision is taken yet."

    PRD §3.1: "Every newly registered meter starts with `accuracy_status` set to `UNTESTED`, `accuracy_pct` null, `correction_factor` null and `last_test_completed_at` null."
    PRD §3.4: "A request opens in `REQUESTED` with `deposit_refunded` false; when `deposit_cents` is greater than zero a `CHARGE` entry with `source_kind` `METER_TEST_DEPOSIT` for the positive deposit is written to the ledger and the account's `balance_cents`, `credit_status` and `service_status` are recomputed in that order."

    Design: Corner/state_machines/corner_state_conditional_cascade_suspect_field_result_escalates_without_firing_closure_effects
    """
    ctx = fixtures.field_test_case(api, requested_by_kind="CUSTOMER", scheduled=True)

    escalated = validate_success(
        api.record_field_result(
            ctx["test_request_id"],
            factories.field_result_payload("SUSPECT", "2026-08-01T10:00:00Z"),
            TECHNICIAN_HEADERS,
        )
    )
    assertions.assert_fields(
        escalated,
        status="BENCH_TEST_PENDING",
        field_result="SUSPECT",
        deposit_refunded=False,
    )
    assertions.assert_null_fields(
        escalated, "accuracy_pct", "bench_result", "accuracy_method"
    )
    assert escalated["tested_at"].startswith("2026-08-01T10:00:00"), (
        f"tested_at must echo the recorded instant, got {escalated['tested_at']!r}"
    )

    meter = fixtures.fetch_meter(api, ctx["meter_id"])
    assertions.assert_fields(meter, accuracy_status="UNTESTED")
    assertions.assert_null_fields(
        meter, "accuracy_pct", "correction_factor", "last_test_completed_at"
    )

    entries = assertions.ledger_entries(api, ctx["account_id"], CSR_HEADERS)
    assertions.assert_no_entry_of_kind(entries, "METER_TEST_DEPOSIT_REFUND")
    assertions.assert_single_entry(
        entries, "METER_TEST_DEPOSIT", entry_type="CHARGE", amount_cents=3000
    )


def test_suspect_field_result_leaves_investigation_bill_and_reads_untouched(api):
    """PRD §3.3: "Evidence arrives in one of two forms, and either form advances the investigation from `EVIDENCE_REQUESTED` to `EVIDENCE_UNDER_REVIEW`: a repair proof is submitted, or a meter test request for this investigation reaches one of its closed states — `CLOSED_PASS`, `CLOSED_FAST` or `CLOSED_SLOW`."

    PRD §3.5: "A bill reaches `REBILL_PENDING` from `ISSUED`, `UNDER_INVESTIGATION` or `ADJUSTED` in exactly two situations: a `CORRECTED` read changes its `consumption_gallons`, or a meter test on its meter closes `CLOSED_FAST`."
    PRD §3.4: "A request opens in `REQUESTED` with `deposit_refunded` false; when `deposit_cents` is greater than zero a `CHARGE` entry with `source_kind` `METER_TEST_DEPOSIT` for the positive deposit is written to the ledger and the account's `balance_cents`, `credit_status` and `service_status` are recomputed in that order."

    Design: Corner/state_machines/corner_state_conditional_cascade_suspect_field_result_escalates_without_firing_closure_effects
    """
    ctx = fixtures.field_test_case(api, requested_by_kind="CUSTOMER", scheduled=True)

    validate_success(
        api.record_field_result(
            ctx["test_request_id"],
            factories.field_result_payload("SUSPECT", "2026-08-01T10:00:00Z"),
            TECHNICIAN_HEADERS,
        )
    )

    assertions.assert_fields(
        fixtures.fetch_investigation(api, ctx["investigation_id"]),
        status="EVIDENCE_REQUESTED",
    )
    bill = fixtures.fetch_bill(api, ctx["bill_id"])
    assertions.assert_fields(bill, billing_status="UNDER_INVESTIGATION")
    assertions.assert_bill_charges(
        bill, consumption_gallons=41000, total_charge_cents=44939
    )

    readings, reading_meta = validate_paginated(
        api.list_meter_readings(
            TECHNICIAN_HEADERS, {"meter_id": ctx["meter_id"], "limit": 100}
        )
    )
    assertions.assert_pagination_meta(reading_meta, total_count=5)
    assert not [r for r in readings if r["read_type"] == "CORRECTED"], (
        "an escalated field test must not restate any read"
    )

    account = fixtures.fetch_account(api, ctx["account_id"])
    assertions.assert_account_state(account, balance_cents=63569)
    entries, ledger_meta = validate_paginated(
        api.list_account_ledger_entries(ctx["account_id"], CSR_HEADERS, {"limit": 100})
    )
    assertions.assert_pagination_meta(ledger_meta, total_count=5)
    assertions.assert_balance_is_ledger_sum(account, entries)
