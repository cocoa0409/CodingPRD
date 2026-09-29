"""Entity shapes: creation defaults, server-owned fields, lookups and schema refusals."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    api_client,
    application_payload,
    beneficial_owner_payload,
    create_category_rule,
    create_draft_application,
    credit_assessment_payload,
    make_applicant_headers,
    make_merchant_user_headers,
    make_portfolio_controller_headers,
    make_risk_analyst_headers,
    make_underwriting_officer_headers,
    onboard_standard_merchant,
    OwnerSpec,
    portfolio_forecast_payload,
    read_application,
    screening_payload,
    set_clock,
    submit_application,
    terminate_merchant,
    appeal_payload,
    add_beneficial_owner,
)

UNKNOWN_ID = "00000000-0000-0000-0000-0000000000ff"


class TestApplicationCreationDefaults:
    """A freshly created application carries only server-derived starting values."""

    def test_creation_returns_the_declared_defaults_and_version_one(self):
        """No screening rule matches 5732, so the disposition is ALLOWED and every counter is empty.

        PRD 3.1: "At creation the server sets `state` to `DRAFT`, `owner_ownership_pct_total` to
        0.00, `outstanding_info_items` to an empty list, `verification_attempt_count` to 0, and
        derives `mcc_disposition` from the single screening rule whose `mcc_code` equals the
        application's - `PROHIBITED` or `RESTRICTED_REVIEW` from that rule's `disposition`, and
        `ALLOWED` when no rule matches."

        PRD 3.1: "`decline_reason_code`, `current_assessment_method`, `current_reserve_pct_bps`,
        `current_reserve_cap_cents`, `current_reserve_type`, `decision_officer_user_id` and
        `decided_at` all start null."

        Design: Corner/entities/application_creation_returns_declared_defaults_and_version_one
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")

        response = api.create_application(
            application_payload(legal_business_name="Alderwood Supply LLC"),
            make_applicant_headers("new-applicant"),
        )
        application = validate_success(response, 201)

        assert application["state"] == "DRAFT"
        assert application["mcc_disposition"] == "ALLOWED"
        assert application["outstanding_info_items"] == []
        assert application["verification_attempt_count"] == 0
        assert float(application["owner_ownership_pct_total"]) == 0.00
        assert application["decline_reason_code"] is None
        assert application["current_assessment_method"] is None
        assert application["current_reserve_pct_bps"] is None
        assert application["current_reserve_cap_cents"] is None
        assert application["current_reserve_type"] is None
        assert application["decision_officer_user_id"] is None
        assert application["decided_at"] is None
        assert application["version"] == 1
        assert application["requested_monthly_volume_cents"] == 30_000_000

    def test_retrieval_returns_the_stored_row_unchanged(self):
        """The fetch echoes the declared risk inputs exactly as they were supplied.

        PRD 3.1: "Three further inputs exist purely to price risk and are discussed again in 3.4:
        `avg_delivery_lag_days`, the average number of days between authorization and delivery of
        the goods or service, from 0 through 365; `prior_processing_history_months`, months of
        verifiable prior card-processing history, from 0 through 600; `credit_score`, the
        principal's bureau score, from 300 through 850; and `declared_chargeback_ratio_bps`, the
        applicant's declared historical chargeback ratio in basis points, from 0 through 10000."

        Design: Corner/entities/application_retrieval_returns_the_stored_row
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")

        created = create_draft_application(
            api, legal_business_name="Alderwood Supply LLC", tax_id="12-3456789"
        )

        fetched = validate_success(
            api.get_application(created["id"], make_underwriting_officer_headers())
        )

        assert fetched["id"] == created["id"]
        assert fetched["legal_business_name"] == "Alderwood Supply LLC"
        assert fetched["tax_id"] == "12-3456789"
        assert fetched["credit_score"] == 700
        assert fetched["avg_delivery_lag_days"] == 0
        assert fetched["prior_processing_history_months"] == 24
        assert fetched["declared_chargeback_ratio_bps"] == 0
        assert fetched["state"] == "DRAFT"
        assert fetched["version"] == 1

    def test_listing_paginates_with_total_count_and_has_more(self):
        """Three applications read two at a time report the full total on every page.

        PRD 2.3: "`limit` is the maximum number of rows returned; it defaults to 10, its minimum
        accepted value is 1 and its maximum accepted value is 100."

        PRD 2.3: "Every list response reports `limit`, `offset`, `total_count` and `has_more` inside
        the `meta` object of the envelope."

        Design: Corner/entities/application_listing_paginates_with_total_count_and_has_more
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        for name in ("Alpha Tools LLC", "Bravo Tools LLC", "Cedar Tools LLC"):
            create_draft_application(api, legal_business_name=name)

        first_page, meta = validate_paginated(
            api.list_applications(make_underwriting_officer_headers(), limit=2, offset=0)
        )
        assert len(first_page) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert [row["legal_business_name"] for row in first_page] == [
            "Alpha Tools LLC",
            "Bravo Tools LLC",
        ]

        last_page, last_meta = validate_paginated(
            api.list_applications(make_underwriting_officer_headers(), limit=2, offset=2)
        )
        assert len(last_page) == 1
        assert last_page[0]["legal_business_name"] == "Cedar Tools LLC"
        assert last_meta["total_count"] == 3
        assert last_meta["has_more"] is False


