"""Account closure: terminal lockdown, OCC stale-version handling, the
request-shape priority tier, and the garnishment-state gate."""
from test_helpers import (
    MANAGER,
    OFFICER,
    ApiErrorId,
    api_client,
    close_with_fresh_version,
    get_account,
    open_account,
    post_transaction,
    register_garnishment,
    resolve_garnishment,
    validate_error,
    validate_success,
)


class TestClosureGatedOnGarnishment:

    def test_close_blocked_while_garnishment_funds_held(self):
        """PRD section 3.9: "Closure is also barred while legal or
        transitional work is in flight: the restriction must be `NONE` with
        no garnishment in `FUNDS_HELD`, no deceased case in `REPORTED`,
        `VERIFIED`, or `RELEASE_PENDING`, and no title change in `SUBMITTED`
        — any of these rejects with `ERR_CLOSURE_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/account_closure_gated_on_garnishment_state
        """
        acct = open_account(opening_deposit_cents=80000,
                            primary_owner_name="Cls C", owner_tax_id="T17")
        order = register_garnishment(acct["id"], 30000, "2026-08-01",
                                     exemption_method="FEDERAL_LOOKBACK")
        assert order["status"] == "FUNDS_HELD"

        blocked_version = get_account(acct["id"])["version"]
        resp = api_client.close_account(
            acct["id"], {"expected_account_version": blocked_version},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_CLOSURE_BLOCKED)

    def test_close_succeeds_after_garnishment_released(self):
        """PRD section 3.9: "A manual closure settles interest accrued over
        the half-open window from `accrual_start_date` to the close date,
        under the account's product rounding variant, posting it as an
        `INTEREST_CREDIT` transaction; a `CLOSURE_PAYOUT` transaction then
        drains the balance to exactly zero. The account records
        `closure_payout_cents` as the pre-close balance plus the settled
        interest and `closure_payout_destination` as `OWNER`, and its
        `version` increments."

        Design: Difficulty/cross_entity_state_dependency/account_closure_gated_on_garnishment_state
        """
        acct = open_account(opening_deposit_cents=80000,
                            primary_owner_name="Cls C", owner_tax_id="T17")
        order = register_garnishment(acct["id"], 30000, "2026-08-01",
                                     exemption_method="FEDERAL_LOOKBACK")
        version_while_held = get_account(acct["id"])["version"]

        resolved = resolve_garnishment(order["id"], "RELEASED")
        assert resolved["status"] == "RELEASED"

        acct_free = get_account(acct["id"])
        assert acct_free["restriction_status"] == "NONE"
        assert acct_free["version"] != version_while_held

        closed = validate_success(
            api_client.close_account(
                acct["id"],
                {"expected_account_version": acct_free["version"]},
                OFFICER),
            expected_status=200,
        )
        assert closed["lifecycle_status"] == "CLOSED"
        # Rate is 0, so no interest settles; the full residual pays out.
        assert closed["closure_payout_cents"] == 80000
        assert closed["closure_payout_destination"] == "OWNER"
        assert closed["balance_cents"] == 0


class TestClosureTerminalAndShape:

    def test_account_close_terminal_lockdown(self):
        """PRD section 3.9: "An `OpsOfficer` or `OpsManager` closes an
        account in `OPEN`, `DORMANT`, or `ESCHEAT_PENDING` — an
        already-`CLOSED` account fails with `ERR_INVALID_STATE`."
        PRD section 3.9: "`CLOSED` is terminal and ends all account
        activity."

        Design: Corner/state_machines/account_close_terminal_lockdown
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Term T", owner_tax_id="C8")
        closed = close_with_fresh_version(acct["id"])
        assert closed["lifecycle_status"] == "CLOSED"

        fresh = get_account(acct["id"])
        resp = api_client.close_account(
            acct["id"], {"expected_account_version": fresh["version"]},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_close_closed_account_missing_version_returns_invalid_request(self):
        """PRD section 2.11: "Both require the request body to carry
        `expected_account_version`, a non-optional field holding the account
        `version` the client last observed."
        PRD section 2.10: "When several checks could reject the same
        request, the server evaluates them in a fixed order so the surfaced
        error is deterministic. The tiers, from first to last:" — with
        "4. **Request shape** — required fields are present, enum members
        are valid, amounts are positive, `pod_beneficiary_name` is present
        exactly when the ownership type in play is `POD`, a requested type
        differs from the current one, and `cycle_start` falls strictly
        before `cycle_end` (`ERR_INVALID_REQUEST`)." preceding
        "5. **State and version** — the target resource's state permits the
        transition (`ERR_INVALID_STATE`)".

        Design: Corner/validations/close_closed_account_missing_version_returns_invalid_request
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Shp H", owner_tax_id="C17")
        closed = close_with_fresh_version(acct["id"])
        assert closed["lifecycle_status"] == "CLOSED"

        # Missing the required version field: the shape tier (4) reports
        # before the state tier (5) even though the account is CLOSED.
        resp = api_client.close_account(acct["id"], {}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestClosureOptimisticConcurrency:

    def test_occ_stale_version_on_close(self):
        """PRD section 3.9: "Closure is optimistic-concurrency guarded per
        §2.11: the request must carry `expected_account_version` matching
        the account's current `version`, because intervening mutations
        change the residual payout basis, and a stale presentation is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD section 2.11: "If the account's current `version` has advanced
        past the presented value — because a hold was placed, a fee posted,
        a transaction landed, or any other mutation intervened — the request
        is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must
        re-read the account and re-issue with the fresh version."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_close
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Occ C", owner_tax_id="R5")
        stale_version = acct["version"]
        # An intervening deposit advances the account version.
        post_transaction(acct["id"], "DEPOSIT", 250, customer_initiated=False)

        resp = api_client.close_account(
            acct["id"], {"expected_account_version": stale_version}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh = get_account(acct["id"])
        assert fresh["version"] != stale_version

        closed = validate_success(
            api_client.close_account(
                acct["id"], {"expected_account_version": fresh["version"]},
                OFFICER),
            expected_status=200,
        )
        assert closed["lifecycle_status"] == "CLOSED"
        assert closed["closure_payout_cents"] == 5250
        assert closed["closure_payout_destination"] == "OWNER"
