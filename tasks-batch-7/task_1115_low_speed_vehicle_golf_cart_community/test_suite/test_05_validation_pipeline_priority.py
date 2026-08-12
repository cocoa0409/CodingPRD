"""Validation-pipeline priority pairs: when one request violates two stages,
the earlier stage's error wins (PRD §2.6 short-circuit pipeline).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    make_permit_holder_headers,
    create_community, create_eligible_holder, deposit,
    setup_active_registration, setup_route, setup_route_pass,
    setup_station, setup_reservation,
    COMMUNITY_ADMIN,
    ApiErrorId,
    create_charging_reservation_payload, create_route_pass_payload,
)


class TestStateBeatsFiscalOnActivate:
    """A second activate on an already-ACTIVE registration with an emptied wallet
    fails both the state stage (no ACTIVE -> ACTIVE transition) and the wallet
    stage (0 < 19000). State (stage 5) is evaluated first."""

    def test_second_activate_returns_invalid_state(self):
        """PRD §2.6: "The pipeline short-circuits at the first stage that fails:
        the error raised by that stage is the one returned, and later stages are
        never consulted."
        PRD §2.6 stage 5: "**State and concurrency** — the target resource's own
        state machine permits the requested transition from its current state, and
        any OCC version field matches the stored version. A state-machine failure
        is rejected with `ERR_INVALID_STATE` (HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_activate
        """
        ctx = setup_active_registration(
            community_name="C-PP1", fleet_program_enabled=True,
            deposit_cents=19000, insurance_overrides={"policy_number": "N-PP1"})
        holder = ctx["holder"]
        assert get_wallet(holder) == 0  # fully drained by the first activation
        hh = make_permit_holder_headers(holder["id"])
        res = api_client.activate_registration(ctx["registration"]["id"], hh)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_second_activate_never_returns_insufficient_funds(self):
        """PRD §2.6 stage 10: "**Wallet sufficiency** — the holder's
        `wallet_balance_cents` covers the amount about to be debited. Failure:
        `ERR_INSUFFICIENT_FUNDS` (HTTP 402)."
        PRD §2.6: "The pipeline short-circuits at the first stage that fails: the
        error raised by that stage is the one returned, and later stages are never
        consulted."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_activate
        """
        ctx = setup_active_registration(
            community_name="C-PP1", fleet_program_enabled=True,
            deposit_cents=19000, insurance_overrides={"policy_number": "N-PP1"})
        holder = ctx["holder"]
        hh = make_permit_holder_headers(holder["id"])
        res = api_client.activate_registration(ctx["registration"]["id"], hh)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_INVALID_STATE"
        assert res.json()["data"]["error_id"] != "ERR_INSUFFICIENT_FUNDS"


def get_wallet(holder):
    from test_helpers import get_holder
    return get_holder(holder["id"])["wallet_balance_cents"]


def _setup_pp2():
    """ACTIVE LSV registration; route A (LSV_ALLOWED) holding pass
    2026-06-01T10:00-12:00; route B (GOLF_CART_ONLY)."""
    ctx = setup_active_registration(
        community_name="C-PP2", fleet_program_enabled=True, deposit_cents=100000,
        insurance_overrides={"policy_number": "N-PP2"})
    holder = ctx["holder"]
    reg = ctx["registration"]
    route_a = setup_route(ctx["community"]["id"], name="Route A",
                          route_type="STREET", allowed_vehicle_class="LSV_ALLOWED")
    route_b = setup_route(ctx["community"]["id"], name="Route B",
                          route_type="PATH", allowed_vehicle_class="GOLF_CART_ONLY")
    setup_route_pass(route_a["id"], reg["id"], holder["id"],
                     start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T12:00:00Z")
    return ctx, route_a, route_b


class TestSafetyBeatsTemporalOnRoutePass:
    """Booking an LSV registration onto a GOLF_CART_ONLY route with a window that
    also overlaps an existing pass fails both the safety gate (stage 6) and the
    overlap gate (stage 7). Safety wins."""

    def test_lsv_on_cart_only_route_returns_route_vehicle_class(self):
        """PRD §2.6 stage 6: "**Safety gates** — driver age and license class at
        eligibility verification (`ERR_UNDERAGE_DRIVER`,
        `ERR_LICENSE_CLASS_INSUFFICIENT`), vehicle equipment minimums at
        registration creation (`ERR_EQUIPMENT_MINIMUM`), and vehicle-class
        admissibility on the route at pass booking (`ERR_ROUTE_VEHICLE_CLASS`),
        all HTTP 422."
        PRD §2.6: "The pipeline short-circuits at the first stage that fails: the
        error raised by that stage is the one returned, and later stages are never
        consulted."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_route_pass
        """
        ctx, _, route_b = _setup_pp2()
        holder = ctx["holder"]
        res = api_client.create_route_pass(
            create_route_pass_payload(route_b["id"], ctx["registration"]["id"],
                                      holder["id"],
                                      start_at="2026-06-01T11:00:00Z",
                                      end_at="2026-06-01T13:00:00Z"),
            make_permit_holder_headers(holder["id"]))
        validate_error(res, ApiErrorId.ERR_ROUTE_VEHICLE_CLASS, expected_status=422)

    def test_overlapping_window_never_surfaces_overlap_error(self):
        """PRD §2.6 stage 7: "**Temporal windows and overlaps** — renewal attempted
        outside its window or grace period (`ERR_RENEWAL_WINDOW_CLOSED`, HTTP 422),
        route-pass window collision (`ERR_ROUTE_PASS_OVERLAP`, HTTP 409),
        charging-slot collision (`ERR_CHARGING_OVERLAP`, HTTP 409), and
        dispatch-window collision (`ERR_DISPATCH_WINDOW_OVERLAP`, HTTP 409)."
        PRD §2.6: "The pipeline short-circuits at the first stage that fails: the
        error raised by that stage is the one returned, and later stages are never
        consulted."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_route_pass
        """
        ctx, _, route_b = _setup_pp2()
        holder = ctx["holder"]
        # [11:00,13:00) overlaps the existing [10:00,12:00) pass on route A; the
        # class violation is still reported first.
        res = api_client.create_route_pass(
            create_route_pass_payload(route_b["id"], ctx["registration"]["id"],
                                      holder["id"],
                                      start_at="2026-06-01T11:00:00Z",
                                      end_at="2026-06-01T13:00:00Z"),
            make_permit_holder_headers(holder["id"]))
        assert res.status_code == 422
        assert res.json()["data"]["error_id"] == "ERR_ROUTE_VEHICLE_CLASS"
        assert res.json()["data"]["error_id"] != "ERR_ROUTE_PASS_OVERLAP"


def _setup_pp3():
    """ONLINE station rate 10 c/min; holder wallet 1000 - 600 = 400 after the
    first booking 10:00-11:00 slot 0."""
    community = create_community(name="C-PP3")
    holder = create_eligible_holder(community["id"], full_name="H PP3",
                                    birth_date="2010-05-01")
    holder = deposit(holder["id"], 1000, holder["version"])
    station = setup_station(community["id"], name="S-PP3", slot_count=2,
                            rate_cents_per_min=10)
    setup_reservation(station["id"], holder["id"], slot_index=0,
                      start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z")
    return community, holder, station


class TestTemporalBeatsFiscalOnChargingBooking:
    """A charging booking whose closed interval violates the 15-minute buffer
    (stage 7) and whose holder wallet (400) cannot cover the fee 600 (stage 10).
    Temporal wins."""

    def test_buffer_violation_returns_charging_overlap(self):
        """PRD §2.6 stage 7: "**Temporal windows and overlaps** — renewal attempted
        outside its window or grace period (`ERR_RENEWAL_WINDOW_CLOSED`, HTTP 422),
        route-pass window collision (`ERR_ROUTE_PASS_OVERLAP`, HTTP 409),
        charging-slot collision (`ERR_CHARGING_OVERLAP`, HTTP 409), and
        dispatch-window collision (`ERR_DISPATCH_WINDOW_OVERLAP`, HTTP 409)."
        PRD §2.6: "The pipeline short-circuits at the first stage that fails: the
        error raised by that stage is the one returned, and later stages are never
        consulted."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_charging_booking
        """
        _, holder, station = _setup_pp3()
        res = api_client.create_charging_reservation(
            create_charging_reservation_payload(
                station["id"], holder["id"], slot_index=0,
                start_at="2026-06-01T11:00:00Z", end_at="2026-06-01T12:00:00Z"),
            make_permit_holder_headers(holder["id"]))
        # 11:00 < 11:00 + 15min buffer -> temporal failure
        validate_error(res, ApiErrorId.ERR_CHARGING_OVERLAP, expected_status=409)

    def test_buffer_violation_never_returns_insufficient_funds(self):
        """PRD §2.6 stage 10: "**Wallet sufficiency** — the holder's
        `wallet_balance_cents` covers the amount about to be debited. Failure:
        `ERR_INSUFFICIENT_FUNDS` (HTTP 402)."
        PRD §2.6: "The pipeline short-circuits at the first stage that fails: the
        error raised by that stage is the one returned, and later stages are never
        consulted."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_charging_booking
        """
        _, holder, station = _setup_pp3()
        assert get_wallet(holder) == 400  # 1000 - 600 from the first booking
        res = api_client.create_charging_reservation(
            create_charging_reservation_payload(
                station["id"], holder["id"], slot_index=0,
                start_at="2026-06-01T11:00:00Z", end_at="2026-06-01T12:00:00Z"),
            make_permit_holder_headers(holder["id"]))
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_CHARGING_OVERLAP"
        assert res.json()["data"]["error_id"] != "ERR_INSUFFICIENT_FUNDS"
