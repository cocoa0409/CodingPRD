"""Read and action endpoints: filtered pages, computed rosters and receipts.

Nothing here is a smoke test — each case pins a page whose contents an
implementation could only get right by filtering before paginating, or a receipt
whose one request has to fan out across three entities.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    add_assessment,
    add_sibling_vehicle,
    assert_pack_shipment,
    assert_reman_stock,
    assert_same_instant,
    list_centers,
    list_modules,
    list_shipments,
    quarantine_pack_with_s3_event,
    read_center,
    read_pack,
    read_program,
    read_shipment,
    setup_base_world,
    setup_center,
    shipment_payload,
    tender_payload,
    validate_error,
    validate_success,
)

THREE_ROWS = [
    ("2026-07-20T00:00:00Z", 71000, 56.000),
    ("2026-07-22T00:00:00Z", 71200, 56.000),
    ("2026-07-24T00:00:00Z", 71400, 56.000),
]


class TestServiceCenterListing:
    """Two filters that must AND, and a page counted against the filtered set."""

    def test_the_filters_combine_and_the_second_page_reports_the_filtered_total(self, api):
        """Four centres, then 3, then 2, then one row on the offset page.

        PRD 2.1: "Every list response repeats `limit` and `offset` in the `meta` object
        alongside `total_count` (the number of records matching the filter before
        pagination) and `has_more` (true when records remain beyond the current page)."

        PRD 6: "List service centers, filterable by region, status and certification
        level."

        PRD 3.1: "A new center is `ACTIVE` with `compliance_score` 100 and all three of
        `open_hazmat_holds`, `rejected_shipment_count` and `late_notification_count` at
        zero."

        Design: Corner/endpoints/service_center_listing_filters_and_paginates_independently
        """
        setup_center(api, name="Center A", region_code="US-WEST", hv_certification_level="L3")
        setup_center(api, name="Center B", region_code="US-EAST", hv_certification_level="L3")
        setup_center(api, name="Center C", region_code="US-EAST", hv_certification_level="L1")
        expected_second = setup_center(
            api, name="Center D", region_code="US-EAST", hv_certification_level="L3"
        )

        rows, meta = list_centers(api)
        assert meta["total_count"] == 4
        assert meta["has_more"] is False
        for row in rows:
            assert row["status"] == "ACTIVE"
            assert row["compliance_score"] == 100
            assert row["open_hazmat_holds"] == 0
            assert row["rejected_shipment_count"] == 0
            assert row["late_notification_count"] == 0

        _, east_meta = list_centers(api, region_code="US-EAST")
        assert east_meta["total_count"] == 3

        # Both filters bear on the same set rather than replacing one another.
        _, east_l3_meta = list_centers(api, region_code="US-EAST", hv_certification_level="L3")
        assert east_l3_meta["total_count"] == 2

        page, page_meta = list_centers(
            api, region_code="US-EAST", hv_certification_level="L3", limit=1, offset=1
        )
        assert len(page) == 1
        # Ordering is `created_at` ascending, so the second L3 US-EAST centre is D.
        assert page[0]["id"] == expected_second["id"]
        assert page[0]["name"] == "Center D"
        assert page_meta["total_count"] == 2
        assert page_meta["limit"] == 1
        assert page_meta["offset"] == 1
        assert page_meta["has_more"] is False

        empty, empty_meta = list_centers(api, status="SHIPPING_SUSPENDED")
        assert empty == []
        assert empty_meta["total_count"] == 0
        assert empty_meta["has_more"] is False


class TestModuleRosterAfterOneAssessment:
    """Three states in one roster, and a counter that reads only one of them."""

    def test_faults_and_degradations_partition_the_roster_without_inflating_the_counter(
        self, api
    ):
        """Two FAULTED, three DEGRADED, eleven HEALTHY — and faulted_module_count 2.

        PRD 3.3: "`module_fault_positions` lists the integer `position_index` values this
        diagnostic declares faulted; `module_degraded_positions` lists those it declares
        merely degraded. Both arrays are accepted for both variants, both default to
        empty, and both are written through to the pack's modules — setting those children
        to `FAULTED` and `DEGRADED` respectively — *before* any retention arithmetic runs."

        PRD 3.1: "A pack's two derived roster counters follow from that:
        `module_replacements_to_date` is the count of its children in `REPLACED`, and
        `faulted_module_count` is the count of its children in `FAULTED`."

        PRD 3.1: "Each module's `module_capacity_kwh` is its parent's
        `nominal_capacity_kwh` divided by its `module_count`, rounded half up to three
        decimals. Modules are reachable only through their pack's module listing, which
        returns them in ascending `position_index` order."

        PRD 3.3: "For `TELEMATICS_FLEET`, the denominator `nominal_basis_kwh` is the
        pack's full beginning-of-life `nominal_capacity_kwh`; faulted modules are *not*
        excluded from it."

        Design: Corner/endpoints/pack_and_module_reads_reflect_the_assessment_fault_and_degrade_writes
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000491"},
            pack_overrides={"serial_number": "PK-C291"},
            snapshots=THREE_ROWS,
        )
        assessment = add_assessment(
            api,
            world,
            module_fault_positions=[3, 7],
            module_degraded_positions=[1, 2, 16],
        )
        # The fleet denominator is the whole pack, so retention is unmoved by the faults.
        assert assessment["retention_pct"] == pytest.approx(70.00, abs=0.01)

        pack = read_pack(api, world["pack_id"])
        assert pack["faulted_module_count"] == 2
        assert pack["module_replacements_to_date"] == 0

        roster, roster_meta = list_modules(api, world["pack_id"], limit=100)
        assert roster_meta["total_count"] == 16
        by_status = {}
        for row in roster:
            by_status.setdefault(row["status"], []).append(row["position_index"])
        assert sorted(by_status["FAULTED"]) == [3, 7]
        assert sorted(by_status["DEGRADED"]) == [1, 2, 16]
        assert len(by_status["HEALTHY"]) == 11
        for row in roster:
            assert row["module_capacity_kwh"] == pytest.approx(5.000, abs=0.001)
            assert row["thermal_runaway_flag"] is False

        page, page_meta = list_modules(api, world["pack_id"], limit=3, offset=2)
        assert [row["position_index"] for row in page] == [3, 4, 5]
        assert page_meta["total_count"] == 16
        assert page_meta["has_more"] is True
        assert page[0]["status"] == "FAULTED"
        assert page[1]["status"] == "HEALTHY"
        assert page[2]["status"] == "HEALTHY"


