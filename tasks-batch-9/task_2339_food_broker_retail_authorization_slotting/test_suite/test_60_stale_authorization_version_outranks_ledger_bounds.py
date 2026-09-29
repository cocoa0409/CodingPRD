"""A one-write-old version pin short-circuits every ledger bound the body also breaks."""

import pytest

from test_helpers import (
    ApiErrorId,
    EntryKind,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
    validate_error,
)
from test_helpers import factories as F

AUTHORIZED_STORES = 400


@pytest.fixture
def authorized_item_with_an_empty_ledger(api):
    """One AUTHORIZED authorization over 400 stores, no deal, no postings yet."""
    scope = fixtures.awarded_authorization_without_deal(
        api, default_store_count=AUTHORIZED_STORES
    )
    scope["buyer_headers"] = make_retailer_buyer_headers(scope["retailer"]["id"])
    scope["stale_version"] = scope["authorization"]["version"]
    return scope


def post(api, scope, expected_authorization_version, **fields):
    return api.post_snapshot(
        F.snapshot_payload(
            scope["authorization"]["id"], expected_authorization_version, **fields
        ),
        scope["buyer_headers"],
    )


def post_the_first_period(api, scope):
    return get_success_data(
        post(
            api,
            scope,
            scope["stale_version"],
            period_index=1,
            reported_store_count=400,
            distributed_store_count=400,
            reported_case_volume=1000,
        ),
        201,
    )


def read_authorization(api, scope):
    return fixtures.get_authorization(api, scope["authorization"]["id"])


def post_the_second_period(api, scope):
    fresh = read_authorization(api, scope)
    return get_success_data(
        post(
            api,
            scope,
            fresh["version"],
            period_index=2,
            reported_store_count=400,
            distributed_store_count=390,
            reported_case_volume=900,
        ),
        201,
    )


