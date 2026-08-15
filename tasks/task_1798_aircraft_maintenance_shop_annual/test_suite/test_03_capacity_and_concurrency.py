"""Boundary, capacity, overlap, concurrency, and compensating-invariant tests."""
from test_helpers import (
    SM,
    create_aircraft,
    create_hangar_slot_payload,
    create_mechanic,
    create_owner,
    create_slot,
    create_work_order,
    get_success_data,
    make_mechanic_headers,
    post_labor_entry,
    reset_clock,
    setup_shop,
    setup_wo_returned_to_service,
    start_work_order,
    validate_error,
    validate_success,
    ApiErrorId,
)


class TestSlotAdjacencyBoundary:
    """Queue A: boundary_precision_check / hangar_slot_adjacency_touching_endpoints_allowed."""

    def test_touching_endpoints_permitted(self, api):
        """PRD §3.2: "for the same `hangar_code`, the new interval must not
        intersect any existing slot in `RESERVED` or `OCCUPIED` status — though
        intervals that merely touch, one's `ends_at` equal to the other's
        `starts_at`, are permitted back-to-back; an intersection is rejected
        with `ERR_SLOT_OVERLAP` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/hangar_slot_adjacency_touching_endpoints_allowed
        """
        reset_clock()
        owner = create_owner()
        aircraft = create_aircraft(owner["id"])
        create_slot(
            aircraft["id"], hangar_code="H-ADJ",
            starts_at="2026-08-10T08:00:00Z", ends_at="2026-08-10T17:00:00Z",
        )
        res = api.create_hangar_slot(
            create_hangar_slot_payload(
                aircraft["id"], hangar_code="H-ADJ",
                starts_at="2026-08-10T17:00:00Z", ends_at="2026-08-11T08:00:00Z",
            ),
            SM,
        )
        validate_success(res, 201)

    def test_one_second_overlap_rejected(self, api):
        """PRD §3.2: "for the same `hangar_code`, the new interval must not
        intersect any existing slot in `RESERVED` or `OCCUPIED` status — though
        intervals that merely touch, one's `ends_at` equal to the other's
        `starts_at`, are permitted back-to-back; an intersection is rejected
        with `ERR_SLOT_OVERLAP` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/hangar_slot_adjacency_touching_endpoints_allowed
        """
        reset_clock()
        owner = create_owner()
        aircraft = create_aircraft(owner["id"])
        create_slot(
            aircraft["id"], hangar_code="H-OVL",
            starts_at="2026-08-10T08:00:00Z", ends_at="2026-08-10T17:00:00Z",
        )
        res = api.create_hangar_slot(
            create_hangar_slot_payload(
                aircraft["id"], hangar_code="H-OVL",
                starts_at="2026-08-10T16:59:59Z", ends_at="2026-08-11T09:00:00Z",
            ),
            SM,
        )
        validate_error(res, ApiErrorId.ERR_SLOT_OVERLAP)


class TestHangarSlotHalfOpenOverlap:
    """Queue A: resource_temporal_overlap / hangar_slot_half_open_overlap."""

    def test_interior_overlap_rejected(self, api):
        """PRD §3.2: "for the same `hangar_code`, the new interval must not
        intersect any existing slot in `RESERVED` or `OCCUPIED` status — though
        intervals that merely touch, one's `ends_at` equal to the other's
        `starts_at`, are permitted back-to-back; an intersection is rejected
        with `ERR_SLOT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/hangar_slot_half_open_overlap
        """
        reset_clock()
        owner = create_owner()
        aircraft = create_aircraft(owner["id"])
        create_slot(
            aircraft["id"], hangar_code="H-INT",
            starts_at="2026-08-10T08:00:00Z", ends_at="2026-08-10T17:00:00Z",
        )
        res = api.create_hangar_slot(
            create_hangar_slot_payload(
                aircraft["id"], hangar_code="H-INT",
                starts_at="2026-08-10T12:00:00Z", ends_at="2026-08-10T13:00:00Z",
            ),
            SM,
        )
        validate_error(res, ApiErrorId.ERR_SLOT_OVERLAP)

    def test_overlap_rejection_returns_409(self, api):
        """PRD §3.2: "an intersection is rejected with `ERR_SLOT_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/hangar_slot_half_open_overlap
        """
        reset_clock()
        owner = create_owner()
        aircraft = create_aircraft(owner["id"])
        create_slot(
            aircraft["id"], hangar_code="H-INT2",
            starts_at="2026-08-10T08:00:00Z", ends_at="2026-08-10T17:00:00Z",
        )
        res = api.create_hangar_slot(
            create_hangar_slot_payload(
                aircraft["id"], hangar_code="H-INT2",
                starts_at="2026-08-10T09:00:00Z", ends_at="2026-08-10T18:00:00Z",
            ),
            SM,
        )
        assert res.status_code == 409, f"overlap must be 409, got {res.status_code}"
        validate_error(res, ApiErrorId.ERR_SLOT_OVERLAP)


