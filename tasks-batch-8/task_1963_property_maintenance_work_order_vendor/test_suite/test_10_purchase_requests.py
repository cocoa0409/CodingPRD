"""Purchase requests: pricing formula, auto-approval threshold, OCC guard,
supersede, receipt posting, and the completion block on open requests."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    complete_payload,
    create_part,
    create_purchase_request,
    current_work_order_version,
    get_part,
    get_purchase_request,
    get_work_order,
    make_technician_headers,
    setup_assigned_work_order,
    setup_in_progress_work_order,
    setup_signed_off_work_order,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]


def _pr_context(api, property_name, unit, **policy):
    """In-progress in-house work order plus a stocked part; returns the ids and headers
    a technician needs to raise purchase requests."""
    bundle = setup_in_progress_work_order(property_name, unit_number=unit, **policy)
    part = create_part(bundle["property"]["id"], sku="VLV-1", name="Valve",
                       unit_cost_cents=12000, reorder_level=0, initial_stock=0)
    tech_headers = make_technician_headers(bundle["technician"]["id"])
    return bundle, part, tech_headers


class TestPurchaseTotalFormula:
    def test_handling_fee_branch_and_auto_approval(self, api):
        """PRD §3.7: "`items_subtotal_cents` is the quantity times the quoted unit cost. `handling_fee_cents` is zero when the quantity is at least 10; below that bulk threshold it is the items subtotal multiplied by eight percent, rounded half-up to the nearest cent. `estimated_total_cents` is the sum of the items subtotal, the shipping fee, and the handling fee."
        PRD §3.7: "The total drives the approval routing: when `estimated_total_cents` is at or under the property's `purchase_auto_approve_threshold_cents` — equality approves — the request is born `APPROVED` with `auto_approved` set to true; otherwise it is born `PENDING` with `auto_approved` false and waits for a manager."

        Design: Difficulty/combinatorial_formula/purchase_total_handling_branch_and_threshold
        """
        bundle, part, tech = _pr_context(api, "PR Property", "103")
        wo_id = bundle["work_order"]["id"]
        pr = create_purchase_request(
            wo_id, part["id"], quantity=3, quoted_unit_cost_cents=12000,
            shipping_fee_cents=2000,
            expected_work_order_version=current_work_order_version(wo_id),
            caller_headers=tech,
        )
        assert pr["items_subtotal_cents"] == 36000, "3 * 12000"
        assert pr["handling_fee_cents"] == 2880, "round_half_up(36000 * 0.08)"
        assert pr["estimated_total_cents"] == 40880
        # Default threshold 50000: 40880 is at or under it.
        assert pr["status"] == "APPROVED"
        assert pr["auto_approved"] is True

    def test_bulk_quantity_exempts_handling_and_goes_pending(self, api):
        """PRD §3.7: "`handling_fee_cents` is zero when the quantity is at least 10; below that bulk threshold it is the items subtotal multiplied by eight percent, rounded half-up to the nearest cent."
        PRD §3.7: "The total drives the approval routing: when `estimated_total_cents` is at or under the property's `purchase_auto_approve_threshold_cents` — equality approves — the request is born `APPROVED` with `auto_approved` set to true; otherwise it is born `PENDING` with `auto_approved` false and waits for a manager."

        Design: Difficulty/combinatorial_formula/purchase_total_handling_branch_and_threshold
        """
        bundle, part, tech = _pr_context(api, "PR Property", "103")
        wo_id = bundle["work_order"]["id"]
        pr = create_purchase_request(
            wo_id, part["id"], quantity=12, quoted_unit_cost_cents=12000,
            shipping_fee_cents=0,
            expected_work_order_version=current_work_order_version(wo_id),
            caller_headers=tech,
        )
        assert pr["items_subtotal_cents"] == 144000, "12 * 12000"
        assert pr["handling_fee_cents"] == 0, "quantity 12 >= 10 exempts the handling fee"
        assert pr["estimated_total_cents"] == 144000
        # 144000 exceeds the default 50000 threshold.
        assert pr["status"] == "PENDING"
        assert pr["auto_approved"] is False


class TestThresholdBoundary:
    def test_total_equal_to_threshold_auto_approves(self, api):
        """PRD §3.7: "The total drives the approval routing: when `estimated_total_cents` is at or under the property's `purchase_auto_approve_threshold_cents` — equality approves — the request is born `APPROVED` with `auto_approved` set to true; otherwise it is born `PENDING` with `auto_approved` false and waits for a manager."

        Design: Difficulty/boundary_precision_check/purchase_threshold_exact_boundary
        """
        bundle, part, tech = _pr_context(
            api, "Threshold Property", "111", purchase_auto_approve_threshold_cents=40880
        )
        wo_id = bundle["work_order"]["id"]
        pr = create_purchase_request(
            wo_id, part["id"], quantity=3, quoted_unit_cost_cents=12000,
            shipping_fee_cents=2000,
            expected_work_order_version=current_work_order_version(wo_id),
            caller_headers=tech,
        )
        assert pr["estimated_total_cents"] == 40880, "36000 + 2000 + 2880 == threshold"
        assert pr["status"] == "APPROVED", "equality approves"
        assert pr["auto_approved"] is True

    def test_total_one_cent_over_threshold_goes_pending(self, api):
        """PRD §3.7: "The total drives the approval routing: when `estimated_total_cents` is at or under the property's `purchase_auto_approve_threshold_cents` — equality approves — the request is born `APPROVED` with `auto_approved` set to true; otherwise it is born `PENDING` with `auto_approved` false and waits for a manager."

        Design: Difficulty/boundary_precision_check/purchase_threshold_exact_boundary
        """
        bundle, part, tech = _pr_context(
            api, "Threshold Property", "111", purchase_auto_approve_threshold_cents=40880
        )
        wo_id = bundle["work_order"]["id"]
        pr = create_purchase_request(
            wo_id, part["id"], quantity=3, quoted_unit_cost_cents=12000,
            shipping_fee_cents=2001,
            expected_work_order_version=current_work_order_version(wo_id),
            caller_headers=tech,
        )
        assert pr["estimated_total_cents"] == 40881, "threshold + 1 cent"
        assert pr["status"] == "PENDING"
        assert pr["auto_approved"] is False


class TestPurchaseCreateOCC:
    def test_purchase_create_with_stale_version_returns_412(self, api):
        """PRD §3.7: "This is the second OCC-guarded write: the payload must carry `expected_work_order_version` equal to the work order's current `version`, or the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.7: "Creating the request increments the work order's `version` by one."

        Design: Corner/complexity_layers/purchase_create_with_stale_version_returns_412
        """
        bundle = setup_assigned_work_order("Occ2 Property", unit_number="702")
        part = create_part(bundle["property"]["id"], sku="SEAL-1", name="Seal",
                           unit_cost_cents=100, reorder_level=0, initial_stock=0)
        tech = make_technician_headers(bundle["technician"]["id"])
        wo_id = bundle["work_order"]["id"]
        observed_version = bundle["work_order"]["version"]  # 2 after dispatch
        pr1 = create_purchase_request(
            wo_id, part["id"], quantity=1, quoted_unit_cost_cents=100,
            shipping_fee_cents=0, expected_work_order_version=observed_version,
            caller_headers=tech,
        )
        assert get_work_order(wo_id)["version"] == 3, "creation bumped the work order version"

        resp = api.create_purchase_request(
            wo_id,
            {
                "part_id": part["id"], "quantity": 2, "quoted_unit_cost_cents": 100,
                "shipping_fee_cents": 0,
                "expected_work_order_version": observed_version,
            },
            tech,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        pr1_after = get_purchase_request(pr1["id"])
        assert pr1_after["status"] == "APPROVED", (
            "the rejected create must not supersede the earlier request"
        )


class TestSupersede:
    def test_new_request_supersedes_prior_pending(self, api):
        """PRD §3.7: "Creation also enforces one active negotiation per part per work order: any earlier purchase request still `PENDING` for the same work order and part is moved to `SUPERSEDED` in the same transaction."

        Design: Corner/state_machines/purchase_request_supersede_marks_old_pending
        """
        bundle = setup_assigned_work_order("Supersede Property", unit_number="210")
        part = create_part(bundle["property"]["id"], sku="PMP-2", name="Pump",
                           unit_cost_cents=30000, reorder_level=0, initial_stock=0)
        tech = make_technician_headers(bundle["technician"]["id"])
        wo_id = bundle["work_order"]["id"]
        # First request is over the default threshold: born PENDING.
        pr1 = create_purchase_request(
            wo_id, part["id"], quantity=2, quoted_unit_cost_cents=30000,
            shipping_fee_cents=0,
            expected_work_order_version=current_work_order_version(wo_id),
            caller_headers=tech,
        )
        assert pr1["status"] == "PENDING", "64800 > 50000 waits for a manager"
        pr2 = create_purchase_request(
            wo_id, part["id"], quantity=1, quoted_unit_cost_cents=31000,
            shipping_fee_cents=0,
            expected_work_order_version=current_work_order_version(wo_id),
            caller_headers=tech,
        )
        assert pr2["items_subtotal_cents"] == 31000
        assert pr2["handling_fee_cents"] == 2480, "round_half_up(31000 * 0.08)"
        assert pr2["estimated_total_cents"] == 33480
        # 33480 is at or under the default 50000 threshold, so the newer request
        # is born APPROVED (per the PRD auto-approval rule); the supersede effect
        # under test is on the older PENDING request.
        assert pr2["status"] == "APPROVED"
        assert pr2["auto_approved"] is True
        pr1_after = get_purchase_request(pr1["id"])
        assert pr1_after["status"] == "SUPERSEDED"


class TestReceive:
    def test_receive_posts_stock_to_part(self, api):
        """PRD §3.7: "Receiving an `APPROVED` request moves it to `RECEIVED` and posts the stock: the part's `quantity_on_hand` rises by the purchased quantity and its `restock_status` is recomputed — this is the receipt event that can lift a depleted part back to `IN_STOCK`."

        Design: Corner/endpoints/receive_increments_part_stock
        """
        bundle = setup_assigned_work_order("Recv Property", unit_number="503")
        part = create_part(bundle["property"]["id"], sku="WSH-1", name="Washer",
                           unit_cost_cents=100, reorder_level=0, initial_stock=0)
        tech = make_technician_headers(bundle["technician"]["id"])
        wo_id = bundle["work_order"]["id"]
        pr = create_purchase_request(
            wo_id, part["id"], quantity=5, quoted_unit_cost_cents=100,
            shipping_fee_cents=0,
            expected_work_order_version=current_work_order_version(wo_id),
            caller_headers=tech,
        )
        # 500 subtotal + 40 handling = 540 <= 50000: born APPROVED.
        assert pr["status"] == "APPROVED"
        data = validate_success(
            api.purchase_request_event(pr["id"], {"event_type": "RECEIVE"}, MANAGER), 200
        )
        assert data["status"] == "RECEIVED"
        assert get_part(part["id"])["quantity_on_hand"] == 5


class TestCompletionBlockedByOpenPurchaseRequest:
    def _setup_pending_request(self, api):
        bundle = setup_signed_off_work_order(property_name="Block Property",
                                             unit_number="114")
        part = create_part(bundle["property"]["id"], sku="PMP-1", name="Pump",
                           unit_cost_cents=30000, reorder_level=0, initial_stock=0)
        tech = make_technician_headers(bundle["technician"]["id"])
        wo_id = bundle["work_order"]["id"]
        pr = create_purchase_request(
            wo_id, part["id"], quantity=2, quoted_unit_cost_cents=30000,
            shipping_fee_cents=0,
            expected_work_order_version=current_work_order_version(wo_id),
            caller_headers=tech,
        )
        # 60000 subtotal + 4800 handling = 64800 > 50000: PENDING.
        assert pr["status"] == "PENDING"
        return bundle, pr, tech

    def test_pending_purchase_request_blocks_completion(self, api):
        """PRD §3.4: "Every purchase request raised against this work order must already be in `RECEIVED`, `REJECTED`, or `SUPERSEDED` status — a `PENDING` or `APPROVED` purchase request blocks completion with `ERR_OPEN_PURCHASE_REQUESTS` (HTTP 409), because stock cannot be written off while procurement is still in flight."

        Design: Difficulty/cross_entity_state_dependency/completion_blocked_by_open_purchase_request
        """
        bundle, pr, tech = self._setup_pending_request(api)
        wo_id = bundle["work_order"]["id"]
        resp = api.complete_work_order(
            wo_id, complete_payload(photo_urls=["https://x/g1.jpg"]), tech
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_PURCHASE_REQUESTS)

        # Receiving moves the request to a non-blocking status and unblocks completion.
        validate_success(
            api.purchase_request_event(pr["id"], {"event_type": "APPROVE"}, MANAGER), 200
        )
        received = validate_success(
            api.purchase_request_event(pr["id"], {"event_type": "RECEIVE"}, MANAGER), 200
        )
        assert received["status"] == "RECEIVED"
        done = validate_success(
            api.complete_work_order(
                wo_id, complete_payload(photo_urls=["https://x/g1.jpg"]), tech
            ),
            200,
        )
        assert done["status"] == "COMPLETED"

    def test_approved_purchase_request_still_blocks_until_received(self, api):
        """PRD §3.7: "Note the asymmetry the completion rule relies on: a `REJECTED` or `SUPERSEDED` request never blocks completion, but an `APPROVED` one does until it is received."

        Design: Difficulty/cross_entity_state_dependency/completion_blocked_by_open_purchase_request
        """
        bundle, pr, tech = self._setup_pending_request(api)
        wo_id = bundle["work_order"]["id"]
        validate_success(
            api.purchase_request_event(pr["id"], {"event_type": "APPROVE"}, MANAGER), 200
        )
        resp = api.complete_work_order(
            wo_id, complete_payload(photo_urls=["https://x/g1.jpg"]), tech
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_PURCHASE_REQUESTS)
        assert get_work_order(wo_id)["status"] == "IN_PROGRESS"

        validate_success(
            api.purchase_request_event(pr["id"], {"event_type": "RECEIVE"}, MANAGER), 200
        )
        done = validate_success(
            api.complete_work_order(
                wo_id, complete_payload(photo_urls=["https://x/g1.jpg"]), tech
            ),
            200,
        )
        assert done["status"] == "COMPLETED"
