"""Store counts are conserved across reported-basis postings and a reversal."""

import pytest

from test_helpers import (
    ApiErrorId,
    AuthorizationState,
    EntryKind,
    VoidRateBasis,
    make_retailer_buyer_headers,
    validate_error,
    fixtures,
)
from test_helpers.assertions import (
    assert_store_counts_conserved,
    assert_voids_report,
    expected_void_rate_bps,
)

AUTHORIZED_STORES = 400


@pytest.fixture
def reported_basis_authorization(api):
    """One award at a reported-basis chain, live and ready to receive periods."""
    return fixtures.awarded_authorization_without_deal(
        api,
        retailer_overrides={
            "void_rate_basis_default": VoidRateBasis.REPORTED_BASIS,
            "at_risk_void_rate_bps": 1500,
        },
        default_store_count=AUTHORIZED_STORES,
    )


def post_first_period(api, scope):
    return fixtures.post_period(
        api,
        scope["authorization"]["id"],
        scope["retailer"]["id"],
        period_index=1,
        reported_store_count=380,
        distributed_store_count=340,
        reported_case_volume=7000,
    )


def post_second_period(api, scope):
    return fixtures.post_period(
        api,
        scope["authorization"]["id"],
        scope["retailer"]["id"],
        period_index=2,
        reported_store_count=400,
        distributed_store_count=395,
        reported_case_volume=8200,
    )


