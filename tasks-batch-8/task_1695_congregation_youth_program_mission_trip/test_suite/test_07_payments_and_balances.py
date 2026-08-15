"""Payments, balances, and the delinquency sweep: deposit-equality boundary,
overpayment floor, immediate read-after-write, refund conservation, the
strictly-greater sweep boundary, and the delinquency cure cycle."""
from test_helpers import (
    ApiErrorId,
    add_donation,
    apply_account_credit,
    create_approved_registration,
    get_account_for_registration,
    get_registration,
    make_director_headers,
    make_treasurer_headers,
    post_payment,
    set_clock,
    setup_program_with_open_trip,
    assert_same_instant,
    validate_error,
    validate_success,
)

DIRECTOR = make_director_headers()
TREASURER = make_treasurer_headers()

BETA = {"base_cost_cents": 80000, "deposit_cents": 50000}


def _beta_trip_with_approved_registration(api, guardian="guardian-1",
                                          **participant_overrides):
    program, trip = setup_program_with_open_trip(**BETA)
    participant, registration, _ = create_approved_registration(
        trip["id"], guardian, participant_overrides=participant_overrides)
    return program, trip, participant, registration


class TestConfirmDepositBoundary:
    def test_confirm_deposit_exact_equality_boundary(self, api):
        """PRD §3.3: "Confirmation — `APPROVED` to `CONFIRMED`, by a
        `ProgramDirector` — ... requires the trip to be `REGISTRATION_OPEN` or
        `REGISTRATION_CLOSED`, and `covered_cents` to be at least the trip's
        `deposit_cents`, with exact equality passing (`ERR_DEPOSIT_NOT_COVERED`,
        HTTP 402 otherwise)."

        Design: Corner/state_machines/confirm_deposit_exact_equality_boundary
        """
        _, _, _, registration = _beta_trip_with_approved_registration(api)
        post_payment(registration["id"], 49999)

        e_low = api.confirm_registration(registration["id"], DIRECTOR)
        validate_error(e_low, ApiErrorId.ERR_DEPOSIT_NOT_COVERED, 402)

        post_payment(registration["id"], 1)  # covered exactly 50000
        confirmed = api.confirm_registration(registration["id"], DIRECTOR)
        assert validate_success(confirmed, 200)["registration_status"] == \
            "CONFIRMED"


class TestOverpaymentFloor:
    def test_overpayment_floors_amount_due_at_zero(self, api):
        """PRD §3.4: "`amount_due_cents` is the cost basis in force — provisional
        before roster lock, final after — plus `late_fees_total_cents`, minus
        `covered_cents`, floored at zero." and "covering the full amount due
        (when that total is greater than zero) yields `PAID_IN_FULL`".

        Design: Corner/calculations/overpayment_floors_amount_due_at_zero
        """
        _, _, _, registration = _beta_trip_with_approved_registration(api)
        post_payment(registration["id"], 90000)  # basis is 80000

        data = get_registration(registration["id"])
        assert data["covered_cents"] == 90000
        assert data["amount_due_cents"] == 0, "amount_due_cents never negative"
        assert data["payment_status"] == "PAID_IN_FULL"


