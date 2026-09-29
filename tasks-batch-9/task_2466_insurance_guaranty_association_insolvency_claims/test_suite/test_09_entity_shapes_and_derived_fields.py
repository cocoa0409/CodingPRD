"""Stored shapes, server-derived fields and the not-found codes of each collection."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_coverage_profile,
    assert_covered_claim,
    assert_insolvency,
    assert_instant_equals,
    assert_transferred_policy,
    assessment_payload,
    claim_payload,
    coverage_profile_payload,
    create_coverage_profile,
    create_insolvency,
    create_policy,
    get_success_data,
    insolvency_payload,
    is_iso8601_timestamp,
    member_insurer_payload,
    move_clock,
    policy_payload,
    read_insolvency,
    read_policy,
    setup_triggered_insolvency,
    trigger_insolvency,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["association_admin_headers"]
RECEIVER = TEST_USERS["receiver_liaison_headers"]
ANALYST = TEST_USERS["coverage_analyst_headers"]
ASSESSOR = TEST_USERS["assessment_officer_headers"]

GREAT_LAKES = {
    "insurer_name": "Great Lakes Mutual Casualty",
    "naic_code": "10001",
    "domiciliary_state_code": "MI",
    "liquidation_order_date": "2026-03-01",
}
FIRST_POLICY = {"policy_number": "PA-1001", "policyholder_name": "Ada Renner"}
SECOND_POLICY = {
    "policy_number": "PA-1002",
    "policyholder_name": "Boris Ilic",
    "annual_premium_cents": 365_000,
}
THIRD_POLICY = {
    "policy_number": "PA-1003",
    "policyholder_name": "Cora Diaz",
    "annual_premium_cents": 900_000,
}
HOMEOWNERS_MINIMAL = {
    "line_of_business": "HOMEOWNERS",
    "per_claim_cap_cents": 30_000_000,
    "per_policy_aggregate_cap_cents": 30_000_000,
    "unearned_premium_cap_cents": 1_000_000,
    "refund_priority_class": 2,
}
WORKERS_COMP_PROFILE = {
    "line_of_business": "WORKERS_COMPENSATION",
    "per_claim_cap_cents": 10_000_000,
    "per_policy_aggregate_cap_cents": 10_000_000,
    "unearned_premium_cap_cents": 1_000_000,
    "refund_priority_class": 1,
    "statutory_deductible_cents": 0,
}


class TestInsolvencyFileShape:
    """The insolvency file as created, as read back and as the order fills it in."""

    def test_a_new_file_lands_in_declared_with_an_empty_ledger(self):
        """The new file lands in `DECLARED`, with `status` defaulting to that value, with
        `triggered_at_utc` null, with every estate ledger bucket and every derived counter at 0, and
        with `distribution_sequence` at 0.

        Design: Corner/entities/insolvency_create_returns_the_declared_row_with_derived_deadlines
        """
        response = api_client.create_insolvency(insolvency_payload(**GREAT_LAKES), ADMIN)
        created = get_success_data(response, 201)

        assert_insolvency(created)
        assert created["status"] == "DECLARED", created["status"]
        assert created["version"] == 1, created["version"]
        assert created["triggered_at_utc"] is None
        assert created["policy_count"] == 0
        assert created["estate_remitted_cents"] == 0
        assert created["distribution_sequence"] == 0
        assert response.json()["data"]["naic_code"] == "10001"

    def test_the_triggering_event_derives_both_statutory_dates_from_the_order_date(self):
        """It computes `coverage_termination_date` as the `liquidation_order_date` advanced by 30
        calendar days — the date on which policies still in force are cancelled by operation of law.
        It computes `proof_of_claim_deadline_utc` as the `liquidation_order_date` advanced by 365
        calendar days, at the instant `00:00:00Z` on that date; filings at exactly that instant are
        still accepted, and only filings strictly after it are late.

        Design: Corner/entities/insolvency_create_returns_the_declared_row_with_derived_deadlines
        """
        env = setup_triggered_insolvency(policy_overrides=dict(FIRST_POLICY))
        insolvency = env["insolvency"]

        assert insolvency["coverage_termination_date"] == "2026-03-31", (
            f"2026-03-01 advanced by 30 days, got {insolvency['coverage_termination_date']}"
        )
        assert_instant_equals(
            insolvency["proof_of_claim_deadline_utc"],
            "2027-03-01T00:00:00Z",
            f"2026-03-01 advanced by 365 days, got {insolvency['proof_of_claim_deadline_utc']}",
        )

    def test_reading_the_file_back_returns_the_stored_row_unchanged(self):
        """Every persisted resource carries an `id` that is a server-minted UUID with no type prefix;
        clients never supply an `id`.

        Design: Corner/entities/insolvency_get_returns_the_stored_row
        """
        created = create_insolvency(**GREAT_LAKES)
        response = api_client.get_insolvency(created["id"], ADMIN)
        fetched = get_success_data(response, 200)

        assert fetched["id"] == created["id"]
        assert fetched["naic_code"] == "10001", fetched["naic_code"]
        assert fetched["insurer_name"] == "Great Lakes Mutual Casualty"
        assert fetched["version"] == 1, (
            f"a read must not mutate the row, got version {fetched['version']}"
        )
        assert fetched["status"] == "DECLARED", fetched["status"]


class TestPolicyBookReads:
    """Listing, page windows and the fields the order fills in on a policy."""

    def test_the_policy_list_reports_the_window_and_the_full_match_count(self):
        """The `meta` block of a list response carries `limit` and `offset` echoing the effective
        values used, `total_count` giving the number of rows matching the filter before the page
        window is applied, and `has_more` set to true exactly when rows remain beyond the current
        window.

        Design: Corner/entities/policies_list_paginates_with_total_count_and_has_more
        """
        create_coverage_profile()
        insolvency = create_insolvency(**GREAT_LAKES)
        for spec in (FIRST_POLICY, SECOND_POLICY, THIRD_POLICY):
            create_policy(insolvency["id"], **spec)

        first_page, first_meta = validate_paginated(
            api_client.list_policies(
                RECEIVER, {"insolvency_id": insolvency["id"], "limit": 2, "offset": 0}
            )
        )
        assert len(first_page) == 2, f"the window holds two rows, got {len(first_page)}"
        assert first_meta["total_count"] == 3, first_meta["total_count"]
        assert first_meta["limit"] == 2 and first_meta["offset"] == 0
        assert first_meta["has_more"] is True, (
            "a third row remains beyond the window, so has_more must be true"
        )

        second_page, second_meta = validate_paginated(
            api_client.list_policies(
                RECEIVER, {"insolvency_id": insolvency["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(second_page) == 1, f"the tail window holds one row, got {len(second_page)}"
        assert second_meta["total_count"] == 3
        assert second_meta["offset"] == 2
        assert second_meta["has_more"] is False

        assert read_insolvency(insolvency["id"])["policy_count"] == 3

    def test_the_order_sets_the_cancellation_date_and_the_unexpired_day_count(self):
        """A directly keyed policy is created in `IMPORTED` with `source_transfer_id` null, with
        `cancellation_date` null, `unexpired_days` 0, `aggregate_paid_cents` 0 and `up_refund_filed`
        false, and the insolvency file's `policy_count` is recomputed.

        Design: Corner/entities/policy_unexpired_days_is_computed_by_the_liquidation_order
        """
        create_coverage_profile()
        insolvency = create_insolvency(**GREAT_LAKES)
        imported = create_policy(insolvency["id"], **FIRST_POLICY)

        assert imported["status"] == "IMPORTED", imported["status"]
        assert imported["cancellation_date"] is None
        assert imported["unexpired_days"] == 0
        assert imported["up_refund_filed"] is False

        trigger_insolvency(insolvency["id"])
        cancelled = read_policy(imported["id"])

        assert_transferred_policy(cancelled)
        assert cancelled["status"] == "CANCELLED_BY_ORDER", cancelled["status"]
        assert cancelled["cancellation_date"] == "2026-03-31", (
            "the earlier of the term end and the coverage termination date, got "
            f"{cancelled['cancellation_date']}"
        )
        assert cancelled["unexpired_days"] == 184, (
            f"whole days from 2026-03-31 to 2026-10-01, got {cancelled['unexpired_days']}"
        )
        assert cancelled["up_refund_filed"] is False

    def test_keying_a_policy_without_its_number_is_a_request_shape_failure(self):
        """Request bodies are validated for shape on every endpoint: every required field must be
        present, every value must have the declared type, every enumerated field must carry a declared
        member, every numeric field must fall in its declared range, and no unknown field is accepted.
        Any of these failures is `ERR_INVALID_REQUEST` (HTTP 400).

        Design: Corner/entities/policy_create_without_policy_number_returns_invalid_request
        """
        create_coverage_profile()
        insolvency = create_insolvency(**GREAT_LAKES)
        body = policy_payload(insolvency["id"], **FIRST_POLICY)
        del body["policy_number"]

        validate_error(api_client.create_policy(body, RECEIVER), "ERR_INVALID_REQUEST", 400)
        assert read_insolvency(insolvency["id"])["policy_count"] == 0, (
            "the refused body must not reach the policy book"
        )


class TestCoverageConfigurationRow:
    """The one entity that is configuration rather than lifecycle."""

    def test_the_optional_configuration_fields_take_their_declared_defaults(self):
        """`statutory_deductible_cents` is subtracted from every covered claim in the line and
        defaults to 10 000 cents, which is one hundred dollars. `net_worth_exclusion_threshold_cents`
        is the policyholder net worth at or above which a claim in the line is excluded from coverage
        altogether, and defaults to 2 500 000 000 cents, which is twenty-five million dollars.
        `covers_punitive_damages` is a boolean that defaults to false; when it is false, the punitive
        portion of a demand is left out of the covered loss basis in that line.

        Design: Corner/entities/coverage_profile_omitted_optional_fields_take_declared_defaults
        """
        profile = get_success_data(
            api_client.create_coverage_profile(
                coverage_profile_payload(**HOMEOWNERS_MINIMAL), ADMIN
            ),
            201,
        )

        assert_coverage_profile(profile)
        assert profile["statutory_deductible_cents"] == 10_000, (
            profile["statutory_deductible_cents"]
        )
        assert profile["net_worth_exclusion_threshold_cents"] == 2_500_000_000, (
            profile["net_worth_exclusion_threshold_cents"]
        )
        assert profile["covers_punitive_damages"] is False
        assert profile["cap_order_mode"] == "OFFSET_THEN_CAP", profile["cap_order_mode"]

    def test_a_listed_configuration_row_exposes_neither_updated_at_nor_version(self):
        """One resource type is deliberately exempt. The statutory coverage configuration row is a
        configuration record rather than a lifecycle record: it carries only `id` and `created_at`. It
        has no `updated_at` field and no `version` field at all, and neither field should appear in
        its representation.

        Design: Corner/entities/coverage_profile_carries_no_version_field_and_no_update_endpoint
        """
        create_coverage_profile()
        create_coverage_profile(**WORKERS_COMP_PROFILE)

        rows, meta = validate_paginated(api_client.list_coverage_profiles(ADMIN))
        assert meta["total_count"] == 2, meta["total_count"]
        assert len(rows) == 2, len(rows)
        for row in rows:
            assert_coverage_profile(row)
            assert "updated_at" not in row, "the configuration row has no updated_at"
            assert "version" not in row, "the configuration row has no version"
            assert is_iso8601_timestamp(row["created_at"])


class TestServerStampedAndReferencedFields:
    """Fields the server owns, and the codes for foreign keys that name nothing."""

    def test_the_claim_filing_instant_comes_from_the_logical_clock(self):
        """Time in this system is a logical clock, never wall-clock time. The clock's startup default
        is exactly `2026-08-01T00:00:00Z`, and the server never falls back to real time. Every
        `created_at`, and every domain timestamp — `filed_at_utc` on a covered claim, `triggered_at_utc`
        on an insolvency file, `certified_at_utc` on an assessment, `recommended_at_utc` on a claim
        recommendation and `responded_at_utc` on a referral — is stamped from that clock.

        Design: Corner/entities/claim_filed_at_utc_is_stamped_from_the_logical_clock
        """
        env = setup_triggered_insolvency(policy_overrides=dict(FIRST_POLICY))
        move_clock("2026-09-10T12:00:00Z")

        claim = get_success_data(
            api_client.create_claim(
                claim_payload(
                    env["insolvency"]["id"],
                    env["policy"]["id"],
                    claim_number="C-1",
                    claimant_name="Ben Ortiz",
                    gross_loss_cents=900_000,
                ),
                ANALYST,
            ),
            201,
        )

        assert_covered_claim(claim)
        assert_instant_equals(
            claim["filed_at_utc"],
            "2026-09-10T12:00:00Z",
            f"the filing instant is the logical clock's, got {claim['filed_at_utc']}",
        )
        assert claim["status"] == "RECEIVED", claim["status"]
        assert claim["version"] == 1, claim["version"]

    def test_reading_a_claim_that_was_never_minted_reports_the_claim_not_found_code(self):
        """Existence of the claim named first in the path, evaluated after insolvency rows →
        `ERR_CLAIM_NOT_FOUND`.

        Design: Corner/entities/claim_get_with_unknown_id_returns_claim_not_found
        """
        response = api_client.get_claim(NON_EXISTENT_UUID, ANALYST)
        validate_error(response, "ERR_CLAIM_NOT_FOUND", 404)
        assert response.json()["response_type"] == "error"

    def test_a_claim_naming_an_unknown_policy_reports_the_referenced_row_code(self):
        """A foreign key supplied in a request body rather than the path — for example `insolvency_id`
        or `policy_id` — that does not resolve to an existing row yields `ERR_REFERENCED_ROW_NOT_FOUND`
        (HTTP 404); this applies to `POST /policies`, `POST /claims`, `POST /assessments` and
        `POST /insolvencies/{id}/poc-transfers`.

        Design: Corner/entities/claim_create_with_unknown_policy_id_returns_referenced_row_not_found
        """
        env = setup_triggered_insolvency(policy_overrides=dict(FIRST_POLICY))
        body = claim_payload(
            env["insolvency"]["id"],
            NON_EXISTENT_UUID,
            claim_number="C-1",
            claimant_name="Ben Ortiz",
            gross_loss_cents=900_000,
        )

        validate_error(
            api_client.create_claim(body, ANALYST), "ERR_REFERENCED_ROW_NOT_FOUND", 404
        )
        rows, _ = validate_paginated(
            api_client.list_claims(ANALYST, {"insolvency_id": env["insolvency"]["id"]})
        )
        assert rows == [], "no claim may be stored against a policy that does not exist"

    def test_an_assessment_naming_an_unknown_file_is_refused_before_the_premium_base(self):
        """Existence of every foreign key supplied in the request body →
        `ERR_REFERENCED_ROW_NOT_FOUND`.

        Design: Corner/entities/assessment_create_with_unknown_insolvency_returns_referenced_row_not_found
        """
        get_success_data(
            api_client.create_member_insurer(
                member_insurer_payload(
                    naic_code="20001",
                    insurer_name="Huron Standard Insurance",
                    direct_written_premium_cents=10_000_000,
                ),
                ADMIN,
            )
        )

        response = api_client.create_assessment(
            assessment_payload(NON_EXISTENT_UUID, needed_amount_cents=150_000), ASSESSOR
        )
        validate_error(response, "ERR_REFERENCED_ROW_NOT_FOUND", 404)

    def test_a_member_cap_rate_outside_the_declared_range_is_refused(self):
        """`annual_cap_rate_bps` is optional and defaults to 200; it expresses the per-member annual
        assessment ceiling in basis points of the member's own premium base and must be an integer
        between 0 and 200 inclusive, so 200 basis points — two percent of premium — is both the
        default and the statutory maximum, and a regulator-reduced rate can only be lower.

        Design: Corner/entities/member_insurer_cap_rate_above_the_declared_range_is_rejected
        """
        response = api_client.create_member_insurer(
            member_insurer_payload(
                naic_code="20001",
                insurer_name="Huron Standard Insurance",
                direct_written_premium_cents=10_000_000,
                annual_cap_rate_bps=250,
            ),
            ADMIN,
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        accepted = get_success_data(
            api_client.create_member_insurer(
                member_insurer_payload(
                    naic_code="20001",
                    insurer_name="Huron Standard Insurance",
                    direct_written_premium_cents=10_000_000,
                    annual_cap_rate_bps=200,
                ),
                ADMIN,
            )
        )
        assert accepted["annual_cap_rate_bps"] == 200, (
            f"the statutory maximum itself is accepted, got {accepted['annual_cap_rate_bps']}"
        )
