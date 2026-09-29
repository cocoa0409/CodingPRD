"""The voids report is a projection over the live ledger, published under both bases at once."""

import pytest

from test_helpers import (
    AUDIT_MANAGER_HEADERS,
    DEFAULT_AT_RISK_VOID_RATE_BPS,
    UPC_1,
    AuthorizationState,
    VoidRateBasis,
    fixtures,
    get_success_data,
    make_principal_portal_headers,
)

AUTHORIZED_STORE_COUNT = 400
FIRST_REPORTED = 380
FIRST_DISTRIBUTED = 340
SECOND_REPORTED = 350
SECOND_DISTRIBUTED = 290


@pytest.fixture
def reported_basis_authorization(api):
    """One AUTHORIZED item at 400 stores in a chain that measures voids on the reported base."""
    scope = fixtures.awarded_authorization_without_deal(
        api,
        retailer_overrides={"void_rate_basis_default": VoidRateBasis.REPORTED_BASIS},
        review_overrides={"new_item_slots": 2},
        default_store_count=AUTHORIZED_STORE_COUNT,
    )
    assert scope["authorization"]["void_rate_basis"] == VoidRateBasis.REPORTED_BASIS
    assert scope["authorization"]["authorized_store_count"] == AUTHORIZED_STORE_COUNT
    return scope


def report_as_portal_user(api, scope):
    return get_success_data(
        api.get_voids_report(
            scope["authorization"]["id"],
            make_principal_portal_headers(scope["principal"]["id"]),
        ),
        200,
    )


def report_as_audit_manager(api, scope):
    return get_success_data(
        api.get_voids_report(scope["authorization"]["id"], AUDIT_MANAGER_HEADERS), 200
    )


def post_first_period(api, scope):
    return fixtures.post_period(
        api,
        scope["authorization"]["id"],
        scope["retailer"]["id"],
        period_index=1,
        reported_store_count=FIRST_REPORTED,
        distributed_store_count=FIRST_DISTRIBUTED,
        reported_case_volume=900,
    )


def post_second_period(api, scope):
    return fixtures.post_period(
        api,
        scope["authorization"]["id"],
        scope["retailer"]["id"],
        period_index=2,
        reported_store_count=SECOND_REPORTED,
        distributed_store_count=SECOND_DISTRIBUTED,
        reported_case_volume=700,
    )


def authorization_state(api, scope):
    return fixtures.get_authorization(api, scope["authorization"]["id"])[
        "authorization_state"
    ]


