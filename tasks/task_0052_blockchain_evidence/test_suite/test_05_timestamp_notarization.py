"""Timestamp notarization: creation, callback, verify, and the required
notarization gate on chain confirmation cascade.

PRD §3.2, §2.10 priority 13.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_timestamp_notarization,
    bring_evidence_to_submitting,
    chain_confirm,
    create_customer_with_balance,
    create_evidence,
    create_notarization,
    create_timestamp_notarization_payload,
    get_evidence,
    iso_z,
    latest_onchain_tx_for_evidence,
    make_customer_headers,
    notary_callback_payload,
    submit_evidence,
    validate_error,
    validate_success,
)
from datetime import datetime, timezone


# ===========================================================================
# Create notarization
# ===========================================================================
class TestCreateNotarization:
    """PRD §3.2: 'the customer (or, on the customer's behalf, a
    NotaryOfficer) creates the notarization by naming the evidence_id,
    choosing a tsa_provider from RFC3161_TSA_A, RFC3161_TSA_B, or
    NOTARY_OFFICE, and supplying a notary_office_id when, and only
    when, the provider is the notary office.'"""

    def test_create_with_rfc3161_provider(self, api):
        customer = create_customer_with_balance(balance_cents=0)
        evidence = create_evidence(customer)
        res = api.create_timestamp_notarization(
            create_timestamp_notarization_payload(
                evidence_id=evidence["id"],
                tsa_provider="RFC3161_TSA_A",
            ),
            make_customer_headers(customer["id"]),
        )
        notar = validate_success(res, 201)
        assert_timestamp_notarization(notar)
        assert notar["evidence_id"] == evidence["id"]
        assert notar["tsa_provider"] == "RFC3161_TSA_A"

    def test_create_with_notary_office(self, api):
        """PRD §3.2: 'supplying a notary_office_id when, and only when,
        the provider is the notary office.'"""
        customer = create_customer_with_balance(balance_cents=0)
        evidence = create_evidence(customer)
        res = api.create_timestamp_notarization(
            create_timestamp_notarization_payload(
                evidence_id=evidence["id"],
                tsa_provider="NOTARY_OFFICE",
                notary_office_id="NO-001",
            ),
            make_customer_headers(customer["id"]),
        )
        notar = validate_success(res, 201)
        assert notar["tsa_provider"] == "NOTARY_OFFICE"
        assert notar["notary_office_id"] == "NO-001"


# ===========================================================================
# Notary callback (PRD §3.2)
# ===========================================================================
class TestNotaryCallback:
    """PRD §3.2: 'The platform completes the notarization
    asynchronously via the notary callback, which populates trusted_time
    (the authoritative ISO 8601 instant returned by the TSA) and
    tsa_token (the opaque proof of issuance).'"""

    def test_callback_populates_trusted_time_and_token(self, api,
                                                       admin_headers):
        customer = create_customer_with_balance(balance_cents=0)
        evidence = create_evidence(customer)
        notar = validate_success(api.create_timestamp_notarization(
            create_timestamp_notarization_payload(
                evidence_id=evidence["id"],
                tsa_provider="RFC3161_TSA_A",
            ),
            make_customer_headers(customer["id"]),
        ), 201)
        trusted_time = iso_z(datetime.now(timezone.utc))
        validate_success(api.deliver_notary_callback(
            notary_callback_payload(
                timestamp_notarization_id=notar["id"],
                trusted_time=trusted_time,
                tsa_token="opaque-token-xyz",
            ),
            admin_headers,
        ), 200)
        # Read back
        got = validate_success(api.get_timestamp_notarization(
            notar["id"], admin_headers,
        ), 200)
        assert got["trusted_time"] == trusted_time
        assert got["tsa_token"] == "opaque-token-xyz"


# ===========================================================================
# Notarization REQUIRED for confirmation cascade (priority 13)
# ===========================================================================
class TestTimestampRequiredOnConfirmCascade:
    """PRD §2.10 priority 13: 'The target Evidence of a chain
    confirmation already has a TimestampNotarization attached; missing
    notarization rejects the confirmation cascade with
    ERR_TIMESTAMP_REQUIRED.'

    Also exercises difficulty-design
    'evidence_confirmation_requires_timestamp_notarization'.
    """

    def test_confirm_without_notarization_rejected(self, api,
                                                    admin_headers):
        """PRD §2.10 priority 13: chain-confirm cascade requires
        TimestampNotarization → ERR_TIMESTAMP_REQUIRED on missing."""
        customer = create_customer_with_balance(balance_cents=1_000)
        evidence = create_evidence(customer)
        # NO notarization attached.
        submit_evidence(evidence)
        tx = latest_onchain_tx_for_evidence(evidence["id"])
        # The chain-confirm call itself should fail because the cascade
        # target Evidence lacks a TimestampNotarization.
        from test_helpers import chain_confirm_payload
        res = api.chain_confirm(
            chain_confirm_payload(
                tx_id=tx["id"],
                block_height=10_000,
                confirmations=12,
            ),
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_TIMESTAMP_REQUIRED.value)
        # PRD §2.10 priority 13: a missing-notarization rejection leaves
        # the Evidence in SUBMITTING (no transition occurred).
        ev_after = get_evidence(evidence["id"])
        assert ev_after["status"] == "SUBMITTING"
