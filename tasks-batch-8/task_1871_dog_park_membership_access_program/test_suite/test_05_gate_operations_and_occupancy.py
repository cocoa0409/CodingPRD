"""Gate check-in/check-out, capacity and occupancy accounting, vaccination
currency at the gate, and the open-visit overlap rule."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_dog,
    check_in_dog,
    check_in_guest,
    check_in_payload,
    check_out_visit,
    create_park_area,
    make_member_headers,
    purchase_pass,
    register_member,
    run_nightly,
    set_clock,
    setup_active_member,
    setup_area_with_members,
    validate_error,
    validate_paginated,
    validate_success,
    verify_dog,
    visit_in_out,
)

ADMIN = TEST_USERS["park_admin_headers"]


def _check_in_dog_raw(api, member_bundle, dog, area):
    return api.check_in(
        check_in_payload(area["id"], dog_id=dog["id"]),
        member_bundle["member_headers"],
    )


class TestVisitCreation:
    def test_visit_initial_state_open(self, api):
        """PRD §3.5: "The created ParkVisit opens in `OPEN` status with
        `checked_in_at` stamped at the current logical instant,
        `checked_out_at` null, `close_reason` null, and `member_id` bound to
        the caller — which for a guest visit is the pass's sponsor."

        Design: Corner/state_machines/visit_initial_state_open
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     full_name="Own Er", email="owner@x.com",
                                     set_clock_first=False)
        visit = check_in_dog(bundle["member"], bundle["dogs"][0], area)
        assert visit["status"] == "OPEN"
        assert visit["checked_out_at"] is None
        assert visit["close_reason"] is None
        assert visit["member_id"] == bundle["member"]["id"]

    def test_checkin_both_dog_and_pass_rejected(self, api):
        """PRD §3.5: "Check-in admits one animal per request: the payload
        carries an `area_id` plus exactly one of `dog_id` for a member's own
        dog or `guest_pass_id` for a sponsored guest — supplying both or
        neither is `ERR_INVALID_REQUEST`."

        Design: Corner/validations/checkin_both_dog_and_pass_rejected
        """
        set_clock("2026-08-03T10:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     full_name="Own Er", email="owner@x.com",
                                     set_clock_first=False)
        guest_pass = purchase_pass(bundle["member"],
                                   guest_dog_size_class="SMALL",
                                   valid_on="2026-08-03")
        resp = api.check_in(
            {"area_id": area["id"], "dog_id": bundle["dogs"][0]["id"],
             "guest_pass_id": guest_pass["id"]},
            bundle["member_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCapacityBoundary:
    def test_capacity_boundary_exact_full(self, api):
        """PRD §3.5: "Finally, last in the pipeline, the capacity quota: the
        check-in proceeds only while the area's `OPEN`-visit count is strictly
        below its `effective_capacity`; occupancy equal to the effective
        capacity rejects with `ERR_AREA_AT_CAPACITY`, while occupancy one below
        still admits."

        Design: Difficulty/boundary_precision_check/capacity_boundary_exact_full
        """
        scenario = setup_area_with_members(n_members=3, size_class="SMALL",
                                           capacity=2, peak_capacity=2,
                                           clock="2026-08-03T10:00:00Z")
        area = scenario["area"]
        members = scenario["members"]

        v1 = check_in_dog(members[0]["member"], members[0]["dog"], area)
        assert v1["status"] == "OPEN", "occupancy 0 < 2 admits"
        v2 = check_in_dog(members[1]["member"], members[1]["dog"], area)
        assert v2["status"] == "OPEN", "occupancy 1 < 2 admits"

        resp = api.check_in(
            check_in_payload(area["id"], dog_id=members[2]["dog"]["id"]),
            members[2]["member_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_AREA_AT_CAPACITY)

        after = validate_success(api.get_area(area["id"], ADMIN))
        assert after["current_occupancy"] == 2

    def test_capacity_reopens_after_checkout(self, api):
        """PRD §3.5: "Finally, last in the pipeline, the capacity quota: the
        check-in proceeds only while the area's `OPEN`-visit count is strictly
        below its `effective_capacity`; occupancy equal to the effective
        capacity rejects with `ERR_AREA_AT_CAPACITY`, while occupancy one below
        still admits."
        PRD §3.4: "The companion figure `current_occupancy` counts exactly the
        area's visits in `OPEN` status — `CLOSED` and `FORCE_CLOSED` visits
        never count — and is recomputed on every check-in, check-out, and
        force-close."

        Design: Difficulty/boundary_precision_check/capacity_boundary_exact_full
        """
        scenario = setup_area_with_members(n_members=2, size_class="SMALL",
                                           capacity=1, peak_capacity=1,
                                           clock="2026-08-03T10:00:00Z")
        area = scenario["area"]
        first, second = scenario["members"]

        visit = check_in_dog(first["member"], first["dog"], area)
        assert visit["status"] == "OPEN"

        blocked = api.check_in(
            check_in_payload(area["id"], dog_id=second["dog"]["id"]),
            second["member_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_AREA_AT_CAPACITY)

        check_out_visit(first["member"], visit)
        admitted = check_in_dog(second["member"], second["dog"], area)
        assert admitted["status"] == "OPEN", (
            "the compensating check-out drops occupancy one below the bar"
        )


class TestOccupancyConservation:
    def test_occupancy_checkin_checkout_conservation(self, api):
        """PRD §3.4: "The companion figure `current_occupancy` counts exactly
        the area's visits in `OPEN` status — `CLOSED` and `FORCE_CLOSED`
        visits never count — and is recomputed on every check-in, check-out,
        and force-close."

        Design: Difficulty/compensating_invariant/occupancy_checkin_checkout_conservation
        """
        scenario = setup_area_with_members(n_members=2, size_class="SMALL",
                                           capacity=4, peak_capacity=4,
                                           clock="2026-08-03T10:00:00Z")
        area = scenario["area"]
        first, second = scenario["members"]

        before = validate_success(api.get_area(area["id"], ADMIN))
        assert before["current_occupancy"] == 0

        v1 = check_in_dog(first["member"], first["dog"], area)
        v2 = check_in_dog(second["member"], second["dog"], area)
        mid = validate_success(api.get_area(area["id"], ADMIN))
        assert mid["current_occupancy"] == 2

        check_out_visit(first["member"], v1)
        check_out_visit(second["member"], v2)
        after = validate_success(api.get_area(area["id"], ADMIN))
        assert after["current_occupancy"] == 0, (
            "each check-in's compensating check-out restores occupancy exactly"
        )

    def test_occupancy_restored_by_force_close(self, api):
        """PRD §3.4: "The companion figure `current_occupancy` counts exactly
        the area's visits in `OPEN` status — `CLOSED` and `FORCE_CLOSED`
        visits never count — and is recomputed on every check-in, check-out,
        and force-close."
        PRD §3.8: "1. Force-close every `OPEN` visit with `close_reason`
        `NIGHTLY_SWEEP`, stamping `checked_out_at` and recomputing each
        affected area's occupancy."

        Design: Difficulty/compensating_invariant/occupancy_checkin_checkout_conservation
        """
        scenario = setup_area_with_members(n_members=2, size_class="SMALL",
                                           capacity=4, peak_capacity=4,
                                           clock="2026-08-03T10:00:00Z")
        area = scenario["area"]
        first, second = scenario["members"]

        v1 = check_in_dog(first["member"], first["dog"], area)
        v2 = check_in_dog(second["member"], second["dog"], area)
        assert validate_success(api.get_area(area["id"], ADMIN))[
            "current_occupancy"] == 2

        summary = run_nightly()
        assert summary["visits_force_closed"] == 2
        after = validate_success(api.get_area(area["id"], ADMIN))
        assert after["current_occupancy"] == 0, (
            "FORCE_CLOSED visits never count toward occupancy"
        )
        for v in (v1, v2):
            refreshed = validate_success(api.get_visit(v["id"], ADMIN))
            assert refreshed["status"] == "FORCE_CLOSED"
            assert refreshed["close_reason"] == "NIGHTLY_SWEEP"

    def test_occupancy_counts_member_and_guest_visits(self, api):
        """PRD §3.4: "The companion figure `current_occupancy` counts exactly
        the area's visits in `OPEN` status — `CLOSED` and `FORCE_CLOSED`
        visits never count — and is recomputed on every check-in, check-out,
        and force-close."
        PRD §3.5: "The created ParkVisit opens in `OPEN` status with
        `checked_in_at` stamped at the current logical instant,
        `checked_out_at` null, `close_reason` null, and `member_id` bound to
        the caller — which for a guest visit is the pass's sponsor."
        PRD §3.5: "For a guest visit, the pass must be `ISSUED` and its
        `valid_on` must equal the current logical date — any other status or
        date is `ERR_GUEST_PASS_NOT_REDEEMABLE` — and redemption flips the pass
        `ISSUED → REDEEMED` within the same request."

        Design: Corner/calculations/occupancy_counts_member_and_guest_visits
        """
        set_clock("2026-08-03T10:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     full_name="Spon Sor",
                                     email="sponsor@x.com",
                                     set_clock_first=False)
        guest_pass = purchase_pass(bundle["member"],
                                   guest_dog_size_class="SMALL",
                                   valid_on="2026-08-03")

        member_visit = check_in_dog(bundle["member"], bundle["dogs"][0], area)
        guest_visit = check_in_guest(bundle["member"], guest_pass, area)
        assert member_visit["status"] == "OPEN"
        assert guest_visit["status"] == "OPEN"
        assert guest_visit["guest_pass_id"] == guest_pass["id"]

        after = validate_success(api.get_area(area["id"], ADMIN))
        assert after["current_occupancy"] == 2, (
            "member-dog visits and guest-pass visits count identically"
        )
        redeemed = validate_success(api.get_guest_pass(guest_pass["id"], ADMIN))
        assert redeemed["status"] == "REDEEMED"


class TestOpenVisitOverlap:
    def test_dog_open_visit_unbounded_overlap(self, api):
        """PRD §3.5: "No dog may hold two open visits at once — a dog with an
        `OPEN` visit anywhere is turned away with `ERR_ALREADY_CHECKED_IN`,
        however long ago that visit began."

        Design: Difficulty/resource_temporal_overlap/dog_open_visit_unbounded_overlap
        """
        scenario = setup_area_with_members(n_members=1, size_class="SMALL",
                                           capacity=4, peak_capacity=4,
                                           clock="2026-08-03T10:00:00Z",
                                           area_name="Small A")
        area_a = scenario["area"]
        bundle = scenario["members"][0]
        area_b = create_park_area(name="Small B", size_class_restriction="SMALL",
                                  capacity=4, peak_capacity=4)

        first = check_in_dog(bundle["member"], bundle["dog"], area_a)
        blocked = api.check_in(
            check_in_payload(area_b["id"], dog_id=bundle["dog"]["id"]),
            bundle["member_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_ALREADY_CHECKED_IN)

        check_out_visit(bundle["member"], first)
        second = check_in_dog(bundle["member"], bundle["dog"], area_b)
        assert second["status"] == "OPEN", (
            "check-out closes the open-ended interval and re-admits the dog"
        )

    def test_nightly_sweep_frees_checked_in_dog(self, api):
        """PRD §3.5: "No dog may hold two open visits at once — a dog with an
        `OPEN` visit anywhere is turned away with `ERR_ALREADY_CHECKED_IN`,
        however long ago that visit began."
        PRD §3.8: "1. Force-close every `OPEN` visit with `close_reason`
        `NIGHTLY_SWEEP`, stamping `checked_out_at` and recomputing each
        affected area's occupancy."

        Design: Difficulty/resource_temporal_overlap/dog_open_visit_unbounded_overlap
        """
        scenario = setup_area_with_members(n_members=1, size_class="SMALL",
                                           capacity=4, peak_capacity=4,
                                           clock="2026-08-03T10:00:00Z",
                                           area_name="Small A")
        area_a = scenario["area"]
        bundle = scenario["members"][0]
        area_b = create_park_area(name="Small B", size_class_restriction="SMALL",
                                  capacity=4, peak_capacity=4)

        first = check_in_dog(bundle["member"], bundle["dog"], area_a)
        blocked = api.check_in(
            check_in_payload(area_b["id"], dog_id=bundle["dog"]["id"]),
            bundle["member_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_ALREADY_CHECKED_IN)

        summary = run_nightly()
        assert summary["visits_force_closed"] == 1
        refreshed = validate_success(api.get_visit(first["id"], ADMIN))
        assert refreshed["status"] == "FORCE_CLOSED"
        assert refreshed["close_reason"] == "NIGHTLY_SWEEP"

        second = check_in_dog(bundle["member"], bundle["dog"], area_b)
        assert second["status"] == "OPEN", (
            "the nightly force-close releases the dog for a fresh check-in"
        )


class TestGateVerification:
    def test_checkin_requires_verified_dog_submitted(self, api):
        """PRD §3.5: "For a dog visit, the dog must belong to the caller
        (`ERR_NOT_OWNER`; administrators are exempt), must stand `VERIFIED`
        (`ERR_DOG_NOT_VERIFIED`), and its `vaccination_expires_on` must be on
        or after the current logical date (`ERR_VACCINATION_EXPIRED`)."

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_dog_verified
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        member = register_member(full_name="Own Er", email="owner@x.com")
        verify_dog(add_dog(member["id"], name="Pip", size_class="SMALL",
                           license_number="LIC-1")["id"])
        validate_success(api.purchase_membership(
            member["id"], make_member_headers(member["id"])), 201)
        unverified = add_dog(member["id"], name="Gus", size_class="SMALL",
                             license_number="LIC-2")
        assert unverified["verification_status"] == "SUBMITTED"

        resp = api.check_in(
            check_in_payload(area["id"], dog_id=unverified["id"]),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DOG_NOT_VERIFIED)

        visits, meta = validate_paginated(api.list_visits(ADMIN))
        assert meta["total_count"] == 0, "no visit is created by the rejection"

    def test_checkin_requires_verified_dog_rejected(self, api):
        """PRD §3.5: "For a dog visit, the dog must belong to the caller
        (`ERR_NOT_OWNER`; administrators are exempt), must stand `VERIFIED`
        (`ERR_DOG_NOT_VERIFIED`), and its `vaccination_expires_on` must be on
        or after the current logical date (`ERR_VACCINATION_EXPIRED`)."
        PRD §3.2: "Rejecting moves the dog `SUBMITTED → REJECTED` and records
        the request's `reason` into `rejection_reason`."

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_dog_verified
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        member = register_member(full_name="Own Er", email="owner2@x.com")
        verify_dog(add_dog(member["id"], name="Pip", size_class="SMALL",
                           license_number="LIC-1")["id"])
        validate_success(api.purchase_membership(
            member["id"], make_member_headers(member["id"])), 201)
        rejected_dog = add_dog(member["id"], name="Gus", size_class="SMALL",
                               license_number="LIC-2")
        rejected_dog = validate_success(api.verify_dog(
            rejected_dog["id"], {"decision": "REJECTED", "reason": "bad docs"},
            ADMIN))
        assert rejected_dog["verification_status"] == "REJECTED"

        resp = api.check_in(
            check_in_payload(area["id"], dog_id=rejected_dog["id"]),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DOG_NOT_VERIFIED)

        _visits, meta = validate_paginated(api.list_visits(ADMIN))
        assert meta["total_count"] == 0


class TestGateVaccinationCurrency:
    def test_vaccination_expiry_beats_capacity(self, api):
        """PRD §2.7: "9. **Vaccination currency** — `vaccination_expires_on` is
        on or after the current logical date at dog verification, at
        resubmission, and at check-in: `ERR_VACCINATION_EXPIRED`."
        PRD §2.7: "12. **Quotas, always last** — the area's `OPEN`-visit count
        below its effective capacity, and the sponsor's monthly guest-pass
        usage below its limit: `ERR_AREA_AT_CAPACITY`,
        `ERR_GUEST_PASS_MONTHLY_LIMIT`."
        PRD §2.7: "Every request is adjudicated against a fixed priority
        pipeline, and a failure at any stage stops the pipeline and surfaces
        that stage's error."

        Design: Difficulty/priority_pair_validation_conflict/checkin_vaccination_beats_capacity
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=1,
                                peak_capacity=1)
        bundle_a = setup_active_member(num_dogs=1, size_class="SMALL",
                                       full_name="M A", email="ma@x.com",
                                       set_clock_first=False)
        check_in_dog(bundle_a["member"], bundle_a["dogs"][0], area)
        assert validate_success(api.get_area(area["id"], ADMIN))[
            "current_occupancy"] == 1

        bundle_b = setup_active_member(num_dogs=1, size_class="SMALL",
                                       vaccination_expires_on="2026-08-10",
                                       full_name="M B", email="mb@x.com",
                                       set_clock_first=False)
        # The clock moves past the vaccination date without a nightly run, so
        # the dog still stands VERIFIED while its certificate has lapsed.
        set_clock("2026-08-12T09:00:00Z")
        resp = api.check_in(
            check_in_payload(area["id"], dog_id=bundle_b["dogs"][0]["id"]),
            bundle_b["member_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VACCINATION_EXPIRED)

    def test_vaccination_valid_on_expiry_date_admitted(self, api):
        """PRD §3.5: "For a dog visit, the dog must belong to the caller
        (`ERR_NOT_OWNER`; administrators are exempt), must stand `VERIFIED`
        (`ERR_DOG_NOT_VERIFIED`), and its `vaccination_expires_on` must be on
        or after the current logical date (`ERR_VACCINATION_EXPIRED`)."
        A vaccination expiring exactly on the current logical date still
        admits; one day earlier is rejected.

        Design: Difficulty/priority_pair_validation_conflict/checkin_vaccination_beats_capacity
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        member = register_member(full_name="Own Er", email="owner3@x.com")
        boundary_dog = verify_dog(add_dog(
            member["id"], name="Pip", size_class="SMALL",
            license_number="LIC-1",
            vaccination_expires_on="2026-08-12")["id"])
        expired_dog = verify_dog(add_dog(
            member["id"], name="Gus", size_class="SMALL",
            license_number="LIC-2",
            vaccination_expires_on="2026-08-11")["id"])
        validate_success(api.purchase_membership(
            member["id"], make_member_headers(member["id"])), 201)

        set_clock("2026-08-12T09:00:00Z")
        visit = validate_success(api.check_in(
            check_in_payload(area["id"], dog_id=boundary_dog["id"]),
            make_member_headers(member["id"]),
        ), 201)
        assert visit["status"] == "OPEN", (
            "vaccination on the current logical date still admits"
        )
        resp = api.check_in(
            check_in_payload(area["id"], dog_id=expired_dog["id"]),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VACCINATION_EXPIRED)


class TestCheckout:
    def test_checkout_closed_visit_rejected(self, api):
        """PRD §3.5: "Closing a visit that is not `OPEN` is rejected with
        `ERR_VISIT_NOT_OPEN`, and a member attempting to close another member's
        visit hears `ERR_NOT_OWNER`."

        Design: Corner/state_machines/checkout_closed_visit_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     full_name="Own Er", email="owner@x.com",
                                     set_clock_first=False)
        visit = check_in_dog(bundle["member"], bundle["dogs"][0], area)
        closed = check_out_visit(bundle["member"], visit)
        assert closed["status"] == "CLOSED"
        assert closed["close_reason"] == "VOLUNTARY"

        resp = api.check_out(visit["id"], bundle["member_headers"])
        validate_error(resp, ApiErrorId.ERR_VISIT_NOT_OPEN)

    def test_checkout_unknown_visit_returns_404(self, api):
        """PRD §2.8: "The not-found family is `ERR_MEMBER_NOT_FOUND`,
        `ERR_DOG_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`,
        `ERR_GUEST_PASS_NOT_FOUND`, `ERR_AREA_NOT_FOUND`,
        `ERR_CLOSURE_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, and `ERR_WASTE_STATION_NOT_FOUND`."

        Design: Corner/errors/error_visit_not_found
        """
        resp = api.check_out(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VISIT_NOT_FOUND)


class TestImmediateConsistency:
    def test_immediate_visibility_after_checkin(self, api):
        """PRD §2.10: "State changes in this system propagate immediately, and
        every side effect of an operation commits atomically within the
        triggering request — there are no deferred or eventually-consistent
        cascades."
        PRD §3.5: "A successful entry recomputes the area's
        `current_occupancy`."

        Design: Corner/consistency_model/immediate_visibility_after_checkin
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     full_name="Own Er", email="owner@x.com",
                                     set_clock_first=False)
        visit = check_in_dog(bundle["member"], bundle["dogs"][0], area)
        assert visit["status"] == "OPEN"

        after = validate_success(api.get_area(area["id"], ADMIN))
        assert after["current_occupancy"] == 1, (
            "the very next read already reflects the check-in"
        )


class TestNightlySweep:
    def test_nightly_run_force_closes_open_visit(self, api):
        """PRD §3.8: "1. Force-close every `OPEN` visit with `close_reason`
        `NIGHTLY_SWEEP`, stamping `checked_out_at` and recomputing each
        affected area's occupancy."
        PRD §3.5: "Involuntary departure, `OPEN → FORCE_CLOSED`, arrives only
        through the two system paths: a member suspension with `close_reason`
        `MEMBER_SUSPENDED` (§3.7) and the nightly sweep with `close_reason`
        `NIGHTLY_SWEEP` (§3.8); both stamp `checked_out_at` and recompute
        occupancy."

        Design: Corner/state_machines/nightly_run_force_closes_open_visit
        """
        set_clock("2026-08-01T10:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     full_name="Own Er", email="owner@x.com",
                                     set_clock_first=False)
        visit = check_in_dog(bundle["member"], bundle["dogs"][0], area)

        set_clock("2026-08-01T23:00:00Z")
        summary = run_nightly()
        assert summary["visits_force_closed"] == 1

        refreshed = validate_success(api.get_visit(visit["id"], ADMIN))
        assert refreshed["status"] == "FORCE_CLOSED"
        assert refreshed["close_reason"] == "NIGHTLY_SWEEP"
        assert refreshed["checked_out_at"] is not None
        after = validate_success(api.get_area(area["id"], ADMIN))
        assert after["current_occupancy"] == 0

    def test_vaccination_expiry_sweep_marks_dog_expired(self, api):
        """PRD §3.8: "6. Sweep `VERIFIED` dogs whose `vaccination_expires_on`
        is before the run's date into `EXPIRED`."
        PRD §3.5: "For a dog visit, the dog must belong to the caller
        (`ERR_NOT_OWNER`; administrators are exempt), must stand `VERIFIED`
        (`ERR_DOG_NOT_VERIFIED`), and its `vaccination_expires_on` must be on
        or after the current logical date (`ERR_VACCINATION_EXPIRED`)."

        Design: Corner/state_machines/vaccination_expiry_sweep_marks_dog_expired
        """
        set_clock("2026-08-01T00:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     vaccination_expires_on="2026-08-10",
                                     full_name="Own Er", email="owner@x.com",
                                     set_clock_first=False)

        set_clock("2026-08-12T09:00:00Z")
        summary = run_nightly()
        assert summary["dogs_expired"] == 1

        dog = validate_success(api.get_dog(bundle["dogs"][0]["id"], ADMIN))
        assert dog["verification_status"] == "EXPIRED"
        resp = api.check_in(
            check_in_payload(area["id"], dog_id=dog["id"]),
            bundle["member_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DOG_NOT_VERIFIED)


class TestVisitListing:
    def test_list_visits_pagination(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return: it defaults to 10 when omitted, with a minimum of 1
        and a maximum of 100. The `offset` parameter specifies how many items
        to skip and defaults to 0."
        PRD §2.3: "Unless otherwise specified, every list endpoint returns
        resources sorted by `created_at` in ascending order. Paginated list
        responses carry `limit`, `offset`, `total_count`, and `has_more` in the
        `meta` object of the response envelope."

        Design: Corner/endpoints/list_visits_pagination
        """
        set_clock("2026-08-01T10:00:00Z")
        area = create_park_area(name="Small Side",
                                size_class_restriction="SMALL", capacity=4,
                                peak_capacity=4)
        bundle = setup_active_member(num_dogs=1, size_class="SMALL",
                                     full_name="Own Er", email="owner@x.com",
                                     set_clock_first=False)
        v1 = visit_in_out(bundle["member"], bundle["dogs"][0], area)
        set_clock("2026-08-01T10:30:00Z")
        v2 = visit_in_out(bundle["member"], bundle["dogs"][0], area)

        page1, meta1 = validate_paginated(
            api.list_visits(ADMIN, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert page1[0]["id"] == v1["id"], "created_at ascending"

        page2, meta2 = validate_paginated(
            api.list_visits(ADMIN, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert page2[0]["id"] == v2["id"]
