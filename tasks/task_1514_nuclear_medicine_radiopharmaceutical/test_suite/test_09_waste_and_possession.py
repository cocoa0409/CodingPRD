"""Waste decay-in-storage, clearance gating, the possession ledger, and the
container-seal concurrency checkpoint."""
import pytest

from test_helpers import (
    TEST_USERS,
    calibrate_vial,
    create_container,
    create_isotope,
    create_license,
    create_order,
    create_authorized_user,
    create_patient,
    create_room,
    get_container,
    get_license,
    get_vial,
    instants_equal,
    make_rso_headers,
    prepare_vial,
    record_survey,
    schedule_delivery,
    set_clock,
    setup_f18_administered,
    setup_f18_department,
    setup_f18_spill_contamination,
    setup_sealed_container_from_administered_vial,
    setup_sealed_container_with_decayed_vial,
    validate_error,
    validate_success,
    advance_spill,
    work_spill_to_decontaminated,
    receive_delivery,
    create_isotope_delivery_payload,
)

ADMIN = TEST_USERS["admin_headers"]
RP = TEST_USERS["radiopharmacist_headers"]


class TestVialActivityBalance:
    """Per-vial accountability: measured == administered + residual + decay
    loss, and the container's intake equals the residual."""

    def test_residual_and_decay_loss_balance(self, api):
        """PRD §3.7: "For an administered vial, `residual_activity_mbq` is the
        un-administered remainder — the vial's `measured_activity_mbq` minus the
        administration's `assayed_activity_exact_mbq` — decayed from the
        administration instant to the disposal instant. ... In both cases
        `decay_loss_mbq` captures the activity lost to physical decay between
        calibration and disposal, and the vial-activity-balance invariant holds:
        the measured activity at calibration is fully accounted for as the sum
        of the administered activity, the residual routed to waste, and the
        decay loss."

        Calibrated 220.000, administered to an assay of 110.000, disposed at the
        same instant: residual 110.000, decay loss 0.000,
        220.000 == 110.000 + 110.000 + 0.000.

        Design: Difficulty/compensating_invariant/vial_activity_balance_conserved
        """
        ctx = setup_f18_administered()
        assert ctx["administration"]["assayed_activity_exact_mbq"] == pytest.approx(
            110.000, abs=1e-9
        )
        container = create_container(ctx["isotope"]["id"], ctx["room"]["id"])
        vial = validate_success(
            api.dispose_dose_vial(
                ctx["vial"]["id"], {"waste_container_id": container["id"]}, RP
            ),
            200,
        )
        assert vial["status"] == "DISPOSED"
        assert vial["residual_activity_mbq"] == pytest.approx(110.000, abs=1e-9)
        assert vial["decay_loss_mbq"] == pytest.approx(0.000, abs=1e-9)
        total = (
            ctx["administration"]["assayed_activity_exact_mbq"]
            + vial["residual_activity_mbq"]
            + vial["decay_loss_mbq"]
        )
        assert total == pytest.approx(220.000, abs=1e-9), "vial-activity balance invariant"

    def test_container_intake_equals_residual(self, api):
        """PRD §3.7: "Disposal stamps `disposed_at`, moves the vial to
        `DISPOSED`, adds the residual rounded half-up to three decimal places
        into the container's `intake_activity_mbq`, and recomputes the
        possession ledger."

        Design: Difficulty/compensating_invariant/vial_activity_balance_conserved
        """
        ctx = setup_f18_administered()
        container = create_container(ctx["isotope"]["id"], ctx["room"]["id"])
        vial = validate_success(
            api.dispose_dose_vial(
                ctx["vial"]["id"], {"waste_container_id": container["id"]}, RP
            ),
            200,
        )
        container_after = get_container(container["id"])
        assert container_after["intake_activity_mbq"] == pytest.approx(
            vial["residual_activity_mbq"], abs=1e-9
        )
        assert container_after["intake_activity_mbq"] == pytest.approx(110.000, abs=1e-9)


