"""Movement permits and movement records: issuance gates, windows, headrooms,
fees, lifecycle transitions, and cascade interactions (PRD §2.9, §3.5, §3.6)."""
from test_helpers import (
    AUDITOR,
    DEFAULTS,
    ApiErrorId,
    assert_movement_permit,
    assert_movement_record,
    create_and_escalate_zone,
    create_draft_certificate,
    create_issued_certificate,
    create_issued_permit,
    create_requested_permit,
    create_scheduled_record,
    get_permit,
    get_premises,
    issue_certificate,
    make_vet_headers,
    set_clock,
    setup_issued_certificate_with_permit,
    setup_standard_scenario,
    submit_certificate,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPermitCreationDefaults:
    def test_permit_computed_headrooms_at_creation(self, api, admin_headers):
        """PRD §3.5: "the permit itself is born `REQUESTED`, with
        `permit_number` null until issuance."
        PRD §3.5: "`committed_headroom` is the `allocated_head_count`
        minus the summed `head_count` of the permit's movement records in
        `SCHEDULED`, `IN_TRANSIT`, or `DELIVERED`; this is the figure that
        gates scheduling."
        PRD §3.5: "`projected_headroom` subtracts only records in `IN_TRANSIT`
        or `DELIVERED`, treating merely-scheduled shipments as not yet consumed
        — so a permit allocated for 20 animals with one scheduled record of 6
        reports a `committed_headroom` of 14 and a `projected_headroom` of 20."
        PRD §3.5: "`total_movement_fees_cents` sums the per-record fees over
        records in `SCHEDULED`, `IN_TRANSIT`, or `DELIVERED`; cancelled records
        contribute nothing."

        Design: Corner/entities/permit_computed_headrooms_at_creation
        """
        scenario, cert = create_issued_certificate()
        resp = api.create_movement_permit(
            {
                "certificate_id": cert["id"],
                "allocated_head_count": 10,
                "valid_from": "2026-08-11T00:00:00Z",
                "valid_until": "2026-09-08T00:00:00Z",
            },
            make_vet_headers(scenario["vet"]["id"]),
        )
        permit = validate_success(resp, 201)
        assert_movement_permit(permit)
        assert permit["status"] == "REQUESTED"
        assert permit["permit_number"] is None
        assert permit["committed_headroom"] == 10, "nothing consumed yet"
        assert permit["projected_headroom"] == 10
        assert permit["total_movement_fees_cents"] == 0


class TestPermitIssueGates:
    def test_permit_issue_allocation_floor(self, api, admin_headers, officer_headers):
        """PRD §3.5: "the `allocated_head_count` must be at least the
        certificate's `head_count`, else
        `ERR_ALLOCATION_BELOW_CERTIFICATE_HEADCOUNT` (HTTP 422)".
        PRD §3.5: "the permit must be `REQUESTED` and its backing certificate
        must be `ISSUED` or `TRANSMITTED` — either failure is
        `ERR_PERMIT_NOT_ISSUABLE` (HTTP 409)".
        PRD §2.10: "Issuing a movement permit mints its `permit_number` in the
        form `EP-<destination state code>-<six-digit sequence>` — for example
        `EP-KS-000001`."

        Design: Corner/state_machines/permit_issue_allocation_floor
        """
        scenario, cert = create_issued_certificate()  # 10 head CATTLE
        vet_h = make_vet_headers(scenario["vet"]["id"])
        perm_low = create_requested_permit(cert["id"], scenario["vet"]["id"], allocated_head_count=5)
        perm_ok = create_requested_permit(cert["id"], scenario["vet"]["id"], allocated_head_count=10)

        resp_low = api.issue_movement_permit(perm_low["id"], officer_headers)
        validate_error(resp_low, ApiErrorId.ERR_ALLOCATION_BELOW_CERTIFICATE_HEADCOUNT)
        assert get_permit(perm_low["id"])["status"] == "REQUESTED"

        issued = validate_success(api.issue_movement_permit(perm_ok["id"], officer_headers), 200)
        assert issued["status"] == "ISSUED", "allocation equal to head_count is inclusive-valid"
        assert issued["permit_number"] == "EP-KS-000001"

        resp_again = api.issue_movement_permit(perm_ok["id"], officer_headers)
        validate_error(resp_again, ApiErrorId.ERR_PERMIT_NOT_ISSUABLE)

    def test_permit_window_containment_boundaries(self, api, admin_headers, officer_headers):
        """PRD §2.9: "Window containment uses inclusive bounds. A permit may be
        issued only when its `valid_from` is at or after the certificate's
        `issued_at` and its `valid_until` is at or before the certificate's
        `valid_until`."
        PRD §3.5: "the permit window must sit inside certificate validity per
        §2.9, else `ERR_PERMIT_WINDOW_OUTSIDE_CVI_VALIDITY` (HTTP 422)".

        Design: Corner/state_machines/permit_window_containment_boundaries
        """
        scenario, cert = create_issued_certificate()
        # issued_at 2026-08-10T00:00:00Z, valid_until 2026-09-09T00:00:00Z.
        perm_early = create_requested_permit(
            cert["id"], scenario["vet"]["id"],
            allocated_head_count=10,
            valid_from="2026-08-09T00:00:00Z", valid_until="2026-09-08T00:00:00Z",
        )
        perm_late = create_requested_permit(
            cert["id"], scenario["vet"]["id"],
            allocated_head_count=10,
            valid_from="2026-08-11T00:00:00Z", valid_until="2026-09-10T00:00:00Z",
        )
        perm_exact = create_requested_permit(
            cert["id"], scenario["vet"]["id"],
            allocated_head_count=10,
            valid_from="2026-08-10T00:00:00Z", valid_until="2026-09-09T00:00:00Z",
        )

        validate_error(
            api.issue_movement_permit(perm_early["id"], officer_headers),
            ApiErrorId.ERR_PERMIT_WINDOW_OUTSIDE_CVI_VALIDITY,
        )
        validate_error(
            api.issue_movement_permit(perm_late["id"], officer_headers),
            ApiErrorId.ERR_PERMIT_WINDOW_OUTSIDE_CVI_VALIDITY,
        )
        exact = validate_success(
            api.issue_movement_permit(perm_exact["id"], officer_headers), 200
        )
        assert exact["status"] == "ISSUED", "the exact envelope issues (both bounds inclusive)"


class TestPermitAdjustStateGate:
    def test_permit_adjust_requires_issued_state(self, api, admin_headers, officer_headers):
        """PRD §3.5: "Officers may later adjust an `ISSUED` permit's
        `allocated_head_count` or `valid_until` through the version-guarded
        operation of §2.8; adjusting a permit that is not `ISSUED` fails with
        `ERR_PERMIT_NOT_ADJUSTABLE` (HTTP 409)".

        Design: Corner/state_machines/permit_adjust_requires_issued_state
        """
        scenario, cert = create_issued_certificate()
        permit = create_requested_permit(cert["id"], scenario["vet"]["id"], allocated_head_count=10)

        resp = api.adjust_movement_permit(
            permit["id"],
            {"expected_permit_version": permit["version"], "allocated_head_count": 12},
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ADJUSTABLE)
        assert get_permit(permit["id"])["allocated_head_count"] == 10

    def test_permit_adjust_allocation_gates(self, api, admin_headers, officer_headers):
        """PRD §3.5: "the new allocation may not drop below the head count
        already consumed — the allocation minus the `committed_headroom` — or
        the request fails with `ERR_ALLOCATION_BELOW_CONSUMED` (HTTP 422)."
        PRD §2.8: "a successful adjustment increments the permit's `version`
        by one and recomputes its headrooms and fee totals."

        Design: Corner/state_machines/permit_adjust_allocation_gates
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=6)
        permit_now = get_permit(permit["id"])

        # Consumed = 10 - 4 = 6; dropping the allocation to 5 is below consumed.
        resp_low = api.adjust_movement_permit(
            permit["id"],
            {"expected_permit_version": permit_now["version"], "allocated_head_count": 5},
            officer_headers,
        )
        validate_error(resp_low, ApiErrorId.ERR_ALLOCATION_BELOW_CONSUMED)

        # The rejected write left the version untouched, so the same expected
        # version still passes OCC for the succeeding adjustment.
        raised = validate_success(
            api.adjust_movement_permit(
                permit["id"],
                {"expected_permit_version": permit_now["version"], "allocated_head_count": 12},
                officer_headers,
            ),
            200,
        )
        assert raised["allocated_head_count"] == 12
        assert raised["committed_headroom"] == 6, "12 - 6 SCHEDULED = 6"


class TestPermitVoidedLockdown:
    def test_permit_voided_terminal_lockdown(self, api, admin_headers, officer_headers):
        """PRD §3.4: "Voiding detonates its own cascade, atomically:
        every movement permit belonging to the certificate whose `status` is
        `REQUESTED`, `ISSUED`, or `SUSPENDED` becomes `VOIDED`; on each such
        permit, every movement record in `SCHEDULED` or `IN_TRANSIT` becomes
        `CANCELLED`; and for each record cancelled out of `IN_TRANSIT`, the
        origin premises' `current_head_count` is restored by that record's
        `head_count`."
        PRD §3.5: "adjusting a permit that is not `ISSUED` fails with
        `ERR_PERMIT_NOT_ADJUSTABLE` (HTTP 409), and the new allocation may not
        drop below the head count already consumed — the allocation minus the
        `committed_headroom` — or the request fails with
        `ERR_ALLOCATION_BELOW_CONSUMED` (HTTP 422)".
        PRD §3.5: "the permit must be `REQUESTED` and its backing certificate
        must be `ISSUED` or `TRANSMITTED` — either failure is
        `ERR_PERMIT_NOT_ISSUABLE` (HTTP 409)".

        Design: Corner/state_machines/permit_voided_terminal_lockdown
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        validate_success(
            api.void_certificate(cert["id"], {"reason": "DISEASE_SUSPECT"}, officer_headers),
            200,
        )
        voided = get_permit(permit["id"])
        assert voided["status"] == "VOIDED"

        resp_patch = api.adjust_movement_permit(
            permit["id"],
            {"expected_permit_version": voided["version"], "allocated_head_count": 12},
            officer_headers,
        )
        validate_error(resp_patch, ApiErrorId.ERR_PERMIT_NOT_ADJUSTABLE)

        resp_issue = api.issue_movement_permit(permit["id"], officer_headers)
        validate_error(resp_issue, ApiErrorId.ERR_PERMIT_NOT_ISSUABLE)


class TestMovementRecordLifecycle:
    def test_movement_record_state_machine_enforcement(
        self, api, admin_headers, officer_headers
    ):
        """PRD §3.5: "Departure advances a record from `SCHEDULED` to
        `IN_TRANSIT` under the same ownership rule."
        PRD §3.5: "departing from any state other than the required one, or
        arriving from a state other than `IN_TRANSIT`, yields
        `ERR_MOVEMENT_NOT_ADVANCEABLE`. Cancellation is permitted from either
        `SCHEDULED` or `IN_TRANSIT` and moves the record to `CANCELLED`; from
        any other state it yields `ERR_MOVEMENT_NOT_ADVANCEABLE`."

        Design: Corner/state_machines/movement_record_state_machine_enforcement
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        record = create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=5)
        set_clock("2026-08-21T00:00:00Z")
        vet_h = make_vet_headers(scenario["vet"]["id"])

        departed = validate_success(api.depart_movement_record(record["id"], vet_h), 200)
        assert_movement_record(departed)
        assert departed["status"] == "IN_TRANSIT"
        assert departed["departed_at"] == "2026-08-21T00:00:00Z"

        validate_error(
            api.depart_movement_record(record["id"], vet_h),
            ApiErrorId.ERR_MOVEMENT_NOT_ADVANCEABLE,
        )

        arrived = validate_success(api.arrive_movement_record(record["id"], vet_h), 200)
        assert arrived["status"] == "DELIVERED"
        assert arrived["arrived_at"] == "2026-08-21T00:00:00Z"

        validate_error(
            api.arrive_movement_record(record["id"], vet_h),
            ApiErrorId.ERR_MOVEMENT_NOT_ADVANCEABLE,
        )
        validate_error(
            api.cancel_movement_record(record["id"], vet_h),
            ApiErrorId.ERR_MOVEMENT_NOT_ADVANCEABLE,
        )

    def test_movement_window_enforced_at_schedule_and_depart(
        self, api, admin_headers, officer_headers
    ):
        """PRD §2.9: "A movement — whether being scheduled against its
        `planned_ship_date` or departing at the logical clock instant — must
        satisfy all of the following: the instant is at or after the permit's
        `valid_from`, at or before the permit's `valid_until`, and at or before
        the certificate's `valid_until`."
        PRD §3.5: "the `planned_ship_date` inside the permit window and not
        after the certificate's `valid_until`
        (`ERR_MOVEMENT_OUTSIDE_PERMIT_WINDOW`)".

        Design: Corner/state_machines/movement_window_enforced_at_schedule_and_depart
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        # Permit window [2026-08-11, 2026-09-08]; certificate valid_until 2026-09-09.
        vet_h = make_vet_headers(scenario["vet"]["id"])

        resp_after = api.create_movement_record(
            {
                "permit_id": permit["id"],
                "head_count": 2,
                "destination_name": "KS Feedlot",
                "planned_ship_date": "2026-09-09T00:00:00Z",
            },
            vet_h,
        )
        validate_error(resp_after, ApiErrorId.ERR_MOVEMENT_OUTSIDE_PERMIT_WINDOW)

        resp_before = api.create_movement_record(
            {
                "permit_id": permit["id"],
                "head_count": 2,
                "destination_name": "KS Feedlot",
                "planned_ship_date": "2026-08-10T00:00:00Z",
            },
            vet_h,
        )
        validate_error(resp_before, ApiErrorId.ERR_MOVEMENT_OUTSIDE_PERMIT_WINDOW)

        # planned_ship_date == valid_from is inclusive-valid.
        record = create_scheduled_record(
            permit["id"], scenario["vet"]["id"],
            head_count=2, planned_ship_date="2026-08-11T00:00:00Z",
        )
        assert record["status"] == "SCHEDULED"

        # Departing while the clock (2026-08-10) precedes valid_from fails.
        validate_error(
            api.depart_movement_record(record["id"], vet_h),
            ApiErrorId.ERR_MOVEMENT_OUTSIDE_PERMIT_WINDOW,
        )
        # At clock == valid_from departure succeeds (inclusive bound).
        set_clock("2026-08-11T00:00:00Z")
        departed = validate_success(api.depart_movement_record(record["id"], vet_h), 200)
        assert departed["status"] == "IN_TRANSIT"


class TestCommittedVsProjectedHeadroom:
    def test_permit_headroom_committed_counts_scheduled(self, api, admin_headers):
        """PRD §3.5: "`committed_headroom` is the `allocated_head_count` minus
        the summed `head_count` of the permit's movement records in
        `SCHEDULED`, `IN_TRANSIT`, or `DELIVERED`; this is the figure that
        gates scheduling."

        Design: Difficulty/dual_variant_calc/permit_headroom_committed_vs_projected_diverge
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(
            allocation=20, cert_head_count=10
        )
        create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=6)

        data = get_permit(permit["id"])
        assert data["committed_headroom"] == 14, (
            f"20 allocated - 6 SCHEDULED = 14 committed, got {data['committed_headroom']}"
        )

    def test_permit_headroom_projected_ignores_scheduled(self, api, admin_headers):
        """PRD §3.5: "`projected_headroom` subtracts only records in
        `IN_TRANSIT` or `DELIVERED`, treating merely-scheduled shipments as not
        yet consumed — so a permit allocated for 20 animals with one scheduled
        record of 6 reports a `committed_headroom` of 14 and a
        `projected_headroom` of 20."

        Design: Difficulty/dual_variant_calc/permit_headroom_committed_vs_projected_diverge
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(
            allocation=20, cert_head_count=10
        )
        create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=6)

        data = get_permit(permit["id"])
        assert data["projected_headroom"] == 20, (
            f"SCHEDULED records do not count projected: expected 20, "
            f"got {data['projected_headroom']}"
        )
        assert data["committed_headroom"] != data["projected_headroom"], (
            "the two variants must diverge on identical underlying rows"
        )


