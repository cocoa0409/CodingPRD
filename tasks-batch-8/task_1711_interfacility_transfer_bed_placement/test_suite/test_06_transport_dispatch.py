"""Transport: dispatch gates, dual-variant ETT, depart/cancel, expiry boundary."""
from test_helpers import (
    ApiErrorId,
    assert_transport_dispatch,
    depart_case,
    dispatch_case,
    drive_to_accepted,
    drive_to_awaiting,
    drive_to_dispatch_ready,
    drive_to_en_route,
    exchange_imaging,
    get_case,
    get_dispatch,
    get_hold,
    list_dispatches,
    set_clock,
    setup_certified_case,
    create_notification,
    create_packet,
    mark_notified,
    upload_documents,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import COORD


def _accepted_case(acuity="CRITICAL", unit="ICU", patient_ref="PT-T-1"):
    ws = setup_certified_case(acuity=acuity, unit=unit, patient_ref=patient_ref)
    drive_to_awaiting(ws)
    drive_to_accepted(ws)
    return ws


def _dispatch_ready_case(acuity="CRITICAL", unit="ICU", patient_ref="PT-T-2"):
    ws = _accepted_case(acuity, unit, patient_ref)
    drive_to_dispatch_ready(ws)
    return ws


class TestDispatchSafetyGates:
    def test_crew_capability_insufficient_rejected(self, api):
        """PRD: "Crew capability must meet the acuity minimum: `CRITICAL`
        demands `CCT`, `EMERGENT` demands `ALS`, and `URGENT` or `STABLE`
        demand `BLS`; anything short fails with
        `ERR_CREW_CAPABILITY_INSUFFICIENT`."
        PRD: "Arranging transport is the densest gate in the workflow, and its
        checks fire in the ladder order of §2.8: state first, then crew, then
        distance, then packet, then hold, then payer."

        Design: Corner/validations/crew_capability_insufficient_rejected
        """
        ws = _accepted_case(patient_ref="PT-CREW-1")
        # No packet, no insurance: the crew rung must fire first.
        resp = api.create_dispatch(
            ws["case"]["id"],
            {"mode": "GROUND_ALS", "crew_capability": "ALS",
             "distance_miles": 20},
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_CAPABILITY_INSUFFICIENT, 422)

    def test_air_distance_below_minimum_rejected(self, api):
        """PRD: "Air modes carry distance floors — `AIR_ROTOR` requires at
        least 30 miles and `AIR_FIXED_WING` at least 100 — failing with
        `ERR_AIR_DISTANCE_BELOW_MINIMUM`."

        Design: Corner/validations/air_distance_below_minimum_rejected
        """
        ws = _dispatch_ready_case(patient_ref="PT-AIR-1")
        case_id = ws["case"]["id"]

        resp = api.create_dispatch(
            case_id, {"mode": "AIR_ROTOR", "crew_capability": "CCT",
                      "distance_miles": 29}, COORD)
        validate_error(resp, ApiErrorId.ERR_AIR_DISTANCE_BELOW_MINIMUM, 422)

        resp = api.create_dispatch(
            case_id, {"mode": "AIR_FIXED_WING", "crew_capability": "CCT",
                      "distance_miles": 90}, COORD)
        validate_error(resp, ApiErrorId.ERR_AIR_DISTANCE_BELOW_MINIMUM, 422)

        # The floor is inclusive: exactly 30 miles is legal for rotor.
        disp = dispatch_case(case_id, "AIR_ROTOR", "CCT", 30)
        assert_transport_dispatch(disp)
        assert disp["status"] == "DISPATCHED"
        assert disp["estimated_minutes_optimistic"] == 40, (
            "base ceil(30/120*60)=15 plus 25 rotor overhead"
        )

    def test_dispatch_without_any_packet_rejected(self, api):
        """PRD: "The case's clinical packet must exist with `overall_status`
        `READY`, failing with `ERR_PACKET_INCOMPLETE` (which also fires when no
        packet exists at all)."

        Design: Corner/validations/dispatch_without_any_packet_rejected
        """
        ws = setup_certified_case(acuity="URGENT", unit="TELEMETRY",
                                  rcv_beds=(("TEL-01", "TELEMETRY", None),),
                                  patient_ref="PT-NOPKT-1")
        drive_to_awaiting(ws)
        drive_to_accepted(ws)
        notif = create_notification(ws["case"]["id"])
        mark_notified(notif["id"])

        resp = api.create_dispatch(
            ws["case"]["id"],
            {"mode": "GROUND_BLS", "crew_capability": "BLS",
             "distance_miles": 8}, COORD)
        validate_error(resp, ApiErrorId.ERR_PACKET_INCOMPLETE, 409)


class TestDepartAndCancel:
    def test_case_depart_before_dispatch_rejected(self, api):
        """PRD: "Departing requires the case in `TRANSPORT_ARRANGED` and its
        latest dispatch still `DISPATCHED`; it flips the dispatch `DISPATCHED →
        EN_ROUTE`, stamps `departed_at`, moves the case `TRANSPORT_ARRANGED →
        EN_ROUTE`, and bumps the case version."

        Design: Corner/state_machines/case_depart_before_dispatch_rejected
        """
        ws = _accepted_case(patient_ref="PT-DEP-1")
        resp = api.depart_case(ws["case"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_case(ws["case"]["id"])["status"] == "ACCEPTED"
        assert list_dispatches(transfer_case_id=ws["case"]["id"]) == []

    def test_dispatch_cancel_after_depart_rejected(self, api):
        """PRD: "A dispatch that has not yet departed can be cancelled instead —
        only a `DISPATCHED` transport is cancellable, anything else drawing
        `ERR_DISPATCH_NOT_CANCELLABLE` — which flips it to `CANCELLED` and
        reverts the case `TRANSPORT_ARRANGED → ACCEPTED` so a different mode or
        crew can be arranged."

        Design: Corner/state_machines/dispatch_cancel_after_depart_rejected
        """
        ws = setup_certified_case(acuity="EMERGENT", unit="ICU",
                                  patient_ref="PT-DCX-1")
        drive_to_awaiting(ws)
        drive_to_accepted(ws)
        drive_to_dispatch_ready(ws)
        drive_to_en_route(ws, "GROUND_ALS", "ALS", 20)

        resp = api.cancel_transport_dispatch(ws["dispatch"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_DISPATCH_NOT_CANCELLABLE, 409)
        assert get_dispatch(ws["dispatch"]["id"])["status"] == "EN_ROUTE"
        assert get_case(ws["case"]["id"])["status"] == "EN_ROUTE"


class TestDualVariantEtt:
    def test_air_dispatch_stores_both_ett_variants(self, api):
        """PRD: "The estimate works from a base of the distance divided by the
        mode's cruise speed — 40 miles per hour for `GROUND_BLS`, 45 for
        `GROUND_ALS`, 120 for `AIR_ROTOR`, 160 for `AIR_FIXED_WING` —
        converted to minutes and rounded up to a whole minute."
        PRD: "`estimated_minutes_optimistic` is that base plus a mode overhead
        of 10 minutes for either ground mode, 25 for rotor, 45 for fixed wing."

        Design: Difficulty/dual_variant_calc/ett_optimistic_vs_conservative_air_dispatch
        """
        ws = _dispatch_ready_case(patient_ref="PT-ETT-1")
        disp = dispatch_case(ws["case"]["id"], "AIR_ROTOR", "CCT", 90)
        assert disp["estimated_minutes_optimistic"] == 70, (
            "ceil(90/120*60)=45 base + 25 rotor overhead"
        )

    def test_conservative_variant_adds_buffers_and_state_advances(self, api):
        """PRD: "`estimated_minutes_conservative` inflates the base by a
        quarter and rounds up before adding the same mode overhead, a crew
        buffer of 0 for `BLS` or `ALS`, 10 for `CCT`, and 15 for
        `CRITICAL_CARE`, and a further 10 minutes when the case acuity is
        `CRITICAL`."
        PRD: "A valid dispatch creates a `TransportDispatch` in `DISPATCHED`
        with `dispatched_at` stamped, both estimated durations computed, and
        the case advanced `ACCEPTED → TRANSPORT_ARRANGED`."

        Design: Difficulty/dual_variant_calc/ett_optimistic_vs_conservative_air_dispatch
        """
        ws = _dispatch_ready_case(patient_ref="PT-ETT-1b")
        disp = dispatch_case(ws["case"]["id"], "AIR_ROTOR", "CCT", 90)
        assert disp["estimated_minutes_conservative"] == 102, (
            "ceil(45*1.25)=57 + 25 overhead + 10 CCT buffer + 10 CRITICAL"
        )
        assert disp["estimated_minutes_conservative"] != (
            disp["estimated_minutes_optimistic"])
        assert disp["status"] == "DISPATCHED"
        assert get_case(ws["case"]["id"])["status"] == "TRANSPORT_ARRANGED"


class TestEttNonlinearInteraction:
    def test_cancel_reverts_case_for_redispatch(self, api):
        """PRD: "A dispatch that has not yet departed can be cancelled instead
        — only a `DISPATCHED` transport is cancellable, anything else drawing
        `ERR_DISPATCH_NOT_CANCELLABLE` — which flips it to `CANCELLED` and
        reverts the case `TRANSPORT_ARRANGED → ACCEPTED` so a different mode or
        crew can be arranged."

        Design: Difficulty/combinatorial_formula/ett_mode_crew_acuity_nonlinear_interaction
        """
        ws = _dispatch_ready_case(patient_ref="PT-COMB-1")
        case_id = ws["case"]["id"]
        air = dispatch_case(case_id, "AIR_ROTOR", "CCT", 90)
        assert air["estimated_minutes_optimistic"] == 70
        assert air["estimated_minutes_conservative"] == 102

        cancelled = validate_success(
            api.cancel_transport_dispatch(air["id"], COORD))
        assert cancelled["status"] == "CANCELLED"
        assert get_case(case_id)["status"] == "ACCEPTED", (
            "dispatch cancel must revert the case for re-selection"
        )

    def test_ground_redispatch_after_air_shows_nonadditive_buffers(self, api):
        """PRD: "The estimate works from a base of the distance divided by the
        mode's cruise speed — 40 miles per hour for `GROUND_BLS`, 45 for
        `GROUND_ALS`, 120 for `AIR_ROTOR`, 160 for `AIR_FIXED_WING` —
        converted to minutes and rounded up to a whole minute."
        PRD: "`estimated_minutes_conservative` inflates the base by a quarter
        and rounds up before adding the same mode overhead, a crew buffer of 0
        for `BLS` or `ALS`, 10 for `CCT`, and 15 for `CRITICAL_CARE`, and a
        further 10 minutes when the case acuity is `CRITICAL`."

        Design: Difficulty/combinatorial_formula/ett_mode_crew_acuity_nonlinear_interaction
        """
        ws = _dispatch_ready_case(patient_ref="PT-COMB-1b")
        case_id = ws["case"]["id"]
        air = dispatch_case(case_id, "AIR_ROTOR", "CCT", 90)
        validate_success(api.cancel_transport_dispatch(air["id"], COORD))
        gnd = dispatch_case(case_id, "GROUND_ALS", "CCT", 90)
        assert gnd["estimated_minutes_optimistic"] == 130, (
            "base ceil(90/45*60)=120 + 10 ground overhead"
        )
        assert gnd["estimated_minutes_conservative"] == 180, (
            "ceil(120*1.25)=150 + 10 overhead + 10 CCT + 10 CRITICAL"
        )
        assert (180 - 102) != (130 - 70), (
            "conservative gap (78) exceeds optimistic gap (60) — non-linear"
        )


class TestPacketGate:
    def _imaging_case(self):
        """ACCEPTED EMERGENT ICU case; packet docs done, imaging pending."""
        ws = setup_certified_case(acuity="EMERGENT", unit="ICU",
                                  patient_ref="PT-PKT-1")
        drive_to_awaiting(ws)
        drive_to_accepted(ws)
        drive_to_dispatch_ready(
            ws, required_documents=["H_AND_P"],
            imaging_studies=[{"study_ref": "CXR-1", "modality": "XRAY"}])
        return ws

    def test_dispatch_blocked_while_imaging_pending(self, api):
        """PRD: "`imaging_status` reads `IMAGING_COMPLETE` when every study
        reference in `imaging_studies` appears in `exchanged_study_refs` —
        vacuously true when no studies are required — otherwise
        `IMAGING_PENDING`."
        PRD: "`overall_status` is `READY` only when both are complete,
        otherwise `INCOMPLETE`."
        PRD: "The case's clinical packet must exist with `overall_status`
        `READY`, failing with `ERR_PACKET_INCOMPLETE` (which also fires when no
        packet exists at all)."

        Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_clinical_packet_status
        """
        ws = self._imaging_case()
        pkt = ws["packet"]
        assert pkt["document_status"] == "DOCUMENTS_COMPLETE"
        assert pkt["imaging_status"] == "IMAGING_PENDING"
        assert pkt["overall_status"] == "INCOMPLETE"

        resp = api.create_dispatch(
            ws["case"]["id"],
            {"mode": "GROUND_ALS", "crew_capability": "ALS",
             "distance_miles": 20}, COORD)
        validate_error(resp, ApiErrorId.ERR_PACKET_INCOMPLETE, 409)
        assert get_case(ws["case"]["id"])["status"] == "ACCEPTED"

    def test_imaging_exchange_unlocks_dispatch(self, api):
        """PRD: "Imaging confirmation works the same way without a version
        guard: the sending physician supplies the `exchanged_study_refs`
        confirmed exchanged, the set unions, the version bumps, and
        `imaging_status` and `overall_status` recompute."
        PRD: "A valid dispatch creates a `TransportDispatch` in `DISPATCHED`
        with `dispatched_at` stamped, both estimated durations computed, and
        the case advanced `ACCEPTED → TRANSPORT_ARRANGED`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_clinical_packet_status
        """
        ws = self._imaging_case()
        pkt = exchange_imaging(ws["packet"]["id"], ws["phys_s"]["id"], ["CXR-1"])
        assert pkt["imaging_status"] == "IMAGING_COMPLETE"
        assert pkt["overall_status"] == "READY"

        disp = dispatch_case(ws["case"]["id"], "GROUND_ALS", "ALS", 20)
        assert disp["status"] == "DISPATCHED"
        assert get_case(ws["case"]["id"])["status"] == "TRANSPORT_ARRANGED"


class TestPacketPrecedesInsurance:
    def test_dispatch_with_incomplete_packet_fails_referential_first(self, api):
        """PRD: "Where a single operation carries several checks from different
        rungs, the rung order decides which error the caller sees: at dispatch,
        for instance, an inadequate crew surfaces before an incomplete packet,
        which surfaces before an expired hold, which in turn surfaces before a
        missing payer clearance."
        PRD: "Finally, a notification in `NOTIFIED` or `EXCEPTION_CLAIMED` must
        exist, failing with `ERR_INSURANCE_NOT_CLEARED`."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_packet_error_precedes_insurance_error
        """
        ws = setup_certified_case(acuity="URGENT", unit="TELEMETRY",
                                  rcv_beds=(("TEL-01", "TELEMETRY", None),),
                                  patient_ref="PT-PRI-3a")
        drive_to_awaiting(ws)
        drive_to_accepted(ws)
        pkt = create_packet(ws["case"]["id"], ws["phys_s"]["id"],
                            ["H_AND_P", "LABS"])
        pkt = upload_documents(pkt["id"], ws["phys_s"]["id"], ["H_AND_P"],
                               pkt["version"])
        ws["packet"] = pkt
        # No insurance notification exists for the case.
        resp = api.create_dispatch(
            ws["case"]["id"],
            {"mode": "GROUND_BLS", "crew_capability": "BLS",
             "distance_miles": 12}, COORD)
        validate_error(resp, ApiErrorId.ERR_PACKET_INCOMPLETE, 409)

    def test_dispatch_after_packet_ready_fails_fiscal_check(self, api):
        """PRD: "Where a single operation carries several checks from different
        rungs, the rung order decides which error the caller sees: at dispatch,
        for instance, an inadequate crew surfaces before an incomplete packet,
        which surfaces before an expired hold, which in turn surfaces before a
        missing payer clearance."
        PRD: "Finally, a notification in `NOTIFIED` or `EXCEPTION_CLAIMED` must
        exist, failing with `ERR_INSURANCE_NOT_CLEARED`."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_packet_error_precedes_insurance_error
        """
        ws = setup_certified_case(acuity="URGENT", unit="TELEMETRY",
                                  rcv_beds=(("TEL-01", "TELEMETRY", None),),
                                  patient_ref="PT-PRI-3b")
        drive_to_awaiting(ws)
        drive_to_accepted(ws)
        pkt = create_packet(ws["case"]["id"], ws["phys_s"]["id"],
                            ["H_AND_P", "LABS"])
        pkt = upload_documents(pkt["id"], ws["phys_s"]["id"], ["H_AND_P"],
                               pkt["version"])
        pkt = upload_documents(pkt["id"], ws["phys_s"]["id"], ["LABS"],
                               pkt["version"])
        assert pkt["overall_status"] == "READY"

        resp = api.create_dispatch(
            ws["case"]["id"],
            {"mode": "GROUND_BLS", "crew_capability": "BLS",
             "distance_miles": 12}, COORD)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_NOT_CLEARED, 402)
        assert get_case(ws["case"]["id"])["status"] == "ACCEPTED", (
            "both rejections leave the case untouched"
        )


class TestHoldExpiryBoundary:
    def test_dispatch_one_minute_before_expiry_succeeds(self, api):
        """PRD: "The case's active hold must still be within its window — a
        hold whose `hold_expires_at` is at or before the clock flips to
        `EXPIRED` and the dispatch fails with `ERR_BED_HOLD_EXPIRED`."

        Design: Difficulty/boundary_precision_check/hold_expiry_exact_equality_blocks_dispatch
        """
        ws = _dispatch_ready_case(patient_ref="PT-EXP-A")
        set_clock("2026-08-01T00:59:00Z")  # CRITICAL hold expires 01:00:00Z
        disp = dispatch_case(ws["case"]["id"], "GROUND_ALS", "CCT", 45)
        assert disp["status"] == "DISPATCHED"
        assert get_case(ws["case"]["id"])["status"] == "TRANSPORT_ARRANGED"

    def test_dispatch_at_exact_expiry_rejected_and_hold_flips(self, api):
        """PRD: "The case's active hold must still be within its window — a
        hold whose `hold_expires_at` is at or before the clock flips to
        `EXPIRED` and the dispatch fails with `ERR_BED_HOLD_EXPIRED`."
        PRD: "A hold occupies its bed over a half-open interval — from
        `hold_started_at` up to but not including `hold_expires_at`; when the
        clock reaches the expiry instant exactly, the hold no longer blocks."

        Design: Difficulty/boundary_precision_check/hold_expiry_exact_equality_blocks_dispatch
        """
        # Packet READY but deliberately no insurance: the temporal rung must
        # fire before the fiscal rung would even be examined.
        ws = _accepted_case(patient_ref="PT-EXP-B")
        pkt = create_packet(ws["case"]["id"], ws["phys_s"]["id"], ["H_AND_P"])
        upload_documents(pkt["id"], ws["phys_s"]["id"], ["H_AND_P"],
                         pkt["version"])
        hold_id = ws["hold_id"]

        set_clock("2026-08-01T01:00:00Z")  # exactly hold_expires_at
        resp = api.create_dispatch(
            ws["case"]["id"],
            {"mode": "GROUND_ALS", "crew_capability": "CCT",
             "distance_miles": 45}, COORD)
        validate_error(resp, ApiErrorId.ERR_BED_HOLD_EXPIRED, 409)

        hold = get_hold(hold_id)
        assert hold["status"] == "EXPIRED"
        assert hold["release_reason"] == "EXPIRED"
        case = get_case(ws["case"]["id"])
        assert case["status"] == "ACCEPTED"
        assert case["active_bed_hold_id"] is None


