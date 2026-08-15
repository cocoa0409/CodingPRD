"""Park areas, effective capacity under peak windows, and maintenance closure
windows."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    check_in_dog,
    create_area_payload,
    create_closure_payload,
    create_park_area,
    make_member_headers,
    register_member,
    run_nightly,
    schedule_closure,
    set_clock,
    setup_active_member,
    setup_area_with_members,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["park_admin_headers"]


class TestAreaCreation:
    def test_create_area_peak_capacity_above_capacity_rejected(self, api):
        """PRD §3.4: "Creating an area takes a `name`, a
        `size_class_restriction` of `SMALL` or `LARGE` (only matching dogs and
        guest passes are ever admitted), a standard `capacity` — the maximum
        number of concurrent `OPEN` visits, strictly greater than zero — a
        `peak_capacity` for busy windows that must not exceed `capacity`, and
        optionally `peak_windows`"

        Design: Corner/entities/create_area_peak_capacity_above_capacity_rejected
        """
        resp = api.create_area(
            create_area_payload(name="Bad Area", size_class_restriction="LARGE",
                                capacity=2, peak_capacity=5),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_area_computed_defaults(self, api):
        """PRD §3.4: "A freshly created area reports `current_occupancy` 0 and
        an `effective_capacity` equal to its `capacity`."

        Design: Corner/entities/create_area_computed_defaults
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Main", size_class_restriction="LARGE",
                                capacity=4, peak_capacity=2)
        assert area["current_occupancy"] == 0
        assert area["effective_capacity"] == 4, (
            "no closure and outside any peak window, so effective == capacity"
        )

    def test_member_cannot_create_area(self, api):
        """PRD §2.1: "A request whose role is not listed among the endpoint's
        authorized roles is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: "| POST | `/dog-park/areas` | Create a park area (size-class
        restriction, capacity, peak derating) | ParkAdmin |"

        Design: Corner/rbac/member_cannot_create_area
        """
        member = register_member(full_name="Own Er", email="owner@x.com")
        resp = api.create_area(
            create_area_payload(name="Rogue Area",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestPeakWindowCapacity:
    def test_peak_window_collapses_effective_capacity(self, api):
        """PRD §3.4: "Otherwise, when the current logical minute-of-day falls
        inside any peak window, it is the lesser of `capacity` and
        `peak_capacity`. At all other times it is simply `capacity`."
        PRD §3.5: "Finally, last in the pipeline, the capacity quota: the
        check-in proceeds only while the area's `OPEN`-visit count is strictly
        below its `effective_capacity`; occupancy equal to the effective
        capacity rejects with `ERR_AREA_AT_CAPACITY`, while occupancy one below
        still admits."

        Design: Difficulty/combinatorial_formula/effective_capacity_peak_window_branch
        """
        scenario = setup_area_with_members(
            n_members=3, size_class="SMALL", capacity=2, peak_capacity=1,
            clock="2026-08-03T16:00:00Z", area_name="Small Side",
            peak_windows=[{"start_minute": 1020, "end_minute": 1140}])
        area = scenario["area"]
        members = scenario["members"]

        # Off-peak (16:00): effective_capacity is the full 2 — both check-ins
        # land below the bar.
        v1 = check_in_dog(members[0]["member"], members[0]["dog"], area)
        v2 = check_in_dog(members[1]["member"], members[1]["dog"], area)
        assert v1["status"] == "OPEN" and v2["status"] == "OPEN"

        # 17:30 falls inside the half-open window [1020, 1140): the effective
        # capacity collapses to min(2, 1) = 1 while the OPEN visits stay.
        set_clock("2026-08-03T17:30:00Z")
        resp = api.check_in(
            {"area_id": area["id"], "dog_id": members[2]["dog"]["id"]},
            members[2]["member_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_AREA_AT_CAPACITY)

        after = validate_success(api.get_area(area["id"], ADMIN))
        assert after["effective_capacity"] == 1, "peak window derating"
        assert after["current_occupancy"] == 2, (
            "existing OPEN visits are grandfathered through the derating"
        )

    def test_peak_window_half_open_boundaries(self, api):
        """PRD §3.4: "optionally `peak_windows`, a list of minute-of-day ranges
        each described by a `start_minute` and an `end_minute` and interpreted
        half-open: the window includes its start minute and excludes its end
        minute."
        PRD §3.4: "Otherwise, when the current logical minute-of-day falls
        inside any peak window, it is the lesser of `capacity` and
        `peak_capacity`. At all other times it is simply `capacity`."

        Design: Difficulty/combinatorial_formula/effective_capacity_peak_window_branch
        """
        set_clock("2026-08-03T16:59:00Z")
        area = create_park_area(
            name="Small Side", size_class_restriction="SMALL", capacity=2,
            peak_capacity=1,
            peak_windows=[{"start_minute": 1020, "end_minute": 1140}])

        def eff_at(instant):
            set_clock(instant)
            return validate_success(api.get_area(area["id"], ADMIN))[
                "effective_capacity"]

        assert eff_at("2026-08-03T16:59:00Z") == 2, "before the window"
        assert eff_at("2026-08-03T17:00:00Z") == 1, (
            "the window includes its start minute"
        )
        assert eff_at("2026-08-03T18:59:00Z") == 1, "inside the window"
        assert eff_at("2026-08-03T19:00:00Z") == 2, (
            "the window excludes its end minute"
        )


class TestClosureWindows:
    def test_closure_overlap_and_half_open_adjacency(self, api):
        """PRD §3.4: "A new window must not overlap any existing `SCHEDULED` or
        `ACTIVE` closure on the same area; adjacency is allowed, so a window
        beginning exactly when another ends is acceptable, while genuine
        overlap is rejected with `ERR_CLOSURE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/closure_overlap_half_open_adjacency
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Main", size_class_restriction="LARGE",
                                capacity=4, peak_capacity=4)

        first = schedule_closure(area["id"], "2026-08-10T00:00:00Z",
                                 "2026-08-12T00:00:00Z", "reseed turf")
        assert first["status"] == "SCHEDULED"

        overlap = api.create_closure(
            area["id"],
            create_closure_payload("2026-08-11T00:00:00Z",
                                   "2026-08-13T00:00:00Z",
                                   "overlapping fence work"),
            ADMIN,
        )
        validate_error(overlap, ApiErrorId.ERR_CLOSURE_OVERLAP)

        adjacent = schedule_closure(area["id"], "2026-08-12T00:00:00Z",
                                    "2026-08-14T00:00:00Z",
                                    "back-to-back gate repair")
        assert adjacent["status"] == "SCHEDULED", (
            "starts_at == prior ends_at is adjacency, not overlap"
        )

    def test_cancelled_closure_does_not_block_overlap(self, api):
        """PRD §3.4: "A new window must not overlap any existing `SCHEDULED` or
        `ACTIVE` closure on the same area; adjacency is allowed, so a window
        beginning exactly when another ends is acceptable, while genuine
        overlap is rejected with `ERR_CLOSURE_OVERLAP`."
        A CANCELLED closure is neither SCHEDULED nor ACTIVE, so it never
        blocks.

        Design: Difficulty/resource_temporal_overlap/closure_overlap_half_open_adjacency
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Main", size_class_restriction="LARGE",
                                capacity=4, peak_capacity=4)
        first = schedule_closure(area["id"], "2026-08-10T00:00:00Z",
                                 "2026-08-12T00:00:00Z", "reseed turf")
        cancelled = validate_success(api.cancel_closure(first["id"], ADMIN))
        assert cancelled["status"] == "CANCELLED"

        second = schedule_closure(area["id"], "2026-08-11T00:00:00Z",
                                  "2026-08-13T00:00:00Z", "fence work")
        assert second["status"] == "SCHEDULED", (
            "a cancelled window no longer participates in the overlap check"
        )

    def test_cancel_active_closure_rejected(self, api):
        """PRD §3.4: "A closure begins life `SCHEDULED`; the nightly run flips
        it `SCHEDULED → ACTIVE` once the logical time has reached `starts_at`
        while still preceding `ends_at`, and `ACTIVE → COMPLETED` once the
        logical time reaches or passes `ends_at`."
        PRD §3.4: "An administrator may also cancel a closure, but only while
        it remains `SCHEDULED` — `SCHEDULED → CANCELLED` — with any other
        status earning `ERR_CLOSURE_NOT_CANCELLABLE`; `COMPLETED` and
        `CANCELLED` are terminal."

        Design: Corner/state_machines/cancel_active_closure_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Main", size_class_restriction="LARGE",
                                capacity=4, peak_capacity=4)
        closure = schedule_closure(area["id"], "2026-08-01T00:00:00Z",
                                   "2026-08-05T00:00:00Z", "turf work")

        summary = run_nightly()
        assert summary["closures_activated"] == 1, (
            "starts_at reached while still preceding ends_at"
        )

        resp = api.cancel_closure(closure["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLOSURE_NOT_CANCELLABLE)

    def test_checkin_rejected_when_area_closure_active(self, api):
        """PRD §3.4: "While a closure stands `ACTIVE`, every check-in to its
        area is rejected with `ERR_AREA_CLOSED` (§3.5)."

        Design: Corner/validations/checkin_rejected_when_area_closure_active
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        schedule_closure(area["id"], "2026-08-01T00:00:00Z",
                         "2026-08-05T00:00:00Z", "turf work")
        run_nightly()
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     full_name="Own Er", email="owner@x.com",
                                     set_clock_first=False)

        resp = api.check_in(
            {"area_id": area["id"], "dog_id": bundle["dogs"][0]["id"]},
            bundle["member_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_AREA_CLOSED)


class TestClosureNotFound:
    def test_closure_on_unknown_area_returns_404(self, api):
        """PRD §2.8: "The not-found family is `ERR_MEMBER_NOT_FOUND`,
        `ERR_DOG_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`,
        `ERR_GUEST_PASS_NOT_FOUND`, `ERR_AREA_NOT_FOUND`,
        `ERR_CLOSURE_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, and `ERR_WASTE_STATION_NOT_FOUND`."

        Design: Corner/errors/error_area_not_found
        """
        resp = api.create_closure(
            NON_EXISTENT_UUID,
            create_closure_payload("2026-08-10T00:00:00Z",
                                   "2026-08-12T00:00:00Z", "turf work"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_AREA_NOT_FOUND)

    def test_cancel_unknown_closure_returns_404(self, api):
        """PRD §2.8: "The not-found family is `ERR_MEMBER_NOT_FOUND`,
        `ERR_DOG_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`,
        `ERR_GUEST_PASS_NOT_FOUND`, `ERR_AREA_NOT_FOUND`,
        `ERR_CLOSURE_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, and `ERR_WASTE_STATION_NOT_FOUND`."

        Design: Corner/errors/error_closure_not_found
        """
        resp = api.cancel_closure(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLOSURE_NOT_FOUND)
