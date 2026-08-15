"""Dispatch offers: travel estimates, eligibility, equipment selection, OCC."""
from test_helpers import (
    DISP,
    ApiErrorId,
    accept_offer,
    add_equipment_asset,
    add_on_shift_transporter,
    add_transporter,
    assert_dispatch_offer,
    assert_transport_request,
    create_dispatch_offer,
    create_location,
    create_offer_payload,
    create_transport_request,
    create_travel_edge,
    get_asset,
    get_request,
    list_request_offers,
    make_clinician_headers,
    make_transporter_headers,
    set_clock,
    setup_trip_in_transit,
    setup_transport_site,
    trip_event_ok,
    validate_error,
    validate_success,
)


def _setup_in_transit_porter_trip(site):
    """Second transporter driving a PORTER_ONLY trip IN_TRANSIT, so exactly
    one trip is in transit on the board."""
    t2 = add_on_shift_transporter("T Two", site["hub"]["id"])
    r0 = create_transport_request("P0", site["ward"]["id"], site["img"]["id"],
                                  priority="ROUTINE",
                                  required_equipment="PORTER_ONLY")
    o0 = create_dispatch_offer(r0, transporter_id=t2["id"])
    accept_offer(o0["id"], t2["id"])
    trip_event_ok(r0["id"], "ARRIVE_PICKUP", transporter_id=t2["id"])
    trip_event_ok(r0["id"], "PICKUP", transporter_id=t2["id"])
    return t2


def _setup_dispatch_vs_commit_board():
    """Site + T One (WHEELCHAIR) ON_SHIFT + WC-001 at W4 + one IN_TRANSIT
    PORTER_ONLY trip. Returns (site, t1, asset)."""
    site = setup_transport_site()
    t1 = add_on_shift_transporter("T One", site["hub"]["id"],
                                  certified_equipment=["WHEELCHAIR"])
    _setup_in_transit_porter_trip(site)
    asset = add_equipment_asset("WC-001", "WHEELCHAIR", site["ward"]["id"])
    return site, t1, asset


class TestTravelEstimateDualVariant:
    def test_dispatch_estimate_snapshot_on_offer(self, api):
        """PRD §3.4: "The deadhead leg is zero minutes when the transporter is
        already at the pickup location — no edge required — and otherwise the
        `base_minutes` of the edge from the transporter's current location to
        the origin. The loaded leg uses the edge from origin to destination:
        its `airborne_minutes` when the trip's isolation precaution is
        `AIRBORNE`, otherwise its `base_minutes`, and that figure is then
        multiplied by an equipment factor — 1.0 for `PORTER_ONLY`, 1.1 for
        `WHEELCHAIR`, 1.25 for `STRETCHER`, and 1.4 for `BARIATRIC_STRETCHER` —
        with the product rounded up to a whole minute."
        PRD §3.4: "The new offer is born `PENDING` with `offer_seq` set to the
        next per-request sequence number (the request's `offer_seq_count`
        increments in step), and its `estimated_travel_minutes` snapshots the
        dispatch-variant travel estimate."

        Design: Difficulty/dual_variant_calc/travel_estimate_dispatch_vs_commit
        """
        site, t1, _asset = _setup_dispatch_vs_commit_board()
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")

        offer = create_dispatch_offer(r1, transporter_id=t1["id"])
        assert_dispatch_offer(offer)
        assert offer["status"] == "PENDING"
        assert offer["offer_seq"] == 1
        assert offer["estimated_travel_minutes"] == 19, (
            "dispatch variant: deadhead 8 (HUB->W4) + ceil(10 x 1.1) = 11")

    def test_commit_eta_adds_congestion_surcharge(self, api):
        """PRD §3.5: "`committed_eta_minutes` is the commit-variant estimate,
        which takes the identical deadhead, loaded, and oxygen legs of the
        dispatch estimate and adds a congestion surcharge of 2 minutes for each
        trip currently `IN_TRANSIT`, counting at most 5 such trips."
        PRD §3.5: "the request advances from `QUEUED` to `ASSIGNED` with
        `assigned_transporter_id` set from the offer"

        Design: Difficulty/dual_variant_calc/travel_estimate_dispatch_vs_commit
        """
        site, t1, _asset = _setup_dispatch_vs_commit_board()
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")
        offer = create_dispatch_offer(r1, transporter_id=t1["id"])
        assert offer["estimated_travel_minutes"] == 19

        accept_offer(offer["id"], t1["id"])
        updated = get_request(r1["id"])
        assert_transport_request(updated)
        assert updated["status"] == "ASSIGNED"
        assert updated["assigned_transporter_id"] == t1["id"]
        assert updated["committed_eta_minutes"] == 21, (
            "commit variant: 19 + 2 x min(1, 5) with exactly one trip "
            "IN_TRANSIT at accept time")


