"""Endpoint behaviour end to end: the surety's re-limit, the seal-event chain,
the sweep as a bulk action, the carrier's computed read, and export perfection."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors, factories
from test_helpers.assertions import (
    assert_bond_amounts,
    assert_field,
    assert_ledger_stream,
    assert_money,
    assert_movement_state,
    assert_points,
)
from test_helpers.fixtures import (
    LATE_ARRIVAL_ASSESSED,
    LATE_ARRIVAL_CLOCK,
    M1_OBLIGATION,
    M1_SEAL,
    M2_SEAL,
    build_departed_movement,
    build_export_pending_proof,
    build_filed_movement,
    build_registered_world,
    build_two_departed_movements,
)
from test_helpers.test_users import CBP_OFFICER_1_ID


class TestSuretyRelimit:
    """Raising the limit moves the headroom and nothing else."""

    def test_raising_the_limit_recomputes_available_without_touching_the_ledger(
        self, client
    ):
        """The surety lifts the limit from 50,000.00 to 60,000.00, so headroom
        becomes 59,958.25 while the 41.75 already obligated and the single ledger
        entry behind it stay exactly as they were.

        PRD: "Changing `limit_amount` recomputes `available_amount` as the new limit less the unchanged `obligated_amount` and immediately re-derives the `ACTIVE`/`SATURATED` pair from that new headroom."

        PRD: "`total_count` reflects the number of records matching the filters before pagination is applied, and `has_more` is true exactly when records beyond the current window remain."

        Design: Corner/endpoints/surety_raises_the_bond_limit_and_the_available_amount_follows
        """
        world = build_filed_movement(client)

        raised = validate_success(
            client.patch_bond(
                world.bond_id, factories.bond_limit_payload(60000.00), world.surety
            ),
            200,
        )
        assert_money(raised["limit_amount"], 60000.00, "limit_amount")
        assert_bond_amounts(
            raised, obligated=M1_OBLIGATION, available=59958.25, status="ACTIVE"
        )

        _entries, ledger_meta = world.ledger_page(bond_id=world.bond_id)
        assert ledger_meta["total_count"] == 1, (
            f"a limit change is not a ledger event, so the audit trail should still "
            f"hold one entry but holds {ledger_meta['total_count']}"
        )

        rows, meta = validate_paginated(
            client.list_bonds(
                world.officer,
                params={
                    "carrier_id": world.carrier_id,
                    "bond_type": "CONTINUOUS",
                    "status": "ACTIVE",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1, (
            f"the carrier has one continuous bond but the filtered read counted "
            f"{meta['total_count']}"
        )
        assert meta["has_more"] is False, (
            "a single row inside a window of ten leaves nothing beyond it"
        )
        assert rows[0]["id"] == world.bond_id, (
            "the filtered read should return the re-limited bond"
        )


class TestSealEventChain:
    """A replacement restores integrity but does not lift the hold the break
    created."""

    def test_a_replacement_restores_integrity_and_leaves_the_system_hold_open(
        self, client
    ):
        """The unauthorized break sets integrity false and opens a system-created
        SEAL_DISCREPANCY hold; the lawful replacement sets integrity true again, yet
        the hold stays OPEN and custody stays at EXAM_HOLD.

        PRD: "`BROKEN_UNAUTHORIZED` records an unexplained break: it sets `seal_intact` false **and** triggers a cascade."

        PRD: "The system automatically creates an examination hold of type `SEAL_DISCREPANCY` against the movement with `created_by_system` true and `placed_by_user_id` recorded as the literal string `SYSTEM`, which drives `custody_status` to `EXAM_HOLD`, recomputes `open_hold_count` for the port whose `port_code` matches the seal event, and — when the movement is at `ARRIVED` and has not yet consumed its one-time general-order grace — extends the general-order deadline as described in §3.6."

        PRD: "`REPLACED` records a lawfully re-sealed container and sets `seal_intact` true, which is the only way to restore integrity after a break."

        Design: Corner/endpoints/replaced_seal_event_restores_integrity_without_lifting_the_system_hold
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]
        world.set_clock("2026-08-05T00:00:00Z")

        broken = validate_success(
            client.record_seal_event(
                factories.seal_event_payload(
                    movement_id,
                    "BROKEN_UNAUTHORIZED",
                    M1_SEAL,
                    factories.PORT_CHICAGO_CODE,
                ),
                world.carrier,
            ),
            201,
        )
        assert_field(broken, "resulting_seal_intact", False, "seal event")

        replaced = validate_success(
            client.record_seal_event(
                factories.seal_event_payload(
                    movement_id, "REPLACED", "SEAL-101", factories.PORT_CHICAGO_CODE
                ),
                world.carrier,
            ),
            201,
        )
        assert_field(replaced, "resulting_seal_intact", True, "seal event")

        movement = world.read_movement(movement_id)
        assert_field(movement, "seal_intact", True, "movement")
        assert_movement_state(
            movement, transit_status="IN_TRANSIT", custody_status="EXAM_HOLD"
        )

        holds = world.holds(movement_id=movement_id)
        assert len(holds) == 1, (
            f"the break should have opened exactly one system hold but the movement "
            f"carries {len(holds)}"
        )
        assert_field(holds[0], "hold_type", "SEAL_DISCREPANCY", "hold")
        assert_field(holds[0], "status", "OPEN", "hold")
        assert_field(holds[0], "created_by_system", True, "hold")
        assert_field(holds[0], "placed_by_user_id", "SYSTEM", "hold")
        assert_field(world.read_port("chicago"), "open_hold_count", 1, "port")

        events = world.seal_events(movement_id)
        assert [event["event_type"] for event in events] == [
            "APPLIED",
            "BROKEN_UNAUTHORIZED",
            "REPLACED",
        ], (
            "the seal history should read in occurrence order but reads "
            f"{[event['event_type'] for event in events]}"
        )


