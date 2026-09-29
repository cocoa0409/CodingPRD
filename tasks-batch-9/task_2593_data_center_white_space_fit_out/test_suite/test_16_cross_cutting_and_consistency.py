"""Cross-cutting layers: the two optimistic-concurrency tokens, the two shapes of
tenant isolation, the tenant-scoped label namespace, and the immediate visibility of
every derived field in the response that caused it."""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    CA,
    EC,
    FP,
    SA,
    TENANT_REP,
    create_cage,
    create_hall,
    create_package,
    create_packet,
    create_rack,
    create_tenant,
    create_zone,
    prove_zone_and_cooling,
    read_busway,
    read_cage,
    read_cage_version,
    read_capacity_summary,
    read_feed,
    read_hall,
    read_hall_version,
    read_package,
    read_packet,
    read_rack,
    reserve_feed,
    setup_commissioning_hall,
    setup_fit_out_hall,
)


def _packet_request(hall_id, cage_id, ref, expected_cage_version):
    return api_client.create_release_packet(
        {
            "hall_id": hall_id,
            "cage_id": cage_id,
            "as_built_drawing_ref": ref,
            "expected_cage_version": expected_cage_version,
        },
        CA,
    )


def _package_request(hall_id, title, expected_hall_version):
    return api_client.create_commissioning_package(
        {
            "hall_id": hall_id,
            "level": "L4",
            "title": title,
            "target_load_kw": 10.00,
            "expected_hall_version": expected_hall_version,
        },
        CA,
    )


class TestReleasePacketCageVersionToken:
    """Packet creation is never state-blocked, so the cage version token is the only
    thing standing between a second agent and a blind supersede."""

    def _cage_awaiting_its_first_packet(self):
        hall = create_hall(
            "CX89", name="OCC Cage Hall", tenant_mode="MULTI_TENANT",
            design_kw_capacity=400.00,
        )
        tenant = create_tenant("TN89", name="Tenant 89", contracted_kw=50.00)
        cage = create_cage(hall["id"], tenant["id"], "CG-1", perimeter_length_m=40.0)
        return {
            "hall_id": hall["id"],
            "tenant_id": tenant["id"],
            "cage_id": cage["id"],
            "cage_v1": read_cage_version(cage["id"]),
        }

    def test_the_token_spent_by_the_first_packet_is_refused_for_the_second(self):
        """The first packet is opened against the cage version the agent read; the very
        same token replayed is refused with 412 because opening the first packet moved
        the cage on by exactly one, and the refusal writes nothing at all.

        PRD §2.8: "If that value does not equal the cage's current `version` — because a
        device commissioning, a rack cascade or an earlier packet acceptance has advanced
        it since the client read the cage — the request is rejected with
        `ERR_STALE_CAGE_VERSION` (HTTP 412)."

        Design: Corner/cross-cutting complexity layers/optimistic_concurrency_on_cage_version_for_release_packets
        """
        ctx = self._cage_awaiting_its_first_packet()
        first = validate_success(
            _packet_request(
                ctx["hall_id"], ctx["cage_id"], "AB-CX89-CG1-r1", ctx["cage_v1"]
            ),
            201,
        )
        assert first["status"] == "DRAFT"
        assert first["as_built_drawing_ref"] == "AB-CX89-CG1-r1"

        validate_error(
            _packet_request(
                ctx["hall_id"], ctx["cage_id"], "AB-CX89-CG1-r2", ctx["cage_v1"]
            ),
            ApiErrorId.ERR_STALE_CAGE_VERSION.value,
            412,
        )

        rows, meta = validate_paginated(
            api_client.list_release_packets(FP, {"cage_id": ctx["cage_id"]})
        )
        assert meta["total_count"] == 1, "the refused create wrote nothing"
        assert [row["id"] for row in rows] == [first["id"]]
        assert read_cage_version(ctx["cage_id"]) == ctx["cage_v1"] + 1, (
            "packet creation bumped the cage once, and the refusal did not bump it again"
        )

    def test_every_successful_create_invalidates_the_token_again(self):
        """A refreshed token lets the second packet in, and that create spends the
        refreshed token in turn, so a third packet replaying it is refused; the DRAFT
        predecessor is left standing because DRAFT is not a live claim to supersede.

        PRD §3.9: "Opening a packet for a cage that already has a packet at `SUBMITTED`,
        `ACCEPTED` or `SUSPENDED` supersedes that prior packet: the prior packet's status
        becomes `SUPERSEDED`, which is terminal, and the new packet's
        `supersedes_packet_id` records the prior packet's identifier."

        PRD §3.9: "The create also increments the cage's `version`, which is why the
        version check matters: a second agent working from a stale cage view would
        silently discard a submission in flight, and `ERR_STALE_CAGE_VERSION` with status
        412 is what prevents it."

        Design: Corner/cross-cutting complexity layers/optimistic_concurrency_on_cage_version_for_release_packets
        """
        ctx = self._cage_awaiting_its_first_packet()
        first = create_packet(
            ctx["hall_id"],
            ctx["cage_id"],
            "AB-CX89-CG1-r1",
            expected_cage_version=ctx["cage_v1"],
        )
        cage_v2 = read_cage_version(ctx["cage_id"])
        assert cage_v2 == ctx["cage_v1"] + 1

        second = validate_success(
            _packet_request(
                ctx["hall_id"], ctx["cage_id"], "AB-CX89-CG1-r2", cage_v2
            ),
            201,
        )
        assert second["status"] == "DRAFT"
        assert second["as_built_drawing_ref"] == "AB-CX89-CG1-r2"
        assert second["supersedes_packet_id"] is None, (
            "a DRAFT predecessor is not one of the three superseded statuses"
        )
        assert read_packet(first["id"])["status"] == "DRAFT"

        validate_error(
            _packet_request(
                ctx["hall_id"], ctx["cage_id"], "AB-CX89-CG1-r3", cage_v2
            ),
            ApiErrorId.ERR_STALE_CAGE_VERSION.value,
            412,
        )

        assert read_cage_version(ctx["cage_id"]) == ctx["cage_v1"] + 2, (
            "two successful creates and two bumps, one per create"
        )
        _, meta = validate_paginated(
            api_client.list_release_packets(FP, {"cage_id": ctx["cage_id"]})
        )
        assert meta["total_count"] == 2


