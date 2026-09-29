"""Role boundaries: the operations each role alone may perform, and the refusals around them."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    add_beneficial_owner,
    api_client,
    appeal_payload,
    approve_termination,
    application_payload,
    beneficial_owner_payload,
    category_rule_payload,
    create_draft_application,
    day_activity_payload,
    day_start,
    make_merchant_user_headers,
    make_portfolio_controller_headers,
    make_risk_analyst_headers,
    make_risk_committee_headers,
    make_underwriting_officer_headers,
    merchant_with_open_chargeback_alert,
    onboard_standard_merchant,
    OwnerSpec,
    propose_termination,
    read_application,
    read_merchant,
    read_reserve_account,
    read_termination_decision,
    release_request_payload,
    screening_payload,
    set_clock,
    settlement_batch_payload,
    submit_application,
    USER_ANALYST_01,
    USER_COMMITTEE_01,
    verification_payload,
)


class TestApplicantOnlyWrites:
    """The applicant's own three writes stay closed to staff with business standing."""

    def test_applicant_write_operations_are_closed_to_every_staff_role(self):
        """An officer may verify the file but may not build it.

        PRD 2.2: "`Applicant` alone may create an application, attach a beneficial owner, submit and
        withdraw."

        PRD 2.6: "**Authorization** - the acting role appears in the operation's role list in 4:
        `ERR_ROLE_NOT_PERMITTED` (403)."

        Design: Corner/rbac/applicant_write_operations_are_closed_to_every_staff_role
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id = create_draft_application(
            api, legal_business_name="Ashgrove Cycles"
        )["id"]
        officer = make_underwriting_officer_headers()

        created_by_officer = api.create_application(
            application_payload(legal_business_name="Ashgrove Cycles Two"), officer
        )
        validate_error(created_by_officer, "ERR_ROLE_NOT_PERMITTED", 403)

        owner_by_officer = api.create_beneficial_owner(
            beneficial_owner_payload(application_id, full_name="Dana Reyes"), officer
        )
        validate_error(owner_by_officer, "ERR_ROLE_NOT_PERMITTED", 403)

        submitted_by_analyst = api.submit_application(application_id, make_risk_analyst_headers())
        validate_error(submitted_by_analyst, "ERR_ROLE_NOT_PERMITTED", 403)

        application = read_application(api, application_id)
        assert application["state"] == "DRAFT"
        assert float(application["owner_ownership_pct_total"]) == 0.00

        owners, meta = validate_paginated(api.list_beneficial_owners(application_id, officer))
        assert owners == []
        assert meta["total_count"] == 0

        _, applications_meta = validate_paginated(api.list_applications(officer))
        assert applications_meta["total_count"] == 1


class TestUnderwritingAndCommitteeSeats:
    """Building the underwriting file and signing it off are different roles."""

    def test_underwriting_and_committee_operations_do_not_overlap(self):
        """Neither seat can carry an application from SUBMITTED to APPROVED alone.

        PRD 2.2: "`UnderwritingOfficer` alone may publish a category rule, record a verification,
        screen an owner, advance an application to underwriting and create a credit assessment."

        PRD 2.2: "`RiskCommitteeApprover` alone may decide an application, release a funding hold,
        activate a remediation program, approve or reject a termination, and review, question and
        decide an appeal."

        Design: Corner/rbac/underwriting_and_committee_operations_do_not_overlap
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id = create_draft_application(
            api, legal_business_name="Ashgrove Cycles"
        )["id"]
        owner = add_beneficial_owner(
            api, application_id, full_name="Dana Reyes", ownership_pct=100.00
        )
        submit_application(api, application_id)

        committee = make_risk_committee_headers(USER_COMMITTEE_01)

        verification_by_committee = api.create_business_verification(
            verification_payload(application_id), committee
        )
        validate_error(verification_by_committee, "ERR_ROLE_NOT_PERMITTED", 403)

        screening_by_committee = api.screen_beneficial_owner(
            owner["id"], screening_payload(), committee
        )
        validate_error(screening_by_committee, "ERR_ROLE_NOT_PERMITTED", 403)

        advance_by_committee = api.advance_to_underwriting(application_id, committee)
        validate_error(advance_by_committee, "ERR_ROLE_NOT_PERMITTED", 403)

        officer = make_underwriting_officer_headers()
        decision_by_officer = api.decide_application(
            application_id, {"decision": "APPROVE"}, officer
        )
        validate_error(decision_by_officer, "ERR_ROLE_NOT_PERMITTED", 403)

        rule_by_analyst = api.create_category_rule(
            category_rule_payload("7995"), make_risk_analyst_headers()
        )
        validate_error(rule_by_analyst, "ERR_ROLE_NOT_PERMITTED", 403)

        application = read_application(api, application_id)
        assert application["state"] == "SUBMITTED"
        assert application["verification_attempt_count"] == 0

        owners, _ = validate_paginated(api.list_beneficial_owners(application_id, officer))
        assert owners[0]["status"] == "PENDING"

        _, rules_meta = validate_paginated(api.list_category_rules(officer))
        assert rules_meta["total_count"] == 0