class TestPossessionQuarantineRoundtrip:
    """Quarantine is not disposal: the possession total must not drift across a
    spill-driven quarantine and its clearance compensation at a fixed clock."""

    def test_possession_unchanged_by_quarantine_roundtrip(self, api):
        """PRD §2.6: "Excluded from the ledger: vials in `PREPARED` (not yet
        assayed), vials in `DECAYED`, `ADMINISTERED`, or `DISPOSED`, deliveries
        in `RECEIVED` or `FAILED` (received material is tracked through its
        vials instead), and containers in `CLEARED`. Quarantining a vial does
        not remove it from the ledger."

        Vial calibrated 220.000 at 08:30; at 08:45 the exact-variant decay is
        220.000 x 0.5^(15/110) = 200.158 — identical before and after the
        quarantine/clearance round-trip at the same clock instant.

        Design: Difficulty/compensating_invariant/possession_roundtrip_through_quarantine
        """
        ctx = setup_f18_spill_contamination()  # spill reported at clock 08:45
        poss_before = get_license(ctx["license"]["id"])["current_possession_mbq"]
        assert poss_before == pytest.approx(200.158, abs=1e-6)
        assert get_vial(ctx["vial"]["id"])["status"] == "QUARANTINED"

        # Possession still counts the quarantined vial at the same clock.
        poss_quarantined = get_license(ctx["license"]["id"])["current_possession_mbq"]
        assert poss_quarantined == pytest.approx(poss_before, abs=1e-9)

        work_spill_to_decontaminated(ctx["spill"]["id"], "rso-1")
        record_survey(ctx["room"]["id"], "PASS", "rso-1")
        advance_spill(ctx["spill"]["id"], "CLEARED", "rso-1")

        poss_after = get_license(ctx["license"]["id"])["current_possession_mbq"]
        assert poss_after == pytest.approx(200.158, abs=1e-6)
        assert poss_after == pytest.approx(poss_before, abs=1e-9)

    def test_vial_restored_to_calibrated_after_clearance(self, api):
        """PRD §3.6: "Every order sitting `ON_HOLD` with `hold_reason` of
        `SPILL_CONTAMINATION` returns to its recorded `hold_previous_status`
        with `hold_reason` cleared, and each such order's `QUARANTINED` vials
        return to `CALIBRATED`."

        Design: Difficulty/compensating_invariant/possession_roundtrip_through_quarantine
        """
        ctx = setup_f18_spill_contamination()
        work_spill_to_decontaminated(ctx["spill"]["id"], "rso-1")
        record_survey(ctx["room"]["id"], "PASS", "rso-1")
        advance_spill(ctx["spill"]["id"], "CLEARED", "rso-1")

        assert get_vial(ctx["vial"]["id"])["status"] == "CALIBRATED"
        assert get_license(ctx["license"]["id"])["current_possession_mbq"] == pytest.approx(
            200.158, abs=1e-6
        )


