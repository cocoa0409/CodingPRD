"""Supply inventory, priority, allocation waterfall, dispatch — PRD §3.7."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    allocate_batch_payload,
    api_client,
    assert_supply_item,
    assert_supply_item_invariant,
    assert_supply_request,
    consume_payload,
    create_supply_item,
    create_supply_request_payload,
    dispatch_payload,
    drive_region_to_published_tier,
    make_hospital_reporter_headers,
    setup_district_with_hospital,
    setup_supply_for_allocate_batch,
    submit_supply_request,
    validate_error,
    validate_success,
)


# ===========================================================================
# SupplyItem registration — PRD §3.7
# ===========================================================================
class TestSupplyItem:

    def test_create_supply_item_defaults(self, api, supply_manager_headers):
        """PRD §3.7: "Each carries a unique sku, a category from PPE,
        TEST_KIT, MEDICATION, or VACCINE, a reserve_quantity of on-hand
        units, and an allocated_quantity reserved but not yet
        dispatched. Both quantities are integers."

        Claim: POST /epi/supply-items persists sku/category/reserve and
        defaults allocated_quantity to 0.
        """
        item = create_supply_item(
            sku="SKU-T1", category="PPE", reserve_quantity=50,
        )
        assert_supply_item(item)
        assert item["sku"] == "SKU-T1"
        assert item["category"] == "PPE"
        assert item["reserve_quantity"] == 50
        assert item["allocated_quantity"] == 0
        assert_supply_item_invariant(item)


# ===========================================================================
# SupplyRequest creation and priority — PRD §3.7
# ===========================================================================
class TestSupplyRequestPriority:

    def test_priority_score_low_tier_ppe(self, api, supply_manager_headers):
        """PRD §3.7: "On creation the server computes a priority_score
        as the sum of two weights — the tier weight read from the
        requesting institution's region (HIGH contributes 100, MEDIUM
        contributes 30, LOW contributes 0) and the category weight of
        the requested item (PPE contributes 5, TEST_KIT contributes 3,
        MEDICATION contributes 8, VACCINE contributes 6)."

        Claim: a PPE request from an institution in a LOW-tier region
        gets priority_score = 0 + 5 = 5.
        """
        item = create_supply_item(
            sku="SKU-P-LOW", category="PPE", reserve_quantity=100,
        )
        # District defaults to LOW (Region.current_risk_tier).
        _region, hospital = setup_district_with_hospital(
            district_code="D-PRI-1",
        )
        request = submit_supply_request(
            sku=item["sku"], hospital_id=hospital["id"],
            requested_quantity=10,
        )
        assert_supply_request(request)
        assert request["priority_score"] == 5, (
            f"LOW(0) + PPE(5) = 5; got priority_score={request['priority_score']}"
        )

    def test_priority_score_high_tier_medication(self, api,
                                                  supply_manager_headers,
                                                  supervisor_headers,
                                                  risk_expert_headers,
                                                  press_officer_headers):
        """PRD §3.7: "the tier weight read from the requesting
        institution's region (HIGH contributes 100, MEDIUM contributes
        30, LOW contributes 0) and the category weight of the
        requested item ... MEDICATION contributes 8."

        Claim: a MEDICATION request from an institution in a HIGH-tier
        region gets priority_score = 100 + 8 = 108.
        """
        region, hospital = setup_district_with_hospital(
            district_code="D-PRI-2",
        )
        drive_region_to_published_tier(region, "HIGH")
        item = create_supply_item(
            sku="SKU-M-HIGH", category="MEDICATION", reserve_quantity=100,
        )
        request = submit_supply_request(
            sku=item["sku"], hospital_id=hospital["id"],
            requested_quantity=5,
        )
        assert request["priority_score"] == 108, (
            f"HIGH(100) + MEDICATION(8) = 108; got "
            f"priority_score={request['priority_score']}"
        )


# ===========================================================================
# Allocate batch waterfall — PRD §3.7
# ===========================================================================
class TestAllocateBatchWaterfall:

    def test_high_tier_request_allocates_first_low_tier_gets_remainder(
        self, api, supply_manager_headers,
    ):
        """PRD §3.7: "the batch path is a strict waterfall: among all
        PENDING requests for the sku, sort by priority_score descending,
        then created_at ascending, then id ascending, and walk the
        sorted list. At each request allocate the smaller of the
        request's requested_quantity and the remaining available ...
        The last request in line that can only be partially satisfied
        receives the entire remaining available (it is not split across
        multiple requests); there is no proportional split, no
        fractional unit, and no redistribution of any remainder."

        Claim: with reserve=100, a HIGH-tier PPE request for 80 sorted
        first and a LOW-tier PPE request for 50 sorted second yields
        80 / 20 allocated quantities (no proportional split).
        # difficulty: combinatorial_formula/supply_allocation_rounding_order
        """
        ctx = setup_supply_for_allocate_batch(
            sku="PPE_MASK", category="PPE", reserve=100,
            high_request_qty=80, low_request_qty=50,
        )
        # Run the batch.
        resp = api.allocate_supply_batch(
            allocate_batch_payload(sku=ctx["item"]["sku"]),
            supply_manager_headers,
        )
        validate_success(resp, 200)
        # Read back each request.
        req_a = validate_success(api.get_supply_request(
            ctx["request_high"]["id"], supply_manager_headers,
        ))
        req_b = validate_success(api.get_supply_request(
            ctx["request_low"]["id"], supply_manager_headers,
        ))
        assert req_a["allocated_quantity"] == 80, (
            f"HIGH-tier PPE request (priority 105) sorts first and "
            f"should receive full 80 units; got "
            f"allocated_quantity={req_a['allocated_quantity']}"
        )
        assert req_b["allocated_quantity"] == 20, (
            f"LOW-tier PPE request (priority 5) sorts second and "
            f"should receive remaining 100-80 = 20 units; got "
            f"allocated_quantity={req_b['allocated_quantity']}"
        )
        # PRD §3.7 invariant: total allocated == 100 (no fractional).
        assert (req_a["allocated_quantity"]
                + req_b["allocated_quantity"]) == 100


# ===========================================================================
# Dispatch / Deliver / Consume — PRD §3.7
# ===========================================================================
class TestDispatchAndConsume:

    def test_dispatch_quantity_must_match_allocated(self, api,
                                                    supply_manager_headers):
        """PRD §3.7: "The quantity must equal the request's
        allocated_quantity; mismatch is rejected with
        ERR_DISPATCH_QUANTITY_MISMATCH."

        Claim: a dispatch with quantity != allocated_quantity →
        ERR_DISPATCH_QUANTITY_MISMATCH.
        """
        item = create_supply_item(
            sku="SKU-DM-1", category="PPE", reserve_quantity=50,
        )
        _region, hospital = setup_district_with_hospital(
            district_code="D-DM-1",
        )
        req = submit_supply_request(
            sku=item["sku"], hospital_id=hospital["id"],
            requested_quantity=10,
        )
        # Allocate.
        alloc_resp = api.allocate_supply_request(
            req["id"], supply_manager_headers,
        )
        allocated = validate_success(alloc_resp, 200)
        assert allocated["status"] == "ALLOCATED"
        # Dispatch with wrong quantity.
        bad = api.dispatch_supply_request(
            req["id"], dispatch_payload(quantity=allocated["allocated_quantity"] + 1),
            supply_manager_headers,
        )
        validate_error(bad, ApiErrorId.ERR_DISPATCH_QUANTITY_MISMATCH.value)

    def test_consume_exceeds_dispatch_rejected(self, api,
                                                supply_manager_headers):
        """PRD §3.7: "this must not exceed dispatched_quantity, with
        ERR_CONSUMPTION_EXCEEDS_DISPATCH thrown otherwise."

        Claim: reporting consumed_quantity > dispatched_quantity →
        ERR_CONSUMPTION_EXCEEDS_DISPATCH.
        """
        item = create_supply_item(
            sku="SKU-CON-1", category="PPE", reserve_quantity=50,
        )
        _region, hospital = setup_district_with_hospital(
            district_code="D-CON-1",
        )
        req = submit_supply_request(
            sku=item["sku"], hospital_id=hospital["id"],
            requested_quantity=10,
        )
        # Allocate → Dispatch → Deliver.
        alloc = validate_success(api.allocate_supply_request(
            req["id"], supply_manager_headers,
        ))
        dispatched = validate_success(api.dispatch_supply_request(
            req["id"],
            dispatch_payload(quantity=alloc["allocated_quantity"]),
            supply_manager_headers,
        ), 201)
        validate_success(api.deliver_dispatch(
            dispatched["id"], supply_manager_headers,
        ))
        # Consume > dispatched.
        bad = api.consume_supply_request(
            req["id"], consume_payload(consumed_quantity=alloc["allocated_quantity"] + 5),
            make_hospital_reporter_headers(hospital["id"]),
        )
        validate_error(bad, ApiErrorId.ERR_CONSUMPTION_EXCEEDS_DISPATCH.value)


# ===========================================================================
# Cancel — PRD §3.7
# ===========================================================================
class TestSupplyCancel:

    def test_cancel_allocated_returns_allocated_quantity_to_pool(
        self, api, supply_manager_headers,
    ):
        """PRD §3.7: "Cancelling a PENDING request simply moves it to
        CANCELLED; cancelling an ALLOCATED request also decrements the
        item's allocated_quantity by the previously-allocated amount,
        returning that capacity to the next allocation cycle."

        Claim: cancelling an ALLOCATED request leaves
        SupplyItem.reserve_quantity unchanged and resets
        SupplyItem.allocated_quantity to 0.
        # difficulty: compensating_invariant/supply_allocate_then_cancel_preserves_available
        """
        item_before = create_supply_item(
            sku="SKU-CA-1", category="PPE", reserve_quantity=100,
        )
        _region, hospital = setup_district_with_hospital(
            district_code="D-CA-1",
        )
        req = submit_supply_request(
            sku=item_before["sku"], hospital_id=hospital["id"],
            requested_quantity=30,
        )
        alloc = validate_success(api.allocate_supply_request(
            req["id"], supply_manager_headers,
        ))
        assert alloc["status"] == "ALLOCATED"
        assert alloc["allocated_quantity"] == 30
        # Snapshot item after allocate.
        item_after_alloc = validate_success(api.get_supply_item(
            item_before["id"], supply_manager_headers,
        ))
        assert item_after_alloc["allocated_quantity"] == 30
        # Cancel.
        cancelled = validate_success(api.cancel_supply_request(
            req["id"], supply_manager_headers,
        ))
        assert cancelled["status"] == "CANCELLED"
        # Item after cancel: reserve unchanged, allocated back to 0.
        item_final = validate_success(api.get_supply_item(
            item_before["id"], supply_manager_headers,
        ))
        assert item_final["reserve_quantity"] == 100, (
            "PRD §3.7: cancel of ALLOCATED does not change reserve_quantity"
        )
        assert item_final["allocated_quantity"] == 0, (
            "PRD §3.7: cancel of ALLOCATED decrements allocated_quantity"
        )
        assert_supply_item_invariant(item_final)