def _quarantined_pack_worlds(api, specs) -> list:
    """One programme and centre, and a quarantined pack per (vin, serial) pair."""
    worlds = []
    for index, (vin, serial) in enumerate(specs):
        if index == 0:
            world = setup_base_world(
                api,
                vehicle_overrides={"vin": vin},
                pack_overrides={"serial_number": serial},
                snapshots=None,
            )
        else:
            world = add_sibling_vehicle(api, worlds[0], vin=vin, serial_number=serial)
        quarantine_pack_with_s3_event(api, world, detected_at="2026-07-30T00:00:00Z")
        worlds.append(world)
    return worlds


class TestTenderConformanceGates:
    """Three identical damaged packs, differing only in packaging and charge."""

    def test_packaging_is_reported_first_and_the_soc_boundary_is_inclusive(self, api):
        """Nonconformant packaging, then 30.01 %, then exactly 30.00 % goes out.

        PRD 3.10: "`packaging_spec` must equal `required_packaging_spec`, or the tender is
        refused with `ERR_PACKAGING_NONCONFORMANT` — shipping a damaged pack in standard
        packaging is refused here, at the moment of handover, not at creation. And
        `state_of_charge_pct` must be at or below `soc_limit_pct`, or the tender is refused
        with `ERR_SOC_LIMIT_EXCEEDED`; the boundary value is accepted, so exactly 30.00
        against a 30.00 limit passes. On success the `status` moves to `TENDERED` and
        `tendered_at` is stamped with the current logical clock."

        PRD 3.10: "`soc_limit_pct` is 30.00 when the classification is `UN3536` *or* the
        `transport_mode` is `AIR`, and 50.00 otherwise."

        Design: Corner/endpoints/shipment_tender_checks_packaging_before_the_soc_boundary
        """
        worlds = _quarantined_pack_worlds(
            api,
            [
                ("5YJ3E1EA7KF000501", "PK-C301"),
                ("5YJ3E1EA7KF000502", "PK-C302"),
                ("5YJ3E1EA7KF000503", "PK-C303"),
            ],
        )
        declarations = [
            ("STANDARD_UN_4G", 30.00),
            ("SP376_STRONG_OUTER", 30.01),
            ("SP376_STRONG_OUTER", 30.00),
        ]
        shipments = []
        for world, (packaging_spec, soc) in zip(worlds, declarations):
            shipment = validate_success(
                api.create_shipment(
                    shipment_payload(
                        world["pack_id"],
                        world["center_id"],
                        world["technician_id"],
                        shipment_contents="FULL_PACK",
                        packaging_spec=packaging_spec,
                        state_of_charge_pct=soc,
                    ),
                    world["tech_headers"],
                ),
                expected_status=201,
            )
            assert_pack_shipment(shipment)
            # The damaged flag dominates the FULL_PACK contents rule.
            assert shipment["hazmat_classification"] == "UN3536"
            assert shipment["required_packaging_spec"] == "SP376_STRONG_OUTER"
            assert shipment["soc_limit_pct"] == pytest.approx(30.00, abs=0.01)
            assert shipment["gross_weight_kg"] == pytest.approx(483.296, abs=0.001)
            # ROUND_HALF_UP(18000 * 483.296 / 100) == ROUND_HALF_UP(86993.28)
            assert shipment["hazmat_fee_cents"] == 86993
            shipments.append(shipment)

        # Standard packaging on a UN3536 load, even at a legal state of charge.
        validate_error(
            api.tender_shipment(
                shipments[0]["id"], tender_payload("CR-1"), worlds[0]["tech_headers"]
            ),
            ApiErrorId.ERR_PACKAGING_NONCONFORMANT.value,
            expected_status=409,
        )
        refused = read_shipment(api, shipments[0]["id"])
        assert refused["status"] == "DRAFT"
        assert refused["tendered_at"] is None

        # One hundredth of a point over the UN3536 ceiling.
        validate_error(
            api.tender_shipment(
                shipments[1]["id"], tender_payload("CR-2"), worlds[1]["tech_headers"]
            ),
            ApiErrorId.ERR_SOC_LIMIT_EXCEEDED.value,
            expected_status=409,
        )
        assert read_shipment(api, shipments[1]["id"])["status"] == "DRAFT"

        tendered = validate_success(
            api.tender_shipment(
                shipments[2]["id"], tender_payload("CR-3"), worlds[2]["tech_headers"]
            )
        )
        assert tendered["status"] == "TENDERED"
        assert_same_instant(tendered["tendered_at"], "2026-08-01T00:00:00Z", "tendered_at")

        # A refused tender is not a compliance event.
        center = read_center(api, worlds[0]["center_id"])
        assert center["status"] == "ACTIVE"
        assert center["rejected_shipment_count"] == 0


