"""The rejection ladder: which of several simultaneous violations is the one reported."""

from __future__ import annotations

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    add_beneficial_owner,
    advance_to_underwriting,
    api_client,
    create_assessment,
    create_batch,
    create_category_rule,
    create_draft_application,
    credit_assessment_payload,
    day_activity_payload,
    day_start,
    decide_application,
    ingest_activity,
    make_applicant_headers,
    make_portfolio_controller_headers,
    make_risk_analyst_headers,
    make_underwriting_officer_headers,
    NO_ROLE_HEADERS,
    onboard_standard_merchant,
    OwnerSpec,
    read_application,
    read_batch,
    read_merchant,
    read_reserve_account,
    record_verification,
    run_monitoring,
    screen_owner,
    set_clock,
    settlement_batch_payload,
    submit_application,
    terminate_merchant,
    USER_COMMITTEE_01,
)


class TestTheTopOfTheLadder:
    """Authentication, then authorization, then schema, then existence."""

    def test_a_missing_role_outranks_both_the_role_list_and_the_schema(self):
        """An unrecognised caller with a malformed date is answered as unauthenticated.

        PRD 2.6: "Checks are evaluated in the fixed precedence order below, and the first failure
        wins."

        PRD 2.1: "A request missing either header, or presenting an `X-User-Role` that is not one of
        those six strings, is rejected with `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/validations/unauthenticated_call_outranks_role_and_schema_errors
        """
        api = api_client

        response = api.create_monitoring_run("2026-13-45", NO_ROLE_HEADERS)

        validate_error(response, "ERR_UNAUTHENTICATED", 401)

        _, meta = validate_paginated(api.list_merchants(make_risk_analyst_headers()))
        assert meta["total_count"] == 0

    def test_the_role_list_outranks_the_schema_check(self):
        """An applicant sweeping the portfolio is refused on the role, not on the date.

        PRD 2.6: "**Authorization** - the acting role appears in the operation's role list in 4:
        `ERR_ROLE_NOT_PERMITTED` (403)."

        Design: Corner/validations/role_check_outranks_the_schema_check
        """
        api = api_client

        response = api.create_monitoring_run("2026-13-45", make_applicant_headers("new-applicant"))

        validate_error(response, "ERR_ROLE_NOT_PERMITTED", 403)

    def test_the_schema_check_outranks_the_existence_lookup(self):
        """A zero page size is a schema failure even when the merchant does not exist.

        PRD 2.6: "**Schema** - required body and query fields present, enum members recognised,
        numeric ranges and string formats respected, `limit` within 1 through 100, `offset` not
        negative, and every date well-formed as `YYYY-MM-DD`: `ERR_INVALID_REQUEST` (400)."

        PRD 2.6: "Then any merchant named in a path or body, with `ERR_MERCHANT_NOT_FOUND` (404)."

        Design: Corner/validations/schema_check_outranks_the_not_found_lookup
        """
        api = api_client

        malformed = api.list_merchant_settlement_batches(
            NON_EXISTENT_UUID, make_portfolio_controller_headers(), limit=0
        )
        validate_error(malformed, "ERR_INVALID_REQUEST", 400)

        well_formed = api.list_merchant_settlement_batches(
            NON_EXISTENT_UUID, make_portfolio_controller_headers(), limit=10
        )
        validate_error(well_formed, "ERR_MERCHANT_NOT_FOUND", 404)

    def test_existence_outranks_the_state_guard(self):
        """A submit against an unknown application is a 404, and the real row is untouched.

        PRD 2.6: "**Existence, in this exact sub-order.** Referenced applications first - including
        an `application_id` in a body and a `supersedes_application_id` - with
        `ERR_APPLICATION_NOT_FOUND` (404)."

        Design: Corner/validations/not_found_outranks_the_state_check
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id = create_draft_application(
            api, legal_business_name="Fernbrook Tea LLC"
        )["id"]
        add_beneficial_owner(api, application_id, full_name="Ola Bergman", ownership_pct=100.00)
        submit_application(api, application_id)

        response = api.submit_application(
            NON_EXISTENT_UUID, make_applicant_headers(NON_EXISTENT_UUID)
        )

        validate_error(response, "ERR_APPLICATION_NOT_FOUND", 404)
        assert read_application(api, application_id)["state"] == "SUBMITTED"


class TestOwnershipAndConcurrencyOutrankState:
    """Steps five and six of the ladder both sit above the state guards of step seven."""

    def test_resource_ownership_outranks_the_state_guard(self):
        """A stranger submitting a terminal application is refused as a non-owner.

        PRD 2.6: "**Ownership** - for the two entity-backed roles, `X-User-ID` matches the resource
        being acted on: `ERR_NOT_RESOURCE_OWNER` (403)."

        PRD 2.1: "When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting
        `MerchantApplication`; ownership checks on any resource that references a
        `MerchantApplication` compare the resource's application reference"

        Design: Corner/validations/resource_ownership_outranks_the_state_check
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        declined_id = create_draft_application(
            api, legal_business_name="Fernbrook Tea LLC"
        )["id"]
        owner = add_beneficial_owner(
            api, declined_id, full_name="Ola Bergman", ownership_pct=100.00
        )
        submit_application(api, declined_id)
        record_verification(api, declined_id)
        screen_owner(api, owner["id"])
        advanced = advance_to_underwriting(api, declined_id)
        create_assessment(api, declined_id, advanced["version"])
        decide_application(
            api,
            declined_id,
            "DECLINE",
            USER_COMMITTEE_01,
            decline_reason_code="INSUFFICIENT_CREDIT",
        )

        other_id = create_draft_application(
            api, legal_business_name="Larkmead Supply LLC"
        )["id"]

        response = api.submit_application(declined_id, make_applicant_headers(other_id))

        validate_error(response, "ERR_NOT_RESOURCE_OWNER", 403)
        assert read_application(api, declined_id)["state"] == "DECLINED"
        assert read_application(api, other_id)["state"] == "DRAFT"

    def test_a_stale_version_outranks_the_application_state_guard(self):
        """A replayed token against an approved application answers 412, not 409.

        PRD 2.6: "**Optimistic concurrency** - `expected_application_version` on credit-assessment
        creation, then `expected_reserve_account_version` on a reserve release request:
        `ERR_STALE_APPLICATION_VERSION` (412) and `ERR_STALE_RESERVE_ACCOUNT_VERSION` (412)
        respectively."

        PRD 2.9: "If the supplied value does not equal the application's current `version`, the
        request is rejected with `ERR_STALE_APPLICATION_VERSION` and HTTP 412, which is what stops
        an officer from re-pinning reserve terms computed from a view of the application another
        writer has already replaced."

        Design: Corner/validations/stale_version_outranks_the_application_state_check
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        assert read_application(api, onboarded.application_id)["state"] == "APPROVED"

        response = api.create_credit_assessment(
            credit_assessment_payload(
                onboarded.application_id,
                onboarded.application_version_at_assessment,
                "CHARGEBACK_WEIGHTED",
            ),
            make_underwriting_officer_headers(),
        )

        validate_error(response, "ERR_STALE_APPLICATION_VERSION", 412)

        application = read_application(api, onboarded.application_id)
        assert application["current_assessment_method"] == "LAG_WEIGHTED"
        assert application["current_reserve_pct_bps"] == 500
        _, meta = validate_paginated(
            api.list_credit_assessments(
                onboarded.application_id, make_underwriting_officer_headers()
            )
        )
        assert meta["total_count"] == 1


class TestTheGoldenPathTripsNothing:
    """Every step of a clean intake and settlement answers with a success status."""

    def test_a_clean_onboarding_and_settlement_path_trips_no_validation(self):
        """Nine writes in a row, each accepted, ending in a scheduled payout.

        PRD 3.5: "`APPROVE` moves the application to `APPROVED` and cascades twice."

        PRD 3.9: "A `NORMAL` merchant's batch is created in `payout_state` `SCHEDULED` with
        `scheduled_payout_date` set to `period_end_date` plus 1 day."

        Design: Corner/validations/clean_onboarding_and_settlement_path_trips_no_validation
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id = create_draft_application(
            api, legal_business_name="Ridgeline Cycles LLC"
        )["id"]
        owner = add_beneficial_owner(
            api, application_id, full_name="Nadia Pike", ownership_pct=100.00
        )
        submitted = submit_application(api, application_id)
        assert submitted["state"] == "SUBMITTED"
        assert record_verification(api, application_id)["status"] == "PASSED"
        assert screen_owner(api, owner["id"])["status"] == "CLEARED"
        advanced = advance_to_underwriting(api, application_id)
        assert advanced["state"] == "UNDERWRITING"
        assessment = create_assessment(api, application_id, advanced["version"])
        assert assessment["reserve_pct_bps"] == 500
        approved = decide_application(api, application_id, "APPROVE", USER_COMMITTEE_01)
        assert approved["state"] == "APPROVED"
        assert float(approved["owner_ownership_pct_total"]) == 100.00
        assert approved["mcc_disposition"] == "ALLOWED"

        merchants, _ = validate_paginated(
            api.list_onboarded_merchants(application_id, make_underwriting_officer_headers())
        )
        merchant_id = merchants[0]["id"]

        set_clock(api, day_start("2026-08-04"))
        activity = validate_success(
            api.create_day_activity(
                day_activity_payload(merchant_id, "2026-08-04"), make_risk_analyst_headers()
            ),
            201,
        )
        assert activity["avg_ticket_cents"] == 1_000

        alerts = run_monitoring(api, "2026-08-04")
        assert alerts == []

        batch = validate_success(
            api.create_settlement_batch(
                settlement_batch_payload(merchant_id, "2026-08-04", "2026-08-04", 1_000_000),
                make_portfolio_controller_headers(),
            ),
            201,
        )
        assert batch["payout_state"] == "SCHEDULED"
        assert batch["reserve_hold_cents"] == 50_000
        assert batch["net_payout_cents"] == 950_000
        assert batch["scheduled_payout_date"] == "2026-08-05"

        merchant = read_merchant(api, merchant_id)
        assert merchant["account_state"] == "ACTIVE"
        assert merchant["funding_state"] == "NORMAL"

        accounts, _ = validate_paginated(
            api.list_merchant_reserve_accounts(merchant_id, make_risk_analyst_headers())
        )
        account = read_reserve_account(api, accounts[0]["id"])
        assert account["state"] == "ACCRUING"
        assert account["held_balance_cents"] == 50_000


