"""Return cases: the DELIVERED gate on approval, the 30-day window boundary,
and the resolve(REPLACE) cascade into inventory.

Covers PRD §3.6 (returns and replacements) and §2.6 (stock status).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_return_case,
    assert_shipment,
    create_return_case_payload,
    get_component,
    list_component_events,
    open_return_case,
    return_case_to_received,
    scan_payload,
    set_clock,
    setup_kitted_scenario,
    ship_via_wave,
    validate_error,
    validate_success,
    TEST_USERS,
)

WAREHOUSE = TEST_USERS["warehouse_ops_headers"]
SUPPORT = TEST_USERS["customer_service_headers"]


class TestReturnApproveShipmentGate:
    def _setup_shipped_case(self):
        """One box SHIPPED (manifested + tendered, not yet scanned); a REFUND
        return case opened against it."""
        env = setup_kitted_scenario(
            "CE2", num_subscribers=1, actual_kitted_count=1, stock=20,
            price_per_box_cents=2000, shipping_weight_grams=1000, zone=2)
        shipment_id = env["shipments"][0]["id"]
        _wave, shipments = ship_via_wave([shipment_id], tender=True)
        assert shipments[0]["fulfill_status"] == "SHIPPED"
        case = open_return_case(shipment_id, reason="WRONG_ITEM",
                                requested_resolution="REFUND")
        return env, shipment_id, case

    def test_return_approve_requires_shipment_delivered(self):
        """PRD §3.6: "Approving moves `REQUESTED → APPROVED` and is guarded
        twice, in §2.9 order: the referenced shipment must stand in
        `DELIVERED` (else `ERR_SHIPMENT_NOT_DELIVERED`)". PRD §3.6: "The case
        is born `REQUESTED`."

        Design: Difficulty/cross_entity_state_dependency/return_approve_requires_shipment_delivered
        """
        _env, _shipment_id, case = self._setup_shipped_case()
        assert case["status"] == "REQUESTED", \
            "the case opens fine while the shipment is merely SHIPPED"

        resp = api_client.approve_return_case(case["id"], SUPPORT)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_DELIVERED)

        after = validate_success(api_client.get_return_case(case["id"], SUPPORT))
        assert after["status"] == "REQUESTED", \
            "a rejected approve must leave the case REQUESTED"

    def test_return_approve_succeeds_once_shipment_delivered(self):
        """PRD §3.6: "the referenced shipment must stand in `DELIVERED` (else
        `ERR_SHIPMENT_NOT_DELIVERED`)" — once a `DELIVERED` scan lands, the
        same approve call passes the gate. PRD §3.5: "a `scan_type` of
        `DELIVERED` moves the shipment `SHIPPED → DELIVERED`".

        Design: Difficulty/cross_entity_state_dependency/return_approve_requires_shipment_delivered
        """
        _env, shipment_id, case = self._setup_shipped_case()
        validate_success(api_client.scan_shipment(shipment_id,
                                                  scan_payload("DELIVERED"),
                                                  WAREHOUSE))
        approved = validate_success(api_client.approve_return_case(case["id"],
                                                                   SUPPORT))
        assert_return_case(approved)
        assert approved["status"] == "APPROVED"


class TestReturnWindowBoundary:
    def test_return_window_exactly_30_days_passes_then_expired(self):
        """PRD §3.6: "the current clock must read no later than thirty days
        after that shipment's `delivered_at` (else
        `ERR_RETURN_WINDOW_EXPIRED`)".

        Design: Corner/validations/return_window_exactly_30_days_passes_then_expired
        """
        env = setup_kitted_scenario(
            "V4", num_subscribers=2, actual_kitted_count=2, stock=10,
            price_per_box_cents=2000, shipping_weight_grams=800, zone=2)
        shipment_ids = [s["id"] for s in env["shipments"]]
        # Delivered at the logical clock reading 2026-05-01T00:00:00Z.
        ship_via_wave(shipment_ids, carrier="USPS", service_level="GROUND",
                      pickup_start="2026-05-10T10:00:00Z",
                      pickup_end="2026-05-10T11:00:00Z",
                      tender=True, scan_type="DELIVERED")
        case_in = open_return_case(shipment_ids[0], reason="DAMAGED",
                                   requested_resolution="REFUND")
        case_out = open_return_case(shipment_ids[1], reason="LOST",
                                    requested_resolution="REFUND")

        # delivered_at 2026-05-01T00:00:00Z + 30 days == 2026-05-31T00:00:00Z.
        set_clock("2026-05-31T00:00:00Z")
        approved = validate_success(api_client.approve_return_case(case_in["id"],
                                                                   SUPPORT))
        assert approved["status"] == "APPROVED", \
            "approval exactly thirty days after delivery must pass"

        set_clock("2026-05-31T00:00:01Z")
        resp = api_client.approve_return_case(case_out["id"], SUPPORT)
        validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED)


class TestReturnReplaceCascade:
    def _setup_received_replace_case(self):
        """Component: 100 on hand, reorder 95, BOM qty 2; run kitted 2 boxes
        (commit 4 -> on_hand 96, available 96 > 95 OK). Shipment 1 DELIVERED;
        shipment 2 stays STAGED. Case REPLACE approved and received."""
        env = setup_kitted_scenario(
            "TC1", num_subscribers=2, actual_kitted_count=2,
            qty_per_box=2, stock=100, price_per_box_cents=2000,
            shipping_weight_grams=1000, zone=2, reorder_point_units=95)
        shipment_id = env["shipments"][0]["id"]
        ship_via_wave([shipment_id], carrier="USPS", service_level="GROUND",
                      pickup_start="2026-05-10T10:00:00Z",
                      pickup_end="2026-05-10T12:00:00Z",
                      tender=True, scan_type="DELIVERED")
        case = open_return_case(shipment_id, reason="DAMAGED",
                                requested_resolution="REPLACE")
        return_case_to_received(case["id"])
        return env, shipment_id, case

    def test_resolve_replace_creates_staged_replacement_shipment(self):
        """PRD §3.6: "On success the server creates a replacement shipment
        bound to the same `run_id` and `subscriber_id` as the original,
        flagged `is_replacement` true (a flag that is false on every ordinary
        shipment), standing in `STAGED` with `label_status` `NONE` ... records
        the new shipment's `id` in `replacement_shipment_id` (null on cases
        resolved any other way); and stamps `resolution_applied` as
        `REPLACED`."

        Design: Difficulty/transitive_cascade/return_replace_cascade_to_component_posture
        """
        env, shipment_id, case = self._setup_received_replace_case()
        resolved = validate_success(api_client.resolve_return_case(case["id"],
                                                                   SUPPORT))
        assert_return_case(resolved)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_applied"] == "REPLACED"
        assert resolved["replacement_shipment_id"], \
            "the replacement shipment id must be recorded"

        replacement = validate_success(
            api_client.get_shipment(resolved["replacement_shipment_id"], WAREHOUSE))
        assert_shipment(replacement)
        assert replacement["fulfill_status"] == "STAGED"
        assert replacement["label_status"] == "NONE"
        assert replacement["is_replacement"] is True
        assert replacement["run_id"] == env["run"]["id"], \
            "the replacement is bound to the original run"
        assert replacement["subscriber_id"] == env["subscribers"][0]["id"]

    def test_resolve_replace_commits_stock_and_flips_stock_status(self):
        """PRD §3.6: "appends `COMMIT` inventory events per BOM line for one
        box, dropping each component's `on_hand_units` by the line's
        `qty_per_box`; recomputes the touched components' `stock_status`".
        PRD §2.6: "`stock_status`, which reads `LOW` when `available_units` is
        less than or equal to the component's `reorder_point_units` and `OK`
        otherwise."

        Design: Difficulty/transitive_cascade/return_replace_cascade_to_component_posture
        """
        env, _shipment_id, case = self._setup_received_replace_case()
        component_id = env["component"]["id"]
        pre = get_component(component_id)
        assert pre["on_hand_units"] == 96 and pre["stock_status"] == "OK", (
            f"pre-resolve posture must be 96/OK, got {pre['on_hand_units']}/"
            f"{pre['stock_status']}"
        )

        validate_success(api_client.resolve_return_case(case["id"], SUPPORT))

        post = get_component(component_id)
        assert post["on_hand_units"] == 94, (
            f"the replacement commits one box of 2 units: "
            f"on_hand {post['on_hand_units']}"
        )
        assert post["stock_status"] == "LOW", \
            "available 94 <= reorder_point 95 must flip stock_status to LOW"

        commits = list_component_events(component_id, event_type="COMMIT")
        deltas = sorted(e["quantity_delta"] for e in commits)
        assert deltas == [-4, -2], (
            f"one COMMIT of -4 (kitting two boxes) and one of -2 "
            f"(the replacement box) expected, got {deltas}"
        )