class TestCommissioningPackageHallVersionToken:
    """The hall token is invalidated by traffic that has nothing to do with
    commissioning, which is exactly what forces the agent to re-read the room."""

    def _commissioning_hall_with_a_spare_position(self):
        ctx = setup_commissioning_hall(
            "CX90",
            rack_design_kw=15.00,
            rack_feed_kw=7.50,
            rack_asset_tag="AT-0601",
            design_kw_capacity=400.00,
        )
        ctx["rack_2"] = create_rack(
            ctx["hall_id"], ctx["zone_id"], "A", 2, design_kw=10.00
        )
        ctx["hall_v1"] = read_hall_version(ctx["hall_id"])
        return ctx

    def test_the_first_package_spends_the_token_and_the_replay_is_refused(self):
        """The L4 package is opened against the hall version the agent read; replaying
        that same version is refused with 412, because the create it authorised
        incremented the hall itself.

        PRD §2.8: "Opening a commissioning package requires a non-optional
        `expected_hall_version` field carrying the client's last observed `version` of the
        target `Hall`. A mismatch with the hall's current `version` is rejected with
        `ERR_STALE_HALL_VERSION` (HTTP 412)."

        Design: Corner/cross-cutting complexity layers/optimistic_concurrency_on_hall_version_for_commissioning_packages
        """
        ctx = self._commissioning_hall_with_a_spare_position()
        first = validate_success(
            _package_request(ctx["hall_id"], "L4 first attempt", ctx["hall_v1"]), 201
        )
        assert first["level"] == "L4"
        assert first["package_state"] == "DRAFT"
        assert first["script_status"] == "NOT_STARTED"

        validate_error(
            _package_request(ctx["hall_id"], "L4 blind supersede", ctx["hall_v1"]),
            ApiErrorId.ERR_STALE_HALL_VERSION.value,
            412,
        )

        hall = read_hall(ctx["hall_id"])
        assert hall["version"] == ctx["hall_v1"] + 1, (
            "the successful create bumped the hall once; the refusal did not bump it"
        )
        assert hall["committed_kw"] == pytest.approx(15.00, abs=0.005)
        _, meta = validate_paginated(
            api_client.list_commissioning_packages(FP, {"hall_id": ctx["hall_id"]})
        )
        assert meta["total_count"] == 1, "the refused create wrote no package"

    def test_an_unrelated_feed_reservation_invalidates_the_commissioning_token(self):
        """A 5.00 kW reservation on a completely different rack position moves the hall
        on, so a package token that was current a moment ago is stale — the agent is made
        to re-read a room whose committed load has changed underneath it.

        PRD §2.8: "Because every feed reservation, every feed release, every rack
        power-on, every posture recompute and every phase advance increments the hall's
        `version`, this forces the commissioning agent to re-read the hall's
        `committed_kw`, its reserve tier and its postures before superseding a package for
        the same hall and level."

        Design: Corner/cross-cutting complexity layers/optimistic_concurrency_on_hall_version_for_commissioning_packages
        """
        ctx = self._commissioning_hall_with_a_spare_position()
        create_package(
            ctx["hall_id"],
            "L4",
            title="L4 first attempt",
            expected_hall_version=ctx["hall_v1"],
        )
        hall_v2 = read_hall_version(ctx["hall_id"])
        assert hall_v2 == ctx["hall_v1"] + 1

        reserve_feed(ctx["rack_2"]["id"], ctx["bw_a"]["id"], "A", 5.00, 32)

        validate_error(
            _package_request(
                ctx["hall_id"], "L4 after unrelated feed work", hall_v2
            ),
            ApiErrorId.ERR_STALE_HALL_VERSION.value,
            412,
        )

        hall = read_hall(ctx["hall_id"])
        assert hall["version"] == ctx["hall_v1"] + 2, (
            "the electrical reservation is what invalidated the commissioning token"
        )
        assert hall["committed_kw"] == pytest.approx(20.00, abs=0.005)
        _, meta = validate_paginated(
            api_client.list_commissioning_packages(FP, {"hall_id": ctx["hall_id"]})
        )
        assert meta["total_count"] == 1

    def test_the_refreshed_create_supersedes_the_package_of_the_same_level(self):
        """Once the agent re-reads the hall, the second L4 create lands and unconditionally
        supersedes the first, pointing the predecessor at its successor; the hall has by
        then moved on by three — two creates and the unrelated reservation.

        PRD §3.7: "Opening a package for a hall and level that already has a package whose
        `package_state` is anything other than `SUPERSEDED` supersedes that prior package:
        its `superseded_by_package_id` is set to the new package's identifier, its
        `package_state` becomes `SUPERSEDED`, and it stops participating in the hall's
        evaluation for going live."

        Design: Corner/cross-cutting complexity layers/optimistic_concurrency_on_hall_version_for_commissioning_packages
        """
        ctx = self._commissioning_hall_with_a_spare_position()
        first = create_package(
            ctx["hall_id"],
            "L4",
            title="L4 first attempt",
            expected_hall_version=ctx["hall_v1"],
        )
        reserve_feed(ctx["rack_2"]["id"], ctx["bw_a"]["id"], "A", 5.00, 32)
        hall_v3 = read_hall_version(ctx["hall_id"])
        assert hall_v3 == ctx["hall_v1"] + 2

        second = validate_success(
            _package_request(ctx["hall_id"], "L4 second attempt", hall_v3), 201
        )
        assert second["level"] == "L4"
        assert second["package_state"] == "DRAFT"

        superseded = read_package(first["id"])
        assert superseded["package_state"] == "SUPERSEDED"
        assert superseded["superseded_by_package_id"] == second["id"]

        hall = read_hall(ctx["hall_id"])
        assert hall["version"] == ctx["hall_v1"] + 3
        assert hall["status"] == "COMMISSIONING"