class TestStoreCountConservation:
    def test_the_first_period_splits_the_authorized_stores_three_ways(
        self, api, reported_basis_authorization
    ):
        """340 distributed, 40 void, 20 pending — and 1,052 basis points after truncation.

        PRD: "On an authorization, `pending_store_count` always equals
        `authorized_store_count` minus `distributed_store_count` minus `void_store_count`."

        Design: Difficulty/compensating_invariant/store_counts_conserved_across_reported_basis_posting_and_reversal
        """
        post_first_period(api, reported_basis_authorization)

        authorization = fixtures.get_authorization(
            api, reported_basis_authorization["authorization"]["id"]
        )
        assert authorization["authorized_store_count"] == AUTHORIZED_STORES
        assert authorization["distributed_store_count"] == 340
        assert authorization["void_store_count"] == 40
        assert authorization["pending_store_count"] == 20
        assert authorization["void_rate_bps"] == 1052
        assert authorization["void_rate_bps"] == expected_void_rate_bps(40, 380)
        assert authorization["authorization_state"] == AuthorizationState.AUTHORIZED
        assert authorization["periods_reported"] == 1
        assert_store_counts_conserved(authorization)

    def test_the_second_period_re_derives_every_counter_from_the_new_latest_posting(
        self, api, reported_basis_authorization
    ):
        """Full reporting drains the pending bucket: 395 distributed, 5 void, 0 pending.

        PRD: "The authorization's distribution counters are recomputed from the new latest
        live posting."

        Design: Difficulty/compensating_invariant/store_counts_conserved_across_reported_basis_posting_and_reversal
        """
        post_first_period(api, reported_basis_authorization)
        post_second_period(api, reported_basis_authorization)

        authorization = fixtures.get_authorization(
            api, reported_basis_authorization["authorization"]["id"]
        )
        assert authorization["distributed_store_count"] == 395
        assert authorization["void_store_count"] == 5
        assert authorization["pending_store_count"] == 0
        assert authorization["void_rate_bps"] == 125
        assert authorization["void_rate_bps"] == expected_void_rate_bps(5, 400)
        assert authorization["periods_reported"] == 2
        assert_store_counts_conserved(authorization)

    def test_the_reversal_appends_a_compensating_entry_and_leaves_the_posting_intact(
        self, api, reported_basis_authorization
    ):
        """The cancelled period-2 row is flagged, not rewritten.

        PRD: "Mistaken reports are corrected by appending, never by editing."

        Design: Difficulty/compensating_invariant/store_counts_conserved_across_reported_basis_posting_and_reversal
        """
        post_first_period(api, reported_basis_authorization)
        second = post_second_period(api, reported_basis_authorization)
        reversal = fixtures.reverse_period(
            api, second["id"], reported_basis_authorization["retailer"]["id"]
        )

        assert reversal["entry_kind"] == EntryKind.REVERSAL
        assert reversal["reverses_snapshot_id"] == second["id"]
        assert reversal["period_index"] == 2

        ledger = fixtures.list_snapshots(
            api, authorization_id=reported_basis_authorization["authorization"]["id"]
        )
        cancelled = next(row for row in ledger if row["id"] == second["id"])
        assert cancelled["is_reversed"] is True
        assert cancelled["reported_store_count"] == 400
        assert cancelled["distributed_store_count"] == 395
        assert cancelled["reported_case_volume"] == 8200

    def test_the_reversal_restores_the_first_period_counters_exactly(
        self, api, reported_basis_authorization
    ):
        """Counters are recomputed from period one, not decremented by the period-two delta.

        PRD: "The reversal decrements `periods_reported` by one and recomputes the counters
        from the new latest live posting; it rolls back the deal's `recovered_cents`,
        `unamortized_balance_cents` and `periods_posted`; when the deal had already closed it
        reopens it, moving `RECOVERED` → `AMORTIZING` and each linked authorization's
        `settlement_state` from `SLOTTING_RECOVERED` back to `SLOTTING_AMORTIZING`; it recomputes
        `void_rate_bps`, moving `AT_RISK` → `AUTHORIZED` and `RECOVERY_HOLD` → `AMORTIZING` when the
        rate has dropped back below the threshold; it re-derives the principal's aggregates and
        `credit_posture`; and it advances the authorization's `version` by one."

        Design: Difficulty/compensating_invariant/store_counts_conserved_across_reported_basis_posting_and_reversal
        """
        post_first_period(api, reported_basis_authorization)
        second = post_second_period(api, reported_basis_authorization)
        fixtures.reverse_period(
            api, second["id"], reported_basis_authorization["retailer"]["id"]
        )

        authorization = fixtures.get_authorization(
            api, reported_basis_authorization["authorization"]["id"]
        )
        assert authorization["distributed_store_count"] == 340
        assert authorization["void_store_count"] == 40
        assert authorization["pending_store_count"] == 20
        assert authorization["void_rate_bps"] == 1052
        assert authorization["periods_reported"] == 1
        assert authorization["authorization_state"] == AuthorizationState.AUTHORIZED
        assert_store_counts_conserved(authorization)

    def test_the_pinned_basis_is_what_keeps_the_restored_authorization_healthy(
        self, api, reported_basis_authorization
    ):
        """The same period-one data would be 1,500 basis points and at risk under the other basis.

        PRD: "and — so a buyer can see what the other measurement convention would have said
        — a `counterfactual_basis` naming the basis not in use together with the
        `counterfactual_void_rate_bps` that basis would have produced from the same latest
        live posting."

        Design: Difficulty/compensating_invariant/store_counts_conserved_across_reported_basis_posting_and_reversal
        """
        post_first_period(api, reported_basis_authorization)
        second = post_second_period(api, reported_basis_authorization)
        fixtures.reverse_period(
            api, second["id"], reported_basis_authorization["retailer"]["id"]
        )

        report = fixtures.get_voids_report(
            api, reported_basis_authorization["authorization"]["id"]
        )
        assert_voids_report(report)
        assert report["void_rate_basis"] == VoidRateBasis.REPORTED_BASIS
        assert report["latest_period_index"] == 1
        assert report["void_rate_bps"] == 1052
        assert report["is_at_risk"] is False
        assert report["counterfactual_basis"] == VoidRateBasis.STORE_COUNT_BASIS
        # 400 authorized less 340 distributed is 60 void, which is exactly the threshold.
        assert report["counterfactual_void_rate_bps"] == 1500
        assert report["counterfactual_void_rate_bps"] == expected_void_rate_bps(
            60, AUTHORIZED_STORES
        )

    def test_a_compensation_cannot_be_applied_twice(self, api, reported_basis_authorization):
        """Reversing an already-reversed posting is refused, so counters cannot double-roll-back.

        PRD: "Only the highest live `period_index` of an authorization may be reversed,
        otherwise `ERR_SNAPSHOT_NOT_LATEST`, and reversing an already-reversed posting or a
        `REVERSAL` entry itself is `ERR_SNAPSHOT_ALREADY_REVERSED`."

        Design: Difficulty/compensating_invariant/store_counts_conserved_across_reported_basis_posting_and_reversal
        """
        post_first_period(api, reported_basis_authorization)
        second = post_second_period(api, reported_basis_authorization)
        retailer_id = reported_basis_authorization["retailer"]["id"]
        fixtures.reverse_period(api, second["id"], retailer_id)

        response = api.reverse_snapshot(second["id"], make_retailer_buyer_headers(retailer_id))
        validate_error(response, ApiErrorId.SNAPSHOT_ALREADY_REVERSED, 409)

        authorization = fixtures.get_authorization(
            api, reported_basis_authorization["authorization"]["id"]
        )
        assert authorization["periods_reported"] == 1
        assert authorization["distributed_store_count"] == 340
        assert_store_counts_conserved(authorization)
