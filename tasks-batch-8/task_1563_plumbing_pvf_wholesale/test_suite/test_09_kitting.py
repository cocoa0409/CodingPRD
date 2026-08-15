"""Takeoff kitting and will-call bin staging (PRD §2.11, §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_kit_payload,
    create_kitted_order,
    create_stage_kit_payload,
    create_submitted_order,
    setup_branch_product_account,
    stage_kit,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["sales_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


class TestKitMembership:
    def test_kit_foreign_line_rejected(self, api, sales_headers):
        """PRD §3.8: "Every referenced line must belong to the order in the path
        (a foreign line is rejected with `ERR_LINE_ORDER_MISMATCH`)".

        Design: Corner/validations/kit_foreign_line_rejected
        """
        branch, product, account = setup_branch_product_account(stock=10)
        order1, _ = create_submitted_order(account["id"], branch["id"], [(product["id"], 1)])
        order2, line2 = create_submitted_order(account["id"], branch["id"], [(product["id"], 1)])

        res = api.create_kit(order1["id"], create_kit_payload([line2[0]]), sales_headers)
        validate_error(res, ApiErrorId.ERR_LINE_ORDER_MISMATCH)

    def test_kit_double_membership_rejected(self, api, sales_headers):
        """PRD §3.8: "must not already belong to another kit whose status is not
        `RELEASED` (double-kitting is rejected with `ERR_KIT_LINE_CONFLICT`)".

        Design: Corner/validations/kit_double_membership_rejected
        """
        branch, product, account = setup_branch_product_account(stock=5)
        order, line_ids = create_submitted_order(account["id"], branch["id"], [(product["id"], 1)])
        validate_success(api.create_kit(order["id"], create_kit_payload(line_ids), sales_headers), 201)

        res = api.create_kit(order["id"], create_kit_payload(line_ids, floor_label="F2"), sales_headers)
        validate_error(res, ApiErrorId.ERR_KIT_LINE_CONFLICT)


class TestStagingBinBuffer:
    def _setup_two_kits(self):
        """Will-call order with two allocated lines and one auto-assembled kit
        per line."""
        branch, product, account = setup_branch_product_account(stock=10)
        order, line_ids, kit_ids = create_kitted_order(
            account["id"], branch["id"], product["id"], num_lines=2
        )
        return branch, product, account, order, kit_ids

    def test_bin_occupied_through_two_hour_buffer(self, api, warehouse_headers):
        """PRD §2.11: "a kit occupying a `staging_bin` holds that bin through
        its `staged_window_end` plus a two-hour turnaround buffer; another kit
        staged into the same bin collides unless its window starts at or after
        that buffered hand-off — a gap of exactly two hours is allowed — and a
        colliding staging is rejected with `ERR_BIN_OVERLAP`."

        K1 holds B7 through 10:00 + 2h = 12:00; K2 at 11:00 collides.

        Design: Difficulty/resource_temporal_overlap/staging_bin_turnaround_buffer
        """
        _, _, _, _, kit_ids = self._setup_two_kits()
        stage_kit(kit_ids[0], bin_label="B7",
                  window_start="2026-08-02T08:00:00Z", window_end="2026-08-02T10:00:00Z")

        res = api.stage_kit(
            kit_ids[1],
            create_stage_kit_payload(staging_bin="B7", window_start="2026-08-02T11:00:00Z",
                                     window_end="2026-08-02T12:00:00Z"),
            warehouse_headers,
        )
        validate_error(res, ApiErrorId.ERR_BIN_OVERLAP)

    def test_bin_handoff_at_exactly_two_hours_allowed(self, api, warehouse_headers):
        """PRD §2.11: "another kit staged into the same bin collides unless its
        window starts at or after that buffered hand-off — a gap of exactly two
        hours is allowed".

        K2 starting exactly at 12:00 (= 10:00 + 2h buffer) stages successfully.

        Design: Difficulty/resource_temporal_overlap/staging_bin_turnaround_buffer
        """
        _, _, _, _, kit_ids = self._setup_two_kits()
        stage_kit(kit_ids[0], bin_label="B7",
                  window_start="2026-08-02T08:00:00Z", window_end="2026-08-02T10:00:00Z")

        staged = validate_success(api.stage_kit(
            kit_ids[1],
            create_stage_kit_payload(staging_bin="B7", window_start="2026-08-02T12:00:00Z",
                                     window_end="2026-08-02T13:00:00Z"),
            warehouse_headers,
        ))
        assert staged["status"] == "STAGED"
        assert staged["staging_bin"] == "B7"


class TestUnstageRework:
    def test_kit_unstage_rework_loop(self, api, warehouse_headers):
        """PRD §3.8: "Unstaging returns a `STAGED` kit to `ASSEMBLED`, clearing
        the bin assignment and window so the bin is freed."

        After unstage the kit reads ASSEMBLED with a null bin, and the same kit
        can stage into a different bin whose window overlaps the old one.

        Design: Corner/state_machines/kit_unstage_rework_loop
        """
        branch, product, account = setup_branch_product_account(stock=5)
        _, _, kit_ids = create_kitted_order(account["id"], branch["id"], product["id"])
        kit_id = kit_ids[0]
        stage_kit(kit_id, bin_label="B1",
                  window_start="2026-08-02T08:00:00Z", window_end="2026-08-02T10:00:00Z")

        unstaged = validate_success(api.unstage_kit(kit_id, warehouse_headers))
        assert unstaged["status"] == "ASSEMBLED"
        assert unstaged["staging_bin"] is None, "unstage must free the bin"

        restaged = validate_success(api.stage_kit(
            kit_id,
            create_stage_kit_payload(staging_bin="B2", window_start="2026-08-02T09:00:00Z",
                                     window_end="2026-08-02T11:00:00Z"),
            warehouse_headers,
        ))
        assert restaged["status"] == "STAGED"
        assert restaged["staging_bin"] == "B2"
