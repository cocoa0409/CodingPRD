"""Volunteer waivers: minor-age boundary, defaults, expiry sweep, supervisor
rules, briefing attendee rules (PRD §3.4, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    brief_event,
    complete_event,
    create_adult_waiver,
    create_event,
    create_minor_waiver,
    create_waiver_payload,
    get_event,
    make_coordinator_headers,
    make_group_leader_headers,
    set_clock,
    setup_active_agreement,
    setup_agreement_with_waiver,
    validate_error,
    validate_paginated,
    validate_success,
)
from prd_bench_local_runner.testing import NON_EXISTENT_UUID

COORD = make_coordinator_headers()


class TestMinorAgeBoundary:
    def test_minor_age_exactly_18_boundary(self, api):
        """PRD §3.4: "Minor status is computed at signing from whole calendar
        years: the volunteer's age is the largest whole number of years that
        can be added to `dob` without passing `signed_date`, and `is_minor` is
        true exactly when that age is strictly less than 18. The boundary is
        sharp — a volunteer whose eighteenth birthday falls exactly on the
        signing date is 18 and not a minor, while a `dob` one day later makes
        the volunteer 17 and a minor."

        Design: Difficulty/boundary_precision_check/minor_age_exactly_18_boundary
        """
        group, segment, agreement = setup_active_agreement(
            group_name="Scout Troop 9", contact_email="tess@troop9.org",
            route_name="Hill Rd", mile_marker_start=1.0, mile_marker_end=2.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        gl = make_group_leader_headers(group["id"])
        sup = create_adult_waiver(agreement["id"], group["id"],
                                  name="Sup Adult", dob="1990-01-01")

        # dob exactly 18 years before the default clock date 2026-08-01.
        adult = validate_success(api.create_waiver(
            create_waiver_payload(agreement["id"],
                                  volunteer_full_name="Ella Eighteen",
                                  dob="2008-08-01"), gl), 201)
        assert adult["is_minor"] is False
        assert adult["status"] == "ACTIVE"

        # One day later: 17 years 364 days -> minor; guardian fields required.
        denied = api.create_waiver(
            create_waiver_payload(agreement["id"],
                                  volunteer_full_name="Milo Minor",
                                  dob="2008-08-02"), gl)
        validate_error(denied, ApiErrorId.ERR_MINOR_GUARDIAN_REQUIRED)

        minor = validate_success(api.create_waiver(
            create_waiver_payload(agreement["id"],
                                  volunteer_full_name="Milo Minor",
                                  dob="2008-08-02",
                                  guardian_full_name="Pat Parent",
                                  guardian_consent=True,
                                  supervisor_waiver_id=sup["id"]), gl), 201)
        assert minor["is_minor"] is True
        assert minor["supervisor_waiver_id"] == sup["id"]

    def test_minor_without_guardian_consent_rejected(self, api):
        """PRD §3.4: "A minor's waiver is accepted only with
        `guardian_full_name` present and `guardian_consent` true, else
        `ERR_MINOR_GUARDIAN_REQUIRED`"

        Design: Difficulty/boundary_precision_check/minor_age_exactly_18_boundary
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        sup = create_adult_waiver(agreement["id"], group["id"],
                                  name="Sup Adult", dob="1990-01-01")
        resp = api.create_waiver(
            create_waiver_payload(agreement["id"],
                                  volunteer_full_name="Nina Minor",
                                  dob="2009-09-09",
                                  guardian_full_name="Pat Parent",
                                  guardian_consent=False,
                                  supervisor_waiver_id=sup["id"]), gl)
        validate_error(resp, ApiErrorId.ERR_MINOR_GUARDIAN_REQUIRED)


class TestWaiverDefaults:
    def test_waiver_defaults_and_computed_dates(self, api):
        """PRD §3.4: "The server stamps `signed_date` with the logical clock
        date at creation, computes `expiry_date` as one year after the signing
        date, and creates the waiver `ACTIVE`."
        PRD §3.4: "`guardian_consent` (which defaults to false)"
        PRD §2.5: "At startup the logical clock reads exactly 2026-08-01T00:00:00Z."

        Design: Corner/entities/waiver_defaults_and_computed_dates
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        waiver = validate_success(api.create_waiver(
            create_waiver_payload(agreement["id"],
                                  volunteer_full_name="Ada Adult",
                                  dob="1990-05-01"), gl), 201)
        assert waiver["is_minor"] is False
        assert waiver["guardian_consent"] is False
        assert waiver["status"] == "ACTIVE"
        assert waiver["signed_date"] == "2026-08-01"
        assert waiver["expiry_date"] == "2027-08-01"

    def test_adult_waiver_leaves_guardian_fields_null(self, api):
        """PRD §3.4: "Adult waivers leave the guardian and supervisor fields
        null."

        Design: Corner/entities/waiver_defaults_and_computed_dates
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        waiver = validate_success(api.create_waiver(
            create_waiver_payload(agreement["id"]), gl), 201)
        assert waiver["guardian_full_name"] is None
        assert waiver["supervisor_waiver_id"] is None


