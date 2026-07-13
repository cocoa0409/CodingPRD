"""Caregiver matching and temporal rules: validation precedence (safety before
temporal), clearance re-checked at clock-in, closed-interval client overlap,
optimistic concurrency on assignment, and clock-in ownership."""
from test_helpers import (
    setup_assigned_visit,
    create_cleared_bonded_caregiver,
    create_client,
    create_visit,
    create_caregiver,
    assign_caregiver,
    set_clock,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    make_caregiver_headers,
    create_assignment_payload,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


class TestAssignSafetyBeatsTemporal:
    def _ctx(self, api):
        """Caregiver CLEARED with expires_at 2026-03-06 (expires once the clock is
        advanced to 2026-03-07), CONFIRMED on client-1 visit1 [10:00-12:00] at the
        default clock; a client-2 visit2 [11:00-13:00] genuinely overlaps."""
        cg = create_cleared_bonded_caregiver(api, name="CG-expired", check_expires_at="2026-03-06T00:00:00Z")
        client1 = create_client(api, name="Client One", home_zip="90001")
        client2 = create_client(api, name="Client Two", home_zip="90002")
        v1 = create_visit(api, client1["id"], scheduled_start="2026-03-05T10:00:00Z", scheduled_end="2026-03-05T12:00:00Z")
        assign_caregiver(api, v1["id"], cg["id"], v1["version"])
        v2 = create_visit(api, client2["id"], scheduled_start="2026-03-05T11:00:00Z", scheduled_end="2026-03-05T13:00:00Z")
        set_clock(api, "2026-03-07T00:00:00Z")  # cg's background check is now expired
        return {"caregiver": cg, "visit2": v2}

    def test_expired_clearance_reported_before_double_book(self, api):
        """PRD §2.10: "Caregiver clearance and bonding are ninth
        (ERR_CAREGIVER_NOT_CLEARED / ERR_CAREGIVER_NOT_BONDED)."
        PRD §2.10: "Temporal-overlap conflicts are eleventh
        (ERR_CAREGIVER_DOUBLE_BOOKED on assignment, ERR_CLIENT_VISIT_OVERLAP on
        visit creation)."

        Design: Difficulty/priority_pair_validation_conflict/assign_safety_beats_temporal
        """
        ctx = self._ctx(api)
        resp = api.create_assignment(
            ctx["visit2"]["id"], create_assignment_payload(ctx["caregiver"]["id"], ctx["visit2"]["version"]), COORD
        )
        validate_error(resp, ApiErrorId.ERR_CAREGIVER_NOT_CLEARED)

    def test_rejected_assignment_leaves_visit_unassigned(self, api):
        """PRD §3.2: "the caregiver must hold a CLEARED background check whose
        expires_at is strictly after the current clock, or the request is rejected
        with ERR_CAREGIVER_NOT_CLEARED"

        Design: Difficulty/priority_pair_validation_conflict/assign_safety_beats_temporal
        """
        ctx = self._ctx(api)
        api.create_assignment(
            ctx["visit2"]["id"], create_assignment_payload(ctx["caregiver"]["id"], ctx["visit2"]["version"]), COORD
        )
        visit = validate_success(api.get_visit(ctx["visit2"]["id"], COORD))
        assert visit["status"] == "SCHEDULED", f"rejected assign must leave visit SCHEDULED, got {visit['status']}"


class TestClockInClearanceRecheck:
    def test_clockin_blocked_when_check_expired(self, api):
        """PRD §3.5: "Clock-in requires the visit to be SCHEDULED (else
        ERR_VISIT_NOT_SCHEDULED), the acting caregiver to own the visit, and —
        because clearance is re-verified in the field — the caregiver to still be
        cleared and bonded at the current clock."

        Design: Difficulty/cross_entity_state_dependency/clockin_blocked_when_caregiver_check_expired
        """
        ctx = setup_assigned_visit(api, caregiver_check_expires_at="2026-03-06T00:00:00Z")
        set_clock(api, "2026-03-07T00:00:00Z")
        cg_headers = make_caregiver_headers(ctx["caregiver"]["id"])
        resp = api.clock_in(ctx["visit"]["id"], {"actual_start": "2026-03-05T09:00:00Z"}, cg_headers)
        validate_error(resp, ApiErrorId.ERR_CAREGIVER_NOT_CLEARED)

    def test_visit_stays_scheduled_after_blocked_clockin(self, api):
        """PRD §3.2: "Clearance and bonding are enforced together at two moments —
        when a caregiver is matched to a visit and when that caregiver clocks in."

        Design: Difficulty/cross_entity_state_dependency/clockin_blocked_when_caregiver_check_expired
        """
        ctx = setup_assigned_visit(api, caregiver_check_expires_at="2026-03-06T00:00:00Z")
        set_clock(api, "2026-03-07T00:00:00Z")
        cg_headers = make_caregiver_headers(ctx["caregiver"]["id"])
        api.clock_in(ctx["visit"]["id"], {"actual_start": "2026-03-05T09:00:00Z"}, cg_headers)
        visit = validate_success(api.get_visit(ctx["visit"]["id"], COORD))
        assert visit["status"] == "SCHEDULED", f"blocked clock-in must leave visit SCHEDULED, got {visit['status']}"


class TestClientVisitOverlapClosed:
    def _client_with_visit(self, api):
        client = create_client(api)
        create_visit(api, client["id"], scheduled_start="2026-03-06T10:00:00Z", scheduled_end="2026-03-06T12:00:00Z")
        return client

    def test_touching_endpoints_treated_as_overlap(self, api):
        """PRD §3.4: "This client-overlap comparison uses closed intervals with no
        buffer, so two visits whose endpoints merely touch — one beginning exactly
        when another ends — are treated as overlapping."

        Design: Difficulty/resource_temporal_overlap/client_visit_overlap_closed_adjacent
        """
        client = self._client_with_visit(api)
        resp = api.create_visit(
            {"client_id": client["id"], "task_type": "COMPANION",
             "scheduled_start": "2026-03-06T12:00:00Z", "scheduled_end": "2026-03-06T13:00:00Z"},
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_CLIENT_VISIT_OVERLAP)

    def test_rejected_overlap_does_not_persist_a_second_visit(self, api):
        """PRD §3.4: "Creating a visit also guards against the same client being
        double-booked: if the new visit's time range overlaps an existing
        non-cancelled visit for that client, the request is rejected with
        ERR_CLIENT_VISIT_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/client_visit_overlap_closed_adjacent
        """
        client = self._client_with_visit(api)
        api.create_visit(
            {"client_id": client["id"], "task_type": "COMPANION",
             "scheduled_start": "2026-03-06T12:00:00Z", "scheduled_end": "2026-03-06T13:00:00Z"},
            COORD,
        )
        data, meta = validate_paginated(api.list_visits(COORD, params={"client_id": client["id"]}))
        assert meta["total_count"] == 1, f"the rejected overlapping visit must not persist, got {meta['total_count']}"


def test_stale_visit_version_on_second_assignment_rejected(api):
    """PRD §2.7: "If expected_visit_version does not equal the visit's current
    version, the request is rejected with ERR_STALE_VISIT_VERSION at HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_visit_version_rejected_on_assign
    """
    ctx = setup_assigned_visit(api)  # first assignment already advanced the version
    stale_version = ctx["visit"]["version"]  # the create-time version, now stale
    resp = api.create_assignment(
        ctx["visit"]["id"], create_assignment_payload(ctx["caregiver"]["id"], stale_version), COORD
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VISIT_VERSION)


def test_clockin_by_non_owner_caregiver_rejected(api):
    """PRD §2.1: "a caregiver may clock in, clock out, escalate, and append
    visit-log entries only on a visit whose caregiver_id equals X-User-ID."

    Design: Corner/validations/error_not_resource_owner_wrong_caregiver_clockin
    """
    ctx = setup_assigned_visit(api)  # visit assigned to ctx["caregiver"]
    other_cg = create_caregiver(api, name="Other Caregiver")
    resp = api.clock_in(
        ctx["visit"]["id"], {"actual_start": "2026-03-05T09:00:00Z"}, make_caregiver_headers(other_cg["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
