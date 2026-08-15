"""Withdrawal-case correction loop, rescission compensation, automatic case
closure, and optimistic concurrency on recalculation."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_award,
    api_client,
    assert_enrollment,
    create_award,
    create_enrollment,
    create_student,
    create_term_t1,
    disburse,
    get_case,
    get_enrollment,
    list_account_entries,
    list_obligations,
    list_offers,
    schedule_disbursement,
    set_clock,
    setup_full_aid_case,
    setup_pell_only_case,
    setup_t2_split_case,
    setup_term_student_enrollment,
    validate_error,
    validate_success,
    withdraw_official,
)
from test_helpers.fixtures import OFFICER_1_ID, OFFICER_2_ID
from test_helpers.test_users import (
    make_financial_aid_officer_headers,
    make_student_headers,
)

REGISTRAR = TEST_USERS["registrar_clerk_headers"]
OFFICER = TEST_USERS["financial_aid_officer_headers"]
BURSAR = TEST_USERS["bursar_clerk_headers"]


def approx3(value):
    return pytest.approx(value, abs=1e-9)


class TestRecalculateLoopThenAutoClose:

    def test_loop_to_full_earning_voids_obligation_and_closes(self):
        """PRD section 3.7: "From the corrected inputs the server recomputes
        the `withdrawal_date`, `completed_days`, `percentage_completed`, and
        `earned_pct`. It then compensates the old calculation before applying
        the new one: every obligation still `PENDING` or `OVERDUE` is voided,
        every offer still `SENT` is voided, and `REVERSAL` ledger entries are
        posted negating each of the case's `REFUND_CREDIT` and
        `R2T4_CHARGEBACK` entries."
        PRD section 3.7: "When all three hold, the case transitions from
        `CALCULATED` to `CLOSED`, clearing the enrollment's
        `current_withdrawal_case_id` and incrementing the case's `version`."

        Design: Difficulty/non_linear_state_machine/withdrawal_case_recalculate_loop_then_autoclose
        """
        scen = setup_full_aid_case(charges=600_000, pell_amount=200_000,
                                   loan_amount=300_000,
                                   withdraw_date="2026-10-25",
                                   officer_id=OFFICER_1_ID)
        case = scen["case"]
        version_at_calc = case["version"]
        old_obligation = scen["obligations"][0]
        assert old_obligation["amount_cents"] == 200_000

        # Correct the notification date to day 64 -> 0.610 -> earned_pct 1.000.
        recalc = validate_success(api_client.recalculate_case(
            case["id"],
            {"expected_withdrawal_case_version": version_at_calc,
             "notification_date": "2026-10-26"},
            make_financial_aid_officer_headers(OFFICER_2_ID)), 200)
        assert recalc["percentage_completed"] == approx3(0.610)
        assert recalc["earned_pct"] == approx3(1.000)
        assert recalc["aid_earned_cents"] == 500_000
        # Two PRD-named increments land in this request: the recalculation
        # itself (section 3.5: "the case's `version` increments by one") and
        # the automatic closure transition (section 3.7: "incrementing the
        # case's `version`").
        assert recalc["version"] == version_at_calc + 2
        assert recalc["calculated_by_user_id"] == OFFICER_2_ID

        # The old obligation was voided by the loop, not returned.
        obligations = list_obligations(case["id"])
        by_id = {o["id"]: o for o in obligations}
        assert by_id[old_obligation["id"]]["status"] == "VOIDED"
        # 100% earned -> nothing owed -> no replacement obligations.
        assert [o for o in obligations if o["status"] == "PENDING"] == []

        # No obligations, no offers, notification sent -> CLOSED.
        assert recalc["status"] == "CLOSED"
        enr = get_enrollment(scen["enrollment"]["id"])
        # Chargeback 200000 reversed: 600000 charges - 500000 aid.
        assert enr["balance_cents"] == 100_000
        assert enr["current_withdrawal_case_id"] is None

    def test_replayed_stale_version_after_successful_recalculate_rejected(self):
        """PRD section 2.8: "If that value does not match the case's current
        `version` — because another writer has advanced the case since the
        client last read it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from
        overwriting a calculation it has not observed."

        Design: Difficulty/non_linear_state_machine/withdrawal_case_recalculate_loop_then_autoclose
        """
        scen = setup_full_aid_case(charges=600_000, pell_amount=200_000,
                                   loan_amount=300_000,
                                   withdraw_date="2026-10-25",
                                   officer_id=OFFICER_1_ID)
        case = scen["case"]
        version_at_calc = case["version"]
        # First loop iteration with identical inputs keeps the case
        # CALCULATED (the obligation is regenerated) and advances version.
        recalc = validate_success(api_client.recalculate_case(
            case["id"],
            {"expected_withdrawal_case_version": version_at_calc,
             "notification_date": "2026-10-25"},
            make_financial_aid_officer_headers(OFFICER_1_ID)), 200)
        assert recalc["status"] == "CALCULATED"
        assert recalc["version"] == version_at_calc + 1
        # Replaying the now-stale version is rejected.
        resp = api_client.recalculate_case(
            case["id"],
            {"expected_withdrawal_case_version": version_at_calc,
             "notification_date": "2026-10-25"},
            make_financial_aid_officer_headers(OFFICER_1_ID))
        validate_error(resp, "ERR_STALE_VERSION", expected_status=412)


class TestAidConservationAcrossRecalculation:

    def test_identical_inputs_reproduce_identical_amounts(self):
        """PRD section 3.7: "Because the pipeline is deterministic,
        recalculating with identical inputs reproduces identical amounts: the
        aid conservation invariant holds across the loop."
        PRD section 3.5: "`aid_unearned_cents` is `aid_disbursable_cents`
        minus `aid_earned_cents`."

        Design: Difficulty/compensating_invariant/aid_conservation_across_recalculation_loop
        """
        scen = setup_full_aid_case(charges=600_000, pell_amount=200_000,
                                   loan_amount=300_000,
                                   withdraw_date="2026-10-25")
        case = scen["case"]
        assert case["aid_earned_cents"] == 300_000
        assert case["aid_unearned_cents"] == 200_000
        assert case["aid_disbursable_cents"] == 500_000
        assert (case["aid_earned_cents"] + case["aid_unearned_cents"]
                == case["aid_disbursable_cents"])

        recalc = validate_success(api_client.recalculate_case(
            case["id"],
            {"expected_withdrawal_case_version": case["version"],
             "notification_date": "2026-10-25"},
            make_financial_aid_officer_headers(OFFICER_1_ID)), 200)
        assert recalc["aid_earned_cents"] == 300_000
        assert recalc["aid_unearned_cents"] == 200_000
        assert recalc["aid_disbursable_cents"] == 500_000

        # Compensation replaced the obligation exactly once: one VOIDED row
        # and one regenerated PENDING row, both for 200000.
        obligations = list_obligations(case["id"])
        voided = [o for o in obligations if o["status"] == "VOIDED"]
        pending = [o for o in obligations if o["status"] == "PENDING"]
        assert len(voided) == 1 and voided[0]["amount_cents"] == 200_000
        assert len(pending) == 1 and pending[0]["amount_cents"] == 200_000

    def test_reversal_entries_negate_chargeback_and_balance_unchanged(self):
        """PRD section 3.7: "It then compensates the old calculation before
        applying the new one: every obligation still `PENDING` or `OVERDUE`
        is voided, every offer still `SENT` is voided, and `REVERSAL` ledger
        entries are posted negating each of the case's `REFUND_CREDIT` and
        `R2T4_CHARGEBACK` entries."
        PRD section 2.6: "a `REVERSAL` entry carries the negation of the
        amount of the entry it reverses, recorded through its
        `reversal_of_entry_id` reference, which is set only on `REVERSAL`
        entries and is null on all others."

        Design: Difficulty/compensating_invariant/aid_conservation_across_recalculation_loop
        """
        scen = setup_full_aid_case(charges=600_000, pell_amount=200_000,
                                   loan_amount=300_000,
                                   withdraw_date="2026-10-25")
        case = scen["case"]
        enrollment_id = scen["enrollment"]["id"]
        chargebacks_before = list_account_entries(
            enrollment_id=enrollment_id, entry_type="R2T4_CHARGEBACK")
        assert len(chargebacks_before) == 1
        original_chargeback = chargebacks_before[0]
        assert original_chargeback["amount_cents"] == 200_000
        balance_before = get_enrollment(enrollment_id)["balance_cents"]
        assert balance_before == 300_000

        validate_success(api_client.recalculate_case(
            case["id"],
            {"expected_withdrawal_case_version": case["version"],
             "notification_date": "2026-10-25"},
            make_financial_aid_officer_headers(OFFICER_1_ID)), 200)

        reversals = list_account_entries(enrollment_id=enrollment_id,
                                         entry_type="REVERSAL")
        assert len(reversals) == 1
        assert reversals[0]["amount_cents"] == -200_000
        assert reversals[0]["reversal_of_entry_id"] == \
            original_chargeback["id"]

        # A fresh chargeback for the regenerated obligation replaced it.
        chargebacks_after = list_account_entries(
            enrollment_id=enrollment_id, entry_type="R2T4_CHARGEBACK")
        assert len(chargebacks_after) == 2
        new_obligation = [o for o in list_obligations(case["id"])
                          if o["status"] == "PENDING"][0]
        new_chargeback = [c for c in chargebacks_after
                          if c["id"] != original_chargeback["id"]][0]
        assert new_chargeback["amount_cents"] == 200_000
        assert new_chargeback["source_ref"] == new_obligation["id"]

        # The ledger nets to the same balance: no drift across the loop.
        assert get_enrollment(enrollment_id)["balance_cents"] == 300_000


class TestEnrollmentWithdrawRescindCycle:

    def test_withdraw_rescind_withdraw_again_cycle(self):
        """PRD section 3.7: "When the case was still `OPEN`, no financial
        artifacts existed and the enrollment simply reverts."
        PRD section 3.4: "An enrollment carries at most one withdrawal case
        in `OPEN`, `CALCULATED`, or `CLOSED`; a successor case may be opened
        only after the prior one has reached `CANCELLED`."

        Design: Difficulty/non_linear_state_machine/enrollment_withdraw_rescind_cycle
        """
        _, _, enrollment = setup_term_student_enrollment(charges=600_000)
        k1 = withdraw_official(enrollment["id"], "2026-09-02")
        assert k1["status"] == "OPEN"

        rescinded = validate_success(api_client.rescind_withdrawal(
            enrollment["id"], REGISTRAR), 200)
        assert rescinded["status"] == "ENROLLED"
        assert rescinded["current_withdrawal_case_id"] is None
        # No aid and no calculation ever ran: balance untouched.
        assert rescinded["balance_cents"] == 600_000

        k1_after = get_case(k1["id"])
        assert k1_after["status"] == "CANCELLED"

        # The cycle permits a brand-new successor case.
        k2 = withdraw_official(enrollment["id"], "2026-09-10")
        assert k2["status"] == "OPEN"
        assert k2["id"] != k1["id"]
        assert get_enrollment(enrollment["id"])["balance_cents"] == 600_000

    def test_rescind_on_enrolled_enrollment_rejected(self):
        """PRD section 3.7: "It requires the enrollment to be `WITHDRAWN` —
        any other status yields `ERR_ENROLLMENT_NOT_WITHDRAWN` — and the
        linked case to be `OPEN` or `CALCULATED`"

        Design: Difficulty/non_linear_state_machine/enrollment_withdraw_rescind_cycle
        """
        _, _, enrollment = setup_term_student_enrollment(charges=600_000)
        resp = api_client.rescind_withdrawal(enrollment["id"], REGISTRAR)
        validate_error(resp, "ERR_ENROLLMENT_NOT_WITHDRAWN",
                       expected_status=409)
        assert get_enrollment(enrollment["id"])["status"] == "ENROLLED"


class TestLedgerBalanceRoundTripOnRescind:

    def test_calculated_case_rescind_restores_balance(self):
        """PRD section 3.7: "When the case was `CALCULATED`, the rescission
        runs the full compensation cascade: the case moves to `CANCELLED`,
        every `PENDING` or `OVERDUE` obligation is voided, every `SENT` offer
        is voided, `REVERSAL` entries negate each of the case's
        `REFUND_CREDIT` and `R2T4_CHARGEBACK` entries, and the enrollment's
        balance is recomputed. In both variants the enrollment returns from
        `WITHDRAWN` to `ENROLLED`, its `balance_notification_sent` flag is
        reset to false and `balance_notified_at` cleared to null,
        `current_withdrawal_case_id` is cleared, and the enrollment's
        `version` increments."

        Design: Difficulty/compensating_invariant/ledger_balance_round_trip_on_rescind
        """
        scen = setup_full_aid_case(charges=600_000, pell_amount=200_000,
                                   loan_amount=300_000,
                                   withdraw_date="2026-09-02",  # day 10
                                   calculate=False)
        enrollment_id = scen["enrollment"]["id"]
        # Pre-withdrawal: 600000 CHARGE - 500000 AID_CREDIT = 100000.
        balance_pre = get_enrollment(enrollment_id)["balance_cents"]
        assert balance_pre == 100_000

        case = validate_success(api_client.calculate_case(
            scen["case"]["id"],
            make_financial_aid_officer_headers(OFFICER_1_ID)), 200)
        # Day 10 of 105 -> 0.095; earned 19000 + 28500 = 47500; return
        # 452500; school share min(round(600000*0.905)=543000, 452500).
        assert case["aid_earned_cents"] == 47_500
        assert case["return_amount_cents"] == 452_500
        assert case["school_return_cents"] == 452_500
        # Mid-calculation: TIERED day 10 <= 14 -> 0.75 refund (450000);
        # balance = 100000 - 450000 + 452500 = 102500.
        balance_mid = get_enrollment(enrollment_id)["balance_cents"]
        assert balance_mid == 102_500

        rescinded = validate_success(api_client.rescind_withdrawal(
            enrollment_id, REGISTRAR), 200)
        assert_enrollment(rescinded)
        assert rescinded["status"] == "ENROLLED"
        assert rescinded["balance_cents"] == 100_000
        assert rescinded["balance_notification_sent"] is False
        assert rescinded["balance_notified_at"] is None
        assert rescinded["current_withdrawal_case_id"] is None

        # Every financial artifact neutralized by a signed REVERSAL.
        reversals = list_account_entries(enrollment_id=enrollment_id,
                                         entry_type="REVERSAL")
        assert len(reversals) == 2
        by_amount = sorted(r["amount_cents"] for r in reversals)
        assert by_amount == [-452_500, 450_000]
        for r in reversals:
            assert r["reversal_of_entry_id"] is not None
        assert get_case(case["id"])["status"] == "CANCELLED"

    def test_open_case_rescind_posts_no_reversals(self):
        """PRD section 3.7: "When the case was still `OPEN`, no financial
        artifacts existed and the enrollment simply reverts."

        Design: Difficulty/compensating_invariant/ledger_balance_round_trip_on_rescind
        """
        scen = setup_full_aid_case(charges=600_000, pell_amount=200_000,
                                   loan_amount=300_000,
                                   withdraw_date="2026-09-02",
                                   calculate=False)
        enrollment_id = scen["enrollment"]["id"]
        assert get_enrollment(enrollment_id)["balance_cents"] == 100_000

        rescinded = validate_success(api_client.rescind_withdrawal(
            enrollment_id, REGISTRAR), 200)
        assert rescinded["status"] == "ENROLLED"
        assert rescinded["balance_cents"] == 100_000
        assert rescinded["balance_notification_sent"] is False
        reversals = list_account_entries(enrollment_id=enrollment_id,
                                         entry_type="REVERSAL")
        assert reversals == []
        assert get_case(scen["case"]["id"])["status"] == "CANCELLED"


class TestInvalidTransitionsAndLocks:

    def test_calculate_on_calculated_case_rejected(self):
        """PRD section 3.5: "The heart of the workflow is the calculation,
        performed by a `FinancialAidOfficer` against a case in `OPEN` status
        — invoking it on a case in any other status is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/calculate_on_calculated_case_rejected
        """
        scen = setup_pell_only_case()
        resp = api_client.calculate_case(
            scen["case"]["id"], make_financial_aid_officer_headers(OFFICER_1_ID))
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
        # No side effects fired a second time.
        assert len(list_obligations(scen["case"]["id"])) == 1

    def test_rescind_after_case_closed_rejected(self):
        """PRD section 3.7: "It requires the enrollment to be `WITHDRAWN` —
        any other status yields `ERR_ENROLLMENT_NOT_WITHDRAWN` — and the
        linked case to be `OPEN` or `CALCULATED`; a case that already reached
        `CLOSED` rejects the rescission with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/rescind_after_case_closed_rejected
        """
        # Day 64 -> 100% earned -> no obligations, no offers; balance
        # 400000 > 0 -> notification sent -> auto-close at calculate.
        scen = setup_pell_only_case(withdraw_date="2026-10-26")
        case = scen["case"]
        assert case["aid_earned_cents"] == 200_000
        assert case["status"] == "CLOSED"
        assert scen["obligations"] == []

        resp = api_client.rescind_withdrawal(scen["enrollment"]["id"],
                                             REGISTRAR)
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
        enr = get_enrollment(scen["enrollment"]["id"])
        assert enr["status"] == "WITHDRAWN"

    def test_record_return_on_voided_obligation_rejected(self):
        """PRD section 3.6: "Recording against an obligation already
        `RETURNED` fails with `ERR_OBLIGATION_ALREADY_RETURNED`, and against
        a `VOIDED` one with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/record_return_on_voided_obligation_rejected
        """
        scen = setup_pell_only_case()
        ob = scen["obligations"][0]
        # Recalculate to day 64 (100% earned): voids the obligation.
        validate_success(api_client.recalculate_case(
            scen["case"]["id"],
            {"expected_withdrawal_case_version": scen["case"]["version"],
             "notification_date": "2026-10-26"},
            make_financial_aid_officer_headers(OFFICER_1_ID)), 200)
        voided = [o for o in list_obligations(scen["case"]["id"])
                  if o["id"] == ob["id"]][0]
        assert voided["status"] == "VOIDED"

        resp = api_client.record_return(ob["id"], {"amount_cents": 80_000},
                                        BURSAR)
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    def test_rescind_blocked_when_return_completed_rejected(self):
        """PRD section 3.7: "The same completed-business guards as
        recalculation apply: a `RETURNED` obligation blocks with
        `ERR_RETURN_ALREADY_COMPLETED`, and an `ACCEPTED` offer blocks with
        `ERR_OFFER_ALREADY_ACCEPTED`."

        Design: Corner/state_machines/rescind_blocked_when_return_completed_rejected
        """
        scen = setup_t2_split_case(charges=80_000,
                                   clock="2026-11-15T00:00:00Z",
                                   record_school_return=True)
        resp = api_client.rescind_withdrawal(scen["enrollment"]["id"],
                                             REGISTRAR)
        validate_error(resp, "ERR_RETURN_ALREADY_COMPLETED",
                       expected_status=409)
        assert get_enrollment(scen["enrollment"]["id"])["status"] == "WITHDRAWN"
        # The student obligation is still PENDING, so the case never closed.
        assert scen["case"]["status"] == "CALCULATED"

    def test_recalculate_blocked_by_returned_obligation_rejected(self):
        """PRD section 3.7: "recalculation is rejected with
        `ERR_RETURN_ALREADY_COMPLETED` when any obligation of the case is
        already `RETURNED`, and with `ERR_OFFER_ALREADY_ACCEPTED` when any
        offer of the case is already `ACCEPTED`, because money that has
        actually moved can no longer be recomputed away."

        Design: Corner/validations/recalculate_blocked_by_returned_obligation_rejected
        """
        scen = setup_t2_split_case(charges=80_000,
                                   clock="2026-11-15T00:00:00Z",
                                   record_school_return=True)
        case = scen["case"]
        assert case["status"] == "CALCULATED"
        resp = api_client.recalculate_case(
            case["id"],
            {"expected_withdrawal_case_version": case["version"]},
            make_financial_aid_officer_headers(OFFICER_2_ID))
        validate_error(resp, "ERR_RETURN_ALREADY_COMPLETED",
                       expected_status=409)
        assert get_case(case["id"])["status"] == "CALCULATED"

    def test_recalculate_blocked_by_accepted_offer_rejected(self):
        """PRD section 3.7: "recalculation is rejected with
        `ERR_RETURN_ALREADY_COMPLETED` when any obligation of the case is
        already `RETURNED`, and with `ERR_OFFER_ALREADY_ACCEPTED` when any
        offer of the case is already `ACCEPTED`, because money that has
        actually moved can no longer be recomputed away."

        Design: Corner/validations/recalculate_blocked_by_accepted_offer_rejected
        """
        # Two loan awards produce two offers; the student accepts the first.
        term = create_term_t1()
        student = create_student()
        enrollment = create_enrollment(student["id"], term["id"],
                                       institutional_charges_cents=600_000)
        pell = create_award(enrollment["id"], "PELL_GRANT", 200_000)
        disburse(schedule_disbursement(pell["id"], 100_000)["id"])
        schedule_disbursement(pell["id"], 100_000)
        sub = create_award(enrollment["id"], "SUBSIDIZED_LOAN", 300_000)
        accept_award(sub["id"], student["id"])
        disburse(schedule_disbursement(sub["id"], 100_000)["id"])
        schedule_disbursement(sub["id"], 200_000)
        unsub = create_award(enrollment["id"], "UNSUBSIDIZED_LOAN", 100_000)
        accept_award(unsub["id"], student["id"])
        schedule_disbursement(unsub["id"], 100_000)

        case = withdraw_official(enrollment["id"], "2026-10-25")
        set_clock("2026-10-26T09:00:00Z")
        calc = validate_success(api_client.calculate_case(
            case["id"], make_financial_aid_officer_headers(OFFICER_1_ID)), 200)
        # earned: pell 120000 + sub 180000 + unsub 60000 = 360000 > 200000.
        assert calc["pwd_loan_cents"] == 140_000
        offers = list_offers(case["id"])
        assert len(offers) == 2
        # Offers are created in ascending award created_at order: SUB first.
        assert offers[0]["amount_cents"] == 80_000
        assert offers[1]["amount_cents"] == 60_000
        validate_success(api_client.accept_offer(
            offers[0]["id"], make_student_headers(student["id"])), 200)

        resp = api_client.recalculate_case(
            case["id"],
            {"expected_withdrawal_case_version": calc["version"]},
            make_financial_aid_officer_headers(OFFICER_2_ID))
        validate_error(resp, "ERR_OFFER_ALREADY_ACCEPTED", expected_status=409)
        # The UNSUB offer is still SENT, keeping the case CALCULATED.
        assert get_case(case["id"])["status"] == "CALCULATED"


class TestOptimisticConcurrency:

    def test_occ_stale_version_rejected_current_accepted(self):
        """PRD section 2.8: "A recalculation request must carry
        `expected_withdrawal_case_version`, a non-optional field holding the
        `version` of the withdrawal case as the client last observed it. If
        that value does not match the case's current `version` — because
        another writer has advanced the case since the client last read it —
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the client from overwriting a calculation it has not
        observed."

        Design: Corner/cross_cutting/occ_stale_version_rejected
        """
        scen = setup_pell_only_case()
        case = scen["case"]
        current_version = case["version"]

        resp = api_client.recalculate_case(
            case["id"],
            {"expected_withdrawal_case_version": current_version - 1},
            make_financial_aid_officer_headers(OFFICER_2_ID))
        validate_error(resp, "ERR_STALE_VERSION", expected_status=412)

        ok = validate_success(api_client.recalculate_case(
            case["id"],
            {"expected_withdrawal_case_version": current_version},
            make_financial_aid_officer_headers(OFFICER_2_ID)), 200)
        assert ok["version"] == current_version + 1
