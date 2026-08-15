"""Catch reports, landing declarations, discrepancy tolerance, quota posting,
and TAC-driven early closure cascades (PRD §3.4, §3.5, §3.2, §2.8)."""
from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    assert_catch_report,
    create_catch_report_payload,
    create_landing_declaration_payload,
    create_opening,
    declare_and_submit,
    get_assignment,
    get_declaration,
    get_holding,
    get_observer,
    get_opening,
    get_trip,
    get_trip_assignment,
    make_captain_headers,
    plan_trip,
    register_observer,
    setup_executed_trip,
    setup_vessel_ready,
    validate_error,
    validate_success,
)

REG = TEST_USERS["regulator_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestDisputeAmendCycle:
    def test_dispute_amend_resubmit_verify_cycle(self):
        """PRD §3.5: "if any line is outside its tolerance, the declaration does not
        error — it transitions from `SUBMITTED` to `DISPUTED` with a normal success
        response, and verification stops there." and "A disputed declaration returns
        to the captain, who amends it by supplying a replacement set of `lines`;
        amendment requires `DISPUTED` status (`ERR_DECLARATION_NOT_DISPUTED`) and
        moves the declaration to `AMENDED`, from which it may be submitted again."

        Design: Difficulty/non_linear_state_machine/landing_declaration_dispute_amend_cycle
        """
        ctx = setup_executed_trip(catch_lbs=4000, holding_pounds=10000)
        vessel_id = ctx["vessel"]["id"]
        declaration = declare_and_submit(ctx["trip"]["id"], vessel_id,
                                         declared_lbs=5000)
        disputed = validate_success(
            api_client.verify_landing_declaration(declaration["id"], REG), 200)
        assert disputed["status"] == "DISPUTED", (
            "declared 5000 vs expected 4000 exceeds the 200-lb tolerance")
        captain = make_captain_headers(vessel_id)
        amended = validate_success(api_client.amend_landing_declaration(
            declaration["id"],
            {"lines": [{"fishery_code": "HALIBUT", "declared_lbs": 4000}]},
            captain), 200)
        assert amended["status"] == "AMENDED"
        resubmitted = validate_success(
            api_client.submit_landing_declaration(declaration["id"], captain), 200)
        assert resubmitted["status"] == "SUBMITTED"
        verified = validate_success(
            api_client.verify_landing_declaration(declaration["id"], REG), 200)
        assert verified["status"] == "VERIFIED"
        assert verified["discrepancy_details"][0]["within_tolerance"] is True
        assert get_holding(ctx["holding"]["id"])["landed_pounds"] == 4000, (
            "only the amended figure is posted")

    def test_verify_over_tolerance_returns_success_not_error(self):
        """PRD §3.5: "Third, the discrepancy gate: if any line is outside its
        tolerance, the declaration does not error — it transitions from `SUBMITTED`
        to `DISPUTED` with a normal success response, and verification stops there."

        Design: Difficulty/non_linear_state_machine/landing_declaration_dispute_amend_cycle
        """
        ctx = setup_executed_trip(catch_lbs=4000, holding_pounds=10000)
        declaration = declare_and_submit(ctx["trip"]["id"], ctx["vessel"]["id"],
                                         declared_lbs=5000)
        resp = api_client.verify_landing_declaration(declaration["id"], REG)
        assert resp.status_code == 200, (
            f"over-tolerance verify must be a normal success, got {resp.status_code}")
        body = validate_success(resp, 200)
        assert body["status"] == "DISPUTED"
        assert body["discrepancy_details"][0]["within_tolerance"] is False
        assert get_holding(ctx["holding"]["id"])["landed_pounds"] == 0, (
            "no landings post while the declaration is disputed")


class TestLandingQuotaBoundary:
    def test_landing_at_exact_available_quota_accepted(self):
        """PRD §3.5: "for each line, the vessel's quota share holding matching the
        line's `fishery_code` and the applicable season year must have
        `available_committed_pounds` at least equal to the line's `declared_lbs`" —
        an exact match satisfies "at least equal".

        Design: Difficulty/boundary_precision_check/landing_quota_exact_boundary
        """
        ctx = setup_executed_trip(catch_lbs=6000, holding_pounds=6000)
        declaration = declare_and_submit(ctx["trip"]["id"], ctx["vessel"]["id"],
                                         declared_lbs=6000)
        verified = validate_success(
            api_client.verify_landing_declaration(declaration["id"], REG), 200)
        assert verified["status"] == "VERIFIED"
        assert get_holding(ctx["holding"]["id"])["landed_pounds"] == 6000

    def test_landing_one_pound_over_quota_rejected(self):
        """PRD §3.5: "a missing holding is `ERR_QUOTA_HOLDING_NOT_FOUND`, and
        insufficient quota is `ERR_QUOTA_EXCEEDED` (HTTP 402)" — with
        available_committed 0 after the first verification, a 1-lb line fails.

        Design: Difficulty/boundary_precision_check/landing_quota_exact_boundary
        """
        ctx = setup_executed_trip(catch_lbs=6000, holding_pounds=6000)
        vessel_id = ctx["vessel"]["id"]
        opening = ctx["opening"]
        declaration1 = declare_and_submit(ctx["trip"]["id"], vessel_id,
                                          declared_lbs=6000)
        validate_success(
            api_client.verify_landing_declaration(declaration1["id"], REG), 200)
        # Second trip on a non-overlapping window lands 1 lb against the
        # exhausted holding.
        advance_clock("2026-08-13T06:00:00Z")
        trip2 = plan_trip(vessel_id, opening["id"],
                          departure="2026-08-13T06:00:00Z",
                          return_="2026-08-15T06:00:00Z")
        captain = make_captain_headers(vessel_id)
        validate_success(api_client.depart_trip(trip2["id"], captain), 200)
        validate_success(api_client.create_catch_report(
            trip2["id"],
            create_catch_report_payload(reported_lbs=1,
                                        reported_at="2026-08-14T06:00:00Z"),
            captain), 201)
        advance_clock("2026-08-15T06:00:00Z")
        validate_success(api_client.return_trip(trip2["id"], captain), 200)
        declaration2 = declare_and_submit(trip2["id"], vessel_id, declared_lbs=1)
        resp = api_client.verify_landing_declaration(declaration2["id"], REG)
        validate_error(resp, "ERR_QUOTA_EXCEEDED", 402)
        assert get_holding(ctx["holding"]["id"])["landed_pounds"] == 6000


class TestTacBoundary:
    def _run_opening_trip(self, area_code, tac_pounds, declared_lbs=5000):
        """One vessel executes a trip on its own opening and submits a
        declaration of declared_lbs. Returns (ctx, declaration)."""
        ctx = setup_vessel_ready(holding_pounds=10000)
        opening = create_opening(area_code=area_code, tac_pounds=tac_pounds)
        advance_clock("2026-08-10T06:00:00Z")
        vessel_id = ctx["vessel"]["id"]
        trip = plan_trip(vessel_id, opening["id"])
        captain = make_captain_headers(vessel_id)
        validate_success(api_client.depart_trip(trip["id"], captain), 200)
        validate_success(api_client.create_catch_report(
            trip["id"],
            create_catch_report_payload(reported_lbs=declared_lbs,
                                        reported_at="2026-08-11T06:00:00Z"),
            captain), 201)
        advance_clock("2026-08-12T06:00:00Z")
        validate_success(api_client.return_trip(trip["id"], captain), 200)
        declaration = declare_and_submit(trip["id"], vessel_id,
                                         declared_lbs=declared_lbs)
        ctx["opening"] = opening
        ctx["trip"] = trip
        return ctx, declaration

    def test_landing_exactly_to_tac_closes_opening(self):
        """PRD §3.2: "Early closure also fires automatically when a verified landing
        pushes `landed_against_tac_pounds` to meet or exceed `tac_pounds` — the
        threshold is inclusive, so landing exactly up to the TAC closes the
        fishery."

        Design: Difficulty/boundary_precision_check/tac_exact_equality_closes_opening
        """
        ctx, declaration = self._run_opening_trip("3A", 5000)
        validate_success(
            api_client.verify_landing_declaration(declaration["id"], REG), 200)
        opening = get_opening(ctx["opening"]["id"])
        assert opening["landed_against_tac_pounds"] == 5000
        assert opening["status"] == "CLOSED_EARLY"

    def test_landing_one_pound_below_tac_stays_open(self):
        """PRD §3.2: "the threshold is inclusive, so landing exactly up to the TAC
        closes the fishery" — one pound short of `tac_pounds` leaves the opening
        OPEN.

        Design: Difficulty/boundary_precision_check/tac_exact_equality_closes_opening
        """
        ctx, declaration = self._run_opening_trip("3B", 5001)
        validate_success(
            api_client.verify_landing_declaration(declaration["id"], REG), 200)
        opening = get_opening(ctx["opening"]["id"])
        assert opening["landed_against_tac_pounds"] == 5000
        assert opening["status"] == "OPEN"


class TestTacCascade:
    def test_tac_exhaustion_cascades_to_observer_availability(self):
        """PRD §3.2: "Either closure path cancels every `PLANNED` trip on the
        opening, cancels each such trip's non-terminal observer assignments, and
        recomputes the affected observers' availability." PRD §3.5: "If that
        posting pushes the opening to its TAC, the early-closure cascade of §3.2
        fires from within the verification."

        Design: Difficulty/transitive_cascade/tac_exhaustion_early_close_cascade
        """
        # Vessel 1 runs the trip that exhausts the TAC.
        v1 = setup_vessel_ready(holding_pounds=10000)["vessel"]
        # Vessel 2 holds a PLANNED 100h observer-required trip with an ASSIGNED
        # observer.
        v2 = setup_vessel_ready(vessel_name="FV Bristol", home_port="KODIAK")["vessel"]
        opening = create_opening(tac_pounds=5000)
        observer = register_observer(certification_level="B")
        trip2 = plan_trip(v2["id"], opening["id"],
                          departure="2026-08-10T06:00:00Z",
                          return_="2026-08-14T06:00:00Z")
        assignment2 = get_trip_assignment(trip2["id"])
        validate_success(api_client.assign_observer(
            assignment2["id"],
            {"observer_id": observer["id"],
             "coverage_from": "2026-08-10T00:00:00Z",
             "coverage_to": "2026-08-14T06:00:00Z",
             "expected_observer_version": observer["version"]},
            COORD), 200)
        assert get_observer(observer["id"])["status"] == "ON_ASSIGNMENT"
        # Vessel 1's trip executes and declares exactly the TAC.
        advance_clock("2026-08-10T06:00:00Z")
        trip1 = plan_trip(v1["id"], opening["id"])
        captain1 = make_captain_headers(v1["id"])
        validate_success(api_client.depart_trip(trip1["id"], captain1), 200)
        validate_success(api_client.create_catch_report(
            trip1["id"],
            create_catch_report_payload(reported_lbs=5000,
                                        reported_at="2026-08-11T06:00:00Z"),
            captain1), 201)
        advance_clock("2026-08-12T06:00:00Z")
        validate_success(api_client.return_trip(trip1["id"], captain1), 200)
        declaration = declare_and_submit(trip1["id"], v1["id"], declared_lbs=5000)
        validate_success(
            api_client.verify_landing_declaration(declaration["id"], REG), 200)
        opening_now = get_opening(opening["id"])
        assert opening_now["landed_against_tac_pounds"] == 5000
        assert opening_now["status"] == "CLOSED_EARLY"
        assert get_trip(trip2["id"])["status"] == "CANCELLED"
        assert get_assignment(assignment2["id"])["status"] == "CANCELLED"
        assert get_observer(observer["id"])["status"] == "AVAILABLE", (
            "cancelling the assignment must recompute the observer to AVAILABLE")

    def test_manual_early_close_cancels_planned_trips(self):
        """PRD §3.2: "A regulator may also close an `OPEN` opening early, moving it
        to `CLOSED_EARLY`; the manual path requires the opening to actually be
        `OPEN`, failing otherwise with `ERR_OPENING_NOT_OPEN`." and "Either closure
        path cancels every `PLANNED` trip on the opening, cancels each such trip's
        non-terminal observer assignments, and recomputes the affected observers'
        availability."

        Design: Difficulty/transitive_cascade/tac_exhaustion_early_close_cascade
        """
        ctx = setup_vessel_ready()
        opening = create_opening(tac_pounds=100000)
        trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                         departure="2026-08-10T06:00:00Z",
                         return_="2026-08-14T06:00:00Z")  # 100h -> observer required
        assignment = get_trip_assignment(trip["id"])
        advance_clock("2026-08-10T06:00:00Z")
        closed = validate_success(
            api_client.close_opening_early(opening["id"], REG), 200)
        assert closed["status"] == "CLOSED_EARLY"
        assert get_trip(trip["id"])["status"] == "CANCELLED"
        assert get_assignment(assignment["id"])["status"] == "CANCELLED"


