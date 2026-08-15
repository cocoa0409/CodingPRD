"""Panel-design revisions, quoting, customer decision, and optimistic concurrency."""

from test_helpers import (
    TEST_USERS,
    TWO_LINE_EQUIPMENT,
    ApiErrorId,
    create_panel_design,
    get_panel_design,
    get_work_order,
    make_customer_headers,
    setup_approved_work_order,
    setup_draft_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["shop_manager_headers"]


class TestRevisionSupersede:
    def test_new_revision_supersedes_prior_draft(self, api):
        """PRD §3.2: "Each new revision receives a `revision` number one greater than the count of revisions the work order already has, assigned in creation order starting from 1, and the server computes `total_added_weight_lb` as the sum over the equipment lines of each line's `quantity` times its `weight_lb`, kept to one decimal."
        PRD §3.2: "Creating a revision automatically supersedes every earlier revision of the same work order still sitting in `DRAFT`, `SUBMITTED`, or `CHANGES_REQUESTED` — those move to `SUPERSEDED` — and advances the work order's `version`."

        Design: Corner/entities/panel_design_create_supersedes_prior_draft
        """
        bundle = setup_draft_work_order(customer_name="Sup Sue",
                                        customer_email="s@x.com",
                                        layout_notes="rev1")
        work_order = bundle["work_order"]
        first = bundle["design"]
        assert first["revision"] == 1

        refreshed = get_work_order(work_order["id"])
        second = create_panel_design(refreshed, layout_notes="rev2")
        assert second["revision"] == 2, (
            f"second revision must be numbered 2, got {second['revision']}")
        assert second["status"] == "DRAFT"
        assert get_panel_design(first["id"])["status"] == "SUPERSEDED", (
            "the earlier DRAFT revision is superseded by the new one")
        reread = get_work_order(work_order["id"])
        assert reread["version"] == work_order["version"] + 1, (
            "each newly authored panel-design revision advances the work order's "
            f"version by one: started at {work_order['version']}, "
            f"now {reread['version']}")


class TestStaleVersionGuard:
    def test_stale_expected_version_rejected(self, api):
        """PRD §2.8: "If the work order's current `version` has advanced past that value since the client read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the work order before authoring the next revision."

        Design: Corner/cross_cutting_layers/panel_design_create_stale_version_returns_412
        """
        bundle = setup_draft_work_order(customer_name="Occ Oscar",
                                        customer_email="o3@x.com",
                                        with_design=False)
        work_order = bundle["work_order"]
        first = create_panel_design(work_order, layout_notes="rev1")
        before = get_work_order(work_order["id"])
        assert before["version"] > work_order["version"], (
            "the first revision advanced the work-order version")

        response = api.create_panel_design(
            {
                "work_order_id": work_order["id"],
                "expected_work_order_version": work_order["version"],
                "layout_notes": "stale rev2",
                "equipment_list": [],
            },
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_STALE_VERSION)
        assert get_panel_design(first["id"])["status"] == "DRAFT", (
            "the rejected create supersedes nothing")
        assert get_work_order(work_order["id"])["version"] == before["version"], (
            "the rejected create leaves the work-order version unchanged")


class TestSubmitQuoteGate:
    def test_submit_quote_without_design_rejected(self, api):
        """PRD §3.2: "The quote requires at least one design revision still in `DRAFT` or `SUBMITTED`; if every revision has been superseded or bounced back for changes, the attempt fails with `ERR_NO_PANEL_DESIGN`."

        Design: Corner/state_machines/submit_quote_without_design_rejected
        """
        bundle = setup_draft_work_order(customer_name="NoDesign Ned",
                                        customer_email="n@x.com",
                                        with_design=False)
        response = api.submit_quote(bundle["work_order"]["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_NO_PANEL_DESIGN)
        assert get_work_order(bundle["work_order"]["id"])["status"] == "DRAFT"


class TestDecideStateGates:
    def test_decide_on_draft_design_rejected(self, api):
        """PRD §3.2: "the owner records an `outcome` on a `SUBMITTED` design while the work order sits in `PENDING_APPROVAL` (`ERR_INVALID_STATE` in any other state)"

        Design: Corner/state_machines/decide_draft_design_rejected
        """
        bundle = setup_draft_work_order(customer_name="Draft Dee",
                                        customer_email="d@x.com")
        response = api.decide_panel_design(
            bundle["design"]["id"], "APPROVE",
            make_customer_headers(bundle["customer"]["id"]))
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert get_panel_design(bundle["design"]["id"])["status"] == "DRAFT"

    def test_decide_on_approved_design_rejected(self, api):
        """PRD §3.2: "the owner records an `outcome` on a `SUBMITTED` design while the work order sits in `PENDING_APPROVAL` (`ERR_INVALID_STATE` in any other state)"
        PRD §3.2: "An `APPROVED` design is terminal and is never superseded."

        Design: Corner/state_machines/decide_approved_design_rejected
        """
        bundle = setup_approved_work_order(customer_name="Term Tom",
                                           customer_email="t@x.com",
                                           equipment_list=[])
        response = api.decide_panel_design(
            bundle["design"]["id"], "REQUEST_CHANGES",
            make_customer_headers(bundle["customer"]["id"]))
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert get_panel_design(bundle["design"]["id"])["status"] == "APPROVED"


class TestQuoteTotals:
    def test_quote_total_individual_no_discount(self, api):
        """PRD §3.2: "Its labor component is the work order's `quoted_labor_hours` times the shop rate of 14,500 cents per hour, rounded half-up to whole cents."
        PRD §3.2: "Its equipment component sums each line's extended price — `quantity` times `unit_price_cents` — across the design, then applies a discount keyed to the owning customer's `customer_kind`: ten percent for `FLEET_OPERATOR`, five percent for `FLIGHT_SCHOOL`, and no discount for `INDIVIDUAL`."

        Design: Corner/calculations/quote_total_individual_literal
        """
        bundle = setup_draft_work_order(
            customer_name="Quote Quinn", customer_email="q@x.com",
            equipment_list=TWO_LINE_EQUIPMENT, layout_notes="two-line",
            work_order_overrides={"estimated_downtime_days": 20,
                                  "quoted_labor_hours": 40,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        quoted = validate_success(api.submit_quote(bundle["work_order"]["id"], MANAGER))
        # 40 h * 14500 = 580000 labor; equipment 1700000 + 900000 = 2600000 at 0%.
        assert quoted["quoted_total_cents"] == 3180000, (
            f"expected quoted_total_cents 3180000, got {quoted['quoted_total_cents']}")
        assert quoted["status"] == "PENDING_APPROVAL"

    def test_quote_total_fleet_operator_discount(self, api):
        """PRD §3.2: "Its equipment component sums each line's extended price — `quantity` times `unit_price_cents` — across the design, then applies a discount keyed to the owning customer's `customer_kind`: ten percent for `FLEET_OPERATOR`, five percent for `FLIGHT_SCHOOL`, and no discount for `INDIVIDUAL`."
        PRD §3.2: "The discounted equipment figure is rounded half-up to whole cents, and `quoted_total_cents` is the labor component plus that rounded figure."

        Design: Corner/calculations/quote_total_fleet_discount_literal
        """
        bundle = setup_draft_work_order(
            customer_name="Fleet Fred", customer_email="f@x.com",
            customer_kind="FLEET_OPERATOR",
            equipment_list=TWO_LINE_EQUIPMENT, layout_notes="two-line",
            work_order_overrides={"estimated_downtime_days": 20,
                                  "quoted_labor_hours": 40,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        quoted = validate_success(api.submit_quote(bundle["work_order"]["id"], MANAGER))
        # 580000 labor + round(2600000 * 0.90) = 580000 + 2340000 = 2920000.
        assert quoted["quoted_total_cents"] == 2920000, (
            f"expected quoted_total_cents 2920000, got {quoted['quoted_total_cents']}")


class TestZeroLineApproval:
    def test_empty_equipment_list_approval_lands_approved(self, api):
        """PRD §3.2: "When the approved design's `equipment_list` is empty, the work order advances from `PENDING_APPROVAL` to `APPROVED`."

        Design: Corner/state_machines/zero_line_approval_keeps_approved
        """
        bundle = setup_approved_work_order(customer_name="Zero Zelda",
                                           customer_email="z@x.com",
                                           equipment_list=[], layout_notes="wiring only")
        assert bundle["work_order"]["status"] == "APPROVED", (
            f"empty-list approval must land APPROVED, got "
            f"{bundle['work_order']['status']}")
        assert bundle["work_order"]["parts_pending_count"] == 0
        orders, meta = validate_paginated(
            api.list_equipment_orders(MANAGER,
                                      params={"work_order_id": bundle["work_order"]["id"]}))
        assert orders == [] and meta["total_count"] == 0, (
            "an empty equipment list releases no procurement orders")
