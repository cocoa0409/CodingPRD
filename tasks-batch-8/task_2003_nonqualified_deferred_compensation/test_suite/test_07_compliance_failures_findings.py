"""Compliance workflows: specified-employee selection, operational failures and
income inclusion, document findings and posture, rabbi trust funding, CIC.

PRD §3.5, §3.7, §3.8, §3.9.
"""
from test_helpers import (
    TEST_USERS,
    add_member,
    advance_clock,
    create_active_plan,
    create_cic_event_payload,
    create_draft_specified_list,
    create_document_finding_payload,
    create_rabbi_trust_payload,
    enroll_participant,
    finalize_list,
    funding_event_payload,
    get_account,
    get_participant,
    get_plan,
    make_compliance_officer_headers,
    open_account,
    open_separation_case,
    plan_version,
    setup_funded_account,
    setup_operational_failure,
    setup_quantified_failure,
    validate_error,
    validate_success,
)

PS = TEST_USERS["plan_sponsor_headers"]
BA = TEST_USERS["benefits_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
TO = TEST_USERS["trust_officer_headers"]


class TestSpecifiedEmployeeSelection:
    def test_specified_officer_cap_selection_with_tiebreak(self, api):
        """PRD §3.5: "The `officer_cap_count` is computed as the smaller of fifty
        and one tenth of the eligible count rounded down to a whole number."
        PRD §3.5: "Members on the `OFFICER` basis are then ranked by
        `annual_compensation_cents` from highest to lowest, ties broken toward
        the earlier-created participant record (the participant's `id` is never
        used as a tiebreaker); those within the cap emerge `is_specified` true,
        and those beyond it emerge `is_specified` false with `exclusion_reason`
        of `OFFICER_CAP_EXCEEDED`."
        PRD §3.5: "Members on the `COMPENSATION_THRESHOLD` basis are specified
        when their `annual_compensation_cents` is at least the plan's
        `officer_comp_threshold_cents` — the boundary is inclusive — and
        otherwise receive `exclusion_reason` of `BELOW_COMP_THRESHOLD`."
        PRD §3.5: "Members on the `FIVE_PERCENT_OWNER` basis are specified
        unconditionally."

        25 eligible participants -> cap min(50, floor(25*0.10)) = 2; three
        OFFICER members (500k, 400k, 400k) resolve the 400k tie by creation
        order.

        Design: Corner/calculations/specified_officer_cap_selection_with_tiebreak
        """
        plan = create_active_plan(name="Plan SO", distribution_events_allowed=["SEPARATION"])
        members = []
        for i in range(1, 26):
            members.append(enroll_participant(plan["id"], employee_ref=f"EMP-S{i:02d}",
                                              hire_date="2023-01-02"))
        m_a, m_b, m_c, m_d, m_e, m_f, m_g = members[:7]

        lst = create_draft_specified_list(plan["id"], identification_date="2026-12-31",
                                          effective_date="2027-04-01")
        add_member(lst["id"], m_a["id"], "OFFICER", 50000000)
        add_member(lst["id"], m_b["id"], "OFFICER", 40000000)
        add_member(lst["id"], m_c["id"], "OFFICER", 40000000)
        add_member(lst["id"], m_d["id"], "COMPENSATION_THRESHOLD", 20000000)
        add_member(lst["id"], m_e["id"], "COMPENSATION_THRESHOLD", 19999999)
        add_member(lst["id"], m_f["id"], "FIVE_PERCENT_OWNER", 100000)

        finalized = finalize_list(lst["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["officer_cap_count"] == 2, "min(50, floor(25*0.10))"

        roster = {m["participant_id"]: m for m in finalized["members"]}
        assert roster[m_a["id"]]["is_specified"] is True, "rank 1 by compensation"
        assert roster[m_b["id"]]["is_specified"] is True, "40000000 tie -> earlier created"
        assert roster[m_c["id"]]["is_specified"] is False
        assert roster[m_c["id"]]["exclusion_reason"] == "OFFICER_CAP_EXCEEDED"
        assert roster[m_d["id"]]["is_specified"] is True, "20000000 >= 20000000 inclusive"
        assert roster[m_e["id"]]["is_specified"] is False
        assert roster[m_e["id"]]["exclusion_reason"] == "BELOW_COMP_THRESHOLD"
        assert roster[m_f["id"]]["is_specified"] is True, "FIVE_PERCENT_OWNER unconditional"

        assert get_participant(m_b["id"])["is_specified_employee"] is True
        assert get_participant(m_c["id"])["is_specified_employee"] is False
        assert get_participant(m_g["id"])["is_specified_employee"] is False, (
            "non-member participant unaffected"
        )


class TestIncomeInclusion:
    def test_income_inclusion_credit_before_interest_order(self, api):
        """PRD §3.8: "The computation then runs in a pinned five-step order,
        because the credit reduces the base *before* interest and tax are
        computed — computing interest on the gross amount and subtracting the
        credit afterward is a different, forbidden order. First,
        `includible_base_cents` is the failure amount minus the correction
        credit, floored at zero. Second, the days outstanding are counted from
        the `failure_date` to the clock date at quantification. Third,
        `premium_interest_cents` is the base multiplied by 800 basis points —
        the combination of a 700-basis-point underpayment rate and a
        100-basis-point premium — multiplied by the days outstanding, divided
        by the product of 10000 and 365, and rounded half-up to whole cents.
        Fourth, `additional_tax_cents` is the base multiplied by 2000 basis
        points — the twenty percent additional tax — divided by 10000, again
        rounded half-up. Fifth, `total_inclusion_cents` is the sum of the base,
        the interest, and the tax."

        Failure 500000 dated 2026-01-15, credit 200000, quantified at the
        startup clock 2026-08-01 (198 days outstanding): base 300000, interest
        round_half_up(300000*800*198/3650000) = 13019, tax 60000, total 373019.

        Design: Corner/calculations/income_inclusion_credit_before_interest_order
        """
        plan = create_active_plan(name="Plan II", distribution_events_allowed=["SEPARATION"])
        participant = enroll_participant(plan["id"], employee_ref="EMP-II",
                                         hire_date="2023-01-02")
        account = open_account(participant["id"], plan["id"])
        failure = setup_operational_failure(
            account["id"], failure_type="LATE_PAYMENT", failure_date="2026-01-15",
            amount_cents=500000, description="scheduled 2026-01-15 paid late")
        assert failure["status"] == "IDENTIFIED"
        assert failure["correction_deadline"] == "2028-12-31", (
            "December 31 of the second calendar year following the failure's year"
        )

        quantified = validate_success(api.quantify_failure(
            failure["id"], {"correction_credit_cents": 200000}, CO), 200)
        assert quantified["status"] == "QUANTIFIED"
        assert quantified["includible_base_cents"] == 300000, "credit applied FIRST"
        assert quantified["premium_interest_cents"] == 13019, (
            "round_half_up(300000*800*198/3650000) = round_half_up(13019.18)"
        )
        assert quantified["additional_tax_cents"] == 60000, "300000 * 2000 / 10000"
        assert quantified["total_inclusion_cents"] == 373019, "base + interest + tax"

    def test_assess_then_correct_leaves_zero_liability_drift(self, api):
        """PRD §3.8: "Assessment adds the case's `total_inclusion_cents` to the
        participant's running `inclusion_liability_cents`, flags the account —
        an `ACTIVE` account moves to `FLAGGED_FOR_INCLUSION` — records
        `assessed_by_user_id`, and moves the case to `INCLUSION_ASSESSED`."
        PRD §3.8: "Correction of a previously assessed case subtracts its
        `total_inclusion_cents` from the participant's
        `inclusion_liability_cents` — an exact compensating reversal, so the
        liability drifts net zero across assess-then-correct — and, when no
        other failure case of the same account remains in `QUANTIFIED` or
        `INCLUSION_ASSESSED`, returns the account from `FLAGGED_FOR_INCLUSION`
        to `ACTIVE`."

        Failure 500000 dated 2027-01-15 quantified at clock 2027-02-01 (17
        days): total_inclusion_cents = 500000 + 1863 + 100000 = 601863; assess
        adds exactly that and correct subtracts exactly that — zero net drift.

        Design: Difficulty/compensating_invariant/assess_then_correct_leaves_zero_liability_drift
        """
        ctx = setup_funded_account(100000, plan_overrides={"name": "Plan IL"},
                                   participant_overrides={"employee_ref": "EMP-IL"})
        advance_clock("2027-02-01T00:00:00Z")
        failure = setup_operational_failure(
            ctx["account"]["id"], failure_type="EARLY_PAYMENT",
            failure_date="2027-01-15", amount_cents=500000,
            description="paid before permissible date")
        assert get_participant(ctx["participant"]["id"])["inclusion_liability_cents"] == 0

        quantified = validate_success(api.quantify_failure(
            failure["id"], {"correction_credit_cents": 0}, CO), 200)
        assert quantified["includible_base_cents"] == 500000
        assert quantified["premium_interest_cents"] == 1863, "round_half_up(500000*800*17/3650000)"
        assert quantified["additional_tax_cents"] == 100000
        assert quantified["total_inclusion_cents"] == 601863

        assessed = validate_success(api.assess_inclusion(failure["id"], CO2), 200)
        assert assessed["status"] == "INCLUSION_ASSESSED"
        assert get_participant(
            ctx["participant"]["id"])["inclusion_liability_cents"] == 601863, "forward action"
        assert get_account(ctx["account"]["id"])["status"] == "FLAGGED_FOR_INCLUSION"

        corrected = validate_success(api.correct_failure(failure["id"], CO), 200)
        assert corrected["status"] == "CORRECTED"
        assert get_participant(
            ctx["participant"]["id"])["inclusion_liability_cents"] == 0, (
            "compensating action: liability returns exactly to zero"
        )
        assert get_account(ctx["account"]["id"])["status"] == "ACTIVE"

    def test_correct_from_quantified_never_flags_account(self, api):
        """PRD §3.8: "From either `QUANTIFIED` or `INCLUSION_ASSESSED`
        (`ERR_FAILURE_STATE_INVALID` otherwise), and only while the clock date
        remains within the `correction_deadline`, inclusive of the deadline
        date (`ERR_CORRECTION_WINDOW_EXPIRED`), a `ComplianceOfficer` may
        correct the case."
        PRD §3.8: "Correction of a previously assessed case subtracts its
        `total_inclusion_cents` from the participant's `inclusion_liability_cents`".

        Correcting a case that was never assessed performs no liability
        subtraction and never touched the account flag.

        Design: Difficulty/compensating_invariant/assess_then_correct_leaves_zero_liability_drift
        """
        ctx = setup_funded_account(100000, plan_overrides={"name": "Plan IL2"},
                                   participant_overrides={"employee_ref": "EMP-IL2"})
        advance_clock("2027-02-01T00:00:00Z")
        failure = setup_quantified_failure(ctx["account"]["id"],
                                           correction_credit_cents=0,
                                           failure_type="EARLY_PAYMENT",
                                           failure_date="2027-01-15",
                                           amount_cents=500000)
        assert failure["status"] == "QUANTIFIED"
        assert get_participant(ctx["participant"]["id"])["inclusion_liability_cents"] == 0
        assert get_account(ctx["account"]["id"])["status"] == "ACTIVE"

        corrected = validate_success(api.correct_failure(failure["id"], CO), 200)
        assert corrected["status"] == "CORRECTED"
        assert get_participant(ctx["participant"]["id"])["inclusion_liability_cents"] == 0
        assert get_account(ctx["account"]["id"])["status"] == "ACTIVE", "never flagged"


class TestCorrectionDeadlinesAndPosture:
    def test_correction_deadline_inclusive_then_lapse(self, api):
        """PRD §3.9: "A `ComplianceOfficer` files a correction — supplying the
        amendment `correction_text`, null until filed — while the finding is
        `REPORTED` (`ERR_FINDING_STATE_INVALID`) and the clock date remains
        within the correction deadline, inclusive (`ERR_CORRECTION_WINDOW_EXPIRED`)".
        PRD §3.9: "`REJECTED` instead sends the finding back to `REPORTED` with
        its `correction_text` retained for audit, and the cycle may repeat."
        PRD §3.9: "a finding still `REPORTED` or `CORRECTION_FILED` when the
        clock date passes its `correction_deadline` lapses to `LAPSED`,
        dragging the plan's posture to `LAPSED_FAILURE`".
        PRD §3.8: "From either `QUANTIFIED` or `INCLUSION_ASSESSED`
        (`ERR_FAILURE_STATE_INVALID` otherwise), and only while the clock date
        remains within the `correction_deadline`, inclusive of the deadline
        date (`ERR_CORRECTION_WINDOW_EXPIRED`), a `ComplianceOfficer` may
        correct the case."

        Both finding and failure carry deadline 2028-12-31 (failure year 2026):
        filing on the deadline date is accepted; after the clock crosses to
        2029-01-01 the finding lapses and the failure's correction is expired.

        Design: Corner/validations/correction_deadline_inclusive_then_lapse
        """
        plan = create_active_plan(name="Plan CD", distribution_events_allowed=["SEPARATION"])
        finding = validate_success(api.create_document_finding(
            create_document_finding_payload(
                plan["id"], description="Missing deferral election timing clause",
                failure_year=2026), CO), 201)
        assert finding["correction_deadline"] == "2028-12-31"

        participant = enroll_participant(plan["id"], employee_ref="EMP-CD")
        account = open_account(participant["id"], plan["id"])
        failure = setup_quantified_failure(
            account["id"], failure_type="LATE_PAYMENT", failure_date="2026-06-01",
            amount_cents=50000, description="paid after scheduled date")
        assert failure["correction_deadline"] == "2028-12-31"

        advance_clock("2028-12-31T12:00:00Z")  # deadline date itself: inclusive
        filed = validate_success(api.file_correction(
            finding["id"], {"correction_text": "Amendment restating election timing rules"},
            CO), 200)
        assert filed["status"] == "CORRECTION_FILED"

        rejected = validate_success(api.adjudicate_finding(
            finding["id"], {"outcome": "REJECTED"}, PS), 200)
        assert rejected["status"] == "REPORTED", "REJECTED cycles the finding back"

        advance_clock("2029-01-01T00:00:00Z")  # past the deadline
        lapsed = validate_success(api.get_document_finding(finding["id"], CO), 200)
        assert lapsed["status"] == "LAPSED"
        assert get_plan(plan["id"])["document_posture"] == "LAPSED_FAILURE"

        expired = api.correct_failure(failure["id"], CO)
        validate_error(expired, "ERR_CORRECTION_WINDOW_EXPIRED", expected_status=422)

    def test_derived_fields_reconcile_on_finding_lifecycle(self, api):
        """PRD §3.9: "It reads `COMPLIANT` when no finding of the plan sits in
        `REPORTED`, `CORRECTION_FILED`, or `LAPSED`; `FAILURE_OPEN` when at
        least one finding is `REPORTED` or `CORRECTION_FILED` and none is
        `LAPSED`; and `LAPSED_FAILURE` the moment any finding has lapsed. The
        `open_findings_count` tallies the findings in `REPORTED` or
        `CORRECTION_FILED`."
        PRD §3.9: "The finding opens `REPORTED` with its `correction_deadline`
        computed as December 31 of the second year following `failure_year`".

        Posture/count track the finding through report -> file -> CORRECTED:
        0/COMPLIANT -> 1/FAILURE_OPEN -> 1/FAILURE_OPEN -> 0/COMPLIANT.

        Design: Corner/cross_cutting_layers/derived_fields_reconcile_on_finding_lifecycle
        """
        plan = create_active_plan(name="Plan DR", distribution_events_allowed=["SEPARATION"])
        assert get_plan(plan["id"])["document_posture"] == "COMPLIANT"
        assert get_plan(plan["id"])["open_findings_count"] == 0

        finding = validate_success(api.create_document_finding(
            create_document_finding_payload(
                plan["id"], description="Missing six-month delay clause",
                failure_year=2026), CO), 201)
        assert finding["correction_deadline"] == "2028-12-31"

        after_report = get_plan(plan["id"])
        assert after_report["document_posture"] == "FAILURE_OPEN"
        assert after_report["open_findings_count"] == 1

        filed = validate_success(api.file_correction(
            finding["id"], {"correction_text": "Insert six-month delay language per 409A"},
            CO), 200)
        assert filed["status"] == "CORRECTION_FILED"
        after_file = get_plan(plan["id"])
        assert after_file["document_posture"] == "FAILURE_OPEN", "filed-but-open still open"
        assert after_file["open_findings_count"] == 1

        adjudicated = validate_success(api.adjudicate_finding(
            finding["id"], {"outcome": "CORRECTED"}, PS), 200)
        assert adjudicated["status"] == "CORRECTED"
        after_correct = get_plan(plan["id"])
        assert after_correct["document_posture"] == "COMPLIANT"
        assert after_correct["open_findings_count"] == 0, "derived fields reconcile"


class TestRabbiTrustAndCic:
    def test_trust_funding_target_and_cic_exact_amount(self, api):
        """PRD §3.7: "The effective target is 12500 basis points — one hundred
        twenty-five percent — once `cic_funding_required` holds, and the trust's
        own `funding_target_bp` otherwise."
        PRD §3.7: "The trust's `posture` follows: `UNFUNDED` when assets are
        zero; `UNDERFUNDED` when assets are positive but below the target; and
        `FUNDED` when assets meet or exceed a positive target — assets exactly
        equal to the target count as funded — or whenever assets are positive
        while the target computes to zero."
        PRD §3.7: "A `CIC_MANDATORY_FUNDING` must be positive, is accepted only
        when a verified change-in-control event exists for the plan
        (`ERR_NO_VERIFIED_CIC`), and must equal the trust's
        `required_funding_cents` exactly at the moment it is posted — the
        statute's full-funding demand admits no partial gestures — with any
        other amount rejected as `ERR_CIC_FUNDING_AMOUNT_MISMATCH`."

        Liability 1000000 -> target 1000000 at 10000 bp; 400000 contributed ->
        UNDERFUNDED (required 600000); +600000 -> FUNDED (inclusive). After CIC
        verification the required funding is exactly 250000; 249999 is rejected
        and 250000 is accepted.

        Design: Corner/calculations/trust_funding_target_and_cic_exact_amount
        """
        ctx = setup_funded_account(
            1000000,
            plan_overrides={"name": "Plan TF",
                            "distribution_events_allowed": ["SEPARATION", "CHANGE_IN_CONTROL"],
                            "rabbi_trust_required": True, "vesting_cliff_years": 3},
            participant_overrides={"employee_ref": "EMP-TF", "hire_date": "2023-01-02"})
        trust = validate_success(api.create_rabbi_trust(
            create_rabbi_trust_payload(ctx["plan"]["id"], funding_target_bp=10000), PS), 201)
        assert trust["posture"] == "UNFUNDED", "assets 0"
        assert trust["assets_cents"] == 0

        first = validate_success(api.post_funding_event(
            trust["id"], funding_event_payload("CONTRIBUTION", 400000), TO), 201)
        assert first["posture"] == "UNDERFUNDED"
        assert first["required_funding_cents"] == 600000, "target 1000000 - 400000"

        second = validate_success(api.post_funding_event(
            trust["id"], funding_event_payload("CONTRIBUTION", 600000), TO), 201)
        assert second["posture"] == "FUNDED", "assets 1000000 == target, inclusive"
        assert second["required_funding_cents"] == 0

        cic = validate_success(api.create_cic_event(
            create_cic_event_payload(ctx["plan"]["id"], event_type="OWNERSHIP_CHANGE",
                                     effective_date="2027-02-01", stake_change_bp=5000), PS), 201)
        verified = validate_success(api.adjudicate_cic(cic["id"], {"outcome": "VERIFIED"}, CO), 200)
        assert verified["status"] == "VERIFIED"

        escalated = validate_success(api.get_rabbi_trust(trust["id"], TO), 200)
        assert escalated["cic_funding_required"] is True
        assert escalated["required_funding_cents"] == 250000, (
            "ceil(1000000*12500/10000) - 1000000"
        )

        short = api.post_funding_event(
            trust["id"], funding_event_payload("CIC_MANDATORY_FUNDING", 249999), TO)
        validate_error(short, "ERR_CIC_FUNDING_AMOUNT_MISMATCH", expected_status=402)

        exact = validate_success(api.post_funding_event(
            trust["id"], funding_event_payload("CIC_MANDATORY_FUNDING", 250000), TO), 201)
        assert exact["assets_cents"] == 1250000
        assert exact["posture"] == "FUNDED"
        assert exact["required_funding_cents"] == 0

    def test_cic_threshold_boundary(self, api):
        """PRD §3.7: "an `OWNERSHIP_CHANGE` requires a stake of at least 5000
        basis points — half the ownership — an `EFFECTIVE_CONTROL_CHANGE`
        requires at least 3500, and an `ASSET_CHANGE` at least 4000, and a
        report below its type's threshold is rejected with
        `ERR_CIC_THRESHOLD_NOT_MET`."

        4999 bp fails adjudication while 5000 bp verifies (inclusive).

        Design: Corner/validations/cic_threshold_boundary
        """
        plan = create_active_plan(name="Plan CT",
                                  distribution_events_allowed=["CHANGE_IN_CONTROL"])
        cic_low = validate_success(api.create_cic_event(
            create_cic_event_payload(plan["id"], stake_change_bp=4999), PS), 201)
        cic_ok = validate_success(api.create_cic_event(
            create_cic_event_payload(plan["id"], stake_change_bp=5000), PS), 201)

        blocked = api.adjudicate_cic(cic_low["id"], {"outcome": "VERIFIED"}, CO)
        validate_error(blocked, "ERR_CIC_THRESHOLD_NOT_MET", expected_status=422)
        unchanged = validate_success(api.get_cic_event(cic_low["id"], CO), 200)
        assert unchanged["status"] == "REPORTED"

        verified = validate_success(api.adjudicate_cic(cic_ok["id"], {"outcome": "VERIFIED"}, CO), 200)
        assert verified["status"] == "VERIFIED", "5000 >= 5000, inclusive"
