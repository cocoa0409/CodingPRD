"""Offer lifecycle cascades: decline, release, close, supersede, auto-dispatch."""
from test_helpers import (
    DISP,
    ApiErrorId,
    accept_offer,
    add_equipment_asset,
    add_on_shift_transporter,
    close_request_ok,
    create_dispatch_offer,
    create_location,
    create_offer_payload,
    create_transport_request,
    create_travel_edge,
    decline_offer,
    get_asset,
    get_request,
    list_cleaning_tasks,
    list_equipment_assets,
    list_request_offers,
    list_requests,
    respond_to_offer,
    set_clock,
    setup_assigned_trip,
    setup_transport_site,
    setup_two_transporter_board,
    trip_event_ok,
    validate_error,
)


class TestDeclineRequeueCycle:
    def test_decline_then_release_returns_request_to_queue(self, api):
        """PRD §3.5: "The offer becomes `DECLINED` with `responded_at`
        stamped, the request's `decline_count` increments, and the declining
        transporter is appended to `excluded_transporter_ids`, removing them
        from all future selection for that request. The offer's reserved
        asset, if any, returns to `AVAILABLE`, and auto-dispatch evaluation
        runs for the freed asset."
        PRD §3.5: "`RELEASE` returns an `ASSIGNED` request to `QUEUED` and may
        be invoked by the assigned transporter or forced by a dispatcher. The
        assignment is cleared, `release_count` increments, the transporter who
        had been holding the trip is appended to `excluded_transporter_ids`,
        the assigned asset returns to `AVAILABLE` with auto-dispatch
        evaluation, and the request's `version` increments."

        Design: Difficulty/non_linear_state_machine/request_decline_requeue_cycle
        """
        board = setup_two_transporter_board()
        site, t1, t2, asset = board["site"], board["t1"], board["t2"], board["asset"]
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")
        offer1 = create_dispatch_offer(r1, transporter_id=t1["id"])
        set_clock("2026-08-01T00:03:00Z")

        # Path one back to QUEUED: the addressed transporter declines, and the
        # cascade auto-dispatches a fresh offer to the other transporter.
        decline_offer(offer1["id"], t1["id"])
        mid = get_request(r1["id"])
        assert mid["status"] == "QUEUED"
        assert mid["decline_count"] == 1
        offers, _meta = list_request_offers(r1["id"])
        assert len(offers) == 2
        assert offers[0]["status"] == "DECLINED"
        assert offers[1]["status"] == "PENDING"
        assert offers[1]["transporter_id"] == t2["id"]

        accept_offer(offers[1]["id"], t2["id"])
        assert get_request(r1["id"])["status"] == "ASSIGNED"

        # Path two back to QUEUED: the assigned transporter releases the trip.
        trip_event_ok(r1["id"], "RELEASE", transporter_id=t2["id"])
        final = get_request(r1["id"])
        assert final["status"] == "QUEUED"
        assert final["release_count"] == 1
        assert final["assigned_transporter_id"] is None
        assert sorted(final["excluded_transporter_ids"]) == sorted(
            [t1["id"], t2["id"]]), "both the decliner and the releaser are excluded"

    def test_decliner_is_excluded_from_future_selection(self, api):
        """PRD §3.5: "the declining transporter is appended to
        `excluded_transporter_ids`, removing them from all future selection
        for that request."
        PRD §3.4: "A manually named transporter must be `ON_SHIFT`, hold no
        active assignment, have no other `PENDING` offer addressed to them, and
        not appear in the request's `excluded_transporter_ids`; they must be
        `oxygen_certified` when `oxygen_required` is set; and when
        `required_equipment` is not `PORTER_ONLY`, that equipment type must
        appear in their `certified_equipment`."
        PRD §3.4: "Any such failure rejects the offer with
        `ERR_TRANSPORTER_INELIGIBLE`."

        Design: Difficulty/non_linear_state_machine/request_decline_requeue_cycle
        """
        site = setup_transport_site()
        t1 = add_on_shift_transporter("T One", site["hub"]["id"],
                                      certified_equipment=["WHEELCHAIR"])
        add_equipment_asset("WC-001", "WHEELCHAIR", site["ward"]["id"])
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")
        offer1 = create_dispatch_offer(r1, transporter_id=t1["id"])
        decline_offer(offer1["id"], t1["id"])

        fresh = get_request(r1["id"])
        assert fresh["excluded_transporter_ids"] == [t1["id"]]
        resp = api.create_offer(r1["id"], create_offer_payload(
            fresh["version"], transporter_id=t1["id"]), DISP)
        validate_error(resp, ApiErrorId.ERR_TRANSPORTER_INELIGIBLE)