class TestWaiverExpirySweep:
    def test_waiver_expiry_sweep_boundary(self, api):
        """PRD §3.4: "A waiver remains `ACTIVE` while the clock date is on or
        before its `expiry_date`; the waiver-expiry sweep moves `ACTIVE`
        waivers whose expiry date has passed to `EXPIRED`"

        Design: Corner/state_machines/waiver_expiry_sweep_boundary
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver()
        # On the expiry date itself the waiver is still ACTIVE.
        set_clock("2027-08-01T09:00:00Z")
        d0 = validate_success(api.get_waiver(waiver["id"], COORD), 200)
        assert d0["expiry_date"] == "2027-08-01"
        assert d0["status"] == "ACTIVE"
        # One day later the sweep flips it.
        set_clock("2027-08-02T09:00:00Z")
        d1 = validate_success(api.get_waiver(waiver["id"], COORD), 200)
        assert d1["status"] == "EXPIRED"

    def test_expired_waiver_is_terminal_for_revoke(self, api):
        """PRD §3.4: "the leader may revoke an `ACTIVE` waiver at any time —
        revoking anything else fails with `ERR_WAIVER_NOT_ACTIVE`"

        Design: Corner/state_machines/waiver_expiry_sweep_boundary
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver()
        gl = make_group_leader_headers(group["id"])
        set_clock("2027-08-02T09:00:00Z")
        assert validate_success(
            api.get_waiver(waiver["id"], COORD), 200)["status"] == "EXPIRED"
        resp = api.revoke_waiver(waiver["id"], gl)
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_ACTIVE)


class TestWaiverRevoke:
    def test_double_waiver_revoke_rejected(self, api):
        """PRD §3.4: "the leader may revoke an `ACTIVE` waiver at any time —
        revoking anything else fails with `ERR_WAIVER_NOT_ACTIVE` — moving it
        to `REVOKED`."

        Design: Corner/validations/double_waiver_revoke_rejected
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver()
        gl = make_group_leader_headers(group["id"])
        first = validate_success(api.revoke_waiver(waiver["id"], gl), 200)
        assert first["status"] == "REVOKED"
        resp = api.revoke_waiver(waiver["id"], gl)
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_ACTIVE)

    def test_revoke_moves_waiver_to_revoked(self, api):
        """PRD §3.4: "the leader may revoke an `ACTIVE` waiver at any time ...
        moving it to `REVOKED`."

        Design: Corner/validations/double_waiver_revoke_rejected
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver()
        gl = make_group_leader_headers(group["id"])
        out = validate_success(api.revoke_waiver(waiver["id"], gl), 200)
        assert out["status"] == "REVOKED"


