"""The credit pool: the two billing reckonings and the pooled-percentage invariant."""

import pytest

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, assert_four_dp
from test_helpers.test_users import CLERK_HEADERS


@pytest.fixture
def commercial_account():
    """An ACTIVE term with one 9020 sqft COMMERCIAL parcel billing 29264 cents."""
    program = fx.setup_active_program(eru_sqft=3000, funding_target_cents=25000)
    account = fx.create_account(
        program["term_id"],
        parcel_id="P-9020",
        parcel_class="COMMERCIAL",
        impervious_area_sqft=9020,
        owner_name="Harborline Retail LLC",
    )
    return {"program": program, "term_id": program["term_id"], "account": account}


def _file_and_approve(account_id, requested_pct, approved_pct=None):
    account = fx.read_account(account_id)
    application = fx.file_credit_application(
        account, requested_pct, headers=CLERK_HEADERS
    )
    return fx.review_credit_application(
        application["id"],
        "APPROVE",
        approved_credit_pct=approved_pct if approved_pct is not None else requested_pct,
    )


class TestInterimVersusFinalReckoning:
    """A still-submitted request counts in one reckoning and not in the other."""

    def test_01_interim_run_honours_a_submitted_request(self, commercial_account):
        """INTERIM bills 20485 because the pending 0.0245 request is honoured.

        PRD: "In the `INTERIM` reckoning, which is forward-looking, an
        application contributes its `approved_credit_pct` when its `status` is
        `APPROVED` and its `requested_credit_pct` when its `status` is
        `SUBMITTED`, and nothing otherwise."

        Design: Difficulty/dual_variant_calc/credit_pool_interim_vs_final_billing_divergence
        """
        account_id = commercial_account["account"]["id"]
        _file_and_approve(account_id, 0.2755)
        fx.file_credit_application(
            fx.read_account(account_id), 0.0245, headers=CLERK_HEADERS
        )

        run = fx.run_billing(commercial_account["term_id"], "INTERIM")

        assert run["billed_account_count"] == 1, "the term holds exactly one account"
        assert_cents(run["total_gross_billable_cents"], 29264, "total_gross_billable_cents")
        assert_cents(run["total_credit_cents"], 8779, "total_credit_cents")
        assert_cents(run["total_net_billed_cents"], 20485, "total_net_billed_cents")

    def test_02_final_run_ignores_the_same_submitted_request(self, commercial_account):
        """FINAL bills 21202 because only the approved 0.2755 contributes.

        PRD: "In the `FINAL` reckoning — the one behind the account's own stored
        `total_credit_pct` and `current_net_fee_cents` — an application
        contributes its `approved_credit_pct` when its `status` is `APPROVED`,
        and nothing otherwise."

        Design: Difficulty/dual_variant_calc/credit_pool_interim_vs_final_billing_divergence
        """
        account_id = commercial_account["account"]["id"]
        _file_and_approve(account_id, 0.2755)
        fx.file_credit_application(
            fx.read_account(account_id), 0.0245, headers=CLERK_HEADERS
        )

        run = fx.run_billing(commercial_account["term_id"], "FINAL")

        assert_cents(run["total_gross_billable_cents"], 29264, "total_gross_billable_cents")
        assert_cents(run["total_credit_cents"], 8062, "total_credit_cents")
        assert_cents(run["total_net_billed_cents"], 21202, "total_net_billed_cents")

    def test_03_the_submitted_request_never_enters_the_persisted_pool(
        self, commercial_account
    ):
        """The account's stored pool stays at 0.2755 through both runs.

        PRD: "`SUBMITTED`, `RETURNED`, `DENIED` and `REVOKED` rows contribute
        nothing."

        Design: Difficulty/dual_variant_calc/credit_pool_interim_vs_final_billing_divergence
        """
        account_id = commercial_account["account"]["id"]
        _file_and_approve(account_id, 0.2755)
        fx.file_credit_application(
            fx.read_account(account_id), 0.0245, headers=CLERK_HEADERS
        )

        fx.run_billing(commercial_account["term_id"], "INTERIM")
        after_interim = fx.read_account(account_id)
        assert_four_dp(after_interim["total_credit_pct"], 0.2755, "total_credit_pct")

        fx.run_billing(commercial_account["term_id"], "FINAL")
        after_final = fx.read_account(account_id)

        assert_four_dp(after_final["total_credit_pct"], 0.2755, "total_credit_pct")
        assert_cents(after_final["current_net_fee_cents"], 21202, "current_net_fee_cents")

    def test_04_the_billing_run_stamps_the_account_it_billed(self, commercial_account):
        """The FINAL run writes its own variant and figures onto the account.

        PRD: "The run recomputes the tiered fee for every account of the term,
        applies the credit reckoning of the requested variant, and writes
        `last_billed_run_type`, `last_billed_credit_pct`, `last_billed_net_cents`
        and `last_billed_at` on every account it bills."

        Design: Difficulty/dual_variant_calc/credit_pool_interim_vs_final_billing_divergence
        """
        account_id = commercial_account["account"]["id"]
        _file_and_approve(account_id, 0.2755)
        fx.file_credit_application(
            fx.read_account(account_id), 0.0245, headers=CLERK_HEADERS
        )

        fx.run_billing(commercial_account["term_id"], "INTERIM")
        fx.run_billing(commercial_account["term_id"], "FINAL")
        account = fx.read_account(account_id)

        assert account["last_billed_run_type"] == "FINAL", (
            "the most recent run was the FINAL one"
        )
        assert_four_dp(account["last_billed_credit_pct"], 0.2755, "last_billed_credit_pct")
        assert_cents(account["last_billed_net_cents"], 21202, "last_billed_net_cents")
        assert account["last_billed_at"] is not None, "the run must stamp last_billed_at"


