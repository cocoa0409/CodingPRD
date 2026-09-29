"""Role-based access control: which persona owns which write surface, where the
shared read surface begins, and the identity checks that outlive the role header."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    make_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import USER_IDS
from test_helpers.fixtures import (
    CA,
    CM,
    EC,
    FP,
    MC,
    OM,
    SA,
    TENANT_REP,
    WA,
    create_busway,
    create_cage,
    create_camera,
    create_cooling_unit,
    create_hall,
    create_mop,
    create_pdu,
    create_rack,
    create_tenant,
    create_zone,
    read_busway,
    read_cage,
    read_cage_version,
    read_capacity_summary,
    read_cooling_unit,
    read_device,
    read_hall,
    read_hall_version,
    read_mop,
    read_pdu,
    read_rack,
    read_zone,
    set_clock,
    setup_fit_out_hall,
    submit_mop,
)


def _unauthorized(response):
    """Every refusal in this file is the same refusal: the role is known and simply
    not listed for the addressed operation."""
    return validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


class TestFacilityPlannerLayoutSurface:
    """Halls, tenants, rack placement, as-built tagging, installation and the phase
    ladder are the planner's alone, and no other staff role may reach them."""

    def _planning_layout(self):
        hall = create_hall("CX80", design_kw_capacity=400.00)
        zone = create_zone(hall["id"], "CA-1")
        rack = create_rack(hall["id"], zone["id"], "A", 1, design_kw=15.00)
        return {"hall": hall, "zone": zone, "rack": rack}

    def test_no_other_staff_role_may_touch_the_layout(self):
        """Hall creation, tenant registration, rack placement, as-built tagging and
        installation are each refused to a staff role that is not the planner, and the
        layout is untouched afterwards.

        PRD: "Authorization is enforced per endpoint against the caller's
        `X-User-Role` as described in §2.1, and the roles listed below are exhaustive
        — any other role receives `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/facility_planner_layout_surface_is_exclusive
        """
        ctx = self._planning_layout()

        _unauthorized(
            api_client.create_hall(
                {
                    "name": "White Space CX80B",
                    "code": "CX80B",
                    "tenant_mode": "SINGLE_TENANT",
                    "design_kw_capacity": 400.00,
                    "gross_area_sqm": 600.0,
                    "cooling_redundancy": "N",
                    "planned_rack_count": 40,
                },
                OM,
            )
        )
        _unauthorized(
            api_client.create_tenant(
                {
                    "name": "Tenant TN80X",
                    "code": "TN80X",
                    "contracted_kw": 80.00,
                    "contract_start_date": "2026-01-01T00:00:00Z",
                },
                SA,
            )
        )
        _unauthorized(
            api_client.create_rack(
                {
                    "hall_id": ctx["hall"]["id"],
                    "containment_zone_id": ctx["zone"]["id"],
                    "grid_row": "A",
                    "grid_col": 2,
                    "design_kw": 15.00,
                    "u_height": 45,
                    "required_feed_count": 2,
                },
                EC,
            )
        )
        _unauthorized(
            api_client.patch_rack(
                ctx["rack"]["id"], {"asset_tag": "AT-9999"}, OM
            )
        )
        _unauthorized(api_client.install_rack(ctx["rack"]["id"], {}, MC))

        rack = read_rack(ctx["rack"]["id"])
        assert rack["status"] == "PLANNED", "no refused call moved the position"
        assert rack["asset_tag"] in (None, ""), (
            "the refused tagging write left the as-built record empty"
        )
        _, halls_meta = validate_paginated(api_client.list_halls(FP))
        assert halls_meta["total_count"] == 1, "no second white space was created"
        _, tenants_meta = validate_paginated(api_client.list_tenants(FP))
        assert tenants_meta["total_count"] == 0, "no tenant was registered"
        _, racks_meta = validate_paginated(
            api_client.list_racks(FP, {"hall_id": ctx["hall"]["id"]})
        )
        assert racks_meta["total_count"] == 1, "the second position was never placed"

    def test_authorisation_on_the_phase_ladder_outranks_the_phase_prerequisites(self):
        """A ChangeManager driving the phase ladder is refused on the role, not on the
        missing electrical skeleton; the planner making the same call sees the
        prerequisite failure that was waiting underneath.

        PRD: "Authentication is therefore always decided before authorisation, and
        both are decided before anything else about the request is examined."

        Design: Corner/rbac/facility_planner_layout_surface_is_exclusive
        """
        ctx = self._planning_layout()

        _unauthorized(
            api_client.advance_hall_phase(
                ctx["hall"]["id"], {"target_status": "FIT_OUT"}, CM
            )
        )
        assert read_hall(ctx["hall"]["id"])["status"] == "PLANNING"

        validate_error(
            api_client.advance_hall_phase(
                ctx["hall"]["id"], {"target_status": "FIT_OUT"}, FP
            ),
            ApiErrorId.ERR_PHASE_PREREQ_NOT_MET.value,
            409,
        )
        assert read_hall(ctx["hall"]["id"])["status"] == "PLANNING", (
            "the hall has no power distribution unit on either feed side yet"
        )

    def test_the_planner_writes_while_the_staff_read_surface_stays_shared(self):
        """The same tagging write and tenant registration that every other role was
        refused succeed for the planner, and the resulting rows read back to roles
        that may not write them.

        PRD: "The eight staff roles listed above `TenantRepresentative` share the
        staff read surface: every list and detail read in §4 that names them, plus the
        administrative clock capability."

        Design: Corner/rbac/facility_planner_layout_surface_is_exclusive
        """
        ctx = self._planning_layout()

        tagged = validate_success(
            api_client.patch_rack(ctx["rack"]["id"], {"asset_tag": "AT-0401"}, FP)
        )
        assert tagged["asset_tag"] == "AT-0401"

        tenant = validate_success(
            api_client.create_tenant(
                {
                    "name": "Tenant TN80",
                    "code": "TN80",
                    "contracted_kw": 80.00,
                    "contract_start_date": "2026-01-01T00:00:00Z",
                },
                FP,
            ),
            201,
        )
        assert tenant["code"] == "TN80"
        assert tenant["allocated_kw"] == pytest.approx(0.00, abs=0.005)

        halls, _ = validate_paginated(api_client.list_halls(EC))
        assert [row["status"] for row in halls] == ["PLANNING"], (
            "an electrical contractor may read the layout it may not write"
        )
        assert read_rack(ctx["rack"]["id"], SA)["asset_tag"] == "AT-0401", (
            "a security administrator reads the as-built tag it may not write"
        )