class TestImmediateConsistency:
    def test_immediate_read_after_write_consistency(self, api):
        """PRD §2.9: "Every operation that changes an input to one of these
        rollups recomputes the rollup synchronously within the same request."
        PRD §3.4: "The new payment is `POSTED` with `posted_at` stamped from the
        logical clock, and the registration's coverage and payment status are
        recomputed immediately".

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        _, _, _, registration = _beta_trip_with_approved_registration(api)
        post_payment(registration["id"], 50000)

        data = get_registration(registration["id"])
        assert data["covered_cents"] == 50000
        assert data["amount_due_cents"] == 30000
        assert data["payment_status"] == "PARTIALLY_PAID"


class TestPaymentRefundConservation:
    def test_payment_post_moves_coverage_forward(self, api):
        """PRD §3.4: "`covered_cents` is the sum of `amount_cents` over the
        registration's `POSTED` payments, plus `fundraising_credit_applied_cents`,
        plus `scholarship_awarded_cents`." and "otherwise covering at least
        `deposit_cents` yields `PARTIALLY_PAID`; otherwise `PENDING_DEPOSIT`".

        Design: Difficulty/compensating_invariant/payment_post_refund_net_collected_conservation
        """
        _, _, _, registration = _beta_trip_with_approved_registration(api)
        before = get_registration(registration["id"])
        assert before["covered_cents"] == 0
        assert before["amount_due_cents"] == 80000
        assert before["payment_status"] == "PENDING_DEPOSIT"

        post_payment(registration["id"], 50000)
        after = get_registration(registration["id"])
        assert after["covered_cents"] == 50000
        assert after["amount_due_cents"] == 30000
        assert after["payment_status"] == "PARTIALLY_PAID", (
            "50000 >= deposit 50000 but < 80000 due")

    def test_payment_refund_restores_net_collected(self, api):
        """PRD §3.4: "A refund recomputes coverage and can downgrade the payment
        status — from `PARTIALLY_PAID` back to `PENDING_DEPOSIT` when coverage
        drops below the deposit, or from `PAID_IN_FULL` to `PARTIALLY_PAID`."

        Design: Difficulty/compensating_invariant/payment_post_refund_net_collected_conservation
        """
        _, _, _, registration = _beta_trip_with_approved_registration(api)
        payment = post_payment(registration["id"], 50000)
        refunded = api.refund_payment(payment["id"], TREASURER,
                                      payload={"reason": "duplicate entry"})
        assert validate_success(refunded, 200)["status"] == "REFUNDED"

        restored = get_registration(registration["id"])
        assert restored["covered_cents"] == 0, "net-collected back to zero"
        assert restored["amount_due_cents"] == 80000
        assert restored["payment_status"] == "PENDING_DEPOSIT", (
            "derived status restored exactly to its pre-action value")


class TestPaymentDeadlineBoundary:
    def test_payment_posted_exactly_at_deadline_is_on_time(self, api):
        """PRD §3.6: "A clock reading exactly equal to a deadline does not fire
        the sweep; the comparison is strictly greater."
        PRD §3.4: "The new payment is `POSTED` with `posted_at` stamped from the
        logical clock".

        Design: Difficulty/boundary_precision_check/payment_deadline_inclusive_timestamp_boundary
        """
        program, trip = setup_program_with_open_trip(**BETA)
        _, reg1, _ = create_approved_registration(trip["id"], "guardian-1")
        _, reg2, _ = create_approved_registration(
            trip["id"], "guardian-2",
            participant_overrides={"family_key": "fam-2"})

        # Land exactly on the deposit deadline: the sweep does not fire.
        set_clock("2027-01-15T00:00:00Z")
        payment = post_payment(reg1["id"], 50000)
        assert_same_instant(payment["posted_at"], "2027-01-15T00:00:00Z",
                            "posted_at")

        reg2_at_due = get_registration(reg2["id"])
        assert reg2_at_due["payment_status"] == "PENDING_DEPOSIT"
        assert reg2_at_due["late_fees_total_cents"] == 0, (
            "at clock == deposit_due_at the strict-> sweep does not fire")

    def test_sweep_fires_one_second_past_deadline(self, api):
        """PRD §3.6: "Sweep A targets the deposit milestone: for every
        registration in `APPROVED` or `CONFIRMED` whose trip's new clock reading
        is strictly past `deposit_due_at` and whose `covered_cents` is below
        `deposit_cents`, with no deposit late fee yet assessed, the registration
        moves to `DELINQUENT` and a late fee is added to `late_fees_total_cents`.
        ... The fee in both cases is the greater of a 2500-cent flat amount and
        5% of the `amount_due_cents` at sweep time, that percentage rounded half
        up to the nearest cent."

        Design: Difficulty/boundary_precision_check/payment_deadline_inclusive_timestamp_boundary
        """
        program, trip = setup_program_with_open_trip(**BETA)
        _, reg1, _ = create_approved_registration(trip["id"], "guardian-1")
        _, reg2, _ = create_approved_registration(
            trip["id"], "guardian-2",
            participant_overrides={"family_key": "fam-2"})

        set_clock("2027-01-15T00:00:00Z")
        post_payment(reg1["id"], 50000)  # deposit covered in time
        set_clock("2027-01-15T00:00:01Z")  # strictly past -> sweep fires

        reg1_after = get_registration(reg1["id"])
        assert reg1_after["payment_status"] == "PARTIALLY_PAID"
        assert reg1_after["late_fees_total_cents"] == 0

        reg2_after = get_registration(reg2["id"])
        assert reg2_after["payment_status"] == "DELINQUENT"
        assert reg2_after["late_fees_total_cents"] == 4000, (
            "max(2500, round_half_up(0.05*80000)) = 4000")
        assert reg2_after["amount_due_cents"] == 84000


class TestDelinquencyCureCycle:
    def test_final_deadline_sweep_marks_delinquent_with_flat_floor_fee(self, api):
        """PRD §3.6: "Sweep B targets the final milestone: same statuses, clock
        strictly past `final_payment_due_at`, `amount_due_cents` still positive,
        and no final fee yet assessed. The fee in both cases is the greater of a
        2500-cent flat amount and 5% of the `amount_due_cents` at sweep time".
        PRD §3.4: "`DELINQUENT` overlays the baseline when a sweep fires".

        Design: Difficulty/non_linear_state_machine/registration_parallel_dimensions_delinquency_cure_cycle
        """
        _, _, _, registration = _beta_trip_with_approved_registration(api)
        post_payment(registration["id"], 50000)
        confirmed = api.confirm_registration(registration["id"], DIRECTOR)
        assert validate_success(confirmed, 200)["registration_status"] == \
            "CONFIRMED"

        # Deposit deadline passes: covered 50000 >= 50000, no delinquency.
        set_clock("2027-01-16T00:00:00Z")
        after_deposit = get_registration(registration["id"])
        assert after_deposit["payment_status"] == "PARTIALLY_PAID"
        assert after_deposit["late_fees_total_cents"] == 0

        # Final deadline passes with 30000 outstanding.
        set_clock("2027-05-02T00:00:00Z")
        after_final = get_registration(registration["id"])
        assert after_final["payment_status"] == "DELINQUENT"
        assert after_final["late_fees_total_cents"] == 2500, (
            "max(2500, round_half_up(0.05*30000)=1500) -> flat floor wins")
        assert after_final["amount_due_cents"] == 32500
        assert after_final["registration_status"] == "CONFIRMED", (
            "the two registration dimensions evolve independently")

    def test_full_coverage_payment_cures_delinquency_to_paid_in_full(self, api):
        """PRD §3.6: "A delinquent registration is cured by money, not by time.
        ... once the clock is past `final_payment_due_at`, only full coverage of
        the amount due cures — to `PAID_IN_FULL`. Covering the full amount due at
        any time (via payment, disbursement, or applied credit) moves a
        delinquent registration straight to `PAID_IN_FULL`."

        Design: Difficulty/non_linear_state_machine/registration_parallel_dimensions_delinquency_cure_cycle
        """
        _, _, _, registration = _beta_trip_with_approved_registration(api)
        post_payment(registration["id"], 50000)
        api.confirm_registration(registration["id"], DIRECTOR)
        set_clock("2027-05-02T00:00:00Z")
        delinquent = get_registration(registration["id"])
        assert delinquent["payment_status"] == "DELINQUENT"
        assert delinquent["late_fees_total_cents"] == 2500

        post_payment(registration["id"], 32500)  # 80000 + 2500 - 50000
        cured = get_registration(registration["id"])
        assert cured["covered_cents"] == 82500
        assert cured["payment_status"] == "PAID_IN_FULL", (
            "DELINQUENT cured by full coverage, completing the cycle")
        assert cured["registration_status"] == "CONFIRMED", (
            "registration_status never left CONFIRMED during the payment cycle")


class TestPaymentAndDonationTerminalLockdown:
    def test_payment_and_donation_terminal_lockdown(self, api):
        """PRD §3.4: "A treasurer may refund a `POSTED` payment (optionally with
        a `reason`); refunding a payment that is not `POSTED` is rejected with
        `ERR_PAYMENT_STATE_FORBIDS_ACTION`."
        PRD §3.4: "A donation in `APPLIED` can never be refunded; refunding a
        donation requires it to still be `RECEIVED`
        (`ERR_DONATION_STATE_FORBIDS_ACTION` otherwise)".

        Design: Corner/state_machines/payment_and_donation_terminal_lockdown
        """
        _, _, _, registration = _beta_trip_with_approved_registration(api)
        payment = post_payment(registration["id"], 50000)
        account = get_account_for_registration(registration["id"])
        donation = add_donation(account["id"], 5000, "CASH")

        credited = apply_account_credit(account["id"])
        assert credited["credit_applied_cents"] == 5000, (
            "apply-credit swept the RECEIVED donation to APPLIED")

        first = api.refund_payment(payment["id"], TREASURER)
        assert validate_success(first, 200)["status"] == "REFUNDED"
        second = api.refund_payment(payment["id"], TREASURER)
        validate_error(second, ApiErrorId.ERR_PAYMENT_STATE_FORBIDS_ACTION, 409)

        e_don = api.refund_donation(donation["id"], TREASURER)
        validate_error(e_don, ApiErrorId.ERR_DONATION_STATE_FORBIDS_ACTION, 409)
