"""Waste-station fill accounting, servicing, and the nightly service-run
epoch."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    advance_report,
    assert_instant_equals,
    check_in_dog,
    create_park_area,
    create_station,
    create_steward,
    file_report,
    make_member_headers,
    make_steward_headers,
    purchase_pass,
    register_member,
    run_nightly,
    set_clock,
    setup_active_member,
    validate_error,
    validate_paginated,
    validate_success,
    visit_in_out,
)

ADMIN = TEST_USERS["park_admin_headers"]


def _the_station(api, area_id):
    data, meta = validate_paginated(api.list_waste_stations(area_id, ADMIN))
    assert meta["total_count"] == 1
    return data[0]


class TestWasteStationCreation:
    def test_create_waste_station_defaults(self, api):
        """PRD §3.8: "An administrator installs a station into an area with
        just a `name`; it begins with `fill_pct` at 0, status `OK`, and
        `last_serviced_at` null until its first servicing."

        Design: Corner/entities/create_waste_station_defaults
        """
        area = create_park_area(name="Main", size_class_restriction="LARGE",
                                capacity=4, peak_capacity=2)
        station = create_station(area["id"], name="North Bin")
        assert station["fill_pct"] == 0
        assert station["status"] == "OK"
        assert station["last_serviced_at"] is None

    def test_service_unknown_station_returns_404(self, api):
        """PRD §2.8: "The not-found family is `ERR_MEMBER_NOT_FOUND`,
        `ERR_DOG_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`,
        `ERR_GUEST_PASS_NOT_FOUND`, `ERR_AREA_NOT_FOUND`,
        `ERR_CLOSURE_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, and `ERR_WASTE_STATION_NOT_FOUND`."

        Design: Corner/errors/error_waste_station_not_found
        """
        resp = api.service_waste_station(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_WASTE_STATION_NOT_FOUND)


class TestWasteFillAccumulation:
    def _setup_area_station_member(self, api):
        set_clock("2026-08-01T09:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        station = create_station(area["id"], name="South Bin")
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     full_name="Own Er", email="owner@x.com",
                                     set_clock_first=False)
        return area, station, bundle

    def test_waste_fill_threshold_boundary(self, api):
        """PRD §3.8: "On each service run, every station gains twenty-five
        percentage points for each visit checked into its area since the
        previous run — or since the station's creation when no run has yet
        occurred — counting visits of every status, with the accumulated
        `fill_pct` capped at 100."
        PRD §3.8: "A station whose total reaches at least eighty flips `OK →
        NEEDS_SERVICE`; at seventy-five (three fresh visits) it stays `OK`,
        while a fourth visit pushes it to 100 and trips the flag."

        Design: Corner/calculations/waste_fill_threshold_boundary
        """
        area, station, bundle = self._setup_area_station_member(api)
        member, dog = bundle["member"], bundle["dogs"][0]

        set_clock("2026-08-01T09:15:00Z")
        for _ in range(3):
            visit_in_out(member, dog, area)

        set_clock("2026-08-01T10:00:00Z")
        first = run_nightly()
        assert first["stations_flagged"] == 0
        station1 = _the_station(api, area["id"])
        assert station1["fill_pct"] == 75, "3 fresh visits x 25 points"
        assert station1["status"] == "OK", "75 stays below the 80 threshold"

        set_clock("2026-08-01T11:00:00Z")
        visit_in_out(member, dog, area)

        set_clock("2026-08-01T12:00:00Z")
        second = run_nightly()
        assert second["stations_flagged"] == 1
        station2 = _the_station(api, area["id"])
        assert station2["fill_pct"] == 100, "75 + 25 crosses the threshold"
        assert station2["status"] == "NEEDS_SERVICE"

    def test_service_resets_fill_by_steward(self, api):
        """PRD §3.8: "Servicing, recorded by a steward or an administrator,
        returns the station from either `OK` or `NEEDS_SERVICE` to `OK`, zeroes
        `fill_pct`, and stamps `last_serviced_at` with the current logical
        time."

        Design: Corner/calculations/service_resets_fill_by_steward
        """
        area, station, bundle = self._setup_area_station_member(api)
        member, dog = bundle["member"], bundle["dogs"][0]

        set_clock("2026-08-01T09:15:00Z")
        for _ in range(4):
            visit_in_out(member, dog, area)
        set_clock("2026-08-01T12:00:00Z")
        run_nightly()
        assert _the_station(api, area["id"])["status"] == "NEEDS_SERVICE"

        steward = create_steward(full_name="Ste Ward", email="steward@x.com")
        serviced = validate_success(api.service_waste_station(
            station["id"], steward["steward_headers"]))
        assert serviced["fill_pct"] == 0, "servicing zeroes the fill"
        assert serviced["status"] == "OK"
        assert_instant_equals(serviced["last_serviced_at"],
                              "2026-08-01T12:00:00Z", "last_serviced_at")


class TestServicingRbac:
    def test_service_requires_steward_flag(self, api):
        """PRD §2.1: "When `X-User-Role` is `Steward`, `X-User-ID` is likewise
        the `id` of a Member, and additionally that member's `is_steward` flag
        must be true; a steward-role request from a member without the flag
        fails with `ERR_NOT_A_STEWARD` (HTTP 403)."

        Design: Corner/validations/service_requires_steward_flag
        """
        area = create_park_area(name="Main", size_class_restriction="LARGE",
                                capacity=4, peak_capacity=4)
        station = create_station(area["id"], name="North Bin")
        plain = register_member(full_name="Plain Member", email="plain@x.com")

        resp = api.service_waste_station(station["id"],
                                         make_steward_headers(plain["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_A_STEWARD)

        after = _the_station(api, area["id"])
        assert after["fill_pct"] == 0
        assert after["last_serviced_at"] is None, (
            "the denied servicing never touches the station"
        )

    def test_parkadmin_override_covers_steward_ops(self, api):
        """PRD §2.1: "`ParkAdmin` is a hierarchical superset of every other
        role's capabilities and is exempt from both ownership checks and the
        steward-flag gate."
        PRD §3.7: "From `FILED` the only move is `FILED → UNDER_REVIEW`, open
        to stewards — members whose `is_steward` flag is set — and to
        administrators, and it recomputes the subject's provisional score."
        PRD §3.8: "Servicing, recorded by a steward or an administrator,
        returns the station from either `OK` or `NEEDS_SERVICE` to `OK`, zeroes
        `fill_pct`, and stamps `last_serviced_at` with the current logical
        time."

        Design: Corner/rbac/parkadmin_override_covers_steward_ops
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Main", size_class_restriction="LARGE",
                                capacity=4, peak_capacity=4)
        station = create_station(area["id"], name="North Bin")
        subject = register_member(full_name="Sub Ject", email="subject@x.com")
        report = file_report(subject["id"], severity="MINOR",
                             occurred_at="2026-08-01T10:00:00Z",
                             description="rough play")

        triaged = advance_report(report["id"], "UNDER_REVIEW", headers=ADMIN)
        assert triaged["status"] == "UNDER_REVIEW"

        serviced = validate_success(
            api.service_waste_station(station["id"], ADMIN))
        assert serviced["status"] == "OK"
        assert_instant_equals(serviced["last_serviced_at"],
                              "2026-08-01T00:00:00Z", "last_serviced_at")

    def test_member_cannot_run_service_run(self, api):
        """PRD §2.1: "A request whose role is not listed among the endpoint's
        authorized roles is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: "| POST | `/dog-park/service-runs/nightly` | Execute the
        nightly service-run epoch: six pinned cascades, atomically |
        ParkAdmin |"

        Design: Corner/rbac/member_cannot_run_service_run
        """
        member = register_member(full_name="Own Er", email="owner@x.com")
        resp = api.run_nightly_service_run(make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestNightlyRunSummary:
    def test_nightly_run_summary_counts(self, api):
        """PRD §3.8: "The run's response reports the epoch's yield as integer
        tallies: `visits_force_closed`, `memberships_expired`,
        `members_lapsed`, `guest_passes_expired`, `closures_activated`,
        `closures_completed`, `dogs_expired`, and `stations_flagged`."
        PRD §3.8: "1. Force-close every `OPEN` visit with `close_reason`
        `NIGHTLY_SWEEP`, stamping `checked_out_at` and recomputing each
        affected area's occupancy."
        PRD §3.8: "2. Expire memberships whose `term_end` is before the run's
        logical time — `ACTIVE → EXPIRED` or `SUSPENDED → EXPIRED`; where the
        prior status was `ACTIVE`, the owning member lapses `ACTIVE → LAPSED`
        in the same run, while a `SUSPENDED` member remains suspended."
        PRD §3.8: "3. Expire `ISSUED` guest passes whose `valid_on` is before
        the run's date, recomputing each sponsor's monthly usage with the
        expired passes still counting."
        PRD §3.8: "6. Sweep `VERIFIED` dogs whose `vaccination_expires_on` is
        before the run's date into `EXPIRED`."

        Design: Corner/cross_cutting_complexity_layers/nightly_run_summary_counts
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     full_name="Spon Sor",
                                     email="sponsor@x.com",
                                     set_clock_first=False)
        member = bundle["member"]
        purchase_pass(member, guest_dog_size_class="SMALL",
                      valid_on="2026-08-03")
        check_in_dog(member, bundle["dogs"][0], area)

        set_clock("2027-01-02T00:00:00Z")
        summary = run_nightly()
        assert summary["visits_force_closed"] == 1
        assert summary["memberships_expired"] == 1
        assert summary["members_lapsed"] == 1
        assert summary["guest_passes_expired"] == 1
        assert summary["closures_activated"] == 0
        assert summary["closures_completed"] == 0
        assert summary["dogs_expired"] == 0, (
            "the dog's vaccination (2027-06-01) is still valid at the run"
        )
        assert summary["stations_flagged"] == 0
