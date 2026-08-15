"""Audit scheduling: state gates, temporal interval rules, windows, RBAC."""
from test_helpers import (
    ADMIN,
    OFFICER,
    TEST_USERS,
    ApiErrorId,
    acknowledge_code,
    assert_audit,
    cancel_audit,
    completed_audit_with_findings,
    create_audit_payload,
    create_auditor,
    create_claim,
    create_code_version,
    create_facility,
    create_supplier,
    decide_claim,
    get_supplier,
    make_auditor_headers,
    make_supplier_contact_headers,
    schedule_audit,
    set_clock,
    setup_active_supplier,
    setup_in_progress_audit,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["audit_coordinator_headers"]


def active_program(legal_name="Scheduling Supplier"):
    """ACTIVE supplier + one facility + one auditor covering the facility."""
    ctx = setup_active_supplier(legal_name=legal_name, sector="FOOD")
    facility = create_facility(ctx["supplier"]["id"], name="Main Site")
    auditor = create_auditor()
    return ctx, facility, auditor


class TestAuditCreationBasics:
    def test_audit_create_initial_state_and_zeroed_tallies(self, api):
        """PRD §3.3: "A created audit begins `SCHEDULED` with its tallies
        `zt_count`, `major_count`, and `minor_count` zeroed."

        Design: Corner/state_machines/audit_initial_state_scheduled
        """
        ctx, facility, auditor = active_program("Zulu Goods")
        audit = validate_success(
            api.create_audit(create_audit_payload(facility["id"], auditor["id"]),
                             COORD),
            201,
        )
        assert_audit(audit)
        assert audit["status"] == "SCHEDULED"
        assert audit["zt_count"] == 0
        assert audit["major_count"] == 0
        assert audit["minor_count"] == 0

    def test_audit_create_forbidden_for_supplier_contact(self, api):
        """PRD §2.1: "Access to each operation is restricted by role; an attempt
        to perform an action outside the caller's designated role is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /audits is authorized for AuditCoordinator only.

        Design: Corner/validations/audit_create_forbidden_for_supplier_contact
        """
        ctx, facility, auditor = active_program("November Goods")
        resp = api.create_audit(
            create_audit_payload(facility["id"], auditor["id"]),
            make_supplier_contact_headers(ctx["supplier"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


class TestSupplierStateGate:
    def test_audit_schedule_blocked_while_supplier_onboarding(self, api):
        """PRD §3.3: "The owning supplier must be `ACTIVE` or `PROBATION`
        (`ERR_SUPPLIER_NOT_AUDITABLE`), the facility must be `ACTIVE`
        (`ERR_FACILITY_NOT_ACTIVE`), and the assigned auditor must be `ACTIVE`
        (`ERR_AUDITOR_NOT_ACTIVE`); within these state checks the supplier is
        evaluated first, then the facility, then the auditor."

        Design: Difficulty/cross_entity_state_dependency/audit_schedule_requires_auditable_supplier
        """
        create_code_version()
        supplier = create_supplier(legal_name="Mike Outfitters",
                                   sector="APPAREL")
        assert supplier["status"] == "ONBOARDING"
        facility = create_facility(supplier["id"], name="Reno Cut")
        auditor = create_auditor()
        resp = api.create_audit(
            create_audit_payload(facility["id"], auditor["id"]), COORD
        )
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_AUDITABLE, 409)
        listed, _ = validate_paginated(
            api.list_audits(OFFICER, params={"facility_id": facility["id"]})
        )
        assert listed == [], "no audit may be scheduled for an ONBOARDING supplier"

    def test_audit_schedule_succeeds_after_acknowledgment(self, api):
        """PRD §3.1: "a supplier's first acknowledgment also moves it
        automatically from `ONBOARDING` to `ACTIVE`."
        PRD §3.3: "The owning supplier must be `ACTIVE` or `PROBATION`
        (`ERR_SUPPLIER_NOT_AUDITABLE`)"

        Design: Difficulty/cross_entity_state_dependency/audit_schedule_requires_auditable_supplier
        """
        cv = create_code_version()
        supplier = create_supplier(legal_name="Mike Outfitters",
                                   sector="APPAREL")
        facility = create_facility(supplier["id"], name="Reno Cut")
        auditor = create_auditor()
        blocked = api.create_audit(
            create_audit_payload(facility["id"], auditor["id"]), COORD
        )
        validate_error(blocked, ApiErrorId.ERR_SUPPLIER_NOT_AUDITABLE)

        acknowledge_code(supplier, cv["id"])
        assert get_supplier(supplier["id"])["status"] == "ACTIVE"

        audit = validate_success(
            api.create_audit(create_audit_payload(facility["id"], auditor["id"]),
                             COORD),
            201,
        )
        assert_audit(audit)
        assert audit["status"] == "SCHEDULED"


class TestAuditorBookingOverlap:
    def test_auditor_touching_windows_allowed(self, api):
        """PRD §3.3: "The auditor must not be double-booked: the new half-open
        window must not intersect any non-`CANCELLED` audit of the same auditor,
        where a conflict exists exactly when the new start falls before an
        existing audit's end and the new end falls after that existing audit's
        start — windows that merely touch at an endpoint are allowed
        (`ERR_AUDITOR_BOOKING_CONFLICT`)."

        Design: Difficulty/resource_temporal_overlap/auditor_half_open_booking_overlap
        """
        ctx = setup_active_supplier(legal_name="Oscar Retail",
                                    sector="HARDLINES")
        fac1 = create_facility(ctx["supplier"]["id"], name="Site 1")
        fac2 = create_facility(ctx["supplier"]["id"], name="Site 2")
        auditor = create_auditor()
        a1 = schedule_audit(
            fac1["id"], auditor["id"],
            scheduled_start="2026-09-01T00:00:00Z",
            scheduled_end="2026-09-05T00:00:00Z",
        )
        # Touches a1 at the endpoint: [09-05, 09-08) starts where a1 ends.
        a2 = validate_success(
            api.create_audit(
                create_audit_payload(
                    fac2["id"], auditor["id"], audit_type="ANNUAL",
                    scheduled_start="2026-09-05T00:00:00Z",
                    scheduled_end="2026-09-08T00:00:00Z",
                ),
                COORD,
            ),
            201,
        )
        assert a1["status"] == "SCHEDULED" and a2["status"] == "SCHEDULED", (
            "touching endpoints are not a conflict under half-open semantics"
        )

    def test_auditor_overlapping_window_rejected(self, api):
        """PRD §3.3: "a conflict exists exactly when the new start falls before
        an existing audit's end and the new end falls after that existing
        audit's start — windows that merely touch at an endpoint are allowed
        (`ERR_AUDITOR_BOOKING_CONFLICT`)."

        Design: Difficulty/resource_temporal_overlap/auditor_half_open_booking_overlap
        """
        ctx = setup_active_supplier(legal_name="Oscar Retail",
                                    sector="HARDLINES")
        fac1 = create_facility(ctx["supplier"]["id"], name="Site 1")
        fac3 = create_facility(ctx["supplier"]["id"], name="Site 3")
        auditor = create_auditor()
        schedule_audit(
            fac1["id"], auditor["id"],
            scheduled_start="2026-09-01T00:00:00Z",
            scheduled_end="2026-09-05T00:00:00Z",
        )
        # [09-04, 09-06) strictly intersects [09-01, 09-05).
        resp = api.create_audit(
            create_audit_payload(
                fac3["id"], auditor["id"],
                scheduled_start="2026-09-04T00:00:00Z",
                scheduled_end="2026-09-06T00:00:00Z",
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_AUDITOR_BOOKING_CONFLICT, 409)


class TestFacilitySpacing:
    def test_facility_gap_under_thirty_days_rejected(self, api):
        """PRD §3.3: "Facility spacing requires the new `scheduled_start` to be
        at least 30 days after the `scheduled_end` of every non-`CANCELLED`
        audit at the same facility, with a start exactly 30 days later permitted
        (`ERR_FACILITY_AUDIT_GAP_VIOLATION`)."

        Design: Difficulty/resource_temporal_overlap/facility_thirty_day_gap_buffer
        """
        ctx = completed_audit_with_findings(
            (),
            supplier_name="Papa Goods",
            facility_name="Boise DC",
            scheduled_start="2026-09-01T00:00:00Z",
            scheduled_end="2026-09-05T00:00:00Z",
        )
        auditor2 = create_auditor(full_name="Second Auditor")
        # 2026-10-03 is 28 days after scheduled_end 2026-09-05 -> < 30 days.
        resp = api.create_audit(
            create_audit_payload(
                ctx["facility"]["id"], auditor2["id"], audit_type="FOLLOW_UP",
                scheduled_start="2026-10-03T00:00:00Z",
                scheduled_end="2026-10-04T00:00:00Z",
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_AUDIT_GAP_VIOLATION, 409)

    def test_facility_gap_exactly_thirty_days_allowed(self, api):
        """PRD §3.3: "Facility spacing requires the new `scheduled_start` to be
        at least 30 days after the `scheduled_end` of every non-`CANCELLED`
        audit at the same facility, with a start exactly 30 days later permitted
        (`ERR_FACILITY_AUDIT_GAP_VIOLATION`)."

        Design: Difficulty/resource_temporal_overlap/facility_thirty_day_gap_buffer
        """
        ctx = completed_audit_with_findings(
            (),
            supplier_name="Papa Goods",
            facility_name="Boise DC",
            scheduled_start="2026-09-01T00:00:00Z",
            scheduled_end="2026-09-05T00:00:00Z",
        )
        auditor2 = create_auditor(full_name="Second Auditor")
        # 2026-10-05 is exactly 30 days after scheduled_end 2026-09-05.
        audit2 = validate_success(
            api.create_audit(
                create_audit_payload(
                    ctx["facility"]["id"], auditor2["id"],
                    audit_type="FOLLOW_UP",
                    scheduled_start="2026-10-05T00:00:00Z",
                    scheduled_end="2026-10-06T00:00:00Z",
                ),
                COORD,
            ),
            201,
        )
        assert audit2["status"] == "SCHEDULED"


class TestValidationOrderStateBeforeTemporal:
    def test_state_error_beats_temporal_on_exited_facility(self, api):
        """PRD §2.6: "Every request is evaluated against a fixed sequence of
        check families; a request that fails an earlier family is rejected
        without any later family being consulted."
        PRD §3.3: "the facility must be `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`)"
        PRD §3.3: "The auditor must not be double-booked: the new half-open
        window must not intersect any non-`CANCELLED` audit of the same auditor"
        The request below violates both rules; the state family (step 7) is
        evaluated before the temporal family (step 10), so the state error wins.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_exited_facility_booking
        """
        fac_a, auditor, au_b = exited_facility_scenario(api)
        resp = api.create_audit(
            create_audit_payload(
                fac_a["id"], auditor["id"],
                scheduled_start="2026-09-02T00:00:00Z",
                scheduled_end="2026-09-04T00:00:00Z",
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_ACTIVE, 409)

    def test_exited_facility_booking_leaves_no_residue(self, api):
        """PRD §2.6: "a request that fails an earlier family is rejected without
        any later family being consulted."
        PRD §3.3: "The auditor must not be double-booked: the new half-open
        window must not intersect any non-`CANCELLED` audit of the same auditor"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_exited_facility_booking
        """
        fac_a, auditor, au_b = exited_facility_scenario(api)
        resp = api.create_audit(
            create_audit_payload(
                fac_a["id"], auditor["id"],
                scheduled_start="2026-09-02T00:00:00Z",
                scheduled_end="2026-09-04T00:00:00Z",
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_ACTIVE)
        listed, _ = validate_paginated(
            api.list_audits(OFFICER, params={"facility_id": fac_a["id"]})
        )
        assert listed == [], "the rejected request creates no audit"
        untouched = validate_success(api.get_audit(au_b["id"], OFFICER))
        assert untouched["status"] == "SCHEDULED", (
            "the auditor's pre-existing booking is untouched"
        )



class TestSchedulingExclusivity:
    def test_schedule_second_open_audit_rejected(self, api):
        """PRD §3.3: "At most one open audit — one in `SCHEDULED`,
        `IN_PROGRESS`, or `REPORT_SUBMITTED` — may exist per facility
        (`ERR_AUDIT_ALREADY_OPEN`)."

        Design: Corner/validations/schedule_second_open_audit_rejected
        """
        ctx, facility, auditor = active_program("Quebec A")
        auditor2 = create_auditor(full_name="Second Auditor")
        first = schedule_audit(facility["id"], auditor["id"])
        assert first["status"] == "SCHEDULED"
        # 30+ days later, a different auditor, no window overlap: only the
        # open-audit exclusivity rule can fail.
        resp = api.create_audit(
            create_audit_payload(
                facility["id"], auditor2["id"], audit_type="FOLLOW_UP",
                scheduled_start="2026-10-10T00:00:00Z",
                scheduled_end="2026-10-11T00:00:00Z",
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_ALREADY_OPEN, 409)

    def test_annual_audit_blocked_by_mutual_recognition(self, api):
        """PRD §3.3: "Finally, an `ANNUAL` audit is refused while a valid
        accepted mutual-recognition claim covers the facility
        (`ERR_COVERED_BY_MUTUAL_RECOGNITION`)."
        PRD §3.9: "A claim counts as valid for this extension, and for blocking
        `ANNUAL` audit creation under `ERR_COVERED_BY_MUTUAL_RECOGNITION`
        (§3.3), while its `external_audit_date` lies within its program's
        validity months of the current clock."

        Design: Corner/validations/annual_blocked_by_valid_mutual_recognition
        """
        ctx = setup_active_supplier(legal_name="Romeo A", sector="FOOD")
        facility = create_facility(ctx["supplier"]["id"], name="Site G")
        claim = create_claim(
            facility["id"], ctx["supplier"]["id"], program_name="SMETA",
            external_audit_ref="EXT-7",
            external_audit_date="2026-07-01T00:00:00Z", external_score=80,
        )
        accepted = decide_claim(claim["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED"
        auditor = create_auditor()

        blocked = api.create_audit(
            create_audit_payload(
                facility["id"], auditor["id"], audit_type="ANNUAL",
                scheduled_start="2026-10-01T00:00:00Z",
                scheduled_end="2026-10-02T00:00:00Z",
            ),
            COORD,
        )
        validate_error(blocked, ApiErrorId.ERR_COVERED_BY_MUTUAL_RECOGNITION, 409)

        ok = validate_success(
            api.create_audit(
                create_audit_payload(
                    facility["id"], auditor["id"], audit_type="INITIAL",
                    scheduled_start="2026-10-01T00:00:00Z",
                    scheduled_end="2026-10-02T00:00:00Z",
                ),
                COORD,
            ),
            201,
        )
        assert ok["status"] == "SCHEDULED", (
            "mutual recognition blocks ANNUAL only, not other audit types"
        )


class TestAuditorPoolRules:
    def test_auditor_country_not_covered_rejected(self, api):
        """PRD §3.3: "The facility's `country_code` must appear in the auditor's
        `country_codes_covered` (`ERR_AUDITOR_COUNTRY_NOT_COVERED`, 422)."

        Design: Corner/validations/auditor_country_not_covered_rejected
        """
        ctx = setup_active_supplier(legal_name="Sierra A", sector="FOOD")
        facility = create_facility(ctx["supplier"]["id"], name="Site F")
        auditor = create_auditor(full_name="India Only",
                                 country_codes_covered=("IN",))
        resp = api.create_audit(
            create_audit_payload(facility["id"], auditor["id"]), COORD
        )
        validate_error(resp, ApiErrorId.ERR_AUDITOR_COUNTRY_NOT_COVERED, 422)

    def test_assign_inactive_auditor_rejected(self, api):
        """PRD §3.3: "the assigned auditor must be `ACTIVE`
        (`ERR_AUDITOR_NOT_ACTIVE`)"
        PRD §3.3: "Deactivation moves an auditor `ACTIVE → INACTIVE` but is
        blocked while the auditor still holds audits in `SCHEDULED`,
        `IN_PROGRESS`, or `REPORT_SUBMITTED` (`ERR_AUDITOR_HAS_OPEN_AUDITS`)."

        Design: Corner/validations/assign_inactive_auditor_rejected
        """
        ctx, facility, _ = active_program("Uniform A")
        auditor = create_auditor(full_name="Retiring Auditor")
        deactivated = validate_success(
            api.deactivate_auditor(auditor["id"], COORD)
        )
        assert deactivated["status"] == "INACTIVE"
        resp = api.create_audit(
            create_audit_payload(facility["id"], auditor["id"]), COORD
        )
        validate_error(resp, ApiErrorId.ERR_AUDITOR_NOT_ACTIVE, 409)

    def test_deactivate_auditor_with_open_audit_rejected(self, api):
        """PRD §3.3: "Deactivation moves an auditor `ACTIVE → INACTIVE` but is
        blocked while the auditor still holds audits in `SCHEDULED`,
        `IN_PROGRESS`, or `REPORT_SUBMITTED` (`ERR_AUDITOR_HAS_OPEN_AUDITS`)."

        Design: Corner/validations/deactivate_auditor_with_open_audit_rejected
        """
        ctx, facility, auditor = active_program("Tango A")
        audit = schedule_audit(facility["id"], auditor["id"])
        blocked = api.deactivate_auditor(auditor["id"], COORD)
        validate_error(blocked, ApiErrorId.ERR_AUDITOR_HAS_OPEN_AUDITS, 409)

        cancel_audit(audit["id"], reason="Rescoped")
        deactivated = validate_success(
            api.deactivate_auditor(auditor["id"], COORD)
        )
        assert deactivated["status"] == "INACTIVE"


class TestWindowShapeAndStart:
    def test_semi_announced_window_too_short_rejected(self, api):
        """PRD §3.3: "The window shape itself must be sane — an `ANNOUNCED`
        audit spans 1 to 10 days, a `SEMI_ANNOUNCED` audit spans 14 to 60 days,
        and `scheduled_start` must be at or after the current logical clock
        (`ERR_INVALID_AUDIT_WINDOW`, 422)."

        Design: Corner/validations/audit_create_semi_announced_window_too_short_rejected
        """
        ctx, facility, auditor = active_program("Delta C")
        # 7 days: below the 14-day SEMI_ANNOUNCED minimum.
        resp = api.create_audit(
            create_audit_payload(
                facility["id"], auditor["id"], announcement="SEMI_ANNOUNCED",
                scheduled_start="2026-09-01T00:00:00Z",
                scheduled_end="2026-09-08T00:00:00Z",
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AUDIT_WINDOW, 422)
        # Exactly 14 days: the inclusive lower bound passes.
        ok = validate_success(
            api.create_audit(
                create_audit_payload(
                    facility["id"], auditor["id"], announcement="SEMI_ANNOUNCED",
                    scheduled_start="2026-09-01T00:00:00Z",
                    scheduled_end="2026-09-15T00:00:00Z",
                ),
                COORD,
            ),
            201,
        )
        assert ok["status"] == "SCHEDULED"

    def test_announced_window_too_long_rejected(self, api):
        """PRD §3.3: "an `ANNOUNCED` audit spans 1 to 10 days, a
        `SEMI_ANNOUNCED` audit spans 14 to 60 days, and `scheduled_start` must
        be at or after the current logical clock (`ERR_INVALID_AUDIT_WINDOW`,
        422)."

        Design: Corner/validations/audit_create_announced_window_too_long_rejected
        """
        ctx, facility, auditor = active_program("Echo C")
        # 15 days: above the 10-day ANNOUNCED maximum.
        resp = api.create_audit(
            create_audit_payload(
                facility["id"], auditor["id"], announcement="ANNOUNCED",
                scheduled_start="2026-09-01T00:00:00Z",
                scheduled_end="2026-09-16T00:00:00Z",
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AUDIT_WINDOW, 422)

    def test_start_before_window_rejected(self, api):
        """PRD §3.3: "Starting requires the audit to be `SCHEDULED`
        (`ERR_AUDIT_INVALID_STATE`), the caller to be the audit's own lead —
        `X-User-ID` must equal the audit's `auditor_id`
        (`ERR_OWNERSHIP_VIOLATION`) — and the logical clock to have reached
        `scheduled_start` (`ERR_AUDIT_WINDOW_NOT_OPEN`)."

        Design: Corner/validations/start_before_window_rejected
        """
        ctx, facility, auditor = active_program("Charlie C")
        audit = schedule_audit(
            facility["id"], auditor["id"],
            scheduled_start="2026-09-10T00:00:00Z",
            scheduled_end="2026-09-12T00:00:00Z",
        )
        # The default logical clock (2026-08-01) is before scheduled_start.
        early = api.start_audit(audit["id"], make_auditor_headers(auditor["id"]))
        validate_error(early, ApiErrorId.ERR_AUDIT_WINDOW_NOT_OPEN, 409)

        set_clock("2026-09-10T00:00:00Z")
        started = validate_success(
            api.start_audit(audit["id"], make_auditor_headers(auditor["id"]))
        )
        assert started["status"] == "IN_PROGRESS"

    def test_audit_start_immediately_visible(self, api):
        """PRD §2.10: "Consistency is immediate: every cascade and recompute
        described in §3 completes synchronously within the triggering request"
        PRD §3.3: "The audit moves `SCHEDULED → IN_PROGRESS`."

        Design: Corner/consistency_model/audit_start_immediate_visibility
        """
        ctx = setup_in_progress_audit(supplier_name="Tango D",
                                      facility_name="Site J2")
        assert ctx["audit"]["status"] == "IN_PROGRESS", (
            "the start mutation is visible in the same response"
        )
        reread = validate_success(api.get_audit(ctx["audit"]["id"], OFFICER))
        assert reread["status"] == "IN_PROGRESS", (
            "the mutation is visible to an independent read by another role"
        )


def exited_facility_scenario(api):
    """facA exited (no audits of its own), facB holds the auditor's
    [2026-09-01, 2026-09-05) SCHEDULED audit, so a fresh booking at facA with
    the same auditor would violate both the facility-state rule and the auditor
    double-booking rule."""
    ctx = setup_active_supplier(legal_name="India Textiles", sector="APPAREL")
    fac_a = create_facility(ctx["supplier"]["id"], name="Site A")
    fac_b = create_facility(ctx["supplier"]["id"], name="Site B")
    auditor = create_auditor()
    au_b = schedule_audit(
        fac_b["id"], auditor["id"],
        scheduled_start="2026-09-01T00:00:00Z",
        scheduled_end="2026-09-05T00:00:00Z",
    )
    exited = validate_success(
        api.exit_facility(fac_a["id"], {"exit_reason": "Site closed"}, ADMIN)
    )
    assert exited["status"] == "EXITED"
    return fac_a, auditor, au_b
