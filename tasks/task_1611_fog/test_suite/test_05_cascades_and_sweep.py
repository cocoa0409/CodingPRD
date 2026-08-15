"""Cross-entity state gates, transitive cascades, and the compliance sweep."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_interceptor,
    create_and_permit_hauler,
    create_disposal_record,
    create_establishment,
    create_failing_inspection,
    create_hauler,
    create_inspection,
    create_manifest,
    create_variance,
    get_establishment,
    get_open_violation,
    get_success_data,
    set_clock,
    setup_pumping_chain,
    setup_submitted_manifest,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestManifestVerifyHaulerGate:
    def test_manifest_verify_requires_permitted_hauler(self, api):
        """PRD: "the named hauler must currently be `PERMITTED`
        (`ERR_HAULER_NOT_PERMITTED`)"
        PRD: "A verified manifest moves to `VERIFIED`, sets the
        establishment's `last_verified_pump_at` to the manifest's `pump_date`,
        and recomputes the establishment's posture"

        Design: Difficulty/cross_entity_state_dependency/manifest_verify_requires_permitted_hauler
        """
        # The hauler is registered but never permitted (APPLIED). Suspending
        # a PERMITTED hauler would cascade-reject its SUBMITTED manifests
        # (PRD: "suspension cascades immediately"), destroying the SUBMITTED
        # precondition this gate is evaluated from; an APPLIED hauler leaves
        # the manifest SUBMITTED while still failing the PERMITTED gate.
        est, interceptor, _permitted = setup_pumping_chain(
            establishment_name="Gate Diner", hauler_name="Gate Haul",
            permit_number="PN-GATE")
        hauler = create_hauler(name="Gate Haul U", permit_number="PN-GATEU")
        manifest = create_manifest(est["id"], interceptor["id"], hauler["id"],
                                   pump_date="2026-08-02T00:00:00Z",
                                   pumped_volume_gal=2000)

        resp = api.verify_pump_manifest(manifest["id"], INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_HAULER_NOT_PERMITTED, 409)

        # Once the hauler is permitted and its disposal is on file, the same
        # manifest verifies and the pump baseline moves to its pump_date.
        get_success_data(api.permit_hauler(hauler["id"], ADMIN))
        create_disposal_record(hauler["id"], manifest["id"],
                               disposed_volume_gal=2000,
                               disposal_site_name="Site B",
                               disposed_at="2026-08-02T12:00:00Z")
        verified = validate_success(api.verify_pump_manifest(manifest["id"],
                                                             INSPECTOR))
        assert verified["status"] == "VERIFIED", (
            "After permitting the same manifest verifies"
        )
        est_after = get_establishment(est["id"])
        assert est_after["last_verified_pump_at"].startswith("2026-08-02"), (
            f"last_verified_pump_at takes the manifest pump_date, got "
            f"{est_after['last_verified_pump_at']}"
        )

    def test_manifest_verify_happy_path_sets_pump_baseline(self, api):
        """PRD: "A verified manifest moves to `VERIFIED`, sets the
        establishment's `last_verified_pump_at` to the manifest's `pump_date`,
        and recomputes the establishment's posture"
        PRD: "Four checks run in a fixed sequence, and the first failure ends
        the review: the named hauler must currently be `PERMITTED`"

        Design: Difficulty/cross_entity_state_dependency/manifest_verify_requires_permitted_hauler
        """
        est, interceptor, hauler, manifest = setup_submitted_manifest(
            pump_date="2026-08-03T00:00:00Z", pumped_volume_gal=1800,
            establishment_name="Gate Annex", hauler_name="Gate Haul 2",
            permit_number="PN-GATE2")
        create_disposal_record(hauler["id"], manifest["id"],
                               disposed_volume_gal=1800)
        assert get_establishment(est["id"])["last_verified_pump_at"] is None
        verified = validate_success(api.verify_pump_manifest(manifest["id"],
                                                             INSPECTOR))
        assert verified["status"] == "VERIFIED"
        after = get_establishment(est["id"])
        assert after["last_verified_pump_at"].startswith("2026-08-03")
        assert after["compliance_status"] == "COMPLIANT"


class TestVarianceApprovalPostureGate:
    def test_variance_approve_blocked_when_establishment_suspended(self, api):
        """PRD: "The establishment's `compliance_status` must not be
        `SUSPENDED` (`ERR_ESTABLISHMENT_SUSPENDED`, HTTP 409)."
        PRD: "`SUSPENDED` whenever any violation of the establishment stands
        at `CITATION`"

        Design: Difficulty/cross_entity_state_dependency/variance_approve_blocked_when_establishment_suspended
        """
        est = create_establishment(name="Suspended Steakhouse",
                                   street_address="80 F Blvd",
                                   seating_capacity=200, fryer_count=3,
                                   cuisine_profile="HIGH_GREASE")
        # 4 CRITICAL = 80 deductions -> score 20, severity CRITICAL,
        # cure_deadline 2026-08-01 + 3d = 2026-08-04.
        create_inspection(est["id"], [
            {"category": "GREASE_TRAP_MAINTENANCE", "severity": "CRITICAL"},
            {"category": "RECORD_KEEPING", "severity": "CRITICAL"},
            {"category": "STRUCTURAL", "severity": "CRITICAL"},
            {"category": "BMP_PRACTICES", "severity": "CRITICAL"},
        ])
        violation = get_open_violation(est["id"])
        set_clock("2026-08-04T00:00:00Z")
        get_success_data(api.escalate_violation(violation["id"], OFFICER))
        assert get_establishment(est["id"])["compliance_status"] == "SUSPENDED"

        # Variance creation is not posture-gated; approval is.
        variance = create_variance(est["id"], scope="PUMPING_FREQUENCY",
                                   requested_frequency_days=120,
                                   justification="late request")
        assert variance["status"] == "UNDER_REVIEW"
        fresh = get_establishment(est["id"])
        resp = api.approve_variance_request(variance["id"], fresh["version"],
                                            OFFICER)
        validate_error(resp, ApiErrorId.ERR_ESTABLISHMENT_SUSPENDED, 409)
        current = validate_success(api.get_variance_request(variance["id"],
                                                            OFFICER))
        assert current["status"] == "UNDER_REVIEW"
        assert get_establishment(est["id"])["compliance_status"] == "SUSPENDED"

    def test_variance_approve_succeeds_when_establishment_compliant(self, api):
        """PRD: "The establishment's `compliance_status` must not be
        `SUSPENDED` (`ERR_ESTABLISHMENT_SUSPENDED`, HTTP 409)."
        PRD: "On approval the server records `approved_by_user_id` and stamps
        `decided_at`; for the `PUMPING_FREQUENCY` scope it also writes
        `requested_frequency_days` into the establishment's
        `variance_override_frequency_days`, which recomputes
        `pumping_frequency_days`; the establishment's `version` advances by
        one, and its posture is recomputed"

        Design: Difficulty/cross_entity_state_dependency/variance_approve_blocked_when_establishment_suspended
        """
        est = create_establishment(name="Compliant Kitchen",
                                   street_address="81 F Blvd")
        assert est["compliance_status"] == "COMPLIANT"
        variance = create_variance(est["id"], scope="PUMPING_FREQUENCY",
                                   requested_frequency_days=120)
        fresh = get_establishment(est["id"])
        approved = validate_success(api.approve_variance_request(
            variance["id"], fresh["version"], OFFICER))
        assert approved["status"] == "APPROVED"
        after = get_establishment(est["id"])
        assert after["variance_override_frequency_days"] == 120
        assert after["pumping_frequency_days"] == 120, (
            "The override replaces the risk-table value"
        )
        assert after["version"] == fresh["version"] + 1


class TestHaulerMismatchCascade:
    def test_manifest_rejection_suspends_hauler_and_orphans_manifests(self, api):
        """PRD: "Rejection carries teeth when the reason is
        `DISPOSAL_MISMATCH`: the hauler's `mismatch_count` increments by one,
        and a hauler whose count thereby reaches 3 immediately transitions
        from `PERMITTED` to `SUSPENDED`, which in turn cascades a
        `HAULER_SUSPENDED` rejection onto every other still-`SUBMITTED`
        manifest naming that hauler."

        Design: Difficulty/transitive_cascade/manifest_rejection_suspends_hauler_and_orphans_manifests
        """
        e1 = create_establishment(name="E1 Diner", street_address="20 First St",
                                  seating_capacity=200, fryer_count=3,
                                  cuisine_profile="HIGH_GREASE")
        e2 = create_establishment(name="E2 Diner",
                                  street_address="21 Second St",
                                  seating_capacity=200, fryer_count=3,
                                  cuisine_profile="HIGH_GREASE")
        i1 = create_active_interceptor(e1["id"], 600)
        i2 = create_active_interceptor(e2["id"], 600)
        hauler = create_and_permit_hauler(name="Cascade Haul",
                                          permit_number="PN-CAS")
        m1 = create_manifest(e1["id"], i1["id"], hauler["id"],
                             pump_date="2026-08-01T00:00:00Z",
                             pumped_volume_gal=1500)
        m2 = create_manifest(e1["id"], i1["id"], hauler["id"],
                             pump_date="2026-08-02T00:00:00Z",
                             pumped_volume_gal=1500)
        m3 = create_manifest(e2["id"], i2["id"], hauler["id"],
                             pump_date="2026-08-01T00:00:00Z",
                             pumped_volume_gal=1500)
        m4 = create_manifest(e2["id"], i2["id"], hauler["id"],
                             pump_date="2026-08-02T00:00:00Z",
                             pumped_volume_gal=1500)

        for manifest in (m1, m2, m3):
            get_success_data(api.reject_pump_manifest(
                manifest["id"], "DISPOSAL_MISMATCH", INSPECTOR))

        hauler_after = validate_success(api.get_hauler(hauler["id"], ADMIN))
        assert hauler_after["mismatch_count"] == 3
        assert hauler_after["status"] == "SUSPENDED", (
            "Auto-transition at threshold 3 — no suspend endpoint was called"
        )
        orphan = validate_success(api.get_pump_manifest(m4["id"], INSPECTOR))
        assert orphan["status"] == "REJECTED", (
            "The orphan cascade rejects still-SUBMITTED manifests"
        )
        assert orphan["reject_reason"] == "HAULER_SUSPENDED"

    def test_manual_suspend_cascades_to_submitted_manifests(self, api):
        """PRD: "Either way, suspension cascades immediately: every pump
        manifest still in `SUBMITTED` status that names the hauler is rejected
        with `reject_reason` `HAULER_SUSPENDED`."

        Design: Difficulty/transitive_cascade/manifest_rejection_suspends_hauler_and_orphans_manifests
        """
        est, interceptor, hauler, manifest = setup_submitted_manifest(
            establishment_name="Cascade Manual", hauler_name="Cascade Haul 2",
            permit_number="PN-CAS2")
        get_success_data(api.suspend_hauler(hauler["id"], OFFICER))
        cascaded = validate_success(api.get_pump_manifest(manifest["id"],
                                                          INSPECTOR))
        assert cascaded["status"] == "REJECTED"
        assert cascaded["reject_reason"] == "HAULER_SUSPENDED"


class TestSweepCascade:
    def test_sweep_escalation_suspends_establishment_and_denies_variances(self, api):
        """PRD: "A sweep auto-escalates every `NOTICED` violation whose
        `cure_deadline` has been reached — that is, at or before the current
        clock — to `CITATION`, applying the same severity-based fine, the same
        `escalated_at` stamping, and the same posture cascade, variance
        denials included, as a manual escalation."
        PRD: "Entering `SUSPENDED` carries an immediate consequence beyond the
        label: every variance request of that establishment currently
        `UNDER_REVIEW` or `INFO_REQUESTED` is denied in the same motion"

        Design: Difficulty/transitive_cascade/sweep_escalation_suspends_establishment_and_denies_variances
        """
        est = create_establishment(name="Sweep Bistro",
                                   street_address="30 Third St",
                                   seating_capacity=200, fryer_count=3,
                                   cuisine_profile="HIGH_GREASE")
        variance = create_variance(est["id"], scope="INTERCEPTOR_SIZE",
                                   justification="space constraints")
        # Failing inspection at the default clock: severity MAJOR, deadline
        # 2026-08-15.
        create_failing_inspection(est["id"])
        violation = get_open_violation(est["id"])
        set_clock("2026-08-15T00:00:00Z")

        sweep = get_success_data(api.run_sweep(ADMIN))
        assert violation["id"] in sweep["escalated_violation_ids"]

        viol_after = validate_success(api.get_violation(violation["id"],
                                                        INSPECTOR))
        assert viol_after["status"] == "CITATION"
        assert viol_after["fine_cents"] == 50000, "MAJOR fine"

        est_after = get_establishment(est["id"])
        assert est_after["compliance_status"] == "SUSPENDED"

        var_after = validate_success(api.get_variance_request(variance["id"],
                                                              OFFICER))
        assert var_after["status"] == "DENIED", (
            "Auto-denied by the SUSPENDED cascade — no deny endpoint was called"
        )
        assert var_after["decided_at"] is not None
        assert var_after["approved_by_user_id"] is None

    def test_sweep_leaves_fresh_violation_untouched(self, api):
        """PRD: "A sweep auto-escalates every `NOTICED` violation whose
        `cure_deadline` has been reached — that is, at or before the current
        clock — to `CITATION`"
        PRD: "returns two lists: the identifiers of the violations it
        escalated, in `escalated_violation_ids`, and the identifiers of the
        establishments it found delinquent, in `delinquent_establishment_ids`."

        Design: Difficulty/transitive_cascade/sweep_escalation_suspends_establishment_and_denies_variances
        """
        est = create_establishment(name="Fresh Bistro",
                                   street_address="31 Third St",
                                   seating_capacity=200, fryer_count=3,
                                   cuisine_profile="HIGH_GREASE")
        # Failing inspection at the default clock: MAJOR deadline 2026-08-15.
        create_failing_inspection(est["id"])
        violation = get_open_violation(est["id"])
        # The clock is still 2026-08-01: the deadline has NOT been reached.
        sweep = get_success_data(api.run_sweep(ADMIN))
        assert violation["id"] not in sweep["escalated_violation_ids"], (
            "The sweep escalates only violations whose cure_deadline has been reached"
        )
        after = validate_success(api.get_violation(violation["id"], INSPECTOR))
        assert after["status"] == "NOTICED"

    def test_sweep_marks_delinquent_establishment(self, api):
        """PRD: "the establishment is overdue when the logical clock is
        strictly later than the baseline plus `pumping_frequency_days`."
        PRD: "The sweep then recomputes pumping delinquency for every
        establishment, and returns two lists: the identifiers of the
        violations it escalated, in `escalated_violation_ids`, and the
        identifiers of the establishments it found delinquent, in
        `delinquent_establishment_ids`."
        PRD: "otherwise `DELINQUENT` whenever `pumping_overdue` holds"

        Design: Corner/endpoints/c_sweep_marks_delinquent_establishment
        """
        # The clock only moves forward from its pinned 2026-08-01T00:00:00Z
        # start, so the establishment is created at that instant.
        est = create_establishment(name="Delinquent Deli",
                                   street_address="31 Y St")
        assert est["pumping_frequency_days"] == 365
        # 2027-08-02 is strictly later than 2026-08-01 + 365d = 2027-08-01.
        set_clock("2027-08-02T00:00:00Z")

        sweep = get_success_data(api.run_sweep(ADMIN))
        assert est["id"] in sweep["delinquent_establishment_ids"]

        after = get_establishment(est["id"])
        assert after["pumping_overdue"] is True
        assert after["compliance_status"] == "DELINQUENT"


class TestPumpingDelinquencyLenses:
    def test_pumping_delinquency_forward_vs_chronological(self, api):
        """PRD: "Because the baseline is the *most recent* verified pump, a
        single fresh verification resets it: an establishment that missed
        windows long ago but pumped recently is not overdue."
        PRD: "Count every window that has fully elapsed — its end at or before
        the current clock — in which no `VERIFIED` manifest's `pump_date`
        falls. A late pump satisfies only the window it actually lands in, so
        the same history can legitimately yield a `missed_pump_windows` of one
        or more while `pumping_overdue` is false."

        Design: Difficulty/dual_variant_calc/pumping_delinquency_forward_vs_chronological
        """
        # The clock starts pinned at 2026-08-01T00:00:00Z and only moves
        # forward, so the establishment's created_at is 2026-08-01.
        est = create_establishment(name="Divergence Diner",
                                   street_address="2 Elm St",
                                   seating_capacity=200, fryer_count=3,
                                   cuisine_profile="HIGH_GREASE")
        assert est["pumping_frequency_days"] == 90
        interceptor = create_active_interceptor(est["id"], 600)
        hauler = create_and_permit_hauler(name="Haul Co", permit_number="PN-1")

        # One VERIFIED pump at 2026-12-25: lands in window W2
        # [2026-10-30, 2027-01-28); window W1 [2026-08-01, 2026-10-30) is
        # empty.
        set_clock("2026-12-25T00:00:00Z")
        manifest = create_manifest(est["id"], interceptor["id"], hauler["id"],
                                   pump_date="2026-12-25T00:00:00Z",
                                   pumped_volume_gal=2000)
        create_disposal_record(hauler["id"], manifest["id"],
                               disposed_volume_gal=2000,
                               disposal_site_name="Site A",
                               disposed_at="2026-12-25T12:00:00Z")
        get_success_data(api.verify_pump_manifest(manifest["id"], INSPECTOR))

        set_clock("2027-02-14T00:00:00Z")
        get_success_data(api.run_sweep(ADMIN))

        after = get_establishment(est["id"])
        # Forward-looking lens: baseline 2026-12-25 + 90d = 2027-03-25 >
        # 2027-02-14, so not overdue.
        assert after["pumping_overdue"] is False
        # Chronological lens: W1 fully elapsed and empty; W2 satisfied by the
        # 2026-12-25 pump; W3 ends 2027-04-28, not yet elapsed.
        assert after["missed_pump_windows"] == 1
        assert after["compliance_status"] == "COMPLIANT"

    def test_overdue_at_strictly_after_boundary(self, api):
        """PRD: "take the establishment's pumping baseline — its
        `last_verified_pump_at` when one is set, otherwise its `created_at` —
        and the establishment is overdue when the logical clock is strictly
        later than the baseline plus `pumping_frequency_days`. Sitting exactly
        at the deadline instant is not yet overdue."

        Design: Difficulty/dual_variant_calc/pumping_delinquency_forward_vs_chronological
        """
        # The clock starts pinned at 2026-08-01T00:00:00Z and only moves
        # forward, so the establishment's created_at is 2026-08-01.
        est = create_establishment(name="Boundary Bistro",
                                   street_address="3 Elm St",
                                   seating_capacity=200, fryer_count=3,
                                   cuisine_profile="HIGH_GREASE")
        assert est["pumping_frequency_days"] == 90
        # created_at 2026-08-01 + 90 days = 2026-10-30: exactly at the
        # deadline is NOT overdue (strict >).
        set_clock("2026-10-30T00:00:00Z")
        sweep1 = get_success_data(api.run_sweep(ADMIN))
        at_deadline = get_establishment(est["id"])
        assert at_deadline["pumping_overdue"] is False, (
            "Sitting exactly at the deadline instant is not yet overdue"
        )
        assert est["id"] not in sweep1["delinquent_establishment_ids"]

        # One second past the deadline is overdue.
        set_clock("2026-10-30T00:00:01Z")
        sweep2 = get_success_data(api.run_sweep(ADMIN))
        past = get_establishment(est["id"])
        assert past["pumping_overdue"] is True
        assert est["id"] in sweep2["delinquent_establishment_ids"]
