"""The error catalogue of the white space: the authentication ladder, the fourteen
per-family not-found codes, the six uniqueness scopes, the commissioning and
change-control gates, the cooling acceptance floors and the handover gates."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    create_busway_payload,
    create_cage_payload,
    create_camera_payload,
    create_containment_zone_payload,
    create_hall_payload,
    create_load_bank_test_payload,
    create_tenant_payload,
)
from test_helpers.fixtures import (
    CA,
    CM,
    EC,
    FP,
    MC,
    OM,
    SA,
    approve_mop,
    approve_script,
    close_mop,
    commission_cooling_unit,
    commission_device,
    create_busway,
    create_cage,
    create_camera,
    create_card_reader,
    create_cooling_unit,
    create_hall,
    create_mop,
    create_package,
    create_packet,
    create_pdu,
    create_rack,
    create_tenant,
    energize_busway,
    execute_mop,
    execute_script,
    install_rack,
    leakage_test,
    place_unit_in_service,
    power_on_rack,
    prove_zone_and_cooling,
    read_busway,
    read_cage,
    read_capacity_summary,
    read_cooling_unit,
    read_hall,
    read_mop,
    read_package,
    read_packet,
    read_pdu,
    read_rack,
    release_feed,
    reserve_feed,
    set_clock,
    setup_commissioning_hall,
    setup_executing_mop,
    setup_fit_out_hall,
    setup_live_hall_with_caged_rack,
    setup_planning_hall,
    setup_scheduled_mop,
    submit_mop,
    submit_packet,
    tag_rack,
    witness_package,
)
from test_helpers.test_users import (
    headers_without_role,
    headers_without_user_id,
    make_headers,
)


def _hall_payload(name, code, **overrides):
    return create_hall_payload(name=name, code=code, **overrides)


def _read_tenant(tenant_id):
    return validate_success(api_client.get_tenant(tenant_id, FP))


class TestAuthLadder:
    """Three failures that all read as 'you may not do that' and are nevertheless
    three different codes at three different rungs of the ladder."""

    def _hall_with_a_mop_target(self):
        hall = create_hall(
            "CX67", name="Auth Ladder Hall", design_kw_capacity=400.00
        )
        pdu_a = create_pdu(hall["id"], "PDU-A1", "A", rated_kw=300.00)
        busway = create_busway(pdu_a["id"], "BW-A1")
        return {"hall_id": hall["id"], "bw_a": busway}

    def test_an_absent_role_and_an_unknown_role_are_both_unauthenticated(self):
        """A hall creation carrying no `X-User-Role` at all and one carrying a role
        string outside the nine both come back 401 `ERR_UNAUTHENTICATED`, and neither
        leaves a hall behind.

        PRD: "If `X-User-Role` is absent, or carries a string that is not one of the nine role
        names defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/auth_ladder_missing_role_wrong_role_and_missing_user_id
        """
        self._hall_with_a_mop_target()

        validate_error(
            api_client.create_hall(
                _hall_payload("No Role", "CX67X"), headers_without_role("u-fp-1")
            ),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api_client.create_hall(
                _hall_payload("Unknown Role", "CX67Y"),
                make_headers("u-fp-1", "DataCenterJanitor"),
            ),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        ), "an out-of-catalogue role string is unauthenticated, never 403"

        rows, meta = validate_paginated(api_client.list_halls(FP, {"limit": 100}))
        codes = [row["code"] for row in rows]
        for code in ("CX67X", "CX67Y"):
            assert code not in codes, f"no hall was created under {code}"
        assert meta["total_count"] == 1, (
            "only the fixture hall exists; neither rejected creation wrote a row"
        )

    def test_a_recognised_but_unlisted_role_is_unauthorized(self):
        """`ElectricalContractor` is one of the nine roles and is simply not listed for
        hall creation, so the same payload comes back 403 `ERR_UNAUTHORIZED` rather than
        401.

        PRD: "If the role is recognised but is not among the roles authorised for the addressed
        operation in the endpoint table of §4, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/errors/auth_ladder_missing_role_wrong_role_and_missing_user_id
        """
        self._hall_with_a_mop_target()

        validate_error(
            api_client.create_hall(_hall_payload("Wrong Role", "CX67Z"), EC),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        rows, meta = validate_paginated(api_client.list_halls(FP, {"limit": 100}))
        assert "CX67Z" not in [row["code"] for row in rows]
        assert meta["total_count"] == 1

    def test_an_identity_recording_endpoint_refuses_an_anonymous_author(self):
        """MOP drafting is one of the ten identity-recording operations, so the correct
        authoring role with no `X-User-ID` at all is refused 401 `ERR_MISSING_USER_ID`
        and no MOP is minted with a null author.

        PRD: "Every endpoint that records or compares an acting identity rejects a request whose
        `X-User-ID` header is missing with `ERR_MISSING_USER_ID` (HTTP 401). Those endpoints
        are exactly ten: commissioning-package script execution, the commissioning-package
        witness decision, method-of-procedure drafting, MOP submission, MOP approval
        decisions, MOP revision, MOP execution, MOP closure, MOP back-out, and
        release-packet acceptance."

        Design: Corner/errors/auth_ladder_missing_role_wrong_role_and_missing_user_id
        """
        ctx = self._hall_with_a_mop_target()

        validate_error(
            api_client.create_mop(
                {
                    "hall_id": ctx["hall_id"],
                    "target_resource_type": "BUSWAY",
                    "target_resource_id": ctx["bw_a"]["id"],
                    "title": "Anonymous MOP",
                    "risk_class": "LOW",
                    "backout_plan": "de-energize",
                    "window_start": "2026-08-10T02:00:00Z",
                    "window_end": "2026-08-10T06:00:00Z",
                },
                headers_without_user_id("ElectricalContractor"),
            ),
            ApiErrorId.ERR_MISSING_USER_ID.value,
            401,
        )
        rows, meta = validate_paginated(
            api_client.list_mops(FP, {"hall_id": ctx["hall_id"]})
        )
        assert meta["total_count"] == 0, "the anonymous draft was never recorded"
        assert rows == []


class TestPathNotFoundVocabulary:
    """Fourteen path variables, fourteen separate not-found codes: no family is
    allowed to borrow another family's 404."""

    def _probe_table(self):
        return [
            ("hall_id", api_client.get_hall, ApiErrorId.ERR_HALL_NOT_FOUND),
            ("tenant_id", api_client.get_tenant, ApiErrorId.ERR_TENANT_NOT_FOUND),
            ("pdu_id", api_client.get_pdu, ApiErrorId.ERR_PDU_NOT_FOUND),
            ("busway_id", api_client.get_busway, ApiErrorId.ERR_BUSWAY_NOT_FOUND),
            (
                "zone_id",
                api_client.get_containment_zone,
                ApiErrorId.ERR_CONTAINMENT_ZONE_NOT_FOUND,
            ),
            (
                "unit_id",
                api_client.get_cooling_unit,
                ApiErrorId.ERR_COOLING_UNIT_NOT_FOUND,
            ),
            ("cage_id", api_client.get_cage, ApiErrorId.ERR_CAGE_NOT_FOUND),
            (
                "device_id",
                api_client.get_security_device,
                ApiErrorId.ERR_SECURITY_DEVICE_NOT_FOUND,
            ),
            ("rack_id", api_client.get_rack, ApiErrorId.ERR_RACK_NOT_FOUND),
            ("feed_id", api_client.get_rack_feed, ApiErrorId.ERR_RACK_FEED_NOT_FOUND),
            (
                "package_id",
                api_client.get_commissioning_package,
                ApiErrorId.ERR_PACKAGE_NOT_FOUND,
            ),
            (
                "test_id",
                api_client.get_load_bank_test,
                ApiErrorId.ERR_LOAD_BANK_TEST_NOT_FOUND,
            ),
            ("mop_id", api_client.get_mop, ApiErrorId.ERR_MOP_NOT_FOUND),
            (
                "packet_id",
                api_client.get_release_packet,
                ApiErrorId.ERR_RELEASE_PACKET_NOT_FOUND,
            ),
        ]

    def test_each_path_family_answers_with_its_own_not_found_code(self):
        """The very same unknown identifier addressed at each of the fourteen
        single-resource reads produces fourteen different 404 codes, one per family.

        PRD: "Each maps to its own 404: `ERR_HALL_NOT_FOUND`, `ERR_TENANT_NOT_FOUND`, `ERR_PDU_NOT_FOUND`, `ERR_BUSWAY_NOT_FOUND`, `ERR_CONTAINMENT_ZONE_NOT_FOUND`, `ERR_COOLING_UNIT_NOT_FOUND`, `ERR_CAGE_NOT_FOUND`, `ERR_SECURITY_DEVICE_NOT_FOUND`, `ERR_RACK_NOT_FOUND`, `ERR_RACK_FEED_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_LOAD_BANK_TEST_NOT_FOUND`, `ERR_MOP_NOT_FOUND` and `ERR_RELEASE_PACKET_NOT_FOUND`."

        Design: Corner/errors/every_path_identifier_has_its_own_not_found_code
        """
        create_hall("CX68", name="Not Found Vocabulary Hall")

        for variable, reader, expected in self._probe_table():
            body = validate_error(
                reader(NON_EXISTENT_UUID, FP), expected.value, 404
            )
            assert body["error_id"] == expected.value, (
                f"{variable} must answer with {expected.value}"
            )

    def test_the_fourteen_codes_are_pairwise_distinct_and_real_rows_still_resolve(self):
        """No two of the fourteen probes return the same code, and the hall that does
        exist still resolves normally after the whole sweep of misses.

        PRD: "Each maps to its own 404: `ERR_HALL_NOT_FOUND`, `ERR_TENANT_NOT_FOUND`, `ERR_PDU_NOT_FOUND`, `ERR_BUSWAY_NOT_FOUND`, `ERR_CONTAINMENT_ZONE_NOT_FOUND`, `ERR_COOLING_UNIT_NOT_FOUND`, `ERR_CAGE_NOT_FOUND`, `ERR_SECURITY_DEVICE_NOT_FOUND`, `ERR_RACK_NOT_FOUND`, `ERR_RACK_FEED_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_LOAD_BANK_TEST_NOT_FOUND`, `ERR_MOP_NOT_FOUND` and `ERR_RELEASE_PACKET_NOT_FOUND`."

        Design: Corner/errors/every_path_identifier_has_its_own_not_found_code
        """
        hall = create_hall("CX68", name="Not Found Vocabulary Hall")

        observed = []
        for _variable, reader, expected in self._probe_table():
            body = validate_error(reader(NON_EXISTENT_UUID, FP), expected.value, 404)
            observed.append(body["error_id"])

        assert len(observed) == 14, "there are fourteen path families in play"
        assert len(set(observed)) == 14, (
            f"every family needs its own code, saw {sorted(observed)}"
        )

        still_there = read_hall(hall["id"])
        assert still_there["id"] == hall["id"]
        assert still_there["code"] == "CX68"


