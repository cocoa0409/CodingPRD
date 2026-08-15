"""Catalog edits (OCC), pack allocation ceilings, packet codes, and the
seed-count conservation invariant."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_seed_count_conservation,
    create_variety,
    get_lot,
    make_volunteer_headers,
    pack_packets,
    read_site,
    setup_active_lot,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestPackAllocationCeilings:
    def test_pack_above_seed_ceiling_rejected(self):
        """PRD §3.4: "The seed ceiling is the lot's `viable_seed_count` divided
        by `seeds_per_packet`, rounded down. The label ceiling is the home
        site's `label_stock_count`, one label per packet. The lifetime ceiling
        is two hundred packets per lot minus the lot's `packets_created_total`
        so far. The allocatable quantity is the smallest of the three; a
        request is admitted only when `packet_count` is at least 1 and at most
        that allocatable figure, and is otherwise rejected with
        `ERR_PACK_QUANTITY_EXCEEDS_ALLOCATABLE`."

        viable 800, labels 100, lifetime headroom 200 -> allocatable 40; a
        request for 41 exceeds it.

        Design: Difficulty/combinatorial_formula/pack_allocation_min_of_four_inputs_mode_a
        """
        ctx = setup_active_lot(
            seeds_received=1000,
            provisional_viability_pct=80.00,
            certified_tested=100,
            certified_sprouted=80,
            label_stock=100,
            site_type="GARDEN",
            zone="ZONE_6B",
        )
        resp = api_client.pack_seed_lot(
            ctx["lot"]["id"],
            {"packet_count": 41, "seeds_per_packet": 20},
            make_volunteer_headers(ctx["volunteer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PACK_QUANTITY_EXCEEDS_ALLOCATABLE)

    def test_pack_at_allocatable_succeeds_and_debits_seeds_and_labels(self):
        """PRD §3.4: "A successful pack moves seeds and labels atomically: the
        lot's loose bucket decreases by `packet_count` times `seeds_per_packet`
        and its in-packets bucket increases by the same amount; the site's
        `label_stock_count` falls by `packet_count`; the lot's
        `packets_created_total` rises by `packet_count`."

        Packing exactly 40 (the min of 40 seed ceiling, 100 labels, 200 lot
        headroom) debits 800 seeds and 40 labels.

        Design: Difficulty/combinatorial_formula/pack_allocation_min_of_four_inputs_mode_a
        """
        ctx = setup_active_lot(
            seeds_received=1000,
            provisional_viability_pct=80.00,
            certified_tested=100,
            certified_sprouted=80,
            label_stock=100,
            site_type="GARDEN",
            zone="ZONE_6B",
        )
        packet_ids = pack_packets(
            ctx["lot"]["id"], ctx["volunteer"]["id"],
            packet_count=40, seeds_per_packet=20,
        )
        assert len(packet_ids) == 40
        lot = get_lot(ctx["lot"]["id"])
        assert lot["seeds_remaining"] == 200, (
            f"Expected 1000 - 40*20 = 200 loose, got {lot['seeds_remaining']}"
        )
        assert lot["seeds_in_packets"] == 800
        assert lot["packets_created_total"] == 40
        site = read_site(ctx["site"]["id"])
        assert site["label_stock_count"] == 60, (
            f"Expected 100 - 40 = 60 labels, got {site['label_stock_count']}"
        )
        assert_seed_count_conservation(lot)


class TestPackEdgeCases:
    def test_pack_rejected_when_seed_ceiling_floors_to_zero(self):
        """PRD §3.4: "The allocatable quantity is the smallest of the three; a
        request is admitted only when `packet_count` is at least 1 and at most
        that allocatable figure, and is otherwise rejected with
        `ERR_PACK_QUANTITY_EXCEEDS_ALLOCATABLE`."

        10 seeds at certified 70.00 (the lowest PASS-band figure per §3.3)
        -> viable 7; floor(7 / 10) == 0, so even one packet of 10 is over
        the allocatable figure.

        Design: Corner/calculations/calc_pack_zero_allocatable_rejected
        """
        ctx = setup_active_lot(
            seeds_received=10,
            provisional_viability_pct=70.00,
            certified_tested=100,
            certified_sprouted=70,
            site_type="GARDEN",
            zone="ZONE_7A",
        )
        assert ctx["lot"]["viable_seed_count"] == 7
        resp = api_client.pack_seed_lot(
            ctx["lot"]["id"],
            {"packet_count": 1, "seeds_per_packet": 10},
            make_volunteer_headers(ctx["volunteer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PACK_QUANTITY_EXCEEDS_ALLOCATABLE)


class TestPacketCodes:
    def test_packet_code_format_and_per_lot_sequence(self):
        """PRD §3.4: "New packets begin `AVAILABLE`, each stamped with a
        human-readable `packet_code` built from the lot code, the harvest year,
        and a three-digit per-lot sequence that starts at 001 — for example,
        the first packet of lot "BRN-24" harvested in 2024 reads
        "BRN-24-2024-001"."

        First pack call of 2 packets takes 001/002; a second pack call of 1
        continues the same per-lot sequence at 003.

        Design: Corner/entities/entity_packet_code_format_and_sequence
        """
        ctx = setup_active_lot(
            seeds_received=500,
            provisional_viability_pct=90.00,
            certified_tested=50,
            certified_sprouted=45,
            site_type="GARDEN",
            zone="ZONE_7A",
            label_stock=10,
            lot_code="LBL",
        )
        first_ids = pack_packets(
            ctx["lot"]["id"], ctx["volunteer"]["id"],
            packet_count=2, seeds_per_packet=10,
        )
        second_ids = pack_packets(
            ctx["lot"]["id"], ctx["volunteer"]["id"],
            packet_count=1, seeds_per_packet=10,
        )
        first_codes = sorted(
            validate_success(api_client.get_seed_packet(pid, ADMIN), 200)[
                "packet_code"
            ]
            for pid in first_ids
        )
        assert first_codes == ["LBL-2026-001", "LBL-2026-002"], (
            f"First pack call must mint 001/002, got {first_codes}"
        )
        second_code = validate_success(
            api_client.get_seed_packet(second_ids[0], ADMIN), 200
        )["packet_code"]
        assert second_code == "LBL-2026-003", (
            f"Sequence must continue across separate pack calls, "
            f"got {second_code}"
        )


class TestSeedCountConservation:
    def test_pack_moves_seeds_from_loose_to_in_packets(self):
        """PRD §2.10: "For each seed lot, the number of seeds physically
        received always equals the sum of three buckets: the seeds still loose
        in the lot, the seeds currently bound in live packets, and the seeds
        that have been discarded."

        pack(10 x 20) on a 1000-seed lot: remaining 800, in_packets 200,
        discarded 0.

        Design: Difficulty/compensating_invariant/seed_count_conservation_pack_then_void_reintegrate
        """
        ctx = setup_active_lot(seeds_received=1000, provisional_viability_pct=90.00)
        pack_packets(
            ctx["lot"]["id"], ctx["volunteer"]["id"],
            packet_count=10, seeds_per_packet=20,
        )
        lot = get_lot(ctx["lot"]["id"])
        assert lot["seeds_remaining"] == 800
        assert lot["seeds_in_packets"] == 200
        assert lot["seeds_discarded"] == 0
        assert_seed_count_conservation(lot)

    def test_void_reintegrate_restores_both_buckets_with_zero_drift(self):
        """PRD §3.4: "An administrator may void an `AVAILABLE` packet —
        unpacking it — with a `mode` of `REINTEGRATE` or `DISCARD`:
        reintegration returns the packet's `seeds_count` to the lot's loose
        bucket, while discarding moves it into the discarded bucket, and in
        both modes the `seeds_count` leaves the in-packets bucket, the packet
        becomes `VOIDED`, the lot and packet versions advance, and the
        depletion check runs."
        PRD §2.10: "For each seed lot, the number of seeds physically received
        always equals the sum of three buckets: the seeds still loose in the
        lot, the seeds currently bound in live packets, and the seeds that have
        been discarded."

        pack(10 x 20) then void REINTEGRATE on all 10: remaining back to 1000,
        in_packets 0, discarded 0.

        Design: Difficulty/compensating_invariant/seed_count_conservation_pack_then_void_reintegrate
        """
        ctx = setup_active_lot(seeds_received=1000, provisional_viability_pct=90.00)
        packet_ids = pack_packets(
            ctx["lot"]["id"], ctx["volunteer"]["id"],
            packet_count=10, seeds_per_packet=20,
        )
        for pid in packet_ids:
            resp = api_client.void_seed_packet(pid, {"mode": "REINTEGRATE"}, ADMIN)
            validate_success(resp, 200)
        lot = get_lot(ctx["lot"]["id"])
        assert lot["seeds_remaining"] == 1000, (
            f"Compensating voids must restore the loose bucket, "
            f"got {lot['seeds_remaining']}"
        )
        assert lot["seeds_in_packets"] == 0
        assert lot["seeds_discarded"] == 0
        assert_seed_count_conservation(lot)


class TestVarietyOptimisticConcurrency:
    def test_stale_expected_version_rejected_after_successful_edit(self):
        """PRD §2.7: "Editing a seed variety requires the request to carry
        `expected_seed_variety_version`, holding the variety `version` the
        client last observed. ... In both cases the field is non-optional: if
        the supplied value does not equal the entity's current `version`, the
        write is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the
        client from overwriting a record it has not observed. A successful
        guarded write increments the entity's `version`, advancing the
        watermark every subsequent writer must match."

        Design: Corner/cross_cutting_layers/occ_variety_update_stale_version
        """
        variety = create_variety(category="HERB", approved_zones=["ZONE_7A"])
        observed = variety["version"]
        resp = api_client.update_seed_variety(
            variety["id"],
            {"expected_seed_variety_version": observed, "rarity_flag": True},
            ADMIN,
        )
        updated = validate_success(resp, 200)
        assert updated["version"] == observed + 1, (
            "A successful guarded write increments the entity's version by one"
        )
        resp = api_client.update_seed_variety(
            variety["id"],
            {"expected_seed_variety_version": observed, "invasive_flag": True},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
