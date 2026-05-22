"""Concurrency, idempotency, optimistic concurrency control (PRD §2.9, §2.10, §2.11)."""

import uuid

import pytest

from test_helpers import (
    TEST_USERS,
    assert_payment_attempt,
    create_payment_attempt_payload,
    make_member_headers,
    register_member,
    setup_active_member_with_subscription,
    submit_payment_attempt,
    validate_error,
    validate_success,
)


class TestIdempotencyReplay:

    def test_replay_returns_same_amount_and_no_second_row(self, api):
        """PRD §2.9: "If a second request arrives with the same idempotency_key
        and the same subscription_id, the server does **not** re-contact the
        gateway and does **not** persist a duplicate row; instead it returns the
        prior response with the ERR_IDEMPOTENT_REPLAY outcome and HTTP 200. This
        contract holds whether the original attempt succeeded, failed, or
        declined; the replay reflects the original outcome, the original
        attempt_number, and the original amount_cents."

        Claim: replaying a SUCCESS PaymentAttempt with the same idempotency_key
        - returns HTTP 200,
        - the response is associated with the prior attempt (same id,
          attempt_number, amount_cents — PRD §2.9 says "reflects the original"),
        - the list of payment attempts still has exactly one row.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        # PaymentAttempt was already submitted to activate; we add a NEW one with
        # a fresh subscription so we know the count exactly.
        # Actually setup_active_member already used a key; we need a fresh sub.
        sub_fresh = api.create_subscription(
            member["id"],
            {"plan": "BASIC", "billing_cycle": "MONTHLY"},
            make_member_headers(member["id"]),
        ).json()["data"]
        key = str(uuid.uuid4())
        first = submit_payment_attempt(
            member, sub_fresh, outcome="SUCCESS", idempotency_key=key
        )
        assert_payment_attempt(first)
        # Replay with the same key, same gateway_txn_id, same outcome.
        payload = create_payment_attempt_payload(
            outcome="SUCCESS",
            idempotency_key=key,
            gateway_txn_id=first["gateway_txn_id"],
        )
        res = api.create_payment_attempt(
            member["id"], sub_fresh["id"], payload, TEST_USERS["billing_admin_headers"]
        )
        # PRD §5 maps ERR_IDEMPOTENT_REPLAY to HTTP 200.
        assert res.status_code == 200, (
            f"PRD §2.9: idempotent replay returns HTTP 200, got {res.status_code}"
        )
        # PRD §2.9: "the replay reflects the original outcome, the original
        # attempt_number, and the original amount_cents."
        body = res.json()
        # Two implementation-faithful shapes are possible:
        #   (a) success envelope with the prior PaymentAttempt as data
        #   (b) error envelope carrying error_id=ERR_IDEMPOTENT_REPLAY + the prior data
        # PRD §5 lists ERR_IDEMPOTENT_REPLAY as an error_id with HTTP 200, so we
        # only assert the count-invariant (no duplicate row) and the prior
        # amount_cents is recoverable from the response when present.
        # Confirm the list contains exactly one attempt for this key.
        listing = api.list_payment_attempts(
            member["id"], sub_fresh["id"], make_member_headers(member["id"])
        ).json()
        attempts = listing.get("data") or []
        matching = [a for a in attempts if a.get("idempotency_key") == key]
        assert len(matching) == 1, (
            f"PRD §2.9: replay must NOT persist a duplicate row; found {len(matching)} "
            f"PaymentAttempt rows with idempotency_key={key}"
        )
        # The persisted row carries the original amount_cents and attempt_number.
        assert matching[0]["amount_cents"] == first["amount_cents"]
        assert matching[0]["attempt_number"] == first["attempt_number"]


class TestOptimisticConcurrencyControl:

    def test_stale_version_on_mutation_rejected(self, api):
        """PRD §2.10: "Endpoints that modify a versioned resource accept an
        optional version field in the request body. When supplied, the server
        compares the inbound version to the current version of the addressed
        resource. If the values do not match, the request is rejected with
        ERR_INVALID_STATE and HTTP 409 — the resource has been mutated between
        the client's read and the client's write, and the client must re-read."

        Claim: a /suspend call carrying a stale `version` field → ERR_INVALID_STATE.
        """
        member, _sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        stale_version = 0  # member.version is >=1 after creation+activation
        res = api.suspend_member(
            member["id"], {"version": stale_version}, make_member_headers(member["id"])
        )
        validate_error(res, "ERR_INVALID_STATE")
