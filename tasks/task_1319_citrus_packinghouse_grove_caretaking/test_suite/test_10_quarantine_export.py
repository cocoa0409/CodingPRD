"""Pest quarantine cascade and export program: posture recompute, assignment
cancellation and capacity release, delivery holds and un-holds, release
gates, the export-lot rework loop, certificate gating and expiry, cold
treatment, fruit-fly protocol, channel coherence, and diversion credits."""
from test_helpers import (
    ApiErrorId,
    assert_export_lot,
    assert_quarantine_order,
    assert_version_incremented,
    create_assignment_payload,
    create_delivery_payload,
    create_export_lot,
    create_quarantine,
    certify_lot,
    eu_export_spec,
    get_assignment,
    get_delivery,
    get_export_lot,
    get_certificate,
    get_grove,
    get_pool,
    get_success_data,
    juice_spec,
    jp_export_spec,
    record_maturity_test,
    release_quarantine,
    set_clock,
    setup_assignment_in_progress,
    setup_certified_lot,
    setup_grove_with_maturity,
    setup_posted_scenario,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    create_crew,
    create_grove,
    create_grower,
    create_pool,
)
from test_helpers.test_users import TEST_USERS, make_officer_headers

ADMIN = TEST_USERS["admin_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


def _setup_quarantine_cascade(tag):
    """Grower with two POLK HAMLIN groves; on G1: a SCHEDULED assignment A1
    (2026-08-01 window), an IN_PROGRESS assignment A2 (2026-08-02 window) and
    a CLEAR delivery D made under A2. Clock parked at 2026-08-02T07:00:00Z."""
    set_clock("2026-08-01T00:00:00Z")
    grower = create_grower(f"GR-{tag}", "Quarantine Cascade Groves")
    grove1 = create_grove(grower["id"], "B1", "HAMLIN", 50, "POLK")
    record_maturity_test(grove1["id"], inspector_id=f"qi-{tag}")
    grove2 = create_grove(grower["id"], "B2", "HAMLIN", 60, "POLK")
    record_maturity_test(grove2["id"], inspector_id=f"qi-{tag}")
    pool = create_pool("HAMLIN", "2026-07-27")
    crew = create_crew(f"CR-{tag}", 400)
    assignment_a1 = get_success_data(api_client.create_assignment(
        create_assignment_payload(crew["id"], grove1["id"],
                                  "2026-08-01T06:00:00Z",
                                  "2026-08-01T18:00:00Z", 100), SUPERVISOR))
    set_clock("2026-08-02T07:00:00Z")
    assignment_a2 = get_success_data(api_client.create_assignment(
        create_assignment_payload(crew["id"], grove1["id"],
                                  "2026-08-02T06:00:00Z",
                                  "2026-08-02T18:00:00Z", 50), SUPERVISOR))
    get_success_data(api_client.start_assignment(assignment_a2["id"], SUPERVISOR))
    delivery = get_success_data(api_client.create_delivery(
        create_delivery_payload(grove1["id"], assignment_a2["id"], 50, 0),
        SUPERVISOR))
    return {
        "grower": grower, "grove1": grove1, "grove2": grove2, "pool": pool,
        "crew": crew, "a1": assignment_a1, "a2": assignment_a2,
        "delivery": delivery,
    }


class TestQuarantineActivationCascade:
    def test_cascade_quarantines_grove_cancels_assignments_holds_delivery(self, api):
        """PRD §3.8: "Activation fires the quarantine cascade, atomically
        within the create request. Every covered grove — the named grove for
        `GROVE` scope, or every grove whose `county_code` matches for
        `COUNTY_ZONE` scope — has its `quarantine_posture` recomputed to
        `QUARANTINED`. Each covered grove's `SCHEDULED` harvest assignments
        are cancelled, releasing the crews' committed window capacity. Each
        covered grove's deliveries still `CLEAR` are held, moving to `HELD`."

        Design: Difficulty/transitive_cascade/quarantine_activation_cascade
        """
        sc = _setup_quarantine_cascade("QC1")
        order = create_quarantine("GROVE", "CANKER", grove_id=sc["grove1"]["id"],
                                  officer_id="co-qc-a")
        assert_quarantine_order(order)
        assert order["status"] == "ACTIVE"
        # Link A->B: the grove's posture is recomputed.
        assert get_grove(sc["grove1"]["id"])["quarantine_posture"] == "QUARANTINED"
        # Link B->C: the SCHEDULED assignment is cancelled with no client call.
        assert get_assignment(sc["a1"]["id"])["status"] == "CANCELLED"
        # Fan-out: the grove's CLEAR delivery is held.
        assert get_delivery(sc["delivery"]["id"])["regulatory_status"] == "HELD"
        # The IN_PROGRESS assignment is not cancelled, and an unaffected grove
        # in the same county is untouched (GROVE scope covers only G1).
        assert get_assignment(sc["a2"]["id"])["status"] == "IN_PROGRESS"
        assert get_grove(sc["grove2"]["id"])["quarantine_posture"] == "CLEAR"

    def test_cascade_releases_crew_committed_capacity(self, api):
        """PRD §3.8: "Each covered grove's `SCHEDULED` harvest assignments are
        cancelled, releasing the crews' committed window capacity" and PRD
        §3.2: cancellation "releases the crew's committed window capacity and
        the derived crew load is recomputed" — proven by successfully
        re-booking the cancelled assignment's exact window on the same crew
        (an overlap with a live assignment would fail per the half-open
        conflict rule).

        Design: Difficulty/transitive_cascade/quarantine_activation_cascade
        """
        sc = _setup_quarantine_cascade("QC1B")
        create_quarantine("GROVE", "CANKER", grove_id=sc["grove1"]["id"],
                          officer_id="co-qc-a")
        # Re-book the cancelled A1's window on the same crew, on the
        # unaffected grove G2.
        rebooked = validate_success(api_client.create_assignment(
            create_assignment_payload(sc["crew"]["id"], sc["grove2"]["id"],
                                      "2026-08-01T06:00:00Z",
                                      "2026-08-01T18:00:00Z", 100),
            SUPERVISOR), expected_status=201)
        assert rebooked["status"] == "SCHEDULED"


class TestQuarantineReleaseGates:
    def test_quarantine_release_gates(self, api):
        """PRD §3.8: "a `ComplianceOfficer` releases an order (`ACTIVE` →
        `RELEASED`, terminal) only when the request's `inspection_passed` is
        true — anything else fails with
        `ERR_QUARANTINE_RELEASE_REQUIREMENTS` — and only when the releasing
        officer's `X-User-ID` differs from the order's `issued_by`
        (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/state_machines/quarantine_release_gates
        """
        scenario = setup_grove_with_maturity("SM10", with_maturity=False)
        order = create_quarantine("GROVE", "CANKER",
                                  grove_id=scenario["grove"]["id"],
                                  officer_id="co-qr-a")
        resp = release_quarantine(order["id"], inspection_passed=False,
                                  officer_id="co-qr-b")
        validate_error(resp, ApiErrorId.ERR_QUARANTINE_RELEASE_REQUIREMENTS)
        resp = release_quarantine(order["id"], inspection_passed=True,
                                  officer_id="co-qr-a")
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        released = validate_success(release_quarantine(
            order["id"], inspection_passed=True, officer_id="co-qr-b"))
        assert released["status"] == "RELEASED"
        assert get_grove(scenario["grove"]["id"])["quarantine_posture"] == "CLEAR"


class TestQuarantineReleaseUnholds:
    def test_quarantine_release_unholds_deliveries(self, api):
        """PRD §3.8: "The release stamps `released_at` and `released_by`, then
        recomputes the posture of every affected grove: a grove returns to
        `CLEAR` only when no other `ACTIVE` order still covers it, whether by
        grove scope or county scope. As each grove clears, every one of its
        deliveries sitting in `HELD` moves to `RELEASED`, provided no other
        hold cause remains".

        Design: Corner/errors/quarantine_release_unholds_deliveries
        """
        scenario = setup_delivery_received_minimal("ER10")
        delivery_id = scenario["delivery"]["id"]
        grove_id = scenario["grove"]["id"]
        q1 = create_quarantine("GROVE", "CANKER", grove_id=grove_id,
                               officer_id="co-uh-a")
        q2 = create_quarantine("GROVE", "BLACK_SPOT", grove_id=grove_id,
                               officer_id="co-uh-b")
        assert get_delivery(delivery_id)["regulatory_status"] == "HELD"
        # Releasing only the first order leaves the grove covered by Q2.
        validate_success(release_quarantine(q1["id"], True, "co-uh-c"))
        assert get_grove(grove_id)["quarantine_posture"] == "QUARANTINED"
        assert get_delivery(delivery_id)["regulatory_status"] == "HELD"
        # Releasing the second (by a different officer than its issuer) clears
        # the grove and returns the delivery to RELEASED.
        validate_success(release_quarantine(q2["id"], True, "co-uh-a"))
        assert get_grove(grove_id)["quarantine_posture"] == "CLEAR"
        assert get_delivery(delivery_id)["regulatory_status"] == "RELEASED"


def setup_delivery_received_minimal(tag):
    """Receiving chain with pool, no channels, one 10-box CLEAR delivery."""
    scenario = setup_assignment_in_progress(tag, planned_boxes=50)
    scenario["pool"] = create_pool("HAMLIN", "2026-07-27")
    scenario["delivery"] = get_success_data(api_client.create_delivery(
        create_delivery_payload(scenario["grove"]["id"],
                                scenario["assignment"]["id"], 10, 0),
        SUPERVISOR))
    return scenario


class TestExportLotReworkLoop:
    def test_fail_inspection_creates_revoked_record_and_rejects_lot(self, api):
        """PRD §3.9: "On `FAIL`, the certificate record is created directly in
        `REVOKED` status as the failed-inspection record, and the lot moves to
        `REJECTED`."

        Design: Difficulty/non_linear_state_machine/export_lot_rework_loop
        """
        scenario = setup_posted_scenario("XL1")
        lot = create_export_lot("JAPAN", "HAMLIN", "FANCY", 10,
                                scenario["channels"]["JP-XL1"]["id"],
                                scenario["grove"]["id"], 24,
                                officer_id="co-xl-a")
        lot = get_success_data(api_client.request_inspection(
            lot["id"], make_officer_headers("co-xl-a")))
        cert = certify_lot(lot["id"], "PC-XL1-A", "FAIL", "co-xl-b")
        assert cert["status"] == "REVOKED", \
            "a FAIL inspection creates the record directly in REVOKED"
        assert get_export_lot(lot["id"])["status"] == "REJECTED"

    def test_rework_loop_returns_to_certified(self, api):
        """PRD §3.9: "A rejected lot can be reworked — `REJECTED` → `BUILDING`
        — which clears `inspection_requested_by` and applies an optional
        `cold_treatment_hours` update, so the rework-and-reinspect loop may
        repeat." and "On `PASS`, the source grove's posture is re-checked and
        must still be `CLEAR` (`ERR_GROVE_QUARANTINED`); the certificate is
        born `ISSUED`, stamped with `issued_at` from the logical clock and an
        `expires_at` exactly fourteen days later; and the lot moves
        `INSPECTION_READY` → `CERTIFIED` with its `phyto_certificate_id` set
        to the new certificate."

        Design: Difficulty/non_linear_state_machine/export_lot_rework_loop
        """
        scenario = setup_posted_scenario("XL1B")
        lot = create_export_lot("JAPAN", "HAMLIN", "FANCY", 10,
                                scenario["channels"]["JP-XL1B"]["id"],
                                scenario["grove"]["id"], 24,
                                officer_id="co-xl-a")
        lot = get_success_data(api_client.request_inspection(
            lot["id"], make_officer_headers("co-xl-a")))
        certify_lot(lot["id"], "PC-XL1B-A", "FAIL", "co-xl-b")
        # Rework returns the lot to BUILDING with the requester cleared.
        reworked = validate_success(api_client.rework_export_lot(
            lot["id"], {}, make_officer_headers("co-xl-b")))
        assert reworked["status"] == "BUILDING"
        assert reworked.get("inspection_requested_by") is None
        # Second inspection round, requested by the other officer.
        lot2 = get_success_data(api_client.request_inspection(
            lot["id"], make_officer_headers("co-xl-b")))
        assert lot2["inspection_requested_by"] == "co-xl-b"
        cert2 = certify_lot(lot["id"], "PC-XL1B-B", "PASS", "co-xl-a")
        assert cert2["status"] == "ISSUED"
        assert cert2["issued_by"] == "co-xl-a" != lot2["inspection_requested_by"]
        assert cert2["issued_at"].startswith("2026-08-01T00:00:00")
        assert cert2["expires_at"].startswith("2026-08-15T00:00:00"), \
            "expires exactly fourteen days after issuance"
        final_lot = get_export_lot(lot["id"])
        assert final_lot["status"] == "CERTIFIED"
        assert final_lot["phyto_certificate_id"] == cert2["id"]


class TestShipGatedByCertificate:
    def test_revoke_drags_lot_back_to_inspection_ready(self, api):
        """PRD §3.9: "A certificate may also be revoked directly by a
        `ComplianceOfficer`, moving `ISSUED` → `REVOKED`, provided its lot is
        not `SHIPPED` (`ERR_INVALID_STATE_TRANSITION`); if the lot was
        `CERTIFIED`, it returns to `INSPECTION_READY` with its
        `phyto_certificate_id` cleared and must be re-inspected before it can
        ship."

        Design: Difficulty/cross_entity_state_dependency/export_ship_gated_by_certificate
        """
        scenario = setup_certified_lot("CE2", boxes=10)
        revoked = validate_success(api_client.revoke_phyto_certificate(
            scenario["certificate"]["id"],
            make_officer_headers(scenario["cert_issuer_id"])))
        assert revoked["status"] == "REVOKED"
        lot = get_export_lot(scenario["lot"]["id"])
        assert lot["status"] == "INSPECTION_READY"
        assert lot.get("phyto_certificate_id") is None

    def test_ship_rejected_after_certificate_revoked(self, api):
        """PRD §3.9: "a `CERTIFIED` lot ships only while its
        `phyto_certificate_id` references a certificate still in `ISSUED`
        status (`ERR_INVALID_STATE_TRANSITION` otherwise)".

        Design: Difficulty/cross_entity_state_dependency/export_ship_gated_by_certificate
        """
        scenario = setup_certified_lot("CE2B", boxes=10)
        validate_success(api_client.revoke_phyto_certificate(
            scenario["certificate"]["id"],
            make_officer_headers(scenario["cert_issuer_id"])))
        resp = api_client.ship_export_lot(
            scenario["lot"]["id"],
            make_officer_headers(scenario["lot_officer_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_export_lot(scenario["lot"]["id"])["status"] == "INSPECTION_READY"


class TestColdTreatmentBoundary:
    def test_export_lot_cold_treatment_boundary(self, api):
        """PRD §3.9: "for a `JAPAN`-bound lot, `cold_treatment_hours` must be
        at least 24 — a full day of cold treatment — failing which the request
        is rejected with `ERR_COLD_TREATMENT_INSUFFICIENT`".

        Design: Corner/state_machines/export_lot_cold_treatment_boundary
        """
        scenario = setup_posted_scenario(
            "SM11", channel_specs=[
                jp_export_spec("JP-SM11", "HAMLIN", boxes=20),
                eu_export_spec("EU-SM11", "HAMLIN", boxes=10),
                juice_spec("JU-SM11", "HAMLIN"),
            ])
        channels = scenario["channels"]
        grove_id = scenario["grove"]["id"]
        lot_23 = create_export_lot("JAPAN", "HAMLIN", "FANCY", 5,
                                   channels["JP-SM11"]["id"], grove_id, 23,
                                   officer_id="co-sm11")
        lot_24 = create_export_lot("JAPAN", "HAMLIN", "FANCY", 5,
                                   channels["JP-SM11"]["id"], grove_id, 24,
                                   officer_id="co-sm11")
        lot_eu = create_export_lot("EU", "HAMLIN", "FANCY", 5,
                                   channels["EU-SM11"]["id"], grove_id, 0,
                                   officer_id="co-sm11")
        resp = api_client.request_inspection(
            lot_23["id"], make_officer_headers("co-sm11"))
        validate_error(resp, ApiErrorId.ERR_COLD_TREATMENT_INSUFFICIENT)
        assert get_export_lot(lot_23["id"])["status"] == "BUILDING"
        # 24 hours is the inclusive boundary for JAPAN.
        ready = validate_success(api_client.request_inspection(
            lot_24["id"], make_officer_headers("co-sm11")))
        assert ready["status"] == "INSPECTION_READY"
        # EU lots carry no cold-treatment gate.
        ready_eu = validate_success(api_client.request_inspection(
            lot_eu["id"], make_officer_headers("co-sm11")))
        assert ready_eu["status"] == "INSPECTION_READY"


class TestCertificateExpiryAtShip:
    def test_cert_expiry_strict_at_ship(self, api):
        """PRD §3.9: "Shipping is the terminal success: a `CERTIFIED` lot
        ships only while its `phyto_certificate_id` references a certificate
        still in `ISSUED` status (`ERR_INVALID_STATE_TRANSITION` otherwise)
        and the logical clock reads strictly before the certificate's
        `expires_at` — a ship attempted at or after the expiry instant fails
        with `ERR_CERT_EXPIRED`. Shipping moves the lot `CERTIFIED` →
        `SHIPPED` and consumes the certificate, moving it `ISSUED` →
        `CONSUMED`."

        Design: Corner/state_machines/cert_expiry_strict_at_ship
        """
        scenario = setup_certified_lot("SM12", boxes=5)
        lot_id = scenario["lot"]["id"]
        cert_id = scenario["certificate"]["id"]
        # At the expiry instant exactly (issued 2026-08-01T00:00 + 14 days):
        # rejected — the bound is strict.
        set_clock("2026-08-15T00:00:00Z")
        resp = api_client.ship_export_lot(
            lot_id, make_officer_headers(scenario["lot_officer_id"]))
        validate_error(resp, ApiErrorId.ERR_CERT_EXPIRED)
        # One second before expiry the ship succeeds.
        set_clock("2026-08-14T23:59:59Z")
        shipped = validate_success(api_client.ship_export_lot(
            lot_id, make_officer_headers(scenario["lot_officer_id"])))
        assert shipped["status"] == "SHIPPED"
        assert get_certificate(cert_id)["status"] == "CONSUMED"


class TestExportLotComputedFields:
    def test_export_lot_pool_id_and_availability_computed(self, api):
        """PRD §3.9: "the lot's `pool_id` is resolved from the source
        channel's variety and `week_start`. Building the lot reserves boxes
        from the channel's posted allocation: `boxes` may not exceed the
        channel's posted-allocation boxes not already reserved by other lots
        (`ERR_CHANNEL_CAPACITY_EXCEEDED`)." and "an optional
        `cold_treatment_hours` of zero or more, defaulting to 0".

        Design: Corner/entities/export_lot_pool_id_and_availability_computed
        """
        scenario = setup_posted_scenario(
            "E11", gross_boxes=40, fancy_boxes=40, choice_boxes=0,
            standard_boxes=0, juice_boxes=0, cull_boxes=0,
            color_score=8, defect_pct=5,
            channel_specs=[
                jp_export_spec("JP-E11", "HAMLIN", boxes=25),
                juice_spec("JU-E11", "HAMLIN"),
            ])
        channel = scenario["channels"]["JP-E11"]
        lot = create_export_lot("JAPAN", "HAMLIN", "FANCY", 20, channel["id"],
                                scenario["grove"]["id"], 30,
                                officer_id="co-e11")
        assert_export_lot(lot)
        assert lot["status"] == "BUILDING"
        assert lot["pool_id"] == scenario["pool"]["id"]
        assert lot["cold_treatment_hours"] == 30
        # Only 25 - 20 = 5 posted-allocation boxes remain: 6 is too many.
        resp = api_client.create_export_lot(
            {"destination_market": "JAPAN", "variety": "HAMLIN", "grade": "FANCY",
             "boxes": 6, "source_channel_id": channel["id"],
             "source_grove_id": scenario["grove"]["id"]},
            make_officer_headers("co-e11"))
        validate_error(resp, ApiErrorId.ERR_CHANNEL_CAPACITY_EXCEEDED)
        # Exactly the remaining 5 fit; the omitted cold treatment defaults to 0.
        lot2 = create_export_lot("JAPAN", "HAMLIN", "FANCY", 5, channel["id"],
                                 scenario["grove"]["id"], None,
                                 officer_id="co-e11")
        assert lot2["cold_treatment_hours"] == 0


class TestExportLotChannelMismatch:
    def test_export_lot_channel_mismatch(self, api):
        """PRD §3.9: "The source channel must be an `EXPORT` channel of
        matching variety and destination market whose week matches the fruit's
        pool week, or the create fails with `ERR_CHANNEL_MISMATCH`".

        Design: Corner/validations/export_lot_channel_mismatch
        """
        scenario = setup_posted_scenario(
            "V8", gross_boxes=40, fancy_boxes=40, choice_boxes=0,
            standard_boxes=0, juice_boxes=0, cull_boxes=0,
            color_score=8, defect_pct=5,
            channel_specs=[
                jp_export_spec("JP-V8", "HAMLIN", boxes=25),
                juice_spec("JU-V8", "HAMLIN"),
            ])
        channel = scenario["channels"]["JP-V8"]
        grove_id = scenario["grove"]["id"]
        resp = api_client.create_export_lot(
            {"destination_market": "JAPAN", "variety": "VALENCIA", "grade": "FANCY",
             "boxes": 5, "source_channel_id": channel["id"],
             "source_grove_id": grove_id, "cold_treatment_hours": 24},
            make_officer_headers("co-v8"))
        validate_error(resp, ApiErrorId.ERR_CHANNEL_MISMATCH)
        resp = api_client.create_export_lot(
            {"destination_market": "EU", "variety": "HAMLIN", "grade": "FANCY",
             "boxes": 5, "source_channel_id": channel["id"],
             "source_grove_id": grove_id},
            make_officer_headers("co-v8"))
        validate_error(resp, ApiErrorId.ERR_CHANNEL_MISMATCH)


class TestFruitFlyProtocol:
    def test_fruit_fly_protocol_block_market_specific(self, api):
        """PRD §2.6 tier 7: "The export-protocol gates
        `ERR_COLD_TREATMENT_INSUFFICIENT` and `ERR_FRUIT_FLY_PROTOCOL_BLOCK`
        also live in this tier, and for JAPAN-bound export-lot transitions the
        fruit-fly protocol check is evaluated before the generic
        quarantine-posture check, so a lot blocked on both surfaces
        `ERR_FRUIT_FLY_PROTOCOL_BLOCK`." PRD §3.9: "for a `JAPAN`-bound lot,
        no `ACTIVE` `FRUIT_FLY` quarantine order may cover the source grove or
        its county, failing which the request is rejected with
        `ERR_FRUIT_FLY_PROTOCOL_BLOCK`".

        Design: Corner/errors/fruit_fly_protocol_block_market_specific
        """
        scenario = setup_posted_scenario(
            "ER7", gross_boxes=40, fancy_boxes=40, choice_boxes=0,
            standard_boxes=0, juice_boxes=0, cull_boxes=0,
            color_score=8, defect_pct=5,
            channel_specs=[
                jp_export_spec("JP-ER7", "HAMLIN", boxes=25),
                eu_export_spec("EU-ER7", "HAMLIN", boxes=10, price=700),
                juice_spec("JU-ER7", "HAMLIN"),
            ])
        grove_id = scenario["grove"]["id"]
        lot_jp = create_export_lot("JAPAN", "HAMLIN", "FANCY", 5,
                                   scenario["channels"]["JP-ER7"]["id"],
                                   grove_id, 24, officer_id="co-ff-a")
        lot_eu = create_export_lot("EU", "HAMLIN", "FANCY", 5,
                                   scenario["channels"]["EU-ER7"]["id"],
                                   grove_id, 0, officer_id="co-ff-a")
        order = create_quarantine("COUNTY_ZONE", "FRUIT_FLY", county_code="POLK",
                                  officer_id="co-ff-a")
        assert get_grove(grove_id)["quarantine_posture"] == "QUARANTINED"
        resp = api_client.request_inspection(
            lot_jp["id"], make_officer_headers("co-ff-a"))
        validate_error(resp, ApiErrorId.ERR_FRUIT_FLY_PROTOCOL_BLOCK)
        resp = api_client.request_inspection(
            lot_eu["id"], make_officer_headers("co-ff-a"))
        validate_error(resp, ApiErrorId.ERR_GROVE_QUARANTINED)
        # Releasing the order (by a different officer) unblocks the JAPAN lot.
        validate_success(release_quarantine(order["id"], True, "co-ff-b"))
        ready = validate_success(api_client.request_inspection(
            lot_jp["id"], make_officer_headers("co-ff-a")))
        assert ready["status"] == "INSPECTION_READY"


class TestExportDiversionCredit:
    def test_export_diversion_credit_math(self, api):
        """PRD §3.9: "Diversion moves the lot to the terminal `DIVERTED` with
        `diverted_to` set to `JUICE`, and adjusts the pool's
        `posted_proceeds_cents` by the lot's `boxes` multiplied by the
        difference between the juice channel's `price_cents_per_box` and the
        source export channel's `price_cents_per_box` — a credit when juice
        pays more, a debit when it pays less; the pool's `posted_ge_boxes` is
        unchanged, since grade-equivalent boxes measure fruit rather than
        destination, and the pool's provisional price is recomputed with a
        version bump."

        Design: Corner/calculations/export_diversion_credit_math
        """
        scenario = setup_posted_scenario("CA8")
        pool_before = scenario["pool"]
        assert pool_before["posted_proceeds_cents"] == 49760
        assert pool_before["posted_ge_boxes"] == 96.8
        lot = create_export_lot("JAPAN", "HAMLIN", "FANCY", 10,
                                scenario["channels"]["JP-CA8"]["id"],
                                scenario["grove"]["id"], 24,
                                officer_id="co-ca8")
        diverted = validate_success(api_client.divert_export_lot(
            lot["id"], make_officer_headers("co-ca8")))
        assert diverted["status"] == "DIVERTED"
        assert diverted["diverted_to"] == "JUICE"
        pool = get_pool(scenario["pool"]["id"])
        # 10 boxes * (220 juice - 900 export) = -6800 debit.
        assert pool["posted_proceeds_cents"] == 49760 - 6800
        assert pool["posted_ge_boxes"] == 96.8, "ge measures fruit, not destination"
        # Both finite channels were exhausted at post, so the projection adds
        # nothing: round_half_up(42960 / 96.8) = 444.
        assert pool["provisional_price_cents_per_ge_box"] == 444
        assert_version_incremented(pool["version"], pool_before["version"])
