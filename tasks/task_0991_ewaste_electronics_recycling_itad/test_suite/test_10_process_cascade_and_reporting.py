"""The batch processing completion cascade (items, recycler volume, auto-issued
Certificate of Recycling, tier upgrade), the chain-of-custody trail, and the
sustainability report (PRD §2.10, §3.1, §3.7, §3.9)."""
import pytest

from test_helpers import (
    add_to_batch,
    deliver_batch,
    new_account,
    new_active_policy,
    new_batch,
    new_manifest,
    new_recycler,
    process_batch,
    receive_manifest,
    scan_and_triage,
    scan_item,
    schedule_manifest,
    set_clock,
    setup_received_manifest,
    ship_batch,
    validate_paginated,
    validate_success,
)

DELIVERY = "2026-06-10T00:00:00Z"


def _setup_ten_server_batch():
    """Account + RECEIVED manifest with ten 100.0 kg SERVER items, all
    recycle-routed into one batch that is shipped and delivered."""
    new_active_policy()
    recycler = new_recycler(name="RecC", accepted_categories=["SERVER"],
                            daily_intake_capacity_kg=100000)
    account, manifest = setup_received_manifest(declared_item_count=10)
    items = [
        scan_and_triage(manifest["id"], "RECYCLE", serial_number=f"SN-S{i:02d}",
                        category="SERVER", weight_kg=100.0, declared_grade="C")
        for i in range(1, 11)
    ]
    batch = new_batch(recycler_id=recycler["id"], scheduled_delivery_date=DELIVERY)
    for item in items:
        batch = add_to_batch(batch["id"], item["id"])
    ship_batch(batch["id"])
    deliver_batch(batch["id"])
    return {"account": account, "manifest": manifest, "items": items,
            "recycler": recycler, "batch": batch}


class TestProcessCompletionCascade:
    def test_process_completes_items_and_upgrades_tier(self, api, compliance_officer_headers,
                                                       platform_admin_headers):
        """PRD §3.7: "Processing moves `DELIVERED` → `PROCESSED` and fires the completion cascade: every contained item moves `DOWNSTREAM` → `COMPLETE`; the batch's `gross_weight_kg` is added to the recycler's `total_processed_kg`; a Certificate of Recycling is auto-issued with `cert_type` `RECYCLING`, the `batch_id` populated, status `ISSUED`, and `issued_by_id` set to the literal `system`; each completing item adds its `weight_kg` to its account's `lifetime_diverted_kg` and may trigger the tier upgrade of §3.1; and custody entries of `event_type` `PROCESSED` are written for each item and for the batch itself."
        PRD §3.1: "at least 1000 kg promotes the account to `VOLUME`, and at least 5000 kg promotes it to `ENTERPRISE`, with both boundaries inclusive so that exactly 1000.0 kg is enough for `VOLUME`."

        Design: Difficulty/transitive_cascade/batch_process_depth3_cascade_tier_upgrade
        """
        ctx = _setup_ten_server_batch()
        validate_success(api.process_batch(ctx["batch"]["id"], compliance_officer_headers))

        items, _meta = validate_paginated(
            api.list_batch_items(ctx["batch"]["id"], compliance_officer_headers)
        )
        assert len(items) == 10
        assert all(item["processing_status"] == "COMPLETE" for item in items)

        account = validate_success(api.get_account(ctx["account"]["id"],
                                                   platform_admin_headers))
        # Ten completions x 100.0 kg accumulate to exactly the inclusive
        # VOLUME threshold, upgrading STANDARD -> VOLUME.
        assert account["lifetime_diverted_kg"] == pytest.approx(1000.0)
        assert account["tier"] == "VOLUME"

    def test_process_accumulates_recycler_processed_volume(self, api,
                                                           compliance_officer_headers):
        """PRD §3.7: "Processing moves `DELIVERED` → `PROCESSED` and fires the completion cascade: every contained item moves `DOWNSTREAM` → `COMPLETE`; the batch's `gross_weight_kg` is added to the recycler's `total_processed_kg`; a Certificate of Recycling is auto-issued with `cert_type` `RECYCLING`, the `batch_id` populated, status `ISSUED`, and `issued_by_id` set to the literal `system`; each completing item adds its `weight_kg` to its account's `lifetime_diverted_kg` and may trigger the tier upgrade of §3.1; and custody entries of `event_type` `PROCESSED` are written for each item and for the batch itself."

        Design: Difficulty/transitive_cascade/batch_process_depth3_cascade_tier_upgrade
        """
        ctx = _setup_ten_server_batch()
        validate_success(api.process_batch(ctx["batch"]["id"], compliance_officer_headers))

        recycler = validate_success(api.get_recycler(ctx["recycler"]["id"],
                                                     compliance_officer_headers))
        assert recycler["total_processed_kg"] == pytest.approx(1000.0)

    def test_process_auto_issues_recycling_certificate(self, api, compliance_officer_headers):
        """PRD §3.7: "a Certificate of Recycling is auto-issued with `cert_type` `RECYCLING`, the `batch_id` populated, status `ISSUED`, and `issued_by_id` set to the literal `system`"

        Design: Difficulty/transitive_cascade/batch_process_depth3_cascade_tier_upgrade
        """
        ctx = _setup_ten_server_batch()
        validate_success(api.process_batch(ctx["batch"]["id"], compliance_officer_headers))

        certs, _meta = validate_paginated(
            api.list_batch_certificates(ctx["batch"]["id"], compliance_officer_headers)
        )
        assert len(certs) == 1
        assert certs[0]["cert_type"] == "RECYCLING"
        assert certs[0]["batch_id"] == ctx["batch"]["id"]
        assert certs[0]["status"] == "ISSUED"
        assert certs[0]["issued_by_id"] == "system"


