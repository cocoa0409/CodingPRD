"""Payment and voucher claims: funding-threshold boundary, insufficient
funds, overpayment ceiling, voucher/student ownership, parallel voucher
dimensions, and the clear/reverse balance invariant."""
from test_helpers import (
    ApiErrorId,
    create_payment_payload,
    get_success_data,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_family,
    create_issued_invoice,
    create_student,
    create_voucher_account,
    enroll_seat,
    post_and_clear_payment,
    set_clock,
    setup_dissolving_pod,
    setup_enrolled_seat,
    setup_family_student_seat,
    setup_pod_active,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pod_operator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]

AWARD = 600000          # cents; 50% threshold == 300000
HALF_AWARD = 300000


def _setup_verified_voucher_seat(api, award=AWARD):
    """ACTIVE pod + family + student + VERIFIED voucher account + ENROLLED
    seat. Returns (pod, family, student, voucher, seat)."""
    pod, *_ = setup_pod_active()
    family = create_family()
    student = create_student(family["id"])
    voucher = create_voucher_account(student["id"], awarded_annual_cents=award)
    voucher = get_success_data(api.verify_voucher_account(voucher["id"], OFFICER))
    assert voucher["verification_status"] == "VERIFIED"
    seat = get_success_data(api.create_seat(
        pod["id"], {"student_id": student["id"], "enrolled_on": "2026-08-01"},
        REGISTRAR,
    ))
    seat = enroll_seat(pod["id"], seat, family["id"])
    return pod, family, student, voucher, seat


class TestVoucherFundingThreshold:
    def test_balance_at_exactly_half_award_stays_funded(self, api):
        """PRD 3.7: "The payment amount is subtracted from
        `disbursable_balance_cents`, and the funding status is reclassified
        against the full `awarded_annual_cents`: a remaining balance of at
        least half the annual award keeps the account `FUNDED` — the
        half-award boundary is inclusive; a positive balance below half
        moves it to `PARTIALLY_DEPLETED`; a balance of exactly zero marks it
        `DEPLETED`."

        Design: Difficulty/boundary_precision_check/voucher_funded_threshold_50pct
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, family, student, voucher, seat = _setup_verified_voucher_seat(api)
        inv = create_issued_invoice(pod["id"], seat["id"])
        pay = get_success_data(api.create_payment(
            pod["id"], seat["id"], inv["id"],
            {"source_kind": "VOUCHER", "amount_cents": HALF_AWARD,
             "voucher_account_id": voucher["id"]},
            REGISTRAR,
        ))
        validate_success(api.clear_payment(pay["id"], OPERATOR))
        va = get_success_data(api.get_voucher_account(voucher["id"], OFFICER))
        assert va["disbursable_balance_cents"] == HALF_AWARD
        assert va["funding_status"] == "FUNDED", (
            f"balance == 50% of award must keep FUNDED, got "
            f"{va['funding_status']}"
        )

    def test_one_cent_below_half_award_flips_to_partially_depleted(self, api):
        """PRD 3.7: "The payment amount is subtracted from
        `disbursable_balance_cents`, and the funding status is reclassified
        against the full `awarded_annual_cents`: a remaining balance of at
        least half the annual award keeps the account `FUNDED` — the
        half-award boundary is inclusive; a positive balance below half
        moves it to `PARTIALLY_DEPLETED`; a balance of exactly zero marks it
        `DEPLETED`."

        Design: Difficulty/boundary_precision_check/voucher_funded_threshold_50pct
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, family, student, voucher, seat = _setup_verified_voucher_seat(api)
        inv = create_issued_invoice(
            pod["id"], seat["id"],
            line_items=[{"description": "Tuition", "quantity": 1,
                         "unit_amount_cents": HALF_AWARD + 10000,
                         "kind": "TUITION"}],
        )
        # Clear HALF_AWARD: balance lands exactly on the threshold.
        p1 = get_success_data(api.create_payment(
            pod["id"], seat["id"], inv["id"],
            {"source_kind": "VOUCHER", "amount_cents": HALF_AWARD,
             "voucher_account_id": voucher["id"]},
            REGISTRAR,
        ))
        validate_success(api.clear_payment(p1["id"], OPERATOR))
        va = get_success_data(api.get_voucher_account(voucher["id"], OFFICER))
        assert va["funding_status"] == "FUNDED"

        # Clear one more cent: balance drops one cent below the threshold.
        p2 = get_success_data(api.create_payment(
            pod["id"], seat["id"], inv["id"],
            {"source_kind": "VOUCHER", "amount_cents": 1,
             "voucher_account_id": voucher["id"]},
            REGISTRAR,
        ))
        validate_success(api.clear_payment(p2["id"], OPERATOR))
        va = get_success_data(api.get_voucher_account(voucher["id"], OFFICER))
        assert va["disbursable_balance_cents"] == HALF_AWARD - 1
        assert va["funding_status"] == "PARTIALLY_DEPLETED", (
            f"balance one cent below 50% must be PARTIALLY_DEPLETED, got "
            f"{va['funding_status']}"
        )

    def test_esa_voucher_disbursement_boundary_constants(self, api):
        """PRD 3.7: "The payment amount is subtracted from
        `disbursable_balance_cents`, and the funding status is reclassified
        against the full `awarded_annual_cents`: a remaining balance of at
        least half the annual award keeps the account `FUNDED` — the
        half-award boundary is inclusive; a positive balance below half
        moves it to `PARTIALLY_DEPLETED`; a balance of exactly zero marks it
        `DEPLETED`."

        Design: Corner/calculations/esa_voucher_disbursement_boundary_constants
        """
        set_clock("2026-08-01T00:00:00Z")
        pod, family, student, voucher, seat = _setup_verified_voucher_seat(api)
        inv = create_issued_invoice(
            pod["id"], seat["id"],
            line_items=[{"description": "Tuition", "quantity": 1,
                         "unit_amount_cents": HALF_AWARD, "kind": "TUITION"}],
        )
        p = get_success_data(api.create_payment(
            pod["id"], seat["id"], inv["id"],
            {"source_kind": "VOUCHER", "amount_cents": HALF_AWARD,
             "voucher_account_id": voucher["id"]},
            REGISTRAR,
        ))
        validate_success(api.clear_payment(p["id"], OPERATOR))
        va = get_success_data(api.get_voucher_account(voucher["id"], OFFICER))
        assert va["disbursable_balance_cents"] == HALF_AWARD
        assert va["funding_status"] == "FUNDED"


