"""Payment waterfall, overpayment credit, reversals, and ledger conservation
claims (PRD §3.3, §2.5, §2.6, §2.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_payment,
    create_payment_payload,
    entries_of_type,
    find_charge_entry,
    list_active_holds,
    make_payment,
    read_account,
    read_ledger,
    set_clock,
    setup_account_with_enrollment,
    setup_plan_scenario,
    validate_error,
    validate_success,
)

_STAFF = TEST_USERS["bursar_staff_headers"]


def test_payment_waterfall_due_date_order(api, bursar_staff_headers):
    """PRD §3.3: "The waterfall considers the charge-family entries — `CHARGE`,
    `LATE_FEE`, `PLAN_FEE`, and `COLLECTIONS_FEE` — that still have a positive
    open amount, visiting them oldest obligation first: ascending `due_date`,
    with ascending `created_at` as the tie-break." and "The resulting per-entry
    splits are recorded on the payment as its `allocations` array, each element
    pairing a `ledger_entry_id` with an allocated `amount_cents` in allocation
    order."

    Design: Corner/calculations/payment_waterfall_due_date_order
    """
    ctx = setup_plan_scenario(credit_hours=1, installment_count=2,
                              first_due_date="2026-09-01", external_ref="S-WF")
    acc = ctx["account_id"]
    ledger = read_ledger(acc)
    tuition = find_charge_entry(ledger, "TUITION")   # due 2026-09-07
    plan_fee = entries_of_type(ledger, "PLAN_FEE")[0]  # due 2026-09-01

    res = api.create_payment(
        create_payment_payload(account_id=acc, amount_cents=5000, method="CASH"),
        bursar_staff_headers,
    )
    payment = validate_success(res, 201)
    assert_payment(payment)
    # PLAN_FEE (due 2026-09-01) is older than the TUITION charge (2026-09-07).
    assert payment["allocations"] == [
        {"ledger_entry_id": plan_fee["id"], "amount_cents": 2500},
        {"ledger_entry_id": tuition["id"], "amount_cents": 2500},
    ], f"waterfall order violated: {payment['allocations']}"
    assert payment["unapplied_cents"] == 0


def test_overpayment_creates_credit_balance(api, bursar_staff_headers):
    """PRD §3.3: "Overpayment is permitted: whatever the waterfall cannot
    allocate remains as the payment's `unapplied_cents` and shows up on the
    account as a credit (negative) balance, since the full `PAYMENT` amount
    counts against charges in the recompute."

    Design: Corner/calculations/overpayment_creates_credit_balance
    """
    ctx = setup_account_with_enrollment(credit_hours=1, external_ref="S-OVP")
    acc = ctx["account_id"]
    payment = validate_success(
        api.create_payment(
            create_payment_payload(account_id=acc, amount_cents=60000, method="CARD"),
            bursar_staff_headers,
        ),
        201,
    )
    assert payment["unapplied_cents"] == 10000
    account = read_account(acc)
    assert account["balance_cents"] == -10000
    assert account["status"] == "OPEN"


def test_payment_amount_zero_returns_422(api, bursar_staff_headers):
    """PRD §3.3: "A non-positive amount is rejected with `ERR_AMOUNT_INVALID`
    (HTTP 422)."

    Design: Corner/errors/payment_amount_zero_returns_422
    """
    ctx = setup_account_with_enrollment(credit_hours=1, external_ref="S-ZP")
    res = api.create_payment(
        create_payment_payload(account_id=ctx["account_id"], amount_cents=0),
        bursar_staff_headers,
    )
    validate_error(res, ApiErrorId.ERR_AMOUNT_INVALID, expected_status=422)
    assert read_account(ctx["account_id"])["payments_total_cents"] == 0


class TestPaymentPostReverseConservation:
    """Post+reverse must restore the ledger position exactly (PRD §3.3, §2.5)."""

    def test_payment_applies_then_reverse_restores_totals(self, api):
        """PRD §3.3: "Reversal posts a `PAYMENT_REVERSAL` entry of the same
        amount with `source_ref` pointing at the original payment, unwinds the
        waterfall so the open amounts on the originally allocated charge
        entries are restored, recomputes the account totals".
        PRD §2.5: "every account total is a deterministic recomputation over
        that ledger".

        Design: Difficulty/compensating_invariant/payment_post_reverse_ledger_conservation
        """
        ctx = setup_account_with_enrollment(credit_hours=9, external_ref="S-CON")
        acc = ctx["account_id"]
        before = read_account(acc)
        assert before["balance_cents"] == 330000
        assert before["payments_total_cents"] == 0

        payment = make_payment(acc, 100000)
        mid = read_account(acc)
        assert mid["balance_cents"] == 230000
        assert mid["payments_total_cents"] == 100000

        validate_success(
            api.reverse_payment(payment["id"], {"reason": "NSF"},
                                _STAFF),
            200,
        )
        end = read_account(acc)
        assert end["balance_cents"] == 330000, "post+reverse must restore balance"
        assert end["payments_total_cents"] == 0, (
            "post+reverse must restore payments_total"
        )

    def test_reversal_retains_both_ledger_entries(self, api, bursar_staff_headers):
        """PRD §2.5: "Entries are never updated or deleted; correction is
        always additive, by posting a reversing entry."

        Design: Difficulty/compensating_invariant/payment_post_reverse_ledger_conservation
        """
        ctx = setup_account_with_enrollment(credit_hours=9, external_ref="S-CN2")
        acc = ctx["account_id"]
        payment = make_payment(acc, 100000)
        validate_success(
            api.reverse_payment(payment["id"], {"reason": "NSF"},
                                bursar_staff_headers),
            200,
        )
        ledger = read_ledger(acc)
        payments = entries_of_type(ledger, "PAYMENT")
        reversals = entries_of_type(ledger, "PAYMENT_REVERSAL")
        assert len(payments) == 1 and payments[0]["amount_cents"] == 100000
        assert len(reversals) == 1 and reversals[0]["amount_cents"] == 100000
        assert reversals[0]["source_ref"] == payment["id"]


class TestPaymentReversalReagingCascade:
    """Reversal re-ages restored debt into past-due and places holds (PRD §3.3)."""

    def _setup_reversed(self):
        ctx = setup_account_with_enrollment(credit_hours=1, external_ref="S-REV")
        acc = ctx["account_id"]
        set_clock("2026-08-05T00:00:00Z")
        payment = make_payment(acc, 50000, method="CHECK")
        set_clock("2026-10-01T00:00:00Z")
        return ctx, payment

    def test_reversal_restores_balance_and_reages_past_due(
        self, api, bursar_staff_headers
    ):
        """PRD §3.3: reversal "recomputes the account totals, and re-ages the
        debt: restored open amounts whose due dates precede the clock date flow
        straight back into `past_due_cents`".
        PRD §2.6: "when a recomputation finds `past_due_cents` greater than
        zero on an `OPEN` account, the account moves to `PAST_DUE`".

        Design: Difficulty/transitive_cascade/payment_reversal_reaging_cascade
        """
        ctx, payment = self._setup_reversed()
        reversed_payment = validate_success(
            api.reverse_payment(payment["id"], {"reason": "NSF"},
                                bursar_staff_headers),
            200,
        )
        assert reversed_payment["status"] == "REVERSED"
        assert reversed_payment["reversed_reason"] == "NSF"
        account = read_account(ctx["account_id"])
        assert account["balance_cents"] == 50000
        assert account["payments_total_cents"] == 0
        # Charges were due 2026-09-07, strictly before clock 2026-10-01.
        assert account["past_due_cents"] == 50000
        assert account["status"] == "PAST_DUE"

    def test_reversal_places_auto_holds_above_threshold(
        self, api, bursar_staff_headers
    ):
        """PRD §3.3: "if that pushes the account to or beyond the term's
        `hold_threshold_cents`, fresh `ACTIVE` `AUTO` holds of both types are
        placed."
        PRD §2.6: holds are created "with `origin` set to `AUTO` and the system
        reason string `PAST_DUE_BALANCE`".

        Design: Difficulty/transitive_cascade/payment_reversal_reaging_cascade
        """
        ctx, payment = self._setup_reversed()
        validate_success(
            api.reverse_payment(payment["id"], {"reason": "NSF"},
                                bursar_staff_headers),
            200,
        )
        holds = list_active_holds(ctx["account_id"])
        assert len(holds) == 2, f"expected 2 AUTO holds, got {len(holds)}"
        assert {h["hold_type"] for h in holds} == {"REGISTRATION", "TRANSCRIPT"}
        for hold in holds:
            assert hold["origin"] == "AUTO"
            assert hold["reason"] == "PAST_DUE_BALANCE"
            assert hold["status"] == "ACTIVE"


def test_payment_reverse_twice_returns_state_error(api, bursar_staff_headers):
    """PRD §3.3: "Only a `POSTED` payment can be reversed; reversing anything
    else yields `ERR_PAYMENT_STATE_INVALID` (HTTP 409)."

    Design: Corner/errors/payment_reverse_twice_returns_state_error
    """
    ctx = setup_account_with_enrollment(credit_hours=1, external_ref="S-TRV")
    acc = ctx["account_id"]
    payment = make_payment(acc, 10000, method="ACH")
    validate_success(
        api.reverse_payment(payment["id"], {"reason": "NSF"}, bursar_staff_headers),
        200,
    )
    res = api.reverse_payment(
        payment["id"], {"reason": "NSF again"}, bursar_staff_headers
    )
    validate_error(res, ApiErrorId.ERR_PAYMENT_STATE_INVALID, expected_status=409)
    ledger = read_ledger(acc)
    assert len(entries_of_type(ledger, "PAYMENT_REVERSAL")) == 1


def test_immediate_read_after_write_consistency(api, bursar_staff_headers):
    """PRD §2.5: "every account total is a deterministic recomputation over
    that ledger" — "From this sign convention the account's derived totals are
    recomputed, on every posting".

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    ctx = setup_account_with_enrollment(credit_hours=9, external_ref="S-CNS")
    acc = ctx["account_id"]
    make_payment(acc, 100000, method="ACH")
    account = read_account(acc)
    assert account["balance_cents"] == 230000
    assert account["payments_total_cents"] == 100000


def test_account_version_increments_on_mutation(api, bursar_staff_headers):
    """PRD §2.9: "an integer `version` that increments by one with every
    modification to the resource. Recomputations of derived fields on an
    account — bucket totals, `past_due_cents`, status flips — count as
    mutations for this purpose."
    PRD §2.8: "Both plan creation and waiver posting increment the account's
    `version` by exactly one as part of their side effects."

    Design: Corner/cross_cutting/account_version_increments_on_mutation
    """
    ctx = setup_account_with_enrollment(credit_hours=9, external_ref="S-VRS")
    acc = ctx["account_id"]
    before = read_account(acc)
    make_payment(acc, 1000)
    after = read_account(acc)
    assert after["version"] == before["version"] + 1, (
        f"payment must advance the account version by exactly one: "
        f"{before['version']} -> {after['version']}"
    )
    assert after["created_at"] == before["created_at"]


# Imported lazily to keep the header import block tidy.
from test_helpers import TEST_USERS as _TU  # noqa: E402

_STAFF = _TU["bursar_staff_headers"]
