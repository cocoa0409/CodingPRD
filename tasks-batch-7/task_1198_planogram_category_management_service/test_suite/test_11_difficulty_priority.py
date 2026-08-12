"""Difficulty: priority_pair_validation_conflict — OCC beats invalid-state; SoD beats understock."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_category_payload,
    create_planogram_payload,
    create_product_payload,
    create_retailer_payload,
    create_supplier_payload,
    make_category_captain_headers,
    setup_category_with_listed_product,
    validate_error,
    validate_success,
)


class TestStaleVersionBeatsInvalidState:
    def test_stale_version_wins_over_invalid_state_on_discontinue(self, api, category_manager_headers):
        """PRD §2.8: "Fourth, on the four OCC-guarded writes the
        expected-version check runs, else `ERR_STALE_VERSION`. Fifth, the
        target entity must be in a state that permits the requested
        transition, else `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/occ_stale_version_beats_invalid_state_on_discontinue
        """
        # Walk product to DISCONTINUING then cancel-discontinuation → LISTED.
        # After cancel, product version has advanced. Now attempt discontinue
        # with a stale expected_product_version AND a state where another
        # transition may apply. To force both failures simultaneously we need
        # a state where the transition is invalid AND the version is stale.
        # Approach: take product CANDIDATE → LISTED → DISCONTINUING → cancel
        # → LISTED. Then DELISTED is reachable only via clock. To get a state
        # that rejects /discontinue on state grounds AND lets us hold a stale
        # version, we re-list after cancel (LISTED is valid for discontinue),
        # so instead we use the DELISTED path: advance clock to DELISTED, then
        # call /discontinue with a stale expected_product_version. DELISTED
        # cannot be discontinued (state) AND the version is stale.
        retailer, category, supplier, product = setup_category_with_listed_product(
            product_overrides={"weekly_demand_units": 50}
        )
        rid, pid = retailer["id"], product["id"]
        pv = validate_success(api.get_product(rid, pid, category_manager_headers))["version"]
        validate_success(
            api.discontinue_product(
                rid, pid,
                {"discontinuation_effective_date": "2026-06-01T00:00:00Z", "expected_product_version": pv},
                category_manager_headers,
            )
        )
        # Move clock past effective date → DELISTED
        validate_success(
            api.set_current_utc(
                rid, {"to_iso8601": "2026-06-02T00:00:00Z"}, TEST_USERS["platform_admin_headers"]
            )
        )
        # Stale version (pv from before discontinue; multiple mutations since)
        resp = api.discontinue_product(
            rid, pid,
            {"discontinuation_effective_date": "2027-01-01T00:00:00Z", "expected_product_version": pv},
            category_manager_headers,
        )
        # Per PRD §2.8 gauntlet, ERR_STALE_VERSION (priority 4) preempts
        # ERR_INVALID_STATE (priority 5).
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_version_wins_over_invalid_state_on_discontinue_relist(self, api, category_manager_headers):
        """PRD §2.8: "Fourth, on the four OCC-guarded writes the
        expected-version check runs, else `ERR_STALE_VERSION`. Fifth, the
        target entity must be in a state that permits the requested
        transition, else `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/occ_stale_version_beats_invalid_state_on_discontinue
        """
        # Second variant: product in CANDIDATE state after relist — discontinue
        # is invalid from CANDIDATE AND the caller's version is stale.
        retailer, category, supplier, product = setup_category_with_listed_product(
            product_overrides={"weekly_demand_units": 50}
        )
        rid, pid = retailer["id"], product["id"]
        pv_listed = validate_success(api.get_product(rid, pid, category_manager_headers))["version"]
        validate_success(
            api.discontinue_product(
                rid, pid,
                {"discontinuation_effective_date": "2026-06-01T00:00:00Z", "expected_product_version": pv_listed},
                category_manager_headers,
            )
        )
        validate_success(
            api.set_current_utc(
                rid, {"to_iso8601": "2026-06-02T00:00:00Z"}, TEST_USERS["platform_admin_headers"]
            )
        )
        # Now DELISTED → relist → CANDIDATE
        validate_success(api.relist_product(rid, pid, category_manager_headers))
        # CANDIDATE state: discontinue is invalid. Stale version also fails.
        resp = api.discontinue_product(
            rid, pid,
            {"discontinuation_effective_date": "2027-01-01T00:00:00Z", "expected_product_version": pv_listed},
            category_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestSelfApprovalBeatsUnderstock:
    def _build_understock_in_review(self, api):
        """Planogram in IN_REVIEW submitted by captain with X-User-ID=sid, with
        an UNDERSTOCK line. Returns (rid, cid, pgid, sid)."""
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), TEST_USERS["platform_admin_headers"]),
            expected_status=201,
        )
        rid = retailer["id"]
        cat = validate_success(
            api.create_category(
                rid,
                create_category_payload(code="C", role="ROUTINE", annual_sales_cents=100_000, total_linear_feet=10),
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        cid = cat["id"]
        supplier = validate_success(
            api.create_supplier(rid, create_supplier_payload(name="S"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        sid = supplier["id"]
        # weekly_demand=700 → daily=100. capacity=7 → dos=0.07 → UNDERSTOCK.
        prod = validate_success(
            api.create_product(
                rid,
                create_product_payload(cid, sid, sku="P1", width_in=6, unit_cost_cents=100, weekly_demand_units=700),
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        validate_success(api.list_product_cut_in(rid, prod["id"], TEST_USERS["category_manager_headers"]))
        pg = validate_success(
            api.create_planogram(rid, cid, create_planogram_payload(name="PG", variant="BASE"), TEST_USERS["category_manager_headers"]),
            expected_status=201,
        )
        pgid = pg["id"]
        validate_success(
            api.create_planogram_line(
                rid, cid, pgid,
                {"product_id": prod["id"], "position_index": 1, "facings": 1, "capacity_units": 7},
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        captain_headers = make_category_captain_headers(sid)
        validate_success(api.submit_planogram(rid, cid, pgid, captain_headers))
        return rid, cid, pgid, sid

    def test_self_approval_error_wins_over_understock(self, api):
        """PRD §2.8: "Only then are the endpoint's business rules evaluated, in
        the relative order each §3 workflow states — so on planogram approval,
        for instance, the segregation-of-duties screen is evaluated before the
        understock screen, and a request failing both reports the
        self-approval error."

        Design: Difficulty/priority_pair_validation_conflict/self_approval_beats_understock_check_on_planogram_approve
        """
        rid, cid, pgid, sid = self._build_understock_in_review(api)
        # Approve with X-User-ID equal to the submitting captain's supplier id.
        # Both segregation-of-duties AND understock would fail; SoD (priority 6) wins.
        from prd_bench_local_runner.testing import build_user_headers
        manager_same_id_headers = build_user_headers(sid, "CategoryManager")
        resp = api.approve_planogram(rid, cid, pgid, manager_same_id_headers)
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)

    def test_self_approval_error_independent_of_understock(self, api):
        """PRD §3.5: "if the approving manager's `X-User-ID` equals the
        recorded `submitted_by_captain_supplier_id`, the approval is rejected
        with `ERR_SELF_APPROVAL_FORBIDDEN` — the same person may not wear both
        the captain and manager hats for one planogram."

        Design: Difficulty/priority_pair_validation_conflict/self_approval_beats_understock_check_on_planogram_approve
        """
        # Build a planogram WITHOUT understock (healthy line) — only SoD fails.
        retailer = validate_success(
            api.create_retailer(create_retailer_payload(name="R"), TEST_USERS["platform_admin_headers"]),
            expected_status=201,
        )
        rid = retailer["id"]
        cat = validate_success(
            api.create_category(
                rid,
                create_category_payload(code="C", role="ROUTINE", annual_sales_cents=100_000, total_linear_feet=10),
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        cid = cat["id"]
        supplier = validate_success(
            api.create_supplier(rid, create_supplier_payload(name="S"), TEST_USERS["retailer_admin_headers"]),
            expected_status=201,
        )
        sid = supplier["id"]
        # weekly=70 → daily=10. capacity=50 → dos=5 → OK.
        prod = validate_success(
            api.create_product(
                rid,
                create_product_payload(cid, sid, sku="P1", width_in=6, unit_cost_cents=100, weekly_demand_units=70),
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        validate_success(api.list_product_cut_in(rid, prod["id"], TEST_USERS["category_manager_headers"]))
        pg = validate_success(
            api.create_planogram(rid, cid, create_planogram_payload(name="PG", variant="BASE"), TEST_USERS["category_manager_headers"]),
            expected_status=201,
        )
        pgid = pg["id"]
        validate_success(
            api.create_planogram_line(
                rid, cid, pgid,
                {"product_id": prod["id"], "position_index": 1, "facings": 5, "capacity_units": 50},
                TEST_USERS["category_manager_headers"],
            ),
            expected_status=201,
        )
        captain_headers = make_category_captain_headers(sid)
        validate_success(api.submit_planogram(rid, cid, pgid, captain_headers))
        # Approve as a manager whose X-User-ID collides with the captain's supplier id
        from prd_bench_local_runner.testing import build_user_headers
        resp = api.approve_planogram(rid, cid, pgid, build_user_headers(sid, "CategoryManager"))
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