class TestPooledPercentageIsConserved:
    """Credit cents are always re-derived from the pooled percentage."""

    def test_05_two_ten_percent_approvals_credit_the_pooled_twenty_percent(
        self, commercial_account
    ):
        """Two 0.1000 approvals credit 5853 cents, not 2926 twice.

        PRD: "The credit in cents is `gross_billable_cents` multiplied by that
        capped percentage, rounded to whole cents, and the net fee is
        `gross_billable_cents` minus that credit."

        Design: Difficulty/compensating_invariant/credit_pool_returns_to_the_exact_gross_fee_after_every_revocation
        """
        account_id = commercial_account["account"]["id"]

        _file_and_approve(account_id, 0.1000)
        after_first = fx.read_account(account_id)
        assert_four_dp(after_first["total_credit_pct"], 0.1000, "total_credit_pct")
        assert_cents(after_first["current_net_fee_cents"], 26338, "current_net_fee_cents")

        _file_and_approve(account_id, 0.1000)
        after_second = fx.read_account(account_id)

        assert_four_dp(after_second["total_credit_pct"], 0.2000, "total_credit_pct")
        assert_cents(after_second["current_net_fee_cents"], 23411, "current_net_fee_cents")
        assert after_second["current_net_fee_cents"] != 23412, (
            "23412 is the result of subtracting 2926 twice instead of crediting "
            "the pooled 0.2000"
        )

    def test_06_revocations_walk_the_net_fee_back_to_the_gross_billable_amount(
        self, commercial_account
    ):
        """Revoking all three approvals restores exactly 29264 cents.

        PRD: "It removes the `approved_credit_pct` from the account's
        `total_credit_pct`, restores `current_net_fee_cents`, raises the term's
        `projected_annual_revenue_cents` and may restore
        `funding_adequacy_status` to `ADEQUATE`."

        Design: Difficulty/compensating_invariant/credit_pool_returns_to_the_exact_gross_fee_after_every_revocation
        """
        account_id = commercial_account["account"]["id"]
        first = _file_and_approve(account_id, 0.1000)
        second = _file_and_approve(account_id, 0.1000)
        third = _file_and_approve(account_id, 0.3000)

        at_ceiling = fx.read_account(account_id)
        assert_four_dp(at_ceiling["total_credit_pct"], 0.5000, "total_credit_pct")
        assert_cents(at_ceiling["current_net_fee_cents"], 14632, "current_net_fee_cents")

        revoked_third = fx.get_success_data(
            fx.api_client.revoke_fee_credit_application(
                third["id"], fx.factories.credit_revoke_payload(), CLERK_HEADERS
            )
        )
        assert revoked_third["status"] == "REVOKED", "revocation writes REVOKED"
        after_third = fx.read_account(account_id)
        assert_four_dp(after_third["total_credit_pct"], 0.2000, "total_credit_pct")
        assert_cents(after_third["current_net_fee_cents"], 23411, "current_net_fee_cents")

        fx.get_success_data(
            fx.api_client.revoke_fee_credit_application(
                second["id"], fx.factories.credit_revoke_payload(), CLERK_HEADERS
            )
        )
        after_second = fx.read_account(account_id)
        assert_four_dp(after_second["total_credit_pct"], 0.1000, "total_credit_pct")
        assert_cents(after_second["current_net_fee_cents"], 26338, "current_net_fee_cents")

        fx.get_success_data(
            fx.api_client.revoke_fee_credit_application(
                first["id"], fx.factories.credit_revoke_payload(), CLERK_HEADERS
            )
        )
        emptied = fx.read_account(account_id)

        assert_four_dp(emptied["total_credit_pct"], 0.0000, "total_credit_pct")
        assert_cents(emptied["current_net_fee_cents"], 29264, "current_net_fee_cents")
        assert emptied["current_net_fee_cents"] == emptied["gross_billable_cents"], (
            "an empty pool must leave the net fee equal to the gross billable amount"
        )

    def test_07_the_gross_fee_chain_is_untouched_by_credit_movement(
        self, commercial_account
    ):
        """Approvals and revocations never rewrite the tiered fee.

        PRD: "Credit is applied on top of the gross billable amount."

        Design: Difficulty/compensating_invariant/credit_pool_returns_to_the_exact_gross_fee_after_every_revocation
        """
        account_id = commercial_account["account"]["id"]
        approved = _file_and_approve(account_id, 0.3000)
        during = fx.read_account(account_id)
        assert_cents(during["gross_fee_cents"], 26129, "gross_fee_cents")
        assert_cents(during["class_surcharge_cents"], 3135, "class_surcharge_cents")

        fx.get_success_data(
            fx.api_client.revoke_fee_credit_application(
                approved["id"], fx.factories.credit_revoke_payload(), CLERK_HEADERS
            )
        )
        after = fx.read_account(account_id)

        assert_cents(after["gross_fee_cents"], 26129, "gross_fee_cents")
        assert_cents(after["class_surcharge_cents"], 3135, "class_surcharge_cents")
        assert_cents(after["gross_billable_cents"], 29264, "gross_billable_cents")

    def test_08_term_revenue_returns_to_the_uncredited_projection(
        self, commercial_account
    ):
        """The term's projection ends at 29264 and reads ADEQUATE again.

        PRD: "`funding_adequacy_status`, which reads `ADEQUATE` when
        `projected_annual_revenue_cents` is greater than or equal to
        `funding_target_cents` and `UNDERFUNDED` otherwise."

        Design: Difficulty/compensating_invariant/credit_pool_returns_to_the_exact_gross_fee_after_every_revocation
        """
        account_id = commercial_account["account"]["id"]
        approved = _file_and_approve(account_id, 0.3000)

        underfunded = fx.read_term(commercial_account["term_id"])
        assert underfunded["funding_adequacy_status"] == "UNDERFUNDED", (
            "a 0.3000 credit drops revenue below the 25000-cent target"
        )

        fx.get_success_data(
            fx.api_client.revoke_fee_credit_application(
                approved["id"], fx.factories.credit_revoke_payload(), CLERK_HEADERS
            )
        )
        restored = fx.read_term(commercial_account["term_id"])

        assert_cents(
            restored["projected_annual_revenue_cents"], 29264, "projected_annual_revenue_cents"
        )
        assert restored["funding_adequacy_status"] == "ADEQUATE", (
            "revoking the credit restores revenue above the funding target"
        )