class TestTenantIsolationHasTwoShapes:
    """The same isolation rule refuses a point read of a foreign row and silently
    shrinks a list that spans tenants."""

    def _two_tenants_sharing_one_hall(self):
        hall = create_hall(
            "CX91", name="Isolation Hall", tenant_mode="MULTI_TENANT",
            design_kw_capacity=400.00,
        )
        tenant_a = create_tenant("TN91A", name="Tenant 91A", contracted_kw=80.00)
        tenant_b = create_tenant("TN91B", name="Tenant 91B", contracted_kw=80.00)
        zone = create_zone(hall["id"], "CA-1")
        cage_a = create_cage(hall["id"], tenant_a["id"], "CG-A")
        cage_b = create_cage(hall["id"], tenant_b["id"], "CG-B")
        rack_a = create_rack(
            hall["id"], zone["id"], "A", 1, design_kw=8.00,
            cage_id=cage_a["id"], tenant_id=tenant_a["id"],
        )
        rack_b = create_rack(
            hall["id"], zone["id"], "B", 1, design_kw=8.00,
            cage_id=cage_b["id"], tenant_id=tenant_b["id"],
        )
        rack_none = create_rack(hall["id"], zone["id"], "C", 1, design_kw=8.00)
        packet_a = create_packet(hall["id"], cage_a["id"], "AB-CX91-A")
        packet_b = create_packet(hall["id"], cage_b["id"], "AB-CX91-B")
        return {
            "hall_id": hall["id"],
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "cage_a": cage_a,
            "cage_b": cage_b,
            "rack_a": rack_a,
            "rack_b": rack_b,
            "rack_none": rack_none,
            "packet_a": packet_a,
            "packet_b": packet_b,
            "as_a": TENANT_REP(tenant_a["id"]),
        }

    def test_a_point_read_of_a_foreign_cage_rack_or_packet_is_refused(self):
        """The neighbour's cage, the neighbour's rack and the neighbour's packet are all
        403 to this tenant, while its own cage reads back normally through the very same
        credentials.

        PRD §2.1: "When `X-User-Role` is `TenantRepresentative`, addressing a single cage,
        a single rack or a single release packet that belongs to a different tenant is
        rejected with `ERR_TENANT_SCOPE_VIOLATION` (HTTP 403), and the same code is
        returned when such a caller requests the capacity-summary view of a hall in which
        its tenant owns nothing."

        Design: Corner/cross-cutting complexity layers/tenant_isolation_is_enforced_on_point_reads_and_by_filtering_lists
        """
        ctx = self._two_tenants_sharing_one_hall()
        as_a = ctx["as_a"]
        scope = ApiErrorId.ERR_TENANT_SCOPE_VIOLATION.value

        validate_error(api_client.get_cage(ctx["cage_b"]["id"], as_a), scope, 403)
        validate_error(api_client.get_rack(ctx["rack_b"]["id"], as_a), scope, 403)
        validate_error(
            api_client.get_release_packet(ctx["packet_b"]["id"], as_a), scope, 403
        )

        own = read_cage(ctx["cage_a"]["id"], as_a)
        assert own["id"] == ctx["cage_a"]["id"]
        assert own["label"] == "CG-A"
        assert own["tenant_id"] == ctx["tenant_a"]["id"]

    def test_a_position_owned_by_nobody_is_foreign_to_every_tenant(self):
        """A rack with no `tenant_id` at all is not a shared row: the ownership check
        compares the rack's tenant foreign key to the caller's identifier, and a null key
        never equals it, so the facility-owned position is 403 to this tenant as well.

        PRD §2.1: "When `X-User-Role` is `TenantRepresentative`, by contrast, `X-User-ID`
        is the `id` of the acting `Tenant`; ownership checks on any resource that
        references a `Tenant` compare the resource's tenant foreign key to `X-User-ID`,
        directly for a rack or a cage and through the owning cage for a release packet."

        Design: Corner/cross-cutting complexity layers/tenant_isolation_is_enforced_on_point_reads_and_by_filtering_lists
        """
        ctx = self._two_tenants_sharing_one_hall()
        assert read_rack(ctx["rack_none"]["id"], FP)["tenant_id"] is None, (
            "`tenant_id` allocates the position to a tenant and defaults to null"
        )
        validate_error(
            api_client.get_rack(ctx["rack_none"]["id"], ctx["as_a"]),
            ApiErrorId.ERR_TENANT_SCOPE_VIOLATION.value,
            403,
        )

    def test_a_list_that_spans_tenants_shrinks_instead_of_refusing(self):
        """Cage, rack and packet lists of a hall that holds two tenants and one
        facility-owned position come back 200 with exactly one row each for this tenant,
        while the planner sees all of them.

        PRD §2.1: "On the tenant-scoped list surfaces — cages, racks and release packets —
        results are silently filtered to the caller's own tenant rather than rejected."

        PRD §3.9: "Packet lists may be narrowed by `hall_id`, `cage_id` and `status`, and
        — because a packet is reachable from a cage and a cage is owned by a tenant — a
        `TenantRepresentative` sees only the packets of their own cages."

        Design: Corner/cross-cutting complexity layers/tenant_isolation_is_enforced_on_point_reads_and_by_filtering_lists
        """
        ctx = self._two_tenants_sharing_one_hall()
        as_a = ctx["as_a"]
        params = {"hall_id": ctx["hall_id"]}

        cages, cage_meta = validate_paginated(api_client.list_cages(as_a, params))
        assert cage_meta["total_count"] == 1
        assert [row["id"] for row in cages] == [ctx["cage_a"]["id"]]

        racks, rack_meta = validate_paginated(api_client.list_racks(as_a, params))
        assert rack_meta["total_count"] == 1, (
            "the foreign position and the facility-owned position are both absent"
        )
        assert [row["id"] for row in racks] == [ctx["rack_a"]["id"]]

        packets, packet_meta = validate_paginated(
            api_client.list_release_packets(as_a, params)
        )
        assert packet_meta["total_count"] == 1
        assert [row["id"] for row in packets] == [ctx["packet_a"]["id"]]

        _, staff_cages = validate_paginated(api_client.list_cages(FP, params))
        assert staff_cages["total_count"] == 2, "no filtering for the staff read surface"
        _, staff_racks = validate_paginated(api_client.list_racks(FP, params))
        assert staff_racks["total_count"] == 3

    def test_an_explicit_foreign_filter_intersects_to_nothing_and_is_not_a_refusal(self):
        """Asking for the neighbour's cages by name is answered, not refused: the filter
        intersects with the caller's own scope and the answer is an empty page.

        PRD §2.1: "On the tenant-scoped list surfaces — cages, racks and release packets —
        results are silently filtered to the caller's own tenant rather than rejected."

        Design: Corner/cross-cutting complexity layers/tenant_isolation_is_enforced_on_point_reads_and_by_filtering_lists
        """
        ctx = self._two_tenants_sharing_one_hall()
        rows, meta = validate_paginated(
            api_client.list_cages(
                ctx["as_a"],
                {"hall_id": ctx["hall_id"], "tenant_id": ctx["tenant_b"]["id"]},
            )
        )
        assert meta["total_count"] == 0, (
            "an explicit foreign filter is not an escape hatch"
        )
        assert rows == []

    def test_the_shared_envelope_and_a_single_tenant_row_stay_readable(self):
        """The hall this tenant occupies still yields its reconciliation view, and a
        single tenant row is outside the isolation predicate altogether, so even the
        neighbour's registration reads back.

        PRD §2.1: "`TenantRepresentative` may read halls (list and detail), the
        capacity-summary view of a hall, a single tenant, racks (list and detail), cages
        (list and detail) and release packets (list and detail) — nothing else."

        PRD §2.1: "The full set of reads governed by this rule is: cage detail, cage list,
        rack list, rack detail, release-packet list, release-packet detail, and the hall
        capacity-summary view."

        Design: Corner/cross-cutting complexity layers/tenant_isolation_is_enforced_on_point_reads_and_by_filtering_lists
        """
        ctx = self._two_tenants_sharing_one_hall()
        as_a = ctx["as_a"]

        summary = read_capacity_summary(ctx["hall_id"], as_a)
        assert summary["design_kw_capacity"] == pytest.approx(400.00, abs=0.005), (
            "the shared hall envelope stays readable to a tenant that occupies it"
        )

        neighbour = validate_success(
            api_client.get_tenant(ctx["tenant_b"]["id"], as_a)
        )
        assert neighbour["code"] == "TN91B", (
            "the tenant row is not one of the governed reads; the predicate is enumerated"
        )


