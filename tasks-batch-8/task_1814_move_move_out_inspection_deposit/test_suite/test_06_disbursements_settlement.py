"""Disbursement ledger: cash/reverse compensation, settlement bubble-up and
unwind, terminal lockdown, balance enforcement, and the key-count invariant
across issue/reopen."""
import test_helpers as th
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_tenancy_ledger_invariant,
    create_disbursement_payload,
    create_dispute_payload,
    create_statement_for,
    get_disbursement,
    get_dispute,
    get_statement,
    get_success_data,
    get_tenancy,
    make_manager_admin_headers,
    make_property_manager_headers,
    make_tenant_headers,
    setup_issued_statement_with_damage,
    setup_refund_sent,
    setup_settled_tenancy,
    setup_vacated_tenancy,
    setup_vacated_with_statement,
    validate_error,
    validate_success,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()


def _list_deductions(tenancy_id):
    resp = api_client.list_deductions(PM, params={"tenancy_id": tenancy_id, "limit": 100})
    data = get_success_data(resp)
    return data if isinstance(data, list) else data.get("data", [])


class TestCashThenReverse:
    def test_cash_sets_paid_and_settles(self):
        """PRD §3.7: "Cashing a refund can close the loop: when
        `refund_paid_cents` reaches at least the statement's
        `refund_due_cents` and no dispute of that statement is in `OPEN`,
        `MANAGER_COUNTERED`, or `ESCALATED_SMALL_CLAIMS`, the statement moves
        from `ISSUED` to `SETTLED` and the tenancy bubbles up from `VACATED`
        to `SETTLED`."

        Cashing the full 149,337c refund: refund_paid 149,337, reserved 0,
        statement SETTLED, tenancy SETTLED.

        Design: Difficulty/compensating_invariant/cash_then_reverse_restores_refund_paid
        """
        ctx = setup_refund_sent()
        disb = ctx["disbursement"]
        validate_success(api_client.mark_cashed(disb["id"], PM))
        ten = get_tenancy(ctx["tenancy"]["id"])
        assert ten["refund_paid_cents"] == 149_337
        assert ten["reserved_cents"] == 0
        assert get_statement(ctx["statement"]["id"])["status"] == "SETTLED"
        assert ten["status"] == "SETTLED"
        assert_tenancy_ledger_invariant(ten)

    def test_reverse_restores_pre_cash_quantities(self):
        """PRD §3.7: "A returned or stop-payment check is reversed by a
        `PropertyManager`, moving a `CASHED` disbursement to `REVERSED` and
        compensating the paid counters — a reversed refund subtracts from
        `refund_paid_cents`, a reversed penalty from `penalty_paid_cents`.
        When the tenancy had already settled and the reversal drags
        `refund_paid_cents` back below the statement's `refund_due_cents`,
        settlement unwinds: the statement reverts from `SETTLED` to `ISSUED`
        and the tenancy from `SETTLED` back to `VACATED`."

        After cash+reverse, refund_paid and balance return to their
        pre-disbursement values (0 and 149,337), statement back to ISSUED,
        tenancy back to VACATED, and the ledger identity holds.

        Design: Difficulty/compensating_invariant/cash_then_reverse_restores_refund_paid
        """
        ctx = setup_refund_sent()
        disb = ctx["disbursement"]
        ten_id = ctx["tenancy"]["id"]
        pre = get_tenancy(ten_id)
        assert pre["balance_remaining_cents"] == 0  # reserved 149,337
        validate_success(api_client.mark_cashed(disb["id"], PM))
        validate_success(api_client.reverse_disbursement(disb["id"], PM))
        ten = get_tenancy(ten_id)
        assert ten["refund_paid_cents"] == 0
        # Pre-disbursement balance (before any reservation) was 149,337.
        assert ten["balance_remaining_cents"] == 149_337, (
            f"cash+reverse must restore the pre-disbursement balance, "
            f"got {ten['balance_remaining_cents']}"
        )
        assert get_disbursement(disb["id"])["status"] == "REVERSED"
        assert get_statement(ctx["statement"]["id"])["status"] == "ISSUED"
        assert ten["status"] == "VACATED"
        assert_tenancy_ledger_invariant(ten)


