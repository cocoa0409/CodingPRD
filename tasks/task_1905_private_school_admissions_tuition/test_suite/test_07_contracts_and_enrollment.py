"""Contracts, deposits, enrollment, and summer melt (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_seat_ledger,
    get_aid,
    get_application,
    get_contract,
    get_cycle,
    get_section,
    get_student,
    issue_contract,
    make_parent_headers,
    parse_instant,
    run_sweep,
    set_clock,
    setup_enrolled_world,
    setup_issued_contract_world,
    setup_offered_application,
    setup_signed_contract_world,
    sign_contract,
    validate_error,
    validate_success,
)


class TestDepositDualVariant:
    """Difficulty: the offer letter's estimated deposit runs on the
    provisional award while the issued contract's deposit runs on the
    accepted final award; identical tuition, divergent variants."""

    def test_offer_letter_estimate_uses_provisional_award(
            self, api, director_headers):
        """PRD §3.5: "an `estimated_deposit_cents` for the offer letter
        computed on the estimated deposit variant: the larger of 50,000 cents
        and ten percent of net tuition rounded half-up to a whole cent, where
        net tuition is the section's `tuition_cents` minus the linked aid
        application's `provisional_award_cents` — or minus zero when no aid
        application exists."

        Design: Difficulty/dual_variant_calc/deposit_estimate_vs_contract_final_diverge
        """
        ctx = setup_offered_application(
            "fam-a", aid=(9_500_000, 4, 12_000_000),
        )
        application = get_application(ctx["application"]["id"])
        assert application["status"] == "OFFERED"
        # Provisional award 2,370,000 -> net 630,000 -> 10% = 63,000.
        assert application["estimated_deposit_cents"] == 63_000

    def test_contract_deposit_uses_accepted_final_award(self, api,
                                                        director_headers):
        """PRD §3.6: "The contract snapshots `tuition_cents` from the grade
        section at issuance and `award_cents` from the accepted final award —
        zero when the family has no aid — computes `net_tuition_cents` as
        tuition minus award, and sets `deposit_amount_cents` on the final
        deposit variant: the larger of 50,000 cents and ten percent of
        `net_tuition_cents` rounded half-up to a whole cent."
        PRD §3.6: "its `response_due_at` is set fourteen days out from the
        issuance clock".

        Design: Difficulty/dual_variant_calc/deposit_estimate_vs_contract_final_diverge
        """
        ctx = setup_offered_application(
            "fam-a", aid=(9_500_000, 4, 12_000_000), accept_aid_award=True,
        )
        contract = issue_contract(ctx["application"]["id"])
        # Accepted final 1,820,000 -> net 1,180,000 -> 10% = 118,000.
        assert contract["tuition_cents"] == 3_000_000
        assert contract["award_cents"] == 1_820_000
        assert contract["net_tuition_cents"] == 1_180_000
        assert contract["deposit_amount_cents"] == 118_000
        # Issued at the 2026-11-02 close clock + 14 days.
        assert parse_instant(contract["response_due_at"]) == parse_instant(
            "2026-11-16T00:00:00Z"
        )
        # The two variants diverge because verified income diverged from
        # reported income.
        application = get_application(ctx["application"]["id"])
        assert application["estimated_deposit_cents"] == 63_000
        assert contract["deposit_amount_cents"] != \
            application["estimated_deposit_cents"]


class TestContractIssuanceGate:
    """Difficulty: issue-contract's validity depends on the linked aid
    application's award_status — an unaccepted award blocks, acceptance
    unblocks."""

    def test_issue_contract_blocked_until_award_accepted(self, api,
                                                         officer_headers):
        """PRD §3.6: "If an aid application is linked to this application, its
        `award_status` must be `ACCEPTED`; issuing against an unfinalized,
        offered-but-unaccepted, or appealed award is `ERR_AID_NOT_FINALIZED`."

        Design: Difficulty/cross_entity_state_dependency/contract_blocked_until_award_accepted
        """
        ctx = setup_offered_application(
            "fam-a", aid=(12_000_000, 4, 12_000_000), accept_aid_award=False,
        )
        assert get_aid(ctx["aid"]["id"])["award_status"] == "OFFERED"
        resp = api.issue_contract(ctx["application"]["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_AID_NOT_FINALIZED, 409)
        assert (get_application(ctx["application"]["id"])["status"]
                == "OFFERED")

    def test_issue_contract_unblocked_after_award_accepted(self, api,
                                                           officer_headers):
        """PRD §3.6: "If an aid application is linked to this application, its
        `award_status` must be `ACCEPTED`".
        PRD §3.6: "Issuance creates the `EnrollmentContract` and moves the
        application `OFFERED` → `CONTRACT_ISSUED`."

        Design: Difficulty/cross_entity_state_dependency/contract_blocked_until_award_accepted
        """
        ctx = setup_offered_application(
            "fam-a", aid=(12_000_000, 4, 12_000_000), accept_aid_award=True,
        )
        resp = api.issue_contract(ctx["application"]["id"], officer_headers)
        contract = validate_success(resp, 201)
        assert contract["status"] == "ISSUED"
        assert contract["award_cents"] == 1_820_000
        assert contract["deposit_amount_cents"] == 118_000
        assert (get_application(ctx["application"]["id"])["status"]
                == "CONTRACT_ISSUED")

    def test_issue_contract_after_offer_expiry_belt_rejected(
            self, api, officer_headers):
        """PRD §3.6: "Issuance requires the application to be `OFFERED`
        (`ERR_APPLICATION_NOT_OFFERED` otherwise) and the logical clock to be
        at or before `offer_expires_at` — a belt check that catches stale
        offers as `ERR_OFFER_EXPIRED` even before the next sweep would expire
        them."

        Design: Corner/validations/issue_contract_after_offer_expiry_belt_rejected
        """
        ctx = setup_offered_application("fam-a")  # offer expires 2026-11-23
        set_clock("2026-11-24T00:00:00Z")  # past expiry; NO sweep has run
        resp = api.issue_contract(ctx["application"]["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED, 422)
        # The belt check fired even though the state precondition still holds.
        assert get_application(ctx["application"]["id"])["status"] == "OFFERED"


class TestContractLifecycle:
    def test_sign_lapsed_contract_rejected(self, api, director_headers):
        """PRD §3.6: "The family signs an `ISSUED` contract — signing from any
        other state is `ERR_CONTRACT_NOT_ISSUED` — moving it to `SIGNED`."

        Design: Corner/state_machines/sign_lapsed_contract_rejected
        """
        ctx = setup_issued_contract_world()  # due 2026-11-16, unsigned
        set_clock("2026-11-17T00:00:00Z")
        run_sweep(ctx["cycle"]["id"])
        assert get_contract(ctx["contract"]["id"])["status"] == "LAPSED"
        resp = api.sign_contract(ctx["contract"]["id"],
                                 make_parent_headers("fam-a"))
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ISSUED, 409)
        assert get_contract(ctx["contract"]["id"])["status"] == "LAPSED"

    def test_pay_unsigned_contract_rejected(self, api):
        """PRD §3.6: "Deposit payments then arrive against the `SIGNED`
        contract; paying against a contract in any other state is
        `ERR_CONTRACT_NOT_SIGNED`."

        Design: Corner/validations/pay_unsigned_contract_rejected
        """
        ctx = setup_issued_contract_world()  # ISSUED, never signed
        resp = api.pay_deposit(ctx["contract"]["id"], 300_000,
                               make_parent_headers("fam-a"))
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_SIGNED, 409)
        assert get_contract(ctx["contract"]["id"])["paid_cents"] == 0

    def test_payment_exceeds_balance_rejected_then_exact_enrolls(
            self, api, director_headers):
        """PRD §3.6: "Each payment carries an `amount_cents` and must not
        exceed the remaining deposit balance — `deposit_amount_cents` minus
        the `paid_cents` collected so far — or it is rejected with
        `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422); accepted payments add to
        `paid_cents`."
        PRD §3.6: "The moment `paid_cents` reaches or exceeds
        `deposit_amount_cents`, enrollment fires automatically inside the
        payment request".

        Design: Corner/validations/payment_exceeds_balance_rejected_then_exact_enrolls
        """
        ctx = setup_signed_contract_world()  # no aid: deposit 300,000
        contract_id = ctx["contract"]["id"]
        resp = api.pay_deposit(contract_id, 300_001,
                               make_parent_headers("fam-a"))
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE, 422)
        held = get_contract(contract_id)
        assert held["paid_cents"] == 0 and held["status"] == "SIGNED"
        data = validate_success(
            api.pay_deposit(contract_id, 300_000, make_parent_headers("fam-a"))
        )
        assert data["status"] == "ENROLLED"
        assert data["paid_cents"] == 300_000

    def test_deposit_floor_applies_when_net_tuition_tiny(self, api,
                                                         director_headers):
        """PRD §3.6: "sets `deposit_amount_cents` on the final deposit
        variant: the larger of 50,000 cents and ten percent of
        `net_tuition_cents` rounded half-up to a whole cent."

        Design: Corner/calculations/deposit_floor_applies_when_net_tuition_tiny
        """
        # Award capped at 2,700,000 against tuition 3,000,000 -> net 300,000;
        # raw 10% would be 30,000, below the floor.
        ctx = setup_issued_contract_world(
            "fam-a", aid=(5_500_000, 4, 5_500_000), accept_aid_award=True,
        )
        contract = ctx["contract"]
        assert contract["net_tuition_cents"] == 300_000
        assert contract["deposit_amount_cents"] == 50_000


class TestEnrollmentCascade:
    """Difficulty: the deposit payment that crosses the threshold flips the
    contract ENROLLED (hop 1) -> the application ENROLLED (hop 2) -> a Student
    row is created with source ADMISSION (hop 3)."""

    def test_final_payment_enrolls_and_creates_student(self, api,
                                                       director_headers):
        """PRD §3.6: "The moment `paid_cents` reaches or exceeds
        `deposit_amount_cents`, enrollment fires automatically inside the
        payment request: the contract moves `SIGNED` → `ENROLLED`, the
        application moves `CONTRACT_ISSUED` → `ENROLLED`, and a `Student` row
        is created with `source` `ADMISSION`, the `family_id` taken from the
        applicant, `current_grade_section_id` set to the application's
        `grade_section_id`, and `status` `ACTIVE` — stored on the contract's
        `created_student_id`."

        Design: Difficulty/transitive_cascade/deposit_payment_enrollment_cascade
        """
        ctx = setup_enrolled_world()  # no aid; one exact 300,000 payment
        contract = get_contract(ctx["contract"]["id"])
        assert contract["status"] == "ENROLLED"
        assert contract["paid_cents"] == 300_000
        assert get_application(ctx["application"]["id"])["status"] == "ENROLLED"
        student = get_student(ctx["student_id"])
        assert student["source"] == "ADMISSION"
        assert student["status"] == "ACTIVE"
        assert student["family_id"] == "fam-a"
        assert (student["current_grade_section_id"] == ctx["section"]["id"])
        assert contract["created_student_id"] == ctx["student_id"]

    def test_enrollment_keeps_the_seat_held(self, api, director_headers):
        """PRD §3.6: "Seats and budget stay put: the seat was already held,
        and the award was already committed at acceptance."
        PRD §2.9: "`seats_held` counts the section's applications in
        `OFFERED`, `CONTRACT_ISSUED`, or `ENROLLED`".

        Design: Difficulty/transitive_cascade/deposit_payment_enrollment_cascade
        """
        ctx = setup_enrolled_world()
        section = get_section(ctx["section"]["id"])
        # OFFERED held the seat; ENROLLED must not double-count it.
        assert section["seats_held"] == 1
        assert_seat_ledger(section)
        # The created student is queryable through the registry.
        student = get_student(ctx["student_id"])
        assert student["status"] == "ACTIVE"


class TestSummerMelt:
    def test_melt_enrolled_cascade_releases_everything(self, api,
                                                       director_headers):
        """PRD §3.6: "withdrawing an application that is `ENROLLED` moves it
        to `MELTED` rather than `WITHDRAWN`. The melt cascade moves the linked
        contract to `MELTED`; forfeits the deposit — the school retains
        `paid_cents` and writes no refund ledger entry; releases the linked
        award, which is always `ACCEPTED` at enrollment, subtracting
        `final_award_cents` from the cycle's `aid_committed_cents`;
        soft-deactivates the student row named by the contract's
        `created_student_id` to `INACTIVE`; and frees the seat".

        Design: Corner/complexity_layers/melt_enrolled_cascade_releases_everything
        """
        ctx = setup_enrolled_world(
            "fam-a", aid=(12_000_000, 4, 12_000_000), accept_aid_award=True,
        )
        assert get_cycle(ctx["cycle"]["id"])["aid_committed_cents"] == 1_820_000
        resp = api.withdraw_application(ctx["application"]["id"],
                                        make_parent_headers("fam-a"))
        data = validate_success(resp, 200)
        assert data["status"] == "MELTED"
        contract = get_contract(ctx["contract"]["id"])
        assert contract["status"] == "MELTED"
        # Deposit forfeited: the school retains the 118,000 paid.
        assert contract["paid_cents"] == 118_000
        assert get_aid(ctx["aid"]["id"])["award_status"] == "RELEASED"
        assert get_cycle(ctx["cycle"]["id"])["aid_committed_cents"] == 0
        assert get_student(ctx["student_id"])["status"] == "INACTIVE"
        section = get_section(ctx["section"]["id"])
        assert section["seats_held"] == 0
        assert section["aid_seats_held"] == 0
        assert_seat_ledger(section)
