"""Inspection-event scheduling: cross-aggregate integrity, technician
assignment identity, and aggregate capacity."""
from test_helpers import (
    ApiErrorId,
    add_license,
    add_technician,
    admin_headers,
    assert_event,
    create_contractor,
    create_event_payload,
    create_plan,
    create_property,
    create_system,
    make_technician_headers,
    schedule_event,
    set_clock,
    setup_inspection_site,
    setup_published_plan,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MARSHAL = TEST_USERS["fire_marshal_headers"]


class TestCrossAggregateIntegrity:
    def test_event_create_rejects_system_from_another_property(self, api):
        """PRD §3.4: "naming the `system_id` under inspection — which must belong
        to the plan's property, else `ERR_CROSS_REFERENCE_MISMATCH`"
        PRD §2.6: "15. **Cross-aggregate integrity** — an event's system must
        belong to its plan's property ... failure yields
        `ERR_CROSS_REFERENCE_MISMATCH`."

        Design: Corner/endpoints/event_create_validates_system_in_plan_property
        """
        con = create_contractor(legal_name="XRef Co", state_license_no="C-9993")
        p1 = create_property(con, address_line="1 X1 St")
        p2 = create_property(con, address_line="2 X2 St")
        sys2 = create_system(con, p2, system_category="FIRE_ALARM")
        tech = add_technician(con, full_name="Xavier Xref")
        plan1 = create_plan(con, p1, plan_year=2026)
        resp = api.create_event(
            plan1["id"],
            create_event_payload(sys2["id"], tech["id"],
                                 scheduled_start="2026-08-05T09:00:00Z",
                                 scheduled_end="2026-08-05T10:00:00Z"),
            admin_headers(con))
        validate_error(resp, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH)


class TestTechnicianCapacity:
    def _capacity_setup(self, api):
        """Technician leads three SCHEDULED events covering 2026-08-12 morning."""
        ctx = setup_inspection_site(system_category="SPRINKLER",
                                    device_type="SPRINKLER_HEAD",
                                    legal_name="Capacity Co")
        setup_published_plan(ctx)
        windows = [
            ("2026-08-12T09:00:00Z", "2026-08-12T10:00:00Z"),
            ("2026-08-12T09:30:00Z", "2026-08-12T10:30:00Z"),
            ("2026-08-12T08:30:00Z", "2026-08-12T10:00:00Z"),
        ]
        for start, end in windows:
            schedule_event(ctx["con"], ctx["plan"], ctx["sys"], ctx["tech"],
                           scheduled_start=start, scheduled_end=end)
        return ctx

    def test_fourth_overlapping_event_rejected_at_closed_endpoint(self, api):
        """PRD §3.4: "Assignment is capacity-checked: if the named technician
        already leads three other events in `SCHEDULED` or `IN_PROGRESS` whose
        closed-closed scheduled intervals intersect the new event's interval,
        the request is rejected with `ERR_TECHNICIAN_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/technician_capacity_fourth_overlapping_event_rejected
        """
        ctx = self._capacity_setup(api)
        resp = api.create_event(
            ctx["plan"]["id"],
            create_event_payload(ctx["sys"]["id"], ctx["tech"]["id"],
                                 scheduled_start="2026-08-12T10:00:00Z",
                                 scheduled_end="2026-08-12T11:00:00Z"),
            ctx["admin"])
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_CAPACITY)
        assert resp.status_code == 409

    def test_fourth_non_overlapping_event_accepted(self, api):
        """PRD §3.4: "Assignment is capacity-checked: if the named technician
        already leads three other events in `SCHEDULED` or `IN_PROGRESS` whose
        closed-closed scheduled intervals intersect the new event's interval,
        the request is rejected with `ERR_TECHNICIAN_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/technician_capacity_fourth_overlapping_event_rejected
        """
        ctx = self._capacity_setup(api)
        resp = api.create_event(
            ctx["plan"]["id"],
            create_event_payload(ctx["sys"]["id"], ctx["tech"]["id"],
                                 scheduled_start="2026-08-12T11:00:00Z",
                                 scheduled_end="2026-08-12T12:00:00Z"),
            ctx["admin"])
        ev = validate_success(resp, 201)
        assert_event(ev)
        assert ev["status"] == "SCHEDULED", (
            "an 11:00-12:00 event intersects none of the three morning events, "
            "so capacity does not bind")


class TestAssignmentIdentity:
    def test_technician_not_assigned_cannot_start_event(self, api):
        """PRD §3.4: "Starting an event requires it to be `SCHEDULED`, the acting
        technician's identity to equal the event's `lead_technician_id` (else
        `ERR_TECHNICIAN_NOT_ASSIGNED`)"
        PRD §2.1: "When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of
        the acting Technician; assignment checks on an inspection event compare
        the event's `lead_technician_id` to `X-User-ID`."

        Design: Corner/rbac/technician_not_assigned_cannot_start_event
        """
        ctx = setup_inspection_site(legal_name="Assign Co")
        tech_b = add_technician(ctx["con"], full_name="Bob Bystander")
        add_license(ctx["con"], tech_b, license_class="ALARM",
                    expires_on="2027-01-01")
        setup_published_plan(ctx)
        ev = schedule_event(ctx["con"], ctx["plan"], ctx["sys"], ctx["tech"],
                            scheduled_start="2026-08-02T09:00:00Z",
                            scheduled_end="2026-08-02T10:00:00Z")
        set_clock("2026-08-02T09:00:00Z")
        resp = api.start_event(ev["id"], make_technician_headers(tech_b["id"]))
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_ASSIGNED)
        after = validate_success(api.get_event(ev["id"], ctx["admin"]))
        assert after["status"] == "SCHEDULED", (
            "the rejected start leaves the event SCHEDULED")
