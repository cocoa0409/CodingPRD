"""Return obligations, post-withdrawal offers, deadline sweeps, and the
fiscal / segregation-of-duties guards around recording returns."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_post_withdrawal_offer,
    assert_return_obligation,
    create_and_fund_award,
    create_award,
    create_enrollment,
    create_student,
    create_term_t1,
    get_enrollment,
    list_obligations,
    schedule_disbursement,
    disburse,
    set_clock,
    setup_pell_only_case,
    setup_pwd_case,
    setup_t2_split_case,
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


class TestRecordReturnGuards:

    def test_returned_obligation_masks_amount_mismatch(self):
        """PRD section 2.9: "for example, recording a return against an
        obligation that is already `RETURNED` surfaces
        `ERR_OBLIGATION_ALREADY_RETURNED` even when the supplied amount is
        also wrong, because the state check (priority 6) precedes fiscal
        exactness (priority 12)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_returned_obligation
        """
        scen = setup_pell_only_case()  # SCHOOL obligation 80000
        ob = scen["obligations"][0]
        assert ob["amount_cents"] == 80_000
        recorded = validate_success(api_client.record_return(
            ob["id"], {"amount_cents": 80_000}, BURSAR), 200)
        assert recorded["status"] == "RETURNED"
        assert recorded["returned_amount_cents"] == 80_000

        # Both checks violated: state (6) wins over fiscal (12).
        resp = api_client.record_return(ob["id"], {"amount_cents": 1}, BURSAR)
        validate_error(resp, "ERR_OBLIGATION_ALREADY_RETURNED",
                       expected_status=409)
        after = [o for o in list_obligations(scen["case"]["id"])
                 if o["id"] == ob["id"]][0]
        assert after["returned_amount_cents"] == 80_000

    def test_returned_obligation_rejects_even_the_correct_amount(self):
        """PRD section 3.6: "Recording against an obligation already
        `RETURNED` fails with `ERR_OBLIGATION_ALREADY_RETURNED`, and against
        a `VOIDED` one with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_returned_obligation
        """
        scen = setup_pell_only_case()
        ob = scen["obligations"][0]
        validate_success(api_client.record_return(
            ob["id"], {"amount_cents": 80_000}, BURSAR), 200)
        resp = api_client.record_return(ob["id"], {"amount_cents": 80_000},
                                        BURSAR)
        validate_error(resp, "ERR_OBLIGATION_ALREADY_RETURNED",
                       expected_status=409)

    def test_return_amount_mismatch_rejected(self):
        """PRD section 3.6: "The supplied amount must equal the obligation's
        `amount_cents` exactly; any difference is rejected with
        `ERR_RETURN_AMOUNT_MISMATCH`."

        Design: Corner/validations/return_amount_mismatch_rejected
        """
        scen = setup_pell_only_case()
        ob = scen["obligations"][0]
        resp = api_client.record_return(ob["id"], {"amount_cents": 79_999},
                                        BURSAR)
        validate_error(resp, "ERR_RETURN_AMOUNT_MISMATCH", expected_status=422)
        after = [o for o in list_obligations(scen["case"]["id"])
                 if o["id"] == ob["id"]][0]
        assert after["status"] == "PENDING"

    def test_late_return_from_overdue_succeeds(self):
        """PRD section 3.6: "Recording a return is shared between the
        `BursarClerk` and the `FinancialAidOfficer`, and is permitted from
        either `PENDING` or `OVERDUE` — a late return is accepted and
        recorded all the same."
        PRD section 3.6: "A successful recording stamps `returned_at` with
        the current logical time, stores the amount as
        `returned_amount_cents`, notes the actor in `recorded_by_user_id`,
        moves the obligation to `RETURNED`, and triggers the case's automatic
        closure evaluation."

        Design: Corner/state_machines/late_return_from_overdue_succeeds
        """
        scen = setup_pell_only_case()
        ob = scen["obligations"][0]
        set_clock("2026-12-10T08:00:00Z")  # one day past due 2026-12-09
        overdue = [o for o in list_obligations(scen["case"]["id"])
                   if o["id"] == ob["id"]][0]
        assert overdue["status"] == "OVERDUE"

        recorded = validate_success(api_client.record_return(
            ob["id"], {"amount_cents": 80_000}, BURSAR), 200)
        assert_return_obligation(recorded)
        assert recorded["status"] == "RETURNED"
        assert recorded["returned_amount_cents"] == 80_000
        assert recorded["returned_at"] is not None
        # All obligations terminal, no offers, notification sent at
        # calculate -> the case auto-closes.
        case = validate_success(api_client.get_withdrawal_case(
            scen["case"]["id"], BURSAR), 200)
        assert case["status"] == "CLOSED"


class TestSegregationOfDuties:

    def test_sod_masks_amount_mismatch(self):
        """PRD section 2.9: "the server evaluates them in a fixed priority
        order and surfaces the earliest applicable failure rather than an
        arbitrary one"
        PRD section 2.9: "11. **Segregation of duties** — a
        `FinancialAidOfficer` may not record the school-party return of a
        case they themselves calculated; otherwise `ERR_SEGREGATION_OF_DUTIES`
        (403)."
        PRD section 2.9: "12. **Fiscal exactness** — a recorded return must
        equal the obligation amount exactly, and scheduled plus disbursed
        disbursements must not exceed the award amount; violations yield
        `ERR_RETURN_AMOUNT_MISMATCH` (422) or `ERR_DISBURSEMENT_EXCEEDS_AWARD`
        (422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_on_sod_return
        """
        scen = setup_pell_only_case(officer_id=OFFICER_1_ID)
        ob = scen["obligations"][0]
        # The calculating officer AND a wrong amount: SoD (11) wins.
        resp = api_client.record_return(
            ob["id"], {"amount_cents": 1},
            make_financial_aid_officer_headers(OFFICER_1_ID))
        validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
        after = [o for o in list_obligations(scen["case"]["id"])
                 if o["id"] == ob["id"]][0]
        assert after["status"] == "PENDING"

    def test_sod_binds_identity_not_role(self):
        """PRD section 3.6: "a `FinancialAidOfficer` whose `X-User-ID`
        equals the case's `calculated_by_user_id` may not record the
        `SCHOOL`-party return of that case — the attempt is rejected with
        `ERR_SEGREGATION_OF_DUTIES` — while a `BursarClerk` is never barred,
        and student-party returns carry no such restriction."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_on_sod_return
        """
        scen = setup_pell_only_case(officer_id=OFFICER_1_ID)
        ob = scen["obligations"][0]
        # Correct amount, but the same officer who calculated: still barred.
        resp = api_client.record_return(
            ob["id"], {"amount_cents": 80_000},
            make_financial_aid_officer_headers(OFFICER_1_ID))
        validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
        # A different FinancialAidOfficer (not the calculator) may record it.
        recorded = validate_success(api_client.record_return(
            ob["id"], {"amount_cents": 80_000},
            make_financial_aid_officer_headers(OFFICER_2_ID)), 200)
        assert recorded["status"] == "RETURNED"

    def test_sod_blocks_calculating_officer_but_not_bursar(self):
        """PRD section 3.6: "a `FinancialAidOfficer` whose `X-User-ID`
        equals the case's `calculated_by_user_id` may not record the
        `SCHOOL`-party return of that case — the attempt is rejected with
        `ERR_SEGREGATION_OF_DUTIES` — while a `BursarClerk` is never barred,
        and student-party returns carry no such restriction."

        Design: Corner/validations/sod_blocks_calculating_officer_but_not_bursar
        """
        scen = setup_pell_only_case(officer_id=OFFICER_1_ID)
        ob = scen["obligations"][0]
        resp = api_client.record_return(
            ob["id"], {"amount_cents": 80_000},
            make_financial_aid_officer_headers(OFFICER_1_ID))
        validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
        recorded = validate_success(api_client.record_return(
            ob["id"], {"amount_cents": 80_000}, BURSAR), 200)
        assert recorded["status"] == "RETURNED"


class TestReturnDeadlineSweep:

    def _setup_obligation(self):
        scen = setup_pell_only_case()
        return scen, scen["obligations"][0]

    def test_due_date_is_inclusive_then_overdue_next_day(self):
        """PRD section 2.5: "Every return obligation still `PENDING` whose
        `due_date` is strictly earlier than the new current date transitions
        to `OVERDUE`; on the `due_date` itself the obligation remains
        `PENDING`, because the deadline is inclusive."
        PRD section 3.5: "a `due_date` exactly 45 calendar days after the
        case's `determination_date`"

        Design: Difficulty/boundary_precision_check/return_deadline_inclusive_due_date
        """
        scen, ob = self._setup_obligation()
        assert ob["due_date"] == "2026-12-09"  # 2026-10-25 + 45 days

        # Late on the due date itself: still PENDING (deadline inclusive).
        set_clock("2026-12-09T23:59:00Z")
        on_due = [o for o in list_obligations(scen["case"]["id"])
                  if o["id"] == ob["id"]][0]
        assert on_due["status"] == "PENDING"

        # The next day the sweep flips it.
        set_clock("2026-12-10T00:00:00Z")
        after = [o for o in list_obligations(scen["case"]["id"])
                 if o["id"] == ob["id"]][0]
        assert after["status"] == "OVERDUE"

    def test_before_due_date_stays_pending(self):
        """PRD section 3.6: "A return obligation begins `PENDING` and ages
        under the logical clock: when a clock sweep finds the current date
        strictly past the obligation's `due_date`, the obligation transitions
        from `PENDING` to `OVERDUE`, while on the due date itself it remains
        `PENDING` — the 45-day deadline is inclusive."

        Design: Difficulty/boundary_precision_check/return_deadline_inclusive_due_date
        """
        scen, ob = self._setup_obligation()
        assert ob["due_date"] == "2026-12-09"
        set_clock("2026-12-08T00:00:00Z")  # one day before the due date
        current = [o for o in list_obligations(scen["case"]["id"])
                   if o["id"] == ob["id"]][0]
        assert current["status"] == "PENDING"


class TestOfferDeadlinesAndExpiry:

    def test_offer_deadline_constants_applied(self):
        """PRD section 3.6: "The student's response window,
        `response_deadline`, is the calendar date of `offered_at` plus 14
        days"
        PRD section 3.6: "A compliance flag, `late_offer`, reads true when
        the offer's creation date falls more than 30 calendar days after the
        case's `determination_date`, marking a violation of the 30-day offer
        rule."

        Design: Corner/calculations/offer_deadline_constants_applied
        """
        # Determination 2026-10-25 (OFFICIAL); calculate runs with the clock
        # at 2026-11-30 -> offered 36 days later (> 2026-11-24) -> late.
        scen = setup_pwd_case(charges=500_000, clock="2026-11-30T10:00:00Z")
        offers = scen["offers"]
        assert len(offers) == 1
        offer = offers[0]
        assert_post_withdrawal_offer(offer)
        assert offer["late_offer"] is True
        assert offer["response_deadline"] == "2026-12-14"  # 11-30 + 14d

    def test_decline_on_expired_offer_rejected(self):
        """PRD section 2.5: "Every post-withdrawal offer still `SENT` whose
        `response_deadline` is strictly earlier than the new current date
        transitions to `EXPIRED`; on the deadline date itself the offer
        remains `SENT` and may still be accepted."
        PRD section 3.6: "the offer must still be `SENT` — an offer in any
        other status is rejected with `ERR_OFFER_NOT_RESPONDABLE`."

        Design: Corner/state_machines/decline_on_expired_offer_rejected
        """
        scen = setup_pwd_case(charges=500_000, clock="2026-10-26T09:00:00Z")
        offer = scen["offers"][0]
        # Offered 2026-10-26 -> response_deadline 2026-11-09; the next day
        # the sweep expires it.
        assert offer["response_deadline"] == "2026-11-09"
        set_clock("2026-11-10T00:00:00Z")
        expired = validate_success(api_client.get_post_withdrawal_offer(
            offer["id"], OFFICER), 200)
        assert expired["status"] == "EXPIRED"

        resp = api_client.decline_offer(
            offer["id"], make_student_headers(scen["student"]["id"]))
        validate_error(resp, "ERR_OFFER_NOT_RESPONDABLE", expected_status=409)

    def test_offer_acceptance_allowed_on_deadline_date(self):
        """PRD section 3.6: "The student's response window,
        `response_deadline`, is the calendar date of `offered_at` plus 14
        days, and acceptance remains allowed on the deadline date itself —
        the window is inclusive, with expiration occurring only once the
        current date passes the deadline, at which point a clock sweep moves
        the offer from `SENT` to `EXPIRED`."

        Design: Corner/calculations/offer_deadline_constants_applied
        """
        scen = setup_pwd_case(charges=500_000, clock="2026-10-26T09:00:00Z")
        offer = scen["offers"][0]
        assert offer["response_deadline"] == "2026-11-09"
        # Move the clock exactly onto the deadline date: still SENT.
        set_clock("2026-11-09T12:00:00Z")
        current = validate_success(api_client.get_post_withdrawal_offer(
            offer["id"], OFFICER), 200)
        assert current["status"] == "SENT"
        accepted = validate_success(api_client.accept_offer(
            offer["id"], make_student_headers(scen["student"]["id"])), 200)
        assert accepted["status"] == "ACCEPTED"
