"""Who may act, who may not, and the four pairs one identity may never complete alone."""
from test_helpers import (
    OFFICER_ALPHA,
    OFFICER_BETA,
    api_client,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    certify_service_commencement_payload,
    consent_refinancing_payload,
    create_enforcement_action_payload,
    settle_enforcement_action_payload,
    verify_service_period_payload,
)
from test_helpers.fixtures import (
    ALPHA,
    BETA,
    CERTIFIER,
    GAMMA,
    LENDER,
    issue_deduction_event,
    list_deduction_events_for_period,
    list_reserve_rows,
    propose_refinancing,
    refresh_concession,
    refresh_service_period,
    set_clock,
    setup_calculated_compensation,
    setup_concession_in_construction,
    setup_concession_in_operations,
    setup_self_reported_period,
)


class TestTheConcessionaireCannotVerifyItsOwnPeriod:
    def test_the_reporting_party_is_refused_by_role_and_not_by_ownership(self):
        """The caller does own the period, so an ownership-flavoured error would be wrong.

        PRD: "When the role is recognised but is not among the roles permitted for the
        requested operation, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/the_concessionaire_cannot_verify_its_own_period
        """
        ctx = setup_self_reported_period()
        report_id = ctx["performance_report"]["id"]

        response = api_client.verify_service_period(
            ctx["service_period_id"],
            verify_service_period_payload(0, 0, 0),
            ctx["cnr_headers"],
        )

        validate_error(response, "ERR_ROLE_NOT_PERMITTED", 403)
        period = refresh_service_period(ctx)
        assert period["reporting_status"] == "SELF_REPORTED"
        assert period["verified_at"] is None
        assert period["unavailable_minutes_verified"] is None
        assert period["availability_ratio"] is None
        # A period with no deduction events carries a zero total and a net payment
        # equal to its frozen gross charge until verification settles it.
        assert period["total_deduction_cents"] == 0
        assert period["net_payment_cents"] == 8604167
        report = validate_success(api_client.get_performance_report(report_id, ALPHA))
        assert report["status"] == "SUBMITTED"
        assert report["variance_pct"] is None


class TestOnlyTheCertifierMayCertifyCommencement:
    def test_the_authority_is_excluded_and_an_early_date_accrues_no_damages(self):
        """The party with the financial interest in the date does not get to set it.

        PRD: "Certifying that the service has actually commenced is the second of the
        `IndependentCertifier`'s three monopolies, and it moves the project out of the
        build and into the payment stream: the concession advances `CONSTRUCTION →
        OPERATIONS`."

        PRD: "Count the whole calendar days from the contractual
        `scheduled_service_commencement` to the certified actual commencement; if the
        project delivered early, that count is treated as zero rather than as a
        negative number."

        Design: Corner/rbac/only_the_certifier_may_certify_service_commencement
        """
        ctx = setup_concession_in_construction()
        set_clock("2026-12-28T00:00:00Z")

        refused = api_client.certify_service_commencement(
            ctx["concession_id"],
            certify_service_commencement_payload("2026-12-28"),
            ALPHA,
        )

        validate_error(refused, "ERR_ROLE_NOT_PERMITTED", 403)
        mid = refresh_concession(ctx)
        assert mid["status"] == "CONSTRUCTION"
        assert mid["actual_service_commencement"] is None
        sponsor_attempt = api_client.certify_service_commencement(
            ctx["concession_id"],
            certify_service_commencement_payload("2026-12-28"),
            ctx["cnr_headers"],
        )
        validate_error(sponsor_attempt, "ERR_ROLE_NOT_PERMITTED", 403)

        certified = validate_success(
            api_client.certify_service_commencement(
                ctx["concession_id"],
                certify_service_commencement_payload("2026-12-28"),
                CERTIFIER,
            )
        )

        assert certified["actual_service_commencement"] == "2026-12-28"
        assert certified["status"] == "OPERATIONS"
        assert certified["ld_accrued_cents"] == 0


