"""Resource overlap regimes: scanner half-open occupancy, shelf aggregate."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_client_with_agreement, create_batch, create_box, create_document,
    create_scanner_unit, create_shelf_slot, shelve_box,
    batch_in_scanning, open_session_with_logs, commit_session, get_batch_version,
    get_shelf_slot, get_box,
    make_intake_clerk_headers, make_prep_technician_headers,
    make_scan_operator_headers, make_platform_admin_headers,
    CLERK, PREP, SCAN, ADMIN,
)


# ---------------------------------------------------------------------------
# Queue A — Difficulty / resource_temporal_overlap
# ---------------------------------------------------------------------------

class TestScannerOccupancyHalfOpenInterval:
    """Two tests for Difficulty instance `scanner_occupancy_half_open_interval`."""

    def _setup_two_batches(self):
        client, _ = create_client_with_agreement(
            name="Occ Co", hipaa_covered=False,
            price_tier="STANDARD", rush_multiplier=1.75,
            storage_free_days=10, storage_daily_rate_cents=55,
            retention_days=30, max_boxes_per_batch=5,
        )
        scanner = create_scanner_unit(scanner_code="SCN-1", capacity=500)
        # Batch B1 in SCANNING with a 50-page doc
        ctx1 = batch_in_scanning(
            [{"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        # Batch B2 in SCANNING with a 50-page doc
        ctx2 = batch_in_scanning(
            [{"doc_type": "OTHER", "pages": 50, "ocr_confidence": 95}],
            client_id=client["id"],
        )
        # Session A OPEN on B1 occupying the scanner
        session_a = open_session_with_logs(ctx1, [(ctx1["documents"][0]["id"], 50)], scanner_id=scanner["id"])
        return client, scanner, ctx1, ctx2, session_a

    def test_second_open_on_occupied_scanner_rejected(self, api):
        """PRD §3.3: "a scanner already occupied by an `OPEN` session on any
        batch rejects a second open with `ERR_SCANNER_BUSY` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/scanner_occupancy_half_open_interval
        """
        _client, scanner, _ctx1, ctx2, _session_a = self._setup_two_batches()
        resp = api_client.create_scan_session(
            ctx2["batch"]["id"], {"scanner_id": scanner["id"]},
            make_scan_operator_headers(SCAN),
        )
        validate_error(resp, ApiErrorId.ERR_SCANNER_BUSY, expected_status=409)

    def test_after_commit_scanner_freed_for_adjacent_session(self, api):
        """PRD §3.3: "On commit the session moves to `COMMITTED` with
        `ended_at` stamped"

        Design: Difficulty/resource_temporal_overlap/scanner_occupancy_half_open_interval
        """
        _client, scanner, ctx1, ctx2, session_a = self._setup_two_batches()
        commit_session(session_a["id"], ctx1["batch"]["id"])
        # After commit (ended_at set), the scanner is free — adjacent session
        # is admitted.
        resp = api_client.create_scan_session(
            ctx2["batch"]["id"], {"scanner_id": scanner["id"]},
            make_scan_operator_headers(SCAN),
        )
        session_b = validate_success(resp, expected_status=201)
        assert session_b["status"] == "OPEN"


class TestShelfAggregateCapacityOverlapAndRelease:
    """Two tests for Difficulty instance
    `shelf_aggregate_capacity_overlap_and_release`."""

    def _setup(self):
        client, _ = create_client_with_agreement(
            name="Agg Co", hipaa_covered=False, max_boxes_per_batch=5,
        )
        slot = create_shelf_slot(shelf_code="SH-AGG", zone="GENERAL", capacity_grams=1000)
        batch = create_batch(client["id"])
        box_a = create_box(batch["id"], box_label="BX-A", intake_weight_grams=600)
        box_b = create_box(batch["id"], box_label="BX-B", intake_weight_grams=500)
        shelve_box(box_a["id"], slot["id"])
        return client, slot, box_a, box_b

    def test_aggregate_capacity_rejects_then_release_frees_slot(self, api):
        """PRD §3.2: "their live `occupied_weight_grams` is the sum of
        `intake_weight_grams` over that slot's `ACTIVE` assignments."

        Design: Difficulty/resource_temporal_overlap/shelf_aggregate_capacity_overlap_and_release
        """
        _client, slot, box_a, box_b = self._setup()
        # 600 + 500 > 1000 -> rejected
        resp = api_client.create_shelf_assignment(
            box_b["id"], {"shelf_slot_id": slot["id"]}, make_intake_clerk_headers(CLERK),
        )
        validate_error(resp, ApiErrorId.ERR_SHELF_OVER_CAPACITY, expected_status=409)
        # Pull box A out of storage via custody PREP; assignment releases.
        # The PREP hand-off must come from a different user than the STORAGE
        # link (auto-recorded by clerk-1 at shelve time). Use prep-1.
        get_success_data(api_client.create_custody_event(
            box_a["id"], {"to_stage": "PREP"}, make_prep_technician_headers(PREP),
        ))
        slot_mid = get_shelf_slot(slot["id"])
        assert slot_mid["occupied_weight_grams"] == 0
        # Retry placement of B — admitted.
        get_success_data(api_client.create_shelf_assignment(
            box_b["id"], {"shelf_slot_id": slot["id"]}, make_intake_clerk_headers(CLERK),
        ))
        slot_end = get_shelf_slot(slot["id"])
        assert slot_end["occupied_weight_grams"] == 500
        box_b_after = get_box(box_b["id"])
        assert box_b_after["status"] == "STORED"

    def test_release_debits_the_slot_by_box_weight(self, api):
        """PRD §3.3: "Pulling a box from storage for prep also releases its
        `ACTIVE` shelf assignment — `released_at` stamped from the clock and
        the box's weight debited from the slot."

        Design: Difficulty/resource_temporal_overlap/shelf_aggregate_capacity_overlap_and_release
        """
        _client, slot, box_a, _box_b = self._setup()
        # Sanity: occupancy is 600 before PREP.
        before = get_shelf_slot(slot["id"])
        assert before["occupied_weight_grams"] == 600
        get_success_data(api_client.create_custody_event(
            box_a["id"], {"to_stage": "PREP"}, make_prep_technician_headers(PREP),
        ))
        after = get_shelf_slot(slot["id"])
        assert after["occupied_weight_grams"] == 0


# ---------------------------------------------------------------------------
# Queue A — Difficulty / compensating_invariant
# ---------------------------------------------------------------------------

class TestShelfOccupancyConservationOccupyThenRelease:
    """Two tests for Difficulty instance
    `shelf_occupancy_conservation_occupy_then_release`."""

    def _setup(self):
        client, _ = create_client_with_agreement(
            name="Conserve Co", hipaa_covered=False,
        )
        slot = create_shelf_slot(shelf_code="SH-C", zone="GENERAL", capacity_grams=2000)
        batch = create_batch(client["id"])
        box = create_box(batch["id"], box_label="BX-A", intake_weight_grams=600)
        return client, slot, box

    def test_occupy_then_release_returns_gauge_to_zero(self, api):
        """PRD §3.2: "An assignment can also be released manually by an
        `IntakeClerk`, which flips it to `RELEASED`, stamps `released_at` from
        the clock, and debits the box weight back off the slot."

        Design: Difficulty/compensating_invariant/shelf_occupancy_conservation_occupy_then_release
        """
        _client, slot, box = self._setup()
        asg = shelve_box(box["id"], slot["id"])
        occ_1 = get_shelf_slot(slot["id"])["occupied_weight_grams"]
        assert occ_1 == 600
        get_success_data(api_client.release_shelf_assignment(asg["id"], make_intake_clerk_headers(CLERK)))
        occ_2 = get_shelf_slot(slot["id"])["occupied_weight_grams"]
        assert occ_2 == 0

    def test_release_flips_assignment_status_and_stamps_released_at(self, api):
        """PRD §3.2: "An assignment can also be released manually by an
        `IntakeClerk`, which flips it to `RELEASED`, stamps `released_at` from
        the clock, and debits the box weight back off the slot."

        Design: Difficulty/compensating_invariant/shelf_occupancy_conservation_occupy_then_release
        """
        _client, slot, box = self._setup()
        asg = shelve_box(box["id"], slot["id"])
        get_success_data(api_client.release_shelf_assignment(asg["id"], make_intake_clerk_headers(CLERK)))
        asg_after = get_success_data(api_client.get_shelf_assignment(asg["id"], make_intake_clerk_headers(CLERK)))
        assert asg_after["status"] == "RELEASED"
        assert asg_after["released_at"] is not None
