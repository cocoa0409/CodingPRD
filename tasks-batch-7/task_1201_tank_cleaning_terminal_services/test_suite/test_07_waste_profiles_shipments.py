"""Waste profiling, shipment logistics, and the reclassification cascade
(PRD §3.5, §3.8)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_waste_profile_payload, create_waste_shipment_payload,
    new_ctx, create_job, create_approved_profile, add_shipment,
    record_sludge, request_gas_free, issue_certificate, add_permit,
    begin_entry, complete_entry, add_inspector, create_inspection,
    run_inspection, begin_and_verify_flush, request_rts,
    contractor_headers, get_job,
    setup_ctx_heel_removed, setup_ctx_flush_verified,
)

OPERATOR = TEST_USERS["operator_headers"]
EHS = TEST_USERS["ehs_headers"]

K051_SLUDGE = [{"material": "SLUDGE", "kg": 2542, "rate_cents_per_kg": 2.0}]


class TestShippedSolidsInvariant:
    def test_deliver_then_void_restores_shipped_solids_exactly(self, api):
        """PRD §3.5: "delivery moves `IN_TRANSIT` to `DELIVERED` and recomputes the job's `shipped_solids_kg` — defined as the manifested kilograms over all of the job's shipments in `DELIVERED` or `RECONCILED`, plus the job's `residual_sludge_kg`."
        PRD §3.5: "Every void recomputes `shipped_solids_kg` and re-runs the return-to-service revert check."

        Design: Difficulty/compensating_invariant/waste_manifested_mass_create_void_invariant
        """
        ctx = setup_ctx_heel_removed()
        create_approved_profile(ctx)
        assert get_job(ctx)["shipped_solids_kg"] == 0

        shipment = add_shipment(ctx, K051_SLUDGE)  # dispatch + deliver
        assert get_job(ctx)["shipped_solids_kg"] == 2542

        validate_success(api.void_shipment(shipment["id"], OPERATOR), 200)
        after = get_job(ctx)
        assert after["shipped_solids_kg"] == 0, (
            "compensating void must restore the counted mass with zero drift")

    def test_booked_shipment_does_not_count_toward_shipped_solids(self, api):
        """PRD §3.5: "the job's `shipped_solids_kg` — defined as the manifested kilograms over all of the job's shipments in `DELIVERED` or `RECONCILED`, plus the job's `residual_sludge_kg`"

        Design: Difficulty/compensating_invariant/waste_manifested_mass_create_void_invariant
        """
        ctx = setup_ctx_heel_removed()
        create_approved_profile(ctx)
        add_shipment(ctx, K051_SLUDGE, dispatch=False, deliver=False)
        assert get_job(ctx)["shipped_solids_kg"] == 0


class TestProfileReclassifyCascade:
    def _rts_pending_with_two_shipments(self, api):
        ctx = setup_ctx_flush_verified(
            terminal_overrides={"mass_balance_tolerance_pct": 2.0},
            shipment_lines=[{"material": "SLUDGE", "kg": 2000,
                             "rate_cents_per_kg": 2.0}],
            reconcile=True)
        s1 = ctx["shipments"][0]
        s2 = add_shipment(ctx, [{"material": "WASH_WATER", "kg": 542,
                                 "rate_cents_per_kg": 1.0}])
        # shipped = 2000 + 542 + 0 = 2542 == expected -> RTS gate passes.
        job = request_rts(ctx)
        assert job["status"] == "RTS_PENDING"
        return ctx, s1, s2

    def test_reclassify_voids_delivered_shipment_and_reverts_rts_gate(self, api):
        """PRD §3.5: "The profile returns to `DRAFT` with the new hazard class, every waste shipment referencing it in `BOOKED`, `IN_TRANSIT`, or `DELIVERED` is voided (manifests invalidated by the reclassification; already-`RECONCILED` shipments survive untouched), each voided shipment triggers a recompute of its job's `shipped_solids_kg`, and if that job was sitting in `RTS_PENDING` and the mass balance of §3.8 now fails, the job automatically falls back to `FLUSH_VERIFIED`."

        Design: Difficulty/transitive_cascade/profile_reclassify_cascade_depth2
        """
        ctx, s1, s2 = self._rts_pending_with_two_shipments(api)
        profile = validate_success(api.reclassify_waste_profile(
            ctx["profile"]["id"], {"hazard_class": "HAZARDOUS"}, EHS), 200)
        assert profile["status"] == "DRAFT"
        assert profile["hazard_class"] == "HAZARDOUS"

        s2_after = validate_success(api.get_waste_shipment(s2["id"], OPERATOR), 200)
        assert s2_after["status"] == "VOIDED"
        s1_after = validate_success(api.get_waste_shipment(s1["id"], OPERATOR), 200)
        assert s1_after["status"] == "RECONCILED"

        job = get_job(ctx)
        assert job["shipped_solids_kg"] == 2000
        # |2000 - 2542| = 542 > 50.84 (2% tolerance) -> gate reverted.
        assert job["status"] == "FLUSH_VERIFIED"

    def test_noop_reclassification_rejected(self, api):
        """PRD §3.5: "When an `EHSOfficer` reclassifies an `APPROVED` profile, the request's `hazard_class` must differ from the current one — a no-op reclassification is rejected with `ERR_INVALID_REQUEST`."

        Design: Difficulty/transitive_cascade/profile_reclassify_cascade_depth2
        """
        ctx = new_ctx()
        create_job(ctx)
        profile = create_approved_profile(ctx, hazard_class="NON_HAZARDOUS")
        res = api.reclassify_waste_profile(
            profile["id"], {"hazard_class": "NON_HAZARDOUS"}, EHS)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        after = validate_success(api.get_waste_profile(profile["id"], OPERATOR), 200)
        assert after["status"] == "APPROVED"


class TestShipmentAndSludgeGates:
    def test_deliver_from_booked_rejected(self, api):
        """PRD §3.5: "Dispatch moves `BOOKED` to `IN_TRANSIT`; delivery moves `IN_TRANSIT` to `DELIVERED`"

        Design: Corner/state_machines/shipment_deliver_from_booked_rejected
        """
        ctx = new_ctx()
        create_job(ctx, heel_volume_liters_sounding=100,
                   base_service_fee_cents=1000)
        create_approved_profile(ctx)
        shipment = add_shipment(
            ctx, [{"material": "SLUDGE", "kg": 50, "rate_cents_per_kg": 2.0}],
            dispatch=False, deliver=False)
        res = api.deliver_shipment(shipment["id"], contractor_headers(ctx))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(api.get_waste_shipment(shipment["id"], OPERATOR), 200)
        assert after["status"] == "BOOKED"

    def test_sludge_removal_without_approved_profile_rejected(self, api):
        """PRD §3.5: "an `APPROVED` waste profile must exist for the job, failing which `ERR_WASTE_PROFILE_NOT_APPROVED`"

        Design: Corner/validations/sludge_removal_without_approved_profile_rejected
        """
        ctx = setup_ctx_heel_removed()
        profile = validate_success(api.create_waste_profile(
            create_waste_profile_payload(ctx["job"]["id"]),
            contractor_headers(ctx)), 201)
        validate_success(api.submit_waste_profile(
            profile["id"], contractor_headers(ctx)), 200)  # SUBMITTED only
        res = api.record_sludge_removal(
            ctx["job"]["id"], {"residual_sludge_kg": 0}, contractor_headers(ctx))
        validate_error(res, ApiErrorId.ERR_WASTE_PROFILE_NOT_APPROVED)
        assert get_job(ctx)["status"] == "HEEL_REMOVED"

    def test_sludge_removal_without_delivered_shipment_rejected(self, api):
        """PRD §3.5: "at least one shipment of the job must stand in `DELIVERED` or `RECONCILED`, failing which `ERR_NO_DELIVERED_SHIPMENT` (HTTP 409)"

        Design: Corner/validations/sludge_removal_without_delivered_shipment_rejected
        """
        ctx = setup_ctx_heel_removed()
        create_approved_profile(ctx)
        add_shipment(ctx, [{"material": "SLUDGE", "kg": 100,
                            "rate_cents_per_kg": 2.0}],
                     dispatch=False, deliver=False)  # BOOKED only
        res = api.record_sludge_removal(
            ctx["job"]["id"], {"residual_sludge_kg": 0}, contractor_headers(ctx))
        validate_error(res, ApiErrorId.ERR_NO_DELIVERED_SHIPMENT)
        assert get_job(ctx)["status"] == "HEEL_REMOVED"

    def test_second_profile_approval_rejected(self, api):
        """PRD §3.5: "Approval enforces a one-approved-profile-per-job invariant: if any other profile of the same job is already `APPROVED`, the approval is rejected with `ERR_PROFILE_ALREADY_APPROVED` (HTTP 409)."

        Design: Corner/validations/second_profile_approval_rejected
        """
        ctx = new_ctx()
        create_job(ctx, heel_volume_liters_sounding=100,
                   base_service_fee_cents=1000)
        p1 = create_approved_profile(ctx)
        p2 = validate_success(api.create_waste_profile(
            create_waste_profile_payload(ctx["job"]["id"], waste_code="K052",
                                         hazard_class="HAZARDOUS",
                                         lab_flash_point_c=55,
                                         lab_tph_mg_l=400),
            contractor_headers(ctx)), 201)
        validate_success(api.submit_waste_profile(
            p2["id"], contractor_headers(ctx)), 200)
        res = api.approve_waste_profile(p2["id"], EHS)
        validate_error(res, ApiErrorId.ERR_PROFILE_ALREADY_APPROVED)
        after = validate_success(api.get_waste_profile(p2["id"], OPERATOR), 200)
        assert after["status"] == "SUBMITTED"

    def test_shipment_profile_job_mismatch_rejected(self, api):
        """PRD §3.5: "Booking evaluates two checks in order: first the referenced profile must be `APPROVED`, failing which `ERR_WASTE_PROFILE_NOT_APPROVED` (HTTP 409); then the profile must belong to the same job as the shipment, failing which `ERR_SHIPMENT_PROFILE_MISMATCH` (HTTP 409)."

        Design: Corner/validations/shipment_profile_job_mismatch_rejected
        """
        ctx = new_ctx()
        job_a = create_job(ctx, heel_volume_liters_sounding=100,
                           base_service_fee_cents=1000)
        profile = create_approved_profile(ctx)
        job_b = create_job(ctx, heel_volume_liters_sounding=100,
                           base_service_fee_cents=1000)
        res = api.create_waste_shipment(
            create_waste_shipment_payload(
                job_b["id"], profile["id"],
                lines=[{"material": "SLUDGE", "kg": 10,
                        "rate_cents_per_kg": 2.0}]),
            contractor_headers(ctx))
        validate_error(res, ApiErrorId.ERR_SHIPMENT_PROFILE_MISMATCH)
