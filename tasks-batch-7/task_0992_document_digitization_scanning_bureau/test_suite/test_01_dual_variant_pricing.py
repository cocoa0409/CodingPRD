"""Dual-variant pricing tests (invoice pricing + storage fee projection)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId,
    create_client_with_agreement, create_batch, create_box, create_document,
    create_scanner_unit, create_shelf_slot, shelve_box, set_clock,
    batch_in_indexing, index_document, batch_delivered,
    get_invoice_id_for_batch, get_invoice,
    get_batch_version, commit_session, scan_and_commit, open_session_with_logs,
    batch_in_scanning,
    get_box, get_batch_version as _get_bv,
    make_platform_admin_headers, make_intake_clerk_headers,
    make_scan_operator_headers, make_qa_reviewer_headers,
    make_indexer_headers, make_billing_clerk_headers, make_client_user_headers,
    CLERK, SCAN, QA, IDX, BILL,
)


# ---------------------------------------------------------------------------
# Queue A — Difficulty / dual_variant_calc
# ---------------------------------------------------------------------------

class TestInvoicePricingProvisionalVsFinal:
    """Two tests per Difficulty instance
    `invoice_pricing_provisional_includes_rejected_final_excludes`."""

    def test_provisional_includes_rejected_pages_before_delivery(self, api):
        """PRD §3.6: "While the batch has not yet reached `DELIVERED`, the
        provisional variant bills everything produced so far: the document set
        is `SCANNED`, `QA_FAILED`, `INDEXED`, `DELIVERED`, and `REJECTED` —
        rejected pages were work produced, and QA-failed pages are still
        billable."

        Design: Difficulty/dual_variant_calc/invoice_pricing_provisional_includes_rejected_final_excludes
        """
        # Setup: 3 documents (100p ocr 95, 25p ocr 90, 10p ocr 50). All scanned.
        # After advancing to INDEXING, d3 (ocr 50) will be REJECTED at index
        # submission; the provisional read BEFORE deliver still counts d3.
        client, _ = create_client_with_agreement(
            name="Acme Legal", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_scanning(
            [
                {"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95},
                {"doc_type": "INVOICE", "pages": 25, "ocr_confidence": 90},
                {"doc_type": "OTHER", "pages": 10, "ocr_confidence": 50},
            ],
            client_id=client["id"],
        )
        # Scan all docs in one session
        specs = [(d["id"], d["pages"]) for d in ctx["documents"]]
        scan_and_commit(ctx, specs)
        get_success_data(api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
        get_success_data(api_client.pass_qa(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))

        # Index d1, d2; submit for d3 (REJECTED branch via ocr 50)
        for i, doc in enumerate(ctx["documents"]):
            get_success_data(index_document(doc["id"], title=f"T{i+1}", record_date=f"2026-01-0{i+1}", subject=f"S{i+1}", ocr_text_ref=f"ocr://t{i+1}"))

        # Provisional read BEFORE deliver: REJECTED d3 still billed.
        inv_id = get_invoice_id_for_batch(ctx["batch"]["id"])
        inv = get_invoice(inv_id)
        # 100*0.45*100=4500 + 25*0.45*100=1125 + 10*0.45*100=450 = 6075
        assert inv["page_subtotal_cents"] == 6075, (
            f"provisional subtotal should include the REJECTED doc: got {inv['page_subtotal_cents']}"
        )
        # d3 confirmed REJECTED
        d3 = get_success_data(api_client.get_document(ctx["documents"][2]["id"], make_qa_reviewer_headers(QA)))
        assert d3["status"] == "REJECTED"

    def test_final_excludes_rejected_pages_after_delivery(self, api):
        """PRD §3.6: "From delivery onward, the final variant's document set is
        `SCANNED`, `INDEXED`, and `DELIVERED` only; rejected documents are
        removed from the bill because undeliverable work is not charged at
        settlement."

        Design: Difficulty/dual_variant_calc/invoice_pricing_provisional_includes_rejected_final_excludes
        """
        client, _ = create_client_with_agreement(
            name="Acme Legal", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_scanning(
            [
                {"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95},
                {"doc_type": "INVOICE", "pages": 25, "ocr_confidence": 90},
                {"doc_type": "OTHER", "pages": 10, "ocr_confidence": 50},
            ],
            client_id=client["id"],
        )
        specs = [(d["id"], d["pages"]) for d in ctx["documents"]]
        scan_and_commit(ctx, specs)
        get_success_data(api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
        get_success_data(api_client.pass_qa(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        for i, doc in enumerate(ctx["documents"]):
            get_success_data(index_document(doc["id"], title=f"T{i+1}", record_date=f"2026-01-0{i+1}", subject=f"S{i+1}", ocr_text_ref=f"ocr://t{i+1}"))

        inv_id = get_invoice_id_for_batch(ctx["batch"]["id"])
        prov = get_invoice(inv_id)["page_subtotal_cents"]
        assert prov == 6075

        get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        final_inv = get_invoice(inv_id)
        # After delivery, d3 (REJECTED) is excluded: 4500 + 1125 = 5625
        assert final_inv["page_subtotal_cents"] == 5625, (
            f"final subtotal should exclude the REJECTED doc: got {final_inv['page_subtotal_cents']}"
        )
        assert final_inv["page_subtotal_cents"] != prov

        # Batch state post-delivery
        batch = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_billing_clerk_headers(BILL)))
        assert batch["status"] == "DELIVERED"
        assert batch["delivery_status"] == "PARTIAL"


class TestStorageFeeProjectedVsFrozenAtIssue:
    """Two tests for Difficulty instance `storage_fee_projected_vs_frozen_at_issue`."""

    def _setup_delivered_stored_box(self):
        """Build a delivered batch with one STORED box (600g) on GENERAL slot."""
        client, _ = create_client_with_agreement(
            name="Med Recs Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        slot = create_shelf_slot(shelf_code="SH-G1", zone="GENERAL", capacity_grams=2000)
        ctx = batch_in_scanning(
            [{"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        shelve_box(ctx["box"]["id"], slot["id"])
        specs = [(d["id"], d["pages"]) for d in ctx["documents"]]
        scan_and_commit(ctx, specs)
        get_success_data(api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
        get_success_data(api_client.pass_qa(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        get_success_data(index_document(ctx["documents"][0]["id"], title="T1", record_date="2026-01-01", subject="S1", ocr_text_ref="ocr://t1"))
        set_clock("2026-05-10T00:00:00Z")
        get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        return client, ctx, slot

    def test_projected_variant_accrues_then_shrinks_on_return(self, api):
        """PRD §3.6: "The projected variant evaluates the accrual as of the
        current logical clock: it surfaces on batch reads as
        `projected_storage_fee_cents` and on a `DRAFT` invoice as
        `storage_subtotal_cents`, grows as the clock advances, and shrinks
        when boxes reach `DESTROYED` or `RETURNED`."

        Design: Difficulty/dual_variant_calc/storage_fee_projected_vs_frozen_at_issue
        """
        client, ctx, _slot = self._setup_delivered_stored_box()
        # 2026-05-22 is 12 whole days after delivered_at 2026-05-10; minus 10
        # free days => 2 chargeable days x 55c = 110.
        set_clock("2026-05-22T00:00:00Z")
        batch = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_billing_clerk_headers(BILL)))
        assert batch["projected_storage_fee_cents"] == 110, (
            f"expected 110c projected at 2026-05-22, got {batch['projected_storage_fee_cents']}"
        )

        # Return the box: projected accrual must drop back to 0.
        get_success_data(api_client.request_return(ctx["box"]["id"], make_client_user_headers(client["id"])))
        get_success_data(api_client.mark_returned(ctx["box"]["id"], make_intake_clerk_headers(CLERK)))
        box = get_box(ctx["box"]["id"])
        assert box["status"] == "RETURNED"

        set_clock("2026-05-30T00:00:00Z")
        batch2 = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_billing_clerk_headers(BILL)))
        assert batch2["projected_storage_fee_cents"] == 0, (
            f"RETURNED boxes must be excluded from projection, got {batch2['projected_storage_fee_cents']}"
        )

    def test_frozen_at_issue_diverges_from_projection_after_return(self, api):
        """PRD §3.6: "The actual-at-issue variant evaluates the same formula as
        of the invoice's `issued_at` and freezes it into `storage_subtotal_cents`
        at issue time; once issued the figure is immutable, two reads of an
        issued invoice at different clocks agree, and a projected read taken
        after a destruction is strictly smaller than the frozen issued value."

        Design: Difficulty/dual_variant_calc/storage_fee_projected_vs_frozen_at_issue
        """
        client, ctx, _slot = self._setup_delivered_stored_box()
        set_clock("2026-05-22T00:00:00Z")  # 2 chargeable days -> 110c
        inv_id = get_invoice_id_for_batch(ctx["batch"]["id"])
        get_success_data(api_client.issue_invoice(inv_id, make_billing_clerk_headers(BILL)))

        # Return the box and advance the clock
        get_success_data(api_client.request_return(ctx["box"]["id"], make_client_user_headers(client["id"])))
        get_success_data(api_client.mark_returned(ctx["box"]["id"], make_intake_clerk_headers(CLERK)))
        set_clock("2026-05-30T00:00:00Z")

        # Frozen issued invoice retains 110; live projection is 0.
        frozen = get_invoice(inv_id)
        assert frozen["storage_subtotal_cents"] == 110
        batch = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_billing_clerk_headers(BILL)))
        assert batch["projected_storage_fee_cents"] == 0
        assert batch["projected_storage_fee_cents"] != frozen["storage_subtotal_cents"]


# ---------------------------------------------------------------------------
# Queue B — Corner / calculations
# ---------------------------------------------------------------------------

class TestStorageFreeWindowBoundary:
    """Corner: storage_free_window_day_boundary."""

    def test_free_window_fully_elapsed_zero_then_one_day_accrues(self, api):
        """PRD §3.6: "For a given as-of instant, a box's chargeable days are
        the whole days fully elapsed between the batch's `delivered_at` and the
        as-of instant, minus the agreement's `storage_free_days`, floored at
        zero — a box becomes chargeable only after `delivered_at` plus the free
        window has fully elapsed, and partial days never count."

        Design: Corner/calculations/storage_free_window_day_boundary
        """
        client, _ = create_client_with_agreement(
            name="Store Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        slot = create_shelf_slot(shelf_code="SH-S", zone="GENERAL", capacity_grams=2000)
        ctx = batch_in_scanning(
            [{"doc_type": "CONTRACT", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        shelve_box(ctx["box"]["id"], slot["id"])
        specs = [(d["id"], d["pages"]) for d in ctx["documents"]]
        scan_and_commit(ctx, specs)
        get_success_data(api_client.submit_qa(ctx["batch"]["id"], make_scan_operator_headers(SCAN)))
        get_success_data(api_client.pass_qa(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))
        get_success_data(index_document(ctx["documents"][0]["id"], title="T1", record_date="2026-01-01", subject="S1", ocr_text_ref="ocr://t1"))
        set_clock("2026-05-10T00:00:00Z")
        get_success_data(api_client.deliver_batch(ctx["batch"]["id"], make_qa_reviewer_headers(QA)))

        # At exactly 10 elapsed days (2026-05-20): chargeable = max(0, 10-10) = 0
        set_clock("2026-05-20T00:00:00Z")
        b1 = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_billing_clerk_headers(BILL)))
        assert b1["projected_storage_fee_cents"] == 0

        # At 11 elapsed days (2026-05-21): chargeable = 1 -> 55c
        set_clock("2026-05-21T00:00:00Z")
        b2 = get_success_data(api_client.get_batch(ctx["batch"]["id"], make_billing_clerk_headers(BILL)))
        assert b2["projected_storage_fee_cents"] == 55


class TestRushMultiplierNotAppliedToStandardBatch:
    """Corner: rush_multiplier_not_applied_to_standard_batch."""

    def test_standard_priority_uses_base_rate_only(self, api):
        """PRD §3.6: "The applicable per-page rate depends only on the batch
        and its agreement: the base rate is 0.30 dollars per page when the
        agreement's `price_tier` is `VOLUME` and 0.45 dollars per page when it
        is `STANDARD`, and for a `RUSH` batch that base is then multiplied by
        the agreement's `rush_multiplier`."

        Design: Corner/calculations/rush_multiplier_not_applied_to_standard_batch
        """
        client, _ = create_client_with_agreement(
            name="Vol Co", hipaa_covered=False,
            price_tier="VOLUME", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        ctx = batch_in_scanning(
            [{"doc_type": "OTHER", "pages": 100, "ocr_confidence": 95}],
            client_id=client["id"], priority="STANDARD",
        )
        specs = [(d["id"], d["pages"]) for d in ctx["documents"]]
        scan_and_commit(ctx, specs)
        inv_id = get_invoice_id_for_batch(ctx["batch"]["id"])
        inv = get_invoice(inv_id)
        # 100 pages * 0.30 * 100 = 3000c; rush_multiplier NOT applied.
        assert inv["page_subtotal_cents"] == 3000, (
            f"STANDARD priority on VOLUME tier must bill 0.30/page flat, got {inv['page_subtotal_cents']}"
        )
