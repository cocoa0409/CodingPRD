"""Operations whose legality is decided by the state of a different row."""
from test_helpers import api_client, validate_error, validate_success
from test_helpers.factories import (
    certify_service_commencement_payload,
    consent_refinancing_payload,
    create_dispute_payload,
    create_service_period_payload,
)
from test_helpers.fixtures import (
    ALPHA,
    CERTIFIER,
    DELTA,
    PERIOD_ONE_END,
    PERIOD_ONE_START,
    issue_deduction_event,
    list_reserve_rows,
    raise_enforcement_action,
    refresh_concession,
    refresh_service_period,
    set_clock,
    setup_concession_in_construction,
    setup_pending_service_period,
    setup_proposed_refinancing,
    submit_performance_report,
    verify_period,
)


class TestServicePeriodCreationReadsTheConcessionStatus:
    def test_a_period_cannot_be_opened_while_the_project_is_still_building(self):
        """The concession sits in CONSTRUCTION, so the payment stream has not opened.

        PRD: "Each period is created with a `period_index` (at least 1, the
        contractual period number), a `period_start` and a `period_end`, and it is
        opened only while the concession is in `OPERATIONS` or `STEP_IN` — otherwise
        `ERR_CONCESSION_STATE_FORBIDS_OPERATION` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/service_period_creation_depends_on_concession_status
        """
        ctx = setup_concession_in_construction()
        set_clock("2027-01-21T00:00:00Z")

        response = api_client.create_service_period(
            ctx["concession_id"],
            create_service_period_payload(1, PERIOD_ONE_START, PERIOD_ONE_END),
            ALPHA,
        )

        validate_error(response, "ERR_CONCESSION_STATE_FORBIDS_OPERATION", 409)
        body = api_client.list_service_periods(
            ALPHA, params={"concession_id": ctx["concession_id"]}
        ).json()
        assert body["meta"]["total_count"] == 0

    def test_the_identical_request_is_accepted_once_commencement_is_certified(self):
        """Nothing about the request changes; only the parent concession's status does.

        PRD: "Certifying that the service has actually commenced is the second of
        the `IndependentCertifier`'s three monopolies, and it moves the project out of
        the build and into the payment stream: the concession advances `CONSTRUCTION →
        OPERATIONS`."

        Design: Difficulty/cross_entity_state_dependency/service_period_creation_depends_on_concession_status
        """
        ctx = setup_concession_in_construction()
        set_clock("2027-01-21T00:00:00Z")
        payload = create_service_period_payload(1, PERIOD_ONE_START, PERIOD_ONE_END)
        validate_error(
            api_client.create_service_period(ctx["concession_id"], payload, ALPHA),
            "ERR_CONCESSION_STATE_FORBIDS_OPERATION",
            409,
        )

        concession = validate_success(
            api_client.certify_service_commencement(
                ctx["concession_id"],
                certify_service_commencement_payload("2027-01-21"),
                CERTIFIER,
            )
        )
        assert concession["status"] == "OPERATIONS"
        assert concession["ld_accrued_cents"] == 5000000

        period = validate_success(
            api_client.create_service_period(ctx["concession_id"], payload, ALPHA), 201
        )
        assert period["period_index"] == 1
        assert period["days_in_period"] == 31
        assert period["gross_unitary_charge_cents"] == 8604167
        assert period["deduction_cap_cents"] == 1720833
        assert period["reporting_status"] == "PENDING"
        assert period["payment_status"] == "UNBILLED"
        body = api_client.list_service_periods(
            ALPHA, params={"concession_id": ctx["concession_id"]}
        ).json()
        assert body["meta"]["total_count"] == 1