class TestTravelEstimateMultiInput:
    def test_airborne_bariatric_oxygen_estimate(self, api):
        """PRD §3.4: "The loaded leg uses the edge from origin to destination:
        its `airborne_minutes` when the trip's isolation precaution is
        `AIRBORNE`, otherwise its `base_minutes`, and that figure is then
        multiplied by an equipment factor — 1.0 for `PORTER_ONLY`, 1.1 for
        `WHEELCHAIR`, 1.25 for `STRETCHER`, and 1.4 for `BARIATRIC_STRETCHER` —
        with the product rounded up to a whole minute. Two minutes of oxygen
        setup are added when `oxygen_required` is set."

        Design: Difficulty/combinatorial_formula/travel_estimate_multiinput_airborne
        """
        site = setup_transport_site()
        t1 = add_on_shift_transporter("T One", site["hub"]["id"],
                                      certified_equipment=["BARIATRIC_STRETCHER"],
                                      oxygen_certified=True,
                                      isolation_certified=True)
        asset = add_equipment_asset("BS-001", "BARIATRIC_STRETCHER",
                                    site["ward"]["id"])
        r1 = create_transport_request(
            "P1", site["ward"]["id"], site["img"]["id"], priority="URGENT",
            required_equipment="BARIATRIC_STRETCHER", oxygen_required=True,
            isolation_precaution="AIRBORNE")

        offer = create_dispatch_offer(r1, transporter_id=t1["id"])
        assert offer["estimated_travel_minutes"] == 33, (
            "deadhead 8 + ceil(16 x 1.4) = 23 (airborne leg) + oxygen 2")
        updated = get_request(r1["id"])
        assert updated["assigned_equipment_id"] == asset["id"], (
            "the chosen asset is recorded as assigned_equipment_id")
        assert get_asset(asset["id"])["status"] == "RESERVED"

    def test_non_airborne_stretcher_uses_base_minutes(self, api):
        """PRD §3.4: "The loaded leg uses the edge from origin to destination:
        its `airborne_minutes` when the trip's isolation precaution is
        `AIRBORNE`, otherwise its `base_minutes`, and that figure is then
        multiplied by an equipment factor — 1.0 for `PORTER_ONLY`, 1.1 for
        `WHEELCHAIR`, 1.25 for `STRETCHER`, and 1.4 for `BARIATRIC_STRETCHER` —
        with the product rounded up to a whole minute. Two minutes of oxygen
        setup are added when `oxygen_required` is set."
        PRD §3.4: "the chosen asset flips to `RESERVED` and is recorded as the
        request's `assigned_equipment_id`."

        Design: Difficulty/combinatorial_formula/travel_estimate_multiinput_airborne
        """
        site = setup_transport_site()
        t1 = add_on_shift_transporter("T One", site["hub"]["id"],
                                      certified_equipment=["STRETCHER"],
                                      oxygen_certified=True)
        asset = add_equipment_asset("ST-001", "STRETCHER", site["ward"]["id"])
        r1 = create_transport_request(
            "P1", site["ward"]["id"], site["img"]["id"], priority="URGENT",
            required_equipment="STRETCHER", oxygen_required=True)

        offer = create_dispatch_offer(r1, transporter_id=t1["id"])
        assert offer["estimated_travel_minutes"] == 23, (
            "deadhead 8 + ceil(10 x 1.25) = 13 (base leg, not airborne) + "
            "oxygen 2")
        updated = get_request(r1["id"])
        assert updated["assigned_equipment_id"] == asset["id"]
        assert get_asset(asset["id"])["status"] == "RESERVED"


