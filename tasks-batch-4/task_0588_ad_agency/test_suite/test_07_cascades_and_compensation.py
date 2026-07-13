"""Invoice issue, void and payment: the credit-hold cascade and its exact inverses."""

from test_helpers import (
    ApiErrorId,
    assemble_invoice,
    assert_invoice,
    assert_retainer,
    assert_retainer_cash_conserved,
    create_time_entry_payload,
    create_vendor_cost_payload,
    issue_invoice,
    open_deliverable,
    retainer_version,
    setup_approved_senior_hour,
    setup_base,
    setup_issued_final_invoice,
    setup_on_hold_campaign,
    validate_error,
    validate_paginated,
    validate_success,
)


def _draft_final_invoice(retainer_funding, **base_overrides):
    """Base scenario + one APPROVED 60-minute SENIOR entry + a DRAFT FINAL invoice of 20600."""
    base = setup_base(retainer_funding=retainer_funding, **base_overrides)
    base["time_entry"] = setup_approved_senior_hour(base)
    base["invoice"] = assemble_invoice(base, billing_mode="FINAL")
    base["invoice_id"] = base["invoice"]["id"]
    return base


class TestCreditHoldCascade:
    """Difficulty: transitive_cascade /
    invoice_issue_depletes_retainer_then_holds_client_then_holds_campaign."""

    def test_issuing_draws_the_retainer_down_to_zero_and_settles_the_invoice(self, api):
        """PRD §3.8: "It moves the invoice `DRAFT → ISSUED` and draws the retainer down:
        `retainer_applied_cents` is the smaller of the retainer's `balance_cents` and the
        invoice's `total_cents`, and `cash_due_cents` is `total_cents` less
        `retainer_applied_cents`."
        PRD §3.8: "And if `cash_due_cents` comes out at zero — because the retainer covered the
        total in full — the invoice's payment dimension jumps immediately to `PAID`, and if the
        owning campaign is sitting in `WRAP_UP` it advances `WRAP_UP → CLOSED` on the spot."

        Design: Difficulty/transitive_cascade/invoice_issue_depletes_retainer_then_holds_client_then_holds_campaign
        """
        base = _draft_final_invoice(20_600)
        version = retainer_version(base["retainer_id"])

        issued = validate_success(api.issue_invoice(
            base["invoice_id"], {"expected_retainer_version": version}, base["admin_headers"]))

        assert_invoice(issued)
        assert issued["approval_status"] == "ISSUED"
        assert issued["total_cents"] == 20_600
        assert issued["retainer_applied_cents"] == 20_600
        assert issued["cash_due_cents"] == 0
        assert issued["payment_status"] == "PAID"

    def test_the_zero_balance_freezes_the_retainer_the_advertiser_and_the_campaign(self, api):
        """PRD §3.1: "When a retainer moves `ACTIVE → DEPLETED`, the owning advertiser is put on
        credit hold — `ACTIVE → CREDIT_HOLD` — and, in turn, every campaign of that advertiser
        then `IN_FLIGHT` is frozen `IN_FLIGHT → ON_HOLD`."
        PRD §3.8: "If that leaves the balance at exactly zero, the retainer moves
        `ACTIVE → DEPLETED`, which puts the advertiser `ACTIVE → CREDIT_HOLD`, which in turn
        freezes every `IN_FLIGHT` campaign of that advertiser to `ON_HOLD` — four hops in a
        single request. If the invoice's `billing_mode` is `FINAL`, every included time entry
        moves `APPROVED → BILLED` and every included vendor cost does the same; a `PROVISIONAL`
        invoice leaves both untouched."

        Design: Difficulty/transitive_cascade/invoice_issue_depletes_retainer_then_holds_client_then_holds_campaign
        """
        base = _draft_final_invoice(20_600)
        issue_invoice(base, base["invoice_id"])

        retainer = validate_success(api.get_retainer(base["retainer_id"], base["admin_headers"]))
        assert_retainer(retainer)
        assert retainer["balance_cents"] == 0
        assert retainer["status"] == "DEPLETED"

        client = validate_success(api.get_client(base["client_id"], base["admin_headers"]))
        assert client["status"] == "CREDIT_HOLD"

        campaign = validate_success(api.get_campaign(base["campaign_id"], base["am_headers"]))
        assert campaign["status"] == "ON_HOLD"

        entry = validate_success(
            api.get_time_entry(base["time_entry"]["id"], base["admin_headers"])
        )
        assert entry["status"] == "BILLED"