class TestVerifyGatePriority:
    def test_verify_draft_declaration_state_gate_wins(self):
        """PRD §3.5: "Verification is a regulator action with three gates, evaluated
        in order. First, the declaration must be `SUBMITTED`
        (`ERR_DECLARATION_NOT_SUBMITTED`)." and "Only when every line is within
        tolerance does the quota gate run".

        Design: Difficulty/priority_pair_validation_conflict/verify_state_beats_quota_fiscal
        """
        ctx = setup_executed_trip(catch_lbs=500, holding_pounds=1000)
        captain = make_captain_headers(ctx["vessel"]["id"])
        declaration = validate_success(api_client.create_landing_declaration(
            ctx["trip"]["id"],
            create_landing_declaration_payload(
                lines=[{"fishery_code": "HALIBUT", "declared_lbs": 99999}]),
            captain), 201)
        assert declaration["status"] == "DRAFT"
        resp = api_client.verify_landing_declaration(declaration["id"], REG)
        validate_error(resp, "ERR_DECLARATION_NOT_SUBMITTED", 409)
        assert get_holding(ctx["holding"]["id"])["landed_pounds"] == 0

    def test_verify_disputed_declaration_state_gate_wins(self):
        """PRD §3.5: "First, the declaration must be `SUBMITTED`
        (`ERR_DECLARATION_NOT_SUBMITTED`)" — a DISPUTED declaration with an
        over-quota line still fails the state gate, never the quota gate.

        Design: Difficulty/priority_pair_validation_conflict/verify_state_beats_quota_fiscal
        """
        ctx = setup_executed_trip(catch_lbs=500, holding_pounds=1000)
        declaration = declare_and_submit(ctx["trip"]["id"], ctx["vessel"]["id"],
                                         declared_lbs=99999)
        disputed = validate_success(
            api_client.verify_landing_declaration(declaration["id"], REG), 200)
        assert disputed["status"] == "DISPUTED"
        resp = api_client.verify_landing_declaration(declaration["id"], REG)
        validate_error(resp, "ERR_DECLARATION_NOT_SUBMITTED", 409)
        assert get_holding(ctx["holding"]["id"])["landed_pounds"] == 0


