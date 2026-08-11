"""Item scanning validation, manifest computed counts, and the triage routing
machine (PRD §2.6, §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    new_account,
    new_manifest,
    scan_item,
    setup_received_manifest,
    setup_triaged_item,
    validate_error,
    validate_success,
)


class TestItemScanValidation:
    def test_item_create_invalid_category_rejected(self, api, intake_operator_headers):
        """PRD §2.6: "5. Request body schema — missing required fields, type mismatches, invalid enum members, a `weight_kg` that is not greater than zero, a `declared_item_count` below one, an `asking_price_cents` below `floor_price_cents`, a missing `pickup_route` on a `PICKUP` manifest (or one supplied on `DROPOFF`), or a `scheduled_end` that is not strictly after `scheduled_start` all yield `ERR_VALIDATION`."

        Design: Corner/entities/item_create_invalid_enum_category_rejected
        """
        _account, manifest = setup_received_manifest(declared_item_count=1)
        resp = api.add_manifest_item(
            manifest["id"],
            {
                "serial_number": "SN-E1",
                "category": "WIDGET",
                "weight_kg": 1.0,
                "data_bearing": False,
                "hazmat_flag": False,
                "declared_grade": "A",
            },
            intake_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert resp.status_code == 400

    def test_item_weight_must_be_positive(self, api, intake_operator_headers):
        """PRD §2.6: "5. Request body schema — missing required fields, type mismatches, invalid enum members, a `weight_kg` that is not greater than zero, a `declared_item_count` below one, an `asking_price_cents` below `floor_price_cents`, a missing `pickup_route` on a `PICKUP` manifest (or one supplied on `DROPOFF`), or a `scheduled_end` that is not strictly after `scheduled_start` all yield `ERR_VALIDATION`."

        Design: Corner/entities/item_weight_must_be_positive_rejected
        """
        _account, manifest = setup_received_manifest(declared_item_count=1)
        resp = api.add_manifest_item(
            manifest["id"],
            {
                "serial_number": "SN-W0",
                "category": "PHONE",
                "weight_kg": 0,
                "data_bearing": False,
                "hazmat_flag": False,
                "declared_grade": "B",
            },
            intake_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert resp.status_code == 400


class TestManifestComputedCounts:
    def test_received_count_and_discrepancy_flag_recomputed(self, api, intake_operator_headers):
        """PRD §3.4: "Each scan recomputes the manifest's `received_item_count` — and with it `discrepancy_flag` — and increments the manifest's `version`."
        PRD §3.3: "A new manifest is `DRAFT`, with `received_item_count` zero and `discrepancy_flag` false; the flag simply records whether `received_item_count` differs from `declared_item_count`."

        Design: Corner/entities/manifest_counts_computed
        """
        _account, manifest = setup_received_manifest(declared_item_count=2)
        scan_item(manifest["id"], serial_number="SN-N1", category="LAPTOP", weight_kg=2.0,
                  declared_grade="A")
        scan_item(manifest["id"], serial_number="SN-N2", category="PHONE", weight_kg=0.3,
                  declared_grade="B")

        manifest = validate_success(api.get_manifest(manifest["id"], intake_operator_headers))
        assert manifest["received_item_count"] == 2
        assert manifest["discrepancy_flag"] is False


class TestTriageManifestGate:
    def test_triage_on_draft_manifest_rejected(self, api, intake_operator_headers):
        """PRD §3.4: "Every triage call requires the owning manifest to be `RECEIVED`, and is rejected with `ERR_MANIFEST_NOT_RECEIVED` otherwise."
        PRD §3.4: "Each physical asset becomes an **Item** when an `IntakeOperator` scans it into a manifest, which is permitted while the manifest is `DRAFT` and again while it is `RECEIVED`; the scanned record carries the owning manifest's identity as its `manifest_id`."

        Design: Difficulty/cross_entity_state_dependency/triage_blocked_until_manifest_received
        """
        account = new_account("Gate Co", "g@gate.example")
        manifest = new_manifest(account)  # stays DRAFT; scanning is allowed in DRAFT
        item = scan_item(manifest["id"], serial_number="SN-G1")

        resp = api.triage_item(item["id"], {"disposition": "RESALE"}, intake_operator_headers)
        validate_error(resp, ApiErrorId.ERR_MANIFEST_NOT_RECEIVED)
        assert resp.status_code == 409

    def test_triage_rejection_leaves_item_intake(self, api, intake_operator_headers):
        """PRD §3.4: "Every triage call requires the owning manifest to be `RECEIVED`, and is rejected with `ERR_MANIFEST_NOT_RECEIVED` otherwise."

        Design: Difficulty/cross_entity_state_dependency/triage_blocked_until_manifest_received
        """
        account = new_account("Gate Co", "g@gate.example")
        manifest = new_manifest(account)
        item = scan_item(manifest["id"], serial_number="SN-G1")

        validate_error(api.triage_item(item["id"], {"disposition": "RESALE"},
                                       intake_operator_headers),
                       ApiErrorId.ERR_MANIFEST_NOT_RECEIVED)
        item = validate_success(api.get_item(item["id"], intake_operator_headers))
        assert item["processing_status"] == "INTAKE"
        assert item["disposition"] == "NONE"


class TestRefurbReroute:
    def test_refurb_reroute_to_recycle_zeroes_provisional_value(self, api, intake_operator_headers):
        """PRD §3.4: "Routing writes the `disposition` — `RESALE`, `REFURB`, or `RECYCLE` — and recomputes `provisional_value_cents`: resale- and refurbishment-routed items are re-estimated under the quote valuation of §3.8, while recycle-routed items carry a provisional value of exactly zero."
        PRD §3.4: "rerouting is allowed from `FOR_REFURB` to `FOR_RESALE` (refurbishment passed QA and the asset is worth selling as-is), from `FOR_REFURB` to `FOR_RECYCLE` (refurbishment proved uneconomical), and from `FOR_RESALE` to `FOR_RECYCLE` (resale abandoned)."

        Design: Corner/state_machines/refurb_reroute_to_recycle
        """
        ctx = setup_triaged_item(disposition="REFURB", category="LAPTOP", weight_kg=2.0,
                                 declared_grade="A", serial_number="SN-RR1")
        # REFURB triage re-estimates under the quote valuation: LAPTOP base
        # 40000 x grade-A multiplier 1.0 = 40000.
        assert ctx["item"]["provisional_value_cents"] == 40000

        resp = api.triage_item(ctx["item"]["id"], {"disposition": "RECYCLE"},
                               intake_operator_headers)
        item = validate_success(resp)
        assert item["processing_status"] == "FOR_RECYCLE"
        assert item["disposition"] == "RECYCLE"
        assert item["provisional_value_cents"] == 0