class TestParallelStateDimensions:
    """Difficulty: non_linear_state_machine /
    invoice_approval_and_payment_dimensions_move_independently."""

    def test_a_partial_payment_moves_only_the_payment_dimension(self, api):
        """PRD §3.8: "The payment dimension then follows the money: `UNPAID` while
        `amount_paid_cents` is 0 and `cash_due_cents` is greater than 0; `PARTIALLY_PAID` once
        `amount_paid_cents` is greater than 0 but still short of `cash_due_cents`; and `PAID`
        once `amount_paid_cents` equals `cash_due_cents` exactly. A single payment that settles
        the whole balance goes `UNPAID → PAID` directly, while smaller payments walk
        `UNPAID → PARTIALLY_PAID → PAID`. The approval dimension stays `ISSUED` throughout — the
        two dimensions never interfere."

        Design: Difficulty/non_linear_state_machine/invoice_approval_and_payment_dimensions_move_independently
        """
        base = setup_issued_final_invoice(retainer_funding=10_000)
        assert base["invoice"]["total_cents"] == 20_600
        assert base["invoice"]["retainer_applied_cents"] == 10_000
        assert base["invoice"]["cash_due_cents"] == 10_600
        assert base["invoice"]["payment_status"] == "UNPAID"

        after = validate_success(api.pay_invoice(
            base["invoice_id"], {"amount_cents": 4_000}, base["reviewer_headers"]))

        assert after["payment_status"] == "PARTIALLY_PAID"
        assert after["approval_status"] == "ISSUED"
        assert after["amount_paid_cents"] == 4_000

    def test_settling_the_balance_reaches_paid_while_approval_stays_issued(self, api):
        """PRD §3.8: "The payment adds `amount_cents` to `amount_paid_cents`, and the cumulative
        total must never exceed `cash_due_cents` — an overpayment is rejected with
        `ERR_PAYMENT_EXCEEDS_BALANCE`."
        PRD §3.8: "A single payment that settles the whole balance goes `UNPAID → PAID`
        directly, while smaller payments walk `UNPAID → PARTIALLY_PAID → PAID`. The approval
        dimension stays `ISSUED` throughout — the two dimensions never interfere."
        PRD §3.1: "When a retainer moves `ACTIVE → DEPLETED`, the owning advertiser is put on
        credit hold — `ACTIVE → CREDIT_HOLD` — and, in turn, every campaign of that advertiser
        then `IN_FLIGHT` is frozen `IN_FLIGHT → ON_HOLD`."

        Design: Difficulty/non_linear_state_machine/invoice_approval_and_payment_dimensions_move_independently
        """
        base = setup_issued_final_invoice(retainer_funding=10_000)
        validate_success(api.pay_invoice(
            base["invoice_id"], {"amount_cents": 4_000}, base["reviewer_headers"]))

        settled = validate_success(api.pay_invoice(
            base["invoice_id"], {"amount_cents": 6_600}, base["reviewer_headers"]))

        assert settled["payment_status"] == "PAID"
        assert settled["approval_status"] == "ISSUED"
        assert settled["amount_paid_cents"] == 10_600

        campaign = validate_success(api.get_campaign(base["campaign_id"], base["am_headers"]))
        assert campaign["status"] == "ON_HOLD", (
            "the retainer was drained to zero at issue, so the campaign is frozen and stays so"
        )