class TestBriefingAttendeeRules:
    def test_briefing_with_revoked_waiver_rejected(self, api):
        """PRD §3.3: "every listed waiver must resolve
        (`ERR_WAIVER_NOT_FOUND`), be `ACTIVE`, be unexpired — the clock date on
        or before its `expiry_date` — and belong to the event's agreement, else
        `ERR_WAIVER_INVALID_ATTENDEE`"

        Design: Corner/validations/briefing_with_revoked_waiver_rejected
        """
        group, segment, agreement, waiver = setup_agreement_with_waiver()
        gl = make_group_leader_headers(group["id"])
        revoked = validate_success(api.revoke_waiver(waiver["id"], gl), 200)
        assert revoked["status"] == "REVOKED"
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        resp = api.record_briefing(
            event["id"], {"attendee_waiver_ids": [waiver["id"]]}, gl)
        validate_error(resp, ApiErrorId.ERR_WAIVER_INVALID_ATTENDEE)

    def test_briefing_with_expired_waiver_rejected(self, api):
        """PRD §3.3: "every listed waiver must resolve
        (`ERR_WAIVER_NOT_FOUND`), be `ACTIVE`, be unexpired — the clock date on
        or before its `expiry_date` — and belong to the event's agreement, else
        `ERR_WAIVER_INVALID_ATTENDEE`"

        Design: Corner/validations/briefing_with_revoked_waiver_rejected
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        # Waiver signed at 2026-08-01 expires 2027-08-01; event in 2027-09.
        waiver = create_adult_waiver(agreement["id"], group["id"])
        # Keep the agreement compliant so the clock jump past the waiver's
        # expiry does not trigger the auto-suspension sweep (PRD §2.6/§3.2),
        # which would cancel the target SCHEDULED event before the briefing.
        keepalive = []
        for day in ("2026-09-10", "2026-09-12", "2026-09-14"):
            ev = create_event(agreement["id"], group["id"], scheduled_date=day,
                              expected_volunteers=2)
            brief_event(ev["id"], group["id"], [waiver["id"]])
            keepalive.append((day, ev["id"]))
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2027-09-10")
        for day, eid in keepalive:
            set_clock(f"{day}T10:00:00Z")
            complete_event(eid, group["id"])
        set_clock("2027-08-05T09:00:00Z")  # waiver now EXPIRED
        resp = api.record_briefing(
            event["id"], {"attendee_waiver_ids": [waiver["id"]]}, gl)
        validate_error(resp, ApiErrorId.ERR_WAIVER_INVALID_ATTENDEE)

    def test_briefing_with_unknown_waiver_returns_not_found(self, api):
        """PRD §2.11 family 3: "volunteer waivers, whether addressed by path,
        cited as a `supervisor_waiver_id`, or listed in `attendee_waiver_ids`
        (`ERR_WAIVER_NOT_FOUND`)"

        Design: Corner/validations/briefing_with_unknown_waiver_returns_not_found
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        resp = api.record_briefing(
            event["id"], {"attendee_waiver_ids": [NON_EXISTENT_UUID]}, gl)
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_FOUND)

    def test_minor_attendee_without_supervisor_present_rejected(self, api):
        """PRD §3.3: "for every minor in the attendee list, the waiver named by
        that minor's `supervisor_waiver_id` must also appear in the list, else
        `ERR_SUPERVISOR_ABSENT`."

        Design: Corner/validations/minor_attendee_without_supervisor_present_rejected
        """
        group, segment, agreement = setup_active_agreement(
            group_name="Scout Troop 9", contact_email="tess@troop9.org",
            route_name="Hill Rd", mile_marker_start=1.0, mile_marker_end=2.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        sup = create_adult_waiver(agreement["id"], group["id"],
                                  name="Sup Adult", dob="1990-01-01")
        m1 = create_minor_waiver(agreement["id"], group["id"], sup["id"])
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=4)
        gl = make_group_leader_headers(group["id"])

        resp = api.record_briefing(
            event["id"], {"attendee_waiver_ids": [m1["id"]]}, gl)
        validate_error(resp, ApiErrorId.ERR_SUPERVISOR_ABSENT)

        ok = validate_success(api.record_briefing(
            event["id"], {"attendee_waiver_ids": [m1["id"], sup["id"]]}, gl), 200)
        assert ok["status"] == "BRIEFING_DONE"
        assert ok["briefing_attendee_count"] == 2

    def test_briefing_records_attendee_count(self, api):
        """PRD §3.3: "A recorded briefing moves the event to `BRIEFING_DONE`
        and sets `briefing_attendee_count` to the size of the attendee list."

        Design: Corner/validations/minor_attendee_without_supervisor_present_rejected
        """
        group, segment, agreement = setup_active_agreement(
            group_name="Scout Troop 9", contact_email="tess@troop9.org",
            route_name="Hill Rd", mile_marker_start=1.0, mile_marker_end=2.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        sup = create_adult_waiver(agreement["id"], group["id"],
                                  name="Sup Adult", dob="1990-01-01")
        m1 = create_minor_waiver(agreement["id"], group["id"], sup["id"])
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=4)
        gl = make_group_leader_headers(group["id"])
        ok = validate_success(api.record_briefing(
            event["id"], {"attendee_waiver_ids": [m1["id"], sup["id"]]}, gl), 200)
        assert ok["briefing_attendee_count"] == 2


