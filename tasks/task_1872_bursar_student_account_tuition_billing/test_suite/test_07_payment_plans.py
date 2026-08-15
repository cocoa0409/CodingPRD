"""Payment plan origination, installment split, default/cure cycle, and
installment payment rule claims (PRD §3.7, §3.8, §2.8, §2.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    account_version,
    create_payment_plan_payload,
    entries_of_type,
    get_installments,
    get_success_data,
    make_payment,
    pay_installment_exact,
    read_ledger,
    run_billing_cycle_at,
    setup_account_with_enrollment,
    setup_collections_account,
    setup_plan_scenario,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

_STAFF = TEST_USERS["bursar_staff_headers"]


class TestInstallmentRoundingAndLateFeeOrder:
    """Pinned rounding: per-installment round first, remainder swept into the
    last installment; late fees rounded per installment (PRD §3.7, §3.8)."""

    def _setup(self):
        # 3cr assesses 120000; a 22499 payment leaves principal 97501.
        ctx = setup_plan_scenario(credit_hours=3, installment_count=3,
                                  first_due_date="2026-09-01",
                                  prepay_cents=22499, external_ref="S-RND")
        return ctx

    def test_split_rounds_each_share_then_sweeps_remainder(self, api):
        """PRD §3.7: "the per-installment share is computed first as the total
        divided by the installment count, rounded half up to whole cents;
        installments one through the penultimate each receive that rounded
        share; and the final installment receives whatever remains — the total
        minus the penultimate sum — so rounding residue is absorbed entirely by
        the last installment. Installment due dates step thirty calendar days
        apart: installment `k` falls due `first_due_date` plus thirty times
        (k − 1) days."

        Design: Difficulty/combinatorial_formula/installment_rounding_remainder_and_late_fee_order
        """
        ctx = self._setup()
        plan = ctx["plan"]
        # principal 97501 + fee 2500 = total 100001 over 3 installments.
        assert plan["principal_cents"] == 97501
        assert plan["fee_cents"] == 2500
        assert plan["total_cents"] == 100001
        installments = ctx["installments"]
        amounts = [i["amount_cents"] for i in installments]
        assert amounts == [33334, 33334, 33333], (
            f"round-first split of 100001/3 must be [33334, 33334, 33333], "
            f"got {amounts}"
        )
        assert sum(amounts) == 100001
        dues = [i["due_date"] for i in installments]
        assert dues == ["2026-09-01", "2026-10-01", "2026-10-31"]

    def test_late_fees_rounded_per_installment_never_merged(
        self, api, bursar_staff_headers
    ):
        """PRD §3.8: "Each flip posts exactly one `LATE_FEE` entry per
        installment — never one merged entry for the account — computed as the
        installment's `amount_cents` multiplied by the term's `late_fee_pct`,
        rounded half up to whole cents **before** any summation, with
        `due_date` equal to the installment's own due date and `source_ref`
        equal to the installment id; the installment's `late_fee_posted` flag
        is set so no installment ever accrues the fee twice."

        Design: Difficulty/combinatorial_formula/installment_rounding_remainder_and_late_fee_order
        """
        ctx = self._setup()
        cycle = run_billing_cycle_at(ctx["term"]["id"], "2026-10-15T00:00:00Z")
        # Installments 1 (due 09-01) and 2 (due 10-01) are past the 10-day
        # grace at clock 2026-10-15; installment 3 (due 10-31) is untouched.
        assert cycle["installments_marked_past_due"] == 2
        assert cycle["late_fees_posted"] == 2

        ledger = read_ledger(ctx["account_id"])
        fees = entries_of_type(ledger, "LATE_FEE")
        assert len(fees) == 2, "one LATE_FEE entry per flipped installment"
        # round_half_up(33334 * 0.05) = 1667 per installment (sum 3334, not
        # the sum-then-round 3333).
        assert sorted(f["amount_cents"] for f in fees) == [1667, 1667]
        installments = get_installments(ctx["plan"]["id"])
        by_seq = {i["sequence"]: i for i in installments}
        assert by_seq[1]["late_fee_posted"] is True
        assert by_seq[2]["late_fee_posted"] is True
        assert by_seq[3]["late_fee_posted"] is False
        fee_dues = sorted(f["due_date"] for f in fees)
        assert fee_dues == ["2026-09-01", "2026-10-01"]


class TestPaymentPlanDefaultCureCycle:
    """ACTIVE -> DEFAULTED -> ACTIVE with accumulating defaulted_count
    (PRD §3.7)."""

    def _setup_defaulted(self):
        ctx = setup_plan_scenario(credit_hours=9, installment_count=4,
                                  first_due_date="2026-09-01",
                                  external_ref="S-CYC")
        run_billing_cycle_at(ctx["term"]["id"], "2026-10-15T00:00:00Z")
        return ctx

    def test_cycle_flips_plan_to_defaulted(self, api, bursar_staff_headers):
        """PRD §3.7: "When the cycle flips at least one of a plan's
        installments to `PAST_DUE`, the plan moves from `ACTIVE` to
        `DEFAULTED`, its `defaulted_count` increments by one".

        Design: Difficulty/non_linear_state_machine/payment_plan_default_cure_cycle
        """
        ctx = self._setup_defaulted()
        plan = validate_success(
            api.get_payment_plan(ctx["plan"]["id"], bursar_staff_headers), 200
        )
        assert plan["status"] == "DEFAULTED"
        assert plan["defaulted_count"] == 1
        installments = get_installments(ctx["plan"]["id"])
        assert [i["status"] for i in installments] == [
            "PAST_DUE", "PAST_DUE", "SCHEDULED", "SCHEDULED",
        ]

    def test_paying_past_due_installments_cures_plan(self, api,
                                                     bursar_staff_headers):
        """PRD §3.7: "when an installment payment leaves no `PAST_DUE`
        installments on a `DEFAULTED` plan, the plan returns to `ACTIVE`" and
        "The `ACTIVE` → `DEFAULTED` → `ACTIVE` cycle may repeat any number of
        times over a plan's life, with `defaulted_count` accumulating each
        lap."

        Design: Difficulty/non_linear_state_machine/payment_plan_default_cure_cycle
        """
        ctx = self._setup_defaulted()
        installments = ctx["installments"]
        for inst in installments[:2]:
            validate_success(
                api.pay_installment(inst["id"], {"amount_cents": 83125},
                                    bursar_staff_headers),
                200,
            )
        plan = validate_success(
            api.get_payment_plan(ctx["plan"]["id"], bursar_staff_headers), 200
        )
        assert plan["status"] == "ACTIVE", "cure closes the loop, not terminal"
        assert plan["defaulted_count"] == 1, "default count accumulates"
        after = get_installments(ctx["plan"]["id"])
        assert [i["status"] for i in after] == [
            "PAID", "PAID", "SCHEDULED", "SCHEDULED",
        ]


def test_plan_completes_when_all_installments_paid(api, bursar_staff_headers):
    """PRD §3.7: "When every installment reaches `PAID`, the plan moves to
    terminal `COMPLETED` from either `ACTIVE` or `DEFAULTED`."

    Design: Corner/state_machines/plan_completes_when_all_installments_paid
    """
    ctx = setup_plan_scenario(credit_hours=2, installment_count=2,
                              first_due_date="2026-09-01", external_ref="S-CMP")
    installments = ctx["installments"]
    validate_success(
        api.pay_installment(installments[0]["id"], {"amount_cents": 43750},
                            bursar_staff_headers),
        200,
    )
    mid = validate_success(
        api.get_payment_plan(ctx["plan"]["id"], bursar_staff_headers), 200
    )
    assert mid["status"] == "ACTIVE", "one installment still open"
    validate_success(
        api.pay_installment(installments[1]["id"], {"amount_cents": 43750},
                            bursar_staff_headers),
        200,
    )
    end = validate_success(
        api.get_payment_plan(ctx["plan"]["id"], bursar_staff_headers), 200
    )
    assert end["status"] == "COMPLETED"


def test_second_plan_while_active_rejected(api, bursar_staff_headers):
    """PRD §3.7: "At most one live plan may exist per account: creation while
    an `ACTIVE` plan already exists is rejected with `ERR_PLAN_ALREADY_ACTIVE`
    (HTTP 409)."

    Design: Corner/validations/second_plan_while_active_rejected
    """
    ctx = setup_plan_scenario(credit_hours=9, installment_count=2,
                              external_ref="S-2P")
    fresh_version = account_version(ctx["account_id"])
    res = api.create_payment_plan(
        create_payment_plan_payload(
            account_id=ctx["account_id"], installment_count=3,
            first_due_date="2026-09-15",
            expected_account_version=fresh_version,
        ),
        bursar_staff_headers,
    )
    validate_error(res, ApiErrorId.ERR_PLAN_ALREADY_ACTIVE, expected_status=409)


def test_plan_create_with_stale_version_rejected(api, bursar_staff_headers):
    """PRD §2.8: "payment-plan creation requires the request to carry
    `expected_account_version` equal to the account's current `version`; if
    another writer has advanced the account version since the client last read
    the account — for example by posting a payment that changed the principal
    basis ... the request is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/validations/plan_create_with_stale_version_rejected
    """
    ctx = setup_account_with_enrollment(credit_hours=9, external_ref="S-STL")
    acc = ctx["account_id"]
    stale_version = account_version(acc)
    make_payment(acc, 1000)  # advances the account version
    res = api.create_payment_plan(
        create_payment_plan_payload(
            account_id=acc, installment_count=2,
            first_due_date="2026-09-01",
            expected_account_version=stale_version,
        ),
        bursar_staff_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    plans = get_success_data(
        api.list_account_payment_plans(acc, bursar_staff_headers)
    )
    assert plans == [], "no plan may be created off a stale version"


class TestPlanBlockedByCollectionsAccount:
    """Plan creation requires account OPEN or PAST_DUE (PRD §3.7)."""

    def test_collections_transition_posts_five_percent_fee(self, api):
        """PRD §3.10: "The transition posts a `COLLECTIONS_FEE` entry computed
        as the account's `balance_cents` multiplied by five percent, rounded
        half up to whole cents, with `due_date` set to the current clock date
        and `source_ref` set to the account id, and the account status becomes
        `COLLECTIONS`."

        Design: Difficulty/cross_entity_state_dependency/plan_blocked_by_collections_account
        """
        ctx = setup_collections_account(credit_hours=9)
        account = ctx["account"]
        assert account["status"] == "COLLECTIONS"
        # round_half_up(330000 * 0.05) = 16500 on top of the 330000 balance.
        assert account["balance_cents"] == 346500
        ledger = read_ledger(ctx["account_id"])
        fees = entries_of_type(ledger, "COLLECTIONS_FEE")
        assert len(fees) == 1 and fees[0]["amount_cents"] == 16500
        assert fees[0]["due_date"] == "2026-10-15"
        assert fees[0]["source_ref"] == ctx["account_id"]

    def test_plan_create_on_collections_account_rejected(
        self, api, bursar_staff_headers
    ):
        """PRD §3.7: "The account must be `OPEN` or `PAST_DUE`
        (`ERR_ACCOUNT_STATE_INVALID` otherwise)".

        Design: Difficulty/cross_entity_state_dependency/plan_blocked_by_collections_account
        """
        ctx = setup_collections_account(credit_hours=9)
        fresh_version = account_version(ctx["account_id"])
        res = api.create_payment_plan(
            create_payment_plan_payload(
                account_id=ctx["account_id"], installment_count=3,
                first_due_date="2026-11-01",
                expected_account_version=fresh_version,
            ),
            bursar_staff_headers,
        )
        validate_error(res, ApiErrorId.ERR_ACCOUNT_STATE_INVALID,
                       expected_status=409)


def test_plan_terminal_and_cancelled_installment_errors(api,
                                                        bursar_staff_headers):
    """PRD §3.7: "cancelling a `COMPLETED` or already-`CANCELLED` plan is
    rejected with `ERR_PLAN_STATE_INVALID` (HTTP 409)", "Cancellation moves
    every non-`PAID` installment to `CANCELLED`", and "Payment is accepted
    only while the installment is `SCHEDULED` or `PAST_DUE` (otherwise
    `ERR_INSTALLMENT_STATE_INVALID`, HTTP 409) and only while the parent plan
    is `ACTIVE` or `DEFAULTED` (otherwise `ERR_PLAN_STATE_INVALID`)".

    Design: Corner/errors/plan_terminal_and_cancelled_installment_errors
    """
    ctx = setup_plan_scenario(credit_hours=2, installment_count=2,
                              first_due_date="2026-09-01", external_ref="S-CPL")
    plan_id = ctx["plan"]["id"]
    inst = ctx["installments"][0]
    validate_success(api.cancel_payment_plan(plan_id, bursar_staff_headers), 200)

    res = api.cancel_payment_plan(plan_id, bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_PLAN_STATE_INVALID, expected_status=409)

    cancelled = get_installments(plan_id)
    assert cancelled[0]["status"] == "CANCELLED"

    res = api.pay_installment(inst["id"], {"amount_cents": 43750},
                              bursar_staff_headers)
    # Both state preconditions fail; PRD §3.7 names both rejections without
    # ordering them against each other.
    validate_error_is_one_of(
        res,
        [ApiErrorId.ERR_INSTALLMENT_STATE_INVALID.value,
         ApiErrorId.ERR_PLAN_STATE_INVALID.value],
    )
    assert res.status_code == 409


def test_installment_partial_amount_returns_422(api, bursar_staff_headers):
    """PRD §3.7: "the request's `amount_cents` must equal the installment's
    remaining amount — its `amount_cents` minus its `paid_cents` — and any
    deviation is rejected with `ERR_INSTALLMENT_AMOUNT_MISMATCH` (HTTP 422)."

    Design: Corner/errors/installment_partial_amount_returns_422
    """
    ctx = setup_plan_scenario(credit_hours=2, installment_count=2,
                              first_due_date="2026-09-01", external_ref="S-PRT")
    inst = ctx["installments"][0]
    res = api.pay_installment(inst["id"], {"amount_cents": 40000},
                              bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_INSTALLMENT_AMOUNT_MISMATCH,
                   expected_status=422)
    after = get_installments(ctx["plan"]["id"])[0]
    assert after["status"] == "SCHEDULED"
    assert after["paid_cents"] == 0


class TestInstallmentPayStateBeatsAmount:
    """State precondition (family 4) outranks the fiscal rule (family 8)."""

    def _setup_paid_installment(self):
        ctx = setup_plan_scenario(credit_hours=2, installment_count=2,
                                  first_due_date="2026-09-01",
                                  external_ref="S-PR1")
        inst = ctx["installments"][0]
        pay_installment_exact(inst)
        return ctx, inst

    def test_paid_installment_with_wrong_amount_reports_state(
        self, api, bursar_staff_headers
    ):
        """PRD §2.9: the pipeline evaluates "(4) target-entity state
        preconditions" before "(8) fiscal and amount rules", and "Ordering
        matters because it determines which error surfaces when several rules
        are violated at once".
        PRD §3.7: "Payment is accepted only while the installment is
        `SCHEDULED` or `PAST_DUE` (otherwise `ERR_INSTALLMENT_STATE_INVALID`,
        HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/installment_pay_state_beats_amount
        """
        _ctx, inst = self._setup_paid_installment()
        res = api.pay_installment(inst["id"], {"amount_cents": 1},
                                  bursar_staff_headers)
        validate_error(res, ApiErrorId.ERR_INSTALLMENT_STATE_INVALID,
                       expected_status=409)

    def test_paid_installment_with_exact_amount_still_state_error(
        self, api, bursar_staff_headers
    ):
        """PRD §3.7: "Payment is accepted only while the installment is
        `SCHEDULED` or `PAST_DUE` (otherwise `ERR_INSTALLMENT_STATE_INVALID`,
        HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/installment_pay_state_beats_amount
        """
        _ctx, inst = self._setup_paid_installment()
        res = api.pay_installment(inst["id"], {"amount_cents": 43750},
                                  bursar_staff_headers)
        validate_error(res, ApiErrorId.ERR_INSTALLMENT_STATE_INVALID,
                       expected_status=409)
