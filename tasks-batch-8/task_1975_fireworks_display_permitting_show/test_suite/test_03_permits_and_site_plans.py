"""Permit review loop, site-plan supersede + OCC, venue buffer, license window
(PRD §2.5, §2.7, §3.2, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_display_payload,
    create_permit_application_payload,
    create_site_plan_payload,
    get_success_data,
    make_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    MARSHAL_1,
    add_site_plan,
    approve_permit,
    create_operator,
    setup_event_draft,
    setup_event_submitted,
)

ADMIN = TEST_USERS["admin_headers"]


class TestSitePlanCreation:
    def test_provisional_rsd_formula_exact(self, api):
        """PRD §3.2: "the server computes the plan's
        `required_spectator_distance_ft` as 70 feet per inch of the parent
        event's `declared_max_shell_diameter_in`, rounded half-up to integer
        feet — a declared 6-inch shell therefore demands 420 feet."

        Design: Corner/calculations/provisional_rsd_formula_exact
        """
        op, op_headers, ev = setup_event_draft()
        resp = api.create_site_plan(
            ev["id"], create_site_plan_payload(ev["version"]), op_headers
        )
        sp = validate_success(resp, expected_status=201)
        assert sp["required_spectator_distance_ft"] == 280  # 70 x declared 4 in

    def test_site_plan_boundary_below_rsd_rejected(self, api):
        """PRD §3.2: "Both `spectator_boundary_ft` and `nearest_structure_ft`
        must be at least this required distance, otherwise creation is
        rejected with `ERR_FALLOUT_EXCEEDS_BOUNDARY`."

        Design: Corner/calculations/site_plan_boundary_below_rsd_rejected
        """
        op, op_headers, ev = setup_event_draft()
        bad = api.create_site_plan(
            ev["id"],
            create_site_plan_payload(ev["version"], spectator_boundary_ft=279),
            op_headers,
        )
        validate_error(bad, ApiErrorId.ERR_FALLOUT_EXCEEDS_BOUNDARY)
        assert bad.status_code == 422
        # Boundary exactly at the required distance (280) is allowed; the
        # rejected attempt must not have advanced the event version.
        ok = api.create_site_plan(
            ev["id"],
            create_site_plan_payload(ev["version"], spectator_boundary_ft=280),
            op_headers,
        )
        validate_success(ok, expected_status=201)


class TestPermitSubmission:
    def test_planned_hours_ceil_and_engine_surcharge(self, api):
        """PRD §3.3: "`planned_hours` is the length of the scheduled window
        rounded up to whole hours" and "`provisional_standby_fee_cents` is
        then the base standby fee of 25000 cents, plus 14500 cents for each
        planned hour, plus a 30000-cent surcharge for each requested standby
        engine."

        Design: Corner/calculations/planned_hours_ceil_and_engine_surcharge
        """
        op, op_headers, ev = setup_event_draft(
            display_overrides={"scheduled_end_at": "2026-09-01T22:30:00Z"}
        )
        sp = add_site_plan(ev, op_headers)
        resp = api.create_permit_application(
            ev["id"], create_permit_application_payload(sp["id"], standby_engines=2),
            op_headers,
        )
        app = validate_success(resp, expected_status=201)
        assert app["planned_hours"] == 3  # ceil(2.5 h)
        assert app["provisional_standby_fee_cents"] == 128500  # 25000 + 3*14500 + 2*30000

    def test_duplicate_application_rejected(self, api):
        """PRD §3.3: "no other application of the same event to be sitting in
        `SUBMITTED` or `INFO_REQUESTED` (a duplicate yields
        `ERR_DUPLICATE_APPLICATION`, and as noted in §2.8 this check fires
        ahead of the generic state check on this endpoint)".

        Design: Corner/validations/duplicate_application_rejected
        """
        op, op_headers, ev, sp, app = setup_event_submitted()
        resp = api.create_permit_application(
            ev["id"], create_permit_application_payload(sp["id"]), op_headers
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION)
        assert resp.status_code == 409

    def test_approve_after_deny_returns_invalid_state(self, api):
        """PRD §3.3: denial "moves the application to `DENIED`, and drives the
        event `SUBMITTED → DENIED` — terminal for the event." PRD §2.8:
        "the transition must be listed for the entity's current state
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/approve_after_deny_returns_invalid_state
        """
        op, op_headers, ev, sp, app = setup_event_submitted()
        deny = api.deny_permit(app["id"], {"decision_note": "site too tight"}, MARSHAL_1)
        validate_success(deny)
        resp = api.approve_permit(app["id"], {"decision_note": "changed my mind"}, MARSHAL_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fresh = get_success_data(api.get_display(ev["id"], op_headers))
        assert fresh["status"] == "DENIED"


class TestPermitRevisionCycle:
    def _setup_info_requested(self, api):
        op, op_headers, ev, sp1, app = setup_event_submitted()
        ri = api.request_info_permit(app["id"], {"decision_note": "move boundary"}, MARSHAL_1)
        validate_success(ri)
        mid = get_success_data(api.get_display(ev["id"], op_headers))
        sp2 = add_site_plan(
            mid, op_headers,
            diagram_ref="D2", launch_area_width_ft=220, launch_area_length_ft=220,
            spectator_boundary_ft=320,
        )
        return op, op_headers, ev, sp1, sp2, app, mid

    def test_resubmit_closes_revision_loop(self, api):
        """PRD §3.3: "Resubmission moves the application `INFO_REQUESTED →
        SUBMITTED`, re-pins `site_plan_id` and `site_plan_version`, increments
        `revision_count` by one, and returns the event `REVISION_REQUESTED →
        SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/permit_application_info_request_cycle
        """
        op, op_headers, ev, sp1, sp2, app, mid = self._setup_info_requested(api)
        assert mid["status"] == "REVISION_REQUESTED"
        resp = api.resubmit_permit(app["id"], {"site_plan_id": sp2["id"]}, op_headers)
        data = validate_success(resp)
        assert data["status"] == "SUBMITTED"
        assert data["revision_count"] == 1
        assert data["site_plan_id"] == sp2["id"]
        ev_after = get_success_data(api.get_display(ev["id"], op_headers))
        assert ev_after["status"] == "SUBMITTED"

    def test_cycle_ends_in_approval_and_supersede(self, api):
        """PRD §3.3: "Approval moves the application to `APPROVED`, records the marshal's `X-User-ID` as `reviewed_by_user_id` along with an optional `decision_note`, and drives the event `SUBMITTED → APPROVED`."
        PRD §3.2: "Filing a site plan supersedes whatever plan was previously `CURRENT` for the event, moving it to `SUPERSEDED`, and increments the event's `version` by one".

        Design: Difficulty/non_linear_state_machine/permit_application_info_request_cycle
        """
        op, op_headers, ev, sp1, sp2, app, mid = self._setup_info_requested(api)
        validate_success(api.resubmit_permit(app["id"], {"site_plan_id": sp2["id"]}, op_headers))
        approve = api.approve_permit(app["id"], {"decision_note": "ok now"}, MARSHAL_1)
        appd = validate_success(approve)
        assert appd["status"] == "APPROVED"
        ev_after = get_success_data(api.get_display(ev["id"], op_headers))
        assert ev_after["status"] == "APPROVED"
        plans, meta = validate_paginated(api.list_site_plans(ev["id"], op_headers))
        # created_at ASC (PRD §2.3): sp1 first, sp2 second.
        assert plans[0]["id"] == sp1["id"] and plans[0]["status"] == "SUPERSEDED"
        assert plans[1]["id"] == sp2["id"] and plans[1]["status"] == "CURRENT"


class TestSitePlanOcc:
    def test_stale_site_plan_create_rejected(self, api):
        """PRD §2.7: "If the event's current `version` has advanced past that
        value — because any authorized write has mutated the event in the
        meantime — the request is rejected with `ERR_STALE_VERSION` (HTTP
        412)."

        Design: Corner/cross_cutting_layers/occ_site_plan_stale_version_rejected
        """
        op, op_headers, ev = setup_event_draft()
        sp1 = add_site_plan(ev, op_headers)  # event version now 2
        stale = api.create_site_plan(
            ev["id"],
            create_site_plan_payload(ev["version"], diagram_ref="D2",
                                     spectator_boundary_ft=320),
            op_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412

    def test_fresh_site_plan_create_supersedes(self, api):
        """PRD §2.7: "For site-plan creation this prevents a client from
        superseding a plan it never saw"; PRD §3.2: "Filing a site plan
        supersedes whatever plan was previously `CURRENT` for the event,
        moving it to `SUPERSEDED`".

        Design: Corner/cross_cutting_layers/occ_site_plan_stale_version_rejected
        """
        op, op_headers, ev = setup_event_draft()
        sp1 = add_site_plan(ev, op_headers)
        fresh_ev = get_success_data(api.get_display(ev["id"], op_headers))
        ok = api.create_site_plan(
            ev["id"],
            create_site_plan_payload(fresh_ev["version"], diagram_ref="D2",
                                     spectator_boundary_ft=320),
            op_headers,
        )
        sp2 = validate_success(ok, expected_status=201)
        plans, meta = validate_paginated(api.list_site_plans(ev["id"], op_headers))
        assert plans[0]["id"] == sp1["id"] and plans[0]["status"] == "SUPERSEDED"
        assert plans[1]["id"] == sp2["id"] and plans[1]["status"] == "CURRENT"


class TestVenueAndLicenseWindows:
    def test_venue_buffer_conflict_inside_buffer(self, api):
        """PRD §3.2: "if another non-terminal event at the same `venue_id`
        overlaps this event's window extended by a 120-minute trailing buffer,
        creation is rejected with `ERR_VENUE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/venue_booking_buffer_boundary
        """
        op, op_headers = create_operator()
        get_success_data(api.create_display(
            create_display_payload(
                venue_id="VEN-X",
                scheduled_start_at="2026-09-01T20:00:00Z",
                scheduled_end_at="2026-09-01T21:00:00Z",
            ),
            op_headers,
        ))
        resp = api.create_display(
            create_display_payload(
                venue_id="VEN-X",
                scheduled_start_at="2026-09-01T22:59:00Z",
                scheduled_end_at="2026-09-01T23:30:00Z",
                declared_max_shell_diameter_in=3,
            ),
            op_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VENUE_CONFLICT)
        assert resp.status_code == 409

    def test_venue_buffer_exact_edge_accepted(self, api):
        """PRD §3.2: "if another non-terminal event at the same `venue_id`
        overlaps this event's window extended by a 120-minute trailing buffer,
        creation is rejected with `ERR_VENUE_CONFLICT`" — a start exactly at
        prior end + 120 min is outside the buffered window and is accepted.

        Design: Difficulty/resource_temporal_overlap/venue_booking_buffer_boundary
        """
        op, op_headers = create_operator()
        get_success_data(api.create_display(
            create_display_payload(
                venue_id="VEN-X",
                scheduled_start_at="2026-09-01T20:00:00Z",
                scheduled_end_at="2026-09-01T21:00:00Z",
            ),
            op_headers,
        ))
        resp = api.create_display(
            create_display_payload(
                venue_id="VEN-X",
                scheduled_start_at="2026-09-01T23:00:00Z",
                scheduled_end_at="2026-09-02T00:30:00Z",
                declared_max_shell_diameter_in=3,
            ),
            op_headers,
        )
        validate_success(resp, expected_status=201)

    def test_venue_conflict_ignores_cancelled_events(self, api):
        """PRD §3.2: "if another non-terminal event at the same `venue_id`
        overlaps this event's window extended by a 120-minute trailing buffer,
        creation is rejected with `ERR_VENUE_CONFLICT`" — cancelled events are
        terminal and free their venue window.

        Design: Corner/validations/venue_conflict_ignores_cancelled_events
        """
        op, op_headers = create_operator()
        ea = get_success_data(api.create_display(
            create_display_payload(
                venue_id="VEN-V",
                scheduled_start_at="2026-09-01T20:00:00Z",
                scheduled_end_at="2026-09-01T21:00:00Z",
            ),
            op_headers,
        ))
        validate_success(api.cancel_display(ea["id"], {"reason": "off"}, op_headers))
        resp = api.create_display(
            create_display_payload(
                venue_id="VEN-V",
                scheduled_start_at="2026-09-01T20:00:00Z",
                scheduled_end_at="2026-09-01T21:00:00Z",
                declared_max_shell_diameter_in=3,
            ),
            op_headers,
        )
        validate_success(resp, expected_status=201)

    def test_license_containment_inclusive_end(self, api):
        """PRD §2.5: "The window is inclusive at both ends: a show whose
        `scheduled_start_at` equals `license_expires_at` exactly is still
        covered."

        Design: Difficulty/resource_temporal_overlap/license_containment_inclusive_boundary
        """
        op, op_headers = create_operator(
            legal_name="L1 Pyro", atf_license_number="ATF-L1",
            license_expires_at="2026-09-01T20:00:00Z",
        )
        resp = api.create_display(
            create_display_payload(
                venue_id="VEN-Y",
                scheduled_start_at="2026-09-01T20:00:00Z",
                scheduled_end_at="2026-09-01T21:00:00Z",
            ),
            op_headers,
        )
        validate_success(resp, expected_status=201)

    def test_license_expired_one_second_before(self, api):
        """PRD §2.5: "A show whose start falls outside the window is rejected
        with `ERR_LICENSE_EXPIRED`."

        Design: Difficulty/resource_temporal_overlap/license_containment_inclusive_boundary
        """
        op, op_headers = create_operator(
            legal_name="L2 Pyro", atf_license_number="ATF-L2",
            license_expires_at="2026-09-01T19:59:59Z",
        )
        resp = api.create_display(
            create_display_payload(
                venue_id="VEN-Z",
                scheduled_start_at="2026-09-01T20:00:00Z",
                scheduled_end_at="2026-09-01T21:00:00Z",
            ),
            op_headers,
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_EXPIRED)
        assert resp.status_code == 409


class TestInvalidTransitions:
    def test_cancel_cancelled_event_returns_invalid_state(self, api):
        """PRD §3.6: "a manual cancel while the event is in `DRAFT`,
        `SUBMITTED`, `REVISION_REQUESTED`, `APPROVED`, `STANDBY_CONFIRMED`, or
        `READY`"; PRD §2.8: "the transition must be listed for the entity's
        current state (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/cancel_cancelled_event_returns_invalid_state
        """
        op, op_headers, ev = setup_event_draft()
        validate_success(api.cancel_display(ev["id"], {"reason": "off"}, op_headers))
        resp = api.cancel_display(ev["id"], {"reason": "again"}, op_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fresh = get_success_data(api.get_display(ev["id"], op_headers))
        assert fresh["status"] == "CANCELLED"

    def test_ready_from_draft_returns_invalid_state(self, api):
        """PRD §3.5: "Readiness is the operator's declaration that the show
        can proceed, moving the event `STANDBY_CONFIRMED → READY`." PRD §2.8:
        "the transition must be listed for the entity's current state
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/ready_from_draft_returns_invalid_state
        """
        op, op_headers, ev = setup_event_draft()
        resp = api.ready_display(ev["id"], op_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