class TestEitherPartyMayNotifyAnEnforcementAction:
    def test_the_acting_role_is_recorded_and_the_sponsor_is_excluded(self):
        """Authority and lenders share the trigger; the subject of the action does not.

        PRD: "Either the public side or the lenders may pull the trigger: an
        `AuthorityOfficer` or a `LenderAgent` notifies an action against a concession
        by supplying the `action_type` — `STEP_IN` or `TERMINATION` — the contractual
        `trigger_reason` and the `effective_date` from which the action bites."

        Design: Corner/rbac/either_party_may_notify_an_enforcement_action
        """
        ctx = setup_concession_in_operations()
        set_clock("2027-02-01T00:00:00Z")
        payload = create_enforcement_action_payload(
            "STEP_IN", "LENDER_DEFAULT_CURE", "2027-02-01"
        )
        sponsor_attempt = api_client.create_enforcement_action(
            ctx["concession_id"], payload, ctx["cnr_headers"]
        )
        validate_error(sponsor_attempt, "ERR_ROLE_NOT_PERMITTED", 403)

        action = validate_success(
            api_client.create_enforcement_action(ctx["concession_id"], payload, LENDER),
            201,
        )

        assert action["initiated_by_role"] == "LenderAgent"
        assert action["action_type"] == "STEP_IN"
        assert action["status"] == "STEP_IN_ACTIVE"
        assert action["cure_deadline"] == "2027-05-02"
        assert refresh_concession(ctx)["status"] == "STEP_IN"
        sponsor = validate_success(
            api_client.get_concessionaire(ctx["concessionaire_id"], ALPHA)
        )
        assert sponsor["status"] == "STEPPED_IN"

        other = setup_concession_in_operations(legal_name="Eastway Bridge Partners SPV")
        set_clock("2027-02-01T00:00:00Z")
        by_authority = validate_success(
            api_client.create_enforcement_action(other["concession_id"], payload, ALPHA),
            201,
        )
        assert by_authority["initiated_by_role"] == "AuthorityOfficer"
        assert by_authority["status"] == "STEP_IN_ACTIVE"
        assert by_authority["cure_deadline"] == "2027-05-02"
        assert refresh_concession(other)["status"] == "STEP_IN"


class TestTheIssuingOfficerMayNotSealThePeriod:
    def test_a_second_officer_completes_the_identical_verification(self):
        """The block is identity-scoped, so it is not a state lock on the endpoint.

        PRD: "Verification is also the first half of a separated pair: an officer whose
        `X-User-ID` matches the `issued_by_user_id` of any deduction event already
        attached to the period may not verify it, and is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/the_issuing_officer_may_not_seal_the_period
        """
        ctx = setup_self_reported_period()
        event = issue_deduction_event(ctx, 400, "UNAVAILABILITY", headers=ALPHA)

        refused = api_client.verify_service_period(
            ctx["service_period_id"], verify_service_period_payload(100, 2, 4), ALPHA
        )

        validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 403)
        mid = refresh_service_period(ctx)
        assert mid["reporting_status"] == "SELF_REPORTED"
        assert mid["verified_at"] is None
        # The event's allocation ran when it was issued, so the money is already set.
        assert mid["total_deduction_cents"] == 500000
        assert mid["net_payment_cents"] == 8104167

        period = validate_success(
            api_client.verify_service_period(
                ctx["service_period_id"], verify_service_period_payload(100, 2, 4), BETA
            )
        )

        assert period["reporting_status"] == "VERIFIED"
        # deduction_points_total sums the points of the period's live events.
        assert period["deduction_points_total"] == 400
        assert period["total_deduction_cents"] == 500000
        assert period["net_payment_cents"] == 8104167
        held = validate_success(api_client.get_deduction_event(event["id"], ALPHA))
        assert held["issued_by_user_id"] == OFFICER_ALPHA
        assert held["allowed_amount_cents"] == 500000
        _, meta = list_deduction_events_for_period(ctx["service_period_id"])
        assert meta["total_count"] == 1