class TestDiscrepancyTolerance:
    def test_discrepancy_tolerance_boundary_inclusive(self):
        """PRD §3.5: "otherwise the tolerance is 5 percent of `expected_lbs` rounded
        half-up to whole pounds, and the line is within tolerance when the absolute
        difference between `declared_lbs` and `expected_lbs` is no greater than
        that tolerance — the boundary is inclusive, so a difference exactly equal
        to the tolerance passes."

        Design: Corner/calculations/discrepancy_tolerance_boundary_inclusive
        """
        ctx = setup_executed_trip(catch_lbs=4000, holding_pounds=20000)
        vessel_id = ctx["vessel"]["id"]
        opening = ctx["opening"]
        # Trip 1 declares exactly at tolerance: expected 4000, tolerance 200.
        declaration1 = declare_and_submit(ctx["trip"]["id"], vessel_id,
                                          declared_lbs=4200)
        # Trip 2 on a non-overlapping window declares one pound over tolerance.
        advance_clock("2026-08-13T06:00:00Z")
        trip2 = plan_trip(vessel_id, opening["id"],
                          departure="2026-08-13T06:00:00Z",
                          return_="2026-08-15T06:00:00Z")
        captain = make_captain_headers(vessel_id)
        validate_success(api_client.depart_trip(trip2["id"], captain), 200)
        validate_success(api_client.create_catch_report(
            trip2["id"],
            create_catch_report_payload(reported_lbs=4000,
                                        reported_at="2026-08-14T06:00:00Z"),
            captain), 201)
        advance_clock("2026-08-15T06:00:00Z")
        validate_success(api_client.return_trip(trip2["id"], captain), 200)
        declaration2 = declare_and_submit(trip2["id"], vessel_id, declared_lbs=4201)
        verified = validate_success(
            api_client.verify_landing_declaration(declaration1["id"], REG), 200)
        assert verified["status"] == "VERIFIED", (
            "diff 200 == tolerance 200 is inclusive and passes")
        disputed = validate_success(
            api_client.verify_landing_declaration(declaration2["id"], REG), 200)
        assert disputed["status"] == "DISPUTED", (
            "diff 201 > 200 disputes without an error")