class TestRetainerCashConservation:
    """Difficulty: compensating_invariant / retainer_cash_conserved_across_issue_and_void."""

    def test_issue_draws_the_applied_cash_out_of_the_balance(self, api):
        """PRD §3.8: "It moves the invoice `DRAFT → ISSUED` and draws the retainer down:
        `retainer_applied_cents` is the smaller of the retainer's `balance_cents` and the
        invoice's `total_cents`, and `cash_due_cents` is `total_cents` less
        `retainer_applied_cents`."
        PRD §2.9: "**Retainer cash.** A retainer's `funded_cents` always equals its
        `balance_cents` plus the sum of `retainer_applied_cents` across every invoice drawing on
        that retainer whose approval dimension is `ISSUED`."

        Design: Difficulty/compensating_invariant/retainer_cash_conserved_across_issue_and_void
        """
        base = _draft_final_invoice(200_000)

        issued = issue_invoice(base, base["invoice_id"])
        assert issued["retainer_applied_cents"] == 20_600

        retainer = validate_success(api.get_retainer(base["retainer_id"], base["admin_headers"]))
        assert retainer["balance_cents"] == 179_400
        assert retainer["funded_cents"] == 200_000
        assert retainer["status"] == "ACTIVE"
        assert_retainer_cash_conserved(retainer, [issued])

    def test_void_returns_the_cash_and_releases_the_billed_line(self, api):
        """PRD §3.8: "Voiding moves the invoice `ISSUED → VOID` (a terminal state), records the
        supplied `reason` into `void_reason`, and adds `retainer_applied_cents` back onto the
        retainer's `balance_cents`, incrementing the retainer's `version`."
        PRD §3.8: "Where the invoice was `FINAL`, every time entry and vendor cost it had billed
        reverts `BILLED → APPROVED`."
        PRD §2.9: "**Retainer cash.** A retainer's `funded_cents` always equals its
        `balance_cents` plus the sum of `retainer_applied_cents` across every invoice drawing on
        that retainer whose approval dimension is `ISSUED`. Void moves an invoice out of that
        filter and simultaneously returns its applied cash to the balance, so the identity holds
        with zero drift. Note that voiding does **not** zero the invoice's own
        `retainer_applied_cents` — the invoice keeps its historical record, and it is the
        approval-status filter that excludes it."

        Design: Difficulty/compensating_invariant/retainer_cash_conserved_across_issue_and_void
        """
        base = _draft_final_invoice(200_000)
        issue_invoice(base, base["invoice_id"])

        voided = validate_success(api.void_invoice(
            base["invoice_id"], {"reason": "Client disputed the scope"}, base["admin_headers"]))
        assert voided["approval_status"] == "VOID"
        assert voided["void_reason"] == "Client disputed the scope"

        retainer = validate_success(api.get_retainer(base["retainer_id"], base["admin_headers"]))
        assert retainer["balance_cents"] == 200_000
        assert retainer["funded_cents"] == 200_000
        assert_retainer_cash_conserved(retainer, [voided])

        entry = validate_success(
            api.get_time_entry(base["time_entry"]["id"], base["admin_headers"])
        )
        assert entry["status"] == "APPROVED", "the void releases the line to be billed again"


