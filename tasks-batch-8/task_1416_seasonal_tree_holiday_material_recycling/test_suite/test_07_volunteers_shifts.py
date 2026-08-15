"""Volunteers and shifts: approval gate, half-open overlap, site-day-role
capacity, cancellation cutoff, and the no-show auto-suspension cascade."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_active_program,
    create_shift,
    get_shift,
    get_volunteer,
    make_volunteer_headers,
    open_site,
    register_approved_volunteer,
    register_volunteer,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestShiftOverlap:

    def _setup(self):
        ctx = create_active_program()
        open_site(ctx["site"])
        volunteer = register_approved_volunteer(ctx["program"]["id"])
        return ctx, volunteer

    def test_adjacent_half_open_shifts_admitted(self):
        """PRD section 3.7: "the new shift's half-open interval — covering
        `start_at` up to but not including `end_at` — must not overlap any of
        the volunteer's existing `SIGNED_UP` or `COMPLETED` shifts; adjacency
        is allowed, so a shift starting exactly when another ends is fine, and
        a true overlap is rejected with `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/volunteer_shift_adjacency_half_open
        """
        ctx, volunteer = self._setup()
        sh1 = create_shift(volunteer, ctx["site"]["id"],
                           start_at="2027-01-09T09:00:00Z",
                           end_at="2027-01-09T12:00:00Z", shift_role="LOADER")
        # Adjacent: starts exactly when the first ends — allowed.
        sh2 = create_shift(volunteer, ctx["site"]["id"],
                           start_at="2027-01-09T12:00:00Z",
                           end_at="2027-01-09T15:00:00Z",
                           shift_role="GREETER")
        assert sh1["status"] == "SIGNED_UP"
        assert sh2["status"] == "SIGNED_UP"

    def test_overlapping_shift_rejected(self):
        """PRD section 3.7: "the new shift's half-open interval — covering
        `start_at` up to but not including `end_at` — must not overlap any of
        the volunteer's existing `SIGNED_UP` or `COMPLETED` shifts; adjacency
        is allowed, so a shift starting exactly when another ends is fine, and
        a true overlap is rejected with `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/volunteer_shift_adjacency_half_open
        """
        ctx, volunteer = self._setup()
        create_shift(volunteer, ctx["site"]["id"],
                     start_at="2027-01-09T09:00:00Z",
                     end_at="2027-01-09T12:00:00Z", shift_role="LOADER")
        create_shift(volunteer, ctx["site"]["id"],
                     start_at="2027-01-09T12:00:00Z",
                     end_at="2027-01-09T15:00:00Z", shift_role="GREETER")

        # 11:00-13:00 straddles both booked intervals: a true overlap.
        resp = api_client.create_volunteer_shift(
            {"volunteer_id": volunteer["id"], "site_id": ctx["site"]["id"],
             "start_at": "2027-01-09T11:00:00Z",
             "end_at": "2027-01-09T13:00:00Z",
             "shift_role": "TRAFFIC_CONTROL"},
            make_volunteer_headers(volunteer["id"]))
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)


class TestShiftGates:

    def test_shift_signup_requires_approved_volunteer(self):
        """PRD section 3.7: "Signup is rejected with
        `ERR_VOLUNTEER_NOT_APPROVED` while the volunteer holds any other
        status".

        Design: Corner/validations/shift_signup_requires_approved_volunteer
        """
        ctx = create_active_program()
        open_site(ctx["site"])
        volunteer = register_volunteer(ctx["program"]["id"])
        assert volunteer["status"] == "APPLIED"

        resp = api_client.create_volunteer_shift(
            {"volunteer_id": volunteer["id"], "site_id": ctx["site"]["id"],
             "start_at": "2027-01-09T09:00:00Z",
             "end_at": "2027-01-09T12:00:00Z", "shift_role": "LOADER"},
            make_volunteer_headers(volunteer["id"]))
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_APPROVED)

        approve = api_client.patch_volunteer(volunteer["id"],
                                             {"status": "APPROVED"}, ADMIN)
        assert validate_success(approve, 200)["status"] == "APPROVED"
        shift = create_shift(volunteer, ctx["site"]["id"],
                             start_at="2027-01-09T09:00:00Z",
                             end_at="2027-01-09T12:00:00Z",
                             shift_role="LOADER")
        assert shift["status"] == "SIGNED_UP"

    def test_shift_role_capacity_full(self):
        """PRD section 3.7: "the count of `SIGNED_UP` or `COMPLETED` shifts at
        the same site on the same calendar date with the same `shift_role`
        must remain at or below the site's `volunteer_slots_per_role` — exact
        equality is admitted, and one shift beyond the limit is rejected with
        `ERR_SHIFT_CAPACITY_FULL`."

        Design: Corner/validations/shift_role_capacity_full
        """
        ctx = create_active_program(
            site_overrides={"volunteer_slots_per_role": 1})
        open_site(ctx["site"])
        v1 = register_approved_volunteer(ctx["program"]["id"])
        v2 = register_approved_volunteer(ctx["program"]["id"])

        first = create_shift(v1, ctx["site"]["id"],
                             start_at="2027-01-09T09:00:00Z",
                             end_at="2027-01-09T12:00:00Z",
                             shift_role="GREETER")
        assert first["status"] == "SIGNED_UP"

        # Second GREETER on the same calendar date at the same site exceeds
        # the single slot, even though v2's own schedule is free.
        resp = api_client.create_volunteer_shift(
            {"volunteer_id": v2["id"], "site_id": ctx["site"]["id"],
             "start_at": "2027-01-09T10:00:00Z",
             "end_at": "2027-01-09T13:00:00Z", "shift_role": "GREETER"},
            make_volunteer_headers(v2["id"]))
        validate_error(resp, ApiErrorId.ERR_SHIFT_CAPACITY_FULL)


class TestShiftCancelCutoff:

    def test_shift_cancel_cutoff_boundary(self):
        """PRD section 3.7: "the volunteer faces a twenty-four-hour cutoff —
        cancellation is allowed only while the clock reads no later than
        twenty-four hours before `start_at`, the boundary inclusive, with
        later attempts rejected as `ERR_SHIFT_CUTOFF_PASSED` — while the
        `ProgramAdmin` is exempt from that cutoff."

        Design: Corner/validations/shift_cancel_cutoff_boundary
        """
        ctx, volunteer = self._setup_two_shifts()
        sh1, sh2 = ctx["sh1"], ctx["sh2"]

        # Exactly start_at - 24h: the volunteer's own cancel is admitted.
        # sh1 starts 2027-01-09T09:00:00Z, so its cutoff is 2027-01-08T09:00:00Z.
        set_clock("2027-01-08T09:00:00Z")
        resp = api_client.patch_volunteer_shift(
            sh1["id"], {"status": "CANCELLED"},
            make_volunteer_headers(volunteer["id"]))
        assert validate_success(resp, 200)["status"] == "CANCELLED"

        # One second inside sh2's own cutoff: the volunteer is rejected.
        # sh2 starts 2027-01-09T12:00:00Z, so its cutoff is 2027-01-08T12:00:00Z.
        set_clock("2027-01-08T12:00:01Z")
        resp = api_client.patch_volunteer_shift(
            sh2["id"], {"status": "CANCELLED"},
            make_volunteer_headers(volunteer["id"]))
        validate_error(resp, ApiErrorId.ERR_SHIFT_CUTOFF_PASSED)
        assert get_shift(sh2["id"])["status"] == "SIGNED_UP"

        # The administrator is exempt from the cutoff.
        resp = api_client.patch_volunteer_shift(
            sh2["id"], {"status": "CANCELLED"}, ADMIN)
        assert validate_success(resp, 200)["status"] == "CANCELLED"

    def _setup_two_shifts(self):
        ctx = create_active_program()
        open_site(ctx["site"])
        volunteer = register_approved_volunteer(ctx["program"]["id"])
        ctx["sh1"] = create_shift(volunteer, ctx["site"]["id"],
                                  start_at="2027-01-09T09:00:00Z",
                                  end_at="2027-01-09T12:00:00Z",
                                  shift_role="LOADER")
        ctx["sh2"] = create_shift(volunteer, ctx["site"]["id"],
                                  start_at="2027-01-09T12:00:00Z",
                                  end_at="2027-01-09T15:00:00Z",
                                  shift_role="GREETER")
        return ctx, volunteer


class TestNoShowAutoSuspend:

    def test_ops_run_auto_suspends_volunteer_at_three_no_shows(self):
        """PRD section 3.8: "Every volunteer shift still `SIGNED_UP` whose
        `end_at` has passed is marked `NO_SHOW`, incrementing the volunteer's
        `no_show_count` — and a volunteer reaching three no-shows is suspended
        with their future `SIGNED_UP` shifts cancelled, per Section 3.7."
        PRD section 3.7: "Each `NO_SHOW` adds one to the volunteer's
        `no_show_count`, and the count reaching three — exactly at the third
        no-show — automatically suspends the volunteer (`APPROVED →
        SUSPENDED`) and cancels all of their future `SIGNED_UP` shifts."

        Design: Corner/state_machines/ops_run_auto_suspends_volunteer_at_three_no_shows
        """
        ctx = create_active_program()
        open_site(ctx["site"])
        volunteer = register_approved_volunteer(ctx["program"]["id"])
        site_id = ctx["site"]["id"]

        for day in ("2027-01-03", "2027-01-04", "2027-01-05"):
            create_shift(volunteer, site_id,
                         start_at=f"{day}T09:00:00Z",
                         end_at=f"{day}T10:00:00Z", shift_role="LOADER")
        future = create_shift(volunteer, site_id,
                              start_at="2027-01-09T09:00:00Z",
                              end_at="2027-01-09T12:00:00Z",
                              shift_role="GREETER")

        # All three early shifts have elapsed; the fourth is still future.
        set_clock("2027-01-06T00:00:00Z")
        validate_success(
            api_client.ops_run_program(ctx["program"]["id"], ADMIN), 200)

        volunteer_after = get_volunteer(volunteer["id"])
        assert volunteer_after["no_show_count"] == 3
        assert volunteer_after["status"] == "SUSPENDED", \
            "the third no-show auto-suspends the volunteer"
        assert get_shift(future["id"])["status"] == "CANCELLED", \
            "auto-suspension cancels future SIGNED_UP shifts"

        data, meta = validate_paginated(api_client.list_volunteer_shifts(
            ADMIN, params={"volunteer_id": volunteer["id"],
                           "status": "NO_SHOW"}))
        assert len(data) == 3
        assert meta["total_count"] == 3