class TestDeclarationGates:
    def test_amend_submitted_declaration_rejected(self):
        """PRD §3.5: "amendment requires `DISPUTED` status
        (`ERR_DECLARATION_NOT_DISPUTED`)".

        Design: Corner/state_machines/amend_submitted_declaration_rejected
        """
        ctx = setup_executed_trip(catch_lbs=4000, holding_pounds=10000)
        declaration = declare_and_submit(ctx["trip"]["id"], ctx["vessel"]["id"],
                                         declared_lbs=4000)
        assert declaration["status"] == "SUBMITTED"
        resp = api_client.amend_landing_declaration(
            declaration["id"],
            {"lines": [{"fishery_code": "HALIBUT", "declared_lbs": 3900}]},
            make_captain_headers(ctx["vessel"]["id"]))
        validate_error(resp, "ERR_DECLARATION_NOT_DISPUTED", 409)
        current = get_declaration(declaration["id"])
        assert current["status"] == "SUBMITTED"
        assert current["lines"][0]["declared_lbs"] == 4000

    def test_duplicate_declaration_rejected(self):
        """PRD §3.5: "the captain files the trip's landing declaration — at most one
        per trip; a second attempt is rejected with `ERR_DECLARATION_EXISTS`".

        Design: Corner/state_machines/duplicate_declaration_rejected
        """
        ctx = setup_executed_trip(catch_lbs=4000, holding_pounds=10000)
        captain = make_captain_headers(ctx["vessel"]["id"])
        validate_success(api_client.create_landing_declaration(
            ctx["trip"]["id"], create_landing_declaration_payload(), captain), 201)
        resp = api_client.create_landing_declaration(
            ctx["trip"]["id"],
            create_landing_declaration_payload(
                port_code="KODIAK",
                lines=[{"fishery_code": "HALIBUT", "declared_lbs": 100}]),
            captain)
        validate_error(resp, "ERR_DECLARATION_EXISTS", 409)

    def test_rbac_captain_cannot_verify_landing(self):
        """PRD §4: POST /landing-declarations/{id}/verify lists only
        FisheriesRegulator; PRD §2.1: "a role that is not listed for the endpoint
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)".

        Design: Corner/rbac/rbac_captain_cannot_verify_landing
        """
        ctx = setup_executed_trip(catch_lbs=4000, holding_pounds=10000)
        declaration = declare_and_submit(ctx["trip"]["id"], ctx["vessel"]["id"],
                                         declared_lbs=4000)
        resp = api_client.verify_landing_declaration(
            declaration["id"], make_captain_headers(ctx["vessel"]["id"]))
        validate_error(resp, "ERR_FORBIDDEN_ROLE", 403)
        assert get_declaration(declaration["id"])["status"] == "SUBMITTED"


