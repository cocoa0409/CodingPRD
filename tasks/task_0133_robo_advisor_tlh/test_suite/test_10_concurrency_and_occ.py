"""Concurrency and optimistic-concurrency-control behaviors.

Coverage targets (PRD §2.5, §3.4, §3.8, §3.11):
- ERR_VERSION_CONFLICT when submitted version differs.
- Form1099B simultaneous create -> exactly one persists.
- Two simultaneous rebalance starts on same (account, quarter_key) ->
  exactly one wins.
"""
from __future__ import annotations

import pytest
from datetime import date

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_exactly_one_succeeds,
    create_form_1099b_payload,
    patch_client_payload,
    quarter_key_of,
    run_race,
    setup_account_with_drift,
    setup_active_client_with_account,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Optimistic concurrency — PRD §2.5
# ===========================================================================
class TestOptimisticConcurrency:

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.5: "When the caller supplies version, the server
        compares the submitted integer to the row's current version;
        on mismatch the request is rejected with ERR_VERSION_CONFLICT
        (HTTP 409)."

        Claim: PATCH /clients/{id} with version != current ->
        ERR_VERSION_CONFLICT.
        """
        client, _ = setup_active_client_with_account()
        # Submit a wrong version (current is at least 1, often
        # higher after activation + cascades).
        wrong_version = client["version"] + 999
        payload = patch_client_payload(
            full_name="New Name", version=wrong_version,
        )
        resp = api.patch_client(
            client["id"], payload,
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_patch_without_version_skips_check(self, api):
        """PRD §2.5: "When the caller omits the version field, the
        server applies the mutation without a concurrency check."

        Claim: PATCH /clients/{id} without version is accepted
        regardless of current version.
        """
        client, _ = setup_active_client_with_account()
        payload = patch_client_payload(full_name="New Name")
        resp = api.patch_client(
            client["id"], payload,
            TEST_USERS["compliance_officer_headers"],
        )
        data = validate_success(resp)
        assert data["full_name"] == "New Name"

    def test_patch_advances_version_by_one(self, api):
        """PRD §2.5: "A successful mutation always advances version
        by one and refreshes updated_at, whether or not version was
        supplied on the request."

        Claim: successful PATCH increments version by exactly 1.
        """
        client, _ = setup_active_client_with_account()
        before_version = client["version"]
        payload = patch_client_payload(full_name="Renamed")
        resp = api.patch_client(
            client["id"], payload,
            TEST_USERS["compliance_officer_headers"],
        )
        data = validate_success(resp)
        assert data["version"] == before_version + 1, (
            f"version must advance by exactly 1; before="
            f"{before_version} after={data['version']}"
        )


# ===========================================================================
# Form 1099-B race — PRD §3.11
# ===========================================================================
class TestFormCreateRace:

    def test_simultaneous_form_creates_only_one_persists(self, api):
        """PRD §3.11: "two simultaneous creates for the same pair
        serialize on the uniqueness constraint so that exactly one
        form persists and the loser receives ERR_FORM_ALREADY_EXISTS."

        Claim: two simultaneous POST /forms-1099b for the same
        (client, tax_year) -> exactly one succeeds (the other gets a
        4xx).
        """
        client, _ = setup_active_client_with_account()
        payload = create_form_1099b_payload(tax_year=2025)
        results = run_race(
            lambda: api.create_form_1099b(
                client["id"], payload,
                TEST_USERS["tax_admin_headers"],
            ),
            lambda: api.create_form_1099b(
                client["id"], payload,
                TEST_USERS["tax_admin_headers"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD names the loser error explicitly:
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_FORM_ALREADY_EXISTS.value],
        )


# ===========================================================================
# Rebalance race — PRD §3.8
# ===========================================================================
class TestRebalanceStartRace:

    def test_simultaneous_starts_only_one_persists(self, api):
        """PRD §3.8: "Two simultaneous starts on the same
        (account_id, quarter_key) serialize first-writer-wins on the
        uniqueness constraint; exactly one RebalanceRun is created,
        and the loser receives ERR_REBALANCE_ALREADY_IN_PROGRESS
        (HTTP 409)."

        Claim: two simultaneous rebalance starts -> exactly one wins.
        """
        scenario = setup_account_with_drift(target_drift_pct=5.50)
        account = scenario["account"]
        qk = quarter_key_of(date.today())
        results = run_race(
            lambda: api.start_rebalance(
                account["id"], {"quarter_key": qk},
                TEST_USERS["advisor_headers"],
            ),
            lambda: api.start_rebalance(
                account["id"], {"quarter_key": qk},
                TEST_USERS["advisor_headers"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser,
            [ApiErrorId.ERR_REBALANCE_ALREADY_IN_PROGRESS.value],
        )
