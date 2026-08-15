"""Transitive cascades: calculate -> obligation -> chargeback -> balance ->
notification, and offer accept -> disbursement -> credit -> balance ->
closure."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_aid_disbursement,
    assert_post_withdrawal_offer,
    assert_return_obligation,
    assert_student_account_entry,
    create_award,
    create_enrollment,
    create_student,
    create_term_t1,
    get_enrollment,
    list_account_entries,
    schedule_disbursement,
    disburse,
    set_clock,
    setup_full_aid_case,
    setup_pwd_case,
    setup_t2_split_case,
    setup_term_student_enrollment,
    validate_success,
    withdraw_official,
)
from test_helpers.test_users import make_student_headers

OFFICER = TEST_USERS["financial_aid_officer_headers"]
BURSAR = TEST_USERS["bursar_clerk_headers"]
REGISTRAR = TEST_USERS["registrar_clerk_headers"]


class TestCalculateCascade:

    def test_obligation_chargeback_balance_notification_chain(self):
        """PRD section 3.5: "a school-party obligation is created when
        `school_return_cents` is greater than zero"
        PRD section 3.5: "Every school-party obligation also posts an
        `R2T4_CHARGEBACK` ledger entry for its amount, positive, with
        `source_ref` set to the obligation's id, charging the school's return
        back to the student's account."
        PRD section 2.6: "Any posting of a new entry triggers an immediate
        recomputation of `balance_cents`. Whenever a recomputation happens
        while a linked withdrawal case is `CALCULATED` and the resulting
        balance is greater than zero, the enrollment's
        `balance_notification_sent` flag is set to true and
        `balance_notified_at` is stamped with the current logical time"

        Design: Difficulty/transitive_cascade/calculate_cascade_obligation_chargeback_balance_notification
        """
        scen = setup_full_aid_case(charges=600_000, pell_amount=200_000,
                                   loan_amount=300_000,
                                   withdraw_date="2026-10-25")
        case = scen["case"]
        # 0.600 -> earned 300000, return 200000, school min(240000, 200000).
        assert case["aid_earned_cents"] == 300_000
        assert case["return_amount_cents"] == 200_000
        assert case["school_return_cents"] == 200_000

        obligations = scen["obligations"]
        assert len(obligations) == 1
        ob = obligations[0]
        assert_return_obligation(ob)
        assert ob["party"] == "SCHOOL"
        assert ob["amount_cents"] == 200_000
        assert ob["status"] == "PENDING"
        assert ob["due_date"] == "2026-12-09"  # 2026-10-25 + 45d

        # Link 2: the obligation's chargeback entry, attributed by source_ref.
        chargebacks = list_account_entries(
            enrollment_id=scen["enrollment"]["id"], entry_type="R2T4_CHARGEBACK")
        assert len(chargebacks) == 1
        assert_student_account_entry(chargebacks[0])
        assert chargebacks[0]["amount_cents"] == 200_000
        assert chargebacks[0]["source_ref"] == ob["id"]

        # Link 3/4: 600000 charges - 500000 aid + 200000 chargeback; the
        # day-63 tiered refund is 0 (63 exceeds every tier's through_day).
        enr = get_enrollment(scen["enrollment"]["id"])
        assert enr["balance_cents"] == 300_000
        assert enr["balance_notification_sent"] is True
        assert enr["balance_notified_at"] is not None

    def test_chargeback_only_for_school_party_and_no_notification_when_nonpositive(self):
        """PRD section 3.5: "Every school-party obligation also posts an
        `R2T4_CHARGEBACK` ledger entry for its amount, positive, with
        `source_ref` set to the obligation's id"
        PRD section 2.6: "Whenever a recomputation happens while a linked
        withdrawal case is `CALCULATED` and the resulting balance is greater
        than zero, the enrollment's `balance_notification_sent` flag is set
        to true"

        Design: Difficulty/transitive_cascade/calculate_cascade_obligation_chargeback_balance_notification
        """
        scen = setup_t2_split_case(charges=80_000,
                                   clock="2026-11-15T00:00:00Z")
        case = scen["case"]
        # school 40000, student 50000 -> two obligations, one chargeback.
        assert case["school_return_cents"] == 40_000
        assert case["student_grant_return_cents"] == 50_000
        assert len(scen["obligations"]) == 2
        school_ob = scen["obligations"][0]
        assert school_ob["party"] == "SCHOOL"

        chargebacks = list_account_entries(
            enrollment_id=scen["enrollment"]["id"], entry_type="R2T4_CHARGEBACK")
        assert len(chargebacks) == 1
        assert chargebacks[0]["amount_cents"] == 40_000
        assert chargebacks[0]["source_ref"] == school_ob["id"]

        # 80000 - 500000 aid + 40000 chargeback = -380000: not positive, so
        # the balance notification is NOT emitted.
        enr = get_enrollment(scen["enrollment"]["id"])
        assert enr["balance_cents"] == -380_000
        assert enr["balance_notification_sent"] is False


class TestOfferAcceptCascade:

    def test_accept_creates_disbursement_posts_credit_and_closes_case(self):
        """PRD section 3.6: "Acceptance stamps `responded_at`, moves the
        offer to `ACCEPTED`, and immediately disburses the funds: a new
        disbursement is created already `DISBURSED` for the offer's
        `amount_cents`, tied to the offer's `award_id`, carrying the offer's
        id in its `pwd_offer_id`, and stamped with the current logical date;
        that disbursement posts its `AID_CREDIT` ledger entry and increases
        the award's `disbursed_amount_cents`. The enrollment's balance is
        then recomputed with notification evaluation, and the case's
        automatic closure evaluation runs."

        Design: Difficulty/transitive_cascade/offer_accept_cascade_disbursement_credit_balance
        """
        scen = setup_pwd_case(charges=500_000, clock="2026-10-26T09:00:00Z")
        case = scen["case"]
        # 0.600: earned 300000 > disbursed 200000 -> PWD path.
        assert case["aid_earned_cents"] == 300_000
        assert case["aid_disbursed_cents"] == 200_000
        assert case["pwd_grant_cents"] == 20_000
        assert case["pwd_loan_cents"] == 80_000
        assert case["return_amount_cents"] == 0
        offers = scen["offers"]
        assert len(offers) == 1
        offer = offers[0]
        assert_post_withdrawal_offer(offer)
        assert offer["amount_cents"] == 80_000
        assert offer["status"] == "SENT"

        # Link 1: the student accepts their own offer.
        accepted = validate_success(api_client.accept_offer(
            offer["id"], make_student_headers(scen["student"]["id"])), 200)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["responded_at"] is not None

        # Link 2: a DISBURSED disbursement tied to the offer now exists.
        pwd_disbursements = validate_success(api_client.list_disbursements(
            OFFICER, params={"pwd_offer_id": offer["id"]}), 200)
        assert len(pwd_disbursements) == 1
        assert_aid_disbursement(pwd_disbursements[0])
        assert pwd_disbursements[0]["amount_cents"] == 80_000
        assert pwd_disbursements[0]["status"] == "DISBURSED"
        assert pwd_disbursements[0]["award_id"] == scen["loan"]["id"]

        # Link 3: the award's disbursed total absorbed the PWD amount.
        loan = validate_success(api_client.get_award(scen["loan"]["id"],
                                                     OFFICER), 200)
        assert loan["disbursed_amount_cents"] == 180_000

        # Link 4: 500000 - 200000 aid - 20000 grant PWD - 80000 loan PWD.
        enr = get_enrollment(scen["enrollment"]["id"])
        assert enr["balance_cents"] == 200_000

        # Link 5: offers terminal, no obligations, notification sent -> CLOSED.
        closed = validate_success(api_client.get_withdrawal_case(case["id"],
                                                                 OFFICER), 200)
        assert closed["status"] == "CLOSED"
        assert enr["current_withdrawal_case_id"] is None

    def test_decline_posts_no_disbursement_and_closes_case(self):
        """PRD section 3.6: "Declining simply stamps `responded_at`, moves
        the offer to `DECLINED`, and runs the same closure evaluation."

        Design: Difficulty/transitive_cascade/offer_accept_cascade_disbursement_credit_balance
        """
        scen = setup_pwd_case(charges=500_000, clock="2026-10-26T09:00:00Z")
        offer = scen["offers"][0]
        declined = validate_success(api_client.decline_offer(
            offer["id"], make_student_headers(scen["student"]["id"])), 200)
        assert declined["status"] == "DECLINED"
        assert declined["responded_at"] is not None

        pwd_disbursements = validate_success(api_client.list_disbursements(
            OFFICER, params={"pwd_offer_id": offer["id"]}), 200)
        assert pwd_disbursements == []

        loan = validate_success(api_client.get_award(scen["loan"]["id"],
                                                     OFFICER), 200)
        assert loan["disbursed_amount_cents"] == 100_000

        # 500000 - 200000 aid - 20000 grant PWD = 280000.
        enr = get_enrollment(scen["enrollment"]["id"])
        assert enr["balance_cents"] == 280_000
        closed = validate_success(api_client.get_withdrawal_case(
            scen["case"]["id"], OFFICER), 200)
        assert closed["status"] == "CLOSED"


class TestPaymentAndCompletion:

    def test_student_payment_reduces_balance(self):
        """PRD section 3.2: "a `BursarClerk`, or the student themselves
        acting on their own enrollment, submits an `amount_cents`, and the
        server posts a `PAYMENT` entry for the negated amount and recomputes
        the balance."
        PRD section 2.6: "`REFUND_CREDIT`, `AID_CREDIT`, and `PAYMENT`
        entries are negative"

        Design: Corner/calculations/student_payment_reduces_balance
        """
        _, _, enrollment = setup_term_student_enrollment(charges=600_000)
        payment = validate_success(api_client.record_payment(
            enrollment["id"], {"amount_cents": 50_000}, BURSAR), 201)
        assert_student_account_entry(payment)
        assert payment["entry_type"] == "PAYMENT"
        assert payment["amount_cents"] == -50_000
        enr = get_enrollment(enrollment["id"])
        assert enr["balance_cents"] == 550_000

    def test_complete_cancels_scheduled_disbursements(self):
        """PRD section 3.2: "Completion cancels every disbursement still
        `SCHEDULED` across the enrollment's awards, increments the
        enrollment's `version`, and lands the enrollment in `COMPLETED`, its
        terminal state."

        Design: Corner/state_machines/complete_cancels_scheduled_disbursements
        """
        term, student, enrollment = setup_term_student_enrollment(
            charges=600_000, with_break=False)
        pell = create_award(enrollment["id"], "PELL_GRANT", 200_000)
        d_disbursed = schedule_disbursement(pell["id"], 100_000)
        disburse(d_disbursed["id"])
        d_scheduled = schedule_disbursement(pell["id"], 100_000)
        # Clock strictly past the term's end_date.
        set_clock("2026-12-12T00:00:00Z")
        completed = validate_success(api_client.complete_enrollment(
            enrollment["id"], REGISTRAR), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["version"] == enrollment["version"] + 1

        d_after_scheduled = validate_success(api_client.get_disbursement(
            d_scheduled["id"], REGISTRAR), 200)
        assert d_after_scheduled["status"] == "CANCELLED"
        d_after_disbursed = validate_success(api_client.get_disbursement(
            d_disbursed["id"], REGISTRAR), 200)
        assert d_after_disbursed["status"] == "DISBURSED"