class TestCustodyTrail:
    def test_custody_events_recorded_through_recycle_chain(self, api,
                                                           compliance_officer_headers):
        """PRD §2.10: "Custody entries are written automatically by the workflows in §3 — facility receipt, batch transfer, downstream shipment, downstream delivery acknowledgment, and processing completion — and the trail is queryable by `subject_type` and `subject_id`, ordered by `created_at` ascending."
        PRD §3.7: "On success the item moves `FOR_RECYCLE` → `BATCHED`, its `recycle_batch_id` is set to the batch, a custody entry is written with `subject_type` `ITEM`, `event_type` `TRANSFERRED`, and `to_location` set to the literal prefix `batch:` followed by the batch's `id`, the batch totals are recomputed, and the batch's `version` increments."

        Design: Corner/state_machines/custody_events_recorded_through_recycle_chain
        """
        recycler = new_recycler(name="RecCu", accepted_categories=["OTHER"],
                                daily_intake_capacity_kg=1000)
        account, manifest = setup_received_manifest(declared_item_count=1)
        # Advance the logical clock between custody-writing steps so each entry
        # has a distinct created_at and the ascending order is deterministic.
        set_clock("2026-05-01T01:00:00Z")
        item = scan_and_triage(manifest["id"], "RECYCLE", serial_number="SN-CU1",
                               category="OTHER", weight_kg=3.0, declared_grade="D")
        batch = new_batch(recycler_id=recycler["id"], scheduled_delivery_date=DELIVERY)
        batch = add_to_batch(batch["id"], item["id"])
        set_clock("2026-05-01T02:00:00Z")
        ship_batch(batch["id"])
        set_clock("2026-05-01T03:00:00Z")
        deliver_batch(batch["id"])
        set_clock("2026-05-01T04:00:00Z")
        process_batch(batch["id"])

        manifest_events, _ = validate_paginated(api.list_custody_events(
            compliance_officer_headers,
            params={"subject_type": "MANIFEST", "subject_id": manifest["id"]},
        ))
        assert [e["event_type"] for e in manifest_events] == ["RECEIVED_FACILITY"]
        assert manifest_events[0]["subject_id"] == manifest["id"]

        item_events, _ = validate_paginated(api.list_custody_events(
            compliance_officer_headers,
            params={"subject_type": "ITEM", "subject_id": item["id"]},
        ))
        assert [e["event_type"] for e in item_events] == ["TRANSFERRED", "PROCESSED"]
        assert item_events[0]["to_location"] == f"batch:{batch['id']}"

        batch_events, _ = validate_paginated(api.list_custody_events(
            compliance_officer_headers,
            params={"subject_type": "BATCH", "subject_id": batch["id"]},
        ))
        assert [e["event_type"] for e in batch_events] == [
            "SHIPPED_DOWNSTREAM", "DELIVERED_DOWNSTREAM", "PROCESSED",
        ]


