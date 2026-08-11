"""Manifest intake lifecycle: initial state, happy path to CLOSED, terminal
lockdown, cancellation and reconciliation guards (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    am_headers,
    new_account,
    new_manifest,
    scan_and_triage,
    scan_item,
    setup_closed_manifest,
    setup_received_manifest,
    validate_error,
    validate_success,
)


class TestManifestInitialState:
    def test_manifest_created_in_draft_with_zero_count(self, api):
        """PRD §3.3: "A new manifest is `DRAFT`, with `received_item_count` zero and `discrepancy_flag` false; the flag simply records whether `received_item_count` differs from `declared_item_count`."

        Design: Corner/state_machines/manifest_initial_state_draft
        """
        account = new_account("Init Co", "init@x.example")
        resp = api.create_manifest(
            {
                "account_id": account["id"],
                "mode": "DROPOFF",
                "scheduled_start": "2026-06-01T09:00:00Z",
                "scheduled_end": "2026-06-01T11:00:00Z",
                "declared_item_count": 1,
            },
            am_headers(account),
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"
        assert data["received_item_count"] == 0
        assert data["discrepancy_flag"] is False


class TestManifestHappyPath:
    def test_manifest_full_lifecycle_reaches_closed(self, api):
        """PRD §3.3: "Closure by an `AccountManager` is available from `RECONCILED`, and only after the money has settled: at least one settlement must exist for the manifest, and every settlement that has not been superseded must be `PAID` or `VOIDED`, otherwise the close is rejected with `ERR_CLOSE_SETTLEMENT_UNPAID`."

        Design: Corner/state_machines/manifest_happy_path_draft_to_closed
        """
        ctx = setup_closed_manifest(sale_price_cents=60000)
        assert ctx["settlement"]["status"] == "PAID"
        assert ctx["manifest"]["status"] == "CLOSED"

    def test_sold_item_completes_at_finalize(self, api, intake_operator_headers):
        """PRD §3.8: "Finalization flips `kind` to `FINAL` and `status` `QUOTE_OPEN` → `FINALIZED`, moves every `SOLD` item of the manifest to `COMPLETE` — each such completion adding the item's weight to `lifetime_diverted_kg` and possibly upgrading the account tier, since resale counts as diversion — and recomputes all four totals under the final variant: only `COMPLETE` items count, sold items contribute their realized net `final_value_cents`, recycled and unsold items contribute zero, fees are computed on the final basis, and the rebate rule runs unchanged."

        Design: Corner/state_machines/manifest_happy_path_draft_to_closed
        """
        ctx = setup_closed_manifest(sale_price_cents=60000)
        item = validate_success(api.get_item(ctx["item"]["id"], intake_operator_headers))
        assert item["processing_status"] == "COMPLETE"


class TestManifestTerminalLockdown:
    def test_cancel_closed_manifest_rejected(self, api):
        """PRD §3.3: "`CLOSED` and `CANCELLED` are terminal; a terminal manifest rejects every further transition with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_closed_manifest_returns_409
        """
        ctx = setup_closed_manifest(sale_price_cents=60000)
        resp = api.cancel_manifest(ctx["manifest"]["id"], am_headers(ctx["account"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409


class TestManifestCancellation:
    def test_cancel_with_scanned_items_rejected(self, api):
        """PRD §3.3: "Cancellation by an `AccountManager` is available from either `DRAFT` or `SCHEDULED`, but only while nothing has been scanned: once `received_item_count` is non-zero, cancellation is rejected with `ERR_MANIFEST_HAS_ITEMS`."

        Design: Corner/state_machines/cancel_with_items_rejected
        """
        account = new_account("CX Co", "cx@x.example")
        manifest = new_manifest(account)
        scan_item(manifest["id"], serial_number="SN-CX1")

        resp = api.cancel_manifest(manifest["id"], am_headers(account))
        validate_error(resp, ApiErrorId.ERR_MANIFEST_HAS_ITEMS)
        assert resp.status_code == 422

        manifest = validate_success(api.get_manifest(manifest["id"], am_headers(account)))
        assert manifest["status"] == "DRAFT"


class TestManifestReconciliation:
    def test_reconcile_count_mismatch_rejected(self, api, intake_operator_headers):
        """PRD §3.3: "Reconciliation enforces its checks in order: the manifest must be in `RECEIVED`; no item of the manifest may still sit in `INTAKE` — both violations surface as `ERR_INVALID_STATE`, and both run before the count checks; then at least one item must have been scanned (`ERR_MANIFEST_EMPTY`); and finally the scanned count must equal the declared count (`ERR_MANIFEST_ITEM_COUNT_MISMATCH`)."

        Design: Corner/state_machines/reconcile_count_mismatch_rejected
        """
        account, manifest = setup_received_manifest(declared_item_count=2)
        scan_and_triage(manifest["id"], "RECYCLE", serial_number="SN-MM1")

        resp = api.reconcile_manifest(manifest["id"], intake_operator_headers)
        validate_error(resp, ApiErrorId.ERR_MANIFEST_ITEM_COUNT_MISMATCH)
        assert resp.status_code == 422

    def test_reconcile_with_zero_items_returns_empty_error(self, api, intake_operator_headers):
        """PRD §3.3: "Reconciliation enforces its checks in order: the manifest must be in `RECEIVED`; no item of the manifest may still sit in `INTAKE` — both violations surface as `ERR_INVALID_STATE`, and both run before the count checks; then at least one item must have been scanned (`ERR_MANIFEST_EMPTY`); and finally the scanned count must equal the declared count (`ERR_MANIFEST_ITEM_COUNT_MISMATCH`)."

        Design: Difficulty/boundary_precision_check/reconcile_with_zero_items_is_empty_error
        """
        account, manifest = setup_received_manifest(declared_item_count=1)
        resp = api.reconcile_manifest(manifest["id"], intake_operator_headers)
        validate_error(resp, ApiErrorId.ERR_MANIFEST_EMPTY)
        assert resp.status_code == 422

    def test_reconcile_with_zero_items_leaves_manifest_received(self, api, intake_operator_headers):
        """PRD §3.3: "Reconciliation enforces its checks in order: the manifest must be in `RECEIVED`; no item of the manifest may still sit in `INTAKE` — both violations surface as `ERR_INVALID_STATE`, and both run before the count checks; then at least one item must have been scanned (`ERR_MANIFEST_EMPTY`); and finally the scanned count must equal the declared count (`ERR_MANIFEST_ITEM_COUNT_MISMATCH`)."

        Design: Difficulty/boundary_precision_check/reconcile_with_zero_items_is_empty_error
        """
        account, manifest = setup_received_manifest(declared_item_count=1)
        validate_error(api.reconcile_manifest(manifest["id"], intake_operator_headers),
                       ApiErrorId.ERR_MANIFEST_EMPTY)
        manifest = validate_success(api.get_manifest(manifest["id"], intake_operator_headers))
        assert manifest["status"] == "RECEIVED"
