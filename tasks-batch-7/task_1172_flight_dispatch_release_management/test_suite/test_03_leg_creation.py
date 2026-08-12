"""Leg creation: safety checks, capacity boundary, dispatcher auto-selection,
workload counters, and the system-field write barrier (PRD §3.1, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_aircraft_payload,
    create_captain_payload,
    create_dispatcher_payload,
    create_leg_payload,
    create_station_payload,
    make_dispatcher_headers,
    setup_reference_data,
    add_leg,
    add_second_leg,
    set_clock,
    validate_error,
    validate_success,
)

SUP = TEST_USERS["supervisor_headers"]


class TestLegCreateSafety:
    def test_captain_not_qualified_rejected(self, api):
        """PRD §3.2: "The named captain's `qualified_type_codes` must contain
        the aircraft's `type_code`, failing which the create is rejected with
        `ERR_CAPTAIN_NOT_QUALIFIED`."

        Design: Corner/validations/captain_not_qualified_rejected
        """
        ctx = setup_reference_data(with_alternate=False)
        c2 = validate_success(
            api.create_captain(
                create_captain_payload(name="Cole Two", license_no="C002",
                                       qualified_type_codes=["B737"]),
                SUP,
            ),
            201,
        )
        res = api.create_leg(
            create_leg_payload(
                ctx["dep_station"]["id"], ctx["arr_station"]["id"],
                ctx["aircraft"]["id"], c2["id"],
                dispatcher_id=ctx["dispatcher"]["id"],
            ),
            ctx["d_headers"],
        )
        validate_error(res, ApiErrorId.ERR_CAPTAIN_NOT_QUALIFIED.value)

    def test_dual_role_assignment_rejected(self, api):
        """PRD §3.2: "And the captain's `license_no` must differ from the
        dispatcher's `license_no`; equality means one person would hold both
        joint-responsibility slots and is rejected with
        `ERR_DUAL_ROLE_ASSIGNMENT`."

        Design: Corner/validations/dual_role_assignment_rejected
        """
        ctx = setup_reference_data(with_alternate=False)
        same_dispatcher = validate_success(
            api.create_dispatcher(
                create_dispatcher_payload(name="Sam Person", license_no="SAME-1"), SUP
            ),
            201,
        )
        same_captain = validate_success(
            api.create_captain(
                create_captain_payload(name="Sam Person", license_no="SAME-1"), SUP
            ),
            201,
        )
        res = api.create_leg(
            create_leg_payload(
                ctx["dep_station"]["id"], ctx["arr_station"]["id"],
                ctx["aircraft"]["id"], same_captain["id"],
                dispatcher_id=same_dispatcher["id"],
            ),
            make_dispatcher_headers(same_dispatcher["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DUAL_ROLE_ASSIGNMENT.value)

    def test_leg_create_rejects_unknown_system_field(self, api):
        """PRD §2.9: "A malformed body — a missing required field, a wrong-typed
        value, an unknown field, an invalid enum member, or a non-positive
        quantity — is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any
        other check runs."

        Design: Corner/entities/leg_create_rejects_unknown_system_field
        """
        ctx = setup_reference_data(with_alternate=False)
        payload = create_leg_payload(
            ctx["dep_station"]["id"], ctx["arr_station"]["id"],
            ctx["aircraft"]["id"], ctx["captain"]["id"],
            dispatcher_id=ctx["dispatcher"]["id"],
        )
        payload["ops_status"] = "DEPARTED"  # system-owned, not a create input
        res = api.create_leg(payload, ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value,
                       expected_status=400)


class TestDispatcherCapacityBoundary:
    def test_dispatcher_at_capacity_boundary_accepts_first_leg(self, api):
        """PRD §3.2: "if that dispatcher's `workload_leg_count` has already
        reached their `max_active_legs` — equality included, so at the limit the
        dispatcher is full — the assignment is rejected with
        `ERR_DISPATCHER_OVERLOADED`." A count of exactly max-1 accepts the leg
        that brings the count to the limit.

        Design: Difficulty/boundary_precision_check/dispatcher_workload_capacity_boundary
        """
        ctx = setup_reference_data(
            with_alternate=False,
            dispatcher_overrides={"name": "Dana Three", "license_no": "D003",
                                  "max_active_legs": 1},
        )
        leg = add_leg(ctx, flight_no="FD220", distance_nm=400,
                      sched_dep_utc="2026-05-01T10:00:00Z",
                      sched_arr_utc="2026-05-01T11:00:00Z")
        assert leg["ops_status"] == "SCHEDULED"
        dispatcher = validate_success(
            api.get_dispatcher(ctx["dispatcher"]["id"], SUP), 200
        )
        assert dispatcher["workload_leg_count"] == 1

    def test_dispatcher_at_capacity_rejects_next_leg(self, api):
        """PRD §3.2: "if that dispatcher's `workload_leg_count` has already
        reached their `max_active_legs` — equality included, so at the limit the
        dispatcher is full — the assignment is rejected with
        `ERR_DISPATCHER_OVERLOADED`."

        Design: Difficulty/boundary_precision_check/dispatcher_workload_capacity_boundary
        """
        ctx = setup_reference_data(
            with_alternate=False,
            dispatcher_overrides={"name": "Dana Three", "license_no": "D003",
                                  "max_active_legs": 1},
        )
        add_leg(ctx, flight_no="FD220", distance_nm=400,
                sched_dep_utc="2026-05-01T10:00:00Z",
                sched_arr_utc="2026-05-01T11:00:00Z")
        res = api.create_leg(
            create_leg_payload(
                ctx["dep_station"]["id"], ctx["arr_station"]["id"],
                ctx["aircraft"]["id"], ctx["captain"]["id"],
                flight_no="FD221", distance_nm=400,
                sched_dep_utc="2026-05-01T12:00:00Z",
                sched_arr_utc="2026-05-01T13:00:00Z",
                dispatcher_id=ctx["dispatcher"]["id"],
            ),
            ctx["d_headers"],
        )
        validate_error(res, ApiErrorId.ERR_DISPATCHER_OVERLOADED.value)


class TestWorkloadVariants:
    def test_workload_flat_count_counts_both_legs(self, api):
        """PRD §3.1: "Two computed counters are exposed on read:
        `workload_leg_count`, the flat count of the dispatcher's legs whose
        `ops_status` is `SCHEDULED` or `DEPARTED`, and `weighted_load_score`, a
        departure-weighted sum over the same leg set in which a leg departing
        within two hours of the current clock contributes 3, a leg departing
        more than two and at most six hours out contributes 2, and any later leg
        contributes 1."

        Design: Difficulty/dual_variant_calc/dispatcher_workload_flat_vs_departure_weighted
        """
        ctx = setup_reference_data(with_alternate=False)
        add_leg(ctx, flight_no="FD300", distance_nm=400,
                sched_dep_utc="2026-05-01T01:00:00Z",
                sched_arr_utc="2026-05-01T02:00:00Z")
        add_second_leg(ctx, flight_no="FD301", distance_nm=400,
                       sched_dep_utc="2026-05-01T10:00:00Z",
                       sched_arr_utc="2026-05-01T11:00:00Z")
        # Startup clock is exactly 2026-05-01T00:00:00Z (PRD §2.4).
        dispatcher = validate_success(
            api.get_dispatcher(ctx["dispatcher"]["id"], SUP), 200
        )
        assert dispatcher["workload_leg_count"] == 2

    def test_workload_weighted_score_differs_from_flat(self, api):
        """PRD §3.1: "The two variants are deliberately distinct: a dispatcher
        holding one leg one hour from departure and another ten hours out shows
        a flat `workload_leg_count` of 2 but a `weighted_load_score` of 4."

        Design: Difficulty/dual_variant_calc/dispatcher_workload_flat_vs_departure_weighted
        """
        ctx = setup_reference_data(with_alternate=False)
        add_leg(ctx, flight_no="FD300", distance_nm=400,
                sched_dep_utc="2026-05-01T01:00:00Z",
                sched_arr_utc="2026-05-01T02:00:00Z")
        add_second_leg(ctx, flight_no="FD301", distance_nm=400,
                       sched_dep_utc="2026-05-01T10:00:00Z",
                       sched_arr_utc="2026-05-01T11:00:00Z")
        dispatcher = validate_success(
            api.get_dispatcher(ctx["dispatcher"]["id"], SUP), 200
        )
        assert dispatcher["weighted_load_score"] == 4
        assert dispatcher["workload_leg_count"] != dispatcher["weighted_load_score"]


class TestAssignmentLedgerInvariant:
    def test_leg_creates_increment_assignment_ledger(self, api):
        """PRD §3.1: "`workload_leg_count`, the flat count of the dispatcher's
        legs whose `ops_status` is `SCHEDULED` or `DEPARTED`" — each created leg
        joins the set, so two creates move the counter from baseline 0 to 2.

        Design: Difficulty/compensating_invariant/global_leg_assignment_ledger_conserved
        """
        ctx = setup_reference_data(
            with_alternate=False,
            dispatcher_overrides={"name": "Dana Seven", "license_no": "D007"},
        )
        add_leg(ctx, flight_no="FD250", distance_nm=400,
                sched_dep_utc="2026-05-01T10:00:00Z",
                sched_arr_utc="2026-05-01T11:00:00Z")
        add_second_leg(ctx, flight_no="FD251", distance_nm=400,
                       sched_dep_utc="2026-05-01T12:00:00Z",
                       sched_arr_utc="2026-05-01T13:00:00Z")
        dispatcher = validate_success(
            api.get_dispatcher(ctx["dispatcher"]["id"], SUP), 200
        )
        assert dispatcher["workload_leg_count"] == 2

    def test_leg_cancel_returns_counter_to_baseline(self, api):
        """PRD §3.8: "**Cancellation** moves a `SCHEDULED` leg to `CANCELLED` at
        the assigned dispatcher's hand, taking a `reason_code`. Cancellation
        cancels any non-terminal release on the leg, drops the leg from the
        dispatcher's workload counters, and writes a `CANCEL_DECISION` record."

        Design: Difficulty/compensating_invariant/global_leg_assignment_ledger_conserved
        """
        ctx = setup_reference_data(
            with_alternate=False,
            dispatcher_overrides={"name": "Dana Seven", "license_no": "D007"},
        )
        add_leg(ctx, flight_no="FD250", distance_nm=400,
                sched_dep_utc="2026-05-01T10:00:00Z",
                sched_arr_utc="2026-05-01T11:00:00Z")
        leg2 = add_second_leg(ctx, flight_no="FD251", distance_nm=400,
                              sched_dep_utc="2026-05-01T12:00:00Z",
                              sched_arr_utc="2026-05-01T13:00:00Z")
        cancelled = validate_success(
            api.cancel_leg(leg2["id"], {"reason_code": "OPS"}, ctx["d_headers"]), 200
        )
        assert cancelled["ops_status"] == "CANCELLED"
        dispatcher = validate_success(
            api.get_dispatcher(ctx["dispatcher"]["id"], SUP), 200
        )
        assert dispatcher["workload_leg_count"] == 1, (
            "only the still-SCHEDULED leg remains in the counter"
        )


class TestDispatcherAutoSelect:
    def test_selector_dispatcher_auto_assign_tie_break(self, api):
        """PRD §3.2: "Eligible dispatchers are ranked by `workload_leg_count`
        ascending, with ties broken by `weighted_load_score` ascending and then
        by dispatcher `created_at` ascending, never by id."

        Design: Corner/complexity_layers/selector_dispatcher_auto_assign_tie_break
        """
        from test_helpers import create_desk_payload, create_desk_shift_payload

        ctx = setup_reference_data(with_alternate=False,
                                   dispatcher_overrides={"name": "Dana A",
                                                         "license_no": "D00A"})
        da = ctx["dispatcher"]
        db = validate_success(
            api.create_dispatcher(
                create_dispatcher_payload(name="Dana B", license_no="D00B"), SUP
            ),
            201,
        )
        # D_A: one leg departing +1h from the 08:00 clock (tier 3).
        add_leg(ctx, flight_no="FD850", distance_nm=400,
                sched_dep_utc="2026-05-01T09:00:00Z",
                sched_arr_utc="2026-05-01T10:00:00Z")
        # D_B: one leg departing +10h (tier 1).
        leg_b = validate_success(
            api.create_leg(
                create_leg_payload(
                    ctx["dep_station"]["id"], ctx["arr_station"]["id"],
                    ctx["aircraft"]["id"], ctx["captain"]["id"],
                    flight_no="FD851", distance_nm=400,
                    sched_dep_utc="2026-05-01T18:00:00Z",
                    sched_arr_utc="2026-05-01T19:00:00Z",
                    dispatcher_id=db["id"],
                ),
                make_dispatcher_headers(db["id"]),
            ),
            201,
        )
        assert leg_b["dispatcher_id"] == db["id"]
        kw = validate_success(
            api.create_desk(create_desk_payload(code="KW", max_dispatchers=2), SUP),
            201,
        )
        for d in (da, db):
            validate_success(
                api.create_desk_shift(
                    create_desk_shift_payload(d["id"], desk_id=kw["id"]), SUP
                ),
                201,
            )
        set_clock(ctx, "2026-05-01T08:00:00Z")

        payload = create_leg_payload(
            ctx["dep_station"]["id"], ctx["arr_station"]["id"],
            ctx["aircraft"]["id"], ctx["captain"]["id"],
            flight_no="FD852", distance_nm=400,
            sched_dep_utc="2026-05-01T12:00:00Z",
            sched_arr_utc="2026-05-01T13:00:00Z",
        )
        leg = validate_success(api.create_leg(payload, ctx["d_headers"]), 201)
        assert leg["dispatcher_id"] == db["id"], (
            "flat tie 1 == 1 must break on weighted_load_score: D_B (1) beats "
            f"D_A (3); got dispatcher_id {leg['dispatcher_id']}"
        )
