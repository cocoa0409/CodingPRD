"""Registration and intake: household/vendor/policy/source creation rules,
application creation guards, and the two resource-capacity rules (funding
period overlap, household service-month bucket)."""
from test_helpers import (
    CLOCK_DEFAULT,
    ApiErrorId,
    assert_application,
    assert_clock_instant,
    assert_funding_source,
    assert_household,
    assert_policy,
    assert_source_balance_invariant,
    create_active_policy,
    create_application,
    create_application_payload,
    create_funding_source,
    create_funding_source_payload,
    create_household,
    create_household_payload,
    create_policy_payload,
    create_vendor,
    get_application,
    make_caseworker_headers,
    TEST_USERS,
    validate_error,
    validate_success,
)

CW1 = TEST_USERS["caseworker_headers"]
PM1 = TEST_USERS["program_manager_headers"]


class TestRegistrationFields:
    def test_household_create_missing_annual_income_rejected(self, api):
        """PRD §2.9: "Request well-formedness — required fields present, enum
        values valid, integer-cent fields positive where declared, `service_month`
        matching the YYYY-MM shape, and outcome-conditional fields supplied (for
        example `confirmed_amount_cents` when a verification completes with outcome
        `PASSED`), else `ERR_INVALID_REQUEST`."
        PRD §3.2: "A `Caseworker` registers it with the `head_of_household_name`,
        the street `address`, a contact `phone`, the `household_size` (at least 1),
        and the `annual_income_cents` (zero or more)."

        Design: Corner/entities/household_create_missing_required_field_rejected
        """
        payload = create_household_payload()
        del payload["annual_income_cents"]
        resp = api.create_household(payload, CW1)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_policy_defaults_applied_on_create(self, api):
        """PRD §3.1: "Four policy flags shape intake: `appeal_window_days`, which
        defaults to 30 when omitted and must be greater than zero, and three
        documentation toggles — `require_eviction_notice` (default true),
        `require_lease_ledger` (default false), and `require_utility_bill`
        (default true). A new policy is born in `DRAFT` status."

        Design: Corner/entities/policy_defaults_applied_on_create
        """
        resp = api.create_policy(create_policy_payload(name="Defaults"), PM1)
        data = validate_success(resp, 201)
        assert_policy(data)
        assert data["appeal_window_days"] == 30
        assert data["require_eviction_notice"] is True
        assert data["require_lease_ledger"] is False
        assert data["require_utility_bill"] is True
        assert data["status"] == "DRAFT"

    def test_application_created_in_intake_with_intake_caseworker_recorded(self, api):
        """PRD §3.2: "A created application starts in `INTAKE`, records the acting
        operator as `intake_caseworker_id` (the segregation-of-duties anchor for
        everything that follows), and leaves `active_award_id` empty; `submitted_at`,
        `waitlisted_at`, `denied_at`, and `closed_at` stay empty until their
        respective events occur, and `denial_reason` stays empty until a denial."

        Design: Corner/entities/application_created_in_intake_with_intake_caseworker_recorded
        """
        vendor = create_vendor("LANDLORD")
        household = create_household()
        resp = api.create_application(
            create_application_payload(household["id"], vendor["id"]),
            make_caseworker_headers("cw-9"),
        )
        data = validate_success(resp, 201)
        assert_application(data)
        assert data["status"] == "INTAKE"
        assert data["intake_caseworker_id"] == "cw-9"
        assert data.get("active_award_id") in (None, ""), "active_award_id must start empty"
        assert data.get("policy_id") in (None, ""), "policy_id is pinned only at submit"

    def test_application_get_not_found_returns_404(self, api):
        """PRD §2.9: "Existence — path identifiers and body foreign keys reference
        existing resources, validated left to right, else `ERR_NOT_FOUND`."

        Design: Corner/entities/application_get_not_found_returns_404
        """
        resp = api.get_application("3f4a9b2c-1111-4222-8333-444455556666", CW1)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_application_invalid_enum_category_rejected(self, api):
        """PRD §2.9: "Request well-formedness — required fields present, enum
        values valid, integer-cent fields positive where declared, `service_month`
        matching the YYYY-MM shape, and outcome-conditional fields supplied (for
        example `confirmed_amount_cents` when a verification completes with outcome
        `PASSED`), else `ERR_INVALID_REQUEST`."
        PRD §3.2: "a `category` of `RENT` or `UTILITY`"

        Design: Corner/entities/application_invalid_enum_category_rejected
        """
        vendor = create_vendor("LANDLORD")
        household = create_household()
        resp = api.create_application(
            create_application_payload(household["id"], vendor["id"], category="MEDICAL"),
            CW1,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_application_fk_to_missing_household_returns_404(self, api):
        """PRD §2.9: "Existence — path identifiers and body foreign keys reference
        existing resources, validated left to right, else `ERR_NOT_FOUND`."

        Design: Corner/entities/application_fk_to_missing_household_returns_404
        """
        vendor = create_vendor("LANDLORD")
        resp = api.create_application(
            create_application_payload(
                "9f4a9b2c-1111-4222-8333-444455556666", vendor["id"]
            ),
            CW1,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_service_month_malformed_rejected(self, api):
        """PRD §2.9: "Request well-formedness — required fields present, enum
        values valid, integer-cent fields positive where declared, `service_month`
        matching the YYYY-MM shape, and outcome-conditional fields supplied (for
        example `confirmed_amount_cents` when a verification completes with outcome
        `PASSED`), else `ERR_INVALID_REQUEST`."
        PRD §3.2: "the `service_month` the assistance covers, formatted YYYY-MM."

        Design: Corner/validations/service_month_malformed_rejected
        """
        vendor = create_vendor("LANDLORD")
        household = create_household()
        resp = api.create_application(
            create_application_payload(
                household["id"], vendor["id"], service_month="2026-8"
            ),
            CW1,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_vendor_category_mismatch_on_application_create(self, api):
        """PRD §3.2: "First, the category must match the vendor's type: `RENT`
        applications require a `LANDLORD` vendor and `UTILITY` applications a
        `UTILITY` vendor, with mismatches rejected as `ERR_VENDOR_CATEGORY_MISMATCH`."

        Design: Corner/validations/vendor_category_mismatch_on_application_create
        """
        vendor = create_vendor(vendor_type="UTILITY", name="City Power & Light")
        household = create_household()
        resp = api.create_application(
            create_application_payload(household["id"], vendor["id"], category="RENT"),
            CW1,
        )
        validate_error(resp, ApiErrorId.ERR_VENDOR_CATEGORY_MISMATCH)


class TestHouseholdServiceMonthBucket:
    def test_same_household_category_month_conflict_rejected(self, api):
        """PRD §3.2: "Second, the same household may not hold another application
        for the same category and `service_month` in any status other than
        `DENIED`, `WITHDRAWN`, or `CLOSED`; a conflicting live application
        triggers `ERR_SERVICE_MONTH_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/household_service_month_bucket_capacity
        """
        vendor = create_vendor("LANDLORD")
        household = create_household()
        first = create_application(household["id"], vendor["id"])  # RENT 2026-08
        assert first["status"] == "INTAKE"
        resp = api.create_application(
            create_application_payload(
                household["id"], vendor["id"], requested_amount_cents=5000
            ),
            CW1,
        )
        validate_error(resp, ApiErrorId.ERR_SERVICE_MONTH_CONFLICT)

    def test_other_category_or_month_allowed_and_withdraw_frees_bucket(self, api):
        """PRD §3.2: "Second, the same household may not hold another application
        for the same category and `service_month` in any status other than
        `DENIED`, `WITHDRAWN`, or `CLOSED`; a conflicting live application
        triggers `ERR_SERVICE_MONTH_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/household_service_month_bucket_capacity
        """
        vendor = create_vendor("LANDLORD")
        utility_vendor = create_vendor(vendor_type="UTILITY", name="City Power & Light")
        household = create_household()
        first = create_application(household["id"], vendor["id"])  # RENT 2026-08
        # Different category in the same month is a different bucket.
        other_category = create_application(
            household["id"], utility_vendor["id"], category="UTILITY",
            requested_amount_cents=5000,
        )
        assert other_category["status"] == "INTAKE"
        # Same category in a different month is a different bucket.
        other_month = create_application(
            household["id"], vendor["id"], requested_amount_cents=5000,
            service_month="2026-09",
        )
        assert other_month["status"] == "INTAKE"
        # Withdrawing the first application releases the RENT 2026-08 bucket.
        withdrawn = validate_success(api.withdraw_application(first["id"], CW1))
        assert withdrawn["status"] == "WITHDRAWN"
        refill = create_application(
            household["id"], vendor["id"], requested_amount_cents=7000
        )
        assert refill["status"] == "INTAKE"
        assert get_application(refill["id"])["status"] == "INTAKE"


class TestPolicyActivation:
    def test_policy_supersede_retires_prior_active(self, api):
        """PRD §3.1: "Activation by a `ProgramManager` moves a `DRAFT` policy to
        `ACTIVE` and simultaneously retires whichever policy was previously
        `ACTIVE` to `RETIRED`, so at most one policy is `ACTIVE` at any moment;
        both the newly activated policy and the retired one bump their `version`.
        Attempting to activate a policy that is not in `DRAFT` fails with
        `ERR_INVALID_POLICY_STATE`."

        Design: Corner/state_machines/policy_supersede_retires_prior_active
        """
        policy_a = validate_success(
            api.create_policy(create_policy_payload(name="A"), PM1), 201
        )
        activated_a = validate_success(api.activate_policy(policy_a["id"], PM1), 200)
        assert activated_a["status"] == "ACTIVE"
        policy_b = validate_success(
            api.create_policy(
                create_policy_payload(
                    name="B", max_annual_benefit_cents=90000,
                    rent_cap_cents=45000, utility_cap_cents=35000,
                    income_limit_cents=4500000,
                ),
                PM1,
            ),
            201,
        )
        activated_b = validate_success(api.activate_policy(policy_b["id"], PM1), 200)
        assert activated_b["status"] == "ACTIVE"
        retired_a = validate_success(api.get_policy(policy_a["id"], PM1), 200)
        assert retired_a["status"] == "RETIRED", "the previously ACTIVE policy is superseded"
        assert retired_a["version"] > activated_a["version"], "retirement bumps the version"
        resp = api.activate_policy(policy_a["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_INVALID_POLICY_STATE)


class TestFunderPeriodOverlap:
    def _create_source_m(self, api):
        return create_funding_source(
            name="M", funder_name="Rotary", source_type="GRANT_RESTRICTED",
            allowed_categories=["RENT"],
            period_start="2026-01-01T00:00:00Z", period_end="2026-07-01T00:00:00Z",
            total_budget_cents=50000,
        )

    def test_same_funder_true_overlap_rejected(self, api):
        """PRD §3.1: "One structural guard applies at creation: the new source's
        half-open period must not overlap the period of any other non-`CLOSED`
        source from the same `funder_name`, though adjacency is permitted — one
        source's `period_end` equal to another's `period_start` does not count as
        overlap. A violation is rejected with `ERR_SOURCE_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/funder_period_half_open_overlap
        """
        self._create_source_m(api)
        resp = api.create_funding_source(
            create_funding_source_payload(
                name="N", funder_name="Rotary", source_type="GRANT_RESTRICTED",
                allowed_categories=["UTILITY"],
                period_start="2026-05-01T00:00:00Z", period_end="2026-09-01T00:00:00Z",
                total_budget_cents=50000,
            ),
            PM1,
        )
        validate_error(resp, ApiErrorId.ERR_SOURCE_PERIOD_OVERLAP)

    def test_adjacent_period_and_other_funder_allowed(self, api):
        """PRD §3.1: "One structural guard applies at creation: the new source's
        half-open period must not overlap the period of any other non-`CLOSED`
        source from the same `funder_name`, though adjacency is permitted — one
        source's `period_end` equal to another's `period_start` does not count as
        overlap. A violation is rejected with `ERR_SOURCE_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/funder_period_half_open_overlap
        """
        self._create_source_m(api)
        # Adjacency: O starts exactly at M's period_end — not an overlap.
        resp_o = api.create_funding_source(
            create_funding_source_payload(
                name="O", funder_name="Rotary", source_type="GRANT_RESTRICTED",
                allowed_categories=["RENT"],
                period_start="2026-07-01T00:00:00Z", period_end="2027-01-01T00:00:00Z",
                total_budget_cents=50000,
            ),
            PM1,
        )
        source_o = validate_success(resp_o, 201)
        assert source_o["status"] == "ACTIVE"
        # Overlap scope is per-funder: Other Org may overlap Rotary freely.
        resp_p = api.create_funding_source(
            create_funding_source_payload(
                name="P", funder_name="Other Org", source_type="DONOR_UNRESTRICTED",
                allowed_categories=["RENT", "UTILITY"],
                period_start="2026-05-01T00:00:00Z", period_end="2026-09-01T00:00:00Z",
                total_budget_cents=50000,
            ),
            PM1,
        )
        source_p = validate_success(resp_p, 201)
        assert source_p["status"] == "ACTIVE"