class TestPossessionPerComponentRounding:
    """Pinned rounding order: each component rounded half-up to three decimals
    before the sum. Two vials decaying to a raw 0.9937... each contribute
    0.994; the conformant total is 1.988, not the sum-then-round 1.987."""

    def _trace_fixture(self, api):
        """Two CALIBRATED vials of 1.000 MBq (min usable 0.5), one per order,
        both calibrated at 08:30; the only RECEIVED delivery is excluded."""
        set_clock("2026-08-01T08:00:00Z")
        iso = create_isotope(None, name="F-18 trace", min_usable_activity_mbq=0.5)
        lic = create_license(iso["id"], license_number="L-300")
        au = create_authorized_user(lic["id"], full_name="Dr. C")
        pat = create_patient(full_name="P Three", weight_kg=60)
        delivery = schedule_delivery(iso["id"])
        receive_delivery(delivery["id"], 5000)
        set_clock("2026-08-01T08:30:00Z")
        vials = []
        for _ in range(2):
            order = create_order(
                pat["id"], iso["id"], au,
                prescribed_activity_mbq=1,
                administration_scheduled_at="2026-08-01T12:00:00Z",
            )
            vial = prepare_vial(order["id"], delivery["id"])
            vials.append(calibrate_vial(vial["id"], 1, "rp-1"))
        return {"isotope": iso, "license": lic, "vials": vials}

    def test_components_rounded_before_sum(self, api):
        """PRD §2.6: "The rounding order is pinned: every component is
        individually rounded half-up to three decimal places before the sum is
        taken, and the sum itself is then rounded half-up to three decimal
        places. Summing raw values and rounding once at the end is a different,
        non-conformant order."

        One minute after calibration each 1.000 MBq vial contributes
        round(1.000 x 0.5^(1/110), 3) = round(0.9937..., 3) = 0.994, so the
        ledger reads 1.988.

        Design: Difficulty/combinatorial_formula/possession_per_component_rounding_order
        """
        ctx = self._trace_fixture(api)
        set_clock("2026-08-01T08:31:00Z")
        possession = get_license(ctx["license"]["id"])["current_possession_mbq"]
        assert possession == pytest.approx(1.988, abs=1e-9), (
            "per-component rounding: 0.994 + 0.994 = 1.988 (sum-then-round would give 1.987)"
        )

    def test_possession_baseline_at_calibration_instant(self, api):
        """PRD §2.6: "**Vials** in `CALIBRATED` or `QUARANTINED` status — each
        contributes its `measured_activity_mbq` decay-corrected (exact variant)
        from its `calibrated_at` to the current instant."

        At the calibration instant itself each vial contributes exactly 1.000
        and the ledger reads 2.000 — the zero-elapsed control for the pinned
        per-component rounding rule.

        Design: Difficulty/combinatorial_formula/possession_per_component_rounding_order
        """
        ctx = self._trace_fixture(api)
        possession = get_license(ctx["license"]["id"])["current_possession_mbq"]
        assert possession == pytest.approx(2.000, abs=1e-9)


class TestPossessionStateFiltering:
    def test_decayed_vial_drops_out_and_future_reference_grows(self, api):
        """PRD §2.6: "**Deliveries** in `SCHEDULED` status — each contributes
        its `reference_activity_mbq` decay-corrected (exact variant) from its
        `reference_time_at` to the current instant." and "Excluded from the
        ledger: vials in `PREPARED` (not yet assayed), vials in `DECAYED`,
        `ADMINISTERED`, or `DISPOSED`, deliveries in `RECEIVED` or `FAILED`..."
        and PRD §2.4: "both directions of the difference are defined — a target
        earlier than its reference yields a negative elapsed value..."

        At 08:30 the ledger holds the calibrated vial (20.000) plus the inbound
        1000 MBq delivery referenced at 12:00, decay-corrected upward by 210
        minutes (~3755.7). At 10:21 the sweep has decayed the vial below its
        10 MBq floor (9.937 < 10 -> DECAYED, excluded) and the delivery's
        contribution, now 99 minutes before its reference instant, is
        1000 x 2^0.9 = 1866.066.

        Design: Corner/calculations/possession_state_filtering_and_future_reference_decay
        """
        ctx = setup_f18_department()
        inbound = validate_success(
            api.create_isotope_delivery(
                create_isotope_delivery_payload(
                    ctx["isotope"]["id"],
                    scheduled_arrival_at="2026-08-01T12:00:00Z",
                    reference_activity_mbq=1000,
                    reference_time_at="2026-08-01T12:00:00Z",
                ),
                RP,
            ),
            201,
        )
        assert inbound["status"] == "SCHEDULED"

        order = create_order(
            ctx["patient"]["id"], ctx["isotope"]["id"], ctx["authorized_user"],
            prescribed_activity_mbq=15,
        )
        vial = prepare_vial(order["id"], ctx["delivery"]["id"])
        calibrate_vial(vial["id"], 20, "rp-1")

        poss1 = get_license(ctx["license"]["id"])["current_possession_mbq"]
        assert poss1 == pytest.approx(3775.724, abs=0.02), (
            "vial 20.000 + inbound delivery decay-corrected upward ~3755.7"
        )

        set_clock("2026-08-01T10:21:00Z")
        assert get_vial(vial["id"])["status"] == "DECAYED", "sweep: 9.937 < 10 floor"
        poss2 = get_license(ctx["license"]["id"])["current_possession_mbq"]
        assert poss2 == pytest.approx(1866.066, abs=0.01), (
            "vial excluded; delivery 99 min before its reference time"
        )