class TestVerificationPosting:
    def test_immediate_read_after_write_consistency(self):
        """PRD §3.5: "A successful verification moves the declaration to `VERIFIED`
        and posts the landings: for every line, the holding's `landed_pounds`
        increases by `declared_lbs`, and the opening's
        `landed_against_tac_pounds` increases by `declared_lbs`."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        ctx = setup_executed_trip(catch_lbs=4000, holding_pounds=10000)
        declaration = declare_and_submit(ctx["trip"]["id"], ctx["vessel"]["id"],
                                         declared_lbs=4000)
        verified = validate_success(
            api_client.verify_landing_declaration(declaration["id"], REG), 200)
        assert verified["status"] == "VERIFIED"
        assert get_declaration(declaration["id"])["status"] == "VERIFIED"
        holding = get_holding(ctx["holding"]["id"])
        assert holding["landed_pounds"] == 4000
        opening = get_opening(ctx["opening"]["id"])
        assert opening["landed_against_tac_pounds"] == 4000


class TestCatchReports:
    def test_catch_report_client_id_input_ignored(self):
        """PRD §3.4: "Each report receives a `haul_seq`, a per-trip sequence number
        starting at 1 and assigned in creation order, and exists in a permanent
        `RECORDED` state." PRD §2.4: "Three resource kinds are append-only event
        records: catch reports, gear events, and VMS pings. These carry only `id`
        and `created_at` — both `updated_at` and `version` are absent — and once
        created they cannot be modified or deleted."

        Design: Corner/entities/catch_report_client_id_input_ignored
        """
        ctx = setup_vessel_ready()
        opening = create_opening()
        advance_clock("2026-08-10T06:00:00Z")
        trip = plan_trip(ctx["vessel"]["id"], opening["id"])
        captain = make_captain_headers(ctx["vessel"]["id"])
        validate_success(api_client.depart_trip(trip["id"], captain), 200)
        first = validate_success(api_client.create_catch_report(
            trip["id"],
            create_catch_report_payload(reported_lbs=1000,
                                        reported_at="2026-08-11T00:00:00Z"),
            captain), 201)
        second = validate_success(api_client.create_catch_report(
            trip["id"],
            create_catch_report_payload(report_type="DISCARD", reported_lbs=100,
                                        reported_at="2026-08-11T01:00:00Z"),
            captain), 201)
        assert_catch_report(first)
        assert_catch_report(second)
        assert first["haul_seq"] == 1
        assert second["haul_seq"] == 2

    def test_catch_report_requires_departed(self):
        """PRD §3.4: "Reports are append-only: creation is the only write, and
        attempting to file one before the trip has departed is rejected with
        `ERR_TRIP_NOT_DEPARTED`."

        Design: Corner/state_machines/catch_report_requires_departed
        """
        ctx = setup_vessel_ready()
        opening = create_opening()
        trip = plan_trip(ctx["vessel"]["id"], opening["id"])
        resp = api_client.create_catch_report(
            trip["id"],
            create_catch_report_payload(reported_lbs=100,
                                        reported_at="2026-08-10T08:00:00Z"),
            make_captain_headers(ctx["vessel"]["id"]))
        validate_error(resp, "ERR_TRIP_NOT_DEPARTED", 409)


class TestVmsGapDetection:
    def test_vms_gap_detection_boundary(self):
        """PRD §3.4: "Consecutive pings — including the synthetic boundaries — are
        then compared, and if any gap is strictly longer than 120 minutes, the
        system creates a compliance violation of type `VMS_GAP` in `OPEN` status
        linked to this trip, with `details` recording the longest gap. A gap of
        exactly 120 minutes is compliant; the comparison is strictly
        greater-than."

        Design: Corner/calculations/vms_gap_detection_boundary
        """
        ctx = setup_vessel_ready(vms_unit_id="VMS-1")
        vessel_id = ctx["vessel"]["id"]
        opening = create_opening()
        captain = make_captain_headers(vessel_id)
        # Trip 1: gaps of exactly 120 minutes (00:00 depart -> 02:00 -> 04:00
        # -> 06:00 return) are compliant.
        advance_clock("2026-08-10T00:00:00Z")
        trip1 = plan_trip(vessel_id, opening["id"],
                          departure="2026-08-10T00:00:00Z",
                          return_="2026-08-10T06:00:00Z")
        validate_success(api_client.depart_trip(trip1["id"], captain), 200)
        for recorded_at in ("2026-08-10T02:00:00Z", "2026-08-10T04:00:00Z"):
            validate_success(api_client.create_vms_ping(
                vessel_id,
                {"recorded_at": recorded_at, "latitude": 59.6, "longitude": -151.5},
                captain), 201)
        advance_clock("2026-08-10T06:00:00Z")
        validate_success(api_client.return_trip(trip1["id"], captain), 200)
        rows = validate_success(
            api_client.list_violations(REG, params={"vessel_id": vessel_id}), 200)
        assert rows == [], f"exactly-120-minute gaps must be compliant, got {rows}"
        # Trip 2: one 121-minute gap (00:00 depart -> 02:01 ping) creates one
        # OPEN VMS_GAP violation linked to the trip.
        advance_clock("2026-08-11T00:00:00Z")
        trip2 = plan_trip(vessel_id, opening["id"],
                          departure="2026-08-11T00:00:00Z",
                          return_="2026-08-11T06:00:00Z")
        validate_success(api_client.depart_trip(trip2["id"], captain), 200)
        validate_success(api_client.create_vms_ping(
            vessel_id,
            {"recorded_at": "2026-08-11T02:01:00Z",
             "latitude": 59.5, "longitude": -151.3},
            captain), 201)
        advance_clock("2026-08-11T04:00:00Z")
        validate_success(api_client.return_trip(trip2["id"], captain), 200)
        rows = validate_success(
            api_client.list_violations(REG, params={"vessel_id": vessel_id}), 200)
        assert len(rows) == 1
        assert rows[0]["violation_type"] == "VMS_GAP"
        assert rows[0]["status"] == "OPEN"
        assert rows[0]["trip_id"] == trip2["id"]
