"""Tuition computation, invoicing, finalization, payment and refund behavior.

Covers the dual-variant tuition calculation (provisional vs finalized), the pinned
per-session rounding order, the period-vs-funds validation precedence, the
wallet-conservation refund invariant, and the supporting corner claims.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    TEST_USERS,
    create_studio_payload,
    create_family_payload,
    create_student_payload,
    create_instructor_payload,
    create_room_payload,
    create_enrollment_payload,
    create_invoice_payload,
    create_payment_payload,
    setup_active_enrollment,
    setup_issued_invoice_with_completed_sessions,
    create_occurrence,
    set_clock,
    assert_invoice,
)

ADMIN = TEST_USERS["studio_admin_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ===========================================================================
# Difficulty / dual_variant_calc / tuition_provisional_vs_finalized_diverge
# ===========================================================================
class TestProvisionalVsFinalizedDiverge:
    def test_finalized_differs_from_provisional_on_same_invoice(self, api):
        """PRD 3.3: "Because the provisional path prorates the whole month and rounds
        once while the finalized path rounds each session before summing, the two
        figures can legitimately differ by a few cents for the same enrollment."

        Design: Difficulty/dual_variant_calc/tuition_provisional_vs_finalized_diverge
        """
        env = setup_issued_invoice_with_completed_sessions(
            hourly_rate_cents=8333, duration_min=45
        )
        sid, inv = env["studio"]["id"], env["invoice"]
        assert inv["provisional_amount_cents"] == 24999

        finalized = validate_success(api.finalize_invoice(sid, inv["id"], BILLING), 200)
        assert finalized["finalized_amount_cents"] == 25000
        assert (
            finalized["finalized_amount_cents"] != inv["provisional_amount_cents"]
        ), "finalized must differ from provisional for this enrollment+period"

    def test_provisional_value_is_prorate_then_round_once(self, api):
        """PRD 3.3: "The prorated base is `monthly_tuition_cents` multiplied by the
        remaining sessions, divided by four sessions per month, rounded half up to
        whole cents. The provisional amount is then that prorated base multiplied by
        one minus the family's `family_discount_pct` read at issue time, rounded half
        up to whole cents."

        Design: Difficulty/dual_variant_calc/tuition_provisional_vs_finalized_diverge
        """
        env = setup_issued_invoice_with_completed_sessions(
            hourly_rate_cents=8333, duration_min=45
        )
        inv = env["invoice"]
        assert_invoice(inv)
        # monthly_tuition = round_half_up(8333 * 45 / 60 * 4) = 24999; 4 future
        # SCHEDULED sessions => prorate 24999 * 4/4 = 24999; no discount.
        assert inv["provisional_amount_cents"] == 24999
        assert inv["amount_due_cents"] == 24999
        assert inv["finalized_amount_cents"] == 0


# ===========================================================================
# Difficulty / combinatorial_formula / finalized_round_per_session_then_sum_order
# ===========================================================================
class TestFinalizedRoundingOrder:
    def test_finalized_rounds_per_session_then_sums(self, api):
        """PRD 3.3: "First, the per-session rate is `monthly_tuition_cents` divided by
        four sessions per month, rounded half up to whole cents." ... "The gross is the
        per-session rate multiplied by the billable count, where the per-session
        rounding happens before this multiplication and summation."

        Design: Difficulty/combinatorial_formula/finalized_round_per_session_then_sum_order
        """
        env = setup_issued_invoice_with_completed_sessions(
            hourly_rate_cents=8333, duration_min=45
        )
        sid, inv = env["studio"]["id"], env["invoice"]
        assert env["enrollment"]["monthly_tuition_cents"] == 24999

        finalized = validate_success(api.finalize_invoice(sid, inv["id"], BILLING), 200)
        # per_session_rate = round_half_up(24999/4) = 6250; 6250 * 4 = 25000.
        assert finalized["finalized_amount_cents"] == 25000

    def test_one_cent_gap_only_from_per_session_rounding(self, api):
        """PRD 3.3: "Because the provisional path prorates the whole month and rounds
        once while the finalized path rounds each session before summing, the two
        figures can legitimately differ by a few cents for the same enrollment."

        Design: Difficulty/combinatorial_formula/finalized_round_per_session_then_sum_order
        """
        env = setup_issued_invoice_with_completed_sessions(
            hourly_rate_cents=8333, duration_min=45
        )
        sid, inv = env["studio"]["id"], env["invoice"]
        finalized = validate_success(api.finalize_invoice(sid, inv["id"], BILLING), 200)
        # 25000 (round-per-session-then-sum) vs 24999 (prorate-then-round-once).
        assert finalized["finalized_amount_cents"] - inv["provisional_amount_cents"] == 1


# ===========================================================================
# Difficulty / priority_pair_validation_conflict /
#   period_not_ended_vs_insufficient_funds_period_wins
# ===========================================================================
class TestPeriodNotEndedOutranksFunds:
    def _setup_unended_period_autopay_zero_wallet(self, api):
        studio, family, student, instructor, room, enr = setup_active_enrollment(
            family_overrides={"autopay_enabled": True},
            instructor_overrides={
                "hourly_rate_cents": 6000,
                "weekly_availability": [{"weekday": 0, "start_min": 0, "end_min": 1440}],
            },
        )
        sid = studio["id"]
        inv = get_success_data(
            api.create_invoice(sid, create_invoice_payload(enr["id"], "2026-01"), BILLING)
        )
        set_clock(sid, "2026-01-15T00:00:00.000Z")  # period NOT ended
        return sid, inv

    def test_finalize_before_period_end_returns_period_not_ended(self, api):
        """PRD 3.3: "Finalization ... is permitted only when the billing period has
        fully elapsed — that is, when the studio clock is at or after the first instant
        of the month after `billing_period` — otherwise it fails with
        `ERR_PERIOD_NOT_ENDED` (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/period_not_ended_vs_insufficient_funds_period_wins
        """
        sid, inv = self._setup_unended_period_autopay_zero_wallet(api)
        res = api.finalize_invoice(sid, inv["id"], BILLING)
        validate_error(res, "ERR_PERIOD_NOT_ENDED", expected_status=409)

    def test_period_check_pre_empts_funds_check_for_autopay_zero_wallet(self, api):
        """PRD 2.6: "This priority chain is global: authentication outranks
        authorization, which outranks existence, which outranks request validity, which
        outranks referential scope, which outranks state and business checks." PRD 3.3:
        "Finalization ... is permitted only when the billing period has fully elapsed ...
        otherwise it fails with `ERR_PERIOD_NOT_ENDED` (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/period_not_ended_vs_insufficient_funds_period_wins
        """
        sid, inv = self._setup_unended_period_autopay_zero_wallet(api)
        # Autopay family with a zero wallet would fail funds at finalize, but the
        # period gate fires first and the invoice never finalizes / charges.
        res = api.finalize_invoice(sid, inv["id"], BILLING)
        validate_error(res, "ERR_PERIOD_NOT_ENDED", expected_status=409)
        after = validate_success(api.get_invoice(sid, inv["id"], BILLING), 200)
        assert after["status"] == "ISSUED", "invoice must remain ISSUED after period-gate rejection"


# ===========================================================================
# Difficulty / compensating_invariant / payment_then_refund_leaves_wallet_unchanged
# ===========================================================================
class TestPaymentRefundWalletInvariant:
    def test_refund_restores_wallet_to_prepayment_value(self, api):
        """PRD 2.8: "a successful payment followed by its refund leaves
        `wallet_balance_cents` exactly where it began". PRD 3.10: "The refund adds the
        payment's `amount_cents` back to the family's `wallet_balance_cents`, returning
        the wallet to its pre-payment value".

        Design: Difficulty/compensating_invariant/payment_then_refund_leaves_wallet_unchanged
        """
        env = setup_issued_invoice_with_completed_sessions(
            hourly_rate_cents=6000, duration_min=60, credit_wallet_cents=50000
        )
        sid, inv, fid = env["studio"]["id"], env["invoice"], env["family"]["id"]
        validate_success(api.finalize_invoice(sid, inv["id"], BILLING), 200)
        pay = validate_success(
            api.create_payment(sid, create_payment_payload(inv["id"], method="WALLET"), BILLING),
            201,
        )
        after_pay = validate_success(api.get_family(sid, fid, BILLING), 200)
        assert after_pay["wallet_balance_cents"] == 26000  # 50000 - 24000

        validate_success(api.refund_payment(sid, pay["id"], BILLING), 200)
        after_refund = validate_success(api.get_family(sid, fid, BILLING), 200)
        assert after_refund["wallet_balance_cents"] == 50000  # zero drift

    def test_refund_marks_payment_refunded_and_reopens_invoice(self, api):
        """PRD 3.10: "A `BillingClerk` may refund a `SUCCEEDED` payment, moving it
        `SUCCEEDED → REFUNDED` (terminal)." ... "and re-opens the associated invoice
        from `PAID → FINALIZED` so it is unpaid again."

        Design: Difficulty/compensating_invariant/payment_then_refund_leaves_wallet_unchanged
        """
        env = setup_issued_invoice_with_completed_sessions(
            hourly_rate_cents=6000, duration_min=60, credit_wallet_cents=50000
        )
        sid, inv = env["studio"]["id"], env["invoice"]
        validate_success(api.finalize_invoice(sid, inv["id"], BILLING), 200)
        pay = validate_success(
            api.create_payment(sid, create_payment_payload(inv["id"], method="WALLET"), BILLING),
            201,
        )
        assert validate_success(api.get_invoice(sid, inv["id"], BILLING), 200)["status"] == "PAID"

        refunded = validate_success(api.refund_payment(sid, pay["id"], BILLING), 200)
        assert refunded["status"] == "REFUNDED"
        reopened = validate_success(api.get_invoice(sid, inv["id"], BILLING), 200)
        assert reopened["status"] == "FINALIZED"


# ===========================================================================
# Corner / endpoints / finalize_autopay_pays_invoice_and_debits_wallet
# ===========================================================================
def test_finalize_autopay_pays_invoice_and_debits_wallet(api):
    """PRD 3.3: "Once finalized, if the family has `autopay_enabled` and its `status`
    is `ACTIVE`, the system synthesizes an `AUTOPAY` payment in a cascade: on success
    the payment's `status` is `SUCCEEDED`, the invoice moves to `PAID`, and the
    family's `wallet_balance_cents` is debited".

    Design: Corner/endpoints/finalize_autopay_pays_invoice_and_debits_wallet
    """
    env = setup_issued_invoice_with_completed_sessions(
        hourly_rate_cents=6000,
        duration_min=60,
        family_overrides={"autopay_enabled": True},
        credit_wallet_cents=30000,
    )
    sid, inv, fid = env["studio"]["id"], env["invoice"], env["family"]["id"]
    finalized = validate_success(api.finalize_invoice(sid, inv["id"], BILLING), 200)
    assert finalized["status"] == "PAID"
    assert finalized["amount_due_cents"] == 24000
    family = validate_success(api.get_family(sid, fid, BILLING), 200)
    assert family["wallet_balance_cents"] == 6000  # 30000 - 24000


# ===========================================================================
# Corner / errors / payment_insufficient_funds_rejected
# ===========================================================================
def test_payment_insufficient_funds_rejected(api):
    """PRD 3.10: "A payment succeeds only when the family's `wallet_balance_cents` is
    at least `amount_due_cents`; otherwise the payment's `status` is `FAILED`, its
    `failure_reason` is set to `INSUFFICIENT_FUNDS`, the operation reports
    `ERR_INSUFFICIENT_FUNDS` (HTTP 402)".

    Design: Corner/errors/payment_insufficient_funds_rejected
    """
    env = setup_issued_invoice_with_completed_sessions(
        hourly_rate_cents=6000, duration_min=60
    )  # non-autopay, wallet 0
    sid, inv = env["studio"]["id"], env["invoice"]
    validate_success(api.finalize_invoice(sid, inv["id"], BILLING), 200)
    res = api.create_payment(sid, create_payment_payload(inv["id"], method="WALLET"), BILLING)
    validate_error(res, "ERR_INSUFFICIENT_FUNDS", expected_status=402)


# ===========================================================================
# Corner / calculations / provisional_proration_partial_month
# ===========================================================================
def test_provisional_proration_partial_month(api):
    """PRD 3.3: "the system first counts the enrollment's `SCHEDULED` lesson
    occurrences whose `scheduled_start_utc` falls within the billing period and is at
    or after the current studio clock, calling that count the remaining sessions. The
    prorated base is `monthly_tuition_cents` multiplied by the remaining sessions,
    divided by four sessions per month, rounded half up to whole cents."

    Design: Corner/calculations/provisional_proration_partial_month
    """
    studio, family, student, instructor, room, enr = setup_active_enrollment(
        instructor_overrides={
            "hourly_rate_cents": 6000,
            "weekly_availability": [{"weekday": 0, "start_min": 0, "end_min": 1440}],
        }
    )
    sid = studio["id"]
    for s in ("2026-01-12T10:00:00.000Z", "2026-01-19T10:00:00.000Z", "2026-01-26T10:00:00.000Z"):
        create_occurrence(sid, enr["id"], s)
    inv = validate_success(
        api.create_invoice(sid, create_invoice_payload(enr["id"], "2026-01"), BILLING), 201
    )
    # monthly_tuition 24000; 3 future SCHEDULED sessions; round_half_up(24000*3/4)=18000.
    assert inv["provisional_amount_cents"] == 18000


# ===========================================================================
# Corner / entities / enrollment_monthly_tuition_computed_ignores_input
# ===========================================================================
def test_enrollment_monthly_tuition_computed_ignores_input(api):
    """PRD 3.3: "Each enrollment's base monthly tuition before any family discount,
    stored as `monthly_tuition_cents`, is computed at enrollment creation as the
    instructor's `hourly_rate_cents` multiplied by `duration_min`, divided by 60 to
    convert to the lesson's fraction of an hour, then multiplied by the number of
    sessions in a month, which is fixed at four, with the result rounded half up to
    whole cents."

    Design: Corner/entities/enrollment_monthly_tuition_computed_ignores_input
    """
    studio = get_success_data(api.create_studio(create_studio_payload(), ADMIN))
    sid = studio["id"]
    family = get_success_data(api.create_family(sid, create_family_payload(), ADMIN))
    student = get_success_data(api.create_student(sid, create_student_payload(family["id"]), ADMIN))
    instructor = get_success_data(
        api.create_instructor(
            sid,
            create_instructor_payload(
                instruments=["PIANO"],
                weekly_availability=[{"weekday": 0, "start_min": 0, "end_min": 1440}],
                hourly_rate_cents=6000,
            ),
            ADMIN,
        )
    )
    room = get_success_data(api.create_room(sid, create_room_payload(supported_instruments=["PIANO"]), ADMIN))
    enr = validate_success(
        api.create_enrollment(
            sid,
            create_enrollment_payload(
                student["id"], instructor["id"], room["id"],
                instrument="PIANO", weekday=0, start_min=600, duration_min=60,
            ),
            ADMIN,
        ),
        201,
    )
    # round_half_up(6000 * 60 / 60 * 4) = 24000.
    assert enr["monthly_tuition_cents"] == 24000
    assert enr["lifecycle_status"] == "PENDING_MATCH"
    assert enr["billing_status"] == "UNBILLED"
