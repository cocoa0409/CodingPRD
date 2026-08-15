"""Ply books: creation defaults, OCC edits, approval supersede cascade, pinning."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_ply_book,
    create_mold,
    create_ply_book_payload,
    create_work_order_payload,
    validate_error,
    validate_success,
)


class TestPlyBookCreation:
    def test_ply_book_created_with_defaults_and_draft_status(self, api, tooling_engineer_headers):
        """PRD §3.3: "Two policy knobs default sensibly: `tolerance_pct`, the
        production weight-acceptance tolerance, defaults to 0.05 and must be strictly
        positive and no greater than 0.5, and `max_repair_attempts`, the ceiling on
        repair cycles per work order, defaults to 2 and may be 0."
        PRD §3.3: "Engineering intent enters the system as a **PlyBook**, created by
        a `ToolingEngineer` in `DRAFT` status."

        Design: Corner/entities/ply_book_created_with_defaults_and_draft_status
        """
        book = validate_success(
            api.create_ply_book(create_ply_book_payload(), tooling_engineer_headers), 201
        )
        assert_ply_book(book)
        assert book["status"] == "DRAFT"
        assert book["tolerance_pct"] == pytest.approx(0.05)
        assert book["max_repair_attempts"] == 2
        assert isinstance(book["version"], int)


class TestPlyBookEdit:
    def test_plybook_patch_after_approve_rejected(self, api, tooling_engineer_headers):
        """PRD §3.3: "any edit or approval attempted on a book no longer in `DRAFT`
        is refused with `ERR_PLY_BOOK_NOT_DRAFT`." The supplied version matches the
        current one, so the OCC check passes and the state guard is what fires.

        Design: Corner/state_machines/plybook_patch_after_approve_rejected
        """
        book = validate_success(
            api.create_ply_book(create_ply_book_payload(), tooling_engineer_headers), 201
        )
        approved = validate_success(
            api.approve_ply_book(book["id"], tooling_engineer_headers), 200
        )
        res = api.patch_ply_book(
            book["id"],
            {"expected_ply_book_version": approved["version"], "tolerance_pct": 0.06},
            tooling_engineer_headers,
        )
        validate_error(res, ApiErrorId.ERR_PLY_BOOK_NOT_DRAFT, expected_status=409)


class TestApproveSupersede:
    def test_plybook_approve_supersedes_previous_revision(self, api, tooling_engineer_headers):
        """PRD §3.3: "Approving a draft moves it to `APPROVED` and simultaneously
        supersedes any previously `APPROVED` book of the same `part_number`, pushing
        that older revision to the terminal `SUPERSEDED` state."

        Design: Corner/state_machines/plybook_approve_supersedes_previous_revision
        """
        rev_a = validate_success(
            api.create_ply_book(
                create_ply_book_payload(revision="A"), tooling_engineer_headers
            ),
            201,
        )
        validate_success(api.approve_ply_book(rev_a["id"], tooling_engineer_headers), 200)
        rev_b = validate_success(
            api.create_ply_book(
                create_ply_book_payload(revision="B"), tooling_engineer_headers
            ),
            201,
        )
        approved_b = validate_success(
            api.approve_ply_book(rev_b["id"], tooling_engineer_headers), 200
        )
        assert approved_b["status"] == "APPROVED"
        rev_a_after = validate_success(
            api.get_ply_book(rev_a["id"], tooling_engineer_headers), 200
        )
        assert rev_a_after["status"] == "SUPERSEDED"


class TestOccPlyBook:
    def test_occ_patch_with_fresh_version_succeeds(self, api, tooling_engineer_headers):
        """PRD §2.7: "A `PATCH /ply-books/{id}` request must carry
        `expected_ply_book_version` equal to the ply book's current `version`".
        PRD §2.4: "`version` (integer): a system-managed counter that increments by
        one on every mutation".

        Design: Corner/complexity_layers/occ_plybook_patch_stale_version_rejected
        """
        book = validate_success(
            api.create_ply_book(create_ply_book_payload(), tooling_engineer_headers), 201
        )
        patched = validate_success(
            api.patch_ply_book(
                book["id"],
                {"expected_ply_book_version": book["version"], "tolerance_pct": 0.06},
                tooling_engineer_headers,
            ),
            200,
        )
        assert patched["version"] == book["version"] + 1
        assert patched["tolerance_pct"] == pytest.approx(0.06)

    def test_occ_plybook_patch_stale_version_rejected(self, api, tooling_engineer_headers):
        """PRD §2.7: "If the supplied value does not match the resource's current
        `version` — because another writer has advanced the resource since the client
        last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
        and no change is applied." A draft stays a draft across edits, so only the
        version check reveals the stale base.

        Design: Corner/complexity_layers/occ_plybook_patch_stale_version_rejected
        """
        book = validate_success(
            api.create_ply_book(create_ply_book_payload(), tooling_engineer_headers), 201
        )
        stale_version = book["version"]
        validate_success(
            api.patch_ply_book(
                book["id"],
                {"expected_ply_book_version": stale_version, "tolerance_pct": 0.06},
                tooling_engineer_headers,
            ),
            200,
        )
        res = api.patch_ply_book(
            book["id"],
            {"expected_ply_book_version": stale_version, "tolerance_pct": 0.07},
            tooling_engineer_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestPinnedVersion:
    def test_pinned_ply_book_version_held_after_supersede(self, api, tooling_engineer_headers, shop_manager_headers):
        """PRD §3.3: "Work orders already released against the older revision are
        unaffected: each work order captures the book's `version` at its own creation
        into `pinned_ply_book_version` and builds to that pinned revision forever
        after, while new releases must reference a book currently in `APPROVED` status."

        Design: Corner/complexity_layers/pinned_ply_book_version_held_after_supersede
        """
        mold = create_mold(mold_code="MOLD-VP1", tooling_phase="PRODUCTION")
        rev_a = validate_success(
            api.create_ply_book(create_ply_book_payload(revision="A"), tooling_engineer_headers),
            201,
        )
        approved_a = validate_success(
            api.approve_ply_book(rev_a["id"], tooling_engineer_headers), 200
        )
        order = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    mold["id"], rev_a["id"], work_order_no="WO-VP1"
                ),
                shop_manager_headers,
            ),
            201,
        )
        assert order["pinned_ply_book_version"] == approved_a["version"]
        assert order["target_part_weight_g"] == pytest.approx(2000.0)

        rev_b = validate_success(
            api.create_ply_book(
                create_ply_book_payload(
                    revision="B",
                    plies=[
                        {
                            "seq": 1,
                            "material_code": "CF-200",
                            "orientation_deg": 0,
                            "areal_weight_g_m2": 200,
                        }
                    ],
                ),
                tooling_engineer_headers,
            ),
            201,
        )
        validate_success(api.approve_ply_book(rev_b["id"], tooling_engineer_headers), 200)

        order_after = validate_success(
            api.get_work_order(order["id"], shop_manager_headers), 200
        )
        assert order_after["pinned_ply_book_version"] == approved_a["version"]
        assert order_after["ply_book_id"] == rev_a["id"]
        # No recomputation from revision B: the pinned revision's 2000.0 g stands.
        assert order_after["target_part_weight_g"] == pytest.approx(2000.0)
        rev_a_after = validate_success(
            api.get_ply_book(rev_a["id"], shop_manager_headers), 200
        )
        assert rev_a_after["status"] == "SUPERSEDED"
