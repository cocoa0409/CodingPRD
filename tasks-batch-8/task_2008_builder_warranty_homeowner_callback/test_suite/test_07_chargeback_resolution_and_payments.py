"""Chargeback resolution forks (UPHELD / REDUCED / WAIVED), payment collection,
the recovery cascade into the reserve, and terminal-state precedence."""
from test_helpers import (
    ApiErrorId,
    approve_chargeback,
    assert_ledger_conservation,
    contest_chargeback,
    create_approved_request,
    create_trade_partner,
    dispatch_work_order,
    get_reserve_for_home,
    issue_chargeback,
    list_reserve_entries,
    record_payment,
    resolve_chargeback,
    setup_contested_chargeback,
    setup_home,
    setup_issued_chargeback,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["rep_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestContestBranchingDivergentEffects:
    def _setup_two_contested(self, api):
        """cb1 (estimate 150000 -> provisional 137500) and cb2 (estimate 110000 ->
        provisional 93500), both contested by the charged partner in-window."""
        homeowner, home = setup_home(closing_date="2026-06-01")
        partner = create_trade_partner()
        sr1 = create_approved_request(
            home["id"], homeowner["id"], description="Leak under master bath"
        )
        wo1 = dispatch_work_order(
            sr1["id"], partner["id"],
            window_start="2026-08-10T09:00:00Z", window_end="2026-08-10T11:00:00Z",
            estimated_cost_cents=150_000,
        )
        cb1 = issue_chargeback(wo1["id"])
        sr2 = create_approved_request(
            home["id"], homeowner["id"], description="Hose bib drips"
        )
        wo2 = dispatch_work_order(
            sr2["id"], partner["id"],
            window_start="2026-08-11T09:00:00Z", window_end="2026-08-11T11:00:00Z",
            estimated_cost_cents=110_000,
        )
        cb2 = issue_chargeback(wo2["id"])
        contest_chargeback(cb1["id"], partner["id"], "Failure predates our rough-in")
        contest_chargeback(cb2["id"], partner["id"], "Freeze damage, homeowner left heat off")
        return {"homeowner": homeowner, "home": home, "partner": partner,
                "cb1": cb1, "cb2": cb2}

    def test_upheld_branch_proceeds_to_payment_and_recovery(self, api):
        """PRD §3.6: "`UPHELD` keeps the full amount."
        PRD §3.6: "The payment that exactly settles the outstanding balance moves
        the chargeback to `PAID` and credits the home's reserve with a `RECOVERY`
        entry for the amount, `chargeback_ref` attached, recomputing
        `balance_cents` and `recovered_to_date_cents` and re-evaluating the trend
        alert."

        Design: Difficulty/non_linear_state_machine/chargeback_contest_branching_divergent_effects
        """
        ctx = self._setup_two_contested(api)
        resolve_chargeback(
            ctx["cb1"]["id"], "UPHELD",
            resolution_notes="Photos show solvent-weld failure",
        )
        paid = record_payment(ctx["cb1"]["id"], 137_500)
        assert paid["status"] == "PAID"
        assert paid["collected_cents"] == 137_500

        reserve = get_reserve_for_home(ctx["home"]["id"])
        assert reserve["recovered_to_date_cents"] == 137_500
        assert reserve["balance_cents"] == 137_500
        recoveries = list_reserve_entries(reserve["id"], kind="RECOVERY")
        assert len(recoveries) == 1
        assert recoveries[0]["amount_cents"] == 137_500
        assert recoveries[0]["chargeback_ref"] == ctx["cb1"]["id"]

    def test_waived_branch_posts_no_reserve_entry(self, api):
        """PRD §3.6: "`WAIVED` zeroes the outstanding balance and recomputes the
        partner's aggregate — and posts nothing to the reserve, because a
        chargeback was never drawn against the reserve in the first place; waiver
        is pure compensation to the partner and leaves no ledger footprint."

        Design: Difficulty/non_linear_state_machine/chargeback_contest_branching_divergent_effects
        """
        ctx = self._setup_two_contested(api)
        resolve_chargeback(
            ctx["cb1"]["id"], "UPHELD",
            resolution_notes="Photos show solvent-weld failure",
        )
        record_payment(ctx["cb1"]["id"], 137_500)
        waived = resolve_chargeback(
            ctx["cb2"]["id"], "WAIVED",
            resolution_notes="Goodwill - first-year partner",
        )
        assert waived["status"] == "WAIVED"
        assert waived["outstanding_cents"] == 0

        reserve = get_reserve_for_home(ctx["home"]["id"])
        recoveries = list_reserve_entries(reserve["id"], kind="RECOVERY")
        assert len(recoveries) == 1, (
            "the waived branch leaves no ledger footprint: only the upheld "
            "branch's RECOVERY entry exists"
        )
        assert recoveries[0]["chargeback_ref"] == ctx["cb1"]["id"]
        assert reserve["balance_cents"] == 137_500


class TestTerminalChargebackOverpaymentConflict:
    def _setup_waived(self, api):
        ctx = setup_contested_chargeback(
            estimated_cost_cents=110_000, contest_reason="Not our fittings"
        )
        resolve_chargeback(
            ctx["chargeback"]["id"], "WAIVED",
            resolution_notes="Insufficient documentation",
        )
        return ctx

    def test_terminal_state_error_wins_over_overpayment(self, api):
        """PRD §2.7: "When a request violates several rules at once, exactly one
        error is returned: the first failure in the fixed precedence below."
        PRD §2.7: "If the target sits in a terminal state for its lifecycle — a
        `CLOSED` service request; an `ACCEPTED` or `CANCELLED` work order; a
        `PAID`, `WAIVED`, or `VOID` chargeback; a `PAID` or `DENIED` claim — the
        rejection is `ERR_ALREADY_TERMINAL`."
        PRD §3.6: "A payment against an `APPROVED`, `UPHELD`, or `REDUCED`
        chargeback records `amount_cents` — optionally with a `payment_reference`
        — and the amount must be positive and no more than the outstanding
        balance; any violation is `ERR_OVERPAYMENT`."

        Design: Difficulty/priority_pair_validation_conflict/terminal_chargeback_overpayment_conflict
        """
        ctx = self._setup_waived(api)
        # 999999 on a WAIVED (terminal) chargeback violates both the terminal-state
        # rule and the payment-bounds rule; the state rejection must win.
        resp = api.record_payment(
            ctx["chargeback"]["id"], {"amount_cents": 999_999}, FINANCE
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

    def test_rejected_payment_mutates_nothing(self, api):
        """PRD §3.6: "`WAIVED` zeroes the outstanding balance and recomputes the
        partner's aggregate — and posts nothing to the reserve, because a
        chargeback was never drawn against the reserve in the first place; waiver
        is pure compensation to the partner and leaves no ledger footprint."
        PRD §2.7: "When a request violates several rules at once, exactly one
        error is returned: the first failure in the fixed precedence below."

        Design: Difficulty/priority_pair_validation_conflict/terminal_chargeback_overpayment_conflict
        """
        ctx = self._setup_waived(api)
        resp = api.record_payment(
            ctx["chargeback"]["id"], {"amount_cents": 999_999}, FINANCE
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

        cb = validate_success(api.get_chargeback(ctx["chargeback"]["id"], REP), 200)
        assert cb["status"] == "WAIVED"
        assert cb["collected_cents"] == 0, "rejected payment collected nothing"
        assert cb["outstanding_cents"] == 0


class TestChargebackPaymentRecoveryCascade:
    def _setup_approved(self, api):
        """Issued (provisional 137500 from a 150000 estimate), then manager-approved.
        No sweep runs, so the reserve holds no accruals."""
        ctx = setup_issued_chargeback(
            estimated_cost_cents=150_000, request_description="Vanity drain leak"
        )
        ctx["chargeback"] = approve_chargeback(ctx["chargeback"]["id"])
        return ctx

    def test_payment_settles_chargeback_and_clears_partner(self, api):
        """PRD §3.6: "The payment that exactly settles the outstanding balance
        moves the chargeback to `PAID`".
        PRD §3.6: "The partner's `outstanding_chargeback_cents` aggregates
        outstanding across its chargebacks in `ISSUED`, `APPROVED`, `CONTESTED`,
        `UPHELD`, or `REDUCED`, and is recomputed on every change."

        Design: Difficulty/transitive_cascade/chargeback_payment_recovery_cascade
        """
        ctx = self._setup_approved(api)
        paid = record_payment(ctx["chargeback"]["id"], 137_500)
        assert paid["status"] == "PAID"
        assert paid["collected_cents"] == 137_500
        assert paid["outstanding_cents"] == 0

        partner = validate_success(
            api.get_trade_partner(ctx["partner"]["id"], MANAGER), 200
        )
        assert partner["outstanding_chargeback_cents"] == 0, (
            "no remaining open chargebacks"
        )

    def test_payment_posts_reserve_recovery(self, api):
        """PRD §3.6: "The payment that exactly settles the outstanding balance
        moves the chargeback to `PAID` and credits the home's reserve with a
        `RECOVERY` entry for the amount, `chargeback_ref` attached, recomputing
        `balance_cents` and `recovered_to_date_cents` and re-evaluating the trend
        alert."
        PRD §3.7: "Anything at or above the threshold is `NORMAL`."

        Design: Difficulty/transitive_cascade/chargeback_payment_recovery_cascade
        """
        ctx = self._setup_approved(api)
        record_payment(ctx["chargeback"]["id"], 137_500)

        reserve = get_reserve_for_home(ctx["home"]["id"])
        assert reserve["recovered_to_date_cents"] == 137_500
        assert reserve["balance_cents"] == 137_500
        assert reserve["alert_status"] == "NORMAL", (
            "137500 >= round_half_up(200000 x 0.20) = 40000"
        )
        entries = list_reserve_entries(reserve["id"])
        assert_ledger_conservation(reserve, entries)


def test_chargeback_reduced_amount_rules(api):
    """PRD §3.6: "`REDUCED` requires a `reduced_amount_cents` that is positive and
    strictly below the current payable amount; it overwrites `final_amount_cents`
    with the reduced figure, moves the basis to `FINAL`, and recomputes the
    outstanding balance and the partner's aggregate."
    PRD §2.7: "Request shape: required fields present, enum values in domain,
    numeric constraints honored — a strictly positive sale price, non-negative
    cost figures, a strictly positive claimed amount, a satisfaction score between
    one and five — and a visit window that ends strictly after it begins, else
    `ERR_INVALID_REQUEST`."

    Design: Corner/calculations/chargeback_reduced_amount_rules
    """
    ctx = setup_contested_chargeback(
        estimated_cost_cents=110_000, contest_reason="Partially our scope"
    )
    # Reducing to the full payable (93500) is not "strictly below" -> shape error.
    resp = api.resolve_chargeback(
        ctx["chargeback"]["id"],
        {"outcome": "REDUCED", "reduced_amount_cents": 93_500,
         "resolution_notes": "Trying full amount"},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    reduced = resolve_chargeback(
        ctx["chargeback"]["id"], "REDUCED",
        reduced_amount_cents=50_000, resolution_notes="Shared fault",
    )
    assert reduced["status"] == "REDUCED"
    assert reduced["final_amount_cents"] == 50_000
    assert reduced["amount_basis"] == "FINAL"
    assert reduced["outstanding_cents"] == 50_000

    paid = record_payment(ctx["chargeback"]["id"], 50_000)
    assert paid["status"] == "PAID"

    reserve = get_reserve_for_home(ctx["home"]["id"])
    assert reserve["recovered_to_date_cents"] == 50_000, (
        "recovery equals the reduced amount, not the original 93500"
    )


def test_overpayment_rejected_exact_amount_ok(api):
    """PRD §3.6: "A payment against an `APPROVED`, `UPHELD`, or `REDUCED`
    chargeback records `amount_cents` — optionally with a `payment_reference` —
    and the amount must be positive and no more than the outstanding balance; any
    violation is `ERR_OVERPAYMENT`."
    PRD §3.6: "The payment that exactly settles the outstanding balance moves the
    chargeback to `PAID` and credits the home's reserve with a `RECOVERY` entry
    for the amount, `chargeback_ref` attached, recomputing `balance_cents` and
    `recovered_to_date_cents` and re-evaluating the trend alert."

    Design: Corner/validations/overpayment_rejected_exact_amount_ok
    """
    ctx = setup_issued_chargeback(estimated_cost_cents=150_000)
    approve_chargeback(ctx["chargeback"]["id"])

    resp = api.record_payment(ctx["chargeback"]["id"], {"amount_cents": 137_501}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)

    paid = record_payment(ctx["chargeback"]["id"], 137_500)
    assert paid["status"] == "PAID"
    assert paid["collected_cents"] == 137_500


def test_immediate_consistency_after_payment(api):
    """PRD §3.6: "The payment that exactly settles the outstanding balance moves
    the chargeback to `PAID` and credits the home's reserve with a `RECOVERY`
    entry for the amount, `chargeback_ref` attached, recomputing `balance_cents`
    and `recovered_to_date_cents` and re-evaluating the trend alert."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/immediate_consistency_after_payment
    """
    ctx = setup_issued_chargeback(estimated_cost_cents=110_000)
    approve_chargeback(ctx["chargeback"]["id"])

    resp = api.record_payment(ctx["chargeback"]["id"], {"amount_cents": 93_500}, FINANCE)
    paid = validate_success(resp, 200)
    assert paid["status"] == "PAID", "payment response itself shows PAID"
    assert paid["collected_cents"] == 93_500

    reserve = get_reserve_for_home(ctx["home"]["id"])
    assert reserve["balance_cents"] == 93_500, (
        "RECOVERY visible on the very next read — no consistency lag"
    )
    partner = validate_success(api.get_trade_partner(ctx["partner"]["id"], MANAGER), 200)
    assert partner["outstanding_chargeback_cents"] == 0
