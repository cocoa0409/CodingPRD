"""LCL consolidation capacity/commodity gates, container assignments, and
the stuffing lifecycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_confirmed_booking,
    create_consolidation_payload,
    create_container_assignment_payload,
    create_open_consolidation,
    create_open_voyage,
    create_active_contract,
    find_booking_invoice,
    setup_fcl_lane,
    setup_lcl_lane,
    setup_stuffed_consolidation,
    stuff_booking,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BC, OPS
from test_helpers.test_users import make_shipper_headers


def _get_consolidation(api, consolidation_id):
    return validate_success(api.get_consolidation(consolidation_id, BC), 200)


class TestCapacityBoundary:
    def _setup_three_bookings(self, api):
        ctx = setup_lcl_lane()
        b1 = create_confirmed_booking(ctx, gross_weight_kg=6000,
                                      volume_cbm=60.0)
        b2 = create_confirmed_booking(ctx, gross_weight_kg=4000,
                                      volume_cbm=40.0)
        b3 = create_confirmed_booking(ctx, gross_weight_kg=0.5,
                                      volume_cbm=0.5)
        consolidation = create_open_consolidation(ctx["voyage"]["id"])
        return ctx, consolidation, b1, b2, b3

    def test_stuff_to_exact_capacity_allowed(self, api):
        """PRD §3.9: "The **capacity gate** requires the resulting totals to
        fit: `used_weight_kg` plus the booking's `gross_weight_kg` must be
        less than or equal to `max_weight_kg`, and `used_volume_cbm` plus the
        booking's `volume_cbm` must be less than or equal to `max_volume_cbm`
        — equality is allowed on both axes, but one kilogram or one cubic
        centimetre over rejects with `ERR_CONSOLIDATION_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/consolidation_capacity_equality_allowed_then_exceeded
        """
        _ctx, consolidation, b1, b2, _b3 = self._setup_three_bookings(api)
        stuff_booking(consolidation["id"], b1["id"])
        stuff_booking(consolidation["id"], b2["id"])

        after = _get_consolidation(api, consolidation["id"])
        assert after["used_weight_kg"] == pytest.approx(10000)
        assert after["used_volume_cbm"] == pytest.approx(100.0)

    def test_one_unit_over_capacity_rejected(self, api):
        """PRD §3.9: "The **capacity gate** requires the resulting totals to
        fit: `used_weight_kg` plus the booking's `gross_weight_kg` must be
        less than or equal to `max_weight_kg`, and `used_volume_cbm` plus the
        booking's `volume_cbm` must be less than or equal to `max_volume_cbm`
        — equality is allowed on both axes, but one kilogram or one cubic
        centimetre over rejects with `ERR_CONSOLIDATION_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/consolidation_capacity_equality_allowed_then_exceeded
        """
        _ctx, consolidation, b1, b2, b3 = self._setup_three_bookings(api)
        stuff_booking(consolidation["id"], b1["id"])
        stuff_booking(consolidation["id"], b2["id"])

        fresh = _get_consolidation(api, consolidation["id"])
        res = api.stuff_consolidation(consolidation["id"], b3["id"],
                                      fresh["version"], BC)
        validate_error(res, ApiErrorId.ERR_CONSOLIDATION_CAPACITY_EXCEEDED,
                       expected_status=422)

        after = _get_consolidation(api, consolidation["id"])
        assert after["used_weight_kg"] == pytest.approx(10000), (
            "no partial mutation on a rejected stuff"
        )
        assert after["used_volume_cbm"] == pytest.approx(100.0)


class TestStuffUnstuffConservation:
    def test_stuff_accumulates_used_capacity(self, api):
        """PRD §3.9: "A successful stuff creates the member assignment per
        §3.8, recomputes `used_weight_kg` / `used_volume_cbm` over the member
        set in `STUFFED`, `GATED_IN`, or `LOADED`, and increments the
        consolidation's `version` by one."

        Design: Difficulty/compensating_invariant/consolidation_capacity_stuff_unstuff_conservation
        """
        ctx = setup_stuffed_consolidation(
            booking_overrides={"gross_weight_kg": 6000, "volume_cbm": 60.0})
        after = _get_consolidation(api, ctx["consolidation"]["id"])
        assert after["used_weight_kg"] == pytest.approx(6000)
        assert after["used_volume_cbm"] == pytest.approx(60.0)
        assert after["version"] == ctx["consolidation"]["version"] + 1

    def test_unstuff_returns_capacity_to_baseline(self, api):
        """PRD §3.9: "The member assignment transitions to `CANCELLED`,
        `used_weight_kg` / `used_volume_cbm` are recomputed, and a `CLOSED`
        consolidation left with zero remaining members in `STUFFED`,
        `GATED_IN`, or `LOADED` automatically reopens to `OPEN`. Unstuffing
        increments the consolidation's `version` by one."

        Design: Difficulty/compensating_invariant/consolidation_capacity_stuff_unstuff_conservation
        """
        ctx = setup_stuffed_consolidation(
            booking_overrides={"gross_weight_kg": 6000, "volume_cbm": 60.0})
        consolidation = _get_consolidation(api, ctx["consolidation"]["id"])

        after = validate_success(
            api.unstuff_consolidation(consolidation["id"],
                                      ctx["booking"]["id"], BC),
            200)
        assert after["used_weight_kg"] == pytest.approx(0)
        assert after["used_volume_cbm"] == pytest.approx(0.0), (
            "the compensating unstuff returns both axes to baseline exactly"
        )
        assert after["version"] == consolidation["version"] + 1


class TestBookingCancelCascade:
    def _setup_closed_single_member(self, api):
        ctx = setup_stuffed_consolidation()
        closed = validate_success(
            api.close_consolidation(ctx["consolidation"]["id"], BC), 200)
        assert closed["status"] == "CLOSED"
        return ctx

    def test_booking_cancel_empties_and_reopens_consolidation(self, api):
        """PRD §3.7: "Either way, the cascade voids the bill of lading in
        `DRAFT`, `ISSUED`, `AMENDMENT_PENDING`, or `SURRENDERED`; voids DRAFT
        FREIGHT invoices; cancels container assignments in `STUFFED` or
        `GATED_IN` (with the LCL consolidation recompute and potential reopen
        described above); cancels any cargo insurance policy in `QUOTED` or
        `BOUND`; and recomputes the shipper's exposure variants."
        PRD §3.7: "For an LCL booking, the consolidation's `used_weight_kg`
        and `used_volume_cbm` are recomputed; if that consolidation was
        `CLOSED` and no member assignment remains in `STUFFED`, `GATED_IN`,
        or `LOADED`, it reopens from `CLOSED` to `OPEN`."

        Design: Difficulty/transitive_cascade/booking_cancel_cascade_depth3_consolidation_reopens
        """
        ctx = self._setup_closed_single_member(api)
        cancelled = validate_success(
            api.cancel_booking(ctx["booking"]["id"], BC,
                               reason="shipper cancelled order"),
            200)
        assert cancelled["status"] == "CANCELLED"

        asg = validate_success(
            api.get_container_assignment(ctx["assignment"]["id"], BC), 200)
        assert asg["status"] == "CANCELLED"

        consolidation = _get_consolidation(api, ctx["consolidation"]["id"])
        assert consolidation["used_weight_kg"] == pytest.approx(0)
        assert consolidation["used_volume_cbm"] == pytest.approx(0.0)
        assert consolidation["status"] == "OPEN", (
            "CLOSED consolidation auto-reopens when its last member is removed"
        )

    def test_booking_cancel_mints_draft_cancellation_invoice(self, api):
        """PRD §3.7: "From `QUOTED`, no cancellation fee applies. From
        `CONFIRMED` or `DOCUMENTATION_CLEARED`, cancellation auto-creates a
        `CANCELLATION` invoice in `DRAFT` with a single `CANCELLATION_FEE`
        line at a flat 75000 cents."

        Design: Difficulty/transitive_cascade/booking_cancel_cascade_depth3_consolidation_reopens
        """
        ctx = self._setup_closed_single_member(api)
        validate_success(
            api.cancel_booking(ctx["booking"]["id"], BC,
                               reason="shipper cancelled order"),
            200)

        cx = find_booking_invoice(ctx["booking"]["id"], "CANCELLATION")
        assert cx is not None, "cancellation from CONFIRMED auto-creates it"
        assert cx["status"] == "DRAFT"
        assert cx["total_cents"] == 75000
        lines = [l for l in cx["lines"] if l["line_type"] == "CANCELLATION_FEE"]
        assert len(lines) == 1 and lines[0]["amount_cents"] == 75000


class TestCommodityMix:
    def _setup_hazmat_reefer(self, api):
        ctx = setup_lcl_lane()
        reefer_tariff = validate_success(
            api.create_tariff(
                {
                    "tariff_code": "T-LCL-R",
                    "origin_port": "CNSHA",
                    "destination_port": "USLAX",
                    "commodity_type": "REEFER",
                    "mode": "LCL",
                    "rate_per_unit_cents": 12000,
                    "minimum_charge_cents": 30000,
                    "effective_from": "2026-08-01T00:00:00Z",
                    "effective_to": "2027-01-01T00:00:00Z",
                },
                _co1()),
            201)
        validate_success(api.publish_tariff(reefer_tariff["id"], _co2()), 200)
        hazmat_tariff = validate_success(
            api.create_tariff(
                {
                    "tariff_code": "T-LCL-H",
                    "origin_port": "CNSHA",
                    "destination_port": "USLAX",
                    "commodity_type": "HAZMAT",
                    "mode": "LCL",
                    "rate_per_unit_cents": 14000,
                    "minimum_charge_cents": 40000,
                    "effective_from": "2026-08-01T00:00:00Z",
                    "effective_to": "2027-01-01T00:00:00Z",
                },
                _co1()),
            201)
        validate_success(api.publish_tariff(hazmat_tariff["id"], _co2()), 200)

        shipper_headers = make_shipper_headers(ctx["shipper"]["id"])
        reefer_booking = validate_success(
            api.create_booking(
                {
                    "voyage_id": ctx["voyage"]["id"],
                    "tariff_id": reefer_tariff["id"],
                    "rate_source": "CONTRACT",
                    "mode": "LCL",
                    "commodity_type": "REEFER",
                    "gross_weight_kg": 2000,
                    "volume_cbm": 4.0,
                    "terms": "PREPAID",
                },
                shipper_headers),
            201)
        validate_success(api.confirm_booking(reefer_booking["id"], BC), 200)
        hazmat_booking = validate_success(
            api.create_booking(
                {
                    "voyage_id": ctx["voyage"]["id"],
                    "tariff_id": hazmat_tariff["id"],
                    "rate_source": "CONTRACT",
                    "mode": "LCL",
                    "commodity_type": "HAZMAT",
                    "gross_weight_kg": 1000,
                    "volume_cbm": 2.0,
                    "terms": "PREPAID",
                },
                shipper_headers),
            201)
        validate_success(api.confirm_booking(hazmat_booking["id"], BC), 200)

        con_r = create_open_consolidation(
            ctx["voyage"]["id"], cfs_location="CFS-LAX-01",
            max_weight_kg=20000, max_volume_cbm=60.0)
        con_h = create_open_consolidation(
            ctx["voyage"]["id"], cfs_location="CFS-LAX-02",
            max_weight_kg=20000, max_volume_cbm=60.0)
        con_g = create_open_consolidation(
            ctx["voyage"]["id"], cfs_location="CFS-LAX-03",
            max_weight_kg=20000, max_volume_cbm=60.0)

        stuff_booking(con_r["id"], reefer_booking["id"])
        stuff_booking(con_h["id"], hazmat_booking["id"])
        return ctx, con_r, con_h, con_g, reefer_booking, hazmat_booking

    def test_hazmat_into_reefer_consolidation_rejected_safety_first(self, api):
        """PRD §3.9: "The **commodity-mix gate** forbids stuffing a `HAZMAT`
        booking into a consolidation that already holds a `REEFER` member
        booking, and vice versa; `GENERAL` mixes with either. A violation is
        rejected with `ERR_INCOMPATIBLE_CARGO_MIX`."
        PRD §2.8: "(8) commodity compatibility inside a consolidation (HAZMAT
        and REEFER do not mix)" runs before "(10) uniqueness constraints (one
        filing per booking and type, one FREIGHT invoice per booking, one
        active bill of lading per booking, one in-flight LCL stuffing per
        booking)".

        Design: Difficulty/priority_pair_validation_conflict/stuff_hazmat_reefer_mix_and_already_stuffed_safety_beats_referential
        """
        (_ctx, con_r, _con_h, _con_g, _reefer_booking,
         hazmat_booking) = self._setup_hazmat_reefer(api)

        fresh = _get_consolidation(api, con_r["id"])
        res = api.stuff_consolidation(con_r["id"], hazmat_booking["id"],
                                      fresh["version"], BC)
        validate_error(res, ApiErrorId.ERR_INCOMPATIBLE_CARGO_MIX,
                       expected_status=422)

        after = _get_consolidation(api, con_r["id"])
        assert after["used_weight_kg"] == pytest.approx(2000), (
            "no partial side effects from the rejected stuff"
        )

    def test_already_stuffed_booking_rejected_referential_alone(self, api):
        """PRD §3.9: "A booking that already holds an LCL assignment in
        `STUFFED`, `GATED_IN`, or `LOADED` may not be stuffed again (rejected
        with `ERR_BOOKING_ALREADY_STUFFED`)."

        Design: Difficulty/priority_pair_validation_conflict/stuff_hazmat_reefer_mix_and_already_stuffed_safety_beats_referential
        """
        (_ctx, _con_r, _con_h, con_g, _reefer_booking,
         hazmat_booking) = self._setup_hazmat_reefer(api)

        # CON_G is empty: no commodity-mix violation is in play, so the
        # uniqueness (referential) gate is the one that fires.
        fresh = _get_consolidation(api, con_g["id"])
        res = api.stuff_consolidation(con_g["id"], hazmat_booking["id"],
                                      fresh["version"], BC)
        validate_error(res, ApiErrorId.ERR_BOOKING_ALREADY_STUFFED,
                       expected_status=409)


class TestConsolidationStateRules:
    def test_close_empty_consolidation_rejected(self, api):
        """PRD §3.9: "A `BookingCoordinator` closes a non-empty `OPEN`
        consolidation: the close requires at least one member assignment in
        `STUFFED` or `GATED_IN` (otherwise `ERR_CONSOLIDATION_EMPTY`) and
        transitions the consolidation from `OPEN` to `CLOSED`."

        Design: Corner/validations/close_empty_consolidation_rejected
        """
        contract = create_active_contract(contract_number="CARR-E")
        voyage = create_open_voyage(
            contract["id"], vessel_name="STAR", voyage_number="ST1",
            destination_port="USNYC", etd="2026-09-01T00:00:00Z",
            eta="2026-09-21T00:00:00Z")
        consolidation = create_open_consolidation(
            voyage["id"], cfs_location="CFS-EM", max_weight_kg=20000,
            max_volume_cbm=60.0)

        res = api.close_consolidation(consolidation["id"], BC)
        validate_error(res, ApiErrorId.ERR_CONSOLIDATION_EMPTY,
                       expected_status=422)
        after = _get_consolidation(api, consolidation["id"])
        assert after["status"] == "OPEN"

    def test_consolidation_stuffing_window_overlap_adjacency(self, api):
        """PRD §3.9: "A separate temporal rule guards stuffing-window overlap
        at a station: another consolidation at the same `cfs_location` in
        `OPEN`, `CLOSED`, or `TENDERED` whose half-open stuffing window
        intersects the new window blocks creation with
        `ERR_STUFFING_WINDOW_OVERLAP`; adjacency is allowed."

        Design: Corner/validations/consolidation_stuffing_window_overlap_adjacency
        """
        contract = create_active_contract(contract_number="CARR-S")
        voyage = create_open_voyage(
            contract["id"], vessel_name="STAR", voyage_number="ST1",
            destination_port="USNYC", etd="2026-09-01T00:00:00Z",
            eta="2026-09-21T00:00:00Z")
        create_open_consolidation(voyage["id"], cfs_location="CFS-OV",
                                  max_weight_kg=20000, max_volume_cbm=60.0)

        adjacent = validate_success(
            api.create_consolidation(
                create_consolidation_payload(
                    voyage["id"], cfs_location="CFS-OV", max_weight_kg=20000,
                    max_volume_cbm=60.0,
                    stuffing_window_start="2026-08-15T00:00:00Z",
                    stuffing_window_end="2026-08-20T00:00:00Z"),
                BC),
            201)
        assert adjacent["status"] == "OPEN", (
            "a window starting exactly at the other's end is adjacent, not overlapping"
        )

        res = api.create_consolidation(
            create_consolidation_payload(
                voyage["id"], cfs_location="CFS-OV", max_weight_kg=20000,
                max_volume_cbm=60.0,
                stuffing_window_start="2026-08-14T00:00:00Z",
                stuffing_window_end="2026-08-20T00:00:00Z"),
            BC)
        validate_error(res, ApiErrorId.ERR_STUFFING_WINDOW_OVERLAP,
                       expected_status=409)


class TestContainerAssignmentRules:
    def test_fcl_assignment_beyond_container_count_rejected(self, api):
        """PRD §3.8: "The booking must be in `CONFIRMED` or
        `DOCUMENTATION_CLEARED` (otherwise `ERR_BOOKING_INVALID_STATE`), and
        the booking may not already hold `container_count` assignments in
        `STUFFED`, `GATED_IN`, or `LOADED` (otherwise
        `ERR_CONTAINER_COUNT_EXCEEDED`)."

        Design: Corner/validations/fcl_assignment_beyond_container_count_rejected
        """
        ctx = setup_fcl_lane()
        booking = create_confirmed_booking(ctx)
        validate_success(
            api.create_container_assignment(
                create_container_assignment_payload(booking["id"]), BC),
            201)

        res = api.create_container_assignment(
            create_container_assignment_payload(
                booking["id"], container_number="MSKU9999999",
                stuffed_weight_kg=1000, stuffed_volume_cbm=5.0),
            BC)
        validate_error(res, ApiErrorId.ERR_CONTAINER_COUNT_EXCEEDED,
                       expected_status=422)

        from test_helpers import validate_paginated
        data, _meta = validate_paginated(
            api.list_container_assignments(BC, params={"limit": 100}))
        live = [a for a in data
                if a.get("booking_id") == booking["id"]
                and a.get("status") in ("STUFFED", "GATED_IN", "LOADED")]
        assert len(live) == 1, "the booking still has exactly one live assignment"

    def test_gate_out_before_discharge_rejected(self, api):
        """PRD §3.8: "A `BookingCoordinator` then gates the container out — a
        transition from `DISCHARGED` to `GATED_OUT` that stamps `gated_out_at`
        and freezes the **final** demurrage computation."
        PRD §3.8: "the assignment must be `STUFFED` (otherwise
        `ERR_ASSIGNMENT_INVALID_STATE`)" (gate-in state rule; the same
        assignment-state error covers out-of-order gate events).

        Design: Corner/state_machines/gate_out_before_discharge_rejected
        """
        ctx = setup_fcl_lane()
        booking = create_confirmed_booking(ctx)
        assignment = validate_success(
            api.create_container_assignment(
                create_container_assignment_payload(booking["id"]), BC),
            201)

        res = api.gate_out_assignment(assignment["id"], BC)
        validate_error(res, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE,
                       expected_status=409)
        after = validate_success(
            api.get_container_assignment(assignment["id"], BC), 200)
        assert after["status"] == "STUFFED"
        assert after["gated_out_at"] is None


class TestFclLoadedGate:
    def test_fcl_loaded_gate_requires_all_containers_gated_in(self, api):
        """PRD §3.8: "For an `FCL` booking, the booking transitions from
        `DOCUMENTATION_CLEARED` to `LOADED` when exactly `container_count` of
        its assignments are in `GATED_IN` or `LOADED`. For an `LCL` booking,
        the booking transitions from `DOCUMENTATION_CLEARED` to `LOADED` when
        its assignment's consolidation reaches `TENDERED`, `DEPARTED`, or
        `ARRIVED`. Either way, member assignments in `GATED_IN` transition to
        `LOADED` alongside."

        Design: Corner/state_machines/fcl_loaded_gate_requires_all_containers_gated_in
        """
        from test_helpers import (
            accept_both_filings,
            create_active_bond,
            create_draft_bl,
            issue_bl,
        )
        ctx = setup_fcl_lane()
        booking = create_confirmed_booking(
            ctx, container_count=2, gross_weight_kg=36000, volume_cbm=100.0)
        create_active_bond()
        issue_bl(create_draft_bl(booking["id"])["id"])
        accept_both_filings(booking["id"])
        assert validate_success(api.get_booking(booking["id"], OPS), 200)[
            "status"] == "DOCUMENTATION_CLEARED"

        a1 = validate_success(
            api.create_container_assignment(
                create_container_assignment_payload(
                    booking["id"], container_number="MSKU0000001"), BC),
            201)
        a2 = validate_success(
            api.create_container_assignment(
                create_container_assignment_payload(
                    booking["id"], container_number="MSKU0000002"), BC),
            201)

        validate_success(api.gate_in_assignment(a1["id"], BC), 200)
        mid = validate_success(api.get_booking(booking["id"], OPS), 200)
        assert mid["status"] == "DOCUMENTATION_CLEARED", (
            "1 of 2 containers gated in — count gate not met"
        )

        validate_success(api.gate_in_assignment(a2["id"], BC), 200)
        end = validate_success(api.get_booking(booking["id"], OPS), 200)
        assert end["status"] == "LOADED"

        a1_after = validate_success(
            api.get_container_assignment(a1["id"], BC), 200)
        assert a1_after["status"] == "LOADED", (
            "the bubble-up flips gated members to LOADED alongside"
        )


# Module-internal header helpers (kept local to avoid polluting shared state).
from test_helpers.test_users import make_compliance_headers


def _co1():
    return make_compliance_headers("co_1")


def _co2():
    return make_compliance_headers("co_2")