class TestCageLabelNamespaceAndTenantCoherence:
    """Two tenants sharing one hall collide on the label namespace, and cage membership
    is tenant-coherent on the write side."""

    def _two_halls_and_two_tenants(self):
        hall_1 = create_hall(
            "CX92", name="Namespace Hall One", tenant_mode="MULTI_TENANT",
            design_kw_capacity=400.00,
        )
        hall_2 = create_hall(
            "CX93", name="Namespace Hall Two", tenant_mode="MULTI_TENANT",
            design_kw_capacity=400.00,
        )
        tenant_a = create_tenant("TN92A", name="Tenant 92A", contracted_kw=80.00)
        tenant_b = create_tenant("TN92B", name="Tenant 92B", contracted_kw=80.00)
        zone_1 = create_zone(hall_1["id"], "CA-1")
        cage_a = create_cage(hall_1["id"], tenant_a["id"], "CG-1")
        return {
            "hall_1": hall_1["id"],
            "hall_2": hall_2["id"],
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "zone_1": zone_1["id"],
            "cage_a": cage_a,
        }

    def _cage_request(self, hall_id, tenant_id, label):
        return api_client.create_cage(
            {
                "hall_id": hall_id,
                "tenant_id": tenant_id,
                "label": label,
                "perimeter_length_m": 30.0,
            },
            SA,
        )

    def _rack_request(self, ctx, cage_id, tenant_id=None):
        payload = {
            "hall_id": ctx["hall_1"],
            "containment_zone_id": ctx["zone_1"],
            "grid_row": "A",
            "grid_col": 1,
            "design_kw": 8.00,
            "u_height": 45,
            "cage_id": cage_id,
        }
        if tenant_id is not None:
            payload["tenant_id"] = tenant_id
        return api_client.create_rack(payload, FP)

    def test_the_label_namespace_is_the_hall_and_not_the_tenant(self):
        """`CG-1` is taken in this hall even though the second tenant's cage would be a
        private enclosure of a different tenant, while the same label is free in the other
        hall and a different label is free in this one.

        PRD §2.6: "`Hall.code` and `Tenant.code` are unique across the whole system; a
        busway `name` is unique within its parent power distribution unit; a containment
        zone `label` and a cage `label` are each unique within their hall; and a security
        device `label` is unique within its cage."

        PRD §2.6: "A collision on any of these is rejected with `ERR_DUPLICATE_CODE`
        (HTTP 409) on hall creation, tenant creation, busway creation, containment-zone
        creation, cage creation and security-device creation."

        Design: Corner/cross-cutting complexity layers/tenant_scoped_uniqueness_and_cage_tenant_coherence
        """
        ctx = self._two_halls_and_two_tenants()
        validate_error(
            self._cage_request(ctx["hall_1"], ctx["tenant_b"]["id"], "CG-1"),
            ApiErrorId.ERR_DUPLICATE_CODE.value,
            409,
        )

        elsewhere = validate_success(
            self._cage_request(ctx["hall_2"], ctx["tenant_b"]["id"], "CG-1"), 201
        )
        assert elsewhere["label"] == "CG-1"
        assert elsewhere["hall_id"] == ctx["hall_2"], (
            "the same label in a different hall is free"
        )

        free_label = validate_success(
            self._cage_request(ctx["hall_1"], ctx["tenant_b"]["id"], "CG-2"), 201
        )
        assert free_label["label"] == "CG-2"
        assert free_label["tenant_id"] == ctx["tenant_b"]["id"]

        _, first_hall = validate_paginated(
            api_client.list_cages(FP, {"hall_id": ctx["hall_1"]})
        )
        assert first_hall["total_count"] == 2, "the refused create left no cage behind"
        _, second_hall = validate_paginated(
            api_client.list_cages(FP, {"hall_id": ctx["hall_2"]})
        )
        assert second_hall["total_count"] == 1

    def test_a_cage_refuses_a_position_carrying_another_tenant(self):
        """Placing a position allocated to the second tenant inside the first tenant's
        cage makes the cage's tenant contradict a rack it contains, and the placement is
        refused with 422.

        PRD §2.5: "A rack's containment zone and its cage must both belong to the rack's
        own hall; a busway's hall is the hall of its parent power distribution unit; a
        feed's busway must sit in the same hall as the feed's rack; a release packet's cage
        must belong to the packet's hall; a load bank test's package must belong to the
        hall the caller names; and a cage's tenant may not contradict the tenant of the
        racks the cage already contains."

        Design: Corner/cross-cutting complexity layers/tenant_scoped_uniqueness_and_cage_tenant_coherence
        """
        ctx = self._two_halls_and_two_tenants()
        validate_error(
            self._rack_request(ctx, ctx["cage_a"]["id"], ctx["tenant_b"]["id"]),
            ApiErrorId.ERR_HALL_MISMATCH.value,
            422,
        )
        _, meta = validate_paginated(
            api_client.list_racks(FP, {"hall_id": ctx["hall_1"]})
        )
        assert meta["total_count"] == 0, "the refused placement wrote no position"

    def test_a_tenant_coherent_cage_in_another_hall_is_still_refused(self):
        """The second tenant's own cage is perfectly coherent with the second tenant's own
        rack, but it stands in another hall, so the placement is refused all the same.

        PRD §2.5: "Any of those disagreements is rejected with `ERR_HALL_MISMATCH`
        (HTTP 422) on rack creation, busway creation, feed reservation, release-packet
        creation and cage creation."

        Design: Corner/cross-cutting complexity layers/tenant_scoped_uniqueness_and_cage_tenant_coherence
        """
        ctx = self._two_halls_and_two_tenants()
        cage_elsewhere = validate_success(
            self._cage_request(ctx["hall_2"], ctx["tenant_b"]["id"], "CG-1"), 201
        )
        validate_error(
            self._rack_request(ctx, cage_elsewhere["id"], ctx["tenant_b"]["id"]),
            ApiErrorId.ERR_HALL_MISMATCH.value,
            422,
        )
        _, meta = validate_paginated(
            api_client.list_racks(FP, {"hall_id": ctx["hall_1"]})
        )
        assert meta["total_count"] == 0

    def test_the_coherent_placement_is_admitted_on_the_position_the_refusals_left_free(self):
        """Neither refused placement consumed grid position A/1, so the coherent position
        lands there and publishes its own uplifted density at once.

        PRD §3.4: "A new position sits at `PLANNED` with `pre_risk_status` null,
        `connected_kw` at 0.000 and `energized_feed_count` at 0, and its `chargeable_kw` is
        fixed at creation as the designed density multiplied by the rack overhead factor of
        1.045 — a four-and-a-half percent uplift covering in-cabinet losses — rounded to
        two decimal places."

        Design: Corner/cross-cutting complexity layers/tenant_scoped_uniqueness_and_cage_tenant_coherence
        """
        ctx = self._two_halls_and_two_tenants()
        cage_elsewhere = validate_success(
            self._cage_request(ctx["hall_2"], ctx["tenant_b"]["id"], "CG-1"), 201
        )
        validate_error(
            self._rack_request(ctx, ctx["cage_a"]["id"], ctx["tenant_b"]["id"]),
            ApiErrorId.ERR_HALL_MISMATCH.value,
            422,
        )
        validate_error(
            self._rack_request(ctx, cage_elsewhere["id"], ctx["tenant_b"]["id"]),
            ApiErrorId.ERR_HALL_MISMATCH.value,
            422,
        )

        admitted = validate_success(
            self._rack_request(ctx, ctx["cage_a"]["id"], ctx["tenant_a"]["id"]), 201
        )
        assert admitted["cage_id"] == ctx["cage_a"]["id"]
        assert admitted["tenant_id"] == ctx["tenant_a"]["id"]
        assert admitted["status"] == "PLANNED"
        assert admitted["chargeable_kw"] == pytest.approx(8.36, abs=0.005), (
            "8.00 kW uplifted by 1.045 is 8.36"
        )

        _, meta = validate_paginated(
            api_client.list_racks(FP, {"hall_id": ctx["hall_1"]})
        )
        assert meta["total_count"] == 1