class TestMovementFeeRounding:
    def test_movement_fee_per_line_rounding_pinned_line_items(self, api, admin_headers):
        """PRD §2.7: "Movement fees use fractional per-head rates, and each
        movement record's fee is rounded **half up to whole cents** before any
        aggregation takes place."
        PRD §3.5: "its `movement_fee_cents` is computed once, at creation: the
        record's `head_count` multiplied by the per-head movement rate for
        the species resolved through the permit to its certificate — 137.5
        cents for `CATTLE`, 62.5 for `SWINE`, 10.25 for `POULTRY`, 45.5 for
        `SHEEP_GOAT`, 210.75 for `EQUINE` — rounded half up to whole cents per
        the pinned order of §2.7."

        Design: Difficulty/combinatorial_formula/movement_fee_per_line_rounding_pinned
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        rec1 = create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=3)
        rec2 = create_scheduled_record(
            permit["id"], scenario["vet"]["id"], head_count=3,
            planned_ship_date="2026-08-22T00:00:00Z",
        )
        # round_half_up(3 * 137.5) = round_half_up(412.5) = 413 per line.
        assert rec1["movement_fee_cents"] == 413
        assert rec2["movement_fee_cents"] == 413

    def test_movement_fee_per_line_rounding_pinned_permit_total(self, api, admin_headers):
        """PRD §2.7: "The rounding order is pinned: per-line rounding first,
        summation second — summing unrounded products and rounding once at the
        end is a rejected interpretation."
        PRD §3.5: "`total_movement_fees_cents` sums the per-record fees over
        records in `SCHEDULED`, `IN_TRANSIT`, or `DELIVERED`; cancelled records
        contribute nothing."

        Design: Difficulty/combinatorial_formula/movement_fee_per_line_rounding_pinned
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=3)
        create_scheduled_record(
            permit["id"], scenario["vet"]["id"], head_count=3,
            planned_ship_date="2026-08-22T00:00:00Z",
        )
        permit = get_permit(permit["id"])
        # Per-line: 413 + 413 = 826. Sum-then-round would give
        # round_half_up(825.0) = 825 — the rejected interpretation.
        assert permit["total_movement_fees_cents"] == 826


