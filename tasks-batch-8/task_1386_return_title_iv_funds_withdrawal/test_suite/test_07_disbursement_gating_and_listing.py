"""Cross-entity disbursement gates, award lifecycle, list/pagination
behavior, immediate consistency, and version increment discipline."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_aid_award,
    assert_aid_disbursement,
    create_and_fund_award,
    create_award,
    create_enrollment,
    create_student,
    create_term_t1,
    disburse,
    get_case,
    get_enrollment,
    list_account_entries,
    schedule_disbursement,
    setup_pell_only_case,
    setup_term_student_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_official,
)
from test_helpers.fixtures import OFFICER_1_ID
from test_helpers.test_users import (
    make_financial_aid_officer_headers,
    make_student_headers,
)

REGISTRAR = TEST_USERS["registrar_clerk_headers"]
OFFICER = TEST_USERS["financial_aid_officer_headers"]
BURSAR = TEST_USERS["bursar_clerk_headers"]


class TestDisbursementGating:

    def test_disbursement_requires_award_accepted(self):
        """PRD section 3.3: "The release is rejected with
        `ERR_INVALID_STATE` when the disbursement is not `SCHEDULED`, with
        `ERR_AWARD_NOT_ACCEPTED` when the parent award is not `ACCEPTED`"

        Design: Difficulty/cross_entity_state_dependency/disbursement_requires_award_accepted
        """
        _, student, enrollment = setup_term_student_enrollment(
            charges=600_000)
        # Loan stays OFFERED: the student never accepts it.
        loan = create_award(enrollment["id"], "SUBSIDIZED_LOAN", 300_000)
        assert loan["status"] == "OFFERED"
        disb = schedule_disbursement(loan["id"], 100_000)
        resp = api_client.disburse_disbursement(disb["id"], OFFICER)
        validate_error(resp, "ERR_AWARD_NOT_ACCEPTED", expected_status=409)

        after = validate_success(api_client.get_disbursement(disb["id"],
                                                             OFFICER), 200)
        assert after["status"] == "SCHEDULED"
        assert after["disbursed_on"] is None

    def test_disbursement_succeeds_once_award_accepted(self):
        """PRD section 3.3: "A successful release stamps `disbursed_on` with
        the current logical date, adds the amount to the award's
        `disbursed_amount_cents` while subtracting it from
        `scheduled_amount_cents`, posts an `AID_CREDIT` ledger entry for the
        negated amount whose `source_ref` is the disbursement's id, and
        recomputes the enrollment's balance."

        Design: Difficulty/cross_entity_state_dependency/disbursement_requires_award_accepted
        """
        _, student, enrollment = setup_term_student_enrollment(
            charges=600_000)
        loan = create_award(enrollment["id"], "SUBSIDIZED_LOAN", 300_000)
        disb = schedule_disbursement(loan["id"], 100_000)
        validate_success(api_client.accept_award(
            loan["id"], make_student_headers(student["id"])), 200)
        released = validate_success(api_client.disburse_disbursement(
            disb["id"], OFFICER), 200)
        assert_aid_disbursement(released)
        assert released["status"] == "DISBURSED"
        assert released["disbursed_on"] is not None

        award = validate_success(api_client.get_award(loan["id"], OFFICER),
                                 200)
        assert award["disbursed_amount_cents"] == 100_000
        assert award["scheduled_amount_cents"] == 0
        credits = list_account_entries(enrollment_id=enrollment["id"],
                                       entry_type="AID_CREDIT")
        assert len(credits) == 1
        assert credits[0]["amount_cents"] == -100_000
        assert credits[0]["source_ref"] == disb["id"]
        assert get_enrollment(enrollment["id"])["balance_cents"] == 500_000

    def test_disbursement_blocked_by_open_withdrawal_case(self):
        """PRD section 3.3: "The release is rejected with `ERR_INVALID_STATE`
        when the disbursement is not `SCHEDULED`, with
        `ERR_AWARD_NOT_ACCEPTED` when the parent award is not `ACCEPTED`, and
        with `ERR_DISBURSEMENT_BLOCKED_BY_CASE` whenever the enrollment has a
        withdrawal case in `OPEN` or `CALCULATED` — once a withdrawal is in
        flight, funds may reach the student only through the post-withdrawal
        disbursement machinery of §3.5, and the system-created disbursements
        produced by that machinery bypass this gate."

        Design: Difficulty/cross_entity_state_dependency/disbursement_blocked_by_active_withdrawal_case
        """
        term = create_term_t1()
        student = create_student()
        enrollment = create_enrollment(student["id"], term["id"],
                                       institutional_charges_cents=600_000)
        create_and_fund_award(enrollment["id"], student["id"],
                              "PELL_GRANT", 200_000, 200_000)
        loan = create_award(enrollment["id"], "SUBSIDIZED_LOAN", 300_000)
        validate_success(api_client.accept_award(
            loan["id"], make_student_headers(student["id"])), 200)
        # Scheduled while no case exists; left SCHEDULED across the withdraw.
        disb = schedule_disbursement(loan["id"], 100_000)
        case = withdraw_official(enrollment["id"], "2026-09-02")
        assert case["status"] == "OPEN"

        # Even with an ACCEPTED award, the OPEN case freezes manual release.
        resp = api_client.disburse_disbursement(disb["id"], OFFICER)
        validate_error(resp, "ERR_DISBURSEMENT_BLOCKED_BY_CASE",
                       expected_status=409)

        after = validate_success(api_client.get_disbursement(disb["id"],
                                                             OFFICER), 200)
        assert after["status"] == "SCHEDULED"
        award = validate_success(api_client.get_award(loan["id"], OFFICER),
                                 200)
        assert award["disbursed_amount_cents"] == 0  # unchanged

    def test_disbursement_blocked_by_calculated_withdrawal_case(self):
        """PRD section 3.3: "The release is rejected with `ERR_INVALID_STATE`
        when the disbursement is not `SCHEDULED`, with
        `ERR_AWARD_NOT_ACCEPTED` when the parent award is not `ACCEPTED`, and
        with `ERR_DISBURSEMENT_BLOCKED_BY_CASE` whenever the enrollment has a
        withdrawal case in `OPEN` or `CALCULATED` — once a withdrawal is in
        flight, funds may reach the student only through the post-withdrawal
        disbursement machinery of §3.5, and the system-created disbursements
        produced by that machinery bypass this gate."

        Design: Difficulty/cross_entity_state_dependency/disbursement_blocked_by_active_withdrawal_case
        """
        # PELL-only case A: after calculate a SCHOOL obligation stays
        # PENDING, so the case remains CALCULATED.
        scen = setup_pell_only_case()
        case = scen["case"]
        assert case["status"] == "CALCULATED"
        # The PELL award is fully disbursed; schedule against a fresh loan
        # instead (calculation cancelled the pre-existing SCHEDULED rows).
        loan = create_award(scen["enrollment"]["id"], "SUBSIDIZED_LOAN",
                            300_000)
        validate_success(api_client.accept_award(
            loan["id"], make_student_headers(scen["student"]["id"])), 200)
        disb = schedule_disbursement(loan["id"], 50_000)
        resp = api_client.disburse_disbursement(disb["id"], OFFICER)
        validate_error(resp, "ERR_DISBURSEMENT_BLOCKED_BY_CASE",
                       expected_status=409)
        after = validate_success(api_client.get_disbursement(disb["id"],
                                                             OFFICER), 200)
        assert after["status"] == "SCHEDULED"


class TestAwardLifecycle:

    def test_award_initial_state_by_program(self):
        """PRD section 3.3: "A Pell grant begins life already `ACCEPTED`,
        reflecting that no student acceptance is required; every loan begins
        `OFFERED`. The award's `is_grant` flag is derived and reads true
        exactly when the program is `PELL_GRANT`."

        Design: Corner/state_machines/award_initial_state_by_program
        """
        _, _, enrollment = setup_term_student_enrollment(charges=600_000)
        pell = create_award(enrollment["id"], "PELL_GRANT", 200_000)
        assert_aid_award(pell)
        assert pell["status"] == "ACCEPTED"
        assert pell["is_grant"] is True

        loan = create_award(enrollment["id"], "UNSUBSIDIZED_LOAN", 100_000)
        assert_aid_award(loan)
        assert loan["status"] == "OFFERED"
        assert loan["is_grant"] is False

    def test_award_cancel_with_disbursements_rejected(self):
        """PRD section 3.3: "a `FinancialAidOfficer` may cancel an award from
        either `OFFERED` or `ACCEPTED`, but only while the award has no
        `DISBURSED` disbursements — an award with disbursed funds cannot be
        cancelled and the attempt fails with
        `ERR_AWARD_HAS_DISBURSEMENTS`."

        Design: Corner/validations/award_cancel_with_disbursements_rejected
        """
        _, student, enrollment = setup_term_student_enrollment(
            charges=600_000)
        pell = create_and_fund_award(enrollment["id"], student["id"],
                                     "PELL_GRANT", 200_000, 200_000)
        resp = api_client.cancel_award(pell["id"], OFFICER)
        validate_error(resp, "ERR_AWARD_HAS_DISBURSEMENTS",
                       expected_status=409)
        award = validate_success(api_client.get_award(pell["id"], OFFICER),
                                 200)
        assert award["status"] == "ACCEPTED"

    def test_disbursement_exceeds_award_rejected(self):
        """PRD section 3.3: "the cumulative total of already scheduled plus
        already disbursed amounts plus the new amount must not exceed the
        award's `amount_cents`, or the request fails with
        `ERR_DISBURSEMENT_EXCEEDS_AWARD`."

        Design: Corner/validations/disbursement_exceeds_award_rejected
        """
        _, _, enrollment = setup_term_student_enrollment(charges=600_000)
        pell = create_award(enrollment["id"], "PELL_GRANT", 200_000)
        schedule_disbursement(pell["id"], 150_000)
        # 150000 scheduled + 100000 new > 200000 award amount.
        resp = api_client.create_disbursement(
            pell["id"], {"amount_cents": 100_000}, OFFICER)
        validate_error(resp, "ERR_DISBURSEMENT_EXCEEDS_AWARD",
                       expected_status=422)
        award = validate_success(api_client.get_award(pell["id"], OFFICER),
                                 200)
        assert award["scheduled_amount_cents"] == 150_000


class TestListingAndPagination:

    def test_list_pagination_envelope(self):
        """PRD section 2.3: "Paginated and non-paginated list-based
        responses include the following fields in the `meta` object of the
        response envelope: `limit`, `offset`, `total_count`, and `has_more`."
        PRD section 2.3: "The `limit` parameter specifies the maximum number
        of items to return. If not provided, it defaults to 10, with a
        minimum of 1 and maximum of 100. The `offset` parameter specifies the
        number of items to skip and defaults to 0."

        Design: Corner/endpoints/list_pagination_envelope
        """
        term = create_term_t1(with_break=False)
        s1 = create_student()
        s2 = create_student()
        e1 = create_enrollment(s1["id"], term["id"],
                               institutional_charges_cents=600_000)
        e2 = create_enrollment(s2["id"], term["id"],
                               institutional_charges_cents=500_000)

        page1, meta1 = validate_paginated(api_client.list_enrollments(
            REGISTRAR, params={"limit": 1, "offset": 0}))
        assert meta1["total_count"] == 2
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0
        assert meta1["has_more"] is True
        assert len(page1) == 1

        page2, meta2 = validate_paginated(api_client.list_enrollments(
            REGISTRAR, params={"limit": 1, "offset": 1}))
        assert meta2["has_more"] is False
        assert len(page2) == 1
        # Ascending creation order: page 2 holds the other enrollment.
        assert {page1[0]["id"], page2[0]["id"]} == {e1["id"], e2["id"]}

    def test_filtered_list_finds_case_by_enrollment(self):
        """PRD section 3.7: "Throughout the lifecycle, officers and auditors
        can list withdrawal cases filtered by `enrollment_id` and `status`,
        review a case's obligations and offers through its nested lists, and
        inspect the append-only ledger filtered by `enrollment_id`,
        `entry_type`, or `reversal_of_entry_id`."

        Design: Corner/endpoints/filtered_list_finds_case_by_enrollment
        """
        term = create_term_t1(with_break=False)
        s1 = create_student()
        s2 = create_student()
        e1 = create_enrollment(s1["id"], term["id"],
                               institutional_charges_cents=600_000)
        e2 = create_enrollment(s2["id"], term["id"],
                               institutional_charges_cents=600_000)
        case = withdraw_official(e1["id"], "2026-09-02")

        data, meta = validate_paginated(api_client.list_withdrawal_cases(
            REGISTRAR, params={"enrollment_id": e1["id"]}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == case["id"]

        data2, meta2 = validate_paginated(api_client.list_withdrawal_cases(
            REGISTRAR, params={"enrollment_id": e2["id"]}))
        assert data2 == []
        assert meta2["total_count"] == 0


class TestConsistencyAndVersioning:

    def test_immediate_visibility_after_calculate(self):
        """PRD section 2.6: "The enrollment's `balance_cents` is always a
        derived figure: the sum of the signed `amount_cents` over every
        account entry of the enrollment, where a positive value means the
        student owes the school. Any posting of a new entry triggers an
        immediate recomputation of `balance_cents`."
        PRD section 3.5: "Calculation closes by recomputing the enrollment's
        `balance_cents` from the ledger; when the balance is positive, the
        notification fields `balance_notification_sent` and
        `balance_notified_at` are set as described in §2.6."

        Design: Corner/consistency/immediate_visibility_after_calculate
        """
        scen = setup_pell_only_case()
        case = scen["case"]
        # min(round(600000 * 0.400) = 240000, 80000) = 80000.
        assert case["school_return_cents"] == 80_000
        # The very next read reflects the whole cascade:
        # 600000 - 200000 aid + 80000 chargeback = 480000.
        enr = get_enrollment(scen["enrollment"]["id"])
        assert enr["balance_cents"] == 480_000
        assert enr["balance_notification_sent"] is True
        assert enr["balance_notified_at"] is not None

    def test_version_increments_on_mutation(self):
        """PRD section 2.4: "`version` (integer): a system-managed integer
        that increments by one with every modification to the resource,
        including modifications caused by cascades originating from another
        resource."
        PRD section 3.4: "In the same action the enrollment moves from
        `ENROLLED` to `WITHDRAWN`, its `current_withdrawal_case_id` is set to
        the new case, and the enrollment's `version` increments."

        Design: Corner/cross_cutting/version_increments_on_mutation
        """
        _, _, enrollment = setup_term_student_enrollment(charges=600_000)
        version_at_create = enrollment["version"]
        assert isinstance(version_at_create, int)
        withdraw_official(enrollment["id"], "2026-09-02")
        after = get_enrollment(enrollment["id"])
        assert after["version"] == version_at_create + 1