class TestTemporalAndFiscalCeilings:
    """Step ten and step twelve of the ladder, on the activity and settlement paths."""

    def test_a_future_activity_row_and_a_regressing_sweep_are_both_refused(self):
        """Tomorrow cannot be observed, and the sweep may stand still but not walk back.

        PRD 3.6: "`business_date` must not be later than the logical clock date, since a facilitator
        cannot observe the future; a forward-dated row is rejected with
        `ERR_ACTIVITY_DATE_IN_FUTURE`."

        PRD 3.7: "`as_of_date` must not be later than the logical clock date, and it must not be
        earlier than the greatest `last_monitoring_run_date` across the whole portfolio - the sweep
        may stand still on a date but never walks backwards - with a violation rejected as
        `ERR_MONITORING_RUN_DATE_REGRESSION`."

        Design: Corner/validations/future_activity_and_regressing_monitoring_run_are_both_refused
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id

        set_clock(api, day_start("2026-08-05"))
        ingest_activity(api, merchant_id, "2026-08-05")
        run_monitoring(api, "2026-08-05")

        forward_dated = api.create_day_activity(
            day_activity_payload(merchant_id, "2026-08-06"), make_risk_analyst_headers()
        )
        validate_error(forward_dated, "ERR_ACTIVITY_DATE_IN_FUTURE", 422)

        backwards = api.create_monitoring_run("2026-08-04", make_risk_analyst_headers())
        validate_error(backwards, "ERR_MONITORING_RUN_DATE_REGRESSION", 409)

        standing_still = api.create_monitoring_run("2026-08-05", make_risk_analyst_headers())
        assert validate_success(standing_still, 201) == []

        _, meta = validate_paginated(
            api.list_day_activity(merchant_id, make_risk_analyst_headers())
        )
        assert meta["total_count"] == 1

    def test_the_trailing_volume_ceiling_rejects_the_second_settlement(self):
        """Twenty million settles; the next eighteen million breaks the 12500 basis point ceiling.

        PRD 3.9: "Finally, the merchant's trailing 30-day volume measured with the window ending at
        `period_end_date` must be at most one and a quarter times `monthly_volume_limit_cents` -
        12500 basis points of the contracted limit - or the batch is refused with
        `ERR_MONTHLY_VOLUME_LIMIT_EXCEEDED`."

        Design: Corner/validations/trailing_volume_tolerance_rejects_the_second_settlement
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id

        set_clock(api, day_start("2026-08-04"))
        ingest_activity(
            api,
            merchant_id,
            "2026-08-04",
            txn_count=2_000,
            volume_cents=20_000_000,
            distinct_card_count=1_900,
        )
        first = create_batch(api, merchant_id, "2026-08-04", "2026-08-04", 20_000_000)
        assert first["reserve_hold_cents"] == 1_000_000
        assert first["net_payout_cents"] == 19_000_000

        set_clock(api, day_start("2026-08-05"))
        ingest_activity(
            api,
            merchant_id,
            "2026-08-05",
            txn_count=1_800,
            volume_cents=18_000_000,
            distinct_card_count=1_700,
        )
        response = api.create_settlement_batch(
            settlement_batch_payload(merchant_id, "2026-08-05", "2026-08-05", 18_000_000),
            make_portfolio_controller_headers(),
        )

        validate_error(response, "ERR_MONTHLY_VOLUME_LIMIT_EXCEEDED", 422)

        _, meta = validate_paginated(
            api.list_merchant_settlement_batches(merchant_id, make_portfolio_controller_headers())
        )
        assert meta["total_count"] == 1
        merchant = read_merchant(api, merchant_id)
        assert merchant["pending_payout_cents"] == 19_000_000
        assert merchant["monthly_volume_limit_cents"] == 30_000_000
        assert read_reserve_account(api, onboarded.reserve_account_id)[
            "held_balance_cents"
        ] == 1_000_000