class TestTheProposingOfficerMayNotConsent:
    def test_the_refused_consent_burns_neither_the_version_nor_the_reserve(self):
        """A second officer consents on the very same expected_concession_version.

        PRD: "Consent is the `AuthorityOfficer`'s, and it is separated from proposal:
        an officer whose `X-User-ID` equals the recorded `proposed_by_user_id` may not
        decide the proposal and is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP
        403)."

        Design: Corner/rbac/the_proposing_officer_may_not_consent_to_the_refinancing
        """
        ctx = setup_concession_in_operations()
        set_clock("2027-03-01T00:00:00Z")
        proposal = propose_refinancing(
            ctx, "2027-03-01", 300000000, 240000000, 10000000, ALPHA
        )
        version_before = refresh_concession(ctx)["version"]

        refused = api_client.consent_refinancing_event(
            proposal["id"], consent_refinancing_payload("CONSENT", version_before), ALPHA
        )

        validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 403)
        mid = validate_success(api_client.get_refinancing_event(proposal["id"], ALPHA))
        assert mid["status"] == "PROPOSED"
        assert mid["consented_by_user_id"] is None
        assert mid["reserve_sweep_cents"] == 0
        concession_mid = refresh_concession(ctx)
        assert concession_mid["version"] == version_before
        assert concession_mid["lifecycle_reserve_balance_cents"] == 8000000

        consented = validate_success(
            api_client.consent_refinancing_event(
                proposal["id"],
                consent_refinancing_payload("CONSENT", version_before),
                BETA,
            )
        )

        assert consented["status"] == "CONSENTED"
        assert consented["consented_by_user_id"] == OFFICER_BETA
        assert consented["proposed_by_user_id"] == OFFICER_ALPHA
        assert consented["gross_gain_cents"] == 50000000
        assert consented["tier_pct_applied"] == 0.3
        assert consented["authority_share_cents"] == 15000000
        assert consented["concessionaire_share_cents"] == 35000000
        assert consented["reserve_sweep_cents"] == 8750000
        concession = refresh_concession(ctx)
        assert concession["lifecycle_reserve_balance_cents"] == 16750000
        assert concession["version"] == version_before + 1
        rows, meta = list_reserve_rows(ctx["concession_id"])
        assert meta["total_count"] == 2
        assert rows[-1]["txn_type"] == "CONTRIBUTION"
        assert rows[-1]["created_by_role"] == "SYSTEM"
        assert rows[-1]["amount_cents"] == 8750000
        assert rows[-1]["resulting_balance_cents"] == 16750000


class TestTheCalculatingOfficerMayNotSettle:
    def test_the_refused_settlement_does_not_start_the_termination_cascade(self):
        """The stored compensation is identical before and after the refusal.

        PRD: "Settlement is what terminates the project, and it is separated from the
        valuation: an `AuthorityOfficer` whose `X-User-ID` equals the recorded
        `calculated_by_user_id` may not settle, and is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/the_calculating_officer_may_not_settle
        """
        ctx = setup_calculated_compensation()
        action_id = ctx["enforcement_action"]["id"]

        refused = api_client.settle_enforcement_action(
            action_id, settle_enforcement_action_payload("SETTLE-2028-0001"), ALPHA
        )

        validate_error(refused, "ERR_SEGREGATION_OF_DUTIES", 403)
        mid = validate_success(api_client.get_enforcement_action(action_id, ALPHA))
        assert mid["status"] == "COMPENSATION_CALCULATED"
        assert mid["settled_at"] is None
        assert mid["settlement_reference"] is None
        assert mid["compensation_cents"] == 292000000
        assert refresh_concession(ctx)["status"] == "OPERATIONS"
        sponsor_mid = validate_success(
            api_client.get_concessionaire(ctx["concessionaire_id"], ALPHA)
        )
        assert sponsor_mid["status"] == "ACTIVE"

        settled = validate_success(
            api_client.settle_enforcement_action(
                action_id, settle_enforcement_action_payload("SETTLE-2028-0001"), GAMMA
            )
        )

        assert settled["status"] == "SETTLED"
        assert settled["settlement_reference"] == "SETTLE-2028-0001"
        assert settled["calculated_by_user_id"] == OFFICER_ALPHA
        assert settled["compensation_cents"] == 292000000
        assert refresh_concession(ctx)["status"] == "TERMINATED"
        sponsor = validate_success(
            api_client.get_concessionaire(ctx["concessionaire_id"], ALPHA)
        )
        assert sponsor["status"] == "WOUND_UP"
