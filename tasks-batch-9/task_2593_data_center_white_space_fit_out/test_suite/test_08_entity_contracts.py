"""Entity contracts: the field sets, seeded defaults, inherited references and
list surfaces every resource of the white space publishes on creation and read."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    assert_busway,
    assert_cage,
    assert_containment_zone,
    assert_cooling_unit,
    assert_hall,
    assert_mop_approval,
    assert_pdu,
    assert_rack,
    assert_rack_feed,
    assert_security_device,
    assert_tenant,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    CM,
    EC,
    FP,
    MC,
    OM,
    SA,
    advance_phase,
    approve_mop,
    create_busway,
    create_cage,
    create_camera,
    create_card_reader,
    create_hall,
    create_mop,
    create_pdu,
    create_rack,
    create_zone,
    read_capacity_summary,
    read_hall,
    read_mop,
    revise_mop,
    set_clock,
    setup_fit_out_hall,
    setup_planning_hall,
    submit_mop,
)

CONTRACT_START = "2026-01-01T00:00:00Z"


class TestHallEntityContract:
    """A hall echoes its seven declared inputs, seeds every derived field of the
    power ledger and cooling model, and refuses payloads that are short a required
    field or carry an out-of-domain enum."""

    def _hall_payload(self, code, **overrides):
        payload = {
            "name": f"Corner Hall {code}",
            "code": code,
            "tenant_mode": "SINGLE_TENANT",
            "design_kw_capacity": 400.00,
            "gross_area_sqm": 600.0,
            "cooling_redundancy": "N",
            "planned_rack_count": 8,
        }
        payload.update(overrides)
        return payload

    def test_creation_returns_every_declared_field_of_the_white_space(self):
        """POST /halls answers 201 with all seven declared inputs echoed verbatim, a
        server-minted id, an ISO 8601 created_at, version 1 and status PLANNING.

        PRD: "The registration carries a human label in `name`, a short `code` for
        floor use, the occupancy stance in `tenant_mode` (either `SINGLE_TENANT` or
        `MULTI_TENANT`), the design electrical capacity of the room in
        `design_kw_capacity` (strictly positive, two decimal places), the room's floor
        area in `gross_area_sqm` (strictly positive), the mechanical redundancy stance
        in `cooling_redundancy` (either `N` or `N_PLUS_1`), and the number of rack
        positions the layout plans for in `planned_rack_count` (at least 1). The hall
        is born in `PLANNING`."
        PRD: "Every resource is addressed by an `id`, which is a server-minted UUID
        carrying no type prefix. Clients never supply an `id`. Alongside it, every
        resource carries `created_at`, an ISO 8601 UTC timestamp rendered with three
        fractional digits."
        PRD: "Thirteen of the fourteen resource types additionally carry `updated_at` —
        an ISO 8601 UTC timestamp refreshed on every mutation — and `version`, an integer
        that starts at 1 when the row is created and increments by exactly one on every
        mutation of that row, including mutations that only touch computed fields."

        Design: Corner/entities/hall_creation_returns_declared_field_set
        """
        payload = self._hall_payload(
            "CX01",
            name="Corner Hall 01",
            tenant_mode="MULTI_TENANT",
            design_kw_capacity=400.00,
            gross_area_sqm=600.0,
            cooling_redundancy="N",
            planned_rack_count=10,
        )
        hall = validate_success(api_client.create_hall(payload, FP), 201)
        assert_hall(hall)

        assert hall["name"] == "Corner Hall 01"
        assert hall["code"] == "CX01"
        assert hall["tenant_mode"] == "MULTI_TENANT"
        assert hall["design_kw_capacity"] == pytest.approx(400.00, abs=0.005)
        assert hall["gross_area_sqm"] == pytest.approx(600.0, abs=0.005)
        assert hall["cooling_redundancy"] == "N"
        assert hall["planned_rack_count"] == 10
        assert hall["status"] == "PLANNING", "a registered hall is born in PLANNING"
        assert hall["version"] == 1, "version starts at 1 when the row is created"
        assert is_valid_uuid(hall["id"]), "the id is a server-minted UUID"
        assert is_iso8601_timestamp(hall["created_at"])

    def test_retrieval_returns_the_stored_row_without_re_derivation_drift(self):
        """Reading the hall back returns the same identity and the same seeded ledger:
        committed 0.00 kW, the first-tier reserve of 25.00 kW and spare 225.00 kW
        against a 250.00 kW room, with both postures at their opening values.

        PRD: "Creation seeds every derived field on the hall. The power ledger opens
        with `committed_kw` at 0.00 and `commissioning_reserve_kw` at 25.00 — the first
        reserve tier — so `spare_kw` opens at the design capacity less 25.00."
        PRD: "`thermal_posture` opens at `NOMINAL` and `release_posture` at `OPEN`."

        Design: Corner/entities/hall_retrieval_returns_stored_row
        """
        created = validate_success(
            api_client.create_hall(
                self._hall_payload(
                    "CX02",
                    name="Corner Hall 02",
                    design_kw_capacity=250.00,
                    gross_area_sqm=400.0,
                    planned_rack_count=6,
                ),
                FP,
            ),
            201,
        )

        hall = validate_success(api_client.get_hall(created["id"], OM), 200)
        assert_hall(hall)
        assert hall["id"] == created["id"]
        assert hall["created_at"] == created["created_at"]
        assert hall["code"] == "CX02"
        assert hall["status"] == "PLANNING"
        assert hall["design_kw_capacity"] == pytest.approx(250.00, abs=0.005)
        assert hall["committed_kw"] == pytest.approx(0.00, abs=0.005)
        assert hall["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005)
        assert hall["spare_kw"] == pytest.approx(225.00, abs=0.005), (
            "spare opens at the design capacity less the first reserve tier"
        )
        assert hall["thermal_posture"] == "NOMINAL"
        assert hall["release_posture"] == "OPEN"
        assert hall["version"] == 1, "a plain read is not a mutation"

    def test_hall_list_paginates_and_narrows_by_status(self):
        """Three halls answer a page_size of 2 with total_count 3 and has_more true, the
        second page carries the remaining row, and the status filter narrows the same
        collection to the one hall that has reached FIT_OUT.

        PRD: "`page_size` is a synonym for `limit` and obeys the same default, minimum
        and maximum, and `page` is a one-based page index whose effect is an offset of
        the page index minus one, multiplied by the effective page size."
        PRD: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` counts every row matching the
        request's filters before pagination is applied and `has_more` is true exactly
        when rows remain beyond the returned window."
        PRD: "Hall and tenant lists may be narrowed by `status`, `tenant_mode` and
        `code` respectively."

        Design: Corner/entities/hall_listing_paginates_and_filters_by_status
        """
        create_hall("CX03", name="Corner Hall 03", design_kw_capacity=100.00)
        create_hall(
            "CX04",
            name="Corner Hall 04",
            tenant_mode="MULTI_TENANT",
            design_kw_capacity=100.00,
        )
        ctx = setup_planning_hall(
            "CX05",
            design_kw_capacity=400.00,
            commission_pdus=False,
            with_cooling_unit=False,
            with_busway_b=False,
        )
        advanced = advance_phase(ctx["hall_id"], "FIT_OUT")
        assert advanced["status"] == "FIT_OUT"

        first, first_meta = validate_paginated(
            api_client.list_halls(FP, {"page": 1, "page_size": 2})
        )
        assert len(first) == 2, "a page size of 2 returns exactly two rows"
        assert first_meta["total_count"] == 3, (
            "total_count counts every matching row before pagination"
        )
        assert first_meta["has_more"] is True, "one row remains beyond the window"

        second, second_meta = validate_paginated(
            api_client.list_halls(FP, {"page": 2, "page_size": 2})
        )
        assert len(second) == 1, "the second page carries the remaining row"
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert {row["code"] for row in first + second} == {"CX03", "CX04", "CX05"}, (
            "the two pages together cover the whole collection exactly once"
        )

        filtered, filtered_meta = validate_paginated(
            api_client.list_halls(FP, {"status": "FIT_OUT"})
        )
        assert filtered_meta["total_count"] == 1
        assert filtered_meta["has_more"] is False
        assert len(filtered) == 1
        assert filtered[0]["code"] == "CX05", (
            "only the advanced hall matches the status filter"
        )

    def test_missing_design_kw_capacity_is_refused_and_stores_nothing(self):
        """A registration that omits the required design_kw_capacity is refused with
        ERR_VALIDATION and leaves the hall collection empty.

        PRD: "**Request shape (`ERR_VALIDATION`, 422)** — every required field of the
        operation's payload is present; enum-typed fields carry in-domain values;
        numeric fields obey their declared constraints, including strict positivity
        where declared and 2 decimal places on kilowatt fields; datetimes are
        well-formed ISO 8601 UTC instants; every window-bearing payload has its
        `window_end` strictly after its `window_start`; and `step_pct_sequence` is a
        strictly ascending list of integers each between 1 and 100."
        PRD: "The registration carries a human label in `name`, a short `code` for
        floor use, the occupancy stance in `tenant_mode` (either `SINGLE_TENANT` or
        `MULTI_TENANT`), the design electrical capacity of the room in
        `design_kw_capacity` (strictly positive, two decimal places), the room's floor
        area in `gross_area_sqm` (strictly positive), the mechanical redundancy stance
        in `cooling_redundancy` (either `N` or `N_PLUS_1`), and the number of rack
        positions the layout plans for in `planned_rack_count` (at least 1)."

        Design: Corner/entities/hall_missing_required_design_kw_capacity_rejected
        """
        payload = self._hall_payload("CX06", name="Corner Hall 06", planned_rack_count=4)
        payload.pop("design_kw_capacity")

        validate_error(
            api_client.create_hall(payload, FP),
            ApiErrorId.ERR_VALIDATION.value,
            422,
        )

        rows, meta = validate_paginated(api_client.list_halls(FP))
        assert meta["total_count"] == 0, "the refused registration created no hall"
        assert rows == []

    def test_out_of_domain_tenant_mode_is_refused_and_stores_nothing(self):
        """tenant_mode is a two-value enum, so DUAL_TENANT is refused with
        ERR_VALIDATION rather than stored.

        PRD: "**Request shape (`ERR_VALIDATION`, 422)** — every required field of the
        operation's payload is present; enum-typed fields carry in-domain values;
        numeric fields obey their declared constraints, including strict positivity
        where declared and 2 decimal places on kilowatt fields; datetimes are
        well-formed ISO 8601 UTC instants; every window-bearing payload has its
        `window_end` strictly after its `window_start`; and `step_pct_sequence` is a
        strictly ascending list of integers each between 1 and 100."
        PRD: "The registration carries a human label in `name`, a short `code` for
        floor use, the occupancy stance in `tenant_mode` (either `SINGLE_TENANT` or
        `MULTI_TENANT`), the design electrical capacity of the room in
        `design_kw_capacity` (strictly positive, two decimal places), the room's floor
        area in `gross_area_sqm` (strictly positive), the mechanical redundancy stance
        in `cooling_redundancy` (either `N` or `N_PLUS_1`), and the number of rack
        positions the layout plans for in `planned_rack_count` (at least 1)."

        Design: Corner/entities/hall_invalid_tenant_mode_enum_rejected
        """
        validate_error(
            api_client.create_hall(
                self._hall_payload(
                    "CX07",
                    name="Corner Hall 07",
                    tenant_mode="DUAL_TENANT",
                    design_kw_capacity=100.00,
                    planned_rack_count=4,
                ),
                FP,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            422,
        )

        rows, meta = validate_paginated(api_client.list_halls(FP))
        assert meta["total_count"] == 0, "no hall row was stored"
        assert rows == []

    def test_supplied_status_ledger_and_version_values_do_not_reach_the_row(self):
        """A registration that also supplies status LIVE, committed_kw 999.00,
        spare_kw 999.00 and version 42 still yields PLANNING, a committed load of
        0.00 kW, spare of 275.00 kW against a 300.00 kW room and version 1, because
        those figures are seeded and derived by the server.

        PRD: "The hall is born in `PLANNING`."
        PRD: "Creation seeds every derived field on the hall. The power ledger opens
        with `committed_kw` at 0.00 and `commissioning_reserve_kw` at 25.00 — the first
        reserve tier — so `spare_kw` opens at the design capacity less 25.00."
        PRD: "Thirteen of the fourteen resource types additionally carry `updated_at` —
        an ISO 8601 UTC timestamp refreshed on every mutation — and `version`, an integer
        that starts at 1 when the row is created and increments by exactly one on every
        mutation of that row, including mutations that only touch computed fields."

        Design: Corner/entities/hall_system_and_computed_fields_client_input_ignored
        """
        hall = validate_success(
            api_client.create_hall(
                self._hall_payload(
                    "CX08",
                    name="Corner Hall 08",
                    design_kw_capacity=300.00,
                    gross_area_sqm=400.0,
                    planned_rack_count=6,
                    status="LIVE",
                    committed_kw=999.00,
                    spare_kw=999.00,
                    version=42,
                ),
                FP,
            ),
            201,
        )
        assert_hall(hall)
        assert hall["status"] == "PLANNING", "the supplied LIVE is not a hall input"
        assert hall["committed_kw"] == pytest.approx(0.00, abs=0.005), (
            "committed load is the sum over the hall's live feeds, of which there are none"
        )
        assert hall["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005)
        assert hall["spare_kw"] == pytest.approx(275.00, abs=0.005), (
            "300.00 kW of design capacity less the 25.00 kW first reserve tier"
        )
        assert hall["version"] == 1, "the supplied 42 is not a hall input"

    def test_capacity_and_counter_fields_open_at_their_seeded_values(self):
        """A brand-new 400.00 kW room opens at the first reserve tier with spare
        375.00 kW, every cooling figure at 0.00 kW and all five counters at 0.

        PRD: "Creation seeds every derived field on the hall. The power ledger opens
        with `committed_kw` at 0.00 and `commissioning_reserve_kw` at 25.00 — the first
        reserve tier — so `spare_kw` opens at the design capacity less 25.00."
        PRD: "`chargeable_kw` and `thermal_load_kw` open at 0.00, as do
        `cooling_capacity_nameplate_kw`, `cooling_capacity_airflow_kw`,
        `cooling_capacity_kw` and `cooling_margin_kw`."
        PRD: "All five counters — `rack_total_count`, `custody_ops_count`,
        `custody_fitout_count`, `at_risk_rack_count` and `open_mop_count` — open at 0."

        Design: Corner/entities/hall_capacity_fields_default_to_zero_on_create
        """
        hall = validate_success(
            api_client.create_hall(
                self._hall_payload(
                    "CX09",
                    name="Corner Hall 09",
                    design_kw_capacity=400.00,
                    cooling_redundancy="N_PLUS_1",
                    planned_rack_count=10,
                ),
                FP,
            ),
            201,
        )
        assert_hall(hall)
        assert hall["committed_kw"] == pytest.approx(0.00, abs=0.005)
        assert hall["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005)
        assert hall["spare_kw"] == pytest.approx(375.00, abs=0.005)
        assert hall["chargeable_kw"] == pytest.approx(0.00, abs=0.005)
        assert hall["thermal_load_kw"] == pytest.approx(0.00, abs=0.005)
        assert hall["cooling_capacity_nameplate_kw"] == pytest.approx(0.00, abs=0.005)
        assert hall["cooling_capacity_airflow_kw"] == pytest.approx(0.00, abs=0.005)
        assert hall["cooling_capacity_kw"] == pytest.approx(0.00, abs=0.005)
        assert hall["cooling_margin_kw"] == pytest.approx(0.00, abs=0.005)
        assert hall["rack_total_count"] == 0
        assert hall["custody_ops_count"] == 0
        assert hall["custody_fitout_count"] == 0
        assert hall["at_risk_rack_count"] == 0
        assert hall["open_mop_count"] == 0


class TestTenantEntityContract:
    """A tenant books entitlement only through racks, so it is registered with an
    empty allocation."""

    def test_registration_opens_allocated_kw_at_zero(self):
        """A tenant registered before any rack exists reports allocated_kw 0.00
        against its 200.00 kW entitlement.

        PRD: "Tenants are registered separately by the same planner, with a legal
        `name`, a short `code`, the contracted electrical entitlement in
        `contracted_kw` (strictly positive, two decimal places) and the contract's ISO
        8601 UTC start instant in `contract_start_date`."
        PRD: "A tenant's `allocated_kw` opens at 0.00 and is thereafter always the sum
        of the designed density of every rack allocated to that tenant whose status is
        anything other than `PLANNED` — a planned rack position reserves floor space
        but books no entitlement."

        Design: Corner/entities/tenant_creation_defaults_allocated_kw_to_zero
        """
        tenant = validate_success(
            api_client.create_tenant(
                {
                    "name": "Northwind Systems",
                    "code": "CXT1",
                    "contracted_kw": 200.00,
                    "contract_start_date": CONTRACT_START,
                },
                FP,
            ),
            201,
        )
        assert_tenant(tenant)
        assert tenant["name"] == "Northwind Systems"
        assert tenant["code"] == "CXT1"
        assert tenant["contracted_kw"] == pytest.approx(200.00, abs=0.005)
        assert tenant["allocated_kw"] == pytest.approx(0.00, abs=0.005), (
            "no rack is allocated to the tenant yet"
        )
        assert tenant["version"] == 1


class TestElectricalChainEntityContracts:
    """The unit publishes its continuous-load ceiling on creation, the run inherits
    its white space and side from that unit, and the feed stores what the ledger
    will later read."""

    def test_new_unit_defaults_its_derate_and_publishes_its_usable_ceiling(self):
        """A unit added without a measured derate sits at PLANNED with
        measured_derate_factor 1.00 and usable_cap_kw 240.000 for a 300.00 kW
        nameplate.

        PRD: "A new unit sits at `PLANNED`, its `measured_derate_factor` defaults to
        1.00, and its `usable_cap_kw` is set immediately to the nameplate rating
        multiplied by the continuous-load factor of 0.80, rounded to three decimal
        places."

        Design: Corner/entities/pdu_defaults_measured_derate_factor_to_one
        """
        hall = create_hall("CX10", name="Corner Hall 10", design_kw_capacity=400.00)

        pdu = validate_success(
            api_client.create_pdu(
                {
                    "hall_id": hall["id"],
                    "name": "PDU-A1",
                    "feed_side": "A",
                    "rated_kw": 300.00,
                },
                EC,
            ),
            201,
        )
        assert_pdu(pdu)
        assert pdu["hall_id"] == hall["id"]
        assert pdu["feed_side"] == "A"
        assert pdu["status"] == "PLANNED"
        assert pdu["measured_derate_factor"] == pytest.approx(1.00, abs=0.005), (
            "the measured derate defaults to 1.00 until acceptance testing records one"
        )
        assert pdu["usable_cap_kw"] == pytest.approx(240.000, abs=0.0005), (
            "300.00 kW at the 0.80 continuous-load factor is 240.000 kW"
        )

    def test_unit_creation_against_an_unknown_hall_is_a_not_found(self):
        """A well-formed but unknown hall_id in the body is refused with
        ERR_HALL_NOT_FOUND and no unit is created.

        PRD: "On the create operations for power distribution units, busway runs,
        racks, rack feeds, cooling units, containment zones, cages, security devices,
        commissioning packages, load bank tests, methods of procedure and release
        packets, every supplied reference — `hall_id`, `tenant_id`, `pdu_id`,
        `busway_id`, `rack_id`, `containment_zone_id`, `cage_id`, `package_id`, and the
        `supersedes_packet_id` linkage where a prior packet is implicated — must
        resolve to an existing row, and the matching `ERR_<PARENT>_NOT_FOUND` is
        returned when it does not."
        PRD: "Each maps to its own 404: `ERR_HALL_NOT_FOUND`, `ERR_TENANT_NOT_FOUND`,
        `ERR_PDU_NOT_FOUND`, `ERR_BUSWAY_NOT_FOUND`, `ERR_CONTAINMENT_ZONE_NOT_FOUND`,
        `ERR_COOLING_UNIT_NOT_FOUND`, `ERR_CAGE_NOT_FOUND`,
        `ERR_SECURITY_DEVICE_NOT_FOUND`, `ERR_RACK_NOT_FOUND`,
        `ERR_RACK_FEED_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`,
        `ERR_LOAD_BANK_TEST_NOT_FOUND`, `ERR_MOP_NOT_FOUND` and
        `ERR_RELEASE_PACKET_NOT_FOUND`."

        Design: Corner/entities/pdu_parent_hall_must_exist_not_found
        """
        validate_error(
            api_client.create_pdu(
                {
                    "hall_id": NON_EXISTENT_UUID,
                    "name": "PDU-A1",
                    "feed_side": "A",
                    "rated_kw": 300.00,
                },
                EC,
            ),
            ApiErrorId.ERR_HALL_NOT_FOUND.value,
            404,
        )

        rows, meta = validate_paginated(api_client.list_pdus(EC))
        assert meta["total_count"] == 0, "the refused request created no unit"
        assert rows == []

    def test_new_run_inherits_its_white_space_and_side_from_its_unit(self):
        """A run created under the B-side unit of a hall in PLANNING publishes that
        hall, side B, raw_kw 273.136, the DESIGN variant and usable_kw 196.66 without
        either inherited value appearing in the request.

        PRD: "Two fields are inherited rather than supplied: the run's `hall_id` is
        copied from the parent unit's hall at creation and never changes thereafter, and
        its `feed_side` is likewise copied from the parent unit. A new run sits at
        `INSTALLED` with `committed_kw` at 0.000 and `feed_count` at 0."
        PRD: "The run's **raw** three-phase capacity, published as `raw_kw`, is the
        current rating multiplied by the line-to-line voltage, multiplied by the
        three-phase constant 1.732, multiplied by the power factor 0.95, then divided by
        1000 to convert volt-amperes to kilowatts, and rounded to three decimal places."
        PRD: "A busway created while its hall is in `PLANNING` or `FIT_OUT` records
        `usable_variant` as `DESIGN`; one created while the hall is in `COMMISSIONING`
        or `LIVE` records it as `COMMISSIONED`."

        Design: Corner/entities/busway_feed_side_and_hall_id_copied_from_pdu
        """
        hall = create_hall("CX11", name="Corner Hall 11", design_kw_capacity=400.00)
        pdu_b = create_pdu(hall["id"], "PDU-B1", "B", rated_kw=300.00)

        busway = validate_success(
            api_client.create_busway(
                {
                    "pdu_id": pdu_b["id"],
                    "name": "BW-B1",
                    "rated_amps": 400,
                    "voltage_v": 415,
                    "redundancy_topology": "N_PLUS_1",
                },
                EC,
            ),
            201,
        )
        assert_busway(busway)
        assert busway["hall_id"] == hall["id"], "the run's hall is copied from its unit"
        assert busway["feed_side"] == "B", "the run's side is copied from its unit"
        assert busway["pdu_id"] == pdu_b["id"]
        assert busway["raw_kw"] == pytest.approx(273.136, abs=0.0005), (
            "400 A at 415 V through 1.732 and 0.95 is 273.136 kW"
        )
        assert busway["usable_variant"] == "DESIGN", (
            "a run created while its hall is in PLANNING records the DESIGN variant"
        )
        assert busway["usable_kw"] == pytest.approx(196.66, abs=0.005), (
            "the N_PLUS_1 trunk figure of 196.658208 binds under the 240.000 unit ceiling"
        )
        assert busway["status"] == "INSTALLED"
        assert busway["committed_kw"] == pytest.approx(0.000, abs=0.0005)
        assert busway["feed_count"] == 0

    def test_new_feed_stores_its_rounded_allocation_and_the_runs_side(self):
        """A 7.50 kW reservation on the A-side run stores allocated_kw 7.500 at RESERVED
        with released_at null, carries the run's own side, and moves the run's committed
        load, the rack's connected load and the hall ledger with it.

        PRD: "What is stored is `allocated_kw`, the requested figure rounded to three
        decimal places, and that stored figure — not the request — is what all
        subsequent arithmetic uses. The `feed_side` recorded on the feed is copied from
        the named busway at creation, and the busway in turn inherited it from its
        upstream unit, so a feed's side is always the side of the electrical path that
        actually carries it. A new feed sits at `RESERVED` with `released_at` null."
        PRD: "On success the run's `committed_kw` grows by the allocation and its
        `feed_count` grows by one, the rack's `connected_kw` is re-derived, the hall
        power ledger is re-derived, and the hall's `version` increments."

        Design: Corner/entities/rack_feed_allocated_kw_and_feed_side_computed
        """
        ctx = setup_fit_out_hall("CX13", design_kw_capacity=400.00)
        rack = create_rack(
            ctx["hall_id"], ctx["zone_id"], "A", 1, design_kw=15.00
        )

        feed = validate_success(
            api_client.create_rack_feed(
                {
                    "rack_id": rack["id"],
                    "busway_id": ctx["bw_a"]["id"],
                    "feed_side": "A",
                    "requested_kw": 7.50,
                    "breaker_amps": 32,
                },
                EC,
            ),
            201,
        )
        assert_rack_feed(feed)
        assert feed["allocated_kw"] == pytest.approx(7.500, abs=0.0005), (
            "the stored allocation is the requested figure at three decimal places"
        )
        assert feed["feed_side"] == "A", "the side is copied from the named run"
        assert feed["status"] == "RESERVED"
        assert feed["released_at"] is None

        busway = validate_success(api_client.get_busway(ctx["bw_a"]["id"], EC), 200)
        assert busway["committed_kw"] == pytest.approx(7.500, abs=0.0005)
        assert busway["feed_count"] == 1

        stored_rack = validate_success(api_client.get_rack(rack["id"], EC), 200)
        assert stored_rack["connected_kw"] == pytest.approx(7.500, abs=0.0005)
        assert stored_rack["energized_feed_count"] == 0, (
            "the rack has not been powered on, so no feed is energised yet"
        )

        hall = read_hall(ctx["hall_id"])
        assert hall["committed_kw"] == pytest.approx(7.50, abs=0.005)
        assert hall["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005)
        assert hall["spare_kw"] == pytest.approx(367.50, abs=0.005)


class TestLayoutEntityContracts:
    """A rack position is placed with four optional fields and a fixed uplift, and it
    is the join between white space, aisle, cage and tenant."""

    def test_omitted_optional_placement_fields_take_their_declared_defaults(self):
        """A placement naming only hall, zone, coordinates and density comes back with
        u_height 42, required_feed_count 2, null cage, tenant and asset tag, and the
        seeded PLANNED figures.

        PRD: "`u_height` is the cabinet height in rack units and must be exactly 42, 45
        or 48, defaulting to 42. `required_feed_count` states how many energised feeds
        the position needs before it may take load, must be either 1 or 2, and defaults
        to 2 — dual-corded by default. `cage_id` places the position inside a tenant
        cage and defaults to null for facility-owned positions. `tenant_id` allocates
        the position to a tenant and defaults to null while unallocated. An `asset_tag`
        may be supplied at placement time but defaults to null."
        PRD: "A new position sits at `PLANNED` with `pre_risk_status` null,
        `connected_kw` at 0.000 and `energized_feed_count` at 0, and its `chargeable_kw`
        is fixed at creation as the designed density multiplied by the rack overhead
        factor of 1.045 — a four-and-a-half percent uplift covering in-cabinet losses —
        rounded to two decimal places."

        Design: Corner/entities/rack_defaults_required_feed_count_and_u_height
        """
        hall = create_hall("CX12", name="Corner Hall 12", design_kw_capacity=400.00)
        zone = create_zone(hall["id"], "CA-1")

        rack = validate_success(
            api_client.create_rack(
                {
                    "hall_id": hall["id"],
                    "containment_zone_id": zone["id"],
                    "grid_row": "A",
                    "grid_col": 1,
                    "design_kw": 10.00,
                },
                FP,
            ),
            201,
        )
        assert_rack(rack)
        assert rack["u_height"] == 42, "an omitted cabinet height defaults to 42 U"
        assert rack["required_feed_count"] == 2, "positions are dual-corded by default"
        assert rack["cage_id"] is None, "a facility-owned position names no cage"
        assert rack["tenant_id"] is None, "an unallocated position names no tenant"
        assert rack["asset_tag"] is None
        assert rack["status"] == "PLANNED"
        assert rack["pre_risk_status"] is None
        assert rack["connected_kw"] == pytest.approx(0.000, abs=0.0005)
        assert rack["energized_feed_count"] == 0
        assert rack["chargeable_kw"] == pytest.approx(10.45, abs=0.005), (
            "10.00 kW at the 1.045 rack overhead factor is 10.45 kW"
        )

        stored = read_hall(hall["id"])
        assert stored["rack_total_count"] == 1
        assert stored["custody_fitout_count"] == 1, (
            "a PLANNED position sits on the fit-out side of the custody partition"
        )
        assert stored["custody_ops_count"] == 0
        assert stored["chargeable_kw"] == pytest.approx(0.00, abs=0.005), (
            "PLANNED positions never contribute to the hall roll-up"
        )

    def test_position_is_addressable_through_each_of_its_four_references(self):
        """A position placed inside a cage and allocated to a tenant echoes all four
        references and is returned by a rack list narrowed on any one of them.

        PRD: "The placement payload names the `hall_id`, the aisle containment zone the
        cabinet sits in via `containment_zone_id`, and the floor coordinates `grid_row`
        and `grid_col`, and declares the designed density in `design_kw` (strictly
        positive, two decimal places)."
        PRD: "Rack lists may be narrowed by `hall_id`, `cage_id`,
        `containment_zone_id`, `tenant_id` and `status`."

        Design: Corner/entities/rack_graph_links_hall_zone_cage_and_tenant
        """
        hall = create_hall(
            "CX19",
            name="Corner Hall 19",
            tenant_mode="MULTI_TENANT",
            design_kw_capacity=400.00,
        )
        tenant = validate_success(
            api_client.create_tenant(
                {
                    "name": "Aurora Cloud",
                    "code": "CXT19",
                    "contracted_kw": 100.00,
                    "contract_start_date": CONTRACT_START,
                },
                FP,
            ),
            201,
        )
        zone = create_zone(hall["id"], "CA-1")
        cage = create_cage(hall["id"], tenant["id"], "CG-1")

        rack = create_rack(
            hall["id"],
            zone["id"],
            "A",
            1,
            design_kw=10.00,
            cage_id=cage["id"],
            tenant_id=tenant["id"],
        )
        assert_rack(rack)
        assert rack["hall_id"] == hall["id"]
        assert rack["containment_zone_id"] == zone["id"]
        assert rack["cage_id"] == cage["id"]
        assert rack["tenant_id"] == tenant["id"]

        for label, params in (
            ("hall_id", {"hall_id": hall["id"]}),
            ("containment_zone_id", {"containment_zone_id": zone["id"]}),
            ("cage_id", {"cage_id": cage["id"]}),
            ("tenant_id", {"tenant_id": tenant["id"]}),
        ):
            rows, meta = validate_paginated(api_client.list_racks(FP, params))
            assert meta["total_count"] == 1, (
                f"a rack list narrowed by {label} finds the position"
            )
            assert rows[0]["id"] == rack["id"]


class TestMechanicalEntityContracts:
    """Mechanical rows carry no measurements until they are actually tested, and an
    untested room contributes nothing to the hall's cooling model."""

    def test_new_unit_carries_no_measured_airflow_and_no_airflow_capacity(self):
        """A cooling unit declared with a 22000 cfm design airflow comes back INSTALLED
        with measured_airflow_cfm null and airflow_capacity_kw 0.00, and the hall's three
        cooling capacity figures stay at 0.00 because the duty set is empty.

        PRD: "A new unit stands at `INSTALLED` with `measured_airflow_cfm` null and
        `airflow_capacity_kw` at 0.00."
        PRD: "The duty set is every cooling unit of the hall whose status is
        `IN_SERVICE`; units at `MAINTENANCE`, `COMMISSIONED` or `INSTALLED` are
        excluded."

        Design: Corner/entities/cooling_unit_measured_airflow_null_until_commissioned
        """
        hall = create_hall("CX14", name="Corner Hall 14", design_kw_capacity=400.00)

        unit = validate_success(
            api_client.create_cooling_unit(
                {
                    "hall_id": hall["id"],
                    "name": "CU-1",
                    "rated_sensible_kw": 120.00,
                    "design_airflow_cfm": 22000,
                    "supply_delta_t_f": 18.0,
                    "redundancy_role": "PRIMARY",
                },
                MC,
            ),
            201,
        )
        assert_cooling_unit(unit)
        assert unit["hall_id"] == hall["id"]
        assert unit["rated_sensible_kw"] == pytest.approx(120.00, abs=0.005)
        assert unit["design_airflow_cfm"] == 22000
        assert unit["supply_delta_t_f"] == pytest.approx(18.0, abs=0.005)
        assert unit["redundancy_role"] == "PRIMARY"
        assert unit["status"] == "INSTALLED"
        assert unit["measured_airflow_cfm"] is None, (
            "nothing has been measured on a freshly declared unit"
        )
        assert unit["airflow_capacity_kw"] == pytest.approx(0.00, abs=0.005)

        stored = read_hall(hall["id"])
        assert stored["cooling_capacity_nameplate_kw"] == pytest.approx(0.00, abs=0.005)
        assert stored["cooling_capacity_airflow_kw"] == pytest.approx(0.00, abs=0.005)
        assert stored["cooling_capacity_kw"] == pytest.approx(0.00, abs=0.005), (
            "an INSTALLED unit is not in the duty set, so it lends no capacity"
        )

    def test_new_zone_carries_no_leakage_or_pressure_measurement(self):
        """A chimney-contained hot aisle comes back UNTESTED with test_count 0 and both
        measurement fields null, and the capacity summary reports worst_leakage_pct 0.00.

        PRD: "A new zone stands at `UNTESTED` with `test_count` at 0 and both
        `measured_leakage_pct` and `measured_static_pressure_pa` null."
        PRD: "The zones that count are those whose `leakage_status` is `PASS` or `FAIL`;
        zones at `UNTESTED` or `REMEDIATION` are excluded because they carry no current
        measurement."
        PRD: "Alongside the plain hall read, a computed capacity-summary read returns
        the whole reconciliation picture in one payload: `hall_id`, `status`,
        `design_kw_capacity`, `committed_kw`, `commissioning_reserve_kw`, `spare_kw`,
        `chargeable_kw`, `thermal_load_kw`, `cooling_capacity_nameplate_kw`,
        `cooling_capacity_airflow_kw`, `cooling_capacity_kw`, `cooling_margin_kw`,
        `thermal_posture`, `release_posture`, `rack_total_count`, `custody_ops_count`,
        `custody_fitout_count`, `at_risk_rack_count`, `open_mop_count`, and
        `worst_leakage_pct` — the highest measured leakage percentage currently selected
        across the hall's containment zones, or 0.00 when no zone currently contributes
        a measurement."

        Design: Corner/entities/containment_zone_measured_fields_null_until_tested
        """
        hall = create_hall("CX15", name="Corner Hall 15", design_kw_capacity=400.00)

        zone = validate_success(
            api_client.create_containment_zone(
                {
                    "hall_id": hall["id"],
                    "label": "HA-1",
                    "zone_type": "HOT_AISLE",
                    "containment_kind": "CHIMNEY",
                    "target_leakage_pct": 8.00,
                    "design_static_pressure_pa": 25.0,
                },
                MC,
            ),
            201,
        )
        assert_containment_zone(zone)
        assert zone["hall_id"] == hall["id"]
        assert zone["label"] == "HA-1"
        assert zone["zone_type"] == "HOT_AISLE"
        assert zone["containment_kind"] == "CHIMNEY"
        assert zone["target_leakage_pct"] == pytest.approx(8.00, abs=0.005)
        assert zone["design_static_pressure_pa"] == pytest.approx(25.0, abs=0.005)
        assert zone["leakage_status"] == "UNTESTED"
        assert zone["test_count"] == 0
        assert zone["measured_leakage_pct"] is None
        assert zone["measured_static_pressure_pa"] is None

        summary = read_capacity_summary(hall["id"])
        assert summary["worst_leakage_pct"] == pytest.approx(0.00, abs=0.005), (
            "no zone contributes a measurement yet"
        )


class TestSecurityEntityContracts:
    """A cage carries its two acceptance thresholds from build time and its devices
    contribute nothing until commissioned, but they are all listable."""

    def _multi_tenant_cage(self, hall_code, tenant_code, tenant_name):
        hall = create_hall(
            hall_code,
            name=f"Corner Hall {hall_code[-2:]}",
            tenant_mode="MULTI_TENANT",
            design_kw_capacity=400.00,
        )
        tenant = validate_success(
            api_client.create_tenant(
                {
                    "name": tenant_name,
                    "code": tenant_code,
                    "contracted_kw": 100.00,
                    "contract_start_date": CONTRACT_START,
                },
                FP,
            ),
            201,
        )
        return hall, tenant

    def test_omitted_acceptance_thresholds_take_their_declared_defaults(self):
        """A cage built with only hall, tenant, label and perimeter comes back requiring
        95.00 percent camera coverage and two reader zones, at FIT_OUT with no coverage
        and no live reader zone.

        PRD: "Two acceptance thresholds may be set at build time and both have defaults:
        `required_camera_coverage_pct`, the camera coverage the cage must reach before
        capacity inside it may be released (greater than 0 and at most 100.00, two
        decimal places, defaulting to 95.00), and `required_reader_zone_count`, the
        number of distinct access-control reader zones that must be live (at least 1,
        defaulting to 2). A new cage stands at `FIT_OUT` with `camera_coverage_pct` at
        0.00 and `active_reader_zone_count` at 0."

        Design: Corner/entities/cage_defaults_coverage_and_reader_requirements
        """
        hall, tenant = self._multi_tenant_cage("CX16", "CXT16", "Helios Data")

        cage = validate_success(
            api_client.create_cage(
                {
                    "hall_id": hall["id"],
                    "tenant_id": tenant["id"],
                    "label": "CG-1",
                    "perimeter_length_m": 40.0,
                },
                SA,
            ),
            201,
        )
        assert_cage(cage)
        assert cage["hall_id"] == hall["id"]
        assert cage["tenant_id"] == tenant["id"]
        assert cage["label"] == "CG-1"
        assert cage["perimeter_length_m"] == pytest.approx(40.0, abs=0.005)
        assert cage["required_camera_coverage_pct"] == pytest.approx(95.00, abs=0.005), (
            "an omitted coverage threshold defaults to 95.00 percent"
        )
        assert cage["required_reader_zone_count"] == 2, (
            "an omitted reader-zone requirement defaults to two zones"
        )
        assert cage["operational_status"] == "FIT_OUT"
        assert cage["camera_coverage_pct"] == pytest.approx(0.00, abs=0.005)
        assert cage["active_reader_zone_count"] == 0

    def test_device_list_narrows_by_cage_and_by_device_type(self):
        """A cage holding one camera and two card readers answers a list narrowed on cage
        and CARD_READER with exactly the two readers, and a list narrowed on the cage
        alone with all three devices, every one of them still PLANNED.

        PRD: "Every device starts at `PLANNED` and, crucially, contributes nothing at all
        to coverage while it is there — an installed but uncommissioned camera leaves
        coverage at 0.00. Device lists may be narrowed by `cage_id`, `device_type` and
        `status`."

        Design: Corner/entities/security_device_listing_filtered_by_cage_and_type
        """
        hall, tenant = self._multi_tenant_cage("CX17", "CXT17", "Meridian Compute")
        cage = validate_success(
            api_client.create_cage(
                {
                    "hall_id": hall["id"],
                    "tenant_id": tenant["id"],
                    "label": "CG-1",
                    "perimeter_length_m": 40.0,
                },
                SA,
            ),
            201,
        )
        camera = create_camera(cage["id"], "CAM-1", 38.0)
        reader_north = create_card_reader(cage["id"], "RDR-N", "Z-N")
        reader_south = create_card_reader(cage["id"], "RDR-S", "Z-S")

        readers, reader_meta = validate_paginated(
            api_client.list_security_devices(
                SA, {"cage_id": cage["id"], "device_type": "CARD_READER"}
            )
        )
        assert reader_meta["total_count"] == 2, (
            "the type filter excludes the camera of the same cage"
        )
        assert {row["label"] for row in readers} == {"RDR-N", "RDR-S"}
        assert {row["id"] for row in readers} == {
            reader_north["id"],
            reader_south["id"],
        }

        every, every_meta = validate_paginated(
            api_client.list_security_devices(SA, {"cage_id": cage["id"]})
        )
        assert every_meta["total_count"] == 3
        assert camera["id"] in {row["id"] for row in every}
        for row in every:
            assert_security_device(row)
            assert row["cage_id"] == cage["id"]
            assert row["status"] == "PLANNED", (
                "a planned device contributes nothing to coverage"
            )

        stored_cage = validate_success(api_client.get_cage(cage["id"], SA), 200)
        assert stored_cage["camera_coverage_pct"] == pytest.approx(0.00, abs=0.005), (
            "an installed but uncommissioned camera leaves coverage at 0.00"
        )


class TestChangeControlEntityContracts:
    """An approval record is the one row of the domain that carries no updated_at and
    no version, and the trail only ever grows."""

    def test_approval_trail_appends_immutable_records_in_creation_order(self):
        """A revision round leaves two approval records on the same MOP — the change
        manager's REQUEST_REVISION at sequence 1 and the operations manager's APPROVE at
        sequence 2 — each carrying the deciding headers and neither carrying updated_at
        or version.

        PRD: "The single exception is the method-of-procedure approval record: an
        approval row is immutable evidence and carries only `id` and `created_at`. It has
        no `updated_at` and no `version` at all."
        PRD: "Every decision appends an immutable approval record carrying the `mop_id`
        it decides, the `approver_role` and `approver_user_id` captured from the request
        headers, the `decision`, the `comment`, and a `sequence` that is the one-based
        position of this record among that MOP's approvals ordered by creation time."
        PRD: "Approval records are the audit trail of change control: they are never
        modified, they carry no `updated_at` and no `version`, and the only way to read
        them is the approval-trail listing of their MOP, returned in creation order."

        Design: Corner/entities/mop_approval_row_is_immutable_and_append_only
        """
        set_clock("2026-08-01T00:00:00Z")
        hall = create_hall("CX18", name="Corner Hall 18", design_kw_capacity=400.00)
        pdu = create_pdu(hall["id"], "PDU-A1", "A", rated_kw=300.00)
        busway = create_busway(pdu["id"], "BW-A1")

        mop = create_mop(
            hall["id"],
            "BUSWAY",
            busway["id"],
            title="Trunk tap addition",
            risk_class="LOW",
            window_start="2026-08-05T02:00:00Z",
            window_end="2026-08-05T04:00:00Z",
            role_headers=EC,
        )
        assert mop["status"] == "DRAFT"
        assert mop["revision_count"] == 0
        assert mop["approval_count"] == 0

        submit_mop(mop["id"], role_headers=EC)
        sent_back = approve_mop(
            mop["id"], role_headers=CM, decision="REQUEST_REVISION", comment="widen window"
        )
        assert sent_back["status"] == "REVISION_REQUESTED"
        assert sent_back["approval_count"] == 0, (
            "a REQUEST_REVISION closes the round, so the count falls back to 0"
        )

        revised = revise_mop(mop["id"], backout_plan="restore the tap and re-energise")
        assert revised["status"] == "UNDER_REVIEW"
        assert revised["revision_count"] == 1

        approved = approve_mop(
            mop["id"], role_headers=OM, decision="APPROVE", comment="content"
        )
        assert approved["status"] == "APPROVED"
        assert approved["approval_count"] == 1
        assert approved["revision_count"] == 1

        rows, meta = validate_paginated(api_client.list_mop_approvals(mop["id"], CM))
        assert meta["total_count"] == 2, "both decisions are still on the trail"
        for row in rows:
            assert_mop_approval(row)
            assert row["mop_id"] == mop["id"]
            assert "updated_at" not in row, (
                "an approval record carries no updated_at at all"
            )
            assert "version" not in row, "an approval record carries no version at all"

        first, second = rows[0], rows[1]
        assert first["sequence"] == 1, "the trail is returned in creation order"
        assert first["decision"] == "REQUEST_REVISION"
        assert first["approver_role"] == "ChangeManager"
        assert first["approver_user_id"] == CM["X-User-ID"]
        assert first["comment"] == "widen window"
        assert second["sequence"] == 2
        assert second["decision"] == "APPROVE"
        assert second["approver_role"] == "OperationsManager"
        assert second["approver_user_id"] == OM["X-User-ID"]
        assert second["comment"] == "content"
        assert read_mop(mop["id"])["status"] == "APPROVED", (
            "the trail records the decisions without re-opening the MOP"
        )