class TestWasteClearance:
    def test_certify_before_clearable_instant_rejected(self, api):
        """PRD §3.7: "Sealing stamps `sealed_at` from the clock, ... computes
        `clearable_after_at` as the sealing instant plus ten half-lives of the
        container's isotope..." and "The current clock instant must be at or
        after `clearable_after_at`, otherwise `ERR_WASTE_CLEARANCE_TOO_EARLY`
        (HTTP 409) — the boundary is inclusive, so certifying exactly at the
        clearable instant is permitted."

        Sealed 08:00 -> clearable 2026-08-02T02:20:00Z; certification at 02:19
        is one minute early.

        Design: Corner/validations/waste_certify_too_early_rejected
        """
        set_clock("2026-08-01T08:00:00Z")
        iso = create_isotope()
        room = create_room(name="Waste-Store")
        container = create_container(iso["id"], room["id"])
        sealed = validate_success(
            api.seal_waste_container(
                container["id"],
                {"expected_container_version": container["version"]},
                make_rso_headers("rso-1"),
            ),
            200,
        )
        assert instants_equal(sealed["clearable_after_at"], "2026-08-02T02:20:00Z")

        set_clock("2026-08-02T02:19:00Z")
        res = api.certify_waste_container_clearance(container["id"], make_rso_headers("rso-2"))
        validate_error(res, "ERR_WASTE_CLEARANCE_TOO_EARLY", expected_status=409)

    def test_certify_without_passing_survey_rejected(self, api):
        """PRD §3.7: "And the latest radiation survey of the storage room
        recorded at or after `sealed_at` must have result `PASS`, otherwise
        `ERR_SURVEY_REQUIRED`."

        Timing (exactly ten half-lives) and activity (0.010 <= 0.05) both pass,
        but no survey exists.

        Design: Corner/validations/waste_certify_requires_passing_survey
        """
        ctx = setup_sealed_container_with_decayed_vial()  # sealed 10:21
        set_clock("2026-08-02T04:41:00Z")  # exactly clearable_after_at
        res = api.certify_waste_container_clearance(
            ctx["container"]["id"], make_rso_headers("rso-2")
        )
        validate_error(res, "ERR_SURVEY_REQUIRED", expected_status=409)

    def test_certify_with_excess_activity_rejected(self, api):
        """PRD §3.7: "The container's `current_activity_mbq` must be at or below
        0.05 MBq, otherwise `ERR_CLEARANCE_ACTIVITY_EXCEEDED` (HTTP 409)."

        Intake 110.000 sealed at 10:20; the clearable instant is ten
        half-lives later, 10:20 + 1100 min = 04:40 next day. At 05:00
        (timing inclusive-satisfied) the decayed activity is still above
        0.05 MBq.

        Design: Corner/errors/clearance_activity_exceeded_rejected
        """
        ctx = setup_sealed_container_from_administered_vial()  # sealed 10:20, intake 110.000
        assert instants_equal(ctx["container"]["clearable_after_at"], "2026-08-02T04:40:00Z")
        set_clock("2026-08-02T05:00:00Z")
        res = api.certify_waste_container_clearance(
            ctx["container"]["id"], make_rso_headers("rso-2")
        )
        validate_error(res, "ERR_CLEARANCE_ACTIVITY_EXCEEDED", expected_status=409)
        assert get_container(ctx["container"]["id"])["status"] == "SEALED"

    def test_clearance_succeeds_at_ten_half_lives(self, api):
        """PRD §3.7: "Once `SEALED`, `current_activity_mbq` is computed as the
        frozen `intake_activity_mbq` multiplied by one-half raised to the power
        of the whole minutes elapsed since sealing divided by the half-life in
        minutes, rounded half-up to three decimal places." and "On success,
        `certified_at` is stamped and `certified_by_user_id` recorded, the
        container moves to `CLEARED`, and it exits the possession ledger."

        Sealed 10:21 with intake 9.937 (a 20.000 MBq vial decayed 111 minutes);
        at 2026-08-02T04:41 (exactly ten half-lives) the activity rounds to
        0.010 <= 0.05; a PASS survey is on record; the certifier differs from
        the sealer.

        Design: Corner/calculations/waste_clearance_success_at_ten_half_lives
        """
        ctx = setup_sealed_container_with_decayed_vial()
        assert ctx["vial"]["residual_activity_mbq"] == pytest.approx(9.937, abs=1e-6)
        assert ctx["container"]["intake_activity_mbq"] == pytest.approx(9.937, abs=1e-6)

        set_clock("2026-08-02T04:41:00Z")
        sealed_now = get_container(ctx["container"]["id"])
        assert sealed_now["status"] == "SEALED"
        assert sealed_now["current_activity_mbq"] == pytest.approx(0.010, abs=1e-9), (
            "SEALED formula: 9.937 / 2^10 rounds to 0.010"
        )
        record_survey(ctx["room"]["id"], "PASS", "rso-1", ambient_dose_rate_usv_h=0.3)
        cleared = validate_success(
            api.certify_waste_container_clearance(
                ctx["container"]["id"], make_rso_headers("rso-2")
            ),
            200,
        )
        assert cleared["status"] == "CLEARED"
        assert cleared["certified_by_user_id"] == "rso-2"

        possession = get_license(ctx["license"]["id"])["current_possession_mbq"]
        assert possession == pytest.approx(0.000, abs=1e-9), (
            "container CLEARED, vial DISPOSED, delivery RECEIVED: nothing counts"
        )