class TestMopTargetNotFound:
    """The polymorphic MOP target has a code of its own, so a bad target never
    borrows the addressed entity family's plain not-found code."""

    def _two_halls_with_a_busway_each(self):
        home = create_hall("CX69", name="MOP Home Hall", design_kw_capacity=400.00)
        home_pdu = create_pdu(home["id"], "PDU-A1", "A", rated_kw=300.00)
        home_bw = create_busway(home_pdu["id"], "BW-A1")
        foreign = create_hall(
            "CX70", name="MOP Foreign Hall", design_kw_capacity=400.00
        )
        foreign_pdu = create_pdu(foreign["id"], "PDU-F1", "A", rated_kw=300.00)
        foreign_bw = create_busway(foreign_pdu["id"], "BW-F1")
        return {
            "home_id": home["id"],
            "home_bw": home_bw,
            "foreign_id": foreign["id"],
            "foreign_bw": foreign_bw,
        }

    def _draft(self, hall_id, target_type, target_id):
        return api_client.create_mop(
            {
                "hall_id": hall_id,
                "target_resource_type": target_type,
                "target_resource_id": target_id,
                "title": "Polymorphic target probe",
                "risk_class": "LOW",
                "backout_plan": "restore the prior configuration",
                "window_start": "2026-08-10T02:00:00Z",
                "window_end": "2026-08-10T06:00:00Z",
            },
            EC,
        )

    def test_a_missing_target_and_a_foreign_hall_target_share_one_dedicated_code(self):
        """An unknown busway identifier and a busway that belongs to another white space
        are both refused `ERR_MOP_TARGET_NOT_FOUND`, never `ERR_BUSWAY_NOT_FOUND`.

        PRD: "A reference that resolves to nothing, or to a resource in another white space, is refused with `ERR_MOP_TARGET_NOT_FOUND`."

        Design: Corner/errors/mop_target_resource_identifier_has_a_distinct_not_found_code
        """
        ctx = self._two_halls_with_a_busway_each()

        validate_error(
            self._draft(ctx["home_id"], "BUSWAY", NON_EXISTENT_UUID),
            ApiErrorId.ERR_MOP_TARGET_NOT_FOUND.value,
            404,
        )
        validate_error(
            self._draft(ctx["home_id"], "BUSWAY", ctx["foreign_bw"]["id"]),
            ApiErrorId.ERR_MOP_TARGET_NOT_FOUND.value,
            404,
        )

        rows, meta = validate_paginated(
            api_client.list_mops(FP, {"hall_id": ctx["home_id"]})
        )
        assert meta["total_count"] == 0, "neither refusal drafted a MOP"
        assert rows == []

    def test_a_target_of_the_wrong_entity_type_is_also_a_target_miss(self):
        """A real busway identifier declared as a `COOLING_UNIT` target is refused
        `ERR_MOP_TARGET_NOT_FOUND` because the row must be of the declared type, while
        the same identifier declared as a `BUSWAY` drafts cleanly.

        PRD: "The target reference is polymorphic: it must resolve to a row of the entity type the `target_resource_type` names, and that row's hall must be the same hall the MOP names."

        Design: Corner/errors/mop_target_resource_identifier_has_a_distinct_not_found_code
        """
        ctx = self._two_halls_with_a_busway_each()

        validate_error(
            self._draft(ctx["home_id"], "COOLING_UNIT", ctx["home_bw"]["id"]),
            ApiErrorId.ERR_MOP_TARGET_NOT_FOUND.value,
            404,
        )

        drafted = validate_success(
            self._draft(ctx["home_id"], "BUSWAY", ctx["home_bw"]["id"]), 201
        )
        assert drafted["status"] == "DRAFT"
        assert drafted["target_resource_type"] == "BUSWAY"
        assert drafted["target_resource_id"] == ctx["home_bw"]["id"]
        assert drafted["author_user_id"] == "u-elec-1"

        rows, meta = validate_paginated(
            api_client.list_mops(FP, {"hall_id": ctx["home_id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == drafted["id"]


class TestDuplicateCodeScopes:
    """One code, six different scopes: global for halls and tenants, per-PDU for
    busway names, per-hall for zone and cage labels, per-cage for device labels."""

    def _hall_with_every_named_thing(self):
        ctx = setup_planning_hall(
            "CX71", tenant_mode="MULTI_TENANT", with_busway_b=False
        )
        ctx["tenant"] = create_tenant("TN71", name="Uniqueness Tenant")
        ctx["cage_1"] = create_cage(
            ctx["hall_id"], ctx["tenant"]["id"], "CG-1", perimeter_length_m=40.0
        )
        ctx["cage_2"] = create_cage(
            ctx["hall_id"], ctx["tenant"]["id"], "CG-2", perimeter_length_m=40.0
        )
        ctx["camera_1"] = create_camera(ctx["cage_1"]["id"], "CAM-1", 38.0)
        return ctx

    def test_each_of_the_six_scopes_rejects_its_own_collision(self):
        """Re-using the hall code, the tenant code, the busway name inside the same PDU,
        the zone label inside the same hall, the cage label inside the same hall and the
        device label inside the same cage all come back 409 `ERR_DUPLICATE_CODE`.

        PRD: "`Hall.code` and `Tenant.code` are unique across the whole system; a busway `name` is unique within its parent power distribution unit; a containment zone `label` and a cage `label` are each unique within their hall; and a security device `label` is unique within its cage."

        Design: Corner/errors/duplicate_code_is_scoped_globally_per_pdu_per_hall_and_per_cage
        """
        ctx = self._hall_with_every_named_thing()
        duplicate = ApiErrorId.ERR_DUPLICATE_CODE.value

        validate_error(
            api_client.create_hall(
                create_hall_payload(name="Second CX71", code="CX71"), FP
            ),
            duplicate,
            409,
        )
        validate_error(
            api_client.create_tenant(
                create_tenant_payload(name="Second TN71", code="TN71"), FP
            ),
            duplicate,
            409,
        )
        validate_error(
            api_client.create_busway(
                create_busway_payload(ctx["pdu_a"]["id"], name="BW-A1"), EC
            ),
            duplicate,
            409,
        )
        validate_error(
            api_client.create_containment_zone(
                create_containment_zone_payload(ctx["hall_id"], label="CA-1"), MC
            ),
            duplicate,
            409,
        )
        validate_error(
            api_client.create_cage(
                create_cage_payload(
                    ctx["hall_id"], ctx["tenant"]["id"], label="CG-1"
                ),
                SA,
            ),
            duplicate,
            409,
        )
        validate_error(
            api_client.create_security_device(
                create_camera_payload(ctx["cage_1"]["id"], label="CAM-1"), SA
            ),
            duplicate,
            409,
        )

    def test_the_same_name_is_admitted_in_a_neighbouring_scope(self):
        """`BW-A1` is free under the other PDU and `CAM-1` is free inside the other cage,
        which is what makes those two scopes narrower than the hall.

        PRD: "A collision on any of these is rejected with `ERR_DUPLICATE_CODE` (HTTP 409) on hall creation, tenant creation, busway creation, containment-zone creation, cage creation and security-device creation."

        Design: Corner/errors/duplicate_code_is_scoped_globally_per_pdu_per_hall_and_per_cage
        """
        ctx = self._hall_with_every_named_thing()

        twin_busway = validate_success(
            api_client.create_busway(
                create_busway_payload(ctx["pdu_b"]["id"], name="BW-A1"), EC
            ),
            201,
        )
        assert twin_busway["name"] == "BW-A1"
        assert twin_busway["feed_side"] == "B", (
            "the busway copies the feed side of its parent PDU"
        )
        assert twin_busway["hall_id"] == ctx["hall_id"]

        twin_camera = validate_success(
            api_client.create_security_device(
                create_camera_payload(ctx["cage_2"]["id"], label="CAM-1"), SA
            ),
            201,
        )
        assert twin_camera["label"] == "CAM-1"
        assert twin_camera["cage_id"] == ctx["cage_2"]["id"]

        busways, busway_meta = validate_paginated(
            api_client.list_busways(FP, {"hall_id": ctx["hall_id"]})
        )
        assert busway_meta["total_count"] == 2
        assert {row["name"] for row in busways} == {"BW-A1"}, (
            "two runs of the same name coexist under different PDUs"
        )

        _devices, device_meta = validate_paginated(
            api_client.list_security_devices(FP, {"cage_id": ctx["cage_1"]["id"]})
        )
        assert device_meta["total_count"] == 1, (
            "the second CAM-1 landed in the other cage, not this one"
        )


class TestDuplicateFeedSideScope:
    """The one-live-feed-per-side rule is scoped to the rack, not to the busway, and a
    release drops the row out of the uniqueness set."""

    def _rack_with_one_a_side_feed(self):
        ctx = setup_fit_out_hall("CX72")
        ctx["bw_a2"] = create_busway(ctx["pdu_a"]["id"], "BW-A2")
        energize_busway(ctx["bw_a2"]["id"])
        ctx["rack_1"] = create_rack(
            ctx["hall_id"], ctx["zone_id"], "A", 1, design_kw=15.00
        )
        ctx["feed_a1"] = reserve_feed(
            ctx["rack_1"]["id"], ctx["bw_a"]["id"], "A", 7.50, 32
        )
        return ctx

    def _reserve_request(self, rack_id, busway_id, feed_side):
        return api_client.create_rack_feed(
            {
                "rack_id": rack_id,
                "busway_id": busway_id,
                "feed_side": feed_side,
                "requested_kw": 7.50,
                "breaker_amps": 32,
            },
            EC,
        )

    def test_a_second_a_side_feed_on_another_run_is_still_a_collision(self):
        """The rack already holds a live A-side feed, so a second A-side feed is refused
        even though it lands on a different busway run; the B side is untouched.

        PRD: "Branch feeds are constrained in the same spirit — a rack holds at most one live feed per redundant side, so a second non-released feed on the same `feed_side` of the same rack is rejected with `ERR_DUPLICATE_FEED_SIDE` (HTTP 409)."

        Design: Corner/errors/duplicate_feed_side_is_scoped_to_non_released_feeds
        """
        ctx = self._rack_with_one_a_side_feed()

        validate_error(
            self._reserve_request(
                ctx["rack_1"]["id"], ctx["bw_a2"]["id"], "A"
            ),
            ApiErrorId.ERR_DUPLICATE_FEED_SIDE.value,
            409,
        )

        b_side = validate_success(
            self._reserve_request(ctx["rack_1"]["id"], ctx["bw_b"]["id"], "B"), 201
        )
        assert b_side["status"] == "RESERVED"
        assert b_side["feed_side"] == "B", (
            "the feed copies the feed side of its busway's parent PDU chain"
        )
        assert b_side["allocated_kw"] == pytest.approx(7.500, abs=0.0005)
        assert read_busway(ctx["bw_a2"]["id"])["feed_count"] == 0, (
            "the refused A-side reservation left nothing on the second run"
        )

    def test_releasing_the_a_side_frees_it_for_a_different_run(self):
        """Once the original A-side feed is released the side is free again, so the same
        reservation that was refused now succeeds on the second run, and the released row
        is only visible when it is asked for.

        PRD: "Releasing a feed frees its side for re-reservation, because released feeds are excluded from that uniqueness set."

        PRD: "RELEASED feeds are hidden unless include_released is true."

        Design: Corner/errors/duplicate_feed_side_is_scoped_to_non_released_feeds
        """
        ctx = self._rack_with_one_a_side_feed()
        validate_success(
            self._reserve_request(ctx["rack_1"]["id"], ctx["bw_b"]["id"], "B"), 201
        )

        released = release_feed(ctx["feed_a1"]["id"])
        assert released["status"] == "RELEASED"

        re_reserved = validate_success(
            self._reserve_request(ctx["rack_1"]["id"], ctx["bw_a2"]["id"], "A"), 201
        )
        assert re_reserved["status"] == "RESERVED"
        assert re_reserved["feed_side"] == "A"
        assert re_reserved["busway_id"] == ctx["bw_a2"]["id"]

        old_run = read_busway(ctx["bw_a"]["id"])
        assert old_run["committed_kw"] == pytest.approx(0.000, abs=0.0005)
        assert old_run["feed_count"] == 0
        new_run = read_busway(ctx["bw_a2"]["id"])
        assert new_run["committed_kw"] == pytest.approx(7.500, abs=0.0005)
        assert new_run["feed_count"] == 1

        live, live_meta = validate_paginated(
            api_client.list_rack_feeds(EC, {"rack_id": ctx["rack_1"]["id"]})
        )
        assert live_meta["total_count"] == 2, "the released row is hidden by default"
        assert {row["feed_side"] for row in live} == {"A", "B"}

        _all_rows, all_meta = validate_paginated(
            api_client.list_rack_feeds(
                EC,
                {"rack_id": ctx["rack_1"]["id"], "include_released": "true"},
            )
        )
        assert all_meta["total_count"] == 3, (
            "the released A-side row is revealed on request"
        )


class TestCommissioningGateErrors:
    """Four commissioning refusals that are easy to conflate: the missing load bank,
    the unapproved script, the unsettled lower level and the witness who executed."""

    def _hall_with_three_packages(self):
        ctx = setup_commissioning_hall("CX73")
        ctx["pkg_l4"] = create_package(ctx["hall_id"], "L4", target_load_kw=10.00)
        approve_script(ctx["pkg_l4"]["id"])
        ctx["pkg_l1"] = create_package(ctx["hall_id"], "L1", target_load_kw=10.00)
        ctx["pkg_l2"] = create_package(ctx["hall_id"], "L2", target_load_kw=10.00)
        return ctx

    def test_level_four_execution_without_a_passing_run_is_a_load_bank_miss(self):
        """The L4 script is approved and the room is thermally nominal, and execution is
        still refused because no `COMPLETED`/`PASS` run of at least the package's target
        load exists.

        PRD: "For packages at level `L4` or `L5` there is an additional evidence requirement: the package must already hold at least one load bank run that is `COMPLETED`, whose `result` is `PASS`, and whose `measured_kw` is at least the package's `target_load_kw`."

        Design: Corner/errors/commissioning_gate_errors_script_level_loadbank_and_witness_identity
        """
        ctx = self._hall_with_three_packages()

        validate_error(
            api_client.execute_script(ctx["pkg_l4"]["id"], CA),
            ApiErrorId.ERR_LOADBANK_PREREQ_MISSING.value,
            409,
        )

        package = read_package(ctx["pkg_l4"]["id"])
        assert package["script_status"] == "SCRIPT_APPROVED", (
            "the refused execution left the script dimension where it was"
        )
        assert package["executed_by_user_id"] is None
        assert package["package_state"] == "IN_EXECUTION"
        assert read_hall(ctx["hall_id"])["thermal_posture"] == "NOMINAL", (
            "the refusal is about evidence, not about the room's thermal posture"
        )

    def test_a_load_bank_run_cannot_be_scheduled_against_an_unapproved_script(self):
        """The L1 package's script is still `NOT_STARTED`, so scheduling a run against it
        is refused `ERR_SCRIPT_NOT_APPROVED` and no run row appears.

        PRD: "The parent package's `script_status` must already be `SCRIPT_APPROVED`, or the run is refused with `ERR_SCRIPT_NOT_APPROVED`."

        Design: Corner/errors/commissioning_gate_errors_script_level_loadbank_and_witness_identity
        """
        ctx = self._hall_with_three_packages()
        assert read_package(ctx["pkg_l1"]["id"])["script_status"] == "NOT_STARTED"

        validate_error(
            api_client.create_load_bank_test(
                create_load_bank_test_payload(ctx["pkg_l1"]["id"]), CA
            ),
            ApiErrorId.ERR_SCRIPT_NOT_APPROVED.value,
            409,
        )

        _rows, meta = validate_paginated(
            api_client.list_load_bank_tests(CA, {"package_id": ctx["pkg_l1"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_an_unsettled_lower_level_blocks_the_higher_level_script(self):
        """L2's script approval is refused while L1 is `DRAFT`, and it is refused again
        once L1 merely reaches `IN_EXECUTION`: only `CERTIFIED` or `SUPERSEDED` settles a
        lower level.

        PRD: "An unsettled lower level is refused with `ERR_LEVEL_PREREQ_NOT_MET`; in particular an `L5` package cannot have its script approved until the hall's `L4` package is certified."

        Design: Corner/errors/commissioning_gate_errors_script_level_loadbank_and_witness_identity
        """
        ctx = self._hall_with_three_packages()
        assert read_package(ctx["pkg_l1"]["id"])["package_state"] == "DRAFT"

        validate_error(
            api_client.approve_script(
                ctx["pkg_l2"]["id"], {"script_revision": 1}, CA
            ),
            ApiErrorId.ERR_LEVEL_PREREQ_NOT_MET.value,
            409,
        )

        approved_l1 = approve_script(ctx["pkg_l1"]["id"])
        assert approved_l1["script_status"] == "SCRIPT_APPROVED"
        assert approved_l1["script_revision"] == 1
        assert approved_l1["package_state"] == "IN_EXECUTION", (
            "approving a script moves the projection from DRAFT to IN_EXECUTION"
        )

        validate_error(
            api_client.approve_script(
                ctx["pkg_l2"]["id"], {"script_revision": 1}, CA
            ),
            ApiErrorId.ERR_LEVEL_PREREQ_NOT_MET.value,
            409,
        )
        assert read_package(ctx["pkg_l2"]["id"])["script_status"] == "NOT_STARTED"

    def test_the_executor_may_not_sign_their_own_execution(self):
        """The agent who executed L1 cannot witness it even while wearing the
        `WitnessAuthority` role; a different individual certifies it, and the hall stays
        in COMMISSIONING because L4 is not yet certified.

        PRD: "and the witnessing `X-User-ID` must differ from the package's `executed_by_user_id`, failing which the request is refused with `ERR_WITNESS_SAME_AS_EXECUTOR`."

        Design: Corner/errors/commissioning_gate_errors_script_level_loadbank_and_witness_identity
        """
        ctx = self._hall_with_three_packages()
        approve_script(ctx["pkg_l1"]["id"])
        executed = execute_script(ctx["pkg_l1"]["id"], user_id="u-ca-1")
        assert executed["script_status"] == "EXECUTED"
        assert executed["executed_by_user_id"] == "u-ca-1"

        validate_error(
            api_client.witness_package(
                ctx["pkg_l1"]["id"],
                {"decision": "WITNESSED"},
                make_headers("u-ca-1", "WitnessAuthority"),
            ),
            ApiErrorId.ERR_WITNESS_SAME_AS_EXECUTOR.value,
            422,
        )
        blocked = read_package(ctx["pkg_l1"]["id"])
        assert blocked["witness_status"] == "PENDING"
        assert blocked["witnessed_by_user_id"] is None
        assert blocked["package_state"] == "IN_EXECUTION"

        signed = witness_package(ctx["pkg_l1"]["id"], "WITNESSED", user_id="u-wa-1")
        assert signed["witness_status"] == "WITNESSED"
        assert signed["witnessed_by_user_id"] == "u-wa-1"
        assert signed["package_state"] == "CERTIFIED"
        assert read_hall(ctx["hall_id"])["status"] == "COMMISSIONING", (
            "certifying L1 does not take the hall live"
        )


class TestMopApprovalIndependence:
    """Three independence rules, three separate codes, and none of them may be
    satisfied by the other two."""

    def _high_risk_mop_under_review(self):
        ctx = setup_planning_hall("CX74")
        mop = create_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_a"]["id"],
            title="Busway tap addition",
            risk_class="HIGH",
            author_user_id="u-elec-1",
        )
        ctx["mop"] = submit_mop(mop["id"], author_user_id="u-elec-1")
        assert ctx["mop"]["status"] == "UNDER_REVIEW"
        assert ctx["mop"]["required_approval_count"] == 2
        return ctx

    def _approval_request(self, mop_id, user_id, role):
        return api_client.create_mop_approval(
            mop_id,
            {"decision": "APPROVE", "comment": "approved"},
            make_headers(user_id, role),
        )

    def test_the_author_cannot_approve_their_own_change(self):
        """The author wearing a `ChangeManager` role is still the author, so the decision
        is refused `ERR_APPROVER_IS_AUTHOR` and no approval record is appended.

        PRD: "The approving `X-User-ID` may never equal the MOP's `author_user_id` — an author approving their own change is refused with `ERR_APPROVER_IS_AUTHOR`."

        Design: Corner/errors/mop_approval_identity_and_role_distinctness_errors
        """
        ctx = self._high_risk_mop_under_review()

        validate_error(
            self._approval_request(
                ctx["mop"]["id"], "u-elec-1", "ChangeManager"
            ),
            ApiErrorId.ERR_APPROVER_IS_AUTHOR.value,
            422,
        )

        after = read_mop(ctx["mop"]["id"])
        assert after["status"] == "UNDER_REVIEW"
        assert after["approval_count"] == 0
        _rows, meta = validate_paginated(
            api_client.list_mop_approvals(ctx["mop"]["id"], CM)
        )
        assert meta["total_count"] == 0, "a refused decision leaves no audit record"

    def test_one_individual_cannot_manufacture_a_two_vote_quorum(self):
        """The same change manager voting twice is refused `ERR_DUPLICATE_APPROVER`, so
        the count stays at one of the two required.

        PRD: "No `approver_user_id` may appear twice among the `APPROVE` decisions of the current review round, so one person cannot manufacture a two-vote quorum; a second vote from the same individual is refused with `ERR_DUPLICATE_APPROVER`."

        Design: Corner/errors/mop_approval_identity_and_role_distinctness_errors
        """
        ctx = self._high_risk_mop_under_review()
        first = approve_mop(ctx["mop"]["id"], role_headers=CM, user_id="u-cm-1")
        assert first["status"] == "UNDER_REVIEW"
        assert first["approval_count"] == 1

        validate_error(
            self._approval_request(ctx["mop"]["id"], "u-cm-1", "ChangeManager"),
            ApiErrorId.ERR_DUPLICATE_APPROVER.value,
            409,
        )

        after = read_mop(ctx["mop"]["id"])
        assert after["approval_count"] == 1, "the duplicate vote was not counted"
        assert after["status"] == "UNDER_REVIEW"
        rows, meta = validate_paginated(
            api_client.list_mop_approvals(ctx["mop"]["id"], CM)
        )
        assert meta["total_count"] == 1
        assert rows[0]["sequence"] == 1
        assert rows[0]["approver_user_id"] == "u-cm-1"

    def test_the_second_high_risk_approval_must_come_from_the_other_role(self):
        """A second `ChangeManager` — a different individual — is still refused
        `ERR_APPROVAL_ROLE_NOT_DISTINCT`; the `OperationsManager` completes the quorum and
        the MOP reaches APPROVED.

        PRD: "And on a `HIGH` risk MOP the second `APPROVE` of the round must come from a **different** `approver_role` than the first, so that a high-risk change always carries one `ChangeManager` and one `OperationsManager`; two votes from the same role are refused with `ERR_APPROVAL_ROLE_NOT_DISTINCT`."

        PRD: "An `APPROVE` that brings the count exactly to the requirement — that is, where the existing `approval_count` plus one equals `required_approval_count` — advances the MOP `UNDER_REVIEW → APPROVED`."

        Design: Corner/errors/mop_approval_identity_and_role_distinctness_errors
        """
        ctx = self._high_risk_mop_under_review()
        approve_mop(ctx["mop"]["id"], role_headers=CM, user_id="u-cm-1")

        validate_error(
            self._approval_request(ctx["mop"]["id"], "u-cm-2", "ChangeManager"),
            ApiErrorId.ERR_APPROVAL_ROLE_NOT_DISTINCT.value,
            422,
        )
        assert read_mop(ctx["mop"]["id"])["approval_count"] == 1

        decided = approve_mop(ctx["mop"]["id"], role_headers=OM, user_id="u-om-1")
        assert decided["status"] == "APPROVED"
        assert decided["approval_count"] == 2

        rows, meta = validate_paginated(
            api_client.list_mop_approvals(ctx["mop"]["id"], CM)
        )
        assert meta["total_count"] == 2, "only the two accepted decisions are recorded"
        assert [row["sequence"] for row in rows] == [1, 2]
        assert [row["approver_role"] for row in rows] == [
            "ChangeManager",
            "OperationsManager",
        ]


class TestMopExecutionAuthority:
    """Two scheduled MOPs sharing a window on two different runs: only the author may
    drive one, and only one may be live in the white space at a time."""

    def _two_scheduled_mops_inside_their_window(self):
        ctx = setup_planning_hall("CX75")
        ctx["bw_a2"] = create_busway(ctx["pdu_a"]["id"], "BW-A2")
        ctx["mop_1"] = setup_scheduled_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_a"]["id"],
            risk_class="MEDIUM",
            window_start="2026-08-10T02:00:00Z",
            window_end="2026-08-10T06:00:00Z",
            author_user_id="u-elec-1",
            title="Works on BW-A1",
        )
        ctx["mop_2"] = setup_scheduled_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_a2"]["id"],
            risk_class="MEDIUM",
            window_start="2026-08-10T02:00:00Z",
            window_end="2026-08-10T06:00:00Z",
            author_user_id="u-elec-1",
            title="Works on BW-A2",
        )
        assert ctx["mop_1"]["status"] == "SCHEDULED"
        assert ctx["mop_2"]["status"] == "SCHEDULED"
        set_clock("2026-08-10T03:00:00Z")
        return ctx

    def test_only_the_author_may_execute_the_scheduled_mop(self):
        """A mechanical contractor holding an authorised role for the endpoint is still
        not the author, so execution is refused `ERR_MOP_EXECUTOR_NOT_AUTHOR` and the MOP
        stays SCHEDULED.

        PRD: "the acting `X-User-ID` must equal `author_user_id`, or `ERR_MOP_EXECUTOR_NOT_AUTHOR`; and no other MOP of the same hall may already be `IN_EXECUTION`, since one live change at a time per white space is the whole discipline — a second concurrent execution is refused with `ERR_HALL_MOP_ALREADY_EXECUTING`."

        Design: Corner/errors/mop_execution_authority_and_one_executing_mop_per_hall
        """
        ctx = self._two_scheduled_mops_inside_their_window()

        validate_error(
            api_client.execute_mop(
                ctx["mop_1"]["id"], make_headers("u-mech-1", "MechanicalContractor")
            ),
            ApiErrorId.ERR_MOP_EXECUTOR_NOT_AUTHOR.value,
            403,
        )

        after = read_mop(ctx["mop_1"]["id"])
        assert after["status"] == "SCHEDULED"
        assert after["executed_at"] is None
        assert after["pre_execution_target_state"] is None
        assert read_hall(ctx["hall_id"])["release_posture"] != "LOCKED", (
            "a refused execution does not lock the white space"
        )

    def test_a_second_concurrent_execution_in_the_same_hall_is_refused(self):
        """With the first MOP `IN_EXECUTION`, the second MOP on a different run in the
        same hall is refused `ERR_HALL_MOP_ALREADY_EXECUTING` and stays SCHEDULED.

        PRD: "and no other MOP of the same hall may already be `IN_EXECUTION`, since one live change at a time per white space is the whole discipline — a second concurrent execution is refused with `ERR_HALL_MOP_ALREADY_EXECUTING`."

        Design: Corner/errors/mop_execution_authority_and_one_executing_mop_per_hall
        """
        ctx = self._two_scheduled_mops_inside_their_window()
        first = execute_mop(ctx["mop_1"]["id"], author_user_id="u-elec-1")
        assert first["status"] == "IN_EXECUTION"
        assert first["executed_at"] is not None
        assert first["pre_execution_target_state"] == "INSTALLED", (
            "the run was never energised, so INSTALLED is what gets captured"
        )

        validate_error(
            api_client.execute_mop(
                ctx["mop_2"]["id"], make_headers("u-elec-1", "ElectricalContractor")
            ),
            ApiErrorId.ERR_HALL_MOP_ALREADY_EXECUTING.value,
            409,
        )
        assert read_mop(ctx["mop_2"]["id"])["status"] == "SCHEDULED"

        hall = read_hall(ctx["hall_id"])
        assert hall["release_posture"] == "LOCKED"
        assert hall["open_mop_count"] == 2, (
            "both the executing and the still-scheduled MOP occupy the hall"
        )

    def test_closure_is_also_the_author_s_act_and_frees_the_hall_for_the_next_mop(self):
        """A non-author closure is refused with the same authority code; once the author
        closes, the second MOP executes and `open_mop_count` falls to one.

        PRD: "Both require the acting `X-User-ID` to equal `author_user_id`, and both stamp `closed_at` with the logical clock's current instant — closing moves the MOP to `CLOSED`, backing out moves it to `BACKED_OUT`, and both are terminal."

        Design: Corner/errors/mop_execution_authority_and_one_executing_mop_per_hall
        """
        ctx = self._two_scheduled_mops_inside_their_window()
        execute_mop(ctx["mop_1"]["id"], author_user_id="u-elec-1")

        validate_error(
            api_client.close_mop(
                ctx["mop_1"]["id"],
                {"closeout_note": "closing on someone else's behalf"},
                make_headers("u-mech-1", "MechanicalContractor"),
            ),
            ApiErrorId.ERR_MOP_EXECUTOR_NOT_AUTHOR.value,
            403,
        )
        assert read_mop(ctx["mop_1"]["id"])["status"] == "IN_EXECUTION"

        closed = close_mop(ctx["mop_1"]["id"], author_user_id="u-elec-1")
        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] is not None

        second = execute_mop(ctx["mop_2"]["id"], author_user_id="u-elec-1")
        assert second["status"] == "IN_EXECUTION"

        hall = read_hall(ctx["hall_id"])
        assert hall["open_mop_count"] == 1, "the closed MOP occupies no window"
        assert hall["release_posture"] == "LOCKED"


class TestCoolingAcceptanceAndMargin:
    """The airflow acceptance floor and the thermal gate are two different refusals,
    and a 20.00 kW nameplate machine that only moves 2700 cfm gates at 9.74 kW."""

    def _hall_with_a_small_cooling_unit(self):
        ctx = setup_fit_out_hall(
            "CX76",
            cooling_redundancy="N",
            cu_rated_sensible_kw=20.00,
            cu_design_airflow_cfm=3000,
            cu_supply_delta_t_f=12.0,
        )
        leakage_test(ctx["zone_id"], 5.00, 20.0)
        ctx["rack_1"] = create_rack(
            ctx["hall_id"], ctx["zone_id"], "A", 1, design_kw=15.00
        )
        reserve_feed(ctx["rack_1"]["id"], ctx["bw_a"]["id"], "A", 7.50, 32)
        reserve_feed(ctx["rack_1"]["id"], ctx["bw_b"]["id"], "B", 7.50, 32)
        install_rack(ctx["rack_1"]["id"], "AT-7601")
        return ctx

    def test_measured_airflow_one_cfm_short_of_ninety_percent_is_refused(self):
        """2699 cfm against a 3000 cfm design misses the 2700 cfm floor and is refused
        `ERR_AIRFLOW_BELOW_DESIGN`; 2700 cfm exactly is admitted and publishes
        9.74279 kW.

        PRD: "It requires the hall to be in `FIT_OUT`, `COMMISSIONING` or `LIVE`, and it requires the measured airflow to reach at least ninety percent of `design_airflow_cfm`; a unit that cannot move the air it was specified for is refused with `ERR_AIRFLOW_BELOW_DESIGN`."

        Design: Corner/errors/cooling_acceptance_floor_and_thermal_margin_errors
        """
        ctx = self._hall_with_a_small_cooling_unit()

        validate_error(
            api_client.commission_cooling_unit(
                ctx["cu_1"]["id"], {"measured_airflow_cfm": 2699}, MC
            ),
            ApiErrorId.ERR_AIRFLOW_BELOW_DESIGN.value,
            422,
        )
        refused = read_cooling_unit(ctx["cu_1"]["id"])
        assert refused["status"] == "INSTALLED"
        assert refused["measured_airflow_cfm"] is None
        assert refused["airflow_capacity_kw"] == pytest.approx(0.00, abs=0.005)

        accepted = commission_cooling_unit(ctx["cu_1"]["id"], 2700)
        assert accepted["status"] == "COMMISSIONED"
        assert accepted["measured_airflow_cfm"] == 2700
        assert accepted["airflow_capacity_kw"] == pytest.approx(
            9.74279, abs=0.000005
        ), "2700 cfm at 5 percent leakage, 12.0 F and the 1.08 coefficient over 3412"

    def test_the_airflow_variant_gates_the_margin_even_under_a_generous_nameplate(self):
        """The unit's 20.00 kW nameplate would carry the rack's 12.75 kW diversified load,
        but the airflow variant gates at 9.74 kW, so power-on is refused
        `ERR_COOLING_MARGIN_EXCEEDED`.

        PRD: "The hall's `cooling_margin_kw`, recomputed with this position's heat load included, is at least 0.00; otherwise `ERR_COOLING_MARGIN_EXCEEDED`."

        PRD: "`cooling_capacity_kw` is the smaller of the two variants, and `cooling_margin_kw` is that gating capacity less `thermal_load_kw`, rounded to two decimal places."

        Design: Corner/errors/cooling_acceptance_floor_and_thermal_margin_errors
        """
        ctx = self._hall_with_a_small_cooling_unit()
        commission_cooling_unit(ctx["cu_1"]["id"], 2700)
        place_unit_in_service(ctx["cu_1"]["id"])

        before = read_hall(ctx["hall_id"])
        assert before["cooling_capacity_nameplate_kw"] == pytest.approx(
            20.00, abs=0.005
        )
        assert before["cooling_capacity_airflow_kw"] == pytest.approx(9.74, abs=0.005)
        assert before["cooling_capacity_kw"] == pytest.approx(9.74, abs=0.005), (
            "the smaller of the two variants gates the room"
        )
        assert before["thermal_load_kw"] == pytest.approx(0.00, abs=0.005)

        validate_error(
            api_client.power_on_rack(ctx["rack_1"]["id"], EC),
            ApiErrorId.ERR_COOLING_MARGIN_EXCEEDED.value,
            422,
        )

        rack = read_rack(ctx["rack_1"]["id"])
        assert rack["status"] == "INSTALLED"
        assert rack["energized_feed_count"] == 0
        after = read_hall(ctx["hall_id"])
        assert after["thermal_load_kw"] == pytest.approx(0.00, abs=0.005), (
            "the refused candidate load was never committed to the model"
        )
        assert after["cooling_margin_kw"] == pytest.approx(9.74, abs=0.005)
        assert after["thermal_posture"] == "NOMINAL"

    def test_a_second_identical_unit_doubles_the_airflow_variant_and_admits_the_rack(self):
        """Two 2700 cfm units publish 19.49 kW of airflow capacity, which clears the
        12.75 kW diversified load with a 6.74 kW margin, so the same power-on succeeds.

        PRD: "Gross airflow capacity is the sum of those per-unit figures across the duty set, and — exactly as in the nameplate variant — when `cooling_redundancy` is `N_PLUS_1` and the duty set is non-empty the largest single per-unit figure is subtracted."

        PRD: "When the hall's `cooling_redundancy` is `N_PLUS_1` and the duty set is non-empty, the largest single `rated_sensible_kw` in the duty set is subtracted from that gross figure; when the stance is `N`, nothing is subtracted."

        Design: Corner/errors/cooling_acceptance_floor_and_thermal_margin_errors
        """
        ctx = self._hall_with_a_small_cooling_unit()
        commission_cooling_unit(ctx["cu_1"]["id"], 2700)
        place_unit_in_service(ctx["cu_1"]["id"])

        cu_2 = create_cooling_unit(
            ctx["hall_id"],
            "CU-2",
            rated_sensible_kw=20.00,
            design_airflow_cfm=3000,
            supply_delta_t_f=12.0,
        )
        commission_cooling_unit(cu_2["id"], 2700)
        place_unit_in_service(cu_2["id"])

        doubled = read_hall(ctx["hall_id"])
        assert doubled["cooling_capacity_airflow_kw"] == pytest.approx(
            19.49, abs=0.005
        ), "two per-unit figures of 9.74279 sum to 19.48558 and publish as 19.49"
        assert doubled["cooling_capacity_nameplate_kw"] == pytest.approx(
            40.00, abs=0.005
        )
        assert doubled["cooling_capacity_kw"] == pytest.approx(19.49, abs=0.005)

        powered = power_on_rack(ctx["rack_1"]["id"])
        assert powered["status"] == "POWERED"
        assert powered["energized_feed_count"] == 2
        assert powered["chargeable_kw"] == pytest.approx(15.68, abs=0.005)

        hall = read_hall(ctx["hall_id"])
        assert hall["thermal_load_kw"] == pytest.approx(12.75, abs=0.005), (
            "15.00 kW at the 0.85 diversity factor"
        )
        assert hall["cooling_margin_kw"] == pytest.approx(6.74, abs=0.005)
        assert hall["thermal_posture"] == "NOMINAL"
        assert hall["custody_ops_count"] == 1
        assert hall["custody_fitout_count"] == 0


class TestTenantContractCeiling:
    """The entitlement ceiling is an aggregate over the tenant's non-planned racks, so
    the position that breaches it is decided by what is already installed."""

    def _tenant_at_ten_kilowatts_with_three_positions(self):
        tenant = create_tenant("TN77", name="Ceiling Tenant", contracted_kw=10.00)
        ctx = setup_fit_out_hall("CX77", tenant_mode="MULTI_TENANT")
        ctx["tenant"] = tenant
        for key, col, design_kw in (
            ("rack_big", 1, 8.00),
            ("rack_exact", 2, 2.00),
            ("rack_over", 3, 1.00),
        ):
            ctx[key] = create_rack(
                ctx["hall_id"],
                ctx["zone_id"],
                "A",
                col,
                design_kw=design_kw,
                required_feed_count=1,
                tenant_id=tenant["id"],
            )
        return ctx

    def test_installations_may_land_exactly_on_the_contracted_ceiling(self):
        """8.00 kW then 2.00 kW bring the tenant to exactly its 10.00 kW entitlement, and
        both installations are admitted because the test is a ceiling, not a strict
        inequality.

        PRD: "A tenant's `allocated_kw` opens at 0.00 and is thereafter always the sum of the designed density of every rack allocated to that tenant whose status is anything other than `PLANNED` — a planned rack position reserves floor space but books no entitlement."

        Design: Corner/errors/tenant_contract_ceiling_is_an_aggregate_over_installed_racks
        """
        ctx = self._tenant_at_ten_kilowatts_with_three_positions()
        assert _read_tenant(ctx["tenant"]["id"])["allocated_kw"] == pytest.approx(
            0.00, abs=0.005
        )

        first = install_rack(ctx["rack_big"]["id"], "AT-7701")
        assert first["status"] == "INSTALLED"
        assert _read_tenant(ctx["tenant"]["id"])["allocated_kw"] == pytest.approx(
            8.00, abs=0.005
        )

        second = install_rack(ctx["rack_exact"]["id"], "AT-7702")
        assert second["status"] == "INSTALLED"
        assert _read_tenant(ctx["tenant"]["id"])["allocated_kw"] == pytest.approx(
            10.00, abs=0.005
        ), "landing exactly on the entitlement is lawful"

    def test_the_one_kilowatt_position_that_crosses_the_ceiling_is_refused(self):
        """With the tenant already at its 10.00 kW entitlement, installing a further
        1.00 kW position is refused `ERR_TENANT_CONTRACT_EXCEEDED`; the position stays
        PLANNED, keeps a null asset tag and contributes nothing to the roll-up.

        PRD: "The tenant's `allocated_kw` then grows by the position's designed density, and if that would carry the tenant above its `contracted_kw` entitlement the installation is refused with `ERR_TENANT_CONTRACT_EXCEEDED`."

        Design: Corner/errors/tenant_contract_ceiling_is_an_aggregate_over_installed_racks
        """
        ctx = self._tenant_at_ten_kilowatts_with_three_positions()
        install_rack(ctx["rack_big"]["id"], "AT-7701")
        install_rack(ctx["rack_exact"]["id"], "AT-7702")

        validate_error(
            api_client.install_rack(
                ctx["rack_over"]["id"], {"asset_tag": "AT-7703"}, FP
            ),
            ApiErrorId.ERR_TENANT_CONTRACT_EXCEEDED.value,
            422,
        )

        assert _read_tenant(ctx["tenant"]["id"])["allocated_kw"] == pytest.approx(
            10.00, abs=0.005
        ), "the refused installation booked nothing"
        refused = read_rack(ctx["rack_over"]["id"])
        assert refused["status"] == "PLANNED"
        assert refused["asset_tag"] is None, (
            "the asset tag offered with a refused installation is not stored"
        )

        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["rack_total_count"] == 3
        assert summary["custody_fitout_count"] == 3, (
            "PLANNED and INSTALLED positions are both in fit-out custody"
        )
        assert summary["custody_ops_count"] == 0
        assert summary["chargeable_kw"] == pytest.approx(10.45, abs=0.005), (
            "8.36 plus 2.09; the PLANNED position never contributes"
        )


class TestReleaseSubmitGates:
    """The three submission gates fire in their own order: an empty scope, then
    incomplete tagging, then the cage's two security floors."""

    def _two_packets_one_empty_one_untagged(self):
        tenant = create_tenant("TN78", name="Handover Tenant", contracted_kw=100.00)
        ctx = setup_fit_out_hall("CX78", tenant_mode="MULTI_TENANT")
        ctx["tenant"] = tenant
        ctx["tenant_id"] = tenant["id"]
        prove_zone_and_cooling(ctx)
        ctx["cage_empty"] = create_cage(
            ctx["hall_id"], tenant["id"], "CG-1", perimeter_length_m=40.0
        )
        ctx["cage_full"] = create_cage(
            ctx["hall_id"], tenant["id"], "CG-2", perimeter_length_m=40.0
        )
        rack = create_rack(
            ctx["hall_id"],
            ctx["zone_id"],
            "A",
            1,
            design_kw=15.00,
            cage_id=ctx["cage_full"]["id"],
            tenant_id=tenant["id"],
        )
        ctx["rack_1"] = rack
        reserve_feed(rack["id"], ctx["bw_a"]["id"], "A", 7.50, 32)
        reserve_feed(rack["id"], ctx["bw_b"]["id"], "B", 7.50, 32)
        install_rack(rack["id"])
        ctx["rack_1"] = power_on_rack(rack["id"])
        assert ctx["rack_1"]["status"] == "POWERED"
        assert ctx["rack_1"]["asset_tag"] is None
        ctx["packet_empty"] = create_packet(
            ctx["hall_id"], ctx["cage_empty"]["id"], "AB-CX78-CG1"
        )
        ctx["packet_full"] = create_packet(
            ctx["hall_id"], ctx["cage_full"]["id"], "AB-CX78-CG2"
        )
        return ctx

    def test_a_cage_with_no_energised_rack_cannot_be_handed_over(self):
        """The empty cage's packet has nothing in scope, so submission is refused
        `ERR_RELEASE_SCOPE_EMPTY` and its tagging figure reads 0.00, not 100.00.

        PRD: "The scope must be non-empty — `rack_in_scope_count` at least 1 — or the request is refused with `ERR_RELEASE_SCOPE_EMPTY`."

        PRD: "When `rack_in_scope_count` is 0 the percentage is 0.00, **not** 100.00: an empty scope is vacuously untagged, not vacuously complete."

        Design: Corner/errors/release_packet_submit_gate_errors_scope_tags_and_cage_coverage
        """
        ctx = self._two_packets_one_empty_one_untagged()

        validate_error(
            api_client.submit_release_packet(ctx["packet_empty"]["id"], CA),
            ApiErrorId.ERR_RELEASE_SCOPE_EMPTY.value,
            422,
        )

        packet = read_packet(ctx["packet_empty"]["id"])
        assert packet["status"] == "DRAFT"
        assert packet["rack_in_scope_count"] == 0
        assert packet["asset_tag_completion_pct"] == pytest.approx(0.00, abs=0.005)
        assert packet["released_kw"] == pytest.approx(0.00, abs=0.005)

    def test_an_untagged_rack_holds_the_handover_at_zero_percent(self):
        """The occupied cage's packet already carries the 15.68 kW it would release, and
        submission is still refused `ERR_ASSET_TAGS_INCOMPLETE` until the rack is tagged;
        the tagging write re-derives the DRAFT packet on the spot.

        PRD: "Asset tagging must be exactly complete — `asset_tag_completion_pct` equal to 100.00, with no tolerance — or the request is refused with `ERR_ASSET_TAGS_INCOMPLETE`; a cage of forty racks with thirty-nine tagged sits at 97.50 and does not submit."

        PRD: "Doing so re-derives the asset-tag completion figure of any release packet of that rack's cage that is still in `DRAFT`, since a packet under assembly must always reflect the current tagging reality."

        Design: Corner/errors/release_packet_submit_gate_errors_scope_tags_and_cage_coverage
        """
        ctx = self._two_packets_one_empty_one_untagged()

        validate_error(
            api_client.submit_release_packet(ctx["packet_full"]["id"], CA),
            ApiErrorId.ERR_ASSET_TAGS_INCOMPLETE.value,
            422,
        )

        before = read_packet(ctx["packet_full"]["id"])
        assert before["status"] == "DRAFT"
        assert before["rack_in_scope_count"] == 1
        assert before["asset_tag_completion_pct"] == pytest.approx(0.00, abs=0.005)
        assert before["released_kw"] == pytest.approx(15.68, abs=0.005), (
            "the cage-restricted roll-up rounds 15.00 times 1.045 to 15.68 first"
        )

        tagged = tag_rack(ctx["rack_1"]["id"], "AT-7801")
        assert tagged["asset_tag"] == "AT-7801"
        after = read_packet(ctx["packet_full"]["id"])
        assert after["asset_tag_completion_pct"] == pytest.approx(100.00, abs=0.005)
        assert after["status"] == "DRAFT", "the tagging write does not submit the packet"

    def test_camera_coverage_short_of_the_floor_blocks_the_submission(self):
        """With the tagging complete the next refusal is the cage's coverage floor: no
        active camera reads 0.00 percent, and a single camera seeing 30.0 of 40.0 metres
        reads 75.00 percent, both short of the 95.00 percent requirement.

        PRD: "And the cage's physical security must meet both of its floors: `camera_coverage_pct` at or above `required_camera_coverage_pct`, **and** `active_reader_zone_count` at or above `required_reader_zone_count`."

        Design: Corner/errors/release_packet_submit_gate_errors_scope_tags_and_cage_coverage
        """
        ctx = self._two_packets_one_empty_one_untagged()
        tag_rack(ctx["rack_1"]["id"], "AT-7801")

        assert read_cage(ctx["cage_full"]["id"])["camera_coverage_pct"] == (
            pytest.approx(0.00, abs=0.005)
        )
        validate_error(
            api_client.submit_release_packet(ctx["packet_full"]["id"], CA),
            ApiErrorId.ERR_CAGE_COVERAGE_INSUFFICIENT.value,
            422,
        )

        camera_1 = create_camera(ctx["cage_full"]["id"], "CAM-1", 30.0)
        assert read_cage(ctx["cage_full"]["id"])["camera_coverage_pct"] == (
            pytest.approx(0.00, abs=0.005)
        ), "a PLANNED camera contributes nothing to coverage"
        commission_device(camera_1["id"])

        partial = read_cage(ctx["cage_full"]["id"])
        assert partial["camera_coverage_pct"] == pytest.approx(75.00, abs=0.005)
        assert partial["active_reader_zone_count"] == 0
        assert partial["operational_status"] == "FIT_OUT"

        validate_error(
            api_client.submit_release_packet(ctx["packet_full"]["id"], CA),
            ApiErrorId.ERR_CAGE_COVERAGE_INSUFFICIENT.value,
            422,
        )
        assert read_packet(ctx["packet_full"]["id"])["status"] == "DRAFT"

    def test_full_coverage_still_needs_the_second_reader_zone(self):
        """Two cameras reach 100.00 percent coverage and a single reader zone is still one
        short of the cage's requirement of two; the second zone secures the cage and the
        packet finally submits with 15.68 kW frozen for review.

        PRD: "`active_reader_zone_count` is the number of **distinct** `reader_zone_label` values among the cage's `ACTIVE` card readers — two readers arming the same zone count once."

        PRD: "On success `released_kw` and `asset_tag_completion_pct` are frozen for the review, so that operations reviews the numbers the agent submitted."

        Design: Corner/errors/release_packet_submit_gate_errors_scope_tags_and_cage_coverage
        """
        ctx = self._two_packets_one_empty_one_untagged()
        tag_rack(ctx["rack_1"]["id"], "AT-7801")
        cage_id = ctx["cage_full"]["id"]
        commission_device(create_camera(cage_id, "CAM-1", 30.0)["id"])
        commission_device(create_camera(cage_id, "CAM-2", 10.0)["id"])

        covered = read_cage(cage_id)
        assert covered["camera_coverage_pct"] == pytest.approx(100.00, abs=0.005)
        assert covered["operational_status"] == "FIT_OUT", (
            "coverage alone does not secure the cage"
        )

        commission_device(create_card_reader(cage_id, "RD-1", "Z-N")["id"])
        one_zone = read_cage(cage_id)
        assert one_zone["active_reader_zone_count"] == 1
        assert one_zone["operational_status"] == "FIT_OUT"
        validate_error(
            api_client.submit_release_packet(ctx["packet_full"]["id"], CA),
            ApiErrorId.ERR_CAGE_COVERAGE_INSUFFICIENT.value,
            422,
        )

        commission_device(create_card_reader(cage_id, "RD-2", "Z-S")["id"])
        secured = read_cage(cage_id)
        assert secured["active_reader_zone_count"] == 2
        assert secured["operational_status"] == "SECURED"

        submitted = submit_packet(ctx["packet_full"]["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["rack_in_scope_count"] == 1
        assert submitted["asset_tag_completion_pct"] == pytest.approx(100.00, abs=0.005)
        assert submitted["released_kw"] == pytest.approx(15.68, abs=0.005)
        assert read_packet(ctx["packet_empty"]["id"])["status"] == "DRAFT", (
            "the other cage's packet is untouched"
        )


class TestLiveSpaceChangeControl:
    """Three refusals that only exist once the room carries load: work without a
    covering MOP, a MOP classified too low to touch a busway, and a handover attempted
    while a change is live."""

    def _live_hall_with_a_submitted_packet(self):
        ctx = setup_live_hall_with_caged_rack(
            "CX79",
            tenant_code="TN79",
            contracted_kw=80.00,
            rack_design_kw=15.00,
            rack_asset_tag="AT-7901",
            camera_coverage_m=40.0,
            tenant_mode="MULTI_TENANT",
        )
        assert ctx["hall"]["status"] == "LIVE"
        packet = create_packet(ctx["hall_id"], ctx["cage_id"], "AB-CX79")
        ctx["packet"] = submit_packet(packet["id"])
        assert ctx["packet"]["status"] == "SUBMITTED"
        return ctx

    def test_recording_a_derate_in_a_live_hall_needs_a_covering_mop(self):
        """A newly added unit in the LIVE hall is at `PLANNED`, so its derate write is a
        lawful transition and is nonetheless refused `ERR_MOP_REQUIRED` because no MOP is
        in execution.

        PRD: "In a hall that has already gone `LIVE`, this write is live-space work: it requires a covering method of procedure to be in execution, either targeting this unit's own busway or otherwise naming it, and without one it is refused with `ERR_MOP_REQUIRED`."

        Design: Corner/errors/live_space_change_control_errors_mop_required_risk_class_and_locked_posture
        """
        ctx = self._live_hall_with_a_submitted_packet()
        pdu_c = create_pdu(ctx["hall_id"], "PDU-C1", "A", rated_kw=300.00)
        assert pdu_c["status"] == "PLANNED"

        validate_error(
            api_client.patch_pdu(
                pdu_c["id"], {"measured_derate_factor": 0.98}, EC
            ),
            ApiErrorId.ERR_MOP_REQUIRED.value,
            409,
        )

        after = read_pdu(pdu_c["id"])
        assert after["status"] == "PLANNED", "the refused write left the unit uncommissioned"
        assert after["measured_derate_factor"] == pytest.approx(1.00, abs=0.005)
        assert after["usable_cap_kw"] == pytest.approx(240.000, abs=0.0005), (
            "the unit-level ceiling is still the nameplate at the continuous-load factor"
        )

    def test_busway_work_in_a_live_hall_must_be_classified_high(self):
        """A MEDIUM-risk MOP against a busway in a LIVE hall drafts happily and cannot
        leave `DRAFT`: submission is refused `ERR_RISK_CLASS_TOO_LOW`, while the same work
        classified HIGH submits and asks for two approvals.

        PRD: "And there is a risk floor: when the hall is `LIVE` and the target type is `BUSWAY` or `COOLING_UNIT`, the MOP's `risk_class` must be `HIGH` before it may leave `DRAFT`, since isolating a busway or pulling a cooling unit out of duty in an occupied room is never routine."

        Design: Corner/errors/live_space_change_control_errors_mop_required_risk_class_and_locked_posture
        """
        ctx = self._live_hall_with_a_submitted_packet()
        medium = create_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_a"]["id"],
            title="Routine busway inspection",
            risk_class="MEDIUM",
            window_start="2026-08-07T02:00:00Z",
            window_end="2026-08-07T06:00:00Z",
            author_user_id="u-elec-1",
        )
        assert medium["status"] == "DRAFT"
        assert medium["required_approval_count"] == 0

        validate_error(
            api_client.submit_mop(
                medium["id"], make_headers("u-elec-1", "ElectricalContractor")
            ),
            ApiErrorId.ERR_RISK_CLASS_TOO_LOW.value,
            422,
        )
        assert read_mop(medium["id"])["status"] == "DRAFT"

        high = create_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_a"]["id"],
            title="Busway isolation",
            risk_class="HIGH",
            window_start="2026-08-07T02:00:00Z",
            window_end="2026-08-07T06:00:00Z",
            author_user_id="u-elec-1",
        )
        submitted = submit_mop(high["id"], author_user_id="u-elec-1")
        assert submitted["status"] == "UNDER_REVIEW"
        assert submitted["required_approval_count"] == 2

    def test_a_locked_posture_blocks_acceptance_until_the_mop_closes(self):
        """Executing the HIGH-risk busway MOP strips the rack of a feed and locks the
        hall, so acceptance is refused `ERR_RELEASE_POSTURE_BLOCKED`; closing the MOP
        compensates the cascade exactly and the same acceptance then succeeds.

        PRD: "A posture that is `LOCKED` or `RESTRICTED`, or a `POWERED` rack short of a feed, is refused with `ERR_RELEASE_POSTURE_BLOCKED`."

        Design: Corner/errors/live_space_change_control_errors_mop_required_risk_class_and_locked_posture
        """
        ctx = self._live_hall_with_a_submitted_packet()
        mop = setup_executing_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_a"]["id"],
            risk_class="HIGH",
            window_start="2026-08-07T02:00:00Z",
            window_end="2026-08-07T06:00:00Z",
            clock_inside="2026-08-07T03:00:00Z",
            author_user_id="u-elec-1",
            tenant_notified_ids=[ctx["tenant_id"]],
        )
        assert mop["status"] == "IN_EXECUTION"
        assert mop["pre_execution_target_state"] == "ENERGIZED"

        locked = read_hall(ctx["hall_id"])
        assert locked["release_posture"] == "LOCKED"
        assert locked["at_risk_rack_count"] == 1
        assert read_rack(ctx["rack_1"]["id"])["status"] == "AT_RISK"
        assert read_cage(ctx["cage_id"])["operational_status"] == "DEGRADED"

        validate_error(
            api_client.accept_release_packet(ctx["packet"]["id"], OM),
            ApiErrorId.ERR_RELEASE_POSTURE_BLOCKED.value,
            409,
        )
        blocked_packet = read_packet(ctx["packet"]["id"])
        assert blocked_packet["status"] == "SUBMITTED"
        assert blocked_packet["accepted_by_user_id"] is None

        closed = close_mop(mop["id"], author_user_id="u-elec-1")
        assert closed["status"] == "CLOSED"
        reopened = read_hall(ctx["hall_id"])
        assert reopened["release_posture"] == "OPEN"
        assert reopened["at_risk_rack_count"] == 0
        assert read_rack(ctx["rack_1"]["id"])["status"] == "POWERED"
        assert read_cage(ctx["cage_id"])["operational_status"] == "SECURED"

        accepted = validate_success(
            api_client.accept_release_packet(ctx["packet"]["id"], OM), 200
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["accepted_by_user_id"] == "u-om-1"
        assert accepted["released_kw"] == pytest.approx(15.68, abs=0.005)
        assert read_rack(ctx["rack_1"]["id"])["status"] == "RELEASED"
        assert read_cage(ctx["cage_id"])["operational_status"] == "RELEASED"