class TestComplianceSweepAsBulkAction:
    """The sweep applies to the movements that qualify and leaves the rest
    alone."""

    def test_the_sweep_marks_the_two_in_transit_movements_and_spares_the_filed_one(
        self, client
    ):
        """Three movements share the same lapsed deadline, but only the two that
        actually left are marked overdue, and the sweep names exactly those two.

        PRD: "First, every movement whose `transit_status` is `IN_TRANSIT` and whose `transit_deadline_utc` now lies strictly before the clock moves `IN_TRANSIT → OVERDUE`."

        PRD: "The sweep stamps `run_at` from the clock and `executed_by_officer_id` from the acting `X-User-ID`, and it performs four passes."

        Design: Corner/endpoints/sweep_marks_only_the_in_transit_movements_overdue
        """
        world = build_registered_world(client)
        first = world.file_movement("MAN-0001")
        second = world.file_movement("MAN-0002")
        never_departed = world.file_movement("MAN-0003")
        world.depart(first, M1_SEAL)
        world.depart(second, M2_SEAL)

        world.set_clock("2026-09-25T00:00:00Z")
        sweep = world.run_sweep("nightly overdue sweep")

        assert_field(sweep, "overdue_marked_count", 2, "sweep")
        assert sorted(sweep["overdue_movement_ids"]) == sorted([first, second]), (
            "the sweep should name the two departed movements but named "
            f"{sweep['overdue_movement_ids']}"
        )
        assert_field(sweep, "run_at", "2026-09-25T00:00:00Z", "sweep")
        assert_field(sweep, "executed_by_officer_id", CBP_OFFICER_1_ID, "sweep")
        assert_field(sweep, "note", "nightly overdue sweep", "sweep")

        for movement_id in (first, second):
            movement = world.read_movement(movement_id)
            assert_movement_state(movement, transit_status="OVERDUE")
            assert_field(movement, "overdue_days", 20, "movement")

        spared = world.read_movement(never_departed)
        assert_movement_state(spared, transit_status="FILED")
        assert_field(spared, "overdue_days", 0, "movement")

        carrier = world.read_carrier()
        assert_field(carrier, "overdue_movement_count", 2, "carrier")
        assert_points(carrier["sanction_points"], 0.0)

        _rows, meta = world.sweeps(limit=10, offset=0)
        assert meta["total_count"] == 1, (
            f"one sweep was run but the register holds {meta['total_count']}"
        )


class TestCarrierComplianceRead:
    """One read shows the whole live posture."""

    def test_the_carrier_read_shows_points_open_claims_and_overdue_movements(
        self, client
    ):
        """After both movements are swept overdue and one of them arrives and draws a
        late-arrival claim, the carrier read shows 2.0 points, one open claim and one
        movement still overdue.

        PRD: "`overdue_movement_count` is always the live count of that carrier's movements whose `transit_status` is `OVERDUE`; `open_claim_count` is the live count of liquidated-damages claims against that carrier's movements whose `status` is `ISSUED`, `PETITIONED`, or `MITIGATED`."

        PRD: "The type weights are 2 for `LATE_ARRIVAL`, 3 for `NO_PROOF_OF_EXPORT`, 4 for `SEAL_VIOLATION`, 4 for `UNAUTHORIZED_DIVERSION`, and 6 for `NON_ARRIVAL`."

        Design: Corner/endpoints/carrier_read_exposes_the_live_compliance_posture
        """
        world = build_two_departed_movements(client)
        overdue_leg = world.movements["MAN-0001"]
        arriving_leg = world.movements["MAN-0002"]

        world.set_clock(LATE_ARRIVAL_CLOCK)
        world.run_sweep("mark both overdue")
        world.report_arrival(arriving_leg)
        claim = world.issue_claim(arriving_leg, "LATE_ARRIVAL", "OVERDUE_ARRIVAL")

        carrier = validate_success(
            client.get_carrier(world.carrier_id, world.officer), 200
        )
        assert_points(carrier["sanction_points"], 2.0)
        assert_field(carrier, "open_claim_count", 1, "carrier")
        assert_field(carrier, "overdue_movement_count", 1, "carrier")
        assert_field(carrier, "custodial_status", "ACTIVE", "carrier")

        still_overdue = world.read_movement(overdue_leg)
        assert_movement_state(still_overdue, transit_status="OVERDUE")
        assert_field(still_overdue, "overdue_days", 7, "movement")

        arrived = world.read_movement(arriving_leg)
        assert_movement_state(arrived, transit_status="ARRIVED")
        assert_field(arrived, "overdue_days", 7, "movement")

        assert_money(
            claim["assessed_amount"], LATE_ARRIVAL_ASSESSED, "claim assessed_amount"
        )


