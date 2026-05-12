"""Batch anchoring: creation, size bounds, member validity, fee calculation.

PRD §3.5, §2.10 priorities 9/10/18.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_batch,
    BATCH_DISCOUNT_TIERS,
    bring_batch_to_confirmed,
    bring_batch_to_submitting,
    create_batch,
    create_batch_payload,
    create_customer,
    create_customer_with_balance,
    create_evidence,
    create_notarization,
    create_pending_evidences,
    get_customer,
    list_audit_logs,
    make_customer_headers,
    submit_batch,
    validate_error,
    validate_success,
)


# ===========================================================================
# Batch size lower boundary (priority 10)
# ===========================================================================
class TestBatchSizeLowerBoundary:
    """PRD §2.10 priority 10: 'Batch.evidence_count is at least 2 and
    at most 1000, inclusive of both endpoints, on POST /batches
    (ERR_BATCH_SIZE_OUT_OF_RANGE).'

    Also exercises difficulty-design 'batch_size_lower_boundary_at_two'.
    """

    def test_size_one_rejected(self, api):
        """PRD §2.10 priority 10: '... at least 2 ... ; a count outside
        that range rejects the batch with ERR_BATCH_SIZE_OUT_OF_RANGE.'"""
        customer = create_customer()
        e1 = create_evidence(customer)
        res = api.create_batch(
            create_batch_payload(
                customer_id=customer["id"], evidence_ids=[e1["id"]],
            ),
            make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_BATCH_SIZE_OUT_OF_RANGE.value)

    def test_size_two_accepted(self, api):
        """PRD §3.5: 'Batch.evidence_count is at least 2 ... a
        single-member batch is rejected upstream by the size validation.'
        The 5% tier requires evidence_count >= 2."""
        customer = create_customer()
        e1 = create_evidence(customer)
        e2 = create_evidence(customer)
        batch = validate_success(api.create_batch(
            create_batch_payload(
                customer_id=customer["id"],
                evidence_ids=[e1["id"], e2["id"]],
            ),
            make_customer_headers(customer["id"]),
        ), 201)
        assert_batch(batch)
        assert batch["evidence_count"] == 2


# ===========================================================================
# Batch member validity (priority 9)
# ===========================================================================
class TestBatchMemberValid:
    """PRD §2.10 priority 9: 'Every member evidence in a batch belongs
    to the same customer and is in PENDING with a null batch_id at
    batch creation (ERR_BATCH_MEMBER_INVALID).'"""

    def test_member_from_different_customer_rejected(self, api):
        c1 = create_customer()
        c2 = create_customer()
        e_c1_a = create_evidence(c1)
        e_c1_b = create_evidence(c1)
        e_c2 = create_evidence(c2)
        res = api.create_batch(
            create_batch_payload(
                customer_id=c1["id"],
                evidence_ids=[e_c1_a["id"], e_c1_b["id"], e_c2["id"]],
            ),
            make_customer_headers(c1["id"]),
        )
        validate_error(res, ApiErrorId.ERR_BATCH_MEMBER_INVALID.value)

    def test_member_already_in_batch_rejected(self, api):
        """PRD §2.10 priority 9: 'in PENDING with a null batch_id at
        batch creation'. An evidence whose batch_id is already set must
        not be added to another batch."""
        customer = create_customer()
        e1 = create_evidence(customer)
        e2 = create_evidence(customer)
        # Bind both to first batch.
        validate_success(api.create_batch(
            create_batch_payload(
                customer_id=customer["id"],
                evidence_ids=[e1["id"], e2["id"]],
            ),
            make_customer_headers(customer["id"]),
        ), 201)
        # Try to reuse e1 + a fresh e3 in a second batch.
        e3 = create_evidence(customer)
        res = api.create_batch(
            create_batch_payload(
                customer_id=customer["id"],
                evidence_ids=[e1["id"], e3["id"]],
            ),
            make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_BATCH_MEMBER_INVALID.value)


# ===========================================================================
# Batch creation side effects (PRD §3.5)
# ===========================================================================
class TestBatchCreationSideEffects:
    """PRD §3.5: 'The system then computes the Batch.merkle_root over
    the member file_hash values in their submission order, sets each
    member's batch_id to this batch's id, and leaves the batch in
    PENDING with total_fee_cents and submission_attempts initialised to
    null and zero respectively.'"""

    def test_creation_sets_member_batch_ids(self, api):
        customer = create_customer()
        evidences = create_pending_evidences(customer, count=3)
        batch = create_batch(
            customer, [e["id"] for e in evidences],
        )
        # Verify each member now has batch_id set.
        from test_helpers import get_evidence
        for ev in evidences:
            re_read = get_evidence(ev["id"])
            assert re_read["batch_id"] == batch["id"]

    def test_creation_computes_merkle_root(self, api):
        """PRD §3.5: 'computes the Batch.merkle_root over the member
        file_hash values'. We can't pin the exact root without
        re-implementing the algorithm, but we can assert it is a 64-char
        lowercase hex string per PRD §2.7."""
        customer = create_customer()
        evidences = create_pending_evidences(customer, count=4)
        batch = create_batch(
            customer, [e["id"] for e in evidences],
        )
        mr = batch["merkle_root"]
        assert isinstance(mr, str) and len(mr) == 64

    def test_initial_total_fee_is_null(self, api):
        """PRD §3.5: 'total_fee_cents and submission_attempts
        initialised to null and zero respectively.'"""
        customer = create_customer()
        evidences = create_pending_evidences(customer, count=2)
        batch = create_batch(customer, [e["id"] for e in evidences])
        assert batch["total_fee_cents"] is None
        assert batch["submission_attempts"] == 0
        assert batch["status"] == "PENDING"


