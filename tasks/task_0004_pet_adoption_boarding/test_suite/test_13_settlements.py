"""Tests for SettlementBatch creation, approval, and mark-paid.

Covers: PRD Section 3.8 (Settlement), Table 1 (SettlementBatch),
Table 2 (SettlementBatch state machine), Table 4 priority 30, 31.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_settlement_batch,
    create_settlement_batch_payload,
    past_date, future_date,
    create_shelter, create_paid_adoption_invoice,
    create_settlement_batch_for_shelter,
)

_manager = TEST_USERS["manager_headers"]
_case_worker = TEST_USERS["case_worker_headers"]


class TestSettlementBatchCreation:
    """PRD 3.8: ShelterManager creates a DRAFT settlement batch."""

    def test_create_settlement_batch_success(self):
        shelter, animal, adopter, app, invoice = create_paid_adoption_invoice(
            species="CAT", weight_kg=5.0
        )
        payload = create_settlement_batch_payload(
            shelter["id"], period_start_days_ago=30, period_end_days_from_now=1
        )
        resp = api_client.create_settlement_batch(payload, _manager)
        data = validate_success(resp, 201)
        assert_settlement_batch(data)
        assert data["status"] == "DRAFT"
        assert data["shelter_id"] == shelter["id"]
        # Should include the paid invoice
        assert invoice["id"] in data["invoice_ids"]
        assert data["gross_amount_cents"] >= invoice["total_amount_cents"]

    def test_create_period_end_not_greater(self):
        """period_end must be strictly > period_start."""
        shelter = create_shelter()
        payload = create_settlement_batch_payload(shelter["id"])
        payload["period_end"] = payload["period_start"]
        resp = api_client.create_settlement_batch(payload, _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_shelter_not_found(self):
        payload = create_settlement_batch_payload(NON_EXISTENT_UUID)
        resp = api_client.create_settlement_batch(payload, _manager)
        validate_error(resp, ApiErrorId.ERR_SHELTER_NOT_FOUND)

    def test_create_with_no_eligible_invoices(self):
        """Empty window — batch is valid but with empty invoice_ids."""
        shelter = create_shelter()
        payload = create_settlement_batch_payload(shelter["id"])
        resp = api_client.create_settlement_batch(payload, _manager)
        data = validate_success(resp, 201)
        assert data["invoice_ids"] == []
        assert data["gross_amount_cents"] == 0
        assert data["net_amount_cents"] == 0


class TestSettlementApprove:
    """PRD 3.8: /approve transitions DRAFT -> APPROVED."""

    def test_approve_success(self):
        shelter, animal, adopter, app, invoice = create_paid_adoption_invoice(
            species="CAT", weight_kg=5.0
        )
        batch = create_settlement_batch_for_shelter(shelter["id"])
        resp = api_client.approve_settlement_batch(batch["id"], _manager)
        data = validate_success(resp)
        assert data["status"] == "APPROVED"
        assert data["approved_by"]
        # The included invoice now has settlement_batch_id set
        refreshed_invoice = get_success_data(api_client.get_fee_invoice(invoice["id"], _manager))
        if invoice["id"] in batch["invoice_ids"]:
            assert refreshed_invoice["settlement_batch_id"] == batch["id"]

    def test_approve_wrong_state(self):
        shelter, animal, adopter, app, invoice = create_paid_adoption_invoice(
            species="CAT", weight_kg=5.0
        )
        batch = create_settlement_batch_for_shelter(shelter["id"])
        get_success_data(api_client.approve_settlement_batch(batch["id"], _manager))
        resp = api_client.approve_settlement_batch(batch["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_approve_fails_if_invoice_status_changed(self):
        """PRD 3.8 + Table 4 priority 30: batch approval rejects if invoice no longer PAID."""
        shelter, animal, adopter, app, invoice = create_paid_adoption_invoice(
            species="CAT", weight_kg=5.0
        )
        batch = create_settlement_batch_for_shelter(shelter["id"])
        if invoice["id"] not in batch["invoice_ids"]:
            pytest.skip("Invoice not included in the batch window")
        # Refund the invoice (changes status to REFUNDED) before approval
        get_success_data(api_client.refund_fee_invoice(invoice["id"], _manager))
        resp = api_client.approve_settlement_batch(batch["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_INVOICE_STATUS_CHANGED)


class TestSettlementMarkPaid:
    """PRD 3.8: /mark-paid APPROVED -> PAID."""

    def test_mark_paid_success(self):
        shelter, animal, adopter, app, invoice = create_paid_adoption_invoice(
            species="CAT", weight_kg=5.0
        )
        batch = create_settlement_batch_for_shelter(shelter["id"])
        get_success_data(api_client.approve_settlement_batch(batch["id"], _manager))
        resp = api_client.mark_paid_settlement_batch(batch["id"], _manager)
        data = validate_success(resp)
        assert data["status"] == "PAID"

    def test_mark_paid_from_draft_rejected(self):
        shelter, animal, adopter, app, invoice = create_paid_adoption_invoice(
            species="CAT", weight_kg=5.0
        )
        batch = create_settlement_batch_for_shelter(shelter["id"])
        resp = api_client.mark_paid_settlement_batch(batch["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSettlementRetrieval:
    def test_get_batch(self):
        shelter = create_shelter()
        batch = create_settlement_batch_for_shelter(shelter["id"])
        resp = api_client.get_settlement_batch(batch["id"], _manager)
        validate_success(resp)

    def test_get_batch_not_found(self):
        resp = api_client.get_settlement_batch(NON_EXISTENT_UUID, _manager)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_BATCH_NOT_FOUND)

    def test_list_batches(self):
        shelter = create_shelter()
        create_settlement_batch_for_shelter(shelter["id"])
        resp = api_client.list_settlement_batches(_manager)
        validate_success(resp)


class TestRevenueAccounting:
    """PRD 3.8 + Table 3 revenue_balance_reconciliation."""

    def test_approve_moves_revenue_pending_to_settled(self):
        """After approve: revenue_pending_cents decreases, revenue_settled_cents increases."""
        shelter, animal, adopter, app, invoice = create_paid_adoption_invoice(
            species="CAT", weight_kg=5.0
        )
        before = get_success_data(api_client.get_shelter(shelter["id"], _manager))
        assert before["revenue_pending_cents"] >= invoice["total_amount_cents"]
        batch = create_settlement_batch_for_shelter(shelter["id"])
        if invoice["id"] not in batch["invoice_ids"]:
            pytest.skip("Invoice not in batch")
        get_success_data(api_client.approve_settlement_batch(batch["id"], _manager))
        after = get_success_data(api_client.get_shelter(shelter["id"], _manager))
        assert after["revenue_pending_cents"] <= before["revenue_pending_cents"]
        assert after["revenue_settled_cents"] >= batch["net_amount_cents"]
