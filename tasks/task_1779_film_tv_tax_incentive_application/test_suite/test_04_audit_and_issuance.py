"""CPA audit workflow and credit issuance gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_qualified_entries,
    add_spend_entry,
    approve_application,
    assert_program_ledger_invariant,
    attest_audit,
    claim_application,
    create_application,
    create_production,
    decide_audit,
    disqualify_entry,
    engage_audit,
    get_application,
    get_certificate_by_application,
    get_program,
    issue_credit,
    make_reviewer_headers,
    open_program,
    qualify_entry,
    register_company,
    register_verified_vendor,
    run_accepted_audit,
    setup_approved_application,
    setup_issued_certificate,
    submit_application,
    submit_audit_draft,
    raise_exceptions,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER1 = TEST_USERS["reviewer1_headers"]
CPA1 = TEST_USERS["cpa1_headers"]
CPA2 = TEST_USERS["cpa2_headers"]


class TestAuditEngagement:
    def test_second_audit_package_rejected_while_active(self, api):
        """PRD §3.5: "engagement is rejected with `ERR_INVALID_STATE_TRANSITION`
        when the application is in any other status, and with
        `ERR_AUDIT_PACKAGE_EXISTS` when the application already has a package in
        any status other than `REJECTED` — at most one live package exists per
        application, which is why filtering the audit-package list by
        `application_id` (or by `status`) returns an array of zero or one."

        Design: Corner/validations/second_audit_package_rejected_while_active
        """
        scenario = setup_approved_application()
        engage_audit(scenario.application, "cpa-1")

        resp = api.create_audit_package(
            {"application_id": scenario.application["id"]}, CPA2)
        validate_error(resp, ApiErrorId.ERR_AUDIT_PACKAGE_EXISTS)
        data, _ = validate_paginated(api.list_audit_packages(
            ADMIN, params={"application_id": scenario.application["id"]}))
        assert len(data) == 1, "still exactly one package on the application"

    def test_reviewer_cannot_create_audit_package_forbidden(self, api):
        """PRD §2.1: "A request whose role is not on the target endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "| POST | `/api/audit-packages` | Engage a CPA audit package on
        an `APPROVED` application | CPAAuditor |"

        Design: Corner/rbac/reviewer_cannot_create_audit_package_forbidden
        """
        scenario = setup_approved_application()
        resp = api.create_audit_package(
            {"application_id": scenario.application["id"]}, REVIEWER1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        data, _ = validate_paginated(api.list_audit_packages(
            ADMIN, params={"application_id": scenario.application["id"]}))
        assert data == []

    def test_rejected_audit_package_frees_replacement(self, api):
        """PRD §3.5: "A decision `outcome` of `REJECT`, optionally justified by a
        `decision_reason`, moves the package to the terminal `REJECTED` state and
        leaves the application `APPROVED`; because a `REJECTED` package no longer
        blocks creation, a fresh audit engagement may follow."

        Design: Corner/state_machines/rejected_audit_package_frees_replacement
        """
        scenario = setup_approved_application()
        package = engage_audit(scenario.application, "cpa-1")
        submit_audit_draft(package, "cpa-1")
        package = attest_audit(package, 40_000_000, 162_500_000, "cpa-1")
        rejected = decide_audit(package, "REJECT", "reviewer-3",
                                decision_reason="ledger unreconciled")
        assert rejected["status"] == "REJECTED"
        assert get_application(scenario.application)["status"] == "APPROVED"

        replacement = validate_success(api.create_audit_package(
            {"application_id": scenario.application["id"]}, CPA2), 201)
        assert replacement["status"] == "ENGAGED"
        assert replacement["cpa_user_id"] == "cpa-2"
        data, _ = validate_paginated(api.list_audit_packages(
            ADMIN, params={"application_id": scenario.application["id"]}))
        statuses = sorted(p["status"] for p in data)
        assert statuses == ["ENGAGED", "REJECTED"]


class TestAttestationGates:
    def test_attest_with_pending_entries_rejected(self, api):
        """PRD §3.5: "Two gates apply: `documentation_complete` must be true in
        the attestation request itself (`ERR_AUDIT_PACKAGE_INCOMPLETE`), and no
        spend entry of the application may still stand `PENDING_REVIEW`
        (`ERR_SPEND_ENTRIES_PENDING`)."

        Design: Corner/validations/attest_with_pending_entries_rejected
        """
        scenario = setup_approved_application()
        vendor = register_verified_vendor(scenario.production, scenario.company)
        e1 = add_spend_entry(scenario.application, vendor, scenario.company,
                             category="BTL", amount_cents=50_000_000,
                             spend_date="2026-10-05T00:00:00Z")
        e2 = add_spend_entry(scenario.application, vendor, scenario.company,
                             category="BTL", amount_cents=50_000_000,
                             spend_date="2026-10-06T00:00:00Z")
        qualify_entry(e1)
        package = engage_audit(scenario.application, "cpa-1")
        submit_audit_draft(package, "cpa-1")

        blocked = api.attest_audit_package(
            package["id"],
            {"attested_atl_cents": 0, "attested_btl_cents": 100_000_000,
             "documentation_complete": True},
            CPA1)
        validate_error(blocked, ApiErrorId.ERR_SPEND_ENTRIES_PENDING)
        current = validate_success(api.get_audit_package(package["id"], ADMIN), 200)
        assert current["status"] == "DRAFT_SUBMITTED"

        disqualify_entry(e2, reason="out-of-period invoice")
        ok = api.attest_audit_package(
            package["id"],
            {"attested_atl_cents": 0, "attested_btl_cents": 50_000_000,
             "documentation_complete": True},
            CPA1)
        attested = validate_success(ok, 200)
        assert attested["status"] == "ATTESTED"
        assert attested["attested_at"] is not None

    def test_attest_incomplete_documentation_rejected(self, api):
        """PRD §3.5: "Two gates apply: `documentation_complete` must be true in
        the attestation request itself (`ERR_AUDIT_PACKAGE_INCOMPLETE`), and no
        spend entry of the application may still stand `PENDING_REVIEW`
        (`ERR_SPEND_ENTRIES_PENDING`)."

        Design: Corner/validations/attest_incomplete_documentation_rejected
        """
        scenario = setup_approved_application()
        package = engage_audit(scenario.application, "cpa-1")
        submit_audit_draft(package, "cpa-1", documentation_complete=False)

        resp = api.attest_audit_package(
            package["id"],
            {"attested_atl_cents": 40_000_000, "attested_btl_cents": 162_500_000,
             "documentation_complete": False},
            CPA1)
        validate_error(resp, ApiErrorId.ERR_AUDIT_PACKAGE_INCOMPLETE)
        current = validate_success(api.get_audit_package(package["id"], ADMIN), 200)
        assert current["status"] == "DRAFT_SUBMITTED"
        assert current["attested_at"] is None

    def test_audit_decision_by_engaged_cpa_rejected_sod(self, api):
        """PRD §2.11: "An audit package may be accepted or rejected only by a
        `FilmOfficeReviewer` whose `X-User-ID` differs from the package's
        `cpa_user_id`. Either violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/audit_decision_by_engaged_cpa_rejected_sod
        """
        scenario = setup_approved_application()
        package = engage_audit(scenario.application, "cpa-1")
        submit_audit_draft(package, "cpa-1")
        attest_audit(package, 40_000_000, 162_500_000, "cpa-1")

        resp = api.decide_audit_package(
            package["id"], {"outcome": "ACCEPT"},
            make_reviewer_headers("cpa-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        current = validate_success(api.get_audit_package(package["id"], ADMIN), 200)
        assert current["status"] == "ATTESTED"


class TestAuditReworkCycle:
    def _setup_draft_submitted(self, api):
        scenario = setup_approved_application()
        package = engage_audit(scenario.application, "cpa-1")
        package = submit_audit_draft(package, "cpa-1")
        return scenario, package

    def test_audit_exceptions_rework_cycle_counts_exceptions(self, api):
        """PRD §3.5: "A `FilmOfficeReviewer` who finds problems raises
        exceptions, carrying `exception_notes` with the request, which returns
        the package to `FIELDWORK` and increments `exception_count` by one. The
        rework cycle between `DRAFT_SUBMITTED` and `FIELDWORK` is unbounded."

        Design: Difficulty/non_linear_state_machine/audit_exceptions_rework_cycle
        """
        _scenario, package = self._setup_draft_submitted(api)
        first = raise_exceptions(package, "missing payroll registers",
                                 reviewer_user_id="reviewer-1")
        assert first["status"] == "FIELDWORK"
        assert first["exception_count"] == 1
        resubmitted = submit_audit_draft(first, "cpa-1")
        assert resubmitted["status"] == "DRAFT_SUBMITTED"
        second = raise_exceptions(resubmitted, "residency affidavits incomplete",
                                  reviewer_user_id="reviewer-2")
        assert second["status"] == "FIELDWORK"
        assert second["exception_count"] == 2, (
            "each raise-exceptions transition increments exception_count by one")

    def test_audit_rework_cycle_completes_to_accepted_and_locks_final(self, api):
        """PRD §3.5: "A decision `outcome` of `ACCEPT` moves the package to the
        terminal `ACCEPTED` state and locks the application's
        `final_credit_cents` — null until this moment — to the FINAL variant of
        the credit computation over the attested above- and below-the-line sums
        (§3.9); the application's `recomputed_credit_cents` is refreshed on the
        same pass."

        Design: Difficulty/non_linear_state_machine/audit_exceptions_rework_cycle
        """
        scenario, package = self._setup_draft_submitted(api)
        package = raise_exceptions(package, "missing payroll registers",
                                   reviewer_user_id="reviewer-1")
        package = submit_audit_draft(package, "cpa-1")
        package = raise_exceptions(package, "residency affidavits incomplete",
                                   reviewer_user_id="reviewer-2")
        package = submit_audit_draft(package, "cpa-1")
        package = attest_audit(package, 40_000_000, 162_500_000, "cpa-1")
        accepted = decide_audit(package, "ACCEPT", "reviewer-3")
        assert accepted["status"] == "ACCEPTED"
        assert accepted["exception_count"] == 2

        application = get_application(scenario.application)
        assert application["final_credit_cents"] == 60_750_000, (
            "FINAL variant over attested 40000000 / 162500000: capped "
            "202500000 at the elevated 0.30 rate")


class TestDualVariantCredit:
    def _setup_divergent_attestation(self, api):
        """System sums atl 40M / btl 162.5M; attested sums 38M / 150M; package
        ATTESTED but not yet decided."""
        scenario = setup_approved_application()
        vendor = register_verified_vendor(scenario.production, scenario.company)
        add_qualified_entries(scenario.application, vendor, scenario.company, [
            {"category": "ATL", "amount_cents": 40_000_000,
             "spend_date": "2026-10-05T00:00:00Z",
             "external_invoice_ref": "INV-ATL-001"},
            {"category": "BTL", "is_resident_labor": True,
             "amount_cents": 100_000_000, "spend_date": "2026-10-12T00:00:00Z",
             "external_invoice_ref": "INV-BTL-002"},
            {"category": "BTL", "amount_cents": 60_000_000,
             "spend_date": "2026-10-19T00:00:00Z",
             "external_invoice_ref": "INV-BTL-003"},
        ])
        package = engage_audit(scenario.application, "cpa-1")
        submit_audit_draft(package, "cpa-1")
        attest_audit(package, 38_000_000, 150_000_000, "cpa-1")
        return scenario

    def test_provisional_variant_uses_system_sums(self, api):
        """PRD §3.9: "The `PROVISIONAL` variant — the default — sources the
        system-qualified sums built by entry reviews."
        PRD §3.9: "Both variants run the same pipeline: apply the above-the-line
        cap of §3.4 to reach the capped total; apply the minimum gate, under
        which a capped total below the program's `minimum_qualified_spend_cents`
        yields a credit of zero and a false `meets_minimum`; select the tier on
        the post-cap total, where a capped total of at least the program's
        `elevated_tier_threshold_cents` — boundary inclusive — earns
        `base_rate_elevated` and anything below it earns `base_rate_standard`;
        and compute the credit as the capped total multiplied by the selected
        rate, rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_credit_divergence
        """
        scenario = self._setup_divergent_attestation(api)
        estimate = validate_success(api.get_credit_estimate(
            scenario.application["id"], REVIEWER1,
            params={"variant": "PROVISIONAL"}), 200)
        assert estimate["variant"] == "PROVISIONAL"
        assert estimate["atl_qualified_cents"] == 40_000_000
        assert estimate["btl_qualified_cents"] == 162_500_000
        assert estimate["capped_total_qualified_cents"] == 202_500_000, (
            "ATL cap floor(0.40 * 202500000) = 81000000 does not bind")
        assert estimate["applied_rate"] == 0.30
        assert estimate["credit_cents"] == 60_750_000
        assert estimate["meets_minimum"] is True

    def test_final_variant_uses_attested_sums_and_diverges(self, api):
        """PRD §3.9: "The `FINAL` variant sources the CPA-attested sums
        `attested_atl_cents` and `attested_btl_cents` and requires an audit
        package standing `ATTESTED` or `ACCEPTED`; without one the read is
        rejected with `ERR_AUDIT_NOT_ACCEPTED`. Identical inputs can yield a
        different credit — even a different rate tier — when the attested totals
        differ from the system sums."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_credit_divergence
        """
        scenario = self._setup_divergent_attestation(api)
        provisional = validate_success(api.get_credit_estimate(
            scenario.application["id"], REVIEWER1,
            params={"variant": "PROVISIONAL"}), 200)
        final = validate_success(api.get_credit_estimate(
            scenario.application["id"], REVIEWER1,
            params={"variant": "FINAL"}), 200)
        assert final["variant"] == "FINAL"
        assert final["atl_qualified_cents"] == 38_000_000
        assert final["btl_qualified_cents"] == 150_000_000
        assert final["capped_total_qualified_cents"] == 188_000_000, (
            "pre-cap 188000000; ATL cap 75200000 does not bind")
        assert final["applied_rate"] == 0.25, "188000000 is below the tier"
        assert final["credit_cents"] == 47_000_000
        assert final["meets_minimum"] is True
        assert provisional["credit_cents"] != final["credit_cents"]
        assert provisional["applied_rate"] != final["applied_rate"], (
            "the two variants diverge in both amount and rate tier on the "
            "same ledger at the same instant")

    def test_credit_estimate_final_requires_attested_package(self, api):
        """PRD §3.9: "The `FINAL` variant sources the CPA-attested sums
        `attested_atl_cents` and `attested_btl_cents` and requires an audit
        package standing `ATTESTED` or `ACCEPTED`; without one the read is
        rejected with `ERR_AUDIT_NOT_ACCEPTED`."

        Design: Corner/calculations/credit_estimate_final_requires_attested_package
        """
        scenario = setup_approved_application()
        resp = api.get_credit_estimate(
            scenario.application["id"], REVIEWER1, params={"variant": "FINAL"})
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_ACCEPTED)


class TestIssueCreditGates:
    def test_issue_credit_blocked_while_audit_only_attested(self, api):
        """PRD §3.6: "An audit package for the application must stand `ACCEPTED`
        (`ERR_AUDIT_NOT_ACCEPTED`)."

        Design: Difficulty/cross_entity_state_dependency/issue_credit_requires_audit_accepted
        """
        scenario = setup_approved_application()
        package = engage_audit(scenario.application, "cpa-1")
        submit_audit_draft(package, "cpa-1")
        attest_audit(package, 40_000_000, 162_500_000, "cpa-1")

        resp = api.issue_credit(scenario.application["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_ACCEPTED)
        assert get_certificate_by_application(scenario.application) is None, (
            "no certificate may materialize while the audit is not ACCEPTED")

    def test_issue_credit_unblocked_after_audit_accepted(self, api):
        """PRD §3.6: "The same operation debits the program ledger per §2.7 —
        `remaining_cap_cents` falls by the final credit and
        `allocated_credit_cents` rises by it — pins the application's
        `recomputed_credit_cents` to `final_credit_cents` at that instant, and
        moves the application to `CREDIT_ISSUED`."
        PRD §2.7: "Each jurisdiction program behaves as a credit ledger governed
        by one invariant: `allocated_credit_cents` plus `remaining_cap_cents`
        always equals `annual_cap_cents`."

        Design: Difficulty/cross_entity_state_dependency/issue_credit_requires_audit_accepted
        """
        scenario = setup_approved_application()
        run_accepted_audit(scenario.application, 40_000_000, 162_500_000)

        certificate = issue_credit(scenario.application)
        assert certificate["issued_amount_cents"] == 60_750_000
        application = get_application(scenario.application)
        assert application["status"] == "CREDIT_ISSUED"
        assert application["recomputed_credit_cents"] == 60_750_000
        program = get_program(scenario.program)
        assert program["allocated_credit_cents"] == 60_750_000
        assert program["remaining_cap_cents"] == 39_250_000
        assert_program_ledger_invariant(program)

    def test_second_certificate_issue_rejected_already_issued(self, api):
        """PRD §3.6: "Issuing credit against an application requires the
        application to stand `APPROVED`; an issuance request against an
        application that is already `CREDIT_ISSUED` is mapped explicitly to
        `ERR_CERTIFICATE_ALREADY_ISSUED` rather than a generic state-transition
        error, and the same error answers any attempt to create a second
        certificate for one application."

        Design: Corner/validations/second_certificate_issue_rejected_already_issued
        """
        scenario = setup_issued_certificate()
        resp = api.issue_credit(scenario.application["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_ALREADY_ISSUED)
        data, _ = validate_paginated(api.list_certificates(
            ADMIN, params={"application_id": scenario.application["id"]}))
        assert len(data) == 1, "still exactly one certificate"

    def test_approve_below_minimum_estimate_rejected(self, api):
        """PRD §3.3: "Approval additionally requires the application's
        `estimated_qualified_spend_cents` to be at least the program's
        `minimum_qualified_spend_cents`; otherwise approval is rejected with
        `ERR_MINIMUM_SPEND_NOT_MET`."

        Design: Corner/validations/approve_below_minimum_estimate_rejected
        """
        program = open_program()
        company = register_company()
        production = create_production(company, title="Tiny Pilot",
                                       production_type="COMMERCIAL",
                                       total_budget_cents=8_000_000)
        application = create_application(
            production, program, estimated_qualified_spend_cents=5_000_000)
        submit_application(application, company)
        claim_application(application)

        resp = api.approve_application(application["id"],
                                       make_reviewer_headers("reviewer-2"))
        validate_error(resp, ApiErrorId.ERR_MINIMUM_SPEND_NOT_MET)
        assert get_application(application)["status"] == "UNDER_REVIEW"

    def test_issue_credit_below_minimum_attested_rejected(self, api):
        """PRD §3.6: "The locked `final_credit_cents` must be greater than zero
        — which is precisely the condition that the attested capped total meets
        the program's `minimum_qualified_spend_cents`
        (`ERR_MINIMUM_SPEND_NOT_MET`)"
        PRD §3.9: "apply the minimum gate, under which a capped total below the
        program's `minimum_qualified_spend_cents` yields a credit of zero and a
        false `meets_minimum`"

        Design: Corner/validations/issue_credit_below_minimum_attested_rejected
        """
        scenario = setup_approved_application(
            estimated_qualified_spend_cents=20_000_000, title="Tiny Pilot",
            production_type="COMMERCIAL", total_budget_cents=20_000_000)
        run_accepted_audit(scenario.application, 0, 8_000_000)

        estimate = validate_success(api.get_credit_estimate(
            scenario.application["id"], REVIEWER1, params={"variant": "FINAL"}),
            200)
        assert estimate["credit_cents"] == 0, (
            "attested capped total 8000000 is below the 10000000 minimum")
        assert estimate["meets_minimum"] is False

        resp = api.issue_credit(scenario.application["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_MINIMUM_SPEND_NOT_MET)
        assert get_certificate_by_application(scenario.application) is None
        assert get_application(scenario.application)["status"] == "APPROVED"


class TestCapExhaustion:
    def _setup_nm_exact_fit(self, api):
        """NM-variant program (annual cap == the A application's final credit)
        with two ACCEPTED-audit applications: A final 37,500,000 (exact fit),
        B final 5,000,000."""
        program = open_program(
            jurisdiction_code="NM", program_name="NM Film Credit FY27",
            annual_cap_cents=37_500_000,
            elevated_tier_threshold_cents=50_000_000)
        company = register_company()
        production_a = create_production(company, title="Desert Rose",
                                         total_budget_cents=300_000_000)
        production_b = create_production(company, title="Mesilla Short",
                                         production_type="COMMERCIAL",
                                         total_budget_cents=80_000_000)
        app_a = create_application(production_a, program,
                                   estimated_qualified_spend_cents=150_000_000)
        app_b = create_application(production_b, program,
                                   estimated_qualified_spend_cents=20_000_000)
        for app in (app_a, app_b):
            submit_application(app, company)
            claim_application(app)
        app_a = approve_application(app_a)
        app_b = approve_application(app_b)
        run_accepted_audit(app_a, 20_000_000, 105_000_000)
        run_accepted_audit(app_b, 0, 20_000_000)
        return program, company, app_a, app_b

    def test_issue_credit_exact_cap_fit_succeeds(self, api):
        """PRD §3.6: "and it must not exceed the program's
        `remaining_cap_cents`, with an exact fit allowed
        (`ERR_PROGRAM_CAP_EXHAUSTED`)."
        PRD §2.7: "Credit issuance debits the ledger — the remaining cap falls
        by the issued amount and the allocated total rises by the same amount."

        Design: Difficulty/boundary_precision_check/issue_credit_exact_cap_fit
        """
        program, _company, app_a, _app_b = self._setup_nm_exact_fit(api)
        certificate = validate_success(
            api.issue_credit(app_a["id"], ADMIN), 201)
        assert certificate["issued_amount_cents"] == 37_500_000, (
            "final credit 125000000 capped * 0.30 elevated == the remaining cap")
        after = get_program(program)
        assert after["remaining_cap_cents"] == 0
        assert after["allocated_credit_cents"] == 37_500_000
        assert_program_ledger_invariant(after)

    def test_issue_credit_past_exhausted_cap_rejected(self, api):
        """PRD §3.6: "and it must not exceed the program's
        `remaining_cap_cents`, with an exact fit allowed
        (`ERR_PROGRAM_CAP_EXHAUSTED`)."

        Design: Difficulty/boundary_precision_check/issue_credit_exact_cap_fit
        """
        program, _company, app_a, app_b = self._setup_nm_exact_fit(api)
        validate_success(api.issue_credit(app_a["id"], ADMIN), 201)
        assert get_program(program)["remaining_cap_cents"] == 0

        resp = api.issue_credit(app_b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CAP_EXHAUSTED)
        assert get_certificate_by_application(app_b) is None

    def test_safety_beats_fiscal_on_issue_credit_error_id(self, api):
        """PRD §2.9: "When a single request violates several rules, the failure
        that surfaces is the one belonging to the earliest category in the
        following evaluation order:"
        PRD §2.9: "8. **Compliance gates** — vendor residency verified at spend
        qualification, an accepted audit package at issuance, documentation
        complete and no pending entries at attestation, and the
        segregation-of-duties pairings (`ERR_VENDOR_RESIDENCY_NOT_VERIFIED`,
        `ERR_AUDIT_NOT_ACCEPTED`, `ERR_AUDIT_PACKAGE_INCOMPLETE`,
        `ERR_SPEND_ENTRIES_PENDING`, `ERR_SEGREGATION_OF_DUTIES`)."
        PRD §2.9: "12. **Fiscal checks** — minimum spend gates, program cap
        sufficiency, the transfer price floor, amounts against remaining
        balances, and the clawback base against the issued amount
        (`ERR_MINIMUM_SPEND_NOT_MET`, `ERR_PROGRAM_CAP_EXHAUSTED`,
        `ERR_TRANSFER_PRICE_BELOW_FLOOR`, `ERR_AMOUNT_EXCEEDS_REMAINING`,
        `ERR_CLAWBACK_EXCEEDS_EXPOSURE`)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_issue_credit
        """
        program = open_program(
            jurisdiction_code="NM", program_name="NM Film Credit FY27",
            annual_cap_cents=30_000_000,
            elevated_tier_threshold_cents=50_000_000)
        company = register_company()
        production = create_production(company, title="Desert Rose",
                                       total_budget_cents=300_000_000)
        application = create_application(
            production, program, estimated_qualified_spend_cents=150_000_000)
        submit_application(application, company)
        claim_application(application)
        application = approve_application(application)
        package = engage_audit(application, "cpa-1")
        submit_audit_draft(package, "cpa-1")
        # Attested totals would produce a 37500000 FINAL credit > 30000000 cap,
        # but the package is only ATTESTED — the compliance gate fires first.
        attest_audit(package, 20_000_000, 105_000_000, "cpa-1")

        resp = api.issue_credit(application["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_ACCEPTED)

    def test_safety_beats_fiscal_on_issue_credit_no_mutation(self, api):
        """PRD §2.9: "8. **Compliance gates** — vendor residency verified at
        spend qualification, an accepted audit package at issuance,
        documentation complete and no pending entries at attestation, and the
        segregation-of-duties pairings (`ERR_VENDOR_RESIDENCY_NOT_VERIFIED`,
        `ERR_AUDIT_NOT_ACCEPTED`, `ERR_AUDIT_PACKAGE_INCOMPLETE`,
        `ERR_SPEND_ENTRIES_PENDING`, `ERR_SEGREGATION_OF_DUTIES`)."
        PRD §3.6: "An audit package for the application must stand `ACCEPTED`
        (`ERR_AUDIT_NOT_ACCEPTED`)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_issue_credit
        """
        program = open_program(
            jurisdiction_code="NM", program_name="NM Film Credit FY27",
            annual_cap_cents=30_000_000,
            elevated_tier_threshold_cents=50_000_000)
        company = register_company()
        production = create_production(company, title="Desert Rose",
                                       total_budget_cents=300_000_000)
        application = create_application(
            production, program, estimated_qualified_spend_cents=150_000_000)
        submit_application(application, company)
        claim_application(application)
        application = approve_application(application)
        package = engage_audit(application, "cpa-1")
        submit_audit_draft(package, "cpa-1")
        attest_audit(package, 20_000_000, 105_000_000, "cpa-1")

        api.issue_credit(application["id"], ADMIN)
        assert get_certificate_by_application(application) is None, (
            "no certificate materializes on the dual-failure request")
        assert get_application(application)["status"] == "APPROVED"
        program_after = get_program(program)
        assert program_after["remaining_cap_cents"] == 30_000_000
        assert program_after["allocated_credit_cents"] == 0
