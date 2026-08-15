"""Milestone half-open windows and property construction capacity (closed)."""
from test_helpers import (
    ApiErrorId,
    create_active_engagement,
    create_active_lease,
    create_lease_space_record,
    create_milestone_record,
    create_property_record,
    create_qualified_contractor,
    create_tenant_record,
    drive_lease_to_pre_construction,
    drive_project_to_construction,
    get_success_data,
    set_logical_clock,
    setup_project_in_construction,
    make_contractor_rep_headers,
    validate_error,
    validate_success,
)


class TestMilestoneAdjacencyBoundary:
    def test_milestone_adjacency_vs_overlap_half_open(self, api, landlord_pm_headers):
        """PRD 3.4: "Two windows on the same engagement in `PLANNED` or
        `CONFIRMED` may not intersect: they conflict when the existing window
        starts before the new window ends and the new window starts before the
        existing window ends, while mere adjacency — one window ending at
        exactly the instant the next begins — does not count as an
        intersection; a genuine conflict is rejected with
        `ERR_SCHEDULE_OVERLAP` (HTTP 409)". PRD 3.4: "A `STANDARD` window is
        confirmed immediately at creation, transitioning straight to
        `CONFIRMED`".

        Design: Difficulty/boundary_precision_check/milestone_adjacency_vs_overlap_half_open
        """
        sc = setup_project_in_construction()
        eng_id = sc["engagement"]["id"]
        ctr = sc["contractor"]["id"]

        m1 = create_milestone_record(
            eng_id, ctr,
            milestone_name="Demolition",
            window_start="2026-08-03T00:00:00Z",
            window_end="2026-08-14T00:00:00Z",
            work_type="STANDARD",
        )
        assert m1["status"] == "CONFIRMED", "STANDARD windows auto-confirm at creation"

        # Adjacent at exactly the prior window's end: accepted.
        m2 = validate_success(
            api.create_milestone(
                eng_id,
                {
                    "milestone_name": "Framing",
                    "window_start": "2026-08-14T00:00:00Z",
                    "window_end": "2026-08-28T00:00:00Z",
                    "work_type": "STANDARD",
                },
                make_contractor_rep_headers(ctr),
            ),
            201,
        )
        assert m2["status"] == "CONFIRMED", (
            "adjacency (window_end == window_start) is not an overlap"
        )

        # One millisecond before the prior window's end: a real overlap.
        resp = api.create_milestone(
            eng_id,
            {
                "milestone_name": "Overlap attempt",
                "window_start": "2026-08-13T23:59:59.999Z",
                "window_end": "2026-08-20T00:00:00Z",
                "work_type": "NOISY",
            },
            make_contractor_rep_headers(ctr),
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_OVERLAP)

    def test_cancelled_milestones_ignored_by_overlap(self, api, landlord_pm_headers):
        """PRD 3.4: "`COMPLETED` and `CANCELLED` milestones are ignored by the
        overlap computation." PRD 3.4: "Two windows on the same engagement in
        `PLANNED` or `CONFIRMED` may not intersect".

        Design: Difficulty/boundary_precision_check/milestone_adjacency_vs_overlap_half_open
        """
        sc = setup_project_in_construction()
        eng_id = sc["engagement"]["id"]
        ctr = sc["contractor"]["id"]

        m1 = create_milestone_record(
            eng_id, ctr,
            milestone_name="Demolition",
            window_start="2026-08-03T00:00:00Z",
            window_end="2026-08-14T00:00:00Z",
            work_type="STANDARD",
        )
        assert m1["status"] == "CONFIRMED"
        cancelled = get_success_data(api.cancel_milestone(m1["id"], landlord_pm_headers))
        assert cancelled["status"] == "CANCELLED"

        # A window squarely inside the cancelled one's span must now be free.
        m2 = validate_success(
            api.create_milestone(
                eng_id,
                {
                    "milestone_name": "Interior after cancel",
                    "window_start": "2026-08-10T00:00:00Z",
                    "window_end": "2026-08-12T00:00:00Z",
                    "work_type": "NOISY",
                },
                make_contractor_rep_headers(ctr),
            ),
            201,
        )
        assert m2["status"] == "PLANNED", "NOISY windows await landlord confirmation"


