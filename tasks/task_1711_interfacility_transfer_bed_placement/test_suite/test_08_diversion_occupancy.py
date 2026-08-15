"""Diversion windows, occupancy accounting, and the saturation hysteresis."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_diversion_event,
    assert_occupancy_consistent,
    create_bed,
    create_case,
    create_diversion_event,
    create_facility,
    create_physician,
    create_screening,
    certify_screening,
    dispatch_case,
    drive_to_accepted,
    drive_to_awaiting,
    get_case,
    get_facility,
    get_hold,
    lift_diversion_event,
    list_diversion_events,
    make_bed_manager_headers,
    make_receiving_physician_headers,
    refuse_case,
    request_acceptance,
    set_bed_status,
    set_clock,
    setup_certified_case,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import COORD


class TestOccupancyAccounting:
    def test_occupancy_zero_operational_beds_saturates(self, api):
        """PRD: "`occupancy_pct` is the unavailable count divided by the
        operational count, multiplied by 100, and rounded half-up to two
        decimal places; when a facility has no operational beds at all,
        `occupancy_pct` is defined as 100.0."
        PRD: "When `occupancy_pct` reaches 95.0 or more — exactly 95.00
        triggers — and the facility has no `ACTIVE` diversion event scoped
        `ALL_UNITS`, the system auto-creates a `DiversionEvent` with scope
        `ALL_UNITS`, a window starting at the current clock and ending four
        hours later, the reason `AUTO_OCCUPANCY_SATURATION`, and `auto_created`
        set to true."

        Design: Corner/calculations/occupancy_zero_operational_beds_saturates
        """
        fac = create_facility(name="Tiny Rural", facility_code="TINY",
                              trauma_level="CRITICAL_ACCESS")
        bed = create_bed(fac["id"], "MS-01", "MED_SURG")
        before = get_facility(fac["id"])
        assert before["occupancy_pct"] == pytest.approx(0.0)
        assert before["operational_bed_count"] == 1

        set_bed_status(bed["id"], fac["id"], "OUT_OF_SERVICE")
        after = get_facility(fac["id"])
        assert after["operational_bed_count"] == 0
        assert after["occupancy_pct"] == pytest.approx(100.0)
        assert after["diversion_status"] == "HARD_DIVERSION"

        events = list_diversion_events(fac["id"])
        assert len(events) == 1
        event = events[0]
        assert_diversion_event(event)
        assert event["auto_created"] is True
        assert event["scope"] == "ALL_UNITS"
        assert event["effective_status"] == "ACTIVE"

    def test_occupancy_fields_reconcile_on_bed_mutations(self, api):
        """PRD: "These figures are recomputed after every bed status change —
        hold creation, confirmation, release, or expiry, and every housekeeping
        status update."
        PRD: "`operational_bed_count` counts the facility's beds whose status
        is anything other than `OUT_OF_SERVICE`. `unavailable_bed_count` counts
        beds in `HELD` or `OCCUPIED`. `occupancy_pct` is the unavailable count
        divided by the operational count, multiplied by 100, and rounded
        half-up to two decimal places; when a facility has no operational beds
        at all, `occupancy_pct` is defined as 100.0."

        Design: Corner/cross_cutting_layers/occupancy_fields_reconcile_on_bed_mutations
        """
        fac = create_facility(name="Receiving Trauma Center", facility_code="RCV",
                              trauma_level="LEVEL_1")
        beds = [create_bed(fac["id"], f"MS-0{i}", "MED_SURG") for i in range(1, 5)]

        f0 = get_facility(fac["id"])
        assert f0["operational_bed_count"] == 4
        assert f0["occupancy_pct"] == pytest.approx(0.0)
        assert_occupancy_consistent(f0)

        set_bed_status(beds[0]["id"], fac["id"], "OCCUPIED")
        f1 = get_facility(fac["id"])
        assert f1["unavailable_bed_count"] == 1
        assert f1["occupancy_pct"] == pytest.approx(25.0)

        set_bed_status(beds[0]["id"], fac["id"], "AVAILABLE")
        f2 = get_facility(fac["id"])
        assert f2["occupancy_pct"] == pytest.approx(0.0), (
            "recompute on every mutation — no stale cache"
        )


class TestSaturationBoundary:
    def _twenty_bed_facility(self):
        fac = create_facility(name="Receiving Trauma Center", facility_code="RCV",
                              trauma_level="LEVEL_1")
        beds = [create_bed(fac["id"], f"MS-{i:02d}", "MED_SURG")
                for i in range(1, 21)]
        return fac, beds

    def test_occupancy_exactly_95_triggers_but_90_does_not(self, api):
        """PRD: "When `occupancy_pct` reaches 95.0 or more — exactly 95.00
        triggers — and the facility has no `ACTIVE` diversion event scoped
        `ALL_UNITS`, the system auto-creates a `DiversionEvent` with scope
        `ALL_UNITS`, a window starting at the current clock and ending four
        hours later, the reason `AUTO_OCCUPANCY_SATURATION`, and `auto_created`
        set to true."

        Design: Difficulty/boundary_precision_check/occupancy_exactly_95_pct_triggers_auto_diversion
        """
        fac, beds = self._twenty_bed_facility()
        for bed in beds[:18]:
            set_bed_status(bed["id"], fac["id"], "OCCUPIED")
        assert get_facility(fac["id"])["occupancy_pct"] == pytest.approx(90.0)
        assert list_diversion_events(fac["id"]) == [], (
            "90.00 is below the 95.0 entry threshold"
        )

        set_bed_status(beds[18]["id"], fac["id"], "OCCUPIED")
        assert get_facility(fac["id"])["occupancy_pct"] == pytest.approx(95.0)
        events = list_diversion_events(fac["id"])
        assert len(events) == 1, "exactly 95.00 crosses the entry threshold"
        assert events[0]["auto_created"] is True
        assert events[0]["scope"] == "ALL_UNITS"
        assert events[0]["effective_status"] == "ACTIVE"

    def test_exit_boundary_strictly_below_90(self, api):
        """PRD: "When `occupancy_pct` falls strictly below 90.0 — a reading of
        exactly 90.00 does not lift anything — every auto-created, `ACTIVE`,
        `ALL_UNITS` diversion of the facility is lifted at the current clock."

        Design: Difficulty/boundary_precision_check/occupancy_exactly_95_pct_triggers_auto_diversion
        """
        fac, beds = self._twenty_bed_facility()
        for bed in beds[:19]:
            set_bed_status(bed["id"], fac["id"], "OCCUPIED")
        assert len(list_diversion_events(fac["id"])) == 1

        # Back down to exactly 90.00: the exit boundary is strict, no lift.
        set_bed_status(beds[18]["id"], fac["id"], "AVAILABLE")
        assert get_facility(fac["id"])["occupancy_pct"] == pytest.approx(90.0)
        assert list_diversion_events(fac["id"])[0]["effective_status"] == "ACTIVE"

        # 85.0 is strictly below 90.0: the auto diversion lifts.
        set_bed_status(beds[17]["id"], fac["id"], "AVAILABLE")
        assert get_facility(fac["id"])["occupancy_pct"] == pytest.approx(85.0)
        event = list_diversion_events(fac["id"])[0]
        assert event["effective_status"] == "LIFTED"
        assert event["lifted_at"] is not None


class TestDiversionClosedInterval:
    def _facility_with_scheduled_window(self):
        fac = create_facility(name="Receiving Trauma Center", facility_code="RCV",
                              trauma_level="LEVEL_1")
        d1 = create_diversion_event(
            fac["id"], "ALL_UNITS", "2026-08-10T10:00:00Z",
            "2026-08-10T12:00:00Z", "Planned generator maintenance")
        return fac, d1

    def test_touching_window_rejected(self, api):
        """PRD: "A diversion window is a closed interval: it occupies its
        `starts_at` through its `ends_at` inclusive of both endpoints."
        PRD: "New diversion windows must be strictly disjoint from every
        existing `SCHEDULED` or `ACTIVE` event of the same facility; a touch or
        overlap is rejected with `ERR_DIVERSION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/diversion_closed_interval_touching_rejected
        """
        fac, d1 = self._facility_with_scheduled_window()
        assert d1["effective_status"] == "SCHEDULED", (
            "the 2026-08-01 default clock precedes the window"
        )
        resp = api.create_diversion_event(
            fac["id"],
            {"scope": "ALL_UNITS", "starts_at": "2026-08-10T12:00:00Z",
             "ends_at": "2026-08-10T14:00:00Z",
             "reason": "Extended maintenance window attempt"},
            make_bed_manager_headers(fac["id"]))
        validate_error(resp, ApiErrorId.ERR_DIVERSION_OVERLAP, 409)

    def test_one_second_gap_accepted(self, api):
        """PRD: "A new window's `ends_at` must be strictly later than its
        `starts_at`, and a window whose endpoints merely touch an existing
        window of the same facility — the new `starts_at` equal to an existing
        `ends_at`, or the new `ends_at` equal to an existing `starts_at` —
        counts as overlapping."

        Design: Difficulty/resource_temporal_overlap/diversion_closed_interval_touching_rejected
        """
        fac, d1 = self._facility_with_scheduled_window()
        resp = api.create_diversion_event(
            fac["id"],
            {"scope": "ALL_UNITS", "starts_at": "2026-08-10T12:00:01Z",
             "ends_at": "2026-08-10T14:00:00Z",
             "reason": "Follow-on maintenance window"},
            make_bed_manager_headers(fac["id"]))
        d2 = validate_success(resp, 201)
        assert d2["effective_status"] == "SCHEDULED"
        assert len(list_diversion_events(fac["id"])) == 2

    def test_diversion_expired_window_no_longer_blocks_overlap(self, api):
        """PRD: "It reads `LIFTED` once `lifted_at` is set; otherwise `EXPIRED`
        once the clock has reached `ends_at`; otherwise `ACTIVE` once the clock
        has reached `starts_at`; otherwise `SCHEDULED`."
        PRD: "New diversion windows must be strictly disjoint from every
        existing `SCHEDULED` or `ACTIVE` event of the same facility; a touch or
        overlap is rejected with `ERR_DIVERSION_OVERLAP`."

        Design: Corner/validations/diversion_expired_window_no_longer_blocks_overlap
        """
        fac = create_facility(name="Receiving Trauma Center", facility_code="RCV",
                              trauma_level="LEVEL_1")
        create_diversion_event(fac["id"], "ALL_UNITS", "2026-08-01T00:00:00Z",
                               "2026-08-01T02:00:00Z", "Overnight generator test")
        set_clock("2026-08-01T03:00:00Z")

        events = list_diversion_events(fac["id"])
        assert events[0]["effective_status"] == "EXPIRED", (
            "clock beyond ends_at flips the derived status"
        )
        d2 = create_diversion_event(
            fac["id"], "ALL_UNITS", "2026-08-01T01:00:00Z",
            "2026-08-01T05:00:00Z",
            "Extended maintenance overlaps expired window")
        assert d2["effective_status"] == "ACTIVE"
        assert len(list_diversion_events(fac["id"])) == 2


class TestAcceptGatedByDiversion:
    def _workspace(self):
        """RCV with ICU + TELEMETRY beds and an ACTIVE SPECIFIC_UNIT TELEMETRY
        diversion; one ICU case and one TELEMETRY case both awaiting."""
        ws = setup_certified_case(
            acuity="CRITICAL", unit="ICU",
            rcv_beds=(("ICU-01", "ICU", None), ("TEL-01", "TELEMETRY", None)),
            patient_ref="PT-DIV-ICU")
        div = create_diversion_event(
            ws["fac_r"]["id"], "SPECIFIC_UNIT", "2026-08-01T00:00:00Z",
            "2026-08-01T04:00:00Z", "Telemetry monitoring capacity exhausted",
            unit_type="TELEMETRY")
        assert div["effective_status"] == "ACTIVE"
        drive_to_awaiting(ws)  # ICU case addressed to RCV

        case_tel = create_case(
            ws["fac_s"]["id"], ws["phys_s"]["id"], "URGENT", "TELEMETRY",
            "CARDIAC_CATH", False, "PT-DIV-TEL")
        create_screening(case_tel["id"], ws["phys_s"]["id"], True, True)
        certify_screening(case_tel["id"], ws["phys_s"]["id"])
        request_acceptance(case_tel["id"], ws["fac_r"]["id"],
                           ws["phys_r"]["id"])
        ws["div"] = div
        ws["case_tel"] = case_tel
        return ws

    def test_specific_unit_diversion_blocks_only_matching_unit(self, api):
        """PRD: "Two safety gates then apply in ladder order: the receiving
        facility must not sit under an applicable diversion — an `ACTIVE` event
        scoped `ALL_UNITS`, or one scoped `SPECIFIC_UNIT` whose `unit_type`
        matches the case's `required_unit_type`, failing with
        `ERR_FACILITY_ON_DIVERSION` — and the bed selector must find an
        eligible bed, failing with `ERR_NO_ELIGIBLE_BED`."
        PRD: "The facility-level `diversion_status` is then a roll-up of its
        events: `HARD_DIVERSION` when any of the facility's events is `ACTIVE`
        with scope `ALL_UNITS`; `SOFT_DIVERSION` when any event is `ACTIVE`
        with scope `SPECIFIC_UNIT` and none is `ACTIVE` with scope
        `ALL_UNITS`; otherwise `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/accept_gated_by_diversion_event_scope
        """
        ws = self._workspace()
        assert get_facility(ws["fac_r"]["id"])["diversion_status"] == "SOFT_DIVERSION"

        # The ICU case is not covered by a TELEMETRY diversion.
        icu = validate_success(api.accept_case(
            ws["case"]["id"], {},
            make_receiving_physician_headers(ws["phys_r"]["id"])))
        assert icu["status"] == "ACCEPTED"

        resp = api.accept_case(
            ws["case_tel"]["id"], {},
            make_receiving_physician_headers(ws["phys_r"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FACILITY_ON_DIVERSION, 403)
        assert get_case(ws["case_tel"]["id"])["status"] == "AWAITING_ACCEPTANCE"

    def test_lifting_diversion_unblocks_matching_unit(self, api):
        """PRD: "A `SCHEDULED` or `ACTIVE` diversion can be lifted early —
        manually by the facility's `BedManager`, whose `X-User-ID` must equal
        the event's `facility_id`, or automatically by the saturation rule —
        which stamps `lifted_at` and recomputes the facility's
        `diversion_status`."

        Design: Difficulty/cross_entity_state_dependency/accept_gated_by_diversion_event_scope
        """
        ws = self._workspace()
        lift_diversion_event(ws["div"]["id"], ws["fac_r"]["id"])
        assert get_facility(ws["fac_r"]["id"])["diversion_status"] == "OPEN"

        tel = validate_success(api.accept_case(
            ws["case_tel"]["id"], {},
            make_receiving_physician_headers(ws["phys_r"]["id"])))
        assert tel["status"] == "ACCEPTED"
        event = [e for e in list_diversion_events(ws["fac_r"]["id"])
                 if e["id"] == ws["div"]["id"]][0]
        assert event["effective_status"] == "LIFTED"
        assert event["lifted_at"] is not None


class TestStateErrorPrecedesDiversion:
    def _workspace(self):
        """RCV on ACTIVE ALL_UNITS diversion; case1 REFUSED, case2 AWAITING."""
        ws = setup_certified_case(acuity="EMERGENT", unit="ICU",
                                  patient_ref="PT-PRI-1")
        drive_to_awaiting(ws)
        refuse_case(ws["case"]["id"], ws["phys_r"]["id"], "CAPACITY_EXCEEDED",
                    "All critical care beds occupied; surge protocol already "
                    "engaged at receiving.")
        create_diversion_event(
            ws["fac_r"]["id"], "ALL_UNITS", "2026-08-01T00:00:00Z",
            "2026-08-01T04:00:00Z", "ER saturation beyond safe boarding levels")

        case2 = create_case(
            ws["fac_s"]["id"], ws["phys_s"]["id"], "EMERGENT", "ICU",
            "CARDIAC_CATH", False, "PT-PRI-2")
        create_screening(case2["id"], ws["phys_s"]["id"], True, True)
        certify_screening(case2["id"], ws["phys_s"]["id"])
        request_acceptance(case2["id"], ws["fac_r"]["id"], ws["phys_r"]["id"])
        ws["case2"] = case2
        return ws

    def test_accept_on_refused_case_reports_state_error(self, api):
        """PRD: "A request that fails several rules must fail with the earliest
        rule on a fixed ladder; the ordering is part of the contract."
        PRD: "**State preconditions** — correct from-state and singleton
        guards (`ERR_INVALID_STATE`, `ERR_SCREENING_LOCKED`,
        `ERR_DUPLICATE_SCREENING`, `ERR_DUPLICATE_PACKET`,
        `ERR_DUPLICATE_NOTIFICATION`, `ERR_BED_NOT_AVAILABLE`,
        `ERR_HOLD_NOT_ACTIVE`, `ERR_DISPATCH_NOT_CANCELLABLE`; all 409)."

        Design: Difficulty/priority_pair_validation_conflict/accept_state_error_precedes_diversion_error
        """
        ws = self._workspace()
        # The diversion is also active, but the state rung precedes safety.
        resp = api.accept_case(
            ws["case"]["id"], {},
            make_receiving_physician_headers(ws["phys_r"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_case(ws["case"]["id"])["status"] == "REFUSED"

    def test_accept_on_awaiting_case_reports_diversion_error(self, api):
        """PRD: "A request that fails several rules must fail with the earliest
        rule on a fixed ladder; the ordering is part of the contract."
        PRD: "Two safety gates then apply in ladder order: the receiving
        facility must not sit under an applicable diversion — an `ACTIVE` event
        scoped `ALL_UNITS`, or one scoped `SPECIFIC_UNIT` whose `unit_type`
        matches the case's `required_unit_type`, failing with
        `ERR_FACILITY_ON_DIVERSION` — and the bed selector must find an
        eligible bed, failing with `ERR_NO_ELIGIBLE_BED`."

        Design: Difficulty/priority_pair_validation_conflict/accept_state_error_precedes_diversion_error
        """
        ws = self._workspace()
        resp = api.accept_case(
            ws["case2"]["id"], {},
            make_receiving_physician_headers(ws["phys_r"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FACILITY_ON_DIVERSION, 403)
        assert get_case(ws["case2"]["id"])["status"] == "AWAITING_ACCEPTANCE"


class TestAcceptCascadeSaturation:
    def _workspace(self):
        """RCV with 10 ICU beds, 9 OCCUPIED (90.0), 1 AVAILABLE; CRITICAL case
        awaiting at RCV."""
        fac_s = create_facility()
        fac_r = create_facility(name="Receiving Trauma Center", facility_code="RCV",
                                trauma_level="LEVEL_1",
                                capabilities=["CARDIAC_CATH"])
        beds = [create_bed(fac_r["id"], f"ICU-{i:02d}", "ICU")
                for i in range(1, 11)]
        for bed in beds[:9]:
            set_bed_status(bed["id"], fac_r["id"], "OCCUPIED")
        phys_s = create_physician("Dr Send", fac_s["id"], "EMERGENCY")
        phys_r = create_physician("Dr Recv", fac_r["id"], "INTENSIVIST")
        case = create_case(fac_s["id"], phys_s["id"], "CRITICAL", "ICU",
                           "CARDIAC_CATH", False, "PT-CASC-1")
        create_screening(case["id"], phys_s["id"], True, True)
        certify_screening(case["id"], phys_s["id"])
        request_acceptance(case["id"], fac_r["id"], phys_r["id"])
        return {"fac_s": fac_s, "fac_r": fac_r, "beds": beds,
                "phys_s": phys_s, "phys_r": phys_r, "case": case}

    def test_accept_holds_last_bed_and_pushes_occupancy_to_100(self, api):
        """PRD: "A successful acceptance flips the round's communication
        `PENDING → ACCEPTED` with `responded_at` stamped, moves the selected bed
        `AVAILABLE → HELD`, and creates a `BedHold` in `ACTIVE` with
        `hold_started_at` stamped from the clock and `hold_expires_at` computed
        from the case's acuity: sixty minutes for `CRITICAL`, two hours for
        `EMERGENT`, four hours for `URGENT`, and eight hours for `STABLE`."
        PRD: "The case records the hold in `active_bed_hold_id`, moves
        `AWAITING_ACCEPTANCE → ACCEPTED`, and bumps its version; the receiving
        facility's occupancy recomputes and the saturation rule evaluates."

        Design: Difficulty/transitive_cascade/accept_cascade_hold_bed_saturation_diversion
        """
        ws = self._workspace()
        pre = get_facility(ws["fac_r"]["id"])
        assert pre["occupancy_pct"] == pytest.approx(90.0)
        assert list_diversion_events(ws["fac_r"]["id"]) == []

        case = validate_success(api.accept_case(
            ws["case"]["id"], {},
            make_receiving_physician_headers(ws["phys_r"]["id"])))
        assert case["status"] == "ACCEPTED"
        assert case["active_bed_hold_id"] is not None

        hold = get_hold(case["active_bed_hold_id"])
        assert hold["status"] == "ACTIVE"
        assert hold["bed_id"] == ws["beds"][9]["id"], (
            "the only AVAILABLE bed is the selector's entire pool"
        )
        post = get_facility(ws["fac_r"]["id"])
        assert post["occupancy_pct"] == pytest.approx(100.0)

    def test_saturation_auto_creates_active_all_units_diversion(self, api):
        """PRD: "When `occupancy_pct` reaches 95.0 or more — exactly 95.00
        triggers — and the facility has no `ACTIVE` diversion event scoped
        `ALL_UNITS`, the system auto-creates a `DiversionEvent` with scope
        `ALL_UNITS`, a window starting at the current clock and ending four
        hours later, the reason `AUTO_OCCUPANCY_SATURATION`, and `auto_created`
        set to true."
        PRD: "The facility-level `diversion_status` is then a roll-up of its
        events: `HARD_DIVERSION` when any of the facility's events is `ACTIVE`
        with scope `ALL_UNITS`; `SOFT_DIVERSION` when any event is `ACTIVE`
        with scope `SPECIFIC_UNIT` and none is `ACTIVE` with scope
        `ALL_UNITS`; otherwise `OPEN`."

        Design: Difficulty/transitive_cascade/accept_cascade_hold_bed_saturation_diversion
        """
        ws = self._workspace()
        validate_success(api.accept_case(
            ws["case"]["id"], {},
            make_receiving_physician_headers(ws["phys_r"]["id"])))
        events = list_diversion_events(ws["fac_r"]["id"])
        assert len(events) == 1, "the accept cascade must reach the saturation rule"
        event = events[0]
        assert event["auto_created"] is True
        assert event["scope"] == "ALL_UNITS"
        assert event["effective_status"] == "ACTIVE"
        assert get_facility(ws["fac_r"]["id"])["diversion_status"] == "HARD_DIVERSION"
