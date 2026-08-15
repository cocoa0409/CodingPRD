"""Arrival cascade, completion, cancellation compensation, and clocked durations."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_transfer_outcome,
    arrive_case,
    cancel_case,
    certify_screening,
    complete_case,
    create_bed,
    create_case,
    create_facility,
    create_notification,
    create_physician,
    create_screening,
    dispatch_case,
    drive_to_accepted,
    drive_to_arrived,
    drive_to_awaiting,
    drive_to_dispatch_ready,
    drive_to_en_route,
    get_case,
    get_case_outcome,
    get_dispatch,
    get_facility,
    get_hold,
    get_notification,
    is_valid_uuid,
    list_communications,
    list_diversion_events,
    list_reviews,
    make_receiving_physician_headers,
    make_sending_physician_headers,
    mark_notified,
    request_acceptance,
    set_bed_status,
    set_clock,
    setup_certified_case,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY, COORD
from test_helpers import api_client


def _en_route_case(patient_ref="PT-ARR-1", acuity="EMERGENT"):
    ws = setup_certified_case(acuity=acuity, unit="ICU", patient_ref=patient_ref)
    drive_to_awaiting(ws)
    drive_to_accepted(ws)
    drive_to_dispatch_ready(ws)
    drive_to_en_route(ws, "GROUND_ALS", "ALS", 20)
    return ws


class TestArrivalCascade:
    def test_arrival_confirms_hold_occupies_bed_creates_outcome(self, api):
        """PRD: "Beyond the dispatch bookkeeping of §3.7, arriving flips the
        case's `ACTIVE` hold to `CONFIRMED` with `release_reason`
        `ARRIVAL_CONFIRMED`, and that confirmation flips the held bed `HELD →
        OCCUPIED`, recomputing the receiving facility's occupancy and
        evaluating saturation."
        PRD: "It then creates the case's `TransferOutcome` — exactly one per
        case — recording the supplied `arrival_condition` of `STABLE`,
        `DETERIORATED`, or `CRITICAL_DECLINE`, the `deterioration_en_route`
        flag, whether the receiving physician `receiving_physician_confirmed`
        the arrival condition, and a `recorded_at` stamp."

        Design: Corner/endpoints/arrival_confirms_hold_occupies_bed_creates_outcome
        """
        ws = _en_route_case()
        case = arrive_case(ws["case"]["id"], "STABLE", False, True)
        assert case["status"] == "ARRIVED"

        hold = get_hold(ws["hold_id"])
        assert hold["status"] == "CONFIRMED"
        assert hold["release_reason"] == "ARRIVAL_CONFIRMED"

        fac = get_facility(ws["fac_r"]["id"])
        assert fac["unavailable_bed_count"] == 1, (
            "the confirmed bed still counts, now as OCCUPIED"
        )

        outcomes = get_case_outcome(ws["case"]["id"])
        assert len(outcomes) == 1
        assert_transfer_outcome(outcomes[0])
        assert outcomes[0]["arrival_condition"] == "STABLE"
        assert outcomes[0]["deterioration_en_route"] is False

        assert get_dispatch(ws["dispatch"]["id"])["status"] == "ARRIVED"

    def test_deterioration_arrival_opens_review_and_complete_does_not_duplicate(
            self, api):
        """PRD: "When `deterioration_en_route` is true and no review is already
        `OPEN` or `UNDER_REVIEW`, a `QualityReview` with trigger `DETERIORATION`
        opens automatically."
        PRD: "Completing the case is the administrative close: from `ARRIVED`,
        it ensures a routine review exists — creating a `QualityReview` with
        trigger `ROUTINE` in `OPEN` when none is `OPEN` or `UNDER_REVIEW` — and
        moves the case `ARRIVED → COMPLETED`."

        Design: Corner/endpoints/deterioration_arrival_opens_review_and_complete_does_not_duplicate
        """
        # Case A: will arrive with deterioration. Case B: clean arrival.
        ws_a = _en_route_case(patient_ref="PT-DET-A")
        ws_b = setup_certified_case(
            acuity="EMERGENT", unit="ICU",
            rcv_beds=(("ICU-02", "ICU", None),),
            snd_code="SNDB", rcv_code="RCVB",
            patient_ref="PT-DET-B")
        drive_to_awaiting(ws_b)
        drive_to_accepted(ws_b)
        drive_to_dispatch_ready(ws_b, channel="PHONE")
        drive_to_en_route(ws_b, "GROUND_ALS", "ALS", 20)
        drive_to_arrived(ws_b, "STABLE", False, True)

        arrive_case(ws_a["case"]["id"], "DETERIORATED", True, True)
        reviews_a = list_reviews(transfer_case_id=ws_a["case"]["id"])
        assert len(reviews_a) == 1
        assert reviews_a[0]["trigger"] == "DETERIORATION"
        assert reviews_a[0]["status"] == "OPEN"

        completed_a = complete_case(ws_a["case"]["id"])
        assert completed_a["status"] == "COMPLETED"
        reviews_a_after = list_reviews(transfer_case_id=ws_a["case"]["id"])
        assert len(reviews_a_after) == 1, (
            "the open DETERIORATION review satisfies the completion guard"
        )

        completed_b = complete_case(ws_b["case"]["id"])
        assert completed_b["status"] == "COMPLETED"
        reviews_b = list_reviews(transfer_case_id=ws_b["case"]["id"])
        assert len(reviews_b) == 1
        assert reviews_b[0]["trigger"] == "ROUTINE"
        assert reviews_b[0]["status"] == "OPEN"


class TestCancellation:
    def test_cancel_voids_pending_notification_and_communication(self, api):
        """PRD: "From any of `INTAKE`, `EMTALA_DETERMINED`,
        `AWAITING_ACCEPTANCE`, `REFUSED`, `ACCEPTED`, or `TRANSPORT_ARRANGED` —
        anything else draws `ERR_INVALID_STATE` — a `TransferCoordinator`
        cancels with a `cancel_reason`, and the system compensates every entity
        that exists: an `ACTIVE` hold flips to `RELEASED` with `release_reason`
        `CASE_CANCELLED`, freeing its bed `HELD → AVAILABLE` with the usual
        occupancy recompute and saturation evaluation; a notification in
        `PENDING`, `NOTIFIED`, or `EXCEPTION_CLAIMED` flips to `VOIDED`; a
        `DISPATCHED` transport flips to `CANCELLED`; a `PENDING` communication
        flips to `VOIDED`; and the case lands in `CANCELLED` with its version
        bumped."

        Design: Corner/state_machines/cancel_voids_pending_notification_and_communication
        """
        ws = setup_certified_case(acuity="EMERGENT", unit="ICU", rcv_beds=(),
                                  patient_ref="PT-VOID-1")
        drive_to_awaiting(ws)
        notif = create_notification(ws["case"]["id"])

        case = cancel_case(ws["case"]["id"],
                           "Patient condition resolved at sending facility.")
        assert case["status"] == "CANCELLED"
        assert get_notification(notif["id"])["status"] == "VOIDED"
        comms = list_communications(transfer_case_id=ws["case"]["id"])
        assert len(comms) == 1
        assert comms[0]["outcome"] == "VOIDED"

    def test_terminal_case_lockdown_rejected(self, api):
        """PRD: "From any of `INTAKE`, `EMTALA_DETERMINED`,
        `AWAITING_ACCEPTANCE`, `REFUSED`, `ACCEPTED`, or `TRANSPORT_ARRANGED` —
        anything else draws `ERR_INVALID_STATE` — a `TransferCoordinator`
        cancels with a `cancel_reason`, and the system compensates every entity
        that exists: an `ACTIVE` hold flips to `RELEASED` with `release_reason`
        `CASE_CANCELLED`, freeing its bed `HELD → AVAILABLE` with the usual
        occupancy recompute and saturation evaluation; a notification in
        `PENDING`, `NOTIFIED`, or `EXCEPTION_CLAIMED` flips to `VOIDED`; a
        `DISPATCHED` transport flips to `CANCELLED`; a `PENDING` communication
        flips to `VOIDED`; and the case lands in `CANCELLED` with its version
        bumped."
        PRD: "`COMPLETED` and `CANCELLED` are the case's terminal states."

        Design: Corner/state_machines/terminal_case_lockdown_rejected
        """
        ws = setup_certified_case(acuity="URGENT", unit="TELEMETRY", rcv_beds=(),
                                  patient_ref="PT-TERM-1")
        cancel_case(ws["case"]["id"], "Transfer no longer clinically indicated.")

        resp = api.request_acceptance(
            ws["case"]["id"],
            {"receiving_facility_id": ws["fac_r"]["id"],
             "receiving_physician_id": ws["phys_r"]["id"],
             "contact_method": "PHONE"},
            COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        resp = api.cancel_case(
            ws["case"]["id"], {"cancel_reason": "Second cancel attempt."}, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        assert get_case(ws["case"]["id"])["status"] == "CANCELLED"


class TestCancelCascadeAutoLift:
    def _workspace(self):
        """RCV with 9 ICU beds (8 OCCUPIED); CRITICAL case ACCEPTED (hold makes
        9/9 = 100.0, so an auto ALL_UNITS diversion exists); insurance NOTIFIED."""
        fac_s = create_facility()
        fac_r = create_facility(name="Receiving Trauma Center", facility_code="RCV",
                                trauma_level="LEVEL_1",
                                capabilities=["CARDIAC_CATH"])
        beds = [create_bed(fac_r["id"], f"ICU-{i:02d}", "ICU")
                for i in range(1, 10)]
        for bed in beds[:8]:
            set_bed_status(bed["id"], fac_r["id"], "OCCUPIED")
        phys_s = create_physician("Dr Send", fac_s["id"], "EMERGENCY")
        phys_r = create_physician("Dr Recv", fac_r["id"], "INTENSIVIST")
        case = create_case(fac_s["id"], phys_s["id"], "CRITICAL", "ICU",
                           "CARDIAC_CATH", False, "PT-CXL-1")
        create_screening(case["id"], phys_s["id"], True, True)
        certify_screening(case["id"], phys_s["id"])
        request_acceptance(case["id"], fac_r["id"], phys_r["id"])
        case = validate_success(api_client.accept_case(
            case["id"], {}, make_receiving_physician_headers(phys_r["id"])))
        notif = mark_notified(create_notification(case["id"])["id"])
        return {"fac_s": fac_s, "fac_r": fac_r, "beds": beds,
                "phys_s": phys_s, "phys_r": phys_r, "case": case,
                "hold_id": case["active_bed_hold_id"], "notif": notif}

    def test_cancel_releases_hold_and_voids_notification(self, api):
        """PRD: "a `TransferCoordinator` cancels with a `cancel_reason`, and the
        system compensates every entity that exists: an `ACTIVE` hold flips to
        `RELEASED` with `release_reason` `CASE_CANCELLED`, freeing its bed
        `HELD → AVAILABLE` with the usual occupancy recompute and saturation
        evaluation; a notification in `PENDING`, `NOTIFIED`, or
        `EXCEPTION_CLAIMED` flips to `VOIDED`; a `DISPATCHED` transport flips
        to `CANCELLED`; a `PENDING` communication flips to `VOIDED`; and the
        case lands in `CANCELLED` with its version bumped."

        Design: Difficulty/transitive_cascade/cancel_cascade_release_bed_auto_lift
        """
        ws = self._workspace()
        case = cancel_case(ws["case"]["id"],
                           "Patient family declined transfer after consent "
                           "discussion.")
        assert case["status"] == "CANCELLED"

        hold = get_hold(ws["hold_id"])
        assert hold["status"] == "RELEASED"
        assert hold["release_reason"] == "CASE_CANCELLED"
        assert get_notification(ws["notif"]["id"])["status"] == "VOIDED"

    def test_cancel_occupancy_drop_auto_lifts_diversion(self, api):
        """PRD: "From any of `INTAKE`, `EMTALA_DETERMINED`,
        `AWAITING_ACCEPTANCE`, `REFUSED`, `ACCEPTED`, or `TRANSPORT_ARRANGED` —
        anything else draws `ERR_INVALID_STATE` — a `TransferCoordinator`
        cancels with a `cancel_reason`, and the system compensates every entity
        that exists: an `ACTIVE` hold flips to `RELEASED` with `release_reason`
        `CASE_CANCELLED`, freeing its bed `HELD → AVAILABLE` with the usual
        occupancy recompute and saturation evaluation; a notification in
        `PENDING`, `NOTIFIED`, or `EXCEPTION_CLAIMED` flips to `VOIDED`; a
        `DISPATCHED` transport flips to `CANCELLED`; a `PENDING` communication
        flips to `VOIDED`; and the case lands in `CANCELLED` with its version
        bumped."
        PRD: "When `occupancy_pct` falls strictly below 90.0 — a reading of
        exactly 90.00 does not lift anything — every auto-created, `ACTIVE`,
        `ALL_UNITS` diversion of the facility is lifted at the current clock."

        Design: Difficulty/transitive_cascade/cancel_cascade_release_bed_auto_lift
        """
        ws = self._workspace()
        events = list_diversion_events(ws["fac_r"]["id"])
        assert len(events) == 1 and events[0]["effective_status"] == "ACTIVE", (
            "accept at 9/9 = 100.0 auto-creates the diversion"
        )

        cancel_case(ws["case"]["id"],
                    "Patient family declined transfer after consent discussion.")
        fac = get_facility(ws["fac_r"]["id"])
        assert fac["occupancy_pct"] == pytest.approx(88.89), (
            "8 of 9 beds unavailable after the release"
        )
        event = list_diversion_events(ws["fac_r"]["id"])[0]
        assert event["effective_status"] == "LIFTED"
        assert event["lifted_at"] is not None
        assert fac["diversion_status"] == "OPEN"


class TestDurationVariants:
    def _arrived_with_lag(self):
        """EMERGENT case determined 00:00, departed 04:00, arrived 05:00."""
        ws = setup_certified_case(acuity="EMERGENT", unit="ICU",
                                  patient_ref="PT-DUR-1")
        drive_to_awaiting(ws)
        drive_to_accepted(ws)
        drive_to_dispatch_ready(ws, channel="PHONE")
        ws["dispatch"] = dispatch_case(ws["case"]["id"], "GROUND_ALS", "ALS", 90)
        set_clock("2026-08-01T04:00:00Z")
        from test_helpers import depart_case
        depart_case(ws["case"]["id"])
        set_clock("2026-08-01T05:00:00Z")
        drive_to_arrived(ws, "STABLE", False, True)
        return ws

    def test_clinical_intent_duration_measures_from_determination(self, api):
        """PRD: "The outcome's `door_to_arrival_minutes` is the clinical-intent
        duration: elapsed seconds between the case's `emtala_determined_at` and
        the arrival instant, divided by 60, rounded down."

        Design: Difficulty/dual_variant_calc/clinical_intent_vs_operational_duration_split
        """
        ws = self._arrived_with_lag()
        outcomes = get_case_outcome(ws["case"]["id"])
        assert len(outcomes) == 1
        assert outcomes[0]["door_to_arrival_minutes"] == 300, (
            "00:00 determination to 05:00 arrival is 300 minutes"
        )
        assert ws["case"]["status"] == "ARRIVED"

    def test_operational_duration_measures_departure_to_arrival(self, api):
        """PRD: "Arrival requires the case in `EN_ROUTE` with its active
        dispatch `EN_ROUTE`; it stamps `arrived_at`, flips the dispatch to
        `ARRIVED`, and computes `actual_duration_minutes` as the elapsed
        seconds between `departed_at` and `arrived_at` divided by 60 and
        rounded down — the operational wheels-rolling measurement, always
        strictly smaller than the clinical-intent measurement of §3.8 whenever
        departure lagged determination."

        Design: Difficulty/dual_variant_calc/clinical_intent_vs_operational_duration_split
        """
        ws = self._arrived_with_lag()
        disp = get_dispatch(ws["dispatch"]["id"])
        assert disp["status"] == "ARRIVED"
        assert disp["actual_duration_minutes"] == 60, (
            "04:00 departure to 05:00 arrival is 60 minutes"
        )
        outcome = get_case_outcome(ws["case"]["id"])[0]
        assert outcome["door_to_arrival_minutes"] != disp["actual_duration_minutes"]


class TestImmediateConsistency:
    def test_mutation_responses_reflect_side_effects_immediately(self, api):
        """PRD: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD: "A successful certification flips the screening to `CERTIFIED`
        with `certified_at` stamped from the clock, mirrors the `determination`
        onto the case's `emtala_obligation`, stamps the case's
        `emtala_determined_at`, advances the case `INTAKE → EMTALA_DETERMINED`,
        and bumps the case version."

        Design: Corner/consistency_model/mutation_responses_reflect_side_effects_immediately
        """
        fac_s = create_facility()
        fac_r = create_facility(name="Receiving Trauma Center", facility_code="RCV",
                                trauma_level="LEVEL_1",
                                capabilities=["CARDIAC_CATH"])
        create_bed(fac_r["id"], "ICU-01", "ICU")
        phys_s = create_physician("Dr Send", fac_s["id"], "EMERGENCY")
        phys_r = create_physician("Dr Recv", fac_r["id"], "INTENSIVIST")
        case = create_case(fac_s["id"], phys_s["id"], "CRITICAL", "ICU",
                           "CARDIAC_CATH", False, "PT-IMM-2")
        create_screening(case["id"], phys_s["id"], True, True)

        certified = validate_success(api.certify_emtala_screening(
            case["id"], make_sending_physician_headers(phys_s["id"])))
        assert certified["status"] == "CERTIFIED"
        assert certified["determination"] == "EMTALA_APPLIES"

        requested = validate_success(api.request_acceptance(
            case["id"],
            {"receiving_facility_id": fac_r["id"],
             "receiving_physician_id": phys_r["id"], "contact_method": "PHONE"},
            COORD))
        assert requested["status"] == "AWAITING_ACCEPTANCE"
        assert requested["negotiation_round"] == 1

        accepted = validate_success(api.accept_case(
            case["id"], {}, make_receiving_physician_headers(phys_r["id"])))
        assert accepted["status"] == "ACCEPTED"
        assert is_valid_uuid(accepted["active_bed_hold_id"]), (
            "the accept response itself carries the new hold id"
        )

        read_back = get_case(case["id"])
        assert read_back["emtala_obligation"] == "EMTALA_APPLIES", (
            "the certified obligation is visible on the very next read"
        )