class TestHeadroomExactFit:
    def test_permit_headroom_exact_fit_schedules(self, api, admin_headers):
        """PRD §3.5: "the shipment's `head_count` no greater than the permit's
        `committed_headroom` (`ERR_PERMIT_HEADROOM_EXCEEDED`, HTTP 422)" —
        equality therefore schedules.

        Design: Difficulty/boundary_precision_check/permit_headroom_exact_fit
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        record = create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=10)
        assert record["status"] == "SCHEDULED", (
            "head_count == committed_headroom must schedule (inclusive gate)"
        )
        assert get_permit(permit["id"])["committed_headroom"] == 0

    def test_permit_headroom_exact_fit_one_more_rejected(self, api, admin_headers):
        """PRD §3.5: "the shipment's `head_count` no greater than the permit's
        `committed_headroom` (`ERR_PERMIT_HEADROOM_EXCEEDED`, HTTP 422)".

        Design: Difficulty/boundary_precision_check/permit_headroom_exact_fit
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=10)
        resp = api.create_movement_record(
            {
                "permit_id": permit["id"],
                "head_count": 1,
                "destination_name": "KS Feedlot",
                "planned_ship_date": "2026-08-22T00:00:00Z",
            },
            make_vet_headers(scenario["vet"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_HEADROOM_EXCEEDED)


class TestHeadroomConservation:
    def test_permit_headroom_conserved_by_cancel_schedule_side(self, api, admin_headers):
        """PRD §3.5: "`committed_headroom` is the `allocated_head_count` minus
        the summed `head_count` of the permit's movement records in
        `SCHEDULED`, `IN_TRANSIT`, or `DELIVERED`; this is the figure that
        gates scheduling."

        Design: Difficulty/compensating_invariant/permit_headroom_conserved_by_cancel
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=6)
        assert get_permit(permit["id"])["committed_headroom"] == 4

    def test_permit_headroom_conserved_by_cancel_restore_side(self, api, admin_headers):
        """PRD §3.5: "Cancelling a scheduled record simply releases its
        committed headroom."

        Design: Difficulty/compensating_invariant/permit_headroom_conserved_by_cancel
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        record = create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=6)
        validate_success(
            api.cancel_movement_record(record["id"], make_vet_headers(scenario["vet"]["id"])),
            200,
        )
        permit = get_permit(permit["id"])
        assert permit["committed_headroom"] == 10, (
            "schedule-then-cancel must conserve permit capacity at 10"
        )
        assert permit["projected_headroom"] == 10


class TestInventoryConservation:
    def test_premises_inventory_conserved_by_depart(self, api, admin_headers):
        """PRD §3.5: "Departure stamps `departed_at` with the logical clock and
        decrements the origin premises' `current_head_count` by the record's
        `head_count`."

        Design: Difficulty/compensating_invariant/premises_inventory_conserved_by_depart_cancel
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(
            allocation=5, cert_head_count=5, head_count=20
        )
        record = create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=5)
        set_clock("2026-08-21T00:00:00Z")
        validate_success(
            api.depart_movement_record(record["id"], make_vet_headers(scenario["vet"]["id"])),
            200,
        )
        assert get_premises(scenario["premises"]["id"])["current_head_count"] == 15

    def test_premises_inventory_conserved_by_depart_cancel(self, api, admin_headers):
        """PRD §3.5: "Cancelling an in-transit record additionally
        restores the origin premises' `current_head_count` by the record's
        `head_count`, a compensating restore that conserves inventory across a
        depart-then-cancel sequence."

        Design: Difficulty/compensating_invariant/premises_inventory_conserved_by_depart_cancel
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(
            allocation=5, cert_head_count=5, head_count=20
        )
        record = create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=5)
        set_clock("2026-08-21T00:00:00Z")
        vet_h = make_vet_headers(scenario["vet"]["id"])
        validate_success(api.depart_movement_record(record["id"], vet_h), 200)

        cancelled = validate_success(api.cancel_movement_record(record["id"], vet_h), 200)
        assert cancelled["status"] == "CANCELLED"
        assert get_premises(scenario["premises"]["id"])["current_head_count"] == 20, (
            "depart followed by cancel-from-IN_TRANSIT must conserve inventory"
        )