class TestOnHoldPrecedesLabourCap:
    """Difficulty: priority_pair_validation_conflict /
    campaign_on_hold_state_precedes_sow_labor_cap_fiscal."""

    @staticmethod
    def _setup():
        # labor_cap 20000 is exactly consumed by the single approved entry, and the retainer of
        # 20600 is exactly drained by the invoice, so the campaign lands in ON_HOLD.
        return setup_on_hold_campaign(labor_cap_cents=20_000, sow_title="Tight SOW")

    def test_the_campaign_hold_error_masks_the_labour_cap_breach(self, api):
        """PRD §2.8: "When a single request violates more than one rule, the response must report
        the violation that comes first in the following ordering. This ordering is normative; a
        lower-numbered check that fails masks every higher-numbered one."
        PRD §2.8: "The cross-entity state gate on the owning campaign: the campaign must be
        `IN_FLIGHT`. A campaign in `ON_HOLD` rejects with `ERR_CAMPAIGN_ON_HOLD` (HTTP 409); a
        campaign in any other non-`IN_FLIGHT` state rejects with `ERR_INVALID_STATE`."
        PRD §2.8: "Capacity and budget ceilings, evaluated last of all: the daily minute cap and
        the labor cap on time-entry creation (`ERR_DAILY_MINUTES_EXCEEDED`,
        `ERR_SOW_LABOR_CAP_EXCEEDED`), the media budget ceiling on insertion-order creation
        (`ERR_MEDIA_BUDGET_EXCEEDED`), and the overpayment check on invoice payment
        (`ERR_PAYMENT_EXCEEDS_BALANCE`), all HTTP 422."

        Design: Difficulty/priority_pair_validation_conflict/campaign_on_hold_state_precedes_sow_labor_cap_fiscal
        """
        base = self._setup()

        # This one request breaks both rules: the campaign is ON_HOLD, and the entry would push
        # consumed_labor_cents from 20000 to 180000 against a 20000 cap.
        resp = api.create_time_entry(
            create_time_entry_payload(base["campaign_id"], base["dana_id"],
                                      "2026-06-05T09:00:00Z", "2026-06-05T17:00:00Z"),
            base["dana_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_ON_HOLD.value)
        assert resp.status_code == 409
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_SOW_LABOR_CAP_EXCEEDED.value

    def test_the_masked_request_books_no_labour_against_the_sow(self, api):
        """PRD §3.5: "The owning SOW's `consumed_labor_cents` is then recomputed as the sum of
        `estimated_amount_cents` over every time entry whose campaign belongs to that SOW and
        whose status is `SUBMITTED`, `APPROVED` or `BILLED`"
        PRD §3.3: "It is frozen `IN_FLIGHT → ON_HOLD` purely as a consequence of its advertiser
        going on credit hold, and released `ON_HOLD → IN_FLIGHT` when the advertiser recovers;
        while frozen it rejects time entries, vendor costs, vendor-cost approvals, time-entry
        approvals, deliverable submissions, deliverable reviews and media-plan sign-off, all with
        `ERR_CAMPAIGN_ON_HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/campaign_on_hold_state_precedes_sow_labor_cap_fiscal
        """
        base = self._setup()

        resp = api.create_time_entry(
            create_time_entry_payload(base["campaign_id"], base["dana_id"],
                                      "2026-06-05T09:00:00Z", "2026-06-05T17:00:00Z"),
            base["dana_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_ON_HOLD.value)

        sow = validate_success(api.get_sow(base["sow_id"], base["admin_headers"]))
        assert sow["consumed_labor_cents"] == 20_000, "no TimeEntry row was created"

        campaign = validate_success(api.get_campaign(base["campaign_id"], base["am_headers"]))
        assert campaign["status"] == "ON_HOLD"


def test_funding_a_depleted_retainer_reverses_the_whole_hold_chain(api):
    """PRD §3.1: "It returns to `ACTIVE` the instant the balance becomes greater than zero again,
    which can happen either through a top-up or through the void of an invoice that had drawn it
    down."
    PRD §3.1: "The reverse chain runs on recovery: when a retainer moves `DEPLETED → ACTIVE`, the
    advertiser returns `CREDIT_HOLD → ACTIVE` provided that *every* retainer of that advertiser is
    now `ACTIVE`, and every campaign of that advertiser sitting in `ON_HOLD` is released back to
    `IN_FLIGHT`."
    PRD §3.1: "Topping the retainer up adds the supplied `amount_cents` to both figures."

    Design: Corner/state_machines/retainer_funding_reverses_the_credit_hold_cascade
    """
    base = setup_on_hold_campaign()

    funded = validate_success(api.fund_retainer(
        base["retainer_id"], {"amount_cents": 50_000}, base["admin_headers"]))

    assert funded["balance_cents"] == 50_000
    assert funded["funded_cents"] == 70_600
    assert funded["status"] == "ACTIVE"

    client = validate_success(api.get_client(base["client_id"], base["admin_headers"]))
    assert client["status"] == "ACTIVE"

    campaign = validate_success(api.get_campaign(base["campaign_id"], base["am_headers"]))
    assert campaign["status"] == "IN_FLIGHT"

    invoice = validate_success(api.get_invoice(base["invoice_id"], base["admin_headers"]))
    assert invoice["approval_status"] == "ISSUED"
    assert_retainer_cash_conserved(funded, [invoice])


def test_paying_a_wrap_up_campaigns_invoice_in_full_closes_the_campaign(api):
    """PRD §3.8: "Whenever the invoice reaches `PAID`, a campaign sitting in `WRAP_UP` is closed:
    `WRAP_UP → CLOSED`."
    PRD §3.4: "First, if the campaign has at least one deliverable and every one of them is now
    `APPROVED`, the campaign advances `IN_FLIGHT → WRAP_UP`."
    PRD §3.8: "A single payment that settles the whole balance goes `UNPAID → PAID` directly,
    while smaller payments walk `UNPAID → PARTIALLY_PAID → PAID`."

    Design: Corner/state_machines/campaign_closes_when_wrap_up_invoice_is_fully_paid
    """
    base = setup_issued_final_invoice(retainer_funding=10_000)
    # The issue drained the retainer, so top it back up to release the campaign, then let
    # creative sign off and drive the campaign into WRAP_UP.
    validate_success(api.fund_retainer(
        base["retainer_id"], {"amount_cents": 1}, base["admin_headers"]))
    deliverable = open_deliverable(base, submit=True)
    validate_success(api.approve_deliverable(deliverable["id"], base["reviewer_headers"]))
    assert validate_success(
        api.get_campaign(base["campaign_id"], base["am_headers"]))["status"] == "WRAP_UP"

    paid = validate_success(api.pay_invoice(
        base["invoice_id"], {"amount_cents": 10_600}, base["reviewer_headers"]))

    assert paid["payment_status"] == "PAID"
    assert paid["approval_status"] == "ISSUED"
    assert paid["amount_paid_cents"] == 10_600

    campaign = validate_success(api.get_campaign(base["campaign_id"], base["am_headers"]))
    assert campaign["status"] == "CLOSED"


def test_voiding_an_invoice_that_has_received_cash_is_rejected(api):
    """PRD §3.8: "It is legal only from `approval_status` `ISSUED` and only while
    `amount_paid_cents` is still 0 — an invoice against which any cash has been received cannot
    be voided, and the attempt is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/void_invoice_that_has_a_payment_returns_invalid_state
    """
    base = setup_issued_final_invoice(retainer_funding=10_000)
    validate_success(api.pay_invoice(
        base["invoice_id"], {"amount_cents": 4_000}, base["reviewer_headers"]))

    resp = api.void_invoice(base["invoice_id"], {"reason": "Too late"}, base["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert resp.status_code == 409

    invoice = validate_success(api.get_invoice(base["invoice_id"], base["admin_headers"]))
    assert invoice["approval_status"] == "ISSUED"
    assert invoice["payment_status"] == "PARTIALLY_PAID"

    retainer = validate_success(api.get_retainer(base["retainer_id"], base["admin_headers"]))
    assert retainer["balance_cents"] == 0, "no cash was returned by the rejected void"


def test_paying_more_than_the_cash_due_is_rejected(api):
    """PRD §3.8: "The payment adds `amount_cents` to `amount_paid_cents`, and the cumulative
    total must never exceed `cash_due_cents` — an overpayment is rejected with
    `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Corner/validations/payment_over_cash_due_returns_payment_exceeds_balance
    """
    base = setup_issued_final_invoice(retainer_funding=10_000)
    assert base["invoice"]["cash_due_cents"] == 10_600

    resp = api.pay_invoice(base["invoice_id"], {"amount_cents": 11_000}, base["reviewer_headers"])
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)
    assert resp.status_code == 422

    invoice = validate_success(api.get_invoice(base["invoice_id"], base["admin_headers"]))
    assert invoice["amount_paid_cents"] == 0
    assert invoice["payment_status"] == "UNPAID"
    assert invoice["cash_due_cents"] == 10_600


def test_paying_an_invoice_that_was_never_issued_is_rejected(api):
    """PRD §3.8: "The invoice must be `ISSUED`; paying an invoice whose approval dimension is
    anything else is rejected with `ERR_INVALID_STATE`."
    PRD §3.8: "A new invoice sits in two independent state dimensions at once: `approval_status`
    is `DRAFT` and `payment_status` is `UNPAID`."

    Design: Corner/validations/payment_on_draft_invoice_returns_invalid_state
    """
    base = _draft_final_invoice(5_000_000)
    assert base["invoice"]["approval_status"] == "DRAFT"

    resp = api.pay_invoice(base["invoice_id"], {"amount_cents": 100}, base["reviewer_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert resp.status_code == 409

    invoice = validate_success(api.get_invoice(base["invoice_id"], base["admin_headers"]))
    assert invoice["approval_status"] == "DRAFT"
    assert invoice["amount_paid_cents"] == 0


def test_recording_a_vendor_cost_on_a_frozen_campaign_is_rejected(api):
    """PRD §3.6: "The cost is stored as `SUBMITTED` with `actual_amount_cents` null. As with
    time, the owning campaign must be `IN_FLIGHT`, or the request meets `ERR_CAMPAIGN_ON_HOLD`."
    PRD §3.3: "It is frozen `IN_FLIGHT → ON_HOLD` purely as a consequence of its advertiser going
    on credit hold, and released `ON_HOLD → IN_FLIGHT` when the advertiser recovers; while frozen
    it rejects time entries, vendor costs, vendor-cost approvals, time-entry approvals,
    deliverable submissions, deliverable reviews and media-plan sign-off, all with
    `ERR_CAMPAIGN_ON_HOLD`."

    Design: Corner/validations/vendor_cost_create_on_on_hold_campaign_returns_campaign_on_hold
    """
    base = setup_on_hold_campaign()

    resp = api.create_vendor_cost(
        create_vendor_cost_payload(base["campaign_id"], vendor_name="Freelance Editor",
                                   vendor_type="FREELANCER", estimated_amount_cents=100_000,
                                   incurred_on="2026-06-03"),
        base["am_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_ON_HOLD.value)
    assert resp.status_code == 409

    campaign = validate_success(api.get_campaign(base["campaign_id"], base["am_headers"]))
    assert campaign["status"] == "ON_HOLD"

    costs, meta = validate_paginated(
        api.list_campaign_vendor_costs(base["campaign_id"], base["am_headers"])
    )
    assert costs == []
    assert meta["total_count"] == 0


def test_the_whole_cascade_is_visible_in_the_issue_response_itself(api):
    """PRD §2.9: "Cascades are not optional side channels — they are part of the request that
    triggered them, they complete before the response is returned, and every resource they touch
    has its `version` incremented and its `updated_at` refreshed exactly as if it had been
    written directly."
    PRD §3.8: "If that leaves the balance at exactly zero, the retainer moves
    `ACTIVE → DEPLETED`, which puts the advertiser `ACTIVE → CREDIT_HOLD`, which in turn freezes
    every `IN_FLIGHT` campaign of that advertiser to `ON_HOLD` — four hops in a single request."

    Design: Corner/consistency_model/all_cascade_effects_are_visible_in_the_same_response
    """
    base = _draft_final_invoice(20_600)
    version = retainer_version(base["retainer_id"])

    issued = validate_success(api.issue_invoice(
        base["invoice_id"], {"expected_retainer_version": version}, base["admin_headers"]))

    # No second read is needed: the issue response already carries the drawdown and the payment.
    assert issued["retainer_applied_cents"] == 20_600
    assert issued["payment_status"] == "PAID"

    assert validate_success(
        api.get_client(base["client_id"], base["admin_headers"]))["status"] == "CREDIT_HOLD"
    assert validate_success(
        api.get_retainer(base["retainer_id"], base["admin_headers"]))["status"] == "DEPLETED"
    assert validate_success(
        api.get_campaign(base["campaign_id"], base["am_headers"]))["status"] == "ON_HOLD"