class TestMilestoneOverlapOnEngagement:
    def test_milestone_half_open_overlap_on_engagement(self, api, landlord_pm_headers):
        """PRD 3.4: "Two windows on the same engagement in `PLANNED` or
        `CONFIRMED` may not intersect: they conflict when the existing window
        starts before the new window ends and the new window starts before the
        existing window ends, while mere adjacency — one window ending at
        exactly the instant the next begins — does not count as an
        intersection; a genuine conflict is rejected with
        `ERR_SCHEDULE_OVERLAP` (HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/milestone_half_open_overlap_on_engagement
        """
        sc = setup_project_in_construction()
        eng_id = sc["engagement"]["id"]
        ctr = sc["contractor"]["id"]

        m1 = create_milestone_record(
            eng_id, ctr,
            milestone_name="Core drilling",
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
            work_type="NOISY",
        )
        assert m1["status"] == "PLANNED"
        m1 = get_success_data(api.confirm_milestone(m1["id"], landlord_pm_headers))
        assert m1["status"] == "CONFIRMED"

        # Interior intersection with the CONFIRMED window: rejected.
        resp = api.create_milestone(
            eng_id,
            {
                "milestone_name": "Overlapping noisy",
                "window_start": "2026-08-15T00:00:00Z",
                "window_end": "2026-08-25T00:00:00Z",
                "work_type": "NOISY",
            },
            make_contractor_rep_headers(ctr),
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_OVERLAP)

        # Adjacent at the confirmed window's end: accepted, still PLANNED.
        m2 = validate_success(
            api.create_milestone(
                eng_id,
                {
                    "milestone_name": "Adjacent noisy",
                    "window_start": "2026-08-20T00:00:00Z",
                    "window_end": "2026-08-27T00:00:00Z",
                    "work_type": "NOISY",
                },
                make_contractor_rep_headers(ctr),
            ),
            201,
        )
        assert m2["status"] == "PLANNED"

    def test_reverse_adjacency_accepted(self, api, landlord_pm_headers):
        """PRD 3.4: "they conflict when the existing window starts before the
        new window ends and the new window starts before the existing window
        ends, while mere adjacency — one window ending at exactly the instant
        the next begins — does not count as an intersection".

        Design: Difficulty/resource_temporal_overlap/milestone_half_open_overlap_on_engagement
        """
        sc = setup_project_in_construction()
        eng_id = sc["engagement"]["id"]
        ctr = sc["contractor"]["id"]

        m1 = create_milestone_record(
            eng_id, ctr,
            milestone_name="Core drilling",
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
            work_type="NOISY",
        )
        m1 = get_success_data(api.confirm_milestone(m1["id"], landlord_pm_headers))
        assert m1["status"] == "CONFIRMED"

        # New window ENDS exactly when the existing one begins: not an overlap.
        m2 = validate_success(
            api.create_milestone(
                eng_id,
                {
                    "milestone_name": "Leading adjacent",
                    "window_start": "2026-08-01T00:00:00Z",
                    "window_end": "2026-08-10T00:00:00Z",
                    "work_type": "NOISY",
                },
                make_contractor_rep_headers(ctr),
            ),
            201,
        )
        assert m2["status"] == "PLANNED", (
            "a window ending exactly at the existing window's start is adjacent, not overlapping"
        )