class TestVoidsReportRecomputesBothBases:
    def test_an_empty_ledger_reports_zeroes_with_every_store_still_pending(
        self, api, reported_basis_authorization
    ):
        """No posting has been made, so there is no live posting for either basis to read.

        PRD: "Both read the *latest live posting*: the `POSTING` entry of that authorization with the
        highest `period_index` among entries that have not been reversed. When no live posting exists,
        `void_rate_bps` is 0."

        PRD: "On an authorization, `pending_store_count` always equals `authorized_store_count` minus
        `distributed_store_count` minus `void_store_count`."

        Design: Corner/endpoints/voids_report_recomputes_both_bases_from_the_live_ledger
        """
        scope = reported_basis_authorization

        report = report_as_portal_user(api, scope)

        assert report["latest_period_index"] == 0
        assert report["reported_store_count"] == 0
        assert report["distributed_store_count"] == 0
        assert report["void_store_count"] == 0
        assert report["void_rate_bps"] == 0
        assert report["pending_store_count"] == AUTHORIZED_STORE_COUNT
        assert report["is_at_risk"] is False

    def test_the_report_echoes_the_pinned_basis_and_names_the_other_one(
        self, api, reported_basis_authorization
    ):
        """The identifying fields come from the authorization, its item and its chain.

        PRD: "A voids report is available as a computed read on any authorization. It returns
        `authorization_id`, `item_id`, the item's `upc`, `retailer_id`, the pinned `void_rate_basis`,
        `authorized_store_count`, `latest_period_index`, `reported_store_count`,
        `distributed_store_count`, `void_store_count`, `pending_store_count`, `void_rate_bps`, the
        chain's `at_risk_void_rate_bps`, an `is_at_risk` boolean, and — so a buyer can see what the
        other measurement convention would have said — a `counterfactual_basis` naming the basis not in
        use together with the `counterfactual_void_rate_bps` that basis would have produced from the
        same latest live posting."

        Design: Corner/endpoints/voids_report_recomputes_both_bases_from_the_live_ledger
        """
        scope = reported_basis_authorization

        report = report_as_portal_user(api, scope)

        assert report["authorization_id"] == scope["authorization"]["id"]
        assert report["item_id"] == scope["item"]["id"]
        assert report["upc"] == UPC_1
        assert report["retailer_id"] == scope["retailer"]["id"]
        assert report["authorized_store_count"] == AUTHORIZED_STORE_COUNT
        assert report["void_rate_basis"] == VoidRateBasis.REPORTED_BASIS
        assert report["counterfactual_basis"] == VoidRateBasis.STORE_COUNT_BASIS
        assert report["at_risk_void_rate_bps"] == DEFAULT_AT_RISK_VOID_RATE_BPS

    def test_the_first_posting_splits_the_two_bases_around_the_threshold(
        self, api, reported_basis_authorization
    ):
        """380 reported and 340 distributed: 40 voids on 380 reported, but 60 on 400 authorized.

        PRD: "Under `REPORTED_BASIS`, `distributed_store_count` is again the latest live posting's
        figure, but `void_store_count` is that posting's `reported_store_count` less
        `distributed_store_count`, and `void_rate_bps` is `void_store_count` multiplied by 10,000
        divided by that same `reported_store_count`, floored — or 0 when the reported count is zero."

        PRD: "Here `pending_store_count` is `authorized_store_count` less `distributed_store_count`
        less `void_store_count`: stores the chain never reported on are pending, not void."

        Design: Corner/endpoints/voids_report_recomputes_both_bases_from_the_live_ledger
        """
        scope = reported_basis_authorization
        post_first_period(api, scope)

        report = report_as_portal_user(api, scope)

        assert report["latest_period_index"] == 1
        assert report["reported_store_count"] == FIRST_REPORTED
        assert report["distributed_store_count"] == FIRST_DISTRIBUTED
        assert report["void_store_count"] == FIRST_REPORTED - FIRST_DISTRIBUTED
        assert report["void_rate_bps"] == 1052
        assert report["pending_store_count"] == (
            AUTHORIZED_STORE_COUNT - FIRST_DISTRIBUTED - (FIRST_REPORTED - FIRST_DISTRIBUTED)
        )
        assert report["counterfactual_void_rate_bps"] == 1500
        assert report["is_at_risk"] is False
        assert authorization_state(api, scope) == AuthorizationState.AUTHORIZED

    def test_the_second_posting_crosses_the_inclusive_threshold_under_the_pinned_basis(
        self, api, reported_basis_authorization
    ):
        """60 voids on 350 reported is 1714, above 1500, while the counterfactual reads 2750.

        PRD: "An `AUTHORIZED` authorization moves to `AT_RISK` when the recomputed `void_rate_bps` is
        at or above the chain's `at_risk_void_rate_bps`; an `AT_RISK` authorization returns to
        `AUTHORIZED` when a later posting, or a reversal, yields a rate strictly below that threshold."

        PRD: "Under `STORE_COUNT_BASIS`, `distributed_store_count` is taken from the latest live
        posting, `void_store_count` is `authorized_store_count` less `distributed_store_count`,
        `void_rate_bps` is `void_store_count` multiplied by 10,000 divided by
        `authorized_store_count`, floored — or 0 when `authorized_store_count` is zero — and
        `pending_store_count` is 0."

        Design: Corner/endpoints/voids_report_recomputes_both_bases_from_the_live_ledger
        """
        scope = reported_basis_authorization
        post_first_period(api, scope)
        post_second_period(api, scope)

        report = report_as_audit_manager(api, scope)

        assert report["latest_period_index"] == 2
        assert report["void_store_count"] == SECOND_REPORTED - SECOND_DISTRIBUTED
        assert report["void_rate_bps"] == 1714
        assert report["pending_store_count"] == (
            AUTHORIZED_STORE_COUNT
            - SECOND_DISTRIBUTED
            - (SECOND_REPORTED - SECOND_DISTRIBUTED)
        )
        assert report["counterfactual_void_rate_bps"] == 2750
        assert report["is_at_risk"] is True
        assert authorization_state(api, scope) == AuthorizationState.AT_RISK

    def test_a_reversal_makes_the_report_fall_back_to_the_previous_period(
        self, api, reported_basis_authorization
    ):
        """Cancelling period 2 restores every figure period 1 produced, rather than zeroing them.

        PRD: "The reversal decrements `periods_reported` by one and recomputes the counters from the
        new latest live posting"

        PRD: "it recomputes `void_rate_bps`, moving `AT_RISK` → `AUTHORIZED` and `RECOVERY_HOLD` →
        `AMORTIZING` when the rate has dropped back below the threshold"

        Design: Corner/endpoints/voids_report_recomputes_both_bases_from_the_live_ledger
        """
        scope = reported_basis_authorization
        post_first_period(api, scope)
        second_posting = post_second_period(api, scope)
        assert report_as_audit_manager(api, scope)["void_rate_bps"] == 1714

        fixtures.reverse_period(api, second_posting["id"], scope["retailer"]["id"])

        report = report_as_audit_manager(api, scope)
        assert report["latest_period_index"] == 1
        assert report["reported_store_count"] == FIRST_REPORTED
        assert report["distributed_store_count"] == FIRST_DISTRIBUTED
        assert report["void_rate_bps"] == 1052
        assert report["pending_store_count"] == 20
        assert report["counterfactual_void_rate_bps"] == 1500
        assert report["is_at_risk"] is False
        assert authorization_state(api, scope) == AuthorizationState.AUTHORIZED

    def test_reading_the_report_never_advances_the_authorization_version(
        self, api, reported_basis_authorization
    ):
        """Only the postings and the reversal move the version; the four reads move nothing.

        PRD: "A voids report is available as a computed read on any authorization."

        PRD: "The principal's aggregates, `at_risk_authorization_count`, `liability_ratio_bps` and
        `credit_posture` are re-derived. The authorization's `version` advances by one."

        Design: Corner/endpoints/voids_report_recomputes_both_bases_from_the_live_ledger
        """
        scope = reported_basis_authorization
        report_as_portal_user(api, scope)
        post_first_period(api, scope)
        report_as_portal_user(api, scope)
        after_one_posting = fixtures.get_authorization(api, scope["authorization"]["id"])

        for _ in range(3):
            report_as_audit_manager(api, scope)

        after_the_reads = fixtures.get_authorization(api, scope["authorization"]["id"])
        assert after_one_posting["version"] == scope["authorization"]["version"] + 1
        assert after_the_reads["version"] == after_one_posting["version"]
        assert after_the_reads["updated_at"] == after_one_posting["updated_at"]
