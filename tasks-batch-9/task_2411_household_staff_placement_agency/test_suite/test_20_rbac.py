"""Role grants, the two body-partitioned actions and the two maker-checker rules.

Every refusal here is taken with a request that is otherwise entirely valid, so
the 403 can only be about who is asking; the two accepting cases pin the rules
down from the other side.
"""
from test_helpers import (
    BILLING,
    CASE_OPENER,
    CASE_RESOLVER,
    CONSULTANT,
    PRINCIPAL,
    RECORDER,
    VERIFIER,
    VETTING_RECORDER_USER_ID,
    VETTING_VERIFIER_USER_ID,
    api_client,
    confirm_start_payload,
    countersign_agreement_payload,
    create_household,
    create_non_solicitation_case_payload,
    create_reference_check_payload,
    create_trial_engagement_payload,
    finalize_scope_payload,
    invoice_milestone_payload,
    make_candidate_headers,
    make_client_headers,
    prepare_payroll_handoff,
    read_candidate,
    read_case,
    read_client,
    read_milestone,
    read_placement,
    read_reference,
    read_requisition,
    read_term,
    record_reference,
    register_candidate,
    resolve_case_payload,
    respond_accommodation_term_payload,
    respond_to_term,
    set_clock,
    settle_case_payload,
    setup_active_placement,
    setup_investigating_case,
    setup_pending_offer,
    setup_scenario,
    setup_substantiated_case,
    setup_vetted_candidate,
    sign_agreement_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verify_reference_payload,
)