class TestContainerSealOcc:
    def test_stale_seal_version_rejected(self, api):
        """PRD §2.8: "`POST /nuclear-medicine/waste-containers/{id}/seal`
        requires `expected_container_version` carrying the client's last
        observed `version` of the target container; a mismatch is likewise
        rejected with `ERR_STALE_VERSION` (HTTP 412)..." and PRD §3.7: "Sealing
        stamps `sealed_at` from the clock, records `sealed_by_user_id` from the
        caller's `X-User-ID`, computes `clearable_after_at` as the sealing
        instant plus ten half-lives of the container's isotope, freezes
        `intake_activity_mbq` at its seal-time value, and increments the
        container's `version` by one."

        Two strictly sequential seals carrying the same captured version: the
        first seals and increments the version; the second is rejected 412.

        Design: Corner/complexity_layers/occ_container_seal_stale_version
        """
        set_clock("2026-08-01T08:00:00Z")
        iso = create_isotope()
        room = create_room(name="Waste-Store")
        container = create_container(iso["id"], room["id"])
        observed_version = container["version"]

        sealed = validate_success(
            api.seal_waste_container(
                container["id"],
                {"expected_container_version": observed_version},
                make_rso_headers("rso-1"),
            ),
            200,
        )
        assert sealed["status"] == "SEALED"
        assert sealed["version"] == observed_version + 1, "version increments by one"
        assert instants_equal(sealed["sealed_at"], "2026-08-01T08:00:00Z")
        assert instants_equal(sealed["clearable_after_at"], "2026-08-02T02:20:00Z")

        stale = api.seal_waste_container(
            container["id"],
            {"expected_container_version": observed_version},
            make_rso_headers("rso-1"),
        )
        validate_error(stale, "ERR_STALE_VERSION", expected_status=412)