class TestEquipmentAvailabilityGate:
    def test_offer_blocked_while_only_asset_in_use(self, api):
        """PRD §3.4: "Finally, when the trip needs equipment, at least one
        `AVAILABLE` asset of the matching type must exist, else
        `ERR_NO_AVAILABLE_EQUIPMENT`."

        Design: Difficulty/cross_entity_state_dependency/offer_requires_available_equipment
        """
        world = setup_trip_in_transit(equipment="WHEELCHAIR", patient_ref="P1")
        site = world["site"]
        # The only WHEELCHAIR is now IN_USE on the trip above; T Two is idle.
        t2 = add_on_shift_transporter("T Two", site["hub"]["id"],
                                      certified_equipment=["WHEELCHAIR"])
        r2 = create_transport_request("P2", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")

        resp = api.create_offer(r2["id"], create_offer_payload(
            r2["version"], transporter_id=t2["id"]), DISP)
        validate_error(resp, ApiErrorId.ERR_NO_AVAILABLE_EQUIPMENT)

    def test_offer_blocked_when_only_other_equipment_type_available(self, api):
        """PRD §3.4: "Finally, when the trip needs equipment, at least one
        `AVAILABLE` asset of the matching type must exist, else
        `ERR_NO_AVAILABLE_EQUIPMENT`."

        Design: Difficulty/cross_entity_state_dependency/offer_requires_available_equipment
        """
        site = setup_transport_site()
        t1 = add_on_shift_transporter("T One", site["hub"]["id"],
                                      certified_equipment=["WHEELCHAIR"])
        add_equipment_asset("ST-001", "STRETCHER", site["ward"]["id"])
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")

        resp = api.create_offer(r1["id"], create_offer_payload(
            r1["version"], transporter_id=t1["id"]), DISP)
        validate_error(resp, ApiErrorId.ERR_NO_AVAILABLE_EQUIPMENT)


class TestEligibilityAndEdges:
    def test_missing_edge_returns_422(self, api):
        """PRD §3.4: "Travel edges must exist from the transporter's
        `current_location_id` to the origin and from the origin to the
        destination, else `ERR_NO_TRAVEL_EDGE`."

        Design: Corner/validations/missing_edge_returns_422
        """
        set_clock("2026-08-01T00:00:00Z")
        hub = create_location("HUB", "Hub", "OTHER", "Z1")
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        w5 = create_location("W5", "Ward 5", "WARD", "Z1")
        create_travel_edge(hub["id"], ward["id"], 8, 12)
        t1 = add_on_shift_transporter("T One", hub["id"])
        r1 = create_transport_request("P1", ward["id"], w5["id"],
                                      priority="ROUTINE",
                                      required_equipment="PORTER_ONLY")

        resp = api.create_offer(r1["id"], create_offer_payload(
            r1["version"], transporter_id=t1["id"]), DISP)
        validate_error(resp, ApiErrorId.ERR_NO_TRAVEL_EDGE)

    def test_eligibility_error_trio_returns_422(self, api):
        """PRD §3.4: "The isolation safety gate comes first: a trip whose
        `isolation_precaution` is anything other than `NONE` requires an
        `isolation_certified` transporter, else
        `ERR_ISOLATION_CAPABILITY_MISMATCH`."
        PRD §3.4: "A manually named transporter must be `ON_SHIFT`, hold no
        active assignment, have no other `PENDING` offer addressed to them, and
        not appear in the request's `excluded_transporter_ids`; they must be
        `oxygen_certified` when `oxygen_required` is set; and when
        `required_equipment` is not `PORTER_ONLY`, that equipment type must
        appear in their `certified_equipment`. Any such failure rejects the
        offer with `ERR_TRANSPORTER_INELIGIBLE`."
        PRD §3.4: "an empty pool rejects the offer with
        `ERR_NO_ELIGIBLE_TRANSPORTER`."

        Design: Corner/errors/eligibility_error_trio_returns_422
        """
        site = setup_transport_site()
        # Both transporters stay OFF_SHIFT and hold no certifications.
        t1 = add_transporter_off_shift(site, "T One")
        add_transporter_off_shift(site, "T Two")
        add_equipment_asset("WC-001", "WHEELCHAIR", site["ward"]["id"])
        r_iso = create_transport_request(
            "P-ISO", site["ward"]["id"], site["img"]["id"], priority="ROUTINE",
            required_equipment="PORTER_ONLY", isolation_precaution="CONTACT")
        r_eq = create_transport_request(
            "P-EQ", site["ward"]["id"], site["img"]["id"], priority="ROUTINE",
            required_equipment="WHEELCHAIR")
        r_auto = create_transport_request(
            "P-AUTO", site["ward"]["id"], site["img"]["id"], priority="ROUTINE",
            required_equipment="PORTER_ONLY")

        # Isolation safety gate (tier 7) fires even though T One is also
        # OFF_SHIFT (a tier-10 constraint failure).
        resp = api.create_offer(r_iso["id"], create_offer_payload(
            r_iso["version"], transporter_id=t1["id"]), DISP)
        validate_error(resp, ApiErrorId.ERR_ISOLATION_CAPABILITY_MISMATCH)

        # Missing the equipment certification.
        resp = api.create_offer(r_eq["id"], create_offer_payload(
            r_eq["version"], transporter_id=t1["id"]), DISP)
        validate_error(resp, ApiErrorId.ERR_TRANSPORTER_INELIGIBLE)

        # Auto-select with every transporter OFF_SHIFT: empty pool.
        resp = api.create_offer(r_auto["id"], create_offer_payload(
            r_auto["version"]), DISP)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_TRANSPORTER)

    def test_offer_on_cancelled_request_state_beats_safety(self, api):
        """PRD §3.4: "only when the version matches does the state check run,
        rejecting offers on non-`QUEUED` requests with
        `ERR_INVALID_REQUEST_STATE`."
        PRD §2.6: "Because the tiers are ordered, a request that would fail
        several checks always reports the earliest failure: a stale offer
        attempt surfaces `ERR_STALE_VERSION` rather than a state error, and an
        unknown path id surfaces `ERR_NOT_FOUND` before any business rule is
        consulted."

        Design: Corner/validations/offer_on_cancelled_request_state_beats_safety
        """
        site = setup_transport_site()
        t2 = add_on_shift_transporter("T Two", site["hub"]["id"],
                                      certified_equipment=["WHEELCHAIR"])
        r1 = create_transport_request(
            "P1", site["ward"]["id"], site["img"]["id"], priority="ROUTINE",
            required_equipment="PORTER_ONLY", isolation_precaution="CONTACT")
        # Cancelled while QUEUED by its own clinician; T Two lacks the
        # isolation certification, so the safety tier would also fail.
        resp = api.close_request(r1["id"], {"action": "CANCEL",
                                            "reason": "ORDER_WITHDRAWN"},
                                 make_clinician_headers("clin-1"))
        validate_success(resp, 200)
        fresh = get_request(r1["id"])

        resp = api.create_offer(r1["id"], create_offer_payload(
            fresh["version"], transporter_id=t2["id"]), DISP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST_STATE)


