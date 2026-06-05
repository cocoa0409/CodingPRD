"""Approval, denial, the certification cascade, the approval gate ordering, and
the conserved caseload counter (PRD §3.5, §2.9, §3.6).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_agency,
    create_household,
    create_participant,
    setup_risk_assessed_application,
    setup_certified_participant,
    make_clerk_headers,
    make_cpa_headers,
    CLERK,
    CPA,
)


class TestCertificationCascade:
    def test_approve_cascades_cert_participant_caseload_ebt(self, api):
        """PRD §3.5: "At the second level, creating that active certification
        transitions the participant from APPLICANT to ACTIVE, increments the
        agency's active_caseload_count by one, and — if the participant does not
        already have one — creates the participant's EbtAccount in OPEN status."

        Design: Difficulty/transitive_cascade/approve_to_cert_to_participant_to_ebt_depth3
        """
        ctx = setup_risk_assessed_application(
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1,
            income_records=[(150000, "MONTHLY")], risk_factor_codes=["GEST_DIABETES"],
            ssn_last4="2004",
        )
        agency_id = ctx["agency_id"]
        p_id = ctx["participant"]["id"]
        validate_success(api.approve_application(ctx["application"]["id"], CPA))

        participant = validate_success(api.get_participant(p_id, CPA))
        assert participant["status"] == "ACTIVE"
        agency = validate_success(api.get_agency(agency_id, CPA))
        assert agency["active_caseload_count"] == 1
        ebts, _ = validate_paginated(
            api.list_ebt_accounts(CPA, params={"participant_id": p_id})
        )
        assert ebts[0]["status"] == "OPEN"

    def test_approve_creates_certification_and_opens_ebt(self, api):
        """PRD §3.5: "At the first level the server creates a Certification for the
        participant in ACTIVE status, recording its participant_id and the
        originating application_id."
        PRD §3.5: "The new EBT account references the participant_id and begins
        with all value counters (issued_value_cents, redeemed_value_cents,
        voided_value_cents, remaining_value_cents) at 0 and an empty balance_units
        map."

        Design: Difficulty/transitive_cascade/approve_to_cert_to_participant_to_ebt_depth3
        """
        ctx = setup_certified_participant(
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")], ssn_last4="2044",
        )
        cert = ctx["certification"]
        assert cert["status"] == "ACTIVE"
        assert cert["application_id"] == ctx["application"]["id"]
        assert cert["participant_id"] == ctx["participant"]["id"]
        ebt = ctx["ebt_account"]
        assert ebt["status"] == "OPEN"
        assert ebt["issued_value_cents"] == 0
        assert ebt["redeemed_value_cents"] == 0
        assert ebt["voided_value_cents"] == 0
        assert ebt["remaining_value_cents"] == 0
        assert ebt["balance_units"] == {}

    def test_pregnant_cert_length_and_priority(self, api):
        """PRD §3.5: "its cert_length_days is derived from the participant's
        category: 280 days for PREGNANT, 180 for POSTPARTUM, and 365 for each of
        BREASTFEEDING, INFANT, and CHILD."
        PRD §3.5: "Approval also sets the participant's priority_level from the
        category: priority 1 for PREGNANT, BREASTFEEDING, and INFANT; priority 6
        for POSTPARTUM; and priority 3 for CHILD."

        Design: Corner/calculations/cert_length_category_pregnant_280_days
        """
        ctx = setup_certified_participant(
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")], clock_iso="2026-01-01T00:00:00.000Z",
            ssn_last4="4445",
        )
        assert ctx["certification"]["cert_length_days"] == 280
        assert ctx["participant"]["priority_level"] == 1


class TestApprovalFork:
    def test_deny_leaves_participant_applicant_and_caseload_unchanged(self, api):
        """PRD §3.5: "On denial the application moves to DENIED, its version
        increments by one, no certification is created, the participant remains in
        APPLICANT status, and the agency's active_caseload_count is unchanged."

        Design: Difficulty/non_linear_state_machine/application_fork_join_approve_vs_deny
        """
        ctx = setup_risk_assessed_application(
            category="CHILD", adjunctive_program="SNAP", household_size=3,
            income_records=[(100000, "MONTHLY")], risk_factor_codes=["ANEMIA"],
            ssn_last4="1002",
        )
        app = validate_success(api.deny_application(ctx["application"]["id"], CPA))
        assert app["status"] == "DENIED"
        participant = validate_success(api.get_participant(ctx["participant"]["id"], CPA))
        assert participant["status"] == "APPLICANT"
        agency = validate_success(api.get_agency(ctx["agency_id"], CPA))
        assert agency["active_caseload_count"] == 0

    def test_approve_branch_mints_certification_and_activates(self, api):
        """PRD §3.5: "When all checks pass, the approval stamps certified_by_user_id
        with the approving CPA's X-User-ID, moves the application to APPROVED, and
        triggers a three-level cascade. At the first level the server creates a
        Certification for the participant in ACTIVE status".

        Design: Difficulty/non_linear_state_machine/application_fork_join_approve_vs_deny
        """
        ctx = setup_certified_participant(
            category="CHILD", adjunctive_program="SNAP", household_size=3,
            risk_factor_codes=["ANEMIA"], income_records=[(100000, "MONTHLY")],
            ssn_last4="1022",
        )
        app = validate_success(api.get_application(ctx["application"]["id"], CPA))
        assert app["status"] == "APPROVED"
        assert ctx["certification"]["status"] == "ACTIVE"
        assert ctx["participant"]["status"] == "ACTIVE"


class TestApprovalGateOrdering:
    def test_invalid_state_beats_income_ineligible(self, api):
        """PRD §2.9: "then the target resource's state legality for the requested
        transition (ERR_INVALID_STATE). Only after all of these pass does the
        server evaluate the operation's domain-specific business rules."
        PRD §3.5: "Approval is the consequential branch and is guarded by a
        sequence of business checks evaluated in the order given in Section 2.9.
        The application must be in RISK_ASSESSED (otherwise ERR_INVALID_STATE)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_income_ineligible
        """
        # DRAFT application (never income-determined) that is also income-ineligible
        agency = create_agency(caseload_cap=50)
        hh = create_household(agency["id"], household_size=1, adjunctive_program="NONE")
        p = create_participant(hh["id"], full_name="Child Three", ssn_last4="1003",
                               category="CHILD")
        app = validate_success(api.create_application({"participant_id": p["id"]}, CLERK), 201)
        resp = api.approve_application(app["id"], CPA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_invalid_state_beats_income_ineligible_at_income_determined(self, api):
        """PRD §2.9: "then the target resource's state legality for the requested
        transition (ERR_INVALID_STATE). Only after all of these pass does the
        server evaluate the operation's domain-specific business rules."
        PRD §3.5: "The application must be in RISK_ASSESSED (otherwise
        ERR_INVALID_STATE)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_income_ineligible
        """
        # INCOME_DETERMINED (not yet RISK_ASSESSED) and income-ineligible: the
        # state check (priority 6) still pre-empts the eligibility gate (priority 10).
        agency = create_agency(caseload_cap=50)
        hh = create_household(agency["id"], household_size=1, adjunctive_program="NONE")
        p = create_participant(hh["id"], full_name="Mid State", ssn_last4="1033",
                               category="CHILD")
        app = validate_success(api.create_application({"participant_id": p["id"]}, CLERK), 201)
        validate_success(api.create_income_record(
            {"application_id": app["id"], "gross_amount_cents": 500000,
             "pay_frequency": "MONTHLY"}, CLERK,
        ), 201)
        det = validate_success(api.determine_income(app["id"], CLERK))
        assert det["status"] == "INCOME_DETERMINED"
        assert det["income_eligible"] is False
        resp = api.approve_application(app["id"], CPA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_dual_participation_beats_caseload(self, api):
        """PRD §2.9: "On approval the order is: segregation of duties
        (ERR_SEGREGATION_OF_DUTIES), then dual participation
        (ERR_DUAL_PARTICIPATION), then the vendor-authorization check where
        applicable, then the eligibility gates (ERR_INCOME_INELIGIBLE before
        ERR_RISK_INELIGIBLE), then the temporal-overlap checks, and finally the
        fiscal and quota checks such as caseload capacity (ERR_CASELOAD_EXCEEDED)."
        PRD §3.5: "no participant in a different household sharing this
        participant's full_name and ssn_last4 may currently hold an ACTIVE
        certification; if one does, the approval is rejected with
        ERR_DUAL_PARTICIPATION."

        Design: Difficulty/priority_pair_validation_conflict/dual_participation_beats_caseload
        """
        agency = create_agency(caseload_cap=1)
        # Participant X: approved, occupies the single caseload slot.
        ctx_x = setup_certified_participant(
            agency_id=agency["id"], category="CHILD", adjunctive_program="SNAP",
            household_size=3, risk_factor_codes=["ANEMIA"],
            income_records=[(100000, "MONTHLY")],
            full_name="Dup Name", ssn_last4="9999",
        )
        assert ctx_x["certification"]["status"] == "ACTIVE"
        # Participant Y: different household, identical (full_name, ssn_last4),
        # eligible and RISK_ASSESSED. Approving Y both duplicates and exceeds cap.
        ctx_y = setup_risk_assessed_application(
            agency_id=agency["id"], category="CHILD", adjunctive_program="SNAP",
            household_size=4, risk_factor_codes=["ANEMIA"],
            income_records=[(100000, "MONTHLY")],
            full_name="Dup Name", ssn_last4="9999",
        )
        resp = api.approve_application(ctx_y["application"]["id"], CPA)
        validate_error(resp, ApiErrorId.ERR_DUAL_PARTICIPATION.value)

    def test_caseload_surfaces_once_dual_condition_absent(self, api):
        """PRD §2.9: "On approval the order is: segregation of duties
        (ERR_SEGREGATION_OF_DUTIES), then dual participation
        (ERR_DUAL_PARTICIPATION), then the vendor-authorization check where
        applicable, then the eligibility gates (ERR_INCOME_INELIGIBLE before
        ERR_RISK_INELIGIBLE), then the temporal-overlap checks, and finally the
        fiscal and quota checks such as caseload capacity (ERR_CASELOAD_EXCEEDED)."
        PRD §3.5: "the caseload gate: the agency's active_caseload_count must be
        strictly less than its caseload_cap (otherwise ERR_CASELOAD_EXCEEDED)."

        Design: Difficulty/priority_pair_validation_conflict/dual_participation_beats_caseload
        """
        # Same full-cap agency, but the second participant is NOT a dual: with the
        # higher-priority dual gate absent, the lower-priority caseload gate is what
        # fires — confirming the ordering relationship of the priority pair.
        agency = create_agency(caseload_cap=1)
        setup_certified_participant(
            agency_id=agency["id"], category="CHILD", adjunctive_program="SNAP",
            household_size=3, risk_factor_codes=["ANEMIA"],
            income_records=[(100000, "MONTHLY")],
            full_name="Solo Name", ssn_last4="8001",
        )
        ctx_z = setup_risk_assessed_application(
            agency_id=agency["id"], category="CHILD", adjunctive_program="MEDICAID",
            household_size=4, risk_factor_codes=["ANEMIA"],
            income_records=[(100000, "MONTHLY")],
            full_name="Other Name", ssn_last4="8002",
        )
        resp = api.approve_application(ctx_z["application"]["id"], CPA)
        validate_error(resp, ApiErrorId.ERR_CASELOAD_EXCEEDED.value)


class TestApprovalBusinessChecks:
    def test_caseload_exceeded_on_second_distinct_approval(self, api):
        """PRD §3.5: "Finally, the caseload gate: the agency's
        active_caseload_count must be strictly less than its caseload_cap
        (otherwise ERR_CASELOAD_EXCEEDED)."

        Design: Corner/errors/caseload_exceeded_on_second_approval
        """
        agency = create_agency(caseload_cap=1)
        setup_certified_participant(
            agency_id=agency["id"], category="CHILD", adjunctive_program="SNAP",
            household_size=3, risk_factor_codes=["ANEMIA"],
            income_records=[(100000, "MONTHLY")],
            full_name="Cap X", ssn_last4="1111",
        )
        # distinct, NOT a dual participant
        ctx_y = setup_risk_assessed_application(
            agency_id=agency["id"], category="CHILD", adjunctive_program="MEDICAID",
            household_size=2, risk_factor_codes=["ANEMIA"],
            income_records=[(100000, "MONTHLY")],
            full_name="Cap Y", ssn_last4="2222",
        )
        resp = api.approve_application(ctx_y["application"]["id"], CPA)
        validate_error(resp, ApiErrorId.ERR_CASELOAD_EXCEEDED.value)

    def test_segregation_of_duties_same_user_blocked(self, api):
        """PRD §3.5: "First, segregation of duties: the approving CPA's X-User-ID
        must differ from the determined_by_user_id stamped at income
        determination; if they are equal, the approval is rejected with
        ERR_SEGREGATION_OF_DUTIES."

        Design: Corner/errors/segregation_of_duties_same_user_blocked
        """
        # determine-income run by user "shared"; approve also by "shared".
        ctx = setup_risk_assessed_application(
            category="CHILD", adjunctive_program="SNAP", household_size=3,
            income_records=[(100000, "MONTHLY")], risk_factor_codes=["ANEMIA"],
            ssn_last4="1212", clerk_id="shared", cpa_id="cpa-1",
        )
        resp = api.approve_application(ctx["application"]["id"], make_cpa_headers("shared"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


class TestConservedCaseload:
    def test_caseload_count_returns_to_zero_after_terminate(self, api):
        """PRD §3.6: "At the first level the certification moves to TERMINATED, the
        participant moves to TERMINATED, the participant's version increments by
        one, and the agency's active_caseload_count is decremented by one,
        compensating the debit that approval applied."

        Design: Difficulty/compensating_invariant/caseload_count_conserved_on_terminate
        """
        ctx = setup_certified_participant(
            category="CHILD", adjunctive_program="SNAP", household_size=3,
            risk_factor_codes=["ANEMIA"], income_records=[(100000, "MONTHLY")],
            ssn_last4="1005",
        )
        agency_id = ctx["agency_id"]
        after_approve = validate_success(api.get_agency(agency_id, CPA))
        assert after_approve["active_caseload_count"] == 1
        validate_success(api.terminate_certification(ctx["certification"]["id"], CPA))
        after_terminate = validate_success(api.get_agency(agency_id, CPA))
        assert after_terminate["active_caseload_count"] == 0

    def test_approve_debits_caseload_by_one(self, api):
        """PRD §3.1: "The active_caseload_count is a derived counter: it is debited
        (incremented) by one each time a participant is certified and credited
        (decremented) by one when a participant's certification is terminated or
        expires."
        PRD §3.5: "creating that active certification transitions the participant
        from APPLICANT to ACTIVE, increments the agency's active_caseload_count by
        one".

        Design: Difficulty/compensating_invariant/caseload_count_conserved_on_terminate
        """
        agency = create_agency(caseload_cap=50)
        before = validate_success(api.get_agency(agency["id"], CLERK))
        assert before["active_caseload_count"] == 0
        setup_certified_participant(
            agency_id=agency["id"], category="CHILD", adjunctive_program="SNAP",
            household_size=3, risk_factor_codes=["ANEMIA"],
            income_records=[(100000, "MONTHLY")], ssn_last4="1055",
        )
        after = validate_success(api.get_agency(agency["id"], CPA))
        assert after["active_caseload_count"] == 1