class TestDeclineAutoDispatchChain:
    def test_decline_frees_asset_and_auto_dispatches_next_offer(self, api):
        """PRD §3.5: "The offer's reserved asset, if any, returns to
        `AVAILABLE`, and auto-dispatch evaluation runs for the freed asset."
        PRD §3.4: "The evaluation considers `QUEUED` requests with no `PENDING`
        offer whose `required_equipment` matches the freed asset's type, ranks
        them by priority (`STAT` first, then `URGENT`, then `ROUTINE`) and then
        by `created_at` ascending, and takes the first candidate."

        Design: Difficulty/transitive_cascade/decline_release_autodispatch_chain
        """
        board = setup_two_transporter_board()
        site, t1, t2, asset = board["site"], board["t1"], board["t2"], board["asset"]
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")
        set_clock("2026-08-01T00:03:00Z")
        r2 = create_transport_request("P2", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")
        offer1 = create_dispatch_offer(r1, transporter_id=t1["id"])
        set_clock("2026-08-01T00:04:00Z")

        decline_offer(offer1["id"], t1["id"])

        offers_r1, _ = list_request_offers(r1["id"])
        assert len(offers_r1) == 2
        assert offers_r1[0]["status"] == "DECLINED"
        auto_offer = offers_r1[1]
        assert auto_offer["status"] == "PENDING"
        assert auto_offer["transporter_id"] == t2["id"], (
            "T One declined and is excluded; T Two is the eligible pool")
        assert auto_offer["offer_seq"] == 2
        assert auto_offer["estimated_travel_minutes"] == 19, (
            "deadhead 8 + ceil(10 x 1.1) = 11")

        offers_r2, _ = list_request_offers(r2["id"])
        assert offers_r2 == [], (
            "R1 wins the freed asset by created_at ascending; R2 gets nothing")
        assert get_asset(asset["id"])["status"] == "RESERVED", (
            "freed by the decline, then re-reserved by the cascade")

    def test_decline_with_empty_pool_leaves_asset_available(self, api):
        """PRD §3.4: "If the pool is empty, no offer is created and the asset
        simply stays `AVAILABLE`."

        Design: Difficulty/transitive_cascade/decline_release_autodispatch_chain
        """
        site = setup_transport_site()
        t1 = add_on_shift_transporter("T One", site["hub"]["id"],
                                      certified_equipment=["WHEELCHAIR"])
        asset = add_equipment_asset("WC-001", "WHEELCHAIR", site["ward"]["id"])
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")
        offer1 = create_dispatch_offer(r1, transporter_id=t1["id"])

        decline_offer(offer1["id"], t1["id"])

        offers, _ = list_request_offers(r1["id"])
        assert len(offers) == 1, "the only transporter is excluded, so the "
        "cascade creates no replacement offer"
        assert offers[0]["status"] == "DECLINED"
        assert get_asset(asset["id"])["status"] == "AVAILABLE"
        assert get_request(r1["id"])["status"] == "QUEUED"


class TestCancelAutoDispatchChain:
    def test_cancel_assigned_frees_asset_and_auto_dispatches(self, api):
        """PRD §3.5: "when cancelling from `ASSIGNED` or `AT_PICKUP`, the
        assigned asset — which was never in use — returns to `AVAILABLE` with
        no cleaning obligation, the transporter is freed,
        `assigned_transporter_id` is cleared, and auto-dispatch evaluation
        runs."
        PRD §3.4: "For that candidate it builds the eligible transporter pool —
        `ON_SHIFT`, no active assignment, no `PENDING` offer addressed, absent
        from `excluded_transporter_ids`, certifications matching the trip's
        isolation, oxygen, and equipment demands, and a travel edge from the
        transporter's current location to the request origin — ranks it by
        deadhead minutes then transporter `created_at`, and creates a
        `PENDING` offer while reserving the freed asset."

        Design: Difficulty/transitive_cascade/cancel_release_autodispatch_chain
        """
        board = setup_two_transporter_board()
        site, t1, t2, asset = board["site"], board["t1"], board["t2"], board["asset"]
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")
        offer1 = create_dispatch_offer(r1, transporter_id=t1["id"])
        accept_offer(offer1["id"], t1["id"])
        set_clock("2026-08-01T00:03:00Z")
        r2 = create_transport_request("P2", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")

        cancelled = close_request_ok(r1["id"], "CANCEL", DISP,
                                     reason="ORDER_WITHDRAWN")
        assert cancelled["status"] == "CANCELLED"

        offers_r2, _ = list_request_offers(r2["id"])
        assert len(offers_r2) == 1
        assert offers_r2[0]["status"] == "PENDING"
        assert offers_r2[0]["transporter_id"] == t1["id"], (
            "deadhead tie 8 == 8 is broken by transporter created_at "
            "ascending, and T One was registered first")
        assert get_asset(asset["id"])["status"] == "RESERVED", (
            "freed by the cancel, re-reserved by auto-dispatch")

    def test_cancel_at_pickup_leaves_no_cleaning_obligation(self, api):
        """PRD §3.5: "when cancelling from `ASSIGNED` or `AT_PICKUP`, the
        assigned asset — which was never in use — returns to `AVAILABLE` with
        no cleaning obligation, the transporter is freed,
        `assigned_transporter_id` is cleared, and auto-dispatch evaluation
        runs."

        Design: Difficulty/transitive_cascade/cancel_release_autodispatch_chain
        """
        world = setup_assigned_trip(equipment="WHEELCHAIR", patient_ref="P1")
        site, t1, asset = world["site"], world["transporter"], world["asset"]
        r1 = world["request"]
        trip_event_ok(r1["id"], "ARRIVE_PICKUP", transporter_id=t1["id"])
        r2 = create_transport_request("P2", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")

        cancelled = close_request_ok(r1["id"], "CANCEL", DISP,
                                     reason="PATIENT_STAYED")
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["assigned_transporter_id"] is None

        _tasks, meta = list_cleaning_tasks(
            params={"equipment_asset_id": asset["id"]})
        assert meta["total_count"] == 0, (
            "the asset was never IN_USE, so no cleaning task is created")

        offers_r2, _ = list_request_offers(r2["id"])
        assert len(offers_r2) == 1
        assert offers_r2[0]["status"] == "PENDING"
        assert offers_r2[0]["transporter_id"] == t1["id"]


class TestEquipmentPoolConservation:
    def test_available_pool_restored_after_offer_and_decline(self, api):
        """PRD §3.4: "Equipment selection is deterministic in both manual and
        automatic flows: among `AVAILABLE` assets of the required type, the
        pick is the earliest `created_at`, breaking ties by `asset_tag`
        ascending; the chosen asset flips to `RESERVED` and is recorded as the
        request's `assigned_equipment_id`."
        PRD §3.5: "The offer's reserved asset, if any, returns to `AVAILABLE`,
        and auto-dispatch evaluation runs for the freed asset."

        Design: Difficulty/compensating_invariant/equipment_pool_conservation
        """
        site = setup_transport_site()
        t1 = add_on_shift_transporter("T One", site["hub"]["id"],
                                      certified_equipment=["WHEELCHAIR"])
        a1 = add_equipment_asset("WC-001", "WHEELCHAIR", site["ward"]["id"])
        add_equipment_asset("WC-002", "WHEELCHAIR", site["ward"]["id"])
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")

        def available_pool():
            _data, meta = list_equipment_assets(
                params={"equipment_type": "WHEELCHAIR", "status": "AVAILABLE"})
            return meta["total_count"]

        assert available_pool() == 2
        offer = create_dispatch_offer(r1, transporter_id=t1["id"])
        assert available_pool() == 1
        assert get_asset(a1["id"])["status"] == "RESERVED", (
            "created_at tie between WC-001 and WC-002 is broken by asset_tag "
            "ascending")
        assert get_request(r1["id"])["assigned_equipment_id"] == a1["id"]

        decline_offer(offer["id"], t1["id"])
        assert available_pool() == 2, (
            "invariant: the AVAILABLE pool is unchanged by an "
            "offer-create + decline pair")
        assert get_asset(a1["id"])["status"] == "AVAILABLE"
        final = get_request(r1["id"])
        assert final["decline_count"] == 1
        assert final["status"] == "QUEUED"

    def test_earliest_created_at_dominates_asset_tag(self, api):
        """PRD §3.4: "among `AVAILABLE` assets of the required type, the pick
        is the earliest `created_at`, breaking ties by `asset_tag` ascending"

        Design: Difficulty/compensating_invariant/equipment_pool_conservation
        """
        site = setup_transport_site()
        t1 = add_on_shift_transporter("T One", site["hub"]["id"],
                                      certified_equipment=["WHEELCHAIR"])
        older = add_equipment_asset("WC-ZZZ", "WHEELCHAIR", site["ward"]["id"])
        set_clock("2026-08-01T00:01:00Z")
        newer = add_equipment_asset("WC-AAA", "WHEELCHAIR", site["ward"]["id"])
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")

        create_dispatch_offer(r1, transporter_id=t1["id"])
        updated = get_request(r1["id"])
        assert updated["assigned_equipment_id"] == older["id"], (
            "WC-ZZZ was created a minute earlier; created_at is the primary "
            "sort key, asset_tag only breaks ties")
        assert get_asset(older["id"])["status"] == "RESERVED"
        assert get_asset(newer["id"])["status"] == "AVAILABLE"


class TestTransporterLoadConservation:
    def test_accept_then_release_restores_zero_load(self, api):
        """PRD §3.5: "`RELEASE` returns an `ASSIGNED` request to `QUEUED` and
        may be invoked by the assigned transporter or forced by a dispatcher.
        The assignment is cleared, `release_count` increments, the transporter
        who had been holding the trip is appended to
        `excluded_transporter_ids`, the assigned asset returns to `AVAILABLE`
        with auto-dispatch evaluation, and the request's `version` increments."

        Design: Difficulty/compensating_invariant/transporter_load_conservation
        """
        world = setup_assigned_trip(equipment="WHEELCHAIR", patient_ref="P1")
        t1, r1 = world["transporter"], world["request"]

        def active_load():
            _data, meta = list_requests(params={
                "assigned_transporter_id": t1["id"], "status": "ASSIGNED"})
            return meta["total_count"]

        assert active_load() == 1
        trip_event_ok(r1["id"], "RELEASE", transporter_id=t1["id"])
        assert active_load() == 0, (
            "invariant: concurrent active load is unchanged by an "
            "accept + release pair")
        final = get_request(r1["id"])
        assert final["status"] == "QUEUED"
        assert final["assigned_transporter_id"] is None
        assert final["release_count"] == 1

    def test_active_assignment_blocks_second_offer(self, api):
        """PRD §3.4: "A manually named transporter must be `ON_SHIFT`, hold no
        active assignment, have no other `PENDING` offer addressed to them, and
        not appear in the request's `excluded_transporter_ids`; they must be
        `oxygen_certified` when `oxygen_required` is set; and when
        `required_equipment` is not `PORTER_ONLY`, that equipment type must
        appear in their `certified_equipment`."
        PRD §3.4: "Any such failure rejects the offer with
        `ERR_TRANSPORTER_INELIGIBLE`."

        Design: Difficulty/compensating_invariant/transporter_load_conservation
        """
        world = setup_assigned_trip(equipment="WHEELCHAIR", patient_ref="P1")
        site, t1 = world["site"], world["transporter"]
        r2 = create_transport_request("P2", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")

        resp = api.create_offer(r2["id"], create_offer_payload(
            r2["version"], transporter_id=t1["id"]), DISP)
        validate_error(resp, ApiErrorId.ERR_TRANSPORTER_INELIGIBLE)


class TestOfferTerminalStates:
    def test_offer_double_respond_returns_409(self, api):
        """PRD §3.5: "Only the transporter named by the offer may respond — an
        offer whose `transporter_id` does not equal the caller's `X-User-ID` is
        rejected with `ERR_FORBIDDEN_ROLE` — and only while the offer is
        `PENDING`, otherwise `ERR_INVALID_OFFER_STATE`."

        Design: Corner/state_machines/offer_double_respond_returns_409
        """
        world = setup_assigned_trip(equipment="PORTER_ONLY", patient_ref="P1")
        t1, offer = world["transporter"], world["offer"]

        second = respond_to_offer(offer["id"], "ACCEPT", t1["id"])
        validate_error(second, ApiErrorId.ERR_INVALID_OFFER_STATE)

    def test_respond_foreign_offer_forbidden_returns_403(self, api):
        """PRD §3.5: "Only the transporter named by the offer may respond — an
        offer whose `transporter_id` does not equal the caller's `X-User-ID` is
        rejected with `ERR_FORBIDDEN_ROLE`"

        Design: Corner/rbac/respond_foreign_offer_forbidden_returns_403
        """
        board = setup_two_transporter_board(equipment="PORTER_ONLY")
        site, t1, t2 = board["site"], board["t1"], board["t2"]
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="PORTER_ONLY")
        offer = create_dispatch_offer(r1, transporter_id=t1["id"])

        resp = respond_to_offer(offer["id"], "ACCEPT", t2["id"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestSupersedeCascade:
    def test_supersede_releases_offer_and_triggers_autodispatch(self, api):
        """PRD §3.5: "On success the request records the payload's
        `duplicate_of_id` as its own `duplicate_of_id`, stamps `closed_at`,
        supersedes any `PENDING` offer with its asset returned to `AVAILABLE`
        plus auto-dispatch evaluation, and increments `version`."
        PRD §3.4: "The evaluation considers `QUEUED` requests with no `PENDING`
        offer whose `required_equipment` matches the freed asset's type, ranks
        them by priority (`STAT` first, then `URGENT`, then `ROUTINE`) and then
        by `created_at` ascending, and takes the first candidate."

        Design: Corner/state_machines/supersede_releases_offer_and_triggers_autodispatch
        """
        board = setup_two_transporter_board()
        site, t1, asset = board["site"], board["t1"], board["asset"]
        w5 = create_location("W5", "Ward 5", "WARD", "Z1")
        create_travel_edge(site["ward"]["id"], w5["id"], 6, 9)

        r2 = create_transport_request("PX", site["ward"]["id"], w5["id"],
                                      priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")
        set_clock("2026-08-01T00:03:00Z")
        r1 = create_transport_request("PX", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")
        offer1 = create_dispatch_offer(r1, transporter_id=t1["id"])

        closed = close_request_ok(r1["id"], "SUPERSEDE", DISP,
                                  duplicate_of_id=r2["id"])
        assert closed["status"] == "SUPERSEDED"
        assert closed["duplicate_of_id"] == r2["id"]

        offers_r1, _ = list_request_offers(r1["id"])
        assert offers_r1[0]["id"] == offer1["id"]
        assert offers_r1[0]["status"] == "SUPERSEDED"

        offers_r2, _ = list_request_offers(r2["id"])
        assert len(offers_r2) == 1
        assert offers_r2[0]["status"] == "PENDING"
        assert offers_r2[0]["transporter_id"] == t1["id"]
        assert offers_r2[0]["estimated_travel_minutes"] == 15, (
            "deadhead 8 (HUB->W4) + ceil(6 x 1.1) = 7 (W4->W5)")
        assert get_asset(asset["id"])["status"] == "RESERVED", (
            "freed by the supersession, re-reserved by the auto-dispatch")