class TestTwoStateGuardsOnTheSameMerchant:
    """A terminated merchant with a closed reserve answers differently on two operations."""

    def test_the_account_state_guard_outranks_the_closed_reserve_guard(self):
        """A new settlement is refused on the account; the reversal is refused on the reserve.

        PRD 2.6: "Then merchant `account_state`, with `ERR_MERCHANT_ACCOUNT_STATE_INVALID` (409).
        Then merchant `funding_state`, with `ERR_FUNDING_STATE_INVALID` (409). Then reserve-account
        closure, with `ERR_RESERVE_ACCOUNT_CLOSED` (409)."

        PRD 3.9: "The merchant's `account_state` must not be `TERMINATED`, or
        `ERR_MERCHANT_ACCOUNT_STATE_INVALID`. The merchant's reserve account must not be in state
        `CLOSED`, or `ERR_RESERVE_ACCOUNT_CLOSED`."

        Design: Corner/validations/account_state_rule_outranks_the_closed_reserve_rule
        """
        api = api_client
        onboarded = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Ridgeline Cycles LLC",
            owners=[OwnerSpec(full_name="Nadia Pike")],
        )
        merchant_id = onboarded.merchant_id

        set_clock(api, day_start("2026-08-04"))
        ingest_activity(api, merchant_id, "2026-08-04")
        batch = create_batch(api, merchant_id, "2026-08-04", "2026-08-04", 1_000_000)

        set_clock(api, day_start("2026-08-05"))
        terminate_merchant(api, merchant_id, "SUSPECTED_LAUNDERING")

        settlement = api.create_settlement_batch(
            settlement_batch_payload(merchant_id, "2026-08-05", "2026-08-05", 1_000_000),
            make_portfolio_controller_headers(),
        )
        validate_error(settlement, "ERR_MERCHANT_ACCOUNT_STATE_INVALID", 409)

        reversal = api.reverse_settlement_batch(
            batch["id"], "FUNDING_ERROR", make_portfolio_controller_headers()
        )
        validate_error(reversal, "ERR_RESERVE_ACCOUNT_CLOSED", 409)

        assert read_merchant(api, merchant_id)["account_state"] == "TERMINATED"
        account = read_reserve_account(api, onboarded.reserve_account_id)
        assert account["state"] == "CLOSED"
        assert account["held_balance_cents"] == 50_000
        unchanged = read_batch(api, batch["id"])
        assert unchanged["payout_state"] == "HELD"
        assert unchanged["reversed_at"] is None
        _, meta = validate_paginated(
            api.list_merchant_settlement_batches(merchant_id, make_portfolio_controller_headers())
        )
        assert meta["total_count"] == 1


