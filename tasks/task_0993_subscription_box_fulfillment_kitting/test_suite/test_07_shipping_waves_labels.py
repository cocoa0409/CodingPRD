"""Shipping waves: window geometry, malformed-interval precedence, manifest
boundary, bulk-assignment atomicity, postage pricing, and the shipment's
parallel label dimension.

Covers PRD §3.5 (waves, labels, scans) and §2.9 (validation order).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_shipment,
    assert_shipping_wave,
    assign_and_manifest,
    assign_shipments_payload,
    assign_to_wave,
    create_shipping_wave_payload,
    create_wave,
    create_stocked_component,
    create_active_plan_with_bom,
    create_client,
    create_run,
    get_shipment,
    get_wave,
    import_named_subscribers,
    list_run_shipments,
    lock_run,
    manifest_wave,
    scan_payload,
    set_clock,
    setup_kitted_scenario,
    ship_via_wave,
    validate_error,
    validate_success,
    TEST_USERS,
)

WAREHOUSE = TEST_USERS["warehouse_ops_headers"]


class TestWaveWindowGeometry:
    def test_wave_same_carrier_buffer_gap_below_30_rejected(self):
        """PRD §3.5: "Against every non-`CANCELLED` wave of the same carrier, a
        new window may not overlap — half-open comparisons, so one window
        ending exactly as another begins is not an overlap — and the gap
        between one window's end and the next window's start must be at least
        thirty minutes; either violation is rejected with
        `ERR_WAVE_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/wave_same_carrier_buffer_gap
        """
        set_clock()
        create_wave("USPS", "GROUND", "2026-05-10T10:00:00Z", "2026-05-10T12:00:00Z")
        resp = api_client.create_shipping_wave(
            create_shipping_wave_payload(
                carrier="USPS", service_level="GROUND",
                pickup_start="2026-05-10T12:15:00Z", pickup_end="2026-05-10T13:00:00Z"),
            WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_WAVE_WINDOW_CONFLICT)

    def test_wave_gap_exactly_30_and_other_carrier_overlap_accepted(self):
        """PRD §3.5: "the gap between one window's end and the next window's
        start must be at least thirty minutes" — exactly thirty minutes
        satisfies it; and the constrained resource is the carrier ("Against
        every non-`CANCELLED` wave of the same carrier"), so a different
        carrier's window may sit wholly inside.

        Design: Difficulty/resource_temporal_overlap/wave_same_carrier_buffer_gap
        """
        set_clock()
        create_wave("USPS", "GROUND", "2026-05-10T10:00:00Z", "2026-05-10T12:00:00Z")

        fedex = validate_success(
            api_client.create_shipping_wave(
                create_shipping_wave_payload(
                    carrier="FEDEX", service_level="GROUND",
                    pickup_start="2026-05-10T11:00:00Z",
                    pickup_end="2026-05-10T11:30:00Z"),
                WAREHOUSE),
            expected_status=201)
        assert fedex["status"] == "SCHEDULED", \
            "a different carrier's window fully inside is accepted"

        usps_after = validate_success(
            api_client.create_shipping_wave(
                create_shipping_wave_payload(
                    carrier="USPS", service_level="EXPRESS",
                    pickup_start="2026-05-10T12:30:00Z",
                    pickup_end="2026-05-10T13:30:00Z"),
                WAREHOUSE),
            expected_status=201)
        assert usps_after["status"] == "SCHEDULED", \
            "a same-carrier gap of exactly 30 minutes is accepted"


class TestMalformedWindowPrecedence:
    def test_wave_malformed_window_rejected_over_overlap_conflict(self):
        """PRD §3.5: "the window includes its start instant and excludes its
        end instant, and the end must be strictly later than the start, with a
        malformed interval rejected as `ERR_INVALID_WINDOW` (HTTP 400). A
        malformed window takes precedence over any overlap finding."

        Design: Difficulty/priority_pair_validation_conflict/wave_malformed_window_rejected_over_overlap_conflict
        """
        set_clock()
        create_wave("USPS", "GROUND", "2026-05-10T10:00:00Z", "2026-05-10T12:00:00Z")
        # Same carrier, geometrically touching the existing window, but
        # end (11:00) is not strictly after start (12:00): malformed wins.
        resp = api_client.create_shipping_wave(
            create_shipping_wave_payload(
                carrier="USPS", service_level="GROUND",
                pickup_start="2026-05-10T12:00:00Z", pickup_end="2026-05-10T11:00:00Z"),
            WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_wave_window_end_equal_to_start_rejected(self):
        """PRD §3.5: "the end must be strictly later than the start, with a
        malformed interval rejected as `ERR_INVALID_WINDOW` (HTTP 400)" — an
        end equal to the start is not strictly later.

        Design: Difficulty/priority_pair_validation_conflict/wave_malformed_window_rejected_over_overlap_conflict
        """
        set_clock()
        resp = api_client.create_shipping_wave(
            create_shipping_wave_payload(
                carrier="FEDEX", service_level="GROUND",
                pickup_start="2026-05-12T13:00:00Z", pickup_end="2026-05-12T13:00:00Z"),
            WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


class TestManifestEmptyBoundary:
    def test_manifest_with_zero_assigned_rejected_empty_collection(self):
        """PRD §3.5: "Manifesting the wave — `SCHEDULED → MANIFESTED` —
        requires at least one assigned shipment (an empty wave is rejected
        with `ERR_WAVE_EMPTY`)". PRD §3.5: "A new wave stands in `SCHEDULED`
        with `assigned_count` 0".

        Design: Difficulty/boundary_precision_check/manifest_with_zero_assigned_rejected_empty_collection
        """
        set_clock()
        wave = create_wave("FEDEX", "GROUND", "2026-05-11T09:00:00Z",
                           "2026-05-11T10:00:00Z")
        assert wave["assigned_count"] == 0

        resp = api_client.manifest_wave(wave["id"], WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_WAVE_EMPTY)

        after = get_wave(wave["id"])
        assert after["status"] == "SCHEDULED", \
            "a rejected manifest must leave the wave SCHEDULED"

    def test_manifest_with_one_assigned_passes(self):
        """PRD §3.5: "requires at least one assigned shipment (an empty wave is
        rejected with `ERR_WAVE_EMPTY`)" — with one assigned shipment the
        manifest proceeds and "purchases one label per assigned shipment".

        Design: Difficulty/boundary_precision_check/manifest_with_zero_assigned_rejected_empty_collection
        """
        env = setup_kitted_scenario(
            "BD2", num_subscribers=1, actual_kitted_count=1, stock=10,
            price_per_box_cents=1000, shipping_weight_grams=800)
        shipment_id = env["shipments"][0]["id"]
        wave = create_wave("FEDEX", "GROUND", "2026-05-11T09:00:00Z",
                           "2026-05-11T10:00:00Z")
        assign_to_wave(wave["id"], [shipment_id])

        manifested = manifest_wave(wave["id"])
        assert manifested["status"] == "MANIFESTED"
        shipment = get_shipment(shipment_id)
        assert shipment["fulfill_status"] == "MANIFESTED"
        assert shipment["label_status"] == "PURCHASED"


class TestBulkAssignAtomicity:
    def test_assign_shipments_bulk_all_or_nothing(self):
        """PRD §3.5: "The call is transactional: if any named shipment is
        ineligible, the whole assignment is rejected." PRD §3.5: "A shipment is
        eligible only when the wave is `SCHEDULED`, the shipment itself stands
        in `STAGED` with a `label_status` of `NONE` or `VOIDED`, and its
        owning run stands in `KITTING`, `KITTED`, or `CLOSED`; each violation
        surfaces as `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/endpoints/assign_shipments_bulk_all_or_nothing
        """
        env = setup_kitted_scenario(
            "EP1", num_subscribers=2, actual_kitted_count=1, stock=10,
            price_per_box_cents=1000, shipping_weight_grams=800)
        run_id = env["run"]["id"]
        staged = list_run_shipments(run_id, fulfill_status="STAGED")
        cancelled = list_run_shipments(run_id, fulfill_status="CANCELLED")
        assert len(staged) == 1 and len(cancelled) == 1
        wave = create_wave("USPS", "GROUND", "2026-05-10T10:00:00Z",
                           "2026-05-10T11:00:00Z")

        resp = api_client.assign_shipments(
            wave["id"],
            assign_shipments_payload([staged[0]["id"], cancelled[0]["id"]]),
            WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        wave_after = get_wave(wave["id"])
        assert wave_after["assigned_count"] == 0, \
            "the whole call must roll back when one shipment is ineligible"
        shipment_after = get_shipment(staged[0]["id"])
        assert shipment_after["fulfill_status"] == "STAGED"
        assert shipment_after["wave_id"] is None, \
            "the eligible shipment must not be assigned by the rejected call"


class TestTerminalWaveAndShipment:
    def test_tendered_wave_cannot_be_cancelled(self):
        """PRD §3.5: "Tendering — `MANIFESTED → TENDERED`, terminal for the
        wave". PRD §2.9: "The generic wrong-state rejection is
        `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/tendered_wave_cannot_be_cancelled
        """
        env = setup_kitted_scenario(
            "SM4", num_subscribers=1, actual_kitted_count=1, stock=10,
            price_per_box_cents=1000, shipping_weight_grams=800)
        shipment_id = env["shipments"][0]["id"]
        wave, _shipments = ship_via_wave(
            [shipment_id], carrier="UPS", service_level="GROUND",
            pickup_start="2026-05-10T10:00:00Z", pickup_end="2026-05-10T11:00:00Z",
            tender=True)
        assert wave["status"] == "TENDERED"

        resp = api_client.cancel_wave(wave["id"], WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_wave(wave["id"])["status"] == "TENDERED", \
            "a terminal wave must not mutate"

    def test_manifested_shipment_cannot_be_cancelled(self):
        """PRD §3.5: "Cancelling a shipment — `QUEUED → CANCELLED` or
        `STAGED → CANCELLED`, and rejected from any other `fulfill_status`
        with `ERR_INVALID_STATE`".

        Design: Corner/state_machines/manifested_shipment_cannot_be_cancelled
        """
        env = setup_kitted_scenario(
            "SM7", num_subscribers=1, actual_kitted_count=1, stock=10,
            price_per_box_cents=1000, shipping_weight_grams=800)
        shipment_id = env["shipments"][0]["id"]
        wave = create_wave("UPS", "GROUND", "2026-05-10T10:00:00Z",
                           "2026-05-10T11:00:00Z")
        assign_and_manifest(wave["id"], [shipment_id])

        resp = api_client.cancel_shipment(shipment_id, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_shipment(shipment_id)
        assert after["fulfill_status"] == "MANIFESTED"
        assert after["label_status"] == "PURCHASED"


class TestPostagePricing:
    def _manifest_one(self, sku_prefix, weight, zone, carrier, service_level):
        """One kitted box manifested on a fresh wave; returns shipment id."""
        env = setup_kitted_scenario(
            sku_prefix, num_subscribers=1, actual_kitted_count=1, stock=10,
            price_per_box_cents=1000, shipping_weight_grams=weight, zone=zone)
        shipment_id = env["shipments"][0]["id"]
        wave = create_wave(carrier, service_level, "2026-05-10T10:00:00Z",
                           "2026-05-10T11:00:00Z")
        assign_to_wave(wave["id"], [shipment_id])
        return env, wave, shipment_id

    def test_postage_tiered_multi_input_express_remote_amount(self):
        """PRD §3.5: "The packed weight from the plan's
        `shipping_weight_grams` is divided into 500-gram slabs, rounding up to
        a whole number of slabs. A service base applies — 320 cents for
        `GROUND`, 745 cents for `EXPRESS` — plus a per-slab rate read from the
        subscriber's `zone`: 25 cents for zone 1, 40 for zone 2, 55 for zone 3,
        75 for zone 4, 95 for zone 5, 120 for zone 6, 150 for zone 7, and 185
        for zone 8. The raw charge is the base plus the zone rate multiplied by
        the slab count, and it is then raised to the service minimum if it
        falls short — 450 cents for `GROUND`, 990 cents for `EXPRESS`.
        Finally, an `EXPRESS` shipment to zone 5 or higher attracts a 200-cent
        remote surcharge."

        Design: Difficulty/combinatorial_formula/postage_tiered_multi_input_express_remote
        """
        _env, wave, shipment_id = self._manifest_one(
            "CF1", weight=200, zone=6, carrier="UPS", service_level="EXPRESS")
        manifest_wave(wave["id"])
        shipment = get_shipment(shipment_id)
        # ceil(200/500)=1 slab; raw = 745 + 120x1 = 865; max(990, 865) = 990;
        # EXPRESS to zone 6 (>= 5) adds 200 -> 1190.
        assert shipment["postage_cents"] == 1190, (
            f"EXPRESS zone-6 200g must price at 1190, got "
            f"{shipment['postage_cents']}"
        )

    def test_postage_manifest_purchases_label_and_mints_tracking(self):
        """PRD §3.5: "For each, the shipment moves `ASSIGNED → MANIFESTED`, its
        postage is computed and stored in `postage_cents`, its `label_status`
        becomes `PURCHASED`, and a fresh `tracking_code` is minted — null until
        the first purchase, and re-minted at every subsequent purchase."

        Design: Difficulty/combinatorial_formula/postage_tiered_multi_input_express_remote
        """
        _env, wave, shipment_id = self._manifest_one(
            "CF1", weight=200, zone=6, carrier="UPS", service_level="EXPRESS")
        before = get_shipment(shipment_id)
        assert before["label_status"] == "NONE"
        assert before["tracking_code"] is None, \
            "tracking_code stays null until the first purchase"

        manifest_wave(wave["id"])
        after = get_shipment(shipment_id)
        assert_shipment(after)
        assert after["fulfill_status"] == "MANIFESTED"
        assert after["label_status"] == "PURCHASED"
        assert after["tracking_code"], "a fresh tracking_code must be minted"

    def test_postage_ground_min_charge_floor_applies(self):
        """PRD §3.5: "The raw charge is the base plus the zone rate multiplied
        by the slab count, and it is then raised to the service minimum if it
        falls short — 450 cents for `GROUND`, 990 cents for `EXPRESS`."

        Design: Corner/calculations/postage_ground_min_charge_floor_applies
        """
        _env, wave, shipment_id = self._manifest_one(
            "CC1", weight=100, zone=1, carrier="USPS", service_level="GROUND")
        manifest_wave(wave["id"])
        shipment = get_shipment(shipment_id)
        # ceil(100/500)=1 slab; raw = 320 + 25x1 = 345 < 450 -> floor 450.
        assert shipment["postage_cents"] == 450, (
            f"GROUND floor must lift raw 345 to 450, got "
            f"{shipment['postage_cents']}"
        )


class TestParallelLabelDimension:
    def _setup_manifested_nl2(self):
        """1200 g plan, zone-3 subscriber, USPS GROUND wave manifested:
        postage = max(450, 320 + 55 x ceil(1200/500)=3) = 485."""
        env = setup_kitted_scenario(
            "NL2", num_subscribers=1, actual_kitted_count=1, stock=10,
            price_per_box_cents=2000, shipping_weight_grams=1200, zone=3)
        shipment_id = env["shipments"][0]["id"]
        wave = create_wave("USPS", "GROUND", "2026-05-10T10:00:00Z",
                           "2026-05-10T12:00:00Z")
        assign_and_manifest(wave["id"], [shipment_id])
        return env, wave, shipment_id

    def test_void_label_moves_label_dimension_alone(self):
        """PRD §3.5: "Labels live on a parallel dimension of the shipment,
        independent of fulfillment". PRD §3.5: "A void leaves `fulfill_status`
        untouched, flips the label to `VOIDED`, keeps the last purchased
        `postage_cents` on the shipment for audit, and triggers the period
        statement's provisional postage recompute."

        Design: Difficulty/non_linear_state_machine/shipment_parallel_dimensions_independent
        """
        _env, _wave, shipment_id = self._setup_manifested_nl2()
        voided = validate_success(api_client.void_label(shipment_id, WAREHOUSE))
        assert voided["label_status"] == "VOIDED"
        assert voided["fulfill_status"] == "MANIFESTED", \
            "the label dimension moves alone; fulfillment must not"
        assert voided["postage_cents"] == 485, \
            "the last purchased postage is kept for audit after a void"

    def test_fulfill_dimension_advances_while_label_stays_voided(self):
        """PRD §3.5: "Fulfillment transitions never read `label_status`, and
        label transitions never read `fulfill_status` beyond one guard".
        PRD §3.5: "every `MANIFESTED` shipment of the wave moves `MANIFESTED →
        SHIPPED`" on tender, and "a `scan_type` of `DELIVERED` moves the
        shipment `SHIPPED → DELIVERED` and stamps `delivered_at` with the
        current clock".

        Design: Difficulty/non_linear_state_machine/shipment_parallel_dimensions_independent
        """
        _env, wave, shipment_id = self._setup_manifested_nl2()
        validate_success(api_client.void_label(shipment_id, WAREHOUSE))

        validate_success(api_client.tender_wave(wave["id"], WAREHOUSE))
        scanned = validate_success(
            api_client.scan_shipment(shipment_id, scan_payload("DELIVERED"),
                                     WAREHOUSE))
        assert scanned["fulfill_status"] == "DELIVERED", \
            "the fulfill dimension advances regardless of the VOIDED label"
        assert scanned["label_status"] == "VOIDED", \
            "the label dimension stays VOIDED through tender and scan"
        assert scanned["delivered_at"] is not None