class TestVoidCascade:
    def test_certificate_void_cascades_permit_and_records_states(
        self, api, admin_headers, officer_headers
    ):
        """PRD §3.4: "Voiding detonates its own cascade, atomically:
        every movement permit belonging to the certificate whose `status` is
        `REQUESTED`, `ISSUED`, or `SUSPENDED` becomes `VOIDED`; on each such
        permit, every movement record in `SCHEDULED` or `IN_TRANSIT` becomes
        `CANCELLED`; and for each record cancelled out of `IN_TRANSIT`, the
        origin premises' `current_head_count` is restored by that record's
        `head_count`."
        PRD §2.10: "Issuing a movement permit mints its `permit_number` in the
        form `EP-<destination state code>-<six-digit sequence>` — for example
        `EP-KS-000001`."

        Design: Difficulty/transitive_cascade/certificate_void_cascades_permit_and_records
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(
            allocation=5, cert_head_count=5, head_count=20
        )
        record = create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=5)
        set_clock("2026-08-21T00:00:00Z")
        validate_success(
            api.depart_movement_record(record["id"], make_vet_headers(scenario["vet"]["id"])),
            200,
        )

        voided = validate_success(
            api.void_certificate(cert["id"], {"reason": "DISEASE_SUSPECT"}, officer_headers),
            200,
        )
        assert voided["status"] == "VOID"

        permit_after = get_permit(permit["id"])
        assert permit_after["status"] == "VOIDED", "void cascade link 1"
        assert permit_after["permit_number"] == "EP-KS-000001"
        records, meta = validate_paginated(
            api.list_movement_records_for_permit(permit["id"], AUDITOR)
        )
        assert meta["total_count"] == 1
        assert records[0]["id"] == record["id"]
        assert records[0]["status"] == "CANCELLED", "void cascade link 2"

    def test_certificate_void_cascades_permit_and_records_inventory_restored(
        self, api, admin_headers, officer_headers
    ):
        """PRD §3.4: "and for each record cancelled out of `IN_TRANSIT`, the
        origin premises' `current_head_count` is restored by that record's
        `head_count`."

        Design: Difficulty/transitive_cascade/certificate_void_cascades_permit_and_records
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(
            allocation=5, cert_head_count=5, head_count=20
        )
        record = create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=5)
        set_clock("2026-08-21T00:00:00Z")
        validate_success(
            api.depart_movement_record(record["id"], make_vet_headers(scenario["vet"]["id"])),
            200,
        )
        assert get_premises(scenario["premises"]["id"])["current_head_count"] == 15

        validate_success(
            api.void_certificate(cert["id"], {"reason": "DISEASE_SUSPECT"}, officer_headers),
            200,
        )
        assert get_premises(scenario["premises"]["id"])["current_head_count"] == 20, (
            "the IN_TRANSIT cancel inside the void cascade restores the 5 head"
        )


