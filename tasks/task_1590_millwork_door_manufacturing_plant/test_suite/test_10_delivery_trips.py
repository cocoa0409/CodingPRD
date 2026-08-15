"""Delivery trips: fill accounting, capacity boundary, assignment gates, lifecycle."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    validate_success, validate_error,
    make_project, make_order, make_opening, make_trip, get_trip, get_opening,
    assign, unassign, set_trip_status, stage_opening,
    setup_openings_finished, setup_openings_staged, H,
)

PM_H = TEST_USERS["plant_manager_headers"]
SC_H = TEST_USERS["shipping_coordinator_headers"]
ANY_H = TEST_USERS["any_headers"]

_UNRATED = dict(species="PAINT_GRADE", profile_code="PR-1", finish_system="PAINT",
                sheen_target="MATTE", hardware_prep_mode="INSTALLER_PREP",
                fire_rating_required="NONE")


def _staged_ctx(contract_code, order_code, openings, machine_code, booth_code, **kwargs):
    return setup_openings_staged(
        contract_code=contract_code, order_code=order_code, openings=openings,
        machine_code=machine_code, machine_species=["PAINT_GRADE"],
        booth_code=booth_code, measured_gu=15, **_UNRATED, **kwargs,
    )


class TestProjectedVsRealizedFill:
    _OPENINGS = (
        {"opening_no": "A1", "leaf_count": 3, "fire_rating": "NONE",
         "required_on_site_date": "2026-10-01"},
        {"opening_no": "A2", "leaf_count": 2, "fire_rating": "NONE",
         "required_on_site_date": "2026-10-01"},
        {"opening_no": "A3", "leaf_count": 1, "fire_rating": "NONE",
         "required_on_site_date": "2026-10-01"},
    )

    def _setup(self, contract_code="C-2001"):
        """Three STAGED openings (3/2/1 leaves); trip capacity 10 with the first
        two assigned (5 committed), the third left STAGED and UNSCHEDULED."""
        ctx = _staged_ctx(contract_code, "O-2001", self._OPENINGS, "M-1", "B-1")
        trip = make_trip(ctx["project"]["id"], trip_code="T-1", truck_capacity_leaves=10,
                         departure_date="2026-09-28", site_arrival_date="2026-09-30")
        assign(trip["id"], ctx["openings"][0]["id"])
        assign(trip["id"], ctx["openings"][1]["id"])
        return ctx, trip

    def test_projected_fill_includes_staged_unscheduled_openings(self, api):
        """PRD §3.7: "The forward-looking `projected_fill_pct` divides the
        committed leaves plus the leaves of every opening of the trip's project
        that is `STAGED` but still `UNSCHEDULED` by `truck_capacity_leaves`,
        multiplies by one hundred, and rounds half-up to one decimal".

        Design: Difficulty/dual_variant_calc/trip_fill_projected_vs_realized_divergence
        """
        ctx, trip = self._setup()
        fetched = get_trip(trip["id"])
        assert fetched["leaves_committed"] == 5
        # (5 committed + 1 staged-unscheduled) / 10 * 100 = 60.0
        assert fetched["projected_fill_pct"] == 60.0, (
            f"projected fill must count prospective load, got {fetched['projected_fill_pct']}"
        )

    def test_realized_fill_frozen_at_departure_diverges(self, api):
        """PRD §3.7: "The settled `realized_fill_pct` counts only the committed
        leaves actually on the truck under the same formula and precision, is
        computed and frozen at departure, and is null until the trip departs.
        Whenever staged-but-unscheduled openings exist in the project, the two
        figures diverge for identical trip data by construction."

        Design: Difficulty/dual_variant_calc/trip_fill_projected_vs_realized_divergence
        """
        ctx, trip = self._setup("C-2001B")
        projected = get_trip(trip["id"])["projected_fill_pct"]

        departed = set_trip_status(trip["id"], "DEPARTED")
        assert departed["realized_fill_pct"] == 50.0, (
            f"realized fill counts only committed leaves (5/10), got "
            f"{departed['realized_fill_pct']}"
        )
        assert departed["realized_fill_pct"] != projected
        # Departure cascades only the assigned openings along the ship axis.
        assert get_opening(ctx["openings"][0]["id"])["ship_status"] == "SHIPPED"
        assert get_opening(ctx["openings"][1]["id"])["ship_status"] == "SHIPPED"
        assert get_opening(ctx["openings"][2]["id"])["ship_status"] == "UNSCHEDULED"


class TestTruckCapacityBoundary:
    _OPENINGS = (
        {"opening_no": "T1", "leaf_count": 3, "fire_rating": "NONE",
         "required_on_site_date": "2026-10-01"},
        {"opening_no": "T2", "leaf_count": 2, "fire_rating": "NONE",
         "required_on_site_date": "2026-10-01"},
        {"opening_no": "T3", "leaf_count": 1, "fire_rating": "NONE",
         "required_on_site_date": "2026-10-01"},
    )

    def _setup(self, contract_code):
        ctx = _staged_ctx(contract_code, "O-7002", self._OPENINGS, "M-T", "B-T")
        trip = make_trip(ctx["project"]["id"], trip_code="T-CAP", truck_capacity_leaves=5,
                         departure_date="2026-09-29", site_arrival_date="2026-10-01")
        return ctx, trip

    def test_assign_at_exact_capacity_succeeds(self, api):
        """PRD §3.7: "the opening's `leaf_count` added to the trip's
        `leaves_committed` must not exceed `truck_capacity_leaves` — an exact
        fit is permitted"."

        Design: Difficulty/boundary_precision_check/truck_leaf_capacity_exact_boundary
        """
        ctx, trip = self._setup("C-7002")
        t1 = assign(trip["id"], ctx["openings"][0]["id"])
        assert t1["leaves_committed"] == 3
        # Boundary: 3 + 2 == capacity 5 succeeds.
        t2 = assign(trip["id"], ctx["openings"][1]["id"])
        assert t2["leaves_committed"] == 5, "exact fit is permitted"
        assert get_opening(ctx["openings"][1]["id"])["ship_status"] == "SCHEDULED"

    def test_assign_beyond_capacity_rejected(self, api):
        """PRD §3.7: "the opening's `leaf_count` added to the trip's
        `leaves_committed` must not exceed `truck_capacity_leaves` — an exact
        fit is permitted, an overflow fails with `ERR_TRUCK_CAPACITY_EXCEEDED`
        (HTTP 402)."

        Design: Difficulty/boundary_precision_check/truck_leaf_capacity_exact_boundary
        """
        ctx, trip = self._setup("C-7002B")
        assign(trip["id"], ctx["openings"][0]["id"])
        assign(trip["id"], ctx["openings"][1]["id"])

        # 5 + 1 > 5 fails; the opening stays UNSCHEDULED.
        resp = api.assign_opening(trip["id"], {"opening_id": ctx["openings"][2]["id"]}, SC_H)
        validate_error(resp, ApiErrorId.ERR_TRUCK_CAPACITY_EXCEEDED, 402)
        assert get_opening(ctx["openings"][2]["id"])["ship_status"] == "UNSCHEDULED"


class TestLeafCommitmentSymmetry:
    def _setup(self, contract_code):
        ctx = _staged_ctx(
            contract_code, "O-9102",
            ({"opening_no": "U1", "leaf_count": 2, "fire_rating": "NONE",
              "required_on_site_date": "2026-10-05"},),
            "M-U", "B-U",
        )
        trip = make_trip(ctx["project"]["id"], trip_code="T-SYM", truck_capacity_leaves=6,
                         departure_date="2026-10-02", site_arrival_date="2026-10-04")
        return ctx, trip

    def test_unassign_restores_commitment(self, api):
        """PRD §3.7: "It returns the opening to `UNSCHEDULED`, clears
        `assigned_trip_id`, subtracts the opening's leaves from
        `leaves_committed`, and increments the trip's `version`. The pair is
        conservative: an assign followed by the matching unassign leaves the
        trip's committed leaves, the opening's shipping axis, and the opening's
        trip reference exactly as they were before."

        Design: Difficulty/compensating_invariant/trip_leaf_commitment_symmetry
        """
        ctx, trip = self._setup("C-9102")
        op = ctx["openings"][0]["id"]

        after_assign = assign(trip["id"], op)
        assert after_assign["leaves_committed"] == 2
        assert get_opening(op)["ship_status"] == "SCHEDULED"

        after_unassign = unassign(trip["id"], op)
        assert after_unassign["leaves_committed"] == 0, "unassign compensates assign exactly"
        opening = get_opening(op)
        assert opening["ship_status"] == "UNSCHEDULED"
        assert opening["assigned_trip_id"] is None

    def test_reassign_after_unassign_recommits(self, api):
        """PRD §3.7: "The pair is conservative: an assign followed by the
        matching unassign leaves the trip's committed leaves, the opening's
        shipping axis, and the opening's trip reference exactly as they were
        before."

        Design: Difficulty/compensating_invariant/trip_leaf_commitment_symmetry
        """
        ctx, trip = self._setup("C-9102B")
        op = ctx["openings"][0]["id"]
        assign(trip["id"], op)
        unassign(trip["id"], op)

        # The pair left no drift: a fresh assign commits the same leaves again.
        reassigned = assign(trip["id"], op)
        assert reassigned["leaves_committed"] == 2
        opening = get_opening(op)
        assert opening["ship_status"] == "SCHEDULED"
        assert opening["assigned_trip_id"] == trip["id"]


class TestAssignRequiresStaged:
    def test_finished_but_unstaged_opening_rejected_then_succeeds(self, api):
        """PRD §3.7: "The opening's fabrication axis must be `STAGED`
        (`ERR_OPENING_NOT_STAGED`)". and "A successful assignment moves the
        opening's shipping axis from `UNSCHEDULED` to `SCHEDULED`, sets its
        `assigned_trip_id`, adds its leaves to `leaves_committed`".

        Design: Difficulty/cross_entity_state_dependency/trip_assign_requires_staged_opening
        """
        ctx = setup_openings_finished(
            contract_code="C-8002", order_code="O-8002", measured_gu=15,
            openings=({"opening_no": "X1", "leaf_count": 1, "fire_rating": "NONE",
                       "required_on_site_date": "2026-10-05"},),
            machine_code="M-S", machine_species=["PAINT_GRADE"], booth_code="B-S",
            cure_start=8, cure_end=12, estimated_minutes=45, slot_start=6, slot_end=8,
            **_UNRATED,
        )
        opening = ctx["openings"][0]
        assert opening["fab_status"] == "FINISHED"
        trip = make_trip(ctx["project"]["id"], trip_code="T-S", truck_capacity_leaves=4,
                         departure_date="2026-10-02", site_arrival_date="2026-10-04")

        # FINISHED is not STAGED: assign is rejected.
        resp = api.assign_opening(trip["id"], {"opening_id": opening["id"]}, SC_H)
        validate_error(resp, ApiErrorId.ERR_OPENING_NOT_STAGED, 409)

        # The same request succeeds after staging.
        stage_opening(opening["id"])
        assigned = assign(trip["id"], opening["id"])
        assert assigned["leaves_committed"] == 1
        assert get_opening(opening["id"])["ship_status"] == "SCHEDULED"

    def test_queued_opening_rejected(self, api):
        """PRD §3.7: "The opening's fabrication axis must be `STAGED`
        (`ERR_OPENING_NOT_STAGED`)"."

        Design: Difficulty/cross_entity_state_dependency/trip_assign_requires_staged_opening
        """
        project = make_project(name="Stage Proj 2", site_address="4 Yard Rd", contract_code="C-8002B")
        order = make_order(project["id"], order_code="O-8002Q", **_UNRATED)
        opening = make_opening(order["id"], opening_no="X1", required_on_site_date="2026-10-05")
        assert opening["fab_status"] == "QUEUED"
        trip = make_trip(project["id"], trip_code="T-S2", truck_capacity_leaves=4,
                         departure_date="2026-10-02", site_arrival_date="2026-10-04")

        resp = api.assign_opening(trip["id"], {"opening_id": opening["id"]}, SC_H)
        validate_error(resp, ApiErrorId.ERR_OPENING_NOT_STAGED, 409)


class TestAssignmentGateSweep:
    def test_trip_assignment_gate_sweep(self, api):
        """PRD §3.7: "its shipping axis must be `UNSCHEDULED`
        (`ERR_OPENING_ALREADY_SCHEDULED`); the opening's order must belong to
        the same project the trip serves (`ERR_TRIP_PROJECT_MISMATCH`); the
        trip's `site_arrival_date` must not fall after the opening's
        `required_on_site_date` (`ERR_DELIVERY_WINDOW_MISSED`)". PRD §3.7:
        "requiring that the opening's `assigned_trip_id` names this trip
        (`ERR_OPENING_NOT_ON_TRIP`)."

        Design: Corner/errors/trip_assignment_gate_sweep
        """
        proj_a = make_project(name="PA", site_address="1 Alpha Way", contract_code="CR-3A")
        a = setup_openings_staged(
            project=proj_a, contract_code="CR-3A", order_code="O-GA", openings=(
                {"opening_no": "GA1", "leaf_count": 1, "fire_rating": "NONE",
                 "required_on_site_date": "2026-10-05"},
                {"opening_no": "GA2", "leaf_count": 1, "fire_rating": "NONE",
                 "required_on_site_date": "2026-10-05"},
            ),
            machine_code="M-GA", machine_species=["PAINT_GRADE"], booth_code="B-GA",
            measured_gu=15, slot_start=6, slot_end=8, estimated_minutes=30, **_UNRATED,
        )
        ga1, ga2 = a["openings"][0]["id"], a["openings"][1]["id"]

        proj_b = make_project(name="PB", site_address="2 Beta Way", contract_code="CR-3B")
        b = setup_openings_staged(
            project=proj_b, contract_code="CR-3B", order_code="O-GB", openings=(
                {"opening_no": "GB1", "leaf_count": 1, "fire_rating": "NONE",
                 "required_on_site_date": "2026-10-05"},
            ),
            machine_code="M-GB", machine_species=["PAINT_GRADE"], booth_code="B-GB",
            measured_gu=15, slot_start=6, slot_end=8, estimated_minutes=30,
            cure_start=13, cure_end=17, **_UNRATED,
        )
        gb1 = b["openings"][0]["id"]

        trip_a = make_trip(proj_a["id"], trip_code="TA", truck_capacity_leaves=5,
                           departure_date="2026-10-02", site_arrival_date="2026-10-04")
        trip_late = make_trip(proj_a["id"], trip_code="TLATE", truck_capacity_leaves=5,
                              departure_date="2026-10-04", site_arrival_date="2026-10-06")
        trip_eq = make_trip(proj_a["id"], trip_code="TEQ", truck_capacity_leaves=5,
                            departure_date="2026-10-03", site_arrival_date="2026-10-05")

        assign(trip_a["id"], ga1)
        # Double-assign: shipping axis no longer UNSCHEDULED.
        resp = api.assign_opening(trip_a["id"], {"opening_id": ga1}, SC_H)
        validate_error(resp, ApiErrorId.ERR_OPENING_ALREADY_SCHEDULED, 409)
        # Cross-project opening.
        resp = api.assign_opening(trip_a["id"], {"opening_id": gb1}, SC_H)
        validate_error(resp, ApiErrorId.ERR_TRIP_PROJECT_MISMATCH, 409)
        # Arrival one day past the required-on-site date.
        resp = api.assign_opening(trip_late["id"], {"opening_id": ga2}, SC_H)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_MISSED, 409)
        # Arrival exactly on the required date is allowed.
        ok = assign(trip_eq["id"], ga2)
        assert ok["leaves_committed"] == 1
        # Unassign from a trip the opening is not on.
        resp = api.unassign_opening(trip_a["id"], {"opening_id": ga2}, SC_H)
        validate_error(resp, ApiErrorId.ERR_OPENING_NOT_ON_TRIP, 409)


class TestTripLifecycleGates:
    def test_trip_depart_gates(self, api):
        """PRD §3.7: "Departure moves the trip from `PLANNED` to `DEPARTED` (a
        `ShippingCoordinator` action) under two gates: at least one opening
        must be assigned (`ERR_NO_OPENINGS_ASSIGNED`)". and "any other trip
        pair — such as `PLANNED` straight to `DELIVERED` — fails with
        `ERR_INVALID_TRIP_STATUS_TRANSITION`."

        Design: Corner/endpoints/trip_depart_gates
        """
        project = make_project(name="P", contract_code="CE-3")
        trip = make_trip(project["id"], trip_code="T-E3", truck_capacity_leaves=4,
                         departure_date="2026-10-02", site_arrival_date="2026-10-03")

        # PLANNED -> DELIVERED is an undeclared pair.
        resp = api.set_delivery_trip_status(trip["id"], {"target_status": "DELIVERED"}, SC_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRIP_STATUS_TRANSITION, 409)

        # An empty trip cannot depart.
        resp = api.set_delivery_trip_status(trip["id"], {"target_status": "DEPARTED"}, SC_H)
        validate_error(resp, ApiErrorId.ERR_NO_OPENINGS_ASSIGNED, 409)

        assert get_trip(trip["id"])["status"] == "PLANNED"

    def test_trip_cancel_releases_openings(self, api):
        """PRD §3.7: "Cancelling a `PLANNED` trip returns its assigned openings
        to `UNSCHEDULED`, clears their trip references, and zeroes
        `leaves_committed`. `CLOSED` and `CANCELLED` are terminal, and any
        other trip pair — such as `PLANNED` straight to `DELIVERED` — fails
        with `ERR_INVALID_TRIP_STATUS_TRANSITION`."

        Design: Corner/state_machines/trip_cancel_releases_openings
        """
        ctx = _staged_ctx(
            "CS-12", "O-C12",
            ({"opening_no": "C1", "leaf_count": 2, "fire_rating": "NONE",
              "required_on_site_date": "2026-10-05"},),
            "M-C12", "B-C12",
        )
        op = ctx["openings"][0]["id"]
        trip = make_trip(ctx["project"]["id"], trip_code="TC", truck_capacity_leaves=6,
                         departure_date="2026-10-02", site_arrival_date="2026-10-04")
        assign(trip["id"], op)

        cancelled = set_trip_status(trip["id"], "CANCELLED")
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["leaves_committed"] == 0

        opening = get_opening(op)
        assert opening["ship_status"] == "UNSCHEDULED"
        assert opening["assigned_trip_id"] is None

        # The cancelled trip is terminally locked.
        resp = api.assign_opening(trip["id"], {"opening_id": op}, SC_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRIP_STATUS_TRANSITION, 409)


class TestRealizedFillNullability:
    def test_realized_fill_null_until_departed(self, api):
        """PRD §3.7: "The settled `realized_fill_pct` counts only the committed
        leaves actually on the truck under the same formula and precision, is
        computed and frozen at departure, and is null until the trip departs."
        PRD §3.7: "A new trip is `PLANNED` with `leaves_committed` at zero".

        Design: Corner/calculations/realized_fill_null_until_departed
        """
        project = make_project(name="P", contract_code="CT-4")
        trip = validate_success(api.create_delivery_trip(
            {"project_id": project["id"], "trip_code": "T-N", "truck_capacity_leaves": 8,
             "departure_date": "2026-10-02", "site_arrival_date": "2026-10-03"}, PM_H,
        ), 201)
        assert trip["realized_fill_pct"] is None, "realized fill is null until departure"
        assert trip["projected_fill_pct"] == 0.0, "empty trip projects 0.0"
        assert trip["leaves_committed"] == 0