class TestUnknownIdentifiersAndMissingFields:
    """Every family answers with its own not-found code; schema refusals persist nothing."""

    def test_an_unknown_uuid_is_not_found_in_all_ten_entity_families(self):
        """Each lookup names a different family, so each returns that family's 404.

        PRD 2.6: "Referenced applications first - including an `application_id` in a body and a
        `supersedes_application_id` - with `ERR_APPLICATION_NOT_FOUND` (404). Then the beneficial
        owner named by an owner-screening request, with `ERR_OWNER_NOT_FOUND` (404). Then any
        merchant named in a path or body, with `ERR_MERCHANT_NOT_FOUND` (404)."

        Design: Corner/entities/unknown_uuid_not_found_across_all_ten_entity_lookups
        """
        api = api_client
        officer = make_underwriting_officer_headers()
        analyst = make_risk_analyst_headers()
        controller = make_portfolio_controller_headers()

        validate_error(
            api.get_application(UNKNOWN_ID, officer), "ERR_APPLICATION_NOT_FOUND", 404
        )
        validate_error(
            api.screen_beneficial_owner(UNKNOWN_ID, screening_payload(), officer),
            "ERR_OWNER_NOT_FOUND",
            404,
        )
        validate_error(api.get_merchant(UNKNOWN_ID, analyst), "ERR_MERCHANT_NOT_FOUND", 404)
        validate_error(
            api.get_reserve_account(UNKNOWN_ID, controller), "ERR_RESERVE_ACCOUNT_NOT_FOUND", 404
        )
        validate_error(
            api.get_settlement_batch(UNKNOWN_ID, controller), "ERR_BATCH_NOT_FOUND", 404
        )
        validate_error(
            api.review_alert(UNKNOWN_ID, {"disposition": "ACKNOWLEDGE"}, analyst),
            "ERR_ALERT_NOT_FOUND",
            404,
        )
        validate_error(
            api.get_remediation_program(UNKNOWN_ID, analyst), "ERR_PROGRAM_NOT_FOUND", 404
        )
        validate_error(
            api.get_termination_decision(UNKNOWN_ID, analyst),
            "ERR_TERMINATION_DECISION_NOT_FOUND",
            404,
        )
        validate_error(api.get_appeal(UNKNOWN_ID, analyst), "ERR_APPEAL_NOT_FOUND", 404)
        validate_error(
            api.get_portfolio_forecast(UNKNOWN_ID, controller), "ERR_FORECAST_NOT_FOUND", 404
        )

    def test_missing_required_input_fields_are_rejected_as_invalid_requests(self):
        """Three bodies each drop one mandatory field, and none of them creates a row.

        PRD 2.6: "**Schema** - required body and query fields present, enum members recognised,
        numeric ranges and string formats respected, `limit` within 1 through 100, `offset` not
        negative, and every date well-formed as `YYYY-MM-DD`: `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/missing_required_input_fields_rejected_with_invalid_request
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        anchor = create_draft_application(api, legal_business_name="Alderwood Supply LLC")

        without_tax_id = application_payload()
        without_tax_id.pop("tax_id")
        validate_error(
            api.create_application(without_tax_id, make_applicant_headers("new-applicant")),
            "ERR_INVALID_REQUEST",
            400,
        )

        without_credit_score = application_payload()
        without_credit_score.pop("credit_score")
        validate_error(
            api.create_application(without_credit_score, make_applicant_headers("new-applicant")),
            "ERR_INVALID_REQUEST",
            400,
        )

        without_pct = beneficial_owner_payload(anchor["id"])
        without_pct.pop("ownership_pct")
        validate_error(
            api.create_beneficial_owner(without_pct, make_applicant_headers(anchor["id"])),
            "ERR_INVALID_REQUEST",
            400,
        )

        _, meta = validate_paginated(api.list_applications(make_underwriting_officer_headers()))
        assert meta["total_count"] == 1
        assert float(read_application(api, anchor["id"])["owner_ownership_pct_total"]) == 0.00

    def test_enum_and_range_constraints_are_rejected_on_four_create_calls(self):
        """An out-of-range percentage, score, unknown country and unknown method all read 400.

        PRD 3.1: "Each owner carries the `application_id` it is disclosed on, a `full_name` of 1
        through 200 non-blank characters, an `ownership_pct` from 0.01 through 100 expressed to two
        decimal places, a `date_of_birth` written as `YYYY-MM-DD`, a `government_id_last4` of
        exactly four digits, and a `country_code` of `US` or `CA`."

        PRD 3.4: "The request supplies `application_id`, a `method` of either `LAG_WEIGHTED` or
        `CHARGEBACK_WEIGHTED`, and `expected_application_version` as described in 2.9."

        Design: Corner/entities/enum_and_range_constraints_rejected_on_four_create_calls
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application = create_draft_application(api, legal_business_name="Alderwood Supply LLC")
        application_id = application["id"]

        validate_error(
            api.create_beneficial_owner(
                beneficial_owner_payload(application_id, ownership_pct=150.0),
                make_applicant_headers(application_id),
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api.create_application(
                application_payload(credit_score=900), make_applicant_headers("new-applicant")
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api.create_application(
                application_payload(country_code="MX"), make_applicant_headers("new-applicant")
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        # The application is DRAFT rather than UNDERWRITING, yet the schema check answers first.
        validate_error(
            api.create_credit_assessment(
                credit_assessment_payload(application_id, 1, "GUESS"),
                make_underwriting_officer_headers(),
            ),
            "ERR_INVALID_REQUEST",
            400,
        )


class TestOmittedOptionalInputsTakeTheirDeclaredDefaults:
    """Two payloads leave an optional field out and the server fills in the documented value."""

    def test_a_restricted_review_rule_without_an_uplift_defaults_to_zero(self):
        """The omitted uplift reads 0 while an explicit 400 is stored verbatim.

        PRD 3.1: "A `PROHIBITED` category blocks underwriting outright; a `RESTRICTED_REVIEW`
        category permits it but adds `reserve_uplift_bps` - an integer from 0 through 2000,
        defaulting to 0 when omitted - to the reserve percentage computed later."

        Design: Corner/entities/category_rule_omitted_reserve_uplift_defaults_to_zero
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")

        defaulted = create_category_rule(
            api, "7273", category="DATING_SERVICES", disposition="RESTRICTED_REVIEW"
        )
        assert defaulted["reserve_uplift_bps"] == 0
        assert defaulted["disposition"] == "RESTRICTED_REVIEW"

        explicit = create_category_rule(
            api,
            "7995",
            category="GAMBLING",
            disposition="RESTRICTED_REVIEW",
            reserve_uplift_bps=400,
        )
        assert explicit["reserve_uplift_bps"] == 400

    def test_a_stressed_forecast_without_a_multiplier_defaults_to_twenty_five_thousand(self):
        """An empty portfolio still records the default stress multiplier of 25000 basis points.

        PRD 3.13: "`stress_multiplier_bps` accompanies the stressed variant, defaults to 25000
        basis points, and must lie between 10000 and 100000 basis points inclusive; under
        `EXPECTED_LOSS` it is ignored even when supplied."

        Design: Corner/entities/forecast_omitted_stress_multiplier_defaults_to_25000
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")

        forecast = validate_success(
            api.create_portfolio_forecast(
                portfolio_forecast_payload("2026-08-01", "STRESSED"),
                make_portfolio_controller_headers(),
            ),
            201,
        )

        assert forecast["stress_multiplier_bps"] == 25_000
        assert forecast["merchant_count"] == 0
        assert forecast["unpaid_exposure_cents"] == 0
        assert forecast["gross_expected_loss_cents"] == 0
        assert forecast["net_expected_loss_cents"] == 0
        assert forecast["total_reserve_held_cents"] == 0
        assert forecast["coverage_gap_cents"] == 0
        assert forecast["reserve_adequacy_ratio_bps"] == 0
        assert forecast["required_additional_reserve_cents"] == 0
        assert forecast["projected_adequacy_ratio_bps"] == 0


class TestServerOwnedAndDerivedFields:
    """Ownership coverage, audit stamps and the immutable record types."""

    def test_the_ownership_total_is_recomputed_on_every_owner_insert(self):
        """40.00 then a further 35.50 leaves the application reading 75.50 percent.

        PRD 3.2: "Attaching an owner immediately recomputes the application's
        `owner_ownership_pct_total` as the sum of `ownership_pct` across all owners of that
        application, carried to two decimal places."

        PRD 3.1: "A new owner starts with `status` `PENDING`, with `sanctions_hit`, `pep_flag` and
        `id_verified` all false and `screened_at` null."

        Design: Corner/entities/ownership_total_recomputed_on_every_owner_insert
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id = create_draft_application(
            api, legal_business_name="Alderwood Supply LLC"
        )["id"]

        first = add_beneficial_owner(
            api, application_id, full_name="Mara Quinn", ownership_pct=40.00
        )
        assert first["status"] == "PENDING"
        assert first["sanctions_hit"] is False
        assert first["pep_flag"] is False
        assert first["id_verified"] is False
        assert first["screened_at"] is None
        assert float(read_application(api, application_id)["owner_ownership_pct_total"]) == 40.00

        add_beneficial_owner(api, application_id, full_name="Ivo Lang", ownership_pct=35.50)
        assert float(read_application(api, application_id)["owner_ownership_pct_total"]) == 75.50

    def test_identifiers_timestamps_and_versions_are_owned_by_the_server(self):
        """Submitting refreshes updated_at and version but never id or created_at.

        PRD 2.4 pins `created_at` as a creation stamp, `updated_at` as refreshed on every mutation
        and `version` as starting at 1 and incrementing on every mutation. It does not say which
        clock feeds the two audit stamps -- every stamp the PRD does route through the logical clock
        (`decided_at`, `screened_at`, `paid_at`, `executed_at`, `terminated_at`, ...) is named
        individually -- so only the relative behaviour of the audit fields is asserted here.

        PRD 2.4: "Most resources additionally carry three system-managed audit fields:
        `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording creation;
        `updated_at`, the same format, refreshed on every mutation of the row; and `version`, an
        integer that starts at 1 on creation and increments by one on every mutation, including
        mutations that only touch derived fields such as a recomputed trailing metric or a re-pinned
        reserve percentage."

        Design: Corner/entities/system_fields_id_timestamps_and_version_are_server_owned
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        created = create_draft_application(api, legal_business_name="Alderwood Supply LLC")
        application_id = created["id"]
        add_beneficial_owner(api, application_id, full_name="Mara Quinn", ownership_pct=100.00)

        assert created["version"] == 1

        set_clock(api, "2026-08-03T09:30:00Z")
        submitted = submit_application(api, application_id)

        assert submitted["id"] == application_id
        assert submitted["created_at"] == created["created_at"]
        assert submitted["updated_at"] != created["updated_at"]
        assert submitted["state"] == "SUBMITTED"
        assert submitted["version"] > created["version"]

    def test_append_only_rows_expose_neither_a_version_nor_an_updated_at(self):
        """A published screening rule carries an id and a created_at and nothing more mutable.

        PRD 2.4: "Three record types are immutable ledger or reference rows and therefore carry
        only `id` and `created_at` - they have neither `updated_at` nor `version`:
        `ProhibitedCategoryRule`, `ReserveLedgerEntry` and `MerchantDayActivity`."

        Design: Corner/entities/append_only_entities_expose_no_version_and_no_mutation_endpoint
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        create_category_rule(
            api,
            "7273",
            category="DATING_SERVICES",
            disposition="RESTRICTED_REVIEW",
            reserve_uplift_bps=250,
        )

        rows, meta = validate_paginated(
            api.list_category_rules(
                make_underwriting_officer_headers(), disposition="RESTRICTED_REVIEW"
            )
        )

        assert meta["total_count"] == 1
        rule = rows[0]
        assert rule["mcc_code"] == "7273"
        assert rule["reserve_uplift_bps"] == 250
        assert rule["id"]
        assert rule["created_at"]
        assert "version" not in rule
        assert "updated_at" not in rule


class TestChildRowsNeedTheirDeclaredParent:
    """A body-level foreign key that resolves to nothing stops the write."""

    def test_an_owner_and_an_assessment_both_require_an_existing_application(self):
        """Both bodies name the same unknown application, so both read the application 404.

        PRD 2.10: "For any path carrying more than one identifier, and for any request that also
        names a resource in its body, identifiers are resolved left to right and body references
        are resolved after path references."

        PRD 2.6: "Referenced applications first - including an `application_id` in a body and a
        `supersedes_application_id` - with `ERR_APPLICATION_NOT_FOUND` (404)."

        Design: Corner/entities/owner_and_assessment_require_an_existing_parent_application
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")

        validate_error(
            api.create_beneficial_owner(
                beneficial_owner_payload(UNKNOWN_ID), make_applicant_headers(UNKNOWN_ID)
            ),
            "ERR_APPLICATION_NOT_FOUND",
            404,
        )
        validate_error(
            api.create_credit_assessment(
                credit_assessment_payload(UNKNOWN_ID, 1), make_underwriting_officer_headers()
            ),
            "ERR_APPLICATION_NOT_FOUND",
            404,
        )

    def test_an_appeal_may_not_cite_the_termination_decision_of_another_merchant(self):
        """Merchant B's appeal names merchant A's executed decision and is refused.

        PRD 3.12: "The named decision must be in state `EXECUTED` and must belong to the same
        merchant as the appeal, or the filing is rejected with `ERR_APPEAL_DECISION_NOT_EXECUTED`."

        Design: Corner/entities/appeal_rejects_a_termination_decision_of_another_merchant
        """
        api = api_client
        first = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Alderwood Supply LLC",
            owners=[OwnerSpec(full_name="Mara Quinn")],
        )
        second = onboard_standard_merchant(
            api,
            clock="2026-08-01T00:00:00Z",
            legal_business_name="Bramble Foods LLC",
            owners=[OwnerSpec(full_name="Ivo Lang")],
        )
        set_clock(api, "2026-08-06T00:00:00Z")
        decision = terminate_merchant(api, first.merchant_id, "SUSPECTED_LAUNDERING")
        assert decision["state"] == "EXECUTED"

        response = api.create_appeal(
            appeal_payload(second.merchant_id, decision["id"]),
            make_merchant_user_headers(second.merchant_id),
        )

        validate_error(response, "ERR_APPEAL_DECISION_NOT_EXECUTED", 409)
        assert validate_success(
            api.get_merchant(second.merchant_id, make_risk_analyst_headers())
        )["account_state"] == "ACTIVE"
        _, meta = validate_paginated(
            api.list_merchant_appeals(
                second.merchant_id, make_merchant_user_headers(second.merchant_id)
            )
        )
        assert meta["total_count"] == 0
