"""Packing sessions: overlap semantics, capacity, volunteer identity binding,
and volunteer status gates."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_member,
    create_packing_session,
    create_seed_lot,
    create_site,
    create_variety,
    create_volunteer,
    make_member_headers,
    make_volunteer_headers,
    sign_up,
    submit_for_review,
    TEST_USERS,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]


class TestVolunteerDoubleBooking:
    def test_back_to_back_sessions_allowed_at_site_but_touch_conflicts_for_volunteer(self):
        """PRD §3.7: "Sessions at the same site observe a half-open overlap
        rule: a new session's interval from start to end must not intersect any
        non-`CANCELLED` session's interval at that site, though back-to-back
        scheduling — one session's end landing exactly on another's start — is
        allowed."
        PRD §3.7: "Double-booking uses closed-interval semantics across the
        volunteer's live assignments — those in `SIGNUP` or `ATTENDED`:
        sessions that merely touch, one ending exactly when the next begins,
        still count as a conflict because volunteers have zero travel time, and
        any overlap or touch is rejected with
        `ERR_VOLUNTEER_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/volunteer_closed_interval_double_booking
        """
        site = create_site(site_type="GARDEN")
        s1 = create_packing_session(
            site["id"],
            start_at="2026-10-11T09:00:00Z", end_at="2026-10-11T11:00:00Z",
        )
        # Site-level half-open rule permits back-to-back adjacency.
        s2 = create_packing_session(
            site["id"],
            start_at="2026-10-11T11:00:00Z", end_at="2026-10-11T13:00:00Z",
        )
        volunteer = create_volunteer()
        first = sign_up(s1["id"], volunteer["id"])
        assert first["status"] == "SIGNUP"
        # Volunteer-level closed semantics: touching endpoints conflict.
        resp = api_client.sign_up_volunteer(
            s2["id"],
            {"volunteer_id": volunteer["id"]},
            make_volunteer_headers(volunteer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_DOUBLE_BOOKED)

    def test_true_overlap_across_sites_conflicts_for_volunteer(self):
        """PRD §3.7: "Double-booking uses closed-interval semantics across the
        volunteer's live assignments — those in `SIGNUP` or `ATTENDED`:
        sessions that merely touch, one ending exactly when the next begins,
        still count as a conflict because volunteers have zero travel time, and
        any overlap or touch is rejected with
        `ERR_VOLUNTEER_DOUBLE_BOOKED`."

        A genuinely overlapping session at a different site conflicts too —
        the rule binds the volunteer, not the site.

        Design: Difficulty/resource_temporal_overlap/volunteer_closed_interval_double_booking
        """
        site_a = create_site(site_type="GARDEN", name="A")
        site_b = create_site(site_type="GARDEN", name="B")
        s1 = create_packing_session(
            site_a["id"],
            start_at="2026-10-11T09:00:00Z", end_at="2026-10-11T11:00:00Z",
        )
        s3 = create_packing_session(
            site_b["id"],
            start_at="2026-10-11T10:30:00Z", end_at="2026-10-11T12:00:00Z",
        )
        volunteer = create_volunteer()
        sign_up(s1["id"], volunteer["id"])
        resp = api_client.sign_up_volunteer(
            s3["id"],
            {"volunteer_id": volunteer["id"]},
            make_volunteer_headers(volunteer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_DOUBLE_BOOKED)


class TestSessionCapacityBoundary:
    def test_second_signup_admitted_third_rejected_at_capacity_2(self):
        """PRD §3.7: "Capacity then requires the session's live-assignment
        count to remain strictly below `capacity`; a session already full
        rejects the sign-up with `ERR_SESSION_CAPACITY_FULL`."

        Capacity 2: the 2nd signup is admitted (1 < 2), the 3rd is rejected
        (2 == capacity).

        Design: Corner/validations/val_session_capacity_boundary
        """
        site = create_site(site_type="GARDEN", region_zone="ZONE_7A")
        session = create_packing_session(
            site["id"],
            start_at="2026-10-25T09:00:00Z", end_at="2026-10-25T11:00:00Z",
            capacity=2,
        )
        v1 = create_volunteer()
        v2 = create_volunteer()
        v3 = create_volunteer()
        sign_up(session["id"], v1["id"])
        second = sign_up(session["id"], v2["id"])
        assert second["status"] == "SIGNUP"
        resp = api_client.sign_up_volunteer(
            session["id"],
            {"volunteer_id": v3["id"]},
            make_volunteer_headers(v3["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_CAPACITY_FULL)


class TestVolunteerIdentityBinding:
    def test_volunteer_cannot_sign_up_another_volunteer(self):
        """PRD §2.1: "Self-service is enforced by an ownership rule: a `Member`
        may act only on resources whose `member_id` equals the presented
        `X-User-ID`, and a `Volunteer` only on assignments whose `volunteer_id`
        equals it. Violations are rejected with `ERR_SELF_SERVICE_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/rbac_volunteer_cannot_signup_other_volunteer
        """
        site = create_site(site_type="GARDEN", region_zone="ZONE_7A")
        session = create_packing_session(
            site["id"],
            start_at="2026-11-01T09:00:00Z", end_at="2026-11-01T11:00:00Z",
        )
        v1 = create_volunteer()
        v2 = create_volunteer()
        resp = api_client.sign_up_volunteer(
            session["id"],
            {"volunteer_id": v2["id"]},
            make_volunteer_headers(v1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_SERVICE_FORBIDDEN)


class TestVolunteerStatusGates:
    def test_applied_volunteer_cannot_record_assay(self):
        """PRD §3.1: "Only `ACTIVE` volunteers may record germination assays,
        pack lots, or sign up for packing sessions."
        PRD §2.9: "when the entity is non-terminal but the trigger is not valid
        from its current state, the rejection is `ERR_INVALID_STATE`."

        Design: Corner/rbac/rbac_applied_volunteer_cannot_record_test
        """
        site = create_site(site_type="GARDEN", region_zone="ZONE_7A")
        variety = create_variety(category="HERB", approved_zones=["ZONE_7A"])
        lot = create_seed_lot(
            variety["id"], site["id"],
            seeds_received=50, provisional_viability_pct=80.00,
        )
        volunteer = create_volunteer(approve=False)
        assert volunteer["status"] == "APPLIED"
        submit_for_review(lot["id"])
        resp = api_client.record_germination_test(
            lot["id"],
            {"seeds_tested": 10, "sprouted_count": 9},
            make_volunteer_headers(volunteer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_member_cannot_pack_or_record(self):
        """PRD §2.1: "A properly authenticated caller whose role is not in an
        endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD §4: POST /api/seed-lots/{id}/pack is authorized for "Volunteer";
        POST /api/seed-lots/{id}/germination-tests is authorized for
        "Volunteer".

        Design: Corner/rbac/rbac_member_cannot_pack_or_record
        """
        site = create_site(site_type="GARDEN", region_zone="ZONE_7A")
        variety = create_variety(category="HERB", approved_zones=["ZONE_7A"])
        lot = create_seed_lot(
            variety["id"], site["id"],
            seeds_received=50, provisional_viability_pct=80.00,
        )
        member = create_member(site["id"])
        headers = make_member_headers(member["id"])
        resp = api_client.pack_seed_lot(
            lot["id"], {"packet_count": 1, "seeds_per_packet": 10}, headers
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        resp = api_client.record_germination_test(
            lot["id"], {"seeds_tested": 10, "sprouted_count": 9}, headers
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
