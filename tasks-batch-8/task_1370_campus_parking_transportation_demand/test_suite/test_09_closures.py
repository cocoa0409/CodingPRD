"""Lot closures: overlap semantics, conditional fields, event reservations,
and the construction displacement cascade."""
from test_helpers import (
    ApiErrorId,
    create_allocation,
    create_closure,
    create_lot,
    create_patron,
    get_allocation,
    get_closure,
    get_lot,
    get_permit,
    purchase_permit,
    setup_construction_closure,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestClosureOverlap:
    def _setup(self):
        lot = create_lot(lot_code="LE", name="Lot E", capacity_total=200)
        closure_a = create_closure(
            lot["id"], reason="EVENT", event_name="GameDay", reserved_spaces=50,
            starts_at="2026-08-10T00:00:00Z", ends_at="2026-08-20T00:00:00Z",
        )
        return lot, closure_a

    def test_adjacent_closures_coexist_half_open(self, api, admin_headers):
        """PRD §3.7: "Because windows are half-open, two closures where one's
        `ends_at` equals the other's `starts_at` do not overlap and both may
        coexist."
        PRD §2.7: "closure windows use half-open `[starts_at, ends_at)`
        semantics where adjacency (one closure's `ends_at` equal to another's
        `starts_at`) does NOT count as overlap, while permit validity windows
        use inclusive `[valid_from, valid_to]` semantics where touching dates
        DO count as overlap."

        Design: Difficulty/resource_temporal_overlap/closure_half_open_adjacency_on_lot
        """
        lot, _ = self._setup()
        resp = api.create_closure(
            {
                "lot_id": lot["id"],
                "reason": "EVENT",
                "event_name": "Orientation",
                "reserved_spaces": 30,
                "starts_at": "2026-08-20T00:00:00Z",  # exactly A's ends_at
                "ends_at": "2026-08-25T00:00:00Z",
            },
            admin_headers,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "SCHEDULED", (
            "adjacent closure must be accepted under half-open semantics"
        )

    def test_interior_intersecting_closure_rejected(self, api, admin_headers):
        """PRD §3.7: "Closures on a single lot must not overlap: a new closure
        is rejected with `ERR_CLOSURE_OVERLAP` (HTTP 409) if any other closure
        on the same lot with status `SCHEDULED` or `ACTIVE` has a
        `[starts_at, ends_at)` window that intersects the new one."

        Design: Difficulty/resource_temporal_overlap/closure_half_open_adjacency_on_lot
        """
        lot, _ = self._setup()
        ok = api.create_closure(
            {
                "lot_id": lot["id"],
                "reason": "EVENT",
                "event_name": "Orientation",
                "reserved_spaces": 30,
                "starts_at": "2026-08-20T00:00:00Z",
                "ends_at": "2026-08-25T00:00:00Z",
            },
            admin_headers,
        )
        validate_success(ok, 201)

        clash = api.create_closure(
            {
                "lot_id": lot["id"],
                "reason": "EVENT",
                "event_name": "Career Fair",
                "reserved_spaces": 10,
                "starts_at": "2026-08-19T00:00:00Z",  # interior of A's window
                "ends_at": "2026-08-21T00:00:00Z",
            },
            admin_headers,
        )
        validate_error(clash, ApiErrorId.ERR_CLOSURE_OVERLAP, 409)

        closures, meta = validate_paginated(
            api.list_closures(admin_headers, params={"lot_id": lot["id"]})
        )
        assert meta["total_count"] == 2, (
            f"only the two non-overlapping closures may exist, got {meta['total_count']}"
        )


class TestClosureShapeRules:
    def test_construction_closure_without_fallback_rejected(self, api, admin_headers):
        """PRD §3.7: "For `CONSTRUCTION` closures, `event_name` and
        `expected_attendance` must be null, `reserved_spaces` must be `0`, and
        `fallback_lot_id` is required and must differ from `lot_id` —
        violations are rejected with `ERR_FALLBACK_LOT_REQUIRED` (HTTP 400)
        when the fallback is missing or equal to the closed lot, and
        `ERR_INVALID_REQUEST` (HTTP 400) for other conditional-field
        violations."

        Design: Corner/validations/construction_closure_without_fallback_rejected
        """
        lot = create_lot(lot_code="LC", name="Lot C")
        resp = api.create_closure(
            {
                "lot_id": lot["id"],
                "reason": "CONSTRUCTION",
                "reserved_spaces": 0,
                "starts_at": "2026-08-10T00:00:00Z",
                "ends_at": "2026-08-20T00:00:00Z",
            },
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FALLBACK_LOT_REQUIRED, 400)

    def test_closure_invalid_interval_rejected(self, api, admin_headers):
        """PRD §3.7: "`ends_at` must be strictly after `starts_at`; otherwise
        `ERR_INVALID_INTERVAL` (HTTP 400)."

        Design: Corner/validations/closure_invalid_interval_rejected
        """
        lot = create_lot(lot_code="LI", name="Lot I")
        resp = api.create_closure(
            {
                "lot_id": lot["id"],
                "reason": "EVENT",
                "event_name": "Zero",
                "reserved_spaces": 5,
                "starts_at": "2026-08-10T00:00:00Z",
                "ends_at": "2026-08-10T00:00:00Z",
            },
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL, 400)


class TestEventClosureLifecycle:
    def test_event_closure_lifecycle_releases_reserved_spaces(self, api, admin_headers):
        """PRD §3.7: "At creation the closure is `SCHEDULED`. For `EVENT`
        closures, the lot's `reserved_spaces_total` immediately increases by
        `reserved_spaces` (the reservation is taken at schedule time, not
        activation time), `available_capacity` is recomputed, and allocations
        on the lot may flip toward `WAITLISTING` if their free-seat picture
        tightens."
        PRD §3.7.2: "Lifting an `ACTIVE` closure transitions it to `LIFTED`
        (terminal) and restores the lot's `posture` to `OPEN`. For `EVENT`
        closures the lot's `reserved_spaces_total` decreases by
        `reserved_spaces`."

        Design: Corner/state_machines/event_closure_lifecycle_releases_reserved_spaces
        """
        lot = create_lot(lot_code="LEV", name="Lot EV", capacity_total=100)
        closure = create_closure(
            lot["id"], reason="EVENT", event_name="GameDay", reserved_spaces=10,
            starts_at="2026-08-10T00:00:00Z", ends_at="2026-08-12T00:00:00Z",
        )
        assert closure["status"] == "SCHEDULED"

        sched = get_lot(lot["id"])
        assert sched["reserved_spaces_total"] == 10, (
            f"the reservation is taken at schedule time, got {sched['reserved_spaces_total']}"
        )
        assert sched["available_capacity"] == 90
        assert sched["posture"] == "OPEN", (
            f"posture does not change until activation, got {sched['posture']}"
        )

        activated = validate_success(api.activate_closure(closure["id"], admin_headers), 200)
        assert activated["status"] == "ACTIVE"
        active = get_lot(lot["id"])
        assert active["posture"] == "CLOSED_EVENT", (
            f"activation flips posture by reason, got {active['posture']}"
        )
        assert active["available_capacity"] == 90

        lifted = validate_success(api.lift_closure(closure["id"], admin_headers), 200)
        assert lifted["status"] == "LIFTED"
        after = get_lot(lot["id"])
        assert after["posture"] == "OPEN"
        assert after["reserved_spaces_total"] == 0
        assert after["available_capacity"] == 100, (
            f"lift releases the reservation, got {after['available_capacity']}"
        )


class TestLotAvailability:
    def test_lot_availability_aggregation(self, api):
        """PRD §3.2: "The lot's `reserved_spaces_total` is the sum of
        `reserved_spaces` across closures on the lot with status `SCHEDULED`
        or `ACTIVE`. The lot's `available_capacity` is `capacity_total` minus
        `reserved_spaces_total` minus the sum of `allocated_count` over all
        allocations on the lot."

        Design: Corner/calculations/lot_availability_aggregation
        """
        lot = create_lot(lot_code="LAV", name="Lot AV", capacity_total=100)
        patron = create_patron(full_name="A", campus_role="STUDENT",
                               residency="OFF_CAMPUS", primary_commute_mode="DRIVE_ALONE")
        allocation = create_allocation(lot["id"], eligible_roles=["STUDENT"], quota=40)
        purchase_permit(patron["id"], allocation["id"], "A222")
        create_closure(
            lot["id"], reason="EVENT", event_name="Graduation", reserved_spaces=25,
            starts_at="2026-09-01T00:00:00Z", ends_at="2026-09-02T00:00:00Z",
        )
        after = get_lot(lot["id"])
        assert after["reserved_spaces_total"] == 25
        assert after["available_capacity"] == 74, (
            f"100 - 25 reserved - 1 allocated = 74, got {after['available_capacity']}"
        )


class TestConstructionDisplacement:
    def test_construction_activation_displaces_permits(self, api, admin_headers):
        """PRD §3.7.1: "On successful activation the closure becomes `ACTIVE`
        and the lot's `posture` flips to `CLOSED_EVENT` or
        `CLOSED_CONSTRUCTION` according to reason, with the lot's `version`
        incrementing." and "The closure's `displaced_permit_count` records the
        number of permits repointed."

        Design: Difficulty/transitive_cascade/construction_closure_displacement_cascade
        """
        ctx = setup_construction_closure(src_quota=2, dst_quota=1)
        resp = api.activate_closure(ctx["closure"]["id"], admin_headers)
        closure = validate_success(resp, 200)
        assert closure["status"] == "ACTIVE"
        assert closure["displaced_permit_count"] == 1, (
            f"one ACTIVE permit must be repointed, got {closure['displaced_permit_count']}"
        )
        lot_1 = get_lot(ctx["lot_1"]["id"])
        assert lot_1["posture"] == "CLOSED_CONSTRUCTION", (
            f"construction activation sets CLOSED_CONSTRUCTION, got {lot_1['posture']}"
        )

    def test_displacement_flips_fallback_allocation_waitlisting(self, api, admin_headers):
        """PRD §3.7.1: "For `CONSTRUCTION` closures, a displacement cascade
        runs: every `ACTIVE` permit on every allocation of the closed lot is
        repointed — the permit's `allocation_id` becomes the fallback lot's
        allocation with the same `permit_code`, and the permit's
        `displaced_from_allocation_id` records the original allocation. Each
        repoint decrements the source allocation's `allocated_count` and
        increments the target's; both allocations re-evaluate
        `OPEN`/`WAITLISTING` status and increment their `version`."

        Design: Difficulty/transitive_cascade/construction_closure_displacement_cascade
        """
        ctx = setup_construction_closure(src_quota=2, dst_quota=1)
        api.activate_closure(ctx["closure"]["id"], admin_headers)

        permit = get_permit(ctx["permit"]["id"])
        assert permit["allocation_id"] == ctx["alloc_dst"]["id"], (
            "the permit must be repointed to the fallback allocation"
        )
        assert permit["displaced_from_allocation_id"] == ctx["alloc_src"]["id"], (
            "the original allocation must be recorded as displaced_from"
        )

        src = get_allocation(ctx["alloc_src"]["id"])
        dst = get_allocation(ctx["alloc_dst"]["id"])
        assert src["allocated_count"] == 0 and src["status"] == "OPEN", (
            f"source drains to 0 of 2 -> OPEN, got {src['allocated_count']}/{src['status']}"
        )
        assert dst["allocated_count"] == 1, (
            f"target absorbs the displaced permit, got {dst['allocated_count']}"
        )
        assert dst["status"] == "WAITLISTING", (
            f"1 of quota 1 hits the flip threshold, got {dst['status']}"
        )


class TestDisplacementReversal:
    def test_displaced_permits_return_on_lift(self, api, admin_headers):
        """PRD §3.7.2: "Lifting an `ACTIVE` closure transitions it to `LIFTED`
        (terminal) and restores the lot's `posture` to `OPEN`." and "For
        `CONSTRUCTION` closures every permit whose
        `displaced_from_allocation_id` points to an allocation of the closed
        lot (and which currently sits on the fallback allocation) is repointed
        back: `allocation_id` returns to the original,
        `displaced_from_allocation_id` is cleared, and allocation counts and
        statuses re-evaluate on both sides."

        Design: Corner/cross_cutting_complexity_layers/displaced_permits_return_on_lift
        """
        ctx = setup_construction_closure(src_quota=2, dst_quota=1)
        api.activate_closure(ctx["closure"]["id"], admin_headers)

        lifted = validate_success(api.lift_closure(ctx["closure"]["id"], admin_headers), 200)
        assert lifted["status"] == "LIFTED"

        permit = get_permit(ctx["permit"]["id"])
        assert permit["allocation_id"] == ctx["alloc_src"]["id"], (
            "the permit must return to its original allocation"
        )
        assert permit["displaced_from_allocation_id"] is None, (
            "displaced_from_allocation_id must be cleared on lift"
        )
        lot_1 = get_lot(ctx["lot_1"]["id"])
        assert lot_1["posture"] == "OPEN"
        src = get_allocation(ctx["alloc_src"]["id"])
        dst = get_allocation(ctx["alloc_dst"]["id"])
        assert src["allocated_count"] == 1
        assert dst["allocated_count"] == 0 and dst["status"] == "OPEN"


class TestDisplacementCapacity:
    def test_displacement_over_capacity_rejected(self, api, admin_headers):
        """PRD §3.7.1: "If any fallback allocation cannot absorb its displaced
        permits within quota, the activation is rejected with
        `ERR_DISPLACEMENT_OVER_CAPACITY` (HTTP 409)."

        Design: Corner/errors/displacement_over_capacity_rejected
        """
        ctx = setup_construction_closure(src_quota=2, dst_quota=1, fill_dst=True)
        resp = api.activate_closure(ctx["closure"]["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_DISPLACEMENT_OVER_CAPACITY, 409)

        closure = get_closure(ctx["closure"]["id"])
        assert closure["status"] == "SCHEDULED", (
            f"a rejected activation is atomic; closure stays SCHEDULED, "
            f"got {closure['status']}"
        )
        permit = get_permit(ctx["permit"]["id"])
        assert permit["allocation_id"] == ctx["alloc_src"]["id"], (
            "no partial displacement may occur"
        )