class TestExportProof:
    """Proof can be supplied once, and only while the report is waiting for it."""

    def test_the_proof_perfects_the_export_once_and_is_refused_a_second_time(
        self, client
    ):
        """The export report waits at PENDING_PROOF with the movement still ARRIVED;
        the proof drives it to EXPORTED and straight on to CLOSED, releasing the
        bond — and a second proof call on the accepted report is refused.

        PRD: "When an `EXPORT` report arrives **without** `proof_of_export_ref`, it is stored at `status` `PENDING_PROOF` and the export is not perfected: neither `transit_status` nor `export_reported_at` changes."

        PRD: "The carrier can perfect it later by supplying the missing `proof_of_export_ref`, optionally together with an `export_conveyance_ref`; the report moves `PENDING_PROOF → ACCEPTED` and the movement advances to `EXPORTED` exactly as if the proof had arrived with the original report."

        PRD: "Closing transitions `EXPORTED → CLOSED` and appends a `RELEASE` ledger entry for the negative of `obligation_amount` with `reason_code` `MOVEMENT_EXPORTED`, which recomputes the bond's `obligated_amount`, `available_amount`, and `open_movement_count` and returns a `SATURATED` bond to `ACTIVE` when headroom reappears above 0.00."

        PRD: "Perfecting a report requires that it actually be in `PENDING_PROOF` — anything else is `ERR_REPORT_INVALID_STATE` — that the acting user be the movement's carrier, that `seal_intact` be true, and that `custody_status` not be `GENERAL_ORDER`."

        Design: Corner/endpoints/export_proof_is_accepted_once_and_only_from_pending_proof
        """
        world, report = build_export_pending_proof(client)
        movement_id = world.movements["MAN-0060"]

        assert_field(report, "status", "PENDING_PROOF", "report")
        assert_movement_state(
            world.read_movement(movement_id), transit_status="ARRIVED"
        )

        perfected = validate_success(
            client.submit_export_proof(
                report["id"],
                factories.export_proof_payload("BOL-88123", "VESSEL-ATLANTIC-9"),
                world.carrier,
            ),
            200,
        )
        assert_field(perfected, "status", "ACCEPTED", "report")
        assert_field(perfected, "proof_of_export_ref", "BOL-88123", "report")
        assert_field(
            perfected, "export_conveyance_ref", "VESSEL-ATLANTIC-9", "report"
        )

        closed = world.read_movement(movement_id)
        assert_movement_state(closed, transit_status="CLOSED")
        assert_field(closed, "export_reported_at", "2026-08-12T00:00:00Z", "movement")

        assert_bond_amounts(
            world.read_bond(),
            obligated=0.00,
            available=50000.00,
            status="ACTIVE",
            open_movement_count=0,
        )
        assert_ledger_stream(
            world.ledger_entries(movement_id=movement_id),
            [
                {
                    "entry_type": "OBLIGATE",
                    "amount": M1_OBLIGATION,
                    "balance_after": M1_OBLIGATION,
                    "reason_code": "MOVEMENT_FILED",
                },
                {
                    "entry_type": "RELEASE",
                    "amount": -M1_OBLIGATION,
                    "balance_after": 0.00,
                    "reason_code": "MOVEMENT_EXPORTED",
                },
            ],
        )

        response = client.submit_export_proof(
            report["id"],
            factories.export_proof_payload("BOL-88124"),
            world.carrier,
        )
        validate_error(response, api_errors.ERR_REPORT_INVALID_STATE, 409)
        assert_field(
            world.read_report(report["id"]),
            "proof_of_export_ref",
            "BOL-88123",
            "report",
        )