class TestRemanufactureReceipt:
    """One receipt, three entities: the pack, its roster and the inventory mirror."""

    def test_an_accepted_remanufacture_restocks_the_pack_and_heals_its_whole_roster(
        self, api
    ):
        """STOCK and REMANUFACTURED, sixteen HEALTHY modules, and DEPLETED becomes AVAILABLE.

        PRD 3.10: "On `REMANUFACTURE` the pack returns to inventory: its `status` moves
        from `REMOVED` — or from `QUARANTINED` — to `STOCK`, its `pack_type` becomes
        `REMANUFACTURED`, its `remanufacture_count` rises by one, its `refurb_soh_pct` is
        set from the receipt payload, its `damaged_defective` flag is cleared, and every
        one of its modules is returned to `HEALTHY`. Because a remanufactured pack has
        entered `STOCK`, the program's `reman_available_count` rises by one and
        `reman_stock_state` is refreshed to `AVAILABLE`."

        PRD 3.10: "Either outcome stamps `received_at` with the current logical clock."

        PRD 3.10: "All five are frozen at creation."

        Design: Corner/endpoints/remanufacture_receipt_returns_the_pack_to_stock_and_refills_inventory
        """
        world = setup_base_world(
            api,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000511"},
            pack_overrides={"serial_number": "PK-C311"},
            snapshots=None,
        )
        assert_reman_stock(read_program(api, world["program_id"]), 0, "DEPLETED")
        quarantine_pack_with_s3_event(
            api, world, detected_at="2026-07-30T00:00:00Z", affected_module_positions=[3, 7]
        )
        shipment = validate_success(
            api.create_shipment(
                shipment_payload(
                    world["pack_id"],
                    world["center_id"],
                    world["technician_id"],
                    shipment_contents="FULL_PACK",
                    packaging_spec="SP376_STRONG_OUTER",
                    state_of_charge_pct=30.00,
                    destination="REMAN_CENTER",
                ),
                world["tech_headers"],
            ),
            expected_status=201,
        )
        validate_success(
            api.tender_shipment(
                shipment["id"], tender_payload("CR-9"), world["tech_headers"]
            )
        )

        received = validate_success(
            api.receive_shipment(
                shipment["id"],
                {"outcome": "ACCEPTED", "disposition": "REMANUFACTURE", "refurb_soh_pct": 88.0},
                world["admin_headers"],
            )
        )
        assert received["status"] == "RECEIVED"
        assert received["disposition"] == "REMANUFACTURE"
        assert_same_instant(received["received_at"], "2026-08-01T00:00:00Z", "received_at")
        assert received["rejection_reason"] is None
        # The declaration was frozen at creation and the receipt does not recompute it.
        assert received["hazmat_classification"] == "UN3536"
        assert received["soc_limit_pct"] == pytest.approx(30.00, abs=0.01)

        pack = read_pack(api, world["pack_id"])
        assert pack["status"] == "STOCK"
        assert pack["pack_type"] == "REMANUFACTURED"
        assert pack["refurb_soh_pct"] == pytest.approx(88.00, abs=0.01)
        assert pack["remanufacture_count"] == 1
        assert pack["damaged_defective"] is False
        # PRD 3.10 enumerates exactly what a REMANUFACTURE receipt writes on the pack
        # and does not touch `installed_vehicle_id`; only a pack-replacement fulfilment
        # nulls it (PRD 3.6), so nothing is asserted about it here.

        assert_reman_stock(read_program(api, world["program_id"]), 1, "AVAILABLE")

        roster, roster_meta = list_modules(api, world["pack_id"], limit=100)
        assert roster_meta["total_count"] == 16
        # Positions 3 and 7 had been faulted by the thermal event.
        assert all(row["status"] == "HEALTHY" for row in roster)

        center = read_center(api, world["center_id"])
        assert center["open_hazmat_holds"] == 0
        assert center["rejected_shipment_count"] == 0
        assert center["compliance_score"] == 100
        assert center["status"] == "ACTIVE"


