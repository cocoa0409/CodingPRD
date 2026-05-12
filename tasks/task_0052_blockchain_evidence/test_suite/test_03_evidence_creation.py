"""Evidence creation: input fields, hash format, period enum, idempotency.

PRD §3.2, §2.7, §2.10 priorities 8/11/20.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_evidence,
    create_customer,
    create_customer_with_balance,
    create_evidence,
    create_evidence_payload,
    make_customer_headers,
    random_sha256_hex,
    unique_suffix,
    validate_error,
    validate_success,
)


# ===========================================================================
# Successful creation (PRD §3.2)
# ===========================================================================
class TestEvidenceCreate:
    """PRD §3.2: 'The newly created Evidence starts in PENDING, with
    submission_attempts at zero and per_evidence_fee_cents, batch_id,
    confirmed_at, and expires_at all null.'"""

    def test_create_evidence_defaults(self, api):
        customer = create_customer_with_balance(balance_cents=0)
        headers = make_customer_headers(customer["id"])
        res = api.create_evidence(
            create_evidence_payload(customer_id=customer["id"]),
            headers,
        )
        ev = validate_success(res, 201)
        assert_evidence(ev)
        assert ev["customer_id"] == customer["id"]
        assert ev["status"] == "PENDING"
        assert ev["submission_attempts"] == 0
        assert ev["per_evidence_fee_cents"] is None
        assert ev["batch_id"] is None
        assert ev["confirmed_at"] is None
        assert ev["expires_at"] is None
        assert ev["version"] == 1


# ===========================================================================
# Hash format (PRD §2.7 / priority 8)
# ===========================================================================
class TestHashFormatInvalid:
    """PRD §2.7: 'Both SHA256 and SM3 produce 64-character lowercase hex
    strings, and file_hash must match that exact length and alphabet
    for the declared hash_algorithm; a mismatch is rejected with
    ERR_HASH_FORMAT_INVALID.'"""

    @pytest.mark.parametrize("bad_hash", [
        "tooshort",                              # length wrong
        "g" * 64,                                # non-hex character
        "A" * 64,                                # uppercase rejected
        "0" * 63,                                # one short
        "0" * 65,                                # one long
    ])
    def test_invalid_file_hash_format_rejected(self, api, bad_hash):
        """PRD §2.7: 'file_hash must match that exact length and
        alphabet for the declared hash_algorithm; a mismatch is rejected
        with ERR_HASH_FORMAT_INVALID.'"""
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        res = api.create_evidence(
            create_evidence_payload(
                customer_id=customer["id"],
                hash_algorithm="SHA256",
                file_hash=bad_hash,
            ),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_HASH_FORMAT_INVALID.value)

    def test_valid_sm3_hash_accepted(self, api):
        """PRD §2.7: 'Both SHA256 and SM3 produce 64-character lowercase
        hex strings'."""
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        res = api.create_evidence(
            create_evidence_payload(
                customer_id=customer["id"],
                hash_algorithm="SM3",
                file_hash=random_sha256_hex(),
            ),
            headers,
        )
        ev = validate_success(res, 201)
        assert ev["hash_algorithm"] == "SM3"


# ===========================================================================
# Storage period enum (PRD §2.10 priority 11)
# ===========================================================================
class TestStoragePeriodEnum:
    """PRD §2.10 priority 11: 'storage_period_days is exactly one of 30,
    90, 365, or 1095 on POST /evidences (ERR_PERIOD_INVALID).'

    Also exercises difficulty-design instance
    'storage_period_enum_membership_exact_set'.
    """

    @pytest.mark.parametrize("good_period", [30, 90, 365, 1095])
    def test_valid_period_accepted(self, api, good_period):
        """PRD §2.10 priority 11: valid values 30, 90, 365, 1095."""
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        res = api.create_evidence(
            create_evidence_payload(
                customer_id=customer["id"],
                storage_period_days=good_period,
            ),
            headers,
        )
        ev = validate_success(res, 201)
        assert ev["storage_period_days"] == good_period

    @pytest.mark.parametrize("bad_period", [0, 1, 29, 31, 89, 91, 364, 366, 1094, 1096, 365000])
    def test_invalid_period_rejected(self, api, bad_period):
        """PRD §2.10 priority 11: any other value rejected with
        ERR_PERIOD_INVALID."""
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        res = api.create_evidence(
            create_evidence_payload(
                customer_id=customer["id"],
                storage_period_days=bad_period,
            ),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_PERIOD_INVALID.value)