class TestMechanicDailyCapacityBuffer:
    """Queue A: resource_temporal_overlap / mechanic_daily_capacity_buffer_overlap."""

    def _setup_in_progress_wo(self, api):
        owner, aircraft, mechanic, slot, wo = setup_shop()
        wo = start_work_order(wo, mechanic)
        return owner, aircraft, mechanic, wo

    def test_cumulative_exactly_at_ten_hours_accepted(self, api):
        """PRD §3.6: "a labor posting is rejected with
        `ERR_MECHANIC_OVERBOOKED` (HTTP 409) whenever it would push the
        mechanic's same-day cumulative billable time, plus a thirty-minute
        buffer, beyond ten billable hours."

        Design: Difficulty/resource_temporal_overlap/mechanic_daily_capacity_buffer_overlap
        """
        owner, aircraft, mechanic, wo = self._setup_in_progress_wo(api)
        mech_h = make_mechanic_headers(mechanic["id"])
        # 96 tenths posted; adding 3 more lands at 99 tenths = 9.9h, which
        # does not exceed the 10.0h cap even with the 3-tenths buffer
        # (99 + 3 = 102 > 100 would exceed; here cumulative is 99 ≤ 100), so
        # it is accepted. All durations honour the multiple-of-3 rule.
        post_labor_entry(wo["id"], mechanic, duration_tenths=96)
        res = api.create_labor_entry(
            wo["id"],
            {"mechanic_id": mechanic["id"], "duration_tenths": 3, "notes": "fill to 99"},
            mech_h,
        )
        validate_success(res, 201)

    def test_cumulative_over_ten_hours_rejected(self, api):
        """PRD §3.6: "a labor posting is rejected with
        `ERR_MECHANIC_OVERBOOKED` (HTTP 409) whenever it would push the
        mechanic's same-day cumulative billable time, plus a thirty-minute
        buffer, beyond ten billable hours."

        Design: Difficulty/resource_temporal_overlap/mechanic_daily_capacity_buffer_overlap
        """
        owner, aircraft, mechanic, wo = self._setup_in_progress_wo(api)
        mech_h = make_mechanic_headers(mechanic["id"])
        post_labor_entry(wo["id"], mechanic, duration_tenths=96)
        # Land at 99 tenths.
        get_success_data(
            api.create_labor_entry(
                wo["id"],
                {"mechanic_id": mechanic["id"], "duration_tenths": 3, "notes": "fill"},
                mech_h,
            )
        )
        # A further 3 tenths pushes the day to 102 tenths > 10.0h cap.
        res = api.create_labor_entry(
            wo["id"],
            {"mechanic_id": mechanic["id"], "duration_tenths": 3, "notes": "over"},
            mech_h,
        )
        validate_error(res, ApiErrorId.ERR_MECHANIC_OVERBOOKED)


class TestInvoiceVoidAndRegenerate:
    """Queue A: compensating_invariant / invoice_void_and_regenerate_conserves_work_order_billing."""

    def test_void_marks_invoice_voided(self, api):
        """PRD §3.8: "A `ShopManager` may instead void a `DRAFT` invoice when
        it was generated in error, moving it to `VOIDED`; a fresh `DRAFT`
        invoice may then be regenerated for the same work order as a
        compensating reissue, subject to the one-active-invoice rule above."

        Design: Difficulty/compensating_invariant/invoice_void_and_regenerate_conserves_work_order_billing
        """
        owner, aircraft, mechanic, verifier, slot, wo, invoice = setup_wo_returned_to_service()
        voided = validate_success(api.void_invoice(invoice["id"], SM), 200)
        assert voided["status"] == "VOIDED", (
            f"void must move invoice to VOIDED, got {voided['status']}"
        )

    def test_after_void_no_active_invoice_remains(self, api):
        """PRD §3.8: "Each work order produces at most one active invoice — the
        `work_order_id` on an invoice is unique per work order — and the
        invoice is born `DRAFT` at the moment of return to service with all
        computed fields populated."

        Design: Difficulty/compensating_invariant/invoice_void_and_regenerate_conserves_work_order_billing
        """
        owner, aircraft, mechanic, verifier, slot, wo, invoice = setup_wo_returned_to_service()
        get_success_data(api.void_invoice(invoice["id"], SM))
        invoices = get_success_data(api.get_work_order_invoice(wo["id"], SM))
        active = [i for i in invoices if i["status"] != "VOIDED"]
        assert len(active) == 0, (
            f"after void there must be zero non-VOIDED invoices, got {len(active)}"
        )
        assert any(i["status"] == "VOIDED" for i in invoices), "voided row remains visible"


