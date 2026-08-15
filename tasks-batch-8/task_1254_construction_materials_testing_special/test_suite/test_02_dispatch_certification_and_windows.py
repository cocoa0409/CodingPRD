"""Dispatch certification gate, technician window occupancy, validation
precedence on dispatch/creation, and assignment listing filters."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    append_certification,
    cancel_assignment,
    certification_entry,
    create_assignment,
    create_assignment_payload,
    create_project,
    create_ssi_revision,
    create_technician,
    create_technician_payload,
    get_assignment,
    get_scope_items,
    make_technician_headers,
    record_soil_test,
    setup_approved_project,
    setup_dispatched_assignment,
    soil_scope_item,
    concrete_scope_item,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]


class TestDispatchCertificationGate:
    def test_dispatch_blocked_by_insufficient_certification_level(self, api):
        """PRD §3.3: "Moving an assignment `REQUESTED → DISPATCHED` requires, in
        order after the generic checks: the technician is `ACTIVE` (otherwise
        `ERR_TECHNICIAN_INACTIVE`); the technician holds a certification whose
        `method` matches the scope item's `test_method` (otherwise
        `ERR_CERTIFICATION_MISSING`); that certification's `level` is at least
        the scope item's `required_cert_level` (otherwise
        `ERR_CERTIFICATION_INSUFFICIENT`); and its `expires_at` falls strictly
        after the assignment's `work_date` (otherwise
        `ERR_CERTIFICATION_EXPIRED`)."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_sufficient_certification
        """
        ctx = setup_approved_project(
            [concrete_scope_item(description="columns", required_cert_level=2)]
        )
        tech = create_technician(
            certifications=[certification_entry("CONCRETE_STRENGTH", level=1)]
        )
        asg = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "09:00", "10:00",
        )
        resp = api.dispatch_assignment(asg["id"], PM)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_INSUFFICIENT)
        assert get_assignment(asg["id"])["status"] == "REQUESTED"

    def test_dispatch_succeeds_after_certification_upgraded(self, api):
        """PRD §3.3: "Moving an assignment `REQUESTED → DISPATCHED` requires, in
        order after the generic checks: the technician is `ACTIVE` (otherwise
        `ERR_TECHNICIAN_INACTIVE`); the technician holds a certification whose
        `method` matches the scope item's `test_method` (otherwise
        `ERR_CERTIFICATION_MISSING`); that certification's `level` is at least
        the scope item's `required_cert_level` (otherwise
        `ERR_CERTIFICATION_INSUFFICIENT`); and its `expires_at` falls strictly
        after the assignment's `work_date` (otherwise
        `ERR_CERTIFICATION_EXPIRED`)."
        PRD §3.2: "Certifications may be supplied at creation and are later
        appended one at a time through a dedicated capability; each entry in
        the `certifications` array is a triple of `method` (one of the four
        test methods), `level` (1 through 3), and `expires_at` (an ISO date)."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_sufficient_certification
        """
        ctx = setup_approved_project(
            [concrete_scope_item(description="columns", required_cert_level=2)]
        )
        tech = create_technician(
            certifications=[certification_entry("CONCRETE_STRENGTH", level=1)]
        )
        asg = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "09:00", "10:00",
        )
        blocked = api.dispatch_assignment(asg["id"], PM)
        validate_error(blocked, ApiErrorId.ERR_CERTIFICATION_INSUFFICIENT)

        append_certification(tech["id"], "CONCRETE_STRENGTH", 2, "2027-01-01")
        dispatched = validate_success(api.dispatch_assignment(asg["id"], PM), 200)
        assert dispatched["status"] == "DISPATCHED", (
            "appending a level-2 certification to the same technician flips the "
            "dispatch transition to legal"
        )


class TestValidationPrecedence:
    def test_dispatch_cancelled_assignment_reports_state_error_not_cert_error(self, api):
        """PRD §2.9: "When several checks could reject the same request, they
        are evaluated in a fixed order so the surfaced error is deterministic."
        PRD §2.9: "Fourth, state: whether the target resource's current state
        permits the operation (`ERR_INVALID_STATE`), a tier that also carries
        the domain state errors `ERR_PROJECT_COMPLETED`,
        `ERR_LETTER_ALREADY_ISSUED`, `ERR_NO_LETTER_TO_VOID`,
        `ERR_TEST_NOT_VOIDABLE`, and `ERR_NO_RESULT_RECORDED`. Fifth,
        technician fitness for dispatch: active status, certification presence,
        level sufficiency, and certification currency (`ERR_TECHNICIAN_INACTIVE`,
        `ERR_CERTIFICATION_MISSING`, `ERR_CERTIFICATION_INSUFFICIENT`,
        `ERR_CERTIFICATION_EXPIRED`)."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_cancelled_with_expired_cert_state_wins
        """
        ctx = setup_approved_project([soil_scope_item()])
        tech = create_technician(certifications=[
            certification_entry("SOIL_COMPACTION", level=2, expires_at="2026-05-03")
        ])
        asg = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "09:00", "10:00",
        )
        cancel_assignment(asg["id"])

        resp = api.dispatch_assignment(asg["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_assignment(asg["id"])["status"] == "CANCELLED", (
            "a rejected dispatch changes no state"
        )

    def test_expired_certification_blocks_dispatch_in_isolation(self, api):
        """PRD §3.3: "Moving an assignment `REQUESTED → DISPATCHED` requires, in
        order after the generic checks: the technician is `ACTIVE` (otherwise
        `ERR_TECHNICIAN_INACTIVE`); the technician holds a certification whose
        `method` matches the scope item's `test_method` (otherwise
        `ERR_CERTIFICATION_MISSING`); that certification's `level` is at least
        the scope item's `required_cert_level` (otherwise
        `ERR_CERTIFICATION_INSUFFICIENT`); and its `expires_at` falls strictly
        after the assignment's `work_date` (otherwise
        `ERR_CERTIFICATION_EXPIRED`)."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_cancelled_with_expired_cert_state_wins
        """
        ctx = setup_approved_project([soil_scope_item()])
        tech = create_technician(certifications=[
            certification_entry("SOIL_COMPACTION", level=2, expires_at="2026-05-03")
        ])
        cancelled = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "09:00", "10:00",
        )
        cancel_assignment(cancelled["id"])  # frees the 09:00-10:00 window
        fresh = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "09:00", "10:00",
        )
        resp = api.dispatch_assignment(fresh["id"], PM)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_EXPIRED)

    def test_overlapping_window_reports_double_booking_before_reference_scope(self, api):
        """PRD §2.9: "When several checks could reject the same request, they
        are evaluated in a fixed order so the surfaced error is deterministic."
        PRD §2.9: "Sixth, temporal occupancy: technician window overlap on
        assignment creation and break-date equality on break scheduling
        (`ERR_TECHNICIAN_DOUBLE_BOOKED`, `ERR_BREAK_DATE_MISMATCH`). Seventh,
        uniqueness and aggregate gates: unique `permit_number`,
        `employee_code`, and `lab_code` at creation, the one-daily-report rule,
        and the posture gate on letter issuance (`ERR_VALIDATION`,
        `ERR_DUPLICATE_DAILY_REPORT`, `ERR_POSTURE_NOT_READY`). Eighth,
        cross-reference scope (`ERR_REFERENCE_MISMATCH`, `ERR_SSI_NOT_APPROVED`)."

        Design: Difficulty/priority_pair_validation_conflict/create_assignment_temporal_beats_referential
        """
        ctx_a = setup_approved_project(
            [soil_scope_item(description="pad A")],
            project_overrides={"name": "Prio B A", "permit_number": "P-PRI-2A"},
        )
        ctx_b = setup_approved_project(
            [soil_scope_item(description="pad B")],
            project_overrides={"name": "Prio B B", "permit_number": "P-PRI-2B"},
        )
        tech = create_technician(certifications=[
            certification_entry("SOIL_COMPACTION", level=2)
        ])
        create_assignment(
            ctx_a["project"]["id"], ctx_a["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "09:00", "10:00",
        )
        resp = api.create_assignment(
            create_assignment_payload(
                ctx_a["project"]["id"], ctx_b["scope_items"][0]["id"], tech["id"],
                "2026-05-04", "09:30", "10:30",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_DOUBLE_BOOKED)

    def test_cross_project_scope_item_rejected_as_reference_mismatch(self, api):
        """PRD §3.3: "The scope item must belong to the project's currently
        approved SSI revision: if the project has no approved revision at all,
        creation fails with `ERR_SSI_NOT_APPROVED`; if the scope item belongs
        to another project or to a revision that is not the current approved
        one, it fails with `ERR_REFERENCE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/create_assignment_temporal_beats_referential
        """
        ctx_a = setup_approved_project(
            [soil_scope_item(description="pad A")],
            project_overrides={"name": "Ref A", "permit_number": "P-REF-A"},
        )
        ctx_b = setup_approved_project(
            [soil_scope_item(description="pad B")],
            project_overrides={"name": "Ref B", "permit_number": "P-REF-B"},
        )
        tech = create_technician(certifications=[
            certification_entry("SOIL_COMPACTION", level=2)
        ])
        resp = api.create_assignment(
            create_assignment_payload(
                ctx_a["project"]["id"], ctx_b["scope_items"][0]["id"], tech["id"],
                "2026-05-04", "09:00", "10:00",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_MISMATCH)


class TestTechnicianWindowOccupancy:
    def test_overlapping_window_rejected(self, api):
        """PRD §3.3: "Windows are half-open intervals on a given `work_date`: a
        new window overlapping an existing `REQUESTED` or `DISPATCHED`
        assignment of the same technician on the same date is rejected with
        `ERR_TECHNICIAN_DOUBLE_BOOKED`, while two windows that merely touch —
        one ending exactly when the other begins — are both allowed."

        Design: Difficulty/resource_temporal_overlap/technician_window_half_open_overlap
        """
        ctx = setup_approved_project([soil_scope_item(required_count=5)])
        tech = create_technician(certifications=[
            certification_entry("SOIL_COMPACTION", level=2)
        ])
        create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "09:00", "10:00",
        )
        resp = api.create_assignment(
            create_assignment_payload(
                ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
                "2026-05-04", "09:30", "10:30",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_DOUBLE_BOOKED)

    def test_adjacent_window_accepted(self, api):
        """PRD §3.3: "Windows are half-open intervals on a given `work_date`: a
        new window overlapping an existing `REQUESTED` or `DISPATCHED`
        assignment of the same technician on the same date is rejected with
        `ERR_TECHNICIAN_DOUBLE_BOOKED`, while two windows that merely touch —
        one ending exactly when the other begins — are both allowed."

        Design: Difficulty/resource_temporal_overlap/technician_window_half_open_overlap
        """
        ctx = setup_approved_project([soil_scope_item(required_count=5)])
        tech = create_technician(certifications=[
            certification_entry("SOIL_COMPACTION", level=2)
        ])
        create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "09:00", "10:00",
        )
        adjacent = validate_success(
            api.create_assignment(
                create_assignment_payload(
                    ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
                    "2026-05-04", "10:00", "11:00",
                ),
                PM,
            ),
            201,
        )
        assert adjacent["status"] == "REQUESTED", (
            "windows sharing only an endpoint do not overlap under half-open arithmetic"
        )
        data, _meta = validate_paginated(
            api.list_assignments(
                PM, params={"technician_id": tech["id"], "work_date": "2026-05-04"}
            )
        )
        assert len(data) == 2, "both the original and the adjacent assignment exist"


class TestAssignmentStateRules:
    def test_requeue_returns_dispatched_assignment_to_requested(self, api):
        """PRD §3.3: "Cancellation from either `REQUESTED` or `DISPATCHED` moves
        the assignment to `CANCELLED` and frees the technician's window; the
        same cancellation capability called with `requeue` set to true on a
        `DISPATCHED` assignment instead returns it to `REQUESTED` — a requeue
        loop for re-dispatch — and likewise frees the window."

        Design: Corner/state_machines/assignment_requeue_loop_dispatched_to_requested
        """
        ctx = setup_dispatched_assignment()
        requeued = validate_success(
            api.cancel_assignment(ctx["assignment"]["id"], {"requeue": True}, PM), 200
        )
        assert requeued["status"] == "REQUESTED", "requeue loops back, not CANCELLED"
        redispatched = validate_success(
            api.dispatch_assignment(ctx["assignment"]["id"], PM), 200
        )
        assert redispatched["status"] == "DISPATCHED"

    def test_complete_without_recorded_result_rejected(self, api):
        """PRD §3.3: "Completion is the technician's own act: only the
        technician whose `id` matches the assignment's `technician_id` may
        complete it (anyone else gets `ERR_FORBIDDEN`), and only from
        `DISPATCHED`, and only when at least one field test or lab sample has
        been recorded against it (otherwise `ERR_NO_RESULT_RECORDED`)."

        Design: Corner/state_machines/complete_assignment_without_results_rejected
        """
        ctx = setup_dispatched_assignment()
        resp = api.complete_assignment(
            ctx["assignment"]["id"], {"completion_note": "nothing done"},
            make_technician_headers(ctx["technician"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_RESULT_RECORDED)
        assert get_assignment(ctx["assignment"]["id"])["status"] == "DISPATCHED"

    def test_complete_by_other_technician_forbidden(self, api):
        """PRD §3.3: "Completion is the technician's own act: only the
        technician whose `id` matches the assignment's `technician_id` may
        complete it (anyone else gets `ERR_FORBIDDEN`), and only from
        `DISPATCHED`, and only when at least one field test or lab sample has
        been recorded against it (otherwise `ERR_NO_RESULT_RECORDED`)."
        PRD §2.1: "When `X-User-Role` is `Technician`, `X-User-ID` is the `id`
        of the acting `Technician` entity; ownership checks on any resource
        that references a `Technician` compare the resource's technician
        foreign-key field to `X-User-ID`."

        Design: Corner/state_machines/complete_assignment_by_other_technician_forbidden
        """
        ctx = setup_dispatched_assignment()
        record_soil_test(ctx["assignment"]["id"], ctx["technician"]["id"], 118.0)
        other = create_technician(certifications=[
            certification_entry("SOIL_COMPACTION", level=2)
        ])
        resp = api.complete_assignment(
            ctx["assignment"]["id"], {"completion_note": "other technician attempting"},
            make_technician_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_assignment(ctx["assignment"]["id"])["status"] == "DISPATCHED"

    def test_assignment_creation_requires_approved_revision(self, api):
        """PRD §3.3: "The scope item must belong to the project's currently
        approved SSI revision: if the project has no approved revision at all,
        creation fails with `ERR_SSI_NOT_APPROVED`; if the scope item belongs
        to another project or to a revision that is not the current approved
        one, it fails with `ERR_REFERENCE_MISMATCH`."

        Design: Corner/validations/assignment_create_without_approved_ssi_rejected
        """
        project = create_project(name="NoSSI", permit_number="P-VAL-5")
        ssi = create_ssi_revision(project["id"], [soil_scope_item()], 4000)
        item_id = get_scope_items(ssi["id"])[0]["id"]
        tech = create_technician(certifications=[
            certification_entry("SOIL_COMPACTION", level=2)
        ])
        resp = api.create_assignment(
            create_assignment_payload(
                project["id"], item_id, tech["id"], "2026-05-04", "09:00", "10:00"
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_SSI_NOT_APPROVED)


class TestTechnicianRegistration:
    def test_certification_with_unknown_method_rejected(self, api):
        """PRD §2.9: "Malformed payloads — a missing required field, an unknown
        enum value, a malformed date or time, an `end_time` that is not after
        `start_time` — are rejected with `ERR_VALIDATION` before any business
        rule is consulted."
        PRD §3.2: "Certifications may be supplied at creation and are later
        appended one at a time through a dedicated capability; each entry in
        the `certifications` array is a triple of `method` (one of the four
        test methods), `level` (1 through 3), and `expires_at` (an ISO date)."

        Design: Corner/validations/create_technician_invalid_enum_rejected
        """
        resp = api.create_technician(
            create_technician_payload(
                certifications=[{"method": "XRAY", "level": 2, "expires_at": "2027-01-01"}],
                full_name="Bad Cert",
                employee_code="T9",
            ),
            TEST_USERS["agency_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert resp.status_code == 400


class TestAssignmentListing:
    def test_assignment_list_filters_intersect(self, api):
        """PRD §3.3: "The assignment list supports optional filters on
        `project_id`, `scope_item_id`, `technician_id`, `status`, and
        `work_date`."

        Design: Corner/endpoints/assignments_list_filters_compose
        """
        ctx = setup_approved_project([soil_scope_item(required_count=5)])
        t1 = create_technician(certifications=[certification_entry("SOIL_COMPACTION", level=2)])
        t2 = create_technician(certifications=[certification_entry("SOIL_COMPACTION", level=2)])
        a1 = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], t1["id"],
            "2026-05-04", "09:00", "10:00",
        )
        create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], t2["id"],
            "2026-05-04", "09:00", "10:00",
        )
        data, meta = validate_paginated(
            api.list_assignments(
                PM, params={"technician_id": t1["id"], "work_date": "2026-05-04"}
            )
        )
        assert len(data) == 1, "filters compose as an intersection, not a union"
        assert data[0]["id"] == a1["id"]
        assert meta["total_count"] == 1