class TestRejectionCountsTheShipmentNotTheHold:
    """The lifetime counter moves twice; the live-hold counter does not move at all."""

    def test_two_rejections_of_already_quarantined_packs_leave_the_center_working(self, api):
        """Score 70 and no hazmat hold, because neither pack entered quarantine here.

        PRD 2.8: "The pack moves from `REMOVED` to `QUARANTINED`, marked damaged and
        reclassified `UN3536`. Because the pack entered quarantine through a rejection,
        the origin center's `open_hazmat_holds` rises by one."

        PRD 2.8: "`open_hazmat_holds` is the number of that center's packs currently
        `QUARANTINED` as the result of a rejected shipment. `rejected_shipment_count` is
        the lifetime number of that center's shipments that reached `REJECTED`... From
        those two lifetime counters the `compliance_score` is recomputed — never
        decremented in place — as one hundred, less fifteen for each rejected shipment,
        less forty for each late notification, with the result floored at zero."

        PRD 3.10: "The `status` must be `TENDERED`, or the receipt is refused with
        `ERR_SHIPMENT_NOT_TENDERED`."

        Design: Corner/endpoints/rejection_of_an_already_quarantined_pack_counts_the_shipment_not_the_hold
        """
        worlds = _quarantined_pack_worlds(
            api,
            [
                ("5YJ3E1EA7KF000521", "PK-C321"),
                ("5YJ3E1EA7KF000522", "PK-C322"),
            ],
        )
        shipments = []
        for world in worlds:
            shipment = validate_success(
                api.create_shipment(
                    shipment_payload(
                        world["pack_id"],
                        world["center_id"],
                        world["technician_id"],
                        shipment_contents="FULL_PACK",
                        packaging_spec="SP376_STRONG_OUTER",
                        state_of_charge_pct=30.00,
                    ),
                    world["tech_headers"],
                ),
                expected_status=201,
            )
            tendered = validate_success(
                api.tender_shipment(
                    shipment["id"], tender_payload(), world["tech_headers"]
                )
            )
            assert tendered["status"] == "TENDERED"
            shipments.append(shipment)

        reasons = ("DOCUMENTATION_MISSING", "PACKAGING_NONCONFORMANT")
        for world, shipment, reason in zip(worlds, shipments, reasons):
            rejected = validate_success(
                api.receive_shipment(
                    shipment["id"],
                    {"outcome": "REJECTED", "rejection_reason": reason},
                    world["admin_headers"],
                )
            )
            assert rejected["status"] == "REJECTED"
            assert rejected["rejection_reason"] == reason
            assert rejected["disposition"] is None
            pack = read_pack(api, world["pack_id"])
            assert pack["status"] == "QUARANTINED"
            assert pack["damaged_defective"] is True

        center = read_center(api, worlds[0]["center_id"])
        assert center["rejected_shipment_count"] == 2
        # 100 - 15 * 2 - 40 * 0 == 70.
        assert center["compliance_score"] == 70
        # PRD 3.10's rejection cascade raises `open_hazmat_holds` unconditionally ("a
        # second rejection both suspends shipping and drops the score to 70") and never
        # says a pack already standing in `QUARANTINED` is exempt, so neither the hold
        # count nor the resulting center status is uniquely determined here.

        # REJECTED is terminal, so a further receipt never reaches the disposition rules.
        validate_error(
            api.receive_shipment(
                shipments[0]["id"],
                {"outcome": "ACCEPTED", "disposition": "SCRAP"},
                worlds[0]["admin_headers"],
            ),
            ApiErrorId.ERR_SHIPMENT_NOT_TENDERED.value,
            expected_status=409,
        )
        assert read_shipment(api, shipments[0]["id"])["status"] == "REJECTED"

        rows, meta = list_shipments(
            api, origin_service_center_id=worlds[0]["center_id"], status="REJECTED"
        )
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert {row["id"] for row in rows} == {shipments[0]["id"], shipments[1]["id"]}
