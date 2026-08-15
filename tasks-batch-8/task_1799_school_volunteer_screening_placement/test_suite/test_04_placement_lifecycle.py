"""Placement pipeline: requests, confirmation gates, unwind, completion."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    check_in_volunteer,
    check_out_volunteer,
    confirm_placement,
    create_active_volunteer,
    create_lincoln_campus,
    create_open_opportunity,
    create_orient_module,
    file_incident,
    get_opportunity,
    get_placement,
    get_volunteer,
    make_volunteer_headers,
    request_placement,
    set_clock,
    setup_volunteer_with_confirmed_placement,
    validate_error,
    validate_paginated,
    validate_success,
)

DC = TEST_USERS["coordinator_headers"]
CA = TEST_USERS["campus_admin_headers"]


class TestPlacementRequests:
    def test_duplicate_active_placement_rejected(self, api):
        """PRD: "A request requires the opportunity to be `OPEN` (else
        `ERR_OPPORTUNITY_INVALID_STATE`) and the volunteer to be `ACTIVE` (else
        `ERR_VOLUNTEER_INVALID_STATE`), and it rejects a duplicate: if the same
        volunteer already holds a placement in `REQUESTED` or `CONFIRMED` on
        that opportunity, the request fails with `ERR_DUPLICATE_PLACEMENT`."

        Design: Corner/endpoints/duplicate_active_placement_rejected
        """
        recruited = create_active_volunteer("Dup Deb", "deb@x.com",
                                            "SUPERVISED")
        vid = recruited["volunteer"]["id"]
        campus = create_lincoln_campus()
        opp = create_open_opportunity(campus["id"], capacity=2)

        first = request_placement(opp["id"], vid)
        assert first["status"] == "REQUESTED"

        duplicate = api.create_placement(
            {"opportunity_id": opp["id"]}, make_volunteer_headers(vid))
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_PLACEMENT)

        # Cancelling releases the pair: a fresh request succeeds.
        validate_success(api.cancel_placement(
            first["id"], make_volunteer_headers(vid)), 200)
        re_request = validate_success(api.create_placement(
            {"opportunity_id": opp["id"]}, make_volunteer_headers(vid)), 201)
        assert re_request["status"] == "REQUESTED"


class TestConfirmGateStack:
    def test_confirm_rejected_when_volunteer_suspended(self, api):
        """PRD: "The full pipeline of §2.7 applies: the placement must be
        `REQUESTED` (else `ERR_PLACEMENT_INVALID_STATE`), its opportunity
        `OPEN` (else `ERR_OPPORTUNITY_INVALID_STATE`), and the volunteer
        `ACTIVE` (else `ERR_VOLUNTEER_INVALID_STATE`)"
        PRD: "Filing a `HIGH` report against a volunteer in `ACTIVE`,
        `RESCREEN_REQUIRED`, or `CLEARANCE_GRANTED` suspends them on the spot"

        Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_volunteer_suspended
        """
        recruited = create_active_volunteer("Blocked Bo", "bo@x.com",
                                            "SUPERVISED")
        vid = recruited["volunteer"]["id"]
        campus = create_lincoln_campus()
        opp = create_open_opportunity(campus["id"], capacity=2)
        placement = request_placement(opp["id"], vid)

        file_incident(vid, severity="HIGH", description="Argument with staff")

        confirm = api.confirm_placement(placement["id"], CA)
        validate_error(confirm, ApiErrorId.ERR_VOLUNTEER_INVALID_STATE)

        assert get_placement(placement["id"])["status"] == "REQUESTED"
        assert get_opportunity(opp["id"])["committed_count"] == 0

    def test_suspension_preserves_requested_placement_and_blocks_confirm(self, api):
        """PRD: "Note the asymmetry with removal: suspension cancels only
        confirmed placements, leaving mere requests in place, and the request
        side is handled later if the incident is substantiated."
        PRD: "Filing a `HIGH` report against a volunteer in `ACTIVE`,
        `RESCREEN_REQUIRED`, or `CLEARANCE_GRANTED` suspends them on the spot:
        the volunteer's status becomes `SUSPENDED`, `prior_status` records the
        status held at the moment of suspension, and `suspension_incident_id`
        records the new report's `id` so the system remembers which incident
        caused the suspension."

        Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_volunteer_suspended
        """
        recruited = create_active_volunteer("Pending Polly", "polly@x.com",
                                            "SUPERVISED")
        vid = recruited["volunteer"]["id"]
        campus = create_lincoln_campus()
        opp = create_open_opportunity(campus["id"], capacity=2)
        placement = request_placement(opp["id"], vid)

        incident = file_incident(vid, severity="HIGH",
                                 description="Alleged altercation")

        suspended = get_volunteer(vid)
        assert suspended["status"] == "SUSPENDED"
        assert suspended["prior_status"] == "ACTIVE"
        assert suspended["suspension_incident_id"] == incident["id"]
        # The mere REQUESTED placement survives the suspension.
        assert get_placement(placement["id"])["status"] == "REQUESTED"

        confirm = api.confirm_placement(placement["id"], CA)
        validate_error(confirm, ApiErrorId.ERR_VOLUNTEER_INVALID_STATE)


class TestHalfOpenOverlap:
    def _overlap_setup(self):
        recruited = create_active_volunteer("Overlap Ollie", "ollie@x.com",
                                            "SUPERVISED")
        vid = recruited["volunteer"]["id"]
        campus = create_lincoln_campus()
        opp_a = create_open_opportunity(
            campus["id"], title="Shift A", capacity=2,
            starts_at="2026-08-10T14:00:00Z", ends_at="2026-08-10T17:00:00Z")
        opp_b = create_open_opportunity(
            campus["id"], title="Shift B", capacity=2,
            starts_at="2026-08-10T17:00:00Z", ends_at="2026-08-10T19:00:00Z")
        opp_c = create_open_opportunity(
            campus["id"], title="Shift C", capacity=2,
            starts_at="2026-08-10T16:00:00Z", ends_at="2026-08-10T18:00:00Z")
        pa = request_placement(opp_a["id"], vid)
        pb = request_placement(opp_b["id"], vid)
        pc = request_placement(opp_c["id"], vid)
        return vid, pa, pb, pc

    def test_adjacent_windows_do_not_conflict(self, api):
        """PRD: "then the temporal rule: the new placement's window must not
        overlap, under half-open semantics, any other `CONFIRMED` placement the
        volunteer holds — an overlap is rejected with
        `ERR_PLACEMENT_TIME_CONFLICT`, while two placements that merely touch,
        one's `ends_at` equal to the other's `starts_at`, are allowed"

        Design: Difficulty/resource_temporal_overlap/placement_overlap_half_open_adjacency
        """
        _, pa, pb, pc = self._overlap_setup()
        confirm_placement(pa["id"])

        # [17:00,19:00) touches [14:00,17:00) without intersecting it.
        adjacent = validate_success(api.confirm_placement(pb["id"], CA), 200)
        assert adjacent["status"] == "CONFIRMED"

        # [16:00,18:00) intersects both confirmed windows.
        overlap = api.confirm_placement(pc["id"], CA)
        validate_error(overlap, ApiErrorId.ERR_PLACEMENT_TIME_CONFLICT)
        assert get_placement(pc["id"])["status"] == "REQUESTED"

    def test_overlapping_window_confirm_rejected(self, api):
        """PRD: "then the temporal rule: the new placement's window must not
        overlap, under half-open semantics, any other `CONFIRMED` placement the
        volunteer holds — an overlap is rejected with
        `ERR_PLACEMENT_TIME_CONFLICT`, while two placements that merely touch,
        one's `ends_at` equal to the other's `starts_at`, are allowed"

        Design: Difficulty/resource_temporal_overlap/placement_overlap_half_open_adjacency
        """
        recruited = create_active_volunteer("Partial Paul", "paul@x.com",
                                            "SUPERVISED")
        vid = recruited["volunteer"]["id"]
        campus = create_lincoln_campus()
        opp_a = create_open_opportunity(
            campus["id"], title="Afternoon", capacity=2,
            starts_at="2026-08-10T14:00:00Z", ends_at="2026-08-10T17:00:00Z")
        opp_c = create_open_opportunity(
            campus["id"], title="Straddler", capacity=2,
            starts_at="2026-08-10T16:00:00Z", ends_at="2026-08-10T18:00:00Z")
        pa = request_placement(opp_a["id"], vid)
        pc = request_placement(opp_c["id"], vid)
        confirm_placement(pa["id"])

        overlap = api.confirm_placement(pc["id"], CA)
        validate_error(overlap, ApiErrorId.ERR_PLACEMENT_TIME_CONFLICT)
        assert get_placement(pc["id"])["status"] == "REQUESTED"
        assert get_placement(pa["id"])["status"] == "CONFIRMED"


class TestValidationPriority:
    def test_confirm_cancelled_restricted_placement_returns_state_error(self, api):
        """PRD: "Every request is evaluated against a fixed, ordered pipeline
        of validation stages, and the first stage that fails determines the
        error returned — later stages are never consulted once an earlier one
        has rejected the request."
        PRD: "The full pipeline of §2.7 applies: the placement must be
        `REQUESTED` (else `ERR_PLACEMENT_INVALID_STATE`)"

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_error_beats_safety_error
        """
        # Flagged UNSUPERVISED volunteer: the restriction gate would fail, but
        # the placement is CANCELLED, so the state stage rejects first.
        recruited = create_active_volunteer("Flag Fred", "fred@x.com",
                                            "UNSUPERVISED", findings="MINOR")
        vid = recruited["volunteer"]["id"]
        assert recruited["volunteer"]["restriction_flags"] == [
            "NO_ONE_ON_ONE", "NO_TRANSPORT"]
        campus = create_lincoln_campus()
        opp = create_open_opportunity(
            campus["id"], title="Reading Mentor",
            required_contact_type="UNSUPERVISED",
            restricted_category="ONE_ON_ONE", capacity=2)
        placement = request_placement(opp["id"], vid)
        validate_success(api.cancel_placement(
            placement["id"], make_volunteer_headers(vid)), 200)

        confirm = api.confirm_placement(placement["id"], CA)
        validate_error(confirm, ApiErrorId.ERR_PLACEMENT_INVALID_STATE)
        assert get_placement(placement["id"])["status"] == "CANCELLED"

    def test_confirm_cancelled_insufficient_clearance_returns_state_error(self, api):
        """PRD: "Every request is evaluated against a fixed, ordered pipeline
        of validation stages, and the first stage that fails determines the
        error returned — later stages are never consulted once an earlier one
        has rejected the request."
        PRD: "The full pipeline of §2.7 applies: the placement must be
        `REQUESTED` (else `ERR_PLACEMENT_INVALID_STATE`), its opportunity
        `OPEN` (else `ERR_OPPORTUNITY_INVALID_STATE`), and the volunteer
        `ACTIVE` (else `ERR_VOLUNTEER_INVALID_STATE`); then the three screening
        gates run in order"

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_error_beats_safety_error
        """
        # BASIC-cleared volunteer on an UNSUPERVISED opportunity: the
        # clearance gate would fail, but the placement is CANCELLED first.
        recruited = create_active_volunteer("Basic Bess", "bess@x.com",
                                            "SUPERVISED", level="BASIC")
        vid = recruited["volunteer"]["id"]
        campus = create_lincoln_campus()
        opp = create_open_opportunity(
            campus["id"], title="Solo Mentor",
            required_contact_type="UNSUPERVISED", capacity=2)
        placement = request_placement(opp["id"], vid)
        validate_success(api.cancel_placement(
            placement["id"], make_volunteer_headers(vid)), 200)

        confirm = api.confirm_placement(placement["id"], CA)
        validate_error(confirm, ApiErrorId.ERR_PLACEMENT_INVALID_STATE)
        assert get_placement(placement["id"])["status"] == "CANCELLED"


class TestPlacementCompletion:
    def test_complete_too_early_rejected(self, api):
        """PRD: "Completion, performed by a `CampusAdmin` or
        `DistrictCoordinator`, moves a `CONFIRMED` placement to the terminal
        `COMPLETED` status and requires two things: the current logical time
        must be at or after the opportunity's `ends_at` (completing earlier is
        rejected with `ERR_PLACEMENT_WINDOW_OPEN`), and at least one check-in
        linked to this placement must already be `CLOSED` (otherwise
        `ERR_NO_CHECKIN_FOR_PLACEMENT`)."

        Design: Corner/endpoints/complete_too_early_rejected
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="Early Earl", email="earl@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]

        set_clock("2026-08-10T14:00:00Z")
        visit = check_in_volunteer(scenario["campus"]["id"], vid,
                                   placement_id=placement["id"])
        check_out_volunteer(visit["id"], vid)

        # 16:00 is still before the 17:00 window end.
        set_clock("2026-08-10T16:00:00Z")
        complete = api.complete_placement(placement["id"], CA)
        validate_error(complete, ApiErrorId.ERR_PLACEMENT_WINDOW_OPEN)
        assert get_placement(placement["id"])["status"] == "CONFIRMED"

    def test_complete_without_checkin_rejected(self, api):
        """PRD: "Completion, performed by a `CampusAdmin` or
        `DistrictCoordinator`, moves a `CONFIRMED` placement to the terminal
        `COMPLETED` status and requires two things: the current logical time
        must be at or after the opportunity's `ends_at` (completing earlier is
        rejected with `ERR_PLACEMENT_WINDOW_OPEN`), and at least one check-in
        linked to this placement must already be `CLOSED` (otherwise
        `ERR_NO_CHECKIN_FOR_PLACEMENT`)."

        Design: Corner/endpoints/complete_without_checkin_rejected
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="NoShow Nina", email="nina@x.com")
        placement = scenario["placement"]
        opp = scenario["opportunity"]

        # Past the window end; the sweep completes the opportunity itself.
        set_clock("2026-08-11T00:00:00Z")
        assert get_opportunity(opp["id"])["status"] == "COMPLETED"

        complete = api.complete_placement(placement["id"], CA)
        validate_error(complete, ApiErrorId.ERR_NO_CHECKIN_FOR_PLACEMENT)
        assert get_placement(placement["id"])["status"] == "CONFIRMED"


class TestSeatConservation:
    def test_confirm_then_cancel_conserves_seat_counts(self, api):
        """PRD: "Releasing a `CONFIRMED` seat recomputes the opportunity's
        `committed_count` and `projected_count`, and the placement's `version`
        increments by one."
        PRD: "when the owning volunteer cancels, `cancel_reason` records
        `VOLUNTEER_WITHDRAW`; when a `CampusAdmin` or `DistrictCoordinator`
        cancels, it records `ADMIN_CANCEL`."

        Design: Difficulty/compensating_invariant/seat_conservation_confirm_then_cancel
        """
        module = create_orient_module()
        campus = create_lincoln_campus()
        opp = create_open_opportunity(campus["id"], title="Two Seats",
                                      capacity=2)
        v1 = create_active_volunteer("Seat One", "one@x.com", "SUPERVISED",
                                     module=module)["volunteer"]
        v2 = create_active_volunteer("Seat Two", "two@x.com", "SUPERVISED",
                                     module=module)["volunteer"]
        p1 = request_placement(opp["id"], v1["id"])
        confirm_placement(p1["id"])
        p2 = request_placement(opp["id"], v2["id"])
        confirm_placement(p2["id"])
        assert get_opportunity(opp["id"])["committed_count"] == 2

        validate_success(api.cancel_placement(
            p1["id"], make_volunteer_headers(v1["id"])), 200)

        after = get_opportunity(opp["id"])
        assert after["committed_count"] == 1
        assert after["projected_count"] == 1

        confirmed, meta = validate_paginated(api.list_placements(
            CA, params={"opportunity_id": opp["id"], "status": "CONFIRMED"}))
        assert meta["total_count"] == 1, (
            "committed_count equals the live CONFIRMED set cardinality")
        assert confirmed[0]["id"] == p2["id"]

        cancelled = get_placement(p1["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "VOLUNTEER_WITHDRAW"

    def test_cancel_confirmed_releases_seat_and_sets_reason(self, api):
        """PRD: "Cancellation is available from either `REQUESTED` or
        `CONFIRMED` (any other status is rejected with
        `ERR_PLACEMENT_INVALID_STATE`) and moves the placement to the terminal
        `CANCELLED` status: when the owning volunteer cancels, `cancel_reason`
        records `VOLUNTEER_WITHDRAW`; when a `CampusAdmin` or
        `DistrictCoordinator` cancels, it records `ADMIN_CANCEL`."
        PRD: "Releasing a `CONFIRMED` seat recomputes the opportunity's
        `committed_count` and `projected_count`, and the placement's `version`
        increments by one."

        Design: Difficulty/compensating_invariant/seat_conservation_confirm_then_cancel
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="Admin Cancel", email="admin.cancel@x.com")
        placement = scenario["placement"]
        opp = scenario["opportunity"]
        version_before = get_placement(placement["id"])["version"]

        cancelled = validate_success(
            api.cancel_placement(placement["id"], CA), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "ADMIN_CANCEL"
        assert cancelled["version"] == version_before + 1

        after = get_opportunity(opp["id"])
        assert after["committed_count"] == 0
        assert after["projected_count"] == 0