def add_transporter_off_shift(site, name):
    """Register a transporter who never clocks in (stays OFF_SHIFT)."""
    return add_transporter(name, site["hub"]["id"])


class TestOfferRbac:
    def test_transporter_cannot_create_offer_returns_403(self, api):
        """PRD §2.1: "A request whose role is not permitted on the endpoint,
        that violates a role-payload restriction, or that fails an ownership
        check is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: the create-offer endpoint is authorized for
        TransportDispatcher only.

        Design: Corner/rbac/transporter_cannot_create_offer_returns_403
        """
        site = setup_transport_site()
        t1 = add_transporter_off_shift(site, "T One")
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="PORTER_ONLY")

        resp = api.create_offer(r1["id"], create_offer_payload(
            r1["version"], transporter_id=t1["id"]),
            make_transporter_headers(t1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestOptimisticConcurrency:
    def test_occ_stale_version_returns_412(self, api):
        """PRD §2.7: "If that value does not equal the request's current
        `version` — because another writer has advanced it since the client
        last read it — the creation is rejected with `ERR_STALE_VERSION`
        (HTTP 412), so a dispatcher never unknowingly builds on a superseded
        view of the queue."

        Design: Corner/cross_cutting_layers/occ_stale_version_returns_412
        """
        site = setup_transport_site()
        t1 = add_on_shift_transporter("T One", site["hub"]["id"],
                                      certified_equipment=["WHEELCHAIR"])
        add_equipment_asset("WC-001", "WHEELCHAIR", site["ward"]["id"])
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")
        observed_version = r1["version"]

        first = api.create_offer(r1["id"], create_offer_payload(
            observed_version, transporter_id=t1["id"]), DISP)
        offer = validate_success(first, 201)
        assert_dispatch_offer(offer)

        stale = api.create_offer(r1["id"], create_offer_payload(
            observed_version, transporter_id=t1["id"]), DISP)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_fresh_version_supersedes_pending_offer(self, api):
        """PRD §3.4: "Creating an offer supersedes any existing `PENDING`
        offer on the same request — the older offer moves to `SUPERSEDED` and
        its reserved asset returns to `AVAILABLE`, and notably no auto-dispatch
        evaluation runs on this supersession path. The new offer is born
        `PENDING` with `offer_seq` set to the next per-request sequence number
        (the request's `offer_seq_count` increments in step), and its
        `estimated_travel_minutes` snapshots the dispatch-variant travel
        estimate."
        PRD §2.4: "`version` is a system-managed integer that increments by
        exactly one on every mutation of the resource."

        Design: Corner/cross_cutting_layers/occ_fresh_version_supersedes_pending_offer
        """
        site = setup_transport_site()
        t1 = add_on_shift_transporter("T One", site["hub"]["id"],
                                      certified_equipment=["WHEELCHAIR"])
        t2 = add_on_shift_transporter("T Two", site["hub"]["id"],
                                      certified_equipment=["WHEELCHAIR"])
        add_equipment_asset("WC-001", "WHEELCHAIR", site["ward"]["id"])
        add_equipment_asset("WC-002", "WHEELCHAIR", site["ward"]["id"])
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")
        offer1 = create_dispatch_offer(r1, transporter_id=t1["id"])
        set_clock("2026-08-01T00:01:00Z")
        fresh = get_request(r1["id"])

        # Re-offer naming a different, fully eligible transporter while a
        # second asset is AVAILABLE: the re-offer succeeds regardless of
        # whether the supersession or the eligibility gate is evaluated
        # first, because T Two holds no PENDING offer and WC-002 is free.
        created = api.create_offer(r1["id"], create_offer_payload(
            fresh["version"], transporter_id=t2["id"]), DISP)
        offer2 = validate_success(created, 201)
        assert offer2["offer_seq"] == 2, (
            "offer_seq is the next per-request sequence number")
        assert offer2["transporter_id"] == t2["id"]
        assert offer2["status"] == "PENDING", "the new offer is born PENDING"

        offers, _meta = list_request_offers(r1["id"])
        assert len(offers) == 2
        assert offers[0]["id"] == offer1["id"]
        assert offers[0]["status"] == "SUPERSEDED", (
            "the older offer moves to SUPERSEDED")
        assert offers[1]["id"] == offer2["id"]
        assert offers[1]["status"] == "PENDING"

        updated = get_request(r1["id"])
        assert updated["version"] == 3, (
            "create (1), offer1 (2), offer2 (3): one increment per mutation")
        assert updated["offer_seq_count"] == 2, (
            "offer_seq_count increments in step with offer_seq")


class TestImmediateConsistency:
    def test_immediate_consistency_read_after_accept(self, api):
        """PRD §3.5: "The offer becomes `ACCEPTED` with `responded_at`
        stamped, the request advances from `QUEUED` to `ASSIGNED` with
        `assigned_transporter_id` set from the offer, and the server commits an
        ETA: `committed_eta_minutes` is the commit-variant estimate, which
        takes the identical deadhead, loaded, and oxygen legs of the dispatch
        estimate and adds a congestion surcharge of 2 minutes for each trip
        currently `IN_TRANSIT`, counting at most 5 such trips. The two
        estimates therefore agree exactly when no other trip is in transit and
        diverge as the corridors fill."
        PRD §2.4: "`version` is a system-managed integer that increments by
        exactly one on every mutation of the resource."

        Design: Corner/consistency_model/immediate_consistency_read_after_accept
        """
        site = setup_transport_site()
        t1 = add_on_shift_transporter("T One", site["hub"]["id"],
                                      certified_equipment=["WHEELCHAIR"])
        add_equipment_asset("WC-001", "WHEELCHAIR", site["ward"]["id"])
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="WHEELCHAIR")
        offer = create_dispatch_offer(r1, transporter_id=t1["id"])
        assert offer["estimated_travel_minutes"] == 19

        accept_offer(offer["id"], t1["id"])
        updated = get_request(r1["id"])
        assert updated["status"] == "ASSIGNED"
        assert updated["assigned_transporter_id"] == t1["id"]
        assert updated["committed_eta_minutes"] == 19, (
            "no trip IN_TRANSIT, so the commit variant agrees with dispatch")
        assert updated["version"] == 3, (
            "create (1), offer (2), accept (3): one increment per mutation")
