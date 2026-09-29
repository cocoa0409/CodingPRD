"""Authentication, the role partition, and the two segregation-of-duties rules."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    ADMIN,
    AUDIT_INSPECTOR,
    AUDIT_INSPECTOR_1,
    CAPTAIN_1,
    CAPTAIN_2,
    DG_OFFICER_1,
    LOAD_CONTROLLER,
    RAMP_AGENT,
    api_client,
)
from test_helpers import ApiErrorId as E
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    HEADERS_BY_ROLE,
    ROLE_LOAD_CONTROLLER,
    audit_inspector_headers,
    captain_headers,
    headers_for,
    headers_missing_role,
    no_auth_headers,
    undeclared_role_headers,
)

_SPECS = {spec["code"]: spec for spec in F.CANONICAL_COMPARTMENTS}


def _layout(*codes: str):
    return [_SPECS[code] for code in codes]


# ---------------------------------------------------------------------------
# Exclusive operations
# ---------------------------------------------------------------------------

_CG_DENIED = "724-23000001"


class TestExclusiveOperationsAreDenied:
    def test_six_roles_each_reach_into_another_role_s_exclusive_operation(self):
        """Every role is caught once, so no permissive branch can carry the suite.

        PRD: "A request whose role is recognised but is not among the roles
        authorised for the called endpoint is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/rbac/each_role_denied_another_roles_exclusive_operation_unauthorized
        """
        world = fx.reference_world(
            compartment_specs=_layout("OC"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.plan_world(world, flight_overrides={"flight_number": "LX1602"})
        flight_version = fx.flight_version(world)
        plan_version = fx.plan_version(world)

        intrusions = [
            api_client.create_aircraft(F.aircraft_payload("HB-BBB"), LOAD_CONTROLLER),
            api_client.create_load_plan(
                F.load_plan_payload(world.flight_id, flight_version), RAMP_AGENT
            ),
            api_client.create_cargo_item(
                F.cargo_item_payload(
                    world.flight_id, _CG_DENIED, item_kind="GENERAL", weight_kg=400
                ),
                HEADERS_BY_ROLE["DangerousGoodsOfficer"],
            ),
            api_client.create_load_sheet(
                F.load_sheet_payload(world.plan_id, plan_version), captain_headers()
            ),
            api_client.depart_flight(world.flight_id, AUDIT_INSPECTOR),
            api_client.patch_flight_conditions(
                world.flight_id, {"outside_air_temp_c": 24}, ADMIN
            ),
        ]

        for response in intrusions:
            validate_error(response, E.UNAUTHORIZED, 403)
        rows, meta = validate_paginated(api_client.list_aircraft(ADMIN))
        A.assert_pagination_meta(meta, total_count=1)
        rows, meta = validate_paginated(
            api_client.list_flight_load_plans(world.flight_id, LOAD_CONTROLLER)
        )
        A.assert_pagination_meta(meta, total_count=1)
        rows, meta = validate_paginated(
            api_client.list_cargo_items(RAMP_AGENT, {"flight_id": world.flight_id})
        )
        A.assert_pagination_meta(meta, total_count=0)
        rows, meta = validate_paginated(
            api_client.list_load_plan_load_sheets(world.plan_id, LOAD_CONTROLLER)
        )
        A.assert_pagination_meta(meta, total_count=0)
        flight = fx.refresh_flight(world)
        A.assert_flight_state(flight, status="PLANNING")
        assert float(flight["outside_air_temp_c"]) == 22, (
            "a refused revision should leave the departure temperature alone"
        )


# ---------------------------------------------------------------------------
# Shared operations
# ---------------------------------------------------------------------------

_CG_SHARED = "724-24000001"


class TestSharedOperationsSucceed:
    def test_each_owning_role_exercises_its_share_of_the_write_surfaces(self):
        """Two roles allocate bags, two roles stow and create flights, all succeed.

        PRD: "`bag_weight_kg` is optional: when a weighed total is supplied it is
        used verbatim, and when it is omitted the allocation's mass is the bag count
        multiplied by the programme's `checked_bag_kg`."

        Design: Corner/rbac/shared_operations_succeed_for_every_owning_role
        """
        world = fx.reference_world(
            compartment_specs=_layout("H1", "H4"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.plan_world(world, flight_overrides={"flight_number": "LX1602"})
        fx.book_cargo(world, _CG_SHARED, item_kind="GENERAL", weight_kg=400, length_m=1.2)
        hold = world.compartment_id("H4")

        by_controller = api_client.create_bag_allocation(
            F.bag_allocation_payload(world.plan_id, world.compartment_id("H1"), 112, 1450),
            LOAD_CONTROLLER,
        )
        by_ramp = api_client.create_bag_allocation(
            F.bag_allocation_payload(world.plan_id, hold, 20, 260), RAMP_AGENT
        )
        stowage = api_client.assign_cargo_item(
            world.cargo_id(_CG_SHARED), {"assigned_compartment_id": hold}, LOAD_CONTROLLER
        )
        second_rotation = api_client.create_flight(
            F.flight_payload(
                world.aircraft_id,
                world.runway_id,
                world.program_id,
                flight_number="LX1604",
                scheduled_off_block_utc="2026-08-15T14:00:00Z",
                scheduled_on_block_utc="2026-08-15T16:00:00Z",
            ),
            ADMIN,
        )

        forward_bags = get_success_data(by_controller, 201)
        aft_bags = get_success_data(by_ramp, 201)
        stowed = get_success_data(stowage, 200)
        later_flight = get_success_data(second_rotation, 201)
        A.assert_kg(forward_bags["effective_weight_kg"], 1450.00, "effective_weight_kg")
        A.assert_kg(aft_bags["effective_weight_kg"], 260.00, "effective_weight_kg")
        A.assert_cargo_state(stowed, assigned_compartment_id=hold)
        A.assert_flight_state(later_flight, status="PLANNING")
        rows, meta = validate_paginated(
            api_client.list_bag_allocations(ADMIN, {"load_plan_id": world.plan_id})
        )
        A.assert_pagination_meta(meta, total_count=2)
        rows, meta = validate_paginated(
            api_client.list_flights(ADMIN, {"aircraft_id": world.aircraft_id})
        )
        A.assert_pagination_meta(meta, total_count=2)


# ---------------------------------------------------------------------------
# Authentication before authorisation
# ---------------------------------------------------------------------------


class TestMissingRoleHeader:
    def test_a_write_and_a_read_without_a_role_are_both_unauthenticated(self):
        """No role header means no request, whatever the endpoint would have allowed.

        PRD: "A request whose `X-User-Role` header is absent, or whose value is not
        one of those six strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_role_header_returns_unauthenticated
        """
        aircraft = fx.create_aircraft("HB-AAA")

        anonymous_write = api_client.create_runway(
            F.runway_payload(
                airport_code="LSZH",
                designator="16",
                elevation_ft=1416,
                length_m=3700,
                slot_capacity_per_window=None,
            ),
            headers_missing_role(),
        )
        anonymous_read = api_client.get_aircraft(str(aircraft["id"]), no_auth_headers())

        validate_error(anonymous_write, E.UNAUTHENTICATED, 401)
        validate_error(anonymous_read, E.UNAUTHENTICATED, 401)
        identified = get_success_data(
            api_client.get_aircraft(str(aircraft["id"]), ADMIN), 200
        )
        assert identified["registration"] == "HB-AAA", (
            "the refused calls should have left the airframe exactly as it was"
        )


class TestUndeclaredRoleName:
    def test_a_role_the_contract_never_published_is_not_merely_unauthorised(self):
        """An unknown principal is stopped before the role list is consulted.

        PRD: "A request whose `X-User-Role` header is absent, or whose value is not
        one of those six strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/undeclared_role_name_returns_unauthenticated
        """
        aircraft = fx.create_aircraft("HB-AAA")

        response = api_client.get_aircraft(
            str(aircraft["id"]), undeclared_role_headers()
        )

        assert response.status_code == 401, (
            f"an undeclared role should be 401 rather than {response.status_code}"
        )
        A.assert_error_envelope(response.json(), E.UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# Segregation of duties on the load sheet
# ---------------------------------------------------------------------------


class TestSheetSegregationOfDuties:
    def test_the_issuing_individual_may_not_sign_their_own_sheet(self):
        """The rule keys on the user identity, not on the role that was worn.

        PRD: "Both arms require the sheet to be `ISSUED` and both enforce the
        segregation-of-duties rule: the acting `Captain`'s `X-User-ID` must differ
        from the sheet's `issued_by_user_id`, or the request is refused with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/captain_cannot_accept_a_sheet_they_issued_themselves
        """
        world = fx.fx_a_computed(flight_overrides={"flight_number": "LX1602"})
        fx.issue_sheet(world, headers_for(CAPTAIN_1, ROLE_LOAD_CONTROLLER))
        A.assert_sheet_figures(
            world.sheet,
            status="ISSUED",
            issued_by_user_id=CAPTAIN_1,
            issued_takeoff_weight_kg=58200.00,
            issued_index_tow=87.26,
        )

        self_signature = api_client.accept_load_sheet(
            world.sheet_id, captain_headers(CAPTAIN_1)
        )

        validate_error(self_signature, E.SEGREGATION_OF_DUTIES, 409)
        A.assert_sheet_figures(
            fx.refresh_sheet(world), status="ISSUED", accepted_by_user_id=None
        )
        A.assert_flight_state(fx.refresh_flight(world), load_release_state="OPEN")

        second_pair_of_eyes = api_client.accept_load_sheet(
            world.sheet_id, captain_headers(CAPTAIN_2)
        )

        signed = get_success_data(second_pair_of_eyes, 200)
        A.assert_sheet_figures(
            signed,
            status="ACCEPTED",
            issued_by_user_id=CAPTAIN_1,
            accepted_by_user_id=CAPTAIN_2,
        )
        A.assert_flight_state(fx.refresh_flight(world), load_release_state="RELEASED")


# ---------------------------------------------------------------------------
# Segregation of duties across the audit
# ---------------------------------------------------------------------------

_DG_AUDITED = "724-25000001"


class TestAuditSegregationOfDuties:
    def test_the_officer_who_accepted_the_declaration_may_not_close_the_audit(self):
        """The bar reaches across aggregates and survives a change of role.

        PRD: "The `X-User-ID` closing an audit must differ from every
        `accepted_by_user_id` recorded on any dangerous-goods declaration on that
        flight's cargo; if the closing inspector is the same operator who accepted
        any of those declarations, closure is refused with
        `ERR_AUDIT_SEGREGATION_CONFLICT`."

        Design: Corner/rbac/audit_closure_barred_to_the_dangerous_goods_acceptor
        """
        world = fx.reference_world(
            compartment_specs=_layout("OC", "H4"), band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.plan_world(world, flight_overrides={"flight_number": "LX1602"})
        fx.book_and_stow_cargo(
            world,
            _DG_AUDITED,
            "H4",
            item_kind="GENERAL",
            weight_kg=400,
            length_m=1.2,
            is_dangerous_goods=True,
        )
        declaration = fx.submit_declaration(world, _DG_AUDITED, 400)
        fx.accept_declaration(str(declaration["id"]), HEADERS_BY_ROLE["DangerousGoodsOfficer"])
        fx.seat(world, "OC", male_count=25, female_count=35)
        fx.compute_plan(world)
        audit = get_success_data(
            api_client.create_load_audit(
                F.load_audit_payload(world.flight_id, "DOCUMENTED_BASIS", 4650, 0, 400),
                audit_inspector_headers(AUDIT_INSPECTOR_1),
            ),
            201,
        )
        A.assert_audit_figures(
            audit,
            status="OPEN",
            pax_delta_kg=0.00,
            bag_delta_kg=0.00,
            cargo_delta_kg=400.00,
            total_absolute_discrepancy_kg=400.00,
            severity="MINOR",
        )
        audit_id = str(audit["id"])
        note = F.close_audit_payload("No discrepancy against the documented figures.")

        by_the_acceptor = api_client.close_load_audit(
            audit_id, note, audit_inspector_headers(DG_OFFICER_1)
        )

        validate_error(by_the_acceptor, E.AUDIT_SEGREGATION_CONFLICT, 409)
        still_open = get_success_data(
            api_client.get_load_audit(audit_id, AUDIT_INSPECTOR), 200
        )
        A.assert_audit_figures(still_open, status="OPEN", closed_by_user_id=None)

        by_an_uninvolved_inspector = api_client.close_load_audit(
            audit_id, note, audit_inspector_headers(AUDIT_INSPECTOR_1)
        )

        closed = get_success_data(by_an_uninvolved_inspector, 200)
        A.assert_audit_figures(
            closed, status="CLOSED", closed_by_user_id=AUDIT_INSPECTOR_1
        )
        A.assert_declaration_state(
            fx.refresh_declaration(world, _DG_AUDITED), accepted_by_user_id=DG_OFFICER_1
        )


# ---------------------------------------------------------------------------
# Shared reads
# ---------------------------------------------------------------------------


class TestEveryRoleMayRead:
    def test_all_six_roles_read_the_same_derived_figures_from_one_flight(self):
        """Writes are partitioned, reads are not, and the payload does not vary.

        PRD: "All six roles may perform every read."

        Design: Corner/rbac/every_role_can_read_the_flight_record
        """
        world = fx.reference_world(
            compartment_specs=[], band_specs=[F.CANONICAL_BANDS[1]]
        )
        fx.flight_world(world, flight_number="LX1602")

        readings = {
            role: get_success_data(api_client.get_flight(world.flight_id, headers), 200)
            for role, headers in HEADERS_BY_ROLE.items()
        }

        assert len(readings) == 6, "all six roles should have been exercised"
        for role, flight in readings.items():
            A.assert_flight_capacity(
                flight,
                dry_operating_weight_kg=42550.00,
                dry_operating_index=62.53,
                performance_limited_takeoff_weight_kg=73810.00,
                allowed_payload_kg=20180.00,
                limiting_factor="MZFW",
            )
        first_role = next(iter(readings))
        for role, flight in readings.items():
            assert flight == readings[first_role], (
                f"the flight read by {role} should match the one read by {first_role}"
            )