class TestDisbursementTerminalLockdown:
    def test_reversed_disbursement_cannot_be_cashed(self):
        """PRD §3.7: "A returned or stop-payment check is reversed by a
        `PropertyManager`, moving a `CASHED` disbursement to `REVERSED`" —
        and the state-guard family of PRD §2.9: "fifth, state preconditions on
        the target resources (the state-guard errors such as
        `ERR_INVALID_STATE_TRANSITION` and `ERR_TENANCY_NOT_VACATED`)".

        REVERSED is terminal: mark_cashed on the reversed check fails and the
        disbursement stays REVERSED.

        Design: Corner/state_machines/disbursement_terminal_reversed_lockdown
        """
        ctx = setup_refund_sent()
        disb = ctx["disbursement"]
        validate_success(api_client.mark_cashed(disb["id"], PM))
        validate_success(api_client.reverse_disbursement(disb["id"], PM))
        resp = api_client.mark_cashed(disb["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_disbursement(disb["id"])["status"] == "REVERSED"


class TestRefundExceedsBalance:
    def test_refund_one_cent_over_rejected_penalty_exempt(self):
        """PRD §3.7: "A `REFUND` may not exceed the tenancy's
        `balance_remaining_cents` (`ERR_AMOUNT_EXCEEDS_BALANCE`); a `PENALTY`
        is exempt from that balance check because it is paid outside the
        deposit ledger."

        REFUND 149,338c against balance 149,337c fails (one cent over); a
        PENALTY of the same amount succeeds (201).

        Design: Corner/validations/refund_exceeds_balance_rejected
        """
        ctx = setup_issued_statement_with_damage()
        ten_id = ctx["tenancy"]["id"]
        stmt_id = ctx["statement"]["id"]
        assert get_tenancy(ten_id)["balance_remaining_cents"] == 149_337
        resp = api_client.create_disbursement(
            create_disbursement_payload(tenancy_id=ten_id, statement_id=stmt_id,
                                        kind="REFUND", amount_cents=149_338),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_AMOUNT_EXCEEDS_BALANCE)
        resp2 = api_client.create_disbursement(
            create_disbursement_payload(tenancy_id=ten_id, statement_id=stmt_id,
                                        kind="PENALTY", amount_cents=149_338),
            PM,
        )
        pen = validate_success(resp2, expected_status=201)
        assert pen["kind"] == "PENALTY"
        assert pen["status"] == "SENT"


class TestIssueReopenKeyInvariant:
    def _setup_key_fob_lock_issued_then_disputed(self):
        """Tenant returned 1 of 2 keys and 0 of 1 fobs: move-out completion
        creates KEY (qty 1, 5,000c), FOB (qty 1, 7,500c), LOCK (12,000c) DRAFT
        lines; statement issued timely then disputed (10,000c)."""
        ctx = setup_vacated_tenancy(
            move_out_items=[], keys_returned=1, fobs_returned=0,
        )
        stmt = create_statement_for(ctx["tenancy"]["id"])
        api_client.set_clock({"to_iso8601": "2026-08-10T00:00:00Z"}, ADMIN)
        validate_success(api_client.issue_statement(stmt["id"], PM))
        resp = api_client.create_dispute(
            create_dispute_payload(statement_id=stmt["id"],
                                   disputed_amount_cents=10_000,
                                   reason="lock charge unfair"),
            make_tenant_headers(ctx["tenancy"]["id"]),
        )
        ctx["dispute"] = get_success_data(resp)
        ctx["statement"] = get_statement(stmt["id"])
        ctx["tenancy"] = get_tenancy(ctx["tenancy"]["id"])
        return ctx

    def test_while_issued_key_identity_holds(self):
        """PRD §3.4: "When at least one key is missing, a line with source
        `KEY_NOT_RETURNED` is created whose `quantity` is the missing-key
        count and whose `amount_cents` is that count multiplied by the
        property's `key_charge_cents`." PRD §3.3: "Key and fob returns are
        tracked as absolute running counts, not deltas."

        While ISSUED: keys_issued 2 == keys_returned 1 + billed KEY quantity 1;
        neither count is mutated by issuance.

        Design: Difficulty/compensating_invariant/issue_then_reopen_conserves_key_counts
        """
        ctx = self._setup_key_fob_lock_issued_then_disputed()
        ten = ctx["tenancy"]
        assert ten["keys_issued"] == 2 and ten["keys_returned"] == 1
        key_lines = [d for d in _list_deductions(ten["id"])
                     if d["source"] == "KEY_NOT_RETURNED"]
        assert len(key_lines) == 1
        assert key_lines[0]["status"] == "BILLED"
        assert key_lines[0]["quantity"] == 1
        assert ten["keys_returned"] + key_lines[0]["quantity"] == ten["keys_issued"]

    def test_after_reopen_key_identity_holds_and_counters_reset(self):
        """PRD §3.5: "Its `BILLED` lines revert to `DRAFT` with `statement_id`
        cleared, `released_cents` resets to zero, `refund_due_cents` resets to
        zero, `issued_at`, `deadline_on`, and `late` are cleared, the active
        dispute moves to `WITHDRAWN`, and the tenancy's deduction counters and
        `version` are recomputed."

        After reopen: the KEY line is DRAFT (quantity 1), keys_issued /
        keys_returned never moved, pending 5,000 + 7,500 + 12,000 = 24,500,
        total 0, dispute WITHDRAWN.

        Design: Difficulty/compensating_invariant/issue_then_reopen_conserves_key_counts
        """
        ctx = self._setup_key_fob_lock_issued_then_disputed()
        stmt = ctx["statement"]
        ten_id = ctx["tenancy"]["id"]
        validate_success(api_client.reopen_statement(stmt["id"], PM))
        ten = get_tenancy(ten_id)
        assert ten["keys_issued"] == 2 and ten["keys_returned"] == 1
        key_lines = [d for d in _list_deductions(ten_id)
                     if d["source"] == "KEY_NOT_RETURNED"]
        assert len(key_lines) == 1 and key_lines[0]["status"] == "DRAFT"
        assert key_lines[0]["quantity"] == 1
        assert key_lines[0]["statement_id"] is None
        assert ten["pending_deductions_cents"] == 24_500, (
            f"5000 + 7500 + 12000 = 24500, got {ten['pending_deductions_cents']}"
        )
        assert ten["total_deductions_cents"] == 0
        assert get_dispute(ctx["dispute"]["id"])["status"] == "WITHDRAWN"