class TestDisputeCreationReadsThePeriodsReportingStatus:
    def test_a_dispute_before_verification_is_refused_as_a_cross_entity_mismatch(self):
        """The deduction is validly issued, but its period has not been verified yet.

        PRD: "The event must be in `ISSUED`, and the period that owns it must have
        reached `VERIFIED` on its reporting axis, since there is nothing to argue about
        before the authority has verified the period; a dispute raised earlier is
        refused with `ERR_CROSS_ENTITY_MISMATCH` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/dispute_creation_depends_on_the_service_periods_reporting_status
        """
        ctx = setup_pending_service_period()
        event = issue_deduction_event(ctx, 400, "UNAVAILABILITY")

        response = api_client.create_deduction_dispute(
            event["id"],
            create_dispute_payload("unavailability minutes double counted in the March log"),
            ctx["cnr_headers"],
        )

        validate_error(response, "ERR_CROSS_ENTITY_MISMATCH", 409)
        unchanged = validate_success(api_client.get_deduction_event(event["id"], ALPHA))
        assert unchanged["status"] == "ISSUED"
        assert unchanged["sequence_no"] == 1
        assert unchanged["raw_amount_cents"] == 500000
        assert unchanged["allowed_amount_cents"] == 500000
        body = api_client.list_deduction_disputes(
            ALPHA, params={"deduction_event_id": event["id"]}
        ).json()
        assert body["meta"]["total_count"] == 0
        assert refresh_concession(ctx)["availability_deduction_ytd_cents"] == 0

    def test_the_same_dispute_is_accepted_once_the_period_reaches_verified(self):
        """Verifying the period is what makes the deduction arguable.

        PRD: "A successful raise creates the dispute in `RAISED` with `round_no` 1,
        `raised_by_user_id` set to the acting `X-User-ID`, `referred_back_reason`,
        `adjudicated_by_user_id`, `adjudicated_at` and `outcome_note` all null, and
        moves the event `ISSUED → DISPUTED`."

        Design: Difficulty/cross_entity_state_dependency/dispute_creation_depends_on_the_service_periods_reporting_status
        """
        ctx = setup_pending_service_period()
        event = issue_deduction_event(ctx, 400, "UNAVAILABILITY")
        submit_performance_report(ctx, 100, 2, 4)
        verify_period(ctx, 100, 2, 4)

        response = api_client.create_deduction_dispute(
            event["id"],
            create_dispute_payload("unavailability minutes double counted in the March log"),
            ctx["cnr_headers"],
        )

        dispute = validate_success(response, 201)
        assert dispute["status"] == "RAISED"
        assert dispute["round_no"] == 1
        assert dispute["raised_by_user_id"] == ctx["concessionaire_id"]
        assert dispute["adjudicated_by_user_id"] is None
        disputed = validate_success(api_client.get_deduction_event(event["id"], ALPHA))
        assert disputed["status"] == "DISPUTED"
        assert disputed["allowed_amount_cents"] == 500000
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 500000
        assert period["net_payment_cents"] == 8104167
        assert refresh_concession(ctx)["availability_deduction_ytd_cents"] == 500000


class TestRefinancingConsentReadsTheEnforcementState:
    def test_a_fresh_concession_version_does_not_buy_past_the_enforcement_freeze(self):
        """The consent carries the concession's current version and is still refused.

        PRD: "New drawdown requests, milestone disbursement, refinancing proposals,
        refinancing decisions and the handback survey are all refused with
        `ERR_CONCESSION_UNDER_ENFORCEMENT` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/refinancing_consent_depends_on_enforcement_action_state_even_with_a_fresh_version
        """
        ctx = setup_proposed_refinancing()
        event = ctx["refinancing_event"]
        assert event["gross_gain_cents"] == 50000000
        assert event["tier_pct_applied"] == 0.3
        assert event["authority_share_cents"] == 15000000
        assert event["concessionaire_share_cents"] == 35000000
        raise_enforcement_action(ctx, "TERMINATION", "AUTHORITY_VOLUNTARY", "2027-01-26", ALPHA)
        current = validate_success(api_client.get_concession(ctx["concession_id"], DELTA))

        response = api_client.consent_refinancing_event(
            event["id"], consent_refinancing_payload("CONSENT", current["version"]), DELTA
        )

        validate_error(response, "ERR_CONCESSION_UNDER_ENFORCEMENT", 409)

    def test_the_frozen_consent_sweeps_nothing_into_the_lifecycle_reserve(self):
        """A consent that got through would have appended a 8,750,000 cent sweep.

        PRD: "On consent, the event lands in `CONSENTED` and its
        `reserve_sweep_cents` is set to twenty-five per cent of the concessionaire's
        share, rounded half up to a whole cent; one ledger entry is appended with
        `txn_type` `CONTRIBUTION`, `created_by_role` `SYSTEM` and a `reason` of
        `REFINANCING_GAIN_SWEEP` for exactly that amount, and the concession's
        `lifecycle_reserve_balance_cents` is set to the new entry's
        `resulting_balance_cents`."

        Design: Difficulty/cross_entity_state_dependency/refinancing_consent_depends_on_enforcement_action_state_even_with_a_fresh_version
        """
        ctx = setup_proposed_refinancing()
        event = ctx["refinancing_event"]
        raise_enforcement_action(ctx, "TERMINATION", "AUTHORITY_VOLUNTARY", "2027-01-26", ALPHA)
        before = validate_success(api_client.get_concession(ctx["concession_id"], DELTA))

        api_client.consent_refinancing_event(
            event["id"], consent_refinancing_payload("CONSENT", before["version"]), DELTA
        )

        stored = validate_success(api_client.get_refinancing_event(event["id"], ALPHA))
        assert stored["status"] == "PROPOSED"
        assert stored["consented_by_user_id"] is None
        assert stored["consented_at"] is None
        assert stored["reserve_sweep_cents"] == 0
        rows, meta = list_reserve_rows(ctx["concession_id"])
        assert meta["total_count"] == 1
        assert rows[0]["reason"] == "CONSTRUCTION_SEED"
        after = refresh_concession(ctx)
        assert after["lifecycle_reserve_balance_cents"] == 8000000
        assert after["version"] == before["version"]