class TestTheCategoryPolicyGate:
    """A prohibited category stops an application that is otherwise flawless."""

    def test_a_prohibited_category_blocks_an_otherwise_perfect_application(self):
        """Coverage, screening and verification are all clean, and the category still refuses.

        PRD 3.3: "First, the application's `mcc_disposition` must not be `PROHIBITED`; a prohibited
        category is rejected with `ERR_PROHIBITED_BUSINESS_CATEGORY`."

        PRD 2.6: "**Underwriting-gate and duty-separation checks, in this exact sub-order.**
        Prohibited category, with `ERR_PROHIBITED_BUSINESS_CATEGORY` (422)."

        Design: Corner/validations/prohibited_category_blocks_an_otherwise_perfect_application
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        rule = create_category_rule(
            api, "5967", category="ADULT_CONTENT", disposition="PROHIBITED"
        )
        assert rule["reserve_uplift_bps"] == 0

        blocked_id = create_draft_application(
            api, legal_business_name="Larkmead Supply LLC", mcc_code="5967"
        )["id"]
        blocked_owner = add_beneficial_owner(
            api, blocked_id, full_name="Ola Bergman", ownership_pct=100.00
        )
        submit_application(api, blocked_id)
        assert record_verification(api, blocked_id)["status"] == "PASSED"
        assert screen_owner(api, blocked_owner["id"])["status"] == "CLEARED"

        response = api.advance_to_underwriting(blocked_id, make_underwriting_officer_headers())

        validate_error(response, "ERR_PROHIBITED_BUSINESS_CATEGORY", 422)
        blocked = read_application(api, blocked_id)
        assert blocked["mcc_disposition"] == "PROHIBITED"
        assert blocked["state"] == "IN_VERIFICATION"
        assert float(blocked["owner_ownership_pct_total"]) == 100.00

        control_id = create_draft_application(
            api, legal_business_name="Ridgeline Cycles LLC"
        )["id"]
        control_owner = add_beneficial_owner(
            api, control_id, full_name="Nadia Pike", ownership_pct=100.00
        )
        submit_application(api, control_id)
        record_verification(api, control_id)
        screen_owner(api, control_owner["id"])
        control = advance_to_underwriting(api, control_id)
        assert control["state"] == "UNDERWRITING"
        assert control["mcc_disposition"] == "ALLOWED"