class TestSchedulingGatedByPermitStatus:
    def test_movement_scheduling_gated_by_permit_status_error(self, api, admin_headers):
        """PRD §3.5: "Scheduling requires the permit to be `ISSUED`
        (`ERR_PERMIT_NOT_ISSUED`, HTTP 409 — this is also what blocks new
        scheduling while a permit sits `SUSPENDED`)".
        PRD §3.6: "Suspension freezes but does not destroy: a `SUSPENDED`
        permit blocks new scheduling and departures through
        `ERR_PERMIT_NOT_ISSUED`, yet its `SCHEDULED` records are left untouched
        pending reinstatement."

        Design: Difficulty/cross_entity_state_dependency/movement_scheduling_gated_by_permit_status
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        create_and_escalate_zone()  # Yolo/CATTLE zone flips permit to SUSPENDED
        assert get_permit(permit["id"])["status"] == "SUSPENDED"

        resp = api.create_movement_record(
            {
                "permit_id": permit["id"],
                "head_count": 4,
                "destination_name": "KS Feedlot",
                "planned_ship_date": "2026-08-21T00:00:00Z",
            },
            make_vet_headers(scenario["vet"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED)

    def test_movement_scheduling_gated_by_permit_status_no_record(
        self, api, admin_headers, auditor_headers
    ):
        """PRD §3.5: "Scheduling requires the permit to be `ISSUED`
        (`ERR_PERMIT_NOT_ISSUED`, HTTP 409 — this is also what blocks new
        scheduling while a permit sits `SUSPENDED`)".

        Design: Difficulty/cross_entity_state_dependency/movement_scheduling_gated_by_permit_status
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        create_and_escalate_zone()

        resp = api.create_movement_record(
            {
                "permit_id": permit["id"],
                "head_count": 4,
                "destination_name": "KS Feedlot",
                "planned_ship_date": "2026-08-21T00:00:00Z",
            },
            make_vet_headers(scenario["vet"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED)
        records, meta = validate_paginated(
            api.list_movement_records_for_permit(permit["id"], auditor_headers)
        )
        assert meta["total_count"] == 0, "no MovementRecord may be persisted"


class TestDepartWhileSuspended:
    def test_depart_blocked_while_permit_suspended(self, api, admin_headers):
        """PRD §3.6: "Suspension freezes but does not destroy: a `SUSPENDED`
        permit blocks new scheduling and departures through
        `ERR_PERMIT_NOT_ISSUED`, yet its `SCHEDULED` records are left untouched
        pending reinstatement."
        PRD §3.5: "Departing requires the record be `SCHEDULED` and the permit
        be `ISSUED` — state failures yield `ERR_MOVEMENT_NOT_ADVANCEABLE` and
        `ERR_PERMIT_NOT_ISSUED` respectively (HTTP 409)."

        Design: Corner/state_machines/depart_blocked_while_permit_suspended
        """
        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        record = create_scheduled_record(permit["id"], scenario["vet"]["id"], head_count=5)
        create_and_escalate_zone()
        assert get_permit(permit["id"])["status"] == "SUSPENDED"
        set_clock("2026-08-21T00:00:00Z")

        resp = api.depart_movement_record(record["id"], make_vet_headers(scenario["vet"]["id"]))
        err = validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED)
        assert err["error_id"] != ApiErrorId.ERR_PREMISES_DISEASE_HOLD
        # The SCHEDULED record is left untouched by the suspension.
        records, meta = validate_paginated(
            api.list_movement_records_for_permit(permit["id"], AUDITOR)
        )
        assert records[0]["status"] == "SCHEDULED"


class TestZoneGateForNewPremises:
    def test_movement_blocked_by_active_zone_for_new_premises(
        self, api, admin_headers, auditor_headers
    ):
        """PRD §3.5: "no `ACTIVE` outbreak zone covering the origin county and
        species at the logical clock (`ERR_OUTBREAK_MOVEMENT_RESTRICTION`,
        HTTP 422)".
        PRD §3.1: "The premises begins life with `disease_status` `MONITORED`
        unless the administrator supplies a different standing at registration".

        Design: Corner/state_machines/movement_blocked_by_active_zone_for_new_premises
        """
        # Zone goes ACTIVE while the database is still empty — no premises held.
        create_and_escalate_zone()

        scenario, cert, permit = setup_issued_certificate_with_permit(allocation=10)
        premises = get_premises(scenario["premises"]["id"])
        assert premises["disease_status"] == "MONITORED", (
            "the escalation cascade ran before registration; no retroactive hold"
        )

        resp = api.create_movement_record(
            {
                "permit_id": permit["id"],
                "head_count": 4,
                "destination_name": "KS Feedlot",
                "planned_ship_date": "2026-08-21T00:00:00Z",
            },
            make_vet_headers(scenario["vet"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OUTBREAK_MOVEMENT_RESTRICTION)
        records, meta = validate_paginated(
            api.list_movement_records_for_permit(permit["id"], auditor_headers)
        )
        assert meta["total_count"] == 0
        assert get_permit(permit["id"])["status"] == "ISSUED"


class TestDepartInventoryAcrossCertificates:
    def test_depart_blocked_when_inventory_consumed_by_other_certificate(
        self, api, admin_headers
    ):
        """PRD §3.5: "the shipment's `head_count` must not exceed the premises'
        `current_head_count` (`ERR_HEAD_COUNT_EXCEEDS_INVENTORY`)" [at
        departure].
        PRD §3.5: "a premises' `current_head_count` equals its
        `initial_head_count` minus the summed `head_count` of every movement
        record whose chain — record to permit to certificate — leads back to
        that premises as origin, counting only records in `IN_TRANSIT` or
        `DELIVERED`."

        Design: Corner/state_machines/depart_blocked_when_inventory_consumed_by_other_certificate
        """
        scenario = setup_standard_scenario(head_count=10)
        vet_h = make_vet_headers(scenario["vet"]["id"])
        cert_a = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"], head_count=6,
            test_record_id=scenario["test"]["id"],
            vaccination_date=DEFAULTS["VACCINATION_DATE"],
        )
        submit_certificate(cert_a["id"], scenario["vet"]["id"])
        cert_a = issue_certificate(cert_a["id"])
        cert_b = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"], head_count=6,
            test_record_id=scenario["test"]["id"],
            vaccination_date=DEFAULTS["VACCINATION_DATE"],
        )
        submit_certificate(cert_b["id"], scenario["vet"]["id"])
        cert_b = issue_certificate(cert_b["id"])
        perm_a = create_issued_permit(cert_a["id"], scenario["vet"]["id"], allocated_head_count=6)
        perm_b = create_issued_permit(cert_b["id"], scenario["vet"]["id"], allocated_head_count=6)
        rec_a = create_scheduled_record(perm_a["id"], scenario["vet"]["id"], head_count=6)
        rec_b = create_scheduled_record(perm_b["id"], scenario["vet"]["id"], head_count=6)
        set_clock("2026-08-21T00:00:00Z")

        departed = validate_success(api.depart_movement_record(rec_a["id"], vet_h), 200)
        assert departed["status"] == "IN_TRANSIT"
        assert get_premises(scenario["premises"]["id"])["current_head_count"] == 4

        # Permit B's own headroom is intact (6), but live inventory is 4 < 6.
        resp_b = api.depart_movement_record(rec_b["id"], vet_h)
        validate_error(resp_b, ApiErrorId.ERR_HEAD_COUNT_EXCEEDS_INVENTORY)
        assert get_premises(scenario["premises"]["id"])["current_head_count"] == 4
        records_b, _ = validate_paginated(
            api.list_movement_records_for_permit(perm_b["id"], AUDITOR)
        )
        assert records_b[0]["status"] == "SCHEDULED"
