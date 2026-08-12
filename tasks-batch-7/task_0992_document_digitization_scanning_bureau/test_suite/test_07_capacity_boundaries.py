"""Boundary precision tests for capacity ceilings (rush, shelf, max-boxes)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId,
    create_client_with_agreement, create_batch, create_box,
    create_shelf_slot, shelve_box,
    get_box, get_shelf_slot,
    make_intake_clerk_headers, make_platform_admin_headers,
    CLERK, ADMIN,
)


# ---------------------------------------------------------------------------
# Queue A — Difficulty / boundary_precision_check
# ---------------------------------------------------------------------------

class TestRushAdmissionBoundaryAtLimit:
    """Two tests for Difficulty instance `rush_admission_boundary_at_limit`."""

    def test_three_rush_admitted_fourth_rejected(self, api):
        """PRD §3.2: "when the requested priority is `RUSH`, an admission
        window is enforced: the bureau admits rush work only while the count
        of batches with `priority` `RUSH` sitting in `INTAKE`, `PREPPING`,
        `SCANNING`, `QA`, or `INDEXING` is strictly below the rush admission
        limit of 3. The request that brings that count to exactly 3 is the
        last one admitted; the next rush create is rejected with
        `ERR_RUSH_CAPACITY_FULL` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/rush_admission_boundary_at_limit
        """
        client, _ = create_client_with_agreement(name="Rush Bound", hipaa_covered=False)
        # Three RUSH admissions all succeed (count goes 0->1->2->3).
        for _ in range(3):
            resp = api_client.create_batch(
                {"client_id": client["id"], "priority": "RUSH"},
                make_intake_clerk_headers(CLERK),
            )
            validate_success(resp, expected_status=201)
        # Fourth RUSH rejected (count is now exactly 3).
        resp = api_client.create_batch(
            {"client_id": client["id"], "priority": "RUSH"},
            make_intake_clerk_headers(CLERK),
        )
        validate_error(resp, ApiErrorId.ERR_RUSH_CAPACITY_FULL, expected_status=409)

    def test_standard_never_counted_by_rush_window(self, api):
        """PRD §3.2: "`STANDARD` batches are never counted by this rule and
        never rejected by it."

        Design: Difficulty/boundary_precision_check/rush_admission_boundary_at_limit
        """
        client, _ = create_client_with_agreement(name="Rush Bound Std", hipaa_covered=False)
        for _ in range(3):
            validate_success(api_client.create_batch(
                {"client_id": client["id"], "priority": "RUSH"},
                make_intake_clerk_headers(CLERK),
            ), expected_status=201)
        # STANDARD batch still admitted while rush is at the limit.
        resp = api_client.create_batch(
            {"client_id": client["id"], "priority": "STANDARD"},
            make_intake_clerk_headers(CLERK),
        )
        validate_success(resp, expected_status=201)


class TestShelfCapacityEqualityAdmittedOverByOneRejected:
    """Two tests for Difficulty instance
    `shelf_capacity_equality_admitted_over_by_one_rejected`."""

    def _setup(self):
        client, _ = create_client_with_agreement(
            name="Shelf Bound", hipaa_covered=False, max_boxes_per_batch=5,
        )
        slot = create_shelf_slot(shelf_code="SH-EQ", zone="GENERAL", capacity_grams=1000)
        batch = create_batch(client["id"])
        box_a = create_box(batch["id"], box_label="BX-A", intake_weight_grams=400)
        box_b = create_box(batch["id"], box_label="BX-B", intake_weight_grams=600)
        box_c = create_box(batch["id"], box_label="BX-C", intake_weight_grams=1)
        return client, batch, slot, box_a, box_b, box_c

    def test_equality_admitted(self, api):
        """PRD §3.2: "A slot admits the box only when its remaining capacity —
        `capacity_grams` minus `occupied_weight_grams` — is at least the box's
        weight; equality is admitted, and only a placement that would strictly
        exceed capacity is rejected with `ERR_SHELF_OVER_CAPACITY` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/shelf_capacity_equality_admitted_over_by_one_rejected
        """
        _client, _batch, slot, box_a, box_b, _box_c = self._setup()
        shelve_box(box_a["id"], slot["id"])
        # 400 + 600 == 1000 -> admitted at exact equality.
        resp = api_client.create_shelf_assignment(
            box_b["id"], {"shelf_slot_id": slot["id"]}, make_intake_clerk_headers(CLERK),
        )
        validate_success(resp, expected_status=201)
        slot_after = get_shelf_slot(slot["id"])
        assert slot_after["occupied_weight_grams"] == 1000

    def test_one_gram_over_rejected(self, api):
        """PRD §3.2: "equality is admitted, and only a placement that would
        strictly exceed capacity is rejected with `ERR_SHELF_OVER_CAPACITY`
        (HTTP 409)."

        Design: Difficulty/boundary_precision_check/shelf_capacity_equality_admitted_over_by_one_rejected
        """
        _client, _batch, slot, box_a, box_b, box_c = self._setup()
        shelve_box(box_a["id"], slot["id"])
        shelve_box(box_b["id"], slot["id"])
        # 1000 + 1 > 1000 -> rejected.
        resp = api_client.create_shelf_assignment(
            box_c["id"], {"shelf_slot_id": slot["id"]}, make_intake_clerk_headers(CLERK),
        )
        validate_error(resp, ApiErrorId.ERR_SHELF_OVER_CAPACITY, expected_status=409)
        box_c_after = get_box(box_c["id"])
        assert box_c_after["status"] == "RECEIVED"


# ---------------------------------------------------------------------------
# Queue B — Corner / errors
# ---------------------------------------------------------------------------

class TestMaxBoxesExceeded:
    """Corner: error_max_boxes_exceeded."""

    def test_third_box_rejected_when_max_is_two(self, api):
        """PRD §3.2: "Intake respects the agreement's ceiling — a box that
        would push the batch past `max_boxes_per_batch` is rejected with
        `ERR_MAX_BOXES_EXCEEDED` (HTTP 409)."

        Design: Corner/errors/error_max_boxes_exceeded
        """
        client, _ = create_client_with_agreement(
            name="BoxCap Co", hipaa_covered=False, max_boxes_per_batch=2,
        )
        batch = create_batch(client["id"])
        create_box(batch["id"], box_label="BX-1", intake_weight_grams=100)
        create_box(batch["id"], box_label="BX-2", intake_weight_grams=100)
        resp = api_client.create_box(
            batch["id"], {"box_label": "BX-3", "intake_weight_grams": 100},
            make_intake_clerk_headers(CLERK),
        )
        validate_error(resp, ApiErrorId.ERR_MAX_BOXES_EXCEEDED, expected_status=409)
        # Still exactly 2 boxes.
        boxes, meta = validate_paginated(api_client.list_batch_boxes(batch["id"], make_intake_clerk_headers(CLERK)))
        assert meta["total_count"] == 2
