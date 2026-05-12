"""Optimistic concurrency control, idempotency, and serialization races.

PRD §2.5, §2.11.

Race tests are generated ONLY where PRD explicitly defines the outcome:
- §2.11 'Two simultaneous POST /evidences/{id}/submit ... serialise on
  the Evidence.status transition; exactly one creates an OnChainTx ...
  and the loser receives ERR_INVALID_STATE.'
- §2.11 'Two simultaneous POST /evidences/{id}/resubmit ... the loser
  receives ERR_INVALID_STATE.'
- §2.11 'Two simultaneous seals of the same DRAFT JudicialPackage
  likewise serialise on JudicialPackage.status; the loser receives
  ERR_INVALID_STATE.'
- §2.11 'Two payment events arriving with the same external_payment_ref
  ... the wallet is credited at most once, and the second event is
  rejected with ERR_DUPLICATE_PAYMENT_REF.'
- §2.11 'Two POST /evidences requests with the same (customer_id,
  idempotency_key) are deduplicated similarly: only the first creates
  a row, the second receives ERR_DUPLICATE_IDEMPOTENCY_KEY.'
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    bring_evidence_to_failed,
    bring_evidence_to_submitting,
    create_customer,
    create_customer_with_balance,
    create_evidence,
    create_evidence_payload,
    create_notarization,
    create_recharge_payload,
    get_customer,
    make_customer_headers,
    payment_event_payload,
    random_payment_ref,
    run_race,
    setup_sealed_judicial_package,  # only for setup variants
    unique_suffix,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.fixtures import JUDICIAL


# ===========================================================================
# OCC version check (PRD §2.5)
# ===========================================================================
# PRD §2.5 OCC applies to mutation endpoints accepting a body. PRD §4
# does not expose a Customer/Evidence PATCH endpoint, and the
# state-transition endpoints (/submit, /resubmit, /seal, /deliver) all
# carry an empty input body per §4. Without a PATCH path, OCC cannot
# be observed from PRD-only behaviour. We log the gap and skip — no
# test emitted. Silence-pattern category: applies_to-scope (no endpoint
# accepts a version body field per PRD §4).


# ===========================================================================
# Concurrent submit on PENDING (PRD §2.11)
# ===========================================================================
class TestConcurrentEvidenceSubmit:
    """PRD §2.11: 'Two simultaneous POST /evidences/{id}/submit calls
    on the same PENDING Evidence serialise on the Evidence.status
    transition; exactly one creates an OnChainTx and bumps
    submission_attempts, and the loser receives ERR_INVALID_STATE
    (HTTP 409).'"""

    def test_double_submit_race_one_wins(self, api):
        """PRD §2.11: 'exactly one ... and the loser receives
        ERR_INVALID_STATE.'"""
        customer = create_customer_with_balance(balance_cents=10_000)
        evidence = create_evidence(customer)
        create_notarization(evidence)
        headers = make_customer_headers(customer["id"])

        results = run_race(
            lambda: api.submit_evidence(evidence["id"], headers),
            lambda: api.submit_evidence(evidence["id"], headers),
        )
        # Exactly one wins (2xx); the loser is 4xx with ERR_INVALID_STATE.
        winners = [r for r in results if 200 <= r.status_code < 300]
        losers = [r for r in results if r.status_code >= 400]
        assert len(winners) == 1, (
            f"Exactly one /submit must win, got "
            f"{[r.status_code for r in results]}"
        )
        assert len(losers) == 1
        validate_error(losers[0], ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Concurrent resubmit on FAILED (PRD §2.11)
# ===========================================================================
class TestConcurrentEvidenceResubmit:
    """PRD §2.11: 'The same guarantee applies to two simultaneous
    POST /evidences/{id}/resubmit calls on the same FAILED Evidence:
    the winner advances FAILED → SUBMITTING and creates the next
    OnChainTx attempt; the loser receives ERR_INVALID_STATE.'"""

    def test_double_resubmit_race_one_wins(self, api):
        customer, ev = bring_evidence_to_failed(balance_cents=10_000)
        headers = make_customer_headers(customer["id"])
        results = run_race(
            lambda: api.resubmit_evidence(ev["id"], headers),
            lambda: api.resubmit_evidence(ev["id"], headers),
        )
        winners = [r for r in results if 200 <= r.status_code < 300]
        losers = [r for r in results if r.status_code >= 400]
        assert len(winners) == 1
        assert len(losers) == 1
        validate_error(losers[0], ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Duplicate external_payment_ref on POST /_events/payment (PRD §2.11)
# ===========================================================================
class TestDuplicatePaymentEvent:
    """PRD §2.11: 'Two payment events arriving with the same
    external_payment_ref are deduplicated by the unique constraint on
    Recharge.external_payment_ref: the wallet is credited at most once,
    and the second event is rejected with ERR_DUPLICATE_PAYMENT_REF.'"""

    def test_second_payment_event_rejected(self, api, admin_headers):
        """PRD §2.11: 'the wallet is credited at most once, and the
        second event is rejected with ERR_DUPLICATE_PAYMENT_REF.'

        PRD §2.10 priority 21 re-enforces the same constraint on
        POST /_events/payment.
        """
        customer = create_customer()
        ref = random_payment_ref()
        validate_success(api.create_recharge(
            create_recharge_payload(
                customer_id=customer["id"],
                amount_cents=10_000,
                external_payment_ref=ref,
            ),
            make_customer_headers(customer["id"]),
        ), 201)
        # First event SUCCESS.
        validate_success(api.deliver_payment_event(
            payment_event_payload(
                external_payment_ref=ref, status="SUCCESS",
            ),
            admin_headers,
        ), 200)
        balance_after_first = get_customer(customer["id"]
                                            )["wallet_balance_cents"]
        # Second event with the same ref must be rejected.
        res = api.deliver_payment_event(
            payment_event_payload(
                external_payment_ref=ref, status="SUCCESS",
            ),
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_PAYMENT_REF.value)
        # Wallet must not have been credited twice.
        balance_after_second = get_customer(customer["id"]
                                             )["wallet_balance_cents"]
        assert balance_after_second == balance_after_first


# ===========================================================================
# Concurrent seal of the same DRAFT JudicialPackage (PRD §2.11)
# ===========================================================================
class TestConcurrentJudicialSeal:
    """PRD §2.11: 'Two simultaneous seals of the same DRAFT
    JudicialPackage likewise serialise on JudicialPackage.status; the
    loser receives ERR_INVALID_STATE.'"""

    def test_double_seal_race_one_wins(self, api):
        from test_helpers import (
            bring_evidence_to_confirmed,
            create_certificate,
            create_judicial_package,
        )
        customer, ev = bring_evidence_to_confirmed(balance_cents=100_000)
        create_certificate(ev)
        pkg = create_judicial_package(ev, authority_code="COURT_BJ")

        results = run_race(
            lambda: api.seal_judicial_package(pkg["id"], JUDICIAL),
            lambda: api.seal_judicial_package(pkg["id"], JUDICIAL),
        )
        winners = [r for r in results if 200 <= r.status_code < 300]
        losers = [r for r in results if r.status_code >= 400]
        assert len(winners) == 1
        assert len(losers) == 1
        validate_error(losers[0], ApiErrorId.ERR_INVALID_STATE.value)