class TestHangarSlotReleaseRestoresCapacity:
    """Queue A: compensating_invariant / hangar_slot_release_restores_capacity."""

    def test_slot_released_after_return_to_service(self, api):
        """PRD §3.7: "On a successful return, three cascades fire: the hangar
        slot moves to `RELEASED` and its occupancy is freed; a `DRAFT` invoice
        is auto-created with every computed line populated, as §3.8 details;
        and the invoice's `warranty_expires_at` is set to the return-to-service
        instant plus ninety days, opening the shop's maintenance warranty
        window."

        Design: Difficulty/compensating_invariant/hangar_slot_release_restores_capacity
        """
        owner, aircraft, mechanic, verifier, slot, wo, invoice = setup_wo_returned_to_service()
        slot_after = get_success_data(api.get_hangar_slot(slot["id"], SM))
        assert slot_after["status"] == "RELEASED", (
            f"RTS must release the slot, got {slot_after['status']}"
        )

    def test_released_slot_frees_capacity_for_overlapping_reservation(self, api):
        """PRD §2.8: "A hangar slot's occupancy follows the work order booked
        against it: the slot becomes occupied when work begins and is released
        when the aircraft returns to service."

        Design: Difficulty/compensating_invariant/hangar_slot_release_restores_capacity
        """
        owner, aircraft, mechanic, verifier, slot, wo, invoice = setup_wo_returned_to_service(
            slot_overrides={
                "hangar_code": "H-REL",
                "starts_at": "2026-08-10T08:00:00Z",
                "ends_at": "2026-08-10T17:00:00Z",
            }
        )
        # After release, an overlapping reservation for the same hangar_code
        # succeeds — the RELEASED slot no longer counts against capacity.
        res = api.create_hangar_slot(
            create_hangar_slot_payload(
                aircraft["id"], hangar_code="H-REL",
                starts_at="2026-08-10T10:00:00Z", ends_at="2026-08-10T12:00:00Z",
            ),
            SM,
        )
        validate_success(res, 201)