class TestSustainabilityReport:
    def test_report_partial_diversion(self, api, platform_admin_headers):
        """PRD §3.9: "The report's `total_items` counts every item the account has ever scanned, in any processing state, and `total_weight_kg` sums their `weight_kg` at three decimal places. The `diverted_weight_kg` sums weight over only those items that have reached `COMPLETE`, and the `diversion_rate_pct` expresses the diverted share as a percentage of total weight, rounded half-up to two decimal places; when the account has no weight at all, the rate is exactly 0.0 rather than a division failure. On the financial side, `resale_proceeds_cents` sums `final_value_cents` over completed items whose `disposition` is `RESALE` or `REFURB`, while `recycling_fees_cents` sums the per-line recycling fees — on the final fee basis of §3.8 — over completed recycle-routed items. Finally, `certificates_issued` counts the account's `ISSUED` certificates of type `DATA_DESTRUCTION`; certificates that have been voided are excluded from this count."

        Design: Corner/calculations/sustainability_report_partial_diversion
        """
        account = new_account("Rep Co", "rep@x.example")
        recycler = new_recycler(name="RecR", accepted_categories=["OTHER"],
                                daily_intake_capacity_kg=1000)
        # Manifest 1: one 2.0 kg OTHER item recycled all the way to COMPLETE.
        manifest_one = new_manifest(account, scheduled_start="2026-06-01T09:00:00Z",
                                    scheduled_end="2026-06-01T10:00:00Z")
        manifest_one = schedule_manifest(manifest_one["id"])
        manifest_one = receive_manifest(manifest_one["id"])
        item_one = scan_and_triage(manifest_one["id"], "RECYCLE", serial_number="SN-RP1",
                                   category="OTHER", weight_kg=2.0, declared_grade="D")
        batch = new_batch(recycler_id=recycler["id"], scheduled_delivery_date=DELIVERY)
        batch = add_to_batch(batch["id"], item_one["id"])
        ship_batch(batch["id"])
        deliver_batch(batch["id"])
        process_batch(batch["id"])

        # Manifest 2: one 2.0 kg LAPTOP scanned and left in INTAKE.
        manifest_two = new_manifest(account, scheduled_start="2026-06-02T09:00:00Z",
                                    scheduled_end="2026-06-02T10:00:00Z")
        manifest_two = schedule_manifest(manifest_two["id"])
        manifest_two = receive_manifest(manifest_two["id"])
        scan_item(manifest_two["id"], serial_number="SN-RP2", category="LAPTOP",
                  weight_kg=2.0, declared_grade="A")

        report = validate_success(api.get_sustainability_report(account["id"],
                                                                platform_admin_headers))
        assert report["total_items"] == 2
        assert report["total_weight_kg"] == pytest.approx(4.0)
        assert report["diverted_weight_kg"] == pytest.approx(2.0)
        assert report["diversion_rate_pct"] == pytest.approx(50.0)
        assert report["resale_proceeds_cents"] == 0
        # Final fee basis for the completed recycle item: OTHER base 900 +
        # 2.0 kg at the LIGHT rate 120 cents/kg = 1140.
        assert report["recycling_fees_cents"] == 1140
        assert report["certificates_issued"] == 0