class TestPropertyCapacityClosedInterval:
    def _two_projects_on_one_property(self, capacity):
        """Two leases on one property, each with a project in PRE_CONSTRUCTION,
        sharing one QUALIFIED contractor."""
        prop = create_property_record(max_concurrent_construction_projects=capacity)
        space_a = create_lease_space_record(prop["id"], suite_number="210")
        space_b = create_lease_space_record(prop["id"], suite_number="220")
        tenant_a = create_tenant_record()
        tenant_b = create_tenant_record()
        lease_a = create_active_lease(space_a["id"], tenant_a["id"])
        lease_b = create_active_lease(space_b["id"], tenant_b["id"])
        a = drive_lease_to_pre_construction(lease_a, tenant_a)
        b = drive_lease_to_pre_construction(lease_b, tenant_b)
        contractor = create_qualified_contractor()
        return prop, a, b, contractor

    def test_property_concurrent_construction_capacity_closed_interval(
        self, api, landlord_pm_headers
    ):
        """PRD 3.4: "the server counts the project's siblings — other TI
        projects on the same property, reached through their leases' spaces,
        currently in `CONSTRUCTION` — whose closed windows intersect the
        requested one, where two closed windows intersect when the sibling's
        start falls on or before the requested end and the requested start
        falls on or before the sibling's end; if that count already equals or
        exceeds the property's `max_concurrent_construction_projects`, the
        start is rejected with `ERR_PROPERTY_CONSTRUCTION_CAPACITY` (HTTP
        409)".

        Design: Difficulty/resource_temporal_overlap/property_concurrent_construction_capacity_closed_interval
        """
        prop, a, b, contractor = self._two_projects_on_one_property(capacity=1)
        a = {**a, **drive_project_to_construction(a["project"], contractor)}
        assert a["project"]["status"] == "CONSTRUCTION"
        create_active_engagement(b["project"]["id"], contractor["id"])

        # Project B's window shares exactly the boundary day 2026-09-04 with A's.
        resp = api.start_construction(
            b["project"]["id"],
            {
                "construction_start_date": "2026-09-04T00:00:00Z",
                "construction_end_date": "2026-09-30T00:00:00Z",
            },
            landlord_pm_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PROPERTY_CONSTRUCTION_CAPACITY)
        b_after = get_success_data(api.get_project(b["project"]["id"], landlord_pm_headers))
        assert b_after["status"] == "PRE_CONSTRUCTION"
        a_after = get_success_data(api.get_project(a["project"]["id"], landlord_pm_headers))
        assert a_after["status"] == "CONSTRUCTION"

    def test_non_overlapping_window_within_capacity_permitted(self, api, landlord_pm_headers):
        """PRD 3.4: "two closed windows intersect when the sibling's start
        falls on or before the requested end and the requested start falls on
        or before the sibling's end; if that count already equals or exceeds
        the property's `max_concurrent_construction_projects`, the start is
        rejected with `ERR_PROPERTY_CONSTRUCTION_CAPACITY` (HTTP 409), and the
        start is permitted only while the conflict count stays strictly below
        the cap."

        Design: Difficulty/resource_temporal_overlap/property_concurrent_construction_capacity_closed_interval
        """
        prop, a, b, contractor = self._two_projects_on_one_property(capacity=1)
        a = {**a, **drive_project_to_construction(a["project"], contractor)}
        assert a["project"]["status"] == "CONSTRUCTION"
        create_active_engagement(b["project"]["id"], contractor["id"])

        # 2026-09-05 is strictly after A's end 2026-09-04: no closed-interval hit.
        started = validate_success(
            api.start_construction(
                b["project"]["id"],
                {
                    "construction_start_date": "2026-09-05T00:00:00Z",
                    "construction_end_date": "2026-09-30T00:00:00Z",
                },
                landlord_pm_headers,
            ),
            200,
        )
        assert started["status"] == "CONSTRUCTION", (
            "a window disjoint from the sibling's closed window stays below the cap"
        )


class TestMilestoneTemporalGates:
    def test_milestone_complete_before_window_end_rejected(self, api, landlord_pm_headers):
        """PRD 3.4: "Completion moves `CONFIRMED` → `COMPLETED` and is the
        contractor's own attestation: the acting `ContractorRep` must own the
        engagement, and the current logical clock must have reached or passed
        `window_end`, failing with `ERR_MILESTONE_WINDOW_NOT_ENDED` (HTTP 422)
        beforehand."

        Design: Corner/validations/milestone_complete_before_window_end_rejected
        """
        sc = setup_project_in_construction()
        milestone = create_milestone_record(
            sc["engagement"]["id"],
            sc["contractor"]["id"],
            milestone_name="Demolition",
            window_start="2026-08-03T00:00:00Z",
            window_end="2026-08-14T00:00:00Z",
            work_type="STANDARD",
        )
        assert milestone["status"] == "CONFIRMED"
        set_logical_clock("2026-08-10T00:00:00Z")

        resp = api.complete_milestone(
            milestone["id"], make_contractor_rep_headers(sc["contractor"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_MILESTONE_WINDOW_NOT_ENDED)
        after = get_success_data(api.get_milestone(milestone["id"], landlord_pm_headers))
        assert after["status"] == "CONFIRMED"

    def test_milestone_inverted_window_rejected(self, api, landlord_pm_headers):
        """PRD 3.4: "Windows are half-open — the start instant is included and
        the end instant excluded — and `window_end` must fall strictly after
        `window_start`, else `ERR_INVALID_WINDOW` (HTTP 422)."

        Design: Corner/validations/milestone_inverted_window_rejected
        """
        sc = setup_project_in_construction()
        resp = api.create_milestone(
            sc["engagement"]["id"],
            {
                "milestone_name": "Inverted",
                "window_start": "2026-08-14T00:00:00Z",
                "window_end": "2026-08-14T00:00:00Z",
                "work_type": "STANDARD",
            },
            make_contractor_rep_headers(sc["contractor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)