class TestExclusiveAgencyOperations:
    def test_01_the_consultant_may_not_confirm_the_start_it_offered(self):
        """Every business precondition is met, so only the grant is missing.

        PRD §4: "| POST | `/placements/{id}/confirm-start` | Confirm the actual
        package: re-price the fee from its four components and re-allocate the
        milestones. | `AgencyPrincipal` |"

        Design: Corner/rbac/the_placement_consultant_cannot_confirm_a_start
        """
        scenario = setup_pending_offer()
        set_clock("2026-09-01T00:00:00Z")

        validate_error(
            api_client.confirm_placement_start(
                scenario["placement"]["id"], confirm_start_payload(), CONSULTANT
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        stored = read_placement(scenario["placement"])
        assert stored["placement_status"] == "PENDING_ACCEPTANCE"
        assert stored["fee_variant"] == "PROVISIONAL"
        assert stored["guarantee_expires_on"] == "2026-11-30"
        assert read_client(scenario["client"])["placement_count"] == 0

    def test_02_the_vetting_desk_may_not_book_the_presentation(self):
        """The specialist cleared this candidate but does not own the household.

        PRD §4: "| POST | `/role-requisitions/{id}/trial-engagements` | Book a
        trial day or working interview for a candidate at the household. |
        `PlacementConsultant` |"

        Design: Corner/rbac/the_vetting_specialist_cannot_book_a_trial
        """
        scenario = setup_vetted_candidate()

        validate_error(
            api_client.create_trial_engagement(
                scenario["requisition"]["id"],
                create_trial_engagement_payload(scenario["candidate"]["id"]),
                RECORDER,
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        stored = read_requisition(scenario["requisition"])
        assert stored["status"] == "SOURCING"
        assert stored["active_trial_count"] == 0

        _, meta = validate_paginated(
            api_client.list_trial_engagements(
                CONSULTANT, {"requisition_id": scenario["requisition"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_03_the_consultant_may_register_a_candidate_but_not_reference_it(self):
        """Registration is shared; adding evidence to the vetting file is not.

        PRD §4: "| POST | `/candidates/{id}/reference-checks` | Record a reference
        to be verified, optionally chaining it to the next-earlier reference. |
        `VettingSpecialist` |"

        Design: Corner/rbac/the_placement_consultant_cannot_record_a_reference_check
        """
        set_clock("2026-08-01T00:00:00Z")
        candidate = register_candidate()

        validate_error(
            api_client.create_reference_check(
                candidate["id"], create_reference_check_payload(), CONSULTANT
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        _, meta = validate_paginated(
            api_client.list_candidate_reference_checks(candidate["id"], RECORDER)
        )
        assert meta["total_count"] == 0

        stored = read_candidate(candidate)
        assert stored["vetting_status"] == "UNVETTED"
        assert stored["screening_score"] == 0

    def test_04_the_principal_may_not_post_the_receivable(self):
        """The principal decided the placement but does not run the ledger.

        PRD §4: "| POST | `/fee-milestones/{id}/invoice` | Invoice a milestone and
        post the receivable. | `BillingAdministrator` |"

        Design: Corner/rbac/the_agency_principal_cannot_invoice_a_milestone
        """
        scenario = setup_active_placement()

        validate_error(
            api_client.invoice_fee_milestone(
                scenario["milestones"][0]["id"], invoice_milestone_payload(), PRINCIPAL
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        assert read_milestone(scenario["milestones"][0])["invoice_status"] == "PENDING"

        _, meta = validate_paginated(
            api_client.list_ledger_entries(scenario["client"]["id"], BILLING)
        )
        assert meta["total_count"] == 0

    def test_05_the_billing_desk_may_not_raise_the_allegation(self):
        """The desk that settles the penalty is not the desk that alleges it.

        PRD §4: "| POST | `/non-solicitation-cases` | Allege that a household
        solicited a candidate in breach of the non-solicitation term. |
        `ComplianceOfficer` |"

        Design: Corner/rbac/the_billing_administrator_cannot_open_an_enforcement_case
        """
        scenario = setup_active_placement()

        validate_error(
            api_client.create_non_solicitation_case(
                create_non_solicitation_case_payload(
                    scenario["client"]["id"], scenario["candidate"]["id"], "2026-09-01"
                ),
                BILLING,
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        _, meta = validate_paginated(
            api_client.list_non_solicitation_cases(
                CASE_OPENER, {"respondent_client_id": scenario["client"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert read_client(scenario["client"])["status"] == "ONBOARDED"

    def test_06_the_household_may_not_freeze_the_commercial_terms(self):
        """Scoping is shared with the household; stamping the fee band is not.

        PRD §4: "| POST | `/role-requisitions/{id}/finalize-scope` | Close the
        scoping round: resolve the fee band and stamp the provisional fee. |
        `PlacementConsultant` |"

        Design: Corner/rbac/the_client_cannot_finalize_the_scope
        """
        scenario = setup_scenario(stage="scoping")

        validate_error(
            api_client.finalize_scope(
                scenario["requisition"]["id"],
                finalize_scope_payload(),
                scenario["client_headers"],
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        stored = read_requisition(scenario["requisition"])
        assert stored["status"] == "SCOPING"
        assert stored["fee_percent_bps"] is None
        assert stored["provisional_fee_cents"] is None

    def test_07_the_compliance_desk_may_not_settle_what_it_assessed(self):
        """Even a second officer is refused: the money movement is another desk's.

        PRD §4: "| POST | `/non-solicitation-cases/{id}/settle` | Settle a
        substantiated case for no more than the assessed penalty. |
        `BillingAdministrator` |"

        Design: Corner/rbac/the_compliance_officer_cannot_settle_a_case_it_substantiated
        """
        scenario = setup_substantiated_case()

        validate_error(
            api_client.settle_non_solicitation_case(
                scenario["case"]["id"], settle_case_payload(1_000_000), CASE_OPENER
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        stored = read_case(scenario["case"])
        assert stored["status"] == "SUBSTANTIATED"
        assert stored["settlement_amount_cents"] is None
        assert read_client(scenario["client"])["status"] == "SUSPENDED"


class TestTheBodyPartitionedAgreement:
    def test_08_the_agency_may_not_sign_on_the_household_s_behalf(self):
        """The same role that may countersign may not sign.

        PRD §2.1: "Two operations are further partitioned by the value in the body
        rather than by the endpoint. On the confidentiality-agreement endpoint, an
        `action` of `SIGN` is exclusive to the `Client` role and an `action` of
        `COUNTERSIGN` is exclusive to `AgencyPrincipal`; the wrong role for the
        supplied `action` is refused with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/the_agency_principal_cannot_sign_for_the_household
        """
        set_clock("2026-08-01T00:00:00Z")
        household = create_household()

        validate_error(
            api_client.confidentiality_agreement(
                household["id"], sign_agreement_payload(), PRINCIPAL
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        stored = read_client(household)
        assert stored["confidentiality_agreement_status"] == "UNSIGNED"
        assert stored["signatory_name"] is None
        assert stored["version"] == 1

    def test_09_the_household_may_not_countersign_its_own_agreement(self):
        """A permitted caller of the endpoint is still refused the other half.

        PRD §2.1: "Two operations are further partitioned by the value in the body
        rather than by the endpoint. On the confidentiality-agreement endpoint, an
        `action` of `SIGN` is exclusive to the `Client` role and an `action` of
        `COUNTERSIGN` is exclusive to `AgencyPrincipal`; the wrong role for the
        supplied `action` is refused with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/the_household_cannot_countersign_its_own_agreement
        """
        set_clock("2026-08-01T00:00:00Z")
        household = create_household()
        headers = make_client_headers(household["id"])
        validate_success(
            api_client.confidentiality_agreement(
                household["id"], sign_agreement_payload(), headers
            )
        )

        validate_error(
            api_client.confidentiality_agreement(
                household["id"], countersign_agreement_payload(), headers
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        stored = read_client(household)
        assert stored["confidentiality_agreement_status"] == "SIGNED"
        assert stored["status"] == "PROSPECT"
        assert stored["countersigned_at"] is None


class TestCarveOutsFromTheReadGrants:
    def test_10_the_candidate_may_read_the_placement_but_not_the_ledger(self):
        """The refusal is scoped to the household's money, not to the role.

        PRD §4: "| GET | `/clients/{id}/ledger-entries` | Read a household's
        append-only ledger in sequence order. | `AgencyPrincipal`,
        `BillingAdministrator`, `ComplianceOfficer`, `Client` |"

        Design: Corner/rbac/a_candidate_cannot_read_the_household_ledger
        """
        scenario = setup_active_placement()
        candidate_headers = make_candidate_headers(scenario["candidate"]["id"])

        validate_error(
            api_client.list_ledger_entries(
                scenario["client"]["id"], candidate_headers
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        placement = validate_success(
            api_client.get_placement(scenario["placement"]["id"], candidate_headers)
        )
        assert placement["id"] == scenario["placement"]["id"]

    def test_11_the_consultant_is_carved_out_of_the_payroll_handoff(self):
        """A blanket read grant has exceptions, and this is one of them.

        PRD §4: "| GET | `/payroll-handoffs/{id}` | Read one payroll and tax
        guidance handoff. | `AgencyPrincipal`, `BillingAdministrator`,
        `ComplianceOfficer`, `Client` |"

        Design: Corner/rbac/the_placement_consultant_cannot_read_the_payroll_handoff
        """
        scenario = setup_active_placement()
        handoff = prepare_payroll_handoff(scenario["placement"])

        validate_error(
            api_client.get_payroll_handoff(handoff["id"], CONSULTANT),
            "ERR_UNAUTHORIZED",
            403,
        )

        read = validate_success(
            api_client.get_payroll_handoff(handoff["id"], CASE_OPENER)
        )
        assert read["status"] == "PREPARED"


class TestSharedCounterpartyOperations:
    def test_12_both_counterparties_answer_the_same_term(self):
        """Each answer is attributed to its own side, which is what alternation
        needs.

        PRD §3.5: "The two counterparties then answer, and only they may:
        responding is exclusive to the `Client` and `Candidate` roles."

        PRD §3.5: "Each counter increments `round_no` by 1, overwrites `live_in`,
        `weekly_hours`, `days_off_per_week`, `private_quarters` and
        `imputed_accommodation_cents` with the supplied counter values, sets
        `last_responder_role` to `CLIENT` or `CANDIDATE` according to the
        responding role, and increments `AccommodationTerm.version`."

        Design: Corner/rbac/both_the_household_and_the_candidate_may_answer_a_term
        """
        scenario = setup_scenario(stage="term_proposed")
        countered = respond_to_term(
            scenario["term"], scenario["client_headers"], "COUNTER", weekly_hours=42
        )
        assert countered["status"] == "COUNTERED"
        assert countered["round_no"] == 2
        assert countered["last_responder_role"] == "CLIENT"

        accepted = validate_success(
            api_client.respond_accommodation_term(
                scenario["term"]["id"],
                respond_accommodation_term_payload("ACCEPT"),
                scenario["candidate_headers"],
            )
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["weekly_hours"] == 42

        assert read_term(scenario["term"])["status"] == "ACCEPTED"
        assert read_requisition(scenario["requisition"])["status"] == "TRIALING"


class TestSeparationOfDuties:
    def test_13_the_recorder_of_a_reference_may_not_verify_it(self):
        """Same desk, same grant, same human — and that is the violation.

        PRD §2.10: "When a `VettingSpecialist` records the outcome of contacting a
        reference, the acting `X-User-ID` must differ from that reference's stored
        `created_by_user_id`; when a `ComplianceOfficer` resolves an enforcement
        case, the acting `X-User-ID` must differ from that case's stored
        `opened_by_user_id`. A violation of either is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/the_specialist_who_recorded_a_reference_cannot_verify_it
        """
        set_clock("2026-08-01T00:00:00Z")
        candidate = register_candidate()
        reference = record_reference(candidate)
        assert reference["created_by_user_id"] == VETTING_RECORDER_USER_ID

        validate_error(
            api_client.verify_reference_check(
                reference["id"], verify_reference_payload("VERIFIED"), RECORDER
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

        stored = read_reference(reference)
        assert stored["status"] == "PENDING"
        assert stored["verified_by_user_id"] is None
        assert read_candidate(candidate)["verified_reference_count"] == 0

    def test_14_a_second_specialist_is_exactly_what_the_rule_wants(self):
        """Only the user id changes, and the same call now succeeds.

        PRD §2.10: "The maker may not be the checker, and the rule is about the
        human identifier, not about the role — a second `VettingSpecialist` is
        exactly what the rule demands."

        Design: Corner/rbac/a_second_specialist_may_verify_the_same_reference
        """
        set_clock("2026-08-01T00:00:00Z")
        candidate = register_candidate()
        reference = record_reference(candidate)

        verified = validate_success(
            api_client.verify_reference_check(
                reference["id"], verify_reference_payload("VERIFIED"), VERIFIER
            )
        )
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == VETTING_VERIFIER_USER_ID
        assert verified["created_by_user_id"] == VETTING_RECORDER_USER_ID

        stored = read_candidate(candidate)
        assert stored["verified_reference_count"] == 1
        assert stored["vetting_status"] == "SCREENING"

    def test_15_the_officer_who_opened_a_case_may_not_resolve_it(self):
        """The same officer was allowed to investigate, so only the decision is
        segregated.

        PRD §3.9: "Resolution is separated from filing by duty: it is performed by
        a `ComplianceOfficer` whose `X-User-ID` must differ from the case's
        `opened_by_user_id`, or the request is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/the_officer_who_opened_a_case_cannot_resolve_it
        """
        scenario = setup_investigating_case()
        assert scenario["case"]["status"] == "INVESTIGATING"
        assert scenario["case"]["investigation_opened_at"] is not None

        validate_error(
            api_client.resolve_non_solicitation_case(
                scenario["case"]["id"],
                resolve_case_payload("SUBSTANTIATE"),
                CASE_OPENER,
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

        stored = read_case(scenario["case"])
        assert stored["status"] == "INVESTIGATING"
        assert stored["penalty_cents"] is None
        assert read_client(scenario["client"])["status"] == "ONBOARDED"

        resolved = validate_success(
            api_client.resolve_non_solicitation_case(
                scenario["case"]["id"],
                resolve_case_payload("SUBSTANTIATE"),
                CASE_RESOLVER,
            )
        )
        assert resolved["status"] == "SUBSTANTIATED"