# ===========================================================================
# Batch fee calculation (PRD §3.5)
# ===========================================================================
class TestBatchFeeCalculation:
    """PRD §3.5: 'The batch fee is computed by a two-step rounding
    protocol: round-per-line first, then sum, then apply the discount,
    then round once more.'

    Per-line: BASE_FEE_BY_TYPE * PERIOD_MULTIPLIER + 50 if
    original_data_b64 not null, else 0. Discount tiers: 100→0.20,
    50→0.15, 10→0.10, 2→0.05.
    """

    def test_two_members_apply_5pct_discount(self, api):
        """PRD §3.5: '5% when at least 2'.

        2 × IMAGE/90d (no original): per-line = round(300 * 2.50) = 750.
        Subtotal = 1500. Discount 5% → round(1500 * 0.95) = 1425.
        """
        customer, batch, _evidences = bring_batch_to_confirmed(
            member_count=2,
            evidence_overrides={
                "evidence_type": "IMAGE", "storage_period_days": 90,
            },
            balance_cents=10_000,
        )
        assert batch["status"] == "CONFIRMED"
        assert batch["total_fee_cents"] == 1425

    def test_ten_members_apply_10pct_discount(self, api):
        """PRD §3.5: '10% when at least 10'.

        10 × IMAGE/90d (no original): per-line=750; subtotal=7500;
        round(7500 * 0.90) = 6750. (Difficulty design
        'batch_fee_mode_b_round_per_line_then_sum_then_discount_then_round'
        target.)
        """
        customer, batch, _evidences = bring_batch_to_confirmed(
            member_count=10,
            evidence_overrides={
                "evidence_type": "IMAGE", "storage_period_days": 90,
            },
            balance_cents=100_000,
        )
        assert batch["total_fee_cents"] == 6750

    def test_batch_confirm_debits_once_and_flips_members(self, api):
        """PRD §3.5: 'pins Batch.total_fee_cents to the value the batch
        fee formula returns, debits the customer's wallet_balance_cents
        exactly once by that total ... appends audit rows of event_type
        BATCH_CONFIRMED and FEE_DEBITED. ... The cascade flips every
        member evidence to CONFIRMED'."""
        from test_helpers import get_evidence
        customer, batch, evidences = bring_batch_to_confirmed(
            member_count=2,
            evidence_overrides={
                "evidence_type": "DOCUMENT", "storage_period_days": 30,
            },
            balance_cents=5_000,
        )
        # Each per-line: round(200 * 1.00) = 200. Subtotal = 400.
        # Discount 5%. round(400 * 0.95) = 380.
        assert batch["total_fee_cents"] == 380
        cust_after = get_customer(customer["id"])
        assert cust_after["wallet_balance_cents"] == 5_000 - 380
        # Every member should now be CONFIRMED.
        for ev in evidences:
            re_read = get_evidence(ev["id"])
            assert re_read["status"] == "CONFIRMED"
        rows = list_audit_logs(
            event_type="BATCH_CONFIRMED",
            target_entity="Batch",
            target_id=batch["id"],
        )
        assert len(rows) >= 1


# ===========================================================================
# Batch submission preconditions (priority 18)
# ===========================================================================
class TestInsufficientBalanceOnBatchSubmit:
    """PRD §2.10 priority 18: 'Customer.wallet_balance_cents is at
    least the forward-looking batch fee quote (subtotal already
    including the volume discount) on batch submit
    (ERR_INSUFFICIENT_BALANCE).'"""

    def test_insufficient_balance_rejects_batch_submit(self, api):
        """PRD §3.5: 'Customer.wallet_balance_cents is at least the
        forward-looking batch fee quote' — too low → ERR_INSUFFICIENT_BALANCE."""
        # 2 × DOCUMENT/30: per-line 200, subtotal 400, *0.95 = 380.
        customer = create_customer_with_balance(balance_cents=100)
        evidences = create_pending_evidences(
            customer, count=2,
            evidence_overrides={
                "evidence_type": "DOCUMENT", "storage_period_days": 30,
            },
        )
        for ev in evidences:
            create_notarization(ev)
        batch = create_batch(customer, [e["id"] for e in evidences])
        res = api.submit_batch(
            batch["id"], make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)


# ===========================================================================
# Merkle proof endpoint
# ===========================================================================
class TestBatchProof:
    """PRD §3.5: 'A test caller can request the Merkle inclusion path
    for any member evidence — read-only output that proves a single
    member belongs to the aggregated root.'"""

    def test_proof_returns_for_member_evidence(self, api,
                                                admin_headers):
        customer, batch, evidences = bring_batch_to_submitting(
            member_count=4,
        )
        ev = evidences[0]
        res = api.get_batch_proof(
            batch["id"], ev["id"], admin_headers,
        )
        validate_success(res, 200)
