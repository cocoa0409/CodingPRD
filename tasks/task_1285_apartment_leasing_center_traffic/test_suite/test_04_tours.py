"""Tours: guided/self-guided field rules, availability sync, buffered-interval
capacity, reschedule revalidation, listing filters, and validation priority."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_same_instant,
    create_agent,
    create_contacted_inquiry,
    create_floorplan,
    create_guided_tour,
    create_inquiry,
    create_property,
    create_tour_payload,
    get_inquiry,
    get_tour,
    make_leasing_agent_headers,
    mark_inquiry_lost,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["property_manager_headers"]

T1_START = "2026-08-10T10:00:00Z"
T1_END = "2026-08-10T11:00:00Z"


def _tour_site(code, buffer=15, max_concurrent=1, total_units=3):
    prop = create_property(name=f"Site {code}", code=code, tour_buffer_minutes=buffer)
    agent = create_agent(prop["id"], max_concurrent_tours=max_concurrent)
    floorplan = create_floorplan(prop["id"], total_units=total_units)
    return prop, agent, floorplan


def _contacted(prop, agent, floorplan, name, email, source="WEB_FORM"):
    return create_contacted_inquiry(prop["id"], agent["id"],
                                    floorplan_id=floorplan["id"],
                                    contact_name=name, contact_email=email,
                                    source=source)


class TestSelfGuidedFieldRules:
    def test_self_guided_tour_end_computed_from_property_window(self, api):
        """PRD §3.3: "For a `SELF_GUIDED` tour `agent_id` must be omitted, and the
        server computes `scheduled_end` as `scheduled_start` plus the property's
        `self_guided_window_minutes`, ignoring any client-supplied value; mixing the
        fields up — an agent on a self-guided tour or none on a guided one — is an
        `ERR_INVALID_REQUEST`."
        PRD §3.3: "When the inquiry is `CONTACTED`, creating the tour advances it to
        `TOUR_SCHEDULED` automatically."

        Design: Corner/entities/self_guided_tour_end_computed_from_property_window
        """
        prop = create_property(name="Self Tour Lofts", code="SG1",
                               self_guided_window_minutes=60)
        agent = create_agent(prop["id"], full_name="SA", email="sa@x.com")
        floorplan = create_floorplan(prop["id"], name="Studio", bedrooms=0,
                                     base_rent_cents=150000, total_units=1)
        inquiry = _contacted(prop, agent, floorplan, "SG", "sg@x.com")

        resp = api.create_tour(
            {"inquiry_id": inquiry["id"], "tour_type": "SELF_GUIDED",
             "scheduled_start": "2026-08-10T10:00:00Z"},
            make_leasing_agent_headers(agent["id"]))
        tour = validate_success(resp, 201)
        assert_same_instant(tour["scheduled_end"], "2026-08-10T11:00:00Z",
                            label="Tour.scheduled_end")
        assert tour.get("agent_id") is None
        assert get_inquiry(inquiry["id"])["status"] == "TOUR_SCHEDULED"

    def test_self_guided_tour_with_agent_id_rejected(self, api):
        """PRD §3.3: "For a `SELF_GUIDED` tour `agent_id` must be omitted, and the
        server computes `scheduled_end` as `scheduled_start` plus the property's
        `self_guided_window_minutes`, ignoring any client-supplied value; mixing the
        fields up — an agent on a self-guided tour or none on a guided one — is an
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/self_guided_tour_with_agent_id_rejected
        """
        prop = create_property(name="Cond Field Court", code="CF1")
        agent = create_agent(prop["id"], full_name="CA", email="cfa@x.com")
        floorplan = create_floorplan(prop["id"], base_rent_cents=150000, total_units=1)
        inquiry = _contacted(prop, agent, floorplan, "CF", "cf@x.com", "PHONE")

        resp = api.create_tour(
            {"inquiry_id": inquiry["id"], "tour_type": "SELF_GUIDED",
             "agent_id": agent["id"], "scheduled_start": "2026-08-10T10:00:00Z"},
            make_leasing_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestTourExistenceAndAvailability:
    def test_tour_create_with_unknown_inquiry_returns_not_found(self, api,
                                                                leasing_agent_headers):
        """PRD §2.10: "Third, existence and request shape: path identifiers are
        resolved and each body reference must point at an existing resource — a
        missing property, agent, floorplan, pricing offer, inquiry, tour, waitlist
        entry, application, lease, or move-in surfaces `ERR_PROPERTY_NOT_FOUND`,
        `ERR_AGENT_NOT_FOUND`, `ERR_FLOORPLAN_NOT_FOUND`,
        `ERR_PRICING_OFFER_NOT_FOUND`, `ERR_INQUIRY_NOT_FOUND`, `ERR_TOUR_NOT_FOUND`,
        `ERR_WAITLIST_ENTRY_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
        `ERR_LEASE_NOT_FOUND`, or `ERR_MOVE_IN_NOT_FOUND` respectively;"

        Design: Corner/entities/tour_create_with_unknown_inquiry_returns_not_found
        """
        resp = api.create_tour(
            {"inquiry_id": NON_EXISTENT_UUID, "tour_type": "SELF_GUIDED",
             "scheduled_start": "2026-08-10T10:00:00Z"},
            leasing_agent_headers)
        validate_error(resp, ApiErrorId.ERR_INQUIRY_NOT_FOUND, 404)

    def test_self_guided_tour_requires_available_unit(self, api):
        """PRD §3.3: "A self-guided booking additionally requires the floorplan of
        interest to have at least one unit available; while that floorplan's
        `available_units` is zero, the request is rejected with
        `ERR_SELF_GUIDED_NO_UNIT`."

        Design: Corner/validations/self_guided_tour_requires_available_unit
        """
        prop = create_property(name="Sync Square", code="SS1")
        agent = create_agent(prop["id"], full_name="SyA", email="sya@x.com")
        floorplan = create_floorplan(prop["id"], name="Future 1BR", total_units=0)
        inquiry = _contacted(prop, agent, floorplan, "SS", "ss@x.com")

        resp = api.create_tour(
            {"inquiry_id": inquiry["id"], "tour_type": "SELF_GUIDED",
             "scheduled_start": "2026-08-10T10:00:00Z"},
            make_leasing_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_SELF_GUIDED_NO_UNIT)

        # The availability gate is specific to self-guided tours: a guided tour on
        # the same sold-out floorplan books normally.
        tour = create_guided_tour(inquiry["id"], agent["id"],
                                  "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        assert tour["status"] == "SCHEDULED"

    def test_tour_with_end_before_start_returns_invalid_time_range(self, api):
        """PRD §3.3: "For a `GUIDED` tour an `agent_id` is required and the client
        supplies `scheduled_end`, which must fall strictly after `scheduled_start`
        (`ERR_INVALID_TIME_RANGE`)."

        Design: Corner/validations/tour_with_end_before_start_returns_invalid_time_range
        """
        prop, agent, floorplan = _tour_site("RR1", total_units=2)
        inquiry = _contacted(prop, agent, floorplan, "RR", "rr@x.com", "PHONE")

        resp = api.create_tour(
            {"inquiry_id": inquiry["id"], "tour_type": "GUIDED",
             "agent_id": agent["id"], "scheduled_start": "2026-08-10T10:00:00Z",
             "scheduled_end": "2026-08-10T10:00:00Z"},
            make_leasing_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE, 400)


class TestTourOutcomes:
    def test_tour_no_show_reverts_inquiry_to_contacted(self, api):
        """PRD §3.3: "The two outcomes differ in their cross-entity effect: a plain
        completion leaves the inquiry where it is, while a `NO_SHOW` reverts the
        inquiry from `TOUR_SCHEDULED` to `CONTACTED` when no other `SCHEDULED` tour
        remains for it."

        Design: Corner/state_machines/tour_no_show_reverts_inquiry_to_contacted
        """
        prop, agent, floorplan = _tour_site("NS1", total_units=2)
        inquiry = _contacted(prop, agent, floorplan, "NS", "ns2@x.com")
        tour = create_guided_tour(inquiry["id"], agent["id"], T1_START, T1_END)
        assert get_inquiry(inquiry["id"])["status"] == "TOUR_SCHEDULED"

        resp = api.complete_tour(tour["id"], "NO_SHOW",
                                 make_leasing_agent_headers(agent["id"]))
        assert validate_success(resp)["status"] == "NO_SHOW"
        assert get_inquiry(inquiry["id"])["status"] == "CONTACTED"

    def test_tour_complete_from_cancelled_returns_invalid_state(self, api):
        """PRD §3.3: "Recording an outcome takes an `outcome` of `COMPLETED` or
        `NO_SHOW`, from `SCHEDULED` only (`ERR_TOUR_INVALID_STATE`)."

        Design: Corner/state_machines/tour_complete_from_cancelled_returns_invalid_state
        """
        prop, agent, floorplan = _tour_site("TC1", total_units=2)
        inquiry = _contacted(prop, agent, floorplan, "TC", "tc@x.com", "PHONE")
        tour = create_guided_tour(inquiry["id"], agent["id"], T1_START, T1_END)
        cancel_resp = api.cancel_tour(tour["id"],
                                      make_leasing_agent_headers(agent["id"]))
        assert validate_success(cancel_resp)["status"] == "CANCELLED"

        resp = api.complete_tour(tour["id"], "COMPLETED",
                                 make_leasing_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_TOUR_INVALID_STATE)
        assert get_tour(tour["id"])["status"] == "CANCELLED"


class TestReschedule:
    def test_reschedule_revalidates_availability(self, api):
        """PRD §3.3: "Rescheduling is a self-loop from `SCHEDULED` back to
        `SCHEDULED`: the client submits a new `scheduled_start` and, for guided
        tours, a new `scheduled_end`, the tour's interval is replaced, the inquiry
        stays `TOUR_SCHEDULED`, and the new interval must pass the same availability
        rules as creation — the conflict check, the self-guided unit check, and the
        end-after-start check all apply again."

        Design: Corner/endpoints/reschedule_revalidates_availability
        """
        prop, agent, floorplan = _tour_site("RS1")
        inquiry1 = _contacted(prop, agent, floorplan, "R1", "rs1@x.com")
        tour1 = create_guided_tour(inquiry1["id"], agent["id"], T1_START, T1_END)
        inquiry2 = _contacted(prop, agent, floorplan, "R2", "rs2@x.com", "PHONE")
        tour2 = create_guided_tour(inquiry2["id"], agent["id"],
                                   "2026-08-10T14:00:00Z", "2026-08-10T15:00:00Z")

        # Moving tour2 into tour1's blocked window is rejected and changes nothing.
        resp = api.reschedule_tour(
            tour2["id"],
            {"scheduled_start": "2026-08-10T10:30:00Z",
             "scheduled_end": "2026-08-10T11:30:00Z"},
            make_leasing_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_TOUR_TIME_CONFLICT)
        assert_same_instant(get_tour(tour2["id"])["scheduled_start"],
                            "2026-08-10T14:00:00Z", label="scheduled_start")

        # Moving it to a free slot succeeds and replaces the interval.
        ok = api.reschedule_tour(
            tour2["id"],
            {"scheduled_start": "2026-08-10T16:00:00Z",
             "scheduled_end": "2026-08-10T17:00:00Z"},
            make_leasing_agent_headers(agent["id"]))
        moved = validate_success(ok)
        assert moved["status"] == "SCHEDULED"
        assert_same_instant(moved["scheduled_start"], "2026-08-10T16:00:00Z",
                            label="rescheduled start")


class TestTourListing:
    def test_tours_filtered_by_agent_returns_only_matching(self, api,
                                                           property_manager_headers):
        """PRD §3.3: "Tours can be listed with `inquiry_id`, `agent_id`, and
        `status` filters."

        Design: Corner/endpoints/tours_filtered_by_agent_returns_only_matching
        """
        prop = create_property(name="Filter Flats", code="FL1")
        agent1 = create_agent(prop["id"], full_name="F One", email="f1@x.com")
        agent2 = create_agent(prop["id"], full_name="F Two", email="f2@x.com")
        floorplan = create_floorplan(prop["id"], total_units=3)
        inquiry1 = create_contacted_inquiry(prop["id"], agent1["id"],
                                            floorplan_id=floorplan["id"],
                                            contact_name="F1", contact_email="fl1@x.com")
        tour1 = create_guided_tour(inquiry1["id"], agent1["id"],
                                   "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        inquiry2 = create_contacted_inquiry(prop["id"], agent2["id"],
                                            floorplan_id=floorplan["id"],
                                            contact_name="F2", contact_email="fl2@x.com",
                                            source="PHONE")
        tour2 = create_guided_tour(inquiry2["id"], agent2["id"],
                                   "2026-08-11T10:00:00Z", "2026-08-11T11:00:00Z")

        by_agent, _ = validate_paginated(api.list_tours(
            property_manager_headers, params={"agent_id": agent1["id"]}))
        assert [t["id"] for t in by_agent] == [tour1["id"]]

        by_inquiry, _ = validate_paginated(api.list_tours(
            property_manager_headers, params={"inquiry_id": inquiry2["id"]}))
        assert [t["id"] for t in by_inquiry] == [tour2["id"]]


class TestGuidedTourBufferBoundary:
    def test_guided_tour_gap_exactly_buffer_is_allowed(self, api):
        """PRD §3.3: "Each scheduled tour blocks its interval plus the property's
        `tour_buffer_minutes` of turnaround, and an agent may hold at most
        `max_concurrent_tours` overlapping blocked intervals; a guided booking whose
        blocked window would collide with the blocked windows of
        `max_concurrent_tours` or more of the agent's existing `SCHEDULED` tours is
        rejected with `ERR_TOUR_TIME_CONFLICT`."

        Design: Difficulty/boundary_precision_check/guided_tour_gap_equal_buffer_allowed_one_less_rejected
        """
        prop, agent, floorplan = _tour_site("BV1")
        inquiry1 = _contacted(prop, agent, floorplan, "B1", "b1@x.com", "PHONE")
        create_guided_tour(inquiry1["id"], agent["id"], T1_START, T1_END)
        inquiry2 = _contacted(prop, agent, floorplan, "B2", "b2@x.com", "PHONE")

        # Starting exactly tour_buffer_minutes (15) after the prior tour's end does
        # not collide with its blocked window.
        tour2 = create_guided_tour(inquiry2["id"], agent["id"],
                                   "2026-08-10T11:15:00Z", "2026-08-10T12:00:00Z")
        assert tour2["status"] == "SCHEDULED"
        assert get_inquiry(inquiry2["id"])["status"] == "TOUR_SCHEDULED"

    def test_guided_tour_gap_one_minute_under_buffer_rejected(self, api):
        """PRD §3.3: "Each scheduled tour blocks its interval plus the property's
        `tour_buffer_minutes` of turnaround, and an agent may hold at most
        `max_concurrent_tours` overlapping blocked intervals; a guided booking whose
        blocked window would collide with the blocked windows of
        `max_concurrent_tours` or more of the agent's existing `SCHEDULED` tours is
        rejected with `ERR_TOUR_TIME_CONFLICT`."

        Design: Difficulty/boundary_precision_check/guided_tour_gap_equal_buffer_allowed_one_less_rejected
        """
        prop, agent, floorplan = _tour_site("BV2")
        inquiry1 = _contacted(prop, agent, floorplan, "B1", "b1@x.com", "PHONE")
        create_guided_tour(inquiry1["id"], agent["id"], T1_START, T1_END)
        inquiry3 = _contacted(prop, agent, floorplan, "B3", "b3@x.com", "PHONE")

        # A 14-minute gap falls inside the prior tour's blocked window (end + 15).
        resp = api.create_tour(
            create_tour_payload(inquiry3["id"], agent_id=agent["id"],
                                scheduled_start="2026-08-10T11:14:00Z",
                                scheduled_end="2026-08-10T12:14:00Z"),
            make_leasing_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_TOUR_TIME_CONFLICT)
        assert get_inquiry(inquiry3["id"])["status"] == "CONTACTED", \
            "a rejected booking must not advance the inquiry"


class TestGuidedTourCapacity:
    def test_guided_tour_overlap_within_capacity_allowed(self, api):
        """PRD §3.3: "Each scheduled tour blocks its interval plus the property's
        `tour_buffer_minutes` of turnaround, and an agent may hold at most
        `max_concurrent_tours` overlapping blocked intervals; a guided booking whose
        blocked window would collide with the blocked windows of
        `max_concurrent_tours` or more of the agent's existing `SCHEDULED` tours is
        rejected with `ERR_TOUR_TIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/guided_tour_capacity_allows_overlap_up_to_max
        """
        prop, agent, floorplan = _tour_site("CC1", max_concurrent=2)
        inquiry1 = _contacted(prop, agent, floorplan, "C1", "c1@x.com")
        inquiry2 = _contacted(prop, agent, floorplan, "C2", "c2@x.com")

        tour1 = create_guided_tour(inquiry1["id"], agent["id"],
                                   "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        # Two mutually overlapping blocked windows are within capacity 2.
        tour2 = create_guided_tour(inquiry2["id"], agent["id"],
                                   "2026-08-10T10:30:00Z", "2026-08-10T11:30:00Z")
        assert get_tour(tour1["id"])["status"] == "SCHEDULED"
        assert tour2["status"] == "SCHEDULED"

    def test_guided_tour_overlap_beyond_capacity_rejected(self, api):
        """PRD §3.3: "Each scheduled tour blocks its interval plus the property's
        `tour_buffer_minutes` of turnaround, and an agent may hold at most
        `max_concurrent_tours` overlapping blocked intervals; a guided booking whose
        blocked window would collide with the blocked windows of
        `max_concurrent_tours` or more of the agent's existing `SCHEDULED` tours is
        rejected with `ERR_TOUR_TIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/guided_tour_capacity_allows_overlap_up_to_max
        """
        prop, agent, floorplan = _tour_site("CC2", max_concurrent=2)
        inquiry1 = _contacted(prop, agent, floorplan, "C1", "c1@x.com")
        create_guided_tour(inquiry1["id"], agent["id"],
                           "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        inquiry2 = _contacted(prop, agent, floorplan, "C2", "c2@x.com")
        create_guided_tour(inquiry2["id"], agent["id"],
                           "2026-08-10T10:30:00Z", "2026-08-10T11:30:00Z")
        inquiry3 = _contacted(prop, agent, floorplan, "C3", "c3@x.com")

        # The third overlapping booking collides with 2 existing blocked windows,
        # reaching the max_concurrent_tours ceiling.
        resp = api.create_tour(
            create_tour_payload(inquiry3["id"], agent_id=agent["id"],
                                scheduled_start="2026-08-10T10:45:00Z",
                                scheduled_end="2026-08-10T11:45:00Z"),
            make_leasing_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_TOUR_TIME_CONFLICT)


class TestValidationPriority:
    def test_tour_create_inquiry_lost_beats_time_conflict(self, api):
        """PRD §2.10: "Every request is validated in a fixed order, and the first
        failing check determines the response."
        PRD §2.10: "Fourth, state checks: the per-entity invalid-state family
        (`ERR_INQUIRY_INVALID_STATE`, `ERR_TOUR_INVALID_STATE`,
        `ERR_WAITLIST_INVALID_STATE`, `ERR_APPLICATION_INVALID_STATE`,
        `ERR_LEASE_INVALID_STATE`, `ERR_MOVEIN_INVALID_STATE`,
        `ERR_PRICING_OFFER_INVALID_STATE`), the pipeline-gating errors
        (`ERR_INQUIRY_NOT_ACTIVE`, `ERR_APPLICATION_NOT_LEASABLE`,
        `ERR_LEASE_NOT_EXECUTED`), a repeat first response (`ERR_ALREADY_RESPONDED`),
        and the stale-version rejection (`ERR_STALE_VERSION`). Seventh, interval and
        capacity rules: agent calendar conflicts (`ERR_TOUR_TIME_CONFLICT`), the
        daily move-in cap (`ERR_MOVEIN_DAY_FULL`), and end-after-start window rules
        (`ERR_INVALID_TIME_RANGE`)."

        Design: Difficulty/priority_pair_validation_conflict/tour_create_inquiry_lost_beats_time_conflict
        """
        prop, agent, floorplan = _tour_site("PP1", total_units=2)
        inquiry1 = _contacted(prop, agent, floorplan, "P1", "p1@x.com", "PHONE")
        create_guided_tour(inquiry1["id"], agent["id"], T1_START, T1_END)
        inquiry2 = create_contacted_inquiry(prop["id"], agent["id"],
                                            floorplan_id=floorplan["id"],
                                            contact_name="P2", contact_email="p2@x.com")
        mark_inquiry_lost(inquiry2["id"], agent["id"])

        # The request violates both the inquiry-state gate (LOST, fourth) and the
        # agent's buffered-interval rule (seventh); the state error must win.
        resp = api.create_tour(
            create_tour_payload(inquiry2["id"], agent_id=agent["id"],
                                scheduled_start="2026-08-10T10:30:00Z",
                                scheduled_end="2026-08-10T11:30:00Z"),
            make_leasing_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_INQUIRY_NOT_ACTIVE)

        data, _ = validate_paginated(
            api.list_tours(PM, params={"inquiry_id": inquiry2["id"]}))
        assert data == [], "a rejected booking must not persist a tour"

    def test_tour_create_against_lost_inquiry_rejected(self, api):
        """PRD §3.3: "Booking against an inquiry in `LOST` or `CONVERTED` is
        rejected with `ERR_INQUIRY_NOT_ACTIVE`, whatever the tour type."

        Design: Difficulty/priority_pair_validation_conflict/tour_create_inquiry_lost_beats_time_conflict
        """
        prop, agent, floorplan = _tour_site("PP2", total_units=2)
        inquiry = create_contacted_inquiry(prop["id"], agent["id"],
                                           floorplan_id=floorplan["id"],
                                           contact_name="P2", contact_email="p2@x.com")
        mark_inquiry_lost(inquiry["id"], agent["id"])

        resp = api.create_tour(
            create_tour_payload(inquiry["id"], agent_id=agent["id"],
                                scheduled_start="2026-08-12T10:00:00Z",
                                scheduled_end="2026-08-12T11:00:00Z"),
            make_leasing_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_INQUIRY_NOT_ACTIVE)