class TestStaleAuthorizationVersionOutranksLedgerBounds:
    def test_an_accepted_posting_bumps_the_authorization_exactly_once(
        self, api, authorized_item_with_an_empty_ledger
    ):
        """The ledger record is created, so the response is a 201 and the parent moves one version.

        PRD: "The entry is written as an append-only ledger record with `entry_kind` at `POSTING`,
        `reverses_snapshot_id` null, `is_reversed` false and `posted_at` stamped from the logical clock,
        and the response carries HTTP 201 because a new ledger record has been created."

        PRD: "The `POSTING` entry is persisted immutably and the authorization's `periods_reported`
        increases by one."

        Design: Corner/cross_cutting_complexity_layers/stale_authorization_version_outranks_every_snapshot_bound
        """
        scope = authorized_item_with_an_empty_ledger

        first = post_the_first_period(api, scope)

        assert first["entry_kind"] == EntryKind.POSTING
        assert first["reverses_snapshot_id"] is None
        assert first["is_reversed"] is False
        after = read_authorization(api, scope)
        assert after["periods_reported"] == 1
        assert after["version"] == scope["stale_version"] + 1

    def test_a_perfectly_legal_period_is_still_refused_on_a_stale_pin(
        self, api, authorized_item_with_an_empty_ledger
    ):
        """Period 2 is exactly what the sequence wants; only the pin is one write behind.

        PRD: "`POST /distribution-snapshots` requires `expected_authorization_version`, carrying the
        client's last observed `version` of the target `Authorization`. A posting is written against that
        authorization's period sequence, void counters and the linked deal's amortization ledger; if an
        earlier posting, a reversal, a void-rate state change or a promotion settlement has since advanced
        the authorization's `version`, the posting is rejected with `ERR_STALE_AUTHORIZATION_VERSION`
        (HTTP 412)."

        PRD: "**Concurrency.** The three version pins of §2.7, returning `ERR_STALE_PRINCIPAL_VERSION`,
        `ERR_STALE_AUTHORIZATION_VERSION` or `ERR_STALE_REVIEW_VERSION` (all 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_authorization_version_outranks_every_snapshot_bound
        """
        scope = authorized_item_with_an_empty_ledger
        post_the_first_period(api, scope)

        response = post(
            api,
            scope,
            scope["stale_version"],
            period_index=2,
            reported_store_count=400,
            distributed_store_count=390,
            reported_case_volume=900,
        )

        validate_error(response, ApiErrorId.STALE_AUTHORIZATION_VERSION, 412)

    def test_the_concurrency_band_outranks_the_uniqueness_bound(
        self, api, authorized_item_with_an_empty_ledger
    ):
        """Period 1 is already occupied, yet the reported error is the version one.

        PRD: "And at most one live `POSTING` ledger entry exists per combination of `authorization_id`
        and `period_index` (`ERR_PERIOD_ALREADY_POSTED`)."

        PRD: "Validations are evaluated in ascending priority bands, and the **first** violated rule
        determines the response."

        Design: Corner/cross_cutting_complexity_layers/stale_authorization_version_outranks_every_snapshot_bound
        """
        scope = authorized_item_with_an_empty_ledger
        post_the_first_period(api, scope)

        response = post(
            api,
            scope,
            scope["stale_version"],
            period_index=1,
            reported_store_count=400,
            distributed_store_count=390,
            reported_case_volume=900,
        )

        validate_error(response, ApiErrorId.STALE_AUTHORIZATION_VERSION, 412)

    def test_three_broken_bounds_at_once_are_all_short_circuited_by_the_stale_pin(
        self, api, authorized_item_with_an_empty_ledger
    ):
        """Out of sequence, more reported than authorized, and more distributed than reported.

        PRD: "Sequencing is strict. `period_index` is 1-based and must equal the authorization's current
        `periods_reported` plus one — no gaps and no back-filling — otherwise
        `ERR_PERIOD_OUT_OF_SEQUENCE`; a live posting already occupying that period is
        `ERR_PERIOD_ALREADY_POSTED`. The store counts must nest: `distributed_store_count` may not exceed
        `reported_store_count`, otherwise `ERR_DISTRIBUTION_EXCEEDS_REPORTED`, and
        `reported_store_count` may not exceed the authorization's `authorized_store_count`, otherwise
        `ERR_REPORTED_EXCEEDS_AUTHORIZED`. Both counts and `reported_case_volume` may be zero."

        PRD: "Later violations are never reported, so a request that breaks three rules always returns
        the code of the earliest band it fails."

        Design: Corner/cross_cutting_complexity_layers/stale_authorization_version_outranks_every_snapshot_bound
        """
        scope = authorized_item_with_an_empty_ledger
        post_the_first_period(api, scope)

        response = post(
            api,
            scope,
            scope["stale_version"],
            period_index=9,
            reported_store_count=900,
            distributed_store_count=950,
            reported_case_volume=900,
        )

        validate_error(response, ApiErrorId.STALE_AUTHORIZATION_VERSION, 412)

    def test_the_refreshed_pin_posts_the_second_period(
        self, api, authorized_item_with_an_empty_ledger
    ):
        """Re-reading the parent is all the rejected client had to do.

        PRD: "If the pinned value does not equal the parent's current `version`, the write is refused
        rather than applied on top of a parent state the client never read."

        PRD: "Once an authorization is `AUTHORIZED`, the chain reports store-level distribution period by
        period, and this is where slotting money is actually recovered."

        Design: Corner/cross_cutting_complexity_layers/stale_authorization_version_outranks_every_snapshot_bound
        """
        scope = authorized_item_with_an_empty_ledger
        post_the_first_period(api, scope)
        validate_error(
            post(
                api,
                scope,
                scope["stale_version"],
                period_index=2,
                reported_store_count=400,
                distributed_store_count=390,
                reported_case_volume=900,
            ),
            ApiErrorId.STALE_AUTHORIZATION_VERSION,
            412,
        )

        second = post_the_second_period(api, scope)

        assert second["period_index"] == 2
        after = read_authorization(api, scope)
        assert after["periods_reported"] == 2
        assert after["version"] == scope["stale_version"] + 2

    def test_a_reversal_carries_no_pin_and_still_advances_the_version(
        self, api, authorized_item_with_an_empty_ledger
    ):
        """So a client that keeps posting after a reversal without re-reading will be refused.

        PRD: "The reversal decrements `periods_reported` by one and recomputes the counters from the new
        latest live posting"

        PRD: "Only the highest live `period_index` of an authorization may be reversed, otherwise
        `ERR_SNAPSHOT_NOT_LATEST`, and reversing an already-reversed posting or a `REVERSAL` entry itself
        is `ERR_SNAPSHOT_ALREADY_REVERSED`."

        Design: Corner/cross_cutting_complexity_layers/stale_authorization_version_outranks_every_snapshot_bound
        """
        scope = authorized_item_with_an_empty_ledger
        post_the_first_period(api, scope)
        second = post_the_second_period(api, scope)
        before_reversal = read_authorization(api, scope)

        reversal = get_success_data(
            api.reverse_snapshot(second["id"], scope["buyer_headers"]), 201
        )

        assert reversal["entry_kind"] == EntryKind.REVERSAL
        assert reversal["reverses_snapshot_id"] == second["id"]
        after = read_authorization(api, scope)
        assert after["periods_reported"] == 1
        assert after["version"] == before_reversal["version"] + 1

    def test_the_sequence_bound_bites_once_the_pin_is_fresh(
        self, api, authorized_item_with_an_empty_ledger
    ):
        """One live period remains after the reversal, so period 9 is a gap of seven.

        PRD: "**Structural constraints.** Uniqueness (§2.10) on chain registration, principal onboarding,
        item setup, conflict-rule declaration, presentation creation and distribution posting;
        `ERR_AGREEMENT_WINDOW_OVERLAP` on agreement activation; `ERR_REVIEW_BLACKOUT_CONFLICT` on review
        scheduling; `ERR_REVIEW_CALENDAR_INVALID` on review scheduling and reopening;
        `ERR_DEMO_SLOT_CAPACITY` on promotion commit; the negotiation and refile bounds
        `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`, `ERR_COUNTER_NOT_HIGHER`, `ERR_PROPOSAL_NOT_LOWER`,
        `ERR_REFILE_LIMIT_REACHED`, `ERR_REVIEW_REOPEN_LIMIT`, `ERR_STORE_COUNT_EXCEEDS_CHAIN` and
        `ERR_CLAIM_EXCEEDS_DEDUCTION` across deal counter, deal re-proposal, deal creation, claim filing,
        review reopen and the award decision; and the ledger-sequence rules `ERR_PERIOD_OUT_OF_SEQUENCE`,
        `ERR_DISTRIBUTION_EXCEEDS_REPORTED`, `ERR_REPORTED_EXCEEDS_AUTHORIZED` and
        `ERR_SNAPSHOT_NOT_LATEST` across distribution posting and reversal. All are HTTP 409."

        PRD: "Mistaken reports are corrected by appending, never by editing."

        Design: Corner/cross_cutting_complexity_layers/stale_authorization_version_outranks_every_snapshot_bound
        """
        scope = authorized_item_with_an_empty_ledger
        post_the_first_period(api, scope)
        second = post_the_second_period(api, scope)
        get_success_data(api.reverse_snapshot(second["id"], scope["buyer_headers"]), 201)
        fresh = read_authorization(api, scope)

        response = post(
            api,
            scope,
            fresh["version"],
            period_index=9,
            reported_store_count=400,
            distributed_store_count=390,
            reported_case_volume=900,
        )

        validate_error(response, ApiErrorId.PERIOD_OUT_OF_SEQUENCE, 409)
        assert read_authorization(api, scope)["version"] == fresh["version"]