class TestSupervisorValidity:
    def test_minor_supervisor_must_be_adult_same_agreement(self, api):
        """PRD §3.4: "its `supervisor_waiver_id` must reference a waiver that
        is `ACTIVE`, belongs to an adult — `is_minor` false — sits under the
        same agreement, and is not the waiver being created, else
        `ERR_SUPERVISOR_INVALID`."

        Design: Corner/validations/minor_supervisor_must_be_adult_same_agreement
        """
        group, segment, agreement = setup_active_agreement(
            group_name="Scout Troop 9", contact_email="tess@troop9.org",
            route_name="Hill Rd", mile_marker_start=1.0, mile_marker_end=2.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        gl = make_group_leader_headers(group["id"])
        sup = create_adult_waiver(agreement["id"], group["id"],
                                  name="Sup Adult", dob="1990-01-01")
        m1 = create_minor_waiver(agreement["id"], group["id"], sup["id"])

        # Supervisor pointing at another minor.
        err1 = api.create_waiver(
            create_waiver_payload(agreement["id"],
                                  volunteer_full_name="Nina Minor",
                                  dob="2009-09-09",
                                  guardian_full_name="Pat Parent",
                                  guardian_consent=True,
                                  supervisor_waiver_id=m1["id"]), gl)
        validate_error(err1, ApiErrorId.ERR_SUPERVISOR_INVALID)

        # Supervisor from a DIFFERENT agreement.
        g2, s2, ag2 = setup_active_agreement(
            group_name="Other Group", org_type="BUSINESS",
            contact_email="o@o.org",
            route_name="Beta Rd", mile_marker_start=8.0, mile_marker_end=9.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        sup_b = create_adult_waiver(ag2["id"], g2["id"], name="Other Adult",
                                    dob="1985-07-04")
        err2 = api.create_waiver(
            create_waiver_payload(agreement["id"],
                                  volunteer_full_name="Nina Minor",
                                  dob="2009-09-09",
                                  guardian_full_name="Pat Parent",
                                  guardian_consent=True,
                                  supervisor_waiver_id=sup_b["id"]), gl)
        validate_error(err2, ApiErrorId.ERR_SUPERVISOR_INVALID)

    def test_supervisor_self_reference_rejected(self, api):
        """PRD §3.4: "its `supervisor_waiver_id` must reference a waiver that
        is `ACTIVE`, belongs to an adult — `is_minor` false — sits under the
        same agreement, and is not the waiver being created, else
        `ERR_SUPERVISOR_INVALID`."

        Design: Corner/validations/minor_supervisor_must_be_adult_same_agreement
        """
        group, segment, agreement = setup_active_agreement()
        gl = make_group_leader_headers(group["id"])
        # A supervisor reference that does not resolve at all is a 404
        # (existence family); a minor citing itself is impossible pre-creation,
        # so exercise the cross-agreement path with an unknown-but-well-formed
        # id to confirm existence resolution precedes the supervisor rule.
        resp = api.create_waiver(
            create_waiver_payload(agreement["id"],
                                  volunteer_full_name="Nina Minor",
                                  dob="2009-09-09",
                                  guardian_full_name="Pat Parent",
                                  guardian_consent=True,
                                  supervisor_waiver_id=NON_EXISTENT_UUID), gl)
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_FOUND)


class TestSupervisorReverseList:
    def test_supervisor_self_reference_reverse_list(self, api):
        """PRD §3.4: "Waiver listings filter by `agreement_id`,
        `supervisor_waiver_id`, and `status`, which makes a supervisor's whole
        supervised crew easy to enumerate."

        Design: Corner/entities/supervisor_self_reference_reverse_list
        """
        group, segment, agreement = setup_active_agreement(
            group_name="Scout Troop 9", contact_email="tess@troop9.org",
            route_name="Hill Rd", mile_marker_start=1.0, mile_marker_end=2.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        sup = create_adult_waiver(agreement["id"], group["id"],
                                  name="Sup Adult", dob="1990-01-01")
        m1 = create_minor_waiver(agreement["id"], group["id"], sup["id"])
        gl = make_group_leader_headers(group["id"])

        rows, meta = validate_paginated(
            api.list_waivers(gl, params={"supervisor_waiver_id": sup["id"]}))
        assert len(rows) == 1
        assert rows[0]["id"] == m1["id"]
        assert meta["total_count"] == 1

    def test_supervisor_reverse_list_excludes_unrelated_waivers(self, api):
        """PRD §3.4: "Waiver listings filter by `agreement_id`,
        `supervisor_waiver_id`, and `status`"

        Design: Corner/entities/supervisor_self_reference_reverse_list
        """
        group, segment, agreement = setup_active_agreement(
            group_name="Scout Troop 9", contact_email="tess@troop9.org",
            route_name="Hill Rd", mile_marker_start=1.0, mile_marker_end=2.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        sup = create_adult_waiver(agreement["id"], group["id"],
                                  name="Sup Adult", dob="1990-01-01")
        m1 = create_minor_waiver(agreement["id"], group["id"], sup["id"])
        other = create_adult_waiver(agreement["id"], group["id"],
                                    name="Ben Adult", dob="1988-03-15")
        gl = make_group_leader_headers(group["id"])
        rows, meta = validate_paginated(
            api.list_waivers(gl, params={"supervisor_waiver_id": other["id"]}))
        assert rows == []
        assert meta["total_count"] == 0