class TestMonitoringAndTreasurySeats:
    """Risk monitoring and money movement exclude each other in both directions."""

    def test_monitoring_writes_and_treasury_writes_exclude_each_other(self):
        """Six refusals leave no activity, no batch and no monitoring history.

        PRD 2.2: "`RiskAnalyst` alone may ingest day activity, run the monitoring sweep, review an
        alert, place a funding hold, open a remediation program, evaluate a remediation month and
        propose a termination."

        PRD 2.2: "`PortfolioController` alone may create, pay and reverse settlement batches, request
        a reserve release, execute a termination and generate a portfolio forecast."

        Design: Corner/rbac/monitoring_writes_and_treasury_writes_exclude_each_other
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ashgrove Cycles",
            owners=[OwnerSpec(full_name="Dana Reyes")],
        )
        merchant_id = onboarded.merchant_id
        set_clock(api, day_start("2026-08-04"))
        decision = propose_termination(api, merchant_id, "EXCESSIVE_CHARGEBACKS", USER_ANALYST_01)
        approve_termination(api, decision["id"], USER_COMMITTEE_01)

        controller = make_portfolio_controller_headers()
        analyst = make_risk_analyst_headers()

        activity_by_controller = api.create_day_activity(
            day_activity_payload(merchant_id, "2026-08-04"), controller
        )
        validate_error(activity_by_controller, "ERR_ROLE_NOT_PERMITTED", 403)

        sweep_by_controller = api.create_monitoring_run("2026-08-04", controller)
        validate_error(sweep_by_controller, "ERR_ROLE_NOT_PERMITTED", 403)

        hold_by_controller = api.place_funding_hold(
            merchant_id, "SUSPECTED_LAUNDERING", controller
        )
        validate_error(hold_by_controller, "ERR_ROLE_NOT_PERMITTED", 403)

        batch_by_analyst = api.create_settlement_batch(
            settlement_batch_payload(merchant_id, "2026-08-04", "2026-08-04", 1_000_000), analyst
        )
        validate_error(batch_by_analyst, "ERR_ROLE_NOT_PERMITTED", 403)

        execution_by_analyst = api.execute_termination_decision(decision["id"], analyst)
        validate_error(execution_by_analyst, "ERR_ROLE_NOT_PERMITTED", 403)

        release_by_analyst = api.create_release_request(
            onboarded.reserve_account_id,
            release_request_payload(
                1, "2026-08-01", "2026-08-02", onboarded.reserve_account["version"]
            ),
            analyst,
        )
        validate_error(release_by_analyst, "ERR_ROLE_NOT_PERMITTED", 403)

        _, days_meta = validate_paginated(api.list_day_activity(merchant_id, analyst))
        assert days_meta["total_count"] == 0
        _, batches_meta = validate_paginated(
            api.list_merchant_settlement_batches(merchant_id, analyst)
        )
        assert batches_meta["total_count"] == 0

        merchant = read_merchant(api, merchant_id)
        assert merchant["last_monitoring_run_date"] is None
        assert merchant["funding_state"] == "NORMAL"
        assert merchant["account_state"] == "ACTIVE"
        assert read_termination_decision(api, decision["id"])["state"] == "APPROVED"
        assert read_reserve_account(api, onboarded.reserve_account_id)["released_to_date_cents"] == 0


class TestMerchantFacingRole:
    """The merchant reads its own file and writes nothing into it."""

    def test_a_merchant_may_read_its_own_risk_file_but_write_nothing_in_it(self):
        """The same identifier that reads successfully is refused on three writes.

        PRD 2.2: "`MerchantUser` alone may file an appeal and respond to an appeal information
        request."

        PRD 2.2: "When `X-User-Role` is `MerchantUser`, `X-User-ID` is the `id` of the acting
        `Merchant`; ownership checks compare the merchant `id` in the path, or the `merchant_id`
        supplied in the body, to `X-User-ID`."

        Design: Corner/rbac/a_merchant_may_read_its_own_risk_file_but_write_nothing_in_it
        """
        api = api_client
        onboarded, alert = merchant_with_open_chargeback_alert(
            api,
            chargeback_count=14,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ashgrove Cycles",
            owners=[OwnerSpec(full_name="Dana Reyes")],
        )
        merchant_id = onboarded.merchant_id
        merchant_headers = make_merchant_user_headers(merchant_id)

        summary = validate_success(api.get_risk_summary(merchant_id, merchant_headers))
        assert summary["gating_ratio_band"] == "EXCESSIVE"
        assert summary["open_alert_count"] == 1

        alerts, alerts_meta = validate_paginated(
            api.list_monitoring_alerts(merchant_id, merchant_headers)
        )
        assert alerts_meta["total_count"] == 1
        assert alerts[0]["id"] == alert["id"]

        _, ledger_meta = validate_paginated(
            api.list_reserve_ledger_entries(onboarded.reserve_account_id, merchant_headers)
        )
        assert ledger_meta["total_count"] == 0

        set_clock(api, day_start("2026-08-06"))
        activity_by_merchant = api.create_day_activity(
            day_activity_payload(
                merchant_id,
                "2026-08-06",
                txn_count=10,
                volume_cents=10_000,
                decline_count=0,
                distinct_card_count=10,
                unique_bin_count=10,
            ),
            merchant_headers,
        )
        validate_error(activity_by_merchant, "ERR_ROLE_NOT_PERMITTED", 403)

        review_by_merchant = api.review_alert(
            alert["id"],
            {"disposition": "DISMISS", "review_note": "We believe this alert is wrong."},
            merchant_headers,
        )
        validate_error(review_by_merchant, "ERR_ROLE_NOT_PERMITTED", 403)

        release_by_merchant = api.create_release_request(
            onboarded.reserve_account_id,
            release_request_payload(
                1, "2026-08-01", "2026-08-02", onboarded.reserve_account["version"]
            ),
            merchant_headers,
        )
        validate_error(release_by_merchant, "ERR_ROLE_NOT_PERMITTED", 403)

        appeal_by_analyst = api.create_appeal(
            appeal_payload(merchant_id, "00000000-0000-0000-0000-0000000000ff"),
            make_risk_analyst_headers(),
        )
        validate_error(appeal_by_analyst, "ERR_ROLE_NOT_PERMITTED", 403)

        _, days_meta = validate_paginated(
            api.list_day_activity(merchant_id, make_risk_analyst_headers())
        )
        assert days_meta["total_count"] == 1
        assert read_merchant(api, merchant_id)["open_alert_count"] == 1


class TestFundingHoldSeats:
    """Placing a hold and lifting it are two roles, not one identity twice."""

    def test_placing_and_lifting_a_funding_hold_are_two_different_seats(self):
        """The analyst holds, the committee lifts, and neither may do the other's step.

        PRD 3.8: "An analyst may also hold funding directly, supplying a `reason_code` from
        `SUSPECTED_LAUNDERING`, `CARD_TESTING`, `EXCESSIVE_CHARGEBACKS` and `TERMINATION_PENDING`,
        which is stored as `funding_hold_reason_code`."

        PRD 3.8: "Lifting a hold is reserved to a `RiskCommitteeApprover` and takes no body."

        PRD 3.8: "When `account_state` is `ACTIVE`, `funding_state` moves `HELD -> NORMAL`,
        `funding_hold_reason_code` is cleared, `delayed_payout_days` is set to 0"

        Design: Corner/rbac/placing_and_lifting_a_funding_hold_are_two_different_seats
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ashgrove Cycles",
            owners=[OwnerSpec(full_name="Dana Reyes")],
        )
        merchant_id = onboarded.merchant_id

        hold_by_committee = api.place_funding_hold(
            merchant_id, "SUSPECTED_LAUNDERING", make_risk_committee_headers(USER_COMMITTEE_01)
        )
        validate_error(hold_by_committee, "ERR_ROLE_NOT_PERMITTED", 403)
        assert read_merchant(api, merchant_id)["funding_state"] == "NORMAL"

        held = validate_success(
            api.place_funding_hold(
                merchant_id, "SUSPECTED_LAUNDERING", make_risk_analyst_headers(USER_ANALYST_01)
            )
        )
        assert held["funding_state"] == "HELD"
        assert held["funding_hold_reason_code"] == "SUSPECTED_LAUNDERING"
        assert held["delayed_payout_days"] == 0

        release_by_analyst = api.release_funding_hold(
            merchant_id, make_risk_analyst_headers(USER_ANALYST_01)
        )
        validate_error(release_by_analyst, "ERR_ROLE_NOT_PERMITTED", 403)
        assert read_merchant(api, merchant_id)["funding_state"] == "HELD"

        released = validate_success(
            api.release_funding_hold(merchant_id, make_risk_committee_headers(USER_COMMITTEE_01))
        )
        assert released["funding_state"] == "NORMAL"
        assert released["funding_hold_reason_code"] is None
        assert released["delayed_payout_days"] == 0
        assert released["account_state"] == "ACTIVE"