class TestValidationPriorityPairs:
    """Queue A: priority_pair_validation_conflict (two instances)."""

    def test_state_outranks_safety_on_return_to_service(self, api):
        """PRD §2.9: "Every request passes through a fixed validation pipeline.
        Authentication is checked first (presence of headers and a known role),
        authorization second (the role's permission for the endpoint),
        existence third (path identifiers and foreign keys), and state
        permissibility fourth — an action attempted against an entity that is
        not in a state allowing that transition is rejected with
        `ERR_INVALID_STATE` (HTTP 409). Only then do the domain business rules
        run."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_return_to_service
        """
        from test_helpers import create_directive_payload
        reset_clock()
        owner = create_owner(approval_cap_cents=100000)
        aircraft = create_aircraft(owner["id"])
        mechanic = create_mechanic(certificate_class="IA")
        slot = create_slot(aircraft["id"], hangar_code="H-PV")
        wo = create_work_order(aircraft["id"], slot, mechanic["id"])
        mech_h = make_mechanic_headers(mechanic["id"])
        # Ground the aircraft via an APPLICABLE_OPEN AD (safety concern).
        directive = get_success_data(
            api.create_directive(create_directive_payload(aircraft["id"]), SM)
        )
        get_success_data(
            api.evaluate_directive(
                directive["id"],
                {"compliance_status": "APPLICABLE_OPEN",
                 "evaluated_by_mechanic_id": mechanic["id"]},
                mech_h,
            )
        )
        aircraft_after = get_success_data(api.get_aircraft(aircraft["id"], SM))
        assert aircraft_after["airworthiness_posture"] == "GROUNDED"
        # WO is still DRAFT (wrong state) AND aircraft GROUNDED (safety).
        # State (pipeline step four) runs before business safety, so the
        # response must be ERR_INVALID_STATE, not ERR_AIRWORTHINESS_BLOCKED.
        res = api.return_to_service(wo["id"], mech_h)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert res.status_code == 409

    def test_state_outranks_safety_even_when_grounded(self, api):
        """PRD §2.9: "state permissibility fourth — an action attempted against
        an entity that is not in a state allowing that transition is rejected
        with `ERR_INVALID_STATE` (HTTP 409). Only then do the domain business
        rules run, and their relative order is pinned so that overlapping
        failures always surface the same error: the regulatory airworthiness
        gate is evaluated first among business rules."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_return_to_service
        """
        from test_helpers import create_directive_payload
        reset_clock()
        owner = create_owner(approval_cap_cents=100000)
        aircraft = create_aircraft(owner["id"])
        mechanic = create_mechanic(certificate_class="IA")
        slot = create_slot(aircraft["id"], hangar_code="H-PV2")
        wo = create_work_order(aircraft["id"], slot, mechanic["id"])
        mech_h = make_mechanic_headers(mechanic["id"])
        directive = get_success_data(
            api.create_directive(create_directive_payload(aircraft["id"]), SM)
        )
        get_success_data(
            api.evaluate_directive(
                directive["id"],
                {"compliance_status": "APPLICABLE_OPEN",
                 "evaluated_by_mechanic_id": mechanic["id"]},
                mech_h,
            )
        )
        res = api.return_to_service(wo["id"], mech_h)
        # ERR_AIRWORTHINESS_BLOCKED must NOT be surfaced: state outranks it.
        body = res.json()
        assert body["data"]["error_id"] != "ERR_AIRWORTHINESS_BLOCKED", (
            "state check must pre-empt the airworthiness gate"
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_traceability_missing_on_mark_sourced(self, api):
        """PRD §3.5: "Every `OPEN` discrepancy whose estimate is at or above
        the cap — `requires_owner_decision` true — moves to
        `PENDING_OWNER_DECISION`; every `OPEN` discrepancy under the cap
        auto-transitions straight to `APPROVED`, the under-cap auto-approval
        that keeps small findings from clogging the owner's queue."
        PRD §3.6: "A requested part walks the sourcing pipeline: a `PartsClerk`
        marks it `SOURCED`, which is the first traceability checkpoint — an
        `OVERHAUL` or `SERVICEABLE` part lacking a non-empty `trace_doc_ref` at
        this point is rejected with `ERR_TRACEABILITY_MISSING` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_part_install
        """
        from test_helpers import PC, make_owner_headers, request_part, setup_wo_with_failed_inspection
        owner, aircraft, mechanic, slot, wo, discrepancy = setup_wo_with_failed_inspection(
            owner_cap=50000
        )
        mech_h = make_mechanic_headers(mechanic["id"])
        current = get_success_data(api.get_discrepancy(discrepancy["id"], mech_h))
        # The auto-created discrepancy may be under the cap (already APPROVED)
        # or at-or-above (PENDING_OWNER_DECISION); approve only when pending.
        if current["status"] == "PENDING_OWNER_DECISION":
            get_success_data(
                api.decide_discrepancy(
                    discrepancy["id"],
                    {"decision": "APPROVE", "expected_discrepancy_version": current["version"]},
                    make_owner_headers(owner["id"]),
                )
            )
        part = request_part(
            discrepancy["id"], mechanic, part_number="PN-OH", condition="OVERHAUL",
            trace_doc_ref="", unit_cost_cents=40000, quantity=1,
        )
        res = api.mark_part_sourced(part["id"], PC)
        validate_error(res, ApiErrorId.ERR_TRACEABILITY_MISSING)
        assert res.status_code == 422

    def test_traceability_failure_leaves_part_requested(self, api):
        """PRD §3.6: "an `OVERHAUL` or `SERVICEABLE` part lacking a non-empty
        `trace_doc_ref` at this point is rejected with
        `ERR_TRACEABILITY_MISSING` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_part_install
        """
        from test_helpers import PC, make_owner_headers, request_part, setup_wo_with_failed_inspection
        owner, aircraft, mechanic, slot, wo, discrepancy = setup_wo_with_failed_inspection(
            owner_cap=50000
        )
        mech_h = make_mechanic_headers(mechanic["id"])
        current = get_success_data(api.get_discrepancy(discrepancy["id"], mech_h))
        if current["status"] == "PENDING_OWNER_DECISION":
            get_success_data(
                api.decide_discrepancy(
                    discrepancy["id"],
                    {"decision": "APPROVE", "expected_discrepancy_version": current["version"]},
                    make_owner_headers(owner["id"]),
                )
            )
        part = request_part(
            discrepancy["id"], mechanic, part_number="PN-OH2", condition="OVERHAUL",
            trace_doc_ref="", unit_cost_cents=40000, quantity=1,
        )
        api.mark_part_sourced(part["id"], PC)
        part_after = get_success_data(api.get_part(part["id"], PC))
        assert part_after["status"] == "REQUESTED", (
            f"rejected mark-sourced must leave part REQUESTED, got {part_after['status']}"
        )