# ===========================================================================
# Evidence type enum (PRD §3.2)
# ===========================================================================
class TestEvidenceTypeEnum:
    """PRD §3.2: 'The customer chooses the evidence_type (one of
    DOCUMENT, IMAGE, VIDEO, CODE_REPOSITORY, or DATASET)'."""

    @pytest.mark.parametrize("ev_type", [
        "DOCUMENT", "IMAGE", "VIDEO", "CODE_REPOSITORY", "DATASET",
    ])
    def test_each_evidence_type_accepted(self, api, ev_type):
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        res = api.create_evidence(
            create_evidence_payload(
                customer_id=customer["id"], evidence_type=ev_type,
            ),
            headers,
        )
        ev = validate_success(res, 201)
        assert ev["evidence_type"] == ev_type

    def test_unknown_evidence_type_rejected(self, api):
        """PRD §2.10: generic body-shape failure → ERR_VALIDATION_FAILED."""
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        res = api.create_evidence(
            create_evidence_payload(
                customer_id=customer["id"],
                evidence_type="NOT_A_TYPE",
            ),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION_FAILED.value)


# ===========================================================================
# Chain id enum (PRD §2.8)
# ===========================================================================
class TestChainIdEnum:
    """PRD §2.8: 'The platform supports four target chains, identified
    by the chain_id enumeration whose only legal values are ETHEREUM,
    FABRIC, BSN, and COSMOS.'"""

    @pytest.mark.parametrize(
        "chain", ["ETHEREUM", "FABRIC", "BSN", "COSMOS"],
    )
    def test_each_chain_accepted(self, api, chain):
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        res = api.create_evidence(
            create_evidence_payload(
                customer_id=customer["id"], chain_id=chain,
            ),
            headers,
        )
        ev = validate_success(res, 201)
        assert ev["chain_id"] == chain


# ===========================================================================
# Idempotency key (PRD §3.2 / priority 20)
# ===========================================================================
class TestIdempotencyKey:
    """PRD §3.2: 'An optional idempotency_key makes the submission safe
    to retry on the wire — the pair (customer_id, idempotency_key) is
    unique per customer when the key is present, and a duplicate
    submission is rejected with ERR_DUPLICATE_IDEMPOTENCY_KEY.'

    PRD §2.11: 'Two POST /evidences requests with the same
    (customer_id, idempotency_key) are deduplicated similarly: only the
    first creates a row, the second receives ERR_DUPLICATE_IDEMPOTENCY_KEY.'
    """

    def test_duplicate_key_same_customer_rejected(self, api):
        """PRD §2.11: 'only the first creates a row, the second receives
        ERR_DUPLICATE_IDEMPOTENCY_KEY.'"""
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        key = f"idem-{unique_suffix()}"
        validate_success(api.create_evidence(
            create_evidence_payload(
                customer_id=customer["id"], idempotency_key=key,
            ),
            headers,
        ), 201)
        res = api.create_evidence(
            create_evidence_payload(
                customer_id=customer["id"], idempotency_key=key,
            ),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_IDEMPOTENCY_KEY.value)

    def test_same_key_different_customer_allowed(self, api):
        """PRD §3.2: '(customer_id, idempotency_key) is unique PER
        CUSTOMER when the key is present'."""
        c1 = create_customer()
        c2 = create_customer()
        key = f"idem-{unique_suffix()}"
        validate_success(api.create_evidence(
            create_evidence_payload(
                customer_id=c1["id"], idempotency_key=key,
            ),
            make_customer_headers(c1["id"]),
        ), 201)
        # c2 uses the same key value — should succeed (different customer).
        validate_success(api.create_evidence(
            create_evidence_payload(
                customer_id=c2["id"], idempotency_key=key,
            ),
            make_customer_headers(c2["id"]),
        ), 201)


# ===========================================================================
# Suspended customer cannot submit (PRD §3.1)
# ===========================================================================
# PRD §3.1: 'a SUSPENDED customer is not permitted to submit new evidence.'
# PRD does not expose an endpoint to flip Customer.status to SUSPENDED, so
# this rule is not testable from the PRD-only contract. Silence-pattern
# category: applies_to-scope — no public path makes a Customer SUSPENDED.