class TestInsufficientVoucherFunds:
    def test_insufficient_voucher_funds_rejected(self, api):
        """PRD 3.7: "A disbursement that would overdraw the balance is
        rejected outright with `ERR_INSUFFICIENT_VOUCHER_FUNDS`."

        Design: Corner/validations/insufficient_voucher_funds_rejected
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, family, student, voucher, seat = _setup_verified_voucher_seat(
            api, award=50000
        )
        inv = create_issued_invoice(pod["id"], seat["id"])
        # Balance is 50000; posting a 60000 voucher payment overdraws it.
        resp = api.create_payment(
            pod["id"], seat["id"], inv["id"],
            {"source_kind": "VOUCHER", "amount_cents": 60000,
             "voucher_account_id": voucher["id"]},
            REGISTRAR,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_VOUCHER_FUNDS,
                       expected_status=422)


class TestOverpayment:
    def test_overpayment_rejected(self, api):
        """PRD 3.7: "Two fiscal guards apply both when the payment is posted
        and when it is later cleared, evaluated in this order: first the
        voucher-funds check — a voucher-funded payment requires its account
        to be `VERIFIED`, the `disbursable_balance_cents` to cover the full
        `amount_cents`, and the funding status to be anything but `FROZEN`,
        with any failure rejected as `ERR_INSUFFICIENT_VOUCHER_FUNDS`
        (HTTP 422) — and then the overpayment ceiling: for family- and
        scholarship-funded payments, cumulative cleared payments against the
        invoice may not exceed its `total_cents`, violations rejected as
        `ERR_OVERPAYMENT` (HTTP 422)."

        Design: Corner/validations/overpayment_rejected
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, *_ = setup_pod_active()
        family, student, seat = setup_enrolled_seat(pod)
        inv = create_issued_invoice(pod["id"], seat["id"])
        total = inv["total_cents"]
        # Clear 80000 (partial), then attempt to clear a second payment that
        # would push paid_cents past total_cents.
        post_and_clear_payment(pod["id"], seat["id"], inv["id"],
                               amount_cents=80000)
        over_amount = total - 80000 + 1
        p2 = get_success_data(api.create_payment(
            pod["id"], seat["id"], inv["id"],
            {"source_kind": "FAMILY", "amount_cents": over_amount},
            REGISTRAR,
        ))
        resp = api.clear_payment(p2["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT, expected_status=422)


class TestVoucherStudentMismatch:
    def test_voucher_student_mismatch_rejected(self, api):
        """PRD 3.5: "If `esa_account_id` is supplied — at registration or in
        a later student update — it must reference a voucher account owned
        by that same student; a cross-student reference is rejected with
        `ERR_VOUCHER_STUDENT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/voucher_student_mismatch_rejected
        """
        family = create_family(family_name="VM")
        stu_a = create_student(family["id"], legal_first_name="A")
        voucher = create_voucher_account(stu_a["id"], awarded_annual_cents=500000)
        resp = api.create_student(
            family["id"],
            {"legal_first_name": "B", "legal_last_name": "Learner",
             "date_of_birth": "2017-01-01", "esa_account_id": voucher["id"]},
            REGISTRAR,
        )
        validate_error(resp, ApiErrorId.ERR_VOUCHER_STUDENT_MISMATCH,
                       expected_status=422)


class TestVoucherParallelDimensions:
    def test_verify_changes_verification_only_not_funding(self, api):
        """PRD 3.5: "The account lives on two independent state dimensions.
        Its `verification_status` begins at `PENDING_VERIFICATION` and is
        settled by a `ComplianceOfficer`: verification requires the
        student's `date_of_birth` to yield an eligible grade band for the
        program's jurisdiction and moves the account to `VERIFIED`,
        recomputing `accepted_by_pod`; rejection moves it to `REJECTED`. Its
        `funding_status` begins at `FUNDED` and tracks the
        `disbursable_balance_cents` that remains available for
        disbursement, as detailed in §3.7."

        Design: Difficulty/non_linear_state_machine/voucher_account_parallel_dimensions
        """
        set_clock("2026-06-01T00:00:00Z")
        family = create_family(family_name="VouchFam")
        student = create_student(family["id"], legal_first_name="Vic",
                                 date_of_birth="2016-05-01")
        voucher = create_voucher_account(student["id"], awarded_annual_cents=600000)
        assert voucher["verification_status"] == "PENDING_VERIFICATION"
        assert voucher["funding_status"] == "FUNDED"

        verified = get_success_data(api.verify_voucher_account(voucher["id"], OFFICER))
        assert verified["verification_status"] == "VERIFIED"
        assert verified["funding_status"] == "FUNDED", (
            "verification must not perturb the funding dimension, got "
            f"{verified['funding_status']}"
        )

    def test_dissolution_freezes_funding_while_verified(self, api):
        """PRD 3.9: "Entering `DISSOLVING` records the `dissolution_reason`,
        sets the pod's `posture` to `CLOSED`, and fires a five-fold cascade
        in a single request: every `ENROLLED` seat moves to `WITHDRAWN` with
        `withdrawn_on` set to the current date; every guide assignment in
        `SCHEDULED` or `ACTIVE` moves to `TERMINATED_EARLY`; every
        `APPROVED` curriculum plan moves to `SUPERSEDED` — carrying the
        conference cancellations of §3.8 with it; a refund claim of kind
        `DISSOLUTION` is created for each withdrawn seat; and every voucher
        account linked to a withdrawn student is frozen to `FROZEN`, held
        pending refund reconciliation."

        Design: Difficulty/non_linear_state_machine/voucher_account_parallel_dimensions
        """
        set_clock("2026-09-01T00:00:00Z")
        pod, family, student, voucher, seat = _setup_verified_voucher_seat(api)
        assert voucher["verification_status"] == "VERIFIED"

        pod_v = get_success_data(api.get_pod(pod["id"], OPERATOR))["version"]
        dissolved_pod = get_success_data(api.dissolve_pod(
            pod["id"],
            {"expected_pod_version": pod_v,
             "dissolution_reason": "operator withdrawal"},
            OPERATOR,
        ))
        assert dissolved_pod["status"] == "DISSOLVING"

        va = get_success_data(api.get_voucher_account(voucher["id"], OFFICER))
        assert va["funding_status"] == "FROZEN", (
            f"dissolution cascade must freeze funding, got {va['funding_status']}"
        )
        assert va["verification_status"] == "VERIFIED", (
            "the verification dimension is orthogonal and must remain "
            f"VERIFIED, got {va['verification_status']}"
        )


class TestClearReverseBalanceInvariant:
    def test_clear_then_reverse_restores_voucher_balance(self, api):
        """PRD 3.7: "And a `PlatformAdmin` may reverse a `CLEARED` payment
        when the linked seat is `WITHDRAWN` or a refund claim in `APPROVED`
        or `PAID` exists for it; reversal moves the payment to `REVERSED`,
        decrements the invoice's and seat's `paid_cents`, and — for
        voucher-sourced payments — restores the amount to the account's
        `disbursable_balance_cents`."

        Design: Difficulty/compensating_invariant/voucher_payment_clear_reverse_balance_invariant
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, family, student, voucher, seat = _setup_verified_voucher_seat(api)
        balance_before = get_success_data(
            api.get_voucher_account(voucher["id"], OFFICER)
        )["disbursable_balance_cents"]

        inv = create_issued_invoice(
            pod["id"], seat["id"],
            line_items=[{"description": "Tuition", "quantity": 1,
                         "unit_amount_cents": 100000, "kind": "TUITION"}],
        )
        pay = get_success_data(api.create_payment(
            pod["id"], seat["id"], inv["id"],
            {"source_kind": "VOUCHER", "amount_cents": 100000,
             "voucher_account_id": voucher["id"]},
            REGISTRAR,
        ))
        validate_success(api.clear_payment(pay["id"], OPERATOR))
        # Withdrawal makes the payment reversible (linked seat WITHDRAWN).
        from test_helpers.fixtures import withdraw_seat
        from test_helpers import make_family_headers
        withdraw_seat(pod["id"], seat["id"], family["id"], "2026-08-20")
        reversed_pay = validate_success(api.reverse_payment(pay["id"], ADMIN))
        assert reversed_pay["payment_status"] == "REVERSED"

        balance_after = get_success_data(
            api.get_voucher_account(voucher["id"], OFFICER)
        )["disbursable_balance_cents"]
        assert balance_after == balance_before, (
            f"clear+reverse must be compensating: before={balance_before}, "
            f"after={balance_after}"
        )

    def test_reverse_decrements_invoice_and_seat_paid_cents(self, api):
        """PRD 3.7: "And a `PlatformAdmin` may reverse a `CLEARED` payment
        when the linked seat is `WITHDRAWN` or a refund claim in `APPROVED`
        or `PAID` exists for it; reversal moves the payment to `REVERSED`,
        decrements the invoice's and seat's `paid_cents`, and — for
        voucher-sourced payments — restores the amount to the account's
        `disbursable_balance_cents`."

        Design: Difficulty/compensating_invariant/voucher_payment_clear_reverse_balance_invariant
        """
        from test_helpers.fixtures import withdraw_seat

        set_clock("2026-08-15T00:00:00Z")
        pod, family, student, voucher, seat = _setup_verified_voucher_seat(api)
        inv = create_issued_invoice(
            pod["id"], seat["id"],
            line_items=[{"description": "Tuition", "quantity": 1,
                         "unit_amount_cents": 100000, "kind": "TUITION"}],
        )
        pay = get_success_data(api.create_payment(
            pod["id"], seat["id"], inv["id"],
            {"source_kind": "VOUCHER", "amount_cents": 100000,
             "voucher_account_id": voucher["id"]},
            REGISTRAR,
        ))
        validate_success(api.clear_payment(pay["id"], OPERATOR))
        inv_mid = get_success_data(api.get_invoice(inv["id"], OPERATOR))
        seat_mid = get_success_data(api.get_seat(seat["id"], REGISTRAR))
        assert inv_mid["paid_cents"] == 100000
        assert seat_mid["paid_cents"] == 100000

        withdraw_seat(pod["id"], seat["id"], family["id"], "2026-08-20")
        validate_success(api.reverse_payment(pay["id"], ADMIN))
        inv_after = get_success_data(api.get_invoice(inv["id"], OPERATOR))
        seat_after = get_success_data(api.get_seat(seat["id"], REGISTRAR))
        assert inv_after["paid_cents"] == 0, (
            f"reversal must decrement invoice paid_cents to 0, got "
            f"{inv_after['paid_cents']}"
        )
        assert seat_after["paid_cents"] == 0, (
            f"reversal must decrement seat paid_cents to 0, got "
            f"{seat_after['paid_cents']}"
        )
