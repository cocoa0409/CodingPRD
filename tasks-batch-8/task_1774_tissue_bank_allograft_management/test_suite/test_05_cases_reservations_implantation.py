"""Implant cases, reservations, and implantation: OR-room overlap, issue
shapes, ownership, temporal windows, and clock-sweep boundaries."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_clock,
    create_recall,
    get_success_data,
    make_manifest_item,
    setup_available_units,
    setup_case,
    setup_issued_unit,
    setup_received_shipment,
    setup_reservation,
    setup_reserved_unit,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
QM = TEST_USERS["quality_headers"]
SURG = TEST_USERS["surgeon_headers"]
SURG2 = TEST_USERS["surgeon2_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestOrRoomOverlap:
    def test_or_room_adjacent_boundary_allowed(self, api):
        """PRD §3.5: "Double-booking is forbidden across the room's active
        calendar: a new case whose half-open window — start inclusive, end
        exclusive — intersects another `SCHEDULED` case in the same
        `or_room_id` is rejected with `ERR_OR_ROOM_DOUBLE_BOOKED`, while
        back-to-back cases whose boundary instants coincide are lawful because
        the touching endpoint lies outside the half-open interval."

        Design: Difficulty/resource_temporal_overlap/or_room_half_open_adjacency
        """
        case_a = setup_case(
            patient_ref="P-A", or_room_id="OR-1",
            scheduled_start="2026-09-01T10:00:00Z",
            scheduled_end="2026-09-01T12:00:00Z",
        )
        # B.start == A.end is adjacency, not overlap (half-open semantics).
        case_b = validate_success(
            api.create_implant_case(
                {
                    "patient_ref": "P-B",
                    "or_room_id": "OR-1",
                    "scheduled_start": "2026-09-01T12:00:00Z",
                    "scheduled_end": "2026-09-01T13:00:00Z",
                },
                SURG2,
            ),
            201,
        )
        assert case_b["status"] == "SCHEDULED"
        assert case_a["status"] == "SCHEDULED"

    def test_or_room_strict_intersection_rejected_other_room_allowed(self, api):
        """PRD §3.5: "Double-booking is forbidden across the room's active
        calendar: a new case whose half-open window — start inclusive, end
        exclusive — intersects another `SCHEDULED` case in the same
        `or_room_id` is rejected with `ERR_OR_ROOM_DOUBLE_BOOKED`, while
        back-to-back cases whose boundary instants coincide are lawful because
        the touching endpoint lies outside the half-open interval."

        Design: Difficulty/resource_temporal_overlap/or_room_half_open_adjacency
        """
        setup_case(
            patient_ref="P-A", or_room_id="OR-1",
            scheduled_start="2026-09-01T10:00:00Z",
            scheduled_end="2026-09-01T12:00:00Z",
        )
        # [11:00, 13:00) strictly intersects [10:00, 12:00).
        resp = api.create_implant_case(
            {
                "patient_ref": "P-C",
                "or_room_id": "OR-1",
                "scheduled_start": "2026-09-01T11:00:00Z",
                "scheduled_end": "2026-09-01T13:00:00Z",
            },
            SURG2,
        )
        validate_error(resp, ApiErrorId.ERR_OR_ROOM_DOUBLE_BOOKED)
        # Same window but a different or_room_id resource.
        case_d = validate_success(
            api.create_implant_case(
                {
                    "patient_ref": "P-D",
                    "or_room_id": "OR-2",
                    "scheduled_start": "2026-09-01T10:00:00Z",
                    "scheduled_end": "2026-09-01T12:00:00Z",
                },
                SURG2,
            ),
            201,
        )
        assert case_d["status"] == "SCHEDULED"


class TestReservationLifecycle:
    def test_reservation_manual_release_then_second_release_rejected(self, api):
        """PRD §3.5: "A `TissueBankCoordinator` may release an `ACTIVE`
        reservation manually (`ERR_RESERVATION_NOT_ACTIVE` on anything else),
        recording `MANUAL` and returning the unit to `AVAILABLE`."

        Design: Corner/state_machines/reservation_manual_release_then_second_release_rejected
        """
        bundle = setup_reserved_unit()
        released = validate_success(
            api.release_reservation(bundle["reservation"]["id"], COORD)
        )
        assert released["status"] == "RELEASED"
        assert released["release_reason"] == "MANUAL"
        unit_after = validate_success(api.get_tissue_unit(bundle["unit"]["id"], QM))
        assert unit_after["status"] == "AVAILABLE"
        resp = api.release_reservation(bundle["reservation"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_RESERVATION_NOT_ACTIVE)

    def test_reserve_quarantined_unit_blocked(self, api):
        """PRD §3.5: "The unit must be `AVAILABLE`
        (`ERR_UNIT_NOT_RESERVABLE`)"

        Design: Corner/errors/error_reserve_quarantined_unit_blocked
        """
        _, _, _, units = setup_received_shipment()
        assert units[0]["status"] == "QUARANTINED"
        case = setup_case()
        resp = api.create_reservation(case["id"], {"tissue_unit_id": units[0]["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_RESERVABLE)

    def test_reservation_hold_until_boundary(self, api):
        """PRD §3.5: "A successful reservation creates an `ACTIVE` reservation
        bound to the case through its `implant_case_id`, with `hold_until`
        computed as the case's `scheduled_end` plus two hours, and moves the
        unit to `RESERVED`."
        PRD §3.5: "The reservation sweep expires an `ACTIVE` reservation once
        the clock is strictly past `hold_until`, recording `CLOCK_EXPIRED` and
        returning a still-`RESERVED` unit to `AVAILABLE`"

        Design: Corner/calculations/reservation_hold_until_boundary
        """
        bundle = setup_reserved_unit()
        reservation = bundle["reservation"]
        assert reservation["hold_until"].startswith("2026-08-10T14:00:00")
        advance_clock("2026-08-10T14:00:00Z")
        at_boundary = validate_success(api.get_reservation(reservation["id"], COORD))
        assert at_boundary["status"] == "ACTIVE"
        advance_clock("2026-08-10T14:00:01Z")
        after = validate_success(api.get_reservation(reservation["id"], COORD))
        assert after["status"] == "EXPIRED"
        assert after["release_reason"] == "CLOCK_EXPIRED"
        unit_after = validate_success(api.get_tissue_unit(bundle["unit"]["id"], QM))
        assert unit_after["status"] == "AVAILABLE"


class TestIssueShapes:
    def test_issue_with_reservation_fulfills_it(self, api):
        """PRD §3.4: "A successful issue moves the unit to `ISSUED`, fulfills
        the reservation when one was used (its status becomes `FULFILLED`), and
        decrements the freezer's `occupied_count`."

        Design: Corner/state_machines/issue_with_reservation_fulfills_it
        """
        bundle = setup_reserved_unit()
        issued = validate_success(
            api.issue_unit(
                bundle["unit"]["id"],
                {"reservation_id": bundle["reservation"]["id"]},
                COORD,
            )
        )
        assert issued["status"] == "ISSUED"
        reservation_after = validate_success(
            api.get_reservation(bundle["reservation"]["id"], COORD)
        )
        assert reservation_after["status"] == "FULFILLED"

    def test_issue_with_other_units_reservation_returns_mismatch(self, api):
        """PRD §3.4: "issue against a reservation carries an optional
        `reservation_id` in the request and requires the unit to be `RESERVED`,
        the named reservation to be `ACTIVE` (`ERR_RESERVATION_NOT_ACTIVE`),
        and the reservation's `tissue_unit_id` to match the unit being issued
        (`ERR_RESERVATION_UNIT_MISMATCH`)."

        Design: Corner/state_machines/issue_with_other_units_reservation_returns_mismatch
        """
        _, _, _, units = setup_available_units(
            items=[
                make_manifest_item(serial_number="U-001"),
                make_manifest_item(serial_number="U-002"),
            ]
        )
        case = setup_case()
        setup_reservation(case["id"], units[0]["id"])
        res2 = setup_reservation(case["id"], units[1]["id"])
        resp = api.issue_unit(units[0]["id"], {"reservation_id": res2["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_RESERVATION_UNIT_MISMATCH)
        unit1 = validate_success(api.get_tissue_unit(units[0]["id"], QM))
        assert unit1["status"] == "RESERVED"
        res2_after = validate_success(api.get_reservation(res2["id"], COORD))
        assert res2_after["status"] == "ACTIVE"


class TestCaseCompletionCascade:
    def test_case_complete_releases_active_reservations(self, api):
        """PRD §3.5: "Cancelling or completing the parent case releases each of
        its remaining `ACTIVE` reservations with `CASE_CANCELLED` or
        `CASE_COMPLETED`, returning those units to `AVAILABLE`."

        Design: Corner/state_machines/case_complete_releases_active_reservations
        """
        _, _, _, units = setup_available_units(
            items=[
                make_manifest_item(serial_number="U-001"),
                make_manifest_item(serial_number="U-002"),
            ]
        )
        case = setup_case()
        res1 = setup_reservation(case["id"], units[0]["id"])
        res2 = setup_reservation(case["id"], units[1]["id"])
        completed = validate_success(api.complete_case(case["id"], SURG))
        assert completed["status"] == "COMPLETED"
        reservations = get_success_data(api.list_case_reservations(case["id"], COORD))
        by_id = {r["id"]: r for r in reservations}
        assert by_id[res1["id"]]["status"] == "RELEASED"
        assert by_id[res1["id"]]["release_reason"] == "CASE_COMPLETED"
        assert by_id[res2["id"]]["status"] == "RELEASED"
        assert by_id[res2["id"]]["release_reason"] == "CASE_COMPLETED"
        for unit in units:
            after = validate_success(api.get_tissue_unit(unit["id"], QM))
            assert after["status"] == "AVAILABLE"

    def test_case_ownership_enforced_for_other_surgeon(self, api):
        """PRD §3.5: "Both cancellation and completion require the same
        ownership check (`ERR_CASE_OWNERSHIP_VIOLATION`) and a `SCHEDULED` case
        (`ERR_CASE_INVALID_STATE`)"
        PRD §3.5: "Ownership: the case's `surgeon_id` must equal the caller's
        `X-User-ID`, otherwise `ERR_CASE_OWNERSHIP_VIOLATION` (HTTP 403)."

        Design: Corner/state_machines/case_ownership_enforced_for_other_surgeon
        """
        case = setup_case()
        assert case["surgeon_id"] == "surg-1"
        validate_error(api.cancel_case(case["id"], SURG2),
                       ApiErrorId.ERR_CASE_OWNERSHIP_VIOLATION)
        validate_error(api.complete_case(case["id"], SURG2),
                       ApiErrorId.ERR_CASE_OWNERSHIP_VIOLATION)
        after = validate_success(api.get_implant_case(case["id"], SURG))
        assert after["status"] == "SCHEDULED"

    def test_case_cancel_after_complete_blocked(self, api):
        """PRD §3.5: "Both cancellation and completion require the same
        ownership check (`ERR_CASE_OWNERSHIP_VIOLATION`) and a `SCHEDULED` case
        (`ERR_CASE_INVALID_STATE`); cancellation moves the case to `CANCELLED`,
        completion to `COMPLETED`, and both release remaining reservations as
        described above."

        Design: Corner/errors/error_case_cancel_after_complete_blocked
        """
        case = setup_case()
        completed = validate_success(api.complete_case(case["id"], SURG))
        assert completed["status"] == "COMPLETED"
        resp = api.cancel_case(case["id"], SURG)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)
        after = validate_success(api.get_implant_case(case["id"], SURG))
        assert after["status"] == "COMPLETED"


class TestTemporalGates:
    def test_unit_expires_before_case_boundary(self, api):
        """PRD §3.5: "The unit must be `AVAILABLE` (`ERR_UNIT_NOT_RESERVABLE`),
        and it must outlive the surgery: its `expiration_at` must fall strictly
        after the case's `scheduled_end`, otherwise the reservation is refused
        with `ERR_UNIT_EXPIRES_BEFORE_CASE`."

        Design: Corner/errors/error_unit_expires_before_case_boundary
        """
        _, _, _, units = setup_available_units(
            items=[
                make_manifest_item(serial_number="U-001",
                                   expiration_at="2026-08-10T12:00:00Z"),
                make_manifest_item(serial_number="U-002",
                                   expiration_at="2026-08-10T12:00:01Z"),
            ]
        )
        case = setup_case()  # scheduled_end 2026-08-10T12:00:00Z
        resp = api.create_reservation(case["id"], {"tissue_unit_id": units[0]["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_UNIT_EXPIRES_BEFORE_CASE)
        reservation = validate_success(
            api.create_reservation(case["id"], {"tissue_unit_id": units[1]["id"]}, COORD),
            201,
        )
        assert reservation["status"] == "ACTIVE"

    def test_implant_window_closed_then_opens(self, api):
        """PRD §3.5: "Timing: the clock must sit inside the implant window — no
        earlier than one hour before `scheduled_start` and no later than
        twenty-four hours after `scheduled_end`, inclusive at both ends —
        otherwise `ERR_IMPLANT_WINDOW_CLOSED`."

        Design: Corner/errors/error_implant_window_closed
        """
        bundle = setup_issued_unit(via_reservation=False)
        # One second before the window opens (window starts 09:00:00).
        advance_clock("2026-08-10T08:59:59Z")
        resp = api.record_implantation(
            bundle["case"]["id"], {"tissue_unit_id": bundle["unit"]["id"]}, SURG
        )
        validate_error(resp, ApiErrorId.ERR_IMPLANT_WINDOW_CLOSED)
        # Earliest legal instant: window bounds are inclusive.
        advance_clock("2026-08-10T09:00:00Z")
        implanted = validate_success(
            api.record_implantation(
                bundle["case"]["id"], {"tissue_unit_id": bundle["unit"]["id"]}, SURG
            )
        )
        assert implanted["status"] == "IMPLANTED"

    def test_expiry_equality_usable_then_sweep_at_plus_one_second(self, api):
        """PRD §2.4: "The unit sweep expires stored units whose `expiration_at`
        is now strictly behind the clock (equality leaves the unit usable)"
        PRD §3.4: "Units in `ISSUED` are deliberately not swept — clinical
        custody overrides expiry — though issue and return-to-stock continue to
        enforce the expiry gate."
        PRD §3.4: "A unit is usable while the clock is on or before its
        `expiration_at`; once the clock is strictly past it, the expiration
        sweep moves units in `QUARANTINED`, `AVAILABLE`, or `RESERVED` to the
        terminal `EXPIRED` state with `hold_reason` cleared to `NONE`, creates
        a `DRAFT` disposition record of type `EXPIRED` per unit"

        Design: Corner/calculations/expiry_equality_usable_then_sweep_at_plus_one_second
        """
        _, _, _, units = setup_available_units(
            items=[
                make_manifest_item(serial_number="U-001",
                                   expiration_at="2026-09-01T00:00:00Z"),
                make_manifest_item(serial_number="U-002",
                                   expiration_at="2026-09-01T00:00:00Z"),
            ]
        )
        # At clock == expiration_at the unit is still usable.
        advance_clock("2026-09-01T00:00:00Z")
        issued = validate_success(api.issue_unit(units[0]["id"], {}, COORD))
        assert issued["status"] == "ISSUED"
        # One second later the sweep takes the still-stored unit.
        advance_clock("2026-09-01T00:00:01Z")
        resp = api.issue_unit(units[1]["id"], {}, COORD)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_ISSUABLE_STATE)
        unit1_after = validate_success(api.get_tissue_unit(units[0]["id"], QM))
        assert unit1_after["status"] == "ISSUED"
        unit2_after = validate_success(api.get_tissue_unit(units[1]["id"], QM))
        assert unit2_after["status"] == "EXPIRED"
        records = get_success_data(api.list_unit_disposition_records(units[1]["id"], QM))
        assert len(records) == 1
        assert records[0]["disposition_type"] == "EXPIRED"
        assert records[0]["status"] == "DRAFT"

    def test_return_to_stock_expired_unit_blocked(self, api):
        """PRD §3.4: "Return-to-stock by a `TissueBankCoordinator` requires the
        unit to be `ISSUED` (`ERR_UNIT_NOT_ISSUED`), the clock still on or
        before `expiration_at` (`ERR_UNIT_EXPIRED`), and no `ACTIVE` recall
        match (`ERR_UNIT_UNDER_ACTIVE_RECALL`)"

        Design: Corner/errors/error_return_to_stock_expired_unit_blocked
        """
        bundle = setup_issued_unit(
            via_reservation=False,
            items=[make_manifest_item(serial_number="U-001",
                                      expiration_at="2026-08-20T00:00:00Z")],
        )
        # ISSUED units are exempt from the sweep; clock moves past expiry.
        advance_clock("2026-08-21T00:00:00Z")
        resp = api.return_unit_to_stock(bundle["unit"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_UNIT_EXPIRED)
        after = validate_success(api.get_tissue_unit(bundle["unit"]["id"], QM))
        assert after["status"] == "ISSUED"


class TestReferentialGates:
    def test_adverse_reaction_on_non_implanted_unit(self, api):
        """PRD §3.7: "The named unit must actually be `IMPLANTED` on this case;
        a unit with any other placement fails with
        `ERR_UNIT_NOT_IMPLANTED_ON_CASE` (HTTP 422)."

        Design: Corner/errors/error_adverse_reaction_on_non_implanted_unit
        """
        bundle = setup_issued_unit(via_reservation=False)
        resp = api.report_adverse_reaction(
            bundle["case"]["id"],
            {
                "tissue_unit_id": bundle["unit"]["id"],
                "reaction_type": "OTHER",
                "severity": "MINOR",
                "description": "Reaction before implant claim",
            },
            SURG,
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_IMPLANTED_ON_CASE)

    def test_record_implantation_unit_issued_to_another_case(self, api):
        """PRD §3.5: "Stock: the named `tissue_unit_id` must be `ISSUED`
        (`ERR_UNIT_NOT_ISSUED`), and if that unit reached `ISSUED` through a
        reservation, the reservation's case must be this case — implanting
        another case's reserved unit fails with
        `ERR_UNIT_ISSUED_TO_ANOTHER_CASE` (HTTP 422)."

        Design: Corner/errors/error_record_implantation_unit_issued_to_another_case
        """
        bundle = setup_issued_unit(via_reservation=True)
        case2 = setup_case(patient_ref="P-2", or_room_id="OR-2")
        advance_clock("2026-08-10T11:00:00Z")
        resp = api.record_implantation(
            case2["id"], {"tissue_unit_id": bundle["unit"]["id"]}, SURG
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_ISSUED_TO_ANOTHER_CASE)
        after = validate_success(api.get_tissue_unit(bundle["unit"]["id"], QM))
        assert after["status"] == "ISSUED"


class TestRecordImplantation:
    def test_record_implantation_side_effects(self, api):
        """PRD §3.5: "Success moves the unit to `IMPLANTED`, stamps
        `implanted_case_id` and `implanted_at`, clears `recall_flag`,
        increments the case's `implanted_unit_count` by one, and creates a
        `DRAFT` disposition record of type `IMPLANTED` under the surgeon's
        `recorded_by_user_id`."

        Design: Corner/endpoints/record_implantation_side_effects
        """
        bundle = setup_issued_unit(via_reservation=False)
        advance_clock("2026-08-10T11:00:00Z")
        implanted = validate_success(
            api.record_implantation(
                bundle["case"]["id"], {"tissue_unit_id": bundle["unit"]["id"]}, SURG
            )
        )
        assert implanted["status"] == "IMPLANTED"
        assert implanted["implanted_case_id"] == bundle["case"]["id"]
        assert implanted["implanted_at"].startswith("2026-08-10T11:00:00")
        assert implanted["recall_flag"] is False
        case_after = validate_success(api.get_implant_case(bundle["case"]["id"], SURG))
        assert case_after["implanted_unit_count"] == 1
        records = get_success_data(
            api.list_unit_disposition_records(bundle["unit"]["id"], SURG)
        )
        assert len(records) == 1
        assert records[0]["disposition_type"] == "IMPLANTED"
        assert records[0]["status"] == "DRAFT"
        assert records[0]["recorded_by_user_id"] == "surg-1"

    def test_unit_not_issued_two_surfaces(self, api):
        """PRD §3.4: "Return-to-stock by a `TissueBankCoordinator` requires the
        unit to be `ISSUED` (`ERR_UNIT_NOT_ISSUED`)"
        PRD §3.5: "Stock: the named `tissue_unit_id` must be `ISSUED`
        (`ERR_UNIT_NOT_ISSUED`)"

        Design: Corner/errors/error_unit_not_issued_two_surfaces
        """
        bundle = setup_available_units()
        _, _, _, units = bundle
        case = setup_case()
        advance_clock("2026-08-10T11:00:00Z")
        resp1 = api.return_unit_to_stock(units[0]["id"], COORD)
        validate_error(resp1, ApiErrorId.ERR_UNIT_NOT_ISSUED)
        resp2 = api.record_implantation(
            case["id"], {"tissue_unit_id": units[0]["id"]}, SURG
        )
        validate_error(resp2, ApiErrorId.ERR_UNIT_NOT_ISSUED)


class TestIssuePriorityStateOverSafety:
    def _setup_expired_recalled_unit(self, api):
        """Unit EXPIRED (swept) while also past expiration_at and matched by an
        ACTIVE recall — state violation plus two safety violations."""
        _, _, _, units = setup_available_units(
            items=[make_manifest_item(serial_number="U-001",
                                      expiration_at="2026-09-01T00:00:00Z")]
        )
        supplier = validate_success(api.get_supplier(units[0]["supplier_id"], QM))
        recall = create_recall(supplier["id"], lot_numbers=["L1"],
                               reason="Lot L1 sterility failure")
        get_success_data(api.activate_recall(recall["id"], QM))
        advance_clock("2026-09-02T00:00:00Z")
        return units[0]

    def test_issue_reports_state_error_not_safety_errors(self, api):
        """PRD §2.8: "When a request violates several rules, the platform
        reports exactly one failure: the one from the earliest rung of a pinned
        priority ladder."
        PRD §2.8: "6. **State-machine preconditions** — the target must be in a
        state from which the requested transition exists (409)"
        PRD §3.4: "Direct issue requires the unit to be `AVAILABLE` (otherwise
        `ERR_UNIT_NOT_ISSUABLE_STATE`)"

        Design: Difficulty/priority_pair_validation_conflict/issue_expired_recalled_unit_state_error_wins
        """
        unit = self._setup_expired_recalled_unit(api)
        resp = api.issue_unit(unit["id"], {}, COORD)
        err = validate_error(resp, ApiErrorId.ERR_UNIT_NOT_ISSUABLE_STATE)
        assert err["error_id"] != "ERR_UNIT_EXPIRED"
        assert err["error_id"] != "ERR_UNIT_UNDER_ACTIVE_RECALL"

    def test_issue_priority_fixture_unit_actually_expired(self, api):
        """PRD §2.4: "The unit sweep expires stored units whose `expiration_at`
        is now strictly behind the clock (equality leaves the unit usable)"
        PRD §3.4: "Direct issue requires the unit to be `AVAILABLE` (otherwise
        `ERR_UNIT_NOT_ISSUABLE_STATE`)"

        Design: Difficulty/priority_pair_validation_conflict/issue_expired_recalled_unit_state_error_wins
        """
        unit = self._setup_expired_recalled_unit(api)
        swept = validate_success(api.get_tissue_unit(unit["id"], QM))
        assert swept["status"] == "EXPIRED"
        assert swept["hold_reason"] == "NONE"
        resp = api.issue_unit(unit["id"], {}, COORD)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_ISSUABLE_STATE)
