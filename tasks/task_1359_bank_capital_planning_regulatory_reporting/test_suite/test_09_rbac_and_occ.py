"""Access control and optimistic concurrency: header validation, role
authorization, segregation of duties, and expected_bank_version staleness."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_exposure,
    add_instrument,
    advance_clock_past,
    bump_bank_version,
    create_bank,
    create_period,
    create_bank_payload,
    create_prepared_call_report,
    create_proposed_distribution,
    create_proposed_sub_debt,
    create_reporting_period_payload,
    setup_accepted_report,
    setup_distributable_bank,
    setup_plan_in_supervisory_review,
    make_capital_analyst_headers,
)


class TestHeaderValidation(object):
    def test_missing_auth_headers_returns_400(self, api, system_operator_headers):
        """PRD §2.1: "A request missing either header, or presenting a
        malformed value, is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        bank = create_bank("CH-AUT-001", legal_name="AuthBank")
        res = api._request("GET", f"/banks/{bank['id']}", headers={})
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)

    def test_missing_role_header_returns_400(self, api, system_operator_headers):
        """PRD §2.1: "Every request to the API must carry two identity
        headers: X-User-ID, identifying the acting user, and X-User-Role,
        declaring the capacity in which they act. A request missing either
        header, or presenting a malformed value, is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        bank = create_bank("CH-AUT-002", legal_name="AuthBank2")
        res = api._request("GET", f"/banks/{bank['id']}", headers={"X-User-ID": "analyst-1"})
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestRoleAuthorization(object):
    def test_regulator_cannot_create_bank(self, api, regulator_reviewer_headers):
        """PRD §2.1: "A request whose role is valid but not authorized for
        the target endpoint is rejected with ERR_FORBIDDEN_FOR_ROLE
        (HTTP 403)." and "SystemOperator is the operational superuser: it
        alone creates banks and advances the logical clock"

        Design: Corner/roles/regulator_cannot_create_bank
        """
        res = api.create_bank(
            create_bank_payload(legal_name="RbacDenyBank", charter_id="CH-RBD-001"),
            regulator_reviewer_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_forbidden_role_for_regulator_endpoint(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §4: the row "| POST | `/banks/{bankId}/capital-plans/{planId}/regulator_approve` | Regulator approves plan | RegulatorReviewer |"
        grants regulator_approve to RegulatorReviewer alone, and PRD §2.1:
        "A request whose role is valid but not authorized for the target
        endpoint is rejected with ERR_FORBIDDEN_FOR_ROLE (HTTP 403)."

        Design: Corner/validations/forbidden_role_for_regulator_endpoint
        """
        bank, period, report, scenario, plan = setup_plan_in_supervisory_review(
            "CH-RBC-001", 10_000_000_000, 100_000_000_000, scenario_code="BASE-RBC"
        )
        assert plan["status"] == "SUPERVISORY_REVIEW"
        res = api.regulator_approve_plan(bank["id"], plan["id"], capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_external_auditor_read_only(self, api, system_operator_headers, external_auditor_headers):
        """PRD §2.1: "All five roles may use every read endpoint; write
        privileges are enumerated per endpoint in §4." and "ExternalAuditor is
        a read-only role for compliance review."

        Design: Corner/roles/external_auditor_read_only
        """
        bank = create_bank("CH-AUD-001", legal_name="AudBank")
        got = validate_success(api.get_bank(bank["id"], external_auditor_headers))
        assert got["id"] == bank["id"]
        res = api.create_reporting_period(
            bank["id"],
            create_reporting_period_payload(
                period_end_date="2026-06-30", period_year=2026, period_quarter="Q2"
            ),
            external_auditor_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_board_approver_cannot_prepare_call_report(self, api, system_operator_headers,
                                                       capital_analyst_headers, board_approver_headers):
        """PRD §4: the row "| POST | `/banks/{bankId}/reporting-periods/{periodId}/call-reports/{reportId}/prepare` | Run RWA, capital, ratio, and edit-check computations | CapitalAnalyst |"
        grants prepare to CapitalAnalyst alone, and PRD §2.1: "A request whose
        role is valid but not authorized for the target endpoint is rejected
        with ERR_FORBIDDEN_FOR_ROLE (HTTP 403)."

        Design: Corner/roles/board_approver_cannot_prepare_call_report
        """
        bank = create_bank("CH-BRD-001", legal_name="BrdBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(bank["id"], period["id"], exposure_at_default_cents=100_000_000)
        add_instrument(bank["id"], outstanding_amount_cents=10_000_000)
        report = validate_success(
            api.create_call_report(bank["id"], period["id"], {}, capital_analyst_headers),
            201,  # PRD §4: creation operations return 201 Created
        )
        res = api.prepare_call_report(bank["id"], period["id"], report["id"], board_approver_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestSegregationOfDuties(object):
    def test_segregation_of_duties_on_call_report_submit(self, api, system_operator_headers,
                                                         capital_analyst_headers):
        """PRD §3.3: "Submission is a segregation-of-duties checkpoint: the
        analyst who submits a validated report must not be the analyst
        recorded as its prepared_by_user_id, and a matching identity is
        rejected with ERR_SEGREGATION_OF_DUTIES_VIOLATION (HTTP 409)."

        Design: Corner/validations/segregation_of_duties_on_call_report_submit
        """
        bank = create_bank("CH-SOD-001", legal_name="SoDBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(bank["id"], period["id"], exposure_at_default_cents=100_000_000)
        add_instrument(bank["id"], outstanding_amount_cents=10_000_000)
        # Prepare and submit as the SAME operator id.
        report = create_prepared_call_report(
            bank["id"], period["id"], preparer_user_id="analyst-prep-1"
        )
        assert report["status"] == "VALIDATED"
        # Move the period unambiguously to FILING_DUE so the state of the
        # period cannot mask the segregation-of-duties failure.
        advance_clock_past("2026-06-30")
        res = api.submit_call_report(
            bank["id"], period["id"], report["id"],
            make_capital_analyst_headers("analyst-prep-1"),
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)


class TestOptimisticConcurrency(object):
    def test_occ_stale_version_on_distribution_approve(self, api, system_operator_headers,
                                                       capital_analyst_headers):
        """PRD §2.8: "On each, if the supplied expected_bank_version does not
        equal the bank's current version, the request is rejected with
        ERR_STALE_VERSION (HTTP 412) and no state changes."

        Design: Corner/validations/occ_stale_version_on_distribution_approve
        """
        # The OCC check is nineteenth — last — in §2.9's fixed order, so the
        # setup must let every earlier check pass: the bank needs a positive
        # distributable pool (capacity, tenth) and a proposal made while the
        # plan is APPROVED (state, fifth).
        created = {}

        def _propose(bank_id, plan, pay_period):
            created["dist"] = create_proposed_distribution(
                bank_id, plan["id"], pay_period["id"],
                distribution_kind="DIVIDEND", distribution_amount_cents=50_000_000,
                proposed_payment_date="2027-03-15",
            )

        bank, base_period, pay_period, scenario, plan = setup_distributable_bank(
            "CH-OCC-001", scenario_code="BASE-OCC", pre_cross_hook=_propose
        )
        dist = created["dist"]
        stale = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        stale_version = stale["version"]
        # Capacity-affecting mutation bumps Bank.version (instrument creation
        # is listed in §2.8).
        bumped = bump_bank_version(bank["id"])
        assert bumped["version"] > stale_version
        res = api.approve_distribution(
            bank["id"], dist["id"], {"expected_bank_version": stale_version},
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_occ_sub_debt_approve_stale_version(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §2.8: "Four write operations guard against exactly that
        staleness and require the request body to carry
        expected_bank_version, the client's last observed version of the
        parent bank: approving a distribution request, approving a sub-debt
        issuance, submitting a capital plan to the regulator, and filing an
        ICAAP document. On each, if the supplied expected_bank_version does
        not equal the bank's current version, the request is rejected with
        ERR_STALE_VERSION (HTTP 412) and no state changes."

        Design: Corner/cross_cutting_layers/occ_sub_debt_approve_stale_version
        """
        bank, period, report = setup_accepted_report(
            "CH-OCS-001", cet1_cents=10_000_000_000, rwa_cents=100_000_000_000
        )
        issuance = create_proposed_sub_debt(
            bank["id"], proposed_amount_cents=500_000_000, proposed_rate_bps=500,
            maturity_years=10, target_settlement_date="2026-09-01",
        )
        stale = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        stale_version = stale["version"]
        bumped = bump_bank_version(bank["id"])
        assert bumped["version"] > stale_version
        res = api.approve_sub_debt(
            bank["id"], issuance["id"], {"expected_bank_version": stale_version},
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_sub_debt_approve_current_version_succeeds(self, api, system_operator_headers,
                                                           capital_analyst_headers):
        """PRD §2.8: "Approving a sub-debt issuance" is one of the four
        writes that "require the request body to carry expected_bank_version,
        the client's last observed version of the parent bank".

        Design: Corner/cross_cutting_layers/occ_sub_debt_approve_stale_version
        """
        bank, period, report = setup_accepted_report(
            "CH-OCS-002", cet1_cents=10_000_000_000, rwa_cents=100_000_000_000
        )
        issuance = create_proposed_sub_debt(
            bank["id"], proposed_amount_cents=500_000_000, proposed_rate_bps=500,
            maturity_years=10, target_settlement_date="2026-09-01",
        )
        current = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        approved = validate_success(
            api.approve_sub_debt(
                bank["id"], issuance["id"], {"expected_bank_version": current["version"]},
                capital_analyst_headers,
            )
        )
        assert approved["status"] == "APPROVED"