class TestEveryDerivedFieldIsVisibleImmediately:
    """Each write's own response body already carries every field it re-derived, and the
    read that follows agrees with it exactly."""

    def _fit_out_hall_with_a_tenant_position(self):
        ctx = setup_fit_out_hall(
            "CX94",
            name="Immediate Consistency Hall",
            tenant_mode="SINGLE_TENANT",
            design_kw_capacity=400.00,
            cooling_redundancy="N",
        )
        prove_zone_and_cooling(ctx)
        ctx["tenant"] = create_tenant("TN94", name="Tenant 94", contracted_kw=80.00)
        ctx["rack_1"] = create_rack(
            ctx["hall_id"],
            ctx["zone_id"],
            "A",
            1,
            design_kw=15.00,
            tenant_id=ctx["tenant"]["id"],
        )
        return ctx

    def _feed_request(self, ctx, busway_id, feed_side):
        return api_client.create_rack_feed(
            {
                "rack_id": ctx["rack_1"]["id"],
                "busway_id": busway_id,
                "feed_side": feed_side,
                "requested_kw": 7.50,
                "breaker_amps": 32,
            },
            EC,
        )

    def _reserve_both_feeds(self, ctx):
        ctx["feed_a"] = validate_success(
            self._feed_request(ctx, ctx["bw_a"]["id"], "A"), 201
        )
        ctx["feed_b"] = validate_success(
            self._feed_request(ctx, ctx["bw_b"]["id"], "B"), 201
        )
        return ctx

    def test_the_reservation_publishes_the_run_and_the_room_ledger_at_once(self):
        """The create response already carries the stored allocation, and the busway and
        the room ledger are correct on the very first read that follows — no lag and no
        recompute-on-read.

        PRD §2.9: "Every computed field named in this document is re-derived from its
        inputs whenever any of those inputs change, within the same request, before the
        response is written."

        PRD §2.9: "A single request routinely re-derives several layers: reserving one
        branch feed re-derives that busway's `committed_kw` and `feed_count`, the rack's
        `connected_kw`, and then the whole hall power ledger; executing a method of
        procedure against a busway re-derives feed statuses, rack statuses, rack custody
        counts, cage security states, release-packet statuses, the cooling model and the
        hall's release posture."

        Design: Corner/consistency model/every_derived_field_is_visible_in_the_same_response_that_caused_it
        """
        ctx = self._fit_out_hall_with_a_tenant_position()
        first = validate_success(self._feed_request(ctx, ctx["bw_a"]["id"], "A"), 201)
        assert first["status"] == "RESERVED"
        assert first["allocated_kw"] == pytest.approx(7.500, abs=0.0005), (
            "the derived allocation is in the create response itself"
        )

        busway = read_busway(ctx["bw_a"]["id"])
        assert busway["committed_kw"] == pytest.approx(7.500, abs=0.0005)
        assert busway["feed_count"] == 1
        assert busway["usable_kw"] == pytest.approx(196.66, abs=0.005)
        assert busway["status"] == "ENERGIZED"

        after_one = read_capacity_summary(ctx["hall_id"])
        assert after_one["committed_kw"] == pytest.approx(7.50, abs=0.005)
        assert after_one["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005)
        assert after_one["spare_kw"] == pytest.approx(367.50, abs=0.005), (
            "committed plus reserve plus spare is already 400.00 on the first read"
        )

        second = validate_success(self._feed_request(ctx, ctx["bw_b"]["id"], "B"), 201)
        assert second["status"] == "RESERVED"
        assert second["allocated_kw"] == pytest.approx(7.500, abs=0.0005)

        after_two = read_capacity_summary(ctx["hall_id"])
        assert after_two["committed_kw"] == pytest.approx(15.00, abs=0.005)
        assert after_two["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005)
        assert after_two["spare_kw"] == pytest.approx(360.00, abs=0.005)

        rack = read_rack(ctx["rack_1"]["id"])
        assert rack["connected_kw"] == pytest.approx(15.000, abs=0.0005)
        assert rack["energized_feed_count"] == 0, (
            "reservation books power without energising anything"
        )
        assert rack["status"] == "PLANNED"

    def test_installation_publishes_the_uplift_and_the_tenant_allocation_at_once(self):
        """The install response already carries the position's own uplifted density, the
        tenant's entitlement has already grown on the next read, and the hall's chargeable
        roll-up and custody partition have already moved — while the heat load has not.

        PRD §3.4: "The tenant's `allocated_kw` then grows by the position's designed
        density, and if that would carry the tenant above its `contracted_kw` entitlement
        the installation is refused with `ERR_TENANT_CONTRACT_EXCEEDED`."

        PRD §3.4: "On success the hall's chargeable roll-up and its custody partition are
        both re-derived."

        PRD §3.5: "Racks at `PLANNED` or `INSTALLED` contribute no heat."

        Design: Corner/consistency model/every_derived_field_is_visible_in_the_same_response_that_caused_it
        """
        ctx = self._reserve_both_feeds(self._fit_out_hall_with_a_tenant_position())
        installed = validate_success(
            api_client.install_rack(
                ctx["rack_1"]["id"], {"asset_tag": "AT-0940"}, FP
            )
        )
        assert installed["status"] == "INSTALLED"
        assert installed["asset_tag"] == "AT-0940"
        assert installed["chargeable_kw"] == pytest.approx(15.68, abs=0.005), (
            "the rack's own derived field is in the transition response"
        )

        tenant = validate_success(
            api_client.get_tenant(ctx["tenant"]["id"], FP)
        )
        assert tenant["allocated_kw"] == pytest.approx(15.00, abs=0.005), (
            "the cross-entity tenant allocation is already reconciled"
        )

        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["chargeable_kw"] == pytest.approx(15.68, abs=0.005)
        assert summary["custody_fitout_count"] == 1
        assert summary["custody_ops_count"] == 0
        assert summary["thermal_load_kw"] == pytest.approx(0.00, abs=0.005), (
            "an installed position is chargeable but not yet a heat load"
        )

    def test_power_on_energises_every_feed_in_its_own_response(self):
        """The power-on response reports the position powered on two energised feeds, and
        the persisted rack and both feed rows agree with it immediately.

        PRD §3.4: "On success every `RESERVED` feed of the position moves to `ENERGIZED`
        and `energized_feed_count` is re-derived, the position's status becomes `POWERED`,
        the hall's `custody_ops_count` grows by one while its `custody_fitout_count` falls
        by one, the hall cooling model is re-derived so that thermal load rises, the
        custody partition is re-derived, and the hall's `version` increments."

        Design: Corner/consistency model/every_derived_field_is_visible_in_the_same_response_that_caused_it
        """
        ctx = self._reserve_both_feeds(self._fit_out_hall_with_a_tenant_position())
        validate_success(
            api_client.install_rack(ctx["rack_1"]["id"], {"asset_tag": "AT-0940"}, FP)
        )
        powered = validate_success(api_client.power_on_rack(ctx["rack_1"]["id"], EC))
        assert powered["status"] == "POWERED"
        assert powered["energized_feed_count"] == 2, (
            "the fan-out onto the feeds is reflected in the rack response body"
        )
        assert powered["connected_kw"] == pytest.approx(15.000, abs=0.0005)

        rack = read_rack(ctx["rack_1"]["id"])
        assert rack["status"] == "POWERED"
        assert rack["energized_feed_count"] == 2, (
            "the response body and the persisted row agree"
        )

        feed_a = read_feed(ctx["feed_a"]["id"])
        assert feed_a["status"] == "ENERGIZED"
        assert feed_a["allocated_kw"] == pytest.approx(7.500, abs=0.0005)

        rows, meta = validate_paginated(
            api_client.list_rack_feeds(FP, {"rack_id": ctx["rack_1"]["id"]})
        )
        assert meta["total_count"] == 2
        assert [row["status"] for row in rows] == ["ENERGIZED", "ENERGIZED"]

    def test_power_on_republishes_the_thermal_model_and_the_custody_partition(self):
        """The same energisation republishes both cooling variants, the gate, the margin
        and the posture, and moves the custody partition — all visible on the first read,
        with the power ledger untouched.

        PRD §3.5: "`thermal_load_kw` is the sum of `design_kw` over the hall's racks whose
        status is `POWERED`, `AT_RISK` or `RELEASED`, multiplied by the diversity factor
        0.85 — no hall ever runs every cabinet at its designed density simultaneously — and
        rounded to two decimal places."

        PRD §3.5: "`cooling_capacity_kw` is the smaller of the two variants, and
        `cooling_margin_kw` is that gating capacity less `thermal_load_kw`, rounded to two
        decimal places."

        Design: Corner/consistency model/every_derived_field_is_visible_in_the_same_response_that_caused_it
        """
        ctx = self._reserve_both_feeds(self._fit_out_hall_with_a_tenant_position())
        validate_success(
            api_client.install_rack(ctx["rack_1"]["id"], {"asset_tag": "AT-0940"}, FP)
        )
        validate_success(api_client.power_on_rack(ctx["rack_1"]["id"], EC))

        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["thermal_load_kw"] == pytest.approx(12.75, abs=0.005)
        assert summary["cooling_capacity_nameplate_kw"] == pytest.approx(
            200.00, abs=0.005
        )
        assert summary["cooling_capacity_airflow_kw"] == pytest.approx(
            119.08, abs=0.005
        )
        assert summary["cooling_capacity_kw"] == pytest.approx(119.08, abs=0.005), (
            "airflow is the smaller of the two variants and therefore the gate"
        )
        assert summary["cooling_margin_kw"] == pytest.approx(106.33, abs=0.005)
        assert summary["thermal_posture"] == "NOMINAL"

        assert summary["custody_ops_count"] == 1
        assert summary["custody_fitout_count"] == 0
        assert summary["rack_total_count"] == 1
        assert summary["committed_kw"] == pytest.approx(15.00, abs=0.005), (
            "the ledger is untouched by energisation while custody moves"
        )
        assert summary["chargeable_kw"] == pytest.approx(15.68, abs=0.005)