class TestElectricalContractorPowerChain:
    """Distribution units, busway runs, branch feeds and rack energisation form one
    chain, and one role holds all of it."""

    def _planning_power_chain(self):
        hall = create_hall("CX81", design_kw_capacity=400.00)
        pdu = create_pdu(hall["id"], "PDU-A1", "A", rated_kw=300.00)
        busway = create_busway(pdu["id"], "BW-A1", rated_amps=400, voltage_v=415)
        zone = create_zone(hall["id"], "CA-1")
        rack = create_rack(hall["id"], zone["id"], "A", 1, design_kw=15.00)
        return {
            "hall": hall,
            "pdu": pdu,
            "busway": busway,
            "zone": zone,
            "rack": rack,
        }

    def test_no_other_role_may_build_derate_or_energise_the_chain(self):
        """Adding a unit, recording its derate, adding a run and energising that run are
        each refused to the mechanical contractor and to the planner, and the chain is
        left exactly as it was.

        PRD: "An `ElectricalContractor` owns the electrical chain: adding power
        distribution units, recording their measured derate factors, adding busway
        runs, energising them, reserving and releasing rack branch feeds, and powering
        racks on."

        Design: Corner/rbac/electrical_contractor_power_chain_is_exclusive
        """
        ctx = self._planning_power_chain()

        _unauthorized(
            api_client.create_pdu(
                {
                    "hall_id": ctx["hall"]["id"],
                    "name": "PDU-B1",
                    "feed_side": "B",
                    "rated_kw": 300.00,
                },
                MC,
            )
        )
        _unauthorized(
            api_client.patch_pdu(
                ctx["pdu"]["id"], {"measured_derate_factor": 0.97}, FP
            )
        )
        _unauthorized(
            api_client.create_busway(
                {
                    "pdu_id": ctx["pdu"]["id"],
                    "name": "BW-A2",
                    "rated_amps": 400,
                    "voltage_v": 415,
                    "redundancy_topology": "N_PLUS_1",
                },
                FP,
            )
        )
        _unauthorized(api_client.energize_busway(ctx["busway"]["id"], MC))

        pdu = read_pdu(ctx["pdu"]["id"])
        assert pdu["status"] == "PLANNED", "the refused derate write commissioned nothing"
        assert pdu["measured_derate_factor"] == pytest.approx(1.00, abs=0.005), (
            "the unit still carries the default derate it was born with"
        )
        busway = read_busway(ctx["busway"]["id"])
        assert busway["status"] == "INSTALLED", "the refused energisation moved nothing"
        _, pdus_meta = validate_paginated(
            api_client.list_pdus(FP, {"hall_id": ctx["hall"]["id"]})
        )
        assert pdus_meta["total_count"] == 1, "the B-side unit was never added"
        _, busways_meta = validate_paginated(
            api_client.list_busways(FP, {"hall_id": ctx["hall"]["id"]})
        )
        assert busways_meta["total_count"] == 1, "the second run was never added"

    def test_feeds_and_rack_energisation_are_refused_before_the_row_is_even_looked_up(
        self,
    ):
        """A commissioning agent may not reserve a feed or power a rack on, and a
        mechanical contractor releasing a feed identifier that does not exist is still
        told about the role rather than about the missing row.

        PRD: "If the role is recognised but is not among the roles authorised for the
        addressed operation in the endpoint table of §4, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403). Authentication is therefore always decided
        before authorisation, and both are decided before anything else about the
        request is examined."

        Design: Corner/rbac/electrical_contractor_power_chain_is_exclusive
        """
        ctx = self._planning_power_chain()

        _unauthorized(
            api_client.create_rack_feed(
                {
                    "rack_id": ctx["rack"]["id"],
                    "busway_id": ctx["busway"]["id"],
                    "feed_side": "A",
                    "requested_kw": 7.50,
                    "breaker_amps": 32,
                },
                CA,
            )
        )
        _unauthorized(api_client.delete_rack_feed(NON_EXISTENT_UUID, MC))
        _unauthorized(api_client.power_on_rack(ctx["rack"]["id"], CA))

        rows, meta = validate_paginated(
            api_client.list_rack_feeds(EC, {"rack_id": ctx["rack"]["id"]})
        )
        assert meta["total_count"] == 0 and rows == [], "no feed was reserved"
        rack = read_rack(ctx["rack"]["id"])
        assert rack["status"] == "PLANNED"
        assert rack["connected_kw"] == pytest.approx(0.000, abs=0.0005)

    def test_the_contractor_commissions_the_unit_and_others_only_read_it(self):
        """The derate write that every other role was refused lands for the electrical
        contractor, and the resulting unit and run read back to roles that could never
        have written them.

        PRD: "The eight staff roles listed above `TenantRepresentative` share the
        staff read surface: every list and detail read in §4 that names them, plus the
        administrative clock capability."

        Design: Corner/rbac/electrical_contractor_power_chain_is_exclusive
        """
        ctx = self._planning_power_chain()

        commissioned = validate_success(
            api_client.patch_pdu(
                ctx["pdu"]["id"], {"measured_derate_factor": 1.00}, EC
            )
        )
        assert commissioned["status"] == "COMMISSIONED"
        assert commissioned["measured_derate_factor"] == pytest.approx(1.00, abs=0.005)
        assert commissioned["usable_cap_kw"] == pytest.approx(240.000, abs=0.0005), (
            "300.00 kW at the 0.80 continuous-load factor is 240.000 kW"
        )

        busway = read_busway(ctx["busway"]["id"], MC)
        assert busway["status"] == "INSTALLED"
        assert busway["usable_variant"] == "DESIGN"
        assert busway["usable_kw"] == pytest.approx(196.66, abs=0.005), (
            "400 A at 415 V on an N+1 run sits under the 240.000 kW unit ceiling"
        )
        rows, meta = validate_paginated(
            api_client.list_busways(CA, {"hall_id": ctx["hall"]["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["name"] == "BW-A1", (
            "a commissioning agent reads the run it may not touch"
        )


class TestMechanicalContractorCoolingSurface:
    """Containment zones, their leakage tests, their remediation and the cooling units
    themselves are one surface owned by one role."""

    def _fit_out_mechanical_plant(self):
        return setup_fit_out_hall("CX82", design_kw_capacity=400.00)

    def test_no_other_role_may_build_prove_or_remediate_the_mechanical_plant(self):
        """Six mechanical writes — two creations, a commissioning, a placement into
        duty, a leakage test and a remediation — are each refused to roles outside the
        mechanical chain, and the plant is untouched.

        PRD: "Authorization is enforced per endpoint against the caller's
        `X-User-Role` as described in §2.1, and the roles listed below are exhaustive
        — any other role receives `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/mechanical_contractor_cooling_surface_is_exclusive
        """
        ctx = self._fit_out_mechanical_plant()

        _unauthorized(
            api_client.create_cooling_unit(
                {
                    "hall_id": ctx["hall_id"],
                    "name": "CU-2",
                    "rated_sensible_kw": 200.00,
                    "design_airflow_cfm": 22000,
                    "supply_delta_t_f": 18.0,
                    "redundancy_role": "PRIMARY",
                },
                EC,
            )
        )
        _unauthorized(
            api_client.commission_cooling_unit(
                ctx["cu_1"]["id"], {"measured_airflow_cfm": 22000}, CA
            )
        )
        _unauthorized(
            api_client.place_cooling_unit_in_service(ctx["cu_1"]["id"], OM)
        )
        _unauthorized(
            api_client.create_containment_zone(
                {
                    "hall_id": ctx["hall_id"],
                    "label": "CA-2",
                    "zone_type": "COLD_AISLE",
                    "containment_kind": "RIGID_ROOF",
                    "target_leakage_pct": 5.00,
                    "design_static_pressure_pa": 20.0,
                },
                EC,
            )
        )
        _unauthorized(
            api_client.leakage_test(
                ctx["zone_id"],
                {"measured_leakage_pct": 5.00, "measured_static_pressure_pa": 20.0},
                EC,
            )
        )
        _unauthorized(
            api_client.remediate_zone(
                ctx["zone_id"], {"remediation_note": "reseal the roof"}, SA
            )
        )

        zone = read_zone(ctx["zone_id"])
        assert zone["leakage_status"] == "UNTESTED", (
            "neither the refused test nor the refused remediation moved the zone"
        )
        assert zone["test_count"] == 0
        assert zone["measured_leakage_pct"] is None
        unit = read_cooling_unit(ctx["cu_1"]["id"])
        assert unit["status"] == "INSTALLED", "the unit was neither commissioned nor duty"
        assert unit["airflow_capacity_kw"] == pytest.approx(0.00, abs=0.005)
        _, zones_meta = validate_paginated(
            api_client.list_containment_zones(FP, {"hall_id": ctx["hall_id"]})
        )
        assert zones_meta["total_count"] == 1, "the second zone was never created"
        _, units_meta = validate_paginated(
            api_client.list_cooling_units(FP, {"hall_id": ctx["hall_id"]})
        )
        assert units_meta["total_count"] == 1, "the second unit was never created"

    def test_the_mechanical_contractor_proves_the_zone_and_commissions_the_unit(self):
        """The same leakage test and commissioning that every other role was refused
        succeed for the mechanical contractor, and the unit's airflow-derived capacity
        is computed against the leakage the zone has just measured.

        PRD §2.1: "A `MechanicalContractor` owns the mechanical chain: adding cooling
        units, commissioning them, placing them into duty, creating containment zones,
        running leakage tests and putting failed zones into remediation."

        PRD §3.5: "Each duty unit's `airflow_capacity_kw` is its
        `measured_airflow_cfm`, multiplied by one minus the hall's leakage fraction,
        multiplied by its `supply_delta_t_f`, multiplied by the airflow coefficient
        1.08, divided by 3412 to convert BTU per hour into kilowatts, and rounded to
        five decimal places."

        Design: Corner/rbac/mechanical_contractor_cooling_surface_is_exclusive
        """
        ctx = self._fit_out_mechanical_plant()

        tested = validate_success(
            api_client.leakage_test(
                ctx["zone_id"],
                {"measured_leakage_pct": 5.00, "measured_static_pressure_pa": 20.0},
                MC,
            )
        )
        assert tested["leakage_status"] == "PASS", (
            "5.00 percent against a 5.00 percent target and 20.0 Pa against an 18.00 Pa "
            "floor both satisfy inclusively"
        )
        assert tested["test_count"] == 1

        commissioned = validate_success(
            api_client.commission_cooling_unit(
                ctx["cu_1"]["id"], {"measured_airflow_cfm": 22000}, MC
            )
        )
        assert commissioned["status"] == "COMMISSIONED"
        assert commissioned["measured_airflow_cfm"] == 22000
        assert commissioned["airflow_capacity_kw"] == pytest.approx(
            119.07855, abs=0.000005
        ), "22000 cfm at 5 percent leakage and an 18.0 F delta-T is 119.07855 kW"

        rows, meta = validate_paginated(
            api_client.list_containment_zones(CA, {"hall_id": ctx["hall_id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["leakage_status"] == "PASS", (
            "a commissioning agent reads the verdict it may not record"
        )
        assert read_cooling_unit(ctx["cu_1"]["id"], EC)["status"] == "COMMISSIONED"


class TestCommissioningAgentAndWitnessAuthorityAreDisjoint:
    """The agent runs commissioning and opens handovers; the witness has exactly one
    write and it is not one of the agent's."""

    def _cage_in_a_planning_hall(self):
        hall = create_hall(
            "CX83", tenant_mode="MULTI_TENANT", design_kw_capacity=400.00
        )
        tenant = create_tenant("TN83", contracted_kw=80.00)
        cage = create_cage(hall["id"], tenant["id"], "CG-1", perimeter_length_m=40.0)
        return {"hall": hall, "tenant": tenant, "cage": cage}

    def test_the_witness_holds_none_of_the_agents_commissioning_writes(self):
        """Opening a package, approving a script, executing a script and scheduling a
        load bank run are all refused to the witness authority — the package create is
        refused on the role even though it carries a current hall version, and the two
        script writes are refused on the role even though they address a package that
        does not exist.

        PRD: "A `WitnessAuthority` exists only to witness executed commissioning
        packages. It has exactly one write capability and never executes a script —
        that separation is what makes a witness signature meaningful."

        Design: Corner/rbac/commissioning_agent_and_witness_authority_surfaces_are_disjoint
        """
        ctx = self._cage_in_a_planning_hall()
        hall_version = read_hall_version(ctx["hall"]["id"])

        _unauthorized(
            api_client.create_commissioning_package(
                {
                    "hall_id": ctx["hall"]["id"],
                    "level": "L1",
                    "title": "L1 integrated systems test",
                    "target_load_kw": 10.00,
                    "expected_hall_version": hall_version,
                },
                WA,
            )
        )
        _unauthorized(
            api_client.approve_script(
                NON_EXISTENT_UUID, {"script_revision": 1}, WA
            )
        )
        _unauthorized(api_client.execute_script(NON_EXISTENT_UUID, WA))
        _unauthorized(
            api_client.create_load_bank_test(
                {
                    "package_id": NON_EXISTENT_UUID,
                    "target_kw": 10.00,
                    "window_start": "2026-08-05T02:00:00Z",
                    "window_end": "2026-08-05T06:00:00Z",
                    "step_pct_sequence": [25, 50, 75, 100],
                },
                WA,
            )
        )

        _, meta = validate_paginated(
            api_client.list_commissioning_packages(
                CA, {"hall_id": ctx["hall"]["id"]}
            )
        )
        assert meta["total_count"] == 0, "the witness opened no package"
        assert read_hall_version(ctx["hall"]["id"]) == hall_version, (
            "a refused package create advances nothing on the hall"
        )

    def test_the_agent_may_not_sign_its_own_witness_decision(self):
        """The witness decision is refused to the commissioning agent on the role
        alone, before the package identifier is even resolved.

        PRD: "A `CommissioningAgent` owns phased commissioning: opening commissioning
        packages at levels `L1` through `L5`, approving and executing their scripts,
        scheduling, starting, completing and aborting load bank runs, and opening and
        submitting capacity-release packets."

        Design: Corner/rbac/commissioning_agent_and_witness_authority_surfaces_are_disjoint
        """
        self._cage_in_a_planning_hall()

        _unauthorized(
            api_client.witness_package(
                NON_EXISTENT_UUID, {"decision": "WITNESSED"}, CA
            )
        )
        _unauthorized(
            api_client.witness_package(
                NON_EXISTENT_UUID, {"decision": "REJECTED"}, OM
            )
        )

    def test_the_agent_opens_the_handover_that_operations_may_not(self):
        """Opening and submitting a release packet are refused to the operations
        manager and land for the commissioning agent, whose empty-scope packet reports
        zero racks and zero percent tagging rather than a vacuous hundred.

        PRD §2.1: "A `CommissioningAgent` owns phased commissioning: opening
        commissioning packages at levels `L1` through `L5`, approving and executing
        their scripts, scheduling, starting, completing and aborting load bank runs,
        and opening and submitting capacity-release packets."

        PRD §3.9: "When `rack_in_scope_count` is 0 the percentage is 0.00, **not**
        100.00: an empty scope is vacuously untagged, not vacuously complete."

        Design: Corner/rbac/commissioning_agent_and_witness_authority_surfaces_are_disjoint
        """
        ctx = self._cage_in_a_planning_hall()
        cage_version = read_cage_version(ctx["cage"]["id"])

        packet_payload = {
            "hall_id": ctx["hall"]["id"],
            "cage_id": ctx["cage"]["id"],
            "as_built_drawing_ref": "AB-CX83-1",
            "expected_cage_version": cage_version,
        }
        _unauthorized(api_client.create_release_packet(packet_payload, OM))
        _unauthorized(api_client.submit_release_packet(NON_EXISTENT_UUID, OM))

        packet = validate_success(
            api_client.create_release_packet(packet_payload, CA), 201
        )
        assert packet["status"] == "DRAFT"
        assert packet["rack_in_scope_count"] == 0
        assert packet["asset_tag_completion_pct"] == pytest.approx(0.00, abs=0.005)
        assert packet["released_kw"] == pytest.approx(0.00, abs=0.005)

        rows, meta = validate_paginated(
            api_client.list_release_packets(FP, {"cage_id": ctx["cage"]["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == packet["id"]


class TestChangeControlAndReleaseAcceptanceAreDisjoint:
    """The chair and the operations manager sit side by side on the approval quorum and
    then part company: only one schedules, and only the other accepts custody."""

    def _two_submitted_mops(self):
        set_clock("2026-08-01T00:00:00Z")
        hall = create_hall("CX84", design_kw_capacity=400.00)
        pdu = create_pdu(hall["id"], "PDU-A1", "A", rated_kw=300.00)
        bw_1 = create_busway(pdu["id"], "BW-A1", rated_amps=400, voltage_v=415)
        bw_2 = create_busway(pdu["id"], "BW-A2", rated_amps=400, voltage_v=415)
        mop_1 = create_mop(
            hall["id"],
            "BUSWAY",
            bw_1["id"],
            title="Isolate BW-A1",
            risk_class="MEDIUM",
            role_headers=EC,
            author_user_id=USER_IDS["ELECTRICAL_CONTRACTOR"],
        )
        submit_mop(
            mop_1["id"], USER_IDS["ELECTRICAL_CONTRACTOR"], role_headers=EC
        )
        mop_2 = create_mop(
            hall["id"],
            "BUSWAY",
            bw_2["id"],
            title="Isolate BW-A2",
            risk_class="MEDIUM",
            role_headers=MC,
            author_user_id=USER_IDS["MECHANICAL_CONTRACTOR"],
        )
        submit_mop(
            mop_2["id"], USER_IDS["MECHANICAL_CONTRACTOR"], role_headers=MC
        )
        return {"hall": hall, "mop_1": mop_1, "mop_2": mop_2}

    def test_the_quorum_is_the_two_peer_approvers_and_nobody_else(self):
        """A commissioning agent cannot vote at all, while a single vote from either
        peer approver carries a MEDIUM risk MOP to APPROVED.

        PRD: "**Approval decisions** are recorded by a `ChangeManager` or an
        `OperationsManager` as peer approvers, each decision naming a `decision` of
        `APPROVE`, `REQUEST_REVISION` or `REJECT` and optionally a `comment`."

        Design: Corner/rbac/change_control_scheduling_and_release_acceptance_are_disjoint_surfaces
        """
        ctx = self._two_submitted_mops()

        _unauthorized(
            api_client.create_mop_approval(
                ctx["mop_1"]["id"],
                {"decision": "APPROVE", "comment": "not my vote"},
                CA,
            )
        )
        assert read_mop(ctx["mop_1"]["id"])["status"] == "UNDER_REVIEW"
        assert read_mop(ctx["mop_1"]["id"])["approval_count"] == 0

        by_chair = validate_success(
            api_client.create_mop_approval(
                ctx["mop_1"]["id"], {"decision": "APPROVE", "comment": "approved"}, CM
            )
        )
        assert by_chair["status"] == "APPROVED"
        assert by_chair["approval_count"] == 1
        assert by_chair["required_approval_count"] == 1, (
            "a MEDIUM risk MOP needs exactly one APPROVE"
        )

        by_operations = validate_success(
            api_client.create_mop_approval(
                ctx["mop_2"]["id"], {"decision": "APPROVE", "comment": "approved"}, OM
            )
        )
        assert by_operations["status"] == "APPROVED"
        assert by_operations["approval_count"] == 1

    def test_scheduling_is_the_chairs_alone_and_approving_does_not_confer_it(self):
        """The operations manager whose vote just approved a MOP still cannot schedule
        it; the chair can, and the MOP only then leaves APPROVED.

        PRD: "**Scheduling** is the `ChangeManager`'s exclusive act and advances an
        approved MOP `APPROVED → SCHEDULED`."

        Design: Corner/rbac/change_control_scheduling_and_release_acceptance_are_disjoint_surfaces
        """
        ctx = self._two_submitted_mops()
        approved = validate_success(
            api_client.create_mop_approval(
                ctx["mop_2"]["id"], {"decision": "APPROVE", "comment": "approved"}, OM
            )
        )
        assert approved["status"] == "APPROVED"

        _unauthorized(api_client.schedule_mop(ctx["mop_2"]["id"], {}, OM))
        assert read_mop(ctx["mop_2"]["id"])["status"] == "APPROVED", (
            "casting the deciding vote does not carry the scheduling capability"
        )

        scheduled = validate_success(
            api_client.schedule_mop(ctx["mop_2"]["id"], {}, CM)
        )
        assert scheduled["status"] == "SCHEDULED"

    def test_custody_acceptance_is_operations_and_never_the_chairs(self):
        """Accepting and rejecting a capacity handover are refused to the chair and to
        the commissioning agent on the role alone, ahead of resolving the packet.

        PRD: "An `OperationsManager` accepts or rejects capacity handover to
        operations and is the second peer approver on method-of-procedure decisions."

        Design: Corner/rbac/change_control_scheduling_and_release_acceptance_are_disjoint_surfaces
        """
        self._two_submitted_mops()

        _unauthorized(api_client.accept_release_packet(NON_EXISTENT_UUID, CM))
        _unauthorized(
            api_client.reject_release_packet(
                NON_EXISTENT_UUID, {"rejected_reason": "paperwork short"}, CA
            )
        )


class TestSecurityAdministratorOwnsCagesAndDevices:
    """Cages, cameras, card readers and their commissioning are one role's
    infrastructure, and everybody else only looks at it."""

    def _cage_with_a_planned_camera(self):
        hall = create_hall(
            "CX85", tenant_mode="MULTI_TENANT", design_kw_capacity=400.00
        )
        tenant = create_tenant("TN85", contracted_kw=80.00)
        cage = create_cage(hall["id"], tenant["id"], "CG-1", perimeter_length_m=40.0)
        camera = create_camera(cage["id"], "CAM-1", 40.0)
        return {"hall": hall, "tenant": tenant, "cage": cage, "camera": camera}

    def test_nobody_else_builds_a_cage_or_activates_its_devices(self):
        """Cage creation, device planning and device commissioning are refused to the
        planner, the mechanical contractor, the commissioning agent and the operations
        manager alike, and the cage's coverage stays at zero.

        PRD: "A `SecurityAdministrator` builds security infrastructure: tenant cages,
        cameras and card readers, and the commissioning of those devices."

        Design: Corner/rbac/security_administrator_owns_cages_and_device_commissioning
        """
        ctx = self._cage_with_a_planned_camera()

        _unauthorized(
            api_client.create_cage(
                {
                    "hall_id": ctx["hall"]["id"],
                    "tenant_id": ctx["tenant"]["id"],
                    "label": "CG-2",
                    "perimeter_length_m": 40.0,
                },
                FP,
            )
        )
        _unauthorized(
            api_client.create_security_device(
                {
                    "cage_id": ctx["cage"]["id"],
                    "device_type": "CARD_READER",
                    "label": "RD-1",
                    "reader_zone_label": "Z-N",
                },
                MC,
            )
        )
        _unauthorized(
            api_client.commission_security_device(ctx["camera"]["id"], CA)
        )
        _unauthorized(
            api_client.commission_security_device(ctx["camera"]["id"], OM)
        )

        assert read_device(ctx["camera"]["id"], FP)["status"] == "PLANNED", (
            "the camera is still merely planned"
        )
        cage = read_cage(ctx["cage"]["id"])
        assert cage["camera_coverage_pct"] == pytest.approx(0.00, abs=0.005)
        assert cage["active_reader_zone_count"] == 0
        assert cage["operational_status"] == "FIT_OUT"
        _, cages_meta = validate_paginated(
            api_client.list_cages(FP, {"hall_id": ctx["hall"]["id"]})
        )
        assert cages_meta["total_count"] == 1, "the second cage was never built"
        _, devices_meta = validate_paginated(
            api_client.list_security_devices(FP, {"cage_id": ctx["cage"]["id"]})
        )
        assert devices_meta["total_count"] == 1, "the card reader was never planned"

    def test_the_administrators_commissioning_republishes_the_cage_coverage(self):
        """The commissioning that four other roles were refused activates the camera for
        the security administrator and republishes full camera coverage, while the cage
        stays at FIT_OUT because the reader-zone floor is still unmet.

        PRD §2.1: "A `SecurityAdministrator` builds security infrastructure: tenant
        cages, cameras and card readers, and the commissioning of those devices."

        PRD §3.6: "When the re-derived coverage reaches or exceeds
        `required_camera_coverage_pct` and the re-derived distinct reader-zone count
        reaches or exceeds `required_reader_zone_count`, and the cage is still at
        `FIT_OUT`, the cage advances `FIT_OUT → SECURED` in that same request."

        Design: Corner/rbac/security_administrator_owns_cages_and_device_commissioning
        """
        ctx = self._cage_with_a_planned_camera()

        activated = validate_success(
            api_client.commission_security_device(ctx["camera"]["id"], SA)
        )
        assert activated["status"] == "ACTIVE"

        cage = read_cage(ctx["cage"]["id"])
        assert cage["camera_coverage_pct"] == pytest.approx(100.00, abs=0.005), (
            "40.0 m of covered length over a 40.0 m perimeter is full coverage"
        )
        assert cage["active_reader_zone_count"] == 0
        assert cage["operational_status"] == "FIT_OUT", (
            "the camera floor alone does not secure a cage; both floors must be met"
        )


class TestTenantRepresentativeIsReadOnly:
    """The tenant-side observer writes nothing at all and reads a strictly smaller
    surface than the eight staff roles."""

    def _tenant_occupied_hall(self):
        hall = create_hall(
            "CX86", tenant_mode="MULTI_TENANT", design_kw_capacity=400.00
        )
        tenant = create_tenant("TN86", contracted_kw=80.00)
        cage = create_cage(hall["id"], tenant["id"], "CG-1", perimeter_length_m=40.0)
        zone = create_zone(hall["id"], "CA-1")
        rack = create_rack(
            hall["id"],
            zone["id"],
            "A",
            1,
            design_kw=8.00,
            cage_id=cage["id"],
            tenant_id=tenant["id"],
            asset_tag="AT-0501",
        )
        return {
            "hall": hall,
            "tenant": tenant,
            "cage": cage,
            "zone": zone,
            "rack": rack,
            "headers": TENANT_REP(tenant["id"]),
        }

    def test_the_observer_holds_no_write_capability_whatsoever(self):
        """Placing a rack, correcting its tag, building a cage, drafting a method of
        procedure and opening a release packet are all refused to the tenant's own
        representative, even for rows the tenant owns.

        PRD: "A `TenantRepresentative` is a read-only tenant-side observer with no
        write capability at all."

        Design: Corner/rbac/tenant_representative_is_read_only_and_off_the_staff_read_surface
        """
        ctx = self._tenant_occupied_hall()
        headers = ctx["headers"]

        _unauthorized(
            api_client.create_rack(
                {
                    "hall_id": ctx["hall"]["id"],
                    "containment_zone_id": ctx["zone"]["id"],
                    "grid_row": "A",
                    "grid_col": 2,
                    "design_kw": 8.00,
                    "u_height": 45,
                    "required_feed_count": 2,
                },
                headers,
            )
        )
        _unauthorized(
            api_client.patch_rack(ctx["rack"]["id"], {"asset_tag": "AT-9999"}, headers)
        )
        _unauthorized(
            api_client.create_cage(
                {
                    "hall_id": ctx["hall"]["id"],
                    "tenant_id": ctx["tenant"]["id"],
                    "label": "CG-2",
                    "perimeter_length_m": 40.0,
                },
                headers,
            )
        )
        _unauthorized(
            api_client.create_mop(
                {
                    "hall_id": ctx["hall"]["id"],
                    "target_resource_type": "RACK",
                    "target_resource_id": ctx["rack"]["id"],
                    "title": "Tenant works",
                    "risk_class": "LOW",
                    "backout_plan": "restore the prior configuration",
                    "window_start": "2026-08-10T02:00:00Z",
                    "window_end": "2026-08-10T06:00:00Z",
                },
                headers,
            )
        )
        _unauthorized(
            api_client.create_release_packet(
                {
                    "hall_id": ctx["hall"]["id"],
                    "cage_id": ctx["cage"]["id"],
                    "as_built_drawing_ref": "AB-CX86-1",
                    "expected_cage_version": read_cage_version(ctx["cage"]["id"]),
                },
                headers,
            )
        )

        assert read_rack(ctx["rack"]["id"])["asset_tag"] == "AT-0501", (
            "the refused tagging write did not overwrite the as-built record"
        )
        _, racks_meta = validate_paginated(
            api_client.list_racks(FP, {"hall_id": ctx["hall"]["id"]})
        )
        assert racks_meta["total_count"] == 1
        _, cages_meta = validate_paginated(
            api_client.list_cages(FP, {"hall_id": ctx["hall"]["id"]})
        )
        assert cages_meta["total_count"] == 1
        _, mops_meta = validate_paginated(
            api_client.list_mops(FP, {"hall_id": ctx["hall"]["id"]})
        )
        assert mops_meta["total_count"] == 0
        _, packets_meta = validate_paginated(
            api_client.list_release_packets(FP, {"hall_id": ctx["hall"]["id"]})
        )
        assert packets_meta["total_count"] == 0

    def test_the_observer_is_off_the_staff_read_surface(self):
        """The tenant list, the distribution-unit surface and the feed surface are staff
        reads, and the tenant's representative is refused all three.

        PRD: "`TenantRepresentative` may read halls (list and detail), the
        capacity-summary view of a hall, a single tenant, racks (list and detail),
        cages (list and detail) and release packets (list and detail) — nothing else."

        Design: Corner/rbac/tenant_representative_is_read_only_and_off_the_staff_read_surface
        """
        ctx = self._tenant_occupied_hall()
        headers = ctx["headers"]

        _unauthorized(api_client.list_tenants(headers))
        _unauthorized(api_client.list_pdus(headers, {"hall_id": ctx["hall"]["id"]}))
        _unauthorized(api_client.list_rack_feeds(headers, {"rack_id": ctx["rack"]["id"]}))

    def test_the_observer_reads_exactly_the_surfaces_it_is_granted(self):
        """Its own rack, its own cage, its own tenant row, the hall it occupies and that
        hall's capacity summary all read back for the tenant's representative.

        PRD: "`TenantRepresentative` may read halls (list and detail), the
        capacity-summary view of a hall, a single tenant, racks (list and detail),
        cages (list and detail) and release packets (list and detail) — nothing else."

        Design: Corner/rbac/tenant_representative_is_read_only_and_off_the_staff_read_surface
        """
        ctx = self._tenant_occupied_hall()
        headers = ctx["headers"]

        assert read_rack(ctx["rack"]["id"], headers)["asset_tag"] == "AT-0501"
        assert read_cage(ctx["cage"]["id"], headers)["label"] == "CG-1"
        tenant = validate_success(
            api_client.get_tenant(ctx["tenant"]["id"], headers)
        )
        assert tenant["code"] == "TN86"
        assert read_hall(ctx["hall"]["id"], headers)["code"] == "CX86"
        summary = read_capacity_summary(ctx["hall"]["id"], headers)
        assert summary["rack_total_count"] == 1, (
            "the tenant owns a rack in this hall, so the summary is open to it"
        )
        halls, halls_meta = validate_paginated(api_client.list_halls(headers))
        assert halls_meta["total_count"] == 1
        assert halls[0]["code"] == "CX86"


class TestMopAuthoringIsSharedByBothContractors:
    """Drafting a method of procedure is the one write surface the two contractor roles
    hold jointly, and change control holds none of it."""

    def _hall_with_two_mop_targets(self):
        set_clock("2026-08-01T00:00:00Z")
        hall = create_hall("CX87", design_kw_capacity=400.00)
        pdu = create_pdu(hall["id"], "PDU-A1", "A", rated_kw=300.00)
        busway = create_busway(pdu["id"], "BW-A1", rated_amps=400, voltage_v=415)
        unit = create_cooling_unit(hall["id"], "CU-1")
        return {"hall": hall, "pdu": pdu, "busway": busway, "unit": unit}

    def _mop_payload(self, hall_id, target_type, target_id, title):
        return {
            "hall_id": hall_id,
            "target_resource_type": target_type,
            "target_resource_id": target_id,
            "title": title,
            "risk_class": "LOW",
            "backout_plan": "restore the prior configuration",
            "window_start": "2026-08-10T02:00:00Z",
            "window_end": "2026-08-10T06:00:00Z",
        }

    def test_either_contractor_may_author_and_submit_its_own_mop(self):
        """The electrical contractor drafts against a busway and the mechanical
        contractor against a cooling unit; each MOP is stamped with its own author and
        each author submits its own draft into review.

        PRD §3.8: "An `ElectricalContractor` or a `MechanicalContractor` drafts one
        against exactly one target resource, naming the `hall_id`, the
        `target_resource_type` (`BUSWAY`, `COOLING_UNIT`, `CONTAINMENT_ZONE` or
        `RACK`), the `target_resource_id`, a `title`, the `risk_class` (`LOW`, `MEDIUM`
        or `HIGH`), a written `backout_plan`, and the intended `window_start` and
        `window_end`."

        PRD §3.8: "A new MOP stands at `DRAFT` with `author_user_id` stamped from the
        drafting `X-User-ID`, `revision_count` at 0, `approval_count` at 0,
        `required_approval_count` at 0, `tenant_notified_ids` empty, and
        `pre_execution_target_state`, `executed_at` and `closed_at` all null."

        Design: Corner/rbac/mop_authoring_is_shared_between_both_contractor_roles
        """
        ctx = self._hall_with_two_mop_targets()

        electrical = validate_success(
            api_client.create_mop(
                self._mop_payload(
                    ctx["hall"]["id"], "BUSWAY", ctx["busway"]["id"], "Isolate BW-A1"
                ),
                EC,
            ),
            201,
        )
        assert electrical["status"] == "DRAFT"
        assert electrical["author_user_id"] == USER_IDS["ELECTRICAL_CONTRACTOR"]
        assert electrical["revision_count"] == 0
        assert electrical["approval_count"] == 0
        assert electrical["required_approval_count"] == 0

        mechanical = validate_success(
            api_client.create_mop(
                self._mop_payload(
                    ctx["hall"]["id"], "COOLING_UNIT", ctx["unit"]["id"], "Swap CU-1"
                ),
                MC,
            ),
            201,
        )
        assert mechanical["status"] == "DRAFT"
        assert mechanical["author_user_id"] == USER_IDS["MECHANICAL_CONTRACTOR"]

        submitted_electrical = validate_success(
            api_client.submit_mop(electrical["id"], EC)
        )
        assert submitted_electrical["status"] == "UNDER_REVIEW"
        assert submitted_electrical["required_approval_count"] == 1, (
            "a LOW risk MOP needs one APPROVE"
        )
        submitted_mechanical = validate_success(
            api_client.submit_mop(mechanical["id"], MC)
        )
        assert submitted_mechanical["status"] == "UNDER_REVIEW"

        rows, meta = validate_paginated(
            api_client.list_mops(FP, {"hall_id": ctx["hall"]["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["author_user_id"] for row in rows} == {
            USER_IDS["ELECTRICAL_CONTRACTOR"],
            USER_IDS["MECHANICAL_CONTRACTOR"],
        }

    def test_the_change_control_roles_may_not_author_a_mop_at_all(self):
        """The chair and the operations manager decide methods of procedure but may not
        write one, so no MOP exists for them to decide.

        PRD: "An `ElectricalContractor` or a `MechanicalContractor` drafts one against
        exactly one target resource, naming the `hall_id`, the `target_resource_type`
        (`BUSWAY`, `COOLING_UNIT`, `CONTAINMENT_ZONE` or `RACK`), the
        `target_resource_id`, a `title`, the `risk_class` (`LOW`, `MEDIUM` or `HIGH`),
        a written `backout_plan`, and the intended `window_start` and `window_end`."

        Design: Corner/rbac/mop_authoring_is_shared_between_both_contractor_roles
        """
        ctx = self._hall_with_two_mop_targets()
        payload = self._mop_payload(
            ctx["hall"]["id"], "BUSWAY", ctx["busway"]["id"], "Isolate BW-A1"
        )

        _unauthorized(api_client.create_mop(payload, CM))
        _unauthorized(api_client.create_mop(payload, OM))

        _, meta = validate_paginated(
            api_client.list_mops(FP, {"hall_id": ctx["hall"]["id"]})
        )
        assert meta["total_count"] == 0, "change control authored nothing"


class TestSegregationOfDutiesBindsIdentityNotRole:
    """The role header decides what an endpoint will accept; the acting identity decides
    whether the quorum is real."""

    def _submitted_high_risk_mop(self):
        set_clock("2026-08-01T00:00:00Z")
        hall = create_hall("CX88", design_kw_capacity=400.00)
        pdu = create_pdu(hall["id"], "PDU-A1", "A", rated_kw=300.00)
        busway = create_busway(pdu["id"], "BW-A1", rated_amps=400, voltage_v=415)
        mop = create_mop(
            hall["id"],
            "BUSWAY",
            busway["id"],
            title="Isolate BW-A1",
            risk_class="HIGH",
            role_headers=EC,
            author_user_id=USER_IDS["ELECTRICAL_CONTRACTOR"],
        )
        submit_mop(mop["id"], USER_IDS["ELECTRICAL_CONTRACTOR"], role_headers=EC)
        return {"hall": hall, "busway": busway, "mop": mop}

    def test_the_author_cannot_approve_by_putting_on_an_approver_role(self):
        """The author's own identity arriving under an OperationsManager role header is
        an authorised call that is still refused, because the check compares identities
        and not role names.

        PRD: "The approving `X-User-ID` may never equal the MOP's `author_user_id` — an
        author approving their own change is refused with `ERR_APPROVER_IS_AUTHOR`."

        Design: Corner/rbac/segregation_of_duties_binds_user_identity_not_role_header
        """
        ctx = self._submitted_high_risk_mop()
        author_as_operations = make_headers(
            USER_IDS["ELECTRICAL_CONTRACTOR"], "OperationsManager"
        )

        validate_error(
            api_client.create_mop_approval(
                ctx["mop"]["id"],
                {"decision": "APPROVE", "comment": "my own change"},
                author_as_operations,
            ),
            ApiErrorId.ERR_APPROVER_IS_AUTHOR.value,
            422,
        )

        mop = read_mop(ctx["mop"]["id"])
        assert mop["status"] == "UNDER_REVIEW"
        assert mop["approval_count"] == 0
        assert mop["required_approval_count"] == 2, "a HIGH risk MOP needs two APPROVEs"
        _, trail_meta = validate_paginated(
            api_client.list_mop_approvals(ctx["mop"]["id"], FP)
        )
        assert trail_meta["total_count"] == 0, "a refused decision appends no record"

    def test_one_individual_cannot_manufacture_the_quorum_by_swapping_roles(self):
        """The chair's first vote counts; the same individual voting again under the
        other approver role is refused on the duplicate identity, not admitted on the
        distinct role; a genuinely second individual completes the quorum.

        PRD: "No `approver_user_id` may appear twice among the `APPROVE` decisions of
        the current review round, so one person cannot manufacture a two-vote quorum; a
        second vote from the same individual is refused with `ERR_DUPLICATE_APPROVER`."

        Design: Corner/rbac/segregation_of_duties_binds_user_identity_not_role_header
        """
        ctx = self._submitted_high_risk_mop()

        first = validate_success(
            api_client.create_mop_approval(
                ctx["mop"]["id"],
                {"decision": "APPROVE", "comment": "chair approves"},
                make_headers(USER_IDS["CHANGE_MANAGER"], "ChangeManager"),
            )
        )
        assert first["status"] == "UNDER_REVIEW", "one of two APPROVEs is not a quorum"
        assert first["approval_count"] == 1

        validate_error(
            api_client.create_mop_approval(
                ctx["mop"]["id"],
                {"decision": "APPROVE", "comment": "same person, other hat"},
                make_headers(USER_IDS["CHANGE_MANAGER"], "OperationsManager"),
            ),
            ApiErrorId.ERR_DUPLICATE_APPROVER.value,
            409,
        )
        held = read_mop(ctx["mop"]["id"])
        assert held["status"] == "UNDER_REVIEW"
        assert held["approval_count"] == 1, (
            "the second hat bought no second vote"
        )

        second = validate_success(
            api_client.create_mop_approval(
                ctx["mop"]["id"],
                {"decision": "APPROVE", "comment": "operations approves"},
                make_headers(USER_IDS["OPERATIONS_MANAGER"], "OperationsManager"),
            )
        )
        assert second["status"] == "APPROVED"
        assert second["approval_count"] == 2

        trail, trail_meta = validate_paginated(
            api_client.list_mop_approvals(ctx["mop"]["id"], FP)
        )
        assert trail_meta["total_count"] == 2, "only the two accepted votes are recorded"
        assert [row["sequence"] for row in trail] == [1, 2]
        assert [row["approver_user_id"] for row in trail] == [
            USER_IDS["CHANGE_MANAGER"],
            USER_IDS["OPERATIONS_MANAGER"],
        ]
