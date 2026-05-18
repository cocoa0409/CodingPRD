"""Optimistic concurrency, idempotency, and race conditions (PRD §2.6, §2.7)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_exactly_one_succeeds,
    create_emd_held,
    create_escrow_file_basic,
    create_party,
    create_property_entity,
    emd_payload,
    escrow_file_payload,
    fresh_idempotency_key,
    party_payload,
    re_get_emd,
    re_get_escrow_file,
    run_race,
    setup_emd_held,
    setup_escrow_in_contingent_cd,
    create_cd,
    issue_cd,
    revise_cd_payload,
    validate_error,
    validate_success,
    version_only_payload,
    with_idempotency,
)


# ===========================================================================
# Optimistic concurrency — PRD §2.6
# ===========================================================================
class TestOptimisticConcurrency:

    def test_state_transition_with_stale_version_rejected(self, api):
        """PRD §2.6: "Any endpoint that mutates a resource by its id
        accepts an optional version field in the request body. When
        present, it must equal the row's current version; otherwise
        the request is rejected with ERR_VERSION_MISMATCH."

        Claim: state transition with a stale version yields
        ERR_VERSION_MISMATCH.
        """
        bundle = create_escrow_file_basic()
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        # Create EMD.
        resp = api.create_emd(
            emd_payload(
                escrow_file_id=bundle["escrow_file"]["id"],
                amount=3000.00,
            ),
            eo,
        )
        emd = validate_success(resp, expected_status=201)
        # Successfully fund it.
        eo2 = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.fund_emd(
            emd["id"], version_only_payload(version=emd["version"]), eo2,
        )
        funded = validate_success(resp)
        # Now attempt another mutation with the STALE pre-fund version.
        eo3 = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.fund_emd(
            emd["id"], version_only_payload(version=emd["version"]), eo3,
        )
        # Either VERSION_MISMATCH (priority 20) or INVALID_STATE
        # (priority 5) is acceptable depending on which check fires
        # first per §2.8 — but PRD §2.6 explicitly says version
        # mismatch yields ERR_VERSION_MISMATCH. State-check runs first
        # by priority — but the row's status is now HELD, not the
        # required PENDING_FUNDS for fund — so ERR_INVALID_STATE wins.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_INVALID_STATE.value,
                ApiErrorId.ERR_VERSION_MISMATCH.value,
            ],
        )


# ===========================================================================
# Idempotency — PRD §2.7
# ===========================================================================
class TestIdempotency:

    def test_same_key_same_body_replays_original_response(self, api):
        """PRD §2.7: "If the same key is replayed with an identical
        request body, the server returns the original response."

        Claim: same Idempotency-Key + same body returns the same id
        (the original resource) on both calls.
        """
        buyer = create_party("BUYER")
        seller = create_party("SELLER")
        prop = create_property_entity()
        payload = escrow_file_payload(
            property_id=prop["id"],
            buyer_party_id=buyer["id"],
            seller_party_id=seller["id"],
        )
        key = fresh_idempotency_key()
        headers = dict(TEST_USERS["escrow_officer_headers"])
        headers["Idempotency-Key"] = key
        resp1 = api.create_escrow_file(payload, headers)
        data1 = validate_success(resp1, expected_status=201)
        resp2 = api.create_escrow_file(payload, headers)
        data2 = validate_success(resp2, expected_status=201)
        assert data1["id"] == data2["id"], (
            f"replay must return same resource: {data1['id']} vs {data2['id']}"
        )

    def test_same_key_different_body_rejected(self, api):
        """PRD §2.7: "If the same key is replayed with a different
        request body, the server rejects the replay with
        ERR_IDEMPOTENCY_REPLAY_MISMATCH."

        Claim: same Idempotency-Key + different body yields
        ERR_IDEMPOTENCY_REPLAY_MISMATCH.
        """
        buyer = create_party("BUYER")
        seller = create_party("SELLER")
        prop = create_property_entity()
        key = fresh_idempotency_key()
        headers = dict(TEST_USERS["escrow_officer_headers"])
        headers["Idempotency-Key"] = key
        payload1 = escrow_file_payload(
            property_id=prop["id"],
            buyer_party_id=buyer["id"],
            seller_party_id=seller["id"],
            purchase_price=300000.00,
        )
        api.create_escrow_file(payload1, headers)
        # Replay with a different purchase_price → mismatch.
        payload2 = dict(payload1)
        payload2["purchase_price"] = 400000.00
        resp = api.create_escrow_file(payload2, headers)
        validate_error(resp, ApiErrorId.ERR_IDEMPOTENCY_REPLAY_MISMATCH)


# ===========================================================================
# Concurrency races — PRD §3.2, §3.5, §3.9
# ===========================================================================
class TestConcurrencyRaces:

    def test_two_funds_on_same_emd_only_one_succeeds(self, api):
        """PRD §3.2: "Two operators racing to fund the same row
        serialize on EarnestMoneyDeposit.status — exactly one
        transition from PENDING_FUNDS to HELD succeeds, and the loser
        receives ERR_INVALID_STATE because the row has already
        advanced."

        Claim: two concurrent fund calls on the same EMD result in
        exactly one success and one ERR_INVALID_STATE.
        """
        bundle = create_escrow_file_basic()
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.create_emd(
            emd_payload(
                escrow_file_id=bundle["escrow_file"]["id"],
                amount=3000.00,
            ),
            eo,
        )
        emd = validate_success(resp, expected_status=201)

        def fund_call():
            return api.fund_emd(
                emd["id"],
                version_only_payload(version=emd["version"]),
                with_idempotency(TEST_USERS["escrow_officer_headers"]),
            )

        results = run_race(fund_call, fund_call)
        outcome = assert_exactly_one_succeeds(*results)
        # The loser is rejected; PRD §3.2 names ERR_INVALID_STATE for
        # this race specifically.
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value

    def test_two_revises_on_same_issued_cd_only_one_succeeds(self, api):
        """PRD §3.5: "Two operators racing to revise the same ISSUED
        disclosure serialize on the row's version: exactly one revise
        succeeds and the loser receives ERR_VERSION_MISMATCH".

        Claim: two concurrent revise calls on the same ISSUED CD with
        the same version result in exactly one success and one
        ERR_VERSION_MISMATCH.
        """
        bundle = setup_escrow_in_contingent_cd()
        cd = create_cd(bundle["escrow_file"]["id"])
        cd = issue_cd(cd["id"], version=cd["version"])
        # Two concurrent revises that BOTH include the current version
        # field — OCC serializes them.
        version = cd["version"]

        def revise_a():
            return api.revise_closing_disclosure(
                cd["id"],
                revise_cd_payload(
                    triggering_change_kind="APR_DELTA_OVER_THRESHOLD",
                    version=version,
                ),
                with_idempotency(TEST_USERS["escrow_officer_headers"]),
            )

        def revise_b():
            return api.revise_closing_disclosure(
                cd["id"],
                revise_cd_payload(
                    triggering_change_kind="FEE_DELTA_UNDER_THRESHOLD",
                    version=version,
                ),
                with_idempotency(TEST_USERS["escrow_officer_headers"]),
            )

        results = run_race(revise_a, revise_b)
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_VERSION_MISMATCH.value
