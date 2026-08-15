"""Copay assistance matching: foundation pool selection, pool-balance
conservation across reserve/release, OCC stale-version rejection, and the
segregation-of-duties release guard."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_copay_assistance,
    create_approved_enrollment,
    create_pool,
    enrollment_version,
    get_enrollment,
    make_financial_counselor_headers,
    match_assistance,
    match_assistance_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

CM = TEST_USERS["case_manager_headers"]
FC = TEST_USERS["financial_counselor_headers"]


class TestFoundationSelector:

    def test_foundation_selector_tie_break_earliest_start_date(self):
        """PRD section 3.4: "Eligible candidates rank by `coverage_pct`
        descending; ties break toward the earliest `start_date`, and any
        remaining tie breaks toward the earliest `created_at`."
        PRD section 3.4: "On success, the selected pool's
        `remaining_balance_cents` is debited by `grant_amount_cents`, and the
        new assistance copies the pool's `coverage_pct`, records the pool in
        `foundation_pool_id`, sets `annual_benefit_cap_cents` to the pool's
        `grant_amount_cents`, and leaves `per_fill_cap_cents` null."

        Design: Corner/calculations/foundation_selector_tie_break_earliest_start_date
        """
        ctx = create_approved_enrollment(patient_ref="PAT-C3")
        # Pool B is created FIRST so creation order cannot explain the pick.
        pool_b = create_pool(name="FundB", start_date="2026-03-01")
        pool_a = create_pool(name="FundA", start_date="2026-01-01")

        assistance = match_assistance(
            ctx["enrollment"]["id"], "FOUNDATION", counselor_id="fc-1")
        assert_copay_assistance(assistance)
        assert assistance["foundation_pool_id"] == pool_a["id"], (
            f"coverage tie must break to the earliest start_date "
            f"({pool_a['id']}), got {assistance['foundation_pool_id']}"
        )
        assert assistance["foundation_pool_id"] != pool_b["id"]
        assert assistance["annual_benefit_cap_cents"] == 200_000, \
            "grant_amount_cents is copied onto the assistance"
        assert assistance["coverage_pct"] == 80
        assert assistance["per_fill_cap_cents"] is None

    def test_foundation_selector_empty_pool_set_returns_error(self):
        """PRD section 3.4: "A pool is eligible when its `diagnosis_code`
        exactly matches the enrollment's `diagnosis_code`, when the current
        logical clock date falls on or after the pool's `start_date` and on
        or before its `end_date`, and when the pool's
        `remaining_balance_cents` is at least its `grant_amount_cents`."
        PRD section 3.4: "An empty candidate set rejects the match with
        `ERR_NO_ELIGIBLE_FOUNDATION`: no assistance is created, no pool is
        mutated, and the enrollment's `version` is not incremented."

        Design: Corner/calculations/foundation_selector_empty_pool_set_returns_error
        """
        ctx = create_approved_enrollment(patient_ref="PAT-C4")
        create_pool(name="FundD", diagnosis_code="X99")
        create_pool(name="FundE", start_date="2027-01-01",
                    end_date="2027-12-31")
        create_pool(name="FundF", total_funding_cents=100_000)

        version = enrollment_version(ctx["enrollment"]["id"])
        resp = api_client.match_copay_assistance(
            ctx["enrollment"]["id"],
            match_assistance_payload(version, assistance_type="FOUNDATION"),
            FC)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_FOUNDATION)

        _, meta = validate_paginated(
            api_client.list_copay_assistances(ctx["enrollment"]["id"], FC))
        assert meta["total_count"] == 0, "the fallback creates nothing"
        assert enrollment_version(ctx["enrollment"]["id"]) == version, \
            "the enrollment's version is not incremented on the fallback"


class TestPoolReserveReleaseConservation:

    def test_foundation_match_debits_pool_by_grant_amount(self):
        """PRD section 3.1: "At creation, the pool's `remaining_balance_cents`
        initializes to `total_funding_cents`; thereafter it decreases by
        `grant_amount_cents` each time a patient is matched against the pool
        and increases by a grant's undisbursed remainder whenever a grant is
        released or superseded."

        Design: Difficulty/compensating_invariant/foundation_pool_reserve_release_conservation
        """
        pool = create_pool(name="FundA", coverage_pct=80)
        ctx = create_approved_enrollment(patient_ref="PAT-R")
        match_assistance(
            ctx["enrollment"]["id"], "FOUNDATION", counselor_id="fc-1")
        resp = api_client.get_foundation_pool(pool["id"], FC)
        pool_after = validate_success(resp, expected_status=200)
        assert pool_after["remaining_balance_cents"] == 4_800_000, (
            f"reserve must debit the grant: 5000000 - 200000 = 4800000, "
            f"got {pool_after['remaining_balance_cents']}"
        )

    def test_release_by_other_counselor_restores_pool_exactly(self):
        """PRD section 3.4: "Release computes `returned_cents` as the
        `annual_benefit_cap_cents` minus the cumulative `disbursed_cents` —
        for an `EXHAUSTED` record this equals the full cap, since
        disbursement has reached the cap — and, for a `FOUNDATION` grant,
        credits that amount back to the pool's `remaining_balance_cents`."
        PRD section 3.4: "Manual release carries a segregation-of-duties
        guard: the releasing user's `X-User-ID` must differ from the
        record's `matched_by_user_id`, and a same-user release attempt is
        rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403)."

        Design: Difficulty/compensating_invariant/foundation_pool_reserve_release_conservation
        """
        pool = create_pool(name="FundA", coverage_pct=80)
        ctx = create_approved_enrollment(patient_ref="PAT-R2")
        assistance = match_assistance(
            ctx["enrollment"]["id"], "FOUNDATION", counselor_id="fc-1")

        resp = api_client.release_copay_assistance(
            assistance["id"], make_financial_counselor_headers("fc-2"))
        released = validate_success(resp, expected_status=200)
        assert released["status"] == "RELEASED"
        assert released["returned_cents"] == 200_000, \
            "nothing was disbursed, so the full grant returns"

        pool_after = validate_success(
            api_client.get_foundation_pool(pool["id"], FC), 200)
        assert pool_after["remaining_balance_cents"] == 5_000_000, (
            f"reserve paired with its compensating release must conserve the "
            f"pool exactly, got {pool_after['remaining_balance_cents']}"
        )


class TestMatchConcurrencyAndReleaseGuard:

    def test_occ_match_with_stale_version_rejected(self):
        """PRD section 2.9: "Running a copay-assistance match requires the
        request body to carry `expected_enrollment_version`, holding the
        enrollment `version` the client last observed; if that value does
        not match the enrollment's current `version`, the match is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."
        PRD section 2.9: "A successful match supersedes any non-terminal
        assistance and increments the enrollment's `version` by one, so a
        writer carrying the previously observed version would otherwise be
        acting on a stale view of the enrollment."

        Design: Corner/cross_cutting_layers/occ_match_with_stale_version_rejected
        """
        ctx = create_approved_enrollment(patient_ref="PAT-O1")
        enr_id = ctx["enrollment"]["id"]
        observed = enrollment_version(enr_id)

        first = validate_success(api_client.match_copay_assistance(
            enr_id, match_assistance_payload(observed), FC), expected_status=201)
        assert enrollment_version(enr_id) == observed + 1, \
            "a successful match increments the enrollment's version by one"

        resp = api_client.match_copay_assistance(
            enr_id, match_assistance_payload(observed), FC)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        data, _ = validate_paginated(api_client.list_copay_assistances(enr_id, FC))
        assert data[0]["id"] == first["id"]
        assert data[0]["status"] == "ACTIVE", \
            "the rejected stale write must not supersede the existing assistance"

    def test_financial_counselor_release_by_matcher_rejected(self):
        """PRD section 3.4: "Manual release carries a segregation-of-duties
        guard: the releasing user's `X-User-ID` must differ from the
        record's `matched_by_user_id`, and a same-user release attempt is
        rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403)."
        PRD section 3.4: "Every new assistance begins with
        `remaining_annual_benefit_cents` equal to its
        `annual_benefit_cap_cents`, `disbursed_cents` at zero, and the
        matching counselor's identity stamped into `matched_by_user_id`."

        Design: Corner/rbac/financial_counselor_release_by_matcher_rejected
        """
        ctx = create_approved_enrollment(patient_ref="PAT-R4")
        assistance = match_assistance(
            ctx["enrollment"]["id"], "COPAY_CARD", counselor_id="fc-1")
        assert assistance["matched_by_user_id"] == "fc-1"

        resp = api_client.release_copay_assistance(
            assistance["id"], make_financial_counselor_headers("fc-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTY)

        resp = api_client.release_copay_assistance(
            assistance["id"], make_financial_counselor_headers("fc-2"))
        released = validate_success(resp, expected_status=200)
        assert released["status"] == "RELEASED", \
            "the same role under a different identity may release"
